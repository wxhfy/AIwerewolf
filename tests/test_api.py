from fastapi.testclient import TestClient

from backend.app import app


def test_create_game_api() -> None:
    client = TestClient(app)
    response = client.post("/api/games?seed=7&agent_type=heuristic")

    assert response.status_code == 200
    data = response.json()
    assert data["winner"] in {"village", "wolf"}
    assert len(data["players"]) == 7
    assert data["events"]
    assert data["badge"]["holder_id"] is not None
    assert data["daily_summaries"]
    assert data["daily_summary_facts"]


def test_health_api() -> None:
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_room_api_flow() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=RoomA&seed=9&player_count=7&agent_type=llm")
    assert room_response.status_code == 200
    room = room_response.json()
    assert room["name"] == "RoomA"
    assert room["status"] == "idle"
    assert room["agent_type"] == "llm"

    get_room = client.get(f"/api/rooms/{room['id']}")
    assert get_room.status_code == 200
    assert get_room.json()["id"] == room["id"]
    assert get_room.json()["agent_type"] == "llm"

    game_response = client.post(f"/api/rooms/{room['id']}/games")
    assert game_response.status_code == 200
    game = game_response.json()
    assert game["winner"] in {"village", "wolf"}
    assert game["phase"] == "GAME_END"
    assert game["badge"]["holder_id"] is not None
    assert game["daily_summaries"]

    history_response = client.get(f"/api/rooms/{room['id']}/games")
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["id"] == game["id"]

    snapshot_response = client.get(f"/api/rooms/{room['id']}/snapshot")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["id"] == game["id"]
    assert snapshot["winner"] in {"village", "wolf"}
