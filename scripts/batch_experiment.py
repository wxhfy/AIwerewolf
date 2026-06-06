"""Batch experiment: run N CognitiveAgent games and track role win rates.

Usage:
  nohup python scripts/batch_experiment.py --games 20 > experiment.log 2>&1 &

Each game takes ~30 min. 20 games = ~10 hours.
Results are saved incrementally to data/experiment/batch_results.jsonl.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from backend.engine.game import WerewolfGame


def _save_game_state(state, filepath: Path) -> None:
    """Save full game state for Track B review and Track C evolution."""
    players_data = []
    for p in state.players:
        players_data.append(
            {
                "name": p.name,
                "role": p.role.value,
                "seat": p.seat,
                "alive": p.alive,
                "death_day": p.death_day if hasattr(p, "death_day") else None,
            }
        )
    events_data = []
    for e in getattr(state, "events", []) or []:
        try:
            evt = {
                "day": getattr(e, "day", 0),
                "phase": str(getattr(e, "phase", "")),
                "type": str(getattr(e, "type", "")),
            }
            for field in ("actor", "target", "content", "speech", "vote", "result"):
                val = getattr(e, field, None)
                if val is not None:
                    evt[field] = str(val) if not isinstance(val, (str, int, float, bool, list, dict)) else val
            events_data.append(evt)
        except Exception:
            pass
    data = {
        "seed": getattr(state, "seed", 0),
        "winner": state.winner.value if hasattr(state.winner, "value") else str(state.winner),
        "days": state.day,
        "players": players_data,
        "events": events_data,
        "event_count": len(events_data),
    }
    import json

    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def run_batch(n_games: int = 20, start_seed: int = 100) -> None:
    output_dir = ROOT / "data" / "experiment"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_file = output_dir / "batch_results.jsonl"
    summary_file = output_dir / "batch_summary.json"

    role_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "games": 0, "survival_days": 0.0, "alive_end": 0})
    game_results = []

    print(f"Experiment started: {datetime.now()}")
    print(f"Games: {n_games}, mode: cognitive")
    print(f"Output: {results_file}")
    print(f"{'=' * 60}")

    for i in range(n_games):
        seed = start_seed + i
        t0 = time.perf_counter()
        result = {"seed": seed, "index": i + 1, "started": datetime.now().isoformat()}

        try:
            game = WerewolfGame(seed=seed, player_count=7)
            state = game.play()
            elapsed = time.perf_counter() - t0

            winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
            result["winner"] = winner
            result["days"] = state.day
            result["duration_s"] = round(elapsed, 1)
            result["players"] = []

            for p in state.players:
                role = p.role.value
                team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
                won = team == winner
                # Track by role
                role_stats[role]["wins"] += 1 if won else 0
                role_stats[role]["games"] += 1
                role_stats[role]["survival_days"] += state.day if p.alive else (p.death_day or 0)
                role_stats[role]["alive_end"] += 1 if p.alive else 0
                # Track by MBTI+role
                mbti = (p.persona or {}).get("mbti", "UNKNOWN") if hasattr(p, "persona") else "UNKNOWN"
                mbti_key = f"{mbti}+{role}"
                role_stats[mbti_key]["wins"] += 1 if won else 0
                role_stats[mbti_key]["games"] += 1
                role_stats[mbti_key]["survival_days"] += state.day if p.alive else (p.death_day or 0)
                role_stats[mbti_key]["alive_end"] += 1 if p.alive else 0
                result["players"].append({"name": p.name, "role": role, "mbti": mbti, "alive": p.alive, "won": won})

            print(f"[{i + 1:2d}/{n_games}] seed={seed} winner={winner} days={state.day} time={elapsed:.0f}s")

            # Save full game state for evolution analysis
            state_file = output_dir / f"game_state_seed{seed}.json"
            try:
                _save_game_state(state, state_file)
            except Exception:
                pass

        except Exception as e:
            elapsed = time.perf_counter() - t0
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()[:500]
            result["duration_s"] = round(elapsed, 1)
            print(f"[{i + 1:2d}/{n_games}] seed={seed} FAILED: {e}")

        game_results.append(result)

        # Write incrementally
        with open(results_file, "a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        # Print running stats every 5 games
        if (i + 1) % 5 == 0:
            print(f"  --- Running stats after {i + 1} games ---")
            for role in sorted(role_stats.keys()):
                s = role_stats[role]
                wr = s["wins"] / max(s["games"], 1)
                print(f"  {role:<14s}: win_rate={wr:.1%} ({s['wins']}/{s['games']})")
            print()

    # Final summary
    stats = {}
    for role, s in sorted(role_stats.items()):
        n = max(s["games"], 1)
        stats[role] = {
            "games": s["games"],
            "wins": s["wins"],
            "win_rate": round(s["wins"] / n, 4),
            "avg_survival_days": round(s["survival_days"] / n, 2),
            "alive_endgame_rate": round(s["alive_end"] / n, 4),
        }

    summary = {
        "completed_at": datetime.now().isoformat(),
        "total_games": n_games,
        "successful": len([r for r in game_results if "error" not in r]),
        "failed": len([r for r in game_results if "error" in r]),
        "role_stats": stats,
        "results": game_results,
    }
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"FINAL RESULTS ({summary['successful']}/{n_games} completed)")
    print(f"{'=' * 60}")
    print(f"{'Role':<14s} {'Win Rate':>9s} {'Surv Days':>10s} {'Alive End':>10s}")
    print(f"{'-' * 56}")
    for role, s in sorted(stats.items()):
        print(f"{role:<14s} {s['win_rate']:>8.1%} {s['avg_survival_days']:>9.1f} {s['alive_endgame_rate']:>9.1%}")
    print(f"{'=' * 60}")
    print(f"Results saved to: {summary_file}")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=20)
    p.add_argument("--start-seed", type=int, default=100)
    args = p.parse_args()
    run_batch(n_games=args.games, start_seed=args.start_seed)
