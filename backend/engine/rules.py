from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Iterable
from uuid import uuid4

from backend.engine.models import Alignment, Player, Role


@dataclass(frozen=True)
class RoleSpec:
    role: Role
    alignment: Alignment
    night_action: str | None = None
    description: str = ""


ROLE_SPECS: dict[Role, RoleSpec] = {
    Role.WEREWOLF: RoleSpec(Role.WEREWOLF, Alignment.WOLF, "attack", "Works with wolves to remove villagers."),
    Role.SEER: RoleSpec(Role.SEER, Alignment.VILLAGE, "divine", "Checks one player's alignment each night."),
    Role.WITCH: RoleSpec(Role.WITCH, Alignment.VILLAGE, "potion", "Can save one night victim and poison one player once per game."),
    Role.HUNTER: RoleSpec(Role.HUNTER, Alignment.VILLAGE, None, "Can shoot once when eliminated, unless poisoned."),
    Role.GUARD: RoleSpec(Role.GUARD, Alignment.VILLAGE, "guard", "Protects one player each night."),
    Role.VILLAGER: RoleSpec(Role.VILLAGER, Alignment.VILLAGE, None, "Finds wolves by speech and voting."),
}


DEFAULT_ROLE_SET: tuple[Role, ...] = (
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.SEER,
    Role.WITCH,
    Role.HUNTER,
    Role.GUARD,
    Role.VILLAGER,
)


def build_players(
    roles: Iterable[Role] = DEFAULT_ROLE_SET,
    *,
    seed: int | None = None,
    names: list[str] | None = None,
) -> list[Player]:
    role_list = list(roles)
    rng = Random(seed)
    rng.shuffle(role_list)
    default_names = ["Ada", "Bert", "Cora", "Duke", "Eli", "Faye", "Gina", "Hale", "Iris", "Joss"]
    names = names or default_names
    if len(names) < len(role_list):
        raise ValueError("Not enough names for the configured roles.")

    players: list[Player] = []
    for index, role in enumerate(role_list, start=1):
        spec = ROLE_SPECS[role]
        players.append(
            Player(
                id=f"P{index}-{uuid4().hex[:6]}",
                seat=index,
                name=names[index - 1],
                role=role,
                alignment=spec.alignment,
            )
        )
    return players


def is_wolf(role: Role) -> bool:
    return ROLE_SPECS[role].alignment == Alignment.WOLF
