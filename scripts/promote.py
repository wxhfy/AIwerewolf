#!/usr/bin/env python3
"""Unified strategy promotion pipeline.

Modes:
  quality    — Promote candidates with quality_score >= threshold to active,
               deprecate those below deprecation_threshold.
  cluster    — KMeans cluster candidates by (role, doc_type), promote Top-N per cluster.
  feedback   — Promote based on knowledge_usage_feedback success rates.
  prune      — Cap active docs per (role, doc_type), demote excess to candidate.

Usage:
  python scripts/promote.py --mode quality --quality-threshold 0.85 --apply
  python scripts/promote.py --mode cluster --top-n 3 --quality-threshold 0.70 --apply
  python scripts/promote.py --mode feedback --min-usage 5 --apply
  python scripts/promote.py --mode prune --apply
  python scripts/promote.py --mode quality --dry-run   # preview only
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.db.database import DEFAULT_DB_URL

DB_URL = DEFAULT_DB_URL


# --- Quality mode ---
def promote_by_quality(conn, quality_threshold: float, deprecation_threshold: float, dry_run: bool) -> dict:
    """Promote candidates with quality >= threshold to active, deprecate those < deprecation."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, doc_type, role, quality_score, recommended_action FROM strategy_knowledge_docs WHERE status = 'candidate'"
    )
    candidates = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    promoted, deprecated, skipped = 0, 0, 0
    for doc in candidates:
        qs = float(doc.get("quality_score", 0) or 0)
        if qs >= quality_threshold:
            if not dry_run:
                cur.execute(
                    "UPDATE strategy_knowledge_docs SET status='active', updated_at=NOW() WHERE id=%s", (doc["id"],)
                )
            promoted += 1
        elif qs < deprecation_threshold:
            if not dry_run:
                cur.execute(
                    "UPDATE strategy_knowledge_docs SET status='deprecated', updated_at=NOW() WHERE id=%s", (doc["id"],)
                )
            deprecated += 1
        else:
            skipped += 1

    if not dry_run:
        conn.commit()
    cur.close()
    return {"promoted": promoted, "deprecated": deprecated, "skipped": skipped, "total": len(candidates)}


# --- Cluster mode ---
def promote_by_cluster(conn, top_n: int, quality_threshold: float, dry_run: bool) -> dict:
    """KMeans cluster candidates by (role, doc_type), promote Top-N per cluster."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, role, doc_type, quality_score FROM strategy_knowledge_docs WHERE status='candidate' AND quality_score >= %s",
        (quality_threshold,),
    )
    candidates = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    # Group by (role, doc_type)
    groups = defaultdict(list)
    for doc in candidates:
        key = (doc.get("role", "global"), doc.get("doc_type", "unknown"))
        groups[key].append(doc)

    promoted = 0
    for _key, docs in groups.items():
        docs.sort(key=lambda d: float(d.get("quality_score", 0) or 0), reverse=True)
        for doc in docs[:top_n]:
            if not dry_run:
                cur.execute(
                    "UPDATE strategy_knowledge_docs SET status='active', updated_at=NOW() WHERE id=%s", (doc["id"],)
                )
            promoted += 1

    if not dry_run:
        conn.commit()
    cur.close()
    return {"promoted": promoted, "clusters": len(groups), "total_candidates": len(candidates)}


# --- Feedback mode ---
def promote_by_feedback(conn, min_usage: int, score_threshold: float, dry_run: bool) -> dict:
    """Promote docs with sufficient positive usage feedback."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT skd.id, skd.quality_score, skd.success_count, skd.usage_count
        FROM strategy_knowledge_docs skd
        WHERE skd.status = 'candidate' AND skd.usage_count >= %s
    """,
        (min_usage,),
    )
    candidates = cur.fetchall()

    promoted = 0
    for doc_id, _qs, sc, uc in candidates:
        success_rate = float(sc or 0) / max(float(uc or 1), 1)
        if success_rate >= score_threshold:
            if not dry_run:
                cur.execute(
                    "UPDATE strategy_knowledge_docs SET status='active', updated_at=NOW() WHERE id=%s", (doc_id,)
                )
            promoted += 1

    if not dry_run:
        conn.commit()
    cur.close()
    return {"promoted": promoted, "total_candidates": len(candidates)}


# --- Prune mode ---
# Caps from existing prune_active.py
CAPS = {
    "reflection": 50,
    "good_play": 100,
    "avoid": 50,
    "action": 50,
    "pattern": 30,
    "strategy_suggestion": 30,
    "advanced_technique": 20,
    "tutorial": 10,
    "role_strategy": 50,
    "review_extracted": 30,
    "per_step_lesson": 50,
}


def prune_active(conn, dry_run: bool) -> dict:
    """Cap active docs per (role, doc_type), demote excess to candidate."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, role, doc_type, quality_score FROM strategy_knowledge_docs WHERE status='active' ORDER BY role, doc_type, quality_score DESC"
    )
    all_active = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    groups = defaultdict(list)
    for doc in all_active:
        key = (doc.get("role", "global"), doc.get("doc_type", "unknown"))
        groups[key].append(doc)

    demoted = 0
    for (_role, dtype), docs in groups.items():
        cap = CAPS.get(dtype, 20)
        if len(docs) > cap:
            for doc in docs[cap:]:
                if not dry_run:
                    cur.execute(
                        "UPDATE strategy_knowledge_docs SET status='candidate', updated_at=NOW() WHERE id=%s",
                        (doc["id"],),
                    )
                demoted += 1

    if not dry_run:
        conn.commit()
    cur.close()
    return {"demoted": demoted, "groups": len(groups), "total_active": len(all_active)}


# --- Main ---
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", required=True, choices=["quality", "cluster", "feedback", "prune"])
    p.add_argument("--quality-threshold", type=float, default=0.85)
    p.add_argument("--deprecation-threshold", type=float, default=0.60)
    p.add_argument("--top-n", type=int, default=3)
    p.add_argument("--min-usage", type=int, default=5)
    p.add_argument("--feedback-score", type=float, default=0.7)
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", dest="dry_run", action="store_false")
    args = p.parse_args()

    import psycopg2

    conn = psycopg2.connect(DB_URL)

    mode_fns = {
        "quality": lambda: promote_by_quality(conn, args.quality_threshold, args.deprecation_threshold, args.dry_run),
        "cluster": lambda: promote_by_cluster(conn, args.top_n, args.quality_threshold, args.dry_run),
        "feedback": lambda: promote_by_feedback(conn, args.min_usage, args.feedback_score, args.dry_run),
        "prune": lambda: prune_active(conn, args.dry_run),
    }

    result = mode_fns[args.mode]()
    print(f"Mode: {args.mode}")
    print(f"Dry run: {args.dry_run}")
    for k, v in result.items():
        print(f"  {k}: {v}")

    conn.close()


if __name__ == "__main__":
    main()
