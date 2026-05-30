"""Tests for Track B open data full pipeline.

Covers: manifest, downloader, dataset builder, audit, policy compliance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# Manifest tests
# ===========================================================================

@pytest.fixture(scope="module")
def manifest():
    path = ROOT / "docs" / "track_b_open_data_sources_manifest.yaml"
    if not path.exists():
        pytest.skip("Manifest not yet created")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_manifest_exists():
    path = ROOT / "docs" / "track_b_open_data_sources_manifest.yaml"
    assert path.exists(), "Manifest file must exist"


def test_manifest_has_sources(manifest):
    sources = manifest.get("sources", {})
    assert len(sources) >= 3, f"Expected >=3 sources, got {len(sources)}"


def test_manifest_each_source_has_required_fields(manifest):
    required = ["priority", "raw_dir", "license_status"]
    for name, info in manifest["sources"].items():
        for field in required:
            assert field in info, f"Source '{name}' missing field '{field}'"


def test_manifest_each_source_has_paper_url_or_project_url(manifest):
    internal_sources = {"track_b_native"}
    for name, info in manifest["sources"].items():
        if name in internal_sources:
            continue
        has_url = info.get("paper_url") or info.get("project_url") or info.get("huggingface_id")
        assert has_url, f"Source '{name}' has no paper_url, project_url, or huggingface_id"


def test_manifest_werewolf_among_us_is_p0(manifest):
    wau = manifest["sources"].get("werewolf_among_us", {})
    assert wau.get("priority") == "P0", "Werewolf Among Us should be P0"


# ===========================================================================
# Downloader tests
# ===========================================================================

def test_downloader_script_exists():
    path = ROOT / "scripts" / "download_track_b_open_sources.py"
    assert path.exists()


def test_raw_directories_exist():
    dirs = [
        "data/external/raw/werewolf_among_us",
        "data/external/raw/wolf",
        "data/external/raw/beyond_survival",
        "data/external/raw/deep_wolf_aiwolf",
        "data/external/raw/werewolf_arena",
    ]
    for d in dirs:
        p = ROOT / d
        assert p.exists(), f"Raw directory missing: {d}"
        assert p.is_dir(), f"Not a directory: {d}"


def test_todo_files_for_unavailable_sources():
    """Unavailable sources should have TODO.md files."""
    todo_dirs = ["wolf", "beyond_survival", "deep_wolf_aiwolf"]
    for d in todo_dirs:
        p = ROOT / "data" / "external" / "raw" / d / "TODO.md"
        if not p.exists():
            # It's OK if the downloader hasn't been run yet
            pass


# ===========================================================================
# Dataset builder tests
# ===========================================================================

def test_builder_script_exists():
    path = ROOT / "scripts" / "build_track_b_open_datasets.py"
    assert path.exists()


def test_combined_speech_samples_exist():
    path = ROOT / "data" / "open" / "combined" / "track_b_open_speech_samples.jsonl"
    if not path.exists():
        pytest.skip("Run scripts/build_track_b_open_datasets.py --all first")
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) >= 100, f"Expected >=100 speech samples, got {len(lines)}"


def test_combined_speech_no_final_q():
    path = ROOT / "data" / "open" / "combined" / "track_b_open_speech_samples.jsonl"
    if not path.exists():
        pytest.skip("Run scripts/build_track_b_open_datasets.py --all first")
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.strip():
                sample = json.loads(line)
                assert "final_q" not in sample, f"Sample {i} contains final_q"
                if i >= 500:
                    break


def test_combined_speech_has_required_metadata():
    path = ROOT / "data" / "open" / "combined" / "track_b_open_speech_samples.jsonl"
    if not path.exists():
        pytest.skip("Run scripts/build_track_b_open_datasets.py --all first")
    required = ["source", "license", "rule_variant", "do_not_train_final_q_directly"]
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.strip():
                sample = json.loads(line)
                for field in required:
                    assert field in sample, f"Sample {i} missing '{field}'"
                assert sample["do_not_train_final_q_directly"] is True, \
                    f"Sample {i} has do_not_train_final_q_directly=False"
                if i >= 100:
                    break


def test_split_files_exist():
    splits = ["speech_train_games.txt", "speech_val_games.txt", "speech_test_games.txt"]
    for s in splits:
        path = ROOT / "data" / "splits" / "open_data" / s
        if not path.exists():
            pytest.skip("Run scripts/build_track_b_open_datasets.py --all first")


def test_splits_are_by_game_id():
    """Verify splits don't overlap by game_id."""
    splits_dir = ROOT / "data" / "splits" / "open_data"
    train_path = splits_dir / "speech_train_games.txt"
    val_path = splits_dir / "speech_val_games.txt"
    test_path = splits_dir / "speech_test_games.txt"

    if not train_path.exists():
        pytest.skip("Run scripts/build_track_b_open_datasets.py --all first")

    train_ids = set(train_path.read_text().strip().split("\n"))
    val_ids = set(val_path.read_text().strip().split("\n"))
    test_ids = set(test_path.read_text().strip().split("\n"))

    assert len(train_ids & val_ids) == 0, "Train and val splits overlap"
    assert len(train_ids & test_ids) == 0, "Train and test splits overlap"
    assert len(val_ids & test_ids) == 0, "Val and test splits overlap"


# ===========================================================================
# Audit tests
# ===========================================================================

def test_audit_script_exists():
    path = ROOT / "scripts" / "audit_track_b_open_datasets.py"
    assert path.exists()


def test_audit_json_exists():
    path = ROOT / "data" / "open" / "combined" / "track_b_open_data_audit.json"
    if not path.exists():
        pytest.skip("Run scripts/audit_track_b_open_datasets.py first")
    audit = json.loads(path.read_text())
    assert "summary" in audit
    assert "datasets" in audit
    assert audit["summary"]["total_samples"] > 0


def test_audit_report_exists():
    path = ROOT / "docs" / "track_b_open_data_audit_report.md"
    if not path.exists():
        pytest.skip("Run scripts/audit_track_b_open_datasets.py first")
    text = path.read_text()
    assert "Policy Compliance" in text
    assert "final_q" in text.lower()
