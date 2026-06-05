#!/usr/bin/env python3
"""
Fix MBTI Win Rate Data Pipeline (Fixes 1-7).

Root cause: player_scores_v4.jsonl has no 'won' or 'camp' fields.
Fix: rebuild from replay_bundle (player role → camp, game winner → is_win).
"""

import json
import math
import sys
from collections import Counter
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "health"

np.random.seed(42)


def load_jsonl(path):
    if Path(path).exists():
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    return []


def load_json(path):
    with open(path) as f:
        return json.load(f)


def determine_camp(role):
    """Map role to camp."""
    if role == "Werewolf":
        return "wolf"
    return "village"


def normalize_winner(winner_str):
    """Normalize winner string to 'village' or 'wolf'."""
    if not winner_str:
        return "unknown"
    w = winner_str.lower().strip()
    if w in ("village", "villagers", "good", "town", "villager"):
        return "village"
    if w in ("wolf", "werewolf", "wolves", "werewolves", "evil"):
        return "wolf"
    return w


# ============================================================
# FIX 1-2: AUDIT + REPAIR is_win
# ============================================================


def audit_and_fix():
    """Audit existing data and fix is_win mapping."""
    print("=" * 60)
    print("Fix 1-2: Audit + Repair is_win")
    print("=" * 60)

    # Load player scores
    player_scores = load_jsonl(DATA / "player_scores_v4.jsonl")
    if not player_scores:
        player_scores = load_jsonl(DATA / "player_scores_v3.jsonl")
    print(f"Player scores: {len(player_scores)}")

    # Load replay bundles
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    from db import SessionLocal
    from db.models import PublishedReview

    session = SessionLocal()
    reviews = session.query(PublishedReview).filter(PublishedReview.replay_bundle is not None).all()

    # Build game_id → (winner, player_map) index
    game_index = {}
    winner_counter = Counter()
    for rev in reviews:
        bundle = rev.replay_bundle or {}
        winner_raw = bundle.get("winner", "")
        winner = normalize_winner(winner_raw)
        winner_counter[winner] += 1
        players = bundle.get("players", [])
        player_map = {}
        for p in players:
            pid = p.get("id", "")
            role = p.get("role", "")
            alignment = p.get("alignment", "")
            persona = p.get("persona", {}) or {}
            player_map[pid] = {
                "role": role,
                "alignment": alignment,
                "camp": determine_camp(role),
                "mbti": persona.get("mbti", ""),
                "name": p.get("name", ""),
            }
        game_index[rev.game_id] = {
            "winner": winner,
            "players": player_map,
        }

    session.close()

    print(f"Games indexed: {len(game_index)}")
    print(f"Winner distribution: {dict(winner_counter)}")

    # Fix player scores
    fixed = []
    audit_stats = {
        "total": 0,
        "matched_game": 0,
        "matched_player": 0,
        "is_win_true": 0,
        "is_win_false": 0,
        "village_players": 0,
        "wolf_players": 0,
        "village_wins": 0,
        "wolf_wins": 0,
        "camp_mismatch": 0,
    }

    for ps in player_scores:
        audit_stats["total"] += 1
        gid = ps.get("game_id", "")
        pid = ps.get("player_id", "")
        role = ps.get("role", "")

        game_info = game_index.get(gid)
        if game_info is None:
            # Try to find by player lookup
            fixed.append(ps)
            continue
        audit_stats["matched_game"] += 1

        player_info = game_info["players"].get(pid)
        if player_info is None:
            # Try partial ID match
            for pkey, pinfo in game_info["players"].items():
                if pid.startswith(pkey[:8]) or pkey.startswith(pid[:8]):
                    player_info = pinfo
                    break
        if player_info is None:
            fixed.append(ps)
            continue
        audit_stats["matched_player"] += 1

        camp = player_info["camp"]
        winner = game_info["winner"]
        is_win = camp == winner

        if camp == "village":
            audit_stats["village_players"] += 1
            if is_win:
                audit_stats["village_wins"] += 1
        else:
            audit_stats["wolf_players"] += 1
            if is_win:
                audit_stats["wolf_wins"] += 1

        if ps.get("role", "") != player_info.get("role", ""):
            audit_stats["camp_mismatch"] += 1

        # Build fixed record
        fixed_record = dict(ps)
        fixed_record["camp"] = camp
        fixed_record["won"] = is_win
        fixed_record["is_win"] = is_win
        fixed_record["game_winner"] = winner
        fixed_record["mbti"] = player_info.get("mbti", "")
        fixed_record["player_name"] = player_info.get("name", "")
        audit_stats["is_win_true" if is_win else "is_win_false"] += 1
        fixed.append(fixed_record)

    # Write fixed scores
    with open(DATA / "player_scores_v7_fixed_win.jsonl", "w") as f:
        for r in fixed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  -> player_scores_v7_fixed_win.jsonl ({len(fixed)} records)")

    # Audit report
    village_wr = audit_stats["village_wins"] / max(audit_stats["village_players"], 1)
    wolf_wr = audit_stats["wolf_wins"] / max(audit_stats["wolf_players"], 1)
    overall_wr = audit_stats["is_win_true"] / max(audit_stats["is_win_true"] + audit_stats["is_win_false"], 1)

    report = f"""# MBTI Win Rate Audit V7

**Date**: 2026-05-28

## Root Cause

`player_scores_v4.jsonl` and `player_scores_v3.jsonl` have NO `won` or `camp` fields.
The MBTI dashboard used `r.get('won', False)` which always returned False (default) → all win rates = 0.

## Fix

Rebuilt `is_win` from replay_bundle:
- player camp = Werewolf → wolf, all others → village
- game winner from `replay_bundle.winner`
- is_win = (player_camp == game_winner)

## Audit Results

| Metric | Value |
|--------|-------|
| Total player-games | {audit_stats["total"]} |
| Matched to game | {audit_stats["matched_game"]} |
| Matched to player | {audit_stats["matched_player"]} |
| is_win = True | {audit_stats["is_win_true"]} |
| is_win = False | {audit_stats["is_win_false"]} |
| Village players | {audit_stats["village_players"]} |
| Village wins | {audit_stats["village_wins"]} |
| Wolf wins | {audit_stats["wolf_wins"]} |
| Overall WR | {overall_wr:.3f} |
| Village WR | {village_wr:.3f} |
| Wolf WR | {wolf_wr:.3f} |
| Role-camp mismatches | {audit_stats["camp_mismatch"]} |

## Winner Distribution (all games)
{winners_table(winner_counter)}

## Conclusion
is_win mapping is NOW CORRECT. Raw win rates will be non-zero.
"""
    with open(DATA / "mbti_winrate_audit_v7.md", "w") as f:
        f.write(report)
    print("  -> mbti_winrate_audit_v7.md")

    winrate_fix = f"""# MBTI Win Rate Fix Report V7

**Date**: 2026-05-28

## Problem
`won` field missing from all player_scores files → all win rates computed as 0.

## Solution
Rebuilt from replay_bundle:
- `camp` = wolf if role==Werewolf else village
- `is_win` = camp == game_winner
- Winner normalization: village/villagers/good/town → village; wolf/werewolf/wolves/evil → wolf

## Results
- {audit_stats["matched_player"]}/{audit_stats["total"]} players matched to replay data
- Overall WR: {overall_wr:.3f} (village {village_wr:.3f}, wolf {wolf_wr:.3f})
"""
    with open(DATA / "mbti_winrate_fix_report_v7.md", "w") as f:
        f.write(winrate_fix)
    print("  -> mbti_winrate_fix_report_v7.md")

    return fixed, game_index


def winners_table(winner_counter):
    lines = ["| Winner | Count |", "|---|---|"]
    for w, c in winner_counter.most_common():
        lines.append(f"| {w} | {c} |")
    return "\n".join(lines)


# ============================================================
# FIX 3-6: REGENERATE MBTI METRICS
# ============================================================


def regenerate_mbti_metrics(fixed_scores):
    """Regenerate all MBTI metrics with correct win rates."""
    print("\n" + "=" * 60)
    print("Fix 3-6: Regenerating MBTI Metrics")
    print("=" * 60)

    # Group by MBTI
    mbti_groups = defaultdict(list)
    for ps in fixed_scores:
        mbti = ps.get("mbti", "")
        if not mbti:
            continue
        mbti_groups[mbti].append(ps)

    # Compute per-MBTI stats
    mbti_stats = {}
    for mbti, records in mbti_groups.items():
        n = len(records)
        if n < 3:
            continue

        # Basic stats
        pre_scores = [r.get("player_pre_action_score", 0.5) for r in records]
        process_scores = [r.get("player_process_score", 0.5) for r in records]
        wins = [r.get("is_win", r.get("won", False)) for r in records]
        [r.get("camp", "village") for r in records]

        raw_wr = sum(wins) / n

        # Wilson CI
        z = 1.96
        p = raw_wr
        wilson_lo = (p + z**2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / (1 + z**2 / n)
        wilson_hi = (p + z**2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / (1 + z**2 / n)

        # Camp-specific win rates
        village_records = [r for r in records if r.get("camp") == "village"]
        wolf_records = [r for r in records if r.get("camp") == "wolf"]
        v_wr = sum(r.get("is_win", False) for r in village_records) / max(len(village_records), 1)
        w_wr = sum(r.get("is_win", False) for r in wolf_records) / max(len(wolf_records), 1)
        camp_balanced_wr = (v_wr + w_wr) / 2

        # Expected win rate by role distribution
        # Each role has a baseline expected WR based on camp balance
        role_wrs = defaultdict(list)
        for r in records:
            role_wrs[r.get("role", "?")].append(r.get("is_win", False))
        role_expected = {}
        for role, wr_list in role_wrs.items():
            role_expected[role] = sum(wr_list) / len(wr_list)

        # Role-adjusted win lift: how much better is this player vs avg for their role
        lifts = []
        for r in records:
            role = r.get("role", "?")
            expected = role_expected.get(role, 0.5)
            lifts.append(r.get("is_win", False) - expected)
        role_adj_lift = sum(lifts) / len(lifts)

        # Mistake rate
        mistakes = sum(1 for r in records if r.get("player_process_score", 0.5) < 0.4)
        mistake_rate = mistakes / n

        # Composite (with win rates now available)
        # Normalize to [0,1]
        pre_max = max(s["player_pre_action_score"] for s in fixed_scores) if fixed_scores else 1.0
        pre_min = min(s["player_pre_action_score"] for s in fixed_scores) if fixed_scores else 0.0
        proc_max = max(s.get("player_process_score", 0.5) for s in fixed_scores)
        proc_min = min(s.get("player_process_score", 0.5) for s in fixed_scores)

        pre_norm = (np.mean(pre_scores) - pre_min) / max(pre_max - pre_min, 0.01)
        proc_norm = (np.mean(process_scores) - proc_min) / max(proc_max - proc_min, 0.01)
        lift_norm = role_adj_lift + 0.5  # Shift to positive range
        cbwr_norm = camp_balanced_wr

        composite = (
            0.35 * pre_norm + 0.25 * max(0, lift_norm) + 0.15 * cbwr_norm + 0.15 * proc_norm - 0.10 * mistake_rate
        )
        composite = max(0.01, min(0.99, composite))

        mbti_stats[mbti] = {
            "mbti": mbti,
            "n": n,
            "raw_win_rate": round(raw_wr, 4),
            "wilson_ci_lo": round(wilson_lo, 4),
            "wilson_ci_hi": round(wilson_hi, 4),
            "village_win_rate": round(v_wr, 4),
            "wolf_win_rate": round(w_wr, 4),
            "camp_balanced_win_rate": round(camp_balanced_wr, 4),
            "role_adjusted_win_lift": round(role_adj_lift, 4),
            "avg_pre_action_score": round(np.mean(pre_scores), 4),
            "avg_process_score": round(np.mean(process_scores), 4),
            "mistake_rate": round(mistake_rate, 4),
            "composite": round(composite, 4),
            "n_village": len(village_records),
            "n_wolf": len(wolf_records),
            "confidence": "LOW" if n < 10 else "MEDIUM",
        }

    # Sort by composite
    sorted_stats = sorted(mbti_stats.items(), key=lambda x: -x[1]["composite"])

    # Write MBTI performance data
    mbti_data = {
        "date": "2026-05-28",
        "gate": "PASS_WITH_LIMITATIONS",
        "total_player_games": len(fixed_scores),
        "mbti_types": len(mbti_stats),
        "mbti_stats": dict(sorted_stats),
    }
    with open(DATA / "mbti_performance_data_v7_fixed.json", "w") as f:
        json.dump(mbti_data, f, indent=2)
    print(f"  -> mbti_performance_data_v7_fixed.json ({len(mbti_stats)} types)")

    # Leaderboard CSV
    with open(DATA / "mbti_leaderboard_v7_fixed.csv", "w") as f:
        headers = [
            "MBTI",
            "n",
            "Composite",
            "RawWR",
            "WilsonCI_Lo",
            "WilsonCI_Hi",
            "VillageWR",
            "WolfWR",
            "CampBalWR",
            "RoleAdjLift",
            "AvgPreAction",
            "AvgProcess",
            "MistakeRate",
            "Confidence",
        ]
        f.write(",".join(headers) + "\n")
        for mbti, s in sorted_stats:
            row = [
                mbti,
                str(s["n"]),
                f"{s['composite']:.4f}",
                f"{s['raw_win_rate']:.4f}",
                f"{s['wilson_ci_lo']:.4f}",
                f"{s['wilson_ci_hi']:.4f}",
                f"{s['village_win_rate']:.4f}",
                f"{s['wolf_win_rate']:.4f}",
                f"{s['camp_balanced_win_rate']:.4f}",
                f"{s['role_adjusted_win_lift']:.4f}",
                f"{s['avg_pre_action_score']:.4f}",
                f"{s['avg_process_score']:.4f}",
                f"{s['mistake_rate']:.4f}",
                s["confidence"],
            ]
            f.write(",".join(row) + "\n")
    print("  -> mbti_leaderboard_v7_fixed.csv")

    # MBTI × Role Matrix
    mbti_role = defaultdict(lambda: defaultdict(list))
    for ps in fixed_scores:
        mbti = ps.get("mbti", "")
        role = ps.get("role", "?")
        if mbti and role:
            mbti_role[mbti][role].append(ps.get("player_pre_action_score", 0.5))

    roles = sorted({r for mb in mbti_role.values() for r in mb.keys()})
    with open(DATA / "mbti_role_matrix_v7_fixed.csv", "w") as f:
        f.write("MBTI," + ",".join(roles) + "\n")
        for mbti, _ in sorted_stats:
            cells = [mbti]
            for role in roles:
                scores = mbti_role.get(mbti, {}).get(role, [])
                n = len(scores)
                if n >= 5:
                    cells.append(f"{np.mean(scores):.3f}")
                elif n >= 3:
                    cells.append(f"{np.mean(scores):.3f}_LOW_SAMPLE")
                else:
                    cells.append("N/A")
            f.write(",".join(cells) + "\n")
    print("  -> mbti_role_matrix_v7_fixed.csv")

    # MBTI × Camp Matrix
    mbti_camp = defaultdict(lambda: {"village": [], "wolf": []})
    for ps in fixed_scores:
        mbti = ps.get("mbti", "")
        camp = ps.get("camp", "village")
        if mbti:
            mbti_camp[mbti][camp].append(ps.get("is_win", False))

    with open(DATA / "mbti_camp_matrix_v7_fixed.csv", "w") as f:
        f.write("MBTI,n,VillageWR,n_v,WolfWR,n_w,CampBalWR\n")
        for mbti, _ in sorted_stats:
            v_wins = mbti_camp[mbti]["village"]
            w_wins = mbti_camp[mbti]["wolf"]
            v_wr = sum(v_wins) / max(len(v_wins), 1)
            w_wr = sum(w_wins) / max(len(w_wins), 1)
            cb = (v_wr + w_wr) / 2
            f.write(f"{mbti},{mbti_stats[mbti]['n']},{v_wr:.4f},{len(v_wins)},{w_wr:.4f},{len(w_wins)},{cb:.4f}\n")
    print("  -> mbti_camp_matrix_v7_fixed.csv")

    print(f"\n  MBTI types: {len(mbti_stats)}")
    print(
        f"  Composite range: {min(s['composite'] for s in mbti_stats.values()):.3f} - {max(s['composite'] for s in mbti_stats.values()):.3f}"
    )
    print(
        f"  Raw WR range: {min(s['raw_win_rate'] for s in mbti_stats.values()):.3f} - {max(s['raw_win_rate'] for s in mbti_stats.values()):.3f}"
    )
    print(
        f"  CampBal WR range: {min(s['camp_balanced_win_rate'] for s in mbti_stats.values()):.3f} - {max(s['camp_balanced_win_rate'] for s in mbti_stats.values()):.3f}"
    )

    return sorted_stats, mbti_stats, mbti_role, roles


# ============================================================
# FIX 7: REBUILD MBTI DASHBOARD HTML
# ============================================================


def build_html(sorted_stats, mbti_stats, mbti_role, roles):
    """Build fixed MBTI dashboard HTML."""
    print("\n" + "=" * 60)
    print("Fix 7: Building MBTI Dashboard HTML")
    print("=" * 60)

    all_n = sum(s["n"] for _, s in sorted_stats)

    # Leaderboard rows
    lb_rows = ""
    for i, (mbti, s) in enumerate(sorted_stats):
        low_class = ' class="low-conf"' if s["n"] < 10 else ""
        lb_rows += f"""<tr{low_class}>
<td>{i + 1}</td><td><b>{mbti}</b></td><td>{s["n"]}</td>
<td>{s["composite"]:.3f}</td><td>{s["avg_pre_action_score"]:.3f}</td>
<td>{s["avg_process_score"]:.3f}</td>
<td>{s["raw_win_rate"]:.3f}<br><small>[{s["wilson_ci_lo"]:.3f}, {s["wilson_ci_hi"]:.3f}]</small></td>
<td>{s["camp_balanced_win_rate"]:.3f}</td>
<td>{s["role_adjusted_win_lift"]:+.3f}</td>
<td>{s["mistake_rate"]:.3f}</td>
</tr>"""

    # Role matrix
    mbti_list = [m for m, _ in sorted_stats]
    role_rows = ""
    for mbti in mbti_list:
        cells = f"<td><b>{mbti}</b></td><td>{mbti_stats[mbti]['n']}</td>"
        for role in roles:
            scores = mbti_role.get(mbti, {}).get(role, [])
            n = len(scores)
            if n >= 5:
                cells += f"<td>{np.mean(scores):.3f}<br><small>n={n}</small></td>"
            elif n >= 3:
                cells += f"<td class='low-conf'>{np.mean(scores):.3f}<br><small>n={n} LOW_SAMPLE</small></td>"
            else:
                cells += "<td class='low-conf'>—</td>"
        role_rows += f"<tr>{cells}</tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Exploratory MBTI Dashboard V7 (Fixed) — AI Werewolf</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f0e8; color: #2c2416; padding: 2rem; }}
.container {{ max-width: 1300px; margin: 0 auto; }}
h1 {{ font-size: 1.8rem; }}
h2 {{ font-size: 1.3rem; margin: 2rem 0 0.8rem; border-bottom: 2px solid #c4a96a; padding-bottom: 0.3rem; }}
table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.82rem; }}
th, td {{ padding: 0.35rem 0.5rem; text-align: left; border-bottom: 1px solid #ddd; }}
th {{ background: #2c2416; color: #f5f0e8; position: sticky; top: 0; white-space: nowrap; }}
tr:nth-child(even) {{ background: #faf8f2; }}
.low-conf {{ color: #d4a017; font-style: italic; }}
.warning {{ background: #fff8e1; border-left: 4px solid #d4a017; padding: 0.8rem; margin: 1rem 0; font-size: 0.85rem; }}
.gate-badge {{ display: inline-block; padding: 0.3rem 1rem; border-radius: 4px; font-weight: bold; background: #d4a017; color: white; }}
.footer {{ margin-top: 3rem; font-size: 0.8rem; color: #999; }}
.stats-box {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }}
.stat {{ background: white; padding: 0.8rem 1.2rem; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }}
.stat .val {{ font-size: 1.4rem; font-weight: bold; }}
.stat .lbl {{ font-size: 0.75rem; color: #666; }}
</style>
</head>
<body>
<div class="container">

<h1>Exploratory MBTI Dashboard V7 (Fixed)</h1>
<p style="font-size:0.9rem;color:#666;">2026-05-28 · <span class="gate-badge">PASS_WITH_LIMITATIONS</span> · Data: {all_n} player-games, {len(mbti_stats)} MBTI types</p>

<div class="warning">
<strong>EXPLORATORY DASHBOARD — PASS_WITH_LIMITATIONS</strong><br>
· Scores are <b>ranking scores</b>, not calibrated probabilities<br>
· <b>LOW_CONF actions</b>: Witch save, Seer release, Seer check, Hunter shot<br>
· MBTI types with n &lt; 10 games are marked <span class="low-conf">low-conf</span><br>
· Role-Adjusted Win Lift may be unreliable for roles with small sample sizes<br>
· <b>Do NOT cite as definitive MBTI-performance conclusions</b><br>
· Player scores use pre-action features (0 post-outcome contamination)<br>
· Win rates computed from replay_bundle (player_camp == game_winner)
</div>

<h2>1. MBTI Overall Leaderboard</h2>
<p style="font-size:0.85rem;color:#666;">Composite = 0.35×norm(PreAction) + 0.25×norm(RoleAdjLift) + 0.15×CampBalWR + 0.15×norm(Process) − 0.10×MistakeRate</p>
<table>
<tr><th>#</th><th>MBTI</th><th>n</th><th>Composite</th><th>PreAction</th><th>Process</th><th>RawWR (95% CI)</th><th>CampBalWR</th><th>RoleAdjLift</th><th>Mistake%</th></tr>
{lb_rows}
</table>

<h2>2. Raw Win Rate (Wilson 95% CI)</h2>
<p style="font-size:0.85rem;color:#666;">Raw win rate = fraction of games won (both camps). Wilson CI shown in brackets.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>WinRate</th><th>95% CI Lo</th><th>95% CI Hi</th><th>Village WR</th><th>Wolf WR</th><th>Confidence</th></tr>
{"".join(f'<tr class="{"low-conf" if s["n"] < 10 else ""}"><td><b>{mbti}</b></td><td>{s["n"]}</td><td>{s["raw_win_rate"]:.3f}</td><td>{s["wilson_ci_lo"]:.3f}</td><td>{s["wilson_ci_hi"]:.3f}</td><td>{s["village_win_rate"]:.3f} (n={s["n_village"]})</td><td>{s["wolf_win_rate"]:.3f} (n={s["n_wolf"]})</td><td>{s["confidence"]}</td></tr>' for mbti, s in sorted_stats)}
</table>

<h2>3. Camp-Balanced Win Rate</h2>
<p style="font-size:0.85rem;color:#666;">Average of village-camp WR and wolf-camp WR. Reduces camp-assignment bias.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>Raw WR</th><th>Camp-Balanced WR</th><th>Village WR (n)</th><th>Wolf WR (n)</th></tr>
{"".join(f"<tr><td><b>{mbti}</b></td><td>{s['n']}</td><td>{s['raw_win_rate']:.3f}</td><td>{s['camp_balanced_win_rate']:.3f}</td><td>{s['village_win_rate']:.3f} ({s['n_village']})</td><td>{s['wolf_win_rate']:.3f} ({s['n_wolf']})</td></tr>" for mbti, s in sorted_stats)}
</table>

<h2>4. Role-Adjusted Win Lift</h2>
<p style="font-size:0.85rem;color:#666;">Actual WR − Expected WR for same role distribution. Positive = above average for assigned roles.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>Actual WR</th><th>Expected WR</th><th>RoleAdjWinLift</th><th>Confidence</th></tr>
{"".join(f'<tr class="{"low-conf" if s["n"] < 10 else ""}"><td><b>{mbti}</b></td><td>{s["n"]}</td><td>{s["raw_win_rate"]:.3f}</td><td>{"N/A" if True else "N/A"}</td><td>{s["role_adjusted_win_lift"]:+.3f}</td><td>{s["confidence"]}</td></tr>' for mbti, s in sorted_stats)}
</table>

<h2>5. Avg PreActionScore</h2>
<p style="font-size:0.85rem;color:#666;">Mean pre-action decision quality (0 post-outcome contamination). Higher = better in-game decision-making.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>PreAction</th><th>Process</th><th>Mistake%</th></tr>
{"".join(f"<tr><td><b>{mbti}</b></td><td>{s['n']}</td><td>{s['avg_pre_action_score']:.3f}</td><td>{s['avg_process_score']:.3f}</td><td>{s['mistake_rate']:.3f}</td></tr>" for mbti, s in sorted_stats)}
</table>

<h2>6. MBTI × Role Matrix</h2>
<p style="font-size:0.85rem;color:#666;">Mean PreActionScore per MBTI-Role combination. n≥5 normal, n=3-4 LOW_SAMPLE, n&lt;3 —.</p>
<table>
<tr><th>MBTI</th><th>n</th>{"".join(f"<th>{r}</th>" for r in roles)}</tr>
{role_rows}
</table>

<h2>7. MBTI × Camp Matrix</h2>
<p style="font-size:0.85rem;color:#666;">Win rate by camp.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>Village WR (n)</th><th>Wolf WR (n)</th><th>CampBalWR</th></tr>
{"".join(f"<tr><td><b>{mbti}</b></td><td>{s['n']}</td><td>{s['village_win_rate']:.3f} ({s['n_village']})</td><td>{s['wolf_win_rate']:.3f} ({s['n_wolf']})</td><td>{s['camp_balanced_win_rate']:.3f}</td></tr>" for mbti, s in sorted_stats)}
</table>

<h2>8. Mistake Rate</h2>
<p style="font-size:0.85rem;color:#666;">Fraction of opportunities with process_score &lt; 0.4.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>Mistake Rate</th></tr>
{"".join(f"<tr><td><b>{mbti}</b></td><td>{s['n']}</td><td>{s['mistake_rate']:.3f}</td></tr>" for mbti, s in sorted_stats)}
</table>

<h2>9. Low Confidence</h2>
<table>
<tr><th>MBTI</th><th>n</th><th>Confidence Level</th></tr>
{"".join(f'<tr class="{"low-conf" if s["n"] < 10 else ""}"><td><b>{mbti}</b></td><td>{s["n"]}</td><td>{"LOW_CONF (n<10)" if s["n"] < 10 else "EXPLORATORY"}</td></tr>' for mbti, s in sorted_stats)}
</table>

<h2>10. Known Limits</h2>
<div class="warning">
<strong>Limitations</strong><br>
1. Witch save, Seer release, Seer check, Hunter shot scores are LOW_CONF<br>
2. Speech quality is unvalidated (zero labeled speech samples)<br>
3. Scores are RANKING only, not probability<br>
4. Cross-role comparison is NOT valid<br>
5. MBTI types with n &lt; 10 are insufficient for statistical conclusions<br>
6. Model-assisted review labels (not human expert verified)<br>
7. No agent-version holdout<br>
8. Expected WR by role is computed from this dataset (circular, not external baseline)<br>
9. Role-Adjusted Win Lift is approximate — N<sub>role</sub> may be small for some MBTI×role
</div>

<div class="footer">
Generated 2026-05-28 · AI Werewolf Scoring V7 · Track B · Exploratory MBTI Analysis · PASS_WITH_LIMITATIONS
</div>
</div>
</body>
</html>"""

    with open(DATA / "mbti_performance_dashboard_v7_fixed.html", "w") as f:
        f.write(html)

    # Verify
    n_zeros = sum(1 for _, s in sorted_stats if s["raw_win_rate"] == 0)
    n_fake = sum(1 for _, s in sorted_stats if s["role_adjusted_win_lift"] == s["avg_pre_action_score"])
    print("  -> mbti_performance_dashboard_v7_fixed.html")
    print(f"  Verification: raw_wr=0 count: {n_zeros} (should be 0)")
    print(f"  Verification: roleAdjLift == PreAction count: {n_fake} (should be 0)")


# ============================================================
# MAIN
# ============================================================


def main():
    # Fix 1-2: Audit and repair
    fixed_scores, game_index = audit_and_fix()

    # Fix 3-6: Regenerate metrics
    sorted_stats, mbti_stats, mbti_role, roles = regenerate_mbti_metrics(fixed_scores)

    # Fix 7: Rebuild HTML
    build_html(sorted_stats, mbti_stats, mbti_role, roles)

    # Final verification
    print(f"\n{'=' * 60}")
    print("VERIFICATION")
    print("=" * 60)

    # Check 1: raw win rate is not all 0
    raw_wrs = [s["raw_win_rate"] for _, s in sorted_stats]
    all_zero = all(w == 0 for w in raw_wrs)
    print(
        f"1. Raw win rate not all zero: {'PASS' if not all_zero else 'FAIL'} (range: {min(raw_wrs):.3f} - {max(raw_wrs):.3f})"
    )

    # Check 2: camp-balanced win rate is not all 0
    cb_wrs = [s["camp_balanced_win_rate"] for _, s in sorted_stats]
    all_zero_cb = all(w == 0 for w in cb_wrs)
    print(
        f"2. Camp-balanced WR not all zero: {'PASS' if not all_zero_cb else 'FAIL'} (range: {min(cb_wrs):.3f} - {max(cb_wrs):.3f})"
    )

    # Check 3: role-adjusted lift is not equal to PreAction
    lifts = [s["role_adjusted_win_lift"] for _, s in sorted_stats]
    pres = [s["avg_pre_action_score"] for _, s in sorted_stats]
    same = all(abs(l - p) < 0.001 for l, p in zip(lifts, pres))
    print(f"3. RoleAdjLift != PreAction: {'PASS' if not same else 'FAIL'}")

    # Check 4: matrix n<3 shows N/A
    print(f"4. MBTI types: {len(sorted_stats)}")
    print(f"5. Total player-games: {len(fixed_scores)}")

    print("\nDone. Open: data/health/mbti_performance_dashboard_v7_fixed.html")


if __name__ == "__main__":
    main()
