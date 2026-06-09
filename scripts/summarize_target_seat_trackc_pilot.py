#!/usr/bin/env python3
"""Build a tracked summary for the target-seat Track C real-LLM pilot.

The raw target-seat A/B outputs live under `outputs/` and are intentionally not
tracked. This script extracts the small evidence surface needed by closure
reports: paired seed count, deltas, bootstrap CI, health gates, and claim
boundaries. It does not run LLM games.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SOURCE = (
    ROOT / "outputs" / "target_seat_trackc_ab_seer_ark_pilot_20260609" / "target_seat_ab_Seer_20260609T082838Z.json"
)
DEFAULT_REPORT = ROOT / "docs" / "PROJECT_TARGET_SEAT_TRACKC_PILOT.md"
DEFAULT_FACTS = ROOT / "docs" / "PROJECT_TARGET_SEAT_TRACKC_PILOT.json"


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


def score_value(row: dict[str, Any], field: str) -> float:
    return fnum(row.get("target_score", {}).get(field))


def result_by_seed(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    parsed: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            parsed[int(row.get("seed"))] = row
        except (TypeError, ValueError):
            continue
    return parsed


def summarize_models(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for seat in row.get("seat_assignments", []) if isinstance(row.get("seat_assignments"), list) else []:
            model = str(seat.get("model") or "").strip()
            if model:
                counter[model] += 1
    return dict(counter)


def build_paired_rows(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_by_seed = result_by_seed(baseline)
    cand_by_seed = result_by_seed(candidate)
    rows: list[dict[str, Any]] = []
    for seed in sorted(set(base_by_seed) & set(cand_by_seed)):
        base = base_by_seed[seed]
        cand = cand_by_seed[seed]
        target = cand.get("target", {}) if isinstance(cand.get("target"), dict) else {}
        rows.append(
            {
                "seed": seed,
                "target_seat": target.get("seat"),
                "target_role": target.get("role"),
                "target_alignment": target.get("alignment"),
                "baseline_game_id": base.get("game_id"),
                "candidate_game_id": cand.get("game_id"),
                "baseline_winner": base.get("winner"),
                "candidate_winner": cand.get("winner"),
                "baseline_target_won": bool(base.get("target_won", False)),
                "candidate_target_won": bool(cand.get("target_won", False)),
                "adjusted_delta": round(
                    score_value(cand, "adjusted_final_score") - score_value(base, "adjusted_final_score"), 4
                ),
                "role_task_delta": round(
                    score_value(cand, "role_task_score") - score_value(base, "role_task_score"), 4
                ),
                "process_delta": round(score_value(cand, "process_score") - score_value(base, "process_score"), 4),
                "baseline_adjusted_score": score_value(base, "adjusted_final_score"),
                "candidate_adjusted_score": score_value(cand, "adjusted_final_score"),
                "baseline_role_task_score": score_value(base, "role_task_score"),
                "candidate_role_task_score": score_value(cand, "role_task_score"),
                "candidate_decisions": inum(cand.get("decision_summary", {}).get("decision_count")),
                "candidate_fallback": inum(cand.get("decision_summary", {}).get("fallback_count")),
                "candidate_invalid": inum(cand.get("decision_summary", {}).get("invalid_count")),
            }
        )
    return rows


def claim_scope(payload: dict[str, Any], comparison: dict[str, Any]) -> str:
    paired = inum(comparison.get("paired_seed_count"))
    max_days = inum(payload.get("max_days"))
    accepted = bool(comparison.get("acceptance", {}).get("accepted", False))
    if max_days <= 1:
        return "smoke_only"
    if accepted:
        return "causal_supported"
    if paired < 20:
        return "real_llm_pilot_only"
    return "formal_candidate_not_accepted"


def build_facts(*, source_path: Path = DEFAULT_SOURCE, generated_at: str | None = None) -> dict[str, Any]:
    payload = read_json(source_path)
    if not payload:
        raise FileNotFoundError(f"target-seat source not found or empty: {source_path}")
    comparison = payload.get("comparison", {}) if isinstance(payload.get("comparison"), dict) else {}
    acceptance = comparison.get("acceptance", {}) if isinstance(comparison.get("acceptance"), dict) else {}
    gates = acceptance.get("gates", {}) if isinstance(acceptance.get("gates"), dict) else {}
    baseline = payload.get("baseline_results", []) if isinstance(payload.get("baseline_results"), list) else []
    candidate = payload.get("candidate_results", []) if isinstance(payload.get("candidate_results"), list) else []
    paired_rows = build_paired_rows(baseline, candidate)
    ci = comparison.get("bootstrap_ci", {}) if isinstance(comparison.get("bootstrap_ci"), dict) else {}
    adjusted_ci = (
        ci.get("adjusted_final_score_delta", {}) if isinstance(ci.get("adjusted_final_score_delta"), dict) else {}
    )
    role_task_ci = ci.get("role_task_score_delta", {}) if isinstance(ci.get("role_task_score_delta"), dict) else {}
    process_ci = ci.get("process_score_delta", {}) if isinstance(ci.get("process_score_delta"), dict) else {}
    win_ci = ci.get("target_win_rate_delta", {}) if isinstance(ci.get("target_win_rate_delta"), dict) else {}

    return {
        "generated_at": generated_at or now_iso(),
        "report_type": "target_seat_trackc_real_llm_pilot",
        "claim_scope": claim_scope(payload, comparison),
        "source": rel(source_path),
        "raw_source_is_tracked": False,
        "runner": payload.get("runner"),
        "target_role": payload.get("target_role"),
        "target_occurrence": payload.get("target_occurrence"),
        "player_count": payload.get("player_count"),
        "max_days": payload.get("max_days"),
        "baseline_framework": payload.get("baseline_framework"),
        "candidate_framework": payload.get("candidate_framework"),
        "model_pool": payload.get("model_pool", []),
        "model_assignment_counts": summarize_models(candidate),
        "requested_seeds": payload.get("requested_seeds", []),
        "paired_seeds": comparison.get("paired_seeds", []),
        "games_jsonl": rel(Path(str(payload.get("games_jsonl", "")))) if payload.get("games_jsonl") else "",
        "failures_jsonl": rel(Path(str(payload.get("failures_jsonl", "")))) if payload.get("failures_jsonl") else "",
        "failure_count": len(payload.get("failures", []) if isinstance(payload.get("failures"), list) else []),
        "baseline_completed": comparison.get("baseline_completed"),
        "candidate_completed": comparison.get("candidate_completed"),
        "paired_seed_count": comparison.get("paired_seed_count"),
        "baseline_target_win_rate": comparison.get("baseline_target_win_rate"),
        "candidate_target_win_rate": comparison.get("candidate_target_win_rate"),
        "target_win_rate_delta": comparison.get("target_win_rate_delta"),
        "baseline_target_adjusted_score": comparison.get("baseline_target_adjusted_score"),
        "candidate_target_adjusted_score": comparison.get("candidate_target_adjusted_score"),
        "target_adjusted_score_delta": comparison.get("target_adjusted_score_delta"),
        "target_role_task_delta": comparison.get("target_role_task_delta"),
        "target_process_score_delta": comparison.get("target_process_score_delta"),
        "positive_adjusted_score_delta_seeds": comparison.get("positive_adjusted_score_delta_seeds"),
        "positive_role_task_delta_seeds": comparison.get("positive_role_task_delta_seeds"),
        "positive_win_delta_seeds": comparison.get("positive_win_delta_seeds"),
        "candidate_decision_count": comparison.get("candidate_decision_count"),
        "candidate_fallback_count": comparison.get("candidate_fallback_count"),
        "candidate_invalid_count": comparison.get("candidate_invalid_count"),
        "candidate_invalid_rate": comparison.get("candidate_invalid_rate"),
        "bootstrap_ci": {
            "adjusted_final_score_delta": adjusted_ci,
            "role_task_score_delta": role_task_ci,
            "process_score_delta": process_ci,
            "target_win_rate_delta": win_ci,
        },
        "acceptance": acceptance,
        "acceptance_gate_summary": {
            "enough_samples": bool(gates.get("enough_samples", False)),
            "strict_health": bool(gates.get("strict_health", False)),
            "score_gate": bool(gates.get("score_gate", False)),
            "role_task_gate": bool(gates.get("role_task_gate", False)),
            "win_gate": bool(gates.get("win_gate", False)),
            "ci_gate": bool(gates.get("ci_gate", False)),
            "improvement_gate": bool(gates.get("improvement_gate", False)),
        },
        "paired_rows": paired_rows,
        "can_write": [
            "真实 LLM target-seat paired A/B runner 已在 Seer 目标席位上跑通。",
            "本 pilot 中 baseline/candidate 各完成 5 局，candidate fallback/invalid 为 0。",
            "candidate 相对 baseline 的目标席位 adjusted/process/role-task 指标呈正向均值趋势。",
        ],
        "cannot_write": [
            "不能写成 Track C 已经获得单目标席位因果增益。",
            "不能写成 Track C 已经提升最终胜率。",
            "不能把 5 paired seeds pilot 替代 80-120 paired seeds 的正式验证。",
        ],
        "claim_boundary": (
            "该 pilot 是真实 LLM target-seat A/B 阶段性证据。由于 bootstrap CI 下界仍跨 0，"
            "acceptance.accepted=false，只能写成正向趋势和链路健康，不能写成 causal_supported。"
        ),
        "next_required_experiment": (
            "先扩到 20 paired seeds 作为 pipeline pilot；若趋势和健康门禁保持，再按功效计划扩到 "
            "80-120 paired seeds，并轮换 Seer/Witch/Guard/Werewolf/Hunter/Villager。"
        ),
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(facts: dict[str, Any]) -> str:
    acceptance = facts.get("acceptance", {}) if isinstance(facts.get("acceptance"), dict) else {}
    gate_summary = facts.get("acceptance_gate_summary", {})
    ci = facts.get("bootstrap_ci", {}) if isinstance(facts.get("bootstrap_ci"), dict) else {}
    lines = [
        "# Target-seat Track C 真实 LLM Pilot 证据",
        "",
        f"生成时间：{facts['generated_at']}",
        "",
        "本文档汇总当前可用的 target-seat Track C 真实 LLM paired A/B pilot。它是 Track C 因果验证的阶段性证据，不是最终因果证明。",
        "",
        "```mermaid",
        "flowchart LR",
        "    accTitle: Target Seat Track C Pilot",
        "    accDescr: This diagram shows a paired target-seat A/B setup where only one target agent uses Track C while all other seats remain baseline.",
        "    seed[Same Seed / Same Roster] --> base[Baseline Game: all seats basic_react]",
        "    seed --> cand[Candidate Game: target seat rag_react]",
        "    base --> score[Target Seat Scores]",
        "    cand --> score",
        "    score --> delta[Paired Deltas]",
        "    delta --> gates[Acceptance Gates]",
        "    gates --> report[Tracked Pilot Evidence]",
        "```",
        "",
        "## 1. 实验定位",
        "",
        markdown_table(
            ["项目", "值"],
            [
                ["Source", facts["source"]],
                ["Raw source tracked", facts["raw_source_is_tracked"]],
                ["Claim scope", facts["claim_scope"]],
                ["Runner", facts["runner"]],
                ["Target role", facts["target_role"]],
                ["Baseline -> Candidate", f"{facts['baseline_framework']} -> {facts['candidate_framework']}"],
                ["Player count / max days", f"{facts['player_count']} / {facts['max_days']}"],
                ["Model pool", ", ".join(facts.get("model_pool", []))],
            ],
        ),
        "",
        "## 2. 核心结果",
        "",
        markdown_table(
            ["Metric", "Value", "Interpretation"],
            [
                [
                    "Paired seeds",
                    facts["paired_seed_count"],
                    "5-pair pilot，未达到 20-pair pipeline pilot 或 80+ formal 建议规模。",
                ],
                [
                    "Completed baseline/candidate",
                    f"{facts['baseline_completed']} / {facts['candidate_completed']}",
                    "两侧均完成。",
                ],
                ["Adjusted delta", fmt(facts["target_adjusted_score_delta"]), "目标席位均值正向趋势。"],
                ["Role-task delta", fmt(facts["target_role_task_delta"]), "目标角色任务分均值正向趋势。"],
                ["Process delta", fmt(facts["target_process_score_delta"]), "过程分均值正向趋势。"],
                [
                    "Target win delta",
                    fmt(facts["target_win_rate_delta"]),
                    "本 pilot 中胜率没有变化，胜率只作辅助指标。",
                ],
                ["Candidate decisions", facts["candidate_decision_count"], "candidate 侧真实决策数。"],
                [
                    "Fallback / invalid",
                    f"{facts['candidate_fallback_count']} / {facts['candidate_invalid_count']}",
                    "健康门禁通过。",
                ],
                ["Accepted", acceptance.get("accepted"), acceptance.get("claim_level")],
            ],
        ),
        "",
        "## 3. Bootstrap CI 与验收门禁",
        "",
        markdown_table(
            ["Delta", "Mean", "CI95Low", "CI95High", "CI crosses zero"],
            [
                [
                    "adjusted_final_score",
                    fmt(ci.get("adjusted_final_score_delta", {}).get("mean")),
                    fmt(ci.get("adjusted_final_score_delta", {}).get("ci95_low")),
                    fmt(ci.get("adjusted_final_score_delta", {}).get("ci95_high")),
                    fnum(ci.get("adjusted_final_score_delta", {}).get("ci95_low")) <= 0,
                ],
                [
                    "role_task_score",
                    fmt(ci.get("role_task_score_delta", {}).get("mean")),
                    fmt(ci.get("role_task_score_delta", {}).get("ci95_low")),
                    fmt(ci.get("role_task_score_delta", {}).get("ci95_high")),
                    fnum(ci.get("role_task_score_delta", {}).get("ci95_low")) <= 0,
                ],
                [
                    "process_score",
                    fmt(ci.get("process_score_delta", {}).get("mean")),
                    fmt(ci.get("process_score_delta", {}).get("ci95_low")),
                    fmt(ci.get("process_score_delta", {}).get("ci95_high")),
                    fnum(ci.get("process_score_delta", {}).get("ci95_low")) <= 0,
                ],
                [
                    "target_win_rate",
                    fmt(ci.get("target_win_rate_delta", {}).get("mean")),
                    fmt(ci.get("target_win_rate_delta", {}).get("ci95_low")),
                    fmt(ci.get("target_win_rate_delta", {}).get("ci95_high")),
                    fnum(ci.get("target_win_rate_delta", {}).get("ci95_low")) <= 0,
                ],
            ],
        ),
        "",
        markdown_table(
            ["Gate", "Passed"],
            [[key, value] for key, value in gate_summary.items()],
        ),
        "",
        "解释：score、role-task、health 和 improvement gate 均通过，但 CI gate 未通过，因此 `accepted=false`，`claim_level=ci_not_positive`。",
        "",
        "## 4. Paired Seed 明细",
        "",
        markdown_table(
            [
                "Seed",
                "Seat",
                "BaseWinner",
                "CandWinner",
                "AdjustedDelta",
                "RoleTaskDelta",
                "ProcessDelta",
                "CandDecisions",
                "CandFallback",
                "CandInvalid",
            ],
            [
                [
                    row["seed"],
                    row["target_seat"],
                    row["baseline_winner"],
                    row["candidate_winner"],
                    fmt(row["adjusted_delta"]),
                    fmt(row["role_task_delta"]),
                    fmt(row["process_delta"]),
                    row["candidate_decisions"],
                    row["candidate_fallback"],
                    row["candidate_invalid"],
                ]
                for row in facts.get("paired_rows", [])
            ],
        ),
        "",
        "## 5. 可写结论与边界",
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
        markdown_table(["说明"], [[facts["claim_boundary"]], [facts["next_required_experiment"]]]),
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--generated-at", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_at = args.generated_at or existing_generated_at(args.output_json)
    facts = build_facts(source_path=args.source, generated_at=generated_at)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_report(facts), encoding="utf-8")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_md}")


if __name__ == "__main__":
    main()
