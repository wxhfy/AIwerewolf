#!/usr/bin/env python3
"""Evaluate model-human pairwise agreement.

Computes pairwise accuracy between human labels and model predictions.
Gracefully handles low-sample and missing-data scenarios.
"""

from __future__ import annotations

import argparse, json, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "health"


def load_labels(path):
    labels = []
    with open(path) as f:
        for line in f:
            if line.strip():
                try: labels.append(json.loads(line))
                except json.JSONDecodeError: pass
    return labels


def load_scores():
    scores = {}
    fp = DATA / "opportunity_scores_trained.jsonl"
    if fp.exists():
        with open(fp) as f:
            for line in f:
                if line.strip():
                    try:
                        d = json.loads(line)
                        scores[d.get("opportunity_id", "")] = d
                    except json.JSONDecodeError: pass
    return scores


def evaluate_agreement(labels, scores):
    usable = [l for l in labels if l.get("label") not in ("TIE", "UNCERTAIN", "UNLABELED", "")]
    if len(usable) < 5:
        return {"status": "low_sample", "usable_pairs": len(usable), "message": "Need >=5 usable pairs"}

    by_action = defaultdict(lambda: {"correct": 0, "total": 0})
    total_correct, total_pairs = 0, 0
    disagreements = []

    for lab in usable:
        aid = lab.get("option_a", {}).get("opportunity_id", "")
        bid = lab.get("option_b", {}).get("opportunity_id", "")
        sa = scores.get(aid, {}); sb = scores.get(bid, {})
        qa = sa.get("calibrated_q", 0.5) or 0.5
        qb = sb.get("calibrated_q", 0.5) or 0.5
        rqa = sa.get("raw_model_q", qa) or qa; rqb = sb.get("raw_model_q", qb) or qb

        model_prefers_a = qa >= qb
        human_prefers_a = lab["label"] == "A_BETTER"
        correct = model_prefers_a == human_prefers_a

        at = lab.get("action_type", "unknown")
        by_action[at]["total"] += 1
        if correct: by_action[at]["correct"] += 1
        total_pairs += 1
        if correct: total_correct += 1

        if not correct:
            disagreements.append({
                "label_id": lab.get("label_id"), "action_type": at,
                "human_label": lab["label"],
                "model_a_q": round(qa, 4), "model_b_q": round(qb, 4),
                "model_prefers": "A" if model_prefers_a else "B",
            })

    acc = total_correct / max(total_pairs, 1)
    by_action_acc = {at: round(d["correct"]/max(d["total"], 1), 4) for at, d in by_action.items()}

    return {
        "status": "evaluated", "total_labeled_pairs": len(labels),
        "usable_pairs": total_pairs, "tie_count": sum(1 for l in labels if l.get("label") == "TIE"),
        "uncertain_count": sum(1 for l in labels if l.get("label") == "UNCERTAIN"),
        "calibrated_q_accuracy": round(acc, 4),
        "by_action_type_accuracy": by_action_acc,
        "disagreement_count": len(disagreements),
        "disagreement_examples": disagreements[:5],
        "low_sample_warning": total_pairs < 20,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate human pairwise agreement")
    parser.add_argument("--labels", default=str(DATA / "human_pairwise_labels_sample.jsonl"))
    parser.add_argument("--output", default=str(DATA / "human_pairwise_agreement.json"))
    args = parser.parse_args()

    labels = load_labels(args.labels)
    scores = load_scores()
    print(f"Labels: {len(labels)}, Scored opportunities: {len(scores)}")

    if not labels:
        print("No labels found. Skipping agreement evaluation.")
        result = {"status": "skipped", "reason": "no_labels"}
    else:
        result = evaluate_agreement(labels, scores)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Result -> {out}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
