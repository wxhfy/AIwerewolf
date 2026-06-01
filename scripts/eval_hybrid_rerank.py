#!/usr/bin/env python3
"""
Proper Hybrid + Reranker evaluation.

Pipeline:
  Stage 1: BM25 + Dense → RRF fusion → top-20 candidates
  Stage 2: BGE-M3 instruction-tuned reranking + keyword boost → top-10

Compares:
  A. BM25 standalone
  B. Dense (BGE-M3) standalone
  C. Hybrid RRF = BM25 + Dense RRF fusion
  D. Hybrid RRF + Reranker = Hybrid RRF top-20 → rerank to top-10
"""

from __future__ import annotations

import json, sys, time, random
from typing import Any, Dict, List

import numpy as np
import jieba
import psycopg2
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

sys.path.insert(0, ".")

CONN_STR = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
RRF_K = 60

# ============================================================
# Test Data
# ============================================================

TEST_SETS = {}

# Set 1: Natural language queries (20)
TEST_SETS["base"] = [
    {"id": "N01", "role": "Seer", "phase": "DAY_BADGE_SPEECH", "text": "我是预言家竞选警长需要报警徽流和查验结果", "kw": ["警徽流", "警长竞选", "报查验"]},
    {"id": "N02", "role": "Witch", "phase": "NIGHT_WITCH_ACTION", "text": "第一晚有人被刀我要决定是否使用解药救人", "kw": ["首夜解药", "解药使用", "救人"]},
    {"id": "N03", "role": "Werewolf", "phase": "NIGHT_WOLF_ACTION", "text": "今晚狼队要选择击杀目标应该优先刀谁", "kw": ["刀人优先级", "刀法", "屠边"]},
    {"id": "N04", "role": "Werewolf", "phase": "DAY_SPEECH", "text": "我是狼人需要伪装成好人发言不能被发现", "kw": ["伪装好人", "狼人伪装", "隐藏"]},
    {"id": "N05", "role": "Villager", "phase": "DAY_SPEECH", "text": "我是平民需要给出有价值的发言分析局势", "kw": ["平民发言", "发言质量"]},
    {"id": "N06", "role": "Hunter", "phase": "DAY_SPEECH", "text": "我被多人投票可能要出局要不要跳猎人身份", "kw": ["猎人跳身份", "枪徽流", "被票"]},
    {"id": "N07", "role": "Seer", "phase": "DAY_SPEECH", "text": "有人对跳预言家我需要证明自己是真的", "kw": ["对跳预言家", "查验链"]},
    {"id": "N08", "role": "Werewolf", "phase": "DAY_SPEECH", "text": "我被真预言家查杀了应该怎么应对", "kw": ["被查杀", "反跳预言家"]},
    {"id": "N09", "role": "Witch", "phase": "mid_game", "text": "第三天了我有一瓶毒药还没用应该毒谁", "kw": ["毒药使用", "开毒时机"]},
    {"id": "N10", "role": "Guard", "phase": "NIGHT_GUARD_ACTION", "text": "今晚我要守护一个人不能连续守同一个", "kw": ["守护目标", "轮换守护"]},
    {"id": "N11", "role": "WhiteWolfKing", "phase": "DAY_SPEECH", "text": "白狼王什么时候自爆带走关键好人最合适", "kw": ["白狼王自爆", "自爆时机"]},
    {"id": "N12", "role": "global", "phase": "DAY_VOTE", "text": "投票环节怎样分析票型来找到狼人", "kw": ["票型分析", "冲票", "跟票"]},
    {"id": "N13", "role": "global", "phase": "late_game", "text": "残局只剩3个人怎么做出正确的投票抉择", "kw": ["残局策略", "残局抉择"]},
    {"id": "N14", "role": "Werewolf", "phase": "DAY_SPEECH", "text": "狼队友被怀疑了怎么帮他又不暴露自己", "kw": ["队友被质疑", "保护队友"]},
    {"id": "N15", "role": "Villager", "phase": "DAY_VOTE", "text": "作为平民不确定该投谁怎么正确投票", "kw": ["平民投票", "投票决定"]},
    {"id": "N16", "role": "global", "phase": "global", "text": "我是新手第一次玩狼人杀需要了解基础规则", "kw": ["新手", "基础规则", "术语"]},
    {"id": "N17", "role": "Witch", "phase": "DAY_SPEECH", "text": "我救过一个人银水要不要在白天报出来", "kw": ["银水", "报银水"]},
    {"id": "N18", "role": "Seer", "phase": "NIGHT_SEER_ACTION", "text": "今晚我要验一个人应该优先验谁", "kw": ["查验选择", "验人优先级"]},
    {"id": "N19", "role": "global", "phase": "mid_game", "text": "我发现之前站错边了现在怎么纠正", "kw": ["站错边", "修正判断"]},
    {"id": "N20", "role": "Werewolf", "phase": "DAY_VOTE", "text": "关键时刻需要和狼队友统一冲票推掉一个好人", "kw": ["冲票", "统一投票", "绑票"]},
]

# Set 2: Special scenarios (20)
TEST_SETS["special"] = [
    {"id": "E01", "role": "Seer", "phase": "DAY_SPEECH", "text": "我被女巫毒了怎么办", "kw": ["被毒", "出局", "遗言"]},
    {"id": "E02", "role": "Werewolf", "phase": "NIGHT_WOLF_ACTION", "text": "只剩下我一匹狼了该怎么刀人", "kw": ["最后一狼", "残局", "独狼"]},
    {"id": "E03", "role": "Villager", "phase": "DAY_SPEECH", "text": "所有人都说我是狼但我真的是平民", "kw": ["被冤枉", "自证清白", "表水"]},
    {"id": "E04", "role": "global", "phase": "global", "text": "这游戏好难我不会玩怎么办", "kw": ["新手", "基础", "入门"]},
    {"id": "E05", "role": "global", "phase": "global", "text": "怎样才能赢", "kw": ["胜利条件", "获胜", "策略"]},
    {"id": "E06", "role": "Seer", "phase": "DAY_BADGE_SPEECH", "text": "我是预言家有查杀但对跳也出现了警徽流怎么安排女巫工作", "kw": ["对跳", "警徽流", "查杀", "女巫"]},
    {"id": "E07", "role": "Werewolf", "phase": "DAY_SPEECH", "text": "既要伪装又要带节奏还要保护队友怎么同时做好这些", "kw": ["伪装", "带节奏", "保护队友"]},
    {"id": "E08", "role": "Werewolf", "phase": "DAY_SPEECH", "text": "好人应该帮狼人隐藏身份投票怎么跟票", "kw": ["狼人", "伪装", "跟票"]},
    {"id": "E09", "role": "Villager", "phase": "DAY_SPEECH", "text": "我听到旁边有声音这局谁是狼我心里有数", "kw": ["场外", "贴脸"]},
    {"id": "E10", "role": "Witch", "phase": "NIGHT_WITCH_ACTION", "text": "我是女巫但我想当预言家那样带队可以吗", "kw": ["女巫", "带队"]},
    {"id": "E11", "role": "global", "phase": "global", "text": "怎么玩", "kw": ["新手", "入门"]},
    {"id": "E12", "role": "Werewolf", "phase": "global", "text": "自刀", "kw": ["自刀", "狼人"]},
    {"id": "E13", "role": "global", "phase": "mid_game", "text": "预言家被刀女巫没救猎人被票开枪带走了狼现在场上剩1狼2民1神怎么投", "kw": ["残局", "轮次", "投票"]},
    {"id": "E14", "role": "Cupid", "phase": "night_1", "text": "丘比特第一晚应该连谁比较好", "kw": ["丘比特", "情侣", "连人"]},
    {"id": "E15", "role": "Werewolf", "phase": "NIGHT_WOLF_ACTION", "text": "大野狼额外刀人应该怎么选目标", "kw": ["大野狼", "额外刀", "双刀"]},
    {"id": "E16", "role": "global", "phase": "global", "text": "如何通过看一个人的表情和动作来判断他是不是狼", "kw": ["面杀", "抿人", "微表情"]},
    {"id": "E17", "role": "global", "phase": "global", "text": "复盘发现自己每局都犯同样的错误怎么改进", "kw": ["复盘", "学习", "改进"]},
    {"id": "E18", "role": "Witch", "phase": "mid_game", "text": "我毒错人了毒死了一个平民现在怎么办", "kw": ["毒错", "救场", "补救"]},
    {"id": "E19", "role": "Werewolf", "phase": "mid_game", "text": "刀错人了刀到了平民狼刀落后怎么翻盘", "kw": ["刀错", "翻盘", "落后"]},
    {"id": "E20", "role": "Guard", "phase": "mid_game", "text": "守错人了守了一个狼人导致预言家被刀死了", "kw": ["守错", "失误"]},
]

# Set 3: Synthetic self-retrieval (40 queries, sampled)
random.seed(42)


def load_docs():
    conn = psycopg2.connect(CONN_STR)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score, doc_type
               FROM strategy_knowledge_docs WHERE status='active'""")
    docs = []
    for sit, rec, rat, role, phase, q, dt in c.fetchall():
        docs.append({"situation": sit or "", "strategy": rec or "", "rationale": rat or "",
                     "role": role or "global", "phase": phase or "global",
                     "quality": float(q) if q else 0.8, "doc_type": dt or ""})
    conn.close()
    return docs


# ============================================================
# Retrievers
# ============================================================

class BM25Searcher:
    def __init__(self, docs):
        self.docs = docs
        self.corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
        self.bm25 = BM25Okapi([t.split() for t in self.corpus])

    def search(self, query, role="", phase="", k=20):
        scores = self.bm25.get_scores(" ".join(jieba.cut(query)).split())
        if scores.max() > 0:
            scores = scores / scores.max()
        scores = scores + np.array([0.1 if d["role"]==role else (0.03 if d["role"]=="global" else 0) for d in self.docs])
        scores = scores + np.array([0.05 if d["phase"]==phase else (0.02 if d["phase"]=="global" else 0) for d in self.docs])
        top = np.argsort(scores)[::-1][:k]
        return [{"idx": int(i), "bm25_score": float(scores[i]),
                 "situation": self.docs[i]["situation"], "strategy": self.docs[i]["strategy"],
                 "quality": self.docs[i]["quality"]} for i in top]


class DenseSearcher:
    def __init__(self, docs, model_path=BGE_PATH, device=GPU):
        self.docs = docs
        self.model = SentenceTransformer(model_path, device=device)
        texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
        self.embs = np.asarray(self.model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32)

    def search(self, query, role="", phase="", k=20):
        qe = np.asarray(self.model.encode(query, normalize_embeddings=True), dtype=np.float32)
        sims = np.dot(self.embs, qe)
        scores = sims + np.array([0.15 if d["role"]==role else (0.05 if d["role"]=="global" else 0) for d in self.docs], dtype=np.float32)
        scores = scores + np.array([0.08 if d["phase"]==phase else (0.03 if d["phase"]=="global" else 0) for d in self.docs], dtype=np.float32)
        top = np.argsort(scores)[::-1][:k]
        return [{"idx": int(i), "dense_score": float(sims[i]),
                 "situation": self.docs[i]["situation"], "strategy": self.docs[i]["strategy"],
                 "quality": self.docs[i]["quality"]} for i in top]


class HybridRRF:
    """BM25 + Dense → Reciprocal Rank Fusion"""
    def __init__(self, bm25, dense, docs):
        self.bm25 = bm25
        self.dense = dense
        self.docs = docs

    def search(self, query, role="", phase="", k=20):
        b_res = self.bm25.search(query, role, phase, k=k)
        d_res = self.dense.search(query, role, phase, k=k)

        scores = {}
        for rank, r in enumerate(b_res, 1):
            scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0/(RRF_K+rank)
        for rank, r in enumerate(d_res, 1):
            scores[r["idx"]] = scores.get(r["idx"], 0) + 1.0/(RRF_K+rank)

        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        return [{"idx": i, "rrf_score": s,
                 "situation": self.docs[i]["situation"], "strategy": self.docs[i]["strategy"],
                 "quality": self.docs[i]["quality"]} for i, s in top]


class BGEReranker:
    """Instruction-tuned BGE-M3 reranker on top of Hybrid RRF candidates.

    Uses BGE-M3 with passage-ranking instruction prefix for
    finer-grained relevance scoring on the top-k candidate pool.
    """
    def __init__(self, model_path=BGE_PATH, device=GPU):
        self.model = SentenceTransformer(model_path, device=device)
        # Pre-compute "relevance" direction for scoring
        self._rel_vec = self.model.encode("该策略与查询高度相关", normalize_embeddings=True)

    def rerank(self, query, candidates, k=10):
        if not candidates:
            return []

        # Method: Instruction-tuned query encoding + candidate encoding
        # BGE-M3 supports instruction prefix for passage retrieval
        q_inst = f"为这个查询检索相关策略：{query}"
        q_emb = np.asarray(self.model.encode(q_inst, normalize_embeddings=True), dtype=np.float32)

        texts = [f"{c['situation']} {c['strategy']}" for c in candidates]
        c_embs = np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)

        # Semantic similarity
        sim_scores = np.dot(c_embs, q_emb)

        # Keyword overlap boost (BM25-like on rerank pool)
        q_words = set(jieba.cut(query))
        kw_scores = np.zeros(len(candidates))
        for i, c in enumerate(candidates):
            c_words = set(jieba.cut(f"{c['situation']} {c['strategy']}"))
            overlap = len(q_words & c_words)
            kw_scores[i] = min(overlap / max(len(q_words), 1), 1.0)

        # Quality boost
        q_scores = np.array([c.get("quality", 0.8) for c in candidates])

        # Final score: 0.6 semantic + 0.25 keyword + 0.15 quality
        final = 0.6 * sim_scores + 0.25 * kw_scores + 0.15 * q_scores
        top = np.argsort(final)[::-1][:k]
        return [{"situation": candidates[i]["situation"], "strategy": candidates[i]["strategy"],
                 "quality": candidates[i]["quality"], "rerank_score": float(final[i])}
                for i in top]


# ============================================================
# Metrics
# ============================================================

def relevance(result, query, level=1):
    content = f"{result.get('situation','')} {result.get('strategy','')}".lower()
    kw = query.get("kw", [])
    matches = sum(1 for k in kw if k.lower() in content)
    return 2 if matches >= 3 else (1 if matches >= 1 else 0)


def evaluate(results, query):
    if not results:
        return {"P@5": 0, "P@10": 0, "MRR": 0, "NDCG@5": 0, "NDCG@10": 0}

    m = {}
    for k in [5, 10]:
        k_eff = min(k, len(results))
        rel = [relevance(r, query) for r in results[:k_eff]]
        m[f"P@{k}"] = sum(1 for r in rel if r > 0) / k_eff

    for rank, r in enumerate(results, 1):
        if relevance(r, query) > 0:
            m["MRR"] = 1.0 / rank
            break
    else:
        m["MRR"] = 0.0

    for k in [5, 10]:
        k_eff = min(k, len(results))
        gains = [relevance(r, query) for r in results[:k_eff]]
        dcg = sum(g / np.log2(i+2) for i, g in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(g / np.log2(i+2) for i, g in enumerate(ideal))
        m[f"NDCG@{k}"] = dcg / idcg if idcg > 0 else 0.0

    return m


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 94)
    print("Hybrid RRF + Reranker Evaluation")
    print("=" * 94)

    docs = load_docs()
    print(f"\n{len(docs)} strategies loaded from PostgreSQL")

    # Build synthetic test set from docs
    candidates = [d for d in docs if 10 <= len(d["situation"]) <= 80]
    sampled = random.sample(candidates, min(40, len(candidates)))
    synthetic = []
    for i, d in enumerate(sampled):
        synthetic.append({
            "id": f"S{i+1:02d}", "role": d["role"], "phase": d["phase"],
            "text": d["situation"],
            "kw": [w for w in jieba.cut(d["situation"]) if len(w) >= 2][:6],
        })
    TEST_SETS["synthetic"] = synthetic

    # Build all retrievers
    print("\n[1/4] Building BM25...")
    t0 = time.perf_counter()
    bm25 = BM25Searcher(docs)
    print(f"  Done in {time.perf_counter()-t0:.1f}s")

    print("[2/4] Building Dense (BGE-M3)...")
    t0 = time.perf_counter()
    dense = DenseSearcher(docs)
    print(f"  Done in {time.perf_counter()-t0:.1f}s")

    print("[3/4] Building Hybrid RRF...")
    hybrid = HybridRRF(bm25, dense, docs)

    print("[4/4] Building Reranker...")
    reranker = BGEReranker()

    # Methods to test
    methods = {
        "A_BM25": ("BM25", lambda q: bm25.search(q["text"], q["role"], q["phase"], k=10)),
        "B_Dense": ("Dense(BGE)", lambda q: dense.search(q["text"], q["role"], q["phase"], k=10)),
        "C_Hybrid_RRF": ("Hybrid RRF", lambda q: hybrid.search(q["text"], q["role"], q["phase"], k=10)),
        "D_Hybrid_RRF+Rerank": ("RRF+Rerank",
            lambda q: reranker.rerank(q["text"],
                hybrid.search(q["text"], q["role"], q["phase"], k=20), k=10)),
    }

    # Run
    all_results = {}
    for set_name, queries in TEST_SETS.items():
        print(f"\n{'='*94}")
        print(f"  {set_name.upper()} ({len(queries)} queries)")
        print(f"{'='*94}")

        set_res = {}
        for mname, (mlabel, mfunc) in methods.items():
            metrics = []
            lats = []
            for q in queries:
                t0 = time.perf_counter()
                results = mfunc(q)
                lat = (time.perf_counter() - t0) * 1000
                lats.append(lat)
                m = evaluate(results, q)
                m["latency_ms"] = lat
                metrics.append(m)

            set_res[mname] = metrics
            agg = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
            print(f"  {mlabel:<22s} P@5={agg['P@5']:.3f}  P@10={agg['P@10']:.3f}  "
                  f"MRR={agg['MRR']:.3f}  NDCG@5={agg['NDCG@5']:.3f}  NDCG@10={agg['NDCG@10']:.3f}  "
                  f"lat={np.mean(lats):.0f}ms")
        all_results[set_name] = set_res

    # Grand summary
    print(f"\n{'='*94}")
    print(f"  GRAND SUMMARY — {sum(len(q) for q in TEST_SETS.values())} total queries")
    print(f"{'='*94}")

    combined = {}
    for mname in methods:
        combined[mname] = []
        for set_name in TEST_SETS:
            combined[mname].extend(all_results[set_name][mname])

    method_labels = {k: v[0] for k, v in methods.items()}
    metric_keys = ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10", "latency_ms"]

    # Header
    print(f"\n{'Method':<24}", end="")
    for mk in metric_keys:
        print(f" {mk:>10}", end="")
    print()

    print("-" * 94)

    def best(name, higher=True):
        vals = {mn: np.mean([q[name] for q in combined[mn]]) for mn in methods}
        return max(vals, key=vals.get) if higher else min(vals, key=vals.get)

    for mname, mlabel in method_labels.items():
        agg = {mk: np.mean([q[mk] for q in combined[mname]]) for mk in metric_keys}
        print(f"{mlabel:<24}", end="")
        for mk in metric_keys:
            is_b = mname == best(mk, higher=(mk != "latency_ms"))
            if mk == "latency_ms":
                print(f" {agg[mk]:>8.0f}ms{' *' if is_b else '  '}", end="")
            else:
                print(f" {agg[mk]:>9.3f}{' *' if is_b else '  '}", end="")
        print()

    # D vs C improvement
    print(f"\n{'='*94}")
    print("  RERANKER IMPACT (D vs C):")
    print(f"{'='*94}")
    print(f"{'Test Set':<20} {'C NDCG@5':>10} {'D NDCG@5':>10} {'Delta':>10}")
    for set_name in TEST_SETS:
        c_ndcg = np.mean([q["NDCG@5"] for q in all_results[set_name]["C_Hybrid_RRF"]])
        d_ndcg = np.mean([q["NDCG@5"] for q in all_results[set_name]["D_Hybrid_RRF+Rerank"]])
        delta = d_ndcg - c_ndcg
        sign = "+" if delta > 0 else ""
        print(f"  {set_name:<20} {c_ndcg:>10.3f} {d_ndcg:>10.3f} {sign}{delta:>9.3f}")

    overall_c = np.mean([q["NDCG@5"] for q in combined["C_Hybrid_RRF"]])
    overall_d = np.mean([q["NDCG@5"] for q in combined["D_Hybrid_RRF+Rerank"]])
    print(f"  {'OVERALL':<20} {overall_c:>10.3f} {overall_d:>10.3f} {'+' if overall_d>overall_c else ''}{overall_d-overall_c:>9.3f}")

    # Winner counts
    print(f"\n{'='*94}")
    print("  WINNER COUNTS (best in each metric):")
    print(f"{'='*94}")
    for mk in metric_keys:
        w = best(mk, higher=(mk != "latency_ms"))
        val = np.mean([q[mk] for q in combined[w]])
        print(f"  {mk:<12}: {method_labels[w]:<24} = {val:.3f}" + ("ms" if mk == "latency_ms" else ""))

    # Per-query detail for interesting queries
    print(f"\n{'='*94}")
    print("  PER-QUERY P@5 — SPECIAL SCENARIOS:")
    print(f"{'='*94}")
    print(f"{'ID':<6} {'Query':<45} {'BM25':>6} {'Dense':>6} {'RRF':>6} {'+Rerank':>8}")
    for q in TEST_SETS["special"]:
        vals = {}
        for mname in methods:
            qm = [qm for qm in all_results["special"][mname] if True][TEST_SETS["special"].index(q)]
            vals[mname] = qm["P@5"] if hasattr(qm, '__iter__') else 0
        # Actually let me just recompute
        pass

    # Print special set per-query differently
    special_queries = TEST_SETS["special"]
    for i, q in enumerate(special_queries):
        pa = all_results["special"]["A_BM25"][i]["P@5"]
        pb = all_results["special"]["B_Dense"][i]["P@5"]
        pc = all_results["special"]["C_Hybrid_RRF"][i]["P@5"]
        pd = all_results["special"]["D_Hybrid_RRF+Rerank"][i]["P@5"]
        best_val = max(pa, pb, pc, pd)
        markers = ["*" if v == best_val else " " for v in [pa, pb, pc, pd]]
        text = q["text"][:42]
        print(f"  {q['id']:<6} {text:<45} {pa:>5.2f}{markers[0]} {pb:>5.2f}{markers[1]} {pc:>5.2f}{markers[2]} {pd:>5.2f}{markers[3]}")


if __name__ == "__main__":
    main()
