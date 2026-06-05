from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.engine.game import WerewolfGame  # noqa: F401

from backend.engine.models import Phase
from backend.engine.phases import PhaseHandler
from backend.engine.phases import default_phase_handlers


class PhaseManager:
    """Reference-inspired phase dispatcher.

    The manager keeps the execution order explicit and makes it easy to replace
    or extend phases without rewriting the top-level game loop.
    """

    def __init__(self, handlers: dict[Phase, PhaseHandler] | None = None):
        self.handlers = handlers or default_phase_handlers()

    def run(self, phase: Phase, game: "WerewolfGame") -> None:
        handler = self.handlers.get(phase)
        if handler is None:
            raise KeyError(f"No phase handler registered for {phase.value}")
        handler.run(game)
