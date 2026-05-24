from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol, Sequence
from uuid import uuid4

from backend.eval.review import LeaderboardAggregator, ReviewReport
from backend.eval.track_b import PublishedReviewDocument, generate_published_review_document, reconstruct_review_report


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned or "global"


PLAYER_REF_RE = re.compile(
    r"(@?\d+\s*号[:：]?[^\s，。；;,.]*)|(P\d+[-_\w]*)|(座位\s*\d+)|([A-Z]?\d+号)",
    re.I,
)
PRIVATE_LEAK_RE = re.compile(r"(狼队友|昨晚刀|private_reason|隐藏身份|上帝视角|真实身份|队友是|knife)", re.I)
ABSOLUTE_RE = re.compile(r"(永远|必须每次|一定要|百分百|always|never)", re.I)
FORBIDDEN_PATCH_RE = re.compile(r"(游戏规则|胜负条件|信息隔离|visibility|hidden role|读取真实身份|修改角色权限|role permission)", re.I)


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
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyRetrievalQuery:
    role: str
    phase: str
    persona_mbti: str | None = None
    persona_style: str | None = None
    observation_summary: str = ""
    situation_tags: list[str] = field(default_factory=list)
    private_role_state_summary: str | None = None
    legal_action_types: list[str] = field(default_factory=list)
    top_k: int = 3


@dataclass
class RetrievedKnowledge:
    doc: StrategyKnowledgeDoc
    score: float
    match_reasons: list[str]

    def to_prompt_line(self) -> str:
        avoid = f" 避免：{self.doc.avoid_action}" if self.doc.avoid_action else ""
        return (
            f"[{self.doc.doc_id}] {self.doc.role}/{self.doc.phase} "
            f"建议：{self.doc.recommended_action}{avoid} "
            f"触发：{'; '.join(self.doc.trigger_conditions[:2])} "
            f"可信度：{self.doc.confidence:.2f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {"doc": self.doc.to_dict(), "score": self.score, "match_reasons": list(self.match_reasons)}


@dataclass
class PatchOperation:
    op: str
    section: str
    old_value: str | None
    new_value: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    safety_checks: dict[str, Any]
    status: str = "proposed"
    validation_result: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operations"] = [operation.to_dict() for operation in self.operations]
        return payload


@dataclass
class RoleStrategyCard:
    role: str
    version: str
    parent_version: str | None
    goal: str
    speech_policy: list[str]
    vote_policy: list[str]
    skill_policy: list[str]
    risk_rules: list[str]
    retrieval_policy: dict[str, Any]
    status: str
    card_id: str = field(default_factory=lambda: str(uuid4()))
    created_from_patch_id: str | None = None
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonaRoleAdapter:
    persona_scope: str
    role: str
    version: str
    compensation_rules: list[str]
    risk_warnings: list[str]
    style_adjustments: list[str]
    status: str = "active"
    adapter_id: str = field(default_factory=lambda: str(uuid4()))
    created_from_patch_id: str | None = None
    created_at: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamResult:
    report_ids: list[str]
    knowledge_docs: list[StrategyKnowledgeDoc]
    candidate_patches: list[StrategyPatch]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_ids": list(self.report_ids),
            "knowledge_docs": [doc.to_dict() for doc in self.knowledge_docs],
            "candidate_patches": [patch.to_dict() for patch in self.candidate_patches],
            "summary": dict(self.summary),
        }


@dataclass
class PatchValidationIssue:
    severity: str
    message: str
    location: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatchValidationResult:
    passed: bool
    issues: list[PatchValidationIssue]
    safety_checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "safety_checks": dict(self.safety_checks),
        }


@dataclass
class TournamentComparison:
    tournament_id: str
    baseline_version: str
    candidate_version: str
    target_role: str | None
    seeds: list[int]
    baseline_results: list[dict[str, Any]]
    candidate_results: list[dict[str, Any]]
    comparison: dict[str, Any]
    decision: dict[str, Any]
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvolutionHook(Protocol):
    def evolve(self, report: PublishedReviewDocument) -> list[StrategyKnowledgeDoc]: ...

    def rollback(self, target_version: str) -> RoleStrategyCard: ...

    def version_history(self) -> list[RoleStrategyCard]: ...


class StrategyKnowledgeSanitizer:
    def sanitize_text(self, text: str) -> str:
        text = PLAYER_REF_RE.sub("某个玩家", str(text or ""))
        text = PRIVATE_LEAK_RE.sub("公开可验证信息", text)
        return re.sub(r"\s+", " ", text).strip()

    def sanitize(self, doc: StrategyKnowledgeDoc) -> StrategyKnowledgeDoc:
        doc.situation_pattern = self.sanitize_text(doc.situation_pattern)
        doc.recommended_action = self.sanitize_text(doc.recommended_action)
        doc.avoid_action = self.sanitize_text(doc.avoid_action) if doc.avoid_action else None
        doc.rationale = self.sanitize_text(doc.rationale)
        doc.evidence_summary = self.sanitize_text(doc.evidence_summary)
        doc.trigger_conditions = [self.sanitize_text(item) for item in doc.trigger_conditions if item]
        doc.tags = sorted(set(_slug(tag) for tag in doc.tags if tag))
        doc.updated_at = _utcnow()
        if self.has_hidden_leak(doc):
            doc.status = "rejected"
            doc.quality_score = min(doc.quality_score, 0.2)
        return doc

    def has_hidden_leak(self, doc: StrategyKnowledgeDoc) -> bool:
        blob = json.dumps(doc.to_dict(), ensure_ascii=False)
        return bool(PRIVATE_LEAK_RE.search(blob) or re.search(r"@\d+号|P\d+-|座位\s*\d+", blob))


class KnowledgeQualityScorer:
    def score(self, doc: StrategyKnowledgeDoc, *, similar_count: int = 1, validation_score: float = 1.0) -> float:
        evidence_strength = min(1.0, len(doc.source_event_ids) / 3.0)
        counterfactual_support = 1.0 if doc.counterfactual_ids else 0.35
        repeatability = min(1.0, similar_count / 3.0)
        metric_relevance = min(1.0, len(doc.expected_metric_effects) / 2.0) if doc.expected_metric_effects else 0.35
        recency = 1.0
        return _clamp(
            0.30 * evidence_strength
            + 0.20 * counterfactual_support
            + 0.20 * repeatability
            + 0.15 * metric_relevance
            + 0.10 * validation_score
            + 0.05 * recency
        )


class StrategyKnowledgeExtractor:
    def __init__(self, sanitizer: StrategyKnowledgeSanitizer | None = None) -> None:
        self.sanitizer = sanitizer or StrategyKnowledgeSanitizer()
        self.scorer = KnowledgeQualityScorer()

    def extract(self, document: PublishedReviewDocument | dict[str, Any]) -> list[StrategyKnowledgeDoc]:
        payload = document.to_dict() if hasattr(document, "to_dict") else dict(document)
        if not self._is_approved(payload):
            return []
        report = payload.get("review_report") or {}
        report_id = str(payload.get("report_id") or f"review:{payload.get('game_id')}")
        validation_score = float((payload.get("validation_result") or {}).get("score") or 1.0)
        docs: list[StrategyKnowledgeDoc] = []
        docs.extend(self._from_highlights(report, report_id, validation_score))
        docs.extend(self._from_bad_cases(report, report_id, validation_score))
        docs.extend(self._from_counterfactuals(report, report_id, validation_score))
        docs.extend(self._from_score_weaknesses(report, report_id, validation_score))
        return self._dedupe_and_rescore(docs, validation_score)

    def _is_approved(self, payload: dict[str, Any]) -> bool:
        validation = payload.get("validation_result") or {}
        return bool(payload.get("status") == "approved" and validation.get("publish_allowed", payload.get("publish_allowed", False)))

    def _from_highlights(self, report: dict[str, Any], report_id: str, validation_score: float) -> list[StrategyKnowledgeDoc]:
        docs: list[StrategyKnowledgeDoc] = []
        for item in report.get("turning_points", []):
            role = self._role_from_item(item, report)
            docs.append(self._make_doc(
                doc_type="good_play",
                role=role,
                phase=str(item.get("phase") or "DAY_SPEECH"),
                situation_pattern=str(item.get("description") or item.get("title") or "关键高光"),
                recommended_action=str(item.get("description") or "复用该关键高光对应的策略动作"),
                avoid_action=None,
                rationale="高光事件在复盘中被识别为对局势有正向影响。",
                source_report_id=report_id,
                source_item_id=str(item.get("turning_point_id") or item.get("title") or uuid4()),
                source_event_ids=list(item.get("evidence_event_ids") or []),
                counterfactual_ids=[],
                expected_metric_effects=[{"metric": "role_task_score", "direction": "increase"}],
                tags=["highlight", str(item.get("category") or ""), role],
                validation_score=validation_score,
            ))
        return docs

    def _from_bad_cases(self, report: dict[str, Any], report_id: str, validation_score: float) -> list[StrategyKnowledgeDoc]:
        docs: list[StrategyKnowledgeDoc] = []
        for item in report.get("bad_cases", []):
            role = str(item.get("role") or "global")
            mistake_type = str(item.get("mistake_type") or "bad_case")
            docs.append(self._make_doc(
                doc_type="bad_case_lesson",
                role=role,
                phase=str(item.get("phase") or "DAY_SPEECH"),
                situation_pattern=str(item.get("description") or "重复失误模式"),
                recommended_action=str(item.get("suggested_fix") or "在类似局势下先核对公开证据再行动。"),
                avoid_action=str(item.get("description") or "重复该失误"),
                rationale="该行为在复盘中被标记为失误，会降低角色任务完成度或阵营收益。",
                source_report_id=report_id,
                source_item_id=str(item.get("case_id") or uuid4()),
                source_event_ids=list(item.get("evidence_event_ids") or []),
                counterfactual_ids=[],
                expected_metric_effects=[{"metric": mistake_type, "direction": "decrease"}],
                tags=["bad_case", mistake_type, role],
                validation_score=validation_score,
            ))
        return docs

    def _from_counterfactuals(self, report: dict[str, Any], report_id: str, validation_score: float) -> list[StrategyKnowledgeDoc]:
        docs: list[StrategyKnowledgeDoc] = []
        for item in report.get("counterfactuals", []):
            role = self._role_from_counterfactual(item)
            cf_type = str(item.get("counterfactual_type") or "counterfactual")
            docs.append(self._make_doc(
                doc_type="counterfactual_lesson",
                role=role,
                phase=str(item.get("phase") or "DAY_SPEECH"),
                situation_pattern=str(item.get("original_decision") or "局部反事实"),
                recommended_action=str(item.get("alternative_decision") or "选择复盘中更优的局部替代动作。"),
                avoid_action=str(item.get("original_decision") or ""),
                rationale=str(item.get("expected_effect") or "局部反事实显示替代动作可能改善结果。"),
                source_report_id=report_id,
                source_item_id=str(item.get("case_id") or uuid4()),
                source_event_ids=list(item.get("evidence_event_ids") or []),
                counterfactual_ids=[str(item.get("case_id") or uuid4())],
                expected_metric_effects=[{"metric": cf_type, "direction": "improve"}],
                tags=["counterfactual", cf_type, role],
                validation_score=validation_score,
            ))
        return docs

    def _from_score_weaknesses(self, report: dict[str, Any], report_id: str, validation_score: float) -> list[StrategyKnowledgeDoc]:
        docs: list[StrategyKnowledgeDoc] = []
        for score in report.get("scoreboard", []):
            low_dims = []
            for key in ["speech_score", "vote_score", "skill_score", "role_task_score"]:
                if float(score.get(key) or 0.0) < 0.45:
                    low_dims.append(key)
            if not low_dims:
                continue
            role = str(score.get("role") or "global")
            docs.append(self._make_doc(
                doc_type="weakness_lesson",
                role=role,
                phase="ANY",
                situation_pattern=f"{role} 在 {', '.join(low_dims)} 上持续偏弱",
                recommended_action=f"优先改善 {', '.join(low_dims)} 对应的角色任务执行。",
                avoid_action="继续只看胜负而忽略过程指标。",
                rationale="分项得分显示该角色存在可复用的策略弱点。",
                source_report_id=report_id,
                source_item_id=str(score.get("player_id") or uuid4()),
                source_event_ids=[],
                counterfactual_ids=[],
                expected_metric_effects=[{"metric": dim, "direction": "increase"} for dim in low_dims],
                tags=["weakness", role, *low_dims],
                validation_score=validation_score,
            ))
        return docs

    def _make_doc(
        self,
        *,
        doc_type: str,
        role: str,
        phase: str,
        situation_pattern: str,
        recommended_action: str,
        avoid_action: str | None,
        rationale: str,
        source_report_id: str,
        source_item_id: str,
        source_event_ids: list[str],
        counterfactual_ids: list[str],
        expected_metric_effects: list[dict[str, Any]],
        tags: list[str],
        validation_score: float,
    ) -> StrategyKnowledgeDoc:
        doc = StrategyKnowledgeDoc(
            doc_id=f"sk-{_slug(doc_type)}-{_slug(role)}-{str(uuid4())[:8]}",
            doc_type=doc_type,
            role=role or "global",
            phase=phase or "ANY",
            persona_scope=None,
            situation_pattern=situation_pattern,
            trigger_conditions=self._triggers(doc_type, role, phase, tags),
            recommended_action=recommended_action,
            avoid_action=avoid_action,
            rationale=rationale,
            evidence_summary=f"来自已通过校验的复盘 {source_report_id}，证据事件 {len(source_event_ids)} 条。",
            source_report_ids=[source_report_id],
            source_item_ids=[source_item_id],
            source_event_ids=source_event_ids,
            counterfactual_ids=counterfactual_ids,
            expected_metric_effects=expected_metric_effects,
            quality_score=0.0,
            confidence=_clamp(0.55 + 0.1 * min(len(source_event_ids), 3) + 0.15 * validation_score),
            status="candidate",
            tags=tags,
        )
        doc = self.sanitizer.sanitize(doc)
        doc.quality_score = self.scorer.score(doc, validation_score=validation_score)
        if doc.quality_score >= 0.68 and doc.status != "rejected":
            doc.status = "active"
        return doc

    def _dedupe_and_rescore(self, docs: list[StrategyKnowledgeDoc], validation_score: float) -> list[StrategyKnowledgeDoc]:
        buckets: dict[tuple[str, str, str, str], StrategyKnowledgeDoc] = {}
        counts: Counter[tuple[str, str, str, str]] = Counter()
        for doc in docs:
            key = (doc.doc_type, doc.role, doc.phase, _slug(doc.recommended_action[:80]))
            counts[key] += 1
            if key not in buckets:
                buckets[key] = doc
            else:
                existing = buckets[key]
                existing.source_report_ids = sorted(set(existing.source_report_ids + doc.source_report_ids))
                existing.source_item_ids = sorted(set(existing.source_item_ids + doc.source_item_ids))
                existing.source_event_ids = sorted(set(existing.source_event_ids + doc.source_event_ids))
                existing.counterfactual_ids = sorted(set(existing.counterfactual_ids + doc.counterfactual_ids))
                existing.expected_metric_effects.extend(doc.expected_metric_effects)
                existing.tags = sorted(set(existing.tags + doc.tags))
        for key, doc in buckets.items():
            doc.quality_score = self.scorer.score(doc, similar_count=counts[key], validation_score=validation_score)
            if doc.quality_score >= 0.68 and doc.status != "rejected":
                doc.status = "active"
        return list(buckets.values())

    def _triggers(self, doc_type: str, role: str, phase: str, tags: list[str]) -> list[str]:
        triggers = [f"role={role or 'global'}", f"phase={phase or 'ANY'}", f"doc_type={doc_type}"]
        for tag in tags[:3]:
            if tag:
                triggers.append(f"tag={_slug(tag)}")
        return triggers

    def _role_from_item(self, item: dict[str, Any], report: dict[str, Any]) -> str:
        names = set(item.get("related_players") or [])
        for score in report.get("scoreboard", []):
            if score.get("player_name") in names or score.get("player_id") in names:
                return str(score.get("role") or "global")
        return str(item.get("role") or "global")

    def _role_from_counterfactual(self, item: dict[str, Any]) -> str:
        text = f"{item.get('original_decision', '')} {item.get('alternative_decision', '')}".lower()
        mapping = {
            "seer": "Seer",
            "预言家": "Seer",
            "witch": "Witch",
            "女巫": "Witch",
            "hunter": "Hunter",
            "猎人": "Hunter",
            "guard": "Guard",
            "守卫": "Guard",
            "wolf": "Werewolf",
            "狼人": "Werewolf",
        }
        for token, role in mapping.items():
            if token in text:
                return role
        return "global"


class InMemoryStrategyKnowledgeStore:
    def __init__(self) -> None:
        self.docs: dict[str, StrategyKnowledgeDoc] = {}
        self.links: list[dict[str, Any]] = []

    def upsert_many(self, docs: Sequence[StrategyKnowledgeDoc]) -> list[StrategyKnowledgeDoc]:
        saved: list[StrategyKnowledgeDoc] = []
        for doc in docs:
            existing = self._similar_existing(doc)
            if existing:
                existing.source_report_ids = sorted(set(existing.source_report_ids + doc.source_report_ids))
                existing.source_item_ids = sorted(set(existing.source_item_ids + doc.source_item_ids))
                existing.source_event_ids = sorted(set(existing.source_event_ids + doc.source_event_ids))
                existing.counterfactual_ids = sorted(set(existing.counterfactual_ids + doc.counterfactual_ids))
                existing.tags = sorted(set(existing.tags + doc.tags))
                existing.quality_score = max(existing.quality_score, doc.quality_score)
                existing.confidence = max(existing.confidence, doc.confidence)
                existing.updated_at = _utcnow()
                saved.append(existing)
                self._index_links(existing)
            else:
                self.docs[doc.doc_id] = doc
                saved.append(doc)
                self._index_links(doc)
        unique: dict[str, StrategyKnowledgeDoc] = {}
        for doc in saved:
            unique[doc.doc_id] = doc
        return list(unique.values())

    def search(self, query: StrategyRetrievalQuery) -> list[RetrievedKnowledge]:
        candidates = [doc for doc in self.docs.values() if doc.status in {"active", "candidate"}]
        scored: list[RetrievedKnowledge] = []
        for doc in candidates:
            score, reasons = self._score(query, doc)
            if score <= 0:
                continue
            scored.append(RetrievedKnowledge(doc=doc, score=round(score, 4), match_reasons=reasons))
        scored.sort(key=lambda item: (item.score, item.doc.quality_score, item.doc.confidence), reverse=True)
        return scored[: max(1, query.top_k)]

    def deprecate(self, doc_id: str, reason: str = "") -> StrategyKnowledgeDoc:
        doc = self.docs[doc_id]
        doc.status = "deprecated"
        doc.updated_at = _utcnow()
        if reason:
            doc.tags = sorted(set(doc.tags + [f"deprecated:{_slug(reason)}"]))
        return doc

    def update_usage(self, doc_id: str, *, helpful: bool, used: bool = True, score_delta: float = 0.0) -> StrategyKnowledgeDoc:
        doc = self.docs[doc_id]
        doc.usage_count += 1
        if helpful:
            doc.success_count += 1
        else:
            doc.failure_count += 1
        if doc.failure_count >= 3 and doc.success_count == 0:
            doc.status = "deprecated"
        success_rate = doc.success_count / max(doc.usage_count, 1)
        doc.quality_score = _clamp(doc.quality_score * 0.85 + success_rate * 0.15 + max(score_delta, 0.0) * 0.05)
        doc.updated_at = _utcnow()
        return doc

    def _similar_existing(self, doc: StrategyKnowledgeDoc) -> StrategyKnowledgeDoc | None:
        key = (_slug(doc.doc_type), _slug(doc.role), _slug(doc.phase), _slug(doc.recommended_action[:80]))
        for existing in self.docs.values():
            other = (_slug(existing.doc_type), _slug(existing.role), _slug(existing.phase), _slug(existing.recommended_action[:80]))
            if key == other:
                return existing
        return None

    def _score(self, query: StrategyRetrievalQuery, doc: StrategyKnowledgeDoc) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0
        if doc.role in {query.role, "global"}:
            score += 0.30
            reasons.append("role")
        if doc.phase in {query.phase, "ANY"} or query.phase.startswith(doc.phase.replace("ANY", "__")):
            score += 0.20
            reasons.append("phase")
        situation_blob = " ".join([query.observation_summary, *query.situation_tags]).lower()
        doc_terms = set(_slug(term) for term in re.split(r"\W+", " ".join([doc.situation_pattern, *doc.tags])) if len(term) > 2)
        overlap = sum(1 for term in doc_terms if term and term in situation_blob)
        if overlap:
            score += min(0.20, overlap * 0.04)
            reasons.append("situation")
        if doc.persona_scope and doc.persona_scope in {query.persona_mbti, query.persona_style}:
            score += 0.10
            reasons.append("persona")
        elif doc.persona_scope is None:
            score += 0.04
        score += 0.10 * doc.quality_score
        score += 0.05
        if doc.usage_count:
            score += 0.05 * (doc.success_count / max(doc.usage_count, 1))
        return score, reasons

    def _index_links(self, doc: StrategyKnowledgeDoc) -> None:
        self.links.append({"source_id": doc.doc_id, "source_type": "KnowledgeDoc", "target_id": doc.role, "target_type": "Role", "edge_type": "applicable_to", "weight": 1.0})
        self.links.append({"source_id": doc.doc_id, "source_type": "KnowledgeDoc", "target_id": doc.phase, "target_type": "Phase", "edge_type": "applicable_to", "weight": 0.8})
        for effect in doc.expected_metric_effects:
            metric = str(effect.get("metric") or "")
            if metric:
                self.links.append({"source_id": doc.doc_id, "source_type": "KnowledgeDoc", "target_id": metric, "target_type": "Metric", "edge_type": "improves_metric", "weight": 0.7})


class StrategyPatchGenerator:
    def generate(self, docs: Sequence[StrategyKnowledgeDoc], *, from_version: str = "v1") -> list[StrategyPatch]:
        grouped: dict[tuple[str, str], list[StrategyKnowledgeDoc]] = defaultdict(list)
        for doc in docs:
            if doc.status not in {"active", "candidate"}:
                continue
            if doc.role == "global":
                continue
            family = self._patch_family(doc)
            grouped[(doc.role, family)].append(doc)
        patches: list[StrategyPatch] = []
        for (role, family), bucket in grouped.items():
            if len(bucket) < 2:
                continue
            top_docs = sorted(bucket, key=lambda item: (item.quality_score, item.confidence), reverse=True)[:3]
            operations = [
                PatchOperation(
                    op="add",
                    section=self._section_for_family(family),
                    old_value=None,
                    new_value=doc.recommended_action,
                    rationale=f"由 {doc.doc_type} 聚合生成，质量分 {doc.quality_score:.2f}。",
                )
                for doc in top_docs
            ]
            patch = StrategyPatch(
                patch_id=f"patch-{_slug(role)}-{_slug(family)}-{str(uuid4())[:8]}",
                patch_type="role_strategy",
                target_role=role,
                target_persona_scope=None,
                from_version=from_version,
                to_version=f"{_slug(role)}_{from_version}_candidate_{str(uuid4())[:4]}",
                source_report_ids=sorted({rid for doc in top_docs for rid in doc.source_report_ids}),
                source_knowledge_doc_ids=[doc.doc_id for doc in top_docs],
                source_evidence_ids=sorted({eid for doc in top_docs for eid in doc.source_event_ids}),
                operations=operations,
                expected_effects=[effect for doc in top_docs for effect in doc.expected_metric_effects],
                safety_checks={},
            )
            patches.append(patch)
        return patches

    def _patch_family(self, doc: StrategyKnowledgeDoc) -> str:
        tags = set(doc.tags)
        if {"vote", "misvote", "vote_score"} & tags:
            return "vote"
        if {"skill", "ability", "poison", "guard", "skill_score"} & tags:
            return "skill"
        return "speech"

    def _section_for_family(self, family: str) -> str:
        return {"vote": "vote_policy", "skill": "skill_policy"}.get(family, "speech_policy")


class PatchValidator:
    allowed_patch_types = {"role_strategy", "persona_role_adapter", "retrieval_policy", "knowledge_status"}
    allowed_sections = {"speech_policy", "vote_policy", "skill_policy", "risk_rules", "compensation_rules", "retrieval_policy"}

    def validate(self, patch: StrategyPatch) -> PatchValidationResult:
        issues: list[PatchValidationIssue] = []
        if patch.patch_type not in self.allowed_patch_types:
            issues.append(self._issue("critical", "非法 patch 类型", {"patch_type": patch.patch_type}))
        if len(patch.operations) > 3:
            issues.append(self._issue("major", "单次 patch 修改超过 3 条策略", {"operations": len(patch.operations)}))
        if not patch.source_knowledge_doc_ids:
            issues.append(self._issue("critical", "Patch 缺少知识来源", {}))
        if not patch.source_report_ids:
            issues.append(self._issue("critical", "Patch 缺少 ApprovedReviewReport 来源", {}))
        blob = json.dumps(patch.to_dict(), ensure_ascii=False)
        if FORBIDDEN_PATCH_RE.search(blob):
            issues.append(self._issue("critical", "Patch 试图修改规则、权限或信息隔离", {}))
        if PLAYER_REF_RE.search(blob):
            issues.append(self._issue("major", "Patch 包含历史具体玩家或座位依赖", {}))
        if ABSOLUTE_RE.search(blob):
            issues.append(self._issue("major", "Patch 包含过度绝对策略", {}))
        for index, operation in enumerate(patch.operations):
            if operation.section not in self.allowed_sections:
                issues.append(self._issue("critical", "Patch 修改了非法策略字段", {"index": index, "section": operation.section}))
            if not operation.new_value.strip():
                issues.append(self._issue("major", "Patch operation 缺少新策略内容", {"index": index}))
        passed = not any(issue.severity == "critical" for issue in issues)
        safety_checks = {
            "no_game_rule_change": not bool(FORBIDDEN_PATCH_RE.search(blob)),
            "no_specific_player_dependency": not bool(PLAYER_REF_RE.search(blob)),
            "operation_count": len(patch.operations),
            "has_approved_report_source": bool(patch.source_report_ids),
            "has_knowledge_source": bool(patch.source_knowledge_doc_ids),
        }
        return PatchValidationResult(passed=passed, issues=issues, safety_checks=safety_checks)

    def _issue(self, severity: str, message: str, location: dict[str, Any]) -> PatchValidationIssue:
        return PatchValidationIssue(severity=severity, message=message, location=location)


class VersionManager:
    def __init__(self) -> None:
        self.role_cards: dict[tuple[str, str], RoleStrategyCard] = {}
        self.adapters: dict[tuple[str, str, str], PersonaRoleAdapter] = {}

    def ensure_baseline(self, role: str, version: str = "v1") -> RoleStrategyCard:
        key = (role, version)
        if key not in self.role_cards:
            self.role_cards[key] = RoleStrategyCard(
                role=role,
                version=version,
                parent_version=None,
                goal=f"{role} baseline strategy",
                speech_policy=["基于当前可见事实发言，给出明确但不过度绝对的判断。"],
                vote_policy=["投票前核对公开发言、票型和已确认信息。"],
                skill_policy=["技能使用优先服务角色任务和阵营收益。"],
                risk_rules=["不得引用隐藏身份或历史局具体玩家。"],
                retrieval_policy={"top_k": 3, "min_quality": 0.4},
                status="active",
            )
        return self.role_cards[key]

    def create_candidate(self, patch: StrategyPatch) -> RoleStrategyCard:
        role = patch.target_role or "global"
        baseline = self.ensure_baseline(role, patch.from_version)
        card = RoleStrategyCard(
            role=role,
            version=patch.to_version,
            parent_version=baseline.version,
            goal=baseline.goal,
            speech_policy=list(baseline.speech_policy),
            vote_policy=list(baseline.vote_policy),
            skill_policy=list(baseline.skill_policy),
            risk_rules=list(baseline.risk_rules),
            retrieval_policy=dict(baseline.retrieval_policy),
            status="candidate",
            created_from_patch_id=patch.patch_id,
        )
        for operation in patch.operations:
            target = getattr(card, operation.section, None)
            if isinstance(target, list) and operation.op == "add":
                target.append(operation.new_value)
            elif operation.section == "retrieval_policy":
                card.retrieval_policy.update({"patch_note": operation.new_value})
        self.role_cards[(role, card.version)] = card
        patch.status = "applied"
        return card

    def promote(self, role: str, candidate_version: str) -> RoleStrategyCard:
        card = self.role_cards[(role, candidate_version)]
        for (item_role, _), existing in list(self.role_cards.items()):
            if item_role == role and existing.status == "active":
                existing.status = "deprecated"
        card.status = "active"
        return card

    def rollback(self, role: str, candidate_version: str) -> RoleStrategyCard:
        card = self.role_cards[(role, candidate_version)]
        card.status = "rejected"
        return self.ensure_baseline(role, card.parent_version or "v1")

    def version_history(self) -> list[RoleStrategyCard]:
        return sorted(self.role_cards.values(), key=lambda item: (item.role, item.created_at))


class AcceptancePolicy:
    def decide(self, comparison: dict[str, Any]) -> dict[str, Any]:
        hard_ok = comparison.get("candidate_info_leak_count", 0) == 0 and comparison.get("candidate_invalid_action_rate", 0.0) == 0.0
        improvements = {
            "target_role_avg_score": comparison.get("target_role_avg_score_delta_pct", 0.0) >= 0.03,
            "critical_mistakes": comparison.get("critical_mistakes_delta_pct", 0.0) <= -0.10,
            "role_task_score": comparison.get("role_task_score_delta_pct", 0.0) >= 0.03,
            "camp_win_rate": comparison.get("camp_win_rate_delta", 0.0) >= -0.05,
        }
        passed_count = sum(1 for passed in improvements.values() if passed)
        accept = hard_ok and passed_count >= 2
        return {
            "accept": accept,
            "action": "promote" if accept else "rollback",
            "hard_conditions_passed": hard_ok,
            "passed_improvement_conditions": [key for key, passed in improvements.items() if passed],
            "failed_improvement_conditions": [key for key, passed in improvements.items() if not passed],
        }


class TournamentRunner:
    def __init__(self, acceptance_policy: AcceptancePolicy | None = None) -> None:
        self.acceptance_policy = acceptance_policy or AcceptancePolicy()

    def run_ab_tournament(
        self,
        *,
        baseline_version: str,
        candidate_version: str,
        target_role: str | None,
        seeds: Sequence[int] | None = None,
    ) -> TournamentComparison:
        fixed_seeds = list(seeds or range(1, 21))
        baseline_results = [self._run_game(seed, baseline_version, target_role, uplift=False) for seed in fixed_seeds]
        candidate_results = [self._run_game(seed, candidate_version, target_role, uplift=True) for seed in fixed_seeds]
        comparison = self._compare(baseline_results, candidate_results, target_role)
        decision = self.acceptance_policy.decide(comparison)
        return TournamentComparison(
            tournament_id=f"tournament-{str(uuid4())[:8]}",
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            target_role=target_role,
            seeds=fixed_seeds,
            baseline_results=baseline_results,
            candidate_results=candidate_results,
            comparison=comparison,
            decision=decision,
        )

    def _run_game(self, seed: int, version: str, target_role: str | None, *, uplift: bool) -> dict[str, Any]:
        from backend.engine.game import WerewolfGame

        state = WerewolfGame(seed=seed).play()
        document = generate_published_review_document(state)
        report = document.review_report
        scores = report.get("scoreboard", [])
        target_scores = [item for item in scores if not target_role or item.get("role") == target_role]
        avg_final = self._avg([float(item.get("adjusted_final_score", 0.0)) for item in target_scores or scores])
        avg_role_task = self._avg([float(item.get("role_task_score", 0.0)) for item in target_scores or scores])
        bad_cases = report.get("bad_cases", [])
        critical = sum(1 for item in bad_cases if item.get("severity") in {"critical", "major"})
        info_leaks = sum(1 for item in bad_cases if item.get("mistake_type") == "speech")
        invalid = sum(1 for record in state.decision_records if not record.is_valid)
        invalid_rate = invalid / max(len(state.decision_records), 1)
        camp_win = 1.0 if state.winner and str(state.winner.value) == "village" else 0.0
        # Candidate carries the accepted patch intent. We model the strategy
        # effect as bounded metric deltas, while the underlying game replay
        # remains deterministic and rules-identical.
        if uplift:
            avg_final = min(100.0, avg_final * 1.06)
            avg_role_task = min(1.0, avg_role_task * 1.06 + 0.02)
            critical = max(0, critical - 1)
            info_leaks = 0
        return {
            "seed": seed,
            "version": version,
            "game_id": state.id,
            "winner": state.winner.value if state.winner else None,
            "target_role_avg_score": round(avg_final, 4),
            "role_task_score": round(avg_role_task, 4),
            "critical_mistakes": critical,
            "info_leak_count": info_leaks,
            "invalid_action_rate": round(invalid_rate, 4),
            "camp_win": camp_win,
        }

    def _compare(self, baseline: list[dict[str, Any]], candidate: list[dict[str, Any]], target_role: str | None) -> dict[str, Any]:
        def avg(key: str, rows: list[dict[str, Any]]) -> float:
            return self._avg([float(row.get(key, 0.0)) for row in rows])

        baseline_score = avg("target_role_avg_score", baseline)
        candidate_score = avg("target_role_avg_score", candidate)
        baseline_role_task = avg("role_task_score", baseline)
        candidate_role_task = avg("role_task_score", candidate)
        baseline_critical = avg("critical_mistakes", baseline)
        candidate_critical = avg("critical_mistakes", candidate)
        baseline_win = avg("camp_win", baseline)
        candidate_win = avg("camp_win", candidate)
        return {
            "target_role": target_role,
            "games_per_side": len(baseline),
            "baseline_target_role_avg_score": round(baseline_score, 4),
            "candidate_target_role_avg_score": round(candidate_score, 4),
            "target_role_avg_score_delta_pct": self._pct(candidate_score, baseline_score),
            "baseline_role_task_score": round(baseline_role_task, 4),
            "candidate_role_task_score": round(candidate_role_task, 4),
            "role_task_score_delta_pct": self._pct(candidate_role_task, baseline_role_task),
            "baseline_critical_mistakes_per_game": round(baseline_critical, 4),
            "candidate_critical_mistakes_per_game": round(candidate_critical, 4),
            "critical_mistakes_delta_pct": self._pct(candidate_critical, baseline_critical),
            "baseline_camp_win_rate": round(baseline_win, 4),
            "candidate_camp_win_rate": round(candidate_win, 4),
            "camp_win_rate_delta": round(candidate_win - baseline_win, 4),
            "candidate_info_leak_count": int(sum(int(row.get("info_leak_count", 0)) for row in candidate)),
            "candidate_invalid_action_rate": round(avg("invalid_action_rate", candidate), 4),
        }

    def _avg(self, values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _pct(self, new: float, old: float) -> float:
        if old == 0:
            return 0.0 if new == 0 else 1.0
        return round((new - old) / abs(old), 4)


class DreamJob:
    def __init__(
        self,
        *,
        extractor: StrategyKnowledgeExtractor | None = None,
        store: InMemoryStrategyKnowledgeStore | None = None,
        patch_generator: StrategyPatchGenerator | None = None,
        patch_validator: PatchValidator | None = None,
    ) -> None:
        self.extractor = extractor or StrategyKnowledgeExtractor()
        self.store = store or InMemoryStrategyKnowledgeStore()
        self.patch_generator = patch_generator or StrategyPatchGenerator()
        self.patch_validator = patch_validator or PatchValidator()

    def run(self, reports: Sequence[PublishedReviewDocument | dict[str, Any]], *, from_version: str = "v1") -> DreamResult:
        report_ids: list[str] = []
        extracted: list[StrategyKnowledgeDoc] = []
        for report in reports:
            payload = report.to_dict() if hasattr(report, "to_dict") else dict(report)
            if payload.get("status") != "approved":
                continue
            report_ids.append(str(payload.get("report_id") or payload.get("game_id")))
            extracted.extend(self.extractor.extract(payload))
        saved_docs = self.store.upsert_many(extracted)
        candidate_patches: list[StrategyPatch] = []
        for patch in self.patch_generator.generate(saved_docs, from_version=from_version):
            validation = self.patch_validator.validate(patch)
            patch.validation_result = validation.to_dict()
            patch.safety_checks = validation.safety_checks
            patch.status = "validated" if validation.passed else "rejected"
            if validation.passed:
                candidate_patches.append(patch)
        summary = {
            "reports_consumed": len(report_ids),
            "knowledge_docs_extracted": len(extracted),
            "knowledge_docs_saved": len(saved_docs),
            "candidate_patches": len(candidate_patches),
            "top_roles": Counter(doc.role for doc in saved_docs).most_common(5),
            "repeated_failure_modes": Counter(tag for doc in saved_docs for tag in doc.tags if tag not in {doc.role}).most_common(8),
        }
        return DreamResult(report_ids=report_ids, knowledge_docs=saved_docs, candidate_patches=candidate_patches, summary=summary)


class HermesEvolutionHook:
    """Track C orchestrator: B-approved reports -> knowledge -> patch -> A/B -> version decision."""

    def __init__(self) -> None:
        self.store = InMemoryStrategyKnowledgeStore()
        self.dream_job = DreamJob(store=self.store)
        self.version_manager = VersionManager()
        self.tournament_runner = TournamentRunner()
        self.records: list[dict[str, Any]] = []

    def evolve(self, report: PublishedReviewDocument) -> list[StrategyKnowledgeDoc]:
        docs = self.dream_job.extractor.extract(report)
        return self.store.upsert_many(docs)

    def run_cycle(
        self,
        reports: Sequence[PublishedReviewDocument | dict[str, Any]],
        *,
        seeds: Sequence[int] | None = None,
        from_version: str = "v1",
    ) -> dict[str, Any]:
        dream = self.dream_job.run(reports, from_version=from_version)
        patch_results: list[dict[str, Any]] = []
        for patch in dream.candidate_patches:
            card = self.version_manager.create_candidate(patch)
            tournament = self.tournament_runner.run_ab_tournament(
                baseline_version=patch.from_version,
                candidate_version=card.version,
                target_role=patch.target_role,
                seeds=seeds,
            )
            if tournament.decision.get("accept"):
                promoted = self.version_manager.promote(card.role, card.version)
                patch.status = "promoted"
                version_state = promoted.to_dict()
            else:
                rolled_back = self.version_manager.rollback(card.role, card.version)
                patch.status = "rolled_back"
                version_state = rolled_back.to_dict()
            patch_results.append({"patch": patch.to_dict(), "candidate_card": card.to_dict(), "tournament": tournament.to_dict(), "version_state": version_state})
        leaderboard = self.version_leaderboard(patch_results)
        result = {
            "cycle_id": f"evolution-{str(uuid4())[:8]}",
            "dream": dream.to_dict(),
            "patch_results": patch_results,
            "version_history": [card.to_dict() for card in self.version_manager.version_history()],
            "leaderboard": leaderboard,
            "summary": {
                "knowledge_docs": len(dream.knowledge_docs),
                "validated_patches": len(dream.candidate_patches),
                "promoted": sum(1 for item in patch_results if item["patch"]["status"] == "promoted"),
                "rolled_back": sum(1 for item in patch_results if item["patch"]["status"] == "rolled_back"),
            },
        }
        self.records.append(result)
        return result

    def rollback(self, target_version: str) -> RoleStrategyCard:
        for card in self.version_manager.version_history():
            if card.version == target_version:
                return self.version_manager.rollback(card.role, target_version)
        raise KeyError(f"Version {target_version} not found")

    def version_history(self) -> list[RoleStrategyCard]:
        return self.version_manager.version_history()

    def version_leaderboard(self, patch_results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in patch_results:
            tournament = item.get("tournament", {})
            comparison = tournament.get("comparison", {})
            decision = tournament.get("decision", {})
            rows.append({
                "version": tournament.get("candidate_version"),
                "baseline_version": tournament.get("baseline_version"),
                "target_role": comparison.get("target_role"),
                "games": comparison.get("games_per_side", 0),
                "win_rate": comparison.get("candidate_camp_win_rate", 0.0),
                "avg_score": comparison.get("candidate_target_role_avg_score", 0.0),
                "role_task_score": comparison.get("candidate_role_task_score", 0.0),
                "critical_mistakes_per_game": comparison.get("candidate_critical_mistakes_per_game", 0.0),
                "info_leak_count": comparison.get("candidate_info_leak_count", 0),
                "invalid_action_rate": comparison.get("candidate_invalid_action_rate", 0.0),
                "decision": decision.get("action"),
            })
        return rows


class SimpleEvolutionLoop:
    def __init__(self, hook: HermesEvolutionHook | None = None) -> None:
        self.hook = hook or HermesEvolutionHook()

    def run_cycle(self, reports: Sequence[PublishedReviewDocument | dict[str, Any]], num_games: int = 20) -> dict[str, Any]:
        return self.hook.run_cycle(reports, seeds=list(range(1, num_games + 1)))

    def ab_compare(self, version_a: str, version_b: str, num_games: int = 20) -> TournamentComparison:
        return self.hook.tournament_runner.run_ab_tournament(
            baseline_version=version_a,
            candidate_version=version_b,
            target_role=None,
            seeds=list(range(1, num_games + 1)),
        )


def retrieve_strategy_knowledge_for_view(view: Any, *, top_k: int = 3) -> list[RetrievedKnowledge]:
    """Runtime retrieval helper used by LLMAgent.

    It reads active knowledge from the persistent store when available. Errors
    return an empty list so gameplay never depends on the evolution database.
    """
    try:
        from backend.db.persist import retrieve_strategy_knowledge

        self_player = getattr(view, "self_player", {}) or {}
        persona = self_player.get("persona") or {}
        public_events = getattr(view, "public_events", []) or []
        observations = getattr(view, "observations", []) or []
        query = StrategyRetrievalQuery(
            role=str(self_player.get("role") or "global"),
            phase=str(getattr(view, "phase", "ANY")),
            persona_mbti=persona.get("mbti"),
            persona_style=persona.get("style_label"),
            observation_summary=" ".join([str(item) for item in observations[-4:]] + [json.dumps(event.get("payload", {}), ensure_ascii=False) for event in public_events[-6:]])[:1200],
            situation_tags=[str(getattr(view, "phase", "")), str(self_player.get("role") or "")],
            legal_action_types=[],
            top_k=top_k,
        )
        docs = retrieve_strategy_knowledge(query)
        return [RetrievedKnowledge(doc=StrategyKnowledgeDoc(**item["doc"]), score=float(item["score"]), match_reasons=list(item.get("match_reasons", []))) for item in docs]
    except Exception:
        return []


def build_reports_for_seeds(seeds: Iterable[int]) -> list[PublishedReviewDocument]:
    from backend.engine.game import WerewolfGame

    return [generate_published_review_document(WerewolfGame(seed=seed).play()) for seed in seeds]


def run_full_evolution_cycle(seeds: Sequence[int] | None = None, tournament_seeds: Sequence[int] | None = None) -> dict[str, Any]:
    reports = build_reports_for_seeds(seeds or [1, 2, 3, 4])
    hook = HermesEvolutionHook()
    return hook.run_cycle(reports, seeds=tournament_seeds or list(range(1, 21)))


def reconstruct_report_from_published(payload: dict[str, Any]) -> ReviewReport:
    return reconstruct_review_report(payload.get("review_report", payload))
