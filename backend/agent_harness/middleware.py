from __future__ import annotations

from typing import Protocol

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import ToolCall
from backend.agent_harness.contracts import ToolResult


class ToolMiddleware(Protocol):
    """Cross-cutting tool hook for validation, metrics, redaction, and normalization."""

    def before_tool(self, call: ToolCall, request: DecisionRequest) -> ToolCall: ...

    def after_tool(self, call: ToolCall, result: ToolResult, request: DecisionRequest) -> ToolResult: ...


class PassthroughToolMiddleware:
    def before_tool(self, call: ToolCall, request: DecisionRequest) -> ToolCall:
        del request
        return call

    def after_tool(self, call: ToolCall, result: ToolResult, request: DecisionRequest) -> ToolResult:
        del call, request
        return result
