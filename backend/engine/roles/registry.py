"""Role registry — `RoleSpec` dataclass + central `ROLE_REGISTRY` dict.

Each role module under `backend/engine/roles/` calls `register_role(...)` at
import time. Code that needs role metadata reads from `ROLE_REGISTRY` (or the
legacy `ROLE_SPECS` re-export in `engine.rules`).

The split between "playable" and "template" roles keeps the 7-12P configs
locked while still letting us ship LLM prompts / UI translations / agent
profiles for future roles that aren't wired into the engine yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.engine.models import ActionType, Alignment, Role


@dataclass(frozen=True)
class RoleSpec:
    role: Role
    alignment: Alignment

    # Display & description — used by the frontend room-setup UI and the
    # moderator panel. zh is authoritative because the product is zh-first.
    display_zh: str
    display_en: str
    description_zh: str
    description_en: str

    # Legacy string label preserved so old callers reading
    # `ROLE_SPECS[role].night_action` keep working. New code should prefer
    # `night_action_type` (a real `ActionType`) and `wakes_up_at_night`.
    night_action: str | None = None
    night_action_type: ActionType | None = None
    wakes_up_at_night: bool = False

    # Day-time abilities (Hunter shoot, WhiteWolfKing boom, future Knight duel,
    # future WolfKing shoot, etc.). Empty tuple = role takes no special day
    # action beyond talk / vote.
    day_actions: tuple[ActionType, ...] = ()

    # Symbolic names of one-shot ability flags (mirrors `RoleAbilities` fields
    # in `engine.models`). Used to surface "ability remaining" hints in
    # prompts and the UI.
    one_shot_abilities: tuple[str, ...] = ()

    # Whether this counts as a 神职 ("god" — strong village info role) for
    # rules like Big Bad Wolf's "all gods dead → extra kill". Wolves are never
    # gods even if they have abilities.
    is_god: bool = False

    # Logical grouping. "basic" = 6 baseline roles; "wolfcha" = wolfcha-spec
    # extras already wired into the engine + wolfcha templates; "extensions" =
    # other-framework templates (lykos/werewolf-brain/etc.).
    pack: str = "basic"

    # If False, the role is a scaffold only: registry/i18n/playbook are set up
    # but `WOLFCHA_ROLE_CONFIGS` won't pick it and the engine has no phase
    # routing for it yet. Promote to True together with the engine wiring PR.
    playable: bool = True

    # Free-form tags for forward compatibility (e.g. "lovers", "boom",
    # "shoot-on-death"). Currently informational; future engine logic can key
    # off this without changing the dataclass shape.
    tags: tuple[str, ...] = field(default_factory=tuple)


ROLE_REGISTRY: dict[Role, RoleSpec] = {}


def register_role(spec: RoleSpec) -> None:
    """Register a role. Duplicate registration is a hard error — it almost
    always means the same role was defined in two pack modules by mistake.
    """
    if spec.role in ROLE_REGISTRY:
        raise ValueError(
            f"Role {spec.role.value} already registered. "
            "Each role must live in exactly one pack module."
        )
    ROLE_REGISTRY[spec.role] = spec


def get_playable_roles() -> list[Role]:
    """Returns roles eligible for inclusion in player-count configs.

    Used by `engine.rules.WOLFCHA_ROLE_CONFIGS` validation and future role
    pickers. Template roles (`playable=False`) are excluded.
    """
    return [role for role, spec in ROLE_REGISTRY.items() if spec.playable]
