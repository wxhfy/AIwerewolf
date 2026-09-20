from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import HarnessBudget
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.agent_harness import PlannerContext
from backend.domains.werewolf.planner import LLMActionPlanner


class RepairingClient:
    model = "test-model"
    provider = "test-provider"

    def __init__(self) -> None:
        self.calls = []

    def chat_sync(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        content = "not json" if len(self.calls) == 1 else '{"option_id":"vote:P2","response":{},"reasoning":"repaired"}'
        return {"choices": [{"message": {"content": content}}], "usage": {}}


def test_planner_repairs_invalid_json_once_with_remaining_deadline() -> None:
    request = DecisionRequest(
        request_id="request-1",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        budget=HarnessBudget(max_steps=1, deadline_ms=3000),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )
    client = RepairingClient()

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.metadata["repair_used"] is True
    assert len(client.calls) == 2
    assert client.calls[1][1]["request_timeout_seconds"] <= client.calls[0][1]["request_timeout_seconds"]


def test_planner_drops_response_payload_for_closed_action() -> None:
    client = RepairingClient()
    client.chat_sync = lambda messages, **kwargs: {
        "choices": [
            {
                "message": {
                    "content": '{"option_id":"vote:P2","response":{"extra":true},"reasoning":"vote"}'
                }
            }
        ],
        "usage": {},
    }
    request = DecisionRequest(
        request_id="request-2",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.response == {}


def test_planner_falls_back_when_model_times_out() -> None:
    client = RepairingClient()

    def timeout(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    client.chat_sync = timeout
    request = DecisionRequest(
        request_id="request-3",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.metadata["fallback_used"] is True
    assert "TimeoutError" in step.action_selection.metadata["fallback_error"]


def test_planner_uses_tool_call_when_client_supports_it() -> None:
    client = RepairingClient()
    client.supports_tool_calling = True

    def tool_call(messages, **kwargs):
        assert kwargs["tools"][0]["function"]["name"] == "submit_action"
        assert kwargs["tool_choice"]["function"]["name"] == "submit_action"
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "submit_action",
                                    "arguments": '{"option_id":"vote:P2","response":{"ignored":true},"reasoning":"tool"}',
                                }
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        }

    client.chat_sync = tool_call
    request = DecisionRequest(
        request_id="request-4",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.response == {}
    assert step.action_selection.metadata["fallback_used"] is False


def test_fallback_uses_subjective_beliefs_instead_of_first_option() -> None:
    client = RepairingClient()

    def timeout(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    client.chat_sync = timeout
    request = DecisionRequest(
        request_id="request-5",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={},
            private_memory=(
                {
                    "beliefs": [
                        {"player_id": "P2", "wolf_probability": 0.2, "confidence": 0.8},
                        {"player_id": "P3", "wolf_probability": 0.9, "confidence": 0.7},
                    ]
                },
            ),
        ),
        action_space=ActionSpace(
            options=(
                ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),
                ActionOption(option_id="vote:P3", action_type="vote", parameters={"target_id": "P3"}),
            )
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P3"
