from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _use_local_strategy_retrieval_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests deterministic even when local .env enables Doubao retrieval."""
    monkeypatch.setenv("STRATEGY_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("STRATEGY_RERANK_PROVIDER", "off")
    monkeypatch.setenv("STRATEGY_RERANK_STRICT", "false")


@pytest.fixture(autouse=True)
def _use_fake_llm_agents_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests default to local LLM-compatible agents without external API cost."""
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("AIWEREWOLF_DEFAULT_AGENT_TYPE", "llm")
