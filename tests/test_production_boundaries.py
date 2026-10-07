from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import _initialize_database
from backend.app import app
from backend.application.matches.repository import MatchJobRepository
from backend.core.config import validate_production_configuration
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import Game
from backend.db.models import GameRoom
from backend.db.models import MatchJob


def test_production_configuration_fails_closed_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("LLM_PROVIDER", "bigmodel")
    monkeypatch.setenv("AIWEREWOLF_STRICT_MODE", "true")
    monkeypatch.setenv("ALLOW_FALLBACK", "false")
    monkeypatch.delenv("_TEST_ALLOW_FAKE_LLM", raising=False)

    with pytest.raises(RuntimeError, match="AUTH_MODE must be static_token"):
        validate_production_configuration()


def test_static_token_auth_and_moderator_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "static_token")
    monkeypatch.setenv("AUTH_TOKENS", "viewer-secret|viewer|viewer,mod-secret|mod|viewer;moderator")
    from backend.core.security import actor_from_authorization

    assert actor_from_authorization("Bearer viewer-secret").actor_id == "viewer"
    assert "moderator" in actor_from_authorization("Bearer mod-secret").roles


def test_database_initialization_errors_abort_api_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("backend.app.init_db", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        _initialize_database()


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr("backend.interfaces.http.api_v1.engine", BrokenEngine())
    response = TestClient(app).get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_expired_worker_cannot_renew_lease() -> None:
    init_db()
    game_id = "expired-worker-fencing-game"
    job_id = "expired-worker-fencing-job"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="running"))
        db.add(GameRoom(id="expired-worker-fencing-room", name="fencing"))
        db.add(
            MatchJob(
                id=job_id,
                game_id=game_id,
                room_id="expired-worker-fencing-room",
                status="running",
                worker_id="worker-old",
                lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )

    try:
        with pytest.raises(RuntimeError, match="lease expired"):
            MatchJobRepository().heartbeat(job_id, "worker-old")
    finally:
        with SessionLocal.begin() as db:
            db.query(MatchJob).filter_by(id=job_id).delete()
            db.query(GameRoom).filter_by(id="expired-worker-fencing-room").delete()
            db.query(Game).filter_by(id=game_id).delete()
