"""Regenerate scoring models to match current 55-feature schema."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.scoring_models import DecisionQualityModel
from backend.eval.scoring_models import ModelFeatures
from backend.eval.scoring_models import OpportunityValueModel
from backend.eval.scoring_models import extract_features


def generate_synthetic_opportunities(n: int = 300) -> list[dict]:
    """Generate synthetic opportunities matching current feature layout."""
    rng = np.random.RandomState(42)
    opps = []
    roles = ["Werewolf", "Werewolf", "Seer", "Witch", "Guard", "Hunter", "Villager"]
    op_types = [
        "speech",
        "vote",
        "werewolf_kill",
        "seer_check",
        "witch_save",
        "witch_poison",
        "guard_protect",
        "hunter_shot",
        "seer_release",
        "witch_skip",
    ]
    alignments = ["Villager", "Villager", "Villager", "Villager", "Wolf", "Wolf"]

    for i in range(n):
        role = rng.choice(roles)
        op_type = rng.choice(op_types)
        target_alignment = rng.choice(alignments)
        day = rng.randint(1, 6)
        alive = rng.randint(3, 10)

        opp = {
            "opportunity_id": f"synth-{i:04d}",
            "game_id": f"game-synth-{i // 10:04d}",
            "player_id": f"P{i % 10 + 1}",
            "role": role,
            "opportunity_type": op_type,
            "day": int(day),
            "game_features": {
                "day": int(day),
                "alive_count": int(alive),
                "is_endgame": bool(alive <= 4),
                "village_alive": int(max(1, alive * 0.6)),
                "wolf_alive": int(max(1, alive * 0.3)),
            },
            "target_features": {
                "target_id": f"P{(i + 3) % 10 + 1}",
                "target_name": f"Player{(i + 3) % 10 + 1}",
                "target_role": rng.choice(roles),
                "target_alignment": target_alignment,
                "target_alive": bool(rng.random() > 0.3),
                "target_is_exposed": bool(rng.random() > 0.7),
            },
            "outcome_features": {
                "target_died_same_phase": bool(rng.random() > 0.7),
                "target_died_reason": rng.choice(["vote", "wolf", "hunter", "witch", ""]),
                "actor_died_same_phase": bool(rng.random() > 0.9),
            },
            "action_features": {
                "action_is_llm": True,
                "action_is_fallback": False,
                "action_parse_success": True,
            },
            "chosen_action": {
                "type": op_type,
                "target_id": f"P{(i + 3) % 10 + 1}",
                "speech": f"Synthetic speech for {role} on day {day}",
            },
            "private_features": {
                "has_confirmed_wolf": bool(rng.random() > 0.5),
                "has_confirmed_good": bool(rng.random() > 0.5),
                "target_is_confirmed_wolf": bool(rng.random() > 0.8),
                "target_is_confirmed_good": bool(rng.random() > 0.8),
                "info_should_release": bool(rng.random() > 0.6),
                "info_was_released": bool(rng.random() > 0.7),
                "info_withheld": bool(rng.random() > 0.8),
                "voted_elsewhere_despite_known_wolf": bool(rng.random() > 0.9),
                "risky_private_info_release": bool(rng.random() > 0.9),
                "consecutive_same_guard_target": bool(rng.random() > 0.9),
            },
            "embedding_features": {
                "nearest_good_similarity": float(rng.random() * 0.5 + 0.3),
                "nearest_bad_similarity": float(rng.random() * 0.5 + 0.3),
                "good_bad_similarity_margin": float(rng.random() * 0.4),
                "similar_good_avg_quality": float(rng.random() * 0.5 + 0.4),
                "similar_bad_avg_quality": float(rng.random() * 0.5 + 0.2),
            },
            "wolf_features": {
                "wolf_perspective_leak_score": float(rng.random() * 0.6),
                "teammate_overprotection": float(rng.random() * 0.5),
                "vote_coordination_failure": float(rng.random() * 0.4),
                "night_kill_target_value": float(rng.random()),
                "counterfactual_target_gap": float(rng.random() * 0.5),
                "speech_grounding_score": float(rng.random() * 0.6 + 0.3),
                "role_goal_conflict_score": float(rng.random() * 0.5),
                "lack_of_public_evidence_support": float(rng.random() * 0.5),
            },
        }
        opps.append(opp)
    return opps


def compute_quality_label(opp: dict, feats: ModelFeatures) -> float:
    """Compute synthetic quality label based on feature heuristics."""
    q = 0.5  # neutral baseline
    role = opp.get("role", "")
    op_type = opp.get("opportunity_type", "")

    # Good actions
    if op_type == "werewolf_kill" and feats.night_kill_target_value > 0.6:
        q += 0.25
    if op_type == "witch_save" and feats.target_role_is_good == 1:
        q += 0.20
    if op_type == "seer_check" and feats.target_role_is_wolf == 1:
        q += 0.25
    if op_type == "guard_protect" and feats.target_role_is_good == 1:
        q += 0.15

    # Bad actions
    if feats.wolf_perspective_leak_score > 0.5:
        q -= 0.35
    if feats.teammate_overprotection > 0.4:
        q -= 0.30
    if feats.role_goal_conflict_score > 0.5:
        q -= 0.25
    if feats.voted_elsewhere_despite_known_wolf:
        q -= 0.40
    if feats.lack_of_public_evidence_support > 0.5:
        q -= 0.20

    return round(max(0.05, min(0.95, q)), 4)


def main():
    print("Generating synthetic training data...")
    opps = generate_synthetic_opportunities(500)

    X_list = []
    y_w_list = []  # opportunity value
    y_q_list = []  # decision quality

    for opp in opps:
        try:
            feats = extract_features(opp)
            arr = feats.to_array()
            X_list.append(arr)

            # Pseudo-label: opportunity value
            op_type = opp["opportunity_type"]
            w = {
                "werewolf_kill": 1.0,
                "guard_protect": 0.8,
                "seer_check": 0.9,
                "witch_save": 0.9,
                "witch_poison": 0.95,
                "hunter_shot": 0.95,
                "witch_skip": 0.6,
                "seer_release": 0.7,
                "vote": 0.5,
                "speech": 0.4,
            }.get(op_type, 0.5)
            y_w_list.append(w)

            # Pseudo-label: decision quality
            q = compute_quality_label(opp, feats)
            y_q_list.append(q)
        except Exception as e:
            print(f"  skipping {opp['opportunity_id']}: {e}")

    X = np.array(X_list)
    y_w = np.array(y_w_list)
    y_q = np.array(y_q_list)

    n = len(X)
    feat_count = X.shape[1]
    print(f"Training data: {n} samples x {feat_count} features")
    print(f"w(y) range: [{y_w.min():.3f}, {y_w.max():.3f}]")
    print(f"q(y) range: [{y_q.min():.3f}, {y_q.max():.3f}]")

    # Train w model
    print("\nTraining OpportunityValueModel...")
    w_model = OpportunityValueModel()
    w_model.fit(X, y_w)
    w_path = ROOT / "data" / "health" / "opportunity_value_model.pkl"
    w_path.parent.mkdir(parents=True, exist_ok=True)
    w_model.save(w_path)
    print(f"Saved to {w_path}")

    # Train q model
    print("Training DecisionQualityModel...")
    q_model = DecisionQualityModel()
    # Convert to binary labels for classification
    y_q_binary = (y_q >= 0.5).astype(int)
    if len(set(y_q_binary)) < 2:
        print("ERROR: only one class in y_q, adding noise")
        y_q_binary[0] = 0
    q_model.fit(X, y_q_binary)
    q_path = ROOT / "data" / "health" / "decision_quality_model.pkl"
    q_model.save(q_path)
    print(f"Saved to {q_path}")

    # Verify
    print("\nVerifying...")
    w_model2 = OpportunityValueModel()
    w_model2.load(w_path)
    pred_w = w_model2.predict(X[:3])
    print(f"w_model predictions: {pred_w}")

    q_model2 = DecisionQualityModel()
    q_model2.load(q_path)
    pred_q = q_model2.predict(X[:3])
    print(f"q_model predictions: {pred_q}")

    # Test with cleancase fixture
    print("\nTesting with cleancase fixture...")
    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.scoring_models import calibrate_decision_quality
    from backend.eval.track_b import ReplayBundleBuilder
    from tests.test_track_b_cleancase_wolf_regression import build_cleancase_001_fixture

    state = build_cleancase_001_fixture()
    bundle = ReplayBundleBuilder().build(state)
    opps_test = OpportunityExtractor().extract(bundle)

    for op in opps_test:
        if op.player_id == "P2" and op.opportunity_type == "speech":
            feats = extract_features(op.to_dict())
            raw_q = float(q_model2.predict(feats.to_array().reshape(1, -1))[0])
            cal = calibrate_decision_quality(op.to_dict(), raw_q)
            print(f"  P2 speech: raw_q={raw_q:.4f}, cal_q={cal.calibrated_q:.4f}")
        if op.opportunity_type == "werewolf_kill":
            feats = extract_features(op.to_dict())
            raw_q = float(q_model2.predict(feats.to_array().reshape(1, -1))[0])
            cal = calibrate_decision_quality(op.to_dict(), raw_q)
            print(f"  {op.player_id} kill d{op.day}: raw_q={raw_q:.4f}, cal_q={cal.calibrated_q:.4f}")

    print("\nDone!")


if __name__ == "__main__":
    main()
