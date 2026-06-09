from __future__ import annotations

import json

import pytest

from scripts.target_seat_trackc_ab_experiment import TargetGameSubprocessError
from scripts.target_seat_trackc_ab_experiment import build_failure_record
from scripts.target_seat_trackc_ab_experiment import completed_sides_by_seed
from scripts.target_seat_trackc_ab_experiment import load_previous_failures
from scripts.target_seat_trackc_ab_experiment import load_previous_results
from scripts.target_seat_trackc_ab_experiment import result_seeds
from scripts.target_seat_trackc_ab_experiment import run_target_game_with_optional_timeout
from scripts.target_seat_trackc_ab_experiment import validate_resume_payload
from scripts.target_seat_trackc_ab_experiment import write_jsonl_rows
from scripts.target_seat_trackc_ab_experiment import write_partial


def _resume_payload() -> dict:
    return {
        "runner": "target_seat_trackc_ab_experiment.py",
        "target_role": "Seer",
        "target_occurrence": 1,
        "player_count": 7,
        "max_days": 20,
        "baseline_framework": "basic_react",
        "candidate_framework": "rag_react",
        "model_pool": ["doubao:ep"],
        "baseline_results": [{"seed": 9301, "side": "baseline", "value": 1}],
        "candidate_results": [{"seed": 9301, "side": "candidate", "value": 2}],
        "failures": [{"seed": 9302, "side": "baseline", "error_type": "Timeout"}],
    }


def test_resume_payload_validation_accepts_matching_metadata(tmp_path) -> None:
    payload = _resume_payload()

    validate_resume_payload(
        payload,
        path=tmp_path / "target_seat_ab_Seer.json",
        target_role="Seer",
        target_occurrence=1,
        player_count=7,
        max_days=20,
        baseline_framework="basic_react",
        candidate_framework="rag_react",
        model_pool=["doubao:ep"],
    )

    baseline, candidate = load_previous_results(payload)
    assert baseline == [{"seed": 9301, "side": "baseline", "value": 1}]
    assert candidate == [{"seed": 9301, "side": "candidate", "value": 2}]
    assert load_previous_failures(payload) == [{"seed": 9302, "side": "baseline", "error_type": "Timeout"}]


def test_resume_payload_validation_rejects_mismatched_metadata(tmp_path) -> None:
    payload = _resume_payload()

    with pytest.raises(RuntimeError, match="target_role"):
        validate_resume_payload(
            payload,
            path=tmp_path / "target_seat_ab_Seer.json",
            target_role="Witch",
            target_occurrence=1,
            player_count=7,
            max_days=20,
            baseline_framework="basic_react",
            candidate_framework="rag_react",
            model_pool=["doubao:ep"],
        )

    with pytest.raises(RuntimeError, match="model_pool"):
        validate_resume_payload(
            payload,
            path=tmp_path / "target_seat_ab_Seer.json",
            target_role="Seer",
            target_occurrence=1,
            player_count=7,
            max_days=20,
            baseline_framework="basic_react",
            candidate_framework="rag_react",
            model_pool=["ark:other"],
        )


def test_resume_helpers_dedupe_completed_sides_and_write_jsonl(tmp_path) -> None:
    baseline = [{"seed": "9301", "side": "baseline"}, {"seed": 9302, "side": "baseline"}]
    candidate = [{"seed": 9301, "side": "candidate"}, {"seed": "bad", "side": "candidate"}]

    completed = completed_sides_by_seed(baseline, candidate)
    assert sorted(completed) == [(9301, "baseline"), (9301, "candidate"), (9302, "baseline")]
    assert result_seeds(baseline, candidate) == [9301, 9302]

    out = tmp_path / "resumed.games.jsonl"
    write_jsonl_rows(out, [*baseline, *candidate])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows == [*baseline, *candidate]


def test_write_partial_includes_long_run_metadata(tmp_path) -> None:
    partial_path = tmp_path / "target.partial.json"
    games_jsonl = tmp_path / "target.games.jsonl"
    failures_jsonl = tmp_path / "target.failures.jsonl"

    write_partial(
        partial_path,
        target_role="Seer",
        baseline_results=[{"seed": 1, "side": "baseline"}],
        candidate_results=[],
        failures=[{"seed": 1, "side": "candidate", "error_type": "Timeout"}],
        games_jsonl=games_jsonl,
        failures_jsonl=failures_jsonl,
        resume_from=tmp_path / "previous.json",
        append=True,
        game_timeout_s=120,
    )

    payload = json.loads(partial_path.read_text(encoding="utf-8"))
    assert payload["target_role"] == "Seer"
    assert payload["baseline_completed"] == 1
    assert payload["candidate_completed"] == 0
    assert payload["failure_count"] == 1
    assert payload["games_jsonl"] == str(games_jsonl)
    assert payload["failures_jsonl"] == str(failures_jsonl)
    assert payload["resume_from"].endswith("previous.json")
    assert payload["append"] is True
    assert payload["game_timeout_s"] == 120


def test_target_game_timeout_wrapper_uses_direct_path_when_disabled(monkeypatch) -> None:
    sentinel = object()

    def fake_run_target_game(**kwargs):
        assert kwargs == {"seed": 9301, "side": "baseline"}
        return sentinel

    monkeypatch.setattr("scripts.target_seat_trackc_ab_experiment.run_target_game", fake_run_target_game)

    assert run_target_game_with_optional_timeout(timeout_s=0, seed=9301, side="baseline") is sentinel


def test_target_game_subprocess_error_exposes_child_payload() -> None:
    exc = TargetGameSubprocessError(
        {
            "error_type": "ValueError",
            "error": "bad side game",
            "traceback": "child traceback",
        }
    )

    assert str(exc) == "bad side game"
    assert exc.error_type == "ValueError"
    assert exc.child_traceback == "child traceback"


def test_target_game_failure_record_is_structured() -> None:
    exc = TargetGameSubprocessError(
        {
            "error_type": "RuntimeError",
            "error": "child failed",
            "traceback": "traceback text",
        }
    )

    record = build_failure_record(
        exc,
        seed=9301,
        side="candidate",
        target_role="Seer",
        elapsed_s=1.25,
        timeout_s=30,
    )

    assert record["seed"] == 9301
    assert record["side"] == "candidate"
    assert record["target_role"] == "Seer"
    assert record["error_type"] == "RuntimeError"
    assert record["error"] == "child failed"
    assert record["traceback"] == "traceback text"
    assert record["external_failure"] is True
    assert record["timeout_s"] == 30
