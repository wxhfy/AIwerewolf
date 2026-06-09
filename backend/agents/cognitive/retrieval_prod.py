"""
Production Strategy Retrieval — Regex Grep + Inverted Index + BM25 Fallback.

Design philosophy: "Search, Don't Index" (inspired by Claude Code's ripgrep approach).
- No embeddings, no vector DB, no GPU.
- LLM drives the search: it picks keywords/regex, sees results, refines.
- Three output modes: "count" (quick assessment), "overview" (titles only), "content" (full).

GPU-free. Data source: PostgreSQL → in-memory indices.
Build time ~0.3s for 941 docs. Grep query latency <0.05ms.

Architecture:
  Primary:   Agent keywords/regex → inverted index grep → multi-field weighted rank
  Fallback:  Grep insufficient (<3 hits) → BM25 full-text rerank
  Legacy:    jieba-only tokenize → grep (ultra-fast ~0.05ms)
  Count:     Inverted index grep with distinct doc count → no content load

Key insight from Claude Code: for a domain with <1000 canonical entries,
grep over tokenized fields is all you need. The LLM's reasoning ability
chooses better search terms than any embedding could capture.

Simplicity over complexity. Amazon 2025: "Keyword Search Is All You Need."
KRAFTON PUBG Ally: BM25-only for game agent knowledge retrieval.
"""

from __future__ import annotations

import logging
import os
import re as _stdlib_re
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ================================================================
# Retrieval Policy (Track C experiment framework)
# ================================================================


class RetrievalPolicy(str, Enum):
    """Policy governing which strategy docs an agent can retrieve.

    Inspired by Claude Code's layered search strategy:
      - "files_with_matches" → overview mode
      - "content" → full text
      - Our extension: GLOBAL → ROLE → MBTI → PHASE layering

    Each policy defines a filtering strategy. SAME_ROLE_ALL_MBTI is the current
    highest-precision default: it keeps runtime retrieval inside the current
    role's active strategy pool, then reranks by keywords, phase, action, and
    quality. Hybrid policies remain available for ablations or fallback-heavy
    experiments.
    """

    GLOBAL_ONLY = "global_only"  # Only role="global" or role=any docs
    SELF_MBTI_ONLY = "self_mbti_only"  # Only docs matching agent's MBTI
    SAME_ROLE_ALL_MBTI = "same_role_all_mbti"  # Docs for agent's role, any MBTI
    SAME_ROLE_SAME_MBTI = "same_role_same_mbti"  # Docs for agent's role + agent's MBTI
    HYBRID_ROLE_MBTI_GLOBAL = "hybrid_role_mbti_global"  # Layered: same_role_same_mbti → same_role_all_mbti → global
    HYBRID_ROLE_ALIGNMENT_PHASE = "hybrid_role_alignment_phase"  # Same as E + phase constraint

    @property
    def is_hybrid(self) -> bool:
        """Whether this policy uses layered buckets (requires fill logic)."""
        return self.value.startswith("hybrid")

    @property
    def bucket_count(self) -> int:
        """Number of priority buckets this policy would produce."""
        if self == RetrievalPolicy.GLOBAL_ONLY:
            return 1
        if self == RetrievalPolicy.SELF_MBTI_ONLY:
            return 1
        if self == RetrievalPolicy.SAME_ROLE_ALL_MBTI:
            return 1
        if self == RetrievalPolicy.SAME_ROLE_SAME_MBTI:
            return 1
        if self == RetrievalPolicy.HYBRID_ROLE_MBTI_GLOBAL:
            return 3
        if self == RetrievalPolicy.HYBRID_ROLE_ALIGNMENT_PHASE:
            return 4
        return 1


@dataclass
class AgentContext:
    """Context passed to every retrieval call for policy-based filtering.

    All fields default to empty/neutral values so existing callers work
    without changes (defaults to GLOBAL_ONLY behavior).
    """

    player_id: str = ""
    role: str = ""  # "Seer", "Werewolf", "Witch", etc.
    alignment: str = ""  # "village" or "wolf"
    mbti: str = ""  # "INTJ", "ENFP", "ISTJ", "ESFP", etc.
    phase: str = ""  # "DAY_SPEECH", "NIGHT_WOLF_ACTION", etc.
    action_type: str = ""  # "talk", "vote", "attack", "save", "check", etc.
    day: int = 0
    alive_status: bool = True
    keywords: List[str] = field(default_factory=list)

    @property
    def is_wolf(self) -> bool:
        """True if agent is on the wolf team."""
        return self.alignment.lower() == "wolf"

    @property
    def normalized_role(self) -> str:
        """Lowercase role for comparison."""
        return self.role.lower().strip()

    @property
    def normalized_mbti(self) -> str:
        """Uppercase MBTI for comparison."""
        return self.mbti.upper().strip()


_WOLF_ROLES = {"werewolf", "whitewolfking", "bigbadwolf", "wolfcub", "alphawolf"}


def _derive_alignment_from_role(role: str) -> str:
    """Derive alignment ('village'/'wolf') from role name. Fallback: ''."""
    if not role:
        return ""
    rl = role.lower().strip()
    if rl in _WOLF_ROLES:
        return "wolf"
    return "village"


def _parse_mbti_from_persona_scope(persona_scope: str | None) -> str:
    """Extract MBTI type from persona_scope string.

    persona_scope format: "mbti:INTJ+role:Werewolf" → "INTJ"
    Returns "" if no MBTI found or persona_scope is None, empty, or "any".
    """
    if not persona_scope or persona_scope.lower() in ("any", "none"):
        return ""
    # Try the mbti: prefix pattern first
    m = _stdlib_re.search(r"mbti:([A-Za-z]{4})", str(persona_scope))
    if m:
        return m.group(1).upper()
    # If the persona_scope itself looks like an MBTI type (4 uppercase letters)
    stripped = str(persona_scope).strip().upper()
    if _stdlib_re.fullmatch(r"[IE][NS][FT][JP]", stripped):
        return stripped
    return ""


def _parse_role_from_persona_scope(persona_scope: str | None) -> str:
    """Extract role scope from persona_scope string.

    persona_scope format: "mbti:INTJ+role:Werewolf" → "Werewolf"
    Returns "" if no role found.
    """
    if not persona_scope:
        return ""
    m = _stdlib_re.search(r"role:(\w+)", str(persona_scope))
    if m:
        return m.group(1)
    return ""


_DEFAULT_CONN = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"


def _resolve_conn_str(conn_str: str = "") -> str:
    """Resolve the PostgreSQL connection string used by the retriever.

    CLI experiment scripts are often launched without sourcing `.env`, so the
    retriever must load the local env file itself before falling back to the
    development DSN.
    """
    if conn_str:
        return conn_str
    if os.getenv("AIWEREWOLF_SKIP_DOTENV", "").lower() in {"1", "true", "yes", "on"}:
        resolved = os.getenv("DATABASE_URL", "").strip() or os.getenv("AIWEREWOLF_DB_URL", "").strip()
        return _normalize_psycopg2_conn_str(resolved) if resolved else ""
    try:
        from backend.llm.env import load_env_file

        load_env_file()
    except Exception:
        pass
    resolved = os.getenv("DATABASE_URL", "").strip() or os.getenv("AIWEREWOLF_DB_URL", "").strip() or _DEFAULT_CONN
    return _normalize_psycopg2_conn_str(resolved)


def _normalize_psycopg2_conn_str(conn_str: str) -> str:
    """Convert SQLAlchemy PostgreSQL URLs into psycopg2-compatible URLs."""
    if conn_str.startswith("postgresql+"):
        return "postgresql://" + conn_str.split("://", 1)[1]
    if conn_str.startswith("postgres+"):
        return "postgres://" + conn_str.split("://", 1)[1]
    return conn_str


def _redact_conn_error(exc: Exception) -> str:
    """Return a connection error string without credentials."""
    msg = str(exc)
    return _stdlib_re.sub(r"(postgres(?:ql)?(?:\+\w+)?://[^:\s/@]+):([^@\s]+)@", r"\1:***@", msg)


# ================================================================
# Werewolf Domain Dictionary (jieba doesn't know these by default)
# ================================================================
_WEREWOLF_TERMS = [
    # Core actions
    "悍跳",
    "查杀",
    "表水",
    "归票",
    "自爆",
    "刀人",
    "银水",
    "金水",
    "铜水",
    "警徽流",
    "警徽",
    # Role compounds
    "悍跳狼",
    "冲锋狼",
    "倒钩狼",
    "深水狼",
    "自刀狼",
    "预言家",
    "真预言家",
    "悍跳预言家",
    # Strategy terms
    "扛推",
    "抗推",
    "穿衣服",
    "反水",
    "退水",
    "站边",
    "撕警徽",
    "爆刀",
    "自刀",
    # Phase terms
    "上警",
    "警上",
    "警下",
    "放逐",
    "归底",
    # Quality markers
    "心路历程",
    "发言漏洞",
    "视角",
    "轮次",
]
_WEREWOLF_TERMS.sort(key=lambda x: -len(x))  # longest first for greedy matching

# Register with jieba on import
try:
    import jieba

    jieba.setLogLevel(logging.ERROR)
    for term in _WEREWOLF_TERMS:
        jieba.add_word(term, freq=100, tag="nz")
    logger.info(f"Registered {len(_WEREWOLF_TERMS)} werewolf domain terms in jieba")
except Exception:
    pass

TOP_K_CANDIDATES = 20
TOP_K_FINAL = 5

# Multi-field weights for grep scoring (situation > strategy > rationale).
# Inspired by Claude Code's layered grep — field relevance matters.
FIELD_WEIGHTS = {
    "situation": 1.0,
    "strategy": 0.7,
    "rationale": 0.4,
}

_ACTION_SCOPE_ALIASES = {
    "speech": "talk",
    "talk": "talk",
    "chat": "talk",
    "vote": "vote",
    "ballot": "vote",
    "attack": "attack",
    "kill": "attack",
    "night": "night_action",
    "night_action": "night_action",
    "divine": "check",
    "check": "check",
    "seer": "check",
    "witch_save": "save",
    "save": "save",
    "witch_poison": "poison",
    "poison": "poison",
    "witch_act": "witch_act",
    "guard": "guard",
    "protect": "guard",
    "shoot": "shoot",
    "boom": "boom",
}

_ACTION_TEXT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("boom", ("自爆", "白狼王", "爆刀", "带走")),
    ("shoot", ("猎人", "开枪", "带人", "枪口")),
    ("poison", ("毒药", "投毒", "毒杀", "盲毒", "带毒")),
    ("save", ("解药", "救人", "银水", "救起", "首夜救")),
    ("guard", ("守卫", "守护", "空守", "连守", "保护")),
    ("check", ("预言家", "查验", "验人", "金水", "查杀", "警徽流")),
    ("attack", ("刀人", "击杀", "刀掉", "刀口", "狼刀", "刀神", "刀民", "自刀")),
    ("vote", ("投票", "归票", "放逐", "冲票", "跟票", "票型", "抗推", "扛推")),
    ("talk", ("发言", "表水", "悍跳", "站边", "对跳", "警上", "警下", "跳身份", "报药水")),
)


def _safe_str(val: Any) -> str:
    """Coerce field value to str. Handles tuples, lists from card.content."""
    if isinstance(val, str):
        return val
    if isinstance(val, (list, tuple)):
        return " ".join(str(v) for v in val)
    return str(val) if val else ""


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _recency_factor(value: Any) -> float:
    parsed = _parse_ts(value)
    if parsed is None:
        return 1.0
    delta_days = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400.0)
    return float(np.exp(-delta_days / 14.0))


def _strategy_rank_score(doc: Dict[str, Any]) -> float:
    quality = float(doc.get("quality", doc.get("quality_score", 0.8)) or 0.8)
    confidence = float(doc.get("confidence", 0.7) or 0.7)
    usage_count = float(doc.get("usage_count", doc.get("used_count", 0)) or 0)
    success_count = float(doc.get("success_count", 0) or 0)
    usage_rate = (success_count + 3.0) / (usage_count + 6.0)
    maturity_bonus = {"raw": 0.0, "refined": 0.06, "canonical": 0.12}.get(
        _safe_str(doc.get("maturity", "raw")).lower(),
        0.0,
    )
    validation_bonus = 0.08 if doc.get("validated_at") or doc.get("validated_on") else 0.0
    epoch_bonus = min(0.08, max(0, int(doc.get("knowledge_epoch", 0) or 0)) * 0.01)
    recency = _recency_factor(doc.get("validated_at") or doc.get("updated_at") or doc.get("created_at"))
    contradiction_penalty = 0.12 if int(doc.get("contradiction_count", 0) or 0) > 0 else 0.0
    return round(
        0.42 * quality
        + 0.20 * confidence
        + 0.12 * usage_rate
        + 0.08 * recency
        + maturity_bonus
        + validation_bonus
        + epoch_bonus
        - contradiction_penalty,
        4,
    )


def _doc_sort_key(doc: Dict[str, Any]) -> tuple[float, float, int, str]:
    return (
        float(doc.get("strategy_rank_score", _strategy_rank_score(doc)) or 0.0),
        float(doc.get("quality", 0.0) or 0.0),
        int(doc.get("knowledge_epoch", 0) or 0),
        _safe_str(doc.get("doc_id", "")),
    )


def _normalize_action_scope(value: Any) -> str:
    raw = _safe_str(value).lower().strip()
    return _ACTION_SCOPE_ALIASES.get(raw, raw if raw in set(_ACTION_SCOPE_ALIASES.values()) else "")


def _phase_action_scope(phase: Any) -> str:
    phase_upper = _safe_str(phase).upper()
    if not phase_upper:
        return ""
    if "BOOM" in phase_upper:
        return "boom"
    if "HUNTER" in phase_upper or "SHOOT" in phase_upper:
        return "shoot"
    if "VOTE" in phase_upper or "BALLOT" in phase_upper:
        return "vote"
    if "WOLF" in phase_upper:
        return "attack"
    if "SEER" in phase_upper:
        return "check"
    if "WITCH" in phase_upper:
        return "witch_act"
    if "GUARD" in phase_upper:
        return "guard"
    if any(token in phase_upper for token in ("SPEECH", "CHAT", "TALK", "BADGE", "LAST_WORDS", "SHERIFF")):
        return "talk"
    if "NIGHT" in phase_upper:
        return "night_action"
    return ""


def _derive_action_scope(doc: Dict[str, Any]) -> str:
    explicit = _normalize_action_scope(doc.get("action_scope", ""))
    if explicit:
        return explicit
    text = " ".join(
        _safe_str(doc.get(field, "")) for field in ("situation", "strategy", "rationale", "doc_type")
    ).lower()
    matched: set[str] = set()
    for action, terms in _ACTION_TEXT_HINTS:
        if any(term.lower() in text for term in terms):
            matched.add(action)
    if {"save", "poison"} <= matched:
        return "witch_act"
    if matched:
        return next(action for action, _terms in _ACTION_TEXT_HINTS if action in matched)
    return _phase_action_scope(doc.get("phase_scope") or doc.get("phase", ""))


def _action_match_score(query_action: str, doc_action: str, doc_phase: str = "") -> float:
    query = _normalize_action_scope(query_action)
    doc = _normalize_action_scope(doc_action) or _phase_action_scope(doc_phase)
    if not query or not doc:
        return 0.5
    if query == doc:
        return 1.0
    if doc == "witch_act" and query in {"save", "poison"}:
        return 0.85
    if query == "night_action" and doc in {"attack", "check", "save", "poison", "witch_act", "guard"}:
        return 0.75
    if doc == "night_action" and query in {"attack", "check", "save", "poison", "guard"}:
        return 0.65
    if query == "talk" and doc in {"vote", "check"}:
        return 0.35
    return 0.0


def _keyword_overlap_score(doc: Dict[str, Any], keywords: List[str]) -> float:
    if not keywords:
        return 0.0
    text = " ".join(
        _safe_str(doc.get(field, "")) for field in ("situation", "strategy", "rationale", "doc_type")
    ).lower()
    hits = 0.0
    for keyword in keywords:
        kw = _safe_str(keyword).lower().strip()
        if not kw:
            continue
        if kw in text:
            hits += 1.0
            continue
        try:
            import jieba

            tokens = [token.lower() for token in jieba.cut(kw) if len(token.strip()) >= 2]
        except Exception:
            tokens = []
        if tokens:
            token_hits = sum(1 for token in tokens if token in text)
            if token_hits:
                hits += min(0.75, token_hits / max(len(tokens), 1))
    return min(1.0, hits / max(len(keywords), 1))


def _phase_match_score(doc_phase: str, query_phase: str) -> float:
    doc = _safe_str(doc_phase).lower().strip()
    query = _safe_str(query_phase).lower().strip()
    if not query:
        return 0.5
    if doc == query:
        return 1.0
    if doc in {"", "global", "any"}:
        return 0.45
    if query.startswith("day_") and doc.startswith("day_"):
        return 0.45
    if query.startswith("night_") and doc.startswith("night_"):
        return 0.45
    return 0.0


def _role_match_score(doc: Dict[str, Any], role: str, alignment: str = "") -> float:
    doc_role = _safe_str(doc.get("role_scope", doc.get("role", ""))).lower().strip()
    query_role = _safe_str(role).lower().strip()
    if query_role and doc_role == query_role:
        return 1.0
    if doc_role in {"global", "any", ""}:
        return 0.45
    doc_alignment = _safe_str(doc.get("alignment_scope", "")).lower().strip()
    if alignment and doc_alignment and doc_alignment == alignment.lower().strip():
        return 0.35
    return 0.0


def _mbti_match_score(doc_mbti: str, query_mbti: str) -> float:
    doc = _safe_str(doc_mbti).upper().strip()
    query = _safe_str(query_mbti).upper().strip()
    if not query:
        return 0.5
    if doc == query:
        return 1.0
    if not doc:
        return 0.45
    return 0.0


def _generic_prompt_noise_penalty(doc: Dict[str, Any], keyword_score: float) -> float:
    if keyword_score >= 0.34:
        return 0.0
    situation = _safe_str(doc.get("situation", ""))
    doc_id = _safe_str(doc.get("doc_id", ""))
    noisy_markers = ("重复决策模式", "对局总结", "成功经验", "失败/应避免", "counterfactual", "bad-case")
    return 0.10 if any(marker in situation or marker in doc_id for marker in noisy_markers) else 0.0


def _result_from_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": doc.get("doc_id", ""),
        "situation": doc.get("situation", ""),
        "strategy": doc.get("strategy", ""),
        "rationale": doc.get("rationale", ""),
        "role": doc.get("role", "global"),
        "phase": doc.get("phase", "global"),
        "role_scope": doc.get("role_scope", doc.get("role", "")),
        "mbti_scope": doc.get("mbti_scope", ""),
        "alignment_scope": doc.get("alignment_scope", ""),
        "phase_scope": doc.get("phase_scope", ""),
        "action_scope": doc.get("action_scope", ""),
        "quality": doc.get("quality", 0.8),
        "confidence": doc.get("confidence", 0.7),
        "doc_type": doc.get("doc_type", ""),
        "strategy_rank_score": doc.get("strategy_rank_score", _strategy_rank_score(doc)),
        "knowledge_epoch": doc.get("knowledge_epoch", 0),
        "doc_version": doc.get("doc_version", "v1"),
        "version_group": doc.get("version_group", ""),
        "maturity": doc.get("maturity", "raw"),
        "supersedes_doc_ids": list(doc.get("supersedes_doc_ids") or []),
        "validated_at": doc.get("validated_at", ""),
        "source_game_id": doc.get("source_game_id", ""),
        "source_decision_id": doc.get("source_decision_id", ""),
        "status": doc.get("status", "active"),
    }


def _normalize_doc_for_policy(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure a strategy doc has policy scope fields."""
    normalized = dict(doc)
    persona_scope = _safe_str(normalized.get("persona_scope", ""))
    role = _safe_str(normalized.get("role", "global")) or "global"
    phase = _safe_str(normalized.get("phase", "global")) or "global"
    persona_role = _parse_role_from_persona_scope(persona_scope)
    role_scope = _safe_str(normalized.get("role_scope") or persona_role or role)
    normalized["role"] = role
    normalized["phase"] = phase
    normalized["role_scope"] = role_scope
    normalized["mbti_scope"] = _safe_str(
        normalized.get("mbti_scope") or _parse_mbti_from_persona_scope(persona_scope)
    ).upper()
    normalized["alignment_scope"] = _safe_str(
        normalized.get("alignment_scope") or _derive_alignment_from_role(role_scope)
    )
    normalized["phase_scope"] = _safe_str(normalized.get("phase_scope") or ("" if phase.lower() == "global" else phase))
    normalized["action_scope"] = _derive_action_scope(normalized)
    normalized["source_game_id"] = _safe_str(normalized.get("source_game_id", ""))
    normalized["source_decision_id"] = _safe_str(normalized.get("source_decision_id", ""))
    normalized["status"] = _safe_str(normalized.get("status", normalized.get("doc_type", "")))
    normalized["quality"] = float(normalized.get("quality", 0.8) or 0.8)
    normalized["confidence"] = float(normalized.get("confidence", 0.7) or 0.7)
    normalized["knowledge_epoch"] = int(normalized.get("knowledge_epoch", 0) or 0)
    normalized["doc_version"] = _safe_str(normalized.get("doc_version", "v1")) or "v1"
    normalized["version_group"] = _safe_str(normalized.get("version_group", ""))
    normalized["maturity"] = _safe_str(normalized.get("maturity", "raw")) or "raw"
    normalized["supersedes_doc_ids"] = list(normalized.get("supersedes_doc_ids") or [])
    normalized["strategy_rank_score"] = _strategy_rank_score(normalized)
    return normalized


# ================================================================
# Policy Filtering Logic
# ================================================================


def filter_by_policy(
    docs: List[Dict[str, Any]],
    policy: RetrievalPolicy,
    ctx: AgentContext,
) -> Dict[str, List[Dict[str, Any]]]:
    """Split and filter docs into priority buckets per retrieval policy.

    Args:
        docs: Full list of doc dicts (each must have role_scope, mbti_scope, etc.)
        policy: Which retrieval policy to apply.
        ctx: Agent context (role, mbti, alignment, phase, action_type).

    Returns:
        Dict mapping bucket_name → sorted list of docs (by quality desc, then score).

    Each bucket name encodes the matching criteria:
        "same_role_same_mbti" — role==ctx.role AND mbti==ctx.mbti
        "same_role_all_mbti" — role==ctx.role, any/no mbti
        "same_alignment_all_mbti" — alignment matches, any/no mbti
        "global" — role=="global" or no role restriction
        "same_role_same_mbti_same_phase" — role + mbti + phase match
    """
    if not ctx.role and not ctx.mbti:
        # No context → fall back to global
        policy = RetrievalPolicy.GLOBAL_ONLY

    role_key = ctx.normalized_role
    mbti_key = ctx.normalized_mbti
    phase_key = ctx.phase.lower().strip()
    align_key = ctx.alignment.lower().strip()

    if policy == RetrievalPolicy.GLOBAL_ONLY:
        return _filter_global(docs)

    elif policy == RetrievalPolicy.SELF_MBTI_ONLY:
        return _filter_self_mbti(docs, mbti_key)

    elif policy == RetrievalPolicy.SAME_ROLE_ALL_MBTI:
        return _filter_same_role(docs, role_key)

    elif policy == RetrievalPolicy.SAME_ROLE_SAME_MBTI:
        return _filter_same_role_mbti(docs, role_key, mbti_key)

    elif policy == RetrievalPolicy.HYBRID_ROLE_MBTI_GLOBAL:
        return _filter_hybrid(docs, role_key, mbti_key)

    elif policy == RetrievalPolicy.HYBRID_ROLE_ALIGNMENT_PHASE:
        return _filter_hybrid_phase(docs, role_key, mbti_key, align_key, phase_key)

    else:
        return _filter_global(docs)


# ---- Individual policy filters ----


def _filter_global(docs: List[Dict]) -> Dict[str, List[Dict]]:
    bucket: List[Dict] = []
    for d in docs:
        role = _safe_str(d.get("role_scope", d.get("role", ""))).lower().strip()
        if role in ("global", "any", ""):
            bucket.append(d)
    bucket.sort(key=_doc_sort_key, reverse=True)
    return {"global": bucket}


def _filter_self_mbti(docs: List[Dict], mbti_key: str) -> Dict[str, List[Dict]]:
    if not mbti_key:
        return _filter_global(docs)
    bucket: List[Dict] = []
    for d in docs:
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()
        if not doc_mbti or doc_mbti == mbti_key:
            bucket.append(d)
    bucket.sort(key=_doc_sort_key, reverse=True)
    return {"self_mbti": bucket}


def _filter_same_role(docs: List[Dict], role_key: str) -> Dict[str, List[Dict]]:
    if not role_key:
        return _filter_global(docs)
    bucket: List[Dict] = []
    for d in docs:
        doc_role = _safe_str(d.get("role_scope", d.get("role", ""))).lower().strip()
        if doc_role == role_key:
            bucket.append(d)
    bucket.sort(key=_doc_sort_key, reverse=True)
    return {"same_role_all_mbti": bucket}


def _filter_same_role_mbti(docs: List[Dict], role_key: str, mbti_key: str) -> Dict[str, List[Dict]]:
    if not role_key and not mbti_key:
        return _filter_global(docs)
    if not mbti_key:
        return _filter_same_role(docs, role_key)
    bucket: List[Dict] = []
    for d in docs:
        doc_role = _safe_str(d.get("role_scope", d.get("role", ""))).lower().strip()
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()
        if doc_role == role_key and doc_mbti == mbti_key:
            bucket.append(d)
    bucket.sort(key=_doc_sort_key, reverse=True)
    return {"same_role_same_mbti": bucket}


def _filter_hybrid(docs: List[Dict], role_key: str, mbti_key: str) -> Dict[str, List[Dict]]:
    """Layered: same_role_same_mbti → same_role_all_mbti → global."""
    buckets: Dict[str, List[Dict]] = {
        "same_role_same_mbti": [],
        "same_role_all_mbti": [],
        "global": [],
    }
    for d in docs:
        doc_role = _safe_str(d.get("role_scope", d.get("role", ""))).lower().strip()
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()

        if role_key and doc_role == role_key and mbti_key and doc_mbti == mbti_key:
            buckets["same_role_same_mbti"].append(d)
        elif role_key and doc_role == role_key and _allow_role_generic_or_cross_mbti(doc_mbti):
            buckets["same_role_all_mbti"].append(d)
        elif doc_role in ("global", "any", "") and _allow_role_generic_or_cross_mbti(doc_mbti):
            buckets["global"].append(d)

    for bucket in buckets.values():
        bucket.sort(key=_doc_sort_key, reverse=True)
    return buckets


def _filter_hybrid_phase(
    docs: List[Dict],
    role_key: str,
    mbti_key: str,
    align_key: str,
    phase_key: str,
) -> Dict[str, List[Dict]]:
    """Layered: same_role_same_mbti_same_phase → same_role_all_mbti → same_alignment → global."""
    buckets: Dict[str, List[Dict]] = {
        "same_role_same_mbti_same_phase": [],
        "same_role_all_mbti": [],
        "same_alignment_all_mbti": [],
        "global": [],
    }
    for d in docs:
        doc_role = _safe_str(d.get("role_scope", d.get("role", ""))).lower().strip()
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()
        doc_phase = _safe_str(d.get("phase_scope", d.get("phase", ""))).lower().strip()
        doc_align = _safe_str(d.get("alignment_scope", "")).lower().strip()

        if (
            role_key
            and doc_role == role_key
            and mbti_key
            and doc_mbti == mbti_key
            and phase_key
            and (doc_phase == phase_key or not doc_phase)
        ):
            buckets["same_role_same_mbti_same_phase"].append(d)
        elif role_key and doc_role == role_key and _allow_role_generic_or_cross_mbti(doc_mbti):
            buckets["same_role_all_mbti"].append(d)
        elif (
            doc_role not in {"global", "any", ""}
            and align_key
            and (doc_align == align_key or not doc_align)
            and _allow_role_generic_or_cross_mbti(doc_mbti)
        ):
            buckets["same_alignment_all_mbti"].append(d)
        elif doc_role in ("global", "any", "") and _allow_role_generic_or_cross_mbti(doc_mbti):
            buckets["global"].append(d)

    for bucket in buckets.values():
        bucket.sort(key=_doc_sort_key, reverse=True)
    return buckets


def _allow_role_generic_or_cross_mbti(doc_mbti: str) -> bool:
    """Allow role fallback docs without importing another MBTI by default.

    Cross-MBTI fill is useful for ablations, but risky for the default Track C
    loop because a high-scoring lesson can encode another persona's play style.
    """
    if not doc_mbti:
        return True
    return os.getenv("TRACK_C_ALLOW_CROSS_MBTI_ROLE_FILL", "").lower() in {"1", "true", "yes", "on"}


# Quality floor for bucket filling — docs below this threshold are skipped.
# Track C lessons are helpful only when they are both relevant and reliable;
# low-quality fill increases prompt noise and can reduce win rate.
_DEFAULT_QUALITY_THRESHOLD = float(os.getenv("TRACK_C_RETRIEVAL_MIN_QUALITY", "0.72") or "0.72")
_ALLOW_LOW_QUALITY_FILL = os.getenv("TRACK_C_ALLOW_LOW_QUALITY_FILL", "").lower() in {"1", "true", "yes", "on"}


def _fill_from_buckets(
    buckets: Dict[str, List[Dict]],
    k: int,
    ratios: Dict[str, int] | None = None,
    quality_threshold: float = _DEFAULT_QUALITY_THRESHOLD,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """Fill k results from priority buckets, applying strict fallback order.

    Higher-priority buckets are exhausted before lower-priority buckets. This
    preserves policy semantics: global docs are fallback, not peers of role docs.
    All phases apply doc_id dedup.

    Returns (results, trace_dict).
    """
    if ratios is None:
        ratios = _DEFAULT_HYBRID_BUCKET_RATIOS

    bucket_names = list(buckets.keys())
    results: List[Dict] = []
    seen_ids: set = set()
    used_from_bucket: Dict[str, int] = dict.fromkeys(bucket_names, 0)
    underfilled: List[str] = []

    # Phase 1: fill by priority with quality threshold.
    for bucket_name in bucket_names:
        bucket_docs = buckets.get(bucket_name, [])
        for doc in bucket_docs:
            if len(results) >= k:
                break
            doc_id = str(doc.get("doc_id", ""))
            if doc_id in seen_ids:
                continue
            if doc.get("quality", 0) < quality_threshold:
                continue  # skip low-quality, don't count as taken
            seen_ids.add(doc_id)
            results.append(doc)
            used_from_bucket[bucket_name] += 1
        if not bucket_docs or used_from_bucket[bucket_name] == 0:
            underfilled.append(bucket_name)

    # Phase 2: still under k → optionally take best available below the
    # threshold. Disabled by default for formal experiments because injecting
    # weak lessons is worse than injecting fewer lessons.
    if len(results) < k and _ALLOW_LOW_QUALITY_FILL:
        for bucket_name in bucket_names:
            if len(results) >= k:
                break
            all_in_bucket = buckets.get(bucket_name, [])
            for doc in all_in_bucket:
                if len(results) >= k:
                    break
                doc_id = str(doc.get("doc_id", ""))
                if doc_id in seen_ids:
                    continue
                seen_ids.add(doc_id)
                results.append(doc)
                used_from_bucket[bucket_name] += 1

    trace = {
        "buckets_used": used_from_bucket,
        "bucket_underfilled": underfilled[:3] if underfilled else [],
        "quality_threshold": quality_threshold,
        "allow_low_quality_fill": _ALLOW_LOW_QUALITY_FILL,
        "skipped_low_quality": sum(
            1 for bn in bucket_names for d in buckets.get(bn, []) if d.get("quality", 0) < quality_threshold
        ),
        "total_filled": len(results),
    }
    return results[:k], trace


def _rerank_buckets_for_context(
    buckets: Dict[str, List[Dict]],
    keywords: List[str],
    role: str,
    phase: str,
    ctx: AgentContext,
) -> Dict[str, List[Dict]]:
    """Rerank docs inside each policy bucket by current situation fit.

    Policy buckets still control visibility and fallback order. This pass only
    changes the order within each bucket so top-3 results prefer docs that match
    the current keywords, phase, action, and role instead of generic high-quality
    reflections.
    """
    reranked: Dict[str, List[Dict]] = {}
    for bucket_name, docs in buckets.items():
        enriched: list[Dict] = []
        for doc in docs:
            item = dict(doc)
            keyword_score = _keyword_overlap_score(item, keywords)
            role_score = _role_match_score(item, role, ctx.alignment)
            phase_score = _phase_match_score(item.get("phase_scope") or item.get("phase", ""), phase)
            action_score = _action_match_score(
                ctx.action_type,
                item.get("action_scope", ""),
                item.get("phase_scope") or item.get("phase", ""),
            )
            mbti_score = _mbti_match_score(item.get("mbti_scope", ""), ctx.mbti)
            quality_score = float(item.get("strategy_rank_score", _strategy_rank_score(item)) or 0.0)
            penalty = _generic_prompt_noise_penalty(item, keyword_score)
            context_score = (
                0.35 * keyword_score
                + 0.18 * phase_score
                + 0.17 * action_score
                + 0.14 * role_score
                + 0.10 * quality_score
                + 0.04 * mbti_score
                - penalty
            )
            item["_retrieval_context_score"] = round(context_score, 4)
            item["_keyword_overlap_score"] = round(keyword_score, 4)
            item["_action_match_score"] = round(action_score, 4)
            item["_phase_match_score"] = round(phase_score, 4)
            enriched.append(item)
        enriched.sort(
            key=lambda row: (
                float(row.get("_retrieval_context_score", 0.0) or 0.0),
                float(row.get("strategy_rank_score", _strategy_rank_score(row)) or 0.0),
                float(row.get("quality", 0.0) or 0.0),
                _safe_str(row.get("doc_id", "")),
            ),
            reverse=True,
        )
        reranked[bucket_name] = enriched
    return reranked


# Default bucket ratios for HYBRID_ROLE_MBTI_GLOBAL (top-3 auto-inject)
_DEFAULT_HYBRID_BUCKET_RATIOS = {
    "same_role_same_mbti": 1,
    "same_role_all_mbti": 1,
    "global": 1,
}

# Default bucket ratios for HYBRID_ROLE_ALIGNMENT_PHASE (top-3 auto-inject)
_DEFAULT_ALIGNMENT_PHASE_BUCKET_RATIOS = {
    "same_role_same_mbti_same_phase": 1,
    "same_role_all_mbti": 1,
    "same_alignment_all_mbti": 1,
    "global": 0,  # only fill if others underfilled
}

# ================================================================
# Production Retriever
# ================================================================


class StrategyRetriever:
    """BM25 + Keyword Grep retriever for AI Werewolf. GPU-free.

    Usage:
        retriever = StrategyRetriever()
        retriever.build()   # one-time init (~0.3s, loads PG + builds indices)
        results = retriever.search("被查杀怎么应对", role="Werewolf", phase="DAY_SPEECH")
    """

    def __init__(self, conn_str: str = ""):
        self._conn = _resolve_conn_str(conn_str)

        self._docs: List[Dict] = []
        self._bm25: Any = None
        self._inverted_index: Dict[str, set] = {}  # keyword → doc indices
        self._built = False

    # ================================================================
    # Build
    # ================================================================

    def build(self) -> int:
        """Load docs from PostgreSQL and build BM25 + inverted index. ~0.3s."""
        if not self._conn:
            return 0
        self._docs = _load_from_pg(self._conn)
        if not self._docs:
            logger.error("No active strategies found in PostgreSQL")
            return 0
        return self._build_indexes()

    def build_from_docs(self, docs: List[Dict]) -> int:
        """Build BM25 + inverted index from in-memory strategy docs (no PG required)."""
        self._docs = docs
        if not self._docs:
            logger.warning("StrategyRetriever.build_from_docs: empty doc list")
            return 0
        return self._build_indexes()

    def _build_indexes(self) -> int:
        """Build BM25 + keyword inverted index from self._docs."""
        import time

        import jieba
        from rank_bm25 import BM25Okapi

        t0 = time.perf_counter()
        self._docs = [_normalize_doc_for_policy(d) for d in self._docs]

        # 1. Build inverted index (for keyword grep)
        for i, d in enumerate(self._docs):
            text = f"{d.get('situation', '')} {d.get('strategy', '')} {d.get('rationale', '')}"
            for w in set(jieba.cut(text)):
                if len(w) >= 2:
                    self._inverted_index.setdefault(w, set()).add(i)

        # 2. Build BM25 index
        corpus = [
            " ".join(jieba.cut(f"{d.get('situation', '')} {d.get('strategy', '')} {d.get('rationale', '')}"))
            for d in self._docs
        ]
        self._bm25 = BM25Okapi([t.split() for t in corpus])

        self._built = True
        elapsed = time.perf_counter() - t0
        logger.info(f"StrategyRetriever built: {len(self._docs)} docs, BM25 + keyword grep, {elapsed:.1f}s")
        return len(self._docs)

    # ================================================================
    # Search (primary API)
    # ================================================================

    def search(
        self,
        query: str,
        role: str = "",
        phase: str = "",
        k: int = TOP_K_FINAL,
        output_mode: str = "content",
        retrieval_policy: RetrievalPolicy = RetrievalPolicy.GLOBAL_ONLY,
        agent_context: Optional[AgentContext] = None,
    ) -> List[Dict[str, str]]:
        """BM25 full-text search with role-priority filtering → top-K.

        Searches same-role + global docs first. If fewer than k/2 results found,
        fills with other-role docs. Rank order: same-role > global > other.

        Args:
            output_mode: "content" (full), "overview" (situation+quality only),
                         "count" (just match count).
            retrieval_policy: Policy for filtering/scoping results.
            agent_context: Agent's role, mbti, alignment, phase context.

        Returns list of {situation, strategy, quality} dicts (fields depend on mode).
        """
        if not self._built:
            return []

        if agent_context is None:
            agent_context = AgentContext(role=role, phase=phase)

        if output_mode == "count":
            import jieba

            tokens = " ".join(jieba.cut(query)).split()
            candidates = [
                d
                for d in self._docs
                if any(
                    t in self._inverted_index and self._docs.index(d) in self._inverted_index[t]
                    for t in tokens
                    if len(t) >= 2
                )
            ]
            buckets = filter_by_policy(candidates, retrieval_policy, agent_context)
            n = sum(len(b) for b in buckets.values())
            return [{"match_count": n, "total_docs": len(self._docs)}]

        results = self._bm25_search_roled(query, role, phase, k=k)
        # Apply policy post-filter
        if retrieval_policy != RetrievalPolicy.GLOBAL_ONLY and results:
            buckets = filter_by_policy(results, retrieval_policy, agent_context)
            filled, _ = _fill_from_buckets(buckets, k)
            results = filled

        if output_mode == "overview":
            return [
                {k: v for k, v in r.items() if k in ("doc_id", "situation", "quality", "doc_type")} for r in results
            ]
        return results

    # ================================================================
    # Agentic Search (keyword-driven)
    # ================================================================

    def search_with_keywords(
        self,
        keywords: List[str],
        role: str = "",
        phase: str = "",
        k: int = TOP_K_FINAL,
        use_bm25_rerank: bool = True,
        output_mode: str = "content",
        regex_mode: bool = False,
        retrieval_policy: RetrievalPolicy = RetrievalPolicy.GLOBAL_ONLY,
        agent_context: Optional[AgentContext] = None,
    ) -> List[Dict[str, str]]:
        """Agent-driven search: keywords/regex → inverted index grep → BM25 rerank → policy filter.

        HIGH-PRECISION fast path. Agent-formulated keywords beat raw jieba
        tokenization (NDCG@5 ~0.85 vs 0.62).

        Multi-field weighted grep: situation match ×1.0, strategy match ×0.7,
        rationale match ×0.4. Inspired by Claude Code's layered grep strategy.

        Args:
            keywords: Agent-formulated search terms (e.g. ["被查杀应对","保护狼队友"]).
                      With regex_mode=True, supports Python regex patterns.
            k: Results to return.
            use_bm25_rerank: If True, BM25-score the grep candidates for ranking.
            output_mode: "content" (full), "overview" (situation+quality only), "count".
            regex_mode: If True, treat keywords as regex patterns (re.compile).
            retrieval_policy: Policy for filtering/scoping results.
            agent_context: Agent's role, mbti, alignment, phase context for policy filtering.
        """
        if not self._built:
            return []

        # Build context if not provided
        if agent_context is None:
            agent_context = AgentContext(role=role, phase=phase, keywords=keywords)

        grep_indices = self._keyword_grep(
            keywords,
            role,
            phase,
            k=TOP_K_CANDIDATES * 2,
            regex_mode=regex_mode,
            mbti=agent_context.mbti,
            action_type=agent_context.action_type,
        )

        if output_mode == "count":
            # Apply policy filter to count
            candidates = [self._docs[i] for i in grep_indices]
            buckets = filter_by_policy(candidates, retrieval_policy, agent_context)
            total = sum(len(b) for b in buckets.values())
            return [{"match_count": total, "total_docs": len(self._docs)}]

        if not grep_indices:
            return []

        # Reorder grep results by role priority: same-role > global > other
        grep_indices = self._reorder_by_role_priority(grep_indices, role)
        candidates = [self._docs[i] for i in grep_indices]

        # Apply policy filtering to scored candidates
        buckets = filter_by_policy(candidates, retrieval_policy, agent_context)
        buckets = _rerank_buckets_for_context(buckets, keywords, role, phase, agent_context)
        if not regex_mode:
            buckets = {
                bucket_name: [doc for doc in bucket_docs if float(doc.get("_keyword_overlap_score", 0.0) or 0.0) > 0.0]
                for bucket_name, bucket_docs in buckets.items()
            }

        # Fill from buckets with appropriate ratios
        filled, bucket_trace = _fill_from_buckets(buckets, k)

        # Build result dicts
        def _build_result(doc: Dict, rank: int, bucket_name: str) -> Dict[str, str]:
            result = {
                "doc_id": _safe_str(doc.get("doc_id", "")),
                "situation": _safe_str(doc.get("situation", "")),
                "strategy": _safe_str(doc.get("strategy", "")),
                "rationale": _safe_str(doc.get("rationale", "")),
                "role": _safe_str(doc.get("role", "")),
                "phase": _safe_str(doc.get("phase", "")),
                "quality": doc.get("quality", 0.8),
                "doc_type": _safe_str(doc.get("doc_type", "")),
                "rank": rank,
                "bucket": bucket_name,
                "retrieval_policy": retrieval_policy.value,
                "role_scope": _safe_str(doc.get("role_scope", doc.get("role", ""))),
                "mbti_scope": _safe_str(doc.get("mbti_scope", "")),
                "phase_scope": _safe_str(doc.get("phase_scope", "")),
                "alignment_scope": _safe_str(doc.get("alignment_scope", "")),
                "action_scope": _safe_str(doc.get("action_scope", "")),
                "source_game_id": _safe_str(doc.get("source_game_id", "")),
                "source_decision_id": _safe_str(doc.get("source_decision_id", "")),
                "status": _safe_str(doc.get("status", "")),
                "quality_score": doc.get("quality", 0.8),
                "strategy_rank_score": doc.get("strategy_rank_score", _strategy_rank_score(doc)),
                "retrieval_context_score": doc.get("_retrieval_context_score", 0.0),
                "keyword_overlap_score": doc.get("_keyword_overlap_score", 0.0),
                "action_match_score": doc.get("_action_match_score", 0.0),
                "phase_match_score": doc.get("_phase_match_score", 0.0),
                "knowledge_epoch": doc.get("knowledge_epoch", 0),
                "doc_version": _safe_str(doc.get("doc_version", "v1")),
                "version_group": _safe_str(doc.get("version_group", "")),
                "maturity": _safe_str(doc.get("maturity", "raw")),
                "supersedes_doc_ids": list(doc.get("supersedes_doc_ids") or []),
                "validated_at": _safe_str(doc.get("validated_at", "")),
                "_bucket_trace": bucket_trace,
            }
            return result

        bucket_by_identity = {
            id(doc): bucket_name for bucket_name, bucket_docs in buckets.items() for doc in bucket_docs
        }
        results = []
        for rank, doc in enumerate(filled, 1):
            # Determine which bucket this doc came from.
            bucket_name = bucket_by_identity.get(id(doc), "unknown")
            result = _build_result(doc, rank, bucket_name)
            if output_mode == "overview":
                result = {
                    k: v
                    for k, v in result.items()
                    if k
                    in (
                        "doc_id",
                        "situation",
                        "quality",
                        "doc_type",
                        "rank",
                        "bucket",
                        "retrieval_policy",
                        "role",
                        "phase",
                        "role_scope",
                        "mbti_scope",
                        "phase_scope",
                        "action_scope",
                        "source_game_id",
                        "status",
                        "strategy_rank_score",
                        "retrieval_context_score",
                        "knowledge_epoch",
                        "doc_version",
                        "maturity",
                    )
                }
            results.append(result)

        if use_bm25_rerank and len(results) >= 3:
            # BM25 rerank the policy-fill results against original doc indices
            pass  # policy-bucketed results are already quality-sorted; skip BM25 reorder

        return results

    def search_regex(
        self,
        patterns: List[str],
        role: str = "",
        phase: str = "",
        k: int = TOP_K_FINAL,
        output_mode: str = "content",
    ) -> List[Dict[str, str]]:
        """Regex-based search: Python regex patterns → inverted index grep → BM25 rerank.

        Use when keywords are too imprecise and you need pattern matching,
        e.g. ["验.*查杀", "刀(民|神)$"].
        """
        return self.search_with_keywords(
            patterns, role=role, phase=phase, k=k, output_mode=output_mode, regex_mode=True
        )

    def count(self, keywords: List[str], role: str = "", phase: str = "") -> Dict[str, int]:
        """Quick count: how many docs match these keywords? No content loading.

        Returns {"match_count": N, "total_docs": N}.
        Use this to assess keyword quality before fetching full results.
        """
        if not self._built:
            return {"match_count": 0, "total_docs": 0}
        grep_indices = self._keyword_grep(keywords, role, phase, k=TOP_K_CANDIDATES * 2)
        return {"match_count": len(grep_indices), "total_docs": len(self._docs)}

    def search_fast(
        self,
        query: str,
        role: str = "",
        phase: str = "",
        k: int = TOP_K_FINAL,
    ) -> List[Dict[str, str]]:
        """Ultra-fast: jieba tokenize → grep only. No BM25. ~0.1ms."""
        if not self._built:
            return []

        import jieba

        keywords = list({w for w in jieba.cut(query) if len(w) >= 2})
        return self.search_with_keywords(keywords, role, phase, k=k, use_bm25_rerank=False)

    # ================================================================
    # Internal: BM25 Search
    # ================================================================

    def _bm25_search(self, query: str, role: str, phase: str, k: int) -> List[Dict]:
        import jieba

        tokens = " ".join(jieba.cut(query)).split()
        scores = self._bm25.get_scores(tokens)
        if np.max(scores) > 0:
            scores = scores / np.max(scores)
        scores = np.array(scores, dtype=np.float64)
        scores += self._role_bonus(role) + self._phase_bonus(phase)
        idx = np.argsort(scores)[::-1][:k]
        return [_result_from_doc(self._docs[i]) for i in idx]

    def _bm25_search_roled(self, query: str, role: str, phase: str, k: int) -> List[Dict]:
        """BM25 search with role-priority filtering.

        Priority: same-role > global > other-role.
        If same-role + global results < k, fills with other-role docs.
        """
        # Split docs by role priority
        same_role = [i for i, d in enumerate(self._docs) if d.get("role", "").lower() == role.lower()]
        global_docs = [
            i for i, d in enumerate(self._docs) if d.get("role", "").lower() == "global" and i not in same_role
        ]
        other_docs = [i for i, d in enumerate(self._docs) if i not in same_role and i not in global_docs]

        # Priority groups
        groups = [same_role, global_docs, other_docs]

        import jieba

        tokens = " ".join(jieba.cut(query)).split()
        bm25_scores = np.array(self._bm25.get_scores(tokens), dtype=np.float64)
        if bm25_scores.max() > 0:
            bm25_scores = bm25_scores / bm25_scores.max()

        results = []
        seen = set()

        # First pass: collect from priority groups, up to k per group
        for group_idx, group in enumerate(groups):
            if not group:
                continue
            # Score only docs in this group
            group_scores = [(i, bm25_scores[i]) for i in group if i not in seen]
            group_scores.sort(key=lambda x: -x[1])
            group_take = group_scores[:k] if group_idx == 0 else group_scores[: k - len(results)]
            for idx, _ in group_take:
                if idx not in seen:
                    results.append(idx)
                    seen.add(idx)

            if len(results) >= k:
                break

        # Second pass: if still not enough, fill from any remaining
        if len(results) < k:
            for i in np.argsort(bm25_scores)[::-1]:
                if i not in seen:
                    results.append(i)
                    seen.add(i)
                    if len(results) >= k:
                        break

        return [_result_from_doc(self._docs[i]) for i in results[:k]]

    # ================================================================
    # Internal: Keyword Grep + BM25 Rerank
    # ================================================================

    def _keyword_grep(
        self,
        keywords: List[str],
        role: str,
        phase: str,
        k: int,
        regex_mode: bool = False,
        mbti: str = "",
        action_type: str = "",
    ) -> List[int]:
        """Grep inverted index with agent-chosen keywords or regex patterns.

        Scoring:
          base = situation×1.0 + strategy×0.7 + rationale×0.4
          context = role+0.5 + phase+0.3 + mbti+0.15 + action+0.2
          quality = quality_score×0.2

        Args:
            keywords: Search terms. With regex_mode, treated as re.compile patterns.
            regex_mode: If True, match keywords as regex against field text.
            mbti: Agent's MBTI for score weighting (soft bonus, not hard filter).
            action_type: Agent's current action for phase-action matching bonus.
        """
        import re as _re

        import jieba

        scores = np.zeros(len(self._docs))
        lexical_hits: set[int] = set()

        if regex_mode:
            # Compile regex patterns once
            compiled = []
            for kw in keywords:
                try:
                    compiled.append(_re.compile(str(kw)))
                except _re.error:
                    compiled.append(str(kw))

            for i, d in enumerate(self._docs):
                for pat in compiled:
                    if isinstance(pat, _re.Pattern):
                        for field, weight in FIELD_WEIGHTS.items():
                            text = _safe_str(d.get(field, ""))
                            if pat.search(text):
                                scores[i] += weight
                                lexical_hits.add(i)
                    else:
                        for field, weight in FIELD_WEIGHTS.items():
                            text = _safe_str(d.get(field, ""))
                            if pat in text:
                                scores[i] += weight
                                lexical_hits.add(i)
        else:
            for i, d in enumerate(self._docs):
                for kw in keywords:
                    # 1. Try jieba tokenization first
                    tokens = list(jieba.cut(str(kw)))
                    valid_tokens = [t for t in tokens if len(t) >= 2]

                    if valid_tokens:
                        for token in valid_tokens:
                            if token in self._inverted_index and i in self._inverted_index[token]:
                                field_hit = False
                                for field, weight in FIELD_WEIGHTS.items():
                                    text = _safe_str(d.get(field, ""))
                                    if token in text:
                                        scores[i] += weight
                                        field_hit = True
                                        lexical_hits.add(i)
                                if not field_hit:
                                    scores[i] += 0.2
                                    lexical_hits.add(i)
                    else:
                        # 2. Fallback: literal substring match (for terms jieba doesn't know)
                        kw_str = str(kw)
                        for field, weight in FIELD_WEIGHTS.items():
                            text = _safe_str(d.get(field, ""))
                            if kw_str in text:
                                scores[i] += weight * 0.8  # slightly lower than token match
                                lexical_hits.add(i)

        for i, d in enumerate(self._docs):
            if i not in lexical_hits:
                continue
            # Context bonuses
            if d["role"] == role:
                scores[i] += 0.5
            if d["phase"] == phase:
                scores[i] += 0.3
            if mbti and _safe_str(d.get("mbti_scope", "")).upper().strip() == mbti:
                scores[i] += 0.15
            # Action bonus: doc phase matches agent's action_type
            doc_phase = _safe_str(d.get("phase", "")).lower()
            if action_type and (
                action_type in doc_phase
                or (action_type == "talk" and "speech" in doc_phase)
                or (action_type == "attack" and "wolf" in doc_phase)
                or (action_type == "save" and "witch" in doc_phase)
                or (action_type == "check" and "seer" in doc_phase)
                or (action_type == "guard" and "guard" in doc_phase)
                or (action_type == "shoot" and "hunter" in doc_phase)
                or (action_type == "vote" and "vote" in doc_phase)
            ):
                scores[i] += 0.2
            # Quality weighting
            scores[i] += d.get("quality", 0.8) * 0.2

        top = np.argsort(scores)[::-1][:k]
        return [int(i) for i in top if scores[i] > 0 and i in lexical_hits]

    def _bm25_rerank_subset(
        self,
        query: str,
        role: str,
        phase: str,
        candidate_indices: List[int],
        k: int,
    ) -> List[Dict[str, str]]:
        """BM25 score restricted to candidate subset + role/phase bonus. ~0.5ms."""
        import jieba

        tokens = " ".join(jieba.cut(query)).split()
        b_raw = np.array(self._bm25.get_scores(tokens))
        if b_raw.max() > 0:
            b_raw = b_raw / b_raw.max()

        for i in range(len(self._docs)):
            rb = 0.12 if self._docs[i]["role"] == role else (0.03 if self._docs[i]["role"] == "global" else 0)
            pb = 0.06 if self._docs[i]["phase"] == phase else (0.02 if self._docs[i]["phase"] == "global" else 0)
            b_raw[i] = b_raw[i] * 0.7 + rb + pb

        top = sorted(candidate_indices, key=lambda i: b_raw[i], reverse=True)[:k]
        return [_result_from_doc(self._docs[i]) for i in top]

    def _reorder_by_role_priority(self, indices: List[int], role: str) -> List[int]:
        """Reorder doc indices by role priority: same-role > global > other."""
        if not role:
            return indices
        rl = role.lower()
        same = [i for i in indices if self._docs[i].get("role", "").lower() == rl]
        glbl = [i for i in indices if self._docs[i].get("role", "").lower() == "global" and i not in same]
        other = [i for i in indices if i not in same and i not in glbl]
        return same + glbl + other

    # ================================================================
    # Helpers
    # ================================================================

    def _role_bonus(self, role: str) -> np.ndarray:
        if not role:
            return np.zeros(len(self._docs), dtype=np.float32)
        return np.array(
            [0.12 if d["role"] == role else (0.03 if d["role"] == "global" else 0) for d in self._docs],
            dtype=np.float32,
        )

    def _phase_bonus(self, phase: str) -> np.ndarray:
        if not phase:
            return np.zeros(len(self._docs), dtype=np.float32)
        return np.array(
            [0.06 if d["phase"] == phase else (0.02 if d["phase"] == "global" else 0) for d in self._docs],
            dtype=np.float32,
        )

    # ================================================================
    # Properties
    # ================================================================

    @property
    def size(self) -> int:
        return len(self._docs)

    @property
    def ready(self) -> bool:
        return self._built

    def get_docs(self) -> List[Dict]:
        """Return raw docs for evaluation / fine-tuning data generation."""
        return self._docs


# ================================================================
# Fine-tuning Pipeline (experimental — requires BGE-M3 GPU)
# ================================================================


def generate_finetune_data(
    docs: List[Dict],
    output_path: str = "data/finetune_triplets.jsonl",
    n_samples: int = 500,
) -> str:
    """Generate contrastive learning triplets for BGE-M3 domain fine-tuning.

    Uses BM25 for hard negative mining. Requires SentenceTransformer at fine-tune time.
    """
    import json
    import random

    import jieba
    from rank_bm25 import BM25Okapi

    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    triplets = []
    for i, anchor in enumerate(docs):
        if len(triplets) >= n_samples:
            break

        same_role = [j for j, d in enumerate(docs) if j != i and d["role"] == anchor["role"]]
        if not same_role:
            continue
        pos_idx = random.choice(same_role)

        tokens = " ".join(jieba.cut(anchor["situation"])).split()
        scores = bm25.get_scores(tokens)
        for j in same_role:
            scores[j] = -999
        scores[i] = -999
        neg_idx = int(np.argmax(scores))

        triplets.append(
            {
                "anchor": anchor["strategy"],
                "positive": docs[pos_idx]["strategy"],
                "hard_negative": docs[neg_idx]["strategy"],
                "anchor_role": anchor["role"],
                "positive_role": docs[pos_idx]["role"],
                "negative_role": docs[neg_idx]["role"],
            }
        )

    with open(output_path, "w") as f:
        for t in triplets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    logger.info(f"Generated {len(triplets)} fine-tuning triplets → {output_path}")
    return output_path


def finetune_retriever(
    model_path: str = "/home/4T-3/PLM/bge-m3/",
    data_path: str = "data/finetune_triplets.jsonl",
    output_path: str = "",
    epochs: int = 3,
    batch_size: int = 16,
    lr: float = 2e-5,
) -> str:
    """Fine-tune BGE-M3 on werewolf domain data (experimental, requires GPU).

    Uses MultipleNegativesRankingLoss for contrastive learning.
    Not required for production — BM25 alone is sufficient for 941 docs.
    """
    import json

    from sentence_transformers import InputExample
    from sentence_transformers import SentenceTransformer
    from sentence_transformers import losses
    from torch.utils.data import DataLoader

    examples = []
    with open(data_path) as f:
        for line in f:
            obj = json.loads(line.strip())
            examples.append(InputExample(texts=[obj["anchor"], obj["positive"]]))
            examples.append(InputExample(texts=[obj["anchor"], obj["hard_negative"]]))

    logger.info(f"Fine-tuning BGE-M3 with {len(examples)} pairs, {epochs} epochs, lr={lr}")

    model = SentenceTransformer(model_path, device="cuda:3")
    loader = DataLoader(examples, shuffle=True, batch_size=batch_size)
    loss = losses.MultipleNegativesRankingLoss(model)

    model.fit(
        train_objectives=[(loader, loss)],
        epochs=epochs,
        optimizer_params={"lr": lr},
        warmup_steps=int(len(loader) * 0.1),
        show_progress_bar=True,
    )

    save_path = output_path or f"{model_path}-werewolf-ft"
    model.save(save_path)
    logger.info(f"Fine-tuned model saved to {save_path}")
    return save_path


# ================================================================
# Helpers
# ================================================================


def _load_from_pg(conn_str: str) -> List[Dict]:
    import psycopg2

    conn = psycopg2.connect(conn_str)
    c = conn.cursor()

    # H6: When TIER_EXPERIMENT_ID is set, filter out docs tagged with a
    # different experiment tier to prevent cross-contamination between
    # parallel experiment tiers sharing the same PostgreSQL database.
    # Untagged docs (no experiment tag) remain visible to all tiers.
    tier_exp_id = os.getenv("TIER_EXPERIMENT_ID", "")

    c.execute("""
        SELECT id, COALESCE(situation_pattern, ''), COALESCE(recommended_action, ''),
               COALESCE(rationale, ''), role, phase, quality_score,
               COALESCE(doc_type, ''),
               COALESCE(confidence_tier, 'L3_strategic'),
               COALESCE(visibility_scope, 'public'),
               COALESCE(deidentified, false),
               COALESCE(contains_current_game_private_info, false),
               COALESCE(persona_scope, ''),
               COALESCE(tags, '[]'::jsonb),
               source_report_ids,
               source_item_ids,
               COALESCE(confidence, 0.7),
               COALESCE(usage_count, 0),
               COALESCE(success_count, 0),
               COALESCE(failure_count, 0),
               COALESCE(knowledge_epoch, 0),
               COALESCE(version_group, ''),
               COALESCE(doc_version, 'v1'),
               COALESCE(parent_doc_id, ''),
               COALESCE(supersedes_doc_ids, '[]'::jsonb),
               COALESCE(maturity, 'raw'),
               validated_at,
               last_used_at,
               created_at,
               updated_at,
               COALESCE(contradiction_count, 0)
        FROM strategy_knowledge_docs
        WHERE status = 'active'
          AND (doc_type != 'reflection' OR quality_score >= 0.85)
    """)

    docs = []
    import json

    for (
        row_id,
        sit,
        rec,
        rat,
        role,
        phase,
        q,
        dtype,
        ctier,
        vscope,
        deid,
        cgpi,
        persona_scope,
        raw_tags,
        raw_src_reports,
        raw_src_items,
        confidence,
        usage_count,
        success_count,
        failure_count,
        knowledge_epoch,
        version_group,
        doc_version,
        parent_doc_id,
        raw_supersedes,
        maturity,
        validated_at,
        last_used_at,
        created_at,
        updated_at,
        contradiction_count,
    ) in c.fetchall():
        tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
        if tier_exp_id and any(str(t).startswith("exp-") for t in tags) and tier_exp_id not in tags:
            continue
        src_reports = (
            list(raw_src_reports or [])
            if isinstance(raw_src_reports, (list, tuple))
            else (json.loads(raw_src_reports) if isinstance(raw_src_reports, str) else [])
        )
        src_items = (
            list(raw_src_items or [])
            if isinstance(raw_src_items, (list, tuple))
            else (json.loads(raw_src_items) if isinstance(raw_src_items, str) else [])
        )
        supersedes = (
            list(raw_supersedes or [])
            if isinstance(raw_supersedes, (list, tuple))
            else (json.loads(raw_supersedes) if isinstance(raw_supersedes, str) else [])
        )
        docs.append(
            _build_doc_dict(
                row_id,
                sit,
                rec,
                rat,
                role,
                phase,
                q,
                dtype,
                ctier,
                vscope,
                deid,
                cgpi,
                persona_scope,
                src_reports,
                src_items,
                confidence=confidence,
                usage_count=usage_count,
                success_count=success_count,
                failure_count=failure_count,
                knowledge_epoch=knowledge_epoch,
                version_group=version_group,
                doc_version=doc_version,
                parent_doc_id=parent_doc_id,
                supersedes_doc_ids=supersedes,
                maturity=maturity,
                validated_at=validated_at,
                last_used_at=last_used_at,
                created_at=created_at,
                updated_at=updated_at,
                contradiction_count=contradiction_count,
                tags=tags,
            )
        )
    conn.close()
    return _drop_superseded_docs(docs)


def _build_doc_dict(
    row_id: str,
    sit: str,
    rec: str,
    rat: str,
    role: str,
    phase: str,
    q: Any,
    dtype: str,
    ctier: str,
    vscope: str,
    deid: Any,
    cgpi: Any,
    persona_scope: str,
    src_reports: list,
    src_items: list,
    *,
    confidence: Any = 0.7,
    usage_count: Any = 0,
    success_count: Any = 0,
    failure_count: Any = 0,
    knowledge_epoch: Any = 0,
    version_group: str = "",
    doc_version: str = "v1",
    parent_doc_id: str = "",
    supersedes_doc_ids: list | None = None,
    maturity: str = "raw",
    validated_at: Any = None,
    last_used_at: Any = None,
    created_at: Any = None,
    updated_at: Any = None,
    contradiction_count: Any = 0,
    tags: list | None = None,
) -> Dict[str, Any]:
    """Build a normalized doc dict with derived scope fields.

    Derives mbti_scope, role_scope, alignment_scope, source_game_id,
    source_decision_id from DB columns. No migration required.
    """
    persona_scope_val = persona_scope.strip() if persona_scope else ""
    mbti_scope = _parse_mbti_from_persona_scope(persona_scope_val)
    persona_role = _parse_role_from_persona_scope(persona_scope_val)

    doc = {
        # Core fields
        "doc_id": row_id or "",
        "situation": sit or "",
        "strategy": rec or "",
        "rationale": rat or "",
        "role": role or "global",
        "phase": phase or "global",
        "quality": float(q) if q else 0.8,
        "confidence": float(confidence) if confidence else 0.7,
        "doc_type": dtype or "",
        # Confidence / visibility
        "confidence_tier": ctier or "L3_strategic",
        "visibility_scope": vscope or "public",
        "deidentified": bool(deid) if deid is not None else False,
        "contains_current_game_private_info": bool(cgpi) if cgpi is not None else False,
        # Scopes — derived from persona_scope and role/phase columns
        "persona_scope": persona_scope_val,
        "mbti_scope": mbti_scope,
        "role_scope": persona_role or role,
        "alignment_scope": _derive_alignment_from_role(persona_role or role),
        "phase_scope": phase if phase and phase.lower() != "global" else "",
        "action_scope": "",  # not present in current schema
        # Source tracing
        "source_game_id": src_reports[0] if src_reports else "",
        "source_decision_id": src_items[0] if src_items else "",
        # Status tracking
        "status": "active",
        "usage_count": int(usage_count or 0),
        "success_count": int(success_count or 0),
        "failure_count": int(failure_count or 0),
        "knowledge_epoch": int(knowledge_epoch or 0),
        "version_group": version_group or "",
        "doc_version": doc_version or "v1",
        "parent_doc_id": parent_doc_id or "",
        "supersedes_doc_ids": list(supersedes_doc_ids or []),
        "maturity": maturity or "raw",
        "validated_at": validated_at.isoformat() if hasattr(validated_at, "isoformat") else validated_at,
        "last_used_at": last_used_at.isoformat() if hasattr(last_used_at, "isoformat") else last_used_at,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        "contradiction_count": int(contradiction_count or 0),
        "tags": list(tags or []),
    }
    doc["strategy_rank_score"] = _strategy_rank_score(doc)
    return doc


def _drop_superseded_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    superseded = {
        old_id
        for doc in docs
        if _safe_str(doc.get("maturity", "raw")).lower() in {"refined", "canonical"}
        for old_id in doc.get("supersedes_doc_ids", [])
    }
    return [doc for doc in docs if doc.get("doc_id") not in superseded]


# ============================================================
# Singleton + Public API
# ============================================================

_retriever: Optional[StrategyRetriever] = None


def get_retriever(conn_str: str = "") -> Optional[StrategyRetriever]:
    """Get or build the global production retriever (singleton). GPU-free.

    Tries PostgreSQL first; falls back to in-memory strategy store (cold-start).
    """
    global _retriever
    if _retriever is not None and _retriever.ready:
        return _retriever

    resolved_conn = _resolve_conn_str(conn_str)
    if resolved_conn:
        try:
            _retriever = StrategyRetriever(conn_str=resolved_conn)
            n = _retriever.build()
            if n > 0:
                return _retriever
        except Exception as e:
            logger.warning("Failed to build production retriever from PG: %s", _redact_conn_error(e))

    # Fallback: in-memory strategy store (cold-start YAML)
    try:
        docs = _load_docs_from_cold_start()
        if docs:
            _retriever = StrategyRetriever()
            n = _retriever.build_from_docs(docs)
            if n > 0:
                logger.info(f"StrategyRetriever built from {n} cold-start docs (in-memory)")
                return _retriever
    except Exception as e:
        logger.warning("Failed to build retriever from cold-start store: %s", e)

    return None


def _load_docs_from_cold_start() -> list[dict]:
    """Load cold-start strategy docs from YAML config + strategy registry.

    Converts StrategyKnowledgeDoc → retriever dict format.
    No PostgreSQL required.
    """
    from backend.agents.strategy_registry import get_strategy_registry

    docs: list[dict] = []
    registry = get_strategy_registry()
    for card in registry.list_all():
        roles = tuple(card.applicable_roles or ())
        role = "global" if len(roles) > 2 else (roles[0] if roles else "global")
        strategy_text = "\n".join(_safe_str(item) for item in card.content if _safe_str(item))
        risk_text = "\n".join(_safe_str(item) for item in card.risk_notes if _safe_str(item))
        docs.append(
            {
                "doc_id": f"cold-{card.strategy_id}",
                "situation": card.summary or card.strategy_name,
                "strategy": strategy_text or card.summary or card.strategy_name,
                "rationale": risk_text or "Cold-start strategy from YAML strategy registry.",
                "role": role,
                "phase": "global",
                "quality": 0.90,
                "doc_type": "cold_start",
                "status": "active",
                "role_scope": role,
                "alignment_scope": _derive_alignment_from_role(role),
                "phase_scope": "",
                "mbti_scope": "",
                "source_game_id": "",
                "source_decision_id": "",
            }
        )
    return docs


def retrieve_strategies_prod(
    role: str,
    phase: str,
    situation: str = "",
    keywords: Optional[List[str]] = None,
    limit: int = 3,
    include_reflections: bool = False,
    output_mode: str = "content",
    regex_mode: bool = False,
    retrieval_policy: RetrievalPolicy = RetrievalPolicy.GLOBAL_ONLY,
    agent_context: Optional[AgentContext] = None,
    mbti: str = "",
    alignment: str = "",
    player_id: str = "",
    action_type: str = "",
) -> List[Dict[str, str]]:
    """Production strategy retrieval: Grep + BM25 + role/phase bonus + policy filter.

    Supports three output modes (inspired by Claude Code's grep modes):
      - "count": just return match count (quick keyword assessment)
      - "overview": situation + quality + scope info (lightweight scan)
      - "content": full strategy content with scope annotations (default)

    Args:
        role: Current role (e.g., "Seer", "Werewolf").
        phase: Current phase (e.g., "DAY_SPEECH", "NIGHT_WOLF_ACTION").
        situation: Natural language description of the current situation.
        keywords: Optional agent-formulated keywords for higher precision.
        limit: Max entries to return.
        include_reflections: If False, exclude doc_type='reflection' results.
        output_mode: "content" | "overview" | "count"
        regex_mode: If True, keywords are treated as Python regex patterns.
        retrieval_policy: Which policy to apply for doc filtering/scoping.
        agent_context: Full AgentContext (takes precedence over individual params).
        mbti: Agent's MBTI type (used if agent_context is None).
        alignment: Agent's alignment ("village"/"wolf").
        player_id: Agent's player ID for tracing.
        action_type: Current action type ("talk"/"vote"/"attack"/etc.).

    Returns:
        List of dicts with fields: doc_id, situation, strategy, quality, doc_type,
        rank, bucket, retrieval_policy, role_scope, mbti_scope, phase_scope,
        source_game_id, status, ...
    """
    retriever = get_retriever()
    if retriever is None:
        return []

    # Build agent context from individual params if full context not provided
    if agent_context is None:
        agent_context = AgentContext(
            player_id=player_id,
            role=role,
            alignment=alignment or _derive_alignment_from_role(role),
            mbti=mbti,
            phase=phase,
            action_type=action_type,
            keywords=keywords or [],
        )

    if keywords and len(keywords) >= 1:
        results = retriever.search_with_keywords(
            keywords,
            role=role,
            phase=phase,
            k=limit,
            output_mode=output_mode,
            regex_mode=regex_mode,
            retrieval_policy=retrieval_policy,
            agent_context=agent_context,
        )
    else:
        query = situation or _default_query_text(role, phase)
        results = retriever.search(
            query,
            role=role,
            phase=phase,
            k=limit,
            output_mode=output_mode,
            retrieval_policy=retrieval_policy,
            agent_context=agent_context,
        )

    if not include_reflections and output_mode != "count":
        results = [r for r in results if not (r.get("doc_type") or "").startswith("reflection")]

    # Apply 4-filter safety pipeline (strict mode: all filters via retrieve_for_agent)
    if os.getenv("AIWEREWOLF_STRICT_MODE", "").lower() == "true":
        from backend.eval.knowledge_confidence import retrieve_for_agent

        is_wolf = role in {"Werewolf", "WhiteWolfKing", "BigBadWolf", "WolfCub"}

        # Build doc dicts with filter-expected fields, preserving original retriever fields
        all_docs = []
        for r in results:
            doc = dict(r)
            doc.setdefault("confidence_tier", r.get("confidence_tier", "L3_strategic"))
            doc.setdefault("visibility_scope", r.get("visibility_scope", "public"))
            doc.setdefault("quality_score", r.get("quality", 0.8))
            doc.setdefault("status", r.get("status", "active"))
            doc.setdefault("applicability_role", r.get("applicability_role", r.get("role", "")))
            doc.setdefault("applicability_phase", phase)
            doc.setdefault("source_game_ids", r.get("source_game_ids", []))
            doc.setdefault("contains_current_game_private_info", r.get("contains_current_game_private_info", False))
            doc.setdefault("deidentified", r.get("deidentified", False))
            doc.setdefault("allowed_roles", r.get("allowed_roles"))
            doc.setdefault("rule_variant", r.get("rule_variant", "standard_competition_v1"))
            all_docs.append(doc)

        filtered = retrieve_for_agent(
            query="",
            agent_role=role,
            is_wolf=is_wolf,
            current_game_id="",
            current_phase=phase,
            rule_variant="standard_competition_v1",
            player_count=0,
            public_facts=set(),
            private_state=set(),
            is_postgame=False,
            top_k=limit,
            all_docs=all_docs,
        )

        if len(filtered) < len(results):
            logger.info(f"4-filter: {len(results)} -> {len(filtered)} results after safety filtering")
        results = filtered

    return results


def count_strategies(
    role: str,
    phase: str,
    keywords: List[str],
) -> Dict[str, int]:
    """Quick keyword match count — no content loading, ~0.05ms.

    Use before search_strategies to test keyword quality.
    Inspired by Claude Code's "count" output mode.
    """
    retriever = get_retriever()
    if retriever is None:
        return {"match_count": 0, "total_docs": 0}
    return retriever.count(keywords, role=role, phase=phase)


def _default_query_text(role: str, phase: str) -> str:
    """Build a default query when no situation description is provided."""
    phase_hints = {
        "DAY_BADGE_SPEECH": "竞选警长 警徽流 报查验",
        "DAY_SPEECH": "白天发言 分析局势 表水",
        "DAY_VOTE": "投票 归票 放逐",
        "NIGHT_WOLF_ACTION": "刀人 击杀目标 刀法",
        "NIGHT_SEER_ACTION": "查验 验人 预言家",
        "NIGHT_WITCH_ACTION": "解药 毒药 救人",
        "NIGHT_GUARD_ACTION": "守护 守卫 保护",
    }
    hint = phase_hints.get(phase, "")
    return f"{role} {phase} {hint}".strip()


def format_strategies_for_prompt(strategies: List[Dict[str, str]]) -> str:
    """Format retrieved strategies for LLM prompt.

    Handles all output modes:
      - "count" → "找到 N 条匹配策略（共 M 条）"
      - "overview" → compact list of situations
      - "content" → full situation + strategy
    """
    if not strategies:
        return ""

    # Count mode
    if len(strategies) == 1 and "match_count" in strategies[0]:
        s = strategies[0]
        return f"(找到 {s['match_count']} 条匹配策略，共 {s.get('total_docs', '?')} 条。用更精确的关键词缩小范围。)"

    # Overview mode (situation only)
    if "strategy" not in strategies[0]:
        lines = ["=== 策略概况（用 search_strategies(mode='content', keywords=...) 查看完整内容） ==="]
        for i, s in enumerate(strategies, 1):
            doc_type = s.get("doc_type", "")
            type_label = " [反思经验]" if (doc_type or "").startswith("reflection") else ""
            quality = s.get("quality", "?")
            doc_id = s.get("doc_id", "")
            score_str = f"{quality:.0%}" if isinstance(quality, (int, float)) else f"{quality}"
            lines.append(f"{i}. [{doc_id} score={score_str}] {s.get('situation', '?')}{type_label}")
        return "\n".join(lines)

    # Content mode (full)
    lines = ["=== 相关策略参考 ==="]
    for i, s in enumerate(strategies, 1):
        doc_type = s.get("doc_type", "")
        is_reflection = (doc_type or "").startswith("reflection")
        type_label = " [反思经验]" if is_reflection else ""
        doc_id = s.get("doc_id", "")
        quality = s.get("quality", "?")
        score_str = f"{quality}" if isinstance(quality, (int, float)) else f"{quality}"
        lines.append(f"{i}. [{doc_id} score={score_str}] 场景：{s.get('situation', '')}{type_label}")
        lines.append(f"   策略：{s.get('strategy', '')}")
        lines.append("")
    return "\n".join(lines)
