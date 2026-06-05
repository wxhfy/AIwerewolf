#!/usr/bin/env python3
# DEPRECATED: Use scripts/promote.py --mode quality instead. Kept for reference.
"""Auto-promote candidate strategies to active via clustering + quality filter.

Cluster candidates by (role, doc_type), pick Top-1 per cluster meeting
quality threshold, promote to active.

Usage:
    python scripts/auto_promote.py --dry-run    # preview only
    python scripts/auto_promote.py --apply      # execute promotion
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Parameters
CLUSTER_TOP_N = 1
MIN_QUALITY_FOR_PROMOTION = 0.85
MAX_CANDIDATES = 3000


def fetch_candidates(conn) -> list[dict[str, Any]]:
    """Fetch all candidate docs for promotion consideration."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, role, doc_type, phase, quality_score, situation_pattern,
                  recommended_action, rationale
           FROM strategy_knowledge_docs
           WHERE status = 'candidate'
           ORDER BY quality_score DESC"""
    )
    docs = []
    for row in cur.fetchall():
        docs.append({
            "id": row[0],
            "role": row[1] or "global",
            "doc_type": row[2] or "unknown",
            "phase": row[3] or "global",
            "quality_score": float(row[4]) if row[4] else 0.8,
            "situation": str(row[5] or ""),
            "action": str(row[6] or ""),
            "rationale": str(row[7] or ""),
        })
    cur.close()
    return docs


def _doc_text(doc: dict) -> str:
    return f"{doc['situation']} {doc['action']} {doc['rationale']}"


def cluster_by_similarity(docs: list[dict]) -> list[list[dict]]:
    """Simple similarity-based clustering using Jaccard on jieba tokens.

    For small candidate pools, a lightweight approach beats heavy embedding models.
    """
    if len(docs) <= 1:
        return [docs] if docs else []

    import jieba

    token_sets = []
    for d in docs:
        tokens = set(w for w in jieba.cut(_doc_text(d)) if len(w) >= 2)
        token_sets.append(tokens)

    # Greedy clustering: assign each doc to nearest cluster
    clusters: list[list[dict]] = []
    assigned = [False] * len(docs)

    for i in range(len(docs)):
        if assigned[i]:
            continue
        cluster = [docs[i]]
        assigned[i] = True

        for j in range(i + 1, len(docs)):
            if assigned[j]:
                continue
            if not token_sets[i] or not token_sets[j]:
                continue
            jaccard = len(token_sets[i] & token_sets[j]) / len(token_sets[i] | token_sets[j])
            if jaccard >= 0.15:
                cluster.append(docs[j])
                assigned[j] = True

        clusters.append(cluster)

    return clusters


def promote_docs(conn, doc_ids: list[str]) -> int:
    """Promote docs from candidate to active. Returns count updated."""
    if not doc_ids:
        return 0
    cur = conn.cursor()
    cur.execute(
        "UPDATE strategy_knowledge_docs SET status = 'active' WHERE id = ANY(%s)",
        (doc_ids,),
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    return updated


def cleanup_excess_candidates(conn, docs: list[dict], max_candidates: int) -> int:
    """If candidate pool exceeds MAX_CANDIDATES, deprecate lowest-quality candidates."""
    excess = len(docs) - max_candidates
    if excess <= 0:
        return 0

    # Sort by quality_score ASC (worst first), deprecate excess
    sorted_docs = sorted(docs, key=lambda d: d["quality_score"])
    to_deprecate = [d["id"] for d in sorted_docs[:excess]]

    cur = conn.cursor()
    cur.execute(
        "UPDATE strategy_knowledge_docs SET status = 'deprecated' WHERE id = ANY(%s)",
        (to_deprecate,),
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    return updated


def main():
    ap = argparse.ArgumentParser(description="Auto-promote candidate strategies to active")
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-quality", type=float, default=MIN_QUALITY_FOR_PROMOTION)
    ap.add_argument("--cluster-top-n", type=int, default=CLUSTER_TOP_N)
    ap.add_argument("--max-candidates", type=int, default=MAX_CANDIDATES)
    args = ap.parse_args()

    import psycopg2
    conn = psycopg2.connect(DB_URL)

    candidates = fetch_candidates(conn)
    logger.info("Loaded %d candidate docs", len(candidates))

    # Group by (role, doc_type)
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in candidates:
        buckets[(d["role"], d["doc_type"])].append(d)

    to_promote: list[str] = []
    promotion_details: list[dict] = []

    for (role, doc_type), docs in sorted(buckets.items()):
        if len(docs) < 2:
            # Single candidate — promote if quality >= threshold
            if docs and docs[0]["quality_score"] >= args.min_quality:
                to_promote.append(docs[0]["id"])
                promotion_details.append({
                    "role": role, "doc_type": doc_type,
                    "cluster_size": 1, "doc_id": docs[0]["id"][:20],
                    "quality": docs[0]["quality_score"],
                })
            continue

        clusters = cluster_by_similarity(docs)

        for cluster in clusters:
            if not cluster:
                continue
            # Sort cluster by quality_score DESC
            cluster.sort(key=lambda d: -d["quality_score"])
            # Pick top-N
            for doc in cluster[:args.cluster_top_n]:
                if doc["quality_score"] >= args.min_quality:
                    to_promote.append(doc["id"])
                    promotion_details.append({
                        "role": role, "doc_type": doc_type,
                        "cluster_size": len(cluster),
                        "doc_id": doc["id"][:20],
                        "quality": doc["quality_score"],
                    })

    # Print summary
    print(f"\n{'='*70}")
    print(f"  Auto-Promotion Summary")
    print(f"{'='*70}")
    print(f"  Candidates loaded: {len(candidates)}")
    print(f"  Candidates to promote: {len(to_promote)}")
    print(f"  Quality threshold: >= {args.min_quality}")
    print(f"  Cluster top-N: {args.cluster_top_n}")
    print(f"")

    if promotion_details:
        print(f"  {'Role':<15} {'DocType':<20} {'Cluster':>7} {'Quality':>8}")
        print(f"  {'-'*50}")
        for d in promotion_details[:30]:
            print(f"  {d['role']:<15} {d['doc_type']:<20} {d['cluster_size']:>7} {d['quality']:>8.2%}")
        if len(promotion_details) > 30:
            print(f"  ... and {len(promotion_details) - 30} more")

    # Cleanup excess
    excess_removed = 0
    if len(candidates) > args.max_candidates:
        excess_removed = len(candidates) - args.max_candidates
        print(f"\n  Candidate pool ({len(candidates)}) exceeds max ({args.max_candidates})")
        print(f"  Would deprecate {excess_removed} lowest-quality candidates.")

    if args.apply:
        if to_promote:
            logger.info("Promoting %d docs from candidate → active...", len(to_promote))
            updated = promote_docs(conn, to_promote)
            logger.info("Done: %d docs promoted to active.", updated)

        if excess_removed > 0:
            logger.info("Cleaning up %d excess candidates → deprecated...", excess_removed)
            removed = cleanup_excess_candidates(conn, candidates, args.max_candidates)
            logger.info("Done: %d candidates deprecated.", removed)

        # Verify
        cur = conn.cursor()
        cur.execute("SELECT status, count(*) FROM strategy_knowledge_docs GROUP BY status")
        statuses = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        for s, cnt in sorted(statuses.items()):
            logger.info("  %s: %d", s, cnt)
    else:
        print(f"\n  [DRY RUN] Add --apply to execute.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
