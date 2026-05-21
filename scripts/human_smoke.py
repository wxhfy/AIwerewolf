"""Smoke test for human-player mixed game flow.

Spins through a full game where seat 3 is a human, auto-driving the human's
actions via the /api/rooms/{id}/action endpoint until the game ends.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request


CONTROL_RE = re.compile(r"[\x00-\x1f]")
BASE = "http://127.0.0.1:8765"


def post(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(CONTROL_RE.sub(" ", raw))


def build_action(pending: dict) -> dict:
    request = pending["request"]
    options = pending.get("options") or []
    first_target = options[0]["id"] if options else None
    if request in {"TALK", "BADGE_SPEECH", "LAST_WORDS"}:
        return {"speech": "我观察大家的发言节奏，先不轻易站队。", "reasoning": "human play"}
    if request in {"VOTE", "BADGE_ELECTION"}:
        return {"target_id": first_target, "reasoning": "投他试试"}
    if request == "WITCH":
        # decline both for simplicity
        return {"save": False, "target_id": None}
    if request in {"ATTACK", "DIVINE", "GUARD", "SHOOT"}:
        return {"target_id": first_target}
    return {"target_id": first_target}


def drive(room_id: str, max_steps: int = 60) -> dict:
    state = post(f"/api/rooms/{room_id}/start")
    steps = 0
    while True:
        if state.get("winner"):
            print(f"[end] winner={state['winner']} day={state['day']} phase={state['phase']}")
            return state
        pending = state.get("pending_input")
        if pending is None:
            print(f"[stall] no pending, phase={state.get('phase')}")
            return state
        steps += 1
        if steps > max_steps:
            print("[max-steps] exit")
            return state
        action = build_action(pending)
        print(f"[step {steps}] phase={state['phase']} request={pending['request']} player={pending['player_name']}")
        state = post(f"/api/rooms/{room_id}/action", action)


def main() -> int:
    room = post("/api/rooms?name=HumanSmoke&seed=11&player_count=7&agent_type=heuristic&human_seat=3")
    print("Room:", room["id"])
    state = drive(room["id"])
    print(json.dumps({
        "winner": state.get("winner"),
        "day": state.get("day"),
        "phase": state.get("phase"),
        "alive_count": state.get("alive_count"),
        "event_count": state.get("event_count"),
    }, ensure_ascii=False))
    return 0 if state.get("winner") else 1


if __name__ == "__main__":
    sys.exit(main())
