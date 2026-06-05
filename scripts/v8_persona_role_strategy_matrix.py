#!/usr/bin/env python3
"""V8 Persona × Role × Strategy Matrix Generator.

Reads game results (from V8 A/B test or production games) and generates
a three-dimensional evaluation matrix: Persona × Role × Strategy.

Usage:
  python scripts/v8_persona_role_strategy_matrix.py \
    --input data/health/strategy_ab_test_results_v8.csv \
    --output-csv data/health/persona_role_strategy_matrix_v8.csv \
    --output-md data/health/persona_role_strategy_analysis_v8.md
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def build_matrix(input_csv: str) -> list[dict]:
    """Read game results and build the persona×role×strategy matrix."""
    rows = []
    with open(input_csv, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Group by (persona_name, role, strategy_id)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["persona_name"], row["role"], row["strategy_id"])
        groups[key].append(row)

    matrix = []
    for (persona_name, role, strategy_id), group_rows in sorted(groups.items()):
        n = len(group_rows)
        wins = sum(1 for r in group_rows if r["is_win"].lower() == "true")
        raw_wr = wins / n if n > 0 else 0.0

        # Confidence level
        if n < 5:
            confidence = "INSUFFICIENT"
            reason = f"n={n}<5"
        elif n < 10:
            confidence = "LOW_SAMPLE"
            reason = f"n={n}<10"
        else:
            confidence = "MEDIUM"
            reason = ""

        matrix.append(
            {
                "persona_name": persona_name,
                "role": role,
                "strategy_id": strategy_id,
                "strategy_name": group_rows[0].get("strategy_name", ""),
                "n": n,
                "raw_win_rate": round(raw_wr, 4),
                "adjusted_win_lift": "",  # requires camp baseline
                "avg_role_normalized_pre_action_score": "",  # requires V7 scoring
                "confidence_level": confidence,
                "low_confidence_reason": reason,
            }
        )

    return matrix


def write_csv(matrix: list[dict], output_csv: str) -> None:
    fields = [
        "persona_name",
        "role",
        "strategy_id",
        "strategy_name",
        "n",
        "raw_win_rate",
        "adjusted_win_lift",
        "avg_role_normalized_pre_action_score",
        "confidence_level",
        "low_confidence_reason",
    ]
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in matrix:
            writer.writerow({k: row.get(k, "") for k in fields})


def write_md(matrix: list[dict], output_md: str) -> None:
    lines = [
        "# Persona × Role × Strategy Analysis V8",
        "",
        "## Summary",
        f"Total persona×role×strategy groups: {len(matrix)}",
        "",
        "## Matrix",
        "",
        "| Persona | Role | Strategy | N | Win Rate | Confidence |",
        "|---------|------|----------|---|----------|------------|",
    ]
    for row in matrix:
        conf_flag = "⚠️ " if row["confidence_level"] in ("LOW_SAMPLE", "INSUFFICIENT") else ""
        lines.append(
            f"| {row['persona_name']} | {row['role']} | "
            f"{row['strategy_name']} | {row['n']} | "
            f"{row['raw_win_rate']:.3f} | {conf_flag}{row['confidence_level']} |"
        )

    lines += [
        "",
        "## Rules",
        "- n < 5: INSUFFICIENT — no conclusion",
        "- 5 ≤ n < 10: LOW_SAMPLE — indicative only",
        "- n ≥ 10: can draw tentative conclusions",
        "- Do NOT say one strategy is 'best'; say 'under current sample, X outperforms Y'",
        "",
        "## Notes",
        "- Role-action LOW_CONF (Witch Save, Seer Release, Hunter Shot) → related strategy downgraded",
        "- Scores are RANKING only, not probability",
        "- This is Persona × Role × Strategy (three-layer) evaluation",
    ]

    Path(output_md).parent.mkdir(parents=True, exist_ok=True)
    with open(output_md, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V8 Persona×Role×Strategy Matrix")
    parser.add_argument("--input", required=True, help="Game results CSV (from v8_strategy_ab_test.py)")
    parser.add_argument("--output-csv", default="data/health/persona_role_strategy_matrix_v8.csv")
    parser.add_argument("--output-md", default="data/health/persona_role_strategy_analysis_v8.md")
    args = parser.parse_args()

    matrix = build_matrix(args.input)
    write_csv(matrix, args.output_csv)
    write_md(matrix, args.output_md)
    print(f"Matrix: {len(matrix)} groups → {args.output_csv}, {args.output_md}")
