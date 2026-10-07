from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from backend.engine.models import Alignment
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player


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
    legal_targets: list[dict[str, Any]] = field(default_factory=list)
    game_id: str = ""


class Visibility:
    """Builds per-agent views and keeps private role information isolated."""

    def for_player(self, state: GameState, player_id: str) -> PlayerView:
        player = state.player(player_id)
        public_events = [event.to_dict() for event in state.events if event.visibility == "public"]
        private_events = [
            event.to_dict() for event in state.events if event.visibility == "private" and player_id in event.visible_to
        ]
        known_wolves = []
        if player.alignment == Alignment.WOLF:
            known_wolves = [p.private_dict() for p in state.players if p.alignment == Alignment.WOLF]

        view = PlayerView(
            player_id=player_id,
            day=state.day,
            phase=state.phase.value,
            self_player=player.private_dict(),
            players=[self._visible_player(player, target) for target in state.players],
            public_events=public_events,
            private_events=private_events,
            known_wolves=known_wolves,
            observations=self._observations(private_events),
            legal_targets=self._legal_targets(state, player),
            game_id=state.id,
        )
        self._assert_safe(view, player)
        return view

    @staticmethod
    def _assert_safe(view: PlayerView, viewer: Player) -> None:
        """Fail closed if a projection accidentally contains hidden role data."""
        if view.self_player.get("id") != viewer.id:
            raise RuntimeError("PlayerView self_player does not match viewer")
        if "role" not in view.self_player or "alignment" not in view.self_player:
            raise RuntimeError("PlayerView must include the viewer's private role data")

        known_wolf_ids = {str(item.get("id")) for item in view.known_wolves}
        if viewer.alignment != Alignment.WOLF and known_wolf_ids:
            raise RuntimeError("Non-wolf PlayerView cannot contain known wolf teammates")
        if any(item.get("alignment") != Alignment.WOLF.value for item in view.known_wolves):
            raise RuntimeError("Known wolf projection contains a non-wolf player")

        for item in view.players:
            is_self = str(item.get("id")) == viewer.id
            is_wolf_teammate = str(item.get("id")) in known_wolf_ids
            if is_self or is_wolf_teammate:
                if "role" not in item or "alignment" not in item:
                    raise RuntimeError("Private teammate projection lost required role data")
            elif "role" in item or "alignment" in item:
                raise RuntimeError("PlayerView leaked another player's role or alignment")

        for event in view.public_events:
            if str(event.get("visibility") or "public") == "private":
                raise RuntimeError("Private event entered public PlayerView history")
        for event in view.private_events:
            if str(event.get("visibility") or "") != "private":
                raise RuntimeError("Non-private event entered private PlayerView history")
            if viewer.id not in list(event.get("visible_to") or []):
                raise RuntimeError("Private event is not addressed to the viewer")

    def _visible_player(self, viewer: Player, target: Player) -> dict[str, Any]:
        if viewer.id == target.id:
            return target.private_dict()
        if viewer.alignment == Alignment.WOLF and target.alignment == Alignment.WOLF:
            return target.private_dict()
        return target.public_dict()

    def _observations(self, events: list[dict[str, Any]]) -> list[str]:
        observations: list[str] = []
        for event in events:
            payload = event["payload"]
            if event["type"] == "PRIVATE_INFO":
                observations.append(str(payload.get("message", "")))
        return [item for item in observations if item]

    def _legal_targets(self, state: GameState, player: Player) -> list[dict[str, Any]]:
        target_ids: set[str] | None = None
        include_self = False

        if state.phase == Phase.DAY_BADGE_ELECTION and state.badge.candidates:
            target_ids = set(state.badge.candidates)
            include_self = True
        elif state.phase == Phase.DAY_VOTE and state.pk_targets:
            target_ids = set(state.pk_targets)
        elif state.phase == Phase.NIGHT_WOLF_ACTION:
            target_ids = {target.id for target in state.alive_players if target.alignment != Alignment.WOLF}
        elif state.phase in {
            Phase.DAY_VOTE,
            Phase.NIGHT_SEER_ACTION,
            Phase.HUNTER_SHOOT,
            Phase.WHITE_WOLF_KING_BOOM,
            Phase.BADGE_TRANSFER,
        }:
            target_ids = {target.id for target in state.alive_players}
        elif state.phase == Phase.NIGHT_GUARD_ACTION:
            target_ids = {target.id for target in state.alive_players}
            include_self = True

        if target_ids is None:
            return []

        targets = []
        for target in state.alive_players:
            if target.id not in target_ids:
                continue
            if target.id == player.id and not include_self:
                continue
            targets.append({"id": target.id, "seat": target.seat, "name": target.name, "alive": target.alive})
        return targets
