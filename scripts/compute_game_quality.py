"""Game Quality Scorer — per-game 100-point quality assessment.

Evaluates each experiment JSON on 6 dimensions, independent of win/loss.
Outputs aggregate summary + per-game breakdown + quality tier classification.

Usage:
    python scripts/compute_game_quality.py
    python scripts/compute_game_quality.py --output data/experiment/quality_report.json
    python scripts/compute_game_quality.py --role Seer
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from statistics import median
from statistics import stdev
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = ROOT / "data" / "experiment"

# ---------------------------------------------------------------------------
# Dimension definitions (sum = 100)
# ---------------------------------------------------------------------------
DIMENSIONS = {
    "structural_integrity": {"max": 20, "label": "结构完整性"},
    "process_validity": {"max": 20, "label": "流程合法性"},
    "real_llm": {"max": 15, "label": "真实 LLM 运行"},
    "gameplay_richness": {"max": 20, "label": "博弈丰富度"},
    "behavior_reason": {"max": 15, "label": "行为合理性"},
    "evaluability": {"max": 10, "label": "可评估性"},
}

QUALITY_TIERS = [
    (90, "S", "高质量，可直接用于评估"),
    (75, "A", "可用，建议抽查"),
    (60, "B", "边缘可用，需注意"),
    (0, "C", "不建议进入统计"),
]


def score_structural_integrity(d: dict) -> tuple[float, list[str]]:
    """Check JSON completeness, field presence, game_id uniqueness handled externally."""
    score = 20.0
    notes: list[str] = []

    required_top = [
        "game_id",
        "winner",
        "days",
        "total_events",
        "total_decisions",
        "fallback_decision_count",
        "publish_allowed",
        "validation_score",
        "target_role_player_scores",
        "target_role_avg_adjusted_final_score",
    ]
    required_meta = ["role", "variant", "seed", "duration_s", "strict_no_fallback"]
    required_ps = [
        "player_id",
        "role",
        "alignment",
        "final_score",
        "adjusted_final_score",
        "camp_result_score",
        "role_task_score",
        "vote_score",
        "speech_score",
        "skill_score",
        "survival_score",
        "mistake_penalty",
        "mistakes",
    ]

    meta = d.get("experiment_meta", {})

    for k in required_top:
        if k not in d:
            score -= 2
            notes.append(f"missing top field: {k}")
    for k in required_meta:
        if k not in meta:
            score -= 1.5
            notes.append(f"missing meta field: {k}")

    pss = d.get("target_role_player_scores", [])
    if not pss:
        score -= 5
        notes.append("empty target_role_player_scores")
    for ps in pss:
        for k in required_ps:
            if k not in ps:
                score -= 1
                notes.append(f"missing player_score field: {k}")

    # Score range sanity
    for ps in pss:
        fs = ps.get("final_score")
        if fs is not None and (fs < -10 or fs > 110):
            score -= 2
            notes.append(f"final_score out of range: {fs}")

    return max(0, score), notes


def score_process_validity(d: dict) -> tuple[float, list[str]]:
    """Days / decisions / duration / winner sanity."""
    score = 20.0
    notes: list[str] = []

    days = d.get("days", 0)
    if days < 2:
        score -= 8
        notes.append(f"too few days: {days}")
    elif days < 3:
        score -= 2
        notes.append(f"short game: {days} days")
    elif days > 6:
        score -= 5
        notes.append(f"too many days: {days}")

    decisions = d.get("total_decisions", 0)
    if decisions < 16:
        score -= 8
        notes.append(f"too few decisions: {decisions}")
    elif decisions < 25:
        score -= 3
        notes.append(f"low decisions: {decisions}")
    elif decisions > 80:
        score -= 5
        notes.append(f"too many decisions: {decisions}")

    # Decisions per day should be reasonable (7-20)
    if days > 0:
        dpd = decisions / days
        if dpd < 7:
            score -= 3
            notes.append(f"low decisions/day: {dpd:.1f}")
        elif dpd > 25:
            score -= 3
            notes.append(f"high decisions/day: {dpd:.1f}")

    winner = d.get("winner")
    if winner not in ("village", "wolf"):
        score -= 5
        notes.append(f"invalid winner: {winner}")

    dur = d.get("experiment_meta", {}).get("duration_s", 0)
    if dur < 120:
        score -= 5
        notes.append(f"too fast: {dur:.0f}s")
    elif dur > 2400:
        score -= 3
        notes.append(f"too slow: {dur:.0f}s")

    return max(0, score), notes


def score_real_llm(d: dict) -> tuple[float, list[str]]:
    """Fallback-free = real LLM game."""
    score = 15.0
    notes: list[str] = []

    fb = d.get("fallback_decision_count", -1)
    if fb < 0:
        score = 0
        notes.append("missing fallback count")
    elif fb > 0:
        # Each fallback costs 5 points
        deduction = min(15, fb * 5)
        score -= deduction
        notes.append(f"{fb} fallback decisions (-{deduction})")

    llm = d.get("llm_decision_count", 0)
    total = d.get("total_decisions", 1)
    if total > 0 and llm / total < 0.9:
        score -= 5
        notes.append(f"LLM ratio low: {llm}/{total}")

    strict = d.get("experiment_meta", {}).get("strict_no_fallback", False)
    if not strict:
        score -= 3
        notes.append("strict_no_fallback=False")

    return max(0, score), notes


def score_gameplay_richness(d: dict) -> tuple[float, list[str]]:
    """Richness proxies: events, highlights, score variance, decisions/day."""
    score = 20.0
    notes: list[str] = []

    events = d.get("total_events", 0)
    if events < 60:
        score -= 6
        notes.append(f"low events: {events}")
    elif events < 90:
        score -= 2
        notes.append(f"moderate events: {events}")
    # > 120 is good

    highlights = d.get("highlight_count", 0)
    if highlights < 2:
        score -= 4
        notes.append(f"few highlights: {highlights}")
    elif highlights < 4:
        score -= 1
        notes.append(f"moderate highlights: {highlights}")

    decisions = d.get("total_decisions", 0)
    days = d.get("days", 1)
    dpd = decisions / days if days else 0
    if dpd >= 14:
        pass  # rich interaction
    elif dpd >= 10:
        score -= 1
    else:
        score -= 3
        notes.append(f"low interaction density: {dpd:.1f} decisions/day")

    # Score dimension diversity: how many dimensions show non-trivial values
    pss = d.get("target_role_player_scores", [])
    if pss:
        dim_active = 0
        for dim in ["vote_score", "speech_score", "skill_score"]:
            vals = [ps.get(dim, 0) for ps in pss]
            if vals and mean(vals) > 0.1:
                dim_active += 1
        if dim_active < 3:
            score -= 2
            notes.append(f"only {dim_active}/3 active skill dimensions")

    return max(0, score), notes


def score_behavior_reason(d: dict) -> tuple[float, list[str]]:
    """Error rate, mistake severity, highlight-to-bad-case ratio."""
    score = 15.0
    notes: list[str] = []

    bad_cases = d.get("bad_case_count", 0)
    decisions = d.get("total_decisions", 1)
    error_rate = bad_cases / decisions

    if error_rate > 0.15:
        score -= 8
        notes.append(f"high error rate: {bad_cases}/{decisions} ({error_rate:.1%})")
    elif error_rate > 0.08:
        score -= 4
        notes.append(f"elevated error rate: {bad_cases}/{decisions} ({error_rate:.1%})")
    elif error_rate > 0.03:
        score -= 1

    # Mistake severity check: critical mistakes are worse
    pss = d.get("target_role_player_scores", [])
    critical_count = 0
    for ps in pss:
        for m in ps.get("mistakes", []):
            if isinstance(m, str) and "critical" in m.lower() or isinstance(m, dict) and m.get("severity") == "critical":
                critical_count += 1

    if critical_count >= 2:
        score -= 5
        notes.append(f"{critical_count} critical mistakes")
    elif critical_count >= 1:
        score -= 2
        notes.append(f"{critical_count} critical mistake")

    # Highlight to bad_case ratio: good games have more highlights than bad cases
    highlights = d.get("highlight_count", 0)
    if highlights > 0 and (highlights >= bad_cases):
        pass  # healthy ratio
    elif bad_cases > highlights * 3:
        score -= 3
        notes.append(f"bad_case ({bad_cases}) >> highlights ({highlights})")

    # Check if target player has extremely low scores across the board (possible bug)
    for ps in pss:
        dims = [ps.get("speech_score", 0), ps.get("vote_score", 0)]
        if dims and all(v == 0 for v in dims):
            score -= 3
            notes.append("player has all-zero skill dimensions")

    return max(0, score), notes


def score_evaluability(d: dict) -> tuple[float, list[str]]:
    """Can this game be meaningfully evaluated?"""
    score = 10.0
    notes: list[str] = []

    if not d.get("publish_allowed"):
        score -= 5
        notes.append("publish_allowed=False")

    vs = d.get("validation_score", 0)
    if vs < 0.8:
        score -= 3
        notes.append(f"low validation_score: {vs}")
    elif vs < 0.95:
        score -= 1

    if d.get("review_status") not in ("approved",):
        score -= 2
        notes.append(f"review_status={d.get('review_status')}")

    pss = d.get("target_role_player_scores", [])
    if len(pss) == 0:
        score -= 5
        notes.append("no target player scores to evaluate")

    # target_role_avg should be computable
    avg = d.get("target_role_avg_adjusted_final_score")
    if avg is None:
        score -= 2
        notes.append("missing target_role_avg_adjusted_final_score")

    return max(0, score), notes


def compute_quality(d: dict) -> dict[str, Any]:
    """Compute full quality score for one game."""
    scorers = {
        "structural_integrity": score_structural_integrity,
        "process_validity": score_process_validity,
        "real_llm": score_real_llm,
        "gameplay_richness": score_gameplay_richness,
        "behavior_reason": score_behavior_reason,
        "evaluability": score_evaluability,
    }

    dims = {}
    all_notes = []
    total = 0.0
    for key, fn in scorers.items():
        s, notes = fn(d)
        dims[key] = {"score": round(s, 1), "max": DIMENSIONS[key]["max"], "notes": notes}
        all_notes.extend(notes)
        total += s

    total = round(min(100, total), 1)

    # Determine tier
    tier = "C"
    tier_label = "不建议进入统计"
    for threshold, t, label in QUALITY_TIERS:
        if total >= threshold:
            tier = t
            tier_label = label
            break

    meta = d.get("experiment_meta", {})
    return {
        "game_id": d.get("game_id", ""),
        "role": meta.get("role", "?"),
        "variant": meta.get("variant", "?"),
        "seed": meta.get("seed", "?"),
        "winner": d.get("winner", "?"),
        "days": d.get("days", 0),
        "total_score": total,
        "tier": tier,
        "tier_label": tier_label,
        "dimensions": dims,
        "notes": all_notes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", default=None, help="Filter by role")
    ap.add_argument("--variant", default=None, help="Filter by variant (good/bad)")
    ap.add_argument("--output", default=None, help="Write JSON report to path")
    ap.add_argument("--min-tier", default="C", help="Only show games at or below this tier")
    args = ap.parse_args()

    files = sorted(EXP_DIR.glob("role_*.json"))
    if not files:
        print("No experiment JSONs found.")
        return

    results = []
    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue

        meta = d.get("experiment_meta", {})
        role = meta.get("role", "?")
        variant = meta.get("variant", "?")

        if args.role and role != args.role:
            continue
        if args.variant and variant != args.variant:
            continue

        q = compute_quality(d)
        q["file"] = f.name
        results.append(q)

    if not results:
        print("No matching games.")
        return

    # Sort by quality score descending
    results.sort(key=lambda r: r["total_score"], reverse=True)

    # -------------------------------------------------------------------
    # Print report
    # -------------------------------------------------------------------
    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
    tier_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for r in results:
        tier_counts[r["tier"]] += 1

    scores = [r["total_score"] for r in results]

    print("=" * 80)
    print("对局质量评分报告")
    print("=" * 80)
    print(f"  评估局数: {len(results)}")
    print(f"  总均分: {mean(scores):.1f}  |  中位: {median(scores):.1f}  |  SD: {stdev(scores):.1f}")
    print(f"  范围: [{min(scores):.1f}, {max(scores):.1f}]")
    print()
    print("  质量分布:")
    for threshold, tier_letter, desc in QUALITY_TIERS:
        count = tier_counts[tier_letter]
        bar = "█" * max(1, count)
        print(f"    {tier_letter} ({desc}): {count:3d} 局  {bar}")
    print()

    # Dimension averages
    print("  各维度平均得分:")
    dim_avgs = {}
    for dim_key, dim_info in DIMENSIONS.items():
        vals = [r["dimensions"][dim_key]["score"] for r in results]
        avg = mean(vals)
        pct = avg / dim_info["max"] * 100
        dim_avgs[dim_key] = avg
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"    {dim_info['label']:12s}  {avg:5.1f}/{dim_info['max']:2d}  {bar}  ({pct:.0f}%)")
    print()

    # Per-role per-variant breakdown
    from collections import defaultdict

    role_variant_scores = defaultdict(list)
    for r in results:
        key = (r["role"], r["variant"])
        role_variant_scores[key].append(r["total_score"])

    print("  按角色+变体 质量均分:")
    for (role, variant), scs in sorted(role_variant_scores.items()):
        tier_count = defaultdict(int)
        for r in results:
            if r["role"] == role and r["variant"] == variant:
                tier_count[r["tier"]] += 1
        tier_str = " ".join(f"{t}={tier_count.get(t, 0)}" for t in ["S", "A", "B", "C"])
        print(f"    {role:10s} {variant:6s}:  mean={mean(scs):.1f}  sd={stdev(scs):.1f}  [{tier_str}]")
    print()

    # -------------------------------------------------------------------
    # Per-game listing
    # -------------------------------------------------------------------
    print("=" * 80)
    print("逐局详情")
    print("=" * 80)

    for r in results:
        tier = r["tier"]
        # Filter by min tier
        if tier_order.get(tier, 99) > tier_order.get(args.min_tier, 99):
            continue

        dim_str = " | ".join(
            f"{DIMENSIONS[k]['label']}={r['dimensions'][k]['score']:.0f}/{DIMENSIONS[k]['max']}" for k in DIMENSIONS
        )
        print(f"\n  [{tier}] {r['file']}")
        print(
            f"       role={r['role']} variant={r['variant']} seed={r['seed']}  winner={r['winner']}  days={r['days']}"
        )
        print(f"       TOTAL={r['total_score']:.1f}  |  {dim_str}")
        notes = r.get("notes", [])
        if notes:
            for note in notes[:5]:
                print(f"         ⚠ {note}")
            if len(notes) > 5:
                print(f"         ... +{len(notes) - 5} more")

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print()
    print("=" * 80)
    print(f"总结: S={tier_counts['S']} A={tier_counts['A']} B={tier_counts['B']} C={tier_counts['C']}")
    s_plus_a = tier_counts["S"] + tier_counts["A"]
    usable = s_plus_a + tier_counts["B"]
    print(f"  高质量 (S+A): {s_plus_a}/{len(results)} ({s_plus_a / len(results) * 100:.0f}%)")
    print(f"  可用   (S+A+B): {usable}/{len(results)} ({usable / len(results) * 100:.0f}%)")
    print(f"  不可用 (C): {tier_counts['C']}/{len(results)} ({tier_counts['C'] / len(results) * 100:.0f}%)")
    print("=" * 80)

    # -------------------------------------------------------------------
    # Output JSON
    # -------------------------------------------------------------------
    if args.output:
        out_path = Path(args.output)
        payload = {
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "summary": {
                "total_games": len(results),
                "mean_score": round(mean(scores), 1),
                "median_score": round(median(scores), 1),
                "sd_score": round(stdev(scores), 1),
                "min_score": round(min(scores), 1),
                "max_score": round(max(scores), 1),
                "tier_counts": tier_counts,
                "dimension_averages": {k: round(v, 1) for k, v in dim_avgs.items()},
            },
            "per_game": results,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
