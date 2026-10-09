from __future__ import annotations

import copy
import json
import math
from collections import Counter
from typing import Any


class ContextBudgetExceeded(ValueError):
    """The mandatory decision context cannot fit inside the configured budget."""


class ContextTokenBudgetManager:
    """Fit structured decision context by removing complete, low-value items."""

    ESTIMATOR = "utf8_bytes_x_0.58_ceiling"
    MANIFEST_RESERVE_TOKENS = 384

    def fit(
        self, payload: dict[str, Any], *, input_token_budget: int, fixed_parts: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        if input_token_budget <= 0:
            raise ValueError("input_token_budget must be positive")
        result = copy.deepcopy(payload)
        original = self.estimate(result, fixed_parts=fixed_parts)
        minimum = self._minimum_payload_tokens(result, fixed_parts=fixed_parts)
        pruned: Counter[str] = Counter()
        target_budget = max(1, input_token_budget - self.MANIFEST_RESERVE_TOKENS)
        while self.estimate(result, fixed_parts=fixed_parts) > target_budget:
            candidate = self._next_candidate(result)
            if candidate is None:
                raise ContextBudgetExceeded(
                    f"mandatory context needs about {minimum} tokens, budget is {input_token_budget}"
                )
            path, category = candidate
            self._remove_path(result, path)
            pruned[category] += 1
        manifest = result.setdefault("context_manifest", {})
        decision = result.get("decision_context") or {}
        state = decision.get("agent_state") or {} if isinstance(decision, dict) else {}
        included = manifest.setdefault("included", {})
        for source, key in (
            ("confirmed_private_facts", "private_facts"),
            ("public_timeline", "public_timeline"),
            ("public_phase_summaries", "public_phase_summaries"),
            ("public_claims", "public_claims"),
            ("inferences", "inferences"),
            ("external_knowledge", "external_knowledge"),
        ):
            included[key] = len(decision.get(source) or []) if isinstance(decision, dict) else 0
        if isinstance(state, dict):
            for source in ("attention_focus", "recalled_episodes", "social_reads"):
                included[source] = len(state.get(source) or [])
        included["persona_fields"] = len(((result.get("agent_profile") or {}).get("persona") or {}))
        estimated = self.estimate(result, fixed_parts=fixed_parts)
        manifest["context_budget"] = {
            "input_token_budget": input_token_budget,
            "original_estimated_input_tokens": original,
            "estimated_input_tokens": estimated,
            "remaining_input_tokens": max(0, input_token_budget - estimated),
            "minimum_required_estimated_input_tokens": minimum,
            "pruned_counts": dict(pruned),
            "estimator": self.ESTIMATOR,
        }
        return result

    @classmethod
    def estimate(cls, value: Any, *, fixed_parts: tuple[str, ...] = ()) -> int:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return max(1, math.ceil(len((encoded + "".join(fixed_parts)).encode("utf-8")) * 0.58))

    def _minimum_payload_tokens(self, payload: dict[str, Any], *, fixed_parts: tuple[str, ...]) -> int:
        minimum = copy.deepcopy(payload)
        for path, _category in self._optional_root_candidates(minimum):
            self._remove_path(minimum, path)
        decision = minimum.get("decision_context")
        if isinstance(decision, dict):
            for key in ("current_task", "agent_state"):
                value = decision.get(key)
                if isinstance(value, dict):
                    for optional in (
                        "prior_reflections",
                        "recalled_episodes",
                        "social_reads",
                        "active_goals",
                        "own_recent_positions",
                    ):
                        value.pop(optional, None)
        return self.estimate(minimum, fixed_parts=fixed_parts)

    def _next_candidate(self, payload: dict[str, Any]) -> tuple[tuple[Any, ...], str] | None:
        ranked: list[tuple[int, int, tuple[Any, ...], str]] = []
        for path, category, priority in self._candidates(payload):
            value = self._get_path(payload, path)
            if value is not None:
                ranked.append((priority, -self.estimate(value), path, category))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1]))
        _priority, _size, path, category = ranked[0]
        return path, category

    def _candidates(self, payload: dict[str, Any]) -> list[tuple[tuple[Any, ...], str, int]]:
        candidates: list[tuple[tuple[Any, ...], str, int]] = []
        decision = payload.get("decision_context") or {}
        if not isinstance(decision, dict):
            return candidates
        for index, item in enumerate(decision.get("public_timeline") or []):
            candidates.append(
                (("decision_context", "public_timeline", index), "public_timeline", self._timeline_priority(item))
            )
        for index, _item in enumerate(decision.get("public_phase_summaries") or []):
            candidates.append(
                (("decision_context", "public_phase_summaries", index), "public_phase_summaries", 45)
            )
        for index, item in enumerate(decision.get("public_claims") or []):
            candidates.append(
                (("decision_context", "public_claims", index), "public_claims", self._claim_priority(item))
            )
        for index, item in enumerate(decision.get("inferences") or []):
            confidence = self._confidence_value(item.get("confidence")) if isinstance(item, dict) else 0.0
            candidates.append((("decision_context", "inferences", index), "inferences", 25 + int(confidence * 20)))
        for index, _item in enumerate(decision.get("external_knowledge") or []):
            candidates.append((("decision_context", "external_knowledge", index), "external_knowledge", 10))
        state = decision.get("agent_state") or {}
        if isinstance(state, dict):
            for key, priority, category in (
                ("recalled_episodes", 15, "recalled_episodes"),
                ("social_reads", 35, "social_reads"),
                ("own_recent_positions", 40, "own_recent_positions"),
                ("recent_public_speeches", 60, "recent_public_speeches"),
                ("active_goals", 55, "active_goals"),
                ("attention_focus", 65, "attention_focus"),
            ):
                for index, _item in enumerate(state.get(key) or []):
                    candidates.append((("decision_context", "agent_state", key, index), category, priority))
        task = decision.get("current_task") or {}
        if isinstance(task, dict):
            for index, _item in enumerate(task.get("prior_reflections") or []):
                candidates.append(
                    (("decision_context", "current_task", "prior_reflections", index), "prior_reflections", 12)
                )
        persona = (payload.get("agent_profile") or {}).get("persona")
        if isinstance(persona, dict):
            for key in ("humor_style", "basic_info", "vocabulary_style", "table_presence", "mistake_pattern"):
                if key in persona:
                    candidates.append((("agent_profile", "persona", key), "persona", 30))
        for path, category in self._optional_root_candidates(payload):
            candidates.append((path, category, 5))
        return candidates

    @staticmethod
    def _optional_root_candidates(payload: dict[str, Any]) -> list[tuple[tuple[Any, ...], str]]:
        candidates: list[tuple[tuple[Any, ...], str]] = []
        capabilities = payload.get("capabilities")
        if isinstance(capabilities, dict):
            for key in ("available_skills", "available_tools"):
                if capabilities.get(key):
                    candidates.append((("capabilities", key), f"capabilities.{key}"))
        if payload.get("public_communication_policy"):
            candidates.append((("public_communication_policy",), "communication_policy"))
        return candidates

    @staticmethod
    def _timeline_priority(item: Any) -> int:
        if not isinstance(item, dict):
            return 20
        kind = str(item.get("kind") or item.get("event_type") or "").lower()
        if any(token in kind for token in ("death", "vote", "reveal", "check", "claim")):
            return 65
        return 20

    @staticmethod
    def _claim_priority(item: Any) -> int:
        if not isinstance(item, dict):
            return 25
        kind = str(item.get("kind") or "").lower()
        if any(token in kind for token in ("role", "check", "contradiction", "retraction")):
            return 70
        return 35

    @staticmethod
    def _confidence_value(value: Any) -> float:
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        mapping = {"high": 1.0, "medium": 0.6, "low": 0.25}
        return mapping.get(str(value or "").strip().lower(), 0.0)

    @staticmethod
    def _get_path(value: Any, path: tuple[Any, ...]) -> Any:
        current = value
        for part in path:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and isinstance(part, int) and part < len(current):
                current = current[part]
            else:
                return None
        return current

    @classmethod
    def _remove_path(cls, value: Any, path: tuple[Any, ...]) -> None:
        if not path:
            return
        parent = cls._get_path(value, path[:-1])
        key = path[-1]
        if isinstance(parent, dict):
            parent.pop(key, None)
        elif isinstance(parent, list) and isinstance(key, int) and key < len(parent):
            parent.pop(key)
