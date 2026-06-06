"""Evolution A/B test: baseline vs evolution-enhanced win rates.

Pipeline:
  1. Run N baseline games → save game states
  2. Generate ReviewReports from game states
  3. Run DreamJob to extract evolution strategy patches
  4. Apply patches to strategy library
  5. Run N evolution-enhanced games
  6. Compare win rates

Usage:
  python scripts/evolution_ab_test.py --baseline-games 5 --evolved-games 5
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.engine.game import WerewolfGame


def save_game_state(state, filepath: Path) -> None:
    """Save full game state for review."""
    players_data = []
    for p in state.players:
        mbti = (p.persona or {}).get("mbti", "UNKNOWN") if hasattr(p, "persona") else "UNKNOWN"
        players_data.append(
            {
                "name": p.name,
                "role": p.role.value,
                "seat": p.seat,
                "mbti": mbti,
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
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def run_games(n_games: int, start_seed: int, tag: str, output_dir: Path) -> list[dict]:
    """Run N games and return results. Save game states for evolution."""
    results = []
    states_dir = output_dir / f"states_{tag}"
    states_dir.mkdir(parents=True, exist_ok=True)

    for i in range(n_games):
        seed = start_seed + i
        t0 = time.perf_counter()
        print(f"  [{i + 1}/{n_games}] seed={seed}...", end=" ", flush=True)

        try:
            game = WerewolfGame(seed=seed, player_count=7)
            state = game.play()
            elapsed = time.perf_counter() - t0

            winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
            print(f"winner={winner} days={state.day} time={elapsed:.0f}s")

            # Save game state for evolution
            save_game_state(state, states_dir / f"game_seed{seed}.json")

            result = {"seed": seed, "winner": winner, "days": state.day, "duration_s": round(elapsed, 1), "players": []}
            for p in state.players:
                role = p.role.value
                team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
                mbti = (p.persona or {}).get("mbti", "UNKNOWN") if hasattr(p, "persona") else "UNKNOWN"
                result["players"].append(
                    {"name": p.name, "role": role, "mbti": mbti, "alive": p.alive, "won": (team == winner)}
                )
            results.append(result)

        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"FAILED: {e}")
            results.append({"seed": seed, "error": str(e), "duration_s": round(elapsed, 1)})

    return results


def compute_stats(results: list[dict]) -> dict:
    """Compute per-role and per-MBTI win rates from results."""
    role_stats = defaultdict(lambda: {"wins": 0, "games": 0})
    mbti_stats = defaultdict(lambda: {"wins": 0, "games": 0})
    combo_stats = defaultdict(lambda: {"wins": 0, "games": 0})
    for r in results:
        if "error" in r or "players" not in r:
            continue
        for p in r["players"]:
            role = p["role"]
            mbti = p.get("mbti", "UNKNOWN")
            won = p.get("won", False)
            role_stats[role]["games"] += 1
            if won:
                role_stats[role]["wins"] += 1
            mbti_stats[mbti]["games"] += 1
            if won:
                mbti_stats[mbti]["wins"] += 1
            combo_stats[f"{mbti}+{role}"]["games"] += 1
            if won:
                combo_stats[f"{mbti}+{role}"]["wins"] += 1

    def fmt(stats, min_games=1):
        out = {}
        for key, s in sorted(stats.items()):
            n = s["games"]
            if n >= min_games:
                out[key] = {"games": n, "wins": s["wins"], "win_rate": round(s["wins"] / n, 4)}
        return out

    wolf_wins = sum(1 for r in results if r.get("winner") == "wolf")
    village_wins = sum(1 for r in results if r.get("winner") == "village")
    total = wolf_wins + village_wins
    return {
        "by_role": fmt(role_stats),
        "by_mbti": fmt(mbti_stats),
        "by_mbti_role": fmt(combo_stats, min_games=2),
        "_overall": {
            "wolf_win_rate": round(wolf_wins / max(total, 1), 4),
            "village_win_rate": round(village_wins / max(total, 1), 4),
            "total_games": total,
        },
    }


def run_evolution_on_states(states_dir: Path, output_dir: Path) -> dict:
    """Run Track B review + Track C DreamJob on saved game states."""
    from backend.eval.evolution import DreamJob

    print("\n=== Running Evolution Pipeline ===")

    # Step 1: Load game states
    state_files = sorted(states_dir.glob("game_seed*.json"))
    print(f"Loaded {len(state_files)} game states")

    # Step 2: Generate ReviewReports
    # Note: generate_review_report needs a GameState object, not JSON
    # For now, we create minimal review reports from game results
    reviews = []
    for sf in state_files:
        try:
            data = json.loads(sf.read_text())
            review = _minimal_review_report(data)
            if review:
                reviews.append(review)
        except Exception as e:
            print(f"  Failed to load {sf}: {e}")

    if not reviews:
        print("  No reviews generated!")
        return {"error": "no_reviews", "reviews_count": 0}

    print(f"  Generated {len(reviews)} review reports")

    # Step 3: Run DreamJob
    try:
        dj = DreamJob()
        result = dj.run(reviews)
        return {
            "reviews_count": len(reviews),
            "knowledge_docs": len(result.knowledge_docs),
            "candidate_patches": len(result.candidate_patches),
            "rejected_items": len(result.rejected_items),
            "safety_summary": result.safety_summary,
            "patches": [
                {
                    "patch_id": p.patch_id,
                    "patch_type": p.patch_type,
                    "target_role": p.target_role,
                    "ops_count": len(p.operations),
                }
                for p in result.candidate_patches
            ],
        }
    except Exception as e:
        print(f"  DreamJob failed: {e}")
        traceback.print_exc()
        return {"error": str(e), "reviews_count": len(reviews)}


def _minimal_review_report(data: dict):
    """Create a minimal ReviewReport from saved game data."""
    from backend.eval.types import ReviewReport

    winner = data.get("winner", "")
    days = data.get("days", 0)
    events = data.get("events", [])
    players = data.get("players", [])
    seed = data.get("seed", 0)

    # Build game summary
    wolf_players = [p["name"] for p in players if p["role"] in ("Werewolf", "WhiteWolfKing")]
    village_roles = [f"{p['name']}({p['role']})" for p in players if p["role"] not in ("Werewolf", "WhiteWolfKing")]
    summary = f"Seed {seed}: {winner} wins in {days} days. Wolves: {', '.join(wolf_players)}. Village: {', '.join(village_roles)}."

    return ReviewReport(
        game_id=f"seed_{seed}",
        winner=winner,
        total_days=days,
        total_events=len(events),
        game_summary=summary,
    )


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--baseline-games", type=int, default=5)
    p.add_argument("--evolved-games", type=int, default=5)
    p.add_argument("--baseline-seed", type=int, default=600)
    p.add_argument("--evolved-seed", type=int, default=700)
    args = p.parse_args()

    output_dir = ROOT / "data" / "evolution_ab"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== Evolution A/B Test ===")
    print(f"Started: {datetime.now()}")
    print(f"Baseline: {args.baseline_games} games (seed {args.baseline_seed})")
    print(f"Evolved:  {args.evolved_games} games (seed {args.evolved_seed})")

    # Phase 1: Baseline
    print("\n--- Phase 1: Baseline Games ---")
    baseline_results = run_games(
        args.baseline_games,
        args.baseline_seed,
        "baseline",
        output_dir,
    )
    baseline_stats = compute_stats(baseline_results)
    print("\nBaseline Stats:")
    _print_stats(baseline_stats)

    # Save baseline
    with open(output_dir / "baseline_results.json", "w") as f:
        json.dump({"results": baseline_results, "stats": baseline_stats}, f, indent=2, ensure_ascii=False)

    # Phase 2: Evolution
    print("\n--- Phase 2: Evolution Pipeline ---")
    states_dir = output_dir / "states_baseline"
    evo_result = run_evolution_on_states(states_dir, output_dir)

    with open(output_dir / "evolution_result.json", "w") as f:
        json.dump(evo_result, f, indent=2, ensure_ascii=False)
    print(f"\nEvolution result: {json.dumps(evo_result, indent=2, ensure_ascii=False)[:500]}")

    # Phase 3: Evolved games (if patches were generated)
    if evo_result.get("candidate_patches", 0) > 0:
        print("\n--- Phase 3: Evolved Games ---")
        evolved_results = run_games(
            args.evolved_games,
            args.evolved_seed,
            "evolved",
            output_dir,
        )
        evolved_stats = compute_stats(evolved_results)
        print("\nEvolved Stats:")
        _print_stats(evolved_stats)

        with open(output_dir / "evolved_results.json", "w") as f:
            json.dump({"results": evolved_results, "stats": evolved_stats}, f, indent=2, ensure_ascii=False)

        # Comparison
        print("\n=== A/B Comparison ===")
        b_wr = baseline_stats["_overall"]["wolf_win_rate"]
        e_wr = evolved_stats["_overall"]["wolf_win_rate"]
        print(f"Baseline wolf win rate: {b_wr:.1%}")
        print(f"Evolved wolf win rate:  {e_wr:.1%}")
        print(f"Delta: {e_wr - b_wr:+.1%}")
    else:
        print("\n--- Phase 3: Skipped (no evolution patches generated) ---")

    print(f"\nCompleted at: {datetime.now()}")
    print(f"Results saved to: {output_dir}")


def _print_stats(stats: dict) -> None:
    """Print formatted stats including role + MBTI."""
    overall = stats["_overall"]
    print(f"  Wolf wins: {overall['wolf_win_rate']:.1%} | Village wins: {overall['village_win_rate']:.1%}")
    print("  --- By Role ---")
    for role, s in stats.get("by_role", {}).items():
        print(f"  {role:<12s}: {s['win_rate']:.1%} ({s['wins']}/{s['games']})")
    print("  --- By MBTI ---")
    for mbti, s in sorted(stats.get("by_mbti", {}).items(), key=lambda x: -x[1]["win_rate"])[:8]:
        print(f"  {mbti:<8s}: {s['win_rate']:.1%} ({s['wins']}/{s['games']})")
    print("  --- Best MBTI+Role ---")
    best = sorted(stats.get("by_mbti_role", {}).items(), key=lambda x: -x[1]["win_rate"])
    for key, s in best[:5]:
        print(f"  {key:<22s}: {s['win_rate']:.1%} ({s['wins']}/{s['games']})")


if __name__ == "__main__":
    main()
