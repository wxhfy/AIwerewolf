"""Structured observation of the game state.

Single Responsibility: extract what the agent can legitimately see
from the raw PlayerView. No judgments, no analysis — pure fact extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PlayerInfo:
    """Public information about a single player."""
    id: str
    name: str
    seat: int
    alive: bool
    role: str = "unknown"


@dataclass
class SpeechInfo:
    """A speech made in the current round."""
    player_id: str
    player_name: str
    seat: int
    content: str


@dataclass
class VoteInfo:
    """A vote cast in a round."""
    voter_id: str
    voter_name: str
    target_id: str
    target_name: str


@dataclass
class DeathInfo:
    """A player death."""
    player_id: str
    player_name: str
    seat: int
    cause: str  # "wolf", "vote", "witch", "hunter"


@dataclass
class Observation:
    """Structured extraction of what the agent can see.

    This is the ONLY output of the observation layer.
    Everything downstream (think, act) consumes this — not raw view.
    """

    # Identity
    player_id: str
    player_name: str
    player_seat: int
    player_role: str

    # Game state
    day: int
    phase: str

    # Players
    alive: List[PlayerInfo] = field(default_factory=list)
    dead: List[PlayerInfo] = field(default_factory=list)

    # Current round
    speeches: List[SpeechInfo] = field(default_factory=list)
    votes: List[VoteInfo] = field(default_factory=list)

    # History
    deaths: List[DeathInfo] = field(default_factory=list)

    # Private info (role-specific)
    private: Dict[str, Any] = field(default_factory=dict)

    # Social signals
    mentioned_by: List[str] = field(default_factory=list)
    adjacent_dead: List[str] = field(default_factory=list)


def observe(view: Any, role: str) -> Observation:
    """Build an Observation from a PlayerView.

    This is the ONLY public function in this module.
    Pure extraction — no logic, no judgments.
    """
    obs = Observation(
        player_id=view.self_player["id"],
        player_name=view.self_player.get("name", ""),
        player_seat=view.self_player.get("seat", 0),
        player_role=role,
        day=view.day,
        phase=view.phase,
    )

    # Players
    for p in view.players:
        info = PlayerInfo(
            id=p["id"],
            name=p.get("name", ""),
            seat=p.get("seat", 0),
            alive=p["alive"],
            role=p.get("role", "unknown"),
        )
        (obs.alive if p["alive"] else obs.dead).append(info)

    # Today's speeches
    for e in view.public_events:
        if e.get("type") == "CHAT_MESSAGE" and e.get("day") == view.day:
            payload = e.get("payload", {}) or {}
            actor = _find_player(view, e.get("actor_id", ""))
            obs.speeches.append(SpeechInfo(
                player_id=e.get("actor_id", ""),
                player_name=actor.get("name", ""),
                seat=actor.get("seat", 0),
                content=payload.get("speech", ""),
            ))

        elif e.get("type") == "VOTE_CAST" and e.get("day") == view.day:
            payload = e.get("payload", {}) or {}
            voter = _find_player(view, e.get("actor_id", ""))
            target = _find_player(view, payload.get("target_id", ""))
            obs.votes.append(VoteInfo(
                voter_id=e.get("actor_id", ""),
                voter_name=voter.get("name", ""),
                target_id=payload.get("target_id", ""),
                target_name=target.get("name", ""),
            ))

        elif e.get("type") == "PLAYER_DIED":
            payload = e.get("payload", {}) or {}
            dead = _find_player(view, payload.get("player_id", ""))
            obs.deaths.append(DeathInfo(
                player_id=payload.get("player_id", ""),
                player_name=dead.get("name", ""),
                seat=dead.get("seat", 0),
                cause=payload.get("cause", "unknown"),
            ))

    # Private info
    for e in view.private_events:
        payload = e.get("payload", {}) or {}
        if "check_result" in payload:
            obs.private["seer_check"] = payload
        if "victim_id" in payload:
            obs.private["witch_victim"] = payload

    # Social signals
    my_seat = f"@{obs.player_seat}号"
    for s in obs.speeches:
        if my_seat in s.content:
            obs.mentioned_by.append(s.player_name)

    total_seats = len(view.players)
    for d in obs.dead:
        diff = abs(d.seat - obs.player_seat)
        if diff == 1 or diff == total_seats - 1:
            obs.adjacent_dead.append(d.name)

    return obs


def format_observation(obs: Observation) -> str:
    """Format Observation into text for LLM consumption."""
    lines = [
        "=== 当前状态 ===",
        f"你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}",
        f"第{obs.day}天 / {obs.phase}阶段",
        "",
        f"存活：{'，'.join(f'{p.seat}号:{p.name}' for p in obs.alive)}",
        f"死亡：{'，'.join(f'{p.seat}号:{p.name}' for p in obs.dead) or '无'}",
    ]

    if obs.speeches:
        lines.append("\n=== 今日发言 ===")
        for s in obs.speeches[-8:]:
            lines.append(f"  {s.seat}号:{s.player_name}：{s.content[:200]}")

    if obs.votes:
        lines.append("\n=== 今日投票 ===")
        for v in obs.votes:
            lines.append(f"  {v.voter_name} -> {v.target_name}")

    if obs.deaths:
        lines.append("\n=== 死亡记录 ===")
        for d in obs.deaths:
            lines.append(f"  第{d.seat}号:{d.player_name}（{d.cause}）")

    if obs.mentioned_by:
        lines.append(f"\n你被 {', '.join(obs.mentioned_by)} 点名提到")

    if obs.adjacent_dead:
        lines.append(f"你和 {', '.join(obs.adjacent_dead)} 座位相邻")

    if obs.private:
        lines.append("\n=== 私有信息 ===")
        for k, v in obs.private.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def _find_player(view: Any, player_id: str) -> dict:
    """Find player dict by id."""
    for p in view.players:
        if p["id"] == player_id:
            return p
    return {"id": player_id, "name": player_id, "seat": 0, "alive": False}
