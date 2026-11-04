from __future__ import annotations

from typing import Any

from sqlalchemy import func

from backend.core.errors import ServiceError
from backend.db.database import SessionLocal
from backend.db.models import AgentDecision
from backend.db.models import DecisionEvaluation
from backend.db.models import Game
from backend.db.models import PublishedReview
from backend.db.models import StrategyKnowledgeDoc
from backend.db.models import TrackCPostGameJob


class AnalysisRepository:
    """Persistence facade for post-game analysis and strategy knowledge."""

    def save_decision_scores(
        self,
        game_id: str,
        scores: list[Any],
        *,
        evaluator_version: str = "per-step-v1",
        evaluator_model: str | None = None,
    ) -> int:
        from backend.db.persist import fence_current_analysis_write

        with SessionLocal() as db:
            fence_current_analysis_write(db)
            persisted = 0
            for score in scores:
                decision_id = str(score.decision_id)
                row = (
                    db.query(DecisionEvaluation)
                    .filter(
                        DecisionEvaluation.decision_id == decision_id,
                        DecisionEvaluation.evaluator_version == evaluator_version,
                    )
                    .first()
                )
                if row is None:
                    row = DecisionEvaluation(
                        game_id=game_id,
                        decision_id=decision_id,
                        evaluator_version=evaluator_version,
                    )
                    db.add(row)
                row.player_id = str(score.player_id)
                row.day = int(score.day or 0)
                row.phase = str(score.phase or "")
                row.action_type = str(score.action_type or "")
                row.role = str(score.role or "")
                row.correctness = float(score.correctness or 0.0)
                row.reasoning_quality = float(score.reasoning_quality or 0.0)
                row.timeliness = float(score.timeliness or 0.0)
                row.impact = float(score.impact or 0.0)
                row.overall_score = float(score.overall_score or 0.0)
                row.scoring_tier = str(score.scoring_tier or "deterministic")
                row.evidence = list(score.evidence or [])
                row.alternative = str(score.alternative or "")
                row.is_highlight = row.overall_score >= 0.75
                row.is_mistake = row.overall_score <= 0.30
                row.evaluator_model = evaluator_model
                row.extra_metadata = dict(score.metadata or {})
                persisted += 1
            db.commit()
            return persisted

    def get_summary(self, game_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            game = db.query(Game).filter(Game.id == game_id).first()
            if game is None:
                return None
            job = db.query(TrackCPostGameJob).filter(TrackCPostGameJob.game_id == game_id).first()
            decision_count = (
                db.query(func.count(AgentDecision.id)).filter(AgentDecision.game_id == game_id).scalar() or 0
            )
            score_query = db.query(DecisionEvaluation).filter(DecisionEvaluation.game_id == game_id)
            evaluated_count = (
                score_query.with_entities(func.count(func.distinct(DecisionEvaluation.decision_id))).scalar() or 0
            )
            average_score = score_query.with_entities(func.avg(DecisionEvaluation.overall_score)).scalar()
            highlight_count = score_query.filter(DecisionEvaluation.is_highlight.is_(True)).count()
            mistake_count = score_query.filter(DecisionEvaluation.is_mistake.is_(True)).count()
            review = db.query(PublishedReview).filter(PublishedReview.game_id == game_id).first()
            strategy_rows = (
                db.query(StrategyKnowledgeDoc.status, func.count(StrategyKnowledgeDoc.id))
                .filter(StrategyKnowledgeDoc.source_game_id == game_id)
                .group_by(StrategyKnowledgeDoc.status)
                .all()
            )
            job_view = {
                "status": job.status if job else "not_scheduled",
                "lifecycle_status": "published"
                if job and job.status == "completed"
                else job.status
                if job
                else "not_scheduled",
                "attempts": int(job.attempts or 0) if job else 0,
                "max_attempts": int(job.max_attempts or 0) if job else 0,
                "last_error": str(job.last_error or "") if job else "",
                "started_at": job.started_at.isoformat() if job and job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job and job.finished_at else None,
                "available_at": job.available_at.isoformat() if job and job.available_at else None,
                "dead_letter": bool(job and job.status == "failed"),
                "stage": (job.extra_metadata or {}).get("stage") if job else None,
                "evolution_status": ((job.extra_metadata or {}).get("track_c") or {}).get("status") if job else None,
            }
            return {
                "match_id": game_id,
                "match_status": str(game.status or ""),
                "job": job_view,
                "decision_count": int(decision_count),
                "evaluated_decision_count": int(evaluated_count),
                "evaluation_coverage": round(evaluated_count / decision_count, 4) if decision_count else 0.0,
                "average_score": round(float(average_score), 4) if average_score is not None else None,
                "highlight_count": int(highlight_count),
                "mistake_count": int(mistake_count),
                "review_status": str(review.status) if review else None,
                "report_status": (
                    "published"
                    if review and review.publish_allowed
                    else "failed"
                    if job
                    and (
                        job.status == "failed" or (job.status == "completed" and review and not review.publish_allowed)
                    )
                    else "running"
                    if job and job.status == "running"
                    else "pending"
                ),
                "strategy_counts": {str(status): int(count) for status, count in strategy_rows},
                "evolution": (job.extra_metadata or {}).get("track_c") if job else None,
            }

    def list_decisions(self, game_id: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.query(AgentDecision)
                .filter(AgentDecision.game_id == game_id)
                .order_by(AgentDecision.day, AgentDecision.created_at, AgentDecision.id)
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "player_id": row.player_id,
                    "day": int(row.day or 0),
                    "phase": str(row.phase or ""),
                    "action_type": str((row.parsed_action or {}).get("action_type", "")),
                    "is_valid": bool(row.is_valid),
                    "error_type": row.error_type,
                    "latency_ms": row.latency_ms,
                    "prompt_tokens": row.prompt_tokens,
                    "completion_tokens": row.completion_tokens,
                    "model_name": row.model_name,
                    "provider": row.provider,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    def list_evaluations(self, game_id: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.query(DecisionEvaluation)
                .filter(DecisionEvaluation.game_id == game_id)
                .order_by(DecisionEvaluation.day, DecisionEvaluation.created_at, DecisionEvaluation.id)
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "decision_id": row.decision_id,
                    "player_id": row.player_id,
                    "day": int(row.day or 0),
                    "phase": str(row.phase or ""),
                    "action_type": str(row.action_type or ""),
                    "role": str(row.role or ""),
                    "correctness": float(row.correctness or 0.0),
                    "reasoning_quality": float(row.reasoning_quality or 0.0),
                    "timeliness": float(row.timeliness or 0.0),
                    "impact": float(row.impact or 0.0),
                    "overall_score": float(row.overall_score or 0.0),
                    "scoring_tier": str(row.scoring_tier or "deterministic"),
                    "evidence": list(row.evidence or []),
                    "alternative": str(row.alternative or ""),
                    "is_highlight": bool(row.is_highlight),
                    "is_mistake": bool(row.is_mistake),
                    "evaluator_version": str(row.evaluator_version or ""),
                    "evaluator_model": row.evaluator_model,
                    "metadata": row.extra_metadata or {},
                }
                for row in rows
            ]

    def list_strategies(
        self,
        *,
        status: str | None,
        role: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            query = db.query(StrategyKnowledgeDoc)
            if status:
                query = query.filter(StrategyKnowledgeDoc.status == status)
            if role:
                query = query.filter(StrategyKnowledgeDoc.role == role)
            rows = query.order_by(StrategyKnowledgeDoc.created_at.desc()).offset(offset).limit(limit).all()
            return [self._strategy_to_dict(row) for row in rows]

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        with SessionLocal() as db:
            row = db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.id == strategy_id).first()
            return self._strategy_to_dict(row) if row else None

    def retry(self, game_id: str, *, actor_id: str, idempotency_key: str | None = None) -> dict[str, Any]:
        from backend.db.persist import _ensure_track_c_post_game_job_row

        with SessionLocal() as db:
            query = db.query(Game).filter(Game.id == game_id)
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            game = query.first()
            if game is None:
                raise ServiceError(404, "match_not_found", "Match not found")
            if game.status != "finished":
                raise ServiceError(409, "match_not_finished", "Only finished matches can be analyzed")
            row = _ensure_track_c_post_game_job_row(db, game_id, source="manual_retry")
            metadata = dict(row.extra_metadata or {})
            keys = list(metadata.get("retry_keys") or [])
            key = f"{actor_id}:{idempotency_key}" if idempotency_key else None
            response = {"match_id": game_id, "status": "pending", "requested_by": actor_id}
            if key and key in keys:
                return response
            if row.status == "running":
                raise ServiceError(409, "analysis_running", "Analysis is already running")
            # Repeating a pending retry must not reset the attempt budget or
            # erase backoff. Only a deliberate retry of terminal work resets it.
            if row.status != "pending":
                metadata["retry_generation"] = int(metadata.get("retry_generation") or 0) + 1
                row.status = "pending"
                row.attempts = 0
                row.last_error = ""
                row.locked_at = None
                row.claim_token = None
                row.available_at = None
                row.started_at = None
                row.finished_at = None
            if key:
                keys = [*keys[-99:], key]
            row.extra_metadata = {**metadata, "retry_requested_by": actor_id, "retry_keys": keys, "dead_letter": False}
            db.commit()
            return response

    @staticmethod
    def _strategy_to_dict(row: StrategyKnowledgeDoc) -> dict[str, Any]:
        return {
            "id": row.id,
            "doc_type": row.doc_type,
            "role": row.role,
            "phase": row.phase or "",
            "status": row.status or "candidate",
            "maturity": row.maturity or "raw",
            "situation_pattern": row.situation_pattern or "",
            "recommended_action": row.recommended_action or "",
            "rationale": row.rationale or "",
            "quality_score": float(row.quality_score or 0.0),
            "confidence": float(row.confidence or 0.0),
            "confidence_tier": row.confidence_tier or "L3_strategic",
            "source_game_id": row.source_game_id,
            "source_decision_id": row.source_decision_id,
            "doc_version": row.doc_version or "v1",
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
