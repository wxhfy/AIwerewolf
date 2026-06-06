"""Tests for Track B open data adapter layer.

Validates schema compliance, adapter output, and policy enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPEN_DATA_DIR = ROOT / "data" / "open"


# ===========================================================================
# Schema tests
# ===========================================================================


def test_speech_quality_sample_schema():
    from backend.eval.open_data.schema import OpenDataLicense
    from backend.eval.open_data.schema import SpeechQualitySample

    s = SpeechQualitySample(
        sample_id="speech_000001",
        source="werewolf_among_us",
        license=OpenDataLicense.VERIFY_BEFORE_USE,
        rule_variant="one_night_werewolf",
        game_id="Game4",
        turn_id="1",
        player_id="Jessica",
        role="Villager",
        utterance="What?",
        weak_label_source="open_dataset_annotation",
    )
    d = s.to_dict()
    assert d["do_not_train_final_q_directly"] is True
    assert d["license"] == "verify_before_use"
    assert d["source"] == "werewolf_among_us"


def test_vote_decision_sample_schema():
    from backend.eval.open_data.schema import VoteDecisionSample

    s = VoteDecisionSample(
        sample_id="vote_000001",
        source="track_b_replay",
        game_id="g1",
        player_id="P1",
        role="Seer",
        vote_target="P2",
        candidate_targets=["P2", "P3"],
    )
    d = s.to_dict()
    assert d["do_not_train_final_q_directly"] is True


def test_counterfactual_pairwise_sample_schema():
    from backend.eval.open_data.schema import CounterfactualPairwiseSample

    s = CounterfactualPairwiseSample(
        pair_id="pair_000001",
        source="track_b_replay",
        game_id="g1",
        role="Werewolf",
        action_type="vote",
        option_a={"action": "vote_P3"},
        option_b={"action": "vote_P1"},
        label="A_BETTER",
    )
    d = s.to_dict()
    assert d["do_not_enable_ranker_without_gate"] is True


def test_value_impact_sample_schema():
    from backend.eval.open_data.schema import ValueImpactSample

    s = ValueImpactSample(
        sample_id="value_000001",
        source="deep_wolf_logs",
        role="Seer",
        phase="DAY_VOTE",
    )
    d = s.to_dict()
    assert d["not_process_quality_label"] is True


def test_role_action_sample_schema():
    from backend.eval.open_data.schema import RoleActionSample

    s = RoleActionSample(
        sample_id="role_action_000001",
        source="track_b_replay",
        role="Seer",
        action_type="claim_or_info_release",
    )
    d = s.to_dict()
    assert d["source"] == "track_b_replay"


def test_weak_label_provenance():
    from backend.eval.open_data.schema import WeakLabel
    from backend.eval.open_data.schema import WeakLabelSource

    wl = WeakLabel(
        label_name="evidence_grounding",
        label_value=0.8,
        source=WeakLabelSource.OPEN_DATASET_ANNOTATION,
        confidence=0.7,
        reason="annotated as Evidence",
        used_future_info=False,
    )
    assert wl.used_future_info is False
    assert wl.source == WeakLabelSource.OPEN_DATASET_ANNOTATION


# ===========================================================================
# Adapter tests
# ===========================================================================


@pytest.fixture(scope="module")
def adapter():
    from backend.eval.open_data.adapters import WerewolfAmongUsAdapter

    return WerewolfAmongUsAdapter()


@pytest.fixture(scope="module")
def adapter_output(adapter):
    return adapter.run(split="train")


def test_adapter_data_dir_exists(adapter):
    assert adapter.data_dir.exists(), f"Data dir not found: {adapter.data_dir}"


def test_adapter_loads_raw_games(adapter):
    games = adapter.load_raw_games(split="train")
    assert len(games) > 0, "Should load at least one raw game"
    game = games[0]
    assert "Game_ID" in game
    assert "Dialogue" in game
    assert "playerNames" in game
    assert "startRoles" in game


def test_adapter_builds_game_logs(adapter_output):
    logs, _ = adapter_output
    assert len(logs) > 0, "Should produce at least one OpenGameLog"
    log = logs[0]
    assert log.source == "werewolf_among_us"
    assert log.license.value == "verify_before_use"
    assert log.rule_variant == "one_night_werewolf"
    assert len(log.events) > 0


def test_adapter_extracts_speech_samples(adapter_output):
    _, samples = adapter_output
    assert len(samples) > 0, "Should produce at least one SpeechQualitySample"
    s = samples[0]
    assert s.do_not_train_final_q_directly is True
    assert s.source == "werewolf_among_us"
    assert s.utterance, "Speech sample must have utterance text"
    assert s.role != "Unknown", f"Role should be mapped, got: {s.role}"


def test_adapter_no_final_q_generated(adapter_output):
    """Verify no final_q is generated from open data."""
    _, samples = adapter_output
    for s in samples:
        d = s.to_dict()
        assert "final_q" not in d, "Open data must not generate final_q"
        assert d["do_not_train_final_q_directly"] is True


def test_adapter_license_metadata_present(adapter_output):
    logs, samples = adapter_output
    for log in logs:
        assert log.license.value != "unknown"
        assert log.source != ""
    for s in samples:
        d = s.to_dict()
        assert d["license"] != "unknown"
        assert d["source"] != ""
        assert d["rule_variant"] != ""


def test_adapter_visibility_fields_present(adapter_output):
    _, samples = adapter_output
    for s in samples:
        d = s.to_dict()
        assert "visible_public_context" in d
        assert "visible_private_context" in d


def test_adapter_weak_labels_have_source(adapter_output):
    _, samples = adapter_output
    samples_with_labels = [s for s in samples if s.weak_labels]
    assert len(samples_with_labels) > 0, "Should have samples with weak labels"
    for s in samples_with_labels:
        for label_name, wl in s.weak_labels.items():
            assert wl.source.value != "", f"Label {label_name} missing source"
            assert wl.used_future_info is False, f"Label {label_name} used future info"


def test_adapter_role_normalization(adapter_output):
    """Verify ONUW roles are mapped to Track B roles."""
    _, samples = adapter_output
    roles_found = {s.role for s in samples}
    # Should only contain Track B-compatible roles or "Unknown"
    valid_roles = {"Werewolf", "Seer", "Villager", "Hunter", "Witch", "Guard", "Unknown"}
    invalid = roles_found - valid_roles
    assert len(invalid) == 0, f"Unmapped roles found: {invalid}"


# ===========================================================================
# Output file tests (after build script runs)
# ===========================================================================


def test_speech_samples_output_exists():
    path = OPEN_DATA_DIR / "track_b_open_speech_samples.jsonl"
    if not path.exists():
        pytest.skip("Run scripts/build_track_b_open_dataset.py first")
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) > 0, "Speech samples file should not be empty"
    sample = json.loads(lines[0])
    assert "do_not_train_final_q_directly" in sample
    assert sample["do_not_train_final_q_directly"] is True
