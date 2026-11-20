from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.engine.game import WerewolfGame
from backend.engine.models import Alignment
from backend.engine.models import Phase


def test_anonymous_show_private_in_disabled_mode_requires_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a) anonymous show_private=true -> 403 in disabled mode without opt-in."""
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("AW_DEV_ALLOW_PRIVATE", "0")
    client = TestClient(app)

    room = client.post("/api/rooms?name=Slice1RoomA&seed=1&player_count=7&agent_type=llm").json()
    room_id = room["id"]
    prep_res = client.post(f"/api/rooms/{room_id}/prepare")
    assert prep_res.status_code == 200

    # Plain GET snapshot is public (not 403)
    public_res = client.get(f"/api/rooms/{room_id}/snapshot")
    assert public_res.status_code == 200

    # show_private=true without opt-in returns 403
    private_res = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true")
    assert private_res.status_code == 403
    assert private_res.json()["code"] == "moderator_required"

    # With opt-in AW_DEV_ALLOW_PRIVATE="1" -> not 403
    monkeypatch.setenv("AW_DEV_ALLOW_PRIVATE", "1")
    opt_in_res = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true")
    assert opt_in_res.status_code == 200


def test_static_token_moderator_and_non_moderator(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b) static_token non-moderator token -> 403, moderator token -> not 403."""
    monkeypatch.setenv("AUTH_MODE", "static_token")
    monkeypatch.setenv(
        "AUTH_TOKENS",
        "viewer-tok|viewer|viewer,mod-tok|mod|viewer;moderator,admin-tok|adm|admin",
    )
    client = TestClient(app)

    # In static_token mode, /api/ requires auth (bearer token)
    res_no_auth = client.get("/api/rooms")
    assert res_no_auth.status_code == 401

    viewer_headers = {"Authorization": "Bearer viewer-tok"}
    mod_headers = {"Authorization": "Bearer mod-tok"}
    admin_headers = {"Authorization": "Bearer admin-tok"}

    # Viewer token can create and prepare room, and access public rooms
    res_viewer_create = client.post(
        "/api/rooms?name=Slice1RoomB&seed=2&player_count=7&agent_type=llm",
        headers=viewer_headers,
    )
    assert res_viewer_create.status_code == 200
    room_id = res_viewer_create.json()["id"]

    res_viewer_prep = client.post(f"/api/rooms/{room_id}/prepare", headers=viewer_headers)
    assert res_viewer_prep.status_code == 200

    # Public snapshot succeeds for viewer
    res_viewer_public = client.get(f"/api/rooms/{room_id}/snapshot", headers=viewer_headers)
    assert res_viewer_public.status_code == 200

    # Non-moderator token requesting show_private=true -> 403
    res_viewer_private = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true", headers=viewer_headers)
    assert res_viewer_private.status_code == 403
    assert res_viewer_private.json()["code"] == "moderator_required"

    # Moderator token requesting show_private=true -> 200
    res_mod_private = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true", headers=mod_headers)
    assert res_mod_private.status_code == 200

    # Admin token also permitted for private view -> 200
    res_admin_private = client.get(f"/api/rooms/{room_id}/snapshot?show_private=true", headers=admin_headers)
    assert res_admin_private.status_code == 200


def test_game_state_post_game_disclosure() -> None:
    """(c) GameState.public_dict() of an in-progress game has no roles and disclosed False;
    moderator_dict has roles; finished game public_dict has roles and disclosed True.
    """
    game = WerewolfGame(seed=42, player_count=7)

    # In-progress game
    in_progress_public = game.state.public_dict()
    assert in_progress_public["disclosed"] is False
    for player in in_progress_public["players"]:
        assert "role" not in player

    in_progress_moderator = game.state.moderator_dict()
    for player in in_progress_moderator["players"]:
        assert "role" in player

    # Finished game
    game.state.winner = Alignment.WOLF
    game.state.phase = Phase.GAME_END
    finished_public = game.state.public_dict()
    assert finished_public["disclosed"] is True
    for player in finished_public["players"]:
        assert "role" in player
        assert player["role"]

    finished_moderator = game.state.moderator_dict()
    for player in finished_moderator["players"]:
        assert "role" in player
        assert player["role"]


def test_match_stream_moderator_anonymous_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """(d) match stream with moderator=true anonymous -> 403."""
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("AW_DEV_ALLOW_PRIVATE", "0")
    client = TestClient(app)

    # Anonymous request to match stream with moderator=true -> 403
    response = client.get("/api/matches/nonexistent-match/stream?moderator=true")
    assert response.status_code == 403

    # Opt-in AW_DEV_ALLOW_PRIVATE=1 -> not 403 (will 404 on nonexistent match)
    monkeypatch.setenv("AW_DEV_ALLOW_PRIVATE", "1")
    response_opt_in = client.get("/api/matches/nonexistent-match/stream?moderator=true")
    assert response_opt_in.status_code == 404


def test_admin_write_route_without_admin_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """(e) an admin write route without admin -> 403."""
    # Test in static_token mode
    monkeypatch.setenv("AUTH_MODE", "static_token")
    monkeypatch.setenv(
        "AUTH_TOKENS",
        "viewer-tok|viewer|viewer,admin-tok|adm|admin",
    )
    client = TestClient(app)

    # POST /api/personas with viewer token (non-admin) -> 403
    res_viewer = client.post(
        "/api/personas",
        json={"name": "test_persona_viewer", "style_label": "cautious"},
        headers={"Authorization": "Bearer viewer-tok"},
    )
    assert res_viewer.status_code == 403

    # POST /api/personas with admin token -> not 403
    res_admin = client.post(
        "/api/personas",
        json={"name": "test_persona_admin", "style_label": "aggressive"},
        headers={"Authorization": "Bearer admin-tok"},
    )
    assert res_admin.status_code != 403

    # In disabled mode without opt-in -> 403
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("AW_DEV_ALLOW_PRIVATE", "0")
    res_disabled = client.post(
        "/api/personas",
        json={"name": "test_persona_disabled", "style_label": "cautious"},
    )
    assert res_disabled.status_code == 403
