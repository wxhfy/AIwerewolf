from __future__ import annotations

import json

import pytest

from scripts.target_seat_trackc_ab_experiment import completed_sides_by_seed
from scripts.target_seat_trackc_ab_experiment import load_previous_results
from scripts.target_seat_trackc_ab_experiment import result_seeds
from scripts.target_seat_trackc_ab_experiment import validate_resume_payload
from scripts.target_seat_trackc_ab_experiment import write_jsonl_rows


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
