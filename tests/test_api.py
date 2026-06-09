import pytest
from fastapi.testclient import TestClient

from backend.app import _build_game
from backend.app import _rooms
from backend.app import app
from backend.engine.game import WerewolfGame


def test_create_game_api() -> None:
    client = TestClient(app)
    response = client.post("/api/games?seed=7&agent_type=llm")

    assert response.status_code == 200
    data = response.json()
    assert data["winner"] in {"village", "wolf"}
    assert len(data["players"]) == 10
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

    status_response = client.get(f"/api/games/{data['id']}/reviews/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["status"] == "ready"
    assert status["hasHtml"] is True
    assert status["hasMarkdown"] is True
    assert status["publishAllowed"] is True

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
    response = client.post("/api/games?seed=13&agent_type=llm&player_count=10")
    assert response.status_code == 200
    data = response.json()
    roles = {
        player.get("role") for player in client.get(f"/api/games/{data['id']}?show_private=true").json()["players"]
    }
    assert len(data["players"]) == 10
    assert "WhiteWolfKing" in roles
    assert "Guard" in roles


def test_health_api() -> None:
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["llm_provider"] == "fake"
    assert data["version"]


def test_leaderboard_api_returns_cross_game_views() -> None:
    client = TestClient(app)
    client.post("/api/games?seed=31&agent_type=llm")
    client.post("/api/games?seed=37&agent_type=llm")

    response = client.get("/api/leaderboard")
    assert response.status_code == 200
    data = response.json()
    assert sorted(data.keys()) == ["persona", "role", "version"]
    assert data["role"]["entries"]
    assert data["version"]["entries"]


def test_room_api_flow() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=RoomA&seed=9&player_count=7&agent_type=llm")
    assert room_response.status_code == 200
    room = room_response.json()
    assert room["name"] == "RoomA"
    assert room["status"] == "idle"
    assert room["agent_type"] == "llm"
    assert room["player_count"] == 7

    get_room = client.get(f"/api/rooms/{room['id']}")
    assert get_room.status_code == 200
    assert get_room.json()["id"] == room["id"]
    assert get_room.json()["agent_type"] == "llm"

    game_response = client.post(f"/api/rooms/{room['id']}/games")
    assert game_response.status_code == 200
    game = game_response.json()
    assert game["winner"] in {"village", "wolf"}
    assert game["phase"] == "GAME_END"
    assert "holder_id" in game["badge"]
    assert game["events"]

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
    probe_game = WerewolfGame(seed=7, player_count=7)
    human_seat = next(player.seat for player in probe_game.state.players if player.role.value == "Guard")

    room_response = client.post(
        f"/api/rooms?name=HumanRoom&seed=7&player_count=7&agent_type=llm&human_seat={human_seat}"
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


def test_human_wolf_team_vote_uses_target_action() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=HumanWolf&seed=1&player_count=7&agent_type=llm&human_seat=5")
    assert room_response.status_code == 200
    room = room_response.json()

    start_response = client.post(f"/api/rooms/{room['id']}/start")
    assert start_response.status_code == 200
    pending_state = start_response.json()
    pending = pending_state["pending_input"]
    assert pending is not None
    assert pending["seat"] == 5
    assert pending["request"] == "WOLF_TEAM_VOTE"
    assert pending["action_type"] == "night_action"

    target_id = pending["options"][0]["id"]
    action_response = client.post(
        f"/api/rooms/{room['id']}/action",
        json={"target_id": target_id, "reasoning": "wolf target proposal"},
    )
    assert action_response.status_code == 200
    assert action_response.json()["id"] == pending_state["id"]


def test_room_pause_resume_control_api() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=PauseRoom&seed=23&player_count=7&agent_type=llm")
    assert room_response.status_code == 200
    room = room_response.json()
    game = _build_game(seed=23, agent_type="llm", player_count=7)
    _rooms.set_active_game(room["id"], game)

    pause_response = client.post(f"/api/rooms/{room['id']}/pause")
    assert pause_response.status_code == 200
    assert pause_response.json()["paused"] is True

    status_response = client.get(f"/api/rooms/{room['id']}/control-status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["paused"] is True
    assert status["running"] is True

    resume_response = client.post(f"/api/rooms/{room['id']}/resume")
    assert resume_response.status_code == 200
    assert resume_response.json()["paused"] is False


def test_runtime_metrics_and_aggregate_endpoints() -> None:
    """Track B/C dashboard contracts: per-game runtime + cross-game aggregate."""
    client = TestClient(app)
    create = client.post("/api/games?seed=11&agent_type=llm")
    assert create.status_code == 200
    game_id = create.json()["id"]

    runtime = client.get(f"/api/games/{game_id}/runtime_metrics")
    assert runtime.status_code == 200
    body = runtime.json()
    assert body["game_id"] == game_id
    assert body["status"] == "finished"
    # Stable contract: local fake LLM still exposes the same runtime fields.
    for key in (
        "decision_count",
        "valid_decision_count",
        "invalid_decision_count",
        "validity_rate",
        "llm_call_count",
        "latency_ms",
        "tokens",
        "speech",
        "by_role",
        "by_player",
    ):
        assert key in body, key
    for stat_key in ("count", "min", "max", "avg", "p50", "p95", "sum"):
        assert stat_key in body["latency_ms"]
        assert stat_key in body["speech"]["char_len"]
    for token_key in ("prompt_sum", "completion_sum", "total_sum"):
        assert token_key in body["tokens"]

    aggregate = client.get("/api/metrics/aggregate?limit_games=20")
    assert aggregate.status_code == 200
    payload = aggregate.json()
    for section in ("games", "runtime", "win_rate_by_role", "win_rate_by_agent_type", "track_b", "track_c"):
        assert section in payload, section
    games = payload["games"]
    for key in ("total", "finished_total", "sampled", "winners", "avg_duration_s", "avg_day_count"):
        assert key in games, key
    assert isinstance(games["winners"], dict)
    runtime_block = payload["runtime"]
    for key in (
        "decision_count",
        "llm_call_count",
        "fallback_count",
        "fallback_ratio",
        "retrieval_used_count",
        "retrieval_used_rate",
        "latency_ms",
        "tokens",
        "speech_char_len",
    ):
        assert key in runtime_block, key
    assert "by_status" in payload["track_b"]
    assert "tournaments_total" in payload["track_c"]


def test_runtime_metrics_404_for_unknown_game() -> None:
    client = TestClient(app)
    resp = client.get("/api/games/does-not-exist/runtime_metrics")
    assert resp.status_code == 404


def test_replay_json_download_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_replay(game_id: str, show_private: bool = False):
        assert game_id == "game-1"
        return {
            "game_id": game_id,
            "show_private": show_private,
            "events": [{"type": "GAME_START"}],
            "decisions": [],
        }

    monkeypatch.setattr("backend.db.persist.get_replay", fake_get_replay)
    client = TestClient(app)

    response = client.get("/api/replay/game-1.json?show_private=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"] == 'attachment; filename="replay-game-1.json"'
    assert response.json()["show_private"] is True
    assert response.json()["events"][0]["type"] == "GAME_START"


def test_replay_json_inline_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.db.persist.get_replay", lambda game_id, show_private=False: {"game_id": game_id})
    client = TestClient(app)

    response = client.get("/api/replay/game-2.json?download=false")

    assert response.status_code == 200
    assert "content-disposition" not in response.headers
    assert response.json() == {"game_id": "game-2"}


def test_replay_json_exports_full_game_process() -> None:
    client = TestClient(app)
    create = client.post("/api/games?seed=41&agent_type=llm&player_count=7")
    assert create.status_code == 200
    game_id = create.json()["id"]

    response = client.get(f"/api/replay/{game_id}.json?download=false&show_private=true")

    assert response.status_code == 200
    replay = response.json()
    assert replay["id"] == game_id
    assert replay["events"]
    assert replay["timeline"]
    assert replay["phase_transitions"]
    assert replay["decisions"]
    assert replay["snapshots"]
    assert replay["votes"]
    assert replay["snapshot"]["phase"] == "GAME_END"
    assert all({"seq", "day", "phase", "type", "content"}.issubset(item) for item in replay["timeline"])
    assert {row["to_phase"] for row in replay["phase_transitions"]} >= {"NIGHT_START", "DAY_START", "GAME_END"}


def test_heuristic_agent_type_is_rejected_for_games() -> None:
    client = TestClient(app)
    resp = client.post("/api/games?seed=7&agent_type=heuristic")
    assert resp.status_code == 400
    assert "heuristic agents are disabled" in resp.json()["detail"]
