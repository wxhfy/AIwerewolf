from __future__ import annotations

import json
import re
import time
from typing import Any

from backend.agent_harness.contracts import ActionSelection
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessStep
from backend.agent_harness.contracts import PlannerContext
from backend.agent_harness.validation import ActionValidationError
from backend.agent_harness.validation import resolve_action
from backend.domains.werewolf.communication import audit_public_speech
from backend.domains.werewolf.communication import public_communication_policy
from backend.domains.werewolf.strategy import build_strategy_snapshot
from backend.domains.werewolf.strategy import strategy_score_for_option

_DELIBERATIVE_KINDS = {
    "werewolf.witch",
    "werewolf.shoot",
    "werewolf.boom",
    "werewolf.transfer_badge",
}


class LLMActionPlanner:
    """One bounded structured LLM call for a harness decision."""

    def __init__(self, client: Any, *, temperature: float = 0.7) -> None:
        self.client = client
        self.temperature = temperature

    def next_step(self, request: DecisionRequest, context: PlannerContext) -> HarnessStep:
        started = time.monotonic()
        if context.step == 1 and request.decision_point.kind in _DELIBERATIVE_KINDS and request.budget.max_steps > 1:
            try:
                response = self._chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are preparing a high-impact decision in an asymmetric-information game. "
                                "Use only the supplied information. Produce a compact strategic assessment, "
                                "compare the legal options, and do not invent hidden facts."
                            ),
                        },
                        {
                            "role": "user",
                            "content": "AIWEREWOLF_DELIBERATION\n"
                            + json.dumps(self._prompt_payload(request, context), ensure_ascii=False),
                        },
                    ],
                    temperature=min(self.temperature, 0.4),
                    max_tokens=min(500, request.budget.max_output_tokens),
                    remaining_ms=self._remaining(context.remaining_ms, started),
                )
            except Exception as exc:
                return self._fallback_step(request, f"deliberation call failed: {type(exc).__name__}: {exc}")
            return HarnessStep.reflect(self._content(response))

        try:
            response = self._chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are an autonomous actor in an asymmetric-information environment. "
                            "Use only the supplied actor-visible context. You may load one advertised skill or call "
                            "one advertised read-only tool when that capability is available and materially useful. "
                            "For public speech, keep private reasoning out of the speech field: never expose wolf-team "
                            "knowledge, hidden night actions, internal scores, probabilities, raw IDs, or system terms. "
                            "Ground public claims in public evidence. A Seer may deliberately publish their own check. "
                            "If the selected option has no response_schema, return response as an empty object and keep "
                            "reasoning under 80 words. Do not add a speech field to non-speech actions. "
                            "Otherwise select exactly one server-generated option_id. Never invent hidden facts. "
                            "Finish by calling submit_action, or return JSON only: "
                            '{"option_id": string, "response": object, "reasoning": string}.'
                        ),
                    },
                    {
                        "role": "user",
                        "content": "AIWEREWOLF_HARNESS_DECISION\n"
                        + json.dumps(self._prompt_payload(request, context), ensure_ascii=False),
                    },
                ],
                temperature=self.temperature,
                max_tokens=request.budget.max_output_tokens,
                remaining_ms=self._remaining(context.remaining_ms, started),
                **self._tool_arguments(request, context),
            )
        except Exception as exc:
            return self._fallback_step(request, f"model call failed: {type(exc).__name__}: {exc}")

        try:
            control_step = self._control_step_from_response(response, context)
        except Exception as exc:
            return self._fallback_step(request, f"invalid harness control call: {type(exc).__name__}: {exc}")
        if control_step is not None:
            return control_step
        content = self._raw_selection_text(response)
        repair_used = False
        repair_error = ""
        fallback_used = False
        fallback_error = ""
        try:
            selection = self._normalize_selection(request, self._selection_from_response(response))
            resolve_action(request, selection)
        except (RuntimeError, ValueError, json.JSONDecodeError, ActionValidationError) as exc:
            repair_error = str(exc)
            repair_used = True
            try:
                repaired = self._chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Repair an invalid action response. Return JSON only with exactly these fields: "
                                '{"option_id": string, "response": object, "reasoning": string}. '
                                "The option_id must be one of the supplied legal option IDs."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "error": repair_error,
                                    "invalid_output": content[:4000],
                                    "legal_options": [option.option_id for option in request.action_space.options],
                                    "response_schemas": {
                                        option.option_id: option.response_schema
                                        for option in request.action_space.options
                                    },
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    temperature=0.0,
                    max_tokens=min(400, request.budget.max_output_tokens),
                    remaining_ms=self._remaining(context.remaining_ms, started),
                    **self._tool_arguments(request, context, final_only=True),
                )
                content = self._raw_selection_text(repaired)
                response = repaired
                selection = self._normalize_selection(request, self._selection_from_response(repaired))
                resolve_action(request, selection)
            except Exception as exc:
                fallback_used = True
                fallback_error = f"{type(exc).__name__}: {exc}"
                selection = self._fallback_selection(request, repair_error, fallback_error)
                resolve_action(request, selection)
        speech_violations: tuple[str, ...] = ()
        speech_rewritten = False
        if selection.option_id == "talk":
            audit = audit_public_speech(request, str(selection.response.get("speech") or ""))
            speech_violations = audit.violations
            speech = audit.speech
            if not audit.accepted:
                speech = self._fallback_speech(request)
                speech_rewritten = True
            selection = ActionSelection(
                option_id=selection.option_id,
                response={**selection.response, "speech": speech},
                reasoning=selection.reasoning,
                metadata=selection.metadata,
            )
        usage = response.get("usage") if isinstance(response, dict) else {}
        return HarnessStep.select_action(
            ActionSelection(
                option_id=selection.option_id,
                response=selection.response,
                reasoning=selection.reasoning,
                metadata={
                    "raw_text": content,
                    "usage": usage if isinstance(usage, dict) else {},
                    "latency_ms": response.get("_latency_ms") if isinstance(response, dict) else None,
                    "model": str(getattr(self.client, "model", "")),
                    "provider": str(getattr(self.client, "provider", "")),
                    "repair_used": repair_used,
                    "repair_error": repair_error or None,
                    "fallback_used": fallback_used,
                    "fallback_error": fallback_error or None,
                    "speech_policy_violations": list(speech_violations),
                    "speech_rewritten": speech_rewritten,
                    "syntax_recovered": bool(selection.metadata.get("syntax_recovered")),
                },
            )
        )

    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        remaining_ms: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.client.chat_sync(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=False,
            request_timeout_seconds=max(0.1, remaining_ms / 1000),
            **kwargs,
        )

    def _tool_arguments(
        self,
        request: DecisionRequest,
        context: PlannerContext,
        *,
        final_only: bool = False,
    ) -> dict[str, Any]:
        if not bool(getattr(self.client, "supports_tool_calling", False)):
            return {}
        tools = [self._submit_action_tool(request)]
        if not final_only:
            if context.skill_catalog and len(context.loaded_skills) < request.budget.max_skill_loads:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": "load_skill",
                            "description": "Load one advertised trusted strategy skill before deciding.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "enum": [skill.name for skill in context.skill_catalog],
                                    }
                                },
                                "required": ["name"],
                                "additionalProperties": False,
                            },
                        },
                    }
                )
            if len(context.tool_results) < request.budget.max_tool_calls:
                for schema in context.tool_schemas:
                    tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": str(schema["name"]),
                                "description": str(
                                    schema.get("description") or "Read actor-visible derived information."
                                ),
                                "parameters": dict(schema.get("input_schema") or {"type": "object", "properties": {}}),
                            },
                        }
                    )
        choice: str | dict[str, Any] = "auto"
        if len(tools) == 1:
            choice = {"type": "function", "function": {"name": "submit_action"}}
        return {"tools": tools, "tool_choice": choice}

    @staticmethod
    def _submit_action_tool(request: DecisionRequest) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "submit_action",
                "description": "Submit exactly one server-generated legal action.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "option_id": {
                            "type": "string",
                            "enum": [option.option_id for option in request.action_space.options],
                        },
                        "response": {"type": "object"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["option_id", "response", "reasoning"],
                    "additionalProperties": False,
                },
            },
        }

    @staticmethod
    def _remaining(initial_ms: int, started: float) -> int:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        remaining = initial_ms - elapsed_ms
        if remaining < 100:
            raise TimeoutError("Agent decision deadline exhausted during model call")
        return remaining

    @staticmethod
    def _prompt_payload(request: DecisionRequest, context: PlannerContext) -> dict[str, Any]:
        limits = LLMActionPlanner._context_limits(request.decision_point.kind)
        memory = LLMActionPlanner._compact_memory(request.information_state.private_memory, limits)
        source_memory = (request.information_state.private_memory or ({},))[0]
        strategy = build_strategy_snapshot(request, source_memory)
        history = list(request.information_state.visible_history[-limits["visible_history"] :])
        knowledge = list(request.knowledge_context)
        return {
            "context_manifest": {
                "schema_version": "1",
                "layers": [
                    "identity_and_policy",
                    "current_observation",
                    "visible_recent_history",
                    "subjective_memory",
                    "derived_strategy_state",
                    "retrieved_cross_episode_knowledge",
                    "loaded_skills_and_tool_results",
                    "legal_action_space",
                ],
                "limits": {
                    **limits,
                    "remaining_ms": context.remaining_ms,
                    "remaining_steps_including_current": max(0, request.budget.max_steps - context.step + 1),
                },
                "included": {
                    "visible_history": len(history),
                    "private_memory_blocks": len(memory),
                    "knowledge_items": len(knowledge),
                    "loaded_skills": len(context.loaded_skills),
                    "tool_results": len(context.tool_results),
                    "legal_options": len(request.action_space.options),
                },
            },
            "actor": {
                "actor_id": request.actor.actor_id,
                "agent_definition_id": request.actor.agent_definition_id,
            },
            "decision_point": {
                "kind": request.decision_point.kind,
                "sequence": request.decision_point.sequence,
            },
            "information_state": {
                "observation": request.information_state.observation,
                "visible_history": history,
                "private_memory": memory,
            },
            "knowledge_context": knowledge,
            "strategy_state": strategy,
            "prior_reflections": list(context.reflections),
            "capabilities": {
                "available_skills": [
                    {"name": skill.name, "description": skill.description} for skill in context.skill_catalog
                ],
                "loaded_skills": [
                    {"name": skill.name, "instructions": skill.instructions} for skill in context.loaded_skills
                ],
                "available_tools": list(context.tool_schemas),
                "tool_results": [
                    {
                        "call_id": result.call_id,
                        "name": result.name,
                        "ok": result.ok,
                        "content": result.content,
                        "error": result.error,
                    }
                    for result in context.tool_results
                ],
            },
            "action_options": [
                {
                    "option_id": option.option_id,
                    "action_type": option.action_type,
                    "parameters": option.parameters,
                    "response_schema": option.response_schema,
                    "model_hint": option.model_hint,
                }
                for option in request.action_space.options
            ],
            "agent_profile": request.agent_profile,
            "domain_metadata": request.domain_metadata,
            "public_communication_policy": public_communication_policy(request),
        }

    @classmethod
    def _control_step_from_response(
        cls,
        response: dict[str, Any],
        context: PlannerContext,
    ) -> HarnessStep | None:
        try:
            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return None
            call = tool_calls[0]
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            if name == "submit_action":
                return None
            arguments = cls._parse_json_object(str(function.get("arguments") or "{}"))
            if name == "load_skill":
                skill_name = str(arguments.get("name") or "")
                if skill_name not in {skill.name for skill in context.skill_catalog}:
                    raise RuntimeError(f"LLM requested an unavailable skill: {skill_name}")
                return HarnessStep.load_skill(skill_name)
            if name not in {str(schema.get("name") or "") for schema in context.tool_schemas}:
                raise RuntimeError(f"LLM called an unexpected harness tool: {name}")
            call_id = str(call.get("id") or f"tool-{context.step}-{name}")
            return HarnessStep.call_tool(call_id, name, arguments)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError("LLM response contains an invalid harness control call") from exc

    @staticmethod
    def _context_limits(kind: str) -> dict[str, int]:
        if kind in {"werewolf.talk", "werewolf.badge_speech", "werewolf.pk_speech", "werewolf.sheriff_closing"}:
            return {
                "visible_history": 8,
                "beliefs_per_memory": 7,
                "relationships_per_memory": 4,
                "recent_claims_per_memory": 8,
                "evidence_edges_per_memory": 4,
                "retrieved_episodes_per_memory": 2,
            }
        if kind in {"werewolf.vote", "werewolf.badge_election"}:
            return {
                "visible_history": 10,
                "beliefs_per_memory": 8,
                "relationships_per_memory": 5,
                "recent_claims_per_memory": 8,
                "evidence_edges_per_memory": 6,
                "retrieved_episodes_per_memory": 2,
            }
        return {
            "visible_history": 6,
            "beliefs_per_memory": 6,
            "relationships_per_memory": 4,
            "recent_claims_per_memory": 4,
            "evidence_edges_per_memory": 3,
            "retrieved_episodes_per_memory": 2,
        }

    @staticmethod
    def _compact_memory(
        memory_items: tuple[dict[str, Any], ...],
        limits: dict[str, int],
    ) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for item in memory_items:
            compacted.append(
                {
                    "working_memory": list(item.get("working_memory") or []),
                    "beliefs": list(item.get("beliefs") or [])[: limits["beliefs_per_memory"]],
                    "relationships": list(item.get("relationships") or [])[
                        : limits["relationships_per_memory"]
                    ],
                    "affect": item.get("affect") or {},
                    "active_goals": list(item.get("active_goals") or [])[:4],
                    "recent_claims": list(item.get("recent_claims") or [])[
                        -limits["recent_claims_per_memory"] :
                    ],
                    "evidence_graph": list(item.get("evidence_graph") or [])[
                        -limits["evidence_edges_per_memory"] :
                    ],
                    "retrieved_episodes": list(item.get("retrieved_episodes") or [])[
                        : limits["retrieved_episodes_per_memory"]
                    ],
                    "last_action": item.get("last_action") or {},
                }
            )
        return compacted

    @classmethod
    def _selection(cls, content: str) -> ActionSelection:
        try:
            parsed = cls._parse_json_object(content)
        except (RuntimeError, json.JSONDecodeError):
            return cls._partial_selection(content)
        return ActionSelection(
            option_id=str(parsed.get("option_id") or ""),
            response=parsed.get("response") if isinstance(parsed.get("response"), dict) else {},
            reasoning=str(parsed.get("reasoning") or ""),
        )

    @staticmethod
    def _partial_selection(content: str) -> ActionSelection:
        """Recover only complete JSON string fields from a truncated response.

        The recovered option still passes through ``resolve_action`` against the
        environment-owned action space. This never invents an action or target.
        """

        def string_field(name: str) -> str:
            match = re.search(
                rf'"{re.escape(name)}"\s*:\s*("(?:\\.|[^"\\])*")',
                content,
                flags=re.DOTALL,
            )
            if match is None:
                return ""
            try:
                value = json.loads(match.group(1))
            except json.JSONDecodeError:
                return ""
            return str(value)

        option_id = string_field("option_id")
        if not option_id:
            raise RuntimeError("LLM did not return a recoverable option_id")
        speech = string_field("speech")
        response = {"speech": speech} if speech else {}
        reasoning = string_field("reasoning") or "Recovered from a truncated structured response."
        return ActionSelection(
            option_id=option_id,
            response=response,
            reasoning=reasoning,
            metadata={"syntax_recovered": True},
        )

    @classmethod
    def _selection_from_response(cls, response: dict[str, Any]) -> ActionSelection:
        try:
            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                function = tool_calls[0].get("function") or {}
                if function.get("name") != "submit_action":
                    raise RuntimeError("LLM called an unexpected action tool")
                return cls._selection(str(function.get("arguments") or ""))
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError("LLM response does not contain a valid action tool call") from exc
        return cls._selection(cls._content(response))

    @classmethod
    def _raw_selection_text(cls, response: dict[str, Any]) -> str:
        try:
            message = response["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                return str((tool_calls[0].get("function") or {}).get("arguments") or "")
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        return cls._content(response)

    @staticmethod
    def _normalize_selection(request: DecisionRequest, selection: ActionSelection) -> ActionSelection:
        option = next(
            (item for item in request.action_space.options if item.option_id == selection.option_id),
            None,
        )
        if option is None:
            return selection
        if option.response_schema is None:
            return ActionSelection(
                option_id=selection.option_id,
                response={},
                reasoning=selection.reasoning,
                metadata=selection.metadata,
            )
        properties = dict(option.response_schema.get("properties") or {})
        response = {key: value for key, value in selection.response.items() if key in properties}
        return ActionSelection(
            option_id=selection.option_id,
            response=response,
            reasoning=selection.reasoning,
            metadata=selection.metadata,
        )

    @staticmethod
    def _fallback_selection(request: DecisionRequest, initial_error: str, repair_error: str) -> ActionSelection:
        option = LLMActionPlanner._fallback_option(request)
        response: dict[str, Any] = {}
        schema = option.response_schema or {}
        properties = dict(schema.get("properties") or {})
        for field in schema.get("required") or []:
            field_schema = dict(properties.get(field) or {})
            field_type = field_schema.get("type")
            if field_type == "string":
                response[field] = LLMActionPlanner._fallback_speech(request)
            elif field_type == "boolean":
                response[field] = False
            elif field_type == "integer":
                response[field] = int(field_schema.get("minimum") or 0)
            elif field_type == "number":
                response[field] = float(field_schema.get("minimum") or 0.0)
            elif field_type == "array":
                response[field] = []
            else:
                response[field] = {}
        return ActionSelection(
            option_id=option.option_id,
            response=response,
            reasoning=f"Deterministic fallback after invalid model output: {initial_error}; {repair_error}",
        )

    @staticmethod
    def _fallback_option(request: DecisionRequest):
        options = list(request.action_space.options)
        memory = (request.information_state.private_memory or ({},))[0]
        kind = request.decision_point.kind
        role = str(request.domain_metadata.get("role") or "")
        known_wolves = {
            str(item.get("id") or "")
            for item in request.information_state.observation.get("known_wolves") or []
        }

        def target(option):
            return option.parameters.get("target_id") or option.parameters.get("poison_target_id")

        def strategy_rank(option):
            return (strategy_score_for_option(request, memory, target(option)), option.option_id)

        if kind == "werewolf.witch":
            save_only = next((item for item in options if item.action_type == "witch_save"), None)
            if int(request.domain_metadata.get("day") or 0) <= 1 and save_only is not None:
                return save_only
            return next((item for item in options if item.option_id == "witch:hold"), options[0])
        if kind in {
            "werewolf.guard",
            "werewolf.transfer_badge",
            "werewolf.wolf_team_vote",
            "werewolf.vote",
            "werewolf.divine",
            "werewolf.shoot",
            "werewolf.boom",
        }:
            targeted = [option for option in options if target(option)]
            if kind == "werewolf.wolf_team_vote" or (
                kind == "werewolf.vote" and role in {"Werewolf", "WhiteWolfKing"}
            ):
                non_teammates = [option for option in targeted if target(option) not in known_wolves]
                if non_teammates:
                    targeted = non_teammates
            return max(targeted or options, key=strategy_rank)
        return options[0]

    @staticmethod
    def _fallback_speech(request: DecisionRequest) -> str:
        memory = (request.information_state.private_memory or ({},))[0]
        observation = request.information_state.observation
        role = str(request.domain_metadata.get("role") or "")
        known_wolves = {
            str(item.get("id") or "") for item in observation.get("known_wolves") or []
        }
        names = {
            str(item.get("id") or ""): str(item.get("name") or item.get("id") or "")
            for item in observation.get("players") or []
        }

        if role == "Seer":
            for event in reversed(request.information_state.visible_history):
                payload = dict(event.get("payload") or {})
                if event.get("type") != "PRIVATE_INFO" or payload.get("kind") != "seer_result":
                    continue
                target_id = str(payload.get("target_id") or "")
                target_name = str(payload.get("target_name") or names.get(target_id) or "该玩家")
                result = "狼人" if payload.get("is_wolf") else "好人"
                return f"我是预言家，昨晚查验了{target_name}，结果是{result}。请结合后续发言和票型验证我的信息。"

        beliefs = list(memory.get("beliefs") or [])
        public_beliefs = [item for item in beliefs if str(item.get("player_id") or "") not in known_wolves]
        if public_beliefs:
            suspect = max(
                public_beliefs,
                key=lambda item: (
                    float(item.get("wolf_probability") or 0.5),
                    float(item.get("confidence") or 0.0),
                    str(item.get("player_id") or ""),
                ),
            )
            player_id = str(suspect.get("player_id") or "")
            player_name = names.get(player_id) or "一名玩家"
            return f"目前我更怀疑{player_name}。请重点核对他的前后发言、站边和实际投票是否一致。"
        return "目前公开信息还不足，我会继续核对身份声明、站边变化和实际票型，不会无依据下定论。"

    def _fallback_step(self, request: DecisionRequest, error: str) -> HarnessStep:
        selection = self._fallback_selection(request, error, "model unavailable")
        return HarnessStep.select_action(
            ActionSelection(
                option_id=selection.option_id,
                response=selection.response,
                reasoning=selection.reasoning,
                metadata={
                    "raw_text": "",
                    "usage": {},
                    "latency_ms": None,
                    "model": str(getattr(self.client, "model", "")),
                    "provider": str(getattr(self.client, "provider", "")),
                    "repair_used": False,
                    "repair_error": None,
                    "fallback_used": True,
                    "fallback_error": error,
                },
            )
        )

    @staticmethod
    def _content(response: dict[str, Any]) -> str:
        try:
            return str(response["choices"][0]["message"].get("content") or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response does not contain assistant content") from exc

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
            stripped = re.sub(r"\s*```$", "", stripped)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
            if match is None:
                raise RuntimeError("LLM did not return a JSON action selection")
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise RuntimeError("LLM action selection must be a JSON object")
        return parsed
