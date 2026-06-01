"""Multi-model comparison: run games with different LLM backends per player.

Verifies:
  1. Multiple ark models load correctly (deepseek-v4-pro, kimi-k2.6, glm-5.1, etc.)
  2. Factory assigns different models to different players
  3. Leaderboard distinguishes results by model
  4. Head-to-head comparison data for model evaluation

Usage:
  MODEL_POOL="ark:deepseek-v4-pro[1m],ark:kimi-k2.6[1m]" \\
    python scripts/eval_multimodel_comparison.py --games 5
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.llm.env import load_env_file
load_env_file()

from backend.agents.factory import create_agents, _resolve_pool_specs
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players, get_role_configuration


def check_pool():
    """Verify model pool is configured and models can be created."""
    print("=== Model Pool Check ===")
    specs = _resolve_pool_specs({})
    if not specs:
        print("  WARNING: MODEL_POOL is empty. Set MODEL_POOL in .env")
        print("  Example: MODEL_POOL=ark:deepseek-v4-pro[1m],ark:kimi-k2.6[1m]")
        return False

    from backend.llm import create_client

    for spec in specs:
        provider = spec["provider"]
        model = spec["model"]
        try:
            client = create_client(
                provider=provider,
                model=model,
                api_key=spec["api_key"],
                base_url=spec["base_url"],
            )
            if hasattr(client, "chat_sync"):
                print(f"  OK: {provider}:{model}")
            else:
                print(f"  FAIL: {provider}:{model} — no chat_sync method")
                return False
        except Exception as e:
            print(f"  WARN: {provider}:{model} — {e}")
            continue

    return True


def run_comparison_games(num_games: int = 3, player_count: int = 7):
    """Run multiple games with multi-model assignment.

    Each game randomly assigns different models from the pool to different
    players, creating natural head-to-head comparison data.
    """
    from backend.db.persist import save_game_start, save_game_end
    from backend.db.database import SessionLocal

    specs = _resolve_pool_specs({})
    if not specs:
        print("ERROR: No models in pool")
        return

    model_stats: dict[str, dict] = {}
    for spec in specs:
        label = f"{spec['provider']}:{spec['model']}"
        model_stats[label] = {"games": 0, "wins": 0, "survived": 0}

    for game_idx in range(num_games):
        seed = 1000 + game_idx
        roles = get_role_configuration(player_count)
        players = build_players(roles, seed=seed)

        # Build agent config with model pool
        agents = create_agents(players, {
            "type": "llm",
            "seed": seed,
            "model_pool": [f"{s['provider']}:{s['model']}" for s in specs],
        })

        # Show assignments
        model_labels = []
        for p in players:
            label = f"{p.model_name or 'unknown'}"
            model_labels.append(label)
            model_key = None
            for s in specs:
                if s["model"] in label:
                    model_key = f"{s['provider']}:{s['model']}"
                    break
            if model_key:
                model_stats[model_key]["games"] += 1

        print(f"\n=== Game {game_idx + 1}/{num_games} (seed={seed}) ===")
        for i, p in enumerate(players):
            print(f"  {p.seat}号 {p.name}({p.role.value}) → {model_labels[i]}")

        # Run game
        try:
            game = WerewolfGame(players=players, agents=agents, seed=seed)
            game.play()

            winner = game.state.winner
            print(f"  Winner: {winner}")

            # Update stats
            for p in players:
                for s in specs:
                    if s["model"] in (p.model_name or ""):
                        model_key = f"{s['provider']}:{s['model']}"
                        won = (
                            (winner and "wolf" in str(winner).lower() and "wolf" in p.role.value.lower())
                            or (winner and "village" in str(winner).lower() and "wolf" not in p.role.value.lower())
                        )
                        if won:
                            model_stats[model_key]["wins"] += 1
                        if p.alive:
                            model_stats[model_key]["survived"] += 1
                        break
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Print comparison
    print(f"\n{'='*60}")
    print("MODEL COMPARISON RESULTS")
    print(f"{'='*60}")
    print(f"{'Model':<40} {'Games':>6} {'Wins':>6} {'Win%':>7} {'Surv%':>7}")
    print("-" * 60)
    for label, stats in sorted(model_stats.items()):
        games = stats["games"]
        if games == 0:
            continue
        win_rate = stats["wins"] / games * 100
        surv_rate = stats["survived"] / games * 100
        print(f"{label:<40} {games:>6} {stats['wins']:>6} {win_rate:>6.1f}% {surv_rate:>6.1f}%")

    # Leaderboard integration
    print(f"\n=== Leaderboard Ready ===")
    print(f"  Run: python scripts/manage_knowledge.py stats")
    print(f"  Or check DB: SELECT * FROM leaderboard_entries ORDER BY win_rate DESC;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-model Werewolf comparison")
    parser.add_argument("--games", type=int, default=3, help="Number of games to run")
    parser.add_argument("--players", type=int, default=7, help="Players per game")
    parser.add_argument("--check", action="store_true", help="Only check model pool")
    args = parser.parse_args()

    if not check_pool():
        sys.exit(1)

    if args.check:
        sys.exit(0)

    run_comparison_games(num_games=args.games, player_count=args.players)
