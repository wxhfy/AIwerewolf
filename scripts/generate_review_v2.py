"""Tasks 6+7: Generate review v2 + Valid Agent v2.

Integrates all diagnostic findings:
  - Guard v2 scoring (protect_policy + target_risk + key_coverage + block_bonus - abuse_penalty)
  - Hunter low-confidence annotation (18 shots < 30 threshold)
  - SpeechScore + CounterfactualImpact
  - Valid Agent re-check

Run: python scripts/generate_review_v2.py [--game-id ID] [--all]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.train_and_ablate import load_opportunities
from scripts.train_and_ablate import rule_decision_quality
from scripts.train_and_ablate import rule_opportunity_value


def load_json(path: str) -> Any:
    with open(ROOT / path, encoding="utf-8") as f:
        return json.load(f)


def guard_score_v2(opp) -> float:
    """Guard v2: protect_policy + target_risk + key_coverage + block_bonus - abuse_penalty."""
    tf = opp.get("target_features", {})
    opp.get("game_features", {})
    outcome = opp.get("outcome_features", {})

    target_role = tf.get("target_role", "Villager")
    role_value = {"Seer": 1.0, "Witch": 0.9, "Guard": 0.5, "Hunter": 0.7, "Villager": 0.3, "Werewolf": 0.0}
    protect_policy = role_value.get(target_role, 0.3)

    kill_likelihood = float(tf.get("target_kill_likelihood", 0.3))
    target_risk = kill_likelihood

    is_key_exposed = tf.get("is_key_role_exposed", False) or tf.get("is_target_confirmed_good", False)
    key_coverage = 1.0 if is_key_exposed else 0.3

    actual_block = tf.get("actual_block", False) or outcome.get("target_died_same_phase", False)
    block_bonus = 0.10 if actual_block else 0.0

    is_self = tf.get("guarded_self", False)
    is_repeat = tf.get("is_repeat_guard", False)
    abuse_penalty = 0.15 if is_self else 0.05 if is_repeat else 0.0

    return max(
        0.0, min(1.0, 0.35 * protect_policy + 0.25 * target_risk + 0.25 * key_coverage + block_bonus - abuse_penalty)
    )


def hunter_shot_quality(opp) -> tuple[float, float]:
    """Hunter shot quality score + confidence."""
    tf = opp.get("target_features", {})
    is_wolf = tf.get("target_alignment") == "wolf"
    is_good = tf.get("target_alignment") == "village"
    if is_wolf:
        return 0.95, 0.90
    elif is_good:
        return 0.10, 0.85
    else:
        return 0.25, 0.40  # unknown target


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    print("Loading data...")
    opps = load_opportunities()
    speech_data = load_json("data/health/speech_scores.json")
    cf_data = load_json("data/health/counterfactual_impacts.json")
    load_json("data/health/baseline_scoring_report.json")

    from sqlalchemy import text

    from backend.db.database import SessionLocal
    from backend.db.database import init_db

    init_db()
    db = SessionLocal()
    clean_ids = set(json.loads(Path("/tmp/clean_llm_game_ids.json").read_text()))
    games = db.execute(text("SELECT id, winner FROM games WHERE id IN :ids"), {"ids": tuple(clean_ids)}).fetchall()
    winner_map = {g[0]: g[1] for g in games}
    db.close()

    # Per-player maps
    opp_player = {}
    for o in opps:
        parts = o["opportunity_id"].split("-")
        pid = parts[2] if len(parts) > 2 else "unknown"
        opp_player[o["opportunity_id"]] = pid
    {o["opportunity_id"]: o["game_id"] for o in opps}

    # Speech per player
    player_speech = {s["player_id"]: s for s in speech_data}
    # CF per player
    player_cf = defaultdict(list)
    for cf in cf_data:
        player_cf[cf["player_id"]].append(cf)

    # Aggregate by (game_id, player_id)
    by_player = defaultdict(list)
    for o in opps:
        gid = o["game_id"]
        pid = opp_player.get(o["opportunity_id"], "unknown")
        by_player[(gid, pid)].append(o)

    reviews = []
    for (gid, pid), player_opps in by_player.items():
        role = player_opps[0]["role"]
        winner = winner_map.get(gid, "")
        won = (winner == "wolf" and role == "Werewolf") or (winner == "village" and role != "Werewolf")

        # Compute opportunity scores
        opp_scores = []
        for o in player_opps:
            op_type = o["opportunity_type"]

            if role == "Guard" and op_type == "guard_protect":
                q = guard_score_v2(o)
                w = rule_opportunity_value(o)
            elif role == "Hunter" and op_type == "hunter_shot":
                q, shot_conf = hunter_shot_quality(o)
                w = rule_opportunity_value(o)
            else:
                w = rule_opportunity_value(o)
                q = rule_decision_quality(o)

            opp_scores.append(
                {
                    "opportunity_id": o["opportunity_id"],
                    "type": op_type,
                    "day": o["day"],
                    "w": round(w, 3),
                    "q": round(q, 3),
                    "score": round(w * q, 3),
                }
            )

        opp_scores.sort(key=lambda x: -x["score"])
        top3_good = opp_scores[:3]
        top3_bad = opp_scores[-3:][::-1]
        n_opps = len(opp_scores)

        # RoleProcessScore
        valid = [s for s in opp_scores if s["w"] > 0]
        total_w = sum(s["w"] for s in valid)
        raw_process = sum(s["w"] * s["q"] for s in valid) / max(total_w, 0.01)
        k, mu = 2.0, 0.5
        alpha = total_w / (total_w + k)
        adjusted_process = alpha * raw_process + (1 - alpha) * mu

        # SpeechScore
        speech = player_speech.get(pid, {})
        speech_score = speech.get("avg_speech_quality", 50) / 100.0

        # CF impact
        cf_pid = player_cf.get(pid, [])
        cf_total = sum(c.get("impact_value", 0) for c in cf_pid)
        cf_impact = max(-1.0, min(1.0, cf_total / max(len(cf_pid), 1)))

        # Mistake penalty
        bad_count = sum(1 for s in opp_scores if s["q"] < 0.3)
        mistake_penalty = min(0.5, bad_count * 0.05)

        # Robustness
        robustness = 1.0

        # ProcessScore
        process_score = (
            0.40 * adjusted_process
            + 0.20 * speech_score
            + 0.15 * cf_impact
            + 0.15 * (1.0 - mistake_penalty)
            + 0.10 * robustness
        )
        final_score = 0.85 * process_score

        # Model confidence
        model_conf = round(min(alpha, 0.9), 2)
        if role == "Hunter":
            model_conf = min(model_conf, 0.50)  # low confidence marker
        if role == "Guard":
            model_conf = min(model_conf, 0.65)  # moderate confidence

        # Key counterfactuals
        key_cfs = [c for c in cf_pid if abs(c.get("impact_value", 0)) > 0.3][:3]

        # Role advice
        advice = []
        if role == "Guard":
            advice.append("Guard v2: protect_policy + target_risk + key_coverage 评分")
            if any(s["type"] == "guard_protect" and s["q"] < 0.3 for s in opp_scores):
                advice.append("守护策略需优化：优先已暴露的高价值神职")
        if role == "Hunter":
            advice.append("Hunter confidence: LOW (18 shots across 56 games)")
            advice.append("无需追 shot d>=0.5；等更多对局数据")
        if role == "Witch":
            poison_bad = [s for s in opp_scores if s["type"] == "witch_poison" and s["q"] < 0.3]
            if poison_bad:
                advice.append("毒药使用需更多公开证据支持")
        if process_score < 0.4:
            advice.append("整体决策质量偏低，参考策略库高质量案例")
        if speech_score < 0.4:
            advice.append("发言可提升：加强立场明确度和事件引用")
        if not advice:
            advice.append("表现稳定")

        reviews.append(
            {
                "game_id": gid,
                "player_id": pid,
                "role": role,
                "won": won,
                "final_score": round(final_score * 100, 1),
                "process_score": round(process_score * 100, 1),
                "role_process_score": round(adjusted_process * 100, 1),
                "speech_score": round(speech_score * 100, 1),
                "counterfactual_impact": round(cf_impact, 3),
                "mistake_penalty": round(mistake_penalty, 3),
                "n_opportunities": n_opps,
                "total_weight": round(total_w, 2),
                "model_confidence": model_conf,
                "top3_good": [{"type": s["type"], "day": s["day"], "score": s["score"]} for s in top3_good],
                "top3_bad": [{"type": s["type"], "day": s["day"], "score": s["score"]} for s in top3_bad],
                "key_counterfactuals": [
                    {"type": c.get("type", ""), "impact": c.get("impact_value", 0)} for c in key_cfs
                ],
                "advice": advice,
                "speech_detail": {
                    "n_speeches": speech.get("n_speeches", 0),
                    "groundedness": speech.get("avg_groundedness", 0),
                    "stance_clarity": speech.get("avg_stance_clarity", 0),
                    "consistency": speech.get("avg_consistency", 0),
                    "strategic_value": speech.get("avg_strategic_value", 0),
                    "information_safety": speech.get("avg_information_safety", 0),
                },
            }
        )

    # Filter
    if args.game_id:
        reviews = [r for r in reviews if r["game_id"] == args.game_id]
    elif not args.all:
        sampled = list({r["game_id"] for r in reviews})[:3]
        reviews = [r for r in reviews if r["game_id"] in sampled]

    # Generate markdown
    lines = [
        "# AI Werewolf — Learned Evaluator Review Report v2",
        "",
        f"**Games**: {len({r['game_id'] for r in reviews})}",
        f"**Players**: {len(reviews)}",
        "",
        "## Scoring System v2",
        "- **ProcessScore** = 0.40×RoleProcessScore + 0.20×SpeechScore + 0.15×CF + 0.15×(1−Penalty) + 0.10×Robustness",
        "- **Guard v2**: protect_policy + target_risk + key_coverage + block_bonus − abuse_penalty (NOT outcome-driven)",
        "- **Hunter**: low-confidence annotation (18 shots < 30 threshold)",
        "",
        "## Known Issues",
        "- Guard d=0.203 (target >=0.3): protect_policy v2 improves over v1 but needs more data",
        "- Hunter d=0.349 (target >=0.5): LOW CONFIDENCE, 18 shots insufficient",
        "- Embedding retrieval: +0.007 paw gain, need hard type filter + fine-tuning",
        "",
        "---",
    ]

    for r in reviews:
        conf_note = ""
        if r["role"] == "Hunter" and r["model_confidence"] <= 0.5:
            conf_note = " ⚠ LOW CONFIDENCE"
        elif r["role"] == "Guard":
            conf_note = " (v2 protect scoring)"

        lines += [
            f"## {r['role']} — {r['player_id'][:12]}{conf_note}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| FinalScore | **{r['final_score']:.1f}** |",
            f"| ProcessScore | {r['process_score']:.1f} |",
            f"| RoleProcessScore | {r['role_process_score']:.1f} |",
            f"| SpeechScore | {r['speech_score']:.1f} |",
            f"| CounterfactualImpact | {r['counterfactual_impact']:+.3f} |",
            f"| MistakePenalty | {r['mistake_penalty']:.3f} |",
            f"| Opportunities | {r['n_opportunities']} (w={r['total_weight']:.1f}) |",
            f"| Model Confidence | {r['model_confidence']:.2f} |",
            f"| Won | {'✓' if r['won'] else '✗'} |",
            "",
            "### Top 3 Good Opportunities",
        ]
        for i, opp in enumerate(r["top3_good"]):
            lines.append(f"{i + 1}. [{opp['type']}] D{opp['day']} — q={opp['score']:.3f}")

        lines += ["", "### Top 3 Bad Opportunities"]
        for i, opp in enumerate(r["top3_bad"]):
            lines.append(f"{i + 1}. [{opp['type']}] D{opp['day']} — q={opp['score']:.3f}")

        if r["key_counterfactuals"]:
            lines += ["", "### Key Counterfactuals"]
            for cf in r["key_counterfactuals"]:
                lines.append(f"- [{cf['type']}] impact={cf['impact']:+.3f}")

        lines += ["", "### Role-Specific Advice"]
        for adv in r["advice"]:
            lines.append(f"- {adv}")
        lines += ["", "---", ""]

    (ROOT / "data/health/review_with_learned_scores_v2.md").write_text("\n".join(lines))
    print("  → review_with_learned_scores_v2.md")

    with open(ROOT / "data/health/review_with_learned_scores_v2.json", "w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2)
    print("  → review_with_learned_scores_v2.json")

    # ---- Valid Agent v2 ----
    issues = []
    for r in reviews:
        if r["process_score"] > 100 or r["process_score"] < 0:
            issues.append({"player": r["player_id"], "type": "score_range"})
        if r["n_opportunities"] < 3:
            issues.append({"player": r["player_id"], "type": "low_opps"})
        if r["model_confidence"] < 0.3:
            issues.append({"player": r["player_id"], "type": "very_low_confidence"})

    # Additional v2 checks
    hunter_reviews = [r for r in reviews if r["role"] == "Hunter"]
    guard_reviews = [r for r in reviews if r["role"] == "Guard"]
    if hunter_reviews:
        avg_hunter_conf = statistics.mean(r["model_confidence"] for r in hunter_reviews)
        if avg_hunter_conf <= 0.5:
            issues.append({"type": "hunter_low_confidence", "detail": f"avg_conf={avg_hunter_conf:.2f}, shots<30"})
    if guard_reviews:
        guard_protect_scores = []
        for r in guard_reviews:
            for o in r.get("top3_good", []):
                if o["type"] == "guard_protect":
                    guard_protect_scores.append(o["score"])
        if guard_protect_scores and statistics.mean(guard_protect_scores) < 0.5:
            issues.append({"type": "guard_protect_low_quality", "detail": "mean_protect_score<0.5"})

    passed = len([i for i in issues if i["type"] in ("score_range", "low_opps")]) == 0
    validation = {
        "report_id": "review-v2",
        "passed": passed,
        "grade": "A" if passed and len(issues) <= 2 else "B",
        "score": 1.0 if passed else 0.7,
        "issues": issues,
        "publish_allowed": passed,
        "recommendations": [
            "Guard v2 scoring applied: actual_block is BONUS only",
            f"Hunter LOW CONFIDENCE: {len(hunter_reviews)} players, {18} shots total",
            "Embedding retrieval: hard type filter recommended",
            f"Found {len(issues)} non-blocking issues",
        ]
        if passed
        else [f"Found {len(issues)} issues to fix"],
    }

    with open(ROOT / "data/health/validation_result_v2.json", "w", encoding="utf-8") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)
    print("  → validation_result_v2.json")
    print(f"\nValid Agent v2: passed={validation['passed']}, grade={validation['grade']}, issues={len(issues)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
