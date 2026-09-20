import pytest

from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSelection
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import AgentHarness
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import HarnessBudget
from backend.agent_harness import HarnessSession
from backend.agent_harness import HarnessStep
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.agent_harness import Skill
from backend.agent_harness import SkillRegistry
from backend.agent_harness import ToolGateway
from backend.agent_harness import ToolSpec
from backend.agent_harness.policy import CapabilityPolicy


def _request(
    *,
    environment_id: str = "social-deduction",
    decision_kind: str = "public.vote",
    options: tuple[ActionOption, ...] | None = None,
    max_steps: int = 5,
    skill_scope: frozenset[str] = frozenset({"social-reasoning/evidence"}),
    tool_scope: frozenset[str] = frozenset({"inspect_visible_history"}),
) -> DecisionRequest:
    return DecisionRequest(
        request_id="request-1234",
        environment_id=environment_id,
        episode_id="episode-1",
        actor=ActorRef(actor_id="actor-1", agent_definition_id="logical-agent"),
        decision_point=DecisionPoint(kind=decision_kind, sequence=4),
        information_state=InformationState(
            schema_id=f"{environment_id}.information-state",
            schema_version="1",
            observation={"public": {"round": 2}, "private": {"clue": "actor-2 is hostile"}},
            visible_history=({"type": "statement", "actor_id": "actor-2"},),
        ),
        action_space=ActionSpace(
            options=options
            or (
                ActionOption(option_id="vote:actor-2", action_type="vote", parameters={"target_id": "actor-2"}),
                ActionOption(option_id="vote:actor-3", action_type="vote", parameters={"target_id": "actor-3"}),
            )
        ),
        memory_scope=MemoryScope(namespace="episode", episode_id="episode-1", actor_id="actor-1"),
        skill_scope=skill_scope,
        tool_scope=tool_scope,
        domain_metadata={"role": "oracle", "faction": "citizens"},
        budget=HarnessBudget(max_steps=max_steps, max_tool_calls=1, max_skill_loads=1),
    )


def _event_types(result) -> list[str]:
    return [event.event_type for event in result.events]


def test_harness_loads_scoped_skill_calls_safe_tool_and_resolves_action() -> None:
    class Planner:
        def next_step(self, request, context):
            assert [skill.name for skill in context.skill_catalog] == ["social-reasoning/evidence"]
            assert [tool["name"] for tool in context.tool_schemas] == ["inspect_visible_history"]
            if not context.loaded_skills:
                return HarnessStep.load_skill("social-reasoning/evidence")
            if not context.tool_results:
                return HarnessStep.call_tool("call-1", "inspect_visible_history")
            return HarnessStep.select_action(ActionSelection(option_id="vote:actor-2"))

    def inspect_history(context, arguments):
        del arguments
        assert context.actor.actor_id == "actor-1"
        assert context.information_state.visible_history[0]["actor_id"] == "actor-2"
        return {"suspicious": ["actor-2"]}

    harness = AgentHarness(
        Planner(),
        skills=SkillRegistry(
            [
                Skill(
                    name="social-reasoning/evidence",
                    description="Compare visible claims and evidence.",
                    instructions="Prefer claims supported by actor-visible evidence.",
                    decision_kinds=frozenset({"public.vote"}),
                    priority=10,
                )
            ]
        ),
        tools=ToolGateway(
            [
                ToolSpec(
                    name="inspect_visible_history",
                    description="Summarize events already visible to the actor.",
                    input_schema={"type": "object", "properties": {}},
                    handler=inspect_history,
                    capabilities=frozenset({"actor_information_state"}),
                )
            ]
        ),
        policy=CapabilityPolicy(allowed_tools=frozenset({"inspect_visible_history"})),
    )

    result = harness.run(_request())

    assert result.status == "completed"
    assert result.action is not None
    assert result.action.action_type == "vote"
    assert result.action.parameters == {"target_id": "actor-2"}
    assert result.loaded_skills == ("social-reasoning/evidence",)
    assert _event_types(result).index("tool.call") < _event_types(result).index("tool.result")
    started = result.events[0].to_record()["payload"]
    assert started["request"]["environment_id"] == "social-deduction"
    assert started["request"]["domain_metadata"]["role"] == "oracle"


def test_harness_can_reflect_before_selecting_an_action() -> None:
    class Planner:
        def next_step(self, request, context):
            del request
            if not context.reflections:
                return HarnessStep.reflect("Compare the two public vote histories.")
            assert context.reflections == ("Compare the two public vote histories.",)
            return HarnessStep.select_action(ActionSelection(option_id="vote:actor-2"))

    result = AgentHarness(Planner()).run(
        _request(max_steps=2, skill_scope=frozenset(), tool_scope=frozenset())
    )

    assert result.status == "completed"
    assert result.action is not None
    assert "planner.reflected" in _event_types(result)


def test_same_harness_contract_supports_different_hidden_information_domains() -> None:
    class FirstOptionPlanner:
        def next_step(self, request, context):
            del context
            return HarnessStep.select_action(ActionSelection(option_id=request.action_space.options[0].option_id))

    harness = AgentHarness(FirstOptionPlanner())
    social_result = harness.run(_request(skill_scope=frozenset(), tool_scope=frozenset()))
    auction_result = harness.run(
        _request(
            environment_id="sealed-auction",
            decision_kind="auction.submit-bid",
            options=(
                ActionOption(option_id="bid:10", action_type="submit_bid", parameters={"amount": 10}),
                ActionOption(option_id="bid:20", action_type="submit_bid", parameters={"amount": 20}),
            ),
            skill_scope=frozenset(),
            tool_scope=frozenset(),
        )
    )

    assert social_result.action is not None
    assert social_result.action.parameters == {"target_id": "actor-2"}
    assert auction_result.action is not None
    assert auction_result.action.parameters == {"amount": 10}


def test_skill_body_is_not_eagerly_exposed_and_scope_is_authoritative() -> None:
    secret_body = "Detailed strategy instructions."

    class Planner:
        def next_step(self, request, context):
            assert context.skill_catalog == ()
            assert secret_body not in repr(context)
            return HarnessStep.select_action(ActionSelection(option_id="vote:actor-2"))

    result = AgentHarness(
        Planner(),
        skills=SkillRegistry([Skill(name="out-of-scope", description="Hidden skill.", instructions=secret_body)]),
    ).run(_request(skill_scope=frozenset()))

    assert result.status == "completed"
    assert result.loaded_skills == ()


def test_harness_hides_database_tool_even_when_deployment_allowlists_it() -> None:
    class Planner:
        def next_step(self, request, context):
            assert context.tool_schemas == ()
            return HarnessStep.call_tool("db-1", "query_database", {"sql": "select * from hidden_state"})

    harness = AgentHarness(
        Planner(),
        tools=ToolGateway(
            [
                ToolSpec(
                    name="query_database",
                    description="Unsafe raw database access.",
                    input_schema={"type": "object"},
                    handler=lambda context, arguments: {},
                    capabilities=frozenset({"database", "sql", "environment_truth"}),
                )
            ]
        ),
        policy=CapabilityPolicy(allowed_tools=frozenset({"query_database"})),
    )

    result = harness.run(_request(tool_scope=frozenset({"query_database"})))

    assert result.status == "rejected"
    assert "not allowed" in str(result.error)
    types = _event_types(result)
    assert types.index("tool.call") < types.index("tool.result") < types.index("run.rejected")


def test_harness_rejects_option_not_generated_by_environment() -> None:
    class Planner:
        def next_step(self, request, context):
            del request, context
            return HarnessStep.select_action(ActionSelection(option_id="vote:actor-9"))

    result = AgentHarness(Planner()).run(_request(skill_scope=frozenset(), tool_scope=frozenset()))

    assert result.status == "rejected"
    assert result.error == "Illegal action option: vote:actor-9"
    assert "action.proposed" in _event_types(result)
    assert "action.accepted" not in _event_types(result)


def test_open_action_response_is_validated_against_environment_schema() -> None:
    speak = ActionOption(
        option_id="speak",
        action_type="speak",
        response_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    class Planner:
        def next_step(self, request, context):
            del request, context
            return HarnessStep.select_action(ActionSelection(option_id="speak", response={"text": ""}))

    result = AgentHarness(Planner()).run(_request(options=(speak,), skill_scope=frozenset(), tool_scope=frozenset()))

    assert result.status == "rejected"
    assert result.error == "Response field 'text' is too short"


def test_harness_fails_when_step_budget_is_exhausted() -> None:
    class Planner:
        def next_step(self, request, context):
            del request, context
            return HarnessStep.load_skill("social-reasoning/evidence")

    result = AgentHarness(
        Planner(),
        skills=SkillRegistry(
            [
                Skill(
                    name="social-reasoning/evidence",
                    description="One skill.",
                    instructions="One body.",
                )
            ]
        ),
    ).run(_request(max_steps=1, tool_scope=frozenset()))

    assert result.status == "failed"
    assert result.error == "Harness step budget exhausted"


def test_session_events_are_append_only_and_payloads_are_immutable() -> None:
    session = HarnessSession()
    source = {"nested": {"value": 1}}

    event = session.append("test", step=0, payload=source)
    source["nested"]["value"] = 2

    assert event.payload["nested"]["value"] == 1
    with pytest.raises(TypeError):
        event.payload["new"] = "value"
    with pytest.raises(TypeError):
        event.payload["nested"]["value"] = 3
    assert event.to_record()["payload"] == {"nested": {"value": 1}}
