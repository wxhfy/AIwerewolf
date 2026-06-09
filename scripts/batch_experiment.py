"""Batch experiment runner: runs N games per batch, appends to output, exits cleanly.
Designed to be called repeatedly to accumulate data without memory buildup.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["AIWEREWOLF_RETRIEVAL_POLICY"] = "same_role_all_mbti"
os.environ["COGNITIVE_ENABLE_ANTI_PATTERNS"] = "1"
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


def run_one(seed: int, track_c: bool) -> dict | None:
    os.environ["COGNITIVE_ENABLE_TRACK_C"] = "1" if track_c else "0"
    from backend.agents.characters import build_character_roster
    from backend.agents.factory import create_agents
    from backend.engine.game import WerewolfGame
    from backend.engine.rules import build_players

    players = build_players(seed=seed)
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
            {"role": p.role, "mbti": mbti_map.get(p.id, "UNKNOWN"), "won": won, "track_c": track_c, "seed": seed}
        )
    return {"seed": seed, "winner": state.winner.value, "day": state.day, "players": per_player, "track_c": track_c}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-seed", type=int, required=True)
    parser.add_argument("--end-seed", type=int, required=True)
    parser.add_argument("--track-c", type=str, default="off", choices=["off", "on"])
    parser.add_argument("--model", type=str, default="deepseek-v4-flash")
    parser.add_argument("--output", type=str, default="data/experiment/mbti_batch.jsonl")
    args = parser.parse_args()

    os.environ["ANTHROPIC_MODEL"] = args.model
    track_c = args.track_c == "on"
    os.makedirs("data/experiment", exist_ok=True)

    records = 0
    skipped = 0
    t_start = time.time()

    for s in range(args.start_seed, args.end_seed + 1):
        t0 = time.time()
        result = run_one(s, track_c)
        elapsed = time.time() - t0
        if result is None or result.get("winner") == "error":
            skipped += 1
            err = result.get("error", "none") if result else "none"
            print(f"  seed={s:>3} SKIP: {err[:80]}")
            continue
        n_players = len(result["players"])
        records += n_players
        wins = sum(1 for p in result["players"] if p["won"])
        print(f"  seed={s:>3} {result['winner']:<8} d={result['day']} w={wins}/{n_players} {elapsed:.0f}s")

        # Write immediately
        with open(args.output, "a") as f:
            for p in result["players"]:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    total_t = time.time() - t_start
    n_games = args.end_seed - args.start_seed + 1
    ok_games = n_games - skipped
    print(f"\nBATCH DONE: {ok_games}/{n_games} games ({skipped} skipped), {records} records, {total_t / 60:.1f}min")


if __name__ == "__main__":
    main()
