from __future__ import annotations

import argparse
import json
import os

from backend.application.matches.configuration import game_from_config
from backend.application.matches.executor import build_game
from backend.db.persist import save_game_end


def resolve_provider(cli_provider: str | None) -> str:
    """Resolve the demo provider without hiding an explicit environment choice."""
    return cli_provider or os.getenv("LLM_PROVIDER") or "fake"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a complete offline AI Werewolf demo game.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for role assignment.")
    parser.add_argument("--max-days", type=int, default=8, help="Maximum day count before wolves win.")
    parser.add_argument("--config", default=None, help="Optional YAML config path.")
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider. Defaults to LLM_PROVIDER, then fake for an offline smoke test.",
    )
    parser.add_argument("--show-private", action="store_true", help="Print moderator view with private events.")
    args = parser.parse_args()
    provider = resolve_provider(args.provider)
    if provider == "fake":
        os.environ["_TEST_ALLOW_FAKE_LLM"] = "true"

    game = (
        game_from_config(args.config)
        if args.config
        else build_game(seed=args.seed, max_days=args.max_days, llm_config={"provider": provider})
    )
    state = game.play()
    save_game_end(state, include_post_game=False)
    data = state.moderator_dict() if args.show_private else state.public_dict()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
