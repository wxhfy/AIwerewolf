from __future__ import annotations

from backend.llm import create_client


def test_siliconflow_factory_uses_free_glm_defaults(monkeypatch) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.delenv("SILICONFLOW_MODEL", raising=False)
    monkeypatch.delenv("SILICONFLOW_BASE_URL", raising=False)

    client = create_client(provider="siliconflow", timeout=1, max_retries=0)

    assert client.provider == "siliconflow"
    assert client.model == "THUDM/GLM-4-9B-0414"
    assert client.base_url == "https://api.siliconflow.cn/v1"
    client.close()


def test_bigmodel_factory_uses_official_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")
    monkeypatch.delenv("BIGMODEL_API_KEY", raising=False)
    monkeypatch.delenv("BIGMODEL_BASE_URL", raising=False)
    monkeypatch.delenv("ZHIPU_BASE_URL", raising=False)
    monkeypatch.delenv("BIGMODEL_MODEL", raising=False)
    monkeypatch.delenv("ZHIPU_MODEL", raising=False)

    client = create_client(provider="glm", timeout=1, max_retries=0)

    assert client.provider == "bigmodel"
    assert client.model == "glm-4-flash-250414"
    assert client.base_url == "https://open.bigmodel.cn/api/paas/v4"
    client.close()


def test_bigmodel_factory_accepts_full_chat_completions_url(monkeypatch) -> None:
    monkeypatch.setenv("BIGMODEL_API_KEY", "test-key")

    client = create_client(
        provider="bigmodel",
        base_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model="glm-test",
        timeout=1,
        max_retries=0,
    )

    assert client.base_url == "https://open.bigmodel.cn/api/paas/v4"
    client.close()


def test_bigmodel_factory_retries_transient_failures_by_default(monkeypatch) -> None:
    monkeypatch.setenv("BIGMODEL_API_KEY", "test-key")
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)

    client = create_client(provider="bigmodel", timeout=1)

    assert client.max_retries == 2
    client.close()
