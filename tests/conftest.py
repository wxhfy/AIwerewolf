from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_EXTERNAL_DATA_TESTS = {
    "test_track_b_human_pairwise_pipeline.py",
    "test_track_b_human_pairwise_schema.py::TestHumanLabelSchema::test_template_file_exists",
    "test_track_b_open_data_adapter.py::test_adapter_loads_raw_games",
    "test_track_b_open_data_adapter.py::test_adapter_builds_game_logs",
    "test_track_b_open_data_adapter.py::test_adapter_extracts_speech_samples",
    "test_track_b_open_data_adapter.py::test_adapter_weak_labels_have_source",
    "test_track_b_open_data_full_pipeline.py::test_raw_directories_exist",
    "test_track_b_pairwise_expansion.py::TestPairwiseExpansion::test_vote_expansion_generates_minimum_pairs",
    "test_track_b_pairwise_expansion.py::TestPairwiseExpansion::test_night_action_expansion_generates_minimum_pairs",
    "test_track_b_pairwise_expansion.py::TestPairwiseExpansion::test_vote_degenerate_rate_improved",
    "test_track_b_pairwise_expansion.py::TestPairwiseExpansion::test_night_action_degenerate_rate_improved",
    "test_track_b_pairwise_expansion.py::TestPairwiseExpansion::test_effective_pair_metrics_computable",
    "test_track_b_speech_semantic_audit_integration.py::test_audit_examples_can_be_generated",
    "test_track_b_vnext_evaluation.py::test_evaluate_track_b_vnext_pairwise_suite_runs",
    "test_track_b_vnext_evaluation.py::test_vnext_eval_report_created",
}

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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.getenv("RUN_EXTERNAL_DATA_TESTS", "").strip().lower() in {"1", "true", "yes"}:
        return
    marker = pytest.mark.skip(reason="requires local-only Track B datasets or generated evaluation artifacts")
    for item in items:
        normalized = item.nodeid.replace("\\", "/")
        if any(normalized.endswith(test_id) or test_id in normalized for test_id in _EXTERNAL_DATA_TESTS):
            item.add_marker(marker)


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
