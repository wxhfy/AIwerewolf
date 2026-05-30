#!/usr/bin/env python3
"""One-time downloader for Track B open data sources.

Reads docs/track_b_open_data_sources_manifest.yaml and downloads all available
sources. Creates raw directories and TODO files for unavailable sources.

Usage:
  python scripts/download_track_b_open_sources.py --manifest docs/track_b_open_data_sources_manifest.yaml
  python scripts/download_track_b_open_sources.py --all
  python scripts/download_track_b_open_sources.py --source werewolf_among_us
  python scripts/download_track_b_open_sources.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_MANIFEST = ROOT / "docs" / "track_b_open_data_sources_manifest.yaml"
EXTERNAL_DIR = ROOT / "data" / "external"


def _load_manifest(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _write_todo(source_name: str, raw_dir: Path, info: dict):
    """Write a TODO file explaining why this source couldn't be auto-downloaded."""
    todo_path = raw_dir / "TODO.md"
    lines = [
        f"# TODO: {source_name}",
        "",
        f"**Status**: {info.get('status', 'unknown')}",
        f"**Priority**: {info.get('priority', 'unknown')}",
        f"**Download method**: {info.get('download_method', 'manual')}",
        "",
        "## Why unavailable",
        info.get("notes", info.get("license_note", "No download path known.")),
        "",
        "## How to obtain",
    ]

    paper_url = info.get("paper_url", "")
    if paper_url:
        lines.append(f"- Paper: {paper_url}")
    project_url = info.get("project_url", "")
    if project_url:
        lines.append(f"- Project site: {project_url}")
    huggingface = info.get("huggingface_id", "")
    if huggingface:
        lines.append(f"- HuggingFace: https://huggingface.co/datasets/{huggingface}")
    github = info.get("github", "")
    if github:
        lines.append(f"- GitHub: {github}")

    lines.extend([
        "",
        "## After obtaining",
        f"Place raw data files in: `{raw_dir}/`",
        f"Then re-run: `python scripts/build_track_b_open_datasets.py --source {source_name}`",
        "",
    ])
    todo_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  TODO written: {todo_path}")


def _download_huggingface(source_name: str, info: dict) -> bool:
    """Try to download a HuggingFace dataset."""
    hf_id = info.get("huggingface_id", "")
    if not hf_id:
        return False

    try:
        from datasets import load_dataset
        print(f"  Downloading {hf_id}...")
        ds = load_dataset(hf_id, trust_remote_code=True, split="train")
        print(f"  Downloaded: {len(ds)} rows")
        return True
    except Exception as e:
        print(f"  HuggingFace download failed: {e}")
        return False


def download_source(source_name: str, info: dict) -> bool:
    """Download a single source. Returns True if data is available."""
    raw_dir = EXTERNAL_DIR / "raw" / source_name
    _ensure_dir(raw_dir)

    status = info.get("status", "unknown")
    method = info.get("download_method", "manual")

    if status == "available" and method == "huggingface_datasets":
        # Data already cached by datasets library; verify it exists
        try:
            from datasets import get_dataset_config_names
            hf_id = info.get("huggingface_id", "")
            if hf_id:
                configs = get_dataset_config_names(hf_id)
                print(f"  HuggingFace dataset '{hf_id}' available (configs: {configs})")
                return True
        except Exception:
            print(f"  HuggingFace dataset check failed, attempting download...")
            return _download_huggingface(source_name, info)

    if status == "available" and method == "native_pipeline":
        print(f"  Native data (manual collection required)")
        # Track B native data comes from running real LLM games
        replays_dir = ROOT / "data" / "replays" / "raw_llm_games"
        if replays_dir.exists():
            n = len(list(replays_dir.glob("*.json*")))
            print(f"  Replays available: {n} files")
        else:
            print(f"  No replays directory yet. Run real LLM games to populate.")
        return True

    # Unavailable or manual sources
    print(f"  Status: {status}, method: {method}")
    _write_todo(source_name, raw_dir, info)

    # Create placeholder outputs
    for output_path in info.get("expected_outputs", []):
        placeholder_dir = ROOT / output_path
        _ensure_dir(placeholder_dir.parent)
        # Write empty file with header
        placeholder_dir.write_text("", encoding="utf-8")

    return False


def main():
    parser = argparse.ArgumentParser(description="Download Track B open data sources")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST),
                       help="Path to sources manifest YAML")
    parser.add_argument("--all", action="store_true",
                       help="Download all sources in manifest")
    parser.add_argument("--source", help="Download a specific source")
    parser.add_argument("--list", action="store_true",
                       help="List all sources and their status")
    args = parser.parse_args()

    manifest = _load_manifest(Path(args.manifest))
    sources = manifest.get("sources", {})

    if args.list:
        print(f"{'Source':<25} {'Priority':<12} {'Status':<15} {'Download':<20}")
        print("-" * 72)
        for name, info in sources.items():
            print(f"{name:<25} {info.get('priority', '?'):<12} "
                  f"{info.get('status', '?'):<15} {info.get('download_method', '?'):<20}")
        return 0

    print("=" * 60)
    print("Track B Open Data Downloader")
    print("=" * 60)

    _ensure_dir(EXTERNAL_DIR / "raw")
    _ensure_dir(EXTERNAL_DIR / "checksums")
    _ensure_dir(EXTERNAL_DIR / "licenses")
    _ensure_dir(EXTERNAL_DIR / "manifests")

    if args.source:
        info = sources.get(args.source)
        if not info:
            print(f"Unknown source: {args.source}")
            return 1
        print(f"\n[{args.source}]")
        ok = download_source(args.source, info)
        print(f"  Result: {'available' if ok else 'TODO/manual'}")
    else:
        available = 0
        todo = 0
        for name, info in sources.items():
            print(f"\n[{name}]")
            ok = download_source(name, info)
            if ok:
                available += 1
            else:
                todo += 1
        print(f"\n{'='*60}")
        print(f"Download complete: {available} available, {todo} TODO/manual")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
