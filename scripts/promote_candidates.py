#!/usr/bin/env python
# DEPRECATED: Use scripts/promote.py --mode quality instead. Kept for reference.
"""Candidate review pipeline: promote high-quality candidates to active,
deprecate low-quality ones, deduplicate near-identical strategies, and print
a structured report.

Usage:
  python scripts/promote_candidates.py
  python scripts/promote_candidates.py --dry-run
  python scripts/promote_candidates.py --quality-threshold 0.80 --deprecation-threshold 0.50
  python scripts/promote_candidates.py --enable-dedup  # remove near-duplicate strategies
  python scripts/promote_candidates.py --max-candidates 5000  # cap candidate pool
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# DB configuration — must be set BEFORE importing backend modules so that
# init_db() / SessionLocal pick up the correct URL.
# ---------------------------------------------------------------------------
DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
os.environ["DATABASE_URL"] = DB_URL

# ---------------------------------------------------------------------------
# Imports (after env is configured)
# ---------------------------------------------------------------------------
from backend.db.database import SessionLocal, init_db                     # noqa: E402
from backend.db.models import StrategyKnowledgeDoc                       # noqa: E402
from backend.eval.evolution import (                                     # noqa: E402
    StrategyKnowledgeStore,
    get_promotion_report,
    promote_candidates,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("promote_candidates")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_ROLES = [
    "Seer",
    "Witch",
    "Hunter",
    "Guard",
    "Villager",
    "Werewolf",
    "WhiteWolfKing",
    "global",
]

DEFAULT_QUALITY_THRESHOLD = 0.85
DEFAULT_DEPRECATION_THRESHOLD = 0.60
DEFAULT_MAX_CANDIDATES = 5000
DUPLICATE_SIMILARITY_THRESHOLD = 0.95
DEDUP_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _count_by_status(store: StrategyKnowledgeStore) -> dict[str, int]:
    """Count docs by status in the store."""
    counts = {"active": 0, "candidate": 0, "deprecated": 0}
    for doc in store.docs.values():
        status = doc.status
        if status in counts:
            counts[status] += 1
        else:
            counts[status] = 1
    return counts


def _count_active_by_role(store: StrategyKnowledgeStore) -> dict[str, int]:
    """Count active docs per role."""
    counts: dict[str, int] = {role: 0 for role in ALL_ROLES}
    for doc in store.docs.values():
        if doc.status == "active":
            role = doc.role if doc.role in counts else "global"
            counts[role] = counts.get(role, 0) + 1
    return counts


def _format_percent(numerator: int, denominator: int) -> str:
    """Return a XX% string, safe for zero denominator."""
    if denominator <= 0:
        return "0%"
    return f"{round(numerator / denominator * 100)}%"


def _build_doc_text(d: StrategyKnowledgeDoc) -> str:
    """Build a text representation for dedup comparison."""
    parts = []
    if d.situation_pattern:
        parts.append(d.situation_pattern[:300])
    if d.recommended_action:
        parts.append(d.recommended_action[:500])
    if d.rationale:
        parts.append(d.rationale[:300])
    return " ".join(parts)


def deduplicate_candidates(
    db,
    *,
    similarity_threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
    batch_size: int = DEDUP_BATCH_SIZE,
    dry_run: bool = False,
) -> dict[str, int]:
    """Detect near-duplicate candidate docs and deprecate lower-quality ones.

    Uses TF-IDF + cosine similarity within each (role, doc_type) bucket.
    Docs with similarity > threshold are considered duplicates — the
    higher quality_score doc is kept, the lower is deprecated.

    Returns {"merged": N, "checked": N}.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    candidates = (
        db.query(StrategyKnowledgeDoc)
        .filter(StrategyKnowledgeDoc.status == "candidate")
        .all()
    )
    logger.info("Dedup: loaded %d candidates for similarity check", len(candidates))

    if len(candidates) < 2:
        return {"merged": 0, "checked": len(candidates)}

    # Group by (role, doc_type) to avoid comparing unrelated docs
    buckets: dict[tuple[str, str], list[StrategyKnowledgeDoc]] = defaultdict(list)
    for doc in candidates:
        key = (doc.role, doc.doc_type or "unknown")
        buckets[key].append(doc)

    total_merged = 0
    total_checked = 0

    for (role, doc_type), docs in sorted(buckets.items()):
        if len(docs) < 2:
            total_checked += len(docs)
            continue

        texts = [_build_doc_text(d) for d in docs]

        try:
            vectorizer = TfidfVectorizer(
                max_features=500,
                ngram_range=(1, 2),
                sublinear_tf=True,
            )
            vectors = vectorizer.fit_transform(texts)
        except ValueError:
            total_checked += len(docs)
            continue

        # Compute pairwise similarity (can be large, so process in sub-batches)
        n = len(docs)
        deprecated_ids: set[str] = set()

        for i in range(0, n, batch_size):
            i_end = min(i + batch_size, n)
            chunk_vectors = vectors[i:i_end]
            sim_chunk = cosine_similarity(chunk_vectors, vectors)

            for local_idx in range(sim_chunk.shape[0]):
                global_idx = i + local_idx
                if docs[global_idx].id in deprecated_ids:
                    continue
                for j in range(sim_chunk.shape[1]):
                    if j <= global_idx:
                        continue  # Only compare i < j to avoid double-processing
                    if docs[j].id in deprecated_ids:
                        continue
                    if sim_chunk[local_idx, j] >= similarity_threshold:
                        # Keep higher quality, deprecate lower
                        q_i = docs[global_idx].quality_score
                        q_j = docs[j].quality_score
                        if q_i >= q_j:
                            deprecated_ids.add(docs[j].id)
                        else:
                            deprecated_ids.add(docs[global_idx].id)
                            break  # current doc is deprecated, skip remaining

        if deprecated_ids and not dry_run:
            for doc in docs:
                if doc.id in deprecated_ids:
                    doc.status = "deprecated"
            db.flush()

        total_merged += len(deprecated_ids)
        total_checked += n

        if len(deprecated_ids) > 0:
            logger.info(
                "  Dedup: %s/%s merged %d duplicates from %d docs",
                role, doc_type, len(deprecated_ids), n,
            )

    if total_merged > 0 and not dry_run:
        try:
            db.commit()
            logger.info("Dedup committed: %d docs deprecated as duplicates", total_merged)
        except Exception:
            db.rollback()
            raise

    return {"merged": total_merged, "checked": total_checked}


def prune_candidate_pool(
    db,
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    dry_run: bool = False,
) -> int:
    """Cap the candidate pool at max_candidates by deprecating lowest-quality ones.

    Returns number of candidates deprecated by pruning.
    """
    candidates = (
        db.query(StrategyKnowledgeDoc)
        .filter(StrategyKnowledgeDoc.status == "candidate")
        .order_by(StrategyKnowledgeDoc.quality_score.asc())
        .all()
    )

    excess = len(candidates) - max_candidates
    if excess <= 0:
        logger.info("Candidate pool size %d within limit %d, no pruning needed.",
                    len(candidates), max_candidates)
        return 0

    to_deprecate = candidates[:excess]
    logger.info(
        "Candidate pool %d exceeds limit %d. Pruning %d lowest-quality candidates "
        "(quality range: %.2f - %.2f).",
        len(candidates), max_candidates, len(to_deprecate),
        to_deprecate[0].quality_score if to_deprecate else 0,
        to_deprecate[-1].quality_score if to_deprecate else 0,
    )

    if dry_run:
        return len(to_deprecate)

    for doc in to_deprecate:
        doc.status = "deprecated"

    try:
        db.commit()
        logger.info("Pruned %d candidates (pool now capped at %d).", len(to_deprecate), max_candidates)
    except Exception:
        db.rollback()
        raise

    return len(to_deprecate)


def print_report(
    *,
    before: dict[str, int],
    thresholds: dict[str, float],
    results: dict[str, int],
    after: dict[str, int],
    active_by_role: dict[str, int],
    cleaning: dict[str, int] | None = None,
) -> None:
    """Print the structured candidate review report."""
    print()
    print("=== Candidate Review Report ===")
    print("Before:")
    print(f"  Active: {before['active']}")
    print(f"  Candidate: {before['candidate']}")
    print(f"  Deprecated: {before['deprecated']}")
    print()
    print("Promotion thresholds:")
    print(f"  quality >= {thresholds['quality']:.2f} -> active")
    print(f"  quality < {thresholds['deprecation']:.2f} -> deprecated")
    print()
    print("Results:")
    total = results.get("total_candidates", 0)
    promoted = results.get("promoted", 0)
    deprecated = results.get("deprecated", 0)
    skipped = results.get("skipped", 0)
    print(f"  Promoted to active: {promoted} ({_format_percent(promoted, total)})")
    print(f"  Deprecated (low quality): {deprecated} ({_format_percent(deprecated, total)})")
    print(f"  Skipped (stays candidate): {skipped}")
    if cleaning:
        merged = cleaning.get("merged", 0)
        pruned = cleaning.get("pruned", 0)
        if merged:
            print(f"  Merged (duplicates removed): {merged}")
        if pruned:
            print(f"  Pruned (candidate pool cap): {pruned}")
    print()
    print("After:")
    print(f"  Active: {after['active']}")
    print(f"  Candidate: {after['candidate']}")
    print(f"  Deprecated: {after['deprecated']}")
    print()
    print("=== Per-role Active Counts ===")
    for role in ALL_ROLES:
        print(f"{role}: {active_by_role.get(role, 0)}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote / deprecate / clean strategy knowledge candidates"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only — do not write changes to the store or DB",
    )
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=DEFAULT_QUALITY_THRESHOLD,
        help=f"Quality score above which candidates are promoted (default: {DEFAULT_QUALITY_THRESHOLD})",
    )
    parser.add_argument(
        "--deprecation-threshold",
        type=float,
        default=DEFAULT_DEPRECATION_THRESHOLD,
        help=f"Quality score below which candidates are deprecated (default: {DEFAULT_DEPRECATION_THRESHOLD})",
    )
    parser.add_argument(
        "--enable-dedup",
        action="store_true",
        default=False,
        help="Enable TF-IDF duplicate detection (expensive on large pools)",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=DEFAULT_MAX_CANDIDATES,
        help=f"Maximum candidate pool size (default: {DEFAULT_MAX_CANDIDATES})",
    )
    args = parser.parse_args()

    quality_threshold = args.quality_threshold
    deprecation_threshold = args.deprecation_threshold
    dry_run = args.dry_run
    enable_dedup = args.enable_dedup
    max_candidates = args.max_candidates

    # ---------------------------------------------------------------
    # Step 0: Clean (dedup + prune) directly via DB
    # ---------------------------------------------------------------
    cleaning: dict[str, int] = {"merged": 0, "pruned": 0}

    if enable_dedup or dry_run:
        logger.info("Initializing DB for cleaning...")
        init_db()
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("SELECT 1"))

            if enable_dedup:
                logger.info("Running duplicate detection...")
                dedup_result = deduplicate_candidates(
                    db,
                    dry_run=dry_run,
                )
                cleaning["merged"] = dedup_result["merged"]
                logger.info("Dedup: merged %d duplicates", cleaning["merged"])

            # Prune if candidate pool exceeds limit
            candidate_count = (
                db.query(StrategyKnowledgeDoc)
                .filter(StrategyKnowledgeDoc.status == "candidate")
                .count()
            )
            if candidate_count > max_candidates:
                cleaning["pruned"] = prune_candidate_pool(
                    db,
                    max_candidates=max_candidates,
                    dry_run=dry_run,
                )
                logger.info("Pruned %d excess candidates", cleaning["pruned"])

        finally:
            db.close()

        if dry_run and not enable_dedup:
            # In dry-run mode without dedup, skip cleaning and proceed to preview
            pass

    if dry_run and cleaning["merged"] == 0 and cleaning["pruned"] == 0:
        pass  # continue to promotion preview below

    # ---------------------------------------------------------------
    # Step 1-3: Load store, promote, sync
    # ---------------------------------------------------------------
    logger.info("Loading strategy knowledge from PostgreSQL...")

    try:
        store = StrategyKnowledgeStore.load_from_pg()
        if store is None:
            logger.error(
                "Failed to load strategy knowledge from PostgreSQL. "
                "Check that the DATABASE_URL is correct and the database is reachable."
            )
            sys.exit(1)
    except Exception as exc:
        logger.error(f"Failed to load from PostgreSQL: {exc}", exc_info=True)
        sys.exit(1)

    logger.info(
        "Loaded %d docs from PostgreSQL",
        len(store.docs),
    )

    # Snapshot before state
    before = _count_by_status(store)
    logger.info(
        "Before: active=%d candidate=%d deprecated=%d",
        before["active"],
        before["candidate"],
        before["deprecated"],
    )

    # Dry-run preview via get_promotion_report
    logger.info("Running dry-run preview (get_promotion_report)...")
    preview = get_promotion_report(store)
    logger.info(
        "Preview: %d would be promoted, %d deprecated, %d skipped",
        preview.get("promoted", 0),
        preview.get("deprecated", 0),
        preview.get("skipped", 0),
    )

    if dry_run:
        logger.info("Dry-run mode — no writes will be performed.")
        after = before  # unchanged
        results = preview
    else:
        # Run real promotion
        logger.info(
            "Running promote_candidates with quality >= %.2f, deprecation < %.2f...",
            quality_threshold,
            deprecation_threshold,
        )
        results = promote_candidates(
            store,
            quality_threshold=quality_threshold,
            deprecation_threshold=deprecation_threshold,
            dry_run=False,
        )
        logger.info(
            "Promotion complete: %d promoted, %d deprecated, %d skipped",
            results.get("promoted", 0),
            results.get("deprecated", 0),
            results.get("skipped", 0),
        )

        # Snapshot after state
        after = _count_by_status(store)
        logger.info(
            "After: active=%d candidate=%d deprecated=%d",
            after["active"],
            after["candidate"],
            after["deprecated"],
        )

        # Sync back to PostgreSQL
        if results.get("promoted", 0) > 0 or results.get("deprecated", 0) > 0:
            logger.info("Syncing changes back to PostgreSQL...")
            try:
                saved = store.sync_to_pg()
                logger.info("Synced %d docs to PostgreSQL", saved)
            except Exception as exc:
                logger.error(f"Failed to sync to PostgreSQL: {exc}", exc_info=True)
                logger.warning(
                    "Promotions were applied in-memory but NOT persisted to the database. "
                    "Re-run the script to retry the sync."
                )
        else:
            logger.info("No changes to sync (no promotions or deprecations).")

    # Print detailed report
    active_by_role = _count_active_by_role(store)

    print_report(
        before=before,
        thresholds={"quality": quality_threshold, "deprecation": deprecation_threshold},
        results=results,
        after=after,
        active_by_role=active_by_role,
        cleaning=cleaning,
    )

    # Cleaning summary
    total_cleaned = cleaning.get("merged", 0) + cleaning.get("pruned", 0)
    if total_cleaned > 0:
        print(f"Cleaning summary: merged {cleaning['merged']} duplicates, "
              f"pruned {cleaning['pruned']} from candidate pool cap.\n")

    logger.info("Done.")


if __name__ == "__main__":
    main()
