"""Simple A/B comparison: optimized vs baseline for a few seeds.

Usage:
    python3 scripts/compare_ab.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["ANTHROPIC_MODEL"] = "deepseek-v4-flash"

SEEDS = [1, 2, 3, 4, 5]


def run_one(seed, disable=False):
    """Run one game. Returns dict with metrics."""
    if disable:
        os.environ["_DISABLE_SKIP_OPTIMISATIONS"] = "1"
    else:
        os.environ.pop("_DISABLE_SKIP_OPTIMISATIONS", None)

    # Token tracker
    tracker = {"calls": 0, "input": 0, "output": 0}

    # Instrument AnthropicClient class
    import backend.llm.anthropic_client as _ac_mod

    _orig_chat_sync = _ac_mod.AnthropicClient.chat_sync

    def _instrumented_chat_sync(self, messages, **kwargs):
        r = _orig_chat_sync(self, messages, **kwargs)
        u = r.get("usage", {})
        tracker["calls"] += 1
        tracker["input"] += u.get("prompt_tokens", 0)
        tracker["output"] += u.get("completion_tokens", 0)
        return r

    _ac_mod.AnthropicClient.chat_sync = _instrumented_chat_sync
    try:
        from scripts.llm_game_smoke import _assert_strict_full_game
        from scripts.llm_game_smoke import _run_one

        t0 = time.time()
        state = _run_one(seed, 4)
        elapsed = time.time() - t0
        _assert_strict_full_game(state)

        fb = sum(1 for r in state.decision_records if r.fallback_used)
        inv = sum(1 for r in state.decision_records if not r.is_valid)
        return {
            "seed": seed,
            "winner": state.winner.value,
            "day": state.day,
            "decisions": len(state.decision_records),
            "calls": tracker["calls"],
            "input_tokens": tracker["input"],
            "output_tokens": tracker["output"],
            "total_tokens": tracker["input"] + tracker["output"],
            "time_s": round(elapsed, 1),
            "fallbacks": fb,
            "invalids": inv,
        }
    finally:
        _ac_mod.AnthropicClient.chat_sync = _orig_chat_sync


def main():
    results = {"baseline": [], "optimized": []}
    for mode, disabled in [("baseline", True), ("optimized", False)]:
        label = "BASELINE" if disabled else "OPTIMIZED"
        print(f"\n{'=' * 50}")
        print(f"  {label}")
        for s in SEEDS:
            try:
                r = run_one(s, disabled)
                results[mode].append(r)
                print(
                    f"  seed={s} {r['winner']:<8} day={r['day']}  calls={r['calls']:>3}  tokens={r['total_tokens']:>8,}  {r['time_s']}s"
                )
            except Exception as e:
                print(f"  seed={s} FAILED: {e}")

    # Summary
    b = results["baseline"]
    o = results["optimized"]
    if not b or not o:
        print("Not enough data")
        return

    def avg(items, key):
        return sum(key(r) for r in items) / len(items)

    print(f"\n{'=' * 60}")
    print("  COMPARISON SUMMARY")
    print(f"{'=' * 60}")
    print(f"  {'Metric':<35} {'Baseline':>10} {'Optimized':>10} {'Delta':>10} {'Change':>8}")
    print(f"  {'-' * 73}")

    for name, key, fmt, lb in [
        ("API calls (avg)", lambda r: r["calls"], ".1f", True),
        ("Input tokens (avg)", lambda r: r["input_tokens"], ",.0f", True),
        ("Output tokens (avg)", lambda r: r["output_tokens"], ",.0f", True),
        ("Total tokens (avg)", lambda r: r["total_tokens"], ",.0f", True),
        ("Wall time (avg, seconds)", lambda r: r["time_s"], ".1f", True),
        ("Game days (avg)", lambda r: r["day"], ".1f", False),
    ]:
        bv = avg(b, key)
        ov = avg(o, key)
        delta = ov - bv
        pct = (delta / bv * 100) if bv else 0
        d = "↓" if ((lb and delta < 0) or (not lb and delta > 0)) else "↑"
        print(
            f"  {name:<35} {bv:>{len(fmt) + 4},{fmt}} {ov:>{len(fmt) + 4},{fmt}} {delta:>+10,.1f} {d}{abs(pct):>6.1f}%"
        )

    # Quality
    print("\n  GAME QUALITY:")
    bw = {r["winner"]: sum(1 for r2 in b if r2["winner"] == r["winner"]) for r in b}
    ow = {r["winner"]: sum(1 for r2 in o if r2["winner"] == r["winner"]) for r in o}
    for w in sorted(set(list(bw) + list(ow))):
        print(f"    winner={w:<8} baseline={bw.get(w, 0)} optimized={ow.get(w, 0)}")
    print(f"    fallbacks:  baseline={sum(r['fallbacks'] for r in b)} optimized={sum(r['fallbacks'] for r in o)}")
    print(f"    invalids:   baseline={sum(r['invalids'] for r in b)} optimized={sum(r['invalids'] for r in o)}")


if __name__ == "__main__":
    main()
