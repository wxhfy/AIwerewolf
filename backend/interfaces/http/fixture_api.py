from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from typing import Optional

from fastapi import APIRouter
from fastapi import Body
from fastapi import HTTPException

from backend.db.database import SessionLocal
from backend.db.models import Game
from backend.db.models import GameRoom
from backend.db.models import GameSnapshot
from backend.db.persist import save_snapshot
from backend.db.persist import set_game_status
from backend.infrastructure.messaging.match_notifications import match_notifications
from backend.protocols.schemas import RoomCreateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev/fixture", tags=["fixture"])

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "slice1_ai_match.json"

_rooms: Any = None


def bind_room_store(rooms: Any) -> None:
    """Module-level setter so app.py can inject _rooms without circular import."""
    global _rooms
    _rooms = rooms


def _enabled() -> bool:
    return os.getenv("AW_ENABLE_FIXTURE") == "1"


def _require_enabled() -> None:
    if not _enabled():
        raise HTTPException(status_code=404, detail="fixture disabled")


def _load_fixture_snapshots() -> list[dict[str, Any]]:
    if not FIXTURE_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"Fixture file not found at {FIXTURE_PATH}")
    try:
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("snapshots", []))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load fixture JSON: {exc}")


def _replay_worker(target_room_id: str, target_game_id: str, delay_sec: float) -> None:
    try:
        snapshots = _load_fixture_snapshots()
        for s in snapshots:
            snap = copy.deepcopy(s)
            snap["id"] = target_game_id
            seq = int(snap["seq"])
            day = int(snap.get("day") or 0)
            phase = str(snap.get("phase") or "")
            save_snapshot(
                target_game_id,
                seq,
                day,
                phase,
                snap,
                snap,
            )  # truth==public intentional for public-only fixture
            if _rooms is not None:
                _rooms.record_snapshot(target_room_id, snap)
            match_notifications.publish(target_game_id, seq)
            time.sleep(delay_sec)
        set_game_status(target_game_id, "finished")
    except Exception:
        logger.exception("Fixture replay failed for game_id=%s", target_game_id)


@router.post("/start")
def start_fixture(payload: Optional[dict[str, Any]] = Body(default=None)) -> dict[str, Any]:
    _require_enabled()
    if _rooms is None:
        raise HTTPException(status_code=500, detail="Room store not bound")

    logger.warning("FIXTURE/MOCK replay started — not a real LLM acceptance")

    body = payload or {}
    interval_ms_val = body.get("interval_ms", 400)
    try:
        interval_ms = int(interval_ms_val)
    except (ValueError, TypeError):
        interval_ms = 400

    room_name = str(body.get("room_name") or "FIXTURE观战")

    snapshots = _load_fixture_snapshots()
    snapshot_count = len(snapshots)

    create_req = RoomCreateRequest(
        name=room_name,
        seed=7,
        player_count=7,
        agent_type="llm",
    )
    try:
        room = _rooms.create_room(create_req)
    except TypeError:
        room = _rooms.create_room(name=room_name, seed=7, player_count=7, agent_type="llm")

    game_id = str(uuid.uuid4())

    with SessionLocal() as db:
        game = Game(
            id=game_id,
            status="running",
            current_day=0,
            current_phase="SETUP",
            seed="7",
        )
        db.add(game)
        db.commit()

    room.current_game_id = game_id
    with SessionLocal.begin() as db:
        row = db.query(GameRoom).filter(GameRoom.id == room.id).first()
        if row is not None:
            row.current_game_id = game_id
            row.updated_at = time.time()
    if hasattr(_rooms, "set_current_game_id"):
        try:
            _rooms.set_current_game_id(room.id, game_id)
        except Exception:
            pass

    delay_sec = max(0.01, interval_ms / 1000.0)
    thread = threading.Thread(
        target=_replay_worker,
        args=(room.id, game_id, delay_sec),
        daemon=True,
    )
    thread.start()

    return {
        "fixture": "FIXTURE/MOCK",
        "note": "Offline canned AI match replay. NOT a real LLM run.",
        "room_id": room.id,
        "game_id": game_id,
        "snapshot_count": snapshot_count,
        "interval_ms": interval_ms,
    }


@router.get("/status/{game_id}")
def get_fixture_status(game_id: str) -> dict[str, Any]:
    _require_enabled()
    with SessionLocal() as db:
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            raise HTTPException(status_code=404, detail=f"Game '{game_id}' not found")

        last_snapshot = (
            db.query(GameSnapshot)
            .filter(GameSnapshot.game_id == game_id)
            .order_by(GameSnapshot.seq.desc())
            .first()
        )
        last_seq = last_snapshot.seq if last_snapshot is not None else None

        return {
            "fixture": "FIXTURE/MOCK",
            "note": "Offline canned AI match replay. NOT a real LLM run.",
            "game_id": game_id,
            "status": game.status,
            "last_snapshot_seq": last_seq,
            "current_day": game.current_day,
            "current_phase": game.current_phase,
        }


__all__ = ["router", "bind_room_store"]
