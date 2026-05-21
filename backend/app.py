from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.engine.game import WerewolfGame
from backend.engine.models import GameState


app = FastAPI(title="AI Werewolf Demo", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_games: dict[str, GameState] = {}
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/games")
def create_game(seed: int = 7, show_private: bool = False):
    game = WerewolfGame(seed=seed)
    state = game.play()
    _games[state.id] = state
    return state.moderator_dict() if show_private else state.public_dict()


@app.get("/api/games/{game_id}")
def get_game(game_id: str, show_private: bool = False):
    state = _games.get(game_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return state.moderator_dict() if show_private else state.public_dict()


@app.get("/api/games")
def list_games():
    return [
        {
            "id": state.id,
            "day": state.day,
            "phase": state.phase.value,
            "winner": state.winner.value if state.winner else None,
        }
        for state in _games.values()
    ]


if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


@app.get("/")
def index():
    index_file = _frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "AI Werewolf backend is running."}
