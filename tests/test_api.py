import pytest
from fastapi.testclient import TestClient

from backend.app import _rooms
from backend.app import app
from backend.application.analysis.service import PostGameAnalysisService
from backend.application.matches.executor import MatchExecutor
from backend.application.matches.repository import MatchJobRepository
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import DecisionEvaluation
from backend.db.models import MatchJob
from backend.db.models import OutboxEvent


def _run_room_match(client: TestClient, room_id: str) -> dict:
    prepared = client.post(f"/api/rooms/{room_id}/prepare?show_private=true")
    assert prepared.status_code == 200
    started = client.post(f"/api/rooms/{room_id}/start?show_private=true")
    assert started.status_code == 200
    match_id = started.json()["match_id"]
    repository = MatchJobRepository()
    worker_id = f"test-worker-{match_id}"
    job = repository.claim_game(match_id, worker_id)
    assert job is not None
    MatchExecutor(repository, worker_id=worker_id).execute(job)
    response = client.get(f"/api/games/{match_id}?show_private=true")
    assert response.status_code == 200
    return response.json()


def _run_ai_match(client: TestClient, *, seed: int, player_count: int = 7) -> dict:
    room = client.post(f"/api/rooms?name=WorkerTest&seed={seed}&player_count={player_count}&agent_type=llm")
    assert room.status_code == 200
    return _run_room_match(client, room.json()["id"])


def test_create_game_api() -> None:
    client = TestClient(app)
    data = _run_ai_match(client, seed=7, player_count=10)
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


def test_post_game_analysis_is_async_persisted_and_idempotent() -> None:
    client = TestClient(app)
    data = _run_ai_match(client, seed=71, player_count=7)

    queued = client.get(f"/api/v1/matches/{data['id']}/analysis")
    assert queued.status_code == 200
    assert queued.json()["job"]["status"] == "pending"

    completed = PostGameAnalysisService().execute(data["id"])
    assert completed is not None
    assert completed["status"] == "completed"

    analysis = client.get(f"/api/v1/matches/{data['id']}/analysis")
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["decision_count"] > 0
    assert payload["evaluated_decision_count"] == payload["decision_count"]
    assert payload["evaluation_coverage"] == 1.0

    evaluations = client.get(f"/api/v1/matches/{data['id']}/decision-evaluations")
    assert evaluations.status_code == 200
    assert len(evaluations.json()) == payload["decision_count"]

    assert PostGameAnalysisService().execute(data["id"]) is None
    with SessionLocal() as db:
        count = db.query(DecisionEvaluation).filter(DecisionEvaluation.game_id == data["id"]).count()
    assert count == payload["decision_count"]

    retry = client.post(f"/api/v1/matches/{data['id']}/analysis/retry")
    assert retry.status_code == 202
    assert retry.json()["status"] == "pending"
    assert client.get("/api/v1/strategies").status_code == 200


def test_create_game_with_wolfcha_10p_pack() -> None:
    client = TestClient(app)
    data = _run_ai_match(client, seed=13, player_count=10)
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


def test_platform_health_capabilities_and_security_headers() -> None:
    init_db()
    client = TestClient(app)

    live = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request-id"})
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert live.headers["x-request-id"] == "test-request-id"
    assert float(live.headers["x-process-time-ms"]) >= 0
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["x-frame-options"] == "DENY"

    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["checks"]["database"] == "ok"

    capabilities = client.get("/api/v1/system/capabilities")
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["transport"] == {"commands": "rest", "updates": "sse", "websocket": False}
    assert payload["persistence"]["match_commands"] is True
    assert payload["persistence"]["agent_decision_jobs"] is True
    assert payload["execution"]["analysis_worker"] is True
    assert payload["persistence"]["decision_evaluations"] is True
    assert payload["persistence"]["post_game_analysis_jobs"] is True
    assert payload["persistence"]["strategy_knowledge"] is True
    assert payload["persistence"]["outbox"] is True


def test_remote_agent_contract_is_explicit_but_not_enabled() -> None:
    client = TestClient(app)
    capabilities = client.get("/api/v1/agent/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["remote_execution_ready"] is False

    response = client.post(
        "/api/v1/agent/decisions",
        json={
            "request_id": "request-12345678",
            "match_id": "match-placeholder",
            "player_id": "player-1",
            "action_type": "vote",
            "observation": {},
            "legal_actions": [],
        },
    )
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "remote_agent_service_not_enabled"
    assert response.json()["request_id"]


def test_match_command_is_idempotent_and_emits_outbox_event() -> None:
    client = TestClient(app)
    room = client.post("/api/rooms?name=CommandRoom&seed=61&player_count=7&agent_type=llm").json()
    prepared = client.post(f"/api/rooms/{room['id']}/prepare")
    assert prepared.status_code == 200
    match_id = prepared.json()["id"]
    command = {
        "command_id": f"pause-{match_id}",
        "type": "pause",
        "expected_seq": prepared.json()["seq"],
        "payload": {},
    }

    first = client.post(f"/api/v1/matches/{match_id}/commands", json=command)
    duplicate = client.post(f"/api/v1/matches/{match_id}/commands", json=command)
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert first.json()["status"] == "completed"
    assert first.json()["result"]["control_state"] == "paused"

    with SessionLocal() as db:
        events = db.query(OutboxEvent).filter(OutboxEvent.aggregate_id == match_id).all()
    assert len(events) == 1
    assert events[0].event_type == "match.command.pause.completed"


def test_match_command_rejects_stale_snapshot_sequence() -> None:
    client = TestClient(app)
    room = client.post("/api/rooms?name=ConflictRoom&seed=67&player_count=7&agent_type=llm").json()
    prepared = client.post(f"/api/rooms/{room['id']}/prepare").json()
    response = client.post(
        f"/api/v1/matches/{prepared['id']}/commands",
        json={"command_id": f"pause-stale-{prepared['id']}", "type": "pause", "expected_seq": 999999},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "http_409"


def test_openapi_exposes_sse_without_legacy_websocket_routes() -> None:
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]

    assert any(path.endswith("/stream") for path in paths)
    assert all(not path.startswith("/ws") for path in paths)


def test_match_events_are_ordered_and_resumable() -> None:
    client = TestClient(app)
    match_id = _run_ai_match(client, seed=701)["id"]

    response = client.get(f"/api/matches/{match_id}/events?limit=1000")
    assert response.status_code == 200
    events = response.json()["events"]
    assert events
    sequences = [event["seq"] for event in events]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))

    cursor = sequences[len(sequences) // 2]
    resumed = client.get(f"/api/matches/{match_id}/events?after_seq={cursor}&limit=1000")
    assert resumed.status_code == 200
    assert all(event["seq"] > cursor for event in resumed.json()["events"])


def test_leaderboard_api_returns_cross_game_views() -> None:
    client = TestClient(app)
    _run_ai_match(client, seed=31)
    _run_ai_match(client, seed=37)

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

    game = _run_room_match(client, room["id"])
    assert game["winner"] in {"village", "wolf"}
    assert game["phase"] == "GAME_END"
    assert "holder_id" in game["badge"]
    assert game["events"]

    history_response = client.get(f"/api/rooms/{room['id']}/games")
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["match_id"] == game["id"]

    snapshot_response = client.get(f"/api/rooms/{room['id']}/snapshot")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["id"] == game["id"]
    assert snapshot["winner"] in {"village", "wolf"}


def test_room_create_accepts_json_llm_config_without_echoing_secret() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/rooms",
        json={
            "name": "JsonLlmRoom",
            "seed": 17,
            "player_count": 7,
            "agent_type": "llm",
            "human_seat": None,
            "llm_config": {
                "provider": "anthropic",
                "model": "deepseek-v4-flash",
                "api_key": "example-room-credential",
                "base_url": "https://api.deepseek.com/anthropic/",
            },
        },
    )

    assert response.status_code == 200
    room = response.json()
    assert room["name"] == "JsonLlmRoom"
    assert room["seed"] == 17
    assert room["player_count"] == 7
    assert room["llm_configured"] is True
    assert room["llm_provider"] == "anthropic"
    assert room["llm_model"] == "deepseek-v4-flash"
    assert room["llm_base_url"] == "https://api.deepseek.com/anthropic"
    assert "example-room-credential" not in response.text

    stored_room = _rooms.get_room(room["id"])
    assert stored_room.llm_config is not None
    assert "api_key" not in stored_room.llm_config
    assert stored_room.llm_config["base_url"] == "https://api.deepseek.com/anthropic"

    get_response = client.get(f"/api/rooms/{room['id']}")
    assert get_response.status_code == 200
    assert "example-room-credential" not in get_response.text


def test_match_job_uses_sanitized_room_llm_config() -> None:
    client = TestClient(app)
    room_response = client.post(
        "/api/rooms",
        json={
            "name": "RoomConfigPropagation",
            "seed": 29,
            "player_count": 7,
            "agent_type": "llm",
            "llm_config": {
                "provider": "anthropic",
                "model": "deepseek-v4-flash",
                "api_key": "example-room-credential",
                "base_url": "https://api.deepseek.com/anthropic/",
            },
        },
    )
    assert room_response.status_code == 200
    room = room_response.json()
    assert client.post(f"/api/rooms/{room['id']}/prepare").status_code == 200
    started = client.post(f"/api/rooms/{room['id']}/start")
    assert started.status_code == 200

    with SessionLocal() as db:
        job = db.query(MatchJob).filter(MatchJob.game_id == started.json()["match_id"]).one()
        config = dict(job.payload["llm_config"])
        serialized = str(job.payload)

    assert config == {
        "provider": "anthropic",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/anthropic",
    }
    assert "example-room-credential" not in serialized


def test_human_room_creation_is_explicitly_disabled() -> None:
    client = TestClient(app)
    response = client.post("/api/rooms?name=HumanRoom&seed=7&player_count=7&agent_type=llm&human_seat=1")
    assert response.status_code == 501
    assert "temporarily disabled" in response.json()["detail"]


def test_human_action_endpoint_is_explicitly_disabled() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=AiOnly&seed=1&player_count=7&agent_type=llm")
    assert room_response.status_code == 200
    room = room_response.json()
    action_response = client.post(
        f"/api/rooms/{room['id']}/action",
        json={"target_id": "P1", "reasoning": "not enabled"},
    )
    assert action_response.status_code == 501


def test_room_pause_resume_control_api() -> None:
    client = TestClient(app)
    room_response = client.post("/api/rooms?name=PauseRoom&seed=23&player_count=7&agent_type=llm")
    assert room_response.status_code == 200
    room = room_response.json()
    assert client.post(f"/api/rooms/{room['id']}/prepare").status_code == 200
    assert client.post(f"/api/rooms/{room['id']}/start").status_code == 200

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


def test_prepared_match_can_start_after_api_memory_is_lost() -> None:
    client = TestClient(app)
    room = client.post("/api/rooms?name=RestartRoom&seed=53&player_count=7&agent_type=llm").json()
    prepared = client.post(f"/api/rooms/{room['id']}/prepare?show_private=true")
    assert prepared.status_code == 200
    match_id = prepared.json()["id"]

    _rooms.active_games.clear()

    restored_room = client.get(f"/api/rooms/{room['id']}")
    assert restored_room.status_code == 200
    assert restored_room.json()["current_game_id"] == match_id
    started = client.post(f"/api/rooms/{room['id']}/start")
    assert started.status_code == 200
    assert started.json()["match_id"] == match_id
    assert started.json()["status"] == "queued"


def test_runtime_metrics_and_aggregate_endpoints() -> None:
    """Track B/C dashboard contracts: per-game runtime + cross-game aggregate."""
    client = TestClient(app)
    game_id = _run_ai_match(client, seed=11)["id"]

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
    game_id = _run_ai_match(client, seed=41)["id"]

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
    resp = client.post("/api/rooms?seed=7&agent_type=heuristic")
    assert resp.status_code == 400
    assert "Only LLM-backed" in resp.json()["detail"]
