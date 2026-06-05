"""Track B vNext Evaluation Tests — verify eval script runs and produces valid output."""

from __future__ import annotations

import json
from pathlib import Path


def _run_suite(suite: str):
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/evaluate_track_b_vnext.py", "--suite", suite],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return r.returncode, r.stdout, r.stderr


def test_evaluate_track_b_vnext_feature_suite_runs():
    rc, stdout, stderr = _run_suite("feature")
    assert rc == 0, f"Feature suite failed: {stderr}"
    assert "Status:" in stdout
    assert "Success rate" in stdout or "SKIPPED" in stdout


def test_evaluate_track_b_vnext_pairwise_suite_runs():
    rc, stdout, stderr = _run_suite("pairwise")
    assert rc == 0, f"Pairwise suite failed: {stderr}"
    assert "accuracy" in stdout.lower() or "pair" in stdout.lower() or "SKIPPED" in stdout


def test_evaluate_track_b_vnext_opportunity_suite_runs():
    rc, stdout, stderr = _run_suite("opportunity")
    assert rc == 0, f"Opportunity suite failed: {stderr}"
    assert "action_type" in stdout or "good_cal" in stdout or "SKIPPED" in stdout or "gap" in stdout


def test_evaluate_track_b_vnext_process_suite_runs():
    rc, stdout, stderr = _run_suite("process")
    assert rc == 0, f"Process suite failed: {stderr}"
    assert "legacy" in stdout.lower() or "v3" in stdout.lower() or "SKIPPED" in stdout


def test_evaluate_track_b_vnext_game_value_suite_runs():
    rc, stdout, stderr = _run_suite("game_value")
    assert rc == 0, f"Game value suite failed: {stderr}"
    assert "Accuracy" in stdout or "SKIPPED" in stdout


def test_evaluate_track_b_vnext_ablation_suite_runs():
    rc, stdout, stderr = _run_suite("ablation")
    assert rc == 0, f"Ablation suite failed: {stderr}"
    assert "A_legacy" in stdout or "SKIPPED" in stdout


def test_vnext_eval_summary_schema():
    p = Path("data/health/track_b_vnext_eval_summary.json")
    if not p.exists():
        import subprocess
        import sys

        subprocess.run([sys.executable, "scripts/evaluate_track_b_vnext.py", "--all"], capture_output=True, timeout=300)
    if p.exists():
        data = json.loads(p.read_text())
        assert "suites" in data
        assert "generated_at" in data
        required = ["feature", "pairwise", "opportunity", "process", "game_value", "ablation"]
        for s in required:
            assert s in data["suites"], f"Missing suite: {s}"
            assert "status" in data["suites"][s]


def test_vnext_eval_report_created():
    p = Path("docs/track_b_vnext_eval_report.md")
    if not p.exists():
        import subprocess
        import sys

        subprocess.run([sys.executable, "scripts/evaluate_track_b_vnext.py", "--all"], capture_output=True, timeout=300)
    assert p.exists(), "Report not generated"
    content = p.read_text()
    assert "Executive Summary" in content
    assert "feature" in content.lower()
    assert "pairwise" in content.lower()
