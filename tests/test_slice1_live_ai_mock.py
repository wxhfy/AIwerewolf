"""Endpoints exercised:
POST /api/rooms; POST /api/rooms/{room_id}/prepare; POST /api/rooms/{room_id}/start;
GET /api/rooms/{room_id}/snapshot.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import app


def test_live_ai_match_runs_without_dev_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake-only local worker must publish changing phases and speech publicly."""
    monkeypatch.delenv("AW_ENABLE_FIXTURE", raising=False)
    monkeypatch.setenv("_TEST_ALLOW_FAKE_LLM", "true")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("MATCH_WORKER_IN_PROCESS", "true")

    client = TestClient(app)
    created = client.post(
        "/api/rooms",
        json={
            "name": "Slice1LiveFake",
            "seed": 7,
            "player_count": 7,
            "agent_type": "llm",
            "llm_config": {"provider": "anthropic", "model": "deepseek-v4-flash"},
        },
    )
    assert created.status_code == 200
    room_id = created.json()["id"]

    prepared = client.post(f"/api/rooms/{room_id}/prepare")
    assert prepared.status_code == 200
    assert prepared.json()["phase"] == "SETUP"
    assert prepared.json()["disclosed"] is False
    assert all("role" not in player for player in prepared.json()["players"])

    started = client.post(f"/api/rooms/{room_id}/start")
    assert started.status_code == 200
    match_id = started.json()["match_id"]

    deadline = time.monotonic() + 30
    snapshot = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/rooms/{room_id}/snapshot")
        assert response.status_code == 200
        snapshot = response.json()
        events = snapshot.get("events", [])
        phase_changes = [event for event in events if event.get("type") == "PHASE_CHANGED"]
        speech_events = [
            event
            for event in events
            if event.get("type") == "CHAT_MESSAGE"
            and isinstance(event.get("payload", {}).get("speech"), str)
            and event["payload"]["speech"].strip()
        ]
        match_status = client.get(f"/api/matches/{match_id}")
        assert match_status.status_code == 200
        if match_status.json()["status"] == "failed":
            pytest.fail(f"fake match failed: {match_status.json().get('last_error')}")
        if (
            match_status.json()["status"] == "completed"
            and len({event.get("phase") for event in phase_changes}) > 1
            and speech_events
        ):
            break
        time.sleep(0.05)
    else:
        pytest.fail("Timed out waiting for public phase changes and a speech event")

    assert snapshot is not None
    assert len({event.get("phase") for event in phase_changes}) > 1
    assert speech_events
    speeches = [event["payload"]["speech"].strip() for event in speech_events]
    assert all(any("\u4e00" <= char <= "\u9fff" for char in speech) for speech in speeches)
    assert all("speaks from the visible evidence" not in speech for speech in speeches)
    assert all("player speaks" not in speech.lower() for speech in speeches)
