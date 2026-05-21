from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.engine.models import GameEvent, GameState, Player, Role


@dataclass(frozen=True)
class PlayerView:
    player_id: str
    day: int
    phase: str
    self_player: dict[str, Any]
    players: list[dict[str, Any]]
    public_events: list[dict[str, Any]]
    private_events: list[dict[str, Any]]
    known_wolves: list[dict[str, Any]]
    observations: list[str]


class Visibility:
    """Builds per-agent views and keeps private role information isolated."""

    def for_player(self, state: GameState, player_id: str) -> PlayerView:
        player = state.player(player_id)
        public_events = [event.to_dict() for event in state.events if event.visibility == "public"]
        private_events = [
            event.to_dict()
            for event in state.events
            if event.visibility == "private" and player_id in event.visible_to
        ]
        known_wolves = []
        if player.role == Role.WEREWOLF:
            known_wolves = [p.private_dict() for p in state.players if p.role == Role.WEREWOLF]

        return PlayerView(
            player_id=player_id,
            day=state.day,
            phase=state.phase.value,
            self_player=player.private_dict(),
            players=[self._visible_player(player, target) for target in state.players],
            public_events=public_events,
            private_events=private_events,
            known_wolves=known_wolves,
            observations=self._observations(private_events),
        )

    def _visible_player(self, viewer: Player, target: Player) -> dict[str, Any]:
        if viewer.id == target.id:
            return target.private_dict()
        if viewer.role == Role.WEREWOLF and target.role == Role.WEREWOLF:
            return target.private_dict()
        return target.public_dict()

    def _observations(self, events: list[dict[str, Any]]) -> list[str]:
        observations: list[str] = []
        for event in events:
            payload = event["payload"]
            if event["type"] == "PRIVATE_INFO":
                observations.append(str(payload.get("message", "")))
        return [item for item in observations if item]
