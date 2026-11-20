from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend.app import app


def test_fixture_disabled_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    # AUTH irrelevant; do NOT set AW_ENABLE_FIXTURE (or set to 0); POST /api/dev/fixture/start -> 404
    monkeypatch.delenv("AW_ENABLE_FIXTURE", raising=False)
    client = TestClient(app)
    res_unset = client.post("/api/dev/fixture/start", json={"interval_ms": 15})
    assert res_unset.status_code == 404

    monkeypatch.setenv("AW_ENABLE_FIXTURE", "0")
    res_zero = client.post("/api/dev/fixture/start", json={"interval_ms": 15})
    assert res_zero.status_code == 404


def test_fixture_start_replays_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AW_ENABLE_FIXTURE", "1")
    client = TestClient(app)

    res = client.post("/api/dev/fixture/start", json={"interval_ms": 15})
    assert res.status_code == 200
    body = res.json()
    assert body.get("fixture") == "FIXTURE/MOCK"
    assert "room_id" in body and body["room_id"]
    assert "game_id" in body and body["game_id"]

    room_id = body["room_id"]
    game_id = body["game_id"]

    # Poll GET /api/rooms/{room_id}/snapshot up to 8s until status 200 and snapshot has phase
    deadline = time.time() + 8.0
    snapshot = None
    while time.time() < deadline:
        snap_res = client.get(f"/api/rooms/{room_id}/snapshot")
        if snap_res.status_code == 200:
            data = snap_res.json()
            if data.get("phase"):
                snapshot = data
                break
        time.sleep(0.05)

    assert snapshot is not None, "Timed out waiting for room snapshot with phase"
    assert "phase" in snapshot

    # Assert players have no "role" key while disclosed is false / winner is null
    if not snapshot.get("disclosed") and snapshot.get("winner") is None:
        players = snapshot.get("players", [])
        assert len(players) > 0
        for player in players:
            assert "role" not in player

    # Wait until GET /api/dev/fixture/status/{game_id} shows status finished OR last_snapshot_seq is not None (allow up to 15s)
    status_deadline = time.time() + 15.0
    status_ok = False
    while time.time() < status_deadline:
        status_res = client.get(f"/api/dev/fixture/status/{game_id}")
        if status_res.status_code == 200:
            status_data = status_res.json()
            if status_data.get("status") == "finished" or status_data.get("last_snapshot_seq") is not None:
                status_ok = True
                break
        time.sleep(0.05)

    assert status_ok, "Timed out waiting for fixture status finished or last_snapshot_seq not None"
