from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage

from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType, Phase
from backend.engine.rules import build_players, get_role_configuration


class DeterministicCognitiveLLM:
    """Tiny fake LLM that exercises AgentLoop parsing without external APIs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, messages):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        self.calls.append(text)
        target = self._target_from_prompt(text)

        if "输出 JSON" in text:
            return AIMessage(content=json.dumps({
                "target": target,
                "reasoning": "offline direct-call decision",
            }, ensure_ascii=False))

        if "【任务：发言】" in text:
            return AIMessage(content="DECISION: " + json.dumps({
                "speech": f"我先按公开信息发言，重点观察 {target} 的站边和票型。",
                "reasoning": "offline cognitive speech",
            }, ensure_ascii=False))

        return AIMessage(content="DECISION: " + json.dumps({
            "target": target,
            "reasoning": "offline cognitive target",
        }, ensure_ascii=False))

    @staticmethod
    def _target_from_prompt(text: str) -> str:
        self_match = re.search(r"你是\s+\d+号:([^，\n]+)", text)
        self_name = self_match.group(1).strip() if self_match else ""
        names = [name.strip() for name in re.findall(r"\d+号:([^，\n]+)", text)]
        for name in names:
            if name and name != self_name:
                return name
        return names[0] if names else "P1"


def test_cognitive_agents_complete_offline_game_and_emit_decisions() -> None:
    seed = 42
    roles = get_role_configuration(7)
    players = build_players(roles, seed=seed)
    fake_llm = DeterministicCognitiveLLM()
    cognitive_agents = {
        player.id: create_cognitive_agent_with_character(
            player_id=player.id,
            role=player.role.value,
            llm=fake_llm,
            player_name=player.name,
            player_seat=player.seat,
            character=None,
        )
        for player in players
    }
    for player in players:
        player.agent_type = "llm"
    game = WerewolfGame(players=players, agents=cognitive_agents, seed=seed, max_days=3)

    state = game.play()

    assert state.phase == Phase.GAME_END
    assert state.winner is not None
    assert len(state.players) == 7
    assert any(event.type == EventType.CHAT_MESSAGE for event in state.events)
    assert any(event.type == EventType.VOTE_CAST for event in state.events)
    assert any(event.type == EventType.NIGHT_ACTION for event in state.events)
    assert fake_llm.calls
    assert any("【任务：发言】" in call for call in fake_llm.calls)
    assert any("【任务：投票】" in call for call in fake_llm.calls)
    assert any("【任务：夜晚行动】" in call for call in fake_llm.calls)
    assert state.decision_records
    assert all(record.parsed_action for record in state.decision_records)
