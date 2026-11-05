"""Post-Hoc Score Calibration — aligns LLM judge scores to human distributions.

Reference: Morandi (arXiv:2605.09227, 2026)
- Ridge regression calibration for < 1500 anchors
- Neural-ODE (FFJORD) score-transport flow for > 1500 anchors
- Decision rule: with 100 anchors → Ridge (KL 0.031 vs 0.058 for ODE)
                 with 1500 anchors → ODE (MAE 0.320 vs 0.359 for Ridge)

Also implements Rulers (2026) quantile mapping for distribution matching.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import numpy as np

from backend.eval.human_label_validator import validate_judge_calibration_dataset
from backend.eval.judge_rubric import RUBRIC_HASH
from backend.eval.judge_rubric import RUBRIC_VERSION


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
                dimension=dimension,
                method="none",
                n_anchors=n,
                raw_mean=float(raw_arr.mean()),
                calibrated_mean=float(raw_arr.mean()),
                raw_std=float(raw_arr.std()),
                calibrated_std=float(raw_arr.std()),
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
            dimension=dimension,
            method="ridge",
            n_anchors=n,
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
        data = {dim: {"raw": raw, "human": human} for dim, (raw, human) in self._anchors.items()}
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
                sample.setdefault("anchors", []).append(
                    {
                        "dimension": dim,
                        "raw": raw_scores[dim],
                        "human": human_score,
                    }
                )

    return sample


@dataclass(frozen=True)
class JudgeCalibrationPolicy:
    """Held-out acceptance criteria; production approval retains a sample floor."""

    min_train: int = 30
    min_validation: int = 20
    min_kappa: float = 0.60
    min_correlation: float = 0.70
    max_abs_bias: float = 0.10
    max_mae: float = 0.15
    min_confidence: float = 0.70
    attempts: int = 2


def load_judge_calibration_dataset(path: str | Path) -> dict[str, Any]:
    """Load an explicit JSON annotation set; never create placeholder labels."""
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_judge_calibration_dataset(dataset)
    if errors:
        raise ValueError("invalid_calibration_dataset:" + ",".join(errors))
    return dataset


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return None
    return round(float(np.corrcoef(left, right)[0, 1]), 6)


def _ranks(values: np.ndarray) -> np.ndarray:
    """Average ranks for ties, without an additional statistics dependency."""
    return np.array([sum(values < value) + (sum(values == value) - 1) / 2 for value in values], dtype=float)


def judge_agreement_metrics(raw_scores: list[float], human_scores: list[float]) -> dict[str, Any]:
    """Quadratic weighted Cohen kappa, Pearson/Spearman, signed bias and MAE."""
    if len(raw_scores) != len(human_scores):
        raise ValueError("score_count_mismatch")
    left, right = np.array(raw_scores, dtype=float), np.array(human_scores, dtype=float)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in [*raw_scores, *human_scores]):
        raise ValueError("scores_must_be_finite_normalized_values")
    if not len(left):
        return {"n": 0, "kappa": None, "pearson": None, "spearman": None, "bias": None, "mae": None}
    left_bins, right_bins = np.minimum((left * 5).astype(int), 4), np.minimum((right * 5).astype(int), 4)
    observed = np.zeros((5, 5))
    for a, b in zip(left_bins, right_bins):
        observed[a, b] += 1
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / len(left)
    weights = (np.arange(5)[:, None] - np.arange(5)[None, :]) ** 2 / 16
    expected_disagreement = float((weights * expected).sum())
    kappa = 1 - float((weights * observed).sum()) / expected_disagreement if expected_disagreement > 0 else None
    return {
        "n": len(left),
        "kappa": round(kappa, 6) if kappa is not None else None,
        "pearson": _correlation(left, right),
        "spearman": _correlation(_ranks(left), _ranks(right)),
        "bias": round(float(np.mean(left - right)), 6),
        "mae": round(float(np.mean(np.abs(left - right))), 6),
    }


def _fit_judge_parameters(raw: list[float], human: list[float]) -> dict[str, float]:
    """Fit a fixed ridge transform, so inference is independent of batch size."""
    x, y = np.array(raw), np.array(human)
    centered_x = x - np.mean(x)
    slope = float(np.dot(centered_x, y - np.mean(y)) / (np.dot(centered_x, centered_x) + 0.001))
    return {
        "slope": slope,
        "intercept": float(np.mean(y) - slope * np.mean(x)),
        "raw_min": float(np.min(x)),
        "raw_max": float(np.max(x)),
    }


def calibrate_judge_dataset(
    dataset: dict[str, Any],
    panel: Any,
    *,
    judge_model: str,
    policy: JudgeCalibrationPolicy | None = None,
    scoring_mode: str = "single_step",
) -> dict[str, Any]:
    """Run the real Judge API on role-visible decisions, then evaluate held-out labels.

    The Judge receives neither human labels nor the dataset's annotation metadata.
    Synthetic or fake-provider results are useful demonstrations, never an
    authorization to promote strategies. Exceptions are recorded by type only.
    """
    errors = validate_judge_calibration_dataset(dataset)
    if errors:
        raise ValueError("invalid_calibration_dataset:" + ",".join(errors))
    if not judge_model.strip():
        raise ValueError("judge_model_required")
    if scoring_mode not in {"single_step", "panel_step"}:
        raise ValueError("invalid_scoring_mode")
    policy = policy or JudgeCalibrationPolicy()
    if policy.min_train < 2 or policy.min_validation < 2 or not 1 <= policy.attempts <= 5:
        raise ValueError("invalid_calibration_policy")
    scored: list[dict[str, Any]] = []
    for sample in dataset["samples"]:
        row = {key: sample[key] for key in ("sample_id", "game_id", "split", "human_score", "confidence")}
        row["raw_score"] = None
        if sample["confidence"] == "low":
            row["error"] = "low_annotation_confidence"
            scored.append(row)
            continue
        for attempt in range(policy.attempts):
            row["attempts"] = attempt + 1
            try:
                score_method = panel.score_step if scoring_mode == "single_step" else panel.score_step_with_panel
                verdict = score_method(dict(sample["decision"]), dict(sample["visible_context"]))
                value = float(verdict.overall) / 10 if verdict is not None else float("nan")
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("invalid_judge_verdict")
                row["raw_score"] = value
                row["judge_confidence"] = getattr(verdict, "confidence", 0.0)
                row.pop("error", None)
                break
            except Exception as exc:
                row["error"] = type(exc).__name__
        scored.append(row)
    usable = [
        row
        for row in scored
        if row["raw_score"] is not None
        and isinstance(row.get("judge_confidence"), (int, float))
        and math.isfinite(row["judge_confidence"])
        and policy.min_confidence <= row["judge_confidence"] <= 1
    ]
    training = [row for row in usable if row["split"] == "train"]
    validation = [row for row in usable if row["split"] == "validation"]
    parameters = (
        _fit_judge_parameters([r["raw_score"] for r in training], [r["human_score"] for r in training])
        if len(training) >= 2
        else None
    )
    raw = [row["raw_score"] for row in validation]
    human = [row["human_score"] for row in validation]
    transformed = (
        [min(1.0, max(0.0, parameters["slope"] * value + parameters["intercept"])) for value in raw]
        if parameters
        else raw
    )
    metrics = {
        "raw": judge_agreement_metrics(raw, human),
        "calibrated": judge_agreement_metrics(transformed, human),
        "train_n": len(training),
        "validation_n": len(validation),
        "failed_n": sum(row["raw_score"] is None and row["confidence"] != "low" for row in scored),
        "excluded_low_confidence_n": sum(row["confidence"] == "low" for row in scored),
        "excluded_low_judge_confidence_n": sum(row["raw_score"] is not None and row not in usable for row in scored),
    }
    evaluated = metrics["calibrated"]
    reasons: list[str] = []
    if len(training) < policy.min_train:
        reasons.append("insufficient_train_samples")
    if len(validation) < policy.min_validation:
        reasons.append("insufficient_validation_samples")
    if metrics["failed_n"]:
        reasons.append("judge_scoring_incomplete")
    if parameters and parameters["slope"] <= 0:
        reasons.append("nonpositive_calibration_slope")
    for name, minimum in (
        ("kappa", policy.min_kappa),
        ("pearson", policy.min_correlation),
        ("spearman", policy.min_correlation),
    ):
        if evaluated[name] is None or evaluated[name] < minimum:
            reasons.append(f"{name}_below_gate")
    if evaluated["bias"] is None or abs(evaluated["bias"]) > policy.max_abs_bias:
        reasons.append("bias_above_gate")
    if evaluated["mae"] is None or evaluated["mae"] > policy.max_mae:
        reasons.append("mae_above_gate")
    passed = not reasons
    synthetic = dataset["synthetic"]
    provider = str(getattr(getattr(panel, "_llm", None), "provider", ""))
    human_verified = not synthetic and dataset["annotation_source"] == "human"
    production_eligible = human_verified and "fake" not in judge_model.lower() and provider != "fake"
    production_floor = len(training) >= 30 and len(validation) >= 20
    production_policy_strict = (
        policy.min_kappa >= 0.60
        and policy.min_correlation >= 0.70
        and policy.max_abs_bias <= 0.10
        and policy.max_mae <= 0.15
        and policy.min_confidence >= 0.70
    )
    if passed and production_eligible and not production_floor:
        reasons.append("production_sample_floor_not_met")
    if passed and production_eligible and not production_policy_strict:
        reasons.append("production_policy_weakened")
    approved = passed and production_eligible and production_floor and production_policy_strict
    digest = hashlib.sha256(json.dumps(dataset, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result = {
        "schema_version": "judge-calibration.v1",
        "dataset_id": dataset["dataset_id"],
        "dataset_hash": digest,
        "judge_model": judge_model,
        "scoring_mode": scoring_mode,
        "rubric_version": RUBRIC_VERSION,
        "rubric_hash": RUBRIC_HASH,
        "synthetic": synthetic,
        "human_verified": human_verified,
        "status": "approved"
        if approved
        else ("demonstration" if synthetic or not production_eligible else "pending_review"),
        "agreement_passed": passed,
        "auto_promotion_allowed": approved,
        "parameters": {"overall": parameters} if parameters else {},
        "metrics": metrics,
        "policy": asdict(policy),
        "reasons": reasons,
        "samples": scored,
    }
    identity = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result["calibration_id"] = identity[:32]
    return result


def apply_judge_calibration(
    profile: dict[str, Any] | None,
    raw_score: float | None,
    *,
    rule_score: float,
    confidence: float = 1.0,
    judge_model: str | None = None,
    rubric_hash: str = RUBRIC_HASH,
    allow_demonstration: bool = False,
    scoring_mode: str = "single_step",
) -> dict[str, Any]:
    """Fail closed to deterministic scoring for untrusted or uncertain judgments."""
    if not math.isfinite(rule_score) or not 0 <= rule_score <= 1:
        raise ValueError("invalid_rule_score")
    reason = None
    if profile is None:
        reason = "calibration_missing"
    elif not (
        profile.get("auto_promotion_allowed") is True
        and profile.get("status") == "approved"
        and profile.get("human_verified") is True
        and profile.get("synthetic") is False
    ) and not (allow_demonstration and profile.get("agreement_passed") is True):
        reason = "calibration_not_approved"
    elif (
        profile.get("rubric_hash") != rubric_hash
        or profile.get("scoring_mode", "single_step") != scoring_mode
        or (judge_model is not None and profile.get("judge_model") != judge_model)
    ):
        reason = "calibration_identity_mismatch"
    elif raw_score is None or not math.isfinite(raw_score) or not 0 <= raw_score <= 1:
        reason = "invalid_judge_score"
    elif not math.isfinite(confidence) or confidence < max(0.70, profile.get("policy", {}).get("min_confidence", 0.70)):
        reason = "low_judge_confidence"
    parameters = (profile or {}).get("parameters", {}).get("overall")
    if reason is None and (
        not parameters
        or any(
            not isinstance(parameters.get(k), (int, float)) or not math.isfinite(parameters[k])
            for k in ("slope", "intercept", "raw_min", "raw_max")
        )
    ):
        reason = "invalid_calibration_parameters"
    if reason is None and not parameters["raw_min"] <= raw_score <= parameters["raw_max"]:
        reason = "outside_calibration_support"
    value = rule_score if reason else min(1.0, max(0.0, parameters["slope"] * raw_score + parameters["intercept"]))
    return {
        "score": round(value, 6),
        "raw_score": raw_score,
        "fallback_used": reason is not None,
        "fallback_reason": reason,
        "calibration_id": (profile or {}).get("calibration_id"),
        "requires_review": reason is not None,
        "confidence": confidence,
    }


def judge_model_identity(client: Any) -> str | None:
    """Bind calibrations to the same provider and model used at inference."""
    provider = str(getattr(client, "provider", "") or "").strip()
    model = str(getattr(client, "model", None) or getattr(client, "model_name", None) or "").strip()
    return f"{provider}:{model}" if provider and model else None
