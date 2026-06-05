"""RankerConfidenceGate and ranker contribution tests."""

from __future__ import annotations


class TestRankerConfidenceGate:
    def test_high_degeneration_becomes_debug_only(self):
        from backend.eval.pairwise_ranker import compute_ranker_gate

        result = compute_ranker_gate(
            effective_pair_count=10,
            degenerate_pair_rate=0.65,
            validation_acc=0.50,
            heldout_acc=0.44,
        )
        assert not result.eligible
        assert result.confidence == "debug_only"
        assert result.weight == 0.0

    def test_low_confidence_gate_assigns_correct_weight(self):
        from backend.eval.pairwise_ranker import compute_ranker_gate

        result = compute_ranker_gate(
            effective_pair_count=20,
            degenerate_pair_rate=0.35,
            validation_acc=0.62,
            heldout_acc=0.58,
        )
        assert result.eligible
        assert result.confidence == "low"
        assert result.weight == 0.05

    def test_medium_confidence_gate_assigns_correct_weight(self):
        from backend.eval.pairwise_ranker import compute_ranker_gate

        result = compute_ranker_gate(
            effective_pair_count=40,
            degenerate_pair_rate=0.25,
            validation_acc=0.68,
            heldout_acc=0.63,
        )
        assert result.eligible
        assert result.confidence == "medium"
        assert result.weight == 0.10

    def test_high_confidence_gate_assigns_correct_weight(self):
        from backend.eval.pairwise_ranker import compute_ranker_gate

        result = compute_ranker_gate(
            effective_pair_count=60,
            degenerate_pair_rate=0.15,
            validation_acc=0.75,
            heldout_acc=0.70,
        )
        assert result.eligible
        assert result.confidence == "high"
        assert result.weight == 0.15

    def test_hard_caps_block_ranker(self):
        from backend.eval.pairwise_ranker import compute_ranker_gate

        result = compute_ranker_gate(
            effective_pair_count=100,
            degenerate_pair_rate=0.05,
            validation_acc=0.99,
            heldout_acc=0.99,
            hard_cap_count=1,
        )
        assert not result.eligible
        assert "hard_caps_detected" in result.reasons


class TestRankerContribution:
    def test_contribution_computes_final_delta(self):
        from backend.eval.pairwise_ranker import compute_ranker_contribution
        from backend.eval.pairwise_ranker import compute_ranker_gate

        gate = compute_ranker_gate(
            effective_pair_count=40,
            degenerate_pair_rate=0.25,
            validation_acc=0.68,
            heldout_acc=0.63,
        )
        contrib = compute_ranker_contribution(
            calibrated_q=0.70,
            learned_rank_q=0.50,
            action_type="speech",
            gate_result=gate,
        )
        assert contrib.used
        expected_final = (1 - 0.10) * 0.70 + 0.10 * 0.50  # 0.68
        assert abs(contrib.final_delta - (expected_final - 0.70)) < 0.01

    def test_debug_only_contributes_zero(self):
        from backend.eval.pairwise_ranker import compute_ranker_contribution
        from backend.eval.pairwise_ranker import compute_ranker_gate

        gate = compute_ranker_gate(
            effective_pair_count=5,
            degenerate_pair_rate=0.70,
            validation_acc=0.40,
            heldout_acc=0.30,
        )
        contrib = compute_ranker_contribution(
            calibrated_q=0.70,
            learned_rank_q=0.30,
            action_type="vote",
            gate_result=gate,
        )
        assert not contrib.used
        assert contrib.final_delta == 0.0
        assert contrib.weight == 0.0

    def test_delta_bounded_at_0_15(self):
        from backend.eval.pairwise_ranker import compute_ranker_contribution
        from backend.eval.pairwise_ranker import compute_ranker_gate

        gate = compute_ranker_gate(
            effective_pair_count=60,
            degenerate_pair_rate=0.10,
            validation_acc=0.80,
            heldout_acc=0.75,
        )
        contrib = compute_ranker_contribution(
            calibrated_q=0.10,
            learned_rank_q=0.95,
            action_type="speech",
            gate_result=gate,
        )
        # delta would be ~0.1275, which is under 0.15
        assert abs(contrib.final_delta) <= 0.15
