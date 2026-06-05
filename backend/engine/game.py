from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from random import Random
from typing import Any, Callable
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
from backend.engine.rules import DEFAULT_ROLE_SET, build_players, get_role_configuration
from backend.engine.summary import build_day_summary
from backend.engine.visibility import Visibility


def _shuffle_personas_pool(count: int, seed: int | None) -> list[dict] | None:
    """Shuffle in-memory PERSONA_POOL by seed so MBTI→role varies per game.

    Each game gets a different set of personas (with different MBTIs)
    assigned to different seats. Over many games each MBTI type plays
    every role, enabling proper MBTI×Role win-rate analysis.
    """
    import random as _random
    from backend.agents.characters import PERSONA_POOL
    rng = _random.Random(seed or 0)
    pool = list(PERSONA_POOL)
    rng.shuffle(pool)
    # Pick `count` unique personas (cycle if pool < count)
    result = []
    for i in range(count):
        result.append(dict(pool[i % len(pool)]))
    return result


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
        player_count: int = 10,
        observer: Callable[[GameState], None] | None = None,
        strategy_version: str | None = None,
        strategy_bias: dict[str, list[str]] | None = None,
        strategy_bias_by_role: dict[str, dict[str, list[str]]] | None = None,
        sampled_personas: list[dict] | None = None,
    ):
        self.rng = Random(seed)
        self.strategy_version = strategy_version
        self.strategy_bias = strategy_bias or {}
        self.strategy_bias_by_role = strategy_bias_by_role or {}
        if players is None:
            roles = get_role_configuration(player_count)
            players = build_players(roles, seed=seed)
        self.state = GameState(
            id=str(uuid4()),
            phase=Phase.SETUP,
            day=0,
            players=players,
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
        # `_play_started` flips True the moment someone calls play() so a
        # reconnecting WebSocket can tell "this game is already running, just
        # tail it" apart from "this game was prepared but never started — I
        # should start it now". play_done fires when play() returns so tailing
        # clients have a definite signal to stop polling.
        import threading as _threading
        self._play_started: bool = False
        self.play_done: _threading.Event = _threading.Event()
        self._play_start_lock: _threading.Lock = _threading.Lock()
        self._shared_lock: _threading.RLock = _threading.RLock()
        sampled_personas = sampled_personas or self._sample_personas_from_db(len(self.state.players), seed)
        if not sampled_personas:
            # DB unavailable — shuffle in-memory PERSONA_POOL per seed so
            # each MBTI plays different roles across games (not name-bound).
            sampled_personas = _shuffle_personas_pool(len(self.state.players), seed)
        if sampled_personas:
            # Adopt the sampled persona's display name onto the seat so the
            # in-game card, system prompt and audit log all reference the
            # same identity.
            for player, persona_data in zip(self.state.players, sampled_personas):
                player.name = persona_data.get("name", player.name)
        self.characters = build_character_roster(
            self.state.players,
            seed=seed or 0,
            sampled_personas=sampled_personas,
        )
        self.agents = {}
        role_models_from_bias: dict[str, dict[str, Any]] = {}
        for role_name, bias in self.strategy_bias_by_role.items():
            role_models_from_bias[role_name] = {"strategy_bias": bias}
        self.attach_agents(
            agents or create_agents(
                self.state.players,
                {
                    "type": os.environ.get("AIWEREWOLF_DEFAULT_AGENT_TYPE", "llm"),
                    "seed": seed or 0,
                    "temperature": 1.0,
                    "speech_temperature": 1.0,
                    "character_map": self.characters,
                    "strategy_bias": self.strategy_bias,
                    "role_models": role_models_from_bias,
                },
            )
        )

    @staticmethod
    def _sample_personas_from_db(count: int, seed: int | None) -> list[dict] | None:
        """Try to pull a random persona roster from the DB.

        Returns None on any failure so the in-repo PERSONA_POOL takes over —
        DB sampling is an enhancement, never a hard requirement.
        """
        try:
            from backend.db.persona_db import sample_personas
            return sample_personas(count, seed=seed)
        except Exception:
            return None

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
        with self._shared_lock:
            bucket = self.state.phase_done.setdefault(self.state.day, [])
            if phase.value not in bucket:
                bucket.append(phase.value)

    def _clear_phase_done(self, *phases: Phase) -> None:
        with self._shared_lock:
            bucket = self.state.phase_done.get(self.state.day)
            if not bucket:
                return
            for phase in phases:
                if phase.value in bucket:
                    bucket.remove(phase.value)

    def _seat_sorted(self, players: list[Player]) -> list[Player]:
        """Return players ordered by seat number.

        Speech / vote phases all funnel through this so the audience sees a
        deterministic clockwise flow even if internal lists ever drift.
        """
        return sorted(players, key=lambda p: p.seat)

    def _day_speech_order(self) -> list[Player]:
        """Order alive players for the daytime speech round.

        Standard table convention:
          * day 1 — start at the sheriff's left neighbour (or seat 1 if no
            badge); otherwise plain seat ascending.
          * day 2+ — start at the player just after the most recent corpse so
            the table feels like a wake-up walk around the seats.
        Whatever the entry point, we rotate around the table so the order is
        still strictly by seat — only the starting offset changes.
        """
        alive = self._seat_sorted(self.state.alive_players)
        if len(alive) <= 1:
            return alive
        anchor_seat = self._speech_anchor_seat()
        if anchor_seat is None:
            return alive
        anchor_index = next(
            (i for i, p in enumerate(alive) if p.seat >= anchor_seat),
            0,
        )
        return alive[anchor_index:] + alive[:anchor_index]

    def _speech_anchor_seat(self) -> int | None:
        if self.state.day <= 1:
            holder_id = self.state.badge.holder_id
            if holder_id:
                holder = self.state.player(holder_id)
                return holder.seat + 1
            return None
        # Find the most recent corpse from yesterday or this morning.
        recent_deaths = [
            player
            for player in self.state.players
            if not player.alive and player.death_day in (self.state.day - 1, self.state.day)
        ]
        if not recent_deaths:
            return None
        recent_deaths.sort(key=lambda p: (p.death_day or 0, p.seat))
        return recent_deaths[-1].seat + 1

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
            self.agents[player.id].initialize(
                view,
                {"max_days": self.state.max_days, "game_id": self.state.id},
            )
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
        # Idempotent start: if play() was already entered (e.g. another thread
        # is mid-game), return the current state immediately. A reconnecting
        # WebSocket detects this case earlier via `_play_started` and switches
        # to tail-only mode, but the lock here is the authoritative guard
        # against two threads trying to drive the same game in parallel.
        with self._play_start_lock:
            if self._play_started:
                return self.state
            self._play_started = True
        try:
            while self.state.winner is None:
                self.play_until_blocked()
                if self.state.pending_input is not None:
                    raise RuntimeError("Human input required; use play_until_blocked/submit_human_action for mixed games.")
            return self.state
        finally:
            self.play_done.set()

    def play_until_blocked(self) -> GameState:
        if not self.state.events:
            self.initialize()
            try:
                from backend.db.persist import save_game_start
                save_game_start(self.state)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "save_game_start failed (non-fatal, game continues)", exc_info=True
                )
        self.state.pending_input = None
        self.interrupt_phase_cycle = False
        try:
            while self.state.winner is None and self.state.day < self.state.max_days:
                if self.state.phase in {Phase.SETUP, Phase.DAY_RESOLVE, Phase.HUNTER_SHOOT, Phase.WHITE_WOLF_KING_BOOM, Phase.GAME_END}:
                    self.phase_manager.run(Phase.NIGHT_START, self)
                elif self.state.phase == Phase.BADGE_TRANSFER:
                    # Badge transfer after night death → continue to day
                    # Badge transfer after day vote → already handled by DAY_RESOLVE before this
                    if self._check_win():
                        break
                    self.phase_manager.run(Phase.DAY_START, self)
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
                import logging
                logging.getLogger(__name__).warning(
                    "save_game_end failed (non-fatal)", exc_info=True
                )
            # Track B→C: score decisions + extract knowledge (post-game, has ground truth)
            try:
                from backend.eval.post_game import run_post_game_scoring
                n = run_post_game_scoring(self.state, str(self.state.id))
                import logging
                if n > 0:
                    logging.getLogger(__name__).info(
                        f"Post-game scoring: {n} knowledge lessons extracted for game {self.state.id}"
                    )
                elif os.getenv("REQUIRE_POST_GAME_SCORING", "").lower() == "true":
                    logging.getLogger(__name__).error("STRICT FAIL: Post-game scoring produced 0 lessons")
            except Exception:
                if os.getenv("REQUIRE_POST_GAME_SCORING", "").lower() == "true":
                    raise  # fail fast in strict mode
                import logging
                logging.getLogger(__name__).warning(
                    "Post-game scoring failed (non-fatal)", exc_info=True
                )
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
        if self.state.day != 1 or self.state.badge.holder_id is not None:
            # Badge campaign only happens on day 1 and only if no sheriff exists
            # yet. Wipe any residual state and short-circuit without emitting
            # PHASE_CHANGED (no UI flicker for skipped phases), and mark the
            # downstream badge phases done so they don't re-run on day 2+.
            self.state.badge.candidates = []
            self.state.badge.signup = {}
            self.state.badge.votes = {}
            self._mark_phase_done(Phase.DAY_BADGE_SIGNUP)
            self._mark_phase_done(Phase.DAY_BADGE_SPEECH)
            self._mark_phase_done(Phase.DAY_BADGE_ELECTION)
            return
        self._set_phase(Phase.DAY_BADGE_SIGNUP)
        alive = self._seat_sorted(self.state.alive_players)
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
        # Speak in seat order so the audience sees a coherent flow.
        candidates = self._seat_sorted(
            [self.state.player(candidate_id) for candidate_id in self.state.badge.candidates]
        )

        def handle(player: Player) -> None:
            if not player.alive:
                return
            decision = self._ask(player, "BADGE_SPEECH", lambda agent: agent.talk())
            if not self.validator.validate(self.state, decision):
                return
            self._emit_speech(player, decision, {"badge_campaign": True})
            if self._maybe_white_wolf_king_boom(player):
                return
        self._run_actor_sequence(Phase.DAY_BADGE_SPEECH, candidates, handle)
        self._mark_phase_done(Phase.DAY_BADGE_SPEECH)

    def _badge_election_phase(self) -> None:
        if self._phase_done(Phase.DAY_BADGE_ELECTION):
            return
        self._set_phase(Phase.DAY_BADGE_ELECTION)
        candidates = self._seat_sorted(
            [self.state.player(pid) for pid in self.state.badge.candidates if self.state.player(pid).alive]
        )
        if len(candidates) < 1:
            self.state.badge.candidates = []
            self.state.badge.signup = {}
            self._mark_phase_done(Phase.DAY_BADGE_ELECTION)
            return
        candidate_ids = {player.id for player in candidates}

        # Voters in seat order, candidates excluded.
        voters = self._seat_sorted(
            [player for player in self.state.alive_players if player.id not in candidate_ids]
        )
        if not voters:
            voters = self._seat_sorted(self.state.alive_players)

        # Parallel LLM execution for all badge votes (simultaneous voting)
        decisions = self._batch_ask(
            players=voters,
            request="BADGE_ELECTION",
            call_fn=lambda agent: agent.vote(),
        )

        # Sequential result processing (main thread, deterministic order)
        votes: dict[str, str] = {}
        for voter, decision in zip(voters, decisions):
            if decision.target_id not in candidate_ids:
                if self._requires_strict_llm_decision(voter):
                    self._raise_invalid_llm_decision(
                        voter,
                        "BADGE_ELECTION",
                        decision,
                        f"target_id={decision.target_id!r} is not a badge candidate",
                    )
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

        self.state.badge.votes = votes
        self.state.badge.history[self.state.day] = dict(votes)
        if not votes:
            # No usable ballots — first candidate wins by default.
            winner_id = candidates[0].id
        else:
            winner_id = self._majority_target(votes)
        self.state.badge.holder_id = winner_id
        winner = self.state.player(winner_id)
        self._log(
            EventType.SYSTEM_MESSAGE,
            "public",
            {"message": f"{winner.name} won the badge election and becomes sheriff."},
        )
        # Election done — clear ballot/candidate roster so day 2+ won't loop.
        self.state.badge.candidates = []
        self.state.badge.signup = {}
        self._mark_phase_done(Phase.DAY_BADGE_ELECTION)

    def _night_role_actions_parallel(self) -> None:
        """Run Guard + Wolf + Seer with parallelism where safe.

        Guard and Seer are independent of each other and of wolves (they
        read public state only, write to different NightActions fields).
        Wolf internal voting is sequential (later wolves see earlier votes)
        so it stays in the main thread. Witch depends on wolf_target_id
        and runs separately after this method completes.

        Thread safety: _guard_phase / _wolf_phase / _seer_phase all use
        _set_phase → _log → events.append and _record_decision →
        decision_records.append, both now protected by _shared_lock.
        """
        import sys as _sys
        import threading as _thr

        guard = self._alive_role(Role.GUARD)
        seer = self._alive_role(Role.SEER)

        guard_done = _thr.Event()
        seer_done = _thr.Event()
        guard_err: list[BaseException | None] = [None]
        seer_err: list[BaseException | None] = [None]

        def _run_guard():
            try:
                if guard and not self._phase_done(Phase.NIGHT_GUARD_ACTION):
                    self._clear_phase_done(Phase.NIGHT_GUARD_ACTION)
                    self._guard_phase()
            except GamePaused:
                guard_err[0] = _sys.exc_info()[1]
            except BaseException as e:
                guard_err[0] = e
            finally:
                guard_done.set()

        def _run_seer():
            try:
                if seer and not self._phase_done(Phase.NIGHT_SEER_ACTION):
                    self._clear_phase_done(Phase.NIGHT_SEER_ACTION)
                    self._seer_phase()
            except GamePaused:
                seer_err[0] = _sys.exc_info()[1]
            except BaseException as e:
                seer_err[0] = e
            finally:
                seer_done.set()

        g_thread = _thr.Thread(target=_run_guard, name="guard") if guard else None
        s_thread = _thr.Thread(target=_run_seer, name="seer") if seer else None

        if g_thread:
            g_thread.start()
        if s_thread:
            s_thread.start()

        # Run Wolf in main thread while Guard/Seer progress in background
        if not self._phase_done(Phase.NIGHT_WOLF_ACTION):
            self._wolf_phase()

        # Wait for Guard and Seer to finish
        if g_thread:
            g_thread.join()
        if s_thread:
            s_thread.join()

        # Propagate GamePaused from background threads
        if isinstance(guard_err[0], GamePaused):
            raise guard_err[0]
        if isinstance(seer_err[0], GamePaused):
            raise seer_err[0]
        # Propagate other errors
        if guard_err[0]:
            raise guard_err[0]
        if seer_err[0]:
            raise seer_err[0]

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
        wolf_ids = [wolf.id for wolf in wolves]
        self._log(
            EventType.PRIVATE_INFO,
            "private",
            {
                "kind": "wolf_chat_start",
                "message": "Wolf team discussion begins. Discuss the night kill target, then each wolf casts an internal attack vote.",
                "wolf_ids": wolf_ids,
                "wolf_names": [wolf.name for wolf in wolves],
            },
            visible_to=wolf_ids,
        )

        def handle(wolf: Player) -> None:
            if wolf.id in self.state.night_actions.wolf_votes:
                return
            visible_votes = [
                {
                    "wolf_id": voter_id,
                    "wolf_name": self.state.player(voter_id).name,
                    "target_id": target_id,
                    "target_name": self.state.player(target_id).name if target_id else None,
                }
                for voter_id, target_id in self.state.night_actions.wolf_votes.items()
                if target_id
            ]
            self._log(
                EventType.PRIVATE_INFO,
                "private",
                {
                    "kind": "wolf_discussion_turn",
                    "actor_id": wolf.id,
                    "actor_name": wolf.name,
                    "message": f"{wolf.name} is choosing a proposed kill target for the wolf team.",
                    "previous_votes": visible_votes,
                },
                visible_to=wolf_ids,
            )
            decision = self._ask(wolf, "WOLF_TEAM_VOTE", lambda agent: agent.attack())
            if self.validator.validate(self.state, decision):
                self.state.night_actions.wolf_votes[wolf.id] = decision.target_id or ""
                self._log_decision(
                    decision,
                    "private",
                    {
                        "kind": "wolf_attack_vote",
                        "target_id": decision.target_id,
                        "target_name": self.state.player(decision.target_id).name if decision.target_id else None,
                        "current_votes": dict(self.state.night_actions.wolf_votes),
                    },
                    wolf_ids,
                )
        self._run_actor_sequence(Phase.NIGHT_WOLF_ACTION, self._seat_sorted(wolves), handle)
        if self.state.night_actions.wolf_votes:
            self.state.night_actions.wolf_target_id = self._majority_target(self.state.night_actions.wolf_votes)
            final_target = self.state.player(self.state.night_actions.wolf_target_id)
            self._log(
                EventType.PRIVATE_INFO,
                "private",
                {
                    "kind": "wolf_attack_tally",
                    "message": f"Wolf team final attack target is {final_target.name}.",
                    "target_id": final_target.id,
                    "target_name": final_target.name,
                    "votes": dict(self.state.night_actions.wolf_votes),
                },
                visible_to=wolf_ids,
            )
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
            self._set_phase(Phase.NIGHT_RESOLVE)  # restore: while-loop routes NIGHT_RESOLVE → DAY
        # If hunter shot happened, restore phase so the main while-loop routes
        # NIGHT_RESOLVE → DAY_START instead of HUNTER_SHOOT → NIGHT_START.
        if self.state.phase != Phase.NIGHT_RESOLVE:
            self._set_phase(Phase.NIGHT_RESOLVE)
        self._mark_phase_done(Phase.NIGHT_RESOLVE)

    def _speech_phase(self) -> None:
        if self._phase_done(Phase.DAY_SPEECH):
            return
        self._set_phase(Phase.DAY_SPEECH)

        def handle(player: Player) -> None:
            decision = self._ask(player, "TALK", lambda agent: agent.talk())
            if not self.validator.validate(self.state, decision):
                return
            self._emit_speech(player, decision, {})
            if self._maybe_white_wolf_king_boom(player):
                return
        speakers = self._day_speech_order()
        self._run_actor_sequence(Phase.DAY_SPEECH, speakers, handle)
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
            self._emit_speech(player, decision, {"pk_speech": True})
            if self._maybe_white_wolf_king_boom(player):
                return

        self._run_actor_sequence(Phase.DAY_PK_SPEECH, self._seat_sorted(pk_players), handle)

    def _vote_phase(self) -> None:
        if self._phase_done(Phase.DAY_VOTE):
            return
        self._set_phase(Phase.DAY_VOTE)
        allowed_targets = set(self.state.pk_targets) if self.state.pk_targets else None
        eligible_voters = self._eligible_day_voters()
        sorted_voters = self._seat_sorted(eligible_voters)

        # Parallel LLM execution for all votes (simultaneous voting is the
        # real game rule — each player decides independently).
        decisions = self._batch_ask(
            players=sorted_voters,
            request="VOTE",
            call_fn=lambda agent: agent.vote(),
        )

        # Sequential result processing (main thread, deterministic order)
        for voter, decision in zip(sorted_voters, decisions):
            if voter.id in self.state.votes:
                continue
            if not self.validator.validate(self.state, decision) or (
                allowed_targets is not None and decision.target_id not in allowed_targets
            ):
                if self._requires_strict_llm_decision(voter):
                    self._raise_invalid_llm_decision(
                        voter,
                        "VOTE",
                        decision,
                        "vote target is invalid or outside PK targets",
                    )
                target = self._fallback_vote_target(voter, target_ids=list(allowed_targets) if allowed_targets else None)
                decision = Decision(
                    voter.id,
                    ActionType.VOTE,
                    target_id=target.id,
                    reasoning="Fallback legal vote.",
                    metadata={"source": "fallback", "fallback": True},
                )
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
        # Defensive: when the recursive PK path runs with no usable ballots,
        # vote_history[day] may not have been written this round. Fall back to
        # the empty dict so the executed-summary still serializes.
        day_votes = self.state.vote_history.get(self.state.day, {})
        self.state.day_history[self.state.day] = {
            "executed": {
                "player_id": target.id,
                "seat": target.seat,
                "votes": self._weighted_tally(day_votes).get(target.id, 0.0),
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
        self._emit_speech(player, decision, {"last_words": True})
        self.state.current_speaker_id = None

    def _emit_speech(self, player: Player, decision: Decision, extra_fields: dict) -> None:
        """Emit CHAT_MESSAGE events. Uses pre-parsed segments from metadata if available."""
        raw_segments = decision.metadata.get("segments")
        if raw_segments and isinstance(raw_segments, list) and len(raw_segments) > 0:
            segments = [str(s) for s in raw_segments]
        else:
            segments = [decision.speech or ""]
        for i, segment in enumerate(segments):
            payload = {
                "actor_id": player.id,
                "actor_name": player.name,
                "speech": segment,
                "reasoning": decision.reasoning if i == 0 else "",
                "segment_index": i,
                "segment_total": len(segments),
                "agent_source": decision.metadata.get("source") if i == 0 else "",
                "agent_model": decision.metadata.get("model") if i == 0 else "",
                "agent_provider": decision.metadata.get("provider") if i == 0 else "",
                "agent_fallback": bool(decision.metadata.get("fallback", False)) if i == 0 else False,
                **extra_fields,
            }
            self._log(EventType.CHAT_MESSAGE, "public", payload)

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
        former = self.state.player(from_id)
        if not alive:
            # Nobody left to inherit — badge effectively destroyed.
            self.state.badge.holder_id = None
            self._log(
                EventType.SYSTEM_MESSAGE,
                "public",
                {
                    "message": f"{former.name} 出局，但场上已无可继承的玩家，警徽消失。",
                    "from_id": former.id,
                    "from_name": former.name,
                    "from_seat": former.seat,
                    "to_id": None,
                    "to_name": None,
                    "to_seat": None,
                    "destroyed": True,
                    "reason": "no_eligible_successor",
                },
            )
            return
        # Ask the dying sheriff (LLM/human/heuristic) to choose a successor or
        # destroy the badge. The agent contract returns ActionType.SKIP for
        # "撕警徽" and ActionType.VOTE with target_id for "传给某某".
        candidate_ids = [p.id for p in alive]
        decision = self._ask(
            former,
            "TRANSFER_BADGE",
            lambda agent: agent.transfer_badge(candidate_ids),
        )
        successor: Player | None = None
        destroyed = False
        if decision.action_type == ActionType.SKIP or not decision.target_id:
            destroyed = True
        else:
            chosen_id = decision.target_id
            if chosen_id in candidate_ids:
                successor = self.state.player(chosen_id)
            else:
                if self._requires_strict_llm_decision(former):
                    self._raise_invalid_llm_decision(
                        former,
                        "TRANSFER_BADGE",
                        decision,
                        f"target_id={chosen_id!r} is not an eligible badge successor",
                    )
                # Agent picked someone invalid (dead or self) — fall back to
                # the heuristic preference so the game keeps moving.
                successor = self._pick_badge_successor(alive)
        self.state.badge.holder_id = successor.id if successor else None
        if destroyed:
            msg = f"{former.name} 撕掉了警徽，本局警徽功能失效。"
        else:
            msg = f"{former.name} 将警徽传给了 {successor.name}（座位 {successor.seat}）。"
        self._log(
            EventType.SYSTEM_MESSAGE,
            "public",
            {
                "message": msg,
                "from_id": former.id,
                "from_name": former.name,
                "from_seat": former.seat,
                "to_id": successor.id if successor else None,
                "to_name": successor.name if successor else None,
                "to_seat": successor.seat if successor else None,
                "destroyed": destroyed,
                "reasoning": decision.reasoning,
            },
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
        # AI turn — emit a "thinking" snapshot BEFORE we block on the LLM
        # round-trip. The frontend reads `current_speaker_id` to light up the
        # PlayerCard with a "思考中" pulse; without this frame the UI looks
        # frozen for the 4–10s the LLM is actually working.
        prior_speaker = self.state.current_speaker_id
        self.state.current_speaker_id = player.id
        if self.observer is not None:
            self.observer(self.state)
        try:
            result = call(agent)
        finally:
            # Only clear if we set it for this _ask — phases like DAY_SPEECH
            # already manage current_speaker_id externally and we shouldn't
            # blow it away.
            if self.state.current_speaker_id == player.id and prior_speaker != player.id:
                self.state.current_speaker_id = prior_speaker
        if isinstance(result, Decision):
            raw = str(result.metadata.get("raw_text", ""))
            reasoning = str(result.metadata.get("reasoning", ""))
            if reasoning:
                raw = f"[推理]\n{reasoning[:3000]}\n\n[输出]\n{raw}"
            self._record_decision(player, request, view.__dict__, result, raw_output=raw)
        elif isinstance(result, list):
            for item in result:
                raw = str(item.metadata.get("raw_text", ""))
                reasoning = str(item.metadata.get("reasoning", ""))
                if reasoning:
                    raw = f"[推理]\n{reasoning[:3000]}\n\n[输出]\n{raw}"
                self._record_decision(player, request, view.__dict__, item, raw_output=raw)
        return result if many else result

    def _batch_ask(
        self,
        players: list[Player],
        request: str,
        call_fn: Callable[[Agent], Any],
    ) -> list[Any]:
        """Execute LLM calls in parallel for independent agent actions.

        Three-phase design ensures thread safety without changing agent code:
          1. Main thread: agent.update(view, request) for each player (CPU-only, fast)
          2. ThreadPoolExecutor: call_fn(agent) for each player (LLM I/O, slow)
          3. Main thread: _record_decision for each player in deterministic order

        Falls back to sequential _ask if any player is human (preserves GamePaused).
        """
        import concurrent.futures as _futures

        # ---- Early exit: mixed human/AI batch falls back to sequential ----
        for player in players:
            if not player.is_ai:
                results: list[Any] = []
                for p in players:
                    results.append(self._ask(p, request, call_fn))
                return results

        n = len(players)

        # ---- Phase 1: Pre-compute views (main thread, no I/O) ----
        views: list[dict] = []
        for player in players:
            view = self.visibility.for_player(self.state, player.id)
            agent = self.agents[player.id]
            agent.update(view, request)
            views.append(view.__dict__)

        # ---- Phase 2: Execute LLM calls in parallel ----
        # Each agent has its own DeepSeekClient which creates a new
        # httpx.Client per chat_sync() call, so concurrent access is safe.
        results_by_index: dict[int, Any] = {}
        with _futures.ThreadPoolExecutor(max_workers=n) as pool:
            fut_to_idx: dict[_futures.Future, int] = {}
            for i, player in enumerate(players):
                agent = self.agents[player.id]
                fut = pool.submit(call_fn, agent)
                fut_to_idx[fut] = i
            for fut in _futures.as_completed(fut_to_idx):
                idx = fut_to_idx[fut]
                results_by_index[idx] = fut.result()

        # ---- Phase 3: Record results (main thread, deterministic order) ----
        results: list[Any] = []
        for i in range(n):
            player = players[i]
            view = views[i]
            result = results_by_index[i]
            results.append(result)
            self._record_sequential(player, request, view, result)

        return results

    def _record_sequential(
        self, player: Player, request: str, view: dict, result: Any,
    ) -> None:
        """Record a decision from _batch_ask result. Mirrors the recording
        portion of _ask() so batch results get the same audit trail."""
        if isinstance(result, Decision):
            raw = str(result.metadata.get("raw_text", ""))
            reasoning = str(result.metadata.get("reasoning", ""))
            if reasoning:
                raw = f"[推理]\n{reasoning[:3000]}\n\n[输出]\n{raw}"
            self._record_decision(player, request, view, result, raw_output=raw)
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, Decision):
                    raw = str(item.metadata.get("raw_text", ""))
                    reasoning = str(item.metadata.get("reasoning", ""))
                    if reasoning:
                        raw = f"[推理]\n{reasoning[:3000]}\n\n[输出]\n{raw}"
                    self._record_decision(player, request, view, item, raw_output=raw)

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
        if pending.request == "TRANSFER_BADGE":
            # SKIP target_id=None means destroy the badge; otherwise the human
            # picked a successor from the option list. We mirror the LLM agent
            # by using VOTE as the carrier action for "pick this player".
            if target_id is None:
                return [Decision(player.id, ActionType.SKIP, reasoning=reasoning or "撕警徽", metadata={"source": "human"})]
            return [Decision(player.id, ActionType.VOTE, target_id=target_id, reasoning=reasoning or "传给该玩家", metadata={"source": "human"})]
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

    def _requires_strict_llm_decision(self, player: Player) -> bool:
        return player.is_ai and str(player.agent_type).strip().lower() in {"llm", "cognitive"}

    def _raise_invalid_llm_decision(
        self,
        player: Player,
        request: str,
        decision: Decision,
        detail: str,
    ) -> None:
        raise RuntimeError(
            f"Invalid LLM decision in {request}: player={player.id} "
            f"action={decision.action_type.value} target={decision.target_id!r}; {detail}"
        )

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
        with self._shared_lock:
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
        with self._shared_lock:
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
        meta = decision.metadata if isinstance(decision.metadata, dict) else {}
        usage = meta.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        latency_ms = meta.get("latency_ms")
        if latency_ms is None and isinstance(usage, dict):
            latency_ms = usage.get("latency_ms")

        # Compute prompt hash from the observation + request (stable fingerprint)
        _prompt_src = json.dumps({"request": request, "day": self.state.day, "phase": self.state.phase.value}, sort_keys=True)
        prompt_hash = hashlib.sha256(_prompt_src.encode()).hexdigest()[:16]

        # Estimate cost from token usage (DeepSeek pricing: ~$0.28/M input, $1.10/M output)
        cost_usd = None
        if prompt_tokens is not None and completion_tokens is not None:
            cost_usd = round((prompt_tokens * 0.28 + completion_tokens * 1.10) / 1_000_000, 6)

        # Extract visible facts from player view
        visible_facts = []
        if isinstance(view, dict):
            sv = view.get("self_player", {})
            visible_facts.append("role=" + str(sv.get("role", "?")))
            visible_facts.append("alive=" + str(sv.get("alive", "?")))
            alive = view.get("alive_players", [])
            visible_facts.append("alive_count=" + str(len(alive) if isinstance(alive, list) else "?"))

        # Populate candidate actions from legal actions or metadata
        candidate_actions = meta.get("candidate_actions", [])
        if not candidate_actions:
            view_targets = view.get("legal_targets", []) if isinstance(view, dict) else []
            for target in view_targets:
                candidate_actions.append({
                    "target_id": target.get("id"),
                    "target_name": target.get("name"),
                })
            if not candidate_actions:
                allowed = set(self.state.pk_targets) if request == "VOTE" and self.state.pk_targets else None
                for target in self.state.alive_players:
                    if target.id != player.id and (allowed is None or target.id in allowed):
                        candidate_actions.append({"target_id": target.id, "target_name": target.name})

        with self._shared_lock:
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
                        "metadata": decision.metadata,
                        "retrieved_knowledge_ids": list(decision.metadata.get("retrieved_knowledge_ids", [])),
                        "retrieval_query_summary": decision.metadata.get("retrieval_query_summary"),
                        "retrieval_used": bool(decision.metadata.get("retrieval_used", False)),
                    },
                    is_valid=is_valid,
                    error_type=error_type,
                    latency_ms=int(latency_ms) if isinstance(latency_ms, (int, float)) else None,
                    prompt_tokens=int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else None,
                    completion_tokens=int(completion_tokens) if isinstance(completion_tokens, (int, float)) else None,
                    created_at=self.state.events[-1].ts if self.state.events else 0.0,
                    # v2 DecisionTrace fields
                    visible_facts=visible_facts,
                    candidate_actions=candidate_actions,
                    confidence=meta.get("confidence"),
                    prompt_hash=prompt_hash,
                    cost_usd=cost_usd,
                    model_name=meta.get("model"),
                    provider=meta.get("provider"),
                    fallback_used=bool(meta.get("fallback", False)),
                    fallback_reason=meta.get("fallback_reason"),
                    metadata=decision.metadata if isinstance(decision.metadata, dict) else {},
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
