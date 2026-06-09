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
    monkeypatch.setattr(agent_loop_module, "_retrieve_track_c_strategy_lessons", lambda obs, action, **kwargs: [])
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
    monkeypatch.setattr(agent_loop_module, "_retrieve_track_c_strategy_lessons", lambda obs, action, **kwargs: [])
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
    assert "本角色基本任务" in prompt
    assert "【身份与性格】只介绍角色边界。" in prompt


def test_track_c_lessons_enter_strategy_layer_only(monkeypatch) -> None:
    def fake_retrieve(obs, action, **kwargs):
        assert obs.player_role == "Seer"
        assert action == "vote"
        assert kwargs["mbti"] == "INTJ"
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
        mbti="INTJ",
    )

    prompt = loop._build_system_text(obs, Memory("P1", "Seer"), create_tools(obs, Memory("P1", "Seer")), "", "")

    task_index = prompt.index("【任务：投票】")
    strategy_index = prompt.index("【策略层：Track C 复盘知识】")
    assert strategy_index > task_index
    assert "doc-track-c-seer" in prompt
    assert "Convert confirmed public information" in prompt
    assert "本角色基本职责不退化" in prompt


def test_track_c_auto_retrieval_uses_precision_policy(monkeypatch) -> None:
    captured = {}

    def fake_prod_retrieve(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return [
            {
                "doc_id": "doc-prod-seer",
                "quality": 0.91,
                "situation": "Seer DAY_VOTE",
                "strategy": "Use public check information to vote.",
                "doc_type": "accepted_patch",
                "status": "active",
                "phase_scope": "DAY_VOTE",
            }
        ]

    monkeypatch.setattr(agent_loop_module, "time", agent_loop_module.time)
    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_prod_retrieve)
    agent_loop_module._TRACK_C_RETRIEVAL_CACHE.clear()
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="INTJ")

    assert lessons[0]["doc_id"] == "doc-prod-seer"
    assert captured["kwargs"]["retrieval_policy"].value == "same_role_all_mbti"
    assert captured["kwargs"]["mbti"] == "INTJ"
    assert captured["kwargs"]["alignment"] == "village"
    assert "预言家" in captured["kwargs"]["keywords"]
    assert "投票" in captured["kwargs"]["keywords"]


def test_track_c_auto_retrieval_filters_unverified_and_persona_mismatch(monkeypatch) -> None:
    def fake_prod_retrieve(*args, **kwargs):
        return [
            {
                "doc_id": "candidate-doc",
                "quality": 0.99,
                "situation": "Seer vote",
                "strategy": "Candidate knowledge should not enter runtime prompt.",
                "doc_type": "accepted_patch",
                "status": "candidate",
            },
            {
                "doc_id": "wrong-mbti-doc",
                "quality": 0.95,
                "situation": "Seer vote",
                "strategy": "ESFJ-specific advice should not be injected for INTJ.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:ESFJ+role:Seer",
            },
            {
                "doc_id": "safe-doc",
                "quality": 0.92,
                "situation": "Seer DAY_VOTE",
                "strategy": "Turn public claims and votes into a concise voting reason.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
                "phase_scope": "DAY_VOTE",
            },
        ]

    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_prod_retrieve)
    agent_loop_module._TRACK_C_RETRIEVAL_CACHE.clear()
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="INTJ")

    assert [lesson["doc_id"] for lesson in lessons] == ["safe-doc"]


def test_track_c_auto_retrieval_blocks_reflection_and_unobservable_cues(monkeypatch) -> None:
    def fake_prod_retrieve(*args, **kwargs):
        return [
            {
                "doc_id": "reflection-doc",
                "quality": 0.96,
                "situation": "Seer vote",
                "strategy": "Use this reflection as direct advice.",
                "doc_type": "reflection",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
            },
            {
                "doc_id": "unobservable-doc",
                "quality": 0.94,
                "situation": "Seer vote",
                "strategy": "Read eye contact and body language before voting.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
            },
            {
                "doc_id": "safe-doc",
                "quality": 0.91,
                "situation": "Seer DAY_VOTE",
                "strategy": "Base the vote on public speech contradictions and vote records.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
                "phase_scope": "DAY_VOTE",
            },
        ]

    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_prod_retrieve)
    agent_loop_module._TRACK_C_RETRIEVAL_CACHE.clear()
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="INTJ")

    assert [lesson["doc_id"] for lesson in lessons] == ["safe-doc"]


def test_track_c_auto_retrieval_cache_is_mbti_aware(monkeypatch) -> None:
    calls = []

    def fake_prod_retrieve(*args, **kwargs):
        calls.append(kwargs["mbti"])
        return [
            {
                "doc_id": f"safe-{kwargs['mbti']}",
                "quality": 0.91,
                "situation": "Seer vote",
                "strategy": "Use public voting evidence.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": f"mbti:{kwargs['mbti']}+role:Seer",
                "phase_scope": "DAY_VOTE",
            }
        ]

    monkeypatch.setenv("TRACK_C_AUTO_RETRIEVAL_CACHE_SECONDS", "120")
    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_prod_retrieve)
    agent_loop_module._TRACK_C_RETRIEVAL_CACHE.clear()
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    intj_lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="INTJ")
    esfj_lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="ESFJ")

    assert [lesson["doc_id"] for lesson in intj_lessons] == ["safe-INTJ"]
    assert [lesson["doc_id"] for lesson in esfj_lessons] == ["safe-ESFJ"]
    assert calls == ["INTJ", "ESFJ"]


def test_track_c_auto_retrieval_defaults_to_top1_and_filters_phase_or_history_ids(monkeypatch) -> None:
    def fake_prod_retrieve(*args, **kwargs):
        return [
            {
                "doc_id": "wrong-phase",
                "quality": 0.97,
                "situation": "Seer NIGHT_SEER_ACTION",
                "strategy": "Choose a night inspection target.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
                "phase_scope": "NIGHT_SEER_ACTION",
            },
            {
                "doc_id": "history-seat",
                "quality": 0.96,
                "situation": "Seer DAY_VOTE",
                "strategy": "Vote 3号 because the historical review did so.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
                "phase_scope": "DAY_VOTE",
            },
            {
                "doc_id": "safe-high",
                "quality": 0.93,
                "situation": "Seer DAY_VOTE",
                "strategy": "Vote from public contradictions and claim consistency.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
                "phase_scope": "DAY_VOTE",
            },
            {
                "doc_id": "safe-second",
                "quality": 0.92,
                "situation": "Seer DAY_VOTE",
                "strategy": "Keep the vote reason concise.",
                "doc_type": "accepted_patch",
                "status": "active",
                "persona_scope": "mbti:INTJ+role:Seer",
                "phase_scope": "DAY_VOTE",
            },
        ]

    monkeypatch.delenv("TRACK_C_AUTO_RETRIEVAL_LIMIT", raising=False)
    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_prod_retrieve)
    agent_loop_module._TRACK_C_RETRIEVAL_CACHE.clear()
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="INTJ")

    assert [lesson["doc_id"] for lesson in lessons] == ["safe-high"]


def test_track_c_strategy_block_marks_lessons_as_optional(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_loop_module,
        "_retrieve_track_c_strategy_lessons",
        lambda *_args, **_kwargs: [
            {
                "doc_id": "safe-high",
                "trigger": "DAY_VOTE",
                "recommendation": "Use public contradictions.",
                "score": 0.93,
            }
        ],
    )
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    block = agent_loop_module._build_track_c_strategy_block(obs, "vote", mbti="INTJ")

    assert "仅作为高置信可选参考" in block
    assert "必须忽略" in block
    assert "可参考做法：Use public contradictions." in block


def test_track_c_auto_retrieval_clears_stale_usage_trace_when_filtered(monkeypatch) -> None:
    def fake_prod_retrieve(*args, **kwargs):
        return [
            {
                "doc_id": "candidate-doc",
                "quality": 0.99,
                "situation": "Seer vote",
                "strategy": "Candidate knowledge should not be injected.",
                "doc_type": "accepted_patch",
                "status": "candidate",
            }
        ]

    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_prod_retrieve)
    agent_loop_module._TRACK_C_RETRIEVAL_CACHE.clear()
    agent_loop_module._LAST_RETRIEVED_STRATEGIES["P1"] = [{"doc_id": "old-doc"}]
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_VOTE",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )

    lessons = agent_loop_module._retrieve_track_c_strategy_lessons(obs, "vote", mbti="INTJ")

    assert lessons == []
    assert "P1" not in agent_loop_module._LAST_RETRIEVED_STRATEGIES


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
