"""
Production Strategy Retrieval — BM25 + BGE-M3 Dense RRF.

Winner of 8-method comparison (NDCG@5=0.723, MRR=0.734, 70ms).
Data source: PostgreSQL → memory cache.

Architecture:
  Stage 1: BM25 + BGE-M3 Dense RRF → top-K candidates (high recall)
  Stage 2 (opt): BGE-M3 ColBERT rerank (high precision, +28ms)

Fine-tuning: see finetune_retriever() for domain adaptation via contrastive learning.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
_DEFAULT_MODEL = "/home/4T-3/PLM/bge-m3/"
_DEFAULT_GPU = "cuda:3"

# ---- Constants ----
RRF_K = 60
TOP_K_CANDIDATES = 20
TOP_K_FINAL = 5


# ============================================================
# Production Retriever
# ============================================================

class StrategyRetriever:
    """BM25 + BGE-M3 Dense RRF retriever for AI Werewolf.

    Usage:
        retriever = StrategyRetriever()
        retriever.build()   # one-time init (loads from PostgreSQL, builds indices)
        results = retriever.search("我被查杀了怎么应对", role="Werewolf", phase="DAY_SPEECH")
    """

    def __init__(
        self,
        model_path: str = "",
        device: str = "",
        conn_str: str = "",
        enable_rerank: bool = False,
    ):
        self._mp = model_path or os.environ.get("BGE_MODEL_PATH", _DEFAULT_MODEL)
        self._dev = device or os.environ.get("BGE_DEVICE", _DEFAULT_GPU)
        self._conn = conn_str or _DEFAULT_CONN
        self._rerank = enable_rerank

        self._docs: List[Dict] = []
        self._bm25: Any = None
        self._bge_dense: Optional[np.ndarray] = None  # (N, 1024)
        self._bge_model: Any = None
        self._bge_sparse: List[Dict] = []
        self._bge_colbert: List[np.ndarray] = []
        self._built = False

    # ================================================================
    # Build
    # ================================================================

    def build(self) -> int:
        """Load docs from PostgreSQL and build all indices. One-time cost ~5s."""
        import time
        from rank_bm25 import BM25Okapi
        from FlagEmbedding import BGEM3FlagModel
        import jieba

        t0 = time.perf_counter()

        # 1. Load from PostgreSQL
        self._docs = _load_from_pg(self._conn)
        if not self._docs:
            logger.error("No active strategies found in PostgreSQL")
            return 0
        logger.info(f"Loaded {len(self._docs)} docs from PostgreSQL")

        # 2. Build BM25 index
        corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}"))
                  for d in self._docs]
        self._bm25 = BM25Okapi([t.split() for t in corpus])

        # 3. Build BGE-M3 indices
        self._bge_model = BGEM3FlagModel(self._mp, use_fp16=True, device=self._dev)
        doc_texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in self._docs]
        N = len(self._docs)

        self._bge_dense = np.zeros((N, 1024), dtype=np.float32)
        bs = 64
        for i in range(0, N, bs):
            batch = doc_texts[i:i+bs]
            out = self._bge_model.encode(batch, return_dense=True, return_sparse=True,
                                         return_colbert_vecs=True)
            self._bge_dense[i:i+len(batch)] = out['dense_vecs']
            self._bge_sparse.extend(out['lexical_weights'])
            self._bge_colbert.extend(out['colbert_vecs'])

        # Normalize dense
        norms = np.linalg.norm(self._bge_dense, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self._bge_dense /= norms

        self._built = True
        elapsed = time.perf_counter() - t0
        logger.info(f"StrategyRetriever built: {N} docs, "
                     f"BM25 + Dense({self._bge_dense.shape[1]}d) + "
                     f"Sparse({len(self._bge_sparse)}) + ColBERT({len(self._bge_colbert)}), "
                     f"{elapsed:.1f}s")
        return N

    # ================================================================
    # Search (primary API)
    # ================================================================

    def search(
        self,
        query: str,
        role: str = "",
        phase: str = "",
        k: int = TOP_K_FINAL,
        use_rerank: Optional[bool] = None,
    ) -> List[Dict[str, str]]:
        """Main search: BM25 + BGE Dense RRF → top-k.

        Args:
            query: Natural language query (game situation description).
            role: Current agent role (e.g., "Seer", "Werewolf").
            phase: Current game phase (e.g., "DAY_SPEECH", "NIGHT_WOLF_ACTION").
            k: Number of results to return.
            use_rerank: Override ColBERT rerank setting.

        Returns:
            List of {situation, strategy, quality} dicts.
        """
        if not self._built:
            return []

        do_rerank = use_rerank if use_rerank is not None else self._rerank

        # Stage 1: BM25 top-K
        bm25_results = self._bm25_search(query, role, phase, k=TOP_K_CANDIDATES)
        # Stage 1: Dense top-K
        dense_results = self._dense_search(query, role, phase, k=TOP_K_CANDIDATES)
        # RRF fusion
        candidates = self._rrf_fuse(bm25_results, dense_results, k=TOP_K_CANDIDATES)

        # Stage 2 (opt): ColBERT rerank
        if do_rerank:
            candidates = self._colbert_rerank(query, candidates, k=k)

        return candidates[:k]

    # ================================================================
    # Internal: BM25
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
        return [{"idx": int(i), "bm25_score": float(scores[i]),
                 "situation": self._docs[i]["situation"],
                 "strategy": self._docs[i]["strategy"],
                 "quality": self._docs[i]["quality"]} for i in idx]

    # ================================================================
    # Internal: BGE Dense
    # ================================================================

    def _dense_search(self, query: str, role: str, phase: str, k: int) -> List[Dict]:
        qv = self._bge_model.encode(query, return_dense=True)['dense_vecs']
        qv = np.asarray(qv, dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = np.dot(self._bge_dense, qv)
        scores = sims + self._role_bonus(role) + self._phase_bonus(phase)
        idx = np.argsort(scores)[::-1][:k]
        return [{"idx": int(i), "dense_score": float(sims[i]),
                 "situation": self._docs[i]["situation"],
                 "strategy": self._docs[i]["strategy"],
                 "quality": self._docs[i]["quality"]} for i in idx]

    # ================================================================
    # Internal: RRF Fusion
    # ================================================================

    def _rrf_fuse(self, list_a: List, list_b: List, k: int) -> List[Dict]:
        scores: Dict[int, float] = {}
        for rank, r in enumerate(list_a, 1):
            scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0 / (RRF_K + rank)
        for rank, r in enumerate(list_b, 1):
            scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0 / (RRF_K + rank)
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return [{"idx": i, "rrf_score": s,
                 "situation": self._docs[i]["situation"],
                 "strategy": self._docs[i]["strategy"],
                 "quality": self._docs[i]["quality"]} for i, s in top]

    # ================================================================
    # Internal: ColBERT Rerank (optional stage 2)
    # ================================================================

    def _colbert_rerank(self, query: str, candidates: List[Dict], k: int) -> List[Dict]:
        out = self._bge_model.encode(query, return_colbert_vecs=True)
        qc = np.asarray(out['colbert_vecs'], dtype=np.float32)
        qc /= np.linalg.norm(qc, axis=1, keepdims=True) + 1e-8

        scores = np.zeros(len(candidates))
        for j, c in enumerate(candidates):
            dc = np.asarray(self._bge_colbert[c["idx"]], dtype=np.float32)
            dc /= np.linalg.norm(dc, axis=1, keepdims=True) + 1e-8
            sim = np.dot(qc, dc.T)
            scores[j] = np.sum(np.max(sim, axis=1))

        top = np.argsort(scores)[::-1][:k]
        return [{"situation": candidates[i]["situation"],
                 "strategy": candidates[i]["strategy"],
                 "quality": candidates[i]["quality"]} for i in top]

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
        """Return raw docs for fine-tuning data generation."""
        return self._docs


# ================================================================
# Fine-tuning Pipeline
# ================================================================

def generate_finetune_data(
    docs: List[Dict],
    output_path: str = "data/finetune_triplets.jsonl",
    n_samples: int = 500,
) -> str:
    """Generate contrastive learning triplets for domain fine-tuning.

    Positive: same role + related phase (different doc)
    Hard negative: different role, similar phase, retrieved by BM25
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

        # Positive: same role, different doc
        same_role = [j for j, d in enumerate(docs) if j != i and d["role"] == anchor["role"]]
        if not same_role:
            continue
        pos_idx = random.choice(same_role)

        # Hard negative: BM25 retrieval with anchor situation as query
        tokens = " ".join(jieba.cut(anchor["situation"])).split()
        scores = bm25.get_scores(tokens)
        # Exclude same-role docs from negatives
        for j in same_role:
            scores[j] = -999
        scores[i] = -999  # exclude self
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
    model_path: str = _DEFAULT_MODEL,
    data_path: str = "data/finetune_triplets.jsonl",
    output_path: str = "",
    epochs: int = 3,
    batch_size: int = 16,
    lr: float = 2e-5,
) -> str:
    """Fine-tune BGE-M3 on werewolf domain data.

    Uses MultipleNegativesRankingLoss for contrastive learning.
    After fine-tuning, the model encodes domain-specific semantics better.
    """
    import json
    from torch.utils.data import DataLoader
    from sentence_transformers import InputExample, SentenceTransformer, losses

    # Load training data
    examples = []
    with open(data_path) as f:
        for line in f:
            obj = json.loads(line.strip())
            examples.append(InputExample(texts=[obj["anchor"], obj["positive"]]))
            examples.append(InputExample(texts=[obj["anchor"], obj["hard_negative"]]))

    logger.info(f"Fine-tuning BGE-M3 with {len(examples)} pairs, {epochs} epochs, lr={lr}")

    model = SentenceTransformer(model_path, device=_DEFAULT_GPU)
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
