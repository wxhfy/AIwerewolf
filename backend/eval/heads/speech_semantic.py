"""Speech Semantic Scorer — audit-only speech act analysis.

Trained on open data (Werewolf Among Us).
Returns speech act probabilities and audit features.
Never returns final_q. Never affects calibrated_q.

Usage:
  from backend.eval.heads.speech_semantic import SpeechSemanticScorer
  scorer = SpeechSemanticScorer()
  result = scorer.score("I think P3 is the werewolf because...")
  # result = {"speech_act_probs": {...}, "audit_features": {...}, "audit_only": True}
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

MODEL_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "models" / "open_data" / "speech_act_classifier_v0.pkl"
)

SPEECH_LABELS = [
    "accusation",
    "interrogation",
    "defense",
    "evidence_use",
    "identity_declaration",
    "call_for_action",
]

AUDIT_FEATURE_MAP = {
    "accusation": "pressure_signal",
    "interrogation": "information_seeking_signal",
    "defense": "defensive_posture_signal",
    "evidence_use": "evidence_grounding_signal",
    "identity_declaration": "identity_claim_signal",
    "call_for_action": "actionability_signal",
}


@dataclass
class SpeechSemanticResult:
    """Audit-only speech semantic analysis result."""

    speech_act_probs: dict[str, float] = field(default_factory=dict)
    audit_features: dict[str, float] = field(default_factory=dict)
    audit_only: bool = True
    source_model: str = "speech_act_classifier_v0"
    model_available: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "speech_act_probs": self.speech_act_probs,
            "audit_features": self.audit_features,
            "audit_only": self.audit_only,
            "source_model": self.source_model,
            "model_available": self.model_available,
            "error": self.error,
        }


class SpeechSemanticScorer:
    """Audit-only speech act and semantic feature extractor.

    Uses a trained SpeechActClassifier (TF-IDF + LogisticRegression) to predict
    persuasion strategy probabilities and converts them to audit features.

    IMPORTANT:
      - audit_only = True (never affects final_q)
      - If model is not trained, returns zero probabilities
      - Does not raise exceptions on model loading failure
    """

    def __init__(self, model_path: str | Path | None = None):
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self.vectorizer = None
        self.classifier = None
        self.model_available = False
        self._load_model()

    def _load_model(self):
        try:
            if not self.model_path.exists():
                return
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
            self.vectorizer = data.get("vectorizer")
            self.classifier = data.get("classifier")
            self.labels = data.get("labels", SPEECH_LABELS)
            if data.get("audit_only", True) and self.vectorizer and self.classifier:
                self.model_available = True
        except Exception:
            self.model_available = False

    def score(self, utterance: str) -> SpeechSemanticResult:
        """Score a single utterance. Returns zero probs if model unavailable."""
        if not utterance or not utterance.strip():
            return SpeechSemanticResult(
                speech_act_probs=dict.fromkeys(SPEECH_LABELS, 0.0),
                audit_features={AUDIT_FEATURE_MAP[label]: 0.0 for label in SPEECH_LABELS},
                model_available=self.model_available,
                error="empty_utterance",
            )

        if not self.model_available:
            return SpeechSemanticResult(
                speech_act_probs=dict.fromkeys(SPEECH_LABELS, 0.0),
                audit_features={AUDIT_FEATURE_MAP[label]: 0.0 for label in SPEECH_LABELS},
                model_available=False,
                error="model_not_available",
            )

        try:
            X = self.vectorizer.transform([utterance])
            proba_matrix = self.classifier.predict_proba(X)

            # proba_matrix[i] is the proba output of the i-th estimator
            # Each row is [P(not_class), P(class)]
            probs: dict[str, float] = {}
            for i, label in enumerate(self.labels):
                if i < len(proba_matrix):
                    probs[label] = round(float(proba_matrix[i][0][1]), 4)

            # Convert to audit features
            audit_features: dict[str, float] = {}
            for label, prob in probs.items():
                feature_name = AUDIT_FEATURE_MAP.get(label, label)
                audit_features[feature_name] = prob

            return SpeechSemanticResult(
                speech_act_probs=probs,
                audit_features=audit_features,
                model_available=True,
            )
        except Exception as e:
            return SpeechSemanticResult(
                speech_act_probs=dict.fromkeys(SPEECH_LABELS, 0.0),
                audit_features={AUDIT_FEATURE_MAP[label]: 0.0 for label in SPEECH_LABELS},
                model_available=True,
                error=str(e)[:200],
            )

    def score_batch(self, utterances: list[str]) -> list[SpeechSemanticResult]:
        """Score multiple utterances."""
        return [self.score(u) for u in utterances]
