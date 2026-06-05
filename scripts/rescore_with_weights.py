"""Re-score existing experiment JSONs with new weight configuration.

Reads ``data/experiment/role_*_*_seed_*.json``, recomputes
``adjusted_final_score`` using alternative scoring weights, and writes
a new ``discrimination_summary.json`` so the dashboard and Phase G
verdict reflect the updated formula.

This is Phase E Iteration 2: test different weights WITHOUT re-running
LLM games (saves ~$50 API cost and ~5 hours wall-clock).

Default new weights (iter2):
  camp 0.25→0.10, role_task 0.25→0.40, vote 0.20, speech 0.10,
  skill 0.10, survival 0.10, mistake unchanged

Usage:
    python scripts/rescore_with_weights.py
    python scripts/rescore_with_weights.py --w-camp 0.15 --w-role-task 0.35
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPERIMENT_DIR = ROOT / "data" / "experiment"
SUMMARY_PATH = EXPERIMENT_DIR / "discrimination_summary.json"

from scripts.analyze_score_distributions import cohens_d
from scripts.analyze_score_distributions import stat_block
from scripts.analyze_score_distributions import welch_t_p


@dataclass
class Weights:
    w_camp: float = 0.10
    w_role_task: float = 0.40
    w_vote: float = 0.20
    w_speech: float = 0.10
    w_skill: float = 0.10
    w_survival: float = 0.10

    def validate(self) -> bool:
        total = self.w_camp + self.w_role_task + self.w_vote + self.w_speech + self.w_skill + self.w_survival
        return abs(total - 1.0) < 0.001

    def label(self) -> str:
        return (
            f"camp{self.w_camp:.2f}_rt{self.w_role_task:.2f}"
            f"_vote{self.w_vote:.2f}_sp{self.w_speech:.2f}"
            f"_sk{self.w_skill:.2f}_sv{self.w_survival:.2f}"
        )


def rescore(scores: dict[str, float], w: Weights) -> float:
    """Recompute adjusted_final_score = clamp(base_total) * 100."""
    base = (
        w.w_camp * scores.get("camp_result_score", 0)
        + w.w_role_task * scores.get("role_task_score", 0)
        + w.w_vote * scores.get("vote_score", 0)
        + w.w_speech * scores.get("speech_score", 0)
        + w.w_skill * scores.get("skill_score", 0)
        + w.w_survival * scores.get("survival_score", 0)
        - scores.get("mistake_penalty", 0)
    )
    clamped = max(0.0, min(1.0, base))
    return round(clamped * 100, 2)


def collect_rescored(w: Weights) -> dict[str, dict[str, list[dict]]]:
    """role -> variant -> [{seed, original_final, new_final, role_task, ...}]"""
    out: dict[str, dict[str, list[dict]]] = {}
    for path in sorted(EXPERIMENT_DIR.glob("role_*_*_seed_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("experiment_meta") or {}
        role = meta.get("role")
        variant = meta.get("variant")
        seed = meta.get("seed")
        if not role or not variant:
            continue
        if not payload.get("publish_allowed"):
            continue
        player_scores = payload.get("target_role_player_scores", [])
        if not player_scores:
            continue
        s = player_scores[0]
        new_final = rescore(s, w)
        out.setdefault(role, {}).setdefault(variant, []).append(
            {
                "seed": seed,
                "original_final": s.get("adjusted_final_score"),
                "new_final": new_final,
                "role_task": s.get("role_task_score"),
                "camp": s.get("camp_result_score"),
                "mistake": s.get("mistake_penalty"),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w-camp", type=float, default=0.10)
    ap.add_argument("--w-role-task", type=float, default=0.40)
    ap.add_argument("--w-vote", type=float, default=0.20)
    ap.add_argument("--w-speech", type=float, default=0.10)
    ap.add_argument("--w-skill", type=float, default=0.10)
    ap.add_argument("--w-survival", type=float, default=0.10)
    args = ap.parse_args()

    w = Weights(
        w_camp=args.w_camp,
        w_role_task=args.w_role_task,
        w_vote=args.w_vote,
        w_speech=args.w_speech,
        w_skill=args.w_skill,
        w_survival=args.w_survival,
    )
    if not w.validate():
        print(f"ERROR: weights don't sum to 1.0: {w.label()}")
        return 1


    data = collect_rescored(w)

    # Read old summary for comparison
    old_d_map = {}
    old_summary_path = EXPERIMENT_DIR / "discrimination_summary.json"
    if old_summary_path.exists():
        try:
            old_payload = json.loads(old_summary_path.read_text(encoding="utf-8"))
            for entry in old_payload.get("per_role", []):
                old_d_map[entry["role"]] = entry.get("cohens_d_adjusted_final_score", float("nan"))
        except Exception:
            pass

    print(f"=== Re-scored with {w.label()} ===")
    print(
        f"{'role':<10} {'g_n':>5} {'b_n':>5} {'g_new':>10} {'b_new':>10} "
        f"{'g_old':>10} {'b_old':>10} {'d_new':>8} {'d_old':>8} {'p_new':>8} {'verdict':<24}"
    )
    print("-" * 144)

    per_role = []
    for role in sorted(data.keys()):
        records = data[role]
        g_new = [r["new_final"] for r in records.get("good", [])]
        b_new = [r["new_final"] for r in records.get("bad", [])]
        g_old = [r["original_final"] for r in records.get("good", [])]
        b_old = [r["original_final"] for r in records.get("bad", [])]

        d_new = cohens_d(g_new, b_new)
        p_new = welch_t_p(g_new, b_new)
        g_mean_new = statistics.mean(g_new) if g_new else 0
        b_mean_new = statistics.mean(b_new) if b_new else 0
        g_mean_old = statistics.mean(g_old) if g_old else 0
        b_mean_old = statistics.mean(b_old) if b_old else 0

        abs_d = abs(d_new) if not math.isnan(d_new) and not math.isinf(d_new) else 0.0
        discriminates = abs_d >= 0.8 and (math.isnan(p_new) or p_new < 0.05) and g_mean_new > b_mean_new
        verdict = "DISCRIMINATES" if discriminates else "FAILS_DISCRIMINATION"

        d_str_new = f"{d_new:+.3f}" if not math.isnan(d_new) else "—"
        p_str_new = f"{p_new:.4f}" if not math.isnan(p_new) else "—"
        d_old = old_d_map.get(role, float("nan"))
        d_str_old = f"{d_old:+.3f}" if not math.isnan(d_old) else "—"

        print(
            f"{role:<10} {len(g_new):>6} {len(b_new):>6} "
            f"{g_mean_new:>10.2f} {b_mean_new:>10.2f} "
            f"{g_mean_old:>10.2f} {b_mean_old:>10.2f} "
            f"{d_str_new:>8} {d_str_old:>8} {p_str_new:>8} {verdict:<24}"
        )

        per_role.append(
            {
                "role": role,
                "good": {"adjusted_final_score": stat_block(g_new), "n": len(g_new)},
                "bad": {"adjusted_final_score": stat_block(b_new), "n": len(b_new)},
                "cohens_d_adjusted_final_score": d_new,
                "welch_t_p_adjusted_final_score": p_new,
                "verdict": verdict,
            }
        )

    print()
    discriminating = sum(1 for e in per_role if e["verdict"] == "DISCRIMINATES")
    overall = discriminating >= 4
    print(f"Discriminating: {discriminating}/{len(per_role)} → OVERALL {'PASS' if overall else 'FAIL'}")

    payload = {
        "weight_config": w.label(),
        "threshold_d": 0.8,
        "threshold_roles": 4,
        "discriminating_count": discriminating,
        "total_roles": len(per_role),
        "overall_pass": overall,
        "per_role": per_role,
        "_note": "Re-scored with alternative weights; original data unchanged",
    }
    SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {SUMMARY_PATH}")
    return 0 if overall else 2


if __name__ == "__main__":
    raise SystemExit(main())
