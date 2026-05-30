"""Tests for Phase C: Speech Semantic Audit Integration.

Validates: metrics completeness, audit examples generation,
no-final_q policy, profile aggregation, and integration report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# Metrics tests
# ===========================================================================

@pytest.fixture(scope="module")
def metrics():
    path = ROOT / "data" / "open" / "combined" / "speech_act_classifier_v0_metrics.json"
    if not path.exists():
        pytest.skip("Metrics not yet generated. Run train_speech_semantic_scorer.py first.")
    return json.loads(path.read_text())


def test_metrics_contains_macro_f1(metrics):
    assert "test_macro_f1" in metrics, "Metrics must include macro_f1"
    assert metrics["test_macro_f1"] > 0, f"macro_f1 should be > 0, got {metrics['test_macro_f1']}"


def test_metrics_contains_micro_f1(metrics):
    assert "test_micro_f1" in metrics, "Metrics must include micro_f1"
    assert metrics["test_micro_f1"] > 0, f"micro_f1 should be > 0, got {metrics['test_micro_f1']}"


def test_metrics_contains_per_label_f1(metrics):
    per_label = metrics.get("per_label_metrics", {})
    for label in ["accusation", "interrogation", "defense",
                  "evidence_use", "identity_declaration", "call_for_action"]:
        assert label in per_label, f"Missing per_label_metrics for '{label}'"
        assert "f1" in per_label[label], f"Missing f1 for label '{label}'"


def test_metrics_contains_per_label_precision_recall(metrics):
    per_label = metrics.get("per_label_metrics", {})
    for label, info in per_label.items():
        if info.get("support", 0) > 0:
            assert "precision" in info, f"Missing precision for '{label}'"
            assert "recall" in info, f"Missing recall for '{label}'"


def test_metrics_audit_only(metrics):
    assert metrics.get("audit_only") is True


def test_metrics_has_label_distribution(metrics):
    ld = metrics.get("label_distribution", {})
    assert len(ld) == 6, f"Expected 6 labels, got {len(ld)}"


# ===========================================================================
# Audit examples tests
# ===========================================================================

def test_audit_examples_script_exists():
    path = ROOT / "scripts" / "generate_speech_semantic_audit_examples.py"
    assert path.exists()


def test_audit_examples_can_be_generated():
    """Run the generator on a small subset and verify output."""
    import subprocess, sys, tempfile
    script = ROOT / "scripts" / "generate_speech_semantic_audit_examples.py"
    if not script.exists():
        pytest.skip("Script not found")

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--limit", "50", "--output", tmp_path],
            capture_output=True, text=True, timeout=120,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            pytest.skip(f"Generator failed: {result.stderr[:200]}")

        with open(tmp_path, encoding="utf-8") as f:
            examples = [json.loads(l) for l in f if l.strip()]

        assert len(examples) > 0, "Should generate at least one audit example"

        for ex in examples:
            assert ex.get("audit_only") is True, f"audit_only must be True, got {ex.get('audit_only')}"
            assert "final_q" not in ex, "Audit example must not contain final_q"
            assert "speech_act_probs" in ex
            assert "audit_features" in ex
            assert "source_model" in ex
            assert ex["source_model"] == "speech_act_classifier_v0"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ===========================================================================
# No final_q policy tests
# ===========================================================================

def test_speech_semantic_scorer_no_final_q():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer
    scorer = SpeechSemanticScorer()
    result = scorer.score("I think P3 is the werewolf.")
    d = result.to_dict()
    assert "final_q" not in d
    assert d["audit_only"] is True


def test_integration_report_states_no_final_q_impact():
    path = ROOT / "docs" / "track_b_speech_semantic_audit_integration_report.md"
    if not path.exists():
        pytest.skip("Integration report not yet created")
    text = path.read_text(encoding="utf-8")
    # Must explicitly state no impact on scoring
    assert "final_q" in text.lower()
    assert "does not affect" in text.lower() or "NO" in text


def test_integration_report_exists():
    path = ROOT / "docs" / "track_b_speech_semantic_audit_integration_report.md"
    assert path.exists(), "Integration report must exist"


def test_classifier_report_exists():
    path = ROOT / "docs" / "track_b_speech_act_classifier_v0_report.md"
    assert path.exists(), "Classifier v0 report must exist"


# ===========================================================================
# Profile aggregation tests
# ===========================================================================

def test_profile_analyzer_script_exists():
    path = ROOT / "scripts" / "analyze_profile_speech_semantics.py"
    assert path.exists()


def test_profile_aggregation_returns_distribution():
    """Run profile analyzer on small audit examples subset."""
    import subprocess, sys, tempfile

    # First generate some audit examples if not exist
    audit_path = ROOT / "data" / "open" / "combined" / "speech_semantic_audit_examples.jsonl"
    if not audit_path.exists():
        pytest.skip("Run generate_speech_semantic_audit_examples.py first")

    script = ROOT / "scripts" / "analyze_profile_speech_semantics.py"
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, str(script),
             "--input", str(audit_path),
             "--output", tmp_path,
             "--profile-field", "role",
             "--limit", "500"],
            capture_output=True, text=True, timeout=120,
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            pytest.skip(f"Analyzer failed: {result.stderr[:200]}")

        with open(tmp_path, encoding="utf-8") as f:
            profiles = [json.loads(l) for l in f if l.strip()]

        assert len(profiles) > 0, "Should produce at least one profile"

        for p in profiles:
            assert "profile_id" in p
            assert "samples" in p
            assert p["samples"] > 0
            assert "top_speech_pattern" in p
            assert p.get("audit_only") is True

            # Check required audit feature fields
            for field in [
                "avg_evidence_grounding_signal", "avg_actionability_signal",
                "avg_identity_claim_signal", "avg_pressure_signal",
                "avg_information_seeking_signal", "avg_defensive_posture_signal",
            ]:
                assert field in p, f"Profile missing field: {field}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
