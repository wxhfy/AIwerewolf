from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
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
    WHITE_WOLF_KING = "WhiteWolfKing"
    SEER = "Seer"
    WITCH = "Witch"
    HUNTER = "Hunter"
    GUARD = "Guard"
    IDIOT = "Idiot"
    # Template roles (playable=False in the registry — present so the registry,
    # LLM prompts and frontend i18n have entries, but excluded from the locked
    # 7–12P configs. Engine wiring (night actions, lover deaths, "all gods
    # dead" triggers, etc.) is a follow-up per role.
    CUPID = "Cupid"
    BIG_BAD_WOLF = "BigBadWolf"
    WOLF_CUB = "WolfCub"
    WOLF_KING = "WolfKing"
    KNIGHT = "Knight"
    ELDER = "Elder"


class Phase(str, Enum):
    SETUP = "SETUP"
    NIGHT_START = "NIGHT_START"
    NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION"
    NIGHT_WOLF_ACTION = "NIGHT_WOLF_ACTION"
    NIGHT_WITCH_ACTION = "NIGHT_WITCH_ACTION"
    NIGHT_SEER_ACTION = "NIGHT_SEER_ACTION"
    NIGHT_RESOLVE = "NIGHT_RESOLVE"
    DAY_START = "DAY_START"
    DAY_BADGE_SIGNUP = "DAY_BADGE_SIGNUP"
    DAY_BADGE_SPEECH = "DAY_BADGE_SPEECH"
    DAY_BADGE_ELECTION = "DAY_BADGE_ELECTION"
    DAY_PK_SPEECH = "DAY_PK_SPEECH"
    DAY_LAST_WORDS = "DAY_LAST_WORDS"
    DAY_SPEECH = "DAY_SPEECH"
    DAY_SHERIFF_CLOSING = "DAY_SHERIFF_CLOSING"
    DAY_VOTE = "DAY_VOTE"
    DAY_RESOLVE = "DAY_RESOLVE"
    BADGE_TRANSFER = "BADGE_TRANSFER"
    HUNTER_SHOOT = "HUNTER_SHOOT"
    WHITE_WOLF_KING_BOOM = "WHITE_WOLF_KING_BOOM"
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
    BOOM = "boom"
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
    WHITE_WOLF_KING_BOOM = "WHITE_WOLF_KING_BOOM"
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
    agent_type: str = "llm"
    model_name: str = ""
    prompt_version: str = "v1"
    persona: dict[str, Any] = field(default_factory=dict)
    death_day: int | None = None
    death_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seat": self.seat,
            "name": self.name,
            "alive": self.alive,
            "is_ai": self.is_ai,
            "agent_type": self.agent_type,
            "persona": {
                "style_label": self.persona.get("style_label"),
                "mbti": self.persona.get("mbti"),
            }
            if self.persona
            else None,
        }

    def private_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data.update({"role": self.role.value, "alignment": self.alignment.value, "persona": self.persona or None})
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
class DecisionAudit:
    id: str
    game_id: str
    player_id: str
    day: int
    phase: str
    request: str
    observation: dict[str, Any]
    legal_actions: list[str]
    prompt_version: str | None
    raw_output: str | None
    parsed_action: dict[str, Any]
    is_valid: bool
    error_type: str | None
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: float
    # v2 DecisionTrace fields (populated when LLM decisions are recorded)
    visible_facts: list[str] = field(default_factory=list)
    candidate_actions: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    prompt_hash: str | None = None
    cost_usd: float | None = None
    model_name: str | None = None
    provider: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingInput:
    player_id: str
    player_name: str
    seat: int
    request: str
    phase: str
    action_type: str
    prompt: str
    options: list[dict[str, Any]] = field(default_factory=list)
    can_skip: bool = False
    placeholder: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "seat": self.seat,
            "request": self.request,
            "phase": self.phase,
            "action_type": self.action_type,
            "prompt": self.prompt,
            "options": list(self.options),
            "can_skip": self.can_skip,
            "placeholder": self.placeholder,
        }


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
    ) -> GameEvent:
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
    idiot_revealed: bool = False
    white_wolf_king_boom_used: bool = False


@dataclass
class BadgeState:
    holder_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    signup: dict[str, bool] = field(default_factory=dict)
    votes: dict[str, str] = field(default_factory=dict)
    history: dict[int, dict[str, str]] = field(default_factory=dict)
    revote_count: int = 0


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
    decision_records: list[DecisionAudit] = field(default_factory=list)
    votes: dict[str, str] = field(default_factory=dict)
    vote_history: dict[int, dict[str, str]] = field(default_factory=dict)
    day_history: dict[int, dict[str, Any]] = field(default_factory=dict)
    badge: BadgeState = field(default_factory=BadgeState)
    night_actions: NightActions = field(default_factory=NightActions)
    abilities: RoleAbilities = field(default_factory=RoleAbilities)
    current_speaker_id: str | None = None
    pk_targets: list[str] = field(default_factory=list)
    pk_source: str | None = None
    pending_input: PendingInput | None = None
    phase_cursor: dict[str, Any] = field(default_factory=dict)
    daily_summaries: dict[int, list[str]] = field(default_factory=dict)
    daily_summary_facts: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    phase_done: dict[int, list[str]] = field(default_factory=dict)
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
            "vote_history": dict(self.vote_history),
            "day_history": dict(self.day_history),
            "badge": {
                "holder_id": self.badge.holder_id,
                "candidates": list(self.badge.candidates),
                "signup": dict(self.badge.signup),
                "votes": dict(self.badge.votes),
                "history": dict(self.badge.history),
                "revote_count": self.badge.revote_count,
            },
            "daily_summaries": dict(self.daily_summaries),
            "daily_summary_facts": dict(self.daily_summary_facts),
            "role_abilities": {
                "witch_heal_used": self.abilities.witch_heal_used,
                "witch_poison_used": self.abilities.witch_poison_used,
                "hunter_can_shoot": self.abilities.hunter_can_shoot,
                "idiot_revealed": self.abilities.idiot_revealed,
                "white_wolf_king_boom_used": self.abilities.white_wolf_king_boom_used,
            },
            "current_speaker_id": self.current_speaker_id,
            "pk_targets": list(self.pk_targets),
            "pk_source": self.pk_source,
            "pending_input": self.pending_input.to_dict() if self.pending_input else None,
            "winner": self.winner.value if self.winner else None,
        }

    def snapshot(self, *, show_private: bool = False) -> dict[str, Any]:
        data = self.moderator_dict() if show_private else self.public_dict()
        data["alive_count"] = sum(1 for player in self.players if player.alive)
        data["event_count"] = len(data["events"])
        if data["events"]:
            data["last_event"] = data["events"][-1]
        else:
            data["last_event"] = None
        return data

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
        data["phase_cursor"] = dict(self.phase_cursor)
        return data
