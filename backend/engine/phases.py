from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from backend.engine.game import WerewolfGame  # noqa: F401

from backend.engine.models import Phase


class PhaseHandler(Protocol):
    phase: Phase

    def run(self, game: "WerewolfGame") -> None: ...


@dataclass(frozen=True)
class AtomicPhase:
    phase: Phase
    runner_name: str

    def run(self, game: "WerewolfGame") -> None:
        getattr(game, self.runner_name)()


@dataclass(frozen=True)
class CompositePhase:
    phase: Phase
    steps: tuple[PhaseHandler, ...]

    def run(self, game: "WerewolfGame") -> None:
        import time as _time

        micro_delay = getattr(game, "phase_delay_ms", 0) / 4000  # ~25% of phase delay, min floor 0.05s
        for idx, step in enumerate(self.steps):
            step.run(game)
            if game.state.winner is not None or getattr(game, "interrupt_phase_cycle", False):
                break
            if idx < len(self.steps) - 1:
                _time.sleep(max(0.08, micro_delay))


def default_phase_handlers() -> dict[Phase, PhaseHandler]:
    night = CompositePhase(
        phase=Phase.NIGHT_START,
        steps=(
            AtomicPhase(Phase.NIGHT_START, "_begin_night"),
            AtomicPhase(Phase.NIGHT_GUARD_ACTION, "_guard_phase"),
            AtomicPhase(Phase.NIGHT_WOLF_ACTION, "_wolf_phase"),
            AtomicPhase(Phase.NIGHT_WITCH_ACTION, "_witch_phase"),
            AtomicPhase(Phase.NIGHT_SEER_ACTION, "_seer_phase"),
            AtomicPhase(Phase.NIGHT_RESOLVE, "_night_resolve"),
        ),
    )
    day = CompositePhase(
        phase=Phase.DAY_START,
        steps=(
            AtomicPhase(Phase.DAY_START, "_begin_day"),
            AtomicPhase(Phase.DAY_BADGE_SIGNUP, "_badge_signup_phase"),
            AtomicPhase(Phase.DAY_BADGE_SPEECH, "_badge_speech_phase"),
            AtomicPhase(Phase.DAY_BADGE_ELECTION, "_badge_election_phase"),
            AtomicPhase(Phase.DAY_SPEECH, "_speech_phase"),
            AtomicPhase(Phase.DAY_SHERIFF_CLOSING, "_sheriff_closing_phase"),
            AtomicPhase(Phase.DAY_VOTE, "_vote_phase"),
            AtomicPhase(Phase.DAY_RESOLVE, "_day_resolve"),
        ),
    )
    hunter = AtomicPhase(Phase.HUNTER_SHOOT, "_hunter_shoot_from_pending")
    badge_transfer = AtomicPhase(Phase.BADGE_TRANSFER, "_badge_transfer_from_pending")
    return {
        Phase.NIGHT_START: night,
        Phase.DAY_START: day,
        Phase.HUNTER_SHOOT: hunter,
        Phase.BADGE_TRANSFER: badge_transfer,
    }
