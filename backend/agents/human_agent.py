from __future__ import annotations

from backend.agents.base import Agent
from backend.engine.models import ActionType, Decision
from backend.engine.visibility import PlayerView


class HumanAgent(Agent):
    """Placeholder agent for a human-controlled seat.

    The game engine intercepts human actions before these methods execute, so
    this class mainly keeps the lifecycle contract consistent.
    """

    def __init__(self, player_id: str):
        self.player_id = player_id
        self.view: PlayerView | None = None

    def initialize(self, view: PlayerView, game_setting: dict) -> None:
        self.view = view

    def update(self, view: PlayerView, request: str) -> None:
        self.view = view

    def day_start(self) -> None:
        return

    def talk(self) -> Decision:
        return Decision(self.player_id, ActionType.TALK, speech="")

    def vote(self) -> Decision:
        return Decision(self.player_id, ActionType.VOTE, target_id=None)

    def attack(self) -> Decision:
        return Decision(self.player_id, ActionType.ATTACK, target_id=None)

    def divine(self) -> Decision:
        return Decision(self.player_id, ActionType.DIVINE, target_id=None)

    def guard(self) -> Decision:
        return Decision(self.player_id, ActionType.GUARD, target_id=None)

    def witch_act(self, victim_id: str | None) -> list[Decision]:
        return [Decision(self.player_id, ActionType.SKIP, reasoning="Awaiting human input.")]

    def shoot(self) -> Decision:
        return Decision(self.player_id, ActionType.SHOOT, target_id=None)

    def boom(self) -> Decision:
        return Decision(self.player_id, ActionType.BOOM, target_id=None)

    def finish(self, winner: str | None) -> None:
        return
