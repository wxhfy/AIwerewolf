"""Tests for Track B MBTI/Profile Evaluation v0."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def summary_json():
    path = ROOT / "data" / "health" / "track_b_mbti_profile_summary.json"
    if not path.exists():
        pytest.skip("MBTI profile summary not yet generated")
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def report_text():
    path = ROOT / "docs" / "track_b_mbti_profile_evaluation_report.md"
    if not path.exists():
        pytest.skip("MBTI profile report not yet generated")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def games():
    path = ROOT / "data" / "health" / "track_b_mbti_profile_games.jsonl"
    if not path.exists():
        pytest.skip("MBTI profile games not yet generated")
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


# ---- Existence ----


def test_summary_exists(summary_json):
    assert len(summary_json["entries"]) >= 4


def test_report_exists(report_text):
    assert len(report_text) > 1000


def test_games_exist(games):
    assert len(games) >= 12


# ---- Profiles ----


def test_at_least_four_profiles(summary_json):
    profiles = {e["profile"] for e in summary_json["entries"]}
    assert len(profiles) >= 4, f"Need >=4 profiles, got {profiles}"


def test_each_profile_has_games_played(summary_json):
    for e in summary_json["entries"]:
        assert e["games_played"] >= 3, f"{e['profile']} has {e['games_played']} games"


def test_each_profile_has_scores(summary_json):
    for e in summary_json["entries"]:
        for field in ["avg_speech_score", "avg_vote_score", "avg_skill_score", "avg_survival_score"]:
            assert field in e, f"Missing {field} in {e['profile']}"


def test_each_profile_has_speech_audit(summary_json):
    for e in summary_json["entries"]:
        sa = e.get("speech_audit", {})
        assert len(sa) > 0, f"{e['profile']} has no speech audit features"


# ---- Low sample ----


def test_low_sample_warning(summary_json):
    for e in summary_json["entries"]:
        if e["games_played"] < 10:
            assert e.get("low_sample_warning") is True


# ---- Report sections ----


def test_report_has_expected_vs_observed(report_text):
    assert "Expected vs Observed" in report_text


def test_report_has_speech_act_distribution(report_text):
    assert "Speech Act Distribution" in report_text


def test_report_says_mbti_is_strategy_profile(report_text):
    assert "不是心理学" in report_text or "strategy profile" in report_text.lower()


def test_report_says_speech_semantic_is_audit_only(report_text):
    assert "audit-only" in report_text.lower() or "audit_only" in report_text.lower() or "不影响" in report_text


def test_report_not_ranked_by_win_rate_only(summary_json):
    entries = summary_json["entries"]
    for i in range(len(entries) - 1):
        assert entries[i]["avg_process_score"] >= entries[i + 1]["avg_process_score"]


def test_report_has_limitations(report_text):
    assert "Limitations" in report_text or "## 10." in report_text


def test_report_has_next_steps(report_text):
    assert "Next Steps" in report_text or "## 11." in report_text


# ---- Games data ----


def test_games_have_speech_audit(games):
    for g in games:
        sa = g.get("speech_audit", {})
        assert len(sa) > 0, f"Game {g.get('game_id', '?')[:8]} missing speech_audit"


def test_games_have_role_distribution(games):
    for g in games:
        rd = g.get("role_distribution", {})
        assert len(rd) > 0
        assert sum(rd.values()) == 7


def test_each_game_has_profile(games):
    profiles_found = set()
    for g in games:
        profiles_found.add(g["profile"])
    assert len(profiles_found) >= 4
