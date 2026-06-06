from __future__ import annotations

import json
import re

import pytest
from langchain_core.messages import AIMessage

from backend.agents.cognitive.agent_loop import AgentLoop
from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import PlayerInfo
from backend.agents.cognitive.observe import observe
from backend.agents.cognitive.reflect import Reflector
from backend.agents.cognitive.reflect import reflections_to_knowledge_docs
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType
from backend.engine.models import Phase
from backend.engine.rules import build_players
from backend.engine.rules import get_role_configuration
from backend.engine.visibility import PlayerView


class DeterministicCognitiveLLM:
    """Tiny fake LLM that exercises AgentLoop parsing without external APIs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, messages):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        self.calls.append(text)
        target = self._target_from_prompt(text)

        if "输出 JSON" in text:
            return AIMessage(
                content=json.dumps(
                    {
                        "target": target,
                        "reasoning": "offline direct-call decision",
                    },
                    ensure_ascii=False,
                )
            )

        if "【任务：发言】" in text:
            return AIMessage(
                content="DECISION: "
                + json.dumps(
                    {
                        "speech": f"我先按公开信息发言，重点观察 {target} 的站边和票型。",
                        "reasoning": "offline cognitive speech",
                    },
                    ensure_ascii=False,
                )
            )

        return AIMessage(
            content="DECISION: "
            + json.dumps(
                {
                    "target": target,
                    "reasoning": "offline cognitive target",
                },
                ensure_ascii=False,
            )
        )

    @staticmethod
    def _target_from_prompt(text: str) -> str:
        self_match = re.search(r"你是\s+\d+号:([^，\n]+)", text)
        self_name = self_match.group(1).strip() if self_match else ""
        legal_match = re.search(r"合法目标[:：]\s*([^\n]+)", text)
        if legal_match:
            legal_names = [name.strip() for name in re.findall(r"\d+号:([^，\n]+)", legal_match.group(1))]
            for name in legal_names:
                if name and name != self_name:
                    return name
            if legal_names:
                return legal_names[0]
        names = [name.strip() for name in re.findall(r"\d+号:([^，\n]+)", text)]
        for name in names:
            if name and name != self_name:
                return name
        return names[0] if names else "P1"


class NonDecisionLLM:
    def invoke(self, messages):
        return AIMessage(content="我还需要继续想想，但没有按格式输出。")


class MalformedReflectionLLM:
    def invoke(self, messages):
        return AIMessage(content='DECISION: {"target": "2号", "reasoning": "not a reflection"}')


def test_agent_loop_raises_when_llm_never_outputs_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    loop = AgentLoop(NonDecisionLLM(), "system prompt", action_type="vote")

    with pytest.raises(RuntimeError, match="failed to produce a DECISION"):
        loop.run(obs, Memory("P1", "Villager"))


def test_reflector_malformed_output_still_produces_knowledge_docs() -> None:
    reflections = Reflector(MalformedReflectionLLM()).reflect_game(
        "game-reflect-1",
        [
            {
                "player_id": "P1",
                "player_name": "Alice",
                "role": "Seer",
                "persona": {"mbti": "INTJ"},
                "won": False,
                "decisions": [{"action_type": "vote", "target": "Bob", "speech": ""}],
                "game_events": [{"type": "VOTE_CAST", "description": "Alice voted Bob"}],
            }
        ],
    )
    docs = reflections_to_knowledge_docs(reflections, "game-reflect-1")

    assert reflections[0].confidence == 0.35
    assert docs
    assert all(doc["doc_type"] == "reflection" for doc in docs)
    assert all(doc["source_report_ids"] == ["game-reflect-1"] for doc in docs)


def test_observe_keeps_engine_seer_result_private_info() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Seer", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Seer", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[
            {
                "type": "PRIVATE_INFO",
                "day": 1,
                "payload": {
                    "kind": "seer_result",
                    "target_id": "P2",
                    "target_name": "Bob",
                    "is_wolf": True,
                    "message": "Seer check: Bob is wolf.",
                },
            }
        ],
        known_wolves=[],
        observations=[],
    )

    obs = observe(view, "Seer")

    assert obs.private["seer_check"]["target_name"] == "Bob"
    assert obs.private["seer_check"]["is_wolf"] is True


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
