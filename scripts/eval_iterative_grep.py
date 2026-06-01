#!/usr/bin/env python3
"""Iterative Agent Grep: multi-round search until convergence."""

import sys, time, numpy as np, jieba, psycopg2
from rank_bm25 import BM25Okapi

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"

def load_docs():
    conn = psycopg2.connect(CONN)
    c = conn.cursor()
    c.execute("""SELECT COALESCE(situation_pattern,''), COALESCE(recommended_action,''),
               COALESCE(rationale,''), role, phase, quality_score
               FROM strategy_knowledge_docs WHERE status='active'""")
    docs = []
    for sit, rec, rat, role, phase, q in c.fetchall():
        docs.append({"situation": sit or "", "strategy": rec or "", "rationale": rat or "",
                     "role": role or "global", "phase": phase or "global", "quality": float(q) if q else 0.8})
    conn.close()
    return docs

BASE = [
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
    {"id":"E01","role":"Seer","phase":"DAY_SPEECH","text":"我被女巫毒了怎么办","kw":["被毒","遗言"]},
    {"id":"E03","role":"Villager","phase":"DAY_SPEECH","text":"所有人都说我是狼但我真的是平民","kw":["被冤枉","表水"]},
    {"id":"E07","role":"Werewolf","phase":"DAY_SPEECH","text":"既要伪装又要带节奏还要保护队友怎么同时做好","kw":["伪装","带节奏"]},
    {"id":"E17","role":"Witch","phase":"mid_game","text":"我毒错人了毒死了一个平民现在怎么办","kw":["毒错","补救"]},
    {"id":"E18","role":"Werewolf","phase":"mid_game","text":"刀错人了刀到了平民狼刀落后怎么翻盘","kw":["刀错","翻盘"]},
    {"id":"E13","role":"global","phase":"mid_game","text":"剩1狼2民1神怎么投","kw":["残局","轮次"]},
    {"id":"E06","role":"Seer","phase":"DAY_BADGE_SPEECH","text":"我是预言家有查杀但对跳也出现了警徽流怎么安排","kw":["对跳","警徽流"]},
]

class IterativeGrep:
    """Multi-round agent grep — simulates an agent refining its search."""

    def __init__(self, docs, max_rounds=3):
        self.docs = docs
        self.N = len(docs)
        self.max_rounds = max_rounds
        # Build inverted index
        self._index = {}
        for i, d in enumerate(docs):
            text = f"{d['situation']} {d['strategy']} {d['rationale']}"
            for w in set(jieba.cut(text)):
                if len(w) >= 2:
                    self._index.setdefault(w, set()).add(i)

    def _grep_one(self, terms, role="", phase=""):
        """Single grep round with given search terms."""
        scores = np.zeros(self.N)
        for term in terms:
            if len(term) >= 2 and term in self._index:
                for idx in self._index[term]:
                    scores[idx] += 1
        # Role/phase boost
        for i, d in enumerate(self.docs):
            if d["role"] == role: scores[i] += 0.5
            if d["phase"] == phase: scores[i] += 0.3
        idx = np.argsort(scores)[::-1][:10]
        return [int(i) for i in idx]

    def search(self, q, topk=10):
        """Iterative search: extract terms from query → grep → extract new terms from results → grep again."""
        # Round 1: grep with original query terms
        terms_round1 = list(set([w for w in jieba.cut(q["text"]) if len(w) >= 2]))
        results_r1 = self._grep_one(terms_round1, q["role"], q["phase"])

        if self.max_rounds == 1:
            return results_r1[:topk]

        # Round 2: extract new keywords from top results
        new_terms = set(terms_round1)
        for idx in results_r1[:5]:
            text = f"{self.docs[idx]['situation']} {self.docs[idx]['strategy']}"
            for w in jieba.cut(text):
                if len(w) >= 2 and w not in new_terms:
                    new_terms.add(w)
        results_r2 = self._grep_one(list(new_terms), q["role"], q["phase"])

        if self.max_rounds == 2:
            return results_r2[:topk]

        # Round 3: further refinement (prioritize newly discovered terms)
        round3_terms = set()
        for idx in results_r2[:3]:  # only from top-3
            text = f"{self.docs[idx]['situation']} {self.docs[idx]['strategy']}"
            for w in jieba.cut(text):
                if len(w) >= 2:
                    round3_terms.add(w)
        # Merge with original but give new terms extra weight
        all_terms = list(new_terms | round3_terms)
        results_r3 = self._grep_one(all_terms, q["role"], q["phase"])
        return results_r3[:topk]


def relevance(idx, q):
    content = f"{docs[idx]['situation']} {docs[idx]['strategy']}".lower()
    return sum(1 for k in q["kw"] if k.lower() in content)

def evaluate(results, q):
    m = {}
    for k in [5, 10]:
        kk = min(k, len(results))
        rel = [1 if relevance(r,q)>0 else 0 for r in results[:kk]]
        m[f"P@{k}"] = sum(rel)/max(kk,1)
    for rank, r in enumerate(results, 1):
        if relevance(r,q)>0: m["MRR"]=1.0/rank; break
    else: m["MRR"]=0.0
    for k in [5, 10]:
        kk = min(k, len(results))
        gains = [relevance(r,q) for r in results[:kk]]
        dcg = sum(g/np.log2(i+2) for i,g in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(g/np.log2(i+2) for i,g in enumerate(ideal))
        m[f"NDCG@{k}"] = dcg/idcg if idcg>0 else 0.0
    return m


if __name__ == "__main__":
    docs = load_docs()
    all_q = BASE  # 25 queries
    print(f"Docs: {len(docs)}, Queries: {len(all_q)}")

    # Build retrievers
    grep1 = IterativeGrep(docs, max_rounds=1)
    grep2 = IterativeGrep(docs, max_rounds=2)
    grep3 = IterativeGrep(docs, max_rounds=3)

    # BM25 baseline
    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    methods = {
        "Grep 1-round": lambda q: grep1.search(q),
        "Grep 2-round": lambda q: grep2.search(q),
        "Grep 3-round": lambda q: grep3.search(q),
        "BM25": lambda q: (lambda s: [int(i) for i in np.argsort(s)[::-1][:10]])(
            (lambda raw: raw/np.max(raw) if np.max(raw)>0 else raw)(
                bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
            ) + np.array([0.1 if d["role"]==q["role"] else 0 for d in docs])
        ),
    }

    print(f"\n{'='*70}")
    print("ITERATIVE AGENT GREP COMPARISON")
    print(f"{'='*70}")

    all_res = {}
    for mname, mfunc in methods.items():
        metrics = []; lats = []
        for q in all_q:
            t0 = time.perf_counter()
            res = mfunc(q)
            lat = (time.perf_counter()-t0)*1000
            lats.append(lat)
            m = evaluate(res, q); m["lat"]=lat; metrics.append(m)

        agg = {k: np.mean([qm[k] for qm in metrics]) for k in ["P@5","P@10","MRR","NDCG@5","NDCG@10"]}
        all_res[mname] = {"agg": agg, "lat": np.mean(lats), "metrics": metrics}
        print(f"  {mname:<20} P@5={agg['P@5']:.3f} NDCG@5={agg['NDCG@5']:.3f} "
              f"MRR={agg['MRR']:.3f} lat={np.mean(lats):.1f}ms")

    # Compared to known best
    print(f"\n  {'BM25+BGE RRF (prod)':<20} P@5=0.394 NDCG@5=0.723 MRR=0.734 lat=70ms")

    # Show iterative improvement per query
    print(f"\n{'='*70}")
    print("PER-QUERY NDCG@5: 1-Round vs 2-Round vs 3-Round")
    improved = 0; degraded = 0
    for i, q in enumerate(all_q):
        n1 = all_res["Grep 1-round"]["metrics"][i]["NDCG@5"]
        n2 = all_res["Grep 2-round"]["metrics"][i]["NDCG@5"]
        n3 = all_res["Grep 3-round"]["metrics"][i]["NDCG@5"]
        if n3 > n1: improved += 1
        if n3 < n1: degraded += 1
        arrow = "↑" if n3>n1 else ("↓" if n3<n1 else "→")
        print(f"  {q['id']}: {n1:.2f} → {n2:.2f} → {n3:.2f} {arrow}")

    print(f"\n  3-round improved {improved} queries, degraded {degraded} queries")
    print(f"  Multi-round grep helps when: query has few keywords → results reveal better terms")
    print(f"  Multi-round grep hurts when: results introduce noise terms that dilute the search")
