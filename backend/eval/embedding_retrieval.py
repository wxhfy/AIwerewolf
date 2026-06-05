"""BGE-M3 embedding-based similar case retrieval for DecisionOpportunity.

Phase 4 of Track B reconstruction (§6): uses BGE-M3 for semantic similarity
search over historical opportunities. Embedding is NOT used for direct scoring
— it feeds similarity features into DecisionQualityModel.

Model: BGE-M3 (BAAI/bge-m3)
  - Multilingual (Chinese + English)
  - Dense + sparse + multi-vector retrieval
  - Max 8192 tokens
  - No fine-tuning needed for MVP
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# BGE-M3 provider
# ---------------------------------------------------------------------------


class BGEM3Provider:
    """Thin wrapper around BGE-M3 for opportunity text embedding."""

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.model_name, use_fp16=(self.device != "cpu"))
        return self._model

    @property
    def dim(self) -> int:
        return 1024  # BGE-M3 dense embedding dimension

    def embed(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Encode texts to dense embeddings. Returns (n, 1024) array."""
        if not texts:
            return np.array([]).reshape(0, self.dim)
        output = self.model.encode(
            texts,
            batch_size=batch_size,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return np.array(output["dense_vecs"])

    def embed_single(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# ---------------------------------------------------------------------------
# Opportunity text formatter (§6.3)
# ---------------------------------------------------------------------------


def format_opportunity_text(opp: dict[str, Any]) -> str:
    """Format an opportunity into a searchable text representation.

    Follows goal doc §6.3 specification.
    """
    lines = [
        f"角色：{opp.get('role', '')}",
        f"阶段：{opp.get('phase', '')}",
        f"机会类型：{opp.get('opportunity_type', '')}",
        f"第{opp.get('day', '?')}天",
    ]

    # Game features
    gf = opp.get("game_features", {})
    if gf:
        lines.append(f"存活人数：{gf.get('alive_count', '?')}")
        cb = gf.get("camp_balance", {})
        if cb:
            lines.append(f"阵营：好人{cb.get('village_alive', '?')}人 狼人{cb.get('wolf_alive', '?')}人")

    # Target features
    tf = opp.get("target_features", {})
    if tf:
        lines.append(f"目标角色：{tf.get('target_role', '?')}")
        lines.append(f"目标阵营：{tf.get('target_alignment', '?')}")

    # Action
    ca = opp.get("chosen_action", {})
    if isinstance(ca, dict):
        action_desc = ca.get("type") or ca.get("action_type") or json.dumps(ca, ensure_ascii=False)[:200]
        lines.append(f"动作：{action_desc}")

    # Context
    pub = opp.get("public_context_summary", "")
    priv = opp.get("private_context_summary", "")
    if pub:
        lines.append(f"公开信息：{pub[:500]}")
    if priv:
        lines.append(f"私有信息：{priv[:500]}")

    # Outcome
    of_ = opp.get("outcome_features", {})
    if of_:
        lines.append(f"结果：{json.dumps(of_, ensure_ascii=False)[:200]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Similarity index
# ---------------------------------------------------------------------------


@dataclass
class RetrievedCase:
    """One similar historical case retrieved by embedding search."""

    opportunity_id: str
    role: str
    opportunity_type: str
    similarity: float
    quality_label: float | None = None
    was_good: bool | None = None
    text: str = ""


class OpportunityIndex:
    """Embedding index over historical DecisionOpportunity records.

    Builds BGE-M3 embeddings for all opportunities and supports
    similarity search.
    """

    def __init__(self, provider: BGEM3Provider | None = None):
        self.provider = provider or BGEM3Provider()
        self.opportunities: list[dict[str, Any]] = []
        self.texts: list[str] = []
        self.embeddings: np.ndarray | None = None

    def add(self, opportunities: list[dict[str, Any]]) -> OpportunityIndex:
        self.opportunities.extend(opportunities)
        new_texts = [format_opportunity_text(o) for o in opportunities]
        self.texts.extend(new_texts)
        self.embeddings = None  # Invalidate cache
        return self

    def build(self, batch_size: int = 32) -> OpportunityIndex:
        if not self.texts:
            return self
        print(f"  Building BGE-M3 index for {len(self.texts)} opportunities...")
        self.embeddings = self.provider.embed(self.texts, batch_size=batch_size)
        print(f"  Index built: {self.embeddings.shape}")
        return self

    def search(
        self,
        query_opp: dict[str, Any],
        top_k: int = 5,
        same_role_only: bool = True,
        same_type_only: bool = False,
    ) -> list[RetrievedCase]:
        """Search for similar historical cases."""
        if self.embeddings is None:
            self.build()

        query_text = format_opportunity_text(query_opp)
        query_vec = self.provider.embed_single(query_text)

        # Cosine similarity with all stored embeddings
        similarities = self._cosine_similarity(query_vec, self.embeddings)

        # Filter and sort
        results: list[RetrievedCase] = []
        query_role = query_opp.get("role", "")
        query_type = query_opp.get("opportunity_type", "")

        for i, sim in enumerate(similarities):
            opp = self.opportunities[i]
            if same_role_only and opp.get("role") != query_role:
                continue
            if same_type_only and opp.get("opportunity_type") != query_type:
                continue
            if opp.get("opportunity_id") == query_opp.get("opportunity_id"):
                continue  # Skip self

            results.append(
                RetrievedCase(
                    opportunity_id=opp.get("opportunity_id", ""),
                    role=opp.get("role", ""),
                    opportunity_type=opp.get("opportunity_type", ""),
                    similarity=round(float(sim), 4),
                    text=self.texts[i][:300],
                )
            )

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:top_k]

    def search_batch(
        self,
        queries: list[dict[str, Any]],
        top_k: int = 5,
        **kwargs,
    ) -> list[list[RetrievedCase]]:
        return [self.search(q, top_k=top_k, **kwargs) for q in queries]

    def _cosine_similarity(self, query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        q_norm = np.linalg.norm(query_vec)
        m_norms = np.linalg.norm(matrix, axis=1)
        if q_norm == 0 or np.any(m_norms == 0):
            return np.zeros(len(matrix))
        dot = np.dot(matrix, query_vec)
        return dot / (m_norms * q_norm + 1e-8)

    def compute_retrieval_features(
        self,
        query_opp: dict[str, Any],
        good_index: OpportunityIndex | None = None,
        bad_index: OpportunityIndex | None = None,
        top_k: int = 3,
    ) -> dict[str, float]:
        """Compute embedding retrieval features for DecisionQualityModel.

        From goal doc §6.3:
          nearest_good_similarity, nearest_bad_similarity,
          good_bad_similarity_margin, similar_good_avg_quality,
          similar_bad_avg_quality
        """
        features: dict[str, float] = {
            "nearest_good_similarity": 0.0,
            "nearest_bad_similarity": 0.0,
            "good_bad_similarity_margin": 0.0,
            "similar_good_avg_quality": 0.0,
            "similar_bad_avg_quality": 0.0,
            "similar_good_count": 0,
            "similar_bad_count": 0,
        }

        if good_index and good_index.embeddings is not None:
            good_results = good_index.search(query_opp, top_k=top_k)
            if good_results:
                features["nearest_good_similarity"] = good_results[0].similarity
                features["similar_good_avg_quality"] = sum(r.similarity for r in good_results) / len(good_results)
                features["similar_good_count"] = len(good_results)

        if bad_index and bad_index.embeddings is not None:
            bad_results = bad_index.search(query_opp, top_k=top_k)
            if bad_results:
                features["nearest_bad_similarity"] = bad_results[0].similarity
                features["similar_bad_avg_quality"] = sum(r.similarity for r in bad_results) / len(bad_results)
                features["similar_bad_count"] = len(bad_results)

        if features["nearest_good_similarity"] > 0 and features["nearest_bad_similarity"] > 0:
            features["good_bad_similarity_margin"] = (
                features["nearest_good_similarity"] - features["nearest_bad_similarity"]
            )

        return features

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            embeddings=self.embeddings if self.embeddings is not None else np.array([]),
            opp_ids=[o.get("opportunity_id", "") for o in self.opportunities],
            roles=[o.get("role", "") for o in self.opportunities],
            types=[o.get("opportunity_type", "") for o in self.opportunities],
        )
        print(f"Index saved to {path} ({len(self.opportunities)} items)")

    @classmethod
    def load(cls, path: str | Path, opportunities: list[dict[str, Any]]) -> OpportunityIndex:
        data = np.load(path, allow_pickle=True)
        index = cls()
        index.embeddings = data["embeddings"]
        index.opportunities = opportunities
        index.texts = [format_opportunity_text(o) for o in opportunities]
        return index


# ---------------------------------------------------------------------------
# Train/val/test split by game
# ---------------------------------------------------------------------------


def split_by_game(
    opportunities: list[dict[str, Any]],
    val_ratio: float = 0.15,
    test_ratio: float = 0.10,
    seed: int = 42,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split opportunities by game_id to avoid data leakage."""
    import random

    random.seed(seed)

    game_ids = list(set(o["game_id"] for o in opportunities))
    random.shuffle(game_ids)

    n = len(game_ids)
    n_test = max(1, int(n * test_ratio))
    n_val = max(1, int(n * val_ratio))
    n_train = n - n_val - n_test

    train_games = set(game_ids[:n_train])
    val_games = set(game_ids[n_train : n_train + n_val])
    test_games = set(game_ids[n_train + n_val :])

    train = [o for o in opportunities if o["game_id"] in train_games]
    val = [o for o in opportunities if o["game_id"] in val_games]
    test = [o for o in opportunities if o["game_id"] in test_games]

    return train, val, test


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/health/opportunities.jsonl")
    ap.add_argument("--build-index", action="store_true")
    ap.add_argument("--test-search", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ROOT = Path(__file__).resolve().parent.parent
    opps_path = ROOT / args.input

    opportunities = []
    with open(opps_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                opportunities.append(json.loads(line))

    print(f"Loaded {len(opportunities)} opportunities")

    if args.limit:
        opportunities = opportunities[: args.limit]

    if args.build_index:
        index = OpportunityIndex()
        index.add(opportunities)
        index.build()
        index.save(ROOT / "data/health/opportunity_index.npz")
        print(f"Index saved with {len(index.opportunities)} items")

    if args.test_search:
        # Test: search for similar opportunities
        index = OpportunityIndex()
        index.add(opportunities)
        index.build()

        # Test queries: pick one from each role
        seen_roles = set()
        for opp in opportunities:
            role = opp.get("role", "")
            op_type = opp.get("opportunity_type", "")
            if role not in seen_roles and op_type in ("witch_save", "guard_protect", "werewolf_kill", "seer_check"):
                seen_roles.add(role)
                print(f"\n=== Query: {role} {op_type} ===")
                results = index.search(opp, top_k=3, same_role_only=True)
                for i, r in enumerate(results):
                    print(f"  {i + 1}. [{r.role}] sim={r.similarity:.4f} | {r.text[:120]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
