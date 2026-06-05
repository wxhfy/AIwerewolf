"""Wolf-aligned roles wired into the engine."""

from __future__ import annotations

from backend.engine.models import ActionType
from backend.engine.models import Alignment
from backend.engine.models import Role
from backend.engine.roles.registry import RoleSpec
from backend.engine.roles.registry import register_role

register_role(
    RoleSpec(
        role=Role.WEREWOLF,
        alignment=Alignment.WOLF,
        display_zh="狼人",
        display_en="Werewolf",
        description_zh="夜晚与队友共同决定刀杀目标。",
        description_en="Coordinates with teammates each night to attack one villager.",
        night_action="attack",
        night_action_type=ActionType.ATTACK,
        wakes_up_at_night=True,
        pack="basic",
        tags=("wolf-family",),
    )
)


register_role(
    RoleSpec(
        role=Role.WHITE_WOLF_KING,
        alignment=Alignment.WOLF,
        display_zh="白狼王",
        display_en="White Wolf King",
        description_zh="白天可自爆并带走一名好人（一次性）；夜晚跟随狼队但不投票。",
        description_en="Daytime self-destruct that kills one villager (one-shot); wakes with wolves but doesn't vote for the kill.",
        night_action="attack",
        night_action_type=ActionType.ATTACK,
        wakes_up_at_night=True,
        day_actions=(ActionType.BOOM,),
        one_shot_abilities=("white_wolf_king_boom_used",),
        pack="wolfcha",
        tags=("wolf-family", "boom"),
    )
)
