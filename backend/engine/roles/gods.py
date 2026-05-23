"""Village 神职 — the four "god" info / utility roles wired into the engine.

These are the four roles `is_god=True` because they hold meaningful private
information or one-shot abilities. The flag is reserved for future "all gods
dead" rules (e.g. Big Bad Wolf's extra kill trigger).
"""
from __future__ import annotations

from backend.engine.models import ActionType, Alignment, Role
from backend.engine.roles.registry import RoleSpec, register_role


register_role(
    RoleSpec(
        role=Role.SEER,
        alignment=Alignment.VILLAGE,
        display_zh="预言家",
        display_en="Seer",
        description_zh="每晚查验一人身份阵营，是好人的主信息位。",
        description_en="Checks one player's alignment each night.",
        night_action="divine",
        night_action_type=ActionType.DIVINE,
        wakes_up_at_night=True,
        is_god=True,
        pack="basic",
    )
)


register_role(
    RoleSpec(
        role=Role.WITCH,
        alignment=Alignment.VILLAGE,
        display_zh="女巫",
        display_en="Witch",
        description_zh="拥有一瓶解药和一瓶毒药，整局各一次。",
        description_en="One save potion and one poison, each usable once per game.",
        night_action="potion",
        night_action_type=ActionType.WITCH_SAVE,  # WITCH_POISON shares the slot
        wakes_up_at_night=True,
        one_shot_abilities=("witch_heal_used", "witch_poison_used"),
        is_god=True,
        pack="basic",
    )
)


register_role(
    RoleSpec(
        role=Role.HUNTER,
        alignment=Alignment.VILLAGE,
        display_zh="猎人",
        display_en="Hunter",
        description_zh="死亡时（被毒杀除外）可开枪带走一名玩家。",
        description_en="Shoots one player when eliminated, unless poisoned.",
        night_action=None,
        wakes_up_at_night=False,
        day_actions=(ActionType.SHOOT,),
        one_shot_abilities=("hunter_can_shoot",),
        is_god=True,
        pack="basic",
    )
)


register_role(
    RoleSpec(
        role=Role.GUARD,
        alignment=Alignment.VILLAGE,
        display_zh="守卫",
        display_en="Guard",
        description_zh="每晚守护一人不被狼人杀害，不能连续两晚守同一人。",
        description_en="Protects one player each night; cannot guard the same player twice in a row.",
        night_action="guard",
        night_action_type=ActionType.GUARD,
        wakes_up_at_night=True,
        is_god=True,
        pack="basic",
    )
)
