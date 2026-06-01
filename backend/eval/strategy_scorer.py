"""Strategy Impact Scoring — evaluates strategy retrieval → action → outcome.

Reference:
- LSPO (ICML 2025): Strategy-feedback loop with CFR + DPO
- MaKTO (2025): Preference-based feedback outperforms outcome-only by +10.9%

Scoring dimensions:
  SI1: Retrieval Relevance — was the retrieved strategy relevant to the situation?
  SI2: Strategy Adherence — did the agent follow the recommended action?
  SI3: Outcome Improvement — did following the strategy improve local results?
  RQ1-3: Retrieval Quality — hit rate, knowledge utilization, recency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.eval.hybrid_scorer import HybridScorer, ScoringCriterion, DimensionScore


# ============================================================
# Strategy Impact Rubric (L4 §6.1)
# ============================================================

STRATEGY_IMPACT_RUBRIC: List[ScoringCriterion] = [
    ScoringCriterion(
        id="SI1", desc="检索相关性 — 检索到的策略和当前局面匹配度",
        criterion_type="rule", weight=0.25,
        rule_check=lambda ctx: _check_retrieval_relevance(ctx),
        reference="LSPO (ICML 2025) strategy space mapping",
    ),
    ScoringCriterion(
        id="SI2", desc="策略遵循度 — Agent 行动是否和检索到的 recommended_action 一致",
        criterion_type="rule", weight=0.35,
        rule_check=lambda ctx: _check_strategy_adherence(ctx),
        reference="MaKTO (2025) preference-based feedback",
    ),
    ScoringCriterion(
        id="SI3", desc="结果改善 — 按策略行动后局部结果是否改善",
        criterion_type="counterfactual", weight=0.40,
        cf_check=lambda ctx: _check_outcome_improvement(ctx),
        reference="LSPO (ICML 2025) strategy-feedback loop",
    ),
]

# ============================================================
# Retrieval Quality Rubric (L4 §6.2)
# ============================================================

RETRIEVAL_QUALITY_RUBRIC: List[ScoringCriterion] = [
    ScoringCriterion(
        id="RQ1", desc="检索命中率 — 返回了相关策略的比例",
        criterion_type="rule", weight=0.40,
        rule_check=lambda ctx: _check_retrieval_hit_rate(ctx),
        reference="LSPO (ICML 2025) retrieval quality",
    ),
    ScoringCriterion(
        id="RQ2", desc="知识利用质量 — 被正确应用的策略 doc 的成功率",
        criterion_type="rule", weight=0.35,
        rule_check=lambda ctx: _check_knowledge_utilization(ctx),
        reference="MaKTO (2025) knowledge feedback",
    ),
    ScoringCriterion(
        id="RQ3", desc="知识时效性 — 越新的知识权重越高 (exp decay)",
        criterion_type="rule", weight=0.25,
        rule_check=lambda ctx: _check_knowledge_recency(ctx),
        reference="Morandi (2026) recency calibration",
    ),
]


# ============================================================
# Rule Check Functions
# ============================================================

def _check_retrieval_relevance(ctx: Dict[str, Any]) -> bool:
    """SI1: Check if retrieved strategies are relevant to the situation."""
    retrieval_scores = ctx.get("retrieval_scores", [])
    if not retrieval_scores:
        return False
    avg_score = sum(retrieval_scores) / len(retrieval_scores)
    return avg_score >= 0.5  # TF-IDF / BGE cosine threshold


def _check_strategy_adherence(ctx: Dict[str, Any]) -> bool:
    """SI2: Check if agent's action matches the retrieved strategy's recommendation.

    Simple rule: the agent's action type or target matches what the
    retrieved strategy recommended. Exact matching on action type.
    """
    retrieved = ctx.get("retrieved_strategies", [])
    actual_action = ctx.get("actual_action", {})
    if not retrieved or not actual_action:
        return False

    action_type = actual_action.get("type", "")
    target = actual_action.get("target", "")

    for strat in retrieved:
        recommended = strat.get("recommended", "").lower()
        # Simple keyword matching on recommended action
        action_keywords = {
            "vote": ["vote", "投票", "投", "归票"],
            "attack": ["attack", "kill", "刀", "击杀"],
            "divine": ["divine", "check", "验", "查验"],
            "guard": ["guard", "protect", "守", "守护"],
            "witch_save": ["save", "救", "解药"],
            "witch_poison": ["poison", "毒", "毒药"],
            "speech": ["speech", "发言", "说", "聊"],
        }
        expected_keywords = action_keywords.get(action_type, [])
        if any(kw in recommended for kw in expected_keywords):
            return True
        # Also check if recommended target matches actual target
        if target and target in recommended:
            return True

    return False


def _check_outcome_improvement(ctx: Dict[str, Any]) -> float:
    """SI3: Counterfactual improvement score.

    Compare actual outcome vs counterfactual (what would have happened
    without following the strategy).

    Returns a float 0-1 where >0.5 means improvement.
    """
    actual = ctx.get("actual_outcome", {})
    counterfactual = ctx.get("counterfactual_outcome", {})

    if not actual or not counterfactual:
        return 0.5  # Neutral — insufficient data

    # Simple comparison: did the actual outcome have better camp results?
    actual_camp_gain = actual.get("camp_gain", 0)
    cf_camp_gain = counterfactual.get("camp_gain", 0)

    delta = actual_camp_gain - cf_camp_gain
    # Normalize: delta>0 means improvement, map to 0-1
    return max(0.0, min(1.0, 0.5 + delta))


def _check_retrieval_hit_rate(ctx: Dict[str, Any]) -> bool:
    """RQ1: Check retrieval hit rate."""
    total_attempts = ctx.get("total_retrieval_attempts", 0)
    hits = ctx.get("retrieval_hits", 0)  # hits = retrieved_with_score >= 0.5
    if total_attempts == 0:
        return True  # No retrievals needed
    return (hits / total_attempts) >= 0.7


def _check_knowledge_utilization(ctx: Dict[str, Any]) -> bool:
    """RQ2: Check knowledge utilization quality."""
    success = ctx.get("knowledge_success_count", 0)
    failure = ctx.get("knowledge_failure_count", 0)
    total = success + failure
    if total == 0:
        return True
    return (success / total) >= 0.5


def _check_knowledge_recency(ctx: Dict[str, Any]) -> bool:
    """RQ3: Check knowledge recency via exponential decay."""
    import math
    age_days = ctx.get("knowledge_age_days", 0)
    weight = math.exp(-age_days / 14.0)  # half-life ≈ 10 days
    return weight >= 0.3  # Not too stale


# ============================================================
# Strategy Scorer
# ============================================================

@dataclass
class StrategyScoreResult:
    """Complete strategy scoring result."""

    player_id: str
    role: str
    strategy_version: str

    strategy_impact: DimensionScore
    retrieval_quality: DimensionScore

    overall_strategy_score: float = 0.0

    # Feedback for Track C: which strategy docs should be promoted/demoted
    knowledge_feedback: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, Any]:
        return {
            "player_id": self.player_id,
            "role": self.role,
            "version": self.strategy_version,
            "impact": self.strategy_impact.raw_score,
            "retrieval_quality": self.retrieval_quality.raw_score,
            "overall": self.overall_strategy_score,
            "feedback_count": len(self.knowledge_feedback),
        }


class StrategyScorer:
    """Scores strategy impact + retrieval quality.

    Generates knowledge feedback for Track C evolution loop:
    - If strategy was applied AND outcome improved → success_count++
    - If strategy was applied BUT outcome degraded → failure_count++
    - If strategy was NOT applied → note for relevance recalibration
    """

    def __init__(self):
        self._impact_scorer = HybridScorer(list(STRATEGY_IMPACT_RUBRIC))
        self._quality_scorer = HybridScorer(list(RETRIEVAL_QUALITY_RUBRIC))

    def score_strategy_impact(
        self,
        retrieved_strategies: List[Dict[str, Any]],
        actual_action: Dict[str, Any],
        actual_outcome: Dict[str, Any],
        counterfactual_outcome: Dict[str, Any],
    ) -> DimensionScore:
        """Score how well retrieved strategies were applied.

        Args:
            retrieved_strategies: List of RetrievedStrategyLesson dicts.
            actual_action: The action the agent took.
            actual_outcome: The actual outcome.
            counterfactual_outcome: What would have happened without the action.

        Returns:
            DimensionScore for strategy impact.
        """
        ctx = {
            "retrieval_scores": [s.get("score", 0) for s in retrieved_strategies],
            "retrieved_strategies": retrieved_strategies,
            "actual_action": actual_action,
            "actual_outcome": actual_outcome,
            "counterfactual_outcome": counterfactual_outcome,
        }
        return self._impact_scorer.score(ctx)

    def score_retrieval_quality(
        self,
        total_attempts: int,
        hits: int,
        knowledge_success: int,
        knowledge_failure: int,
        knowledge_age_days: float = 0.0,
    ) -> DimensionScore:
        """Score retrieval quality metrics."""
        ctx = {
            "total_retrieval_attempts": total_attempts,
            "retrieval_hits": hits,
            "knowledge_success_count": knowledge_success,
            "knowledge_failure_count": knowledge_failure,
            "knowledge_age_days": knowledge_age_days,
        }
        return self._quality_scorer.score(ctx)

    def score_full(
        self,
        player_id: str,
        role: str,
        strategy_version: str,
        decision_contexts: List[Dict[str, Any]],
    ) -> StrategyScoreResult:
        """Complete strategy scoring across all decisions in a game.

        Args:
            player_id: Player identifier.
            role: Player's role.
            strategy_version: Strategy version used.
            decision_contexts: List of per-decision contexts, each containing:
                - retrieved_strategies, actual_action, actual_outcome,
                  counterfactual_outcome

        Returns:
            StrategyScoreResult with impact + quality scores and Track C feedback.
        """
        impact_scores = []
        quality_scores = []
        feedback_list = []

        for i, dctx in enumerate(decision_contexts):
            # Score strategy impact per decision
            impact = self.score_strategy_impact(
                dctx.get("retrieved_strategies", []),
                dctx.get("actual_action", {}),
                dctx.get("actual_outcome", {}),
                dctx.get("counterfactual_outcome", {}),
            )
            impact_scores.append(impact.raw_score)

            # Score retrieval quality
            quality = self.score_retrieval_quality(
                dctx.get("total_attempts", 1),
                dctx.get("hits", 0),
                dctx.get("knowledge_success", 0),
                dctx.get("knowledge_failure", 0),
                dctx.get("knowledge_age_days", 0),
            )
            quality_scores.append(quality.raw_score)

            # Generate Track C feedback
            for strat in dctx.get("retrieved_strategies", []):
                feedback = {
                    "doc_id": strat.get("doc_id", ""),
                    "was_applied": _check_strategy_adherence({
                        "retrieved_strategies": [strat],
                        "actual_action": dctx.get("actual_action", {}),
                    }),
                    "outcome_improved": _check_outcome_improvement({
                        "actual_outcome": dctx.get("actual_outcome", {}),
                        "counterfactual_outcome": dctx.get("counterfactual_outcome", {}),
                    }) > 0.5,
                    "situation": dctx.get("situation", ""),
                }
                feedback_list.append(feedback)

        avg_impact = sum(impact_scores) / max(1, len(impact_scores))
        avg_quality = sum(quality_scores) / max(1, len(quality_scores))

        return StrategyScoreResult(
            player_id=player_id,
            role=role,
            strategy_version=strategy_version,
            strategy_impact=DimensionScore(
                dimension="strategy_impact",
                raw_score=round(avg_impact, 4),
            ),
            retrieval_quality=DimensionScore(
                dimension="retrieval_quality",
                raw_score=round(avg_quality, 4),
            ),
            overall_strategy_score=round(0.6 * avg_impact + 0.4 * avg_quality, 4),
            knowledge_feedback=feedback_list,
        )
