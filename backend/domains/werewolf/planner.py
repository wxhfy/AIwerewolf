from __future__ import annotations

import json
import os
import re
import time
from difflib import SequenceMatcher
from typing import Any

from backend.agent_harness.contracts import ActionSelection
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessStep
from backend.agent_harness.contracts import PlannerContext
from backend.agent_harness.model import classify_model_error
from backend.agent_harness.model import complete_chat
from backend.agent_harness.model import supports_tool_calling
from backend.agent_harness.response import content_text
from backend.agent_harness.response import tool_arguments
from backend.agent_harness.response import tool_calls
from backend.agent_harness.response import tool_name
from backend.agent_harness.validation import ActionValidationError
from backend.agent_harness.validation import resolve_action
from backend.domains.werewolf.communication import audit_public_speech
from backend.domains.werewolf.communication import public_communication_policy
from backend.domains.werewolf.context import build_decision_context_v1
from backend.domains.werewolf.context import project_agent_profile_v1
from backend.domains.werewolf.context_budget import ContextTokenBudgetManager
from backend.domains.werewolf.decision_policy import apply_role_policy
from backend.domains.werewolf.strategy import strategy_score_for_option

_DELIBERATIVE_KINDS = {
    "werewolf.witch",
    "werewolf.shoot",
    "werewolf.boom",
    "werewolf.transfer_badge",
}


class LLMActionPlanner:
    """One bounded structured LLM call for a harness decision."""

    def __init__(self, client: Any, *, temperature: float = 0.7, input_token_budget: int | None = None) -> None:
        self.client = client
        self.temperature = temperature
        self.context_budget = ContextTokenBudgetManager()
        self.input_token_budget = input_token_budget or self._resolve_input_token_budget(client)

    def next_step(self, request: DecisionRequest, context: PlannerContext) -> HarnessStep:
        started = time.monotonic()
        prompt_payload = self._prompt_payload(
            request,
            context,
            input_token_budget=self.input_token_budget,
            fixed_parts=("AIWEREWOLF_HARNESS_DECISION",),
        )
        if context.step == 1 and request.decision_point.kind in _DELIBERATIVE_KINDS and request.budget.max_steps > 1:
            try:
                response = self._chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are preparing a high-impact decision in an asymmetric-information game. "
                                "Use only the supplied information. Produce a compact strategic assessment, "
                                "compare the legal options, and do not invent hidden facts. Let the supplied persona "
                                "shape risk preference without overriding role knowledge or game rules."
                            ),
                        },
                        {
                            "role": "user",
                            "content": "AIWEREWOLF_DELIBERATION\n" + json.dumps(prompt_payload, ensure_ascii=False),
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
                            "Use only decision_context. Treat confirmed_private_facts as direct knowledge, "
                            "public_timeline as observations, public_claims as unverified statements attributed to "
                            "their speakers, and inferences as fallible estimates. Never treat another player's "
                            "claim as your own check, action, or memory. You may load one advertised skill or call "
                            "one advertised read-only tool when that capability is available and materially useful. "
                            "Use agent_profile.persona for identity and voice, and agent_profile.behavior for soft "
                            "attention, social, risk, and conversation tendencies. These are preferences, not evidence, "
                            "and cannot override role knowledge, legal options, or game rules. Adapt them to the "
                            "current situation instead of mechanically following them. Avoid caricature and repeated catchphrases. Use the actor memory and "
                            "evidence attached to inferences as fallible, attributed context. Check agent_state.recent_public_speeches "
                            "before speaking and add new evidence or a new conversational move instead of repeating yourself. "
                            "For public speech, keep private reasoning out of the speech field: never expose wolf-team "
                            "knowledge, hidden night actions as system facts, internal scores, probabilities, raw IDs, or system terms. "
                            "Ground public claims in public evidence. You may claim a role, bluff a check or night action, hedge, or mislead as a deliberate public strategy; other players will judge the claim. "
                            "If the selected option has no response_schema, return response as an empty object and keep "
                            "reasoning under 80 words. Do not add a speech field to non-speech actions. "
                            "For non-speech actions, select exactly one option_id from action_options. If skip is not listed, never return skip; "
                            "when legal target options are listed, choose one of those targets. Never invent target IDs or repeat a completed role action when another legal target exists. "
                            "Never invent hidden facts. Finish by calling submit_action, or return JSON only: "
                            '{"option_id": string, "response": object, "reasoning": string}.'
                        ),
                    },
                    {
                        "role": "user",
                        "content": "AIWEREWOLF_HARNESS_DECISION\n" + json.dumps(prompt_payload, ensure_ascii=False),
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
        failure_kind: str | None = None
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
                failure_kind = classify_model_error(exc)
                selection = self._fallback_selection(request, repair_error, fallback_error)
                resolve_action(request, selection)
        selection = apply_role_policy(request, selection)
        resolve_action(request, selection)
        speech_violations: tuple[str, ...] = ()
        speech_rewritten = False
        speech_repetition_detected = False
        speech_repetition_repaired = False
        speech_repetition_score = 0.0
        if selection.option_id == "talk":
            audit = audit_public_speech(request, str(selection.response.get("speech") or ""))
            speech_violations = audit.violations
            speech = audit.speech
            if not audit.accepted:
                speech = self._fallback_speech(request)
                speech_rewritten = True
            speech_repetition_score = self._recent_speech_similarity(request, speech)
            if speech_repetition_score >= 0.82:
                speech_repetition_detected = True
                repaired = self._repair_repeated_speech(request, speech, context, started)
                if repaired:
                    speech = repaired
                    speech_repetition_repaired = True
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
                    "safe_degradation_used": fallback_used,
                    "failure_kind": failure_kind,
                    "speech_policy_violations": list(speech_violations),
                    "speech_rewritten": speech_rewritten,
                    "speech_repetition_detected": speech_repetition_detected,
                    "speech_repetition_repaired": speech_repetition_repaired,
                    "speech_repetition_score": round(speech_repetition_score, 3),
                    "syntax_recovered": bool(selection.metadata.get("syntax_recovered")),
                    "policy_overridden": bool(selection.metadata.get("policy_overridden")),
                    "policy_original_option_id": selection.metadata.get("policy_original_option_id"),
                    "policy_reason": selection.metadata.get("policy_reason"),
                    "context_budget": prompt_payload.get("context_manifest", {}).get("context_budget"),
                },
            )
        )

    @staticmethod
    def _normalize_speech_for_comparison(speech: str) -> str:
        return re.sub(r"\s+", "", str(speech or "")).strip().lower()

    @classmethod
    def _recent_speech_similarity(cls, request: DecisionRequest, speech: str) -> float:
        normalized = cls._normalize_speech_for_comparison(speech)
        if len(normalized) < 40:
            return 0.0
        best = 0.0
        for event in reversed(request.information_state.visible_history):
            payload = dict(event.get("payload") or {})
            if str(payload.get("actor_id") or payload.get("speaker_id") or "") != request.actor.actor_id:
                continue
            previous = cls._normalize_speech_for_comparison(str(payload.get("speech") or ""))
            if len(previous) < 40:
                continue
            best = max(best, SequenceMatcher(None, normalized, previous).ratio())
        return best

    @classmethod
    def _is_recent_speech_duplicate(cls, request: DecisionRequest, speech: str) -> bool:
        return cls._recent_speech_similarity(request, speech) >= 0.82

    def _repair_repeated_speech(
        self,
        request: DecisionRequest,
        speech: str,
        context: PlannerContext,
        started: float,
    ) -> str:
        """Ask for one bounded, phase-aware rewrite without changing game facts."""
        try:
            response = self._chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite one public game speech. Return JSON only as {\"speech\": string}. "
                            "Keep the actor's role strategy and visible evidence, but add a new conversational move "
                            "for the current phase. Do not invent facts, reveal private knowledge, or mention this rewrite."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "phase": request.domain_metadata.get("phase"),
                                "request_kind": request.domain_metadata.get("request_kind"),
                                "current_speech": speech,
                                "recent_public_timeline": list(request.information_state.visible_history)[-8:],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=min(self.temperature, 0.5),
                max_tokens=220,
                remaining_ms=self._remaining(context.remaining_ms, started),
            )
            raw = self._raw_selection_text(response)
            parsed = self._parse_json_object(raw)
            candidate = str(parsed.get("speech") or "").strip()
            audit = audit_public_speech(request, candidate)
            if audit.accepted and not self._is_recent_speech_duplicate(request, audit.speech):
                return audit.speech
        except Exception:
            return ""
        return ""

    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        remaining_ms: int,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return complete_chat(
            self.client,
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
        if not supports_tool_calling(self.client):
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
    def _resolve_input_token_budget(client: Any) -> int:
        configured = getattr(client, "context_input_tokens", None)
        if configured is None:
            configured = os.getenv("AGENT_CONTEXT_INPUT_TOKENS")
        if configured is None:
            window = getattr(client, "context_window_tokens", None)
            if window:
                configured = int(window) - 2048
        try:
            return max(2048, int(configured or 10000))
        except (TypeError, ValueError):
            return 10000

    @staticmethod
    def _prompt_payload(
        request: DecisionRequest,
        context: PlannerContext,
        *,
        input_token_budget: int | None = None,
        fixed_parts: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        limits = LLMActionPlanner._context_limits(request.decision_point.kind)
        decision_context = build_decision_context_v1(request, context, limits)
        payload = {
            "context_manifest": {
                "schema_version": "werewolf.decision_context.v1",
                "layers": [
                    "identity",
                    "agent_profile",
                    "situation",
                    "confirmed_private_facts",
                    "public_timeline",
                    "public_phase_summaries",
                    "public_claims",
                    "inferences",
                    "agent_state",
                    "external_knowledge",
                    "current_task",
                ],
                "limits": limits,
                "included": {
                    "private_facts": len(decision_context["confirmed_private_facts"]),
                    "public_timeline": len(decision_context["public_timeline"]),
                    "public_phase_summaries": len(decision_context["public_phase_summaries"]),
                    "public_claims": len(decision_context["public_claims"]),
                    "inferences": len(decision_context["inferences"]),
                    "external_knowledge": len(decision_context["external_knowledge"]),
                    "persona_fields": len(project_agent_profile_v1(request.agent_profile)["persona"]),
                    "attention_focus": len(decision_context["agent_state"]["attention_focus"]),
                    "recalled_episodes": len(decision_context["agent_state"]["recalled_episodes"]),
                    "social_reads": len(decision_context["agent_state"]["social_reads"]),
                    "legal_options": len(request.action_space.options),
                },
            },
            "decision_context": decision_context,
            "action_options": [
                {
                    "option_id": option.option_id,
                    "action_type": option.action_type,
                    **({"parameters": option.parameters} if option.parameters else {}),
                    **({"response_schema": option.response_schema} if option.response_schema else {}),
                    **({"model_hint": option.model_hint} if option.model_hint else {}),
                }
                for option in request.action_space.options
            ],
            "agent_profile": project_agent_profile_v1(request.agent_profile),
            "public_communication_policy": public_communication_policy(request),
        }
        if context.skill_catalog or context.loaded_skills or context.tool_schemas or context.tool_results:
            payload["capabilities"] = {
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
                        **({"error": result.error} if result.error else {}),
                    }
                    for result in context.tool_results
                ],
            }
        if input_token_budget is None:
            return payload
        return ContextTokenBudgetManager().fit(
            payload,
            input_token_budget=input_token_budget,
            fixed_parts=fixed_parts,
        )

    @classmethod
    def _control_step_from_response(
        cls,
        response: dict[str, Any],
        context: PlannerContext,
    ) -> HarnessStep | None:
        try:
            calls = tool_calls(response)
            if not calls:
                return None
            call = calls[0]
            name = tool_name(call)
            if name == "submit_action":
                return None
            arguments = cls._parse_json_object(tool_arguments(call))
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
        if kind in {"werewolf.talk", "werewolf.badge_speech", "werewolf.pk_speech", "werewolf.sheriff_closing", "werewolf.last_words"}:
            return {
                "public_timeline": 10,
                "phase_summaries": 4,
                "private_facts": 8,
                "public_claims": 10,
                "inferences": 5,
                "external_knowledge": 2,
                "working_memory": 4,
                "retrieved_episodes": 3,
                "social_reads": 4,
            }
        if kind in {"werewolf.vote", "werewolf.badge_election"}:
            return {
                "public_timeline": 14,
                "phase_summaries": 5,
                "private_facts": 8,
                "public_claims": 10,
                "inferences": 6,
                "external_knowledge": 2,
                "working_memory": 4,
                "retrieved_episodes": 4,
                "social_reads": 5,
            }
        return {
            "public_timeline": 6,
            "phase_summaries": 3,
            "private_facts": 8,
            "public_claims": 6,
            "inferences": 5,
            "external_knowledge": 2,
            "working_memory": 3,
            "retrieved_episodes": 2,
            "social_reads": 4,
        }

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
            calls = tool_calls(response)
            if calls:
                call = calls[0]
                if tool_name(call) != "submit_action":
                    raise RuntimeError("LLM called an unexpected action tool")
                return cls._selection(tool_arguments(call))
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError("LLM response does not contain a valid action tool call") from exc
        return cls._selection(cls._content(response))

    @classmethod
    def _raw_selection_text(cls, response: dict[str, Any]) -> str:
        try:
            calls = tool_calls(response)
            if calls:
                return tool_arguments(calls[0])
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
            str(item.get("id") or "") for item in request.information_state.observation.get("known_wolves") or []
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
            if kind == "werewolf.wolf_team_vote" or (kind == "werewolf.vote" and role in {"Werewolf", "WhiteWolfKing"}):
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
        known_wolves = {str(item.get("id") or "") for item in observation.get("known_wolves") or []}
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
                    "safe_degradation_used": True,
                    "fallback_error": error,
                    "failure_kind": classify_model_error(RuntimeError(error)),
                },
            )
        )

    @staticmethod
    def _content(response: dict[str, Any]) -> str:
        try:
            return content_text(response)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

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
