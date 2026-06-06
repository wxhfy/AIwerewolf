"""Personality-to-mechanics mapping for the cognitive pipeline.

Translates MindTraits into concrete numeric parameters that control
NON-LLM pipeline behavior: vote temperature, speech segment count,
suspicion gain, etc.

IMPORTANT: Personality EXPRESSION belongs in profiles.py as natural
language injected into the system prompt. This module handles only
MECHANICAL parameters — numbers that control pipeline behavior, not
words that the LLM reads.

Layer mapping:
  MBTI (prompt)  →  profiles.py → system prompt (rich NL descriptions)
  Mind (mechanical) → humanization.py → numeric parameters (pipeline config)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.agents.cognitive.profiles import MindTraits
from backend.agents.cognitive.profiles import PersonaTraits


@dataclass
class HumanizationProfile:
    """Mechanical behavioral parameters — controls pipeline, NOT LLM thinking.

    These are numeric knobs for the pipeline infrastructure:
    - speech segment count (how many bubbles per talk)
    - vote temperature (LLM sampling temperature for vote)
    - suspicion gain (how fast suspicion accumulates in memory)
    - etc.

    None of these are injected into LLM prompts. The LLM gets its
    personality from the rich MBTI descriptions in the system prompt.
    """

    vote_temperature: float  # LLM temperature for vote calls
    suspicion_gain: float  # multiplier on suspicion accumulation
    recency_weight: float  # weight on recent events vs older
    grudge_weight: float  # impact of being accused/mentioned
    follow_weight: float  # tendency to follow trusted players
    stubbornness: float  # resistance to changing opinion
    self_protection_weight: float  # self-preservation instinct
    speech_min_segments: int  # min speech bubbles per talk
    speech_max_segments: int  # max speech bubbles per talk


def build_humanization_profile(
    persona: Optional[PersonaTraits] = None,
    mind: Optional[MindTraits] = None,
) -> HumanizationProfile:
    """Derive mechanical parameters from mind traits.

    Returns sensible defaults when persona/mind are None.
    These parameters control pipeline infrastructure, not LLM behavior.
    """
    if persona is None and mind is None:
        return HumanizationProfile(
            vote_temperature=0.8,
            suspicion_gain=1.0,
            recency_weight=1.0,
            grudge_weight=0.8,
            follow_weight=0.6,
            stubbornness=0.5,
            self_protection_weight=1.0,
            speech_min_segments=2,
            speech_max_segments=3,
        )

    p = persona or PersonaTraits()
    m = mind or MindTraits()

    # ---- Courage → vote temperature + self-protection ----
    if m.courage == "bold":
        vote_temperature = 0.3
        grudge_weight = 1.5
        self_protection_weight = 0.5
    elif m.courage == "cautious":
        vote_temperature = 1.2
        grudge_weight = 0.4
        self_protection_weight = 1.5
    else:
        vote_temperature = 0.6
        grudge_weight = 0.8
        self_protection_weight = 1.0

    # ---- Memory bias → recency + stubbornness ----
    if m.memory_bias == "recent":
        recency_weight = 2.0
        stubbornness = 0.2
    elif m.memory_bias == "first_impression":
        recency_weight = 0.4
        stubbornness = 1.5
    elif m.memory_bias == "selective":
        recency_weight = 1.0
        stubbornness = 1.0
    else:
        recency_weight = 0.8
        stubbornness = 0.5

    # ---- Suspicion threshold → suspicion gain ----
    if m.suspicion_threshold == "low":
        suspicion_gain = 1.5
    elif m.suspicion_threshold == "high":
        suspicion_gain = 0.5
    else:
        suspicion_gain = 1.0

    # ---- Logic depth → speech segments ----
    if m.logic_depth == "deep":
        speech_max = 4
    elif m.logic_depth == "shallow":
        speech_max = 2
    else:
        speech_max = 3

    # ---- Table presence → speech segments + follow weight ----
    if m.table_presence == "dominant":
        speech_max = max(speech_max, 4)
        speech_min = 2
        follow_weight = 0.3
    elif m.table_presence == "quiet":
        speech_max = min(speech_max, 2)
        speech_min = 1
        follow_weight = 0.5
    else:
        speech_max = min(speech_max, 3)
        speech_min = 2
        follow_weight = 0.6

    # ---- Style label adjustments ----
    style = p.style_label or ""
    if style in ("aggressive", "provocative"):
        grudge_weight *= 1.5
        vote_temperature = max(0.15, vote_temperature - 0.2)
    elif style in ("analytical", "meticulous"):
        suspicion_gain *= 0.8
        speech_max = max(speech_max, 3)
    elif style == "observant":
        speech_max = min(speech_max, 2)
        speech_min = min(speech_min, 1)
    elif style in ("persuasive",):
        follow_weight *= 0.6

    return HumanizationProfile(
        vote_temperature=round(vote_temperature, 2),
        suspicion_gain=round(suspicion_gain, 2),
        recency_weight=round(recency_weight, 2),
        grudge_weight=round(grudge_weight, 2),
        follow_weight=round(follow_weight, 2),
        stubbornness=round(stubbornness, 2),
        self_protection_weight=round(self_protection_weight, 2),
        speech_min_segments=speech_min,
        speech_max_segments=speech_max,
    )
