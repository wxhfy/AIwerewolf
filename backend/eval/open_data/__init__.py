"""Open data reconstruction layer for Track B.

Converts external Werewolf / social-deduction datasets into
Track B-compatible small datasets (SpeechQualityDataset, VoteDecisionDataset,
CounterfactualPairwiseDataset, ValueImpactDataset, RoleActionDataset).

Policy:
  - All open-data outputs are audit-only by default.
  - No final_q is generated from open data.
  - Source, license, and rule_variant metadata must be preserved.
  - Visibility reconstruction is mandatory for every sample.
"""

from backend.eval.open_data.schema import (
    CanonicalGameEvent,
    OpenDataLicense,
    OpenGameLog,
    SpeechQualitySample,
    VoteDecisionSample,
    CounterfactualPairwiseSample,
    ValueImpactSample,
    RoleActionSample,
    VisibilityState,
    WeakLabel,
    WeakLabelSource,
)

__all__ = [
    "CanonicalGameEvent",
    "OpenDataLicense",
    "OpenGameLog",
    "SpeechQualitySample",
    "VoteDecisionSample",
    "CounterfactualPairwiseSample",
    "ValueImpactSample",
    "RoleActionSample",
    "VisibilityState",
    "WeakLabel",
    "WeakLabelSource",
]
