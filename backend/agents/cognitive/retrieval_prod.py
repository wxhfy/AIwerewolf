"""
Production Strategy Retrieval — BM25 + Keyword Grep + Role/Phase Bonus.

GPU-free. Data source: PostgreSQL → in-memory indices.
Build time ~0.3s for 941 docs. Query latency <1ms.

Architecture:
  Fast path: Agent keywords → inverted index grep → BM25 rerank subset (NDCG~0.85)
  Standard:  BM25 full-text + role/phase bonus → top-K
  Ultra-fast: jieba tokenize → grep only (no BM25, ~0.1ms)

Simplicity over complexity. Amazon 2025: "Keyword Search Is All You Need."
KRAFTON PUBG Ally: BM25-only for game agent knowledge retrieval.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"

TOP_K_CANDIDATES = 20
TOP_K_FINAL = 5


# ============================================================
# Production Retriever
# ============================================================

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
        import time
        from rank_bm25 import BM25Okapi
        import jieba

        t0 = time.perf_counter()

        # 1. Load from PostgreSQL
        self._docs = _load_from_pg(self._conn)
        if not self._docs:
            logger.error("No active strategies found in PostgreSQL")
            return 0

        # 2. Build inverted index (for keyword grep)
        for i, d in enumerate(self._docs):
            text = f"{d['situation']} {d['strategy']} {d['rationale']}"
            for w in set(jieba.cut(text)):
                if len(w) >= 2:
                    self._inverted_index.setdefault(w, set()).add(i)

        # 3. Build BM25 index
        corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}"))
                  for d in self._docs]
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
    ) -> List[Dict[str, str]]:
        """BM25 full-text search + role/phase bonus → top-K.

        Returns list of {situation, strategy, quality} dicts.
        """
        if not self._built:
            return []

        return self._bm25_search(query, role, phase, k=k)

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
    ) -> List[Dict[str, str]]:
        """Agent-driven search: Agent keywords → inverted index grep → BM25 rerank.

        HIGH-PRECISION fast path. Agent-formulated keywords beat raw jieba
        tokenization (NDCG@5 ~0.85 vs 0.62).

        Args:
            keywords: Agent-formulated search terms (e.g. ["被查杀应对","保护狼队友"])
            k: Results to return.
            use_bm25_rerank: If True, BM25-score the grep candidates for ranking.
                             If False, return raw grep results (ultra-fast ~0.1ms).
        """
        if not self._built:
            return []

        grep_indices = self._keyword_grep(keywords, role, phase, k=TOP_K_CANDIDATES * 2)

        if len(grep_indices) < 3:
            return self.search(" ".join(keywords), role, phase, k=k)

        if not use_bm25_rerank:
            return [{"situation": self._docs[i]["situation"],
                     "strategy": self._docs[i]["strategy"],
                     "quality": self._docs[i]["quality"]} for i in grep_indices[:k]]

        return self._bm25_rerank_subset(" ".join(keywords), role, phase, grep_indices, k=k)

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
        keywords = list(set([w for w in jieba.cut(query) if len(w) >= 2]))
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
        return [{"situation": self._docs[i]["situation"],
                 "strategy": self._docs[i]["strategy"],
                 "quality": self._docs[i]["quality"]} for i in idx]

    # ================================================================
    # Internal: Keyword Grep + BM25 Rerank
    # ================================================================

    def _keyword_grep(self, keywords: List[str], role: str, phase: str, k: int) -> List[int]:
        """Grep inverted index with agent-chosen keywords."""
        import jieba
        scores = np.zeros(len(self._docs))

        for kw in keywords:
            for token in jieba.cut(str(kw)):
                if len(token) >= 2 and token in self._inverted_index:
                    for idx in self._inverted_index[token]:
                        scores[idx] += 1

        for i, d in enumerate(self._docs):
            if d["role"] == role: scores[i] += 0.5
            if d["phase"] == phase: scores[i] += 0.3

        top = np.argsort(scores)[::-1][:k]
        return [int(i) for i in top if scores[i] > 0]

    def _bm25_rerank_subset(
        self, query: str, role: str, phase: str,
        candidate_indices: List[int], k: int,
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
        return [{"situation": self._docs[i]["situation"],
                 "strategy": self._docs[i]["strategy"],
                 "quality": self._docs[i]["quality"]} for i in top]

    # ================================================================
    # Helpers
    # ================================================================

    def _role_bonus(self, role: str) -> np.ndarray:
        if not role:
            return np.zeros(len(self._docs), dtype=np.float32)
        return np.array([0.12 if d["role"] == role else
                        (0.03 if d["role"] == "global" else 0)
                        for d in self._docs], dtype=np.float32)

    def _phase_bonus(self, phase: str) -> np.ndarray:
        if not phase:
            return np.zeros(len(self._docs), dtype=np.float32)
        return np.array([0.06 if d["phase"] == phase else
                        (0.02 if d["phase"] == "global" else 0)
                        for d in self._docs], dtype=np.float32)

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
    import json, random
    from rank_bm25 import BM25Okapi
    import jieba

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

        triplets.append({
            "anchor": anchor["strategy"],
            "positive": docs[pos_idx]["strategy"],
            "hard_negative": docs[neg_idx]["strategy"],
            "anchor_role": anchor["role"],
            "positive_role": docs[pos_idx]["role"],
            "negative_role": docs[neg_idx]["role"],
        })

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
    from torch.utils.data import DataLoader
    from sentence_transformers import InputExample, SentenceTransformer, losses

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
    c.execute("""
        SELECT COALESCE(situation_pattern, ''), COALESCE(recommended_action, ''),
               COALESCE(rationale, ''), role, phase, quality_score
        FROM strategy_knowledge_docs WHERE status = 'active'
    """)
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append({
            "situation": sit or "", "strategy": rec or "", "rationale": rat or "",
            "role": role or "global", "phase": phase or "global",
            "quality": float(q) if q else 0.8,
        })
    conn.close()
    return docs


# ============================================================
# Singleton + Public API
# ============================================================

_retriever: Optional[StrategyRetriever] = None


def get_retriever(conn_str: str = "") -> Optional[StrategyRetriever]:
    """Get or build the global production retriever (singleton). GPU-free.

    Returns None only if PostgreSQL is unreachable.
    """
    global _retriever
    if _retriever is not None and _retriever.ready:
        return _retriever

    try:
        _retriever = StrategyRetriever(conn_str=conn_str)
        n = _retriever.build()
        if n == 0:
            logger.warning("Production retriever built but no docs loaded")
            return None
        return _retriever
    except Exception as e:
        logger.warning(f"Failed to build production retriever: {e}")
        return None


def retrieve_strategies_prod(
    role: str,
    phase: str,
    situation: str = "",
    keywords: Optional[List[str]] = None,
    limit: int = 3,
) -> List[Dict[str, str]]:
    """Production strategy retrieval: BM25 + keyword grep + role/phase bonus.

    Args:
        role: Current role (e.g., "Seer", "Werewolf").
        phase: Current phase (e.g., "DAY_SPEECH", "NIGHT_WOLF_ACTION").
        situation: Natural language description of the current situation.
        keywords: Optional agent-formulated keywords for higher precision.
        limit: Max entries to return.

    Returns:
        List of {situation, strategy, quality} dicts.
    """
    retriever = get_retriever()
    if retriever is None:
        return []

    if keywords and len(keywords) >= 2:
        return retriever.search_with_keywords(keywords, role=role, phase=phase, k=limit)

    query = situation or _default_query_text(role, phase)
    return retriever.search(query, role=role, phase=phase, k=limit)


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
    """Format retrieved strategies for LLM prompt."""
    if not strategies:
        return ""
    lines = ["=== 相关策略参考 ==="]
    for i, s in enumerate(strategies, 1):
        lines.append(f"{i}. 场景：{s.get('situation', '')}")
        lines.append(f"   策略：{s.get('strategy', '')}")
        lines.append("")
    return "\n".join(lines)
