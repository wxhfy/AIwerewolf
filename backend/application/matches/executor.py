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
from backend.db.persist import get_agent_decision_by_request_id
from backend.db.persist import get_match_checkpoint
from backend.db.persist import save_decisions_batch
from backend.db.persist import save_event
from backend.db.persist import save_game_start
from backend.db.persist import save_snapshot_and_checkpoint
from backend.engine.game import WerewolfGame
from backend.engine.models import ActionType
from backend.engine.models import Decision
from backend.engine.models import GameState
from backend.engine.models import Player
from backend.infrastructure.messaging.match_notifications import match_notifications

logger = logging.getLogger(__name__)


def _sample_personas(count: int, seed: int | None) -> list[dict] | None:
    from backend.db.persona_db import sample_personas

    return sample_personas(count, seed=seed)


def persist_snapshot(state: GameState, *, job_id: str | None = None) -> None:
    moderator = state.snapshot(show_private=True)
    public = state.snapshot(show_private=False)
    seq = int(moderator.get("seq") or 0)
    save_snapshot_and_checkpoint(
        state.id,
        job_id=job_id,
        seq=seq,
        day=state.day,
        phase=state.phase.value,
        truth=moderator,
        public=public,
        cursor={
            "last_event_seq": seq,
            "phase": state.phase.value,
            "decision_count": len(state.decision_records),
        },
    )
    match_notifications.publish(state.id, seq)


def restore_game_from_checkpoint(game: WerewolfGame, checkpoint: dict[str, Any] | None) -> bool:
    """Restore an executable game from the latest durable moderator snapshot."""
    if not checkpoint or str(checkpoint.get("status") or "running") in {"finished", "completed"}:
        return False
    truth_state = checkpoint.get("truth_state")
    if not isinstance(truth_state, dict) or not truth_state.get("id"):
        return False
    restored = GameState.from_moderator_snapshot(truth_state)
    cursor = dict(checkpoint.get("cursor") or {})
    # The sequence is advanced while constructing a request, before the next
    # observer checkpoint. Reconcile it with the last durably confirmed count.
    restored.phase_cursor["__decision_sequence__"] = int(cursor.get("decision_count") or 0)
    game.state = restored
    return True


def build_game(
    *,
    seed: int,
    agent_type: str = "llm",
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
    phase_delay_ms: float = 0,
    max_days: int = 20,
    llm_config: dict[str, Any] | None = None,
    strategy_version: str | None = None,
    strategy_bias: dict[str, list[str]] | None = None,
    strategy_bias_by_role: dict[str, dict[str, list[str]]] | None = None,
    game_id: str | None = None,
    players=None,
    sampled_personas: list[dict] | None = None,
    agent_runtime: AgentRuntime | None = None,
    decision_replayer=None,
) -> WerewolfGame:
    runtime = agent_runtime or LocalAgentRuntime()
    game = prepare_game(
        seed=seed,
        player_count=player_count,
        rule_pack_id=rule_pack_id,
        phase_delay_ms=phase_delay_ms,
        max_days=max_days,
        game_id=game_id,
        players=players,
        sampled_personas=sampled_personas,
        strategy_version=strategy_version,
        strategy_bias=strategy_bias,
        strategy_bias_by_role=strategy_bias_by_role,
    )
    runtime_config = {"type": agent_type, "seed": seed, **(llm_config or {})}
    runtime_config.setdefault("strategy_bias", strategy_bias or {})
    if strategy_bias_by_role:
        role_models = dict(runtime_config.get("role_models") or {})
        for role, bias in strategy_bias_by_role.items():
            role_models[role] = {**dict(role_models.get(role) or {}), "strategy_bias": bias}
        runtime_config["role_models"] = role_models
    game.decision_replayer = decision_replayer
    runtime.attach(game, runtime_config)
    return game


def prepare_game(
    *,
    seed: int,
    player_count: int = 10,
    rule_pack_id: str = "wolfcha-default",
    phase_delay_ms: float = 0,
    max_days: int = 20,
    game_id: str | None = None,
    players=None,
    sampled_personas: list[dict] | None = None,
    strategy_version: str | None = None,
    strategy_bias: dict[str, list[str]] | None = None,
    strategy_bias_by_role: dict[str, dict[str, list[str]]] | None = None,
) -> WerewolfGame:
    del rule_pack_id
    init_db()
    game = WerewolfGame(
        players=players,
        seed=seed,
        player_count=player_count,
        max_days=max_days,
        phase_delay_ms=phase_delay_ms,
        sampled_personas=sampled_personas,
        strategy_version=strategy_version,
        strategy_bias=strategy_bias,
        strategy_bias_by_role=strategy_bias_by_role,
        persona_sampler=_sample_personas,
        on_game_start=save_game_start,
        on_game_end=None,
        on_event=save_event,
        on_decision_persist=save_decisions_batch,
        on_decisions_flush=save_decisions_batch,
        on_post_game=None,
        game_id=game_id,
    )
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

        def decision_replayer(request_id: str, player: Player, request: str) -> Decision | None:
            del request
            persisted = get_agent_decision_by_request_id(request_id)
            if persisted is None:
                return None
            action = dict(persisted.get("parsed_action") or {})
            try:
                action_type = ActionType(str(action.get("action_type")))
            except ValueError:
                return None
            metadata = dict(persisted.get("metadata") or {})
            metadata.update({"source": "agent_replay", "harness_request_id": request_id})
            return Decision(
                actor_id=str(persisted.get("player_id") or player.id),
                action_type=action_type,
                target_id=action.get("target_id"),
                speech=action.get("speech"),
                reasoning=str(action.get("reasoning") or "[replayed persisted decision]"),
                metadata=metadata,
            )

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
            decision_replayer=decision_replayer,
        )

        checkpoint = get_match_checkpoint(spec.match_id)
        if restore_game_from_checkpoint(game, checkpoint):
            logger.info(
                "Match %s restored from checkpoint seq=%s phase=%s",
                spec.match_id,
                checkpoint.get("seq") if checkpoint else None,
                checkpoint.get("phase") if checkpoint else None,
            )

        def observe(state: GameState) -> None:
            # Fence a worker whose lease expired while it was waiting on a
            # model request before it overwrites the next owner's checkpoint.
            self.repository.heartbeat(job.id, self.worker_id, lease_seconds=self.lease_seconds)
            persist_snapshot(state, job_id=job.id)
            control_state = self.repository.heartbeat(
                job.id,
                self.worker_id,
                lease_seconds=self.lease_seconds,
                checkpoint_seq=int(state.snapshot(show_private=True).get("seq") or 0),
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
