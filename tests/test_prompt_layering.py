from __future__ import annotations

from backend.agents.cognitive import agent_loop as agent_loop_module
from backend.agents.cognitive.agent_loop import AgentLoop
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import PlayerInfo
from backend.agents.cognitive.profiles import PROFILES
from backend.agents.cognitive.prompts import build_system_prompt
from backend.agents.cognitive.prompts import build_think_prompt
from backend.agents.cognitive.tools import create_tools
from backend.agents.cognitive.wolf_team import WolfTeamView
from backend.agents.cognitive.wolf_team import assign_wolf_tactics
from backend.agents.cognitive.wolf_team import negotiate_wolf_kill
from backend.agents.prompts import ROLE_SYSTEM_PROMPTS

NON_STRATEGY_FORBIDDEN = (
    "核心策略",
    "【发言策略】",
    "【桌面策略】",
    "【身份策略】",
    "必须跳",
    "必须上警",
    "优先刀",
    "优先守",
    "优先救",
    "强势归票",
    "带偏",
    "警徽流",
    "拿狼时的打法",
    "扮狼欺骗",
    "伪装方式",
    "【本角色常见失误",
    "查到狼人必须",
    "跟随预言家",
    "首夜优先守护",
    "刀人优先级",
)


def test_cognitive_system_prompts_do_not_inject_hard_strategy() -> None:
    for role, profile in PROFILES.items():
        prompt = build_system_prompt(role, profile)
        for phrase in NON_STRATEGY_FORBIDDEN:
            assert phrase not in prompt, f"{role} system prompt leaks strategy phrase: {phrase}"


def test_legacy_role_system_prompts_stay_role_descriptive() -> None:
    for role, prompt in ROLE_SYSTEM_PROMPTS.items():
        for phrase in NON_STRATEGY_FORBIDDEN:
            assert phrase not in prompt, f"{role.value} role system prompt leaks strategy phrase: {phrase}"


def test_think_prompt_uses_role_boundaries_not_role_tactics() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    prompt = build_think_prompt(obs, Memory("P1", "Seer"))

    assert "结合你的角色能力和私有信息边界" in prompt
    old_role_tactics = (
        "如果你还没跳身份",
        "当前的优先目标",
        "不要划水",
        "今晚应该守谁",
        "查到狼人必须",
        "跟随预言家",
        "【本角色常见失误",
    )
    for phrase in old_role_tactics:
        assert phrase not in prompt


def test_agent_loop_task_layer_has_no_role_hard_strategy(monkeypatch) -> None:
    monkeypatch.setattr(agent_loop_module, "_retrieve_track_c_strategy_lessons", lambda obs, action: [])
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Werewolf",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
        legal_targets=[PlayerInfo(id="P2", name="Bob", seat=2, alive=True)],
    )
    loop = AgentLoop(
        llm=object(),
        system_prompt="【身份与性格】只介绍角色边界。",
        action_type="night",
    )

    prompt = loop._build_system_text(obs, Memory("P1", "Werewolf"), create_tools(obs, Memory("P1", "Werewolf")), "", "")

    assert "【任务：夜晚行动】" in prompt
    assert "【策略层：Track C 复盘知识】" not in prompt
    assert "刀人优先级" not in prompt
    assert "狼队要统一冲票" not in prompt


def test_agent_loop_places_forced_strategy_only_in_strategy_layer(monkeypatch) -> None:
    monkeypatch.setattr(agent_loop_module, "_retrieve_track_c_strategy_lessons", lambda obs, action: [])
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
        legal_targets=[PlayerInfo(id="P2", name="Bob", seat=2, alive=True)],
    )
    loop = AgentLoop(
        llm=object(),
        system_prompt="【身份与性格】只介绍角色边界。",
        action_type="vote",
        strategy_bias={"vote_policy": ["Use verified public information before voting."]},
    )

    prompt = loop._build_system_text(obs, Memory("P1", "Seer"), create_tools(obs, Memory("P1", "Seer")), "", "")

    assert "【本局强制策略规则" in prompt
    assert "[vote_policy] Use verified public information before voting." in prompt
    assert "【身份与性格】只介绍角色边界。" in prompt


def test_track_c_lessons_enter_strategy_layer_only(monkeypatch) -> None:
    def fake_retrieve(obs, action):
        assert obs.player_role == "Seer"
        assert action == "vote"
        return [
            {
                "doc_id": "doc-track-c-seer",
                "score": 0.88,
                "trigger": "Seer has public pressure after a confirmed check.",
                "recommendation": "Convert confirmed public information into vote pressure.",
                "rationale": "Approved Track B review showed hidden checks created misvotes.",
            }
        ]

    monkeypatch.setattr(agent_loop_module, "_retrieve_track_c_strategy_lessons", fake_retrieve)
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
        legal_targets=[PlayerInfo(id="P2", name="Bob", seat=2, alive=True)],
    )
    loop = AgentLoop(
        llm=object(),
        system_prompt="【身份与性格】只介绍角色边界。",
        action_type="vote",
    )

    prompt = loop._build_system_text(obs, Memory("P1", "Seer"), create_tools(obs, Memory("P1", "Seer")), "", "")

    task_index = prompt.index("【任务：投票】")
    strategy_index = prompt.index("【策略层：Track C 复盘知识】")
    assert strategy_index > task_index
    assert "doc-track-c-seer" in prompt
    assert "Convert confirmed public information" in prompt


def test_rules_tool_answers_mechanics_without_recommendation() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Werewolf",
        day=0,
        phase="NIGHT_WOLF_ACTION",
    )
    answer = create_tools(obs, Memory("P1", "Werewolf"))["check_rules"]["fn"]("狼人可以空刀吗")

    assert "可以" in answer
    assert "推荐" not in answer


def test_wolf_team_module_does_not_assign_hard_tactics_or_kill_target() -> None:
    assignments = assign_wolf_tactics(["W1", "W2"], {"alive_player_ids": ["W1", "W2", "P3"]})
    target = negotiate_wolf_kill(
        WolfTeamView(alive_wolves=["W1", "W2"]),
        {"alive_player_ids": ["W1", "W2", "P3"]},
        belief_tracker=None,
    )

    assert assignments == {}
    assert target == ""
