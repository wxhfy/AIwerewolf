"""Evaluate strategy retrieval precision.

Quantifies how accurately the strategy retrieval system returns
relevant strategies for each (role, phase, situation) query.

Metrics: Precision@k, Recall@k, MRR, NDCG@k

Run: python scripts/eval_retrieval.py [--verbose]
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.persist import retrieve_strategy_knowledge
from backend.eval.evolution import StrategyRetrievalQuery

# Ground truth: (role, phase, situation_tags) → expected strategy keywords
# Each test case defines what a "correct" retrieval should contain
GROUND_TRUTH = [
    # === Seer ===
    {
        "role": "Seer",
        "phase": "night_1",
        "summary": "首夜，需要选择查验目标",
        "tags": ["night_action", "first_night", "divine"],
        "expected_keywords": ["查验", "后置位", "警上", "选人", "验人"],
        "forbidden_keywords": ["毒药", "开枪", "自刀"],
        "description": "Seer N1: who to check",
    },
    {
        "role": "Seer",
        "phase": "day_1",
        "summary": "第一天警上发言，需要报查验抢警徽",
        "tags": ["speech", "badge_election", "claim"],
        "expected_keywords": ["警徽流", "查验", "金水", "查杀", "心路历程"],
        "forbidden_keywords": [],
        "description": "Seer D1: badge election speech",
    },
    {
        "role": "Seer",
        "phase": "mid_game",
        "summary": "面对悍跳狼对跳预言家，需要辨别真伪",
        "tags": ["vote", "fake_seer", "debate"],
        "expected_keywords": ["悍跳", "对跳", "辨别", "逻辑", "票型"],
        "forbidden_keywords": [],
        "description": "Seer mid: counter fake seer",
    },
    # === Witch ===
    {
        "role": "Witch",
        "phase": "night_1",
        "summary": "首夜，收到刀口信息，决定是否使用解药",
        "tags": ["night_action", "first_night", "save"],
        "expected_keywords": ["解药", "救人", "首夜", "救"],
        "forbidden_keywords": ["毒", "查验"],
        "description": "Witch N1: use antidote or not",
    },
    {
        "role": "Witch",
        "phase": "mid_game",
        "summary": "持毒药，需要决定毒人时机和目标",
        "tags": ["night_action", "poison", "decision"],
        "expected_keywords": ["毒药", "时机", "确定", "狼", "窗口"],
        "forbidden_keywords": [],
        "description": "Witch mid: when to poison",
    },
    {
        "role": "Witch",
        "phase": "day_1",
        "summary": "双药在手，需要隐藏身份参与白天发言",
        "tags": ["speech", "hide_role", "day_1"],
        "expected_keywords": ["隐藏", "身份", "平民", "视角", "发言"],
        "forbidden_keywords": ["跳", "报银水"],
        "description": "Witch D1: hide identity in speech",
    },
    # === Guard ===
    {
        "role": "Guard",
        "phase": "night_1",
        "summary": "首夜，需要决定守护目标（有女巫时）",
        "tags": ["night_action", "first_night", "protect"],
        "expected_keywords": ["空守", "奶穿", "首夜", "女巫", "解药"],
        "forbidden_keywords": [],
        "description": "Guard N1: empty guard or protect",
    },
    {
        "role": "Guard",
        "phase": "mid_game",
        "summary": "预言家已明身份，需要持续保护",
        "tags": ["night_action", "protect", "priority"],
        "expected_keywords": ["预言家", "守护", "女巫", "优先级", "心理"],
        "forbidden_keywords": [],
        "description": "Guard mid: protect priority",
    },
    # === Hunter ===
    {
        "role": "Hunter",
        "phase": "day_1",
        "summary": "前期身份未暴露，需要隐藏",
        "tags": ["speech", "hide_role", "early_game"],
        "expected_keywords": ["隐藏", "平民", "伪装", "威慑", "跳"],
        "forbidden_keywords": [],
        "description": "Hunter early: hide identity",
    },
    {
        "role": "Hunter",
        "phase": "late_game",
        "summary": "出局时，需要选择开枪目标",
        "tags": ["night_action", "shoot", "eliminated"],
        "expected_keywords": ["开枪", "带走", "狼", "优先级", "神职"],
        "forbidden_keywords": [],
        "description": "Hunter late: shoot target priority",
    },
    # === Werewolf ===
    {
        "role": "Werewolf",
        "phase": "day_1",
        "summary": "第一天，需要决定是否悍跳预言家",
        "tags": ["speech", "fake_claim", "badge"],
        "expected_keywords": ["悍跳", "预言家", "抢警徽", "不悍跳"],
        "forbidden_keywords": [],
        "description": "Wolf D1: fake seer or not",
    },
    {
        "role": "Werewolf",
        "phase": "night_1",
        "summary": "首夜，需要决定刀人目标和团队分工",
        "tags": ["night_action", "kill", "teamwork"],
        "expected_keywords": ["刀", "分工", "悍跳狼", "冲锋狼", "倒钩狼"],
        "forbidden_keywords": [],
        "description": "Wolf N1: kill target + team roles",
    },
    {
        "role": "Werewolf",
        "phase": "mid_game",
        "summary": "需要隐藏身份，建立对立面",
        "tags": ["speech", "deception", "deep_cover"],
        "expected_keywords": ["隐藏", "对立面", "自刀", "倒钩", "投票"],
        "forbidden_keywords": [],
        "description": "Wolf mid: deception and deep cover",
    },
    # === Villager ===
    {
        "role": "Villager",
        "phase": "day_1",
        "summary": "第一天白天，需要站边和投票",
        "tags": ["speech", "vote", "stand_point"],
        "expected_keywords": ["站边", "投票", "发言", "理由", "划水"],
        "forbidden_keywords": [],
        "description": "Villager D1: stand and vote",
    },
    {
        "role": "Villager",
        "phase": "mid_game",
        "summary": "需要找狼人，分析票型",
        "tags": ["analyze", "find_wolf", "vote_pattern"],
        "expected_keywords": ["找狼", "票型", "冲锋狼", "倒钩狼", "团队"],
        "forbidden_keywords": [],
        "description": "Villager mid: find wolves from votes",
    },
]


def compute_precision_at_k(retrieved: list[dict], expected: list[str], k: int) -> float:
    """Fraction of top-k results that match at least one expected keyword."""
    if not retrieved or k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = 0
    for item in top_k:
        text = (
            item.get("recommendation", "") + " " + item.get("situation_pattern", "") + item.get("rationale", "")
        ).lower()
        if any(kw.lower() in text for kw in expected):
            hits += 1
    return hits / min(k, len(top_k))


def compute_recall_at_k(retrieved: list[dict], expected: list[str], k: int) -> float:
    """Fraction of expected keywords matched by at least one top-k result."""
    if not retrieved or not expected or k <= 0:
        return 0.0
    top_k = retrieved[:k]
    all_text = " ".join(item.get("recommendation", "") + item.get("rationale", "") for item in top_k).lower()
    matched = sum(1 for kw in expected if kw.lower() in all_text)
    return matched / len(expected)


def compute_mrr(retrieved: list[dict], expected: list[str]) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant result."""
    if not retrieved or not expected:
        return 0.0
    for i, item in enumerate(retrieved):
        text = (item.get("recommendation", "") + item.get("rationale", "")).lower()
        if any(kw.lower() in text for kw in expected):
            return 1.0 / (i + 1)
    return 0.0


def compute_ndcg_at_k(retrieved: list[dict], expected: list[str], k: int) -> float:
    """Normalized DCG using binary relevance (1 if matches any keyword)."""
    if not retrieved or not expected or k <= 0:
        return 0.0
    import math

    def dcg(relevances):
        return sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(relevances))

    relevances = []
    for item in retrieved[:k]:
        text = (item.get("recommendation", "") + item.get("rationale", "")).lower()
        rel = 1.0 if any(kw.lower() in text for kw in expected) else 0.0
        relevances.append(rel)

    ideal = sorted(relevances, reverse=True)
    idcg = dcg(ideal)
    if idcg == 0:
        return 0.0
    return dcg(relevances) / idcg


def check_forbidden(retrieved: list[dict], forbidden: list[str], k: int = 3) -> list[str]:
    """Check if forbidden keywords appear in top-k results."""
    violations = []
    if not forbidden:
        return violations
    for item in retrieved[:k]:
        text = (item.get("recommendation", "") + item.get("rationale", "")).lower()
        for kw in forbidden:
            if kw.lower() in text:
                violations.append(kw)
    return violations


def run_evaluation(verbose: bool = False) -> dict[str, Any]:
    results = []
    per_role: dict[str, list[dict]] = {}

    for i, test in enumerate(GROUND_TRUTH):
        role = test["role"]
        try:
            rows = retrieve_strategy_knowledge(
                StrategyRetrievalQuery(
                    role=role,
                    phase=test["phase"],
                    observation_summary=test["summary"],
                    situation_tags=test["tags"],
                    top_k=5,
                )
            )
        except Exception as e:
            print(f"  ERROR [{test['description']}]: {e}")
            rows = []

        p1 = compute_precision_at_k(rows, test["expected_keywords"], 1)
        p3 = compute_precision_at_k(rows, test["expected_keywords"], 3)
        p5 = compute_precision_at_k(rows, test["expected_keywords"], 5)
        r3 = compute_recall_at_k(rows, test["expected_keywords"], 3)
        mrr = compute_mrr(rows, test["expected_keywords"])
        ndcg = compute_ndcg_at_k(rows, test["expected_keywords"], 5)
        forbidden_hits = check_forbidden(rows, test.get("forbidden_keywords", []), 3)

        result = {
            "description": test["description"],
            "role": role,
            "phase": test["phase"],
            "retrieved_count": len(rows),
            "precision@1": p1,
            "precision@3": p3,
            "precision@5": p5,
            "recall@3": r3,
            "mrr": mrr,
            "ndcg@5": ndcg,
            "forbidden_violations": forbidden_hits,
        }
        results.append(result)
        per_role.setdefault(role, []).append(result)

        if verbose:
            status = "✓" if p1 > 0 else "✗"
            print(
                f"  {status} {test['description']}: P@1={p1:.0%} P@3={p3:.0%} R@3={r3:.0%} MRR={mrr:.2f} NDCG={ndcg:.2f}"
            )
            if forbidden_hits:
                print(f"    ⚠ Forbidden keywords found: {forbidden_hits}")
            if verbose and p1 == 0:
                print(f"    Expected: {test['expected_keywords']}")
                for r in rows[:3]:
                    rec = r.get("recommendation", "")[:120]
                    print(f"    Got: [{r.get('score', 0):.2f}] {rec}")

    return {
        "results": results,
        "per_role": per_role,
        "summary": _compute_summary(results, per_role),
    }


def _compute_summary(results, per_role):
    metrics = ["precision@1", "precision@3", "precision@5", "recall@3", "mrr", "ndcg@5"]

    overall = {}
    for m in metrics:
        vals = [r[m] for r in results]
        overall[m] = {
            "mean": round(statistics.mean(vals), 3),
            "median": round(statistics.median(vals), 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
        }

    role_summary = {}
    for role, items in per_role.items():
        role_summary[role] = {}
        for m in metrics:
            vals = [r[m] for r in items]
            role_summary[role][m] = round(statistics.mean(vals), 3)

    forbidden_total = sum(len(r["forbidden_violations"]) for r in results)

    return {
        "overall": overall,
        "per_role": role_summary,
        "total_forbidden_violations": forbidden_total,
        "total_queries": len(results),
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--output", default=None, help="Save JSON report")
    args = ap.parse_args()

    print("=== Strategy Retrieval Precision Evaluation ===\n")
    print(f"Test queries: {len(GROUND_TRUTH)}")
    print(f"Roles: {sorted(set(t['role'] for t in GROUND_TRUTH))}")
    print()

    report = run_evaluation(verbose=args.verbose)

    # Print summary
    s = report["summary"]
    print("\n=== Overall Metrics ===")
    print(f"{'Metric':<16s} {'Mean':>8s} {'Median':>8s} {'Min':>8s} {'Max':>8s}")
    for m, vals in s["overall"].items():
        print(f"{m:<16s} {vals['mean']:>8.3f} {vals['median']:>8.3f} {vals['min']:>8.3f} {vals['max']:>8.3f}")

    print("\n=== Per-Role Precision@1 ===")
    for role in sorted(s["per_role"]):
        p1 = s["per_role"][role].get("precision@1", 0)
        bar = "█" * int(p1 * 20)
        print(f"  {role:<10s}: {p1:.0%} {bar}")

    print("\n=== Per-Role MRR ===")
    for role in sorted(s["per_role"]):
        mrr = s["per_role"][role].get("mrr", 0)
        bar = "█" * int(mrr * 20)
        print(f"  {role:<10s}: {mrr:.2f} {bar}")

    print(f"\n  Forbidden keyword violations: {s['total_forbidden_violations']}/{s['total_queries']}")

    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\nReport saved to {args.output}")

    # Exit code based on quality threshold
    overall_p1 = s["overall"]["precision@1"]["mean"]
    if overall_p1 < 0.5:
        print(f"\n⚠ Precision@1 = {overall_p1:.0%} below 50% threshold — retrieval needs improvement")
        return 1
    else:
        print(f"\n✓ Precision@1 = {overall_p1:.0%} meets 50% threshold")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
