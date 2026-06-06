"""Skill Protocol — unified interface for role abilities.

Blueprint v2 §G4: replace scattered if/elif chains in actions.py and game.py
with a standard Skill protocol. Adding a new role means implementing one class
and registering it, not touching engine internals.

Design:
  Skill (Protocol)     — contract every ability fulfills
  SkillRegistry        — singleton replacing ACTION_RULES + phase dispatch
  register_builtins()  — one-shot registration of core 6+ roles
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol
from typing import runtime_checkable

from backend.engine.models import ActionType
from backend.engine.models import Decision
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player
from backend.engine.models import Role

# ================================================================
# Skill Protocol
# ================================================================


@runtime_checkable
class Skill(Protocol):
    """Contract every role ability must fulfill.

    Each skill is self-contained: it declares its metadata, validates
    actions, applies effects, and controls visibility — all without
    the engine knowing implementation details.
    """

    # ---- Metadata (class-level, set on concrete instances) ----
    name: str
    owner_role: Role
    phase: Phase
    action_type: ActionType
    priority: int  # lower = earlier in resolution order
    consumes_resource: str | None  # e.g. "antidote", "poison", "bullet"
    can_target_self: bool
    can_target_dead: bool
    can_execute_when_dead: bool
    requires_target: bool

    # ---- Lifecycle ----

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        """Return list of legal target player IDs."""
        ...

    def validate(self, decision: Decision, state: GameState) -> bool:
        """Return True if the decision is legal under current state."""
        ...

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        """Apply the skill effect. Returns list of event payloads to log."""
        ...

    def summarize_for_actor(self, decision: Decision, state: GameState) -> str:
        """Human-readable summary for the acting player."""
        ...

    def summarize_for_public(self, events: list[dict[str, Any]]) -> str:
        """Human-readable summary for public log."""
        ...


# ================================================================
# Skill Registry
# ================================================================


@dataclass
class SkillEntry:
    """Wraps a Skill with resolved metadata for fast lookup."""

    skill: Skill
    name: str
    owner_role: Role
    phase: Phase
    action_type: ActionType
    priority: int
    consumes_resource: str | None


class SkillRegistry:
    """Singleton mapping (role, phase) → Skill for the engine.

    Replaces the hard-coded ACTION_RULES dict in actions.py.
    """

    _instance: SkillRegistry | None = None

    def __init__(self):
        self._by_role_phase: dict[tuple[Role, Phase], list[SkillEntry]] = {}
        self._by_action: dict[ActionType, SkillEntry] = {}
        self._all: list[SkillEntry] = []

    # ---- Singleton ----

    @classmethod
    def get(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = cls()
            register_builtins(cls._instance)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None

    # ---- Registration ----

    def register(self, skill: Skill) -> SkillEntry:
        entry = SkillEntry(
            skill=skill,
            name=skill.name,
            owner_role=skill.owner_role,
            phase=skill.phase,
            action_type=skill.action_type,
            priority=skill.priority,
            consumes_resource=skill.consumes_resource,
        )
        key = (skill.owner_role, skill.phase)
        self._by_role_phase.setdefault(key, []).append(entry)
        self._by_action[skill.action_type] = entry
        self._all.append(entry)
        # Keep sorted by priority for resolution order
        self._by_role_phase[key].sort(key=lambda e: e.priority)
        return entry

    # ---- Lookup ----

    def for_role_phase(self, role: Role, phase: Phase) -> list[SkillEntry]:
        """Skills available to a role in a given phase."""
        return self._by_role_phase.get((role, phase), [])

    def for_action(self, action_type: ActionType) -> SkillEntry | None:
        """Skill that produces this action type."""
        return self._by_action.get(action_type)

    def allowed_roles(self, action_type: ActionType) -> tuple[Role, ...]:
        """Roles allowed to use this action type (backward-compat with ACTION_RULES)."""
        entry = self._by_action.get(action_type)
        if entry is None:
            return ()
        return (entry.owner_role,)

    def validate_action(self, decision: Decision, state: GameState) -> bool:
        """Validate a decision using the appropriate skill."""
        entry = self._by_action.get(decision.action_type)
        if entry is None:
            return False
        actor = state.player(decision.actor_id)
        if entry.skill.can_execute_when_dead is False and not actor.alive:
            return False
        if entry.owner_role != actor.role:
            return False
        if entry.skill.requires_target:
            if decision.target_id is None:
                return False
            try:
                target = state.player(decision.target_id)
            except KeyError:
                return False
            if not entry.skill.can_target_dead and not target.alive:
                return False
            if not entry.skill.can_target_self and target.id == actor.id:
                return False
        return entry.skill.validate(decision, state)

    def all_skills(self) -> list[SkillEntry]:
        return list(self._all)


# ================================================================
# Built-in Skill Implementations
# ================================================================


class _BaseSkill:
    """Default no-op implementations so concrete skills are minimal."""

    requires_target: bool = True
    can_target_self: bool = False
    can_target_dead: bool = False
    can_execute_when_dead: bool = False
    consumes_resource: str | None = None

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        alive = [p.id for p in state.alive_players]
        if self.can_target_self:
            return alive
        return [pid for pid in alive if pid != actor.id]

    def validate(self, decision: Decision, state: GameState) -> bool:
        actor = state.player(decision.actor_id)
        if not self.can_execute_when_dead and not actor.alive:
            return False
        if self.requires_target:
            if decision.target_id is None:
                return False
            try:
                target = state.player(decision.target_id)
            except KeyError:
                return False
            if not self.can_target_dead and not target.alive:
                return False
            if not self.can_target_self and target.id == actor.id:
                return False
        return True

    def summarize_for_actor(self, decision: Decision, state: GameState) -> str:
        target_name = state.player(decision.target_id).name if decision.target_id else "nobody"
        return f"{self.name}: target={target_name}"

    def summarize_for_public(self, events: list[dict[str, Any]]) -> str:
        return f"{self.name} used"


class GuardSkill(_BaseSkill):
    name = "guard"
    owner_role = Role.GUARD
    phase = Phase.NIGHT_GUARD_ACTION
    action_type = ActionType.GUARD
    priority = 1
    consumes_resource = None
    can_target_self = True

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        # Cannot guard the same target twice in a row
        last = state.night_actions.last_guard_target_id
        return [p.id for p in state.alive_players if p.id != last]

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        state.night_actions.guard_target_id = decision.target_id
        state.night_actions.last_guard_target_id = decision.target_id
        return [{"action": "guard", "target_id": decision.target_id}]


class WolfAttackSkill(_BaseSkill):
    name = "wolf_attack"
    owner_role = Role.WEREWOLF
    phase = Phase.NIGHT_WOLF_ACTION
    action_type = ActionType.ATTACK
    priority = 2

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        wolves = {p.id for p in state.alive_players if p.alignment.value == "wolf"}
        return [p.id for p in state.alive_players if p.id not in wolves]

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        state.night_actions.wolf_target_id = decision.target_id
        return [{"action": "wolf_attack", "target_id": decision.target_id}]


class WitchSaveSkill(_BaseSkill):
    name = "witch_save"
    owner_role = Role.WITCH
    phase = Phase.NIGHT_WITCH_ACTION
    action_type = ActionType.WITCH_SAVE
    priority = 3
    consumes_resource = "antidote"

    def validate(self, decision: Decision, state: GameState) -> bool:
        if state.abilities.witch_heal_used:
            return False
        if decision.target_id != state.night_actions.wolf_target_id:
            return False
        return super().validate(decision, state)

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        state.abilities.witch_heal_used = True
        state.night_actions.witch_save = True
        return [{"action": "witch_save", "target_id": decision.target_id}]


class WitchPoisonSkill(_BaseSkill):
    name = "witch_poison"
    owner_role = Role.WITCH
    phase = Phase.NIGHT_WITCH_ACTION
    action_type = ActionType.WITCH_POISON
    priority = 4
    consumes_resource = "poison"

    def validate(self, decision: Decision, state: GameState) -> bool:
        if state.abilities.witch_poison_used:
            return False
        return super().validate(decision, state)

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        state.abilities.witch_poison_used = True
        state.night_actions.witch_poison_target_id = decision.target_id
        return [{"action": "witch_poison", "target_id": decision.target_id}]


class SeerDivineSkill(_BaseSkill):
    name = "seer_divine"
    owner_role = Role.SEER
    phase = Phase.NIGHT_SEER_ACTION
    action_type = ActionType.DIVINE
    priority = 5

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        target = state.player(decision.target_id or "")
        is_wolf = target.alignment.value == "wolf"
        state.night_actions.seer_target_id = target.id
        state.night_actions.seer_result = {
            "kind": "seer_result",
            "target_id": target.id,
            "target_name": target.name,
            "is_wolf": is_wolf,
            "message": f"Seer check: {target.name} is {'wolf' if is_wolf else 'not wolf'}.",
        }
        return [{"action": "seer_divine", "target_id": target.id, "is_wolf": is_wolf}]


class HunterShootSkill(_BaseSkill):
    name = "hunter_shoot"
    owner_role = Role.HUNTER
    phase = Phase.HUNTER_SHOOT
    action_type = ActionType.SHOOT
    priority = 10
    can_execute_when_dead = True

    def validate(self, decision: Decision, state: GameState) -> bool:
        if not state.abilities.hunter_can_shoot:
            return False
        return super().validate(decision, state)

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        state.abilities.hunter_can_shoot = False
        target = state.player(decision.target_id or "")
        return [{"action": "hunter_shoot", "target_id": target.id, "target_name": target.name}]


class VillageTalkSkill(_BaseSkill):
    name = "talk"
    owner_role = Role.VILLAGER
    phase = Phase.DAY_SPEECH
    action_type = ActionType.TALK
    priority = 0
    requires_target = False

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        return []

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        return [{"action": "talk", "speech": getattr(decision, "speech", "") or ""}]

    def validate(self, decision: Decision, state: GameState) -> bool:
        actor = state.player(decision.actor_id)
        return actor.alive


class VillageVoteSkill(_BaseSkill):
    name = "vote"
    owner_role = Role.VILLAGER
    phase = Phase.DAY_VOTE
    action_type = ActionType.VOTE
    priority = 0

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        return [p.id for p in state.alive_players if p.id != actor.id]

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        return [{"action": "vote", "target_id": decision.target_id}]


class SkipActionSkill(_BaseSkill):
    name = "skip"
    owner_role = Role.VILLAGER
    phase = Phase.NIGHT_WITCH_ACTION
    action_type = ActionType.SKIP
    priority = 99
    requires_target = False
    can_target_self = True

    def legal_targets(self, state: GameState, actor: Player) -> list[str]:
        return []

    def apply(self, decision: Decision, state: GameState) -> list[dict[str, Any]]:
        return [{"action": "skip"}]

    def validate(self, decision: Decision, state: GameState) -> bool:
        return True


# ================================================================
# Registration
# ================================================================


def register_builtins(registry: SkillRegistry) -> None:
    """Register all built-in skills. Called once on first SkillRegistry.get()."""
    registry.register(GuardSkill())
    registry.register(WolfAttackSkill())
    registry.register(WitchSaveSkill())
    registry.register(WitchPoisonSkill())
    registry.register(SeerDivineSkill())
    registry.register(HunterShootSkill())
    registry.register(VillageTalkSkill())
    registry.register(VillageVoteSkill())
    registry.register(SkipActionSkill())
