#!/usr/bin/env python3
"""
Optimal retrieval for AI Werewolf strategy corpus (907 Chinese docs).

Methods compared:
  A. BM25 (standalone)
  B. BGE-M3 Dense (1024-dim cosine)
  C. BGE-M3 Sparse (learned lexical weights)
  D. BGE-M3 Dense + Sparse fusion (BGE native hybrid)
  E. BM25 + BGE-M3 Dense RRF (current best)
  F. BGE-M3 Sparse + Dense RRF (all-BGE hybrid)
  G. BGE-M3 ColBERT rerank on Dense top-20 (late interaction)
  H. BGE-Reranker-v2-m3 on E (RRF) top-20 (cross-encoder, if available)

Test sets: base(20) + special(20) + synthetic(40) = 80 queries
"""

from __future__ import annotations

import os
import sys
import time

import jieba
import numpy as np
import psycopg2
from rank_bm25 import BM25Okapi

sys.path.insert(0, ".")

CONN_STR = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
RERANKER_PATH = "/home/4T-3/PLM/bge-reranker-v2-m3/"
GPU = "cuda:3"

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


def build_queries():
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
            "kw": ["平民投票", "投票"],
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
            "kw": ["最后一狼", "残局", "独狼"],
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
            "kw": ["伪装", "带节奏", "保护队友"],
        },
        {
            "id": "E08",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "好人应该帮狼人隐藏身份投票怎么跟票",
            "kw": ["狼人", "伪装", "跟票"],
        },
        {
            "id": "E09",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "我听到旁边有声音这局谁是狼我心里有数",
            "kw": ["场外", "贴脸"],
        },
        {
            "id": "E10",
            "role": "Witch",
            "phase": "NIGHT_WITCH_ACTION",
            "text": "我是女巫但我想当预言家那样带队可以吗",
            "kw": ["女巫", "带队"],
        },
        {"id": "E11", "role": "global", "phase": "global", "text": "怎么玩", "kw": ["新手", "入门"]},
        {"id": "E12", "role": "Werewolf", "phase": "global", "text": "自刀", "kw": ["自刀"]},
        {
            "id": "E13",
            "role": "global",
            "phase": "mid_game",
            "text": "预言家被刀女巫没救猎人被票带走了狼现在剩1狼2民1神怎么投",
            "kw": ["残局", "轮次"],
        },
        {
            "id": "E14",
            "role": "Cupid",
            "phase": "night_1",
            "text": "丘比特第一晚应该连谁比较好",
            "kw": ["丘比特", "情侣"],
        },
        {
            "id": "E15",
            "role": "Werewolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "大野狼额外刀人应该怎么选目标",
            "kw": ["大野狼", "双刀"],
        },
        {
            "id": "E16",
            "role": "global",
            "phase": "global",
            "text": "如何通过表情和动作判断是不是狼",
            "kw": ["面杀", "抿人"],
        },
        {
            "id": "E17",
            "role": "global",
            "phase": "global",
            "text": "复盘发现自己每局都犯同样的错误怎么改进",
            "kw": ["复盘", "学习"],
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
    return {"base": base, "special": special}


# ============================================================
# Retrievers
# ============================================================


class BM25Ret:
    def __init__(self, docs):
        self.docs = docs
        corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
        self.bm25 = BM25Okapi([t.split() for t in corpus])

    def search(self, q, role="", phase="", k=20):
        scores = self.bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if scores.max() > 0:
            scores = scores / scores.max()
        scores += np.array(
            [0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in self.docs]
        )
        scores += np.array(
            [0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in self.docs]
        )
        top = np.argsort(scores)[::-1][:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
            }
            for i in top
        ]


class BGEBase:
    """Shared BGE-M3 model for all BGE-based methods."""

    def __init__(self, docs, model_path=BGE_PATH, device=GPU):
        from FlagEmbedding import BGEM3FlagModel

        self.docs = docs
        self.model = BGEM3FlagModel(model_path, use_fp16=True, device=device)
        self.doc_texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
        # Pre-compute all representations
        t0 = time.perf_counter()
        self.dense_embs = np.zeros((len(docs), 1024), dtype=np.float32)
        self.sparse_embs = []  # List[dict]
        self.colbert_embs = []  # List[np.ndarray]
        batch_size = 64
        for i in range(0, len(docs), batch_size):
            batch = self.doc_texts[i : i + batch_size]
            out = self.model.encode(batch, return_dense=True, return_sparse=True, return_colbert_vecs=True)
            self.dense_embs[i : i + len(batch)] = out["dense_vecs"]
            self.sparse_embs.extend(out["lexical_weights"])
            self.colbert_embs.extend(out["colbert_vecs"])
        # Normalize dense
        norms = np.linalg.norm(self.dense_embs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self.dense_embs = self.dense_embs / norms
        print(
            f"  BGE pre-computed: dense={self.dense_embs.shape}, sparse={len(self.sparse_embs)}, "
            f"colbert={len(self.colbert_embs)} chunks in {time.perf_counter() - t0:.1f}s"
        )

    def encode_query(self, text):
        return self.model.encode(text, return_dense=True, return_sparse=True, return_colbert_vecs=True)

    def search_dense(self, q, k=20):
        out = self.encode_query(q["text"])
        q_dense = np.asarray(out["dense_vecs"], dtype=np.float32)
        q_dense = q_dense / np.linalg.norm(q_dense)
        sims = np.dot(self.dense_embs, q_dense)
        scores = sims + np.array(
            [0.15 if d["role"] == q["role"] else (0.05 if d["role"] == "global" else 0) for d in self.docs],
            dtype=np.float32,
        )
        scores += np.array(
            [0.08 if d["phase"] == q["phase"] else (0.03 if d["phase"] == "global" else 0) for d in self.docs],
            dtype=np.float32,
        )
        top = np.argsort(scores)[::-1][:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
                "idx": int(i),
            }
            for i in top
        ]

    def search_sparse(self, q, k=20):
        out = self.encode_query(q["text"])
        q_weights = out["lexical_weights"]
        scores = np.zeros(len(self.docs))
        for i, doc_weights in enumerate(self.sparse_embs):
            score = 0.0
            for token, qw in q_weights.items():
                if token in doc_weights:
                    score += qw * doc_weights[token]
            scores[i] = score
        if scores.max() > 0:
            scores = scores / scores.max()
        scores += np.array(
            [0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in self.docs]
        )
        scores += np.array(
            [0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in self.docs]
        )
        top = np.argsort(scores)[::-1][:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
                "idx": int(i),
            }
            for i in top
        ]

    def search_colbert_rerank(self, q, candidates_k=20, final_k=10):
        """ColBERT late interaction reranking on top of dense retrieval."""
        out = self.encode_query(q["text"])
        q_colbert = np.asarray(out["colbert_vecs"], dtype=np.float32)
        # Normalize query token vectors
        q_norms = np.linalg.norm(q_colbert, axis=1, keepdims=True)
        q_norms[q_norms == 0] = 1
        q_colbert = q_colbert / q_norms

        # Get candidates from dense search
        cand_dense = self.search_dense(q, k=candidates_k)
        cand_indices = [c["idx"] for c in cand_dense]

        # ColBERT MaxSim scoring
        scores = np.zeros(len(cand_indices))
        for j, idx in enumerate(cand_indices):
            d_colbert = np.asarray(self.colbert_embs[idx], dtype=np.float32)
            d_norms = np.linalg.norm(d_colbert, axis=1, keepdims=True)
            d_norms[d_norms == 0] = 1
            d_colbert = d_colbert / d_norms
            # MaxSim: sum over query tokens of max over doc tokens
            sim_matrix = np.dot(q_colbert, d_colbert.T)  # (Q, D)
            scores[j] = np.sum(np.max(sim_matrix, axis=1))

        # Add bonuses
        scores += np.array(
            [
                0.1 if self.docs[idx]["role"] == q["role"] else (0.03 if self.docs[idx]["role"] == "global" else 0)
                for idx in cand_indices
            ]
        )
        scores += np.array(
            [
                0.05 if self.docs[idx]["phase"] == q["phase"] else (0.02 if self.docs[idx]["phase"] == "global" else 0)
                for idx in cand_indices
            ]
        )

        top = np.argsort(scores)[::-1][:final_k]
        return [
            {
                "situation": self.docs[cand_indices[i]]["situation"],
                "strategy": self.docs[cand_indices[i]]["strategy"],
                "quality": self.docs[cand_indices[i]]["quality"],
            }
            for i in top
        ]


class HybridFusion:
    """Fuse two ranked lists via RRF or weighted fusion."""

    def __init__(self, docs):
        self.docs = docs

    def rrf(self, list_a, list_b, k=20, rrf_k=60):
        scores = {}
        for rank, r in enumerate(list_a, 1):
            idx = r.get("idx", 0)
            scores[idx] = scores.get(idx, 0) + 1.0 / (rrf_k + rank)
        for rank, r in enumerate(list_b, 1):
            idx = r.get("idx", 0)
            scores[idx] = scores.get(idx, 0) + 1.0 / (rrf_k + rank)
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
            }
            for i, _ in top
        ]

    def weighted(self, list_a, list_b, docs, w_a=0.5, w_b=0.5, k=20):
        scores = np.zeros(len(docs))
        for r in list_a:
            scores[r.get("idx", 0)] += w_a * r.get("score", 1.0 / (1 + list_a.index(r)))
        for r in list_b:
            scores[r.get("idx", 0)] += w_b * r.get("score", 1.0 / (1 + list_b.index(r)))
        top = np.argsort(scores)[::-1][:k]
        return [
            {"situation": docs[i]["situation"], "strategy": docs[i]["strategy"], "quality": docs[i]["quality"]}
            for i in top
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
        m[f"P@{k}"] = sum(1 for r in rel if r > 0) / kk
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
    print("OPTIMAL RETRIEVAL FOR AI WEREWOLF — 8 Methods Comparison")
    print("=" * 100)

    docs = load_docs()
    print(f"\n{len(docs)} strategies loaded from PostgreSQL")

    queries = build_queries()
    all_queries = queries["base"] + queries["special"]

    # Build BGE-M3 representations (once)
    print("\n[1/2] Pre-computing BGE-M3 dense + sparse + colbert...")
    bge = BGEBase(docs)

    print("\n[2/2] Building BM25...")
    bm25 = BM25Ret(docs)
    fusion = HybridFusion(docs)

    # Check if Reranker is available
    reranker_available = os.path.exists(RERANKER_PATH) and os.path.exists(f"{RERANKER_PATH}/pytorch_model.bin")
    if not reranker_available:
        reranker_available = os.path.exists(f"{RERANKER_PATH}/model.safetensors")
    if not reranker_available:
        # Try to find any checkpoint
        for f in os.listdir(RERANKER_PATH) if os.path.exists(RERANKER_PATH) else []:
            if f.endswith(".bin") or f.endswith(".safetensors"):
                reranker_available = True
                break
    print(f"  Reranker available: {reranker_available}")

    # Load reranker if available
    reranker = None
    if reranker_available:
        try:
            from FlagEmbedding import FlagReranker

            reranker = FlagReranker(RERANKER_PATH, use_fp16=True, devices=[GPU])
            print("  Reranker loaded OK")
        except Exception as e:
            print(f"  Reranker load failed: {e}")
            reranker_available = False

    # ================================================================
    # Evaluate all methods
    # ================================================================

    methods = {}

    def add_method(name, func):
        methods[name] = func

    add_method("A_BM25", lambda q: bm25.search(q, k=10))
    add_method("B_BGE_Dense", lambda q: bge.search_dense(q, k=10))
    add_method("C_BGE_Sparse", lambda q: bge.search_sparse(q, k=10))
    add_method("D_BGE_DenseSparse", lambda q: fusion.rrf(bge.search_dense(q, k=20), bge.search_sparse(q, k=20), k=10))
    add_method(
        "E_BM25+BGE_RRF",
        lambda q: fusion.rrf(
            [
                {"idx": i, "situation": r["situation"], "strategy": r["strategy"], "quality": r["quality"]}
                for i, r in enumerate(bm25.search(q, k=20))
            ],
            bge.search_dense(q, k=20),
            k=10,
        ),
    )
    add_method(
        "F_BGE_SparseDense_RRF", lambda q: fusion.rrf(bge.search_sparse(q, k=20), bge.search_dense(q, k=20), k=10)
    )
    add_method("G_ColBERT_Rerank", lambda q: bge.search_colbert_rerank(q, candidates_k=20, final_k=10))

    # Reranker method (if available)
    if reranker_available:

        def reranked_search(q):
            # Stage 1: Hybrid RRF (BM25 + Dense)
            b_results = bm25.search(q, k=20)
            d_results = bge.search_dense(q, k=20)
            candidates = fusion.rrf(
                [
                    {"idx": i, "situation": r["situation"], "strategy": r["strategy"], "quality": r["quality"]}
                    for i, r in enumerate(b_results)
                ],
                d_results,
                k=20,
            )
            # Stage 2: BGE-Reranker cross-encoding
            pairs = [(q["text"], f"{c['situation']} {c['strategy']}") for c in candidates]
            scores = reranker.compute_score(pairs, normalize=True)
            if isinstance(scores, float):
                scores = [scores]
            top = np.argsort(np.array(scores))[::-1][:10]
            return [candidates[i] for i in top]

        add_method("H_Reranker_on_RRF", reranked_search)

    # Run evaluation
    results = {}
    for mname, mfunc in methods.items():
        metrics = []
        lats = []
        for q in all_queries:
            t0 = time.perf_counter()
            res = mfunc(q)
            lat = (time.perf_counter() - t0) * 1000
            lats.append(lat)
            m = evaluate(res, q)
            m["latency_ms"] = lat
            metrics.append(m)

        # Also compute per-set metrics
        base_metrics = metrics[:20]
        spec_metrics = metrics[20:]
        results[mname] = {
            "all": metrics,
            "base": base_metrics,
            "special": spec_metrics,
        }

        agg_all = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
        agg_base = {k: np.mean([qm[k] for qm in base_metrics]) for k in ["P@5", "NDCG@5"]}
        agg_spec = {k: np.mean([qm[k] for qm in spec_metrics]) for k in ["P@5", "NDCG@5"]}
        print(f"\n{mname}:")
        print(
            f"  ALL:    P@5={agg_all['P@5']:.3f} P@10={agg_all['P@10']:.3f} MRR={agg_all['MRR']:.3f} "
            f"NDCG@5={agg_all['NDCG@5']:.3f} NDCG@10={agg_all['NDCG@10']:.3f} lat={np.mean(lats):.0f}ms"
        )
        print(f"  BASE:   P@5={agg_base['P@5']:.3f} NDCG@5={agg_base['NDCG@5']:.3f}")
        print(f"  SPEC:   P@5={agg_spec['P@5']:.3f} NDCG@5={agg_spec['NDCG@5']:.3f}")

    # ================================================================
    # Grand Summary Table
    # ================================================================
    print(f"\n{'=' * 100}")
    print("GRAND SUMMARY — 40 queries (20 base + 20 special)")
    print(f"{'=' * 100}")

    metric_keys = ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10", "latency_ms"]
    print(f"\n{'Method':<28}", end="")
    for mk in metric_keys:
        print(f" {mk:>10}", end="")
    print(f" {'Base NDCG':>10} {'Spec NDCG':>10}")
    print("-" * 100)

    def best_of(metric_name, higher=True):
        vals = {mn: np.mean([q[metric_name] for q in results[mn]["all"]]) for mn in methods}
        return max(vals, key=vals.get) if higher else min(vals, key=vals.get)

    for mname in methods:
        agg = {mk: np.mean([q[mk] for q in results[mname]["all"]]) for mk in metric_keys}
        base_ndcg = np.mean([q["NDCG@5"] for q in results[mname]["base"]])
        spec_ndcg = np.mean([q["NDCG@5"] for q in results[mname]["special"]])
        print(f"{mname:<28}", end="")
        for mk in metric_keys:
            is_b = mname == best_of(mk, higher=(mk != "latency_ms"))
            if mk == "latency_ms":
                print(f" {agg[mk]:>8.0f}ms{'*' if is_b else ' '}", end="")
            else:
                print(f" {agg[mk]:>9.3f}{'*' if is_b else ' '}", end="")
        print(f" {base_ndcg:>10.3f} {spec_ndcg:>10.3f}")

    # Winner counts
    print(f"\n{'=' * 100}")
    print("WINNER PER METRIC:")
    for mk in metric_keys + ["Base_NDCG", "Spec_NDCG"]:
        if mk.startswith("Base"):
            w = max(methods, key=lambda m: np.mean([q["NDCG@5"] for q in results[m]["base"]]))
            v = np.mean([q["NDCG@5"] for q in results[w]["base"]])
        elif mk.startswith("Spec"):
            w = max(methods, key=lambda m: np.mean([q["NDCG@5"] for q in results[m]["special"]]))
            v = np.mean([q["NDCG@5"] for q in results[w]["special"]])
        else:
            w = best_of(mk, higher=(mk != "latency_ms"))
            v = np.mean([q[mk] for q in results[w]["all"]])
        print(f"  {mk:<15}: {w:<30} = {v:.3f}" + ("ms" if "latency" in mk else ""))

    # Final recommendation
    print(f"\n{'=' * 100}")
    print("RECOMMENDATION:")
    print(f"{'=' * 100}")

    # Find the best method for quality (highest NDCG@5) under 50ms latency constraint
    candidates_quality = {
        mn: np.mean([q["NDCG@5"] for q in results[mn]["all"]])
        for mn in methods
        if np.mean([q["latency_ms"] for q in results[mn]["all"]]) < 50
    }
    best_quality = max(candidates_quality, key=candidates_quality.get)

    # Find the fastest method with NDCG@5 > 0.80
    candidates_fast = {
        mn: np.mean([q["latency_ms"] for q in results[mn]["all"]])
        for mn in methods
        if np.mean([q["NDCG@5"] for q in results[mn]["all"]]) > 0.80
    }
    best_fast = min(candidates_fast, key=candidates_fast.get)

    # Best overall (NDCG@5 per ms of latency)
    efficiency = {
        mn: np.mean([q["NDCG@5"] for q in results[mn]["all"]])
        / max(np.mean([q["latency_ms"] for q in results[mn]["all"]]), 0.1)
        for mn in methods
    }
    best_efficient = max(efficiency, key=efficiency.get)

    print(f"  Best quality (NDCG@5, <50ms):   {best_quality}")
    print(f"  Fastest good (NDCG@5>0.80):      {best_fast}")
    print(f"  Most efficient (NDCG/ms):         {best_efficient}")

    # Print top-3 ranking by NDCG@5
    ranked = sorted(methods.keys(), key=lambda m: np.mean([q["NDCG@5"] for q in results[m]["all"]]), reverse=True)
    print("\n  Top-3 by NDCG@5:")
    for i, m in enumerate(ranked[:3], 1):
        ndcg = np.mean([q["NDCG@5"] for q in results[m]["all"]])
        lat = np.mean([q["latency_ms"] for q in results[m]["all"]])
        base_n = np.mean([q["NDCG@5"] for q in results[m]["base"]])
        spec_n = np.mean([q["NDCG@5"] for q in results[m]["special"]])
        print(f"    {i}. {m:<28} NDCG@5={ndcg:.3f}  lat={lat:.0f}ms  base={base_n:.3f}  spec={spec_n:.3f}")


if __name__ == "__main__":
    main()
