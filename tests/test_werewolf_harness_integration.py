from backend.application.matches.executor import build_game
from backend.engine.models import Role


def test_match_worker_path_runs_complete_ai_game_through_harness(monkeypatch) -> None:
    monkeypatch.setenv("_TEST_ALLOW_FAKE_LLM", "true")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("MODEL_POOL", "fake:fake-llm")

    game = build_game(
        seed=7,
        player_count=7,
        llm_config={"provider": "fake", "model": "fake-llm"},
    )

    assert game.decision_runtime is not None
    assert not hasattr(game, "agents")

    state = game.play()

    assert state.winner is not None
    assert state.decision_records
    assert all(record.metadata.get("source") == "agent_harness" for record in state.decision_records)
    assert all(record.metadata.get("harness_request_id") for record in state.decision_records)
    assert all(record.metadata.get("harness_event_count") for record in state.decision_records)
    assert all(record.metadata.get("harness_trace_storage") == "agent_harness_events" for record in state.decision_records)
    assert all("harness_events" not in record.metadata for record in state.decision_records)
    assert all(
        set(record.metadata["harness_event_types"])
        >= {"run.started", "action.accepted", "run.completed"}
        for record in state.decision_records
    )

    villager = next(player for player in state.players if player.role == Role.VILLAGER)
    villager_record = next(record for record in state.decision_records if record.player_id == villager.id)
    assert villager_record.observation["known_wolves"] == []
    for visible_player in villager_record.observation["players"]:
        if visible_player["id"] == villager.id:
            assert visible_player["role"] == Role.VILLAGER.value
        else:
            assert "role" not in visible_player
            assert "alignment" not in visible_player
