"""Multi-tier concurrent experiment: compare 4 agent configurations.

Tiers:
  1. baseline     — no anti-patterns, no Track C (pure MBTI + Role)
  2. anti_only    — static anti-patterns only, no Track C
  3. trackc_only  — Track C dynamic strategy only, no anti-patterns
  4. both         — anti-patterns + Track C (current production default)

Runs each tier in a SEPARATE PROCESS so each has its own httpx connection pool.
Within each tier, games run sequentially (no concurrent API calls within a tier).

Usage:
  python scripts/multi_tier_experiment.py --games 12
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

TIERS = {
    "baseline":    {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "0"},
    "anti_only":   {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "0"},
    "trackc_only": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "1"},
    "both":        {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "1"},
}


def bootstrap_ci(data: list[float], n_bootstrap: int = 10000, ci: float = 0.95) -> dict:
    """Compute bootstrap confidence interval for win rate data.

    Args:
        data: List of binary outcomes (1=win, 0=loss).
        n_bootstrap: Number of bootstrap resamples.
        ci: Confidence level (default 0.95 for 95% CI).

    Returns:
        dict with mean, ci_lower, ci_upper, n_samples.
    """
    if len(data) < 5:
        return {
            "mean": float(np.mean(data)) if data else 0.0,
            "ci_lower": None, "ci_upper": None,
            "n_samples": len(data),
            "warning": "Insufficient samples for bootstrap (< 5)",
        }

    data_arr = np.array(data)
    means = []
    rng = np.random.RandomState(42)
    for _ in range(n_bootstrap):
        sample = rng.choice(data_arr, size=len(data_arr), replace=True)
        means.append(float(np.mean(sample)))

    means_arr = np.array(means)
    alpha = (1 - ci) / 2
    return {
        "mean": round(float(np.mean(data_arr)), 4),
        "ci_lower": round(float(np.percentile(means_arr, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(means_arr, (1 - alpha) * 100)), 4),
        "n_samples": len(data),
        "n_bootstrap": n_bootstrap,
    }

# Script that runs one tier's games
_WORKER_SCRIPT = """
import json, os, sys, time, traceback, warnings
sys.path.insert(0, {root!r})
warnings.filterwarnings("ignore")

from backend.engine.game import WerewolfGame

tier = {tier!r}
env_vars = {env_vars!r}
seeds = {seeds!r}
output_file = {output_file!r}
experiment_id = {experiment_id!r}
require_db = {require_db!r}

for key, val in env_vars.items():
    os.environ[key] = val

# Set experiment metadata in env for cross-process tracking
os.environ["EXPERIMENT_ID"] = experiment_id
# H6: Per-tier experiment ID for isolating strategy knowledge between tiers.
# Each tier tags its docs with a unique ID so the retrieval layer can filter
# out Track C candidate docs from tiers where Track C is disabled.
os.environ["TIER_EXPERIMENT_ID"] = "{experiment_id}_{tier}"
os.environ["DB_POOL_SIZE"] = "1"
os.environ["DB_MAX_OVERFLOW"] = "0"

# DB initialization (best-effort for experiment tracking)
db_available = False
strategy_snapshot = None
if require_db:
    try:
        from backend.db.database import init_db, SessionLocal
        init_db()
        db = SessionLocal()
        try:
            from sqlalchemy import func
            from backend.db.models import StrategyKnowledgeDoc
            q = db.query(func.count(StrategyKnowledgeDoc.id)).filter(
                StrategyKnowledgeDoc.status == "active"
            )
            active_count = q.scalar()
            strategy_snapshot = {{
                "active_count": active_count or 0,
                "timestamp": time.time(),
            }}
        except Exception:
            strategy_snapshot = {{"active_count": -1, "timestamp": time.time()}}
        finally:
            db.close()
        db_available = True
        print(f"[{{tier}}] DB connected, strategy_snapshot={{strategy_snapshot}}", flush=True)
    except Exception as e:
        print(f"[{{tier}}] DB init failed (non-fatal): {{e}}", flush=True)
        traceback.print_exc()

for i, seed in enumerate(seeds):
    t0 = time.perf_counter()
    result = {{"seed": seed, "tier": tier, "index": i + 1, "total": len(seeds),
              "experiment_id": experiment_id}}
    if strategy_snapshot:
        result["strategy_snapshot"] = strategy_snapshot
    try:
        game = WerewolfGame(seed=seed, player_count=7)
        state = game.play()
        elapsed = time.perf_counter() - t0
        winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
        result["winner"] = winner
        result["days"] = state.day
        result["duration_s"] = round(elapsed, 1)
        result["game_id"] = getattr(state, "id", "") or ""
        result["players"] = []
        fb = 0
        for p in state.players:
            role = p.role.value
            team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
            won = team == winner
            mbti = (p.persona or {{}}).get("mbti", "UNKNOWN") if hasattr(p, "persona") else "UNKNOWN"
            fb += getattr(p, "fallback_count", 0) or 0
            result["players"].append({{
                "name": p.name, "role": role, "mbti": mbti,
                "alive": p.alive, "won": won, "seat": p.seat,
            }})
        result["fallback_count"] = fb
        print(f"[{{tier}}] {{i+1}}/{{len(seeds)}} seed={{seed}} winner={{winner}} days={{state.day}} time={{elapsed:.0f}}s fb={{fb}} game_id={{result['game_id']}}", flush=True)
    except Exception as e:
        elapsed = time.perf_counter() - t0
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()[:500]
        result["duration_s"] = round(elapsed, 1)
        print(f"[{{tier}}] {{i+1}}/{{len(seeds)}} seed={{seed}} FAILED: {{e}}", flush=True)
        traceback.print_exc()
    with open(output_file, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\\n")
print(f"DONE_{{tier}}", flush=True)
"""


def _run_tier_subprocess(
    tier: str, seeds: list[int], output_file: Path,
    experiment_id: str = "", require_db: bool = True,
) -> subprocess.Popen:
    """Launch a subprocess to run games for one tier."""
    script = _WORKER_SCRIPT.format(
        root=str(ROOT),
        tier=tier,
        env_vars=TIERS[tier],
        seeds=seeds,
        output_file=str(output_file),
        experiment_id=experiment_id,
        require_db=require_db,
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )


def compile_stats(results: list[dict]) -> dict:
    """Compile role-level, MBTI-level, and team-level statistics."""
    role_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "games": 0}
    )
    role_outcomes: dict[str, list] = defaultdict(list)
    mbti_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "games": 0}
    )
    team_stats: dict[str, dict] = defaultdict(
        lambda: {"wins": 0, "games": 0}
    )

    for r in results:
        if "error" in r:
            continue
        winner = r["winner"]
        for p in r.get("players", []):
            role = p["role"]
            team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
            mbti = p.get("mbti", "UNKNOWN")
            won = p["won"]
            role_stats[role]["wins"] += 1 if won else 0
            role_stats[role]["games"] += 1
            role_outcomes[role].append(1 if won else 0)
            mbti_stats[mbti]["wins"] += 1 if won else 0
            mbti_stats[mbti]["games"] += 1
            team_stats[team]["wins"] += 1 if won else 0
            team_stats[team]["games"] += 1

    def _fmt(raw: dict) -> dict:
        out = {}
        for key, d in sorted(raw.items()):
            n = max(d["games"], 1)
            out[key] = {"games": d["games"], "wins": d["wins"], "win_rate": round(d["wins"] / n, 4)}
        return out

    # Compute bootstrap CIs for each role
    role_stats_fmt = _fmt(role_stats)
    for role_key in role_stats_fmt:
        outcomes = role_outcomes.get(role_key, [])
        ci = bootstrap_ci(outcomes)
        role_stats_fmt[role_key]["win_rate_ci"] = {
            "lower": ci["ci_lower"],
            "upper": ci["ci_upper"],
        }

    return {"role_stats": role_stats_fmt, "mbti_stats": _fmt(mbti_stats), "team_stats": _fmt(team_stats)}


def _print_comparison(tier_summaries: dict) -> None:
    """Print comparison tables to stdout."""
    tiers = list(tier_summaries.keys())
    roles = sorted(set().union(*[set(s.get("role_stats", {}).keys()) for s in tier_summaries.values()]))
    mbti_types = sorted(set().union(*[set(s.get("mbti_stats", {}).keys()) for s in tier_summaries.values()]))

    print(f"\n{'='*110}")
    print("MULTI-TIER WIN RATE COMPARISON")
    print(f"{'='*110}")

    # Team-level
    print(f"\n--- Team-Level Win Rates ---")
    header = f"{'Team':<12s}"
    for t in tiers:
        header += f" {t:>14s}"
    print(header)
    print("-" * 90)
    for team in ["village", "wolf"]:
        row = f"{team:<12s}"
        for tier in tiers:
            ts = tier_summaries[tier].get("team_stats", {}).get(team, {})
            wr = ts.get("win_rate", 0)
            g = ts.get("games", 0)
            row += f" {wr:>8.1%} ({g:>3d}g)"
        print(row)

    # Role-level
    print(f"\n--- Role-Level Win Rates (with 95% bootstrap CI) ---")
    header = f"{'Role':<16s}"
    for t in tiers:
        header += f" {t:>24s}"
    print(header)
    print("-" * 110)
    for role in roles:
        row = f"{role:<16s}"
        for tier in tiers:
            rs = tier_summaries[tier].get("role_stats", {}).get(role, {})
            wr = rs.get("win_rate", 0)
            g = rs.get("games", 0)
            ci_info = rs.get("win_rate_ci", {})
            ci_lower = ci_info.get("lower")
            ci_upper = ci_info.get("upper")
            if ci_lower is not None and ci_upper is not None:
                row += f" {wr:>6.1%} [{ci_lower:.1%}-{ci_upper:.1%}] ({g:>2d}g)"
            else:
                row += f" {wr:>6.1%} (---) ({g:>2d}g)"
        print(row)

    # MBTI-level
    print(f"\n--- MBTI-Level Win Rates ---")
    header = f"{'MBTI':<8s}"
    for t in tiers:
        header += f" {t:>14s}"
    print(header)
    print("-" * 90)
    for mbti in mbti_types:
        row = f"{mbti:<8s}"
        for tier in tiers:
            ms = tier_summaries[tier].get("mbti_stats", {}).get(mbti, {})
            wr = ms.get("win_rate", 0)
            g = ms.get("games", 0)
            row += f" {wr:>8.1%} ({g:>3d}g)"
        print(row)

    # Meta
    print(f"\n--- Meta ---")
    header = f"{'Metric':<20s}"
    for t in tiers:
        header += f" {t:>14s}"
    print(header)
    print("-" * 90)
    for metric in ["game_count", "error_count", "avg_duration_s", "total_fallbacks"]:
        row = f"{metric:<20s}"
        for tier in tiers:
            val = tier_summaries[tier].get(metric, "-")
            if isinstance(val, float):
                row += f" {val:>13.1f} "
            else:
                row += f" {str(val):>14s}"
        print(row)
    print(f"{'='*110}")


def run_experiment(n_games: int = 12, require_db: bool = True) -> None:
    """Run all tiers in parallel subprocesses.

    Args:
        n_games: Number of games per tier.
        require_db: If True, workers attempt DB connection for experiment tracking.
                   Set False for offline/local runs without a DB server.
    """
    experiment_id = f"exp-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    output_dir = ROOT / "data" / "experiment" / "multi_tier"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_file = output_dir / "summary.json"

    print(f"{'='*70}")
    print(f"Multi-Tier Experiment: {n_games} games x {len(TIERS)} tiers = {n_games * len(TIERS)} total")
    print(f"Experiment ID: {experiment_id}")
    print(f"Started: {datetime.now()}")
    print(f"Tiers: {list(TIERS.keys())}")
    print(f"Mode: 4 parallel subprocesses, each running {n_games} games sequentially")
    print(f"Require DB: {require_db}")
    print(f"{'='*70}")

    # Launch one subprocess per tier
    processes: dict[str, subprocess.Popen] = {}
    tier_files: dict[str, Path] = {}
    for tier in TIERS:
        seeds = [1000 + list(TIERS.keys()).index(tier) * 1000 + i for i in range(n_games)]
        out_file = output_dir / f"{tier}.jsonl"
        out_file.write_text("")  # truncate
        tier_files[tier] = out_file
        proc = _run_tier_subprocess(tier, seeds, out_file, experiment_id=experiment_id, require_db=require_db)
        processes[tier] = proc
        print(f"  Started [{tier}] PID={proc.pid} ({n_games} games, seeds {seeds[0]}-{seeds[-1]})")

    # Monitor all subprocesses
    t0 = time.perf_counter()
    import threading
    import queue

    output_queue: queue.Queue = queue.Queue()

    def _reader(proc, tier_name):
        for line in proc.stdout:
            output_queue.put((tier_name, line.rstrip()))

    readers = []
    for tier, proc in processes.items():
        t = threading.Thread(target=_reader, args=(proc, tier), daemon=True)
        t.start()
        readers.append(t)

    # Wait for all to complete, printing output as it arrives
    while any(p.poll() is None for p in processes.values()):
        try:
            tier_name, line = output_queue.get(timeout=5)
            print(f"  {line}", flush=True)
        except queue.Empty:
            # Print heartbeat
            elapsed = time.perf_counter() - t0
            running = [t for t, p in processes.items() if p.poll() is None]
            if running:
                print(f"  [heartbeat] {elapsed:.0f}s running: {running}", flush=True)

    # Drain remaining output
    for t in readers:
        t.join(timeout=2)
    while not output_queue.empty():
        try:
            tier_name, line = output_queue.get_nowait()
            print(f"  {line}", flush=True)
        except queue.Empty:
            break

    total_elapsed = time.perf_counter() - t0

    # Load results and compile stats
    tier_summaries = {}
    all_results: dict[str, list] = {}
    for tier in TIERS:
        results = []
        if tier_files[tier].exists():
            for line in tier_files[tier].read_text().strip().split("\n"):
                if line.strip():
                    results.append(json.loads(line))
        all_results[tier] = results
        tier_summaries[tier] = compile_stats(results)
        tier_summaries[tier]["game_count"] = len([r for r in results if "error" not in r])
        tier_summaries[tier]["error_count"] = len([r for r in results if "error" in r])
        times = [r.get("duration_s", 0) for r in results if "error" not in r]
        tier_summaries[tier]["avg_duration_s"] = round(sum(times) / max(len(times), 1), 1)
        tier_summaries[tier]["total_fallbacks"] = sum(r.get("fallback_count", 0) for r in results if "error" not in r)

    # Save combined results
    combined_file = output_dir / "results.jsonl"
    with open(combined_file, "w") as f:
        for tier in TIERS:
            for r in all_results[tier]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "experiment_id": experiment_id,
        "completed_at": datetime.now().isoformat(),
        "games_per_tier": n_games,
        "total_games": n_games * len(TIERS),
        "total_duration_s": round(total_elapsed, 1),
        "mode": "4 parallel subprocesses, sequential within each",
        "require_db": require_db,
        "tiers": tier_summaries,
    }
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    _print_comparison(tier_summaries)

    print(f"\nExperiment complete! Total: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
    print(f"Summary: {summary_file}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=12)
    args = p.parse_args()
    run_experiment(n_games=args.games)
