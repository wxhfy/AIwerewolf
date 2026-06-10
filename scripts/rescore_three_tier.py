#!/usr/bin/env python3
"""Three-Tier LLM Judge Scoring Script.

Re-scores all completed games using the full three-tier cascade:
  Tier 1: Deterministic rule scoring (free, instant)
  Tier 2: Light LLM judge for ambiguous decisions
  Tier 3: Heavy LLM 3-judge panel for high-impact decisions

Usage:
    LLM_PROVIDER=anthropic python3 scripts/rescore_three_tier.py \
        --input outputs/exp_10model_leaderboard/game_runs.jsonl \
        --output outputs/leaderboard/three_tier_scores.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AIWEREWOLF_SKIP_DOTENV", "1")


def load_game_ids(game_runs_file: str) -> list[dict]:
    """Load game metadata from game_runs.jsonl."""
    games = []
    with open(game_runs_file) as f:
        for line in f:
            games.append(json.loads(line.strip()))
    return games


def load_game_from_db(game_id: str) -> dict | None:
    """Load full game state and decisions from the database."""
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("DATABASE_URL", "sqlite:///data/werewolf.db")
    engine = create_engine(db_url)

    with engine.connect() as conn:
        # Load game
        r = conn.execute(text("SELECT * FROM games WHERE id = :gid"), {"gid": game_id})
        game_row = r.fetchone()
        if not game_row:
            return None

        # Load players
        r = conn.execute(
            text("SELECT * FROM players WHERE game_id = :gid"),
            {"gid": game_id},
        )
        players = []
        for row in r.fetchall():
            players.append({
                "id": row[0],
                "game_id": row[1],
                "seat_no": row[2],
                "name": row[3],
                "role": row[4],
                "is_ai": row[5],
                "agent_type": row[6],
                "model_name": row[7],
            })

        # Load agent decisions
        r = conn.execute(
            text("SELECT * FROM agent_decisions WHERE game_id = :gid ORDER BY id"),
            {"gid": game_id},
        )
        decisions = []
        for row in r.fetchall():
            decisions.append({
                "id": row[0],
                "game_id": row[1],
                "player_id": row[2],
                "day": row[3],
                "phase": row[4],
                "observation": row[5],
                "legal_actions": row[6],
                "prompt_version": row[7],
                "raw_output": row[8],
                "parsed_action": row[9],
            })

        # Load game events
        r = conn.execute(
            text("SELECT * FROM game_events WHERE game_id = :gid ORDER BY seq"),
            {"gid": game_id},
        )
        events = []
        for row in r.fetchall():
            events.append({
                "id": row[0],
                "game_id": row[1],
                "seq": row[2],
                "ts": row[3],
                "day": row[4],
                "phase": row[5],
                "event_type": row[6],
                "actor_id": row[7],
                "target_id": row[8],
                "visibility": row[9],
            })

    return {
        "game_id": game_id,
        "players": players,
        "decisions": decisions,
        "events": events,
    }


def build_state_dict(game_data: dict, game_meta: dict) -> dict:
    """Build state dict compatible with PerStepScorer."""
    players = []
    for p in game_data["players"]:
        players.append({
            "id": p["id"],
            "name": p["name"],
            "role": p["role"],
            "alignment": "wolf" if p["role"] in ("Werewolf", "WhiteWolfKing") else "village",
            "alive": True,  # Will be updated from events
        })

    # Build events list
    events = []
    for e in game_data["events"]:
        events.append({
            "id": e["id"],
            "type": e["event_type"],
            "day": e["day"],
            "phase": e["phase"],
            "actor_id": e["actor_id"],
            "target_id": e["target_id"],
            "payload": {},
        })

    return {
        "game_id": game_data["game_id"],
        "players": players,
        "events": events,
        "day": game_meta.get("days", 3),
        "winner": game_meta.get("winner", ""),
    }


def build_decisions_list(game_data: dict) -> list[dict]:
    """Build decisions list compatible with PerStepScorer."""
    decisions = []
    for d in game_data["decisions"]:
        parsed = {}
        if d.get("parsed_action"):
            try:
                parsed = json.loads(d["parsed_action"])
            except (json.JSONDecodeError, TypeError):
                pass

        decisions.append({
            "id": str(d["id"]),
            "player_id": d["player_id"],
            "player_name": next(
                (p["name"] for p in game_data["players"] if p["id"] == d["player_id"]),
                "",
            ),
            "player_role": next(
                (p["role"] for p in game_data["players"] if p["id"] == d["player_id"]),
                "",
            ),
            "day": d.get("day", 0),
            "phase": d.get("phase", ""),
            "action_type": parsed.get("action_type", ""),
            "target_id": parsed.get("target_id", ""),
            "speech": parsed.get("speech", ""),
            "reasoning": parsed.get("reasoning", ""),
            "raw_text": parsed.get("reasoning", "") or parsed.get("speech", ""),
            "observation": d.get("observation", ""),
        })
    return decisions


def build_speech_acts(game_data: dict) -> list[dict]:
    """Extract speech acts from decisions for speech scoring."""
    speech_acts = []
    for d in game_data["decisions"]:
        parsed = {}
        if d.get("parsed_action"):
            try:
                parsed = json.loads(d["parsed_action"])
            except (json.JSONDecodeError, TypeError):
                pass

        if parsed.get("action_type") == "talk":
            speech_acts.append({
                "player_id": d["player_id"],
                "day": d.get("day", 0),
                "phase": d.get("phase", ""),
                "speech": parsed.get("speech", ""),
            })
    return speech_acts


def rescore_game(game_meta: dict, scorer) -> dict | None:
    """Re-score a single game with three-tier scoring."""
    game_id = game_meta["game_id"]

    # Load from DB
    game_data = load_game_from_db(game_id)
    if not game_data:
        print(f"  Game {game_id[:8]} not found in DB, skipping")
        return None

    if not game_data["decisions"]:
        print(f"  Game {game_id[:8]} has no decisions in DB, skipping")
        return None

    # Build inputs for PerStepScorer
    state = build_state_dict(game_data, game_meta)
    decisions = build_decisions_list(game_data)
    speech_acts = build_speech_acts(game_data)

    # Score with three tiers
    t0 = time.perf_counter()
    scores = scorer.score_all(
        decisions,
        state,
        speech_acts,
        light_llm=True,
        heavy_llm=True,
    )
    elapsed = time.perf_counter() - t0

    # Aggregate results
    tier_counts = scorer.tally_tiers(scores)

    # Per-player aggregation
    player_scores = defaultdict(lambda: {
        "scores": [],
        "tiers": defaultdict(int),
        "role": "",
        "model": "",
        "alignment": "",
    })

    for s in scores:
        ps = player_scores[s.player_name]
        ps["scores"].append(s.overall_score)
        ps["tiers"][s.scoring_tier] += 1
        ps["role"] = s.role

    # Map player names to models from seat_assignments
    seat_map = {}
    for seat in game_meta.get("seat_assignments", []):
        seat_map[seat["name"]] = {
            "model": seat.get("model", ""),
            "role": seat.get("role", ""),
            "alignment": seat.get("alignment", ""),
        }

    # Build per-player results
    player_results = []
    for name, ps in player_scores.items():
        avg_score = sum(ps["scores"]) / len(ps["scores"]) if ps["scores"] else 0
        seat_info = seat_map.get(name, {})
        player_results.append({
            "name": name,
            "role": seat_info.get("role", ps["role"]),
            "alignment": seat_info.get("alignment", ""),
            "model": seat_info.get("model", ""),
            "avg_score": round(avg_score, 4),
            "decision_count": len(ps["scores"]),
            "tier_counts": dict(ps["tiers"]),
        })

    return {
        "game_id": game_id,
        "seed": game_meta.get("seed"),
        "winner": game_meta.get("winner"),
        "days": game_meta.get("days"),
        "elapsed_s": round(elapsed, 1),
        "total_decisions": len(scores),
        "tier_counts": tier_counts,
        "player_results": player_results,
    }


def aggregate_by_model(results: list[dict]) -> list[dict]:
    """Aggregate three-tier scores by model."""
    model_stats = defaultdict(lambda: {
        "games": 0,
        "total_decisions": 0,
        "tier_counts": defaultdict(int),
        "player_scores": [],
        "player_win_scores": [],
    })

    for r in results:
        for p in r.get("player_results", []):
            model = p.get("model", "unknown")
            ms = model_stats[model]
            ms["games"] += 1
            ms["total_decisions"] += p.get("decision_count", 0)
            for tier, count in p.get("tier_counts", {}).items():
                ms["tier_counts"][tier] += count
            ms["player_scores"].append(p["avg_score"])

    # Build leaderboard
    leaderboard = []
    for model, ms in model_stats.items():
        scores = ms["player_scores"]
        avg_score = sum(scores) / len(scores) if scores else 0
        leaderboard.append({
            "model": model,
            "games": ms["games"],
            "avg_three_tier_score": round(avg_score, 4),
            "total_decisions": ms["total_decisions"],
            "tier_distribution": dict(ms["tier_counts"]),
        })

    leaderboard.sort(key=lambda x: x["avg_three_tier_score"], reverse=True)
    return leaderboard


def main():
    parser = argparse.ArgumentParser(description="Three-tier LLM judge rescoring")
    parser.add_argument(
        "--input",
        default="outputs/exp_10model_leaderboard/game_runs.jsonl",
        help="Input game_runs.jsonl",
    )
    parser.add_argument(
        "--output",
        default="outputs/leaderboard/three_tier_scores.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=0,
        help="Max games to rescore (0 = all)",
    )
    args = parser.parse_args()

    # Load game list
    games = load_game_ids(args.input)
    if args.max_games > 0:
        games = games[: args.max_games]
    print(f"Loaded {len(games)} games from {args.input}")

    # Create LLM client for Tier 2/3
    from backend.llm import create_client

    llm_client = create_client(provider="anthropic")
    print(f"LLM client created: {type(llm_client).__name__}")

    # Create PerStepScorer
    from backend.eval.per_step_scorer import PerStepScorer

    scorer = PerStepScorer(llm_client=llm_client)
    print("PerStepScorer initialized with three-tier cascade")

    # Re-score each game
    results = []
    for i, game in enumerate(games):
        game_id = game["game_id"][:8]
        print(f"\n[{i+1}/{len(games)}] Rescoring game {game_id} (seed={game.get('seed')})...")
        result = rescore_game(game, scorer)
        if result:
            results.append(result)
            tiers = result["tier_counts"]
            print(f"  ✓ {result['total_decisions']} decisions scored in {result['elapsed_s']}s")
            print(f"    Tiers: {tiers}")

    # Aggregate by model
    model_leaderboard = aggregate_by_model(results)

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scoring_method": "three_tier_cascade",
        "tier_1": "Deterministic rule scoring (vote/speech/skill/survival)",
        "tier_2": "Light LLM judge for ambiguous decisions (single judge)",
        "tier_3": "Heavy LLM 3-judge panel (Strategist + Logician + Psychologist + Critic)",
        "games_scored": len(results),
        "model_leaderboard": model_leaderboard,
        "game_results": results,
    }

    # Save
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Saved to {out_path}")

    # Print summary
    print(f"\n{'='*70}")
    print("Three-Tier Leaderboard")
    print(f"{'='*70}")
    print(f"{'Model':45s} {'Games':>5s} {'AvgScore':>10s} {'T1':>5s} {'T2':>5s} {'T3':>5s}")
    print("-" * 75)
    for m in model_leaderboard:
        tiers = m.get("tier_distribution", {})
        print(
            f"{m['model'][:44]:45s} "
            f"{m['games']:>5d} "
            f"{m['avg_three_tier_score']:>10.4f} "
            f"{tiers.get('deterministic', 0):>5d} "
            f"{tiers.get('light_llm', 0):>5d} "
            f"{tiers.get('heavy_llm', 0):>5d}"
        )


if __name__ == "__main__":
    main()
