from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.agents.factory import create_agents
from backend.db.database import init_db
from backend.engine.game import WerewolfGame
from backend.engine.models import GameState
from backend.engine.rules import build_players, get_role_configuration
from backend.protocols import RoomCreateRequest, RoomManager


app = FastAPI(title="AI Werewolf Demo", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rooms = RoomManager()


@app.on_event("startup")
def _initialize_database() -> None:
    try:
        init_db()
    except Exception:
        pass


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _build_game(
    seed: int,
    agent_type: str = "llm",
    human_seat: Optional[int] = None,
    player_count: int = 7,
    rule_pack_id: str = "wolfcha-default",
) -> WerewolfGame:
    players = build_players(get_role_configuration(player_count), seed=seed)
    game = WerewolfGame(seed=seed, players=players)
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
    player_count: int = 7,
    rule_pack_id: str = "wolfcha-default",
):
    game = _build_game(seed=seed, agent_type=agent_type, human_seat=human_seat, player_count=player_count, rule_pack_id=rule_pack_id)
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


@app.get("/api/leaderboard")
def leaderboard(role: Optional[str] = None, limit: int = 20):
    """Aggregated leaderboard rows (Track B). Filter by role if provided."""
    from backend.db.persist import get_leaderboard
    return get_leaderboard(role=role, limit=limit)


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


@app.post("/api/rooms")
def create_room(
    name: str = "Demo Room",
    seed: int = 7,
    player_count: int = 7,
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
        snapshot = state.snapshot(show_private=show_private)
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
    snapshot = state.snapshot(show_private=show_private)
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
    snapshot = state.snapshot(show_private=show_private)
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
) -> GameState:
    """Stream game snapshots to WebSocket in real-time as the game progresses.

    Supports reconnect: if the room already has an active (running) game, we
    attach to it instead of starting a second parallel game. Reconnecting
    clients first receive the entire snapshot buffer accumulated so far, then
    follow live frames until the game finishes.
    """
    import threading
    import asyncio as aio

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
        game = _build_game(seed=seed, agent_type=agent_type, player_count=player_count, rule_pack_id=rule_pack_id)
        if room_id:
            _rooms.set_active_game(room_id, game)
            _rooms.reset_snapshot_buffer(room_id)

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
            await websocket.send_json({"type": "status", "status": "starting"})
            player_count = int(payload.get("player_count", 7))
            state = await stream_game(websocket, seed, show_private, agent_type=agent_type, player_count=player_count)
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
                await websocket.send_json({"type": "error", "message": "Human rooms use /api/rooms/{room_id}/start and /action."})
                continue
            show_private = bool(payload.get("show_private", False))
            room.seed = int(payload.get("seed", room.seed))
            room.agent_type = str(payload.get("agent_type", room.agent_type))
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
            )
            final = state.snapshot(show_private=show_private)
            room = _rooms.record_game(room_id, state, final)
            await websocket.send_json({"type": "complete", "state": final, "room": room.to_dict()})
    except WebSocketDisconnect:
        return


@app.get("/")
def index():
    """Backend root — the UI lives in the Next.js app on port 3002."""
    return {
        "message": "AI Werewolf backend is running.",
        "ui": "http://localhost:3002",
        "docs": "/docs",
    }
