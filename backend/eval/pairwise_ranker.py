"""PairwiseLogisticRanker — learning-first decision quality ranking.

Trains a logistic regression on pairwise preference data:
  x = features_better - features_worse
  label = 1 (better > worse)

At inference:
  1. Compute absolute quality via base DQM.
  2. Compute pairwise preference against generated counterfactuals.
  3. Combine into learned_rank_q.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class PairwiseExample:
    pair_id: str
    source: str
    role: str
    action_type: str
    better_features: dict[str, float]
    worse_features: dict[str, float]
    better_label: float = 0.85
    worse_label: float = 0.15


@dataclass
class RankResult:
    learned_rank_q: float
    pairwise_margin: float
    rank_confidence: float


class PairwiseLogisticRanker:
    """Learns to rank opportunities via pairwise preference."""

    def __init__(self):
        self.model = None
        self.feature_names: list[str] = []
        self._scaler_mean: np.ndarray | None = None
        self._scaler_std: np.ndarray | None = None

    def _features_to_vector(self, features: dict[str, float], feature_names: list[str]) -> np.ndarray:
        return np.array([features.get(n, 0.0) for n in feature_names], dtype=np.float32)

    def fit(self, pairs: list[PairwiseExample]) -> dict[str, Any]:
        """Train logistic regression on pairwise differences.

        Filters zero-variance features and near-zero delta pairs.
        Uses symmetric augmentation (x_better - x_worse, label=1;
        x_worse - x_better, label=0).
        """
        from sklearn.linear_model import LogisticRegression

        # Collect all feature names
        all_names: set[str] = set()
        for p in pairs:
            all_names.update(p.better_features.keys())
            all_names.update(p.worse_features.keys())
        all_names_sorted = sorted(all_names)

        # Build pairwise difference matrix (first pass: detect degenerate features)
        X_diff_raw: list[np.ndarray] = []
        valid_pair_indices: list[int] = []
        for i, p in enumerate(pairs):
            bv = self._features_to_vector(p.better_features, all_names_sorted)
            wv = self._features_to_vector(p.worse_features, all_names_sorted)
            diff = bv - wv
            # Skip pairs with near-zero feature delta (no signal)
            if np.max(np.abs(diff)) < 1e-6:
                continue
            X_diff_raw.append(diff)
            X_diff_raw.append(-diff)  # symmetric: reversed
            valid_pair_indices.append(i)

        if not X_diff_raw:
            # All pairs degenerate — fall back to using all features
            self.feature_names = all_names_sorted
            self.model = LogisticRegression(max_iter=1000, class_weight="balanced")
            try:
                self.model.fit(np.zeros((2, len(all_names_sorted))), np.array([0, 1]))
            except Exception:
                pass
            return {
                "n_pairs": len(pairs),
                "n_features": len(all_names_sorted),
                "train_accuracy": 0.5,
                "feature_count": len(all_names_sorted),
                "warning": "all_pairs_degenerate",
                "valid_pairs": 0,
            }

        X_raw = np.array(X_diff_raw, dtype=np.float32)
        y_arr = np.array([1, 0] * len(valid_pair_indices))  # 1=better>worse, 0=worse<better

        # Filter zero-variance features
        feature_vars = np.var(X_raw, axis=0)
        nonzero_var_mask = feature_vars > 1e-8
        n_zero_var = int(np.sum(~nonzero_var_mask))

        if np.sum(nonzero_var_mask) < 1:
            # No features with variance — keep all
            nonzero_var_mask = np.ones(len(all_names_sorted), dtype=bool)
            n_zero_var = 0

        self.feature_names = [all_names_sorted[i] for i in range(len(all_names_sorted)) if nonzero_var_mask[i]]
        X = X_raw[:, nonzero_var_mask]

        # Standardize
        self._scaler_mean = X.mean(axis=0)
        self._scaler_std = X.std(axis=0) + 1e-8
        X_scaled = (X - self._scaler_mean) / self._scaler_std

        self.model = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.model.fit(X_scaled, y_arr)

        accuracy = float(self.model.score(X_scaled, y_arr))
        return {
            "n_pairs": len(pairs),
            "valid_pairs": len(valid_pair_indices),
            "degenerate_pairs": len(pairs) - len(valid_pair_indices),
            "n_features_total": len(all_names_sorted),
            "n_features_used": len(self.feature_names),
            "n_zero_variance_features": n_zero_var,
            "train_accuracy": round(accuracy, 4),
            "feature_count": len(self.feature_names),
        }

    def _prepare_input(self, features: dict[str, float]) -> np.ndarray | None:
        """Convert features dict to standardized model input, using filtered feature_names."""
        if self.model is None or not self.feature_names:
            return None
        fv = self._features_to_vector(features, self.feature_names)
        X_in = fv.reshape(1, -1)
        if self._scaler_mean is not None and len(self._scaler_mean) == X_in.shape[1]:
            X_in = (X_in - self._scaler_mean.reshape(1, -1)) / self._scaler_std.reshape(1, -1)
        elif self._scaler_mean is not None:
            # Dimension mismatch — model was trained with different feature set
            return None
        return X_in

    def predict_rank(self, features: dict[str, float]) -> RankResult:
        """Predict learned rank score from features.

        Note: pairwise models are trained on differences, not absolutes.
        For single-opportunity scoring, use compare_pair() or the base DQM.
        """
        if self.model is None or not self.feature_names:
            return RankResult(0.5, 0.0, 0.0)

        X_in = self._prepare_input(features)
        if X_in is None:
            return RankResult(0.5, 0.0, 0.0)

        if self._scaler_mean is not None:
            X_in = (X_in - self._scaler_mean) / self._scaler_std

        proba = self.model.predict_proba(X_in)[0]
        rank_q = float(proba[1])  # Probability of being the "better" action

        # Margin: how far from decision boundary
        if hasattr(self.model, "decision_function"):
            margin = float(self.model.decision_function(X_in)[0])
        else:
            margin = float(proba[1] - proba[0])

        confidence = float(max(proba))

        return RankResult(
            learned_rank_q=round(rank_q, 4),
            pairwise_margin=round(margin, 4),
            rank_confidence=round(confidence, 4),
        )

    def compare_pair(self, better_features: dict[str, float], worse_features: dict[str, float]) -> float:
        """Probability that 'better' ranks above 'worse'."""
        if self.model is None or not self.feature_names:
            return 0.5
        bv = self._features_to_vector(better_features, self.feature_names)
        wv = self._features_to_vector(worse_features, self.feature_names)
        diff = (bv - wv).reshape(1, -1)
        if self._scaler_mean is not None and len(self._scaler_mean) == diff.shape[1]:
            diff = (diff - self._scaler_mean.reshape(1, -1)) / self._scaler_std.reshape(1, -1)
        elif self._scaler_mean is not None:
            return 0.5
        return float(self.model.predict_proba(diff)[0][1])

    def save(self, path: str | Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "model": self.model,
                    "feature_names": self.feature_names,
                    "scaler_mean": self._scaler_mean,
                    "scaler_std": self._scaler_std,
                },
                f,
            )

    def load(self, path: str | Path) -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
            self.model = data["model"]
            self.feature_names = data.get("feature_names", [])
            self._scaler_mean = data.get("scaler_mean")
            self._scaler_std = data.get("scaler_std")


class PerActionPairwiseRankers:
    """Per-action-type rankers: speech, vote, night_action, skill.

    Each ranker is a PairwiseLogisticRanker trained only on its pair type.
    Falls back to a global ranker when per-action data is insufficient.
    """

    def __init__(self):
        self.rankers: dict[str, PairwiseLogisticRanker] = {}
        self._pair_counts: dict[str, int] = {}
        self._accuracies: dict[str, float] = {}

    def fit(self, all_pairs: list[PairwiseExample]) -> dict[str, Any]:
        """Train one ranker per action type group."""
        from collections import defaultdict

        by_action: dict[str, list[PairwiseExample]] = defaultdict(list)
        for p in all_pairs:
            # Map pair_type to action group
            if "speech" in p.action_type or "speech" in p.pair_id:
                by_action["speech"].append(p)
            elif "vote" in p.action_type or "vote" in p.pair_id:
                by_action["vote"].append(p)
            elif (
                "kill" in p.action_type
                or "night" in p.action_type
                or "seer" in p.action_type
                or "witch" in p.action_type
                or "guard" in p.action_type
                or "narrative" in p.action_type
                or "endgame" in p.action_type
                or "low_info" in p.action_type
            ):
                by_action["night_action"].append(p)
            else:
                by_action["other"].append(p)

        info = {}
        for action, pairs in by_action.items():
            if len(pairs) < 5:
                info[action] = {"status": "skipped", "reason": f"only {len(pairs)} pairs"}
                continue
            ranker = PairwiseLogisticRanker()
            train_info = ranker.fit(pairs)
            self.rankers[action] = ranker
            self._pair_counts[action] = len(pairs)
            self._accuracies[action] = train_info.get("train_accuracy", 0.5)
            info[action] = train_info

        return info

    def compare_pair(
        self, better_features: dict[str, float], worse_features: dict[str, float], action_type: str = "other"
    ) -> float:
        """Use per-action ranker if available, else fall back to other."""
        if action_type in self.rankers:
            return self.rankers[action_type].compare_pair(better_features, worse_features)
        if "other" in self.rankers:
            return self.rankers["other"].compare_pair(better_features, worse_features)
        return 0.5

    def predict_rank(self, features: dict[str, float], action_type: str = "other") -> "RankResult":
        if action_type in self.rankers:
            return self.rankers[action_type].predict_rank(features)
        if "other" in self.rankers:
            return self.rankers["other"].predict_rank(features)
        return RankResult(0.5, 0.0, 0.0)

    @property
    def pair_counts(self) -> dict[str, int]:
        return dict(self._pair_counts)

    @property
    def accuracies(self) -> dict[str, float]:
        return dict(self._accuracies)


def pairwise_examples_from_jsonl(path: str | Path) -> list[PairwiseExample]:
    """Load pairwise examples from JSONL file, extracting features via registry if needed."""
    from backend.eval.features import register_default_extractors

    registry = register_default_extractors()

    examples: list[PairwiseExample] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                better = d.get("good", d.get("better", {}))
                worse = d.get("bad", d.get("worse", {}))
                b_opp = better.get("opportunity", {}) if isinstance(better, dict) else {}
                w_opp = worse.get("opportunity", {}) if isinstance(worse, dict) else {}

                # Extract features from opportunities via registry
                if b_opp and isinstance(b_opp, dict):
                    bf_raw = registry.extract(b_opp).features
                    bf = {k: float(v) if isinstance(v, (int, float)) else 0.0 for k, v in bf_raw.items()}
                else:
                    bf = better.get("features", {}) if isinstance(better, dict) else {}

                if w_opp and isinstance(w_opp, dict):
                    wf_raw = registry.extract(w_opp).features
                    wf = {k: float(v) if isinstance(v, (int, float)) else 0.0 for k, v in wf_raw.items()}
                else:
                    wf = worse.get("features", {}) if isinstance(worse, dict) else {}

                if bf and wf:
                    examples.append(
                        PairwiseExample(
                            pair_id=d.get("pair_id", ""),
                            source=d.get("source", ""),
                            role=d.get("role", better.get("role", b_opp.get("role", ""))),
                            action_type=d.get("action_type", d.get("pair_type", b_opp.get("opportunity_type", ""))),
                            better_features=bf,
                            worse_features=wf,
                            better_label=float(better.get("label_quality", 0.85)),
                            worse_label=float(worse.get("label_quality", 0.15)),
                        )
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
    return examples


# ===================================================================
# RankerConfidenceGate
# ===================================================================


@dataclass
class RankerGateResult:
    eligible: bool
    weight: float
    confidence: str  # "high" | "medium" | "low" | "debug_only"
    reasons: list[str] = field(default_factory=list)


@dataclass
class RankerContribution:
    used: bool
    action_ranker: str
    eligible: bool
    weight: float
    confidence: str
    final_delta: float
    reasons: list[str] = field(default_factory=list)


def compute_ranker_gate(
    *,
    effective_pair_count: int,
    degenerate_pair_rate: float,
    validation_acc: float = 0.5,
    heldout_acc: float = 0.5,
    hard_cap_count: int = 0,
) -> RankerGateResult:
    """Determine whether a per-action ranker can affect scoring.

    Returns eligibility, weight, and confidence level.
    """
    reasons: list[str] = []

    if hard_cap_count > 0:
        return RankerGateResult(False, 0.0, "debug_only", ["hard_caps_detected"])

    # High confidence gate
    if effective_pair_count >= 50 and degenerate_pair_rate <= 0.20 and validation_acc >= 0.70 and heldout_acc >= 0.65:
        return RankerGateResult(True, 0.15, "high", ["all_high_gates_passed"])

    # Medium confidence gate
    if effective_pair_count >= 30 and degenerate_pair_rate <= 0.30 and validation_acc >= 0.65 and heldout_acc >= 0.60:
        return RankerGateResult(True, 0.10, "medium", ["medium_confidence_gate_passed"])

    # Low confidence gate
    if effective_pair_count >= 15 and degenerate_pair_rate <= 0.40 and validation_acc >= 0.60:
        return RankerGateResult(True, 0.05, "low", ["low_confidence_gate_passed"])

    # Debug only
    if effective_pair_count < 15:
        reasons.append("effective_pair_count_below_minimum")
    if degenerate_pair_rate > 0.40:
        reasons.append("degenerate_pair_rate_above_maximum")
    if validation_acc < 0.60:
        reasons.append("validation_acc_below_minimum")

    return RankerGateResult(False, 0.0, "debug_only", reasons or ["below_all_gates"])


def compute_ranker_contribution(
    *,
    calibrated_q: float,
    learned_rank_q: float,
    action_type: str,
    gate_result: RankerGateResult,
) -> RankerContribution:
    """Compute the ranker's contribution to the final quality score.

    final_q = (1 - weight) * calibrated_q + weight * learned_rank_q
    """
    if not gate_result.eligible:
        return RankerContribution(
            used=False,
            action_ranker=action_type,
            eligible=False,
            weight=0.0,
            confidence=gate_result.confidence,
            final_delta=0.0,
            reasons=gate_result.reasons,
        )

    w = gate_result.weight
    final_q = (1 - w) * calibrated_q + w * learned_rank_q
    delta = final_q - calibrated_q

    # Bound check
    if abs(delta) > 0.15:
        delta = 0.15 if delta > 0 else -0.15
        gate_result.reasons.append("delta_clamped_at_bound")

    return RankerContribution(
        used=True,
        action_ranker=action_type,
        eligible=True,
        weight=w,
        confidence=gate_result.confidence,
        final_delta=round(delta, 4),
        reasons=gate_result.reasons,
    )
