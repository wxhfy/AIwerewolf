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
    players = [
        Player(id="p1", seat=1, name="P1", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="p2", seat=2, name="P2", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="p3", seat=3, name="P3", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]

    agents = create_agents(
        players,
        {
            "type": "llm",
            "provider": "doubao",
            "model": "doubao-default",
            "role_models": {
                "Werewolf": {"model": "deepseek-v4-pro[1m]"},
                "SEER": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                "Villager": {"type": "heuristic"},
            },
        },
    )

    assert agents["p1"].client.model == "deepseek-v4-pro[1m]"
    assert agents["p1"].client.provider == "doubao"
    assert agents["p2"].client.model == "deepseek-v4-flash"
    assert agents["p2"].client.provider == "deepseek"
    assert players[0].model_name == "deepseek-v4-pro[1m]"
    assert players[1].model_name == "deepseek-v4-flash"
    assert players[2].agent_type == "heuristic"
