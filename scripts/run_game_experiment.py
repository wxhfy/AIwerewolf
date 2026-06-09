"""Run 20-game experiment to measure role win rate and improvement.

Usage:
    python scripts/run_game_experiment.py [--mode heuristic|llm] [--games 20]

Default: heuristic mode, 20 games.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore")

from backend.engine.game import WerewolfGame


def run_experiment(
    n_games: int = 20,
    mode: str = "heuristic",
    start_seed: int = 1,
) -> list[dict[str, Any]]:
    """Run N games and collect per-role statistics."""
    results = []
    role_stats: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"wins": [], "survival_days": [], "alive_endgame": [], "team": ""}
    )

    for i in range(n_games):
        seed = start_seed + i
        t0 = time.perf_counter()
        try:
            game = WerewolfGame(seed=seed, player_count=7)
            state = game.play()
            elapsed = time.perf_counter() - t0

            winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
            max_days = state.day

            for p in state.players:
                role = p.role.value
                team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"

                # Win: 1 if team matches winner
                won = team == winner
                role_stats[role]["wins"].append(1.0 if won else 0.0)
                role_stats[role]["survival_days"].append(float(state.day if p.alive else p.death_day or 0))
                role_stats[role]["alive_endgame"].append(1.0 if p.alive else 0.0)
                role_stats[role]["team"] = team

            results.append(
                {
                    "seed": seed,
                    "winner": winner,
                    "days": max_days,
                    "duration_s": round(elapsed, 1),
                }
            )

            print(f"  Game {i + 1}/{n_games}: seed={seed}, winner={winner}, days={max_days}, time={elapsed:.0f}s")

        except Exception as e:
            print(f"  Game {i + 1}/{n_games}: seed={seed}, FAILED: {e}")
            results.append({"seed": seed, "error": str(e)})

    # Compile statistics
    stats = {}
    for role, data in sorted(role_stats.items()):
        wins = data["wins"]
        surv = data["survival_days"]
        alive = data["alive_endgame"]
        n = len(wins)
        stats[role] = {
            "team": data["team"],
            "games": n,
            "win_rate": round(sum(wins) / max(n, 1), 4),
            "avg_survival_days": round(sum(surv) / max(n, 1), 2),
            "alive_endgame_rate": round(sum(alive) / max(n, 1), 4),
        }

    return results, stats


def print_report(stats: dict, total_games: int):
    """Print a formatted report."""
    print()
    print("=" * 65)
    print(f"ROLE PERFORMANCE REPORT ({total_games} games)")
    print("=" * 65)
    print(f"{'Role':<18s} {'Team':<8s} {'Win Rate':>10s} {'Surv Days':>10s} {'Alive End':>10s}")
    print("-" * 65)

    for role, data in sorted(stats.items()):
        team = data["team"]
        wr = f"{data['win_rate']:.1%}"
        sd = f"{data['avg_survival_days']:.1f}"
        ae = f"{data['alive_endgame_rate']:.1%}"
        print(f"{role:<18s} {team:<8s} {wr:>10s} {sd:>10s} {ae:>10s}")

    print("-" * 65)

    # Team-level stats
    village_wins = sum(d["win_rate"] * d["games"] for _, d in stats.items() if d["team"] == "village")
    village_games = sum(d["games"] for _, d in stats.items() if d["team"] == "village")
    wolf_wins = sum(d["win_rate"] * d["games"] for _, d in stats.items() if d["team"] == "wolf")
    wolf_games = sum(d["games"] for _, d in stats.items() if d["team"] == "wolf")

    if village_games > 0:
        print(f"\nVillage overall win rate: {village_wins / village_games:.1%}")
    if wolf_games > 0:
        print(f"Wolf overall win rate: {wolf_wins / wolf_games:.1%}")

    print("=" * 65)

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="heuristic", choices=["heuristic", "llm"])
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    print(f"Running {args.games} games in {args.mode} mode...")
    t0 = time.perf_counter()

    results, stats = run_experiment(n_games=args.games, mode=args.mode)
    print_report(stats, len([r for r in results if "error" not in r]))

    total_elapsed = time.perf_counter() - t0
    print(f"\nTotal time: {total_elapsed:.0f}s ({total_elapsed / 60:.1f} min)")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"results": results, "stats": stats, "mode": args.mode, "games": args.games}
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
