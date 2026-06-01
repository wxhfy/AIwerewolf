"""Game state replay engine — exact recalculation for counterfactuals.

Provides deterministic replay of the game engine's resolution logic
without requiring LLM calls. Used by CounterfactualAnalyzer to upgrade
counterfactual confidence from "estimated" to "exact" where possible.

Design: pure functions over snapshot data. No side effects, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# Night Resolution — exact recalculation
# ============================================================

@dataclass
class NightActionsSnapshot:
    """Snapshot of night actions for a single night."""
    day: int
    wolf_target_id: str | None = None
    guard_target_id: str | None = None
    witch_save_used: bool = False
    witch_poison_target_id: str | None = None


@dataclass
class NightResolutionResult:
    """Deterministic result of night resolution."""
    deaths: list[dict[str, str]] = field(default_factory=list)
    survivors: set[str] = field(default_factory=set)
    # Who would have died under the ORIGINAL actions
    original_deaths: list[dict[str, str]] = field(default_factory=list)


def resolve_night(snapshot: NightActionsSnapshot) -> NightResolutionResult:
    """Replay the night resolution logic deterministically.

    Engine logic (from game.py _night_resolve):
      deaths = []
      if wolf_target AND NOT witch_save AND wolf_target != guard_target:
          deaths.append(wolf_target, "wolf")
      if poison_target:
          deaths.append(poison_target, "poison")

    This is an EXACT reproduction — no estimation.
    """
    deaths: list[dict[str, str]] = []

    # Wolf kill: target dies UNLESS saved by witch OR protected by guard
    if snapshot.wolf_target_id:
        blocked = (
            snapshot.witch_save_used
            or snapshot.wolf_target_id == snapshot.guard_target_id
        )
        if not blocked:
            deaths.append({"player_id": snapshot.wolf_target_id, "reason": "wolf"})

    # Witch poison: target dies unconditionally
    if snapshot.witch_poison_target_id:
        deaths.append({"player_id": snapshot.witch_poison_target_id, "reason": "poison"})

    # Deduplicate (same player can't die twice)
    unique_deaths: list[dict[str, str]] = []
    seen: set[str] = set()
    for death in deaths:
        if death["player_id"] not in seen:
            unique_deaths.append(death)
            seen.add(death["player_id"])

    # Survivors = all involved players minus the dead
    all_involved = set()
    if snapshot.wolf_target_id:
        all_involved.add(snapshot.wolf_target_id)
    if snapshot.guard_target_id:
        all_involved.add(snapshot.guard_target_id)
    if snapshot.witch_poison_target_id:
        all_involved.add(snapshot.witch_poison_target_id)
    survivors = all_involved - {d["player_id"] for d in unique_deaths}

    return NightResolutionResult(deaths=unique_deaths, survivors=survivors)


_UNCHANGED = object()  # Sentinel: distinguishes "don't change" from "set to None"


def replay_night_with_change(
    original: NightActionsSnapshot,
    *,
    new_wolf_target: str | None = _UNCHANGED,
    new_guard_target: str | None = _UNCHANGED,
    new_witch_save: bool | None = _UNCHANGED,
    new_poison_target: str | None = _UNCHANGED,
) -> tuple[NightResolutionResult, NightResolutionResult]:
    """Replay night resolution with an alternative decision.

    Returns (original_result, counterfactual_result) for comparison.

    Example:
        # "What if the guard had protected the Seer instead of the Villager?"
        original = NightActionsSnapshot(
            day=1, wolf_target_id=seer_id,
            guard_target_id=villager_id,  # Guard protected the wrong person
        )
        orig, cf = replay_night_with_change(original, new_guard_target=seer_id)
        # orig.deaths = [{seer_id, "wolf"}]
        # cf.deaths = []  # Seer survives!

    """
    original_result = resolve_night(original)

    cf_snapshot = NightActionsSnapshot(
        day=original.day,
        wolf_target_id=new_wolf_target if new_wolf_target is not _UNCHANGED else original.wolf_target_id,
        guard_target_id=new_guard_target if new_guard_target is not _UNCHANGED else original.guard_target_id,
        witch_save_used=new_witch_save if new_witch_save is not _UNCHANGED else original.witch_save_used,
        witch_poison_target_id=new_poison_target if new_poison_target is not _UNCHANGED else original.witch_poison_target_id,
    )

    cf_result = resolve_night(cf_snapshot)
    cf_result.original_deaths = original_result.deaths

    return original_result, cf_result


# ============================================================
# Vote Resolution — exact recalculation
# ============================================================

@dataclass
class VoteSnapshot:
    """Snapshot of a vote round."""
    day: int
    votes: list[tuple[str, str]]  # (voter_id, target_id)
    badge_weight: dict[str, float] | None = None  # voter_id → vote weight


def resolve_vote(snapshot: VoteSnapshot, pk_targets: set[str] | None = None) -> str | None:
    """Replay vote resolution: count votes, return the exiled player_id.

    If pk_targets is provided, only those targets are eligible.
    Ties broken alphabetically (matching engine convention).
    """
    tally: dict[str, float] = {}
    weights = snapshot.badge_weight or {}

    for voter_id, target_id in snapshot.votes:
        if pk_targets and target_id not in pk_targets:
            continue
        weight = weights.get(voter_id, 1.0)
        tally[target_id] = tally.get(target_id, 0.0) + weight

    if not tally:
        return None

    max_votes = max(tally.values())
    candidates = sorted(tid for tid, count in tally.items() if count == max_votes)
    return candidates[0]


def replay_vote_with_swap(
    snapshot: VoteSnapshot,
    voter_id: str,
    new_target_id: str,
    pk_targets: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """Replay vote resolution with one voter's choice swapped.

    Returns (original_exile, counterfactual_exile).
    """
    original_exile = resolve_vote(snapshot, pk_targets)

    # Swap the vote
    cf_votes = []
    for vid, tid in snapshot.votes:
        if vid == voter_id:
            cf_votes.append((vid, new_target_id))
        else:
            cf_votes.append((vid, tid))

    cf_snapshot = VoteSnapshot(
        day=snapshot.day,
        votes=cf_votes,
        badge_weight=snapshot.badge_weight,
    )
    cf_exile = resolve_vote(cf_snapshot, pk_targets)

    return original_exile, cf_exile


# ============================================================
# Hunter Shot Resolution — exact recalculation
# ============================================================

def replay_hunter_shot(
    original_target_id: str,
    alternative_target_id: str,
) -> dict[str, Any]:
    """Replay hunter shot: simple — hunter shoots X instead of Y.

    Returns comparison dict with outcome_change flag.
    """
    return {
        "original_shot_target": original_target_id,
        "alternative_shot_target": alternative_target_id,
        "outcome_changed": original_target_id != alternative_target_id,
        "method": "exact_recalculation",
    }


# ============================================================
# GameState Counterfactual Replayer
# ============================================================

@dataclass
class ReplayResult:
    """Result of a counterfactual replay."""
    counterfactual_type: str
    original_outcome: dict[str, Any]
    alternative_outcome: dict[str, Any]
    outcome_changed: bool
    confidence: float
    evidence: list[str] = field(default_factory=list)


def extract_night_snapshot(
    events: list[Any],
    day: int,
    player_resolver: callable,
) -> NightActionsSnapshot | None:
    """Extract night actions for a specific day from game events.

    Args:
        events: GameEvent list from GameState.
        day: Which night to extract.
        player_resolver: Function(id) → Player.

    Returns:
        NightActionsSnapshot or None if insufficient data.
    """
    snapshot = NightActionsSnapshot(day=day)

    for event in events:
        if event.day != day:
            continue
        payload = event.payload or {}
        action_type = payload.get("action_type", "")

        if action_type == "attack":
            snapshot.wolf_target_id = str(payload.get("target_id", "") or "")
        elif action_type == "guard":
            snapshot.guard_target_id = str(payload.get("target_id", "") or "")
        elif action_type == "witch_save":
            snapshot.witch_save_used = True
        elif action_type == "witch_poison":
            snapshot.witch_poison_target_id = str(payload.get("target_id", "") or "")

    # At minimum we need a wolf attack to make this meaningful
    if not snapshot.wolf_target_id:
        return None

    return snapshot


def extract_vote_snapshot(
    events: list[Any],
    day: int,
) -> VoteSnapshot | None:
    """Extract vote data for a specific day from game events.

    Returns VoteSnapshot or None if no votes found.
    """
    votes: list[tuple[str, str]] = []
    badge_weight: dict[str, float] = {}

    for event in events:
        if event.day != day:
            continue
        if getattr(event, 'type', None) and hasattr(event.type, 'value'):
            if event.type.value == "VOTE_CAST":
                payload = event.payload or {}
                voter_id = str(payload.get("voter_id", ""))
                target_id = str(payload.get("target_id", ""))
                if voter_id and target_id:
                    votes.append((voter_id, target_id))
                    weight = float(payload.get("vote_weight", 1.0))
                    if weight != 1.0:
                        badge_weight[voter_id] = weight

    if not votes:
        return None

    return VoteSnapshot(day=day, votes=votes, badge_weight=badge_weight or None)
