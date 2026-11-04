from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app import app
from backend.core.config import Settings
from backend.core.errors import install_exception_handlers
from backend.core.middleware import RedisRateLimitMiddleware
from backend.core.middleware import install_middleware
from backend.core.observability import count
from backend.core.observability import log_event
from backend.core.observability import metrics_snapshot
from backend.core.observability import operation_context
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import Game
from backend.db.models import TrackCPostGameJob
from backend.ops.worker_health import WorkerHeartbeat
from backend.ops.worker_health import WorkerHeartbeatLoop
from backend.ops.worker_health import record_heartbeat
from backend.ops.worker_health import worker_health


def _test_app(*, rate_limit: int = 0) -> FastAPI:
    local = FastAPI()
    config = replace(
        Settings.from_env(),
        max_request_body_bytes=1024,
        rate_limit_requests=rate_limit,
        redis_url="redis://unused" if rate_limit else "",
    )
    install_middleware(local, config)
    install_exception_handlers(local)

    @local.post("/input")
    def receive(payload: dict):
        return payload

    @local.get("/database")
    def broken_database():
        raise OperationalError("query-with-private-data", {}, RuntimeError("private-connection-data"))

    @local.get("/broken")
    def broken_endpoint():
        raise RuntimeError("private-exception-data")

    @local.get("/matches/{match_id}/rooms/{room_id}")
    def correlated(match_id: str, room_id: str):
        return {"match_id": match_id, "room_id": room_id}

    return local


@pytest.mark.parametrize(
    "path,status,code",
    [
        ("/missing", 404, "http_404"),
        ("/database", 503, "persistence_unavailable"),
        ("/broken", 500, "internal_error"),
    ],
)
def test_errors_have_safe_problem_envelope(path, status, code):
    response = TestClient(_test_app()).get(path, headers={"X-Request-ID": "observability-test"})
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == code
    assert response.json()["request_id"] == "observability-test"
    assert "private-" not in response.text
    if status == 503:
        assert response.headers["retry-after"] == "1"


def test_middleware_rejections_and_validation_share_problem_contract(monkeypatch):
    client = TestClient(_test_app())
    too_large = client.post("/input", content="a" * 1025)
    assert too_large.status_code == 413
    assert too_large.json()["request_id"] == too_large.headers["x-request-id"]
    invalid = client.post("/input", json=["private-input"])
    assert invalid.status_code == 422
    assert "private-input" not in invalid.text
    monkeypatch.setattr(RedisRateLimitMiddleware, "_consume", lambda *_args: 2)
    limited = TestClient(_test_app(rate_limit=1)).get("/missing")
    assert limited.status_code == 429
    assert limited.json()["request_id"]
    assert limited.headers["retry-after"]


def test_logs_have_correlation_without_query_data(caplog):
    caplog.set_level(logging.INFO, logger="aiwerewolf.access")
    client = TestClient(_test_app())
    response = client.get("/matches/m1/rooms/r1?private_query=hidden", headers={"X-Request-ID": "corr-1"})
    assert response.status_code == 200
    event = json.loads(caplog.records[-1].message)
    assert (event["request_id"], event["match_id"], event["room_id"]) == ("corr-1", "m1", "r1")
    assert event["route"] == "/matches/{match_id}/rooms/{room_id}"
    assert "private_query" not in caplog.text


def test_context_is_reset_and_counters_are_process_scoped(caplog):
    logger = logging.getLogger("test.observability")
    caplog.set_level(logging.INFO, logger=logger.name)
    with operation_context(request_id="context-1", match_id="match-1", room_id="room-1"):
        log_event(logger, "test.event")
    log_event(logger, "test.after")
    assert json.loads(caplog.records[0].message)["match_id"] == "match-1"
    assert json.loads(caplog.records[1].message)["match_id"] is None
    before = metrics_snapshot()["counters"].get("test.counter", 0)
    count("test.counter")
    assert metrics_snapshot()["counters"]["test.counter"] == before + 1


def test_health_redacts_dependency_error_details(monkeypatch):
    from backend.infrastructure.messaging.match_notifications import match_notifications

    monkeypatch.setattr(match_notifications, "health", lambda: "error: private-connection-details")
    client = TestClient(app)
    for path in ("/api/health", "/api/v1/health/ready"):
        response = client.get(path)
        assert "private-connection-details" not in response.text
        assert response.json()["checks"]["redis"] == "error: unavailable"


def test_worker_heartbeats_are_durable_and_stale_is_visible():
    init_db()
    worker_id = f"heartbeat-{uuid4().hex}"
    try:
        record_heartbeat(worker_id, "analysis")
        record_heartbeat(worker_id, "analysis")
        with SessionLocal.begin() as db:
            assert db.query(WorkerHeartbeat).filter_by(worker_id=worker_id).count() == 1
            db.get(WorkerHeartbeat, worker_id).heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        row = next(row for row in worker_health()["workers"] if row["worker_id"] == worker_id)
        assert row["status"] == "stale"
        with WorkerHeartbeatLoop(worker_id, "analysis"):
            row = next(row for row in worker_health()["workers"] if row["worker_id"] == worker_id)
            assert row["status"] == "running"
        row = next(
            row
            for row in TestClient(app).get("/api/v1/health/workers").json()["workers"]
            if row["worker_id"] == worker_id
        )
        assert row["status"] == "stopped"
    finally:
        with SessionLocal.begin() as db:
            db.query(WorkerHeartbeat).filter_by(worker_id=worker_id).delete()


def test_review_pending_failed_and_missing_are_distinct():
    init_db()
    game_id = f"review-health-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="finished"))
        db.add(TrackCPostGameJob(game_id=game_id, status="pending"))
    client = TestClient(app)
    try:
        pending = client.get(f"/api/games/{game_id}/reviews")
        assert pending.status_code == 425
        assert pending.json()["code"] == "analysis_not_ready"
        assert pending.headers["retry-after"] == "2"
        status = client.get(f"/api/games/{game_id}/reviews/status").json()
        assert status["status"] == "pending" and status["lifecycle_status"] == "pending"
        with SessionLocal.begin() as db:
            job = db.query(TrackCPostGameJob).filter_by(game_id=game_id).one()
            job.status = "failed"
        failed = client.get(f"/api/games/{game_id}/reviews/html")
        assert failed.status_code == 409
        assert failed.json()["code"] == "analysis_failed"
        assert failed.json()["analysis"]["retryable"]
        missing = client.get("/api/games/no-such-match/reviews/status")
        assert missing.status_code == 404 and missing.json()["code"] == "match_not_found"
        assert "queues" in client.get("/api/v1/system/metrics").json()
    finally:
        with SessionLocal.begin() as db:
            db.query(TrackCPostGameJob).filter_by(game_id=game_id).delete()
            db.query(Game).filter_by(id=game_id).delete()


def test_human_action_preserves_202_background_contract(monkeypatch):
    """Protect the pre-existing asynchronous /action work while editing shared API middleware."""
    import backend.app as api

    class HumanGame:
        def __init__(self):
            self.state = self
            self.pending_input = {"type": "speech"}
            self.id = "async-human-match"

        def apply_human_action(self, payload):
            assert payload == {"text": "test speech"}
            self.pending_input = None
            return self

        def snapshot(self, *, show_private):
            return {"id": self.id, "seq": 8, "pending_input": self.pending_input}

    game = HumanGame()
    continued = []
    monkeypatch.setattr(api._rooms, "get_room", lambda _id: SimpleNamespace(human_seat=1))
    monkeypatch.setattr(api._rooms, "get_active_game", lambda _id: game)
    monkeypatch.setattr(api._rooms, "record_snapshot", lambda *_args: None)
    monkeypatch.setattr(api._rooms, "set_room_status", lambda *_args: None)
    monkeypatch.setattr(api, "_mark_human_seat", lambda *_args: None)
    monkeypatch.setattr(api, "_attach_room_runtime", lambda *_args: None)
    monkeypatch.setattr(api, "_save_snapshot", lambda *_args: None)
    monkeypatch.setattr(api, "_human_runner_active", lambda *_args: False)
    monkeypatch.setattr(api, "_continue_human_room_in_background", lambda room_id: continued.append(room_id))
    response = TestClient(app).post("/api/rooms/async-human-room/action", json={"text": "test speech"})
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["match_id"] == game.id
    assert response.json()["seq"] == 8
    assert continued == ["async-human-room"]
