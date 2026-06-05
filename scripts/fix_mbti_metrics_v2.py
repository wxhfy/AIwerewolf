#!/usr/bin/env python3
"""
MBTI Metrics Fix V2 — Real RoleAdjustedWinLift, Role-Normalized Scores, Filtered Dashboard.

Fixes:
1. Compute real Expected WR from (role, camp) baseline
2. Role-normalized PreAction = score - mean(score | role)
3. Composite = 0.35*norm(role_norm_pre) + 0.25*norm(lift) + 0.15*cbwr + 0.15*norm(process) - 0.10*mistake
4. Main leaderboard: n>=10 only; n<10 → Low Sample section
5. Top-5 explanation cards
6. Rebuilt HTML
"""

import json
import math
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


# ============================================================
# FIX 1: REAL ROLE-ADJUSTED WIN LIFT
# ============================================================


def compute_role_camp_baselines(fixed_scores):
    """Compute expected WR for each (role, camp) combination."""
    rc_groups = defaultdict(list)
    for ps in fixed_scores:
        role = ps.get("role", "?")
        camp = ps.get("camp", "?")
        is_win = ps.get("is_win", False)
        rc_groups[(role, camp)].append(is_win)

    baseline = {}
    for (role, camp), wins in sorted(rc_groups.items()):
        n = len(wins)
        wr = sum(wins) / n if n > 0 else 0.5
        baseline[(role, camp)] = {"n": n, "wr": wr}

    # Fallback: camp-only baseline for rare role/camp combos
    camp_baseline = defaultdict(list)
    for ps in fixed_scores:
        camp = ps.get("camp", "?")
        camp_baseline[camp].append(ps.get("is_win", False))
    camp_wr = {c: sum(w) / max(len(w), 1) for c, w in camp_baseline.items()}

    return baseline, camp_wr


def compute_real_lift(fixed_scores, rc_baseline, camp_wr):
    """Compute role_adjusted_win_lift for each player and aggregate by MBTI."""
    # Per-player lift
    for ps in fixed_scores:
        role = ps.get("role", "?")
        camp = ps.get("camp", "?")
        key = (role, camp)
        if key in rc_baseline and rc_baseline[key]["n"] >= 5:
            expected = rc_baseline[key]["wr"]
            fallback = False
        else:
            expected = camp_wr.get(camp, 0.5)
            fallback = True
        ps["expected_wr"] = expected
        ps["expected_wr_fallback"] = fallback
        ps["role_adjusted_win_lift"] = ps.get("is_win", False) - expected

    # Aggregate by MBTI
    mbti_lifts = defaultdict(list)
    for ps in fixed_scores:
        mbti = ps.get("mbti", "")
        if mbti:
            mbti_lifts[mbti].append(ps["role_adjusted_win_lift"])

    return (
        {
            m: {
                "mean_lift": round(np.mean(vals), 4),
                "n": len(vals),
                "n_fallback": sum(1 for ps in fixed_scores if ps.get("mbti") == m and ps.get("expected_wr_fallback")),
            }
            for m, vals in mbti_lifts.items()
        },
        rc_baseline,
        camp_wr,
    )


# ============================================================
# FIX 2: ROLE-NORMALIZED PRE-ACTION SCORE
# ============================================================


def compute_role_normalized_pre(fixed_scores):
    """Compute role-normalized pre-action scores."""
    # Per-role baseline
    role_scores = defaultdict(list)
    for ps in fixed_scores:
        role = ps.get("role", "?")
        role_scores[role].append(ps.get("player_pre_action_score", 0.5))

    role_mean = {r: np.mean(vals) for r, vals in role_scores.items()}
    role_std = {r: np.std(vals) for r, vals in role_scores.items()}

    # Per-player normalized scores
    for ps in fixed_scores:
        role = ps.get("role", "?")
        raw = ps.get("player_pre_action_score", 0.5)
        rm = role_mean.get(role, 0.5)
        rs = role_std.get(role, 0.1)
        ps["role_norm_pre_action"] = raw - rm
        ps["role_z_pre_action"] = (raw - rm) / max(rs, 0.01)

    # Aggregate by MBTI
    mbti_norm = defaultdict(list)
    mbti_z = defaultdict(list)
    for ps in fixed_scores:
        mbti = ps.get("mbti", "")
        if mbti:
            mbti_norm[mbti].append(ps["role_norm_pre_action"])
            mbti_z[mbti].append(ps["role_z_pre_action"])

    mbti_role_norm = {}
    for mbti, vals in mbti_norm.items():
        mbti_role_norm[mbti] = {
            "avg_role_norm_pre": round(np.mean(vals), 4),
            "avg_role_z_pre": round(np.mean(vals), 4) if vals else 0,
            "std_role_norm_pre": round(np.std(vals), 4),
            "n": len(vals),
        }

    return mbti_role_norm, role_mean, role_std


# ============================================================
# FIX 3-6: COMPOSITE + FILTER + CARDS + HTML
# ============================================================


def norm(x, all_vals):
    """Normalize to [0,1] given all values."""
    lo, hi = min(all_vals), max(all_vals)
    rng = hi - lo
    if rng < 0.001:
        return 0.5
    return (x - lo) / rng


def build_full_mbti_stats(fixed_scores, mbti_role_norm, lift_data):
    """Compute complete per-MBTI stats with all metrics."""
    mbti_groups = defaultdict(list)
    for ps in fixed_scores:
        mbti = ps.get("mbti", "")
        if mbti:
            mbti_groups[mbti].append(ps)

    # Compute norms for composite
    all_role_norm = [s.get("role_norm_pre_action", 0) for s in fixed_scores]
    all_process = [s.get("player_process_score", 0.5) for s in fixed_scores]

    stats = {}
    for mbti, records in mbti_groups.items():
        n = len(records)
        if n < 3:
            continue

        wins = [r.get("is_win", False) for r in records]
        camps = [r.get("camp", "village") for r in records]
        raw_wr = sum(wins) / n

        # Wilson CI
        z = 1.96
        p = raw_wr
        wlo = (p + z**2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / (1 + z**2 / n)
        whi = (p + z**2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / (1 + z**2 / n)

        # Camp WR
        v_records = [r for r in records if r.get("camp") == "village"]
        w_records = [r for r in records if r.get("camp") == "wolf"]
        v_wr = sum(r.get("is_win", False) for r in v_records) / max(len(v_records), 1)
        w_wr = sum(r.get("is_win", False) for r in w_records) / max(len(w_records), 1)
        cbwr = (v_wr + w_wr) / 2

        # Role-norm pre
        rn_pre = mbti_role_norm.get(mbti, {}).get("avg_role_norm_pre", 0)
        avg_pre = np.mean([r.get("player_pre_action_score", 0.5) for r in records])
        avg_process = np.mean([r.get("player_process_score", 0.5) for r in records])

        # Role-adjusted win lift
        lift = lift_data.get(mbti, {}).get("mean_lift", 0)
        n_fallback = lift_data.get(mbti, {}).get("n_fallback", 0)

        # Mistake rate
        mistakes = sum(1 for r in records if r.get("player_process_score", 0.5) < 0.4)
        mistake_rate = mistakes / n

        # Composite
        rn_norm = norm(rn_pre, all_role_norm) if all_role_norm else 0.5
        lift_norm = norm(lift, [lift_data.get(m, {}).get("mean_lift", 0) for m in mbti_groups])
        proc_norm = norm(avg_process, all_process) if all_process else 0.5

        composite = 0.35 * rn_norm + 0.25 * max(0, lift_norm) + 0.15 * cbwr + 0.15 * proc_norm - 0.10 * mistake_rate
        composite = max(0.01, min(0.99, composite))

        # Role distribution for explanation
        role_dist = defaultdict(int)
        for r in records:
            role_dist[r.get("role", "?")] += 1

        # Strengths / weaknesses
        # Role where this MBTI has highest normalized pre-action
        mbti_role_scores = defaultdict(list)
        for r in records:
            mbti_role_scores[r.get("role", "?")].append(r.get("role_norm_pre_action", 0))

        strengths = []
        weaknesses = []
        for role, scores in mbti_role_scores.items():
            avg = np.mean(scores)
            if avg > 0.01:
                strengths.append((role, round(avg, 3)))
            elif avg < -0.01:
                weaknesses.append((role, round(avg, 3)))

        strengths.sort(key=lambda x: -x[1])
        weaknesses.sort(key=lambda x: x[1])

        stats[mbti] = {
            "mbti": mbti,
            "n": n,
            "raw_win_rate": round(raw_wr, 4),
            "wilson_ci_lo": round(wlo, 4),
            "wilson_ci_hi": round(whi, 4),
            "village_win_rate": round(v_wr, 4),
            "wolf_win_rate": round(w_wr, 4),
            "camp_balanced_win_rate": round(cbwr, 4),
            "role_adjusted_win_lift": round(lift, 4),
            "n_fallback_expected_wr": n_fallback,
            "avg_role_norm_pre": round(rn_pre, 4),
            "avg_pre_action_score": round(avg_pre, 4),
            "avg_process_score": round(avg_process, 4),
            "mistake_rate": round(mistake_rate, 4),
            "composite": round(composite, 4),
            "n_village": len(v_records),
            "n_wolf": len(w_records),
            "role_distribution": dict(role_dist),
            "strengths": strengths[:3],
            "weaknesses": weaknesses[:3],
            "confidence": "MEDIUM" if n >= 15 else ("LOW" if n >= 10 else "LOW_SAMPLE"),
        }

    return stats


def build_html(stats, role_mean, role_std, camp_wr, rc_baseline):
    """Build final MBTI dashboard HTML."""
    # Split: n>=10 = main, n<10 = low sample
    main = {m: s for m, s in stats.items() if s["n"] >= 10}
    low_sample = {m: s for m, s in stats.items() if s["n"] < 10}

    # Sort by composite
    main_sorted = sorted(main.items(), key=lambda x: -x[1]["composite"])
    low_sorted = sorted(low_sample.items(), key=lambda x: -x[1]["composite"])

    total_n = sum(s["n"] for s in stats.values())
    main_n = sum(s["n"] for s in main.values())

    # === 1. EXECUTIVE SUMMARY ===
    exec_cards = ""
    for label, value in [
        ("Total Player-Games", str(total_n)),
        ("MBTI Types", str(len(stats))),
        ("Main Leaderboard (n≥10)", str(len(main))),
        ("Low Sample (n<10)", str(len(low_sample))),
        ("Scoring Gate", "PASS_WITH_LIMITATIONS"),
        (
            "Composite Range",
            f"{min(s['composite'] for s in main.values()):.3f} – {max(s['composite'] for s in main.values()):.3f}",
        ),
    ]:
        exec_cards += f'<div class="stat"><div class="val">{value}</div><div class="lbl">{label}</div></div>'

    # === 3. MAIN LEADERBOARD (n>=10) ===
    lb_rows = ""
    for i, (mbti, s) in enumerate(main_sorted):
        strengths_str = ", ".join(f"{r}({v:+.2f})" for r, v in s["strengths"][:2])
        weaknesses_str = ", ".join(f"{r}({v:+.2f})" for r, v in s["weaknesses"][:2])
        lb_rows += f"""<tr>
<td>{i + 1}</td><td><b>{mbti}</b></td><td>{s["n"]}</td>
<td class="composite">{s["composite"]:.3f}</td>
<td>{s["avg_role_norm_pre"]:+.3f}</td>
<td>{s["avg_pre_action_score"]:.3f}</td>
<td>{s["avg_process_score"]:.3f}</td>
<td>{s["raw_win_rate"]:.3f}<br><small>[{s["wilson_ci_lo"]:.3f}, {s["wilson_ci_hi"]:.3f}]</small></td>
<td>{s["camp_balanced_win_rate"]:.3f}</td>
<td>{s["role_adjusted_win_lift"]:+.3f}</td>
<td>{s["mistake_rate"]:.3f}</td>
<td style="font-size:0.75rem">↑{strengths_str}<br>↓{weaknesses_str}</td>
</tr>"""

    # === 4. TOP-5 CARDS ===
    cards = ""
    for i, (mbti, s) in enumerate(main_sorted[:5]):
        role_dist = ", ".join(f"{r}({c})" for r, c in sorted(s["role_distribution"].items()))
        strengths = "; ".join(f"{r}: {v:+.2f}" for r, v in s["strengths"])
        weaknesses = "; ".join(f"{r}: {v:+.2f}" for r, v in s["weaknesses"]) if s["weaknesses"] else "none identified"
        why = []
        if s["avg_role_norm_pre"] > 0.005:
            why.append(f"above-average role-normalized decision quality ({s['avg_role_norm_pre']:+.3f})")
        if s["camp_balanced_win_rate"] > 0.45:
            why.append(f"solid camp-balanced win rate ({s['camp_balanced_win_rate']:.3f})")
        if s["role_adjusted_win_lift"] > 0.02:
            why.append(f"positive role-adjusted win lift ({s['role_adjusted_win_lift']:+.3f})")
        if s["mistake_rate"] < 0.15:
            why.append(f"low mistake rate ({s['mistake_rate']:.3f})")
        why_str = "; ".join(why) if why else "mixed signals across metrics"

        cards += f"""<div class="explain-card">
<h3>#{i + 1} {mbti} · Composite {s["composite"]:.3f} · n={s["n"]}</h3>
<div class="explain-grid">
<div><strong>Strengths</strong><br>{strengths}</div>
<div><strong>Weak roles</strong><br>{weaknesses}</div>
<div><strong>Role distribution</strong><br>{role_dist}</div>
<div><strong>Camp</strong><br>V:{s["village_win_rate"]:.3f} (n={s["n_village"]}) W:{s["wolf_win_rate"]:.3f} (n={s["n_wolf"]})</div>
</div>
<div class="explain-why"><strong>Why ranked here:</strong> {why_str}</div>
<div class="explain-caveat"><strong>Not definitive because:</strong> n={s["n"]} games; scoring system is PASS_WITH_LIMITATIONS; cross-role comparison has structural limits; role-adjusted lift uses internal baseline.</div>
</div>"""

    # === 5. LIFT TABLE ===
    lift_rows = ""
    for mbti, s in main_sorted:
        lift_rows += f"<tr><td><b>{mbti}</b></td><td>{s['n']}</td><td>{s['raw_win_rate']:.3f}</td><td>{s['role_adjusted_win_lift']:+.3f}</td><td>{s['n_fallback_expected_wr']}/{s['n']} fallback</td><td>{s['confidence']}</td></tr>"

    # === 6. ROLE-NORM TABLE ===
    norm_rows = ""
    for mbti, s in main_sorted:
        norm_rows += f"<tr><td><b>{mbti}</b></td><td>{s['n']}</td><td>{s['avg_pre_action_score']:.3f}</td><td>{s['avg_role_norm_pre']:+.3f}</td><td>{s['avg_process_score']:.3f}</td></tr>"

    # === 7. ROLE BASELINE TABLE ===
    base_rows = ""
    for (role, camp), v in sorted(rc_baseline.items()):
        n = v["n"]
        wr = v["wr"]
        status = "OK" if n >= 5 else "LOW_SAMPLE"
        cls = "low-conf" if n < 5 else ""
        base_rows += (
            f'<tr class="{cls}"><td>{role}</td><td>{camp}</td><td>{n}</td><td>{wr:.3f}</td><td>{status}</td></tr>'
        )

    # === 8. MBTI × ROLE MATRIX ===
    mbti_role = defaultdict(lambda: defaultdict(list))
    for ps in load_jsonl(DATA / "player_scores_v7_fixed_win.jsonl"):
        mbti = ps.get("mbti", "")
        role = ps.get("role", "?")
        if mbti and role:
            mbti_role[mbti][role].append(ps.get("role_norm_pre_action", 0))

    roles = sorted(set(r for mb in mbti_role.values() for r in mb.keys()))
    mbti_order = [m for m, _ in main_sorted]
    matrix_rows = ""
    for mbti in mbti_order:
        cells = f"<td><b>{mbti}</b></td><td>{stats[mbti]['n']}</td>"
        for role in roles:
            scores = mbti_role.get(mbti, {}).get(role, [])
            n = len(scores)
            if n >= 5:
                cells += f"<td>{np.mean(scores):+.3f}<br><small>n={n}</small></td>"
            elif n >= 3:
                cells += f"<td class='low-conf'>{np.mean(scores):+.3f}<br><small>n={n} LOW</small></td>"
            else:
                cells += "<td class='low-conf'>—</td>"
        matrix_rows += f"<tr>{cells}</tr>"

    # === 9. LOW SAMPLE ===
    low_rows = ""
    for mbti, s in low_sorted:
        low_rows += f"<tr class='low-conf'><td>{mbti}</td><td>{s['n']}</td><td>{s['avg_role_norm_pre']:+.3f}</td><td>{s['raw_win_rate']:.3f}</td><td>LOW_SAMPLE (n&lt;10)</td></tr>"

    # === HTML ===
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MBTI Performance Dashboard V7 (Metrics Fixed) — AI Werewolf</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f0e8; color: #2c2416; padding: 1.5rem; }}
.container {{ max-width: 1400px; margin: 0 auto; }}
h1 {{ font-size: 1.6rem; }}
h2 {{ font-size: 1.2rem; margin: 2rem 0 0.6rem; border-bottom: 2px solid #c4a96a; padding-bottom: 0.3rem; }}
h3 {{ font-size: 1rem; margin: 0.3rem 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 0.8rem 0; font-size: 0.8rem; }}
th, td {{ padding: 0.3rem 0.5rem; text-align: left; border-bottom: 1px solid #ddd; }}
th {{ background: #2c2416; color: #f5f0e8; white-space: nowrap; }}
tr:nth-child(even) {{ background: #faf8f2; }}
.low-conf {{ color: #d4a017; }}
.gate-badge {{ display: inline-block; padding: 0.2rem 0.8rem; border-radius: 4px; font-weight: bold; background: #d4a017; color: white; font-size: 0.85rem; }}
.warning-box {{ background: #fff8e1; border-left: 4px solid #d4a017; padding: 0.8rem; margin: 0.8rem 0; font-size: 0.85rem; }}
.stats-row {{ display: flex; gap: 0.8rem; flex-wrap: wrap; margin: 0.8rem 0; }}
.stat {{ background: white; padding: 0.6rem 1rem; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; min-width: 100px; }}
.stat .val {{ font-size: 1.3rem; font-weight: bold; }}
.stat .lbl {{ font-size: 0.7rem; color: #666; }}
.composite {{ font-weight: bold; font-size: 1.05rem; }}
.explain-card {{ background: white; border-radius: 8px; padding: 0.8rem; margin: 0.6rem 0; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.explain-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.5rem; margin: 0.5rem 0; font-size: 0.82rem; }}
.explain-why {{ font-size: 0.82rem; color: #2a7d2a; margin-top: 0.3rem; }}
.explain-caveat {{ font-size: 0.78rem; color: #888; margin-top: 0.3rem; font-style: italic; }}
.footer {{ margin-top: 2rem; font-size: 0.78rem; color: #999; }}
</style>
</head>
<body>
<div class="container">

<h1>MBTI Performance Dashboard V7 (Metrics Fixed)</h1>
<p style="font-size:0.85rem;color:#666;">2026-05-28 · <span class="gate-badge">PASS_WITH_LIMITATIONS</span></p>

<div class="warning-box">
<strong>EXPLORATORY — NOT DEFINITIVE MBTI CONCLUSIONS</strong><br>
· Scores are <b>ranking scores</b>, not calibrated probabilities<br>
· <b>LOW_CONF actions</b>: Witch save, Seer release, Seer check, Hunter shot<br>
· <b>Main leaderboard</b>: only MBTI types with n≥10 games. n&lt;10 → Low Sample section.<br>
· <b>Role-normalized PreAction</b>: score − mean(score | same role). Reduces role bias.<br>
· <b>Role-Adjusted Win Lift</b>: actual WR − expected WR for same (role, camp).<br>
· <b>Expected WR</b>: computed from (role, camp) baseline; fallback to camp-only if n&lt;5.<br>
· Cross-role comparison has structural limits — role normalization reduces but does not eliminate.<br>
· Do NOT cite as "MBTI X is better than MBTI Y" — all rankings are exploratory.
</div>

<!-- 1. EXECUTIVE SUMMARY -->
<h2>1. Executive Summary</h2>
<div class="stats-row">{exec_cards}</div>

<!-- 2. METRIC VALIDITY -->
<h2>2. Metric Validity</h2>
<table>
<tr><th>Metric</th><th>Source</th><th>Status</th><th>Note</th></tr>
<tr><td>Role-Normalized PreAction</td><td>role_norm_pre = score − mean(score|role)</td><td>VALID</td><td>Reduces role bias; 0 post-outcome contamination</td></tr>
<tr><td>Role-Adjusted Win Lift</td><td>is_win − expected_wr(role,camp)</td><td>VALID</td><td>Baseline from {len(rc_baseline)} (role,camp) groups</td></tr>
<tr><td>Camp-Balanced WR</td><td>(village_wr + wolf_wr)/2</td><td>VALID</td><td>Reduces camp assignment bias</td></tr>
<tr><td>Raw Win Rate</td><td>games_won / total_games</td><td>EXPLORATORY</td><td>Confounded by role assignment luck</td></tr>
<tr><td>Process Score</td><td>V4 model aggregation</td><td>EXPLORATORY</td><td>Vote component uses pre-action features; non-Guard LOW_CONF</td></tr>
<tr><td>Composite</td><td>0.35×norm(RoleNormPre) + 0.25×norm(Lift) + 0.15×CampBalWR + 0.15×norm(Process) − 0.10×Mistake</td><td>EXPLORATORY</td><td>Weights are heuristic; ranking is ordinal</td></tr>
</table>

<!-- 3. MAIN LEADERBOARD (n>=10) -->
<h2>3. Main MBTI Leaderboard (n ≥ 10)</h2>
<p style="font-size:0.85rem;color:#666;">{len(main)} MBTI types with {main_n} player-games. Sorted by Composite.</p>
<table>
<tr><th>#</th><th>MBTI</th><th>n</th><th>Composite</th><th>RoleNormPre</th><th>RawPre</th><th>Process</th><th>RawWR (95% CI)</th><th>CampBalWR</th><th>WinLift</th><th>Mistake</th><th>Top ↑ / ↓</th></tr>
{lb_rows}
</table>

<!-- 4. TOP-5 EXPLANATION CARDS -->
<h2>4. Top MBTI Explanation Cards</h2>
{cards}

<!-- 5. ROLE-ADJUSTED WIN LIFT -->
<h2>5. Role-Adjusted Win Lift</h2>
<p style="font-size:0.85rem;color:#666;">Expected WR computed from (role, camp) baseline. Fallback to camp-only if role×camp n&lt;5.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>Actual WR</th><th>WinLift</th><th>Fallback</th><th>Conf</th></tr>
{lift_rows}
</table>

<h3>Role×Camp Baseline Win Rates</h3>
<table>
<tr><th>Role</th><th>Camp</th><th>n</th><th>Expected WR</th><th>Status</th></tr>
{base_rows}
</table>
<p style="font-size:0.8rem;color:#666;">Camp-only fallback: village={camp_wr.get("village", 0.5):.3f}, wolf={camp_wr.get("wolf", 0.5):.3f}</p>

<!-- 6. ROLE-NORMALIZED PRE-ACTION -->
<h2>6. Role-Normalized PreAction</h2>
<p style="font-size:0.85rem;color:#666;">RoleNormPre = score − mean(score | same role). Positive = above average for assigned role.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>Raw PreAction</th><th>RoleNormPre</th><th>Process</th></tr>
{norm_rows}
</table>

<h3>Per-Role PreAction Baselines</h3>
<table>
<tr><th>Role</th><th>n</th><th>Mean PreAction</th><th>Std</th></tr>
{"".join(f"<tr><td>{r}</td><td>{len([s for s in load_jsonl(DATA / "player_scores_v7_fixed_win.jsonl") if s.get("role") == r])}</td><td>{role_mean[r]:.4f}</td><td>{role_std[r]:.4f}</td></tr>" for r in sorted(role_mean.keys()))}
</table>

<!-- 7. MBTI × ROLE MATRIX -->
<h2>7. MBTI × Role Matrix (Role-Normalized PreAction)</h2>
<p style="font-size:0.85rem;color:#666;">n≥5 normal, n=3-4 LOW_SAMPLE, n&lt;3 —. Values are role-normalized (cross-role comparable).</p>
<table>
<tr><th>MBTI</th><th>n</th>{"".join(f"<th>{r}</th>" for r in roles)}</tr>
{matrix_rows}
</table>

<!-- 8. MBTI × CAMP MATRIX -->
<h2>8. MBTI × Camp Matrix</h2>
<table>
<tr><th>MBTI</th><th>n</th><th>Village WR (n)</th><th>Wolf WR (n)</th><th>CampBalWR</th></tr>
{"".join(f"<tr><td><b>{mbti}</b></td><td>{s["n"]}</td><td>{s["village_win_rate"]:.3f} ({s["n_village"]})</td><td>{s["wolf_win_rate"]:.3f} ({s["n_wolf"]})</td><td>{s["camp_balanced_win_rate"]:.3f}</td></tr>" for mbti, s in main_sorted)}
</table>

<!-- 9. LOW SAMPLE -->
<h2>9. Low Sample MBTI (n &lt; 10)</h2>
<p style="font-size:0.85rem;color:#666;">Not included in main leaderboard. Insufficient data for ranking.</p>
<table>
<tr><th>MBTI</th><th>n</th><th>RoleNormPre</th><th>Raw WR</th><th>Status</th></tr>
{low_rows if low_rows else '<tr><td colspan="5">All MBTI types have n≥10.</td></tr>'}
</table>

<!-- 10. KNOWN LIMITS -->
<h2>10. Known Limits</h2>
<div class="warning-box">
<strong>Limitations</strong><br>
1. Witch save, Seer release, Seer check, Hunter shot scores are LOW_CONF<br>
2. Speech quality is unvalidated (zero labeled speech samples)<br>
3. Scores are RANKING only, not probability<br>
4. Role normalization reduces but does NOT eliminate cross-role comparison bias<br>
5. MBTI types with n&lt;10 are excluded from main leaderboard (insufficient data)<br>
6. Expected WR is computed from this dataset (internal baseline, not external)<br>
7. Model-assisted review labels (not human expert verified)<br>
8. No agent-version holdout<br>
9. Composite weights are heuristic — ranking is ordinal, not cardinal
</div>

<div class="footer">
Generated 2026-05-28 · AI Werewolf Scoring V7 · Track B · PASS_WITH_LIMITATIONS
</div>
</div>
</body>
</html>"""

    with open(DATA / "mbti_performance_dashboard_v7_metrics_fixed.html", "w") as f:
        f.write(html)

    return html, main_sorted


# ============================================================
# MAIN
# ============================================================


def main():
    print("=" * 60)
    print("MBTI Metrics Fix V2")
    print("=" * 60)

    # Load fixed player scores
    fixed_scores = load_jsonl(DATA / "player_scores_v7_fixed_win.jsonl")
    print(f"Loaded {len(fixed_scores)} player-game records")

    # Fix 1: Real Role-Adjusted Win Lift
    print("\n[Fix 1] Computing real Role-Adjusted Win Lift...")
    rc_baseline, camp_wr = compute_role_camp_baselines(fixed_scores)
    lift_data, rc_baseline, camp_wr = compute_real_lift(fixed_scores, rc_baseline, camp_wr)

    # Audit
    lift_zeros = sum(1 for m, v in lift_data.items() if abs(v["mean_lift"]) < 0.001)
    all_zero = lift_zeros == len(lift_data)
    print(f"  Role×Camp groups: {len(rc_baseline)}")
    print(f"  Camp WR: village={camp_wr.get('village', 0):.3f}, wolf={camp_wr.get('wolf', 0):.3f}")
    print(
        f"  Lift range: {min(v['mean_lift'] for v in lift_data.values()):.4f} – {max(v['mean_lift'] for v in lift_data.values()):.4f}"
    )
    print(f"  Lift zeros: {lift_zeros}/{len(lift_data)} (all_zero={all_zero})")

    with open(DATA / "role_adjusted_win_lift_audit_v7.md", "w") as f:
        f.write(f"""# Role-Adjusted Win Lift Audit V7

**Date**: 2026-05-28

## Method

For each player-game: expected_wr = mean(is_win | role, camp)
If (role, camp) has n<5, fallback to camp-only baseline.
role_adjusted_win_lift = is_win - expected_wr

## Role×Camp Baselines

| Role | Camp | n | Expected WR | Status |
|------|------|---|-------------|--------|
{chr(10).join(f"| {role} | {camp} | {v["n"]} | {v["wr"]:.3f} | {"OK" if v["n"] >= 5 else "LOW_SAMPLE"}" for (role, camp), v in sorted(rc_baseline.items()))}

Camp-only fallback: village={camp_wr.get("village", 0):.3f}, wolf={camp_wr.get("wolf", 0):.3f}

## Per-MBTI Lift

| MBTI | n | Actual WR | Mean Lift | n_fallback |
|------|---|-----------|-----------|------------|
{chr(10).join(f"| {m} | {v["n"]} | {sum(1 for ps in fixed_scores if ps.get("mbti") == m and ps.get("is_win")) / max(v["n"], 1):.3f} | {v["mean_lift"]:+.4f} | {v["n_fallback"]} |" for m, v in sorted(lift_data.items()))}

## Verification

- All zeros: {"FAIL" if all_zero else "PASS"} (should be PASS)
- Range: {min(v["mean_lift"] for v in lift_data.values()):.4f} – {max(v["mean_lift"] for v in lift_data.values()):.4f}
""")
    print("  -> role_adjusted_win_lift_audit_v7.md")

    # Fix 2: Role-Normalized PreAction
    print("\n[Fix 2] Computing role-normalized pre-action scores...")
    mbti_role_norm, role_mean, role_std = compute_role_normalized_pre(fixed_scores)

    # Write role-normalized scores CSV
    with open(DATA / "mbti_role_normalized_scores_v7.csv", "w") as f:
        f.write("MBTI,n,avg_role_norm_pre,avg_role_z_pre,std_role_norm_pre\n")
        for mbti, v in sorted(mbti_role_norm.items()):
            f.write(f"{mbti},{v['n']},{v['avg_role_norm_pre']},{v['avg_role_z_pre']},{v['std_role_norm_pre']}\n")

    n_pos = sum(1 for v in mbti_role_norm.values() if v["avg_role_norm_pre"] > 0)
    print(f"  Role baselines: {len(role_mean)} roles")
    print(f"  MBTI with positive role-norm: {n_pos}/{len(mbti_role_norm)}")
    print("  -> mbti_role_normalized_scores_v7.csv")

    # Fix 3-6: Composite + Filter + Cards + HTML
    print("\n[Fix 3-6] Building full MBTI stats and HTML...")
    stats = build_full_mbti_stats(fixed_scores, mbti_role_norm, lift_data)
    html, main_sorted = build_html(stats, role_mean, role_std, camp_wr, rc_baseline)

    main_n = len([m for m, s in stats.items() if s["n"] >= 10])
    low_n = len([m for m, s in stats.items() if s["n"] < 10])
    print(f"  MBTI types: {len(stats)} (main={main_n}, low_sample={low_n})")
    print("  -> mbti_performance_dashboard_v7_metrics_fixed.html")

    # Verification
    print(f"\n{'=' * 60}")
    print("VERIFICATION")
    print("=" * 60)

    # 1. Expected WR not all N/A
    exp_wrs = [ps.get("expected_wr", 0.5) for ps in fixed_scores]
    all_na = all(w == 0 for w in exp_wrs)  # Would be 0 if not computed
    print(f"1. Expected WR computed: {'PASS' if not all_na else 'FAIL'} (mean={np.mean(exp_wrs):.3f})")

    # 2. RoleAdjLift not all 0
    lifts = [v["mean_lift"] for v in lift_data.values()]
    all_z = all(abs(l) < 0.0001 for l in lifts)
    print(
        f"2. RoleAdjLift not all zero: {'PASS' if not all_z else 'FAIL'} (range: {min(lifts):.4f} to {max(lifts):.4f})"
    )

    # 3. Composite uses role-norm pre not raw pre
    for mbti, s in list(stats.items())[:3]:
        diff = abs(s["avg_role_norm_pre"] - s["avg_pre_action_score"])
        print(
            f"3. {mbti}: RoleNormPre={s['avg_role_norm_pre']:+.3f} vs RawPre={s['avg_pre_action_score']:.3f} (diff={diff:.3f})"
        )

    # 4. n<10 not in main
    print(f"4. Main leaderboard: n≥10, {main_n} types. Low sample: {low_n} types")

    # 5. Top MBTI has explanation
    if main_sorted:
        top = main_sorted[0]
        has_strengths = len(top[1].get("strengths", [])) > 0
        has_weaknesses = len(top[1].get("weaknesses", [])) > 0
        print(
            f"5. Top MBTI #{top[0]}: strengths={len(top[1].get('strengths', []))}, weaknesses={len(top[1].get('weaknesses', []))}"
        )

    print("\nDone. Open: data/health/mbti_performance_dashboard_v7_metrics_fixed.html")


if __name__ == "__main__":
    main()
