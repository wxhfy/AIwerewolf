from __future__ import annotations

from typing import Protocol

from backend.application.agents.contracts import AgentDecisionRequest
from backend.application.agents.contracts import AgentDecisionResult


class AgentGateway(Protocol):
    """Boundary used by match execution, regardless of local or remote agent hosting."""

    def decide(self, request: AgentDecisionRequest) -> AgentDecisionResult: ...
