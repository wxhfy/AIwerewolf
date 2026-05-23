"""Wolfcha-style roles.

Contains the playable IDIOT (already wired into the engine) plus three
template roles from wolfcha's role catalog that are NOT yet wired into the
engine and therefore ship as `playable=False`:

  - CUPID — village; night 0 picks two lovers who die together
  - BIG_BAD_WOLF — wolf; after all 4 gods die, gets a solo extra kill
  - WOLF_CUB — wolf; when killed by villagers, wolves get a second kill next
    night

Promote any of these by flipping `playable=True` once the engine routes the
new night/day phase, then add them to `WOLFCHA_ROLE_CONFIGS` if you want them
in default seat configs.
"""
from __future__ import annotations

from backend.engine.models import Alignment, Role
from backend.engine.roles.registry import RoleSpec, register_role


register_role(
    RoleSpec(
        role=Role.IDIOT,
        alignment=Alignment.VILLAGE,
        display_zh="白痴",
        display_en="Idiot",
        description_zh="被白天投票放逐时翻牌存活，但失去投票权。",
        description_en="Survives the first day-exile by revealing, then loses voting rights.",
        one_shot_abilities=("idiot_revealed",),
        pack="wolfcha",
        playable=True,
        tags=("survives-first-exile",),
    )
)


register_role(
    RoleSpec(
        role=Role.CUPID,
        alignment=Alignment.VILLAGE,
        display_zh="丘比特",
        display_en="Cupid",
        description_zh="第 0 夜指定两名情侣，其中一人死亡时另一人殉情。",
        description_en="Night 0 picks two lovers; when one dies, the other dies too.",
        wakes_up_at_night=True,
        pack="wolfcha",
        playable=False,
        tags=("lovers", "night-zero"),
    )
)


register_role(
    RoleSpec(
        role=Role.BIG_BAD_WOLF,
        alignment=Alignment.WOLF,
        display_zh="大恶狼",
        display_en="Big Bad Wolf",
        description_zh="所有神职死亡后，每晚可在狼队刀杀之外多刀一人。",
        description_en="After all village gods are dead, gets an extra solo kill each night.",
        wakes_up_at_night=True,
        pack="wolfcha",
        playable=False,
        tags=("wolf-family", "extra-kill"),
    )
)


register_role(
    RoleSpec(
        role=Role.WOLF_CUB,
        alignment=Alignment.WOLF,
        display_zh="小狼狗",
        display_en="Wolf Cub",
        description_zh="被好人投票放逐或被毒杀时，狼队下一晚获得双刀。",
        description_en="When killed by villagers, wolves get two kills the following night.",
        wakes_up_at_night=True,
        pack="wolfcha",
        playable=False,
        tags=("wolf-family", "death-trigger"),
    )
)
