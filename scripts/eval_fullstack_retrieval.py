#!/usr/bin/env python3
"""
Full-stack Retrieval Evaluation: BM25 + Dense + Hybrid + Reranker.

Methods:
  A. BM25 (sparse)
  B. Dense (BGE-M3 embeddings)
  C. Hybrid RRF (Reciprocal Rank Fusion)
  D. Hybrid Weighted (BM25 + Dense weighted fusion)
  E. Hybrid + Reranker (BGE-M3 cross-encoding top-k)

Test sets:
  1. Base 20 queries (role-specific natural language)
  2. Synthetic queries from strategy corpus (60 queries, self-retrieval)
  3. Special scenarios (edge cases, adversarial, multi-intent)
"""

from __future__ import annotations

import random
import sys
import time
from typing import Dict
from typing import List

import jieba
import numpy as np
import psycopg2
from rank_bm25 import BM25Okapi

sys.path.insert(0, ".")

CONN_STR = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU_DEVICE = "cuda:3"
TOP_K_RETRIEVAL = 20  # retrieve top-20 for reranking
TOP_K_FINAL = 10  # evaluate final top-10

# ============================================================
# Data Loading
# ============================================================


def load_docs(conn_str: str = CONN_STR) -> List[Dict]:
    """Load all active strategy docs from PostgreSQL."""
    conn = psycopg2.connect(conn_str)
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score, doc_type
        FROM strategy_knowledge_docs WHERE status='active'
    """)
    docs = []
    for sit, rec, rat, role, phase, q, dt in c.fetchall():
        docs.append(
            {
                "situation": sit or "",
                "strategy": rec or "",
                "rationale": rat or "",
                "role": role or "global",
                "phase": phase or "global",
                "quality": float(q) if q else 0.8,
                "doc_type": dt or "unknown",
            }
        )
    conn.close()
    return docs


# ============================================================
# Test Sets
# ============================================================


def build_test_sets(docs: List[Dict]) -> Dict[str, List[Dict]]:
    """Build all test query sets."""

    # Set 1: Manual NL queries (20 queries)
    set1 = [
        {
            "id": "N01",
            "role": "Seer",
            "phase": "DAY_BADGE_SPEECH",
            "text": "我是预言家竞选警长需要报警徽流和查验结果",
            "keywords": ["警徽流", "警长竞选", "报查验"],
        },
        {
            "id": "N02",
            "role": "Witch",
            "phase": "NIGHT_WITCH_ACTION",
            "text": "第一晚有人被刀我要决定是否使用解药救人",
            "keywords": ["首夜解药", "解药使用", "救人"],
        },
        {
            "id": "N03",
            "role": "Werewolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "今晚狼队要选择击杀目标应该优先刀谁",
            "keywords": ["刀人优先级", "刀法", "屠边"],
        },
        {
            "id": "N04",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "我是狼人需要伪装成好人发言不能被发现",
            "keywords": ["伪装好人", "狼人伪装"],
        },
        {
            "id": "N05",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "我是平民需要给出有价值的发言分析局势",
            "keywords": ["平民发言", "发言质量"],
        },
        {
            "id": "N06",
            "role": "Hunter",
            "phase": "DAY_SPEECH",
            "text": "我被多人投票可能要出局要不要跳猎人身份",
            "keywords": ["猎人跳身份", "枪徽流"],
        },
        {
            "id": "N07",
            "role": "Seer",
            "phase": "DAY_SPEECH",
            "text": "有人对跳预言家我需要证明自己是真的",
            "keywords": ["对跳预言家", "查验链"],
        },
        {
            "id": "N08",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "我被真预言家查杀了应该怎么应对",
            "keywords": ["被查杀", "反跳预言家"],
        },
        {
            "id": "N09",
            "role": "Witch",
            "phase": "mid_game",
            "text": "第三天了我有一瓶毒药还没用应该毒谁",
            "keywords": ["毒药使用", "开毒时机"],
        },
        {
            "id": "N10",
            "role": "Guard",
            "phase": "NIGHT_GUARD_ACTION",
            "text": "今晚我要守护一个人不能连续守同一个",
            "keywords": ["守护目标", "轮换守护"],
        },
        {
            "id": "N11",
            "role": "WhiteWolfKing",
            "phase": "DAY_SPEECH",
            "text": "白狼王什么时候自爆带走关键好人最合适",
            "keywords": ["白狼王自爆", "自爆时机"],
        },
        {
            "id": "N12",
            "role": "global",
            "phase": "DAY_VOTE",
            "text": "投票环节怎样分析票型来找到狼人",
            "keywords": ["票型分析", "冲票"],
        },
        {
            "id": "N13",
            "role": "global",
            "phase": "late_game",
            "text": "残局只剩3个人怎么做出正确的投票抉择",
            "keywords": ["残局策略", "残局抉择"],
        },
        {
            "id": "N14",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "狼队友被怀疑了怎么帮他又不暴露自己",
            "keywords": ["队友被质疑", "保护队友"],
        },
        {
            "id": "N15",
            "role": "Villager",
            "phase": "DAY_VOTE",
            "text": "作为平民不确定该投谁怎么正确投票",
            "keywords": ["平民投票", "投票决定"],
        },
        {
            "id": "N16",
            "role": "global",
            "phase": "global",
            "text": "我是新手第一次玩狼人杀需要了解基础规则",
            "keywords": ["新手", "基础规则", "术语"],
        },
        {
            "id": "N17",
            "role": "Witch",
            "phase": "DAY_SPEECH",
            "text": "我救过一个人银水要不要在白天报出来",
            "keywords": ["银水", "报银水", "跳身份"],
        },
        {
            "id": "N18",
            "role": "Seer",
            "phase": "NIGHT_SEER_ACTION",
            "text": "今晚我要验一个人应该优先验谁",
            "keywords": ["查验选择", "验人优先级"],
        },
        {
            "id": "N19",
            "role": "global",
            "phase": "mid_game",
            "text": "我发现之前站错边了现在怎么纠正",
            "keywords": ["站错边", "修正判断"],
        },
        {
            "id": "N20",
            "role": "Werewolf",
            "phase": "DAY_VOTE",
            "text": "关键时刻需要和狼队友统一冲票推掉一个好人",
            "keywords": ["冲票", "统一投票", "绑票"],
        },
    ]

    # Set 2: Synthetic queries from strategy corpus (60 queries)
    # Take random situation_pattern fields as queries, the source doc is the relevance target
    set2 = []
    # Pick diverse docs across roles and types
    candidates = [d for d in docs if len(d["situation"]) >= 10 and len(d["situation"]) <= 80]
    random.seed(42)
    sampled = random.sample(candidates, min(60, len(candidates)))
    for i, d in enumerate(sampled):
        sid = f"S{i + 1:02d}"
        # Use situation text as query
        keywords = [w for w in jieba.cut(d["situation"]) if len(w) >= 2][:6]
        set2.append(
            {
                "id": sid,
                "role": d["role"],
                "phase": d["phase"],
                "text": d["situation"],
                "keywords": keywords,
                "target_situation": d["situation"],  # ground truth
            }
        )

    # Set 3: Special scenarios (20 queries)
    set3 = [
        # Edge cases
        {
            "id": "E01",
            "role": "Seer",
            "phase": "DAY_SPEECH",
            "text": "我被女巫毒了怎么办",
            "keywords": ["被毒", "出局", "遗言"],
        },
        {
            "id": "E02",
            "role": "Werewolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "只剩下我一匹狼了该怎么刀人",
            "keywords": ["最后一狼", "残局", "独狼"],
        },
        {
            "id": "E03",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "所有人都说我是狼但我真的是平民",
            "keywords": ["被冤枉", "自证清白", "表水"],
        },
        # Ambiguous queries
        {
            "id": "E04",
            "role": "global",
            "phase": "global",
            "text": "这游戏好难我不会玩",
            "keywords": ["新手", "基础", "入门"],
        },
        {
            "id": "E05",
            "role": "global",
            "phase": "global",
            "text": "怎样才能赢",
            "keywords": ["胜利条件", "获胜", "策略"],
        },
        # Multi-intent queries
        {
            "id": "E06",
            "role": "Seer",
            "phase": "DAY_BADGE_SPEECH",
            "text": "我是预言家第一天查杀了3号但现在有人对跳我该不该报警徽流怎么安排女巫工作",
            "keywords": ["对跳", "警徽流", "查杀", "女巫"],
        },
        {
            "id": "E07",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "既要伪装又要带节奏还要保护队友怎么同时做好这些",
            "keywords": ["伪装", "带节奏", "保护队友"],
        },
        # Adversarial queries
        {
            "id": "E08",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "好人应该帮狼人隐藏身份投票怎么跟票",
            "keywords": ["狼人", "伪装", "跟票", "混入"],
        },
        {
            "id": "E09",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "我听到旁边有声音这局谁是狼我心里有数",
            "keywords": ["场外", "贴脸", "违规"],
        },
        # Role-confused queries
        {
            "id": "E10",
            "role": "Witch",
            "phase": "NIGHT_WITCH_ACTION",
            "text": "我是女巫但我想当预言家那样带队可以吗",
            "keywords": ["女巫", "带队", "隐藏"],
        },
        # Very short queries
        {"id": "E11", "role": "global", "phase": "global", "text": "怎么玩", "keywords": ["新手", "入门"]},
        {"id": "E12", "role": "Werewolf", "phase": "global", "text": "自刀", "keywords": ["自刀", "狼人"]},
        # Very long queries
        {
            "id": "E13",
            "role": "global",
            "phase": "mid_game",
            "text": "第一天预言家跳了说查杀5号，5号反跳预言家说查杀8号，8号是女巫跳出来说救了3号银水，现在第二天了场上已经死了两个人分别是预言家和猎人开枪带走了9号，现在需要分析谁是狼人应该投票给谁",
            "keywords": ["对跳", "多跳", "银水", "死亡分析", "投票"],
        },
        # Non-standard role queries
        {
            "id": "E14",
            "role": "Cupid",
            "phase": "night_1",
            "text": "丘比特第一晚应该连谁比较好",
            "keywords": ["丘比特", "情侣", "连人"],
        },
        {
            "id": "E15",
            "role": "BigBadWolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "大野狼额外刀人应该怎么选目标",
            "keywords": ["大野狼", "额外刀", "双刀"],
        },
        # Meta-game queries
        {
            "id": "E16",
            "role": "global",
            "phase": "global",
            "text": "如何通过看一个人的表情和动作来判断他是不是狼",
            "keywords": ["面杀", "抿人", "微表情"],
        },
        {
            "id": "E17",
            "role": "global",
            "phase": "global",
            "text": "复盘的时候发现自己每局都犯同样的错误怎么改进",
            "keywords": ["复盘", "学习", "改进"],
        },
        # Counterfactual queries
        {
            "id": "E18",
            "role": "Witch",
            "phase": "mid_game",
            "text": "我毒错人了毒死了一个平民现在怎么办",
            "keywords": ["毒错", "救场", "补救"],
        },
        {
            "id": "E19",
            "role": "Werewolf",
            "phase": "mid_game",
            "text": "刀错人了刀到了一个平民狼刀落后了怎么翻盘",
            "keywords": ["刀错", "翻盘", "落后"],
        },
        {
            "id": "E20",
            "role": "Guard",
            "phase": "mid_game",
            "text": "守错人了守了一个狼人导致预言家被刀死了",
            "keywords": ["守错", "失误", "补救"],
        },
    ]

    return {"base": set1, "synthetic": set2, "special": set3}


# ============================================================
# Retrieval Methods
# ============================================================


class BM25Retriever:
    def __init__(self, docs: List[Dict]):
        self.docs = docs
        self.corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
        self.tokenized = [text.split() for text in self.corpus]
        self.bm25 = BM25Okapi(self.tokenized)

    def search(self, query: str, role: str = "", phase: str = "", k: int = 20) -> List[Dict]:
        tokenized = " ".join(jieba.cut(query)).split()
        scores = self.bm25.get_scores(tokenized)
        # Add role/phase bonuses
        rb = np.array([0.1 if d["role"] == role else (0.03 if d["role"] == "global" else 0) for d in self.docs])
        pb = np.array([0.05 if d["phase"] == phase else (0.02 if d["phase"] == "global" else 0) for d in self.docs])
        # Normalize BM25 scores to 0-1 range
        if scores.max() > 0:
            scores = scores / scores.max()
        scores = scores + rb + pb
        top = np.argsort(scores)[::-1][:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
                "bm25_score": float(scores[i]),
                "idx": int(i),
            }
            for i in top
        ]


class DenseRetriever:
    def __init__(self, docs: List[Dict], model_path: str = BGE_PATH, device: str = GPU_DEVICE):
        from sentence_transformers import SentenceTransformer

        self.docs = docs
        self.model = SentenceTransformer(model_path, device=device)
        texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
        self.embeddings = np.asarray(
            self.model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False),
            dtype=np.float32,
        )

    def search(self, query: str, role: str = "", phase: str = "", k: int = 20) -> List[Dict]:
        qe = np.asarray(self.model.encode(query, normalize_embeddings=True), dtype=np.float32)
        sims = np.dot(self.embeddings, qe)
        rb = np.array(
            [0.15 if d["role"] == role else (0.05 if d["role"] == "global" else 0) for d in self.docs], dtype=np.float32
        )
        pb = np.array(
            [0.08 if d["phase"] == phase else (0.03 if d["phase"] == "global" else 0) for d in self.docs],
            dtype=np.float32,
        )
        scores = sims + rb + pb
        top = np.argsort(scores)[::-1][:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
                "dense_score": float(sims[i]),
                "idx": int(i),
            }
            for i in top
        ]


class HybridRetriever:
    """Combines BM25 + Dense results via RRF or weighted fusion."""

    def __init__(self, bm25: BM25Retriever, dense: DenseRetriever, docs: List[Dict]):
        self.bm25 = bm25
        self.dense = dense
        self.docs = docs

    def search_rrf(self, query: str, role: str = "", phase: str = "", k: int = 20, rrf_k: int = 60) -> List[Dict]:
        """Reciprocal Rank Fusion."""
        bm25_results = self.bm25.search(query, role, phase, k=k)
        dense_results = self.dense.search(query, role, phase, k=k)

        # Assign ranks
        scores = {}
        for rank, r in enumerate(bm25_results, 1):
            scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0 / (rrf_k + rank)
        for rank, r in enumerate(dense_results, 1):
            scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0 / (rrf_k + rank)

        # Sort by RRF score
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
                "rrf_score": s,
                "idx": i,
            }
            for i, s in top
        ]

    def search_weighted(
        self,
        query: str,
        role: str = "",
        phase: str = "",
        k: int = 20,
        bm25_weight: float = 0.3,
        dense_weight: float = 0.7,
    ) -> List[Dict]:
        """Weighted score fusion (BM25 + Dense)."""
        bm25_results = self.bm25.search(query, role, phase, k=len(self.docs))  # get all
        dense_results = self.dense.search(query, role, phase, k=len(self.docs))

        # Build score maps
        bm25_scores = np.zeros(len(self.docs))
        for r in bm25_results:
            bm25_scores[r["idx"]] = r.get("bm25_score", 0)
        dense_scores = np.zeros(len(self.docs))
        for r in dense_results:
            dense_scores[r["idx"]] = r.get("dense_score", 0)

        # Normalize
        if bm25_scores.max() > 0:
            bm25_scores = bm25_scores / bm25_scores.max()
        if dense_scores.max() > 0:
            dense_scores = dense_scores / dense_scores.max()

        # Role/phase bonus
        rb = np.array([0.15 if d["role"] == role else (0.05 if d["role"] == "global" else 0) for d in self.docs])
        pb = np.array([0.08 if d["phase"] == phase else (0.03 if d["phase"] == "global" else 0) for d in self.docs])

        combined = bm25_weight * bm25_scores + dense_weight * dense_scores + 0.1 * rb + 0.05 * pb
        top = np.argsort(combined)[::-1][:k]
        return [
            {
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
                "hybrid_score": float(combined[i]),
                "idx": int(i),
            }
            for i in top
        ]


class Reranker:
    """BGE-M3 cross-encoding reranker: re-scores top-k candidates."""

    def __init__(self, model_path: str = BGE_PATH, device: str = GPU_DEVICE):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_path, device=device)

    def rerank(self, query: str, candidates: List[Dict], k: int = 10) -> List[Dict]:
        """Re-score candidates by encoding (query, candidate) pairs and computing similarity."""
        if not candidates:
            return []

        # Encode query + each candidate separately (simpler cross-encoding)
        q_emb = np.asarray(self.model.encode(query, normalize_embeddings=True), dtype=np.float32)
        texts = [f"{c['situation']} {c['strategy']}" for c in candidates]
        c_embs = np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)

        sims = np.dot(c_embs, q_emb)

        # Rerank
        top = np.argsort(sims)[::-1][:k]
        return [
            {
                "situation": candidates[i]["situation"],
                "strategy": candidates[i]["strategy"],
                "quality": candidates[i]["quality"],
                "rerank_score": float(sims[i]),
            }
            for i in top
        ]


# ============================================================
# Evaluation Metrics
# ============================================================


def judge_relevance(result, query) -> int:
    """Score: 2 (highly relevant), 1 (relevant), 0 (irrelevant)."""
    content = f"{result.get('situation', '')} {result.get('strategy', '')}".lower()
    kw = query.get("keywords", [])
    matches = sum(1 for k in kw if k.lower() in content)
    return 2 if matches >= 3 else (1 if matches >= 1 else 0)


def compute_metrics(results: List[Dict], query: Dict, k_vals=None) -> Dict:
    """Compute P@k, R@k, MRR, NDCG@k for a single query."""
    if k_vals is None:
        k_vals = [3, 5, 10]
    m = {"id": query["id"]}
    for k in k_vals:
        if k > len(results):
            k = len(results)
        rel = [judge_relevance(r, query) for r in results[:k]]
        m[f"P@{k}"] = sum(1 for r in rel if r > 0) / max(k, 1)
        # Recall: fraction of top-20 relevant docs captured in top-k
        all_rel_est = max(10, sum(1 for r in results[:20] if judge_relevance(r, query) > 0))
        m[f"R@{k}"] = sum(1 for r in rel if r > 0) / max(all_rel_est, 1)

    # MRR
    for rank, r in enumerate(results, 1):
        if judge_relevance(r, query) > 0:
            m["MRR"] = 1.0 / rank
            break
    else:
        m["MRR"] = 0.0

    # NDCG
    for k in k_vals:
        k_eff = min(k, len(results))
        gains = [judge_relevance(r, query) for r in results[:k_eff]]
        dcg = sum(g / np.log2(i + 2) for i, g in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(g / np.log2(i + 2) for i, g in enumerate(ideal))
        m[f"NDCG@{k}"] = dcg / idcg if idcg > 0 else 0.0

    return m


# ============================================================
# Main Evaluation
# ============================================================


def run():
    print("=" * 90)
    print("FULL-STACK RETRIEVAL EVALUATION")
    print("BM25 → Dense → Hybrid(RRF) → Hybrid(Weighted) → Reranker")
    print("=" * 90)

    # Load docs
    print("\n[0] Loading data...")
    docs = load_docs()
    print(f"  {len(docs)} docs from PostgreSQL")

    # Build test sets
    test_sets = build_test_sets(docs)
    for name, queries in test_sets.items():
        print(f"  Test set '{name}': {len(queries)} queries")

    # Build retrievers
    print("\n[1] Building BM25 retriever...")
    t0 = time.perf_counter()
    bm25 = BM25Retriever(docs)
    print(f"  BM25 built in {time.perf_counter() - t0:.1f}s")

    print("\n[2] Building Dense (BGE-M3) retriever...")
    t0 = time.perf_counter()
    dense = DenseRetriever(docs)
    print(f"  Dense built in {time.perf_counter() - t0:.1f}s")

    print("\n[3] Building Hybrid retrievers...")
    hybrid = HybridRetriever(bm25, dense, docs)

    print("\n[4] Building Reranker...")
    reranker = Reranker()

    # Define methods to evaluate
    methods = {}

    # A: BM25
    methods["A_BM25"] = lambda q: bm25.search(q["text"], q["role"], q["phase"], k=TOP_K_FINAL)

    # B: Dense
    methods["B_Dense"] = lambda q: dense.search(q["text"], q["role"], q["phase"], k=TOP_K_FINAL)

    # C: Hybrid RRF
    methods["C_Hybrid_RRF"] = lambda q: hybrid.search_rrf(q["text"], q["role"], q["phase"], k=TOP_K_FINAL)

    # D: Hybrid Weighted
    methods["D_Hybrid_Wtd"] = lambda q: hybrid.search_weighted(q["text"], q["role"], q["phase"], k=TOP_K_FINAL)

    # E: Reranked (Hybrid Weighted top-20 → rerank to 10)
    def reranked_search(q):
        candidates = hybrid.search_weighted(q["text"], q["role"], q["phase"], k=TOP_K_RETRIEVAL)
        return reranker.rerank(q["text"], candidates, k=TOP_K_FINAL)

    methods["E_Reranked"] = reranked_search

    # Run evaluation on all test sets
    all_results = {}
    for set_name, queries in test_sets.items():
        print(f"\n{'=' * 90}")
        print(f"  TEST SET: {set_name} ({len(queries)} queries)")
        print(f"{'=' * 90}")

        set_results = {}
        for method_name, method_func in methods.items():
            # Warmup
            if set_name == list(test_sets.keys())[0]:
                method_func(queries[0])

            query_metrics = []
            latencies = []
            for q in queries:
                t0 = time.perf_counter()
                results = method_func(q)
                lat = (time.perf_counter() - t0) * 1000
                latencies.append(lat)
                m = compute_metrics(results, q)
                m["latency_ms"] = lat
                m["n_results"] = len(results)
                query_metrics.append(m)

            set_results[method_name] = query_metrics

            # Print summary for this method
            agg = {k: np.mean([qm[k] for qm in query_metrics]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
            avg_lat = np.mean(latencies)
            print(
                f"  {method_name:<18s} P@5={agg['P@5']:.3f} P@10={agg['P@10']:.3f} "
                f"MRR={agg['MRR']:.3f} NDCG@5={agg['NDCG@5']:.3f} NDCG@10={agg['NDCG@10']:.3f} "
                f"lat={avg_lat:.1f}ms"
            )

        all_results[set_name] = set_results

    # ================================================================
    # Final Summary
    # ================================================================
    print(f"\n{'=' * 90}")
    print("  FINAL SUMMARY — All Test Sets Combined")
    print(f"{'=' * 90}")

    method_names = list(methods.keys())
    total_queries = sum(len(qs) for qs in test_sets.values())

    # Aggregate across all test sets
    combined = {}
    for mn in method_names:
        all_qm = []
        for set_name in test_sets:
            all_qm.extend(all_results[set_name][mn])
        combined[mn] = all_qm

    # Print header
    print(f"\n{'Method':<20}", end="")
    metrics_labels = ["P@3", "P@5", "P@10", "MRR", "NDCG@5", "NDCG@10", "latency_ms"]
    for label in metrics_labels:
        print(f" {label:>10}", end="")
    print()

    print("-" * 90)

    def best_of(key, higher_better=True):
        vals = {mn: np.mean([qm[key] for qm in combined[mn]]) for mn in method_names}
        return max(vals, key=vals.get) if higher_better else min(vals, key=vals.get)

    for mn in method_names:
        qm = combined[mn]
        agg = {k: np.mean([q[k] for q in qm]) for k in ["P@3", "P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
        agg["latency_ms"] = np.mean([q["latency_ms"] for q in qm])
        print(f"{mn:<20}", end="")
        for label in metrics_labels:
            val = agg[label]
            is_best = mn == best_of(label, higher_better=(label != "latency_ms"))
            marker = " *" if is_best else ""
            if label == "latency_ms":
                print(f" {val:>8.1f}ms{marker}", end="")
            else:
                print(f" {val:>9.3f}{marker}", end="")
        print()

    # Winner counts
    print(f"\n{'=' * 90}")
    print("  WINNER COUNTS (best in each metric)")
    print(f"{'=' * 90}")
    for label in metrics_labels:
        winner = best_of(label, higher_better=(label != "latency_ms"))
        winner_val = (
            np.mean([q[label] for q in combined[winner]])
            if label != "latency_ms"
            else np.mean([q["latency_ms"] for q in combined[winner]])
        )
        print(f"  {label:<12}: {winner:<20} = {winner_val:.3f}" + ("ms" if label == "latency_ms" else ""))

    # Per-set breakdown
    print(f"\n{'=' * 90}")
    print("  PER-SET NDCG@5 BREAKDOWN")
    print(f"{'=' * 90}")
    print(f"{'Test Set':<20} {'Queries':>8}", end="")
    for mn in method_names:
        print(f" {mn:>14}", end="")
    print()
    for set_name in test_sets:
        qs = test_sets[set_name]
        print(f"{set_name:<20} {len(qs):>8}", end="")
        for mn in method_names:
            ndcg = np.mean([qm["NDCG@5"] for qm in all_results[set_name][mn]])
            best_in_set = mn == max(
                method_names, key=lambda m: np.mean([qm["NDCG@5"] for qm in all_results[set_name][m]])
            )
            marker = " *" if best_in_set else ""
            print(f" {ndcg:>13.3f}{marker}", end="")
        print()

    # Latency breakdown
    print(f"\n{'=' * 90}")
    print("  LATENCY BREAKDOWN")
    print(f"{'=' * 90}")
    print(f"{'Method':<20} {'Mean':>10} {'P50':>10} {'P95':>10}")
    for mn in method_names:
        lats = [q["latency_ms"] for q in combined[mn]]
        print(f"{mn:<20} {np.mean(lats):>8.1f}ms {np.percentile(lats, 50):>8.1f}ms {np.percentile(lats, 95):>8.1f}ms")

    print(f"\n  Total queries evaluated: {total_queries}")
    print("  * = best method for that metric/test set")


if __name__ == "__main__":
    run()
