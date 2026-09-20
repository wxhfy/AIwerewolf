from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MemoryLimits:
    episodic_capacity: int
    recent_event_base: int
    retrieved_episode_base: int
    working_chunk_base: int
    minimum: int
    maximum: int


@dataclass(frozen=True)
class MemorySettings:
    version: str
    limits: MemoryLimits
    event_salience: dict[str, float]
    trait_levels: dict[str, float]
    retrieval_baseline: dict[str, float]
    dynamics: dict[str, float]

    def trait(self, value: Any, default: float = 0.5) -> float:
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        return float(self.trait_levels.get(str(value or "").strip().lower(), default))


def load_memory_settings(path: Path | None = None) -> MemorySettings:
    config_path = path or Path(__file__).resolve().parents[2] / "configs" / "cognitive_memory.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    limits = raw.get("limits") or {}
    return MemorySettings(
        version=str(raw.get("version") or "cognitive-memory-v1"),
        limits=MemoryLimits(
            episodic_capacity=int(limits.get("episodic_capacity", 96)),
            recent_event_base=int(limits.get("recent_event_base", 10)),
            retrieved_episode_base=int(limits.get("retrieved_episode_base", 5)),
            working_chunk_base=int(limits.get("working_chunk_base", 5)),
            minimum=int(limits.get("minimum", 3)),
            maximum=int(limits.get("maximum", 12)),
        ),
        event_salience={key: float(value) for key, value in (raw.get("event_salience") or {}).items()},
        trait_levels={key: float(value) for key, value in (raw.get("trait_levels") or {}).items()},
        retrieval_baseline={key: float(value) for key, value in (raw.get("retrieval_baseline") or {}).items()},
        dynamics={key: float(value) for key, value in (raw.get("dynamics") or {}).items()},
    )


@dataclass(frozen=True)
class CognitiveDynamics:
    recent_event_limit: int
    retrieved_episode_limit: int
    working_chunk_limit: int
    retrieval_weights: dict[str, float]
    social_sensitivity: float
    emotional_sensitivity: float
    day_decay: float
    social_decay: float


def derive_dynamics(settings: MemorySettings, profile: dict[str, Any], affect: Any) -> CognitiveDynamics:
    persona = dict(profile.get("persona") or {})
    logic = settings.trait(persona.get("logic_depth"))
    suspicion = settings.trait(persona.get("suspicion_threshold"))
    protection = settings.trait(persona.get("self_protection"))
    courage = settings.trait(persona.get("courage"))
    pressure = settings.trait(persona.get("pressure_style"))
    memory_bias = str(persona.get("memory_bias") or "comprehensive")
    trait_influence = settings.dynamics["trait_influence"]
    affect_influence = settings.dynamics["affect_influence"]

    weights = dict(settings.retrieval_baseline)
    weights["relevance"] *= 1.0 + logic * trait_influence
    weights["goal"] *= 1.0 + (logic + courage) * trait_influence / 2
    weights["emotion"] *= 1.0 + (float(affect.arousal) + float(affect.fear)) * affect_influence
    weights["recency"] *= 1.0 + float(affect.arousal) * affect_influence
    if memory_bias == "recent":
        weights["recency"] *= 1.0 + trait_influence
    elif memory_bias == "first_impression":
        weights["importance"] *= 1.0 + trait_influence / 2
    elif memory_bias == "selective":
        weights["relevance"] *= 1.0 + trait_influence
    elif memory_bias == "comprehensive":
        weights["importance"] *= 1.0 + trait_influence / 3
        weights["goal"] *= 1.0 + trait_influence / 3
    total = sum(weights.values()) or 1.0
    weights = {key: value / total for key, value in weights.items()}

    attention_factor = 0.75 + logic * 0.45 + (1.0 - float(affect.arousal)) * 0.2
    if memory_bias == "comprehensive":
        attention_factor += 0.2
    elif memory_bias == "selective":
        attention_factor -= 0.1
    minimum = settings.limits.minimum
    maximum = settings.limits.maximum

    def bounded(base: int, factor: float) -> int:
        return max(minimum, min(maximum, round(base * factor)))

    social_sensitivity = 0.65 + (1.0 - suspicion) * 0.45 + protection * 0.25
    emotional_sensitivity = 0.55 + pressure * 0.35 + (1.0 - courage) * 0.25
    day_decay = settings.dynamics["day_decay_base"] + (0.04 if memory_bias == "comprehensive" else 0.0)
    social_decay = settings.dynamics["social_decay_base"] + closeness_retention(memory_bias)
    return CognitiveDynamics(
        recent_event_limit=bounded(settings.limits.recent_event_base, attention_factor),
        retrieved_episode_limit=bounded(settings.limits.retrieved_episode_base, attention_factor),
        working_chunk_limit=bounded(settings.limits.working_chunk_base, attention_factor),
        retrieval_weights=weights,
        social_sensitivity=social_sensitivity,
        emotional_sensitivity=emotional_sensitivity,
        day_decay=min(0.99, day_decay),
        social_decay=min(0.99, social_decay),
    )


def closeness_retention(memory_bias: str) -> float:
    return {
        "recent": -0.02,
        "first_impression": 0.03,
        "selective": 0.0,
        "comprehensive": 0.02,
    }.get(memory_bias, 0.0)
