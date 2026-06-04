"""Agent tools — callable by the cognitive agent during its thinking loop.

Each tool is a standalone function that takes structured input and returns
formatted text. Tools are created as closures that capture the current
Observation and Memory at invocation time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.retrieval import retrieve_strategies as retrieve_tfidf
from backend.agents.cognitive.retrieval_prod import format_strategies_for_prompt


def create_tools(
    obs: Observation,
    memory: Memory,
) -> Dict[str, Any]:
    """Create tool implementations bound to current Observation and Memory.

    Returns a dict of {tool_name: tool_config} where tool_config contains
    the callable and its description for the system prompt.
    """

    # ---- search_strategies ----
    def search_strategies(
        keywords: List[str],
        limit: int = 3,
        include_reflections: bool = False,
        mode: str = "content",
        use_regex: bool = False,
    ) -> str:
        """Search the strategy knowledge base with agent-chosen keywords or regex.

        Three output modes (inspired by Claude Code's grep):
          - "count": just return match count (use FIRST to test keyword quality)
          - "overview": situation + quality only (use to scan broadly)
          - "content": full strategy text (default, use when you've identified
                        relevant keywords)

        Workflow: start with mode="count" → refine keywords → mode="overview"
        → pick promising strategies → mode="content" with focused keywords.

        Keywords: choose precise domain terms (e.g., "被查杀应对", "警徽流").
        With use_regex=True, keywords are Python regex patterns.
        Set include_reflections=False to exclude post-game reflections.
        """
        try:
            from backend.agents.cognitive.retrieval_prod import retrieve_strategies_prod
            results = retrieve_strategies_prod(
                obs.player_role, obs.phase, keywords=keywords, limit=limit,
                output_mode=mode, regex_mode=use_regex,
            )
        except Exception:
            results = []
        if not results:
            # Fallback to TF-IDF (PostgreSQL-independent)
            results = retrieve_tfidf(
                obs.player_role, obs.phase, situation=" ".join(keywords), limit=limit,
            )
        if not results:
            return "(未找到相关策略)"
        if not include_reflections and mode != "count":
            results = [r for r in results
                       if not r.get("doc_type", "").startswith("reflection")]
            if not results:
                return "(未找到相关策略)"
        return format_strategies_for_prompt(results)

    # ---- recall_memory ----
    def recall_memory(filter: str = "all", target_player: str = "") -> str:
        """Query the agent's memory for judgments, history, and role state.

        filter options:
          - "judgments": all players you've evaluated
          - "suspicious": players you marked as suspicious/wolf
          - "trusted": players you marked as trusted/good
          - "recent_actions": your last few actions
          - "role_state": your role-specific state (seer checks, etc.)
          - "all": everything
        """
        lines = []

        if filter in ("judgments", "suspicious", "trusted", "all"):
            if filter == "suspicious":
                judgments = memory.get_suspects()
            elif filter == "trusted":
                judgments = memory.get_trusted()
            else:
                judgments = memory.judgments

            if judgments:
                label = "嫌疑人" if filter == "suspicious" else ("信任" if filter == "trusted" else "玩家判断")
                lines.append(f"=== {label} ===")
                for j in judgments:
                    if target_player and j.target != target_player:
                        continue
                    lines.append(f"  {j.target}: {j.label}({j.confidence:.0%}) "
                                 f"[Day{j.day}] - {j.reasoning[:80]}")

        if filter in ("recent_actions", "all"):
            actions = memory.get_recent_actions(5)
            if actions:
                lines.append("=== 最近行动 ===")
                for a in actions:
                    lines.append(f"  D{a.day} [{a.phase}] {a.action_type}: "
                                 f"{a.content[:80]}")

        if filter in ("role_state", "all"):
            rs = memory.role_state
            if rs:
                lines.append("=== 角色状态 ===")
                for k, v in rs.items():
                    lines.append(f"  {k}: {v}")

        if not lines:
            return "(没有相关记忆)"
        return "\n".join(lines)

    # ---- check_rules ----
    _RULES_FAQ = {
        "守卫可以连续守同一个人吗": "不能。守卫不能连续两晚守护同一人。",
        "守卫守护了狼人刀的人会怎样": "被守护的人不会死。如果是同守同救（女巫也救了），那人会死（奶穿规则，默认不启用）。",
        "女巫可以同一晚用解药和毒药吗": "不能。女巫每晚只能使用一瓶药（解药或毒药）。",
        "解药用过了还能用吗": "不能。解药只能使用一次。",
        "毒药用过了还能用吗": "不能。毒药只能使用一次。",
        "猎人被毒了能开枪吗": "不能。猎人只有被投票放逐或狼人刀死时才能开枪，被毒死不能开枪。",
        "白痴被投票放逐会怎样": "白痴被放逐后翻开身份牌，不会出局，但失去投票权。",
        "白狼王自爆有什么效果": "白狼王可以在白天任意时刻自爆，带走一名玩家后立即进入黑夜。",
        "警长有什么特权": "警长拥有1.5票投票权，死时可以转移警徽给任意存活玩家。",
        "狼人可以空刀吗": "可以。若选择空刀，当夜不会产生狼人击杀目标。",
    }

    def check_rules(question: str) -> str:
        """Query game rules. Use this when unsure about mechanics."""
        normalized = question.strip()
        for q, a in _RULES_FAQ.items():
            if q in normalized or normalized in q or q[:4] in normalized:
                return a
        return f"关于「{question}」没有确切的规则记录。请基于标准狼人杀规则推理。"

    # ---- get_social_info ----
    def get_social_info() -> str:
        """Query the trust network and deception signals for this agent.

        Returns trusted/distrusted players and recent deception signals.
        """
        result = memory.social_model.format_for_prompt(memory.player_id)
        if not result:
            return "(暂无信任网络信息)"
        return result

    # ---- analyze_votes ----
    def analyze_votes() -> str:
        """Analyze current voting patterns from observation data."""
        votes = obs.votes
        if not votes:
            return "本回合暂无投票数据。"

        tally: Dict[str, List[str]] = {}
        for v in votes:
            target = v.target_name or v.target_id
            voter = v.voter_name or v.voter_id
            tally.setdefault(target, []).append(voter)

        lines = ["=== 今日投票分析 ==="]
        for target, voters in sorted(tally.items(), key=lambda x: -len(x[1])):
            lines.append(f"  {target} ← {', '.join(voters)} ({len(voters)}票)")
        lines.append(f"  总投票人数: {len(votes)}")
        return "\n".join(lines)

    # ---- set_strategic_intent ----
    def set_strategic_intent(
        objective: str,
        target_phase: str,
        conditions: str = "",
        fallback: str = "",
    ) -> str:
        """Declare a multi-turn strategic intention.

        Use this when you want to commit to a plan that spans multiple turns,
        e.g., "I'll fake claim Seer tomorrow" or "I'll frame player X over
        two days of speeches." The system will remind you of your intent in
        future turns.

        Args:
            objective: What you want to achieve (short phrase).
            target_phase: When to execute (e.g., "DAY_SPEECH", "DAY_VOTE",
                         "NIGHT_WOLF_ACTION").
            conditions: What must hold true for the plan to proceed.
            fallback: What to do if conditions fail.
        """
        cond_list = [c.strip() for c in conditions.split(";")] if conditions else []
        intent = memory.planner.set_intent(
            objective=objective,
            target_phase=target_phase,
            day=obs.day,
            phase=obs.phase,
            conditions=cond_list if cond_list else None,
            fallback=fallback,
        )
        lines = [f"策略意图已记录: {intent.objective}"]
        lines.append(f"  触发阶段: {intent.target_phase}")
        if intent.conditions:
            lines.append(f"  前置条件: {', '.join(intent.conditions)}")
        if intent.fallback:
            lines.append(f"  失败回退: {intent.fallback}")
        lines.append("  系统会在对应阶段提醒你执行。可以在新信息出现后更新或放弃。")
        return "\n".join(lines)

    # ---- Tool registry ----
    return {
        "search_strategies": {
            "fn": search_strategies,
            "description": (
                'search_strategies(keywords: list[str], limit: int = 3, include_reflections: bool = False, mode: str = "content", use_regex: bool = False)\n'
                '  用关键词或正则搜索狼人杀策略库。三层模式：\n'
                '  mode="count" — 仅返回匹配数量（先测试关键词好坏）\n'
                '  mode="overview" — 仅返回场景标题和评分（快速扫描）\n'
                '  mode="content" — 返回完整策略（默认，确认关键词后使用）\n'
                '  推荐流程: count → overview → content，逐步缩小范围。\n'
                '  use_regex=True 时关键词被视为 Python 正则。\n'
                '  例: search_strategies(keywords=["被查杀"], mode="count")\n'
                '  例: search_strategies(keywords=["查杀.*狼", "悍跳"], use_regex=True)'
            ),
        },
        "recall_memory": {
            "fn": recall_memory,
            "description": (
                'recall_memory(filter: str, target_player: str = "")\n'
                '  查询记忆。filter可选: "judgments", "suspicious", "trusted", '
                '"recent_actions", "role_state", "all"。\n'
                '  target_player可选: 指定玩家名只查对该玩家的判断。\n'
                '  例: recall_memory(filter="suspicious")'
            ),
        },
        "check_rules": {
            "fn": check_rules,
            "description": (
                'check_rules(question: str)\n'
                '  查询游戏规则。当你对某个机制不确定时使用。\n'
                '  例: check_rules(question="守卫可以连续守护同一人吗")'
            ),
        },
        "get_social_info": {
            "fn": get_social_info,
            "description": (
                "get_social_info()\n"
                "  查询信任网络信息，包括你信任/怀疑的玩家和最近的欺骗信号。\n"
                "  例: get_social_info()"
            ),
        },
        "set_strategic_intent": {
            "fn": set_strategic_intent,
            "description": (
                'set_strategic_intent(objective: str, target_phase: str, conditions: str = "", fallback: str = "")\n'
                '  设定跨回合策略意图。告诉系统你的多步计划，后续回合会自动提醒你。\n'
                '  objective: 计划目标（如 "bluff_seer_day2"）\n'
                '  target_phase: 执行阶段（"DAY_SPEECH", "DAY_VOTE", "NIGHT_WOLF_ACTION"）\n'
                '  conditions: 分号分隔的前置条件\n'
                '  fallback: 条件不满足时的备选方案\n'
                '  例: set_strategic_intent(objective="fake_claim_seer", target_phase="DAY_SPEECH", '
                'conditions="no_other_seer_claim", fallback="continue_deep_cover")'
            ),
        },
        "analyze_votes": {
            "fn": analyze_votes,
            "description": (
                "analyze_votes()\n"
                "  分析当前投票模式。自动统计票型分布。"
            ),
        },
    }
