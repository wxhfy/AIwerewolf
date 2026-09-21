from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.domains.werewolf.communication import audit_public_speech


def _request(role: str) -> DecisionRequest:
    return DecisionRequest(
        request_id="speech-audit",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.talk", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={
                "self_player": {"id": "P1", "name": "Alice", "role": role},
                "players": [
                    {"id": "P1", "name": "Alice"},
                    {"id": "P2", "name": "Bob"},
                    {"id": "P3", "name": "Carol"},
                ],
            },
        ),
        action_space=ActionSpace(options=(ActionOption(option_id="talk", action_type="talk"),)),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        domain_metadata={"role": role},
    )


def test_wolf_private_perspective_is_rejected() -> None:
    audit = audit_public_speech(
        _request("Werewolf"),
        "Carol was attacked and killed by us at night.",
    )

    assert "wolf_private_perspective" in audit.violations


def test_implicit_wolf_objective_is_rejected() -> None:
    audit = audit_public_speech(
        _request("Werewolf"),
        "As a werewolf, we should move public suspicion toward non-wolves without exposing our identity.",
    )

    assert "wolf_private_perspective" in audit.violations


def test_witch_private_action_is_rejected() -> None:
    audit = audit_public_speech(_request("Witch"), "I kept my potion and did not save anyone.")

    assert "witch_night_action_disclosure" in audit.violations


def test_seer_may_publish_own_check_and_ids_are_rendered_as_names() -> None:
    audit = audit_public_speech(_request("Seer"), "I am the Seer. My check says P3 is wolf.")

    assert audit.accepted
    assert "P3" not in audit.speech
    assert "Carol" in audit.speech


def test_internal_probability_is_rejected() -> None:
    audit = audit_public_speech(_request("Villager"), "P2 has wolf probability 0.8242.")

    assert "internal_score_disclosure" in audit.violations


def test_non_seer_cannot_claim_a_private_check() -> None:
    audit = audit_public_speech(_request("Guard"), "I checked P3 last night and my check says P3 is safe.")

    assert "role_capability_mismatch" in audit.violations
