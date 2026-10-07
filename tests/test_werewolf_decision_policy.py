from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSelection
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.domains.werewolf.decision_policy import apply_role_policy


def _request(
    role: str,
    kind: str,
    options: tuple[ActionOption, ...],
    *,
    actor_id: str = "P1",
    known_wolves: list[dict] | None = None,
    history: tuple[dict, ...] = (),
    memory: dict | None = None,
) -> DecisionRequest:
    return DecisionRequest(
        request_id="policy-request",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id=actor_id, agent_definition_id="test"),
        decision_point=DecisionPoint(kind=kind, sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={
                "self_player": {"id": actor_id, "name": "Actor", "role": role},
                "players": [
                    {"id": actor_id, "name": "Actor", "alive": True},
                    {"id": "P2", "name": "Player 2", "alive": True},
                    {"id": "P3", "name": "Player 3", "alive": True},
                ],
                "known_wolves": known_wolves or [],
            },
            visible_history=history,
            private_memory=(memory or {},),
        ),
        action_space=ActionSpace(options=options),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id=actor_id),
        domain_metadata={"role": role, "day": 1},
    )


def test_witch_saves_self_when_confirmed_victim() -> None:
    request = _request(
        "Witch",
        "werewolf.witch",
        (
            ActionOption("witch:hold", "witch_hold"),
            ActionOption("witch:save:P1", "witch_save", {"target_id": "P1"}),
            ActionOption("witch:poison:P2", "witch_poison", {"target_id": "P2"}),
        ),
    )

    result = apply_role_policy(request, ActionSelection("witch:hold", reasoning="keep potion"))

    assert result.option_id == "witch:save:P1"
    assert result.metadata["policy_reason"].startswith("witch_was")


def test_wolf_public_vote_cannot_target_confirmed_teammate() -> None:
    options = (
        ActionOption("vote:P2", "vote", {"target_id": "P2"}),
        ActionOption("vote:P3", "vote", {"target_id": "P3"}),
    )
    request = _request(
        "Werewolf",
        "werewolf.vote",
        options,
        known_wolves=[{"id": "P1"}, {"id": "P2"}],
        memory={"beliefs": [{"player_id": "P3", "wolf_probability": 0.6, "confidence": 0.5}]},
    )

    result = apply_role_policy(request, ActionSelection("vote:P2", reasoning="bus teammate"))

    assert result.option_id == "vote:P3"
    assert result.metadata["policy_original_option_id"] == "vote:P2"


def test_seer_does_not_vote_privately_confirmed_non_wolf() -> None:
    options = (
        ActionOption("vote:P2", "vote", {"target_id": "P2"}),
        ActionOption("vote:P3", "vote", {"target_id": "P3"}),
    )
    seer_result = {
        "seq": 2,
        "type": "PRIVATE_INFO",
        "visibility": "private",
        "payload": {"kind": "seer_result", "target_id": "P2", "is_wolf": False},
    }
    request = _request("Seer", "werewolf.vote", options, history=(seer_result,))

    result = apply_role_policy(request, ActionSelection("vote:P2", reasoning="vote P2"))

    assert result.option_id == "vote:P3"
    assert result.metadata["policy_reason"] == "seer_vote_targeted_a_privately_confirmed_non_wolf"


def test_seer_does_not_repeat_completed_check_from_long_term_private_memory() -> None:
    options = (
        ActionOption("divine:P2", "divine", {"target_id": "P2"}),
        ActionOption("divine:P3", "divine", {"target_id": "P3"}),
    )
    memory = {
        "confirmed_private_facts": [
            {
                "event_seq": 2,
                "summary": "My divine result says Player 2 is not wolf",
                "actor_ids": ["P2"],
                "tags": ["private", "seer_result"],
            }
        ]
    }
    request = _request("Seer", "werewolf.divine", options, memory=memory)

    result = apply_role_policy(request, ActionSelection("divine:P2", reasoning="check again"))

    assert result.option_id == "divine:P3"


def test_hunter_avoids_uncontested_seer_who_publicly_cleared_them() -> None:
    options = (
        ActionOption("shoot:P2", "shoot", {"target_id": "P2"}),
        ActionOption("shoot:P3", "shoot", {"target_id": "P3"}),
    )
    memory = {
        "recent_claims": [
            {"speaker_id": "P2", "kind": "role_claim", "target_id": "P2", "value": "Seer"},
            {"speaker_id": "P2", "kind": "check_claim", "target_id": "P1", "value": "village"},
        ]
    }
    request = _request("Hunter", "werewolf.shoot", options, memory=memory)

    result = apply_role_policy(request, ActionSelection("shoot:P2", reasoning="shoot P2"))

    assert result.option_id == "shoot:P3"
    assert result.metadata["policy_overridden"] is True
