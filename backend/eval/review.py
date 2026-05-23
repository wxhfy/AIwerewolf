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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, Sequence

from backend.engine.models import Alignment, EventType, GameEvent, GameState, Player, Role


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
    highlights: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)
    adjusted_final_score: float | None = None
    impact_bonus: float = 0.0
    semantic_highlight_bonus: float = 0.0
    review_penalty: float = 0.0


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


@dataclass
class PlayerReview:
    """Per-player structured replay narrative."""

    player_id: str
    player_name: str
    role: str
    alignment: str
    rule_score: float
    adjusted_final_score: float
    rank: int
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


@dataclass
class ReviewReport:
    """Structured replay report for one completed match."""

    game_id: str
    winner: str | None
    total_days: int
    total_events: int
    game_summary: str
    scoreboard: list[dict[str, Any]] = field(default_factory=list)
    mvp_results: list[MVPResult] = field(default_factory=list)
    turning_points: list[TurningPoint] = field(default_factory=list)
    player_reviews: list[PlayerReview] = field(default_factory=list)
    bad_cases: list[BadCaseReport] = field(default_factory=list)
    counterfactuals: list[CounterfactualCase] = field(default_factory=list)
    strategy_suggestions: list[StrategySuggestion] = field(default_factory=list)
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
    "vote": "投票反事实",
    "skill": "技能反事实",
    "info_release": "信息释放反事实",
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
            score for score in player_scores
            if state.winner is not None and score.alignment == state.winner.value
        ] or list(player_scores)
        winning_best = max(winning_scores, key=lambda score: self._mvp_score(score))

        return [
            self._build_result(global_best, "global_mvp", bonus_map.get(global_best.player_id, [])),
            self._build_result(winning_best, "winning_camp_mvp", bonus_map.get(winning_best.player_id, [])),
        ]

    def _mvp_score(self, score: PlayerScore) -> float:
        adjusted = score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score
        return round(0.60 * adjusted + 0.25 * score.impact_bonus + 0.15 * score.semantic_highlight_bonus, 2)

    def _build_result(
        self,
        score: PlayerScore,
        mvp_type: str,
        bonuses: Sequence[ReviewBonus],
    ) -> MVPResult:
        evidence = [item for bonus in bonuses for item in bonus.evidence][:4] or score.highlights[:3]
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
        )


class ReviewBonusDetector:
    """Rule-based replay-layer detector for high-impact highlights and extra penalties."""

    def detect(
        self,
        state: GameState,
        player_scores: Sequence[PlayerScore],
        bad_case_reports: Sequence[BadCaseReport],
        contexts: dict[str, "_PlayerContext"],
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
        bonuses.extend(self._detect_witch_bonuses(state, contexts))
        bonuses.extend(self._detect_hunter_bonuses(state, contexts))
        bonuses.extend(self._detect_wolf_bonuses(state, contexts))
        bonuses.extend(self._detect_review_penalties(state, contexts, reports_by_player, score_by_player))
        return bonuses

    def _detect_key_vote_bonuses(
        self,
        state: GameState,
        contexts: dict[str, "_PlayerContext"],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for day in sorted({event.day for event in state.events if event.type == EventType.VOTE_CAST}):
            day_votes = [event for event in state.events if event.type == EventType.VOTE_CAST and event.day == day]
            exiled = next(
                (
                    event for event in state.events
                    if event.type == EventType.PLAYER_DIED and event.day == day and event.payload.get("reason") == "vote"
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
                    if not (target_id in previous_leaders and len(previous_leaders) > 1 and counts[target_id] > previous_max):
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
        contexts: dict[str, "_PlayerContext"],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.SEER:
                continue
            wolf_checks = [event for event in ctx.private_info_events if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")]
            for check_event in wolf_checks:
                target_id = check_event.payload.get("target_id")
                target_name = check_event.payload.get("target_name")
                releasing_speech = next(
                    (
                        speech for speech in ctx.speech_events
                        if target_name and target_name in str(speech.payload.get("speech", ""))
                    ),
                    None,
                )
                if releasing_speech is None:
                    continue
                influenced_votes = [
                    event for event in state.events
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

    def _detect_witch_bonuses(
        self,
        state: GameState,
        contexts: dict[str, "_PlayerContext"],
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
                    dead_wolves = {death.payload.get("player_id") for death in state.events if death.type == EventType.PLAYER_DIED}
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
                                evidence=[f"救下 {target.name}（{ROLE_LABELS.get(target.role.value, target.role.value)}）后，该角色后续继续产生有效贡献。"],
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
        contexts: dict[str, "_PlayerContext"],
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
                dead_wolves = {death.payload.get("player_id") for death in state.events if death.type == EventType.PLAYER_DIED}
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

    def _detect_wolf_bonuses(
        self,
        state: GameState,
        contexts: dict[str, "_PlayerContext"],
    ) -> list[ReviewBonus]:
        bonuses: list[ReviewBonus] = []
        for player_id, ctx in contexts.items():
            if ctx.player.role != Role.WEREWOLF:
                continue
            for vote_event in ctx.vote_events:
                target = self._event_target(state, vote_event)
                if target is None or target.alignment != Alignment.VILLAGE or target.role not in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD}:
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

    def _detect_review_penalties(
        self,
        state: GameState,
        contexts: dict[str, "_PlayerContext"],
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
                        evidence=[report.description for report in reports if "did not release" in report.description][:2],
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
                            evidence=[report.description for report in reports if "poisoned villager-side" in report.description][:1],
                            confidence=0.7,
                            category="penalty",
                        )
                    )
            if player.role == Role.VILLAGER:
                repeated_target = self._repeated_wrong_lead_target(state, ctx)
                if repeated_target is not None and repeated_target.role in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD}:
                    penalties.append(
                        ReviewBonus(
                            player_id=player_id,
                            bonus_type="wrong_day_lead",
                            score_delta=-2.5,
                            reason="Replay penalizes repeatedly driving pressure onto a key villager-side target.",
                            evidence=[f"Repeatedly named and voted {repeated_target.name}, who was a {repeated_target.role.value}."],
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
            if event.payload.get("actor_id") == player_id and event.type in {EventType.CHAT_MESSAGE, EventType.NIGHT_ACTION, EventType.HUNTER_SHOT}:
                return True
            if event.type == EventType.PRIVATE_INFO and player_id in event.visible_to and event.payload.get("kind") == "seer_result":
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

    def _repeated_wrong_lead_target(self, state: GameState, ctx: "_PlayerContext") -> Player | None:
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

    def __init__(
        self,
        *,
        bonus_detector: ReviewBonusDetector | None = None,
        final_score_calculator: FinalScoreCalculator | None = None,
        mvp_selector: MVPSelector | None = None,
    ) -> None:
        self.bonus_detector = bonus_detector or ReviewBonusDetector()
        self.final_score_calculator = final_score_calculator or FinalScoreCalculator()
        self.mvp_selector = mvp_selector or MVPSelector()

    def compute(self, state: GameState) -> GameMetrics:
        contexts = self._build_contexts(state)
        bad_case_reports = self.detect_bad_cases(state)
        reports_by_player = self._reports_by_player(state, bad_case_reports)
        player_scores = [
            self._build_player_score(state, contexts[player.id], reports_by_player.get(player.id, []))
            for player in state.players
        ]
        role_metrics = [
            self._build_role_metrics(contexts[player.id], score)
            for player, score in zip(state.players, player_scores)
        ]
        persona_metrics = self.aggregate_persona_metrics(player_scores)
        review_bonuses = self.bonus_detector.detect(state, player_scores, bad_case_reports, contexts)
        adjusted_scores = self.final_score_calculator.apply(player_scores, review_bonuses)
        mvp_results = self.mvp_selector.select(state, adjusted_scores, review_bonuses)

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
                "role_score_formula": (
                    "0.25*camp + 0.25*role_task + 0.20*vote + "
                    "0.10*speech + 0.10*skill + 0.10*survival - mistake_penalty"
                ),
                "final_adjusted_formula": "RuleBasedScore + ImpactBonus + SemanticHighlightBonus - ReviewPenalty",
            },
        )

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
                            )
                        )

            if player.role == Role.SEER:
                wolf_checks = [
                    event.payload
                    for event in ctx.private_info_events
                    if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")
                ]
                if wolf_checks:
                    released_targets = self._released_check_targets(ctx)
                    for payload in wolf_checks:
                        target_name = str(payload.get("target_name") or "")
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
                            )
                        )

            if player.role == Role.VILLAGER:
                consecutive_good_votes = self._consecutive_votes_on_alignment(state, ctx.vote_events, Alignment.VILLAGE)
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
                (sum(values) / len(values)) - global_role_avg[role]
                for role, values in role_bucket.items()
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
        role_task_score, role_highlights = self._role_task_score(state, ctx, vote_score, speech_score, skill_score, survival_score)
        mistake_penalty = self._mistake_penalty(reports)

        highlights = list(role_highlights)
        mistakes = [f"[{report.severity}] {report.description}" for report in reports]
        if camp_result_score >= 1.0:
            highlights.append("与本方阵营一同获胜。")
        if survival_score >= 1.0:
            highlights.append("存活至对局结束。")

        base_total = (
            0.25 * camp_result_score
            + 0.25 * role_task_score
            + 0.20 * vote_score
            + 0.10 * speech_score
            + 0.10 * skill_score
            + 0.10 * survival_score
            - mistake_penalty
        )
        final_score = round(self._clamp(base_total) * 100, 2)

        persona_name = player.name
        return PlayerScore(
            player_id=player.id,
            player_name=player.name,
            persona_id=persona_name,
            persona_name=persona_name,
            role=player.role.value,
            alignment=player.alignment.value,
            camp_result_score=round(camp_result_score, 4),
            role_task_score=round(role_task_score, 4),
            vote_score=round(vote_score, 4),
            speech_score=round(speech_score, 4),
            skill_score=round(skill_score, 4),
            survival_score=round(survival_score, 4),
            mistake_penalty=round(mistake_penalty, 4),
            final_score=final_score,
            highlights=highlights,
            mistakes=mistakes,
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
            (event.day for event in state.events if event.type == EventType.PLAYER_DIED and event.payload.get("player_id") == player.id),
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
            wolf_checks = [e for e in ctx.private_info_events if e.payload.get("kind") == "seer_result" and e.payload.get("is_wolf")]
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
            timing = 1.0 if ctx.night_action_events else 0.4
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
        streak = 0
        best = 0
        for event in sorted(vote_events, key=lambda item: (item.day, item.ts)):
            target = self._target_player(state, event)
            if target is not None and target.alignment == alignment:
                streak += 1
                best = max(best, streak)
            else:
                streak = 0
        return best

    def _speech_hit_eliminated_target(self, state: GameState, speech: str) -> bool:
        eliminated_names = {
            event.payload.get("player_name")
            for event in state.events
            if event.type == EventType.PLAYER_DIED
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
            return 0.4
        scores: list[float] = []
        for event in save_events:
            target = self._target_player(state, event)
            if target is None:
                continue
            was_wolf_target = self._is_majority_wolf_target(state, target.id, event.day)
            value = 1.0 if was_wolf_target and target.alignment == Alignment.VILLAGE else 0.2
            scores.append(value)
        return 0.4 if not scores else self._clamp(sum(scores) / len(scores))

    def _witch_poison_value(self, state: GameState, ctx: _PlayerContext) -> float:
        poison_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "witch_poison"]
        if not poison_events:
            return 0.4
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
            if target_id and self._is_majority_wolf_target(state, target_id, event.day) and not self._died_by_reason(state, target_id, "wolf", event.day):
                successes += 1
        return self._clamp(successes / len(guard_events))

    def _guard_key_role_protection(self, state: GameState, ctx: _PlayerContext) -> float:
        guard_events = [event for event in ctx.night_action_events if event.payload.get("action_type") == "guard"]
        if not guard_events:
            return 0.0
        protected = 0
        for event in guard_events:
            target = self._target_player(state, event)
            if target is not None and target.role.value in self.POWER_ROLES:
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

    def _villager_logic_consistency(self, state: GameState, ctx: _PlayerContext) -> float:
        if not ctx.vote_events:
            return 0.4
        consistent = 0
        for vote_event in ctx.vote_events:
            target = self._target_player(state, vote_event)
            if target is None:
                continue
            target_name = target.name
            prior_speeches = [
                event for event in ctx.speech_events if event.day <= vote_event.day
            ]
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
    ) -> BadCaseReport:
        return BadCaseReport(
            game_id=state.id,
            day=day,
            player_name=player.name,
            role=player.role.value,
            mistake_type=mistake_type,
            description=description,
            suggested_fix=suggested_fix,
            severity=severity,
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

    def __init__(self, counterfactual_analyzer: "CounterfactualAnalyzer | None" = None) -> None:
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
                "adjusted_final_score": score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
                "impact_bonus": score.impact_bonus,
                "semantic_highlight_bonus": score.semantic_highlight_bonus,
                "review_penalty": score.review_penalty,
            }
            for index, score in enumerate(ranked_scores, start=1)
        ]

        turning_points = self._build_turning_points(bonuses, bad_cases, score_map)
        counterfactuals = self.counterfactual_analyzer.analyze(
            state,
            metrics,
            bad_cases=bad_cases,
            turning_points=turning_points,
            review_bonuses=bonuses,
        )
        strategy_suggestions = self._build_strategy_suggestions(metrics.player_scores, bad_cases, bonuses, counterfactuals, turning_points)
        player_reviews = self._build_player_reviews(ranked_scores, bonuses, bad_cases, counterfactuals)
        game_summary = self._build_game_summary(metrics, turning_points, mvp_results)

        return ReviewReport(
            game_id=metrics.game_id,
            winner=metrics.winner,
            total_days=metrics.total_days,
            total_events=metrics.total_events,
            game_summary=game_summary,
            scoreboard=scoreboard,
            mvp_results=mvp_results,
            turning_points=turning_points,
            player_reviews=player_reviews,
            bad_cases=bad_cases,
            counterfactuals=counterfactuals,
            strategy_suggestions=strategy_suggestions,
            metadata={
                "winner_reasoning": game_summary,
                "score_formula": metrics.metadata.get("role_score_formula"),
                "adjusted_formula": metrics.metadata.get("final_adjusted_formula"),
                "leaderboard_available": True,
                "leaderboard_note": "跨局表现请查看 Leaderboard 输出；跨局 Leaderboard 由 LeaderboardAggregator 单独生成，本报告仅针对当前单局。",
                "player_scores": [asdict(score) for score in metrics.player_scores],
                "source_metadata": dict(metrics.metadata),
                # TODO: allow an LLM review narrator to append richer natural-language summaries.
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
            impact_highlights = [self._zh_text(bonus.reason) for bonus in player_bonuses if bonus.category in {"impact", "semantic"} and bonus.score_delta > 0]
            penalty_notes = [self._zh_text(bonus.reason) for bonus in player_bonuses if bonus.category == "penalty" and bonus.score_delta < 0]
            reports = name_to_bad_cases.get(score.player_name, [])
            player_counterfactuals = counterfactuals_by_player.get(score.player_name, [])
            mistakes = list(dict.fromkeys([self._zh_text(item) for item in score.mistakes] + [self._zh_text(report.description) for report in reports]))
            weaknesses = list(dict.fromkeys(penalty_notes + [self._zh_text(report.suggested_fix) for report in reports]))
            highlights = list(dict.fromkeys([self._zh_text(item) for item in score.highlights] + impact_highlights))
            suggestions = self._player_suggestions(score, reports, player_bonuses, player_counterfactuals)

            reviews.append(
                PlayerReview(
                    player_id=score.player_id,
                    player_name=score.player_name,
                    role=score.role,
                    alignment=score.alignment,
                    rule_score=score.final_score,
                    adjusted_final_score=score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
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
    ) -> list[TurningPoint]:
        turning_points: list[TurningPoint] = []
        for bonus in bonuses:
            if bonus.category != "impact" or bonus.score_delta <= 0 or not bonus.evidence:
                continue
            score = score_map.get(bonus.player_id)
            related = [score.player_name] if score is not None else [bonus.player_id]
            turning_points.append(
                TurningPoint(
                    day=bonus.day,
                    phase=bonus.phase,
                    title=self._bonus_title(bonus),
                    description=bonus.reason,
                    impact=round(min(abs(bonus.score_delta), 5.0), 2),
                    related_players=related,
                    evidence=list(bonus.evidence),
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
                )
            )
        unique: dict[tuple[Any, ...], TurningPoint] = {}
        for point in turning_points:
            key = (point.day, point.phase, point.title, point.description)
            if key not in unique or point.impact > unique[key].impact:
                unique[key] = point
        return sorted(unique.values(), key=lambda point: ((point.day or 0), point.impact), reverse=True)

    def _build_strategy_suggestions(
        self,
        player_scores: Sequence[PlayerScore],
        bad_cases: Sequence[BadCaseReport],
        bonuses: Sequence[ReviewBonus],
        counterfactuals: Sequence[CounterfactualCase],
        turning_points: Sequence[TurningPoint],
    ) -> list[StrategySuggestion]:
        suggestions: list[StrategySuggestion] = []
        reports_by_player: dict[str, list[BadCaseReport]] = defaultdict(list)
        counterfactuals_by_player: dict[str, list[CounterfactualCase]] = defaultdict(list)
        score_by_id = {score.player_id: score for score in player_scores}
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
                        )
                    )

        for bonus in bonuses:
            if bonus.category != "impact" or bonus.score_delta <= 0 or not bonus.evidence:
                continue
            score = score_by_id.get(bonus.player_id)
            if score is None or bonus.bonus_type not in {"seer_info_conversion", "key_role_save", "final_wolf_shot", "wolf_power_role_push"}:
                continue
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
                )
            )

        for score in player_scores:
            cf_items = counterfactuals_by_player.get(score.player_name, [])
            if cf_items and not reports_by_player.get(score.player_name):
                suggestions.append(
                    StrategySuggestion(
                        target_type="player",
                        target=score.player_name,
                        suggestion_type="report_suggestion",
                        suggestion=self._game_specific_counterfactual_suggestion(score, cf_items[0]),
                        source=self._zh_text(cf_items[0].expected_effect),
                        priority="high" if cf_items[0].confidence >= 0.75 else "medium",
                        metadata={
                            "scope": "game_specific",
                            "safe_for_agent": False,
                            "source_type": "counterfactual",
                            "evidence_summary": self._zh_text(cf_items[0].expected_effect),
                        },
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
        strengths.extend(bonus.reason for bonus in bonuses if bonus.score_delta > 0 and bonus.category in {"impact", "semantic"})
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
            f"投票：反映投票命中率与票型贡献。",
            f"发言：反映公开发言的信息量与转化能力。",
            f"技能：反映技能使用价值或夜间行动质量。",
            f"生存：反映存活时长与残局存在感。",
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
        if bonus.bonus_type == "key_role_save":
            return "女巫在关键轮次应优先评估神职存活价值，能保住后续还能继续产出信息或保护收益的角色时，救人优先级更高。"
        if bonus.bonus_type == "final_wolf_shot":
            return "猎人临死前应优先瞄准能够直接锁定胜负的高狼面目标，把开枪收益最大化。"
        if bonus.bonus_type == "wolf_power_role_push":
            return "狼人白天推进关键神职出局时，最好让发言逻辑、票型方向和队友配合保持一致，避免推进成功后立刻暴露自己的狼面。"
        return f"{self._role_label(role)}在关键轮次应主动把优势行为沉淀为可复用节奏。"

    def _covered_dimensions(self, bonus_types: set[str]) -> set[str]:
        mapping = {
            "seer_info_conversion": "speech",
            "decisive_vote": "vote",
            "last_wolf_poison": "skill",
            "key_role_save": "skill",
            "final_wolf_shot": "skill",
            "wolf_power_role_push": "speech",
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
        }
        result = replacements.get(text, text)
        # Regex replacements run FIRST on the original English text,
        # before role_tokens substitution partial-translates the string.
        regex_replacements = [
            (r"^(?P<actor>.+?) voted a checked-good player (?P<target>.+?)\.?$", r"\g<actor>投票给已被确认偏好人的玩家\g<target>"),
            (r"^(?P<actor>.+?) voted villager-side players in consecutive rounds\.?$", r"\g<actor>连续多轮投票落在好人阵营玩家身上"),
            (r"^(?P<actor>.+?) repeatedly voted villager-side players \((?P<count>\d+) times\)\.?$", r"\g<actor>连续\g<count>次把票投在好人阵营玩家身上"),
            (r"^(?P<actor>.+?) poisoned villager-side player (?P<target>.+?)\.?$", r"\g<actor>毒杀了好人阵营玩家\g<target>"),
            (r"^(?P<actor>.+?) shot villager-side player (?P<target>.+?)\.?$", r"\g<actor>开枪打中了好人阵营玩家\g<target>"),
            (r"^The table exiled villager-side player (?P<target>.+?) on day (?P<day>\d+)\.?$", r"第\g<day>天场上错误放逐了好人阵营玩家\g<target>"),
            (r"^If one additional vote had moved onto (?P<target>.+?), the day could have resolved against a wolf instead\.?$", r"如果再有一票转投给\g<target>，这轮白天可能就会改为放逐狼人"),
            (r"^The wrong exile on (?P<target>.+?) may have been avoided by consolidating onto (?P<wolf>.+?)\.?$", r"如果把票型集中到\g<wolf>身上，原本对\g<target>的错误放逐可能可以避免"),
            (r"^If (?P<actor>.+?) had held poison or redirected onto a higher-confidence wolf target, (?P<target>.+?) might survive the night\.?$", r"如果\g<actor>当时选择不交毒，或改毒更高狼面的目标，\g<target>本可能活过当晚"),
            (r"^Village-side numbers and public information from (?P<target>.+?) would likely be preserved\.?$", r"这样可以保留\g<target>带来的好人轮次人数与公开信息"),
            (r"^The witch did not save key role (?P<target>.+?) on night (?P<day>\d+)\.?$", r"女巫在第\g<day>天夜里没有救下关键角色\g<target>"),
            (r"^If the witch had saved (?P<target>.+?), the village might retain a high-value (?P<role>.+?) for the next day\.?$", r"如果女巫当晚救下\g<target>，好人阵营可能把这名高价值的\g<role>保留到下一天"),
            (r"^(?P<target>.+?) died to the wolf attack on night (?P<day>\d+)\.?$", r"\g<target>在第\g<day>天夜里死于狼刀"),
            (r"^(?P<role>.+?) is a key village-side role\.?$", r"\g<role>是好人阵营的关键角色"),
            (r"^If (?P<actor>.+?) had held the shot or targeted a higher-confidence wolf read, the trade could avoid friendly fire\.?$", r"如果\g<actor>当时选择不开枪，或改打更高狼面的目标，这次换子就可能避免误伤好人"),
            (r"^Village-side resources would not be lost to the hunter shot on (?P<target>.+?)\.?$", r"这样就不会因为猎人这一枪再损失\g<target>对应的好人资源"),
            (r"^Hunter shot removed (?P<target>.+?)\.?$", r"猎人开枪带走了\g<target>"),
            # Counterfactual expected_effect patterns
            (r"^Preserving (?P<target>.+?) could keep more public or private information online\.?$", r"保留\g<target>可以维持更多公开或私密信息渠道。"),
            (r"^If (?P<actor>.+?) had switched to (?P<wolf>.+?), the wagon likely avoids exiling (?P<exiled>.+?)\.?$", r"如果\g<actor>转投\g<wolf>，放逐目标可能从\g<exiled>改为狼人。"),
            (r"^Village-side elimination pressure could move from (?P<exiled>.+?) to wolf (?P<wolf>.+?)\.?$", r"好人阵营的放逐压力可能从\g<exiled>转向狼人\g<wolf>。"),
            (r"^Publicly releasing the check could improve vote convergence onto (?P<target>.+?) and reduce good-player misvotes\.?$", r"公开发布查验结果可能让票型更快向\g<target>集中，减少好人误投。"),
            # Counterfactual original_decision patterns (info release)
            (r"^(?P<actor>.+?) held the wolf result on (?P<target>.+?) instead of releasing it publicly\.?$", r"\g<actor>选择隐藏了对\g<target>的查杀结果，没有公开发布。"),
            (r"^If (?P<actor>.+?) had announced the wolf check on (?P<target>.+?) during day (?P<day>\d+), the village might align votes earlier\.?$", r"如果\g<actor>在第\g<day>天公开宣布对\g<target>的查杀，好人阵营可能更早统一票型。"),
            # Bad case: seer checked wolf but didn't release
            (r"^(?P<actor>.+?) checked wolf (?P<target>.+?) but did not release the information later\.?$", r"\g<actor>查验到狼人阵营\g<target>但未在后续公开该查杀信息"),
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
            "last_wolf_poison": "最后一狼毒杀",
            "key_role_save": "关键救人",
            "final_wolf_shot": "最后一狼击杀",
            "wolf_power_role_push": "关键神职放逐推进",
        }
        return title_map.get(bonus.bonus_type, bonus.bonus_type.replace("_", " ").title())


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
    ) -> list[CounterfactualCase]:
        cases: list[CounterfactualCase] = []
        cases.extend(self._vote_cases(state, bad_cases, turning_points))
        cases.extend(self._skill_cases(state, bad_cases))
        cases.extend(self._info_release_cases(state, bad_cases, review_bonuses))
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
                    event for event in state.events
                    if event.type == EventType.PLAYER_DIED and event.day == day and event.payload.get("reason") == "vote"
                ),
                None,
            )
            if exile is None:
                continue
            exiled = state.player(str(exile.payload.get("player_id")))
            if exiled.alignment != Alignment.VILLAGE:
                continue

            counts: dict[str, int] = defaultdict(int)
            ordered_votes = [event for event in sorted(state.events, key=lambda item: item.ts) if event.type == EventType.VOTE_CAST and event.day == day]
            for event in ordered_votes:
                target_id = event.payload.get("target_id")
                if target_id:
                    counts[str(target_id)] += 1
            if not counts:
                continue
            exiled_votes = counts.get(exiled.id, 0)
            wolf_targets = [
                (target_id, count) for target_id, count in counts.items()
                if state.player(target_id).alignment == Alignment.WOLF
            ]
            if not wolf_targets:
                continue
            wolf_target_id, wolf_votes = max(wolf_targets, key=lambda item: item[1])
            if exiled_votes - wolf_votes > 1:
                continue

            wolf_target = state.player(wolf_target_id)
            pivot_vote = self._find_pivot_vote(ordered_votes, exiled.id, wolf_target_id)
            source_turning_point_id = self._find_turning_point_id(turning_points, day, exiled.name)
            source_bad_case_id = self._find_bad_case_id(bad_cases, day, exiled.name, "vote")
            if pivot_vote is not None:
                voter = state.player(str(pivot_vote.payload.get("voter_id")))
                current_target = state.player(str(pivot_vote.payload.get("target_id")))
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-vote-{day}-{voter.id}",
                        game_id=state.id,
                        day=day,
                        phase=pivot_vote.phase.value,
                        counterfactual_type="vote",
                        original_decision=f"{voter.name} voted {current_target.name} on day {day}.",
                        alternative_decision=f"If {voter.name} had switched to {wolf_target.name}, the wagon likely avoids exiling {exiled.name}.",
                        expected_effect=f"Village-side elimination pressure could move from {exiled.name} to wolf {wolf_target.name}.",
                        affected_players=[voter.name, exiled.name, wolf_target.name],
                        confidence=0.82,
                        evidence=[
                            f"{exiled.name} was exiled with {exiled_votes} vote(s).",
                            f"{wolf_target.name} finished close behind with {wolf_votes} vote(s).",
                        ],
                        severity="major",
                        source_bad_case_id=source_bad_case_id,
                        source_turning_point_id=source_turning_point_id,
                    )
                )
            else:
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-vote-{day}-{exiled.id}",
                        game_id=state.id,
                        day=day,
                        phase="DAY_VOTE",
                        counterfactual_type="vote",
                        original_decision=f"The table exiled villager-side player {exiled.name} on day {day}.",
                        alternative_decision=f"If one additional vote had moved onto {wolf_target.name}, the day could have resolved against a wolf instead.",
                        expected_effect=f"The wrong exile on {exiled.name} may have been avoided by consolidating onto {wolf_target.name}.",
                        affected_players=[exiled.name, wolf_target.name],
                        confidence=0.72,
                        evidence=[
                            f"{wolf_target.name} was the closest wolf wagon with {wolf_votes} vote(s).",
                            f"The margin to {exiled.name} was only {exiled_votes - wolf_votes}.",
                        ],
                        severity="major",
                        source_bad_case_id=source_bad_case_id,
                        source_turning_point_id=source_turning_point_id,
                    )
                )
        return cases

    def _skill_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
    ) -> list[CounterfactualCase]:
        cases: list[CounterfactualCase] = []
        for event in state.events:
            if event.type == EventType.NIGHT_ACTION and event.payload.get("action_type") == "witch_poison":
                actor = state.player(str(event.payload.get("actor_id")))
                target = self._target_player(state, event)
                if actor.role == Role.WITCH and target is not None and target.alignment == Alignment.VILLAGE:
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-skill-witch-poison-{event.day}-{actor.id}",
                            game_id=state.id,
                            day=event.day,
                            phase=event.phase.value,
                            counterfactual_type="skill",
                            original_decision=f"{actor.name} poisoned villager-side player {target.name}.",
                            alternative_decision=f"If {actor.name} had held poison or redirected onto a higher-confidence wolf target, {target.name} might survive the night.",
                            expected_effect=f"Village-side numbers and public information from {target.name} would likely be preserved.",
                            affected_players=[actor.name, target.name],
                            confidence=0.88,
                            evidence=[f"Poison directly killed {target.name}.", "This was flagged as a critical mis-poison."],
                            severity="critical",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, event.day, actor.name, "ability"),
                        )
                    )
            if event.type == EventType.NIGHT_ACTION and event.payload.get("action_type") == "attack":
                target = self._target_player(state, event)
                if target is None or target.role not in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD}:
                    continue
                save_used = any(
                    item.type == EventType.NIGHT_ACTION
                    and item.day == event.day
                    and item.payload.get("action_type") == "witch_save"
                    and item.payload.get("target_id") == target.id
                    for item in state.events
                )
                if not save_used and self._died_by_reason(state, target.id, "wolf", event.day):
                    witch_player = state.role_player(Role.WITCH)
                    witch_name = witch_player.name if witch_player else "the witch"
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-skill-witch-save-{event.day}-{target.id}",
                            game_id=state.id,
                            day=event.day,
                            phase=event.phase.value,
                            counterfactual_type="skill",
                            original_decision=f"The witch did not save key role {target.name} on night {event.day}.",
                            alternative_decision=f"If the witch had saved {target.name}, the village might retain a high-value {target.role.value} for the next day.",
                            expected_effect=f"Preserving {target.name} could keep more public or private information online.",
                            affected_players=[witch_name, target.name],
                            confidence=0.7,
                            evidence=[f"{target.name} died to the wolf attack on night {event.day}.", f"{target.role.value} is a key village-side role."],
                            severity="major",
                        )
                    )
            if event.type == EventType.HUNTER_SHOT:
                hunter = state.player(str(event.payload.get("hunter_id")))
                target = state.player(str(event.payload.get("target_id")))
                if target.alignment == Alignment.VILLAGE:
                    cases.append(
                        CounterfactualCase(
                            case_id=f"{state.id}-skill-hunter-shot-{event.day}-{hunter.id}",
                            game_id=state.id,
                            day=event.day,
                            phase=event.phase.value,
                            counterfactual_type="skill",
                            original_decision=f"{hunter.name} shot villager-side player {target.name}.",
                            alternative_decision=f"If {hunter.name} had held the shot or targeted a higher-confidence wolf read, the trade could avoid friendly fire.",
                            expected_effect=f"Village-side resources would not be lost to the hunter shot on {target.name}.",
                            affected_players=[hunter.name, target.name],
                            confidence=0.9,
                            evidence=[f"Hunter shot removed {target.name}.", "The shot was flagged as a critical mistake."],
                            severity="critical",
                            source_bad_case_id=self._find_bad_case_id(bad_cases, event.day, hunter.name, "ability"),
                        )
                    )
        return cases

    def _info_release_cases(
        self,
        state: GameState,
        bad_cases: Sequence[BadCaseReport],
        review_bonuses: Sequence[ReviewBonus],
    ) -> list[CounterfactualCase]:
        cases: list[CounterfactualCase] = []
        contexts = self._build_contexts(state)
        for player in state.players:
            if player.role != Role.SEER:
                continue
            ctx = contexts[player.id]
            wolf_checks = [
                event for event in ctx.private_info_events
                if event.payload.get("kind") == "seer_result" and event.payload.get("is_wolf")
            ]
            if not wolf_checks:
                continue
            if any(bonus.player_id == player.id and bonus.bonus_type == "seer_info_conversion" for bonus in review_bonuses):
                continue
            released_targets = self._released_check_targets(ctx)
            for check_event in wolf_checks:
                target_name = str(check_event.payload.get("target_name") or "")
                if target_name and target_name in released_targets:
                    continue
                day = self._first_speech_day(ctx) or check_event.day
                bad_case_id = self._find_bad_case_id(bad_cases, day, player.name, "speech")
                cases.append(
                    CounterfactualCase(
                        case_id=f"{state.id}-info-{day}-{player.id}",
                        game_id=state.id,
                        day=day,
                        phase="DAY_SPEECH",
                        counterfactual_type="info_release",
                        original_decision=f"{player.name} held the wolf result on {target_name} instead of releasing it publicly.",
                        alternative_decision=f"If {player.name} had announced the wolf check on {target_name} during day {day}, the village might align votes earlier.",
                        expected_effect=f"Publicly releasing the check could improve vote convergence onto {target_name} and reduce good-player misvotes.",
                        affected_players=[player.name, target_name],
                        confidence=0.84,
                        evidence=[
                            f"Private seer result identified {target_name} as wolf.",
                            f"No later public speech from {player.name} referenced that result.",
                        ],
                        severity="major",
                        source_bad_case_id=bad_case_id,
                    )
                )
                break
        return cases

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

    def _build_contexts(self, state: GameState) -> dict[str, "_PlayerContext"]:
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

    def _released_check_targets(self, ctx: "_PlayerContext") -> set[str]:
        released_targets: set[str] = set()
        for payload in [event.payload for event in ctx.private_info_events if event.payload.get("kind") == "seer_result"]:
            target_name = str(payload.get("target_name") or "")
            if not target_name:
                continue
            if any(target_name in str(event.payload.get("speech", "")) for event in ctx.speech_events):
                released_targets.add(target_name)
        return released_targets

    def _first_speech_day(self, ctx: "_PlayerContext") -> int | None:
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
        lines.extend([
            "",
            "## 3. 玩家评分榜",
            "",
            "| 排名 | 玩家 | 角色 | 阵营 | 硬规则分 | 复盘加权 | 最终分 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
        ])
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
            lines.append(f"### {review.rank}. {review.player_name}（{ROLE_LABELS.get(review.role, review.role)}，{ALIGNMENT_LABELS.get(review.alignment, review.alignment)}）")
            lines.append(f"- 整体评价：{review.overall_summary}")
            delta = round(review.adjusted_final_score - review.rule_score, 2)
            lines.append(f"- 分数概览：硬规则分 {review.rule_score:.2f}，复盘加权 {delta:+.2f}，最终分 {review.adjusted_final_score:.2f}。")
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
            lines.append(f"- 主要亮点：{'；'.join(self._zh_text(item) for item in review.highlights[:3]) if review.highlights else '无'}")
            lines.append(f"- 主要问题：{'；'.join(self._zh_text(item) for item in review.mistakes[:2]) if review.mistakes else '无'}")
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
                lines.append(f"- [{SEVERITY_LABELS.get(item.priority, item.priority)}] {self._zh_text(item.suggestion)}")
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
        lines.extend(["", "## 9. 说明", f"- {report.metadata.get('leaderboard_note', '跨局表现请查看 Leaderboard 输出，本报告仅针对当前单局。')}"])
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
        if "## Persona Leaderboard" in markdown or "## Role Leaderboard" in markdown or "## Version Leaderboard" in markdown:
            issues.append("错误嵌入完整 Leaderboard")
            fixes.append("移除跨局排行榜正文，只保留单局说明")
        for review in report.player_reviews:
            if not review.suggestions and f"{review.player_name}（" in markdown and "下一局建议：本局无明显复盘建议。" not in markdown:
                issues.append(f"{review.player_name} 的无建议状态表达不一致")
                fixes.append("无明确问题时明确写出本局无明显复盘建议")
                break
        evidence_suggestions = [
            item for item in report.strategy_suggestions
            if not item.metadata.get("evidence_summary")
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
                (sum(values) / len(values)) - role_global_avg[role]
                for role, values in role_buckets.items()
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
                    if role_normalized_components else None,
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
                avg_counterfactual_count = sum(version_game_counterfactuals[version]) / len(version_game_counterfactuals[version])
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
            "adjusted_final_score": score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
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
            1
            for item in bucket
            for mistake in item["mistakes"]
            if str(mistake).startswith("[critical]")
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
        report_list = [reports] if isinstance(reports, ReviewReport) else list(reports)
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
            target_role = suggestion.target if suggestion.target_type == "role" and suggestion.target in self.ROLE_NAMES else "global"
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
        cleaned = re.sub(r"\bthe player is (a|an)?\s*(wolf|seer|witch|hunter|guard|villager)\b", "a role signal appeared", cleaned, flags=re.IGNORECASE)
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
                avg_adjusted_final_score=score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
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
