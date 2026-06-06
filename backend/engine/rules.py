from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Iterable
from uuid import uuid4

from backend.engine.models import Alignment
from backend.engine.models import Player
from backend.engine.models import Role

# Importing the roles package triggers each module's `register_role(...)` so
# `ROLE_REGISTRY` is fully populated before anything below reads it.
from backend.engine.roles import ROLE_REGISTRY
from backend.engine.roles import get_playable_roles
from backend.engine.roles.registry import RoleSpec as _RegistryRoleSpec


# Legacy `RoleSpec` shape — kept for back-compat with callers that read
# `ROLE_SPECS[role].night_action` / `.alignment` / `.description`. The
# authoritative spec is `backend.engine.roles.registry.RoleSpec`; we down-cast
# at import time so the old call sites keep working unchanged.
@dataclass(frozen=True)
class RoleSpec:
    role: Role
    alignment: Alignment
    night_action: str | None = None
    description: str = ""


def _legacy_spec(spec: _RegistryRoleSpec) -> RoleSpec:
    return RoleSpec(
        role=spec.role,
        alignment=spec.alignment,
        night_action=spec.night_action,
        description=spec.description_en,
    )


ROLE_SPECS: dict[Role, RoleSpec] = {role: _legacy_spec(spec) for role, spec in ROLE_REGISTRY.items()}


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
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.GUARD,
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


# Sanity check: the 7-12P configs are locked to playable roles only. Template
# roles (playable=False in the registry) must never sneak into the auto-config
# until their engine wiring lands. Validated at import time so the failure is
# loud rather than surfacing as a half-broken game three days later.
def _validate_configs_only_use_playable_roles() -> None:
    playable = set(get_playable_roles())
    for n, roles in WOLFCHA_ROLE_CONFIGS.items():
        unplayable = [r for r in roles if r not in playable]
        if unplayable:
            names = ", ".join(r.value for r in unplayable)
            raise RuntimeError(
                f"{n}P config contains template roles ({names}). "
                "Mark them playable=True in the registry, or remove from the config."
            )


_validate_configs_only_use_playable_roles()


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
            "Ada",
            "Bert",
            "Cora",
            "Duke",
            "Eli",
            "Faye",
            "Gina",
            "Hale",
            "Iris",
            "Jude",
            "Kira",
            "Luca",
            "Mina",
            "Nora",
            "Orin",
            "Pia",
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
