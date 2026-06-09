"""Minimal LLM batch runner — no AB tournament, no DreamJob — purely:

1. Plays N games where every player is an LLMAgent
2. Persists via existing save_game_start / save_game_end pipeline (which also
   triggers save_published_review for Track B)
3. Writes a per-batch JSON log so we can quantify progress incrementally

Designed to be safe to run in background for hundreds of games and to be
restartable. Use --seeds to specify exactly which seeds to use; use
--seed-start / --seed-count for sequential ranges.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.agents.llm_agent import LLMAgent
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players

HEALTH_DIR = ROOT / "data" / "health"
HEALTH_DIR.mkdir(parents=True, exist_ok=True)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def play_one_game(seed: int) -> dict[str, Any]:
    """Plays a single LLM game. Returns metric blob. Any exception bubbles up."""
    started = time.time()
    players = build_players(seed=seed)
    agents = create_agents(players, {"type": "llm", "seed": seed})
    # Track which model each seat got (factory writes to player.model_name)
    seat_models = {p.seat: p.model_name for p in players}
    game = WerewolfGame(players=players, agents=agents, seed=seed)
    state = game.play()
    duration = time.time() - started

    decisions = state.decision_records
    fallback_decisions = [
        rec
        for rec in decisions
        if bool((rec.parsed_action or {}).get("metadata", {}).get("fallback"))
        or bool((rec.parsed_action or {}).get("agent_fallback"))
        or str((rec.parsed_action or {}).get("metadata", {}).get("source", "")) == "fallback"
    ]
    llm_decisions = [
        rec for rec in decisions if str((rec.parsed_action or {}).get("metadata", {}).get("source", "")) == "llm"
    ]

    return {
        "seed": seed,
        "game_id": state.id,
        "winner": state.winner.value if state.winner else None,
        "days": state.day,
        "events": len(state.events),
        "decisions": len(decisions),
        "llm_decisions": len(llm_decisions),
        "fallback_decisions": len(fallback_decisions),
        "duration_s": round(duration, 2),
        "seat_models": seat_models,
    }


def run_batch(seeds: list[int], strict: bool, batch_label: str) -> Path:
    LLMAgent.STRICT_NO_FALLBACK = strict
    started_at = utcnow_iso()
    log_path = HEALTH_DIR / f"llm_batch_{batch_label}.jsonl"
    summary_path = HEALTH_DIR / f"llm_batch_{batch_label}.summary.json"

    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    print(f"[{started_at}] Starting LLM batch — {len(seeds)} games, strict={strict}", flush=True)

    with open(log_path, "a", encoding="utf-8") as logf:
        for i, seed in enumerate(seeds, 1):
            t0 = time.time()
            print(f"[{utcnow_iso()}] ({i}/{len(seeds)}) seed={seed} starting", flush=True)
            try:
                metric = play_one_game(seed)
                metric["_batch_index"] = i
                metric["_at"] = utcnow_iso()
                logf.write(json.dumps(metric, ensure_ascii=False) + "\n")
                logf.flush()
                succeeded.append(metric)
                print(
                    f"  ✓ winner={metric['winner']} days={metric['days']} "
                    f"llm/fallback={metric['llm_decisions']}/{metric['fallback_decisions']} "
                    f"took={metric['duration_s']}s",
                    flush=True,
                )
            except Exception as exc:
                err = {
                    "seed": seed,
                    "_batch_index": i,
                    "_at": utcnow_iso(),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "duration_s": round(time.time() - t0, 2),
                }
                traceback.print_exc()
                logf.write(json.dumps({"failed": err}, ensure_ascii=False) + "\n")
                logf.flush()
                failed.append(err)
                print(f"  ✗ seed={seed} FAILED: {type(exc).__name__}: {exc}", flush=True)

    finished_at = utcnow_iso()
    summary = {
        "batch_label": batch_label,
        "started_at": started_at,
        "finished_at": finished_at,
        "seeds_total": len(seeds),
        "games_succeeded": len(succeeded),
        "games_failed": len(failed),
        "winner_breakdown": _winner_breakdown(succeeded),
        "model_usage": _model_usage(succeeded),
        "avg_duration_s": round(sum(g["duration_s"] for g in succeeded) / max(len(succeeded), 1), 2),
        "fallback_decision_total": sum(g["fallback_decisions"] for g in succeeded),
        "llm_decision_total": sum(g["llm_decisions"] for g in succeeded),
        "errors": [{"seed": e["seed"], "error_type": e["error_type"]} for e in failed[:20]],
        "log_path": str(log_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\n[{finished_at}] Batch done — {len(succeeded)}/{len(seeds)} ok, "
        f"{len(failed)} failed. Summary: {summary_path}",
        flush=True,
    )
    return summary_path


def _winner_breakdown(games: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for g in games:
        key = str(g.get("winner") or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


def _model_usage(games: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for g in games:
        for _seat, model in (g.get("seat_models") or {}).items():
            key = model or "<empty>"
            out[key] = out.get(key, 0) + 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", help="Explicit seeds list")
    ap.add_argument("--seed-start", type=int, default=1)
    ap.add_argument("--seed-count", type=int, default=10)
    ap.add_argument("--strict-fallback", default="false", help="If true, any LLM fallback aborts the game")
    ap.add_argument("--label", default=None, help="Batch label (default UTC timestamp)")
    args = ap.parse_args()

    if args.seeds:
        seeds = list(args.seeds)
    else:
        seeds = list(range(args.seed_start, args.seed_start + args.seed_count))

    strict = args.strict_fallback.lower() not in {"false", "0", "no", "off"}
    label = args.label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_batch(seeds, strict=strict, batch_label=label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
