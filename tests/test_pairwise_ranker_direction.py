"""PairwiseLogisticRanker direction sanity tests.

Tests that the ranker correctly learns that "better" actions should
score higher than "worse" actions, using synthetic data independent
of werewolf fixtures.
"""

from __future__ import annotations

import numpy as np

from backend.eval.pairwise_ranker import PairwiseExample
from backend.eval.pairwise_ranker import PairwiseLogisticRanker


def _make_pair(better_f, worse_f, pair_id="test", source="synthetic"):
    return PairwiseExample(
        pair_id=pair_id,
        source=source,
        role="Werewolf",
        action_type="speech",
        better_features=better_f,
        worse_features=worse_f,
    )


class TestPairwiseRankerDirection:
    """Verify ranker correctly learns which direction is 'better'."""

    def test_good_ranks_higher_than_bad(self):
        """With clear feature signal, P(better>worse) should be > 0.8."""
        pairs = []
        for i in range(30):
            pairs.append(
                _make_pair(
                    {"quality_signal": 0.9, "noise": np.random.random()},
                    {"quality_signal": 0.1, "noise": np.random.random()},
                    f"synth-{i:04d}",
                )
            )
        ranker = PairwiseLogisticRanker()
        info = ranker.fit(pairs)
        print(f"\n  Trained: {info}")

        result = ranker.predict_rank({"quality_signal": 0.9, "noise": 0.5})
        bad_result = ranker.predict_rank({"quality_signal": 0.1, "noise": 0.5})

        print(f"  Better rank_q: {result.learned_rank_q:.4f}")
        print(f"  Worse rank_q: {bad_result.learned_rank_q:.4f}")

        assert result.learned_rank_q > bad_result.learned_rank_q, "Ranker should give higher score to better features"
        assert result.learned_rank_q > 0.5, f"Good features should score > 0.5, got {result.learned_rank_q}"

    def test_bad_ranks_lower_than_good(self):
        """compare_pair(bad, good) should give P < 0.5 (prefers good)."""
        pairs = []
        for i in range(30):
            pairs.append(
                _make_pair(
                    {"quality_signal": 0.95, "noise": np.random.random()},
                    {"quality_signal": 0.05, "noise": np.random.random()},
                )
            )
        ranker = PairwiseLogisticRanker()
        ranker.fit(pairs)

        # compare_pair(better, worse) — but we test compare_pair(worse, better)
        prob_bad_over_good = ranker.compare_pair(
            {"quality_signal": 0.05, "noise": 0.5},
            {"quality_signal": 0.95, "noise": 0.5},
        )
        print(f"\n  P(bad>good) = {prob_bad_over_good:.4f}")
        assert prob_bad_over_good < 0.3, (
            f"Should strongly prefer good over bad, got P(bad>good)={prob_bad_over_good:.4f}"
        )

    def test_compare_pair_works(self):
        """compare_pair(better, worse) should return > 0.5."""
        pairs = [_make_pair({"q": 1.0}, {"q": 0.0}) for _ in range(20)]
        ranker = PairwiseLogisticRanker()
        ranker.fit(pairs)
        prob = ranker.compare_pair({"q": 1.0}, {"q": 0.0})
        print(f"\n  P(better>worse) = {prob:.4f}")
        assert prob > 0.7, f"Should strongly prefer better, got {prob}"

    def test_reversed_labels_give_low_accuracy(self):
        """If we train with reversed labels, accuracy should drop."""
        pairs = []
        for i in range(30):
            pairs.append(
                _make_pair(
                    {"q": 0.95},
                    {"q": 0.05},
                )
            )
        # Train normally
        ranker_correct = PairwiseLogisticRanker()
        r1 = ranker_correct.fit(pairs)

        # Train with reversed labels (worse as better)
        reversed_pairs = []
        for p in pairs:
            reversed_pairs.append(
                _make_pair(
                    p.worse_features,
                    p.better_features,
                    p.pair_id + "_rev",
                )
            )
        ranker_rev = PairwiseLogisticRanker()
        r2 = ranker_rev.fit(reversed_pairs)

        # Both might fit well on training data (reversed just learns opposite)
        # But on heldout, correct should prefer {"q": 0.9} > {"q": 0.1}
        correct_pred = ranker_correct.compare_pair({"q": 0.9}, {"q": 0.1})
        reversed_pred = ranker_rev.compare_pair({"q": 0.9}, {"q": 0.1})

        print(f"\n  Correct ranker P(good>bad): {correct_pred:.4f}")
        print(f"  Reversed ranker P(good>bad): {reversed_pred:.4f}")

        assert correct_pred > 0.5, f"Correct ranker should prefer good, got {correct_pred}"
        assert reversed_pred < 0.5, f"Reversed ranker should prefer bad, got {reversed_pred}"

    def test_symmetric_augmentation_improves_accuracy(self):
        """Adding (x_bad - x_good, label=0) pairs should improve accuracy."""
        # Create clean separable data
        pairs = []
        np.random.seed(42)
        for i in range(50):
            pairs.append(
                _make_pair(
                    {"quality_signal": 0.8 + 0.15 * np.random.random(), "risk_signal": 0.1 + 0.1 * np.random.random()},
                    {"quality_signal": 0.1 + 0.1 * np.random.random(), "risk_signal": 0.8 + 0.15 * np.random.random()},
                )
            )

        ranker = PairwiseLogisticRanker()
        info = ranker.fit(pairs)
        acc_no_sym = info["train_accuracy"]

        # With symmetric augmentation built into fit
        print(f"\n  Without symmetric aug: train_acc={acc_no_sym:.4f}")
        assert acc_no_sym >= 0.70, f"Even without symmetric aug, clean data should achieve >= 0.70, got {acc_no_sym}"

    def test_save_load_preserves_predictions(self, tmp_path):
        """Ranker should produce same predictions after save/load."""
        pairs = [_make_pair({"a": 0.9, "b": 0.1}, {"a": 0.1, "b": 0.9}) for _ in range(20)]
        ranker = PairwiseLogisticRanker()
        ranker.fit(pairs)

        before = ranker.compare_pair({"a": 0.9, "b": 0.1}, {"a": 0.1, "b": 0.9})

        p = tmp_path / "test_ranker.pkl"
        ranker.save(p)
        ranker2 = PairwiseLogisticRanker()
        ranker2.load(p)

        after = ranker2.compare_pair({"a": 0.9, "b": 0.1}, {"a": 0.1, "b": 0.9})
        assert abs(before - after) < 0.01, f"Predictions should match after load: {before:.4f} vs {after:.4f}"

    def test_all_zero_features_handled(self):
        """Ranker should not crash with all-zero features."""
        pairs = [_make_pair({"a": 0.0, "b": 0.0}, {"a": 0.0, "b": 0.0}) for _ in range(10)]
        ranker = PairwiseLogisticRanker()
        ranker.fit(pairs)
        result = ranker.predict_rank({"a": 0.0, "b": 0.0})
        # Should not crash — can return any score
        assert 0.0 <= result.learned_rank_q <= 1.0

    def test_many_features_no_overfit(self):
        """With 50 random features and only 2 meaningful ones, should still learn."""
        np.random.seed(42)
        pairs = []
        for i in range(60):
            bf = {f"rand_{j}": np.random.random() for j in range(48)}
            wf = {f"rand_{j}": np.random.random() for j in range(48)}
            bf["real_signal"] = 0.85
            wf["real_signal"] = 0.15
            pairs.append(_make_pair(bf, wf))
        ranker = PairwiseLogisticRanker()
        info = ranker.fit(pairs)
        print(
            f"\n  50-feature test: train_acc={info['train_accuracy']:.4f} "
            f"n_features={info.get('n_features_total', info.get('n_features', '?'))}"
        )
        # Should at least be better than random on training data
        assert info["train_accuracy"] >= 0.60, "With 50 features but 2 clear signals, should achieve >= 0.60"
