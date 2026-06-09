"""Knowledge Abstractor — from per-player reviews to retrievable PostgreSQL strategy docs.

Track C data flow:
  PerStepScorer → PlayerReviewReport → KnowledgeAbstractor → PostgreSQL
       ↓                                                    ↓
  ScoredStep (per action)                    strategy_knowledge_docs table
       ↓                                                    ↓
  PlayerReviewReport (per player)            Next game: StrategyRetrievalQuery
       ↓                                                    ↓
  AbstractedLesson (tagged, role-specific)   RetrievedStrategyLesson → LLM prompt

Each game produces:
- N per-player reviews (one per agent)
- M abstracted lessons (from highlight/mistake/strategy-applied steps)
- Lessons stored as StrategyKnowledgeDoc records for future retrieval
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from backend.eval.per_step_scorer import PlayerReviewReport
from backend.eval.per_step_scorer import ScoredStep

AUTO_PROMOTION_QUALITY_THRESHOLD = float(os.getenv("TRACKC_AUTO_PROMOTION_QUALITY_THRESHOLD", "0.85"))
AUTO_PROMOTION_CLUSTER_THRESHOLD = float(os.getenv("TRACKC_AUTO_PROMOTION_CLUSTER_THRESHOLD", "0.75"))
AUTO_PROMOTION_CLUSTER_TOP_N = int(os.getenv("TRACKC_AUTO_PROMOTION_CLUSTER_TOP_N", "5"))
ACTIVE_DOC_CAP_PER_ROLE_TYPE = int(os.getenv("TRACKC_ACTIVE_DOC_CAP_PER_ROLE_TYPE", "20"))
CANDIDATE_DOC_CAP_PER_ROLE_TYPE = int(os.getenv("TRACKC_CANDIDATE_DOC_CAP_PER_ROLE_TYPE", "200"))
CANDIDATE_DOC_TOTAL_CAP = int(os.getenv("TRACKC_CANDIDATE_DOC_TOTAL_CAP", "5000"))
CANDIDATE_DEPRECATION_THRESHOLD = float(os.getenv("TRACKC_CANDIDATE_DEPRECATION_THRESHOLD", "0.60"))
CANDIDATE_STALE_DAYS = int(os.getenv("TRACKC_CANDIDATE_STALE_DAYS", "45"))
FEEDBACK_PROMOTION_MIN_USAGE = int(os.getenv("TRACKC_FEEDBACK_PROMOTION_MIN_USAGE", "3"))
FEEDBACK_PROMOTION_SUCCESS_RATE = float(os.getenv("TRACKC_FEEDBACK_PROMOTION_SUCCESS_RATE", "0.70"))
FEEDBACK_DEPRECATION_MIN_USAGE = int(os.getenv("TRACKC_FEEDBACK_DEPRECATION_MIN_USAGE", "5"))
FEEDBACK_DEPRECATION_FAILURE_RATE = float(os.getenv("TRACKC_FEEDBACK_DEPRECATION_FAILURE_RATE", "0.70"))


@dataclass
class AbstractedLesson:
    """A single abstracted lesson ready for PostgreSQL storage.

    This is the atomic unit of Track C knowledge.
    Each lesson comes from ONE player's experience in ONE game,
    tagged with role + persona + situation + quality for precise retrieval.
    """

    # Identity
    source_game_id: str
    source_player_id: str
    source_step_id: str

    # Who is this lesson for?
    target_role: str  # "Seer", "Werewolf", "Witch", "global"
    target_persona_scope: str = ""  # "INTJ", "analytical", "" (empty = any persona)

    # When does this apply?
    phase: str = ""  # "DAY_SPEECH", "NIGHT_WITCH_ACTION", "global"
    situation_pattern: str = ""  # Natural language: "多人对跳预言家时"
    trigger_conditions: List[str] = field(default_factory=list)

    # What should the agent do?
    recommended_action: str = ""  # "优先投票已查杀的狼人"
    avoid_action: str = ""  # "不要在没有证据时强踩"
    rationale: str = ""  # Why this works

    # Quality signals
    quality_score: float = 0.0  # 0-1 based on step outcome + repeatability
    confidence: float = 0.0  # based on evidence quality
    source_type: str = ""  # "highlight" | "mistake_lesson" | "strategy_applied"

    # Tags for retrieval
    tags: List[str] = field(default_factory=list)

    # Evidence
    evidence_summary: str = ""
    source_event_ids: List[str] = field(default_factory=list)

    # Experiment tracking
    experiment_id: str = ""

    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_pg_dict(self) -> Dict[str, Any]:
        """Convert to dict matching strategy_knowledge_docs table schema.

        SQLAlchemy JSON columns accept native list/dict values here; keeping
        them native also matches StrategyKnowledgeDocData's dataclass contract.
        """
        return {
            "doc_id": f"{self.source_game_id}:{self.source_step_id}:{self.source_type}",
            "doc_type": "per_step_lesson",
            "role": self.target_role,
            "phase": self.phase,
            "persona_scope": self.target_persona_scope or None,
            "situation_pattern": self.situation_pattern,
            "trigger_conditions": list(self.trigger_conditions),
            "recommended_action": self.recommended_action,
            "avoid_action": self.avoid_action or None,
            "rationale": self.rationale,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "source_report_ids": [self.source_game_id],
            "source_item_ids": [self.source_step_id],
            "source_event_ids": list(self.source_event_ids),
            "counterfactual_ids": [],
            "expected_metric_effects": [],
            "evidence_summary": self.evidence_summary,
            "tags": list(self.tags),
            "status": "candidate",
            "experiment_id": self.experiment_id or None,
            "source_game_id": self.source_game_id,
            "source_decision_id": self.source_step_id,
        }


class KnowledgeAbstractor:
    """Converts per-player reviews into abstracted, retrievable lessons.

    For each player review:
    1. Extract lessons from highlight steps (what went RIGHT)
    2. Extract lessons from mistake steps (what went WRONG → inverted advice)
    3. Extract lessons from strategy-applied steps (did retrieval help?)
    4. Deduplicate similar lessons within the same game
    5. Store as StrategyKnowledgeDoc records in PostgreSQL

    These lessons are then retrievable in future games via
    StrategyRetrievalQuery (role + phase + persona + situation).
    """

    def __init__(self, min_quality: float = 0.50):
        self._min_quality = min_quality

    def abstract_from_review(self, review: PlayerReviewReport) -> List[AbstractedLesson]:
        """Extract abstracted lessons from one player's review.

        Args:
            review: The per-player review report from PerStepScorer.

        Returns:
            List of AbstractedLesson objects ready for PostgreSQL.
        """
        lessons: List[AbstractedLesson] = []

        for step in review.scored_steps:
            # From highlights: what worked well
            if step.is_highlight:
                lesson = self._from_highlight(step, review)
                if lesson and lesson.quality_score >= self._min_quality:
                    lessons.append(lesson)

            # From mistakes: what to avoid (inverted into positive advice)
            if step.is_mistake:
                lesson = self._from_mistake(step, review)
                if lesson and lesson.quality_score >= self._min_quality:
                    lessons.append(lesson)

            # From strategy-applied steps: was retrieval helpful?
            if step.strategy_applied:
                lesson = self._from_strategy_use(step, review)
                if lesson and lesson.quality_score >= self._min_quality:
                    lessons.append(lesson)

            # From general observations: medium-scoring steps still carry lessons
            if not step.is_highlight and not step.is_mistake and not step.strategy_applied:
                lesson = self._from_observation(step, review)
                if lesson and lesson.quality_score >= self._min_quality:
                    lessons.append(lesson)

        # Track experiment isolation (H6): tag every lesson with the experiment_id
        # from the environment so each tier's knowledge stays isolated.
        exp_id = os.getenv("TIER_EXPERIMENT_ID", "")
        if exp_id:
            for lesson in lessons:
                lesson.experiment_id = exp_id

        # Deduplicate similar lessons
        lessons = self._deduplicate(lessons)

        return lessons

    def abstract_from_game(self, reviews: List[PlayerReviewReport]) -> Dict[str, List[AbstractedLesson]]:
        """Extract all lessons from a full game.

        Returns:
            Dict mapping role → list of lessons for that role.
        """
        by_role: Dict[str, List[AbstractedLesson]] = {}
        for review in reviews:
            lessons = self.abstract_from_review(review)
            for lesson in lessons:
                role = lesson.target_role
                if role not in by_role:
                    by_role[role] = []
                by_role[role].append(lesson)
        return by_role

    # ============================================================
    # Lesson extraction from different step types
    # ============================================================

    def _from_highlight(self, step: ScoredStep, review: PlayerReviewReport) -> Optional[AbstractedLesson]:
        """Extract a lesson from a highlight (successful action)."""
        st = (
            getattr(step.step_type, "value", step.step_type)
            if hasattr(step.step_type, "value")
            else str(step.step_type)
        )
        tag_val = st.value if hasattr(st, "value") else str(st)
        return AbstractedLesson(
            source_game_id=review.game_id,
            source_player_id=review.player_id,
            source_step_id=step.step_id,
            target_role=review.role,
            target_persona_scope=review.persona_style or review.persona_mbti,
            phase=step.phase,
            situation_pattern=self._infer_situation(step, review),
            trigger_conditions=self._infer_triggers(step),
            recommended_action=f"面对类似情况时，可参考该{review.role}的做法: {step.action_summary}",
            rationale=f"该决策得分为{step.step_score:.0%}，对阵营产生了正面影响。",
            quality_score=step.step_score,
            confidence=0.85,
            source_type="highlight",
            tags=step.lesson_tags + [review.role, tag_val],
            evidence_summary=step.action_summary,
            source_event_ids=list(step.evidence_event_ids),
        )

    def _from_mistake(self, step: ScoredStep, review: PlayerReviewReport) -> Optional[AbstractedLesson]:
        """Extract a lesson from a mistake (inverted into what TO do)."""
        if not step.mistake_type:
            return None

        # Invert the mistake into positive advice
        avoidance_advice = {
            "fabrication": "发言必须基于真实事件，不要编造不存在的投票或信息。",
            "empty_speech": "发言要有具体怀疑对象和依据，避免空泛的'先观察'。",
            "wrong_vote": "投票前检查公开信息（查验结果、票型），不要盲跟。",
            "missed_skill": "在关键轮次不要犹豫使用技能。",
            "bad_target": "选择行动目标时优先考虑高价值角色。",
        }

        return AbstractedLesson(
            source_game_id=review.game_id,
            source_player_id=review.player_id,
            source_step_id=step.step_id,
            target_role=review.role,
            target_persona_scope=review.persona_style or review.persona_mbti,
            phase=step.phase,
            situation_pattern=self._infer_situation(step, review),
            trigger_conditions=self._infer_triggers(step),
            recommended_action=avoidance_advice.get(step.mistake_type, step.lesson_abstract),
            avoid_action=step.action_summary,
            rationale=f"该决策得分为{step.step_score:.0%}，属于{step.mistake_type}类型失误。避免类似行为可提升表现。",
            quality_score=0.5 + (1.0 - step.step_score) * 0.5,  # Higher quality for clear mistakes
            confidence=0.90,
            source_type="mistake_lesson",
            tags=step.lesson_tags + [review.role, "失误", step.mistake_type],
            evidence_summary=step.action_summary,
            source_event_ids=list(step.evidence_event_ids),
        )

    def _from_strategy_use(self, step: ScoredStep, review: PlayerReviewReport) -> Optional[AbstractedLesson]:
        """Extract a lesson about whether retrieved strategy was helpful."""
        if not step.retrieved_strategies:
            return None

        helpful = step.strategy_impact > 0.5
        return AbstractedLesson(
            source_game_id=review.game_id,
            source_player_id=review.player_id,
            source_step_id=step.step_id,
            target_role=review.role,
            target_persona_scope=review.persona_style or review.persona_mbti,
            phase=step.phase,
            situation_pattern=self._infer_situation(step, review),
            trigger_conditions=self._infer_triggers(step),
            recommended_action=(
                f"检索到的策略{'有效' if helpful else '需要调整'}: "
                f"{step.retrieved_strategies[0].get('recommended', '')[:100] if step.retrieved_strategies else ''}"
            ),
            rationale=(
                f"应用检索策略后结果{'改善' if helpful else '未改善'}。策略影响分: {step.strategy_impact:.0%}。"
            ),
            quality_score=step.strategy_impact,
            confidence=0.75,
            source_type="strategy_applied",
            tags=step.lesson_tags + [review.role, "策略检索", "feedback"],
            evidence_summary=step.action_summary,
            source_event_ids=list(step.evidence_event_ids),
        )

    def _from_observation(self, step: ScoredStep, review: PlayerReviewReport) -> Optional[AbstractedLesson]:
        """Extract a general observation lesson from any scored step."""
        st = (
            getattr(step.step_type, "value", step.step_type)
            if hasattr(step.step_type, "value")
            else str(step.step_type)
        )
        tag_val = st.value if hasattr(st, "value") else str(st)
        return AbstractedLesson(
            source_game_id=review.game_id,
            source_player_id=review.player_id,
            source_step_id=step.step_id,
            target_role=review.role,
            target_persona_scope=review.persona_style or review.persona_mbti,
            phase=step.phase,
            situation_pattern=self._infer_situation(step, review),
            trigger_conditions=self._infer_triggers(step),
            recommended_action=(f"在{step.phase}阶段，{review.role}应保持{step.action_summary[:80]}的决策风格"),
            rationale=f"该决策得分为{step.step_score:.0%}，为中等表现。保持并略作优化。",
            quality_score=max(0.50, step.step_score),
            confidence=0.70,
            source_type="observation",
            tags=step.lesson_tags + [review.role, tag_val],
            evidence_summary=step.action_summary,
            source_event_ids=list(step.evidence_event_ids),
        )

    # ============================================================
    # Helpers
    # ============================================================

    @staticmethod
    def _infer_situation(step: ScoredStep, review: PlayerReviewReport) -> str:
        """Infer the game situation from context."""
        parts = [review.role, step.phase]
        if step.day > 0:
            parts.append(f"D{step.day}")
        st = (
            getattr(step.step_type, "value", step.step_type)
            if hasattr(step.step_type, "value")
            else str(step.step_type)
        )
        if st == "speech":
            parts.append("发言阶段")
        elif st == "vote":
            parts.append("投票阶段")
        else:
            parts.append("夜晚行动")
        return " ".join(parts)

    @staticmethod
    def _infer_triggers(step: ScoredStep) -> List[str]:
        """Infer trigger conditions for this lesson."""
        triggers = [step.phase, f"role={step.role}"]
        for tag in step.lesson_tags:
            triggers.append(tag)
        return triggers

    @staticmethod
    def _deduplicate(lessons: List[AbstractedLesson]) -> List[AbstractedLesson]:
        """Deduplicate lessons with similar content within the same game."""
        seen: Dict[str, AbstractedLesson] = {}
        for lesson in lessons:
            key = f"{lesson.target_role}:{lesson.source_type}:{lesson.recommended_action[:50]}"
            if key not in seen or lesson.quality_score > seen[key].quality_score:
                seen[key] = lesson
        return list(seen.values())


# ============================================================
# PostgreSQL Integration
# ============================================================


def store_lessons_to_db(
    lessons: List[AbstractedLesson],
    conn_str: str = "",
) -> int:
    """Store abstracted lessons to PostgreSQL via upsert with cross-game dedup.

    Routes through _upsert_strategy_knowledge_rows which handles:
    - Cross-game dedup by (role, phase, recommended_action[:100])
    - Quality gates (rejects English-only, empty, raw player records)
    - Promotion: candidate → active when ≥3 source games confirm

    Args:
        lessons: List of AbstractedLesson objects.
        conn_str: PostgreSQL connection string (unused — kept for compat).

    Returns:
        Number of lessons stored (new + merged).
    """
    if not lessons:
        return 0

    import logging

    from backend.db.database import SessionLocal
    from backend.db.persist import StrategyKnowledgeDocData
    from backend.db.persist import _upsert_strategy_knowledge_rows

    logger = logging.getLogger(__name__)

    # Convert to StrategyKnowledgeDocData
    docs: list[StrategyKnowledgeDocData] = []
    for lesson in lessons:
        d = lesson.to_pg_dict()
        # Remove legacy keys not in StrategyKnowledgeDocData.
        d.pop("game_id", None)
        d.pop("id", None)  # Let upsert dedup by content, not UUID
        docs.append(StrategyKnowledgeDocData(**d))

    db = SessionLocal()
    try:
        saved = _upsert_strategy_knowledge_rows(db, docs)
        db.commit()

        active_count = sum(1 for s in saved if s.get("status") == "active")
        candidate_count = sum(1 for s in saved if s.get("status") == "candidate")
        logger.info(
            "Stored %d lessons: %d active, %d candidate (cross-game dedup + promotion applied)",
            len(saved),
            active_count,
            candidate_count,
        )
        return len(saved)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _quality(row: Any) -> float:
    try:
        return float(getattr(row, "quality_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _usage_count(row: Any) -> int:
    try:
        return int(getattr(row, "usage_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _success_count(row: Any) -> int:
    try:
        return int(getattr(row, "success_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _failure_count(row: Any) -> int:
    try:
        return int(getattr(row, "failure_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _group_key(row: Any) -> tuple[str, str]:
    return (str(getattr(row, "role", "") or "global"), str(getattr(row, "doc_type", "") or "unknown"))


def _is_reflection_doc(row: Any) -> bool:
    return str(getattr(row, "doc_type", "") or "").lower().startswith("reflection")


def _updated_rank(row: Any) -> float:
    value = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _candidate_sort_key(row: Any) -> tuple[float, float, int]:
    return (_quality(row), _updated_rank(row), _usage_count(row))


def _is_stale_candidate(row: Any, cutoff: datetime) -> bool:
    value = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    if value is None:
        return False
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value < cutoff and _usage_count(row) == 0 and _quality(row) < AUTO_PROMOTION_CLUSTER_THRESHOLD
    return False


def run_strategy_knowledge_lifecycle(
    *,
    quality_threshold: float = AUTO_PROMOTION_QUALITY_THRESHOLD,
    cluster_threshold: float = AUTO_PROMOTION_CLUSTER_THRESHOLD,
    cluster_top_n: int = AUTO_PROMOTION_CLUSTER_TOP_N,
    active_cap_per_role_type: int = ACTIVE_DOC_CAP_PER_ROLE_TYPE,
    candidate_cap_per_role_type: int = CANDIDATE_DOC_CAP_PER_ROLE_TYPE,
    candidate_total_cap: int = CANDIDATE_DOC_TOTAL_CAP,
    deprecation_threshold: float = CANDIDATE_DEPRECATION_THRESHOLD,
    stale_days: int = CANDIDATE_STALE_DAYS,
    feedback_min_usage: int = FEEDBACK_PROMOTION_MIN_USAGE,
    feedback_success_rate: float = FEEDBACK_PROMOTION_SUCCESS_RATE,
    feedback_deprecation_min_usage: int = FEEDBACK_DEPRECATION_MIN_USAGE,
    feedback_deprecation_failure_rate: float = FEEDBACK_DEPRECATION_FAILURE_RATE,
    dry_run: bool = False,
) -> dict[str, int]:
    """Run the shared Track C knowledge lifecycle.

    This is the single promotion/governance implementation used by both layers:
    the automatic post-game hook and the explicit maintenance script.

    Lifecycle:
    1. feedback/quality/cluster gates promote candidate docs to active
    2. active docs are capped per (role, doc_type)
    3. low-quality, stale, or excess candidates are deprecated
    """
    import logging

    from backend.db.database import SessionLocal
    from backend.db.models import StrategyKnowledgeDoc

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    result = {
        "feedback_promoted": 0,
        "quality_promoted": 0,
        "cluster_promoted": 0,
        "active_demoted": 0,
        "low_quality_deprecated": 0,
        "feedback_deprecated": 0,
        "stale_deprecated": 0,
        "candidate_pruned": 0,
        "active_after": 0,
        "candidate_after": 0,
        "deprecated_after": 0,
    }
    original_status: dict[str, str] = {}

    try:
        rows = (
            db.query(StrategyKnowledgeDoc)
            .filter(StrategyKnowledgeDoc.status.in_(["active", "candidate", "deprecated"]))
            .all()
        )
        original_status = {str(getattr(row, "id", id(row))): str(getattr(row, "status", "") or "") for row in rows}

        # Step 1: usage feedback can promote validated candidates or deprecate harmful ones.
        for row in rows:
            status = str(getattr(row, "status", "") or "")
            usage = _usage_count(row)
            if usage <= 0:
                continue
            success_rate = _success_count(row) / max(usage, 1)
            failure_rate = _failure_count(row) / max(usage, 1)
            if (
                status == "candidate"
                and not _is_reflection_doc(row)
                and usage >= feedback_min_usage
                and success_rate >= feedback_success_rate
                and _quality(row) >= deprecation_threshold
            ):
                row.status = "active"
                result["feedback_promoted"] += 1
            elif (
                status in {"candidate", "active"}
                and usage >= feedback_deprecation_min_usage
                and failure_rate >= feedback_deprecation_failure_rate
                and (_quality(row) < quality_threshold or status == "candidate")
            ):
                row.status = "deprecated"
                result["feedback_deprecated"] += 1

        # Step 2: high-confidence quality promotion.
        for row in rows:
            if (
                str(getattr(row, "status", "") or "") == "candidate"
                and not _is_reflection_doc(row)
                and _quality(row) >= quality_threshold
            ):
                row.status = "active"
                result["quality_promoted"] += 1

        # Step 3: cluster gate promotes the best remaining candidates per bucket.
        candidate_groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for row in rows:
            if (
                str(getattr(row, "status", "") or "") == "candidate"
                and not _is_reflection_doc(row)
                and _quality(row) >= cluster_threshold
            ):
                candidate_groups[_group_key(row)].append(row)
        for group in candidate_groups.values():
            for row in sorted(group, key=_candidate_sort_key, reverse=True)[:cluster_top_n]:
                if str(getattr(row, "status", "") or "") == "candidate":
                    row.status = "active"
                    result["cluster_promoted"] += 1

        # Step 4: keep the active pool small and curated.
        active_groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for row in rows:
            if str(getattr(row, "status", "") or "") == "active":
                active_groups[_group_key(row)].append(row)
        for group in active_groups.values():
            if len(group) <= active_cap_per_role_type:
                continue
            keep = {id(row) for row in sorted(group, key=_candidate_sort_key, reverse=True)[:active_cap_per_role_type]}
            for row in group:
                if id(row) not in keep:
                    row.status = "candidate"
                    result["active_demoted"] += 1

        # Step 5: prevent candidate accumulation.
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
        for row in rows:
            if str(getattr(row, "status", "") or "") != "candidate":
                continue
            if _quality(row) < deprecation_threshold:
                row.status = "deprecated"
                result["low_quality_deprecated"] += 1
            elif _is_stale_candidate(row, stale_cutoff):
                row.status = "deprecated"
                result["stale_deprecated"] += 1

        candidate_groups = defaultdict(list)
        for row in rows:
            if str(getattr(row, "status", "") or "") == "candidate":
                candidate_groups[_group_key(row)].append(row)
        for group in candidate_groups.values():
            if len(group) <= candidate_cap_per_role_type:
                continue
            keep = {
                id(row) for row in sorted(group, key=_candidate_sort_key, reverse=True)[:candidate_cap_per_role_type]
            }
            for row in group:
                if id(row) not in keep and str(getattr(row, "status", "") or "") == "candidate":
                    row.status = "deprecated"
                    result["candidate_pruned"] += 1

        candidates = [row for row in rows if str(getattr(row, "status", "") or "") == "candidate"]
        if len(candidates) > candidate_total_cap:
            keep = {id(row) for row in sorted(candidates, key=_candidate_sort_key, reverse=True)[:candidate_total_cap]}
            for row in candidates:
                if id(row) not in keep and str(getattr(row, "status", "") or "") == "candidate":
                    row.status = "deprecated"
                    result["candidate_pruned"] += 1

        result["active_after"] = sum(1 for row in rows if str(getattr(row, "status", "") or "") == "active")
        result["candidate_after"] = sum(1 for row in rows if str(getattr(row, "status", "") or "") == "candidate")
        result["deprecated_after"] = sum(1 for row in rows if str(getattr(row, "status", "") or "") == "deprecated")

        if dry_run:
            db.rollback()
            for row in rows:
                key = str(getattr(row, "id", id(row)))
                if key in original_status:
                    row.status = original_status[key]
        else:
            db.commit()

        logger.info("Track C knowledge lifecycle: %s", result)
        return result
    except Exception:
        db.rollback()
        for row in locals().get("rows", []):
            key = str(getattr(row, "id", id(row)))
            if key in original_status:
                row.status = original_status[key]
        logger.warning("Track C knowledge lifecycle failed", exc_info=True)
        return result
    finally:
        db.close()


def promote_after_store() -> int:
    """Run automatic post-game candidate promotion and pool governance.

    Called from post_game.py after each game's lessons are stored.
    Returns total number of candidates promoted to active.
    """
    result = run_strategy_knowledge_lifecycle()
    return result["feedback_promoted"] + result["quality_promoted"] + result["cluster_promoted"]
