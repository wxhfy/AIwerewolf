from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
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
    return get_review_reports(game_id)


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
    """Stream game snapshots to WebSocket in real-time as the game progresses."""
    import threading
    import asyncio as aio

    loop = aio.get_running_loop()
    # Thread-safe queue for real-time snapshot delivery
    queue: list[dict] = []
    lock = threading.Lock()
    done = threading.Event()

    def observe(state: GameState) -> None:
        snapshot = state.snapshot(show_private=show_private)
        with lock:
            queue.append(snapshot)

    game = _build_game(seed=seed, agent_type=agent_type, player_count=player_count, rule_pack_id=rule_pack_id)
    game.observer = observe

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
            await aio.sleep(0.3)  # poll every 300ms

    # Run game in thread, drain snapshots in parallel
    async def run_game() -> GameState:
        return await loop.run_in_executor(None, game.play)

    drain_task = aio.create_task(drain_queue())
    try:
        state = await run_game()
    finally:
        done.set()
        await drain_task

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


if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/")
def index():
    index_file = _frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "AI Werewolf backend is running."}
