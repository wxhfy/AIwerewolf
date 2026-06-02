from backend.agents.llm_agent import LLMAgent
from backend.engine.models import Role
from backend.engine.visibility import PlayerView


def _agent_and_view() -> tuple[LLMAgent, PlayerView]:
    agent = LLMAgent(
        "p1",
        provider="doubao",
        model="ep-test",
        api_key="test-key",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    view = PlayerView(
        player_id="p1",
        day=1,
        phase="DAY_SPEECH",
        self_player={
            "id": "p1",
            "seat": 1,
            "name": "P1",
            "role": Role.VILLAGER.value,
            "alignment": "village",
            "persona": {"mbti": "INTJ"},
        },
        players=[
            {"id": "p1", "seat": 1, "name": "P1", "alive": True},
            {"id": "p2", "seat": 2, "name": "P2", "alive": True},
            {"id": "p3", "seat": 3, "name": "P3", "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent.view = view
    return agent, view


def test_player_memory_preserves_structured_suspects() -> None:
    agent, view = _agent_and_view()
    trace = {
        "observation": {"noticed_events": [], "suspicious_points": []},
        "reasoning": {
            "reason_summary": "2号发言偏滑",
            "suspected_players": [
                {"player_ref": "2号", "suspicion_level": 0.64, "reason": "没有解释自己的观察点"}
            ],
            "trusted_players": [{"player_ref": "3号", "trust_level": 0.55}],
        },
        "planning": {"intent": "继续追问2号", "target_players": ["2号"], "strategy": ""},
    }

    normalized = agent._normalize_agent_trace({**trace, "speaking": {"final": "先问2号。"}}, "先问2号。")
    updates = agent._update_player_memory_from_trace(normalized, "先问2号。", view)
    snapshot = agent._player_memory_snapshot()

    assert snapshot["suspected_players"] == [
        {"player_ref": "2号", "level": 0.64, "reason": "没有解释自己的观察点", "round": 1}
    ]
    assert snapshot["trusted_players"] == [
        {"player_ref": "3号", "level": 0.55, "reason": "暂时没有明显矛盾", "round": 1}
    ]
    assert all("{'player_ref'" not in item["player_ref"] for item in snapshot["suspected_players"])
    assert any(item["field"] == "suspected_players" and item["action"] == "upsert" for item in updates)


def test_player_memory_block_does_not_render_dict_strings() -> None:
    agent, view = _agent_and_view()
    trace = {
        "observation": {"noticed_events": [], "suspicious_points": []},
        "reasoning": {
            "suspected_players": [{"target": "2号", "score": 0.7, "evidence": "改票没有解释"}],
            "trusted_players": [],
        },
        "planning": {},
        "speaking": {"final": "2号改票要解释。"},
    }

    normalized = agent._normalize_agent_trace(trace, "2号改票要解释。")
    agent._update_player_memory_from_trace(normalized, "2号改票要解释。", view)
    block = agent._build_player_memory_block()

    assert "{'player_ref'" not in block
    assert "{'target'" not in block
    assert "2号，怀疑度 0.70：改票没有解释" in block


def test_player_memory_filters_private_strategy_text() -> None:
    agent, view = _agent_and_view()
    trace = {
        "observation": {
            "noticed_events": ["公开发言都在讨论2号"],
            "suspicious_points": ["作为狼需要装好人视角", "作为特殊身份不要暴露信息"],
        },
        "reasoning": {
            "suspected_players": [{"player_ref": "2号", "reason": "作为狼需要装好人视角"}],
            "trusted_players": [],
            "self_risk": "作为特殊身份不要暴露信息",
        },
        "planning": {
            "intent": "伪装中立观察者引导好人内讧",
            "strategy": "作为特殊身份不要暴露信息，暂时不跳身份",
            "target_players": [],
        },
        "speaking": {"final": "我先听2号解释。"},
    }

    normalized = agent._normalize_agent_trace(trace, "我先听2号解释。")
    agent._update_player_memory_from_trace(normalized, "我先听2号解释。", view)
    snapshot_text = str(agent._player_memory_snapshot())
    block = agent._build_player_memory_block()

    assert "作为狼" not in snapshot_text
    assert "作为特殊身份" not in snapshot_text
    assert "伪装中立" not in snapshot_text
    assert "不跳身份" not in snapshot_text
    assert "装好人视角" not in block
    assert "不要暴露信息" not in block
