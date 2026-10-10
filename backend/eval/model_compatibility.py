from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from backend.agent_harness import AgentHarness
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessResult
from backend.domains.werewolf.planner import LLMActionPlanner


@dataclass(frozen=True)
class ModelCompatibilityResult:
    """One model's result for one identical actor decision request."""

    model_id: str
    provider: str
    status: str
    action_option_id: str | None
    action_type: str | None
    action_valid: bool
    fallback_used: bool
    safe_degradation_used: bool
    failure_kind: str | None
    latency_ms: int | None
    harness_event_types: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_model(
    request: DecisionRequest,
    client: Any,
    *,
    model_id: str | None = None,
    provider: str | None = None,
) -> ModelCompatibilityResult:
    """Run one identical request through one provider-neutral model client."""
    planner = LLMActionPlanner(client)
    result: HarnessResult = AgentHarness(planner).run(request)
    action = result.action
    metadata = dict(action.metadata) if action is not None else {}
    return ModelCompatibilityResult(
        model_id=str(model_id or getattr(client, "model", "unknown")),
        provider=str(provider or getattr(client, "provider", "unknown")),
        status=result.status,
        action_option_id=action.option_id if action else None,
        action_type=action.action_type if action else None,
        action_valid=bool(action is not None and result.status == "completed"),
        fallback_used=bool(metadata.get("fallback_used") or metadata.get("fallback")),
        safe_degradation_used=bool(metadata.get("safe_degradation_used")),
        failure_kind=str(metadata.get("failure_kind")) if metadata.get("failure_kind") else None,
        latency_ms=_int_or_none(metadata.get("latency_ms")),
        harness_event_types=tuple(event.event_type for event in result.events),
        error=result.error,
    )


def summarize_results(results: list[ModelCompatibilityResult]) -> dict[str, Any]:
    """Aggregate contract-level compatibility metrics without ranking intelligence."""
    total = len(results)
    valid = sum(item.action_valid for item in results)
    fallback = sum(item.fallback_used for item in results)
    degraded = sum(item.safe_degradation_used for item in results)
    latencies = [item.latency_ms for item in results if item.latency_ms is not None]
    return {
        "total_models": total,
        "valid_action_rate": _ratio(valid, total),
        "fallback_rate": _ratio(fallback, total),
        "safe_degradation_rate": _ratio(degraded, total),
        "latency_ms": {
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else None,
        },
        "failure_kinds": _counts(item.failure_kind for item in results),
        "statuses": _counts(item.status for item in results),
        "results": [item.to_dict() for item in results],
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _ratio(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            key = str(value)
            counts[key] = counts.get(key, 0) + 1
    return counts
