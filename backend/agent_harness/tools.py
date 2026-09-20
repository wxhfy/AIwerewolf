from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Callable

from backend.agent_harness.contracts import ActorRef
from backend.agent_harness.contracts import DecisionPoint
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import InformationState
from backend.agent_harness.contracts import ToolCall
from backend.agent_harness.contracts import ToolResult
from backend.agent_harness.middleware import ToolMiddleware
from backend.agent_harness.policy import CapabilityPolicy
from backend.agent_harness.policy import PolicyViolation


@dataclass(frozen=True)
class TrustedToolContext:
    """Server-owned identity and information scope, never supplied by the model."""

    request_id: str
    environment_id: str
    episode_id: str
    actor: ActorRef
    decision_point: DecisionPoint
    information_state: InformationState
    domain_metadata: dict[str, Any]


ToolHandler = Callable[[TrustedToolContext, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler = field(repr=False, compare=False)
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def public_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


class ToolGateway:
    """Guarded execution pipeline from untrusted model calls to domain projections."""

    def __init__(
        self,
        tools: list[ToolSpec] | None = None,
        *,
        middleware: tuple[ToolMiddleware, ...] = (),
    ) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._middleware = middleware
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self, policy: CapabilityPolicy, request: DecisionRequest) -> tuple[dict[str, Any], ...]:
        visible = [
            tool.public_schema()
            for tool in self._tools.values()
            if policy.allows(tool.name, tool.capabilities, request)
        ]
        return tuple(sorted(visible, key=lambda schema: str(schema["name"])))

    def invoke(self, call: ToolCall, policy: CapabilityPolicy, request: DecisionRequest) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            raise PolicyViolation(f"Unknown tool: {call.name}")

        candidate = call
        for middleware in self._middleware:
            transformed = middleware.before_tool(candidate, request)
            if transformed.name != call.name or transformed.call_id != call.call_id:
                raise PolicyViolation("Tool middleware cannot change tool identity")
            candidate = transformed

        policy.authorize(candidate, capabilities=tool.capabilities, request=request)
        context = TrustedToolContext(
            request_id=request.request_id,
            environment_id=request.environment_id,
            episode_id=request.episode_id,
            actor=request.actor,
            decision_point=request.decision_point,
            information_state=request.information_state,
            domain_metadata=dict(request.domain_metadata),
        )
        try:
            content = tool.handler(context, dict(candidate.arguments))
            result = ToolResult(
                call_id=candidate.call_id,
                name=tool.name,
                ok=True,
                content=dict(content or {}),
            )
        except Exception as exc:
            result = ToolResult(
                call_id=candidate.call_id,
                name=tool.name,
                ok=False,
                content={},
                error=str(exc)[:500],
            )

        for middleware in reversed(self._middleware):
            transformed = middleware.after_tool(candidate, result, request)
            if transformed.name != tool.name or transformed.call_id != candidate.call_id:
                raise PolicyViolation("Tool middleware cannot change result identity")
            result = transformed
        return result
