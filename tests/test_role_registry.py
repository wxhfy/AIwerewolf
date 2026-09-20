from __future__ import annotations

import pytest

from backend.engine.models import Role
from backend.engine.roles import ROLE_REGISTRY
from backend.engine.roles import RoleSpec
from backend.engine.roles import get_playable_roles
from backend.engine.roles import register_role
from backend.engine.rules import WOLFCHA_ROLE_CONFIGS


def test_every_role_is_registered() -> None:
    assert set(Role) == set(ROLE_REGISTRY)


def test_playable_roles_exclude_templates() -> None:
    playable = set(get_playable_roles())
    templates = {role for role, spec in ROLE_REGISTRY.items() if not spec.playable}
    assert not playable & templates
    assert len(playable) + len(templates) == len(Role)


def test_locked_configs_only_use_playable_roles() -> None:
    playable = set(get_playable_roles())
    for player_count, roles in WOLFCHA_ROLE_CONFIGS.items():
        assert all(role in playable for role in roles), f"{player_count}P config contains a template role"


def test_register_role_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_role(next(iter(ROLE_REGISTRY.values())))


def test_role_spec_shape() -> None:
    seer = ROLE_REGISTRY[Role.SEER]
    assert isinstance(seer, RoleSpec)
    assert seer.is_god is True
    assert seer.wakes_up_at_night is True
    assert seer.playable is True
    with pytest.raises(AttributeError):
        seer.playable = False  # type: ignore[misc]
