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
from backend.agents.cognitive.retrieval import format_strategies_for_prompt


def create_tools(
    obs: Observation,
    memory: Memory,
) -> Dict[str, Any]:
    """Create tool implementations bound to current Observation and Memory.

    Returns a dict of {tool_name: tool_config} where tool_config contains
    the callable and its description for the system prompt.
    """

    # ---- search_strategies ----
    def search_strategies(keywords: List[str], limit: int = 3) -> str:
        """Search the strategy knowledge base with agent-chosen keywords.

        Use this when you need tactical guidance for a specific situation.
        Choose precise, domain-specific keywords (e.g., "被查杀应对", "警徽流").
        """
        try:
            from backend.agents.cognitive.retrieval_prod import retrieve_strategies_prod
            results = retrieve_strategies_prod(
                obs.player_role, obs.phase, keywords=keywords, limit=limit,
            )
        except Exception:
            results = []
        if not results:
            results = retrieve_tfidf(
                obs.player_role, obs.phase, situation=" ".join(keywords), limit=limit,
            )
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
        "狼人可以空刀吗": "可以，但通常不推荐。空刀意味着放弃击杀机会。",
    }

    def check_rules(question: str) -> str:
        """Query game rules. Use this when unsure about mechanics."""
        for q, a in _RULES_FAQ.items():
            if q in question or any(w in question for w in q[:4]):
                return a
        return f"关于「{question}」没有确切的规则记录。请基于标准狼人杀规则推理。"

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

    # ---- Tool registry ----
    return {
        "search_strategies": {
            "fn": search_strategies,
            "description": (
                'search_strategies(keywords: list[str], limit: int = 3)\n'
                '  用关键词搜索狼人杀策略库。选精准的领域术语（如「被查杀」「警徽流」「表水」）。\n'
                '  例: search_strategies(keywords=["被查杀应对", "反跳预言家"], limit=3)'
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
        "analyze_votes": {
            "fn": analyze_votes,
            "description": (
                "analyze_votes()\n"
                "  分析当前投票模式。自动统计票型分布。"
            ),
        },
    }
