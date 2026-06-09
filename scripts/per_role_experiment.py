"""Per-role Track C effectiveness experiment.

Runs N games with Track C ON vs OFF, tracking per-player (role, mbti, won).
Computes per-role win rate delta to quantify Track C's impact per role.

7-player setup: Seer×1 Witch×1 Hunter×1 Guard×1 Villager×1 Werewolf×2
→ Each game yields 7 data points (1 per player slot).

Usage:
  python scripts/per_role_experiment.py --games 20 --model deepseek-v4-flash
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


def run_one(seed: int, track_c: bool) -> dict:
    """Run a single game, return per-player results."""
    os.environ["COGNITIVE_ENABLE_TRACK_C"] = "1" if track_c else "0"
    # Use agent-level retrieval policy
    os.environ["AIWEREWOLF_RETRIEVAL_POLICY"] = "same_role_all_mbti"

    from backend.agents.characters import build_character_roster
    from backend.agents.factory import create_agents
    from backend.engine.game import WerewolfGame
    from backend.engine.rules import build_players

    players = build_players(seed=seed)
    roster = build_character_roster(seed=seed, players=players)
    agents = create_agents(
        players,
        {
            "type": "llm",
            "seed": seed,
            "character_map": {p.id: roster.get(p.id) for p in players if p.id in roster},
        },
    )
    game = WerewolfGame(players=players, agents=agents, seed=seed, max_days=4)
    state = game.play()

    per_player = []
    for p in state.players:
        agent = game.agents.get(p.id)
        mbti = "UNKNOWN"
        if agent:
            prof = getattr(agent, "_profile", None)
            if prof and getattr(prof, "persona", None):
                mbti = prof.persona.mbti or "UNKNOWN"
        role = p.role
        is_wolf = role in ("Werewolf", "WhiteWolfKing")
        won = (state.winner.value == "wolf" and is_wolf) or (state.winner.value == "village" and not is_wolf)
        per_player.append({"role": role, "mbti": mbti, "won": won, "track_c": track_c, "seed": seed})

    return {"seed": seed, "winner": state.winner.value, "day": state.day, "players": per_player, "track_c": track_c}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--model", type=str, default="deepseek-v4-flash")
    parser.add_argument("--output", type=str, default="data/experiment/per_role_track_c.jsonl")
    args = parser.parse_args()

    os.environ["ANTHROPIC_MODEL"] = args.model
    n = args.games

    all_players = []
    for mode, track_c in [("Baseline", False), ("Track C", True)]:
        label = "TRACK C ON" if track_c else "TRACK C OFF"
        print(f"\n{'=' * 50}\n  {label} ({n} games)\n{'=' * 50}")
        for s in range(1, n + 1):
            t0 = time.time()
            try:
                result = run_one(s, track_c)
                elapsed = time.time() - t0
                players = result["players"]
                all_players.extend(players)
                wins = sum(1 for p in players if p["won"])
                print(
                    f"  seed={s:>3}  winner={result['winner']:<8} day={result['day']}  "
                    f"players_won={wins}/{len(players)}  {elapsed:.0f}s"
                )
            except Exception as e:
                print(f"  seed={s:>3}  FAILED: {e}")

    # Save raw data
    os.makedirs("data/experiment", exist_ok=True)
    with open(args.output, "w") as f:
        for p in all_players:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\nSaved {len(all_players)} player records to {args.output}")

    # ── Analysis ──
    print(f"\n{'=' * 60}")
    print("  PER-ROLE TRACK C EFFECTIVENESS")
    print(f"{'=' * 60}")

    # Group by (role, track_c)
    by_key: dict[tuple[str, bool], list[bool]] = defaultdict(list)
    by_mbti: dict[tuple[str, str, bool], list[bool]] = defaultdict(list)
    for p in all_players:
        by_key[(p["role"], p["track_c"])].append(p["won"])
        by_mbti[(p["role"], p["mbti"], p["track_c"])].append(p["won"])

    print(f"\n{'Role':<14s} {'Baseline':>10s} {'Track C':>10s} {'Δ':>8s}  {'n_base':>6s} {'n_tc':>6s}")
    print("-" * 70)
    for role in ["Seer", "Witch", "Hunter", "Guard", "Villager", "Werewolf"]:
        base_wins = by_key.get((role, False), [])
        tc_wins = by_key.get((role, True), [])
        if not base_wins or not tc_wins:
            continue
        b_rate = sum(base_wins) / len(base_wins)
        t_rate = sum(tc_wins) / len(tc_wins)
        delta = t_rate - b_rate
        print(f"  {role:<14s} {b_rate:>9.1%} {t_rate:>9.1%} {delta:>+7.1%}  {len(base_wins):>6d} {len(tc_wins):>6d}")

    # Per MBTI x Role
    print(f"\n{'MBTI':<6s} {'Role':<14s} {'Baseline':>8s} {'Track C':>8s} {'Δ':>7s}  {'n':>4s}")
    print("-" * 60)
    mbti_combos = sorted(by_mbti.keys())
    for role, mbti, tc in mbti_combos:
        if tc:
            continue  # only show one row per combo
        base = by_mbti.get((role, mbti, False), [])
        tc_list = by_mbti.get((role, mbti, True), [])
        if len(base) < 2 or len(tc_list) < 2:
            continue
        b_rate = sum(base) / len(base)
        t_rate = sum(tc_list) / len(tc_list)
        delta = t_rate - b_rate
        if abs(delta) > 0.05:  # only show meaningful deltas
            print(
                f"  {mbti:<6s} {role:<14s} {b_rate:>7.1%} {t_rate:>7.1%} {delta:>+6.1%}  {len(base) + len(tc_list):>4d}"
            )


if __name__ == "__main__":
    main()
