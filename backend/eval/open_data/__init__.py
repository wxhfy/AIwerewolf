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

from backend.eval.open_data.schema import CanonicalGameEvent
from backend.eval.open_data.schema import CounterfactualPairwiseSample
from backend.eval.open_data.schema import OpenDataLicense
from backend.eval.open_data.schema import OpenGameLog
from backend.eval.open_data.schema import RoleActionSample
from backend.eval.open_data.schema import SpeechQualitySample
from backend.eval.open_data.schema import ValueImpactSample
from backend.eval.open_data.schema import VisibilityState
from backend.eval.open_data.schema import VoteDecisionSample
from backend.eval.open_data.schema import WeakLabel
from backend.eval.open_data.schema import WeakLabelSource

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
