"""Track B feature extractors."""

from typing import Optional

from backend.eval.features.registry import FeatureRegistry, get_feature_registry
from backend.eval.features.base import BaseActionFeatures
from backend.eval.features.private_context import PrivateContextFeatures
from backend.eval.features.vote import VoteQualityFeatures
from backend.eval.features.kill import KillTargetValueFeatures


def register_default_extractors(registry: Optional[FeatureRegistry] = None) -> FeatureRegistry:
    """Register all default feature extractors."""
    if registry is None:
        registry = get_feature_registry()
    registry.register(BaseActionFeatures())
    registry.register(PrivateContextFeatures())
    registry.register(VoteQualityFeatures())
    registry.register(KillTargetValueFeatures())
    return registry
