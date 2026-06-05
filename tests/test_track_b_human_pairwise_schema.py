"""Human pairwise label schema validation tests."""

from __future__ import annotations

import json
from pathlib import Path

from backend.eval.human_label_validator import validate_human_pairwise_label
from backend.eval.human_label_validator import validate_human_pairwise_labels


def _valid_template():
    return {
        "label_id": "label_000001",
        "game_id": "game_xxx",
        "source": "real_replay",
        "role": "Werewolf",
        "action_type": "vote",
        "day": 2,
        "phase": "DAY_VOTE",
        "context_summary": "Only information visible at decision time.",
        "visible_public_context": {"events": []},
        "visible_private_context": {"info": "private"},
        "option_a": {"opportunity_id": "opp_a", "action": {"type": "vote", "target": "P3"}, "evidence_event_ids": []},
        "option_b": {"opportunity_id": "opp_b", "action": {"type": "vote", "target": "P5"}, "evidence_event_ids": []},
        "label": "A_BETTER",
        "confidence": "high",
        "reason": "Option A better matches the role objective under the visible context.",
        "annotator_id": "annotator_001",
        "created_at": "2026-05-29T00:00:00Z",
    }


class TestHumanLabelSchema:
    def test_valid_template_passes(self):
        errs = validate_human_pairwise_label(_valid_template())
        assert not errs, f"Expected no errors, got {errs}"

    def test_missing_reason_fails(self):
        t = _valid_template()
        t["reason"] = ""
        errs = validate_human_pairwise_label(t)
        assert any("empty_reason" in e for e in errs), f"Expected empty_reason error, got {errs}"

    def test_invalid_label_fails(self):
        t = _valid_template()
        t["label"] = "INVALID"
        errs = validate_human_pairwise_label(t)
        assert any("invalid_label" in e for e in errs)

    def test_tie_is_allowed(self):
        t = _valid_template()
        t["label"] = "TIE"
        errs = validate_human_pairwise_label(t)
        assert not errs

    def test_uncertain_is_allowed(self):
        t = _valid_template()
        t["label"] = "UNCERTAIN"
        errs = validate_human_pairwise_label(t)
        assert not errs

    def test_missing_visible_context_fails(self):
        t = _valid_template()
        del t["visible_public_context"]
        errs = validate_human_pairwise_label(t)
        assert any("missing_required_field" in e for e in errs)

    def test_option_missing_action_fails(self):
        t = _valid_template()
        t["option_a"] = {"opportunity_id": "opp_a"}
        errs = validate_human_pairwise_label(t)
        assert any("option_a_missing_action" in e for e in errs)

    def test_future_info_leak_detected(self):
        t = _valid_template()
        t["reason"] = "After the game we know now that option A was better."
        errs = validate_human_pairwise_label(t)
        assert any("possible_future_info_leak" in e for e in errs)

    def test_batch_validation(self):
        labels = [_valid_template() for _ in range(5)]
        labels[2]["reason"] = ""  # Make one invalid
        result = validate_human_pairwise_labels(labels)
        assert result["valid"] == 4
        assert result["invalid"] == 1

    def test_template_file_exists(self):
        p = Path("data/health/human_pairwise_labels_template.jsonl")
        assert p.exists(), "Template file not found"
        labels = []
        with open(p) as f:
            for line in f:
                if line.strip():
                    labels.append(json.loads(line))
        assert len(labels) >= 1
        errs = validate_human_pairwise_label(labels[0])
        assert not errs, f"Template should be valid, got {errs}"
