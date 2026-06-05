"""Tests for pairwise vote/night-action expansion and per-action rankers."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def _count_pairs(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    pairs = []
    with open(p) as f:
        for line in f:
            if line.strip():
                try:
                    pairs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return pairs


def _pair_degenerate_rate(pairs, reg=None):
    if reg is None:
        from backend.eval.features import register_default_extractors

        reg = register_default_extractors()
    deg = 0
    for p in pairs:
        b_opp = p.get("bad", {}).get("opportunity", {})
        g_opp = p.get("good", {}).get("opportunity", {})
        if not b_opp or not g_opp:
            deg += 1
            continue
        bf = reg.extract(b_opp).features
        gf = reg.extract(g_opp).features
        all_k = set(list(bf.keys()) + list(gf.keys()))
        td = sum(
            abs(float(bf.get(k, 0)) - float(gf.get(k, 0)))
            for k in all_k
            if isinstance(bf.get(k), (int, float)) and isinstance(gf.get(k), (int, float))
        )
        if td < 1e-6:
            deg += 1
    return deg / max(len(pairs), 1)


class TestPairwiseExpansion:
    def test_vote_expansion_generates_minimum_pairs(self):
        pairs = _count_pairs("data/health/pairwise_vote_expansion_examples.jsonl")
        assert len(pairs) >= 70, f"Expected >=70 vote pairs, got {len(pairs)}"

    def test_night_action_expansion_generates_minimum_pairs(self):
        pairs = _count_pairs("data/health/pairwise_night_action_expansion_examples.jsonl")
        assert len(pairs) >= 40, f"Expected >=40 night-action pairs, got {len(pairs)}"

    def test_vote_degenerate_rate_improved(self):
        pairs = _count_pairs("data/health/pairwise_vote_expansion_examples.jsonl")
        assert len(pairs) >= 10, "Need vote pairs"
        rate = _pair_degenerate_rate(pairs)
        print(f"\n  Vote degenerate rate: {rate:.1%}")
        assert rate <= 0.35, f"Vote degenerate rate too high: {rate:.1%}"

    def test_night_action_degenerate_rate_improved(self):
        pairs = _count_pairs("data/health/pairwise_night_action_expansion_examples.jsonl")
        assert len(pairs) >= 10, "Need night-action pairs"
        rate = _pair_degenerate_rate(pairs)
        print(f"\n  Night-action degenerate rate: {rate:.1%}")
        assert rate <= 0.25, f"Night-action degenerate rate too high: {rate:.1%}"

    def test_no_player_id_shortcut_in_expansion_pairs(self):
        for path in ["pairwise_vote_expansion_examples.jsonl", "pairwise_night_action_expansion_examples.jsonl"]:
            pairs = _count_pairs(f"data/health/{path}")
            for p in pairs[:5]:
                b_opp = p.get("bad", {}).get("opportunity", {})
                for k, v in b_opp.items():
                    if isinstance(v, str) and v.startswith("P") and len(v) <= 3:
                        if k in ("player_id", "target_id", "action_target_id"):
                            continue  # OK: these are data fields
                # Check features don't have P1/P2 shortcuts
                bf = p.get("bad", {}).get("features", {})
                for fk in bf:
                    assert not fk.startswith("P1_"), f"Player-id shortcut feature: {fk}"

    def test_per_action_rankers_train_and_predict(self):
        from backend.eval.pairwise_ranker import PerActionPairwiseRankers

        # Create synthetic pairs for each action type
        np.random.seed(42)
        all_pairs = []
        for ptype, base_features, n in [
            ("speech", {"grounding": 0.8, "leak": 0.1}, 15),
            ("vote", {"coordination": 0.9, "alignment": 0.8}, 10),
            ("kill", {"target_value": 0.9, "gap": 0.05}, 8),
        ]:
            from backend.eval.pairwise_ranker import PairwiseExample

            for i in range(n):
                bf = {k: v + 0.1 * np.random.random() for k, v in base_features.items()}
                wf = {k: 0.2 + 0.1 * np.random.random() for k, v in base_features.items()}
                all_pairs.append(
                    PairwiseExample(
                        pair_id=f"{ptype}-{i:04d}",
                        source="test",
                        role="Werewolf",
                        action_type=ptype,
                        better_features=bf,
                        worse_features=wf,
                    )
                )

        par = PerActionPairwiseRankers()
        par.fit(all_pairs)
        print(f"\n  Per-action rankers: {list(par.rankers.keys())}")
        print(f"  Pair counts: {par.pair_counts}")
        assert "speech" in par.rankers, "Should have speech ranker"
        assert "vote" in par.rankers or "other" in par.rankers

    def test_effective_pair_metrics_computable(self):
        from backend.eval.pairwise_ranker import pairwise_examples_from_jsonl

        all_pairs = []
        for f in ["pairwise_vote_expansion_examples.jsonl", "pairwise_night_action_expansion_examples.jsonl"]:
            p = Path("data/health") / f
            if p.exists():
                all_pairs.extend(pairwise_examples_from_jsonl(p))

        by_type = defaultdict(list)
        for pair in all_pairs:
            by_type[pair.action_type].append(pair)

        from backend.eval.features import register_default_extractors

        register_default_extractors()

        print("\n  === Effective Pair Metrics ===")
        for ptype, ps in sorted(by_type.items()):
            deg = 0
            deltas = []
            for p in ps:
                bf, gf = p.better_features, p.worse_features
                all_k = set(list(bf.keys()) + list(gf.keys()))
                td = sum(
                    abs(float(bf.get(k, 0)) - float(gf.get(k, 0)))
                    for k in all_k
                    if isinstance(bf.get(k), (int, float)) and isinstance(gf.get(k), (int, float))
                )
                if td < 1e-6:
                    deg += 1
                deltas.append(td)
            rate = deg / max(len(ps), 1)
            med = np.median(deltas) if deltas else 0
            print(
                f"  {ptype:30s}: n={len(ps):3d} effective={len(ps) - deg} "
                f"degenerate_rate={rate:.1%} median_delta={med:.4f}"
            )

        assert len(all_pairs) >= 80, f"Expected >=80 total pairs, got {len(all_pairs)}"


def test_hard_cap_count_is_zero():
    """Verify calibration still has zero hard caps after all changes."""
    from backend.eval.opportunity import OpportunityExtractor
    from backend.eval.scoring_models import calibrate_decision_quality
    from backend.eval.scoring_models import extract_features
    from backend.eval.scoring_models import load_track_b_models
    from backend.eval.track_b import ReplayBundleBuilder
    from tests.test_track_b_badcase_wolf_regression import build_badcase_002_fixture

    state = build_badcase_002_fixture()
    bundle = ReplayBundleBuilder().build(state)
    opps = OpportunityExtractor().extract(bundle)
    _, q_model = load_track_b_models()

    hard_cap_reasons = {"witch_poisoned_good", "hunter_shot_good", "wolf_explicit_exposure_cap"}
    hc = 0
    for op in opps:
        feats = extract_features(op.to_dict())
        raw_q = float(q_model.predict(feats.to_array().reshape(1, -1))[0])
        cal = calibrate_decision_quality(op.to_dict(), raw_q)
        for r in cal.calibration_reasons:
            if r in hard_cap_reasons:
                hc += 1

    assert hc == 0, f"Hard caps found: {hc}"
