"""Statistical analysis of B-score distributions from the
score_discrimination_experiment harness.

Reads ``data/experiment/role_*_*_seed_*.json`` and for each (role) computes:
  - mean ± SD of ``target_role_avg_adjusted_final_score`` for good vs bad
  - mean ± SD of ``target_role_avg_role_task_score`` for good vs bad
  - mean of total mistakes per game for good vs bad
  - Cohen's d (effect size) and Welch's t-test approximation

Pass criteria (Phase G):
  - At least 4 of 5 roles must have d ≥ 0.8 AND p < 0.05 on adjusted_final_score
  - good arm must have lower mistake count than bad arm

Writes ``data/experiment/discrimination_summary.json`` aggregating per-role
statistics for the dashboard endpoint to consume.

Usage:
    python scripts/analyze_score_distributions.py
    python scripts/analyze_score_distributions.py --roles Seer Witch
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_DIR = ROOT / "data" / "experiment"
SUMMARY_PATH = EXPERIMENT_DIR / "discrimination_summary.json"


def cohens_d(a: list[float], b: list[float]) -> float:
    """Compute Cohen's d (pooled standard deviation)."""
    if not a or not b:
        return float("nan")
    if len(a) == 1 and len(b) == 1:
        return float("nan")
    mean_a = statistics.mean(a)
    mean_b = statistics.mean(b)
    var_a = statistics.variance(a) if len(a) > 1 else 0.0
    var_b = statistics.variance(b) if len(b) > 1 else 0.0
    pooled = math.sqrt((var_a + var_b) / 2) if (var_a + var_b) > 0 else 0.0
    if pooled == 0:
        return float("inf") if mean_a != mean_b else 0.0
    return (mean_a - mean_b) / pooled


def welch_t_p(a: list[float], b: list[float]) -> float:
    """Welch's t-test two-tailed p, normal-approx (no scipy)."""
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    mean_a = statistics.mean(a)
    mean_b = statistics.mean(b)
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    se = math.sqrt(var_a / len(a) + var_b / len(b))
    if se == 0:
        return 0.0 if mean_a != mean_b else 1.0
    t = (mean_a - mean_b) / se
    # Normal approx for tail (good enough for n>=5)
    # P(|Z| > |t|) = 2 * (1 - Phi(|t|))
    z = abs(t)
    # Use erf-based normal CDF
    phi = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return float(2 * (1 - phi))


def stat_block(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "sd": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def collect_results(role_filter: list[str] | None = None) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """role -> variant -> [game records]"""
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for path in sorted(EXPERIMENT_DIR.glob("role_*_*_seed_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("experiment_meta") or {}
        role = meta.get("role")
        variant = meta.get("variant")
        if not role or not variant:
            continue
        if role_filter and role not in role_filter:
            continue
        if not payload.get("publish_allowed"):
            # Skip non-publishable games to keep the comparison clean
            continue
        out.setdefault(role, {}).setdefault(variant, []).append(payload)
    return out


def analyze_role(role: str, records_by_variant: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    good_records = records_by_variant.get("good", [])
    bad_records = records_by_variant.get("bad", [])

    def _avgs(records, key):
        return [r[key] for r in records if r.get(key) is not None]

    g_final = _avgs(good_records, "target_role_avg_adjusted_final_score")
    b_final = _avgs(bad_records, "target_role_avg_adjusted_final_score")
    g_task = _avgs(good_records, "target_role_avg_role_task_score")
    b_task = _avgs(bad_records, "target_role_avg_role_task_score")
    g_mist = [r.get("target_role_total_mistakes", 0) for r in good_records]
    b_mist = [r.get("target_role_total_mistakes", 0) for r in bad_records]

    d_final = cohens_d(g_final, b_final)
    p_final = welch_t_p(g_final, b_final)
    d_task = cohens_d(g_task, b_task)
    p_task = welch_t_p(g_task, b_task)

    abs_d_final = abs(d_final) if not math.isnan(d_final) and not math.isinf(d_final) else (float("inf") if math.isinf(d_final) else 0.0)
    discriminates = (
        abs_d_final >= 0.8
        and (math.isnan(p_final) or p_final < 0.05)
        and (statistics.mean(g_final) if g_final else 0) > (statistics.mean(b_final) if b_final else 0)
    )

    return {
        "role": role,
        "good": {
            "adjusted_final_score": stat_block(g_final),
            "role_task_score": stat_block(g_task),
            "mistakes_per_game": stat_block([float(x) for x in g_mist]),
        },
        "bad": {
            "adjusted_final_score": stat_block(b_final),
            "role_task_score": stat_block(b_task),
            "mistakes_per_game": stat_block([float(x) for x in b_mist]),
        },
        "cohens_d_adjusted_final_score": d_final,
        "welch_t_p_adjusted_final_score": p_final,
        "cohens_d_role_task_score": d_task,
        "welch_t_p_role_task_score": p_task,
        "verdict": (
            "DISCRIMINATES" if discriminates
            else "INCONCLUSIVE" if (len(g_final) < 2 or len(b_final) < 2)
            else "FAILS_DISCRIMINATION"
        ),
    }


def render_table(per_role: list[dict[str, Any]]) -> None:
    print()
    print(f"{'role':<10} {'good_n':>6} {'bad_n':>6} {'good_avg':>10} {'bad_avg':>10} {'d_final':>9} {'p_final':>9} {'verdict':<24}")
    print("-" * 96)
    for entry in per_role:
        g_n = entry["good"]["adjusted_final_score"]["n"]
        b_n = entry["bad"]["adjusted_final_score"]["n"]
        g_mean = entry["good"]["adjusted_final_score"]["mean"]
        b_mean = entry["bad"]["adjusted_final_score"]["mean"]
        d = entry["cohens_d_adjusted_final_score"]
        p = entry["welch_t_p_adjusted_final_score"]
        g_str = f"{g_mean:.2f}" if g_mean is not None else "—"
        b_str = f"{b_mean:.2f}" if b_mean is not None else "—"
        d_str = f"{d:+.3f}" if not math.isnan(d) and not math.isinf(d) else ("+inf" if math.isinf(d) and d > 0 else "—")
        p_str = f"{p:.4f}" if not math.isnan(p) else "—"
        print(f"{entry['role']:<10} {g_n:>6} {b_n:>6} {g_str:>10} {b_str:>10} {d_str:>9} {p_str:>9} {entry['verdict']:<24}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", nargs="+", default=None, help="Filter to specific roles (default: all)")
    ap.add_argument("--threshold-d", type=float, default=0.8, help="Cohen's d acceptance threshold")
    ap.add_argument("--threshold-roles", type=int, default=4, help="Min roles passing threshold to overall PASS")
    args = ap.parse_args()

    results = collect_results(role_filter=args.roles)
    if not results:
        print("No experiment results found (data/experiment/role_*_*_seed_*.json empty)")
        return 1

    per_role = [analyze_role(role, records) for role, records in sorted(results.items())]
    render_table(per_role)

    discriminating_count = sum(1 for entry in per_role if entry["verdict"] == "DISCRIMINATES")
    overall_pass = discriminating_count >= args.threshold_roles
    print(f"Roles discriminating (d≥{args.threshold_d}, p<0.05): "
          f"{discriminating_count}/{len(per_role)}  →  "
          f"OVERALL {'PASS' if overall_pass else 'FAIL'}")

    payload = {
        "threshold_d": args.threshold_d,
        "threshold_roles": args.threshold_roles,
        "discriminating_count": discriminating_count,
        "total_roles": len(per_role),
        "overall_pass": overall_pass,
        "per_role": per_role,
    }
    SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {SUMMARY_PATH}")
    return 0 if overall_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
