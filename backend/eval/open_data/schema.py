"""Canonical schemas for Track B open-data reconstruction.

Every sample from an external dataset must conform to one of these schemas.
All schemas enforce:
  - source and license metadata
  - rule_variant tracking
  - visibility reconstruction (public + private context)
  - weak label source tracing
  - explicit do_not_train_final_q_directly marker
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WeakLabelSource(str, Enum):
    OPEN_DATASET_ANNOTATION = "open_dataset_annotation"
    HEURISTIC = "heuristic"
    OUTCOME_PROXY = "outcome_proxy"
    LLM_JUDGE = "llm_judge"
    HUMAN = "human"


class OpenDataLicense(str, Enum):
    UNKNOWN = "unknown"
    CC_BY_4_0 = "cc-by-4.0"
    CC_BY_SA_4_0 = "cc-by-sa-4.0"
    CC_BY_NC_4_0 = "cc-by-nc-4.0"
    MIT = "mit"
    APACHE_2_0 = "apache-2.0"
    CUSTOM_RESEARCH = "custom_research_only"
    VERIFY_BEFORE_USE = "verify_before_use"


# ---------------------------------------------------------------------------
# Weak Label
# ---------------------------------------------------------------------------

@dataclass
class WeakLabel:
    """A single weak label with full provenance."""
    label_name: str
    label_value: float | str | None
    source: WeakLabelSource
    confidence: float = 0.5
    reason: str = ""
    used_future_info: bool = False


# ---------------------------------------------------------------------------
# Canonical Game Event
# ---------------------------------------------------------------------------

@dataclass
class CanonicalGameEvent:
    """A single game event normalized from an open dataset."""
    event_id: str
    source: str
    game_id: str
    timestamp_or_turn: int
    phase: str  # DAY_DISCUSSION | DAY_VOTE | NIGHT | ROLE_ACTION
    actor: str
    role_if_visible: str = "Unknown"
    event_type: str = "speech"  # speech | vote | skill | night_action | claim | system
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, Any] = field(default_factory=lambda: {"public": True, "private_to": []})
    raw_ref: str = ""


# ---------------------------------------------------------------------------
# Visibility State
# ---------------------------------------------------------------------------

@dataclass
class VisibilityState:
    """What was visible to a player at decision time."""
    visible_public_context: dict[str, Any] = field(default_factory=dict)
    visible_private_context: dict[str, Any] = field(default_factory=dict)
    unavailable_future_context: dict[str, Any] = field(default_factory=dict)
    visibility_confidence: str = "unknown"  # high | medium | low


# ---------------------------------------------------------------------------
# Open Game Log
# ---------------------------------------------------------------------------

@dataclass
class OpenGameLog:
    """A complete game reconstructed from an open dataset."""
    source: str
    license: OpenDataLicense = OpenDataLicense.VERIFY_BEFORE_USE
    rule_variant: str = "unknown"
    game_id: str = ""
    events: list[CanonicalGameEvent] = field(default_factory=list)
    players: list[dict[str, Any]] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)
    winner: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Speech Quality Sample
# ---------------------------------------------------------------------------

@dataclass
class SpeechQualitySample:
    """Canonical speech quality sample (§3.1)."""
    sample_id: str
    source: str
    license: OpenDataLicense = OpenDataLicense.VERIFY_BEFORE_USE
    rule_variant: str = "unknown"
    game_id: str = ""
    turn_id: str = ""
    phase: str = "DAY_DISCUSSION"
    player_id: str = ""
    role: str = "Unknown"
    utterance: str = ""
    visible_public_context: dict[str, Any] = field(default_factory=dict)
    visible_private_context: dict[str, Any] = field(default_factory=dict)
    weak_labels: dict[str, WeakLabel] = field(default_factory=dict)
    weak_label_source: str = "unknown"
    do_not_train_final_q_directly: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source": self.source,
            "license": self.license.value,
            "rule_variant": self.rule_variant,
            "game_id": self.game_id,
            "turn_id": self.turn_id,
            "phase": self.phase,
            "player_id": self.player_id,
            "role": self.role,
            "utterance": self.utterance,
            "visible_public_context": self.visible_public_context,
            "visible_private_context": self.visible_private_context,
            "weak_labels": {
                k: {
                    "label_name": v.label_name,
                    "label_value": v.label_value,
                    "source": v.source.value,
                    "confidence": v.confidence,
                    "reason": v.reason,
                    "used_future_info": v.used_future_info,
                }
                for k, v in self.weak_labels.items()
            },
            "weak_label_source": self.weak_label_source,
            "do_not_train_final_q_directly": self.do_not_train_final_q_directly,
        }


# ---------------------------------------------------------------------------
# Vote Decision Sample
# ---------------------------------------------------------------------------

@dataclass
class VoteDecisionSample:
    """Canonical vote decision sample (§3.2)."""
    sample_id: str
    source: str
    license: OpenDataLicense = OpenDataLicense.VERIFY_BEFORE_USE
    rule_variant: str = "unknown"
    game_id: str = ""
    phase: str = "DAY_VOTE"
    player_id: str = ""
    role: str = "Unknown"
    visible_public_context: dict[str, Any] = field(default_factory=dict)
    visible_private_context: dict[str, Any] = field(default_factory=dict)
    vote_target: str = ""
    candidate_targets: list[str] = field(default_factory=list)
    weak_labels: dict[str, WeakLabel] = field(default_factory=dict)
    weak_label_source: str = "unknown"
    do_not_train_final_q_directly: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source": self.source,
            "license": self.license.value,
            "rule_variant": self.rule_variant,
            "game_id": self.game_id,
            "phase": self.phase,
            "player_id": self.player_id,
            "role": self.role,
            "visible_public_context": self.visible_public_context,
            "visible_private_context": self.visible_private_context,
            "vote_target": self.vote_target,
            "candidate_targets": self.candidate_targets,
            "weak_labels": {
                k: {
                    "label_name": v.label_name,
                    "label_value": v.label_value,
                    "source": v.source.value,
                    "confidence": v.confidence,
                }
                for k, v in self.weak_labels.items()
            },
            "weak_label_source": self.weak_label_source,
            "do_not_train_final_q_directly": self.do_not_train_final_q_directly,
        }


# ---------------------------------------------------------------------------
# Counterfactual Pairwise Sample
# ---------------------------------------------------------------------------

@dataclass
class CounterfactualPairwiseSample:
    """Canonical pairwise preference sample (§3.3)."""
    pair_id: str
    source: str
    license: OpenDataLicense = OpenDataLicense.VERIFY_BEFORE_USE
    rule_variant: str = "unknown"
    game_id: str = ""
    role: str = "Unknown"
    action_type: str = ""  # vote | speech | skill | night_action
    visible_context: dict[str, Any] = field(default_factory=dict)
    option_a: dict[str, Any] = field(default_factory=dict)
    option_b: dict[str, Any] = field(default_factory=dict)
    label: str = "UNCERTAIN"  # A_BETTER | B_BETTER | TIE | UNCERTAIN
    label_source: str = "unknown"
    confidence: str = "low"
    reason: str = ""
    do_not_enable_ranker_without_gate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "source": self.source,
            "license": self.license.value,
            "rule_variant": self.rule_variant,
            "game_id": self.game_id,
            "role": self.role,
            "action_type": self.action_type,
            "visible_context": self.visible_context,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "label": self.label,
            "label_source": self.label_source,
            "confidence": self.confidence,
            "reason": self.reason,
            "do_not_enable_ranker_without_gate": self.do_not_enable_ranker_without_gate,
        }


# ---------------------------------------------------------------------------
# Value Impact Sample
# ---------------------------------------------------------------------------

@dataclass
class ValueImpactSample:
    """Canonical value impact sample (§3.4)."""
    sample_id: str
    source: str
    license: OpenDataLicense = OpenDataLicense.VERIFY_BEFORE_USE
    rule_variant: str = "unknown"
    state_id: str = ""
    phase: str = ""
    role: str = "Unknown"
    visible_context: dict[str, Any] = field(default_factory=dict)
    candidate_action: dict[str, Any] = field(default_factory=dict)
    future_outcome: dict[str, Any] = field(default_factory=dict)
    weak_labels: dict[str, WeakLabel] = field(default_factory=dict)
    weak_label_source: str = "unknown"
    not_process_quality_label: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source": self.source,
            "license": self.license.value,
            "rule_variant": self.rule_variant,
            "state_id": self.state_id,
            "phase": self.phase,
            "role": self.role,
            "visible_context": self.visible_context,
            "candidate_action": self.candidate_action,
            "future_outcome": self.future_outcome,
            "weak_labels": {
                k: {"label_name": v.label_name, "label_value": v.label_value,
                    "source": v.source.value, "confidence": v.confidence}
                for k, v in self.weak_labels.items()
            },
            "weak_label_source": self.weak_label_source,
            "not_process_quality_label": self.not_process_quality_label,
        }


# ---------------------------------------------------------------------------
# Role Action Sample
# ---------------------------------------------------------------------------

@dataclass
class RoleActionSample:
    """Canonical role/action sample (§3.5)."""
    sample_id: str
    source: str
    role: str = "Unknown"
    action_type: str = ""
    visible_context: dict[str, Any] = field(default_factory=dict)
    actual_action: dict[str, Any] = field(default_factory=dict)
    candidate_actions: list[dict[str, Any]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    weak_labels: dict[str, WeakLabel] = field(default_factory=dict)
    human_label: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source": self.source,
            "role": self.role,
            "action_type": self.action_type,
            "visible_context": self.visible_context,
            "actual_action": self.actual_action,
            "candidate_actions": self.candidate_actions,
            "features": self.features,
            "weak_labels": {
                k: {"label_name": v.label_name, "label_value": v.label_value,
                    "source": v.source.value, "confidence": v.confidence}
                for k, v in self.weak_labels.items()
            },
            "human_label": self.human_label,
        }
