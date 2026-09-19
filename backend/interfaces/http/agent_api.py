from __future__ import annotations

from fastapi import APIRouter

from backend.application.agents.contracts import AgentCapabilities
from backend.application.agents.contracts import AgentDecisionRequest
from backend.application.agents.contracts import AgentDecisionResult
from backend.core.errors import NotImplementedServiceError
from backend.core.security import CurrentActor

router = APIRouter(prefix="/api/v1/agent", tags=["agent-service"])


@router.get("/health")
def agent_health() -> dict:
    return {"status": "ok", "mode": "local", "remote_service": "not_deployed"}


@router.get("/capabilities", response_model=AgentCapabilities)
def agent_capabilities() -> AgentCapabilities:
    return AgentCapabilities()


@router.post("/decisions", response_model=AgentDecisionResult)
def request_agent_decision(request: AgentDecisionRequest, actor: CurrentActor) -> AgentDecisionResult:
    del request, actor
    raise NotImplementedServiceError(
        "Remote Agent Service execution is not enabled. Match Worker currently uses LocalAgentRuntime.",
        code="remote_agent_service_not_enabled",
    )
