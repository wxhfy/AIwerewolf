"""Analyze player-level MBTI/role Track C experiment outputs.

The input files contain one row per player with role, MBTI, win flag, Track C
flag, and seed. They are useful for role/persona coverage and Track C trend
slides, but they do not include provider/model metadata, so the report marks
them as auxiliary evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUTS = [
    ROOT / "data" / "experiment" / "mbti_batch_baseline.jsonl",
    ROOT / "data" / "experiment" / "mbti_batch_trackc.jsonl",
    ROOT / "data" / "experiment" / "mbti_role_track_c_v2.jsonl",
]
DEFAULT_OUTPUT = ROOT / "docs" / "experiments" / "mbti_track_c_auxiliary_analysis"


def load_rows(paths: Sequence[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for path in paths:
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_source_file"] = str(path)
            row["_source_line_no"] = line_no
            key = (row.get("seed"), row.get("track_c"), row.get("role"), row.get("mbti"), row.get("won"), str(path))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def summarize(rows: Sequence[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        group = key_fn(row)
        grouped[group].append(row)
    out: dict[str, Any] = {}
    for group, bucket in sorted(grouped.items()):
        wins = sum(1 for row in bucket if bool(row.get("won")))
        out[group] = {
            "samples": len(bucket),
            "wins": wins,
            "win_rate": round(wins / max(len(bucket), 1), 6),
            "seed_count": len({row.get("seed") for row in bucket}),
        }
    return out


def track_c_deltas(rows: Sequence[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    if key_name == "role":

        def key_fn(row: dict[str, Any]) -> str:
            return str(row.get("role") or "UNKNOWN")

    elif key_name == "mbti":

        def key_fn(row: dict[str, Any]) -> str:
            return str(row.get("mbti") or "UNKNOWN")

    elif key_name == "role_mbti":

        def key_fn(row: dict[str, Any]) -> str:
            return f"{row.get('role') or 'UNKNOWN'}+{row.get('mbti') or 'UNKNOWN'}"

    else:
        raise ValueError(key_name)

    grouped: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(key_fn(row), bool(row.get("track_c")))].append(row)
    keys = sorted({key for key, _ in grouped})
    result: list[dict[str, Any]] = []
    for key in keys:
        base = grouped.get((key, False), [])
        tc = grouped.get((key, True), [])
        base_wr = sum(1 for row in base if bool(row.get("won"))) / max(len(base), 1)
        tc_wr = sum(1 for row in tc if bool(row.get("won"))) / max(len(tc), 1)
        result.append(
            {
                "key": key,
                "baseline_samples": len(base),
                "track_c_samples": len(tc),
                "baseline_win_rate": round(base_wr, 6) if base else None,
                "track_c_win_rate": round(tc_wr, 6) if tc else None,
                "delta": round(tc_wr - base_wr, 6) if base and tc else None,
            }
        )
    return result


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def pct(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{100 * value:.1f}%"


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# MBTI / Role Track C Auxiliary Analysis",
        "",
        f"> Generated at: {payload['generated_at']}",
        "",
        "This is auxiliary evidence from player-level JSONL files produced by long-running experiments. "
        "Rows contain role, MBTI, win flag, Track C flag, and seed, but not provider/model metadata. "
        "Use it for role/persona coverage and trend slides; do not use it alone as v4flash formal proof.",
        "",
        "## 1. Coverage",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Rows | {payload['row_count']} |",
        f"| Seeds | {payload['seed_count']} |",
        f"| Roles | {payload['role_count']} |",
        f"| MBTI types | {payload['mbti_count']} |",
        f"| Track C off rows | {payload['track_c_counts'].get('False', 0)} |",
        f"| Track C on rows | {payload['track_c_counts'].get('True', 0)} |",
        "",
        "## 2. Track C Delta by Role",
        "",
        "| Role | Baseline n | Track C n | Baseline win | Track C win | Delta |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["role_deltas"]:
        lines.append(
            f"| {row['key']} | {row['baseline_samples']} | {row['track_c_samples']} | "
            f"{pct(row['baseline_win_rate'])} | {pct(row['track_c_win_rate'])} | {pct(row['delta'])} |"
        )
    lines.extend(
        [
            "",
            "## 3. Top MBTI×Role Positive Deltas",
            "",
            "| MBTI×Role | Baseline n | Track C n | Baseline win | Track C win | Delta |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["top_role_mbti_deltas"]:
        lines.append(
            f"| {row['key']} | {row['baseline_samples']} | {row['track_c_samples']} | "
            f"{pct(row['baseline_win_rate'])} | {pct(row['track_c_win_rate'])} | {pct(row['delta'])} |"
        )
    lines.extend(
        [
            "",
            "## 4. Interpretation",
            "",
            "- This dataset supports the presentation claim that the project can analyze role/persona-specific Track C effects.",
            "- It should be paired with the formal v4flash framework analysis for provider/model controlled claims.",
            "- Low-sample MBTI×role cells should be labeled as exploratory.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, dest="inputs")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    inputs = args.inputs or DEFAULT_INPUTS
    rows = load_rows(inputs)
    role_deltas = track_c_deltas(rows, "role")
    role_mbti_deltas = [
        row for row in track_c_deltas(rows, "role_mbti") if row["delta"] is not None and row["baseline_samples"] >= 2
    ]
    role_mbti_deltas.sort(
        key=lambda row: (row["delta"], row["track_c_samples"] + row["baseline_samples"]), reverse=True
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in inputs],
        "row_count": len(rows),
        "seed_count": len({row.get("seed") for row in rows}),
        "role_count": len({row.get("role") for row in rows}),
        "mbti_count": len({row.get("mbti") for row in rows}),
        "track_c_counts": {
            str(key): value for key, value in sorted(Counter(bool(row.get("track_c")) for row in rows).items())
        },
        "overall": summarize(rows, lambda row: "track_c_on" if bool(row.get("track_c")) else "track_c_off"),
        "role_summary": summarize(rows, lambda row: str(row.get("role") or "UNKNOWN")),
        "mbti_summary": summarize(rows, lambda row: str(row.get("mbti") or "UNKNOWN")),
        "role_deltas": role_deltas,
        "top_role_mbti_deltas": role_mbti_deltas[:20],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    write_csv(
        args.output_dir / "role_deltas.csv",
        role_deltas,
        ["key", "baseline_samples", "track_c_samples", "baseline_win_rate", "track_c_win_rate", "delta"],
    )
    write_csv(
        args.output_dir / "role_mbti_deltas.csv",
        role_mbti_deltas,
        ["key", "baseline_samples", "track_c_samples", "baseline_win_rate", "track_c_win_rate", "delta"],
    )
    print(f"rows={len(rows)} report={args.output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
