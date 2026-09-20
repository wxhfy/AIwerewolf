from __future__ import annotations

from typing import Protocol
from typing import TypeVar

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessResult
from backend.game_runtime.contracts import EnvironmentAdapter
from backend.game_runtime.contracts import EpisodeOutcome

StateT = TypeVar("StateT")


class DecisionRuntime(Protocol):
    def run(self, request: DecisionRequest) -> HarnessResult: ...


class EpisodeRuntimeError(RuntimeError):
    pass


class EpisodeRunner:
    """Drives an environment while keeping simultaneous actions sealed."""

    def __init__(self, runtime: DecisionRuntime, *, max_transitions: int = 10_000) -> None:
        if max_transitions < 1:
            raise ValueError("max_transitions must be positive")
        self.runtime = runtime
        self.max_transitions = max_transitions

    def run(self, adapter: EnvironmentAdapter[StateT], initial_state: StateT) -> EpisodeOutcome[StateT]:
        state = initial_state
        transitions = 0
        decision_count = 0

        while not adapter.is_terminal(state):
            if transitions >= self.max_transitions:
                raise EpisodeRuntimeError("Episode transition budget exhausted")

            batch = adapter.next_decision_batch(state)
            actions = []
            for request in batch.requests:
                result = self.runtime.run(request)
                if result.status != "completed" or result.action is None:
                    raise EpisodeRuntimeError(
                        f"Decision {request.request_id} did not complete: {result.error or result.status}"
                    )
                actions.append(result.action)

            # No action is applied until the complete batch has resolved. This
            # prevents later actors in a simultaneous phase from seeing earlier choices.
            state = adapter.apply_actions(state, batch, tuple(actions))
            transitions += 1
            decision_count += len(actions)

        return EpisodeOutcome(
            final_state=state,
            transitions=transitions,
            decision_count=decision_count,
        )
