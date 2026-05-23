from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=15) as response:
        return int(response.status), response.read().decode("utf-8")


def http_post(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.status), response.read().decode("utf-8")


def wait_for_server(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            status, body = http_get(url)
            if status == 200 and "ok" in body:
                return
        except Exception as exc:  # pragma: no cover - integration polling
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Server did not become healthy in time: {last_error}")


def assert_match_payload(data: dict) -> None:
    assert data["winner"] in {"village", "wolf"}
    assert data["phase"] == "GAME_END"
    assert len(data["players"]) == 7
    assert sum(1 for player in data["players"] if player["alive"]) >= 1
    assert any(event["type"] == "CHAT_MESSAGE" for event in data["events"])
    assert any(event["type"] == "VOTE_CAST" for event in data["events"])
    assert any(event["type"] == "GAME_END" for event in data["events"])
    assert data["daily_summaries"]
    assert data["daily_summary_facts"]


def main() -> int:
    port = free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_for_server(f"http://127.0.0.1:{port}/api/health")

        status, root_body = http_get(f"http://127.0.0.1:{port}/")
        assert status == 200
        root_payload = json.loads(root_body)
        assert root_payload["message"] == "AI Werewolf backend is running."
        assert root_payload["ui"].startswith("http://localhost:")
        assert root_payload["docs"] == "/docs"

        status, room_body = http_post(
            f"http://127.0.0.1:{port}/api/rooms?name=SmokeRoom&seed=5&player_count=7&agent_type=heuristic"
        )
        assert status == 200
        room = json.loads(room_body)
        assert room["name"] == "SmokeRoom"
        assert room["agent_type"] == "heuristic"
        room_id = room["id"]

        status, fetched_room = http_get(f"http://127.0.0.1:{port}/api/rooms/{room_id}")
        assert status == 200
        assert json.loads(fetched_room)["id"] == room_id

        status, room_game_body = http_post(f"http://127.0.0.1:{port}/api/rooms/{room_id}/games")
        assert status == 200
        room_game_payload = json.loads(room_game_body)
        assert_match_payload(room_game_payload)

        status, room_games_body = http_get(f"http://127.0.0.1:{port}/api/rooms/{room_id}/games")
        assert status == 200
        room_games = json.loads(room_games_body)
        assert len(room_games) == 1
        assert room_games[0]["id"] == room_game_payload["id"]

        status, room_snapshot_body = http_get(f"http://127.0.0.1:{port}/api/rooms/{room_id}/snapshot")
        assert status == 200
        room_snapshot = json.loads(room_snapshot_body)
        assert room_snapshot["id"] == room_game_payload["id"]

        for seed in (3, 7, 11):
            status, body = http_post(f"http://127.0.0.1:{port}/api/games?seed={seed}&agent_type=heuristic")
            assert status == 200
            payload = json.loads(body)
            assert_match_payload(payload)

            game_id = payload["id"]
            status, game_body = http_get(f"http://127.0.0.1:{port}/api/games/{game_id}")
            assert status == 200
            loaded = json.loads(game_body)
            assert loaded["id"] == game_id
            assert_match_payload(loaded)

        status, listed_body = http_get(f"http://127.0.0.1:{port}/api/games")
        assert status == 200
        games = json.loads(listed_body)
        assert len(games) >= 3
        print("E2E smoke passed")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
