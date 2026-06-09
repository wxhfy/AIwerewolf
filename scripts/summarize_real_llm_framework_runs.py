#!/usr/bin/env python3
"""Summarize real-LLM framework experiment outputs for report evidence.

The script reads outputs from `track_bc_leaderboard_experiment.py` and related
framework-gap runs. It does not call an LLM or mutate the database.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GLOBS = [
    "outputs/final_showcase_report/real_experiment_real_llm*",
    "outputs/final_showcase_report/real_experiment_leaderboard_*",
    "outputs/final_showcase_report/real_experiment_model_leaderboard_*",
    "docs/experiments/framework_gap_reflexion*",
    "docs/experiments/track_c_runtime_fix/*",
    "docs/experiments/formal_v4flash_framework_analysis",
]

DEFAULT_REPORT = ROOT / "docs" / "PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.md"
DEFAULT_FACTS = ROOT / "docs" / "PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


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
    return f"{fnum(value):.{digits}f}"


def pct(value: Any) -> str:
    return f"{fnum(value) * 100:.2f}%"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def sanitize_model_pool(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    sanitized: list[str] = []
    for value in values:
        text = str(value)
        text = re.sub(r"ep-\d{14}-[A-Za-z0-9_-]+", "ep-<redacted>", text)
        sanitized.append(text)
    return sanitized


def discover_run_dirs(patterns: list[str]) -> list[Path]:
    dirs: set[Path] = set()
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            if path.is_dir() and ((path / "summary.json").exists() or (path / "partial_summary.json").exists()):
                dirs.add(path)
    return sorted(dirs)


def select_summary_path(run_dir: Path) -> tuple[Path | None, bool]:
    summary = run_dir / "summary.json"
    if summary.exists():
        return summary, False
    partial = run_dir / "partial_summary.json"
    if partial.exists():
        return partial, True
    return None, False


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def group_metrics(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("group_key") or row.get("framework") or "unknown")].append(row)

    results: list[dict[str, Any]] = []
    for group_key, group_rows in sorted(buckets.items()):
        decision_count = sum(inum(row.get("decision_count")) for row in group_rows)
        fallback_count = sum(inum(row.get("fallback_count")) for row in group_rows)
        invalid_count = sum(inum(row.get("invalid_count")) for row in group_rows)
        results.append(
            {
                "group_key": group_key,
                "framework": group_rows[0].get("framework", ""),
                "rows": len(group_rows),
                "decision_count": decision_count,
                "fallback_count": fallback_count,
                "invalid_count": invalid_count,
                "avg_knowledge_hit_rate": mean([fnum(row.get("knowledge_hit_rate")) for row in group_rows]),
                "avg_adjusted_final_score": mean([fnum(row.get("avg_adjusted_final_score")) for row in group_rows]),
                "avg_win_rate": mean([fnum(row.get("win_rate")) for row in group_rows]),
            }
        )
    return results


def game_run_decision_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "decision_count": sum(inum(row.get("decision_count")) for row in rows),
        "fallback_count": sum(inum(row.get("fallback_count")) for row in rows),
        "invalid_count": sum(inum(row.get("invalid_count")) for row in rows),
    }


def is_formal_analysis_summary(summary: dict[str, Any]) -> bool:
    return isinstance(summary.get("tier_summaries"), dict) and isinstance(summary.get("row_counts"), dict)


def formal_analysis_group_metrics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    tier_summaries = summary.get("tier_summaries", {})
    if not isinstance(tier_summaries, dict):
        return []

    rubric_by_tier = {
        str(row.get("tier") or ""): row for row in summary.get("rubric_leaderboard", []) or [] if isinstance(row, dict)
    }
    results: list[dict[str, Any]] = []
    for tier, payload in sorted(tier_summaries.items()):
        if not isinstance(payload, dict):
            continue
        rubric_row = rubric_by_tier.get(str(tier), {})
        completed = inum(payload.get("completed_games"))
        results.append(
            {
                "group_key": f"tier:{tier}",
                "framework": str(payload.get("display_name") or tier),
                "rows": completed,
                "decision_count": inum(payload.get("llm_decisions")),
                "fallback_count": inum(payload.get("fallback_count")),
                "invalid_count": inum(payload.get("invalid_count")),
                "avg_knowledge_hit_rate": fnum(payload.get("knowledge_hit_rate")),
                "avg_adjusted_final_score": fnum(rubric_row.get("rubric_total_score")),
                "rubric_total_score": fnum(rubric_row.get("rubric_total_score")),
                "avg_win_rate": fnum(payload.get("village_win_rate")),
                "attempted_games": inum(payload.get("attempted_games")),
                "failed_games": inum(payload.get("failed_games")),
                "external_failure_rate": fnum(payload.get("external_failure_rate")),
                "macro_role_win_rate": fnum(payload.get("macro_role_win_rate")),
            }
        )
    return results


def summarize_formal_analysis(run_dir: Path, summary_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    group_summary = formal_analysis_group_metrics(summary)
    total_decisions = sum(row["decision_count"] for row in group_summary)
    total_fallback = sum(row["fallback_count"] for row in group_summary)
    total_invalid = sum(row["invalid_count"] for row in group_summary)
    completed = sum(row["rows"] for row in group_summary)
    failed = sum(row.get("failed_games", 0) for row in group_summary)
    attempted = sum(row.get("attempted_games", 0) for row in group_summary)
    row_counts = summary.get("row_counts", {}) if isinstance(summary.get("row_counts"), dict) else {}

    return {
        "run_dir": rel(run_dir),
        "summary_file": rel(summary_path),
        "status": "complete",
        "source_schema": "formal_v4flash_analysis",
        "started_at": None,
        "generated_at": summary.get("generated_at"),
        "axis": "framework",
        "games_per_framework": 0,
        "seeds": [],
        "player_count": 7,
        "max_days": None,
        "game_timeout_s": 0,
        "model_pool": sanitize_model_pool(["dsv4flash:deepseek-v4-flash"]),
        "frameworks": [row["framework"] for row in group_summary],
        "completed_raw_games": completed,
        "failed_games": failed,
        "attempted_games": attempted or inum(row_counts.get("formal_v4flash")),
        "failure_types": {},
        "group_summary": group_summary,
        "total_decisions": total_decisions,
        "total_fallback": total_fallback,
        "total_invalid": total_invalid,
        "mean_knowledge_hit_rate": mean([row["avg_knowledge_hit_rate"] for row in group_summary]),
        "leaderboard_summary": {
            "entries": len(group_summary),
            "rubric_entries": len(summary.get("rubric_leaderboard", []) or []),
            "formal_v4flash_rows": inum(row_counts.get("formal_v4flash")),
            "excluded_rows": inum(row_counts.get("excluded")),
        },
        "scope": "formal_analysis_with_failures",
        "claim_level": "formal_framework_quantified",
        "boundary": (
            "正式 v4flash 二次分析可证明框架版本、决策健康和工程指标可量化；"
            "但各 tier 失败率不均，不能写成 Track C 胜率因果提升。"
        ),
    }


def classify_run(summary: dict[str, Any], group_rows: list[dict[str, str]], summary_is_partial: bool) -> dict[str, str]:
    completed = inum(summary.get("completed_raw_games"))
    failed = inum(summary.get("failed_games"))
    attempted = inum(summary.get("attempted_games"))
    games_per_framework = inum(summary.get("games_per_framework"))
    max_days = inum(summary.get("max_days"))
    framework_count = len(summary.get("frameworks", []) or [])
    expected_games = games_per_framework * max(framework_count, 1)

    if summary_is_partial and attempted == 0 and not group_rows:
        return {
            "scope": "running_no_completed_games",
            "claim_level": "no_evidence_yet",
            "boundary": "实验已创建输出目录，但尚无完成或失败局；不能用于结论。",
        }
    if max_days <= 1:
        return {
            "scope": "smoke_only",
            "claim_level": "pipeline_health_only",
            "boundary": "max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。",
        }
    if failed > 0:
        return {
            "scope": "incomplete_with_failures",
            "claim_level": "operational_diagnostics",
            "boundary": "存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。",
        }
    if completed >= expected_games and games_per_framework >= 5 and max_days > 1:
        return {
            "scope": "formal_candidate",
            "claim_level": "framework_trend",
            "boundary": "可作为真实 LLM 框架趋势证据；若要证明 Track C 因果增益仍需 target-seat paired A/B。",
        }
    if completed > 0:
        return {
            "scope": "low_sample_or_partial",
            "claim_level": "trend_only",
            "boundary": "样本量或完成度不足，只能作为趋势/链路证据。",
        }
    return {
        "scope": "no_completed_games",
        "claim_level": "no_evidence_yet",
        "boundary": "尚无完成局，不能用于方法有效性结论。",
    }


def summarize_run(run_dir: Path) -> dict[str, Any]:
    summary_path, summary_is_partial = select_summary_path(run_dir)
    if summary_path is None:
        raise FileNotFoundError(f"No summary.json or partial_summary.json in {run_dir}")

    summary = read_json(summary_path)
    if not summary_is_partial and is_formal_analysis_summary(summary):
        return summarize_formal_analysis(run_dir, summary_path, summary)

    group_rows = read_csv(run_dir / "group_results.csv")
    game_runs = read_jsonl(run_dir / "game_runs.jsonl")
    failures = read_jsonl(run_dir / "failures.jsonl")
    group_summary = group_metrics(group_rows)
    classification = classify_run(summary, group_rows, summary_is_partial)
    failure_types = Counter(str(row.get("error_type") or "unknown") for row in failures)
    game_decisions = game_run_decision_summary(game_runs)
    total_decisions = (
        game_decisions["decision_count"] if game_runs else sum(row["decision_count"] for row in group_summary)
    )
    total_fallback = (
        game_decisions["fallback_count"] if game_runs else sum(row["fallback_count"] for row in group_summary)
    )
    total_invalid = game_decisions["invalid_count"] if game_runs else sum(row["invalid_count"] for row in group_summary)

    return {
        "run_dir": rel(run_dir),
        "summary_file": rel(summary_path),
        "status": "partial" if summary_is_partial else "complete",
        "started_at": summary.get("started_at"),
        "generated_at": summary.get("generated_at") or summary.get("updated_at"),
        "axis": summary.get("axis"),
        "games_per_framework": inum(summary.get("games_per_framework")),
        "seeds": summary.get("seeds", []),
        "player_count": inum(summary.get("player_count")),
        "max_days": inum(summary.get("max_days")),
        "game_timeout_s": inum(summary.get("game_timeout_s")),
        "model_pool": sanitize_model_pool(summary.get("model_pool", [])),
        "frameworks": [item.get("name") for item in summary.get("frameworks", []) if isinstance(item, dict)],
        "completed_raw_games": inum(summary.get("completed_raw_games")),
        "failed_games": inum(summary.get("failed_games")),
        "attempted_games": inum(summary.get("attempted_games")),
        "failure_types": dict(sorted(failure_types.items())),
        "group_summary": group_summary,
        "total_decisions": total_decisions,
        "total_fallback": total_fallback,
        "total_invalid": total_invalid,
        "mean_knowledge_hit_rate": mean([row["avg_knowledge_hit_rate"] for row in group_summary]),
        "leaderboard_summary": summary.get("leaderboard_summary", {}),
        **classification,
    }


def build_facts(run_dirs: list[Path], *, generated_at: str | None = None) -> dict[str, Any]:
    runs = [summarize_run(path) for path in run_dirs]
    return {
        "generated_at": generated_at or now_iso(),
        "report_type": "real_llm_framework_evidence_summary",
        "sources": [run["run_dir"] for run in runs],
        "aggregate": {
            "run_count": len(runs),
            "completed_raw_games": sum(inum(run.get("completed_raw_games")) for run in runs),
            "failed_games": sum(inum(run.get("failed_games")) for run in runs),
            "total_decisions": sum(inum(run.get("total_decisions")) for run in runs),
            "total_fallback": sum(inum(run.get("total_fallback")) for run in runs),
            "total_invalid": sum(inum(run.get("total_invalid")) for run in runs),
            "formal_candidate_runs": sum(1 for run in runs if run.get("scope") == "formal_candidate"),
            "smoke_runs": sum(1 for run in runs if run.get("scope") == "smoke_only"),
            "running_no_completed_games": sum(1 for run in runs if run.get("scope") == "running_no_completed_games"),
        },
        "runs": runs,
        "claim_boundaries": [
            "fallback/invalid 为 0 可证明决策健康，不等同于胜率因果提升。",
            "max_days<=1 或 games_per_framework<5 的结果只能作为 smoke/trend。",
            "全席位框架对比可以证明框架可被量化区分；Track C 因果增益仍需 target-seat paired A/B。",
        ],
    }


def existing_generated_at(path: Path) -> str | None:
    payload = read_json(path)
    value = payload.get("generated_at")
    return str(value) if value else None


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(facts: dict[str, Any]) -> str:
    runs = list(facts.get("runs", []))
    lines = [
        "# 真实 LLM 框架实验汇总",
        "",
        f"生成时间：{facts.get('generated_at')}",
        "",
        "本文件汇总 `track_bc_leaderboard_experiment.py` 及相关真实 LLM 框架实验产物。它只读取已有输出，不调用 LLM，不写数据库。报告重点是区分“可引用证据”和“暂不能写入结论的实验”。",
        "",
        "原始实验输出位于 `.gitignore` 覆盖的本地 `docs/experiments/` 与 `outputs/` 目录；本文件和配套 JSON 是可提交的聚合事实快照。",
        "",
        "## 1. 总览",
        "",
        markdown_table(
            ["指标", "值"],
            [
                ["run_count", facts["aggregate"]["run_count"]],
                ["completed_raw_games", facts["aggregate"]["completed_raw_games"]],
                ["failed_games", facts["aggregate"]["failed_games"]],
                ["total_decisions", facts["aggregate"]["total_decisions"]],
                ["total_fallback", facts["aggregate"]["total_fallback"]],
                ["total_invalid", facts["aggregate"]["total_invalid"]],
                ["formal_candidate_runs", facts["aggregate"]["formal_candidate_runs"]],
                ["smoke_runs", facts["aggregate"]["smoke_runs"]],
                ["running_no_completed_games", facts["aggregate"]["running_no_completed_games"]],
            ],
        ),
        "",
        "## 2. Run 级证据边界",
        "",
        markdown_table(
            [
                "Run",
                "Status",
                "Scope",
                "Games/Framework",
                "MaxDays",
                "Completed",
                "Failed",
                "Fallback",
                "Invalid",
                "MeanKnowledgeHit",
                "ClaimLevel",
            ],
            [
                [
                    run["run_dir"],
                    run["status"],
                    run["scope"],
                    run["games_per_framework"],
                    run["max_days"],
                    run["completed_raw_games"],
                    run["failed_games"],
                    run["total_fallback"],
                    run["total_invalid"],
                    fmt(run["mean_knowledge_hit_rate"]),
                    run["claim_level"],
                ]
                for run in runs
            ],
        ),
        "",
        "## 3. 分组指标",
        "",
    ]
    for run in runs:
        lines.extend(
            [
                f"### {run['run_dir']}",
                "",
                f"证据边界：{run['boundary']}",
                "",
            ]
        )
        group_rows = run.get("group_summary", [])
        if group_rows:
            lines.append(
                markdown_table(
                    [
                        "Group",
                        "Rows",
                        "Score",
                        "WinRate",
                        "Decision",
                        "Fallback",
                        "Invalid",
                        "KnowledgeHit",
                    ],
                    [
                        [
                            row["group_key"],
                            row["rows"],
                            fmt(row["avg_adjusted_final_score"]),
                            fmt(row["avg_win_rate"]),
                            row["decision_count"],
                            row["fallback_count"],
                            row["invalid_count"],
                            fmt(row["avg_knowledge_hit_rate"]),
                        ]
                        for row in group_rows
                    ],
                )
            )
        else:
            lines.append("当前没有完成局分组指标。")
        paired_delta = run.get("leaderboard_summary", {}).get("paired_delta", {})
        if paired_delta:
            lines.extend(
                [
                    "",
                    "Paired delta：",
                    "",
                    markdown_table(
                        ["Baseline", "Candidate", "PairedSeeds", "ScoreDelta", "WinDelta"],
                        [
                            [
                                paired_delta.get("baseline"),
                                paired_delta.get("candidate"),
                                paired_delta.get("paired_seed_count"),
                                fmt(paired_delta.get("avg_adjusted_final_score_delta")),
                                fmt(paired_delta.get("avg_win_rate_delta")),
                            ]
                        ],
                    ),
                ]
            )
        if run.get("failure_types"):
            lines.extend(["", f"Failure types：`{json.dumps(run['failure_types'], ensure_ascii=False)}`"])
        lines.append("")

    lines.extend(
        [
            "## 4. 可写结论与边界",
            "",
            "| 可以写入报告的内容 | 证据条件 |",
            "| --- | --- |",
            "| 真实 LLM 框架实验 runner 可记录 completed/failed/fallback/invalid/knowledge hit | 本文件 run 级表和分组表 |",
            "| fallback/invalid 为 0 的完成局具备决策健康证据 | 对应 run 的 Fallback/Invalid 列为 0 |",
            "| Track C/RAG 相关框架能产生 knowledge hit | 分组表中 KnowledgeHit > 0 |",
            "",
            "| 暂不能写入的内容 | 原因 |",
            "| --- | --- |",
            "| Track C 对胜率有统计显著因果提升 | 当前全席位框架对比不能隔离单个目标席位，仍需 target-seat paired A/B |",
            "| 正在运行且无完成局的实验结果 | `running_no_completed_games` 只能说明输出目录已创建 |",
            "| max_days<=1 的实验代表完整对局能力 | 该类实验只是 smoke，不覆盖完整局长和终局稳定性 |",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        action="append",
        default=[],
        help="Experiment output directory. May be repeated. Defaults to known real-LLM experiment globs.",
    )
    parser.add_argument("--output-md", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_FACTS)
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Override generated_at for reproducible committed evidence snapshots.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dirs = [Path(item) for item in args.input_dir] if args.input_dir else discover_run_dirs(DEFAULT_GLOBS)
    generated_at = args.generated_at or existing_generated_at(args.output_json)
    facts = build_facts(run_dirs, generated_at=generated_at)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_report(facts), encoding="utf-8")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_md}")


if __name__ == "__main__":
    main()
