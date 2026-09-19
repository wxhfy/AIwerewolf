from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Field


class AgentDecisionRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    match_id: str
    player_id: str
    action_type: str
    observation: dict[str, Any]
    legal_actions: list[dict[str, Any]] = Field(default_factory=list)
    agent_config: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: int = Field(default=30_000, ge=100, le=300_000)


class AgentUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


class AgentDecisionResult(BaseModel):
    request_id: str
    status: str
    action: dict[str, Any] | None = None
    reasoning: str = ""
    usage: AgentUsage = Field(default_factory=AgentUsage)
    trace: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentCapabilities(BaseModel):
    protocol_version: str = "v1"
    execution_modes: list[str] = Field(default_factory=lambda: ["local"])
    supported_actions: list[str] = Field(
        default_factory=lambda: [
            "talk",
            "vote",
            "attack",
            "divine",
            "guard",
            "witch_act",
            "shoot",
            "boom",
            "transfer_badge",
        ]
    )
    remote_execution_ready: bool = False
