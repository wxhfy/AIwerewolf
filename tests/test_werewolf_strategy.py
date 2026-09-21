from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.domains.werewolf.strategy import build_strategy_snapshot
from backend.domains.werewolf.strategy import strategy_score_for_option


def _request(kind: str = "werewolf.vote") -> DecisionRequest:
    return DecisionRequest(
        request_id="strategy-request",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="werewolf:Villager:test"),
        decision_point=DecisionPoint(kind=kind, sequence=5),
        information_state=InformationState(
            schema_id="werewolf.player-view",
            schema_version="1",
            observation={
                "self_player": {"id": "P1", "name": "甲", "role": "Villager", "alive": True},
                "players": [
                    {"id": "P1", "name": "甲", "alive": True},
                    {"id": "P2", "name": "乙", "alive": True},
                    {"id": "P3", "name": "丙", "alive": True},
                ],
                "known_wolves": [],
            },
        ),
        action_space=ActionSpace(
            options=(
                ActionOption("vote:P2", "vote", {"target_id": "P2"}),
                ActionOption("vote:P3", "vote", {"target_id": "P3"}),
            )
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        domain_metadata={"role": "Villager"},
    )


def _memory() -> dict:
    return {
        "beliefs": [
            {
                "player_id": "P2",
                "wolf_probability": 0.72,
                "confidence": 0.7,
                "evidence_for": ["P2 broke a vote commitment"],
                "evidence_against": [],
            },
            {
                "player_id": "P3",
                "wolf_probability": 0.42,
                "confidence": 0.4,
                "evidence_for": [],
                "evidence_against": ["consistent public stance"],
            },
        ],
        "relationships": [
            {"player_id": "P2", "trust": -0.2, "threat": 0.2, "influence": 0.1},
            {"player_id": "P3", "trust": 0.2, "threat": 0.0, "influence": 0.3},
        ],
        "recent_claims": [
            {"speaker_id": "P2", "kind": "role_claim", "value": "Seer", "target_id": "P2"},
            {"speaker_id": "P3", "kind": "role_claim", "value": "Seer", "target_id": "P3"},
            {"speaker_id": "P2", "kind": "contradiction", "value": "vote", "target_id": "P2"},
        ],
    }


def test_strategy_snapshot_surfaces_contested_roles_and_ranked_evidence() -> None:
    snapshot = build_strategy_snapshot(_request(), _memory())

    assert snapshot["provenance"] == "derived_only_from_actor_visible_memory"
    assert snapshot["contested_roles"] == [{"role": "Seer", "claimants": ["P2", "P3"]}]
    assert snapshot["suspect_ranking"][0]["player_id"] == "P2"
    assert snapshot["suspect_ranking"][0]["contradictions"] == 1
    assert snapshot["suspect_ranking"][0]["evidence_for"] == ["P2 broke a vote commitment"]


def test_strategy_score_changes_with_decision_kind() -> None:
    vote_request = _request("werewolf.vote")
    guard_request = _request("werewolf.guard")

    assert strategy_score_for_option(vote_request, _memory(), "P2") > strategy_score_for_option(
        vote_request, _memory(), "P3"
    )
    assert strategy_score_for_option(guard_request, _memory(), "P3") > strategy_score_for_option(
        guard_request, _memory(), "P2"
    )
