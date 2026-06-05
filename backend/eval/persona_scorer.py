"""Persona Consistency Scoring — evaluates MBTI/personality-behavior alignment.

Reference:
- VCU (2025): Personality diversity sampling improves game unpredictability
- WOLF (NeurIPS 2025): 5-category deception taxonomy
- Rulers (2026): Evidence-grounded LLM judging

Hybrid scoring: 35% rules (checkable) + 65% LLM with mechanical evidence validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from backend.eval.hybrid_scorer import DimensionScore
from backend.eval.hybrid_scorer import HybridScorer
from backend.eval.hybrid_scorer import ScoringCriterion


@dataclass
class PersonaScoreResult:
    """Complete persona scoring result for one player in one game."""

    player_id: str
    persona_mbti: str
    persona_style: str
    role: str

    # Sub-scores
    persona_consistency: DimensionScore
    deception_skill: Optional[DimensionScore] = None  # For wolves only
    detection_skill: Optional[DimensionScore] = None  # For good camp only

    # Combined
    overall_persona_score: float = 0.0

    @property
    def summary(self) -> Dict[str, Any]:
        return {
            "player_id": self.player_id,
            "persona_mbti": self.persona_mbti,
            "persona_style": self.persona_style,
            "role": self.role,
            "consistency": self.persona_consistency.raw_score,
            "deception": self.deception_skill.raw_score if self.deception_skill else None,
            "detection": self.detection_skill.raw_score if self.detection_skill else None,
            "overall": self.overall_persona_score,
            "confidence": self.persona_consistency.confidence,
        }


# ============================================================
# Persona Consistency Rubric (L3 §5.1)
# ============================================================

PERSONA_CONSISTENCY_RUBRIC: List[ScoringCriterion] = [
    # --- Rule-checkable criteria (35%) ---
    ScoringCriterion(
        id="PC1",
        desc="发言长度符合声称习惯 (speech_length_habit)",
        criterion_type="rule",
        weight=0.15,
        rule_check=lambda ctx: _check_speech_length(ctx),
        reference="VCU (2025) personality diversity",
    ),
    ScoringCriterion(
        id="PC2",
        desc="社交行为符合声称习惯 (social_habit)",
        criterion_type="rule",
        weight=0.20,
        rule_check=lambda ctx: _check_social_habit(ctx),
        reference="VCU (2025) personality diversity",
    ),
    # --- LLM semantic criteria (65%) ---
    ScoringCriterion(
        id="PC3",
        desc="推理方式一致性 (reasoning_style)",
        criterion_type="llm",
        weight=0.30,
        evidence_required=True,
        llm_prompt="""判断该发言的推理方式：
- logical_chain: 有清晰的"因为...所以..."逻辑链
- gut_feeling: 凭直觉/感觉判断，缺少严密的逻辑推导
- comparative: 通过对比不同玩家的行为来做判断

发言声称的推理方式: {claimed_style}
实际表现出的推理方式: ？

和声称的是否一致？输出 JSON: {"passed": true/false, "evidence_text": "原文片段", "reasoning": "判断理由"}""",
        reference="Beyond Survival (2025) RI/SJ dimensions",
    ),
    ScoringCriterion(
        id="PC4",
        desc="不确定性反应 (uncertainty_style)",
        criterion_type="llm",
        weight=0.20,
        evidence_required=True,
        llm_prompt="""判断发言者在面对不确定信息时的反应：
- admit_ignorance: 承认自己不确定，表示需要更多信息
- overcompensate: 过度补偿，即使不确定也假装很肯定
- stay_quiet: 保持沉默或含糊其辞

发言声称的风格: {claimed_style}
实际表现: ？

输出 JSON: {"passed": true/false, "evidence_text": "原文片段", "reasoning": "判断理由"}""",
        reference="Beyond Survival (2025) CT dimension",
    ),
    ScoringCriterion(
        id="PC5",
        desc="压力反应一致性 (pressure_style)",
        criterion_type="llm",
        weight=0.15,
        evidence_required=True,
        llm_prompt="""该发言者是否在被质疑/被点名的压力下？
如果有，判断其反应方式：
- defensive: 自辩为主，解释自己的行为
- counter_attack: 反点质疑者
- deflect: 转移话题，回避质疑
- calm: 冷静回应，不卑不亢

声称的风格: {claimed_style}
实际表现: ？

输出 JSON: {"passed": true/false, "evidence_text": "原文片段", "reasoning": "判断理由"}""",
        reference="WOLF (NeurIPS 2025) deception dynamics",
    ),
]


# ============================================================
# Deception Skill Rubric (Wolves only, L3 §5.2)
# ============================================================

DECEPTION_RUBRIC: List[ScoringCriterion] = [
    ScoringCriterion(
        id="DS1",
        desc="操控成功 — 发言是否导致好人被放逐",
        criterion_type="rule",
        weight=0.40,
        rule_check=lambda ctx: _check_manipulation_success(ctx),
        reference="WOLF (NeurIPS 2025) manipulation success rate",
    ),
    ScoringCriterion(
        id="DS2",
        desc="怀疑度管理 — 公共怀疑度是否被你压低",
        criterion_type="rule",
        weight=0.30,
        rule_check=lambda ctx: _check_suspicion_management(ctx),
        reference="WOLF (NeurIPS 2025) suspicion dynamics",
    ),
    ScoringCriterion(
        id="DS3",
        desc="身份保护 — 是否避免了暴露狼队友",
        criterion_type="rule",
        weight=0.30,
        rule_check=lambda ctx: _check_identity_protection(ctx),
        reference="WOLF (NeurIPS 2025) coordination detection",
    ),
]


# ============================================================
# Detection Skill Rubric (Good camp only, L3 §5.2)
# ============================================================

DETECTION_RUBRIC: List[ScoringCriterion] = [
    ScoringCriterion(
        id="DT1",
        desc="狼人识别 — 是否正确识别了狼人发言中的欺骗",
        criterion_type="rule",
        weight=0.40,
        rule_check=lambda ctx: _check_wolf_identification(ctx),
        reference="WOLF (NeurIPS 2025) detection precision (71-73%)",
    ),
    ScoringCriterion(
        id="DT2",
        desc="投票命中 — 关键轮次是否投了狼",
        criterion_type="rule",
        weight=0.30,
        rule_check=lambda ctx: _check_vote_on_wolves(ctx),
        reference="Beyond Survival (2025) VA dimension",
    ),
    ScoringCriterion(
        id="DT3",
        desc="抗欺骗能力 — 是否被狼人的伪装发言误导",
        criterion_type="rule",
        weight=0.30,
        rule_check=lambda ctx: _check_deception_resistance(ctx),
        reference="WOLF (NeurIPS 2025) detection recall (48-61%)",
    ),
]


# ============================================================
# Rule Check Functions
# ============================================================


def _check_speech_length(ctx: Dict[str, Any]) -> bool:
    """PC1: Check if speech length matches claimed habit."""
    habit = ctx.get("speech_length_habit", "")
    speech_len = len(ctx.get("speech_text", ""))
    thresholds = {
        "short_and_punchy": (10, 150),
        "detailed": (200, 800),
        "storyteller": (300, 2000),
    }
    lo, hi = thresholds.get(habit, (0, 9999))
    return lo <= speech_len <= hi


def _check_social_habit(ctx: Dict[str, Any]) -> bool:
    """PC2: Check if social behavior matches claimed habit."""
    habit = ctx.get("social_habit", "")
    speech_text = ctx.get("speech_text", "")
    suspected = ctx.get("suspected_players", [])
    defended = ctx.get("defended_players", [])

    if habit == "leader":
        return len(suspected) >= 2 or len(defended) >= 1
    elif habit == "follower":
        return _references_previous_speaker(ctx)
    elif habit == "lone_wolf":
        return not _references_previous_speaker(ctx)
    elif habit == "mediator":
        return len(defended) >= 1 and len(suspected) >= 1
    return True  # Unknown style, pass


def _references_previous_speaker(ctx: Dict[str, Any]) -> bool:
    """Check if speech references a previous speaker."""
    prev_speakers = ctx.get("previous_speaker_names", [])
    speech = ctx.get("speech_text", "")
    for name in prev_speakers:
        if name in speech:
            return True
    return False


def _check_manipulation_success(ctx: Dict[str, Any]) -> bool:
    """DS1: Did the wolf's speech lead to a good player being exiled?"""
    votes_after = ctx.get("votes_after_speech", [])
    your_push_target = ctx.get("push_target", "")
    if not your_push_target:
        return False
    exile = ctx.get("exile_result", {})
    return exile.get("target") == your_push_target and not exile.get("is_wolf", True)


def _check_suspicion_management(ctx: Dict[str, Any]) -> bool:
    """DS2: Did public suspicion toward the wolf stay low?"""
    player_suspicion = ctx.get("player_suspicion", 0.5)
    avg_suspicion = ctx.get("average_suspicion", 0.5)
    return player_suspicion < avg_suspicion


def _check_identity_protection(ctx: Dict[str, Any]) -> bool:
    """DS3: Did the wolf avoid exposing teammates?"""
    wolf_teammates = ctx.get("wolf_teammates", [])
    your_suspected = ctx.get("suspected_players", [])
    # Wolf should not actively suspect teammates
    for tm in wolf_teammates:
        if tm in your_suspected:
            return False
    return True


def _check_wolf_identification(ctx: Dict[str, Any]) -> bool:
    """DT1: Did the player correctly identify wolf deception?"""
    your_suspected = ctx.get("suspected_players", [])
    actual_wolves = ctx.get("actual_wolves", [])
    return any(w in your_suspected for w in actual_wolves)


def _check_vote_on_wolves(ctx: Dict[str, Any]) -> bool:
    """DT2: Did the player vote for a wolf in key rounds?"""
    vote_target = ctx.get("vote_target", "")
    actual_wolves = ctx.get("actual_wolves", [])
    return vote_target in actual_wolves


def _check_deception_resistance(ctx: Dict[str, Any]) -> bool:
    """DT3: Was the player NOT misled by wolf deception?"""
    wolf_push_target = ctx.get("wolf_push_target", "")
    your_vote = ctx.get("vote_target", "")
    # If you voted the same as wolves pushed, you were misled
    if wolf_push_target and your_vote == wolf_push_target:
        return False
    return True


# ============================================================
# Persona Scorer
# ============================================================


class PersonaScorer:
    """Scores persona consistency + deception/detection skill.

    Usage:
        scorer = PersonaScorer()
        result = scorer.score(speech_acts, context)
    """

    def __init__(self, llm_judge: Optional[Callable] = None):
        self._llm_judge = llm_judge
        self._consistency_scorer = HybridScorer(list(PERSONA_CONSISTENCY_RUBRIC))
        self._deception_scorer = HybridScorer(list(DECEPTION_RUBRIC))
        self._detection_scorer = HybridScorer(list(DETECTION_RUBRIC))

    def score_persona_consistency(
        self,
        speech_acts: List[Dict[str, Any]],
        persona_info: Dict[str, Any],
    ) -> DimensionScore:
        """Score persona consistency across all speeches in a game.

        Args:
            speech_acts: List of parsed speech acts.
            persona_info: Dict with persona traits (speech_length_habit, social_habit,
                          reasoning_style, uncertainty_style, pressure_style).

        Returns:
            Aggregated DimensionScore across all speeches.
        """
        all_scores = []
        for act in speech_acts:
            ctx = {
                "speech_text": act.get("text", ""),
                "speech_length_habit": persona_info.get("speech_length_habit", ""),
                "social_habit": persona_info.get("social_habit", ""),
                "claimed_style": persona_info.get("reasoning_style", ""),
                "suspected_players": act.get("suspected_players", []),
                "defended_players": act.get("defended_players", []),
                "previous_speaker_names": act.get("previous_speaker_names", []),
            }
            result = self._consistency_scorer.score(ctx, llm_judge=self._llm_judge)
            all_scores.append(result.raw_score)

        avg = sum(all_scores) / max(1, len(all_scores))
        return DimensionScore(
            dimension="persona_consistency",
            raw_score=round(avg, 4),
        )

    def score_deception(
        self,
        speech_acts: List[Dict[str, Any]],
        game_context: Dict[str, Any],
    ) -> DimensionScore:
        """Score deception skill for wolf players."""
        all_scores = []
        for act in speech_acts:
            ctx = {
                **game_context,
                "speech_text": act.get("text", ""),
                "suspected_players": act.get("suspected_players", []),
                "push_target": act.get("push_target", ""),
            }
            result = self._deception_scorer.score(ctx)
            all_scores.append(result.raw_score)

        avg = sum(all_scores) / max(1, len(all_scores))
        return DimensionScore(dimension="deception_skill", raw_score=round(avg, 4))

    def score_detection(
        self,
        speech_acts: List[Dict[str, Any]],
        game_context: Dict[str, Any],
    ) -> DimensionScore:
        """Score detection skill for good camp players."""
        all_scores = []
        for act in speech_acts:
            ctx = {
                **game_context,
                "speech_text": act.get("text", ""),
                "suspected_players": act.get("suspected_players", []),
                "vote_target": act.get("vote_target", ""),
            }
            result = self._detection_scorer.score(ctx)
            all_scores.append(result.raw_score)

        avg = sum(all_scores) / max(1, len(all_scores))
        return DimensionScore(dimension="detection_skill", raw_score=round(avg, 4))

    def score_full(
        self,
        player_id: str,
        role: str,
        alignment: str,
        persona_info: Dict[str, Any],
        speech_acts: List[Dict[str, Any]],
        game_context: Dict[str, Any],
    ) -> PersonaScoreResult:
        """Complete persona scoring for one player."""
        consistency = self.score_persona_consistency(speech_acts, persona_info)

        deception = None
        detection = None
        if alignment == "wolf":
            deception = self.score_deception(speech_acts, game_context)
        else:
            detection = self.score_detection(speech_acts, game_context)

        overall = consistency.raw_score
        if deception:
            overall = 0.5 * consistency.raw_score + 0.5 * deception.raw_score
        elif detection:
            overall = 0.5 * consistency.raw_score + 0.5 * detection.raw_score

        return PersonaScoreResult(
            player_id=player_id,
            persona_mbti=persona_info.get("mbti", ""),
            persona_style=persona_info.get("style_label", ""),
            role=role,
            persona_consistency=consistency,
            deception_skill=deception,
            detection_skill=detection,
            overall_persona_score=round(overall, 4),
        )
