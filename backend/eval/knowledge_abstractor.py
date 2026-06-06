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

        All list/dict fields are serialized to JSON strings so psycopg2
        inserts them correctly into jsonb columns.
        """
        import json as _json

        return {
            "doc_type": "per_step_lesson",
            "role": self.target_role,
            "phase": self.phase,
            "persona_scope": self.target_persona_scope or None,
            "situation_pattern": self.situation_pattern,
            "trigger_conditions": _json.dumps(self.trigger_conditions, ensure_ascii=False),
            "recommended_action": self.recommended_action,
            "avoid_action": self.avoid_action or None,
            "rationale": self.rationale,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "source_report_ids": _json.dumps([self.source_game_id], ensure_ascii=False),
            "source_item_ids": _json.dumps([self.source_step_id], ensure_ascii=False),
            "source_event_ids": _json.dumps(self.source_event_ids, ensure_ascii=False),
            "evidence_summary": self.evidence_summary,
            "tags": _json.dumps(self.tags, ensure_ascii=False),
            "status": "candidate",
            "experiment_id": self.experiment_id or None,
            "source_game_id": self.source_game_id,
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
    """Store abstracted lessons to PostgreSQL strategy_knowledge_docs.

    Args:
        lessons: List of AbstractedLesson objects.
        conn_str: PostgreSQL connection string.

    Returns:
        Number of lessons stored.
    """
    if not lessons:
        return 0

    import logging
    import os as _os
    from uuid import uuid4

    import psycopg2

    from backend.db.database import DEFAULT_DB_URL

    logger = logging.getLogger(__name__)
    auto_promote = _os.getenv("AUTO_PROMOTE_LESSONS", "").lower() == "true"

    conn = psycopg2.connect(conn_str or DEFAULT_DB_URL)
    c = conn.cursor()

    stored = 0
    errors = 0
    role_counts: dict[str, int] = {}
    for lesson in lessons:
        doc = lesson.to_pg_dict()
        # Auto-promote to active if all conditions met
        if auto_promote and lesson.confidence >= 0.90 and not lesson.source_type.startswith("reflection"):
            doc["status"] = "active"
        # Pop extra keys not present in the INSERT column list
        doc.pop("game_id", None)
        # experiment_id is intentionally kept — it goes into the INSERT below (H6 tier isolation)
        # Generate a primary key (raw psycopg2 bypasses SQLAlchemy default)
        doc["id"] = str(uuid4())
        try:
            # Use savepoint so a single failed INSERT doesn't roll back
            # previously successful rows in this transaction.
            sp_id = f"sp_{stored}"
            c.execute(f"SAVEPOINT {sp_id}")
            c.execute(
                """
                INSERT INTO strategy_knowledge_docs
                    (id, doc_type, role, phase, persona_scope, situation_pattern,
                     trigger_conditions, recommended_action, avoid_action, rationale,
                     quality_score, confidence, source_report_ids, source_item_ids,
                     source_event_ids, evidence_summary, tags, status, experiment_id,
                     source_game_id)
                VALUES (%(id)s, %(doc_type)s, %(role)s, %(phase)s, %(persona_scope)s,
                        %(situation_pattern)s, %(trigger_conditions)s,
                        %(recommended_action)s, %(avoid_action)s, %(rationale)s,
                        %(quality_score)s, %(confidence)s, %(source_report_ids)s,
                        %(source_item_ids)s, %(source_event_ids)s,
                        %(evidence_summary)s, %(tags)s, %(status)s, %(experiment_id)s,
                        %(source_game_id)s)
            """,
                doc,
            )
            stored += 1
            role_counts[lesson.target_role] = role_counts.get(lesson.target_role, 0) + 1
        except Exception as e:
            c.execute(f"ROLLBACK TO SAVEPOINT {sp_id}")
            errors += 1
            if errors <= 3:
                logger.warning(
                    "Failed to store lesson (role=%s, type=%s): %s",
                    lesson.target_role,
                    lesson.source_type,
                    str(e)[:200],
                )

    conn.commit()
    conn.close()

    logger.info(
        "Stored %d candidate lessons (status=candidate). Set AUTO_PROMOTE_LESSONS=true to auto-promote to active.",
        stored,
    )
    if role_counts:
        logger.info("Lessons by role: %s", dict(role_counts))

    return stored
