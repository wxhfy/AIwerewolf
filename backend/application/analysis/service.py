from __future__ import annotations

import logging
from typing import Any

from backend.db.persist import build_post_game_state_from_db
from backend.db.persist import claim_track_c_post_game_job
from backend.db.persist import complete_track_c_post_game_job
from backend.db.persist import fail_track_c_post_game_job
from backend.eval.post_game import run_post_game_scoring

logger = logging.getLogger(__name__)


class PostGameAnalysisService:
    """Execute one durable Track B/C job outside the API and Match Worker."""

    def execute(self, game_id: str, *, stale_after_seconds: int = 900) -> dict[str, Any] | None:
        job = claim_track_c_post_game_job(game_id, stale_after_seconds=stale_after_seconds)
        if job is None:
            return None
        state = build_post_game_state_from_db(game_id)
        if state is None:
            fail_track_c_post_game_job(
                game_id,
                "Cannot rebuild finished game state for post-game analysis",
                retryable=False,
                metadata={"stage": "state_rebuild"},
            )
            return None
        try:
            result = run_post_game_scoring(state, game_id, return_details=True)
        except Exception as exc:
            fail_track_c_post_game_job(
                game_id,
                str(exc),
                retryable=True,
                metadata={"stage": "track_b_track_c"},
            )
            raise
        details = result if isinstance(result, dict) else {"lessons_stored": int(result or 0)}
        return complete_track_c_post_game_job(
            game_id,
            lessons_stored=int(details.get("lessons_stored", 0)),
            promoted_count=int(details.get("promoted_count", 0)),
            metadata={
                "stage": "track_b_track_c",
                "decisions_scored": int(details.get("decisions_scored", 0)),
            },
        )
