from __future__ import annotations

import argparse
import json

from backend.engine.config import game_from_config
from backend.engine.game import WerewolfGame


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a complete offline AI Werewolf demo game.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for role assignment.")
    parser.add_argument("--max-days", type=int, default=8, help="Maximum day count before wolves win.")
    parser.add_argument("--config", default=None, help="Optional YAML config path.")
    parser.add_argument("--show-private", action="store_true", help="Print moderator view with private events.")
    args = parser.parse_args()

    game = game_from_config(args.config) if args.config else WerewolfGame(seed=args.seed, max_days=args.max_days)
    state = game.play()
    data = state.moderator_dict() if args.show_private else state.public_dict()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
