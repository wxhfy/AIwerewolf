from __future__ import annotations

import json
from pathlib import Path

from scripts import summarize_real_llm_framework_runs as summary


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_group_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "seed,source_game_id,group_key,framework,players,wins,win_rate,avg_adjusted_final_score,avg_final_score,avg_vote_score,avg_speech_score,avg_skill_score,decision_count,fallback_count,invalid_count,knowledge_hit_rate,roles,role_wins,alignments",
                '1,g1,framework:basic_react,basic_react,7,2,0.285714,40,40,0,0,0.5,10,0,0,0.0,"{}","{}","{}"',
                '1,g2,framework:trackc_only,trackc_only,7,2,0.285714,45,45,0,0,0.6,10,0,0,0.8,"{}","{}","{}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _base_summary(*, max_days: int = 20, games_per_framework: int = 5, completed: int = 10) -> dict:
    return {
        "started_at": "2026-06-09T00:00:00+00:00",
        "generated_at": "2026-06-09T00:10:00+00:00",
        "axis": "framework",
        "games_per_framework": games_per_framework,
        "seeds": [1, 2, 3, 4, 5],
        "player_count": 7,
        "max_days": max_days,
        "game_timeout_s": 1200,
        "model_pool": ["doubao:model"],
        "frameworks": [{"name": "basic_react"}, {"name": "trackc_only"}],
        "completed_raw_games": completed,
        "failed_games": 0,
        "attempted_games": completed,
        "leaderboard_summary": {
            "paired_delta": {
                "baseline": "framework:basic_react",
                "candidate": "framework:trackc_only",
                "paired_seed_count": 5,
                "avg_adjusted_final_score_delta": 5.0,
                "avg_win_rate_delta": 0.0,
            }
        },
    }


def test_summarize_run_classifies_formal_candidate(tmp_path: Path) -> None:
    run_dir = tmp_path / "formal"
    _write_json(run_dir / "summary.json", _base_summary())
    _write_group_csv(run_dir / "group_results.csv")
    (run_dir / "failures.jsonl").write_text("", encoding="utf-8")

    result = summary.summarize_run(run_dir)

    assert result["scope"] == "formal_candidate"
    assert result["claim_level"] == "framework_trend"
    assert result["completed_raw_games"] == 10
    assert result["total_decisions"] == 20
    assert result["total_fallback"] == 0
    assert result["total_invalid"] == 0
    assert result["mean_knowledge_hit_rate"] == 0.4


def test_summarize_run_redacts_endpoint_ids_from_model_pool(tmp_path: Path) -> None:
    run_dir = tmp_path / "formal"
    payload = _base_summary()
    endpoint_id = "ep-" + "20260514115354" + "-k4jz4"
    payload["model_pool"] = [f"doubao:{endpoint_id}", "anthropic:deepseek-v4-flash"]
    _write_json(run_dir / "summary.json", payload)
    _write_group_csv(run_dir / "group_results.csv")
    (run_dir / "failures.jsonl").write_text("", encoding="utf-8")

    result = summary.summarize_run(run_dir)

    assert result["model_pool"] == ["doubao:ep-<redacted>", "anthropic:deepseek-v4-flash"]


def test_summarize_run_classifies_smoke_when_max_days_one(tmp_path: Path) -> None:
    run_dir = tmp_path / "smoke"
    _write_json(run_dir / "summary.json", _base_summary(max_days=1, games_per_framework=3, completed=6))
    _write_group_csv(run_dir / "group_results.csv")
    (run_dir / "failures.jsonl").write_text("", encoding="utf-8")

    result = summary.summarize_run(run_dir)

    assert result["scope"] == "smoke_only"
    assert result["claim_level"] == "pipeline_health_only"
    assert "max_days<=1" in result["boundary"]


def test_summarize_run_classifies_running_partial_without_games(tmp_path: Path) -> None:
    run_dir = tmp_path / "running"
    payload = _base_summary()
    payload.update(
        {
            "run_status": "partial",
            "updated_at": "2026-06-09T00:01:00+00:00",
            "completed_raw_games": 0,
            "failed_games": 0,
            "attempted_games": 0,
        }
    )
    payload.pop("generated_at")
    _write_json(run_dir / "partial_summary.json", payload)
    (run_dir / "group_results.csv").write_text(
        "seed,source_game_id,group_key,framework,players,wins,win_rate,avg_adjusted_final_score,avg_final_score,avg_vote_score,avg_speech_score,avg_skill_score,decision_count,fallback_count,invalid_count,knowledge_hit_rate,roles,role_wins,alignments\n",
        encoding="utf-8",
    )
    (run_dir / "failures.jsonl").write_text("", encoding="utf-8")

    result = summary.summarize_run(run_dir)

    assert result["status"] == "partial"
    assert result["scope"] == "running_no_completed_games"
    assert result["claim_level"] == "no_evidence_yet"


def test_summarize_run_handles_formal_analysis_schema(tmp_path: Path) -> None:
    run_dir = tmp_path / "formal_analysis"
    _write_json(
        run_dir / "summary.json",
        {
            "generated_at": "2026-06-09T00:00:00+00:00",
            "row_counts": {"raw": 20, "formal_v4flash": 12, "excluded": 8},
            "tier_summaries": {
                "baseline": {
                    "display_name": "basic_react",
                    "attempted_games": 6,
                    "completed_games": 5,
                    "failed_games": 1,
                    "external_failure_rate": 0.166667,
                    "village_win_rate": 0.4,
                    "macro_role_win_rate": 0.45,
                    "llm_decisions": 120,
                    "fallback_count": 0,
                    "invalid_count": 0,
                },
                "trackc_only": {
                    "display_name": "trackc_only",
                    "attempted_games": 6,
                    "completed_games": 4,
                    "failed_games": 2,
                    "external_failure_rate": 0.333333,
                    "village_win_rate": 0.5,
                    "macro_role_win_rate": 0.47,
                    "llm_decisions": 130,
                    "fallback_count": 0,
                    "invalid_count": 0,
                },
            },
            "rubric_leaderboard": [{"tier": "trackc_only"}, {"tier": "baseline"}],
        },
    )

    result = summary.summarize_run(run_dir)

    assert result["source_schema"] == "formal_v4flash_analysis"
    assert result["scope"] == "formal_analysis_with_failures"
    assert result["claim_level"] == "formal_framework_quantified"
    assert result["completed_raw_games"] == 9
    assert result["failed_games"] == 3
    assert result["attempted_games"] == 12
    assert result["total_decisions"] == 250
    assert result["total_fallback"] == 0
    assert result["total_invalid"] == 0
    assert result["leaderboard_summary"]["formal_v4flash_rows"] == 12


def test_formal_analysis_uses_rubric_scores(tmp_path: Path) -> None:
    run_dir = tmp_path / "formal_analysis"
    _write_json(
        run_dir / "summary.json",
        {
            "generated_at": "2026-06-09T00:00:00+00:00",
            "row_counts": {"formal_v4flash": 2, "excluded": 0},
            "tier_summaries": {
                "baseline": {
                    "display_name": "basic_react",
                    "completed_games": 1,
                    "failed_games": 0,
                    "attempted_games": 1,
                    "llm_decisions": 10,
                },
                "both": {
                    "display_name": "cognitive_full",
                    "completed_games": 1,
                    "failed_games": 0,
                    "attempted_games": 1,
                    "llm_decisions": 10,
                },
            },
            "rubric_leaderboard": [
                {"tier": "both", "rubric_total_score": 78.745},
                {"tier": "baseline", "rubric_total_score": 70.6437},
            ],
        },
    )

    result = summary.summarize_run(run_dir)
    scores = {row["framework"]: row["rubric_total_score"] for row in result["group_summary"]}

    assert scores == {"basic_react": 70.6437, "cognitive_full": 78.745}


def test_render_report_contains_boundaries(tmp_path: Path) -> None:
    run_dir = tmp_path / "formal"
    _write_json(run_dir / "summary.json", _base_summary())
    _write_group_csv(run_dir / "group_results.csv")
    (run_dir / "failures.jsonl").write_text("", encoding="utf-8")

    facts = summary.build_facts([run_dir])
    report = summary.render_report(facts)

    assert facts["aggregate"]["formal_candidate_runs"] == 1
    assert "Run 级证据边界" in report
    assert "Track C 对胜率有统计显著因果提升" in report
    assert "framework:trackc_only" in report


def test_build_facts_accepts_fixed_generated_at(tmp_path: Path) -> None:
    run_dir = tmp_path / "formal"
    _write_json(run_dir / "summary.json", _base_summary())
    _write_group_csv(run_dir / "group_results.csv")
    (run_dir / "failures.jsonl").write_text("", encoding="utf-8")

    facts = summary.build_facts([run_dir], generated_at="2026-06-09T15:36:46+08:00")

    assert facts["generated_at"] == "2026-06-09T15:36:46+08:00"


def test_existing_generated_at_reads_committed_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "facts.json"
    _write_json(output, {"generated_at": "2026-06-09T15:36:46+08:00"})

    assert summary.existing_generated_at(output) == "2026-06-09T15:36:46+08:00"
    assert summary.existing_generated_at(tmp_path / "missing.json") is None
