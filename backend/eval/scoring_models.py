"""Small structured models for opportunity-level scoring.

Phase 3+5 of Track B reconstruction (§5):
  - OpportunityValueModel: w(o) ∈ [0,1] — how important is this opportunity?
  - DecisionQualityModel: q(o) ∈ [0,1] — how good was the chosen action?
  - MistakeSeverityModel: severity(b) ∈ [0,1] — how severe is this mistake?

MVP uses LightGBM / Logistic Regression with pairwise training.
"""

from __future__ import annotations

import json
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

@dataclass
class ModelFeatures:
    """Feature vector for small scoring models."""

    # ---- Role encoding (one-hot) ----
    role_seer: int = 0
    role_witch: int = 0
    role_guard: int = 0
    role_hunter: int = 0
    role_werewolf: int = 0
    role_villager: int = 0

    # ---- Opportunity type encoding ----
    op_seer_check: int = 0
    op_witch_save: int = 0
    op_witch_poison: int = 0
    op_guard_protect: int = 0
    op_hunter_shot: int = 0
    op_werewolf_kill: int = 0
    op_vote: int = 0
    op_speech: int = 0

    # ---- Game context (§5.1) ----
    day: float = 1.0
    alive_count: float = 6.0
    is_endgame: int = 0
    village_alive: float = 3.0
    wolf_alive: float = 2.0
    camp_balance_ratio: float = 1.0  # village_alive / wolf_alive

    # ---- Target features ----
    target_role_is_good: int = -1  # -1 = no target
    target_role_is_wolf: int = -1
    target_alive: int = -1
    target_is_exposed: int = -1

    # ---- Outcome features ----
    target_died: int = -1
    target_died_reason_hunter: int = 0
    target_died_reason_vote: int = 0
    target_died_reason_wolf: int = 0
    target_died_reason_witch: int = 0

    # ---- Action features ----
    action_is_llm: int = 1
    action_is_fallback: int = 0
    action_parse_success: int = 1

    # ---- Embedding retrieval features (§6.3) ----
    nearest_good_similarity: float = 0.0
    nearest_bad_similarity: float = 0.0
    good_bad_similarity_margin: float = 0.0
    similar_good_avg_quality: float = 0.0
    similar_bad_avg_quality: float = 0.0

    def to_array(self) -> np.ndarray:
        return np.array([
            self.role_seer, self.role_witch, self.role_guard,
            self.role_hunter, self.role_werewolf, self.role_villager,
            self.op_seer_check, self.op_witch_save, self.op_witch_poison,
            self.op_guard_protect, self.op_hunter_shot, self.op_werewolf_kill,
            self.op_vote, self.op_speech,
            self.day, self.alive_count, self.is_endgame,
            self.village_alive, self.wolf_alive, self.camp_balance_ratio,
            self.target_role_is_good, self.target_role_is_wolf,
            self.target_alive, self.target_is_exposed,
            self.target_died, self.target_died_reason_hunter,
            self.target_died_reason_vote, self.target_died_reason_wolf,
            self.target_died_reason_witch,
            self.action_is_llm, self.action_is_fallback, self.action_parse_success,
            self.nearest_good_similarity, self.nearest_bad_similarity,
            self.good_bad_similarity_margin,
            self.similar_good_avg_quality, self.similar_bad_avg_quality,
        ], dtype=np.float32)

    FEATURE_NAMES = [
        "role_seer", "role_witch", "role_guard", "role_hunter", "role_werewolf", "role_villager",
        "op_seer_check", "op_witch_save", "op_witch_poison", "op_guard_protect",
        "op_hunter_shot", "op_werewolf_kill", "op_vote", "op_speech",
        "day", "alive_count", "is_endgame", "village_alive", "wolf_alive", "camp_balance_ratio",
        "target_role_is_good", "target_role_is_wolf", "target_alive", "target_is_exposed",
        "target_died", "target_died_reason_hunter", "target_died_reason_vote",
        "target_died_reason_wolf", "target_died_reason_witch",
        "action_is_llm", "action_is_fallback", "action_parse_success",
        "nearest_good_similarity", "nearest_bad_similarity", "good_bad_similarity_margin",
        "similar_good_avg_quality", "similar_bad_avg_quality",
    ]


def extract_features(opportunity: dict[str, Any]) -> ModelFeatures:
    """Extract ModelFeatures from a DecisionOpportunity dict."""
    role = opportunity.get("role", "")
    op_type = opportunity.get("opportunity_type", "")
    game_feat = opportunity.get("game_features", {})
    target_feat = opportunity.get("target_features", {})
    outcome_feat = opportunity.get("outcome_features", {})
    chosen = opportunity.get("chosen_action", {})
    if not isinstance(chosen, dict):
        chosen = {}

    # Role encoding
    feats = ModelFeatures()
    role_map = {
        "Seer": "role_seer", "Witch": "role_witch", "Guard": "role_guard",
        "Hunter": "role_hunter", "Werewolf": "role_werewolf", "Villager": "role_villager",
    }
    if role in role_map:
        setattr(feats, role_map[role], 1)

    # Opportunity type encoding
    op_map = {
        "seer_check": "op_seer_check", "witch_save": "op_witch_save",
        "witch_poison": "op_witch_poison", "guard_protect": "op_guard_protect",
        "hunter_shot": "op_hunter_shot", "werewolf_kill": "op_werewolf_kill",
        "vote": "op_vote", "speech": "op_speech",
    }
    if op_type in op_map:
        setattr(feats, op_map[op_type], 1)

    # Game context
    feats.day = float(opportunity.get("day", 1))
    feats.alive_count = float(game_feat.get("alive_count", 6))
    feats.is_endgame = 1 if game_feat.get("is_endgame") else 0
    cb = game_feat.get("camp_balance", {})
    feats.village_alive = float(cb.get("village_alive", 3))
    feats.wolf_alive = float(cb.get("wolf_alive", 2))
    feats.camp_balance_ratio = feats.village_alive / max(feats.wolf_alive, 1)

    # Target features
    if target_feat:
        alignment = target_feat.get("target_alignment", "")
        feats.target_role_is_good = 1 if alignment == "village" else 0
        feats.target_role_is_wolf = 1 if alignment == "wolf" else 0
        feats.target_alive = 1 if target_feat.get("target_alive") else 0
        feats.target_is_exposed = 1 if target_feat.get("target_is_exposed") else 0

    # Outcome features
    if outcome_feat:
        feats.target_died = 1 if outcome_feat.get("target_died_same_phase") else 0
        reason = outcome_feat.get("target_died_reason", "") or ""
        for r, field in [("hunter", "target_died_reason_hunter"), ("vote", "target_died_reason_vote"),
                         ("wolf", "target_died_reason_wolf"), ("witch", "target_died_reason_witch")]:
            if r in reason:
                setattr(feats, field, 1)

    # Action features
    metadata = chosen.get("metadata", {}) if isinstance(chosen, dict) else {}
    feats.action_is_llm = 1 if metadata.get("source") == "llm" else 0
    feats.action_is_fallback = 1 if metadata.get("fallback") else 0
    feats.action_parse_success = 0 if metadata.get("fallback") else 1

    return feats


# ---------------------------------------------------------------------------
# Scikit-learn wrapper models
# ---------------------------------------------------------------------------

class OpportunityValueModel:
    """w(o): predict how important an opportunity is. §5.1"""

    def __init__(self):
        self.model = None
        self.feature_importances_: dict[str, float] = {}

    def fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.linear_model import LogisticRegression
        self.model = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.model.fit(X, y)
        self.feature_importances_ = dict(
            zip(ModelFeatures.FEATURE_NAMES, np.abs(self.model.coef_[0]))
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None or not hasattr(self.model, 'classes_'):
            return np.full(len(X), 0.5)
        return self.model.predict_proba(X)[:, 1]

    def save(self, path: str | Path):
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "importances": self.feature_importances_}, f)

    def load(self, path: str | Path):
        with open(path, "rb") as f:
            data = pickle.load(f)
            self.model = data["model"]
            self.feature_importances_ = data.get("importances", {})


class DecisionQualityModel:
    """q(o): predict action quality. §5.2 — pairwise training preferred."""

    def __init__(self):
        self.model = None
        self.feature_importances_: dict[str, float] = {}

    def fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.ensemble import GradientBoostingClassifier
        self.model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42,
        )
        self.model.fit(X, y)
        self.feature_importances_ = dict(
            zip(ModelFeatures.FEATURE_NAMES, self.model.feature_importances_)
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None or not hasattr(self.model, 'classes_'):
            return np.full(len(X), 0.5)
        return self.model.predict_proba(X)[:, 1]

    def predict_pairwise(self, X_a: np.ndarray, X_b: np.ndarray) -> np.ndarray:
        """P(A > B) = sigmoid(F(A) - F(B)). §5.2"""
        scores_a = self.predict(X_a)
        scores_b = self.predict(X_b)
        diff = scores_a - scores_b
        return 1.0 / (1.0 + np.exp(-diff))

    def save(self, path: str | Path):
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "importances": self.feature_importances_}, f)

    def load(self, path: str | Path):
        with open(path, "rb") as f:
            data = pickle.load(f)
            self.model = data["model"]
            self.feature_importances_ = data.get("importances", {})


class MistakeSeverityModel:
    """severity(b): predict mistake severity. §5.3"""

    def __init__(self):
        self.model = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.linear_model import Ridge
        self.model = Ridge(alpha=1.0)
        self.model.fit(X, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.model is None or not hasattr(self.model, 'coef_'):
            return np.full(len(X), 0.5)
        return np.clip(self.model.predict(X), 0.0, 1.0)

    def save(self, path: str | Path):
        with open(path, "wb") as f:
            pickle.dump(self.model, f)

    def load(self, path: str | Path):
        with open(path, "rb") as f:
            self.model = pickle.load(f)


# ---------------------------------------------------------------------------
# ProcessScore calculator (§2.11)
# ---------------------------------------------------------------------------

@dataclass
class ProcessScoreResult:
    """Per-player process score breakdown."""
    player_id: str
    role: str
    adjusted_role_process_score: float
    speech_score: float
    counterfactual_impact: float
    mistake_penalty: float
    robustness_score: float
    process_score: float
    num_opportunities: int
    total_weight: float


def calculate_process_score(
    opportunities: list[dict[str, Any]],
    opportunity_value_model: OpportunityValueModel | None = None,
    decision_quality_model: DecisionQualityModel | None = None,
    speech_scores: dict[str, float] | None = None,
) -> list[ProcessScoreResult]:
    """Calculate process scores following goal doc §2.4-2.11."""
    from collections import defaultdict

    # Group by player
    by_player: dict[str, list[dict]] = defaultdict(list)
    for opp in opportunities:
        by_player[opp["player_id"]].append(opp)

    results: list[ProcessScoreResult] = []
    w_model = opportunity_value_model
    q_model = decision_quality_model

    for player_id, opps in by_player.items():
        role = opps[0].get("role", "unknown")

        # Compute opportunity-level scores
        weights = []
        qualities = []
        for opp in opps:
            feats = extract_features(opp)
            X = feats.to_array().reshape(1, -1)
            w = w_model.predict(X)[0] if w_model else 0.5
            q = q_model.predict(X)[0] if q_model else 0.5
            weights.append(w)
            qualities.append(q)

        total_w = sum(weights)
        role_process = (
            sum(w * q for w, q in zip(weights, qualities)) / total_w
            if total_w > 0 else 0.5
        )

        # Bayesian smoothing for low-opportunity roles (§2.6)
        k = 2.0
        mu_role = 0.5  # Default mean; should be calibrated per role
        alpha = total_w / (total_w + k)
        adjusted_process = alpha * role_process + (1 - alpha) * mu_role

        # Speech score
        speech = speech_scores.get(player_id, 0.5) if speech_scores else 0.5

        # Robustness
        n_opps = len(opps)
        n_fallback = sum(1 for o in opps if o.get("chosen_action", {}).get("metadata", {}).get("fallback"))
        robustness = 1.0 - (n_fallback / max(n_opps, 1))

        # Simplified mistake penalty and counterfactual (placeholder for MVP)
        mistake_penalty = 0.0
        counterfactual_impact = 0.0

        # Process score formula (§2.11)
        process_score = (
            0.40 * adjusted_process
            + 0.20 * speech
            + 0.15 * counterfactual_impact
            + 0.15 * (1.0 - mistake_penalty)
            + 0.10 * robustness
        )

        results.append(ProcessScoreResult(
            player_id=player_id,
            role=role,
            adjusted_role_process_score=round(adjusted_process, 4),
            speech_score=round(speech, 4),
            counterfactual_impact=round(counterfactual_impact, 4),
            mistake_penalty=round(mistake_penalty, 4),
            robustness_score=round(robustness, 4),
            process_score=round(process_score, 4),
            num_opportunities=n_opps,
            total_weight=round(total_w, 2),
        ))

    return results
