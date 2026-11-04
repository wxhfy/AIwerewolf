from __future__ import annotations

import logging
import os
import signal
import threading
from uuid import uuid4

from backend.application.analysis.service import PostGameAnalysisService
from backend.core.config import validate_production_configuration
from backend.core.observability import count
from backend.core.observability import log_event
from backend.core.observability import operation_context
from backend.db.database import init_db
from backend.db.persist import analysis_enabled
from backend.db.persist import dispatch_match_analysis_outbox
from backend.db.persist import list_recoverable_track_c_post_game_jobs
from backend.db.persist import reconcile_finished_match_analysis
from backend.ops.worker_health import WorkerHeartbeatLoop

logger = logging.getLogger(__name__)


class AnalysisWorker:
    def __init__(self) -> None:
        self.service = PostGameAnalysisService()
        self.worker_id = f"analysis-{uuid4().hex[:12]}"
        self.stop_event = threading.Event()
        self.poll_seconds = max(0.2, float(os.getenv("ANALYSIS_WORKER_POLL_SECONDS", "2")))
        self.batch_size = max(1, int(os.getenv("ANALYSIS_WORKER_BATCH_SIZE", "5")))
        self.stale_after_seconds = max(30, int(os.getenv("ANALYSIS_JOB_STALE_SECONDS", "900")))

    def stop(self, *_args) -> None:
        self.stop_event.set()

    def run_once(self) -> int:
        count("analysis.worker.tick")
        dispatch_match_analysis_outbox(limit=self.batch_size * 2)
        reconcile_finished_match_analysis(limit=self.batch_size * 2)
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
                with operation_context(match_id=game_id, request_id=str(job.get("id") or "")):
                    result = self.service.execute(game_id, stale_after_seconds=self.stale_after_seconds)
                if result is not None:
                    processed += 1
                    count("analysis.job.completed")
                    log_event(logger, "analysis.job.completed", match_id=game_id, request_id=job.get("id"))
            except Exception as exc:
                count("analysis.job.failed")
                log_event(
                    logger,
                    "analysis.job.failed",
                    level=logging.ERROR,
                    match_id=game_id,
                    request_id=job.get("id"),
                    error_type=type(exc).__name__,
                )
        return processed

    def run_forever(self) -> None:
        validate_production_configuration()
        init_db()
        with WorkerHeartbeatLoop(self.worker_id, "analysis"):
            if not analysis_enabled():
                log_event(logger, "analysis.worker.disabled", worker_id=self.worker_id)
                while not self.stop_event.is_set():
                    self.stop_event.wait(max(self.poll_seconds, 5))
                return
            log_event(logger, "analysis.worker.started", worker_id=self.worker_id)
            while not self.stop_event.is_set():
                try:
                    processed = self.run_once()
                except Exception as exc:
                    count("analysis.worker.poll_failed")
                    log_event(
                        logger,
                        "analysis.worker.poll_failed",
                        level=logging.ERROR,
                        worker_id=self.worker_id,
                        error_type=type(exc).__name__,
                    )
                    processed = 0
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
