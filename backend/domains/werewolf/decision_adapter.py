from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from backend.agent_harness.contracts import ActionOption
from backend.agent_harness.contracts import ActionSpace
from backend.agent_harness.contracts import ActorRef
from backend.agent_harness.contracts import DecisionPoint
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessBudget
from backend.agent_harness.contracts import HarnessResult
from backend.agent_harness.contracts import InformationState
from backend.agent_harness.contracts import MemoryScope
from backend.engine.models import ActionType
from backend.engine.models import Decision
from backend.engine.models import GameState
from backend.engine.models import Player
from backend.engine.visibility import PlayerView

_SPEECH_REQUESTS = {"TALK", "BADGE_SPEECH", "PK_SPEECH", "SHERIFF_CLOSING", "LAST_WORDS"}
_TARGET_ACTIONS = {
    "BADGE_ELECTION": ActionType.VOTE,
    "VOTE": ActionType.VOTE,
    "GUARD": ActionType.GUARD,
    "WOLF_TEAM_VOTE": ActionType.ATTACK,
    "DIVINE": ActionType.DIVINE,
    "SHOOT": ActionType.SHOOT,
    "BOOM": ActionType.BOOM,
    "TRANSFER_BADGE": ActionType.VOTE,
}
_DELIBERATIVE_REQUESTS = {"WITCH", "SHOOT", "BOOM", "TRANSFER_BADGE"}
_REASONING_EVENT_TYPES = {
    "CHAT_MESSAGE",
    "VOTE_CAST",
    "PLAYER_DIED",
    "PRIVATE_INFO",
    "HUNTER_SHOT",
    "WHITE_WOLF_KING_BOOM",
    "GAME_END",
}


class WerewolfDecisionAdapter:
    """Translate role-safe engine views into portable harness contracts."""

    environment_id = "werewolf"

    def build_request(
        self,
        state: GameState,
        player: Player,
        view: PlayerView,
        request_kind: str,
        *,
        agent_definition_id: str,
        agent_profile: dict[str, Any] | None = None,
        simultaneous_group_id: str | None = None,
        deadline_ms: int = 30_000,
    ) -> DecisionRequest:
        options = self._action_options(state, player, view, request_kind)
        profile = dict(agent_profile or {})
        strategy_bias = profile.pop("strategy_bias", None)
        strategy_version = profile.pop("strategy_version", None)
        knowledge_context = ()
        if strategy_bias:
            knowledge_context = (
                {
                    "scope": "cross_episode",
                    "source": "track_c",
                    "version": str(strategy_version or "unversioned"),
                    "content": strategy_bias,
                },
            )
        observation = {
            "player_id": view.player_id,
            "day": view.day,
            "phase": view.phase,
            "self_player": self._compact_player(view.self_player, include_private=True),
            "players": [self._compact_player(item) for item in view.players],
            "known_wolves": [self._compact_player(item, include_private=True) for item in view.known_wolves],
            "observations": view.observations,
            "legal_targets": view.legal_targets,
        }
        sequence = len(state.decision_records) + 1
        return DecisionRequest(
            request_id=f"{state.id}:{sequence}:{uuid4().hex[:8]}",
            environment_id=self.environment_id,
            episode_id=state.id,
            actor=ActorRef(actor_id=player.id, agent_definition_id=agent_definition_id),
            decision_point=DecisionPoint(
                kind=f"werewolf.{request_kind.lower()}",
                sequence=sequence,
                simultaneous_group_id=simultaneous_group_id,
            ),
            information_state=InformationState(
                schema_id="werewolf.player-view",
                schema_version="1",
                observation=observation,
                visible_history=tuple(
                    self._compact_event(event)
                    for event in (*view.public_events, *view.private_events)
                    if str(event.get("type") or "") in _REASONING_EVENT_TYPES
                ),
            ),
            action_space=ActionSpace(options=tuple(options)),
            memory_scope=MemoryScope(namespace="match", episode_id=state.id, actor_id=player.id),
            knowledge_context=knowledge_context,
            policy_tags=frozenset({"role-safe-view", "environment-owned-actions"}),
            agent_profile=profile,
            domain_metadata={
                "request_kind": request_kind,
                "role": player.role.value,
                "alignment": player.alignment.value,
                "day": state.day,
                "phase": state.phase.value,
            },
            budget=HarnessBudget(
                max_steps=2 if request_kind in _DELIBERATIVE_REQUESTS else 1,
                max_tool_calls=0,
                max_skill_loads=0,
                max_output_tokens=self._output_token_budget(request_kind, len(options)),
                deadline_ms=deadline_ms,
            ),
        )

    @staticmethod
    def _compact_player(player: dict[str, Any], *, include_private: bool = False) -> dict[str, Any]:
        compact = {
            key: player[key]
            for key in ("id", "seat", "name", "alive")
            if key in player
        }
        persona = dict(player.get("persona") or {})
        if persona:
            compact["persona"] = {
                key: persona[key]
                for key in ("style_label", "mbti")
                if persona.get(key)
            }
        if include_private:
            for key in ("role", "alignment"):
                if key in player:
                    compact[key] = player[key]
        return compact

    @staticmethod
    def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event.get("payload") or {})
        allowed_payload = {
            key: payload[key]
            for key in (
                "actor_id",
                "actor_name",
                "speaker_id",
                "speaker_name",
                "voter_id",
                "voter_name",
                "target_id",
                "target_name",
                "player_id",
                "player_name",
                "speech",
                "message",
                "reason",
                "kind",
                "is_wolf",
            )
            if key in payload
        }
        return {
            "id": event.get("id"),
            "seq": event.get("seq"),
            "day": event.get("day"),
            "phase": event.get("phase"),
            "type": event.get("type"),
            "visibility": event.get("visibility"),
            "payload": allowed_payload,
        }

    @staticmethod
    def _output_token_budget(request_kind: str, option_count: int) -> int:
        if request_kind in _SPEECH_REQUESTS:
            return min(560, 360 + option_count * 12)
        if request_kind in _DELIBERATIVE_REQUESTS:
            return min(360, 220 + option_count * 12)
        return min(280, 140 + option_count * 10)

    def to_engine_decisions(
        self,
        player: Player,
        request: DecisionRequest,
        result: HarnessResult,
    ) -> list[Decision]:
        if result.status != "completed" or result.action is None:
            raise RuntimeError(f"Agent harness failed for {request.request_id}: {result.error or result.status}")
        action = result.action
        metadata = {
            "source": "agent_harness",
            "model_backed": bool(action.metadata.get("model") or action.metadata.get("provider")),
            "harness_request_id": request.request_id,
            "harness_option_id": action.option_id,
            "harness_events": [event.to_record() for event in result.events],
            "candidate_actions": [
                {"option_id": option.option_id, **option.parameters} for option in request.action_space.options
            ],
            **action.metadata,
        }
        reasoning = action.reasoning

        if action.action_type == "talk":
            return [
                Decision(
                    player.id,
                    ActionType.TALK,
                    speech=str(action.response.get("speech") or "").strip(),
                    reasoning=reasoning,
                    metadata=metadata,
                )
            ]
        if action.action_type == "witch_hold":
            return [Decision(player.id, ActionType.SKIP, reasoning=reasoning, metadata=metadata)]
        if action.action_type == "witch_save":
            return [
                Decision(
                    player.id,
                    ActionType.WITCH_SAVE,
                    target_id=str(action.parameters["target_id"]),
                    reasoning=reasoning,
                    metadata=metadata,
                )
            ]
        if action.action_type == "witch_poison":
            return [
                Decision(
                    player.id,
                    ActionType.WITCH_POISON,
                    target_id=str(action.parameters["target_id"]),
                    reasoning=reasoning,
                    metadata=metadata,
                )
            ]
        if action.action_type == "witch_save_and_poison":
            return [
                Decision(
                    player.id,
                    ActionType.WITCH_SAVE,
                    target_id=str(action.parameters["save_target_id"]),
                    reasoning=reasoning,
                    metadata=metadata,
                ),
                Decision(
                    player.id,
                    ActionType.WITCH_POISON,
                    target_id=str(action.parameters["poison_target_id"]),
                    reasoning=reasoning,
                    metadata=metadata,
                ),
            ]
        if action.action_type == ActionType.SKIP.value:
            return [Decision(player.id, ActionType.SKIP, reasoning=reasoning, metadata=metadata)]
        return [
            Decision(
                player.id,
                ActionType(action.action_type),
                target_id=str(action.parameters.get("target_id") or "") or None,
                reasoning=reasoning,
                metadata=metadata,
            )
        ]

    def _action_options(
        self,
        state: GameState,
        player: Player,
        view: PlayerView,
        request_kind: str,
    ) -> list[ActionOption]:
        if request_kind in _SPEECH_REQUESTS:
            return [
                ActionOption(
                    option_id="talk",
                    action_type="talk",
                    response_schema={
                        "type": "object",
                        "properties": {"speech": {"type": "string", "minLength": 1, "maxLength": 2000}},
                        "required": ["speech"],
                        "additionalProperties": False,
                    },
                    model_hint="Speak only from the supplied actor-visible information.",
                )
            ]
        if request_kind == "WITCH":
            return self._witch_options(state, player)
        action_type = _TARGET_ACTIONS.get(request_kind)
        if action_type is None:
            raise ValueError(f"Unsupported werewolf decision request: {request_kind}")
        options = [
            ActionOption(
                option_id=f"{action_type.value}:{target_id}",
                action_type=action_type.value,
                parameters={"target_id": target_id},
            )
            for target_id in self._target_ids(state, player, view, request_kind)
        ]
        if request_kind in {"BOOM", "TRANSFER_BADGE"}:
            options.append(ActionOption(option_id="skip", action_type=ActionType.SKIP.value))
        if not options:
            options.append(ActionOption(option_id="skip", action_type=ActionType.SKIP.value))
        return options

    @staticmethod
    def _target_ids(state: GameState, player: Player, view: PlayerView, request_kind: str) -> list[str]:
        if request_kind == "BADGE_ELECTION":
            allowed = set(state.badge.candidates)
        elif request_kind == "VOTE" and state.pk_targets:
            allowed = set(state.pk_targets)
        elif request_kind == "TRANSFER_BADGE":
            allowed = {target.id for target in state.alive_players if target.id != player.id}
        else:
            allowed = {str(target["id"]) for target in view.legal_targets}
        if request_kind == "GUARD" and state.night_actions.last_guard_target_id:
            allowed.discard(state.night_actions.last_guard_target_id)
        return [target.id for target in state.alive_players if target.id in allowed]

    @staticmethod
    def _witch_options(state: GameState, player: Player) -> list[ActionOption]:
        options = [ActionOption(option_id="witch:hold", action_type="witch_hold")]
        victim_id = state.night_actions.wolf_target_id
        can_save = bool(victim_id and not state.abilities.witch_heal_used)
        poison_targets = [
            target.id
            for target in state.alive_players
            if target.id != player.id and not state.abilities.witch_poison_used
        ]
        if can_save:
            options.append(
                ActionOption(
                    option_id=f"witch:save:{victim_id}",
                    action_type="witch_save",
                    parameters={"target_id": victim_id},
                )
            )
        for target_id in poison_targets:
            options.append(
                ActionOption(
                    option_id=f"witch:poison:{target_id}",
                    action_type="witch_poison",
                    parameters={"target_id": target_id},
                )
            )
            if can_save:
                options.append(
                    ActionOption(
                        option_id=f"witch:save:{victim_id}:poison:{target_id}",
                        action_type="witch_save_and_poison",
                        parameters={"save_target_id": victim_id, "poison_target_id": target_id},
                    )
                )
        return options

    @staticmethod
    def view_record(view: PlayerView) -> dict[str, Any]:
        return asdict(view)
