from __future__ import annotations

import json
from pathlib import Path

from scripts import summarize_target_seat_trackc_pilot as pilot


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _result(side: str, seed: int, *, adjusted: float, role_task: float, process: float) -> dict:
    return {
        "side": side,
        "seed": seed,
        "target": {"seat": 4, "role": "Seer", "alignment": "village"},
        "game_id": f"{side}-{seed}",
        "winner": "wolf",
        "target_won": False,
        "target_score": {
            "adjusted_final_score": adjusted,
            "role_task_score": role_task,
            "process_score": process,
        },
        "decision_summary": {"decision_count": 10, "fallback_count": 0, "invalid_count": 0},
        "seat_assignments": [
            {"seat": 4, "model": "anthropic:model-a", "is_target": True},
            {"seat": 1, "model": "anthropic:model-a", "is_target": False},
        ],
    }


def test_build_facts_marks_real_llm_pilot_not_causal(tmp_path: Path) -> None:
    source = tmp_path / "target.json"
    _write_json(
        source,
        {
            "runner": "target_seat_trackc_ab_experiment.py",
            "target_role": "Seer",
            "target_occurrence": 1,
            "baseline_framework": "basic_react",
            "candidate_framework": "rag_react",
            "requested_seeds": [1, 2],
            "player_count": 7,
            "max_days": 20,
            "model_pool": ["anthropic:model-a"],
            "games_jsonl": str(tmp_path / "games.jsonl"),
            "failures_jsonl": str(tmp_path / "failures.jsonl"),
            "baseline_results": [
                _result("baseline", 1, adjusted=10, role_task=0.1, process=10),
                _result("baseline", 2, adjusted=20, role_task=0.2, process=20),
            ],
            "candidate_results": [
                _result("candidate", 1, adjusted=15, role_task=0.2, process=15),
                _result("candidate", 2, adjusted=18, role_task=0.3, process=18),
            ],
            "failures": [],
            "comparison": {
                "paired_seed_count": 2,
                "paired_seeds": [1, 2],
                "baseline_completed": 2,
                "candidate_completed": 2,
                "baseline_target_win_rate": 0.0,
                "candidate_target_win_rate": 0.0,
                "target_win_rate_delta": 0.0,
                "baseline_target_adjusted_score": 15,
                "candidate_target_adjusted_score": 16.5,
                "target_adjusted_score_delta": 1.5,
                "target_role_task_delta": 0.1,
                "target_process_score_delta": 1.5,
                "positive_adjusted_score_delta_seeds": 1,
                "positive_role_task_delta_seeds": 2,
                "positive_win_delta_seeds": 0,
                "candidate_decision_count": 20,
                "candidate_fallback_count": 0,
                "candidate_invalid_count": 0,
                "candidate_invalid_rate": 0.0,
                "bootstrap_ci": {
                    "adjusted_final_score_delta": {"mean": 1.5, "ci95_low": -2.0, "ci95_high": 5.0},
                    "role_task_score_delta": {"mean": 0.1, "ci95_low": 0.0, "ci95_high": 0.2},
                    "process_score_delta": {"mean": 1.5, "ci95_low": -2.0, "ci95_high": 5.0},
                    "target_win_rate_delta": {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0},
                },
                "acceptance": {
                    "accepted": False,
                    "claim_level": "ci_not_positive",
                    "gates": {
                        "enough_samples": True,
                        "strict_health": True,
                        "score_gate": True,
                        "role_task_gate": True,
                        "win_gate": True,
                        "ci_gate": False,
                        "improvement_gate": True,
                    },
                },
            },
        },
    )

    facts = pilot.build_facts(source_path=source, generated_at="2026-06-09T00:00:00+08:00")

    assert facts["claim_scope"] == "real_llm_pilot_only"
    assert facts["paired_seed_count"] == 2
    assert facts["paired_rows"][0]["adjusted_delta"] == 5.0
    assert facts["acceptance_gate_summary"]["ci_gate"] is False
    assert "不能写成 Track C 已经获得单目标席位因果增益。" in facts["cannot_write"]

    report = pilot.render_report(facts)
    assert "真实 LLM Pilot" in report
    assert "CI gate 未通过" in report
    assert "不是最终因果证明" in report


def test_existing_generated_at_reads_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "facts.json"
    _write_json(output, {"generated_at": "2026-06-09T00:00:00+08:00"})

    assert pilot.existing_generated_at(output) == "2026-06-09T00:00:00+08:00"
    assert pilot.existing_generated_at(tmp_path / "missing.json") is None


def test_build_facts_marks_20_pair_pipeline_pilot_not_formal(tmp_path: Path) -> None:
    source = tmp_path / "target.json"
    baseline_results = [
        _result("baseline", seed, adjusted=10 + seed, role_task=0.1, process=10 + seed) for seed in range(1, 21)
    ]
    candidate_results = [
        _result("candidate", seed, adjusted=13 + seed, role_task=0.15, process=13 + seed) for seed in range(1, 21)
    ]
    _write_json(
        source,
        {
            "runner": "target_seat_trackc_ab_experiment.py",
            "target_role": "Seer",
            "target_occurrence": 1,
            "baseline_framework": "basic_react",
            "candidate_framework": "rag_react",
            "requested_seeds": list(range(1, 21)),
            "player_count": 7,
            "max_days": 20,
            "model_pool": ["anthropic:model-a"],
            "baseline_results": baseline_results,
            "candidate_results": candidate_results,
            "failures": [],
            "comparison": {
                "paired_seed_count": 20,
                "paired_seeds": list(range(1, 21)),
                "baseline_completed": 20,
                "candidate_completed": 20,
                "target_win_rate_delta": 0.0,
                "target_adjusted_score_delta": 3.0,
                "target_role_task_delta": 0.05,
                "target_process_score_delta": 3.0,
                "candidate_decision_count": 200,
                "candidate_fallback_count": 0,
                "candidate_invalid_count": 0,
                "candidate_invalid_rate": 0.0,
                "bootstrap_ci": {
                    "adjusted_final_score_delta": {"mean": 3.0, "ci95_low": -1.0, "ci95_high": 7.0},
                    "role_task_score_delta": {"mean": 0.05, "ci95_low": -0.01, "ci95_high": 0.1},
                    "process_score_delta": {"mean": 3.0, "ci95_low": -1.0, "ci95_high": 7.0},
                    "target_win_rate_delta": {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0},
                },
                "acceptance": {
                    "accepted": False,
                    "claim_level": "ci_not_positive",
                    "gates": {
                        "enough_samples": True,
                        "strict_health": True,
                        "score_gate": True,
                        "role_task_gate": True,
                        "win_gate": False,
                        "ci_gate": False,
                        "improvement_gate": True,
                    },
                },
            },
        },
    )

    facts = pilot.build_facts(source_path=source, generated_at="2026-06-09T00:00:00+08:00")
    report = pilot.render_report(facts)

    assert facts["claim_scope"] == "pipeline_pilot_not_accepted"
    assert "各完成 20 局" in facts["can_write"][1]
    assert "20 paired seeds pipeline pilot" in facts["cannot_write"][2]
    assert "下一步按功效计划扩到 80-120 paired seeds" in facts["next_required_experiment"]
    assert "20-pair pipeline pilot 已完成" in report
