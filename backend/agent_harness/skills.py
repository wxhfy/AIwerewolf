from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import LoadedSkill
from backend.agent_harness.contracts import SkillDescriptor
from backend.agent_harness.policy import PolicyViolation


@dataclass(frozen=True)
class Skill:
    """Trusted instructions advertised by metadata and loaded only on demand."""

    name: str
    description: str
    instructions: str
    environment_ids: frozenset[str] = field(default_factory=frozenset)
    decision_kinds: frozenset[str] = field(default_factory=frozenset)
    required_policy_tags: frozenset[str] = field(default_factory=frozenset)
    model_invocable: bool = True
    trusted: bool = True
    priority: int = 0

    def visible_for(self, request: DecisionRequest) -> bool:
        return (
            self.trusted
            and self.model_invocable
            and self.name in request.skill_scope
            and (not self.environment_ids or request.environment_id in self.environment_ids)
            and (not self.decision_kinds or request.decision_point.kind in self.decision_kinds)
            and self.required_policy_tags.issubset(request.policy_tags)
        )


class SkillRegistry:
    """Provides progressive disclosure without exposing storage to the model."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Duplicate skill: {skill.name}")
        if not skill.name.strip() or not skill.description.strip() or not skill.instructions.strip():
            raise ValueError("Skill name, description, and instructions are required")
        self._skills[skill.name] = skill

    def catalog(self, request: DecisionRequest) -> tuple[SkillDescriptor, ...]:
        visible = [skill for skill in self._skills.values() if skill.visible_for(request)]
        visible.sort(key=lambda item: (-item.priority, item.name))
        return tuple(SkillDescriptor(name=skill.name, description=skill.description) for skill in visible)

    def load(self, name: str, request: DecisionRequest) -> LoadedSkill:
        skill = self._skills.get(name)
        if skill is None or not skill.visible_for(request):
            raise PolicyViolation(f"Skill is not available for this request: {name}")
        return LoadedSkill(name=skill.name, instructions=skill.instructions)
