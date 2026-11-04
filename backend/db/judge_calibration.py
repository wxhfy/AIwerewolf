"""Durable, immutable Judge calibration artifacts and promotion eligibility."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.db.models import JSON
from backend.db.models import Base


class JudgeCalibration(Base):
    __tablename__ = "judge_calibrations"

    id = Column(String(32), primary_key=True)
    dataset_id = Column(String, nullable=False)
    dataset_hash = Column(String(64), nullable=False)
    judge_model = Column(String, nullable=False)
    rubric_hash = Column(String, nullable=False)
    scoring_mode = Column(String, nullable=False, default="single_step")
    status = Column(String, nullable=False)
    synthetic = Column(Boolean, nullable=False)
    human_verified = Column(Boolean, nullable=False)
    artifact = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index("ix_judge_calibration_identity", "judge_model", "rubric_hash", "status", "created_at"),)


def _eligible(profile: dict[str, Any]) -> bool:
    """Recheck durable artifacts rather than trusting a caller-provided flag."""
    metrics = profile.get("metrics") or {}
    agreement = metrics.get("calibrated") or {}
    parameters = (profile.get("parameters") or {}).get("overall") or {}
    try:
        return (
            profile.get("status") == "approved"
            and profile.get("auto_promotion_allowed") is True
            and profile.get("agreement_passed") is True
            and profile.get("human_verified") is True
            and profile.get("synthetic") is False
            and "fake" not in str(profile.get("judge_model", "")).lower()
            and metrics["train_n"] >= 30
            and metrics["validation_n"] >= 20
            and metrics["failed_n"] == 0
            and agreement["kappa"] >= 0.60
            and agreement["pearson"] >= 0.70
            and agreement["spearman"] >= 0.70
            and abs(agreement["bias"]) <= 0.10
            and agreement["mae"] <= 0.15
            and parameters["slope"] > 0
        )
    except (KeyError, TypeError, ValueError):
        return False


def _as_artifact(row: JudgeCalibration) -> dict[str, Any]:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {**row.artifact, "created_at": created_at.isoformat()}


def save_judge_calibration(profile: dict[str, Any], session: Session | None = None) -> dict[str, Any]:
    """Idempotently save a content-addressed calibration; never overwrite it."""
    if profile.get("status") == "approved" and not _eligible(profile):
        raise ValueError("ineligible_calibration_cannot_be_approved")
    if session is None:
        from backend.db.database import SessionLocal

        with SessionLocal() as owned:
            result = save_judge_calibration(profile, owned)
            owned.commit()
            return result
    existing = session.get(JudgeCalibration, profile["calibration_id"])
    if existing is not None:
        if existing.artifact != profile:
            raise ValueError("calibration_identity_conflict")
        return _as_artifact(existing)
    row = JudgeCalibration(
        id=profile["calibration_id"],
        dataset_id=profile["dataset_id"],
        dataset_hash=profile["dataset_hash"],
        judge_model=profile["judge_model"],
        rubric_hash=profile["rubric_hash"],
        scoring_mode=profile.get("scoring_mode", "single_step"),
        status=profile["status"],
        synthetic=profile["synthetic"],
        human_verified=profile["human_verified"],
        artifact=profile,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = session.get(JudgeCalibration, profile["calibration_id"])
        if existing is None or existing.artifact != profile:
            raise ValueError("calibration_identity_conflict") from None
        return _as_artifact(existing)
    return _as_artifact(row)


def latest_approved_calibration(
    session: Session | None = None,
    *,
    judge_model: str | None = None,
    rubric_hash: str | None = None,
    scoring_mode: str | None = None,
) -> dict[str, Any] | None:
    """Read a matching real-human calibration; absent/unmigrated stores fail closed."""
    if session is None:
        from backend.db.database import SessionLocal

        try:
            with SessionLocal() as owned:
                return latest_approved_calibration(
                    owned, judge_model=judge_model, rubric_hash=rubric_hash, scoring_mode=scoring_mode
                )
        except OperationalError:
            return None
    query = session.query(JudgeCalibration).filter(
        JudgeCalibration.status == "approved",
        JudgeCalibration.synthetic.is_(False),
        JudgeCalibration.human_verified.is_(True),
    )
    if judge_model is not None:
        query = query.filter(JudgeCalibration.judge_model == judge_model)
    if rubric_hash is not None:
        query = query.filter(JudgeCalibration.rubric_hash == rubric_hash)
    if scoring_mode is not None:
        query = query.filter(JudgeCalibration.scoring_mode == scoring_mode)
    for row in query.order_by(JudgeCalibration.created_at.desc(), JudgeCalibration.id.desc()).limit(100):
        if _eligible(row.artifact):
            return _as_artifact(row)
    return None
