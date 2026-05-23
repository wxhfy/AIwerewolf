"""Baseline village role: plain villager."""
from __future__ import annotations

from backend.engine.models import Alignment, Role
from backend.engine.roles.registry import RoleSpec, register_role


register_role(
    RoleSpec(
        role=Role.VILLAGER,
        alignment=Alignment.VILLAGE,
        display_zh="村民",
        display_en="Villager",
        description_zh="无技能好人，靠发言和投票揪出狼人。",
        description_en="Plain villager — finds wolves by speech and voting.",
        pack="basic",
    )
)
