"""Personality-to-behavior mapping layer.

Translates the existing Persona + PlayerMind system into concrete numeric
parameters that shape how an agent votes, speaks, remembers, and reacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from backend.agents.characters import Character


@dataclass
class HumanizationProfile:
    """Numeric behavioral parameters derived from a character's personality."""

    vote_temperature: float  # softmax temperature for vote selection
    suspicion_gain: float  # multiplier on suspicion deltas
    recency_weight: float  # weight on recent events vs older
    grudge_weight: float  # how much being mentioned/accused matters
    follow_weight: float  # tendency to follow trusted players' reads
    stubbornness: float  # resistance to changing opinion
    self_protection_weight: float  # how much self-preservation matters
    speech_min_segments: int  # minimum speech bubbles per talk
    speech_max_segments: int  # maximum speech bubbles per talk
    analysis_depth: str  # "shallow" | "moderate" | "deep"
    risk_appetite: str  # "low" | "medium" | "high"
    uncertainty_style: str  # "admit" | "deflect" | "overcompensate"


def build_humanization_profile(character: Character | None) -> HumanizationProfile:
    """Derive behavioral parameters from a character's Persona and PlayerMind.

    Returns sensible defaults when character is None.
    """
    if character is None:
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
            analysis_depth="moderate",
            risk_appetite="medium",
            uncertainty_style="admit",
        )

    p = character.persona
    m = character.mind

    # ---- Base values from PlayerMind ----
    courage = m.courage
    if courage == "bold":
        vote_temperature = 0.3
        grudge_weight = 1.5
        self_protection_weight = 0.5
        risk_appetite = "high"
    elif courage == "cautious":
        vote_temperature = 1.2
        grudge_weight = 0.4
        self_protection_weight = 1.5
        risk_appetite = "low"
    else:  # "calculated"
        vote_temperature = 0.6
        grudge_weight = 0.8
        self_protection_weight = 1.0
        risk_appetite = "medium"

    memory = m.memory_bias
    if memory == "recent":
        recency_weight = 2.0
        stubbornness = 0.2
    elif memory == "first_impression":
        recency_weight = 0.4
        stubbornness = 1.5
    elif memory == "selective":
        recency_weight = 1.0
        stubbornness = 1.0
    else:  # "comprehensive"
        recency_weight = 0.8
        stubbornness = 0.5

    threshold = m.suspicion_threshold
    if threshold == "low":
        suspicion_gain = 1.5
    elif threshold == "high":
        suspicion_gain = 0.5
    else:  # "medium"
        suspicion_gain = 1.0

    logic = m.logic_depth
    if logic == "deep":
        speech_max = 4
        analysis_depth = "deep"
    elif logic == "shallow":
        speech_max = 2
        analysis_depth = "shallow"
    else:  # "moderate"
        speech_max = 3
        analysis_depth = "moderate"

    presence = m.table_presence
    if presence == "dominant":
        speech_max = max(speech_max, 4)
        speech_min = 2
        follow_weight = 0.3
    elif presence == "quiet":
        speech_max = min(speech_max, 2)
        speech_min = 1
        follow_weight = 0.5
    else:  # "balanced"
        speech_max = min(speech_max, 3)
        speech_min = 2
        follow_weight = 0.6

    uncertainty = p.uncertainty_style or "admit"

    # ---- Adjust by persona style_label ----
    style = p.style_label or ""
    if style in ("aggressive", "provocative"):
        grudge_weight *= 1.5
        vote_temperature = max(0.15, vote_temperature - 0.2)
    elif style in ("analytical", "meticulous"):
        suspicion_gain *= 0.8
        analysis_depth = "deep"
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
        analysis_depth=analysis_depth,
        risk_appetite=risk_appetite,
        uncertainty_style=uncertainty,
    )


def build_stance_summary(
    public_stance: dict[str, Any],
    player_id: str,
    view: Any = None,
) -> str:
    """Build a concise Chinese text summary of the agent's current stances.

    Used to inject into heuristic speech context and LLM prompts.
    """
    suspects = public_stance.get("suspects", {})
    trusted = public_stance.get("trusted", {})
    grudges = public_stance.get("grudges", {})
    last_vote = public_stance.get("last_vote_target")
    tunnel = public_stance.get("tunnel_target")

    lines: list[str] = []

    # Suspects
    if suspects:
        suspect_strs = []
        for pid, info in sorted(suspects.items(), key=lambda x: -x[1].get("score", 0)):
            reason = info.get("reason", "?")
            day = info.get("day", "?")
            tag = _resolve_tag(pid, view)
            suspect_strs.append(f"{tag}({reason}，第{day}天)")
        if suspect_strs:
            lines.append("你当前怀疑：" + " | ".join(suspect_strs[:3]))

    # Trusted
    if trusted:
        trust_strs = []
        for pid, info in sorted(trusted.items(), key=lambda x: -x[1].get("score", 0)):
            reason = info.get("reason", "?")
            tag = _resolve_tag(pid, view)
            trust_strs.append(f"{tag}({reason})")
        if trust_strs:
            lines.append("你当前信任：" + " | ".join(trust_strs[:3]))

    # Last vote
    if last_vote:
        tag = _resolve_tag(last_vote, view)
        lines.append(f"上一轮你投了：{tag}")

    # Grudges (who pointed at me)
    if grudges:
        grudge_strs = []
        for pid, score in sorted(grudges.items(), key=lambda x: -x[1]):
            tag = _resolve_tag(pid, view)
            grudge_strs.append(tag)
        if grudge_strs:
            lines.append("点过你的人：" + "、".join(grudge_strs[:3]))

    # Tunnel
    if tunnel:
        tag = _resolve_tag(tunnel, view)
        lines.append(f"你一直盯着：{tag}（有新事实可以松动）")

    return "\n".join(lines) if lines else "（暂无明确立场）"


def _resolve_tag(player_id: str, view: Any = None) -> str:
    """Resolve a player_id to @N号:名字 format if view is available."""
    if view is None:
        return player_id
    try:
        for p in view.players:
            if p.get("id") == player_id:
                seat = p.get("seat", "?")
                name = p.get("name", "?")
                return f"@{seat}号:{name}"
    except Exception:
        pass
    return player_id
