"""Evolution test: run game → review → extract patches → measure impact.

Usage:
  python scripts/evolution_test.py --games 5
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.engine.game import WerewolfGame
from backend.eval.evolution import DreamJob
from backend.eval.review import generate_review_report


def run_evolution_test(n_games: int = 5, start_seed: int = 500) -> None:
    """Run games, generate reviews, extract evolution candidates."""
    output_dir = ROOT / "data" / "evolution_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    game_results = []

    print(f"=== Evolution Test: {n_games} games with review ===")
    print(f"Started: {datetime.now()}")

    dj = DreamJob()

    for i in range(n_games):
        seed = start_seed + i
        t0 = time.perf_counter()
        print(f"\n[{i + 1}/{n_games}] Game seed={seed}...")

        try:
            # Step 1: Run game
            game = WerewolfGame(seed=seed, player_count=7)
            state = game.play()
            elapsed = time.perf_counter() - t0

            winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
            print(f"  Winner: {winner}, Days: {state.day}, Time: {elapsed:.0f}s")

            game_results.append(
                {
                    "seed": seed,
                    "winner": winner,
                    "days": state.day,
                    "duration_s": round(elapsed, 1),
                }
            )

            # Step 2: Generate review report (fast mode, 1 iteration)
            print("  Generating review report...")
            try:
                report = generate_review_report(state, max_iterations=1)
                if report:
                    reports.append(report)
                    evo_count = len(report.evolution_candidates) if report.evolution_candidates else 0
                    print(f"  Review OK, evolution_candidates: {evo_count}")
                else:
                    print("  Review returned None")
            except Exception as e:
                print(f"  Review failed: {e}")

        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  FAILED: {e}")
            traceback.print_exc()

    # Step 3: Run DreamJob on all reports
    print(f"\n=== Running DreamJob on {len(reports)} reports ===")
    if reports:
        try:
            result = dj.run(reports)
            print(f"Accepted patches: {len(result.accepted_patches)}")
            print(f"Rejected: {len(result.rejected_items)}")
            print(f"Safety: {result.safety_summary}")

            # Print patch details
            for i, patch in enumerate(result.accepted_patches):
                print(f"\n--- Patch {i + 1} ---")
                print(f"Role: {patch.target_role}")
                print(f"Situation: {patch.situation_pattern[:100]}...")
                print(f"Recommendation: {patch.recommended_action[:100]}...")
                print(f"Quality: {patch.quality_score:.2f}, Confidence: {patch.confidence:.2f}")

            # Save results
            summary = {
                "timestamp": datetime.now().isoformat(),
                "games": game_results,
                "reports_count": len(reports),
                "accepted_patches": len(result.accepted_patches),
                "rejected_items": len(result.rejected_items),
                "safety_summary": result.safety_summary,
            }
            with open(output_dir / "evolution_summary.json", "w") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            print(f"\nResults saved to {output_dir / 'evolution_summary.json'}")

        except Exception as e:
            print(f"DreamJob failed: {e}")
            traceback.print_exc()
    else:
        print("No reports to process!")

    print(f"\n=== Evolution test complete at {datetime.now()} ===")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=5)
    p.add_argument("--start-seed", type=int, default=500)
    args = p.parse_args()
    run_evolution_test(n_games=args.games, start_seed=args.start_seed)
