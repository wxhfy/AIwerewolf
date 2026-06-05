#!/usr/bin/env python3
"""Quick LLM-verified fine-tuning: 60 verified triplets, 1 epoch."""

import json
import os
import random
import re
import time

import jieba
import numpy as np
import psycopg2
import requests
import torch
import torch.nn as nn
from rank_bm25 import BM25Okapi
from torch.utils.data import DataLoader
from torch.utils.data import Dataset

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
BGP = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
OUT = "/home/4T-3/PLM/bge-m3-werewolf-ft-v3/"
LK = os.environ.get("DSV4FLASH_API_KEY", "")
LU = "https://ark.cn-beijing.volces.com/api/coding/v1/chat/completions"

QUERIES = [
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
        "id": "N11",
        "role": "WhiteWolfKing",
        "phase": "DAY_SPEECH",
        "text": "白狼王什么时候自爆带走关键好人最合适",
        "kw": ["白狼王自爆", "自爆时机"],
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
    {"id": "E01", "role": "Seer", "phase": "DAY_SPEECH", "text": "我被女巫毒了怎么办", "kw": ["被毒", "遗言"]},
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
]


def load_docs():
    c = psycopg2.connect(CONN).cursor()
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
    c.connection.close()
    return docs


def llm_verify_batch(pairs):
    items = "\n\n".join(f"#{i + 1}\nQ: {a[:150]}\nN: {n[:150]}" for i, (a, n) in enumerate(pairs))
    p = f'判断每对策略是否属于【不同主题】。同类问题=false_negative, 完全无关=true_negative。只返回JSON数组: [{{"id":1,"is_true_negative":true/false,"conf":0.0-1.0}},...]\n\n{items}'
    try:
        r = requests.post(
            LU,
            headers={"Authorization": f"Bearer {LK}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": p}],
                "temperature": 0.1,
                "max_tokens": 300,
            },
            timeout=30,
        )
        c = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", c, re.DOTALL)
        return (
            json.loads(m.group())
            if m
            else [{"id": i + 1, "is_true_negative": True, "conf": 0.5} for i in range(len(pairs))]
        )
    except:
        return [{"id": i + 1, "is_true_negative": True, "conf": 0.5} for i in range(len(pairs))]


class TD(Dataset):
    def __init__(s, t, tok, ml=256):
        s.t = t
        s.tok = tok
        s.ml = ml

    def __len__(s):
        return len(s.t)

    def __getitem__(s, i):
        return s.t[i]

    def collate(s, b):
        texts = [x["anchor_text"] for x in b] + [x["positive_text"] for x in b] + [x["negative_text"] for x in b]
        return s.tok(texts, padding=True, truncation=True, max_length=s.ml, return_tensors="pt"), len(b)


def evaluate(model_path, docs, queries):
    from sentence_transformers import SentenceTransformer

    m = SentenceTransformer(model_path, device=GPU)
    N = len(docs)
    dtx = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
    de = np.asarray(m.encode(dtx, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32)
    c2 = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm = BM25Okapi([t.split() for t in c2])
    metrics = []
    for q in queries:
        bs = bm.get_scores(" ".join(jieba.cut(q["text"])).split())
        if bs.max() > 0:
            bs = bs / bs.max()
        bs += np.array([0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in docs])
        bt = list(np.argsort(bs)[::-1][:20])
        qe = np.asarray(m.encode(q["text"], normalize_embeddings=True), dtype=np.float32)
        ds = np.dot(de, qe) + np.array(
            [0.12 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in docs], dtype=np.float32
        )
        dt = list(np.argsort(ds)[::-1][:20])
        rrf = {}
        for r, i in enumerate(bt, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
        for r, i in enumerate(dt, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
        final = [i for i, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:10]]
        res = [{"situation": docs[i]["situation"], "strategy": docs[i]["strategy"]} for i in final]
        mv = {}
        for k in [5, 10]:
            kk = min(k, len(res))
            mv[f"P@{k}"] = (
                sum(
                    1
                    for r in res[:kk]
                    if sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) > 0
                )
                / kk
            )
        for rnk, r in enumerate(res, 1):
            if sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) > 0:
                mv["MRR"] = 1.0 / rnk
                break
        else:
            mv["MRR"] = 0.0
        for k in [5, 10]:
            kk = min(k, len(res))
            gs = [
                sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) for r in res[:kk]
            ]
            dc = sum(g / np.log2(j + 2) for j, g in enumerate(gs))
            ig = sorted(gs, reverse=True)
            ic = sum(g / np.log2(j + 2) for j, g in enumerate(ig))
            mv[f"NDCG@{k}"] = dc / ic if ic > 0 else 0.0
        metrics.append(mv)
    agg = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
    return agg["NDCG@5"], agg


if __name__ == "__main__":
    print("=" * 50)
    print("LLM BATCH VERIFY + QUICK FINE-TUNE")
    print("=" * 50)
    if not LK:
        raise RuntimeError("DSV4FLASH_API_KEY must be set before running LLM verification.")
    docs = load_docs()
    print(f"Docs: {len(docs)}, Queries: {len(QUERIES)}")

    # Baseline
    print("\n[1] Baseline...")
    t0 = time.perf_counter()
    b_ndcg, b_agg = evaluate(BGP, docs, QUERIES)
    print(f"  NDCG@5={b_ndcg:.3f} P@5={b_agg['P@5']:.3f} MRR={b_agg['MRR']:.3f} ({time.perf_counter() - t0:.0f}s)")

    # Generate + verify candidates
    print("\n[2] Generate + LLM verify...")
    c2 = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']}")) for d in docs]
    bm = BM25Okapi([t.split() for t in c2])
    ri = {}
    [ri.setdefault(d["role"], []).append(i) for i, d in enumerate(docs)]

    pairs = []
    for i, anchor in enumerate(docs):
        if len(pairs) >= 60:
            break
        same = [j for j in ri.get(anchor["role"], []) if j != i]
        if not same:
            continue
        pos = random.choice(same)
        tokens = " ".join(jieba.cut(anchor["situation"])).split()
        if not tokens:
            continue
        scores = bm.get_scores(tokens)
        mask = np.ones(len(docs), bool)
        mask[i] = False
        for j in same:
            mask[j] = False
        neg = int(np.argmax(np.where(mask, scores, -1)))
        pairs.append(
            {
                "a": f"{anchor['situation']} {anchor['strategy']}",
                "p": f"{docs[pos]['situation']} {docs[pos]['strategy']}",
                "n": f"{docs[neg]['situation']} {docs[neg]['strategy']}",
            }
        )

    # Batch verify
    verified = []
    for bi in range(0, 60, 10):
        batch = [(p["a"], p["n"]) for p in pairs[bi : bi + 10]]
        results = llm_verify_batch(batch)
        for p, r in zip(pairs[bi : bi + 10], results):
            if r.get("is_true_negative", True):
                verified.append({"anchor_text": p["a"], "positive_text": p["p"], "negative_text": p["n"]})
        print(f"  Batch {bi // 10 + 1}: {len(verified)}/{bi + len(batch)} accepted")

    print(f"  Total verified: {len(verified)}")

    # Fine-tune
    print(f"\n[3] Fine-tune ({len(verified)} triplets, 1 epoch)...")
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    device = torch.device(GPU)
    tokenizer = AutoTokenizer.from_pretrained(BGP)
    model = SentenceTransformer(BGP, device=GPU)
    model.train()
    ds = TD(verified, tokenizer)
    dl = DataLoader(ds, batch_size=12, shuffle=True, collate_fn=ds.collate)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-5)
    model.to(device)
    for step, (enc, n) in enumerate(dl):
        enc = {k: v.to(device) for k, v in enc.items()}
        # Use underlying transformer directly for gradient flow
        transformer = model._modules["0"].auto_model
        out = transformer(**enc)
        # Mean pooling over token dim
        mask = enc["attention_mask"].unsqueeze(-1).float()
        embs = (out.last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1)
        norms = embs.norm(p=2, dim=1, keepdim=True).clamp(min=1e-8)
        embs = embs / norms
        a, p, nn = embs[:n], embs[n : 2 * n], embs[2 * n :]
        ps = (a * p).sum(dim=1) / 0.05
        ns = (a * nn).sum(dim=1) / 0.05
        loss = -ps.mean() + torch.logsumexp(torch.stack([ps, ns], dim=1), dim=1).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        if step % 5 == 0:
            print(f"  Step {step}/{len(dl)}: Loss={loss.item():.4f}")

    # Save
    os.makedirs(OUT, exist_ok=True)
    import shutil

    torch.save(model._modules["0"].auto_model.state_dict(), os.path.join(OUT, "pytorch_model.bin"))
    for f in os.listdir(BGP):
        src = os.path.join(BGP, f)
        if os.path.isfile(src) and not f.endswith(".bin") and not f.endswith(".pt"):
            dst = os.path.join(OUT, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
    for sub in ["1_Pooling"]:
        sd, dd = os.path.join(BGP, sub), os.path.join(OUT, sub)
        if os.path.exists(sd) and not os.path.exists(dd):
            shutil.copytree(sd, dd)
    print(f"  Saved to {OUT}")

    # Evaluate
    print("\n[4] Evaluate...")
    t0 = time.perf_counter()
    a_ndcg, a_agg = evaluate(OUT, docs, QUERIES)
    print(f"  NDCG@5={a_ndcg:.3f} P@5={a_agg['P@5']:.3f} MRR={a_agg['MRR']:.3f} ({time.perf_counter() - t0:.0f}s)")

    delta = a_ndcg - b_ndcg
    print(f"\n{'=' * 50}")
    print(f"RESULT: {b_ndcg:.3f} → {a_ndcg:.3f} ({'+' if delta > 0 else ''}{delta:.3f}, {delta / b_ndcg * 100:+.1f}%)")
    if a_ndcg > b_ndcg:
        print("✅ LLM verification improved fine-tuning!")
    else:
        print("⚠️ Still no improvement — zero-shot is the baseline")
