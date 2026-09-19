from __future__ import annotations

import logging
import os
import signal
import threading

from backend.application.analysis.service import PostGameAnalysisService
from backend.db.database import init_db
from backend.db.persist import list_recoverable_track_c_post_game_jobs

logger = logging.getLogger(__name__)


class AnalysisWorker:
    def __init__(self) -> None:
        self.service = PostGameAnalysisService()
        self.stop_event = threading.Event()
        self.poll_seconds = max(0.2, float(os.getenv("ANALYSIS_WORKER_POLL_SECONDS", "2")))
        self.batch_size = max(1, int(os.getenv("ANALYSIS_WORKER_BATCH_SIZE", "5")))
        self.stale_after_seconds = max(30, int(os.getenv("ANALYSIS_JOB_STALE_SECONDS", "900")))

    def stop(self, *_args) -> None:
        self.stop_event.set()

    def run_once(self) -> int:
        jobs = list_recoverable_track_c_post_game_jobs(
            limit=self.batch_size,
            stale_after_seconds=self.stale_after_seconds,
        )
        processed = 0
        for job in jobs:
            game_id = str(job.get("game_id") or "")
            if not game_id:
                continue
            try:
                result = self.service.execute(game_id, stale_after_seconds=self.stale_after_seconds)
                if result is not None:
                    processed += 1
            except Exception:
                logger.exception("Post-game analysis failed for match %s", game_id)
        return processed

    def run_forever(self) -> None:
        init_db()
        logger.info("Analysis worker started")
        while not self.stop_event.is_set():
            processed = self.run_once()
            if processed == 0:
                self.stop_event.wait(self.poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = AnalysisWorker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
