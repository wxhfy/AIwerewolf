"""Tests for Track B Minimal Leaderboard Demo.

Validates leaderboard data integrity, report structure, and rubric alignment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def summary_json():
    path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_summary.json"
    if not path.exists():
        pytest.skip("Leaderboard summary not yet generated.")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report_text():
    path = ROOT / "docs" / "track_b_minimal_leaderboard_report.md"
    if not path.exists():
        pytest.skip("Leaderboard report not yet generated.")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def games_jsonl():
    path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_games.jsonl"
    if not path.exists():
        pytest.skip("Leaderboard games not yet generated.")
    games = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                games.append(json.loads(line))
    return games


# ---- Existence ----

def test_summary_exists(summary_json):
    assert "entries" in summary_json
    assert len(summary_json["entries"]) >= 2


def test_report_exists(report_text):
    assert len(report_text) > 1000


def test_games_exist(games_jsonl):
    assert len(games_jsonl) >= 4  # at least 4 games


# ---- Agent versions ----

def test_at_least_two_agent_versions(summary_json):
    versions = {e["agent_version"] for e in summary_json["entries"]}
    assert len(versions) >= 2, f"Need >= 2 agent versions, got {versions}"


def test_each_version_has_games_played(summary_json):
    for e in summary_json["entries"]:
        assert e["games_played"] >= 3, f"{e['agent_version']} has only {e['games_played']} games"


# ---- Required fields ----

def test_each_entry_has_required_fields(summary_json):
    required = [
        "agent_version", "model_id", "games_played",
        "avg_process_score", "avg_speech_score", "avg_vote_score",
        "avg_skill_score", "critical_mistake_rate",
    ]
    for e in summary_json["entries"]:
        for field in required:
            assert field in e, f"Missing field '{field}' in {e['agent_version']}"


def test_each_entry_has_confidence_interval(summary_json):
    for e in summary_json["entries"]:
        ci = e.get("confidence_interval", [])
        assert len(ci) == 2, f"confidence_interval should be [low, high], got {ci}"
        assert ci[0] <= ci[1], f"confidence_interval low > high: {ci}"


# ---- Low sample warning ----

def test_low_sample_warning_when_games_lt_10(summary_json):
    for e in summary_json["entries"]:
        if e["games_played"] < 10:
            assert e.get("low_sample_warning") is True, \
                f"{e['agent_version']}: {e['games_played']} games but low_sample_warning not True"


# ---- Ranking ----

def test_not_ranked_by_win_rate_only(report_text, summary_json):
    """Leaderboard should not be sorted purely by win_rate."""
    entries = summary_json["entries"]
    # The entry with highest avg_process_score might not have highest win_rate
    if len(entries) >= 2:
        # The ranking should be by avg_process_score
        for i in range(len(entries) - 1):
            assert entries[i]["avg_process_score"] >= entries[i+1]["avg_process_score"], \
                f"Entries not sorted by avg_process_score: {entries[i]['agent_version']} < {entries[i+1]['agent_version']}"


# ---- Report sections ----

def test_report_has_required_sections(report_text):
    required = [
        "## 1. Executive Summary",
        "## 2. Experiment Setup",
        "## 3. Leaderboard",
        "## 7. Interpretation",
        "## 8. Rubric Alignment",
        "## 9. Limitations",
        "## 10. Next Steps",
    ]
    for section in required:
        assert section in report_text, f"Missing section: {section}"


def test_report_mentions_low_sample(report_text):
    assert "LOW_SAMPLE" in report_text or "low_sample" in report_text.lower() or \
           "低样本" in report_text or "不是统计" in report_text


def test_report_mentions_smoke_test(report_text):
    assert "smoke" in report_text.lower() or "PASS_SMOKE" in report_text


# ---- Rubric alignment ----

def test_rubric_leaderboard_is_pass_smoke(report_text):
    rubric_section = report_text.split("## 8. Rubric Alignment")[1].split("---")[0] if "## 8." in report_text else ""
    assert "PASS_SMOKE" in rubric_section or "PASS_SMOKE" in report_text, \
        "Leaderboard rubric should be PASS_SMOKE"


# ---- Games JSONL ----

def test_games_have_source(games_jsonl):
    for g in games_jsonl:
        assert "source" in g
        assert g["source"] == "real_llm_game"


def test_games_have_scores(games_jsonl):
    for g in games_jsonl:
        assert "player_scores" in g
        assert len(g["player_scores"]) >= 1
        ps = g["player_scores"][0]
        assert "process_score" in ps
        assert "speech_score" in ps
        assert "vote_score" in ps


def test_games_have_game_summary(games_jsonl):
    for g in games_jsonl:
        summary = g.get("game_summary", {})
        assert "avg_process_score" in summary
        assert "critical_mistakes" in summary
