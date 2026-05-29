"""Human pairwise labeling pipeline tests — verify scripts run and handle edge cases."""

from __future__ import annotations

import json, pytest, subprocess, sys
from pathlib import Path

DATA = Path("data/health")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


class TestHumanPairwisePipeline:
    def test_build_human_pairwise_queue_runs(self):
        rc, stdout, stderr = _run([sys.executable, "scripts/build_human_pairwise_queue.py",
                                    "--max", "10"])
        # Queue script always succeeds, even with low sample
        assert rc == 0, f"Queue build failed: {stderr}"
        qpath = DATA / "human_pairwise_queue.jsonl"
        assert qpath.exists(), f"Queue file not created: {qpath}"
        if qpath.exists():
            lines = [l for l in open(qpath) if l.strip()]
            print(f"\n  Queue candidates: {len(lines)}")

    def test_human_pairwise_queue_schema(self):
        qpath = DATA / "human_pairwise_queue.jsonl"
        if not qpath.exists():
            subprocess.run([sys.executable, "scripts/build_human_pairwise_queue.py",
                           "--max", "10"], capture_output=True, timeout=120)
        if not qpath.exists():
            pytest.skip("Queue file not available")
        with open(qpath) as f:
            for line in f:
                if not line.strip(): continue
                d = json.loads(line)
                required = ["label_id", "option_a", "option_b", "label", "role", "action_type"]
                for r in required:
                    assert r in d, f"Missing {r} in queue candidate"

    def test_human_pairwise_label_sample_validates(self):
        spath = DATA / "human_pairwise_labels_sample.jsonl"
        assert spath.exists(), "Sample labels not found"
        rc, stdout, stderr = _run([sys.executable,
            "scripts/validate_human_pairwise_labels.py",
            "--input", str(spath),
            "--output", str(DATA / "human_pairwise_validation_result.json"),
        ])
        assert rc == 0, f"Validation failed: {stderr}"
        result_path = DATA / "human_pairwise_validation_result.json"
        assert result_path.exists()
        r = json.loads(result_path.read_text())
        assert r["valid"] >= 4, f"Expected >=4 valid, got {r['valid']}"
        print(f"\n  Valid labels: {r['valid']}/{r['total']}")

    def test_validate_human_pairwise_labels_script(self):
        rc, stdout, stderr = _run([sys.executable,
            "scripts/validate_human_pairwise_labels.py",
            "--input", str(DATA / "human_pairwise_labels_sample.jsonl"),
        ])
        assert rc == 0
        result = json.loads((DATA / "human_pairwise_validation_result.json").read_text())
        assert "TIE" in result.get("label_distribution", {})
        assert "UNCERTAIN" in result.get("label_distribution", {})

    def test_evaluate_human_pairwise_agreement_runs(self):
        rc, stdout, stderr = _run([sys.executable,
            "scripts/evaluate_human_pairwise_agreement.py",
            "--labels", str(DATA / "human_pairwise_labels_sample.jsonl"),
        ])
        # Agreement script should succeed even with low sample
        assert rc == 0, f"Agreement eval failed: {stderr}"
        apath = DATA / "human_pairwise_agreement.json"
        assert apath.exists()
        r = json.loads(apath.read_text())
        assert "status" in r
        print(f"\n  Agreement status: {r['status']}")

    def test_vnext_human_pairwise_suite_skips_without_labels(self):
        """vNext eval should not fail when real labels are missing."""
        rc, stdout, stderr = _run([sys.executable,
            "scripts/evaluate_track_b_vnext.py", "--suite", "human_pairwise",
        ])
        # Should succeed regardless of label availability
        assert rc == 0 or "SKIPPED" in stdout or "No labels" in stdout

    def test_agreement_handles_tie_uncertain(self):
        spath = DATA / "human_pairwise_labels_sample.jsonl"
        labels = []
        with open(spath) as f:
            for line in f:
                if line.strip():
                    try: labels.append(json.loads(line))
                    except json.JSONDecodeError: pass
        ties = [l for l in labels if l.get("label") == "TIE"]
        uncertains = [l for l in labels if l.get("label") == "UNCERTAIN"]
        assert len(ties) >= 1, "Sample must contain TIE example"
        assert len(uncertains) >= 1, "Sample must contain UNCERTAIN example"
        # TIE and UNCERTAIN pass validator
        from backend.eval.human_label_validator import validate_human_pairwise_label
        for l in ties + uncertains:
            errs = validate_human_pairwise_label(l)
            assert not errs, f"TIE/UNCERTAIN should be valid, got {errs}"
