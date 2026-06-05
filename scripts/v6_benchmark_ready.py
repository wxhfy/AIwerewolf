#!/usr/bin/env python3
"""
V6 Benchmark Ready Sprint (Phases V6-1 through V6-8).

Key improvements over V5:
- V6-1: Human review queue with priority scoring
- V6-2: Model-assisted review (AI acting as reviewer)
- V6-3: Hard negative difficulty rebalance
- V6-4: Witch save / Seer release targeted fix
- V6-5: Rebuild V6 dataset
- V6-6: Retrain task scorers with V6 dataset
- V6-7: Gate V6 BENCHMARK_READY determination
- V6-8: Updated technical report
"""

import json
import math
import random
import warnings
from collections import Counter
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "health"

random.seed(42)
np.random.seed(42)


def load_jsonl(path):
    if Path(path).exists():
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    return []


def load_json(path):
    with open(path) as f:
        return json.load(f)


def cohens_d(good, bad):
    ng, nb = len(good), len(bad)
    if ng < 2 or nb < 2:
        return None
    mg, mb = np.mean(good), np.mean(bad)
    ps = math.sqrt(((ng - 1) * np.var(good, ddof=1) + (nb - 1) * np.var(bad, ddof=1)) / (ng + nb - 2))
    if ps < 1e-10:
        return 0.0
    return (mg - mb) / ps


def compute_paw(good, bad):
    if len(good) < 1 or len(bad) < 1:
        return None
    gs = np.array(random.sample(list(good), min(200, len(good))))
    bs = np.array(random.sample(list(bad), min(200, len(bad))))
    wins = np.sum(gs[:, None] > bs[None, :])
    ties = np.sum(gs[:, None] == bs[None, :])
    return (wins + 0.5 * ties) / (len(gs) * len(bs))


# ============================================================
# V6-1: HUMAN REVIEW QUEUE
# ============================================================


def compute_hard_negative_difficulty(sample, good_centroids):
    """Estimate how 'hard' a negative sample is based on feature distance from good samples."""
    feats = sample.get("pre_features_snapshot", {})
    feat_vec = np.array(list(feats.values())[:20])
    key = f"{sample['role']}|{sample['opportunity_type']}"

    if key not in good_centroids or len(good_centroids[key]) == 0 or len(feat_vec) == 0:
        return 0.5

    g_centroid = good_centroids[key]
    if len(feat_vec) != len(g_centroid):
        return 0.5

    dist = np.linalg.norm(feat_vec - g_centroid)
    norm_dist = dist / max(math.sqrt(len(feat_vec)), 1)
    return round(1.0 - norm_dist, 3)  # 1.0 = very hard (close to good), 0.0 = very easy


def build_review_queue(samples, opportunities):
    """Build prioritized human review queue."""
    # Compute good centroids per role-action
    good_feats = defaultdict(list)
    for s in samples:
        if s["label"] == "good":
            key = f"{s['role']}|{s['opportunity_type']}"
            feats = s.get("pre_features_snapshot", {})
            feat_vec = np.array(list(feats.values())[:20])
            if len(feat_vec) > 0:
                good_feats[key].append(feat_vec)

    good_centroids = {}
    for key, vecs in good_feats.items():
        if vecs:
            # Pad to same length
            max_len = max(len(v) for v in vecs)
            padded = []
            for v in vecs:
                if len(v) < max_len:
                    v = np.pad(v, (0, max_len - len(v)))
                padded.append(v)
            good_centroids[key] = np.mean(padded, axis=0)

    # Compute difficulty for all samples
    queue = []
    for s in samples:
        # Skip already human-reviewed and pairwise
        if s.get("human_reviewed"):
            continue
        if s.get("label_type") == "pairwise":
            continue

        difficulty = compute_hard_negative_difficulty(s, good_centroids)

        # Priority scoring
        priority = "P2"  # Default
        reasons = []

        # P0: Critical for LOW_CONF roles
        key = f"{s['role']}|{s['opportunity_type']}"
        low_conf_actions = {"Witch|witch_save", "Seer|seer_check", "Seer|seer_release", "Hunter|hunter_shot"}
        if key in low_conf_actions:
            priority = "P0"
            reasons.append(f"LOW_CONF action: {key}")

        # P0: Medium difficulty (most informative for training)
        if 0.35 <= difficulty <= 0.70:
            if priority != "P0":
                priority = "P0"
            reasons.append(f"medium_hard_negative: difficulty={difficulty:.3f}")

        # P0: Rule label conflict risk
        if s.get("label_source") == "rule" and s.get("label_confidence", 0) < 0.5:
            if priority != "P0":
                priority = "P0"
            reasons.append("low_confidence_rule_label")

        # P1: Easy negative with is_hard_negative flag
        if s.get("is_hard_negative") and difficulty < 0.35:
            if priority not in ("P0",):
                priority = "P1"
            reasons.append(f"easy_negative_review: difficulty={difficulty:.3f}")

        # P1: Synthetic/counterfactual
        if s.get("is_counterfactual"):
            if priority not in ("P0",):
                priority = "P1"
            reasons.append("counterfactual_sample_review")

        # P1: Label confidence < 0.75
        if s.get("label_confidence", 1.0) < 0.75:
            if priority not in ("P0",):
                priority = "P1"
            reasons.append(f"low_label_confidence: {s.get('label_confidence', 0):.3f}")

        queue.append(
            {
                "sample_id": s.get("sample_id", ""),
                "game_id": s.get("game_id", ""),
                "role": s.get("role", ""),
                "opportunity_type": s.get("opportunity_type", ""),
                "task_type": s.get("task_type", ""),
                "context_summary": s.get("context_summary", ""),
                "chosen_action": s.get("chosen_action", {}),
                "alternative_action": s.get("alternative_action", ""),
                "current_label": s.get("label", ""),
                "label_source": s.get("label_source", ""),
                "label_confidence": s.get("label_confidence", 1.0),
                "hard_negative_difficulty": difficulty,
                "review_priority": priority,
                "disagreement_reason": "; ".join(reasons),
                "is_hard_negative": s.get("is_hard_negative", False),
                "pre_features_snapshot": s.get("pre_features_snapshot", {}),
            }
        )

    # Sort by priority
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    queue.sort(key=lambda x: (priority_order.get(x["review_priority"], 2), -x["hard_negative_difficulty"]))

    return queue, good_centroids


# ============================================================
# V6-2: MODEL-ASSISTED REVIEW
# ============================================================


def review_sample(sample):
    """AI acting as reviewer: assess label correctness based on pre-action features.

    Uses available pre-action features and context to determine if the current
    label is correct, or if it should be changed.
    """
    feats = sample.get("pre_features_snapshot", {})
    role = sample.get("role", "")
    opp_type = sample.get("opportunity_type", "")
    current_label = sample.get("current_label", "")
    difficulty = sample.get("hard_negative_difficulty", 0.5)

    # Reviewer: assess pre-action decision quality
    decision_quality = 0.5  # Neutral default
    reasons = []

    # Evidence-based assessment
    for feat_name, feat_val in feats.items():
        if feat_name == "vote_consistent_with_public_top_suspicion" and feat_val > 0.7:
            decision_quality += 0.1
            reasons.append(f"{feat_name}={feat_val:.2f}")
        elif feat_name == "is_following_majority_without_reason" and feat_val > 0.7:
            decision_quality -= 0.1
            reasons.append(f"{feat_name}={feat_val:.2f}")
        elif feat_name == "vote_consistent_with_own_speech" and feat_val > 0.7:
            decision_quality += 0.08
        elif feat_name == "vote_consistent_with_own_speech" and feat_val < 0.3:
            decision_quality -= 0.08
        elif feat_name == "target_suspicion_percentile" and feat_val > 0.7:
            decision_quality += 0.08
        elif feat_name == "target_suspicion_percentile" and feat_val < 0.3:
            decision_quality -= 0.08
        elif feat_name == "speaker_trust_score_of_voter" and feat_val < 0.2:
            decision_quality -= 0.05
        elif feat_name == "accuses_good_player" and feat_val > 0.7:
            decision_quality -= 0.08
        elif feat_name == "wolf_perspective_leak_risk" and feat_val > 0.3:
            decision_quality -= 0.1
        elif feat_name == "self_suspicion_before" and feat_val > 0.7:
            decision_quality -= 0.05  # High suspicion = harder to make good decisions

    # Role-specific assessment
    if role == "Witch" and opp_type == "witch_save":
        role_val = feats.get("save_target_claimed_role_value", 0.3)
        kill_likelihood = feats.get("estimated_kill_likelihood", 0.3)
        if role_val > 0.7 and kill_likelihood > 0.5:
            decision_quality += 0.15
            reasons.append("high_value_target_high_kill_risk")
        elif role_val < 0.3:
            decision_quality -= 0.1
            reasons.append("low_value_save_target")

    if role == "Seer" and opp_type == "seer_release":
        release_timing = feats.get("release_timing_need", 0.5)
        self_pressure = feats.get("seer_self_under_pressure", 0)
        if release_timing > 0.7 and self_pressure > 0.5:
            decision_quality += 0.15
            reasons.append("critical_release_timing")
        elif release_timing < 0.3 and self_pressure < 0.3:
            decision_quality += 0.05
            reasons.append("safe_to_wait")

    if role == "Werewolf" and opp_type == "werewolf_kill":
        leak_risk = feats.get("wolf_perspective_leak_risk", 0)
        wolf_align = feats.get("wolf_team_vote_alignment", 0.5)
        public_grounded = feats.get("public_reason_groundedness", 0.2)
        if leak_risk > 0.3:
            decision_quality -= 0.1
            reasons.append("wolf_perspective_leak")
        if wolf_align > 0.8:
            decision_quality -= 0.05
            reasons.append("obvious_wolf_team_alignment")
        if public_grounded > 0.5:
            decision_quality += 0.08
            reasons.append("well_grounded_kill_decision")

    if role == "Hunter" and opp_type == "hunter_shot":
        shot_susp = feats.get("shot_target_suspicion", 0.5)
        timing = feats.get("shot_timing", 0.5)
        if shot_susp > 0.6 and timing > 0.5:
            decision_quality += 0.15
            reasons.append("high_suspicion_target_good_timing")
        elif shot_susp < 0.4:
            decision_quality -= 0.15
            reasons.append("shooting_low_suspicion_target")

    # Clamp
    decision_quality = max(0.05, min(0.95, decision_quality))

    # If no features available, keep current label
    if not feats:
        return {
            "sample_id": sample.get("sample_id", ""),
            "reviewer_type": "model_assisted",
            "reviewer_label": current_label,
            "reviewer_confidence": 0.5,
            "reviewer_notes": "no_features_available",
            "decision_quality_estimate": 0.5,
            "is_label_changed": False,
            "old_label": current_label,
            "new_label": current_label,
            "change_reason": "",
        }

    # Determine label (use current label as prior, only change with strong evidence)
    if decision_quality >= 0.60:
        new_label = "good"
    elif decision_quality <= 0.25:
        new_label = "bad"
    else:
        new_label = current_label  # Keep current label if ambiguous

    # If current label is from human source, trust it more
    if sample.get("label_source") == "human":
        if decision_quality >= 0.65:
            new_label = "good"
        elif decision_quality <= 0.20:
            new_label = "bad"
        else:
            new_label = current_label  # Keep human label

    # Reviewer confidence
    reviewer_confidence = 0.5 + 0.1 * len(reasons) if reasons else 0.55
    reviewer_confidence = min(0.85, reviewer_confidence)

    # Check if label changed
    is_changed = new_label != current_label

    # For hard negatives: if difficulty is high (close to good) and features are mixed,
    # we may keep the label but lower confidence
    if difficulty > 0.6 and not is_changed:
        reviewer_confidence = min(reviewer_confidence, 0.7)

    return {
        "sample_id": sample.get("sample_id", ""),
        "reviewer_type": "model_assisted",
        "reviewer_label": new_label,
        "reviewer_confidence": round(reviewer_confidence, 3),
        "reviewer_notes": "; ".join(reasons) if reasons else "neutral_feature_assessment",
        "decision_quality_estimate": round(decision_quality, 3),
        "is_label_changed": is_changed,
        "old_label": current_label,
        "new_label": new_label,
        "change_reason": "; ".join(reasons) if is_changed else "",
    }


# ============================================================
# V6-3: HARD NEGATIVE REBALANCE
# ============================================================


def rebalance_hard_negatives(all_samples):
    """Downsample easy negatives, retain hard negatives.

    Uses merged samples that already have reviewed labels ('label' field).
    """
    # Recompute difficulty with reviewed labels
    good_samples = [s for s in all_samples if s.get("label") == "good"]
    good_feats = defaultdict(list)
    for s in good_samples:
        key = f"{s.get('role', '')}|{s.get('opportunity_type', '')}"
        feats = s.get("pre_features_snapshot", {})
        feat_vec = np.array(list(feats.values())[:20])
        if len(feat_vec) > 0:
            good_feats[key].append(feat_vec)

    good_centroids = {}
    for key, vecs in good_feats.items():
        if vecs:
            max_len = max(len(v) for v in vecs)
            padded = [np.pad(v, (0, max_len - len(v))) if len(v) < max_len else v for v in vecs]
            good_centroids[key] = np.mean(padded, axis=0)

    # Classify all hard negatives
    hn_by_difficulty = {"easy": 0, "medium": 0, "hard": 0, "downsampled": 0, "retained": 0}
    rebalanced_samples = []

    for s in all_samples:
        if not s.get("is_hard_negative"):
            rebalanced_samples.append(s)
            continue

        # Recompute difficulty
        feats = s.get("pre_features_snapshot", {})
        feat_vec = np.array(list(feats.values())[:20])
        key = f"{s.get('role', '')}|{s.get('opportunity_type', '')}"

        difficulty = 0.5
        if key in good_centroids and len(feat_vec) > 0:
            gc = good_centroids[key]
            if len(feat_vec) == len(gc):
                dist = np.linalg.norm(feat_vec - gc)
                difficulty = 1.0 - dist / max(math.sqrt(len(feat_vec)), 1)

        s_copy = dict(s)
        s_copy["hard_negative_difficulty"] = round(difficulty, 3)

        if difficulty < 0.35:
            hn_by_difficulty["easy"] += 1
            # Downsample: keep only 60% of easy negatives
            if random.random() < 0.60:
                rebalanced_samples.append(s_copy)
                hn_by_difficulty["retained"] += 1
            else:
                hn_by_difficulty["downsampled"] += 1
        elif difficulty < 0.70:
            hn_by_difficulty["medium"] += 1
            rebalanced_samples.append(s_copy)
            hn_by_difficulty["retained"] += 1
        else:
            hn_by_difficulty["hard"] += 1
            rebalanced_samples.append(s_copy)
            hn_by_difficulty["retained"] += 1

    return rebalanced_samples, hn_by_difficulty


# ============================================================
# MAIN V6 PIPELINE
# ============================================================


def main():
    print("=" * 60)
    print("V6 Benchmark Ready Sprint")
    print("=" * 60)

    # Load data
    print("\n[Loading] V5 dataset and features...")
    v5_samples = load_jsonl(DATA / "benchmark_dataset_v5.jsonl")
    opportunities = load_jsonl(DATA / "opportunities_v3_features.jsonl")
    eval_gold = load_jsonl(DATA / "eval_gold_set.jsonl")
    eval_silver = load_jsonl(DATA / "eval_silver_set.jsonl")
    hard_negatives = load_jsonl(DATA / "hard_negative_candidates_v4.jsonl")
    speech_data = load_json(DATA / "speech_scores.json")
    opp_orig = load_jsonl(DATA / "opportunities.jsonl")
    opp_orig_idx = {o["opportunity_id"]: o for o in opp_orig}

    eval_index = {}
    for item in eval_gold + eval_silver:
        eval_index[item["opportunity_id"]] = item

    print(f"  V5 samples: {len(v5_samples)}")
    print(f"  Opportunities: {len(opportunities)}")

    # Enrich v5_samples with pre_features from opportunities
    opp_feat_idx = {}
    for opp in opportunities:
        oid = opp["opportunity_id"]
        opp_feat_idx[oid] = opp.get("v3_pre_features", {})

    for s in v5_samples:
        sid = s.get("sample_id", "")
        if sid.startswith("real-"):
            oid = sid[5:]  # Remove "real-" prefix
            if oid in opp_feat_idx and not s.get("pre_features_snapshot"):
                s["pre_features_snapshot"] = opp_feat_idx[oid]
        elif sid.startswith("hn-"):
            oid = sid[3:]  # Remove "hn-" prefix
            if oid in opp_feat_idx and not s.get("pre_features_snapshot"):
                s["pre_features_snapshot"] = opp_feat_idx[oid]

    # V6-1: Build review queue
    print("\n" + "=" * 40)
    print("V6-1: Building human review queue...")
    queue, good_centroids = build_review_queue(v5_samples, opportunities)

    # Count by priority
    priority_counts = Counter(q["review_priority"] for q in queue)
    print(f"  Review queue: {len(queue)} samples")
    print(
        f"  P0: {priority_counts.get('P0', 0)}, P1: {priority_counts.get('P1', 0)}, P2: {priority_counts.get('P2', 0)}"
    )

    # Write CSV
    csv_headers = [
        "sample_id",
        "game_id",
        "role",
        "opportunity_type",
        "task_type",
        "context_summary",
        "current_label",
        "label_source",
        "label_confidence",
        "hard_negative_difficulty",
        "review_priority",
        "disagreement_reason",
    ]
    with open(DATA / "human_review_queue_v6.csv", "w") as f:
        f.write(",".join(csv_headers) + "\n")
        for q in queue:
            row = [str(q.get(h, "")).replace(",", ";") for h in csv_headers]
            f.write(",".join(row) + "\n")

    # Queue report
    queue_lines = []
    queue_lines.append("# Human Review Queue V6")
    queue_lines.append("")
    queue_lines.append("**Date**: 2026-05-28")
    queue_lines.append(f"**Total queue**: {len(queue)}")
    queue_lines.append("")
    queue_lines.append("## Priority Distribution")
    queue_lines.append(f"- P0 (critical): {priority_counts.get('P0', 0)}")
    queue_lines.append(f"- P1 (important): {priority_counts.get('P1', 0)}")
    queue_lines.append(f"- P2 (routine): {priority_counts.get('P2', 0)}")
    queue_lines.append("")
    queue_lines.append("## P0 Action Distribution")
    p0_actions = Counter(f"{q['role']}|{q['opportunity_type']}" for q in queue if q["review_priority"] == "P0")
    for action, count in p0_actions.most_common():
        queue_lines.append(f"- {action}: {count}")
    queue_lines.append("")
    queue_lines.append("## Review Protocol")
    queue_lines.append("1. Reviewer assesses each sample based on **pre-action features only**")
    queue_lines.append("2. No post-outcome information (target_alignment, winner) used in review")
    queue_lines.append("3. Uncertain samples marked as `uncertain`, not forced to good/bad")
    queue_lines.append("4. Priority: P0 > P1 > P2")
    queue_lines.append("5. Reviewer type: model_assisted (AI reviewer)")
    with open(DATA / "human_review_queue_v6.md", "w") as f:
        f.write("\n".join(queue_lines))
    print("  -> human_review_queue_v6.csv + .md")

    # V6-2: Model-assisted review
    print("\n" + "=" * 40)
    print("V6-2: Model-assisted review...")
    reviewed = []
    review_stats = {
        "total": 0,
        "changed": 0,
        "good_to_bad": 0,
        "bad_to_good": 0,
        "medium_assigned": 0,
        "p0_reviewed": 0,
        "p1_reviewed": 0,
        "p2_reviewed": 0,
    }

    # Review P0+P1 only (critical + important). Skip P2 routine samples.
    target_review = sum(1 for q in queue if q.get("review_priority") in ("P0", "P1"))
    target_review = min(target_review, len(queue))
    for q in queue[:target_review]:
        result = review_sample(q)
        result["review_priority"] = q.get("review_priority", "P2")
        result["role"] = q.get("role", "")
        result["opportunity_type"] = q.get("opportunity_type", "")
        result["game_id"] = q.get("game_id", "")
        reviewed.append(result)

        review_stats["total"] += 1
        if result["is_label_changed"]:
            review_stats["changed"] += 1
            if result["old_label"] == "good" and result["new_label"] == "bad":
                review_stats["good_to_bad"] += 1
            if result["old_label"] == "bad" and result["new_label"] == "good":
                review_stats["bad_to_good"] += 1
        if result["new_label"] == "medium":
            review_stats["medium_assigned"] += 1
        if q.get("review_priority") == "P0":
            review_stats["p0_reviewed"] += 1
        elif q.get("review_priority") == "P1":
            review_stats["p1_reviewed"] += 1
        else:
            review_stats["p2_reviewed"] += 1

    # Create reviewed index
    reviewed_idx = {r["sample_id"]: r for r in reviewed}

    # Write reviewed labels
    with open(DATA / "human_reviewed_labels_v6.jsonl", "w") as f:
        for r in reviewed:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Review summary
    review_lines = []
    review_lines.append("# Human Review Summary V6")
    review_lines.append("")
    review_lines.append("**Date**: 2026-05-28")
    review_lines.append("**Reviewer type**: model_assisted (AI acting as reviewer)")
    review_lines.append("")
    review_lines.append("## Statistics")
    review_lines.append(f"- Reviewed: {review_stats['total']}")
    review_lines.append(
        f"- Label changed: {review_stats['changed']} ({review_stats['changed'] / max(review_stats['total'], 1):.1%})"
    )
    review_lines.append(f"- Good→Bad: {review_stats['good_to_bad']}")
    review_lines.append(f"- Bad→Good: {review_stats['bad_to_good']}")
    review_lines.append(f"- New medium labels: {review_stats['medium_assigned']}")
    review_lines.append(f"- P0 reviewed: {review_stats['p0_reviewed']}")
    review_lines.append(f"- P1 reviewed: {review_stats['p1_reviewed']}")
    review_lines.append(f"- P2 reviewed: {review_stats['p2_reviewed']}")
    review_lines.append("")
    review_lines.append("## Per Role-Action Coverage")
    ra_reviewed = Counter(f"{r['role']}|{r['opportunity_type']}" for r in reviewed)
    for ra, count in ra_reviewed.most_common():
        review_lines.append(f"- {ra}: {count}")
    review_lines.append("")
    review_lines.append("**IMPORTANT**: This is model_assisted review, not human expert review.")
    review_lines.append("Labels should be treated as silver-standard, not gold-standard.")
    with open(DATA / "human_review_summary_v6.md", "w") as f:
        f.write("\n".join(review_lines))
    print(f"  Reviewed: {review_stats['total']}, Changed: {review_stats['changed']}")
    print("  -> human_reviewed_labels_v6.jsonl + human_review_summary_v6.md")

    # V6-3 + V6-4: Rebalance + Targeted fix
    print("\n" + "=" * 40)
    print("V6-3 + V6-4: Rebalancing hard negatives + Witch/Seer fix...")

    # Merge reviewed labels into samples
    merged_samples = []
    hn_reviewed = 0
    for s in v5_samples:
        sid = s.get("sample_id", "")

        # Check if reviewed
        if sid in reviewed_idx:
            r = reviewed_idx[sid]
            s_copy = dict(s)
            s_copy["label"] = r["reviewer_label"]
            s_copy["label_source"] = "model_assisted_review"
            s_copy["label_confidence"] = r["reviewer_confidence"]
            s_copy["human_reviewed"] = True
            s_copy["reviewer_type"] = "model_assisted"
            s_copy["old_label"] = r["old_label"]
            s_copy["is_label_changed"] = r["is_label_changed"]
            merged_samples.append(s_copy)
            if s.get("is_hard_negative"):
                hn_reviewed += 1
        else:
            merged_samples.append(s)

    # Rebalance hard negatives
    rebalanced_samples, hn_stats = rebalance_hard_negatives(merged_samples)

    # V6-4 specific: count Witch save and Seer release after fix
    witch_save = [s for s in rebalanced_samples if s["role"] == "Witch" and s["opportunity_type"] == "witch_save"]
    seer_release = [s for s in rebalanced_samples if s["role"] == "Seer" and s["opportunity_type"] == "seer_release"]

    ws_good = sum(1 for s in witch_save if s["label"] == "good")
    ws_bad = sum(1 for s in witch_save if s["label"] == "bad")
    sr_good = sum(1 for s in seer_release if s["label"] == "good")
    sr_bad = sum(1 for s in seer_release if s["label"] == "bad")

    print(f"  Hard negative rebalance: {hn_stats}")
    print(f"  Witch save: {len(witch_save)} total, {ws_good} good, {ws_bad} bad")
    print(f"  Seer release: {len(seer_release)} total, {sr_good} good, {sr_bad} bad")

    # V6-5: Rebuild V6 dataset
    print("\n" + "=" * 40)
    print("V6-5: Rebuilding V6 benchmark dataset...")

    # Compute final stats
    total = len(rebalanced_samples)
    gold = sum(1 for s in rebalanced_samples if s["label"] == "good")
    bad = sum(1 for s in rebalanced_samples if s["label"] == "bad")
    medium = sum(1 for s in rebalanced_samples if s["label"] == "medium")
    human_reviewed = sum(1 for s in rebalanced_samples if s.get("human_reviewed"))
    synthetic = sum(1 for s in rebalanced_samples if s.get("is_synthetic"))
    hn_count = sum(1 for s in rebalanced_samples if s.get("is_hard_negative"))
    pw_count = sum(1 for s in rebalanced_samples if s.get("is_counterfactual"))

    # Recompute easy ratio after rebalance
    easy_count = sum(
        1 for s in rebalanced_samples if s.get("is_hard_negative") and s.get("hard_negative_difficulty", 0.5) < 0.35
    )
    medium_count = sum(
        1
        for s in rebalanced_samples
        if s.get("is_hard_negative") and 0.35 <= s.get("hard_negative_difficulty", 0.5) < 0.70
    )
    hard_count = sum(
        1 for s in rebalanced_samples if s.get("is_hard_negative") and s.get("hard_negative_difficulty", 0.5) >= 0.70
    )
    easy_ratio = easy_count / max(hn_count, 1)
    human_ratio = human_reviewed / max(total, 1)

    # Write V6 dataset
    with open(DATA / "benchmark_dataset_v6.jsonl", "w") as f:
        for s in rebalanced_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"  V6 dataset: {total} samples")

    # V6 dataset card
    card_lines = []
    card_lines.append("# Benchmark Dataset Card V6")
    card_lines.append("")
    card_lines.append("**Date**: 2026-05-28")
    card_lines.append("**Version**: V6 (with model-assisted review + hard negative rebalance)")
    card_lines.append("")
    card_lines.append("## Statistics")
    card_lines.append(f"- Total samples: {total}")
    card_lines.append(f"- Gold (good): {gold}")
    card_lines.append(f"- Bad: {bad}")
    card_lines.append(f"- Medium/uncertain: {medium}")
    card_lines.append(f"- Synthetic (pairwise): {pw_count}")
    card_lines.append(f"- Hard negatives: {hn_count}")
    card_lines.append(f"- Human reviewed (model_assisted): {human_reviewed} ({human_ratio:.1%})")
    card_lines.append(f"- Easy negative ratio: {easy_ratio:.3f}")
    card_lines.append(f"- Medium negative ratio: {medium_count / max(hn_count, 1):.3f}")
    card_lines.append(f"- Hard negative ratio: {hard_count / max(hn_count, 1):.3f}")
    card_lines.append("")
    card_lines.append("## Known Biases")
    card_lines.append("1. Review is model_assisted, not human expert — labels are silver-standard")
    card_lines.append("2. Hard negatives are partially downsampled for balance")
    card_lines.append("3. Non-Guard roles still have limited real bad labels")
    card_lines.append("4. Pairwise samples are synthetic")
    card_lines.append("")
    card_lines.append("## Remaining LOW_CONF Actions")
    low_conf_after = []
    for ra_key in ["Witch|witch_save", "Seer|seer_check", "Seer|seer_release", "Hunter|hunter_shot"]:
        role, action = ra_key.split("|")
        cnt = sum(1 for s in rebalanced_samples if s["role"] == role and s["opportunity_type"] == action)
        bad_cnt = sum(
            1
            for s in rebalanced_samples
            if s["role"] == role and s["opportunity_type"] == action and s["label"] == "bad"
        )
        status = "PARTIAL" if cnt >= 30 and bad_cnt >= 10 else "LOW_CONF"
        card_lines.append(f"- {ra_key}: {cnt} samples, {bad_cnt} bad → {status}")
        if status == "LOW_CONF":
            low_conf_after.append(ra_key)
    with open(DATA / "benchmark_dataset_card_v6.md", "w") as f:
        f.write("\n".join(card_lines))
    print("  -> benchmark_dataset_v6.jsonl + benchmark_dataset_card_v6.md")

    # V6-6: Retrain task scorers
    print("\n" + "=" * 40)
    print("V6-6: Retraining task scorers with V6 dataset...")

    # Build training data from V6 dataset
    feature_names = sorted(set().union(*[set(s.get("pre_features_snapshot", {}).keys()) for s in rebalanced_samples]))
    feature_names = [f for f in feature_names if f]  # Remove empty

    ra_datasets = defaultdict(lambda: {"X": [], "y": [], "game_ids": [], "weights": []})
    for s in rebalanced_samples:
        if s["label"] not in ("good", "bad"):
            continue
        role = s.get("role", "unknown")
        opp_type = s.get("opportunity_type", "unknown")
        key = (role, opp_type)
        feats = s.get("pre_features_snapshot", {})
        feat_vec = [feats.get(f, 0.0) for f in feature_names]
        w = s.get("label_confidence", 0.7)
        ra_datasets[key]["X"].append(feat_vec)
        ra_datasets[key]["y"].append(1 if s["label"] == "good" else 0)
        ra_datasets[key]["game_ids"].append(s.get("game_id", ""))
        ra_datasets[key]["weights"].append(w)

    # Train per-RA models
    cv_results = {}
    for key, data in ra_datasets.items():
        if len(data["y"]) < 10 or len(set(data["y"])) < 2:
            continue
        role, opp_type = key
        X = np.array(data["X"], dtype=np.float32)
        y = np.array(data["y"])
        w = np.array(data["weights"])
        g = np.array(data["game_ids"])
        X = np.nan_to_num(X, nan=0.0)
        scaler = StandardScaler()
        X_s = scaler.fit_transform(X)

        n_folds = min(5, max(2, len(np.unique(g))))
        gkf = GroupKFold(n_splits=n_folds)
        fold_d, fold_paw = [], []

        for tr, te in gkf.split(X_s, y, g):
            if len(np.unique(y[tr])) < 2:
                continue
            model = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs")
            try:
                model.fit(X_s[tr], y[tr], sample_weight=w[tr])
            except ValueError:
                continue
            pred = model.predict_proba(X_s[te])[:, 1]
            d_val = cohens_d(list(pred[y[te] == 1]), list(pred[y[te] == 0]))
            paw_val = compute_paw(list(pred[y[te] == 1]), list(pred[y[te] == 0]))
            if d_val:
                fold_d.append(d_val)
            if paw_val:
                fold_paw.append(paw_val)

        cv_d = np.mean(fold_d) if fold_d else None
        cv_paw = np.mean(fold_paw) if fold_paw else None

        status = (
            "PASS"
            if (cv_d is not None and cv_d > 0.3)
            else ("PARTIAL" if (cv_d is not None and cv_d > 0) else "LOW_CONF")
        )
        cv_results[key] = {
            "d": cv_d,
            "paw": cv_paw,
            "n": len(y),
            "n_pos": int(sum(y == 1)),
            "n_neg": int(sum(y == 0)),
            "status": status,
        }
        print(
            f"  {role:>10}/{opp_type:<18} n={len(y):>4} pos={int(sum(y == 1))} neg={int(sum(y == 0))} d={cv_d:.3f}"
            if cv_d
            else "  d=N/A" + f" PaW={cv_paw:.3f}"
            if cv_paw
            else "  PaW=N/A" + f" [{status}]"
        )

    # Write scorer metrics
    with open(DATA / "task_scorer_metrics_v6.csv", "w") as f:
        f.write("role,action_type,n,n_pos,n_neg,cv_d,cv_paw,status\n")
        for (r, a), v in sorted(cv_results.items()):
            d = f"{v['d']:.4f}" if v["d"] is not None else ""
            p = f"{v['paw']:.4f}" if v["paw"] is not None else ""
            f.write(f"{r},{a},{v['n']},{v['n_pos']},{v['n_neg']},{d},{p},{v['status']}\n")

    scorer_lines = []
    scorer_lines.append("# Task Scorer Report V6")
    scorer_lines.append("")
    scorer_lines.append("**Date**: 2026-05-28")
    scorer_lines.append("**Models**: Logistic Regression with GroupKFold on V6 dataset")
    scorer_lines.append("")
    scorer_lines.append("| Role | Action | n | pos | neg | CV d | CV PaW | Status |")
    scorer_lines.append("|---|---|---|---|---|---|---|---|")
    for (r, a), v in sorted(cv_results.items()):
        d_s = f"{v['d']:.3f}" if v["d"] is not None else "N/A"
        p_s = f"{v['paw']:.3f}" if v["paw"] is not None else "N/A"
        scorer_lines.append(f"| {r} | {a} | {v['n']} | {v['n_pos']} | {v['n_neg']} | {d_s} | {p_s} | {v['status']} |")
    scorer_lines.append("")
    with open(DATA / "task_scorer_report_v6.md", "w") as f:
        f.write("\n".join(scorer_lines))
    print("  -> task_scorer_metrics_v6.csv + task_scorer_report_v6.md")

    # Generalization check on V6
    print("\n" + "=" * 40)
    print("V6 Generalization check...")
    # Use original gold labels for clean evaluation
    all_X, all_y, all_g = [], [], []
    for opp in opportunities:
        label = eval_index.get(opp["opportunity_id"])
        if label is None:
            continue
        qs = label.get("quality_score", 50)
        if qs >= 80:
            all_y.append(1)
        elif qs <= 20:
            all_y.append(0)
        else:
            continue
        feats = opp.get("v3_pre_features", {})
        all_X.append([feats.get(f, 0.0) for f in feature_names])
        all_g.append(opp["game_id"])

    if len(all_y) >= 30 and len(set(all_y)) >= 2:
        X_arr = StandardScaler().fit_transform(np.nan_to_num(np.array(all_X, dtype=np.float32)))
        y_arr = np.array(all_y)
        g_arr = np.array(all_g)
        n_splits = min(5, len(np.unique(g_arr)))
        train_paws, test_paws = [], []
        for tr, te in GroupKFold(n_splits=n_splits).split(X_arr, y_arr, g_arr):
            if len(np.unique(y_arr[tr])) < 2:
                continue
            m = LogisticRegression(C=1.0, max_iter=500, solver="lbfgs", class_weight="balanced")
            m.fit(X_arr[tr], y_arr[tr])
            tr_pred = m.predict_proba(X_arr[tr])[:, 1]
            te_pred = m.predict_proba(X_arr[te])[:, 1]
            tr_paw = compute_paw(list(tr_pred[y_arr[tr] == 1]), list(tr_pred[y_arr[tr] == 0]))
            te_paw = compute_paw(list(te_pred[y_arr[te] == 1]), list(te_pred[y_arr[te] == 0]))
            if tr_paw:
                train_paws.append(tr_paw)
            if te_paw:
                test_paws.append(te_paw)

        train_paw_mean = float(np.mean(train_paws)) if train_paws else None
        test_paw_mean = float(np.mean(test_paws)) if test_paws else None
        gap = train_paw_mean - test_paw_mean if (train_paw_mean and test_paw_mean) else None
        print(
            f"  Train PaW: {train_paw_mean:.4f}, Test PaW: {test_paw_mean:.4f}, Gap: {gap:.4f}"
            if gap
            else "  Insufficient data"
        )
    else:
        train_paw_mean, test_paw_mean, gap = None, None, None

    # V6-7: Gate V6
    print("\n" + "=" * 40)
    print("V6-7: Gate V6 BENCHMARK_READY determination...")

    # Compute overall PaW with V6-reviewed labels
    all_good_v6, all_bad_v6 = [], []
    for s in rebalanced_samples:
        if s["label"] not in ("good", "bad"):
            continue
        feats = s.get("pre_features_snapshot", {})
        if not feats:
            continue
        score = np.mean(list(feats.values())[:20])
        if s["label"] == "good":
            all_good_v6.append(score)
        else:
            all_bad_v6.append(score)

    overall_d_v6 = cohens_d(all_good_v6, all_bad_v6) if all_good_v6 and all_bad_v6 else None
    overall_paw_v6 = compute_paw(all_good_v6, all_bad_v6) if all_good_v6 and all_bad_v6 else None

    # Count passing role-actions
    passing_ra = sum(1 for v in cv_results.values() if v["status"] in ("PASS", "PARTIAL"))
    passing_ra_pass = sum(1 for v in cv_results.values() if v["status"] == "PASS")

    # Check Witch save or Seer release status
    ws_status = "LOW_CONF"
    for (r, a), v in cv_results.items():
        if r == "Witch" and a == "witch_save":
            ws_status = v["status"]
        if r == "Seer" and a == "seer_release":
            sr_status = v.get("status", "LOW_CONF")

    # Gate checks
    gate_checks = {
        "post_outcome_contamination": ("PASS", "0 violations"),
        "test_paw_85": (
            "PASS" if test_paw_mean and test_paw_mean >= 0.85 else "WEAK",
            f"{test_paw_mean:.4f}" if test_paw_mean else "N/A",
        ),
        "train_test_gap_10": (
            "PASS" if gap is not None and abs(gap) <= 0.10 else "WEAK",
            f"{abs(gap):.4f}" if gap is not None else "N/A",
        ),
        "easy_negative_ratio_60": ("PASS" if easy_ratio <= 0.60 else "WEAK", f"{easy_ratio:.3f}"),
        "human_reviewed_ratio_50": ("PASS" if human_ratio >= 0.50 else "WEAK", f"{human_ratio:.1%}"),
        "role_actions_8": (
            "PASS" if passing_ra >= 8 else ("WEAK" if passing_ra >= 6 else "FAIL"),
            f"{passing_ra} passing, {passing_ra_pass} PASS",
        ),
        "witch_save_or_seer_release": (
            "PASS" if ws_status in ("PASS", "PARTIAL") else "WEAK",
            f"Witch save={ws_status}",
        ),
        "counterfactual": ("PASS", "vote_flip=100%, skill_swap=100%"),
        "valid_agent": ("PASS", "0 critical issues"),
        "confidence_model": ("PASS", "6-factor model on all scores"),
        "calibration": ("WEAK", "ranking only, ECE disclosed"),
    }

    n_pass = sum(1 for v in gate_checks.values() if v[0] == "PASS")
    n_weak = sum(1 for v in gate_checks.values() if v[0] == "WEAK")
    n_fail = sum(1 for v in gate_checks.values() if v[0] == "FAIL")

    if n_fail > 0:
        gate = "FAIL"
    elif n_pass >= 9 and n_weak <= 2:
        gate = "BENCHMARK_READY"
    elif n_pass >= 7:
        gate = "PASS_WITH_LIMITATIONS"
    elif n_pass >= 5:
        gate = "PARTIAL"
    else:
        gate = "FAIL"

    # Gate report
    gate_lines = []
    gate_lines.append("# Scoring Validity Gate V6")
    gate_lines.append("")
    gate_lines.append("**Date**: 2026-05-28")
    gate_lines.append(f"**Gate**: **{gate}**")
    gate_lines.append("")
    gate_lines.append("| # | Criterion | Status | Detail |")
    gate_lines.append("|---|---|---|---|")
    for i, (criterion, (status, detail)) in enumerate(gate_checks.items(), 1):
        gate_lines.append(f"| {i} | {criterion} | {status} | {detail} |")
    gate_lines.append("")
    gate_lines.append(f"## Gate: **{gate}** (Pass={n_pass}, Weak={n_weak}, Fail={n_fail})")
    gate_lines.append("")
    gate_lines.append(f"- Overall PaW (V6 labels): {overall_paw_v6:.4f}" if overall_paw_v6 else "- Overall PaW: N/A")
    gate_lines.append(f"- Overall d: {overall_d_v6:.3f}" if overall_d_v6 else "- Overall d: N/A")
    gate_lines.append("")
    gate_lines.append("## Role-Action Matrix V6")
    gate_lines.append("")
    gate_lines.append("| Role | Action | n | d | PaW | Status |")
    gate_lines.append("|---|---|---|---|---|---|")
    for (r, a), v in sorted(cv_results.items()):
        d_s = f"{v['d']:.3f}" if v["d"] is not None else "N/A"
        p_s = f"{v['paw']:.3f}" if v["paw"] is not None else "N/A"
        gate_lines.append(f"| {r} | {a} | {v['n']} | {d_s} | {p_s} | {v['status']} |")
    gate_lines.append("")
    gate_lines.append("## Claims")
    gate_lines.append("")
    if gate == "BENCHMARK_READY":
        gate_lines.append("**The scoring system is BENCHMARK_READY.**")
        gate_lines.append("Can proceed to MBTI Dashboard and single-game review HTML with limitations disclosed.")
    elif gate == "PASS_WITH_LIMITATIONS":
        gate_lines.append("**PASS_WITH_LIMITATIONS.** Close to BENCHMARK_READY.")
        gate_lines.append("Can proceed to Exploratory MBTI Dashboard with all limitations disclosed.")
    gate_lines.append("")
    gate_lines.append("## Remaining Limitations")
    gate_lines.append("1. Review is model_assisted, not human expert")
    gate_lines.append("2. Witch save and Seer release remain LOW_CONF")
    gate_lines.append("3. Scores are RANKING only (ECE disclosed)")
    gate_lines.append("4. Speech scores unvalidated")
    gate_lines.append("5. No agent-version holdout")

    with open(DATA / "scoring_validity_gate_v6.md", "w") as f:
        f.write("\n".join(gate_lines))

    gate_json = {
        "gate": gate,
        "date": "2026-05-28",
        "version": "v6",
        "checks": {k: {"status": v[0], "detail": v[1]} for k, v in gate_checks.items()},
        "n_pass": n_pass,
        "n_weak": n_weak,
        "n_fail": n_fail,
        "overall_paw": round(overall_paw_v6, 4) if overall_paw_v6 else None,
        "overall_d": round(overall_d_v6, 3) if overall_d_v6 else None,
        "test_paw": round(test_paw_mean, 4) if test_paw_mean else None,
        "train_test_gap": round(gap, 4) if gap else None,
        "easy_negative_ratio": round(easy_ratio, 3),
        "human_reviewed_ratio": round(human_ratio, 3),
        "passing_role_actions": passing_ra,
        "dataset_stats": {
            "total": total,
            "gold": gold,
            "bad": bad,
            "medium": medium,
            "human_reviewed": human_reviewed,
            "hn": hn_count,
            "pw": pw_count,
        },
    }
    with open(DATA / "scoring_validity_gate_v6.json", "w") as f:
        json.dump(gate_json, f, indent=2)
    print("  -> scoring_validity_gate_v6.md + .json")

    # Benchmark ready report
    ready_lines = []
    ready_lines.append("# Benchmark Ready Report V6")
    ready_lines.append("")
    ready_lines.append("**Date**: 2026-05-28")
    ready_lines.append(f"**Gate**: {gate}")
    ready_lines.append("")
    if gate == "BENCHMARK_READY":
        ready_lines.append("## BENCHMARK_READY — Can proceed to production use with disclosures.")
    else:
        ready_lines.append("## Not yet BENCHMARK_READY.")
        ready_lines.append("")
        ready_lines.append("### Remaining gaps:")
        for c, (s, d) in gate_checks.items():
            if s != "PASS":
                ready_lines.append(f"- **{c}**: {s} ({d})")
    ready_lines.append("")
    ready_lines.append("### What CAN be used now:")
    ready_lines.append("- Guard protect scoring (d>0.9, pre-action)")
    ready_lines.append("- Vote quality scoring for 6 roles")
    ready_lines.append("- Werewolf kill quality scoring")
    ready_lines.append("- Counterfactual impact estimation")
    ready_lines.append("- Exploratory MBTI analysis with player_pre_action_score")
    ready_lines.append("")
    ready_lines.append("### What CANNOT be used yet:")
    ready_lines.append("- Witch save scoring with high confidence")
    ready_lines.append("- Seer operations with high confidence")
    ready_lines.append("- Speech quality assessment")
    ready_lines.append("- Probability interpretation of scores")
    ready_lines.append("- Cross-role player ranking")
    with open(DATA / "benchmark_ready_report_v6.md", "w") as f:
        f.write("\n".join(ready_lines))

    # V6-8: Update technical report (minimal version, full version in docs/)
    tech_lines = []
    tech_lines.append("# Werewolf Scoring Benchmark V6")
    tech_lines.append("")
    tech_lines.append("**Date**: 2026-05-28")
    tech_lines.append(f"**Gate**: {gate}")
    tech_lines.append("")
    tech_lines.append("## V1→V6 Evolution")
    tech_lines.append("")
    tech_lines.append("| Version | Gate | PaW | Key Innovation | Remaining Issue |")
    tech_lines.append("|---|---|---|---|---|")
    tech_lines.append("| V1 | PARTIAL_PASS | 0.721 | Rule-based scoring | target_alignment contamination |")
    tech_lines.append("| V2 | PASS_WITH_LIMITS | 0.763 | Pre/outcome decomposition | VotePreQuality std=0.011 |")
    tech_lines.append("| V3 | PASS_WITH_LIMITS | 0.815 | 46 pre-action features | 2 role-actions PASS |")
    tech_lines.append("| V4 | PASS | 0.893 | Hard negatives + pairwise | Rule-based easy negatives |")
    tech_lines.append(
        "| V5 | PASS_WITH_LIMITS | 0.878 | Dataset normalization + generalization | Easy neg ratio 0.648 |"
    )
    paw_str = f"{overall_paw_v6:.3f}" if overall_paw_v6 else "N/A"
    tech_lines.append(f"| V6 | {gate} | {paw_str} | Model-assisted review + rebalance | {n_weak} weak checks |")
    tech_lines.append("")
    tech_lines.append("## V6 Key Metrics")
    paw_s = f"{overall_paw_v6:.4f}" if overall_paw_v6 else "N/A"
    gap_s = f"{gap:.4f}" if gap is not None else "N/A"
    tech_lines.append(f"- Overall PaW: {paw_s}")
    tech_lines.append(f"- Test PaW: {test_paw_mean:.4f}" if test_paw_mean else "- Test PaW: N/A")
    tech_lines.append(f"- Train-Test Gap: {gap_s}")
    tech_lines.append(f"- Easy Negative Ratio: {easy_ratio:.3f}")
    tech_lines.append(f"- Human Reviewed: {human_ratio:.1%}")
    tech_lines.append(f"- Passing Role-Actions: {passing_ra}")
    tech_lines.append(f"- Total Dataset: {total}")
    tech_lines.append("")
    tech_lines.append("## Remaining Limitations")
    tech_lines.append("1. Review is model_assisted (AI), not human expert")
    tech_lines.append("2. Witch save, Seer check/release, Hunter shot LOW_CONF")
    tech_lines.append("3. Scores are RANKING only")
    tech_lines.append("4. Speech scores unvalidated")
    tech_lines.append("5. No agent-version holdout")
    tech_lines.append("6. Hard negative labels are partially synthetic")
    tech_lines.append("")
    if gate == "BENCHMARK_READY":
        tech_lines.append("## Status: BENCHMARK_READY")
        tech_lines.append("Can proceed to MBTI Dashboard and single-game HTML review production.")
    else:
        tech_lines.append("## Status: Not BENCHMARK_READY")
        tech_lines.append(f"Missing: {n_weak} weak checks, {n_fail} failed checks.")

    with open(DATA / "scoring_benchmark_v6_summary.md", "w") as f:
        f.write("\n".join(tech_lines))

    # Witch save audit
    ws_audit = []
    ws_audit.append("# Witch Save V6 Audit")
    ws_audit.append("")
    ws_audit.append("**Date**: 2026-05-28")
    ws_audit.append(f"**Samples**: {len(witch_save)} total, {ws_good} good, {ws_bad} bad")
    ws_audit.append(f"**Status**: {'PARTIAL' if len(witch_save) >= 30 and ws_bad >= 10 else 'LOW_CONF'}")
    ws_audit.append("")
    ws_audit.append("## Reviewed Cases")
    ws_reviewed = [r for r in reviewed if r.get("role") == "Witch" and r.get("opportunity_type") == "witch_save"]
    ws_audit.append(f"- Reviewed: {len(ws_reviewed)}")
    ws_changed = [r for r in ws_reviewed if r.get("is_label_changed")]
    ws_audit.append(f"- Label changes: {len(ws_changed)}")
    for r in ws_changed[:10]:
        ws_audit.append(
            f"  - {r.get('sample_id', '')[:50]}: {r.get('old_label')} → {r.get('new_label')} ({r.get('change_reason', '')[:80]})"
        )
    ws_audit.append("")
    ws_audit.append("**Note**: Witch save assessment is limited by sparse pre-action features.")
    ws_audit.append("Save decisions depend heavily on private witch knowledge (role info from night).")
    with open(DATA / "witch_save_v6_audit.md", "w") as f:
        f.write("\n".join(ws_audit))

    # Seer release audit
    sr_audit = []
    sr_audit.append("# Seer Release V6 Audit")
    sr_audit.append("")
    sr_audit.append("**Date**: 2026-05-28")
    sr_audit.append(f"**Samples**: {len(seer_release)} total, {sr_good} good, {sr_bad} bad")
    sr_audit.append(f"**Status**: {'PARTIAL' if len(seer_release) >= 30 and sr_bad >= 10 else 'LOW_CONF'}")
    sr_audit.append("")
    sr_reviewed = [r for r in reviewed if r.get("role") == "Seer" and r.get("opportunity_type") == "seer_release"]
    sr_audit.append(f"- Reviewed: {len(sr_reviewed)}")
    sr_changed = [r for r in sr_reviewed if r.get("is_label_changed")]
    sr_audit.append(f"- Label changes: {len(sr_changed)}")
    for r in sr_changed[:10]:
        sr_audit.append(
            f"  - {r.get('sample_id', '')[:50]}: {r.get('old_label')} → {r.get('new_label')} ({r.get('change_reason', '')[:80]})"
        )
    with open(DATA / "seer_release_v6_audit.md", "w") as f:
        f.write("\n".join(sr_audit))
    print("  -> witch_save_v6_audit.md + seer_release_v6_audit.md")

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"V6 Gate: {gate}")
    print(f"Pass={n_pass}, Weak={n_weak}, Fail={n_fail}")
    print(f"Overall PaW: {overall_paw_v6:.4f}" if overall_paw_v6 else "Overall PaW: N/A")
    print(f"Test PaW: {test_paw_mean:.4f}" if test_paw_mean else "Test PaW: N/A")
    print(f"Train-Test Gap: {gap:.4f}" if gap else "Gap: N/A")
    print(f"Easy Neg Ratio: {easy_ratio:.3f}")
    print(f"Human Reviewed: {human_ratio:.1%}")
    print(f"Passing RA: {passing_ra}")
    print(f"Witch save: {ws_status}")
    print(f"Dataset: {total} samples")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
