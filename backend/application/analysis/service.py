from __future__ import annotations

import logging
import threading
from typing import Any

from backend.core.observability import log_event
from backend.db import persist
from backend.db.models import PublishedReview
from backend.db.persist import AnalysisClaimLost
from backend.db.persist import analysis_write_scope
from backend.db.persist import build_post_game_state_from_db
from backend.db.persist import checkpoint_track_c_post_game_job
from backend.db.persist import claim_track_c_post_game_job
from backend.db.persist import complete_track_c_post_game_job
from backend.db.persist import fail_track_c_post_game_job
from backend.db.persist import heartbeat_track_c_post_game_job
from backend.db.persist import save_post_game_artifacts
from backend.eval.post_game import run_post_game_scoring

from .reflection import run_agent_reflections

logger = logging.getLogger(__name__)


class AnalysisLeaseLost(AnalysisClaimLost):
    pass


class _AnalysisLease:
    def __init__(self, game_id: str, token: str, stale_after_seconds: int) -> None:
        self.game_id = game_id
        self.token = token
        self.interval = max(0.1, min(30.0, stale_after_seconds / 3))
        self.stopped = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._renew, daemon=True, name="analysis-job-heartbeat")

    def _renew(self) -> None:
        while not self.stopped.wait(self.interval):
            try:
                if not heartbeat_track_c_post_game_job(self.game_id, self.token):
                    self.lost.set()
                    return
            except Exception:
                # A DB outage cannot prove continued ownership. Stop this
                # attempt at its next stage boundary rather than double-write.
                self.lost.set()
                return

    def assert_owned(self) -> None:
        if self.lost.is_set() or not heartbeat_track_c_post_game_job(self.game_id, self.token):
            raise AnalysisLeaseLost("Analysis job lease lost")

    def __enter__(self) -> _AnalysisLease:
        self.thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self.stopped.set()
        self.thread.join(timeout=2)


def coordinate_evolution(game_id: str, *, request_id: str) -> dict[str, Any]:
    """Track C consumes approved reports only, never an unfinished artifact."""
    with persist.SessionLocal() as db:
        connection = db.connection()
        has_reports = connection.dialect.has_table(connection, PublishedReview.__tablename__)
        review = db.query(PublishedReview).filter(PublishedReview.game_id == game_id).first() if has_reports else None
        if review is None or not review.publish_allowed or review.status != "approved":
            return {"status": "pending_review", "promoted_count": 0, "reason": "approved_review_required"}
    from backend.application.evolution.coordinator import TrackCCoordinator

    return TrackCCoordinator().execute(game_id, request_id=request_id)


class PostGameAnalysisService:
    """Execute durable Track B/C stages with attempt fencing and recovery."""

    def execute(self, game_id: str, *, stale_after_seconds: int = 900) -> dict[str, Any] | None:
        job = claim_track_c_post_game_job(game_id, stale_after_seconds=stale_after_seconds)
        if job is None:
            return None
        token = str(job["claim_token"])
        log_event(logger, "analysis.job.claimed", match_id=game_id, request_id=job["id"], attempt=job["attempts"])
        stage = "state_rebuild"
        try:
            with analysis_write_scope(game_id, token), _AnalysisLease(game_id, token, stale_after_seconds) as lease:
                state = build_post_game_state_from_db(game_id)
                if state is None:
                    fail_track_c_post_game_job(
                        game_id,
                        "Cannot rebuild finished game state for post-game analysis",
                        retryable=False,
                        claim_token=token,
                        metadata={"stage": stage},
                    )
                    return None
                lease.assert_owned()
                checkpoint = dict(job.get("metadata") or {})
                if checkpoint.get("track_b_complete"):
                    details = dict(checkpoint.get("track_b_details") or {})
                    reflection_docs = int(checkpoint.get("reflection_docs") or 0)
                else:
                    stage = "track_b_scoring"
                    result = run_post_game_scoring(state, game_id, return_details=True)
                    details = result if isinstance(result, dict) else {"lessons_stored": int(result or 0)}
                    lease.assert_owned()
                    stage = "reflections"
                    reflection_docs = run_agent_reflections(state)
                    lease.assert_owned()
                    stage = "report_publication"
                    save_post_game_artifacts(state, claim_token=token)
                    lease.assert_owned()
                    if not checkpoint_track_c_post_game_job(
                        game_id,
                        token,
                        {"track_b_complete": True, "track_b_details": details, "reflection_docs": int(reflection_docs)},
                    ):
                        raise AnalysisLeaseLost("Analysis job lease lost at checkpoint")
                stage = "track_c_coordinator"
                generation = int(checkpoint.get("retry_generation") or 0)
                request_id = str(job["id"]) if generation == 0 else f"{job['id']}:retry:{generation}"
                evolution = coordinate_evolution(game_id, request_id=request_id)
                if evolution.get("status") in {"failed", "running"}:
                    raise RuntimeError("Track C has not completed this attempt")
                lease.assert_owned()
                return complete_track_c_post_game_job(
                    game_id,
                    claim_token=token,
                    lessons_stored=int(details.get("lessons_stored", 0)),
                    promoted_count=int(details.get("promoted_count", 0)) + int(evolution.get("promoted_count", 0)),
                    metadata={
                        "stage": "completed",
                        "decisions_scored": int(details.get("decisions_scored", 0)),
                        "reflection_docs": int(reflection_docs),
                        "track_c": evolution,
                    },
                )
        except AnalysisClaimLost:
            log_event(
                logger,
                "analysis.lease_lost",
                level=logging.WARNING,
                match_id=game_id,
                request_id=job["id"],
                stage=stage,
            )
            return None
        except Exception as exc:
            # Provider exception text can contain request URLs or credentials;
            # persist only the type and stage, never arbitrary exception text.
            fail_track_c_post_game_job(
                game_id,
                f"{type(exc).__name__}: analysis stage failed",
                retryable=True,
                claim_token=token,
                metadata={"stage": stage, "error_code": "analysis_stage_failed"},
            )
            raise
