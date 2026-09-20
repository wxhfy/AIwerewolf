from types import SimpleNamespace

from backend.db.persist import _decision_is_llm


def test_model_backed_harness_decision_counts_as_llm_without_token_usage() -> None:
    decision = SimpleNamespace(
        parsed_action={
            "metadata": {
                "source": "agent_harness",
                "model_backed": True,
                "provider": "fake",
                "model": "fake-llm",
            }
        },
        prompt_tokens=0,
        completion_tokens=0,
    )

    assert _decision_is_llm(decision) is True
