"""Strategy retrieval — semantic search for relevant strategies.

Single Responsibility: find the most relevant strategy entries
for a given game situation from the PostgreSQL knowledge base.

Method: TF-IDF vector semantic search with role/phase scoring bonuses.
Data source: PostgreSQL (strategy_knowledge_docs table).
Fallback: SQL metadata matching if vector index unavailable.
"""

from __future__ import annotations

import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_CONN = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"


# ============================================================
# Strategy Index (TF-IDF over PostgreSQL data)
# ============================================================


class StrategyIndex:
    """TF-IDF vector index over strategy documents loaded from PostgreSQL.

    Built once at agent initialization. Provides semantic search
    against the full text of all active strategies.
    """

    def __init__(self, conn_str: str = ""):
        self._conn_str = conn_str or _DEFAULT_CONN
        self._docs: List[Dict[str, Any]] = []
        self._doc_texts: List[str] = []
        self._doc_vectors: Any = None  # scipy sparse matrix
        self._vectorizer: Any = None
        self._built = False

    # ---- Build ----

    def build(self) -> int:
        """Load all active strategies from PostgreSQL and build TF-IDF index."""
        self._docs = _load_docs_from_pg(self._conn_str)
        if not self._docs:
            logger.warning("StrategyIndex: no active strategies found in DB")
            return 0
        return self._build_tfidf()

    def build_from_docs(self, docs: List[Dict[str, Any]]) -> int:
        """Build TF-IDF index from in-memory strategy docs (no PG required)."""
        self._docs = docs
        if not self._docs:
            logger.warning("StrategyIndex.build_from_docs: empty doc list")
            return 0
        return self._build_tfidf()

    def _build_tfidf(self) -> int:
        """Build TF-IDF vector index from self._docs."""
        import jieba
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._doc_texts = []
        for d in self._docs:
            text = f"{d.get('situation', '')} {d.get('recommended', '')} {d.get('rationale', '')}"
            self._doc_texts.append(" ".join(jieba.cut(text)))

        self._vectorizer = TfidfVectorizer(max_features=3000, ngram_range=(1, 2))
        self._doc_vectors = self._vectorizer.fit_transform(self._doc_texts)
        self._built = True
        logger.info(f"StrategyIndex built: {len(self._docs)} docs, {self._doc_vectors.shape[1]} features")
        return len(self._docs)

    # ---- Search ----

    def search(
        self,
        query: str,
        role: str = "",
        phase: str = "",
        limit: int = 5,
        persona_mbti: str = "",
        persona_style: str = "",
    ) -> List[Dict[str, str]]:
        """Semantic search with TF-IDF cosine similarity + persona/role/phase bonuses.

        Scoring formula:
            score = vector_sim * 0.5 + persona_match * 0.2
                  + role_match * 0.15 + quality * 0.15

        Retrieval priority (three-tier):
            1. Exact persona_scope match ("mbti:INTJ+role:Werewolf")
            2. Partial persona match ("mbti:INTJ")
            3. Global knowledge (no persona_scope)

        Args:
            query: Natural language query describing the situation.
            role: Current role for relevance bonus.
            phase: Current phase for relevance bonus.
            limit: Max results to return.
            persona_mbti: Agent's MBTI type for persona-scoped retrieval.
            persona_style: Agent's style label for further filtering.

        Returns:
            List of {situation, strategy, quality, persona_scope} dicts.
        """
        if not self._built:
            return _fallback_sql(role, phase, limit, self._conn_str, persona_mbti)

        import jieba
        from sklearn.metrics.pairwise import cosine_similarity

        # Vectorize query
        tokenized = " ".join(jieba.cut(query))
        q_vec = self._vectorizer.transform([tokenized])
        sims = cosine_similarity(q_vec, self._doc_vectors)[0]

        # Persona match bonus (three-tier priority)
        persona_exact = f"mbti:{persona_mbti}+role:{role}" if persona_mbti and role else ""
        persona_partial = f"mbti:{persona_mbti}" if persona_mbti else ""

        persona_bonus = np.array(
            [
                0.20
                if persona_exact and d.get("persona_scope") == persona_exact
                else (
                    0.15
                    if persona_partial and d.get("persona_scope") == persona_partial
                    else (0.05 if d.get("persona_scope") and d.get("role") == role else 0)
                )
                for d in self._docs
            ]
        )

        # Role/phase bonuses
        role_bonus = np.array(
            [0.15 if d.get("role") == role else (0.05 if d.get("role") == "global" else 0) for d in self._docs]
        )
        phase_bonus = np.array(
            [0.08 if d.get("phase") == phase else (0.03 if d.get("phase") == "global" else 0) for d in self._docs]
        )
        quality_bonus = np.array([d.get("quality", 0.8) * 0.10 for d in self._docs])

        # Weighted scoring
        scores = sims * 0.50 + persona_bonus + role_bonus * 0.70 + phase_bonus * 0.70 + quality_bonus
        top_n = int(min(limit, len(self._docs)))
        top_idx = np.argsort(scores)[::-1][:top_n]

        results = []
        for i in top_idx:
            d = self._docs[i]
            results.append(
                {
                    "situation": d.get("situation", ""),
                    "strategy": d.get("recommended", ""),
                    "quality": d.get("quality", 0.8),
                    "persona_scope": d.get("persona_scope", ""),
                    "doc_type": d.get("doc_type", ""),
                }
            )
        return results

    # ---- Properties ----

    @property
    def size(self) -> int:
        return len(self._docs)

    @property
    def ready(self) -> bool:
        return self._built


# ============================================================
# Singleton
# ============================================================

_index: Optional[StrategyIndex] = None


def get_index(conn_str: str = "") -> StrategyIndex:
    """Get or build the global strategy index (singleton).

    Tries PostgreSQL first; falls back to in-memory cold-start strategy store.
    """
    global _index
    if _index is None or not _index.ready:
        _index = StrategyIndex(conn_str)
        n = _index.build()
        if n == 0:
            # Try in-memory cold-start store
            try:
                from backend.agents.cognitive.retrieval_prod import _load_docs_from_cold_start

                docs = _load_docs_from_cold_start()
                if docs:
                    # Convert to retrieval.py's expected format
                    formatted = [
                        {
                            "situation": d["situation"],
                            "recommended": d["strategy"],
                            "rationale": d["rationale"],
                            "role": d["role"],
                            "phase": d["phase"],
                            "quality": d["quality"],
                        }
                        for d in docs
                    ]
                    n = _index.build_from_docs(formatted)
                    if n > 0:
                        logger.info(f"StrategyIndex built from {n} cold-start docs (in-memory)")
            except Exception:
                logger.warning("StrategyIndex is empty — retrieval will fall back to SQL")
    return _index


def rebuild_index(conn_str: str = "") -> int:
    """Force rebuild the global index (e.g., after DB updates)."""
    global _index
    _index = StrategyIndex(conn_str)
    return _index.build()


# ============================================================
# Public API (used by cognitive agent pipeline)
# ============================================================


def retrieve_strategies(
    role: str,
    phase: str,
    situation: str = "",
    limit: int = 3,
    conn_str: str = "",
    persona_mbti: str = "",
    persona_style: str = "",
    include_reflections: bool = True,
) -> List[Dict[str, str]]:
    """Retrieve relevant strategies for a game situation.

    Uses TF-IDF vector semantic search as primary method,
    with PostgreSQL metadata matching as fallback.

    Supports persona-scoped retrieval: when persona_mbti is provided,
    strategies matching that MBTI type get priority bonuses (three-tier:
    exact match > partial match > global knowledge).

    Args:
        role: Current role (e.g., "Seer", "Werewolf").
        phase: Current phase (e.g., "DAY_SPEECH", "NIGHT_ACTION").
        situation: Natural language description of the current situation.
        limit: Max entries to return.
        persona_mbti: Agent's MBTI for persona-scoped retrieval.
        persona_style: Agent's style label for further filtering.
        include_reflections: If False, exclude doc_type='reflection' results.

    Returns:
        List of {situation, strategy, quality, persona_scope, doc_type} dicts.
    """
    try:
        idx = get_index(conn_str)
        if idx.ready:
            query = situation or _default_query(role, phase)
            results = idx.search(
                query,
                role=role,
                phase=phase,
                limit=limit,
                persona_mbti=persona_mbti,
                persona_style=persona_style,
            )
            if not include_reflections:
                results = [r for r in results if not r.get("doc_type", "").startswith("reflection")]
            return results
    except Exception as e:
        logger.warning(f"Vector retrieval failed, falling back to SQL: {e}")

    results = _fallback_sql(role, phase, limit, conn_str, persona_mbti)
    if not include_reflections:
        results = [r for r in results if not r.get("doc_type", "").startswith("reflection")]
    return results


def format_strategies_for_prompt(strategies: List[Dict[str, str]]) -> str:
    """Format retrieved strategies into prompt text."""
    if not strategies:
        return ""

    lines = ["=== 相关策略参考 ==="]
    for i, s in enumerate(strategies, 1):
        persona_tag = f" [{s['persona_scope']}]" if s.get("persona_scope") else ""
        doc_type = s.get("doc_type", "")
        type_label = " [反思经验]" if doc_type == "reflection" else ""
        lines.append(f"{i}. 场景：{s['situation']}{persona_tag}{type_label}")
        lines.append(f"   策略：{s['strategy']}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# Internal helpers
# ============================================================


def _load_docs_from_pg(conn_str: str) -> List[Dict[str, Any]]:
    """Load all active strategy documents from PostgreSQL (now includes persona_scope + experiment_id filter for tier isolation)."""
    import os as _os

    import psycopg2

    conn = psycopg2.connect(conn_str)
    c = conn.cursor()
    exp_id = _os.getenv("TIER_EXPERIMENT_ID", "")
    if exp_id:
        c.execute(
            """
            SELECT COALESCE(situation_pattern, ''),
                   COALESCE(recommended_action, ''),
                   COALESCE(rationale, ''),
                   role, phase, quality_score,
                   COALESCE(persona_scope, ''),
                   COALESCE(doc_type, '')
            FROM strategy_knowledge_docs
            WHERE status = 'active'
              AND (doc_type != 'reflection' OR quality_score >= 0.85)
              AND (experiment_id = %s OR experiment_id IS NULL)
        """,
            (exp_id,),
        )
    else:
        c.execute("""
            SELECT COALESCE(situation_pattern, ''),
                   COALESCE(recommended_action, ''),
                   COALESCE(rationale, ''),
                   role, phase, quality_score,
                   COALESCE(persona_scope, ''),
                   COALESCE(doc_type, '')
            FROM strategy_knowledge_docs
            WHERE status = 'active'
              AND (doc_type != 'reflection' OR quality_score >= 0.85)
        """)
    docs = []
    for sit, rec, rat, role, phase, q, pscope, dtype in c.fetchall():
        docs.append(
            {
                "situation": sit or "",
                "recommended": rec or "",
                "rationale": rat or "",
                "role": role or "global",
                "phase": phase or "global",
                "quality": float(q) if q else 0.8,
                "persona_scope": pscope or "",
                "doc_type": dtype or "",
            }
        )
    conn.close()
    return docs


def _default_query(role: str, phase: str) -> str:
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


def _fallback_sql(role: str, phase: str, limit: int, conn_str: str, persona_mbti: str = "") -> List[Dict[str, str]]:
    """Fallback: SQL metadata matching when vector index is unavailable.

    Now includes persona_scope prioritization for MBTI-specific knowledge.
    """
    try:
        import psycopg2

        conn = psycopg2.connect(conn_str or _DEFAULT_CONN)
        c = conn.cursor()

        persona_pattern = f"%mbti:{persona_mbti}%" if persona_mbti else ""

        if persona_pattern:
            c.execute(
                """
                SELECT situation_pattern, recommended_action, quality_score,
                       COALESCE(persona_scope, '') as persona_scope,
                       COALESCE(doc_type, '') as doc_type
                FROM strategy_knowledge_docs
                WHERE status = 'active'
                  AND (role = %s OR role = 'global')
                  AND (phase = %s OR phase = 'global')
                ORDER BY (
                    quality_score
                    + CASE WHEN persona_scope LIKE %s THEN 0.20 ELSE 0 END
                    + CASE WHEN role != 'global' THEN 0.15 ELSE 0 END
                    + CASE WHEN phase != 'global' THEN 0.08 ELSE 0 END
                ) * (0.9 + RANDOM() * 0.2) DESC
                LIMIT %s
            """,
                (role, phase, persona_pattern, limit),
            )
        else:
            c.execute(
                """
                SELECT situation_pattern, recommended_action, quality_score,
                       COALESCE(persona_scope, '') as persona_scope,
                       COALESCE(doc_type, '') as doc_type
                FROM strategy_knowledge_docs
                WHERE status = 'active'
                  AND (role = %s OR role = 'global')
                  AND (phase = %s OR phase = 'global')
                ORDER BY (
                    quality_score
                    + CASE WHEN role != 'global' THEN 0.15 ELSE 0 END
                    + CASE WHEN phase != 'global' THEN 0.08 ELSE 0 END
                ) * (0.9 + RANDOM() * 0.2) DESC
                LIMIT %s
            """,
                (role, phase, limit),
            )
        results = []
        for row in c.fetchall():
            sit, rec, q = row[0], row[1], row[2]
            pscope = row[3] if len(row) > 3 else ""
            dtype = row[4] if len(row) > 4 else ""
            results.append(
                {
                    "situation": sit or "",
                    "strategy": rec or "",
                    "quality": float(q) if q else 0.8,
                    "persona_scope": pscope or "",
                    "doc_type": dtype or "",
                }
            )
        conn.close()
        return results
    except Exception:
        return []
