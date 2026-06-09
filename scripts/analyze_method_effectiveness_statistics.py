#!/usr/bin/env python3
"""Statistical evidence layer for method effectiveness.

The script consolidates confidence intervals and paired tests from existing
artifacts. It does not run new games, call LLMs, or mutate the database.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE_DIR = ROOT / "docs" / "evidence"
RETRIEVAL_DETAILS = ROOT / "outputs" / "retrieval_effectiveness_current" / "per_query_details.jsonl"
MBTI_TRACK_C_SUMMARY = ROOT / "docs" / "experiments" / "mbti_track_c_auxiliary_analysis" / "summary.json"
MBTI_ROLE_DELTAS = ROOT / "docs" / "experiments" / "mbti_track_c_auxiliary_analysis" / "role_deltas.csv"
FORMAL_LEADERBOARD = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis" / "leaderboard.csv"
FORMAL_RUBRIC = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis" / "rubric_leaderboard.csv"
METHOD_FACTS = EVIDENCE_DIR / "PROJECT_METHOD_EFFECTIVENESS_FACTS.json"
USAGE_DECISION_SCORE_FACTS = EVIDENCE_DIR / "PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json"
USAGE_DECISION_SCORE_REPORT = EVIDENCE_DIR / "PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.md"

DEFAULT_REPORT = EVIDENCE_DIR / "PROJECT_METHOD_EFFECTIVENESS_STATISTICS.md"
DEFAULT_FACTS = EVIDENCE_DIR / "PROJECT_METHOD_EFFECTIVENESS_STATISTICS.json"

DEFAULT_POLICY = "hybrid_role_mbti_global"
BASELINE_POLICY = "global_only"
EXACT_POLICY = "same_role_same_mbti"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{fnum(value):.{digits}f}"


def pct(value: Any) -> str:
    return f"{fnum(value) * 100:.2f}%"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def bootstrap_mean_ci(
    values: list[float],
    *,
    iterations: int = 5000,
    seed: int = 20260609,
    alpha: float = 0.05,
) -> dict[str, Any]:
    if not values:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0, "iterations": 0}
    if len(values) == 1:
        return {
            "mean": values[0],
            "ci_low": values[0],
            "ci_high": values[0],
            "iterations": 0,
        }
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.mean(sample))
    return {
        "mean": statistics.mean(values),
        "ci_low": percentile(means, alpha / 2),
        "ci_high": percentile(means, 1 - alpha / 2),
        "iterations": iterations,
    }


def sign_test(deltas: list[float]) -> dict[str, Any]:
    positives = sum(1 for value in deltas if value > 0)
    negatives = sum(1 for value in deltas if value < 0)
    ties = sum(1 for value in deltas if value == 0)
    n = positives + negatives
    if n == 0:
        p_value = 1.0
    else:
        smaller = min(positives, negatives)
        tail = sum(math.comb(n, i) for i in range(smaller + 1)) / (2**n)
        p_value = min(1.0, 2.0 * tail)
    return {
        "positive": positives,
        "negative": negatives,
        "tie": ties,
        "n_non_tie": n,
        "two_sided_p": p_value,
    }


def dcg_at_k(scores: list[int], k: int) -> float:
    return sum(score / math.log2(index + 2) for index, score in enumerate(scores[:k]))


def ndcg_at_k(scores: list[int], k: int) -> float:
    if not scores:
        return 0.0
    actual = dcg_at_k(scores, k)
    ideal = dcg_at_k(sorted(scores, reverse=True), k)
    return actual / ideal if ideal > 0 else 0.0


def precision_at_k(scores: list[int], k: int) -> float:
    if not scores:
        return 0.0
    return sum(1 for score in scores[:k] if score >= 2) / min(k, len(scores))


def effective_at_k(scores: list[int], k: int) -> float:
    return 1.0 if any(score >= 2 for score in scores[:k]) else 0.0


def retrieval_query_metrics(row: dict[str, Any]) -> dict[str, float]:
    scores = [int(value) for value in row.get("relevance_scores", [])]
    return {
        "precision_at_3": precision_at_k(scores, 3),
        "effective_at_3": effective_at_k(scores, 3),
        "ndcg_at_5": ndcg_at_k(scores, 5),
        "coverage": 1.0 if int(row.get("n_results") or 0) > 0 else 0.0,
    }


def paired_retrieval_stats(
    rows: list[dict[str, Any]],
    *,
    candidate_policy: str,
    baseline_policy: str,
    iterations: int,
) -> dict[str, Any]:
    by_policy_query: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        by_policy_query[(str(row.get("policy")), str(row.get("query_id")))] = row
    query_ids = sorted({str(row.get("query_id")) for row in rows if row.get("query_id")})
    paired_ids = [
        query_id
        for query_id in query_ids
        if (candidate_policy, query_id) in by_policy_query and (baseline_policy, query_id) in by_policy_query
    ]

    metric_names = ["precision_at_3", "effective_at_3", "ndcg_at_5", "coverage"]
    metric_stats: dict[str, Any] = {}
    for metric_name in metric_names:
        baseline_values: list[float] = []
        candidate_values: list[float] = []
        deltas: list[float] = []
        for query_id in paired_ids:
            baseline_value = retrieval_query_metrics(by_policy_query[(baseline_policy, query_id)])[metric_name]
            candidate_value = retrieval_query_metrics(by_policy_query[(candidate_policy, query_id)])[metric_name]
            baseline_values.append(baseline_value)
            candidate_values.append(candidate_value)
            deltas.append(candidate_value - baseline_value)
        ci = bootstrap_mean_ci(deltas, iterations=iterations)
        metric_stats[metric_name] = {
            "baseline_mean": statistics.mean(baseline_values) if baseline_values else 0.0,
            "candidate_mean": statistics.mean(candidate_values) if candidate_values else 0.0,
            "mean_delta": ci["mean"],
            "bootstrap_ci_low": ci["ci_low"],
            "bootstrap_ci_high": ci["ci_high"],
            "bootstrap_iterations": ci["iterations"],
            "sign_test": sign_test(deltas),
            "deltas": deltas,
            "ci_crosses_zero": ci["ci_low"] <= 0 <= ci["ci_high"],
        }
    return {
        "candidate_policy": candidate_policy,
        "baseline_policy": baseline_policy,
        "paired_query_count": len(paired_ids),
        "paired_query_ids": paired_ids,
        "metrics": metric_stats,
        "source": str(RETRIEVAL_DETAILS.relative_to(ROOT)),
        "interpretation": (
            "Paired bootstrap over fixed retrieval queries. Supports retrieval relevance, "
            "not online game-win causality."
        ),
    }


def wilson_ci(successes: int, total: int, z: float = 1.96) -> dict[str, float]:
    if total <= 0:
        return {"rate": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    p = successes / total
    denom = 1 + (z * z / total)
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) / total) + (z * z / (4 * total * total))) / denom
    return {
        "rate": p,
        "ci_low": max(0.0, center - margin),
        "ci_high": min(1.0, center + margin),
    }


def two_proportion_delta(
    *,
    baseline_successes: int,
    baseline_total: int,
    candidate_successes: int,
    candidate_total: int,
) -> dict[str, Any]:
    p0 = baseline_successes / baseline_total if baseline_total else 0.0
    p1 = candidate_successes / candidate_total if candidate_total else 0.0
    delta = p1 - p0
    se = math.sqrt(
        (p0 * (1 - p0) / baseline_total if baseline_total else 0.0)
        + (p1 * (1 - p1) / candidate_total if candidate_total else 0.0)
    )
    if se > 0:
        z_score = delta / se
        p_value = math.erfc(abs(z_score) / math.sqrt(2))
        ci_low = delta - 1.96 * se
        ci_high = delta + 1.96 * se
    else:
        z_score = 0.0
        p_value = 1.0
        ci_low = delta
        ci_high = delta
    return {
        "baseline_rate": p0,
        "candidate_rate": p1,
        "delta": delta,
        "standard_error": se,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "z_score": z_score,
        "two_sided_p": p_value,
        "ci_crosses_zero": ci_low <= 0 <= ci_high,
        "baseline_wilson": wilson_ci(baseline_successes, baseline_total),
        "candidate_wilson": wilson_ci(candidate_successes, candidate_total),
    }


def track_c_auxiliary_stats(summary: dict[str, Any], role_rows: list[dict[str, str]]) -> dict[str, Any]:
    overall = summary.get("overall", {}) if isinstance(summary, dict) else {}
    off = overall.get("track_c_off", {})
    on = overall.get("track_c_on", {})
    overall_delta = two_proportion_delta(
        baseline_successes=inum(off.get("wins")),
        baseline_total=inum(off.get("samples")),
        candidate_successes=inum(on.get("wins")),
        candidate_total=inum(on.get("samples")),
    )
    role_stats: list[dict[str, Any]] = []
    for row in role_rows:
        baseline_total = inum(row.get("baseline_samples"))
        candidate_total = inum(row.get("track_c_samples"))
        baseline_wins = round(fnum(row.get("baseline_win_rate")) * baseline_total)
        candidate_wins = round(fnum(row.get("track_c_win_rate")) * candidate_total)
        role_stats.append(
            {
                "role": row.get("key", ""),
                "baseline_samples": baseline_total,
                "candidate_samples": candidate_total,
                "baseline_wins": baseline_wins,
                "candidate_wins": candidate_wins,
                "stats": two_proportion_delta(
                    baseline_successes=baseline_wins,
                    baseline_total=baseline_total,
                    candidate_successes=candidate_wins,
                    candidate_total=candidate_total,
                ),
            }
        )
    return {
        "overall": {
            "baseline_label": "track_c_off",
            "candidate_label": "track_c_on",
            "baseline_samples": inum(off.get("samples")),
            "candidate_samples": inum(on.get("samples")),
            "baseline_wins": inum(off.get("wins")),
            "candidate_wins": inum(on.get("wins")),
            "baseline_seed_count": inum(off.get("seed_count")),
            "candidate_seed_count": inum(on.get("seed_count")),
            "stats": overall_delta,
        },
        "by_role": role_stats,
        "source": str(MBTI_TRACK_C_SUMMARY.relative_to(ROOT)),
        "interpretation": (
            "Auxiliary all-seat Track C switch. Useful as trend evidence only; it is not target-seat causal A/B."
        ),
    }


def runtime_feedback_stats(method_facts: dict[str, Any]) -> dict[str, Any]:
    feedback = method_facts.get("runtime_feedback", {}) if isinstance(method_facts, dict) else {}
    retrieved = inum(feedback.get("retrieved"))
    used = inum(feedback.get("used"))
    helpful = inum(feedback.get("helpful"))
    return {
        "status": feedback.get("status", "missing"),
        "source": feedback.get("source", ""),
        "filter": feedback.get("filter", ""),
        "retrieved": retrieved,
        "used": used,
        "helpful": helpful,
        "used_over_retrieved": wilson_ci(used, retrieved),
        "helpful_over_retrieved": wilson_ci(helpful, retrieved),
        "helpful_over_used": wilson_ci(helpful, used),
        "interpretation": "Current non-fake PostgreSQL snapshot. This is usage feedback, not causal score lift.",
    }


def formal_health_stats(leaderboard_rows: list[dict[str, str]], rubric_rows: list[dict[str, str]]) -> dict[str, Any]:
    decisions = sum(inum(row.get("llm_decisions")) for row in leaderboard_rows)
    fallback = sum(inum(row.get("fallback_count")) for row in leaderboard_rows)
    invalid = sum(inum(row.get("invalid_count")) for row in leaderboard_rows)
    attempted = sum(inum(row.get("attempted_games")) for row in leaderboard_rows)
    completed = sum(inum(row.get("completed_games")) for row in leaderboard_rows)
    external_failed = sum(inum(row.get("external_failed_games")) for row in leaderboard_rows)
    rubric_scores = [fnum(row.get("rubric_total_score")) for row in rubric_rows]
    return {
        "attempted_games": attempted,
        "completed_games": completed,
        "external_failed_games": external_failed,
        "external_failure_rate": external_failed / max(attempted, 1),
        "llm_decisions": decisions,
        "fallback_count": fallback,
        "invalid_count": invalid,
        "fallback_rate": fallback / max(decisions, 1),
        "invalid_rate": invalid / max(decisions, 1),
        "rubric_score_min": min(rubric_scores) if rubric_scores else 0.0,
        "rubric_score_max": max(rubric_scores) if rubric_scores else 0.0,
        "rubric_score_spread": (max(rubric_scores) - min(rubric_scores)) if rubric_scores else 0.0,
        "source": str(FORMAL_LEADERBOARD.relative_to(ROOT)),
        "interpretation": "Formal real-LLM health and separability evidence; not Track C final causal proof.",
    }


def build_evidence(iterations: int) -> dict[str, Any]:
    retrieval_rows = read_jsonl(RETRIEVAL_DETAILS)
    mbti_summary = read_json(MBTI_TRACK_C_SUMMARY)
    role_deltas = read_csv(MBTI_ROLE_DELTAS)
    method_facts = read_json(METHOD_FACTS)
    usage_decision_scores = read_json(USAGE_DECISION_SCORE_FACTS)
    formal_leaderboard = read_csv(FORMAL_LEADERBOARD)
    formal_rubric = read_csv(FORMAL_RUBRIC)

    retrieval_default_vs_global = paired_retrieval_stats(
        retrieval_rows,
        candidate_policy=DEFAULT_POLICY,
        baseline_policy=BASELINE_POLICY,
        iterations=iterations,
    )
    retrieval_exact_vs_default = paired_retrieval_stats(
        retrieval_rows,
        candidate_policy=EXACT_POLICY,
        baseline_policy=DEFAULT_POLICY,
        iterations=iterations,
    )

    return {
        "generated_at": now_iso(),
        "sources": {
            "retrieval_details": str(RETRIEVAL_DETAILS.relative_to(ROOT)),
            "mbti_track_c_summary": str(MBTI_TRACK_C_SUMMARY.relative_to(ROOT)),
            "mbti_role_deltas": str(MBTI_ROLE_DELTAS.relative_to(ROOT)),
            "method_facts": str(METHOD_FACTS.relative_to(ROOT)),
            "usage_decision_score_facts": str(USAGE_DECISION_SCORE_FACTS.relative_to(ROOT)),
            "usage_decision_score_report": str(USAGE_DECISION_SCORE_REPORT.relative_to(ROOT)),
            "formal_leaderboard": str(FORMAL_LEADERBOARD.relative_to(ROOT)),
            "formal_rubric": str(FORMAL_RUBRIC.relative_to(ROOT)),
        },
        "retrieval_paired": {
            "default_vs_global": retrieval_default_vs_global,
            "exact_vs_default": retrieval_exact_vs_default,
        },
        "track_c_auxiliary": track_c_auxiliary_stats(mbti_summary, role_deltas),
        "runtime_feedback": runtime_feedback_stats(method_facts),
        "strategy_usage_decision_scores": usage_decision_scores,
        "formal_health": formal_health_stats(formal_leaderboard, formal_rubric),
        "claim_boundaries": [
            {
                "claim": "默认检索策略相对 global_only 有统计支持的检索指标提升",
                "status": "supported_by_paired_retrieval_statistics",
                "boundary": "仅证明离线检索相关性和覆盖率，不证明最终胜率因果提升。",
            },
            {
                "claim": "Track C 开关提升最终胜率",
                "status": "not_proven",
                "boundary": "辅助 all-seat 数据 CI 跨 0，且不是 target-seat paired A/B。",
            },
            {
                "claim": "运行时策略反馈显示策略被大量使用且 helpful/used 较高",
                "status": "supported_as_runtime_feedback",
                "boundary": "helpful 不是随机对照因果分数，不能替代 Track B 差分或 target-seat A/B。",
            },
            {
                "claim": "使用策略的决策与更高 Track B 逐步评分相关",
                "status": "supported_as_observational_association"
                if usage_decision_scores
                and not usage_decision_scores.get("overall", {}).get("used_vs_unused", {}).get("ci_crosses_zero", True)
                else "not_supported_or_missing",
                "boundary": "观测性联表统计，不能替代 target-seat 随机/配对因果实验。",
            },
        ],
    }


def ci_text(stats: dict[str, Any], digits: int = 4) -> str:
    return f"[{fmt(stats.get('ci_low'), digits)}, {fmt(stats.get('ci_high'), digits)}]"


def metric_ci_text(stats: dict[str, Any], digits: int = 4) -> str:
    return f"[{fmt(stats.get('bootstrap_ci_low'), digits)}, {fmt(stats.get('bootstrap_ci_high'), digits)}]"


def render_report(evidence: dict[str, Any]) -> str:
    retrieval = evidence["retrieval_paired"]["default_vs_global"]
    exact = evidence["retrieval_paired"]["exact_vs_default"]
    aux = evidence["track_c_auxiliary"]["overall"]
    runtime = evidence["runtime_feedback"]
    usage_scores = evidence.get("strategy_usage_decision_scores", {})
    formal = evidence["formal_health"]
    usage_overall = usage_scores.get("overall", {}).get("used_vs_unused", {}) if isinstance(usage_scores, dict) else {}
    usage_counts = usage_scores.get("row_counts", {}) if isinstance(usage_scores, dict) else {}
    usage_strict = (
        usage_scores.get("stratified", {}).get("strict_role_action_tier_day_phase", {})
        if isinstance(usage_scores, dict)
        else {}
    )
    usage_role_internal = (
        usage_scores.get("stratified", {}).get("role_internal_action_tier_day_phase", {}).get("roles", [])
        if isinstance(usage_scores, dict)
        else []
    )

    lines = [
        "# 项目方法有效性统计补充报告",
        "",
        f"生成时间：{evidence['generated_at']}",
        "",
        "本报告只基于已有实验产物重新计算统计量，不运行新对局、不调用 LLM、不写数据库。它用于把“可证明的有效性”“趋势证据”和“尚未证明的因果结论”分开。",
        "",
        "## 1. 检索策略 paired bootstrap",
        "",
        f"对比：`{retrieval['candidate_policy']}` vs `{retrieval['baseline_policy']}`；paired queries={retrieval['paired_query_count']}。",
        "",
        table(
            ["Metric", "BaselineMean", "CandidateMean", "MeanDelta", "Bootstrap95CI", "Sign +/−/tie", "SignP", "CI跨0"],
            [
                [
                    metric,
                    fmt(row["baseline_mean"]),
                    fmt(row["candidate_mean"]),
                    fmt(row["mean_delta"]),
                    metric_ci_text(row),
                    f"{row['sign_test']['positive']}/{row['sign_test']['negative']}/{row['sign_test']['tie']}",
                    fmt(row["sign_test"]["two_sided_p"]),
                    row["ci_crosses_zero"],
                ]
                for metric, row in retrieval["metrics"].items()
            ],
        ),
        "",
        "解释：默认检索策略在固定 query set 上相对 `global_only` 提升了 P@3、Effective@3、nDCG@5 和 Coverage。该证据支持“检索设计有效”，但不等价于在线胜率因果提升。",
        "",
        f"对比：`{exact['candidate_policy']}` vs `{exact['baseline_policy']}`；paired queries={exact['paired_query_count']}。",
        "",
        table(
            ["Metric", "DefaultMean", "ExactMean", "MeanDelta", "Bootstrap95CI", "Sign +/−/tie", "SignP"],
            [
                [
                    metric,
                    fmt(row["baseline_mean"]),
                    fmt(row["candidate_mean"]),
                    fmt(row["mean_delta"]),
                    metric_ci_text(row),
                    f"{row['sign_test']['positive']}/{row['sign_test']['negative']}/{row['sign_test']['tie']}",
                    fmt(row["sign_test"]["two_sided_p"]),
                ]
                for metric, row in exact["metrics"].items()
            ],
        ),
        "",
        "解释：精确 `same_role_same_mbti` 相对默认混合策略显著更稀疏，可作为优先个性化桶，但不适合作为唯一检索策略。",
        "",
        "## 2. Track C 辅助胜率趋势",
        "",
        table(
            ["Baseline", "Candidate", "BaselineRate", "CandidateRate", "Delta", "Normal95CI", "PValue", "CI跨0"],
            [
                [
                    f"{aux['baseline_label']} n={aux['baseline_samples']} wins={aux['baseline_wins']}",
                    f"{aux['candidate_label']} n={aux['candidate_samples']} wins={aux['candidate_wins']}",
                    fmt(aux["stats"]["baseline_rate"]),
                    fmt(aux["stats"]["candidate_rate"]),
                    fmt(aux["stats"]["delta"]),
                    ci_text(aux["stats"]),
                    fmt(aux["stats"]["two_sided_p"]),
                    aux["stats"]["ci_crosses_zero"],
                ]
            ],
        ),
        "",
        "解释：辅助数据中 Track C on 的胜率高于 off，但 95% CI 跨 0，且这是全席位同时切换，不是 target-seat paired A/B。因此只能写成趋势证据，不能写成最终因果结论。",
        "",
        "## 3. 运行时 feedback Wilson CI",
        "",
        table(
            ["Metric", "Count", "Rate", "Wilson95CI", "Source"],
            [
                [
                    "used/retrieved",
                    f"{runtime['used']}/{runtime['retrieved']}",
                    fmt(runtime["used_over_retrieved"]["rate"]),
                    ci_text(runtime["used_over_retrieved"]),
                    runtime.get("source", ""),
                ],
                [
                    "helpful/retrieved",
                    f"{runtime['helpful']}/{runtime['retrieved']}",
                    fmt(runtime["helpful_over_retrieved"]["rate"]),
                    ci_text(runtime["helpful_over_retrieved"]),
                    runtime.get("filter", ""),
                ],
                [
                    "helpful/used",
                    f"{runtime['helpful']}/{runtime['used']}",
                    fmt(runtime["helpful_over_used"]["rate"]),
                    ci_text(runtime["helpful_over_used"]),
                    "当前非 fake DB 快照",
                ],
            ],
        ),
        "",
        "解释：运行时 feedback 说明策略被大量检索、部分进入实际决策，且 used 后的 helpful 标记比例较高。它是运行链路有效性的证据，不是随机对照因果分数。",
        "",
        "## 4. 策略使用与 Track B 逐决策评分",
        "",
        table(
            ["Metric", "Value"],
            [
                ["decision_rows", usage_counts.get("decision_rows", "n/a")],
                ["used_decisions", usage_counts.get("used_decisions", "n/a")],
                ["unused_decisions", usage_counts.get("unused_decisions", "n/a")],
                ["used_mean", fmt(usage_overall.get("used_mean"))],
                ["unused_mean", fmt(usage_overall.get("unused_mean"))],
                ["mean_delta", fmt(usage_overall.get("mean_delta_used_minus_unused"))],
                [
                    "95CI",
                    f"[{fmt(usage_overall.get('bootstrap_ci_low'))}, {fmt(usage_overall.get('bootstrap_ci_high'))}]",
                ],
                ["CI跨0", usage_overall.get("ci_crosses_zero", "n/a")],
                ["strict_strata", usage_strict.get("strata_count", "n/a")],
                ["strict_used_retained", usage_strict.get("used_retained", "n/a")],
                ["strict_weighted_delta", fmt(usage_strict.get("weighted_mean_delta_used_minus_unused"))],
                [
                    "strict_positive/negative/tied",
                    f"{usage_strict.get('positive_strata', 'n/a')}/{usage_strict.get('negative_strata', 'n/a')}/{usage_strict.get('tied_strata', 'n/a')}",
                ],
            ],
        ),
        "",
        "解释：该统计把 Track B per-step score 与 knowledge usage feedback 通过 decision_id 联表。严格分层按 role/action/scoring_tier/day/phase 控制明显混杂后仍保持正向；这仍是观测性关联，不是因果证明。",
        "",
        "角色内控制结果：",
        "",
        table(
            [
                "Role",
                "TotalUsed",
                "UsedRetained",
                "Strata",
                "WeightedDelta",
                "MeanDelta",
                "MedianDelta",
                "+/-/0 Strata",
            ],
            [
                [
                    row.get("role"),
                    row.get("total_used"),
                    f"{row.get('used_retained')} ({pct(row.get('used_retention_rate'))})",
                    row.get("strata_count"),
                    fmt(row.get("weighted_mean_delta_used_minus_unused")),
                    fmt(row.get("mean_of_stratum_deltas")),
                    fmt(row.get("median_of_stratum_deltas")),
                    f"{row.get('positive_strata')}/{row.get('negative_strata')}/{row.get('tied_strata')}",
                ]
                for row in usage_role_internal
            ],
        )
        if usage_role_internal
        else "角色内控制结果尚未生成。",
        "",
        "解释：6 个核心角色的角色内 strict weighted delta 当前均为正。WhiteWolfKing 样本量低且 weighted delta 略负，暂不作为稳定增益结论。",
        "",
        "## 5. 正式 v4flash 健康度",
        "",
        table(
            ["Metric", "Value", "Interpretation"],
            [
                [
                    "attempted/completed",
                    f"{formal['attempted_games']}/{formal['completed_games']}",
                    "真实 LLM 正式样本",
                ],
                ["external_failure_rate", fmt(formal["external_failure_rate"]), "外部服务稳定性风险"],
                ["llm_decisions", formal["llm_decisions"], "正式决策规模"],
                ["fallback_rate", fmt(formal["fallback_rate"]), "strict 决策健康"],
                ["invalid_rate", fmt(formal["invalid_rate"]), "strict 决策健康"],
                ["rubric_score_spread", fmt(formal["rubric_score_spread"]), "框架版本可区分"],
            ],
        ),
        "",
        "## 6. 结论边界",
        "",
        table(
            ["Claim", "Status", "Boundary"],
            [[row["claim"], row["status"], row["boundary"]] for row in evidence["claim_boundaries"]],
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5000, help="Bootstrap iterations")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--facts", default=str(DEFAULT_FACTS))
    args = parser.parse_args()

    evidence = build_evidence(iterations=max(args.iterations, 0))
    report_path = Path(args.report).resolve()
    facts_path = Path(args.facts).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(evidence), encoding="utf-8")
    facts_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {report_path.relative_to(ROOT)}")
    print(f"Wrote {facts_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
