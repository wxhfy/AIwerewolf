from __future__ import annotations

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


def get_actor(authorization: str | None = Header(default=None)) -> ActorContext:
    """Authentication seam. Replace this dependency with JWT/OIDC verification in production."""
    if settings.auth_mode == "disabled":
        return ActorContext(actor_id="anonymous", actor_type="development")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    raise HTTPException(status_code=501, detail="JWT/OIDC verifier is not configured")


CurrentActor = Annotated[ActorContext, Depends(get_actor)]
