from __future__ import annotations

import json
from typing import Any
from typing import Dict
from typing import Optional

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.responses import Response

from backend.agents.factory import create_agents
from backend.db.database import init_db
from backend.engine.game import WerewolfGame
from backend.engine.models import GameState
from backend.protocols import RoomCreateRequest
from backend.protocols import RoomManager

app = FastAPI(title="AI Werewolf Demo", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rooms = RoomManager()


def _sample_personas(count: int, seed: int | None) -> list[dict] | None:
    from backend.db.persona_db import sample_personas

    return sample_personas(count, seed=seed)


def _save_game_start(state: GameState) -> None:
    from backend.db.persist import save_game_start

    save_game_start(state)


def _save_game_end(state: GameState) -> None:
    from backend.db.persist import save_game_end

    save_game_end(state)


def _save_decisions(decisions: list[dict]) -> int:
    from backend.db.persist import save_decisions_batch

    return save_decisions_batch(decisions)


def _run_post_game_scoring(state: GameState) -> None:
    import logging
    import os

    from backend.eval.post_game import run_post_game_scoring

    count = run_post_game_scoring(state, str(state.id))
    if count > 0:
        logging.getLogger(__name__).info(
            "Post-game scoring: %s knowledge lessons extracted for game %s",
            count,
            state.id,
        )
    elif os.getenv("REQUIRE_POST_GAME_SCORING", "").lower() == "true":
        logging.getLogger(__name__).error("STRICT FAIL: Post-game scoring produced 0 lessons")


@app.on_event("startup")
def _initialize_database() -> None:
    try:
        init_db()
    except Exception:
        pass


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
    result["checks"]["strict_mode"] = os.getenv("AIWEREWOLF_STRICT_MODE", "false")
    result["version"] = "0.1.0"

    return result


def _build_game(
    seed: int,
    agent_type: str = "llm",
    human_seat: Optional[int] = None,
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
    phase_delay_ms: float = 0,
) -> WerewolfGame:
    game = WerewolfGame(
        seed=seed,
        player_count=player_count,
        phase_delay_ms=phase_delay_ms,
        persona_sampler=_sample_personas,
        on_game_start=_save_game_start,
        on_game_end=_save_game_end,
        on_decisions_flush=_save_decisions,
        on_post_game=_run_post_game_scoring,
    )
    game.attach_agents(
        create_agents(
            game.state.players,
            {
                "type": agent_type,
                "seed": seed,
                "human_seat": human_seat,
                "character_map": game.characters,
            },
        )
    )
    return game


@app.post("/api/games")
def create_game(
    seed: int = 7,
    show_private: bool = False,
    agent_type: str = "llm",
    human_seat: Optional[int] = None,
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
):
    try:
        game = _build_game(
            seed=seed,
            agent_type=agent_type,
            human_seat=human_seat,
            player_count=player_count,
            rule_pack_id=rule_pack_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if human_seat is not None:
        state = game.play_until_blocked()
        _rooms.games[state.id] = state
        return state.snapshot(show_private=show_private)
    state = game.play()
    _rooms.games[state.id] = state
    return state.moderator_dict() if show_private else state.public_dict()


@app.get("/api/games/{game_id}")
def get_game(game_id: str, show_private: bool = False):
    try:
        state = _rooms.get_game(game_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Game not found")
    return state.moderator_dict() if show_private else state.public_dict()


@app.get("/api/games")
def list_games():
    return _rooms.list_games()


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
):
    request = RoomCreateRequest(
        name=name,
        seed=seed,
        player_count=player_count,
        agent_type=agent_type,
        human_seat=human_seat,
        rule_pack_id=rule_pack_id,
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
        return _rooms.list_room_games(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")


@app.get("/api/rooms/{room_id}/snapshot")
def get_room_snapshot(room_id: str):
    try:
        snapshot = _rooms.get_latest_snapshot(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@app.post("/api/rooms/{room_id}/games")
def create_room_game(room_id: str, show_private: bool = False):
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    game = _build_game(
        seed=room.seed,
        agent_type=room.agent_type,
        human_seat=room.human_seat,
        player_count=room.player_count,
        rule_pack_id=room.rule_pack_id,
    )
    if room.human_seat is not None:
        _rooms.set_active_game(room_id, game)
        state = game.play_until_blocked()
        snapshot = state.snapshot(show_private=True)
        _rooms.record_snapshot(room_id, snapshot)
        if state.winner is not None:
            _rooms.record_game(room_id, state, snapshot)
        return snapshot
    state = game.play()
    snapshot = state.snapshot(show_private=show_private)
    _rooms.record_game(room_id, state, snapshot)
    return snapshot


@app.post("/api/rooms/{room_id}/prepare")
def prepare_room_game(room_id: str, show_private: bool = False):
    """Create the game shell so the lobby has roles + personas to show
    immediately, without advancing past SETUP.

    Flow: lobby Confirm → POST /prepare → setGameState(snapshot) → navigate to
    play page → play page sees full roster → WebSocket connects → stream_game
    detects the prepared active_game and starts game.play() itself.

    Idempotent for a given room: if a game is already prepared but not started
    (or even already running), we just return its current snapshot.
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
    game = _build_game(
        seed=room.seed,
        agent_type=room.agent_type,
        human_seat=room.human_seat,
        player_count=room.player_count,
        rule_pack_id=room.rule_pack_id,
    )
    _rooms.set_active_game(room_id, game)
    _rooms.reset_snapshot_buffer(room_id)

    # Wire the observer BEFORE initialize() so the GAME_START event and the
    # role-assignment private events are captured in the room's snapshot
    # buffer — a reconnecting client picks them up via the WS reuse path.
    def _observer(state):
        _rooms.append_snapshot(room_id, state.snapshot(show_private=show_private))

    game.observer = _observer
    game.initialize()
    try:
        from backend.db.persist import save_game_start

        save_game_start(game.state)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("save_game_start failed during room prepare", exc_info=True)
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
    if game is None:
        game = _build_game(
            seed=room.seed,
            agent_type=room.agent_type,
            human_seat=room.human_seat,
            player_count=room.player_count,
            rule_pack_id=room.rule_pack_id,
        )
    _rooms.set_active_game(room_id, game)
    state = game.play_until_blocked()
    snapshot = state.snapshot(show_private=show_private or room.human_seat is not None)
    _rooms.record_snapshot(room_id, snapshot)
    if state.winner is not None:
        _rooms.record_game(room_id, state, snapshot)
    return snapshot


@app.post("/api/rooms/{room_id}/action")
def submit_room_action(room_id: str, payload: Dict[str, Any], show_private: bool = False):
    try:
        game = _rooms.get_active_game(room_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Room not found")
    if game is None:
        raise HTTPException(status_code=409, detail="No active game")
    try:
        state = game.submit_human_action(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        room = None
    snapshot = state.snapshot(show_private=show_private or (room is not None and room.human_seat is not None))
    _rooms.record_snapshot(room_id, snapshot)
    if state.winner is not None:
        _rooms.record_game(room_id, state, snapshot)
    return snapshot


async def stream_game(
    websocket: WebSocket,
    seed: int,
    show_private: bool,
    agent_type: str = "llm",
    room_id: str | None = None,
    player_count: int = 7,
    rule_pack_id: str = "wolfcha-default",
    delay_ms: float = 800,
) -> GameState:
    """Stream game snapshots to WebSocket in real-time as the game progresses.

    Supports reconnect: if the room already has an active (running) game, we
    attach to it instead of starting a second parallel game. Reconnecting
    clients first receive the entire snapshot buffer accumulated so far, then
    follow live frames until the game finishes.
    """
    import asyncio as aio
    import threading

    loop = aio.get_running_loop()
    # Thread-safe queue for real-time snapshot delivery
    queue: list[dict] = []
    lock = threading.Lock()
    done = threading.Event()

    # Reconnect path: if an unfinished game already runs for this room, attach
    # to it instead of building a fresh one. There are now TWO reconnect
    # sub-cases:
    #   - "prepared, not started" — POST /prepare built the game and called
    #     initialize() but nobody called play() yet. We're the first WS, so we
    #     should drive game.play() ourselves.
    #   - "started, running" — another stream_game call is already executing
    #     game.play() in its executor. We just tail snapshots.
    # We distinguish via game._play_started, set inside play()'s start lock.
    is_reused_running = False
    game: WerewolfGame | None = None
    if room_id:
        existing = _rooms.get_active_game(room_id)
        if existing is not None and existing.state.winner is None:
            game = existing
            is_reused_running = game._play_started

    if game is None:
        game = _build_game(
            seed=seed,
            agent_type=agent_type,
            player_count=player_count,
            rule_pack_id=rule_pack_id,
            phase_delay_ms=delay_ms,
        )
        if room_id:
            _rooms.set_active_game(room_id, game)
            _rooms.reset_snapshot_buffer(room_id)
    else:
        # Override the delay on an existing game so the WS caller's speed
        # preference takes effect even when the game was pre-built by /prepare.
        game.phase_delay_ms = delay_ms

    def observe(state: GameState) -> None:
        snapshot = state.snapshot(show_private=show_private)
        if room_id:
            _rooms.append_snapshot(room_id, snapshot)
        with lock:
            queue.append(snapshot)

    # The engine only supports one observer; the previous WS's observer (if
    # any) is now disconnected and its drain task is dead, so overwriting is
    # safe — but we still pre-load this client with the full history first.
    game.observer = observe
    if room_id and (is_reused_running or game._play_started):
        with lock:
            queue.extend(_rooms.get_snapshot_buffer(room_id))
    elif room_id and game.state.events:
        # Prepared-not-started: the initialize() call emitted GAME_START and
        # role_assignment events that the lobby already showed via the
        # /prepare response. Replay them so the WS client sees the same
        # baseline before live frames start streaming.
        with lock:
            queue.extend(_rooms.get_snapshot_buffer(room_id))

    async def drain_queue() -> None:
        """Send queued snapshots to the WebSocket as they arrive."""
        last_idx = 0
        while not done.is_set():
            with lock:
                new_snapshots = queue[last_idx:]
                last_idx = len(queue)
            for snap in new_snapshots:
                msg: dict = {"type": "snapshot", "state": snap}
                if room_id:
                    msg["room_id"] = room_id
                    _rooms.record_snapshot(room_id, snap)
                await websocket.send_json(msg)
            # Task 3: Check for streaming tokens from LLM calls
            stream_tokens = getattr(game, "_stream_token_buffer", None)
            if stream_tokens:
                tokens_to_send = []
                while not stream_tokens.empty():
                    try:
                        token = stream_tokens.get_nowait()
                        tokens_to_send.append(token)
                    except Exception:
                        break
                for token_data in tokens_to_send:
                    await websocket.send_json({"type": "stream_token", **token_data})
            await aio.sleep(0.08)  # poll every 80ms (was 300ms — felt sluggish during LLM turns)
        # Final flush so we don't drop snapshots queued between the last loop
        # iteration and done.set().
        with lock:
            new_snapshots = queue[last_idx:]
        for snap in new_snapshots:
            msg = {"type": "snapshot", "state": snap}
            if room_id:
                msg["room_id"] = room_id
                _rooms.record_snapshot(room_id, snap)
            try:
                await websocket.send_json(msg)
            except Exception:
                break
        # Task 3: Final flush of any remaining stream tokens
        stream_tokens = getattr(game, "_stream_token_buffer", None)
        if stream_tokens:
            while not stream_tokens.empty():
                try:
                    token = stream_tokens.get_nowait()
                    await websocket.send_json({"type": "stream_token", **token})
                except Exception:
                    break

    drain_task = aio.create_task(drain_queue())
    try:
        if is_reused_running:
            # The game is already executing in another thread; just tail the
            # snapshot stream until it finishes. Poll cadence is generous —
            # what matters for UX is drain_queue's 80ms cycle.
            while game.state.winner is None and not game.play_done.is_set():
                await aio.sleep(0.5)
            state = game.state
        else:
            # Either fresh game or prepared-but-not-started — we drive
            # game.play() ourselves. The idempotent guard inside play()
            # makes this safe even if a second WS races us.
            state = await loop.run_in_executor(None, game.play)
    finally:
        done.set()
        try:
            await drain_task
        except Exception:
            pass

    _rooms.games[state.id] = state
    return state


@app.websocket("/ws/games")
async def games_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("action") != "start":
                await websocket.send_json({"type": "error", "message": "Unsupported action"})
                continue
            seed = int(payload.get("seed", 7))
            agent_type = str(payload.get("agent_type", "llm"))
            show_private = bool(payload.get("show_private", False))
            delay_ms = max(0, float(payload.get("delay_ms", 800)))
            await websocket.send_json({"type": "status", "status": "starting"})
            player_count = int(payload.get("player_count", 7))
            state = await stream_game(
                websocket, seed, show_private, agent_type=agent_type, player_count=player_count, delay_ms=delay_ms
            )
            final = state.snapshot(show_private=show_private)
            await websocket.send_json({"type": "complete", "state": final})
    except WebSocketDisconnect:
        return


@app.websocket("/ws/rooms/{room_id}")
async def room_ws(websocket: WebSocket, room_id: str) -> None:
    await websocket.accept()
    try:
        room = _rooms.get_room(room_id)
    except KeyError:
        await websocket.send_json({"type": "error", "message": "Room not found"})
        await websocket.close()
        return

    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("action") != "start":
                await websocket.send_json({"type": "error", "message": "Unsupported action"})
                continue
            if room.human_seat is not None:
                await websocket.send_json(
                    {"type": "error", "message": "Human rooms use /api/rooms/{room_id}/start and /action."}
                )
                continue
            show_private = bool(payload.get("show_private", False))
            room.seed = int(payload.get("seed", room.seed))
            room.agent_type = str(payload.get("agent_type", room.agent_type))
            delay_ms = max(0, float(payload.get("delay_ms", 800)))
            _rooms.set_room_status(room_id, "running")
            await websocket.send_json({"type": "room", "room": room.to_dict()})
            state = await stream_game(
                websocket,
                room.seed,
                show_private,
                agent_type=room.agent_type,
                room_id=room_id,
                player_count=room.player_count,
                rule_pack_id=room.rule_pack_id,
                delay_ms=delay_ms,
            )
            final = state.snapshot(show_private=show_private)
            room = _rooms.record_game(room_id, state, final)
            try:
                await websocket.send_json({"type": "complete", "state": final, "room": room.to_dict()})
            except (RuntimeError, WebSocketDisconnect):
                return
    except WebSocketDisconnect:
        return


@app.get("/")
def index():
    """Backend root — the UI lives in the Next.js app on port 3001."""
    return {
        "message": "AI Werewolf backend is running.",
        "ui": "http://localhost:3001",
        "docs": "/docs",
    }
