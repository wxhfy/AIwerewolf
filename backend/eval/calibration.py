"""Post-Hoc Score Calibration — aligns LLM judge scores to human distributions.

Reference: Morandi (arXiv:2605.09227, 2026)
- Ridge regression calibration for < 1500 anchors
- Neural-ODE (FFJORD) score-transport flow for > 1500 anchors
- Decision rule: with 100 anchors → Ridge (KL 0.031 vs 0.058 for ODE)
                 with 1500 anchors → ODE (MAE 0.320 vs 0.359 for Ridge)

Also implements Rulers (2026) quantile mapping for distribution matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import json
import math
from pathlib import Path

import numpy as np


@dataclass
class CalibrationResult:
    """Result of calibrating a scoring dimension."""

    dimension: str
    method: str  # "ridge" | "quantile_map" | "none"
    n_anchors: int
    raw_mean: float
    calibrated_mean: float
    raw_std: float
    calibrated_std: float
    kl_divergence: Optional[float] = None  # KL(raw || human)
    calibration_scores: List[float] = field(default_factory=list)


class ScoreCalibrator:
    """Post-hoc calibration for LLM-based scoring dimensions.

    Usage:
        calibrator = ScoreCalibrator()
        calibrator.add_anchor(raw_score=0.65, human_score=0.72, dimension="persuasive")
        # ... accumulate at least 50 anchors per dimension ...
        calibrated = calibrator.calibrate("persuasive", new_raw_scores=[0.70, 0.55])
    """

    def __init__(self, min_anchors: int = 50):
        self._min_anchors = min_anchors
        self._anchors: Dict[str, Tuple[List[float], List[float]]] = {}  # dim → (raw, human)
        self._models: Dict[str, Any] = {}  # dim → fitted model

    def add_anchor(self, raw_score: float, human_score: float, dimension: str) -> None:
        """Add a human-labeled anchor point for calibration.

        Args:
            raw_score: The raw score from the LLM judge (0-1).
            human_score: The human-assigned score for the same item (0-1).
            dimension: Scoring dimension name.
        """
        if dimension not in self._anchors:
            self._anchors[dimension] = ([], [])
        self._anchors[dimension][0].append(raw_score)
        self._anchors[dimension][1].append(human_score)

    def add_anchors_batch(self, anchors: List[Dict[str, Any]]) -> None:
        """Add multiple anchors at once.

        Args:
            anchors: List of {"dimension": str, "raw": float, "human": float}.
        """
        for a in anchors:
            self.add_anchor(a["raw"], a["human"], a["dimension"])

    def n_anchors(self, dimension: str) -> int:
        """Number of anchors available for a dimension."""
        if dimension not in self._anchors:
            return 0
        return len(self._anchors[dimension][0])

    def calibrate(
        self,
        dimension: str,
        raw_scores: List[float],
    ) -> CalibrationResult:
        """Calibrate raw scores to match human distribution.

        Automatically selects method:
        - < 50 anchors: no calibration (insufficient data)
        - 50-1500 anchors: Ridge regression
        - > 1500 anchors: would use Neural-ODE (not yet implemented, falls back to Ridge)
        """
        n = self.n_anchors(dimension)
        raw_arr = np.array(raw_scores)

        if n < self._min_anchors:
            return CalibrationResult(
                dimension=dimension, method="none", n_anchors=n,
                raw_mean=float(raw_arr.mean()), calibrated_mean=float(raw_arr.mean()),
                raw_std=float(raw_arr.std()), calibrated_std=float(raw_arr.std()),
                calibration_scores=raw_scores,
            )

        anchor_raw = np.array(self._anchors[dimension][0])
        anchor_human = np.array(self._anchors[dimension][1])

        # Ridge regression calibration
        calibrated = self._ridge_calibrate(raw_arr, anchor_raw, anchor_human)

        # Quantile mapping to match distribution shape
        calibrated = self._quantile_map(calibrated, anchor_human)

        # KL divergence as quality metric
        kl = self._compute_kl(raw_arr, anchor_human)

        return CalibrationResult(
            dimension=dimension, method="ridge", n_anchors=n,
            raw_mean=float(raw_arr.mean()),
            calibrated_mean=float(calibrated.mean()),
            raw_std=float(raw_arr.std()),
            calibrated_std=float(calibrated.std()),
            kl_divergence=kl,
            calibration_scores=[round(float(c), 4) for c in calibrated],
        )

    def _ridge_calibrate(
        self,
        raw: np.ndarray,
        anchor_raw: np.ndarray,
        anchor_human: np.ndarray,
    ) -> np.ndarray:
        """Ridge regression: maps raw scores → human-aligned scores."""
        from sklearn.linear_model import Ridge
        model = Ridge(alpha=1.0)
        X = anchor_raw.reshape(-1, 1)
        model.fit(X, anchor_human)
        return model.predict(raw.reshape(-1, 1))

    def _quantile_map(self, scores: np.ndarray, target_dist: np.ndarray) -> np.ndarray:
        """Map score distribution quantiles to match target distribution.

        Ensures the calibrated scores have the same shape as human labels.
        """
        n = len(scores)
        ranks = np.argsort(np.argsort(scores))  # [0, n-1]
        target_sorted = np.sort(target_dist)
        # Interpolate target values for each rank
        indices = np.clip((ranks / max(1, n - 1)) * (len(target_dist) - 1), 0, len(target_dist) - 1).astype(int)
        return target_sorted[indices]

    def _compute_kl(self, raw: np.ndarray, human: np.ndarray) -> float:
        """Compute KL divergence between raw and human score distributions."""
        try:
            bins = min(10, len(human) // 5)
            if bins < 2:
                return 0.0
            raw_hist, _ = np.histogram(raw, bins=bins, range=(0, 1), density=True)
            human_hist, _ = np.histogram(human, bins=bins, range=(0, 1), density=True)
            # Add small epsilon to avoid log(0)
            eps = 1e-10
            raw_hist = raw_hist + eps
            human_hist = human_hist + eps
            raw_hist /= raw_hist.sum()
            human_hist /= human_hist.sum()
            kl = np.sum(raw_hist * np.log(raw_hist / human_hist))
            return round(float(kl), 6)
        except Exception:
            return 0.0

    def save_anchors(self, path: str) -> None:
        """Persist anchors to JSON file."""
        data = {
            dim: {"raw": raw, "human": human}
            for dim, (raw, human) in self._anchors.items()
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_anchors(self, path: str) -> None:
        """Load anchors from JSON file."""
        with open(path) as f:
            data = json.load(f)
        for dim, values in data.items():
            self._anchors[dim] = (values["raw"], values["human"])

    def summary(self) -> Dict[str, Any]:
        """Summary of calibration status."""
        dims = {}
        for dim, (raw, human) in self._anchors.items():
            dims[dim] = {
                "n_anchors": len(raw),
                "ready": len(raw) >= self._min_anchors,
                "raw_range": [round(min(raw), 3), round(max(raw), 3)],
                "human_range": [round(min(human), 3), round(max(human), 3)],
            }
        return {
            "total_dimensions": len(dims),
            "dimensions": dims,
            "min_anchors_required": self._min_anchors,
        }


# ============================================================
# Calibration Data Collector (for building anchor sets)
# ============================================================

def collect_calibration_sample(
    game_id: str,
    player_id: str,
    speech_text: str,
    persona_info: Dict[str, Any],
    raw_scores: Dict[str, float],
    human_label: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Collect one calibration sample.

    This is intended to be called during manual review: a human reads the
    speech + persona info, then labels each dimension.

    Args:
        game_id: Game identifier.
        player_id: Player identifier.
        speech_text: The speech text being scored.
        persona_info: Persona traits of the speaker.
        raw_scores: Dict of dimension → raw LLM score.
        human_label: Optional dict of dimension → human-assigned score.

    Returns:
        Calibration sample dict.
    """
    sample = {
        "game_id": game_id,
        "player_id": player_id,
        "speech_text": speech_text[:500],
        "persona_mbti": persona_info.get("mbti", ""),
        "persona_style": persona_info.get("style_label", ""),
        "raw_scores": raw_scores,
        "human_labels": human_label or {},
    }

    if human_label:
        for dim, human_score in human_label.items():
            if dim in raw_scores:
                sample.setdefault("anchors", []).append({
                    "dimension": dim,
                    "raw": raw_scores[dim],
                    "human": human_score,
                })

    return sample
