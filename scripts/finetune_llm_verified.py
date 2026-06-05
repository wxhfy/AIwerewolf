#!/usr/bin/env python3
"""
LLM-Verified Hard Negative Mining for BGE-M3 Fine-tuning.

Pipeline:
  1. BM25 generates candidate hard negatives
  2. DeepSeek-v4-Flash verifies each negative is truly IRRELEVANT
  3. Filter out false negatives (BM25 top-match that's actually relevant)
  4. Fine-tune BGE-M3 with clean triplets
  5. Evaluate before vs after
"""

import json
import os
import random
import sys
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

sys.path.insert(0, ".")

CONN = os.environ.get("DATABASE_URL", "")
BGE_PATH = "/home/4T-3/PLM/bge-m3/"
GPU = "cuda:3"
OUTPUT_PATH = "/home/4T-3/PLM/bge-m3-werewolf-ft-v2/"

# LLM config
LLM_API_KEY = os.environ.get("DSV4FLASH_API_KEY", "")
LLM_BASE_URL = os.environ.get("DSV4FLASH_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v1")
LLM_MODEL = os.environ.get("DSV4FLASH_MODEL", "deepseek-v4-flash")

# Test queries
BASE_QUERIES = [
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
        "id": "N05",
        "role": "Villager",
        "phase": "DAY_SPEECH",
        "text": "我是平民需要给出有价值的发言分析局势",
        "kw": ["平民发言", "发言质量"],
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
        "kw": ["冲票", "统一投票"],
    },
]
SPECIAL_QUERIES = [
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
    {"id": "E13", "role": "global", "phase": "mid_game", "text": "剩1狼2民1神怎么投", "kw": ["残局", "轮次"]},
    {
        "id": "E06",
        "role": "Seer",
        "phase": "DAY_BADGE_SPEECH",
        "text": "我是预言家有查杀但对跳也出现了警徽流怎么安排",
        "kw": ["对跳", "警徽流"],
    },
]

# ============================================================
# Data loading
# ============================================================


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


# ============================================================
# LLM Verification
# ============================================================


def llm_verify_negative(anchor, candidate_neg, positive=None, max_retries=2):
    """Ask LLM: is candidate_neg truly irrelevant to anchor?

    Returns: (is_truly_negative: bool, confidence: float, reasoning: str)
    """
    prompt = f"""你是狼人杀策略专家。判断以下两条策略内容是否属于【不同主题/不同场景】。

策略A（查询场景）：
{anchor[:300]}

策略B（候选负例）：
{candidate_neg[:300]}

判断标准：
- 如果B和A讨论的是【同一类问题】（如同为"预言家警徽流"相关），则B是【假负例(false_negative)】
- 如果B和A讨论的是【完全不同的策略主题】，则B是【真负例(true_negative)】
- 角色相同但策略主题不同（如A讲"预言家验人"、B讲"预言家投票"）也算真负例

请只回复一个JSON：
{{"is_true_negative": true/false, "confidence": 0.0-1.0, "reasoning": "一句话理由"}}"""

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
                timeout=30,
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Extract JSON from response
            import re

            m = re.search(r"\{[^}]+\}", content)
            if m:
                result = json.loads(m.group())
                return (
                    result.get("is_true_negative", True),
                    result.get("confidence", 0.5),
                    result.get("reasoning", ""),
                )
            return (True, 0.5, "parse failed")
        except Exception as e:
            if attempt == max_retries - 1:
                return (True, 0.3, f"error: {e}")
            time.sleep(2)

    return (True, 0.3, "max retries")


# ============================================================
# Triplet Generation + LLM Verification
# ============================================================


def generate_verified_triplets(docs, n_samples=300, verify_ratio=0.5):
    """Generate triplets and LLM-verify hard negatives.

    verify_ratio: fraction of candidates to verify with LLM (0.5 = verify 50%)
    """
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])
    role_indices = {}
    for i, d in enumerate(docs):
        role_indices.setdefault(d["role"], []).append(i)

    triplets = []
    verified_count = 0
    rejected_count = 0

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
        for j in same_role:
            mask[j] = False
        masked = np.where(mask, scores, -1)
        neg_idx = int(np.argmax(masked))

        anchor_text = f"{anchor['situation']} {anchor['strategy']}"
        neg_text = f"{docs[neg_idx]['situation']} {docs[neg_idx]['strategy']}"
        pos_text = f"{docs[pos_idx]['situation']} {docs[pos_idx]['strategy']}"

        # LLM verification (for a subset to control cost)
        should_verify = random.random() < verify_ratio
        if should_verify:
            is_neg, conf, reason = llm_verify_negative(anchor_text, neg_text)
            if is_neg and conf > 0.4:
                triplets.append(
                    {
                        "anchor_text": anchor_text,
                        "positive_text": pos_text,
                        "negative_text": neg_text,
                        "llm_verified": True,
                        "llm_confidence": conf,
                    }
                )
                verified_count += 1
            else:
                rejected_count += 1
                # Use a different negative or skip
                if len(same_role) < len(docs) - 2:
                    # Try second-best BM25 negative
                    masked[neg_idx] = False  # mask this one
                    neg_idx2 = int(np.argmax(np.where(mask, scores, -1)))
                    neg_text2 = f"{docs[neg_idx2]['situation']} {docs[neg_idx2]['strategy']}"
                    is_neg2, conf2, _ = llm_verify_negative(anchor_text, neg_text2)
                    if is_neg2 and conf2 > 0.4:
                        triplets.append(
                            {
                                "anchor_text": anchor_text,
                                "positive_text": pos_text,
                                "negative_text": neg_text2,
                                "llm_verified": True,
                                "llm_confidence": conf2,
                            }
                        )
                        verified_count += 1
                    else:
                        rejected_count += 1
        else:
            # Unverified: include directly (fallback)
            triplets.append(
                {
                    "anchor_text": anchor_text,
                    "positive_text": pos_text,
                    "negative_text": neg_text,
                    "llm_verified": False,
                    "llm_confidence": 0.0,
                }
            )

    print(
        f"  Generated {len(triplets)} triplets "
        f"({verified_count} LLM-verified, {rejected_count} rejected, "
        f"{len(triplets) - verified_count} unverified)"
    )

    os.makedirs("data", exist_ok=True)
    with open("data/ft_llm_verified.jsonl", "w") as f:
        for t in triplets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print("  Saved to data/ft_llm_verified.jsonl")

    return triplets


# ============================================================
# Fine-tuning (same as before, with torch)
# ============================================================


class TripletDataset(Dataset):
    def __init__(self, triplets, tokenizer, max_len=256):
        self.triplets = triplets
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.triplets)

    def __getitem__(self, idx):
        t = self.triplets[idx]
        return {"anchor": t["anchor_text"], "positive": t["positive_text"], "negative": t["negative_text"]}

    def collate(self, batch):
        all_texts = [b["anchor"] for b in batch] + [b["positive"] for b in batch] + [b["negative"] for b in batch]
        encoded = self.tokenizer(all_texts, padding=True, truncation=True, max_length=self.max_len, return_tensors="pt")
        return encoded, len(batch)


def finetune(triplets, output_path=OUTPUT_PATH, epochs=2, batch_size=12, lr=2e-5):
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    device = torch.device(GPU)
    tokenizer = AutoTokenizer.from_pretrained(BGE_PATH)
    model = SentenceTransformer(BGE_PATH, device=GPU)
    model.train()

    dataset = TripletDataset(triplets, tokenizer)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, collate_fn=dataset.collate)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    total_steps = len(loader) * epochs
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=total_steps)

    print(f"  Training: {len(triplets)} triplets, {epochs} epochs, batch={batch_size}")

    model.to(device)
    best_loss = float("inf")

    for epoch in range(epochs):
        epoch_loss = 0.0
        for _step, (encoded, n_anchors) in enumerate(loader):
            encoded = {k: v.to(device) for k, v in encoded.items()}
            outputs = model.forward(encoded)
            all_embs = nn.functional.normalize(outputs["sentence_embedding"], p=2, dim=1)

            anchor_emb = all_embs[:n_anchors]
            pos_emb = all_embs[n_anchors : 2 * n_anchors]
            neg_emb = all_embs[2 * n_anchors :]

            pos_sim = (anchor_emb * pos_emb).sum(dim=1)
            neg_sim = (anchor_emb * neg_emb).sum(dim=1)

            pos_scores = pos_sim / 0.05
            neg_scores = neg_sim / 0.05

            loss = -pos_scores.mean() + torch.logsumexp(torch.stack([pos_scores, neg_scores], dim=1), dim=1).mean()

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            epoch_loss += loss.item()

        avg_loss = epoch_loss / len(loader)
        print(f"  Epoch {epoch + 1}: Avg Loss={avg_loss:.4f}")

        if avg_loss < best_loss:
            best_loss = avg_loss
            os.makedirs(output_path, exist_ok=True)
            import shutil

            transformer = model._modules["0"].auto_model
            torch.save(transformer.state_dict(), os.path.join(output_path, "pytorch_model.bin"))
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


# ============================================================
# Evaluation (same as before)
# ============================================================


def evaluate_model(model_path, docs, queries, label=""):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_path, device=GPU)
    len(docs)
    doc_texts = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]

    doc_embs = np.asarray(
        model.encode(doc_texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32
    )
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    metrics = []
    for q in queries:
        b_scores = bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if b_scores.max() > 0:
            b_scores = b_scores / b_scores.max()
        b_scores += np.array([0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in docs])
        b_scores += np.array(
            [0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in docs]
        )
        b_top = list(np.argsort(b_scores)[::-1][:20])

        qe = np.asarray(model.encode(q["text"], normalize_embeddings=True), dtype=np.float32)
        sims = np.dot(doc_embs, qe)
        d_scores = sims + np.array(
            [0.12 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in docs], dtype=np.float32
        )
        d_scores += np.array(
            [0.06 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in docs],
            dtype=np.float32,
        )
        d_top = list(np.argsort(d_scores)[::-1][:20])

        rrf = {}
        for rank, i in enumerate(b_top, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + rank)
        for rank, i in enumerate(d_top, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + rank)
        final = [i for i, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:10]]

        res = [{"situation": docs[i]["situation"], "strategy": docs[i]["strategy"]} for i in final]
        m = {}
        for k in [5, 10]:
            kk = min(k, len(res))
            rel = [
                1 if sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) > 0 else 0
                for r in res[:kk]
            ]
            m[f"P@{k}"] = sum(rel) / max(kk, 1)
        for rank2, r in enumerate(res, 1):
            if sum(1 for kw in q["kw"] if kw.lower() in f"{r['situation']} {r['strategy']}".lower()) > 0:
                m["MRR"] = 1.0 / rank2
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
            idcg = sum(g / np.log2(j + 2) for j, g in enumerate(gs))
            m[f"NDCG@{k}"] = dcg / idcg if idcg > 0 else 0.0
        metrics.append(m)

    agg = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
    base_m = [metrics[i] for i in range(min(20, len(queries)))]
    spec_m = [metrics[i] for i in range(min(20, len(queries)), len(queries))]
    b_ndcg = np.mean([q["NDCG@5"] for q in base_m]) if base_m else 0
    s_ndcg = np.mean([q["NDCG@5"] for q in spec_m]) if spec_m else 0
    print(
        f"\n  {label} (BM25+RRF): NDCG@5={agg['NDCG@5']:.3f} P@5={agg['P@5']:.3f} MRR={agg['MRR']:.3f} Base={b_ndcg:.3f} Spec={s_ndcg:.3f}"
    )
    return agg["NDCG@5"]


# ================================================================
# Main
# ================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("LLM-VERIFIED HARD NEGATIVE MINING + FINE-TUNING")
    print("=" * 70)
    if not CONN:
        raise RuntimeError("DATABASE_URL must be set before running fine-tuning.")
    if not LLM_API_KEY:
        raise RuntimeError("DSV4FLASH_API_KEY must be set before running LLM verification.")

    docs = load_docs()
    all_q = BASE_QUERIES + SPECIAL_QUERIES
    print(f"Docs: {len(docs)}, Queries: {len(all_q)}")

    # BEFORE
    print("\n[1/4] Baseline (zero-shot)...")
    before_ndcg = evaluate_model(BGE_PATH, docs, all_q, "BEFORE")

    # Generate + LLM verify
    print("\n[2/4] Generating + LLM-verifying hard negatives...")
    print(f"  LLM: {LLM_MODEL}")
    triplets = generate_verified_triplets(docs, n_samples=400, verify_ratio=0.5)
    # Use only verified triplets for best quality
    verified_only = [t for t in triplets if t.get("llm_verified")]
    print(f"  Using {len(verified_only)} LLM-verified triplets for training")

    # Fine-tune
    print("\n[3/4] Fine-tuning with verified triplets...")
    if len(verified_only) >= 50:
        ft_path = finetune(verified_only, epochs=2, batch_size=12, lr=2e-5)
    else:
        print("  Not enough verified triplets, using all triplets")
        ft_path = finetune(triplets, epochs=2, batch_size=12, lr=2e-5)

    # AFTER
    print("\n[4/4] Evaluating after fine-tuning...")
    after_ndcg = evaluate_model(ft_path, docs, all_q, "AFTER")

    # Final
    delta = after_ndcg - before_ndcg
    print(f"\n{'=' * 70}")
    print(f"RESULT: NDCG@5 {before_ndcg:.3f} → {after_ndcg:.3f} ({'+' if delta > 0 else ''}{delta:.3f})")
    print(f"Model: {ft_path}")
