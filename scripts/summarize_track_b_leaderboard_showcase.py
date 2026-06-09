#!/usr/bin/env python3
"""Build a Track B leaderboard showcase from existing real-LLM outputs.

This script is intentionally read-only with respect to experiment execution: it
parses local `outputs/` artifacts produced by `track_bc_leaderboard_experiment.py`
and writes a tracked Markdown/JSON summary. The report frames the evidence as
Track B multi-layer review/leaderboard capability, not as Track C causal gain.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FRAMEWORK_DIR = (
    ROOT / "outputs" / "final_showcase_report" / "real_experiment_leaderboard_ark_framework_g5_20260609"
)
DEFAULT_MODEL_DIR = (
    ROOT / "outputs" / "final_showcase_report" / "real_experiment_model_leaderboard_ark_full_cognitive_g1_20260609"
)
DEFAULT_SINGLE_PREFLIGHT = ROOT / "outputs" / "final_showcase_report" / "real_llm_ark_userkey_preflight.json"
DEFAULT_MULTI_PREFLIGHT = ROOT / "outputs" / "final_showcase_report" / "real_llm_ark_multi_model_preflight.json"

DEFAULT_REPORT = ROOT / "docs" / "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.md"
DEFAULT_FACTS = ROOT / "docs" / "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def existing_generated_at(path: Path) -> str | None:
    payload = read_json(path)
    value = payload.get("generated_at")
    return str(value) if value else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
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
    if value is None:
        return "n/a"
    return f"{fnum(value):.{digits}f}"


def pct(value: Any) -> str:
    return f"{fnum(value) * 100:.2f}%"


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def parse_json_cell(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def compact_chat_checks(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in preflight.get("chat_checks", []) if isinstance(preflight, dict) else []:
        rows.append(
            {
                "label": item.get("label", ""),
                "ok": bool(item.get("ok", False)),
                "elapsed_s": fnum(item.get("elapsed_s")),
                "response_preview": item.get("response_preview", ""),
                "error": item.get("error", ""),
            }
        )
    return rows


def summarize_game_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "game_count": len(rows),
        "game_ids": [row.get("game_id") for row in rows],
        "winner_counts": dict(Counter(str(row.get("winner") or "unknown") for row in rows)),
        "avg_days": round(avg([fnum(row.get("days")) for row in rows]), 4),
        "avg_events": round(avg([fnum(row.get("events")) for row in rows]), 4),
        "avg_elapsed_s": round(avg([fnum(row.get("elapsed_s")) for row in rows]), 4),
        "raw_decision_count": sum(inum(row.get("decision_count")) for row in rows),
        "fallback_count": sum(inum(row.get("fallback_count")) for row in rows),
        "invalid_count": sum(inum(row.get("invalid_count")) for row in rows),
        "retrieved_count": sum(inum(row.get("retrieved_count")) for row in rows),
        "avg_knowledge_hit_rate": round(avg([fnum(row.get("knowledge_hit_rate")) for row in rows]), 6),
        "provider_counts": dict(sum((Counter(row.get("provider_counts", {})) for row in rows), Counter())),
        "model_counts": dict(sum((Counter(row.get("model_counts", {})) for row in rows), Counter())),
    }


def summarize_group_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        parsed.append(
            {
                "seed": row.get("seed", ""),
                "source_game_id": row.get("source_game_id", ""),
                "group_key": row.get("group_key", ""),
                "framework": row.get("framework", ""),
                "players": inum(row.get("players")),
                "wins": inum(row.get("wins")),
                "win_rate": fnum(row.get("win_rate")),
                "avg_adjusted_final_score": fnum(row.get("avg_adjusted_final_score")),
                "avg_final_score": fnum(row.get("avg_final_score")),
                "avg_vote_score": fnum(row.get("avg_vote_score")),
                "avg_speech_score": fnum(row.get("avg_speech_score")),
                "avg_skill_score": fnum(row.get("avg_skill_score")),
                "decision_count": inum(row.get("decision_count")),
                "fallback_count": inum(row.get("fallback_count")),
                "invalid_count": inum(row.get("invalid_count")),
                "knowledge_hit_rate": fnum(row.get("knowledge_hit_rate")),
                "roles": parse_json_cell(row.get("roles", "")),
                "role_wins": parse_json_cell(row.get("role_wins", "")),
                "alignments": parse_json_cell(row.get("alignments", "")),
            }
        )
    return parsed


def summarize_framework_pilot(run_dir: Path) -> dict[str, Any]:
    summary = read_json(run_dir / "summary.json") or read_json(run_dir / "partial_summary.json")
    game_runs = read_jsonl(run_dir / "game_runs.jsonl")
    group_rows = summarize_group_rows(read_csv(run_dir / "group_results.csv"))
    completed_groups = sorted({row["group_key"] for row in group_rows if row.get("group_key")})
    return {
        "source_dir": rel(run_dir),
        "summary_file": rel(
            (run_dir / "summary.json") if (run_dir / "summary.json").exists() else (run_dir / "partial_summary.json")
        ),
        "status": "complete" if (run_dir / "summary.json").exists() else "partial",
        "axis": summary.get("axis", "framework"),
        "frameworks_requested": [
            item.get("name", "") for item in summary.get("frameworks", []) if isinstance(item, dict)
        ],
        "completed_groups": completed_groups,
        "games_per_framework": inum(summary.get("games_per_framework")),
        "completed_raw_games": inum(summary.get("completed_raw_games")),
        "failed_games": inum(summary.get("failed_games")),
        "attempted_games": inum(summary.get("attempted_games")),
        "max_days": inum(summary.get("max_days")),
        "model_pool": summary.get("model_pool", []),
        "game_summary": summarize_game_runs(game_runs),
        "group_rows": group_rows,
        "boundary": (
            "本批次完成了 basic_react 的 5 局真实火山 Ark 对局；后续 rag_react/full_cognitive 未完成，"
            "因此只能作为 Track B baseline 分层展示和运行健康证据，不能作为完整三框架排行榜。"
        ),
    }


def summarize_model_pilot(run_dir: Path) -> dict[str, Any]:
    summary = read_json(run_dir / "summary.json") or read_json(run_dir / "partial_summary.json")
    game_runs = read_jsonl(run_dir / "game_runs.jsonl")
    group_rows = summarize_group_rows(read_csv(run_dir / "group_results.csv"))
    leaderboard = read_json(run_dir / "leaderboard.json")
    architecture = read_json(run_dir / "architecture_evidence_leaderboard.json")
    return {
        "source_dir": rel(run_dir),
        "summary_file": rel(
            (run_dir / "summary.json") if (run_dir / "summary.json").exists() else (run_dir / "partial_summary.json")
        ),
        "status": "complete" if (run_dir / "summary.json").exists() else "partial",
        "axis": summary.get("axis", "model"),
        "framework": (summary.get("frameworks") or [{}])[0].get("name", "")
        if isinstance(summary.get("frameworks"), list)
        else "",
        "model_pool": summary.get("model_pool", []),
        "completed_raw_games": inum(summary.get("completed_raw_games")),
        "failed_games": inum(summary.get("failed_games")),
        "attempted_games": inum(summary.get("attempted_games")),
        "max_days": inum(summary.get("max_days")),
        "leaderboard_summary": summary.get("leaderboard_summary", {}),
        "role_distribution_audit": summary.get("role_distribution_audit", {}),
        "role_win_rates": summary.get("role_win_rates", {}),
        "bootstrap_reliability": summary.get("bootstrap_reliability", {}),
        "game_summary": summarize_game_runs(game_runs),
        "group_rows": group_rows,
        "leaderboard_entries": leaderboard.get("entries", []) if isinstance(leaderboard, dict) else [],
        "architecture_entries": architecture.get("entries", []) if isinstance(architecture, dict) else [],
        "architecture_dimensions": architecture.get("dimensions", {}) if isinstance(architecture, dict) else {},
        "boundary": (
            "本模型榜单是 1 局 pilot，席位角色分布并不均衡；可展示 Track B 多层评分和模型分组能力，"
            "不能写成正式模型优劣结论。"
        ),
    }


def build_facts(
    *,
    framework_dir: Path = DEFAULT_FRAMEWORK_DIR,
    model_dir: Path = DEFAULT_MODEL_DIR,
    single_preflight_path: Path = DEFAULT_SINGLE_PREFLIGHT,
    multi_preflight_path: Path = DEFAULT_MULTI_PREFLIGHT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    single_preflight = read_json(single_preflight_path)
    multi_preflight = read_json(multi_preflight_path)
    framework = summarize_framework_pilot(framework_dir)
    model = summarize_model_pilot(model_dir)
    model_checks = compact_chat_checks(multi_preflight)
    ok_models = [row["label"] for row in model_checks if row["ok"]]
    failed_models = [row["label"] for row in model_checks if not row["ok"]]
    raw_decisions = framework["game_summary"]["raw_decision_count"] + model["game_summary"]["raw_decision_count"]
    fallback_count = framework["game_summary"]["fallback_count"] + model["game_summary"]["fallback_count"]
    invalid_count = framework["game_summary"]["invalid_count"] + model["game_summary"]["invalid_count"]
    completed_games = framework["completed_raw_games"] + model["completed_raw_games"]

    return {
        "generated_at": generated_at or now_iso(),
        "report_type": "track_b_leaderboard_multilayer_showcase",
        "claim_scope": "Track B 多层评分与 leaderboard 展示；不是 Track C 因果增益证明",
        "sources": {
            "framework_pilot": framework["source_dir"],
            "model_pilot": model["source_dir"],
            "single_model_preflight": rel(single_preflight_path),
            "multi_model_preflight": rel(multi_preflight_path),
        },
        "provider_preflight": {
            "single_model_status": single_preflight.get("status"),
            "single_model_safe": bool(single_preflight.get("safe_for_formal_experiment", False)),
            "single_model_checks": compact_chat_checks(single_preflight),
            "multi_model_status": multi_preflight.get("status"),
            "multi_model_safe": bool(multi_preflight.get("safe_for_formal_experiment", False)),
            "ok_models": ok_models,
            "failed_models": failed_models,
            "multi_model_checks": model_checks,
        },
        "aggregate": {
            "completed_real_llm_games": completed_games,
            "failed_games": framework["failed_games"] + model["failed_games"],
            "raw_decision_count": raw_decisions,
            "fallback_count": fallback_count,
            "invalid_count": invalid_count,
            "fallback_rate": round(fallback_count / max(raw_decisions, 1), 6),
            "invalid_rate": round(invalid_count / max(raw_decisions, 1), 6),
        },
        "track_b_layers": [
            {
                "layer": "game_level",
                "meaning": "完整对局层：胜方、天数、事件数、耗时、provider/model 追踪。",
                "source": "game_runs.jsonl",
            },
            {
                "layer": "version_or_model_level",
                "meaning": "版本/模型层：按 framework 或 model 分组的平均分、胜率、榜单排名。",
                "source": "group_results.csv / leaderboard.json",
            },
            {
                "layer": "player_role_level",
                "meaning": "席位/角色层：不同模型分到的角色、阵营、席位样本和角色胜率。",
                "source": "summary.json role_distribution_audit / role_win_rates",
            },
            {
                "layer": "score_dimension_level",
                "meaning": "评分维度层：adjusted、vote、speech、skill 和 rubric 维度拆解。",
                "source": "group_results.csv / architecture_evidence_leaderboard.csv",
            },
            {
                "layer": "decision_health_level",
                "meaning": "决策健康层：真实决策数、fallback、invalid、完成/失败。",
                "source": "game_runs.jsonl / group_results.csv",
            },
            {
                "layer": "knowledge_auxiliary_level",
                "meaning": "知识命中辅助层：knowledge_hit_rate 用于展示 Track C 信息注入痕迹，但不作为 Track B 主结论。",
                "source": "group_results.csv / game_runs.jsonl",
            },
        ],
        "framework_pilot": framework,
        "model_pilot": model,
        "claim_boundaries": [
            "模型 pilot 只有 1 局，且模型分到的角色不同，不能写成正式模型优劣结论。",
            "framework g5 批次只完成 basic_react 5 局；rag_react/full_cognitive 未完成，不能写成完整三框架对比。",
            "Track B leaderboard 展示的是评分、复盘和可区分能力；Track C 因果增益仍需 target-seat paired A/B。",
            "group_results 中的 decision_count 来自整局 metadata，模型分组行不可简单相加；总决策数以 game_runs.jsonl 为准。",
        ],
        "can_write": [
            "火山 Ark 真实 LLM 对局可以进入 Track B leaderboard 流程并产出多层评分。",
            "当前完成的真实 LLM 对局 fallback/invalid 均为 0，可作为决策健康证据。",
            "Track B 可以按模型/版本、角色席位、评分维度和 rubric 维度拆解对局质量。",
        ],
        "cannot_write": [
            "不能写成 deepseek-v4-pro[1m] 正式优于 deepseek-v4-flash[1m]。",
            "不能写成 full_cognitive 已在本轮 framework leaderboard 中超过 basic_react。",
            "不能把 knowledge_hit_rate 写成 Track C 对胜率的因果提升。",
        ],
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(facts: dict[str, Any]) -> str:
    framework = facts["framework_pilot"]
    model = facts["model_pilot"]
    aggregate = facts["aggregate"]
    provider = facts["provider_preflight"]
    lines = [
        "# Track B Leaderboard 多层展示实验",
        "",
        f"生成时间：{facts['generated_at']}",
        "",
        "本文档汇总当前真实 LLM 输出中可用于展示 Track B 的材料。它的定位是“多层复盘与 leaderboard 展示”，不是 Track C 因果增益报告。",
        "",
        "```mermaid",
        "flowchart LR",
        "    accTitle: Track B Evidence Flow",
        "    accDescr: This diagram shows how a real LLM game becomes Track B review metrics, leaderboard entries, rubric dimensions, and report evidence.",
        "    game[GameRun / WerewolfGame] --> metrics[MetricsCalculator]",
        "    metrics --> player[PlayerScore]",
        "    metrics --> group[group_results.csv]",
        "    player --> leaderboard[LeaderboardAggregator]",
        "    group --> rubric[architecture_evidence_leaderboard]",
        "    leaderboard --> report[Track B Showcase]",
        "    rubric --> report",
        "    group --> report",
        "```",
        "",
        "## 1. 证据定位",
        "",
        markdown_table(
            ["项目", "说明"],
            [
                ["证据类型", facts["claim_scope"]],
                ["完成真实 LLM 对局", aggregate["completed_real_llm_games"]],
                ["失败局", aggregate["failed_games"]],
                ["整局真实决策数", aggregate["raw_decision_count"]],
                ["fallback / invalid", f"{aggregate['fallback_count']} / {aggregate['invalid_count']}"],
                ["总决策口径", "以 game_runs.jsonl 为准；模型分组行的 decision_count 不相加"],
            ],
        ),
        "",
        "## 2. Provider 与模型可用性",
        "",
        markdown_table(
            ["检查", "状态", "Safe", "可用模型", "失败模型", "来源"],
            [
                [
                    "单模型 preflight",
                    provider.get("single_model_status"),
                    provider.get("single_model_safe"),
                    ", ".join(row["label"] for row in provider.get("single_model_checks", []) if row.get("ok")),
                    ", ".join(row["label"] for row in provider.get("single_model_checks", []) if not row.get("ok")),
                    facts["sources"]["single_model_preflight"],
                ],
                [
                    "多模型 preflight",
                    provider.get("multi_model_status"),
                    provider.get("multi_model_safe"),
                    ", ".join(provider.get("ok_models", [])),
                    ", ".join(provider.get("failed_models", [])),
                    facts["sources"]["multi_model_preflight"],
                ],
            ],
        ),
        "",
        "## 3. Track B 多层分析框架",
        "",
        markdown_table(
            ["层级", "说明", "来源"],
            [[row["layer"], row["meaning"], row["source"]] for row in facts["track_b_layers"]],
        ),
        "",
        "## 4. Framework Pilot：baseline 层展示",
        "",
        framework["boundary"],
        "",
        markdown_table(
            ["Framework", "Seed", "Players", "WinRate", "Adjusted", "Vote", "Speech", "Skill", "KnowledgeHit"],
            [
                [
                    row["group_key"],
                    row["seed"],
                    row["players"],
                    fmt(row["win_rate"]),
                    fmt(row["avg_adjusted_final_score"]),
                    fmt(row["avg_vote_score"]),
                    fmt(row["avg_speech_score"]),
                    fmt(row["avg_skill_score"]),
                    fmt(row["knowledge_hit_rate"]),
                ]
                for row in framework["group_rows"]
            ],
        ),
        "",
        "framework pilot 整局健康：",
        "",
        markdown_table(
            ["Games", "RawDecisions", "Fallback", "Invalid", "AvgDays", "AvgEvents", "AvgElapsedS", "WinnerCounts"],
            [
                [
                    framework["game_summary"]["game_count"],
                    framework["game_summary"]["raw_decision_count"],
                    framework["game_summary"]["fallback_count"],
                    framework["game_summary"]["invalid_count"],
                    fmt(framework["game_summary"]["avg_days"]),
                    fmt(framework["game_summary"]["avg_events"]),
                    fmt(framework["game_summary"]["avg_elapsed_s"]),
                    json.dumps(framework["game_summary"]["winner_counts"], ensure_ascii=False),
                ]
            ],
        ),
        "",
        "## 5. Model Leaderboard Pilot：模型层展示",
        "",
        model["boundary"],
        "",
        markdown_table(
            [
                "Model",
                "SeatSamples",
                "WinRate",
                "Adjusted",
                "Vote",
                "Speech",
                "Skill",
                "KnowledgeHit",
                "Fallback",
                "Invalid",
            ],
            [
                [
                    row["group_key"],
                    row["players"],
                    fmt(row["win_rate"]),
                    fmt(row["avg_adjusted_final_score"]),
                    fmt(row["avg_vote_score"]),
                    fmt(row["avg_speech_score"]),
                    fmt(row["avg_skill_score"]),
                    fmt(row["knowledge_hit_rate"]),
                    row["fallback_count"],
                    row["invalid_count"],
                ]
                for row in model["group_rows"]
            ],
        ),
        "",
        "模型 pilot 的角色席位分布：",
        "",
        markdown_table(
            ["Model", "SeatSamples", "Roles", "Alignments", "MacroRoleWinRate"],
            [
                [
                    key,
                    payload.get("seat_samples", 0),
                    json.dumps(payload.get("roles", {}), ensure_ascii=False),
                    json.dumps(payload.get("alignments", {}), ensure_ascii=False),
                    fmt(model.get("role_win_rates", {}).get(key, {}).get("macro_role_win_rate")),
                ]
                for key, payload in model.get("role_distribution_audit", {}).items()
            ],
        ),
        "",
        "## 6. Rubric 维度展示",
        "",
        markdown_table(
            ["Rank", "Group", "RubricTotal", "SingleAgent", "MultiAgent", "Engineering", "AdvancedBC", "SeatSamples"],
            [
                [
                    row.get("rank"),
                    row.get("group_key"),
                    fmt(row.get("rubric_total_score")),
                    fmt(row.get("rubric_dimensions", {}).get("single_agent")),
                    fmt(row.get("rubric_dimensions", {}).get("multi_agent")),
                    fmt(row.get("rubric_dimensions", {}).get("engineering")),
                    fmt(row.get("rubric_dimensions", {}).get("advanced_bc")),
                    row.get("evidence_signals", {}).get("seat_samples"),
                ]
                for row in model.get("architecture_entries", [])
            ],
        ),
        "",
        "## 7. 可写结论与边界",
        "",
        "可以写入报告：",
        "",
        markdown_table(["结论"], [[item] for item in facts["can_write"]]),
        "",
        "暂不能写入报告：",
        "",
        markdown_table(["结论"], [[item] for item in facts["cannot_write"]]),
        "",
        "边界说明：",
        "",
        markdown_table(["边界"], [[item] for item in facts["claim_boundaries"]]),
        "",
        "## 8. 后续补充建议",
        "",
        markdown_table(
            ["补充项", "建议"],
            [
                ["模型 leaderboard", "将通过 preflight 的模型扩展到每模型 5-20 局，并按角色/阵营平衡席位。"],
                ["framework leaderboard", "继续完成 rag_react 与 full_cognitive 的同 seed 对比，补齐三框架榜单。"],
                [
                    "Track B 逐步评分",
                    "从 PerStepScorer 导出 speech/vote/skill step 级 score，用于展示高光、失误和 judge agreement。",
                ],
                ["角色层展示", "按 Seer/Witch/Guard/Werewolf 等角色生成 role-normalized leaderboard。"],
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework-dir", type=Path, default=DEFAULT_FRAMEWORK_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--single-preflight", type=Path, default=DEFAULT_SINGLE_PREFLIGHT)
    parser.add_argument("--multi-preflight", type=Path, default=DEFAULT_MULTI_PREFLIGHT)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--generated-at", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_at = args.generated_at or existing_generated_at(args.output_json)
    facts = build_facts(
        framework_dir=args.framework_dir,
        model_dir=args.model_dir,
        single_preflight_path=args.single_preflight,
        multi_preflight_path=args.multi_preflight,
        generated_at=generated_at,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_report(facts), encoding="utf-8")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_md}")


if __name__ == "__main__":
    main()
