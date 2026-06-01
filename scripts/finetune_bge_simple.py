#!/usr/bin/env python3
"""
Simple BGE-M3 fine-tuning — direct PyTorch training loop (no deepspeed).

Avoids deepspeed/torch compatibility issues.
Uses MultipleNegativesRankingLoss with in-batch negatives.
"""

import os, sys, json, time, random
import numpy as np
import jieba
import psycopg2
from rank_bm25 import BM25Okapi
import torch
from torch.utils.data import DataLoader, Dataset

sys.path.insert(0, ".")

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
OUTPUT_PATH = "/home/4T-3/PLM/bge-m3-werewolf-ft/"

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
    {"id":"E17","role":"Witch","phase":"mid_game","text":"我毒错人了毒死了一个平民现在怎么办","kw":["毒错","补救"]},
    {"id":"E18","role":"Werewolf","phase":"mid_game","text":"刀错人了刀到了平民狼刀落后怎么翻盘","kw":["刀错","翻盘"]},
    {"id":"E13","role":"global","phase":"mid_game","text":"剩1狼2民1神怎么投","kw":["残局","轮次"]},
    {"id":"E06","role":"Seer","phase":"DAY_BADGE_SPEECH","text":"我是预言家有查杀但对跳也出现了警徽流怎么安排","kw":["对跳","警徽流"]},
]


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


class TripletDataset(Dataset):
    """Dataset of (anchor, positive, negative) triplets."""
    def __init__(self, triplets, tokenizer, max_len=256):
        self.triplets = triplets
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.triplets)

    def __getitem__(self, idx):
        t = self.triplets[idx]
        return {
            "anchor": t["anchor_text"],
            "positive": t["positive_text"],
            "negative": t["negative_text"],
        }

    def collate(self, batch):
        anchors = [b["anchor"] for b in batch]
        positives = [b["positive"] for b in batch]
        negatives = [b["negative"] for b in batch]
        all_texts = anchors + positives + negatives
        encoded = self.tokenizer(all_texts, padding=True, truncation=True,
                                 max_length=self.max_len, return_tensors="pt")
        return encoded, len(anchors)


def generate_triplets(docs, n_samples=600):
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])
    role_indices = {}
    for i, d in enumerate(docs):
        role_indices.setdefault(d["role"], []).append(i)

    triplets = []
    for i, anchor in enumerate(docs):
        if len(triplets) >= n_samples:
            break
        same_role = [j for j in role_indices.get(anchor["role"], []) if j != i]
        if not same_role:
            continue
        pos_idx = random.choice(same_role)

        tokens = " ".join(jieba.cut(anchor["situation"])).split()
        if not tokens:
            continue
        scores = bm25.get_scores(tokens)
        mask = np.ones(len(docs), dtype=bool)
        mask[i] = False
        for j in same_role: mask[j] = False
        masked = np.where(mask, scores, -1)
        neg_idx = int(np.argmax(masked))

        triplets.append({
            "anchor_text": f"{anchor['situation']} {anchor['strategy']}",
            "positive_text": f"{docs[pos_idx]['situation']} {docs[pos_idx]['strategy']}",
            "negative_text": f"{docs[neg_idx]['situation']} {docs[neg_idx]['strategy']}",
        })

    return triplets


def finetune_simple(triplets, model_path=BGE_PATH, output_path=OUTPUT_PATH,
                    epochs=3, batch_size=16, lr=2e-5):
    """Fine-tune BGE-M3 with manual PyTorch training loop."""
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer
    import torch.nn as nn

    device = torch.device(GPU)
    tokenizer = AutoTokenizer.from_pretrained(model_path)

    # Load model (as SentenceTransformer for easy embedding)
    model = SentenceTransformer(model_path, device=GPU)
    # Get the underlying transformer for training
    model.train()

    # Create dataset
    dataset = TripletDataset(triplets, tokenizer)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True,
                        collate_fn=dataset.collate)

    # Optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    total_steps = len(loader) * epochs
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=total_steps)

    print(f"Training: {len(triplets)} triplets, {epochs} epochs, "
          f"batch={batch_size}, lr={lr}, steps={total_steps}")

    model.to(device)
    best_loss = float('inf')

    for epoch in range(epochs):
        epoch_loss = 0.0
        for step, (encoded, n_anchors) in enumerate(loader):
            # Move to GPU
            encoded = {k: v.to(device) for k, v in encoded.items()}

            # Forward: get embeddings for all texts
            outputs = model.forward(encoded)
            # sentence_embedding is the pooled output
            all_embs = outputs['sentence_embedding']  # (3*B, dim)
            all_embs = nn.functional.normalize(all_embs, p=2, dim=1)

            # Split into anchor, positive, negative
            anchor_emb = all_embs[:n_anchors]
            pos_emb = all_embs[n_anchors:2*n_anchors]
            neg_emb = all_embs[2*n_anchors:]

            # Compute similarity matrix
            # anchor × all (positives + in-batch negatives)
            # Simple approach: anchor-pos cosine similarity
            pos_sim = (anchor_emb * pos_emb).sum(dim=1)  # (B,)
            neg_sim = (anchor_emb * neg_emb).sum(dim=1)  # (B,)

            # InfoNCE-like loss
            pos_scores = pos_sim / 0.05  # temperature
            neg_scores = neg_sim / 0.05

            # For each anchor: positive should be higher than negative
            loss = -pos_scores.mean() + torch.logsumexp(
                torch.stack([pos_scores, neg_scores], dim=1), dim=1
            ).mean()

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()

            if step % 20 == 0:
                print(f"  Epoch {epoch+1}, Step {step}/{len(loader)}, Loss: {loss.item():.4f}")

        avg_loss = epoch_loss / len(loader)
        print(f"  Epoch {epoch+1} done, Avg Loss: {avg_loss:.4f}")

        if avg_loss < best_loss:
            best_loss = avg_loss
            os.makedirs(output_path, exist_ok=True)
            # Save transformer weights directly (bypass deepspeed issue in save_pretrained)
            import shutil
            transformer = model._modules['0'].auto_model
            torch.save(transformer.state_dict(), os.path.join(output_path, 'pytorch_model.bin'))
            # Copy essential files from source model
            for f in os.listdir(model_path):
                src = os.path.join(model_path, f)
                if os.path.isfile(src) and not f.endswith('.bin') and not f.endswith('.pt'):
                    dst = os.path.join(output_path, f)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
            # Copy subdirs
            for sub in ['1_Pooling']:
                src_d = os.path.join(model_path, sub)
                dst_d = os.path.join(output_path, sub)
                if os.path.exists(src_d) and not os.path.exists(dst_d):
                    shutil.copytree(src_d, dst_d)
            print(f"  Saved best model to {output_path}")

    return output_path


def evaluate_model(model_path, docs, queries, label=""):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_path, device=GPU)
    N = len(docs)
    doc_texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]

    t0 = time.perf_counter()
    doc_embs = np.asarray(model.encode(doc_texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32)
    enc_t = time.perf_counter() - t0

    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    metrics = []; lats = []
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
        rrf = {}
        for rank, i in enumerate(b_top, 1): rrf[int(i)] = rrf.get(int(i),0) + 1/(60+rank)
        for rank, i in enumerate(d_top, 1): rrf[int(i)] = rrf.get(int(i),0) + 1/(60+rank)
        final = [i for i,_ in sorted(rrf.items(), key=lambda x:x[1], reverse=True)[:10]]
        lat = (time.perf_counter()-t0)*1000
        lats.append(lat)

        res = [{"situation": docs[i]["situation"], "strategy": docs[i]["strategy"]} for i in final]
        m = {}
        for k in [5, 10]:
            kk = min(k, len(res))
            rel = []
            for r in res[:kk]:
                c = f"{r['situation']} {r['strategy']}".lower()
                rel.append(1 if sum(1 for kw in q["kw"] if kw.lower() in c) > 0 else 0)
            m[f"P@{k}"] = sum(rel)/max(kk,1)
        for rank2, r in enumerate(res, 1):
            c = f"{r['situation']} {r['strategy']}".lower()
            if sum(1 for kw in q["kw"] if kw.lower() in c) > 0:
                m["MRR"]=1.0/rank2; break
        else: m["MRR"]=0.0
        for k in [5, 10]:
            kk = min(k, len(res))
            gains = []
            for r in res[:kk]:
                c = f"{r['situation']} {r['strategy']}".lower()
                gains.append(sum(1 for kw in q["kw"] if kw.lower() in c))
            dcg = sum(g/np.log2(j+2) for j,g in enumerate(gains))
            gs = sorted(gains, reverse=True)
            idcg = sum(g/np.log2(j+2) for j,g in enumerate(gs))
            m[f"NDCG@{k}"] = dcg/idcg if idcg>0 else 0.0
        metrics.append(m)

    agg = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5","P@10","MRR","NDCG@5","NDCG@10"]}
    base_m = [metrics[i] for i in range(min(20, len(queries)))]
    spec_m = [metrics[i] for i in range(min(20, len(queries)), len(queries))]
    b_ndcg = np.mean([q["NDCG@5"] for q in base_m]) if base_m else 0
    s_ndcg = np.mean([q["NDCG@5"] for q in spec_m]) if spec_m else 0

    print(f"\n  {label}:")
    print(f"    NDCG@5={agg['NDCG@5']:.3f} P@5={agg['P@5']:.3f} MRR={agg['MRR']:.3f} "
          f"Base={b_ndcg:.3f} Spec={s_ndcg:.3f} "
          f"enc={enc_t:.1f}s q_lat={np.mean(lats):.0f}ms")
    return agg["NDCG@5"]


if __name__ == "__main__":
    print("=" * 60)
    print("BGE-M3 SIMPLE FINE-TUNING")
    print("=" * 60)

    docs = load_docs()
    all_q = BASE_QUERIES + SPECIAL_QUERIES
    print(f"Docs: {len(docs)}, Queries: {len(all_q)}")

    # BEFORE
    print(f"\n[1/3] Evaluating BEFORE fine-tuning...")
    before_ndcg = evaluate_model(BGE_PATH, docs, all_q, "BEFORE")

    # Generate data
    print(f"\n[2/3] Generating training data + fine-tuning...")
    triplets = generate_triplets(docs, n_samples=500)
    print(f"  Generated {len(triplets)} triplets")

    # Fine-tune
    ft_path = finetune_simple(triplets, epochs=2, batch_size=12, lr=2e-5)

    # AFTER
    print(f"\n[3/3] Evaluating AFTER fine-tuning...")
    after_ndcg = evaluate_model(ft_path, docs, all_q, "AFTER")

    # Summary
    delta = after_ndcg - before_ndcg
    print(f"\n{'='*60}")
    print(f"RESULT: NDCG@5 {before_ndcg:.3f} → {after_ndcg:.3f} ({'↑' if delta>0 else '↓'}{abs(delta):.3f})")
    print(f"Model: {ft_path}")
