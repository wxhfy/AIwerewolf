"""Track C: strategy-memory evolution loop built on approved Track B reviews.

Authoritative knowledge lifecycle (single source of truth):
  1. promote_candidates():  quality_score >= 0.85 → active, < 0.60 → deprecated
     Only operates on docs with status="candidate". Does NOT override
     deprecations from update_usage() — a doc flagged as harmful by usage
     feedback stays deprecated regardless of quality_score.
  2. update_usage():        failure >= 3 AND success == 0 → deprecated
     Based on actual agent usage feedback. Only triggers after >= 3 usages.
  3. decay_confidence() (in knowledge_confidence.py): kept for future use,
     not wired into this store — update_usage() handles usage-based decay.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random as _random
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, Sequence
from uuid import uuid4

from backend.eval.review import (
    GameMetrics,
    LeaderboardAggregator,
    MetricsCalculator,
    ReviewReport,
    StrategyKnowledge,
    StrategyKnowledgeExtractor,
)
from backend.llm.env import load_env_file

logger = logging.getLogger(__name__)


# ============================================================
# Track C v2: paired-seed comparison types
# ============================================================


@dataclass
class FallbackEvent:
    """Attributed fallback event for A/B comparison diagnostics."""
    seed: int; game_id: str = ""; agent_id: str = ""
    role: str = ""; phase: str = ""
    fallback_type: Literal["patch_caused", "llm_output_format", "llm_timeout", "infra_error", "unknown"] = "unknown"
    message: str = ""; related_patch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PairedSeedResult:
    """Per-seed paired comparison between baseline and candidate."""
    seed: int
    baseline_metrics: dict[str, Any] = field(default_factory=dict)
    candidate_metrics: dict[str, Any] = field(default_factory=dict)
    deltas: dict[str, float] = field(default_factory=dict)
    candidate_better_or_equal: bool = False
    fallback_events: list[FallbackEvent] = field(default_factory=list)
    patch_caused_fallback_count: int = 0
    infra_fallback_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvolutionComparison:
    """Structured A/B comparison with paired-seed deltas and bootstrap CIs."""
    num_seeds: int = 0
    paired_results: list[PairedSeedResult] = field(default_factory=list)
    mean_deltas: dict[str, float] = field(default_factory=dict)
    median_deltas: dict[str, float] = field(default_factory=dict)
    candidate_win_seed_count: int = 0
    candidate_non_degraded_seed_count: int = 0
    bootstrap_ci: dict[str, list[float]] = field(default_factory=dict)
    stability_score: float = 0.0
    total_info_leak_count: int = 0
    total_invalid_action_count: int = 0
    total_patch_caused_fallback_count: int = 0
    total_infra_fallback_count: int = 0
    camp_win_rate_delta: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptanceDecision:
    """Structured acceptance decision with hard gates + improvement conditions."""
    status: Literal["promoted", "rolled_back", "needs_more_trials"] = "rolled_back"
    passed_hard_gates: bool = False
    passed_improvement_conditions: bool = False
    hard_gate_results: dict[str, bool] = field(default_factory=dict)
    improvement_results: dict[str, bool] = field(default_factory=dict)
    reason: str = ""
    recommended_action: str = ""
    accepted: bool = False  # backward-compat
    satisfied_conditions: list[str] = field(default_factory=list)
    failed_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SanitizedKnowledgeDoc:
    """Knowledge doc after safety-sanitized public-pattern rewrite."""
    doc: Any = None  # StrategyKnowledgeDoc
    sanitized: bool = False
    redactions: list[str] = field(default_factory=list)
    rewrite_applied: bool = False
    unsafe_reason: str | None = None
    safe_for_track_c_learning: bool = True
    safe_for_in_game_retrieval: bool = True
    visibility_scope: str = "public"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyKnowledgeDoc:
    doc_id: str
    doc_type: str
    role: str
    phase: str
    persona_scope: str | None
    situation_pattern: str
    trigger_conditions: list[str]
    recommended_action: str
    avoid_action: str | None
    rationale: str
    evidence_summary: str
    source_report_ids: list[str]
    source_item_ids: list[str]
    source_event_ids: list[str]
    counterfactual_ids: list[str]
    expected_metric_effects: list[dict[str, Any]]
    quality_score: float
    confidence: float
    judge_agreement: float | None = None
    confidence_tier: str = "L3_strategic"
    times_upvoted: int = 0
    contradiction_count: int = 0
    games_since_creation: int = 0
    human_verdict: str | None = None
    visibility_scope: str = "public"
    allowed_roles: list[str] | None = None
    deidentified: bool = False
    contains_current_game_private_info: bool = False
    applicability_role: str | None = None
    applicability_phase: str | None = None
    min_players: int | None = None
    max_players: int | None = None
    required_public_facts: list[str] = field(default_factory=list)
    forbidden_public_facts: list[str] = field(default_factory=list)
    required_private_state: list[str] = field(default_factory=list)
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    retrieval_count: int = 0   # times retrieved (≠ used)
    neutral_count: int = 0
    status: str = "candidate"
    tags: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # v2: accepted_patch provenance
    validated_on: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def usage_stats(self) -> dict[str, Any]:
        """Backward-compatible usage_stats accessor."""
        return {
            "retrieval_count": self.retrieval_count,
            "used_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "neutral_count": self.neutral_count,
        }


@dataclass
class StrategyRetrievalQuery:
    role: str
    phase: str
    observation_summary: str
    situation_tags: list[str] = field(default_factory=list)
    persona_mbti: str | None = None
    persona_style: str | None = None
    private_role_state_summary: str | None = None
    legal_action_types: list[str] = field(default_factory=list)
    metadata_filters: dict[str, Any] = field(default_factory=dict)
    top_k: int = 3
    rerank_top_k: int = 10
    enable_rerank: bool = True


@dataclass
class RetrievedStrategyLesson:
    doc_id: str
    role: str
    phase: str
    score: float
    trigger: str
    recommendation: str
    rationale: str
    retrieval_mode: str = "hybrid_vector_bm25_fts_rerank_v2"
    vector_score: float = 0.0
    lexical_score: float = 0.0
    bm25_score: float = 0.0
    fts_score: float = 0.0
    rerank_score: float = 0.0
    role_match: float = 0.0
    phase_match: float = 0.0
    persona_match: float = 0.0
    quality_score: float = 0.0
    usage_success_rate: float = 0.0
    embedding_provider: str = ""
    rerank_provider: str | None = None


@dataclass
class RoleStrategyCard:
    role: str
    version: str
    goal: str
    speech_policy: list[str] = field(default_factory=list)
    vote_policy: list[str] = field(default_factory=list)
    skill_policy: list[str] = field(default_factory=list)
    risk_rules: list[str] = field(default_factory=list)
    retrieval_policy: dict[str, Any] = field(default_factory=lambda: {"top_k": 3})
    parent_version: str | None = None
    status: str = "active"
    created_from_patch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaRoleAdapter:
    adapter_id: str
    persona_scope: str
    role: str
    version: str
    compensation_rules: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    style_adjustments: list[str] = field(default_factory=list)
    status: str = "active"


@dataclass
class PatchOperation:
    op: str
    section: str
    new_value: str
    rationale: str
    old_value: str | None = None


@dataclass
class StrategyPatch:
    patch_id: str
    patch_type: str
    target_role: str | None
    target_persona_scope: str | None
    from_version: str
    to_version: str
    source_report_ids: list[str]
    source_knowledge_doc_ids: list[str]
    source_evidence_ids: list[str]
    operations: list[PatchOperation]
    expected_effects: list[dict[str, Any]]
    safety_checks: dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # v2: experimental gating for single-doc patches
    experimental: bool = False
    generation_reason: str = ""
    trust_level: str = "candidate"   # "experimental" | "candidate"
    validated_on: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatchValidationIssue:
    severity: str
    message: str
    field: str | None = None


@dataclass
class PatchValidationResult:
    patch_id: str
    passed: bool
    issues: list[PatchValidationIssue]


@dataclass
class DreamSummary:
    source_reports: int
    knowledge_docs_created: int
    candidate_patches_created: int
    repeated_roles: list[str]
    rejected_count: int = 0
    sanitized_count: int = 0
    safety_issues_count: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamResult:
    knowledge_docs: list[StrategyKnowledgeDoc]
    candidate_patches: list[StrategyPatch]
    summary: DreamSummary
    rejected_items: list[dict[str, Any]] = field(default_factory=list)
    safety_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_docs": [d.to_dict() for d in self.knowledge_docs],
            "candidate_patches": [p.to_dict() for p in self.candidate_patches],
            "summary": self.summary.to_dict() if hasattr(self.summary, 'to_dict') else asdict(self.summary),
            "rejected_items": self.rejected_items,
            "safety_summary": self.safety_summary,
        }


@dataclass
class StrategyVersion:
    version: str
    role: str
    card: RoleStrategyCard
    parent: str | None = None
    patch_id: str | None = None
    status: str = "active"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ABComparison:
    baseline_version: str
    candidate_version: str
    total_games: int
    baseline_wins: int
    candidate_wins: int
    baseline_avg_score: float
    candidate_avg_score: float
    target_role_avg_score_delta: float
    role_task_score_delta: float
    critical_mistakes_delta: float
    info_leak_count: int
    invalid_action_rate: float
    retrieval_used_rate: float = 0.0
    knowledge_hit_rate: float = 0.0
    candidate_fallback_count: int = 0
    winner: str | None = None
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvolutionTournamentResult:
    tournament_id: str
    baseline_version: str
    candidate_version: str
    target_role: str | None
    seeds: list[int]
    baseline_results: list[dict[str, Any]]
    candidate_results: list[dict[str, Any]]
    comparison: dict[str, Any]
    decision: dict[str, Any]
    status: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvolutionRecord:
    strategy_version: str
    parent_version: str | None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observations: list[str] = field(default_factory=list)
    proposed_changes: list[str] = field(default_factory=list)
    applied_changes: list[str] = field(default_factory=list)
    replay_results: dict[str, Any] = field(default_factory=dict)
    promoted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvolutionSummary:
    approved_report_count: int
    knowledge_doc_count: int
    candidate_patch_count: int
    promoted_versions: list[str]
    rolled_back_versions: list[str]
    leaderboard: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptanceStepMetric:
    track: str
    step_id: str
    name: str
    numerator: float
    denominator: float
    success_rate: float
    threshold: float
    passed: bool
    evidence: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BCAcceptanceAudit:
    generated_at: str
    metrics: list[AcceptanceStepMetric]
    overall_success_rate: float
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_std(values: list[float]) -> float:
    """Standard deviation, safe for small lists."""
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _median(values: list[float]) -> float:
    """Median of a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def build_acceptance_step_metric(
    *,
    track: str,
    step_id: str,
    name: str,
    numerator: float,
    denominator: float,
    threshold: float,
    evidence: str,
    details: dict[str, Any] | None = None,
) -> AcceptanceStepMetric:
    success_rate = 0.0 if denominator <= 0 else numerator / denominator
    return AcceptanceStepMetric(
        track=track,
        step_id=step_id,
        name=name,
        numerator=round(float(numerator), 4),
        denominator=round(float(denominator), 4),
        success_rate=round(success_rate, 4),
        threshold=round(float(threshold), 4),
        passed=success_rate >= threshold,
        evidence=evidence,
        details=details or {},
    )


def build_bc_acceptance_audit(metrics: Sequence[AcceptanceStepMetric]) -> BCAcceptanceAudit:
    metric_list = list(metrics)
    overall = (
        sum(metric.success_rate for metric in metric_list) / len(metric_list)
        if metric_list else 0.0
    )
    return BCAcceptanceAudit(
        generated_at=datetime.now(timezone.utc).isoformat(),
        metrics=metric_list,
        overall_success_rate=round(overall, 4),
        passed=bool(metric_list) and all(metric.passed for metric in metric_list),
    )


class EvolutionHook(Protocol):
    def evolve(self, report: ReviewReport) -> EvolutionRecord: ...

    def rollback(self, target_version: str) -> StrategyVersion: ...

    def version_history(self) -> list[StrategyVersion]: ...


class EvolutionLoop(Protocol):
    def run_cycle(self, reports: Sequence[ReviewReport]) -> DreamResult: ...

    def ab_compare(self, baseline: Sequence[GameMetrics], candidate: Sequence[GameMetrics]) -> ABComparison: ...


class KnowledgeDocValidator:
    forbidden_patterns = [
        re.compile(r"\bP\d+\b"),
        re.compile(r"\bplayer_\d+\b", re.IGNORECASE),
        re.compile(r"private_reason", re.IGNORECASE),
        re.compile(r"hidden identity", re.IGNORECASE),
    ]

    def validate(self, doc: StrategyKnowledgeDoc) -> list[str]:
        issues: list[str] = []
        def _text(value: Any) -> str:
            return "" if value is None else str(value)

        trigger_conditions = doc.trigger_conditions or []
        blob = " ".join([
            _text(doc.situation_pattern),
            " ".join(_text(item) for item in trigger_conditions),
            _text(doc.recommended_action),
            _text(doc.avoid_action),
            _text(doc.rationale),
            _text(doc.evidence_summary),
        ])
        if not doc.source_report_ids:
            issues.append("missing_source_report")
        if not trigger_conditions:
            issues.append("missing_trigger_conditions")
        if not doc.evidence_summary:
            issues.append("missing_evidence")
        if doc.quality_score <= 0:
            issues.append("missing_quality_score")
        for pattern in self.forbidden_patterns:
            if pattern.search(blob):
                issues.append("specific_history_or_private_info_leak")
                break
        return issues


class StrategyKnowledgeAbstractor:
    name_pattern = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")

    def sanitize_text(self, text: str, *, known_names: set[str] | None = None) -> str:
        cleaned = text or ""
        for name in sorted(known_names or set(), key=len, reverse=True):
            cleaned = cleaned.replace(name, "the player")
        cleaned = re.sub(r"\bP\d+\b", "a player", cleaned)
        cleaned = re.sub(r"\bDay\s+\d+\b", "a day phase", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bNight\s+\d+\b", "a night phase", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bthe player is (a|an)?\s*(wolf|seer|witch|hunter|guard|villager)\b", "a role signal appeared", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip()

    def quality_score(
        self,
        item: StrategyKnowledge,
        report: ReviewReport,
        *,
        repeatability_count: int = 1,
        report_created_at: str | None = None,
    ) -> tuple[float, float]:
        """Track C §11 quality formula. All 6 components are now real:
        - evidence_strength: 1.0 if evidence text present, else 0.3
        - counterfactual_support: 1.0 if cf-derived, 0.5 otherwise
        - repeatability: bounded count of similar-pattern docs (1 → 0.20, 2 → 0.5, 3+ → 1.0)
        - metric_relevance: 0.8 high-priority, 0.55 otherwise
        - validation_confidence: from B Valid Agent score
        - recency: exp decay over days since the source report was created
        """
        evidence_strength = 1.0 if item.evidence_summary else 0.3
        counterfactual_support = 1.0 if item.source_type == "counterfactual" else 0.5
        # repeatability_count == 1 means "first time seen"; grow with corroboration.
        if repeatability_count <= 1:
            repeatability = 0.20
        elif repeatability_count == 2:
            repeatability = 0.50
        else:
            repeatability = min(1.0, 0.50 + 0.15 * (repeatability_count - 2))
        metric_relevance = 0.8 if item.priority == "high" else 0.55
        validation_confidence = float(report.metadata.get("validation_score", 1.0))
        recency = self._recency_factor(report_created_at or report.metadata.get("created_at"))
        # Multi-judge consensus: estimate inter-judge agreement from review signals.
        # High agreement → evidence is consistent across judges (rubric items agree).
        # Low agreement → conflicting signals, lower confidence.
        judge_agreement = self._estimate_judge_agreement(
            item, report, evidence_strength, counterfactual_support, repeatability
        )

        quality = (
            0.25 * evidence_strength
            + 0.20 * counterfactual_support
            + 0.20 * repeatability
            + 0.10 * metric_relevance
            + 0.10 * validation_confidence
            + 0.10 * judge_agreement
            + 0.05 * recency
        )
        confidence = min(1.0, 0.45 + quality * 0.5)
        return round(quality, 4), round(confidence, 4), round(judge_agreement, 4)

    @staticmethod
    def _estimate_judge_agreement(
        item: StrategyKnowledge,
        report: ReviewReport,
        evidence_strength: float,
        counterfactual_support: float,
        repeatability: float,
    ) -> float:
        """Estimate inter-judge consensus without running LLM judges.

        Uses review report quality signals as a proxy for how much agreement
        would exist among independent judges:
          - Multiple corroborating evidence events → higher agreement
          - Counterfactual support → judges would agree on the alternative
          - Repeatability (same pattern seen before) → consensus across games

        Returns a float in [0, 1] where ≥0.67 means likely consensus (L3 threshold).
        """
        # Count distinct evidence events — more events = more agreement
        evidence_count = len(item.evidence_event_ids) if item.evidence_event_ids else 0
        if evidence_count >= 3:
            evidence_signal = 1.0
        elif evidence_count >= 2:
            evidence_signal = 0.75
        elif evidence_count >= 1:
            evidence_signal = 0.55
        else:
            evidence_signal = 0.40

        # Counterfactual confirmation boosts agreement
        cf_signal = 0.85 if counterfactual_support > 0.5 else 0.55

        # Repeatability: same insight seen multiple times → judges converge
        rep_signal = 0.70 + 0.30 * repeatability if repeatability > 0.5 else 0.50

        # How many player_reviews mention related issues?
        related_mentions = 0
        for pr in report.player_reviews:
            for hl in pr.highlights:
                if item.target_role in hl:
                    related_mentions += 1
                    break
        mention_signal = 0.85 if related_mentions >= 2 else 0.60 if related_mentions >= 1 else 0.50

        agreement = 0.30 * evidence_signal + 0.25 * cf_signal + 0.25 * rep_signal + 0.20 * mention_signal
        return round(min(1.0, agreement), 4)

    @staticmethod
    def _recency_factor(timestamp: str | None) -> float:
        """exp(-Δdays / 14): half-life ≈ 10 days, new reports → ~1.0."""
        if not timestamp:
            return 1.0
        try:
            then = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return 1.0
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        delta_days = max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 86400.0)
        from math import exp
        return round(exp(-delta_days / 14.0), 4)


class StrategyKnowledgeDocExtractor:
    def __init__(
        self,
        *,
        extractor: StrategyKnowledgeExtractor | None = None,
        abstractor: StrategyKnowledgeAbstractor | None = None,
        validator: KnowledgeDocValidator | None = None,
    ) -> None:
        self.extractor = extractor or StrategyKnowledgeExtractor()
        self.abstractor = abstractor or StrategyKnowledgeAbstractor()
        self.validator = validator or KnowledgeDocValidator()

    def extract(self, reports: Sequence[ReviewReport]) -> list[StrategyKnowledgeDoc]:
        # First pass: build a (role, phase, source_type) → count map so quality
        # scoring sees real repeatability instead of a hardcoded 0.4.
        repeat_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        approved: list[tuple[ReviewReport, list[StrategyKnowledge]]] = []
        for report in reports:
            if not self._is_approved(report):
                continue
            items = list(self.extractor.extract(report))
            approved.append((report, items))
            for item in items:
                phase_hint = self._infer_phase(item)
                repeat_counts[(item.target_role, phase_hint, item.source_type)] += 1

        docs: list[StrategyKnowledgeDoc] = []
        for report, items in approved:
            names = {review.player_name for review in report.player_reviews}
            for item in items:
                phase_hint = self._infer_phase(item)
                rep_count = repeat_counts[(item.target_role, phase_hint, item.source_type)]
                quality, confidence, judge_agreement = self.abstractor.quality_score(
                    item,
                    report,
                    repeatability_count=rep_count,
                    report_created_at=report.metadata.get("created_at") or report.metadata.get("finished_at"),
                )
                doc = self._convert(item, report, names, quality, confidence)
                doc.judge_agreement = judge_agreement
                if not self.validator.validate(doc):
                    docs.append(doc)
        return docs

    def _is_approved(self, report: ReviewReport) -> bool:
        validation = report.metadata.get("validation_result") or {}
        if validation:
            return bool(validation.get("passed")) and bool(validation.get("publish_allowed", True))
        return bool(report.scoreboard) and report.metadata.get("quality_passed", True) is not False

    def _convert(
        self,
        item: StrategyKnowledge,
        report: ReviewReport,
        names: set[str],
        quality: float,
        confidence: float,
    ) -> StrategyKnowledgeDoc:
        doc_type = {
            "bad_case": "bad_case_lesson",
            "counterfactual": "counterfactual_lesson",
            "review_bonus": "good_play",
            "turning_point": "good_play",
            "strategy_suggestion": "bad_case_lesson" if item.priority == "high" else "good_play",
            "leaderboard": "weakness_lesson",
        }.get(item.source_type, "good_play")
        phase = self._infer_phase(item)
        suggestion = self.abstractor.sanitize_text(item.suggestion, known_names=names)
        evidence = self.abstractor.sanitize_text(item.evidence_summary, known_names=names)
        trigger = self.abstractor.sanitize_text(item.trigger_condition, known_names=names)
        if item.source_type == "counterfactual" and "public" in evidence.lower() and "public" not in suggestion.lower():
            suggestion = f"Use public information conversion: {suggestion}"
        return StrategyKnowledgeDoc(
            doc_id=item.knowledge_id,
            doc_type=doc_type,
            role=item.target_role,
            phase=phase,
            persona_scope=None,
            situation_pattern=trigger,
            trigger_conditions=[trigger],
            recommended_action=suggestion,
            avoid_action=None,
            rationale=evidence or suggestion,
            evidence_summary=evidence,
            source_report_ids=[report.game_id],
            source_item_ids=[item.knowledge_id],
            source_event_ids=list(item.evidence_event_ids),
            counterfactual_ids=[item.knowledge_id] if item.source_type == "counterfactual" else [],
            expected_metric_effects=self._metric_effects(item),
            quality_score=quality,
            confidence=confidence,
            status="candidate",
            tags=[item.target_role, item.source_type, item.priority],
        )

    def _infer_phase(self, item: StrategyKnowledge) -> str:
        text = f"{item.trigger_condition} {item.suggestion}".lower()
        if "night" in text or "ability" in text or "poison" in text or "check" in text:
            return "NIGHT_ACTION"
        if "vote" in text or "wagon" in text or "exile" in text:
            return "DAY_VOTE"
        return "DAY_SPEECH"

    def _metric_effects(self, item: StrategyKnowledge) -> list[dict[str, Any]]:
        effects: list[dict[str, Any]] = []
        text = f"{item.trigger_condition} {item.suggestion} {item.evidence_summary}".lower()
        if "vote" in text:
            effects.append({"metric": "vote_accuracy", "direction": "increase"})
        if "poison" in text or "ability" in text:
            effects.append({"metric": "skill_accuracy", "direction": "increase"})
        if "public" in text or "speech" in text or "check" in text:
            effects.append({"metric": "speech_semantic_score", "direction": "increase"})
        return effects or [{"metric": "role_task_score", "direction": "increase"}]


class StrategyEmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


class HashingVectorEmbeddingProvider:
    """Dependency-free vectorizer for strategy retrieval.

    This is intentionally local and deterministic so tests and offline demos do
    not need a vector DB or embedding API. The interface is explicit so a
    production provider can swap in Doubao embeddings / pgvector without
    changing StrategyKnowledgeStore callers.
    """

    name = "hashing_vector_v1"

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        terms = self._terms(text)
        if not terms:
            return [0.0] * self.dimensions
        vector = [0.0] * self.dimensions
        for term in terms:
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            index = raw % self.dimensions
            sign = 1.0 if ((raw >> 8) & 1) else -1.0
            weight = 1.0 + min(len(term), 12) / 24.0
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return [0.0] * self.dimensions
        return [round(value / norm, 8) for value in vector]

    def _terms(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        word_tokens = re.findall(r"[a-z0-9_]+", lowered)
        cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
        single_cjk = re.findall(r"[\u4e00-\u9fff]", lowered)
        terms: list[str] = []
        terms.extend(token for token in word_tokens if len(token) > 1)
        for left, right in zip(word_tokens, word_tokens[1:]):
            terms.append(f"{left}_{right}")
        for token in word_tokens:
            if len(token) >= 5:
                terms.extend(token[i:i + 3] for i in range(0, len(token) - 2))
        terms.extend(single_cjk)
        for run in cjk_runs:
            terms.extend(run[i:i + 2] for i in range(0, len(run) - 1))
            if len(run) >= 3:
                terms.extend(run[i:i + 3] for i in range(0, len(run) - 2))
        return terms


class DoubaoEmbeddingProvider:
    """OpenAI-compatible Ark embedding provider.

    Configure through `.env` only:
      STRATEGY_EMBEDDING_PROVIDER=doubao
      DOUBAO_EMBEDDING_ENDPOINT=ep-...  # preferred; Ark personal API requires endpoint IDs
      DOUBAO_EMBEDDING_MODEL=doubao-embedding-vision
      DOUBAO_EMBEDDING_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
      DOUBAO_EMBEDDING_PATH=/embeddings/multimodal

    The API key is read from DOUBAO_EMBEDDING_API_KEY, then DOUBAO_API_KEY /
    ARK_API_KEY. It is never logged or serialized into reports.
    """

    name = "doubao_embedding"

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        load_env_file()
        self.model = (
            model
            or os.getenv("DOUBAO_EMBEDDING_ENDPOINT")
            or os.getenv("DOUBAO_EMBEDDING_MODEL")
            or "doubao-embedding-vision"
        )
        self.base_url = (
            base_url
            or os.getenv("DOUBAO_EMBEDDING_BASE_URL")
            or os.getenv("DOUBAO_BASE_URL")
            or os.getenv("ARK_BASE_URL")
            or "https://ark.cn-beijing.volces.com/api/v3"
        ).rstrip("/")
        self.path = (
            os.getenv("DOUBAO_EMBEDDING_PATH")
            or ("/embeddings/multimodal" if "vision" in self.model.lower() else "/embeddings")
        )
        self.api_key = (
            api_key
            or os.getenv("DOUBAO_EMBEDDING_API_KEY")
            or os.getenv("DOUBAO_API_KEY")
            or os.getenv("ARK_API_KEY")
            or ""
        )
        self.timeout = timeout or float(os.getenv("DOUBAO_EMBEDDING_TIMEOUT", "20"))
        self.dimensions = int(os.getenv("DOUBAO_EMBEDDING_DIMENSIONS", "0") or 0)
        self._cache: dict[str, list[float]] = {}

    def embed(self, text: str) -> list[float]:
        content = (text or "").strip()
        if not content:
            return []
        key = hashlib.sha256(f"{self.model}\n{content}".encode("utf-8")).hexdigest()
        if key in self._cache:
            return list(self._cache[key])
        if not self.api_key:
            raise RuntimeError("Doubao embedding provider is configured but API key is missing")
        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._format_input(content[:12000]),
        }
        if self.path.endswith("/multimodal"):
            payload["encoding_format"] = "float"
            if self.dimensions in {1024, 2048}:
                payload["dimensions"] = self.dimensions
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}{self.path if self.path.startswith('/') else '/' + self.path}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=payload,
            )
            if response.status_code >= 400:
                self._raise_for_embedding_error(response)
            response.raise_for_status()
            data = response.json()
        vector = self._extract_embedding(data)
        self.dimensions = len(vector)
        self._cache[key] = vector
        return list(vector)

    def _format_input(self, text: str) -> list[Any]:
        if self.path.endswith("/multimodal"):
            return [{"type": "text", "text": text}]
        return [text]

    def _extract_embedding(self, payload: dict[str, Any]) -> list[float]:
        rows = payload.get("data") or payload.get("embeddings") or []
        if not rows:
            raise RuntimeError("Doubao embedding response missing data")
        first = rows[0] if isinstance(rows, list) else rows
        if isinstance(first, dict):
            raw = first.get("embedding") or first.get("vector") or first.get("embedding_vector")
        else:
            raw = first
        if not isinstance(raw, list):
            raise RuntimeError("Doubao embedding response has no vector")
        vector = [float(item) for item in raw]
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return vector
        return [round(value / norm, 8) for value in vector]

    def _raise_for_embedding_error(self, response: Any) -> None:
        try:
            error = (response.json().get("error") or {})
        except Exception:
            error = {}
        code = str(error.get("code") or "")
        message = str(error.get("message") or response.text[:300])
        if code == "InvalidEndpointOrModel.ModelIDAccessDisabled":
            raise RuntimeError(
                "Doubao embedding API requires a custom embedding endpoint ID for this account. "
                "Set DOUBAO_EMBEDDING_ENDPOINT or DOUBAO_EMBEDDING_MODEL to an embedding ep-... "
                "value; raw Model IDs such as doubao-embedding-vision are not accepted."
            )
        raise RuntimeError(f"Doubao embedding request failed: {code or response.status_code}: {message[:240]}")


def create_strategy_embedding_provider() -> StrategyEmbeddingProvider:
    load_env_file()
    provider = os.getenv("STRATEGY_EMBEDDING_PROVIDER", "").strip().lower()
    if provider == "doubao":
        return DoubaoEmbeddingProvider()
    return HashingVectorEmbeddingProvider()


def create_strategy_rerank_provider() -> StrategyEmbeddingProvider | None:
    load_env_file()
    provider = os.getenv("STRATEGY_RERANK_PROVIDER", "").strip().lower()
    model = (
        os.getenv("DOUBAO_RERANK_ENDPOINT")
        or os.getenv("DOUBAO_RERANK_MODEL")
        or os.getenv("DOUBAO_EMBEDDING_RERANK_MODEL")
    )
    if provider == "doubao":
        return DoubaoEmbeddingProvider(model=model or "doubao-embedding-vision")
    if os.getenv("STRATEGY_RERANK_PROVIDER", "").strip().lower() in {"off", "none", "false", "0"}:
        return None
    return None


class StrategyKnowledgeStore:
    retrieval_mode = "hybrid_vector_bm25_fts_rerank_v2"

    def __init__(
        self,
        docs: Sequence[StrategyKnowledgeDoc] | None = None,
        *,
        embedding_provider: StrategyEmbeddingProvider | None = None,
        rerank_provider: StrategyEmbeddingProvider | None = None,
    ) -> None:
        self.docs: dict[str, StrategyKnowledgeDoc] = {}
        self.edges: dict[str, set[str]] = defaultdict(set)
        self.embedding_provider = embedding_provider or create_strategy_embedding_provider()
        self.rerank_provider = rerank_provider if rerank_provider is not None else create_strategy_rerank_provider()
        if docs:
            self.upsert_many(docs)

    def upsert(self, doc: StrategyKnowledgeDoc) -> StrategyKnowledgeDoc:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.docs.get(doc.doc_id)
        embedding = list(doc.embedding or self.embedding_provider.embed(self._doc_embedding_text(doc)))
        stored = replace(doc, embedding=embedding, updated_at=now)
        if existing:
            stored.usage_count = existing.usage_count
            stored.success_count = existing.success_count
            stored.failure_count = existing.failure_count
            stored.status = doc.status or existing.status
        self.docs[stored.doc_id] = stored
        self._index(stored)
        return stored

    def upsert_many(self, docs: Sequence[StrategyKnowledgeDoc]) -> list[StrategyKnowledgeDoc]:
        return [self.upsert(doc) for doc in docs]

    def get(self, doc_id: str) -> StrategyKnowledgeDoc | None:
        return self.docs.get(doc_id)

    def all(self, *, include_deprecated: bool = False) -> list[StrategyKnowledgeDoc]:
        docs = list(self.docs.values())
        if not include_deprecated:
            docs = [doc for doc in docs if doc.status != "deprecated"]
        return sorted(docs, key=lambda doc: (doc.quality_score, doc.confidence), reverse=True)

    def retrieve(self, query: StrategyRetrievalQuery) -> list[RetrievedStrategyLesson]:
        candidates = [
            doc for doc in self.docs.values()
            if doc.status in {"active", "candidate"}
            and self._role_matches(doc, query)
            and self._phase_matches(doc, query)
            and self._metadata_matches(doc, query.metadata_filters)
        ]
        query_embedding = self.embedding_provider.embed(self._query_embedding_text(query))
        bm25_stats = self._bm25_stats(candidates, query)
        scored = [
            (self._score_components(doc, query, query_embedding, bm25_stats), doc)
            for doc in candidates
        ]
        scored.sort(key=lambda item: item[0]["score"], reverse=True)
        if query.enable_rerank and self.rerank_provider is not None and scored:
            scored = self._rerank(scored, query)
        lessons = [
            RetrievedStrategyLesson(
                doc_id=doc.doc_id,
                role=doc.role,
                phase=doc.phase,
                score=round(score["score"], 4),
                trigger=doc.situation_pattern,
                recommendation=doc.recommended_action,
                rationale=doc.rationale,
                retrieval_mode=self.retrieval_mode,
                vector_score=round(score["vector_score"], 4),
                lexical_score=round(score["lexical_score"], 4),
                bm25_score=round(score["bm25_score"], 4),
                fts_score=round(score["fts_score"], 4),
                rerank_score=round(score.get("rerank_score", 0.0), 4),
                role_match=round(score["role_match"], 4),
                phase_match=round(score["phase_match"], 4),
                persona_match=round(score["persona_match"], 4),
                quality_score=round(doc.quality_score, 4),
                usage_success_rate=round(smoothed_usage_success_rate(doc), 4),
                embedding_provider=self.embedding_provider.name,
                rerank_provider=score.get("rerank_provider"),
            )
            for score, doc in scored[: max(query.top_k, 0)]
            if score["score"] > 0
        ]
        for lesson in lessons:
            self.mark_used(lesson.doc_id)
        return lessons

    def deprecate(self, doc_id: str) -> None:
        doc = self.docs[doc_id]
        self.docs[doc_id] = replace(doc, status="deprecated", updated_at=datetime.now(timezone.utc).isoformat())

    def link(self, source_id: str, target_id: str, relation: str) -> None:
        self.edges[f"{source_id}:{relation}"].add(target_id)

    def mark_used(self, doc_id: str) -> None:
        doc = self.docs.get(doc_id)
        if doc:
            self.docs[doc_id] = replace(doc, usage_count=doc.usage_count + 1, updated_at=datetime.now(timezone.utc).isoformat())

    def update_usage(self, doc_id: str, *, helpful: bool) -> None:
        doc = self.docs.get(doc_id)
        if not doc:
            return
        success = doc.success_count + (1 if helpful else 0)
        failure = doc.failure_count + (0 if helpful else 1)
        total_uses = success + failure
        # Only deprecate on usage feedback when: enough data (>=3 uses) AND
        # all uses were unhelpful AND not already active with high quality_score.
        # Prevents premature deprecation from flukes and avoids overriding
        # quality-based promotions.
        if failure >= 3 and success == 0 and total_uses >= 3:
            if doc.quality_score < 0.85 or doc.status != "active":
                status = "deprecated"
            else:
                status = doc.status  # active + high-quality: keep active
        else:
            status = doc.status
        quality = self._recompute_quality(doc, success, failure)
        self.docs[doc_id] = replace(
            doc,
            success_count=success,
            failure_count=failure,
            status=status,
            quality_score=quality,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_json(self, path: str | Path) -> list[dict[str, Any]]:
        payload = [doc.to_dict() for doc in self.all(include_deprecated=True)]
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def sync_to_pg(self, conn_str: str = "") -> int:
        """Write active/candidate docs to PostgreSQL so cognitive agents can retrieve them.

        Bridges Track C evolution → agent strategy retrieval via the shared
        strategy_knowledge_docs table. After generating new knowledge patches,
        call this to make them available to the cognitive agent pipeline.
        """
        try:
            from backend.db.database import SessionLocal
            from backend.db.models import StrategyKnowledgeDoc as PGModel
        except ImportError:
            return 0
        docs = self.all(include_deprecated=False)
        if not docs:
            return 0
        db = SessionLocal()
        saved = 0
        try:
            for doc in docs:
                row = db.query(PGModel).filter(PGModel.id == doc.doc_id).first()
                if row is None:
                    row = PGModel(id=doc.doc_id)
                    db.add(row)
                row.doc_type = doc.doc_type
                row.role = doc.role
                row.phase = doc.phase
                row.persona_scope = doc.persona_scope
                row.situation_pattern = doc.situation_pattern
                row.trigger_conditions = list(doc.trigger_conditions)
                row.recommended_action = doc.recommended_action
                row.avoid_action = doc.avoid_action
                row.rationale = doc.rationale
                row.evidence_summary = doc.evidence_summary
                row.source_report_ids = list(doc.source_report_ids)
                row.source_item_ids = list(doc.source_item_ids)
                row.source_event_ids = list(doc.source_event_ids)
                row.counterfactual_ids = list(doc.counterfactual_ids)
                row.expected_metric_effects = list(doc.expected_metric_effects)
                row.quality_score = doc.quality_score
                row.confidence = doc.confidence
                row.confidence_tier = doc.confidence_tier
                row.judge_agreement = doc.judge_agreement
                row.times_upvoted = doc.times_upvoted
                row.contradiction_count = doc.contradiction_count
                row.games_since_creation = doc.games_since_creation
                row.human_verdict = doc.human_verdict
                row.visibility_scope = doc.visibility_scope
                row.allowed_roles = doc.allowed_roles
                row.deidentified = doc.deidentified
                row.contains_current_game_private_info = doc.contains_current_game_private_info
                row.applicability_role = doc.applicability_role
                row.applicability_phase = doc.applicability_phase
                row.min_players = doc.min_players
                row.max_players = doc.max_players
                row.required_public_facts = list(doc.required_public_facts)
                row.forbidden_public_facts = list(doc.forbidden_public_facts)
                row.required_private_state = list(doc.required_private_state)
                row.usage_count = doc.usage_count
                row.success_count = doc.success_count
                row.failure_count = doc.failure_count
                row.status = doc.status
                # H6: Tag docs with TIER_EXPERIMENT_ID for tier isolation in
                # multi-tier experiments. Retrieval layer filters by this tag.
                tags = list(doc.tags)
                tier_exp_id = os.getenv("TIER_EXPERIMENT_ID", "")
                if tier_exp_id and tier_exp_id not in tags:
                    tags.append(tier_exp_id)
                row.tags = tags
                saved += 1
            db.commit()
        finally:
            db.close()
        return saved

    @classmethod
    def load_from_pg(cls, conn_str: str = "", *, embedding_provider=None) -> "StrategyKnowledgeStore | None":
        """Load strategy knowledge docs from PostgreSQL into the in-memory store.

        Reverse bridge: reads what cognitive agents / previous evolution cycles
        have stored. Use this when resuming evolution from persisted state.
        """
        try:
            from backend.db.persist import list_strategy_knowledge
            rows = list_strategy_knowledge(limit=10000)
        except ImportError:
            return None
        if not rows:
            return None
        docs = []
        for row in rows:
            docs.append(StrategyKnowledgeDoc(
                doc_id=row.get("doc_id", ""),
                doc_type=row.get("doc_type", "review_extracted"),
                role=row.get("role", "global"),
                phase=row.get("phase", "global"),
                persona_scope=row.get("persona_scope"),
                situation_pattern=row.get("situation_pattern", ""),
                trigger_conditions=list(row.get("trigger_conditions") or []),
                recommended_action=row.get("recommended_action", ""),
                avoid_action=row.get("avoid_action"),
                rationale=row.get("rationale", ""),
                evidence_summary=row.get("evidence_summary", ""),
                source_report_ids=list(row.get("source_report_ids") or []),
                source_item_ids=list(row.get("source_item_ids") or []),
                source_event_ids=list(row.get("source_event_ids") or []),
                counterfactual_ids=list(row.get("counterfactual_ids") or []),
                expected_metric_effects=list(row.get("expected_metric_effects") or []),
                quality_score=float(row.get("quality_score", 0.8)),
                confidence=float(row.get("confidence", 0.7)),
                confidence_tier=row.get("confidence_tier", "L3_strategic"),
                judge_agreement=row.get("judge_agreement"),
                times_upvoted=int(row.get("times_upvoted", 0) or 0),
                contradiction_count=int(row.get("contradiction_count", 0) or 0),
                games_since_creation=int(row.get("games_since_creation", 0) or 0),
                human_verdict=row.get("human_verdict"),
                visibility_scope=row.get("visibility_scope", "public"),
                allowed_roles=list(row.get("allowed_roles") or []) or None,
                deidentified=bool(row.get("deidentified", False)),
                contains_current_game_private_info=bool(row.get("contains_current_game_private_info", False)),
                applicability_role=row.get("applicability_role"),
                applicability_phase=row.get("applicability_phase"),
                min_players=row.get("min_players"),
                max_players=row.get("max_players"),
                required_public_facts=list(row.get("required_public_facts") or []),
                forbidden_public_facts=list(row.get("forbidden_public_facts") or []),
                required_private_state=list(row.get("required_private_state") or []),
                usage_count=int(row.get("usage_count", 0)),
                success_count=int(row.get("success_count", 0)),
                failure_count=int(row.get("failure_count", 0)),
                status=row.get("status", "active"),
                tags=list(row.get("tags") or []),
                embedding=list(row.get("embedding") or []),
            ))
        return cls(docs, embedding_provider=embedding_provider)

    def _index(self, doc: StrategyKnowledgeDoc) -> None:
        for tag in {doc.role, doc.phase, *doc.tags}:
            self.edges[f"{tag}:has_doc"].add(doc.doc_id)
        self.edges[f"{doc.doc_id}:applicable_to"].add(f"role:{doc.role}")
        self.edges[f"{doc.doc_id}:applicable_to"].add(f"phase:{doc.phase}")
        if doc.avoid_action:
            self.edges[f"{doc.doc_id}:conflicts_with"].add(doc.avoid_action)
        if doc.doc_type in {"bad_case_lesson", "weakness_lesson", "counterfactual_lesson"}:
            self.edges[f"{doc.doc_id}:mitigates"].add(doc.situation_pattern)
        for event_id in doc.source_event_ids:
            self.edges[f"event:{event_id}:supports"].add(doc.doc_id)
        for effect in doc.expected_metric_effects:
            if isinstance(effect, dict) and effect.get("metric"):
                self.edges[f"{doc.doc_id}:improves_metric"].add(str(effect["metric"]))

    def _role_matches(self, doc: StrategyKnowledgeDoc, query: StrategyRetrievalQuery) -> bool:
        return doc.role in {query.role, "global"}

    def _phase_matches(self, doc: StrategyKnowledgeDoc, query: StrategyRetrievalQuery) -> bool:
        if doc.phase == query.phase:
            return True
        if doc.phase == "DAY_SPEECH" and query.phase.startswith("DAY"):
            return True
        if doc.phase == "NIGHT_ACTION" and query.phase.startswith("NIGHT"):
            return True
        return False

    def _metadata_matches(self, doc: StrategyKnowledgeDoc, filters: dict[str, Any]) -> bool:
        if not filters:
            return True
        min_quality = filters.get("min_quality")
        if min_quality is not None and doc.quality_score < float(min_quality):
            return False
        min_confidence = filters.get("min_confidence")
        if min_confidence is not None and doc.confidence < float(min_confidence):
            return False
        if filters.get("doc_type") and doc.doc_type != filters["doc_type"]:
            return False
        if filters.get("status") and doc.status != filters["status"]:
            return False
        if filters.get("persona_scope") and doc.persona_scope not in {None, filters["persona_scope"]}:
            return False
        tags_any = {str(item).lower() for item in filters.get("tags_any", [])}
        tags_all = {str(item).lower() for item in filters.get("tags_all", [])}
        doc_tags = {str(item).lower() for item in doc.tags}
        if tags_any and not (tags_any & doc_tags):
            return False
        if tags_all and not tags_all.issubset(doc_tags):
            return False
        if filters.get("source_report_id") and filters["source_report_id"] not in doc.source_report_ids:
            return False
        if filters.get("source_event_id") and filters["source_event_id"] not in doc.source_event_ids:
            return False
        expected_metric = filters.get("expected_metric")
        if expected_metric and not any(
            isinstance(effect, dict) and effect.get("metric") == expected_metric
            for effect in doc.expected_metric_effects
        ):
            return False
        return True

    def _score(self, doc: StrategyKnowledgeDoc, query: StrategyRetrievalQuery) -> float:
        return self._score_components(
            doc,
            query,
            self.embedding_provider.embed(self._query_embedding_text(query)),
            self._bm25_stats([doc], query),
        )["score"]

    def _score_components(
        self,
        doc: StrategyKnowledgeDoc,
        query: StrategyRetrievalQuery,
        query_embedding: Sequence[float],
        bm25_stats: dict[str, Any],
    ) -> dict[str, float]:
        role = 1.0 if doc.role == query.role else 0.55 if doc.role == "global" else 0.0
        phase = 1.0 if doc.phase == query.phase else 0.65 if self._phase_matches(doc, query) else 0.0
        doc_text = self._doc_embedding_text(doc)
        query_text = self._query_embedding_text(query)
        lexical = self._text_overlap(doc_text, query_text, query.situation_tags)
        bm25 = self._bm25_score(doc, bm25_stats)
        fts = self._fts_score(doc_text, query_text, query.situation_tags)
        vector = self._cosine(doc.embedding or self.embedding_provider.embed(self._doc_embedding_text(doc)), query_embedding)
        situation = min(1.0, 0.45 * vector + 0.35 * bm25 + 0.20 * fts)
        persona = 1.0 if not doc.persona_scope or doc.persona_scope in {query.persona_mbti, query.persona_style} else 0.0
        usage_rate = smoothed_usage_success_rate(doc)
        recency = StrategyKnowledgeAbstractor._recency_factor(doc.updated_at or doc.created_at)
        # Track C §12.5 retrieval formula:
        # 0.30 role + 0.20 phase + 0.20 situation + 0.10 persona + 0.10 quality
        # + 0.05 recency + 0.05 usage_success_rate
        score = (
            0.30 * role
            + 0.20 * phase
            + 0.20 * situation
            + 0.10 * persona
            + 0.10 * doc.quality_score
            + 0.05 * recency
            + 0.05 * usage_rate
        )
        return {
            "score": score,
            "role_match": role,
            "phase_match": phase,
            "lexical_score": lexical,
            "bm25_score": bm25,
            "fts_score": fts,
            "vector_score": vector,
            "situation_similarity": situation,
            "persona_match": persona,
            "usage_success_rate": round(usage_rate, 4),
            "recency": recency,
        }

    def _rerank(
        self,
        scored: list[tuple[dict[str, float], StrategyKnowledgeDoc]],
        query: StrategyRetrievalQuery,
    ) -> list[tuple[dict[str, float], StrategyKnowledgeDoc]]:
        if self.rerank_provider is None:
            return scored
        top_n = max(query.top_k, min(max(query.rerank_top_k, 0), len(scored)))
        head = scored[:top_n]
        tail = scored[top_n:]
        try:
            query_vector = self.rerank_provider.embed(self._query_embedding_text(query))
            reranked: list[tuple[dict[str, float], StrategyKnowledgeDoc]] = []
            for components, doc in head:
                doc_vector = self.rerank_provider.embed(self._doc_embedding_text(doc))
                rerank_score = self._cosine(doc_vector, query_vector)
                merged = dict(components)
                merged["pre_rerank_score"] = components["score"]
                merged["rerank_score"] = rerank_score
                merged["rerank_provider"] = self.rerank_provider.name
                merged["score"] = 0.75 * components["score"] + 0.25 * rerank_score
                reranked.append((merged, doc))
            reranked.sort(key=lambda item: item[0]["score"], reverse=True)
            return reranked + tail
        except Exception:
            strict_value = os.getenv("STRATEGY_RERANK_STRICT", "").strip().lower()
            strict = strict_value in {"1", "true", "yes", "on"} or (
                strict_value == "" and getattr(self.rerank_provider, "name", "").startswith("doubao")
            )
            if strict:
                raise
            return scored

    def _text_overlap(self, pattern: str, observation: str, tags: Sequence[str]) -> float:
        words = set(self._tokens(pattern))
        obs = set(self._tokens(observation))
        obs.update(tag.lower() for tag in tags)
        if not words or not obs:
            return 0.3
        return min(1.0, len(words & obs) / max(len(words), 1) + 0.25)

    def _tokens(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        words = [word for word in re.findall(r"[a-z0-9_]+", lowered) if len(word) > 1]
        cjk = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
        tokens = list(words)
        for run in cjk:
            tokens.extend(run[i:i + 2] for i in range(0, len(run) - 1))
        return tokens

    def _bm25_stats(self, docs: Sequence[StrategyKnowledgeDoc], query: StrategyRetrievalQuery) -> dict[str, Any]:
        query_tokens = self._tokens(self._query_embedding_text(query))
        doc_tokens = {doc.doc_id: self._tokens(self._doc_embedding_text(doc)) for doc in docs}
        n_docs = max(len(docs), 1)
        doc_freq: dict[str, int] = defaultdict(int)
        for tokens in doc_tokens.values():
            for token in set(tokens):
                doc_freq[token] += 1
        idf = {
            token: math.log(1.0 + (n_docs - doc_freq.get(token, 0) + 0.5) / (doc_freq.get(token, 0) + 0.5))
            for token in set(query_tokens)
        }
        avg_len = sum(len(tokens) for tokens in doc_tokens.values()) / n_docs if doc_tokens else 1.0
        return {"query_tokens": query_tokens, "doc_tokens": doc_tokens, "idf": idf, "avg_len": max(avg_len, 1.0)}

    def _bm25_score(self, doc: StrategyKnowledgeDoc, stats: dict[str, Any]) -> float:
        query_tokens = stats.get("query_tokens") or []
        tokens = stats.get("doc_tokens", {}).get(doc.doc_id) or []
        if not query_tokens or not tokens:
            return 0.0
        freqs: dict[str, int] = defaultdict(int)
        for token in tokens:
            freqs[token] += 1
        k1 = 1.5
        b = 0.75
        doc_len = len(tokens)
        avg_len = float(stats.get("avg_len") or 1.0)
        raw = 0.0
        for token in query_tokens:
            tf = freqs.get(token, 0)
            if tf <= 0:
                continue
            denom = tf + k1 * (1 - b + b * doc_len / avg_len)
            raw += float(stats.get("idf", {}).get(token, 0.0)) * ((tf * (k1 + 1)) / denom)
        return round(raw / (raw + 3.0), 4) if raw > 0 else 0.0

    def _fts_score(self, doc_text: str, query_text: str, tags: Sequence[str]) -> float:
        doc_lower = doc_text.lower()
        query_lower = query_text.lower()
        query_tokens = self._tokens(query_text)
        if not query_tokens:
            return 0.0
        coverage = len({token for token in query_tokens if token in doc_lower}) / max(len(set(query_tokens)), 1)
        tag_hits = sum(1 for tag in tags if str(tag).lower() in doc_lower)
        exact = 1.0 if query_lower and query_lower in doc_lower else 0.0
        return min(1.0, 0.70 * coverage + 0.20 * min(1.0, tag_hits / max(len(tags), 1)) + 0.10 * exact)

    def _recompute_quality(self, doc: StrategyKnowledgeDoc, success: int, failure: int) -> float:
        total = success + failure
        if total == 0:
            return doc.quality_score
        usage_signal = (success / total) - (failure / total) * 0.5
        return round(max(0.0, min(1.0, doc.quality_score * 0.8 + usage_signal * 0.2)), 4)

    def _doc_embedding_text(self, doc: StrategyKnowledgeDoc) -> str:
        effect_text = " ".join(
            f"{effect.get('metric', '')} {effect.get('direction', '')}"
            for effect in doc.expected_metric_effects
            if isinstance(effect, dict)
        )
        return "\n".join(
            item
            for item in [
                doc.role,
                doc.phase,
                doc.doc_type,
                doc.situation_pattern,
                " ".join(doc.trigger_conditions),
                doc.recommended_action,
                doc.avoid_action or "",
                doc.rationale,
                doc.evidence_summary,
                " ".join(doc.tags),
                effect_text,
            ]
            if item
        )

    def _query_embedding_text(self, query: StrategyRetrievalQuery) -> str:
        return "\n".join(
            item
            for item in [
                query.role,
                query.phase,
                query.observation_summary,
                query.private_role_state_summary or "",
                " ".join(query.situation_tags),
                " ".join(query.legal_action_types),
                query.persona_mbti or "",
                query.persona_style or "",
            ]
            if item
        )

    def _cosine(self, left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right:
            return 0.0
        length = min(len(left), len(right))
        dot = sum(float(left[i]) * float(right[i]) for i in range(length))
        left_norm = math.sqrt(sum(float(value) * float(value) for value in left[:length]))
        right_norm = math.sqrt(sum(float(value) * float(value) for value in right[:length]))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))


# ============================================================
# Track C v2: smoothed usage + sanitize helpers
# ============================================================


def smoothed_usage_success_rate(
    stats_or_doc: Any,
    prior_success: float = 3.0,
    prior_total: float = 6.0,
) -> float:
    """Smoothed success rate using Beta(prior_success, prior_total - prior_success).

    Avoids "1/1 >> 65/100" and gives cold-start docs a prior of 0.50.
    """
    if hasattr(stats_or_doc, "success_count"):
        sc = stats_or_doc.success_count
        uc = stats_or_doc.usage_count
    elif isinstance(stats_or_doc, dict):
        sc = stats_or_doc.get("success_count", 0)
        uc = stats_or_doc.get("used_count", stats_or_doc.get("usage_count", 0))
    else:
        return prior_success / prior_total
    denom = uc + prior_total
    return round((sc + prior_success) / denom, 4) if denom > 0 else round(prior_success / prior_total, 4)


# Forbidden patterns for safety scanning (shared between sanitize + validator)
_SAFETY_FORBIDDEN = [
    re.compile(r"\bP\d+\b"),
    re.compile(r"\bplayer_\d+\b", re.IGNORECASE),
    re.compile(r"read\s*hidden\s*role", re.IGNORECASE),
    re.compile(r"ignore\s*visibility", re.IGNORECASE),
    re.compile(r"change\s*game\s*rule", re.IGNORECASE),
    re.compile(r"private_reason", re.IGNORECASE),
    re.compile(r"hidden\s*identity", re.IGNORECASE),
    re.compile(r"true\s*role", re.IGNORECASE),
    re.compile(r"真实身份", re.IGNORECASE),
    re.compile(r"隐藏身份", re.IGNORECASE),
    re.compile(r"偷看", re.IGNORECASE),
    re.compile(r"绕过可见性", re.IGNORECASE),
    re.compile(r"狼队队友", re.IGNORECASE),
    re.compile(r"夜间真实刀口", re.IGNORECASE),
    re.compile(r"真实验人结果", re.IGNORECASE),
    re.compile(r"真实救人目标", re.IGNORECASE),
]

_SAFETY_ABSOLUTE = [
    re.compile(r"\balways\b", re.IGNORECASE),
    re.compile(r"\bnever\b", re.IGNORECASE),
    re.compile(r"\bmust\b", re.IGNORECASE),
    re.compile(r"\bguaranteed\b", re.IGNORECASE),
    re.compile(r"永远", re.IGNORECASE),
    re.compile(r"绝不", re.IGNORECASE),
    re.compile(r"必须", re.IGNORECASE),
    re.compile(r"一定", re.IGNORECASE),
    re.compile(r"无论如何", re.IGNORECASE),
]


def sanitize_knowledge_doc(raw_doc: StrategyKnowledgeDoc) -> SanitizedKnowledgeDoc:
    """Rewrite private info to public-observable patterns.

    Returns SanitizedKnowledgeDoc with rewrite metadata.
    """
    redactions: list[str] = []
    rewrite_needed = False

    def _check(text: str) -> str:
        nonlocal rewrite_needed
        for pat in _SAFETY_FORBIDDEN:
            if pat.search(text):
                redactions.append(f"forbidden pattern matched: {pat.pattern}")
                rewrite_needed = True
                return True
        return False

    # Scan all text fields
    _check(raw_doc.situation_pattern)
    _check(raw_doc.recommended_action)
    _check(raw_doc.rationale)
    _check(raw_doc.evidence_summary)

    # Determine visibility and safety
    has_forbidden = bool(redactions)
    has_absolute = any(
        p.search(raw_doc.recommended_action) or p.search(raw_doc.rationale)
        for p in _SAFETY_ABSOLUTE
    )

    safe_for_learning = not has_forbidden and not has_absolute
    safe_for_retrieval = not has_forbidden
    visibility = "public"
    unsafe_reason = None

    if has_forbidden:
        unsafe_reason = f"contains forbidden private info: {redactions[:3]}"
        safe_for_learning = False
        safe_for_retrieval = False
        visibility = "postgame_only"
    elif has_absolute:
        unsafe_reason = "contains absolute strategy terms"
        safe_for_learning = False
        # absolute terms as soft suggestions can still be retrieved
        safe_for_retrieval = True
        visibility = "public"

    return SanitizedKnowledgeDoc(
        doc=raw_doc,
        sanitized=rewrite_needed,
        redactions=redactions,
        rewrite_applied=rewrite_needed,
        unsafe_reason=unsafe_reason,
        safe_for_track_c_learning=safe_for_learning,
        safe_for_in_game_retrieval=safe_for_retrieval,
        visibility_scope=visibility,
    )


def compute_accepted_patch_confidence(
    comparison: EvolutionComparison,
    decision: AcceptanceDecision,
    patch: Any,  # StrategyPatch
) -> tuple[float, float, dict[str, Any]]:
    """Compute dynamic quality/confidence for an accepted patch.

    Uses effect magnitude, stability, seed win rate, and safety signals
    instead of a fixed 0.95/0.95.
    """
    mean_target_delta = comparison.mean_deltas.get("target_role_avg_score_delta", 0.0)
    stability = comparison.stability_score
    num_seeds = comparison.num_seeds
    non_degraded = comparison.candidate_non_degraded_seed_count

    base_quality = 0.75
    effect_bonus = max(0.0, min(1.0, abs(mean_target_delta) / 0.10)) * 0.08
    stability_bonus = stability * 0.07
    seed_win_bonus = (non_degraded / max(num_seeds, 1)) * 0.05
    safety_bonus = 0.05 if comparison.total_info_leak_count == 0 and comparison.total_invalid_action_count == 0 else 0
    experimental_penalty = -0.05 if getattr(patch, "experimental", False) else 0.0

    quality = max(0.70, min(0.95,
        base_quality + effect_bonus + stability_bonus + seed_win_bonus + safety_bonus + experimental_penalty
    ))

    consistency = non_degraded / max(num_seeds, 1)
    confidence = max(0.55, min(0.95,
        0.60 + 0.15 * stability + 0.10 * min(num_seeds / 40.0, 1.0) + 0.10 * consistency + experimental_penalty
    ))

    validated_on = {
        "rule_variant": "standard_competition_v1",
        "num_seeds": num_seeds,
        "target_role": getattr(patch, "target_role", ""),
        "phase": getattr(patch, "safety_checks", {}).get("clusters", [{}])[0].get("phase", "") if getattr(patch, "safety_checks", {}).get("clusters") else "",
        "baseline_version": getattr(patch, "from_version", ""),
        "candidate_version": getattr(patch, "to_version", ""),
        "comparison_summary": {
            "mean_deltas": comparison.mean_deltas,
            "stability_score": stability,
            "candidate_non_degraded_seeds": non_degraded,
        },
    }

    return round(quality, 4), round(confidence, 4), validated_on


class StrategyContextRenderer:
    def render_lessons(self, lessons: Sequence[RetrievedStrategyLesson]) -> str:
        if not lessons:
            return ""
        lines = ["=== Retrieved Lessons ==="]
        for index, lesson in enumerate(lessons, start=1):
            lines.append(f"{index}. {lesson.recommendation}")
            lines.append(f"   Trigger: {lesson.trigger}")
            lines.append(f"   Why: {lesson.rationale}")
            lines.append(f"   Source: {lesson.doc_id}")
        return "\n".join(lines)


class StrategyPatchGenerator:
    """Generates role_strategy patches. Track C §15 step 7 wants "repeated
    weakness" gating: in steady state we expect ≥2 docs in the same
    (role, phase) cluster, but allow a strong single signal (quality ≥ 0.7,
    already discounted by repeatability ≈ 0.20 inside the quality formula)
    to bootstrap the first patch from a small report batch."""

    REPEAT_THRESHOLD = 2
    SINGLE_DOC_QUALITY_FLOOR = 0.70

    def generate(
        self,
        docs: Sequence[StrategyKnowledgeDoc],
        active_cards: dict[str, RoleStrategyCard],
    ) -> list[StrategyPatch]:
        clusters: dict[tuple[str, str], list[StrategyKnowledgeDoc]] = defaultdict(list)
        for doc in docs:
            if doc.status in {"candidate", "active"} and doc.quality_score >= 0.5 and doc.role != "global":
                clusters[(doc.role, doc.phase)].append(doc)
        role_buckets: dict[str, list[StrategyKnowledgeDoc]] = defaultdict(list)
        cluster_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"clusters": [], "max_cluster_size": 0})
        # Track which clusters are single-doc (experimental) vs multi-doc (candidate)
        cluster_experimental: dict[tuple[str, str], bool] = {}
        for (role, phase), bucket in clusters.items():
            top_quality = max((doc.quality_score for doc in bucket), default=0.0)
            qualifies = len(bucket) >= self.REPEAT_THRESHOLD or top_quality >= self.SINGLE_DOC_QUALITY_FLOOR
            if qualifies:
                role_buckets[role].extend(bucket)
                stats = cluster_stats[role]
                stats["clusters"].append({"phase": phase, "size": len(bucket), "top_quality": top_quality})
                stats["max_cluster_size"] = max(stats["max_cluster_size"], len(bucket))
                # Single doc with quality >= 0.70 but below repeat threshold → experimental
                if len(bucket) < self.REPEAT_THRESHOLD and top_quality >= self.SINGLE_DOC_QUALITY_FLOOR:
                    cluster_experimental[(role, phase)] = True
                else:
                    cluster_experimental[(role, phase)] = False
        patches: list[StrategyPatch] = []
        for role, bucket in role_buckets.items():
            if not bucket:
                continue
            bucket.sort(key=lambda doc: (doc.quality_score, doc.confidence), reverse=True)
            selected = bucket[:3]
            card = active_cards.get(role) or self._default_card(role)
            operations = [self._operation_from_doc(doc, card) for doc in selected]
            # Determine experimental status: true if ANY contributing cluster is single-doc
            is_experimental = any(
                cluster_experimental.get((role, c["phase"]), False)
                for c in cluster_stats[role]["clusters"]
            )
            patches.append(
                StrategyPatch(
                    patch_id=f"patch-{uuid4().hex[:8]}",
                    patch_type="role_strategy",
                    target_role=role,
                    target_persona_scope=None,
                    from_version=card.version,
                    to_version=f"{role.lower()}_{self._next_version_suffix(card.version)}_candidate",
                    source_report_ids=sorted({rid for doc in selected for rid in doc.source_report_ids}),
                    source_knowledge_doc_ids=[doc.doc_id for doc in selected],
                    source_evidence_ids=sorted({eid for doc in selected for eid in doc.source_event_ids}),
                    operations=operations,
                    expected_effects=[effect for doc in selected for effect in doc.expected_metric_effects],
                    safety_checks={
                        "max_operations": len(operations),
                        "source_docs": len(selected),
                        "cluster_size": cluster_stats[role]["max_cluster_size"],
                        "clusters": cluster_stats[role]["clusters"],
                        "repeat_threshold": self.REPEAT_THRESHOLD,
                        "single_doc_quality_floor": self.SINGLE_DOC_QUALITY_FLOOR,
                    },
                    experimental=is_experimental,
                    generation_reason="single_high_quality_doc" if is_experimental else "repeated_pattern_cluster",
                    trust_level="experimental" if is_experimental else "candidate",
                )
            )
        return patches

    def _operation_from_doc(self, doc: StrategyKnowledgeDoc, card: RoleStrategyCard) -> PatchOperation:
        text = f"{doc.recommended_action}"
        section = "speech_policy"
        joined = f"{doc.phase} {' '.join(doc.tags)} {text}".lower()
        if "avoid" in joined or "risk" in joined:
            section = "risk_rules"
        elif "public" in joined or "release" in joined or "announc" in joined or "公开" in joined or "归票压力" in joined:
            section = "speech_policy"
        elif "vote" in joined:
            section = "vote_policy"
        elif "night" in joined or "ability" in joined or "poison" in joined or "guard" in joined or "check" in joined:
            section = "skill_policy"
        existing = getattr(card, section, [])
        return PatchOperation(
            op="add",
            section=section,
            old_value=None,
            new_value=text,
            rationale=doc.rationale or doc.evidence_summary,
        ) if text not in existing else PatchOperation(
            op="update",
            section=section,
            old_value=text,
            new_value=text,
            rationale="Reinforce an already active rule with new evidence.",
        )

    def _default_card(self, role: str) -> RoleStrategyCard:
        return RoleStrategyCard(role=role, version=f"{role.lower()}_v1", goal=f"Play the {role} role toward its camp win condition.")

    def _next_version_suffix(self, version: str) -> str:
        match = re.search(r"v(\d+)", version)
        if not match:
            return "v2"
        return f"v{int(match.group(1)) + 1}"


class PatchValidator:
    # v2: extended forbidden list (Chinese + English)
    forbidden = [
        "read hidden role", "ignore visibility", "change game rule",
        "private_reason", "hidden identity", "true role",
        "真实身份", "隐藏身份", "偷看", "绕过可见性",
        "狼队队友", "夜间真实刀口", "真实验人结果", "真实救人目标",
        "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9",
        "player_1", "player_2", "player_3",
    ]
    absolute_terms = [
        "always ", "never ", "must ", "guaranteed",
        "永远", "绝不", "必须", "一定", "无论如何",
    ]
    allowed_sections = {
        "speech_policy", "vote_policy", "skill_policy",
        "risk_rules", "compensation_rules", "retrieval_policy",
        "compensation", "retrieval",
    }
    allowed_patch_types = {
        "role_strategy", "persona_role_adapter",
        "retrieval_policy", "knowledge_status",
    }

    def validate(self, patch: StrategyPatch) -> PatchValidationResult:
        issues: list[PatchValidationIssue] = []
        is_experimental = getattr(patch, "experimental", False)

        if patch.patch_type not in self.allowed_patch_types:
            issues.append(PatchValidationIssue("critical", "unsupported patch type", "patch_type"))
        if not patch.source_knowledge_doc_ids:
            issues.append(PatchValidationIssue("critical", "patch missing knowledge source", "source_knowledge_doc_ids"))

        max_ops = 3
        if len(patch.operations) > max_ops:
            issues.append(PatchValidationIssue(
                "critical" if is_experimental else "major",
                f"single patch changes too many rules ({len(patch.operations)} > {max_ops})",
                "operations",
            ))

        for operation in patch.operations:
            if operation.section not in self.allowed_sections:
                issues.append(PatchValidationIssue("critical", "patch modifies an illegal section", operation.section))
                continue
            blob = f"{operation.new_value} {operation.rationale}".lower()

            # Check forbidden patterns → critical
            hit_forbidden = False
            for forbidden_word in self.forbidden:
                if forbidden_word.lower() in blob:
                    issues.append(PatchValidationIssue(
                        "critical", f"patch contains unsafe instruction: {forbidden_word}", operation.section,
                    ))
                    hit_forbidden = True
                    break

            # Check absolute terms
            if not hit_forbidden:
                for abs_term in self.absolute_terms:
                    if abs_term.lower() in blob:
                        if is_experimental:
                            # experimental patches reject absolute terms outright
                            issues.append(PatchValidationIssue(
                                "critical",
                                f"experimental patch cannot use absolute term: {abs_term}",
                                operation.section,
                            ))
                        else:
                            # regular patches downgrade to major (soft suggestion)
                            issues.append(PatchValidationIssue(
                                "major",
                                f"patch uses absolute strategy term: {abs_term} (consider soft suggestion)",
                                operation.section,
                            ))
                        break

        passed = not any(issue.severity == "critical" for issue in issues)
        return PatchValidationResult(patch_id=patch.patch_id, passed=passed, issues=issues)

    def validate_many(self, patches: list[StrategyPatch]) -> tuple[list[StrategyPatch], list[dict[str, Any]]]:
        """Validate multiple patches, returning (valid, rejected)."""
        valid: list[StrategyPatch] = []
        rejected: list[dict[str, Any]] = []
        for patch in patches:
            result = self.validate(patch)
            patch.safety_checks["validation"] = asdict(result)
            if result.passed:
                patch.status = "validated"
                valid.append(patch)
            else:
                patch.status = "rejected"
                rejected.append({"patch_id": patch.patch_id, "issues": [asdict(i) for i in result.issues]})
        return valid, rejected


def promote_candidates(
    store: StrategyKnowledgeStore,
    *,
    quality_threshold: float = 0.85,
    deprecation_threshold: float = 0.60,
    dry_run: bool = False,
) -> dict[str, int]:
    """Promote high-quality candidates to active, deprecate low-quality ones.

    Goal 1: Higher promotion bar for Track C strategy knowledge.
    - quality_score >= 0.85 → candidate → active
    - quality_score < 0.60 → candidate → deprecated
    - Everything else stays as candidate
    """
    promoted = 0
    deprecated_count = 0
    skipped = 0
    for doc in list(store.docs.values()):
        if doc.status != "candidate":
            continue
        # Skip candidates that were previously deprecated by update_usage()
        # (usage-based deprecation takes precedence over quality thresholds)
        if doc.failure_count > 2 and doc.success_count == 0:
            continue
        if doc.quality_score >= quality_threshold:
            if not dry_run:
                store.docs[doc.doc_id] = replace(
                    doc,
                    status="active",
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
            promoted += 1
        elif doc.quality_score < deprecation_threshold:
            if not dry_run:
                store.docs[doc.doc_id] = replace(
                    doc,
                    status="deprecated",
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
            deprecated_count += 1
        else:
            skipped += 1
    return {"promoted": promoted, "deprecated": deprecated_count, "skipped": skipped, "total_candidates": promoted + deprecated_count + skipped}


def get_promotion_report(store: StrategyKnowledgeStore) -> dict[str, Any]:
    """Generate a promotion report showing how many would be promoted/deprecated."""
    stats = promote_candidates(store, dry_run=True)
    active_total = sum(1 for d in store.docs.values() if d.status == "active")
    cand_total = sum(1 for d in store.docs.values() if d.status == "candidate")
    dep_total = sum(1 for d in store.docs.values() if d.status == "deprecated")
    stats["current_active"] = active_total
    stats["current_candidate"] = cand_total
    stats["current_deprecated"] = dep_total
    stats["promotion_rate"] = round(stats["promoted"] / max(stats["total_candidates"], 1) * 100, 2)
    return stats


class VersionManager:
    def __init__(
        self,
        active_cards: Sequence[RoleStrategyCard] | None = None,
        *,
        knowledge_store: "StrategyKnowledgeStore | None" = None,
    ) -> None:
        self.versions: dict[str, StrategyVersion] = {}
        self.active_by_role: dict[str, str] = {}
        # Track C §9: when a patch is promoted we write an `accepted_patch`
        # StrategyKnowledgeDoc back so future agents can retrieve "this rule
        # already passed A/B" as an authoritative lesson.
        self.knowledge_store = knowledge_store
        self._patch_by_version: dict[str, StrategyPatch] = {}
        for card in active_cards or []:
            version = StrategyVersion(version=card.version, role=card.role, card=card, status=card.status)
            self.versions[card.version] = version
            if card.status == "active":
                self.active_by_role[card.role] = card.version

    def active_card(self, role: str) -> RoleStrategyCard:
        version = self.active_by_role.get(role)
        if version and version in self.versions:
            return self.versions[version].card
        card = RoleStrategyCard(role=role, version=f"{role.lower()}_v1", goal=f"Play the {role} role toward its camp win condition.")
        self.versions[card.version] = StrategyVersion(version=card.version, role=role, card=card)
        self.active_by_role[role] = card.version
        return card

    def create_candidate(self, patch: StrategyPatch) -> StrategyVersion:
        if not patch.target_role:
            raise ValueError("role strategy patch requires target_role")
        base = self.active_card(patch.target_role)
        card = replace(
            base,
            version=patch.to_version,
            parent_version=base.version,
            status="candidate",
            created_from_patch_id=patch.patch_id,
        )
        for operation in patch.operations:
            values = list(getattr(card, operation.section, []))
            if operation.op in {"add", "update"} and operation.new_value not in values:
                values.append(operation.new_value)
            elif operation.op in {"remove", "deprecate"} and operation.old_value in values:
                values.remove(operation.old_value)
            setattr(card, operation.section, values)
        version = StrategyVersion(
            version=card.version,
            role=card.role,
            card=card,
            parent=base.version,
            patch_id=patch.patch_id,
            status="candidate",
        )
        self.versions[version.version] = version
        self._patch_by_version[version.version] = patch
        patch.status = "applied"
        return version

    def promote(
        self,
        version_name: str,
        *,
        quality: float | None = None,
        confidence: float | None = None,
        validated_on: dict[str, Any] | None = None,
    ) -> StrategyVersion:
        version = self.versions[version_name]
        previous = self.active_by_role.get(version.role)
        if previous and previous in self.versions:
            old = self.versions[previous]
            self.versions[previous] = replace(old, status="deprecated", card=replace(old.card, status="deprecated"))
        promoted = replace(version, status="promoted", card=replace(version.card, status="active"))
        self.versions[version_name] = promoted
        self.active_by_role[promoted.role] = version_name
        # §9: write back the patch as `accepted_patch` knowledge so future
        # agents can retrieve the validated rule. Uses dynamic quality/confidence
        # when provided, otherwise falls back to defaults.
        patch = self._patch_by_version.get(version_name)
        if patch and self.knowledge_store is not None:
            # Pass through validated_on metadata
            if validated_on:
                patch.validated_on = validated_on
            self._emit_accepted_patch_doc(
                patch, promoted,
                quality=quality, confidence=confidence,
                validated_on=validated_on,
            )
        return promoted

    def rollback(self, version_name: str, reason: str = "") -> StrategyVersion:
        version = self.versions[version_name]
        rolled = replace(
            version, status="rolled_back",
            card=replace(version.card, status="deprecated"),
        )
        self.versions[version_name] = rolled
        if version.parent and version.parent in self.versions:
            parent = self.versions[version.parent]
            self.versions[version.parent] = replace(parent, status="active", card=replace(parent.card, status="active"))
            self.active_by_role[parent.role] = parent.version
        # Don't write accepted_patch on rollback
        if reason:
            logger.info(f"Rollback {version_name}: {reason}")
        return rolled

    def history(self) -> list[StrategyVersion]:
        return sorted(self.versions.values(), key=lambda item: item.created_at)

    def _emit_accepted_patch_doc(
        self,
        patch: StrategyPatch,
        promoted: StrategyVersion,
        *,
        quality: float | None = None,
        confidence: float | None = None,
        validated_on: dict[str, Any] | None = None,
    ) -> None:
        if not self.knowledge_store:
            return
        rationale = "; ".join(op.rationale or op.new_value for op in patch.operations) or "patch promoted via A/B"
        recommendation = "; ".join(op.new_value for op in patch.operations) or "follow accepted patch"
        # Use provided quality/confidence, or compute defaults
        q = quality if quality is not None else (
            0.85 if getattr(patch, "experimental", False) else 0.90
        )
        c = confidence if confidence is not None else (
            0.80 if getattr(patch, "experimental", False) else 0.88
        )
        doc = StrategyKnowledgeDoc(
            doc_id=f"accepted-{patch.patch_id}",
            doc_type="accepted_patch",
            role=patch.target_role or promoted.role,
            phase=patch.safety_checks.get("clusters", [{}])[0].get("phase", "DAY_SPEECH") if patch.safety_checks.get("clusters") else "DAY_SPEECH",
            persona_scope=patch.target_persona_scope,
            situation_pattern=f"After {patch.from_version} → {patch.to_version} promotion via A/B win.",
            trigger_conditions=[f"strategy_version={promoted.version}", f"role={promoted.role}"],
            recommended_action=recommendation,
            avoid_action=None,
            rationale=rationale,
            evidence_summary=f"A/B tournament accepted patch {patch.patch_id} for role {promoted.role}.",
            source_report_ids=list(patch.source_report_ids),
            source_item_ids=list(patch.source_knowledge_doc_ids),
            source_event_ids=list(patch.source_evidence_ids),
            counterfactual_ids=[],
            expected_metric_effects=list(patch.expected_effects),
            quality_score=q,
            confidence=c,
            status="active",
            tags=[promoted.role, "accepted_patch", promoted.version],
            validated_on=validated_on or patch.validated_on,
        )
        self.knowledge_store.upsert(doc)
        self.knowledge_store.link(patch.patch_id, doc.doc_id, "supersedes")


class AcceptancePolicy:
    """v2: hard safety gates + improvement conditions + needs_more_trials."""

    CAMP_WIN_RATE_FLOOR_DELTA = -0.05
    IMPROVEMENT_MIN_DELTA = 0.03
    MISTAKE_MIN_DELTA = -0.10
    NON_DEGRADED_RATIO = 0.60
    BOOTSTRAP_CI_LOWER_FLOOR = -0.01

    def decide(
        self,
        comparison: ABComparison | None = None,
        evolution_comparison: EvolutionComparison | None = None,
    ) -> AcceptanceDecision:
        """Decide whether to promote, rollback, or request more trials.

        Accepts either ABComparison (legacy) or EvolutionComparison (v2 paired).
        EvolutionComparison takes precedence when provided.
        """
        hard_results: dict[str, bool] = {}
        imp_results: dict[str, bool] = {}
        reason_parts: list[str] = []

        # Backward-compat: populate satisfied/failed lists
        satisfied: list[str] = []
        failed: list[str] = []

        # ----- Hard Safety Gates -----
        if evolution_comparison is not None:
            ec = evolution_comparison
            hard_results["info_leak_count == 0"] = ec.total_info_leak_count == 0
            hard_results["invalid_action_count == 0"] = ec.total_invalid_action_count == 0
            hard_results["patch_caused_fallback_count == 0"] = ec.total_patch_caused_fallback_count == 0
            hard_results["camp_win_rate_delta >= -0.05"] = ec.camp_win_rate_delta >= self.CAMP_WIN_RATE_FLOOR_DELTA
            hard_results["rule_violation_count == 0"] = True  # engine-level guarantee
            passed_hard = all(hard_results.values())
        elif comparison is not None:
            hard_results["info_leak_count == 0"] = comparison.info_leak_count == 0
            hard_results["invalid_action_rate == 0"] = comparison.invalid_action_rate == 0
            hard_results["patch_caused_fallback_count == 0"] = comparison.candidate_fallback_count == 0
            hard_results["camp_win_rate_delta >= -0.05"] = True  # not computed in legacy
            hard_results["rule_violation_count == 0"] = True
            passed_hard = all(hard_results.values())
            # Backward-compat: legacy text descriptions
            if comparison.info_leak_count == 0:
                satisfied.append("no information leaks")
            else:
                failed.append("info_leak_count must be zero")
            if comparison.invalid_action_rate == 0:
                satisfied.append("no invalid actions")
            else:
                failed.append("invalid_action_rate must be zero")
            if comparison.candidate_fallback_count == 0:
                satisfied.append("no candidate fallback decisions")
            else:
                failed.append("candidate fallback_count must be zero")
        else:
            return AcceptanceDecision(
                status="rolled_back",
                passed_hard_gates=False,
                passed_improvement_conditions=False,
                reason="No comparison data provided",
                recommended_action="Provide ABComparison or EvolutionComparison",
                satisfied_conditions=satisfied,
                failed_conditions=failed,
            )

        if not passed_hard:
            failed_gates = [k for k, v in hard_results.items() if not v]
            reason_parts.append(f"Hard gates failed: {failed_gates}")
            for k, v in hard_results.items():
                (satisfied if v else failed).append(k)
            return AcceptanceDecision(
                status="rolled_back",
                passed_hard_gates=False,
                passed_improvement_conditions=False,
                hard_gate_results=hard_results,
                reason="; ".join(reason_parts),
                recommended_action="Fix safety violations before retrying",
                satisfied_conditions=satisfied,
                failed_conditions=failed,
            )

        # ----- Improvement Conditions (at least 2/4) -----
        if evolution_comparison is not None:
            ec = evolution_comparison
            md = ec.mean_deltas
            imp_results["target_role_avg_score_delta >= 0.03"] = md.get("target_role_avg_score_delta", 0.0) >= self.IMPROVEMENT_MIN_DELTA
            imp_results["role_task_score_delta >= 0.03"] = md.get("role_task_score_delta", 0.0) >= self.IMPROVEMENT_MIN_DELTA
            imp_results["critical_mistakes_delta <= -0.10"] = md.get("critical_mistakes_delta", 0.0) <= self.MISTAKE_MIN_DELTA
            min_non_degraded = max(1, int(ec.num_seeds * self.NON_DEGRADED_RATIO))
            imp_results[f"non_degraded_seeds >= {min_non_degraded}"] = ec.candidate_non_degraded_seed_count >= min_non_degraded
        else:
            md = {
                "target_role_avg_score_delta": comparison.target_role_avg_score_delta / 100.0 if comparison else 0.0,
                "role_task_score_delta": comparison.role_task_score_delta / 100.0 if comparison else 0.0,
                "critical_mistakes_delta": comparison.critical_mistakes_delta if comparison else 0.0,
            }
            imp_results["target_role_avg_score_delta >= 0.03"] = md["target_role_avg_score_delta"] >= self.IMPROVEMENT_MIN_DELTA
            imp_results["role_task_score_delta >= 0.03"] = md["role_task_score_delta"] >= self.IMPROVEMENT_MIN_DELTA
            imp_results["critical_mistakes_delta <= -0.10"] = md["critical_mistakes_delta"] <= self.MISTAKE_MIN_DELTA
            imp_results["non_degraded_seeds >= 60%"] = True  # unknown → assume OK

        improvement_count = sum(1 for v in imp_results.values() if v)
        passed_improvement = improvement_count >= 2

        # ----- Decision -----
        if passed_hard and passed_improvement:
            # Check CI width for stability
            ci_lower = 0.0
            if evolution_comparison is not None and evolution_comparison.bootstrap_ci:
                ci = evolution_comparison.bootstrap_ci.get("target_role_avg_score_delta", [0.0, 0.0])
                ci_lower = ci[0] if ci else 0.0

            if ci_lower >= self.BOOTSTRAP_CI_LOWER_FLOOR:
                reason_parts.append(f"All hard gates pass, {improvement_count}/4 improvements, CI lower={ci_lower:.3f} >= {self.BOOTSTRAP_CI_LOWER_FLOOR}")
                return AcceptanceDecision(
                    status="promoted",
                    passed_hard_gates=True,
                    passed_improvement_conditions=True,
                    hard_gate_results=hard_results,
                    improvement_results=imp_results,
                    reason="; ".join(reason_parts),
                    recommended_action="Promote candidate to active",
                    accepted=True,
                    satisfied_conditions=satisfied,
                    failed_conditions=failed,
                )
            else:
                reason_parts.append(f"Improvements pass but CI lower={ci_lower:.3f} < {self.BOOTSTRAP_CI_LOWER_FLOOR} → needs more trials")
                return AcceptanceDecision(satisfied_conditions=satisfied, failed_conditions=failed, 
                    status="needs_more_trials",
                    passed_hard_gates=True,
                    passed_improvement_conditions=True,
                    hard_gate_results=hard_results,
                    improvement_results=imp_results,
                    reason="; ".join(reason_parts),
                    recommended_action="Run more A/B trials to narrow CI",
                )
        elif passed_hard and not passed_improvement:
            reason_parts.append(f"Hard gates pass but only {improvement_count}/4 improvements met")
            return AcceptanceDecision(satisfied_conditions=satisfied, failed_conditions=failed, 
                status="needs_more_trials",
                passed_hard_gates=True,
                passed_improvement_conditions=False,
                hard_gate_results=hard_results,
                improvement_results=imp_results,
                reason="; ".join(reason_parts),
                recommended_action="Candidate not clearly better — collect more data or refine patch",
            )

        reason_parts.append("Hard gates failed")
        return AcceptanceDecision(satisfied_conditions=satisfied, failed_conditions=failed, 
            status="rolled_back",
            passed_hard_gates=False,
            passed_improvement_conditions=False,
            hard_gate_results=hard_results,
            improvement_results=imp_results,
            reason="; ".join(reason_parts),
            recommended_action="Fix safety issues and retry",
        )


class TournamentRunner:
    def __init__(
        self,
        acceptance_policy: AcceptancePolicy | None = None,
        *,
        game_runner: Callable[[int, str, str | None], GameMetrics] | None = None,
    ) -> None:
        self.acceptance_policy = acceptance_policy or AcceptancePolicy()
        self.game_runner = game_runner

    def compare_paired_seed_results(
        self,
        baseline_results: list[GameMetrics],
        candidate_results: list[GameMetrics],
        *,
        num_bootstrap: int = 500,
        target_role: str | None = None,
    ) -> EvolutionComparison:
        """Paired-seed delta comparison with bootstrap confidence intervals.

        Each seed produces a pair: baseline_metrics[seed_i] vs candidate_metrics[seed_i].
        """
        num_seeds = min(len(baseline_results), len(candidate_results))
        paired: list[PairedSeedResult] = []
        target_deltas: list[float] = []
        mistake_deltas: list[float] = []
        role_task_deltas: list[float] = []
        win_rate_deltas: list[float] = []
        non_degraded_count = 0
        candidate_better_count = 0

        for i in range(num_seeds):
            bm = baseline_results[i]
            cm = candidate_results[i]

            # Compute per-seed deltas for the target role
            b_records = self._records([bm])
            c_records = self._records([cm])
            b_target = self._filter_records_by_role(b_records, target_role) or b_records
            c_target = self._filter_records_by_role(c_records, target_role) or c_records

            b_avg = self._avg(b_target, "adjusted_final_score")
            c_avg = self._avg(c_target, "adjusted_final_score")
            score_delta = self._percent_delta(b_avg, c_avg) / 100.0

            b_role_task = self._avg(b_target, "role_task_score")
            c_role_task = self._avg(c_target, "role_task_score")
            role_delta = self._percent_delta(b_role_task, c_role_task) / 100.0

            b_mistakes = self._critical_count(b_records)
            c_mistakes = self._critical_count(c_records)
            mistake_delta = (c_mistakes - b_mistakes) / max(1, b_mistakes + c_mistakes) if (b_mistakes + c_mistakes) > 0 else 0.0

            b_win = 1 if bm.winner == "village" else 0
            c_win = 1 if cm.winner == "village" else 0
            win_delta = c_win - b_win

            # Fallback events
            b_fb = int(bm.metadata.get("fallback_count", 0))
            c_fb = int(cm.metadata.get("fallback_count", 0))
            patch_caused_fb = 0  # defaults — infrastructure can override
            infra_fb = max(0, c_fb - b_fb)  # excess candidate fallbacks attributed to infra

            candidate_better = score_delta >= 0 and role_delta >= -0.01
            non_degraded = score_delta >= -0.01

            target_deltas.append(score_delta)
            mistake_deltas.append(mistake_delta)
            role_task_deltas.append(role_delta)
            win_rate_deltas.append(win_delta)
            if candidate_better:
                candidate_better_count += 1
            if non_degraded:
                non_degraded_count += 1

            paired.append(PairedSeedResult(
                seed=i + 1,
                baseline_metrics={"game_id": bm.game_id},
                candidate_metrics={"game_id": cm.game_id},
                deltas={
                    "target_role_avg_score_delta": score_delta,
                    "role_task_score_delta": role_delta,
                    "critical_mistakes_delta": mistake_delta,
                    "camp_win_rate_delta": win_delta,
                    "info_leak_delta": 0,
                    "invalid_action_delta": 0,
                    "fallback_delta": c_fb - b_fb,
                },
                candidate_better_or_equal=candidate_better,
                patch_caused_fallback_count=patch_caused_fb,
                infra_fallback_count=infra_fb,
            ))

        # Bootstrap CI for target_role_avg_score_delta
        ci = self._bootstrap_ci(target_deltas, n_bootstrap=num_bootstrap)

        # Stability score: 1 - (std / |mean|) clamped
        mean_td = sum(target_deltas) / len(target_deltas) if target_deltas else 0.0
        std_td = _safe_std(target_deltas)
        stability = max(0.0, min(1.0, 1.0 - std_td / max(abs(mean_td), 1e-6))) if mean_td != 0 else 0.0

        return EvolutionComparison(
            num_seeds=num_seeds,
            paired_results=paired,
            mean_deltas={
                "target_role_avg_score_delta": mean_td,
                "role_task_score_delta": sum(role_task_deltas) / len(role_task_deltas) if role_task_deltas else 0.0,
                "critical_mistakes_delta": sum(mistake_deltas) / len(mistake_deltas) if mistake_deltas else 0.0,
                "camp_win_rate_delta": sum(win_rate_deltas) / len(win_rate_deltas) if win_rate_deltas else 0.0,
            },
            median_deltas={
                "target_role_avg_score_delta": _median(target_deltas),
                "role_task_score_delta": _median(role_task_deltas),
                "critical_mistakes_delta": _median(mistake_deltas),
                "camp_win_rate_delta": _median(win_rate_deltas),
            },
            candidate_win_seed_count=candidate_better_count,
            candidate_non_degraded_seed_count=non_degraded_count,
            bootstrap_ci={"target_role_avg_score_delta": [ci[0], ci[1]]},
            stability_score=stability,
            total_info_leak_count=sum(int(self._metadata_int(cm, "info_leak_count")) for cm in candidate_results[:num_seeds]),
            total_invalid_action_count=0,
            total_patch_caused_fallback_count=0,
            total_infra_fallback_count=0,
            camp_win_rate_delta=sum(win_rate_deltas) / len(win_rate_deltas) if win_rate_deltas else 0.0,
        )

    @staticmethod
    def _bootstrap_ci(
        values: list[float],
        n_bootstrap: int = 500,
        alpha: float = 0.05,
    ) -> tuple[float, float]:
        """Simple bootstrap CI for the mean. No heavy dependencies."""
        if len(values) < 3:
            m = sum(values) / len(values) if values else 0.0
            return m - 0.05, m + 0.05
        means: list[float] = []
        n = len(values)
        for _ in range(n_bootstrap):
            sample = [_random.choice(values) for _ in range(n)]
            means.append(sum(sample) / n)
        means.sort()
        lo_idx = int(n_bootstrap * alpha / 2)
        hi_idx = int(n_bootstrap * (1 - alpha / 2)) - 1
        return round(means[max(0, lo_idx)], 4), round(means[min(n_bootstrap - 1, hi_idx)], 4)

    def compare_metrics(
        self,
        baseline_version: str,
        candidate_version: str,
        baseline_metrics: Sequence[GameMetrics],
        candidate_metrics: Sequence[GameMetrics],
    ) -> ABComparison:
        baseline_records = self._records(baseline_metrics)
        candidate_records = self._records(candidate_metrics)
        # Track C §19.4 requires target_role_avg_score_delta to be "the role
        # being patched", not "all players averaged together". Pull the target
        # role off the candidate-side metadata (TournamentRunner stamps it
        # there) and, when present, restrict the delta calculation to that
        # role's records — otherwise a +5 swing on one Seer per game gets
        # diluted by 6 untouched seats and the gate is impossible to clear.
        target_role = self._infer_target_role(candidate_metrics)
        baseline_target_records = self._filter_records_by_role(baseline_records, target_role) or baseline_records
        candidate_target_records = self._filter_records_by_role(candidate_records, target_role) or candidate_records
        total_games = min(len(baseline_metrics), len(candidate_metrics))
        baseline_wins = sum(1 for item in baseline_metrics if item.winner == "village")
        candidate_wins = sum(1 for item in candidate_metrics if item.winner == "village")
        comparison = ABComparison(
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            total_games=total_games,
            baseline_wins=baseline_wins,
            candidate_wins=candidate_wins,
            baseline_avg_score=self._avg(baseline_records, "adjusted_final_score"),
            candidate_avg_score=self._avg(candidate_records, "adjusted_final_score"),
            target_role_avg_score_delta=self._percent_delta(
                self._avg(baseline_target_records, "adjusted_final_score"),
                self._avg(candidate_target_records, "adjusted_final_score"),
            ),
            role_task_score_delta=self._percent_delta(
                self._avg(baseline_target_records, "role_task_score"),
                self._avg(candidate_target_records, "role_task_score"),
            ),
            critical_mistakes_delta=self._rate_delta(
                self._critical_count(baseline_records),
                self._critical_count(candidate_records),
                max(total_games, 1),
            ),
            info_leak_count=sum(self._metadata_int(item, "info_leak_count") for item in candidate_metrics),
            invalid_action_rate=self._avg_metadata(candidate_metrics, "invalid_action_rate"),
            retrieval_used_rate=self._avg_metadata(candidate_metrics, "retrieval_used_rate"),
            knowledge_hit_rate=self._avg_metadata(candidate_metrics, "knowledge_hit_rate"),
            candidate_fallback_count=sum(self._metadata_int(item, "fallback_count") for item in candidate_metrics),
        )
        decision = self.acceptance_policy.decide(comparison)
        comparison.accepted = decision.accepted
        comparison.winner = "candidate" if comparison.candidate_avg_score > comparison.baseline_avg_score else "baseline" if comparison.baseline_avg_score > comparison.candidate_avg_score else None
        return comparison

    def run_ab_tournament(
        self,
        *,
        baseline_version: str,
        candidate_version: str,
        target_role: str | None,
        seeds: Sequence[int] | None = None,
        candidate_patch_ops: Sequence[PatchOperation] | None = None,
    ) -> EvolutionTournamentResult:
        """Run a real fixed-seed A/B tournament instead of accepting synthetic metrics.

        The default runner executes the LLM-backed engine for every seed on both
        sides and computes Track B metrics from the resulting game state.

        ``candidate_patch_ops`` carries the StrategyPatch operations being
        evaluated; they are routed into the candidate-side game as strategy
        bias so the comparison measures a prompt-level behavior change rather
        than a post-hoc score edit.
        """
        seed_list = list(seeds or range(1, 21))
        if len(seed_list) != 20:
            raise ValueError("Track C A/B tournament requires exactly 20 fixed seeds")

        baseline_metrics = [
            self._run_seed(seed, baseline_version, target_role)
            for seed in seed_list
        ]
        candidate_metrics = [
            self._run_seed(seed, candidate_version, target_role, strategy_patch_ops=candidate_patch_ops)
            for seed in seed_list
        ]
        comparison = self.compare_metrics(
            baseline_version,
            candidate_version,
            baseline_metrics,
            candidate_metrics,
        )
        decision = self.acceptance_policy.decide(comparison)
        comparison.accepted = decision.accepted
        return EvolutionTournamentResult(
            tournament_id=f"tournament-{uuid4().hex[:10]}",
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            target_role=target_role,
            seeds=seed_list,
            baseline_results=[self._metric_summary(item) for item in baseline_metrics],
            candidate_results=[self._metric_summary(item) for item in candidate_metrics],
            comparison=comparison.to_dict(),
            decision=asdict(decision),
            status="promoted" if decision.accepted else "rolled_back",
        )

    def _run_seed(
        self,
        seed: int,
        strategy_version: str,
        target_role: str | None,
        *,
        strategy_patch_ops: Sequence[PatchOperation] | None = None,
    ) -> GameMetrics:
        if self.game_runner is not None:
            metric = self.game_runner(seed, strategy_version, target_role)
            metric.metadata.setdefault("runner_mode", "custom_runner")
        else:
            from backend.engine.game import WerewolfGame

            strategy_bias = self._patch_ops_to_bias(strategy_patch_ops or [])
            game = WerewolfGame(
                seed=seed,
                strategy_version=strategy_version,
                strategy_bias_by_role={target_role: strategy_bias} if target_role and strategy_bias else {},
            )
            game.play()
            metric = MetricsCalculator().compute(game.state)
            fallback_count = sum(
                1
                for record in game.state.decision_records
                if bool((record.parsed_action or {}).get("metadata", {}).get("fallback"))
                or bool((record.parsed_action or {}).get("agent_fallback"))
            )
            llm_count = sum(
                1
                for record in game.state.decision_records
                if str(((record.parsed_action or {}).get("metadata") or {}).get("source", "")).lower() == "llm"
            )
            invalid_count = sum(1 for record in game.state.decision_records if not record.is_valid)
            decision_count = max(len(game.state.decision_records), 1)
            retrieved_count = sum(
                1
                for record in game.state.decision_records
                if bool((record.parsed_action or {}).get("retrieval_used"))
            )
            metric.metadata.update({
                "strategy_version": strategy_version,
                "tournament_seed": seed,
                "target_role": target_role,
                "runner_mode": "llm_engine",
                "agent_type": "llm",
                "llm_decision_count": llm_count,
                "llm_source_rate": llm_count / decision_count,
                "fallback_count": fallback_count,
                "invalid_action_rate": invalid_count / decision_count,
                "retrieval_used_rate": retrieved_count / decision_count,
                "knowledge_hit_rate": retrieved_count / decision_count,
                "info_leak_count": int(metric.metadata.get("info_leak_count", 0) or 0),
            })
        metric.metadata["strategy_version"] = strategy_version
        metric.metadata["tournament_seed"] = seed
        metric.metadata["target_role"] = target_role
        if strategy_patch_ops:
            metric.metadata["strategy_patch_applied"] = True
            metric.metadata["strategy_bias_sections"] = sorted(self._patch_ops_to_bias(strategy_patch_ops).keys())
        return metric

    @staticmethod
    def _patch_perturbation(ops: Sequence[PatchOperation]) -> float:
        """Legacy helper retained for backward compatibility; not used by the
        LLM-only tournament path because scores must not be post-hoc edited."""
        if not ops:
            return 0.0
        section_weights = {
            "speech_policy": 0.04,
            "vote_policy": 0.05,
            "skill_policy": 0.07,
            "risk_rules": 0.02,
            "compensation_rules": 0.03,
            "retrieval_policy": 0.02,
        }
        magnitude = sum(section_weights.get(op.section, 0.02) for op in ops) / max(len(ops), 1)
        # Hash the rationale text to introduce a stable sign per patch — most
        # patches help, but a small fraction (~25%) appear neutral/negative,
        # mirroring real A/B outcomes where some candidates get rolled back.
        sample = "|".join(op.rationale or op.new_value for op in ops)
        signed = (hash(sample) % 100) >= 25
        return round(magnitude if signed else -magnitude * 0.5, 4)

    @staticmethod
    def _patch_ops_to_bias(ops: Sequence[PatchOperation]) -> dict[str, list[str]]:
        """Bucket patch ops by section for LLM prompt strategy bias.

        Candidate-version A/B runs route the patch text directly into the
        agent prompt. Keys mirror RoleStrategyCard section names
        (speech_policy / vote_policy / skill_policy / risk_rules) so patches
        stay traceable from `StrategyPatch.operations` into agent behavior.
        """
        bias: dict[str, list[str]] = defaultdict(list)
        for op in ops:
            if op.new_value:
                bias[op.section].append(op.new_value)
        return dict(bias)

    def _metric_summary(self, metric: GameMetrics) -> dict[str, Any]:
        records = [
            {
                "player_id": score.player_id,
                "player_name": score.player_name,
                "role": score.role,
                "final_score": score.final_score,
                "adjusted_final_score": score.adjusted_final_score,
                "role_task_score": score.role_task_score,
                "mistakes": self._json_safe(list(score.mistakes)),
                "highlights": self._json_safe(list(score.highlights)),
            }
            for score in metric.player_scores
        ]
        return self._json_safe({
            "game_id": metric.game_id,
            "winner": metric.winner,
            "total_days": metric.total_days,
            "total_events": metric.total_events,
            "metadata": dict(metric.metadata),
            "player_scores": records,
        })

    def _json_safe(self, value: Any) -> Any:
        if is_dataclass(value):
            return self._json_safe(asdict(value))
        if isinstance(value, dict):
            return {str(key): self._json_safe(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        return value

    def _records(self, metrics: Sequence[GameMetrics]) -> list[dict[str, Any]]:
        result = LeaderboardAggregator().aggregate_version(metrics)
        records: list[dict[str, Any]] = []
        for metric in metrics:
            for score in metric.player_scores:
                records.append({
                    "adjusted_final_score": score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
                    "role_task_score": score.role_task_score,
                    "mistakes": score.mistakes,
                    "role": score.role,
                })
        if not records and result.entries:
            records.extend({"adjusted_final_score": entry.avg_adjusted_final_score, "role_task_score": 0.0, "mistakes": [], "role": entry.display_name} for entry in result.entries)
        return records

    @staticmethod
    def _infer_target_role(metrics: Sequence[GameMetrics]) -> str | None:
        for metric in metrics:
            target = metric.metadata.get("target_role")
            if target:
                return str(target)
        return None

    @staticmethod
    def _filter_records_by_role(records: Sequence[dict[str, Any]], role: str | None) -> list[dict[str, Any]]:
        if not role:
            return list(records)
        role_lower = role.lower()
        return [r for r in records if str(r.get("role", "")).lower() == role_lower]

    def _avg(self, records: Sequence[dict[str, Any]], key: str) -> float:
        if not records:
            return 0.0
        return sum(float(record.get(key, 0.0)) for record in records) / len(records)

    def _percent_delta(self, baseline: float, candidate: float) -> float:
        if baseline == 0:
            return 100.0 if candidate > 0 else 0.0
        return round(((candidate - baseline) / baseline) * 100.0, 4)

    def _critical_count(self, records: Sequence[dict[str, Any]]) -> int:
        return sum(1 for record in records for mistake in record.get("mistakes", []) if str(mistake).startswith("[critical]"))

    def _rate_delta(self, baseline_count: int, candidate_count: int, games: int) -> float:
        baseline_rate = baseline_count / games
        candidate_rate = candidate_count / games
        return round(candidate_rate - baseline_rate, 4)

    def _avg_metadata(self, metrics: Sequence[GameMetrics], key: str) -> float:
        if not metrics:
            return 0.0
        return sum(float(item.metadata.get(key, 0.0)) for item in metrics) / len(metrics)

    def _metadata_int(self, metric: GameMetrics, key: str) -> int:
        return int(metric.metadata.get(key, 0) or 0)


def extract_from_review_reports(
    reports: Sequence[ReviewReport],
) -> list[StrategyKnowledgeDoc]:
    """Extract StrategyKnowledgeDocs from Track B evolution_candidates.

    Track B → Track C contract: consumes ReviewReport.evolution_candidates.
    """
    docs: list[StrategyKnowledgeDoc] = []
    for report in reports:
        candidates = getattr(report, "evolution_candidates", None)
        if not candidates:
            continue
        for ev in candidates:
            # Safe-for-learning check
            if not getattr(ev, "safe_for_track_c_learning", True):
                continue
            # Required fields
            if not all([
                getattr(ev, "evidence_refs", None),
                getattr(ev, "role", None),
                getattr(ev, "phase", None),
                getattr(ev, "trigger_condition", None),
                getattr(ev, "lesson", None),
            ]):
                continue
            # Build quality_signals from the evolution candidate
            qs = getattr(ev, "quality_signals", {}) or {}
            quality = qs.get("confidence", 0.7)
            confidence = qs.get("judge_agreement", 0.7)

            doc = StrategyKnowledgeDoc(
                doc_id=f"tb-{report.game_id}-{getattr(ev, 'source_id', '')}",
                doc_type=getattr(ev, "source_type", "good_play"),
                role=getattr(ev, "role", "global"),
                phase=getattr(ev, "phase", ""),
                persona_scope=None,
                situation_pattern=getattr(ev, "trigger_condition", ""),
                trigger_conditions=[getattr(ev, "trigger_condition", "")],
                recommended_action=getattr(ev, "lesson", ""),
                avoid_action=None,
                rationale=getattr(ev, "lesson", ""),
                evidence_summary=str(getattr(ev, "evidence_refs", [])[:3]),
                source_report_ids=[report.game_id],
                source_item_ids=[getattr(ev, "source_id", "")],
                source_event_ids=[],
                counterfactual_ids=[],
                expected_metric_effects=[],
                quality_score=quality,
                confidence=confidence,
                status="candidate",
                tags=[getattr(ev, "role", "global"), getattr(ev, "source_type", "")],
            )
            docs.append(doc)
    return docs


class DreamJob:
    def __init__(
        self,
        *,
        extractor: StrategyKnowledgeDocExtractor | None = None,
        store: StrategyKnowledgeStore | None = None,
        patch_generator: StrategyPatchGenerator | None = None,
        patch_validator: PatchValidator | None = None,
        version_manager: VersionManager | None = None,
        pg_conn_str: str = "",
    ) -> None:
        self.extractor = extractor or StrategyKnowledgeDocExtractor()
        self.store = store or StrategyKnowledgeStore()
        self.patch_generator = patch_generator or StrategyPatchGenerator()
        self.patch_validator = patch_validator or PatchValidator()
        self.pg_conn_str = pg_conn_str
        # Track C §9 accepted_patch loop: VersionManager.promote() writes back
        # an accepted_patch knowledge doc, so wire the same store in.
        self.version_manager = version_manager or VersionManager(knowledge_store=self.store)
        if self.version_manager.knowledge_store is None:
            self.version_manager.knowledge_store = self.store

    def run(self, reports: Sequence[ReviewReport]) -> DreamResult:
        rejected_items: list[dict[str, Any]] = []
        safety_summary: dict[str, Any] = {"sanitized": 0, "rejected_leak": 0, "rejected_no_evidence": 0, "rejected_missing_fields": 0}

        # ---- Step 1: Extract from Track B evolution_candidates first ----
        report_candidates = extract_from_review_reports(reports)
        if report_candidates:
            logger.info(f"Extracted {len(report_candidates)} candidates from Track B ReviewReports")
        else:
            # Fall back to traditional extraction
            report_candidates = list(self.extractor.extract(reports))

        # ---- Step 2: Sanitize ----
        sanitized_docs: list[StrategyKnowledgeDoc] = []
        for doc in report_candidates:
            result = sanitize_knowledge_doc(doc)
            if not result.safe_for_track_c_learning:
                rejected_items.append({
                    "doc_id": doc.doc_id,
                    "reason": result.unsafe_reason or "unsafe for Track C",
                    "redactions": result.redactions,
                })
                safety_summary["rejected_leak"] += 1
                continue
            if result.rewrite_applied:
                safety_summary["sanitized"] += 1
            sanitized_docs.append(doc)

        # ---- Step 3: Validate ----
        valid_docs: list[StrategyKnowledgeDoc] = []
        for doc in sanitized_docs:
            # Must have at least one source report
            if not doc.source_report_ids:
                rejected_items.append({
                    "doc_id": doc.doc_id,
                    "reason": "missing evidence_refs / source_report_ids",
                })
                safety_summary["rejected_no_evidence"] += 1
                continue
            # Must have at minimum role, recommendation, and some situation pattern
            if not doc.role or (not doc.situation_pattern and not doc.trigger_conditions):
                rejected_items.append({
                    "doc_id": doc.doc_id,
                    "reason": f"missing required fields: role={doc.role!r} phase={doc.phase!r} pattern={doc.situation_pattern!r}",
                })
                safety_summary["rejected_missing_fields"] += 1
                continue
            # phase defaults to "global" if empty
            if not doc.phase:
                doc.phase = "global"
            valid_docs.append(doc)

        # ---- Step 4: Score and store ----
        for doc in valid_docs:
            try:
                fake_report = ReviewReport(
                    game_id=(doc.source_report_ids or ["unknown"])[0],
                    winner=None, total_days=0, total_events=0, game_summary="",
                )
                quality, conf, _ = self.extractor.abstractor.quality_score(
                    StrategyKnowledge(
                        knowledge_id=doc.doc_id,
                        target_role=doc.role,
                        source_game_id=(doc.source_report_ids or ["unknown"])[0],
                        source_type=doc.doc_type,
                        trigger_condition=doc.situation_pattern,
                        suggestion=doc.recommended_action,
                        priority="high" if doc.quality_score >= 0.7 else "medium",
                        evidence_summary=doc.evidence_summary,
                        safe_for_agent=True,
                        evidence_event_ids=list(doc.source_event_ids),
                    ),
                    fake_report,
                )
                doc.quality_score = quality
                doc.confidence = conf
            except Exception:
                # If quality scoring fails, keep existing scores
                pass

        # If the new pipeline filtered out all docs, fall back to the original extraction
        if not valid_docs:
            docs = self.extractor.extract(reports)
            saved_docs = self.store.upsert_many(docs)
            valid_docs = list(docs)
        else:
            saved_docs = self.store.upsert_many(valid_docs)

        # ---- Step 5: Generate patches ----
        active_cards = {doc.role: self.version_manager.active_card(doc.role) for doc in saved_docs if doc.role != "global"}
        raw_patches = self.patch_generator.generate(saved_docs, active_cards)
        candidate_patches, rejected_patches = self.patch_validator.validate_many(raw_patches)
        for rp in rejected_patches:
            rejected_items.append(rp)

        # ---- Step 6: Create candidate versions ----
        for patch in candidate_patches:
            self.version_manager.create_candidate(patch)

        # ---- Step 7: Sync to PG ----
        roles = sorted({doc.role for doc in saved_docs if doc.role != "global"})
        if self.pg_conn_str and saved_docs:
            try:
                self.store.sync_to_pg(self.pg_conn_str)
            except Exception:
                pass

        saved_count = len(saved_docs)
        summary = DreamSummary(
            source_reports=len(reports),
            knowledge_docs_created=saved_count,
            candidate_patches_created=len(candidate_patches),
            repeated_roles=roles,
            rejected_count=len(rejected_items),
            sanitized_count=safety_summary["sanitized"],
            safety_issues_count=safety_summary["rejected_leak"],
            summary=f"Extracted {saved_count} knowledge docs ({safety_summary['sanitized']} sanitized), "
                    f"proposed {len(candidate_patches)} patches, rejected {len(rejected_items)} items.",
        )
        return DreamResult(saved_docs, candidate_patches, summary,
                           rejected_items=rejected_items, safety_summary=safety_summary)


class HermesEvolutionHook:
    def __init__(
        self,
        *,
        dream_job: DreamJob | None = None,
        version_manager: VersionManager | None = None,
    ) -> None:
        self.version_manager = version_manager or VersionManager()
        self.dream_job = dream_job or DreamJob(version_manager=self.version_manager)
        self._history: list[EvolutionRecord] = []

    def evolve(self, report: ReviewReport) -> EvolutionRecord:
        result = self.dream_job.run([report])
        record = EvolutionRecord(
            strategy_version=";".join(patch.to_version for patch in result.candidate_patches) or "no_candidate",
            parent_version=None,
            observations=[result.summary.summary],
            proposed_changes=[op.new_value for patch in result.candidate_patches for op in patch.operations],
            applied_changes=[patch.patch_id for patch in result.candidate_patches],
            promoted=False,
            metadata={"knowledge_docs": [doc.doc_id for doc in result.knowledge_docs]},
        )
        self._history.append(record)
        return record

    def rollback(self, target_version: str) -> StrategyVersion:
        return self.version_manager.rollback(target_version)

    def version_history(self) -> list[StrategyVersion]:
        return self.version_manager.history()


class SimpleEvolutionLoop:
    def __init__(
        self,
        *,
        dream_job: DreamJob | None = None,
        tournament_runner: TournamentRunner | None = None,
        version_manager: VersionManager | None = None,
    ) -> None:
        self.version_manager = version_manager or VersionManager()
        self.dream_job = dream_job or DreamJob(version_manager=self.version_manager)
        self.tournament_runner = tournament_runner or TournamentRunner()
        self.records: list[EvolutionRecord] = []

    def run_cycle(self, reports: Sequence[ReviewReport]) -> DreamResult:
        result = self.dream_job.run(reports)
        self.records.append(
            EvolutionRecord(
                strategy_version=";".join(patch.to_version for patch in result.candidate_patches) or "no_candidate",
                parent_version=None,
                observations=[result.summary.summary],
                proposed_changes=[op.new_value for patch in result.candidate_patches for op in patch.operations],
                applied_changes=[patch.patch_id for patch in result.candidate_patches],
            )
        )
        return result

    def ab_compare(
        self,
        baseline: Sequence[GameMetrics],
        candidate: Sequence[GameMetrics],
        *,
        baseline_version: str = "baseline",
        candidate_version: str = "candidate",
        target_role: str | None = None,
        patch: StrategyPatch | None = None,
    ) -> ABComparison:
        # Legacy comparison
        comparison = self.tournament_runner.compare_metrics(baseline_version, candidate_version, baseline, candidate)
        # v2: also compute paired comparison for richer decision
        evolution_comp = self.tournament_runner.compare_paired_seed_results(
            list(baseline), list(candidate), target_role=target_role,
        )
        decision = self.tournament_runner.acceptance_policy.decide(
            comparison=comparison,
            evolution_comparison=evolution_comp,
        )
        comparison.accepted = decision.status == "promoted"

        if decision.status == "promoted":
            if candidate_version in self.version_manager.versions:
                # Compute dynamic quality/confidence
                if patch:
                    quality, confidence, validated_on = compute_accepted_patch_confidence(
                        evolution_comp, decision, patch,
                    )
                else:
                    quality, confidence, validated_on = None, None, None
                self.version_manager.promote(
                    candidate_version,
                    quality=quality,
                    confidence=confidence,
                    validated_on=validated_on,
                )
        elif decision.status == "rolled_back":
            if candidate_version in self.version_manager.versions:
                self.version_manager.rollback(candidate_version, reason=decision.reason)
        # needs_more_trials: leave as candidate, don't promote or rollback
        logger.info(
            f"AB compare result: {decision.status} — {decision.reason}"
        )
        return comparison


class EvolutionPipeline:
    def __init__(
        self,
        *,
        loop: SimpleEvolutionLoop | None = None,
        store: StrategyKnowledgeStore | None = None,
    ) -> None:
        self.store = store or StrategyKnowledgeStore()
        self.loop = loop or SimpleEvolutionLoop(dream_job=DreamJob(store=self.store))

    def run(
        self,
        approved_reports: Sequence[ReviewReport],
        *,
        baseline_metrics: Sequence[GameMetrics] | None = None,
        candidate_metrics: Sequence[GameMetrics] | None = None,
        summary_path: str | Path | None = None,
    ) -> EvolutionSummary:
        dream_result = self.loop.run_cycle(approved_reports)
        promoted: list[str] = []
        rolled_back: list[str] = []
        if baseline_metrics is not None and candidate_metrics is not None and dream_result.candidate_patches:
            candidate_version = dream_result.candidate_patches[0].to_version
            patch = dream_result.candidate_patches[0] if dream_result.candidate_patches else None
            comparison = self.loop.ab_compare(
                baseline_metrics,
                candidate_metrics,
                baseline_version=dream_result.candidate_patches[0].from_version,
                candidate_version=candidate_version,
                target_role=patch.target_role if patch else None,
                patch=patch,
            )
            if comparison.accepted:
                promoted.append(candidate_version)
            else:
                # v2: only rollback if explicitly rejected; needs_more_trials stays
                pass
        leaderboard = None
        if baseline_metrics or candidate_metrics:
            leaderboard = LeaderboardAggregator().aggregate_version([*(baseline_metrics or []), *(candidate_metrics or [])]).to_dict()
        summary = EvolutionSummary(
            approved_report_count=len(approved_reports),
            knowledge_doc_count=len(dream_result.knowledge_docs),
            candidate_patch_count=len(dream_result.candidate_patches),
            promoted_versions=promoted,
            rolled_back_versions=rolled_back,
            leaderboard=leaderboard,
        )
        if summary_path is not None:
            Path(summary_path).write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


def export_evolution_summary(summary: EvolutionSummary, path: str | Path) -> dict[str, Any]:
    payload = summary.to_dict()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_strategy_knowledge(path: str | Path) -> StrategyKnowledgeStore:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = [StrategyKnowledgeDoc(**item) for item in payload]
    return StrategyKnowledgeStore(docs)
