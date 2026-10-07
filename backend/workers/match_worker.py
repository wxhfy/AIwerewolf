from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid

from backend.application.matches.executor import MatchExecutor
from backend.application.matches.executor import worker_poll_interval
from backend.application.matches.repository import MatchJobRepository
from backend.core.config import validate_production_configuration
from backend.db.database import init_db

logger = logging.getLogger(__name__)


class MatchWorker:
    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.repository = MatchJobRepository()
        self.executor = MatchExecutor(self.repository, worker_id=self.worker_id)
        self.stop_event = threading.Event()

    def stop(self, *_args) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        validate_production_configuration()
        init_db()
        logger.info("Match worker %s started", self.worker_id)
        poll_interval = worker_poll_interval()
        recovery_interval = max(1.0, float(os.getenv("MATCH_LEASE_RECOVERY_SECONDS", "30")))
        next_recovery = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now >= next_recovery:
                expired = self.repository.fail_expired_leases()
                if expired:
                    logger.warning("Processed %s expired match worker leases", expired)
                next_recovery = now + recovery_interval
            job = self.repository.claim_next(self.worker_id)
            if job is None:
                self.stop_event.wait(poll_interval)
                continue
            try:
                self.executor.execute(job)
            except Exception as exc:
                logger.exception("Match %s failed", job.game_id)
                self.repository.fail(job.id, self.worker_id, str(exc))


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = MatchWorker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
