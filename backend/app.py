from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.models import GameState
from backend.protocols import RoomCreateRequest, RoomManager


app = FastAPI(title="AI Werewolf Demo", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
_rooms = RoomManager()


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _build_game(seed: int, agent_type: str = "llm") -> WerewolfGame:
    game = WerewolfGame(seed=seed)
    game.agents = create_agents(game.state.players, {"type": agent_type, "seed": seed})
    return game


@app.post("/api/games")
def create_game(seed: int = 7, show_private: bool = False, agent_type: str = "llm"):
    game = _build_game(seed=seed, agent_type=agent_type)
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


@app.post("/api/rooms")
def create_room(name: str = "Demo Room", seed: int = 7, player_count: int = 7, agent_type: str = "llm"):
    request = RoomCreateRequest(name=name, seed=seed, player_count=player_count, agent_type=agent_type)
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
    game = _build_game(seed=room.seed, agent_type=room.agent_type)
    state = game.play()
    snapshot = state.snapshot(show_private=show_private)
    _rooms.record_game(room_id, state, snapshot)
    return snapshot


async def stream_game(websocket: WebSocket, seed: int, show_private: bool, agent_type: str = "llm", room_id: str | None = None) -> GameState:
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

    game = _build_game(seed=seed, agent_type=agent_type)
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
            state = await stream_game(websocket, seed, show_private, agent_type=agent_type)
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
            show_private = bool(payload.get("show_private", False))
            room.seed = int(payload.get("seed", room.seed))
            room.agent_type = str(payload.get("agent_type", room.agent_type))
            _rooms.set_room_status(room_id, "running")
            await websocket.send_json({"type": "room", "room": room.to_dict()})
            state = await stream_game(websocket, room.seed, show_private, agent_type=room.agent_type, room_id=room_id)
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
