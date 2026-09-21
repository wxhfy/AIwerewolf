from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


@dataclass
class EpisodicMemory:
    memory_id: str
    event_seq: int
    day: int
    phase: str
    kind: str
    content: str
    source: str
    importance: float
    confidence: float = 1.0
    valence: float = 0.0
    actor_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class BeliefState:
    player_id: str
    wolf_probability: float = 0.5
    confidence: float = 0.1
    evidence_for: list[str] = field(default_factory=list)
    evidence_against: list[str] = field(default_factory=list)
    last_updated_seq: int = 0

    def normalize(self) -> None:
        self.wolf_probability = _clamp(self.wolf_probability, 0.0, 1.0)
        self.confidence = _clamp(self.confidence, 0.0, 1.0)
        self.evidence_for = self.evidence_for[-6:]
        self.evidence_against = self.evidence_against[-6:]


@dataclass
class RelationshipState:
    player_id: str
    trust: float = 0.0
    closeness: float = 0.0
    threat: float = 0.0
    influence: float = 0.0
    perceived_attitude: float = 0.0
    last_updated_seq: int = 0

    def normalize(self) -> None:
        for name in ("trust", "closeness", "threat", "influence", "perceived_attitude"):
            setattr(self, name, _clamp(getattr(self, name)))


@dataclass
class AffectiveState:
    valence: float = 0.0
    arousal: float = 0.2
    dominance: float = 0.5
    fear: float = 0.1
    anger: float = 0.0
    confidence: float = 0.5
    social_pressure: float = 0.0

    def normalize(self) -> None:
        self.valence = _clamp(self.valence)
        for name in ("arousal", "dominance", "fear", "anger", "confidence", "social_pressure"):
            setattr(self, name, _clamp(getattr(self, name), 0.0, 1.0))


@dataclass
class GoalState:
    goal_id: str
    description: str
    priority: float
    status: str = "active"
    target_player_id: str | None = None
    created_day: int = 0
    expires_day: int | None = None


@dataclass
class SpeechClaim:
    claim_id: str
    event_seq: int
    speaker_id: str
    kind: str
    target_id: str | None
    value: str
    polarity: float
    confidence: float
    evidence_text: str
    contradicted: bool = False
    retracted: bool = False


@dataclass
class EvidenceEdge:
    edge_id: str
    event_seq: int
    source_player_id: str
    target_player_id: str
    relation: str
    weight: float
    confidence: float
    evidence_text: str


@dataclass
class ActorMemoryState:
    episode_id: str
    actor_id: str
    version: int = 1
    last_event_seq: int = 0
    last_day: int = 0
    working_memory: list[str] = field(default_factory=list)
    episodic: list[EpisodicMemory] = field(default_factory=list)
    beliefs: dict[str, BeliefState] = field(default_factory=dict)
    relationships: dict[str, RelationshipState] = field(default_factory=dict)
    affect: AffectiveState = field(default_factory=AffectiveState)
    goals: list[GoalState] = field(default_factory=list)
    claims: list[SpeechClaim] = field(default_factory=list)
    evidence_graph: list[EvidenceEdge] = field(default_factory=list)
    last_action: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ActorMemoryState:
        state = cls(
            episode_id=str(value.get("episode_id") or ""),
            actor_id=str(value.get("actor_id") or ""),
            version=int(value.get("version") or 1),
            last_event_seq=int(value.get("last_event_seq") or 0),
            last_day=int(value.get("last_day") or 0),
            working_memory=[str(item) for item in value.get("working_memory") or []],
            episodic=[EpisodicMemory(**item) for item in value.get("episodic") or []],
            beliefs={key: BeliefState(**item) for key, item in (value.get("beliefs") or {}).items()},
            relationships={key: RelationshipState(**item) for key, item in (value.get("relationships") or {}).items()},
            affect=AffectiveState(**(value.get("affect") or {})),
            goals=[GoalState(**item) for item in value.get("goals") or []],
            claims=[SpeechClaim(**item) for item in value.get("claims") or []],
            evidence_graph=[EvidenceEdge(**item) for item in value.get("evidence_graph") or []],
            last_action=dict(value.get("last_action") or {}),
        )
        state.affect.normalize()
        return state
