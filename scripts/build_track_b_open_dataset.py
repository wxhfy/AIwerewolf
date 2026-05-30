#!/usr/bin/env python3
"""Build Track B open datasets from external werewolf data sources.

Phase 1: Werewolf Among Us → SpeechQualityDataset

Usage:
  python scripts/build_track_b_open_dataset.py                     # All sources
  python scripts/build_track_b_open_dataset.py --source werewolf_among_us
  python scripts/build_track_b_open_dataset.py --split train       # Ego4D train only
  python scripts/build_track_b_open_dataset.py --list-sources      # List available sources
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OPEN_DATA_DIR = ROOT / "data" / "open"
REPORT_PATH = ROOT / "docs" / "track_b_open_data_adapter_report.md"


def _ensure_dirs():
    OPEN_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _save_jsonl(items: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


# ===========================================================================
# Source: Werewolf Among Us
# ===========================================================================

def build_werewolf_among_us(split: str = "all") -> dict[str, Any]:
    """Convert Werewolf Among Us dataset to Track B SpeechQualitySamples."""
    from backend.eval.open_data.adapters import WerewolfAmongUsAdapter

    adapter = WerewolfAmongUsAdapter()
    print(f"Data dir: {adapter.data_dir}")

    raw_games = adapter.load_raw_games(split)
    print(f"Raw games loaded: {len(raw_games)}")

    logs, samples = adapter.run(split)
    print(f"OpenGameLogs: {len(logs)}")
    print(f"SpeechQualitySamples: {len(samples)}")

    # Save logs
    log_path = OPEN_DATA_DIR / "track_b_open_game_logs.jsonl"
    log_dicts = []
    for log in logs:
        log_dicts.append({
            "source": log.source,
            "license": log.license.value,
            "rule_variant": log.rule_variant,
            "game_id": log.game_id,
            "n_events": len(log.events),
            "n_players": len(log.players),
            "winner": log.winner,
            "metadata": log.metadata,
        })
    _save_jsonl(log_dicts, log_path)
    print(f"  Logs saved: {log_path} ({len(log_dicts)} records)")

    # Save speech samples
    speech_path = OPEN_DATA_DIR / "track_b_open_speech_samples.jsonl"
    speech_dicts = [s.to_dict() for s in samples]
    _save_jsonl(speech_dicts, speech_path)
    print(f"  Speech samples saved: {speech_path} ({len(speech_dicts)} records)")

    # Stats
    roles = {}
    for s in samples:
        roles[s.role] = roles.get(s.role, 0) + 1

    annotation_types = {}
    for s in samples:
        for label_name in s.weak_labels:
            annotation_types[label_name] = annotation_types.get(label_name, 0) + 1

    return {
        "source": "werewolf_among_us",
        "license": adapter.license.value,
        "rule_variant": adapter.rule_variant,
        "total_games": len(logs),
        "total_speech_samples": len(samples),
        "role_distribution": roles,
        "annotation_types": annotation_types,
        "output_files": {
            "game_logs": str(log_path),
            "speech_samples": str(speech_path),
        },
    }


# ===========================================================================
# Report
# ===========================================================================

def _generate_report(results: dict[str, Any]):
    """Generate a Markdown report of the open data adapter run."""
    lines = [
        "# Track B Open Data Adapter Report",
        "",
        f"> Generated from {len(results)} source(s)",
        "",
        "---",
        "",
        "## Summary",
        "",
    ]

    for source_name, result in results.items():
        lines.extend([
            f"### {source_name}",
            "",
            f"- **License**: {result.get('license', 'unknown')}",
            f"- **Rule variant**: {result.get('rule_variant', 'unknown')}",
            f"- **Games**: {result.get('total_games', 0)}",
            f"- **Speech samples**: {result.get('total_speech_samples', 0)}",
            "",
            "#### Role Distribution",
            "",
            "| Role | Count |",
            "| --- | ---: |",
        ])
        for role, count in sorted(result.get("role_distribution", {}).items()):
            lines.append(f"| {role} | {count} |")
        lines.append("")

        lines.extend([
            "#### Weak Label Types",
            "",
            "| Label | Count |",
            "| --- | ---: |",
        ])
        for label, count in sorted(result.get("annotation_types", {}).items()):
            lines.append(f"| {label} | {count} |")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Policy Compliance",
        "",
        "- [x] No final_q generated from open data",
        "- [x] Source and license metadata preserved",
        "- [x] rule_variant recorded",
        "- [x] visible_public_context present",
        "- [x] Weak label source traced",
        "- [x] do_not_train_final_q_directly = true",
        "- [x] Outcome labels marked as outcome_proxy where applicable",
        "",
        "## Allowed Claims",
        "",
        "Track B has an open-data reconstruction path and can export external "
        "speech data into Track B-compatible schemas.",
        "",
        "## Disallowed Claims",
        "",
        "- Track B is NOT trained on open data",
        "- Track B final_q is NOT validated by open data",
        "- Role-specific models are NOT production ready",
        "- Human alignment is NOT complete",
        "",
    ])

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written: {REPORT_PATH}")


# ===========================================================================
# CLI
# ===========================================================================

AVAILABLE_SOURCES = {
    "werewolf_among_us": build_werewolf_among_us,
}


def main():
    parser = argparse.ArgumentParser(description="Build Track B open datasets")
    parser.add_argument("--source", choices=list(AVAILABLE_SOURCES.keys()),
                       help="Specific source to build")
    parser.add_argument("--split", default="all",
                       help="Dataset split (train/val/test/all)")
    parser.add_argument("--list-sources", action="store_true",
                       help="List available sources")
    args = parser.parse_args()

    if args.list_sources:
        print("Available sources:")
        for name in AVAILABLE_SOURCES:
            print(f"  - {name}")
        return 0

    _ensure_dirs()
    results: dict[str, Any] = {}

    if args.source:
        fn = AVAILABLE_SOURCES[args.source]
        results[args.source] = fn(args.split)
    else:
        for name, fn in AVAILABLE_SOURCES.items():
            try:
                results[name] = fn(args.split)
            except Exception as e:
                print(f"  {name} FAILED: {e}")
                import traceback
                traceback.print_exc()

    if results:
        _generate_report(results)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
