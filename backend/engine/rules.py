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
    Role.WHITE_WOLF_KING: RoleSpec(Role.WHITE_WOLF_KING, Alignment.WOLF, "attack", "Wolf role that can self-destruct during the day and take one player."),
    Role.SEER: RoleSpec(Role.SEER, Alignment.VILLAGE, "divine", "Checks one player's alignment each night."),
    Role.WITCH: RoleSpec(Role.WITCH, Alignment.VILLAGE, "potion", "Can save one night victim and poison one player once per game."),
    Role.HUNTER: RoleSpec(Role.HUNTER, Alignment.VILLAGE, None, "Can shoot once when eliminated, unless poisoned."),
    Role.GUARD: RoleSpec(Role.GUARD, Alignment.VILLAGE, "guard", "Protects one player each night."),
    Role.VILLAGER: RoleSpec(Role.VILLAGER, Alignment.VILLAGE, None, "Finds wolves by speech and voting."),
    Role.IDIOT: RoleSpec(Role.IDIOT, Alignment.VILLAGE, None, "Immune to the first exile, then loses voting rights after revealing."),
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


WOLFCHA_ROLE_CONFIGS: dict[int, tuple[Role, ...]] = {
    7: DEFAULT_ROLE_SET,
    8: (
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.VILLAGER,
        Role.VILLAGER,
    ),
    9: (
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.VILLAGER,
        Role.VILLAGER,
        Role.VILLAGER,
    ),
    10: (
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WHITE_WOLF_KING,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.GUARD,
        Role.VILLAGER,
        Role.VILLAGER,
        Role.VILLAGER,
    ),
    11: (
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WHITE_WOLF_KING,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.GUARD,
        Role.IDIOT,
        Role.VILLAGER,
        Role.VILLAGER,
    ),
    12: (
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WHITE_WOLF_KING,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.GUARD,
        Role.IDIOT,
        Role.VILLAGER,
        Role.VILLAGER,
        Role.VILLAGER,
    ),
}


def get_role_configuration(player_count: int) -> tuple[Role, ...]:
    if player_count not in WOLFCHA_ROLE_CONFIGS:
        raise ValueError(f"Unsupported player count: {player_count}")
    return WOLFCHA_ROLE_CONFIGS[player_count]


def build_players(
    roles: Iterable[Role] = DEFAULT_ROLE_SET,
    *,
    seed: int | None = None,
    names: list[str] | None = None,
) -> list[Player]:
    role_list = list(roles)
    rng = Random(seed)
    rng.shuffle(role_list)
    # Use character names from persona pool for more human feel
    from backend.agents.characters import PERSONA_POOL

    rng_char = Random(seed)
    char_pool = [p["name"] for p in PERSONA_POOL]
    rng_char.shuffle(char_pool)
    if len(char_pool) >= len(role_list):
        default_names = char_pool[: len(role_list)]
    else:
        fallback_pool = [
            "Ada", "Bert", "Cora", "Duke", "Eli", "Faye", "Gina", "Hale",
            "Iris", "Jude", "Kira", "Luca", "Mina", "Nora", "Orin", "Pia",
        ]
        default_names = list(char_pool)
        for name in fallback_pool:
            if len(default_names) >= len(role_list):
                break
            if name not in default_names:
                default_names.append(name)
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
