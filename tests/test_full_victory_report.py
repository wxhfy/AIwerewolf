from __future__ import annotations

import json

from scripts.full_victory_report import build_payload
from scripts.full_victory_report import summarize_tier_results
from scripts.mbti_acceptance_batch import _summary


def test_summarize_tier_results_includes_role_mbti_and_deltas() -> None:
    baseline = [
        {
            "winner": "village",
            "days": 3,
            "duration_s": 10,
            "players": [
                {"role": "Seer", "mbti": "INTJ", "team": "village", "won": True},
                {"role": "Werewolf", "mbti": "ENTP", "team": "wolf", "won": False},
            ],
        }
    ]
    both = [
        {
            "winner": "wolf",
            "days": 2,
            "duration_s": 11,
            "players": [
                {"role": "Seer", "mbti": "INTJ", "team": "village", "won": False},
                {"role": "Werewolf", "mbti": "ENTP", "team": "wolf", "won": True},
            ],
        }
    ]

    summary = summarize_tier_results({"baseline": baseline, "anti_only": [], "trackc_only": [], "both": both})

    assert summary["tiers"]["baseline"]["role"]["Seer"]["win_rate"] == 1.0
    assert summary["tiers"]["both"]["mbti_role"]["ENTP+Werewolf"]["win_rate"] == 1.0
    assert summary["tier_deltas"]["both"]["game_win_rate"]["wolf"]["delta"] == 1.0
    assert summary["tier_deltas"]["both"]["role"]["Seer"]["delta"] == -1.0


def test_mbti_acceptance_summary_has_role_and_alignment_layers() -> None:
    rows = [
        {
            "target_mbti": "INTJ",
            "target_role": "Seer",
            "target_alignment": "village",
            "target_won": True,
            "target_decisions": 4,
            "winner": "village",
            "llm_decisions": 8,
            "fallback_decisions": 0,
            "invalid_decisions": 0,
            "duration_s": 1.0,
        },
        {
            "target_mbti": "INTJ",
            "target_role": "Werewolf",
            "target_alignment": "wolf",
            "target_won": False,
            "target_decisions": 5,
            "winner": "village",
            "llm_decisions": 9,
            "fallback_decisions": 0,
            "invalid_decisions": 0,
            "duration_s": 1.0,
        },
    ]

    summary = _summary("unit", "2026-01-01T00:00:00+00:00", rows, [], __file__, 2)

    assert summary["mbti_stats"]["INTJ"]["games"] == 2
    assert summary["role_stats"]["Seer"]["win_rate"] == 1.0
    assert summary["alignment_stats"]["wolf"]["win_rate"] == 0.0
    assert summary["mbti_role_stats"]["INTJ+Werewolf"]["games"] == 1
    assert summary["mbti_alignment_stats"]["INTJ+village"]["wins"] == 1


def test_build_payload_reads_tier_and_mbti_files(tmp_path) -> None:
    tier_dir = tmp_path / "tiers"
    tier_dir.mkdir()
    for tier in ("baseline", "anti_only", "trackc_only", "both"):
        (tier_dir / f"{tier}.jsonl").write_text("", encoding="utf-8")
    (tier_dir / "baseline.jsonl").write_text(
        json.dumps(
            {
                "winner": "village",
                "provider": "dsv4flash",
                "model": "dsv4flash:deepseek-v4-flash",
                "players": [{"role": "Guard", "mbti": "ISFJ", "team": "village", "won": True}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tier_dir / "both.jsonl").write_text(
        json.dumps(
            {
                "winner": "wolf",
                "provider": "deepseek",
                "model": "deepseek:deepseek-v4-flash",
                "players": [{"role": "Werewolf", "mbti": "ENTP", "team": "wolf", "won": True}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mbti_jsonl = tmp_path / "mbti.jsonl"
    mbti_jsonl.write_text(
        json.dumps(
            {
                "target_mbti": "ISFJ",
                "target_role": "Guard",
                "target_alignment": "village",
                "target_won": True,
                "winner": "village",
                "llm_decisions": 1,
                "fallback_decisions": 0,
                "invalid_decisions": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_payload(tier_dir, None, mbti_jsonl)

    assert payload["multi_tier"]["tiers"]["baseline"]["games_completed"] == 1
    assert payload["multi_tier_source_distribution"]["providers"] == {"deepseek": 1, "dsv4flash": 1}
    assert payload["multi_tier_source_distribution"]["models"] == {
        "deepseek:deepseek-v4-flash": 1,
        "dsv4flash:deepseek-v4-flash": 1,
    }
    assert payload["mbti_acceptance"]["mbti_role_stats"]["ISFJ+Guard"]["win_rate"] == 1.0
