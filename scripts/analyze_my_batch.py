"""Analyze MY LLM batch games to quantify Track B scoring quality.

Usage:
    python scripts/analyze_my_batch.py [--label mine_20260525...]

What it produces:
1. Sample size per role × outcome (e.g. "Werewolf in wolf-winning games")
2. Process_score distribution per role × outcome — to detect outcome bias
3. Adjusted_final_score vs process_score per player — comparison
4. Win-rate per role (matches data discussed for the leaderboard)
5. Strategy retrieval coverage on the same set of games
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from backend.db.database import SessionLocal


def load_my_game_ids(label: str | None) -> list[str]:
    """Return all my LLM game_ids. If label given, load from the batch jsonl;
    else discover by querying all all-LLM games created since this session."""
    if label:
        path = ROOT / "data" / "health" / f"llm_batch_{label}.jsonl"
        if not path.exists():
            print(f"WARN: batch log {path} missing, falling back to DB query")
        else:
            ids: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if "game_id" in record:
                        ids.append(record["game_id"])
                except json.JSONDecodeError:
                    continue
            print(f"Loaded {len(ids)} game_ids from {path.name}")
            return ids

    # Fallback: query all-LLM games from today.
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
            SELECT g.id
            FROM games g
            WHERE g.status = 'finished'
              AND g.created_at >= '2026-05-25 12:00:00'
              AND EXISTS (SELECT 1 FROM players p WHERE p.game_id=g.id AND p.agent_type='llm')
              AND NOT EXISTS (SELECT 1 FROM players p WHERE p.game_id=g.id AND p.agent_type!='llm')
            ORDER BY g.created_at
        """)
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()


def collect_player_reviews(game_ids: list[str]) -> list[dict[str, Any]]:
    """Pull each game's published_review.report_json.player_reviews."""
    if not game_ids:
        return []
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
            SELECT pr.game_id, g.winner, pr.report_json, pr.score, pr.grade, pr.status
            FROM published_reviews pr
            JOIN games g ON g.id = pr.game_id
            WHERE pr.game_id IN :gids
        """),
            {"gids": tuple(game_ids)},
        ).fetchall()

        all_reviews: list[dict[str, Any]] = []
        for game_id, winner, report_json, validation_score, grade, status in rows:
            if not report_json:
                continue
            player_reviews = report_json.get("player_reviews", [])
            for pr in player_reviews:
                pr["_game_id"] = game_id
                pr["_winner"] = winner
                pr["_won"] = (winner == "wolf" and pr.get("alignment") == "wolf") or (
                    winner == "village" and pr.get("alignment") == "village"
                )
                pr["_validation_score"] = float(validation_score or 0)
                pr["_validation_grade"] = grade
                pr["_validation_status"] = status
                all_reviews.append(pr)
        return all_reviews
    finally:
        db.close()


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": 0.0, "median": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0}
    n = len(values)
    return {
        "n": n,
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "stdev": round(statistics.stdev(values), 2) if n > 1 else 0.0,
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def quantify_outcome_bias(player_reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """For each role, compare:
       - process_score distribution between wins vs losses
       - adjusted_final_score distribution between wins vs losses
    The gap between (a) and (b) is the outcome bias the process_score split
    is supposed to remove. We want process gap ≈ 0, adjusted gap can be > 0.
    """
    by_role: dict[str, dict[str, list[float]]] = {}
    for pr in player_reviews:
        role = pr.get("role") or "Unknown"
        won = pr.get("_won")
        bucket = by_role.setdefault(
            role, {"win_process": [], "lose_process": [], "win_adjusted": [], "lose_adjusted": []}
        )
        bucket["win_process" if won else "lose_process"].append(float(pr.get("process_score") or 0))
        bucket["win_adjusted" if won else "lose_adjusted"].append(
            float(pr.get("adjusted_final_score") or pr.get("rule_score") or 0)
        )

    result: dict[str, Any] = {}
    for role, b in by_role.items():
        win_p = summarize(b["win_process"])
        lose_p = summarize(b["lose_process"])
        win_a = summarize(b["win_adjusted"])
        lose_a = summarize(b["lose_adjusted"])
        result[role] = {
            "n_win": win_p["n"],
            "n_lose": lose_p["n"],
            "process_score": {"win": win_p, "lose": lose_p, "gap_mean": round(win_p["mean"] - lose_p["mean"], 2)},
            "adjusted_final_score": {
                "win": win_a,
                "lose": lose_a,
                "gap_mean": round(win_a["mean"] - lose_a["mean"], 2),
            },
            "bias_removed_pct": (
                round(
                    100 * (1 - abs(win_p["mean"] - lose_p["mean"]) / max(abs(win_a["mean"] - lose_a["mean"]), 0.01)),
                    1,
                )
                if (win_p["n"] and lose_p["n"])
                else None
            ),
        }
    return result


def role_win_rate(player_reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for pr in player_reviews:
        role = pr.get("role") or "Unknown"
        b = out.setdefault(role, {"games": 0, "wins": 0})
        b["games"] += 1
        if pr.get("_won"):
            b["wins"] += 1
    for role, b in out.items():
        b["win_rate"] = round(b["wins"] / b["games"], 4) if b["games"] else 0.0
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=None)
    ap.add_argument("--max-games", type=int, default=500)
    args = ap.parse_args()

    game_ids = load_my_game_ids(args.label)[: args.max_games]
    print(f"\n=== My batch — {len(game_ids)} games ===")

    if not game_ids:
        print("No games found. Did the batch run?")
        return 1

    reviews = collect_player_reviews(game_ids)
    print(f"  player-reviews loaded: {len(reviews)}")

    # 1. Win rate by role
    win_rate = role_win_rate(reviews)
    print("\n=== Win rate per role ===")
    print(f"{'role':<12s} {'games':>6s} {'wins':>6s} {'win_rate':>10s}")
    for role in sorted(win_rate):
        b = win_rate[role]
        print(f"{role:<12s} {b['games']:>6d} {b['wins']:>6d} {b['win_rate']:>10.4f}")

    # 2. Outcome bias quantification
    bias = quantify_outcome_bias(reviews)
    print("\n=== Outcome bias per role (win vs lose distributions) ===")
    print("  process_score gap should drop toward 0 if the split worked,")
    print("  adjusted_final_score gap may still be large (camp_result is in there).\n")
    print(
        f"{'role':<12s} {'n_w':>4s} {'n_l':>4s} | "
        f"{'proc_w':>7s} {'proc_l':>7s} {'gap':>6s} | "
        f"{'adj_w':>7s} {'adj_l':>7s} {'gap':>6s} | bias_removed_%"
    )
    for role in sorted(bias):
        b = bias[role]
        pw = b["process_score"]["win"]["mean"]
        pl = b["process_score"]["lose"]["mean"]
        pg = b["process_score"]["gap_mean"]
        aw = b["adjusted_final_score"]["win"]["mean"]
        al_ = b["adjusted_final_score"]["lose"]["mean"]
        ag = b["adjusted_final_score"]["gap_mean"]
        rem = b.get("bias_removed_pct")
        rem_s = f"{rem}%" if rem is not None else "n/a"
        print(
            f"{role:<12s} {b['n_win']:>4d} {b['n_lose']:>4d} | "
            f"{pw:>7.2f} {pl:>7.2f} {pg:>+6.2f} | "
            f"{aw:>7.2f} {al_:>7.2f} {ag:>+6.2f} | {rem_s}"
        )

    # 3. Validation result distribution
    grades: dict[str, int] = {}
    statuses: dict[str, int] = {}
    val_scores: list[float] = []
    for pr in reviews:
        grades[pr["_validation_grade"]] = grades.get(pr["_validation_grade"], 0) + 1
        statuses[pr["_validation_status"]] = statuses.get(pr["_validation_status"], 0) + 1
        val_scores.append(pr["_validation_score"])
    print("\n=== Track B validation roll-up (per-player rows) ===")
    print(f"  grades: {grades}")
    print(f"  statuses: {statuses}")
    if val_scores:
        print(f"  validation_score: {summarize(val_scores)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
