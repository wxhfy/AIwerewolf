from __future__ import annotations

from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import HarnessBudget
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.eval.model_compatibility import evaluate_model
from backend.eval.model_compatibility import summarize_results


class ValidClient:
    model = "valid-model"
    provider = "test"
    supports_tool_calling = False

    def complete(self, messages, **kwargs):
        return {
            "choices": [{"message": {"content": '{"option_id":"vote:P2","response":{},"reasoning":"ok"}'}}],
            "usage": {},
        }


class TimeoutClient:
    model = "timeout-model"
    provider = "test"
    supports_tool_calling = False

    def complete(self, messages, **kwargs):
        raise TimeoutError("upstream timeout")


def _request() -> DecisionRequest:
    return DecisionRequest(
        request_id="compatibility-request",
        environment_id="werewolf",
        episode_id="game-compatibility",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-compatibility", actor_id="P1"),
        budget=HarnessBudget(max_steps=1, deadline_ms=1000),
    )


def test_compatibility_runner_keeps_same_request_contract() -> None:
    request = _request()
    valid = evaluate_model(request, ValidClient())
    degraded = evaluate_model(request, TimeoutClient())

    assert valid.action_valid is True
    assert valid.fallback_used is False
    assert degraded.action_valid is True
    assert degraded.safe_degradation_used is True
    assert degraded.failure_kind == "timeout"
    summary = summarize_results([valid, degraded])
    assert summary["valid_action_rate"] == 1.0
    assert summary["safe_degradation_rate"] == 0.5
    assert summary["failure_kinds"] == {"timeout": 1}
