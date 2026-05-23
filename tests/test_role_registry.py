"""Smoke tests for the role registry.

Covers:
- Every Role enum member has a registered RoleSpec (catches half-added roles).
- `get_playable_roles()` excludes templates.
- The locked 7-12P configs never include template roles.
- `register_role()` rejects duplicate registration.
- Every Role has an `ACTION_PLAYBOOKS` entry AND a `ROLE_PROFILES` entry AND
  a `ROLE_SYSTEM_PROMPTS` entry (so prompt assembly never KeyErrors).
"""
from __future__ import annotations

import pytest

from backend.agents.playbooks import ACTION_PLAYBOOKS
from backend.agents.profiles import ROLE_PROFILES
from backend.agents.prompts import ROLE_SYSTEM_PROMPTS
from backend.engine.models import Role
from backend.engine.roles import ROLE_REGISTRY, RoleSpec, get_playable_roles, register_role
from backend.engine.rules import WOLFCHA_ROLE_CONFIGS


def test_every_role_is_registered() -> None:
    """Every Role enum member must have a RoleSpec in the registry.

    This catches the common mistake of adding a Role enum value without
    creating a pack module entry.
    """
    enum_roles = set(Role)
    registered = set(ROLE_REGISTRY.keys())
    assert enum_roles == registered, f"unregistered roles: {enum_roles - registered}"


def test_playable_roles_excludes_templates() -> None:
    playable = set(get_playable_roles())
    templates = {r for r, spec in ROLE_REGISTRY.items() if not spec.playable}
    assert playable & templates == set()
    assert len(playable) + len(templates) == len(Role)


def test_locked_configs_only_use_playable_roles() -> None:
    """The 7-12P configs are locked to playable roles. Template roles can
    never sneak into the auto-config until their engine wiring lands.
    """
    playable = set(get_playable_roles())
    for player_count, roles in WOLFCHA_ROLE_CONFIGS.items():
        for role in roles:
            assert role in playable, (
                f"{player_count}P config contains template role {role.value!r}"
            )


def test_register_role_rejects_duplicates() -> None:
    """Re-registering an existing role must raise — it's almost always a
    sign that the same role was defined in two pack modules.
    """
    existing = next(iter(ROLE_REGISTRY.values()))
    with pytest.raises(ValueError, match="already registered"):
        register_role(existing)


def test_agent_metadata_covers_all_roles() -> None:
    """The three role-keyed dicts in the agents layer must cover every Role.

    `ROLE_PROFILES` is the strictest — `llm_agent.py` does `.get` with a
    VILLAGER fallback, but explicit entries produce better LLM behavior.
    """
    for role in Role:
        assert role in ROLE_PROFILES, f"missing ROLE_PROFILES entry for {role.value}"
        assert role in ROLE_SYSTEM_PROMPTS, f"missing ROLE_SYSTEM_PROMPTS entry for {role.value}"
        assert role in ACTION_PLAYBOOKS, f"missing ACTION_PLAYBOOKS entry for {role.value}"


def test_role_spec_shape() -> None:
    """Spot-check that RoleSpec is frozen and carries the documented fields."""
    seer = ROLE_REGISTRY[Role.SEER]
    assert isinstance(seer, RoleSpec)
    assert seer.is_god is True
    assert seer.wakes_up_at_night is True
    assert seer.playable is True
    # Frozen — attempts to mutate must fail.
    with pytest.raises(Exception):
        seer.playable = False  # type: ignore[misc]


def test_template_roles_have_correct_pack() -> None:
    """Sanity check: every template role belongs to wolfcha or extensions
    (not 'basic'), and basic roles are all playable.
    """
    for role, spec in ROLE_REGISTRY.items():
        if not spec.playable:
            assert spec.pack in ("wolfcha", "extensions"), (
                f"{role.value} is unplayable but in pack {spec.pack!r}"
            )
        if spec.pack == "basic":
            assert spec.playable, f"basic-pack role {role.value} should be playable"
