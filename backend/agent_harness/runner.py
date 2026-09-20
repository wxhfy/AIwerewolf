from __future__ import annotations

import time
from typing import Any
from typing import Protocol

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessResult
from backend.agent_harness.contracts import HarnessStep
from backend.agent_harness.contracts import PlannerContext
from backend.agent_harness.contracts import ToolResult
from backend.agent_harness.events import EventWriter
from backend.agent_harness.events import HarnessSession
from backend.agent_harness.policy import CapabilityPolicy
from backend.agent_harness.policy import PolicyViolation
from backend.agent_harness.skills import SkillRegistry
from backend.agent_harness.tools import ToolGateway
from backend.agent_harness.validation import ActionValidationError
from backend.agent_harness.validation import resolve_action


class HarnessPlanner(Protocol):
    """Model adapter. It receives immutable data contracts, never service objects."""

    def next_step(self, request: DecisionRequest, context: PlannerContext) -> HarnessStep: ...


class AgentHarness:
    """Event-sourced, bounded runtime for one environment decision request."""

    def __init__(
        self,
        planner: HarnessPlanner,
        *,
        skills: SkillRegistry | None = None,
        tools: ToolGateway | None = None,
        policy: CapabilityPolicy | None = None,
        event_writer: EventWriter | None = None,
    ) -> None:
        self.planner = planner
        self.skills = skills or SkillRegistry()
        self.tools = tools or ToolGateway()
        self.policy = policy or CapabilityPolicy()
        self.event_writer = event_writer

    def run(self, request: DecisionRequest) -> HarnessResult:
        started = time.monotonic()
        session = HarnessSession(self.event_writer)
        catalog = self.skills.catalog(request)
        schemas = self.tools.schemas(self.policy, request)
        loaded = []
        tool_results: list[ToolResult] = []
        seen_call_ids: set[str] = set()
        session.append(
            "run.started",
            step=0,
            payload={
                "request": self._request_snapshot(request),
                "skill_catalog": [{"name": skill.name, "description": skill.description} for skill in catalog],
                "tool_schemas": list(schemas),
            },
        )

        for step_number in range(1, request.budget.max_steps + 1):
            if self._deadline_exceeded(started, request):
                return self._failed(session, loaded, tool_results, step_number, "Harness deadline exceeded")

            session.append("step.started", step=step_number)
            try:
                session.append("model.requested", step=step_number)
                step = self.planner.next_step(
                    request,
                    PlannerContext(
                        step=step_number,
                        skill_catalog=catalog,
                        loaded_skills=tuple(loaded),
                        tool_schemas=schemas,
                        tool_results=tuple(tool_results),
                    ),
                )
                session.append("model.responded", step=step_number, payload=self._step_snapshot(step))

                if step.kind == "load_skill" and step.skill_call is not None:
                    if len(loaded) >= request.budget.max_skill_loads:
                        raise PolicyViolation("Skill load budget exceeded")
                    if any(skill.name == step.skill_call.name for skill in loaded):
                        raise PolicyViolation(f"Skill is already loaded: {step.skill_call.name}")
                    session.append(
                        "skill.load.requested",
                        step=step_number,
                        payload={"name": step.skill_call.name},
                    )
                    try:
                        skill = self.skills.load(step.skill_call.name, request)
                    except PolicyViolation as exc:
                        session.append(
                            "skill.load.failed",
                            step=step_number,
                            payload={"name": step.skill_call.name, "error": str(exc)},
                        )
                        raise
                    loaded.append(skill)
                    session.append(
                        "skill.loaded",
                        step=step_number,
                        payload={"name": skill.name, "instructions": skill.instructions},
                    )
                    session.append("step.completed", step=step_number)
                    continue

                if step.kind == "tool" and step.tool_call is not None:
                    if len(tool_results) >= request.budget.max_tool_calls:
                        raise PolicyViolation("Tool call budget exceeded")
                    if not step.tool_call.call_id or step.tool_call.call_id in seen_call_ids:
                        raise PolicyViolation("Tool call IDs must be non-empty and unique within a run")
                    seen_call_ids.add(step.tool_call.call_id)
                    session.append(
                        "tool.call",
                        step=step_number,
                        payload={
                            "call_id": step.tool_call.call_id,
                            "name": step.tool_call.name,
                            "arguments": step.tool_call.arguments,
                        },
                    )
                    try:
                        result = self.tools.invoke(step.tool_call, self.policy, request)
                    except PolicyViolation as exc:
                        session.append(
                            "tool.result",
                            step=step_number,
                            payload={
                                "call_id": step.tool_call.call_id,
                                "name": step.tool_call.name,
                                "ok": False,
                                "content": {},
                                "error": str(exc),
                            },
                        )
                        raise
                    tool_results.append(result)
                    session.append(
                        "tool.result",
                        step=step_number,
                        payload={
                            "call_id": result.call_id,
                            "name": result.name,
                            "ok": result.ok,
                            "content": result.content,
                            "error": result.error,
                        },
                    )
                    session.append("step.completed", step=step_number)
                    continue

                if step.kind == "select_action" and step.action_selection is not None:
                    session.append(
                        "action.proposed",
                        step=step_number,
                        payload={
                            "option_id": step.action_selection.option_id,
                            "response": step.action_selection.response,
                            "reasoning": step.action_selection.reasoning,
                            "metadata": step.action_selection.metadata,
                        },
                    )
                    action = resolve_action(request, step.action_selection)
                    session.append(
                        "action.accepted",
                        step=step_number,
                        payload={
                            "option_id": action.option_id,
                            "action_type": action.action_type,
                            "parameters": action.parameters,
                            "response": action.response,
                        },
                    )
                    session.append("step.completed", step=step_number)
                    session.append("run.completed", step=step_number)
                    return HarnessResult(
                        status="completed",
                        action=action,
                        events=session.events,
                        loaded_skills=tuple(skill.name for skill in loaded),
                        tool_calls=len(tool_results),
                    )

                raise RuntimeError("Planner returned an invalid harness step")
            except (PolicyViolation, ActionValidationError) as exc:
                session.append("request.rejected", step=step_number, payload={"error": str(exc)})
                session.append("step.completed", step=step_number)
                session.append("run.rejected", step=step_number, payload={"error": str(exc)})
                return HarnessResult(
                    status="rejected",
                    action=None,
                    events=session.events,
                    loaded_skills=tuple(skill.name for skill in loaded),
                    tool_calls=len(tool_results),
                    error=str(exc),
                )
            except Exception as exc:
                return self._failed(session, loaded, tool_results, step_number, str(exc))

        return self._failed(
            session,
            loaded,
            tool_results,
            request.budget.max_steps,
            "Harness step budget exhausted",
        )

    @staticmethod
    def _deadline_exceeded(started: float, request: DecisionRequest) -> bool:
        return (time.monotonic() - started) * 1000 >= request.budget.deadline_ms

    @staticmethod
    def _request_snapshot(request: DecisionRequest) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "environment_id": request.environment_id,
            "episode_id": request.episode_id,
            "actor": {
                "actor_id": request.actor.actor_id,
                "agent_definition_id": request.actor.agent_definition_id,
            },
            "decision_point": {
                "kind": request.decision_point.kind,
                "sequence": request.decision_point.sequence,
                "schema_version": request.decision_point.schema_version,
                "simultaneous_group_id": request.decision_point.simultaneous_group_id,
            },
            "information_state": {
                "schema_id": request.information_state.schema_id,
                "schema_version": request.information_state.schema_version,
                "observation": request.information_state.observation,
                "visible_history": list(request.information_state.visible_history),
                "private_memory": list(request.information_state.private_memory),
            },
            "action_space": [
                {
                    "option_id": option.option_id,
                    "action_type": option.action_type,
                    "parameters": option.parameters,
                    "response_schema": option.response_schema,
                    "model_hint": option.model_hint,
                }
                for option in request.action_space.options
            ],
            "memory_scope": {
                "namespace": request.memory_scope.namespace,
                "episode_id": request.memory_scope.episode_id,
                "actor_id": request.memory_scope.actor_id,
            },
            "skill_scope": sorted(request.skill_scope),
            "tool_scope": sorted(request.tool_scope),
            "policy_tags": sorted(request.policy_tags),
            "agent_profile": request.agent_profile,
            "domain_metadata": request.domain_metadata,
            "budget": {
                "max_steps": request.budget.max_steps,
                "max_tool_calls": request.budget.max_tool_calls,
                "max_skill_loads": request.budget.max_skill_loads,
                "max_output_tokens": request.budget.max_output_tokens,
                "deadline_ms": request.budget.deadline_ms,
            },
        }

    @staticmethod
    def _step_snapshot(step: HarnessStep) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": step.kind}
        if step.skill_call is not None:
            payload["skill_call"] = {"name": step.skill_call.name}
        if step.tool_call is not None:
            payload["tool_call"] = {
                "call_id": step.tool_call.call_id,
                "name": step.tool_call.name,
                "arguments": step.tool_call.arguments,
            }
        if step.action_selection is not None:
            payload["action_selection"] = {
                "option_id": step.action_selection.option_id,
                "response": step.action_selection.response,
                "reasoning": step.action_selection.reasoning,
                "metadata": step.action_selection.metadata,
            }
        return payload

    @staticmethod
    def _failed(session, loaded, tool_results, step: int, error: str) -> HarnessResult:
        session.append("run.failed", step=step, payload={"error": error})
        return HarnessResult(
            status="failed",
            action=None,
            events=session.events,
            loaded_skills=tuple(skill.name for skill in loaded),
            tool_calls=len(tool_results),
            error=error,
        )
