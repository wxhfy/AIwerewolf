from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import ToolCall

FORBIDDEN_CAPABILITIES = frozenset({"database", "sql", "shell", "filesystem", "network", "environment_truth"})


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class CapabilityPolicy:
    """Monotonic guard: request scope may narrow but never broaden deployment policy."""

    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    denied_capabilities: frozenset[str] = FORBIDDEN_CAPABILITIES

    def allows(self, tool_name: str, tool_capabilities: frozenset[str], request: DecisionRequest) -> bool:
        return (
            tool_name in self.allowed_tools
            and tool_name in request.tool_scope
            and not bool(tool_capabilities & self.denied_capabilities)
        )

    def authorize(
        self,
        call: ToolCall,
        *,
        capabilities: frozenset[str],
        request: DecisionRequest,
    ) -> None:
        if not self.allows(call.name, capabilities, request):
            raise PolicyViolation(f"Tool is not allowed for this request: {call.name}")
