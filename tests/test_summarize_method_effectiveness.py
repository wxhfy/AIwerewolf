from __future__ import annotations

from pathlib import Path

from scripts import summarize_method_effectiveness as summary


def test_sanitize_endpoint_ids_redacts_nested_provider_endpoint() -> None:
    endpoint_id = "ep-" + "20260514115354" + "-k4jz4"
    payload = {
        "resolved_models": [
            {
                "provider": "doubao",
                "model": endpoint_id,
                "label": f"doubao:{endpoint_id}",
            }
        ],
        "chat_checks": [{"label": f"doubao:{endpoint_id}", "ok": True}],
        "safe_value": "anthropic:deepseek-v4-flash",
    }

    redacted = summary.sanitize_endpoint_ids(payload)

    assert redacted["resolved_models"][0]["model"] == "ep-<redacted>"
    assert redacted["resolved_models"][0]["label"] == "doubao:ep-<redacted>"
    assert redacted["chat_checks"][0]["label"] == "doubao:ep-<redacted>"
    assert redacted["safe_value"] == "anthropic:deepseek-v4-flash"


def test_select_target_seat_results_reuses_tracked_snapshot_by_default(monkeypatch) -> None:
    snapshot = [{"source": "docs/frozen.json", "paired_seed_count": 3}]

    def fail_collect() -> list[dict]:
        raise AssertionError("local outputs should not be scanned by default")

    monkeypatch.setattr(summary, "collect_target_seat_results", fail_collect)

    assert summary.select_target_seat_results(target_seat_snapshot=snapshot) == snapshot


def test_select_target_seat_results_scans_outputs_when_explicitly_refreshed(monkeypatch) -> None:
    refreshed = [{"source": "outputs/new.json", "paired_seed_count": 5}]

    monkeypatch.setattr(summary, "collect_target_seat_results", lambda: refreshed)

    assert summary.select_target_seat_results(target_seat_snapshot=[], refresh_target_seat=True) == refreshed


def test_existing_target_seat_results_redacts_endpoint_ids(tmp_path: Path) -> None:
    endpoint_id = "ep-" + "20260514115354" + "-k4jz4"
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(
        '{"target_seat_ab": [{"source": "x", "model": "doubao:' + endpoint_id + '"}]}',
        encoding="utf-8",
    )

    assert summary.existing_target_seat_results(facts_path) == [{"source": "x", "model": "doubao:ep-<redacted>"}]


def test_merge_target_seat_rows_prefers_tracked_real_llm_pilot() -> None:
    pilot = {
        "generated_at": "2026-06-09T17:15:35+08:00",
        "source": "outputs/target/real.json",
        "claim_scope": "real_llm_pilot_only",
        "target_role": "Seer",
        "baseline_framework": "basic_react",
        "candidate_framework": "rag_react",
        "paired_seed_count": 5,
        "target_adjusted_score_delta": 20.668,
        "target_role_task_delta": 0.283,
        "target_process_score_delta": 22.184,
        "candidate_decision_count": 201,
        "candidate_fallback_count": 0,
        "candidate_invalid_count": 0,
        "max_days": 20,
        "player_count": 7,
        "acceptance": {"accepted": False, "claim_level": "ci_not_positive"},
    }
    frozen_smoke = {
        "source": "outputs/target/smoke.json",
        "claim_scope": "smoke_only",
        "target_role": "Seer",
        "paired_seed_count": 3,
        "max_days": 1,
    }

    rows = summary.merge_target_seat_rows([frozen_smoke], pilot)

    assert rows[0]["source"] == "outputs/target/real.json"
    assert rows[0]["summary_source"] == "docs/evidence/PROJECT_TARGET_SEAT_TRACKC_PILOT.json"
    assert rows[0]["claim_scope"] == "real_llm_pilot_only"
    assert rows[0]["target_process_score_delta"] == 22.184
    assert rows[1]["claim_scope"] == "smoke_only"


def test_target_seat_claim_scope_marks_20_pair_pipeline_not_accepted() -> None:
    assert summary.target_seat_claim_scope(max_days=20, paired=20, accepted=False) == "pipeline_pilot_not_accepted"
    assert summary.target_seat_claim_scope(max_days=1, paired=20, accepted=False) == "smoke_only"
    assert summary.target_seat_claim_scope(max_days=20, paired=80, accepted=False) == "formal_candidate_not_accepted"
    assert summary.target_seat_claim_scope(max_days=20, paired=20, accepted=True) == "causal_supported"


def test_target_seat_boundary_uses_dynamic_paired_count() -> None:
    row = {"paired_seed_count": 20, "max_days": 20, "claim_scope": "pipeline_pilot_not_accepted"}

    boundary = summary.target_seat_boundary(row)

    assert "20-pair 真实 LLM pipeline pilot" in boundary
    assert "CI gate 未通过" in boundary
