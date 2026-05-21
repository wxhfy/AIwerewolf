from __future__ import annotations

from collections import Counter
from random import Random
from typing import Callable
from uuid import uuid4

from backend.agents.base import Agent
from backend.agents.characters import Character, build_character_roster
from backend.agents.factory import create_agents
from backend.engine.actions import ActionValidator
from backend.engine.models import (
    ActionType,
    Alignment,
    Decision,
    DecisionAudit,
    EventType,
    GameEvent,
    GameState,
    NightActions,
    PendingInput,
    Phase,
    Player,
    Role,
)
from backend.engine.phase_manager import PhaseManager
from backend.engine.rules import DEFAULT_ROLE_SET, build_players
from backend.engine.summary import build_day_summary
from backend.engine.visibility import Visibility


def _phase_already_past(current: Phase, target: Phase) -> bool:
    """Legacy helper — see _phase_done in WerewolfGame for the resume guard.

    Retained because earlier guards reference it; the per-day completion set is
    the source of truth for resume-after-human-pause behaviour.
    """
    _ORDER = {
        Phase.SETUP: 0,
        Phase.NIGHT_START: 1,
        Phase.NIGHT_GUARD_ACTION: 2,
        Phase.NIGHT_WOLF_ACTION: 3,
        Phase.NIGHT_WITCH_ACTION: 4,
        Phase.NIGHT_SEER_ACTION: 5,
        Phase.NIGHT_RESOLVE: 6,
        Phase.DAY_START: 7,
        Phase.DAY_BADGE_SIGNUP: 8,
        Phase.DAY_BADGE_SPEECH: 9,
        Phase.DAY_BADGE_ELECTION: 10,
        Phase.DAY_PK_SPEECH: 11,
        Phase.DAY_SPEECH: 12,
        Phase.DAY_VOTE: 13,
        Phase.DAY_LAST_WORDS: 14,
        Phase.DAY_RESOLVE: 15,
        Phase.BADGE_TRANSFER: 16,
        Phase.HUNTER_SHOOT: 17,
        Phase.WHITE_WOLF_KING_BOOM: 18,
        Phase.GAME_END: 19,
    }
    return _ORDER.get(current, 0) > _ORDER.get(target, 0)


class GamePaused(RuntimeError):
    pass


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
        self.pending_badge_transfer_from_id: str | None = None
        self.human_action_buffer: dict[str, list[Decision]] = {}
        self.interrupt_phase_cycle = False
        self.characters = build_character_roster(self.state.players, seed=seed or 0)
        self.agents = {}
        self.attach_agents(
            agents or create_agents(
                self.state.players,
                {
                    "type": "heuristic",
                    "seed": seed or 0,
                    "temperature": 0.4,
                    "character_map": self.characters,
                },
            )
        )

    def attach_agents(self, agents: dict[str, Agent]) -> None:
        self.agents = agents
        for player in self.state.players:
            char = self.characters.get(player.id)
            if char is not None and hasattr(self.agents[player.id], "character"):
                self.agents[player.id].character = char
            if char is not None:
                player.persona = {
                    "name": char.persona.name,
                    "mbti": char.persona.mbti,
                    "basic_info": char.persona.basic_info,
                    "style_label": char.persona.style_label,
                    "reasoning_style": char.persona.reasoning_style,
                    "speech_length_habit": char.persona.speech_length_habit,
                    "vocabulary_style": char.persona.vocabulary_style,
                }

    # ------------------------------------------------------------------
    # Resume safety helpers
    # ------------------------------------------------------------------

    def _phase_done(self, phase: Phase) -> bool:
        """True if `phase` has already been processed for the current day.

        Per-day tracking lets re-vote / re-resolve loops (the PK tie-break path)
        clear specific completion flags and re-run the relevant handlers without
        interfering with the resume-after-human-pause skip logic.
        """
        return phase.value in self.state.phase_done.get(self.state.day, [])

    def _mark_phase_done(self, phase: Phase) -> None:
        bucket = self.state.phase_done.setdefault(self.state.day, [])
        if phase.value not in bucket:
            bucket.append(phase.value)

    def _clear_phase_done(self, *phases: Phase) -> None:
        bucket = self.state.phase_done.get(self.state.day)
        if not bucket:
            return
        for phase in phases:
            if phase.value in bucket:
                bucket.remove(phase.value)

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
        while self.state.winner is None:
            self.play_until_blocked()
            if self.state.pending_input is not None:
                raise RuntimeError("Human input required; use play_until_blocked/submit_human_action for mixed games.")
        return self.state

    def play_until_blocked(self) -> GameState:
        if not self.state.events:
            self.initialize()
            try:
                from backend.db.persist import save_game_start
                save_game_start(self.state)
            except Exception:
                pass
        self.state.pending_input = None
        self.interrupt_phase_cycle = False
        try:
            while self.state.winner is None and self.state.day < self.state.max_days:
                if self.state.phase in {Phase.SETUP, Phase.DAY_RESOLVE, Phase.BADGE_TRANSFER, Phase.HUNTER_SHOOT, Phase.WHITE_WOLF_KING_BOOM, Phase.GAME_END}:
                    self.phase_manager.run(Phase.NIGHT_START, self)
                elif self.state.phase == Phase.NIGHT_RESOLVE:
                    if self._check_win():
                        break
                    self.phase_manager.run(Phase.DAY_START, self)
                elif self.state.phase in {
                    Phase.NIGHT_START,
                    Phase.NIGHT_GUARD_ACTION,
                    Phase.NIGHT_WOLF_ACTION,
                    Phase.NIGHT_WITCH_ACTION,
                    Phase.NIGHT_SEER_ACTION,
                }:
                    self.phase_manager.run(Phase.NIGHT_START, self)
                else:
                    self.phase_manager.run(Phase.DAY_START, self)
                if self.state.pending_input is not None or self._check_win():
                    break
        except GamePaused:
            return self.state
        if self.state.winner is None and self.state.day >= self.state.max_days:
            self.state.winner = Alignment.WOLF
            self._log(EventType.GAME_END, "public", {"winner": self.state.winner.value, "reason": "max_days_reached"})
        if self.state.winner is not None:
            self._set_phase(Phase.GAME_END)
            for agent in self.agents.values():
                agent.finish(self.state.winner.value if self.state.winner else None)
            try:
                from backend.db.persist import save_game_end
                save_game_end(self.state)
            except Exception:
                pass
        return self.state

    def submit_human_action(self, payload: dict[str, object]) -> GameState:
        pending = self.state.pending_input
        if pending is None:
            raise ValueError("No human input is pending.")
        player = self.state.player(pending.player_id)
        decisions = self._coerce_human_decisions(player, pending, payload)
        self.human_action_buffer[player.id] = decisions
        self.state.pending_input = None
        return self.play_until_blocked()

    def _begin_night(self) -> None:
        # Resume safety: night already initialized for the next day → skip.
        # _begin_night increments state.day, so the completion flag lives on day+1.
        next_day = self.state.day + 1
        if Phase.NIGHT_START.value in self.state.phase_done.get(next_day, []):
            return
        self.state.day = next_day
        self.state.votes = {}
        self.state.pk_targets = []
        self.state.pk_source = None
        self.state.night_actions = NightActions(last_guard_target_id=self.state.night_actions.last_guard_target_id)
        self.state.current_speaker_id = None
        self.state.phase_cursor = {}
        self._set_phase(Phase.NIGHT_START)
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"Night {self.state.day} begins."})
        self._mark_phase_done(Phase.NIGHT_START)

    def _begin_day(self) -> None:
        # Resume safety: day already initialized for this day → skip.
        if self._phase_done(Phase.DAY_START):
            return
        self.state.current_speaker_id = None
        self.state.phase_cursor = {}
        self.state.votes = {}
        self.interrupt_phase_cycle = False
        self._set_phase(Phase.DAY_START)
        for agent in self.agents.values():
            agent.day_start()
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"Day {self.state.day} begins."})
        self._mark_phase_done(Phase.DAY_START)

    def _badge_signup_phase(self) -> None:
        if self._phase_done(Phase.DAY_BADGE_SIGNUP):
            return
        self._set_phase(Phase.DAY_BADGE_SIGNUP)
        if self.state.day != 1 or self.state.badge.holder_id is not None:
            self._mark_phase_done(Phase.DAY_BADGE_SIGNUP)
            return
        alive = list(self.state.alive_players)
        if len(alive) <= 2:
            self._mark_phase_done(Phase.DAY_BADGE_SIGNUP)
            return
        candidates = self._pick_badge_candidates(alive)
        self.state.badge.candidates = [player.id for player in candidates]
        self.state.badge.signup = {player.id: True for player in candidates}
        candidate_names = [player.name for player in candidates]
        self._log(
            EventType.SYSTEM_MESSAGE,
            "public",
            {"message": f"Badge signup opens. Candidates: {', '.join(candidate_names)}."},
        )
        self._mark_phase_done(Phase.DAY_BADGE_SIGNUP)

    def _badge_speech_phase(self) -> None:
        if self._phase_done(Phase.DAY_BADGE_SPEECH):
            return
        self._set_phase(Phase.DAY_BADGE_SPEECH)
        if not self.state.badge.candidates:
            self._mark_phase_done(Phase.DAY_BADGE_SPEECH)
            return
        candidates = [self.state.player(candidate_id) for candidate_id in self.state.badge.candidates]

        def handle(player: Player) -> None:
            if not player.alive:
                return
            decision = self._ask(player, "BADGE_SPEECH", lambda agent: agent.talk())
            if not self.validator.validate(self.state, decision):
                return
            self._log(
                EventType.CHAT_MESSAGE,
                "public",
                {
                    "actor_id": player.id,
                    "actor_name": player.name,
                    "speech": decision.speech or "",
                    "reasoning": decision.reasoning,
                    "agent_source": decision.metadata.get("source"),
                    "agent_model": decision.metadata.get("model"),
                    "agent_provider": decision.metadata.get("provider"),
                    "agent_fallback": bool(decision.metadata.get("fallback", False)),
                    "badge_campaign": True,
                },
            )
            if self._maybe_white_wolf_king_boom(player):
                return
        self._run_actor_sequence(Phase.DAY_BADGE_SPEECH, candidates, handle)
        self._mark_phase_done(Phase.DAY_BADGE_SPEECH)

    def _badge_election_phase(self) -> None:
        if self._phase_done(Phase.DAY_BADGE_ELECTION):
            return
        self._set_phase(Phase.DAY_BADGE_ELECTION)
        candidates = [self.state.player(pid) for pid in self.state.badge.candidates if self.state.player(pid).alive]
        if len(candidates) < 1:
            self.state.badge.candidates = []
            self.state.badge.signup = {}
            self._mark_phase_done(Phase.DAY_BADGE_ELECTION)
            return
        votes = dict(self.state.badge.votes)
        candidate_ids = {player.id for player in candidates}

        def handle(voter: Player) -> None:
            if voter.id in votes:
                return
            decision = self._ask(voter, "BADGE_ELECTION", lambda agent: agent.vote())
            if decision.target_id not in candidate_ids:
                decision = Decision(
                    voter.id,
                    ActionType.VOTE,
                    target_id=candidates[0].id,
                    reasoning="Fallback badge vote.",
                    metadata={"source": "fallback", "fallback": True},
                )
            votes[voter.id] = decision.target_id or candidates[0].id
            target = self.state.player(votes[voter.id])
            self._log(
                EventType.VOTE_CAST,
                "public",
                {
                    "voter_id": voter.id,
                    "voter_name": voter.name,
                    "target_id": target.id,
                    "target_name": target.name,
                    "reasoning": decision.reasoning,
                    "agent_source": decision.metadata.get("source"),
                    "agent_model": decision.metadata.get("model"),
                    "agent_provider": decision.metadata.get("provider"),
                    "agent_fallback": bool(decision.metadata.get("fallback", False)),
                    "badge_election": True,
                },
            )
            self.state.badge.votes = dict(votes)

        self._run_actor_sequence(Phase.DAY_BADGE_ELECTION, list(self.state.alive_players), handle)
        self.state.badge.votes = votes
        self.state.badge.history[self.state.day] = dict(votes)
        winner_id = self._majority_target(votes)
        self.state.badge.holder_id = winner_id
        winner = self.state.player(winner_id)
        self._log(
            EventType.SYSTEM_MESSAGE,
            "public",
            {"message": f"{winner.name} won the badge election and becomes sheriff."},
        )
        self._mark_phase_done(Phase.DAY_BADGE_ELECTION)

    def _guard_phase(self) -> None:
        if self._phase_done(Phase.NIGHT_GUARD_ACTION):
            return
        self._set_phase(Phase.NIGHT_GUARD_ACTION)
        guard = self._alive_role(Role.GUARD)
        if guard is None:
            self._mark_phase_done(Phase.NIGHT_GUARD_ACTION)
            return
        decision = self._ask(guard, "GUARD", lambda agent: agent.guard())
        if not self.validator.validate(self.state, decision):
            self._mark_phase_done(Phase.NIGHT_GUARD_ACTION)
            return
        if decision.target_id == self.state.night_actions.last_guard_target_id:
            self._log_decision(decision, "private", {"ignored": True, "reason": "guard_cannot_repeat"}, [guard.id])
            self._mark_phase_done(Phase.NIGHT_GUARD_ACTION)
            return
        self.state.night_actions.guard_target_id = decision.target_id
        self.state.night_actions.last_guard_target_id = decision.target_id
        self._log_decision(decision, "private", {"target_id": decision.target_id}, [guard.id])
        self._mark_phase_done(Phase.NIGHT_GUARD_ACTION)

    def _wolf_phase(self) -> None:
        if self._phase_done(Phase.NIGHT_WOLF_ACTION):
            return
        self._set_phase(Phase.NIGHT_WOLF_ACTION)
        wolves = [player for player in self.state.alive_players if player.alignment == Alignment.WOLF]
        if not wolves:
            self._mark_phase_done(Phase.NIGHT_WOLF_ACTION)
            return

        def handle(wolf: Player) -> None:
            if wolf.id in self.state.night_actions.wolf_votes:
                return
            decision = self._ask(wolf, "ATTACK", lambda agent: agent.attack())
            if self.validator.validate(self.state, decision):
                self.state.night_actions.wolf_votes[wolf.id] = decision.target_id or ""
                self._log_decision(decision, "private", {"target_id": decision.target_id}, [w.id for w in wolves])
        self._run_actor_sequence(Phase.NIGHT_WOLF_ACTION, wolves, handle)
        if self.state.night_actions.wolf_votes:
            self.state.night_actions.wolf_target_id = self._majority_target(self.state.night_actions.wolf_votes)
        self._mark_phase_done(Phase.NIGHT_WOLF_ACTION)

    def _witch_phase(self) -> None:
        if self._phase_done(Phase.NIGHT_WITCH_ACTION):
            return
        self._set_phase(Phase.NIGHT_WITCH_ACTION)
        witch = self._alive_role(Role.WITCH)
        if witch is None:
            self._mark_phase_done(Phase.NIGHT_WITCH_ACTION)
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
        self._mark_phase_done(Phase.NIGHT_WITCH_ACTION)

    def _seer_phase(self) -> None:
        if self._phase_done(Phase.NIGHT_SEER_ACTION):
            return
        self._set_phase(Phase.NIGHT_SEER_ACTION)
        seer = self._alive_role(Role.SEER)
        if seer is None:
            self._mark_phase_done(Phase.NIGHT_SEER_ACTION)
            return
        decision = self._ask(seer, "DIVINE", lambda agent: agent.divine())
        if not self.validator.validate(self.state, decision):
            self._mark_phase_done(Phase.NIGHT_SEER_ACTION)
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
        self._mark_phase_done(Phase.NIGHT_SEER_ACTION)

    def _night_resolve(self) -> None:
        if self._phase_done(Phase.NIGHT_RESOLVE):
            return
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
        # Hunter killed at night can shoot (unless poisoned - handled in _kill)
        for death in unique_deaths:
            target = self.state.player(death["player_id"])
            if target.role == Role.HUNTER and self.state.abilities.hunter_can_shoot:
                self.pending_hunter_id = target.id
                self.phase_manager.run(Phase.HUNTER_SHOOT, self)
        if self.pending_badge_transfer_from_id and self.state.winner is None:
            self.phase_manager.run(Phase.BADGE_TRANSFER, self)
        self._mark_phase_done(Phase.NIGHT_RESOLVE)

    def _speech_phase(self) -> None:
        if self._phase_done(Phase.DAY_SPEECH):
            return
        self._set_phase(Phase.DAY_SPEECH)

        def handle(player: Player) -> None:
            decision = self._ask(player, "TALK", lambda agent: agent.talk())
            if not self.validator.validate(self.state, decision):
                return
            self._log(
                EventType.CHAT_MESSAGE,
                "public",
                {
                    "actor_id": player.id,
                    "actor_name": player.name,
                    "speech": decision.speech or "",
                    "reasoning": decision.reasoning,
                    "agent_source": decision.metadata.get("source"),
                    "agent_model": decision.metadata.get("model"),
                    "agent_provider": decision.metadata.get("provider"),
                    "agent_fallback": bool(decision.metadata.get("fallback", False)),
                },
            )
            if self._maybe_white_wolf_king_boom(player):
                return
        self._run_actor_sequence(Phase.DAY_SPEECH, list(self.state.alive_players), handle)
        self._mark_phase_done(Phase.DAY_SPEECH)

    def _pk_speech_phase(self, target_ids: list[str]) -> None:
        self._set_phase(Phase.DAY_PK_SPEECH)
        pk_players = [self.state.player(player_id) for player_id in target_ids if self.state.player(player_id).alive]
        if not pk_players:
            return
        names = ", ".join(player.name for player in pk_players)
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"Vote tie. PK speeches between {names}."})

        def handle(player: Player) -> None:
            decision = self._ask(player, "TALK", lambda agent: agent.talk())
            if not self.validator.validate(self.state, decision):
                return
            self._log(
                EventType.CHAT_MESSAGE,
                "public",
                {
                    "actor_id": player.id,
                    "actor_name": player.name,
                    "speech": decision.speech or "",
                    "reasoning": decision.reasoning,
                    "agent_source": decision.metadata.get("source"),
                    "agent_model": decision.metadata.get("model"),
                    "agent_provider": decision.metadata.get("provider"),
                    "agent_fallback": bool(decision.metadata.get("fallback", False)),
                    "pk_speech": True,
                },
            )
            if self._maybe_white_wolf_king_boom(player):
                return

        self._run_actor_sequence(Phase.DAY_PK_SPEECH, pk_players, handle)

    def _vote_phase(self) -> None:
        if self._phase_done(Phase.DAY_VOTE):
            return
        self._set_phase(Phase.DAY_VOTE)
        allowed_targets = set(self.state.pk_targets) if self.state.pk_targets else None
        eligible_voters = self._eligible_day_voters()

        def handle(voter: Player) -> None:
            if voter.id in self.state.votes:
                return
            decision = self._ask(voter, "VOTE", lambda agent: agent.vote())
            if not self.validator.validate(self.state, decision) or (
                allowed_targets is not None and decision.target_id not in allowed_targets
            ):
                target = self._fallback_vote_target(voter, target_ids=list(allowed_targets) if allowed_targets else None)
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
                    "agent_source": decision.metadata.get("source"),
                    "agent_model": decision.metadata.get("model"),
                    "agent_provider": decision.metadata.get("provider"),
                    "agent_fallback": bool(decision.metadata.get("fallback", False)),
                    "vote_weight": self._vote_weight(voter.id),
                    "is_pk_vote": bool(self.state.pk_targets),
                },
            )
        self._run_actor_sequence(Phase.DAY_VOTE, eligible_voters, handle)
        self._mark_phase_done(Phase.DAY_VOTE)

    def _day_resolve(self) -> None:
        if self._phase_done(Phase.DAY_RESOLVE):
            return
        self._set_phase(Phase.DAY_RESOLVE)
        if not self.state.votes:
            self._mark_phase_done(Phase.DAY_RESOLVE)
            return
        self.state.vote_history[self.state.day] = dict(self.state.votes)
        target_ids = self._top_targets(self.state.votes, weighted=True)
        if len(target_ids) > 1 and not self.state.pk_targets:
            self.state.day_history[self.state.day] = {"voteTie": True}
            self.state.pk_targets = list(target_ids)
            self.state.pk_source = "vote"
            # Allow the PK round to re-run the speech + vote phases that we
            # already marked done for the regular day flow.
            self._clear_phase_done(Phase.DAY_PK_SPEECH, Phase.DAY_VOTE, Phase.DAY_RESOLVE)
            self._pk_speech_phase(target_ids)
            self.state.votes = {}
            self._vote_phase()
            self._day_resolve()
            return
        if len(target_ids) > 1 and self.state.pk_targets:
            self.state.day_history[self.state.day] = {"voteTie": True}
            self._log(EventType.SYSTEM_MESSAGE, "public", {"message": "PK vote tied again. No one is eliminated today."})
            self.state.pk_targets = []
            self.state.pk_source = None
            self._refresh_day_summary()
            self._mark_phase_done(Phase.DAY_RESOLVE)
            return
        target_id = target_ids[0]
        executed = self.state.player(target_id)
        if executed.role == Role.IDIOT and not self.state.abilities.idiot_revealed:
            self.state.abilities.idiot_revealed = True
            self.state.day_history[self.state.day] = {
                "idiotRevealed": {"player_id": executed.id, "seat": executed.seat}
            }
            self._log(
                EventType.SYSTEM_MESSAGE,
                "public",
                {"message": f"{executed.name} revealed as Idiot and survives exile, but loses voting rights."},
            )
            self.state.pk_targets = []
            self.state.pk_source = None
            self._refresh_day_summary()
            self._mark_phase_done(Phase.DAY_RESOLVE)
            return
        self._last_words_phase(target_id)
        self._kill(target_id, "vote")
        target = self.state.player(target_id)
        self._log(EventType.SYSTEM_MESSAGE, "public", {"message": f"{target.name} was voted out."})
        self.state.day_history[self.state.day] = {
            "executed": {
                "player_id": target.id,
                "seat": target.seat,
                "votes": self._weighted_tally(self.state.vote_history[self.state.day])[target.id],
            }
        }
        self.state.pk_targets = []
        self.state.pk_source = None
        if target.role == Role.HUNTER and self.state.abilities.hunter_can_shoot:
            self.pending_hunter_id = target.id
            self.phase_manager.run(Phase.HUNTER_SHOOT, self)
        if self.pending_badge_transfer_from_id and self.state.winner is None:
            self.phase_manager.run(Phase.BADGE_TRANSFER, self)
        self._refresh_day_summary()
        # Restore phase so the play_until_blocked dispatcher routes us to night.
        self._set_phase(Phase.DAY_RESOLVE)
        self._mark_phase_done(Phase.DAY_RESOLVE)

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
                "agent_source": decision.metadata.get("source"),
                "agent_model": decision.metadata.get("model"),
                "agent_provider": decision.metadata.get("provider"),
                "agent_fallback": bool(decision.metadata.get("fallback", False)),
            },
        )
        if self.pending_badge_transfer_from_id and self.state.winner is None:
            self.phase_manager.run(Phase.BADGE_TRANSFER, self)
        self._refresh_day_summary()

    def _last_words_phase(self, player_id: str) -> None:
        player = self.state.player(player_id)
        if not player.alive:
            return
        self._set_phase(Phase.DAY_LAST_WORDS)
        self.state.current_speaker_id = player.id
        decision = self._ask(player, "LAST_WORDS", lambda agent: agent.talk())
        if not self.validator.validate(self.state, decision):
            return
        self._log(
            EventType.CHAT_MESSAGE,
            "public",
            {
                "actor_id": player.id,
                "actor_name": player.name,
                "speech": decision.speech or "",
                "reasoning": decision.reasoning,
                "agent_source": decision.metadata.get("source"),
                "agent_model": decision.metadata.get("model"),
                "agent_provider": decision.metadata.get("provider"),
                "agent_fallback": bool(decision.metadata.get("fallback", False)),
                "last_words": True,
            },
        )
        self.state.current_speaker_id = None

    def _maybe_white_wolf_king_boom(self, player: Player) -> bool:
        if player.role != Role.WHITE_WOLF_KING or not player.alive or self.state.abilities.white_wolf_king_boom_used:
            return False
        decision = self._ask(player, "BOOM", lambda agent: agent.boom())
        if decision.action_type != ActionType.BOOM:
            return False
        if not self.validator.validate(self.state, decision):
            return False
        self._white_wolf_king_boom(player, decision)
        return True

    def _white_wolf_king_boom(self, king: Player, decision: Decision) -> None:
        self._set_phase(Phase.WHITE_WOLF_KING_BOOM)
        self.state.abilities.white_wolf_king_boom_used = True
        target = self.state.player(decision.target_id or "")
        self._kill(king.id, "boom")
        self._kill(target.id, "boom")
        self.state.day_history[self.state.day] = {
            **self.state.day_history.get(self.state.day, {}),
            "whiteWolfKingBoom": {
                "boom_player_id": king.id,
                "boom_seat": king.seat,
                "target_player_id": target.id,
                "target_seat": target.seat,
            },
        }
        self._log(
            EventType.WHITE_WOLF_KING_BOOM,
            "public",
            {
                "boom_player_id": king.id,
                "boom_player_name": king.name,
                "target_id": target.id,
                "target_name": target.name,
                "reasoning": decision.reasoning,
                "agent_source": decision.metadata.get("source"),
                "agent_model": decision.metadata.get("model"),
                "agent_provider": decision.metadata.get("provider"),
                "agent_fallback": bool(decision.metadata.get("fallback", False)),
            },
        )
        self._log(
            EventType.SYSTEM_MESSAGE,
            "public",
            {"message": f"{king.name} self-destructs as White Wolf King and takes {target.name}."},
        )
        if target.role == Role.HUNTER and self.state.abilities.hunter_can_shoot:
            self.pending_hunter_id = target.id
            self.phase_manager.run(Phase.HUNTER_SHOOT, self)
        if self.pending_badge_transfer_from_id and self.state.winner is None:
            self.phase_manager.run(Phase.BADGE_TRANSFER, self)
        self.interrupt_phase_cycle = True
        self._refresh_day_summary()

    def _badge_transfer_from_pending(self) -> None:
        if self.pending_badge_transfer_from_id is None:
            return
        from_id = self.pending_badge_transfer_from_id
        self.pending_badge_transfer_from_id = None
        self._set_phase(Phase.BADGE_TRANSFER)
        alive = [player for player in self.state.alive_players if player.id != from_id]
        if not alive:
            self.state.badge.holder_id = None
            return
        successor = self._pick_badge_successor(alive)
        self.state.badge.holder_id = successor.id
        former = self.state.player(from_id)
        self._log(
            EventType.SYSTEM_MESSAGE,
            "public",
            {"message": f"{former.name} transfers the badge to {successor.name}."},
        )

    def _ask(self, player: Player, request: str, call, *, many: bool = False):
        view = self.visibility.for_player(self.state, player.id)
        agent = self.agents[player.id]
        agent.update(view, request)
        if not player.is_ai:
            queued = self.human_action_buffer.get(player.id, [])
            if not queued:
                self.state.pending_input = self._build_pending_input(player, request)
                if self.observer is not None:
                    self.observer(self.state)
                raise GamePaused(f"Waiting for human input: {player.name} {request}")
            result = queued if many else queued[0]
            self.human_action_buffer[player.id] = []
            if isinstance(result, Decision):
                self._record_decision(player, request, view.__dict__, result, raw_output="[human]")
            else:
                for item in result:
                    self._record_decision(player, request, view.__dict__, item, raw_output="[human]")
            return result
        result = call(agent)
        if isinstance(result, Decision):
            self._record_decision(player, request, view.__dict__, result, raw_output=str(result.metadata.get("raw_text", "")))
        elif isinstance(result, list):
            for item in result:
                self._record_decision(player, request, view.__dict__, item, raw_output=str(item.metadata.get("raw_text", "")))
        return result if many else result

    def _coerce_human_decisions(self, player: Player, pending: PendingInput, payload: dict[str, object]) -> list[Decision]:
        target_id = str(payload.get("target_id") or "") or None
        speech = str(payload.get("speech") or "").strip() or None
        reasoning = str(payload.get("reasoning") or "Human action")
        if pending.request in {"TALK", "BADGE_SPEECH", "LAST_WORDS"}:
            return [Decision(player.id, ActionType.TALK, speech=speech or "...", reasoning=reasoning, metadata={"source": "human"})]
        if pending.request in {"VOTE", "BADGE_ELECTION"}:
            return [Decision(player.id, ActionType.VOTE, target_id=target_id, reasoning=reasoning, metadata={"source": "human"})]
        if pending.request == "ATTACK":
            return [Decision(player.id, ActionType.ATTACK, target_id=target_id, reasoning=reasoning, metadata={"source": "human"})]
        if pending.request == "DIVINE":
            return [Decision(player.id, ActionType.DIVINE, target_id=target_id, reasoning=reasoning, metadata={"source": "human"})]
        if pending.request == "GUARD":
            return [Decision(player.id, ActionType.GUARD, target_id=target_id, reasoning=reasoning, metadata={"source": "human"})]
        if pending.request == "SHOOT":
            return [Decision(player.id, ActionType.SHOOT, target_id=target_id, reasoning=reasoning, metadata={"source": "human"})]
        if pending.request == "BOOM":
            return [Decision(player.id, ActionType.BOOM, target_id=target_id, reasoning=reasoning, metadata={"source": "human"})]
        if pending.request == "WITCH":
            decisions: list[Decision] = []
            if bool(payload.get("save")) and self.state.night_actions.wolf_target_id:
                decisions.append(
                    Decision(
                        player.id,
                        ActionType.WITCH_SAVE,
                        target_id=self.state.night_actions.wolf_target_id,
                        reasoning=reasoning,
                        metadata={"source": "human"},
                    )
                )
            if target_id:
                decisions.append(
                    Decision(
                        player.id,
                        ActionType.WITCH_POISON,
                        target_id=target_id,
                        reasoning=reasoning,
                        metadata={"source": "human"},
                    )
                )
            if not decisions:
                decisions.append(Decision(player.id, ActionType.SKIP, reasoning=reasoning, metadata={"source": "human"}))
            return decisions
        raise ValueError(f"Unsupported human request: {pending.request}")

    def _kill(self, player_id: str, reason: str) -> None:
        player = self.state.player(player_id)
        if not player.alive:
            return
        player.alive = False
        player.death_day = self.state.day
        player.death_reason = reason
        if self.state.badge.holder_id == player.id:
            self.pending_badge_transfer_from_id = player.id
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

    def _pick_badge_candidates(self, alive: list[Player]) -> list[Player]:
        priority_roles = {Role.SEER, Role.HUNTER, Role.WEREWOLF, Role.WHITE_WOLF_KING, Role.WITCH}
        candidates = [player for player in alive if player.role in priority_roles]
        if len(candidates) < 2:
            remaining = [player for player in alive if player not in candidates]
            candidates.extend(remaining[: 2 - len(candidates)])
        if len(candidates) > 3:
            candidates = sorted(candidates, key=lambda player: (player.seat, player.name))[:3]
        return candidates

    def _pick_badge_successor(self, alive: list[Player]) -> Player:
        preferred = [player for player in alive if player.alignment == Alignment.VILLAGE]
        pool = preferred or alive
        return sorted(pool, key=lambda player: (player.seat, player.name))[0]

    def _alive_role(self, role: Role) -> Player | None:
        return next((player for player in self.state.alive_players if player.role == role), None)

    def _fallback_vote_target(self, voter: Player, target_ids: list[str] | None = None) -> Player:
        allowed = set(target_ids) if target_ids else None
        return next(
            player
            for player in self.state.alive_players
            if player.id != voter.id and (allowed is None or player.id in allowed)
        )

    def _majority_target(self, votes: dict[str, str]) -> str:
        counts = Counter(votes.values())
        max_votes = max(counts.values())
        tied = sorted(target_id for target_id, count in counts.items() if count == max_votes)
        return tied[0]

    def _vote_weight(self, voter_id: str) -> float:
        return 1.5 if self.state.badge.holder_id == voter_id else 1.0

    def _weighted_tally(self, votes: dict[str, str]) -> dict[str, float]:
        counts: dict[str, float] = {}
        for voter_id, target_id in votes.items():
            counts[target_id] = counts.get(target_id, 0.0) + self._vote_weight(voter_id)
        return counts

    def _top_targets(self, votes: dict[str, str], *, weighted: bool = False) -> list[str]:
        counts = self._weighted_tally(votes) if weighted else {key: float(value) for key, value in Counter(votes.values()).items()}
        max_votes = max(counts.values())
        return sorted(target_id for target_id, count in counts.items() if count == max_votes)

    def _eligible_day_voters(self) -> list[Player]:
        alive = [
            player for player in self.state.alive_players
            if not (player.role == Role.IDIOT and self.state.abilities.idiot_revealed)
        ]
        if not self.state.pk_targets:
            return alive
        pk_set = set(self.state.pk_targets)
        return [player for player in alive if player.id not in pk_set]

    def _set_phase(self, phase: Phase) -> None:
        self.state.phase = phase
        self._log(EventType.PHASE_CHANGED, "public", {"phase": phase.value})

    def _run_actor_sequence(self, phase: Phase, players: list[Player], handler) -> None:
        cursor_key = phase.value
        start_index = int(self.state.phase_cursor.get(cursor_key, 0))
        for index in range(start_index, len(players)):
            if self.state.winner is not None or self.interrupt_phase_cycle:
                break
            player = players[index]
            self.state.phase_cursor[cursor_key] = index
            self.state.current_speaker_id = player.id
            handler(player)
        self.state.current_speaker_id = None
        self.state.phase_cursor.pop(cursor_key, None)

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
            "agent_source": decision.metadata.get("source"),
            "agent_model": decision.metadata.get("model"),
            "agent_provider": decision.metadata.get("provider"),
            "agent_fallback": bool(decision.metadata.get("fallback", False)),
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

    def _record_decision(
        self,
        player: Player,
        request: str,
        view: dict,
        decision: Decision,
        *,
        raw_output: str | None = None,
        is_valid: bool = True,
        error_type: str | None = None,
    ) -> None:
        self.state.decision_records.append(
            DecisionAudit(
                id=str(uuid4()),
                game_id=self.state.id,
                player_id=player.id,
                day=self.state.day,
                phase=self.state.phase.value,
                request=request,
                observation=view,
                legal_actions=[],
                prompt_version=player.prompt_version,
                raw_output=raw_output,
                parsed_action={
                    "action_type": decision.action_type.value,
                    "target_id": decision.target_id,
                    "speech": decision.speech,
                    "reasoning": decision.reasoning,
                },
                is_valid=is_valid,
                error_type=error_type,
                latency_ms=None,
                prompt_tokens=None,
                completion_tokens=None,
                created_at=self.state.events[-1].ts if self.state.events else 0.0,
            )
        )

    def _build_pending_input(self, player: Player, request: str) -> PendingInput:
        allowed_targets = set(self.state.pk_targets) if request == "VOTE" and self.state.pk_targets else None
        options = [
            {"id": target.id, "name": target.name, "seat": target.seat}
            for target in self.state.alive_players
            if target.id != player.id and (allowed_targets is None or target.id in allowed_targets)
        ]
        action_type = "speech"
        prompt = f"{player.name} is expected to act in phase {self.state.phase.value}."
        can_skip = False
        placeholder = None
        if request in {"TALK", "BADGE_SPEECH", "LAST_WORDS"}:
            action_type = "speech"
            placeholder = "输入你的发言..."
            prompt = f"轮到 {player.name} 发言。"
        elif request in {"VOTE", "BADGE_ELECTION"}:
            action_type = "vote"
            prompt = f"轮到 {player.name} 选择投票目标。"
        elif request == "ATTACK":
            action_type = "night_action"
            prompt = f"轮到 {player.name} 选择夜袭目标。"
        elif request == "DIVINE":
            action_type = "night_action"
            prompt = f"轮到 {player.name} 选择查验目标。"
        elif request == "GUARD":
            action_type = "night_action"
            prompt = f"轮到 {player.name} 选择守护目标。"
        elif request == "SHOOT":
            action_type = "special"
            prompt = f"轮到 {player.name} 选择开枪目标。"
        elif request == "BOOM":
            action_type = "special"
            prompt = f"轮到 {player.name} 选择白狼王自爆带走的目标。"
        elif request == "WITCH":
            action_type = "special"
            can_skip = True
            prompt = f"轮到 {player.name} 决定是否救人或毒人。"
        return PendingInput(
            player_id=player.id,
            player_name=player.name,
            seat=player.seat,
            request=request,
            phase=self.state.phase.value,
            action_type=action_type,
            prompt=prompt,
            options=options,
            can_skip=can_skip,
            placeholder=placeholder,
        )

    def _refresh_day_summary(self) -> None:
        if self.state.day <= 0:
            return
        bullets, facts = build_day_summary(self.state.events, self.state.day)
        self.state.daily_summaries[self.state.day] = bullets
        self.state.daily_summary_facts[self.state.day] = facts
