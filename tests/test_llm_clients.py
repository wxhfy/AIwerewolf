from __future__ import annotations

import json

from backend.llm import create_client


def test_create_client_infers_deepseek_from_model() -> None:
    client = create_client(provider=None, model="deepseek-v4-flash")
    assert client.base_url == "https://api.deepseek.com"
    assert client.model == "deepseek-v4-flash"


def test_create_client_defaults_to_dsv4flash(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("DSV4FLASH_API_KEY", "test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    client = create_client(provider=None)

    assert client.provider == "dsv4flash"
    assert client.model == "deepseek-v4-flash"


def test_create_client_applies_timeout_and_retries(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *args, **kwargs: None)
    monkeypatch.setenv("DSV4FLASH_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")

    client = create_client(provider="dsv4flash")

    assert client.max_retries == 4
    assert client.timeout.read == 60


def test_fake_client_returns_harness_selection() -> None:
    client = create_client(provider="fake")
    payload = {
        "action_options": [
            {"option_id": "vote:p2", "action_type": "vote", "parameters": {"target_id": "p2"}}
        ]
    }

    response = client.chat_sync(
        [{"role": "user", "content": "AIWEREWOLF_HARNESS_DECISION\n" + json.dumps(payload)}]
    )
    selection = json.loads(response["choices"][0]["message"]["content"])

    assert selection["option_id"] == "vote:p2"
