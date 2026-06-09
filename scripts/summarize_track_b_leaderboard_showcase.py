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
EVIDENCE_DIR = ROOT / "docs" / "evidence"

DEFAULT_FRAMEWORK_DIR = (
    ROOT / "outputs" / "final_showcase_report" / "real_experiment_leaderboard_ark_framework_g5_20260609"
)
DEFAULT_MODEL_DIR = (
    ROOT / "outputs" / "final_showcase_report" / "real_experiment_model_leaderboard_ark_full_cognitive_g1_20260609"
)
DEFAULT_SINGLE_PREFLIGHT = ROOT / "outputs" / "final_showcase_report" / "real_llm_ark_userkey_preflight.json"
DEFAULT_MULTI_PREFLIGHT = ROOT / "outputs" / "final_showcase_report" / "real_llm_ark_multi_model_preflight.json"

DEFAULT_REPORT = EVIDENCE_DIR / "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.md"
DEFAULT_FACTS = EVIDENCE_DIR / "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json"


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


def compact_counts(mapping: dict[str, Any]) -> str:
    if not mapping:
        return ""
    return ", ".join(f"{key}:{value}" for key, value in sorted(mapping.items()))


def summarize_game_run_rows(rows: list[dict[str, Any]], *, scope: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        model_counts = row.get("model_counts", {}) if isinstance(row.get("model_counts"), dict) else {}
        provider_counts = row.get("provider_counts", {}) if isinstance(row.get("provider_counts"), dict) else {}
        parsed.append(
            {
                "scope": scope,
                "seed": row.get("seed", ""),
                "game_id": row.get("game_id", ""),
                "framework": row.get("framework", ""),
                "winner": row.get("winner", ""),
                "days": inum(row.get("days")),
                "events": inum(row.get("events")),
                "elapsed_s": fnum(row.get("elapsed_s")),
                "decision_count": inum(row.get("decision_count")),
                "fallback_count": inum(row.get("fallback_count")),
                "invalid_count": inum(row.get("invalid_count")),
                "knowledge_hit_rate": fnum(row.get("knowledge_hit_rate")),
                "provider_mix": compact_counts(provider_counts),
                "model_mix": compact_counts(model_counts),
            }
        )
    return parsed


def build_score_dimension_rows(*groups: tuple[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scope, group_rows in groups:
        for row in group_rows:
            rows.append(
                {
                    "scope": scope,
                    "group_key": row.get("group_key", ""),
                    "seed": row.get("seed", ""),
                    "seat_samples": row.get("players", 0),
                    "win_rate": row.get("win_rate", 0.0),
                    "adjusted": row.get("avg_adjusted_final_score", 0.0),
                    "vote": row.get("avg_vote_score", 0.0),
                    "speech": row.get("avg_speech_score", 0.0),
                    "skill": row.get("avg_skill_score", 0.0),
                    "knowledge_hit_rate": row.get("knowledge_hit_rate", 0.0),
                    "fallback_count": row.get("fallback_count", 0),
                    "invalid_count": row.get("invalid_count", 0),
                }
            )
    return rows


def build_role_seat_rows(model: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    role_distribution = model.get("role_distribution_audit", {})
    role_win_rates = model.get("role_win_rates", {})
    if not isinstance(role_distribution, dict):
        return rows
    for key, payload in role_distribution.items():
        if not isinstance(payload, dict):
            continue
        win_payload = role_win_rates.get(key, {}) if isinstance(role_win_rates, dict) else {}
        per_role = win_payload.get("role_win_rates", {}) if isinstance(win_payload, dict) else {}
        role_rate_text = "; ".join(
            f"{role}: samples={info.get('samples', 0)}, wins={info.get('wins', 0)}, win_rate={fmt(info.get('win_rate'))}"
            for role, info in sorted(per_role.items())
            if isinstance(info, dict)
        )
        rows.append(
            {
                "group_key": key,
                "seat_samples": payload.get("seat_samples", 0),
                "roles": payload.get("roles", {}),
                "alignments": payload.get("alignments", {}),
                "macro_role_win_rate": win_payload.get("macro_role_win_rate"),
                "micro_role_win_rate": win_payload.get("micro_role_win_rate"),
                "per_role_win_rates": role_rate_text,
            }
        )
    return rows


def build_decision_health_rows(
    framework: dict[str, Any], model: dict[str, Any], aggregate: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    for scope, payload in [("framework_pilot", framework), ("model_pilot", model)]:
        game_summary = payload.get("game_summary", {})
        raw_decisions = inum(game_summary.get("raw_decision_count"))
        fallback_count = inum(game_summary.get("fallback_count"))
        invalid_count = inum(game_summary.get("invalid_count"))
        rows.append(
            {
                "scope": scope,
                "games": game_summary.get("game_count", 0),
                "raw_decisions": raw_decisions,
                "fallback_count": fallback_count,
                "invalid_count": invalid_count,
                "fallback_rate": round(fallback_count / max(raw_decisions, 1), 6),
                "invalid_rate": round(invalid_count / max(raw_decisions, 1), 6),
                "avg_days": game_summary.get("avg_days", 0),
                "avg_events": game_summary.get("avg_events", 0),
                "avg_elapsed_s": game_summary.get("avg_elapsed_s", 0),
                "winner_counts": game_summary.get("winner_counts", {}),
            }
        )
    rows.append(
        {
            "scope": "aggregate",
            "games": aggregate["completed_real_llm_games"],
            "raw_decisions": aggregate["raw_decision_count"],
            "fallback_count": aggregate["fallback_count"],
            "invalid_count": aggregate["invalid_count"],
            "fallback_rate": aggregate["fallback_rate"],
            "invalid_rate": aggregate["invalid_rate"],
            "avg_days": "",
            "avg_events": "",
            "avg_elapsed_s": "",
            "winner_counts": {},
        }
    )
    return rows


def build_track_b_panels(model_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "panel": "game_level",
            "display_name": "对局层",
            "main_question": "每一局是否完整跑完，胜方、天数、事件数、耗时和真实决策健康如何。",
            "metrics": ["winner", "days", "events", "elapsed_s", "decision_count", "fallback_count", "invalid_count"],
            "source": "game_runs.jsonl",
            "report_boundary": "可展示对局运行和 Track B 输入质量；不能单独推出模型优劣或 Track C 增益。",
        },
        {
            "panel": "version_or_model_level",
            "display_name": "模型/版本层",
            "main_question": "同一 scoring pipeline 能否按 framework 或 model 分组形成 leaderboard。",
            "metrics": [
                "win_rate",
                "avg_adjusted_final_score",
                "avg_vote_score",
                "avg_speech_score",
                "avg_skill_score",
            ],
            "source": "group_results.csv / leaderboard.json",
            "report_boundary": "当前 model pilot 只有 1 局且角色不均衡，只能展示分组能力。",
        },
        {
            "panel": "player_role_level",
            "display_name": "玩家/角色席位层",
            "main_question": "不同模型实际拿到了哪些角色和阵营，分数解释是否受角色分布影响。",
            "metrics": ["seat_samples", "roles", "alignments", "macro_role_win_rate", "per_role_win_rates"],
            "source": "summary.json role_distribution_audit / role_win_rates",
            "report_boundary": "该层用于解释混杂因素，不用于正式模型排名结论。",
        },
        {
            "panel": "score_dimension_level",
            "display_name": "评分维度层",
            "main_question": "Agent 表现可以拆成投票、发言、技能和最终调整分，而不是只看胜负。",
            "metrics": ["avg_adjusted_final_score", "avg_vote_score", "avg_speech_score", "avg_skill_score"],
            "source": "group_results.csv",
            "report_boundary": "维度分用于 Track B 复盘展示；胜率仍只作为辅助指标。",
        },
        {
            "panel": "rubric_level",
            "display_name": "Rubric 层",
            "main_question": "项目验收口径如何映射为 single_agent、multi_agent、engineering、advanced_bc 四个维度。",
            "metrics": ["rubric_total_score", "single_agent", "multi_agent", "engineering", "advanced_bc"],
            "source": "architecture_evidence_leaderboard.json / csv",
            "report_boundary": "Rubric 分是展示评分，不是统计显著性检验。",
        },
        {
            "panel": "decision_health_level",
            "display_name": "决策健康层",
            "main_question": "真实 LLM 输出是否出现 fallback、invalid、异常失败或决策污染。",
            "metrics": ["raw_decision_count", "fallback_rate", "invalid_rate", "failed_games"],
            "source": "game_runs.jsonl / failures.jsonl",
            "report_boundary": "该层证明输入质量和可审计性，是其他评分层的前置健康条件。",
        },
        {
            "panel": "review_artifact_level",
            "display_name": "复盘展示层",
            "main_question": "Track B 输出是否能进入可展示的榜单、rubric 表和报告材料。",
            "metrics": ["leaderboard.json", "architecture_evidence_leaderboard", "academic_report.md"],
            "source": rel(model_dir / "academic_report.md"),
            "report_boundary": "该层展示报告产物存在，不等价于人工评审一致性实验。",
        },
    ]


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
        "game_rows": summarize_game_run_rows(game_runs, scope="framework_pilot"),
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
        "game_rows": summarize_game_run_rows(game_runs, scope="model_pilot"),
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
    aggregate = {
        "completed_real_llm_games": completed_games,
        "failed_games": framework["failed_games"] + model["failed_games"],
        "raw_decision_count": raw_decisions,
        "fallback_count": fallback_count,
        "invalid_count": invalid_count,
        "fallback_rate": round(fallback_count / max(raw_decisions, 1), 6),
        "invalid_rate": round(invalid_count / max(raw_decisions, 1), 6),
    }

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
        "aggregate": aggregate,
        "track_b_layers": build_track_b_panels(model_dir),
        "track_b_showcase_panels": {
            "game_level_rows": framework["game_rows"] + model["game_rows"],
            "version_or_model_rows": framework["group_rows"] + model["group_rows"],
            "role_seat_rows": build_role_seat_rows(model),
            "score_dimension_rows": build_score_dimension_rows(
                ("framework_pilot", framework["group_rows"]),
                ("model_pilot", model["group_rows"]),
            ),
            "rubric_rows": model["architecture_entries"],
            "decision_health_rows": build_decision_health_rows(framework, model, aggregate),
            "review_artifacts": [
                {
                    "artifact": "leaderboard.json",
                    "purpose": "模型/版本榜单条目",
                    "source": rel(model_dir / "leaderboard.json"),
                    "exists": (model_dir / "leaderboard.json").exists(),
                },
                {
                    "artifact": "architecture_evidence_leaderboard.json",
                    "purpose": "项目 rubric 展示分",
                    "source": rel(model_dir / "architecture_evidence_leaderboard.json"),
                    "exists": (model_dir / "architecture_evidence_leaderboard.json").exists(),
                },
                {
                    "artifact": "academic_report.md",
                    "purpose": "实验报告正文材料",
                    "source": rel(model_dir / "academic_report.md"),
                    "exists": (model_dir / "academic_report.md").exists(),
                },
            ],
        },
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
    panels = facts.get("track_b_showcase_panels", {})
    lines = [
        "# Track B Leaderboard 多层展示实验",
        "",
        f"生成时间：{facts['generated_at']}",
        "",
        "本文档汇总当前真实 LLM 输出中可用于展示 Track B 的材料。它的定位是“多层复盘、逐步评分与 leaderboard 展示”，不是 Track C 因果增益报告。",
        "",
        "```mermaid",
        "flowchart LR",
        "    accTitle: Track B Evidence Flow",
        "    accDescr: This diagram shows how a real LLM game becomes multi-layer Track B review panels, including game, role, score, rubric, health, and report artifacts.",
        "    game[GameRun / WerewolfGame] --> metrics[MetricsCalculator]",
        "    metrics --> player[PlayerScore]",
        "    metrics --> group[group_results.csv]",
        "    player --> leaderboard[LeaderboardAggregator]",
        "    group --> rubric[architecture_evidence_leaderboard]",
        "    game --> health[Decision Health]",
        "    group --> role[Role / Seat Panel]",
        "    group --> score[Score Dimension Panel]",
        "    leaderboard --> report[Track B Showcase]",
        "    rubric --> report",
        "    health --> report",
        "    role --> report",
        "    score --> report",
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
                [
                    "Track C 字段边界",
                    "knowledge_hit_rate 只作为知识注入痕迹展示，不作为 Track B 主评分结论，也不写成 Track C 因果增益。",
                ],
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
        "Track B 的展示重点是把一局真实 LLM 对局拆成多个可解释面板。排行榜只是其中一个面板；更重要的是能同时看到对局是否完成、每个模型或框架拿到什么角色、投票/发言/技能维度如何、rubric 如何映射，以及 fallback/invalid 是否污染评分。",
        "",
        markdown_table(
            ["展示面板", "分析问题", "核心指标", "来源", "结论边界"],
            [
                [
                    row["display_name"],
                    row["main_question"],
                    ", ".join(row["metrics"]),
                    row["source"],
                    row["report_boundary"],
                ]
                for row in facts["track_b_layers"]
            ],
        ),
        "",
        "## 4. 对局层：真实 LLM 对局输入",
        "",
        markdown_table(
            [
                "Scope",
                "Seed",
                "GameId",
                "Framework",
                "Winner",
                "Days",
                "Events",
                "ElapsedS",
                "Decisions",
                "Fallback",
                "Invalid",
                "ModelMix",
            ],
            [
                [
                    row["scope"],
                    row["seed"],
                    row["game_id"],
                    row["framework"],
                    row["winner"],
                    row["days"],
                    row["events"],
                    fmt(row["elapsed_s"]),
                    row["decision_count"],
                    row["fallback_count"],
                    row["invalid_count"],
                    row["model_mix"],
                ]
                for row in panels.get("game_level_rows", [])
            ],
        ),
        "",
        "该层用于说明 Track B 的输入质量：当前 6 局真实 LLM 输出均有完整 game run 记录，整局真实决策数以 `game_runs.jsonl` 为准。",
        "",
        "## 5. 模型/版本层：Framework 与 Model 分组",
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
        "Model leaderboard pilot：",
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
        "该层可以展示 Track B 是否能把不同 framework 或 model 放到同一 scoring pipeline 下比较。当前数据只能说明分组和打分流程可用，不能写成正式模型优劣结论。",
        "",
        "## 6. 玩家/角色席位层：角色分布与混杂解释",
        "",
        markdown_table(
            ["Model", "SeatSamples", "Roles", "Alignments", "MacroRoleWinRate", "MicroRoleWinRate", "PerRoleWinRates"],
            [
                [
                    row["group_key"],
                    row["seat_samples"],
                    json.dumps(row["roles"], ensure_ascii=False),
                    json.dumps(row["alignments"], ensure_ascii=False),
                    fmt(row["macro_role_win_rate"]),
                    fmt(row["micro_role_win_rate"]),
                    row["per_role_win_rates"],
                ]
                for row in panels.get("role_seat_rows", [])
            ],
        ),
        "",
        "该层是 Track B 展示中很关键的一层：狼人杀的分数受角色、阵营和席位影响很大，因此模型或版本榜单必须配套展示角色分布。当前模型 pilot 中两个模型的角色并不均衡，所以只能展示“系统能分层分析”，不能写成正式模型排名。",
        "",
        "## 7. 评分维度层：胜负之外的行为拆解",
        "",
        markdown_table(
            [
                "Scope",
                "Group",
                "Seed",
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
                    row["scope"],
                    row["group_key"],
                    row["seed"],
                    row["seat_samples"],
                    fmt(row["win_rate"]),
                    fmt(row["adjusted"]),
                    fmt(row["vote"]),
                    fmt(row["speech"]),
                    fmt(row["skill"]),
                    fmt(row["knowledge_hit_rate"]),
                    row["fallback_count"],
                    row["invalid_count"],
                ]
                for row in panels.get("score_dimension_rows", [])
            ],
        ),
        "",
        "该层展示 Track B 的核心价值：不只给出胜负，而是把 Agent 表现拆成投票、发言、技能和调整后总分。`KnowledgeHit` 在这里只作为策略检索痕迹，不能解释为 Track C 的胜率提升。",
        "",
        "## 8. Rubric 层：项目验收维度映射",
        "",
        markdown_table(
            [
                "Rank",
                "Group",
                "RubricTotal",
                "SingleAgent",
                "MultiAgent",
                "Engineering",
                "AdvancedBC",
                "SeatSamples",
                "CoreRoleCoverage",
                "KnowledgeHit",
                "Fallback",
                "Invalid",
            ],
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
                    fmt(row.get("evidence_signals", {}).get("core_role_coverage")),
                    fmt(row.get("evidence_signals", {}).get("knowledge_hit_rate")),
                    row.get("evidence_signals", {}).get("fallback_count"),
                    row.get("evidence_signals", {}).get("invalid_count"),
                ]
                for row in panels.get("rubric_rows", [])
            ],
        ),
        "",
        "该层把项目展示所需的验收语言映射到四类 rubric：single_agent、multi_agent、engineering 和 advanced_bc。它适合放在结项展示中说明“评分维度如何组织”，但不替代统计检验。",
        "",
        "## 9. 决策健康层与复盘产物层",
        "",
        markdown_table(
            [
                "Scope",
                "Games",
                "RawDecisions",
                "Fallback",
                "Invalid",
                "FallbackRate",
                "InvalidRate",
                "AvgDays",
                "AvgEvents",
                "AvgElapsedS",
                "WinnerCounts",
            ],
            [
                [
                    row["scope"],
                    row["games"],
                    row["raw_decisions"],
                    row["fallback_count"],
                    row["invalid_count"],
                    fmt(row["fallback_rate"]),
                    fmt(row["invalid_rate"]),
                    row["avg_days"] if row["avg_days"] == "" else fmt(row["avg_days"]),
                    row["avg_events"] if row["avg_events"] == "" else fmt(row["avg_events"]),
                    row["avg_elapsed_s"] if row["avg_elapsed_s"] == "" else fmt(row["avg_elapsed_s"]),
                    json.dumps(row["winner_counts"], ensure_ascii=False),
                ]
                for row in panels.get("decision_health_rows", [])
            ],
        ),
        "",
        "复盘产物：",
        "",
        markdown_table(
            ["Artifact", "Purpose", "Exists", "Source"],
            [
                [
                    row["artifact"],
                    row["purpose"],
                    row["exists"],
                    row["source"],
                ]
                for row in panels.get("review_artifacts", [])
            ],
        ),
        "",
        "该层用于说明 Track B 展示的输入没有 fallback/invalid 污染，并且已经产出 leaderboard、rubric leaderboard 和报告材料。人工一致性、逐步高光/失误抽样仍是后续可补实验。",
        "",
        "## 10. 可写结论与边界",
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
        "## 11. 后续补充建议",
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
