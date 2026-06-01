#!/usr/bin/env python3
"""
Fine-tune BGE-M3 on AI Werewolf domain using contrastive learning.

Pipeline:
  1. Generate training triplets from strategy corpus
  2. Fine-tune BGE-M3 with MultipleNegativesRankingLoss
  3. Benchmark retrieval NDCG@5 before vs after
"""

import sys, os, json, time, random
import numpy as np
import jieba
import psycopg2
from rank_bm25 import BM25Okapi

sys.path.insert(0, ".")

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
OUTPUT_PATH = "/home/4T-3/PLM/bge-m3-werewolf-ft/"

# ---- Test queries (same 37 as before) ----
BASE_QUERIES = [
    {"id":"N01","role":"Seer","phase":"DAY_BADGE_SPEECH","text":"我是预言家竞选警长需要报警徽流和查验结果","kw":["警徽流","警长竞选"]},
    {"id":"N02","role":"Witch","phase":"NIGHT_WITCH_ACTION","text":"第一晚有人被刀我要决定是否使用解药救人","kw":["首夜解药","解药使用"]},
    {"id":"N03","role":"Werewolf","phase":"NIGHT_WOLF_ACTION","text":"今晚狼队要选择击杀目标应该优先刀谁","kw":["刀人优先级","刀法"]},
    {"id":"N04","role":"Werewolf","phase":"DAY_SPEECH","text":"我是狼人需要伪装成好人发言不能被发现","kw":["伪装好人","狼人伪装"]},
    {"id":"N05","role":"Villager","phase":"DAY_SPEECH","text":"我是平民需要给出有价值的发言分析局势","kw":["平民发言","发言质量"]},
    {"id":"N06","role":"Hunter","phase":"DAY_SPEECH","text":"我被多人投票可能要出局要不要跳猎人身份","kw":["猎人跳身份","枪徽流"]},
    {"id":"N07","role":"Seer","phase":"DAY_SPEECH","text":"有人对跳预言家我需要证明自己是真的","kw":["对跳预言家","查验链"]},
    {"id":"N08","role":"Werewolf","phase":"DAY_SPEECH","text":"我被真预言家查杀了应该怎么应对","kw":["被查杀","反跳"]},
    {"id":"N09","role":"Witch","phase":"mid_game","text":"第三天了我有一瓶毒药还没用应该毒谁","kw":["毒药使用","开毒时机"]},
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
    {"id":"E02","role":"Werewolf","phase":"NIGHT_WOLF_ACTION","text":"只剩下我一匹狼了该怎么刀人","kw":["最后一狼","独狼"]},
    {"id":"E03","role":"Villager","phase":"DAY_SPEECH","text":"所有人都说我是狼但我真的是平民","kw":["被冤枉","表水"]},
    {"id":"E04","role":"global","phase":"global","text":"这游戏好难我不会玩怎么办","kw":["新手","入门"]},
    {"id":"E05","role":"global","phase":"global","text":"怎样才能赢","kw":["胜利","策略"]},
    {"id":"E06","role":"Seer","phase":"DAY_BADGE_SPEECH","text":"我是预言家有查杀但对跳也出现了警徽流怎么安排","kw":["对跳","警徽流"]},
    {"id":"E07","role":"Werewolf","phase":"DAY_SPEECH","text":"既要伪装又要带节奏还要保护队友怎么同时做好","kw":["伪装","带节奏"]},
    {"id":"E08","role":"Werewolf","phase":"DAY_SPEECH","text":"好人应该帮狼人隐藏身份投票怎么跟票","kw":["伪装","跟票"]},
    {"id":"E11","role":"global","phase":"global","text":"怎么玩","kw":["新手","入门"]},
    {"id":"E12","role":"Werewolf","phase":"global","text":"自刀","kw":["自刀"]},
    {"id":"E13","role":"global","phase":"mid_game","text":"剩1狼2民1神怎么投","kw":["残局","轮次"]},
    {"id":"E14","role":"Cupid","phase":"night_1","text":"丘比特第一晚应该连谁比较好","kw":["丘比特","情侣"]},
    {"id":"E18","role":"Witch","phase":"mid_game","text":"我毒错人了毒死了一个平民现在怎么办","kw":["毒错","补救"]},
    {"id":"E19","role":"Werewolf","phase":"mid_game","text":"刀错人了刀到了平民狼刀落后怎么翻盘","kw":["刀错","翻盘"]},
    {"id":"E20","role":"Guard","phase":"mid_game","text":"守错人了守了一个狼人导致预言家被刀死了","kw":["守错","失误"]},
]


# ================================================================
# Data loading
# ================================================================

def load_docs():
    conn = psycopg2.connect(CONN)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score
               FROM strategy_knowledge_docs WHERE status='active'""")
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append({"situation": sit or "", "strategy": rec or "", "rationale": rat or "",
                     "role": role or "global", "phase": phase or "global",
                     "quality": float(q) if q else 0.8})
    conn.close()
    return docs


# ================================================================
# Training data generation
# ================================================================

def generate_triplets(docs, output_path="data/ft_triplets.jsonl", n_samples=600):
    """Generate (anchor, positive, hard_negative) triplets.

    Positive: same role, different doc (different phase = more variety)
    Hard negative: BM25 top-mismatch from the anchor's role perspective
    """
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    triplets = []
    # Group docs by role for positive sampling
    role_indices = {}
    for i, d in enumerate(docs):
        role_indices.setdefault(d["role"], []).append(i)

    for i, anchor in enumerate(docs):
        if len(triplets) >= n_samples:
            break
        if not role_indices.get(anchor["role"]):
            continue

        # Positive: same role, different doc
        same_role = [j for j in role_indices[anchor["role"]] if j != i]
        if not same_role:
            continue
        pos_idx = random.choice(same_role)

        # Hard negative: BM25 search using anchor text, pick highest-scoring doc
        # that is NOT the anchor and NOT same-role
        tokens = " ".join(jieba.cut(anchor["situation"])).split()
        if not tokens:
            continue
        scores = bm25.get_scores(tokens)
        # Mask out anchor and same-role docs
        mask = np.ones(len(docs), dtype=bool)
        mask[i] = False
        for j in same_role:
            mask[j] = False
        masked_scores = np.where(mask, scores, -1)
        neg_idx = int(np.argmax(masked_scores))

        triplets.append({
            "anchor_text": f"{anchor['situation']} {anchor['strategy']}",
            "positive_text": f"{docs[pos_idx]['situation']} {docs[pos_idx]['strategy']}",
            "negative_text": f"{docs[neg_idx]['situation']} {docs[neg_idx]['strategy']}",
            "anchor_role": anchor["role"],
        })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        for t in triplets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    print(f"Generated {len(triplets)} triplets → {output_path}")
    return output_path


# ================================================================
# Fine-tuning
# ================================================================

def finetune(data_path, model_path=BGE_PATH, output_path=OUTPUT_PATH,
             epochs=3, batch_size=16, lr=2e-5):
    """Fine-tune BGE-M3 with MultipleNegativesRankingLoss."""
    import torch
    from torch.utils.data import DataLoader
    from sentence_transformers import SentenceTransformer, InputExample, losses

    # Load training data
    examples = []
    with open(data_path) as f:
        for line in f:
            obj = json.loads(line.strip())
            # (anchor, positive) as positive pair
            examples.append(InputExample(texts=[obj["anchor_text"], obj["positive_text"]]))
            # (anchor, negative) as hard negative pair
            examples.append(InputExample(texts=[obj["anchor_text"], obj["negative_text"]]))

    random.shuffle(examples)
    print(f"Training with {len(examples)} pairs ({len(examples)//2} triplets)")
    print(f"  epochs={epochs}, batch_size={batch_size}, lr={lr}")

    # Load model
    model = SentenceTransformer(model_path, device=GPU)

    # DataLoader
    loader = DataLoader(examples, shuffle=True, batch_size=batch_size)

    # MultipleNegativesRankingLoss: standard for embedding fine-tuning
    # Uses in-batch negatives as additional negative samples
    loss_fn = losses.MultipleNegativesRankingLoss(model)

    # Train
    warmup = int(len(loader) * 0.1)
    model.fit(
        train_objectives=[(loader, loss_fn)],
        epochs=epochs,
        optimizer_params={"lr": lr},
        warmup_steps=warmup,
        show_progress_bar=True,
        output_path=output_path,
        save_best_model=True,
    )

    print(f"Fine-tuned model saved to {output_path}")
    return output_path


# ================================================================
# Retrieval evaluation
# ================================================================

def evaluate_retrieval(model_path, docs, queries, label=""):
    """Evaluate a BGE-M3 model for dense retrieval."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_path, device=GPU)
    N = len(docs)
    doc_texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]

    # Encode docs
    t0 = time.perf_counter()
    doc_embs = np.asarray(model.encode(doc_texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32)
    enc_time = time.perf_counter() - t0

    # Encode queries and search
    results = []
    lats = []
    for q in queries:
        t0 = time.perf_counter()
        qe = np.asarray(model.encode(q["text"], normalize_embeddings=True), dtype=np.float32)
        sims = np.dot(doc_embs, qe)

        # Role/phase bonuses (same as production)
        scores = sims + np.array([0.12 if d["role"]==q["role"] else (0.03 if d["role"]=="global" else 0) for d in docs], dtype=np.float32)
        scores += np.array([0.06 if d["phase"]==q["phase"] else (0.02 if d["phase"]=="global" else 0) for d in docs], dtype=np.float32)

        idx = np.argsort(scores)[::-1][:10]
        lat = (time.perf_counter()-t0)*1000
        lats.append(lat)

        top_docs = [{"situation": docs[i]["situation"], "strategy": docs[i]["strategy"]} for i in idx]
        results.append(top_docs)

    # Compute metrics
    all_metrics = []
    for i, (res, q) in enumerate(zip(results, queries)):
        m = {}
        for k in [5, 10]:
            kk = min(k, len(res))
            rel = []
            for r in res[:kk]:
                content = f"{r['situation']} {r['strategy']}".lower()
                rel.append(sum(1 for kw in q["kw"] if kw.lower() in content))
            m[f"P@{k}"] = sum(1 for r in rel if r > 0) / max(kk, 1)
        for rank, r in enumerate(res, 1):
            content = f"{r['situation']} {r['strategy']}".lower()
            if sum(1 for kw in q["kw"] if kw.lower() in content) > 0:
                m["MRR"] = 1.0/rank; break
        else: m["MRR"] = 0.0
        for k in [5, 10]:
            kk = min(k, len(res))
            gains = []
            for r in res[:kk]:
                content = f"{r['situation']} {r['strategy']}".lower()
                gains.append(sum(1 for kw in q["kw"] if kw.lower() in content))
            dcg = sum(g/np.log2(j+2) for j,g in enumerate(gains))
            gains_sorted = sorted(gains, reverse=True)
            idcg = sum(g/np.log2(j+2) for j,g in enumerate(gains_sorted))
            m[f"NDCG@{k}"] = dcg/idcg if idcg>0 else 0.0
        all_metrics.append(m)

    agg = {k: np.mean([qm[k] for qm in all_metrics]) for k in ["P@5","P@10","MRR","NDCG@5","NDCG@10"]}
    avg_lat = np.mean(lats)

    print(f"\n  {label} (Dense only):")
    print(f"    P@5={agg['P@5']:.3f}  P@10={agg['P@10']:.3f}  MRR={agg['MRR']:.3f}  "
          f"NDCG@5={agg['NDCG@5']:.3f}  NDCG@10={agg['NDCG@10']:.3f}  "
          f"enc={enc_time:.1f}s  query_lat={avg_lat:.0f}ms")

    # Also evaluate BM25 + Dense RRF
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    rrf_metrics = []
    rrf_lats = []
    for q in queries:
        t0 = time.perf_counter()
        # BM25
        b_scores = bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if b_scores.max() > 0: b_scores = b_scores / b_scores.max()
        b_scores += np.array([0.1 if d["role"]==q["role"] else (0.03 if d["role"]=="global" else 0) for d in docs])
        b_scores += np.array([0.05 if d["phase"]==q["phase"] else (0.02 if d["phase"]=="global" else 0) for d in docs])
        b_top = list(np.argsort(b_scores)[::-1][:20])

        # Dense
        qe = np.asarray(model.encode(q["text"], normalize_embeddings=True), dtype=np.float32)
        sims = np.dot(doc_embs, qe)
        d_scores = sims + np.array([0.12 if d["role"]==q["role"] else (0.03 if d["role"]=="global" else 0) for d in docs], dtype=np.float32)
        d_scores += np.array([0.06 if d["phase"]==q["phase"] else (0.02 if d["phase"]=="global" else 0) for d in docs], dtype=np.float32)
        d_top = list(np.argsort(d_scores)[::-1][:20])

        # RRF
        rrf_scores = {}
        for rank, i in enumerate(b_top, 1): rrf_scores[int(i)] = rrf_scores.get(int(i), 0) + 1/(60+rank)
        for rank, i in enumerate(d_top, 1): rrf_scores[int(i)] = rrf_scores.get(int(i), 0) + 1/(60+rank)
        final = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        lat = (time.perf_counter()-t0)*1000
        rrf_lats.append(lat)

        res = [{"situation": docs[i]["situation"], "strategy": docs[i]["strategy"]} for i,_ in final]
        m = {}
        for k in [5, 10]:
            kk = min(k, len(res))
            rel = []
            for r in res[:kk]:
                content = f"{r['situation']} {r['strategy']}".lower()
                rel.append(sum(1 for kw in q["kw"] if kw.lower() in content))
            m[f"P@{k}"] = sum(1 for r in rel if r > 0) / max(kk, 1)
        for rank, r in enumerate(res, 1):
            content = f"{r['situation']} {r['strategy']}".lower()
            if sum(1 for kw in q["kw"] if kw.lower() in content) > 0:
                m["MRR"] = 1.0/rank; break
        else: m["MRR"] = 0.0
        for k in [5, 10]:
            kk = min(k, len(res))
            gains = []
            for r in res[:kk]:
                content = f"{r['situation']} {r['strategy']}".lower()
                gains.append(sum(1 for kw in q["kw"] if kw.lower() in content))
            dcg = sum(g/np.log2(j+2) for j,g in enumerate(gains))
            gains_sorted = sorted(gains, reverse=True)
            idcg = sum(g/np.log2(j+2) for j,g in enumerate(gains_sorted))
            m[f"NDCG@{k}"] = dcg/idcg if idcg>0 else 0.0
        rrf_metrics.append(m)

    rrf_agg = {k: np.mean([qm[k] for qm in rrf_metrics]) for k in ["P@5","P@10","MRR","NDCG@5","NDCG@10"]}

    # Split by base/special
    base_rrf = [rrf_metrics[i] for i in range(20)]
    spec_rrf = [rrf_metrics[i] for i in range(20, len(rrf_metrics))]
    base_n = np.mean([q["NDCG@5"] for q in base_rrf]) if base_rrf else 0
    spec_n = np.mean([q["NDCG@5"] for q in spec_rrf]) if spec_rrf else 0

    print(f"\n  {label} (BM25 + Dense RRF):")
    print(f"    P@5={rrf_agg['P@5']:.3f}  P@10={rrf_agg['P@10']:.3f}  MRR={rrf_agg['MRR']:.3f}  "
          f"NDCG@5={rrf_agg['NDCG@5']:.3f}  NDCG@10={rrf_agg['NDCG@10']:.3f}  "
          f"lat={np.mean(rrf_lats):.0f}ms")
    print(f"    Base NDCG@5={base_n:.3f}  Special NDCG@5={spec_n:.3f}")

    return {"dense": agg, "rrf": rrf_agg, "rrf_ndcg5": rrf_agg["NDCG@5"]}


# ================================================================
# Main
# ================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("BGE-M3 FINE-TUNING FOR AI WEREWOLF")
    print("=" * 70)

    docs = load_docs()
    all_queries = BASE_QUERIES + SPECIAL_QUERIES
    print(f"Docs: {len(docs)}, Queries: {len(all_queries)}")

    # ============================================================
    # Step 1: Evaluate BEFORE fine-tuning
    # ============================================================
    print(f"\n{'='*70}")
    print("STEP 1: Before Fine-tuning (Zero-shot BGE-M3)")
    print(f"{'='*70}")
    before = evaluate_retrieval(BGE_PATH, docs, all_queries, "BEFORE")

    # ============================================================
    # Step 2: Generate training data
    # ============================================================
    print(f"\n{'='*70}")
    print("STEP 2: Generate Training Data")
    print(f"{'='*70}")
    data_path = generate_triplets(docs, n_samples=600)

    # ============================================================
    # Step 3: Fine-tune
    # ============================================================
    print(f"\n{'='*70}")
    print("STEP 3: Fine-tune BGE-M3")
    print(f"{'='*70}")
    ft_path = finetune(data_path, epochs=3, batch_size=16, lr=2e-5)

    # ============================================================
    # Step 4: Evaluate AFTER fine-tuning
    # ============================================================
    print(f"\n{'='*70}")
    print("STEP 4: After Fine-tuning")
    print(f"{'='*70}")
    after = evaluate_retrieval(ft_path, docs, all_queries, "AFTER")

    # ============================================================
    # Final Comparison
    # ============================================================
    print(f"\n{'='*70}")
    print("FINAL COMPARISON")
    print(f"{'='*70}")

    b_ndcg = before["rrf_ndcg5"]
    a_ndcg = after["rrf_ndcg5"]
    delta = a_ndcg - b_ndcg

    print(f"""
  BM25 + BGE Dense RRF NDCG@5:
    Before fine-tuning:  {b_ndcg:.3f}
    After fine-tuning:   {a_ndcg:.3f}
    Delta:               {'+' if delta > 0 else ''}{delta:.3f} ({delta/b_ndcg*100:+.1f}%)

  Dense-only NDCG@5:
    Before: {before['dense']['NDCG@5']:.3f}
    After:  {after['dense']['NDCG@5']:.3f}

  Fine-tuned model saved to: {ft_path}
""")

    if delta > 0:
        print("  ✅ Fine-tuning improved retrieval quality!")
    else:
        print("  ⚠️  Fine-tuning did not improve — zero-shot BGE-M3 is already strong on this corpus")
