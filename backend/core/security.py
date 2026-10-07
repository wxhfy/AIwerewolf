from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Annotated
from typing import Protocol

from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException

from backend.core.config import settings


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    actor_type: str
    roles: tuple[str, ...] = ()


class TokenVerifier(Protocol):
    def verify(self, token: str) -> ActorContext: ...


def _verify_static_token(token: str) -> ActorContext:
    """Verify ``token|actor_id|role1,role2`` entries from AUTH_TOKENS."""
    for entry in os.getenv("AUTH_TOKENS", "").split(","):
        parts = entry.strip().split("|", 2)
        if len(parts) != 3:
            continue
        expected, actor_id, roles = parts
        if hmac.compare_digest(token, expected):
            return ActorContext(actor_id=actor_id, actor_type="token", roles=tuple(r for r in roles.split(";") if r))
    raise HTTPException(status_code=401, detail="Invalid bearer token")


def actor_from_authorization(authorization: str | None) -> ActorContext:
    auth_mode = os.getenv("AUTH_MODE", settings.auth_mode).strip().lower()
    if auth_mode == "disabled":
        return ActorContext(actor_id="anonymous", actor_type="development")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    if auth_mode == "static_token":
        return _verify_static_token(authorization[7:].strip())
    raise HTTPException(status_code=501, detail="Configured authentication verifier is unavailable")


def get_actor(authorization: str | None = Header(default=None)) -> ActorContext:
    """Authentication seam. Replace this dependency with JWT/OIDC verification in production."""
    return actor_from_authorization(authorization)


def require_moderator(actor: ActorContext) -> ActorContext:
    if os.getenv("AUTH_MODE", settings.auth_mode).strip().lower() != "disabled" and "moderator" not in actor.roles:
        raise HTTPException(status_code=403, detail="Moderator role required")
    return actor


CurrentActor = Annotated[ActorContext, Depends(get_actor)]
