import pytest

from backend.agents.factory import create_agents
from backend.engine.models import Alignment, Player, Role
from backend.llm import create_client


def test_create_client_infers_deepseek_from_model() -> None:
    client = create_client(provider=None, model="deepseek-v4-flash")
    assert client.base_url == "https://api.deepseek.com"
    assert client.model == "deepseek-v4-flash"


def test_create_client_defaults_to_dsv4flash(monkeypatch) -> None:
    # Stub load_env_file so the test exercises the in-code defaults rather
    # than the user's .env.
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    for var in ("LLM_PROVIDER", "DSV4FLASH_API_KEY", "DSV4FLASH_BASE_URL", "DSV4FLASH_MODEL",
                "DOUBAO_API_KEY", "ARK_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                "DOUBAO_ENDPOINT", "DOUBAO_MODEL", "ANTHROPIC_MODEL", "DOUBAO_BASE_URL",
                "ARK_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DSV4FLASH_API_KEY", "test-key")
    client = create_client(provider=None)
    assert client.provider == "dsv4flash"
    assert client.model == "deepseek-v4-flash"


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
