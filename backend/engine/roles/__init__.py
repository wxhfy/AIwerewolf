"""Single source of truth for werewolf role metadata.

Importing this package triggers each role module's `register_role(...)` call so
`ROLE_REGISTRY` is fully populated. Downstream code reads through `ROLE_REGISTRY`
(or the legacy `ROLE_SPECS` shim in `engine.rules`) instead of hard-coding role
behavior inline.

To add a new role, see `backend/engine/roles/README.md`.
"""

from __future__ import annotations

# Import side-effects: each module registers its roles at import time. Order
# only matters for human readability — registration rejects duplicates so a
# conflict surfaces immediately.
from backend.engine.roles import basic  # noqa: F401
from backend.engine.roles import extensions  # noqa: F401
from backend.engine.roles import gods  # noqa: F401
from backend.engine.roles import wolfcha  # noqa: F401
from backend.engine.roles import wolves  # noqa: F401
from backend.engine.roles.registry import ROLE_REGISTRY
from backend.engine.roles.registry import RoleSpec
from backend.engine.roles.registry import get_playable_roles
from backend.engine.roles.registry import register_role

__all__ = ["ROLE_REGISTRY", "RoleSpec", "get_playable_roles", "register_role"]
