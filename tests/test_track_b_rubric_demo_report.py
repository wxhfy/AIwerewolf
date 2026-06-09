"""Tests for Track B Rubric Demo Report quality.

Validates structural integrity, ID consistency, and rubric alignment
of the generated demo report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def report_text():
    path = ROOT / "docs" / "track_b_rubric_demo_report.md"
    if not path.exists():
        pytest.skip("Demo report not yet generated. Run scripts/build_rubric_demo.py first.")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def summary_json():
    path = ROOT / "data" / "health" / "track_b_rubric_demo_summary.json"
    if not path.exists():
        pytest.skip("Demo summary not yet generated. Run scripts/build_rubric_demo.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ---- Existence and structure ----


def test_report_exists(report_text):
    assert len(report_text) > 1000, "Report should be non-trivial"


def test_all_required_sections(report_text):
    required = [
        "## 1. Executive Summary",
        "## 2. Game Metadata",
        "## 3. Multi-Dimensional Score Summary",
        "## 4. Critical Decision Review",
        "## 5. Counterfactual Review",
        "## 6. Improvement Suggestions",
        "## 7. Rubric Alignment",
        "## 8. Limitations",
        "## 9. Next Steps",
    ]
    for section in required:
        assert section in report_text, f"Missing required section: {section}"


# ---- ID consistency ----


def test_no_internal_cf_ids_in_report(report_text):
    """CD/CF IDs must use CD-XXX / CF-XXX format, not internal cf_XXXX."""
    internal_ids = re.findall(r"\bcf_\d{4}\b", report_text)
    assert len(internal_ids) == 0, f"Internal CF IDs leaked into report: {internal_ids}"


def test_cd_ids_sequential(report_text):
    """CD IDs should be sequential CD-001, CD-002, ..."""
    cd_ids = re.findall(r"CD-(\d{3})", report_text)
    nums = sorted({int(n) for n in cd_ids})
    assert nums[0] == 1, f"First CD ID should be CD-001, got CD-{nums[0]:03d}"
    for i, n in enumerate(nums):
        assert n == i + 1, f"CD IDs not sequential: missing CD-{i + 1:03d}"


def test_cf_ids_sequential(report_text):
    """CF IDs should be sequential CF-001, CF-002, ..."""
    cf_ids = re.findall(r"CF-(\d{3})", report_text)
    if cf_ids:
        nums = sorted({int(n) for n in cf_ids})
        assert nums[0] == 1, f"First CF ID should be CF-001, got CF-{nums[0]:03d}"
        for i, n in enumerate(nums):
            assert n == i + 1, f"CF IDs not sequential: missing CF-{i + 1:03d}"


def test_cd_references_cf_only_existing(report_text):
    """Every CD's counterfactual_ids should reference CF IDs that exist in the report."""
    # Extract all CF IDs actually displayed
    cf_ids_displayed = set(re.findall(r"^#### (CF-\d{3}):", report_text, re.MULTILINE))
    # Also add synthetic CF IDs
    cf_ids_displayed |= set(re.findall(r"^#### (CF-\d{3}):", report_text, re.MULTILINE))

    # Extract CD→CF references from Critical Decision Review section
    cd_section = (
        report_text.split("## 4. Critical Decision Review")[1].split("---")[0] if "## 4." in report_text else ""
    )
    # Find all CF references in CD tables: | **Counterfactuals** | CF-001, CF-002 |
    cf_refs_in_cds = set()
    for line in cd_section.split("\n"):
        if "**反事实推演**" in line or "**Counterfactuals**" in line:
            for m in re.finditer(r"CF-\d{3}", line):
                cf_refs_in_cds.add(m.group(0))

    if cf_refs_in_cds:
        missing = cf_refs_in_cds - cf_ids_displayed
        assert len(missing) == 0, f"CD references CF IDs not in report: {missing}"


# ---- Leaderboard PENDING ----


def test_leaderboard_status_is_pending(report_text):
    assert (
        "PENDING" in report_text.split("## 7. Rubric Alignment")[1].split("## 8.")[0]
        if "## 7." in report_text
        else True
    )


# ---- Limitations ----


def test_controlled_fixture_limitation_present(report_text):
    limitations = report_text.split("## 8. Limitations")[1].split("---")[0] if "## 8." in report_text else ""
    assert "controlled_fixture_replay" in limitations.lower() or "fixture" in limitations.lower()


# ---- No truncation ----


def test_no_truncated_short_sentences(report_text):
    """Should not contain obviously truncated tokens like standalone single chars."""
    # Check table cells aren't just 2-3 chars (likely truncations)
    # We look for pipe-delimited cells with 1-2 chars that look truncated
    truncated_patterns = [
        r"\|\s+wol\s*\|",  # truncated "wolf"
        r"\|\s+pre\s*\|",  # truncated "prevent" or "predict"
    ]
    for pat in truncated_patterns:
        matches = re.findall(pat, report_text, re.IGNORECASE)
        assert len(matches) == 0, f"Truncated text found: {matches}"


# ---- Summary JSON ----


def test_summary_has_required_fields(summary_json):
    assert "demo_version" in summary_json
    assert "critical_decisions" in summary_json
    assert "rubric_alignment" in summary_json
    assert "limitations" in summary_json


def test_summary_critical_decisions_consistency(summary_json):
    cd = summary_json["critical_decisions"]
    actual_total = len(cd["items"])
    assert cd["total"] == actual_total, f"total={cd['total']} but items={actual_total}"
    actual_with_cf = sum(1 for item in cd["items"] if len(item["counterfactual_ids"]) > 0)
    assert cd["with_counterfactual"] == actual_with_cf, (
        f"with_counterfactual={cd['with_counterfactual']} but actual={actual_with_cf}"
    )


def test_summary_ambiguous_count(summary_json):
    cd = summary_json["critical_decisions"]
    actual_ambiguous = sum(1 for item in cd["items"] if item.get("_ambiguous"))
    assert cd["ambiguous_downgraded"] == actual_ambiguous
