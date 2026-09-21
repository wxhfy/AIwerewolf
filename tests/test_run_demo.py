from backend.application.matches import configuration
from backend.run_demo import resolve_provider


def test_resolve_provider_prefers_cli(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "bigmodel")

    assert resolve_provider("siliconflow") == "siliconflow"


def test_resolve_provider_uses_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "bigmodel")

    assert resolve_provider(None) == "bigmodel"


def test_resolve_provider_defaults_to_fake(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    assert resolve_provider(None) == "fake"


def test_game_from_config_uses_persistent_build_path(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "demo.yaml"
    config_path.write_text(
        """
game:
  player_count: 7
  max_days: 4
agents:
  type: llm
  seed: 21
  provider: bigmodel
  model: glm-4-flash-250414
""".strip(),
        encoding="utf-8",
    )
    captured = {}
    sentinel = object()

    def fake_build_game(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(configuration, "build_game", fake_build_game)

    result = configuration.game_from_config(config_path)

    assert result is sentinel
    assert captured["seed"] == 21
    assert captured["agent_type"] == "llm"
    assert captured["player_count"] == 7
    assert captured["max_days"] == 4
    assert captured["llm_config"] == {
        "seed": 21,
        "provider": "bigmodel",
        "model": "glm-4-flash-250414",
    }
