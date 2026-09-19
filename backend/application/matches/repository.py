from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from sqlalchemy import or_

from backend.db.database import SessionLocal
from backend.db.models import Game
from backend.db.models import GameRoom
from backend.db.models import GameSnapshot
from backend.db.models import MatchJob


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ClaimedMatchJob:
    id: str
    game_id: str
    room_id: str
    payload: dict[str, Any]
    attempts: int


class MatchJobRepository:
    """PostgreSQL-backed queue with row locking and worker leases."""

    def prepare(self, *, game_id: str, room_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with SessionLocal.begin() as db:
            row = db.query(MatchJob).filter(MatchJob.game_id == game_id).first()
            if row is None:
                row = MatchJob(game_id=game_id, room_id=room_id, payload=payload, status="prepared")
                db.add(row)
                db.flush()
            elif row.status == "prepared":
                row.payload = payload
            game = db.query(Game).filter(Game.id == game_id).first()
            if game is not None and game.status != "finished":
                game.status = "prepared"
            return self._to_dict(row)

    def enqueue(
        self,
        *,
        game_id: str,
        room_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with SessionLocal.begin() as db:
            row = db.query(MatchJob).filter(MatchJob.game_id == game_id).first()
            if row is None:
                if payload is None:
                    raise KeyError(game_id)
                row = MatchJob(game_id=game_id, room_id=room_id, payload=payload)
                db.add(row)
                db.flush()
            elif row.status not in {"running", "completed"}:
                row.status = "queued"
                row.control_state = "running"
                row.finished_at = None
                row.last_error = ""
                if payload is not None:
                    row.payload = payload
            game = db.query(Game).filter(Game.id == game_id).first()
            if game is not None and game.status != "finished":
                game.status = row.status
            return self._to_dict(row)

    def claim_next(self, worker_id: str, *, lease_seconds: int = 600) -> ClaimedMatchJob | None:
        return self._claim(worker_id, lease_seconds=lease_seconds)

    def claim_game(
        self,
        game_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 600,
    ) -> ClaimedMatchJob | None:
        return self._claim(worker_id, game_id=game_id, lease_seconds=lease_seconds)

    def _claim(
        self,
        worker_id: str,
        *,
        game_id: str | None = None,
        lease_seconds: int = 600,
    ) -> ClaimedMatchJob | None:
        now = _now()
        with SessionLocal.begin() as db:
            query = db.query(MatchJob).filter(
                MatchJob.status == "queued",
                MatchJob.control_state == "running",
            )
            if game_id is not None:
                query = query.filter(MatchJob.game_id == game_id)
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = query.order_by(MatchJob.created_at.asc()).first()
            if row is None:
                return None
            row.status = "running"
            row.worker_id = worker_id
            row.attempts = int(row.attempts or 0) + 1
            row.started_at = row.started_at or now
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            game = db.query(Game).filter(Game.id == row.game_id).first()
            if game is not None:
                game.status = "running"
            room = db.query(GameRoom).filter(GameRoom.id == row.room_id).first()
            if room is not None:
                room.status = "running"
                room.updated_at = now.timestamp()
            db.flush()
            return ClaimedMatchJob(row.id, row.game_id, row.room_id, dict(row.payload or {}), row.attempts)

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: int = 600) -> str:
        now = _now()
        with SessionLocal.begin() as db:
            row = db.query(MatchJob).filter(MatchJob.id == job_id, MatchJob.worker_id == worker_id).first()
            if row is None:
                raise RuntimeError(f"Worker {worker_id} no longer owns job {job_id}")
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return str(row.control_state)

    def complete(self, job_id: str, worker_id: str) -> None:
        with SessionLocal.begin() as db:
            row = db.query(MatchJob).filter(MatchJob.id == job_id, MatchJob.worker_id == worker_id).first()
            if row is None:
                raise RuntimeError(f"Worker {worker_id} no longer owns job {job_id}")
            row.status = "completed"
            row.control_state = "completed"
            row.finished_at = _now()
            row.lease_expires_at = None
            row.last_error = ""
            room = db.query(GameRoom).filter(GameRoom.id == row.room_id).first()
            if room is not None:
                history = list(room.game_history or [])
                if row.game_id not in history:
                    history.append(row.game_id)
                room.game_history = history
                room.current_game_id = row.game_id
                room.status = "completed"
                room.updated_at = _now().timestamp()
                snapshot = (
                    db.query(GameSnapshot)
                    .filter(GameSnapshot.game_id == row.game_id)
                    .order_by(GameSnapshot.seq.desc())
                    .first()
                )
                if snapshot is not None:
                    room.latest_snapshot = snapshot.truth_state

    def fail(self, job_id: str, worker_id: str, error: str) -> None:
        with SessionLocal.begin() as db:
            row = db.query(MatchJob).filter(MatchJob.id == job_id, MatchJob.worker_id == worker_id).first()
            if row is None:
                return
            row.status = "failed"
            row.finished_at = _now()
            row.lease_expires_at = None
            row.last_error = error[:8000]
            game = db.query(Game).filter(Game.id == row.game_id).first()
            if game is not None and game.status != "finished":
                game.status = "failed"
            room = db.query(GameRoom).filter(GameRoom.id == row.room_id).first()
            if room is not None:
                room.status = "failed"
                room.updated_at = _now().timestamp()

    def set_control_state(self, game_id: str, state: str) -> dict[str, Any]:
        if state not in {"running", "paused"}:
            raise ValueError(f"Unsupported control state: {state}")
        with SessionLocal.begin() as db:
            row = db.query(MatchJob).filter(MatchJob.game_id == game_id).first()
            if row is None:
                raise KeyError(game_id)
            if row.status in {"completed", "failed"}:
                raise RuntimeError(f"Match is already {row.status}")
            row.control_state = state
            return self._to_dict(row)

    def get_by_game_id(self, game_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            row = db.query(MatchJob).filter(MatchJob.game_id == game_id).first()
            return self._to_dict(row) if row else None

    def get_latest_for_room(self, room_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            row = db.query(MatchJob).filter(MatchJob.room_id == room_id).order_by(MatchJob.created_at.desc()).first()
            return self._to_dict(row) if row else None

    def list_for_room(self, room_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.query(MatchJob).filter(MatchJob.room_id == room_id).order_by(MatchJob.created_at.desc()).all()
            return [self._to_dict(row) for row in rows]

    def fail_expired_leases(self) -> int:
        now = _now()
        with SessionLocal.begin() as db:
            rows = (
                db.query(MatchJob)
                .filter(
                    MatchJob.status == "running",
                    or_(MatchJob.lease_expires_at.is_(None), MatchJob.lease_expires_at < now),
                )
                .all()
            )
            for row in rows:
                row.status = "failed"
                row.finished_at = now
                row.last_error = "Worker lease expired; automatic replay is disabled to avoid duplicate LLM actions."
                game = db.query(Game).filter(Game.id == row.game_id).first()
                if game is not None and game.status != "finished":
                    game.status = "failed"
            return len(rows)

    @staticmethod
    def _to_dict(row: MatchJob) -> dict[str, Any]:
        return {
            "id": row.id,
            "match_id": row.game_id,
            "room_id": row.room_id,
            "status": row.status,
            "control_state": row.control_state,
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "worker_id": row.worker_id,
            "last_error": row.last_error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
