#!/usr/bin/env python3
"""Build human pairwise labeling queue from real replay opportunities.

Outputs unlabeled candidates following the human pairwise label schema.
Gracefully exits with low-sample warning if no real replay data exists.
"""

from __future__ import annotations

import argparse, json, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "health"


def load_opps():
    opps = []
    fp = DATA / "opportunities.jsonl"
    if fp.exists():
        with open(fp) as f:
            for line in f:
                if line.strip():
                    try: opps.append(json.loads(line))
                    except json.JSONDecodeError: pass
    return opps


def build_queue(opps, max_candidates=200):
    if not opps:
        print("No real replay opportunities found. Queue is empty.")
        return [], True  # low_sample

    # Group by (role, action_type)
    by_key = defaultdict(list)
    for opp in opps:
        key = (opp.get("role", ""), opp.get("opportunity_type", ""))
        by_key[key].append(opp)

    candidates = []
    cid = 0

    for (role, atype), items in sorted(by_key.items()):
        if len(items) < 2:
            continue
        # Take pairs within same role/action, preferring score diversity
        scored = [o for o in items if o.get("calibrated_q") is not None]
        if len(scored) >= 2:
            scored.sort(key=lambda o: o.get("calibrated_q", 0.5))
            # Pair lowest vs highest
            for i in range(min(5, len(scored)//2)):
                a, b = scored[i], scored[-1-i]
                if a.get("opportunity_id") == b.get("opportunity_id"):
                    continue
                candidates.append({
                    "label_id": f"label_candidate_{cid:06d}",
                    "game_id": a.get("game_id", b.get("game_id", "")),
                    "source": "real_replay",
                    "role": role, "action_type": atype,
                    "day": a.get("day", 0), "phase": a.get("phase", ""),
                    "context_summary": a.get("public_context_summary", "")[:200],
                    "visible_public_context": {"events_summary": a.get("public_context_summary", "")},
                    "visible_private_context": {"summary": a.get("private_context_summary", "")},
                    "option_a": {
                        "opportunity_id": a.get("opportunity_id", ""),
                        "action": a.get("chosen_action", {}),
                        "evidence_event_ids": a.get("evidence_event_ids", [])[:10],
                    },
                    "option_b": {
                        "opportunity_id": b.get("opportunity_id", ""),
                        "action": b.get("chosen_action", {}),
                        "evidence_event_ids": b.get("evidence_event_ids", [])[:10],
                    },
                    "label": "UNLABELED", "confidence": "medium",
                    "reason": "", "annotator_id": "", "created_at": "",
                })
                cid += 1
                if cid >= max_candidates:
                    break
        if cid >= max_candidates:
            break

    low_sample = cid < 20
    return candidates, low_sample


def main():
    parser = argparse.ArgumentParser(description="Build human pairwise labeling queue")
    parser.add_argument("--output", default=str(DATA / "human_pairwise_queue.jsonl"))
    parser.add_argument("--max", type=int, default=200)
    args = parser.parse_args()

    opps = load_opps()
    print(f"Loaded {len(opps)} opportunities")
    candidates, low_sample = build_queue(opps, args.max)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    action_coverage = defaultdict(int)
    for c in candidates:
        action_coverage[c["action_type"]] += 1

    print(f"Candidates: {len(candidates)} -> {out}")
    for at, n in sorted(action_coverage.items()):
        print(f"  {at}: {n}")
    if low_sample:
        print("WARNING: low sample — insufficient candidates for robust validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
