from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("AIWEREWOLF_SKIP_DOTENV", "true")
_TEST_DB_PATH = Path(tempfile.gettempdir()) / f"aiwerewolf-test-{os.getpid()}.sqlite"
_TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_TEST_DB_PATH.unlink(missing_ok=True)
os.environ.setdefault("AIWEREWOLF_SQLITE_PATH", str(_TEST_DB_PATH))
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("AIWEREWOLF_DEFAULT_AGENT_TYPE", "llm")
os.environ["MODEL_POOL"] = "fake:fake-llm"
os.environ["DOUBAO_MODEL_POOL"] = "fake:fake-llm"


@pytest.fixture(autouse=True)
def _use_local_strategy_retrieval_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests deterministic even when local .env enables Doubao retrieval."""
    monkeypatch.setenv("STRATEGY_EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("STRATEGY_RERANK_PROVIDER", "off")
    monkeypatch.setenv("STRATEGY_RERANK_STRICT", "false")


@pytest.fixture(autouse=True)
def _use_fake_llm_agents_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests default to local LLM-compatible agents without external API cost."""
    monkeypatch.setenv("_TEST_ALLOW_FAKE_LLM", "true")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("AIWEREWOLF_DEFAULT_AGENT_TYPE", "llm")
    monkeypatch.setenv("MODEL_POOL", "fake:fake-llm")
    monkeypatch.setenv("DOUBAO_MODEL_POOL", "fake:fake-llm")
    for key in (
        "DOUBAO_MODEL",
        "DOUBAO_ENDPOINT",
        "DOUBAO_BASE_URL",
        "ARK_BASE_URL",
        "DSV4FLASH_MODEL",
        "DSV4FLASH_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_BASE_URL",
        "WEAPI_MODEL",
        "WEAPI_BASE_URL",
        "MIMO_MODEL",
        "MIMO_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
