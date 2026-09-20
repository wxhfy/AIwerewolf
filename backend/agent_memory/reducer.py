from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_memory.config import CognitiveDynamics
from backend.agent_memory.config import derive_dynamics
from backend.agent_memory.config import load_memory_settings
from backend.agent_memory.models import ActorMemoryState
from backend.agent_memory.models import BeliefState
from backend.agent_memory.models import EpisodicMemory
from backend.agent_memory.models import GoalState
from backend.agent_memory.models import RelationshipState

_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class CognitiveMemoryReducer:
    """Deterministically update subjective memory from actor-visible events."""

    def __init__(self) -> None:
        self.settings = load_memory_settings()

    def dynamics(self, state: ActorMemoryState, request: DecisionRequest) -> CognitiveDynamics:
        return derive_dynamics(self.settings, request.agent_profile, state.affect)

    def update(self, state: ActorMemoryState, request: DecisionRequest) -> None:
        observation = request.information_state.observation
        day = int(observation.get("day") or request.domain_metadata.get("day") or 0)
        if state.last_day and day > state.last_day:
            self._decay_between_days(state, day - state.last_day, self.dynamics(state, request))
        state.last_day = max(state.last_day, day)
        self._ensure_social_models(state, request)

        events = sorted(
            (
                event
                for event in request.information_state.visible_history
                if int(event.get("seq") or 0) > state.last_event_seq
            ),
            key=lambda event: int(event.get("seq") or 0),
        )
        for event in events:
            self._apply_event(state, request, event, self.dynamics(state, request))
            state.last_event_seq = max(state.last_event_seq, int(event.get("seq") or 0))

        self._refresh_goals(state, request)
        dynamics = self.dynamics(state, request)
        self._refresh_working_memory(state, dynamics)
        state.episodic = state.episodic[-self.settings.limits.episodic_capacity :]
        state.affect.normalize()

    def retrieved(self, state: ActorMemoryState, request: DecisionRequest) -> list[EpisodicMemory]:
        query = self._query_terms(request)
        memory_bias = str(request.agent_profile.get("persona", {}).get("memory_bias") or "comprehensive")
        current_seq = max(state.last_event_seq, 1)
        dynamics = self.dynamics(state, request)
        weights = dynamics.retrieval_weights

        def score(memory: EpisodicMemory) -> float:
            age = max(0, current_seq - memory.event_seq)
            recency = 1.0 / (1.0 + age / 8.0)
            relevance = self._overlap(query, self._tokens(memory.content + " " + " ".join(memory.tags)))
            unresolved = 1.0 if any(
                goal.status == "active" and goal.target_player_id in memory.actor_ids for goal in state.goals
            ) else 0.0
            emotional = min(1.0, abs(memory.valence))
            if memory_bias == "first_impression":
                recency = max(recency, 1.0 / (1.0 + memory.event_seq / max(1, current_seq)))
            return (
                weights["importance"] * memory.importance
                + weights["relevance"] * relevance
                + weights["recency"] * recency
                + weights["goal"] * unresolved
                + weights["emotion"] * emotional
            )

        ranked = sorted(state.episodic, key=lambda item: (score(item), item.event_seq), reverse=True)
        return ranked[: dynamics.retrieved_episode_limit]

    def prompt_snapshot(
        self,
        state: ActorMemoryState,
        request: DecisionRequest,
        retrieved: list[EpisodicMemory],
    ) -> dict[str, Any]:
        beliefs = sorted(
            state.beliefs.values(),
            key=lambda item: (abs(item.wolf_probability - 0.5) * item.confidence, item.player_id),
            reverse=True,
        )
        relationships = sorted(
            state.relationships.values(),
            key=lambda item: (max(abs(item.trust), item.threat, item.influence), item.player_id),
            reverse=True,
        )
        dynamics = self.dynamics(state, request)
        return {
            "working_memory": list(state.working_memory),
            "beliefs": [asdict(item) for item in beliefs[:8]],
            "relationships": [asdict(item) for item in relationships[:8]],
            "affect": asdict(state.affect),
            "active_goals": [asdict(item) for item in state.goals if item.status == "active"][:4],
            "retrieved_episodes": [asdict(item) for item in retrieved],
            "last_action": dict(state.last_action),
            "memory_policy": {
                "version": self.settings.version,
                "raw_event_window": dynamics.recent_event_limit,
                "retrieved_episode_limit": dynamics.retrieved_episode_limit,
                "working_memory_limit": dynamics.working_chunk_limit,
                "retrieval_weights": dynamics.retrieval_weights,
                "subjective": True,
            },
            "decision_kind": request.decision_point.kind,
        }

    def record_action(self, state: ActorMemoryState, request: DecisionRequest, action: Any) -> None:
        parameters = dict(getattr(action, "parameters", {}) or {})
        response = dict(getattr(action, "response", {}) or {})
        reasoning = str(getattr(action, "reasoning", "") or "")[:500]
        action_type = str(getattr(action, "action_type", ""))
        target_id = str(parameters.get("target_id") or parameters.get("poison_target_id") or "") or None
        state.last_action = {
            "sequence": request.decision_point.sequence,
            "day": request.domain_metadata.get("day"),
            "phase": request.domain_metadata.get("phase"),
            "action_type": action_type,
            "target_id": target_id,
            "response": response,
            "reasoning": reasoning,
        }
        content = f"I chose {action_type}"
        if target_id:
            content += f" targeting {target_id}"
        if reasoning:
            content += f" because {reasoning}"
        state.episodic.append(
            EpisodicMemory(
                memory_id=f"decision:{request.request_id}",
                event_seq=state.last_event_seq,
                day=int(request.domain_metadata.get("day") or 0),
                phase=str(request.domain_metadata.get("phase") or ""),
                kind="self_action",
                content=content[:1000],
                source="self",
                importance=self.settings.event_salience["self_action"],
                confidence=state.affect.confidence,
                actor_ids=[target_id] if target_id else [],
                tags=["self_action", action_type],
            )
        )
        dynamics = self.dynamics(state, request)
        self._refresh_working_memory(state, dynamics)
        state.episodic = state.episodic[-self.settings.limits.episodic_capacity :]

    def _ensure_social_models(self, state: ActorMemoryState, request: DecisionRequest) -> None:
        observation = request.information_state.observation
        known_wolves = {str(item.get("id")) for item in observation.get("known_wolves") or []}
        for player in observation.get("players") or []:
            player_id = str(player.get("id") or "")
            if not player_id or player_id == state.actor_id:
                continue
            belief = state.beliefs.setdefault(player_id, BeliefState(player_id=player_id))
            relation = state.relationships.setdefault(player_id, RelationshipState(player_id=player_id))
            if player_id in known_wolves:
                belief.wolf_probability = 1.0
                belief.confidence = 1.0
                belief.evidence_for = ["Known teammate from role-private information"]
                relation.trust = max(relation.trust, 0.75)
                relation.closeness = max(relation.closeness, 0.5)
                belief.normalize()
                relation.normalize()

    def _apply_event(
        self,
        state: ActorMemoryState,
        request: DecisionRequest,
        event: dict[str, Any],
        dynamics: CognitiveDynamics,
    ) -> None:
        payload = dict(event.get("payload") or {})
        event_type = str(event.get("type") or "")
        seq = int(event.get("seq") or 0)
        day = int(event.get("day") or 0)
        phase = str(event.get("phase") or "")
        source = "private" if event.get("visibility") == "private" else "public"
        content, importance, valence, actor_ids, tags = self._event_memory(event_type, payload, state.actor_id)
        if content:
            state.episodic.append(
                EpisodicMemory(
                    memory_id=str(event.get("id") or f"event:{seq}"),
                    event_seq=seq,
                    day=day,
                    phase=phase,
                    kind=event_type.lower(),
                    content=content[:1200],
                    source=source,
                    importance=importance,
                    valence=valence,
                    actor_ids=actor_ids,
                    tags=tags,
                )
            )

        if event_type == "PRIVATE_INFO" and payload.get("kind") == "seer_result":
            target_id = str(payload.get("target_id") or "")
            if target_id:
                belief = state.beliefs.setdefault(target_id, BeliefState(player_id=target_id))
                is_wolf = bool(payload.get("is_wolf"))
                belief.wolf_probability = 0.99 if is_wolf else 0.01
                belief.confidence = 1.0
                evidence = f"Private divine result: {payload.get('target_name') or target_id} is {'wolf' if is_wolf else 'not wolf'}"
                (belief.evidence_for if is_wolf else belief.evidence_against).append(evidence)
                belief.last_updated_seq = seq
                belief.normalize()
                response = self.settings.dynamics["event_response_scale"] * dynamics.emotional_sensitivity
                state.affect.confidence += response
                state.affect.dominance += response / 2

        if event_type == "VOTE_CAST":
            voter_id = str(payload.get("voter_id") or "")
            target_id = str(payload.get("target_id") or "")
            if target_id == state.actor_id and voter_id and voter_id != state.actor_id:
                relation = state.relationships.setdefault(voter_id, RelationshipState(player_id=voter_id))
                response = self.settings.dynamics["event_response_scale"] * dynamics.social_sensitivity
                relation.trust -= response
                relation.threat += response
                relation.perceived_attitude -= response
                relation.last_updated_seq = seq
                relation.normalize()
                emotional = self.settings.dynamics["event_response_scale"] * dynamics.emotional_sensitivity
                state.affect.social_pressure += emotional
                state.affect.arousal += emotional * 0.75
                state.affect.fear += emotional * 0.5
                state.affect.valence -= emotional * 0.5

        if event_type == "CHAT_MESSAGE":
            actor_id = str(payload.get("actor_id") or "")
            speech = str(payload.get("speech") or "")
            self_name = str(request.information_state.observation.get("self_player", {}).get("name") or "")
            if actor_id and actor_id != state.actor_id and self_name and self_name in speech:
                relation = state.relationships.setdefault(actor_id, RelationshipState(player_id=actor_id))
                response = self.settings.dynamics["event_response_scale"] * dynamics.social_sensitivity
                relation.influence += response * 0.35
                relation.last_updated_seq = seq
                relation.normalize()
                state.affect.social_pressure += response * dynamics.emotional_sensitivity * 0.25

        if event_type == "PLAYER_DIED":
            response = self.settings.dynamics["event_response_scale"] * dynamics.emotional_sensitivity
            state.affect.fear += response
            state.affect.arousal += response * 0.7
            state.affect.valence -= response * 0.6

    def _event_memory(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor_id: str,
    ) -> tuple[str, float, float, list[str], list[str]]:
        if event_type == "CHAT_MESSAGE":
            speaker = str(payload.get("actor_name") or payload.get("actor_id") or "Unknown")
            speech = str(payload.get("speech") or "").strip()
            return (
                f"{speaker} said: {speech}" if speech else "",
                self.settings.event_salience["speech"],
                0.0,
                [str(payload.get("actor_id") or "")],
                ["speech"],
            )
        if event_type == "VOTE_CAST":
            voter = str(payload.get("voter_name") or payload.get("voter_id") or "Unknown")
            target = str(payload.get("target_name") or payload.get("target_id") or "Unknown")
            ids = [str(item) for item in (payload.get("voter_id"), payload.get("target_id")) if item]
            valence = -self.settings.dynamics["event_response_scale"] if payload.get("target_id") == actor_id else 0.0
            return f"{voter} voted for {target}", self.settings.event_salience["vote"], valence, ids, ["vote"]
        if event_type == "PLAYER_DIED":
            player = str(payload.get("player_name") or payload.get("player_id") or "Unknown")
            return (
                f"{player} died ({payload.get('reason') or 'unknown cause'})",
                self.settings.event_salience["death"],
                -self.settings.event_salience["death"] / 2,
                [str(payload.get("player_id") or "")],
                ["death"],
            )
        if event_type == "PRIVATE_INFO":
            kind = str(payload.get("kind") or "private_information")
            message = str(payload.get("message") or "").strip()
            if kind == "seer_result":
                target = str(payload.get("target_name") or payload.get("target_id") or "Unknown")
                message = f"My divine result says {target} is {'wolf' if payload.get('is_wolf') else 'not wolf'}"
            ids = [str(item) for item in (payload.get("actor_id"), payload.get("target_id")) if item]
            importance = self.settings.event_salience[
                "role_certainty" if kind in {"role_assignment", "seer_result"} else "private_information"
            ]
            return message or f"Private information: {kind}", importance, importance / 10, ids, ["private", kind]
        if event_type in {"HUNTER_SHOT", "WHITE_WOLF_KING_BOOM", "GAME_END"}:
            importance = self.settings.event_salience["decisive_action"]
            return str(payload.get("message") or payload), importance, -importance / 3, [], [event_type.lower()]
        return "", 0.0, 0.0, [], []

    def _refresh_goals(self, state: ActorMemoryState, request: DecisionRequest) -> None:
        role = str(request.domain_metadata.get("role") or "")
        day = int(request.domain_metadata.get("day") or 0)
        base = {
            "Werewolf": "Protect the wolf team while steering public suspicion toward non-wolves.",
            "WhiteWolfKing": "Protect the wolf team and preserve a high-impact self-detonation opportunity.",
            "Seer": "Convert private checks into credible public information without wasting future checks.",
            "Witch": "Preserve limited medicine and use it only when its expected impact is high.",
            "Guard": "Protect likely village power while avoiding an illegal repeated guard.",
            "Hunter": "Build a reliable target model in case a shot becomes available.",
            "Idiot": "Help the village while managing the risk of being voted out.",
            "Villager": "Identify wolves through claims, votes, consistency, and social behavior.",
        }.get(role, "Advance the objectives of my alignment using only information visible to me.")
        decision_goal = f"Make a coherent {request.decision_point.kind} decision from current evidence."
        state.goals = [
            GoalState("role-objective", base, 1.0, created_day=0),
            GoalState("current-decision", decision_goal, 0.9, created_day=day, expires_day=day),
        ]

    def _refresh_working_memory(self, state: ActorMemoryState, dynamics: CognitiveDynamics) -> None:
        chunks: list[str] = []
        strong_beliefs = sorted(
            state.beliefs.values(),
            key=lambda item: abs(item.wolf_probability - 0.5) * item.confidence,
            reverse=True,
        )
        for belief in strong_beliefs[:2]:
            if belief.confidence >= 0.25:
                chunks.append(
                    f"Belief about {belief.player_id}: wolf_probability={belief.wolf_probability:.2f}, confidence={belief.confidence:.2f}"
                )
        threats = sorted(state.relationships.values(), key=lambda item: item.threat, reverse=True)
        if threats and threats[0].threat >= 0.15:
            chunks.append(f"Social threat: {threats[0].player_id} threat={threats[0].threat:.2f}")
        private = [memory for memory in reversed(state.episodic) if memory.source == "private"]
        if private:
            chunks.append(f"Important private fact: {private[0].content}")
        for goal in state.goals:
            if goal.status == "active":
                chunks.append(f"Goal: {goal.description}")
        if state.last_action:
            chunks.append(f"Previous action: {state.last_action.get('action_type')} {state.last_action.get('target_id') or ''}".strip())
        state.working_memory = chunks[: dynamics.working_chunk_limit]

    @staticmethod
    def _decay_between_days(
        state: ActorMemoryState,
        elapsed_days: int,
        dynamics: CognitiveDynamics,
    ) -> None:
        factor = dynamics.day_decay**max(1, elapsed_days)
        state.affect.arousal *= factor
        state.affect.fear *= factor
        state.affect.anger *= factor
        state.affect.social_pressure *= factor
        state.affect.valence *= factor
        for relation in state.relationships.values():
            relation.threat *= dynamics.social_decay**elapsed_days
            relation.perceived_attitude *= dynamics.social_decay**elapsed_days
            relation.normalize()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.lower() for token in _WORD_RE.findall(text) if len(token) > 1}

    def _query_terms(self, request: DecisionRequest) -> set[str]:
        observation = request.information_state.observation
        text = " ".join(
            [
                request.decision_point.kind,
                str(request.domain_metadata.get("role") or ""),
                str(request.domain_metadata.get("phase") or ""),
                " ".join(str(item.get("name") or item.get("id") or "") for item in observation.get("legal_targets") or []),
            ]
        )
        return self._tokens(text)

    @staticmethod
    def _overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, len(left | right))
