#!/usr/bin/env python3
"""vNext Scoring v3 — LLM-only + cross-validation + feature optimization.

Key improvements:
1. Filter for LLM-only opportunities (source='llm')
2. Cross-validation for robust evaluation
3. Feature importance analysis and selection
4. Better training data balance
"""

import json
import pickle
import sys
from collections import Counter
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.features import register_default_extractors
from backend.eval.pairwise_ranker import PairwiseExample
from backend.eval.pairwise_ranker import PairwiseLogisticRanker

# Features to exclude
EXCLUDE_FEATURES = {
    "camp_balance_ratio",
    "day",
    "is_endgame",
    "alive_count",
    "village_alive",
    "wolf_alive",
    "action_target_id",
    "action_is_llm",
    "action_is_fallback",
    "action_parse_success",
}


def safe_numeric(features: dict) -> dict:
    return {
        k: float(v)
        for k, v in features.items()
        if k not in EXCLUDE_FEATURES and isinstance(v, (int, float, bool, np.integer, np.floating))
    }


def load_llm_data():
    """Load only LLM-run opportunities."""
    opps = []
    with open(ROOT / "data" / "health" / "opportunities.jsonl") as f:
        for line in f:
            if line.strip():
                try:
                    o = json.loads(line)
                    # Filter: only LLM actions
                    action = o.get("chosen_action", {}) or {}
                    meta = action.get("metadata", {}) or {}
                    if meta.get("source") == "llm":
                        opps.append(o)
                except:
                    pass

    player_scores = {}
    with open(ROOT / "data" / "health" / "player_scores_v7_fixed_win.jsonl") as f:
        for line in f:
            if line.strip():
                try:
                    ps = json.loads(line)
                    player_scores[(ps["game_id"], ps["player_id"])] = ps
                except:
                    pass

    return opps, player_scores


def extract_features(opps, player_scores, registry):
    """Extract features and attach scores."""
    for opp in opps:
        try:
            result = registry.extract(opp)
            opp["_f"] = safe_numeric(result.features)
        except:
            opp["_f"] = {}

        key = (opp.get("game_id", ""), opp.get("player_id", ""))
        ps = player_scores.get(key, {})
        opp["_ps"] = ps.get("player_process_score", 0.5)
        opp["_won"] = ps.get("won", False)
        opp["_role"] = opp.get("role", "")


def generate_balanced_pairs(opps, by_key):
    """Generate balanced pairwise training data."""
    all_pairs = []
    pc = 0

    # Won vs Lost pairs
    for (role, op_type), items in by_key.items():
        if len(items) < 4:
            continue

        won = [o for o in items if o.get("_won", False)]
        lost = [o for o in items if not o.get("_won", True)]

        if not won or not lost:
            continue

        # Balance: equal number of won and lost
        min_count = min(len(won), len(lost))
        won_sample = won[: min(min_count, 10)]
        lost_sample = lost[: min(min_count, 10)]

        for g in won_sample:
            for b in lost_sample:
                gf = g["_f"]
                bf = b["_f"]
                keys = sorted(set(gf) | set(bf))
                gv = {k: gf.get(k, 0.0) for k in keys}
                bv = {k: bf.get(k, 0.0) for k in keys}
                diff = sum(abs(gv[k] - bv[k]) for k in keys)
                if diff < 0.1:
                    continue
                all_pairs.append(
                    PairwiseExample(
                        pair_id=f"w-{pc:06d}",
                        source="won_vs_lost",
                        role=role,
                        action_type=op_type,
                        better_features=gv,
                        worse_features=bv,
                    )
                )
                pc += 1

    # Process score pairs (for additional signal)
    for (role, op_type), items in by_key.items():
        if len(items) < 6:
            continue
        scored = [(o, o.get("_ps", 0.5)) for o in items]
        scored.sort(key=lambda x: x[1])
        n = len(scored)
        good = [o for o, s in scored[int(n * 0.7) :] if s > 0.55]
        bad = [o for o, s in scored[: int(n * 0.3)] if s < 0.45]
        if not good or not bad:
            continue
        for g in good[:6]:
            for b in bad[:3]:
                gf = g["_f"]
                bf = b["_f"]
                keys = sorted(set(gf) | set(bf))
                gv = {k: gf.get(k, 0.0) for k in keys}
                bv = {k: bf.get(k, 0.0) for k in keys}
                diff = sum(abs(gv[k] - bv[k]) for k in keys)
                if diff < 0.1:
                    continue
                all_pairs.append(
                    PairwiseExample(
                        pair_id=f"s-{pc:06d}",
                        source="process_score",
                        role=role,
                        action_type=op_type,
                        better_features=gv,
                        worse_features=bv,
                    )
                )
                pc += 1

    return all_pairs


def cross_validate(all_pairs, n_folds=5):
    """Cross-validation for robust evaluation."""
    np.random.seed(42)
    indices = np.random.permutation(len(all_pairs))
    fold_size = len(all_pairs) // n_folds

    results = []
    for fold in range(n_folds):
        start = fold * fold_size
        end = start + fold_size if fold < n_folds - 1 else len(all_pairs)

        test_idx = indices[start:end]
        train_idx = np.concatenate([indices[:start], indices[end:]])

        train = [all_pairs[i] for i in train_idx]
        test = [all_pairs[i] for i in test_idx]

        ranker = PairwiseLogisticRanker()
        info = ranker.fit(train)

        # Evaluate
        correct = sum(1 for p in test if ranker.compare_pair(p.better_features, p.worse_features) > 0.5)
        acc = correct / len(test) if test else 0

        results.append(
            {
                "fold": fold,
                "train_size": len(train),
                "test_size": len(test),
                "train_acc": info.get("train_accuracy", 0),
                "test_acc": acc,
                "features_used": info.get("n_features_used", 0),
            }
        )

    return results


def train_final(all_pairs):
    """Train final model on all data."""
    ranker = PairwiseLogisticRanker()
    info = ranker.fit(all_pairs)
    return ranker, info


def score_opportunities(opps, ranker, baseline):
    """Score all opportunities using global baseline."""
    sbp = defaultdict(list)
    for opp in opps:
        if not opp.get("_f"):
            continue
        pid = opp.get("player_id", "")
        role = opp.get("_role", "")
        feats = opp["_f"]

        prob = ranker.compare_pair(feats, baseline)
        sbp[pid].append(
            {
                "role": role,
                "q": prob,
                "ps": opp.get("_ps", 0.5),
            }
        )

    return sbp


def main():
    print("=" * 60)
    print("vNext Scoring v3 — LLM-only + Cross-validation")
    print("=" * 60)

    # Load LLM-only data
    opps, player_scores = load_llm_data()
    registry = register_default_extractors()
    extract_features(opps, player_scores, registry)
    print(f"LLM opportunities: {len(opps)}")
    print(f"Player scores: {len(player_scores)}")

    # Group by (role, opportunity_type)
    by_key = defaultdict(list)
    for opp in opps:
        if opp.get("_f"):
            key = (opp.get("_role", ""), opp.get("opportunity_type", ""))
            by_key[key].append(opp)

    # Generate pairs
    all_pairs = generate_balanced_pairs(opps, by_key)
    print(f"\nGenerated {len(all_pairs)} pairs")

    roles = Counter(p.role for p in all_pairs)
    print(f"By role: {dict(roles)}")

    # Cross-validation
    print(f"\n{'=' * 60}")
    print("Cross-validation (5 folds)")
    print(f"{'=' * 60}")

    cv_results = cross_validate(all_pairs, n_folds=5)
    print(f"\n{'Fold':<6} {'Train':<8} {'Test':<8} {'TrainAcc':<10} {'TestAcc':<10} {'Features':<10}")
    print("-" * 52)
    for r in cv_results:
        print(
            f"{r['fold']:<6} {r['train_size']:<8} {r['test_size']:<8} {r['train_acc']:.4f}    {r['test_acc']:.4f}    {r['features_used']}"
        )

    avg_test_acc = np.mean([r["test_acc"] for r in cv_results])
    std_test_acc = np.std([r["test_acc"] for r in cv_results])
    print(f"\nAverage test accuracy: {avg_test_acc:.4f} ± {std_test_acc:.4f}")

    # Train final model
    print(f"\n{'=' * 60}")
    print("Training final model on all data")
    print(f"{'=' * 60}")

    ranker, info = train_final(all_pairs)
    print(f"Train accuracy: {info.get('train_accuracy', '?')}")
    print(f"Features used: {info.get('n_features_used', '?')}")

    # Compute global baseline
    all_feats = [o["_f"] for o in opps if o["_f"]]
    feature_keys = sorted(set().union(*[f.keys() for f in all_feats]))
    global_baseline = {}
    for k in feature_keys:
        vals = [f.get(k, 0.0) for f in all_feats]
        global_baseline[k] = float(np.median(vals))

    # Score all opportunities
    sbp = score_opportunities(opps, ranker, global_baseline)

    # Summary
    print(f"\n{'=' * 60}")
    print("vNext v3 Scoring Summary (LLM-only)")
    print(f"{'=' * 60}")

    print(f"\n{'Role':<12} {'vNext':<10} {'Std':<8} {'Min':<8} {'Max':<8} {'ProcSc':<10}")
    print("-" * 55)
    for role in ["Seer", "Witch", "Hunter", "Guard", "Werewolf", "Villager"]:
        vn, ps = [], []
        for pid, ls in sbp.items():
            if ls[0]["role"] == role:
                vn.append(np.mean([o["q"] for o in ls]))
                ps.append(np.mean([o["ps"] for o in ls]))
        if vn:
            print(
                f"{role:<12} {np.mean(vn):.4f}   {np.std(vn):.4f}  {np.min(vn):.4f}  {np.max(vn):.4f}  {np.mean(ps):.4f}"
            )

    # Correlation
    vn_all, ps_all = [], []
    for pid, ls in sbp.items():
        vn_all.append(np.mean([o["q"] for o in ls]))
        ps_all.append(np.mean([o["ps"] for o in ls]))
    if len(vn_all) > 2:
        corr = np.corrcoef(vn_all, ps_all)[0, 1]
        from scipy.stats import spearmanr

        rho, pval = spearmanr(vn_all, ps_all)
        print(f"\nCorrelation (vNext v3 vs ProcessScore): {corr:.4f}")
        print(f"Spearman rank correlation: {rho:.4f} (p={pval:.6f})")

    # Top features
    coefs = ranker.model.coef_[0] if hasattr(ranker.model, "coef_") else []
    if len(coefs) > 0:
        fw = sorted(zip(ranker.feature_names, coefs), key=lambda x: abs(x[1]), reverse=True)
        print("\nTop 15 features:")
        for n, w in fw[:15]:
            print(f"  {n}: {w:+.4f}")

    # Save
    ranker.save(str(ROOT / "data" / "health" / "decision_quality_model_vnext_v3.pkl"))
    with open(str(ROOT / "data" / "health" / "vnext_v3_baselines.pkl"), "wb") as f:
        pickle.dump({"global": global_baseline}, f)
    print("\nSaved model and baselines!")


if __name__ == "__main__":
    main()
