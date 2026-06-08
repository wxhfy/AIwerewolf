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
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from backend.eval.per_step_scorer import PlayerReviewReport
from backend.eval.per_step_scorer import ScoredStep


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


def promote_after_store() -> int:
    """Promote candidates to active after new lessons are stored.

    Runs the standard 3-step promotion pipeline:
    1. quality  — promote candidates with quality_score ≥ 0.85
    2. cluster  — promote top-5 per (role, doc_type) cluster, quality ≥ 0.75
    3. prune    — cap active docs per (role, doc_type) at 30

    Called from post_game.py after each game's lessons are stored.
    Returns total number of candidates promoted.
    """
    import logging
    from collections import defaultdict

    from sqlalchemy import or_

    from backend.db.database import SessionLocal
    from backend.db.persist import StrategyKnowledgeDoc

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    promoted_total = 0

    try:
        # ── Step 1: quality promo (q ≥ 0.90) ──
        quality_threshold = 0.85
        rows = (
            db.query(StrategyKnowledgeDoc)
            .filter(
                StrategyKnowledgeDoc.status == "candidate",
                StrategyKnowledgeDoc.quality_score >= quality_threshold,
                or_(
                    StrategyKnowledgeDoc.doc_type.is_(None),
                    ~StrategyKnowledgeDoc.doc_type.ilike("reflection%"),
                ),
            )
            .all()
        )
        for row in rows:
            row.status = "active"
            promoted_total += 1

        # ── Step 2: cluster promo (top-5 per role/doc_type, q ≥ 0.75) ──
        cluster_threshold = 0.75
        top_n = 5
        rows = (
            db.query(StrategyKnowledgeDoc)
            .filter(
                StrategyKnowledgeDoc.status == "candidate",
                StrategyKnowledgeDoc.quality_score >= cluster_threshold,
                or_(
                    StrategyKnowledgeDoc.doc_type.is_(None),
                    ~StrategyKnowledgeDoc.doc_type.ilike("reflection%"),
                ),
            )
            .order_by(StrategyKnowledgeDoc.quality_score.desc())
            .all()
        )
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for row in rows:
            key = (row.role, row.doc_type or "unknown")
            groups[key].append(row)
        for key, group in groups.items():
            for row in sorted(group, key=lambda r: r.quality_score, reverse=True)[:top_n]:
                if row.status == "candidate":
                    row.status = "active"
                    promoted_total += 1

        # ── Step 3: prune (cap active per role/doc_type at 20) ──
        cap = 20
        active_rows = (
            db.query(StrategyKnowledgeDoc)
            .filter(StrategyKnowledgeDoc.status == "active")
            .order_by(StrategyKnowledgeDoc.quality_score.desc())
            .all()
        )
        active_groups: dict[tuple[str, str], list] = defaultdict(list)
        for row in active_rows:
            key = (row.role, row.doc_type or "unknown")
            active_groups[key].append(row)
        for key, group in active_groups.items():
            if len(group) > cap:
                # Demote lowest-quality excess to candidate
                excess = sorted(group, key=lambda r: r.quality_score)[: len(group) - cap]
                for row in excess:
                    row.status = "candidate"

        db.commit()

        if promoted_total > 0:
            logger.info("promote_after_store: %d candidates → active", promoted_total)
        return promoted_total
    except Exception:
        db.rollback()
        logger.warning("promote_after_store failed", exc_info=True)
        return 0
    finally:
        db.close()
