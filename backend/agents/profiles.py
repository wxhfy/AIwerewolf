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
    # ---- Template roles (playable=False in registry) ----
    # These profiles exist so prompt assembly never KeyErrors when the registry
    # eventually flips one of these to playable. They're also useful if a
    # future scenario lets a player preview the LLM persona before enabling
    # the role in a config.
    Role.CUPID: RoleProfile(
        role=Role.CUPID,
        table_goal="第 0 夜挑选两名情侣建立隐藏阵营纽带，白天伪装成普通村民。",
        speech_style="低调但要有自己的站边逻辑，避免被怀疑是丘比特。",
        pressure_style="被压力时强调自己的票型和怀疑链，不暴露情侣关系。",
        reveal_policy="一般不主动跳，除非情侣已死、需要为殉情提供解释。",
    ),
    Role.BIG_BAD_WOLF: RoleProfile(
        role=Role.BIG_BAD_WOLF,
        table_goal="伪装成普通狼或好人，在所有神职死亡后开启额外刀杀压垮好人阵营。",
        speech_style="发言节奏类似标准狼，避免显露独立刀杀的优势心态。",
        pressure_style="局势对狼不利时考虑通过白天压力换神。",
        reveal_policy="不主动跳身份，神职全亡前隐藏自己的额外能力。",
        wolf_disguise_style="伪装出有强逻辑的好人形象，让额外刀杀更易被认为是普通狼队行动。",
    ),
    Role.WOLF_CUB: RoleProfile(
        role=Role.WOLF_CUB,
        table_goal="像普通狼队员一样行动，必要时主动接受白天投票以触发狼队双刀。",
        speech_style="节奏与普通狼一致，关键时刻可以舍身让出票位。",
        pressure_style="被冲票时考虑是否值得换取下一晚双刀的收益。",
        reveal_policy="不主动跳；死亡后狼队即时获得加成。",
        wolf_disguise_style="制造看似好人的票型，让被投出去的代价对狼队收益最大化。",
    ),
    Role.WOLF_KING: RoleProfile(
        role=Role.WOLF_KING,
        table_goal="像猎人般威慑好人，无论何时死亡都能开枪带走一名好人。",
        speech_style="带有压迫感的强势狼发言，逼好人提前表态。",
        pressure_style="被怀疑时强调自身价值，让好人不敢轻易投自己。",
        reveal_policy="不主动跳，被推出局时开枪带走最有威胁的好人。",
        wolf_disguise_style="可以伪装成猎人或预言家以骗取信任，再用开枪反杀。",
    ),
    Role.KNIGHT: RoleProfile(
        role=Role.KNIGHT,
        table_goal="用决斗能力威慑狼队，在关键轮次锁定一只狼。",
        speech_style="冷静直接，敢于点出怀疑对象。",
        pressure_style="被怀疑时可考虑直接发动决斗，用结果证明自己的清白。",
        reveal_policy="决斗触发时被动暴露身份；除非局势紧急否则不主动跳。",
    ),
    Role.ELDER: RoleProfile(
        role=Role.ELDER,
        table_goal="利用第一次免疫的特性吸引狼刀，间接帮神职拖延轮次。",
        speech_style="平稳，不必夸张地暴露存活机制。",
        pressure_style="被怀疑时可以暗示自己是稳定好人位以缓和压力。",
        reveal_policy="第一次被刀而不死时暴露身份；之后正常死亡。",
    ),
}
