"""Durable heartbeats, observable across API and worker processes."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import String
from sqlalchemy.exc import IntegrityError

from backend.core.observability import count
from backend.core.observability import log_event
from backend.db.database import SessionLocal
from backend.db.models import Base

logger = logging.getLogger(__name__)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id = Column(String, primary_key=True)
    worker_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="running")
    heartbeat_at = Column(DateTime, nullable=False)


def record_heartbeat(worker_id: str, worker_type: str, *, status: str = "running") -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = db.get(WorkerHeartbeat, worker_id)
        if row is None:
            try:
                with db.begin_nested():
                    row = WorkerHeartbeat(worker_id=worker_id, worker_type=worker_type, status=status, heartbeat_at=now)
                    db.add(row)
                    db.flush()
            except IntegrityError:
                row = db.get(WorkerHeartbeat, worker_id)
        row.status = status
        row.heartbeat_at = now
        db.commit()


def worker_health(*, stale_after_seconds: int = 90) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    with SessionLocal() as db:
        rows = db.query(WorkerHeartbeat).order_by(WorkerHeartbeat.worker_type, WorkerHeartbeat.worker_id).all()
        workers = [
            {
                "worker_id": row.worker_id,
                "worker_type": row.worker_type,
                "status": row.status if row.heartbeat_at.replace(tzinfo=timezone.utc) > cutoff else "stale",
                "heartbeat_at": row.heartbeat_at.isoformat(),
            }
            for row in rows
        ]
    return {"workers": workers, "stale_after_seconds": stale_after_seconds}


class WorkerHeartbeatLoop:
    """Refresh even during long tournaments or match executions; never owns jobs."""

    def __init__(self, worker_id: str, worker_type: str, *, interval_seconds: float = 15):
        self.worker_id = worker_id
        self.worker_type = worker_type
        self.interval_seconds = max(0.1, interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _record(self, status: str = "running") -> None:
        try:
            record_heartbeat(self.worker_id, self.worker_type, status=status)
        except Exception as exc:
            count("worker.heartbeat.failed")
            log_event(
                logger,
                "worker.heartbeat.failed",
                level=logging.WARNING,
                worker_id=self.worker_id,
                worker_type=self.worker_type,
                error_type=type(exc).__name__,
            )

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._record()

    def __enter__(self):
        self._record()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{self.worker_type}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._record("stopped")
