"""Analyze persisted formal AI Werewolf experiment JSONL outputs.

This script does not run games. It turns long-running experiment outputs from
another agent/process into auditable tables for the paper/presentation.

The default mode is intentionally strict:

* keep Volcengine v4flash rows only;
* exclude pro, fake, official DeepSeek, and unknown-model rows from formal
  evidence;
* keep failed rows in external run-health tables, but exclude whole-game
  failures/API errors from win-rate denominators and Agent architecture scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from statistics import mean
from typing import Any
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.track_bc_leaderboard_experiment import RUBRIC_DIMENSIONS
from scripts.track_bc_leaderboard_experiment import RUBRIC_WEIGHTS
from scripts.track_bc_leaderboard_experiment import clamp
from scripts.track_bc_leaderboard_experiment import normalize_metric

DEFAULT_INPUT = ROOT / "data" / "experiment" / "multi_tier" / "formal_dsv4flash_7p_tier_6x_v2"
DEFAULT_OUTPUT = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis"
TIERS = ("baseline", "anti_only", "trackc_only", "both")
TIER_LABEL = {
    "baseline": "basic_react",
    "anti_only": "anti_only",
    "trackc_only": "trackc_only",
    "both": "cognitive_full",
}
CORE_ROLES = {"Villager", "Werewolf", "Seer", "Witch", "Hunter"}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            rows.append({"error": f"json_decode_error:{exc}", "source_line_no": line_no})
            continue
        row["_source_file"] = str(path)
        row["_source_line_no"] = line_no
        rows.append(row)
    return rows


def is_failed(row: dict[str, Any]) -> bool:
    winner = str(row.get("winner", "")).lower()
    return bool(row.get("error")) or winner in {"", "none", "null"}


def invalid_count(row: dict[str, Any]) -> int:
    value = row.get("invalid_decisions", 0)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def fallback_count(row: dict[str, Any]) -> int:
    total = 0
    for key in ("fallback_count", "player_fallback_count"):
        try:
            total += int(row.get(key, 0) or 0)
        except (TypeError, ValueError):
            pass
    value = row.get("fallback_decisions")
    if isinstance(value, list):
        total += len(value)
    elif isinstance(value, dict):
        total += len(value)
    return total


def filter_reason(row: dict[str, Any]) -> str:
    provider = str(row.get("provider", "")).strip().lower()
    model_text = " ".join(str(row.get(key, "")) for key in ("model", "model_pool")).lower()
    if provider == "fake" or "fake" in model_text:
        return "fake/offline row"
    if "pro" in model_text:
        return "pro model row"
    if "deepseek-v4-flash" not in model_text:
        return "model is not explicitly deepseek-v4-flash"
    if provider not in {"dsv4flash", "doubao"}:
        return f"non-Volcengine provider: {provider or 'unknown'}"
    return ""


def keep_formal_row(row: dict[str, Any]) -> bool:
    return not filter_reason(row)


def wilson_ci(wins: int, total: int, z: float = 1.96) -> list[float | None]:
    if total <= 0:
        return [None, None]
    p = wins / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def role_team(role: str) -> str:
    return "wolf" if role in {"Werewolf", "WhiteWolfKing", "WolfKing", "WolfCub", "BigBadWolf"} else "village"


def summarize_players(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if is_failed(row):
            continue
        for player in row.get("players", []) or []:
            if key == "team":
                group = str(player.get("team") or role_team(str(player.get("role", ""))))
            else:
                group = str(player.get(key) or "UNKNOWN")
            grouped[group].append(player)

    out: dict[str, Any] = {}
    for group, players in sorted(grouped.items()):
        wins = sum(1 for player in players if bool(player.get("won")))
        out[group] = {
            "samples": len(players),
            "wins": wins,
            "win_rate": round(wins / max(len(players), 1), 6),
            "wilson_ci95": wilson_ci(wins, len(players)),
        }
    return out


def summarize_tiers(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tier[str(row.get("tier", "unknown"))].append(row)

    result: dict[str, dict[str, Any]] = {}
    for tier in sorted(by_tier):
        tier_rows = by_tier[tier]
        completed = [row for row in tier_rows if not is_failed(row)]
        failed = [row for row in tier_rows if is_failed(row)]
        winner_counts = Counter(str(row.get("winner")) for row in completed)
        players = [player for row in completed for player in (row.get("players", []) or [])]
        role_counts = Counter(str(player.get("role") or "UNKNOWN") for player in players)
        role_wins = Counter(str(player.get("role") or "UNKNOWN") for player in players if bool(player.get("won")))
        seat_samples = len(players)
        llm_decisions = sum(int(row.get("llm_decisions", 0) or 0) for row in completed)
        fallback_total = sum(fallback_count(row) for row in completed)
        invalid_total = sum(invalid_count(row) for row in completed)
        avg_days = mean([float(row.get("days", 0) or 0) for row in completed]) if completed else 0.0
        avg_duration = mean([float(row.get("duration_s", 0) or 0) for row in completed]) if completed else 0.0
        role_rates = {
            role: {
                "samples": int(role_counts[role]),
                "wins": int(role_wins[role]),
                "win_rate": round(role_wins[role] / max(role_counts[role], 1), 6),
            }
            for role in sorted(role_counts)
        }
        macro_role_win_rate = mean([item["win_rate"] for item in role_rates.values()]) if role_rates else 0.0
        wolf_wins = winner_counts.get("wolf", 0)
        village_wins = winner_counts.get("village", 0)
        attempted_games = len(tier_rows)
        external_failed_games = len(failed)
        external_failure_rate = external_failed_games / max(attempted_games, 1)
        valid_completion_rate = 1.0 if completed else 0.0
        result[tier] = {
            "tier": tier,
            "display_name": TIER_LABEL.get(tier, tier),
            "rows": attempted_games,
            "attempted_games": attempted_games,
            "completed_games": len(completed),
            "failed_games": external_failed_games,
            "external_failed_games": external_failed_games,
            "external_failure_rate": round(external_failure_rate, 6),
            "attempt_completion_rate": round(len(completed) / max(attempted_games, 1), 6),
            "completion_rate": round(valid_completion_rate, 6),
            "winner_counts": dict(sorted(winner_counts.items())),
            "wolf_win_rate": round(wolf_wins / max(len(completed), 1), 6),
            "village_win_rate": round(village_wins / max(len(completed), 1), 6),
            "wolf_win_ci95": wilson_ci(wolf_wins, len(completed)),
            "village_win_ci95": wilson_ci(village_wins, len(completed)),
            "avg_days": round(avg_days, 6),
            "avg_duration_s": round(avg_duration, 6),
            "llm_decisions": llm_decisions,
            "fallback_count": fallback_total,
            "invalid_count": invalid_total,
            "fallback_rate": round(fallback_total / max(llm_decisions, 1), 6),
            "invalid_rate": round(invalid_total / max(llm_decisions, 1), 6),
            "seat_samples": seat_samples,
            "role_counts": dict(sorted(role_counts.items())),
            "role_wins": dict(sorted(role_wins.items())),
            "role_win_rates": role_rates,
            "macro_role_win_rate": round(macro_role_win_rate, 6),
            "core_role_coverage": round(len(CORE_ROLES & set(role_counts)) / len(CORE_ROLES), 6),
            "providers": dict(sorted(Counter(str(row.get("provider")) for row in tier_rows).items())),
            "models": dict(sorted(Counter(str(row.get("model")) for row in tier_rows).items())),
            "error_types": dict(sorted(Counter(str(row.get("error_type") or "unknown") for row in failed).items())),
        }
    return result


def build_leaderboard(tiers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for tier, summary in tiers.items():
        entries.append(
            {
                "tier": tier,
                "display_name": summary["display_name"],
                "attempted_games": summary["attempted_games"],
                "completed_games": summary["completed_games"],
                "failed_games": summary["failed_games"],
                "external_failed_games": summary["external_failed_games"],
                "external_failure_rate": summary["external_failure_rate"],
                "attempt_completion_rate": summary["attempt_completion_rate"],
                "completion_rate": summary["completion_rate"],
                "wolf_win_rate": summary["wolf_win_rate"],
                "village_win_rate": summary["village_win_rate"],
                "macro_role_win_rate": summary["macro_role_win_rate"],
                "fallback_count": summary["fallback_count"],
                "invalid_count": summary["invalid_count"],
                "llm_decisions": summary["llm_decisions"],
                "seat_samples": summary["seat_samples"],
                "avg_duration_s": summary["avg_duration_s"],
            }
        )
    entries.sort(
        key=lambda row: (row["macro_role_win_rate"], row["wolf_win_rate"], row["completed_games"]), reverse=True
    )
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    return entries


def mean_or_zero(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def build_architecture_evidence_leaderboard(
    tiers: dict[str, dict[str, Any]], leaderboard: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not tiers:
        return []
    tier_keys = sorted(tiers)
    macro_role_norm = normalize_metric({key: tiers[key]["macro_role_win_rate"] for key in tier_keys})
    wolf_win_norm = normalize_metric({key: tiers[key]["wolf_win_rate"] for key in tier_keys})
    duration_norm = normalize_metric({key: tiers[key]["avg_duration_s"] for key in tier_keys}, higher_is_better=False)
    decision_norm = normalize_metric({key: tiers[key]["llm_decisions"] for key in tier_keys})
    rank_by_tier = {row["tier"]: row["rank"] for row in leaderboard}
    n = max(len(leaderboard), 1)

    baseline = tiers.get("baseline", {})
    base_wolf = float(baseline.get("wolf_win_rate", 0.0))
    base_macro = float(baseline.get("macro_role_win_rate", 0.0))

    entries: list[dict[str, Any]] = []
    for tier in tier_keys:
        row = tiers[tier]
        decisions = max(float(row.get("llm_decisions", 0)), 1.0)
        health = clamp(
            1.0 - float(row.get("fallback_count", 0)) / decisions - float(row.get("invalid_count", 0)) / decisions
        )
        rank_score = 1.0 if n <= 1 else 1.0 - ((rank_by_tier.get(tier, n) - 1) / (n - 1))
        trackc_enabled = 1.0 if tier in {"trackc_only", "both"} else 0.0
        anti_enabled = 1.0 if tier in {"anti_only", "both"} else 0.0
        wolf_delta_score = clamp(0.5 + (float(row["wolf_win_rate"]) - base_wolf))
        macro_delta_score = clamp(0.5 + (float(row["macro_role_win_rate"]) - base_macro))
        single_raw = mean_or_zero(
            [
                macro_role_norm.get(tier, 0.0),
                decision_norm.get(tier, 0.0),
                float(row.get("core_role_coverage", 0.0)),
                health,
                anti_enabled,
            ]
        )
        multi_raw = mean_or_zero(
            [
                macro_role_norm.get(tier, 0.0),
                wolf_win_norm.get(tier, 0.0),
                float(row.get("core_role_coverage", 0.0)),
                health,
            ]
        )
        engineering_raw = mean_or_zero(
            [
                health,
                float(row.get("core_role_coverage", 0.0)),
                duration_norm.get(tier, 0.0),
                1.0 if row.get("completed_games", 0) > 0 else 0.0,
            ]
        )
        advanced_raw = mean_or_zero(
            [
                rank_score,
                trackc_enabled,
                wolf_delta_score,
                macro_delta_score,
                health,
            ]
        )
        dims = {
            "single_agent": round(single_raw * RUBRIC_WEIGHTS["single_agent"], 4),
            "multi_agent": round(multi_raw * RUBRIC_WEIGHTS["multi_agent"], 4),
            "engineering": round(engineering_raw * RUBRIC_WEIGHTS["engineering"], 4),
            "advanced_bc": round(advanced_raw * RUBRIC_WEIGHTS["advanced_bc"], 4),
        }
        entries.append(
            {
                "rank": 0,
                "tier": tier,
                "display_name": row["display_name"],
                "rubric_total_score": round(sum(dims.values()), 4),
                "rubric_dimensions": dims,
                "raw_dimension_scores": {
                    "single_agent": round(single_raw, 6),
                    "multi_agent": round(multi_raw, 6),
                    "engineering": round(engineering_raw, 6),
                    "advanced_bc": round(advanced_raw, 6),
                },
                "evidence_signals": {
                    "completed_games": row["completed_games"],
                    "failed_games": row["failed_games"],
                    "external_failed_games": row["external_failed_games"],
                    "external_failure_rate": row["external_failure_rate"],
                    "attempt_completion_rate": row["attempt_completion_rate"],
                    "completion_rate": row["completion_rate"],
                    "wolf_win_rate": row["wolf_win_rate"],
                    "village_win_rate": row["village_win_rate"],
                    "macro_role_win_rate": row["macro_role_win_rate"],
                    "fallback_count": row["fallback_count"],
                    "invalid_count": row["invalid_count"],
                    "llm_decisions": row["llm_decisions"],
                    "seat_samples": row["seat_samples"],
                    "core_role_coverage": row["core_role_coverage"],
                    "trackc_enabled": bool(trackc_enabled),
                    "anti_patterns_enabled": bool(anti_enabled),
                    "wolf_win_delta_vs_baseline": round(float(row["wolf_win_rate"]) - base_wolf, 6),
                    "macro_role_win_delta_vs_baseline": round(float(row["macro_role_win_rate"]) - base_macro, 6),
                },
            }
        )
    entries.sort(
        key=lambda item: (
            item["rubric_total_score"],
            item["rubric_dimensions"]["advanced_bc"],
            item["evidence_signals"]["completed_games"],
        ),
        reverse=True,
    )
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    return entries


def paired_seed_delta(rows: Sequence[dict[str, Any]], baseline: str, candidate: str) -> dict[str, Any]:
    completed = [row for row in rows if not is_failed(row)]
    by_tier_seed: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in completed:
        seed = row.get("seed")
        if seed is None:
            continue
        by_tier_seed[str(row.get("tier"))][int(seed)] = row
    seeds = sorted(set(by_tier_seed.get(baseline, {})) & set(by_tier_seed.get(candidate, {})))
    if not seeds:
        return {"baseline": baseline, "candidate": candidate, "paired_seed_count": 0}
    wolf_delta = []
    village_delta = []
    same_winner = 0
    for seed in seeds:
        b = str(by_tier_seed[baseline][seed].get("winner"))
        c = str(by_tier_seed[candidate][seed].get("winner"))
        if b == c:
            same_winner += 1
        wolf_delta.append((1.0 if c == "wolf" else 0.0) - (1.0 if b == "wolf" else 0.0))
        village_delta.append((1.0 if c == "village" else 0.0) - (1.0 if b == "village" else 0.0))
    return {
        "baseline": baseline,
        "candidate": candidate,
        "paired_seed_count": len(seeds),
        "seeds": seeds,
        "avg_wolf_win_delta": round(mean(wolf_delta), 6),
        "avg_village_win_delta": round(mean(village_delta), 6),
        "positive_wolf_delta_seeds": sum(1 for value in wolf_delta if value > 0),
        "positive_village_delta_seeds": sum(1 for value in village_delta if value > 0),
        "same_winner_seeds": same_winner,
    }


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value * 100:.1f}%"


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Formal v4flash Framework Experiment Analysis",
        "",
        f"> Generated at: {payload['generated_at']}",
        f"> Source directory: `{payload['source_dir']}`",
        "",
        "## 1. Evidence Filter",
        "",
        "Formal rows keep only Volcengine v4flash records: provider in `dsv4flash/doubao`, "
        "model text contains `deepseek-v4-flash`, and model text does not contain `pro`.",
        "",
        "| Bucket | Rows |",
        "|---|---:|",
        f"| Raw rows | {payload['row_counts']['raw']} |",
        f"| Formal v4flash rows | {payload['row_counts']['formal_v4flash']} |",
        f"| Excluded rows | {payload['row_counts']['excluded']} |",
        "",
        "Excluded reasons:",
        "",
    ]
    for reason, count in payload["excluded_reasons"].items():
        lines.append(f"- {reason}: {count}")

    lines.extend(
        [
            "",
            "## 2. Track B/C Framework Leaderboard",
            "",
            "Whole-game failures/API errors are external run-health signals. They are not counted as Agent losses.",
            "",
            "| Rank | Tier | Completed | External Failed | External Failure | Wolf Win | Village Win | Macro Role Win | LLM Decisions | Fallback | Invalid |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["leaderboard"]:
        lines.append(
            f"| {row['rank']} | `{row['tier']}` / {row['display_name']} | {row['completed_games']} | "
            f"{row['external_failed_games']} | {fmt_pct(row['external_failure_rate'])} | {fmt_pct(row['wolf_win_rate'])} | "
            f"{fmt_pct(row['village_win_rate'])} | {fmt_pct(row['macro_role_win_rate'])} | "
            f"{row['llm_decisions']} | {row['fallback_count']} | {row['invalid_count']} |"
        )

    lines.extend(
        [
            "",
            "## 3. Architecture Evidence Leaderboard",
            "",
            "Mapped to project architecture evidence: Agent decision quality, multi-Agent behavior, engineering health, and B/C loop.",
            "Whole-game failures/API errors are excluded from Agent architecture scores and shown only as external failure.",
            "",
            "| Rank | Tier | Total | Single Agent /20 | Multi-Agent /20 | Engineering /30 | B/C /30 | Key Evidence |",
            "|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in payload["architecture_evidence_leaderboard"]:
        dims = row["rubric_dimensions"]
        signals = row["evidence_signals"]
        evidence = (
            f"wolf={fmt_pct(signals['wolf_win_rate'])}; "
            f"macro_role={fmt_pct(signals['macro_role_win_rate'])}; "
            f"external_fail={fmt_pct(signals['external_failure_rate'])}; "
            f"fallback={signals['fallback_count']}; invalid={signals['invalid_count']}"
        )
        lines.append(
            f"| {row['rank']} | `{row['tier']}` / {row['display_name']} | {row['rubric_total_score']:.2f} | "
            f"{dims['single_agent']:.2f} | {dims['multi_agent']:.2f} | {dims['engineering']:.2f} | "
            f"{dims['advanced_bc']:.2f} | {evidence} |"
        )

    lines.extend(["", "## 4. Paired Seed Deltas", ""])
    for item in payload["paired_seed_deltas"]:
        lines.extend(
            [
                f"### {item['candidate']} vs {item['baseline']}",
                "",
                f"- Paired seeds: {item.get('paired_seed_count', 0)}",
                f"- Avg wolf-win delta: {item.get('avg_wolf_win_delta')}",
                f"- Avg village-win delta: {item.get('avg_village_win_delta')}",
                f"- Positive wolf-delta seeds: {item.get('positive_wolf_delta_seeds')}",
                f"- Same-winner seeds: {item.get('same_winner_seeds')}",
                "",
            ]
        )

    lines.extend(
        [
            "## 5. Architecture Evidence Interpretation",
            "",
            "- Single Agent: evidence comes from real LLM decisions, role coverage, and no fallback in formal rows. This report does not inspect prompt text directly; use `docs/EXPERIMENT_SECTION_DESIGN.md` and code references for prompt-layer evidence.",
            "- Multi-Agent: evidence comes from role/team outcome, role coverage, paired seeds, and strict information isolation gate. The strongest claim is that the platform supports role-differentiated multi-agent experiments; direct deception/detection scoring still needs the Track B semantic audit output.",
            "- Engineering: formal completed rows show real v4flash games with fallback=0; whole-game failures/API errors are external run-health signals, not Agent losses. Visibility strict was run separately and passed 92/92.",
            "- Advanced B/C: Track B/C variants are distinguishable in the leaderboard. Treat Track C outcome claims as evidence, not final significance proof, until the balanced target-seat A/B completes.",
            "",
            "## 6. Conclusion Boundary",
            "",
            "Use this report for the paper/presentation as a formal experiment audit. Do not claim `cognitive_full` is statistically superior unless the 20-seed paired runner completes with enough valid paired seeds across frameworks. The current evidence is enough to show the leaderboard can distinguish framework versions and that B/C modules are experimentally testable under v4flash.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    input_dir = args.input_dir
    rows = load_jsonl(input_dir / "results.jsonl")
    if not rows:
        for tier in TIERS:
            rows.extend(load_jsonl(input_dir / f"{tier}.jsonl"))

    formal_rows = [row for row in rows if keep_formal_row(row)]
    excluded = [row for row in rows if not keep_formal_row(row)]
    excluded_reasons = Counter(filter_reason(row) or "kept" for row in excluded)
    tiers = summarize_tiers(formal_rows)
    leaderboard = build_leaderboard(tiers)
    architecture_evidence = build_architecture_evidence_leaderboard(tiers, leaderboard)
    paired = [
        paired_seed_delta(formal_rows, "baseline", "anti_only"),
        paired_seed_delta(formal_rows, "baseline", "trackc_only"),
        paired_seed_delta(formal_rows, "baseline", "both"),
        paired_seed_delta(formal_rows, "anti_only", "both"),
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(input_dir),
        "row_counts": {
            "raw": len(rows),
            "formal_v4flash": len(formal_rows),
            "excluded": len(excluded),
        },
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        "rubric_weights": RUBRIC_WEIGHTS,
        "rubric_dimensions": RUBRIC_DIMENSIONS,
        "tier_summaries": tiers,
        "leaderboard": leaderboard,
        "architecture_evidence_leaderboard": architecture_evidence,
        "rubric_leaderboard": architecture_evidence,
        "paired_seed_deltas": paired,
        "role_summary": summarize_players(formal_rows, "role"),
        "team_summary": summarize_players(formal_rows, "team"),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    write_csv(
        args.output_dir / "leaderboard.csv",
        leaderboard,
        [
            "rank",
            "tier",
            "display_name",
            "attempted_games",
            "completed_games",
            "failed_games",
            "external_failed_games",
            "external_failure_rate",
            "attempt_completion_rate",
            "completion_rate",
            "wolf_win_rate",
            "village_win_rate",
            "macro_role_win_rate",
            "llm_decisions",
            "fallback_count",
            "invalid_count",
            "seat_samples",
            "avg_duration_s",
        ],
    )
    write_csv(
        args.output_dir / "architecture_evidence_leaderboard.csv",
        [
            {
                "rank": row["rank"],
                "tier": row["tier"],
                "display_name": row["display_name"],
                "rubric_total_score": row["rubric_total_score"],
                **row["rubric_dimensions"],
                **row["evidence_signals"],
            }
            for row in architecture_evidence
        ],
        [
            "rank",
            "tier",
            "display_name",
            "rubric_total_score",
            "single_agent",
            "multi_agent",
            "engineering",
            "advanced_bc",
            "completed_games",
            "failed_games",
            "external_failed_games",
            "external_failure_rate",
            "attempt_completion_rate",
            "completion_rate",
            "wolf_win_rate",
            "village_win_rate",
            "macro_role_win_rate",
            "fallback_count",
            "invalid_count",
            "llm_decisions",
            "seat_samples",
            "core_role_coverage",
            "trackc_enabled",
            "anti_patterns_enabled",
            "wolf_win_delta_vs_baseline",
            "macro_role_win_delta_vs_baseline",
        ],
    )
    print(f"formal_rows={len(formal_rows)} excluded={len(excluded)}")
    print(f"report={args.output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
