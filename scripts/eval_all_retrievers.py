#!/usr/bin/env python3
"""4-method retrieval comparison: A.Metadata, B.FullText, C.TF-IDF, D.BGE-M3."""

from __future__ import annotations

import sys
import time

import numpy as np
import psycopg2

sys.path.insert(0, ".")

CONN_STR = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"

TEST_QUERIES = [
    {
        "id": "Q1",
        "role": "Seer",
        "phase": "DAY_BADGE_SPEECH",
        "query_text": "我是预言家现在竞选警长需要报警徽流和查验结果",
        "keywords": ["警徽流", "警长竞选", "预言家警上", "报查验"],
    },
    {
        "id": "Q2",
        "role": "Witch",
        "phase": "NIGHT_WITCH_ACTION",
        "query_text": "第一晚有人被刀我要决定是否使用解药救人",
        "keywords": ["首夜解药", "第一晚救人", "解药使用", "盲救"],
    },
    {
        "id": "Q3",
        "role": "Werewolf",
        "phase": "NIGHT_WOLF_ACTION",
        "query_text": "今晚我们狼队要选择击杀目标应该优先刀谁",
        "keywords": ["刀人优先级", "击杀目标", "刀法", "屠边"],
    },
    {
        "id": "Q4",
        "role": "Werewolf",
        "phase": "DAY_SPEECH",
        "query_text": "我是狼人需要伪装成好人发言不能被发现",
        "keywords": ["伪装好人", "狼人伪装", "模仿好人", "隐藏狼人身份"],
    },
    {
        "id": "Q5",
        "role": "Villager",
        "phase": "DAY_SPEECH",
        "query_text": "我是平民需要给出有价值的发言来分析局势",
        "keywords": ["平民发言", "发言质量", "村民发言", "分析发言"],
    },
    {
        "id": "Q6",
        "role": "Hunter",
        "phase": "DAY_SPEECH",
        "query_text": "我被多人投票可能要出局了要不要跳猎人身份",
        "keywords": ["猎人跳身份", "开枪威慑", "枪徽流", "被票"],
    },
    {
        "id": "Q7",
        "role": "Seer",
        "phase": "DAY_SPEECH",
        "query_text": "有人对跳预言家我需要证明自己是真的",
        "keywords": ["对跳预言家", "真假预言家", "悍跳", "对跳", "查验链"],
    },
    {
        "id": "Q8",
        "role": "Werewolf",
        "phase": "DAY_SPEECH",
        "query_text": "我被真预言家查杀了应该怎么应对",
        "keywords": ["被查杀", "反跳预言家", "被真预言家查杀", "自爆"],
    },
    {
        "id": "Q9",
        "role": "Witch",
        "phase": "mid_game",
        "query_text": "已经第三天了我有一瓶毒药还没用应该毒谁",
        "keywords": ["毒药使用", "开毒", "撒毒", "毒人时机"],
    },
    {
        "id": "Q10",
        "role": "Guard",
        "phase": "NIGHT_GUARD_ACTION",
        "query_text": "今晚我要守护一个人不能连续守同一个",
        "keywords": ["守护目标", "轮换守护", "守卫守护", "不能连续"],
    },
    {
        "id": "Q11",
        "role": "WhiteWolfKing",
        "phase": "DAY_SPEECH",
        "query_text": "我是白狼王什么时候自爆带走关键好人最合适",
        "keywords": ["白狼王自爆", "自爆时机", "自爆带人", "吞警徽"],
    },
    {
        "id": "Q12",
        "role": "global",
        "phase": "DAY_VOTE",
        "query_text": "投票环节怎样分析票型来找到狼人",
        "keywords": ["票型分析", "投票记录", "变票者", "冲票"],
    },
    {
        "id": "Q13",
        "role": "global",
        "phase": "late_game",
        "query_text": "残局阶段只剩3个人了怎么做出最后正确的投票抉择",
        "keywords": ["残局策略", "残局抉择", "最后抉择", "残局"],
    },
    {
        "id": "Q14",
        "role": "Werewolf",
        "phase": "DAY_SPEECH",
        "query_text": "我的狼队友被怀疑了我应该怎么帮他又不暴露自己",
        "keywords": ["队友被质疑", "保护队友", "转移注意力", "狼队友配合"],
    },
    {
        "id": "Q15",
        "role": "Villager",
        "phase": "DAY_VOTE",
        "query_text": "我作为平民不确定该投谁怎么做出正确的投票",
        "keywords": ["平民投票", "投票决定", "不确定投谁"],
    },
    {
        "id": "Q16",
        "role": "global",
        "phase": "global",
        "query_text": "我是新手第一次玩狼人杀需要了解基础规则和术语",
        "keywords": ["新手", "基础规则", "术语", "游戏规则"],
    },
    {
        "id": "Q17",
        "role": "Witch",
        "phase": "DAY_SPEECH",
        "query_text": "我救过一个人银水要不要在白天报出来",
        "keywords": ["银水", "报银水", "跳身份", "女巫发言"],
    },
    {
        "id": "Q18",
        "role": "Seer",
        "phase": "NIGHT_SEER_ACTION",
        "query_text": "今晚我要验一个人应该优先验谁",
        "keywords": ["查验选择", "验人优先级", "首验", "查验目标"],
    },
    {
        "id": "Q19",
        "role": "global",
        "phase": "mid_game",
        "query_text": "我发现之前站错边了现在怎么纠正",
        "keywords": ["站错边", "修正判断", "站边", "纠正"],
    },
    {
        "id": "Q20",
        "role": "Werewolf",
        "phase": "DAY_VOTE",
        "query_text": "关键时刻需要和狼队友统一冲票推掉一个好人",
        "keywords": ["冲票", "统一投票", "冲票战术", "绑票"],
    },
]


def load_strategies():
    conn = psycopg2.connect(CONN_STR)
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score
        FROM strategy_knowledge_docs WHERE status='active'
    """)
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append(
            {
                "situation": sit or "",
                "recommended": rec or "",
                "rationale": rat or "",
                "role": role or "global",
                "phase": phase or "global",
                "quality": float(q) if q else 0.8,
            }
        )
    conn.close()
    return docs


def judge_relevance(result, query, level=1):
    """level=1: any keyword match; level=2: >=2 keyword matches"""
    content = f"{result.get('situation', '')} {result.get('strategy', '')}".lower()
    count = sum(1 for kw in query.get("keywords", []) if kw.lower() in content)
    return 2 if count >= 2 else (1 if count >= 1 else 0)


def p_at_k(results, query, k):
    if not results:
        return 0.0
    k = min(k, len(results))
    return sum(1 for r in results[:k] if judge_relevance(r, query) > 0) / k


def mrr(results, query):
    for i, r in enumerate(results, 1):
        if judge_relevance(r, query) > 0:
            return 1.0 / i
    return 0.0


def ndcg_at_k(results, query, k):
    if not results:
        return 0.0
    k = min(k, len(results))
    gains = [judge_relevance(r, query) for r in results[:k]]
    dcg = sum(g / np.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(gains, reverse=True)
    idcg = sum(g / np.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def eval_method(name, func, queries, warmup=True):
    if warmup:
        func(queries[0])
    metrics = []
    for q in queries:
        t0 = time.perf_counter()
        results = func(q)
        lat = (time.perf_counter() - t0) * 1000
        metrics.append(
            {
                "id": q["id"],
                "P@3": p_at_k(results, q, 3),
                "P@5": p_at_k(results, q, 5),
                "P@10": p_at_k(results, q, 10),
                "MRR": mrr(results, q),
                "NDCG@5": ndcg_at_k(results, q, 5),
                "NDCG@10": ndcg_at_k(results, q, 10),
                "latency_ms": lat,
                "n": len(results),
            }
        )
    return metrics


def print_summary(all_metrics, methods):
    print(f"\n{'=' * 80}")
    print(f"{'Metric':<18}", end="")
    for name in methods:
        print(f" {name:>16}", end="")
    print(f" {'Winner':<16}")
    print(f"{'-' * 80}")

    keys = [
        ("P@5", "P@5"),
        ("P@10", "P@10"),
        ("MRR", "MRR"),
        ("NDCG@5", "NDCG@5"),
        ("NDCG@10", "NDCG@10"),
        ("Avg Latency", "latency_ms"),
    ]
    for label, key in keys:
        vals = {n: np.mean([m[key] for m in all_metrics[n]]) for n in methods}
        if "Latency" in label:
            winner = min(vals, key=vals.get)
        else:
            winner = max(vals, key=vals.get)
        print(f"{label:<18}", end="")
        for name in methods:
            m = " *" if name == winner else ""
            if "Latency" in label:
                print(f" {vals[name]:>14.1f}ms{m}", end="")
            else:
                print(f" {vals[name]:>15.3f}{m}", end="")
        print(f" {winner:>16}")
    print(f"{'-' * 80}")
    print("  * = best")


def main():
    print("=" * 80)
    print("4-Method Retrieval Comparison: Metadata vs FullText vs TF-IDF vs BGE-M3")
    print("=" * 80)

    # Load shared data
    docs = load_strategies()
    print(f"\nLoaded {len(docs)} strategies from PostgreSQL")

    # ---- Method A: Metadata ----
    print("\n[1/4] Building A: Metadata (SQL)")

    def a_search(q):
        conn = psycopg2.connect(CONN_STR)
        c = conn.cursor()
        c.execute(
            """
            SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''), quality_score
            FROM strategy_knowledge_docs WHERE status='active'
              AND (role = %s OR role = 'global') AND (phase = %s OR phase = 'global')
            ORDER BY (quality_score + CASE WHEN role!='global' THEN 0.15 ELSE 0 END
                     + CASE WHEN phase!='global' THEN 0.08 ELSE 0 END) * (0.9+RANDOM()*0.2) DESC
            LIMIT 10
        """,
            (q["role"], q["phase"]),
        )
        results = [
            {"situation": r[0] or "", "strategy": r[1] or "", "quality": float(r[2]) if r[2] else 0.8}
            for r in c.fetchall()
        ]
        conn.close()
        return results

    metrics_a = eval_method("A_Metadata", a_search, TEST_QUERIES)

    # ---- Method B: FullText ----
    print("[2/4] Building B: FullText (ILIKE)")
    import jieba

    def b_search(q):
        words = [w for w in jieba.cut(q["query_text"]) if len(w) >= 2]
        words = list(dict.fromkeys(words))[:5]
        if not words:
            return []
        clauses = " OR ".join(
            [
                f"(COALESCE(situation_pattern,'') ILIKE '%{w}%' OR COALESCE(recommended_action,'') ILIKE '%{w}%')"
                for w in words
            ]
        )
        match_expr = " + ".join(
            [
                f"(CASE WHEN COALESCE(situation_pattern,'') ILIKE '%{w}%' THEN 1 ELSE 0 END +"
                f" CASE WHEN COALESCE(recommended_action,'') ILIKE '%{w}%' THEN 1 ELSE 0 END)"
                for w in words
            ]
        )
        conn = psycopg2.connect(CONN_STR)
        c = conn.cursor()
        c.execute(f"""
            SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''), quality_score
            FROM strategy_knowledge_docs WHERE status='active' AND ({clauses})
            ORDER BY ({match_expr} * 0.3 + quality_score * 0.5
                     + CASE WHEN role='{q["role"]}' THEN 0.2 ELSE 0 END
                     + CASE WHEN phase='{q["phase"]}' THEN 0.1 ELSE 0 END
                     ) * (0.9+RANDOM()*0.2) DESC
            LIMIT 10
        """)
        results = [
            {"situation": r[0] or "", "strategy": r[1] or "", "quality": float(r[2]) if r[2] else 0.8}
            for r in c.fetchall()
        ]
        conn.close()
        return results

    metrics_b = eval_method("B_FullText", b_search, TEST_QUERIES)

    # ---- Method C: TF-IDF ----
    print("[3/4] Building C: TF-IDF Vector Index")
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    doc_texts = [" ".join(jieba.cut(f"{d['situation']} {d['recommended']} {d['rationale']}")) for d in docs]
    vec = TfidfVectorizer(max_features=3000, ngram_range=(1, 2))
    doc_vecs = vec.fit_transform(doc_texts)

    def c_search(q):
        qv = vec.transform([" ".join(jieba.cut(q["query_text"]))])
        sims = cosine_similarity(qv, doc_vecs)[0]
        rb = np.array([0.15 if d["role"] == q["role"] else (0.05 if d["role"] == "global" else 0) for d in docs])
        pb = np.array([0.08 if d["phase"] == q["phase"] else (0.03 if d["phase"] == "global" else 0) for d in docs])
        qb = np.array([d["quality"] * 0.1 for d in docs])
        scores = sims + rb + pb + qb
        top = np.argsort(scores)[::-1][:10]
        return [
            {"situation": docs[i]["situation"], "strategy": docs[i]["recommended"], "quality": docs[i]["quality"]}
            for i in top
        ]

    metrics_c = eval_method("C_TFIDF", c_search, TEST_QUERIES)

    # ---- Method D: BGE-M3 ----
    print("[4/4] Building D: BGE-M3 Embedding Index")
    from sentence_transformers import SentenceTransformer

    t0 = time.perf_counter()
    model = SentenceTransformer("/home/4T-3/PLM/bge-m3/", device="cuda:3")
    load_t = time.perf_counter() - t0

    bge_texts = [f"{d['situation']} {d['recommended']} {d['rationale']}" for d in docs]
    t0 = time.perf_counter()
    bge_embs = np.asarray(
        model.encode(bge_texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32
    )
    enc_t = time.perf_counter() - t0
    print(
        f"  Model load: {load_t:.1f}s, Encode {len(docs)} docs: {enc_t:.1f}s, Emb shape: {bge_embs.shape}, Memory: {bge_embs.nbytes / 1024**2:.1f}MB"
    )

    def d_search(q):
        qe = np.asarray(model.encode(q["query_text"], normalize_embeddings=True), dtype=np.float32)
        sims = np.dot(bge_embs, qe)
        rb = np.array(
            [0.15 if d["role"] == q["role"] else (0.05 if d["role"] == "global" else 0) for d in docs], dtype=np.float32
        )
        pb = np.array(
            [0.08 if d["phase"] == q["phase"] else (0.03 if d["phase"] == "global" else 0) for d in docs],
            dtype=np.float32,
        )
        qb = np.array([d["quality"] * 0.1 for d in docs], dtype=np.float32)
        scores = sims + rb + pb + qb
        top = np.argsort(scores)[::-1][:10]
        return [
            {"situation": docs[i]["situation"], "strategy": docs[i]["recommended"], "quality": docs[i]["quality"]}
            for i in top
        ]

    metrics_d = eval_method("D_BGE", d_search, TEST_QUERIES)

    # Print summary
    all_metrics = {"A_Metadata": metrics_a, "B_FullText": metrics_b, "C_TFIDF": metrics_c, "D_BGE-M3": metrics_d}
    methods = list(all_metrics.keys())
    print_summary(all_metrics, methods)

    # Per-query detail
    print(f"\n{'=' * 80}")
    print("Per-query P@5 comparison:")
    print(f"{'Q':<5} {'Role':<12} {'Phase':<20} {'A_Meta':>8} {'B_Full':>8} {'C_TFIDF':>8} {'D_BGE':>8}")
    for i, q in enumerate(TEST_QUERIES):
        pa = metrics_a[i]["P@5"]
        pb = metrics_b[i]["P@5"]
        pc = metrics_c[i]["P@5"]
        pd = metrics_d[i]["P@5"]
        qid = q["id"]
        print(f"{qid:<5} {q['role']:<12} {q['phase']:<20} {pa:>8.2f} {pb:>8.2f} {pc:>8.2f} {pd:>8.2f}")

    # Winner counts
    print(f"\n{'=' * 80}")
    print("P@5 winner count per query:")
    winners = {"A": 0, "B": 0, "C": 0, "D": 0}
    for i in range(len(TEST_QUERIES)):
        vals = {"A": metrics_a[i]["P@5"], "B": metrics_b[i]["P@5"], "C": metrics_c[i]["P@5"], "D": metrics_d[i]["P@5"]}
        best = max(vals, key=vals.get)
        winners[best] += 1
    for k, v in winners.items():
        print(f"  {k}: {v} queries")

    # Latency details
    print("\nLatency percentiles:")
    for name in methods:
        lats = [m["latency_ms"] for m in all_metrics[name]]
        print(
            f"  {name:12s}: mean={np.mean(lats):.1f}ms p50={np.percentile(lats, 50):.1f}ms p95={np.percentile(lats, 95):.1f}ms"
        )


if __name__ == "__main__":
    main()
