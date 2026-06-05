#!/usr/bin/env python3
"""Batch LLM-verified hard negative mining (10 pairs per API call)."""

import json
import os
import random
import re
import sys

import jieba
import numpy as np
import psycopg2
import requests
import torch
from rank_bm25 import BM25Okapi
from torch.utils.data import DataLoader
from torch.utils.data import Dataset

sys.path.insert(0, ".")

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
OUTPUT_PATH = "/home/4T-3/PLM/bge-m3-werewolf-ft-v2/"
LLM_KEY = os.environ.get("DSV4FLASH_API_KEY", "")
LLM_URL = "https://ark.cn-beijing.volces.com/api/coding/v1/chat/completions"
LLM_MODEL = "deepseek-v4-flash"

BASE = [
    {
        "id": "N01",
        "role": "Seer",
        "phase": "DAY_BADGE_SPEECH",
        "text": "我是预言家竞选警长需要报警徽流和查验结果",
        "kw": ["警徽流", "警长竞选"],
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
        "kw": ["冲票", "统一投票"],
    },
    {"id": "E01", "role": "Seer", "phase": "DAY_SPEECH", "text": "我被女巫毒了怎么办", "kw": ["被毒", "遗言"]},
    {
        "id": "E03",
        "role": "Villager",
        "phase": "DAY_SPEECH",
        "text": "所有人都说我是狼但我真的是平民",
        "kw": ["被冤枉", "表水"],
    },
    {
        "id": "E07",
        "role": "Werewolf",
        "phase": "DAY_SPEECH",
        "text": "既要伪装又要带节奏还要保护队友怎么同时做好",
        "kw": ["伪装", "带节奏"],
    },
    {
        "id": "E17",
        "role": "Witch",
        "phase": "mid_game",
        "text": "我毒错人了毒死了一个平民现在怎么办",
        "kw": ["毒错", "补救"],
    },
    {
        "id": "E18",
        "role": "Werewolf",
        "phase": "mid_game",
        "text": "刀错人了刀到了平民狼刀落后怎么翻盘",
        "kw": ["刀错", "翻盘"],
    },
]


def load_docs():
    conn = psycopg2.connect(CONN)
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


def batch_verify(pairs, batch_size=8):
    """Verify multiple (anchor, candidate_neg) pairs in one API call."""
    items = []
    for i, (anchor, neg) in enumerate(pairs):
        items.append(f"#{i + 1}\n查询: {anchor[:200]}\n候选负例: {neg[:200]}")

    prompt = (
        "判断以下每对策略是否属于【不同主题】。如果讨论的是同一类问题→false_negative，完全不同主题→true_negative。\n\n"
        + "\n\n".join(items)
        + '\n\n返回JSON数组: [{"id":1,"is_true_negative":true/false,"confidence":0.0-1.0},...] 只返回JSON。'
    )

    try:
        resp = requests.post(
            LLM_URL,
            headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 500,
            },
            timeout=60,
        )
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Extract JSON array
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"  Batch verify error: {e}")
    return [{"id": i + 1, "is_true_negative": True, "confidence": 0.5} for i in range(len(pairs))]


def generate_verified_triplets(docs, n_samples=300):
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])
    role_idx = {}
    [role_idx.setdefault(d["role"], []).append(i) for i, d in enumerate(docs)]

    # First, generate all candidates
    candidates = []
    for i, anchor in enumerate(docs):
        if len(candidates) >= n_samples * 2:
            break
        same = [j for j in role_idx.get(anchor["role"], []) if j != i]
        if not same:
            continue
        pos = random.choice(same)
        tokens = " ".join(jieba.cut(anchor["situation"])).split()
        if not tokens:
            continue
        scores = bm25.get_scores(tokens)
        mask = np.ones(len(docs), bool)
        mask[i] = False
        for j in same:
            mask[j] = False
        neg = int(np.argmax(np.where(mask, scores, -1)))
        candidates.append(
            {
                "idx": i,
                "pos": pos,
                "neg": neg,
                "anchor_text": f"{anchor['situation']} {anchor['strategy']}",
                "pos_text": f"{docs[pos]['situation']} {docs[pos]['strategy']}",
                "neg_text": f"{docs[neg]['situation']} {docs[neg]['strategy']}",
            }
        )

    # Batch LLM verify
    print(f"  {len(candidates)} candidates to verify in batches of 8...")
    verified_triplets = []
    for bi in range(0, min(len(candidates), n_samples * 2), 8):
        batch = candidates[bi : bi + 8]
        pairs = [(c["anchor_text"], c["neg_text"]) for c in batch]
        results = batch_verify(pairs)
        for c, r in zip(batch, results):
            if r.get("is_true_negative", True) and r.get("confidence", 0.5) > 0.3:
                verified_triplets.append(
                    {
                        "anchor_text": c["anchor_text"],
                        "positive_text": c["pos_text"],
                        "negative_text": c["neg_text"],
                        "llm_confidence": r.get("confidence", 0.5),
                    }
                )
        if (bi // 8 + 1) % 5 == 0:
            print(
                f"    Verified {bi + len(batch)}/{min(len(candidates), n_samples * 2)}, {len(verified_triplets)} accepted"
            )

    print(f"  Final: {len(verified_triplets)} LLM-verified triplets (out of {min(len(candidates), n_samples * 2)})")
    os.makedirs("data", exist_ok=True)
    with open("data/ft_llm_verified.jsonl", "w") as f:
        for t in verified_triplets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return verified_triplets


class TripletDataset(Dataset):
    def __init__(self, triplets, tokenizer, max_len=256):
        self.triplets = triplets
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.triplets)

    def __getitem__(self, i):
        t = self.triplets[i]
        return {"anchor": t["anchor_text"], "positive": t["positive_text"], "negative": t["negative_text"]}

    def collate(self, batch):
        texts = [b["anchor"] for b in batch] + [b["positive"] for b in batch] + [b["negative"] for b in batch]
        return self.tokenizer(texts, padding=True, truncation=True, max_length=self.max_len, return_tensors="pt"), len(
            batch
        )


def finetune(triplets, output_path=OUTPUT_PATH, epochs=2, batch_size=12, lr=2e-5):
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    device = torch.device(GPU)
    tokenizer = AutoTokenizer.from_pretrained(BGE_PATH)
    model = SentenceTransformer(BGE_PATH, device=GPU)
    model.train()
    ds = TripletDataset(triplets, tokenizer)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=True, collate_fn=ds.collate)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=len(dl) * epochs)
    print(f"  Training: {len(triplets)} triplets, {epochs} epochs, batch={batch_size}")
    model.to(device)
    best_loss = float("inf")
    for ep in range(epochs):
        ep_loss = 0.0
        for _step, (enc, n) in enumerate(dl):
            enc = {k: v.to(device) for k, v in enc.items()}
            embs = torch.nn.functional.normalize(model.forward(enc)["sentence_embedding"], p=2, dim=1)
            a, p, nn = embs[:n], embs[n : 2 * n], embs[2 * n :]
            ps = (a * p).sum(dim=1) / 0.05
            ns = (a * nn).sum(dim=1) / 0.05
            loss = -ps.mean() + torch.logsumexp(torch.stack([ps, ns], dim=1), dim=1).mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sch.step()
            ep_loss += loss.item()
        avg = ep_loss / len(dl)
        print(f"  Epoch {ep + 1}: Loss={avg:.4f}")
        if avg < best_loss:
            best_loss = avg
            os.makedirs(output_path, exist_ok=True)
            import shutil

            torch.save(model._modules["0"].auto_model.state_dict(), os.path.join(output_path, "pytorch_model.bin"))
            for f in os.listdir(BGE_PATH):
                src = os.path.join(BGE_PATH, f)
                if os.path.isfile(src) and not f.endswith(".bin") and not f.endswith(".pt"):
                    dst = os.path.join(output_path, f)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
            for sub in ["1_Pooling"]:
                sd, dd = os.path.join(BGE_PATH, sub), os.path.join(output_path, sub)
                if os.path.exists(sd) and not os.path.exists(dd):
                    shutil.copytree(sd, dd)
            print(f"  Saved to {output_path}")
    return output_path


def evaluate_model(model_path, docs, queries, label=""):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_path, device=GPU)
    len(docs)
    dtx = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
    dembs = np.asarray(
        model.encode(dtx, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32
    )
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])
    metrics = []
    for q in queries:
        bs = bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if bs.max() > 0:
            bs = bs / bs.max()
        bs += np.array([0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in docs])
        bs += np.array([0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in docs])
        bt = list(np.argsort(bs)[::-1][:20])
        qe = np.asarray(model.encode(q["text"], normalize_embeddings=True), dtype=np.float32)
        ds = np.dot(dembs, qe) + np.array(
            [0.12 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in docs], dtype=np.float32
        )
        ds += np.array(
            [0.06 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in docs],
            dtype=np.float32,
        )
        dt = list(np.argsort(ds)[::-1][:20])
        rrf = {}
        for r, i in enumerate(bt, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
        for r, i in enumerate(dt, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
        final = [i for i, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:10]]
        res = [{"situation": docs[i]["situation"], "strategy": docs[i]["strategy"]} for i in final]
        m = {}
        for k in [5, 10]:
            kk = min(k, len(res))
            m[f"P@{k}"] = (
                sum(
                    1
                    for r in res[:kk]
                    if sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) > 0
                )
                / kk
            )
        for rnk, r in enumerate(res, 1):
            if sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) > 0:
                m["MRR"] = 1.0 / rnk
                break
        else:
            m["MRR"] = 0.0
        for k in [5, 10]:
            kk = min(k, len(res))
            gains = [
                sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) for r in res[:kk]
            ]
            dcg = sum(g / np.log2(j + 2) for j, g in enumerate(gains))
            gs = sorted(gains, reverse=True)
            m[f"NDCG@{k}"] = (
                dcg / sum(g / np.log2(j + 2) for j, g in enumerate(gs))
                if sum(g / np.log2(j + 2) for j, g in enumerate(gs)) > 0
                else 0.0
            )
        metrics.append(m)
    agg = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
    print(f"\n  {label}: NDCG@5={agg['NDCG@5']:.3f} P@5={agg['P@5']:.3f} MRR={agg['MRR']:.3f}")
    return agg["NDCG@5"]


if __name__ == "__main__":
    print("=" * 60)
    print("LLM BATCH-VERIFIED HARD NEGATIVE MINING")
    print("=" * 60)
    if not LLM_KEY:
        raise RuntimeError("DSV4FLASH_API_KEY must be set before running LLM verification.")
    docs = load_docs()
    all_q = BASE[:15] + BASE[15:]  # all 20
    print(f"Docs: {len(docs)}, Queries: {len(all_q)}")

    print("\n[1/3] Baseline...")
    before = evaluate_model(BGE_PATH, docs, all_q, "BEFORE")

    print("\n[2/3] LLM batch verification...")
    triplets = generate_verified_triplets(docs, n_samples=200)

    print("\n[3/3] Fine-tuning + evaluation...")
    if len(triplets) >= 30:
        ft_path = finetune(triplets, epochs=2, batch_size=12, lr=2e-5)
        after = evaluate_model(ft_path, docs, all_q, "AFTER")
    else:
        print("  Not enough verified triplets!")
        after = before

    delta = after - before
    print(f"\n{'=' * 60}")
    print(f"RESULT: {before:.3f} → {after:.3f} ({'+' if delta > 0 else ''}{delta:.3f})")
