"""Build per-game report data JSON for V3 HTML single-game replay.

Loads replay_bundle from DB, cross-references with review_v2 scores,
speech scores, counterfactual impacts, and computes derived metrics:
suspicion matrix, camp advantage curve, drama score, pivot votes, player cards.

Usage:
  python scripts/build_single_game_report_data.py --game-id <id>     # single game
  python scripts/build_single_game_report_data.py --all              # all 56 clean games
  python scripts/build_single_game_report_data.py --sample 3         # first N games
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.v3_report import analyze_speech_acts_from_dict
from backend.eval.v3_report import build_player_radar
from backend.eval.v3_report import build_suspicion_matrix_from_dict
from backend.eval.v3_report import compute_camp_advantage_curve
from backend.eval.v3_report import compute_drama_score
from backend.eval.v3_report import compute_pivot_votes


def load_json(path: str) -> Any:
    with open(ROOT / path, encoding="utf-8") as f:
        return json.load(f)


def build_game_data(game_id: str, data_sources: dict) -> dict | None:
    """Assemble all data for one game into a PerGameReportData-compatible dict.

    Returns None if replay_bundle is missing for this game.
    """
    (
        replay_map,
        review_by_game,
        speech_by_game,
        cf_by_game,
        opps_by_game,
        winner_map,
    ) = data_sources["lookups"]

    bundle = replay_map.get(game_id)
    if bundle is None:
        print(f"  SKIP {game_id}: no replay_bundle")
        return None

    players = bundle.get("players", [])
    events = bundle.get("events", [])
    votes_raw = bundle.get("votes", [])
    decisions = bundle.get("decisions", [])
    winner = bundle.get("winner", "unknown")
    rule_pack = bundle.get("rule_pack", "")
    finished_at = bundle.get("finished_at", "")

    # Compute derived data
    speech_acts = analyze_speech_acts_from_dict(events, players)
    suspicion_snapshots = build_suspicion_matrix_from_dict(events, speech_acts, players)
    # Fill game_id into suspicion snapshots
    for s in suspicion_snapshots:
        s["game_id"] = game_id

    camp_advantage = compute_camp_advantage_curve(events, players)

    # Filter to this game
    game_reviews = review_by_game.get(game_id, [])
    game_cfs = cf_by_game.get(game_id, [])
    game_opps = opps_by_game.get(game_id, [])

    # Drama score
    drama = compute_drama_score(camp_advantage, suspicion_snapshots, votes_raw, game_cfs, events)

    # Pivot votes
    pivot_votes = compute_pivot_votes(votes_raw, players)

    # Organize votes by day for HTML rendering
    vote_flows: dict[int, list[dict]] = defaultdict(list)
    for v in votes_raw:
        day = v.get("day", 0)
        vote_flows[day].append(
            {
                "voter_id": v.get("voter_id", ""),
                "voter_name": v.get("voter_name", ""),
                "target_id": v.get("target_id", ""),
                "target_name": v.get("target_name", ""),
                "reasoning": v.get("reasoning", "")[:200],
            }
        )

    # Add pivot info to vote flows
    for day, pivots in pivot_votes.items():
        pv_map = {p["voter_id"]: p for p in pivots}
        for vf in vote_flows.get(day, []):
            pv = pv_map.get(vf["voter_id"])
            if pv:
                vf["is_pivot"] = pv["is_pivot"]
                vf["alternative_target"] = pv["alternative_target"]
                vf["impact"] = pv["impact"]

    # Scoreboard from review_v2
    scoreboard = []
    for r in game_reviews:
        # Merge speech detail
        speech_data = speech_by_game.get(r["player_id"], {})  # player_id is "P1-xxxxx" format
        # speech_by_game is keyed by player_id from speech_scores.json which uses
        # "P1-xxxxx" format. review_v2 uses "P1-xxxxx" format too.
        speech_detail = {
            "n_speeches": speech_data.get("n_speeches", 0),
            "groundedness": speech_data.get("avg_groundedness", 0),
            "stance_clarity": speech_data.get("avg_stance_clarity", 0),
            "consistency": speech_data.get("avg_consistency", 0),
            "strategic_value": speech_data.get("avg_strategic_value", 0),
            "information_safety": speech_data.get("avg_information_safety", 0),
        }
        radar = build_player_radar(r, speech_data)

        scoreboard.append(
            {
                "player_id": r["player_id"],
                "role": r["role"],
                "won": r["won"],
                "final_score": r["final_score"],
                "process_score": r["process_score"],
                "role_process_score": r["role_process_score"],
                "speech_score": r["speech_score"],
                "counterfactual_impact": r["counterfactual_impact"],
                "mistake_penalty": r["mistake_penalty"],
                "model_confidence": r["model_confidence"],
                "n_opportunities": r["n_opportunities"],
                "top3_good": r["top3_good"],
                "top3_bad": r["top3_bad"],
                "advice": r["advice"],
                "speech_detail": speech_detail,
                "radar": radar,
            }
        )

    # Sort scoreboard by final_score desc
    scoreboard.sort(key=lambda x: -x["final_score"])

    # MVP = top player by final_score
    mvp = scoreboard[0] if scoreboard else None

    # Total days
    total_days = max(
        (e.get("day", 0) for e in events if e.get("visibility") == "public"),
        default=0,
    )

    # Top 5 good/bad opportunities across all players in this game
    all_good = []
    all_bad = []
    for r in game_reviews:
        pid = r["player_id"]
        role = r["role"]
        for g in r.get("top3_good", []):
            all_good.append(
                {
                    "player_id": pid,
                    "role": role,
                    "type": g["type"],
                    "day": g["day"],
                    "score": g["score"],
                }
            )
        for b in r.get("top3_bad", []):
            all_bad.append(
                {
                    "player_id": pid,
                    "role": role,
                    "type": b["type"],
                    "day": b["day"],
                    "score": b["score"],
                }
            )
    all_good.sort(key=lambda x: -x["score"])
    all_bad.sort(key=lambda x: x["score"])

    # Player cards
    player_cards = []
    for p in players:
        pid = p["id"]
        # Find matching review
        rev = next((r for r in game_reviews if r["player_id"] == pid), None)

        # Player's speech data
        sp_data = speech_by_game.get(pid, {})

        # Player's opportunities (by scanning opps for matching player)
        player_opps = [o for o in game_opps if _opp_player_id(o, pid)]

        player_cards.append(
            {
                "player_id": pid,
                "name": p.get("name", pid),
                "role": p.get("role", "Villager"),
                "alignment": p.get("alignment", "village"),
                "alive": p.get("alive", True),
                "death_day": p.get("death_day"),
                "death_reason": p.get("death_reason"),
                "persona": p.get("persona", {}),
                "agent_type": p.get("agent_type", ""),
                "model_name": p.get("model_name", ""),
                "final_score": rev["final_score"] if rev else 0,
                "process_score": rev["process_score"] if rev else 0,
                "speech_score": rev["speech_score"] if rev else 0,
                "counterfactual_impact": rev["counterfactual_impact"] if rev else 0,
                "model_confidence": rev["model_confidence"] if rev else 0.5,
                "top3_good": rev["top3_good"] if rev else [],
                "top3_bad": rev["top3_bad"] if rev else [],
                "advice": rev["advice"] if rev else [],
                "radar": build_player_radar(rev or {}, sp_data),
                "n_opportunities": len(player_opps),
                "speech_detail": {
                    "n_speeches": sp_data.get("n_speeches", 0),
                    "avg_speech_quality": sp_data.get("avg_speech_quality", 50),
                    "groundedness": sp_data.get("avg_groundedness", 0),
                    "stance_clarity": sp_data.get("avg_stance_clarity", 0),
                    "consistency": sp_data.get("avg_consistency", 0),
                    "strategic_value": sp_data.get("avg_strategic_value", 0),
                    "information_safety": sp_data.get("avg_information_safety", 0),
                },
            }
        )

    # Evidence map: event_id -> full event for drawer
    evidence_map = {}
    for e in events:
        eid = e.get("id", "")
        if eid:
            evidence_map[eid] = {
                "seq": e.get("seq", 0),
                "event_type": e.get("event_type", ""),
                "day": e.get("day", 0),
                "phase": str(e.get("phase", "")),
                "visibility": e.get("visibility", "public"),
                "payload": e.get("payload", {}),
            }

    # Validation: generate per-game validation (simplified from v2 global)
    hunter_players = [s for s in scoreboard if s["role"] == "Hunter"]
    guard_players = [s for s in scoreboard if s["role"] == "Guard"]
    issues = []
    for hp in hunter_players:
        if hp["model_confidence"] <= 0.5:
            issues.append(
                {
                    "type": "hunter_low_confidence",
                    "player_id": hp["player_id"],
                    "detail": "Hunter confidence LOW (shots < 30 total)",
                }
            )
    for gp in guard_players:
        if gp["model_confidence"] <= 0.65:
            issues.append(
                {
                    "type": "guard_medium_confidence",
                    "player_id": gp["player_id"],
                    "detail": "Guard v2 scoring moderate confidence",
                }
            )

    per_game_validation = {
        "passed": len(issues) == 0 or all(i["type"] == "hunter_low_confidence" for i in issues),
        "grade": "A" if len(issues) <= 1 else "B",
        "issues": issues,
        "publish_allowed": True,
    }

    return {
        "game_id": game_id,
        "winner": winner,
        "rule_pack": rule_pack,
        "finished_at": finished_at,
        "mvp": mvp,
        "total_days": total_days,
        "valid_grade": per_game_validation["grade"],
        "players": players,
        "events": events,
        "decisions": decisions,
        "scoreboard": scoreboard,
        "camp_advantage": [
            {
                "seq": p.seq,
                "event_id": p.event_id,
                "day": p.day,
                "phase": p.phase,
                "event_type": p.event_type,
                "label": p.label,
                "advantage": p.advantage,
                "delta": p.delta,
            }
            for p in camp_advantage
        ],
        "suspicion_snapshots": suspicion_snapshots,
        "vote_flows": {str(k): v for k, v in vote_flows.items()},
        "pivot_votes": {str(k): v for k, v in pivot_votes.items()},
        "top_good_opportunities": all_good[:5],
        "top_bad_opportunities": all_bad[:5],
        "counterfactuals": game_cfs,
        "player_cards": player_cards,
        "validation": per_game_validation,
        "speech_acts": speech_acts,
        "evidence_map": evidence_map,
        "drama_score": {
            "score": drama.score,
            "camp_advantage_swing": drama.camp_advantage_swing,
            "suspicion_swing": drama.suspicion_swing,
            "pivot_vote_count": drama.pivot_vote_count,
            "counterfactual_impact_sum": drama.counterfactual_impact_sum,
            "role_skill_impact": drama.role_skill_impact,
            "comeback_score": drama.comeback_score,
            "top_moments": drama.top_moments,
        },
    }


def _opp_player_id(opp: dict, player_id: str) -> bool:
    """Check if an opportunity belongs to a specific player."""
    # opportunity_id format: opp-<game_id>-<player_id>-<day>-<type>
    oid = opp.get("opportunity_id", "")
    parts = oid.split("-")
    if len(parts) >= 3:
        return parts[2] == player_id
    return False


def _build_lookups() -> dict:
    """Load all data sources and build lookup tables."""
    print("Loading data sources...")

    # 1. replay_bundle from DB
    from sqlalchemy import text

    from backend.db.database import SessionLocal
    from backend.db.database import init_db

    init_db()
    db = SessionLocal()
    clean_ids = set(json.loads(Path("/tmp/clean_llm_game_ids.json").read_text()))
    rows = db.execute(
        text(
            "SELECT game_id, replay_bundle FROM published_reviews WHERE game_id IN :ids AND replay_bundle IS NOT NULL"
        ),
        {"ids": tuple(clean_ids)},
    ).fetchall()
    replay_map = {}
    for row in rows:
        bundle = row[1]
        if isinstance(bundle, str):
            bundle = json.loads(bundle)
        replay_map[row[0]] = bundle
    db.close()
    print(f"  replay_bundles: {len(replay_map)} games")

    # 2. review scores
    review_data = load_json("data/health/review_with_learned_scores_v2.json")
    review_by_game: dict[str, list[dict]] = defaultdict(list)
    review_by_player: dict[str, dict] = {}
    for r in review_data:
        review_by_game[r["game_id"]].append(r)
        review_by_player[r["player_id"]] = r
    print(f"  reviews: {len(review_data)} players across {len(review_by_game)} games")

    # 3. speech scores
    speech_data = load_json("data/health/speech_scores.json")
    speech_by_player: dict[str, dict] = {}
    for s in speech_data:
        speech_by_player[s["player_id"]] = s
    print(f"  speech scores: {len(speech_data)}")

    # 4. counterfactual impacts
    cf_data = load_json("data/health/counterfactual_impacts.json")
    cf_by_game: dict[str, list[dict]] = defaultdict(list)
    for cf in cf_data:
        cf_by_game[cf.get("game_id", "")].append(cf)
    print(f"  counterfactuals: {len(cf_data)}")

    # 5. opportunities
    opp_file = ROOT / "data/health/opportunities.jsonl"
    opps = []
    if opp_file.exists():
        with open(opp_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    opps.append(json.loads(line))
    opps_by_game: dict[str, list[dict]] = defaultdict(list)
    for o in opps:
        opps_by_game[o["game_id"]].append(o)
    print(f"  opportunities: {len(opps)}")

    # 6. winner map from games table
    db2 = SessionLocal()
    games = db2.execute(
        text("SELECT id, winner FROM games WHERE id IN :ids"),
        {"ids": tuple(clean_ids)},
    ).fetchall()
    winner_map = {g[0]: g[1] for g in games}
    db2.close()

    return {
        "lookups": (
            replay_map,
            review_by_game,
            speech_by_player,
            cf_by_game,
            opps_by_game,
            winner_map,
        ),
        "replay_map": replay_map,
        "review_by_game": review_by_game,
        "speech_by_player": speech_by_player,
        "cf_by_game": cf_by_game,
        "opps_by_game": opps_by_game,
        "winner_map": winner_map,
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", default=None, help="Single game ID")
    ap.add_argument("--all", action="store_true", help="All 56 clean games")
    ap.add_argument("--sample", type=int, default=None, help="First N clean games")
    ap.add_argument(
        "--output-dir",
        default="data/health/reports",
        help="Output directory for JSON files",
    )
    args = ap.parse_args()

    data = _build_lookups()
    replay_map = data["replay_map"]

    # Determine game IDs
    if args.game_id:
        game_ids = [args.game_id]
    else:
        game_ids = sorted(replay_map.keys())
        if args.sample:
            game_ids = game_ids[: args.sample]
        elif not args.all:
            game_ids = game_ids[:1]  # default: first game
            print("Default: single game. Use --all for all 56 games.")

    # Output directory
    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nBuilding report data for {len(game_ids)} game(s)...")

    for i, gid in enumerate(game_ids):
        print(f"  [{i + 1}/{len(game_ids)}] {gid[:16]}...", end=" ", flush=True)
        game_data = build_game_data(gid, data)
        if game_data is None:
            print("SKIP")
            continue

        out_path = out_dir / f"single_game_data_{gid}.json"
        out_path.write_text(
            json.dumps(game_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"OK (drama={game_data['drama_score']['score']}, days={game_data['total_days']})")

    print(f"\nDone! Output: {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
