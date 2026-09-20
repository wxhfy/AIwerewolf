from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSelection
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import AgentHarness
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import HarnessStep
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.game_runtime import DecisionBatch
from backend.game_runtime import EpisodeRunner


@dataclass
class HiddenChoiceState:
    terminal: bool = False
    choices: dict[str, str] = field(default_factory=dict)


def _choice_request(actor_id: str) -> DecisionRequest:
    return DecisionRequest(
        request_id=f"choice:{actor_id}",
        environment_id="hidden-choice",
        episode_id="episode-1",
        actor=ActorRef(actor_id=actor_id, agent_definition_id="first-option"),
        decision_point=DecisionPoint(
            kind="round.choose",
            sequence=1,
            simultaneous_group_id="round-1",
        ),
        information_state=InformationState(
            schema_id="hidden-choice.information-state",
            schema_version="1",
            observation={"own_actor_id": actor_id, "submitted_choices": []},
        ),
        action_space=ActionSpace(
            options=(
                ActionOption(option_id=f"{actor_id}:left", action_type="choose", parameters={"value": "left"}),
                ActionOption(option_id=f"{actor_id}:right", action_type="choose", parameters={"value": "right"}),
            )
        ),
        memory_scope=MemoryScope(namespace="episode", episode_id="episode-1", actor_id=actor_id),
    )


class HiddenChoiceAdapter:
    def is_terminal(self, state: HiddenChoiceState) -> bool:
        return state.terminal

    def next_decision_batch(self, state: HiddenChoiceState) -> DecisionBatch:
        assert state.choices == {}
        return DecisionBatch(
            batch_id="round-1",
            mode="simultaneous",
            requests=(_choice_request("actor-1"), _choice_request("actor-2")),
        )

    def apply_actions(self, state, batch, actions):
        assert state.choices == {}
        assert batch.mode == "simultaneous"
        return HiddenChoiceState(
            terminal=True,
            choices={
                request.actor.actor_id: action.parameters["value"]
                for request, action in zip(batch.requests, actions, strict=True)
            },
        )


def test_episode_runner_keeps_simultaneous_actions_sealed_until_batch_resolution() -> None:
    class FirstOptionPlanner:
        def next_step(self, request, context):
            del context
            return HarnessStep.select_action(ActionSelection(option_id=request.action_space.options[0].option_id))

    outcome = EpisodeRunner(AgentHarness(FirstOptionPlanner())).run(
        HiddenChoiceAdapter(),
        HiddenChoiceState(),
    )

    assert outcome.transitions == 1
    assert outcome.decision_count == 2
    assert outcome.final_state.choices == {"actor-1": "left", "actor-2": "left"}


def test_decision_batch_rejects_duplicate_actor() -> None:
    request = _choice_request("actor-1")
    duplicate_actor = replace(request, request_id="choice:actor-1:duplicate")

    with pytest.raises(ValueError, match="actor can appear only once"):
        DecisionBatch(
            batch_id="invalid",
            mode="simultaneous",
            requests=(request, duplicate_actor),
        )
