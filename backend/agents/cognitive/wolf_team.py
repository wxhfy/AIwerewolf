"""Wolf team coordination — legal wolf-team information view.

CRITICAL: All wolf coordination logic MUST only use information legally
visible to wolf players. Wolves know:
  - Their own role + wolf teammates (from PlayerView.known_wolves)
  - Public speeches, votes, claims, deaths
  - Wolf team night discussion (private events)
  - BeliefTracker inferences

Wolves MUST NOT access:
  - Non-wolf players' true roles or alignments
  - Seer check results
  - Witch potion status
  - Guard protection history (except their own)
  - Hunter shot availability
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WolfTeamView:
    """Wolf team's legally visible private perspective.

    Only contains information that wolf players are allowed to know.
    Does NOT contain non-wolf players' true roles or alignments.
    """

    alive_wolves: list[str] = field(default_factory=list)
    dead_wolves: list[str] = field(default_factory=list)

    # Optional LLM-declared labels. This module does not assign tactics itself.
    role_assignments: dict[str, str] = field(default_factory=dict)

    # Night kill coordination
    agreed_kill_target: str | None = None
    agreed_narrative: str = ""

    # Risks the wolf team should be aware of
    contradiction_risks: list[str] = field(default_factory=list)

    # Current broad game phase label, if supplied by an LLM/strategy layer.
    tactic_phase: str = "early"

    # Public information summaries (derived from public events only)
    public_claims_summary: dict[str, str] = field(default_factory=dict)
    public_vote_summary: dict[str, list[str]] = field(default_factory=dict)

    # Wolf team's beliefs about non-wolf players (from BeliefTracker)
    wolf_beliefs: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_wolf_team_view(
    wolf_ids: list[str],
    all_alive_ids: list[str],
    belief_tracker: Any,  # BeliefTracker instance
    public_events: list[dict[str, Any]],
    wolf_votes: dict[str, str] | None = None,
) -> WolfTeamView:
    """Build a WolfTeamView from legally visible information only.

    Args:
        wolf_ids: List of wolf player IDs (self + teammates from PlayerView).
        all_alive_ids: All currently alive player IDs.
        belief_tracker: BeliefTracker with role claims, contradictions, voting patterns.
        public_events: Public game events (speeches, votes, deaths).
        wolf_votes: Current wolf night kill votes, if any.
    """
    view = WolfTeamView()

    # Alive/dead split from public info
    dead_set = set()
    for event in public_events:
        if event.get("type") == "PLAYER_DIED":
            dead_set.add((event.get("payload") or {}).get("player_id", ""))

    view.alive_wolves = [w for w in wolf_ids if w not in dead_set]
    view.dead_wolves = [w for w in wolf_ids if w in dead_set]

    # Extract public claims from belief tracker
    if hasattr(belief_tracker, 'claims'):
        for claim in belief_tracker.claims:
            pid = getattr(claim, 'player_id', '')
            role = getattr(claim, 'claimed_role', '')
            if pid and role:
                view.public_claims_summary[pid] = role

    # Extract public vote patterns
    vote_map: dict[str, list[str]] = {}
    for event in public_events:
        if event.get("type") == "VOTE_CAST":
            payload = event.get("payload") or {}
            voter = payload.get("voter_id", "") or event.get("actor_id", "")
            target = payload.get("target_id", "")
            if voter and target:
                if voter not in vote_map:
                    vote_map[voter] = []
                vote_map[voter].append(target)
    view.public_vote_summary = vote_map

    # Set agreed kill target from wolf votes
    if wolf_votes:
        from collections import Counter
        tally = Counter(wolf_votes.values())
        if tally:
            view.agreed_kill_target = tally.most_common(1)[0][0]

    return view


def negotiate_wolf_kill(
    wolf_view: WolfTeamView,
    public_state: dict[str, Any],
    belief_tracker: Any,
) -> str:
    """[DEPRECATED] LLM-only compatibility hook — DO NOT USE in new code.

    Kill selection must be made by the LLM from visible information or from the
    explicit strategy layer. This function intentionally returns no target so a
    caller cannot silently reintroduce a hard-coded kill heuristic.

    For task-tracked wolf kill coordination, see the WolfTeamView task
    tracking pipeline instead.
    """
    return ""


def build_wolf_coordination_context(
    wolf_id: str,
    team_view: WolfTeamView,
) -> str:
    """Build legal wolf-team context for Think-stage injection.

    Only includes information legally visible to the wolf team.
    """
    lines = [
        "[狼队可见信息]",
        f"统一口径: {team_view.agreed_narrative or '暂无'}",
    ]

    if team_view.role_assignments:
        lines.append("已声明的队友标签:")
        for mate_id, tactic in team_view.role_assignments.items():
            if mate_id != wolf_id:
                lines.append(f"  - {mate_id}: {tactic}")

    if team_view.contradiction_risks:
        lines.append("需要避免的矛盾:")
        for risk in team_view.contradiction_risks:
            lines.append(f"  - {risk}")

    if team_view.agreed_kill_target:
        lines.append(f"当前计划刀口: {team_view.agreed_kill_target}")

    return "\n".join(lines)


def assign_wolf_tactics(
    wolf_ids: list[str],
    public_state: dict[str, Any],
) -> dict[str, str]:
    """[DEPRECATED] LLM-only compatibility hook — DO NOT USE in new code.

    The non-strategy layer must not assign fixed wolf-team tactics. Explicit
    tactic labels may still come from the LLM planner or strategy layer.

    For task-tracked wolf role assignments, see the WolfTeamView task
    tracking pipeline instead.
    """
    return {}
