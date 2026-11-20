from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import Game
from backend.db.models import TrackCPostGameJob


def test_slice1_review_not_ready_returns_425_and_retry_after():
    init_db()
    game_id = f"slice1-not-ready-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="finished"))
        db.add(TrackCPostGameJob(game_id=game_id, status="pending"))
    client = TestClient(app)
    try:
        response = client.get(f"/api/games/{game_id}/reviews")
        assert response.status_code == 425
        data = response.json()
        assert data["code"] == "analysis_not_ready"
        assert response.headers.get("retry-after") == "2"

        status_response = client.get(f"/api/games/{game_id}/reviews/status")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["lifecycle_status"] == "pending"
        assert status_data["status"] == "pending"
        assert status_data["retryable"] is False
    finally:
        with SessionLocal.begin() as db:
            db.query(TrackCPostGameJob).filter_by(game_id=game_id).delete()
            db.query(Game).filter_by(id=game_id).delete()


def test_slice1_review_failed_and_not_scheduled_lifecycle():
    init_db()
    game_id_failed = f"slice1-failed-{uuid4().hex}"
    game_id_not_scheduled = f"slice1-unscheduled-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id_failed, status="finished"))
        db.add(TrackCPostGameJob(game_id=game_id_failed, status="failed"))
        db.add(Game(id=game_id_not_scheduled, status="finished"))
    client = TestClient(app)
    try:
        failed_resp = client.get(f"/api/games/{game_id_failed}/reviews")
        assert failed_resp.status_code == 409
        assert failed_resp.json()["code"] == "analysis_failed"

        failed_status = client.get(f"/api/games/{game_id_failed}/reviews/status").json()
        assert failed_status["lifecycle_status"] == "failed"
        assert failed_status["retryable"] is True

        unscheduled_status = client.get(f"/api/games/{game_id_not_scheduled}/reviews/status").json()
        assert unscheduled_status["lifecycle_status"] == "not_scheduled"
        assert unscheduled_status["retryable"] is False
    finally:
        with SessionLocal.begin() as db:
            db.query(TrackCPostGameJob).filter_by(game_id=game_id_failed).delete()
            db.query(Game).filter_by(id=game_id_failed).delete()
            db.query(Game).filter_by(id=game_id_not_scheduled).delete()
