from __future__ import annotations

import json
import re
from typing import Any

from backend.agent_harness.contracts import ActionSelection
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessStep
from backend.agent_harness.contracts import PlannerContext


class LLMActionPlanner:
    """One bounded structured LLM call for a harness decision."""

    def __init__(self, client: Any, *, temperature: float = 0.7) -> None:
        self.client = client
        self.temperature = temperature

    def next_step(self, request: DecisionRequest, context: PlannerContext) -> HarnessStep:
        if context.step != 1:
            raise RuntimeError("Werewolf planner supports one model step per decision")
        response = self.client.chat_sync(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an autonomous actor in an asymmetric-information environment. "
                        "Use only the supplied information_state. Select exactly one server-generated option_id. "
                        "Return JSON only: {\"option_id\": string, \"response\": object, \"reasoning\": string}."
                    ),
                },
                {
                    "role": "user",
                    "content": "AIWEREWOLF_HARNESS_DECISION\n"
                    + json.dumps(self._prompt_payload(request), ensure_ascii=False),
                },
            ],
            temperature=self.temperature,
            max_tokens=request.budget.max_output_tokens,
            thinking=False,
        )
        content = self._content(response)
        parsed = self._parse_json_object(content)
        usage = response.get("usage") if isinstance(response, dict) else {}
        return HarnessStep.select_action(
            ActionSelection(
                option_id=str(parsed.get("option_id") or ""),
                response=parsed.get("response") if isinstance(parsed.get("response"), dict) else {},
                reasoning=str(parsed.get("reasoning") or ""),
                metadata={
                    "raw_text": content,
                    "usage": usage if isinstance(usage, dict) else {},
                    "latency_ms": response.get("_latency_ms") if isinstance(response, dict) else None,
                    "model": str(getattr(self.client, "model", "")),
                    "provider": str(getattr(self.client, "provider", "")),
                },
            )
        )

    @staticmethod
    def _prompt_payload(request: DecisionRequest) -> dict[str, Any]:
        return {
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
                "visible_history": list(request.information_state.visible_history),
                "private_memory": list(request.information_state.private_memory),
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
        }

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
