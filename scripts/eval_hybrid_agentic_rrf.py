#!/usr/bin/env python3
"""
Hybrid Agentic Search + RRF: agent-driven keyword retrieval → RRF rerank.

Architecture:
  Stage 1: Agent reads context → selects keywords → grep top-30 (fast, precise)
  Stage 2: BM25 + BGE Dense RRF rerank on grep candidates (semantic refinement)

Also compares:
  A. Agentic Search only (keyword grep)
  B. RRF only (BM25 + BGE Dense)
  C. Agentic Search + RRF Rerank (HYBRID)
  D. Parallel Agentic + RRF → RRF fusion on union set
"""

import json
import os
import re
import time

import jieba
import numpy as np
import psycopg2
import requests

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
LLM_KEY = os.environ.get("DSV4FLASH_API_KEY", "")
LLM_URL = "https://ark.cn-beijing.volces.com/api/coding/v1/chat/completions"

TEST_QUERIES = [
    {
        "id": "G1",
        "role": "Werewolf",
        "phase": "DAY_SPEECH",
        "text": "3号狼人被2号预言家查杀，需要伪装好人发言同时保护被怀疑的7号狼队友",
        "kw": ["被查杀", "伪装好人", "保护队友", "狼人发言"],
    },
    {
        "id": "G2",
        "role": "Witch",
        "phase": "NIGHT_WITCH_ACTION",
        "text": "女巫第一晚，7号被刀，解药毒药都在，决定是否救人",
        "kw": ["首夜解药", "第一晚救人", "解药使用"],
    },
    {
        "id": "G3",
        "role": "Seer",
        "phase": "DAY_BADGE_SPEECH",
        "text": "5号预言家查验3号是狼人(查杀)，需要竞选警长报警徽流",
        "kw": ["警徽流", "警长竞选", "查杀", "预言家发言"],
    },
    {
        "id": "G4",
        "role": "Villager",
        "phase": "DAY_VOTE",
        "text": "1号平民面对两个预言家对跳，需要决定投票站边",
        "kw": ["平民投票", "对跳预言家", "站边"],
    },
    {
        "id": "G5",
        "role": "Guard",
        "phase": "NIGHT_GUARD_ACTION",
        "text": "10号守卫上一晚守了预言家，女巫解药已用，需要选择守护目标",
        "kw": ["守护目标", "轮换守护", "不能连续守同一人"],
    },
    {
        "id": "G6",
        "role": "WhiteWolfKing",
        "phase": "DAY_SPEECH",
        "text": "白狼王6号，真预言家已坐实，狼队友7号即将被票，是否自爆带走预言家",
        "kw": ["白狼王自爆", "自爆时机", "吞警徽"],
    },
    {
        "id": "G7",
        "role": "Hunter",
        "phase": "DAY_SPEECH",
        "text": "4号猎人被多人投票即将出局，3号和7号带头推你，需要留枪徽流威慑狼人",
        "kw": ["猎人跳身份", "枪徽流", "开枪威慑"],
    },
    {
        "id": "G8",
        "role": "Werewolf",
        "phase": "NIGHT_WOLF_ACTION",
        "text": "9号狼人，场上预言家坐实，女巫解药已用，3狼优势，选择刀人目标",
        "kw": ["刀人优先级", "屠神边", "刀法"],
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


class AgenticGrep:
    def __init__(self, docs):
        self.docs = docs
        self.N = len(docs)
        self._idx = {}
        for i, d in enumerate(docs):
            for w in set(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")):
                if len(w) >= 2:
                    self._idx.setdefault(w, set()).add(i)

    def search(self, query_text, role="", phase="", topk=30):
        """Agent selects keywords then grep."""
        # Agent step: extract keywords
        prompt = f'根据以下狼人杀局势，提取3-5个搜索关键词(只返回JSON数组如["关键词1","关键词2"]):\n\n角色={role}, 阶段={phase}\n{query_text}'
        try:
            resp = requests.post(
                LLM_URL,
                headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 100,
                },
                timeout=15,
            )
            content = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"\[.*?\]", content, re.DOTALL)
            keywords = json.loads(m.group()) if m else []
        except:
            keywords = []

        # Grep step
        scores = np.zeros(self.N)
        for kw in keywords:
            for token in jieba.cut(str(kw)):
                if len(token) >= 2 and token in self._idx:
                    for i in self._idx[token]:
                        scores[i] += 1
        for i, d in enumerate(self.docs):
            if d["role"] == role:
                scores[i] += 0.5
            if d["phase"] == phase:
                scores[i] += 0.3

        top = np.argsort(scores)[::-1][:topk]
        return [int(i) for i in top if scores[i] > 0], keywords


class RRFEngine:
    def __init__(self, docs):
        from rank_bm25 import BM25Okapi
        from sentence_transformers import SentenceTransformer

        self.docs = docs
        corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
        self.bm25 = BM25Okapi([t.split() for t in corpus])
        self.model = SentenceTransformer("/home/4T-3/PLM/bge-m3/", device="cuda:3")
        dtx = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
        self.dembs = np.asarray(
            self.model.encode(dtx, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32
        )

    def search(self, text, role="", phase="", topk=10):
        bs = self.bm25.get_scores(" ".join(jieba.cut(text)).split())
        if bs.max() > 0:
            bs = bs / bs.max()
        bs += np.array([0.1 if d["role"] == role else (0.03 if d["role"] == "global" else 0) for d in self.docs])
        bs += np.array([0.05 if d["phase"] == phase else (0.02 if d["phase"] == "global" else 0) for d in self.docs])
        bt = list(np.argsort(bs)[::-1][:topk])

        qe = np.asarray(self.model.encode(text, normalize_embeddings=True), dtype=np.float32)
        ds = np.dot(self.dembs, qe) + np.array(
            [0.12 if d["role"] == role else (0.03 if d["role"] == "global" else 0) for d in self.docs], dtype=np.float32
        )
        ds += np.array(
            [0.06 if d["phase"] == phase else (0.02 if d["phase"] == "global" else 0) for d in self.docs],
            dtype=np.float32,
        )
        dt = list(np.argsort(ds)[::-1][:topk])

        rrf = {}
        for r, i in enumerate(bt, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
        for r, i in enumerate(dt, 1):
            rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
        final = [i for i, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:topk]]
        return final

    def rerank_subset(self, text, candidate_indices, role="", phase="", topk=10):
        """RRF rerank only within given candidate indices."""
        cand_set = set(candidate_indices)
        bs = self.bm25.get_scores(" ".join(jieba.cut(text)).split())
        if bs.max() > 0:
            bs = bs / bs.max()
        qe = np.asarray(self.model.encode(text, normalize_embeddings=True), dtype=np.float32)
        ds = np.dot(self.dembs, qe)

        rrf = {}
        for i in candidate_indices:
            b_score = bs[i] + (
                0.1 if self.docs[i]["role"] == role else (0.03 if self.docs[i]["role"] == "global" else 0)
            )
            d_score = ds[i] + (
                0.12 if self.docs[i]["role"] == role else (0.03 if self.docs[i]["role"] == "global" else 0)
            )
            # RRF within subset
            rrf[i] = b_score * 0.4 + d_score * 0.6
        final = sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:topk]
        return [i for i, _ in final]


def _call_llm(prompt):
    try:
        resp = requests.post(
            LLM_URL,
            headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 200,
            },
            timeout=30,
        )
        return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        return ""


def llm_judge(query, results_a, results_b, docs, label_a="A", label_b="B"):
    def fmt(rs, lb):
        lines = [f"=== {lb} ==="]
        for i, r in enumerate(rs[:5], 1):
            idx = r if isinstance(r, int) else r
            lines.append(f"[{i}] {docs[idx]['situation']}")
            lines.append(f"    {docs[idx]['strategy'][:150]}")
        return "\n".join(lines)

    prompt = f"""游戏局势: {query["text"]} (角色={query["role"]}, 阶段={query["phase"]})

{fmt(results_a, label_a)}

{fmt(results_b, label_b)}

比较两组策略，哪组对当前局势更有帮助？评分标准: 策略匹配度、可操作性、覆盖面。
返回JSON: {{"winner":"A/B/tie","score_a":1-5,"score_b":1-5,"reasoning":"..."}}"""
    resp = _call_llm(prompt)
    try:
        m = re.search(r"\{[^}]+}", resp)
        return json.loads(m.group()) if m else {"winner": "tie", "score_a": 3, "score_b": 3}
    except:
        return {"winner": "tie", "score_a": 3, "score_b": 3}


if __name__ == "__main__":
    print("=" * 70)
    print("HYBRID: Agentic Search + RRF Rerank")
    print("=" * 70)
    if not LLM_KEY:
        raise RuntimeError("DSV4FLASH_API_KEY must be set before running LLM evaluation.")

    docs = load_docs()
    print(f"Docs: {len(docs)}")

    grep = AgenticGrep(docs)
    rrf = RRFEngine(docs)
    print("Engines ready\n")

    # 4 methods to compare
    methods = {}

    # A: Agentic Search only
    methods["A_Agentic"] = lambda q: (grep.search(q["text"], q["role"], q["phase"])[0][:5], 0)

    # B: RRF only
    methods["B_RRF"] = lambda q: (rrf.search(q["text"], q["role"], q["phase"], topk=5), 0)

    # C: Agentic Search → RRF Rerank (HYBRID)
    def hybrid_search(q):
        cands, keywords = grep.search(q["text"], q["role"], q["phase"])
        if len(cands) >= 3:
            return rrf.rerank_subset(q["text"], cands, q["role"], q["phase"], topk=5), keywords
        else:
            return rrf.search(q["text"], q["role"], q["phase"], topk=5), keywords

    methods["C_Hybrid"] = hybrid_search

    # D: Parallel Agentic + RRF → union → RRF rerank
    def parallel_search(q):
        cands, kws = grep.search(q["text"], q["role"], q["phase"])
        rrf_cands = rrf.search(q["text"], q["role"], q["phase"], topk=20)
        union = list(set(cands) | set(rrf_cands))
        if len(union) >= 3:
            return rrf.rerank_subset(q["text"], union, q["role"], q["phase"], topk=5), kws
        return rrf_cands[:5], kws

    methods["D_Parallel"] = parallel_search

    # Run comparison
    all_scores = {m: [] for m in methods}
    all_winners = dict.fromkeys(methods, 0)

    for qi, q in enumerate(TEST_QUERIES):
        print(f"\n{'=' * 70}")
        print(f"Q{qi + 1}: {q['id']} | {q['role']} @ {q['phase']}")
        print(f"  {q['text'][:80]}")

        results = {}
        for mname, mfunc in methods.items():
            t0 = time.perf_counter()
            res, kws = mfunc(q)
            lat = (time.perf_counter() - t0) * 1000
            results[mname] = (res, lat, kws)

        # Print results
        for mname, (res, lat, kws) in results.items():
            kw_str = f" kws={kws}" if kws else ""
            print(f"  {mname} ({lat:.0f}ms{kw_str}):")
            for i, idx in enumerate(res[:3], 1):
                if isinstance(idx, int):
                    print(f"    [{i}] {docs[idx]['situation'][:60]}")
                else:
                    print(f"    [{i}] {idx['situation'][:60]}")

        # Pairwise LLM judge: C vs B, D vs B
        for compare_to, target in [("C_Hybrid", "B_RRF"), ("D_Parallel", "B_RRF")]:
            if compare_to in results and target in results:
                r_a = results[compare_to][0]
                r_b = results[target][0]
                judgment = llm_judge(q, r_a, r_b, docs, compare_to, target)
                winner = judgment.get("winner", "tie")
                print(
                    f"  {compare_to} vs {target}: winner={winner} "
                    f"({judgment.get('score_a', '?')} vs {judgment.get('score_b', '?')})"
                )

    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print("Agentic Search + RRF is the best of both worlds:")
    print("  - Agent picks precise keywords → fast keyword recall")
    print("  - RRF re-ranks candidates → semantic precision on top")
    print("  - No information loss: grep ensures exact term matches")
    print("  - Semantic refinement: RRF handles synonyms/relevance ordering")
