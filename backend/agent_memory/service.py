from __future__ import annotations

import threading
from dataclasses import replace
from typing import Protocol

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessResult
from backend.agent_harness.contracts import InformationState
from backend.agent_memory.models import ActorMemoryState
from backend.agent_memory.reducer import CognitiveMemoryReducer


class ActorMemoryRepository(Protocol):
    def load(self, episode_id: str, actor_id: str) -> ActorMemoryState | None: ...
    def save(self, state: ActorMemoryState) -> None: ...


class ActorMemoryService:
    """Own actor memory lifecycle without exposing persistence to the model."""

    def __init__(self, repository: ActorMemoryRepository | None = None) -> None:
        self.repository = repository
        self.reducer = CognitiveMemoryReducer()
        self._states: dict[tuple[str, str], ActorMemoryState] = {}
        self._lock = threading.RLock()

    def prepare(self, request: DecisionRequest) -> DecisionRequest:
        with self._lock:
            state = self._state(request)
            self.reducer.update(state, request)
            retrieved = self.reducer.retrieved(state, request)
            memory = self.reducer.prompt_snapshot(state, request, retrieved)
            recent_limit = self.reducer.dynamics(state, request).recent_event_limit
            recent = tuple(request.information_state.visible_history[-recent_limit:])
            prepared = replace(
                request,
                information_state=InformationState(
                    schema_id=request.information_state.schema_id,
                    schema_version=request.information_state.schema_version,
                    observation=request.information_state.observation,
                    visible_history=recent,
                    private_memory=(memory,),
                ),
            )
            return prepared

    def record_result(self, request: DecisionRequest, result: HarnessResult) -> None:
        with self._lock:
            state = self._state(request)
            if result.status == "completed" and result.action is not None:
                self.reducer.record_action(state, request, result.action)
            self._save(state)

    def get_state(self, episode_id: str, actor_id: str) -> ActorMemoryState | None:
        with self._lock:
            return self._states.get((episode_id, actor_id))

    def _state(self, request: DecisionRequest) -> ActorMemoryState:
        key = (request.episode_id, request.actor.actor_id)
        state = self._states.get(key)
        if state is not None:
            return state
        if self.repository is not None:
            state = self.repository.load(*key)
        if state is None:
            state = ActorMemoryState(episode_id=key[0], actor_id=key[1])
        self._states[key] = state
        return state

    def _save(self, state: ActorMemoryState) -> None:
        if self.repository is not None:
            self.repository.save(state)
