from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException
from sqlalchemy import inspect

from backend.application.commands.contracts import MatchCommandRequest
from backend.application.commands.contracts import MatchCommandResponse
from backend.application.commands.repository import MatchCommandRepository
from backend.application.matches.repository import MatchJobRepository
from backend.core.config import settings
from backend.core.errors import NotImplementedServiceError
from backend.core.security import CurrentActor
from backend.db.database import engine
from backend.infrastructure.messaging.match_notifications import match_notifications
from backend.infrastructure.persistence.match_feed import MatchFeedRepository

router = APIRouter(prefix="/api/v1")
match_jobs = MatchJobRepository()
match_feed = MatchFeedRepository()
commands = MatchCommandRepository()


@router.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@router.get("/health/ready", tags=["health"])
def readiness() -> dict:
    checks: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    checks["redis"] = match_notifications.health()
    ready = checks["database"] == "ok"
    return {"status": "ready" if ready else "not_ready", "ready": ready, "checks": checks}


@router.get("/system/capabilities", tags=["system"])
def capabilities() -> dict:
    tables = set(inspect(engine).get_table_names())
    return {
        "api_version": "v1",
        "environment": settings.environment,
        "transport": {"commands": "rest", "updates": "sse", "websocket": False},
        "execution": {
            "match_worker": True,
            "analysis_worker": True,
            "agent_runtime": "local_harness",
            "human_matches": False,
        },
        "persistence": {
            "games": "games" in tables,
            "rooms": "rooms" in tables,
            "match_jobs": "match_jobs" in tables,
            "match_commands": "match_commands" in tables,
            "agent_decision_jobs": "agent_decision_jobs" in tables,
            "decision_evaluations": "decision_evaluations" in tables,
            "post_game_analysis_jobs": "track_c_post_game_jobs" in tables,
            "strategy_knowledge": "strategy_knowledge_docs" in tables,
            "outbox": "outbox_events" in tables,
        },
        "auth_mode": settings.auth_mode,
    }


@router.get("/matches/{match_id}", tags=["matches"])
def get_match(match_id: str) -> dict:
    job = match_jobs.get_by_game_id(match_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Match not found")
    snapshot = match_feed.latest_snapshot(match_id)
    return {**job, "latest_seq": int((snapshot or {}).get("seq") or 0), "snapshot": snapshot}


@router.post(
    "/matches/{match_id}/commands",
    response_model=MatchCommandResponse,
    tags=["matches"],
)
def submit_match_command(
    match_id: str,
    request: MatchCommandRequest,
    actor: CurrentActor,
) -> dict:
    existing = commands.get(request.command_id)
    if existing is not None:
        if existing["match_id"] != match_id or existing["type"] != request.type.value:
            raise HTTPException(status_code=409, detail="command_id was already used for a different command")
        return existing

    job = match_jobs.get_by_game_id(match_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Match not found")
    latest = match_feed.latest_snapshot(match_id)
    latest_seq = int((latest or {}).get("seq") or 0)
    if request.expected_seq is not None and request.expected_seq != latest_seq:
        raise HTTPException(
            status_code=409,
            detail={"message": "Snapshot sequence conflict", "expected": request.expected_seq, "actual": latest_seq},
        )

    commands.create(
        command_id=request.command_id,
        match_id=match_id,
        command_type=request.type.value,
        actor_id=actor.actor_id,
        expected_seq=request.expected_seq,
        payload=request.payload,
    )
    if request.type.value == "cancel":
        commands.fail(request.command_id, "Cancellation is not implemented", status="rejected")
        raise NotImplementedServiceError(
            "Match cancellation requires cooperative engine checkpoints and is not implemented yet.",
            code="match_cancel_not_implemented",
        )

    target_state = "paused" if request.type.value == "pause" else "running"
    try:
        result = match_jobs.set_control_state(match_id, target_state)
    except RuntimeError as exc:
        commands.fail(request.command_id, str(exc), status="rejected")
        raise HTTPException(status_code=409, detail=str(exc))
    return commands.complete(request.command_id, result)
