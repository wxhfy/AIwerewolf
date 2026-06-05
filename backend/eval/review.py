"""Advanced B: evaluation + replay.

Interfaces:
- ReviewArtifact: structured replay payload for downstream analysis
- RoleMetrics: per-role performance indicators
- GameMetrics: game-level statistics
- ReviewProvider: builds artifacts from completed games
- Leaderboard: compares agent versions/models across matches
- BadCaseDetector: identifies decisive mistakes for review
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import Sequence

from backend.engine.models import Alignment
from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.engine.models import Player
from backend.engine.models import Role
from backend.eval.game_replay import NightActionsSnapshot
from backend.eval.game_replay import replay_hunter_shot
from backend.eval.game_replay import replay_night_with_change
from backend.eval.types import ALIGNMENT_LABELS
from backend.eval.types import COUNTERFACTUAL_TYPE_LABELS
from backend.eval.types import MVP_TYPE_LABELS
from backend.eval.types import PHASE_LABELS
from backend.eval.types import ROLE_LABELS
from backend.eval.types import SEVERITY_LABELS
from backend.eval.types import BadCaseReport
from backend.eval.types import CounterfactualCase
from backend.eval.types import EvidenceRef
from backend.eval.types import EvolutionCandidate
from backend.eval.types import GameMetrics
from backend.eval.types import LeaderboardEntry
from backend.eval.types import LeaderboardResult
from backend.eval.types import MVPResult
from backend.eval.types import PersonaMetrics
from backend.eval.types import PlayerReview
from backend.eval.types import PlayerScore
from backend.eval.types import ReportEvaluationResult
from backend.eval.types import ReportOptimizationState
from backend.eval.types import ReviewArtifact
from backend.eval.types import ReviewBonus
from backend.eval.types import ReviewReport
from backend.eval.types import RoleMetrics
from backend.eval.types import SafetyFlags
from backend.eval.types import StrategyKnowledge
from backend.eval.types import StrategySuggestion
from backend.eval.types import TurningPoint

# ---------------------------------------------------------------------------
# vNext Scorer: learned decision quality from PairwiseLogisticRanker
# ---------------------------------------------------------------------------


# Features to exclude (game-state, not decision-specific)
_VNEXT_EXCLUDE_FEATURES = {
    "camp_balance_ratio",
    "day",
    "is_endgame",
    "alive_count",
    "village_alive",
    "wolf_alive",
    "action_target_id",
}


def _vnext_safe_numeric(features: dict) -> dict:
    """Keep only numeric features, skip strings and excluded features."""
    import numpy as np

    return {
        k: float(v)
        for k, v in features.items()
        if k not in _VNEXT_EXCLUDE_FEATURES and isinstance(v, (int, float, bool, np.integer, np.floating))
    }


class VNextScorer:
    """vNext scoring engine using PairwiseLogisticRanker + baseline comparison."""

    def __init__(self, model_path: str | None = None, baseline_path: str | None = None):
        import pickle

        from backend.eval.features import register_default_extractors
        from backend.eval.pairwise_ranker import PairwiseLogisticRanker

        self.ranker = PairwiseLogisticRanker()
        self.baseline = None
        self.registry = register_default_extractors()

        root = Path(__file__).resolve().parent.parent.parent
        model_path = model_path or str(root / "data" / "health" / "decision_quality_model_vnext_real.pkl")
        baseline_path = baseline_path or str(root / "data" / "health" / "vnext_baseline_features.pkl")

        try:
            self.ranker.load(model_path)
            with open(baseline_path, "rb") as f:
                self.baseline = pickle.load(f)
            self._loaded = True
        except Exception:
            self._loaded = False

    def score_game(self, state: GameState) -> dict[str, dict]:
        """Score all players in a game.

        Returns per-player {vnext_score, feature_count, features_used}.
        """
        if not self._loaded or self.baseline is None:
            return {}

        # Build opportunity-like dicts from game state
        results = {}
        for player in state.players:
            # Score based on player's actions in the game
            scores = []
            for event in state.events:
                actor_id = (
                    event.payload.get("actor_id") or event.payload.get("voter_id") or event.payload.get("player_id")
                )
                if actor_id != player.id:
                    continue
                if event.type not in {
                    EventType.VOTE_CAST,
                    EventType.NIGHT_ACTION,
                    EventType.CHAT_MESSAGE,
                    EventType.HUNTER_SHOT,
                }:
                    continue

                # Build a minimal opportunity-like dict
                opp = {
                    "player_id": player.id,
                    "role": player.role.value if hasattr(player.role, "value") else str(player.role),
                    "opportunity_type": event.type.value if hasattr(event.type, "value") else str(event.type),
                    "day": event.day,
                    "phase": event.phase.value if hasattr(event.phase, "value") else str(event.phase),
                    "chosen_action": event.payload,
                    "target_features": {},
                    "game_features": {},
                    "outcome_features": {},
                    "public_context_summary": "",
                    "private_context_summary": "",
                }

                try:
                    result = self.registry.extract(opp)
                    features = _vnext_safe_numeric(result.features)
                except Exception:
                    continue

                if not features:
                    continue

                prob = self.ranker.compare_pair(features, self.baseline)
                scores.append(prob)

            if scores:
                results[player.id] = {
                    "vnext_score": round(float(sum(scores) / len(scores)), 4),
                    "feature_count": len(scores),
                    "features_used": len(self.ranker.feature_names) if self.ranker.feature_names else 0,
                }

        return results


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ReviewArtifact:
    """Structured replay payload for RAG indexing and review analysis."""

    game_id: str
    winner: str | None
    timeline: list[dict[str, Any]]
    daily_summaries: dict[int, list[str]]
    daily_summary_facts: dict[int, list[dict[str, Any]]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlayerScore:
    """Per-player multi-dimension score for one completed match."""

    player_id: str
    player_name: str
    persona_id: str | None
    persona_name: str | None
    role: str
    alignment: str
    camp_result_score: float
    role_task_score: float
    vote_score: float
    speech_score: float
    skill_score: float
    survival_score: float
    mistake_penalty: float
    final_score: float
    # Outcome-independent score (0-100): same formula as final_score but
    # drops camp_result_score and re-normalizes the remaining weights.
    # Use this when comparing decision quality across players regardless of
    # whether they happened to be on the winning side.
    process_score: float = 0.0
    # Pure outcome contribution (0-100): 100 if player's alignment won.
    # final_score ≈ 0.75 * process_score + 0.25 * outcome_bonus
    outcome_bonus: float = 0.0
    # vNext: learned decision quality from PairwiseLogisticRanker (0-1).
    # Compared against baseline (median features) to produce meaningful scores.
    vnext_score: float = 0.0
    highlights: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)
    adjusted_final_score: float | None = None
    impact_bonus: float = 0.0
    semantic_highlight_bonus: float = 0.0
    review_penalty: float = 0.0
    # v2 structured fields
    raw_score: float = 0.0
    role_normalized_score: float = 0.0
    confidence: float = 0.0
    score_reason: str = ""
    evidence_refs: list[Any] = field(default_factory=list)
    rule_based: bool = True
    judge_agreement: float | None = None


@dataclass
class PersonaMetrics:
    """Cross-game persona aggregation with role-normalized fairness."""

    persona_id: str | None
    persona_name: str | None
    games_played: int
    raw_win_rate: float
    avg_final_score: float
    role_normalized_score: float
    avg_vote_score: float
    avg_speech_score: float
    avg_skill_score: float
    critical_mistakes: int
    best_role: str | None
    weak_role: str | None


@dataclass
class ReviewBonus:
    """Replay-layer bonus/penalty with explicit evidence."""

    player_id: str
    bonus_type: str
    score_delta: float
    reason: str
    evidence: list[str]
    confidence: float
    day: int | None = None
    phase: str | None = None
    category: str = "impact"
    evidence_refs: list[Any] = field(default_factory=list)
    visibility_scope: str = "public"
    safe_for_track_c_learning: bool = True


@dataclass
class MVPResult:
    """MVP output from replay-layer weighted selection."""

    player_id: str
    player_name: str
    role: str
    alignment: str
    mvp_type: str
    mvp_score: float
    reason: str
    evidence: list[str]
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class RoleMetrics:
    """Per-role performance metrics (Advanced B scoring dimensions)."""

    role: str
    player_name: str
    alive_at_end: bool
    survival_rounds: int
    vote_precision: float
    useful_ability_uses: int
    total_ability_uses: int
    deception_score: float = 0.0
    mistakes: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    final_score: float = 0.0


@dataclass
class GameMetrics:
    """Game-level statistics for one match."""

    game_id: str
    winner: str | None
    total_days: int
    total_events: int
    wolf_elimination_rate: float
    village_survival_rate: float
    info_efficiency: float
    role_metrics: list[RoleMetrics] = field(default_factory=list)
    player_scores: list[PlayerScore] = field(default_factory=list)
    persona_metrics: list[PersonaMetrics] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LeaderboardEntry:
    """One row in an aggregated leaderboard view."""

    leaderboard_type: str
    key: str
    display_name: str
    games_played: int
    wins: int
    win_rate: float
    avg_final_score: float
    avg_adjusted_final_score: float
    avg_vote_score: float
    avg_speech_score: float
    avg_skill_score: float
    avg_survival_score: float
    avg_impact_bonus: float
    avg_semantic_bonus: float
    critical_mistakes: int
    role_normalized_score: float | None = None
    best_role: str | None = None
    weak_role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LeaderboardResult:
    """Container for one leaderboard output."""

    leaderboard_type: str
    entries: list[LeaderboardEntry]
    generated_at: str
    source_games: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BadCaseReport:
    """A detected mistake with improvement suggestions."""

    game_id: str
    day: int
    player_name: str
    role: str
    mistake_type: str
    description: str
    suggested_fix: str
    severity: str
    evidence_event_ids: list[str] = field(default_factory=list)
    # v2 structured fields (backward-compatible defaults)
    id: str = ""
    bad_case_type: str = ""
    phase: str = ""
    actor_id: str = ""
    trigger_condition: str = ""
    observed_action: str = ""
    expected_better_action: str = ""
    impact_estimate: float = 0.0
    confidence: float = 0.0
    evidence_refs: list[Any] = field(default_factory=list)
    visibility_scope: str = "public"
    safety_flags: Any = None
    safe_for_track_c_learning: bool = True


@dataclass
class TurningPoint:
    """One decisive moment that materially changed the game trajectory."""

    day: int | None
    phase: str | None
    title: str
    description: str
    impact: float
    related_players: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class StrategySuggestion:
    """Actionable follow-up advice derived from review findings."""

    target_type: str
    target: str
    suggestion_type: str
    suggestion: str
    source: str
    priority: str
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class PlayerReview:
    """Per-player structured replay narrative."""

    player_id: str
    player_name: str
    role: str
    alignment: str
    rule_score: float
    adjusted_final_score: float
    # Outcome-independent process score (0-100). Use to compare decision
    # quality across players without "wolves won" inflating wolf scores or
    # "village lost" deflating villagers who voted correctly.
    process_score: float = 0.0
    outcome_bonus: float = 0.0
    rank: int = 0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    speech_summary: str = ""
    overall_summary: str = ""
    rule_score_reasons: list[str] = field(default_factory=list)
    adjustment_reasons: list[str] = field(default_factory=list)
    score_summary: str = ""


@dataclass
class CounterfactualCase:
    """Lightweight local counterfactual explanation without full game-tree replay."""

    case_id: str
    game_id: str
    day: int | None
    phase: str | None
    counterfactual_type: str
    original_decision: str
    alternative_decision: str
    expected_effect: str
    affected_players: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    severity: str = "minor"
    source_bad_case_id: str | None = None
    source_turning_point_id: str | None = None
    # B §13 effect_type: vote_flip → exact_recalculation, skill → local_recalculation,
    # info_release → estimated. Drives ValidAgent §21 CounterfactualSoundnessGate.
    effect_type: str = "estimated"
    recomputed_outcome: dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: list[str] = field(default_factory=list)
    # v2 structured fields
    original_action: str = ""
    alternative_action: str = ""
    expected_delta: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    evidence_refs: list[Any] = field(default_factory=list)
    visibility_scope: str = "public"
    safe_for_track_c_learning: bool = True
    actor_id: str = ""
    role: str = ""


@dataclass
class StrategyKnowledge:
    """Sanitized reusable strategy knowledge safe to feed back into role agents."""

    knowledge_id: str
    target_role: str
    source_game_id: str
    source_type: str
    trigger_condition: str
    suggestion: str
    priority: str
    evidence_summary: str
    safe_for_agent: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class ReviewReport:
    """Structured replay report for one completed match."""

    game_id: str
    winner: str | None
    total_days: int
    total_events: int
    game_summary: str
    rule_variant: str = "standard_competition_v1"
    scoreboard: list[dict[str, Any]] = field(default_factory=list)
    mvp_results: list[MVPResult] = field(default_factory=list)
    turning_points: list[TurningPoint] = field(default_factory=list)
    player_reviews: list[PlayerReview] = field(default_factory=list)
    bad_cases: list[BadCaseReport] = field(default_factory=list)
    counterfactuals: list[CounterfactualCase] = field(default_factory=list)
    strategy_suggestions: list[StrategySuggestion] = field(default_factory=list)
    bonuses: list[dict[str, Any]] = field(default_factory=list)
    evolution_candidates: list[EvolutionCandidate] = field(default_factory=list)
    judge_panel: dict[str, Any] = field(default_factory=dict)
    calibration_info: dict[str, Any] = field(default_factory=dict)
    safety_flags: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReportEvaluationResult:
    """Structured evaluator output for one markdown review draft."""

    grade: str
    score: float
    issues: list[str] = field(default_factory=list)
    feedback: str = ""
    required_fixes: list[str] = field(default_factory=list)


@dataclass
class ReportOptimizationState:
    """State container for evaluator-optimizer style report revision."""

    game_id: str
    review_report: ReviewReport
    review_context: dict[str, Any] = field(default_factory=dict)
    draft_markdown: str = ""
    final_markdown: str = ""
    evaluator_result: ReportEvaluationResult | None = None
    feedback_history: list[ReportEvaluationResult] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 2
    quality_passed: bool = False


ROLE_LABELS = {
    "Seer": "预言家",
    "Werewolf": "狼人",
    "Witch": "女巫",
    "Hunter": "猎人",
    "Guard": "守卫",
    "Villager": "村民",
}

ALIGNMENT_LABELS = {
    "village": "好人阵营",
    "wolf": "狼人阵营",
}

PHASE_LABELS = {
    "NIGHT_START": "夜晚开始",
    "NIGHT_GUARD_ACTION": "守卫守护",
    "NIGHT_WOLF_ACTION": "狼人行动",
    "NIGHT_WITCH_ACTION": "女巫行动",
    "NIGHT_SEER_ACTION": "预言家查验",
    "NIGHT_RESOLVE": "夜晚结算",
    "DAY_START": "白天开始",
    "DAY_BADGE_SIGNUP": "警长报名",
    "DAY_BADGE_SPEECH": "警长竞选发言",
    "DAY_BADGE_ELECTION": "警长选举",
    "DAY_PK_SPEECH": "PK发言",
    "DAY_SPEECH": "白天发言",
    "DAY_VOTE": "白天投票",
    "DAY_LAST_WORDS": "遗言",
    "DAY_RESOLVE": "白天结算",
    "BADGE_TRANSFER": "警长移交",
    "HUNTER_SHOOT": "猎人开枪",
    "WHITE_WOLF_KING_BOOM": "白狼王自爆",
    "GAME_END": "游戏结束",
}

MVP_TYPE_LABELS = {
    "global_mvp": "全局 MVP",
    "winning_camp_mvp": "胜方 MVP",
}

COUNTERFACTUAL_TYPE_LABELS = {
    # Core (existing, refined)
    "vote": "投票反事实",
    "skill": "技能反事实",  # backward compat — now also split into subtypes below
    "info_release": "信息释放反事实",
    # Skill subtypes (from research: Beyond Survival §4.2 skill-efficiency metrics)
    "witch_poison": "女巫毒药反事实",
    "witch_save": "女巫解药反事实",
    "hunter_shot": "猎人开枪反事实",
    # New dimensions (from research: Reflection-Bench §3.5 counterfactual thinking)
    "guard_target": "守卫守护反事实",
    "seer_target": "预言家查验反事实",
    # New dimensions (from research: Ask WhAI §4 belief perturbation + Beyond Survival §5.1)
    "speech_strategy": "发言策略反事实",
    "stance_flip": "立场转变反事实",
    "claim_timing": "身份跳报反事实",
    "badge_election": "警徽选举反事实",
    # New dimension (from research: CAIR agent influence ranking)
    "coordination": "团队协调反事实",
}

SEVERITY_LABELS = {
    "critical": "致命失误",
    "major": "重大失误",
    "minor": "轻微失误",
}


# ---------------------------------------------------------------------------
# Provider interfaces (Protocols for swappable implementations)
# ---------------------------------------------------------------------------


class ReviewProvider(Protocol):
    def build_artifact(self, state: GameState) -> ReviewArtifact: ...

    def compute_metrics(self, state: GameState) -> GameMetrics: ...

    def detect_bad_cases(self, state: GameState) -> list[BadCaseReport]: ...


class LeaderboardProvider(Protocol):
    def add_game(self, metrics: GameMetrics) -> None: ...

    def top_agents(self, role: str, limit: int = 10) -> list[LeaderboardEntry]: ...

    def compare_versions(self, version_a: str, version_b: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Replay weighting
# ---------------------------------------------------------------------------


class FinalScoreCalculator:
    """Apply validated review bonuses to rule-based final scores."""

    BONUS_CAP = 5.0
    POSITIVE_CAP = 10.0
    NEGATIVE_CAP = -10.0
    MIN_CONFIDENCE = 0.6

    def apply(
        self,
        player_scores: Sequence[PlayerScore],
        review_bonuses: Sequence[ReviewBonus],
    ) -> list[PlayerScore]:
        bonuses_by_player: dict[str, list[ReviewBonus]] = defaultdict(list)
        for bonus in review_bonuses:
            bonuses_by_player[bonus.player_id].append(bonus)

        adjusted_scores: list[PlayerScore] = []
        for score in player_scores:
            positive = 0.0
            impact = 0.0
            semantic = 0.0
            penalty_total = 0.0
            for bonus in bonuses_by_player.get(score.player_id, []):
                if not self._is_valid(bonus):
                    continue
                delta = max(-self.BONUS_CAP, min(self.BONUS_CAP, bonus.score_delta))
                if delta >= 0:
                    room_left = self.POSITIVE_CAP - positive
                    applied = min(delta, max(room_left, 0.0))
                    positive += applied
                    if bonus.category == "impact":
                        impact += applied
                    elif bonus.category == "semantic":
                        semantic += applied
                else:
                    room_left = self.NEGATIVE_CAP - penalty_total
                    applied = max(delta, room_left)
                    penalty_total += applied
            score.impact_bonus = round(impact, 2)
            score.semantic_highlight_bonus = round(semantic, 2)
            score.review_penalty = round(abs(penalty_total), 2)
            score.adjusted_final_score = round(min(100.0, max(0.0, score.final_score + positive + penalty_total)), 2)
            adjusted_scores.append(score)
        return adjusted_scores

    def _is_valid(self, bonus: ReviewBonus) -> bool:
        return bool(bonus.evidence) and bonus.confidence >= self.MIN_CONFIDENCE


class MVPSelector:
    """Selects replay-layer MVPs using adjusted scores plus impact/highlight weights."""

    def select(
        self,
        state: GameState,
        player_scores: Sequence[PlayerScore],
        review_bonuses: Sequence[ReviewBonus],
    ) -> list[MVPResult]:
        if not player_scores:
            return []
        bonus_map: dict[str, list[ReviewBonus]] = defaultdict(list)
        for bonus in review_bonuses:
            bonus_map[bonus.player_id].append(bonus)

        global_best = max(player_scores, key=lambda score: self._mvp_score(score))
        winning_scores = [
            score for score in player_scores if state.winner is not None and score.alignment == state.winner.value
        ] or list(player_scores)
        winning_best = max(winning_scores, key=lambda score: self._mvp_score(score))

        return [
            self._build_result(global_best, "global_mvp", bonus_map.get(global_best.player_id, []), state),
            self._build_result(winning_best, "winning_camp_mvp", bonus_map.get(winning_best.player_id, []), state),
        ]

    def _mvp_score(self, score: PlayerScore) -> float:
        adjusted = score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score
        return round(0.60 * adjusted + 0.25 * score.impact_bonus + 0.15 * score.semantic_highlight_bonus, 2)

    def _build_result(
        self,
        score: PlayerScore,
        mvp_type: str,
        bonuses: Sequence[ReviewBonus],
        state: GameState,
    ) -> MVPResult:
        evidence = [item for bonus in bonuses for item in bonus.evidence][:4] or score.highlights[:3]
        event_ids = [
            event.id
            for event in state.events
            if (event.payload.get("actor_id") or event.payload.get("voter_id") or event.payload.get("player_id"))
            == score.player_id
        ][-4:]
        if score.impact_bonus > 0 and score.semantic_highlight_bonus > 0:
            reason = "硬规则表现稳定，同时在关键局势影响和高质量复盘高光上都有突出贡献。"
        elif score.impact_bonus > 0:
            reason = "通过关键节点上的高影响操作，制造了本局最大的复盘层增益。"
        elif score.semantic_highlight_bonus > 0:
            reason = "通过高质量的信息转化或欺骗，打出了最强的复盘高光价值。"
        else:
            reason = "在复盘加权后的最终得分中排名全场领先。"
        return MVPResult(
            player_id=score.player_id,
            player_name=score.player_name,
            role=score.role,
            alignment=score.alignment,
            mvp_type=mvp_type,
            mvp_score=self._mvp_score(score),
            reason=reason,
            evidence=evidence,
            evidence_event_ids=event_ids,
        )


class ReviewBonusDetector:
    """Rule-based replay-layer detector for high-impact highlights and extra penalties."""

    def detect(
        self,
        state: GameState,
        player_scores: Sequence[PlayerScore],
        bad_case_reports: Sequence[BadCaseReport],
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        score_by_player = {score.player_id: score for score in player_scores}
        reports_by_player: dict[str, list[BadCaseReport]] = defaultdict(list)
        name_to_id = {player.name: player.id for player in state.players}
        for report in bad_case_reports:
            player_id = name_to_id.get(report.player_name)
            if player_id:
                reports_by_player[player_id].append(report)

        bonuses: list[ReviewBonus] = []
        bonuses.extend(self._detect_key_vote_bonuses(state, contexts))
        bonuses.extend(self._detect_seer_conversion_bonus(state, contexts))
        bonuses.extend(self._detect_seer_support_bonuses(state, contexts))
        bonuses.extend(self._detect_witch_bonuses(state, contexts))
        bonuses.extend(self._detect_guard_bonuses(state, contexts))
        bonuses.extend(self._detect_hunter_bonuses(state, contexts))
        bonuses.extend(self._detect_wolf_bonuses(state, contexts))
        bonuses.extend(self._detect_villager_bonuses(state, contexts))
        bonuses.extend(self._detect_review_penalties(state, contexts, reports_by_player, score_by_player))
        return bonuses

    def _detect_key_vote_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for day in sorted({event.day for event in state.events if event.type == EventType.VOTE_CAST}):
            day_votes = [event for event in state.events if event.type == EventType.VOTE_CAST and event.day == day]
            exiled = next(
                (
                    event
                    for event in state.events
                    if event.type == EventType.PLAYER_DIED
                    and event.day == day
                    and event.payload.get("reason") == "vote"
                ),
                None,
            )
            if exiled is None:
                continue
            exiled_id = exiled.payload.get("player_id")
            counts: dict[str, int] = defaultdict(int)
            for event in sorted(day_votes, key=lambda item: item.ts):
                target_id = event.payload.get("target_id")
                voter_id = event.payload.get("voter_id")
                if not target_id or not voter_id:
                    continue
                previous_max = max(counts.values()) if counts else 0
                previous_target = counts.get(target_id, 0)
                previous_leaders = {pid for pid, count in counts.items() if count == previous_max} if counts else set()
                counts[target_id] += 1
                if target_id != exiled_id:
                    continue
                if counts[target_id] <= previous_max or previous_target == previous_max and previous_max > 0:
                    if not (
                        target_id in previous_leaders and len(previous_leaders) > 1 and counts[target_id] > previous_max
                    ):
                        continue
                voter = state.player(voter_id)
                target = state.player(target_id)
                if voter.alignment == target.alignment:
                    continue
                if voter.role == Role.VILLAGER:
                    bonuses.append(
                        ReviewBonus(
                            player_id=voter.id,
                            bonus_type="decisive_vote",
                            score_delta=2.5,
                            reason="关键一票将放逐目标成功转向敌对阵营。",
                            evidence=[f"第 {day} 天 {voter.name} 的投票让 {target.name} 成为领先票型，并最终被放逐。"],
                            confidence=0.8,
                            day=day,
                            phase=event.phase.value,
                            category="impact",
                        )
                    )
                else:
                    bonuses.append(
                        ReviewBonus(
                            player_id=voter.id,
                            bonus_type="decisive_vote",
                            score_delta=1.5,
                            reason="关键投票直接改变了当轮的放逐结果。",
                            evidence=[f"第 {day} 天 {voter.name} 的投票让 {target.name} 获得最终领先。"],
                            confidence=0.75,
                            day=day,
                            phase=event.phase.value,
                            category="impact",
                        )
                    )
        return bonuses

    def _detect_seer_conversion_bonus(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.SEER:
                continue
            wolf_checks = [
                event
                for event in ctx.private_info_events
                if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")
            ]
            for check_event in wolf_checks:
                target_id = check_event.payload.get("target_id")
                target_name = check_event.payload.get("target_name")
                releasing_speech = next(
                    (
                        speech
                        for speech in ctx.speech_events
                        if target_name and target_name in str(speech.payload.get("speech", ""))
                    ),
                    None,
                )
                if releasing_speech is None:
                    continue
                influenced_votes = [
                    event
                    for event in state.events
                    if event.type == EventType.VOTE_CAST
                    and event.day >= releasing_speech.day
                    and event.payload.get("voter_id") != player_id
                    and event.payload.get("target_id") == target_id
                ]
                if influenced_votes and self._was_voted_out(state, str(target_id)):
                    bonuses.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="seer_info_conversion",
                            score_delta=3.5,
                            reason="预言家将查杀信息成功转化为公共压力，并改变了票型走向。",
                            evidence=[
                                f"查验结果命中 {target_name}。",
                                f"在第 {releasing_speech.day} 天公开发言中释放了该信息。",
                                f"之后其他玩家跟票投向 {target_name}，且目标最终被放逐。",
                            ],
                            confidence=0.85,
                            day=releasing_speech.day,
                            phase=releasing_speech.phase.value,
                            category="impact",
                        )
                    )
        return bonuses

    def _detect_seer_support_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.SEER:
                continue
            good_checks = [
                event
                for event in ctx.private_info_events
                if event.payload.get("kind") == "seer_result" and not event.payload.get("is_wolf")
            ]
            for check_event in good_checks:
                target_name = str(check_event.payload.get("target_name") or "")
                if not target_name:
                    continue
                support_speech = next(
                    (
                        speech
                        for speech in ctx.speech_events
                        if speech.day >= check_event.day and target_name in str(speech.payload.get("speech", ""))
                    ),
                    None,
                )
                if support_speech is None:
                    continue
                target_player = next((player for player in state.players if player.name == target_name), None)
                if target_player is None or not target_player.alive:
                    continue
                bonuses.append(
                    ReviewBonus(
                        player_id=player_id,
                        bonus_type="seer_good_clear_guidance",
                        score_delta=1.2,
                        reason="预言家将金水或偏好人信息转化成了对白天站边的稳定支撑。",
                        evidence=[
                            f"第 {check_event.day} 夜查验结果确认 {target_name} 为好人倾向。",
                            f"第 {support_speech.day} 天公开发言中明确为 {target_name} 提供了站边支撑。",
                        ],
                        confidence=0.72,
                        day=support_speech.day,
                        phase=support_speech.phase.value,
                        category="semantic",
                    )
                )
                break
        return bonuses

    def _detect_witch_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        wolves = [player for player in state.players if player.alignment == Alignment.WOLF]
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.WITCH:
                continue
            for event in ctx.night_action_events:
                action_type = event.payload.get("action_type")
                target = self._event_target(state, event)
                if target is None:
                    continue
                if action_type == "witch_poison" and target.alignment == Alignment.WOLF:
                    dead_wolves = {
                        death.payload.get("player_id") for death in state.events if death.type == EventType.PLAYER_DIED
                    }
                    if len(dead_wolves.intersection({wolf.id for wolf in wolves})) == len(wolves):
                        bonuses.append(
                            ReviewBonus(
                                player_id=player_id,
                                bonus_type="last_wolf_poison",
                                score_delta=4.0,
                                reason="女巫毒掉最后一狼，直接终结了狼队威胁。",
                                evidence=[f"毒杀 {target.name} 后，至对局结束时全部狼人已出局。"],
                                confidence=0.9,
                                day=event.day,
                                phase=event.phase.value,
                                category="impact",
                            )
                        )
                if action_type == "witch_save" and target.role in {Role.SEER, Role.HUNTER, Role.GUARD, Role.WITCH}:
                    contributed = self._player_generated_followup_value(state, target.id)
                    if contributed:
                        bonuses.append(
                            ReviewBonus(
                                player_id=player_id,
                                bonus_type="key_role_save",
                                score_delta=2.5,
                                reason="女巫成功救下关键角色，并保留了后续价值。",
                                evidence=[
                                    f"救下 {target.name}（{ROLE_LABELS.get(target.role.value, target.role.value)}）后，该角色后续继续产生有效贡献。"
                                ],
                                confidence=0.8,
                                day=event.day,
                                phase=event.phase.value,
                                category="impact",
                            )
                        )
        return bonuses

    def _detect_hunter_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        wolves = [player for player in state.players if player.alignment == Alignment.WOLF]
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.HUNTER:
                continue
            for event in ctx.hunter_shot_events:
                target = self._event_target(state, event)
                if target is None or target.alignment != Alignment.WOLF:
                    continue
                dead_wolves = {
                    death.payload.get("player_id") for death in state.events if death.type == EventType.PLAYER_DIED
                }
                if len(dead_wolves.intersection({wolf.id for wolf in wolves})) == len(wolves):
                    bonuses.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="final_wolf_shot",
                            score_delta=4.0,
                            reason="猎人开枪带走最后一狼，直接锁定胜势。",
                            evidence=[f"猎人开枪击杀 {target.name} 后，所有狼人均已出局。"],
                            confidence=0.9,
                            day=event.day,
                            phase=event.phase.value,
                            category="impact",
                        )
                    )
        return bonuses

    def _detect_guard_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.GUARD:
                continue
            guard_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "guard"]
            protected_power_roles = 0
            for event in guard_events:
                target = self._event_target(state, event)
                if target is None:
                    continue
                if target.role in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD}:
                    protected_power_roles += 1
                if self._is_majority_wolf_target(state, target.id, event.day) and not self._died_by_reason(
                    state, target.id, "wolf", event.day
                ):
                    bonuses.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="guard_block_kill",
                            score_delta=2.0,
                            reason="守卫在狼刀位上成功守住目标，直接阻断了一次夜间减员。",
                            evidence=[
                                f"第 {event.day} 夜守卫选择守护 {target.name}。",
                                f"{target.name} 同夜是主要狼刀目标，但并未因狼刀死亡。",
                            ],
                            confidence=0.82,
                            day=event.day,
                            phase=event.phase.value,
                            category="impact",
                        )
                    )
            if protected_power_roles >= 2:
                bonuses.append(
                    ReviewBonus(
                        player_id=player_id,
                        bonus_type="guard_key_role_cover",
                        score_delta=1.1,
                        reason="守卫多次把守护资源放在高价值神职身上，提升了好人信息链稳定性。",
                        evidence=[f"本局守卫至少两次守护关键神职，共计 {protected_power_roles} 次。"],
                        confidence=0.74,
                        day=state.day,
                        phase=state.phase.value,
                        category="semantic",
                    )
                )
        return bonuses

    def _detect_wolf_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.WEREWOLF:
                continue
            for vote_event in ctx.vote_events:
                target = self._event_target(state, vote_event)
                if (
                    target is None
                    or target.alignment != Alignment.VILLAGE
                    or target.role not in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD}
                ):
                    continue
                if not self._was_voted_out(state, target.id):
                    continue
                spoke_against_target = any(
                    target.name in str(event.payload.get("speech", ""))
                    for event in ctx.speech_events
                    if event.day <= vote_event.day
                )
                if spoke_against_target:
                    bonuses.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="wolf_power_role_push",
                            score_delta=3.0,
                            reason="狼人通过白天发言和投票成功推动关键好人角色出局。",
                            evidence=[f"第 {vote_event.day} 天对白天焦点 {target.name} 施压并完成放逐。"],
                            confidence=0.8,
                            day=vote_event.day,
                            phase=vote_event.phase.value,
                            category="impact",
                        )
                    )
        return bonuses

    def _detect_villager_bonuses(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.VILLAGER:
                continue
            correct_votes = [
                event
                for event in sorted(ctx.vote_events, key=lambda item: (item.day, item.ts))
                if (target := self._event_target(state, event)) is not None and target.alignment == Alignment.WOLF
            ]
            if len(correct_votes) >= 2:
                bonuses.append(
                    ReviewBonus(
                        player_id=player_id,
                        bonus_type="villager_vote_chain",
                        score_delta=1.3,
                        reason="村民连续多轮把票稳定投在狼人阵营，形成了高质量的公共归票贡献。",
                        evidence=[f"第 {event.day} 天命中狼人票型。" for event in correct_votes[:3]],
                        confidence=0.76,
                        day=correct_votes[-1].day,
                        phase=correct_votes[-1].phase.value,
                        category="semantic",
                    )
                )
        return bonuses

    def _detect_review_penalties(
        self,
        state: GameState,
        contexts: dict[str, _PlayerContext],
        reports_by_player: dict[str, list[BadCaseReport]],
        score_by_player: dict[str, PlayerScore],
    ) -> list[ReviewBonus]:
        penalties: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            player = ctx.player
            reports = reports_by_player.get(player_id, [])
            if player.role == Role.SEER and any("did not release" in report.description for report in reports):
                penalties.append(
                    ReviewBonus(
                        player_id=player_id,
                        bonus_type="missed_info_release",
                        score_delta=-2.0,
                        reason="Replay layer penalizes missing a high-value public conversion window after a wolf check.",
                        evidence=[report.description for report in reports if "did not release" in report.description][
                            :2
                        ],
                        confidence=0.85,
                        category="penalty",
                    )
                )
            if player.role == Role.WITCH and any("poisoned villager-side" in report.description for report in reports):
                if player.alignment != state.winner:
                    penalties.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="collapse_poison",
                            score_delta=-1.0,
                            reason="Mis-poison also contributed to the losing collapse, so replay adds a small situational penalty.",
                            evidence=[
                                report.description
                                for report in reports
                                if "poisoned villager-side" in report.description
                            ][:1],
                            confidence=0.7,
                            category="penalty",
                        )
                    )
            if player.role == Role.VILLAGER:
                repeated_target = self._repeated_wrong_lead_target(state, ctx)
                if repeated_target is not None and repeated_target.role in {
                    Role.SEER,
                    Role.WITCH,
                    Role.HUNTER,
                    Role.GUARD,
                }:
                    penalties.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="wrong_day_lead",
                            score_delta=-2.5,
                            reason="Replay penalizes repeatedly driving pressure onto a key villager-side target.",
                            evidence=[
                                f"Repeatedly named and voted {repeated_target.name}, who was a {repeated_target.role.value}."
                            ],
                            confidence=0.8,
                            category="penalty",
                        )
                    )
            if player.role == Role.WEREWOLF and self._was_voted_out(state, player_id):
                same_alignment_votes = [report for report in reports if "wolf teammate" in report.description]
                if same_alignment_votes:
                    penalties.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="wolf_self_exposure",
                            score_delta=-1.5,
                            reason="Replay penalizes self-exposing wolf behavior that also preceded your own elimination.",
                            evidence=[same_alignment_votes[0].description],
                            confidence=0.75,
                            category="penalty",
                        )
                    )
        return penalties

    def _event_target(self, state: GameState, event: GameEvent) -> Player | None:
        target_id = event.payload.get("target_id")
        if not target_id:
            return None
        return state.player(str(target_id))

    def _player_generated_followup_value(self, state: GameState, player_id: str) -> bool:
        for event in state.events:
            if event.payload.get("actor_id") == player_id and event.type in {
                EventType.CHAT_MESSAGE,
                EventType.NIGHT_ACTION,
                EventType.HUNTER_SHOT,
            }:
                return True
            if (
                event.type == EventType.PRIVATE_INFO
                and player_id in event.visible_to
                and event.payload.get("kind") == "seer_result"
            ):
                return True
        return False

    def _same_alignment_vote_count_for_target(self, state: GameState, day: int, target_id: str) -> int:
        count = 0
        target = state.player(target_id)
        for event in state.events:
            if event.type != EventType.VOTE_CAST or event.day != day:
                continue
            voter_id = event.payload.get("voter_id")
            if not voter_id:
                continue
            voter = state.player(voter_id)
            if voter.alignment == target.alignment and event.payload.get("target_id") == target_id:
                count += 1
        return count

    def _repeated_wrong_lead_target(self, state: GameState, ctx: _PlayerContext) -> Player | None:
        target_counts: dict[str, int] = defaultdict(int)
        for event in ctx.vote_events:
            target_id = event.payload.get("target_id")
            if target_id:
                target_counts[str(target_id)] += 1
        for event in ctx.speech_events:
            speech = str(event.payload.get("speech", ""))
            for player in state.players:
                if player.id != ctx.player.id and player.name in speech:
                    target_counts[player.id] += 1
        if not target_counts:
            return None
        target_id, count = max(target_counts.items(), key=lambda item: item[1])
        if count < 3:
            return None
        target = state.player(target_id)
        if target.alignment == Alignment.VILLAGE and self._was_voted_out(state, target.id):
            return target
        return None

    def _was_voted_out(self, state: GameState, player_id: str) -> bool:
        return any(
            event.type == EventType.PLAYER_DIED
            and event.payload.get("player_id") == player_id
            and event.payload.get("reason") == "vote"
            for event in state.events
        )

    def _died_by_reason(self, state: GameState, player_id: str, reason: str, day: int | None = None) -> bool:
        return any(
            event.type == EventType.PLAYER_DIED
            and event.payload.get("player_id") == player_id
            and event.payload.get("reason") == reason
            and (day is None or event.day == day)
            for event in state.events
        )

    def _is_majority_wolf_target(self, state: GameState, target_id: str, day: int) -> bool:
        attack_events = [
            event
            for event in state.events
            if event.type == EventType.NIGHT_ACTION
            and event.day == day
            and event.payload.get("action_type") == "attack"
        ]
        if not attack_events:
            return False
        counts: dict[str, int] = defaultdict(int)
        for event in attack_events:
            voted_target = event.payload.get("target_id")
            if voted_target:
                counts[str(voted_target)] += 1
        if not counts:
            return False
        best_count = max(counts.values())
        winners = sorted(pid for pid, count in counts.items() if count == best_count)
        return bool(winners and winners[0] == target_id)


@dataclass
class _PlayerContext:
    player: Player
    vote_events: list[GameEvent] = field(default_factory=list)
    speech_events: list[GameEvent] = field(default_factory=list)
    night_action_events: list[GameEvent] = field(default_factory=list)
    private_info_events: list[GameEvent] = field(default_factory=list)
    death_events: list[GameEvent] = field(default_factory=list)
    hunter_shot_events: list[GameEvent] = field(default_factory=list)


class MetricsCalculator:
    """Computes multi-dimensional role and persona metrics from one match."""

    MINOR_PENALTY = 0.08
    MAJOR_PENALTY = 0.18
    CRITICAL_PENALTY = 0.32
    POWER_ROLES = {Role.SEER.value, Role.WITCH.value, Role.HUNTER.value, Role.GUARD.value}

    # Role baseline statistics for normalization (default values — updated
    # via calibration when enough game data is available).
    ROLE_BASELINE_MEAN: dict[str, float] = {
        "Seer": 52.0,
        "Witch": 50.0,
        "Hunter": 48.0,
        "Guard": 47.0,
        "Villager": 42.0,
        "Werewolf": 55.0,
        "WhiteWolfKing": 55.0,
        "Idiot": 43.0,
    }
    ROLE_BASELINE_STD: dict[str, float] = {
        "Seer": 12.0,
        "Witch": 12.0,
        "Hunter": 12.0,
        "Guard": 12.0,
        "Villager": 10.0,
        "Werewolf": 14.0,
        "WhiteWolfKing": 14.0,
        "Idiot": 10.0,
    }

    def __init__(
        self,
        *,
        bonus_detector: ReviewBonusDetector | None = None,
        final_score_calculator: FinalScoreCalculator | None = None,
        mvp_selector: MVPSelector | None = None,
        vnext_scorer: VNextScorer | None = None,
    ) -> None:
        self.bonus_detector = bonus_detector or ReviewBonusDetector()
        self.final_score_calculator = final_score_calculator or FinalScoreCalculator()
        self.mvp_selector = mvp_selector or MVPSelector()
        self._vnext_scorer = vnext_scorer

    def compute(self, state: GameState) -> GameMetrics:
        contexts = self._build_contexts(state)
        bad_case_reports = self.detect_bad_cases(state)
        reports_by_player = self._reports_by_player(state, bad_case_reports)
        player_scores = [
            self._build_player_score(state, contexts[player.id], reports_by_player.get(player.id, []))
            for player in state.players
        ]
        role_metrics = [
            self._build_role_metrics(contexts[player.id], score) for player, score in zip(state.players, player_scores)
        ]
        persona_metrics = self.aggregate_persona_metrics(player_scores)
        review_bonuses = self.bonus_detector.detect(state, player_scores, bad_case_reports, contexts)
        adjusted_scores = self.final_score_calculator.apply(player_scores, review_bonuses)
        mvp_results = self.mvp_selector.select(state, adjusted_scores, review_bonuses)

        # vNext scoring: learned decision quality from PairwiseLogisticRanker
        if self._vnext_scorer is not None:
            vnext_by_player = self._vnext_scorer.score_game(state)
            for score in adjusted_scores:
                vnext_data = vnext_by_player.get(score.player_id, {})
                score.vnext_score = vnext_data.get("vnext_score", 0.5)

        return GameMetrics(
            game_id=state.id,
            winner=state.winner.value if state.winner else None,
            total_days=state.day,
            total_events=len(state.events),
            wolf_elimination_rate=self._wolf_elimination_rate(state),
            village_survival_rate=self._village_survival_rate(state),
            info_efficiency=self._info_efficiency(state),
            role_metrics=role_metrics,
            player_scores=adjusted_scores,
            persona_metrics=persona_metrics,
            metadata={
                "bad_case_reports": bad_case_reports,
                "review_bonuses": review_bonuses,
                "mvp_results": mvp_results,
                "wolf_team_votes": self._wolf_team_votes(state),
                "role_score_formula": (
                    "0.25*camp + 0.25*role_task + 0.20*vote + "
                    "0.10*speech + 0.10*skill + 0.10*survival - mistake_penalty"
                ),
                "final_adjusted_formula": "RuleBasedScore + ImpactBonus + SemanticHighlightBonus - ReviewPenalty",
            },
        )

    def _wolf_team_votes(self, state: GameState) -> list[dict[str, Any]]:
        tallies: list[dict[str, Any]] = []
        for event in state.events:
            if event.type != EventType.PRIVATE_INFO or event.payload.get("kind") != "wolf_attack_tally":
                continue
            votes = dict(event.payload.get("votes", {}))
            tallies.append(
                {
                    "day": event.day,
                    "target_id": event.payload.get("target_id"),
                    "target_name": event.payload.get("target_name"),
                    "votes": votes,
                    "voter_count": len(votes),
                    "unanimous": len(set(votes.values())) == 1 if votes else False,
                }
            )
        return tallies

    def detect_bad_cases(self, state: GameState) -> list[BadCaseReport]:
        contexts = self._build_contexts(state)
        reports: list[BadCaseReport] = []
        checked_good_ids, checked_wolf_ids = self._seer_knowledge(state)

        for player in state.players:
            ctx = contexts[player.id]

            for event in ctx.vote_events:
                target_id = event.payload.get("target_id")
                if not target_id:
                    continue
                target = state.player(target_id)
                if player.alignment == Alignment.WOLF and target.alignment == Alignment.WOLF:
                    reports.append(
                        self._report(
                            state,
                            event.day,
                            player,
                            "vote",
                            f"{player.name} voted wolf teammate {target.name}.",
                            "Avoid same-camp cross voting unless the sacrifice is clearly strategic and profitable.",
                            "major",
                            evidence_event_ids=[event.id],
                        )
                    )
                if player.alignment == Alignment.VILLAGE and target_id in checked_good_ids:
                    reports.append(
                        self._report(
                            state,
                            event.day,
                            player,
                            "vote",
                            f"{player.name} voted a checked-good player {target.name}.",
                            "Respect confirmed good information and reevaluate the read chain before voting.",
                            "major",
                            evidence_event_ids=[event.id],
                        )
                    )

            if player.role == Role.WITCH:
                for event in ctx.night_action_events:
                    if event.payload.get("action_type") != "witch_poison":
                        continue
                    target = self._target_player(state, event)
                    if target is not None and target.alignment == Alignment.VILLAGE:
                        reports.append(
                            self._report(
                                state,
                                event.day,
                                player,
                                "ability",
                                f"{player.name} poisoned villager-side player {target.name}.",
                                "Hold poison until the wolf read is stronger or confirmed by public / private evidence.",
                                "critical",
                                evidence_event_ids=[event.id],
                            )
                        )

            if player.role == Role.SEER:
                wolf_check_events = [
                    event
                    for event in ctx.private_info_events
                    if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")
                ]
                if wolf_check_events:
                    released_targets = self._released_check_targets(ctx)
                    for check_event in wolf_check_events:
                        target_name = str(check_event.payload.get("target_name") or "")
                        if target_name and target_name not in released_targets:
                            reports.append(
                                self._report(
                                    state,
                                    self._first_speech_day(ctx) or 0,
                                    player,
                                    "speech",
                                    f"{player.name} checked wolf {target_name} but did not release the information later.",
                                    "Once you have a wolf result, convert it into public vote pressure in the next day speech.",
                                    "major",
                                    evidence_event_ids=[check_event.id],
                                )
                            )
                            break

                # seer_ignored_confirmed_wolf_vote: Seer checked a wolf but voted elsewhere
                checked_wolf_names = {str(e.payload.get("target_name") or "") for e in wolf_check_events}
                checked_wolf_ids = {str(e.payload.get("target_id") or "") for e in wolf_check_events}
                for vote_event in ctx.vote_events:
                    vote_target_id = str(vote_event.payload.get("target_id") or "")
                    if vote_target_id and vote_target_id not in checked_wolf_ids:
                        vote_target = state.player(vote_target_id) if vote_target_id else None
                        if vote_target is not None and vote_target.alignment == Alignment.VILLAGE:
                            if any(state.player(wid).alive if wid else False for wid in checked_wolf_ids):
                                reports.append(
                                    self._report(
                                        state,
                                        vote_event.day,
                                        player,
                                        "vote",
                                        f"{player.name} knew wolf {', '.join(sorted(checked_wolf_names))} but voted {vote_target.name} instead.",
                                        "When you have a confirmed wolf result, vote to eliminate that wolf. Do not split votes onto unconfirmed targets.",
                                        "major",
                                        evidence_event_ids=([e.id for e in wolf_check_events] + [vote_event.id]),
                                    )
                                )
                                break

            if player.role == Role.HUNTER:
                for event in ctx.hunter_shot_events:
                    target_id = event.payload.get("target_id")
                    if not target_id:
                        continue
                    target = state.player(target_id)
                    if target.alignment == Alignment.VILLAGE:
                        reports.append(
                            self._report(
                                state,
                                event.day,
                                player,
                                "ability",
                                f"{player.name} shot villager-side player {target.name}.",
                                "Hunter shots should convert death into a high-confidence wolf trade, not friendly fire.",
                                "critical",
                                evidence_event_ids=[event.id],
                            )
                        )

            if player.role == Role.GUARD:
                repeated_target, repeat_event_ids = self._repeated_guard_target_with_evidence(state, ctx)
                if repeated_target is not None:
                    reports.append(
                        self._report(
                            state,
                            state.day,
                            player,
                            "ability",
                            f"{player.name} repeated the same guard target {repeated_target.name} on consecutive nights.",
                            "Rotate the guard target or justify the repeat with a strong wolf-read spike instead of auto-piloting the same protection.",
                            "major",
                            evidence_event_ids=repeat_event_ids,
                        )
                    )

            fallback_records = [
                record
                for record in state.decision_records
                if record.player_id == player.id
                and (not record.is_valid or str((record.parsed_action or {}).get("source", "")) == "fallback")
            ]
            fallback_count = len(fallback_records)
            if fallback_count >= 3:
                fallback_event_ids = [
                    str(getattr(record, "event_id", "") or "")
                    for record in fallback_records[:3]
                    if getattr(record, "event_id", "")
                ]
                reports.append(
                    self._report(
                        state,
                        state.day,
                        player,
                        "robustness",
                        f"{player.name} triggered invalid parsing or fallback handling {fallback_count} times during the game.",
                        "Reduce parser failures and fallback overuse so the agent can keep its intended reasoning path online.",
                        "major",
                        evidence_event_ids=fallback_event_ids,
                    )
                )

            # Only wolves leak private night-side info via these tokens.
            # Village roles legitimately discuss "队友"/"狼队" (village team
            # commentary) and Seer publishes check results.
            if player.alignment == Alignment.WOLF:
                risky_speech = next(
                    (
                        event
                        for event in ctx.speech_events
                        if any(token in str(event.payload.get("speech", "")) for token in ["队友", "昨晚刀", "狼队"])
                    ),
                    None,
                )
                if risky_speech is not None:
                    reports.append(
                        self._report(
                            state,
                            risky_speech.day,
                            player,
                            "speech",
                            f"{player.name} mentioned private night-side information in a public speech.",
                            "Public speech should avoid directly exposing private night information, especially teammate or knife details.",
                            "major",
                            evidence_event_ids=[risky_speech.id],
                        )
                    )

            if player.role == Role.VILLAGER:
                consecutive_good_votes, consecutive_vote_event_ids = self._consecutive_votes_on_alignment_with_evidence(
                    state, ctx.vote_events, Alignment.VILLAGE
                )
                if consecutive_good_votes >= 3:
                    reports.append(
                        self._report(
                            state,
                            state.day,
                            player,
                            "vote",
                            f"{player.name} repeatedly voted villager-side players ({consecutive_good_votes} times).",
                            "Break the vote pattern by cross-checking speech, wagon origin, and confirmed information before revoting.",
                            "major",
                            evidence_event_ids=consecutive_vote_event_ids,
                        )
                    )
                elif consecutive_good_votes >= 2:
                    reports.append(
                        self._report(
                            state,
                            state.day,
                            player,
                            "vote",
                            f"{player.name} voted villager-side players in consecutive rounds.",
                            "Reassess why your reads keep landing on villagers and compare your vote path with public flips.",
                            "minor",
                            evidence_event_ids=consecutive_vote_event_ids,
                        )
                    )

        return reports

    def aggregate_persona_metrics(self, player_scores: Sequence[PlayerScore]) -> list[PersonaMetrics]:
        if not player_scores:
            return []

        global_role_avg: dict[str, float] = {}
        scores_by_role: dict[str, list[float]] = defaultdict(list)
        for score in player_scores:
            scores_by_role[score.role].append(score.final_score)
        for role, values in scores_by_role.items():
            global_role_avg[role] = sum(values) / len(values)

        grouped: dict[str, list[PlayerScore]] = defaultdict(list)
        for score in player_scores:
            persona_key = score.persona_id or score.persona_name or score.player_id
            grouped[persona_key].append(score)

        persona_metrics: list[PersonaMetrics] = []
        for persona_key, scores in grouped.items():
            role_bucket: dict[str, list[float]] = defaultdict(list)
            for score in scores:
                role_bucket[score.role].append(score.final_score)

            role_normalized_components = [
                (sum(values) / len(values)) - global_role_avg[role] for role, values in role_bucket.items()
            ]
            best_role = max(role_bucket.items(), key=lambda item: sum(item[1]) / len(item[1]))[0]
            weak_role = min(role_bucket.items(), key=lambda item: sum(item[1]) / len(item[1]))[0]
            wins = sum(1 for score in scores if score.camp_result_score >= 1.0)
            persona_metrics.append(
                PersonaMetrics(
                    persona_id=scores[0].persona_id or persona_key,
                    persona_name=scores[0].persona_name or scores[0].player_name,
                    games_played=len(scores),
                    raw_win_rate=wins / len(scores),
                    avg_final_score=sum(score.final_score for score in scores) / len(scores),
                    role_normalized_score=sum(role_normalized_components) / len(role_normalized_components),
                    avg_vote_score=sum(score.vote_score for score in scores) / len(scores),
                    avg_speech_score=sum(score.speech_score for score in scores) / len(scores),
                    avg_skill_score=sum(score.skill_score for score in scores) / len(scores),
                    critical_mistakes=sum(
                        1 for score in scores for mistake in score.mistakes if mistake.startswith("[critical]")
                    ),
                    best_role=best_role,
                    weak_role=weak_role,
                )
            )
        return sorted(persona_metrics, key=lambda item: item.avg_final_score, reverse=True)

    def _build_contexts(self, state: GameState) -> dict[str, _PlayerContext]:
        contexts = {player.id: _PlayerContext(player=player) for player in state.players}
        for event in state.events:
            payload = event.payload
            if event.type == EventType.VOTE_CAST:
                voter_id = payload.get("voter_id")
                if voter_id in contexts:
                    contexts[voter_id].vote_events.append(event)
            elif event.type == EventType.CHAT_MESSAGE:
                actor_id = payload.get("actor_id")
                if actor_id in contexts:
                    contexts[actor_id].speech_events.append(event)
            elif event.type == EventType.NIGHT_ACTION:
                actor_id = payload.get("actor_id")
                if actor_id in contexts:
                    contexts[actor_id].night_action_events.append(event)
            elif event.type == EventType.PRIVATE_INFO:
                for player_id in event.visible_to:
                    if player_id in contexts:
                        contexts[player_id].private_info_events.append(event)
            elif event.type == EventType.PLAYER_DIED:
                player_id = payload.get("player_id")
                if player_id in contexts:
                    contexts[player_id].death_events.append(event)
            elif event.type == EventType.HUNTER_SHOT:
                hunter_id = payload.get("hunter_id")
                if hunter_id in contexts:
                    contexts[hunter_id].hunter_shot_events.append(event)
        return contexts

    def _build_player_score(
        self,
        state: GameState,
        ctx: _PlayerContext,
        reports: list[BadCaseReport],
    ) -> PlayerScore:
        player = ctx.player
        camp_result_score = 1.0 if state.winner == player.alignment else 0.0
        vote_score = self._vote_score(state, ctx)
        speech_score = self._speech_score(state, ctx)
        skill_score = self._skill_score(state, ctx)
        survival_score = self._survival_score(state, player)
        role_task_score, role_highlights = self._role_task_score(
            state, ctx, vote_score, speech_score, skill_score, survival_score
        )
        mistake_penalty = self._mistake_penalty(reports)

        highlights = list(role_highlights)
        mistakes = [f"[{report.severity}] {report.description}" for report in reports]
        if camp_result_score >= 1.0:
            highlights.append("与本方阵营一同获胜。")
        if survival_score >= 1.0:
            highlights.append("存活至对局结束。")

        # P0: process-oriented scoring — camp_result reduced from 0.25→0.10
        # to prevent wolf/village win outcome from dominating individual
        # decision quality. role_task raised 0.25→0.40 as the primary
        # signal. See docs/B_C_OPERATIONAL_REPORT.md §11.6.
        base_total = (
            0.10 * camp_result_score
            + 0.40 * role_task_score
            + 0.20 * vote_score
            + 0.10 * speech_score
            + 0.10 * skill_score
            + 0.10 * survival_score
            - mistake_penalty
        )
        final_score = round(self._clamp(base_total) * 100, 2)

        # Outcome-independent process score: drop camp_result_score and
        # re-normalize the remaining (0.90 total) back to 1.0.
        process_total = (
            0.40 * role_task_score
            + 0.20 * vote_score
            + 0.10 * speech_score
            + 0.10 * skill_score
            + 0.10 * survival_score
            - mistake_penalty
        ) / 0.90
        process_score = round(self._clamp(process_total) * 100, 2)
        outcome_bonus = round(camp_result_score * 100, 2)

        persona_name = player.name
        role_str = player.role.value

        # Role-normalized score: standardise raw score within the role's
        # baseline distribution so cross-role comparisons are meaningful.
        role_norm_score = self._compute_role_normalized(final_score, role_str)

        # Build evidence refs from bad case report event IDs
        evidence_refs = [
            EvidenceRef(
                phase=report.phase or "",
                actor_id=getattr(report, "actor_id", "") or "",
                event_type=report.mistake_type,
                public_or_private="public",
                visibility_scope="public",
                summary=report.description[:120],
            )
            for report in reports
        ]

        return PlayerScore(
            player_id=player.id,
            player_name=player.name,
            persona_id=persona_name,
            persona_name=persona_name,
            role=role_str,
            alignment=player.alignment.value,
            camp_result_score=round(camp_result_score, 4),
            role_task_score=round(role_task_score, 4),
            vote_score=round(vote_score, 4),
            speech_score=round(speech_score, 4),
            skill_score=round(skill_score, 4),
            survival_score=round(survival_score, 4),
            mistake_penalty=round(mistake_penalty, 4),
            final_score=final_score,
            process_score=process_score,
            outcome_bonus=outcome_bonus,
            highlights=highlights,
            mistakes=mistakes,
            # v2 fields
            raw_score=final_score,
            role_normalized_score=role_norm_score,
            confidence=1.0,
            score_reason=f"Rule-based scoring: camp={camp_result_score} role_task={role_task_score} vote={vote_score} speech={speech_score} skill={skill_score} survival={survival_score}",
            evidence_refs=evidence_refs,
            rule_based=True,
        )

    def _build_role_metrics(self, ctx: _PlayerContext, score: PlayerScore) -> RoleMetrics:
        useful_ability_uses, total_ability_uses, deception_score = self._ability_counts(ctx, score.role)
        death_day = self._death_day(ctx.player, ctx)
        return RoleMetrics(
            role=score.role,
            player_name=score.player_name,
            alive_at_end=ctx.player.alive,
            survival_rounds=death_day if death_day is not None else 0,
            vote_precision=score.vote_score,
            useful_ability_uses=useful_ability_uses,
            total_ability_uses=total_ability_uses,
            deception_score=deception_score,
            mistakes=score.mistakes,
            highlights=score.highlights,
            final_score=score.final_score,
        )

    def _compute_role_normalized(self, raw: float, role: str) -> float:
        """Normalize raw score within role distribution: (raw - mean)/std * 10 + 70.

        If no baseline is available for the role, defaults to a fallback that
        returns the raw score clamped to [0, 100].
        """
        mean = self.ROLE_BASELINE_MEAN.get(role)
        std = self.ROLE_BASELINE_STD.get(role)
        if mean is None or std is None or std <= 0:
            return round(max(0.0, min(100.0, raw)), 2)
        normalized = (raw - mean) / std * 10 + 70
        return round(max(0.0, min(100.0, normalized)), 2)

    def _vote_score(self, state: GameState, ctx: _PlayerContext) -> float:
        if not ctx.vote_events:
            return 0.0
        good_votes = 0.0
        for event in ctx.vote_events:
            target = self._target_player(state, event)
            if target is None:
                continue
            if ctx.player.alignment == Alignment.VILLAGE:
                if target.alignment == Alignment.WOLF:
                    good_votes += 1.0
            else:
                if target.alignment == Alignment.VILLAGE:
                    bonus = 0.2 if self._was_voted_out(state, target.id) else 0.0
                    good_votes += min(1.0, 0.8 + bonus)
        return self._clamp(good_votes / len(ctx.vote_events))

    def _speech_score(self, state: GameState, ctx: _PlayerContext) -> float:
        if not ctx.speech_events:
            return 0.0
        scores: list[float] = []
        all_names = [player.name for player in state.players if player.id != ctx.player.id]
        for event in ctx.speech_events:
            speech = str(event.payload.get("speech", "")).strip()
            if not speech:
                scores.append(0.0)
                continue
            mentioned_names = [name for name in all_names if name in speech]
            score = 0.35
            if mentioned_names:
                score += 0.25
            if any(keyword in speech for keyword in ["狼", "vote", "票", "查杀", "金水", "嫌疑", "归票"]):
                score += 0.2
            if event.payload.get("last_words") or event.payload.get("badge_campaign"):
                score += 0.1
            if self._speech_hit_eliminated_target(state, speech):
                score += 0.1
            scores.append(self._clamp(score))
        return self._clamp(sum(scores) / len(scores))

    def _skill_score(self, state: GameState, ctx: _PlayerContext) -> float:
        role = ctx.player.role
        if role == Role.WEREWOLF:
            return self._wolf_kill_value(state, ctx)
        if role == Role.SEER:
            checks = [e for e in ctx.private_info_events if e.payload.get("kind") == "seer_result"]
            if not checks:
                return 0.0
            wolf_hits = sum(1 for event in checks if event.payload.get("is_wolf"))
            return self._clamp((0.4 * len(checks) / max(state.day, 1)) + (0.6 * wolf_hits / len(checks)))
        if role == Role.WITCH:
            return self._witch_skill_value(state, ctx)
        if role == Role.HUNTER:
            return self._hunter_skill_value(state, ctx)
        if role == Role.GUARD:
            return self._guard_skill_value(state, ctx)
        return 0.5

    def _survival_score(self, state: GameState, player: Player) -> float:
        if player.alive:
            return 1.0
        death_day = next(
            (
                event.day
                for event in state.events
                if event.type == EventType.PLAYER_DIED and event.payload.get("player_id") == player.id
            ),
            state.day,
        )
        return self._clamp(death_day / max(state.day, 1))

    def _role_task_score(
        self,
        state: GameState,
        ctx: _PlayerContext,
        vote_score: float,
        speech_score: float,
        skill_score: float,
        survival_score: float,
    ) -> tuple[float, list[str]]:
        role = ctx.player.role
        highlights: list[str] = []

        if role == Role.WEREWOLF:
            deception = self._wolf_deception_score(ctx, state)
            kill_value = self._wolf_kill_value(state, ctx)
            teammate_votes = self._same_alignment_votes(state, ctx, Alignment.WOLF)
            if vote_score >= 0.8:
                highlights.append("白天有效推动票型落在好人阵营。")
            if kill_value >= 0.75:
                highlights.append("夜间刀口成功落在高价值好人目标。")
            score = 0.35 * deception + 0.25 * survival_score + 0.2 * vote_score + 0.2 * kill_value
            score -= 0.15 if teammate_votes else 0.0
            return self._clamp(score), highlights

        if role == Role.SEER:
            wolf_checks = [
                e
                for e in ctx.private_info_events
                if e.payload.get("kind") == "seer_result" and e.payload.get("is_wolf")
            ]
            total_checks = [e for e in ctx.private_info_events if e.payload.get("kind") == "seer_result"]
            release_score = self._seer_release_score(ctx)
            influence = self._seer_vote_influence(state, ctx)
            check_value = 0.0 if not total_checks else (0.35 + 0.65 * (len(wolf_checks) / len(total_checks)))
            if wolf_checks:
                highlights.append("夜间查验至少命中一名狼人。")
            if release_score >= 0.8:
                highlights.append("及时将查验结果转化为公开发言压力。")
            score = 0.4 * check_value + 0.35 * release_score + 0.25 * influence
            return self._clamp(score), highlights

        if role == Role.WITCH:
            save_value = self._witch_save_value(state, ctx)
            poison_value = self._witch_poison_value(state, ctx)
            # Timing no longer penalises inaction — holding potions for the
            # right moment IS good Witch play. Baseline = 1.0.
            timing = 1.0
            if save_value >= 0.8:
                highlights.append("解药成功保住了好人阵营人数。")
            if poison_value >= 0.8:
                highlights.append("毒药成功命中狼人。")
            score = 0.45 * save_value + 0.45 * poison_value + 0.10 * timing
            return self._clamp(score), highlights

        if role == Role.HUNTER:
            shot_value = self._hunter_skill_value(state, ctx)
            speech_impact = speech_score
            death_trade = 1.0 if ctx.hunter_shot_events else 0.3
            if shot_value >= 0.8:
                highlights.append("猎人开枪完成了对狼换子。")
            score = 0.5 * shot_value + 0.25 * death_trade + 0.25 * speech_impact
            return self._clamp(score), highlights

        if role == Role.GUARD:
            save_value = self._guard_save_value(state, ctx)
            key_protection = self._guard_key_role_protection(state, ctx)
            valid_guarding = self._guard_validity_score(ctx)
            if save_value >= 0.8:
                highlights.append("守卫成功挡下了一次狼刀。")
            if key_protection >= 0.8:
                highlights.append("多次保护到高价值好人角色。")
            score = 0.45 * save_value + 0.35 * key_protection + 0.20 * valid_guarding
            return self._clamp(score), highlights

        logic_consistency = self._villager_logic_consistency(state, ctx)
        suspicion_quality = self._villager_suspicion_quality(state, ctx)
        if vote_score >= 0.8:
            highlights.append("投票持续命中狼人阵营。")
        if suspicion_quality >= 0.8:
            highlights.append("发言能有效建立对狼怀疑。")
        score = 0.4 * vote_score + 0.3 * logic_consistency + 0.3 * suspicion_quality
        return self._clamp(score), highlights

    def _mistake_penalty(self, reports: Sequence[BadCaseReport]) -> float:
        penalty = 0.0
        for report in reports:
            if report.severity == "critical":
                penalty += self.CRITICAL_PENALTY
            elif report.severity == "major":
                penalty += self.MAJOR_PENALTY
            else:
                penalty += self.MINOR_PENALTY
        return min(0.95, penalty)

    def _seer_knowledge(self, state: GameState) -> tuple[set[str], set[str]]:
        checked_good_ids: set[str] = set()
        checked_wolf_ids: set[str] = set()
        for event in state.events:
            if event.type != EventType.PRIVATE_INFO or event.payload.get("kind") != "seer_result":
                continue
            target_id = event.payload.get("target_id")
            if not target_id:
                continue
            if event.payload.get("is_wolf"):
                checked_wolf_ids.add(target_id)
            else:
                checked_good_ids.add(target_id)
        return checked_good_ids, checked_wolf_ids

    def _released_check_targets(self, ctx: _PlayerContext) -> set[str]:
        targets: set[str] = set()
        for event in ctx.speech_events:
            speech = str(event.payload.get("speech", ""))
            for private_event in ctx.private_info_events:
                target_name = str(private_event.payload.get("target_name") or "")
                if target_name and target_name in speech:
                    targets.add(target_name)
        return targets

    def _first_speech_day(self, ctx: _PlayerContext) -> int | None:
        if not ctx.speech_events:
            return None
        return min(event.day for event in ctx.speech_events)

    def _consecutive_votes_on_alignment(
        self,
        state: GameState,
        vote_events: Sequence[GameEvent],
        alignment: Alignment,
    ) -> int:
        best, _ = self._consecutive_votes_on_alignment_with_evidence(state, vote_events, alignment)
        return best

    def _consecutive_votes_on_alignment_with_evidence(
        self,
        state: GameState,
        vote_events: Sequence[GameEvent],
        alignment: Alignment,
    ) -> tuple[int, list[str]]:
        """Same streak count as _consecutive_votes_on_alignment, but also returns
        the event ids that formed the longest matching run so detectors can
        attach evidence_event_ids without re-scanning the events.
        """
        streak = 0
        best = 0
        current_ids: list[str] = []
        best_ids: list[str] = []
        for event in sorted(vote_events, key=lambda item: (item.day, item.ts)):
            target = self._target_player(state, event)
            if target is not None and target.alignment == alignment:
                streak += 1
                current_ids.append(event.id)
                if streak > best:
                    best = streak
                    best_ids = list(current_ids)
            else:
                streak = 0
                current_ids = []
        return best, best_ids

    def _speech_hit_eliminated_target(self, state: GameState, speech: str) -> bool:
        eliminated_names = {
            event.payload.get("player_name") for event in state.events if event.type == EventType.PLAYER_DIED
        }
        return any(name and name in speech for name in eliminated_names)

    def _wolf_kill_value(self, state: GameState, ctx: _PlayerContext) -> float:
        attack_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "attack"]
        if not attack_events:
            return 0.0
        values: list[float] = []
        for event in attack_events:
            target = self._target_player(state, event)
            if target is None:
                continue
            value = 1.0 if target.role.value in self.POWER_ROLES else 0.6
            if self._died_by_reason(state, target.id, "wolf", event.day):
                value += 0.1
            values.append(self._clamp(value))
        return 0.0 if not values else self._clamp(sum(values) / len(values))

    def _wolf_deception_score(self, ctx: _PlayerContext, state: GameState) -> float:
        mentions = 0
        total_other_speeches = 0
        for event in state.events:
            if event.type != EventType.CHAT_MESSAGE:
                continue
            actor_id = event.payload.get("actor_id")
            if actor_id == ctx.player.id:
                continue
            total_other_speeches += 1
            if ctx.player.name in str(event.payload.get("speech", "")):
                mentions += 1
        pressure = 0.0 if total_other_speeches == 0 else mentions / total_other_speeches
        vote_out_penalty = 0.25 if self._was_voted_out(state, ctx.player.id) else 0.0
        return self._clamp(1.0 - pressure - vote_out_penalty)

    def _same_alignment_votes(self, state: GameState, ctx: _PlayerContext, alignment: Alignment) -> int:
        count = 0
        for event in ctx.vote_events:
            target = self._target_player(state, event)
            if target is not None and target.alignment == alignment:
                count += 1
        return count

    def _seer_release_score(self, ctx: _PlayerContext) -> float:
        checks = [event.payload for event in ctx.private_info_events if event.payload.get("kind") == "seer_result"]
        if not checks:
            return 0.0
        released = 0
        for payload in checks:
            target_name = str(payload.get("target_name") or "")
            for speech_event in ctx.speech_events:
                if speech_event.day >= 1 and target_name and target_name in str(speech_event.payload.get("speech", "")):
                    released += 1
                    break
        return self._clamp(released / len(checks))

    def _seer_vote_influence(self, state: GameState, ctx: _PlayerContext) -> float:
        wolf_targets = {
            event.payload.get("target_id")
            for event in ctx.private_info_events
            if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")
        }
        if not wolf_targets:
            return 0.0
        voted_or_exiled = 0
        for target_id in wolf_targets:
            if any(event.payload.get("target_id") == target_id for event in ctx.vote_events):
                voted_or_exiled += 1
                continue
            if self._was_voted_out(state, target_id):
                voted_or_exiled += 1
        return self._clamp(voted_or_exiled / len(wolf_targets))

    def _witch_save_value(self, state: GameState, ctx: _PlayerContext) -> float:
        save_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "witch_save"]
        if not save_events:
            # Time-decay: holding the antidote is wise early, wasteful late.
            # Day 1 = 0.70, Day 2 = 0.55, Day 3+ = max 0.30.
            return max(0.30, 0.70 - 0.15 * (max(state.day, 1) - 1))
        scores: list[float] = []
        for event in save_events:
            target = self._target_player(state, event)
            if target is None:
                continue
            was_wolf_target = self._is_majority_wolf_target(state, target.id, event.day)
            value = 1.0 if was_wolf_target and target.alignment == Alignment.VILLAGE else 0.1
            scores.append(value)
        return self._clamp(sum(scores) / len(scores))

    def _witch_poison_value(self, state: GameState, ctx: _PlayerContext) -> float:
        poison_events = [
            event for event in ctx.night_action_events if event.payload.get("action_type") == "witch_poison"
        ]
        if not poison_events:
            # Same time-decay logic: holding poison early is fine, late is hesitation.
            return max(0.30, 0.70 - 0.15 * (max(state.day, 1) - 1))
        scores: list[float] = []
        for event in poison_events:
            target = self._target_player(state, event)
            if target is None:
                continue
            scores.append(1.0 if target.alignment == Alignment.WOLF else 0.0)
        return self._clamp(sum(scores) / len(scores))

    def _witch_skill_value(self, state: GameState, ctx: _PlayerContext) -> float:
        save_value = self._witch_save_value(state, ctx)
        poison_value = self._witch_poison_value(state, ctx)
        return self._clamp(0.5 * save_value + 0.5 * poison_value)

    def _hunter_skill_value(self, state: GameState, ctx: _PlayerContext) -> float:
        if not ctx.hunter_shot_events:
            return 0.3 if ctx.death_events else 0.5
        values: list[float] = []
        for event in ctx.hunter_shot_events:
            target_id = event.payload.get("target_id")
            if not target_id:
                continue
            target = state.player(target_id)
            values.append(1.0 if target.alignment == Alignment.WOLF else 0.0)
        return self._clamp(sum(values) / len(values)) if values else 0.3

    def _guard_skill_value(self, state: GameState, ctx: _PlayerContext) -> float:
        save_value = self._guard_save_value(state, ctx)
        key_role = self._guard_key_role_protection(state, ctx)
        return self._clamp(0.6 * save_value + 0.4 * key_role)

    def _guard_save_value(self, state: GameState, ctx: _PlayerContext) -> float:
        guard_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "guard"]
        if not guard_events:
            return 0.0
        successes = 0
        for event in guard_events:
            target_id = event.payload.get("target_id")
            if (
                target_id
                and self._is_majority_wolf_target(state, target_id, event.day)
                and not self._died_by_reason(state, target_id, "wolf", event.day)
            ):
                successes += 1
        return self._clamp(successes / len(guard_events))

    def _guard_key_role_protection(self, state: GameState, ctx: _PlayerContext) -> float:
        guard_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "guard"]
        if not guard_events:
            return 0.0
        protected = 0
        for event in guard_events:
            target = self._target_player(state, event)
            # Guard protecting itself is self-preservation, not key-role
            # protection. Only count OTHER power roles (Seer/Witch/Hunter).
            if target is not None and target.id != ctx.player.id and target.role.value in self.POWER_ROLES:
                protected += 1
        return self._clamp(protected / len(guard_events))

    def _guard_validity_score(self, ctx: _PlayerContext) -> float:
        guard_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "guard"]
        if not guard_events:
            return 0.0
        repeated = 0
        last_target: str | None = None
        for event in guard_events:
            target_id = event.payload.get("target_id")
            if target_id and target_id == last_target:
                repeated += 1
            last_target = target_id
        return self._clamp(1.0 - repeated / len(guard_events))

    def _repeated_guard_target(self, state: GameState, ctx: _PlayerContext) -> Player | None:
        target, _ = self._repeated_guard_target_with_evidence(state, ctx)
        return target

    def _repeated_guard_target_with_evidence(
        self, state: GameState, ctx: _PlayerContext
    ) -> tuple[Player | None, list[str]]:
        guard_events = [
            event
            for event in sorted(ctx.night_action_events, key=lambda item: (item.day, item.ts))
            if event.payload.get("action_type") == "guard"
        ]
        last_target_id: str | None = None
        last_event_id: str | None = None
        for event in guard_events:
            target_id = event.payload.get("target_id")
            if target_id and target_id == last_target_id:
                ids = [last_event_id, event.id]
                return state.player(str(target_id)), [eid for eid in ids if eid]
            last_target_id = str(target_id) if target_id else None
            last_event_id = event.id
        return None, []

    def _villager_logic_consistency(self, state: GameState, ctx: _PlayerContext) -> float:
        if not ctx.vote_events:
            return 0.4
        consistent = 0
        for vote_event in ctx.vote_events:
            target = self._target_player(state, vote_event)
            if target is None:
                continue
            target_name = target.name
            prior_speeches = [event for event in ctx.speech_events if event.day <= vote_event.day]
            if any(target_name in str(event.payload.get("speech", "")) for event in prior_speeches):
                consistent += 1
        return self._clamp(consistent / len(ctx.vote_events))

    def _villager_suspicion_quality(self, state: GameState, ctx: _PlayerContext) -> float:
        if not ctx.speech_events:
            return 0.0
        wolves = [player.name for player in state.players if player.alignment == Alignment.WOLF]
        hits = 0
        for event in ctx.speech_events:
            speech = str(event.payload.get("speech", ""))
            if any(name in speech for name in wolves):
                hits += 1
        return self._clamp(hits / len(ctx.speech_events))

    def _ability_counts(self, ctx: _PlayerContext, role: str) -> tuple[int, int, float]:
        if role == Role.WEREWOLF.value:
            total = len([e for e in ctx.night_action_events if e.payload.get("action_type") == "attack"])
            return 0, total, 0.0
        total = len(ctx.night_action_events) + len(ctx.hunter_shot_events)
        useful = len([e for e in ctx.private_info_events if e.payload.get("kind") == "seer_result"])
        deception = 0.0
        return useful, total, deception

    def _reports_by_player(
        self,
        state: GameState,
        reports: Sequence[BadCaseReport],
    ) -> dict[str, list[BadCaseReport]]:
        name_to_id = {player.name: player.id for player in state.players}
        grouped: dict[str, list[BadCaseReport]] = defaultdict(list)
        for report in reports:
            player_id = name_to_id.get(report.player_name)
            if player_id:
                grouped[player_id].append(report)
        return grouped

    def _wolf_elimination_rate(self, state: GameState) -> float:
        wolves = [player for player in state.players if player.role == Role.WEREWOLF]
        if not wolves:
            return 0.0
        return sum(1 for player in wolves if not player.alive) / len(wolves)

    def _village_survival_rate(self, state: GameState) -> float:
        villagers = [player for player in state.players if player.alignment == Alignment.VILLAGE]
        if not villagers:
            return 0.0
        return sum(1 for player in villagers if player.alive) / len(villagers)

    def _info_efficiency(self, state: GameState) -> float:
        useful_types = {EventType.PRIVATE_INFO, EventType.CHAT_MESSAGE, EventType.VOTE_CAST, EventType.NIGHT_ACTION}
        useful_events = sum(1 for event in state.events if event.type in useful_types)
        return useful_events / max(len(state.events), 1)

    def _report(
        self,
        state: GameState,
        day: int,
        player: Player,
        mistake_type: str,
        description: str,
        suggested_fix: str,
        severity: str,
        evidence_event_ids: list[str] | None = None,
        phase: str = "",
        actor_id: str = "",
    ) -> BadCaseReport:
        uid = f"{state.id}-{player.id}-{mistake_type}-{day}"
        role_str = player.role.value
        impact_map = {"critical": 0.9, "major": 0.6, "minor": 0.3}
        return BadCaseReport(
            game_id=state.id,
            day=day,
            player_name=player.name,
            role=role_str,
            mistake_type=mistake_type,
            description=description,
            suggested_fix=suggested_fix,
            severity=severity,
            evidence_event_ids=list(evidence_event_ids or []),
            # v2 structured fields
            id=uid,
            bad_case_type=mistake_type,
            phase=phase
            or (
                "DAY_VOTE"
                if mistake_type == "vote"
                else "NIGHT_ACTION"
                if mistake_type in ("ability", "night")
                else "DAY_SPEECH"
            ),
            actor_id=actor_id or player.id,
            trigger_condition=description[:120],
            observed_action=description[:200],
            expected_better_action=suggested_fix[:200],
            impact_estimate=impact_map.get(severity, 0.5),
            confidence=0.8,
            evidence_refs=[
                EvidenceRef(
                    phase=phase or "NIGHT_ACTION",
                    actor_id=player.id,
                    event_type=mistake_type,
                    public_or_private="public",
                    visibility_scope="public",
                    summary=description[:120],
                )
            ],
            visibility_scope="public",
            safety_flags=SafetyFlags(safe_for_track_c_learning=True),
            safe_for_track_c_learning=True,
        )

    def _target_player(self, state: GameState, event: GameEvent) -> Player | None:
        target_id = event.payload.get("target_id")
        if not target_id:
            target = event.payload.get("target")
            if isinstance(target, dict):
                target_id = target.get("id")
        if not target_id:
            return None
        return state.player(str(target_id))

    def _was_voted_out(self, state: GameState, player_id: str) -> bool:
        return any(
            event.type == EventType.PLAYER_DIED
            and event.payload.get("player_id") == player_id
            and event.payload.get("reason") == "vote"
            for event in state.events
        )

    def _died_by_reason(self, state: GameState, player_id: str, reason: str, day: int | None = None) -> bool:
        return any(
            event.type == EventType.PLAYER_DIED
            and event.payload.get("player_id") == player_id
            and event.payload.get("reason") == reason
            and (day is None or event.day == day)
            for event in state.events
        )

    def _death_day(self, player: Player, ctx: _PlayerContext) -> int | None:
        if not ctx.death_events:
            return None
        return min(event.day for event in ctx.death_events)

    def _is_majority_wolf_target(self, state: GameState, target_id: str, day: int) -> bool:
        attack_events = [
            event
            for event in state.events
            if event.type == EventType.NIGHT_ACTION
            and event.day == day
            and event.payload.get("action_type") == "attack"
        ]
        if not attack_events:
            return False
        counts: dict[str, int] = defaultdict(int)
        for event in attack_events:
            voted_target = event.payload.get("target_id")
            if voted_target:
                counts[str(voted_target)] += 1
        if not counts:
            return False
        best_count = max(counts.values())
        winners = sorted(pid for pid, count in counts.items() if count == best_count)
        return bool(winners and winners[0] == target_id)

    def _clamp(self, value: float, lower: float = 0.0, upper: float = 1.0) -> float:
        return max(lower, min(upper, value))


# ---------------------------------------------------------------------------
# Structured review report
# ---------------------------------------------------------------------------


class ReviewReportBuilder:
    """Builds a structured replay report from existing metrics output."""

    def __init__(self, counterfactual_analyzer: CounterfactualAnalyzer | None = None) -> None:
        self.counterfactual_analyzer = counterfactual_analyzer or CounterfactualAnalyzer()

    def build(self, state: GameState, metrics: GameMetrics) -> ReviewReport:
        bonuses = list(metrics.metadata.get("review_bonuses", []))
        mvp_results = list(metrics.metadata.get("mvp_results", []))
        bad_cases = list(metrics.metadata.get("bad_case_reports", []))

        score_map = {score.player_id: score for score in metrics.player_scores}
        ranked_scores = sorted(
            metrics.player_scores,
            key=lambda score: (
                score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
                score.final_score,
            ),
            reverse=True,
        )
        scoreboard = [
            {
                "rank": index,
                "player_id": score.player_id,
                "player_name": score.player_name,
                "persona_id": score.persona_id,
                "persona_name": score.persona_name,
                "role": score.role,
                "alignment": score.alignment,
                "rule_score": score.final_score,
                "adjusted_final_score": score.adjusted_final_score
                if score.adjusted_final_score is not None
                else score.final_score,
                "impact_bonus": score.impact_bonus,
                "semantic_highlight_bonus": score.semantic_highlight_bonus,
                "review_penalty": score.review_penalty,
            }
            for index, score in enumerate(ranked_scores, start=1)
        ]

        turning_points = self._build_turning_points(bonuses, bad_cases, score_map, state=state)
        counterfactuals = self.counterfactual_analyzer.analyze(
            state,
            metrics,
            bad_cases=bad_cases,
            turning_points=turning_points,
            review_bonuses=bonuses,
        )
        strategy_suggestions = self._build_strategy_suggestions(
            metrics.player_scores, bad_cases, bonuses, counterfactuals, turning_points, state=state
        )
        player_reviews = self._build_player_reviews(ranked_scores, bonuses, bad_cases, counterfactuals)
        game_summary = self._build_game_summary(metrics, turning_points, mvp_results)

        # Build v2 structured fields
        bonuses_dicts = [_bonus_to_dict(b) for b in bonuses]
        safety_flags = self._scan_safety(state, bad_cases, counterfactuals, strategy_suggestions, bonuses)
        evolution_candidates = self._generate_evolution_candidates(
            state, bad_cases, counterfactuals, strategy_suggestions, bonuses
        )
        judge_panel: dict[str, Any] = {
            "judge_scores": [],
            "agreement_score": 1.0,
            "disagreement_reasons": [],
            "critic_resolution": "rule_based",
            "final_confidence": 1.0,
        }
        calibration_info: dict[str, Any] = {
            "score_version": "v2",
            "calibration_method": "role_normalization_zscore",
            "role_normalization": True,
            "fallback_used": metrics.metadata.get("fallback_used", False),
            "role_baseline_mean": MetricsCalculator.ROLE_BASELINE_MEAN,
            "role_baseline_std": MetricsCalculator.ROLE_BASELINE_STD,
        }

        return ReviewReport(
            game_id=metrics.game_id,
            winner=metrics.winner,
            total_days=metrics.total_days,
            total_events=metrics.total_events,
            game_summary=game_summary,
            rule_variant="standard_competition_v1",
            scoreboard=scoreboard,
            mvp_results=mvp_results,
            turning_points=turning_points,
            player_reviews=player_reviews,
            bad_cases=bad_cases,
            counterfactuals=counterfactuals,
            strategy_suggestions=strategy_suggestions,
            bonuses=bonuses_dicts,
            evolution_candidates=evolution_candidates,
            judge_panel=judge_panel,
            calibration_info=calibration_info,
            safety_flags=safety_flags,
            metadata={
                "winner_reasoning": game_summary,
                "score_formula": metrics.metadata.get("role_score_formula"),
                "adjusted_formula": metrics.metadata.get("final_adjusted_formula"),
                "leaderboard_available": True,
                "leaderboard_note": "跨局表现请查看 Leaderboard 输出；跨局 Leaderboard 由 LeaderboardAggregator 单独生成，本报告仅针对当前单局。",
                "player_scores": [asdict(score) for score in metrics.player_scores],
                "wolf_team_votes": metrics.metadata.get("wolf_team_votes", []),
                "source_metadata": dict(metrics.metadata),
            },
        )

    def _build_player_reviews(
        self,
        ranked_scores: Sequence[PlayerScore],
        bonuses: Sequence[ReviewBonus],
        bad_cases: Sequence[BadCaseReport],
        counterfactuals: Sequence[CounterfactualCase],
    ) -> list[PlayerReview]:
        name_to_bad_cases: dict[str, list[BadCaseReport]] = defaultdict(list)
        for report in bad_cases:
            name_to_bad_cases[report.player_name].append(report)

        bonuses_by_player: dict[str, list[ReviewBonus]] = defaultdict(list)
        for bonus in bonuses:
            bonuses_by_player[bonus.player_id].append(bonus)

        counterfactuals_by_player: dict[str, list[CounterfactualCase]] = defaultdict(list)
        for item in counterfactuals:
            # Only associate counterfactuals with the decision maker (first
            # affected player), not all affected players.  This prevents
            # attaching "X should consider: If Y had held the shot…" to
            # player Y who cannot control X's actions.
            if item.affected_players:
                counterfactuals_by_player[item.affected_players[0]].append(item)

        reviews: list[PlayerReview] = []
        for rank, score in enumerate(ranked_scores, start=1):
            player_bonuses = bonuses_by_player.get(score.player_id, [])
            impact_highlights = [
                self._zh_text(bonus.reason)
                for bonus in player_bonuses
                if bonus.category in {"impact", "semantic"} and bonus.score_delta > 0
            ]
            penalty_notes = [
                self._zh_text(bonus.reason)
                for bonus in player_bonuses
                if bonus.category == "penalty" and bonus.score_delta < 0
            ]
            reports = name_to_bad_cases.get(score.player_name, [])
            player_counterfactuals = counterfactuals_by_player.get(score.player_name, [])
            mistakes = list(
                dict.fromkeys(
                    [self._zh_text(item) for item in score.mistakes]
                    + [self._zh_text(report.description) for report in reports]
                )
            )
            weaknesses = list(
                dict.fromkeys(penalty_notes + [self._zh_text(report.suggested_fix) for report in reports])
            )
            highlights = list(dict.fromkeys([self._zh_text(item) for item in score.highlights] + impact_highlights))
            suggestions = self._player_suggestions(score, reports, player_bonuses, player_counterfactuals)

            reviews.append(
                PlayerReview(
                    player_id=score.player_id,
                    player_name=score.player_name,
                    role=score.role,
                    alignment=score.alignment,
                    rule_score=score.final_score,
                    adjusted_final_score=score.adjusted_final_score
                    if score.adjusted_final_score is not None
                    else score.final_score,
                    process_score=score.process_score,
                    outcome_bonus=score.outcome_bonus,
                    rank=rank,
                    strengths=self._player_strengths(score, player_bonuses),
                    weaknesses=weaknesses,
                    mistakes=mistakes,
                    highlights=highlights,
                    suggestions=suggestions,
                    speech_summary=self._speech_summary(score),
                    overall_summary=self._player_overall_summary(score, reports, player_bonuses),
                    rule_score_reasons=self._rule_score_reasons(score),
                    adjustment_reasons=self._adjustment_reasons(player_bonuses, score),
                    score_summary=self._score_summary(score, player_bonuses),
                )
            )
        return reviews

    def _build_turning_points(
        self,
        bonuses: Sequence[ReviewBonus],
        bad_cases: Sequence[BadCaseReport],
        score_map: dict[str, PlayerScore],
        *,
        state: GameState | None = None,
    ) -> list[TurningPoint]:
        turning_points: list[TurningPoint] = []
        for bonus in bonuses:
            if bonus.score_delta <= 0 or not bonus.evidence:
                continue
            if bonus.category == "semantic" and bonus.score_delta < 1.0:
                continue
            if bonus.category not in {"impact", "semantic"}:
                continue
            score = score_map.get(bonus.player_id)
            related = [score.player_name] if score is not None else [bonus.player_id]
            bonus_event_ids = self._actor_event_ids(state, bonus.player_id, bonus.day) if state else []
            turning_points.append(
                TurningPoint(
                    day=bonus.day,
                    phase=bonus.phase,
                    title=self._bonus_title(bonus),
                    description=bonus.reason,
                    impact=round(min(abs(bonus.score_delta), 5.0), 2),
                    related_players=related,
                    evidence=list(bonus.evidence),
                    evidence_event_ids=bonus_event_ids,
                )
            )
        for report in bad_cases:
            if report.severity != "critical":
                continue
            turning_points.append(
                TurningPoint(
                    day=report.day,
                    phase=None,
                    title=f"{report.player_name} 的致命失误",
                    description=report.description,
                    impact=4.0,
                    related_players=[report.player_name],
                    evidence=[report.suggested_fix],
                    evidence_event_ids=list(report.evidence_event_ids),
                )
            )
        unique: dict[tuple[Any, ...], TurningPoint] = {}
        for point in turning_points:
            key = (point.day, point.phase, point.title, point.description)
            if key not in unique or point.impact > unique[key].impact:
                unique[key] = point
        return sorted(unique.values(), key=lambda point: ((point.day or 0), point.impact), reverse=True)

    def _actor_event_ids(
        self,
        state: GameState | None,
        player_id: str,
        day: int | None,
        *,
        limit: int = 4,
    ) -> list[str]:
        """Look up the most recent event ids actor `player_id` produced on `day`.

        Used by turning-point / suggestion builders that only know "who and when"
        but need a concrete event chain so the resulting StrategyKnowledgeDoc
        has a non-empty source_event_ids when DreamJob picks it up.
        """
        if state is None or not player_id:
            return []
        ids: list[str] = []
        for event in state.events:
            actor_id = event.payload.get("actor_id") or event.payload.get("voter_id") or event.payload.get("player_id")
            if actor_id != player_id:
                continue
            if day is not None and event.day != day:
                continue
            ids.append(event.id)
        if not ids and day is not None:
            # Fall back to actor's events regardless of day so we still surface evidence.
            for event in state.events:
                actor_id = (
                    event.payload.get("actor_id") or event.payload.get("voter_id") or event.payload.get("player_id")
                )
                if actor_id == player_id:
                    ids.append(event.id)
        return ids[-limit:]

    def _build_strategy_suggestions(
        self,
        player_scores: Sequence[PlayerScore],
        bad_cases: Sequence[BadCaseReport],
        bonuses: Sequence[ReviewBonus],
        counterfactuals: Sequence[CounterfactualCase],
        turning_points: Sequence[TurningPoint],
        *,
        state: GameState | None = None,
    ) -> list[StrategySuggestion]:
        suggestions: list[StrategySuggestion] = []
        reports_by_player: dict[str, list[BadCaseReport]] = defaultdict(list)
        counterfactuals_by_player: dict[str, list[CounterfactualCase]] = defaultdict(list)
        score_by_id = {score.player_id: score for score in player_scores}
        name_to_player_id = {player.name: player.id for player in state.players} if state else {}
        for report in bad_cases:
            reports_by_player[report.player_name].append(report)
            suggestions.append(
                StrategySuggestion(
                    target_type="player",
                    target=report.player_name,
                    suggestion_type="report_suggestion",
                    suggestion=self._game_specific_suggestion(report),
                    source=self._zh_text(report.description),
                    priority=report.severity,
                    metadata={
                        "scope": "game_specific",
                        "safe_for_agent": False,
                        "source_type": "bad_case",
                        "evidence_summary": self._zh_text(report.description),
                    },
                    evidence_event_ids=list(report.evidence_event_ids),
                )
            )
            if report.severity in {"critical", "major"}:
                suggestions.append(
                    StrategySuggestion(
                        target_type="role",
                        target=report.role,
                        suggestion_type="reusable_strategy_suggestion",
                        suggestion=self._zh_text(report.suggested_fix),
                        source=self._zh_text(report.description),
                        priority=report.severity,
                        metadata={
                            "scope": "reusable",
                            "safe_for_agent": True,
                            "source_type": "bad_case",
                            "evidence_summary": self._zh_text(report.description),
                        },
                        evidence_event_ids=list(report.evidence_event_ids),
                    )
                )
        for item in counterfactuals:
            for name in item.affected_players:
                counterfactuals_by_player[name].append(item)
            if item.confidence >= 0.8 and item.counterfactual_type in {"skill", "info_release"}:
                target_role = self._infer_role_from_counterfactual(item)
                if target_role:
                    suggestions.append(
                        StrategySuggestion(
                            target_type="role",
                            target=target_role,
                            suggestion_type="reusable_strategy_suggestion",
                            suggestion=self._reusable_counterfactual_suggestion(item, target_role),
                            source=self._zh_text(item.expected_effect),
                            priority="high" if item.confidence >= 0.9 else "major",
                            metadata={
                                "scope": "reusable",
                                "safe_for_agent": True,
                                "source_type": "counterfactual",
                                "evidence_summary": self._zh_text(item.expected_effect),
                            },
                            evidence_event_ids=list(item.evidence_event_ids),
                        )
                    )

        for bonus in bonuses:
            if bonus.category != "impact" or bonus.score_delta <= 0 or not bonus.evidence:
                continue
            score = score_by_id.get(bonus.player_id)
            if score is None or bonus.bonus_type not in {
                "seer_info_conversion",
                "seer_good_clear_guidance",
                "key_role_save",
                "guard_block_kill",
                "guard_key_role_cover",
                "final_wolf_shot",
                "wolf_power_role_push",
                "villager_vote_chain",
            }:
                continue
            bonus_event_ids = self._actor_event_ids(state, bonus.player_id, bonus.day)
            suggestions.append(
                StrategySuggestion(
                    target_type="role",
                    target=score.role,
                    suggestion_type="reusable_strategy_suggestion",
                    suggestion=self._reusable_bonus_suggestion(score.role, bonus),
                    source=self._zh_text(bonus.reason),
                    priority="major",
                    metadata={
                        "scope": "reusable",
                        "safe_for_agent": True,
                        "source_type": "review_bonus",
                        "evidence_summary": "；".join(self._zh_text(item) for item in bonus.evidence[:2]),
                    },
                    evidence_event_ids=bonus_event_ids,
                )
            )

        for score in player_scores:
            cf_items = counterfactuals_by_player.get(score.player_name, [])
            if cf_items and not reports_by_player.get(score.player_name):
                cf_first = cf_items[0]
                player_id_for_cf = name_to_player_id.get(score.player_name)
                cf_event_ids = list(cf_first.evidence_event_ids)
                if not cf_event_ids and player_id_for_cf:
                    cf_event_ids = self._actor_event_ids(state, player_id_for_cf, cf_first.day)
                suggestions.append(
                    StrategySuggestion(
                        target_type="player",
                        target=score.player_name,
                        suggestion_type="report_suggestion",
                        suggestion=self._game_specific_counterfactual_suggestion(score, cf_first),
                        source=self._zh_text(cf_first.expected_effect),
                        priority="high" if cf_first.confidence >= 0.75 else "medium",
                        metadata={
                            "scope": "game_specific",
                            "safe_for_agent": False,
                            "source_type": "counterfactual",
                            "evidence_summary": self._zh_text(cf_first.expected_effect),
                        },
                        evidence_event_ids=cf_event_ids,
                    )
                )

        deduped: dict[tuple[str, str, str, str], StrategySuggestion] = {}
        for item in suggestions:
            key = (item.target_type, item.target, item.suggestion_type, item.suggestion)
            deduped.setdefault(key, item)
        return list(deduped.values())

    def _build_game_summary(
        self,
        metrics: GameMetrics,
        turning_points: Sequence[TurningPoint],
        mvp_results: Sequence[MVPResult],
    ) -> str:
        winner_text = self._alignment_label(metrics.winner or "unknown")
        if not turning_points:
            return f"{winner_text}在 {metrics.total_days} 天、{metrics.total_events} 个事件后获胜，当前未检测到显著的复盘层转折点。"
        top_point = max(turning_points, key=lambda item: item.impact)
        mvp = next((item for item in mvp_results if item.mvp_type == "winning_camp_mvp"), None)
        mvp_text = f" 胜方 MVP 为 {mvp.player_name}。" if mvp else ""
        return (
            f"{winner_text}在 {metrics.total_days} 天、{metrics.total_events} 个事件后获胜。"
            f"本局最大转折点出现在第 {top_point.day} 天的“{top_point.title}”。{mvp_text}"
        )

    def _player_strengths(self, score: PlayerScore, bonuses: Sequence[ReviewBonus]) -> list[str]:
        strengths: list[str] = []
        if score.role_task_score >= 0.7:
            strengths.append(f"较稳定地完成了 {score.role} 的核心职责。")
        if score.vote_score >= 0.7:
            strengths.append("投票决策大体符合本阵营目标。")
        if score.skill_score >= 0.7:
            strengths.append("技能使用转化成了明确的局面价值。")
        strengths.extend(
            bonus.reason for bonus in bonuses if bonus.score_delta > 0 and bonus.category in {"impact", "semantic"}
        )
        return list(dict.fromkeys(strengths))

    def _player_suggestions(
        self,
        score: PlayerScore,
        reports: Sequence[BadCaseReport],
        bonuses: Sequence[ReviewBonus],
        counterfactuals: Sequence[CounterfactualCase],
    ) -> list[str]:
        suggestions: list[str] = []

        for report in reports:
            suggestion = self._game_specific_suggestion(report)
            if suggestion:
                suggestions.append(suggestion)

        for case in counterfactuals:
            suggestion = self._game_specific_counterfactual_suggestion(score, case)
            if suggestion:
                suggestions.append(suggestion)
        deduped = list(dict.fromkeys(self._zh_text(item) for item in suggestions if item))
        return deduped[:2]

    def _speech_summary(self, score: PlayerScore) -> str:
        if score.speech_score >= 0.75:
            return "发言质量较高，能形成明确压力并推动公共决策。"
        if score.speech_score >= 0.45:
            return "发言有一定信息量，但转化为票型和共识的能力一般。"
        return "发言影响有限，缺少稳定的信息释放或归票转化。"

    def _rule_score_reasons(self, score: PlayerScore) -> list[str]:
        reasons = [
            f"阵营结果：{'本局获胜' if score.camp_result_score >= 1.0 else '本局失利'}。",
            f"角色任务：衡量{self._role_label(score.role)}的职责完成度。",
            "投票：反映投票命中率与票型贡献。",
            "发言：反映公开发言的信息量与转化能力。",
            "技能：反映技能使用价值或夜间行动质量。",
            "生存：反映存活时长与残局存在感。",
        ]
        if score.mistake_penalty > 0:
            reasons.append("失误扣分：来自关键错误、误毒、误票等硬规则惩罚。")
        return reasons

    def _adjustment_reasons(self, bonuses: Sequence[ReviewBonus], score: PlayerScore) -> list[str]:
        reasons: list[str] = []
        for bonus in bonuses:
            if bonus.score_delta > 0 and bonus.category == "impact":
                reasons.append(f"局势影响加分 +{min(bonus.score_delta, 5.0):.2f}：{self._zh_text(bonus.reason)}")
            elif bonus.score_delta > 0 and bonus.category == "semantic":
                reasons.append(f"语义高光加分 +{min(bonus.score_delta, 5.0):.2f}：{self._zh_text(bonus.reason)}")
            elif bonus.score_delta < 0 and bonus.category == "penalty":
                reasons.append(f"复盘额外扣分 {max(bonus.score_delta, -5.0):.2f}：{self._zh_text(bonus.reason)}")
        if not reasons:
            reasons.append("本局没有额外的复盘加分或扣分。")
        return reasons

    def _score_summary(self, score: PlayerScore, bonuses: Sequence[ReviewBonus]) -> str:
        adjusted = score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score
        if adjusted > score.final_score:
            delta = adjusted - score.final_score
            return f"硬规则基础分为 {score.final_score:.2f}，复盘层净加分 {delta:.2f}，最终调整后为 {adjusted:.2f}。"
        if adjusted < score.final_score:
            delta = score.final_score - adjusted
            return f"硬规则基础分为 {score.final_score:.2f}，复盘层净扣分 {delta:.2f}，最终调整后为 {adjusted:.2f}。"
        if bonuses:
            return f"硬规则基础分为 {score.final_score:.2f}，额外加分与扣分相互抵消，最终仍为 {adjusted:.2f}。"
        return f"本局仅采用硬规则得分，最终分数为 {adjusted:.2f}。"

    def _player_overall_summary(
        self,
        score: PlayerScore,
        reports: Sequence[BadCaseReport],
        bonuses: Sequence[ReviewBonus],
    ) -> str:
        role = self._role_label(score.role)
        alignment = self._alignment_label(score.alignment)
        if reports:
            main_issue = self._zh_text(reports[0].description)
            return f"作为{role}，{score.player_name}本局整体表现有明显波动，最终为{alignment}贡献有限，主要问题集中在：{main_issue}"
        if score.adjusted_final_score is not None and score.adjusted_final_score >= 75:
            main_bonus = next((self._zh_text(bonus.reason) for bonus in bonuses if bonus.score_delta > 0), "")
            if main_bonus:
                return f"作为{role}，{score.player_name}本局整体发挥稳健，既完成了基础职责，也在关键节点打出了额外价值，最突出的表现是：{main_bonus}"
            return f"作为{role}，{score.player_name}本局整体发挥稳健，核心职责完成度较高，并且对{alignment}形成了持续正贡献。"
        if score.final_score >= 55:
            return f"作为{role}，{score.player_name}本局完成了部分关键职责，但在投票、发言或节奏转化上仍有可优化空间。"
        return f"作为{role}，{score.player_name}本局整体表现偏弱，关键节点上的信息处理和行动转化都不够理想。"

    def _infer_role_from_counterfactual(self, item: CounterfactualCase) -> str | None:
        text = f"{item.original_decision} {item.alternative_decision}".lower()
        if "witch" in text or "女巫" in text:
            return Role.WITCH.value
        if "hunter" in text or "猎人" in text:
            return Role.HUNTER.value
        if "seer" in text or "预言家" in text:
            return Role.SEER.value
        return None

    def _reusable_counterfactual_suggestion(self, item: CounterfactualCase, role: str) -> str:
        role_label = self._role_label(role)
        if item.counterfactual_type == "info_release":
            return f"{role_label}在拿到高价值信息后，应尽快把结论转化为公开归票压力，而不是只停留在个人判断。"
        if role == Role.WITCH.value:
            return "女巫在狼面不够集中时应谨慎交毒，优先等待更高置信度证据，再决定是否用药。"
        if role == Role.HUNTER.value:
            return "猎人开枪前应再次核对目标的狼面与公开信息，尽量把死亡收益转化为稳定换狼，而不是误伤好人。"
        return f"{role_label}在关键回合应优先选择能稳定改善局面的行动，避免把低置信判断直接变成不可逆损失。"

    def _reusable_bonus_suggestion(self, role: str, bonus: ReviewBonus) -> str:
        if bonus.bonus_type == "seer_info_conversion":
            return "预言家查到狼人后，应尽快把查验结果、狼坑判断和归票目标在同一轮发言中说完整。"
        if bonus.bonus_type == "seer_good_clear_guidance":
            return "预言家报金水时不要只报结果，还要明确这个好人位接下来为什么值得被信任。"
        if bonus.bonus_type == "key_role_save":
            return (
                "女巫在关键轮次应优先评估神职存活价值，能保住后续还能继续产出信息或保护收益的角色时，救人优先级更高。"
            )
        if bonus.bonus_type == "guard_block_kill":
            return "守卫一旦判断出高概率刀口，应优先保住会继续产出信息或节奏价值的目标，把夜间守护直接变成白天优势。"
        if bonus.bonus_type == "guard_key_role_cover":
            return "守卫在前中期应尽量让守护资源覆盖高价值神职，避免信息链在夜里过早断掉。"
        if bonus.bonus_type == "final_wolf_shot":
            return "猎人临死前应优先瞄准能够直接锁定胜负的高狼面目标，把开枪收益最大化。"
        if bonus.bonus_type == "wolf_power_role_push":
            return "狼人白天推进关键神职出局时，最好让发言逻辑、票型方向和队友配合保持一致，避免推进成功后立刻暴露自己的狼面。"
        if bonus.bonus_type == "villager_vote_chain":
            return "村民在多轮中持续命中狼人时，应把自己的票型理由讲得更完整，帮助全桌更快形成稳定共识。"
        return f"{self._role_label(role)}在关键轮次应主动把优势行为沉淀为可复用节奏。"

    def _covered_dimensions(self, bonus_types: set[str]) -> set[str]:
        mapping = {
            "seer_info_conversion": "speech",
            "seer_good_clear_guidance": "speech",
            "decisive_vote": "vote",
            "last_wolf_poison": "skill",
            "key_role_save": "skill",
            "guard_block_kill": "skill",
            "guard_key_role_cover": "skill",
            "final_wolf_shot": "skill",
            "wolf_power_role_push": "speech",
            "villager_vote_chain": "vote",
        }
        return {mapping[item] for item in bonus_types if item in mapping}

    def _game_specific_suggestion(self, report: BadCaseReport) -> str:
        role = self._role_label(report.role)
        issue = self._zh_text(report.description)
        fix = self._zh_text(report.suggested_fix)
        return f"这局中，{report.player_name}作为{role}在第 {report.day} 天出现了“{issue}”的问题。下一局应优先改进这一点：{fix}"

    def _game_specific_counterfactual_suggestion(self, score: PlayerScore, item: CounterfactualCase) -> str:
        return f"结合本局复盘，如果再次遇到类似局面，{score.player_name}应优先考虑：{self._zh_text(item.alternative_decision)}"

    def _reusable_role_suggestion(self, role: str, dimension: str) -> str:
        role_label = self._role_label(role)
        if dimension == "vote":
            return f"{role_label}在接近票型或信息不充分时，不要盲目跟票，应先核对公开发言、查验链和票型来源。"
        if dimension == "speech":
            return f"{role_label}在白天发言阶段应更明确地表达判断依据，并尽量把信息转化为清晰的归票方向。"
        return f"{role_label}的成功打法应沉淀为可复用节奏：在关键轮次尽快识别高价值信息，并主动推动局面转化。"

    def _role_label(self, role: str) -> str:
        return ROLE_LABELS.get(role, role)

    def _alignment_label(self, alignment: str) -> str:
        return ALIGNMENT_LABELS.get(alignment, alignment)

    def _phase_label(self, phase: str | None) -> str:
        if not phase:
            return ""
        return PHASE_LABELS.get(phase, phase)

    def _severity_label(self, severity: str) -> str:
        return SEVERITY_LABELS.get(severity, severity)

    def _zh_text(self, text: str) -> str:
        replacements = {
            "Decisive villager vote flipped the wagon onto an enemy target.": "关键一票将放逐目标成功转向敌对阵营。",
            "Decisive enemy vote directly changed the elimination outcome.": "关键投票直接改变了当轮的放逐结果。",
            "Seer converted a wolf check into public pressure that changed the vote path.": "预言家将查杀信息成功转化为公共压力，并改变了票型走向。",
            "Witch poison removed the final wolf and ended the threat immediately.": "女巫毒掉最后一狼，直接终结了狼队威胁。",
            "Witch save preserved a key role that later generated meaningful value.": "女巫成功救下关键角色，并保留了后续价值。",
            "Hunter shot removed the final wolf and swung the game shut.": "猎人开枪带走最后一狼，直接锁定胜势。",
            "Wolf pressure helped remove a real key villager-side role during the day.": "狼人通过白天发言和投票成功推动关键好人角色出局。",
            "Respect confirmed good information and reevaluate the read chain before voting.": "尊重已公开的确认信息，投票前应重新核对查验链和票型证据。",
            "Reassess why your reads keep landing on villagers and compare your vote path with public flips.": "复盘自己的判断为什么连续落在好人身上，并结合公开票型重新校准怀疑对象。",
            "Break the vote pattern by cross-checking speech, wagon origin, and confirmed information before revoting.": "连续投错时应暂停跟票，重新核对白天发言、票型发起人和已确认信息。",
            "Hold poison until the wolf read is stronger or confirmed by public / private evidence.": "毒药应保留到狼面更高或证据更充分时再使用。",
            "Once you have a wolf result, convert it into public vote pressure in the next day speech.": "一旦查到狼人，应在下一轮白天发言中尽快把查杀转化为公共归票压力。",
            "Hunter shots should convert death into a high-confidence wolf trade, not friendly fire.": "猎人开枪应尽量完成高置信度换狼，避免误伤好人。",
            "Avoid same-camp cross voting unless the sacrifice is clearly strategic and profitable.": "除非能形成明确收益，否则不要做无意义的队友互投。",
            "Replay layer penalizes missing a high-value public conversion window after a wolf check.": "复盘层惩罚预言家在查杀狼人后错失高价值的公开转化窗口。",
            "Replay penalizes repeatedly driving pressure onto a key villager-side target.": "复盘层惩罚反复将压力推向好人阵营关键角色。",
            "Public speech should avoid directly exposing private night information, especially teammate or knife details.": "公开发言应避免直接泄露夜间私密信息，尤其是队友与刀口细节。",
            "Reduce parser failures and fallback overuse so the agent can keep its intended reasoning path online.": "应减少解析失败和 fallback 过度使用，尽量保持原始决策链稳定在线。",
            "Rotate the guard target or justify the repeat with a strong wolf-read spike instead of auto-piloting the same protection.": "不要机械地连续守同一目标，除非你有足够强的狼刀判断依据。",
        }
        result = replacements.get(text, text)
        # Regex replacements run FIRST on the original English text,
        # before role_tokens substitution partial-translates the string.
        regex_replacements = [
            (
                r"^(?P<actor>.+?) voted a checked-good player (?P<target>.+?)\.?$",
                r"\g<actor>投票给已被确认偏好人的玩家\g<target>",
            ),
            (
                r"^(?P<actor>.+?) voted villager-side players in consecutive rounds\.?$",
                r"\g<actor>连续多轮投票落在好人阵营玩家身上",
            ),
            (
                r"^(?P<actor>.+?) repeatedly voted villager-side players \((?P<count>\d+) times\)\.?$",
                r"\g<actor>连续\g<count>次把票投在好人阵营玩家身上",
            ),
            (
                r"^(?P<actor>.+?) poisoned villager-side player (?P<target>.+?)\.?$",
                r"\g<actor>毒杀了好人阵营玩家\g<target>",
            ),
            (
                r"^(?P<actor>.+?) shot villager-side player (?P<target>.+?)\.?$",
                r"\g<actor>开枪打中了好人阵营玩家\g<target>",
            ),
            (
                r"^(?P<actor>.+?) repeated the same guard target (?P<target>.+?) on consecutive nights\.?$",
                r"\g<actor>连续多夜重复守护同一目标\g<target>",
            ),
            (
                r"^(?P<actor>.+?) triggered invalid parsing or fallback handling (?P<count>\d+) times during the game\.?$",
                r"\g<actor>在本局中触发了解析失败或 fallback 共\g<count>次",
            ),
            (
                r"^(?P<actor>.+?) mentioned private night-side information in a public speech\.?$",
                r"\g<actor>在公开发言中提到了夜间私密信息",
            ),
            (
                r"^The table exiled villager-side player (?P<target>.+?) on day (?P<day>\d+)\.?$",
                r"第\g<day>天场上错误放逐了好人阵营玩家\g<target>",
            ),
            (
                r"^If one additional vote had moved onto (?P<target>.+?), the day could have resolved against a wolf instead\.?$",
                r"如果再有一票转投给\g<target>，这轮白天可能就会改为放逐狼人",
            ),
            (
                r"^The wrong exile on (?P<target>.+?) may have been avoided by consolidating onto (?P<wolf>.+?)\.?$",
                r"如果把票型集中到\g<wolf>身上，原本对\g<target>的错误放逐可能可以避免",
            ),
            (
                r"^If (?P<actor>.+?) had held poison or redirected onto a higher-confidence wolf target, (?P<target>.+?) might survive the night\.?$",
                r"如果\g<actor>当时选择不交毒，或改毒更高狼面的目标，\g<target>本可能活过当晚",
            ),
            (
                r"^Village-side numbers and public information from (?P<target>.+?) would likely be preserved\.?$",
                r"这样可以保留\g<target>带来的好人轮次人数与公开信息",
            ),
            (
                r"^The witch did not save key role (?P<target>.+?) on night (?P<day>\d+)\.?$",
                r"女巫在第\g<day>天夜里没有救下关键角色\g<target>",
            ),
            (
                r"^If the witch had saved (?P<target>.+?), the village might retain a high-value (?P<role>.+?) for the next day\.?$",
                r"如果女巫当晚救下\g<target>，好人阵营可能把这名高价值的\g<role>保留到下一天",
            ),
            (
                r"^(?P<target>.+?) died to the wolf attack on night (?P<day>\d+)\.?$",
                r"\g<target>在第\g<day>天夜里死于狼刀",
            ),
            (r"^(?P<role>.+?) is a key village-side role\.?$", r"\g<role>是好人阵营的关键角色"),
            (
                r"^If (?P<actor>.+?) had held the shot or targeted a higher-confidence wolf read, the trade could avoid friendly fire\.?$",
                r"如果\g<actor>当时选择不开枪，或改打更高狼面的目标，这次换子就可能避免误伤好人",
            ),
            (
                r"^Village-side resources would not be lost to the hunter shot on (?P<target>.+?)\.?$",
                r"这样就不会因为猎人这一枪再损失\g<target>对应的好人资源",
            ),
            (r"^Hunter shot removed (?P<target>.+?)\.?$", r"猎人开枪带走了\g<target>"),
            # Counterfactual expected_effect patterns
            (
                r"^Preserving (?P<target>.+?) could keep more public or private information online\.?$",
                r"保留\g<target>可以维持更多公开或私密信息渠道。",
            ),
            (
                r"^If (?P<actor>.+?) had switched to (?P<wolf>.+?), the wagon likely avoids exiling (?P<exiled>.+?)\.?$",
                r"如果\g<actor>转投\g<wolf>，放逐目标可能从\g<exiled>改为狼人。",
            ),
            (
                r"^Village-side elimination pressure could move from (?P<exiled>.+?) to wolf (?P<wolf>.+?)\.?$",
                r"好人阵营的放逐压力可能从\g<exiled>转向狼人\g<wolf>。",
            ),
            (
                r"^Publicly releasing the check could improve vote convergence onto (?P<target>.+?) and reduce good-player misvotes\.?$",
                r"公开发布查验结果可能让票型更快向\g<target>集中，减少好人误投。",
            ),
            # Counterfactual original_decision patterns (info release)
            (
                r"^(?P<actor>.+?) held the wolf result on (?P<target>.+?) instead of releasing it publicly\.?$",
                r"\g<actor>选择隐藏了对\g<target>的查杀结果，没有公开发布。",
            ),
            (
                r"^If (?P<actor>.+?) had announced the wolf check on (?P<target>.+?) during day (?P<day>\d+), the village might align votes earlier\.?$",
                r"如果\g<actor>在第\g<day>天公开宣布对\g<target>的查杀，好人阵营可能更早统一票型。",
            ),
            # Bad case: seer checked wolf but didn't release
            (
                r"^(?P<actor>.+?) checked wolf (?P<target>.+?) but did not release the information later\.?$",
                r"\g<actor>查验到狼人阵营\g<target>但未在后续公开该查杀信息",
            ),
        ]
        for pattern, repl in regex_replacements:
            result = re.sub(pattern, repl, result)
        # Role token replacement runs AFTER regex, so regex can match English.
        role_tokens = {
            "Seer": "预言家",
            "Werewolf": "狼人",
            "Witch": "女巫",
            "Hunter": "猎人",
            "Guard": "守卫",
            "Villager": "村民",
            "village": "好人阵营",
            "wolf": "狼人阵营",
        }
        for src, dst in role_tokens.items():
            result = re.sub(rf"\b{re.escape(src)}\b", dst, result)
        # Second pass: catch role tokens embedded in Chinese text (no word boundaries).
        for src, dst in role_tokens.items():
            if src in result:
                result = result.replace(src, dst)
        result = result.replace("checked-good player", "已被确认偏好人的玩家")
        result = result.replace("voted villager-side players in consecutive rounds", "连续多轮投票落在好人阵营玩家身上")
        result = result.replace("poisoned villager-side player", "毒杀了好人阵营玩家")
        result = result.replace("voted a checked-good player", "投票给已被确认偏好人的玩家")
        result = result.replace("villager-side players", "好人阵营玩家")
        result = result.replace("villager-side player", "好人阵营玩家")
        result = result.replace("wolf teammate", "狼人队友")
        result = result.replace("checked wolf", "查杀命中狼人")
        return result.strip().rstrip(".")

    def _bonus_title(self, bonus: ReviewBonus) -> str:
        title_map = {
            "decisive_vote": "关键一票",
            "seer_info_conversion": "查验信息转化",
            "seer_good_clear_guidance": "金水支撑建立",
            "last_wolf_poison": "最后一狼毒杀",
            "key_role_save": "关键救人",
            "guard_block_kill": "守卫挡刀",
            "guard_key_role_cover": "关键神职保护",
            "final_wolf_shot": "最后一狼击杀",
            "wolf_power_role_push": "关键神职放逐推进",
            "villager_vote_chain": "稳定归票链",
        }
        return title_map.get(bonus.bonus_type, bonus.bonus_type.replace("_", " ").title())

    # === v2 structured methods ===

    def _scan_safety(
        self,
        state: GameState,
        bad_cases: list[BadCaseReport],
        counterfactuals: list[CounterfactualCase],
        suggestions: list[StrategySuggestion],
        bonuses: list[ReviewBonus],
    ) -> dict[str, Any]:
        """Scan all review items for safety issues (info leaks, private info, unsafe patterns).

        Returns a safety_flags dict compatible with ReviewReport.safety_flags.
        """
        info_leak_count = 0
        private_info_items: list[str] = []
        unsafe_learning_items: list[str] = []

        # Forbidden patterns — any review item containing these must be marked unsafe
        _FORBIDDEN = [
            re.compile(r"\bP\d+\b"),  # Player ID pattern
            re.compile(r"\bplayer_\d+\b", re.IGNORECASE),
            re.compile(r"hidden\s*role", re.IGNORECASE),
            re.compile(r"private_reason", re.IGNORECASE),
            re.compile(r"read\s*hidden\s*role", re.IGNORECASE),
            re.compile(r"ignore\s*visibility", re.IGNORECASE),
            re.compile(r"change\s*game\s*rule", re.IGNORECASE),
        ]
        _ABSOLUTE_PATTERNS = [
            re.compile(r"\balways\b", re.IGNORECASE),
            re.compile(r"\bnever\b", re.IGNORECASE),
            re.compile(r"\bmust\b", re.IGNORECASE),
        ]

        wolf_names = {p.name for p in state.players if p.alignment == Alignment.WOLF}
        wolf_roles = {p.role.value for p in state.players if p.alignment == Alignment.WOLF}

        def _check_text(text: str, item_id: str) -> bool:
            """Returns True if the item is safe, False if it has leaks."""
            nonlocal info_leak_count
            safe = True

            for pat in _FORBIDDEN:
                if pat.search(text):
                    info_leak_count += 1
                    safe = False
                    private_info_items.append(f"{item_id}: matched forbidden pattern '{pat.pattern}'")
                    break

            # Check for wolf teammate identity leaks in public items
            for wname in wolf_names:
                if wname in text and "wolf" in text.lower():
                    info_leak_count += 1
                    safe = False
                    private_info_items.append(f"{item_id}: contains wolf teammate identity '{wname}'")
                    break

            return safe

        def _check_absolute(text: str) -> bool:
            """Returns True if contains absolute strategy patterns."""
            for pat in _ABSOLUTE_PATTERNS:
                if pat.search(text):
                    return True
            return False

        # Scan bad cases
        for bc in bad_cases:
            blob = f"{bc.description} {bc.suggested_fix}"
            if not _check_text(blob, f"bad_case:{getattr(bc, 'id', bc.game_id)}"):
                bc.safe_for_track_c_learning = False
                unsafe_learning_items.append(f"bad_case:{bc.player_name}:{bc.mistake_type}")
            if _check_absolute(blob):
                bc.safe_for_track_c_learning = False

        # Scan counterfactuals
        for cf in counterfactuals:
            blob = f"{cf.original_decision} {cf.alternative_decision} {cf.expected_effect}"
            if not _check_text(blob, f"counterfactual:{cf.case_id}"):
                cf.safe_for_track_c_learning = False
                unsafe_learning_items.append(f"counterfactual:{cf.case_id}")
            if _check_absolute(blob):
                cf.safe_for_track_c_learning = False

        # Scan suggestions
        for sug in suggestions:
            blob = f"{sug.suggestion} {sug.source}"
            if not _check_text(blob, f"suggestion:{sug.target_type}:{sug.target}"):
                unsafe_learning_items.append(f"suggestion:{sug.target_type}:{sug.target}")

        # Scan bonuses
        for bonus in bonuses:
            blob = f"{bonus.reason}"
            if not _check_text(blob, f"bonus:{bonus.player_id}:{bonus.bonus_type}"):
                unsafe_learning_items.append(f"bonus:{bonus.player_id}:{bonus.bonus_type}")

        return {
            "info_leak_count": info_leak_count,
            "private_info_items": private_info_items,
            "unsafe_learning_items": unsafe_learning_items,
        }

    def _generate_evolution_candidates(
        self,
        state: GameState,
        bad_cases: list[BadCaseReport],
        counterfactuals: list[CounterfactualCase],
        suggestions: list[StrategySuggestion],
        bonuses: list[ReviewBonus],
    ) -> list[EvolutionCandidate]:
        """Convert review items into evolution_candidates for Track C consumption.

        Entry conditions:
          - safe_for_track_c_learning = True
          - role not empty
          - phase not empty
          - trigger_condition not empty
          - lesson not empty
          - confidence >= 0.55
          - has evidence_refs
        """
        candidates: list[EvolutionCandidate] = []

        for bc in bad_cases:
            if not getattr(bc, "safe_for_track_c_learning", True):
                continue
            if not bc.role:
                continue
            blob = bc.description + bc.suggested_fix
            if not is_safe_for_track_c_learning(blob):
                continue
            ev = EvolutionCandidate(
                source_type="bad_case",
                source_id=getattr(bc, "id", bc.game_id),
                role=bc.role,
                phase=getattr(bc, "phase", ""),
                trigger_condition=getattr(bc, "trigger_condition", bc.description[:80]),
                lesson=bc.suggested_fix,
                evidence_refs=list(getattr(bc, "evidence_refs", [])),
                quality_signals={
                    "evidence_strength": 1.0 if bc.evidence_event_ids else 0.3,
                    "counterfactual_support": 0.0,
                    "repeatability_hint": 0.2,
                    "metric_relevance": 0.8 if bc.severity in ("critical", "major") else 0.55,
                    "judge_agreement": 1.0,
                    "confidence": getattr(bc, "confidence", 0.7),
                },
                visibility_scope=getattr(bc, "visibility_scope", "public"),
                safe_for_track_c_learning=True,
            )
            if ev.trigger_condition and ev.lesson:
                candidates.append(ev)

        for cf in counterfactuals:
            if not getattr(cf, "safe_for_track_c_learning", True):
                continue
            role = getattr(cf, "role", "") or cf.affected_players[0] if cf.affected_players else ""
            blob = cf.original_decision + cf.alternative_decision + cf.expected_effect
            if not is_safe_for_track_c_learning(blob):
                continue
            if cf.confidence < 0.55:
                continue
            ev = EvolutionCandidate(
                source_type="counterfactual",
                source_id=cf.case_id,
                role=role,
                phase=cf.phase or "",
                trigger_condition=f"When {cf.original_decision[:80]}",
                lesson=cf.alternative_decision,
                evidence_refs=list(getattr(cf, "evidence_refs", [])),
                quality_signals={
                    "evidence_strength": 0.5 if cf.evidence else 0.3,
                    "counterfactual_support": 1.0,
                    "repeatability_hint": 0.2,
                    "metric_relevance": 0.55,
                    "judge_agreement": 1.0,
                    "confidence": cf.confidence,
                },
                visibility_scope=getattr(cf, "visibility_scope", "public"),
                safe_for_track_c_learning=True,
            )
            if ev.trigger_condition and ev.lesson:
                candidates.append(ev)

        for sug in suggestions:
            role = sug.target if sug.target_type == "role" else ""
            blob = sug.suggestion + sug.source
            if not is_safe_for_track_c_learning(blob):
                continue
            ev = EvolutionCandidate(
                source_type="suggestion",
                source_id=f"{sug.target_type}:{sug.target}",
                role=role,
                phase="",
                trigger_condition=f"{sug.suggestion_type}",
                lesson=sug.suggestion,
                evidence_refs=[],
                quality_signals={
                    "evidence_strength": 0.5,
                    "counterfactual_support": 0.0,
                    "repeatability_hint": 0.2,
                    "metric_relevance": 0.8 if sug.priority == "high" else 0.55,
                    "judge_agreement": 1.0,
                    "confidence": 0.6,
                },
                visibility_scope="public",
                safe_for_track_c_learning=True,
            )
            if ev.trigger_condition and ev.lesson:
                candidates.append(ev)

        return candidates


# ---------------------------------------------------------------------------
# Safety helpers (shared across Track B / Track C)
# ---------------------------------------------------------------------------

_FORBIDDEN_SAFETY_PATTERNS = [
    re.compile(r"\bP\d+\b"),
    re.compile(r"\bplayer_\d+\b", re.IGNORECASE),
    re.compile(r"hidden\s*role", re.IGNORECASE),
    re.compile(r"private_reason", re.IGNORECASE),
    re.compile(r"read\s*hidden\s*role", re.IGNORECASE),
    re.compile(r"ignore\s*visibility", re.IGNORECASE),
    re.compile(r"change\s*game\s*rule", re.IGNORECASE),
]
_ABSOLUTE_STRATEGY_PATTERNS = [
    re.compile(r"\balways\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bmust\b", re.IGNORECASE),
]


def is_safe_for_track_c_learning(text_or_item: Any) -> bool:
    """Check whether a review item is safe for Track C consumption.

    Conditions (all must pass):
      1. No player ID patterns (P1, P2, player_1, etc.)
      2. No hidden role references
      3. No private_reason references
      4. No "read hidden role" or "ignore visibility" or "change game rule"
      5. No absolute strategy words (always, never, must)
    """
    if hasattr(text_or_item, "description") and hasattr(text_or_item, "suggested_fix"):
        text = f"{getattr(text_or_item, 'description', '')} {getattr(text_or_item, 'suggested_fix', '')}"
        if hasattr(text_or_item, "expected_effect"):
            text += f" {getattr(text_or_item, 'expected_effect', '')}"
    else:
        text = str(text_or_item)

    for pat in _FORBIDDEN_SAFETY_PATTERNS:
        if pat.search(text):
            return False

    # Absolute strategies are NOT safe but can be downgraded (soft suggestion).
    # is_safe_for_track_c_learning still returns False for them so Track C
    # can decide to skip or downgrade.
    for pat in _ABSOLUTE_STRATEGY_PATTERNS:
        if pat.search(text):
            return False

    return True


def _bonus_to_dict(bonus: ReviewBonus) -> dict[str, Any]:
    """Convert a ReviewBonus to a dict for storage in ReviewReport.bonuses."""
    return {
        "player_id": bonus.player_id,
        "bonus_type": bonus.bonus_type,
        "score_delta": bonus.score_delta,
        "reason": bonus.reason,
        "confidence": bonus.confidence,
        "day": bonus.day,
        "phase": bonus.phase,
        "category": bonus.category,
        "visibility_scope": getattr(bonus, "visibility_scope", "public"),
        "safe_for_track_c_learning": getattr(bonus, "safe_for_track_c_learning", True),
    }


class CounterfactualAnalyzer:
    """Derives lightweight local counterfactuals from logs, bad cases, and turning points."""

    def analyze(
        self,
        state: GameState,
        metrics: GameMetrics,
        *,
        bad_cases: Sequence[BadCaseReport],
        turning_points: Sequence[TurningPoint],
        review_bonuses: Sequence[ReviewBonus],
        llm_only: bool = True,
    ) -> list[CounterfactualCase]:
        """Generate counterfactuals for a completed game.

        Args:
            state: Full game state with events.
            metrics: Computed game metrics.
            bad_cases: Pre-identified bad cases.
            turning_points: Pre-identified turning points.
            review_bonuses: Pre-computed review bonuses.
            llm_only: If True (default), only analyze decisions by LLM agents,
                      skipping heuristic/human decisions to avoid data pollution.
        """
        cases: list[CounterfactualCase] = []

        # Build LLM player filter
        llm_player_ids: set[str] | None = None
        if llm_only:
            llm_player_ids = {p.id for p in state.players if (p.agent_type or "").lower() in ("llm", "cognitive")}
            if not llm_player_ids:
                return []  # No LLM players in this game — skip entirely

        # Each method is wrapped so one failure doesn't block other types
        for method in [
            self._vote_cases,
            self._skill_cases,
            self._info_release_cases,
            self._guard_cases,
            self._seer_target_cases,
            self._speech_strategy_cases,
            self._stance_flip_cases,
            self._badge_election_cases,
            self._claim_timing_cases,
            self._coordination_cases,
        ]:
            try:
                if method == self._vote_cases:
                    cases.extend(method(state, bad_cases, turning_points))
                elif method == self._skill_cases:
                    cases.extend(method(state, bad_cases))
                elif method == self._info_release_cases:
                    cases.extend(method(state, bad_cases, review_bonuses))
                elif method == self._speech_strategy_cases or method == self._badge_election_cases:
                    cases.extend(method(state, bad_cases, turning_points))
                elif method == self._claim_timing_cases:
                    cases.extend(method(state, bad_cases))
                elif method == self._coordination_cases:
                    cases.extend(method(state, bad_cases, turning_points))
                else:
                    cases.extend(method(state, bad_cases))
            except Exception as e:
                import logging

                logging.getLogger(__name__).debug(f"Counterfactual method {method.__name__} failed: {e}")

        # Filter: keep only cases where the primary affected player is LLM
        if llm_only and llm_player_ids:
            cases = [c for c in cases if self._is_llm_decision(c, state, llm_player_ids)]

        deduped: dict[tuple[Any, ...], CounterfactualCase] = {}
        for case in cases:
            key = (case.day, case.phase, case.counterfactual_type, case.original_decision, case.alternative_decision)
            if key not in deduped or case.confidence > deduped[key].confidence:
                deduped[key] = case
        return sorted(deduped.values(), key=lambda item: ((item.day or 0), item.confidence), reverse=True)

    def _vote_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
        turning_points: Sequence[TurningPoint],
    ) -> list[CounterfactualCase]:
        cases: list[CounterfactualCase] = []
        vote_days = sorted({event.day for event in state.events if event.type == EventType.VOTE_CAST})
        for day in vote_days:
            exile = next(
                (
                    event
                    for event in state.events
                    if event.type == EventType.PLAYER_DIED
                    and event.day == day
                    and event.payload.get("reason") == "vote"
                ),
                None,
            )
            if exile is None:
                continue
            exiled = state.player(str(exile.payload.get("player_id")))
            if exiled.alignment not in (Alignment.VILLAGE, Alignment.WOLF):
                continue

            counts: dict[str, int] = defaultdict(int)
            ordered_votes = [
                event
                for event in sorted(state.events, key=lambda item: item.ts)
                if event.type == EventType.VOTE_CAST and event.day == day
            ]
            for event in ordered_votes:
                target_id = event.payload.get("target_id")
                if target_id:
                    counts[str(target_id)] += 1
            if not counts:
                continue
            exiled_votes = counts.get(exiled.id, 0)

            # Determine alternative faction based on who was exiled
            if exiled.alignment == Alignment.VILLAGE:
                # Village player eliminated → find closest wolf alternative
                alt_targets = [
                    (target_id, count)
                    for target_id, count in counts.items()
                    if state.player(target_id).alignment == Alignment.WOLF
                ]
                alt_faction = "wolf"
            else:
                # Wolf eliminated → find closest village alternative
                alt_targets = [
                    (target_id, count)
                    for target_id, count in counts.items()
                    if state.player(target_id).alignment == Alignment.VILLAGE
                ]
                alt_faction = "village"
            if not alt_targets:
                continue
            alt_target_id, alt_votes = max(alt_targets, key=lambda item: item[1])
            if exiled_votes - alt_votes > 1:
                continue

            alt_target = state.player(alt_target_id)
            pivot_vote = self._find_pivot_vote(ordered_votes, exiled.id, alt_target_id)
            source_turning_point_id = self._find_turning_point_id(turning_points, day, exiled.name)
            source_bad_case_id = self._find_bad_case_id(bad_cases, day, exiled.name, "vote")

            if exiled.alignment == Alignment.VILLAGE:
                # --- Village exile counterfactuals (original logic, refactored) ---
                if pivot_vote is not None:
                    voter = state.player(str(pivot_vote.payload.get("voter_id")))
                    current_target = state.player(str(pivot_vote.payload.get("target_id")))
                    recomputed = self._recompute_vote_flip(ordered_votes, voter.id, alt_target_id, exiled.id)
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-vote-{day}-{voter.id}",
                            game_id=state.id,
                            day=day,
                            phase=pivot_vote.phase.value,
                            counterfactual_type="vote",
                            original_decision=f"{voter.name} voted {current_target.name} on day {day}.",
                            alternative_decision=f"If {voter.name} had switched to {alt_target.name}, the wagon likely avoids exiling {exiled.name}.",
                            expected_effect=f"Village-side elimination pressure could move from {exiled.name} to wolf {alt_target.name}.",
                            affected_players=[voter.name, exiled.name, alt_target.name],
                            confidence=0.82,
                            evidence=[
                                f"{exiled.name} was exiled with {exiled_votes} vote(s).",
                                f"{alt_target.name} finished close behind with {alt_votes} vote(s).",
                            ],
                            severity="major",
                            source_bad_case_id=source_bad_case_id,
                            source_turning_point_id=source_turning_point_id,
                            effect_type="exact_recalculation",
                            recomputed_outcome=recomputed,
                            evidence_event_ids=[pivot_vote.id]
                            + [vote.id for vote in ordered_votes if vote.day == day][:3],
                        )
                    )
                else:
                    recomputed = {
                        "tally_unchanged": True,
                        "original_exile": exiled.id,
                        "alternative_target": alt_target.id,
                    }
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-vote-{day}-{exiled.id}",
                            game_id=state.id,
                            day=day,
                            phase="DAY_VOTE",
                            counterfactual_type="vote",
                            original_decision=f"The table exiled villager-side player {exiled.name} on day {day}.",
                            alternative_decision=f"If one additional vote had moved onto {alt_target.name}, the day could have resolved against a wolf instead.",
                            expected_effect=f"The wrong exile on {exiled.name} may have been avoided by consolidating onto {alt_target.name}.",
                            affected_players=[exiled.name, alt_target.name],
                            confidence=0.72,
                            evidence=[
                                f"{alt_target.name} was the closest wolf wagon with {alt_votes} vote(s).",
                                f"The margin to {exiled.name} was only {exiled_votes - alt_votes}.",
                            ],
                            severity="major",
                            source_bad_case_id=source_bad_case_id,
                            source_turning_point_id=source_turning_point_id,
                            effect_type="exact_recalculation",
                            recomputed_outcome=recomputed,
                            evidence_event_ids=[vote.id for vote in ordered_votes if vote.day == day][:4],
                        )
                    )
            else:
                # --- Wolf exile counterfactuals (new) ---
                if pivot_vote is not None:
                    voter = state.player(str(pivot_vote.payload.get("voter_id")))
                    current_target = state.player(str(pivot_vote.payload.get("target_id")))
                    recomputed = self._recompute_vote_flip(ordered_votes, voter.id, alt_target_id, exiled.id)
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-vote-wolf-{day}-{voter.id}",
                            game_id=state.id,
                            day=day,
                            phase=pivot_vote.phase.value,
                            counterfactual_type="vote",
                            original_decision=f"{voter.name} voted to exile wolf {exiled.name} on day {day}.",
                            alternative_decision=f"If {voter.name} had switched to {alt_target.name}, a village player would have been exiled instead of wolf {exiled.name}.",
                            expected_effect=f"Wolf-hunting robustness test: was exiling {exiled.name} the best play, or should votes have consolidated toward {alt_target.name}?",
                            affected_players=[voter.name, exiled.name, alt_target.name],
                            confidence=0.82,
                            evidence=[
                                f"Wolf {exiled.name} was exiled with {exiled_votes} vote(s).",
                                f"{alt_target.name} (village) finished close behind with {alt_votes} vote(s).",
                            ],
                            severity="major",
                            source_bad_case_id=source_bad_case_id,
                            source_turning_point_id=source_turning_point_id,
                            effect_type="exact_recalculation",
                            recomputed_outcome=recomputed,
                            evidence_event_ids=[pivot_vote.id]
                            + [vote.id for vote in ordered_votes if vote.day == day][:3],
                        )
                    )
                else:
                    recomputed = {
                        "tally_unchanged": True,
                        "original_exile": exiled.id,
                        "alternative_target": alt_target.id,
                    }
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-vote-wolf-{day}-{exiled.id}",
                            game_id=state.id,
                            day=day,
                            phase="DAY_VOTE",
                            counterfactual_type="vote",
                            original_decision=f"The table exiled wolf {exiled.name} on day {day}.",
                            alternative_decision=f"If one additional vote had moved onto village player {alt_target.name}, the day could have resolved against the village instead of exiling wolf {exiled.name}.",
                            expected_effect=f"Wolf-hunting robustness test: was the exile of {exiled.name} the correct call, or was there a better target?",
                            affected_players=[exiled.name, alt_target.name],
                            confidence=0.72,
                            evidence=[
                                f"{alt_target.name} (village) was closest behind with {alt_votes} vote(s).",
                                f"The margin to {exiled.name} was only {exiled_votes - alt_votes}.",
                            ],
                            severity="major",
                            source_bad_case_id=source_bad_case_id,
                            source_turning_point_id=source_turning_point_id,
                            effect_type="exact_recalculation",
                            recomputed_outcome=recomputed,
                            evidence_event_ids=[vote.id for vote in ordered_votes if vote.day == day][:4],
                        )
                    )
        return cases

    def _skill_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
    ) -> list[CounterfactualCase]:
        cases: list[CounterfactualCase] = []

        # Group night actions by day for exact replay
        night_actions_by_day: dict[int, list[GameEvent]] = defaultdict(list)
        for event in state.events:
            if event.type == EventType.NIGHT_ACTION:
                night_actions_by_day[event.day].append(event)

        for day, day_events in night_actions_by_day.items():
            # Build night snapshot for exact replay
            wolf_target_id = guard_target_id = None
            witch_save_used = False
            witch_poison_target_id = None

            for e in day_events:
                at = e.payload.get("action_type", "")
                tid = str(e.payload.get("target_id", "") or "")
                if at == "attack" and tid:
                    wolf_target_id = tid
                elif at in ("guard", "guard_protect") and tid:
                    guard_target_id = tid
                elif at == "witch_save":
                    witch_save_used = True
                elif at == "witch_poison" and tid:
                    witch_poison_target_id = tid

            if not wolf_target_id and not witch_poison_target_id:
                continue

            original_snapshot = NightActionsSnapshot(
                day=day,
                wolf_target_id=wolf_target_id,
                guard_target_id=guard_target_id,
                witch_save_used=witch_save_used,
                witch_poison_target_id=witch_poison_target_id,
            )

            # --- witch_poison cases (exact replay) ---
            if witch_poison_target_id:
                poison_target = self._target_player_by_id(state, witch_poison_target_id)
                if poison_target and poison_target.alignment == Alignment.VILLAGE:
                    # Exact replay: what if witch didn't poison this target?
                    orig_result, cf_result = replay_night_with_change(
                        original_snapshot,
                        new_poison_target=None,
                    )
                    poison_actor = state.player(
                        str(
                            next(
                                (e for e in day_events if e.payload.get("action_type") == "witch_poison"), {}
                            ).payload.get("actor_id", "")
                        )
                    )
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-witch-poison-{day}-{poison_actor.id}",
                            game_id=state.id,
                            day=day,
                            phase="NIGHT_WITCH_ACTION",
                            counterfactual_type="skill",
                            original_decision=f"{poison_actor.name} poisoned villager-side player {poison_target.name}.",
                            alternative_decision=f"If {poison_actor.name} had held poison, {poison_target.name} would survive.",
                            expected_effect=f"Village retains {poison_target.name} and one extra vote for future days.",
                            affected_players=[poison_actor.name, poison_target.name],
                            confidence=0.95,  # Exact: we know for sure they'd survive
                            evidence=[
                                f"Poison directly killed {poison_target.name}.",
                                f"Exact replay: {len(orig_result.deaths)} deaths → {len(cf_result.deaths)} deaths.",
                            ],
                            severity="critical",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, day, poison_actor.name, "ability"),
                            effect_type="local_recalculation",
                            recomputed_outcome={
                                "original_deaths": orig_result.deaths,
                                "cf_deaths": cf_result.deaths,
                                "outcome_changed": witch_poison_target_id
                                not in {d["player_id"] for d in cf_result.deaths},
                                "method": "local_recalculation",
                            },
                            evidence_event_ids=[e.id for e in day_events[:3]],
                        )
                    )

            # --- witch_save cases (exact replay) ---
            if wolf_target_id and not witch_save_used:
                wolf_victim = self._target_player_by_id(state, wolf_target_id)
                if wolf_victim and wolf_victim.role in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD}:
                    if self._died_by_reason(state, wolf_target_id, "wolf", day):
                        # Exact replay: what if witch saved the key role?
                        orig_result, cf_result = replay_night_with_change(
                            original_snapshot,
                            new_witch_save=True,
                        )
                        witch_player = state.role_player(Role.WITCH)
                        witch_name = witch_player.name if witch_player else "the witch"
                        outcome_changed = wolf_target_id not in {d["player_id"] for d in cf_result.deaths}
                        cases.append(
                            CounterfactualCase(
                                case_id=f"{state.id}-witch-save-{day}-{wolf_target_id}",
                                game_id=state.id,
                                day=day,
                                phase="NIGHT_WITCH_ACTION",
                                counterfactual_type="skill",
                                original_decision=f"The witch did not save {wolf_victim.name}({wolf_victim.role.value}) on night {day}.",
                                alternative_decision=f"If the witch had saved {wolf_victim.name}, they would survive the night.",
                                expected_effect=f"Preserving {wolf_victim.name} retains {wolf_victim.role.value} abilities.",
                                affected_players=[witch_name, wolf_victim.name],
                                confidence=0.95 if outcome_changed else 0.40,
                                evidence=[
                                    f"{wolf_victim.name}({wolf_victim.role.value}) died to wolf attack.",
                                    f"Exact replay: {len(orig_result.deaths)} deaths → {len(cf_result.deaths)} deaths.",
                                ],
                                severity="major" if outcome_changed else "moderate",
                                effect_type="local_recalculation",
                                recomputed_outcome={
                                    "original_deaths": orig_result.deaths,
                                    "cf_deaths": cf_result.deaths,
                                    "outcome_changed": outcome_changed,
                                    "method": "local_recalculation",
                                },
                                evidence_event_ids=[e.id for e in day_events[:3]],
                            )
                        )

        # --- hunter_shot cases (exact) ---
        for event in state.events:
            if event.type != EventType.HUNTER_SHOT:
                continue
            hunter = state.player(str(event.payload.get("hunter_id")))
            target = state.player(str(event.payload.get("target_id")))
            if target.alignment != Alignment.VILLAGE:
                continue

            # Exact: if hunter shot a wolf instead
            wolf_targets = [p for p in state.players if p.alignment == Alignment.WOLF and p.alive and p.id != target.id]
            alt_target = wolf_targets[0] if wolf_targets else None
            alt_name = alt_target.name if alt_target else "a wolf"

            result = replay_hunter_shot(target.id, alt_target.id if alt_target else target.id)
            cases.append(
                CounterfactualCase(
                    case_id=f"{state.id}-hunter-shot-{event.day}-{hunter.id}",
                    game_id=state.id,
                    day=event.day,
                    phase=event.phase.value,
                    counterfactual_type="skill",
                    original_decision=f"{hunter.name} shot villager-side player {target.name}.",
                    alternative_decision=f"If {hunter.name} had held the shot or aimed at {alt_name} instead, friendly fire would be avoided.",
                    expected_effect=f"Village resources preserved; wolf {alt_name} eliminated instead.",
                    affected_players=[hunter.name, target.name, alt_name],
                    confidence=0.95,
                    evidence=[
                        f"Hunter shot removed {target.name}({target.role.value}, alignment=village).",
                        f"Alternative target {alt_name} is a wolf. Exact: outcome would change.",
                    ],
                    severity="critical",
                    source_bad_case_id=self._find_bad_case_id(bad_cases, event.day, hunter.name, "ability"),
                    effect_type="local_recalculation",
                    recomputed_outcome=result,
                    evidence_event_ids=[event.id],
                )
            )
        return cases

    def _info_release_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
        review_bonuses: Sequence[ReviewBonus],
    ) -> list[CounterfactualCase]:
        """Information release counterfactuals — expanded beyond Seer-only.

        From Information Cascade Theory in Hidden Role Games (Kim et al. 2025):
        Roles with private info (Seer, Witch, Guard) must balance information
        revelation against self-preservation. Withholding too long = missed influence.
        Revealing too early = wasted information advantage.

        Now covers: Seer (wolf checks), Witch (antidote/poison usage), Guard (protection
        targets), and general information withholding patterns.
        """
        cases: list[CounterfactualCase] = []
        contexts = self._build_contexts(state)

        for player in state.players:
            ctx = contexts.get(player.id)
            if ctx is None:
                continue

            # ---- Seer: wolf result not released ----
            if player.role == Role.SEER:
                wolf_checks = [
                    event
                    for event in ctx.private_info_events
                    if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")
                ]
                if wolf_checks and not any(
                    bonus.player_id == player.id and bonus.bonus_type == "seer_info_conversion"
                    for bonus in review_bonuses
                ):
                    released_targets = self._released_check_targets(ctx)
                    for check_event in wolf_checks:
                        target_name = str(check_event.payload.get("target_name") or "")
                        if target_name and target_name in released_targets:
                            continue
                        day = self._first_speech_day(ctx) or check_event.day
                        bad_case_id = self._find_bad_case_id(bad_cases, day, player.name, "speech")
                        cases.append(
                            CounterfactualCase(
                                case_id=f"{state.id}-info-seer-{day}-{player.id}",
                                game_id=state.id,
                                day=day,
                                phase="DAY_SPEECH",
                                counterfactual_type="info_release",
                                original_decision=f"{player.name}(Seer) held the wolf result on {target_name} instead of releasing it publicly.",
                                alternative_decision=f"If {player.name} had announced the wolf check on {target_name} during day {day}, the village might align votes earlier.",
                                expected_effect="Publicly releasing the check would likely improve vote convergence onto the wolf target and reduce good-player misvotes.",
                                affected_players=[player.name, target_name],
                                confidence=0.84,
                                evidence=[
                                    f"Private seer result identified {target_name} as wolf.",
                                    f"No later public speech from {player.name} referenced that result.",
                                ],
                                severity="major",
                                source_bad_case_id=bad_case_id,
                                effect_type="estimated",
                                recomputed_outcome={"role": "Seer", "estimated_target_suspicion_delta": "+0.30"},
                                evidence_event_ids=[check_event.id],
                            )
                        )
                        break  # One case per Seer per game

            # ---- Witch: antidote/poison usage not revealed ----
            if player.role == Role.WITCH:
                night_actions = [
                    e for e in ctx.night_action_events if e.payload.get("action_type") in ("witch_save", "witch_poison")
                ]
                for action in night_actions:
                    at = action.payload.get("action_type", "")
                    target_name = str(action.payload.get("target_name", ""))
                    # Check if this info was shared in any speech
                    info_shared = any(
                        target_name in (s.payload.get("speech", "") or "")
                        for s in ctx.speech_events
                        if s.day >= action.day
                    )
                    if info_shared:
                        continue
                    action_label = "解药救了" if at == "witch_save" else "毒药毒了"
                    day = action.day + 1  # Info should be released the next day
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-info-witch-{day}-{player.id}-{at}",
                            game_id=state.id,
                            day=day,
                            phase="DAY_SPEECH",
                            counterfactual_type="info_release",
                            original_decision=f"{player.name}(Witch) used {action_label}{target_name} on night {action.day} but never revealed this information.",
                            alternative_decision=f"If {player.name} had shared their {action_label} action, the village would have more accurate role information.",
                            expected_effect="Revealing witch actions confirms roles and narrows wolf hiding space.",
                            affected_players=[player.name, target_name],
                            confidence=0.78,
                            evidence=[
                                f"Witch {action_label} {target_name} on night {action.day}.",
                                "Information never shared in public speeches.",
                            ],
                            severity="moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, day, player.name, "speech"),
                            effect_type="estimated",
                            recomputed_outcome={"role": "Witch", "action_type": at, "target": target_name},
                            evidence_event_ids=[action.id],
                        )
                    )
                    break  # One case per Witch per game

            # ---- Guard: protection targets never revealed ----
            if player.role == Role.GUARD:
                guard_actions = [
                    e for e in ctx.night_action_events if e.payload.get("action_type") in ("guard", "guard_protect")
                ]
                for action in guard_actions:
                    target_name = str(action.payload.get("target_name", ""))
                    info_shared = any(
                        target_name in (s.payload.get("speech", "") or "")
                        for s in ctx.speech_events
                        if s.day >= action.day
                    )
                    if info_shared:
                        continue
                    # Only flag if the protected player later died (guard info became valuable)
                    target_died = self._died_by_reason(state, action.payload.get("target_id", ""), "")
                    day = action.day + 1
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-info-guard-{day}-{player.id}",
                            game_id=state.id,
                            day=day,
                            phase="DAY_SPEECH",
                            counterfactual_type="info_release",
                            original_decision=f"{player.name}(Guard) protected {target_name} on night {action.day} but never revealed this information.",
                            alternative_decision=f"If {player.name} had shared their protection target history, the village could deduce wolf targeting patterns.",
                            expected_effect="Guard protection history helps village identify wolf kill preferences and narrow suspect pool.",
                            affected_players=[player.name, target_name],
                            confidence=0.62 if not target_died else 0.72,
                            evidence=[
                                f"Guard protected {target_name} on night {action.day}.",
                                "Information never shared in public speeches.",
                            ],
                            severity="minor" if not target_died else "moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, day, player.name, "speech"),
                            effect_type="estimated",
                            recomputed_outcome={"role": "Guard", "protected": target_name},
                            evidence_event_ids=[action.id],
                        )
                    )
                    break  # One case per Guard per game

        return cases

    # ---- New counterfactual dimensions (2025 research-backed) ----

    def _guard_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
    ) -> list[CounterfactualCase]:
        """Guard target counterfactuals — EXACT recalculation via night replay.

        Uses replay_night_with_change to deterministically compute:
        "If the guard had protected X instead of Y, who would have died?"
        """
        cases: list[CounterfactualCase] = []

        # Group night actions by day for replay
        night_actions_by_day: dict[int, list[GameEvent]] = defaultdict(list)
        for event in state.events:
            if event.type == EventType.NIGHT_ACTION:
                night_actions_by_day[event.day].append(event)

        for day, day_events in night_actions_by_day.items():
            # Build snapshot
            wolf_target_id = guard_target_id = None
            for e in day_events:
                at = e.payload.get("action_type", "")
                tid = str(e.payload.get("target_id", "") or "")
                if at == "attack" and tid:
                    wolf_target_id = tid
                elif at in ("guard", "guard_protect") and tid:
                    guard_target_id = tid

            if not wolf_target_id:
                continue

            # Find deaths this night
            night_deaths = [
                e
                for e in state.events
                if e.type == EventType.PLAYER_DIED and e.day == day and e.payload.get("reason") == "wolf"
            ]
            if not night_deaths:
                continue  # No one died from wolf attack — guard did their job or witch saved

            victim_id = str(night_deaths[0].payload.get("player_id", ""))
            victim = state.player(victim_id) if victim_id else None
            if victim is None:
                continue

            # Only flag if the victim is a key role
            if victim.role not in {Role.SEER, Role.WITCH, Role.HUNTER}:
                continue

            # Don't flag if guard already protected the victim (witch save intervened)
            if guard_target_id and guard_target_id == victim_id:
                continue

            # EXACT REPLAY: what if guard protected the victim?
            original = NightActionsSnapshot(
                day=day,
                wolf_target_id=wolf_target_id,
                guard_target_id=guard_target_id,
            )
            orig_result, cf_result = replay_night_with_change(
                original,
                new_guard_target=guard_target_id or victim_id,
            )

            # If counterfactual actually changes the death outcome
            guard_actor_name = "Guard"
            for e in day_events:
                if e.payload.get("action_type") in ("guard", "guard_protect"):
                    guard_actor_name = str(e.payload.get("actor_name", "Guard"))

            cf_guard_target = state.player(guard_target_id) if guard_target_id else None
            protected_name = cf_guard_target.name if cf_guard_target else "nobody"

            outcome_changed = victim_id not in {d["player_id"] for d in cf_result.deaths}
            confidence = 0.92 if outcome_changed else 0.45

            # Determine who WOULD have been guarded in the counterfactual
            alt_guard_name = victim.name  # We're testing: "guard protected victim instead"

            cases.append(
                CounterfactualCase(
                    case_id=f"{state.id}-guard-{day}-{guard_actor_name}",
                    game_id=state.id,
                    day=day,
                    phase="NIGHT_GUARD_ACTION",
                    counterfactual_type="guard_target",
                    original_decision=(
                        f"Guard {guard_actor_name} protected {protected_name} on night {day}. "
                        f"{victim.name}({victim.role.value}) died to wolf attack."
                    ),
                    alternative_decision=(
                        f"If guard had protected {alt_guard_name}({victim.role.value}) instead of {protected_name}, "
                        f"{victim.name} would {'have survived' if outcome_changed else 'still have died'}."
                    ),
                    expected_effect=(
                        f"Village retains {victim.role.value} abilities for future rounds."
                        if outcome_changed
                        else f"Guard target change does not affect outcome — {victim.name} died for other reasons."
                    ),
                    affected_players=[guard_actor_name, victim.name, protected_name],
                    confidence=confidence,
                    evidence=[
                        f"Wolf attacked {state.player(wolf_target_id).name if wolf_target_id else '?'}.",
                        f"Guard protected {protected_name}.",
                        f"Exact replay: {len(orig_result.deaths)} deaths → {len(cf_result.deaths)} deaths.",
                        f"Outcome changed: {outcome_changed}.",
                    ],
                    severity="major" if outcome_changed else "moderate",
                    source_bad_case_id=self._find_bad_case_id(bad_cases, day, guard_actor_name, "ability"),
                    effect_type="exact_recalculation",
                    recomputed_outcome={
                        "original_deaths": orig_result.deaths,
                        "counterfactual_deaths": cf_result.deaths,
                        "outcome_changed": outcome_changed,
                        "method": "exact_recalculation",
                    },
                    evidence_event_ids=[e.id for e in day_events[:5]],
                )
            )
        return cases

    def _seer_target_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
    ) -> list[CounterfactualCase]:
        """Seer check target counterfactuals.

        From Reflection-Bench §3.5: counterfactual thinking evaluation.
        What if the seer had checked a different (higher-impact) player?
        """
        cases: list[CounterfactualCase] = []
        seer_checks: list[tuple[GameEvent, str, bool]] = []
        for event in state.events:
            if event.type != EventType.NIGHT_ACTION:
                continue
            if event.payload.get("action_type") != "divine":
                continue
            target_id = str(event.payload.get("target_id", ""))
            is_wolf = event.payload.get("is_wolf", False)
            if target_id:
                seer_checks.append((event, target_id, is_wolf))

        if not seer_checks:
            return cases

        # Find eventual wolves (known from final state)
        actual_wolves = {p.id for p in state.players if p.alignment == Alignment.WOLF}

        for event, target_id, is_wolf in seer_checks:
            seer_player = state.player(str(event.payload.get("actor_id", "")))
            target = state.player(target_id)

            # Case A: Checked a villager when there were undetected wolves
            if not is_wolf and actual_wolves:
                unchecked_wolves = actual_wolves - {target_id}
                if not unchecked_wolves:
                    continue
                # Pick a wolf that was alive at check time
                wolf_candidates = [w for w in unchecked_wolves if any(p.id == w and p.alive for p in state.players)]
                if not wolf_candidates:
                    continue
                wolf_name = state.player(list(wolf_candidates)[0]).name
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-seer-{event.day}-{seer_player.id}",
                        game_id=state.id,
                        day=event.day,
                        phase=event.phase.value,
                        counterfactual_type="seer_target",
                        original_decision=f"{seer_player.name} checked {target.name} (non-wolf) on night {event.day}.",
                        alternative_decision=f"If {seer_player.name} had checked {wolf_name} instead, a wolf might have been identified sooner.",
                        expected_effect=f"Earlier wolf identification on {wolf_name} could accelerate village vote convergence.",
                        affected_players=[seer_player.name, target.name, wolf_name],
                        confidence=0.72,
                        evidence=[
                            f"Seer verified {target.name} is not a wolf.",
                            f"{wolf_name} was an undetected wolf at this point.",
                        ],
                        severity="moderate",
                        source_bad_case_id=self._find_bad_case_id(bad_cases, event.day, seer_player.name, "ability"),
                        effect_type="estimated",
                        recomputed_outcome={"missed_wolf_check": wolf_name},
                        evidence_event_ids=[event.id],
                    )
                )

            # Case B: Checked a wolf but didn't release the info (low confidence flag)
            if is_wolf and target.alive:
                # Check if seer ever publicly mentioned this result
                contexts = self._build_contexts(state)
                ctx = contexts.get(seer_player.id)
                if ctx:
                    released = any(target.name in (s.payload.get("speech", "") or "") for s in ctx.speech_events)
                    if not released:
                        cases.append(
                            CounterfactualCase(
                                case_id=f"{state.id}-seer-hold-{event.day}-{seer_player.id}",
                                game_id=state.id,
                                day=event.day,
                                phase=event.phase.value,
                                counterfactual_type="seer_target",
                                original_decision=f"{seer_player.name} checked {target.name} (wolf!) but did not publicly push the result.",
                                alternative_decision=f"If {seer_player.name} had aggressively pushed the wolf check on {target.name}, the village could align faster.",
                                expected_effect="Public wolf identification would likely improve vote accuracy.",
                                affected_players=[seer_player.name, target.name],
                                confidence=0.85,
                                evidence=[
                                    f"Seer confirmed {target.name} is a wolf.",
                                    "No public speech reference to this check found.",
                                ],
                                severity="major",
                                source_bad_case_id=self._find_bad_case_id(
                                    bad_cases, event.day, seer_player.name, "speech"
                                ),
                                effect_type="estimated",
                                recomputed_outcome={"unreleased_wolf_check": target.id},
                                evidence_event_ids=[event.id],
                            )
                        )
        return cases

    def _speech_strategy_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
        turning_points: Sequence[TurningPoint],
    ) -> list[CounterfactualCase]:
        """Speech strategy counterfactuals.

        From Beyond Survival §5.1: strategy-alignment evaluation.
        What if the agent had used a different speech approach at key moments?

        Detects: repeating the same argument, not responding to accusations,
        missing the chance to redirect suspicion.
        """
        cases: list[CounterfactualCase] = []
        contexts = self._build_contexts(state)

        for player in state.players:
            ctx = contexts.get(player.id)
            if ctx is None:
                continue
            speeches = ctx.speech_events
            if len(speeches) < 2:
                continue

            # Detect repetition: same target mentioned 3+ times with no new evidence
            mention_counts: dict[str, list[int]] = defaultdict(list)
            for s in speeches:
                speech_text = s.payload.get("speech", "") or ""
                for other in state.players:
                    if other.name in speech_text:
                        mention_counts[other.name].append(s.day)

            for target_name, days in mention_counts.items():
                if len(days) >= 3 and len(set(days)) == len(days):
                    # Repeated mentions across different days — possible tunnel vision
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-speech-repeat-{player.id}-{target_name}",
                            game_id=state.id,
                            day=max(days),
                            phase="DAY_SPEECH",
                            counterfactual_type="speech_strategy",
                            original_decision=f"{player.name} repeatedly mentioned {target_name} across {len(days)} days without new evidence.",
                            alternative_decision=f"If {player.name} had diversified analysis targets or provided new reasoning, the discussion might uncover more signals.",
                            expected_effect="More diverse speech could help the village gather broader information.",
                            affected_players=[player.name, target_name],
                            confidence=0.65,
                            evidence=[
                                f"Mentioned {target_name} on days: {', '.join(str(d) for d in days)}.",
                                "No new evidence introduced across these mentions.",
                            ],
                            severity="moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, max(days), player.name, "speech"),
                            effect_type="estimated",
                            recomputed_outcome={"repeated_target": target_name, "mention_days": len(days)},
                            evidence_event_ids=[s.id for s in speeches[-3:]],
                        )
                    )
                    break  # One case per player

            # Detect: being accused but not responding
            accused_speeches = [
                s
                for s in state.events
                if s.type == EventType.CHAT_MESSAGE
                and player.name in (s.payload.get("speech", "") or "")
                and s.payload.get("actor_id") != player.id
            ]
            my_speeches_after_accusation = [
                s for s in speeches if s.day >= min((a.day for a in accused_speeches), default=0)
            ]
            if accused_speeches and not my_speeches_after_accusation:
                accuser = state.player(str(accused_speeches[0].payload.get("actor_id", "")))
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-speech-noreply-{player.id}",
                        game_id=state.id,
                        day=accused_speeches[0].day,
                        phase="DAY_SPEECH",
                        counterfactual_type="speech_strategy",
                        original_decision=f"{player.name} did not respond when {accuser.name} mentioned them.",
                        alternative_decision=f"If {player.name} had directly addressed {accuser.name}'s accusation, the table might reassess.",
                        expected_effect="Responding to accusations could reduce suspicion and provide more information.",
                        affected_players=[player.name, accuser.name],
                        confidence=0.60,
                        evidence=[
                            f"{accuser.name} mentioned {player.name} on day {accused_speeches[0].day}.",
                            f"{player.name} did not respond in subsequent speeches.",
                        ],
                        severity="moderate",
                        source_bad_case_id=self._find_bad_case_id(
                            bad_cases, accused_speeches[0].day, player.name, "speech"
                        ),
                        effect_type="estimated",
                        recomputed_outcome={"missed_response_to": accuser.name},
                        evidence_event_ids=[accused_speeches[0].id],
                    )
                )

            # ---- Speech-vote contradiction: said one thing, voted another ----
            votes_today = [e for e in ctx.vote_events if e.day == max((s.day for s in speeches), default=0)]
            for speech in speeches[-3:]:
                speech_text = speech.payload.get("speech", "") or ""
                for vote in votes_today:
                    if vote.day != speech.day:
                        continue
                    vote_target = (
                        state.player(str(vote.payload.get("target_id", ""))) if vote.payload.get("target_id") else None
                    )
                    if vote_target is None:
                        continue
                    # Check if speech defended someone but voted for them
                    defend_keywords = ["好人", "不像狼", "可信", "好人面", "好人牌", "平民", "金水"]
                    if any(kw in speech_text for kw in defend_keywords) and vote_target.name in speech_text:
                        cases.append(
                            CounterfactualCase(
                                case_id=f"{state.id}-speech-contra-{player.id}-D{speech.day}",
                                game_id=state.id,
                                day=speech.day,
                                phase="DAY_SPEECH",
                                counterfactual_type="speech_strategy",
                                original_decision=f"{player.name} defended {vote_target.name} in speech but voted to exile them on day {speech.day}.",
                                alternative_decision=f"If {player.name} had voted consistently with their speech, their credibility would be stronger.",
                                expected_effect="Speech-vote consistency is a key signal for village trust assessment.",
                                affected_players=[player.name, vote_target.name],
                                confidence=0.74,
                                evidence=[
                                    f'Speech: "{speech_text[:100]}..."',
                                    f"Voted to exile {vote_target.name} same day.",
                                ],
                                severity="moderate",
                                source_bad_case_id=self._find_bad_case_id(bad_cases, speech.day, player.name, "speech"),
                                effect_type="estimated",
                                recomputed_outcome={"contradiction": "speech_defended_voted_exile"},
                                evidence_event_ids=[speech.id, vote.id],
                            )
                        )
                        break  # One case per player per pattern

            # ---- Empty rhetoric: long speech with no event references ----
            for speech in speeches[-3:]:
                speech_text = speech.payload.get("speech", "") or ""
                if len(speech_text) > 80:
                    # Check for concrete references: player names, day numbers, roles
                    has_player_ref = any(p.name in speech_text for p in state.players if p.id != player.id)
                    has_role_ref = any(
                        role in speech_text for role in ["预言家", "女巫", "猎人", "守卫", "狼", "查验", "银水"]
                    )
                    has_vote_ref = any(kw in speech_text for kw in ["投票", "票型", "归票", "冲票"])
                    if not (has_player_ref or has_role_ref or has_vote_ref):
                        cases.append(
                            CounterfactualCase(
                                case_id=f"{state.id}-speech-empty-{player.id}-D{speech.day}",
                                game_id=state.id,
                                day=speech.day,
                                phase="DAY_SPEECH",
                                counterfactual_type="speech_strategy",
                                original_decision=f"{player.name}'s speech on day {speech.day} ({len(speech_text)} chars) lacked concrete references to players, roles, or votes.",
                                alternative_decision=f"If {player.name} had anchored their speech with specific player names and game events, it would be more persuasive and useful to the village.",
                                expected_effect="Factual, evidence-anchored speech is more persuasive and gives village better information.",
                                affected_players=[player.name],
                                confidence=0.55,
                                evidence=[
                                    f"Speech length: {len(speech_text)} chars, no player/role/vote references.",
                                ],
                                severity="minor",
                                source_bad_case_id=self._find_bad_case_id(bad_cases, speech.day, player.name, "speech"),
                                effect_type="estimated",
                                recomputed_outcome={"empty_rhetoric": True, "speech_length": len(speech_text)},
                                evidence_event_ids=[speech.id],
                            )
                        )
                        break  # One case per player

        return cases

    def _stance_flip_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
    ) -> list[CounterfactualCase]:
        """Stance flip counterfactuals — vote + speech patterns.

        From Ask WhAI §4: belief perturbation evaluation.
        What if the agent changed their stance on a player without clear justification?

        Detects: voting for someone previously defended, defending someone
        previously voted for, speech stance changes with no new events to explain.
        """
        cases: list[CounterfactualCase] = []
        contexts = self._build_contexts(state)

        for player in state.players:
            ctx = contexts.get(player.id)
            if ctx is None:
                continue

            # Get all votes by this player
            votes = [
                (event.day, str(event.payload.get("target_id", "")))
                for event in sorted(state.events, key=lambda e: e.ts)
                if event.type == EventType.VOTE_CAST and str(event.payload.get("voter_id", "")) == player.id
            ]

            # ---- Vote-based stance flip ----
            if len(votes) >= 2:
                vote_targets_by_day: dict[int, str] = {}
                for day, target_id in votes:
                    vote_targets_by_day[day] = target_id

                prev_days = sorted(vote_targets_by_day.keys())
                for i in range(1, len(prev_days)):
                    prev_day = prev_days[i - 1]
                    curr_day = prev_days[i]
                    prev_target = state.player(vote_targets_by_day[prev_day])
                    curr_target = state.player(vote_targets_by_day[curr_day])

                    new_info_about_prev = any(
                        e.type == EventType.PLAYER_DIED and e.payload.get("player_id") == prev_target.id
                        for e in state.events
                        if prev_day <= e.day <= curr_day
                    )
                    if new_info_about_prev:
                        continue

                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-stance-vote-{curr_day}-{player.id}",
                            game_id=state.id,
                            day=curr_day,
                            phase="DAY_VOTE",
                            counterfactual_type="stance_flip",
                            original_decision=f"{player.name} voted for {curr_target.name} on day {curr_day} after previously voting {prev_target.name} on day {prev_day}.",
                            alternative_decision=f"If {player.name} had maintained their stance or provided clear reasoning for the flip, the vote pattern would be more interpretable.",
                            expected_effect="Consistent voting patterns help the village track alignment and detect wolves.",
                            affected_players=[player.name, prev_target.name, curr_target.name],
                            confidence=0.68,
                            evidence=[
                                f"Voted {prev_target.name} day {prev_day}, then {curr_target.name} day {curr_day}.",
                                "No significant new information about the previous target emerged between these votes.",
                            ],
                            severity="moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, curr_day, player.name, "vote"),
                            effect_type="estimated",
                            recomputed_outcome={
                                "flip_type": "vote",
                                "flip_from": prev_target.id,
                                "flip_to": curr_target.id,
                            },
                            evidence_event_ids=[],
                        )
                    )
                    break  # One vote-flip case per player

            # ---- Speech-based stance flip: defended X on day N, accused X on day N+1 ----
            speeches = ctx.speech_events
            if len(speeches) >= 2:
                # Detect stance toward each other player across speeches
                accuse_keywords = ["狼", "可疑", "问题", "铁狼", "标狼", "不好", "出"]
                defend_keywords = ["好人", "不像狼", "可信", "好人面", "好人牌", "平民", "金水"]
                for other in state.players:
                    if other.id == player.id:
                        continue
                    # Track stance across days
                    stance_timeline: list[tuple[int, str]] = []  # (day, "accuse"|"defend")
                    for speech in sorted(speeches, key=lambda e: e.ts):
                        text = speech.payload.get("speech", "") or ""
                        if other.name not in text:
                            continue
                        if any(kw in text for kw in accuse_keywords):
                            stance_timeline.append((speech.day, "accuse"))
                        elif any(kw in text for kw in defend_keywords):
                            stance_timeline.append((speech.day, "defend"))
                    # Look for flips
                    for i in range(1, len(stance_timeline)):
                        prev_day, prev_stance = stance_timeline[i - 1]
                        curr_day, curr_stance = stance_timeline[i]
                        if prev_stance != curr_stance:
                            # Stance flip detected in speech
                            cases.append(
                                CounterfactualCase(
                                    case_id=f"{state.id}-stance-speech-{curr_day}-{player.id}-{other.id}",
                                    game_id=state.id,
                                    day=curr_day,
                                    phase="DAY_SPEECH",
                                    counterfactual_type="stance_flip",
                                    original_decision=f"{player.name} {prev_stance}ed {other.name} on day {prev_day} but {curr_stance}ed them on day {curr_day} in speech.",
                                    alternative_decision=f"If {player.name} had explained why their stance on {other.name} changed, the village could better assess the reasoning.",
                                    expected_effect="Explained stance changes provide information; unexplained flips cause confusion and suspicion.",
                                    affected_players=[player.name, other.name],
                                    confidence=0.60,
                                    evidence=[
                                        f"Day {prev_day}: {prev_stance}ed {other.name}.",
                                        f"Day {curr_day}: {curr_stance}ed {other.name}.",
                                    ],
                                    severity="minor",
                                    source_bad_case_id=self._find_bad_case_id(
                                        bad_cases, curr_day, player.name, "speech"
                                    ),
                                    effect_type="estimated",
                                    recomputed_outcome={
                                        "flip_type": "speech",
                                        "from_stance": prev_stance,
                                        "to_stance": curr_stance,
                                    },
                                    evidence_event_ids=[],
                                )
                            )
                            break  # One speech-flip case per (player, target) pair
                    else:
                        continue
                    break  # One case per player (combined vote+speech flips)
        return cases

    def _badge_election_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
        turning_points: Sequence[TurningPoint],
    ) -> list[CounterfactualCase]:
        """Badge election counterfactuals.

        What if the sheriff badge went to a different (better) player?
        The sheriff has 1.5 vote weight and controls speak order — a critical role.

        Detects: badge given to a wolf or to a player with low information value.
        """
        cases: list[CounterfactualCase] = []
        badge_holder_id = state.badge.holder_id
        if not badge_holder_id:
            return cases

        badge_player = state.player(badge_holder_id)

        # Case A: Badge went to a wolf
        if badge_player.alignment == Alignment.WOLF:
            # Find a good alternative: a surviving villager-side player who spoke well
            good_candidates = [
                p
                for p in state.players
                if p.alignment == Alignment.VILLAGE and p.role in {Role.SEER, Role.WITCH, Role.HUNTER} and p.alive
            ]
            if good_candidates:
                alt = good_candidates[0]
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-badge-wolf-{badge_player.id}",
                        game_id=state.id,
                        day=0,
                        phase="DAY_BADGE_ELECTION",
                        counterfactual_type="badge_election",
                        original_decision=f"The badge went to {badge_player.name}, who is a wolf.",
                        alternative_decision=f"If the badge had gone to {alt.name}({alt.role.value}) instead, village-side coordination might improve.",
                        expected_effect="Wolf-controlled badge gives the wolf team 1.5x vote weight and speak-order control.",
                        affected_players=[badge_player.name, alt.name],
                        confidence=0.75,
                        evidence=[
                            f"{badge_player.name}({badge_player.role.value}) is a wolf.",
                            f"{alt.name}({alt.role.value}) was a viable village-side candidate.",
                        ],
                        severity="major",
                        source_bad_case_id=self._find_bad_case_id(bad_cases, 0, "table", "badge"),
                        effect_type="estimated",
                        recomputed_outcome={"wolf_badge": True, "alternative_candidate": alt.id},
                        evidence_event_ids=[],
                    )
                )

        # Case B: Badge went to a player who died early without contributing
        if not badge_player.alive:
            death_day = next(
                (
                    e.day
                    for e in state.events
                    if e.type == EventType.PLAYER_DIED and e.payload.get("player_id") == badge_player.id
                ),
                99,
            )
            if death_day <= 2 and badge_player.alignment == Alignment.VILLAGE:
                surviving_goods = [
                    p for p in state.players if p.alignment == Alignment.VILLAGE and p.alive and p.id != badge_player.id
                ]
                if surviving_goods:
                    alt = surviving_goods[0]
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-badge-early-death-{badge_player.id}",
                            game_id=state.id,
                            day=death_day,
                            phase="DAY_RESOLVE",
                            counterfactual_type="badge_election",
                            original_decision=f"The badge went to {badge_player.name}, who died on day {death_day} without significant contribution.",
                            alternative_decision=f"If the badge had gone to a longer-surviving player like {alt.name}, badge continuity might improve.",
                            expected_effect="Early badge loss reduces village-side coordination for remaining days.",
                            affected_players=[badge_player.name, alt.name],
                            confidence=0.62,
                            evidence=[
                                f"{badge_player.name} died day {death_day}.",
                                f"Badge lost early — {len(state.players) - death_day} days without sheriff.",
                            ],
                            severity="moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, death_day, "table", "badge"),
                            effect_type="estimated",
                            recomputed_outcome={"early_badge_loss": True, "death_day": death_day},
                            evidence_event_ids=[],
                        )
                    )
        return cases

    # ---- claim_timing + coordination (2025 frontier: from RESERVED → ACTIVE) ----

    # Role claim keyword patterns (same as observe.py _detect_role_claim)
    _CLAIM_PATTERNS: list[tuple[str, str]] = [
        ("我是预言家", "Seer"),
        ("我是真预言家", "Seer"),
        ("我是女巫", "Witch"),
        ("我是猎人", "Hunter"),
        ("我是守卫", "Guard"),
        ("我是白痴", "Idiot"),
        ("我是村民", "Villager"),
        ("我是好人", "Villager"),
        ("我是平民", "Villager"),
        ("我跳预言家", "Seer"),
        ("我跳女巫", "Witch"),
        ("我跳猎人", "Hunter"),
        ("我跳守卫", "Guard"),
        ("我是神", "God"),
        ("我是神职", "God"),
        ("我是真预", "Seer"),
        ("我是单边预", "Seer"),
        ("银水是", "Witch"),
        ("救了", "Witch"),
        ("毒了", "Witch"),
        ("查了", "Seer"),
        ("查验", "Seer"),
        ("金水", "Seer"),
        ("查杀", "Seer"),
    ]

    def _detect_claim(self, speech_text: str) -> str | None:
        """Detect a role claim from speech text. Returns role name or None."""
        for pattern, role in self._CLAIM_PATTERNS:
            if pattern in speech_text:
                return role
        return None

    def _claim_timing_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
    ) -> list[CounterfactualCase]:
        """Claim timing counterfactuals — from RESERVED → ACTIVE.

        From Optimal Stopping Theory in Hidden Role Games (Li et al. 2025):
        Role claims have an optimal timing window. Claiming too early wastes
        information advantage; claiming too late loses influence opportunity.

        Detects:
          - Seer claiming wolf result before revealing role → information leak
          - Seer holding wolf check too long → missed vote influence
          - Witch revealing antidote usage too early → draws wolf fire prematurely
          - Villager fake-claiming god role → risks real god counter-claim
          - Wolf fake claims at suboptimal times (before/after critical events)
        """
        cases: list[CounterfactualCase] = []
        contexts = self._build_contexts(state)

        for player in state.players:
            ctx = contexts.get(player.id)
            if ctx is None:
                continue
            speeches = ctx.speech_events
            if not speeches:
                continue

            # Detect: when did this player first claim a role?
            first_claim_day: int | None = None
            claimed_role: str | None = None
            for s in sorted(speeches, key=lambda e: e.ts):
                text = s.payload.get("speech", "") or ""
                detected = self._detect_claim(text)
                if detected:
                    first_claim_day = s.day
                    claimed_role = detected
                    break

            if first_claim_day is None:
                continue  # No claim — not necessarily bad, skip

            # ---- Case A: Seer claimed role without having any wolf result ----
            if player.role == Role.SEER and claimed_role == "Seer":
                seer_checks = [e for e in ctx.private_info_events if e.payload.get("kind") == "seer_result"]
                has_wolf_result = any(e.payload.get("is_wolf") for e in seer_checks if e.day < first_claim_day)
                if not has_wolf_result and first_claim_day <= 1:
                    # Seer claimed too early — no wolf result to share
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-claim-early-seer-{player.id}",
                            game_id=state.id,
                            day=first_claim_day,
                            phase="DAY_SPEECH",
                            counterfactual_type="claim_timing",
                            original_decision=f"{player.name}(Seer) claimed Seer on day {first_claim_day} without having a wolf check result yet.",
                            alternative_decision=f"If {player.name} waited until day {first_claim_day + 1} after getting a night result, the claim would carry more credibility and information value.",
                            expected_effect="Delayed claim with evidence increases credibility and gives village actionable information.",
                            affected_players=[player.name],
                            confidence=0.72 if first_claim_day == 1 else 0.55,
                            evidence=[
                                f"Claimed Seer on day {first_claim_day}.",
                                f"No wolf check result available before claim (only {len(seer_checks)} checks done).",
                            ],
                            severity="moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, first_claim_day, player.name, "claim"),
                            effect_type="estimated",
                            recomputed_outcome={"claim_day": first_claim_day, "has_wolf_result": False},
                            evidence_event_ids=[],
                        )
                    )

                # Case B: Seer has wolf result but didn't claim until late
                if has_wolf_result:
                    wolf_check_days = [
                        e.day for e in seer_checks if e.payload.get("is_wolf") and e.day < first_claim_day
                    ]
                    if wolf_check_days and first_claim_day - max(wolf_check_days) >= 2:
                        # Held wolf info for 2+ days before claiming
                        cases.append(
                            CounterfactualCase(
                                case_id=f"{state.id}-claim-late-seer-{player.id}",
                                game_id=state.id,
                                day=first_claim_day,
                                phase="DAY_SPEECH",
                                counterfactual_type="claim_timing",
                                original_decision=f"{player.name}(Seer) waited until day {first_claim_day} to claim Seer, but had a wolf check from day {max(wolf_check_days)}.",
                                alternative_decision=f"If {player.name} had claimed Seer on day {max(wolf_check_days)} with the wolf result, the village could have aligned votes earlier.",
                                expected_effect=f"Earlier claim with evidence could prevent {first_claim_day - max(wolf_check_days)} days of village mis-coordination.",
                                affected_players=[player.name],
                                confidence=0.80,
                                evidence=[
                                    f"Wolf check result on day {max(wolf_check_days)}.",
                                    f"Claimed Seer only on day {first_claim_day} — {first_claim_day - max(wolf_check_days)} day delay.",
                                ],
                                severity="major",
                                source_bad_case_id=self._find_bad_case_id(
                                    bad_cases, first_claim_day, player.name, "claim"
                                ),
                                effect_type="estimated",
                                recomputed_outcome={"delay_days": first_claim_day - max(wolf_check_days)},
                                evidence_event_ids=[],
                            )
                        )

            # ---- Case C: Wolf fake-claimed a god role but real god is still alive ----
            if player.role in {Role.WEREWOLF, Role.WHITE_WOLF_KING} and claimed_role in {
                "Seer",
                "Witch",
                "Hunter",
                "Guard",
            }:
                real_god_alive = any(
                    p.role.value == claimed_role and p.alive and p.id != player.id for p in state.players
                )
                if real_god_alive and first_claim_day <= 2:
                    # Wolf fake-claimed while real god is alive — risky strategy
                    real_god = next((p for p in state.players if p.role.value == claimed_role and p.alive), None)
                    counter_claim_day = None
                    if real_god:
                        real_ctx = contexts.get(real_god.id)
                        if real_ctx:
                            for s in sorted(real_ctx.speech_events, key=lambda e: e.ts):
                                if self._detect_claim(s.payload.get("speech", "") or "") == claimed_role:
                                    counter_claim_day = s.day
                                    break
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-claim-wolf-fake-{player.id}",
                            game_id=state.id,
                            day=first_claim_day,
                            phase="DAY_SPEECH",
                            counterfactual_type="claim_timing",
                            original_decision=f"{player.name}(Wolf) fake-claimed {claimed_role} on day {first_claim_day} while real {claimed_role}({real_god.name if real_god else '?'}) was alive.",
                            alternative_decision=f"If {player.name} had claimed Villager instead, they would avoid a direct counter-claim from the real {claimed_role}.",
                            expected_effect=f"Fake-claiming while real god is alive risks immediate counter-claim exposure{' (which happened day ' + str(counter_claim_day) + ')' if counter_claim_day else ''}.",
                            affected_players=[player.name, real_god.name if real_god else "?"],
                            confidence=0.78 if counter_claim_day else 0.62,
                            evidence=[
                                f"Wolf player {player.name} claimed {claimed_role} on day {first_claim_day}.",
                                f"Real {claimed_role}: {real_god.name if real_god else 'unknown'} was alive.",
                            ]
                            + (
                                [f"Real {claimed_role} counter-claimed on day {counter_claim_day}."]
                                if counter_claim_day
                                else []
                            ),
                            severity="major" if counter_claim_day else "moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, first_claim_day, player.name, "claim"),
                            effect_type="estimated",
                            recomputed_outcome={"fake_claim": True, "counter_claimed": counter_claim_day is not None},
                            evidence_event_ids=[],
                        )
                    )

            # ---- Case D: Villager claimed god role (dangerous bluff) ----
            if player.role == Role.VILLAGER and claimed_role in {"Seer", "Witch", "Hunter", "Guard"}:
                real_god = next((p for p in state.players if p.role.value == claimed_role), None)
                if real_god is not None:
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-claim-villager-god-{player.id}",
                            game_id=state.id,
                            day=first_claim_day,
                            phase="DAY_SPEECH",
                            counterfactual_type="claim_timing",
                            original_decision=f"{player.name}(Villager) claimed {claimed_role} on day {first_claim_day}. Real {claimed_role} is {real_god.name}.",
                            alternative_decision=f"If {player.name} had stayed honest as Villager, the real {claimed_role} wouldn't need to waste time counter-claiming, and village information stays cleaner.",
                            expected_effect="Villager god-claiming pollutes the information space and can cause the real god to be misvoted.",
                            affected_players=[player.name, real_god.name],
                            confidence=0.70,
                            evidence=[
                                f"Villager {player.name} claimed {claimed_role}.",
                                f"Real {claimed_role}: {real_god.name}.",
                            ],
                            severity="moderate",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, first_claim_day, player.name, "claim"),
                            effect_type="estimated",
                            recomputed_outcome={"villager_fake_god": True},
                            evidence_event_ids=[],
                        )
                    )

        return cases

    def _coordination_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
        turning_points: Sequence[TurningPoint],
    ) -> list[CounterfactualCase]:
        """Wolf team coordination counterfactuals — from RESERVED → ACTIVE.

        From Multi-Agent Coalition Game Theory (Chen et al. 2025):
        Wolf team coordination is a cooperative game with imperfect information.
        Optimal wolf play requires vote alignment, consistent narratives, and
        coordinated night kills.

        Detects:
          - Wolf teammates voted for different targets on same day (vote split)
          - Wolf accused another wolf in speech (wolf infighting)
          - Night kill target misaligned with wolf team's day strategy
          - Wolf team missed a guaranteed win by not coordinating on same target
        """
        cases: list[CounterfactualCase] = []
        contexts = self._build_contexts(state)
        wolfs = [p for p in state.players if p.role in {Role.WEREWOLF, Role.WHITE_WOLF_KING}]
        if len(wolfs) < 2:
            return cases  # Need at least 2 wolves for coordination analysis

        wolf_ids = {w.id for w in wolfs}

        # ---- Case A: Wolf vote split on same day ----
        vote_by_day: dict[int, dict[str, str]] = defaultdict(dict)
        for event in state.events:
            if event.type != EventType.VOTE_CAST:
                continue
            voter = str(event.payload.get("voter_id", ""))
            if voter not in wolf_ids:
                continue
            target = str(event.payload.get("target_id", ""))
            vote_by_day[event.day][voter] = target

        for day, wolf_votes in vote_by_day.items():
            if len(wolf_votes) < 2:
                continue
            unique_targets = set(wolf_votes.values())
            if len(unique_targets) >= 2:
                # Wolves split their votes — coordination failure
                wolf_names = [state.player(wid).name for wid in wolf_votes]
                target_names = [state.player(tid).name for tid in unique_targets]
                # Check if this split cost them the vote
                all_votes = defaultdict(int)
                for event in state.events:
                    if event.type == EventType.VOTE_CAST and event.day == day:
                        all_votes[str(event.payload.get("target_id", ""))] += 1
                top_target = max(all_votes, key=all_votes.get, default="?")
                top_count = all_votes.get(top_target, 0)
                wolf_count = len(wolf_votes)
                # If wolves had united behind any one target, could they have changed the outcome?
                united_would_win = any(
                    all_votes.get(t, 0) + wolf_count - sum(1 for v in wolf_votes.values() if v == t) > top_count
                    for t in unique_targets
                )
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-coord-split-{day}",
                        game_id=state.id,
                        day=day,
                        phase="DAY_VOTE",
                        counterfactual_type="coordination",
                        original_decision=f"Wolf team split votes on day {day}: {', '.join(f'{state.player(w).name}→{state.player(t).name}' for w, t in wolf_votes.items())}.",
                        alternative_decision=f"If all wolves had coordinated on one target, they could {'have changed the vote outcome' if united_would_win else 'increase their voting power'}.",
                        expected_effect=f"United wolf voting{' would flip the exile result' if united_would_win else ' strengthens wolf voting bloc'}.",
                        affected_players=list(wolf_names),
                        confidence=0.85 if united_would_win else 0.65,
                        evidence=[
                            f"Day {day} wolf votes: {', '.join(f'{state.player(w).name}→{state.player(t).name}' for w, t in wolf_votes.items())}.",
                            f"Vote split across {len(unique_targets)} targets.",
                        ]
                        + (["United wolves could have changed the outcome."] if united_would_win else []),
                        severity="major" if united_would_win else "moderate",
                        source_bad_case_id=self._find_bad_case_id(bad_cases, day, wolf_names[0], "vote"),
                        effect_type="estimated" if not united_would_win else "exact",
                        recomputed_outcome={
                            "wolf_split": True,
                            "would_flip": united_would_win,
                            "targets": list(unique_targets),
                        },
                        evidence_event_ids=[],
                    )
                )

        # ---- Case B: Wolf-vs-wolf accusation (infighting) ----
        for wolf in wolfs:
            ctx = contexts.get(wolf.id)
            if ctx is None:
                continue
            for speech in ctx.speech_events:
                text = speech.payload.get("speech", "") or ""
                for other_wolf in wolfs:
                    if other_wolf.id == wolf.id:
                        continue
                    if other_wolf.name in text:
                        # Check if it's an accusation (not a defense)
                        accusation_keywords = ["狼", "不好", "可疑", "问题", "铁狼", "标狼", "出", "票", "查杀"]
                        is_accusation = any(kw in text for kw in accusation_keywords)
                        if is_accusation:
                            cases.append(
                                CounterfactualCase(
                                    case_id=f"{state.id}-coord-infight-{wolf.id}-{other_wolf.id}-D{speech.day}",
                                    game_id=state.id,
                                    day=speech.day,
                                    phase="DAY_SPEECH",
                                    counterfactual_type="coordination",
                                    original_decision=f"{wolf.name}(Wolf) accused wolf teammate {other_wolf.name} on day {speech.day}.",
                                    alternative_decision=f"If {wolf.name} had redirected suspicion to a villager instead of {other_wolf.name}, the wolf team would maintain better cover.",
                                    expected_effect="Wolf infighting reduces team coordination and exposes both wolves to village scrutiny.",
                                    affected_players=[wolf.name, other_wolf.name],
                                    confidence=0.82,
                                    evidence=[
                                        f'{wolf.name} accused {other_wolf.name}: "{text[:100]}..."',
                                        "Both are wolf teammates.",
                                    ],
                                    severity="major",
                                    source_bad_case_id=self._find_bad_case_id(
                                        bad_cases, speech.day, wolf.name, "speech"
                                    ),
                                    effect_type="estimated",
                                    recomputed_outcome={
                                        "wolf_infighting": True,
                                        "accuser": wolf.id,
                                        "accused": other_wolf.id,
                                    },
                                    evidence_event_ids=[speech.id],
                                )
                            )
                            break  # One case per wolf pair
                else:
                    continue
                break

        # ---- Case C: Night kill misaligned with wolf team day narrative ----
        for day in range(1, state.day + 1):
            night_kills = [
                e
                for e in state.events
                if e.type == EventType.NIGHT_ACTION
                and e.day == day
                and str(e.payload.get("action_type", "")) == "attack"
                and str(e.payload.get("actor_id", "")) in wolf_ids
            ]
            if not night_kills:
                continue
            kill_target = str(night_kills[0].payload.get("target_id", ""))
            kill_name = str(night_kills[0].payload.get("target_name", ""))
            kill_role = str(night_kills[0].payload.get("target_role", "")) or (
                state.player(kill_target).role.value if kill_target else "?"
            )

            # Check: did wolves vote for this person the previous day?
            prev_day_votes = [
                str(e.payload.get("target_id", ""))
                for e in state.events
                if e.type == EventType.VOTE_CAST and e.day == day and str(e.payload.get("voter_id", "")) in wolf_ids
            ]
            if prev_day_votes and kill_target not in prev_day_votes:
                # Wolves killed someone they didn't vote for — narrative inconsistency
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-coord-kill-misalign-{day}",
                        game_id=state.id,
                        day=day,
                        phase="NIGHT_WOLF_ACTION",
                        counterfactual_type="coordination",
                        original_decision=f"Wolves voted for {', '.join(set(state.player(t).name for t in prev_day_votes))} on day {day} but killed {kill_name}({kill_role}) that night.",
                        alternative_decision="If wolves had killed one of their day vote targets, the narrative consistency would be stronger.",
                        expected_effect="Kill-vote misalignment creates a detectable pattern that skilled players can use to identify wolves.",
                        affected_players=[state.player(wid).name for wid in wolf_ids],
                        confidence=0.70,
                        evidence=[
                            f"Day {day} wolf votes: {', '.join(set(state.player(t).name for t in prev_day_votes))}.",
                            f"Night {day} kill: {kill_name}({kill_role}).",
                        ],
                        severity="moderate",
                        source_bad_case_id=self._find_bad_case_id(bad_cases, day, kill_name, "night"),
                        effect_type="estimated",
                        recomputed_outcome={"kill_vote_misalignment": True},
                        evidence_event_ids=[night_kills[0].id],
                    )
                )

        return cases

    # ---- Shared Helpers (used by counterfactual analysis methods) ----

    def _build_contexts(self, state: GameState) -> dict[str, _PlayerContext]:
        """Build per-player event contexts for counterfactual analysis."""
        contexts = {player.id: _PlayerContext(player=player) for player in state.players}
        for event in state.events:
            payload = event.payload
            if event.type == EventType.VOTE_CAST:
                voter_id = payload.get("voter_id")
                if voter_id in contexts:
                    contexts[voter_id].vote_events.append(event)
            elif event.type == EventType.CHAT_MESSAGE:
                actor_id = payload.get("actor_id")
                if actor_id in contexts:
                    contexts[actor_id].speech_events.append(event)
            elif event.type == EventType.NIGHT_ACTION:
                actor_id = payload.get("actor_id")
                if actor_id in contexts:
                    contexts[actor_id].night_action_events.append(event)
            elif event.type == EventType.PLAYER_DIED:
                player_id = payload.get("player_id")
                if player_id in contexts:
                    contexts[player_id].death_events.append(event)
            elif hasattr(EventType, "PRIVATE_INFO") and event.type == EventType.PRIVATE_INFO:
                for pid in getattr(event, "visible_to", []):
                    if pid in contexts:
                        contexts[pid].private_info_events.append(event)
        return contexts

    def _released_check_targets(self, ctx: _PlayerContext) -> set[str]:
        """Find seer check targets that were publicly mentioned in speeches."""
        released: set[str] = set()
        for check in ctx.private_info_events:
            target_name = str(check.payload.get("target_name") or "")
            if not target_name:
                continue
            for speech in ctx.speech_events:
                if target_name in (speech.payload.get("speech", "") or ""):
                    released.add(target_name)
                    break
        return released

    def _first_speech_day(self, ctx: _PlayerContext) -> int | None:
        """Find the first day this player made a public speech."""
        for event in sorted(ctx.speech_events, key=lambda e: e.ts):
            return event.day
        return None

    def _target_player(self, state: GameState, event: GameEvent) -> Player | None:
        """Extract the target player from an event."""
        target_id = str(event.payload.get("target_id", ""))
        if not target_id:
            return None
        try:
            return state.player(target_id)
        except Exception:
            return None

    @staticmethod
    def _target_player_by_id(state: GameState, player_id: str) -> Player | None:
        """Look up a player by ID, returning None if not found."""
        try:
            return state.player(player_id)
        except Exception:
            return None

    def _died_by_reason(self, state: GameState, player_id: str, reason: str, day: int | None = None) -> bool:
        """Check if a player died for a specific reason."""
        for event in state.events:
            if event.type != EventType.PLAYER_DIED:
                continue
            if str(event.payload.get("player_id", "")) != player_id:
                continue
            if event.payload.get("reason", "") != reason:
                continue
            if day is not None and event.day != day:
                continue
            return True
        return False

    @staticmethod
    def _is_llm_decision(
        case: CounterfactualCase,
        state: GameState,
        llm_player_ids: set[str],
    ) -> bool:
        """Check if a counterfactual case involves an LLM (not heuristic) decision.

        A case is valid for LLM analysis if:
        1. The primary affected player is an LLM agent, AND
        2. The event payload doesn't indicate a heuristic fallback.
        """
        # Check primary affected player
        for name in case.affected_players[:1]:
            player = next((p for p in state.players if p.name == name), None)
            if player is not None and player.id not in llm_player_ids:
                return False

        # Check evidence events for fallback flags
        for event_id in case.evidence_event_ids:
            event = next((e for e in state.events if e.id == event_id), None)
            if event is None:
                continue
            payload = event.payload or {}
            if payload.get("agent_fallback") is True:
                return False
            src = str(payload.get("agent_source", "")).lower()
            if src in ("heuristic", "heuristic_fallback", "fallback"):
                return False

        return True

    def _find_pivot_vote(
        self,
        ordered_votes: Sequence[GameEvent],
        exiled_id: str,
        wolf_target_id: str,
    ) -> GameEvent | None:
        counts: dict[str, int] = defaultdict(int)
        pivot: GameEvent | None = None
        for event in ordered_votes:
            target_id = str(event.payload.get("target_id"))
            before_gap = counts.get(exiled_id, 0) - counts.get(wolf_target_id, 0)
            counts[target_id] += 1
            after_gap = counts.get(exiled_id, 0) - counts.get(wolf_target_id, 0)
            if target_id == exiled_id and after_gap >= 1 and before_gap <= 0:
                pivot = event
        return pivot

    def _recompute_vote_flip(
        self,
        ordered_votes: Sequence[GameEvent],
        voter_id: str,
        new_target_id: str,
        original_exile_id: str,
    ) -> dict[str, Any]:
        """B §13.1 exact_recalculation: swap one vote, recount the tally,
        report the new exile (highest count, ties broken alphabetically — same
        as engine ResolutionEngine convention). Returns dict for evidence."""
        tally: dict[str, int] = defaultdict(int)
        for event in ordered_votes:
            actual_voter = str(event.payload.get("voter_id"))
            actual_target = str(event.payload.get("target_id"))
            effective_target = new_target_id if actual_voter == voter_id else actual_target
            tally[effective_target] += 1
        if not tally:
            return {"new_tally": {}, "new_exile": None, "outcome_changed": False}
        max_votes = max(tally.values())
        candidates = sorted(tid for tid, count in tally.items() if count == max_votes)
        new_exile = candidates[0]
        return {
            "new_tally": dict(tally),
            "new_exile": new_exile,
            "original_exile": original_exile_id,
            "outcome_changed": new_exile != original_exile_id,
            "method": "exact_recalculation",
        }

    def _find_bad_case_id(
        self,
        bad_cases: Sequence[BadCaseReport],
        day: int | None,
        player_name: str,
        mistake_type: str,
    ) -> str | None:
        for report in bad_cases:
            if report.day == day and report.player_name == player_name and report.mistake_type == mistake_type:
                return f"{report.game_id}-{report.day}-{report.player_name}-{report.mistake_type}"
        return None

    def _find_turning_point_id(
        self,
        turning_points: Sequence[TurningPoint],
        day: int | None,
        keyword: str,
    ) -> str | None:
        for index, point in enumerate(turning_points, start=1):
            if point.day == day and keyword in point.description:
                return f"turning-point-{index}"
        return None

    def _build_contexts(self, state: GameState) -> dict[str, _PlayerContext]:
        contexts = {player.id: _PlayerContext(player=player) for player in state.players}
        for event in state.events:
            payload = event.payload
            if event.type == EventType.CHAT_MESSAGE:
                actor_id = payload.get("actor_id")
                if actor_id in contexts:
                    contexts[actor_id].speech_events.append(event)
            elif event.type == EventType.PRIVATE_INFO:
                for player_id in event.visible_to:
                    if player_id in contexts:
                        contexts[player_id].private_info_events.append(event)
        return contexts

    def _released_check_targets(self, ctx: _PlayerContext) -> set[str]:
        released_targets: set[str] = set()
        for payload in [
            event.payload for event in ctx.private_info_events if event.payload.get("kind") == "seer_result"
        ]:
            target_name = str(payload.get("target_name") or "")
            if not target_name:
                continue
            if any(target_name in str(event.payload.get("speech", "")) for event in ctx.speech_events):
                released_targets.add(target_name)
        return released_targets

    def _first_speech_day(self, ctx: _PlayerContext) -> int | None:
        if not ctx.speech_events:
            return None
        return min(event.day for event in ctx.speech_events)

    def _target_player(self, state: GameState, event: GameEvent) -> Player | None:
        target_id = event.payload.get("target_id")
        if not target_id:
            return None
        return state.player(str(target_id))

    def _died_by_reason(self, state: GameState, player_id: str, reason: str, day: int | None = None) -> bool:
        return any(
            event.type == EventType.PLAYER_DIED
            and event.payload.get("player_id") == player_id
            and event.payload.get("reason") == reason
            and (day is None or event.day == day)
            for event in state.events
        )


class MarkdownReportRenderer:
    """Renders a structured review report into markdown."""

    def render(self, report: ReviewReport, *, evaluation_result: ReportEvaluationResult | None = None) -> str:
        winning_reason = report.metadata.get("winner_reasoning") or report.game_summary
        lines = [
            "# 本局复盘报告",
            "",
            "## 1. 本局概览",
            f"- 胜方：{ALIGNMENT_LABELS.get(report.winner or '', report.winner)}",
            f"- 对局天数：{report.total_days} 天",
            f"- 核心总结：{winning_reason}",
        ]
        if evaluation_result is not None:
            status = "通过" if evaluation_result.grade == "pass" else "未通过"
            lines.append(f"- 报告审核：{status}（评分 {evaluation_result.score:.2f}）")
        lines.extend(["", "## 2. MVP"])
        for item in report.mvp_results:
            lines.append(
                f"- {MVP_TYPE_LABELS.get(item.mvp_type, item.mvp_type)}：{item.player_name}"
                f"（{ROLE_LABELS.get(item.role, item.role)}，{ALIGNMENT_LABELS.get(item.alignment, item.alignment)}），"
                f"分数={item.mvp_score}，理由={self._zh_text(item.reason)}"
            )
        lines.extend(
            [
                "",
                "## 3. 玩家评分榜",
                "",
                "| 排名 | 玩家 | 角色 | 阵营 | 硬规则分 | 复盘加权 | 最终分 |",
                "| --- | --- | --- | --- | ---: | ---: | ---: |",
            ]
        )
        for entry in report.scoreboard:
            delta = round(entry["adjusted_final_score"] - entry["rule_score"], 2)
            lines.append(
                f"| {entry['rank']} | {entry['player_name']} | {ROLE_LABELS.get(entry['role'], entry['role'])} | "
                f"{ALIGNMENT_LABELS.get(entry['alignment'], entry['alignment'])} | {entry['rule_score']} | {delta} | {entry['adjusted_final_score']} |"
            )
        lines.extend(["", "## 4. 关键转折点"])
        if report.turning_points:
            for point in report.turning_points:
                evidence = "；".join(self._zh_text(item) for item in point.evidence[:2]) if point.evidence else "无"
                lines.append(
                    f"- 第 {point.day} 天 {PHASE_LABELS.get(point.phase or '', point.phase or '')}：{self._zh_text(point.title)}。"
                    f"影响值 {point.impact}。说明：{self._zh_text(point.description)}。证据：{evidence}"
                )
        else:
            lines.append("- 暂无关键转折点。")
        lines.extend(["", "## 5. 反事实推演"])
        if report.counterfactuals:
            for item in report.counterfactuals:
                lines.append(
                    f"- 第 {item.day} 天 {PHASE_LABELS.get(item.phase or '', item.phase or '')}"
                    f"（{COUNTERFACTUAL_TYPE_LABELS.get(item.counterfactual_type, item.counterfactual_type)}）："
                    f"原决策为“{self._zh_text(item.original_decision)}”。"
                    f"如果改为“{self._zh_text(item.alternative_decision)}”，"
                    f"预期会带来“{self._zh_text(item.expected_effect)}”。"
                    f"置信度 {item.confidence}。"
                )
        else:
            lines.append("- 本局没有检测到高置信度的反事实案例。")
        lines.extend(["", "## 6. 玩家逐个复盘"])
        for review in report.player_reviews:
            lines.append(
                f"### {review.rank}. {review.player_name}（{ROLE_LABELS.get(review.role, review.role)}，{ALIGNMENT_LABELS.get(review.alignment, review.alignment)}）"
            )
            lines.append(f"- 整体评价：{review.overall_summary}")
            delta = round(review.adjusted_final_score - review.rule_score, 2)
            lines.append(
                f"- 分数概览：硬规则分 {review.rule_score:.2f}，复盘加权 {delta:+.2f}，最终分 {review.adjusted_final_score:.2f}。"
            )
            # Show the outcome-vs-process split so wolf-win inflation is visible.
            if review.process_score or review.outcome_bonus:
                lines.append(
                    f"- 过程/胜负分解：过程分 {review.process_score:.2f}（决策合理性，不含胜负）"
                    f" + 胜负加成 {review.outcome_bonus:.2f}（阵营是否取胜）。"
                )
            lines.append(f"- 得分解读：{review.score_summary}")
            lines.extend(["", "  硬规则得分分解", "", "| 维度 | 说明 |", "| --- | --- |"])
            for item in review.rule_score_reasons or ["无"]:
                label, desc = self._split_reason(item)
                lines.append(f"| {label} | {desc} |")
            lines.extend(["", "  复盘加减分", "", "| 类别 | 分值 | 说明 |", "| --- | ---: | --- |"])
            if review.adjustment_reasons:
                for item in review.adjustment_reasons:
                    label, value, desc = self._split_adjustment(item)
                    lines.append(f"| {label} | {value} | {desc} |")
            else:
                lines.append("| 无 | 0.00 | 本局没有额外的复盘加分或扣分。 |")
            lines.append(
                f"- 主要亮点：{'；'.join(self._zh_text(item) for item in review.highlights[:3]) if review.highlights else '无'}"
            )
            lines.append(
                f"- 主要问题：{'；'.join(self._zh_text(item) for item in review.mistakes[:2]) if review.mistakes else '无'}"
            )
            if review.suggestions:
                lines.append(f"- 下一局建议：{'；'.join(self._zh_text(item) for item in review.suggestions[:2])}")
            else:
                lines.append("- 下一局建议：本局无明显复盘建议。")
        lines.extend(["", "## 7. 关键失误"])
        if report.bad_cases:
            for case in report.bad_cases:
                lines.append(
                    f"- 第 {case.day} 天，{case.player_name}（{ROLE_LABELS.get(case.role, case.role)}），"
                    f"{SEVERITY_LABELS.get(case.severity, case.severity)}：{self._zh_text(case.description)}。"
                    f"建议：{self._zh_text(case.suggested_fix)}"
                )
        else:
            lines.append("- 暂无关键失误。")
        lines.extend(["", "## 8. 策略建议", "", "### 本局复盘建议"])
        game_specific = [item for item in report.strategy_suggestions if item.metadata.get("scope") == "game_specific"]
        reusable = [item for item in report.strategy_suggestions if item.metadata.get("scope") != "game_specific"]
        if game_specific:
            for item in game_specific:
                lines.append(
                    f"- [{SEVERITY_LABELS.get(item.priority, item.priority)}] {self._zh_text(item.suggestion)}"
                )
        else:
            lines.append("- 暂无本局复盘建议。")
        lines.extend(["", "### 可复用策略建议"])
        if reusable:
            for item in reusable:
                lines.append(
                    f"- [{SEVERITY_LABELS.get(item.priority, item.priority)}] "
                    f"{ROLE_LABELS.get(item.target, item.target) if item.target_type == 'role' else '全局'}：{self._zh_text(item.suggestion)}"
                )
        else:
            lines.append("- 暂无可复用策略建议。")
        lines.extend(
            [
                "",
                "## 9. 说明",
                f"- {report.metadata.get('leaderboard_note', '跨局表现请查看 Leaderboard 输出，本报告仅针对当前单局。')}",
            ]
        )
        return "\n".join(lines)

    def _zh_text(self, text: str) -> str:
        return ReviewReportBuilder()._zh_text(text)

    def _split_reason(self, text: str) -> tuple[str, str]:
        if "：" in text:
            label, desc = text.split("：", 1)
            return label.strip(), self._zh_text(desc.strip())
        if ":" in text:
            label, desc = text.split(":", 1)
            return label.strip(), self._zh_text(desc.strip())
        return "说明", self._zh_text(text)

    def _split_adjustment(self, text: str) -> tuple[str, str, str]:
        value = "0.00"
        label = "复盘加减分"
        desc = self._zh_text(text)
        if "：" in text:
            prefix, raw_desc = text.split("：", 1)
            desc = self._zh_text(raw_desc.strip())
            if prefix.strip():
                label = prefix.strip()
                parts = prefix.strip().split(" ", 1)
                if len(parts) == 2 and parts[1]:
                    value = parts[1].replace("+", "")
        elif ":" in text:
            prefix, raw_desc = text.split(":", 1)
            desc = self._zh_text(raw_desc.strip())
            if prefix.strip():
                label = prefix.strip()
        return label, value, desc


class MockReviewLLM:
    """Mock reviewer model that rewrites with deterministic rule-based cleanup.

    This keeps the evaluator-optimizer workflow testable without a real LLM.
    """

    def generate(self, report: ReviewReport, draft: str, feedback: str = "") -> str:
        renderer = MarkdownReportRenderer()
        text = renderer.render(report)
        if feedback:
            # Re-render from facts instead of editing ad hoc text to avoid drifting from source facts.
            text = renderer.render(report)
        return text


class ReportGenerator:
    """Generates moderator-style markdown from a structured review report.

    LangGraph is intentionally not required here. If the project adds `langgraph`
    later, this class can be used as the `generate_report` node body.
    """

    def __init__(
        self,
        renderer: MarkdownReportRenderer | None = None,
        review_llm: MockReviewLLM | None = None,
    ) -> None:
        self.renderer = renderer or MarkdownReportRenderer()
        self.review_llm = review_llm or MockReviewLLM()

    def generate(self, report: ReviewReport, feedback: str = "") -> str:
        base = self.renderer.render(report)
        return self.review_llm.generate(report, base, feedback)


class ReviewQualityChecker:
    """Final non-LLM hard-rule gate for review markdown."""

    required_sections = [
        "# 本局复盘报告",
        "## 1. 本局概览",
        "## 2. MVP",
        "## 3. 玩家评分榜",
        "## 4. 关键转折点",
        "## 5. 反事实推演",
        "## 6. 玩家逐个复盘",
        "## 7. 关键失误",
        "## 8. 策略建议",
    ]

    banned_tokens = [
        "global_mvp",
        "winning_camp_mvp",
        "DAY_SPEECH",
        "DAY_VOTE",
        "checked-good player",
    ]

    def check(self, report: ReviewReport, markdown: str) -> ReportEvaluationResult:
        issues: list[str] = []
        fixes: list[str] = []
        for section in self.required_sections:
            if section not in markdown:
                issues.append(f"缺少章节：{section}")
                fixes.append(f"补全章节 {section}")
        for token in self.banned_tokens:
            if token in markdown:
                issues.append(f"出现英文枚举：{token}")
                fixes.append("移除英文枚举并改为中文")
        if "阵营结果分" in markdown or "角色任务分" in markdown or "投票分 0." in markdown:
            issues.append("仍包含调试式子分数展开")
            fixes.append("改为自然语言得分总结")
        for item in report.mvp_results:
            if item.player_name not in markdown:
                issues.append(f"MVP 玩家缺失：{item.player_name}")
                fixes.append("保留原始 MVP 事实")
        for entry in report.scoreboard[:3]:
            if str(entry["adjusted_final_score"]) not in markdown:
                issues.append(f"评分榜事实缺失：{entry['player_name']} 最终分")
                fixes.append("保留评分榜中的原始分数")
        grade = "pass" if not issues else "fail"
        score = max(0.0, 1.0 - 0.1 * len(issues))
        return ReportEvaluationResult(
            grade=grade,
            score=score,
            issues=issues,
            feedback="；".join(issues) if issues else "报告通过最终质量门。",
            required_fixes=fixes,
        )


class ReportEvaluator:
    """Audits generated markdown without changing report facts."""

    required_sections = ReviewQualityChecker.required_sections
    banned_tokens = ReviewQualityChecker.banned_tokens
    banned_token_patterns = [
        r"\bSeer\b",
        r"\bWerewolf\b",
        r"\bWitch\b",
        r"\bHunter\b",
        r"\bGuard\b",
        r"\bVillager\b",
        r"\bvillage\b",
        r"\bwolf\b",
    ]
    templated_suggestions = [
        "减少低置信度跟票",
        "发言更明确",
        "需要收紧投票纪律",
    ]

    def evaluate(self, report: ReviewReport, markdown: str) -> ReportEvaluationResult:
        issues: list[str] = []
        fixes: list[str] = []
        for section in self.required_sections:
            if section not in markdown:
                issues.append(f"缺少必需章节：{section}")
                fixes.append(f"补全 {section}")
        for token in self.banned_tokens:
            if token in markdown:
                issues.append(f"仍含英文枚举或英文角色：{token}")
                fixes.append("统一改成中文展示")
                break
        if not issues:
            for pattern in self.banned_token_patterns:
                if re.search(pattern, markdown):
                    issues.append(f"仍含英文枚举或英文角色：{pattern}")
                    fixes.append("统一改成中文展示")
                    break
        for phrase in self.templated_suggestions:
            if phrase in markdown:
                issues.append("存在模板化建议")
                fixes.append("建议必须改成具体、证据驱动的复盘建议")
                break
        if (
            "## Persona Leaderboard" in markdown
            or "## Role Leaderboard" in markdown
            or "## Version Leaderboard" in markdown
        ):
            issues.append("错误嵌入完整 Leaderboard")
            fixes.append("移除跨局排行榜正文，只保留单局说明")
        for review in report.player_reviews:
            if (
                not review.suggestions
                and f"{review.player_name}（" in markdown
                and "下一局建议：本局无明显复盘建议。" not in markdown
            ):
                issues.append(f"{review.player_name} 的无建议状态表达不一致")
                fixes.append("无明确问题时明确写出本局无明显复盘建议")
                break
        evidence_suggestions = [
            item for item in report.strategy_suggestions if not item.metadata.get("evidence_summary")
        ]
        if evidence_suggestions:
            issues.append("存在无证据策略建议")
            fixes.append("所有策略建议都要带 evidence_summary")
        for bonus in report.metadata.get("source_metadata", {}).get("review_bonuses", []):
            pass
        score = max(0.0, 1.0 - 0.12 * len(issues))
        return ReportEvaluationResult(
            grade="pass" if not issues else "fail",
            score=score,
            issues=issues,
            feedback="；".join(issues) if issues else "审核通过。",
            required_fixes=fixes,
        )


class ReportOptimizer:
    """Evaluator-optimizer loop for report polishing.

    This is implemented as a plain Python workflow to avoid introducing
    `langgraph` as a hard dependency. The state object is intentionally shaped
    so it can map directly onto a future `StateGraph`.
    """

    def __init__(
        self,
        generator: ReportGenerator | None = None,
        evaluator: ReportEvaluator | None = None,
        quality_checker: ReviewQualityChecker | None = None,
    ) -> None:
        self.generator = generator or ReportGenerator()
        self.evaluator = evaluator or ReportEvaluator()
        self.quality_checker = quality_checker or ReviewQualityChecker()

    def optimize(
        self,
        report: ReviewReport,
        *,
        review_context: dict[str, Any] | None = None,
        max_iterations: int = 2,
    ) -> ReportOptimizationState:
        state = ReportOptimizationState(
            game_id=report.game_id,
            review_report=report,
            review_context=review_context or {},
            max_iterations=max_iterations,
        )
        feedback = ""
        while True:
            state.iteration += 1
            state.draft_markdown = self.generator.generate(report, feedback)
            state.evaluator_result = self.evaluator.evaluate(report, state.draft_markdown)
            state.feedback_history.append(state.evaluator_result)
            if state.evaluator_result.grade == "pass" or state.iteration >= state.max_iterations:
                evaluator_passed = state.evaluator_result.grade == "pass"
                final_gate = self.quality_checker.check(report, state.draft_markdown)
                state.feedback_history.append(final_gate)
                state.final_markdown = state.draft_markdown
                state.quality_passed = final_gate.grade == "pass" and evaluator_passed
                state.evaluator_result = final_gate
                return state
            feedback = state.evaluator_result.feedback


def export_review_report(
    report: ReviewReport,
    *,
    json_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
    renderer: MarkdownReportRenderer | None = None,
) -> dict[str, Any]:
    payload = report.to_dict()
    if json_path is not None:
        Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if markdown_path is not None:
        rendered = (renderer or MarkdownReportRenderer()).render(report)
        Path(markdown_path).write_text(rendered, encoding="utf-8")
    return payload


class LeaderboardAggregator:
    """Aggregates cross-game leaderboard views from metrics or review reports."""

    def aggregate_persona(
        self,
        items: Sequence[GameMetrics | ReviewReport],
    ) -> LeaderboardResult:
        records, source_games = self._extract_records(items)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            key = record["persona_id"] or record["persona_name"] or record["player_id"]
            grouped[str(key)].append(record)

        role_global_avg = self._role_global_adjusted_avg(records)
        entries: list[LeaderboardEntry] = []
        for key, bucket in grouped.items():
            role_buckets: dict[str, list[float]] = defaultdict(list)
            for record in bucket:
                role_buckets[record["role"]].append(record["adjusted_final_score"])
            role_normalized_components = [
                (sum(values) / len(values)) - role_global_avg[role] for role, values in role_buckets.items()
            ]
            best_role = max(role_buckets.items(), key=lambda item: sum(item[1]) / len(item[1]))[0]
            weak_role = min(role_buckets.items(), key=lambda item: sum(item[1]) / len(item[1]))[0]
            entries.append(
                self._build_entry(
                    "persona",
                    key,
                    bucket[0]["persona_name"] or bucket[0]["player_name"],
                    bucket,
                    role_normalized_score=round(sum(role_normalized_components) / len(role_normalized_components), 4)
                    if role_normalized_components
                    else None,
                    best_role=best_role,
                    weak_role=weak_role,
                )
            )
        entries.sort(key=lambda item: (item.avg_adjusted_final_score, item.role_normalized_score or 0.0), reverse=True)
        return self._result("persona", entries, source_games, {"dimension": "persona"})

    def aggregate_role(
        self,
        items: Sequence[GameMetrics | ReviewReport],
    ) -> LeaderboardResult:
        records, source_games = self._extract_records(items)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[record["role"]].append(record)

        entries = [
            self._build_entry(
                "role",
                role,
                role,
                bucket,
                metadata={
                    "avg_role_task_score": round(sum(item["role_task_score"] for item in bucket) / len(bucket), 4),
                    "mistake_count": sum(len(item["mistakes"]) for item in bucket),
                    "personas": sorted({item["persona_name"] or item["player_name"] for item in bucket}),
                },
            )
            for role, bucket in grouped.items()
        ]
        entries.sort(key=lambda item: item.avg_adjusted_final_score, reverse=True)
        return self._result("role", entries, source_games, {"dimension": "role"})

    def aggregate_version(
        self,
        items: Sequence[GameMetrics | ReviewReport],
    ) -> LeaderboardResult:
        records, source_games = self._extract_records(items)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        version_game_counterfactuals: dict[str, list[int]] = defaultdict(list)
        for record in records:
            version = record.get("strategy_version") or record.get("agent_version") or "v0"
            grouped[str(version)].append(record)
        for game in items:
            version = self._item_version(game)
            version_game_counterfactuals[version].append(self._item_counterfactual_count(game))

        entries: list[LeaderboardEntry] = []
        for version, bucket in grouped.items():
            avg_counterfactual_count = 0.0
            if version_game_counterfactuals[version]:
                avg_counterfactual_count = sum(version_game_counterfactuals[version]) / len(
                    version_game_counterfactuals[version]
                )
            entries.append(
                self._build_entry(
                    "version",
                    version,
                    version,
                    bucket,
                    metadata={
                        "avg_counterfactual_count": round(avg_counterfactual_count, 4),
                    },
                )
            )
        entries.sort(key=lambda item: (item.win_rate, item.avg_adjusted_final_score), reverse=True)
        return self._result("version", entries, source_games, {"dimension": "strategy_version"})

    def aggregate_all(
        self,
        items: Sequence[GameMetrics | ReviewReport],
    ) -> dict[str, LeaderboardResult]:
        return {
            "persona": self.aggregate_persona(items),
            "role": self.aggregate_role(items),
            "version": self.aggregate_version(items),
        }

    def _extract_records(
        self,
        items: Sequence[GameMetrics | ReviewReport],
    ) -> tuple[list[dict[str, Any]], int]:
        records: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, GameMetrics):
                version = self._item_version(item)
                for score in item.player_scores:
                    records.append(self._score_to_record(item.game_id, score, version))
            else:
                version = self._item_version(item)
                payload_scores = list(item.metadata.get("player_scores", []))
                for score in payload_scores:
                    records.append(self._score_payload_to_record(item.game_id, score, version))
        return records, len(items)

    def _score_to_record(self, game_id: str, score: PlayerScore, version: str) -> dict[str, Any]:
        return {
            "game_id": game_id,
            "player_id": score.player_id,
            "player_name": score.player_name,
            "persona_id": score.persona_id,
            "persona_name": score.persona_name,
            "role": score.role,
            "alignment": score.alignment,
            "camp_result_score": score.camp_result_score,
            "final_score": score.final_score,
            "adjusted_final_score": score.adjusted_final_score
            if score.adjusted_final_score is not None
            else score.final_score,
            "vote_score": score.vote_score,
            "speech_score": score.speech_score,
            "skill_score": score.skill_score,
            "survival_score": score.survival_score,
            "role_task_score": score.role_task_score,
            "impact_bonus": score.impact_bonus,
            "semantic_bonus": score.semantic_highlight_bonus,
            "mistakes": list(score.mistakes),
            "strategy_version": version,
            "agent_version": version,
        }

    def _score_payload_to_record(self, game_id: str, score: dict[str, Any], version: str) -> dict[str, Any]:
        return {
            "game_id": game_id,
            "player_id": score.get("player_id"),
            "player_name": score.get("player_name"),
            "persona_id": score.get("persona_id"),
            "persona_name": score.get("persona_name"),
            "role": score.get("role"),
            "alignment": score.get("alignment"),
            "camp_result_score": score.get("camp_result_score", 0.0),
            "final_score": score.get("final_score", 0.0),
            "adjusted_final_score": score.get("adjusted_final_score", score.get("final_score", 0.0)),
            "vote_score": score.get("vote_score", 0.0),
            "speech_score": score.get("speech_score", 0.0),
            "skill_score": score.get("skill_score", 0.0),
            "survival_score": score.get("survival_score", 0.0),
            "role_task_score": score.get("role_task_score", 0.0),
            "impact_bonus": score.get("impact_bonus", 0.0),
            "semantic_bonus": score.get("semantic_highlight_bonus", 0.0),
            "mistakes": list(score.get("mistakes", [])),
            "strategy_version": version,
            "agent_version": version,
        }

    def _build_entry(
        self,
        leaderboard_type: str,
        key: str,
        display_name: str,
        bucket: Sequence[dict[str, Any]],
        *,
        role_normalized_score: float | None = None,
        best_role: str | None = None,
        weak_role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LeaderboardEntry:
        wins = sum(1 for item in bucket if item["camp_result_score"] >= 1.0)
        critical_mistakes = sum(
            1 for item in bucket for mistake in item["mistakes"] if str(mistake).startswith("[critical]")
        )
        return LeaderboardEntry(
            leaderboard_type=leaderboard_type,
            key=key,
            display_name=display_name,
            games_played=len(bucket),
            wins=wins,
            win_rate=round(wins / len(bucket), 4),
            avg_final_score=round(sum(item["final_score"] for item in bucket) / len(bucket), 4),
            avg_adjusted_final_score=round(sum(item["adjusted_final_score"] for item in bucket) / len(bucket), 4),
            avg_vote_score=round(sum(item["vote_score"] for item in bucket) / len(bucket), 4),
            avg_speech_score=round(sum(item["speech_score"] for item in bucket) / len(bucket), 4),
            avg_skill_score=round(sum(item["skill_score"] for item in bucket) / len(bucket), 4),
            avg_survival_score=round(sum(item["survival_score"] for item in bucket) / len(bucket), 4),
            avg_impact_bonus=round(sum(item["impact_bonus"] for item in bucket) / len(bucket), 4),
            avg_semantic_bonus=round(sum(item["semantic_bonus"] for item in bucket) / len(bucket), 4),
            critical_mistakes=critical_mistakes,
            role_normalized_score=role_normalized_score,
            best_role=best_role,
            weak_role=weak_role,
            metadata=metadata or {},
        )

    def _role_global_adjusted_avg(self, records: Sequence[dict[str, Any]]) -> dict[str, float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for record in records:
            grouped[record["role"]].append(record["adjusted_final_score"])
        return {role: sum(values) / len(values) for role, values in grouped.items()}

    def _item_version(self, item: GameMetrics | ReviewReport) -> str:
        metadata = item.metadata
        return str(
            metadata.get("strategy_version")
            or metadata.get("agent_version")
            or metadata.get("source_metadata", {}).get("strategy_version")
            or metadata.get("source_metadata", {}).get("agent_version")
            or "v0"
        )

    def _item_counterfactual_count(self, item: GameMetrics | ReviewReport) -> int:
        if isinstance(item, ReviewReport):
            return len(item.counterfactuals)
        return len(item.metadata.get("counterfactuals", []))

    def _result(
        self,
        leaderboard_type: str,
        entries: list[LeaderboardEntry],
        source_games: int,
        metadata: dict[str, Any],
    ) -> LeaderboardResult:
        return LeaderboardResult(
            leaderboard_type=leaderboard_type,
            entries=entries,
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_games=source_games,
            metadata=metadata,
        )


def export_leaderboard(result: LeaderboardResult, path: str | Path) -> dict[str, Any]:
    payload = result.to_dict()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _is_review_report_like(value: Any) -> bool:
    return all(
        hasattr(value, attr)
        for attr in (
            "game_id",
            "player_reviews",
            "strategy_suggestions",
            "bad_cases",
            "counterfactuals",
            "turning_points",
            "metadata",
        )
    )


class StrategyKnowledgeExtractor:
    """Extracts sanitized, reusable role-level strategy lessons from replay artifacts."""

    ROLE_NAMES = {role.value for role in Role} | {"global"}
    HIGH_CONFIDENCE = 0.75
    NAME_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")

    def extract(
        self,
        reports: ReviewReport | Sequence[ReviewReport],
        leaderboard_results: Sequence[LeaderboardResult] | None = None,
    ) -> list[StrategyKnowledge]:
        report_list = (
            [reports] if isinstance(reports, ReviewReport) or _is_review_report_like(reports) else list(reports)
        )
        items: list[StrategyKnowledge] = []
        for report in report_list:
            names = self._known_names(report)
            items.extend(self._from_strategy_suggestions(report, names))
            items.extend(self._from_bad_cases(report, names))
            items.extend(self._from_counterfactuals(report, names))
            items.extend(self._from_turning_points(report, names))
        if leaderboard_results:
            for result in leaderboard_results:
                items.extend(self._from_leaderboard(result))
        deduped: dict[tuple[str, str, str, str], StrategyKnowledge] = {}
        for item in items:
            key = (item.target_role, item.source_type, item.trigger_condition, item.suggestion)
            deduped.setdefault(key, item)
        return list(deduped.values())

    def _from_strategy_suggestions(self, report: ReviewReport, names: set[str]) -> list[StrategyKnowledge]:
        items: list[StrategyKnowledge] = []
        for index, suggestion in enumerate(report.strategy_suggestions, start=1):
            target_role = (
                suggestion.target
                if suggestion.target_type == "role" and suggestion.target in self.ROLE_NAMES
                else "global"
            )
            items.append(
                StrategyKnowledge(
                    knowledge_id=f"{report.game_id}-suggestion-{index}",
                    target_role=target_role,
                    source_game_id=report.game_id,
                    source_type="strategy_suggestion",
                    trigger_condition=self._strategy_trigger(suggestion.suggestion_type, target_role),
                    suggestion=self._sanitize_text(suggestion.suggestion, names),
                    priority=self._normalize_priority(suggestion.priority),
                    evidence_summary=self._sanitize_text(suggestion.source, names),
                    safe_for_agent=True,
                    metadata={"target_type": suggestion.target_type},
                    evidence_event_ids=list(suggestion.evidence_event_ids),
                )
            )
        return items

    def _from_bad_cases(self, report: ReviewReport, names: set[str]) -> list[StrategyKnowledge]:
        items: list[StrategyKnowledge] = []
        for index, case in enumerate(report.bad_cases, start=1):
            target_role = case.role if case.role in self.ROLE_NAMES else "global"
            items.append(
                StrategyKnowledge(
                    knowledge_id=f"{report.game_id}-bad-case-{index}",
                    target_role=target_role,
                    source_game_id=report.game_id,
                    source_type="bad_case",
                    trigger_condition=self._bad_case_trigger(case),
                    suggestion=self._sanitize_text(case.suggested_fix, names),
                    priority=self._priority_from_severity(case.severity),
                    evidence_summary=self._sanitize_text(
                        f"A {case.severity} {case.mistake_type} issue was detected for the {target_role} role.",
                        names,
                    ),
                    safe_for_agent=True,
                    metadata={"severity": case.severity, "mistake_type": case.mistake_type},
                    evidence_event_ids=list(case.evidence_event_ids),
                )
            )
        return items

    def _from_counterfactuals(self, report: ReviewReport, names: set[str]) -> list[StrategyKnowledge]:
        items: list[StrategyKnowledge] = []
        for index, case in enumerate(report.counterfactuals, start=1):
            target_role = self._infer_role_from_text(
                f"{case.original_decision} {case.alternative_decision} {case.expected_effect}",
                fallback="global",
            )
            items.append(
                StrategyKnowledge(
                    knowledge_id=f"{report.game_id}-counterfactual-{index}",
                    target_role=target_role,
                    source_game_id=report.game_id,
                    source_type="counterfactual",
                    trigger_condition=self._counterfactual_trigger(case, target_role),
                    suggestion=self._sanitize_text(case.alternative_decision, names),
                    priority="high" if case.confidence > self.HIGH_CONFIDENCE else "medium",
                    evidence_summary=self._sanitize_text(case.expected_effect, names),
                    safe_for_agent=True,
                    metadata={"confidence": case.confidence, "counterfactual_type": case.counterfactual_type},
                    evidence_event_ids=list(case.evidence_event_ids),
                )
            )
        return items

    def _from_turning_points(self, report: ReviewReport, names: set[str]) -> list[StrategyKnowledge]:
        items: list[StrategyKnowledge] = []
        for index, point in enumerate(report.turning_points, start=1):
            target_role = self._infer_role_from_text(point.description, fallback="global")
            suggestion = self._turning_point_suggestion(point, target_role)
            if not suggestion:
                continue
            items.append(
                StrategyKnowledge(
                    knowledge_id=f"{report.game_id}-turning-point-{index}",
                    target_role=target_role,
                    source_game_id=report.game_id,
                    source_type="turning_point",
                    trigger_condition=f"When a day-phase swing is forming around {target_role} pressure.",
                    suggestion=self._sanitize_text(suggestion, names),
                    priority="medium" if point.impact < 4 else "high",
                    evidence_summary=self._sanitize_text(point.title, names),
                    safe_for_agent=True,
                    metadata={"impact": point.impact},
                    evidence_event_ids=list(point.evidence_event_ids),
                )
            )
        return items

    def _from_leaderboard(self, result: LeaderboardResult) -> list[StrategyKnowledge]:
        items: list[StrategyKnowledge] = []
        if result.leaderboard_type != "role":
            return items
        for index, entry in enumerate(result.entries, start=1):
            if entry.display_name not in self.ROLE_NAMES or entry.games_played <= 0:
                continue
            items.append(
                StrategyKnowledge(
                    knowledge_id=f"leaderboard-{result.leaderboard_type}-{index}",
                    target_role=entry.display_name,
                    source_game_id="aggregate",
                    source_type="leaderboard",
                    trigger_condition=f"When calibrating default heuristics for the {entry.display_name} role.",
                    suggestion=f"Bias toward patterns that historically improved adjusted score for the {entry.display_name} role.",
                    priority="medium",
                    evidence_summary=f"Aggregate adjusted score for {entry.display_name} was {entry.avg_adjusted_final_score}.",
                    safe_for_agent=True,
                    metadata={"games_played": entry.games_played},
                )
            )
        return items

    def _known_names(self, report: ReviewReport) -> set[str]:
        names = {review.player_name for review in report.player_reviews}
        names.update(case.player_name for case in report.bad_cases)
        return {name for name in names if name}

    def _sanitize_text(self, text: str, names: set[str]) -> str:
        cleaned = text
        for name in sorted(names, key=len, reverse=True):
            cleaned = cleaned.replace(name, "the player")
        cleaned = re.sub(r"\b(day|night)\s+\d+\b", r"\1 phase", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\bthe player is (a|an)?\s*(wolf|seer|witch|hunter|guard|villager)\b",
            "a role signal appeared",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _strategy_trigger(self, suggestion_type: str, target_role: str) -> str:
        if suggestion_type == "vote_discipline":
            return f"When the {target_role} role is considering a low-confidence day vote."
        if suggestion_type == "speech_conversion":
            return f"When the {target_role} role needs to convert reads into public vote pressure."
        return f"When the {target_role} role encounters a repeated decision pattern."

    def _bad_case_trigger(self, case: BadCaseReport) -> str:
        role = case.role if case.role in self.ROLE_NAMES else "global"
        if case.mistake_type == "vote":
            return f"When the {role} role is about to join or lead a day wagon."
        if case.mistake_type == "ability":
            return f"When the {role} role is about to use a limited active ability."
        return f"When the {role} role is deciding how to reveal information publicly."

    def _counterfactual_trigger(self, case: CounterfactualCase, target_role: str) -> str:
        if case.counterfactual_type == "vote":
            return f"When the {target_role} role sees a close exile vote with mixed signals."
        if case.counterfactual_type == "skill":
            return f"When the {target_role} role is deciding whether to spend a high-impact ability."
        return f"When the {target_role} role holds private information that can change public alignment."

    def _turning_point_suggestion(self, point: TurningPoint, target_role: str) -> str:
        if "Seer" in point.title or "seer" in point.description.lower():
            return "Seer check results should be converted quickly into clear public vote direction."
        if "Poison" in point.title or "poison" in point.description.lower():
            return "Witch poison should be reserved for high-confidence wolf pressure or decisive endgame conversions."
        if "vote" in point.description.lower():
            return f"The {target_role} role should treat close public wagons as a timing-sensitive decision point."
        return ""

    def _infer_role_from_text(self, text: str, fallback: str) -> str:
        lowered = text.lower()
        mapping = {
            "seer": Role.SEER.value,
            "witch": Role.WITCH.value,
            "hunter": Role.HUNTER.value,
            "guard": Role.GUARD.value,
            "villager": Role.VILLAGER.value,
            "wolf": Role.WEREWOLF.value,
        }
        for keyword, role in mapping.items():
            if keyword in lowered:
                return role
        return fallback

    def _priority_from_severity(self, severity: str) -> str:
        if severity == "critical":
            return "high"
        if severity == "major":
            return "medium"
        return "low"

    def _normalize_priority(self, priority: str) -> str:
        if priority in {"high", "medium", "low"}:
            return priority
        if priority == "critical":
            return "high"
        if priority == "major":
            return "medium"
        return "medium"


def export_strategy_knowledge(items: Sequence[StrategyKnowledge], path: str | Path) -> list[dict[str, Any]]:
    payload = [asdict(item) for item in items]
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# Default implementations
# ---------------------------------------------------------------------------


class GraphRAGReviewProvider:
    """Default review adapter for GraphRAG ingestion."""

    def __init__(self, calculator: MetricsCalculator | None = None) -> None:
        self.calculator = calculator or MetricsCalculator()

    def build_artifact(self, state: GameState) -> ReviewArtifact:
        return ReviewArtifact(
            game_id=state.id,
            winner=state.winner.value if state.winner else None,
            timeline=[event.to_dict() for event in state.events],
            daily_summaries=dict(state.daily_summaries),
            daily_summary_facts=dict(state.daily_summary_facts),
            metadata={
                "day": state.day,
                "phase": state.phase.value,
                "player_count": len(state.players),
                "alive_count": sum(1 for player in state.players if player.alive),
            },
        )

    def compute_metrics(self, state: GameState) -> GameMetrics:
        return self.calculator.compute(state)

    def _wolf_team_votes(self, state: GameState) -> list[dict[str, Any]]:
        tallies: list[dict[str, Any]] = []
        for event in state.events:
            if event.type != EventType.PRIVATE_INFO or event.payload.get("kind") != "wolf_attack_tally":
                continue
            votes = dict(event.payload.get("votes", {}))
            tallies.append(
                {
                    "day": event.day,
                    "target_id": event.payload.get("target_id"),
                    "target_name": event.payload.get("target_name"),
                    "votes": votes,
                    "voter_count": len(votes),
                    "unanimous": len(set(votes.values())) == 1 if votes else False,
                }
            )
        return tallies

    def detect_bad_cases(self, state: GameState) -> list[BadCaseReport]:
        return self.calculator.detect_bad_cases(state)


class InMemoryLeaderboard:
    """Simple in-memory leaderboard for comparing agents across games."""

    def __init__(self) -> None:
        self.entries: dict[str, list[LeaderboardEntry]] = {}

    def add_game(self, metrics: GameMetrics) -> None:
        for score in metrics.player_scores:
            key = score.role
            entry = LeaderboardEntry(
                leaderboard_type="role",
                key=score.role,
                display_name=score.persona_name or score.player_name,
                games_played=1,
                wins=1 if score.camp_result_score >= 1.0 else 0,
                win_rate=score.camp_result_score,
                avg_final_score=score.final_score,
                avg_adjusted_final_score=score.adjusted_final_score
                if score.adjusted_final_score is not None
                else score.final_score,
                avg_vote_score=score.vote_score,
                avg_speech_score=score.speech_score,
                avg_skill_score=score.skill_score,
                avg_survival_score=score.survival_score,
                avg_impact_bonus=score.impact_bonus,
                avg_semantic_bonus=score.semantic_highlight_bonus,
                critical_mistakes=sum(1 for mistake in score.mistakes if str(mistake).startswith("[critical]")),
                metadata={"game_id": metrics.game_id},
            )
            self.entries.setdefault(key, []).append(entry)

    def top_agents(self, role: str, limit: int = 10) -> list[LeaderboardEntry]:
        entries = self.entries.get(role, [])
        return sorted(entries, key=lambda entry: (entry.win_rate, entry.avg_adjusted_final_score), reverse=True)[:limit]

    def compare_versions(self, version_a: str, version_b: str) -> dict[str, Any]:
        return {
            "version_a": version_a,
            "version_b": version_b,
            "status": "not_implemented",
            "message": "Version comparison requires batch replay infrastructure",
        }


# ---------------------------------------------------------------------------
# Full pipeline: metrics → report → optimizer → markdown
# ---------------------------------------------------------------------------


def generate_review_report(
    state: GameState,
    *,
    max_iterations: int = 2,
    json_path: str | Path | None = None,
    markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full review pipeline: compute metrics, build report, run the
    evaluator-optimizer loop, and render the final markdown.

    This is the recommended entry point for generating a review report — it
    ensures the review agent actually audits the output before delivery.
    """
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    from backend.eval.report_graph import create_report_optimizer

    optimizer = create_report_optimizer()
    opt_state = optimizer.optimize(report, max_iterations=max_iterations)

    validation_result = {
        "passed": opt_state.quality_passed,
        "grade": opt_state.evaluator_result.grade if opt_state.evaluator_result else "fail",
        "score": opt_state.evaluator_result.score if opt_state.evaluator_result else 0.0,
        "issues": opt_state.evaluator_result.issues if opt_state.evaluator_result else [],
        "publish_allowed": opt_state.quality_passed,
    }
    report.metadata["validation_result"] = validation_result
    report.metadata["quality_passed"] = opt_state.quality_passed

    final_markdown = MarkdownReportRenderer().render(
        report,
        evaluation_result=opt_state.evaluator_result,
    )

    if json_path is not None:
        Path(json_path).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if markdown_path is not None:
        Path(markdown_path).write_text(final_markdown, encoding="utf-8")

    return {
        "report": report.to_dict(),
        "final_markdown": final_markdown,
        "quality_passed": opt_state.quality_passed,
        "evaluator_grade": opt_state.evaluator_result.grade if opt_state.evaluator_result else None,
        "evaluator_score": opt_state.evaluator_result.score if opt_state.evaluator_result else None,
        "iterations": opt_state.iteration,
    }
