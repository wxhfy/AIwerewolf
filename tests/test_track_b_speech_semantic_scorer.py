"""Tests for SpeechSemanticScorer — audit-only speech act analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_import():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    assert scorer is not None


def test_scorer_returns_audit_only():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    result = scorer.score("I think P3 is the werewolf.")
    assert result.audit_only is True


def test_scorer_returns_probs():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    result = scorer.score("I accuse P3 of being the werewolf because of the voting pattern.")
    assert "accusation" in result.speech_act_probs
    assert "evidence_use" in result.speech_act_probs
    # All probs should be between 0 and 1
    for v in result.speech_act_probs.values():
        assert 0.0 <= v <= 1.0, f"Prob out of range: {v}"


def test_scorer_returns_audit_features():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    result = scorer.score("I am the Seer and I checked P1 as a werewolf.")
    assert "identity_claim_signal" in result.audit_features
    assert "evidence_grounding_signal" in result.audit_features
    assert result.audit_only is True


def test_scorer_no_final_q():
    """SpeechSemanticScorer must never return final_q."""
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    result = scorer.score("test")
    d = result.to_dict()
    assert "final_q" not in d
    assert d["audit_only"] is True


def test_scorer_empty_utterance():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    result = scorer.score("")
    assert result.audit_only is True
    assert result.error == "empty_utterance"


def test_scorer_batch():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    results = scorer.score_batch(["Hello", "I accuse P3", "I am the Seer"])
    assert len(results) == 3
    for r in results:
        assert r.audit_only is True


def test_scorer_model_artifact():
    """Check if trained model artifact exists and is valid."""
    path = ROOT / "models" / "open_data" / "speech_act_classifier_v0.pkl"
    if not path.exists():
        pytest.skip("SpeechActClassifier not yet trained")
    import pickle

    with open(path, "rb") as f:
        data = pickle.load(f)
    assert data.get("audit_only") is True
    assert "vectorizer" in data
    assert "classifier" in data
    assert "labels" in data


def test_model_metrics_exist():
    path = ROOT / "data" / "open" / "combined" / "speech_act_classifier_v0_metrics.json"
    if not path.exists():
        pytest.skip("SpeechActClassifier metrics not yet generated")
    metrics = json.loads(path.read_text())
    assert metrics.get("audit_only") is True
    assert "test_exact_accuracy" in metrics
    assert "test_hamming_loss" in metrics
    assert "label_distribution" in metrics
    assert metrics["version"] == "v0"


def test_source_model_field():
    from backend.eval.heads.speech_semantic import SpeechSemanticScorer

    scorer = SpeechSemanticScorer()
    result = scorer.score("test")
    assert result.source_model == "speech_act_classifier_v0"
