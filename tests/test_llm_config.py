import pytest

from backend.agents.factory import create_agents
from backend.engine.models import Alignment
from backend.engine.models import Player
from backend.engine.models import Role
from backend.llm import create_client


def test_create_client_infers_deepseek_from_model() -> None:
    client = create_client(provider=None, model="deepseek-v4-flash")
    assert client.base_url == "https://api.deepseek.com"
    assert client.model == "deepseek-v4-flash"


def test_create_client_defaults_to_dsv4flash(monkeypatch) -> None:
    # Stub load_env_file so the test exercises the in-code defaults rather
    # than the user's .env.
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    for var in (
        "LLM_PROVIDER",
        "DSV4FLASH_API_KEY",
        "DSV4FLASH_BASE_URL",
        "DSV4FLASH_MODEL",
        "DOUBAO_API_KEY",
        "ARK_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "DOUBAO_ENDPOINT",
        "DOUBAO_MODEL",
        "ANTHROPIC_MODEL",
        "DOUBAO_BASE_URL",
        "ARK_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "MIMO_BASE_URL",
        "MIMO_MODEL",
        "MIMO_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DSV4FLASH_API_KEY", "test-key")
    client = create_client(provider=None)
    assert client.provider == "dsv4flash"
    assert client.model == "deepseek-v4-flash"


def test_create_client_mimo_requires_base_url(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    client = create_client(provider="mimo")

    assert client.provider == "mimo"
    assert client.available is False


def test_create_client_mimo_uses_openai_compatible_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("MIMO_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("MIMO_MODEL", "mimo-test")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    client = create_client(provider="mimo")

    assert client.provider == "mimo"
    assert client.base_url == "http://127.0.0.1:8001/v1"
    assert client.model == "mimo-test"
    assert client.api_key == "local"


def test_fake_llm_uses_public_pressure_when_target_is_legal() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:Carol，身份=Villager\n"
        "合法目标：1号:Alice，2号:Bob，4号:Dave\n"
        "=== 今日发言 ===\n"
        "1号:Alice：我是预言家，查杀 Bob，今天归票 Bob。\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "Bob"' in content


def test_create_agents_applies_role_model_overrides() -> None:
    from backend.agents.cognitive.agent import CognitiveAgent

    players = [
        Player(id="p1", seat=1, name="P1", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="p2", seat=2, name="P2", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="p3", seat=3, name="P3", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]

    agents = create_agents(
        players,
        {
            "type": "llm",
            "provider": "fake",
            "model": "doubao-default",
            "role_models": {
                "Werewolf": {"provider": "fake", "model": "deepseek-v4-pro[1m]"},
                "SEER": {"provider": "fake", "model": "deepseek-v4-flash"},
                "Villager": {"provider": "fake", "model": "glm-5.1[1m]"},
            },
        },
    )

    # P1 (Werewolf): CognitiveAgent with role model override
    assert isinstance(agents["p1"], CognitiveAgent)
    assert players[0].model_name == "deepseek-v4-pro[1m]"
    # P2 (Seer): CognitiveAgent with provider+model override
    assert isinstance(agents["p2"], CognitiveAgent)
    assert players[1].model_name == "deepseek-v4-flash"
    # P3 (Villager): still LLM-backed, with role model override
    assert isinstance(agents["p3"], CognitiveAgent)
    assert players[2].model_name == "glm-5.1[1m]"
    assert players[2].agent_type == "llm"


def test_create_agents_rejects_heuristic_override() -> None:
    players = [
        Player(id="p1", seat=1, name="P1", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]

    with pytest.raises(ValueError, match="heuristic agents are disabled"):
        create_agents(
            players,
            {
                "type": "llm",
                "provider": "fake",
                "role_models": {"Villager": {"type": "heuristic"}},
            },
        )
