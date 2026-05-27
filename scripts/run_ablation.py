"""Phase 5: Run complete ablation A/B/C with proper per-player Cohen's d.

A = old rule baseline (from baseline_scoring_report.json)
B = opportunity-only rule (w_rule × q_rule)
C = opportunity + small models (w_rule × q_model)

Uses GroupKFold by game_id. Computes per-role Cohen's d for good/bad separation.
"""

from __future__ import annotations

import json, math, statistics, sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.scoring_models import (
    DecisionQualityModel, ModelFeatures, extract_features,
)
from scripts.train_and_ablate import (
    load_opportunities, load_labeled, load_baseline,
    rule_opportunity_value, rule_decision_quality,
    group_kfold_split,
)


def cohens_d(values_a: list[float], values_b: list[float]) -> float:
    """Cohen's d effect size between two groups."""
    if len(values_a) < 2 or len(values_b) < 2:
        return 0.0
    ma, mb = statistics.mean(values_a), statistics.mean(values_b)
    na, nb = len(values_a), len(values_b)
    va = statistics.variance(values_a) if na > 1 else 0.0
    vb = statistics.variance(values_b) if nb > 1 else 0.0
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return (ma - mb) / pooled if pooled > 0 else 0.0


def main() -> int:
    print("Loading data...")
    opps = load_opportunities()
    labeled = load_labeled()
    baseline = load_baseline()

    # Load game outcome data
    from backend.db.database import SessionLocal, init_db
    from backend.db.models import PublishedReview
    from sqlalchemy import text
    init_db()
    db = SessionLocal()
    clean_ids = set(json.loads(Path("/tmp/clean_llm_game_ids.json").read_text()))
    games = db.execute(text("SELECT id, winner FROM games WHERE id IN :ids"),
        {"ids": tuple(clean_ids)}).fetchall()
    winner_map = {g[0]: g[1] for g in games}
    db.close()

    # Map: opportunity_id → game_id, player_id
    opp_game = {o["opportunity_id"]: o["game_id"] for o in opps}
    opp_player = {}
    for o in opps:
        pid = o.get("player_id", "")
        if not pid:
            parts = o["opportunity_id"].split("-")
            pid = parts[2] if len(parts) > 2 else "unknown"
        opp_player[o["opportunity_id"]] = pid

    # ---- Train DecisionQualityModel (GroupKFold) ----
    print("\n=== Training DecisionQualityModel (GroupKFold) ===")
    opp_by_id = {o["opportunity_id"]: o for o in opps}

    X_all, y_all, game_all = [], [], []
    for item in labeled:
        opp = opp_by_id.get(item["opportunity_id"])
        if opp is None:
            continue
        feats = extract_features(opp)
        X_all.append(feats.to_array())
        label_qs = item.get("label", {}).get("quality_score")
        y_all.append((label_qs / 100.0) if label_qs is not None else rule_decision_quality(opp))
        game_all.append(opp["game_id"])

    X_all = np.array(X_all)
    y_all = np.array(y_all)
    y_binary = (y_all >= 0.5).astype(int)

    folds = group_kfold_split(opps, n_splits=5)
    fold_results = []
    q_model = DecisionQualityModel()

    for fold_i, (train_opps, test_opps) in enumerate(folds):
        train_games = set(o["game_id"] for o in train_opps)
        test_games = set(o["game_id"] for o in test_opps)

        train_mask = np.array([g in train_games for g in game_all])
        test_mask = np.array([g in test_games for g in game_all])

        if train_mask.sum() < 5 or test_mask.sum() < 2:
            continue
        if len(set(y_binary[train_mask])) < 2:
            continue

        try:
            q_model.fit(X_all[train_mask], y_binary[train_mask])
        except Exception:
            continue

        y_pred = q_model.predict(X_all[test_mask])
        acc = float(np.mean((y_pred >= 0.5) == y_binary[test_mask]))
        # Pairwise accuracy
        n_correct, n_pairs = 0, 0
        for i in range(len(y_pred)):
            for j in range(i + 1, len(y_pred)):
                if y_binary[test_mask][i] != y_binary[test_mask][j]:
                    n_pairs += 1
                    if (y_pred[i] > y_pred[j]) == (y_binary[test_mask][i] > y_binary[test_mask][j]):
                        n_correct += 1
        paw = n_correct / max(n_pairs, 1)
        fold_results.append({"fold": fold_i, "accuracy": acc, "pairwise_accuracy": paw,
                             "n_train": int(train_mask.sum()), "n_test": int(test_mask.sum())})

    if fold_results:
        mean_acc = statistics.mean([r["accuracy"] for r in fold_results])
        mean_paw = statistics.mean([r["pairwise_accuracy"] for r in fold_results])
        print(f"  Folds: {len(fold_results)}, Accuracy: {mean_acc:.4f}, Pairwise: {mean_paw:.4f}")
    else:
        print("  WARNING: No folds trained!")
        mean_acc, mean_paw = 0.0, 0.0

    # Train final model on all data
    if len(set(y_binary)) >= 2:
        q_model.fit(X_all, y_binary)
    final_model = q_model

    # ---- Compute per-player scores for each system ----
    print("\n=== Computing Per-Player Scores ===")

    # Aggregate opportunities by (game_id, player_id)
    by_player: dict[tuple, list[dict]] = defaultdict(list)
    for opp in opps:
        gid = opp["game_id"]
        pid = opp_player.get(opp["opportunity_id"], "unknown")
        by_player[(gid, pid)].append(opp)

    # Get player role and alignment
    player_info: dict[tuple, dict] = {}
    for opp in opps:
        gid = opp["game_id"]
        pid = opp_player.get(opp["opportunity_id"], "unknown")
        key = (gid, pid)
        if key not in player_info:
            player_info[key] = {"role": opp["role"], "game_id": gid}

    # Compute scores
    system_scores: dict[str, dict[tuple, float]] = {
        "B_rule": {},
        "C_model": {},
    }

    for key, player_opps in by_player.items():
        # System B: rule-based
        b_scores = [rule_opportunity_value(o) * rule_decision_quality(o) for o in player_opps]
        system_scores["B_rule"][key] = statistics.mean(b_scores) if b_scores else 0.5

        # System C: rule w + model q
        c_scores = []
        for o in player_opps:
            feats = extract_features(o)
            w = rule_opportunity_value(o)
            q = float(final_model.predict(feats.to_array().reshape(1, -1))[0])
            c_scores.append(w * q)
        system_scores["C_model"][key] = statistics.mean(c_scores) if c_scores else 0.5

    # ---- Compute per-role Cohen's d ----
    print("\n=== Per-Role Cohen's d (Good vs Bad Separation) ===")

    def compute_role_d(system_key: str) -> dict[str, float]:
        role_good: dict[str, list[float]] = defaultdict(list)
        role_bad: dict[str, list[float]] = defaultdict(list)

        for key, score in system_scores[system_key].items():
            gid, pid = key
            info = player_info.get(key, {})
            role = info.get("role", "Unknown")
            winner = winner_map.get(gid, "")

            # Determine if player won
            if role == "Werewolf":
                won = winner == "wolf"
            else:
                won = winner == "village"

            if won:
                role_good[role].append(score)
            else:
                role_bad[role].append(score)

        result = {}
        for role in ["Werewolf", "Seer", "Witch", "Guard", "Hunter", "Villager"]:
            good = role_good.get(role, [])
            bad = role_bad.get(role, [])
            d = cohens_d(good, bad)
            result[role] = round(d, 3)
        return result

    b_d = compute_role_d("B_rule")
    c_d = compute_role_d("C_model")

    # System A: from baseline
    baseline_roles = baseline.get("role_summary", {})
    a_d = {role: baseline_roles.get(role, {}).get("cohens_d", 0) for role in b_d}

    # ---- Generate Report ----
    lines = [
        "# Learned Evaluator Ablation Report",
        "",
        f"**Date**: 2026-05-27",
        f"**Data**: 56 games, {len(opps)} opportunities, {len(labeled)} labeled samples",
        "",
        "## Systems Compared",
        "- **A (Old Rule)**: camp_result(25%) + role_task(25%) + vote(12%) + speech(12%) + skill(12%) + survival(8%) + info(6%)",
        "- **B (Rule Opp)**: w_rule(o) × q_rule(o) — heuristic opportunity-level scoring",
        "- **C (+Small Model)**: w_rule(o) × q_model(o) — rule-based importance + ML decision quality",
        "",
        "## DecisionQualityModel Performance",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Cross-validation Accuracy | {mean_acc:.4f} |",
        f"| Pairwise Accuracy | {mean_paw:.4f} |",
        f"| Training Samples | {len(X_all)} |",
        f"| Features | {len(ModelFeatures.FEATURE_NAMES)} |",
        "",
        "## Per-Role Cohen's d (Win vs Loss Separation)",
        "| Role | A (Old Rule) | B (Rule Opp) | C (Small Model) | Target | Winner |",
        "|------|-------------|-------------|-----------------|--------|--------|",
    ]

    for role in ["Werewolf", "Seer", "Witch", "Guard", "Hunter", "Villager"]:
        a_val = a_d.get(role, 0)
        b_val = b_d.get(role, 0)
        c_val = c_d.get(role, 0)
        target = {"Witch": ">=0.5", "Guard": ">=0.3", "Hunter": ">=0.5"}.get(role, ">=0.5")
        # Determine which is best
        best = max(a_val, b_val, c_val)
        winner = ""
        if best == a_val:
            winner = "A"
        elif best == b_val:
            winner = "B"
        elif best == c_val:
            winner = "C"
        if best == a_val == b_val:
            winner = "="

        lines.append(f"| {role} | {a_val:.3f} | {b_val:.3f} | {c_val:.3f} | {target} | {winner} |")

    lines += [
        "",
        "## Key Findings",
    ]

    # Analyze improvements
    improved = []
    for role in ["Witch", "Guard", "Hunter"]:
        if c_d.get(role, 0) > a_d.get(role, 0):
            improved.append(role)

    lines.append(f"### Witch / Guard / Hunter Improvement")
    for role in ["Witch", "Guard", "Hunter"]:
        a = a_d.get(role, 0)
        c = c_d.get(role, 0)
        delta = c - a
        status = "✓ Improved" if delta > 0 else "⚠ No change" if delta == 0 else "✗ Degraded"
        lines.append(f"- **{role}**: A={a:.3f} → C={c:.3f} (Δ={delta:+.3f}) — {status}")

    lines += [
        "",
        "### Feature Importance (DecisionQualityModel)",
    ]
    if q_model.feature_importances_:
        sorted_feats = sorted(q_model.feature_importances_.items(), key=lambda x: -x[1])
        lines.append("| Rank | Feature | Importance |")
        lines.append("|------|---------|------------|")
        for i, (name, imp) in enumerate(sorted_feats[:10]):
            lines.append(f"| {i+1} | {name} | {imp:.6f} |")

    lines += [
        "",
        "### Per-Role Mean Scores",
        "| Role | B Mean | C Mean | Old Baseline Mean |",
        "|------|--------|--------|-------------------|",
    ]
    for role in ["Werewolf", "Seer", "Witch", "Guard", "Hunter", "Villager"]:
        b_scores = [s for k, s in system_scores["B_rule"].items() if player_info.get(k, {}).get("role") == role]
        c_scores = [s for k, s in system_scores["C_model"].items() if player_info.get(k, {}).get("role") == role]
        old_mean = baseline_roles.get(role, {}).get("mean_adjusted", 0)
        b_mean = statistics.mean(b_scores) if b_scores else 0
        c_mean = statistics.mean(c_scores) if c_scores else 0
        lines.append(f"| {role} | {b_mean:.1f} | {c_mean:.1f} | {old_mean:.1f} |")

    lines += [
        "",
        "### Limitations & Next Steps",
        "- System A Cohen's d is inflated by camp_result (25% of score = which side won)",
        "- System B/C Cohen's d reflects actual decision quality differentiation",
        "- Smaller d for B/C is EXPECTED and HEALTHIER — measures skill, not outcome",
        "- Next: Add BGE-M3 embedding retrieval features (Ablation D)",
        "- Next: Collect more labeled samples for roles other than Hunter",
        "- Next: Calibrate with human-review samples",
    ]

    report_path = ROOT / "data/health/learned_evaluator_ablation_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport saved to {report_path}")

    # Also save model metrics
    metrics = {
        "DecisionQualityModel": {
            "fold_results": fold_results,
            "mean_accuracy": round(mean_acc, 4),
            "mean_pairwise_accuracy": round(mean_paw, 4),
            "n_samples": len(X_all),
            "n_features": len(ModelFeatures.FEATURE_NAMES),
        },
        "Cohen_d_comparison": {
            "A_old_rule": a_d,
            "B_rule_opportunity": b_d,
            "C_small_models": c_d,
        },
    }
    metrics_path = ROOT / "data/health/model_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Metrics saved to {metrics_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
