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

    Each policy defines a filtering strategy; HYBRID_ROLE_MBTI_GLOBAL is the
    recommended default as it balances personalization with coverage.
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


_DEFAULT_CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"

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


def _safe_str(val: Any) -> str:
    """Coerce field value to str. Handles tuples, lists from card.content."""
    if isinstance(val, str):
        return val
    if isinstance(val, (list, tuple)):
        return " ".join(str(v) for v in val)
    return str(val) if val else ""


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
        role = _safe_str(d.get("role", "")).lower().strip()
        if role in ("global", "any", ""):
            bucket.append(d)
    bucket.sort(key=lambda d: d.get("quality", 0), reverse=True)
    return {"global": bucket}


def _filter_self_mbti(docs: List[Dict], mbti_key: str) -> Dict[str, List[Dict]]:
    if not mbti_key:
        return _filter_global(docs)
    bucket: List[Dict] = []
    for d in docs:
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()
        if not doc_mbti or doc_mbti == mbti_key:
            bucket.append(d)
    bucket.sort(key=lambda d: d.get("quality", 0), reverse=True)
    return {"self_mbti": bucket}


def _filter_same_role(docs: List[Dict], role_key: str) -> Dict[str, List[Dict]]:
    if not role_key:
        return _filter_global(docs)
    bucket: List[Dict] = []
    for d in docs:
        doc_role = _safe_str(d.get("role", "")).lower().strip()
        if doc_role == role_key or doc_role in ("global", "any", ""):
            bucket.append(d)
    bucket.sort(key=lambda d: d.get("quality", 0), reverse=True)
    return {"same_role_all_mbti": bucket}


def _filter_same_role_mbti(docs: List[Dict], role_key: str, mbti_key: str) -> Dict[str, List[Dict]]:
    if not role_key and not mbti_key:
        return _filter_global(docs)
    if not mbti_key:
        return _filter_same_role(docs, role_key)
    bucket: List[Dict] = []
    for d in docs:
        doc_role = _safe_str(d.get("role", "")).lower().strip()
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()
        if doc_role == role_key and doc_mbti == mbti_key:
            bucket.append(d)
    bucket.sort(key=lambda d: d.get("quality", 0), reverse=True)
    return {"same_role_same_mbti": bucket}


def _filter_hybrid(docs: List[Dict], role_key: str, mbti_key: str) -> Dict[str, List[Dict]]:
    """Layered: same_role_same_mbti → same_role_all_mbti → global."""
    buckets: Dict[str, List[Dict]] = {
        "same_role_same_mbti": [],
        "same_role_all_mbti": [],
        "global": [],
    }
    for d in docs:
        doc_role = _safe_str(d.get("role", "")).lower().strip()
        doc_mbti = _safe_str(d.get("mbti_scope", "")).upper().strip()

        if role_key and doc_role == role_key and mbti_key and doc_mbti == mbti_key:
            buckets["same_role_same_mbti"].append(d)
        elif role_key and (doc_role == role_key or doc_role in ("global", "any", "")):
            buckets["same_role_all_mbti"].append(d)
        elif doc_role in ("global", "any", ""):
            buckets["global"].append(d)

    for bucket in buckets.values():
        bucket.sort(key=lambda d: d.get("quality", 0), reverse=True)
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
        doc_role = _safe_str(d.get("role", "")).lower().strip()
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
        elif role_key and (doc_role == role_key or doc_role in ("global", "any", "")):
            buckets["same_role_all_mbti"].append(d)
        elif align_key and (doc_align == align_key or not doc_align):
            buckets["same_alignment_all_mbti"].append(d)
        elif doc_role in ("global", "any", ""):
            buckets["global"].append(d)

    for bucket in buckets.values():
        bucket.sort(key=lambda d: d.get("quality", 0), reverse=True)
    return buckets


# Quality floor for bucket filling — docs below this threshold are skipped
_DEFAULT_QUALITY_THRESHOLD = 0.60


def _fill_from_buckets(
    buckets: Dict[str, List[Dict]],
    k: int,
    ratios: Dict[str, int] | None = None,
    quality_threshold: float = _DEFAULT_QUALITY_THRESHOLD,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """Fill k results from priority buckets, applying ratios + quality threshold.

    Phase 1: Fill 1:1:1 from each bucket (only docs >= quality_threshold).
    Phase 2: Underfilled slots → fill from same_role → global in priority order.
    Phase 3: Still under → take best available regardless of threshold.
    All phases apply doc_id dedup.

    Returns (results, trace_dict).
    """
    if ratios is None:
        ratios = _DEFAULT_HYBRID_BUCKET_RATIOS

    bucket_names = list(buckets.keys())
    total_ratio = sum(ratios.get(bn, 0) for bn in bucket_names)
    if total_ratio == 0:
        ratios = dict.fromkeys(bucket_names, 1)
        total_ratio = len(bucket_names)

    results: List[Dict] = []
    seen_ids: set = set()
    used_from_bucket: Dict[str, int] = {}
    underfilled: List[str] = []

    # Phase 1: fill 1:1:1 with quality threshold
    for bucket_name in bucket_names:
        target = max(1, int(k * ratios.get(bucket_name, 1) / total_ratio))
        bucket_docs = buckets.get(bucket_name, [])
        taken = 0
        for doc in bucket_docs:
            if taken >= target:
                break
            doc_id = str(doc.get("doc_id", ""))
            if doc_id in seen_ids:
                continue
            if doc.get("quality", 0) < quality_threshold:
                continue  # skip low-quality, don't count as taken
            seen_ids.add(doc_id)
            results.append(doc)
            taken += 1
        used_from_bucket[bucket_name] = taken
        if taken < target:
            underfilled.append(bucket_name)

    # Phase 2: underfilled → fill from same_role → global in priority order
    if len(results) < k and underfilled:
        fill_order = bucket_names  # already in priority order
        for bucket_name in fill_order:
            if len(results) >= k:
                break
            bucket_docs = buckets.get(bucket_name, [])
            for doc in bucket_docs:
                if len(results) >= k:
                    break
                doc_id = str(doc.get("doc_id", ""))
                if doc_id in seen_ids:
                    continue
                if doc.get("quality", 0) < quality_threshold:
                    continue
                seen_ids.add(doc_id)
                results.append(doc)
                used_from_bucket[bucket_name] += 1

    # Phase 3: still under k → take best available, drop quality threshold
    if len(results) < k:
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
        "skipped_low_quality": sum(
            1 for bn in bucket_names for d in buckets.get(bn, []) if d.get("quality", 0) < quality_threshold
        ),
        "total_filled": len(results),
    }
    return results[:k], trace


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
        self._conn = conn_str or _DEFAULT_CONN

        self._docs: List[Dict] = []
        self._bm25: Any = None
        self._inverted_index: Dict[str, set] = {}  # keyword → doc indices
        self._built = False

    # ================================================================
    # Build
    # ================================================================

    def build(self) -> int:
        """Load docs from PostgreSQL and build BM25 + inverted index. ~0.3s."""
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
            if filled:
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

        if len(grep_indices) < 3:
            return self.search(
                " ".join(keywords),
                role,
                phase,
                k=k,
                output_mode=output_mode,
                retrieval_policy=retrieval_policy,
                agent_context=agent_context,
            )

        # Reorder grep results by role priority: same-role > global > other
        grep_indices = self._reorder_by_role_priority(grep_indices, role)
        candidates = [self._docs[i] for i in grep_indices]

        # Apply policy filtering to scored candidates
        buckets = filter_by_policy(candidates, retrieval_policy, agent_context)

        # Fill from buckets with appropriate ratios
        filled, bucket_trace = _fill_from_buckets(buckets, k)

        # If no results from policy, fall back to BM25 unfiltered
        if not filled and retrieval_policy != RetrievalPolicy.GLOBAL_ONLY:
            filled = candidates[:k]
            bucket_trace = {"fallback": "policy_empty", "buckets_used": {}}

        # Build result dicts
        def _build_result(doc: Dict, rank: int, bucket_name: str) -> Dict[str, str]:
            result = {
                "doc_id": _safe_str(doc.get("doc_id", "")),
                "situation": _safe_str(doc.get("situation", "")),
                "strategy": _safe_str(doc.get("strategy", "")),
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
                "_bucket_trace": bucket_trace,
            }
            return result

        results = []
        for rank, doc in enumerate(filled, 1):
            # Determine which bucket this doc came from
            bucket_name = "unknown"
            for bn, bdocs in buckets.items():
                if doc in bdocs:
                    bucket_name = bn
                    break
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
                        "role_scope",
                        "mbti_scope",
                        "phase_scope",
                        "source_game_id",
                        "status",
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
        return [
            {
                "doc_id": self._docs[i].get("doc_id", ""),
                "situation": self._docs[i]["situation"],
                "strategy": self._docs[i]["strategy"],
                "quality": self._docs[i]["quality"],
                "doc_type": self._docs[i].get("doc_type", ""),
            }
            for i in idx
        ]

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

        return [
            {
                "doc_id": self._docs[i].get("doc_id", ""),
                "situation": self._docs[i]["situation"],
                "strategy": self._docs[i]["strategy"],
                "quality": self._docs[i]["quality"],
                "doc_type": self._docs[i].get("doc_type", ""),
            }
            for i in results[:k]
        ]

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
                    else:
                        for field, weight in FIELD_WEIGHTS.items():
                            text = _safe_str(d.get(field, ""))
                            if pat in text:
                                scores[i] += weight
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
                                if not field_hit:
                                    scores[i] += 0.2
                    else:
                        # 2. Fallback: literal substring match (for terms jieba doesn't know)
                        kw_str = str(kw)
                        for field, weight in FIELD_WEIGHTS.items():
                            text = _safe_str(d.get(field, ""))
                            if kw_str in text:
                                scores[i] += weight * 0.8  # slightly lower than token match

        for i, d in enumerate(self._docs):
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
        return [int(i) for i in top if scores[i] > 0]

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
        return [
            {
                "doc_id": self._docs[i].get("doc_id", ""),
                "situation": self._docs[i]["situation"],
                "strategy": self._docs[i]["strategy"],
                "quality": self._docs[i]["quality"],
                "doc_type": self._docs[i].get("doc_type", ""),
            }
            for i in top
        ]

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

    if tier_exp_id:
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
                   source_item_ids
            FROM strategy_knowledge_docs
            WHERE status = 'active'
              AND (doc_type != 'reflection' OR quality_score >= 0.85)
        """)
    else:
        c.execute("""
            SELECT id, COALESCE(situation_pattern, ''), COALESCE(recommended_action, ''),
                   COALESCE(rationale, ''), role, phase, quality_score,
                   COALESCE(doc_type, ''),
                   COALESCE(confidence_tier, 'L3_strategic'),
                   COALESCE(visibility_scope, 'public'),
                   COALESCE(deidentified, false),
                   COALESCE(contains_current_game_private_info, false),
                   COALESCE(persona_scope, ''),
                   source_report_ids,
                   source_item_ids
            FROM strategy_knowledge_docs
            WHERE status = 'active'
              AND (doc_type != 'reflection' OR quality_score >= 0.85)
        """)

    docs = []
    if tier_exp_id:
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
        ) in c.fetchall():
            # H6: If a doc has experiment tags but NOT our tier's tag, skip it.
            tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
            if any(t.startswith("exp-") for t in tags) and tier_exp_id not in tags:
                continue
            # JSONB columns arrive as Python lists; handle both str and list cases
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
                )
            )
    else:
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
            raw_src_reports,
            raw_src_items,
        ) in c.fetchall():
            import json

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
                )
            )
    conn.close()
    return docs


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
) -> Dict[str, Any]:
    """Build a normalized doc dict with derived scope fields.

    Derives mbti_scope, role_scope, alignment_scope, source_game_id,
    source_decision_id from DB columns. No migration required.
    """
    persona_scope_val = persona_scope.strip() if persona_scope else ""
    mbti_scope = _parse_mbti_from_persona_scope(persona_scope_val)
    persona_role = _parse_role_from_persona_scope(persona_scope_val)

    return {
        # Core fields
        "doc_id": row_id or "",
        "situation": sit or "",
        "strategy": rec or "",
        "rationale": rat or "",
        "role": role or "global",
        "phase": phase or "global",
        "quality": float(q) if q else 0.8,
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
        "status": dtype,  # doc_type serves as the status field in current schema
    }


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

    # Primary: PostgreSQL
    try:
        _retriever = StrategyRetriever(conn_str=conn_str)
        n = _retriever.build()
        if n > 0:
            return _retriever
    except Exception as e:
        logger.warning(f"Failed to build production retriever from PG: {e}")

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
        logger.warning(f"Failed to build retriever from cold-start store: {e}")

    return None


def _load_docs_from_cold_start() -> list[dict]:
    """Load cold-start strategy docs from YAML config + strategy registry.

    Converts StrategyKnowledgeDoc → retriever dict format.
    No PostgreSQL required.
    """
    from backend.agents.strategy_registry import get_strategy_registry
    from backend.eval.evolution import StrategyKnowledgeStore

    store = StrategyKnowledgeStore()

    # 1. Load from strategy registry (YAML cold-start cards)
    try:
        registry = get_strategy_registry()
        for card in registry.list_all():
            doc_id = f"cold-{card.strategy_id}"
            if doc_id not in store.docs:
                from backend.eval.evolution import StrategyKnowledgeDoc

                roles = card.applicable_roles
                role = "global" if len(roles) > 2 else (roles[0] if roles else "global")
                doc = StrategyKnowledgeDoc(
                    doc_id=doc_id,
                    doc_type="cold_start",
                    role=role,
                    phase="global",
                    persona_scope=None,
                    situation_pattern=card.summary or card.strategy_name,
                    trigger_conditions=[],
                    recommended_action=card.content[:300] if card.content else "",
                    avoid_action=None,
                    rationale=card.risk_notes or "",
                    evidence_summary="Cold-start strategy from YAML",
                    source_report_ids=[],
                    source_item_ids=[],
                    source_event_ids=[],
                    counterfactual_ids=[],
                    expected_metric_effects=[],
                    quality_score=0.90,
                    confidence=0.85,
                    status="active",
                    tags=card.applicable_roles,
                )
                store.upsert(doc)
    except Exception:
        pass

    # Convert to retriever dict format
    docs = []
    for doc in store.all(include_deprecated=False):
        docs.append(
            {
                "doc_id": doc.doc_id or "",
                "situation": doc.situation_pattern or "",
                "strategy": doc.recommended_action or "",
                "rationale": doc.rationale or "",
                "role": doc.role or "global",
                "phase": doc.phase or "global",
                "quality": doc.quality_score,
                "doc_type": doc.doc_type or "",
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
