from __future__ import annotations

from dataclasses import dataclass

from backend.engine.models import ActionType
from backend.engine.models import Decision
from backend.engine.models import GameState
from backend.engine.models import Role


@dataclass(frozen=True)
class ActionRule:
    action_type: ActionType
    actor_roles: tuple[Role, ...]
    requires_target: bool = True
    alive_actor_required: bool = True


ACTION_RULES: dict[ActionType, ActionRule] = {
    ActionType.TALK: ActionRule(ActionType.TALK, tuple(Role), requires_target=False),
    ActionType.VOTE: ActionRule(ActionType.VOTE, tuple(Role)),
    ActionType.ATTACK: ActionRule(ActionType.ATTACK, (Role.WEREWOLF, Role.WHITE_WOLF_KING)),
    ActionType.BOOM: ActionRule(ActionType.BOOM, (Role.WHITE_WOLF_KING,), alive_actor_required=True),
    ActionType.DIVINE: ActionRule(ActionType.DIVINE, (Role.SEER,)),
    ActionType.GUARD: ActionRule(ActionType.GUARD, (Role.GUARD,)),
    ActionType.WITCH_SAVE: ActionRule(ActionType.WITCH_SAVE, (Role.WITCH,)),
    ActionType.WITCH_POISON: ActionRule(ActionType.WITCH_POISON, (Role.WITCH,)),
    ActionType.SHOOT: ActionRule(ActionType.SHOOT, (Role.HUNTER,), alive_actor_required=False),
    ActionType.SKIP: ActionRule(ActionType.SKIP, tuple(Role), requires_target=False, alive_actor_required=False),
}


class ActionValidator:
    def validate(self, state: GameState, decision: Decision) -> bool:
        rule = ACTION_RULES[decision.action_type]
        actor = state.player(decision.actor_id)
        if rule.alive_actor_required and not actor.alive:
            return False
        if actor.role not in rule.actor_roles:
            return False
        if decision.action_type == ActionType.VOTE and actor.role == Role.IDIOT and state.abilities.idiot_revealed:
            return False
        if rule.requires_target:
            if decision.target_id is None:
                return False
            try:
                target = state.player(decision.target_id)
            except KeyError:
                return False
            if not target.alive:
                return False
            if target.id == actor.id and decision.action_type in {
                ActionType.VOTE,
                ActionType.ATTACK,
                ActionType.DIVINE,
                ActionType.WITCH_POISON,
                ActionType.SHOOT,
            }:
                return False
        return True
