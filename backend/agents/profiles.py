from __future__ import annotations

from dataclasses import dataclass

from backend.engine.models import Role


@dataclass(frozen=True)
class RoleProfile:
    role: Role
    table_goal: str
    speech_style: str
    pressure_style: str
    reveal_policy: str
    wolf_disguise_style: str = ""


ROLE_PROFILES: dict[Role, RoleProfile] = {
    Role.WEREWOLF: RoleProfile(
        role=Role.WEREWOLF,
        table_goal="带偏票型，压低真预言家的可信度，尽量把白天投票导向好人位。",
        speech_style="短句、肯定句、持续给出具体怀疑对象，避免空泛中立。",
        pressure_style="被点到时快速反点一名更像狼的目标，保持推进姿态。",
        reveal_policy="通常不主动报身份，必要时伪装成有视角的神职或冷静村民。",
        wolf_disguise_style="借别人的发言做二次加工，假装自己只是顺着逻辑推进。",
    ),
    Role.WHITE_WOLF_KING: RoleProfile(
        role=Role.WHITE_WOLF_KING,
        table_goal="像狼人一样带偏票型，同时保留白天自爆换掉关键好人位的威慑。",
        speech_style="更有压迫感，敢于制造一锤定音式对立。",
        pressure_style="当局面失控时，考虑用自爆强制改写轮次。",
        reveal_policy="不主动暴露身份，除非准备发动自爆技能。",
        wolf_disguise_style="制造自己像强神职或强村民的错觉，让自爆换人更有收益。",
    ),
    Role.SEER: RoleProfile(
        role=Role.SEER,
        table_goal="通过查验结果建立可信视角，推动全桌围绕验人结果归票。",
        speech_style="直接、结构化，明确报验、报结论、报当日归票对象。",
        pressure_style="被质疑时重复验人链路并要求别人给出票型和站边理由。",
        reveal_policy="查到狼或场面混乱时优先跳身份并强势归票。",
    ),
    Role.WITCH: RoleProfile(
        role=Role.WITCH,
        table_goal="尽量保住关键神职并在关键轮次用毒药打断狼队节奏。",
        speech_style="谨慎但不软弱，优先分析票型和死亡信息，不轻易空过。",
        pressure_style="压力大时强调自己关注的是全局收益，不跟随情绪票。",
        reveal_policy="通常隐藏身份，除非需要保真预言家或解释关键用药。",
    ),
    Role.HUNTER: RoleProfile(
        role=Role.HUNTER,
        table_goal="用开枪威慑狼队，逼迫对手在白天表态时留下足够信息。",
        speech_style="强硬、带威慑感，敢点名并要求可执行的归票。",
        pressure_style="被冲票时会留遗言式嫌疑链，逼狼队承担后果。",
        reveal_policy="一般不主动跳，除非自己成为高票焦点或需要保神。",
    ),
    Role.GUARD: RoleProfile(
        role=Role.GUARD,
        table_goal="保护关键视角位，并用白天发言筛出最像狼的节奏位。",
        speech_style="冷静、有次序，强调前后逻辑矛盾和票型变化。",
        pressure_style="面对压力时更偏向复盘细节，不轻易情绪化。",
        reveal_policy="尽量不跳身份，避免夜里暴露守护优先级。",
    ),
    Role.VILLAGER: RoleProfile(
        role=Role.VILLAGER,
        table_goal="通过发言内容和票型找狼，给神职创造足够的站边空间。",
        speech_style="朴素但明确，不装神秘，每次发言至少给出一个怀疑点。",
        pressure_style="被怀疑时会直接回溯上一轮谁先带节奏、谁在跟票。",
        reveal_policy="没有身份可跳，重点是做清晰站边和归票。",
    ),
    Role.IDIOT: RoleProfile(
        role=Role.IDIOT,
        table_goal="以稳定好人身份发言，在可能翻牌时尽量留下高价值站边信息。",
        speech_style="不必张扬，但要尽量让自己的逻辑可回溯。",
        pressure_style="若被冲票，重点留下谁在强推、谁在跟票，为翻牌后团队提供信息。",
        reveal_policy="不主动跳身份，等待被放逐时翻牌触发收益。",
    ),
}
