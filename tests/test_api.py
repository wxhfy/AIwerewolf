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
    assert data["daily_summaries"]
    assert data["daily_summary_facts"]


def test_health_api() -> None:
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_room_api_flow() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=RoomA&seed=9&player_count=7")
    assert room_response.status_code == 200
    room = room_response.json()
    assert room["name"] == "RoomA"
    assert room["status"] == "idle"

    get_room = client.get(f"/api/rooms/{room['id']}")
    assert get_room.status_code == 200
    assert get_room.json()["id"] == room["id"]

    game_response = client.post(f"/api/rooms/{room['id']}/games")
    assert game_response.status_code == 200
    game = game_response.json()
    assert game["winner"] in {"village", "wolf"}
    assert game["phase"] == "GAME_END"
    assert game["daily_summaries"]
