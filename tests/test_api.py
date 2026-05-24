from fastapi.testclient import TestClient

from backend.app import app
from backend.engine.game import WerewolfGame


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

    review_response = client.get(f"/api/games/{data['id']}/reviews")
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["status"] == "approved"
    assert review["publish_allowed"] is True
    assert review["validation_result"]["passed"] is True
    assert review["speech_acts"]
    assert review["suspicion_matrix"]
    assert review["html_report"]

    metrics_response = client.get(f"/api/games/{data['id']}/metrics")
    assert metrics_response.status_code == 200
    metrics = metrics_response.json()
    assert metrics["scoreboard"]
    assert metrics["player_scores"]
    assert metrics["speech_acts"]
    assert metrics["validation"]["publish_allowed"] is True

    html_response = client.get(f"/api/games/{data['id']}/reviews/html")
    assert html_response.status_code == 200
    assert "Track B Review" in html_response.text
    assert "AI Werewolf 复盘报告" in html_response.text


def test_create_game_with_wolfcha_10p_pack() -> None:
    client = TestClient(app)
    response = client.post("/api/games?seed=13&agent_type=heuristic&player_count=10")
    assert response.status_code == 200
    data = response.json()
    roles = {player.get("role") for player in client.get(f"/api/games/{data['id']}?show_private=true").json()["players"]}
    assert len(data["players"]) == 10
    assert "WhiteWolfKing" in roles
    assert "Guard" in roles


def test_health_api() -> None:
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_leaderboard_api_returns_cross_game_views() -> None:
    client = TestClient(app)
    client.post("/api/games?seed=31&agent_type=heuristic")
    client.post("/api/games?seed=37&agent_type=heuristic")

    response = client.get("/api/leaderboard")
    assert response.status_code == 200
    data = response.json()
    assert sorted(data.keys()) == ["persona", "role", "version"]
    assert data["role"]["entries"]
    assert data["version"]["entries"]


def test_room_api_flow() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=RoomA&seed=9&player_count=7&agent_type=heuristic")
    assert room_response.status_code == 200
    room = room_response.json()
    assert room["name"] == "RoomA"
    assert room["status"] == "idle"
    assert room["agent_type"] == "heuristic"
    assert room["player_count"] == 7

    get_room = client.get(f"/api/rooms/{room['id']}")
    assert get_room.status_code == 200
    assert get_room.json()["id"] == room["id"]
    assert get_room.json()["agent_type"] == "heuristic"

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


def test_human_room_flow_blocks_and_accepts_action() -> None:
    client = TestClient(app)
    probe_game = WerewolfGame(seed=7)
    human_seat = next(player.seat for player in probe_game.state.players if player.role.value == "Guard")

    room_response = client.post(
        f"/api/rooms?name=HumanRoom&seed=7&player_count=7&agent_type=heuristic&human_seat={human_seat}"
    )
    assert room_response.status_code == 200
    room = room_response.json()
    assert room["human_seat"] == human_seat

    start_response = client.post(f"/api/rooms/{room['id']}/start")
    assert start_response.status_code == 200
    pending_state = start_response.json()
    assert pending_state["pending_input"] is not None
    assert pending_state["pending_input"]["seat"] == human_seat

    target_id = pending_state["pending_input"]["options"][0]["id"]
    action_response = client.post(
        f"/api/rooms/{room['id']}/action",
        json={"target_id": target_id, "reasoning": "test action"},
    )
    assert action_response.status_code == 200
    resumed_state = action_response.json()
    assert resumed_state["id"] == pending_state["id"]
