"""Role-specific prompt templates inspired by WereWolfPlus agent_manager/prompts/werewolf_prompt.py.

Each action template follows: RULES → STATE → OBSERVATIONS → STRATEGY → JSON OUTPUT
"""

from __future__ import annotations

from backend.engine.models import Role

# ---------------------------------------------------------------------------
# System prompts — fixed rules, cached across calls
# ---------------------------------------------------------------------------

GAME_RULES = """狼人杀游戏规则：
- 角色：{role_count} 名玩家，包括狼人、预言家、女巫、猎人、守卫、村民
- 黑夜：狼人刀人→女巫用药→预言家查验→守卫守护
- 白天：玩家轮流发言→投票放逐→公布结果
- 好人阵营获胜条件：所有狼人被投票出局
- 狼人阵营获胜条件：狼人数量 ≥ 存活好人数"""


ROLE_SYSTEM_PROMPTS: dict[Role, str] = {
    Role.WEREWOLF: (
        "你是狼人杀中的狼人。你的目标是误导好人、保护自己和狼队友，最终让狼人阵营获胜。\n"
        "核心策略：白天假装好人，带偏票型；夜晚和狼队友协调刀人。\n"
        "记住：你永远不能说自己是狼人，必须伪装成好人身份。"
    ),
    Role.SEER: (
        "你是狼人杀中的预言家。你的目标是用查验结果引导好人阵营投票，找出所有狼人。\n"
        "核心策略：合理使用查验能力，在关键轮次跳身份给出查验结果。\n"
        "记住：查验结果只告诉你被查验者是不是狼，不会告诉你具体身份。"
    ),
    Role.WITCH: (
        "你是狼人杀中的女巫。你有一瓶解药和一瓶毒药，各限使用一次。\n"
        "核心策略：解药优先保关键神职；毒药在把握较高时使用，争取制造轮次优势。\n"
        "记住：你不知道被刀的是谁（除非跳身份），用药需谨慎。"
    ),
    Role.HUNTER: (
        "你是狼人杀中的猎人。你死亡时可以开枪带走一名玩家。\n"
        "核心策略：用开枪威慑狼队，逼迫对手在白天做出明确表态。\n"
        "注意：被女巫毒死时不能开枪。"
    ),
    Role.GUARD: (
        "你是狼人杀中的守卫。每夜可以守护一名玩家，不能连续两夜守护同一人。\n"
        "核心策略：守护关键神职和高价值好人，用白天发言分析信息差。\n"
        "记住：不能暴露自己的守护偏好。"
    ),
    Role.VILLAGER: (
        "你是狼人杀中的村民。你没有任何特殊能力，只能靠推理和投票。\n"
        "核心策略：每次发言给出明确怀疑对象和站边逻辑，给神职创造站边空间。\n"
        "记住：村民的票和发言是好人阵营最重要的武器。"
    ),
}

# ---------------------------------------------------------------------------
# Action-specific strategy templates
# ---------------------------------------------------------------------------

ACTION_STRATEGIES: dict[str, dict[Role, str]] = {
    "talk": {
        Role.WEREWOLF: (
            "发言策略：给出一位具体怀疑对象，攻击其发言中的矛盾点。"
            "借他人发言做二次加工，假装自己只是顺着逻辑走。"
            "避免空泛中立发言，同时也避免过度攻击到狼队友。"
        ),
        Role.SEER: (
            "发言策略：如果你有查验结果且值得公开，明确报出查验对象和结果（好人/狼人）。"
            "如果还没跳身份，先以村民角度给出推理和怀疑对象。"
            "每次发言至少给出一个主怀疑对象和一个备选怀疑。"
        ),
        Role.WITCH: (
            "发言策略：关注死亡信息和票型变化。"
            "不要暴露自己的用药信息（解药/毒药使用情况）。"
            "可以质疑不承担责任的中立发言位。"
        ),
        Role.HUNTER: (
            "发言策略：发言可以强硬，逼迫对手留下清晰站边。"
            "每次发言至少给出一个明确的怀疑对象和理由。"
            "被推上高票位时要留完整嫌疑链（谁先带节奏、谁在跟票）。"
        ),
        Role.GUARD: (
            "发言策略：重点分析谁在利用信息差带节奏。"
            "避免发言透露自己的守护偏好。"
            "以村民视角给出自己的站边逻辑和怀疑对象。"
        ),
        Role.VILLAGER: (
            "发言策略：每轮至少给出一个主怀疑和一个备选怀疑对象。"
            "不要只复述别人的结论，要给出自己的站边逻辑。"
            "为神职创造足够空间，同时对自己的怀疑负责。"
        ),
    },
    "vote": {
        Role.WEREWOLF: (
            "投票策略：跟进已经成型的好人票坑以减少狼队痕迹。"
            "如果狼队友被点，制造第二焦点而不是生硬保人。"
            "优先投不威胁狼队且容易被别人跟票的目标。"
        ),
        Role.SEER: (
            "投票策略：如果有查杀，优先投票查杀目标。"
            "如果没有查杀，推动桌面最不自然的带节奏位出局。"
        ),
        Role.WITCH: (
            "投票策略：优先投票型里最像狼队节奏位的人。"
            "如果真预言家给出可信查杀，优先配合查杀目标。"
        ),
        Role.HUNTER: (
            "投票策略：优先投强推错误逻辑又想混在票型里的人。"
            "投票要让自己的立场清晰可回溯。"
        ),
        Role.GUARD: (
            "投票策略：优先投逻辑反复横跳的带节奏位。"
            "避免跟风投票，每票都要有清晰理由。"
        ),
        Role.VILLAGER: (
            "投票策略：优先投不愿承担归票责任、只会模糊跟票的人。"
            "投出每一票都要能说出自己的完整逻辑链。"
        ),
    },
    "attack": {  # wolf night kill
        Role.WEREWOLF: (
            "刀人策略：优先刀掉能形成稳定视角的神职（如预言家、女巫）。"
            "如果白天多人对立，留着混乱桌面比刀掉单个人价值更高。"
            "避免刀掉已经在白天被广泛怀疑的好人（让好人替你们推）。"
        ),
    },
    "divine": {  # seer check
        Role.SEER: (
            "查验策略：优先查验高影响力位、警长位、主动带节奏位。"
            "避免重复查验已经足够清楚的目标。"
            "第一轮可以随意挑一位查验以获得初始信息。"
        ),
    },
    "guard": {
        Role.GUARD: (
            "守护策略：优先守护高价值神职与可信带队位。"
            "不能连续守同一人时，次优先守公开金水或最像真预言家的人。"
            "如果你怀疑某位好人今晚会被狼队刀，优先守他。"
        ),
    },
    "witch_act": {
        Role.WITCH: (
            "女巫行动策略：\n"
            "解药：第一轮一般救人（除非特殊策略）；后续轮次优先保关键神职。\n"
            "毒药：只在把握较高时使用（如明确确认某人是狼），争取制造轮次优势。\n"
            "如果不确定，宁可留着药也不用。"
        ),
    },
    "shoot": {
        Role.HUNTER: (
            "开枪策略：优先打对自己威胁最大、最像狼的节奏位。"
            "如果你被投票推出，打那个带节奏推你的人。"
            "如果你被狼刀死，根据白天的发言和票型选择目标。"
        ),
    },
}

# ---------------------------------------------------------------------------
# JSON output format templates
# ---------------------------------------------------------------------------

TALK_OUTPUT_FORMAT = '{"reasoning": "你的思考过程（1-2句）", "speech": "你的公开发言"}'
TARGET_OUTPUT_FORMAT = '{"reasoning": "你的思考过程（1-2句）", "target": "玩家名字"}'
WITCH_OUTPUT_FORMAT = '{"reasoning": "你的思考过程", "save": true/false, "poison_target": "玩家名字或null"}'


def get_system_prompt(role: Role) -> str:
    return ROLE_SYSTEM_PROMPTS.get(role, ROLE_SYSTEM_PROMPTS[Role.VILLAGER])


def get_action_strategy(action: str, role: Role) -> str:
    strategies = ACTION_STRATEGIES.get(action, {})
    return strategies.get(role, strategies.get(Role.VILLAGER, ""))


def get_output_format(action: str) -> str:
    if action in ("talk",):
        return TALK_OUTPUT_FORMAT
    if action in ("witch_act",):
        return WITCH_OUTPUT_FORMAT
    return TARGET_OUTPUT_FORMAT
