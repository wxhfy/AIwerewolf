from __future__ import annotations

from uuid import uuid4

from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.agent_harness.contracts import HarnessResult
from backend.agent_harness.contracts import ResolvedAction
from backend.agent_memory import ActorMemoryService
from backend.agent_memory import SqlActorMemoryRepository
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import Game
from backend.db.models import Player


def _event(seq: int, *, event_type: str = "CHAT_MESSAGE", visibility: str = "public", **payload):
    return {
        "id": f"event-{seq}",
        "seq": seq,
        "day": 1,
        "phase": "DAY_SPEECH",
        "type": event_type,
        "visibility": visibility,
        "payload": payload,
    }


def _request(*, actor_id: str = "P1", profile: dict | None = None, events=()) -> DecisionRequest:
    episode_id = "memory-test-game"
    return DecisionRequest(
        request_id=f"request-{uuid4().hex}",
        environment_id="werewolf",
        episode_id=episode_id,
        actor=ActorRef(actor_id=actor_id, agent_definition_id="werewolf:Villager:test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=20),
        information_state=InformationState(
            schema_id="werewolf.player-view",
            schema_version="1",
            observation={
                "day": 1,
                "phase": "DAY_VOTE",
                "self_player": {"id": actor_id, "name": "甲", "role": "Villager"},
                "players": [
                    {"id": actor_id, "name": "甲", "alive": True},
                    {"id": "P2", "name": "乙", "alive": True},
                    {"id": "P3", "name": "丙", "alive": True},
                ],
                "known_wolves": [],
                "observations": [],
                "legal_targets": [{"id": "P2", "name": "乙"}, {"id": "P3", "name": "丙"}],
            },
            visible_history=tuple(events),
        ),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id=episode_id, actor_id=actor_id),
        agent_profile={"persona": dict(profile or {})},
        domain_metadata={"role": "Villager", "day": 1, "phase": "DAY_VOTE"},
    )


def test_context_is_bounded_but_subjective_memory_keeps_older_events() -> None:
    events = tuple(
        _event(seq, actor_id="P2", actor_name="乙", speech=f"第 {seq} 条公开发言") for seq in range(1, 31)
    )
    service = ActorMemoryService()
    prepared = service.prepare(
        _request(
            events=events,
            profile={"memory_bias": "selective", "logic_depth": "deep", "courage": "calculated"},
        )
    )
    state = service.get_state("memory-test-game", "P1")

    assert state is not None
    policy = prepared.information_state.private_memory[0]["memory_policy"]
    assert len(prepared.information_state.visible_history) == policy["raw_event_window"]
    assert len(prepared.information_state.visible_history) < len(events)
    assert len(state.episodic) == len(events)
    assert prepared.information_state.private_memory[0]["retrieved_episodes"]


def test_personality_and_affect_generate_dynamic_memory_policy() -> None:
    service = ActorMemoryService()
    comprehensive = service.prepare(
        _request(
            actor_id="P1",
            profile={"memory_bias": "comprehensive", "logic_depth": "deep", "courage": "bold"},
            events=(_event(1, actor_id="P2", actor_name="乙", speech="观察发言"),),
        )
    )
    selective = service.prepare(
        _request(
            actor_id="P3",
            profile={"memory_bias": "selective", "logic_depth": "shallow", "courage": "cautious"},
            events=(_event(1, actor_id="P2", actor_name="乙", speech="观察发言"),),
        )
    )

    comprehensive_policy = comprehensive.information_state.private_memory[0]["memory_policy"]
    selective_policy = selective.information_state.private_memory[0]["memory_policy"]
    assert comprehensive_policy["raw_event_window"] != selective_policy["raw_event_window"]
    assert comprehensive_policy["retrieval_weights"] != selective_policy["retrieval_weights"]


def test_private_role_fact_only_changes_memory_when_present_in_actor_view() -> None:
    seer_result = _event(
        2,
        event_type="PRIVATE_INFO",
        visibility="private",
        kind="seer_result",
        target_id="P2",
        target_name="乙",
        is_wolf=True,
    )
    service = ActorMemoryService()
    service.prepare(_request(actor_id="P1", events=(seer_result,)))
    service.prepare(_request(actor_id="P3", events=()))

    seer_memory = service.get_state("memory-test-game", "P1")
    villager_memory = service.get_state("memory-test-game", "P3")
    assert seer_memory is not None and villager_memory is not None
    assert seer_memory.beliefs["P2"].wolf_probability > 0.9
    assert villager_memory.beliefs["P2"].wolf_probability == 0.5
    assert all("divine result" not in item.content for item in villager_memory.episodic)


def test_action_is_written_back_as_episodic_and_prospective_context() -> None:
    service = ActorMemoryService()
    request = _request(events=(_event(1, actor_id="P2", actor_name="乙", speech="我怀疑甲"),))
    prepared = service.prepare(request)
    action = ResolvedAction(
        option_id="vote:P2",
        action_type="vote",
        parameters={"target_id": "P2"},
        response={},
        reasoning="乙公开施压且证据不足",
        metadata={},
    )
    service.record_result(
        prepared,
        HarnessResult(status="completed", action=action, events=(), loaded_skills=(), tool_calls=0),
    )
    state = service.get_state("memory-test-game", "P1")

    assert state is not None
    assert state.last_action["target_id"] == "P2"
    assert state.episodic[-1].kind == "self_action"
    assert any("Previous action" in chunk for chunk in state.working_memory)


def test_sql_repository_round_trip() -> None:
    init_db()
    game_id = f"memory-db-{uuid4().hex}"
    player_id = f"player-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="running"))
        db.add(Player(id=player_id, game_id=game_id, seat_no=1, name="甲", role="Villager"))

    repository = SqlActorMemoryRepository()
    service = ActorMemoryService(repository)
    request = _request(actor_id=player_id, events=(_event(1, actor_id="P2", actor_name="乙", speech="公开信息"),))
    request = DecisionRequest(
        **{
            **request.__dict__,
            "episode_id": game_id,
            "memory_scope": MemoryScope(namespace="match", episode_id=game_id, actor_id=player_id),
        }
    )
    prepared = service.prepare(request)
    service.record_result(
        prepared,
        HarnessResult(status="failed", action=None, events=(), loaded_skills=(), tool_calls=0, error="test"),
    )

    restored = ActorMemoryService(repository)
    restored.prepare(request)
    state = restored.get_state(game_id, player_id)
    assert state is not None
    assert state.last_event_seq == 1
    assert state.episodic[0].content.endswith("公开信息")


def test_speech_claims_build_evidence_graph_and_update_beliefs() -> None:
    service = ActorMemoryService()
    speech = _event(1, actor_id="P2", actor_name="P2", speech="I checked P3: P3 is wolf")
    prepared = service.prepare(_request(events=(speech,)))
    state = service.get_state("memory-test-game", "P1")

    assert state is not None
    assert any(claim.kind == "check_claim" and claim.target_id == "P3" for claim in state.claims)
    assert any(edge.target_player_id == "P3" for edge in state.evidence_graph)
    assert state.beliefs["P3"].wolf_probability > 0.5
    assert prepared.information_state.private_memory[0]["recent_claims"]


def test_negated_wolf_claim_is_positive_evidence() -> None:
    service = ActorMemoryService()
    speech = _event(1, actor_id="P2", actor_name="P2", speech="I checked P3: P3 is not a wolf")

    service.prepare(_request(events=(speech,)))
    state = service.get_state("memory-test-game", "P1")

    assert state is not None
    claim = next(item for item in state.claims if item.kind == "check_claim" and item.target_id == "P3")
    assert claim.value == "village"
    assert claim.polarity < 0
    assert state.beliefs["P3"].wolf_probability < 0.5


def test_broken_vote_commitment_is_recorded_as_contradiction() -> None:
    service = ActorMemoryService()
    events = (
        _event(1, actor_id="P2", actor_name="P2", speech="I will vote for P3"),
        _event(2, event_type="VOTE_CAST", voter_id="P2", target_id="P1"),
    )
    service.prepare(_request(events=events))
    state = service.get_state("memory-test-game", "P1")

    assert state is not None
    assert any(claim.kind == "contradiction" and claim.speaker_id == "P2" for claim in state.claims)
    assert state.beliefs["P2"].wolf_probability > 0.5
