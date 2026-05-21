from __future__ import annotations

from collections import Counter
from random import Random
from typing import Callable
from uuid import uuid4

from backend.agents.base import Agent
from backend.agents.characters import Character, Persona, PlayerMind, build_character, build_characters_for_roles
from backend.agents.heuristic import HeuristicAgent
from backend.engine.actions import ActionValidator
from backend.engine.models import (
    ActionType,
    Alignment,
    Decision,
    EventType,
    GameEvent,
    GameState,
    NightActions,
    Phase,
    Player,
    Role,
)
from backend.engine.phase_manager import PhaseManager
from backend.engine.rules import DEFAULT_ROLE_SET, build_players
from backend.engine.summary import build_day_summary
from backend.engine.visibility import Visibility


class WerewolfGame:
    """Runs a full local AI Werewolf game.

    The engine is intentionally stateful but narrow: phases mutate GameState,
    actions enter as Decision objects, and all observations flow through
    Visibility. This keeps rule changes and Agent swaps localized.
    """

    def __init__(
        self,
        *,
        players: list[Player] | None = None,
        agents: dict[str, Agent] | None = None,
        seed: int | None = None,
        max_days: int = 8,
        observer: Callable[[GameState], None] | None = None,
    ):
        self.rng = Random(seed)
        self.state = GameState(
            id=str(uuid4()),
            phase=Phase.SETUP,
            day=0,
            players=players or build_players(DEFAULT_ROLE_SET, seed=seed),
            max_days=max_days,
        )
        self.visibility = Visibility()
        self.validator = ActionValidator()
        self.observer = observer
        self.phase_manager = PhaseManager()
        self.pending_hunter_id: str | None = None
        # Build character assignments for human-like personas
        roles = [p.role for p in self.state.players]
        self.characters = build_characters_for_roles(roles, seed=seed or 0)
        self.agents = agents or {
            player.id: HeuristicAgent(
                player.id,
                seed=(seed or 0) + player.seat,
                character=self.characters.get(player.role.value),
            )
            for player in self.state.players
        }

    def initialize(self) -> None:
        self._log(
            EventType.GAME_START,
            "public",
            {
                "game_id": self.state.id,
                "players": [player.public_dict() for player in self.state.players],
                "role_count": len(self.state.players),
            },
        )
        for player in self.state.players:
            view = self.visibility.for_player(self.state, player.id)
            self.agents[player.id].initialize(view, {"max_days": self.state.max_days})
            self._log(
                EventType.PRIVATE_INFO,
                "private",
                {
                    "kind": "role_assignment",
                    "message": f"You are {player.name}, role={player.role.value}, alignment={player.alignment.value}.",
                },
                visible_to=[player.id],
            )
        self._check_win()

    def play(self) -> GameState:
        if not self.state.events:
            self.initialize()
        while self.state.winner is None and self.state.day < self.state.max_days:
            self.phase_manager.run(Phase.NIGHT_START, self)
            if self._check_win():
                break
            self.phase_manager.run(Phase.DAY_START, self)
            self._check_win()
        if self.state.winner is None:
            self.state.winner = Alignment.WOLF
            self._log(EventType.GAME_END, "public", {"winner": self.state.winner.value, "reason": "max_days_reached"})
        self._set_phase(Phase.GAME_END)
        for agent in self.agents.values():
            agent.finish(self.state.winner.value if self.state.winner else None)
        return self.state

    def _begin_night(self) -> None:
        self.state.day += 1
        self.state.votes = {}
        self.state.night_actions = NightActions(last_guard_target_id=self.state.night_actions.last_guard_target_id)
        self._set_phase(Phase.NIGHT_START)
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"Night {self.state.day} begins."})

    def _begin_day(self) -> None:
        self._set_phase(Phase.DAY_START)
        for agent in self.agents.values():
            agent.day_start()
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"Day {self.state.day} begins."})

    def _guard_phase(self) -> None:
        self._set_phase(Phase.NIGHT_GUARD_ACTION)
        guard = self._alive_role(Role.GUARD)
        if guard is None:
            return
        decision = self._ask(guard, "GUARD", lambda agent: agent.guard())
        if not self.validator.validate(self.state, decision):
            return
        if decision.target_id == self.state.night_actions.last_guard_target_id:
            self._log_decision(decision, "private", {"ignored": True, "reason": "guard_cannot_repeat"}, [guard.id])
            return
        self.state.night_actions.guard_target_id = decision.target_id
        self.state.night_actions.last_guard_target_id = decision.target_id
        self._log_decision(decision, "private", {"target_id": decision.target_id}, [guard.id])

    def _wolf_phase(self) -> None:
        self._set_phase(Phase.NIGHT_WOLF_ACTION)
        wolves = [player for player in self.state.alive_players if player.role == Role.WEREWOLF]
        if not wolves:
            return
        for wolf in wolves:
            decision = self._ask(wolf, "ATTACK", lambda agent: agent.attack())
            if self.validator.validate(self.state, decision):
                self.state.night_actions.wolf_votes[wolf.id] = decision.target_id or ""
                self._log_decision(decision, "private", {"target_id": decision.target_id}, [w.id for w in wolves])
        if self.state.night_actions.wolf_votes:
            self.state.night_actions.wolf_target_id = self._majority_target(self.state.night_actions.wolf_votes)

    def _witch_phase(self) -> None:
        self._set_phase(Phase.NIGHT_WITCH_ACTION)
        witch = self._alive_role(Role.WITCH)
        if witch is None:
            return
        victim_id = self.state.night_actions.wolf_target_id
        decisions = self._ask(witch, "WITCH", lambda agent: agent.witch_act(victim_id), many=True)
        for decision in decisions:
            if decision.action_type == ActionType.WITCH_SAVE:
                if self.state.abilities.witch_heal_used or decision.target_id != victim_id:
                    continue
                if self.validator.validate(self.state, decision):
                    self.state.abilities.witch_heal_used = True
                    self.state.night_actions.witch_save = True
                    self._log_decision(decision, "private", {"target_id": decision.target_id}, [witch.id])
            elif decision.action_type == ActionType.WITCH_POISON:
                if self.state.abilities.witch_poison_used:
                    continue
                if self.validator.validate(self.state, decision):
                    self.state.abilities.witch_poison_used = True
                    self.state.night_actions.witch_poison_target_id = decision.target_id
                    self._log_decision(decision, "private", {"target_id": decision.target_id}, [witch.id])
            elif decision.action_type == ActionType.SKIP:
                self._log_decision(decision, "private", {"skipped": True}, [witch.id])

    def _seer_phase(self) -> None:
        self._set_phase(Phase.NIGHT_SEER_ACTION)
        seer = self._alive_role(Role.SEER)
        if seer is None:
            return
        decision = self._ask(seer, "DIVINE", lambda agent: agent.divine())
        if not self.validator.validate(self.state, decision):
            return
        target = self.state.player(decision.target_id or "")
        result = {
            "kind": "seer_result",
            "target_id": target.id,
            "target_name": target.name,
            "is_wolf": target.alignment == Alignment.WOLF,
            "message": f"Seer check: {target.name} is {'wolf' if target.alignment == Alignment.WOLF else 'not wolf'}.",
        }
        self.state.night_actions.seer_target_id = target.id
        self.state.night_actions.seer_result = result
        self._log_decision(decision, "private", {"target_id": target.id}, [seer.id])
        self._log(EventType.PRIVATE_INFO, "private", result, visible_to=[seer.id])

    def _night_resolve(self) -> None:
        self._set_phase(Phase.NIGHT_RESOLVE)
        deaths: list[dict[str, str]] = []
        wolf_target_id = self.state.night_actions.wolf_target_id
        if wolf_target_id and not self.state.night_actions.witch_save and wolf_target_id != self.state.night_actions.guard_target_id:
            deaths.append({"player_id": wolf_target_id, "reason": "wolf"})
        poison_target_id = self.state.night_actions.witch_poison_target_id
        if poison_target_id:
            deaths.append({"player_id": poison_target_id, "reason": "poison"})

        unique_deaths = []
        seen: set[str] = set()
        for death in deaths:
            if death["player_id"] not in seen:
                unique_deaths.append(death)
                seen.add(death["player_id"])
        self.state.night_actions.deaths = unique_deaths
        for death in unique_deaths:
            self._kill(death["player_id"], death["reason"])
        if unique_deaths:
            names = [self.state.player(death["player_id"]).name for death in unique_deaths]
            self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"Night deaths: {', '.join(names)}."})
        else:
            self._log(EventType.SYSTEM_MESSAGE, "public", {"message": "No one died last night."})

    def _speech_phase(self) -> None:
        self._set_phase(Phase.DAY_SPEECH)
        for player in self.state.alive_players:
            decision = self._ask(player, "TALK", lambda agent: agent.talk())
            if not self.validator.validate(self.state, decision):
                continue
            self._log(
                EventType.CHAT_MESSAGE,
                "public",
                {
                    "actor_id": player.id,
                    "actor_name": player.name,
                    "speech": decision.speech or "",
                    "reasoning": decision.reasoning,
                },
            )

    def _vote_phase(self) -> None:
        self._set_phase(Phase.DAY_VOTE)
        for voter in self.state.alive_players:
            decision = self._ask(voter, "VOTE", lambda agent: agent.vote())
            if not self.validator.validate(self.state, decision):
                target = self._fallback_vote_target(voter)
                decision = Decision(voter.id, ActionType.VOTE, target_id=target.id, reasoning="Fallback legal vote.")
            self.state.votes[voter.id] = decision.target_id or ""
            target = self.state.player(decision.target_id or "")
            self._log(
                EventType.VOTE_CAST,
                "public",
                {
                    "voter_id": voter.id,
                    "voter_name": voter.name,
                    "target_id": target.id,
                    "target_name": target.name,
                    "reasoning": decision.reasoning,
                },
            )

    def _day_resolve(self) -> None:
        self._set_phase(Phase.DAY_RESOLVE)
        if not self.state.votes:
            return
        target_id = self._majority_target(self.state.votes)
        self._kill(target_id, "vote")
        target = self.state.player(target_id)
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"{target.name} was voted out."})
        if target.role == Role.HUNTER and self.state.abilities.hunter_can_shoot:
            self.pending_hunter_id = target.id
            self.phase_manager.run(Phase.HUNTER_SHOOT, self)
        self._refresh_day_summary()

    def _hunter_shoot_from_pending(self) -> None:
        if self.pending_hunter_id is None:
            return
        hunter = self.state.player(self.pending_hunter_id)
        self.pending_hunter_id = None
        if hunter.alive:
            return
        self._hunter_shoot(hunter)

    def _hunter_shoot(self, hunter: Player) -> None:
        self._set_phase(Phase.HUNTER_SHOOT)
        decision = self._ask(hunter, "SHOOT", lambda agent: agent.shoot())
        if not self.validator.validate(self.state, decision):
            return
        self._kill(decision.target_id or "", "hunter")
        target = self.state.player(decision.target_id or "")
        self._log(
            EventType.HUNTER_SHOT,
            "public",
            {
                "hunter_id": hunter.id,
                "hunter_name": hunter.name,
                "target_id": target.id,
                "target_name": target.name,
                "reasoning": decision.reasoning,
            },
        )
        self._refresh_day_summary()

    def _ask(self, player: Player, request: str, call, *, many: bool = False):
        view = self.visibility.for_player(self.state, player.id)
        agent = self.agents[player.id]
        agent.update(view, request)
        result = call(agent)
        return result if many else result

    def _kill(self, player_id: str, reason: str) -> None:
        player = self.state.player(player_id)
        if not player.alive:
            return
        player.alive = False
        if player.role == Role.HUNTER and reason == "poison":
            self.state.abilities.hunter_can_shoot = False
        self._log(
            EventType.PLAYER_DIED,
            "public",
            {
                "player_id": player.id,
                "player_name": player.name,
                "reason": reason,
            },
        )

    def _check_win(self) -> bool:
        alive_wolves = [player for player in self.state.alive_players if player.alignment == Alignment.WOLF]
        alive_village = [player for player in self.state.alive_players if player.alignment == Alignment.VILLAGE]
        winner: Alignment | None = None
        reason = ""
        if not alive_wolves:
            winner = Alignment.VILLAGE
            reason = "all_wolves_dead"
        elif len(alive_wolves) >= len(alive_village):
            winner = Alignment.WOLF
            reason = "wolves_reached_parity"
        if winner:
            self.state.winner = winner
            self._log(EventType.GAME_END, "public", {"winner": winner.value, "reason": reason})
            return True
        return False

    def _alive_role(self, role: Role) -> Player | None:
        return next((player for player in self.state.alive_players if player.role == role), None)

    def _fallback_vote_target(self, voter: Player) -> Player:
        return next(player for player in self.state.alive_players if player.id != voter.id)

    def _majority_target(self, votes: dict[str, str]) -> str:
        counts = Counter(votes.values())
        max_votes = max(counts.values())
        tied = sorted(target_id for target_id, count in counts.items() if count == max_votes)
        return tied[0]

    def _set_phase(self, phase: Phase) -> None:
        self.state.phase = phase
        self._log(EventType.PHASE_CHANGED, "public", {"phase": phase.value})

    def _log_decision(
        self,
        decision: Decision,
        visibility: str,
        payload: dict,
        visible_to: list[str] | None = None,
    ) -> None:
        actor = self.state.player(decision.actor_id)
        target = self.state.player(decision.target_id).public_dict() if decision.target_id else None
        full_payload = {
            "actor_id": actor.id,
            "actor_name": actor.name,
            "action_type": decision.action_type.value,
            "target": target,
            "reasoning": decision.reasoning,
            **payload,
        }
        self._log(EventType.NIGHT_ACTION, visibility, full_payload, visible_to=visible_to)

    def _log(
        self,
        type: EventType,
        visibility: str,
        payload: dict,
        *,
        visible_to: list[str] | None = None,
    ) -> None:
        self.state.events.append(
            GameEvent.create(
                day=self.state.day,
                phase=self.state.phase,
                type=type,
                visibility=visibility,
                payload=payload,
                visible_to=visible_to,
            )
        )
        if self.observer is not None:
            self.observer(self.state)

    def _refresh_day_summary(self) -> None:
        if self.state.day <= 0:
            return
        bullets, facts = build_day_summary(self.state.events, self.state.day)
        self.state.daily_summaries[self.state.day] = bullets
        self.state.daily_summary_facts[self.state.day] = facts
