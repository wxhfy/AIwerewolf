"""Structured observation of the game state.

Single Responsibility: extract what the agent can legitimately see
from the raw PlayerView. No judgments, no analysis — pure fact extraction.

Now integrates BeliefTracker: stateful tracking of role claims, contradictions,
and voting patterns across rounds. Mirrors BeliefState from llm_agent.py
but optimized for the cognitive pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

# ============================================================
# Structured observation types
# ============================================================


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
    day: int = 0


@dataclass
class DeathInfo:
    """A player death."""

    player_id: str
    player_name: str
    seat: int
    cause: str  # "wolf", "vote", "witch", "hunter"
    revealed_role: str = ""


@dataclass
class RoleClaim:
    """A role claim extracted from speech or system events."""

    player_name: str
    player_id: str
    seat: int
    claimed_role: str
    day: int
    context: str  # "badge_election", "day_speech", "last_words", "revealed_on_death"


@dataclass
class Contradiction:
    """A detected contradiction (e.g., multiple claims of same unique role)."""

    role: str
    claimants: List[str]  # player names
    description: str


# ============================================================
# BeliefTracker — stateful game-state tracker
# ============================================================


class BeliefTracker:
    """Stateful tracker of game knowledge across rounds.

    Extracts and maintains:
    - Role claims (who claimed what, when)
    - Contradictions (multiple claims of unique roles)
    - Voting patterns (who voted for whom)
    - Death history with roles

    Designed to be lightweight and embeddable in the Observation pipeline.
    """

    def __init__(self):
        self.claims: List[RoleClaim] = []
        self.votes: List[VoteInfo] = []
        self.deaths: List[DeathInfo] = []
        self.contradictions: List[Contradiction] = []
        self._unique_roles = {"预言家", "女巫", "猎人", "守卫", "Seer", "Witch", "Hunter", "Guard"}
        self._processed_speech_ids: set = set()
        self._seen_vote_keys: set = set()
        self._seen_death_keys: set = set()

    def update(self, view: Any) -> None:
        """Update tracker from current PlayerView."""
        self._extract_claims(view)
        self._extract_votes(view)
        self._extract_deaths(view)
        self._detect_contradictions()

    # ---- Extraction ----

    def _extract_claims(self, view: Any) -> None:
        """Extract role claims from speeches and system events."""
        for e in view.public_events:
            etype = e.get("type", "")
            payload = e.get("payload", {}) or {}
            day = e.get("day", 0)
            actor_id = e.get("actor_id", "")
            actor = _find_player(view, actor_id)

            if etype == "CHAT_MESSAGE":
                speech = payload.get("speech", "")
                claimed = _detect_role_claim(speech)
                if claimed and claimed in self._unique_roles:
                    # Avoid duplicates from same speech
                    speech_key = f"{actor_id}:{speech[:50]}"
                    if speech_key in self._processed_speech_ids:
                        continue
                    self._processed_speech_ids.add(speech_key)
                    self.claims.append(
                        RoleClaim(
                            player_name=actor.get("name", actor_id),
                            player_id=actor_id,
                            seat=actor.get("seat", 0),
                            claimed_role=claimed,
                            day=day,
                            context="day_speech",
                        )
                    )

            elif etype == "PLAYER_DIED":
                revealed = payload.get("role", "")
                if revealed:
                    pid = payload.get("player_id", "")
                    dead = _find_player(view, pid)
                    self.claims.append(
                        RoleClaim(
                            player_name=dead.get("name", pid),
                            player_id=pid,
                            seat=dead.get("seat", 0),
                            claimed_role=revealed,
                            day=day,
                            context="revealed_on_death",
                        )
                    )

    def _extract_votes(self, view: Any) -> None:
        """Extract votes from public events.

        Deduplicates: a (voter_id, target_id, day) key prevents the same
        vote from being recorded twice when update() runs on every _observe() call.
        """
        for e in view.public_events:
            if e.get("type") == "VOTE_CAST" and e.get("day") == view.day:
                payload = e.get("payload", {}) or {}
                voter_id = e.get("actor_id", "")
                target_id = payload.get("target_id", "")
                day = e.get("day", view.day)
                vote_key = (voter_id, target_id, day)
                if vote_key in self._seen_vote_keys:
                    continue
                self._seen_vote_keys.add(vote_key)
                voter = _find_player(view, voter_id)
                target = _find_player(view, target_id)
                self.votes.append(
                    VoteInfo(
                        voter_id=voter_id,
                        voter_name=voter.get("name", ""),
                        target_id=target_id,
                        target_name=target.get("name", ""),
                        day=day,
                    )
                )

    def _extract_deaths(self, view: Any) -> None:
        """Extract deaths from public events. Deduplicates by (player_id, cause)."""
        for e in view.public_events:
            if e.get("type") == "PLAYER_DIED":
                payload = e.get("payload", {}) or {}
                pid = payload.get("player_id", "")
                cause = payload.get("cause", payload.get("reason", "unknown"))
                death_key = (pid, cause)
                if death_key in self._seen_death_keys:
                    continue
                self._seen_death_keys.add(death_key)
                dead = _find_player(view, pid)
                self.deaths.append(
                    DeathInfo(
                        player_id=pid,
                        player_name=dead.get("name", pid),
                        seat=dead.get("seat", 0),
                        cause=cause,
                        revealed_role=payload.get("role", ""),
                    )
                )

    # ---- Contradiction detection ----

    def _detect_contradictions(self) -> None:
        """Detect multiple claims of the same unique role."""
        self.contradictions = []
        claims_by_role: Dict[str, List[RoleClaim]] = {}
        for c in self.claims:
            role = c.claimed_role
            if role not in claims_by_role:
                claims_by_role[role] = []
            claims_by_role[role].append(c)

        for role, role_claims in claims_by_role.items():
            if len(role_claims) >= 2:
                names = list(set(c.player_name for c in role_claims))
                if len(names) >= 2:
                    self.contradictions.append(
                        Contradiction(
                            role=role,
                            claimants=names,
                            description=f"多人声称是{role}: {', '.join(names)}",
                        )
                    )

    # ---- Formatting ----

    def format_for_prompt(self) -> str:
        """Format tracker state as prompt text."""
        parts = []

        if self.claims:
            lines = ["=== 角色声称 ==="]
            for c in self.claims[-8:]:
                lines.append(f"  {c.seat}号:{c.player_name} 声称是 {c.claimed_role} (D{c.day}, {c.context})")
            parts.append("\n".join(lines))

        if self.contradictions:
            lines = ["=== 矛盾 ==="]
            for c in self.contradictions:
                lines.append(f"  {c.description}")
            parts.append("\n".join(lines))

        if self.votes:
            latest_day = max(v.day for v in self.votes) if self.votes else 0
            day_votes = [v for v in self.votes if v.day == latest_day]
            if day_votes:
                lines = [f"=== D{latest_day} 投票 ==="]
                for v in day_votes:
                    lines.append(f"  {v.voter_name} -> {v.target_name}")
                parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def clear_round(self) -> None:
        """Clear per-round data (claims/votes persist across rounds)."""
        pass  # Claims/votes accumulate usefully


# ============================================================
# Observation — what the agent sees right now
# ============================================================


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
    legal_targets: List[PlayerInfo] = field(default_factory=list)

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

    # Belief tracker output (new — from BeliefTracker)
    role_claims: List[RoleClaim] = field(default_factory=list)
    contradictions: List[Contradiction] = field(default_factory=list)
    belief_summary: str = ""


def observe(view: Any, role: str, tracker: Optional[BeliefTracker] = None) -> Observation:
    """Build an Observation from a PlayerView.

    Args:
        view: PlayerView from game engine
        role: Agent's role string
        tracker: Optional BeliefTracker for stateful claim/contradiction tracking.
                 If provided, it is updated and its output merged into the Observation.

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

    for p in getattr(view, "legal_targets", []):
        obs.legal_targets.append(
            PlayerInfo(
                id=p["id"],
                name=p.get("name", ""),
                seat=p.get("seat", 0),
                alive=p.get("alive", True),
            )
        )

    # Today's speeches
    for e in view.public_events:
        if e.get("type") == "CHAT_MESSAGE" and e.get("day") == view.day:
            payload = e.get("payload", {}) or {}
            actor = _find_player(view, e.get("actor_id", ""))
            obs.speeches.append(
                SpeechInfo(
                    player_id=e.get("actor_id", ""),
                    player_name=actor.get("name", ""),
                    seat=actor.get("seat", 0),
                    content=payload.get("speech", ""),
                )
            )

        elif e.get("type") == "VOTE_CAST" and e.get("day") == view.day:
            payload = e.get("payload", {}) or {}
            voter = _find_player(view, e.get("actor_id", ""))
            target = _find_player(view, payload.get("target_id", ""))
            obs.votes.append(
                VoteInfo(
                    voter_id=e.get("actor_id", ""),
                    voter_name=voter.get("name", ""),
                    target_id=payload.get("target_id", ""),
                    target_name=target.get("name", ""),
                    day=e.get("day", view.day),
                )
            )

        elif e.get("type") == "PLAYER_DIED":
            payload = e.get("payload", {}) or {}
            dead = _find_player(view, payload.get("player_id", ""))
            obs.deaths.append(
                DeathInfo(
                    player_id=payload.get("player_id", ""),
                    player_name=dead.get("name", ""),
                    seat=dead.get("seat", 0),
                    cause=payload.get("cause", payload.get("reason", "unknown")),
                    revealed_role=payload.get("role", ""),
                )
            )

    # Private info
    for e in view.private_events:
        payload = e.get("payload", {}) or {}
        if payload.get("kind") == "seer_result":
            obs.private["seer_check"] = payload
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
    for d in obs.deaths:
        diff = abs(d.seat - obs.player_seat)
        if diff == 1 or diff == total_seats - 1:
            obs.adjacent_dead.append(d.player_name)

    # Belief tracker integration
    if tracker is not None:
        tracker.update(view)
        obs.role_claims = tracker.claims[:]
        obs.contradictions = tracker.contradictions[:]
        obs.belief_summary = tracker.format_for_prompt()

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

    if obs.legal_targets:
        lines.append(f"合法目标：{'，'.join(f'{p.seat}号:{p.name}' for p in obs.legal_targets)}")

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
            role_str = f"({d.revealed_role})" if d.revealed_role else ""
            lines.append(f"  第{d.seat}号:{d.player_name} {role_str}（{d.cause}）")

    if obs.role_claims:
        lines.append("\n=== 角色声称 ===")
        for c in obs.role_claims[-6:]:
            lines.append(f"  {c.seat}号:{c.player_name} -> {c.claimed_role} (D{c.day})")

    if obs.contradictions:
        lines.append("\n=== 矛盾 ===")
        for c in obs.contradictions:
            lines.append(f"  {c.description}")

    if obs.mentioned_by:
        lines.append(f"\n你被 {', '.join(obs.mentioned_by)} 点名提到")

    if obs.adjacent_dead:
        lines.append(f"你和 {', '.join(obs.adjacent_dead)} 座位相邻")

    if obs.private:
        lines.append("\n=== 私有信息 ===")
        for k, v in obs.private.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


# ============================================================
# Internal helpers
# ============================================================


def _find_player(view: Any, player_id: str) -> dict:
    """Find player dict by id."""
    for p in view.players:
        if p["id"] == player_id:
            return p
    return {"id": player_id, "name": player_id, "seat": 0, "alive": False}


def _detect_role_claim(speech: str) -> Optional[str]:
    """Detect if a speech contains a role claim. Returns role name or None."""
    patterns = [
        (r"(?:我是|我就是|我是真的)\s*(?:一个\s*)?(预言家|女巫|猎人|守卫|村民|白狼王|狼人)", 1),
        (r"(?:跳|报)\s*(?:一个\s*)?(预言家|女巫|猎人|守卫)", 1),
        (r"(?:身份.*?是|底牌.*?是)\s*(预言家|女巫|猎人|守卫|村民|白狼王|狼人)", 1),
    ]
    for pattern, group in patterns:
        m = re.search(pattern, speech)
        if m:
            return m.group(group)
    return None
