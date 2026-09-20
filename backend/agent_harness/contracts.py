from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

if TYPE_CHECKING:
    from backend.agent_harness.events import HarnessEvent


@dataclass(frozen=True)
class HarnessBudget:
    """Hard limits enforced by the runtime rather than suggested to the model."""

    max_steps: int = 6
    max_tool_calls: int = 3
    max_skill_loads: int = 2
    max_output_tokens: int = 1200
    deadline_ms: int = 30_000

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_tool_calls < 0 or self.max_skill_loads < 0:
            raise ValueError("Harness step, tool, and skill budgets cannot be negative")
        if self.max_output_tokens < 1:
            raise ValueError("Harness output-token budget must be positive")
        if self.deadline_ms < 100:
            raise ValueError("Harness deadline must be at least 100ms")


@dataclass(frozen=True)
class ActorRef:
    actor_id: str
    agent_definition_id: str


@dataclass(frozen=True)
class DecisionPoint:
    """Domain-defined point at which an actor must select an action."""

    kind: str
    sequence: int
    schema_version: str = "1"
    simultaneous_group_id: str | None = None


@dataclass(frozen=True)
class InformationState:
    """The complete information legally available to one actor."""

    schema_id: str
    schema_version: str
    observation: dict[str, Any]
    visible_history: tuple[dict[str, Any], ...] = ()
    private_memory: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class MemoryScope:
    namespace: str
    episode_id: str
    actor_id: str


@dataclass(frozen=True)
class ActionOption:
    """A server-generated legal action and its model-supplied response schema."""

    option_id: str
    action_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] | None = None
    model_hint: str | None = None


@dataclass(frozen=True)
class ActionSpace:
    options: tuple[ActionOption, ...]

    def __post_init__(self) -> None:
        option_ids = [option.option_id for option in self.options]
        if not option_ids:
            raise ValueError("Action space must contain at least one legal option")
        if any(not option_id.strip() for option_id in option_ids):
            raise ValueError("Action option IDs cannot be empty")
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("Action option IDs must be unique")


@dataclass(frozen=True)
class DecisionRequest:
    """One actor-scoped decision emitted by an asymmetric-information environment."""

    request_id: str
    environment_id: str
    episode_id: str
    actor: ActorRef
    decision_point: DecisionPoint
    information_state: InformationState
    action_space: ActionSpace
    memory_scope: MemoryScope
    knowledge_context: tuple[dict[str, Any], ...] = ()
    skill_scope: frozenset[str] = field(default_factory=frozenset)
    tool_scope: frozenset[str] = field(default_factory=frozenset)
    policy_tags: frozenset[str] = field(default_factory=frozenset)
    agent_profile: dict[str, Any] = field(default_factory=dict)
    domain_metadata: dict[str, Any] = field(default_factory=dict)
    budget: HarnessBudget = field(default_factory=HarnessBudget)

    def __post_init__(self) -> None:
        if self.memory_scope.episode_id != self.episode_id:
            raise ValueError("Memory scope episode must match the decision request")
        if self.memory_scope.actor_id != self.actor.actor_id:
            raise ValueError("Memory scope actor must match the decision request")


@dataclass(frozen=True)
class SkillCall:
    name: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    ok: bool
    content: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class ActionSelection:
    """Untrusted model output. The environment-owned option supplies the action."""

    option_id: str
    response: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedAction:
    """Validated action returned to the environment."""

    option_id: str
    action_type: str
    parameters: dict[str, Any]
    response: dict[str, Any]
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessStep:
    kind: Literal["reflect", "load_skill", "tool", "select_action"]
    reflection: str | None = None
    skill_call: SkillCall | None = None
    tool_call: ToolCall | None = None
    action_selection: ActionSelection | None = None

    @classmethod
    def reflect(cls, reflection: str) -> HarnessStep:
        return cls(kind="reflect", reflection=reflection)

    @classmethod
    def load_skill(cls, name: str) -> HarnessStep:
        return cls(kind="load_skill", skill_call=SkillCall(name=name))

    @classmethod
    def call_tool(
        cls,
        call_id: str,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> HarnessStep:
        return cls(
            kind="tool",
            tool_call=ToolCall(call_id=call_id, name=name, arguments=dict(arguments or {})),
        )

    @classmethod
    def select_action(cls, selection: ActionSelection) -> HarnessStep:
        return cls(kind="select_action", action_selection=selection)


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    description: str


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    instructions: str


@dataclass(frozen=True)
class PlannerContext:
    """The complete model-visible harness surface for the next step."""

    step: int
    remaining_ms: int
    reflections: tuple[str, ...]
    skill_catalog: tuple[SkillDescriptor, ...]
    loaded_skills: tuple[LoadedSkill, ...]
    tool_schemas: tuple[dict[str, Any], ...]
    tool_results: tuple[ToolResult, ...]


@dataclass(frozen=True)
class HarnessResult:
    status: Literal["completed", "rejected", "failed"]
    action: ResolvedAction | None
    events: tuple[HarnessEvent, ...]
    loaded_skills: tuple[str, ...]
    tool_calls: int
    error: str | None = None
