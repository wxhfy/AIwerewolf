from __future__ import annotations

from typing import Any

# Shared metadata keys used to carry AgentLoop audit data.

TOOL_TRACE = "_tool_trace"
AUTO_INJECTED_STRATEGIES = "_auto_injected_strategies"
RETRIEVED_KNOWLEDGE_IDS = "_retrieved_knowledge_ids"
USAGE = "_usage"

COMPAT_TOOL_TRACE = "tool_trace"
COMPAT_AUTO_INJECTED_STRATEGIES = "auto_injected_strategies"
COMPAT_RETRIEVED_KNOWLEDGE_IDS = "retrieved_knowledge_ids"
COMPAT_USAGE = "usage"

DECISION_RETRIEVED_KNOWLEDGE_IDS = "retrieved_knowledge_ids"
DECISION_RETRIEVAL_USED = "retrieval_used"
DECISION_USAGE = "usage"

LOOP_RESULT_KEYS = (
    TOOL_TRACE,
    AUTO_INJECTED_STRATEGIES,
    RETRIEVED_KNOWLEDGE_IDS,
    USAGE,
)

DECISION_TRACE_KEYS = (
    TOOL_TRACE,
    AUTO_INJECTED_STRATEGIES,
    DECISION_RETRIEVED_KNOWLEDGE_IDS,
    DECISION_USAGE,
)


def copy_loop_result_keys(source: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Copy AgentLoop audit fields into a public pipeline result."""

    for key in LOOP_RESULT_KEYS:
        if key in source:
            result[key] = source[key]
    return result


def compat_loop_trace_payload(
    *,
    tool_trace: list[dict[str, Any]],
    auto_injected: list[str],
    retrieved_ids: list[str],
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Build the legacy trace payload consumed by CognitiveAgent fallback paths."""

    return {
        COMPAT_TOOL_TRACE: tool_trace,
        COMPAT_AUTO_INJECTED_STRATEGIES: auto_injected,
        COMPAT_RETRIEVED_KNOWLEDGE_IDS: retrieved_ids,
        COMPAT_USAGE: usage,
    }


def compat_metadata_from_trace(metadata: dict[str, Any], trace: dict[str, Any]) -> list[str]:
    """Merge older global AgentLoop trace data into decision metadata."""

    if trace.get(COMPAT_TOOL_TRACE):
        metadata[TOOL_TRACE] = trace[COMPAT_TOOL_TRACE]

    auto_injected_ids = knowledge_id_list(trace.get(COMPAT_AUTO_INJECTED_STRATEGIES, []))
    if auto_injected_ids:
        metadata[AUTO_INJECTED_STRATEGIES] = auto_injected_ids
        metadata[DECISION_RETRIEVAL_USED] = True

    merged = trace.get(
        COMPAT_RETRIEVED_KNOWLEDGE_IDS,
        auto_injected_ids,
    )
    merged_ids = knowledge_id_list(merged)
    if merged_ids:
        metadata[DECISION_RETRIEVED_KNOWLEDGE_IDS] = merged_ids
        metadata[DECISION_RETRIEVAL_USED] = True

    usage = trace.get(COMPAT_USAGE, {})
    if usage:
        metadata[DECISION_USAGE] = usage_metadata(usage)
    return merged_ids


def knowledge_id_list(value: Any) -> list[str]:
    """Normalize retrieved knowledge ids for persistence and metadata."""

    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def usage_metadata(usage: dict[str, Any]) -> dict[str, Any]:
    """Normalize token usage fields for decision metadata."""

    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def loop_metadata_from_result(
    result: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract AgentLoop audit fields carried with a pipeline result."""

    metadata = dict(extra or {})
    if TOOL_TRACE in result:
        metadata[TOOL_TRACE] = result[TOOL_TRACE]
    if AUTO_INJECTED_STRATEGIES in result:
        auto_injected_ids = knowledge_id_list(result[AUTO_INJECTED_STRATEGIES])
        metadata[AUTO_INJECTED_STRATEGIES] = auto_injected_ids
        if auto_injected_ids:
            metadata[DECISION_RETRIEVAL_USED] = True
    if RETRIEVED_KNOWLEDGE_IDS in result:
        retrieved_ids = knowledge_id_list(result[RETRIEVED_KNOWLEDGE_IDS])
        metadata[DECISION_RETRIEVED_KNOWLEDGE_IDS] = retrieved_ids
        if retrieved_ids:
            metadata[DECISION_RETRIEVAL_USED] = True
    if USAGE in result and isinstance(result[USAGE], dict):
        metadata[DECISION_USAGE] = usage_metadata(result[USAGE])
    return metadata
