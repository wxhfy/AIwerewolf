"""BeliefState — structured game state tracking for LLM agents.

Maintains a structured summary of role claims, deaths, votes, contradictions,
and observations. Injected into prompts so the LLM can reason about the game
state rather than relying on raw event logs.

Updated each turn by LLMAgent.update() → belief_state.update(view).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Claim:
    """A role claim made by a player."""

    player_id: str
    player_name: str
    seat: int
    claimed_role: str
    day: int
    context: str  # e.g. "badge_election", "day_speech", "last_words"
    verified: bool = False  # True if confirmed by seer check or flip
    contradicts: str | None = None  # player_id of contradicting claimant


@dataclass
class DeathRecord:
    """Record of a player's death."""

    player_id: str
    player_name: str
    seat: int
    day: int
    reason: str  # "vote", "wolf", "poison", "hunter"
    last_words: str | None = None
    revealed_role: str | None = None


@dataclass
class VoteRecord:
    """Record of a vote."""

    day: int
    voter_id: str
    voter_name: str
    target_id: str
    target_name: str
    is_badge: bool = False


class BeliefState:
    """Structured game state tracking for an LLM agent.

    Updated each turn by parsing the PlayerView. Injected into prompts
    as a structured summary so the LLM can reason about the game state.
    """

    def __init__(self, player_id: str):
        self.player_id = player_id

        # Role claims: player_id → list of claims
        self.claims: dict[str, list[Claim]] = {}

        # Deaths: ordered list
        self.deaths: list[DeathRecord] = []

        # Votes: ordered list
        self.votes: list[VoteRecord] = []

        # Player analysis: player_id → analysis dict
        self.player_analysis: dict[str, dict[str, Any]] = {}

        # Key observations (contradictions, suspicious patterns)
        self.observations: list[str] = []

        # Seer check results (private, only for seer)
        self.seer_checks: list[dict[str, Any]] = []

        # Witch state (private, only for witch)
        self.witch_state: dict[str, Any] = {}

        # Guard state (private, only for guard)
        self.guard_state: dict[str, Any] = {}

        # Badge holder
        self.badge_holder: str | None = None

        # Current day
        self.current_day: int = 0

        # My role
        self.my_role: str | None = None

        # My alignment
        self.my_alignment: str | None = None

    def initialize(self, view: Any) -> None:
        """Initialize from the initial PlayerView."""
        # Extract my role and alignment
        self.my_role = view.self_player.get("role")
        self.my_alignment = view.self_player.get("alignment")

        # Initialize player analysis for all players
        for p in view.players:
            pid = p["id"]
            self.player_analysis[pid] = {
                "name": p.get("name", "?"),
                "seat": p.get("seat", 0),
                "alive": p.get("alive", True),
                "suspect_level": 0,  # -100 to 100, positive = more suspicious
                "notes": [],
            }

        # Process private events (role assignments, seer checks, etc.)
        self._process_private_events(view)

    def update(self, view: Any) -> None:
        """Update belief state from current PlayerView."""
        self.current_day = view.day

        # Update alive status
        for p in view.players:
            pid = p["id"]
            if pid in self.player_analysis:
                self.player_analysis[pid]["alive"] = p.get("alive", True)

        # Process new public events
        self._process_public_events(view)

        # Process new private events
        self._process_private_events(view)

        # Detect contradictions
        self._detect_contradictions()

    def _process_private_events(self, view: Any) -> None:
        """Process private events (seer checks, witch actions, etc.)."""
        for event in view.private_events:
            payload = event.get("payload", {}) or {}
            kind = payload.get("kind", "")

            if kind == "role_assignment":
                # Already handled in initialize
                pass

            elif kind == "seer_result":
                target_id = payload.get("target_id", "")
                target_name = payload.get("target_name", "?")
                is_wolf = payload.get("is_wolf", False)
                day = event.get("day", 0)
                self.seer_checks.append(
                    {
                        "day": day,
                        "target_id": target_id,
                        "target_name": target_name,
                        "is_wolf": is_wolf,
                    }
                )

            elif kind == "witch_save":
                self.witch_state["save_used"] = True
                self.witch_state["save_target"] = payload.get("target_name", "?")

            elif kind == "witch_poison":
                self.witch_state["poison_used"] = True
                self.witch_state["poison_target"] = payload.get("target_name", "?")

            elif kind == "guard_protect":
                self.guard_state["last_protected"] = payload.get("target_name", "?")

    def _process_public_events(self, view: Any) -> None:
        """Process public events (claims, deaths, votes, speeches)."""
        for event in view.public_events:
            etype = event.get("type", "")
            payload = event.get("payload", {}) or {}
            day = event.get("day", 0)

            if etype == "PLAYER_DIED":
                self._process_death(event, payload, day)

            elif etype == "VOTE_CAST":
                self._process_vote(event, payload, day)

            elif etype == "CHAT_MESSAGE":
                self._process_speech(event, payload, day)

            elif etype == "SYSTEM_MESSAGE":
                self._process_system_message(event, payload, day)

    def _process_death(self, event: dict, payload: dict, day: int) -> None:
        """Process a death event."""
        player_id = payload.get("player_id", "")
        player_name = payload.get("player_name", "?")
        reason = payload.get("reason", "?")

        # Find seat
        seat = 0
        for pid, analysis in self.player_analysis.items():
            if pid == player_id:
                seat = analysis.get("seat", 0)
                analysis["alive"] = False
                break

        # Get last words if available
        last_words = None
        for e in event.get("last_words_events", []):
            if e.get("type") == "CHAT_MESSAGE":
                last_words = e.get("payload", {}).get("speech", "")
                break

        # Check if role was revealed
        revealed_role = None
        if reason == "vote":
            # Voting out reveals role
            revealed_role = payload.get("role")

        death = DeathRecord(
            player_id=player_id,
            player_name=player_name,
            seat=seat,
            day=day,
            reason=reason,
            last_words=last_words,
            revealed_role=revealed_role,
        )
        self.deaths.append(death)

    def _process_vote(self, event: dict, payload: dict, day: int) -> None:
        """Process a vote event."""
        voter_id = payload.get("voter_id", "")
        voter_name = payload.get("voter_name", "?")
        target_id = payload.get("target_id", "")
        target_name = payload.get("target_name", "?")
        is_badge = payload.get("badge_election", False)

        vote = VoteRecord(
            day=day,
            voter_id=voter_id,
            voter_name=voter_name,
            target_id=target_id,
            target_name=target_name,
            is_badge=is_badge,
        )
        self.votes.append(vote)

    def _process_speech(self, event: dict, payload: dict, day: int) -> None:
        """Process a speech event — extract role claims."""
        actor_id = payload.get("actor_id", "")
        actor_name = payload.get("actor_name", "?")
        speech = payload.get("speech", "")
        is_badge = payload.get("badge_campaign", False)
        is_last_words = payload.get("last_words", False)

        if not speech or not actor_id:
            return

        # Find seat
        seat = 0
        for pid, analysis in self.player_analysis.items():
            if pid == actor_id:
                seat = analysis.get("seat", 0)
                break

        # Extract role claims from speech
        self._extract_claims(actor_id, actor_name, seat, speech, day, is_badge, is_last_words)

    def _extract_claims(
        self, player_id: str, player_name: str, seat: int, speech: str, day: int, is_badge: bool, is_last_words: bool
    ) -> None:
        """Extract role claims from a speech."""
        speech.lower()

        # Determine context
        if is_badge:
            context = "badge_election"
        elif is_last_words:
            context = "last_words"
        else:
            context = "day_speech"

        # Check for seer claim
        seer_keywords = ["我是预言家", "预言家", "我是验", "我验了", "昨晚验", "查了", "查验"]
        for keyword in seer_keywords:
            if keyword in speech:
                # Check if this is a new claim or confirmation
                existing_claims = self.claims.get(player_id, [])
                has_seer_claim = any(c.claimed_role == "Seer" for c in existing_claims)
                if not has_seer_claim:
                    claim = Claim(
                        player_id=player_id,
                        player_name=player_name,
                        seat=seat,
                        claimed_role="Seer",
                        day=day,
                        context=context,
                    )
                    self.claims.setdefault(player_id, []).append(claim)
                break

        # Check for witch claim
        witch_keywords = ["我是女巫", "女巫", "我救了", "我毒了", "解药", "毒药"]
        for keyword in witch_keywords:
            if keyword in speech:
                existing_claims = self.claims.get(player_id, [])
                has_witch_claim = any(c.claimed_role == "Witch" for c in existing_claims)
                if not has_witch_claim:
                    claim = Claim(
                        player_id=player_id,
                        player_name=player_name,
                        seat=seat,
                        claimed_role="Witch",
                        day=day,
                        context=context,
                    )
                    self.claims.setdefault(player_id, []).append(claim)
                break

        # Check for guard claim
        guard_keywords = ["我是守卫", "守卫", "我守了"]
        for keyword in guard_keywords:
            if keyword in speech:
                existing_claims = self.claims.get(player_id, [])
                has_guard_claim = any(c.claimed_role == "Guard" for c in existing_claims)
                if not has_guard_claim:
                    claim = Claim(
                        player_id=player_id,
                        player_name=player_name,
                        seat=seat,
                        claimed_role="Guard",
                        day=day,
                        context=context,
                    )
                    self.claims.setdefault(player_id, []).append(claim)
                break

        # Check for hunter claim
        hunter_keywords = ["我是猎人", "猎人"]
        for keyword in hunter_keywords:
            if keyword in speech:
                existing_claims = self.claims.get(player_id, [])
                has_hunter_claim = any(c.claimed_role == "Hunter" for c in existing_claims)
                if not has_hunter_claim:
                    claim = Claim(
                        player_id=player_id,
                        player_name=player_name,
                        seat=seat,
                        claimed_role="Hunter",
                        day=day,
                        context=context,
                    )
                    self.claims.setdefault(player_id, []).append(claim)
                break

    def _process_system_message(self, event: dict, payload: dict, day: int) -> None:
        """Process system messages (badge assignment, etc.)."""
        msg = payload.get("message", "")
        if "sheriff" in msg.lower() or "badge" in msg.lower() or "警长" in msg:
            # Extract badge holder
            for pid, analysis in self.player_analysis.items():
                name = analysis.get("name", "")
                if name in msg:
                    self.badge_holder = pid
                    break

    def _detect_contradictions(self) -> None:
        """Detect contradictions between claims."""
        # Group claims by role
        role_claimants: dict[str, list[Claim]] = {}
        for _player_id, claims in self.claims.items():
            for claim in claims:
                role_claimants.setdefault(claim.claimed_role, []).append(claim)

        # Check for multiple claimants of unique roles
        unique_roles = ["Seer", "Witch", "Guard", "Hunter"]
        for role in unique_roles:
            claimants = role_claimants.get(role, [])
            if len(claimants) > 1:
                names = [f"{c.seat}号{c.player_name}" for c in claimants]
                self.observations.append(f"⚠️ 多人声称{role}：{'、'.join(names)}，存在矛盾")
                # Mark contradictions
                for i, c1 in enumerate(claimants):
                    for j, c2 in enumerate(claimants):
                        if i < j:
                            c1.contradicts = c2.player_id
                            c2.contradicts = c1.player_id

        # Check for seer claims vs actual seer checks
        seer_claims = role_claimants.get("Seer", [])
        for claim in seer_claims:
            # Check if this player's claimed checks match actual checks
            if self.seer_checks and claim.player_id == self.player_id:
                # I am the real seer - check if someone else is claiming
                for other_claim in seer_claims:
                    if other_claim.player_id != self.player_id:
                        self.observations.append(
                            f"⚠️ {other_claim.seat}号{other_claim.player_name}声称预言家，但我是真预言家，这是假跳"
                        )

    def get_summary(self) -> str:
        """Get a structured summary for prompt injection."""
        lines = []

        # My identity
        lines.append("【我的身份】")
        lines.append(f"角色: {self.my_role or '?'}")
        lines.append(f"阵营: {self.my_alignment or '?'}")
        if self.badge_holder:
            holder = self.player_analysis.get(self.badge_holder, {})
            lines.append(f"警长: {holder.get('seat', '?')}号{holder.get('name', '?')}")
        lines.append("")

        # Role claims
        if self.claims:
            lines.append("【角色声称】")
            for _player_id, claims in self.claims.items():
                for claim in claims:
                    status = ""
                    if claim.contradicts:
                        contradicter = self.player_analysis.get(claim.contradicts, {})
                        status = f" ⚠️与{contradicter.get('seat', '?')}号矛盾"
                    lines.append(
                        f"  {claim.seat}号{claim.player_name} "
                        f"在第{claim.day}天{claim.context}声称{claim.claimed_role}{status}"
                    )
            lines.append("")

        # Deaths
        if self.deaths:
            lines.append("【出局记录】")
            for death in self.deaths:
                role_info = f"（身份：{death.revealed_role}）" if death.revealed_role else ""
                last_words_info = ""
                if death.last_words:
                    last_words_info = f" 遗言：「{death.last_words[:80]}」"
                lines.append(
                    f"  第{death.day}天 {death.seat}号{death.player_name} "
                    f"出局（{death.reason}）{role_info}{last_words_info}"
                )
            lines.append("")

        # Voting patterns (recent)
        recent_votes = [v for v in self.votes if not v.is_badge][-10:]
        if recent_votes:
            lines.append("【近期投票】")
            for vote in recent_votes:
                lines.append(f"  第{vote.day}天 {vote.voter_name} → {vote.target_name}")
            lines.append("")

        # Seer checks (private)
        if self.seer_checks:
            lines.append("【预言家查验记录】")
            for check in self.seer_checks:
                result = "狼人" if check["is_wolf"] else "好人"
                lines.append(f"  第{check['day']}夜 查{check['target_name']} = {result}")
            lines.append("")

        # Witch state (private)
        if self.witch_state:
            lines.append("【女巫状态】")
            if self.witch_state.get("save_used"):
                lines.append(f"  解药已使用（救了{self.witch_state.get('save_target', '?')}）")
            else:
                lines.append("  解药可用")
            if self.witch_state.get("poison_used"):
                lines.append(f"  毒药已使用（毒了{self.witch_state.get('poison_target', '?')}）")
            else:
                lines.append("  毒药可用")
            lines.append("")

        # Guard state (private)
        if self.guard_state:
            lines.append("【守卫状态】")
            if self.guard_state.get("last_protected"):
                lines.append(f"  上次守护: {self.guard_state['last_protected']}")
            lines.append("")

        # Key observations
        if self.observations:
            lines.append("【关键发现】")
            for obs in self.observations[-5:]:  # Last 5 observations
                lines.append(f"  {obs}")
            lines.append("")

        return "\n".join(lines) if lines else "（暂无结构化信息）"

    def get_reasoning_context(self) -> str:
        """Get reasoning context for the LLM — highlights what to think about."""
        lines = []

        # Contradictions to resolve
        contradictions = [obs for obs in self.observations if "矛盾" in obs or "假跳" in obs]
        if contradictions:
            lines.append("【需要解决的矛盾】")
            for obs in contradictions:
                lines.append(f"  {obs}")
            lines.append("")

        # Dead players' last words (often ignored!)
        dead_with_words = [d for d in self.deaths if d.last_words]
        if dead_with_words:
            lines.append("【遗言信息——不要忽略！】")
            for death in dead_with_words:
                lines.append(f"  {death.seat}号{death.player_name}（{death.reason}）遗言：「{death.last_words[:100]}」")
            lines.append("")

        # Voting pattern analysis
        if self.votes:
            lines.append("【投票模式分析】")
            # Find who voted together
            recent = [v for v in self.votes if not v.is_badge][-7:]
            if recent:
                # Group by target
                target_voters: dict[str, list[str]] = {}
                for v in recent:
                    target_voters.setdefault(v.target_name, []).append(v.voter_name)
                for target, voters in target_voters.items():
                    if len(voters) >= 2:
                        lines.append(f"  {'、'.join(voters)} 都投了 {target}")
            lines.append("")

        return "\n".join(lines) if lines else ""
