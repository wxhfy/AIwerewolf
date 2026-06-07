#!/usr/bin/env python3
"""Comprehensive multi-tier experiment with detailed per-player statistics.

Runs N games per tier, collecting win rates stratified by:
  - Team (village / wolf)
  - Role (Seer, Witch, Hunter, Guard, Villager, Werewolf)
  - MBTI personality type

Tiers:
  1. baseline     — no anti-patterns, no Track C (pure MBTI + Role)
  2. anti_only    — static anti-patterns only
  3. trackc_only  — Track C dynamic strategy only
  4. both         — anti-patterns + Track C (production default)

Results saved incrementally (one JSONL line per game) with a full report at end.

Usage:
  python scripts/run_experiment.py --games 20          # 20 games per tier
  python scripts/run_experiment.py --games 12 --tiers baseline,both  # fast compare
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.engine.game import WerewolfGame
from backend.llm.env import load_env_file

load_env_file()

# ---------------------------------------------------------------------------
ALL_TIERS = {
    "baseline": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "0"},
    "anti_only": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "0"},
    "trackc_only": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "0", "COGNITIVE_ENABLE_TRACK_C": "1"},
    "both": {"COGNITIVE_ENABLE_ANTI_PATTERNS": "1", "COGNITIVE_ENABLE_TRACK_C": "1"},
}
OUT_DIR = ROOT / "data" / "experiment"


# ---------------------------------------------------------------------------
def bootstrap_ci(data: list[float], n_bootstrap: int = 10000, ci: float = 0.95) -> dict:
    if len(data) < 2:
        m = round(np.mean(data), 4) if data else 0.0
        return {"mean": m, "ci_lower": m, "ci_upper": m, "n": len(data)}
    arr = np.array(data)
    means = [float(np.mean(np.random.RandomState(42).choice(arr, len(arr), replace=True))) for _ in range(n_bootstrap)]
    alpha = (1 - ci) / 2
    return {
        "mean": round(float(np.mean(arr)), 4),
        "ci_lower": round(float(np.percentile(means, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(means, (1 - alpha) * 100)), 4),
        "n": len(data),
    }


# ---------------------------------------------------------------------------
def run_one_game(tier: str, seed: int, env_vars: dict, player_count: int = 7) -> dict:
    for k, v in env_vars.items():
        os.environ[k] = v
    os.environ["TIER_EXPERIMENT_ID"] = f"exp_{tier}"

    t0 = time.time()
    try:
        game = WerewolfGame(seed=seed, player_count=player_count)
        game.initialize()
        game.play()
        dur = int(time.time() - t0)
        winner = game.state.winner or "unknown"
        players = []
        for p in game.state.players:
            role = p.role
            is_wolf = role in ("Werewolf", "WhiteWolfKing")
            won = (winner == "wolf" and is_wolf) or (winner == "village" and not is_wolf)
            mbti = "UNKNOWN"
            persona = getattr(p, "persona", None) or {}
            if isinstance(persona, dict):
                mbti = persona.get("mbti", "UNKNOWN")
            elif hasattr(persona, "mbti"):
                mbti = persona.mbti or "UNKNOWN"
            agent = game.agents.get(p.id)
            if mbti == "UNKNOWN" and agent:
                prof = getattr(agent, "_profile", None)
                if prof and getattr(prof, "persona", None):
                    mbti = prof.persona.mbti or "UNKNOWN"
            players.append(
                {"name": p.name, "role": role, "mbti": mbti, "team": "wolf" if is_wolf else "village", "won": won}
            )
        return {
            "tier": tier,
            "seed": seed,
            "winner": winner,
            "day": game.state.day,
            "duration_s": dur,
            "players": players,
        }
    except Exception as e:
        import traceback

        return {
            "tier": tier,
            "seed": seed,
            "error": str(e)[:300],
            "traceback": traceback.format_exc()[-500:],
            "duration_s": int(time.time() - t0),
            "players": [],
        }


# ---------------------------------------------------------------------------
def generate_report(all_results: list[dict], tier_names: list[str]) -> str:
    tier_games: dict[str, list[dict]] = defaultdict(list)
    for r in all_results:
        if "error" not in r:
            tier_games[r["tier"]].append(r)

    L = []
    S = "=" * 90
    L.append(S)
    L.append("MULTI-TIER EXPERIMENT REPORT")
    L.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"Provider: {os.getenv('LLM_PROVIDER', '?')} | Model: {os.getenv('DSV4FLASH_MODEL', '?')}")
    L.append(S)

    # ── 1. Overall ──
    L.append("\n## 1. OVERALL WIN RATES\n")
    L.append(f"{'Tier':<16} {'Games':>6} {'Village%':>12} {'Wolf%':>12} {'AvgDays':>9}")
    L.append("-" * 60)
    for t in tier_names:
        gs = tier_games.get(t, [])
        n = len(gs)
        if n == 0:
            L.append(f"{t:<16} {0:>6} {'--':>12} {'--':>12} {'--':>9}")
            continue
        vw = sum(1 for g in gs if g["winner"] == "village")
        ww = sum(1 for g in gs if g["winner"] == "wolf")
        ad = sum(g.get("day", 0) for g in gs) / n
        L.append(f"{t:<16} {n:>6} {vw / n * 100:>11.1f}% {ww / n * 100:>11.1f}% {ad:>8.1f}")

    # ── 2. Team win rates ──
    L.append(f"\n{'─' * 90}\n## 2. TEAM WIN RATES (95% Bootstrap CI)\n")
    for team_name, team_label in [("village", "Village (好人阵营)"), ("wolf", "Wolf (狼人阵营)")]:
        L.append(f"\n### {team_label}\n")
        L.append(f"{'Tier':<16} {'Games':>6} {'WinRate':>12} {'95% CI':>22} {'vs Baseline':>16}")
        L.append("-" * 80)
        base_wr = None
        for t in tier_names:
            gs = tier_games.get(t, [])
            outcomes = [1.0 if p["won"] else 0.0 for g in gs for p in g.get("players", []) if p["team"] == team_name]
            if not outcomes:
                L.append(f"{t:<16} {0:>6} {'--':>12}")
                continue
            ci = bootstrap_ci(outcomes)
            wr = ci["mean"]
            if base_wr is None:
                base_wr = wr
                ds = "--"
            else:
                ds = f"{(wr - base_wr) * 100:+.1f}%"
            L.append(
                f"{t:<16} {len(gs):>6} {wr * 100:>10.1f}%  [{ci['ci_lower'] * 100:.1f}–{ci['ci_upper'] * 100:.1f}%]  {ds:>12}"
            )

    # ── 3. Role win rates ──
    L.append(f"\n{'─' * 90}\n## 3. ROLE WIN RATES (95% Bootstrap CI)\n")
    for role in ["Seer", "Witch", "Hunter", "Guard", "Villager", "Werewolf"]:
        L.append(f"\n### {role}\n")
        L.append(f"{'Tier':<16} {'Samples':>8} {'WinRate':>12} {'95% CI':>22} {'vs Baseline':>16}")
        L.append("-" * 80)
        base_wr = None
        for t in tier_names:
            gs = tier_games.get(t, [])
            outcomes = [1.0 if p["won"] else 0.0 for g in gs for p in g.get("players", []) if p["role"] == role]
            if not outcomes:
                L.append(f"{t:<16} {0:>8} {'--':>12}")
                continue
            ci = bootstrap_ci(outcomes)
            wr = ci["mean"]
            if base_wr is None:
                base_wr = wr
                ds = "--"
            else:
                ds = f"{(wr - base_wr) * 100:+.1f}%"
            L.append(
                f"{t:<16} {len(outcomes):>8} {wr * 100:>10.1f}%  [{ci['ci_lower'] * 100:.1f}–{ci['ci_upper'] * 100:.1f}%]  {ds:>12}"
            )

    # ── 4. MBTI win rates ──
    L.append(f"\n{'─' * 90}\n## 4. MBTI WIN RATES\n")
    all_mbti = sorted(
        {
            p.get("mbti", "UNKNOWN")
            for t in tier_names
            for g in tier_games.get(t, [])
            for p in g.get("players", [])
            if p.get("mbti") and p["mbti"] != "UNKNOWN"
        }
    )
    for mbti in all_mbti:
        L.append(f"\n### {mbti}\n")
        L.append(f"{'Tier':<16} {'Samples':>8} {'WinRate':>12} {'vs Baseline':>16}")
        L.append("-" * 60)
        base_wr = None
        for t in tier_names:
            gs = tier_games.get(t, [])
            outcomes = [1.0 if p["won"] else 0.0 for g in gs for p in g.get("players", []) if p.get("mbti") == mbti]
            if not outcomes:
                L.append(f"{t:<16} {0:>8} {'--':>12}")
                continue
            ci = bootstrap_ci(outcomes)
            wr = ci["mean"]
            if base_wr is None:
                base_wr = wr
                ds = "--"
            else:
                ds = f"{(wr - base_wr) * 100:+.1f}%"
            L.append(f"{t:<16} {len(outcomes):>8} {wr * 100:>10.1f}%  {ds:>12}")

    # ── 5. Summary ──
    L.append(f"\n{'─' * 90}\n## 5. SUMMARY\n")
    for t in tier_names:
        gs = tier_games.get(t, [])
        n = len(gs)
        errs = sum(1 for r in all_results if r["tier"] == t and "error" in r)
        td = sum(g.get("duration_s", 0) for g in gs)
        L.append(f"  {t:<16}: {n} games, {errs} errors, {td / 60:.0f}min")
    L.append(f"\n{S}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Multi-tier experiment runner")
    p.add_argument("--games", type=int, default=20, help="Games per tier (default: 20)")
    p.add_argument("--tiers", type=str, default="baseline,anti_only,trackc_only,both")
    p.add_argument("--players", type=int, default=7)
    p.add_argument("--base-seed", type=int, default=1000)
    args = p.parse_args()

    tier_names = [t.strip() for t in args.tiers.split(",")]
    tiers = {n: ALL_TIERS[n] for n in tier_names if n in ALL_TIERS}
    if not tiers:
        print(f"ERROR: choose from {list(ALL_TIERS)}")
        sys.exit(1)

    n_games = args.games
    total = len(tiers) * n_games
    print(f"Experiment: {len(tiers)} tiers × {n_games} games = {total} total")
    print(f"Provider: {os.getenv('LLM_PROVIDER', '?')}  Model: {os.getenv('DSV4FLASH_MODEL', '?')}")
    print(f"Players/game: {args.players}\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eid = datetime.now().strftime("exp-%Y%m%d-%H%M%S")
    res_file = OUT_DIR / f"{eid}.jsonl"
    rep_file = OUT_DIR / f"{eid}_report.txt"

    # Resume
    done_set: set[tuple[str, int]] = set()
    if res_file.exists():
        with open(res_file) as f:
            for line in f:
                try:
                    r = json.loads(line.strip())
                    done_set.add((r["tier"], r["seed"]))
                except:
                    pass
        print(f"Resuming: {len(done_set)} games already done")

    queue = []
    for tn in tier_names:
        for i in range(n_games):
            sd = args.base_seed + i * 100 + list(tier_names).index(tn) * 10
            if (tn, sd) not in done_set:
                queue.append((tn, sd, tiers[tn]))
    pending = len(queue)
    done = total - pending
    print(f"Done: {done}, Pending: {pending}")
    if pending == 0:
        print("All done. Generating report...")
        all_r = [json.loads(l) for l in res_file.read_text().splitlines() if l.strip()]
        rep = generate_report(all_r, tier_names)
        print(rep)
        rep_file.write_text(rep, encoding="utf-8")
        print(f"\nReport: {rep_file}")
        return

    t0 = time.time()
    for idx, (tier, seed, env) in enumerate(queue):
        num = done + idx + 1
        eta = ""
        if idx > 0:
            elapsed = time.time() - t0
            eta = f" ETA: {elapsed / idx * (pending - idx) / 60:.0f}min"
        print(f"\n[{num}/{total}] {tier} seed={seed}{eta}", flush=True)
        result = run_one_game(tier, seed, env, args.players)
        d = result.get("duration_s", 0)
        if "error" in result:
            print(f"  FAILED ({d}s): {result['error'][:120]}", flush=True)
        else:
            print(
                f"  DONE ({d}s/{d / 60:.1f}min): Winner={result.get('winner', '?')}, Day={result.get('day', '?')}",
                flush=True,
            )
        res_file.open("a").write(json.dumps(result, ensure_ascii=False) + "\n")

        if (idx + 1) % 5 == 0 or idx == pending - 1:
            all_r = [json.loads(l) for l in res_file.read_text().splitlines() if l.strip()]
            rep = generate_report(all_r, tier_names)
            rep_file.write_text(rep, encoding="utf-8")
            print(f"  [interim report: {rep_file}]")

    # Final
    td = int(time.time() - t0)
    print(f"\n{'=' * 90}\nEXPERIMENT COMPLETE — {td}s ({td / 60:.0f}min/{td / 3600:.1f}h)\n{'=' * 90}")
    all_r = [json.loads(l) for l in res_file.read_text().splitlines() if l.strip()]
    rep = generate_report(all_r, tier_names)
    rep_file.write_text(rep, encoding="utf-8")
    print(rep)
    print(f"\nResults: {res_file}\nReport:  {rep_file}")


if __name__ == "__main__":
    main()
