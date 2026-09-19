from __future__ import annotations

from typing import Any
from typing import Protocol

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame


class AgentRuntime(Protocol):
    """Build agents for a match without exposing Agent internals to the worker."""

    def attach(self, game: WerewolfGame, config: dict[str, Any]) -> None: ...


class LocalAgentRuntime:
    """Adapter around the existing in-process CognitiveAgent implementation.

    This is intentionally a boundary, not yet a network service. A future
    Agent Service can implement the same responsibility without changing the
    match worker's orchestration contract.
    """

    def attach(self, game: WerewolfGame, config: dict[str, Any]) -> None:
        agent_config = dict(config)
        agent_config["character_map"] = game.characters
        game.attach_agents(create_agents(game.state.players, agent_config))
