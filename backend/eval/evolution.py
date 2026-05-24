"""Track C: strategy-memory evolution loop built on approved Track B reviews."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence
from uuid import uuid4

from backend.eval.review import (
    GameMetrics,
    LeaderboardAggregator,
    ReviewReport,
    StrategyKnowledge,
    StrategyKnowledgeExtractor,
)


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
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    status: str = "candidate"
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    top_k: int = 3


@dataclass
class RetrievedStrategyLesson:
    doc_id: str
    role: str
    phase: str
    score: float
    trigger: str
    recommendation: str
    rationale: str


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
    summary: str


@dataclass
class DreamResult:
    knowledge_docs: list[StrategyKnowledgeDoc]
    candidate_patches: list[StrategyPatch]
    summary: DreamSummary


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
    winner: str | None = None
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptanceDecision:
    accepted: bool
    reason: str
    satisfied_conditions: list[str]
    failed_conditions: list[str]


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
        blob = " ".join([
            doc.situation_pattern,
            " ".join(doc.trigger_conditions),
            doc.recommended_action,
            doc.avoid_action or "",
            doc.rationale,
            doc.evidence_summary,
        ])
        if not doc.source_report_ids:
            issues.append("missing_source_report")
        if not doc.trigger_conditions:
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

    def quality_score(self, item: StrategyKnowledge, report: ReviewReport) -> tuple[float, float]:
        evidence_strength = 1.0 if item.evidence_summary else 0.3
        counterfactual_support = 1.0 if item.source_type == "counterfactual" else 0.5
        repeatability = 0.4
        metric_relevance = 0.8 if item.priority == "high" else 0.55
        validation_confidence = float(report.metadata.get("validation_score", 1.0))
        quality = (
            0.30 * evidence_strength
            + 0.20 * counterfactual_support
            + 0.20 * repeatability
            + 0.15 * metric_relevance
            + 0.10 * validation_confidence
            + 0.05
        )
        confidence = min(1.0, 0.45 + quality * 0.5)
        return round(quality, 4), round(confidence, 4)


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
        docs: list[StrategyKnowledgeDoc] = []
        for report in reports:
            if not self._is_approved(report):
                continue
            names = {review.player_name for review in report.player_reviews}
            for item in self.extractor.extract(report):
                quality, confidence = self.abstractor.quality_score(item, report)
                doc = self._convert(item, report, names, quality, confidence)
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
            source_event_ids=[],
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


class StrategyKnowledgeStore:
    def __init__(self, docs: Sequence[StrategyKnowledgeDoc] | None = None) -> None:
        self.docs: dict[str, StrategyKnowledgeDoc] = {}
        self.edges: dict[str, set[str]] = defaultdict(set)
        if docs:
            self.upsert_many(docs)

    def upsert(self, doc: StrategyKnowledgeDoc) -> StrategyKnowledgeDoc:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.docs.get(doc.doc_id)
        stored = replace(doc, updated_at=now)
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
            if doc.status in {"active", "candidate"} and self._role_matches(doc, query) and self._phase_matches(doc, query)
        ]
        scored = [(self._score(doc, query), doc) for doc in candidates]
        scored.sort(key=lambda item: item[0], reverse=True)
        lessons = [
            RetrievedStrategyLesson(
                doc_id=doc.doc_id,
                role=doc.role,
                phase=doc.phase,
                score=round(score, 4),
                trigger=doc.situation_pattern,
                recommendation=doc.recommended_action,
                rationale=doc.rationale,
            )
            for score, doc in scored[: max(query.top_k, 0)]
            if score > 0
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
        status = "deprecated" if failure >= 3 and success == 0 else doc.status
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

    def _index(self, doc: StrategyKnowledgeDoc) -> None:
        for tag in {doc.role, doc.phase, *doc.tags}:
            self.edges[f"{tag}:has_doc"].add(doc.doc_id)

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

    def _score(self, doc: StrategyKnowledgeDoc, query: StrategyRetrievalQuery) -> float:
        role = 1.0 if doc.role == query.role else 0.55 if doc.role == "global" else 0.0
        phase = 1.0 if doc.phase == query.phase else 0.65 if self._phase_matches(doc, query) else 0.0
        situation = self._text_overlap(doc.situation_pattern, query.observation_summary, query.situation_tags)
        persona = 1.0 if not doc.persona_scope or doc.persona_scope in {query.persona_mbti, query.persona_style} else 0.0
        usage_rate = 0.5 if doc.usage_count == 0 else doc.success_count / max(doc.usage_count, 1)
        return (
            0.30 * role
            + 0.20 * phase
            + 0.20 * situation
            + 0.10 * persona
            + 0.10 * doc.quality_score
            + 0.05
            + 0.05 * usage_rate
        )

    def _text_overlap(self, pattern: str, observation: str, tags: Sequence[str]) -> float:
        words = {word.lower() for word in re.findall(r"[A-Za-z_一-鿿]+", pattern) if len(word) > 1}
        obs = {word.lower() for word in re.findall(r"[A-Za-z_一-鿿]+", observation) if len(word) > 1}
        obs.update(tag.lower() for tag in tags)
        if not words or not obs:
            return 0.3
        return min(1.0, len(words & obs) / max(len(words), 1) + 0.25)

    def _recompute_quality(self, doc: StrategyKnowledgeDoc, success: int, failure: int) -> float:
        total = success + failure
        if total == 0:
            return doc.quality_score
        usage_signal = (success / total) - (failure / total) * 0.5
        return round(max(0.0, min(1.0, doc.quality_score * 0.8 + usage_signal * 0.2)), 4)


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
    def generate(
        self,
        docs: Sequence[StrategyKnowledgeDoc],
        active_cards: dict[str, RoleStrategyCard],
    ) -> list[StrategyPatch]:
        grouped: dict[str, list[StrategyKnowledgeDoc]] = defaultdict(list)
        for doc in docs:
            if doc.status in {"candidate", "active"} and doc.quality_score >= 0.5:
                grouped[doc.role].append(doc)
        patches: list[StrategyPatch] = []
        for role, bucket in grouped.items():
            if role == "global" or not bucket:
                continue
            bucket.sort(key=lambda doc: (doc.quality_score, doc.confidence), reverse=True)
            selected = bucket[:3]
            card = active_cards.get(role) or self._default_card(role)
            operations = [self._operation_from_doc(doc, card) for doc in selected]
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
                    safety_checks={"max_operations": len(operations), "source_docs": len(selected)},
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
    forbidden = [
        "read hidden role",
        "ignore visibility",
        "change game rule",
        "always ",
        "never ",
        "P1",
        "P2",
        "P3",
        "private_reason",
    ]
    allowed_sections = {"speech_policy", "vote_policy", "skill_policy", "risk_rules", "compensation_rules", "retrieval_policy"}

    def validate(self, patch: StrategyPatch) -> PatchValidationResult:
        issues: list[PatchValidationIssue] = []
        if patch.patch_type not in {"role_strategy", "persona_role_adapter", "retrieval_policy", "knowledge_status"}:
            issues.append(PatchValidationIssue("critical", "unsupported patch type", "patch_type"))
        if not patch.source_knowledge_doc_ids:
            issues.append(PatchValidationIssue("critical", "patch missing knowledge source", "source_knowledge_doc_ids"))
        if len(patch.operations) > 3:
            issues.append(PatchValidationIssue("major", "single patch changes too many rules", "operations"))
        for operation in patch.operations:
            if operation.section not in self.allowed_sections:
                issues.append(PatchValidationIssue("critical", "patch modifies an illegal section", operation.section))
            blob = f"{operation.new_value} {operation.rationale}".lower()
            for forbidden in self.forbidden:
                if forbidden.lower() in blob:
                    severity = "major" if forbidden.strip() in {"always", "never"} else "critical"
                    issues.append(PatchValidationIssue(severity, f"patch contains unsafe instruction: {forbidden}", operation.section))
                    break
        passed = not any(issue.severity == "critical" for issue in issues)
        return PatchValidationResult(patch_id=patch.patch_id, passed=passed, issues=issues)


class VersionManager:
    def __init__(self, active_cards: Sequence[RoleStrategyCard] | None = None) -> None:
        self.versions: dict[str, StrategyVersion] = {}
        self.active_by_role: dict[str, str] = {}
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
        patch.status = "applied"
        return version

    def promote(self, version_name: str) -> StrategyVersion:
        version = self.versions[version_name]
        previous = self.active_by_role.get(version.role)
        if previous and previous in self.versions:
            old = self.versions[previous]
            self.versions[previous] = replace(old, status="deprecated", card=replace(old.card, status="deprecated"))
        promoted = replace(version, status="promoted", card=replace(version.card, status="active"))
        self.versions[version_name] = promoted
        self.active_by_role[promoted.role] = version_name
        return promoted

    def rollback(self, version_name: str) -> StrategyVersion:
        version = self.versions[version_name]
        rolled = replace(version, status="rolled_back", card=replace(version.card, status="deprecated"))
        self.versions[version_name] = rolled
        if version.parent and version.parent in self.versions:
            parent = self.versions[version.parent]
            self.versions[version.parent] = replace(parent, status="active", card=replace(parent.card, status="active"))
            self.active_by_role[parent.role] = parent.version
        return rolled

    def history(self) -> list[StrategyVersion]:
        return sorted(self.versions.values(), key=lambda item: item.created_at)


class AcceptancePolicy:
    def decide(self, comparison: ABComparison) -> AcceptanceDecision:
        failed: list[str] = []
        satisfied: list[str] = []
        if comparison.info_leak_count != 0:
            failed.append("info_leak_count must be zero")
        else:
            satisfied.append("no information leaks")
        if comparison.invalid_action_rate != 0:
            failed.append("invalid_action_rate must be zero")
        else:
            satisfied.append("no invalid actions")

        improvements = 0
        if comparison.target_role_avg_score_delta >= 3.0:
            improvements += 1
            satisfied.append("target role score improved by at least 3%")
        else:
            failed.append("target role score did not improve enough")
        if comparison.critical_mistakes_delta <= -0.10:
            improvements += 1
            satisfied.append("critical mistakes decreased by at least 10%")
        else:
            failed.append("critical mistakes did not decrease enough")
        if comparison.role_task_score_delta >= 3.0:
            improvements += 1
            satisfied.append("role task score improved by at least 3%")
        else:
            failed.append("role task score did not improve enough")
        candidate_win_rate = comparison.candidate_wins / max(comparison.total_games, 1)
        baseline_win_rate = comparison.baseline_wins / max(comparison.total_games, 1)
        if candidate_win_rate >= baseline_win_rate - 0.05:
            improvements += 1
            satisfied.append("camp win rate did not regress more than 5%")
        else:
            failed.append("camp win rate regressed more than 5%")

        accepted = comparison.info_leak_count == 0 and comparison.invalid_action_rate == 0 and improvements >= 2
        return AcceptanceDecision(
            accepted=accepted,
            reason="candidate accepted" if accepted else "candidate rejected",
            satisfied_conditions=satisfied,
            failed_conditions=failed if not accepted else [],
        )


class TournamentRunner:
    def __init__(self, acceptance_policy: AcceptancePolicy | None = None) -> None:
        self.acceptance_policy = acceptance_policy or AcceptancePolicy()

    def compare_metrics(
        self,
        baseline_version: str,
        candidate_version: str,
        baseline_metrics: Sequence[GameMetrics],
        candidate_metrics: Sequence[GameMetrics],
    ) -> ABComparison:
        baseline_records = self._records(baseline_metrics)
        candidate_records = self._records(candidate_metrics)
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
                self._avg(baseline_records, "adjusted_final_score"),
                self._avg(candidate_records, "adjusted_final_score"),
            ),
            role_task_score_delta=self._percent_delta(
                self._avg(baseline_records, "role_task_score"),
                self._avg(candidate_records, "role_task_score"),
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
        )
        decision = self.acceptance_policy.decide(comparison)
        comparison.accepted = decision.accepted
        comparison.winner = "candidate" if comparison.candidate_avg_score > comparison.baseline_avg_score else "baseline" if comparison.baseline_avg_score > comparison.candidate_avg_score else None
        return comparison

    def _records(self, metrics: Sequence[GameMetrics]) -> list[dict[str, Any]]:
        result = LeaderboardAggregator().aggregate_version(metrics)
        records: list[dict[str, Any]] = []
        for metric in metrics:
            for score in metric.player_scores:
                records.append({
                    "adjusted_final_score": score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score,
                    "role_task_score": score.role_task_score,
                    "mistakes": score.mistakes,
                })
        if not records and result.entries:
            records.extend({"adjusted_final_score": entry.avg_adjusted_final_score, "role_task_score": 0.0, "mistakes": []} for entry in result.entries)
        return records

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


class DreamJob:
    def __init__(
        self,
        *,
        extractor: StrategyKnowledgeDocExtractor | None = None,
        store: StrategyKnowledgeStore | None = None,
        patch_generator: StrategyPatchGenerator | None = None,
        patch_validator: PatchValidator | None = None,
        version_manager: VersionManager | None = None,
    ) -> None:
        self.extractor = extractor or StrategyKnowledgeDocExtractor()
        self.store = store or StrategyKnowledgeStore()
        self.patch_generator = patch_generator or StrategyPatchGenerator()
        self.patch_validator = patch_validator or PatchValidator()
        self.version_manager = version_manager or VersionManager()

    def run(self, reports: Sequence[ReviewReport]) -> DreamResult:
        docs = self.extractor.extract(reports)
        saved_docs = self.store.upsert_many(docs)
        active_cards = {doc.role: self.version_manager.active_card(doc.role) for doc in saved_docs if doc.role != "global"}
        raw_patches = self.patch_generator.generate(saved_docs, active_cards)
        candidate_patches: list[StrategyPatch] = []
        for patch in raw_patches:
            validation = self.patch_validator.validate(patch)
            patch.safety_checks["validation"] = asdict(validation)
            if validation.passed:
                patch.status = "validated"
                candidate_patches.append(patch)
                self.version_manager.create_candidate(patch)
            else:
                patch.status = "rejected"
        roles = sorted({doc.role for doc in saved_docs if doc.role != "global"})
        summary = DreamSummary(
            source_reports=len(reports),
            knowledge_docs_created=len(saved_docs),
            candidate_patches_created=len(candidate_patches),
            repeated_roles=roles,
            summary=f"Extracted {len(saved_docs)} sanitized strategy lessons and proposed {len(candidate_patches)} candidate patches.",
        )
        return DreamResult(saved_docs, candidate_patches, summary)


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
    ) -> ABComparison:
        comparison = self.tournament_runner.compare_metrics(baseline_version, candidate_version, baseline, candidate)
        if comparison.accepted:
            if candidate_version in self.version_manager.versions:
                self.version_manager.promote(candidate_version)
        elif candidate_version in self.version_manager.versions:
            self.version_manager.rollback(candidate_version)
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
            comparison = self.loop.ab_compare(
                baseline_metrics,
                candidate_metrics,
                baseline_version=dream_result.candidate_patches[0].from_version,
                candidate_version=candidate_version,
            )
            if comparison.accepted:
                promoted.append(candidate_version)
            else:
                rolled_back.append(candidate_version)
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


class StrategyAwarePromptMixin:
    def __init__(self, store: StrategyKnowledgeStore | None = None) -> None:
        self.store = store or StrategyKnowledgeStore()
        self.renderer = StrategyContextRenderer()
        self.last_retrieved_knowledge_ids: list[str] = []

    def retrieve_context(self, query: StrategyRetrievalQuery) -> str:
        lessons = self.store.retrieve(query)
        self.last_retrieved_knowledge_ids = [lesson.doc_id for lesson in lessons]
        return self.renderer.render_lessons(lessons)


def export_evolution_summary(summary: EvolutionSummary, path: str | Path) -> dict[str, Any]:
    payload = summary.to_dict()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_strategy_knowledge(path: str | Path) -> StrategyKnowledgeStore:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = [StrategyKnowledgeDoc(**item) for item in payload]
    return StrategyKnowledgeStore(docs)
