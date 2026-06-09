from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import summarize_track_b_leaderboard_showcase as showcase


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_group_csv(path: Path, rows: list[dict]) -> None:
    headers = [
        "seed",
        "source_game_id",
        "group_key",
        "framework",
        "players",
        "wins",
        "win_rate",
        "avg_adjusted_final_score",
        "avg_final_score",
        "avg_vote_score",
        "avg_speech_score",
        "avg_skill_score",
        "decision_count",
        "fallback_count",
        "invalid_count",
        "knowledge_hit_rate",
        "roles",
        "role_wins",
        "alignments",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _group_row(group_key: str, *, decision_count: int = 10, players: int = 7) -> dict:
    return {
        "seed": "1",
        "source_game_id": "g1",
        "group_key": group_key,
        "framework": "full_cognitive",
        "players": str(players),
        "wins": "1",
        "win_rate": "0.25",
        "avg_adjusted_final_score": "42.0",
        "avg_final_score": "40.0",
        "avg_vote_score": "0.3",
        "avg_speech_score": "0.5",
        "avg_skill_score": "0.6",
        "decision_count": str(decision_count),
        "fallback_count": "0",
        "invalid_count": "0",
        "knowledge_hit_rate": "0.8",
        "roles": '{"Werewolf": 1}',
        "role_wins": '{"Werewolf": 1}',
        "alignments": '{"wolf": 1}',
    }


def _write_framework_run(run_dir: Path) -> None:
    _write_json(
        run_dir / "partial_summary.json",
        {
            "axis": "framework",
            "games_per_framework": 5,
            "frameworks": [{"name": "basic_react"}, {"name": "rag_react"}],
            "completed_raw_games": 1,
            "failed_games": 0,
            "attempted_games": 1,
            "max_days": 20,
            "model_pool": ["anthropic:model-a"],
        },
    )
    _write_jsonl(
        run_dir / "game_runs.jsonl",
        [
            {
                "game_id": "g1",
                "winner": "wolf",
                "days": 2,
                "events": 100,
                "elapsed_s": 30.0,
                "decision_count": 10,
                "fallback_count": 0,
                "invalid_count": 0,
                "retrieved_count": 2,
                "knowledge_hit_rate": 0.2,
                "provider_counts": {"anthropic": 10},
                "model_counts": {"model-a": 10},
            }
        ],
    )
    _write_group_csv(run_dir / "group_results.csv", [_group_row("framework:basic_react", decision_count=10)])


def _write_model_run(run_dir: Path) -> None:
    _write_json(
        run_dir / "summary.json",
        {
            "axis": "model",
            "frameworks": [{"name": "full_cognitive"}],
            "model_pool": ["anthropic:model-a", "anthropic:model-b"],
            "completed_raw_games": 1,
            "failed_games": 0,
            "attempted_games": 1,
            "max_days": 3,
            "leaderboard_summary": {"can_distinguish": True},
            "role_distribution_audit": {
                "model:anthropic:model-a": {"seat_samples": 4, "roles": {"Seer": 1}, "alignments": {"village": 4}}
            },
            "role_win_rates": {"model:anthropic:model-a": {"macro_role_win_rate": 0.25}},
            "bootstrap_reliability": {"reason": "pilot"},
        },
    )
    _write_jsonl(
        run_dir / "game_runs.jsonl",
        [
            {
                "game_id": "g2",
                "winner": "wolf",
                "days": 2,
                "events": 120,
                "elapsed_s": 40.0,
                "decision_count": 12,
                "fallback_count": 0,
                "invalid_count": 0,
                "retrieved_count": 5,
                "knowledge_hit_rate": 0.5,
                "provider_counts": {"anthropic": 12},
                "model_counts": {"model-a": 6, "model-b": 6},
            }
        ],
    )
    _write_group_csv(
        run_dir / "group_results.csv",
        [
            _group_row("model:anthropic:model-a", decision_count=12, players=4),
            _group_row("model:anthropic:model-b", decision_count=12, players=3),
        ],
    )
    _write_json(
        run_dir / "leaderboard.json",
        {"entries": [{"key": "model:anthropic:model-a", "avg_adjusted_final_score": 42.0}]},
    )
    _write_json(
        run_dir / "architecture_evidence_leaderboard.json",
        {
            "entries": [
                {
                    "rank": 1,
                    "group_key": "model:anthropic:model-a",
                    "rubric_total_score": 70.0,
                    "rubric_dimensions": {"single_agent": 10.0},
                    "evidence_signals": {"seat_samples": 4},
                }
            ]
        },
    )


def test_build_facts_uses_game_runs_for_total_decisions(tmp_path: Path) -> None:
    framework_dir = tmp_path / "framework"
    model_dir = tmp_path / "model"
    _write_framework_run(framework_dir)
    _write_model_run(model_dir)
    single_preflight = tmp_path / "single.json"
    multi_preflight = tmp_path / "multi.json"
    _write_json(
        single_preflight,
        {
            "status": "ok",
            "safe_for_formal_experiment": True,
            "chat_checks": [{"label": "anthropic:model-a", "ok": True, "elapsed_s": 1.0}],
        },
    )
    _write_json(
        multi_preflight,
        {
            "status": "unsafe",
            "safe_for_formal_experiment": False,
            "chat_checks": [
                {"label": "anthropic:model-a", "ok": True, "elapsed_s": 1.0},
                {"label": "anthropic:model-b", "ok": False, "elapsed_s": 1.0},
            ],
        },
    )

    facts = showcase.build_facts(
        framework_dir=framework_dir,
        model_dir=model_dir,
        single_preflight_path=single_preflight,
        multi_preflight_path=multi_preflight,
        generated_at="2026-06-09T00:00:00+08:00",
    )

    assert facts["aggregate"]["completed_real_llm_games"] == 2
    assert facts["aggregate"]["raw_decision_count"] == 22
    assert facts["aggregate"]["fallback_count"] == 0
    assert facts["provider_preflight"]["ok_models"] == ["anthropic:model-a"]
    assert facts["provider_preflight"]["failed_models"] == ["anthropic:model-b"]
    assert "不是 Track C 因果增益" in facts["claim_scope"]
    assert len(facts["track_b_layers"]) >= 7
    assert facts["track_b_showcase_panels"]["game_level_rows"][0]["decision_count"] == 10
    assert facts["track_b_showcase_panels"]["role_seat_rows"][0]["group_key"] == "model:anthropic:model-a"
    assert facts["track_b_showcase_panels"]["decision_health_rows"][-1]["scope"] == "aggregate"
    assert any("group_results" in boundary for boundary in facts["claim_boundaries"])


def test_render_report_states_track_b_boundary(tmp_path: Path) -> None:
    framework_dir = tmp_path / "framework"
    model_dir = tmp_path / "model"
    _write_framework_run(framework_dir)
    _write_model_run(model_dir)
    preflight = tmp_path / "preflight.json"
    _write_json(preflight, {"status": "ok", "safe_for_formal_experiment": True, "chat_checks": []})
    facts = showcase.build_facts(
        framework_dir=framework_dir,
        model_dir=model_dir,
        single_preflight_path=preflight,
        multi_preflight_path=preflight,
    )

    report = showcase.render_report(facts)

    assert "Track B Leaderboard 多层展示实验" in report
    assert "不是 Track C 因果增益报告" in report
    assert "对局层：真实 LLM 对局输入" in report
    assert "玩家/角色席位层" in report
    assert "评分维度层" in report
    assert "决策健康层与复盘产物层" in report
    assert "不能写成正式模型优劣结论" in report


def test_existing_generated_at_reads_committed_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "facts.json"
    _write_json(output, {"generated_at": "2026-06-09T16:19:56+08:00"})

    assert showcase.existing_generated_at(output) == "2026-06-09T16:19:56+08:00"
    assert showcase.existing_generated_at(tmp_path / "missing.json") is None
