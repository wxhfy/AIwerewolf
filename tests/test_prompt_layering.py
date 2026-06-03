from __future__ import annotations

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, PlayerInfo
from backend.agents.cognitive.profiles import PROFILES
from backend.agents.cognitive.prompts import build_system_prompt, build_think_prompt
from backend.agents.cognitive.tools import create_tools
from backend.agents.cognitive.wolf_team import (
    WolfTeamView,
    assign_wolf_tactics,
    negotiate_wolf_kill,
)
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
    )
    for phrase in old_role_tactics:
        assert phrase not in prompt


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
