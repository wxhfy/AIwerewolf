"""Evaluation, review, and future self-improvement interfaces."""

from backend.eval.evolution import EvolutionHook, HermesEvolutionHook
from backend.eval.review import GraphRAGReviewProvider, ReviewArtifact, ReviewProvider

__all__ = [
    "EvolutionHook",
    "GraphRAGReviewProvider",
    "HermesEvolutionHook",
    "ReviewArtifact",
    "ReviewProvider",
]
