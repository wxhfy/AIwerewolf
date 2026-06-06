"""ProcessScoreV3 — role-normalized, confidence-aware player process scoring.

Replaces monolithic weighted average with:
- weighted decision quality across opportunities
- role-normalized z-score aggregation
- critical regret from counterfactual gaps
- confidence / low-sample warnings
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np


@dataclass
class ProcessScoreV3Result:
    player_id: str
    role: str
    weighted_quality: float
    role_normalized_quality: float
    speech_quality: float
    robustness: float
    high_impact_positive_rate: float
    critical_regret_rate: float
    process_score_v3: float
    n_opportunities: int
    confidence_interval: float = 0.0
    low_sample_warning: bool = False
    calibration_dependency_rate: float = 0.0


@dataclass
class GameEvaluationValue:
    game_id: str
    decision_signal: float
    reviewability: float
    training_value: float
    badcase_value: float
    clean_case_value: float
    recommended_use: list[str] = field(default_factory=list)


def compute_process_score_v3(
    opportunities: list[dict[str, Any]],
    *,
    role_action_stats: dict[tuple[str, str], dict[str, float]] | None = None,
) -> list[ProcessScoreV3Result]:
    """Compute V3 process scores with role normalization.

    Formula:
      process_score_v3 =
        0.45 * weighted_quality
        + 0.20 * role_normalized_quality
        + 0.15 * speech_quality
        + 0.10 * robustness
        + 0.10 * high_impact_positive_rate
        - 0.20 * critical_regret_rate
    """
    by_player: dict[str, list[dict]] = defaultdict(list)
    for opp in opportunities:
        by_player[opp.get("player_id", "")].append(opp)

    ra_stats = role_action_stats or {}
    results: list[ProcessScoreV3Result] = []

    for pid, opps in by_player.items():
        role = opps[0].get("role", "unknown")
        n = len(opps)

        # Weighted quality: sum(value * q) / sum(value)
        weights, qualities, raw_qs = [], [], []
        speech_qs: list[float] = []
        critical_regrets: list[float] = []
        calibration_deps: list[float] = []

        for opp in opps:
            w = opp.get("opportunity_value", 0.5) or 0.5
            cq = opp.get("calibrated_q", opp.get("combined_score", 0.5)) or 0.5
            rq = opp.get("raw_model_q", cq)
            weights.append(w)
            qualities.append(cq)
            raw_qs.append(rq)

            # Speech quality from speech-type opportunities
            if opp.get("opportunity_type") in ("speech", "seer_release"):
                speech_qs.append(cq)

            # Critical regret from counterfactual gap
            gap = opp.get("counterfactual_target_gap", 0) or 0
            if gap > 0.3:
                critical_regrets.append(gap)

            # Calibration dependency: how much calibration changed raw_q
            if rq is not None and cq is not None:
                calibration_deps.append(abs(rq - cq))

        tw = sum(weights)
        wq = sum(w * q for w, q in zip(weights, qualities)) / max(tw, 0.01)
        sq = float(np.mean(speech_qs)) if speech_qs else 0.5

        # Role-normalized: z-score within role+action_type groups
        role_zs: list[float] = []
        for opp in opps:
            key = (opp.get("role", ""), opp.get("opportunity_type", ""))
            stats = ra_stats.get(key)
            cq = opp.get("calibrated_q", 0.5) or 0.5
            if stats and stats.get("std", 0) > 0.001:
                z = (cq - stats["mean"]) / stats["std"]
                role_zs.append(z)
        rnq = float(np.tanh(np.mean(role_zs) / 3)) * 0.5 + 0.5 if role_zs else 0.5

        # Robustness
        n_fb = sum(1 for o in opps if (o.get("chosen_action", {}) or {}).get("metadata", {}).get("fallback"))
        rob = 1.0 - n_fb / max(n, 1)

        # High impact positive rate
        hip = sum(1 for q in qualities if q >= 0.70) / max(n, 1)

        # Critical regret rate
        crr = float(np.mean(critical_regrets)) if critical_regrets else 0.0

        # Calibration dependency
        cdr = float(np.mean(calibration_deps)) if calibration_deps else 0.0

        # V3 formula
        ps = 0.45 * wq + 0.20 * rnq + 0.15 * sq + 0.10 * rob + 0.10 * hip - 0.20 * crr
        ps = max(0.0, min(1.0, ps))

        # Confidence interval (simple: SEM * 1.96)
        se = np.std(qualities) / math.sqrt(max(n, 1)) if n >= 3 else 0.25
        ci = 1.96 * se

        results.append(
            ProcessScoreV3Result(
                player_id=pid,
                role=role,
                weighted_quality=round(wq, 4),
                role_normalized_quality=round(rnq, 4),
                speech_quality=round(sq, 4),
                robustness=round(rob, 4),
                high_impact_positive_rate=round(hip, 4),
                critical_regret_rate=round(crr, 4),
                process_score_v3=round(ps, 4),
                n_opportunities=n,
                confidence_interval=round(ci, 4),
                low_sample_warning=n < 3,
                calibration_dependency_rate=round(cdr, 4),
            )
        )

    return results


def compute_game_value(
    game_id: str,
    opportunities: list[dict[str, Any]],
    process_scores: list[ProcessScoreV3Result],
) -> GameEvaluationValue:
    """Score a game's utility for training and evaluation."""
    if not opportunities:
        return GameEvaluationValue(game_id, 0, 0, 0, 0, 0, [])

    qs = [o.get("calibrated_q", 0.5) or 0.5 for o in opportunities]
    decision_signal = float(np.std(qs))  # Variance = signal
    reviewability = min(1.0, len(opportunities) / 30)

    # Training value: has both good and bad examples
    bad_count = sum(1 for q in qs if q < 0.35)
    good_count = sum(1 for q in qs if q > 0.65)
    training_value = min(1.0, (bad_count + good_count) / max(len(qs), 1) * 2)

    # Badcase value: has clear mistakes
    badcase_value = min(1.0, bad_count / max(len(qs), 1) * 5)

    # Clean case value: has clear good play
    clean_case_value = min(1.0, good_count / max(len(qs), 1) * 3)

    # Recommendations
    uses = []
    if badcase_value > 0.3:
        uses.append("badcase_training")
    if clean_case_value > 0.4:
        uses.append("clean_case_benchmark")
    if training_value > 0.5:
        uses.append("pairwise_training")
    if reviewability > 0.5:
        uses.append("strategy_replay")
    if decision_signal > 0.2:
        uses.append("model_capability_leaderboard")

    return GameEvaluationValue(
        game_id=game_id,
        decision_signal=round(decision_signal, 4),
        reviewability=round(reviewability, 4),
        training_value=round(training_value, 4),
        badcase_value=round(badcase_value, 4),
        clean_case_value=round(clean_case_value, 4),
        recommended_use=uses,
    )
