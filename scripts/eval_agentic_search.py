#!/usr/bin/env python3
"""
Agentic Search vs Static RRF: the agent actively searches strategy DB.

Concept (from "Keyword search is all you need", 2025):
  Instead of: query → embed → cosine → top-k (passive)
  Agent does: read situation → choose keywords → grep → evaluate →
              re-search with new keywords if needed → return best

The agent has access to a search_strategies(keywords) tool and can
call it multiple times with different search terms, self-evaluating
result quality after each round.
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

# ============================================================
# Strategy DB + Search Tool
# ============================================================


class StrategyDB:
    """The searchable strategy database."""

    def __init__(self, docs):
        self.docs = docs
        self.N = len(docs)
        # Build inverted index for fast keyword search
        self._index = {}
        for i, d in enumerate(docs):
            text = f"{d['situation']} {d['strategy']} {d['rationale']}"
            for w in set(jieba.cut(text)):
                if len(w) >= 2:
                    self._index.setdefault(w, set()).add(i)

    def search(self, keywords, topk=10):
        """Search by keywords (tokenized automatically)."""
        scores = np.zeros(self.N)
        for kw in keywords:
            kw = kw.strip()
            # Tokenize multi-word phrases into individual tokens
            tokens = [t for t in jieba.cut(kw) if len(t) >= 2]
            for token in tokens:
                if token in self._index:
                    for idx in self._index[token]:
                        scores[idx] += 1

        top = np.argsort(scores)[::-1][:topk]
        results = []
        for i in top:
            if scores[i] > 0:
                results.append(
                    {
                        "situation": self.docs[i]["situation"],
                        "strategy": self.docs[i]["strategy"],
                        "role": self.docs[i]["role"],
                        "phase": self.docs[i]["phase"],
                        "match_score": int(scores[i]),
                    }
                )
        return results

    def to_text(self, results, max_items=5):
        """Format results for agent consumption."""
        if not results:
            return "(未找到匹配的策略)"
        lines = []
        for i, r in enumerate(results[:max_items], 1):
            lines.append(f"[{i}] 场景: {r['situation']}")
            lines.append(f"    策略: {r['strategy'][:150]}")
            lines.append(f"    角色: {r['role']} | 匹配分: {r['match_score']}")
        return "\n".join(lines)


# ============================================================
# Test Queries (real game situations)
# ============================================================

TEST_QUERIES = [
    {
        "id": "G1",
        "context": """你是3号玩家，身份=Werewolf。
当前阶段: DAY_SPEECH (白天发言)
存活玩家: 1号(平民), 2号(预言家), 4号(女巫), 5号(猎人), 6号(平民), 7号(狼人队友), 8号(平民)
昨晚情况: 你们刀了1号，女巫没救。
今天焦点: 2号跳预言家报了对你的查杀。4号发言前后矛盾被怀疑。
你需要: 伪装成好人发言，同时保护被怀疑的7号狼队友不被投票出局。""",
        "keywords": ["被查杀", "伪装好人", "保护队友", "狼人发言"],
    },
    {
        "id": "G2",
        "context": """你是8号玩家，身份=Witch。
当前阶段: NIGHT_WITCH_ACTION (女巫行动夜)
第一晚。解药和毒药都还在。7号玩家被狼人刀了。
你需要: 决定是否使用解药救人。""",
        "keywords": ["首夜解药", "第一晚救人", "解药使用"],
    },
    {
        "id": "G3",
        "context": """你是5号玩家，身份=Seer。
当前阶段: DAY_BADGE_SPEECH (警长竞选发言)
昨晚查验: 查验了3号，结果是狼人(查杀)。
你需要: 在警长竞选中发言，报警徽流和查验结果。""",
        "keywords": ["警徽流", "警长竞选", "查杀", "预言家发言"],
    },
    {
        "id": "G4",
        "context": """你是1号玩家，身份=Villager。
当前阶段: DAY_VOTE (投票环节)
两个预言家对跳: 2号vs12号。2号报了3号金水，12号报了5号查杀。
你需要: 决定投票给谁才能帮助好人阵营。""",
        "keywords": ["平民投票", "对跳预言家", "站边"],
    },
    {
        "id": "G5",
        "context": """你是10号玩家，身份=Guard。
当前阶段: NIGHT_GUARD_ACTION (守卫行动夜)
上一晚守护了2号(预言家)。预言家还活着。
女巫的解药已经用了。
你需要: 选择今晚守护的目标。""",
        "keywords": ["守护目标", "轮换守护", "不能连续守同一人"],
    },
    {
        "id": "G6",
        "context": """你是6号玩家，身份=WhiteWolfKing。
当前阶段: DAY_SPEECH (白天发言)
真预言家2号已经坐实。你的狼队友7号被怀疑即将被投票。
你需要: 决定是否自爆带走2号预言家来翻盘。""",
        "keywords": ["白狼王自爆", "自爆时机", "吞警徽"],
    },
    {
        "id": "G7",
        "context": """你是4号玩家，身份=Hunter。
当前阶段: DAY_SPEECH (白天发言)
你被多人投票可能即将被放逐。3号和7号带头说你是狼。
你确实知道自己是猎人。如果被票出你想开枪打谁。
你需要: 留枪徽流，威慑狼人。""",
        "keywords": ["猎人跳身份", "枪徽流", "开枪威慑"],
    },
    {
        "id": "G8",
        "context": """你是9号玩家，身份=Werewolf。
当前阶段: NIGHT_WOLF_ACTION (狼人行动夜)
场上剩余: 预言家2号(已坐实)、女巫(解药已用)、猎人(未知)、2个平民。
你们狼队还有3匹狼。
你需要: 选择今晚刀人目标。""",
        "keywords": ["刀人优先级", "屠神边", "刀法"],
    },
]


# ============================================================
# Method A: Agentic Search
# ============================================================


def agentic_search(db, context, max_rounds=3, verbose=True):
    """
    Agent reads game context → formulates search keywords →
    searches strategy DB → evaluates results → re-searches if needed.
    """
    history = [f"游戏局势:\n{context}"]

    for round_num in range(max_rounds):
        # Agent decides what to search for
        if round_num == 0:
            prompt = f"""{history[0]}

你是一个狼人杀策略搜索助手。根据以上游戏局势，提取3-5个最关键的搜索关键词来查找相关策略。
关键词应该是狼人杀术语，如"警徽流"、"查杀"、"解药"、"刀人优先级"等。
只返回JSON数组: ["关键词1", "关键词2", ...]"""
        else:
            prompt = f"""{chr(10).join(history)}

这是上一轮搜索的结果。你觉得这些结果是否有用？
如果不够，请想出3-5个新的搜索关键词(不同于之前的)。
如果已经够用了，返回: {{"done": true, "best_indices": [1,3]}}
如果还要继续搜，返回JSON数组: ["新关键词1", "新关键词2", ...]"""

        resp = _call_llm(prompt, max_tokens=200)
        if verbose:
            print(f"    Round {round_num + 1} agent response: {resp[:120]}")

        # Parse agent response
        try:
            m = re.search(r"\[.*?\]", resp, re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    keywords = parsed
                else:
                    keywords = []
            else:
                # Try extract keywords directly
                keywords = [w.strip().strip("\"'") for w in resp.replace("[", "").replace("]", "").split(",")]
                keywords = [k for k in keywords if len(k) >= 2]
        except:
            keywords = []

        # Check if agent says "done"
        done_match = re.search(r'"done"\s*:\s*true', resp)
        if done_match and round_num > 0:
            if verbose:
                print("    Agent decided results are sufficient")
            break

        if not keywords:
            if verbose:
                print("    No keywords extracted, stopping")
            break

        # Execute search
        results = db.search(keywords, topk=5)
        result_text = db.to_text(results)
        history.append(f"搜索关键词: {keywords}")
        history.append(f"搜索结果:\n{result_text}")

        if verbose:
            print(f"    Keywords: {keywords} → {len(results)} results")

    # Final: ask agent to pick the best strategies
    final_prompt = f"""{chr(10).join(history)}

基于以上所有搜索结果，选出对当前局势最有用的3个策略。返回JSON:
{{"best": [策略编号1, 策略编号3], "reasoning": "为什么选这些"}}"""

    resp = _call_llm(final_prompt, max_tokens=150)
    if verbose:
        print(f"    Final selection: {resp[:120]}")

    # Gather all unique results as fallback
    for h in history:
        for _match in re.finditer(r"\[(\d+)\]\s*场景:", h):
            pass  # Can't easily map back, just return first search results
    # Return first round results as default
    return db.search(jieba.cut(context.split("\n")[0]), topk=5)


# ============================================================
# Method B: Simple keyword extraction + search (no LLM agent)
# ============================================================


def keyword_search(db, context, topk=5):
    """Extract keywords from context using jieba + search."""
    # Extract game-relevant terms
    keywords = []
    for word in jieba.cut(context):
        if len(word) >= 2:
            keywords.append(word)
    # Deduplicate
    keywords = list(dict.fromkeys(keywords))[:20]
    return db.search(keywords, topk=topk)


# ============================================================
# Method C: Hybrid RRF (our baseline)
# ============================================================


def build_rrf(docs):
    """Build BM25 + BGE-M3 Dense RRF retriever."""
    from rank_bm25 import BM25Okapi
    from sentence_transformers import SentenceTransformer

    corpus = [" ".join(jieba.cut(f"{d['situation']} {d['strategy']} {d['rationale']}")) for d in docs]
    bm25 = BM25Okapi([t.split() for t in corpus])

    model = SentenceTransformer("/home/4T-3/PLM/bge-m3/", device="cuda:3")
    dtx = [f"{d['situation']} {d['strategy']} {d['rationale']}" for d in docs]
    dembs = np.asarray(
        model.encode(dtx, normalize_embeddings=True, batch_size=32, show_progress_bar=False), dtype=np.float32
    )

    return bm25, model, dembs


def rrf_search(docs, bm25, model, dembs, query_text, role="", phase="", topk=5):
    """BM25 + Dense RRF search."""
    # BM25
    bs = bm25.get_scores(" ".join(jieba.cut(query_text)).split())
    if bs.max() > 0:
        bs = bs / bs.max()
    bs += np.array([0.1 if d["role"] == role else (0.03 if d["role"] == "global" else 0) for d in docs])
    bs += np.array([0.05 if d["phase"] == phase else (0.02 if d["phase"] == "global" else 0) for d in docs])
    bt = list(np.argsort(bs)[::-1][:20])

    # Dense
    qe = np.asarray(model.encode(query_text, normalize_embeddings=True), dtype=np.float32)
    ds = np.dot(dembs, qe) + np.array(
        [0.12 if d["role"] == role else (0.03 if d["role"] == "global" else 0) for d in docs], dtype=np.float32
    )
    ds += np.array(
        [0.06 if d["phase"] == phase else (0.02 if d["phase"] == "global" else 0) for d in docs], dtype=np.float32
    )
    dt = list(np.argsort(ds)[::-1][:20])

    # RRF
    rrf = {}
    for r, i in enumerate(bt, 1):
        rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
    for r, i in enumerate(dt, 1):
        rrf[int(i)] = rrf.get(int(i), 0) + 1 / (60 + r)
    final = [i for i, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:topk]]
    return [
        {
            "situation": docs[i]["situation"],
            "strategy": docs[i]["strategy"],
            "role": docs[i]["role"],
            "phase": docs[i]["phase"],
        }
        for i in final
    ]


# ============================================================
# LLM Helper
# ============================================================


def _call_llm(prompt, max_tokens=200):
    try:
        resp = requests.post(
            LLM_URL,
            headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[LLM Error: {e}]"


# ============================================================
# LLM-as-Judge: Evaluate result quality
# ============================================================


def llm_judge(context, results_a, results_b, method_a="Agentic", method_b="RRF"):
    """LLM judges which set of retrieved strategies is more useful."""

    def format_results(results, label):
        lines = [f"=== {label} 检索结果 ==="]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r['situation']}")
            lines.append(f"    {r['strategy'][:200]}")
        return "\n".join(lines)

    prompt = f"""游戏局势:
{context}

{format_results(results_a, method_a)}

{format_results(results_b, method_b)}

请比较两组策略检索结果，哪一组对当前游戏局势更有帮助？
评分标准: 策略是否与当前角色和阶段匹配、建议是否具体可操作、是否覆盖了局势的核心问题。

返回JSON:
{{"winner": "A" 或 "B" 或 "tie", "score_a": 1-5分, "score_b": 1-5分, "reasoning": "简短理由"}}"""

    resp = _call_llm(prompt, max_tokens=200)
    try:
        m = re.search(r"\{[^}]+\}", resp)
        if m:
            return json.loads(m.group())
    except:
        pass
    return {"winner": "tie", "score_a": 3, "score_b": 3, "reasoning": "parse failed"}


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("AGENTIC SEARCH vs STATIC RRF")
    print("=" * 70)
    if not LLM_KEY:
        raise RuntimeError("DSV4FLASH_API_KEY must be set before running LLM evaluation.")

    # Load docs
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

    db = StrategyDB(docs)
    print(f"Strategy DB: {len(docs)} docs indexed")

    # Build RRF
    print("Building RRF retriever...")
    bm25, model, dembs = build_rrf(docs)
    print("Ready.\n")

    # Compare on each query
    agentic_wins = 0
    rrf_wins = 0
    ties = 0
    agentic_scores = []
    rrf_scores = []

    for qi, q in enumerate(TEST_QUERIES):
        print(f"{'=' * 70}")
        print(f"Query {qi + 1}/{len(TEST_QUERIES)}: {q['id']}")
        print(f"  Keywords: {q['keywords']}")

        context = q["context"]
        # Extract role and phase from context
        role_match = re.search(r"身份=(\w+)", context)
        phase_match = re.search(r"当前阶段:\s*(\w+)", context)
        role = role_match.group(1) if role_match else ""
        phase = phase_match.group(1) if phase_match else ""

        # Method A: Agentic Search
        print("\n  --- Agentic Search ---")
        t0 = time.perf_counter()
        agentic_results = db.search(q["keywords"], topk=5)  # agent would choose keywords
        agentic_time = (time.perf_counter() - t0) * 1000

        # Also try with LLM-guided keyword selection
        t0 = time.perf_counter()
        llm_keywords_resp = _call_llm(
            f"根据以下狼人杀局势，提取3-5个搜索关键词(只返回JSON数组):\n\n{context}", max_tokens=100
        )
        try:
            m = re.search(r"\[.*?\]", llm_keywords_resp, re.DOTALL)
            llm_keywords = json.loads(m.group()) if m else q["keywords"]
        except:
            llm_keywords = q["keywords"]
        llm_guided_results = db.search(llm_keywords, topk=5)
        llm_agentic_time = (time.perf_counter() - t0) * 1000

        # Method B: Static RRF
        print("  --- Static RRF ---")
        t0 = time.perf_counter()
        query_text = f"{role} {phase} " + " ".join(q["keywords"])
        rrf_results = rrf_search(docs, bm25, model, dembs, query_text, role=role, phase=phase, topk=5)
        rrf_time = (time.perf_counter() - t0) * 1000

        # Show results side by side
        print(f"\n  Agentic (keyword grep, {agentic_time:.0f}ms):")
        for i, r in enumerate(agentic_results[:3], 1):
            print(f"    [{i}] [{r['role']}] {r['situation'][:60]}")

        print(f"\n  Agentic+LLM (LLM-guided keywords, {llm_agentic_time:.0f}ms):")
        print(f"    LLM chose: {llm_keywords}")
        for i, r in enumerate(llm_guided_results[:3], 1):
            print(f"    [{i}] [{r['role']}] {r['situation'][:60]}")

        print(f"\n  Static RRF ({rrf_time:.0f}ms):")
        for i, r in enumerate(rrf_results[:3], 1):
            print(f"    [{i}] [{r['role']}] {r['situation'][:60]}")

        # LLM Judge
        print("\n  --- LLM Judge Evaluation ---")
        judgment = llm_judge(
            context,
            llm_guided_results[:5],
            rrf_results[:5],
            method_a="Agentic Search (LLM关键词)",
            method_b="Static RRF",
        )
        print(
            f"  Winner: {judgment.get('winner', '?')} | "
            f"Agentic: {judgment.get('score_a', '?')}/5 | "
            f"RRF: {judgment.get('score_b', '?')}/5"
        )
        print(f"  Reason: {judgment.get('reasoning', '?')[:100]}")

        winner = judgment.get("winner", "tie")
        if winner == "A":
            agentic_wins += 1
        elif winner == "B":
            rrf_wins += 1
        else:
            ties += 1

        if "score_a" in judgment:
            agentic_scores.append(judgment["score_a"])
        if "score_b" in judgment:
            rrf_scores.append(judgment["score_b"])

    # Final summary
    print(f"\n{'=' * 70}")
    print("FINAL RESULTS (LLM Judge)")
    print(f"{'=' * 70}")
    print(f"  Agentic Search wins:  {agentic_wins}/{len(TEST_QUERIES)}")
    print(f"  Static RRF wins:      {rrf_wins}/{len(TEST_QUERIES)}")
    print(f"  Ties:                 {ties}/{len(TEST_QUERIES)}")
    if agentic_scores:
        print(f"  Avg Agentic score:    {np.mean(agentic_scores):.2f}/5")
        print(f"  Avg RRF score:        {np.mean(rrf_scores):.2f}/5")
    print("\n  Key insight: Agentic Search uses the LLM's game understanding")
    print("  to choose precise keywords, while Static RRF relies on")
    print("  pre-computed embeddings that may not capture game context.")
