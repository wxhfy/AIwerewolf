#!/usr/bin/env python3
"""vNext Scoring Integration

Integrates PairwiseLogisticRanker with the existing review.py scoring system.
Uses baseline comparison to produce meaningful rank scores.

Usage:
  python3 scripts/vnext_scoring.py [--player-scores FILE] [--opps FILE] [--output FILE]
"""

import argparse
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.features import register_default_extractors
from backend.eval.pairwise_ranker import PairwiseLogisticRanker

# Features to exclude (game-state, not decision-specific)
EXCLUDE_FEATURES = {
    'camp_balance_ratio', 'day', 'is_endgame', 'alive_count',
    'village_alive', 'wolf_alive', 'action_target_id',
}


def safe_numeric(features: dict) -> dict:
    """Keep only numeric features, skip strings and excluded features."""
    return {
        k: float(v) for k, v in features.items()
        if k not in EXCLUDE_FEATURES
        and isinstance(v, (int, float, bool, np.integer, np.floating))
    }


class VNextScorer:
    """vNext scoring engine using PairwiseLogisticRanker + baseline comparison."""

    def __init__(self, model_path: str = None, baseline_path: str = None):
        self.ranker = PairwiseLogisticRanker()
        self.baseline = None
        self.registry = register_default_extractors()

        model_path = model_path or str(ROOT / 'data' / 'health' / 'decision_quality_model_vnext_real.pkl')
        baseline_path = baseline_path or str(ROOT / 'data' / 'health' / 'vnext_baseline_features.pkl')

        self.ranker.load(model_path)
        with open(baseline_path, 'rb') as f:
            self.baseline = pickle.load(f)

    def score_opportunity(self, opp: dict) -> dict:
        """Score a single opportunity against baseline.

        Returns:
            {
                'vnext_score': float,  # 0-1, probability of being better than baseline
                'feature_count': int,
                'features_used': int,
            }
        """
        try:
            result = self.registry.extract(opp)
            features = safe_numeric(result.features)
        except Exception:
            return {'vnext_score': 0.5, 'feature_count': 0, 'features_used': 0}

        if not features:
            return {'vnext_score': 0.5, 'feature_count': 0, 'features_used': 0}

        # Compare against baseline
        prob = self.ranker.compare_pair(features, self.baseline)

        return {
            'vnext_score': round(prob, 4),
            'feature_count': len(features),
            'features_used': len(self.ranker.feature_names),
        }

    def score_game(self, opportunities: list) -> dict:
        """Score all opportunities in a game.

        Returns per-player aggregated scores.
        """
        by_player = defaultdict(list)
        for opp in opportunities:
            pid = opp.get('player_id', '')
            score_info = self.score_opportunity(opp)
            by_player[pid].append(score_info)

        results = {}
        for pid, scores in by_player.items():
            vnext_scores = [s['vnext_score'] for s in scores]
            results[pid] = {
                'vnext_score': round(float(np.mean(vnext_scores)), 4),
                'vnext_std': round(float(np.std(vnext_scores)), 4),
                'n_opportunities': len(scores),
            }

        return results


def main():
    parser = argparse.ArgumentParser(description='vNext Scoring')
    parser.add_argument('--player-scores', default=str(ROOT / 'data' / 'health' / 'player_scores_v7_fixed_win.jsonl'))
    parser.add_argument('--opps', default=str(ROOT / 'data' / 'health' / 'opportunities.jsonl'))
    parser.add_argument('--output', default=str(ROOT / 'data' / 'health' / 'vnext_scores.jsonl'))
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()

    scorer = VNextScorer()

    # Load opportunities
    opps = []
    with open(args.opps) as f:
        for line in f:
            if line.strip():
                try:
                    opps.append(json.loads(line))
                except:
                    pass

    # Load player scores for process_score comparison
    player_scores = {}
    with open(args.player_scores) as f:
        for line in f:
            if line.strip():
                try:
                    ps = json.loads(line)
                    player_scores[(ps['game_id'], ps['player_id'])] = ps
                except:
                    pass

    print(f"Loaded {len(opps)} opportunities, {len(player_scores)} player scores")

    # Score all opportunities
    results_by_player = defaultdict(list)
    for opp in opps:
        pid = opp.get('player_id', '')
        gid = opp.get('game_id', '')
        role = opp.get('role', '')
        score_info = scorer.score_opportunity(opp)

        results_by_player[pid].append({
            'game_id': gid,
            'role': role,
            'opportunity_type': opp.get('opportunity_type', ''),
            **score_info,
        })

    # Aggregate per player
    output = []
    for pid, scores in sorted(results_by_player.items()):
        vnext_scores = [s['vnext_score'] for s in scores]
        role = scores[0]['role']

        # Get process score for comparison
        gid = scores[0]['game_id']
        ps_data = player_scores.get((gid, pid), {})
        process_score = ps_data.get('player_process_score', None)

        record = {
            'player_id': pid,
            'game_id': gid,
            'role': role,
            'vnext_score': round(float(np.mean(vnext_scores)), 4),
            'vnext_std': round(float(np.std(vnext_scores)), 4),
            'vnext_min': round(float(np.min(vnext_scores)), 4),
            'vnext_max': round(float(np.max(vnext_scores)), 4),
            'n_opportunities': len(scores),
            'process_score': process_score,
        }
        output.append(record)

    # Save
    with open(args.output, 'w') as f:
        for rec in output:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f"\nSaved {len(output)} player scores to {args.output}")

    # Print summary
    if args.summary or True:  # Always print summary
        print(f"\n{'='*70}")
        print(f"vNext Scoring Summary")
        print(f"{'='*70}")

        # Per role
        by_role = defaultdict(list)
        for rec in output:
            by_role[rec['role']].append(rec)

        print(f"\n{'Role':<12} {'vNext':<10} {'Std':<8} {'Min':<8} {'Max':<8} {'ProcSc':<10} {'N':<5}")
        print("-" * 65)
        for role in ['Seer', 'Witch', 'Hunter', 'Guard', 'Werewolf', 'Villager']:
            recs = by_role.get(role, [])
            if not recs:
                continue
            vn = [r['vnext_score'] for r in recs]
            ps = [r['process_score'] for r in recs if r['process_score'] is not None]
            print(f"{role:<12} {np.mean(vn):.4f}   {np.std(vn):.4f}  {np.min(vn):.4f}  {np.max(vn):.4f}  {np.mean(ps) if ps else 0:.4f}   {len(recs)}")

        # Correlation
        vn_all = [r['vnext_score'] for r in output]
        ps_all = [r['process_score'] for r in output if r['process_score'] is not None]
        if len(ps_all) > 2:
            vn_filtered = [r['vnext_score'] for r in output if r['process_score'] is not None]
            corr = np.corrcoef(vn_filtered, ps_all)[0, 1]
            print(f"\nCorrelation (vNext vs ProcessScore): {corr:.4f}")

        # Top/Bottom players
        print(f"\nTop 10 Players by vNext:")
        for rec in sorted(output, key=lambda x: x['vnext_score'], reverse=True)[:10]:
            ps = rec['process_score'] or 0
            print(f"  {rec['player_id']:<15} {rec['role']:<10} vNext={rec['vnext_score']:.4f}  Process={ps:.4f}")

        print(f"\nBottom 10 Players by vNext:")
        for rec in sorted(output, key=lambda x: x['vnext_score'])[:10]:
            ps = rec['process_score'] or 0
            print(f"  {rec['player_id']:<15} {rec['role']:<10} vNext={rec['vnext_score']:.4f}  Process={ps:.4f}")


if __name__ == '__main__':
    main()
