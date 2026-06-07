"""Benchmark: API call reduction optimizations (Plan A + Plan B).

Compares optimized vs baseline across multiple seeds with:
- API call count, token usage, wall-clock time
- Per-optimization trigger frequency
- Game quality metrics (winner, days, fallback/invalid rates)

Usage:
    python3 scripts/bench_optimizations.py [--seeds 1-5] [--model deepseek-v4-flash]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TokenTracker:
    """Per-game token accounting."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.api_calls = 0
        self.skip_triggers = {
            "vote_single_target": 0,  # Plan B: vote with 1 legal target
            "divine_single_target": 0,  # Plan B: seer with 1 legal target
            "guard_single_target": 0,  # Plan B: guard with 1 legal target
            "attack_single_target": 0,  # Plan B: wolf with 1 legal target
            "witch_no_potion": 0,  # Plan B: witch with 0 potions
            "vote_reuse_speech": 0,  # Plan A: vote reuses tentative_vote
        }

    def record_api_call(self, usage: dict):
        self.api_calls += 1
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def total_skips(self) -> int:
        return sum(self.skip_triggers.values())


def _patch_for_tracking(tracker: TokenTracker, disable_optimizations: bool = False):
    """Monkey-patch the agent and client to track metrics."""
    from backend.agents.cognitive import agent as agent_mod
    from backend.llm.anthropic_client import AnthropicClient

    # Patch client for token tracking
    _orig_chat = AnthropicClient.chat_sync

    def _tracked_chat(self, messages, **kwargs):
        result = _orig_chat(self, messages, **kwargs)
        tracker.record_api_call(result.get("usage", {}))
        return result

    AnthropicClient.chat_sync = _tracked_chat

    if disable_optimizations:
        return  # Don't patch skip tracking

    # Patch agent decisions to count skip triggers
    _vote_orig = agent_mod.CognitiveAgent.vote

    def _vote(self):
        obs = self._observe()
        legal_ids = {p.id for p in obs.legal_targets}
        if len(legal_ids) == 1:
            tracker.skip_triggers["vote_single_target"] += 1
        else:
            tentative = self._pipeline.get_tentative_vote()
            if tentative and tentative.get("raw"):
                t_target = self._resolve_target(tentative["raw"])
                if t_target and t_target in legal_ids:
                    if not self._has_meaningful_new_info_since_speech(obs):
                        tracker.skip_triggers["vote_reuse_speech"] += 1
        return _vote_orig(self)

    agent_mod.CognitiveAgent.vote = _vote

    _divine_orig = agent_mod.CognitiveAgent.divine

    def _divine(self):
        obs = self._observe()
        if len({p.id for p in obs.legal_targets}) == 1:
            tracker.skip_triggers["divine_single_target"] += 1
        return _divine_orig(self)

    agent_mod.CognitiveAgent.divine = _divine

    _guard_orig = agent_mod.CognitiveAgent.guard

    def _guard(self):
        obs = self._observe()
        if len({p.id for p in obs.legal_targets}) == 1:
            tracker.skip_triggers["guard_single_target"] += 1
        return _guard_orig(self)

    agent_mod.CognitiveAgent.guard = _guard

    _attack_orig = agent_mod.CognitiveAgent.attack

    def _attack(self):
        obs = self._observe()
        if len({p.id for p in obs.legal_targets}) == 1:
            tracker.skip_triggers["attack_single_target"] += 1
        return _attack_orig(self)

    agent_mod.CognitiveAgent.attack = _attack

    _witch_orig = agent_mod.CognitiveAgent.witch_act

    def _witch_act(self, victim_id):
        if self._witch_save_used and self._witch_poison_used:
            tracker.skip_triggers["witch_no_potion"] += 1
        return _witch_orig(self, victim_id)

    agent_mod.CognitiveAgent.witch_act = _witch_act


def run_one_game(seed: int, tracker: TokenTracker, disable_optimizations: bool = False) -> dict:
    """Run a single game and return quality metrics."""
    from scripts.llm_game_smoke import _run_one

    if disable_optimizations:
        os.environ["_DISABLE_SKIP_OPTIMISATIONS"] = "1"
    else:
        os.environ.pop("_DISABLE_SKIP_OPTIMISATIONS", None)

    _patch_for_tracking(tracker, disable_optimizations=disable_optimizations)

    state = _run_one(seed, max_days=4)

    talk_events = [e for e in state.events if str(e.type.value) == "CHAT_MESSAGE"]
    vote_events = [e for e in state.events if str(e.type.value) == "VOTE_CAST"]
    fallback_count = sum(1 for e in talk_events + vote_events if e.payload.get("agent_fallback"))
    invalid_count = sum(1 for r in state.decision_records if not r.is_valid)

    return {
        "seed": seed,
        "winner": state.winner.value if state.winner else "unknown",
        "day": state.day,
        "talk_events": len(talk_events),
        "vote_events": len(vote_events),
        "decisions": len(state.decision_records),
        "fallbacks": fallback_count,
        "invalids": invalid_count,
    }


def _clear_module_cache():
    for mod in list(sys.modules):
        if "backend.agents" in mod or "backend.llm" in mod or "backend.engine" in mod:
            del sys.modules[mod]


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=str, default="1-5")
    parser.add_argument("--model", type=str, default="deepseek-v4-flash")
    parser.add_argument("--provider", type=str, default="anthropic")
    args = parser.parse_args()

    seed_range = args.seeds.split("-")
    seed_start, seed_end = int(seed_range[0]), int(seed_range[-1])
    seeds = list(range(seed_start, seed_end + 1))

    os.environ.setdefault("LLM_PROVIDER", args.provider)
    os.environ.setdefault("ANTHROPIC_MODEL", args.model)

    all_results = {"baseline": [], "optimized": []}

    for mode, disabled in [("baseline", True), ("optimized", False)]:
        label = "BASELINE (no optimizations)" if disabled else "OPTIMIZED (A+B enabled)"
        print(f"\n{'=' * 60}")
        print(f"  {label}")
        print(f"  Model: {args.model}  Seeds: {seed_start}-{seed_end}")
        print(f"{'=' * 60}")

        for seed in seeds:
            _clear_module_cache()
            tracker = TokenTracker()
            t0 = time.time()

            try:
                game = run_one_game(seed, tracker, disable_optimizations=disabled)
                elapsed = time.time() - t0

                result = {
                    **game,
                    "tracker": tracker,
                    "time_s": round(elapsed, 1),
                }
                all_results[mode].append(result)

                print(
                    f"  seed={seed:>2}  winner={game['winner']:<8} day={game['day']}  "
                    f"calls={tracker.api_calls:>3}  tokens={tracker.total_tokens:>8,}  "
                    f"time={elapsed:.0f}s"
                )
                if not disabled and tracker.total_skips > 0:
                    triggered = [k for k, v in tracker.skip_triggers.items() if v > 0]
                    print(f"         skips: {tracker.total_skips} ({', '.join(triggered)})")

            except Exception as exc:
                print(f"  seed={seed:>2}  FAILED: {exc}")
                all_results[mode].append({"seed": seed, "error": str(exc)})

    # ── Aggregate report ──
    print(f"\n{'=' * 60}")
    print("  COMPARISON SUMMARY")
    print(f"{'=' * 60}")

    # Print detailed table
    b_ok = [r for r in all_results["baseline"] if "tracker" in r]
    o_ok = [r for r in all_results["optimized"] if "tracker" in r]

    col_width = 50

    def _avg(items, key_fn):
        return sum(key_fn(r) for r in items) / len(items) if items else 0

    if b_ok and o_ok:
        print(f"\n{'Metric':<{col_width}} {'Baseline':>12} {'Optimized':>12} {'Delta':>10} {'Change':>8}")
        print("-" * (col_width + 12 + 12 + 10 + 8))

        rows = [
            ("API calls (avg/game)", lambda r: r["tracker"].api_calls, ".1f", True),
            ("Input tokens (avg/game)", lambda r: r["tracker"].input_tokens, ",.0f", True),
            ("Output tokens (avg/game)", lambda r: r["tracker"].output_tokens, ",.0f", True),
            ("Total tokens (avg/game)", lambda r: r["tracker"].total_tokens, ",.0f", True),
            ("Wall time (avg/game, seconds)", lambda r: r["time_s"], ".1f", True),
            ("Game days (avg)", lambda r: r["day"], ".1f", False),
        ]
        for name, fn, fmt, lb in rows:
            b_val = _avg(b_ok, fn)
            o_val = _avg(o_ok, fn)
            delta = o_val - b_val
            pct = (delta / b_val * 100) if b_val else 0
            direction = "↓" if ((lb and delta < 0) or (not lb and delta > 0)) else "↑"
            print(f"  {name:<{col_width-2}} {b_val:>{len(fmt)+4},{fmt}} {o_val:>{len(fmt)+4},{fmt}} {delta:>+10,.1f} {direction}{abs(pct):>6.1f}%")

        _print_row("API calls (avg/game)", b_avg["calls"], o_avg["calls"], ".1f", True)
        _print_row("Input tokens (avg/game)", b_avg["input"], o_avg["input"], ",.0f", True)
        _print_row("Output tokens (avg/game)", b_avg["output"], o_avg["output"], ",.0f", True)
        _print_row("Total tokens (avg/game)", b_avg["total"], o_avg["total"], ",.0f", True)
        _print_row("Wall time (avg/game)", b_avg["time"], o_avg["time"], ".1f", True)

    # Trigger frequency
    if o_ok:
        print(f"\n{'─' * 80}")
        print("  OPTIMIZATION TRIGGER FREQUENCY (per game)")
        trigger_totals = {}
        for r in o_ok:
            for k, v in r["tracker"].skip_triggers.items():
                trigger_totals[k] = trigger_totals.get(k, 0) + v

        total_games = len(o_ok)
        for name, count in sorted(trigger_totals.items(), key=lambda x: -x[1]):
            avg = count / total_games
            bar = "█" * int(avg * 5)
            print(f"  {name:<35s} {count:>3d} total  {avg:>5.1f}/game  {bar}")

    # Game quality comparison
    print(f"\n{'─' * 80}")
    print("  GAME QUALITY (WINNER / ERRORS)")

    b_winners = {}
    o_winners = {}
    b_errors = {"fallbacks": 0, "invalids": 0}
    o_errors = {"fallbacks": 0, "invalids": 0}
    for r in b_ok:
        b_winners[r["winner"]] = b_winners.get(r["winner"], 0) + 1
        b_errors["fallbacks"] += r["fallbacks"]
        b_errors["invalids"] += r["invalids"]
    for r in o_ok:
        o_winners[r["winner"]] = o_winners.get(r["winner"], 0) + 1
        o_errors["fallbacks"] += r["fallbacks"]
        o_errors["invalids"] += r["invalids"]

    print(f"  {'':20s} {'Baseline':>10} {'Optimized':>10}")
    for winner in sorted(set(list(b_winners) + list(o_winners))):
        b_w = b_winners.get(winner, 0)
        o_w = o_winners.get(winner, 0)
        print(f"  Winner={winner:<14s} {b_w:>10d} {o_w:>10d}")
    print(f"  Fallbacks:         {b_errors['fallbacks']:>10d} {o_errors['fallbacks']:>10d}")
    print(f"  Invalid decisions: {b_errors['invalids']:>10d} {o_errors['invalids']:>10d}")


if __name__ == "__main__":
    main()
