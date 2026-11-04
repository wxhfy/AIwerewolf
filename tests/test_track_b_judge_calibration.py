"""Offline tests; every annotation here is synthetic, never production data."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.judge_calibration import JudgeCalibration
from backend.db.judge_calibration import latest_approved_calibration
from backend.db.judge_calibration import save_judge_calibration
from backend.eval.calibration import JudgeCalibrationPolicy
from backend.eval.calibration import apply_judge_calibration
from backend.eval.calibration import calibrate_judge_dataset
from backend.eval.calibration import judge_agreement_metrics
from backend.eval.calibration import load_judge_calibration_dataset
from backend.eval.human_label_validator import validate_judge_calibration_dataset
from backend.eval.judge_rubric import RUBRIC_HASH
from backend.eval.llm_judge import LLMJudgePanel
from scripts.calibrate_track_b_judge import SyntheticCalibrationClient

FIXTURE = Path(__file__).parent / "fixtures" / "judge_calibration_synthetic.json"
SMALL = JudgeCalibrationPolicy(min_train=4, min_validation=4)


def _dataset():
    return load_judge_calibration_dataset(FIXTURE)


def _demo_profile():
    return calibrate_judge_dataset(
        _dataset(),
        LLMJudgePanel(client=SyntheticCalibrationClient()),
        judge_model="fake:calibration-demo",
        policy=SMALL,
    )


def _simulated_approved_profile(scoring_mode="single_step"):
    """Exercise human approval in an isolated DB with test-only provenance."""
    dataset = _dataset()
    dataset.update(dataset_id="unit-test-simulated-human-source", synthetic=False, annotation_source="human")
    samples = []
    for split, count in (("train", 30), ("validation", 20)):
        for i in range(count):
            row = copy.deepcopy(dataset["samples"][i % 6])
            row.update(
                sample_id=f"test-only-{split}-{i}",
                game_id=f"test-only-game-{split}-{i}",
                split=split,
                annotator_id="test-only-simulated-annotator",
            )
            samples.append(row)
    dataset["samples"] = samples
    client = SyntheticCalibrationClient()
    client.provider = "unit-test-configured-provider"
    return calibrate_judge_dataset(
        dataset, LLMJudgePanel(client=client), judge_model="unit-test:judge-v1", scoring_mode=scoring_mode
    )


def test_synthetic_fixture_is_explicit_and_never_approves_promotion():
    profile = _demo_profile()
    assert profile["status"] == "demonstration"
    assert profile["synthetic"] is True
    assert profile["human_verified"] is False
    assert profile["agreement_passed"] is True
    assert profile["auto_promotion_allowed"] is False
    assert profile["metrics"]["calibrated"]["mae"] < profile["metrics"]["raw"]["mae"]
    assert profile["parameters"]["overall"]["slope"] > 1


def test_metrics_identical_and_inverted_scores():
    identical = judge_agreement_metrics([0, 0.25, 0.5, 0.75, 1], [0, 0.25, 0.5, 0.75, 1])
    assert identical == {"n": 5, "kappa": 1, "pearson": 1, "spearman": 1, "bias": 0, "mae": 0}
    inverted = judge_agreement_metrics([0, 0.25, 0.5, 0.75, 1], [1, 0.75, 0.5, 0.25, 0])
    assert inverted["kappa"] == -1
    assert inverted["pearson"] == -1
    assert inverted["spearman"] == -1


def test_constant_or_missing_labels_do_not_fabricate_correlation():
    metrics = judge_agreement_metrics([0.5, 0.5], [0.5, 0.5])
    assert metrics["kappa"] is None
    assert metrics["pearson"] is None
    assert metrics["spearman"] is None
    assert judge_agreement_metrics([], [])["n"] == 0
    with pytest.raises(ValueError, match="score_count"):
        judge_agreement_metrics([0.5], [])
    with pytest.raises(ValueError, match="finite"):
        judge_agreement_metrics([float("nan")], [0.5])


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda d: d.pop("synthetic"), "synthetic_must_be_explicit_boolean"),
        (lambda d: d["samples"].append(d["samples"][0]), "duplicate_sample_id"),
        (lambda d: d["samples"][6].update(game_id=d["samples"][0]["game_id"]), "game_crosses_splits"),
        (lambda d: d["samples"][0].update(human_score=float("nan")), "human_score_out_of_range"),
        (lambda d: d["samples"][0].update(human_score=True), "human_score_out_of_range"),
        (lambda d: d["samples"][0].update(annotator_id=""), "missing_annotator_id"),
        (lambda d: d["samples"][0].update(visible_context={}), "missing_visible_context"),
    ],
)
def test_invalid_annotations_are_rejected_before_judge_call(mutation, expected):
    dataset = _dataset()
    mutation(dataset)
    assert any(expected in error for error in validate_judge_calibration_dataset(dataset))
    with pytest.raises(ValueError, match=expected):
        calibrate_judge_dataset(dataset, None, judge_model="fake:test")


def test_judge_never_receives_human_labels_or_annotation_metadata():
    client = SyntheticCalibrationClient()
    original = client.chat_sync
    calls = []

    def inspect(messages, **kwargs):
        text = json.dumps(messages)
        assert "human_score" not in text
        assert "annotator_id" not in text
        assert "synthetic-fixture-not-a-human" not in text
        calls.append(messages)
        return original(messages, **kwargs)

    client.chat_sync = inspect
    calibrate_judge_dataset(_dataset(), LLMJudgePanel(client=client), judge_model="fake:test", policy=SMALL)
    assert len(calls) == 12


def test_scoring_retries_and_excludes_low_confidence_labels():
    dataset = _dataset()
    dataset["samples"][0]["confidence"] = "low"
    client = SyntheticCalibrationClient()
    original = client.chat_sync
    attempts = 0

    def transient(messages, **kwargs):
        nonlocal attempts
        attempts += 1
        return {"choices": [{"message": {"content": "{}"}}]} if attempts == 1 else original(messages, **kwargs)

    client.chat_sync = transient
    profile = calibrate_judge_dataset(dataset, LLMJudgePanel(client=client), judge_model="fake:test", policy=SMALL)
    assert profile["metrics"]["excluded_low_confidence_n"] == 1
    assert profile["metrics"]["failed_n"] == 0
    assert profile["samples"][1]["attempts"] == 2
    assert attempts == 12


def test_failed_scoring_exhausts_bounded_retries_without_approval():
    class BrokenPanel:
        def score_step(self, *_args):
            raise RuntimeError("must-not-export-sensitive-provider-message")

    profile = calibrate_judge_dataset(_dataset(), BrokenPanel(), judge_model="unit-test:v1", policy=SMALL)
    assert profile["metrics"]["failed_n"] == 12
    assert profile["auto_promotion_allowed"] is False
    assert "judge_scoring_incomplete" in profile["reasons"]
    assert all(row["attempts"] == 2 for row in profile["samples"])
    assert "must-not-export" not in json.dumps(profile)


def test_low_judge_confidence_excluded_from_calibration_fit_and_validation():
    client = SyntheticCalibrationClient()
    original = client.chat_sync

    def uncertain(messages, **kwargs):
        response = original(messages, **kwargs)
        verdict = json.loads(response["choices"][0]["message"]["content"])
        verdict["confidence"] = 0.1
        response["choices"][0]["message"]["content"] = json.dumps(verdict)
        return response

    client.chat_sync = uncertain
    profile = calibrate_judge_dataset(_dataset(), LLMJudgePanel(client=client), judge_model="fake:test", policy=SMALL)
    assert profile["metrics"]["excluded_low_judge_confidence_n"] == 12
    assert profile["metrics"]["train_n"] == 0
    assert profile["metrics"]["validation_n"] == 0
    assert profile["parameters"] == {}
    assert profile["agreement_passed"] is False


def test_simulated_human_calibration_requires_production_samples_and_metrics():
    profile = _simulated_approved_profile()
    assert profile["status"] == "approved"
    assert profile["auto_promotion_allowed"] is True
    assert profile["metrics"]["train_n"] == 30
    assert profile["metrics"]["validation_n"] == 20
    small = _dataset()
    small.update(synthetic=False, annotation_source="human")
    client = SyntheticCalibrationClient()
    client.provider = "unit-test"
    insufficient = calibrate_judge_dataset(
        small, LLMJudgePanel(client=client), judge_model="unit-test:judge", policy=SMALL
    )
    assert insufficient["status"] == "pending_review"
    assert "production_sample_floor_not_met" in insufficient["reasons"]


def test_database_save_is_immutable_idempotent_and_identity_scoped(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'calibrations.sqlite'}")
    JudgeCalibration.__table__.create(engine)
    profile = _simulated_approved_profile()
    with Session(engine) as session:
        saved = save_judge_calibration(profile, session)
        assert save_judge_calibration(profile, session) == saved
        session.commit()
    with Session(engine) as session:
        assert session.query(JudgeCalibration).count() == 1
        assert (
            latest_approved_calibration(session, judge_model="unit-test:judge-v1", rubric_hash=RUBRIC_HASH)[
                "calibration_id"
            ]
            == profile["calibration_id"]
        )
        assert latest_approved_calibration(session, judge_model="unit-test:other") is None
        assert latest_approved_calibration(session, rubric_hash="outdated-rubric") is None
        assert latest_approved_calibration(session, scoring_mode="panel_step") is None
        modified = {**profile, "reasons": ["changed"]}
        with pytest.raises(ValueError, match="identity_conflict"):
            save_judge_calibration(modified, session)
    engine.dispose()


def test_synthetic_or_forged_approvals_cannot_enter_approved_store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'calibrations.sqlite'}")
    JudgeCalibration.__table__.create(engine)
    with Session(engine) as session:
        profile = _demo_profile()
        save_judge_calibration(profile, session)
        assert latest_approved_calibration(session) is None
        profile.update(status="approved", auto_promotion_allowed=True)
        with pytest.raises(ValueError, match="ineligible"):
            save_judge_calibration(profile, session)
    engine.dispose()


@pytest.mark.parametrize(
    "profile_change,raw,confidence,reason",
    [
        ({"status": "pending_review"}, 0.5, 0.9, "calibration_not_approved"),
        ({"rubric_hash": "old"}, 0.5, 0.9, "calibration_identity_mismatch"),
        ({}, 0.5, 0.2, "low_judge_confidence"),
        ({}, None, 0.9, "invalid_judge_score"),
        ({}, 0.99, 0.9, "outside_calibration_support"),
    ],
)
def test_uncertain_or_unsupported_judgments_fall_back_to_rule_score(profile_change, raw, confidence, reason):
    profile = {**_simulated_approved_profile(), **profile_change}
    result = apply_judge_calibration(
        profile, raw, rule_score=0.42, confidence=confidence, judge_model="unit-test:judge-v1"
    )
    assert result["score"] == 0.42
    assert result["fallback_reason"] == reason
    assert result["requires_review"] is True


def test_calibrated_inference_is_fixed_for_single_or_batch_items():
    profile = _simulated_approved_profile()
    one = apply_judge_calibration(profile, 0.5, rule_score=0.42, confidence=0.9)
    assert one["fallback_used"] is False
    assert one["score"] == pytest.approx(0.5, abs=0.001)
    assert apply_judge_calibration(None, 0.5, rule_score=0.42)["fallback_reason"] == "calibration_missing"
    assert (
        apply_judge_calibration(_demo_profile(), 0.5, rule_score=0.42)["fallback_reason"] == "calibration_not_approved"
    )


def test_panel_uses_calibration_and_missing_confidence_triggers_rule_fallback():
    client = SyntheticCalibrationClient()
    panel = LLMJudgePanel(client=client)
    sample = _dataset()["samples"][2]
    verdict = panel.score_step_calibrated(
        sample["decision"],
        sample["visible_context"],
        profile=_demo_profile(),
        rule_score=0.3,
        judge_model="fake:calibration-demo",
        allow_demonstration=True,
    )
    assert verdict.calibration_info["fallback_used"] is False
    assert verdict.overall == pytest.approx(4, abs=0.01)
    client.chat_sync = lambda *_args, **_kwargs: {"choices": [{"message": {"content": '{"T1_score":4,"T2_score":4}'}}]}
    verdict = panel.score_step_calibrated(
        sample["decision"],
        sample["visible_context"],
        profile=_demo_profile(),
        rule_score=0.3,
        judge_model="fake:calibration-demo",
        allow_demonstration=True,
    )
    assert verdict.overall == 3
    assert verdict.calibration_info["fallback_reason"] == "low_judge_confidence"


@pytest.mark.parametrize("raw", ["{}", '{"T1_score":11,"T2_score":4}', '{"T1_score":"8","T2_score":4}', "[1,2,3]"])
def test_panel_does_not_invent_scores_for_missing_or_invalid_judge_fields(raw):
    client = SyntheticCalibrationClient()
    client.chat_sync = lambda *_args, **_kwargs: {"choices": [{"message": {"content": raw}}]}
    panel = LLMJudgePanel(client=client)
    assert panel.score_step({}, {}) is None
    assert panel.score_step_with_panel({}, {}) is None


def _cascade_client():
    client = SyntheticCalibrationClient()
    client.provider = "unit-test"
    client.model = "judge-v1"
    return client


def _cascade_input():
    sample = _dataset()["samples"][2]
    decision = {**sample["decision"], "player_id": "actor", "target_id": "target"}
    state = {
        "players": [
            {"id": "actor", "name": "Actor", "role": "Villager", "alignment": "village"},
            {"id": "target", "name": "Target", "role": "Villager", "alignment": "village"},
        ]
    }
    return decision, state


def test_actual_scoring_cascade_preserves_rules_without_approved_calibration():
    from backend.eval.per_step_scorer import PerStepScorer

    decision, state = _cascade_input()
    scorer = PerStepScorer(llm_client=_cascade_client())
    rule = scorer.score_vote(decision, state).overall_score
    score = scorer.score_all([decision], state, [], light_llm=True, heavy_llm=True)[0]
    assert score.overall_score == rule
    assert score.scoring_tier == "deterministic"
    assert score.light_llm_score is None
    assert score.heavy_llm_score is None
    assert score.metadata["judge_calibration"]["single_step"]["fallback_reason"] == "calibration_missing"
    assert score.metadata["judge_calibration"]["panel_step"]["fallback_reason"] == "calibration_missing"


def test_actual_scoring_cascade_uses_identity_and_mode_matched_calibration():
    from backend.eval.per_step_scorer import PerStepScorer

    decision, state = _cascade_input()
    single, panel = _simulated_approved_profile(), _simulated_approved_profile("panel_step")
    scorer = PerStepScorer(
        llm_client=_cascade_client(), calibration_profiles={"single_step": single, "panel_step": panel}
    )
    score = scorer.score_all([decision], state, [], light_llm=True, heavy_llm=True)[0]
    assert score.overall_score == pytest.approx(0.4, abs=0.001)
    assert score.scoring_tier == "heavy_llm"
    assert score.metadata["judge_calibration"]["single_step"]["calibration_id"] == single["calibration_id"]
    assert score.metadata["judge_calibration"]["panel_step"]["calibration_id"] == panel["calibration_id"]
    mismatched = PerStepScorer(llm_client=_cascade_client(), calibration_profiles={"panel_step": single})
    score = mismatched.score_all([decision], state, [], heavy_llm=True)[0]
    assert score.scoring_tier == "deterministic"
    assert score.metadata["judge_calibration"]["panel_step"]["fallback_reason"] == "calibration_identity_mismatch"


@pytest.mark.parametrize("responses", [(1, 1, 9), (4, 4, None)])
def test_panel_disagreement_or_partial_judges_prevent_runtime_llm_upgrade(responses):
    from backend.eval.per_step_scorer import PerStepScorer

    client = _cascade_client()
    outputs = iter(responses)

    def chat(*_args, **_kwargs):
        value = next(outputs)
        verdict = {} if value is None else {"T1_score": value, "T2_score": value, "confidence": 0.95}
        return {"choices": [{"message": {"content": json.dumps(verdict)}}]}

    client.chat_sync = chat
    decision, state = _cascade_input()
    scorer = PerStepScorer(
        llm_client=client, calibration_profiles={"panel_step": _simulated_approved_profile("panel_step")}
    )
    score = scorer.score_all([decision], state, [], heavy_llm=True)[0]
    assert score.scoring_tier == "deterministic"
    assert score.metadata["judge_calibration"]["panel_step"]["fallback_reason"] == "low_judge_confidence"


def test_cli_offline_exports_and_persists_demo_only(tmp_path):
    output, db = tmp_path / "calibration.json", tmp_path / "calibration.sqlite"
    command = [
        sys.executable,
        "scripts/calibrate_track_b_judge.py",
        "--input",
        str(FIXTURE),
        "--provider",
        "fake",
        "--demo-small",
        "--output",
        str(output),
        "--sqlite-store",
        str(db),
    ]
    env = {**os.environ, "AIWEREWOLF_SKIP_DOTENV": "true"}
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, result.stderr
    profile = json.loads(output.read_text())
    assert profile["status"] == "demonstration"
    assert profile["auto_promotion_allowed"] is False
    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as session:
        assert session.query(JudgeCalibration).count() == 1
        assert latest_approved_calibration(session) is None
    engine.dispose()


def test_cli_rejects_ambiguous_provenance_without_artifact(tmp_path):
    source, output = tmp_path / "ambiguous.json", tmp_path / "output.json"
    dataset = _dataset()
    dataset.pop("synthetic")
    source.write_text(json.dumps(dataset))
    result = subprocess.run(
        [sys.executable, "scripts/calibrate_track_b_judge.py", "--input", str(source), "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert not output.exists()


def test_provider_and_parse_failures_log_only_safe_exception_types(caplog):
    from backend.eval.judge_rubric import STRATEGIST_RUBRIC

    marker = "SIMULATED_PRIVATE_PROVIDER_MESSAGE"
    client = SyntheticCalibrationClient()

    def fail(*_args, **_kwargs):
        raise RuntimeError(marker)

    client.chat_sync = fail
    panel = LLMJudgePanel(client=client)
    assert panel.score_step({}, {}) is None
    raw = json.dumps({f"{STRATEGIST_RUBRIC[0].id}_score": marker})
    assert panel._parse_judge_output(raw, STRATEGIST_RUBRIC) == []
    assert marker not in caplog.text
    assert "judge.provider.failed" in caplog.text
    assert "judge.parse.failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "ValueError" in caplog.text
