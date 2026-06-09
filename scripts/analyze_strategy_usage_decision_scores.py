#!/usr/bin/env python3
"""Decision-level Track C usage vs Track B score analysis.

The analysis joins:
  published_reviews.report_json.metadata.per_step_scores[*].decision_id
  -> agent_decisions.id
  -> knowledge_usage_feedback.decision_id

It excludes fake/offline games and aggregates knowledge feedback rows at the
decision level before comparing scores.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE_DIR = ROOT / "docs" / "evidence"
DEFAULT_REPORT = EVIDENCE_DIR / "PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.md"
DEFAULT_FACTS = EVIDENCE_DIR / "PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json"


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


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


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


def bootstrap_delta_ci(
    a_values: list[float],
    b_values: list[float],
    *,
    iterations: int = 3000,
    seed: int = 20260609,
    alpha: float = 0.05,
) -> dict[str, float | int]:
    """Estimate CI for mean(a)-mean(b).

    Full bootstrap over 100k+ decision rows is unnecessarily expensive. For
    large samples, use the Welch normal approximation; for smaller samples,
    retain bootstrap.
    """
    if not a_values or not b_values:
        return {"mean_delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "iterations": 0, "method": "empty"}
    delta = statistics.mean(a_values) - statistics.mean(b_values)
    if len(a_values) == 1 or len(b_values) == 1 or iterations <= 0:
        return {"mean_delta": delta, "ci_low": delta, "ci_high": delta, "iterations": 0, "method": "point"}
    if (len(a_values) + len(b_values)) * iterations > 5_000_000:
        var_a = statistics.variance(a_values) if len(a_values) > 1 else 0.0
        var_b = statistics.variance(b_values) if len(b_values) > 1 else 0.0
        se = math.sqrt(var_a / len(a_values) + var_b / len(b_values))
        ci_low = delta - 1.96 * se
        ci_high = delta + 1.96 * se
        return {
            "mean_delta": delta,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "iterations": 0,
            "method": "welch_normal",
        }
    rng = random.Random(seed)
    sampled: list[float] = []
    for _ in range(iterations):
        a_sample = [a_values[rng.randrange(len(a_values))] for _ in range(len(a_values))]
        b_sample = [b_values[rng.randrange(len(b_values))] for _ in range(len(b_values))]
        sampled.append(statistics.mean(a_sample) - statistics.mean(b_sample))
    return {
        "mean_delta": delta,
        "ci_low": percentile(sampled, alpha / 2),
        "ci_high": percentile(sampled, 1 - alpha / 2),
        "iterations": iterations,
        "method": "bootstrap",
    }


def safe_mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def safe_median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def group_summary(
    used_scores: list[float],
    unused_scores: list[float],
    *,
    iterations: int,
) -> dict[str, Any]:
    delta = bootstrap_delta_ci(used_scores, unused_scores, iterations=iterations)
    return {
        "used_count": len(used_scores),
        "unused_count": len(unused_scores),
        "used_mean": safe_mean(used_scores),
        "unused_mean": safe_mean(unused_scores),
        "used_median": safe_median(used_scores),
        "unused_median": safe_median(unused_scores),
        "mean_delta_used_minus_unused": delta["mean_delta"],
        "bootstrap_ci_low": delta["ci_low"],
        "bootstrap_ci_high": delta["ci_high"],
        "bootstrap_iterations": delta["iterations"],
        "ci_method": delta["method"],
        "ci_crosses_zero": bool(delta["ci_low"] <= 0 <= delta["ci_high"]),
    }


def load_decision_rows(limit: int = 0, *, statement_timeout_ms: int = 90_000) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from backend.db import SessionLocal

    limit_sql = "LIMIT :limit" if limit > 0 else ""
    query = text(
        f"""
        WITH steps AS (
          SELECT
            pr.game_id,
            step->>'decision_id' AS decision_id,
            NULLIF(step->>'day', '')::int AS day,
            step->>'role' AS role,
            step->>'phase' AS phase,
            step->>'action_type' AS action_type,
            NULLIF(step->>'overall_score', '')::float AS overall_score,
            NULLIF(step->>'correctness', '')::float AS correctness,
            step->>'scoring_tier' AS scoring_tier
          FROM published_reviews pr,
          LATERAL jsonb_array_elements(pr.report_json->'metadata'->'per_step_scores') step
          WHERE jsonb_typeof(pr.report_json->'metadata'->'per_step_scores') = 'array'
            AND step ? 'decision_id'
            AND COALESCE(step->>'decision_id', '') <> ''
            AND step ? 'overall_score'
        ),
        nonfake_steps AS (
          SELECT s.*
          FROM steps s
          WHERE NOT EXISTS (
            SELECT 1 FROM players p_fake
            WHERE p_fake.game_id = s.game_id
              AND lower(COALESCE(p_fake.model_name, '')) LIKE '%fake%'
          )
        ),
        feedback AS (
          SELECT
            k.decision_id,
            COUNT(*) AS feedback_rows,
            COUNT(DISTINCT k.knowledge_doc_id) AS distinct_docs,
            BOOL_OR(k.retrieved IS TRUE) AS retrieved,
            BOOL_OR(k.used IS TRUE) AS used,
            BOOL_OR(k.helpful IS TRUE) AS helpful,
            AVG(COALESCE(k.score_delta, 0.0)) AS avg_feedback_score_delta
          FROM knowledge_usage_feedback k
          WHERE k.decision_id IS NOT NULL AND k.decision_id <> ''
          GROUP BY k.decision_id
        )
        SELECT
          s.game_id,
          s.decision_id,
          s.day,
          s.role,
          s.phase,
          s.action_type,
          s.overall_score,
          s.correctness,
          s.scoring_tier,
          d.player_id,
          d.model_name,
          d.provider,
          COALESCE(f.feedback_rows, 0) AS feedback_rows,
          COALESCE(f.distinct_docs, 0) AS distinct_docs,
          COALESCE(f.retrieved, FALSE) AS retrieved,
          COALESCE(f.used, FALSE) AS used,
          COALESCE(f.helpful, FALSE) AS helpful,
          COALESCE(f.avg_feedback_score_delta, 0.0) AS avg_feedback_score_delta
        FROM nonfake_steps s
        JOIN agent_decisions d ON d.id = s.decision_id
        LEFT JOIN feedback f ON f.decision_id = s.decision_id
        WHERE s.overall_score IS NOT NULL
        {limit_sql}
        """
    )
    params = {"limit": limit} if limit > 0 else {}
    with SessionLocal() as db:
        if statement_timeout_ms > 0:
            db.execute(text("SET LOCAL statement_timeout = :timeout_ms"), {"timeout_ms": statement_timeout_ms})
        return [dict(row) for row in db.execute(query, params).mappings()]


def summarize_by_key(
    rows: list[dict[str, Any]], key: str, *, iterations: int, min_used: int, min_unused: int
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"used": [], "unused": []})
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            continue
        bucket = "used" if bool(row.get("used")) else "unused"
        grouped[value][bucket].append(fnum(row.get("overall_score")))

    result: list[dict[str, Any]] = []
    for value, group in grouped.items():
        if len(group["used"]) < min_used or len(group["unused"]) < min_unused:
            continue
        summary = group_summary(group["used"], group["unused"], iterations=iterations)
        summary[key] = value
        result.append(summary)
    result.sort(
        key=lambda item: (item["used_count"] + item["unused_count"], item["mean_delta_used_minus_unused"]), reverse=True
    )
    return result


def summarize_helpful(rows: list[dict[str, Any]], *, iterations: int) -> dict[str, Any]:
    helpful_scores = [
        fnum(row.get("overall_score")) for row in rows if bool(row.get("used")) and bool(row.get("helpful"))
    ]
    unhelpful_scores = [
        fnum(row.get("overall_score")) for row in rows if bool(row.get("used")) and not bool(row.get("helpful"))
    ]
    return group_summary(helpful_scores, unhelpful_scores, iterations=iterations)


def stratified_summary(
    rows: list[dict[str, Any]],
    keys: list[str],
    *,
    iterations: int,
    min_used: int = 5,
    min_unused: int = 20,
) -> dict[str, Any]:
    """Compare used vs unused within matching strata, then aggregate.

    This reduces obvious confounding from role/action/phase/day distributions.
    The aggregate uses used-decision counts as weights because the question is:
    "When Track C is used, how does the matched decision score compare?"
    """
    grouped: dict[tuple[str, ...], dict[str, list[float]]] = defaultdict(lambda: {"used": [], "unused": []})
    for row in rows:
        key = tuple(str(row.get(name) if row.get(name) is not None else "") for name in keys)
        if any(part == "" for part in key):
            continue
        bucket = "used" if bool(row.get("used")) else "unused"
        grouped[key][bucket].append(fnum(row.get("overall_score")))

    strata: list[dict[str, Any]] = []
    weighted_delta_sum = 0.0
    weight_sum = 0.0
    used_retained = 0
    unused_retained = 0

    for key, group in grouped.items():
        used_scores = group["used"]
        unused_scores = group["unused"]
        if len(used_scores) < min_used or len(unused_scores) < min_unused:
            continue
        summary = group_summary(used_scores, unused_scores, iterations=iterations)
        label = "|".join(f"{name}={value}" for name, value in zip(keys, key))
        weight = float(len(used_scores))
        weighted_delta_sum += weight * fnum(summary.get("mean_delta_used_minus_unused"))
        weight_sum += weight
        used_retained += len(used_scores)
        unused_retained += len(unused_scores)
        strata.append(
            {
                "stratum": label,
                "keys": dict(zip(keys, key)),
                **summary,
            }
        )

    strata.sort(key=lambda item: item["used_count"], reverse=True)
    deltas = [fnum(item.get("mean_delta_used_minus_unused")) for item in strata]
    positive = sum(1 for value in deltas if value > 0)
    negative = sum(1 for value in deltas if value < 0)
    tied = sum(1 for value in deltas if value == 0)
    weighted_delta = weighted_delta_sum / weight_sum if weight_sum else 0.0

    return {
        "keys": keys,
        "min_used_per_stratum": min_used,
        "min_unused_per_stratum": min_unused,
        "strata_count": len(strata),
        "used_retained": used_retained,
        "unused_retained": unused_retained,
        "used_retention_rate": used_retained / max(sum(1 for row in rows if bool(row.get("used"))), 1),
        "weighted_mean_delta_used_minus_unused": weighted_delta,
        "mean_of_stratum_deltas": safe_mean(deltas),
        "median_of_stratum_deltas": safe_median(deltas),
        "positive_strata": positive,
        "negative_strata": negative,
        "tied_strata": tied,
        "top_strata": strata[:20],
    }


def role_internal_stratified_summary(
    rows: list[dict[str, Any]],
    keys: list[str],
    *,
    iterations: int,
    min_used: int = 3,
    min_unused: int = 15,
) -> list[dict[str, Any]]:
    """Run stratified used-vs-unused comparisons separately within each role."""
    roles = sorted({str(row.get("role") or "") for row in rows if row.get("role")})
    role_rows: list[dict[str, Any]] = []
    for role in roles:
        subset = [row for row in rows if str(row.get("role") or "") == role]
        total_used = sum(1 for row in subset if bool(row.get("used")))
        total_unused = sum(1 for row in subset if not bool(row.get("used")))
        summary = stratified_summary(
            subset,
            keys,
            iterations=iterations,
            min_used=min_used,
            min_unused=min_unused,
        )
        retained_used = inum(summary.get("used_retained"))
        retained_unused = inum(summary.get("unused_retained"))
        role_rows.append(
            {
                "role": role,
                "total_used": total_used,
                "total_unused": total_unused,
                "strata_count": summary.get("strata_count", 0),
                "used_retained": retained_used,
                "unused_retained": retained_unused,
                "used_retention_rate": retained_used / max(total_used, 1),
                "unused_retention_rate": retained_unused / max(total_unused, 1),
                "weighted_mean_delta_used_minus_unused": summary.get("weighted_mean_delta_used_minus_unused", 0.0),
                "mean_of_stratum_deltas": summary.get("mean_of_stratum_deltas", 0.0),
                "median_of_stratum_deltas": summary.get("median_of_stratum_deltas", 0.0),
                "positive_strata": summary.get("positive_strata", 0),
                "negative_strata": summary.get("negative_strata", 0),
                "tied_strata": summary.get("tied_strata", 0),
                "top_strata": summary.get("top_strata", [])[:10],
            }
        )
    role_rows.sort(key=lambda row: row["total_used"], reverse=True)
    return role_rows


def build_evidence(iterations: int, limit: int = 0, *, statement_timeout_ms: int = 90_000) -> dict[str, Any]:
    rows = load_decision_rows(limit=limit, statement_timeout_ms=statement_timeout_ms)
    used_scores = [fnum(row.get("overall_score")) for row in rows if bool(row.get("used"))]
    unused_scores = [fnum(row.get("overall_score")) for row in rows if not bool(row.get("used"))]
    retrieved_scores = [fnum(row.get("overall_score")) for row in rows if bool(row.get("retrieved"))]
    no_retrieval_scores = [fnum(row.get("overall_score")) for row in rows if not bool(row.get("retrieved"))]

    overall_used = group_summary(used_scores, unused_scores, iterations=iterations)
    overall_retrieved = group_summary(retrieved_scores, no_retrieval_scores, iterations=iterations)
    helpful = summarize_helpful(rows, iterations=iterations)

    by_role = summarize_by_key(rows, "role", iterations=iterations, min_used=50, min_unused=200)
    by_action = summarize_by_key(rows, "action_type", iterations=iterations, min_used=50, min_unused=200)
    by_phase = summarize_by_key(rows, "phase", iterations=iterations, min_used=50, min_unused=200)
    stratified_coarse = stratified_summary(
        rows,
        ["role", "action_type", "scoring_tier"],
        iterations=0,
        min_used=5,
        min_unused=20,
    )
    stratified_strict = stratified_summary(
        rows,
        ["role", "action_type", "scoring_tier", "day", "phase"],
        iterations=0,
        min_used=5,
        min_unused=20,
    )
    role_internal_coarse = role_internal_stratified_summary(
        rows,
        ["action_type", "scoring_tier"],
        iterations=0,
        min_used=3,
        min_unused=15,
    )
    role_internal_strict = role_internal_stratified_summary(
        rows,
        ["action_type", "scoring_tier", "day", "phase"],
        iterations=0,
        min_used=3,
        min_unused=15,
    )

    feedback_decisions = sum(1 for row in rows if inum(row.get("feedback_rows")) > 0)
    distinct_games = len({row.get("game_id") for row in rows})
    distinct_players = len({row.get("player_id") for row in rows})
    used_delta = fnum(overall_used.get("mean_delta_used_minus_unused"))
    used_ci_crosses_zero = bool(overall_used.get("ci_crosses_zero", True))
    if used_ci_crosses_zero:
        directional_claim = (
            "当前非 fake DB 快照中，strategy-used 与 unused 决策的 Track B 均值差 "
            f"为 {used_delta:.4f}，置信区间跨 0；不能写成稳定增益。"
        )
    elif used_delta > 0:
        directional_claim = (
            "当前非 fake DB 快照中，strategy-used 决策的 Track B 均值高于 unused 决策，且均值差置信区间不跨 0。"
        )
    else:
        directional_claim = (
            "当前非 fake DB 快照中，strategy-used 决策的 Track B 均值低于 unused 决策，"
            "且均值差置信区间不跨 0；需要检查检索触发场景和策略质量。"
        )

    return {
        "generated_at": now_iso(),
        "source": {
            "tables": [
                "published_reviews.report_json.metadata.per_step_scores",
                "agent_decisions",
                "knowledge_usage_feedback",
                "players",
            ],
            "filter": "excludes games whose players.model_name contains fake",
        },
        "row_counts": {
            "decision_rows": len(rows),
            "distinct_games": distinct_games,
            "distinct_players": distinct_players,
            "feedback_decisions": feedback_decisions,
            "used_decisions": len(used_scores),
            "unused_decisions": len(unused_scores),
            "retrieved_decisions": len(retrieved_scores),
            "no_retrieval_decisions": len(no_retrieval_scores),
        },
        "overall": {
            "used_vs_unused": overall_used,
            "retrieved_vs_no_retrieval": overall_retrieved,
            "helpful_vs_unhelpful_among_used": helpful,
        },
        "by_role": by_role,
        "by_action_type": by_action,
        "by_phase": by_phase,
        "stratified": {
            "coarse_role_action_tier": stratified_coarse,
            "strict_role_action_tier_day_phase": stratified_strict,
            "role_internal_action_tier": {
                "keys": ["action_type", "scoring_tier"],
                "min_used_per_stratum": 3,
                "min_unused_per_stratum": 15,
                "roles": role_internal_coarse,
            },
            "role_internal_action_tier_day_phase": {
                "keys": ["action_type", "scoring_tier", "day", "phase"],
                "min_used_per_stratum": 3,
                "min_unused_per_stratum": 15,
                "roles": role_internal_strict,
            },
        },
        "claim_boundary": {
            "observed": directional_claim,
            "not_supported": "这是观测性关联，仍可能受到检索更常出现在较容易或较晚决策中的混杂影响；不能写成随机因果估计。",
            "required_for_causality": "需要 target-seat paired A/B：固定 seed、对手和角色分配，并且只为目标席位开启 Track C。",
        },
    }


def render_report(evidence: dict[str, Any]) -> str:
    counts = evidence["row_counts"]
    overall = evidence["overall"]
    used = overall["used_vs_unused"]
    retrieved = overall["retrieved_vs_no_retrieval"]
    helpful = overall["helpful_vs_unhelpful_among_used"]
    stratified = evidence.get("stratified", {})
    coarse = stratified.get("coarse_role_action_tier", {}) if isinstance(stratified, dict) else {}
    strict = stratified.get("strict_role_action_tier_day_phase", {}) if isinstance(stratified, dict) else {}
    role_internal = (
        stratified.get("role_internal_action_tier_day_phase", {}).get("roles", [])
        if isinstance(stratified, dict)
        else []
    )

    lines = [
        "# 策略使用与逐决策评分关联分析",
        "",
        f"生成时间：{evidence['generated_at']}",
        "",
        "本报告从当前 PostgreSQL 快照中联表分析 Track C 策略使用和 Track B 逐决策评分的关系。它使用 `published_reviews.report_json.metadata.per_step_scores[*].decision_id` 连接 `agent_decisions.id` 和 `knowledge_usage_feedback.decision_id`，并排除 fake/offline game。",
        "",
        "## 1. 数据规模",
        "",
        table(
            ["Metric", "Value"],
            [
                ["decision_rows", counts["decision_rows"]],
                ["distinct_games", counts["distinct_games"]],
                ["distinct_players", counts["distinct_players"]],
                ["feedback_decisions", counts["feedback_decisions"]],
                ["used_decisions", counts["used_decisions"]],
                ["unused_decisions", counts["unused_decisions"]],
                ["retrieved_decisions", counts["retrieved_decisions"]],
                ["no_retrieval_decisions", counts["no_retrieval_decisions"]],
            ],
        ),
        "",
        "## 2. 决策级总体结果",
        "",
        table(
            ["Comparison", "A Count", "B Count", "A Mean", "B Mean", "MeanDelta", "Bootstrap95CI", "CI跨0"],
            [
                [
                    "used vs unused",
                    used["used_count"],
                    used["unused_count"],
                    fmt(used["used_mean"]),
                    fmt(used["unused_mean"]),
                    fmt(used["mean_delta_used_minus_unused"]),
                    f"[{fmt(used['bootstrap_ci_low'])}, {fmt(used['bootstrap_ci_high'])}]",
                    used["ci_crosses_zero"],
                ],
                [
                    "retrieved vs no_retrieval",
                    retrieved["used_count"],
                    retrieved["unused_count"],
                    fmt(retrieved["used_mean"]),
                    fmt(retrieved["unused_mean"]),
                    fmt(retrieved["mean_delta_used_minus_unused"]),
                    f"[{fmt(retrieved['bootstrap_ci_low'])}, {fmt(retrieved['bootstrap_ci_high'])}]",
                    retrieved["ci_crosses_zero"],
                ],
                [
                    "helpful vs unhelpful among used",
                    helpful["used_count"],
                    helpful["unused_count"],
                    fmt(helpful["used_mean"]),
                    fmt(helpful["unused_mean"]),
                    fmt(helpful["mean_delta_used_minus_unused"]),
                    f"[{fmt(helpful['bootstrap_ci_low'])}, {fmt(helpful['bootstrap_ci_high'])}]",
                    helpful["ci_crosses_zero"],
                ],
            ],
        ),
        "",
        "解释：该表是观测性关联。`used vs unused` 可以说明策略使用决策在当前数据中对应更高或更低的 Track B 分数，但不能单独证明策略使用造成分数变化。",
        "",
        "## 3. 混杂控制后的分层结果",
        "",
        table(
            [
                "Stratification",
                "Strata",
                "UsedRetained",
                "UnusedRetained",
                "WeightedDelta",
                "MeanDelta",
                "MedianDelta",
                "+/-/0 Strata",
            ],
            [
                [
                    "role + action + tier",
                    coarse.get("strata_count", 0),
                    f"{coarse.get('used_retained', 0)} ({pct(coarse.get('used_retention_rate', 0))})",
                    coarse.get("unused_retained", 0),
                    fmt(coarse.get("weighted_mean_delta_used_minus_unused")),
                    fmt(coarse.get("mean_of_stratum_deltas")),
                    fmt(coarse.get("median_of_stratum_deltas")),
                    f"{coarse.get('positive_strata', 0)}/{coarse.get('negative_strata', 0)}/{coarse.get('tied_strata', 0)}",
                ],
                [
                    "role + action + tier + day + phase",
                    strict.get("strata_count", 0),
                    f"{strict.get('used_retained', 0)} ({pct(strict.get('used_retention_rate', 0))})",
                    strict.get("unused_retained", 0),
                    fmt(strict.get("weighted_mean_delta_used_minus_unused")),
                    fmt(strict.get("mean_of_stratum_deltas")),
                    fmt(strict.get("median_of_stratum_deltas")),
                    f"{strict.get('positive_strata', 0)}/{strict.get('negative_strata', 0)}/{strict.get('tied_strata', 0)}",
                ],
            ],
        ),
        "",
        "解释：分层统计只在同角色、同动作、同评分层级等可比局面内比较 used 与 unused，再按 used 决策数加权。它不能消除所有混杂，但比总体均值更接近“相似局面下策略使用是否对应更高评分”。",
        "",
        "## 4. 按角色分层",
        "",
        table(
            ["Role", "Used", "Unused", "UsedMean", "UnusedMean", "Delta", "95CI", "CI跨0"],
            [
                [
                    row.get("role"),
                    row["used_count"],
                    row["unused_count"],
                    fmt(row["used_mean"]),
                    fmt(row["unused_mean"]),
                    fmt(row["mean_delta_used_minus_unused"]),
                    f"[{fmt(row['bootstrap_ci_low'])}, {fmt(row['bootstrap_ci_high'])}]",
                    row["ci_crosses_zero"],
                ]
                for row in evidence["by_role"][:12]
            ],
        ),
        "",
        "## 5. 角色内控制后的分层结果",
        "",
        "该表在每个角色内部再按 action_type、scoring_tier、day、phase 建立可比 strata，然后比较 strategy-used 与 unused 决策。它比单纯按角色均值更能回答“每个角色是否都有增益趋势”。",
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
                for row in role_internal
            ],
        )
        if role_internal
        else "角色内分层结果尚未生成。",
        "",
        "解释：如果某个角色的 UsedRetained 很低，说明该角色可比 strata 还不足，需要补更多真实局或降低分层粒度。WeightedDelta 仍是观测性指标，不能替代 target-seat paired A/B。",
        "",
        "## 6. 按动作类型分层",
        "",
        table(
            ["Action", "Used", "Unused", "UsedMean", "UnusedMean", "Delta", "95CI", "CI跨0"],
            [
                [
                    row.get("action_type"),
                    row["used_count"],
                    row["unused_count"],
                    fmt(row["used_mean"]),
                    fmt(row["unused_mean"]),
                    fmt(row["mean_delta_used_minus_unused"]),
                    f"[{fmt(row['bootstrap_ci_low'])}, {fmt(row['bootstrap_ci_high'])}]",
                    row["ci_crosses_zero"],
                ]
                for row in evidence["by_action_type"][:12]
            ],
        ),
        "",
        "## 7. 结论边界",
        "",
        table(
            ["结论类型", "内容"],
            [
                ["当前观测", evidence["claim_boundary"]["observed"]],
                ["不能写", evidence["claim_boundary"]["not_supported"]],
                ["因果证明需要", evidence["claim_boundary"]["required_for_causality"]],
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--limit", type=int, default=0, help="Optional SQL limit for debugging")
    parser.add_argument("--statement-timeout-ms", type=int, default=90_000)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--facts", default=str(DEFAULT_FACTS))
    args = parser.parse_args()

    evidence = build_evidence(
        iterations=max(args.iterations, 0),
        limit=max(args.limit, 0),
        statement_timeout_ms=max(args.statement_timeout_ms, 0),
    )
    report_path = Path(args.report).resolve()
    facts_path = Path(args.facts).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(evidence), encoding="utf-8")
    facts_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {display_path(report_path)}")
    print(f"Wrote {display_path(facts_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
