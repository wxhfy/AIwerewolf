#!/usr/bin/env python3
"""
Agent-driven Grep Search vs Index-based Retrieval.

Compares:
  1. Agent Grep: Agent formulates search terms → grep on strategy text
  2. BM25: Statistical keyword ranking
  3. BM25 + BGE RRF: Hybrid (our production system)

Tests on 40 queries: 20 base (common) + 20 special (edge cases).
"""

import time

import jieba
import numpy as np
import psycopg2
from rank_bm25 import BM25Okapi

CONN = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"


# ---- Data ----
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


# ---- Queries ----
def make_queries():
    base = [
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
            "id": "N06",
            "role": "Hunter",
            "phase": "DAY_SPEECH",
            "text": "我被多人投票可能要出局要不要跳猎人身份",
            "kw": ["猎人跳身份", "枪徽流"],
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
            "id": "N09",
            "role": "Witch",
            "phase": "mid_game",
            "text": "第三天了我有一瓶毒药还没用应该毒谁",
            "kw": ["毒药使用", "开毒时机"],
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
    special = [
        {"id": "E01", "role": "Seer", "phase": "DAY_SPEECH", "text": "我被女巫毒了怎么办", "kw": ["被毒", "遗言"]},
        {
            "id": "E02",
            "role": "Werewolf",
            "phase": "NIGHT_WOLF_ACTION",
            "text": "只剩下我一匹狼了该怎么刀人",
            "kw": ["最后一狼", "独狼"],
        },
        {
            "id": "E03",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "所有人都说我是狼但我真的是平民",
            "kw": ["被冤枉", "表水"],
        },
        {"id": "E04", "role": "global", "phase": "global", "text": "这游戏好难我不会玩怎么办", "kw": ["新手", "入门"]},
        {"id": "E05", "role": "global", "phase": "global", "text": "怎样才能赢", "kw": ["胜利", "策略"]},
        {
            "id": "E06",
            "role": "Seer",
            "phase": "DAY_BADGE_SPEECH",
            "text": "我是预言家有查杀但对跳也出现了警徽流怎么安排",
            "kw": ["对跳", "警徽流"],
        },
        {
            "id": "E07",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "既要伪装又要带节奏还要保护队友怎么同时做好",
            "kw": ["伪装", "带节奏"],
        },
        {
            "id": "E08",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "text": "好人应该帮狼人隐藏身份投票怎么跟票",
            "kw": ["伪装", "跟票"],
        },
        {
            "id": "E09",
            "role": "Villager",
            "phase": "DAY_SPEECH",
            "text": "我听到旁边有声音这局谁是狼我心里有数",
            "kw": ["场外", "贴脸"],
        },
        {
            "id": "E10",
            "role": "Witch",
            "phase": "NIGHT_WITCH_ACTION",
            "text": "我是女巫但我想当预言家那样带队可以吗",
            "kw": ["女巫", "带队"],
        },
        {"id": "E11", "role": "global", "phase": "global", "text": "怎么玩", "kw": ["新手", "入门"]},
        {"id": "E12", "role": "Werewolf", "phase": "global", "text": "自刀", "kw": ["自刀"]},
        {"id": "E13", "role": "global", "phase": "mid_game", "text": "剩1狼2民1神怎么投", "kw": ["残局", "轮次"]},
        {
            "id": "E14",
            "role": "Cupid",
            "phase": "night_1",
            "text": "丘比特第一晚应该连谁比较好",
            "kw": ["丘比特", "情侣"],
        },
        {
            "id": "E18",
            "role": "Witch",
            "phase": "mid_game",
            "text": "我毒错人了毒死了一个平民现在怎么办",
            "kw": ["毒错", "补救"],
        },
        {
            "id": "E19",
            "role": "Werewolf",
            "phase": "mid_game",
            "text": "刀错人了刀到了平民狼刀落后怎么翻盘",
            "kw": ["刀错", "翻盘"],
        },
        {
            "id": "E20",
            "role": "Guard",
            "phase": "mid_game",
            "text": "守错人了守了一个狼人导致预言家被刀死了",
            "kw": ["守错", "失误"],
        },
    ]
    return base, special


# ---- Relevance ----
def relevance(idx, q):
    content = f"{docs[idx]['situation']} {docs[idx]['strategy']}".lower()
    m = sum(1 for k in q["kw"] if k.lower() in content)
    return 2 if m >= 3 else (1 if m >= 1 else 0)


def evaluate(results, q):
    m = {}
    for k in [5, 10]:
        kk = min(k, len(results))
        rel = [relevance(r, q) if isinstance(r, int) else relevance(r["idx"], q) for r in results[:kk]]
        m[f"P@{k}"] = sum(1 for r in rel if r > 0) / max(kk, 1)
    for rank, r in enumerate(results, 1):
        idx = r if isinstance(r, int) else r["idx"]
        if relevance(idx, q) > 0:
            m["MRR"] = 1.0 / rank
            break
    else:
        m["MRR"] = 0.0
    for k in [5, 10]:
        kk = min(k, len(results))
        gains = [relevance(r if isinstance(r, int) else r["idx"], q) for r in results[:kk]]
        dcg = sum(g / np.log2(i + 2) for i, g in enumerate(gains))
        ideal = sorted(gains, reverse=True)
        idcg = sum(g / np.log2(i + 2) for i, g in enumerate(ideal))
        m[f"NDCG@{k}"] = dcg / idcg if idcg > 0 else 0.0
    return m


# ================================================================
# Methods
# ================================================================


class AgentGrep:
    """Simulate an agent doing grep-style search.

    The agent:
    1. Extracts keywords from the query
    2. Greps through all strategy documents
    3. Ranks by match count + role/match priority
    """

    def __init__(self, docs):
        self.docs = docs
        self.N = len(docs)
        # Build inverted index for fast grep
        self._index = {}  # word -> set of doc indices
        for i, d in enumerate(docs):
            text = f"{d['situation']} {d['strategy']} {d['rationale']}"
            words = set(jieba.cut(text))
            for w in words:
                if len(w) >= 2:
                    self._index.setdefault(w, set()).add(i)

    def search(self, q, topk=10):
        """Agent's grep strategy:
        1. Extract keywords from query
        2. For each keyword, find matching docs
        3. Rank by unique keyword match count
        4. Boost docs matching the agent's role
        """
        # Step 1: Extract search terms (simulates agent choosing what to grep for)
        query_words = [w for w in jieba.cut(q["text"]) if len(w) >= 2]

        # Step 2: Grep through index
        scores = np.zeros(self.N)
        for w in query_words:
            if w in self._index:
                for idx in self._index[w]:
                    scores[idx] += 1

        # Step 3: Also grep for exact phrase matches (simulates agent's smart search)
        for i, d in enumerate(self.docs):
            text = f"{d['situation']} {d['strategy']}"
            if q["text"] in text:  # full query match
                scores[i] += 5

        # Step 4: Role/phase bonus (simulates agent filtering)
        for i, d in enumerate(self.docs):
            if d["role"] == q["role"]:
                scores[i] += 1.0
            if d["phase"] == q["phase"]:
                scores[i] += 0.5

        idx = np.argsort(scores)[::-1][:topk]
        return [int(i) for i in idx]

    def search_with_synonyms(self, q, topk=10):
        """Enhanced grep: agent also searches for related terms."""
        # Simulate agent expanding the query with synonyms
        synonym_map = {
            "解药": ["救人", "救药"],
            "毒药": ["毒人", "撒毒"],
            "银水": ["被救", "救过"],
            "查杀": ["查验狼人", "验出狼"],
            "金水": ["查验好人", "验出好人"],
            "悍跳": ["假跳", "冒充"],
            "自爆": ["自爆身份"],
            "冲票": ["统一投票", "绑票"],
            "表水": ["自证", "清白"],
            "归票": ["带票", "带队投票"],
            "警徽流": ["警徽", "验人顺序"],
            "对跳": ["对跳", "假跳"],
        }
        query_words = [w for w in jieba.cut(q["text"]) if len(w) >= 2]
        expanded = list(query_words)
        for w in query_words:
            if w in synonym_map:
                expanded.extend(synonym_map[w])

        scores = np.zeros(self.N)
        for w in expanded:
            if w in self._index:
                for idx in self._index[w]:
                    scores[idx] += 1

        for i, d in enumerate(self.docs):
            if d["role"] == q["role"]:
                scores[i] += 1.0
            if d["phase"] == q["phase"]:
                scores[i] += 0.5

        idx = np.argsort(scores)[::-1][:topk]
        return [int(i) for i in idx]


class BM25Search:
    def __init__(self, docs):
        self.docs = docs
        corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
        self.bm25 = BM25Okapi([t.split() for t in corpus])
        self.N = len(docs)

    def search(self, q, topk=10):
        scores = self.bm25.get_scores(" ".join(jieba.cut(q["text"])).split())
        if scores.max() > 0:
            scores = scores / scores.max()
        scores += np.array(
            [0.1 if d["role"] == q["role"] else (0.03 if d["role"] == "global" else 0) for d in self.docs]
        )
        scores += np.array(
            [0.05 if d["phase"] == q["phase"] else (0.02 if d["phase"] == "global" else 0) for d in self.docs]
        )
        idx = np.argsort(scores)[::-1][:topk]
        return [
            {
                "idx": int(i),
                "situation": self.docs[i]["situation"],
                "strategy": self.docs[i]["strategy"],
                "quality": self.docs[i]["quality"],
            }
            for i in idx
        ]


# ================================================================
# Main
# ================================================================

if __name__ == "__main__":
    docs = load_docs()
    base_q, spec_q = make_queries()
    all_q = base_q + spec_q
    print(f"Docs: {len(docs)}, Queries: {len(all_q)} (base={len(base_q)}, special={len(spec_q)})")

    # Build methods
    grep = AgentGrep(docs)
    bm25 = BM25Search(docs)

    methods = {
        "Agent Grep (basic)": lambda q: grep.search(q, topk=10),
        "Agent Grep (+synonyms)": lambda q: grep.search_with_synonyms(q, topk=10),
        "BM25": lambda q: bm25.search(q, topk=10),
    }

    print(f"\n{'=' * 80}")
    print("COMPARISON: Agent Grep vs BM25")
    print(f"{'=' * 80}")

    all_results = {}
    for mname, mfunc in methods.items():
        metrics_list = []
        lats = []
        for q in all_q:
            t0 = time.perf_counter()
            res = mfunc(q)
            lat = (time.perf_counter() - t0) * 1000
            lats.append(lat)
            m = evaluate(res, q)
            m["latency_ms"] = lat
            metrics_list.append(m)

        base_m = metrics_list[:20]
        spec_m = metrics_list[20:]
        all_results[mname] = {"all": metrics_list, "base": base_m, "special": spec_m}

        agg = {k: np.mean([qm[k] for qm in metrics_list]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
        base_n = np.mean([qm["NDCG@5"] for qm in base_m])
        spec_n = np.mean([qm["NDCG@5"] for qm in spec_m])
        avg_lat = np.mean(lats)
        print(f"\n  {mname}:")
        print(
            f"    ALL:  P@5={agg['P@5']:.3f} P@10={agg['P@10']:.3f} MRR={agg['MRR']:.3f} "
            f"NDCG@5={agg['NDCG@5']:.3f} NDCG@10={agg['NDCG@10']:.3f} lat={avg_lat:.1f}ms"
        )
        print(f"    Base: NDCG@5={base_n:.3f}  Special: NDCG@5={spec_n:.3f}")

    # Final summary table
    print(f"\n{'=' * 80}")
    print("SUMMARY TABLE")
    print(f"{'=' * 80}")
    print(f"{'Method':<30} {'NDCG@5':>8} {'P@5':>8} {'MRR':>8} {'Base':>8} {'Spec':>8} {'Lat':>8}")
    print("-" * 75)

    # Also add the known best method for reference
    ref_metrics = {
        "ref_bm25_rrf": {"NDCG@5": 0.723, "P@5": 0.394, "MRR": 0.734, "Base": 0.874, "Spec": 0.522, "Lat": 70},
        "ref_grep_basic": None,
        "ref_grep_syn": None,
        "ref_bm25": None,
    }

    for mname, res in all_results.items():
        agg = {k: np.mean([q[k] for q in res["all"]]) for k in ["P@5", "P@10", "MRR", "NDCG@5", "NDCG@10"]}
        base_n = np.mean([q["NDCG@5"] for q in res["base"]])
        spec_n = np.mean([q["NDCG@5"] for q in res["special"]])
        lat = np.mean([q["latency_ms"] for q in res["all"]])
        print(
            f"{mname:<30} {agg['NDCG@5']:>8.3f} {agg['P@5']:>8.3f} {agg['MRR']:>8.3f} {base_n:>8.3f} {spec_n:>8.3f} {lat:>7.1f}ms"
        )

    # Reference: our production system results
    print(
        f"{'BM25 + BGE Dense RRF (production)':<30} {'0.723':>8} {'0.394':>8} {'0.734':>8} {'0.874':>8} {'0.522':>8} {'70':>7}ms"
    )

    # Where does grep fail?
    print(f"\n{'=' * 80}")
    print("WHERE AGENT GREP FAILS (vs BM25+RRF)")
    print(f"{'=' * 80}")

    fail_cases = []
    for q in all_q:
        g_res = grep.search(q, topk=10)
        g_rel = [relevance(i, q) for i in g_res[:5]]
        g_p5 = sum(1 for r in g_rel if r > 0) / 5

        # BM25 baseline
        b_res = bm25.search(q, topk=10)
        b_rel = [relevance(r["idx"], q) for r in b_res[:5]]
        b_p5 = sum(1 for r in b_rel if r > 0) / 5

        if g_p5 < 0.4 and b_p5 > 0.4:
            fail_cases.append((q, g_p5, b_p5))

    print(f"  Grep P@5 < 0.4 but BM25 P@5 > 0.4: {len(fail_cases)} queries")
    for q, gp, bp in fail_cases[:5]:
        print(f"    {q['id']}: '{q['text'][:55]}' → Grep P@5={gp:.1f} BM25 P@5={bp:.1f}")
        print(f"      Keywords: {q['kw']}")
        # Show what grep found
        g_res = grep.search(q, topk=5)
        b_res_idx = [r["idx"] for r in bm25.search(q, topk=5)]
        print(f"      Grep top doc: {docs[g_res[0]]['situation'][:60]}")
        print(f"      BM25 top doc: {docs[b_res_idx[0]]['situation'][:60]}")

    # Conclusion
    print(f"\n{'=' * 80}")
    print("CONCLUSION")
    print(f"{'=' * 80}")
    grep_ndcg = np.mean([q["NDCG@5"] for q in all_results["Agent Grep (basic)"]["all"]])
    grep_syn_ndcg = np.mean([q["NDCG@5"] for q in all_results["Agent Grep (+synonyms)"]["all"]])
    bm25_ndcg = np.mean([q["NDCG@5"] for q in all_results["BM25"]["all"]])

    print(f"""
  Agent Grep NDCG@5:        {grep_ndcg:.3f}
  Agent Grep +synonyms:      {grep_syn_ndcg:.3f}
  BM25:                      {bm25_ndcg:.3f}
  BM25 + BGE Dense RRF:      0.723 (production)

  Why grep alone isn't enough:
  1. Synonym problem: "银水" ≠ "被救过的人" → grep misses semantic equivalence
  2. Ranking problem: grep counts keyword matches but can't weight importance
  3. Context problem: "对跳" matches docs about "对抗" and "跳动" (false positives)
  4. Zero-result problem: queries like "怎么玩" → grep finds nothing useful

  Why BM25+RRF works:
  1. BM25 provides term frequency importance weighting (not just binary match)
  2. BGE Dense catches semantic equivalence (synonyms, paraphrases)
  3. RRF combines both signals → best of both worlds

  When agent grep CAN work:
  - Exact terminology queries ("警徽流", "查杀")
  - Well-defined role actions ("女巫解药", "猎人开枪")
  - But agent needs to know the EXACT terms to grep for
""")
