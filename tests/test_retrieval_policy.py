from __future__ import annotations

from typing import Any

from backend.agents.cognitive.agent_loop import AgentLoop
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import PlayerInfo
from backend.agents.cognitive.retrieval_prod import AgentContext
from backend.agents.cognitive.retrieval_prod import RetrievalPolicy
from backend.agents.cognitive.retrieval_prod import StrategyRetriever
from backend.agents.cognitive.tools import create_tools
from backend.agents.factory import _resolve_retrieval_policy


def _docs() -> list[dict[str, Any]]:
    return [
        {
            "doc_id": "global-check",
            "situation": "查杀 表水 通用",
            "strategy": "通用查杀表水策略",
            "role": "global",
            "phase": "DAY_SPEECH",
            "quality": 0.90,
        },
        {
            "doc_id": "seer-intj",
            "situation": "查杀 表水 预言家",
            "strategy": "INTJ 预言家查杀表水策略",
            "role": "Seer",
            "phase": "DAY_SPEECH",
            "quality": 0.95,
            "persona_scope": "mbti:INTJ+role:Seer",
        },
        {
            "doc_id": "seer-enfp",
            "situation": "查杀 表水 预言家",
            "strategy": "ENFP 预言家查杀表水策略",
            "role": "Seer",
            "phase": "DAY_SPEECH",
            "quality": 0.94,
            "persona_scope": "mbti:ENFP+role:Seer",
        },
        {
            "doc_id": "wolf-intj",
            "situation": "查杀 表水 狼人",
            "strategy": "INTJ 狼人抗推策略",
            "role": "Werewolf",
            "phase": "DAY_SPEECH",
            "quality": 0.93,
            "persona_scope": "mbti:INTJ+role:Werewolf",
        },
    ]


def _retriever() -> StrategyRetriever:
    retriever = StrategyRetriever()
    assert retriever.build_from_docs(_docs()) == 4
    return retriever


def _ctx(mbti: str = "INTJ") -> AgentContext:
    return AgentContext(role="Seer", phase="DAY_SPEECH", mbti=mbti, alignment="village")


def test_hybrid_policy_keeps_global_in_global_bucket() -> None:
    results = _retriever().search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.HYBRID_ROLE_MBTI_GLOBAL,
        agent_context=_ctx("INTJ"),
    )

    by_id = {item["doc_id"]: item for item in results}
    assert list(by_id) == ["seer-intj", "global-check"]
    assert by_id["seer-intj"]["bucket"] == "same_role_same_mbti"
    assert by_id["global-check"]["bucket"] == "global"


def test_hybrid_policy_allows_cross_mbti_role_fill_only_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("TRACK_C_ALLOW_CROSS_MBTI_ROLE_FILL", "1")

    results = _retriever().search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.HYBRID_ROLE_MBTI_GLOBAL,
        agent_context=_ctx("INTJ"),
    )

    by_id = {item["doc_id"]: item for item in results}
    assert list(by_id) == ["seer-intj", "seer-enfp", "global-check"]
    assert by_id["seer-enfp"]["bucket"] == "same_role_all_mbti"


def test_hybrid_policy_uses_role_generic_docs_without_cross_mbti() -> None:
    retriever = StrategyRetriever()
    assert (
        retriever.build_from_docs(
            [
                {
                    "doc_id": "seer-intj",
                    "situation": "查杀 表水 预言家",
                    "strategy": "INTJ 预言家策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.95,
                    "persona_scope": "mbti:INTJ+role:Seer",
                },
                {
                    "doc_id": "seer-generic",
                    "situation": "查杀 表水 预言家",
                    "strategy": "通用预言家策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.94,
                },
                {
                    "doc_id": "seer-enfp",
                    "situation": "查杀 表水 预言家",
                    "strategy": "ENFP 预言家策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.93,
                    "persona_scope": "mbti:ENFP+role:Seer",
                },
            ]
        )
        == 3
    )

    results = retriever.search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.HYBRID_ROLE_MBTI_GLOBAL,
        agent_context=_ctx("INTJ"),
    )

    assert [item["doc_id"] for item in results] == ["seer-intj", "seer-generic"]
    assert results[1]["bucket"] == "same_role_all_mbti"


def test_hybrid_policy_prefers_validated_canonical_later_strategy_version() -> None:
    retriever = StrategyRetriever()
    assert (
        retriever.build_from_docs(
            [
                {
                    "doc_id": "seer-v1",
                    "situation": "查杀 表水 预言家",
                    "strategy": "旧版预言家查杀表水策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.95,
                    "confidence": 0.85,
                    "knowledge_epoch": 1,
                    "doc_version": "seer_v1",
                    "maturity": "refined",
                    "validated_at": "2026-05-20T00:00:00+00:00",
                },
                {
                    "doc_id": "seer-v3",
                    "situation": "查杀 表水 预言家",
                    "strategy": "新版预言家查杀表水策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.90,
                    "confidence": 0.88,
                    "knowledge_epoch": 3,
                    "doc_version": "seer_v3",
                    "maturity": "canonical",
                    "validated_at": "2026-06-08T00:00:00+00:00",
                },
            ]
        )
        == 2
    )

    results = retriever.search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=2,
        retrieval_policy=RetrievalPolicy.SAME_ROLE_ALL_MBTI,
        agent_context=_ctx("INTJ"),
    )

    assert [item["doc_id"] for item in results] == ["seer-v3", "seer-v1"]
    assert results[0]["maturity"] == "canonical"
    assert results[0]["knowledge_epoch"] == 3
    assert results[0]["strategy_rank_score"] > results[1]["strategy_rank_score"]


def test_hybrid_alignment_phase_rejects_cross_mbti_alignment_fill() -> None:
    retriever = StrategyRetriever()
    assert (
        retriever.build_from_docs(
            [
                {
                    "doc_id": "witch-enfp",
                    "situation": "查杀 表水 女巫",
                    "strategy": "ENFP 女巫阵营经验",
                    "role": "Witch",
                    "phase": "DAY_SPEECH",
                    "quality": 0.95,
                    "persona_scope": "mbti:ENFP+role:Witch",
                },
                {
                    "doc_id": "village-generic",
                    "situation": "查杀 表水 好人阵营",
                    "strategy": "好人阵营通用经验",
                    "role": "Witch",
                    "phase": "DAY_SPEECH",
                    "quality": 0.93,
                },
                {
                    "doc_id": "global-check",
                    "situation": "查杀 表水 通用",
                    "strategy": "通用查杀表水策略",
                    "role": "global",
                    "phase": "DAY_SPEECH",
                    "quality": 0.90,
                },
            ]
        )
        == 3
    )

    results = retriever.search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.HYBRID_ROLE_ALIGNMENT_PHASE,
        agent_context=_ctx("INTJ"),
    )

    by_id = {item["doc_id"]: item for item in results}
    assert "witch-enfp" not in by_id
    assert by_id["village-generic"]["bucket"] == "same_alignment_all_mbti"
    assert by_id["global-check"]["bucket"] == "global"


def test_same_role_same_mbti_bm25_returns_empty_without_matching_mbti() -> None:
    results = _retriever().search(
        "查杀 表水",
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.SAME_ROLE_SAME_MBTI,
        agent_context=_ctx("ISTJ"),
    )

    assert results == []


def test_hybrid_policy_does_not_fill_low_quality_docs_by_default() -> None:
    retriever = StrategyRetriever()
    assert (
        retriever.build_from_docs(
            [
                {
                    "doc_id": "seer-good",
                    "situation": "查杀 表水 预言家",
                    "strategy": "高质量预言家策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.95,
                    "persona_scope": "mbti:INTJ+role:Seer",
                },
                {
                    "doc_id": "seer-noisy",
                    "situation": "查杀 表水 预言家",
                    "strategy": "低质量噪声策略",
                    "role": "Seer",
                    "phase": "DAY_SPEECH",
                    "quality": 0.2,
                    "persona_scope": "mbti:ENFP+role:Seer",
                },
                {
                    "doc_id": "global-noisy",
                    "situation": "查杀 表水 通用",
                    "strategy": "低质量通用噪声",
                    "role": "global",
                    "phase": "DAY_SPEECH",
                    "quality": 0.1,
                },
            ]
        )
        == 3
    )

    results = retriever.search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.HYBRID_ROLE_MBTI_GLOBAL,
        agent_context=_ctx("INTJ"),
    )

    assert [item["doc_id"] for item in results] == ["seer-good"]


def test_same_role_same_mbti_keyword_search_returns_empty_without_matching_mbti() -> None:
    results = _retriever().search_with_keywords(
        ["查杀"],
        role="Seer",
        phase="DAY_SPEECH",
        k=3,
        retrieval_policy=RetrievalPolicy.SAME_ROLE_SAME_MBTI,
        agent_context=_ctx("ISTJ"),
    )

    assert results == []


def test_search_strategy_tool_uses_configured_default_policy(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_retrieve(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        captured.update(kwargs)
        return [{"doc_id": "ok", "situation": "查杀", "strategy": "策略", "quality": 0.9, "doc_type": ""}]

    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_retrieve)
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_SPEECH",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )
    tools = create_tools(
        obs,
        Memory("P1", "Seer"),
        mbti="INTJ",
        alignment="village",
        player_id="P1",
        default_retrieval_policy="same_role_same_mbti",
    )

    output = tools["search_strategies"]["fn"](["查杀"])

    assert "ok" in output
    assert captured["retrieval_policy"] == RetrievalPolicy.SAME_ROLE_SAME_MBTI
    assert captured["mbti"] == "INTJ"
    assert captured["alignment"] == "village"


def test_search_strategy_tool_explicit_policy_overrides_default(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_retrieve(*_args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        captured.update(kwargs)
        return [{"doc_id": "ok", "situation": "查杀", "strategy": "策略", "quality": 0.9, "doc_type": ""}]

    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_retrieve)
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_SPEECH",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )
    tools = create_tools(obs, Memory("P1", "Seer"), default_retrieval_policy="same_role_same_mbti")

    tools["search_strategies"]["fn"](["查杀"], retrieval_policy="global_only")

    assert captured["retrieval_policy"] == RetrievalPolicy.GLOBAL_ONLY


def test_search_strategy_tool_does_not_tfidf_fallback_for_strict_policy(monkeypatch) -> None:
    def fake_retrieve(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def fake_tfidf(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("strict policy must not fall back to legacy TF-IDF")

    monkeypatch.setattr("backend.agents.cognitive.retrieval_prod.retrieve_strategies_prod", fake_retrieve)
    monkeypatch.setattr("backend.agents.cognitive.tools.retrieve_tfidf", fake_tfidf)
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Seer",
        day=1,
        phase="DAY_SPEECH",
        alive=[PlayerInfo(id="P1", name="Alice", seat=1, alive=True)],
    )
    tools = create_tools(obs, Memory("P1", "Seer"), default_retrieval_policy="same_role_same_mbti")

    output = tools["search_strategies"]["fn"](["不存在的策略词"])

    assert "未找到匹配的策略" in output


def test_native_tool_schema_exposes_retrieval_controls() -> None:
    loop = AgentLoop(object(), "system prompt")
    schemas = loop._tools_to_bind_schemas(
        {
            "search_strategies": {
                "fn": lambda: None,
                "description": "search_strategies(keywords: list[str])\n  search",
            }
        }
    )

    props = schemas[0]["function"]["parameters"]["properties"]
    assert "retrieval_policy" in props
    assert props["retrieval_policy"]["enum"] == [policy.value for policy in RetrievalPolicy]
    assert "mode" in props
    assert "use_regex" in props


def test_agent_factory_defaults_to_hybrid_retrieval_policy(monkeypatch) -> None:
    monkeypatch.delenv("AIWEREWOLF_RETRIEVAL_POLICY", raising=False)

    assert _resolve_retrieval_policy({}) == "hybrid_role_mbti_global"


def test_agent_factory_retrieval_policy_precedence(monkeypatch) -> None:
    monkeypatch.setenv("AIWEREWOLF_RETRIEVAL_POLICY", "same_role_all_mbti")

    assert _resolve_retrieval_policy({}) == "same_role_all_mbti"
    assert _resolve_retrieval_policy({"retrieval_policy": "same_role_same_mbti"}) == "same_role_same_mbti"
