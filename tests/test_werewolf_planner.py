import json

from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import AgentHarness
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import HarnessBudget
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.agent_harness import PlannerContext
from backend.domains.werewolf.capabilities import EVIDENCE_TOOL
from backend.domains.werewolf.capabilities import build_capability_policy
from backend.domains.werewolf.capabilities import build_tool_gateway
from backend.domains.werewolf.context import project_agent_profile_v1
from backend.domains.werewolf.planner import LLMActionPlanner


class RepairingClient:
    model = "test-model"
    provider = "test-provider"

    def __init__(self) -> None:
        self.calls = []

    def chat_sync(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        content = "not json" if len(self.calls) == 1 else '{"option_id":"vote:P2","response":{},"reasoning":"repaired"}'
        return {"choices": [{"message": {"content": content}}], "usage": {}}


def test_profile_projection_exposes_soft_behavior_without_runtime_config() -> None:
    projected = project_agent_profile_v1(
        {
            "internal_runtime_config": "must not pass",
            "persona": {
                "name": "Analyst",
                "mbti": "INTJ",
                "style_label": "analytical",
                "reasoning_style": "对比前后发言的细节矛盾",
                "logic_style": "证据链 + 时间线核对",
                "speech_length_habit": "简洁有力",
                "social_habit": "独立分析，不轻易跟票",
                "courage": "cautious",
                "memory_bias": "recent",
                "suspicion_threshold": "high",
                "self_protection": "passive",
                "logic_depth": "deep",
                "trigger_topics": ["票型异常"],
                "mistake_pattern": "过度自信",
            },
        }
    )

    persona = projected["persona"]
    behavior = projected["behavior"]
    assert persona["mbti"] == "INTJ"
    assert persona["logic_style"] == "证据链 + 时间线核对"
    assert persona["trigger_topics"] == ["票型异常"]
    assert "internal_runtime_config" not in json.dumps(projected, ensure_ascii=False)
    assert behavior["decision_style"]["risk_tolerance"] < 0.5
    assert behavior["cognitive_bias"]["contradiction_sensitivity"] > 0.8
    assert behavior["conversation_style"]["must_reference_recent_evidence"] is True


class CanonicalModelClient:
    model = "portable-model"
    provider = "portable-provider"
    supports_tool_calling = False

    def complete(self, messages, **kwargs):
        return {
            "choices": [
                {"message": {"content": '{"option_id":"vote:P2","response":{},"reasoning":"portable"}'}}
            ],
            "usage": {},
        }


def test_planner_uses_provider_neutral_complete_contract() -> None:
    request = DecisionRequest(
        request_id="request-portable",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    step = LLMActionPlanner(CanonicalModelClient()).next_step(request, PlannerContext(1, 2500, (), (), (), (), ()))
    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"



def test_planner_repairs_invalid_json_once_with_remaining_deadline() -> None:
    request = DecisionRequest(
        request_id="request-1",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        budget=HarnessBudget(max_steps=1, deadline_ms=3000),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )
    client = RepairingClient()

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.metadata["repair_used"] is True
    assert len(client.calls) == 2
    assert client.calls[1][1]["request_timeout_seconds"] <= client.calls[0][1]["request_timeout_seconds"]


def test_planner_drops_response_payload_for_closed_action() -> None:
    client = RepairingClient()
    client.chat_sync = lambda messages, **kwargs: {
        "choices": [{"message": {"content": '{"option_id":"vote:P2","response":{"extra":true},"reasoning":"vote"}'}}],
        "usage": {},
    }
    request = DecisionRequest(
        request_id="request-2",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.response == {}


def test_planner_recovers_legal_option_from_truncated_json() -> None:
    client = RepairingClient()
    client.chat_sync = lambda messages, **kwargs: {
        "choices": [
            {"message": {"content": '{"option_id":"vote:P2","response":{"speech":"unneeded"},"reasoning":"truncated'}}
        ],
        "usage": {},
    }
    request = DecisionRequest(
        request_id="request-truncated",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(1, 2500, (), (), (), (), ())

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.response == {}
    assert step.action_selection.metadata["syntax_recovered"] is True
    assert step.action_selection.metadata["fallback_used"] is False


def test_planner_falls_back_when_model_times_out() -> None:
    client = RepairingClient()

    def timeout(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    client.chat_sync = timeout
    request = DecisionRequest(
        request_id="request-3",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.metadata["fallback_used"] is True
    assert "TimeoutError" in step.action_selection.metadata["fallback_error"]


def test_planner_uses_tool_call_when_client_supports_it() -> None:
    client = RepairingClient()
    client.supports_tool_calling = True

    def tool_call(messages, **kwargs):
        assert kwargs["tools"][0]["function"]["name"] == "submit_action"
        assert kwargs["tool_choice"]["function"]["name"] == "submit_action"
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "submit_action",
                                    "arguments": '{"option_id":"vote:P2","response":{"ignored":true},"reasoning":"tool"}',
                                }
                            }
                        ],
                    }
                }
            ],
            "usage": {},
        }

    client.chat_sync = tool_call
    request = DecisionRequest(
        request_id="request-4",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P2"
    assert step.action_selection.response == {}
    assert step.action_selection.metadata["fallback_used"] is False


def test_fallback_uses_subjective_beliefs_instead_of_first_option() -> None:
    client = RepairingClient()

    def timeout(*args, **kwargs):
        raise TimeoutError("upstream timeout")

    client.chat_sync = timeout
    request = DecisionRequest(
        request_id="request-5",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={},
            private_memory=(
                {
                    "beliefs": [
                        {"player_id": "P2", "wolf_probability": 0.2, "confidence": 0.8},
                        {"player_id": "P3", "wolf_probability": 0.9, "confidence": 0.7},
                    ]
                },
            ),
        ),
        action_space=ActionSpace(
            options=(
                ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),
                ActionOption(option_id="vote:P3", action_type="vote", parameters={"target_id": "P3"}),
            )
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P3"


def test_wolf_fallback_never_targets_known_teammate() -> None:
    client = RepairingClient()
    client.chat_sync = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("upstream timeout"))
    request = DecisionRequest(
        request_id="request-wolf-fallback",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={
                "known_wolves": [{"id": "P2", "name": "队友"}],
                "players": [{"id": "P2", "name": "队友"}, {"id": "P3", "name": "村民"}],
            },
            private_memory=(
                {
                    "beliefs": [
                        {"player_id": "P2", "wolf_probability": 1.0, "confidence": 1.0},
                        {"player_id": "P3", "wolf_probability": 0.6, "confidence": 0.4},
                    ]
                },
            ),
        ),
        action_space=ActionSpace(
            options=(
                ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),
                ActionOption(option_id="vote:P3", action_type="vote", parameters={"target_id": "P3"}),
            )
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        domain_metadata={"role": "Werewolf"},
    )
    context = PlannerContext(1, 2500, (), (), (), (), ())

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    assert step.action_selection.option_id == "vote:P3"


def test_public_speech_leak_is_rewritten_and_flagged() -> None:
    client = RepairingClient()
    client.chat_sync = lambda messages, **kwargs: {
        "choices": [
            {
                "message": {
                    "content": '{"option_id":"talk","response":{"speech":"昨晚我们狼队决定攻击 P3，P3 的狼人概率是 0.82"},"reasoning":"private"}'
                }
            }
        ],
        "usage": {},
    }
    request = DecisionRequest(
        request_id="request-speech-policy",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.talk", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={
                "known_wolves": [{"id": "P2", "name": "队友"}],
                "players": [{"id": "P2", "name": "队友"}, {"id": "P3", "name": "小明"}],
            },
            private_memory=({"beliefs": [{"player_id": "P3", "wolf_probability": 0.7, "confidence": 0.4}]},),
        ),
        action_space=ActionSpace(
            options=(
                ActionOption(
                    option_id="talk",
                    action_type="talk",
                    response_schema={
                        "type": "object",
                        "properties": {"speech": {"type": "string"}},
                        "required": ["speech"],
                    },
                ),
            )
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        domain_metadata={"role": "Werewolf"},
    )
    context = PlannerContext(1, 2500, (), (), (), (), ())

    step = LLMActionPlanner(client).next_step(request, context)

    assert step.action_selection is not None
    speech = step.action_selection.response["speech"]
    assert "狼队" not in speech
    assert "0.82" not in speech
    assert "P3" not in speech
    assert step.action_selection.metadata["speech_rewritten"] is True
    assert set(step.action_selection.metadata["speech_policy_violations"]) == {
        "internal_score_disclosure",
        "wolf_private_perspective",
    }


def test_prompt_payload_describes_context_layers_and_loaded_capabilities() -> None:
    request = DecisionRequest(
        request_id="request-context",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={
                "self_player": {"id": "P1", "name": "Actor", "role": "Villager"},
                "players": [{"id": "P1", "name": "Actor"}, {"id": "P2", "name": "Speaker"}],
            },
            visible_history=tuple(
                {
                    "seq": index,
                    "day": 1,
                    "type": "CHAT_MESSAGE",
                    "visibility": "public",
                    "payload": {"actor_id": "P2", "actor_name": "Speaker", "speech": f"statement {index}"},
                }
                for index in range(16)
            ),
            private_memory=(
                {
                    "beliefs": [
                        {
                            "player_id": "P2",
                            "wolf_probability": 0.8,
                            "confidence": 0.7,
                            "evidence_for": ["P2 contradicted a vote commitment"],
                        }
                    ],
                    "relationships": [
                        {
                            "player_id": "P2",
                            "trust": -0.4,
                            "closeness": 0.0,
                            "threat": 0.6,
                            "influence": 0.2,
                            "perceived_attitude": -0.5,
                            "last_updated_seq": 11,
                        }
                    ],
                    "working_memory": ["P2 changed their vote stance after being challenged."],
                    "retrieved_episodes": [
                        {
                            "memory_id": "event-3",
                            "event_seq": 3,
                            "day": 1,
                            "phase": "DAY_TALK",
                            "kind": "chat_message",
                            "source": "public",
                            "content": "P2 said they would vote for P3.",
                            "actor_ids": ["P2"],
                            "tags": ["speech"],
                        }
                    ],
                    "affect": {
                        "confidence": 0.72,
                        "social_pressure": 0.55,
                        "fear": 0.2,
                        "anger": 0.1,
                        "arousal": 0.4,
                        "valence": -0.2,
                    },
                    "active_goals": [{"description": "Resolve whether P2's claim is credible."}],
                    "recent_claims": [
                        {
                            "claim_id": "claim-stance-1",
                            "event_seq": 11,
                            "speaker_id": "P3",
                            "kind": "stance",
                            "target_id": "P2",
                            "value": "suspicious",
                            "polarity": 0.7,
                            "confidence": 0.62,
                            "evidence_text": "P2 changed their vote stance after being challenged.",
                            "contradicted": False,
                            "retracted": False,
                        },
                        {
                            "claim_id": "claim-1",
                            "event_seq": 12,
                            "speaker_id": "P2",
                            "kind": "check_claim",
                            "target_id": "P1",
                            "value": "village",
                            "polarity": -1.0,
                            "confidence": 0.82,
                            "evidence_text": "I checked P1; P1 is not a wolf.",
                            "contradicted": False,
                            "retracted": False,
                        },
                    ],
                },
            ),
        ),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        agent_profile={
            "harness_mode": "direct",
            "internal_runtime_config": "must not be forwarded",
            "persona": {
                "style_label": "analytical",
                "logic_depth": "deep",
                "speech_length_habit": "short_and_punchy",
            },
        },
    )
    context = PlannerContext(
        step=1,
        remaining_ms=2500,
        reflections=(),
        skill_catalog=(),
        loaded_skills=(),
        tool_schemas=(),
        tool_results=(),
    )

    payload = LLMActionPlanner._prompt_payload(request, context)

    assert payload["context_manifest"]["schema_version"] == "werewolf.decision_context.v1"
    assert payload["context_manifest"]["included"]["public_timeline"] == 14
    assert payload["context_manifest"]["layers"][-1] == "current_task"
    assert "capabilities" not in payload
    decision_context = payload["decision_context"]
    assert decision_context["schema"] == "werewolf.decision_context.v1"
    assert decision_context["inferences"][0]["player_id"] == "P2"
    assert decision_context["inferences"][0]["epistemic_status"] == "fallible_actor_inference"
    inference = decision_context["inferences"][0]
    assert inference["supporting_evidence"][0]["event_seq"] == 11
    assert inference["supporting_evidence"][0]["epistemic_status"] == "attributed_claim_not_confirmed_fact"
    claim = next(item for item in decision_context["public_claims"] if item["claim_type"] == "check_claim")
    assert claim["speaker_id"] == "P2"
    assert claim["epistemic_status"] == "speaker_claim_not_actor_fact"
    assert any(item["claim_type"] == "stance" for item in decision_context["public_claims"])
    assert decision_context["agent_state"]["attention_focus"] == [
        "P2 changed their vote stance after being challenged."
    ]
    assert decision_context["agent_state"]["recalled_episodes"][0]["event_id"] == "event-3"
    assert decision_context["agent_state"]["social_reads"][0]["attitude"] == "guarded"
    assert decision_context["agent_state"]["affect"]["confidence"] == "high"
    assert payload["agent_profile"]["persona"]["style_label"] == "analytical"
    assert "internal_runtime_config" not in json.dumps(payload, ensure_ascii=False)
    assert not any(fact.get("kind") == "seer_result" for fact in decision_context["confirmed_private_facts"])
    assert "information_state" not in payload
    assert "strategy_state" not in payload
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "working_memory" not in decision_context["agent_state"]
    assert "evidence_graph" not in serialized
    assert "wolf_probability" not in serialized

    class CapturingClient:
        model = "test-model"
        provider = "test-provider"

        def __init__(self) -> None:
            self.messages = []

        def chat_sync(self, messages, **kwargs):
            self.messages = messages
            return {
                "choices": [{"message": {"content": '{"option_id":"vote:P2","response":{},"reasoning":"vote"}'}}],
                "usage": {},
            }

    client = CapturingClient()
    LLMActionPlanner(client).next_step(request, context)
    assert "Use agent_profile.persona" in client.messages[0]["content"]


def test_llm_planner_can_call_actor_scoped_evidence_tool_then_submit_action() -> None:
    class ToolClient:
        model = "test-model"
        provider = "test-provider"
        supports_tool_calling = True

        def __init__(self) -> None:
            self.calls = 0

        def chat_sync(self, messages, **kwargs):
            self.calls += 1
            tool_names = [item["function"]["name"] for item in kwargs["tools"]]
            if self.calls == 1:
                assert EVIDENCE_TOOL in tool_names
                assert kwargs["tool_choice"] == "auto"
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "inspect-1",
                                        "function": {
                                            "name": EVIDENCE_TOOL,
                                            "arguments": '{"player_id":"P2"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {},
                }
            assert EVIDENCE_TOOL in messages[1]["content"]
            assert EVIDENCE_TOOL not in tool_names
            assert kwargs["tool_choice"]["function"]["name"] == "submit_action"
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "submit-1",
                                    "function": {
                                        "name": "submit_action",
                                        "arguments": '{"option_id":"vote:P2","response":{},"reasoning":"evidence"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            }

    request = DecisionRequest(
        request_id="request-tool-loop",
        environment_id="werewolf",
        episode_id="game-1",
        actor=ActorRef(actor_id="P1", agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(
            schema_id="test",
            schema_version="1",
            observation={
                "self_player": {"id": "P1"},
                "players": [{"id": "P1"}, {"id": "P2"}],
            },
            private_memory=(
                {
                    "beliefs": [{"player_id": "P2", "wolf_probability": 0.8, "confidence": 0.7}],
                    "relationships": [],
                    "recent_claims": [],
                    "evidence_graph": [],
                },
            ),
        ),
        action_space=ActionSpace(
            options=(ActionOption(option_id="vote:P2", action_type="vote", parameters={"target_id": "P2"}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id="game-1", actor_id="P1"),
        tool_scope=frozenset({EVIDENCE_TOOL}),
        policy_tags=frozenset({"role-safe-view"}),
        budget=HarnessBudget(max_steps=2, max_tool_calls=1, max_skill_loads=0, deadline_ms=3000),
    )
    client = ToolClient()
    result = AgentHarness(
        LLMActionPlanner(client),
        tools=build_tool_gateway(),
        policy=build_capability_policy(),
    ).run(request)

    assert result.status == "completed"
    assert result.action is not None
    assert result.action.option_id == "vote:P2"
    assert result.tool_calls == 1
    assert client.calls == 2
