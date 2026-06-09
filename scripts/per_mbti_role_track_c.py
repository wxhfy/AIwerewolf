"""Large-scale MBTI×Role Track C experiment with anti-patterns ON.

Target: n≥8 per MBTI×Role×Track_C combo (96 combos × 8 = 768 records/mode)
→ ~110 games/mode → 220 games total → ~2-3 hours with v4-flash

Usage:
  python scripts/per_mbti_role_track_c.py --games 100 --model deepseek-v4-flash
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["AIWEREWOLF_RETRIEVAL_POLICY"] = "same_role_all_mbti"
os.environ["COGNITIVE_ENABLE_ANTI_PATTERNS"] = "1"  # production setting
os.environ["PYTHONUNBUFFERED"] = "1"

ALL_MBTI = [
    "INTJ",
    "INTP",
    "ENTJ",
    "ENTP",
    "INFJ",
    "INFP",
    "ENFJ",
    "ENFP",
    "ISTJ",
    "ISFJ",
    "ESTJ",
    "ESFJ",
    "ISTP",
    "ISFP",
    "ESTP",
    "ESFP",
]
ALL_ROLES = ["Seer", "Witch", "Hunter", "Guard", "Villager", "Werewolf"]


def run_one(seed: int, track_c: bool) -> dict:
    os.environ["COGNITIVE_ENABLE_TRACK_C"] = "1" if track_c else "0"

    from backend.agents.characters import build_character_roster
    from backend.agents.factory import create_agents
    from backend.engine.game import WerewolfGame
    from backend.engine.rules import build_players

    players = build_players(seed=seed)

    # MBTI round-robin: (seed*7 + i) % 16
    mbti_map = {}
    for i, p in enumerate(players):
        mbti_map[p.id] = ALL_MBTI[(seed * 7 + i) % 16]

    roster = build_character_roster(seed=seed, players=players)
    for p in players:
        if p.is_ai and p.id in roster:
            target_mbti = mbti_map[p.id]
            char = roster[p.id]
            if hasattr(char, "persona") and char.persona:
                char.persona.mbti = target_mbti
            if hasattr(char, "profile") and char.profile:
                char.profile.mbti = target_mbti

    character_map = {p.id: roster[p.id] for p in players if p.id in roster}
    agents = create_agents(players, {"type": "llm", "seed": seed, "character_map": character_map})
    game = WerewolfGame(players=players, agents=agents, seed=seed, max_days=4)

    try:
        state = game.play()
    except RuntimeError as e:
        msg = str(e)[:120]
        return {"seed": seed, "winner": "error", "day": 0, "players": [], "track_c": track_c, "error": msg}

    per_player = []
    for p in state.players:
        is_wolf = p.role in ("Werewolf", "WhiteWolfKing")
        won = (state.winner.value == "wolf" and is_wolf) or (state.winner.value == "village" and not is_wolf)
        per_player.append(
            {
                "role": p.role,
                "mbti": mbti_map.get(p.id, "UNKNOWN"),
                "won": won,
                "track_c": track_c,
                "seed": seed,
            }
        )
    return {"seed": seed, "winner": state.winner.value, "day": state.day, "players": per_player, "track_c": track_c}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--model", type=str, default="deepseek-v4-flash")
    parser.add_argument("--output", type=str, default="data/experiment/mbti_role_track_c.jsonl")
    parser.add_argument("--append", action="store_true", help="Append to existing output")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["both", "baseline", "track_c"],
        default="both",
        help="Which mode(s) to run (for parallelization)",
    )
    args = parser.parse_args()
    os.environ["ANTHROPIC_MODEL"] = args.model
    n = args.games

    _mode = "a" if args.append else "w"
    os.makedirs("data/experiment", exist_ok=True)
    out_f = open(args.output, _mode)

    all_players = []
    skipped = 0
    total_elapsed = 0.0

    modes_to_run = []
    if args.mode in ("both", "baseline"):
        modes_to_run.append(("Baseline", False))
    if args.mode in ("both", "track_c"):
        modes_to_run.append(("Track C", True))

    for mode_label, track_c in modes_to_run:
        label = "TC=ON " if track_c else "TC=OFF"
        print(f"\n{'=' * 60}")
        print(f"  {label} — {n} games, anti-patterns=ON, model={args.model}")
        print(f"{'=' * 60}")

        for s in range(1, n + 1):
            t0 = time.time()
            result = run_one(s, track_c)
            elapsed = time.time() - t0
            total_elapsed += elapsed

            if result.get("winner") == "error":
                skipped += 1
                print(f"  [{s:>3}/{n}] SKIP seed={s}: {result.get('error', '')[:80]}")
                continue

            players = result["players"]
            all_players.extend(players)
            for p in players:
                out_f.write(json.dumps(p, ensure_ascii=False) + "\n")
            out_f.flush()

            wins = sum(1 for p in players if p["won"])
            avg_t = total_elapsed / (s + (0 if track_c else 0) + (n if track_c else 0) - skipped)
            eta = avg_t * (2 * n - s - (n if track_c else 0))
            print(
                f"  [{s:>3}/{n}] seed={s:>3} {result['winner']:<8} d={result['day']} "
                f"w={wins}/7 {elapsed:.0f}s  ETA~{eta / 60:.0f}min"
            )

    out_f.close()
    print(f"\n{'=' * 60}")
    print(f"  DONE: {len(all_players)} records, {skipped} skipped, {total_elapsed / 60:.1f}min total")
    print(f"  Output: {args.output}")

    # ── Analysis ──
    by_key = defaultdict(list)
    for p in all_players:
        by_key[(p["mbti"], p["role"], p["track_c"])].append(p["won"])

    # Count combos with sufficient data
    good = sum(
        1
        for m in ALL_MBTI
        for r in ALL_ROLES
        if len(by_key.get((m, r, False), [])) >= 3 and len(by_key.get((m, r, True), [])) >= 3
    )

    print(f"\n  MBTI×Role combos with ≥3 baseline AND ≥3 Track C: {good}/96")

    # Per-role pooled summary
    by_role = defaultdict(list)
    for p in all_players:
        by_role[(p["role"], p["track_c"])].append(p["won"])

    print(f"\n  {'Role':<14s} {'Base WR':>8s} {'TC WR':>8s} {'Δ':>7s}  {'nB':>5s} {'nTC':>5s}")
    print(f"  {'-' * 50}")
    for role in ALL_ROLES:
        b = by_role.get((role, False), [])
        t = by_role.get((role, True), [])
        if b and t:
            print(
                f"  {role:<14s} {sum(b) / len(b):>7.1%} {sum(t) / len(t):>7.1%} "
                f"{sum(t) / len(t) - sum(b) / len(b):>+6.1%}  {len(b):>5d} {len(t):>5d}"
            )

    # MBTI×Role detail (only combos with ≥3 per mode)
    print(f"\n  {'MBTI':<6s} {'Role':<12s} {'Base':>7s} {'TC':>7s} {'Δ':>6s}  n")
    print(f"  {'-' * 45}")
    details = []
    for mbti in ALL_MBTI:
        for role in ALL_ROLES:
            b = by_key.get((mbti, role, False), [])
            t = by_key.get((mbti, role, True), [])
            if len(b) >= 3 and len(t) >= 3:
                delta = sum(t) / len(t) - sum(b) / len(b)
                details.append((mbti, role, sum(b) / len(b), sum(t) / len(t), delta, len(b), len(t)))

    details.sort(key=lambda x: -x[4])
    for mbti, role, br, tr, delta, nb, nt in details:
        marker = " ↑" if delta > 0.05 else (" ↓" if delta < -0.05 else "  ")
        print(f"  {mbti:<6s} {role:<12s} {br:>6.1%} {tr:>6.1%} {delta:>+5.1%}{marker} {nb}+{nt}")

    # By cognitive style
    print("\n  === By Cognitive Style (pooled) ===")
    analysts = ["INTJ", "INTP", "ENTJ", "ENTP"]
    diplomats = ["INFJ", "INFP", "ENFJ", "ENFP"]
    sentinels = ["ISTJ", "ISFJ", "ESTJ", "ESFJ"]
    explorers = ["ISTP", "ISFP", "ESTP", "ESFP"]

    for style_name, style_mbtis in [
        ("Analyst(NT)", analysts),
        ("Diplomat(NF)", diplomats),
        ("Sentinel(SJ)", sentinels),
        ("Explorer(SP)", explorers),
    ]:
        for role in ALL_ROLES:
            b_all = [
                p["won"] for p in all_players if p["role"] == role and not p["track_c"] and p["mbti"] in style_mbtis
            ]
            t_all = [p["won"] for p in all_players if p["role"] == role and p["track_c"] and p["mbti"] in style_mbtis]
            if len(b_all) >= 6 and len(t_all) >= 6:
                delta = sum(t_all) / len(t_all) - sum(b_all) / len(b_all)
                marker = " ↑" if delta > 0.05 else (" ↓" if delta < -0.05 else "  ")
                print(
                    f"  {style_name:<16s} {role:<12s} {sum(b_all) / len(b_all):>6.1%} → {sum(t_all) / len(t_all):>6.1%} "
                    f"Δ={delta:>+5.1%}{marker}  n={len(b_all)}+{len(t_all)}"
                )


if __name__ == "__main__":
    main()
