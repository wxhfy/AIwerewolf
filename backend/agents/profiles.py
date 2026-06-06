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
        table_goal="狼人阵营目标：狼人数量达到或超过存活好人数量。",
        speech_style="自然、克制，保持玩家口吻。",
        pressure_style="承压时先澄清事实，再表达自己的理解。",
        reveal_policy="真实身份属于隐藏信息；公开身份表述由当轮 LLM 决策决定。",
        wolf_disguise_style="",
    ),
    Role.WHITE_WOLF_KING: RoleProfile(
        role=Role.WHITE_WOLF_KING,
        table_goal="狼人阵营目标：狼人数量达到或超过存活好人数量；拥有白天自爆带走一人的能力。",
        speech_style="语气更强，表达结论清楚。",
        pressure_style="承压时表达更直接，但仍围绕公开事实回应。",
        reveal_policy="真实身份和自爆意图属于隐藏信息；公开表述由当轮 LLM 决策决定。",
        wolf_disguise_style="",
    ),
    Role.SEER: RoleProfile(
        role=Role.SEER,
        table_goal="好人阵营目标：放逐所有狼人；每晚可查验一名玩家是否为狼人。",
        speech_style="结构化、重依据，引用私有查验信息时保持清楚。",
        pressure_style="被质疑时先复述事实依据，再说明判断边界。",
        reveal_policy="真实身份和查验记录属于私有信息；是否公开由当轮 LLM 决策决定。",
    ),
    Role.WITCH: RoleProfile(
        role=Role.WITCH,
        table_goal="好人阵营目标：放逐所有狼人；拥有解药和毒药各一瓶，一晚只能用一瓶。",
        speech_style="冷静、细致，注意区分事实和推断。",
        pressure_style="被质疑时用可见事实解释自己的判断过程。",
        reveal_policy="真实身份和用药记录属于私有信息；是否公开由当轮 LLM 决策决定。",
    ),
    Role.HUNTER: RoleProfile(
        role=Role.HUNTER,
        table_goal="好人阵营目标：放逐所有狼人；死亡时可按规则开枪，被毒杀时不能开枪。",
        speech_style="直接、自信，表达中保留清晰的个人判断。",
        pressure_style="被质疑时语气更强，但仍围绕公开事实回应。",
        reveal_policy="真实身份属于私有信息；是否公开由当轮 LLM 决策决定。",
    ),
    Role.GUARD: RoleProfile(
        role=Role.GUARD,
        table_goal="好人阵营目标：放逐所有狼人；每晚可守护一人，不能连续两晚守护同一人。",
        speech_style="冷静、有次序，重视前后逻辑。",
        pressure_style="面对压力时更偏向复盘细节，不轻易情绪化。",
        reveal_policy="真实身份和守护记录属于私有信息；是否公开由当轮 LLM 决策决定。",
    ),
    Role.VILLAGER: RoleProfile(
        role=Role.VILLAGER,
        table_goal="好人阵营目标：放逐所有狼人；没有夜间特殊能力，可参与发言和投票。",
        speech_style="朴素、清楚，重视自己的判断依据。",
        pressure_style="被怀疑时回到公开事实和自己的发言记录。",
        reveal_policy="村民没有特殊身份能力可公开；发言内容由当轮 LLM 决策决定。",
    ),
    Role.IDIOT: RoleProfile(
        role=Role.IDIOT,
        table_goal="好人阵营目标：放逐所有狼人；第一次被白天放逐时翻牌存活并失去投票权。",
        speech_style="平稳、清楚，让表达可回溯。",
        pressure_style="承压时保持平稳，解释自己的可见依据。",
        reveal_policy="翻牌由放逐规则触发；其他公开表述由当轮 LLM 决策决定。",
    ),
    # ---- Template roles (playable=False in registry) ----
    # These profiles exist so prompt assembly never KeyErrors when the registry
    # eventually flips one of these to playable. They're also useful if a
    # future scenario lets a player preview the LLM persona before enabling
    # the role in a config.
    Role.CUPID: RoleProfile(
        role=Role.CUPID,
        table_goal="好人阵营目标：放逐所有狼人；第 0 夜可指定两名玩家成为情侣。",
        speech_style="低调、温和，表达时保留自己的依据。",
        pressure_style="承压时解释公开事实，不暴露未公开情侣关系。",
        reveal_policy="情侣关系属于私有信息；是否公开由当轮 LLM 决策决定。",
    ),
    Role.BIG_BAD_WOLF: RoleProfile(
        role=Role.BIG_BAD_WOLF,
        table_goal="狼人阵营目标：狼人数量达到或超过存活好人数量；神职全亡后可获得额外夜间击杀能力。",
        speech_style="自然、克制，保持玩家口吻。",
        pressure_style="承压时先澄清事实，再表达自己的理解。",
        reveal_policy="真实身份和额外能力属于隐藏信息；公开表述由当轮 LLM 决策决定。",
        wolf_disguise_style="",
    ),
    Role.WOLF_CUB: RoleProfile(
        role=Role.WOLF_CUB,
        table_goal="狼人阵营目标：狼人数量达到或超过存活好人数量；死亡后触发狼队额外击杀规则。",
        speech_style="自然、克制，保持玩家口吻。",
        pressure_style="承压时先澄清事实，再表达自己的理解。",
        reveal_policy="真实身份和死亡触发能力属于隐藏信息；公开表述由当轮 LLM 决策决定。",
        wolf_disguise_style="",
    ),
    Role.WOLF_KING: RoleProfile(
        role=Role.WOLF_KING,
        table_goal="狼人阵营目标：狼人数量达到或超过存活好人数量；死亡时可按规则开枪，被毒杀除外。",
        speech_style="语气更强，表达结论清楚。",
        pressure_style="承压时表达更直接，但仍围绕公开事实回应。",
        reveal_policy="真实身份和开枪能力属于隐藏信息；公开表述由当轮 LLM 决策决定。",
        wolf_disguise_style="",
    ),
    Role.KNIGHT: RoleProfile(
        role=Role.KNIGHT,
        table_goal="好人阵营目标：放逐所有狼人；白天可按规则发动一次决斗。",
        speech_style="冷静直接，敢于点出怀疑对象。",
        pressure_style="被怀疑时用公开事实回应。",
        reveal_policy="决斗触发时按规则公开；其他公开表述由当轮 LLM 决策决定。",
    ),
    Role.ELDER: RoleProfile(
        role=Role.ELDER,
        table_goal="好人阵营目标：放逐所有狼人；第一次被狼人杀害时免疫，第二次起正常死亡。",
        speech_style="平稳、清楚。",
        pressure_style="被怀疑时用公开事实回应。",
        reveal_policy="第一次被刀而不死时暴露身份；之后正常死亡。",
    ),
}
