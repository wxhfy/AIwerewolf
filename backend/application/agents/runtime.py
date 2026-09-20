from __future__ import annotations

from typing import Any
from typing import Protocol

from backend.application.agents.harness_runtime import build_harness_runtime
from backend.engine.game import WerewolfGame


class AgentRuntime(Protocol):
    """Build agents for a match without exposing Agent internals to the worker."""

    def attach(self, game: WerewolfGame, config: dict[str, Any]) -> None: ...


class LocalAgentRuntime:
    """Attach the in-process harness implementation at the Agent Service seam."""

    def attach(self, game: WerewolfGame, config: dict[str, Any]) -> None:
        game.attach_decision_runtime(build_harness_runtime(game.state.players, dict(config)))
