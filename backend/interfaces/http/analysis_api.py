from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query

from backend.application.analysis.contracts import AnalysisRetryResponse
from backend.application.analysis.contracts import DecisionEvaluationItem
from backend.application.analysis.contracts import DecisionTraceItem
from backend.application.analysis.contracts import MatchAnalysisResponse
from backend.application.analysis.contracts import StrategyKnowledgeItem
from backend.application.analysis.repository import AnalysisRepository
from backend.core.security import CurrentActor

router = APIRouter(prefix="/api/v1")
repository = AnalysisRepository()


@router.get(
    "/matches/{match_id}/analysis",
    response_model=MatchAnalysisResponse,
    tags=["analysis"],
)
def get_match_analysis(match_id: str) -> dict:
    result = repository.get_summary(match_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return result


@router.get(
    "/matches/{match_id}/decisions",
    response_model=list[DecisionTraceItem],
    tags=["analysis"],
)
def list_match_decisions(
    match_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    if repository.get_summary(match_id) is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return repository.list_decisions(match_id, limit=limit, offset=offset)


@router.get(
    "/matches/{match_id}/decision-evaluations",
    response_model=list[DecisionEvaluationItem],
    tags=["analysis"],
)
def list_match_decision_evaluations(
    match_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    if repository.get_summary(match_id) is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return repository.list_evaluations(match_id, limit=limit, offset=offset)


@router.post(
    "/matches/{match_id}/analysis/retry",
    response_model=AnalysisRetryResponse,
    status_code=202,
    tags=["analysis"],
)
def retry_match_analysis(match_id: str, actor: CurrentActor) -> dict:
    result = repository.retry(match_id, actor_id=actor.actor_id)
    if result is None:
        raise HTTPException(status_code=409, detail="Only finished matches can be analyzed")
    if result["status"] == "running":
        raise HTTPException(status_code=409, detail="Analysis is already running")
    return result


@router.get(
    "/strategies",
    response_model=list[StrategyKnowledgeItem],
    tags=["strategies"],
)
def list_strategies(
    status: str | None = Query(default=None),
    role: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return repository.list_strategies(status=status, role=role, limit=limit, offset=offset)


@router.get(
    "/strategies/{strategy_id}",
    response_model=StrategyKnowledgeItem,
    tags=["strategies"],
)
def get_strategy(strategy_id: str) -> dict:
    result = repository.get_strategy(strategy_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return result
