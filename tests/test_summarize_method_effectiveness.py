from __future__ import annotations

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
