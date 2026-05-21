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

        status, html = http_get(f"http://127.0.0.1:{port}/")
        assert status == 200
        assert 'id="run"' in html
        assert 'id="lang-en"' in html

        status, js = http_get(f"http://127.0.0.1:{port}/static/app.js")
        assert status == 200
        assert "const dictionary" in js
        assert "statusLoading" in js

        status, css = http_get(f"http://127.0.0.1:{port}/static/style.css")
        assert status == 200
        assert ".statusbar" in css

        for seed in (3, 7, 11):
            status, body = http_post(f"http://127.0.0.1:{port}/api/games?seed={seed}")
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
