"""LLM-only batch game runner with results tracking.

Runs N games with real LLM agents, tracks fallback/decision/performance metrics,
and writes a JSON report. Designed for the P1-6 requirement: 20+ LLM games with
fallback_count=0, token/latency/cost tracking.

Usage:
    python scripts/llm_batch_runner.py --seeds 7 11 13 17 19 --output data/health/llm_batch_report.json
    python scripts/llm_batch_runner.py --games 5 --output data/health/llm_batch_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType
from backend.engine.rules import build_players


@dataclass
class GameResult:
    seed: int
    winner: str | None = None
    day: int = 0
    total_decisions: int = 0
    llm_decisions: int = 0
    fallback_count: int = 0
    talk_count: int = 0
    vote_count: int = 0
    total_latency_ms: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cost_estimate_usd: float = 0.0
    error: str | None = None
    duration_s: float = 0.0


def run_one_game(seed: int) -> GameResult:
    """Run a single LLM game and collect metrics."""
    result = GameResult(seed=seed)
    t0 = time.perf_counter()

    try:
        players = build_players(seed=seed)
        agents = create_agents(players, {"type": "llm", "seed": seed})
        game = WerewolfGame(players=players, agents=agents, seed=seed)
        state = game.play()

        result.winner = state.winner.value if state.winner else None
        result.day = state.day
        result.duration_s = round(time.perf_counter() - t0, 2)

        # Count events
        for event in state.events:
            if event.type == EventType.CHAT_MESSAGE:
                result.talk_count += 1
                if event.payload.get("agent_source") == "llm":
                    result.llm_decisions += 1
                if event.payload.get("agent_fallback"):
                    result.fallback_count += 1
            elif event.type == EventType.VOTE_CAST:
                result.vote_count += 1
                if event.payload.get("agent_source") == "llm":
                    result.llm_decisions += 1
                if event.payload.get("agent_fallback"):
                    result.fallback_count += 1

        # Collect decision-level metrics
        for record in state.decision_records:
            result.total_decisions += 1
            if record.latency_ms:
                result.total_latency_ms += record.latency_ms
            if record.prompt_tokens:
                result.total_prompt_tokens += record.prompt_tokens
            if record.completion_tokens:
                result.total_completion_tokens += record.completion_tokens

        # Rough cost estimate (doubao pricing)
        if result.total_prompt_tokens > 0:
            result.cost_estimate_usd = round(
                result.total_prompt_tokens * 0.000001 + result.total_completion_tokens * 0.000002, 6
            )

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        result.duration_s = round(time.perf_counter() - t0, 2)
        traceback.print_exc()

    return result


def main():
    parser = argparse.ArgumentParser(description="LLM-only batch game runner")
    parser.add_argument(
        "--seeds", type=int, nargs="*", default=None, help="Specific seeds to run (default: 5 random games)"
    )
    parser.add_argument("--games", type=int, default=5, help="Number of games to run with random seeds")
    parser.add_argument("--output", type=str, default="data/health/llm_batch_report.json")
    parser.add_argument("--start-seed", type=int, default=1)
    args = parser.parse_args()

    if args.seeds:
        seeds = args.seeds
    else:
        seeds = list(range(args.start_seed, args.start_seed + args.games))

    results: list[GameResult] = []
    t0 = time.perf_counter()

    for i, seed in enumerate(seeds):
        print(f"\n[{i + 1}/{len(seeds)}] Seed={seed} ...", flush=True)
        result = run_one_game(seed)
        results.append(result)

        status = "OK" if not result.error else f"ERROR: {result.error}"
        print(
            f"  Winner={result.winner}, Day={result.day}, "
            f"Decisions={result.total_decisions}, Fallback={result.fallback_count}, "
            f"Duration={result.duration_s}s ({status})"
        )

        # Save incrementally
        _save_report(args.output, seeds[: i + 1], results, time.perf_counter() - t0)

    _save_report(args.output, seeds, results, time.perf_counter() - t0)
    _print_summary(results, time.perf_counter() - t0)
    return 0


def _save_report(path: str, seeds: list[int], results: list[GameResult], total_duration: float):
    completed = [r for r in results if not r.error]
    failed = [r for r in results if r.error]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_mode": "llm",
        "total_games": len(results),
        "seeds_requested": seeds,
        "completed": len(completed),
        "failed": len(failed),
        "total_duration_s": round(total_duration, 2),
        "avg_duration_s": round(sum(r.duration_s for r in completed) / max(len(completed), 1), 2),
        "fallback_count": sum(r.fallback_count for r in results),
        "total_decisions": sum(r.total_decisions for r in results),
        "llm_decisions": sum(r.llm_decisions for r in results),
        "total_prompt_tokens": sum(r.total_prompt_tokens for r in results),
        "total_completion_tokens": sum(r.total_completion_tokens for r in results),
        "total_cost_estimate_usd": round(sum(r.cost_estimate_usd for r in results), 6),
        "total_latency_ms": sum(r.total_latency_ms for r in results),
        "winners": {r.winner: sum(1 for rr in completed if rr.winner == r.winner) for r in completed},
        "games": [asdict(r) for r in results],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def _print_summary(results: list[GameResult], total_duration: float):
    completed = [r for r in results if not r.error]
    print(f"\n{'=' * 60}")
    print(f"Batch Summary: {len(completed)}/{len(results)} games completed")
    print(f"Total duration: {total_duration:.0f}s")
    if completed:
        wins = {}
        for r in completed:
            wins[r.winner] = wins.get(r.winner, 0) + 1
        print(f"Winners: {wins}")
        print(f"Avg decisions/game: {sum(r.total_decisions for r in completed) // len(completed)}")
        print(f"Total fallbacks: {sum(r.fallback_count for r in completed)}")
        print(f"Total tokens: {sum(r.total_prompt_tokens + r.total_completion_tokens for r in completed)}")
        print(f"Est. cost: ${sum(r.cost_estimate_usd for r in completed):.4f} USD")
    if any(r.error for r in results):
        print(f"Failed seeds: {[r.seed for r in results if r.error]}")


if __name__ == "__main__":
    raise SystemExit(main())
