from __future__ import annotations

from typing import Any

from backend.db.database import SessionLocal
from backend.db.models import MatchCommand
from backend.db.models import OutboxEvent


class MatchCommandRepository:
    def get(self, command_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            row = db.query(MatchCommand).filter(MatchCommand.id == command_id).first()
            return self._to_dict(row) if row else None

    def create(
        self,
        *,
        command_id: str,
        match_id: str,
        command_type: str,
        actor_id: str,
        expected_seq: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with SessionLocal.begin() as db:
            existing = db.query(MatchCommand).filter(MatchCommand.id == command_id).first()
            if existing is not None:
                return self._to_dict(existing)
            row = MatchCommand(
                id=command_id,
                match_id=match_id,
                command_type=command_type,
                actor_id=actor_id,
                expected_seq=expected_seq,
                payload=payload,
                status="accepted",
            )
            db.add(row)
            db.flush()
            return self._to_dict(row)

    def complete(self, command_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with SessionLocal.begin() as db:
            row = db.query(MatchCommand).filter(MatchCommand.id == command_id).one()
            row.status = "completed"
            row.result = result
            row.error = None
            db.add(
                OutboxEvent(
                    aggregate_type="match",
                    aggregate_id=row.match_id,
                    event_type=f"match.command.{row.command_type}.completed",
                    payload={"command_id": row.id, "result": result},
                )
            )
            db.flush()
            return self._to_dict(row)

    def fail(self, command_id: str, error: str, *, status: str = "failed") -> dict[str, Any]:
        with SessionLocal.begin() as db:
            row = db.query(MatchCommand).filter(MatchCommand.id == command_id).one()
            row.status = status
            row.error = error[:4000]
            db.flush()
            return self._to_dict(row)

    @staticmethod
    def _to_dict(row: MatchCommand) -> dict[str, Any]:
        return {
            "command_id": row.id,
            "match_id": row.match_id,
            "type": row.command_type,
            "status": row.status,
            "result": dict(row.result or {}),
            "error": row.error,
        }
