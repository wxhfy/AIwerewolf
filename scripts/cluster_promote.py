#!/usr/bin/env python3
"""
Cluster-based strategy promotion using TF-IDF + KMeans.

Groups candidate docs by (role, doc_type), clusters them, and promotes
the Top-3 highest-quality docs per cluster to active status. Also deprecates
candidates with quality_score below the deprecation threshold.

Usage:
  python scripts/cluster_promote.py                    # Full run
  python scripts/cluster_promote.py --dry-run           # Preview only
  python scripts/cluster_promote.py --min-clusters 5 --max-clusters 30
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

# Path setup
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
os.environ.setdefault("DATABASE_URL", DB_URL)

from backend.db.database import SessionLocal, init_db
from backend.db.models import StrategyKnowledgeDoc
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cluster_promote")

MIN_DOCS_PER_BUCKET = 5
DEFAULT_MIN_CLUSTERS = 5
DEFAULT_MAX_CLUSTERS = 50
TOP_PER_CLUSTER = 3
MIN_QUALITY_FOR_PROMOTION = 0.70
DEPRECATION_QUALITY_THRESHOLD = 0.60


def _build_text(doc: StrategyKnowledgeDoc) -> str:
    """Build a text blob for TF-IDF vectorization."""
    parts = []
    if doc.situation_pattern:
        parts.append(doc.situation_pattern)
    if doc.recommended_action:
        parts.append(doc.recommended_action[:500])
    if doc.rationale:
        parts.append(doc.rationale[:300])
    return " ".join(parts)


def _optimal_k(vectors: np.ndarray, min_k: int, max_k: int) -> int:
    """Determine optimal K using silhouette score or fast heuristic.

    For large buckets (n > 300), uses a fast sqrt-based heuristic to avoid
    expensive silhouette computation. For small/medium buckets, samples
    a few K values and evaluates with silhouette score.
    """
    n_samples = vectors.shape[0]
    max_possible = min(max_k, n_samples - 1)
    min_possible = min(min_k, max_possible - 1)

    if max_possible <= min_possible or max_possible <= 1:
        return max(1, n_samples // 3)

    # Fast heuristic for large buckets: sqrt-based with bounds
    if n_samples > 300:
        return max(min_possible, min(max_possible, int(n_samples ** 0.5) + 3))

    # For small/medium buckets, evaluate a few K values
    import math as _math
    k_candidates = set()
    k_candidates.add(max(2, n_samples // 10))   # ~10% of samples
    k_candidates.add(max(2, n_samples // 5))    # ~20% of samples
    k_candidates.add(max(2, n_samples // 3))    # ~33% of samples
    k_candidates.add(min_possible)
    k_candidates.add(max_possible)
    # Add a few log-spaced points
    log_min = _math.log(max(min_possible, 2))
    log_max = _math.log(max_possible)
    for i in range(5):
        k = int(_math.exp(log_min + (log_max - log_min) * i / 4))
        k = max(2, min(max_possible, k))
        k_candidates.add(k)

    k_candidates = sorted([k for k in k_candidates if min_possible <= k <= max_possible and k < n_samples])

    if len(k_candidates) <= 1:
        return max(2, n_samples // 5)

    best_k = max(2, n_samples // 5)
    best_score = -1.0

    for k in k_candidates:
        try:
            km = KMeans(n_clusters=k, random_state=42, n_init=5)
            labels = km.fit_predict(vectors)
            if len(set(labels)) < 2:
                continue
            # Use sample-based silhouette for buckets > 100
            if n_samples > 100:
                sample_size = min(n_samples, 500)
                indices = np.random.RandomState(42).choice(n_samples, sample_size, replace=False)
                score = silhouette_score(vectors[indices], labels[indices])
            else:
                score = silhouette_score(vectors, labels)
            if score > best_score:
                best_score = score
                best_k = k
        except Exception:
            continue

    return best_k


def _report_bucket(
    role: str,
    doc_type: str,
    n_docs: int,
    n_clusters: int,
    qualities: list[float],
    promoted: list[str],
) -> str:
    """Format a single bucket report line."""
    avg_q = sum(qualities) / len(qualities) if qualities else 0
    min_q = min(qualities) if qualities else 0
    max_q = max(qualities) if qualities else 0
    return (
        f"  {role:16s} | {doc_type:24s} | docs={n_docs:4d} | "
        f"clusters={n_clusters:2d} | promoted={len(promoted)} | "
        f"quality=[{min_q:.2f}-{max_q:.2f}] avg={avg_q:.2f}"
    )


def run_cluster_promotion(
    db,
    *,
    min_clusters: int = DEFAULT_MIN_CLUSTERS,
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Main cluster promotion pipeline. Returns a report dict."""

    # ── Step 1: Fetch all candidate docs ───────────────────────────────
    candidates = (
        db.query(StrategyKnowledgeDoc)
        .filter(StrategyKnowledgeDoc.status == "candidate")
        .all()
    )
    logger.info("Loaded %d candidate documents from DB", len(candidates))

    if not candidates:
        logger.info("No candidates to process.")
        return {"buckets": [], "total_promoted": 0, "total_docs": 0}

    # ── Step 2: Group by (role, doc_type) ─────────────────────────────
    buckets: dict[tuple[str, str], list[StrategyKnowledgeDoc]] = defaultdict(list)
    for doc in candidates:
        key = (doc.role, doc.doc_type or "unknown")
        buckets[key].append(doc)

    logger.info("Grouped into %d (role, doc_type) buckets", len(buckets))

    report_buckets: list[dict[str, Any]] = []
    total_promoted = 0
    all_promoted_ids: list[str] = []
    deprecated_count = 0

    # ── Step 3: Process each bucket ───────────────────────────────────
    for (role, doc_type), docs in sorted(buckets.items()):
        n_docs = len(docs)

        if n_docs < MIN_DOCS_PER_BUCKET:
            logger.debug("Skipping small bucket: %s/%s (%d docs)", role, doc_type, n_docs)
            report_buckets.append({
                "role": role, "doc_type": doc_type, "n_docs": n_docs,
                "n_clusters": 0, "n_promoted": 0,
                "qualities": [d.quality_score for d in docs],
                "skipped": True, "reason": "too_few_docs",
            })
            continue

        # Build text corpus
        texts = [_build_text(doc) for doc in docs]
        qualities = [doc.quality_score for doc in docs]

        # TF-IDF vectorization
        try:
            vectorizer = TfidfVectorizer(
                max_features=1000,
                stop_words=None,
                ngram_range=(1, 2),
                sublinear_tf=True,
            )
            vectors = vectorizer.fit_transform(texts)
        except ValueError:
            logger.warning("TF-IDF failed for bucket %s/%s, skipping", role, doc_type)
            report_buckets.append({
                "role": role, "doc_type": doc_type, "n_docs": n_docs,
                "n_clusters": 0, "n_promoted": 0,
                "qualities": qualities, "skipped": True, "reason": "tfidf_failed",
            })
            continue

        if vectors.shape[0] < 3 or vectors.nnz == 0:
            # Too few features — promote top N by quality, filtered by MIN_QUALITY_FOR_PROMOTION
            docs_sorted = sorted(docs, key=lambda d: d.quality_score, reverse=True)
            promoted = [d for d in docs_sorted[:TOP_PER_CLUSTER * 3]
                       if d.quality_score >= MIN_QUALITY_FOR_PROMOTION]
            if not promoted:
                promoted = docs_sorted[:1]  # Always promote at least 1 if any exist

            report_buckets.append({
                "role": role, "doc_type": doc_type, "n_docs": n_docs,
                "n_clusters": len(promoted), "n_promoted": len(promoted),
                "qualities": qualities, "skipped": False,
                "reason": "top_quality_fallback",
            })
        else:
            # KMeans clustering
            dense = vectors.toarray()
            k = _optimal_k(dense, min_clusters, max_clusters)

            try:
                km = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = km.fit_predict(dense)
            except Exception:
                logger.warning("KMeans failed for %s/%s, using top-N fallback", role, doc_type)
                docs_sorted = sorted(docs, key=lambda d: (d.quality_score, d.confidence), reverse=True)
                promoted = [d for d in docs_sorted[:TOP_PER_CLUSTER * 3]
                           if d.quality_score >= MIN_QUALITY_FOR_PROMOTION]
                if not promoted:
                    promoted = docs_sorted[:1]
                labels = np.zeros(n_docs, dtype=int)
            else:
                # Select Top-3 highest quality docs per cluster
                cluster_docs: dict[int, list[StrategyKnowledgeDoc]] = defaultdict(list)
                for i, doc in enumerate(docs):
                    cluster_id = int(labels[i])
                    cluster_docs[cluster_id].append(doc)
                promoted: list[StrategyKnowledgeDoc] = []
                for cluster_id, cdocs in cluster_docs.items():
                    cdocs_sorted = sorted(cdocs, key=lambda d: d.quality_score, reverse=True)
                    # Take Top-3 per cluster, filtered by quality >= MIN_QUALITY_FOR_PROMOTION
                    for doc in cdocs_sorted[:TOP_PER_CLUSTER]:
                        if doc.quality_score >= MIN_QUALITY_FOR_PROMOTION:
                            promoted.append(doc)

            report_buckets.append({
                "role": role, "doc_type": doc_type, "n_docs": n_docs,
                "n_clusters": k, "n_promoted": len(promoted),
                "qualities": qualities, "skipped": False, "reason": "clustered",
            })

        # ── Promote representatives ───────────────────────────────────
        promoted_ids = set()
        if not dry_run:
            for doc in promoted:
                doc.status = "active"
                promoted_ids.add(doc.id)
            # Deprecate non-selected candidates in this bucket
            bucket_deprecated = 0
            for doc in docs:
                if doc.id not in promoted_ids and doc.status == "candidate":
                    doc.status = "deprecated"
                    bucket_deprecated += 1
            deprecated_count += bucket_deprecated
            logger.info("Bucket %s/%s: promoted %d, deprecated %d non-selected",
                        role, doc_type, len(promoted), bucket_deprecated)
            db.flush()

        bucket_promoted_ids = [doc.id for doc in promoted]
        all_promoted_ids.extend(bucket_promoted_ids)
        total_promoted += len(promoted)

    # ── Step 4: Deprecate low-quality candidates (remaining) ─────────
    for doc in candidates:
        if doc.status == "candidate" and doc.quality_score < DEPRECATION_QUALITY_THRESHOLD:
            if not dry_run:
                doc.status = "deprecated"
            deprecated_count += 1
    if deprecated_count > 0:
        logger.info("Total deprecated: %d (non-selected + low-quality < %.2f)", deprecated_count, DEPRECATION_QUALITY_THRESHOLD)

    # ── Step 5: Commit ────────────────────────────────────────────────
    if not dry_run and (total_promoted > 0 or deprecated_count > 0):
        try:
            db.commit()
            logger.info("Committed %d promotions to DB", total_promoted)
        except Exception as exc:
            db.rollback()
            logger.error("Failed to commit promotions: %s", exc)
            raise

    return {
        "buckets": report_buckets,
        "total_promoted": total_promoted,
        "total_deprecated": deprecated_count,
        "total_docs": len(candidates),
        "all_promoted_ids": all_promoted_ids,
    }


def print_report(report: dict[str, Any]) -> None:
    """Print a structured cluster promotion report."""
    buckets = report.get("buckets", [])
    total_promoted = report.get("total_promoted", 0)
    total_deprecated = report.get("total_deprecated", 0)
    total_docs = report.get("total_docs", 0)

    print()
    print("=" * 80)
    print("  CLUSTER PROMOTION REPORT")
    print("=" * 80)
    print(f"  Total candidates processed:  {total_docs}")
    print(f"  Total promoted to active:    {total_promoted}")
    print(f"  Total deprecated (low qual): {total_deprecated}")
    if total_docs > 0:
        print(f"  Promotion rate:              {total_promoted / total_docs * 100:.1f}%")
    print(f"  Parameters: Top-{TOP_PER_CLUSTER}/cluster, min_quality={MIN_QUALITY_FOR_PROMOTION}, "
          f"deprecate < {DEPRECATION_QUALITY_THRESHOLD}")
    print()

    # Group buckets by role for cleaner display
    by_role: dict[str, list[dict]] = defaultdict(list)
    for b in buckets:
        by_role[b["role"]].append(b)

    print(f"  {'Role':16s} | {'Doc Type':24s} | {'Docs':>4s} | {'Clusters':>8s} | {'Promoted':>8s} | Quality Range")
    print("  " + "-" * 78)

    skipped_count = 0
    for role in sorted(by_role.keys()):
        for i, b in enumerate(by_role[role]):
            qualities = b["qualities"]
            avg_q = sum(qualities) / len(qualities) if qualities else 0
            min_q = min(qualities) if qualities else 0
            max_q = max(qualities) if qualities else 0
            skip_mark = " [SKIP]" if b["skipped"] else ""
            print(
                f"  {role:16s} | {b['doc_type']:24s} | {b['n_docs']:4d} | "
                f"{b['n_clusters']:8d} | {b['n_promoted']:8d} | "
                f"{min_q:.2f}-{max_q:.2f} (avg:{avg_q:.2f}){skip_mark}"
            )
            if b["skipped"]:
                skipped_count += 1

    print("  " + "-" * 78)
    print(f"  Buckets: {len(buckets)} total, {skipped_count} skipped (too few docs)")
    print(f"  Quality minimum for promotion: {MIN_QUALITY_FOR_PROMOTION}")
    print(f"  Deprecation threshold: < {DEPRECATION_QUALITY_THRESHOLD}")
    print("=" * 80)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster-based strategy promotion")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--min-clusters", type=int, default=DEFAULT_MIN_CLUSTERS,
                        help=f"Minimum K for KMeans (default: {DEFAULT_MIN_CLUSTERS})")
    parser.add_argument("--max-clusters", type=int, default=DEFAULT_MAX_CLUSTERS,
                        help=f"Maximum K for KMeans (default: {DEFAULT_MAX_CLUSTERS})")
    args = parser.parse_args()

    if args.min_clusters >= args.max_clusters:
        logger.error("min-clusters must be < max-clusters")
        return 1

    logger.info("Starting cluster-based promotion...")
    logger.info("  min_clusters=%d  max_clusters=%d  dry_run=%s",
                args.min_clusters, args.max_clusters, args.dry_run)

    init_db()
    db = SessionLocal()

    try:
        # Quick connectivity test
        db.execute(text("SELECT 1"))

        report = run_cluster_promotion(
            db,
            min_clusters=args.min_clusters,
            max_clusters=args.max_clusters,
            dry_run=args.dry_run,
        )

        print_report(report)

        if args.dry_run:
            logger.info("DRY RUN complete — no changes were written to DB.")
        else:
            logger.info("Cluster promotion complete. %d docs promoted.", report["total_promoted"])

    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        return 1
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
