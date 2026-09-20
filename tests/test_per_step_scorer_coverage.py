from backend.eval.per_step_scorer import PerStepScorer


def test_generic_lifecycle_action_keeps_full_scoring_coverage() -> None:
    decision = {
        "id": "decision-1",
        "player_id": "P1",
        "player_name": "Sheriff",
        "player_role": "Villager",
        "day": 2,
        "phase": "BADGE_TRANSFER",
        "action_type": "skip",
        "raw_text": "No trustworthy successor is available.",
    }

    scores = PerStepScorer().score_all([decision], {"players": []}, [])

    assert len(scores) == 1
    assert scores[0].decision_id == "decision-1"
    assert scores[0].action_type == "skip"
    assert scores[0].scoring_tier == "deterministic_generic"
    assert scores[0].metadata == {"generic_rubric": True}
