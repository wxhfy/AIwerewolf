"""Phase 3+5: Train small scoring models + run ablation experiments.

Follows goal doc §5 and §8:
  - OpportunityValueModel: w(o)
  - DecisionQualityModel: q(o)
  - MistakeSeverityModel: severity(b)

Uses GroupKFold by game_id (NOT random split).
Ablation: A (old rule) vs B (opportunity-only rule) vs C (+ small models).

Run: python scripts/train_and_ablate.py [--limit N]
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.eval.scoring_models import DecisionQualityModel
from backend.eval.scoring_models import OpportunityValueModel
from backend.eval.scoring_models import extract_features

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_opportunities(path: str = "data/health/opportunities.jsonl") -> list[dict]:
    opps = []
    with open(ROOT / path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                opps.append(json.loads(line))
    return opps


def load_labeled(path: str = "data/health/labeled_opportunities.jsonl") -> list[dict]:
    labeled = []
    with open(ROOT / path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                labeled.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return labeled


def load_baseline(path: str = "data/health/baseline_scoring_report.json") -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Group-aware splitting
# ---------------------------------------------------------------------------


def group_kfold_split(opportunities: list[dict], n_splits: int = 5) -> list[tuple[list, list]]:
    """Split opportunities by game_id for GroupKFold."""
    game_ids = sorted(set(o["game_id"] for o in opportunities))
    random.seed(42)
    random.shuffle(game_ids)

    fold_size = max(1, len(game_ids) // n_splits)
    folds = []
    for i in range(n_splits):
        start = i * fold_size
        end = start + fold_size if i < n_splits - 1 else len(game_ids)
        test_games = set(game_ids[start:end])
        train_games = set(game_ids[:start]) | set(game_ids[end:])

        train = [o for o in opportunities if o["game_id"] in train_games]
        test = [o for o in opportunities if o["game_id"] in test_games]
        folds.append((train, test))

    return folds


# ---------------------------------------------------------------------------
# Rule-based opportunity scoring (Ablation B)
# ---------------------------------------------------------------------------


def rule_opportunity_value(opp: dict) -> float:
    """Rule-based opportunity importance w(o)."""
    op_type = opp.get("opportunity_type", "")
    game_feat = opp.get("game_features", {})
    day = opp.get("day", 1)
    alive = game_feat.get("alive_count", 6)
    is_endgame = game_feat.get("is_endgame", False)

    # Night actions are high-value
    base = {
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

    # Endgame bonus
    if is_endgame:
        base = min(1.0, base * 1.3)
    # Late game bonus
    if alive <= 4:
        base = min(1.0, base * 1.2)

    return min(1.0, base)


def rule_decision_quality(opp: dict) -> float:
    """Rule-based decision quality q(o)."""
    target_feat = opp.get("target_features", {})
    outcome_feat = opp.get("outcome_features", {})
    role = opp.get("role", "")
    op_type = opp.get("opportunity_type", "")

    quality = 0.5  # Default neutral

    # Good: target is wolf
    if target_feat.get("target_alignment") == "wolf":
        quality += 0.3
    # Bad: target is good
    elif target_feat.get("target_alignment") == "village":
        quality -= 0.1

    # Good: target died (action had effect)
    if outcome_feat.get("target_died_same_phase"):
        if target_feat.get("target_alignment") == "wolf":
            quality += 0.2
        elif target_feat.get("target_alignment") == "village":
            quality -= 0.2

    # Role-specific bonuses
    if role == "Witch" and op_type == "witch_save":
        # Saving is generally good
        quality += 0.1
    elif role == "Guard" and op_type == "guard_protect":
        if outcome_feat.get("actor_died_same_phase"):
            quality -= 0.1  # Guard died = bad positioning
    elif role == "Hunter" and op_type == "hunter_shot":
        if target_feat.get("target_alignment") == "wolf":
            quality += 0.3  # Shooting wolf is excellent
        else:
            quality -= 0.3  # Shooting good is terrible

    return max(0.0, min(1.0, quality))


# ---------------------------------------------------------------------------
# Training with GroupKFold
# ---------------------------------------------------------------------------


@dataclass
class TrainingResult:
    model_name: str
    fold_metrics: list[dict[str, float]]
    feature_importances: dict[str, float]
    predictions: list[dict[str, Any]]


def train_opportunity_value_model(
    labeled: list[dict],
    opportunities: list[dict],
    n_splits: int = 5,
) -> TrainingResult:
    """Train OpportunityValueModel with GroupKFold."""
    # Build training data: use rule-based w(o) as pseudo-label for MVP
    opp_by_id = {o["opportunity_id"]: o for o in opportunities}
    X_list, y_list, game_ids_list = [], [], []

    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        X_list.append(feats.to_array())
        w = rule_opportunity_value(opp)
        # Adjust by label quality
        label_qs = item.get("label", {}).get("quality_score")
        if label_qs is not None:
            w = 0.7 * w + 0.3 * (label_qs / 100.0)
        y_list.append(w)
        game_ids_list.append(opp["game_id"])

    X = np.array(X_list)
    y = np.array(y_list)
    game_ids_arr = np.array(game_ids_list)

    folds = group_kfold_split(opportunities, n_splits)
    fold_metrics = []
    all_importances: list[dict[str, float]] = []

    model = OpportunityValueModel()
    for fold_i, (train_opps, test_opps) in enumerate(folds):
        train_games = set(o["game_id"] for o in train_opps)
        test_games = set(o["game_id"] for o in test_opps)

        train_mask = np.isin(game_ids_arr, list(train_games))
        test_mask = np.isin(game_ids_arr, list(test_games))

        if train_mask.sum() < 5 or test_mask.sum() < 2:
            continue

        try:
            model.fit(X[train_mask], y[train_mask])
        except Exception:
            continue

        y_pred = model.predict(X[test_mask])
        mse = float(np.mean((y[test_mask] - y_pred) ** 2))
        mae = float(np.mean(np.abs(y[test_mask] - y_pred)))
        fold_metrics.append(
            {
                "fold": fold_i,
                "mse": round(mse, 4),
                "mae": round(mae, 4),
                "n_train": int(train_mask.sum()),
                "n_test": int(test_mask.sum()),
            }
        )
        all_importances.append(model.feature_importances_)

    # Average importances
    avg_importances: dict[str, float] = {}
    if all_importances:
        for key in all_importances[0]:
            avg_importances[key] = round(float(np.mean([imp.get(key, 0) for imp in all_importances])), 6)

    # Predict on all data for analysis
    predictions = []
    for i, item in enumerate(labeled):
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        w_pred = model.predict(feats.to_array().reshape(1, -1))[0]
        predictions.append(
            {
                "opportunity_id": item["opportunity_id"],
                "role": opp["role"],
                "op_type": opp["opportunity_type"],
                "w_predicted": round(float(w_pred), 4),
                "w_rule": round(y_list[i] if i < len(y_list) else 0.0, 4),
            }
        )

    return TrainingResult(
        model_name="OpportunityValueModel",
        fold_metrics=fold_metrics,
        feature_importances=avg_importances,
        predictions=predictions,
    )


def train_decision_quality_model(
    labeled: list[dict],
    opportunities: list[dict],
    n_splits: int = 5,
) -> TrainingResult:
    """Train DecisionQualityModel with GroupKFold."""
    opp_by_id = {o["opportunity_id"]: o for o in opportunities}
    X_list, y_list, game_ids_list = [], [], []

    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        X_list.append(feats.to_array())

        # Use label quality_score as target
        label = item.get("label", {})
        qs = label.get("quality_score")
        if qs is not None:
            y_list.append(qs / 100.0)
        else:
            # Fallback: rule-based
            y_list.append(rule_decision_quality(opp))

        game_ids_list.append(opp["game_id"])

    X = np.array(X_list)
    y = np.array(y_list)
    game_ids_arr = np.array(game_ids_list)

    folds = group_kfold_split(opportunities, n_splits)
    fold_metrics = []
    all_importances: list[dict[str, float]] = []

    model = DecisionQualityModel()
    for fold_i, (train_opps, test_opps) in enumerate(folds):
        train_games = set(o["game_id"] for o in train_opps)
        test_games = set(o["game_id"] for o in test_opps)

        train_mask = np.isin(game_ids_arr, list(train_games))
        test_mask = np.isin(game_ids_arr, list(test_games))

        if train_mask.sum() < 5 or test_mask.sum() < 2:
            continue

        # Convert to binary for classification
        y_binary = (y[train_mask] >= 0.5).astype(int)
        y_test_binary = (y[test_mask] >= 0.5).astype(int)
        if len(set(y_binary)) < 2:
            continue

        try:
            model.fit(X[train_mask], y_binary)
        except Exception:
            continue

        y_pred = model.predict(X[test_mask])
        accuracy = float(np.mean((y_pred >= 0.5) == y_test_binary))

        # Pairwise accuracy
        if len(y_pred) >= 2:
            n_correct = 0
            n_pairs = 0
            for i in range(len(y_pred)):
                for j in range(i + 1, len(y_pred)):
                    if y_test_binary[i] != y_test_binary[j]:
                        n_pairs += 1
                        if (y_pred[i] > y_pred[j]) == (y_test_binary[i] > y_test_binary[j]):
                            n_correct += 1
            pairwise_acc = n_correct / max(n_pairs, 1)
        else:
            pairwise_acc = 0.5

        fold_metrics.append(
            {
                "fold": fold_i,
                "accuracy": round(accuracy, 4),
                "pairwise_accuracy": round(pairwise_acc, 4),
                "n_train": int(train_mask.sum()),
                "n_test": int(test_mask.sum()),
            }
        )
        all_importances.append(model.feature_importances_)

    avg_importances: dict[str, float] = {}
    if all_importances:
        for key in all_importances[0]:
            avg_importances[key] = round(float(np.mean([imp.get(key, 0) for imp in all_importances])), 6)

    return TrainingResult(
        model_name="DecisionQualityModel",
        fold_metrics=fold_metrics,
        feature_importances=avg_importances,
        predictions=[],
    )


# ---------------------------------------------------------------------------
# Ablation comparison
# ---------------------------------------------------------------------------


@dataclass
class AblationResult:
    system: str
    per_role: dict[str, dict[str, float]]
    pairwise_accuracy: float
    cohens_d: dict[str, float]


def compute_ablation(
    opportunities: list[dict], labeled: list[dict], q_model: DecisionQualityModel | None = None
) -> dict[str, AblationResult]:
    """Run ablation A/B/C comparison."""
    from sqlalchemy import text

    from backend.db.database import SessionLocal
    from backend.db.database import init_db

    # Load outcome data
    init_db()
    db = SessionLocal()
    clean_ids = set(json.loads(Path("/tmp/clean_llm_game_ids.json").read_text()))
    games = db.execute(text("SELECT id, winner FROM games WHERE id IN :ids"), {"ids": tuple(clean_ids)}).fetchall()
    winner_map = {g[0]: g[1] for g in games}
    db.close()

    # Map opportunity_id to game_id
    opp_game_map = {o["opportunity_id"]: o["game_id"] for o in opportunities}
    opp_role_map = {o["opportunity_id"]: o["role"] for o in opportunities}

    # Collect scores per player per system
    by_player: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for item in labeled:
        opp_id = item["opportunity_id"]
        game_id = opp_game_map.get(opp_id, "")
        role = opp_role_map.get(opp_id, "")
        winner = winner_map.get(game_id, "")
        player_id = item.get("player_id", opp_id.split("-")[2] if "-" in opp_id else "unknown")

        label = item.get("label", {})
        qs = label.get("quality_score", 50)

        # System A: old rule baseline (map from stored baseline)
        # We compute B and C here, A comes from baseline_scoring_report.json

        # System B: rule-based opportunity score
        opp = next((o for o in opportunities if o["opportunity_id"] == opp_id), None)
        if opp:
            w_b = rule_opportunity_value(opp)
            q_b = rule_decision_quality(opp)
            score_b = w_b * q_b
            by_player[f"B:{player_id}"][role].append(score_b)

            # System C: rule w + model q
            if q_model:
                feats = extract_features(opp)
                q_c = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
                w_c = w_b  # Same rule-based w for now
                score_c = w_c * q_c
                by_player[f"C:{player_id}"][role].append(score_c)

    # Aggregate per player
    def aggregate(scores_dict):
        per_role_scores = defaultdict(list)
        for key, role_scores in scores_dict.items():
            system, player_id = key.split(":", 1)
            for role, scores in role_scores.items():
                if scores:
                    avg = statistics.mean(scores)
                    per_role_scores[role].append({"player": player_id, "score": avg})
        return per_role_scores

    # Build results
    results = {}

    # System A: from baseline
    baseline = load_baseline()
    a_role = baseline.get("role_summary", {})

    # System B
    b_agg = aggregate(dict(by_player))

    results["A_old_rule"] = AblationResult(
        system="A: Old Rule Baseline",
        per_role={r: {"mean": d.get("mean_adjusted", 0), "cohens_d": d.get("cohens_d", 0)} for r, d in a_role.items()},
        pairwise_accuracy=0.0,
        cohens_d={r: d.get("cohens_d", 0) for r, d in a_role.items()},
    )

    # System B
    b_role_stats = {}
    for role, scores in b_agg.items():
        vals = [s["score"] for s in scores]
        if len(vals) >= 2:
            b_role_stats[role] = {"mean": round(statistics.mean(vals), 3), "n": len(vals)}

    results["B_opportunity_rule"] = AblationResult(
        system="B: Opportunity Rule",
        per_role=b_role_stats,
        pairwise_accuracy=0.0,
        cohens_d={},
    )

    # System C
    c_agg = aggregate(dict(by_player))
    c_role_stats = {}
    for role, scores in c_agg.items():
        vals = [s["score"] for s in scores]
        if len(vals) >= 2:
            c_role_stats[role] = {"mean": round(statistics.mean(vals), 3), "n": len(vals)}

    results["C_small_models"] = AblationResult(
        system="C: Opportunity + Small Models",
        per_role=c_role_stats,
        pairwise_accuracy=0.0,
        cohens_d={},
    )

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_reports(
    ovm_result: TrainingResult,
    dqm_result: TrainingResult,
    ablation: dict[str, AblationResult],
    output_dir: Path,
):
    """Generate model_metrics.json, feature_importance.md, prediction_examples.md,
    and learned_evaluator_ablation_report.md."""

    # 1. model_metrics.json
    metrics = {
        "OpportunityValueModel": {
            "fold_metrics": ovm_result.fold_metrics,
            "mean_mae": round(statistics.mean([m["mae"] for m in ovm_result.fold_metrics]), 4)
            if ovm_result.fold_metrics
            else 0,
        },
        "DecisionQualityModel": {
            "fold_metrics": dqm_result.fold_metrics,
            "mean_accuracy": round(statistics.mean([m["accuracy"] for m in dqm_result.fold_metrics]), 4)
            if dqm_result.fold_metrics
            else 0,
            "mean_pairwise_accuracy": round(
                statistics.mean([m["pairwise_accuracy"] for m in dqm_result.fold_metrics]), 4
            )
            if dqm_result.fold_metrics
            else 0,
        },
    }
    (output_dir / "model_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))

    # 2. feature_importance.md
    lines = ["# Feature Importance (DecisionQualityModel)", ""]
    sorted_feats = (
        sorted(dqm_result.feature_importances.items(), key=lambda x: -x[1]) if dqm_result.feature_importances else []
    )
    lines.append("| Feature | Importance |")
    lines.append("|---------|------------|")
    for name, imp in sorted_feats[:15]:
        lines.append(f"| {name} | {imp:.6f} |")
    (output_dir / "feature_importance.md").write_text("\n".join(lines))

    # 3. prediction_examples.md
    lines = ["# Prediction Examples", ""]
    good_preds = sorted(ovm_result.predictions, key=lambda x: -x["w_predicted"])[:5]
    bad_preds = sorted(ovm_result.predictions, key=lambda x: x["w_predicted"])[:5]
    lines.append("## Top 5 Highest Value Opportunities")
    for p in good_preds:
        lines.append(f"- [{p['role']}] {p['op_type']}: w={p['w_predicted']:.3f} (rule={p['w_rule']:.3f})")
    lines.append("")
    lines.append("## Top 5 Lowest Value Opportunities")
    for p in bad_preds:
        lines.append(f"- [{p['role']}] {p['op_type']}: w={p['w_predicted']:.3f} (rule={p['w_rule']:.3f})")
    (output_dir / "prediction_examples.md").write_text("\n".join(lines))

    # 4. learned_evaluator_ablation_report.md
    lines = [
        "# Learned Evaluator Ablation Report",
        "",
        "## Systems Compared",
        "- **A**: Old Rule Baseline (camp_result + role_task + vote + speech + skill + survival)",
        "- **B**: Opportunity-Only Rule (w(o) × q(o) with heuristic rules)",
        "- **C**: Opportunity + Small Models (w(o) rule, q(o) from LightGBM/LogisticRegression)",
        "",
        "## Per-Role Cohen's d (Good vs Bad Separation)",
        "| Role | A (Old Rule) | B (Rule Opp) | C (Small Models) | Target |",
        "|------|-------------|-------------|------------------|--------|",
    ]
    for role in ["Werewolf", "Seer", "Witch", "Guard", "Hunter", "Villager"]:
        a_d = ablation.get("A_old_rule", AblationResult("", {}, 0, {})).cohens_d.get(role, 0)
        b_d = 0.0  # placeholder
        c_d = 0.0  # placeholder
        target = {"Witch": ">=0.5", "Guard": ">=0.3", "Hunter": ">=0.5"}.get(role, ">=0.5")
        lines.append(f"| {role} | {a_d:.3f} | {b_d:.3f} | {c_d:.3f} | {target} |")

    lines += [
        "",
        "## Pairwise Accuracy",
        f"DecisionQualityModel mean pairwise accuracy: {metrics['DecisionQualityModel'].get('mean_pairwise_accuracy', 0):.3f}",
        "",
        "## Witch / Guard / Hunter Improvement",
        "| Role | Old Rule Issue | New Model Fix | Status |",
        "|------|---------------|---------------|--------|",
        "| Witch | Outcome-dependent (poison=bad if hit good regardless of evidence) | Evidence-weighted quality score | Pending validation |",
        "| Guard | Only scored on 'did guard block a kill' | Strategy quality scored regardless of wolf target | Pending validation |",
        "| Hunter | Low-opportunity, max 1 shot/game | Restraint + shot quality weighted by suspicion | Pending validation |",
    ]
    (output_dir / "learned_evaluator_ablation_report.md").write_text("\n".join(lines))

    print(f"\nReports generated in {output_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--output-dir", default="data/health")
    args = ap.parse_args()

    out_dir = ROOT / args.output_dir

    # Load data
    print("Loading data...")
    opportunities = load_opportunities()
    print(f"  {len(opportunities)} opportunities")

    try:
        labeled = load_labeled()
        print(f"  {len(labeled)} labeled samples")
    except FileNotFoundError:
        print("  No labeled data yet. Run label_opportunities_fast.py first.")
        return 1

    if args.limit:
        opportunities = opportunities[: args.limit]
        labeled = labeled[: args.limit]

    # Train models
    print("\n=== Training OpportunityValueModel ===")
    ovm_result = train_opportunity_value_model(labeled, opportunities)
    print(
        f"  Folds: {len(ovm_result.fold_metrics)}, Mean MAE: {statistics.mean([m['mae'] for m in ovm_result.fold_metrics]):.4f}"
        if ovm_result.fold_metrics
        else "  No folds trained"
    )

    print("\n=== Training DecisionQualityModel ===")
    dqm_result = train_decision_quality_model(labeled, opportunities)
    print(
        f"  Folds: {len(dqm_result.fold_metrics)}, Mean Accuracy: {statistics.mean([m['accuracy'] for m in dqm_result.fold_metrics]):.4f}"
        if dqm_result.fold_metrics
        else "  No folds trained"
    )
    if dqm_result.fold_metrics:
        paw = statistics.mean([m["pairwise_accuracy"] for m in dqm_result.fold_metrics])
        print(f"  Mean Pairwise Accuracy: {paw:.4f}")

    # Ablation
    print("\n=== Running Ablation A/B/C ===")
    q_model = DecisionQualityModel()
    # Train on all data for ablation
    all_X, all_y = [], []
    opp_by_id = {o["opportunity_id"]: o for o in opportunities}
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        all_X.append(feats.to_array())
        label_qs = item.get("label", {}).get("quality_score")
        all_y.append((label_qs / 100.0) if label_qs is not None else rule_decision_quality(opp))

    if len(set(int(y >= 0.5) for y in all_y)) >= 2:
        q_model.fit(np.array(all_X), np.array([int(y >= 0.5) for y in all_y]))

    # Train final OpportunityValueModel on all labeled data
    print("\n=== Training final models on all data ===")
    ovm_final = OpportunityValueModel()
    ovm_X, ovm_y = [], []
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        ovm_X.append(feats.to_array())
        w = rule_opportunity_value(opp)
        label_qs = item.get("label", {}).get("quality_score")
        if label_qs is not None:
            w = 0.7 * w + 0.3 * (label_qs / 100.0)
        ovm_y.append(w)

    if len(ovm_X) >= 5:
        ovm_final.fit(np.array(ovm_X), np.array(ovm_y))
        print(f"  OVM trained on {len(ovm_X)} samples")
    else:
        print("  OVM: insufficient data, skipping")

    ablation = compute_ablation(opportunities, labeled, q_model)
    print(f"  Systems: {list(ablation.keys())}")

    # Generate reports
    print("\n=== Generating Reports ===")
    generate_reports(ovm_result, dqm_result, ablation, out_dir)

    # Save models
    out_dir.mkdir(parents=True, exist_ok=True)
    ovm_path = out_dir / "opportunity_value_model.pkl"
    dqm_path = out_dir / "decision_quality_model.pkl"
    if ovm_final.model is not None:
        ovm_final.save(ovm_path)
        print(f"  OVM saved to {ovm_path}")
    if q_model.model is not None:
        q_model.save(dqm_path)
        print(f"  DQM saved to {dqm_path}")

    print(f"\nDone! Reports in {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
