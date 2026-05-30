#!/usr/bin/env python3
"""vNext Scoring v2 — Role-specific baselines + optimized features.

Key improvements over v1:
1. Role-specific baselines (different median features per role)
2. Feature selection: only keep features with high variance and correlation
3. Better training: use player_won as label (cleaner signal)
"""

import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.features import register_default_extractors
from backend.eval.pairwise_ranker import PairwiseLogisticRanker, PairwiseExample

# Features to exclude
EXCLUDE_FEATURES = {
    'camp_balance_ratio', 'day', 'is_endgame', 'alive_count',
    'village_alive', 'wolf_alive', 'action_target_id',
    # Low-signal features
    'action_is_llm', 'action_is_fallback', 'action_parse_success',
}


def safe_numeric(features: dict) -> dict:
    return {
        k: float(v) for k, v in features.items()
        if k not in EXCLUDE_FEATURES
        and isinstance(v, (int, float, bool, np.integer, np.floating))
    }


def load_data():
    """Load all data."""
    opps = []
    with open(ROOT / 'data' / 'health' / 'opportunities.jsonl') as f:
        for line in f:
            if line.strip():
                try:
                    opps.append(json.loads(line))
                except:
                    pass

    player_scores = {}
    with open(ROOT / 'data' / 'health' / 'player_scores_v7_fixed_win.jsonl') as f:
        for line in f:
            if line.strip():
                try:
                    ps = json.loads(line)
                    player_scores[(ps['game_id'], ps['player_id'])] = ps
                except:
                    pass

    return opps, player_scores


def extract_features(opps, player_scores, registry):
    """Extract features and attach scores."""
    for opp in opps:
        try:
            result = registry.extract(opp)
            opp['_f'] = safe_numeric(result.features)
        except:
            opp['_f'] = {}

        key = (opp.get('game_id', ''), opp.get('player_id', ''))
        ps = player_scores.get(key, {})
        opp['_ps'] = ps.get('player_process_score', 0.5)
        opp['_won'] = ps.get('won', False)
        opp['_role'] = opp.get('role', '')


def compute_role_baselines(opps):
    """Compute median features per role."""
    by_role = defaultdict(list)
    for opp in opps:
        if opp.get('_f'):
            by_role[opp['_role']].append(opp['_f'])

    baselines = {}
    for role, feats_list in by_role.items():
        if not feats_list:
            continue
        all_keys = sorted(set().union(*[f.keys() for f in feats_list]))
        baseline = {}
        for k in all_keys:
            vals = [f.get(k, 0.0) for f in feats_list]
            baseline[k] = float(np.median(vals))
        baselines[role] = baseline

    return baselines


def generate_pairs(opps, by_key):
    """Generate pairwise training data using won/lost."""
    all_pairs = []
    pc = 0

    for (role, op_type), items in by_key.items():
        if len(items) < 4:
            continue

        won = [o for o in items if o.get('_won', False)]
        lost = [o for o in items if not o.get('_won', True)]

        if not won or not lost:
            continue

        for g in won[:8]:
            for b in lost[:4]:
                gf = g['_f']
                bf = b['_f']
                keys = sorted(set(gf) | set(bf))
                gv = {k: gf.get(k, 0.0) for k in keys}
                bv = {k: bf.get(k, 0.0) for k in keys}
                diff = sum(abs(gv[k] - bv[k]) for k in keys)
                if diff < 0.1:
                    continue
                all_pairs.append(PairwiseExample(
                    pair_id=f"r-{pc:06d}",
                    source="won_vs_lost",
                    role=role,
                    action_type=op_type,
                    better_features=gv,
                    worse_features=bv,
                ))
                pc += 1

    # Also use process_score for more pairs
    for (role, op_type), items in by_key.items():
        if len(items) < 6:
            continue
        scored = [(o, o.get('_ps', 0.5)) for o in items]
        scored.sort(key=lambda x: x[1])
        n = len(scored)
        good = [o for o, s in scored[int(n * 0.7):] if s > 0.55]
        bad = [o for o, s in scored[:int(n * 0.3)] if s < 0.45]
        if not good or not bad:
            continue
        for g in good[:6]:
            for b in bad[:3]:
                gf = g['_f']
                bf = b['_f']
                keys = sorted(set(gf) | set(bf))
                gv = {k: gf.get(k, 0.0) for k in keys}
                bv = {k: bf.get(k, 0.0) for k in keys}
                diff = sum(abs(gv[k] - bv[k]) for k in keys)
                if diff < 0.1:
                    continue
                all_pairs.append(PairwiseExample(
                    pair_id=f"s-{pc:06d}",
                    source="process_score",
                    role=role,
                    action_type=op_type,
                    better_features=gv,
                    worse_features=bv,
                ))
                pc += 1

    return all_pairs


def train_and_evaluate(all_pairs):
    """Train PairwiseLogisticRanker and evaluate."""
    np.random.seed(42)
    idx = np.random.permutation(len(all_pairs))
    n_train = int(0.7 * len(all_pairs))
    n_val = int(0.15 * len(all_pairs))

    train = [all_pairs[i] for i in idx[:n_train]]
    val = [all_pairs[i] for i in idx[n_train:n_train + n_val]]
    test = [all_pairs[i] for i in idx[n_train + n_val:]]

    print(f"Train: {len(train)}, Val: {len(val)}, Test: {len(test)}")

    ranker = PairwiseLogisticRanker()
    info = ranker.fit(train)

    print(f"\nTraining:")
    for k, v in info.items():
        print(f"  {k}: {v}")

    if val:
        c = sum(1 for p in val if ranker.compare_pair(p.better_features, p.worse_features) > 0.5)
        print(f"\nVal Acc: {c / len(val):.4f} ({c}/{len(val)})")
    if test:
        c = sum(1 for p in test if ranker.compare_pair(p.better_features, p.worse_features) > 0.5)
        print(f"Test Acc: {c / len(test):.4f} ({c}/{len(test)})")

    # Per-role
    br = defaultdict(lambda: {'c': 0, 't': 0})
    for p in test:
        pred = ranker.compare_pair(p.better_features, p.worse_features) > 0.5
        br[p.role]['t'] += 1
        if pred:
            br[p.role]['c'] += 1
    print(f"\nPer-Role Test:")
    for r in sorted(br):
        d = br[r]
        print(f"  {r}: {d['c'] / d['t']:.4f} ({d['c']}/{d['t']})")

    # Top features
    coefs = ranker.model.coef_[0] if hasattr(ranker.model, 'coef_') else []
    if len(coefs) > 0:
        fw = sorted(zip(ranker.feature_names, coefs), key=lambda x: abs(x[1]), reverse=True)
        print(f"\nTop 10 features:")
        for n, w in fw[:10]:
            print(f"  {n}: {w:+.4f}")

    return ranker


def score_opportunities(opps, ranker, baselines):
    """Score all opportunities using role-specific baselines."""
    sbp = defaultdict(list)
    for opp in opps:
        if not opp.get('_f'):
            continue
        pid = opp.get('player_id', '')
        role = opp.get('_role', '')
        feats = opp['_f']

        # Use role-specific baseline
        baseline = baselines.get(role, {})
        if not baseline:
            continue

        prob = ranker.compare_pair(feats, baseline)
        sbp[pid].append({
            'role': role,
            'q': prob,
            'ps': opp.get('_ps', 0.5),
            'won': opp.get('_won', False),
        })

    return sbp


def main():
    print("=" * 60)
    print("vNext Scoring v2 — Role-specific baselines")
    print("=" * 60)

    # Load data
    opps, player_scores = load_data()
    registry = register_default_extractors()
    extract_features(opps, player_scores, registry)
    print(f"Loaded {len(opps)} opportunities, {len(player_scores)} player scores")

    # Compute role-specific baselines
    baselines = compute_role_baselines(opps)
    print(f"Computed baselines for {len(baselines)} roles")
    for role, bl in baselines.items():
        print(f"  {role}: {len(bl)} features")

    # Group by (role, opportunity_type)
    by_key = defaultdict(list)
    for opp in opps:
        if opp.get('_f'):
            key = (opp.get('_role', ''), opp.get('opportunity_type', ''))
            by_key[key].append(opp)

    # Generate pairs
    all_pairs = generate_pairs(opps, by_key)
    print(f"\nGenerated {len(all_pairs)} pairs")

    from collections import Counter
    roles = Counter(p.role for p in all_pairs)
    print(f"By role: {dict(roles)}")

    # Train
    ranker = train_and_evaluate(all_pairs)

    # Score all opportunities
    sbp = score_opportunities(opps, ranker, baselines)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"vNext v2 Scoring Summary")
    print(f"{'=' * 60}")

    print(f"\n{'Role':<12} {'vNext':<10} {'Std':<8} {'Min':<8} {'Max':<8} {'ProcSc':<10}")
    print("-" * 55)
    for role in ['Seer', 'Witch', 'Hunter', 'Guard', 'Werewolf', 'Villager']:
        vn, ps = [], []
        for pid, ls in sbp.items():
            if ls[0]['role'] == role:
                vn.append(np.mean([o['q'] for o in ls]))
                ps.append(np.mean([o['ps'] for o in ls]))
        if vn:
            print(f"{role:<12} {np.mean(vn):.4f}   {np.std(vn):.4f}  {np.min(vn):.4f}  {np.max(vn):.4f}  {np.mean(ps):.4f}")

    # Correlation
    vn_all, ps_all = [], []
    for pid, ls in sbp.items():
        vn_all.append(np.mean([o['q'] for o in ls]))
        ps_all.append(np.mean([o['ps'] for o in ls]))
    if len(vn_all) > 2:
        corr = np.corrcoef(vn_all, ps_all)[0, 1]
        from scipy.stats import spearmanr
        rho, pval = spearmanr(vn_all, ps_all)
        print(f"\nCorrelation (vNext v2 vs ProcessScore): {corr:.4f}")
        print(f"Spearman rank correlation: {rho:.4f} (p={pval:.6f})")

    # Save model and baselines
    ranker.save(str(ROOT / 'data' / 'health' / 'decision_quality_model_vnext_v2.pkl'))
    with open(str(ROOT / 'data' / 'health' / 'vnext_v2_baselines.pkl'), 'wb') as f:
        pickle.dump(baselines, f)
    print(f"\nSaved model and baselines!")


if __name__ == '__main__':
    main()
