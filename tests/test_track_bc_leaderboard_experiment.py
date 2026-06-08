from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from scripts import track_bc_leaderboard_experiment as exp


def _score(player_id: str, role: str, alignment: str, value: float, won: bool) -> exp.PlayerScore:
    return exp.PlayerScore(
        player_id=player_id,
        player_name=player_id,
        persona_id=None,
        persona_name=None,
        role=role,
        alignment=alignment,
        camp_result_score=1.0 if won else 0.0,
        role_task_score=value / 100,
        vote_score=value / 100,
        speech_score=value / 100,
        skill_score=value / 100,
        survival_score=value / 100,
        mistake_penalty=0.0,
        final_score=value,
        adjusted_final_score=value,
    )


def _metric(game_id: str, scores: list[exp.PlayerScore]) -> exp.GameMetrics:
    return exp.GameMetrics(
        game_id=game_id,
        winner="village",
        total_days=2,
        total_events=20,
        wolf_elimination_rate=1.0,
        village_survival_rate=0.8,
        info_efficiency=0.7,
        player_scores=scores,
    )


def _record(seed: int, framework: str, model_specs: Sequence[exp.ModelSpec]) -> dict:
    return {
        "seed": seed,
        "game_id": f"g-{framework}-{seed}",
        "framework": framework,
        "winner": "village",
        "days": 2,
        "events": 20,
        "elapsed_s": 0.01,
        "player_count": 7,
        "model_pool": [spec.label for spec in model_specs],
        "seat_assignments": [],
        "decision_count": 7,
        "fallback_count": 0,
        "fallback_rate": 0.0,
        "invalid_count": 0,
        "invalid_action_rate": 0.0,
        "retrieved_count": 3,
        "knowledge_hit_rate": 0.428571,
    }


def test_framework_experiment_exports_track_c_delta(tmp_path: Path) -> None:
    def runner(
        seed: int,
        player_count: int,
        max_days: int,
        model_specs: Sequence[exp.ModelSpec],
        framework: exp.FrameworkSpec,
        game_index: int,
    ) -> exp.GameRunResult:
        value = 82.0 if framework.name == "cognitive_full" else 60.0
        won = framework.name == "cognitive_full"
        scores = [
            _score("p1", "Villager", "village", value, won),
            _score("p2", "Seer", "village", value, won),
            _score("p3", "Werewolf", "wolf", value - 5, not won),
        ]
        metric = _metric(f"g-{framework.name}-{seed}", scores)
        return exp.GameRunResult(
            metric=metric,
            player_model_labels={score.player_id: model_specs[0].label for score in scores},
            record=_record(seed, framework.name, model_specs),
        )

    summary = exp.run_experiment(
        axis="framework",
        model_specs=[exp.ModelSpec("fake", "fake-llm")],
        frameworks=[exp.FRAMEWORKS["basic_react"], exp.FRAMEWORKS["cognitive_full"]],
        games=2,
        start_seed=11,
        player_count=7,
        max_days=3,
        output_dir=tmp_path,
        runner=runner,
    )

    leaderboard = json.loads((tmp_path / "leaderboard.json").read_text(encoding="utf-8"))
    keys = [entry["key"] for entry in leaderboard["entries"]]

    assert "framework:basic_react" in keys
    assert "framework:cognitive_full" in keys
    assert summary["leaderboard_summary"]["can_distinguish"] is True
    assert summary["leaderboard_summary"]["paired_delta"]["candidate"] == "framework:cognitive_full"
    assert summary["leaderboard_summary"]["paired_delta"]["avg_adjusted_final_score_delta"] > 0
    assert summary["role_win_rates"]["framework:cognitive_full"]["macro_role_win_rate"] > 0
    assert summary["bootstrap_reliability"]["iterations"] > 0
    assert (tmp_path / "rubric_leaderboard.json").exists()
    assert (tmp_path / "rubric_leaderboard.csv").exists()
    rubric_entries = summary["rubric_leaderboard"]["entries"]
    assert rubric_entries[0]["group_key"] == "framework:cognitive_full"
    assert set(rubric_entries[0]["rubric_dimensions"]) == {
        "single_agent",
        "multi_agent",
        "engineering",
        "advanced_bc",
    }
    assert rubric_entries[0]["rubric_total_score"] > rubric_entries[-1]["rubric_total_score"]
    report = (tmp_path / "academic_report.md").read_text(encoding="utf-8")
    assert "Rubric Leaderboard" in report
    assert "Track C 非冗余性说明" in report
    assert "Bootstrap Reliability" in report


def test_model_axis_splits_single_game_metrics_by_player_model(tmp_path: Path) -> None:
    model_a = exp.ModelSpec("fake", "model-a")
    model_b = exp.ModelSpec("fake", "model-b")

    def runner(
        seed: int,
        player_count: int,
        max_days: int,
        model_specs: Sequence[exp.ModelSpec],
        framework: exp.FrameworkSpec,
        game_index: int,
    ) -> exp.GameRunResult:
        labels: dict[str, str] = {}
        scores: list[exp.PlayerScore] = []
        roles = [
            ("p1", "Villager", "village"),
            ("p2", "Seer", "village"),
            ("p3", "Werewolf", "wolf"),
            ("p4", "Witch", "village"),
        ]
        for seat_index, (player_id, role, alignment) in enumerate(roles):
            spec = exp.model_for_seat(model_specs, game_index, seat_index)
            labels[player_id] = spec.label
            value = 85.0 if spec.model == "model-a" else 55.0
            scores.append(_score(player_id, role, alignment, value, won=spec.model == "model-a"))
        return exp.GameRunResult(
            metric=_metric(f"g-model-{seed}", scores),
            player_model_labels=labels,
            record=_record(seed, framework.name, model_specs),
        )

    summary = exp.run_experiment(
        axis="model",
        model_specs=[model_a, model_b],
        frameworks=[exp.FRAMEWORKS["cognitive_full"]],
        games=2,
        start_seed=21,
        player_count=7,
        max_days=3,
        output_dir=tmp_path,
        runner=runner,
    )

    leaderboard = json.loads((tmp_path / "leaderboard.json").read_text(encoding="utf-8"))
    keys = {entry["key"] for entry in leaderboard["entries"]}

    assert keys == {"model:fake:model-a", "model:fake:model-b"}
    assert summary["leaderboard_summary"]["can_distinguish"] is True
    assert summary["role_distribution_audit"]["model:fake:model-a"]["seat_samples"] > 0
    assert summary["role_win_rates"]["model:fake:model-a"]["micro_role_win_rate"] > 0
    assert summary["rubric_leaderboard"]["weights"] == {
        "single_agent": 20.0,
        "multi_agent": 20.0,
        "engineering": 30.0,
        "advanced_bc": 30.0,
    }
    assert "role_wins" in (tmp_path / "group_results.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "rubric_total_score" in (tmp_path / "rubric_leaderboard.csv").read_text(encoding="utf-8").splitlines()[0]
    assert (tmp_path / "group_results.csv").exists()


def test_framework_specs_encode_academic_baseline_and_full_stack() -> None:
    basic = exp.FRAMEWORKS["basic_react"]
    full = exp.FRAMEWORKS["cognitive_full"]

    assert basic.env["COGNITIVE_ENABLE_TRACK_C"] == "0"
    assert basic.env["COGNITIVE_ENABLE_ANTI_PATTERNS"] == "0"
    assert basic.env["COGNITIVE_ENABLE_REFLECTION"] == "0"
    assert basic.retrieval_policy == "global_only"
    assert full.env["COGNITIVE_ENABLE_TRACK_C"] == "1"
    assert full.env["COGNITIVE_ENABLE_ANTI_PATTERNS"] == "1"
    assert full.env["COGNITIVE_ENABLE_REFLECTION"] == "1"
    assert full.retrieval_policy == "hybrid_role_mbti_global"
    assert exp.parse_model_specs("ark:m1,doubao:m2") == [
        exp.ModelSpec("ark", "m1"),
        exp.ModelSpec("doubao", "m2"),
    ]


def test_experiment_docstring_uses_v4flash_not_pro() -> None:
    doc = exp.__doc__ or ""

    assert "deepseek-v4-flash" in doc
    assert "deepseek-v4-pro" not in doc
