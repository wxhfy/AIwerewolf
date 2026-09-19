from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import uuid

from backend.application.matches.executor import MatchExecutor
from backend.application.matches.executor import worker_poll_interval
from backend.application.matches.repository import MatchJobRepository
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
        init_db()
        expired = self.repository.fail_expired_leases()
        if expired:
            logger.warning("Marked %s expired match worker leases as failed", expired)
        logger.info("Match worker %s started", self.worker_id)
        poll_interval = worker_poll_interval()
        while not self.stop_event.is_set():
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
