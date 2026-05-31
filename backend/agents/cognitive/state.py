"""Game state observation utilities for the cognitive agent.

Extracts structured observations from raw game events — what the agent can
legitimately see, hear, and infer from public + private information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerInfo:
    """Public information about a player."""
    player_id: str
    name: str
    seat: int
    role: str  # only known if revealed or self
    alive: bool
    is_sheriff: bool = False
    vote_target: str | None = None
    mentioned_by: list[str] = field(default_factory=list)
    suspicion_score: float = 0.0  # 0-1, how suspicious others find this player


@dataclass
class SpeechRecord:
    """A single speech in the current round."""
    player_id: str
    player_name: str
    seat: int
    content: str
    phase: str
    day: int


@dataclass
class VoteRecord:
    """A vote cast in a round."""
    voter_id: str
    voter_name: str
    target_id: str
    target_name: str
    day: int


@dataclass
class DeathRecord:
    """A player death."""
    player_id: str
    player_name: str
    seat: int
    cause: str  # 'wolf', 'vote', 'witch', 'hunter'
    day: int


@dataclass
class GameObservation:
    """Structured observation of the current game state.

    This is what the agent can legitimately know — no hidden information
    unless it belongs to this agent's role.
    """
    # Basic state
    day: int
    phase: str
    player_id: str
    player_name: str
    player_seat: int
    player_role: str

    # Players
    alive_players: list[PlayerInfo] = field(default_factory=list)
    dead_players: list[PlayerInfo] = field(default_factory=list)
    sheriff_id: str | None = None

    # Current round
    today_speeches: list[SpeechRecord] = field(default_factory=list)
    today_votes: list[VoteRecord] = field(default_factory=list)

    # History
    yesterday_votes: list[VoteRecord] = field(default_factory=list)
    deaths: list[DeathRecord] = field(default_factory=list)

    # Private info (only for this agent)
    private_info: dict[str, Any] = field(default_factory=dict)

    # Context
    speak_order_hint: str = ""
    mentioned_by: list[str] = field(default_factory=list)
    adjacent_dead: list[str] = field(default_factory=list)


def build_observation(view: Any, player_role: str) -> GameObservation:
    """Build a structured observation from the raw PlayerView.

    Args:
        view: The PlayerView object from the game engine
        player_role: The role string of this agent

    Returns:
        GameObservation with all extractable information
    """
    obs = GameObservation(
        day=view.day,
        phase=view.phase,
        player_id=view.self_player["id"],
        player_name=view.self_player["name"],
        player_seat=view.self_player["seat"],
        player_role=player_role,
    )

    # Build player lists
    for p in view.players:
        info = PlayerInfo(
            player_id=p["id"],
            name=p["name"],
            seat=p["seat"],
            role=p.get("role", "unknown"),
            alive=p["alive"],
        )
        if p["alive"]:
            obs.alive_players.append(info)
        else:
            obs.dead_players.append(info)

    # Extract today's speeches
    for event in view.public_events:
        etype = event.get("type", "")
        payload = event.get("payload", {}) or {}
        actor_id = event.get("actor_id", "")

        if etype == "CHAT_MESSAGE" and event.get("day") == view.day:
            actor_info = _find_player(view, actor_id)
            obs.today_speeches.append(SpeechRecord(
                player_id=actor_id,
                player_name=actor_info.get("name", actor_id),
                seat=actor_info.get("seat", 0),
                content=payload.get("speech", ""),
                phase=event.get("phase", ""),
                day=view.day,
            ))

        elif etype == "VOTE_CAST" and event.get("day") == view.day:
            voter_info = _find_player(view, actor_id)
            target_info = _find_player(view, payload.get("target_id", ""))
            obs.today_votes.append(VoteRecord(
                voter_id=actor_id,
                voter_name=voter_info.get("name", actor_id),
                target_id=payload.get("target_id", ""),
                target_name=target_info.get("name", payload.get("target_id", "")),
                day=view.day,
            ))

        elif etype == "PLAYER_DIED":
            dead_info = _find_player(view, payload.get("player_id", ""))
            obs.deaths.append(DeathRecord(
                player_id=payload.get("player_id", ""),
                player_name=dead_info.get("name", ""),
                seat=dead_info.get("seat", 0),
                cause=payload.get("cause", "unknown"),
                day=event.get("day", 0),
            ))

    # Extract private info
    for event in view.private_events:
        payload = event.get("payload", {}) or {}
        if "check_result" in payload:
            obs.private_info["seer_check"] = payload
        if "victim_id" in payload:
            obs.private_info["witch_victim"] = payload
        if "guard_target" in payload:
            obs.private_info["guard_target"] = payload

    # Build mention list
    my_seat_str = f"@{obs.player_seat}号"
    for speech in obs.today_speeches:
        if my_seat_str in speech.content or str(obs.player_seat) in speech.content:
            obs.mentioned_by.append(speech.player_name)

    # Adjacent dead
    total_seats = len(view.players)
    for dead in obs.dead_players:
        diff = abs(dead.seat - obs.player_seat)
        if diff == 1 or diff == total_seats - 1:
            obs.adjacent_dead.append(dead.name)

    return obs


def _find_player(view: Any, player_id: str) -> dict[str, Any]:
    """Find a player dict by id from the view."""
    for p in view.players:
        if p["id"] == player_id:
            return p
    return {"id": player_id, "name": player_id, "seat": 0, "alive": False}


def format_observation_text(obs: GameObservation) -> str:
    """Format the observation into a structured text for LLM consumption."""
    lines = [
        f"=== 当前状态 ===",
        f"你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}",
        f"第{obs.day}天 / {obs.phase}阶段",
        "",
    ]

    # Alive players
    alive_str = "，".join(f"{p.seat}号:{p.name}" for p in obs.alive_players)
    dead_str = "，".join(f"{p.seat}号:{p.name}" for p in obs.dead_players) if obs.dead_players else "无"
    lines.append(f"存活玩家：{alive_str}")
    lines.append(f"已死亡：{dead_str}")
    lines.append("")

    # Today's speeches
    if obs.today_speeches:
        lines.append("=== 今日发言记录 ===")
        for s in obs.today_speeches:
            lines.append(f"  {s.seat}号:{s.player_name}：{s.content[:200]}")
        lines.append("")

    # Today's votes
    if obs.today_votes:
        lines.append("=== 今日投票记录 ===")
        for v in obs.today_votes:
            lines.append(f"  {v.voter_name} -> {v.target_name}")
        lines.append("")

    # Deaths
    if obs.deaths:
        lines.append("=== 死亡记录 ===")
        for d in obs.deaths:
            lines.append(f"  第{d.day}天：{d.player_name}（{d.seat}号）死因={d.cause}")
        lines.append("")

    # Mentioned
    if obs.mentioned_by:
        lines.append(f"=== 你被以下玩家点名提到 ===")
        for name in obs.mentioned_by:
            lines.append(f"  - {name}")
        lines.append("")

    # Adjacent dead
    if obs.adjacent_dead:
        lines.append(f"=== 你和以下死亡玩家座位相邻 ===")
        for name in obs.adjacent_dead:
            lines.append(f"  - {name}")
        lines.append("")

    # Private info
    if obs.private_info:
        lines.append("=== 你的私有信息 ===")
        for key, val in obs.private_info.items():
            lines.append(f"  {key}: {val}")
        lines.append("")

    return "\n".join(lines)
