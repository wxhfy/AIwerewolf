"""Analyze MBTI-specific win rates from batch experiment results.

Reconstructs MBTI assignments per game using the same seed-based
character roster logic, then computes win rates by:
  1. MBTI type alone
  2. Role alone
  3. MBTI + Role combination

Usage:
  python scripts/analyze_mbti.py [--jsonl data/experiment/batch_results.jsonl]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def reconstruct_mbti(seed: int, player_names: list[str], player_roles: list[str]) -> dict[str, str]:
    """Reconstruct {player_name: mbti} using the same character roster logic."""
    from backend.agents.characters import build_character_roster

    # Build synthetic Player-like objects
    class FakePlayer:
        def __init__(self, name, role, idx):
            self.id = f"P{idx}"
            self.name = name
            self.role = FakeRole(role)
            self.seat = idx + 1
            self.alive = True
            self.is_ai = True

    class FakeRole:
        def __init__(self, value):
            self.value = value

    players = [FakePlayer(name, role, i) for i, (name, role) in enumerate(zip(player_names, player_roles))]
    roster = build_character_roster(players, seed=seed)

    mbti_map = {}
    for pid, char in roster.items():
        # Find player name from id
        for p in players:
            if p.id == pid:
                mbti_map[p.name] = char.persona.mbti
                break
    return mbti_map


def analyze(jsonl_path: str) -> dict:
    """Full MBTI + Role win-rate analysis."""
    results = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if "error" not in r:
                    results.append(r)
            except json.JSONDecodeError:
                pass

    print(f"Loaded {len(results)} completed games")

    # Stats containers
    role_stats = defaultdict(lambda: {"wins": 0, "games": 0})  # role
    mbti_stats = defaultdict(lambda: {"wins": 0, "games": 0})  # mbti
    combo_stats = defaultdict(lambda: {"wins": 0, "games": 0})  # mbti+role

    # Process each game
    with_mbti = 0
    without_mbti = 0

    for r in results:
        seed = r.get("seed", 0)
        players = r.get("players", [])
        if not players:
            continue

        # Check if MBTI is already in the data
        has_mbti = any("mbti" in p for p in players)

        if has_mbti:
            with_mbti += 1
            for p in players:
                mbti = p.get("mbti", "UNKNOWN")
                role = p["role"]
                won = p.get("won", False)
                role_stats[role]["games"] += 1
                if won:
                    role_stats[role]["wins"] += 1
                mbti_stats[mbti]["games"] += 1
                if won:
                    mbti_stats[mbti]["wins"] += 1
                key = f"{mbti}+{role}"
                combo_stats[key]["games"] += 1
                if won:
                    combo_stats[key]["wins"] += 1
        else:
            without_mbti += 1
            # Reconstruct MBTI from seed
            names = [p["name"] for p in players]
            roles = [p["role"] for p in players]
            try:
                mbti_map = reconstruct_mbti(seed, names, roles)
                for p in players:
                    mbti = mbti_map.get(p["name"], "UNKNOWN")
                    role = p["role"]
                    won = p.get("won", False)
                    role_stats[role]["games"] += 1
                    if won:
                        role_stats[role]["wins"] += 1
                    mbti_stats[mbti]["games"] += 1
                    if won:
                        mbti_stats[mbti]["wins"] += 1
                    key = f"{mbti}+{role}"
                    combo_stats[key]["games"] += 1
                    if won:
                        combo_stats[key]["wins"] += 1
            except Exception as e:
                print(f"  WARNING: failed to reconstruct MBTI for seed={seed}: {e}")

    print(f"Games with MBTI in data: {with_mbti}, reconstructed: {without_mbti}")

    # Format stats
    def fmt_stats(stats: dict, min_games: int = 1) -> list[dict]:
        out = []
        for key, s in sorted(stats.items()):
            n = s["games"]
            if n < min_games:
                continue
            out.append(
                {
                    "key": key,
                    "games": n,
                    "wins": s["wins"],
                    "win_rate": round(s["wins"] / n, 4),
                }
            )
        out.sort(key=lambda x: -x["win_rate"])
        return out

    return {
        "total_games": len(results),
        "by_role": fmt_stats(role_stats),
        "by_mbti": fmt_stats(mbti_stats),
        "by_mbti_role": fmt_stats(combo_stats, min_games=2),
    }


def print_report(analysis: dict) -> None:
    """Pretty-print the MBTI analysis."""
    print(f"\n{'=' * 60}")
    print(f"Total games analyzed: {analysis['total_games']}")
    print(f"{'=' * 60}")

    # By Role
    print("\n--- Win Rate by Role ---")
    print(f"{'Role':<14s} {'Win Rate':>9s} {'Wins':>6s} {'Games':>6s}")
    print(f"{'-' * 40}")
    for item in analysis["by_role"]:
        print(f"{item['key']:<14s} {item['win_rate']:>8.1%} {item['wins']:>5d} {item['games']:>5d}")

    # By MBTI
    print("\n--- Win Rate by MBTI ---")
    print(f"{'MBTI':<8s} {'Win Rate':>9s} {'Wins':>6s} {'Games':>6s}")
    print(f"{'-' * 35}")
    for item in analysis["by_mbti"]:
        print(f"{item['key']:<8s} {item['win_rate']:>8.1%} {item['wins']:>5d} {item['games']:>5d}")

    # By MBTI+Role (top 20)
    print("\n--- Win Rate by MBTI + Role (top 20, min 2 games) ---")
    print(f"{'MBTI+Role':<22s} {'Win Rate':>9s} {'Wins':>6s} {'Games':>6s}")
    print(f"{'-' * 50}")
    for item in analysis["by_mbti_role"][:20]:
        print(f"{item['key']:<22s} {item['win_rate']:>8.1%} {item['wins']:>5d} {item['games']:>5d}")

    # Best MBTI per role
    print("\n--- Best MBTI per Role ---")
    best_per_role = {}
    for item in analysis["by_mbti_role"]:
        mbti_role = item["key"]
        if "+" not in mbti_role:
            continue
        mbti, role = mbti_role.rsplit("+", 1)
        if role not in best_per_role or item["win_rate"] > best_per_role[role]["win_rate"]:
            best_per_role[role] = {"mbti": mbti, **item}
    for role in sorted(best_per_role):
        b = best_per_role[role]
        print(f"  {role:<12s}: {b['mbti']:<6s} ({b['win_rate']:.1%}, {b['games']} games)")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--jsonl", default="data/experiment/batch_results.jsonl")
    p.add_argument("--output", default="")
    args = p.parse_args()

    analysis = analyze(args.jsonl)
    print_report(analysis)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        print(f"\nSaved to {args.output}")
