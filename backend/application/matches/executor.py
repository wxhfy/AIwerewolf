from __future__ import annotations

import logging
import os
import time
from typing import Any

from backend.application.agents.runtime import AgentRuntime
from backend.application.agents.runtime import LocalAgentRuntime
from backend.application.matches.repository import ClaimedMatchJob
from backend.application.matches.repository import MatchJobRepository
from backend.application.matches.spec import MatchExecutionSpec
from backend.db.database import init_db
from backend.db.persist import complete_match_transaction
from backend.db.persist import save_decisions_batch
from backend.db.persist import save_event
from backend.db.persist import save_game_start
from backend.db.persist import save_snapshot
from backend.engine.game import WerewolfGame
from backend.engine.models import GameState
from backend.infrastructure.messaging.match_notifications import match_notifications

logger = logging.getLogger(__name__)


def _sample_personas(count: int, seed: int | None) -> list[dict] | None:
    from backend.db.persona_db import sample_personas

    return sample_personas(count, seed=seed)


def persist_snapshot(state: GameState) -> None:
    moderator = state.snapshot(show_private=True)
    public = state.snapshot(show_private=False)
    seq = int(moderator.get("seq") or 0)
    save_snapshot(state.id, seq, state.day, state.phase.value, moderator, public)
    match_notifications.publish(state.id, seq)


def build_game(
    *,
    seed: int,
    agent_type: str = "llm",
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
    phase_delay_ms: float = 0,
    llm_config: dict[str, Any] | None = None,
    game_id: str | None = None,
    players=None,
    sampled_personas: list[dict] | None = None,
    agent_runtime: AgentRuntime | None = None,
) -> WerewolfGame:
    runtime = agent_runtime or LocalAgentRuntime()
    game = prepare_game(
        seed=seed,
        player_count=player_count,
        rule_pack_id=rule_pack_id,
        phase_delay_ms=phase_delay_ms,
        game_id=game_id,
        players=players,
        sampled_personas=sampled_personas,
    )
    runtime.attach(
        game,
        {
            "type": agent_type,
            "seed": seed,
            **(llm_config or {}),
        },
    )
    return game


def prepare_game(
    *,
    seed: int,
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
    phase_delay_ms: float = 0,
    game_id: str | None = None,
    players=None,
    sampled_personas: list[dict] | None = None,
) -> WerewolfGame:
    del rule_pack_id
    init_db()
    game = WerewolfGame(
        players=players,
        seed=seed,
        player_count=player_count,
        phase_delay_ms=phase_delay_ms,
        sampled_personas=sampled_personas,
        persona_sampler=_sample_personas,
        on_game_start=save_game_start,
        on_game_end=None,
        on_event=save_event,
        on_decisions_flush=save_decisions_batch,
        on_post_game=None,
        game_id=game_id,
        auto_attach_agents=False,
    )
    for player in game.state.players:
        character = game.characters[player.id]
        player.persona = {
            "name": character.persona.name,
            "mbti": character.persona.mbti,
            "basic_info": character.persona.basic_info,
            "style_label": character.persona.style_label,
            "reasoning_style": character.persona.reasoning_style,
            "speech_length_habit": character.persona.speech_length_habit,
            "vocabulary_style": character.persona.vocabulary_style,
        }
    return game


class MatchExecutor:
    """Own one claimed AI match from setup through durable completion."""

    def __init__(
        self,
        repository: MatchJobRepository,
        *,
        worker_id: str,
        agent_runtime: AgentRuntime | None = None,
        lease_seconds: int = 600,
    ) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.agent_runtime = agent_runtime or LocalAgentRuntime()
        self.lease_seconds = lease_seconds

    def execute(self, job: ClaimedMatchJob) -> GameState:
        spec = MatchExecutionSpec.from_dict(job.payload)
        if spec.match_id != job.game_id:
            raise ValueError(f"Job match_id mismatch: {job.game_id} != {spec.match_id}")
        if any(not bool(player.get("is_ai", True)) for player in spec.players):
            raise ValueError("Match Worker currently accepts AI-only matches")

        game = build_game(
            seed=spec.seed,
            agent_type=spec.agent_type,
            player_count=spec.player_count,
            rule_pack_id=spec.rule_pack_id,
            phase_delay_ms=spec.phase_delay_ms,
            llm_config=spec.llm_config,
            game_id=spec.match_id,
            players=spec.build_players(),
            sampled_personas=spec.personas,
            agent_runtime=self.agent_runtime,
        )

        def observe(state: GameState) -> None:
            persist_snapshot(state)
            control_state = self.repository.heartbeat(
                job.id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            while control_state == "paused":
                time.sleep(0.5)
                control_state = self.repository.heartbeat(
                    job.id,
                    self.worker_id,
                    lease_seconds=self.lease_seconds,
                )

        game.observer = observe
        state = game.play()
        complete_match_transaction(state, job_id=job.id, worker_id=self.worker_id)
        final_snapshot = state.snapshot(show_private=True)
        match_notifications.publish(state.id, int(final_snapshot.get("seq") or len(state.events)))
        logger.info("Match %s completed with winner=%s", state.id, state.winner.value if state.winner else None)
        return state


def worker_poll_interval() -> float:
    return max(0.1, float(os.getenv("MATCH_WORKER_POLL_SECONDS", "1")))
