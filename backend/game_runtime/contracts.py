from __future__ import annotations

from dataclasses import dataclass
from typing import Generic
from typing import Literal
from typing import Protocol
from typing import TypeVar

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import ResolvedAction

StateT = TypeVar("StateT")


@dataclass(frozen=True)
class DecisionBatch:
    """One sequential decision or a sealed set of simultaneous decisions."""

    batch_id: str
    mode: Literal["sequential", "simultaneous"]
    requests: tuple[DecisionRequest, ...]

    def __post_init__(self) -> None:
        if not self.requests:
            raise ValueError("Decision batch cannot be empty")
        if self.mode not in {"sequential", "simultaneous"}:
            raise ValueError(f"Unsupported decision batch mode: {self.mode}")
        if self.mode == "sequential" and len(self.requests) != 1:
            raise ValueError("Sequential decision batches must contain exactly one request")
        if self.mode == "simultaneous":
            group_ids = {request.decision_point.simultaneous_group_id for request in self.requests}
            if None in group_ids or len(group_ids) != 1:
                raise ValueError("Simultaneous requests must share a non-empty group ID")
        request_ids = [request.request_id for request in self.requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("Decision request IDs must be unique within a batch")
        actor_ids = [request.actor.actor_id for request in self.requests]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("An actor can appear only once within a decision batch")
        environment_ids = {request.environment_id for request in self.requests}
        if len(environment_ids) != 1:
            raise ValueError("Decision batch cannot mix environments")
        episode_ids = {request.episode_id for request in self.requests}
        if len(episode_ids) != 1:
            raise ValueError("Decision batch cannot mix episodes")


class EnvironmentAdapter(Protocol[StateT]):
    """Domain seam between a full hidden state and actor-scoped decisions."""

    def is_terminal(self, state: StateT) -> bool: ...

    def next_decision_batch(self, state: StateT) -> DecisionBatch: ...

    def apply_actions(
        self,
        state: StateT,
        batch: DecisionBatch,
        actions: tuple[ResolvedAction, ...],
    ) -> StateT: ...


@dataclass(frozen=True)
class EpisodeOutcome(Generic[StateT]):
    final_state: StateT
    transitions: int
    decision_count: int
