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
from backend.engine.models import ActionType
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


class BadWitchLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content="今晚我再想想，不输出结构化 JSON。")


class EmptySpeechLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"speech": "", "reasoning": "empty speech"}')


class InvalidDirectTargetLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='{"target": "不存在的玩家", "reasoning": "invalid target"}')


class InvalidNightTargetLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"target": "狼人队友", "reasoning": "invalid wolf target"}')


class SkipNightTargetLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"target": "跳过", "reasoning": "skip required target"}')


class NativeDecisionLLM:
    """Fake native function-calling LLM that records bound tools and choices."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "NativeDecisionLLM":
        return NativeDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "max_tokens": kwargs.get("max_tokens"),
                "text": text,
            }
        )

        if kwargs.get("force_tool_name") == "submit_decision" or tool_names == ["submit_decision"]:
            if "【任务：发言】" in text:
                args = {"speech": "我先按公开信息发言，重点观察2号的站边。", "reasoning": "native final speech"}
            else:
                args = {"target": "Bob", "reasoning": "native final target"}
            return AIMessage(
                content="",
                tool_calls=[{"id": "call_decision", "name": "submit_decision", "args": args}],
            )

        assert "recall_memory" in tool_names
        return AIMessage(
            content="",
            tool_calls=[{"id": "call_memory", "name": "recall_memory", "args": {"filter": "all"}}],
        )


class EmptyNativeThenTextDecisionLLM:
    """Native function-call attempt returns empty, then text repair succeeds."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "EmptyNativeThenTextDecisionLLM":
        return EmptyNativeThenTextDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision":
            return AIMessage(content="")
        return AIMessage(content='DECISION: {"target": "Bob", "reasoning": "text repair target"}')


class InvalidNativeArgsThenTextDecisionLLM:
    """Native submit_decision has missing args, then text repair succeeds."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "InvalidNativeArgsThenTextDecisionLLM":
        return InvalidNativeArgsThenTextDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision" or "submit_decision" in tool_names:
            return AIMessage(
                content="",
                tool_calls=[{"id": "call_bad", "name": "submit_decision", "args": {"speech": ""}}],
            )
        return AIMessage(
            content='DECISION: {"speech": "我用文本格式补交最终发言。", "reasoning": "text repair speech"}'
        )


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

    with pytest.raises(RuntimeError, match="failed to produce a structured decision"):
        loop.run(obs, Memory("P1", "Villager"))


def test_agent_loop_native_fc_uses_info_tool_then_forces_submit_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = NativeDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["speech"]
    assert decision["reasoning"] == "native final speech"
    assert len(llm.calls) == 2
    assert "recall_memory" in llm.calls[0]["tool_names"]
    assert "submit_decision" in llm.calls[0]["tool_names"]
    assert llm.calls[0]["force_tool_name"] is None
    assert llm.calls[1]["tool_names"] == ["submit_decision"]
    assert llm.calls[1]["force_tool_name"] == "submit_decision"
    assert decision["_tool_trace"][0]["tool"] == "recall_memory"


@pytest.mark.parametrize("action_type,phase", [("vote", "DAY_VOTE"), ("night", "NIGHT_WOLF_ACTION")])
def test_agent_loop_vote_and_night_default_directly_force_submit_decision(action_type: str, phase: str) -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Werewolf" if action_type == "night" else "Villager",
        day=1,
        phase=phase,
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = NativeDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type=action_type, player_id="P1")

    decision = loop.run(obs, Memory("P1", obs.player_role))

    assert decision["target"] == "Bob"
    assert decision["reasoning"] == "native final target"
    assert len(llm.calls) == 1
    assert llm.calls[0]["tool_names"] == ["submit_decision"]
    assert llm.calls[0]["force_tool_name"] == "submit_decision"


def test_agent_loop_decision_schema_restricts_target_to_legal_targets() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Werewolf",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="WolfB", seat=2, alive=True),
            PlayerInfo(id="P3", name="Bob", seat=3, alive=True),
        ],
        legal_targets=[PlayerInfo(id="P3", name="Bob", seat=3, alive=True)],
    )
    loop = AgentLoop(NativeDecisionLLM(), "system prompt", action_type="night", player_id="P1")

    schema = loop._decision_tool_schema(obs)

    target_schema = schema["function"]["parameters"]["properties"]["target"]
    assert target_schema["enum"] == ["3号", "3号:Bob", "Bob", "P3"]
    assert "2号" not in target_schema["description"]
    assert "3号:Bob" in target_schema["description"]


def test_agent_loop_repairs_empty_native_submit_decision_with_text_decision() -> None:
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
    llm = EmptyNativeThenTextDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="vote", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["target"] == "Bob"
    assert decision["reasoning"] == "text repair target"
    assert len(llm.calls) == 2
    assert llm.calls[0]["force_tool_name"] == "submit_decision"
    assert llm.calls[1]["force_tool_name"] is None
    assert llm.calls[1]["tool_names"] == []


def test_agent_loop_repairs_invalid_native_submit_args_with_text_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = InvalidNativeArgsThenTextDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["speech"] == "我用文本格式补交最终发言。"
    assert decision["reasoning"] == "text repair speech"
    assert len(llm.calls) == 3
    assert llm.calls[-1]["force_tool_name"] is None
    assert llm.calls[-1]["tool_names"] == []


def test_cognitive_agent_talk_preserves_native_fc_reasoning() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Villager",
        llm=NativeDecisionLLM(),
        player_name="Alice",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "TALK")

    decision = agent.talk()

    assert decision.action_type == ActionType.TALK
    assert decision.speech
    assert decision.reasoning == "native final speech"
    assert agent.memory.actions[-1].reasoning == "native final speech"


def test_cognitive_agent_empty_speech_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Villager",
        llm=EmptySpeechLLM(),
        player_name="Alice",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "TALK")

    with pytest.raises(RuntimeError, match="speech response is empty or too short"):
        agent.talk()


def test_cognitive_agent_required_night_skip_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_GUARD_ACTION",
        self_player={"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
        players=[
            {"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P1", "name": "Guard", "seat": 1, "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Guard",
        llm=SkipNightTargetLLM(),
        player_name="Guard",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "GUARD")

    with pytest.raises(RuntimeError, match="skip keyword"):
        agent.guard()


def test_cognitive_agent_required_night_illegal_target_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        self_player={"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
        players=[
            {"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
            {"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True},
            {"id": "P3", "name": "Villager", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[{"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True}],
        observations=[],
        legal_targets=[
            {"id": "P3", "name": "Villager", "seat": 3, "alive": True},
            {"id": "P4", "name": "Guard", "seat": 4, "alive": True},
        ],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Werewolf",
        llm=InvalidNightTargetLLM(),
        player_name="WolfA",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "ATTACK")

    with pytest.raises(RuntimeError, match="unresolved attack target"):
        agent.attack()


def test_cognitive_agent_night_decision_rejects_resolved_illegal_target() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        self_player={"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
        players=[
            {"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
            {"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True},
            {"id": "P3", "name": "Villager", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[{"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True}],
        observations=[],
        legal_targets=[{"id": "P3", "name": "Villager", "seat": 3, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Werewolf",
        llm=DeterministicCognitiveLLM(),
        player_name="WolfA",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "ATTACK")

    with pytest.raises(RuntimeError, match="illegal attack target"):
        agent._night_decision({"target": "狼人队友", "reasoning": "illegal teammate target"}, ActionType.ATTACK)


def test_cognitive_agent_witch_invalid_json_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WITCH_ACTION",
        self_player={"id": "P1", "name": "Witch", "seat": 1, "role": "Witch", "alive": True},
        players=[
            {"id": "P1", "name": "Witch", "seat": 1, "role": "Witch", "alive": True},
            {"id": "P2", "name": "Victim", "seat": 2, "alive": True},
            {"id": "P3", "name": "Target", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Victim", "seat": 2, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Witch",
        llm=BadWitchLLM(),
        player_name="Witch",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "WITCH")

    with pytest.raises(ValueError, match="did not contain JSON"):
        agent.witch_act("P2")


def test_cognitive_agent_direct_action_invalid_target_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="HUNTER_SHOOT",
        self_player={"id": "P1", "name": "Hunter", "seat": 1, "role": "Hunter", "alive": False},
        players=[
            {"id": "P1", "name": "Hunter", "seat": 1, "role": "Hunter", "alive": False},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Bob", "seat": 2, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Hunter",
        llm=InvalidDirectTargetLLM(),
        player_name="Hunter",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "SHOOT")

    with pytest.raises(RuntimeError, match="invalid shoot target"):
        agent.shoot()


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
