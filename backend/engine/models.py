from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any
from uuid import uuid4


class Alignment(str, Enum):
    VILLAGE = "village"
    WOLF = "wolf"


class Role(str, Enum):
    VILLAGER = "Villager"
    WEREWOLF = "Werewolf"
    SEER = "Seer"
    WITCH = "Witch"
    HUNTER = "Hunter"
    GUARD = "Guard"


class Phase(str, Enum):
    SETUP = "SETUP"
    NIGHT_START = "NIGHT_START"
    NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION"
    NIGHT_WOLF_ACTION = "NIGHT_WOLF_ACTION"
    NIGHT_WITCH_ACTION = "NIGHT_WITCH_ACTION"
    NIGHT_SEER_ACTION = "NIGHT_SEER_ACTION"
    NIGHT_RESOLVE = "NIGHT_RESOLVE"
    DAY_START = "DAY_START"
    DAY_SPEECH = "DAY_SPEECH"
    DAY_VOTE = "DAY_VOTE"
    DAY_RESOLVE = "DAY_RESOLVE"
    HUNTER_SHOOT = "HUNTER_SHOOT"
    GAME_END = "GAME_END"


class ActionType(str, Enum):
    TALK = "talk"
    VOTE = "vote"
    ATTACK = "attack"
    DIVINE = "divine"
    GUARD = "guard"
    WITCH_SAVE = "witch_save"
    WITCH_POISON = "witch_poison"
    SHOOT = "shoot"
    SKIP = "skip"


class EventType(str, Enum):
    GAME_START = "GAME_START"
    PHASE_CHANGED = "PHASE_CHANGED"
    PRIVATE_INFO = "PRIVATE_INFO"
    CHAT_MESSAGE = "CHAT_MESSAGE"
    NIGHT_ACTION = "NIGHT_ACTION"
    VOTE_CAST = "VOTE_CAST"
    PLAYER_DIED = "PLAYER_DIED"
    HUNTER_SHOT = "HUNTER_SHOT"
    SYSTEM_MESSAGE = "SYSTEM_MESSAGE"
    GAME_END = "GAME_END"


@dataclass
class Player:
    id: str
    seat: int
    name: str
    role: Role
    alignment: Alignment
    alive: bool = True
    is_ai: bool = True

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seat": self.seat,
            "name": self.name,
            "alive": self.alive,
            "is_ai": self.is_ai,
        }

    def private_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data.update({"role": self.role.value, "alignment": self.alignment.value})
        return data


@dataclass
class Decision:
    actor_id: str
    action_type: ActionType
    target_id: str | None = None
    speech: str | None = None
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GameEvent:
    id: str
    ts: float
    day: int
    phase: Phase
    type: EventType
    visibility: str
    payload: dict[str, Any]
    visible_to: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        day: int,
        phase: Phase,
        type: EventType,
        visibility: str,
        payload: dict[str, Any],
        visible_to: list[str] | None = None,
    ) -> "GameEvent":
        return cls(
            id=str(uuid4()),
            ts=time(),
            day=day,
            phase=phase,
            type=type,
            visibility=visibility,
            payload=payload,
            visible_to=visible_to or [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "day": self.day,
            "phase": self.phase.value,
            "type": self.type.value,
            "visibility": self.visibility,
            "visible_to": self.visible_to,
            "payload": self.payload,
        }


@dataclass
class RoleAbilities:
    witch_heal_used: bool = False
    witch_poison_used: bool = False
    hunter_can_shoot: bool = True


@dataclass
class NightActions:
    guard_target_id: str | None = None
    last_guard_target_id: str | None = None
    wolf_votes: dict[str, str] = field(default_factory=dict)
    wolf_target_id: str | None = None
    witch_save: bool = False
    witch_poison_target_id: str | None = None
    seer_target_id: str | None = None
    seer_result: dict[str, Any] | None = None
    deaths: list[dict[str, str]] = field(default_factory=list)


@dataclass
class GameState:
    id: str
    phase: Phase
    day: int
    players: list[Player]
    events: list[GameEvent] = field(default_factory=list)
    votes: dict[str, str] = field(default_factory=dict)
    night_actions: NightActions = field(default_factory=NightActions)
    abilities: RoleAbilities = field(default_factory=RoleAbilities)
    winner: Alignment | None = None
    max_days: int = 8

    @property
    def alive_players(self) -> list[Player]:
        return [player for player in self.players if player.alive]

    def player(self, player_id: str) -> Player:
        for player in self.players:
            if player.id == player_id:
                return player
        raise KeyError(f"Unknown player id: {player_id}")

    def role_player(self, role: Role) -> Player | None:
        return next((player for player in self.players if player.role == role), None)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase.value,
            "day": self.day,
            "players": [player.public_dict() for player in self.players],
            "events": [event.to_dict() for event in self.events if event.visibility == "public"],
            "votes": dict(self.votes),
            "winner": self.winner.value if self.winner else None,
        }

    def moderator_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data["players"] = [player.private_dict() for player in self.players]
        data["events"] = [event.to_dict() for event in self.events]
        data["night_actions"] = {
            "guard_target_id": self.night_actions.guard_target_id,
            "last_guard_target_id": self.night_actions.last_guard_target_id,
            "wolf_votes": dict(self.night_actions.wolf_votes),
            "wolf_target_id": self.night_actions.wolf_target_id,
            "witch_save": self.night_actions.witch_save,
            "witch_poison_target_id": self.night_actions.witch_poison_target_id,
            "seer_target_id": self.night_actions.seer_target_id,
            "seer_result": self.night_actions.seer_result,
            "deaths": list(self.night_actions.deaths),
        }
        return data
