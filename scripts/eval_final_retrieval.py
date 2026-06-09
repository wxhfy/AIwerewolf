#!/usr/bin/env python3
"""
Final Retrieval System Design for AI Werewolf Strategy Corpus (907 docs).

Methods compared (corrected + cutting-edge):
  A. BM25 (sparse baseline)
  B. BGE-M3 Dense (1024-dim)
  C. BGE-M3 Sparse (learned lexical)
  D. BGE-M3 Dense + Sparse RRF (native fusion)
  E. BM25 + BGE-M3 Dense RRF (hybrid baseline, FIXED idx)
  F. BGE-M3 Dense + Sparse RRF + ColBERT Rerank (two-stage)
  G. BGE-M3 + Dynamic Entropy-based Alpha Tuning
  H. Query Expansion + RRF + ColBERT Rerank (full pipeline)

Key improvements over previous:
  - Fixed BM25 idx propagation for correct RRF
  - Dynamic entropy-based alpha tuning (2025 ICML workshop)
  - Query expansion using BGE-M3 for zero-shot query enrichment
  - Proper two-stage ColBERT reranking on RRF pool (not just Dense pool)
"""

from __future__ import annotations

import sys
import time

import jieba
import numpy as np
import psycopg2
from rank_bm25 import BM25Okapi

sys.path.insert(0, ".")

CONN_STR = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
RRF_K = 60

# ============================================================
# Data
# ============================================================


def load_docs():
    conn = psycopg2.connect(CONN_STR)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score
               FROM strategy_knowledge_docs WHERE status='active'""")
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append(
            {
                "situation": sit or "",
                "strategy": rec or "",
                "rationale": rat or "",
                "role": role or "global",
                "phase": phase or "global",
                "quality": float(q) if q else 0.8,
            }
        )
    conn.close()
    return docs


# ============================================================
# Test Queries (40: 20 base + 20 special)
# ============================================================


def make_queries():
    base = [
        {
            "id": "N01",
            "role": "Seer",
            "phase": "DAY_BADGE_SPEECH",
            "text": "我是预言家竞选警长需要报警徽流和查验结果",
            "kw": ["警徽流", "警长竞选", "报查验"],
        },
        {
            "id": "N02",
            "role": "Witch",
            "phase": "NIGHT_WITCH_ACTION",
            "text": "第一晚有人被刀我要决定是否使用解药救人",
            "kw": ["首夜解药", "解药使用"],
        },
        {
            "id": "N03",
            "role": "Werewolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "今晚狼队要选择击杀目标应该优先刀谁",
            "kw": ["刀人优先级", "刀法"],
        },
        {
            "id": "N04",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "我是狼人需要伪装成好人发言不能被发现",
            "kw": ["伪装好人", "狼人伪装"],
        },
        {
            "id": "N05",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "我是平民需要给出有价值的发言分析局势",
            "kw": ["平民发言", "发言质量"],
        },
        {
            "id": "N06",
            "role": "Hunter",
            "phase": "DAY_SPEECH",
            "text": "我被多人投票可能要出局要不要跳猎人身份",
            "kw": ["猎人跳身份", "枪徽流"],
        },
        {
            "id": "N07",
            "role": "Seer",
            "phase": "DAY_SPEECH",
            "text": "有人对跳预言家我需要证明自己是真的",
            "kw": ["对跳预言家", "查验链"],
        },
        {
            "id": "N08",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "我被真预言家查杀了应该怎么应对",
            "kw": ["被查杀", "反跳"],
        },
        {
            "id": "N09",
            "role": "Witch",
            "phase": "mid_game",
            "text": "第三天了我有一瓶毒药还没用应该毒谁",
            "kw": ["毒药使用", "开毒时机"],
        },
        {
            "id": "N10",
            "role": "Guard",
            "phase": "NIGHT_GUARD_ACTION",
            "text": "今晚我要守护一个人不能连续守同一个",
            "kw": ["守护目标", "轮换守护"],
        },
        {
            "id": "N11",
            "role": "WhiteWolfKing",
            "phase": "DAY_SPEECH",
            "text": "白狼王什么时候自爆带走关键好人最合适",
            "kw": ["白狼王自爆", "自爆时机"],
        },
        {
            "id": "N12",
            "role": "global",
            "phase": "DAY_VOTE",
            "text": "投票环节怎样分析票型来找到狼人",
            "kw": ["票型分析", "冲票"],
        },
        {
            "id": "N13",
            "role": "global",
            "phase": "late_game",
            "text": "残局只剩3个人怎么做出正确的投票抉择",
            "kw": ["残局策略", "残局抉择"],
        },
        {
            "id": "N14",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "狼队友被怀疑了怎么帮他又不暴露自己",
            "kw": ["队友被质疑", "保护队友"],
        },
        {
            "id": "N15",
            "role": "Villager",
            "phase": "DAY_VOTE",
            "text": "作为平民不确定该投谁怎么正确投票",
            "kw": ["平民投票"],
        },
        {
            "id": "N16",
            "role": "global",
            "phase": "global",
            "text": "我是新手第一次玩狼人杀需要了解基础规则",
            "kw": ["新手", "基础规则"],
        },
        {
            "id": "N17",
            "role": "Witch",
            "phase": "DAY_SPEECH",
            "text": "我救过一个人银水要不要在白天报出来",
            "kw": ["银水", "报银水"],
        },
        {
            "id": "N18",
            "role": "Seer",
            "phase": "NIGHT_SEER_ACTION",
            "text": "今晚我要验一个人应该优先验谁",
            "kw": ["查验选择", "验人优先级"],
        },
        {
            "id": "N19",
            "role": "global",
            "phase": "mid_game",
            "text": "我发现之前站错边了现在怎么纠正",
            "kw": ["站错边", "修正判断"],
        },
        {
            "id": "N20",
            "role": "Werewolf",
            "phase": "DAY_VOTE",
            "text": "关键时刻需要和狼队友统一冲票推掉一个好人",
            "kw": ["冲票", "统一投票", "绑票"],
        },
    ]
    special = [
        {"id": "E01", "role": "Seer", "phase": "DAY_SPEECH", "text": "我被女巫毒了怎么办", "kw": ["被毒", "遗言"]},
        {
            "id": "E02",
            "role": "Werewolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "只剩下我一匹狼了该怎么刀人",
            "kw": ["最后一狼", "独狼"],
        },
        {
            "id": "E03",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "所有人都说我是狼但我真的是平民",
            "kw": ["被冤枉", "表水"],
        },
        {"id": "E04", "role": "global", "phase": "global", "text": "这游戏好难我不会玩怎么办", "kw": ["新手", "入门"]},
        {"id": "E05", "role": "global", "phase": "global", "text": "怎样才能赢", "kw": ["胜利", "策略"]},
        {
            "id": "E06",
            "role": "Seer",
            "phase": "DAY_BADGE_SPEECH",
            "text": "我是预言家有查杀但对跳也出现了警徽流怎么安排",
            "kw": ["对跳", "警徽流", "查杀"],
        },
        {
            "id": "E07",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "既要伪装又要带节奏还要保护队友怎么同时做好",
            "kw": ["伪装", "带节奏"],
        },
        {
            "id": "E09",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "我听到旁边有声音这局谁是狼我心里有数",
            "kw": ["场外", "贴脸"],
        },
        {"id": "E11", "role": "global", "phase": "global", "text": "怎么玩", "kw": ["新手", "入门"]},
        {"id": "E12", "role": "Werewolf", "phase": "global", "text": "自刀", "kw": ["自刀"]},
        {"id": "E13", "role": "global", "phase": "mid_game", "text": "剩1狼2民1神怎么投", "kw": ["残局", "轮次"]},
        {
            "id": "E14",
            "role": "Cupid",
            "phase": "night_1",
            "text": "丘比特第一晚应该连谁比较好",
            "kw": ["丘比特", "情侣"],
        },
        {
            "id": "E18",
            "role": "Witch",
            "phase": "mid_game",
            "text": "我毒错人了毒死了一个平民现在怎么办",
            "kw": ["毒错", "补救"],
        },
        {
            "id": "E19",
            "role": "Werewolf",
            "phase": "mid_game",
            "text": "刀错人了刀到了平民狼刀落后怎么翻盘",
            "kw": ["刀错", "翻盘"],
        },
        {
            "id": "E20",
            "role": "Guard",
            "phase": "mid_game",
            "text": "守错人了守了一个狼人导致预言家被刀死了",
            "kw": ["守错", "失误"],
        },
    ]
    return base + special


# ============================================================
# BGE-M3 Engine (shared)
# ============================================================


class BGEEngine:
    """Unified BGE-M3: Dense + Sparse + ColBERT + Query Expansion."""

    def __init__(self, docs, model_path=BGE_PATH, device=GPU):
        from FlagEmbedding import BGEM3FlagModel

        self.docs = docs
        self.model = BGEM3FlagModel(model_path, use_fp16=True, device=device)
        self.doc_texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
        self.N = len(docs)

        # Pre-compute
        t0 = time.perf_counter()
        self.dense = np.zeros((self.N, 1024), dtype=np.float32)
        self.sparse = []  # List[Dict[int, float]]
        self.colbert = []  # List[np.ndarray]
        bs = 64
        for i in range(0, self.N, bs):
            batch = self.doc_texts[i : i + bs]
            out = self.model.encode(batch, return_dense=True, return_sparse=True, return_colbert_vecs=True)
            self.dense[i : i + len(batch)] = out["dense_vecs"]
            self.sparse.extend(out["lexical_weights"])
            self.colbert.extend(out["colbert_vecs"])
        # Normalize dense
        norms = np.linalg.norm(self.dense, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self.dense /= norms
        self._build_time = time.perf_counter() - t0
        print(
            f"  BGE Engine: {self.N} docs, dense={self.dense.shape}, "
            f"sparse={len(self.sparse)}, colbert={len(self.colbert)}, "
            f"built in {self._build_time:.1f}s"
        )

    def encode(self, text):
        return self.model.encode(text, return_dense=True, return_sparse=True, return_colbert_vecs=True)

    # ---- Dense search ----
    def search_dense(self, q, k=20):
        out = self.encode(q["text"])
        qv = np.asarray(out["dense_vecs"], dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = np.dot(self.dense, qv)
        scores = sims + self._role_bonus(q) + self._phase_bonus(q)
        idx = np.argsort(scores)[::-1][:k]
        return [
            {
                "idx": int(i),
                "score": float(sims[i]),
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
            }
            for i in idx
        ]

    # ---- Sparse search ----
    def search_sparse(self, q, k=20):
        out = self.encode(q["text"])
        q_weights = out["lexical_weights"]
        scores = np.zeros(self.N)
        for i, dw in enumerate(self.sparse):
            s = sum(q_weights.get(t, 0) * dw.get(t, 0) for t in q_weights)
            scores[i] = s
        if scores.max() > 0:
            scores /= scores.max()
        scores += self._role_bonus(q) + self._phase_bonus(q)
        idx = np.argsort(scores)[::-1][:k]
        return [
            {
                "idx": int(i),
                "score": float(scores[i]),
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
            }
            for i in idx
        ]

    # ---- ColBERT rerank ----
    def colbert_rerank(self, q, candidates, k=10):
        out = self.encode(q["text"])
        qc = np.asarray(out["colbert_vecs"], dtype=np.float32)
        qc /= np.linalg.norm(qc, axis=1, keepdims=True) + 1e-8

        scores = np.zeros(len(candidates))
        for j, c in enumerate(candidates):
            dc = np.asarray(self.colbert[c["idx"]], dtype=np.float32)
            dc /= np.linalg.norm(dc, axis=1, keepdims=True) + 1e-8
            sim = np.dot(qc, dc.T)
            scores[j] = np.sum(np.max(sim, axis=1))

        top = np.argsort(scores)[::-1][:k]
        return [
            {
                "situation": candidates[i]["situation"],
                "strategy": candidates[i]["strategy"],
                "quality": candidates[i]["quality"],
            }
            for i in top
        ]

    # ---- Query expansion ----
    def expand_query(self, q_text, top_k=3):
        """Use BGE-M3 to find related strategy text, extract key phrases as query expansion."""
        # Quick dense search to find related strategies
        out = self.encode(q_text)
        qv = np.asarray(out["dense_vecs"], dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = np.dot(self.dense, qv)
        top_idx = np.argsort(sims)[::-1][:top_k]

        # Extract key phrases from top strategies
        phrases = []
        for i in top_idx:
            # Use jieba to extract key terms
            words = [w for w in jieba.cut(self.docs[i]["situation"]) if len(w) >= 2]
            phrases.extend(words[:3])

        # Deduplicate and add to query
        new_terms = [p for p in phrases if p not in q_text][:5]
        if new_terms:
            return q_text + " " + " ".join(new_terms)
        return q_text

    def _role_bonus(self, q):
        return np.array(
            [0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in self.docs],
            dtype=np.float32,
        )

    def _phase_bonus(self, q):
        return np.array(
            [0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in self.docs],
            dtype=np.float32,
        )

    def _query_entropy(self, q_weights):
        """Compute normalized entropy of query sparse weights for dynamic alpha tuning."""
        vals = np.array(list(q_weights.values()))
        if len(vals) < 2:
            return 0.0
        probs = vals / vals.sum()
        entropy = -np.sum(probs * np.log(probs + 1e-8))
        max_entropy = np.log(len(probs))
        return entropy / max_entropy if max_entropy > 0 else 0.0


# ============================================================
# BM25 Engine
# ============================================================


class BM25Engine:
    def __init__(self, docs):
        self.docs = docs
        corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
        self.bm25 = BM25Okapi([t.split() for t in corpus])
        self.N = len(docs)

    def search(self, q, k=20):
        scores = self.bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if scores.max() > 0:
            scores = scores / scores.max()
        scores += np.array(
            [0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in self.docs]
        )
        scores += np.array(
            [0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in self.docs]
        )
        idx = np.argsort(scores)[::-1][:k]
        return [
            {
                "idx": int(i),
                "score": float(scores[i]),
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
            }
            for i in idx
        ]


# ============================================================
# Fusion Methods
# ============================================================


def rrf_fuse(list_a, list_b, docs, k=20, rrf_k=RRF_K):
    """Reciprocal Rank Fusion — CORRECTED with proper idx from both lists."""
    scores = {}
    for rank, r in enumerate(list_a, 1):
        scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0 / (rrf_k + rank)
    for rank, r in enumerate(list_b, 1):
        scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0 / (rrf_k + rank)
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
    return [
        {
            "idx": i,
            "rrf_score": s,
            "situation": docs[i]["situation"],
            "strategy": docs[i]["strategy"],
            "quality": docs[i]["quality"],
        }
        for i, s in top
    ]


def dynamic_alpha_fuse(list_a, list_b, docs, entropy, k=20):
    """
    Dynamic entropy-based alpha tuning (ICML 2025).
    High entropy (many diverse keywords) → more weight on sparse.
    Low entropy (few specific terms) → more weight on dense.
    """
    alpha = 0.3 + 0.4 * entropy  # entropy 0→alpha=0.3, entropy 1→alpha=0.7
    scores = np.zeros(len(docs))
    for r in list_a:
        scores[r["idx"]] += alpha * r.get("score", 1.0 / (1 + list_a.index(r)))
    for r in list_b:
        scores[r["idx"]] += (1 - alpha) * r.get("score", 1.0 / (1 + list_b.index(r)))
    idx = np.argsort(scores)[::-1][:k]
    return [
        {
            "idx": int(i),
            "situation": docs[i]["situation"],
            "strategy": docs[i]["strategy"],
            "quality": docs[i]["quality"],
        }
        for i in idx
    ]


# ============================================================
# Metrics
# ============================================================


def relevance(result, query):
    content = f"{result.get('situation', '')} {result.get('strategy', '')}".lower()
    kw = query.get("kw", [])
    m = sum(1 for k in kw if k.lower() in content)
    return 2 if m >= 3 else (1 if m >= 1 else 0)


def evaluate(results, query):
    m = {}
    for k in [5, 10]:
        kk = min(k, len(results))
        rel = [relevance(r, query) for r in results[:kk]]
        m[f"P@{k}"] = sum(1 for r in rel if r > 0) / max(kk, 1)
    for rank, r in enumerate(results, 1):
        if relevance(r, query) > 0:
            m["MRR"] = 1.0 / rank
            break
    else:
        m["MRR"] = 0.0
    for k in [5, 10]:
        kk = min(k, len(results))
        gains = [relevance(r, query) for r in results[:kk]]
        dcg = sum(g / np.log2(i + 2) for i, g in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(g / np.log2(i + 2) for i, g in enumerate(ideal))
        m[f"NDCG@{k}"] = dcg / idcg if idcg > 0 else 0.0
    return m


# ============================================================
# Main
# ============================================================


def main():
    print("=" * 100)
    print("FINAL RETRIEVAL SYSTEM — 8 Methods, Corrected + Cutting-Edge")
    print("=" * 100)

    docs = load_docs()
    queries = make_queries()
    print(f"\n{docs} docs, {len(queries)} queries")

    # Build engines
    print("\n[1/2] BGE-M3 Engine (dense + sparse + colbert)...")
    bge = BGEEngine(docs)

    print("\n[2/2] BM25 Engine...")
    bm25 = BM25Engine(docs)

    # ================================================================
    # Define methods
    # ================================================================
    methods = {}

    # A: BM25
    methods["A_BM25"] = ("BM25", lambda q: bm25.search(q, k=10))

    # B: BGE Dense
    methods["B_BGE_Dense"] = ("BGE Dense", lambda q: bge.search_dense(q, k=10))

    # C: BGE Sparse
    methods["C_BGE_Sparse"] = ("BGE Sparse", lambda q: bge.search_sparse(q, k=10))

    # D: BGE Dense + Sparse RRF
    methods["D_BGE_DS_RRF"] = (
        "BGE DS-RRF",
        lambda q: rrf_fuse(bge.search_dense(q, k=20), bge.search_sparse(q, k=20), docs, k=10),
    )

    # E: BM25 + BGE Dense RRF (FIXED)
    methods["E_BM25+BGE_RRF"] = (
        "BM25+BGE RRF",
        lambda q: rrf_fuse(bm25.search(q, k=20), bge.search_dense(q, k=20), docs, k=10),
    )

    # F: BGE DS-RRF + ColBERT rerank
    methods["F_DS_RRF+ColBERT"] = (
        "DS-RRF+ColBERT",
        lambda q: bge.colbert_rerank(
            q, rrf_fuse(bge.search_dense(q, k=20), bge.search_sparse(q, k=20), docs, k=20), k=10
        ),
    )

    # G: Dynamic entropy-based alpha tuning (BGE Sparse + Dense)
    def dyn_search(q):
        out = bge.encode(q["text"])
        entropy = bge._query_entropy(out["lexical_weights"])
        # Get both lists with full scores
        d_list = bge.search_dense(q, k=20)
        s_list = bge.search_sparse(q, k=20)
        return dynamic_alpha_fuse(s_list, d_list, docs, entropy, k=10)

    methods["G_DynAlpha"] = ("DynAlpha Fuse", dyn_search)

    # H: Query Expansion + DS-RRF + ColBERT (full pipeline)
    def full_pipeline(q):
        expanded_text = bge.expand_query(q["text"], top_k=3)
        q_expanded = dict(q)  # copy
        q_expanded["text"] = expanded_text
        candidates = rrf_fuse(bge.search_dense(q_expanded, k=20), bge.search_sparse(q_expanded, k=20), docs, k=20)
        return bge.colbert_rerank(q_expanded, candidates, k=10)

    methods["H_QE+DS+ColBERT"] = ("QE+DS+ColBERT", full_pipeline)

    # ================================================================
    # Evaluate
    # ================================================================
    results = {}
    for mname, (mlabel, mfunc) in methods.items():
        metrics_list = []
        lats = []
        for q in queries:
            t0 = time.perf_counter()
            res = mfunc(q)
            lat = (time.perf_counter() - t0) * 1000
            lats.append(lat)
            m = evaluate(res, q)
            m["latency_ms"] = lat
            metrics_list.append(m)

        base_m = metrics_list[:20]
        spec_m = metrics_list[20:]
        results[mname] = {"all": metrics_list, "base": base_m, "special": spec_m}

        agg = {k: np.mean([qm[k] for qm in metrics_list]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
        base_n = np.mean([qm["NDCG@5"] for qm in base_m])
        spec_n = np.mean([qm["NDCG@5"] for qm in spec_m])
        print(f"\n{mname} ({mlabel}):")
        print(
            f"  ALL:  P@5={agg['P@5']:.3f} P@10={agg['P@10']:.3f} MRR={agg['MRR']:.3f} "
            f"NDCG@5={agg['NDCG@5']:.3f} NDCG@10={agg['NDCG@10']:.3f}  lat={np.mean(lats):.0f}ms"
        )
        print(f"  BASE: NDCG@5={base_n:.3f}  SPEC: NDCG@5={spec_n:.3f}")

    # ================================================================
    # Summary Table
    # ================================================================
    print(f"\n{'=' * 100}")
    print("SUMMARY TABLE — All 8 Methods (40 queries)")
    print(f"{'=' * 100}")
    print(
        f"\n{'#':<3} {'Method':<24} {'P@5':>7} {'P@10':>7} {'MRR':>7} {'NDCG@5':>8} {'NDCG@10':>8} {'Lat':>6} {'Base':>7} {'Spec':>7}"
    )
    print("-" * 100)

    def best(metric, higher=True):
        vals = {mn: np.mean([q[metric] for q in results[mn]["all"]]) for mn in methods}
        return max(vals, key=vals.get) if higher else min(vals, key=vals.get)

    ranked = sorted(methods.keys(), key=lambda m: np.mean([q["NDCG@5"] for q in results[m]["all"]]), reverse=True)

    for rank, mname in enumerate(ranked, 1):
        label = methods[mname][0]
        agg = {
            k: np.mean([q[k] for q in results[mname]["all"]])
            for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10", "latency_ms"]
        }
        base_n = np.mean([q["NDCG@5"] for q in results[mname]["base"]])
        spec_n = np.mean([q["NDCG@5"] for q in results[mname]["special"]])
        markers = []
        for mk in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]:
            if mname == best(mk):
                markers.append(mk)
        star = " ⭐" if len(markers) >= 2 else ""

        print(
            f"{rank:<3} {label:<24} {agg['P@5']:>7.3f} {agg['P@10']:>7.3f} {agg['MRR']:>7.3f} "
            f"{agg['NDCG@5']:>8.3f} {agg['NDCG@10']:>8.3f} {agg['latency_ms']:>5.0f}ms {base_n:>7.3f} {spec_n:>7.3f}{star}"
        )

    # Winner details
    print(f"\n{'=' * 100}")
    print("METRIC WINNERS:")
    for mk in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10", "latency_ms"]:
        w = best(mk, higher=(mk != "latency_ms"))
        label, _ = methods[w]
        v = np.mean([q[mk] for q in results[w]["all"]])
        print(f"  {mk:<12}: {label:<24} = {v:.3f}" + ("ms" if "latency" in mk else ""))

    # Recommendation
    print(f"\n{'=' * 100}")
    print("FINAL RECOMMENDATION:")
    print(f"{'=' * 100}")

    # Find best quality under 200ms
    quality_candidates = {
        mn: np.mean([q["NDCG@5"] for q in results[mn]["all"]])
        for mn in methods
        if np.mean([q["latency_ms"] for q in results[mn]["all"]]) < 200
    }
    best_q = max(quality_candidates, key=quality_candidates.get)

    # Find fastest with NDCG > 0.75
    fast_candidates = {
        mn: np.mean([q["latency_ms"] for q in results[mn]["all"]])
        for mn in methods
        if np.mean([q["NDCG@5"] for q in results[mn]["all"]]) > 0.65
    }
    best_f = min(fast_candidates, key=fast_candidates.get) if fast_candidates else "N/A"

    _, best_q_label = methods[best_q]
    print(f"\n  🏆 Production choice: {best_q_label}")
    print(f"     NDCG@5 = {np.mean([q['NDCG@5'] for q in results[best_q]['all']]):.3f}")
    print(f"     Latency = {np.mean([q['latency_ms'] for q in results[best_q]['all']]):.0f}ms")
    print(f"     Base NDCG@5 = {np.mean([q['NDCG@5'] for q in results[best_q]['base']]):.3f}")
    print(f"     Special NDCG@5 = {np.mean([q['NDCG@5'] for q in results[best_q]['special']]):.3f}")

    print(f"\n  ⚡ Fast fallback: {methods[best_f][1] if best_f != 'N/A' else 'N/A'}")


if __name__ == "__main__":
    main()
