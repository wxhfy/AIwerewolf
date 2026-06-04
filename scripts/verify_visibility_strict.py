#!/usr/bin/env python3
"""Information isolation smoke check for the Werewolf game engine.

Validates that Visibility.for_player() correctly enforces role/alignment-based
information hiding by simulating a full night round and checking each player's
view for leaks.

Usage:
    python scripts/verify_visibility_strict.py

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

from __future__ import annotations

import sys
from uuid import uuid4

sys.path.insert(0, "/home/fyh0106/AIwerewolf")

from backend.engine.models import (
    Alignment,
    Role,
    Phase,
    EventType,
    Player,
    GameEvent,
    GameState,
    BadgeState,
    NightActions,
)
from backend.engine.visibility import Visibility


# ============================================================
# Test setup: 6 players with known roles
# ============================================================

PLAYERS = [
    Player(id="p1", seat=1, name="Alice", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    Player(id="p2", seat=2, name="Bob",   role=Role.WEREWOLF, alignment=Alignment.WOLF),
    Player(id="p3", seat=3, name="Carol", role=Role.SEER,     alignment=Alignment.VILLAGE),
    Player(id="p4", seat=4, name="Dave",  role=Role.WITCH,    alignment=Alignment.VILLAGE),
    Player(id="p5", seat=5, name="Eve",   role=Role.GUARD,    alignment=Alignment.VILLAGE),
    Player(id="p6", seat=6, name="Frank", role=Role.WEREWOLF, alignment=Alignment.WOLF),
]

ROLE_MAP = {p.id: p.role for p in PLAYERS}
ALIGN_MAP = {p.id: p.alignment for p in PLAYERS}

# ============================================================
# Helpers
# ============================================================

_passes = 0
_fails = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passes, _fails
    if condition:
        _passes += 1
        print(f"  PASS  {name}")
    else:
        _fails += 1
        print(f"  FAIL  {name}  -- {detail}")


def make_event(phase: Phase, etype: EventType, visibility: str, payload: dict,
               visible_to: list[str] | None = None) -> GameEvent:
    return GameEvent(
        id=str(uuid4()),
        ts=0.0,
        day=1,
        phase=phase,
        type=etype,
        visibility=visibility,
        payload=payload,
        visible_to=visible_to or [],
    )


def build_state(phase: Phase, events: list[GameEvent]) -> GameState:
    return GameState(
        id="test-game-001",
        phase=phase,
        day=1,
        players=list(PLAYERS),
        events=events,
    )


# ============================================================
# Test: Simulated Night Round
# ============================================================

print("=" * 70)
print("Information Isolation Smoke Check")
print("=" * 70)

visibility = Visibility()

# --- Build events simulating a full night round ---

events: list[GameEvent] = []

# 1. NIGHT_START system message (public)
events.append(make_event(
    Phase.NIGHT_START, EventType.SYSTEM_MESSAGE, "public",
    {"message": "Night 1 begins."},
))

# 2. Role assignment messages (private, one per player)
for p in PLAYERS:
    events.append(make_event(
        Phase.SETUP, EventType.PRIVATE_INFO, "private",
        {"kind": "role_assignment",
         "message": f"You are {p.name}, role={p.role.value}"},
        visible_to=[p.id],
    ))

# 3. Guard action: Eve guards Bob (private to Eve)
events.append(make_event(
    Phase.NIGHT_GUARD_ACTION, EventType.NIGHT_ACTION, "private",
    {"action_type": "guard", "target_id": "p2", "target_name": "Bob"},
    visible_to=["p5"],
))

# 4. Wolf team discussion (private to wolves: Bob + Frank)
events.append(make_event(
    Phase.NIGHT_WOLF_ACTION, EventType.PRIVATE_INFO, "private",
    {"kind": "wolf_chat_start",
     "message": "Wolf team discussion begins.",
     "wolf_ids": ["p2", "p6"],
     "wolf_names": ["Bob", "Frank"]},
    visible_to=["p2", "p6"],
))

# 5. Wolf attack vote: Bob votes to kill Alice
events.append(make_event(
    Phase.NIGHT_WOLF_ACTION, EventType.NIGHT_ACTION, "private",
    {"kind": "wolf_attack_vote",
     "target_id": "p1", "target_name": "Alice",
     "actor_id": "p2",
     "current_votes": {"p2": "p1"}},
    visible_to=["p2", "p6"],
))

# 6. Wolf attack vote: Frank also votes Alice
events.append(make_event(
    Phase.NIGHT_WOLF_ACTION, EventType.NIGHT_ACTION, "private",
    {"kind": "wolf_attack_vote",
     "target_id": "p1", "target_name": "Alice",
     "actor_id": "p6",
     "current_votes": {"p2": "p1", "p6": "p1"}},
    visible_to=["p2", "p6"],
))

# 7. Wolf final tally (private to wolves)
events.append(make_event(
    Phase.NIGHT_WOLF_ACTION, EventType.PRIVATE_INFO, "private",
    {"kind": "wolf_attack_tally",
     "message": "Wolf team final attack target is Alice.",
     "target_id": "p1", "target_name": "Alice"},
    visible_to=["p2", "p6"],
))

# 8. Witch is told the victim: Alice was attacked (private to Witch: Dave)
events.append(make_event(
    Phase.NIGHT_WITCH_ACTION, EventType.PRIVATE_INFO, "private",
    {"kind": "witch_notify",
     "victim_id": "p1", "victim_name": "Alice",
     "message": "Tonight's victim is Alice."},
    visible_to=["p4"],
))

# 9. Witch chooses to save Alice (private to Witch: Dave)
events.append(make_event(
    Phase.NIGHT_WITCH_ACTION, EventType.NIGHT_ACTION, "private",
    {"action_type": "witch_save", "target_id": "p1"},
    visible_to=["p4"],
))

# 10. Seer checks Bob (private to Seer: Carol)
events.append(make_event(
    Phase.NIGHT_SEER_ACTION, EventType.PRIVATE_INFO, "private",
    {"kind": "seer_result",
     "target_id": "p2", "target_name": "Bob",
     "is_wolf": True,
     "message": "Seer check: Bob is wolf."},
    visible_to=["p3"],
))

# 11. Night deaths announced (public)
events.append(make_event(
    Phase.NIGHT_RESOLVE, EventType.SYSTEM_MESSAGE, "public",
    {"message": "No one died last night."},
))

# Build the state
state = build_state(Phase.NIGHT_RESOLVE, events)

# ============================================================
# Compute views for each player
# ============================================================

views: dict[str, any] = {}
for p in PLAYERS:
    views[p.id] = visibility.for_player(state, p.id)


# ============================================================
# Test Suite
# ============================================================

print("\n--- 1. STRUCTURAL CHECKS ---\n")

# 1a: Every player gets a view
for p in PLAYERS:
    check(
        f"Player {p.name} gets a PlayerView",
        hasattr(views[p.id], 'player_id') and views[p.id].player_id == p.id,
        f"View missing or wrong player_id",
    )

# 1b: Self players are private_dict (include role)
for p in PLAYERS:
    sv = views[p.id].self_player
    check(
        f"{p.name} sees own role ({p.role.value})",
        sv.get("role") == p.role.value,
        f"Expected role={p.role.value}, got role={sv.get('role')}",
    )
    check(
        f"{p.name} sees own alignment ({p.alignment.value})",
        sv.get("alignment") == p.alignment.value,
        f"Expected alignment={p.alignment.value}, got alignment={sv.get('alignment')}",
    )

# 1c: Public events appear in everyone's view
# Only SYSTEM_MESSAGE events are public; PRIVATE_INFO/NIGHT_ACTION are private
expected_public_count = sum(1 for e in events if e.visibility == "public")
for p in PLAYERS:
    actual = len(views[p.id].public_events)
    check(
        f"{p.name} sees {actual} public events (expected {expected_public_count})",
        actual == expected_public_count,
        f"Expected {expected_public_count}, got {actual}",
    )

# 1d: All player list is present
for p in PLAYERS:
    check(
        f"{p.name} sees all {len(PLAYERS)} players",
        len(views[p.id].players) == len(PLAYERS),
        f"Expected {len(PLAYERS)}, got {len(views[p.id].players)}",
    )


print("\n--- 2. INFORMATION ISOLATION: Villager (Alice, p1) ---\n")

alice_view = views["p1"]

# 2a: Villager has only role_assignment as private event
check(
    f"Villager has 1 private event (role_assignment)",
    len(alice_view.private_events) == 1,
    f"Expected 1, got {len(alice_view.private_events)}: "
    f"{[e.get('payload',{}).get('kind','') for e in alice_view.private_events]}",
)

# 2b: Villager does NOT see seer result
seer_in_villager = any(
    e.get("payload", {}).get("kind") == "seer_result"
    for e in alice_view.private_events
)
check(
    "Villager does NOT see seer result in private_events",
    not seer_in_villager,
    "Villager should not have access to seer_check results",
)

# 2c: Villager does NOT see witch victim
witch_in_villager = any(
    "victim_id" in e.get("payload", {}) for e in alice_view.private_events
)
check(
    "Villager does NOT see witch victim",
    not witch_in_villager,
    "Villager should not know tonight's victim",
)

# 2d: Villager does NOT see wolf team
check(
    "Villager has empty known_wolves",
    len(alice_view.known_wolves) == 0,
    f"Expected 0 wolves in known_wolves, got {len(alice_view.known_wolves)}",
)


print("\n--- 3. INFORMATION ISOLATION: Wolf (Bob, p2) ---\n")

bob_view = views["p2"]

# 3a: Wolf sees wolf teammates (excl. self: just Frank)
wolf_names_in_view = {w.get("name", "") for w in bob_view.known_wolves}
check(
    f"Wolf sees both teammates (Bob+Frank): got {wolf_names_in_view}",
    wolf_names_in_view == {"Bob", "Frank"},
    f"Expected {{'Bob', 'Frank'}}, got {wolf_names_in_view}",
)

# 3b: Wolf sees wolf-team private events (chat, votes, tally)
bob_private_kinds = [
    e.get("payload", {}).get("kind", "")
    for e in bob_view.private_events
]
has_wolf_chat = any(k.startswith("wolf_") for k in bob_private_kinds)
check(
    "Wolf sees wolf_* private events",
    has_wolf_chat,
    f"Expected wolf_* events, got kinds: {bob_private_kinds}",
)

# 3c: Wolf does NOT see seer result
seer_in_wolf = any(
    e.get("payload", {}).get("kind") == "seer_result"
    for e in bob_view.private_events
)
check(
    "Wolf does NOT see seer result",
    not seer_in_wolf,
    "Wolf should not have access to seer_check results",
)

# 3d: Wolf does NOT see witch actions
witch_in_wolf = any(
    "victim_id" in e.get("payload", {}) for e in bob_view.private_events
)
check(
    "Wolf does NOT see witch victim notification",
    not witch_in_wolf,
    "Wolf should not know what the witch knows",
)


print("\n--- 4. INFORMATION ISOLATION: Seer (Carol, p3) ---\n")

carol_view = views["p3"]

# 4a: Seer sees check result in private_events
seer_events = [
    e for e in carol_view.private_events
    if e.get("payload", {}).get("kind") == "seer_result"
]
check(
    "Seer sees seer_check result in private_events",
    len(seer_events) >= 1,
    f"Expected >=1 seer_result events, got {len(seer_events)}",
)
if seer_events:
    payload = seer_events[0].get("payload", {})
    check(
        "Seer result confirms Bob is wolf",
        payload.get("is_wolf") is True,
        f"Expected is_wolf=True, got {payload.get('is_wolf')}",
    )
    check(
        "Seer result has correct target_id (Bob=p2)",
        payload.get("target_id") == "p2",
        f"Expected target_id=p2, got {payload.get('target_id')}",
    )

# 4b: Seer does NOT see wolf team
check(
    "Seer has empty known_wolves",
    len(carol_view.known_wolves) == 0,
    f"Seer should not see wolf teammates, got {len(carol_view.known_wolves)}",
)

# 4c: Seer does NOT see witch data
witch_in_seer = any(
    "victim_id" in e.get("payload", {}) for e in carol_view.private_events
)
check(
    "Seer does NOT see witch victim",
    not witch_in_seer,
    "Seer should not have witch info",
)


print("\n--- 5. INFORMATION ISOLATION: Witch (Dave, p4) ---\n")

dave_view = views["p4"]

# 5a: Witch sees victim notification
witch_victim_events = [
    e for e in dave_view.private_events
    if "victim_id" in e.get("payload", {})
]
check(
    "Witch sees victim notification",
    len(witch_victim_events) >= 1,
    f"Expected >=1 events with victim_id, got {len(witch_victim_events)}",
)
if witch_victim_events:
    payload = witch_victim_events[0].get("payload", {})
    check(
        "Witch victim is Alice (p1)",
        payload.get("victim_id") == "p1",
        f"Expected victim_id=p1, got {payload.get('victim_id')}",
    )

# 5b: Witch does NOT see seer result
seer_in_witch = any(
    e.get("payload", {}).get("kind") == "seer_result"
    for e in dave_view.private_events
)
check(
    "Witch does NOT see seer result",
    not seer_in_witch,
    "Witch should not have seer info",
)

# 5c: Witch does NOT see wolf team
check(
    "Witch has empty known_wolves",
    len(dave_view.known_wolves) == 0,
    f"Witch should not see wolf teammates, got {len(dave_view.known_wolves)}",
)

# 5d: Witch does NOT see wolf coordination details
wolf_coord_in_witch = any(
    (e.get("payload", {}) or {}).get("kind", "").startswith("wolf_")
    for e in dave_view.private_events
)
check(
    "Witch does NOT see wolf coordination events",
    not wolf_coord_in_witch,
    "Witch should not know wolf internal discussions",
)


print("\n--- 6. INFORMATION ISOLATION: Guard (Eve, p5) ---\n")

eve_view = views["p5"]

# 6a: Guard sees own guard action
guard_events = [
    e for e in eve_view.private_events
    if e.get("payload", {}).get("action_type") == "guard"
]
check(
    "Guard sees guard action in private_events",
    len(guard_events) >= 1,
    f"Expected >=1 guard events, got {len(guard_events)}",
)

# 6b, 6c, 6d: Guard does NOT see cross-role secrets
seer_in_guard = any(
    e.get("payload", {}).get("kind") == "seer_result"
    for e in eve_view.private_events
)
check(
    "Guard does NOT see seer result",
    not seer_in_guard,
    "Guard should not have seer info",
)
check(
    "Guard has empty known_wolves",
    len(eve_view.known_wolves) == 0,
    f"Guard should not see wolf teammates, got {len(eve_view.known_wolves)}",
)
witch_in_guard = any(
    "victim_id" in e.get("payload", {}) for e in eve_view.private_events
)
check(
    "Guard does NOT see witch victim",
    not witch_in_guard,
    "Guard should not have witch info",
)


print("\n--- 7. PLAYER LIST VISIBILITY (role masking) ---\n")

# For non-wolf, non-self players: only see public_dict (no role/alignment)
# Villager Alice should not see other players' roles
alice_view2 = views["p1"]
for p_dict in alice_view2.players:
    if p_dict["id"] != "p1":  # Not self
        has_role_leak = "role" in p_dict and p_dict["role"] not in (
            "unknown", None, ""
        )
        check(
            f"Alice sees {p_dict.get('name', p_dict['id'])} without role",
            not has_role_leak,
            f"Alice should NOT see role of {p_dict.get('name')}, "
            f"got role={p_dict.get('role')}",
        )

# Wolf Bob should see other wolves' roles (via private_dict)
bob_view2 = views["p2"]
for p_dict in bob_view2.players:
    if p_dict["id"] == "p6":  # Frank, fellow wolf
        check(
            "Bob sees fellow wolf Frank's role as Werewolf",
            p_dict.get("role") == Role.WEREWOLF.value,
            f"Bob should see Frank as Werewolf, got role={p_dict.get('role')}",
        )
    elif p_dict["id"] != "p2":  # Not self, not fellow wolf
        has_role_leak = "role" in p_dict and p_dict["role"] not in (
            "unknown", None, ""
        )
        check(
            f"Bob sees {p_dict.get('name', p_dict['id'])} without role",
            not has_role_leak,
            f"Bob should NOT see role of {p_dict.get('name')}, "
            f"got role={p_dict.get('role')}",
        )


print("\n--- 8. NO CROSS-CONTAMINATION: Seer/Witch/Wolf secrets ---\n")

# Verify no single player sees ALL the secrets
for p in PLAYERS:
    view = views[p.id]
    has_seer = any(
        e.get("payload", {}).get("kind") == "seer_result"
        for e in view.private_events
    )
    has_witch = any(
        "victim_id" in e.get("payload", {})
        for e in view.private_events
    )
    has_wolf = len(view.known_wolves) > 0

    cnt = sum([has_seer, has_witch, has_wolf])
    check(
        f"{p.name}({p.role.value}) has <=1 secret category "
        f"(seer={has_seer}, witch={has_witch}, wolf={has_wolf})",
        cnt <= 1,
        f"Player {p.name} has {cnt} secret categories -- potential leak!",
    )


print("\n--- 9. PUBLIC EVENT INTEGRITY ---\n")

# Public events must not contain private info
for p in PLAYERS:
    view = views[p.id]
    for event in view.public_events:
        payload = event.get("payload", {})

        # Public events must not contain seer results
        if isinstance(payload, dict) and "is_wolf" in payload:
            check(
                f"Public event (type={event.get('type')}) in {p.name}'s view "
                f"does NOT leak seer result",
                False,
                f"Seer result leaked in public event: {payload}",
            )
        else:
            check(
                f"Public event (type={event.get('type')}) in {p.name}'s view "
                f"does NOT leak seer result",
                True,
                "",
            )

        # Public events must not contain role assignments
        if isinstance(payload, dict) and payload.get("kind") == "role_assignment":
            check(
                f"Public event (type={event.get('type')}) in {p.name}'s view "
                f"does NOT leak role assignment",
                False,
                f"Role assignment leaked in public event: {payload}",
            )
        else:
            check(
                f"Public event (type={event.get('type')}) in {p.name}'s view "
                f"does NOT leak role assignment",
                True,
                "",
            )


# ============================================================
# Results
# ============================================================

print()
print("=" * 70)
print(f"RESULTS: {_passes} passed, {_fails} failed")
print("=" * 70)

if _fails > 0:
    print(f"\nFAILURE: {_fails} information isolation check(s) failed!")
    sys.exit(1)
else:
    print("\nAll information isolation checks passed.")
    sys.exit(0)
