#!/usr/bin/env python3
"""Plan statistical power for target-seat Track C A/B experiments.

This script does not run games or call LLMs. It estimates how many paired seeds
are needed before `target_seat_trackc_ab_experiment.py` can support a causal
Track C claim with useful power.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "outputs" / "target_seat_power_plan"
DEFAULT_REPORT = OUTPUT_DIR / "PROJECT_TARGET_SEAT_AB_POWER_PLAN.md"
DEFAULT_FACTS = OUTPUT_DIR / "PROJECT_TARGET_SEAT_AB_POWER_PLAN.json"

TARGET_RUNNER = ROOT / "scripts" / "target_seat_trackc_ab_experiment.py"
SCORE_EFFECTS = [3.0, 5.0, 8.0, 10.0]
SCORE_SD_SCENARIOS = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
ROLE_TASK_EFFECTS = [0.03, 0.05, 0.08, 0.10]
ROLE_TASK_SD_SCENARIOS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
WIN_EFFECTS = [0.03, 0.05, 0.08, 0.10]
WIN_DISCORDANCE_SCENARIOS = [0.20, 0.30, 0.40, 0.50]
ASSUMED_PAIR_CORRELATIONS = [0.25, 0.50, 0.75]

Z_BY_POWER = {
    0.80: 0.8416212336,
    0.90: 1.2815515655,
}
Z_ALPHA_TWO_SIDED_005 = 1.9599639845


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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


def ceil_sample(value: float) -> int:
    if not math.isfinite(value) or value <= 0:
        return 0
    return int(math.ceil(value))


def paired_continuous_n(effect: float, paired_delta_sd: float, *, power: float = 0.80) -> int:
    if effect <= 0 or paired_delta_sd <= 0:
        return 0
    z_power = Z_BY_POWER[power]
    return ceil_sample(((Z_ALPHA_TWO_SIDED_005 + z_power) * paired_delta_sd / effect) ** 2)


def paired_binary_n(effect: float, discordance_rate: float, *, power: float = 0.80) -> int:
    """Approximate paired binary sample size for signed win deltas.

    Each paired seed contributes -1, 0, or +1. If the expected mean paired
    difference is `effect` and the total discordance rate is q=P(+1)+P(-1), the
    variance of the signed delta is approximately q-effect^2.
    """
    if effect <= 0 or discordance_rate <= 0 or discordance_rate <= effect * effect:
        return 0
    z_power = Z_BY_POWER[power]
    variance = discordance_rate - effect * effect
    return ceil_sample(((Z_ALPHA_TWO_SIDED_005 + z_power) ** 2) * variance / (effect * effect))


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def collect_observed_role_stats() -> dict[str, Any]:
    """Read non-fake score variance from current PostgreSQL if available."""
    try:
        from sqlalchemy import text

        from backend.db import SessionLocal

        db = SessionLocal()
        try:
            rows = [
                dict(row)
                for row in db.execute(
                    text(
                        """
                        WITH scores AS (
                          SELECT
                            COALESCE(ps.score_obj->>'role', p.role) AS role,
                            (ps.score_obj->>'role_task_score')::float AS role_task_score,
                            (ps.score_obj->>'process_score')::float AS process_score,
                            (ps.score_obj->>'adjusted_final_score')::float AS adjusted_final_score,
                            (ps.score_obj->>'final_score')::float AS final_score
                          FROM published_reviews pr
                          CROSS JOIN LATERAL jsonb_array_elements(
                            pr.report_json::jsonb->'metadata'->'player_scores'
                          ) AS ps(score_obj)
                          LEFT JOIN players p ON p.id = ps.score_obj->>'player_id'
                          WHERE pr.report_json::jsonb->'metadata' ? 'player_scores'
                            AND NOT EXISTS (
                              SELECT 1
                              FROM players p_fake
                              WHERE p_fake.game_id = pr.game_id
                                AND lower(COALESCE(p_fake.model_name, '')) LIKE '%fake%'
                            )
                        )
                        SELECT
                          role,
                          COUNT(*) AS n,
                          COUNT(adjusted_final_score) AS n_adjusted,
                          AVG(adjusted_final_score) AS adjusted_mean,
                          STDDEV_SAMP(adjusted_final_score) AS adjusted_sd,
                          COUNT(role_task_score) AS n_role_task,
                          AVG(role_task_score) AS role_task_mean,
                          STDDEV_SAMP(role_task_score) AS role_task_sd,
                          COUNT(process_score) AS n_process,
                          AVG(process_score) AS process_mean,
                          STDDEV_SAMP(process_score) AS process_sd,
                          AVG(final_score) AS final_mean,
                          STDDEV_SAMP(final_score) AS final_sd
                        FROM scores
                        GROUP BY role
                        ORDER BY n DESC
                        """
                    )
                ).mappings()
            ]
            totals = (
                db.execute(
                    text(
                        """
                    WITH scores AS (
                      SELECT
                        (ps.score_obj->>'role_task_score')::float AS role_task_score,
                        (ps.score_obj->>'process_score')::float AS process_score,
                        (ps.score_obj->>'adjusted_final_score')::float AS adjusted_final_score,
                        (ps.score_obj->>'final_score')::float AS final_score
                      FROM published_reviews pr
                      CROSS JOIN LATERAL jsonb_array_elements(
                        pr.report_json::jsonb->'metadata'->'player_scores'
                      ) AS ps(score_obj)
                      WHERE pr.report_json::jsonb->'metadata' ? 'player_scores'
                        AND NOT EXISTS (
                          SELECT 1
                          FROM players p_fake
                          WHERE p_fake.game_id = pr.game_id
                            AND lower(COALESCE(p_fake.model_name, '')) LIKE '%fake%'
                        )
                    )
                    SELECT
                      COUNT(*) AS n,
                      AVG(adjusted_final_score) AS adjusted_mean,
                      STDDEV_SAMP(adjusted_final_score) AS adjusted_sd,
                      AVG(role_task_score) AS role_task_mean,
                      STDDEV_SAMP(role_task_score) AS role_task_sd,
                      AVG(process_score) AS process_mean,
                      STDDEV_SAMP(process_score) AS process_sd,
                      AVG(final_score) AS final_mean,
                      STDDEV_SAMP(final_score) AS final_sd
                    FROM scores
                    """
                    )
                )
                .mappings()
                .first()
            )
            return {
                "status": "ok",
                "queried_at": now_iso(),
                "source": "PostgreSQL published_reviews.report_json.metadata.player_scores, excluding games whose players.model_name contains fake",
                "overall": dict(totals or {}),
                "by_role": rows,
            }
        finally:
            db.close()
    except Exception as exc:
        return {
            "status": "unavailable",
            "queried_at": now_iso(),
            "source": "PostgreSQL published_reviews.report_json.metadata.player_scores",
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "overall": {},
            "by_role": [],
        }


def continuous_scenario_table(
    effects: list[float],
    sd_scenarios: list[float],
    *,
    power: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sd in sd_scenarios:
        row: dict[str, Any] = {"paired_delta_sd": sd}
        for effect in effects:
            row[f"delta_{effect:g}"] = paired_continuous_n(effect, sd, power=power)
        rows.append(row)
    return rows


def role_power_rows(role_stats: list[dict[str, Any]], *, metric: str, effects: list[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sd_key = f"{metric}_sd"
    for role in role_stats:
        observed_sd = fnum(role.get(sd_key))
        if observed_sd <= 0:
            continue
        for rho in ASSUMED_PAIR_CORRELATIONS:
            paired_sd = math.sqrt(max(0.0, 2 * (1 - rho))) * observed_sd
            row: dict[str, Any] = {
                "role": role.get("role", ""),
                "n_observed": inum(role.get("n")),
                "observed_individual_sd": round(observed_sd, 4),
                "assumed_pair_correlation": rho,
                "estimated_paired_delta_sd": round(paired_sd, 4),
            }
            for effect in effects:
                row[f"delta_{effect:g}"] = paired_continuous_n(effect, paired_sd, power=0.80)
            rows.append(row)
    return rows


def win_power_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for discordance in WIN_DISCORDANCE_SCENARIOS:
        row: dict[str, Any] = {"discordance_rate": discordance}
        for effect in WIN_EFFECTS:
            row[f"delta_{effect:g}"] = paired_binary_n(effect, discordance, power=0.80)
        rows.append(row)
    return rows


def build_evidence() -> dict[str, Any]:
    observed = collect_observed_role_stats()
    adjusted_scenarios_80 = continuous_scenario_table(SCORE_EFFECTS, SCORE_SD_SCENARIOS, power=0.80)
    adjusted_scenarios_90 = continuous_scenario_table(SCORE_EFFECTS, SCORE_SD_SCENARIOS, power=0.90)
    role_task_scenarios_80 = continuous_scenario_table(ROLE_TASK_EFFECTS, ROLE_TASK_SD_SCENARIOS, power=0.80)
    by_role = observed.get("by_role", []) if observed.get("status") == "ok" else []
    adjusted_role_power = role_power_rows(by_role, metric="adjusted", effects=SCORE_EFFECTS)
    role_task_role_power = role_power_rows(by_role, metric="role_task", effects=ROLE_TASK_EFFECTS)
    win_rows = win_power_rows()

    recommendation = {
        "pilot_paired_seeds": 20,
        "minimum_confirmatory_paired_seeds": 80,
        "preferred_confirmatory_paired_seeds": 120,
        "high_confidence_paired_seeds": 200,
        "primary_metrics": ["target_adjusted_score_delta", "target_role_task_delta"],
        "secondary_metrics": ["target_win_rate_delta", "target_process_score_delta"],
        "rationale": (
            "20 个 paired seeds 适合验证 pipeline 和健康门禁，不适合直接作为最终因果证明。"
            "除非真实 paired 方差很低，否则评分和 role-task 指标通常需要 80+ paired seeds；"
            "胜率差所需样本显著更大，应作为辅助指标。"
        ),
    }

    return {
        "generated_at": now_iso(),
        "report_type": "target_seat_trackc_ab_power_plan",
        "sources": {
            "target_seat_runner": str(TARGET_RUNNER.relative_to(ROOT)),
            "observed_score_stats": observed.get("source", ""),
        },
        "acceptance_gates_from_runner_defaults": {
            "min_paired_seeds": 20,
            "min_adjusted_score_delta": 3.0,
            "min_role_task_delta": 0.03,
            "min_win_rate_delta": 0.03,
            "require_positive_ci": True,
            "strict_health": "candidate_fallback_count == 0 and candidate_invalid_count == 0",
        },
        "statistical_assumptions": {
            "alpha": 0.05,
            "test": "two-sided mean paired delta approximation",
            "power_levels": [0.80, 0.90],
            "paired_continuous_formula": "n = ((z_alpha/2 + z_power) * paired_delta_sd / effect)^2",
            "paired_binary_formula": "n = ((z_alpha/2 + z_power)^2 * (discordance_rate - effect^2)) / effect^2",
            "boundary": "This is a planning estimate, not an experimental result.",
        },
        "observed_score_stats": observed,
        "scenario_tables": {
            "adjusted_score_power80": adjusted_scenarios_80,
            "adjusted_score_power90": adjusted_scenarios_90,
            "role_task_power80": role_task_scenarios_80,
            "target_win_power80": win_rows,
            "adjusted_score_by_role_power80": adjusted_role_power,
            "role_task_by_role_power80": role_task_role_power,
        },
        "recommendation": recommendation,
        "claim_boundary": (
            "Use this plan to choose real target-seat A/B sample size. "
            "Do not cite the scenario tables as evidence that Track C improves performance."
        ),
    }


def rows_for_table(rows: list[dict[str, Any]], keys: list[str], *, limit: int | None = None) -> list[list[Any]]:
    selected = rows[:limit] if limit else rows
    return [[row.get(key, "") for key in keys] for row in selected]


def render_report(evidence: dict[str, Any]) -> str:
    observed = evidence["observed_score_stats"]
    scenarios = evidence["scenario_tables"]
    recommendation = evidence["recommendation"]
    observed_rows = observed.get("by_role", []) if observed.get("status") == "ok" else []

    lines = [
        "# Target-seat Track C A/B 功效计划",
        "",
        f"生成时间：{evidence['generated_at']}",
        "",
        "本文件用于规划后续真实 target-seat Track C 因果 A/B 实验。它只估计样本量，不运行游戏、不调用 LLM，也不构成 Track C 已经产生因果增益的结论。",
        "",
        "## 1. 当前 Runner 验收门槛",
        "",
        table(
            ["Gate", "Default"],
            [
                ["min_paired_seeds", evidence["acceptance_gates_from_runner_defaults"]["min_paired_seeds"]],
                [
                    "min_adjusted_score_delta",
                    evidence["acceptance_gates_from_runner_defaults"]["min_adjusted_score_delta"],
                ],
                ["min_role_task_delta", evidence["acceptance_gates_from_runner_defaults"]["min_role_task_delta"]],
                ["min_win_rate_delta", evidence["acceptance_gates_from_runner_defaults"]["min_win_rate_delta"]],
                ["require_positive_ci", evidence["acceptance_gates_from_runner_defaults"]["require_positive_ci"]],
                ["strict_health", evidence["acceptance_gates_from_runner_defaults"]["strict_health"]],
            ],
        ),
        "",
        f"代码依据：`{evidence['sources']['target_seat_runner']}`。这些门槛表示 runner 目前可以接受 20 个 paired seeds 的结果，但 20 局更适合作为 pipeline pilot，而不是最终因果证明。",
        "",
        "## 2. 现有评分方差快照",
        "",
    ]

    if observed.get("status") == "ok":
        lines += [
            f"来源：{observed.get('source')}。",
            "",
            table(
                [
                    "Role",
                    "N",
                    "AdjustedMean",
                    "AdjustedSD",
                    "RoleTaskMean",
                    "RoleTaskSD",
                    "ProcessMean",
                    "ProcessSD",
                ],
                [
                    [
                        row.get("role"),
                        row.get("n"),
                        fmt(row.get("adjusted_mean"), 2),
                        fmt(row.get("adjusted_sd"), 2),
                        fmt(row.get("role_task_mean"), 4),
                        fmt(row.get("role_task_sd"), 4),
                        fmt(row.get("process_mean"), 2),
                        fmt(row.get("process_sd"), 2),
                    ]
                    for row in observed_rows
                ],
            ),
            "",
            "说明：该表是非 fake 历史评分分布。它提供目标角色评分波动的上界参考，但不是 paired A/B 的真实差分方差；真实 paired delta 方差必须由后续 A/B 输出补齐。",
        ]
    else:
        lines += [
            f"PostgreSQL 快照不可用：{observed.get('error')}",
            "",
        ]

    lines += [
        "",
        "## 3. Adjusted Score 样本量情景",
        "",
        "以下为 80% power 的 paired mean delta 情景表。数值表示需要的 paired seeds 数；这是功效计划，不是实验结果。",
        "",
        table(
            ["PairedDeltaSD", "Delta=3", "Delta=5", "Delta=8", "Delta=10"],
            rows_for_table(
                scenarios["adjusted_score_power80"],
                ["paired_delta_sd", "delta_3", "delta_5", "delta_8", "delta_10"],
            ),
        ),
        "",
        "90% power 对应样本量如下：",
        "",
        table(
            ["PairedDeltaSD", "Delta=3", "Delta=5", "Delta=8", "Delta=10"],
            rows_for_table(
                scenarios["adjusted_score_power90"],
                ["paired_delta_sd", "delta_3", "delta_5", "delta_8", "delta_10"],
            ),
        ),
        "",
        "## 4. Role-task Score 样本量情景",
        "",
        "Role-task 是 0-1 量纲，更适合作为目标席位行为质量的主指标之一。以下为 80% power 情景表。",
        "",
        table(
            ["PairedDeltaSD", "Delta=0.03", "Delta=0.05", "Delta=0.08", "Delta=0.10"],
            rows_for_table(
                scenarios["role_task_power80"],
                ["paired_delta_sd", "delta_0.03", "delta_0.05", "delta_0.08", "delta_0.1"],
            ),
        ),
        "",
        "## 5. Target Win Rate 样本量情景",
        "",
        "胜率是离散且高噪声指标。以下以 paired binary signed delta 近似估计；DiscordanceRate 表示同一 seed 下 baseline/candidate 胜负不一致的比例。",
        "",
        table(
            ["DiscordanceRate", "Delta=0.03", "Delta=0.05", "Delta=0.08", "Delta=0.10"],
            rows_for_table(
                scenarios["target_win_power80"],
                ["discordance_rate", "delta_0.03", "delta_0.05", "delta_0.08", "delta_0.1"],
            ),
        ),
        "",
        "结论边界：如果只希望证明 3%-5% 的胜率差，所需 paired seeds 远高于当前 runner 默认 20。因此胜率应作为参考指标，主结论应优先基于 adjusted score、role-task score、fallback/invalid 健康门禁和 bootstrap CI。",
        "",
        "## 6. 推荐实验规模",
        "",
        table(
            ["级别", "PairedSeeds", "用途"],
            [
                [
                    "pilot",
                    recommendation["pilot_paired_seeds"],
                    "验证 provider、runner、per-agent feature flags、fallback/invalid 和输出格式",
                ],
                [
                    "minimum_confirmatory",
                    recommendation["minimum_confirmatory_paired_seeds"],
                    "检测中等 adjusted score / role-task 改进，仍需报告 CI 和角色分层结果",
                ],
                [
                    "preferred_confirmatory",
                    recommendation["preferred_confirmatory_paired_seeds"],
                    "推荐正式结项补实验规模，兼顾成本和统计稳定性",
                ],
                [
                    "high_confidence",
                    recommendation["high_confidence_paired_seeds"],
                    "用于更小效应或跨角色轮换的高置信验证",
                ],
            ],
        ),
        "",
        recommendation["rationale"],
        "",
        "## 7. 推荐命令模板",
        "",
        "provider preflight 通过后，先跑 pilot：",
        "",
        "```bash",
        "python scripts/target_seat_trackc_ab_experiment.py \\",
        "  --target-role Seer \\",
        "  --seeds 9301 9302 9303 9304 9305 9306 9307 9308 9309 9310 9311 9312 9313 9314 9315 9316 9317 9318 9319 9320 \\",
        "  --baseline-framework basic_react \\",
        "  --candidate-framework rag_react \\",
        "  --player-count 7 \\",
        "  --max-days 20 \\",
        "  --bootstrap-iterations 2000 \\",
        "  --min-paired-seeds 20 \\",
        "  --output-dir outputs/target_seat_trackc_ab_seer_pilot",
        "```",
        "",
        "正式补实验建议至少 80 个 paired seeds，并保持同 seed、同角色分配、同 baseline 对手，只升级一个目标席位。若目标是跨角色结论，应按 Seer/Werewolf/Witch/Guard/Hunter/Villager 分别运行，再做角色分层汇总。",
        "",
        "## 8. 不能据此书写的结论",
        "",
        "- 不能把本文件中的样本量情景写成 Track C 已经提升胜率或评分。",
        "- 不能用 20 paired seeds 的 pilot 结果直接替代最终因果实验，除非实际 paired delta 很大且 bootstrap CI 明确为正。",
        "- 不能只看 target win rate；狼人杀单局胜负噪声高，必须同时报告目标席位评分、role-task、fallback/invalid 和 CI。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan target-seat Track C A/B power")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--facts", default=str(DEFAULT_FACTS))
    args = parser.parse_args()

    evidence = build_evidence()
    report_path = Path(args.report)
    facts_path = Path(args.facts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(evidence), encoding="utf-8")
    facts_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Wrote {facts_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
