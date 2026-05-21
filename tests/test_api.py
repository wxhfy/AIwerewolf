from fastapi.testclient import TestClient

from backend.app import app


def test_create_game_api() -> None:
    client = TestClient(app)
    response = client.post("/api/games?seed=7")

    assert response.status_code == 200
    data = response.json()
    assert data["winner"] in {"village", "wolf"}
    assert len(data["players"]) == 7
    assert data["events"]


def test_health_api() -> None:
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
