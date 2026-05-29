"""Feature Extractor Registry — modular, auditable feature extraction.

Each extractor produces a flat dict with provenance tracking.
The registry returns unified feature dicts for any opportunity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class FeatureExtractor(Protocol):
    """Protocol for feature extractors."""
    name: str
    version: str

    def supports(self, opportunity: dict[str, Any]) -> bool: ...
    def extract(self, opportunity: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, float | int | str]: ...


@dataclass
class FeatureResult:
    """Unified feature extraction result with provenance."""
    features: dict[str, float | int | str] = field(default_factory=dict)
    feature_sources: dict[str, str] = field(default_factory=dict)
    extractors_used: list[str] = field(default_factory=list)
    extractors_skipped: list[str] = field(default_factory=list)


class FeatureRegistry:
    """Registry of feature extractors with dependency ordering."""

    def __init__(self) -> None:
        self._extractors: dict[str, FeatureExtractor] = {}

    def register(self, extractor: FeatureExtractor) -> None:
        key = f"{extractor.name}:{extractor.version}"
        self._extractors[key] = extractor

    def extract(
        self,
        opportunity: dict[str, Any],
        context: dict[str, Any] | None = None,
        *,
        extractor_names: list[str] | None = None,
    ) -> FeatureResult:
        """Extract features using all registered extractors (or named subset)."""
        result = FeatureResult()
        ctx = context or {}

        for key, ext in self._extractors.items():
            if extractor_names and ext.name not in extractor_names:
                result.extractors_skipped.append(key)
                continue
            if not ext.supports(opportunity):
                result.extractors_skipped.append(key)
                continue
            try:
                feats = ext.extract(opportunity, ctx)
                for fname, fval in feats.items():
                    result.features[fname] = fval
                    result.feature_sources[fname] = f"{ext.name}:{ext.version}"
                result.extractors_used.append(key)
            except Exception:
                result.extractors_skipped.append(f"{key}(error)")

        return result

    def list_extractors(self) -> list[dict[str, str]]:
        return [
            {"name": ext.name, "version": ext.version}
            for ext in self._extractors.values()
        ]


# Global singleton
_registry: FeatureRegistry | None = None


def get_feature_registry() -> FeatureRegistry:
    global _registry
    if _registry is None:
        _registry = FeatureRegistry()
    return _registry
