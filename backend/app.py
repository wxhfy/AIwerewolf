from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any
from typing import Dict
from typing import Optional

from fastapi import Body
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.responses import Response

from backend.application.matches.executor import prepare_game
from backend.application.matches.repository import MatchJobRepository
from backend.application.matches.spec import MatchExecutionSpec
from backend.core.config import settings
from backend.core.errors import install_exception_handlers
from backend.core.middleware import install_middleware
from backend.db.database import init_db
from backend.engine.models import GameState
from backend.infrastructure.messaging.match_notifications import match_notifications
from backend.interfaces.http.agent_api import router as agent_api_router
from backend.interfaces.http.analysis_api import router as analysis_api_router
from backend.interfaces.http.api_v1 import router as api_v1_router
from backend.interfaces.http.match_stream import router as match_stream_router
from backend.protocols import RoomCreateRequest
from backend.protocols import RoomManager


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _initialize_database()
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_middleware(app, settings)
install_exception_handlers(app)
app.include_router(api_v1_router)
app.include_router(agent_api_router)
app.include_router(analysis_api_router)
app.include_router(match_stream_router)

_rooms = RoomManager()
_match_jobs = MatchJobRepository()


def _save_game_start(state: GameState) -> None:
    from backend.db.persist import save_game_start

    save_game_start(state)


def _save_snapshot(state: GameState) -> None:
    from backend.db.persist import save_snapshot

    moderator = state.snapshot(show_private=True)
    public = state.snapshot(show_private=False)
    save_snapshot(
        state.id,
        int(moderator.get("seq") or 0),
        state.day,
        state.phase.value,
        moderator,
        public,
    )
    match_notifications.publish(state.id, int(moderator.get("seq") or 0))


def _initialize_database() -> None:
    import logging

    logger = logging.getLogger(__name__)
    try:
        init_db()
    except Exception:
        logger.warning("Database initialization failed during startup", exc_info=True)
        return


@app.get("/api/health")
def health():
    """Health check — verifies DB and LLM connectivity."""
    import os

    from backend.db.database import engine

    result: dict = {"status": "ok", "checks": {}}

    # DB check
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        result["checks"]["database"] = "ok"
    except Exception as exc:
        result["checks"]["database"] = f"error: {exc}"
        result["status"] = "degraded"

    # LLM check
    provider = os.getenv("LLM_PROVIDER", "unset")
    result["checks"]["llm_provider"] = provider
    redis_status = match_notifications.health()
    result["checks"]["redis"] = redis_status
    if redis_status.startswith("error:"):
        result["status"] = "degraded"
    result["checks"]["strict_mode"] = os.getenv("AIWEREWOLF_STRICT_MODE", "false")
    result["version"] = "0.1.0"

    return result


def _sanitize_room_llm_config(raw: Any) -> Optional[Dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    config: Dict[str, str] = {}
    for source_key, target_key in (
        ("provider", "provider"),
        ("model", "model"),
        ("base_url", "base_url"),
    ):
        value = raw.get(source_key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            config[target_key] = text.rstrip("/") if target_key == "base_url" else text
    return config or None


def _payload_int(payload: Dict[str, Any], key: str, fallback: int) -> int:
    value = payload.get(key, fallback)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _payload_optional_int(payload: Dict[str, Any], key: str, fallback: Optional[int]) -> Optional[int]:
    if key not in payload or payload.get(key) in (None, ""):
        return fallback
    try:
        return int(payload[key])
    except (TypeError, ValueError):
        return fallback


@app.post("/api/games")
def create_game(
    seed: int = 7,
    show_private: bool = False,
    agent_type: str = "llm",
    human_seat: Optional[int] = None,
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
):
    del seed, show_private, agent_type, human_seat, player_count, rule_pack_id
    raise HTTPException(
        status_code=410,
        detail="Synchronous game execution was removed; create a room, prepare it, then start the AI match.",
    )


@app.get("/api/games/{game_id}")
def get_game(game_id: str, show_private: bool = False):
    from backend.infrastructure.persistence.match_feed import MatchFeedRepository

    snapshot = MatchFeedRepository().latest_snapshot(game_id, moderator=show_private)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return snapshot


@app.get("/api/games")
def list_games():
    from backend.db.persist import list_games as db_list_games

    return db_list_games(limit=200)


@app.get("/api/history")
def game_history(limit: int = 20):
    """Return recent game history from the database for the frontend panel."""
    from backend.db.persist import list_games as db_list_games

    try:
        return db_list_games(limit=limit)
    except Exception:
        return []


@app.get("/api/history/{game_id}")
def game_history_detail(game_id: str):
    """Return one game's summary: players, speeches, votes, deaths."""
    from backend.db.persist import get_game_summary

    try:
        summary = get_game_summary(game_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="Game not found")
        return summary
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load game history")


# ---------------------------------------------------------------------------
# Track B reserved endpoints — replay, metrics, leaderboard, review reports
# ---------------------------------------------------------------------------


@app.get("/api/replay/{game_id}.json")
def replay_game_json(game_id: str, show_private: bool = False, download: bool = True):
    """Download the persisted replay payload as JSON.

    This is the audit/export counterpart to `/api/replay/{game_id}`. The
    payload comes from the same persisted replay source, while `download=true`
    makes browsers save it with a stable file name.
    """
    from backend.db.persist import get_replay

    payload = get_replay(game_id, show_private=show_private)
    if payload is None:
        raise HTTPException(status_code=404, detail="Game not found")
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="replay-{game_id}.json"'
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


@app.get("/api/replay/{game_id}")
def replay_game(game_id: str, show_private: bool = False):
    """Return the full replay payload (snapshots + all events + decisions).

    Used by the Track B replay UI. The current implementation returns the
    final snapshot + every persisted event/decision/vote; once a step-by-step
    replay UI is built, we can extend this with per-day snapshots.
    """
    from backend.db.persist import get_replay

    payload = get_replay(game_id, show_private=show_private)
    if payload is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return payload


@app.get("/api/games/{game_id}/metrics")
def game_metrics(game_id: str):
    """Per-game multi-dimensional metrics (Track B). One row per (player, metric)."""
    from backend.db.persist import get_game_metrics

    metrics = get_game_metrics(game_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return metrics


@app.get("/api/games/{game_id}/runtime_metrics")
def game_runtime_metrics(game_id: str):
    """Per-game runtime metrics: LLM latency, tokens, speech length, decision validity.

    Stable JSON schema usable by future dashboard clients without null-checks.
    """
    from backend.db.persist import get_runtime_metrics

    metrics = get_runtime_metrics(game_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return metrics


@app.get("/api/metrics/aggregate")
def metrics_aggregate(limit_games: int = 200):
    """Cross-game aggregate metrics for Track B/C visualization.

    Returns a stable schema covering game outcomes, runtime cost, win rate by
    role / agent_type, Track B review status distribution, and Track C
    strategy/patch/tournament summary.
    """
    from backend.db.persist import get_aggregate_metrics

    return get_aggregate_metrics(limit_games=max(1, min(limit_games, 5000)))


@app.get("/api/leaderboard")
def leaderboard(role: Optional[str] = None, limit: int = 20):
    """Aggregated leaderboard rows (Track B). Filter by role if provided."""
    from backend.db.persist import get_leaderboard

    return get_leaderboard(role=role, limit=limit)


@app.get("/api/leaderboard/role_matrix")
def leaderboard_role_matrix(
    limit_games: int = 500,
    llm_only: bool = True,
    since_iso: Optional[str] = None,
):
    """Per-(agent, role) win-rate matrix.

    Filters to all-LLM games by default so heuristic AB-tournament noise from
    other tenants doesn't enter the table. `since_iso` further constrains the
    sample to games finished after a wall-clock cutoff (ISO-8601 UTC).
    """
    from backend.db.persist import get_role_model_leaderboard

    return get_role_model_leaderboard(
        limit_games=max(1, min(limit_games, 5000)),
        llm_only=llm_only,
        since_iso=since_iso,
    )


@app.get("/api/strategy/attribution")
def strategy_attribution(
    limit_games: int = 500,
    llm_only: bool = True,
    since_iso: Optional[str] = None,
    top_k: int = 20,
):
    """Which strategy knowledge docs got retrieved & whether they helped.

    Hits the knowledge_usage_feedback table; useful for Track C verification
    (active docs with usage_count==0 are clear signals of broken retrieval).
    """
    from backend.db.persist import get_strategy_attribution

    return get_strategy_attribution(
        limit_games=max(1, min(limit_games, 5000)),
        llm_only=llm_only,
        since_iso=since_iso,
        top_k=max(1, min(top_k, 200)),
    )


@app.get("/api/games/{game_id}/reviews")
def game_reviews(game_id: str):
    """Reviewer-agent generated post-game reports (Track B)."""
    from backend.db.persist import get_review_reports

    payload = get_review_reports(game_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return payload


@app.get("/api/games/{game_id}/reviews/status")
def game_review_status(game_id: str):
    """Lightweight readiness probe for post-game review artifacts.

    This endpoint intentionally returns 200 while a review is still being
    generated, so the frontend can poll without creating browser 404 noise.
    """
    from backend.db.persist import get_review_reports

    payload = get_review_reports(game_id) or {}
    has_html = bool(payload.get("html_report"))
    has_markdown = bool(str(payload.get("markdown") or "").strip())
    return {
        "game_id": game_id,
        "status": "ready" if has_html or has_markdown else "pending",
        "hasHtml": has_html,
        "hasMarkdown": has_markdown,
        "publishAllowed": bool(payload.get("publish_allowed")),
        "grade": payload.get("grade"),
        "score": payload.get("score"),
        "publishedAt": payload.get("published_at"),
    }


@app.get("/api/games/{game_id}/reviews/html", response_class=HTMLResponse)
def game_review_html(game_id: str):
    from backend.db.persist import get_review_html

    payload = get_review_html(game_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="HTML review not found")
    return HTMLResponse(payload)


@app.get("/api/games/{game_id}/reviews.md")
def game_review_markdown(game_id: str, download: bool = True):
    """Return the post-game review as raw markdown.

    Frontends embed the prettified HTML via /reviews/html; this endpoint is
    the "下载 MD" button next to it. `download=true` (default) sets the
    Content-Disposition attachment header so browsers save it as a file
    named `review-<game_id>.md`. Pass `?download=false` to inline.
    """
    from backend.db.persist import get_review_markdown

    payload = get_review_markdown(game_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Markdown review not found")
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="review-{game_id}.md"'
    return Response(content=payload, media_type="text/markdown; charset=utf-8", headers=headers)


# ---------------------------------------------------------------------------
# Track C reserved endpoints — agent versions + self-evolution chain
# ---------------------------------------------------------------------------


@app.get("/api/agents")
def list_agent_versions():
    """List registered agent versions (Track C)."""
    from backend.db.persist import list_agent_versions

    return list_agent_versions()


@app.post("/api/agents")
def register_agent_version(payload: Dict[str, Any]):
    """Register a new agent version (Track C).

    Body: {name, agent_type, model_name, prompt_version, config, parent_version_id, notes}
    """
    from backend.db.persist import register_agent_version

    try:
        record = register_agent_version(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return record


@app.get("/api/evolution")
def list_evolution_rounds(limit: int = 20):
    """List the self-evolution iteration log (Track C)."""
    from backend.db.persist import list_evolution_rounds

    return list_evolution_rounds(limit=limit)


@app.get("/api/evolution/dashboard")
def evolution_dashboard():
    from backend.db.persist import get_evolution_dashboard

    return get_evolution_dashboard()


@app.get("/api/eval/role-scores")
def eval_role_scores(role: Optional[str] = None):
    """Score-discrimination experiment results (Phase D/F output).

    Reads ``data/experiment/discrimination_summary.json`` (written by
    ``scripts/analyze_score_distributions.py``) plus raw per-game JSONs in
    the same directory. If the summary file isn't present yet (e.g. dry-run
    still in progress), returns ``{"available": false, ...}`` with partial
    raw counts so the dashboard can show "running" state.
    """
    from pathlib import Path

    experiment_dir = Path(__file__).resolve().parent.parent / "data" / "experiment"
    summary_path = experiment_dir / "discrimination_summary.json"
    raw_files = sorted(experiment_dir.glob("role_*_*_seed_*.json")) if experiment_dir.exists() else []

    per_role_counts: dict[str, dict[str, int]] = {}
    raw_records: list[dict] = []
    for path in raw_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("experiment_meta") or {}
        rname = meta.get("role")
        variant = meta.get("variant")
        if not rname or not variant:
            continue
        if role and rname != role:
            continue
        per_role_counts.setdefault(rname, {}).setdefault(variant, 0)
        per_role_counts[rname][variant] += 1
        if payload.get("publish_allowed"):
            raw_records.append(
                {
                    "role": rname,
                    "variant": variant,
                    "seed": meta.get("seed"),
                    "game_id": payload.get("game_id"),
                    "adjusted_final_score": payload.get("target_role_avg_adjusted_final_score"),
                    "role_task_score": payload.get("target_role_avg_role_task_score"),
                    "mistakes": payload.get("target_role_total_mistakes", 0),
                    "fallback": payload.get("fallback_decision_count", 0),
                    "winner": payload.get("winner"),
                }
            )

    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = None
    else:
        summary = None

    if role and summary:
        summary = dict(summary)
        summary["per_role"] = [r for r in summary.get("per_role", []) if r.get("role") == role]

    return {
        "available": summary is not None,
        "summary": summary,
        "raw_counts": per_role_counts,
        "raw_records": raw_records,
        "total_records": len(raw_records),
    }


@app.post("/api/evolution/cycle")
def run_evolution_cycle(payload: Optional[Dict[str, Any]] = None):
    from backend.db.persist import run_evolution_cycle

    body = payload or {}
    report_ids = body.get("report_ids")
    seeds = body.get("seeds")
    return run_evolution_cycle(
        report_ids=list(report_ids) if isinstance(report_ids, list) else None,
        seeds=[int(item) for item in seeds] if isinstance(seeds, list) else None,
    )


@app.post("/api/evolution/dream")
def run_track_c_dream_job(payload: Optional[Dict[str, Any]] = None):
    from backend.db.persist import run_dream_job

    body = payload or {}
    report_ids = body.get("report_ids")
    from_version = str(body.get("from_version") or "v1")
    return run_dream_job(list(report_ids) if isinstance(report_ids, list) else None, from_version=from_version)


@app.get("/api/strategy/knowledge")
def list_strategy_knowledge(
    role: Optional[str] = None, phase: Optional[str] = None, status: Optional[str] = None, limit: int = 100
):
    from backend.db.persist import list_strategy_knowledge

    return list_strategy_knowledge(role=role, phase=phase, status=status, limit=limit)


@app.post("/api/strategy/knowledge/extract/{game_id}")
def extract_strategy_knowledge(game_id: str):
    from backend.db.persist import extract_strategy_knowledge_from_game

    return extract_strategy_knowledge_from_game(game_id)


@app.post("/api/strategy/knowledge/{doc_id}/deprecate")
def deprecate_strategy_knowledge(doc_id: str, payload: Optional[Dict[str, Any]] = None):
    from backend.db.persist import deprecate_strategy_knowledge

    try:
        return deprecate_strategy_knowledge(doc_id, reason=str((payload or {}).get("reason") or "manual"))
    except KeyError:
        raise HTTPException(status_code=404, detail="Knowledge doc not found")


@app.get("/api/strategy/cards")
def list_strategy_cards(role: Optional[str] = None):
    from backend.db.persist import list_role_strategy_cards

    return list_role_strategy_cards(role=role)


@app.post("/api/strategy/patches/{patch_id}/apply")
def apply_strategy_patch(patch_id: str):
    from backend.db.persist import apply_strategy_patch

    try:
        return apply_strategy_patch(patch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Strategy patch not found")


@app.get("/api/personas")
def list_personas_endpoint():
    """List the persona library used to populate AI players.

    The frontend persona viewer + Track B/C tools consume this. Empty list
    when the DB hasn't been seeded yet — never raises.
    """
    try:
        from backend.db.persona_db import list_personas

        return list_personas()
    except Exception:
        return []


@app.post("/api/personas")
def create_persona(payload: Dict[str, Any]):
    """Add a new persona to the library."""
    try:
        from backend.db.persona_db import create_persona as _create

        return _create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.put("/api/personas/{name}")
def update_persona(name: str, payload: Dict[str, Any]):
    """Update an existing persona."""
    try:
        from backend.db.persona_db import update_persona as _update

        return _update(name, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")


@app.delete("/api/personas/{name}")
def delete_persona(name: str):
    """Soft-delete a persona."""
    try:
        from backend.db.persona_db import update_persona as _update

        return _update(name, {"is_active": False})
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found")


@app.post("/api/rooms")
def create_room(
    name: str = "Demo Room",
    seed: int = 7,
    player_count: int = 10,
    agent_type: str = "llm",
    human_seat: Optional[int] = None,
    rule_pack_id: str = "wolfcha-default",
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    body = payload or {}
    name = str(body.get("name", name))
    seed = _payload_int(body, "seed", seed)
    player_count = _payload_int(body, "player_count", player_count)
    agent_type = str(body.get("agent_type", agent_type))
    if agent_type.strip().lower() not in {"llm", "cognitive"}:
        raise HTTPException(status_code=400, detail="Only LLM-backed AI rooms are supported")
    human_seat = _payload_optional_int(body, "human_seat", human_seat)
    if human_seat is not None:
        raise HTTPException(status_code=501, detail="Human matches are temporarily disabled; use an AI-only room")
    rule_pack_id = str(body.get("rule_pack_id", rule_pack_id))
    llm_config = _sanitize_room_llm_config(body.get("llm_config"))
    request = RoomCreateRequest(
        name=name,
        seed=seed,
        player_count=player_count,
        agent_type=agent_type,
        human_seat=human_seat,
        rule_pack_id=rule_pack_id,
        llm_config=llm_config,
    )
    room = _rooms.create_room(request)
    return room.to_dict()


@app.get("/api/rooms")
def list_rooms():
    return _rooms.list_rooms()


@app.get("/api/rooms/{room_id}")
def get_room(room_id: str):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    return room.to_dict()


@app.get("/api/rooms/{room_id}/games")
def list_room_games(room_id: str):
    try:
        _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    return _match_jobs.list_for_room(room_id)


@app.get("/api/rooms/{room_id}/snapshot")
def get_room_snapshot(room_id: str):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    snapshot = None
    if room.current_game_id:
        from backend.infrastructure.persistence.match_feed import MatchFeedRepository

        snapshot = MatchFeedRepository().latest_snapshot(room.current_game_id, moderator=True)
    if snapshot is None:
        snapshot = room.latest_snapshot
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@app.post("/api/rooms/{room_id}/games")
def create_room_game(room_id: str, show_private: bool = False):
    del show_private
    raise HTTPException(
        status_code=410,
        detail="Synchronous room execution was removed; use /prepare followed by /start.",
    )


@app.post("/api/rooms/{room_id}/prepare")
def prepare_room_game(room_id: str, show_private: bool = False):
    """Create and persist a match shell without advancing beyond setup.

    Starting the match is a separate REST command. Clients consume ordered,
    persisted projections through SSE. Repeated calls return the active match.
    """
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    existing = _rooms.get_active_game(room_id)
    if existing is not None and existing.state.winner is None:
        # Either already prepared or already running — return the current
        # snapshot rather than building a second game with the same seed.
        snapshot = existing.state.snapshot(show_private=show_private)
        _rooms.record_snapshot(room_id, snapshot)
        return snapshot
    if room.current_game_id:
        existing_job = _match_jobs.get_by_game_id(room.current_game_id)
        if existing_job is not None:
            from backend.infrastructure.persistence.match_feed import MatchFeedRepository

            snapshot = MatchFeedRepository().latest_snapshot(room.current_game_id, moderator=show_private)
            if snapshot is not None:
                return snapshot
    game = prepare_game(
        seed=room.seed,
        player_count=room.player_count,
        rule_pack_id=room.rule_pack_id,
    )
    _rooms.set_active_game(room_id, game)

    _save_game_start(game.state)
    _save_snapshot(game.state)
    spec = MatchExecutionSpec.from_game(
        game,
        room_id=room_id,
        seed=room.seed,
        agent_type=room.agent_type,
        rule_pack_id=room.rule_pack_id,
        llm_config=room.llm_config,
    )
    _match_jobs.prepare(game_id=game.state.id, room_id=room_id, payload=spec.to_dict())
    _rooms.set_room_status(room_id, "prepared")
    snapshot = game.state.snapshot(show_private=show_private)
    _rooms.record_snapshot(room_id, snapshot)
    return snapshot


@app.post("/api/rooms/{room_id}/start")
def start_or_resume_room_game(room_id: str, show_private: bool = False):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    game = _rooms.get_active_game(room_id)
    if room.human_seat is not None:
        raise HTTPException(status_code=501, detail="Human matches are temporarily disabled")
    if game is None and not room.current_game_id:
        prepare_room_game(room_id, show_private=True)
        room = _rooms.get_room(room_id)
        game = _rooms.get_active_game(room_id)
    payload = None
    match_id = room.current_game_id
    if game is not None:
        match_id = game.state.id
        payload = MatchExecutionSpec.from_game(
            game,
            room_id=room_id,
            seed=room.seed,
            agent_type=room.agent_type,
            rule_pack_id=room.rule_pack_id,
            llm_config=room.llm_config,
        ).to_dict()
    if not match_id:
        raise HTTPException(status_code=500, detail="Prepared match is unavailable")
    try:
        job = _match_jobs.enqueue(game_id=match_id, room_id=room_id, payload=payload)
    except KeyError:
        raise HTTPException(status_code=409, detail="Prepared match job is unavailable")
    _rooms.set_room_status(room_id, job["status"])
    from backend.infrastructure.persistence.match_feed import MatchFeedRepository

    snapshot = MatchFeedRepository().latest_snapshot(match_id, moderator=show_private)
    if snapshot is None:
        raise HTTPException(status_code=500, detail="Prepared match snapshot is unavailable")
    return {
        "match_id": match_id,
        "room_id": room_id,
        "status": job["status"],
        "seq": snapshot.get("seq", 0),
        "snapshot": snapshot,
    }


@app.post("/api/rooms/{room_id}/action")
def submit_room_action(room_id: str, payload: Dict[str, Any], show_private: bool = False):
    del payload, show_private
    try:
        _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    raise HTTPException(status_code=501, detail="Human matches are temporarily disabled")


@app.post("/api/rooms/{room_id}/pause")
def pause_room_game(room_id: str):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    if not room.current_game_id:
        raise HTTPException(status_code=409, detail="No running game")
    try:
        _match_jobs.set_control_state(room.current_game_id, "paused")
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    room = _rooms.set_room_status(room_id, "paused")
    return {"room_id": room_id, "paused": True, "status": room.status}


@app.post("/api/rooms/{room_id}/resume")
def resume_room_game(room_id: str):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    if not room.current_game_id:
        raise HTTPException(status_code=409, detail="No running game")
    try:
        _match_jobs.set_control_state(room.current_game_id, "running")
    except (KeyError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    room = _rooms.set_room_status(room_id, "running")
    return {"room_id": room_id, "paused": False, "status": room.status}


@app.get("/api/rooms/{room_id}/control-status")
def room_control_status(room_id: str):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    job = _match_jobs.get_by_game_id(room.current_game_id) if room.current_game_id else None
    return {
        "room_id": room_id,
        "status": job["status"] if job else room.status,
        "paused": bool(job and job["control_state"] == "paused"),
        "running": bool(job and job["status"] in {"queued", "running"}),
    }


@app.get("/api/matches/{match_id}")
def get_match_execution(match_id: str):
    job = _match_jobs.get_by_game_id(match_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Match execution not found")
    return job


@app.get("/")
def index():
    """Backend root — the UI lives in the Next.js app on port 3001."""
    return {
        "message": "AI Werewolf backend is running.",
        "ui": "http://localhost:3001",
        "docs": "/docs",
    }
