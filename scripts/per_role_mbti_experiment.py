"""Per-role × MBTI Track C experiment with systematic MBTI coverage.

Ensures each of 16 MBTI × 6 roles gets baseline + Track C samples.
Cycles MBTI assignments across games using a balanced design.

Usage:
  python scripts/per_role_mbti_experiment.py --games 50 --model deepseek-v4-flash
  → 50 baseline + 50 Track C = 100 games, ~2.5 hours with v4-flash
  → ~700 player records, ~3 per MBTI-role combo
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


def assign_mbti_balanced(seed: int, players: list) -> dict[str, str]:
    """Assign MBTI to players using a round-robin to ensure coverage."""
    assignments: dict[str, str] = {}
    for i, p in enumerate(players):
        mbti_idx = (seed * 7 + i) % len(ALL_MBTI)
        assignments[p.id] = ALL_MBTI[mbti_idx]
    return assignments


def run_one(seed: int, track_c: bool) -> dict:
    os.environ["COGNITIVE_ENABLE_TRACK_C"] = "1" if track_c else "0"
    os.environ["COGNITIVE_ENABLE_ANTI_PATTERNS"] = "0"  # isolate Track C effect

    from backend.agents.characters import build_character_roster
    from backend.agents.factory import create_agents
    from backend.engine.game import WerewolfGame
    from backend.engine.rules import build_players

    players = build_players(seed=seed)
    mbti_map = assign_mbti_balanced(seed, players)

    # Build character roster normally, then override MBTI
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
        # Strict mode kills game on invalid LLM decision — skip this seed
        msg = str(e)[:100]
        print(f"  seed={seed} GAME_ERROR: {msg}")
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
    parser.add_argument("--games", type=int, default=50)
    parser.add_argument("--model", type=str, default="deepseek-v4-flash")
    parser.add_argument("--output", type=str, default="data/experiment/per_role_mbti_track_c.jsonl")
    args = parser.parse_args()
    os.environ["ANTHROPIC_MODEL"] = args.model
    n = args.games

    all_players = []
    skipped = 0
    for mode, track_c in [("Baseline", False), ("Track C", True)]:
        label = "Track C ON" if track_c else "Track C OFF"
        print(f"\n{'=' * 60}\n  {label} ({n} games, MBTI-balanced)\n{'=' * 60}")
        for s in range(1, n + 1):
            t0 = time.time()
            result = run_one(s, track_c)
            elapsed = time.time() - t0
            players = result["players"]
            if result.get("winner") == "error":
                skipped += 1
                continue
            all_players.extend(players)
            wins = sum(1 for p in players if p["won"])
            print(f"  seed={s:>3} {result['winner']:<8} d={result['day']} won={wins}/{len(players)} {elapsed:.0f}s")

    os.makedirs("data/experiment", exist_ok=True)
    with open(args.output, "w") as f:
        for p in all_players:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\nSaved {len(all_players)} records → {args.output}")

    # Analysis
    by_role_mbti: dict[tuple[str, str, bool], list[bool]] = defaultdict(list)
    for p in all_players:
        by_role_mbti[(p["role"], p["mbti"], p["track_c"])].append(p["won"])

    print(f"\n{'=' * 80}")
    print("  MBTI × ROLE TRACK C EFFECTIVENESS")
    print(f"{'=' * 80}")
    print(f"\n{'Role':<12s} {'MBTI':<6s} {'Base WR':>8s} {'TC WR':>8s} {'Δ':>7s}  {'n_base':>6s} {'n_tc':>6s}")
    print("-" * 60)
    for role in ALL_ROLES:
        for mbti in ALL_MBTI:
            base = by_role_mbti.get((role, mbti, False), [])
            tc = by_role_mbti.get((role, mbti, True), [])
            if len(base) < 2 or len(tc) < 2:
                continue
            b_rate = sum(base) / len(base)
            t_rate = sum(tc) / len(tc)
            delta = t_rate - b_rate
            print(
                f"  {role:<12s} {mbti:<6s} {b_rate:>7.1%} {t_rate:>7.1%} {delta:>+6.1%}  {len(base):>6d} {len(tc):>6d}"
            )

    # Summary: per-role average Δ
    print(f"\n{'Role':<12s} {'Avg Δ':>7s}  {'Base n':>7s} {'TC n':>7s}")
    print("-" * 40)
    for role in ALL_ROLES:
        base_all = [p["won"] for p in all_players if p["role"] == role and not p["track_c"]]
        tc_all = [p["won"] for p in all_players if p["role"] == role and p["track_c"]]
        if base_all and tc_all:
            avg_delta = sum(tc_all) / len(tc_all) - sum(base_all) / len(base_all)
            print(f"  {role:<12s} {avg_delta:>+6.1%}  {len(base_all):>7d} {len(tc_all):>7d}")


if __name__ == "__main__":
    main()
