#!/usr/bin/env python3
# DEPRECATED: Use scripts/promote.py --mode prune instead. Kept for reference.
"""Prune active strategies by (role, doc_type) per-class caps.

Excess docs are demoted to 'candidate' (not deprecated) so the candidate
pool stays populated for future promotion.

Usage:
    python scripts/prune_active.py --dry-run    # preview only
    python scripts/prune_active.py --apply      # execute pruning
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Per-role caps for each doc_type
DOC_TYPE_CAPS: dict[str, int] = {
    "reflection": 20,
    "avoid": 30,
    "good_play": 25,
    "action": 20,
    "pattern": 10,
    "bad_case_lesson": 15,
    "counterfactual_lesson": 10,
    "role_strategy": 15,
    "strategy_suggestion": 15,
    "web_strategy": 15,
}


def _cap_for(doc_type: str) -> int | None:
    """Return the per-role cap for a doc_type, or None if unlimited."""
    return DOC_TYPE_CAPS.get(doc_type)  # None = unlimited


def fetch_active_buckets(conn):
    """Return list of (role, doc_type, [(id, quality_score), ...]) for active docs."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, role, doc_type, quality_score
           FROM strategy_knowledge_docs
           WHERE status = 'active'
           ORDER BY role, doc_type, quality_score DESC"""
    )
    buckets: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for row in cur.fetchall():
        doc_id, role, doc_type, quality = row
        key = (role or "global", doc_type or "unknown")
        buckets[key].append((doc_id, float(quality) if quality else 0.8))
    cur.close()
    return buckets


def demote_docs(conn, doc_ids: list[str]) -> int:
    """Demote docs from active to candidate. Returns count updated."""
    if not doc_ids:
        return 0
    cur = conn.cursor()
    cur.execute(
        "UPDATE strategy_knowledge_docs SET status = 'candidate' WHERE id = ANY(%s)",
        (doc_ids,),
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    return updated


def main():
    ap = argparse.ArgumentParser(description="Prune active strategies by (role,doc_type) caps")
    ap.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without executing (default)")
    ap.add_argument("--apply", action="store_true", help="Actually execute the pruning")
    args = ap.parse_args()

    import psycopg2

    conn = psycopg2.connect(DB_URL)

    # Current state
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM strategy_knowledge_docs WHERE status = 'active'")
    total_active_before = cur.fetchone()[0]
    cur.close()
    logger.info("Active docs before pruning: %d", total_active_before)

    buckets = fetch_active_buckets(conn)

    to_demote: list[str] = []
    stats: dict[str, dict] = {}  # doc_type -> {keep, demote, total}

    total_keep = 0
    total_demote = 0

    for (role, doc_type), docs in buckets.items():
        cap = _cap_for(doc_type)
        key = f"{role}/{doc_type}"

        if cap is None:
            # Unlimited types
            stats[key] = {"keep": len(docs), "demote": 0, "total": len(docs)}
            total_keep += len(docs)
            continue

        # Sort by quality_score DESC, keep top N
        docs_sorted = sorted(docs, key=lambda x: -x[1])

        keep = docs_sorted[:cap]
        demote = docs_sorted[cap:]

        stats[key] = {"keep": len(keep), "demote": len(demote), "total": len(docs)}
        total_keep += len(keep)
        total_demote += len(demote)

        if demote:
            to_demote.extend([d[0] for d in demote])

    # Print summary
    print(f"\n{'=' * 70}")
    print("  Active Pruning Summary")
    print(f"{'=' * 70}")
    print(f"  {'Bucket':<30} {'Total':>6} {'Keep':>6} {'Demote':>6} {'Cap':>6}")
    print(f"  {'-' * 54}")

    # Sort by demote count desc
    for key, s in sorted(stats.items(), key=lambda x: -x[1]["demote"]):
        cap = _cap_for(key.split("/")[-1]) if "/" in key else None
        cap_str = str(cap) if cap is not None else "∞"
        if s["demote"] > 0:
            print(f"  {key:<30} {s['total']:>6} {s['keep']:>6} {s['demote']:>6} {cap_str:>6}")

    print(f"  {'-' * 54}")
    print(f"  {'TOTAL':<30} {total_active_before:>6} {total_keep:>6} {total_demote:>6}")
    print(f"{'=' * 70}")

    # Role-level check: each role should have at least 50 active
    role_keep: dict[str, int] = defaultdict(int)
    for key, s in stats.items():
        role = key.rsplit("/", 1)[0]  # "Werewolf/reflection" → "Werewolf"
        role_keep[role] += s["keep"]

    print("\n  Active per role after pruning:")
    for role, cnt in sorted(role_keep.items(), key=lambda x: -x[1]):
        flag = " ⚠️ <50" if cnt < 50 else ""
        print(f"    {role:<20} {cnt:>5}{flag}")

    if args.apply:
        if not to_demote:
            logger.info("Nothing to demote — all buckets within caps.")
        else:
            logger.info("Demoting %d docs from active → candidate...", len(to_demote))
            updated = demote_docs(conn, to_demote)
            logger.info("Done: %d docs demoted to candidate.", updated)

            # Verify
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM strategy_knowledge_docs WHERE status = 'active'")
            total_active_after = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM strategy_knowledge_docs WHERE status = 'candidate'")
            total_candidate_after = cur.fetchone()[0]
            cur.close()
            logger.info("Active: %d → %d", total_active_before, total_active_after)
            logger.info("Candidate: now %d", total_candidate_after)
    else:
        print(f"\n  [DRY RUN] Add --apply to execute. Would demote {len(to_demote)} docs.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
