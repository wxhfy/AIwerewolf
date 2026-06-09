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
