from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel
from pydantic import Field


class MatchCommandType(str, Enum):
    pause = "pause"
    resume = "resume"
    cancel = "cancel"


class MatchCommandRequest(BaseModel):
    command_id: str = Field(min_length=8, max_length=128)
    type: MatchCommandType
    expected_seq: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class MatchCommandResponse(BaseModel):
    command_id: str
    match_id: str
    type: MatchCommandType
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
