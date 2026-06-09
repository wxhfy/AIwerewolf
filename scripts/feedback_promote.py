#!/usr/bin/env python3
# DEPRECATED: Use scripts/promote.py --mode feedback instead. Kept for reference.
"""Feedback-driven strategy promotion/demotion.

Uses knowledge_usage_feedback records to compute a per-strategy feedback score,
then promotes high performers to active and demotes low performers to deprecated.

Formula:
  feedback_score = 0.3 × usage_rate + 0.4 × success_rate
                 + 0.2 × avg_score_delta_norm + 0.1 × recency_weight

Promotion rules:
  - feedback_score >= 0.7 AND usage_count >= 5 → promote to active
  - feedback_score < 0.3 AND usage_count >= 10 → demote to deprecated
  - Otherwise → keep current status

Usage:
    python scripts/feedback_promote.py --dry-run    # preview only
    python scripts/feedback_promote.py --apply      # execute promotion/demotion
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_URL = "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Scoring weights
WEIGHT_USAGE = 0.3
WEIGHT_SUCCESS = 0.4
WEIGHT_SCORE_DELTA = 0.2
WEIGHT_RECENCY = 0.1

# Thresholds
PROMOTE_SCORE = 0.7
PROMOTE_MIN_USAGE = 5
DEMOTE_SCORE = 0.3
DEMOTE_MIN_USAGE = 10


def fetch_feedback_data(conn):
    """Fetch aggregated feedback per knowledge_doc_id."""
    cur = conn.cursor()
    cur.execute(
        """SELECT knowledge_doc_id,
                  COUNT(*) as total_retrieved,
                  SUM(CASE WHEN used THEN 1 ELSE 0 END) as total_used,
                  SUM(CASE WHEN helpful THEN 1 ELSE 0 END) as total_helpful,
                  AVG(score_delta) as avg_score_delta,
                  MAX(created_at) as last_used_at
           FROM knowledge_usage_feedback
           WHERE knowledge_doc_id IS NOT NULL
             AND knowledge_doc_id != ''
           GROUP BY knowledge_doc_id
           HAVING COUNT(*) >= 2"""
    )
    data = {}
    for row in cur.fetchall():
        doc_id, total, used, helpful, avg_delta, last_used = row
        data[doc_id] = {
            "total_retrieved": int(total),
            "total_used": int(used or 0),
            "total_helpful": int(helpful or 0),
            "avg_score_delta": float(avg_delta) if avg_delta is not None else 0.0,
            "last_used_at": last_used,
        }
    cur.close()
    return data


def fetch_doc_status(conn, doc_ids: list[str]) -> dict[str, dict]:
    """Fetch current status and quality for given doc IDs."""
    if not doc_ids:
        return {}
    cur = conn.cursor()
    cur.execute(
        "SELECT id, status, quality_score, doc_type, role FROM strategy_knowledge_docs WHERE id = ANY(%s)",
        (doc_ids,),
    )
    result = {}
    for row in cur.fetchall():
        result[row[0]] = {
            "status": row[1],
            "quality_score": float(row[2]) if row[2] else 0.8,
            "doc_type": row[3] or "",
            "role": row[4] or "global",
        }
    cur.close()
    return result


def compute_feedback_scores(feedback_data: dict, doc_statuses: dict) -> list[dict[str, Any]]:
    """Compute feedback_score for each doc. Returns sorted list of score dicts."""
    now = datetime.now(timezone.utc)
    scores = []

    # Normalize score_delta: map [-20, 50] → [0, 1]
    all_deltas = [d["avg_score_delta"] for d in feedback_data.values()]
    delta_min = min(all_deltas) if all_deltas else -20
    delta_max = max(all_deltas) if all_deltas else 50
    delta_range = delta_max - delta_min or 1

    for doc_id, fb in feedback_data.items():
        total = fb["total_retrieved"]
        usage_rate = fb["total_used"] / total if total > 0 else 0
        success_rate = fb["total_helpful"] / fb["total_used"] if fb["total_used"] > 0 else 0

        # Normalize score delta to [0, 1]
        norm_delta = (fb["avg_score_delta"] - delta_min) / delta_range
        norm_delta = max(0.0, min(1.0, norm_delta))

        # Recency: days since last use, decaying
        last_used = fb["last_used_at"]
        if last_used:
            days_since = (now - last_used.replace(tzinfo=timezone.utc)).days
            recency = max(0.0, 1.0 - days_since / 30.0)  # decay over 30 days
        else:
            days_since = 999
            recency = 0.0

        feedback_score = (
            WEIGHT_USAGE * usage_rate
            + WEIGHT_SUCCESS * success_rate
            + WEIGHT_SCORE_DELTA * norm_delta
            + WEIGHT_RECENCY * recency
        )

        doc_info = doc_statuses.get(doc_id, {})
        scores.append(
            {
                "doc_id": doc_id,
                "current_status": doc_info.get("status", "unknown"),
                "doc_type": doc_info.get("doc_type", ""),
                "role": doc_info.get("role", "global"),
                "quality_score": doc_info.get("quality_score", 0.8),
                "feedback_score": round(feedback_score, 4),
                "usage_count": total,
                "usage_rate": round(usage_rate, 3),
                "success_rate": round(success_rate, 3),
                "avg_score_delta": round(fb["avg_score_delta"], 2),
                "recency": round(recency, 3),
                "days_since_use": days_since,
            }
        )

    scores.sort(key=lambda x: -x["feedback_score"])
    return scores


def update_statuses(conn, promote_ids: list[str], demote_ids: list[str]):
    """Batch update doc statuses."""
    if promote_ids:
        cur = conn.cursor()
        cur.execute(
            "UPDATE strategy_knowledge_docs SET status = 'active' WHERE id = ANY(%s)",
            (promote_ids,),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        logger.info("Promoted %d docs to active", updated)

    if demote_ids:
        cur = conn.cursor()
        cur.execute(
            "UPDATE strategy_knowledge_docs SET status = 'deprecated' WHERE id = ANY(%s)",
            (demote_ids,),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        logger.info("Demoted %d docs to deprecated", updated)


def main():
    ap = argparse.ArgumentParser(description="Feedback-driven strategy promotion/demotion")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--promote-score", type=float, default=PROMOTE_SCORE)
    ap.add_argument("--demote-score", type=float, default=DEMOTE_SCORE)
    ap.add_argument("--min-usage-promote", type=int, default=PROMOTE_MIN_USAGE)
    ap.add_argument("--min-usage-demote", type=int, default=DEMOTE_MIN_USAGE)
    args = ap.parse_args()

    import psycopg2

    conn = psycopg2.connect(DB_URL)

    # Fetch data
    logger.info("Fetching feedback data...")
    feedback_data = fetch_feedback_data(conn)
    logger.info("Found %d docs with feedback data", len(feedback_data))

    doc_ids = list(feedback_data.keys())
    doc_statuses = fetch_doc_status(conn, doc_ids)
    logger.info("Matched %d docs in strategy_knowledge_docs", len(doc_statuses))

    # Compute scores
    scores = compute_feedback_scores(feedback_data, doc_statuses)

    # Classify
    promote_ids = []
    demote_ids = []
    for s in scores:
        if s["feedback_score"] >= args.promote_score and s["usage_count"] >= args.min_usage_promote:
            if s["current_status"] != "deprecated":
                promote_ids.append(s["doc_id"])
        elif s["feedback_score"] < args.demote_score and s["usage_count"] >= args.min_usage_demote:
            if s["current_status"] != "active":
                demote_ids.append(s["doc_id"])

    # Print report
    print(f"\n{'=' * 70}")
    print("  Feedback-Driven Promotion Report")
    print(f"{'=' * 70}")
    print(f"  Docs with feedback data: {len(scores)}")
    print(f"  Docs to promote (score >= {args.promote_score}, usage >= {args.min_usage_promote}): {len(promote_ids)}")
    print(f"  Docs to demote  (score <  {args.demote_score}, usage >= {args.min_usage_demote}): {len(demote_ids)}")
    print("")

    # Top performers
    print("  Top 15 by feedback_score:")
    print(
        f"  {'Score':>7} {'Usage':>6} {'Use%':>6} {'Succ%':>6} {'Delta':>6} {'Days':>5} {'Status':>8} {'Role':>12} {'Type'}"
    )
    print(f"  {'-' * 70}")
    for s in scores[:15]:
        print(
            f"  {s['feedback_score']:>7.3f} {s['usage_count']:>6} {s['usage_rate']:>6.0%} "
            f"{s['success_rate']:>6.0%} {s['avg_score_delta']:>6.1f} {s['days_since_use']:>5} "
            f"{s['current_status']:>8} {s['role']:>12} {s['doc_type']}"
        )

    # Bottom performers (candidates for demotion)
    worst = [s for s in scores if s["feedback_score"] < args.demote_score and s["usage_count"] >= args.min_usage_demote]
    if worst:
        print("\n  Bottom performers (demotion candidates):")
        print(
            f"  {'Score':>7} {'Usage':>6} {'Use%':>6} {'Succ%':>6} {'Delta':>6} {'Days':>5} {'Status':>8} {'Role':>12} {'Type'}"
        )
        print(f"  {'-' * 70}")
        for s in sorted(worst, key=lambda x: x["feedback_score"])[:15]:
            print(
                f"  {s['feedback_score']:>7.3f} {s['usage_count']:>6} {s['usage_rate']:>6.0%} "
                f"{s['success_rate']:>6.0%} {s['avg_score_delta']:>6.1f} {s['days_since_use']:>5} "
                f"{s['current_status']:>8} {s['role']:>12} {s['doc_type']}"
            )

    # Score distribution
    buckets = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    dist = defaultdict(int)
    for s in scores:
        score = s["feedback_score"]
        for b in reversed(buckets):
            if score >= b:
                dist[b] += 1
                break
    print("\n  Score distribution:")
    for b in sorted(dist.keys()):
        bar = "█" * (dist[b] // max(1, max(dist.values()) // 30))
        print(f"    >= {b:.1f}: {dist[b]:>5} {bar}")

    if args.apply:
        update_statuses(conn, promote_ids, demote_ids)
        # Verify
        cur = conn.cursor()
        cur.execute("SELECT status, count(*) FROM strategy_knowledge_docs GROUP BY status")
        statuses = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        for s, cnt in sorted(statuses.items()):
            logger.info("  %s: %d", s, cnt)
    else:
        print("\n  [DRY RUN] Add --apply to execute.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
