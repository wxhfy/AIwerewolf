"""Track B shared data types — zero logic, pure data definitions.

Single Responsibility: define all dataclasses and label constants.
No imports from other eval/* modules. No functions with logic.
"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

# ============================================================
# EvidenceRef — standardized evidence references
# ============================================================


@dataclass
class EvidenceRef:
    """Standardised evidence anchor for all review conclusions.

    Every bad case, counterfactual, suggestion, bonus, and score_reason
    MUST link to at least one EvidenceRef.
    """

    phase: str = ""
    turn_index: int | None = None
    actor_id: str | None = None
    target_id: str | None = None
    event_type: str = ""
    public_or_private: str = "public"  # "public" | "private"
    visibility_scope: str = "public"  # "public" | "self_private" | "wolf_team_private" | "postgame_only"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        """Sanitized version for public display — redacts private details."""
        data = self.to_dict()
        if data.get("visibility_scope") in ("self_private", "wolf_team_private"):
            data["summary"] = "[private evidence — redacted]"
            data["actor_id"] = None
            data["target_id"] = None
        return data


# ============================================================
# Safety Flags
# ============================================================


@dataclass
class SafetyFlags:
    """Per-item safety metadata for Track C consumption."""

    safe_for_track_c_learning: bool = True
    safe_for_in_game_retrieval: bool = True
    visibility_scope: str = "public"  # "public" | "self_private" | "wolf_team_private" | "postgame_only"
    contains_player_ids: bool = False
    contains_private_info: bool = False
    contains_absolute_strategy: bool = False
    contains_rule_tampering: bool = False
    contains_visibility_bypass: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# Evolution Candidate — Track B → Track C bridge
# ============================================================


@dataclass
class EvolutionCandidate:
    """A review conclusion packaged for Track C self-evolution consumption."""

    source_type: str = ""  # "bad_case" | "counterfactual" | "suggestion" | "bonus"
    source_id: str = ""
    role: str = ""
    phase: str = ""
    trigger_condition: str = ""
    lesson: str = ""
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    quality_signals: dict[str, float] = field(default_factory=dict)
    visibility_scope: str = "public"
    safe_for_track_c_learning: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# Label Constants
# ============================================================

ROLE_LABELS = {
    "Seer": "预言家",
    "Werewolf": "狼人",
    "Witch": "女巫",
    "Hunter": "猎人",
    "Guard": "守卫",
    "Villager": "村民",
}

ALIGNMENT_LABELS = {"village": "好人阵营", "wolf": "狼人阵营"}

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

MVP_TYPE_LABELS = {"global_mvp": "全局 MVP", "winning_camp_mvp": "胜方 MVP"}

COUNTERFACTUAL_TYPE_LABELS = {
    "vote": "投票反事实",
    "skill": "技能反事实",
    "info_release": "信息释放反事实",
    "witch_poison": "女巫毒药反事实",
    "witch_save": "女巫解药反事实",
    "hunter_shot": "猎人开枪反事实",
    "guard_target": "守卫守护反事实",
    "seer_target": "预言家查验反事实",
    "speech_strategy": "发言策略反事实",
    "stance_flip": "立场转变反事实",
    "claim_timing": "身份跳报反事实",
    "badge_election": "警徽选举反事实",
    "coordination": "团队协调反事实",
}

SEVERITY_LABELS = {"critical": "致命失误", "major": "重大失误", "minor": "轻微失误"}


# ============================================================
# Review Dataclasses
# ============================================================


@dataclass
class ReviewArtifact:
    game_id: str
    winner: str | None
    timeline: list[dict[str, Any]]
    daily_summaries: dict[int, list[str]]
    daily_summary_facts: dict[int, list[dict[str, Any]]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlayerScore:
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
    process_score: float = 0.0
    outcome_bonus: float = 0.0
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
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    rule_based: bool = True
    judge_agreement: float | None = None


@dataclass
class PersonaMetrics:
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
    player_id: str
    bonus_type: str
    score_delta: float
    reason: str
    evidence: list[str]
    confidence: float
    day: int | None = None
    phase: str | None = None
    category: str = "impact"
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    visibility_scope: str = "public"
    safe_for_track_c_learning: bool = True


@dataclass
class MVPResult:
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
    leaderboard_type: str
    entries: list[LeaderboardEntry]
    generated_at: str
    source_games: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BadCaseReport:
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
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    visibility_scope: str = "public"
    safety_flags: SafetyFlags | None = None
    safe_for_track_c_learning: bool = True


@dataclass
class TurningPoint:
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
    player_id: str
    player_name: str
    role: str
    alignment: str
    rule_score: float
    adjusted_final_score: float
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
    effect_type: str = "estimated"
    recomputed_outcome: dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: list[str] = field(default_factory=list)
    # v2 structured fields
    original_action: str = ""
    alternative_action: str = ""
    expected_delta: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    visibility_scope: str = "public"
    safe_for_track_c_learning: bool = True
    actor_id: str = ""
    role: str = ""


@dataclass
class StrategyKnowledge:
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

    def to_public_dict(self) -> dict[str, Any]:
        """Public-safe version that redacts private evidence in safety_flags."""
        data = self.to_dict()
        sf = data.get("safety_flags", {})
        if isinstance(sf, dict) and sf:
            # Redact private_info_items for public consumption
            private_items = sf.get("private_info_items", [])
            if private_items:
                sf["private_info_items"] = ["[redacted]" for _ in private_items]
            data["safety_flags"] = sf
        return data


@dataclass
class ReportEvaluationResult:
    grade: str
    score: float
    issues: list[str] = field(default_factory=list)
    feedback: str = ""
    required_fixes: list[str] = field(default_factory=list)


@dataclass
class ReportOptimizationState:
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


# ============================================================
# DecisionTrace — structured decision audit trail (v2 G2)
# ============================================================


@dataclass
class DecisionTrace:
    """Structured, replayable decision record.

    Captures the complete context of every agent decision for
    post-game review, counterfactual analysis, and audit.

    Three hard constraints:
      1. visible_facts only from final legal input (PlayerView + Memory + Retrieval)
      2. candidate_actions from ActionValidator.legal_actions()
      3. Internal vs Public versions — Public removes prompt text and private info
    """

    decision_id: str
    game_id: str
    agent_id: str
    agent_version: str = "cognitive_v1"
    prompt_hash: str = ""
    prompt_template_version: str = ""

    # Phase context
    phase: str = ""
    day: int = 0

    # === Input provenance ===
    visible_facts: list[str] = field(default_factory=list)
    visible_facts_source: str = ""  # "PlayerView + AllowedMemory + AllowedRetrieval"
    visibility_scope_hash: str = ""

    # === Decision content ===
    belief_delta: dict[str, Any] = field(default_factory=dict)
    candidate_actions: list[dict[str, Any]] = field(default_factory=list)
    chosen_action: str = ""
    confidence: float = 0.0
    rationale: str = ""

    # === Strategy trace ===
    retrieved_strategy_ids: list[str] = field(default_factory=list)
    active_playbook: str | None = None
    strategy_memory_snapshot: dict[str, Any] = field(default_factory=dict)

    # === Model metadata ===
    model_name: str = ""
    provider: str = ""
    token_in: int = 0
    token_out: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0

    # === Audit ===
    validation_errors: int = 0
    fallback_used: bool = False
    fallback_reason: str | None = None
    error_type: str | None = None
    random_seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        """Sanitized version for public display — removes prompt text, costs, seeds."""
        data = self.to_dict()
        # Remove internal-only fields
        for key in (
            "prompt_hash",
            "prompt_template_version",
            "token_in",
            "token_out",
            "cost_usd",
            "random_seed",
            "visibility_scope_hash",
        ):
            data.pop(key, None)
        # Truncate rationale for display
        if len(data.get("rationale", "")) > 300:
            data["rationale"] = data["rationale"][:297] + "..."
        return data
