from __future__ import annotations

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.events import HarnessEvent
from backend.db.database import SessionLocal
from backend.db.models import AgentHarnessEvent


class SqlHarnessEventRepository:
    """Persist Harness traces outside agent decision metadata for audit and replay."""

    def save(self, request: DecisionRequest, events: tuple[HarnessEvent, ...]) -> None:
        if not events:
            return
        with SessionLocal.begin() as db:
            existing = {
                row[0]
                for row in db.query(AgentHarnessEvent.seq)
                .filter(AgentHarnessEvent.request_id == request.request_id)
                .all()
            }
            for event in events:
                if event.seq in existing:
                    continue
                record = event.to_record()
                db.add(
                    AgentHarnessEvent(
                        game_id=request.episode_id,
                        player_id=request.actor.actor_id,
                        request_id=request.request_id,
                        seq=event.seq,
                        event_type=event.event_type,
                        step=event.step,
                        timestamp_ms=event.timestamp_ms,
                        payload=record["payload"],
                    )
                )
