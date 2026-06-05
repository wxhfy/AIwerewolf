"""Role win-rate experiment: compare baseline vs strategy-enhanced agent.
Runs N games, tracks per-role win rate, survival, and decision quality.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from backend.engine.game import WerewolfGame


def run_baseline(n: int = 20) -> tuple[list[dict], dict]:
    """Run baseline games with default settings."""
    results = []
    role_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "games": 0, "survival_sum": 0.0, "alive_sum": 0})

    for i in range(n):
        seed = 100 + i
        t0 = time.perf_counter()
        try:
            game = WerewolfGame(seed=seed, player_count=7)
            state = game.play()
            elapsed = time.perf_counter() - t0

            winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)

            for p in state.players:
                role = p.role.value
                team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
                won = team == winner
                role_stats[role]["wins"] += 1 if won else 0
                role_stats[role]["games"] += 1
                role_stats[role]["survival_sum"] += float(state.day if p.alive else (p.death_day or 0))
                role_stats[role]["alive_sum"] += 1 if p.alive else 0

            results.append({"seed": seed, "winner": winner, "days": state.day, "time_s": round(elapsed, 1)})
            print(f"  [{i + 1}/{n}] seed={seed} winner={winner} days={state.day} time={elapsed:.0f}s")

        except Exception as e:
            print(f"  [{i + 1}/{n}] seed={seed} FAILED: {e}")
            results.append({"seed": seed, "error": str(e)})

    stats = _compile_stats(role_stats)
    return results, stats


def _compile_stats(raw: dict) -> dict:
    stats = {}
    for role, d in sorted(raw.items()):
        n = max(d["games"], 1)
        stats[role] = {
            "games": d["games"],
            "win_rate": round(d["wins"] / n, 4),
            "avg_survival_days": round(d["survival_sum"] / n, 2),
            "alive_endgame_rate": round(d["alive_sum"] / n, 4),
        }
    return stats


def print_report(baseline_stats: dict, enhanced_stats: dict | None = None):
    """Print comparison report."""
    print()
    print("=" * 80)
    if enhanced_stats:
        print(f"{'Role':<16s} {'Base WR':>9s} {'Enh WR':>9s} {'Delta':>8s} {'Base Surv':>10s} {'Enh Surv':>10s}")
    else:
        print(f"{'Role':<16s} {'Win Rate':>9s} {'Surv Days':>10s} {'Alive End':>10s}")
    print("-" * 80)

    for role in sorted(baseline_stats.keys()):
        b = baseline_stats[role]
        if enhanced_stats and role in enhanced_stats:
            e = enhanced_stats[role]
            delta = e["win_rate"] - b["win_rate"]
            print(
                f"{role:<16s} {b['win_rate']:>8.1%} {e['win_rate']:>8.1%} {delta:>+7.1%} "
                f"{b['avg_survival_days']:>9.1f} {e['avg_survival_days']:>9.1f}"
            )
        else:
            print(f"{role:<16s} {b['win_rate']:>8.1%} {b['avg_survival_days']:>9.1f} {b['alive_endgame_rate']:>9.1%}")

    print("=" * 80)

    # Team-level
    for team in ["village", "wolf"]:
        roles_in_team = [
            r for r, d in baseline_stats.items() if (r in ("Werewolf", "WhiteWolfKing")) == (team == "wolf")
        ]
        wins = sum(baseline_stats[r]["win_rate"] * baseline_stats[r]["games"] for r in roles_in_team)
        games = sum(baseline_stats[r]["games"] for r in roles_in_team)
        if games > 0:
            print(f"{team.capitalize()} overall: {wins / games:.1%} ({games} role-games)", end="")
            if enhanced_stats:
                e_wins = sum(enhanced_stats[r]["win_rate"] * enhanced_stats[r]["games"] for r in roles_in_team)
                e_games = sum(enhanced_stats[r]["games"] for r in roles_in_team)
                if e_games > 0:
                    print(f" → {e_wins / e_games:.1%} ({e_games} role-games)")
                else:
                    print()
            else:
                print()


def main():
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--output", default="data/experiment/winrate_experiment.json")
    args = parser.parse_args()

    print(f"Role Win-Rate Experiment: {args.games} games")
    print(f"Mode: {os.environ.get('AIWEREWOLF_DEFAULT_AGENT_TYPE', 'llm')}")
    print()

    # Baseline
    print("--- Baseline ---")
    t0 = time.perf_counter()
    base_results, base_stats = run_baseline(args.games)
    base_time = time.perf_counter() - t0

    print_report(base_stats)

    print(f"\nTotal: {len([r for r in base_results if 'error' not in r])}/{args.games} games completed")
    print(f"Time: {base_time:.0f}s ({base_time / 60:.1f} min)")

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "games": args.games,
        "mode": os.environ.get("AIWEREWOLF_DEFAULT_AGENT_TYPE", "llm"),
        "baseline": {"results": base_results, "stats": base_stats},
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
