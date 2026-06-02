"""DEPRECATED: BGE-M3 embedding-based strategy retrieval.

Superseded by retrieval_prod.py (BM25 + keyword grep, GPU-free).
Kept for reference / evaluation scripts that import BGEM3FlagModel.
Do not use for production — the GPU overhead is unnecessary for 941 docs.

Data source: PostgreSQL (strategy_knowledge_docs) → BGE-M3 embeddings → cosine search.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
_DEFAULT_MODEL_PATH = "/home/4T-3/PLM/bge-m3/"
_DEFAULT_DEVICE = "cuda:3"


class BGERetriever:
    """BGE-M3 embedding-based strategy retriever.

    Usage:
        retriever = BGERetriever()
        retriever.build()  # one-time: load model + encode all docs
        results = retriever.search("狼人被查杀怎么应对", role="Werewolf", phase="DAY_SPEECH")
    """

    def __init__(
        self,
        model_path: str = "",
        device: str = "",
        conn_str: str = "",
    ):
        self._model_path = model_path or os.environ.get("BGE_MODEL_PATH", _DEFAULT_MODEL_PATH)
        self._device = device or os.environ.get("BGE_DEVICE", _DEFAULT_DEVICE)
        self._conn_str = conn_str or _DEFAULT_CONN

        self._model: Any = None
        self._docs: List[Dict[str, Any]] = []
        self._embeddings: Optional[np.ndarray] = None  # (N, 1024)
        self._built = False

    # ---- Build ----

    def build(self) -> int:
        """Load model + encode all strategy docs from PostgreSQL.

        Returns number of documents indexed.
        """
        import torch
        from sentence_transformers import SentenceTransformer

        # 1. Load model
        logger.info(f"Loading BGE-M3 from {self._model_path} on {self._device}...")
        self._model = SentenceTransformer(self._model_path, device=self._device)
        dim = self._model.get_sentence_embedding_dimension()
        logger.info(f"  Model loaded, embedding dim={dim}")

        # 2. Load docs from PostgreSQL
        self._docs = _load_docs_from_pg(self._conn_str)
        if not self._docs:
            logger.warning("No active strategies found in PostgreSQL")
            return 0

        # 3. Encode all doc texts
        doc_texts = [
            f"{d.get('situation', '')} {d.get('recommended', '')} {d.get('rationale', '')}"
            for d in self._docs
        ]
        logger.info(f"  Encoding {len(doc_texts)} docs...")
        self._embeddings = self._model.encode(
            doc_texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        )
        self._embeddings = np.asarray(self._embeddings, dtype=np.float32)
        self._built = True

        logger.info(f"BGE Retriever built: {len(self._docs)} docs, "
                     f"{self._embeddings.shape[1]} dim, "
                     f"{self._embeddings.nbytes / 1024**2:.1f} MB embeddings")
        return len(self._docs)

    # ---- Search ----

    def search(
        self,
        query: str,
        role: str = "",
        phase: str = "",
        limit: int = 5,
    ) -> List[Dict[str, str]]:
        """Semantic search with BGE-M3 embeddings + role/phase bonuses.

        Args:
            query: Natural language query.
            role: Current role for relevance bonus.
            phase: Current phase for relevance bonus.
            limit: Max results.

        Returns:
            List of {situation, strategy, quality} dicts.
        """
        if not self._built:
            return []

        # Encode query
        q_emb = self._model.encode(query, normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype=np.float32)

        # Cosine similarity (embeddings are already normalized)
        sims = np.dot(self._embeddings, q_emb)  # (N,)

        # Role/phase bonuses (same weight as TF-IDF version for fair comparison)
        role_bonus = np.array([
            0.15 if d.get("role") == role else (0.05 if d.get("role") == "global" else 0)
            for d in self._docs
        ], dtype=np.float32)
        phase_bonus = np.array([
            0.08 if d.get("phase") == phase else (0.03 if d.get("phase") == "global" else 0)
            for d in self._docs
        ], dtype=np.float32)
        quality_bonus = np.array([d.get("quality", 0.8) * 0.1 for d in self._docs], dtype=np.float32)

        scores = sims + role_bonus + phase_bonus + quality_bonus
        top_n = min(limit, len(self._docs))
        top_idx = np.argsort(scores)[::-1][:top_n]

        results = []
        for i in top_idx:
            d = self._docs[i]
            results.append({
                "situation": d.get("situation", ""),
                "strategy": d.get("recommended", ""),
                "quality": d.get("quality", 0.8),
                "similarity": float(sims[i]),
            })
        return results

    # ---- Fine-tuning ----

    def prepare_finetune_data(self, output_path: str = "") -> str:
        """Prepare contrastive learning data from strategy corpus.

        Creates positive pairs (same role + related phase) and hard negatives
        (different role, similar phase) for domain adaptation fine-tuning.

        Returns path to the generated training data.
        """
        import json

        if output_path:
            path = output_path
        else:
            path = "data/bge_finetune_pairs.jsonl"

        pairs = []
        for i, d1 in enumerate(self._docs):
            # Positive: same role + same phase (different doc)
            positives = []
            for j, d2 in enumerate(self._docs):
                if i != j and d2.get("role") == d1.get("role") and d2.get("phase") == d1.get("phase"):
                    positives.append(d2["recommended"])
                    if len(positives) >= 3:
                        break

            # Negative: different role
            negatives = []
            for j, d2 in enumerate(self._docs):
                if d2.get("role") != d1.get("role") and d2.get("role") != "global":
                    negatives.append(d2["recommended"])
                    if len(negatives) >= 3:
                        break

            if positives and negatives:
                pairs.append({
                    "anchor": d1["recommended"],
                    "positive": positives[0],
                    "negatives": negatives,
                })

        with open(path, "w") as f:
            for p in pairs:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

        logger.info(f"Fine-tune data written: {len(pairs)} triplets → {path}")
        return path

    def finetune(
        self,
        train_data_path: str = "",
        epochs: int = 3,
        lr: float = 2e-5,
        output_path: str = "",
    ) -> str:
        """Fine-tune BGE-M3 on domain data with contrastive learning.

        Uses MultipleNegativesRankingLoss with in-batch negatives.
        After fine-tuning, the model weights are saved to output_path.
        """
        from torch.utils.data import DataLoader
        from sentence_transformers import InputExample, losses

        path = train_data_path or "data/bge_finetune_pairs.jsonl"

        # Load training data
        import json
        examples = []
        with open(path) as f:
            for line in f:
                obj = json.loads(line.strip())
                # (anchor, positive) as positive pair
                examples.append(InputExample(
                    texts=[obj["anchor"], obj["positive"]]
                ))
                # (anchor, negative) as additional pairs for hard negative
                for neg in obj.get("negatives", [])[:1]:
                    examples.append(InputExample(
                        texts=[obj["anchor"], neg]
                    ))

        logger.info(f"Fine-tuning with {len(examples)} examples, {epochs} epochs, lr={lr}")

        # DataLoader
        loader = DataLoader(examples, shuffle=True, batch_size=16)

        # MultipleNegativesRankingLoss (standard for embedding fine-tuning)
        loss = losses.MultipleNegativesRankingLoss(self._model)

        # Fine-tune
        self._model.fit(
            train_objectives=[(loader, loss)],
            epochs=epochs,
            optimizer_params={"lr": lr},
            warmup_steps=int(len(loader) * 0.1),
            show_progress_bar=True,
        )

        # Save
        save_path = output_path or f"{self._model_path}-werewolf-finetuned"
        self._model.save(save_path)
        logger.info(f"Fine-tuned model saved to {save_path}")
        return save_path

    # ---- Properties ----

    @property
    def size(self) -> int:
        return len(self._docs)

    @property
    def ready(self) -> bool:
        return self._built

    @property
    def embedding_dim(self) -> int:
        return self._embeddings.shape[1] if self._embeddings is not None else 0


# ============================================================
# Public API (compatible with retrieval.py interface)
# ============================================================

_retriever: Optional[BGERetriever] = None


def get_bge_retriever(
    model_path: str = "", device: str = "", conn_str: str = ""
) -> BGERetriever:
    """Get or build the global BGE retriever (singleton)."""
    global _retriever
    if _retriever is None or not _retriever.ready:
        _retriever = BGERetriever(
            model_path=model_path,
            device=device,
            conn_str=conn_str,
        )
        _retriever.build()
    return _retriever


def retrieve_strategies_bge(
    role: str,
    phase: str,
    situation: str = "",
    limit: int = 3,
    conn_str: str = "",
) -> List[Dict[str, str]]:
    """Retrieve strategies using BGE-M3 embeddings (drop-in for retrieval.retrieve_strategies)."""
    retriever = get_bge_retriever(conn_str=conn_str)
    query = situation or _default_query(role, phase)
    return retriever.search(query, role=role, phase=phase, limit=limit)


def format_strategies_for_prompt(strategies: List[Dict[str, str]]) -> str:
    """Format retrieved strategies into prompt text."""
    if not strategies:
        return ""

    lines = ["=== 相关策略参考 ==="]
    for i, s in enumerate(strategies, 1):
        lines.append(f"{i}. 场景：{s.get('situation', '')}")
        lines.append(f"   策略：{s.get('strategy', '')}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# Internal helpers
# ============================================================

def _load_docs_from_pg(conn_str: str) -> List[Dict[str, Any]]:
    """Load all active strategy documents from PostgreSQL."""
    import psycopg2
    conn = psycopg2.connect(conn_str)
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(situation_pattern, ''),
               COALESCE(recommended_action, ''),
               COALESCE(rationale, ''),
               role, phase, quality_score
        FROM strategy_knowledge_docs
        WHERE status = 'active'
    """)
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append({
            "situation": sit or "",
            "recommended": rec or "",
            "rationale": rat or "",
            "role": role or "global",
            "phase": phase or "global",
            "quality": float(q) if q else 0.8,
        })
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
