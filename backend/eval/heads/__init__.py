"""Track B evaluation heads — small audit-only scorers.

Each head is trained on a specific task dataset and returns audit signals.
None of them affect final_q without passing a documented promotion gate.
"""

from backend.eval.heads.speech_semantic import SpeechSemanticResult
from backend.eval.heads.speech_semantic import SpeechSemanticScorer

__all__ = ["SpeechSemanticScorer", "SpeechSemanticResult"]
