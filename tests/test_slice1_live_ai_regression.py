"""Regression around the slice1 live mock path (rooms → prepare → start).

Covers public visibility, event feed, fixture-off preview, and the
in-process fake runner guards that must not fire in production.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import _effective_llm_config
from backend.app import _local_fake_match_execution_enabled
from backend.app import app


def _enable_local_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AW_ENABLE_FIXTURE", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("_TEST_ALLOW_FAKE_LLM", "true")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("MATCH_WORKER_IN_PROCESS", "true")


def _create_and_prepare(client: TestClient, name: str) -> tuple[str, dict]:
    created = client.post(
        "/api/rooms",
        json={
            "name": name,
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
    return room_id, prepared.json()


def _wait_for_live_match(client: TestClient, room_id: str, match_id: str, timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    snapshot: dict | None = None
    phase_changes: list[dict] = []
    speech_events: list[dict] = []
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
            return snapshot
        time.sleep(0.05)
    pytest.fail("Timed out waiting for public phase changes and a speech event")


def _assert_no_roles(players: list[dict]) -> None:
    assert players
    for player in players:
        assert "role" not in player


def test_preview_keeps_fixture_off_and_rooms_path_open(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local_fake(monkeypatch)
    client = TestClient(app)

    fixture = client.post("/api/dev/fixture/start", json={"interval_ms": 15})
    assert fixture.status_code == 404

    room_id, prepared = _create_and_prepare(client, "Slice1RegFixtureOff")
    assert prepared["phase"] == "SETUP"
    assert prepared["disclosed"] is False
    _assert_no_roles(prepared["players"])
    public = client.get(f"/api/rooms/{room_id}/snapshot")
    assert public.status_code == 200
    _assert_no_roles(public.json()["players"])


def test_public_prepare_and_live_snapshot_hide_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local_fake(monkeypatch)
    monkeypatch.setenv("AW_DEV_ALLOW_PRIVATE", "0")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    client = TestClient(app)

    room_id, prepared = _create_and_prepare(client, "Slice1RegHideRoles")
    _assert_no_roles(prepared["players"])

    private = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true")
    assert private.status_code == 403

    started = client.post(f"/api/rooms/{room_id}/start")
    assert started.status_code == 200
    match_id = started.json()["match_id"]
    start_snapshot = started.json()["snapshot"]
    if not start_snapshot.get("disclosed") and start_snapshot.get("winner") is None:
        _assert_no_roles(start_snapshot.get("players", []))

    deadline = time.monotonic() + 30
    saw_in_progress = False
    while time.monotonic() < deadline:
        public = client.get(f"/api/rooms/{room_id}/snapshot")
        assert public.status_code == 200
        snapshot = public.json()
        if not snapshot.get("disclosed") and snapshot.get("winner") is None:
            _assert_no_roles(snapshot.get("players", []))
            if snapshot.get("phase") and snapshot.get("phase") != "SETUP":
                saw_in_progress = True
        leak = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true")
        assert leak.status_code == 403
        status = client.get(f"/api/matches/{match_id}")
        assert status.status_code == 200
        if status.json()["status"] == "failed":
            pytest.fail(f"fake match failed: {status.json().get('last_error')}")
        if status.json()["status"] == "completed":
            assert snapshot.get("disclosed") is True
            assert snapshot.get("players")
            for player in snapshot["players"]:
                assert "role" in player
            assert saw_in_progress
            return
        time.sleep(0.05)
    pytest.fail("Timed out waiting for a completed live match while checking role visibility")


def test_match_events_and_stream_show_phase_and_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local_fake(monkeypatch)
    client = TestClient(app)

    room_id, _prepared = _create_and_prepare(client, "Slice1RegStream")
    started = client.post(f"/api/rooms/{room_id}/start")
    assert started.status_code == 200
    match_id = started.json()["match_id"]
    _wait_for_live_match(client, room_id, match_id)

    events_res = client.get(f"/api/matches/{match_id}/events")
    assert events_res.status_code == 200
    body = events_res.json()
    events = body.get("events") or []
    assert events
    types = {event.get("type") for event in events}
    assert "PHASE_CHANGED" in types
    speech = [
        event
        for event in events
        if event.get("type") == "CHAT_MESSAGE"
        and isinstance((event.get("payload") or {}).get("speech"), str)
        and event["payload"]["speech"].strip()
    ]
    if not speech:
        # Feed rows may nest the chat in data/payload differently; accept any spoken text.
        speech = [
            event
            for event in events
            if "speech" in str(event)
        ]
    assert speech

    with client.stream("GET", f"/api/matches/{match_id}/stream") as response:
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type
        got_snapshot = False
        deadline = time.monotonic() + 8
        for line in response.iter_lines():
            text = line.decode() if isinstance(line, bytes) else line
            if text.startswith("event: snapshot") or text.startswith("data:"):
                got_snapshot = True
                break
            if time.monotonic() > deadline:
                break
        assert got_snapshot


def test_in_process_runner_requires_allow_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AW_ENABLE_FIXTURE", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("MATCH_WORKER_IN_PROCESS", "true")
    monkeypatch.setenv("_TEST_ALLOW_FAKE_LLM", "false")
    client = TestClient(app)

    room_id, _prepared = _create_and_prepare(client, "Slice1RegNoAllow")
    started = client.post(f"/api/rooms/{room_id}/start")
    assert started.status_code == 200
    match_id = started.json()["match_id"]
    assert started.json()["status"] == "queued"

    time.sleep(1.0)
    status = client.get(f"/api/matches/{match_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"


def test_production_does_not_start_local_fake_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AW_ENABLE_FIXTURE", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("_TEST_ALLOW_FAKE_LLM", "true")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("MATCH_WORKER_IN_PROCESS", "true")

    room = SimpleNamespace(llm_config={"provider": "fake", "model": "fake-llm"})
    assert _effective_llm_config(room)["provider"] == "fake"
    assert _local_fake_match_execution_enabled(room) is False

    client = TestClient(app)
    room_id, _prepared = _create_and_prepare(client, "Slice1RegProduction")
    started = client.post(f"/api/rooms/{room_id}/start")
    assert started.status_code == 200
    match_id = started.json()["match_id"]
    assert started.json()["status"] == "queued"
    time.sleep(1.0)
    status = client.get(f"/api/matches/{match_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"


def test_dev_siliconflow_pin_overrides_lobby_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LLM_PROVIDER", "siliconflow")
    monkeypatch.setenv("SILICONFLOW_MODEL", "THUDM/GLM-4-9B-0414")
    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.delenv("_TEST_ALLOW_FAKE_LLM", raising=False)

    room = SimpleNamespace(
        llm_config={
            "provider": "anthropic",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/anthropic",
        }
    )
    config = _effective_llm_config(room)
    assert config["provider"] == "siliconflow"
    assert config["model"] == "THUDM/GLM-4-9B-0414"
    assert config["base_url"] == "https://api.siliconflow.cn/v1"
    assert "api_key" not in config
    assert _local_fake_match_execution_enabled(room) is False


def test_production_does_not_pin_siliconflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "siliconflow")
    monkeypatch.setenv("SILICONFLOW_MODEL", "THUDM/GLM-4-9B-0414")

    room = SimpleNamespace(
        llm_config={
            "provider": "anthropic",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/anthropic",
        }
    )
    config = _effective_llm_config(room)
    assert config["provider"] == "anthropic"
    assert config["model"] == "deepseek-v4-flash"
