from __future__ import annotations

import pytest

from backend.domains.werewolf.context_budget import ContextBudgetExceeded
from backend.domains.werewolf.context_budget import ContextTokenBudgetManager


def _payload() -> dict:
    return {
        "context_manifest": {"schema_version": "werewolf.decision_context.v1"},
        "decision_context": {
            "epistemic_contract": {"confirmed_private_facts": "direct"},
            "identity": {"actor_id": "p1", "role": "seer"},
            "game_contract": {"claim_semantics": "attributed"},
            "situation": {"phase": "day", "roster": [{"id": "p1"}, {"id": "p2"}]},
            "confirmed_private_facts": [
                {"kind": "self_role", "role": "seer"},
                {"kind": "seer_result", "target_id": "p2"},
            ],
            "public_timeline": [
                {"kind": "speech", "seq": index, "text": "old speech " + "x" * 100} for index in range(12)
            ]
            + [{"kind": "player_death", "seq": 99, "text": "p3 died"}],
            "public_claims": [{"kind": "speech", "speaker_id": "p2", "text": "claim " + "y" * 100} for _ in range(8)]
            + [{"kind": "role_claim", "speaker_id": "p2", "role": "seer"}],
            "inferences": [{"target_id": "p2", "confidence": 0.2, "summary": "weak" + "z" * 100} for _ in range(6)],
            "agent_state": {
                "active_goals": [{"text": "find the wolf"}],
                "attention_focus": ["p2"],
                "recalled_episodes": [{"text": "old episode " + "r" * 100} for _ in range(3)],
                "social_reads": [{"target_id": "p2", "read": "uncertain"} for _ in range(3)],
            },
            "external_knowledge": [{"content": "general advice " + "a" * 100} for _ in range(2)],
            "current_task": {"decision_frame": {"objective": "choose"}, "prior_reflections": ["old reflection"]},
        },
        "action_options": [{"option_id": "talk", "action_type": "public_speech"}],
        "agent_profile": {"persona": {"name": "A", "reasoning_style": "careful", "humor_style": "dry"}},
        "public_communication_policy": {"must_not_reveal": ["role"]},
    }


def test_budget_prunes_complete_low_value_items_and_keeps_invariants() -> None:
    manager = ContextTokenBudgetManager()
    original = _payload()
    fitted = manager.fit(original, input_token_budget=1800, fixed_parts=("system prompt",))
    context = fitted["decision_context"]
    assert context["identity"]["role"] == "seer"
    assert context["confirmed_private_facts"] == original["decision_context"]["confirmed_private_facts"]
    assert fitted["action_options"][0]["option_id"] == "talk"
    assert context["public_timeline"][-1]["kind"] == "player_death"
    report = fitted["context_manifest"]["context_budget"]
    assert report["original_estimated_input_tokens"] > report["estimated_input_tokens"]
    assert report["pruned_counts"]
    assert report["estimated_input_tokens"] <= 1800
    assert ContextTokenBudgetManager.estimate(fitted, fixed_parts=("system prompt",)) <= 1800


def test_budget_does_not_mutate_original_payload() -> None:
    manager = ContextTokenBudgetManager()
    original = _payload()
    manager.fit(original, input_token_budget=1800)
    assert len(original["decision_context"]["public_timeline"]) == 13
    assert "context_budget" not in original["context_manifest"]


def test_budget_reports_impossible_mandatory_context() -> None:
    with pytest.raises(ContextBudgetExceeded):
        ContextTokenBudgetManager().fit(_payload(), input_token_budget=20)
