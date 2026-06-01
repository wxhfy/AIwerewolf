#!/usr/bin/env python3
"""
ColBERT Late Interaction Rerank — evaluate impact on retrieval quality.

ColBERT does token-level MaxSim between query and document tokens,
providing cross-encoder quality at bi-encoder speed.

Test: Base RRF vs RRF + ColBERT Rerank on all 37 queries.
"""

import sys, time, numpy as np, jieba, psycopg2
from rank_bm25 import BM25Okapi

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
GPU = "cuda:3"

BASE_QUERIES = [
    {"id":"N01","role":"Seer","phase":"DAY_BADGE_SPEECH","text":"我是预言家竞选警长需要报警徽流和查验结果","kw":["警徽流","警长竞选"]},
    {"id":"N02","role":"Witch","phase":"NIGHT_WITCH_ACTION","text":"第一晚有人被刀我要决定是否使用解药救人","kw":["首夜解药","解药使用"]},
    {"id":"N03","role":"Werewolf","phase":"NIGHT_WOLF_ACTION","text":"今晚狼队要选择击杀目标应该优先刀谁","kw":["刀人优先级","刀法"]},
    {"id":"N04","role":"Werewolf","phase":"DAY_SPEECH","text":"我是狼人需要伪装成好人发言不能被发现","kw":["伪装好人","狼人伪装"]},
    {"id":"N05","role":"Villager","phase":"DAY_SPEECH","text":"我是平民需要给出有价值的发言分析局势","kw":["平民发言","发言质量"]},
    {"id":"N07","role":"Seer","phase":"DAY_SPEECH","text":"有人对跳预言家我需要证明自己是真的","kw":["对跳预言家","查验链"]},
    {"id":"N08","role":"Werewolf","phase":"DAY_SPEECH","text":"我被真预言家查杀了应该怎么应对","kw":["被查杀","反跳"]},
    {"id":"N10","role":"Guard","phase":"NIGHT_GUARD_ACTION","text":"今晚我要守护一个人不能连续守同一个","kw":["守护目标","轮换守护"]},
    {"id":"N11","role":"WhiteWolfKing","phase":"DAY_SPEECH","text":"白狼王什么时候自爆带走关键好人最合适","kw":["白狼王自爆","自爆时机"]},
    {"id":"N12","role":"global","phase":"DAY_VOTE","text":"投票环节怎样分析票型来找到狼人","kw":["票型分析","冲票"]},
    {"id":"N13","role":"global","phase":"late_game","text":"残局只剩3个人怎么做出正确的投票抉择","kw":["残局策略","残局抉择"]},
    {"id":"N14","role":"Werewolf","phase":"DAY_SPEECH","text":"狼队友被怀疑了怎么帮他又不暴露自己","kw":["队友被质疑","保护队友"]},
    {"id":"N15","role":"Villager","phase":"DAY_VOTE","text":"作为平民不确定该投谁怎么正确投票","kw":["平民投票"]},
    {"id":"N16","role":"global","phase":"global","text":"我是新手第一次玩狼人杀需要了解基础规则","kw":["新手","基础规则"]},
    {"id":"N17","role":"Witch","phase":"DAY_SPEECH","text":"我救过一个人银水要不要在白天报出来","kw":["银水","报银水"]},
    {"id":"N18","role":"Seer","phase":"NIGHT_SEER_ACTION","text":"今晚我要验一个人应该优先验谁","kw":["查验选择","验人优先级"]},
    {"id":"N19","role":"global","phase":"mid_game","text":"我发现之前站错边了现在怎么纠正","kw":["站错边","修正判断"]},
    {"id":"N20","role":"Werewolf","phase":"DAY_VOTE","text":"关键时刻需要和狼队友统一冲票推掉一个好人","kw":["冲票","统一投票"]},
]
SPECIAL_QUERIES = [
    {"id":"E01","role":"Seer","phase":"DAY_SPEECH","text":"我被女巫毒了怎么办","kw":["被毒","遗言"]},
    {"id":"E03","role":"Villager","phase":"DAY_SPEECH","text":"所有人都说我是狼但我真的是平民","kw":["被冤枉","表水"]},
    {"id":"E07","role":"Werewolf","phase":"DAY_SPEECH","text":"既要伪装又要带节奏还要保护队友怎么同时做好","kw":["伪装","带节奏"]},
    {"id":"E11","role":"global","phase":"global","text":"怎么玩","kw":["新手","入门"]},
    {"id":"E13","role":"global","phase":"mid_game","text":"剩1狼2民1神怎么投","kw":["残局","轮次"]},
    {"id":"E17","role":"Witch","phase":"mid_game","text":"我毒错人了毒死了一个平民现在怎么办","kw":["毒错","补救"]},
    {"id":"E18","role":"Werewolf","phase":"mid_game","text":"刀错人了刀到了平民狼刀落后怎么翻盘","kw":["刀错","翻盘"]},
    {"id":"E19","role":"Guard","phase":"mid_game","text":"守错人了守了一个狼人导致预言家被刀死了","kw":["守错","失误"]},
    {"id":"E20","role":"Cupid","phase":"night_1","text":"丘比特第一晚应该连谁比较好","kw":["丘比特","情侣"]},
    {"id":"E21","role":"BigBadWolf","phase":"NIGHT_WOLF_ACTION","text":"大野狼额外刀人应该怎么选目标","kw":["大野狼","双刀"]},
]

def load_docs():
    conn = psycopg2.connect(CONN); c = conn.cursor()
    c.execute("""SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score
               FROM strategy_knowledge_docs WHERE status='active'""")
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append({"situation": sit or "", "strategy": rec or "", "rationale": rat or "",
                     "role": role or "global", "phase": phase or "global", "quality": float(q) if q else 0.8})
    conn.close()
    return docs

def relevance(idx, q, docs):
    content = f"{docs[idx]['situation']} {docs[idx]['strategy']}".lower()
    return sum(1 for k in q["kw"] if k.lower() in content)

def evaluate(final_indices, q, docs):
    m = {}
    for k in [5, 10]:
        kk = min(k, len(final_indices))
        rel = [1 if relevance(i, q, docs) > 0 else 0 for i in final_indices[:kk]]
        m[f"P@{k}"] = sum(rel) / max(kk, 1)
    for rank, i in enumerate(final_indices, 1):
        if relevance(i, q, docs) > 0: m["MRR"] = 1.0/rank; break
    else: m["MRR"] = 0.0
    for k in [5, 10]:
        kk = min(k, len(final_indices))
        gains = [relevance(i, q, docs) for i in final_indices[:kk]]
        dcg = sum(g / np.log2(j+2) for j, g in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(g / np.log2(j+2) for j, g in enumerate(ideal))
        m[f"NDCG@{k}"] = dcg/idcg if idcg > 0 else 0.0
    return m


if __name__ == "__main__":
    print("=" * 60)
    print("ColBERT RERANK — Impact Evaluation")
    print("=" * 60)

    docs = load_docs()
    all_q = BASE_QUERIES + SPECIAL_QUERIES
    print(f"Docs: {len(docs)}, Queries: {len(all_q)}")

    # Build RRF (shared)
    from sentence_transformers import SentenceTransformer
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])
    model = SentenceTransformer("/home/4T-3/PLM/bge-m3/", device=GPU)
    dtx = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
    dembs = np.asarray(model.encode(dtx, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32)

    # Build ColBERT via FlagEmbedding
    from FlagEmbedding import BGEM3FlagModel
    bge = BGEM3FlagModel("/home/4T-3/PLM/bge-m3/", use_fp16=True, device=GPU)
    colbert_embs = []
    for i in range(0, len(docs), 64):
        batch = dtx[i:i+64]
        out = bge.encode(batch, return_colbert_vecs=True)
        colbert_embs.extend(out['colbert_vecs'])
    print(f"ColBERT index: {len(colbert_embs)} docs ready")

    # Evaluate BOTH methods
    methods = {}
    methods["RRF"] = {"metrics": [], "lats": []}
    methods["RRF+ColBERT"] = {"metrics": [], "lats": []}

    for q in all_q:
        # --- RRF ---
        t0 = time.perf_counter()
        bs = bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if bs.max()>0: bs=bs/bs.max()
        bs += np.array([0.1 if d["role"]==q["role"] else (0.03 if d["role"]=="global" else 0) for d in docs])
        bs += np.array([0.05 if d["phase"]==q["phase"] else (0.02 if d["phase"]=="global" else 0) for d in docs])
        bt = list(np.argsort(bs)[::-1][:20])

        qe = np.asarray(model.encode(q["text"], normalize_embeddings=True), dtype=np.float32)
        ds = np.dot(dembs, qe)+np.array([0.12 if d["role"]==q["role"] else (0.03 if d["role"]=="global" else 0) for d in docs],dtype=np.float32)
        ds += np.array([0.06 if d["phase"]==q["phase"] else (0.02 if d["phase"]=="global" else 0) for d in docs],dtype=np.float32)
        dt = list(np.argsort(ds)[::-1][:20])

        rrf = {}
        for r,i in enumerate(bt,1): rrf[int(i)]=rrf.get(int(i),0)+1/(60+r)
        for r,i in enumerate(dt,1): rrf[int(i)]=rrf.get(int(i),0)+1/(60+r)
        rrf_final = [i for i,_ in sorted(rrf.items(), key=lambda x:x[1], reverse=True)[:5]]
        rrf_lat = (time.perf_counter()-t0)*1000
        methods["RRF"]["metrics"].append(evaluate(rrf_final, q, docs))
        methods["RRF"]["lats"].append(rrf_lat)

        # --- RRF + ColBERT ---
        t0 = time.perf_counter()
        rrf_candidates_20 = [i for i,_ in sorted(rrf.items(), key=lambda x:x[1], reverse=True)[:20]]

        # ColBERT MaxSim reranking
        q_out = bge.encode(q["text"], return_colbert_vecs=True)
        qc = np.asarray(q_out['colbert_vecs'], dtype=np.float32)
        qc /= np.linalg.norm(qc, axis=1, keepdims=True) + 1e-8

        scores = np.zeros(len(rrf_candidates_20))
        for j, idx in enumerate(rrf_candidates_20):
            dc = np.asarray(colbert_embs[idx], dtype=np.float32)
            dc /= np.linalg.norm(dc, axis=1, keepdims=True) + 1e-8
            sim = np.dot(qc, dc.T)
            scores[j] = np.sum(np.max(sim, axis=1))

        top = np.argsort(scores)[::-1][:5]
        colbert_final = [rrf_candidates_20[i] for i in top]
        colbert_lat = (time.perf_counter()-t0)*1000
        methods["RRF+ColBERT"]["metrics"].append(evaluate(colbert_final, q, docs))
        methods["RRF+ColBERT"]["lats"].append(colbert_lat)

    # Summary
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    for mname in methods:
        agg = {k: np.mean([qm[k] for qm in methods[mname]["metrics"]]) for k in ["P@5","P@10","MRR","NDCG@5","NDCG@10"]}
        base_m = methods[mname]["metrics"][:len(BASE_QUERIES)]
        spec_m = methods[mname]["metrics"][len(BASE_QUERIES):]
        base_n = np.mean([qm["NDCG@5"] for qm in base_m])
        spec_n = np.mean([qm["NDCG@5"] for qm in spec_m])
        avg_lat = np.mean(methods[mname]["lats"])
        print(f"\n{mname}:")
        print(f"  NDCG@5={agg['NDCG@5']:.3f} P@5={agg['P@5']:.3f} MRR={agg['MRR']:.3f}")
        print(f"  Base={base_n:.3f} Special={spec_n:.3f} Lat={avg_lat:.0f}ms")

    # Delta
    rrf_ndcg = np.mean([qm["NDCG@5"] for qm in methods["RRF"]["metrics"]])
    col_ndcg = np.mean([qm["NDCG@5"] for qm in methods["RRF+ColBERT"]["metrics"]])
    delta = col_ndcg - rrf_ndcg
    print(f"\nDelta NDCG@5: {rrf_ndcg:.3f} → {col_ndcg:.3f} ({'+' if delta>0 else ''}{delta:.3f})")
