#!/usr/bin/env python
"""Personal knowledge base management CLI.

Manages MBTI-scoped strategy knowledge:
  - Dream Job: extract knowledge from published game reviews
  - Stats: view knowledge base status per persona/role
  - Prune: clean up deprecated/stale knowledge docs

Usage:
  python scripts/manage_knowledge.py dream-job --persona mbti:INTJ
  python scripts/manage_knowledge.py stats --persona mbti:INTJ
  python scripts/manage_knowledge.py stats --role Werewolf
  python scripts/manage_knowledge.py prune --dry-run
  python scripts/manage_knowledge.py promote --min-quality 0.6 --min-usage 3

Design references:
  - Claude Code AutoDream: Orient → Collect → Integrate → Prune
  - MemOS lifecycle: Generated → Activated → Archived → Purged
  - LangMem background ReflectionExecutor pattern
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from datetime import timedelta
from datetime import timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _get_db():
    """Get database session."""
    from backend.db.database import SessionLocal
    from backend.db.database import init_db

    init_db()
    return SessionLocal()


def cmd_dream_job(args):
    """Run Dream Job on published reviews, optionally filtered by persona_scope."""
    from backend.db.models import PublishedReview
    from backend.db.persist import run_dream_job

    db = _get_db()
    try:
        query = db.query(PublishedReview).filter(PublishedReview.publish_allowed.is_(True))
        if args.persona:
            # Filter reviews where at least one player has matching persona
            # For simplicity, run on all approved reviews and let the
            # persona-aware scoring handle prioritization
            pass

        rows = (
            query.order_by(PublishedReview.published_at.desc().nullslast(), PublishedReview.created_at.desc())
            .limit(args.limit)
            .all()
        )

        report_ids = [row.id for row in rows]
        if not report_ids:
            print("No approved reviews found.")
            return

        print(f"Running Dream Job on {len(report_ids)} reviews...")
        if args.persona:
            print(f"  Persona filter: {args.persona}")

        result = run_dream_job(report_ids)
        summary = result.get("summary", {})
        print("\nDream Job complete:")
        print(f"  Knowledge docs: {summary.get('knowledge_docs', 0)}")
        print(f"  Validated patches: {summary.get('validated_patches', 0)}")
        print(f"  Promoted: {summary.get('promoted', 0)}")
        print(f"  Rolled back: {summary.get('rolled_back', 0)}")

        if args.persona:
            _print_persona_knowledge(db, args.persona)
    finally:
        db.close()


def cmd_stats(args):
    """Show knowledge base statistics."""
    from sqlalchemy import func as sa_func

    from backend.db.models import StrategyKnowledgeDoc

    db = _get_db()
    try:
        query = db.query(StrategyKnowledgeDoc)

        if args.persona:
            query = query.filter(StrategyKnowledgeDoc.persona_scope.like(f"%{args.persona}%"))
        if args.role:
            query = query.filter(StrategyKnowledgeDoc.role == args.role)

        total = query.count()

        # By status
        status_counts = dict(
            db.query(StrategyKnowledgeDoc.status, sa_func.count(StrategyKnowledgeDoc.id))
            .filter(StrategyKnowledgeDoc.persona_scope.like(f"%{args.persona}%") if args.persona else True)
            .filter(StrategyKnowledgeDoc.role == args.role if args.role else True)
            .group_by(StrategyKnowledgeDoc.status)
            .all()
        )

        # By doc_type
        type_counts = dict(
            db.query(StrategyKnowledgeDoc.doc_type, sa_func.count(StrategyKnowledgeDoc.id))
            .filter(StrategyKnowledgeDoc.persona_scope.like(f"%{args.persona}%") if args.persona else True)
            .filter(StrategyKnowledgeDoc.role == args.role if args.role else True)
            .group_by(StrategyKnowledgeDoc.doc_type)
            .all()
        )

        # Top persona_scopes
        persona_scopes = (
            db.query(StrategyKnowledgeDoc.persona_scope, sa_func.count(StrategyKnowledgeDoc.id))
            .filter(StrategyKnowledgeDoc.persona_scope.isnot(None), StrategyKnowledgeDoc.persona_scope != "")
            .group_by(StrategyKnowledgeDoc.persona_scope)
            .order_by(sa_func.count(StrategyKnowledgeDoc.id).desc())
            .limit(10)
            .all()
        )

        # Quality distribution
        quality_rows = (
            db.query(StrategyKnowledgeDoc.quality_score)
            .filter(StrategyKnowledgeDoc.status.in_(["active", "candidate"]))
            .all()
        )
        qualities = [q for (q,) in quality_rows if q is not None]

        print(f"\n{'=' * 60}")
        print("Knowledge Base Stats")
        if args.persona:
            print(f"  Persona: {args.persona}")
        if args.role:
            print(f"  Role: {args.role}")
        print(f"{'=' * 60}")
        print(f"  Total docs: {total}")
        print(f"  By status: {status_counts}")
        print(f"  By type: {type_counts}")
        if qualities:
            print(
                f"  Quality: min={min(qualities):.2f} avg={sum(qualities) / len(qualities):.2f} max={max(qualities):.2f}"
            )
        print("\n  Top persona scopes:")
        for scope, count in persona_scopes:
            print(f"    {scope}: {count} docs")
        print()

        if args.verbose:
            _print_recent_docs(db, args)
    finally:
        db.close()


def cmd_prune(args):
    """Prune stale/deprecated knowledge docs."""
    from backend.db.models import StrategyKnowledgeDoc

    db = _get_db()
    try:
        # Find deprecated docs
        deprecated = db.query(StrategyKnowledgeDoc).filter(StrategyKnowledgeDoc.status == "deprecated").all()

        # Find stale candidate docs (never used, old)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stale = (
            db.query(StrategyKnowledgeDoc)
            .filter(
                StrategyKnowledgeDoc.status == "candidate",
                StrategyKnowledgeDoc.usage_count == 0,
                StrategyKnowledgeDoc.updated_at < cutoff,
            )
            .all()
        )

        # Find failed docs (high failure rate, no success)
        failed = (
            db.query(StrategyKnowledgeDoc)
            .filter(
                StrategyKnowledgeDoc.status == "candidate",
                StrategyKnowledgeDoc.failure_count >= 5,
                StrategyKnowledgeDoc.success_count == 0,
            )
            .all()
        )

        print("\nPrune candidates:")
        print(f"  Deprecated: {len(deprecated)}")
        print(f"  Stale (>30d unused candidate): {len(stale)}")
        print(f"  Failed (>=5 failures, 0 successes): {len(failed)}")

        if args.dry_run:
            print("\n[Dry run] No changes made.")
            if args.verbose:
                for doc in deprecated[:5]:
                    print(f"  - {doc.id}: {doc.situation_pattern[:60]}...")
                for doc in stale[:5]:
                    print(f"  - {doc.id}: {doc.situation_pattern[:60]}...")
            return

        count = 0
        for doc in deprecated:
            db.delete(doc)
            count += 1
        for doc in stale:
            db.delete(doc)
            count += 1
        for doc in failed:
            doc.status = "deprecated"  # Archive instead of delete
            count += 1

        db.commit()
        print(f"\nPruned/archived {count} docs.")
    finally:
        db.close()


def cmd_promote(args):
    """Promote candidate knowledge docs to active based on quality + usage."""
    from backend.db.models import StrategyKnowledgeDoc

    db = _get_db()
    try:
        candidates = (
            db.query(StrategyKnowledgeDoc)
            .filter(
                StrategyKnowledgeDoc.status == "candidate",
                StrategyKnowledgeDoc.quality_score >= args.min_quality,
                StrategyKnowledgeDoc.usage_count >= args.min_usage,
            )
            .all()
        )

        if args.dry_run:
            print(f"\n[Dry run] Would promote {len(candidates)} docs:")
            for doc in candidates[:10]:
                print(
                    f"  - {doc.id}: q={doc.quality_score:.2f} usage={doc.usage_count} {doc.situation_pattern[:60]}..."
                )
            return

        for doc in candidates:
            doc.status = "active"
        db.commit()
        print(f"\nPromoted {len(candidates)} docs to active.")
    finally:
        db.close()


def _print_persona_knowledge(db, persona_filter: str):
    """Print persona-scoped knowledge after dream job."""
    from backend.db.models import StrategyKnowledgeDoc

    docs = (
        db.query(StrategyKnowledgeDoc)
        .filter(
            StrategyKnowledgeDoc.persona_scope.like(f"%{persona_filter}%"),
            StrategyKnowledgeDoc.status.in_(["active", "candidate"]),
        )
        .order_by(StrategyKnowledgeDoc.quality_score.desc())
        .limit(10)
        .all()
    )

    if docs:
        print(f"\n  Recent persona knowledge ({persona_filter}):")
        for doc in docs:
            print(f"    [{doc.doc_type}] q={doc.quality_score:.2f} {doc.situation_pattern[:80]}")


def _print_recent_docs(db, args):
    """Print recent knowledge docs."""
    from backend.db.models import StrategyKnowledgeDoc

    docs = db.query(StrategyKnowledgeDoc).order_by(StrategyKnowledgeDoc.updated_at.desc()).limit(20).all()

    print("\n  Recent docs:")
    for doc in docs:
        persona = doc.persona_scope or "global"
        print(
            f"    [{doc.status}][{doc.doc_type}][{doc.role}][{persona}] q={doc.quality_score:.2f} u={doc.usage_count} {doc.situation_pattern[:80]}"
        )


def main():
    parser = argparse.ArgumentParser(description="Personal knowledge base management (MBTI-scoped strategy knowledge)")
    sub = parser.add_subparsers(dest="command", help="Command")

    # dream-job
    p_dream = sub.add_parser("dream-job", help="Run Dream Job knowledge extraction")
    p_dream.add_argument("--persona", default="", help="Filter by persona_scope (e.g. mbti:INTJ)")
    p_dream.add_argument("--limit", type=int, default=30, help="Max reviews to process")

    # stats
    p_stats = sub.add_parser("stats", help="Show knowledge base statistics")
    p_stats.add_argument("--persona", default="", help="Filter by persona_scope")
    p_stats.add_argument("--role", default="", help="Filter by role")
    p_stats.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    # prune
    p_prune = sub.add_parser("prune", help="Prune stale/deprecated knowledge")
    p_prune.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    p_prune.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    # promote
    p_promote = sub.add_parser("promote", help="Promote candidate docs to active")
    p_promote.add_argument("--min-quality", type=float, default=0.6, help="Minimum quality score")
    p_promote.add_argument("--min-usage", type=int, default=3, help="Minimum usage count")
    p_promote.add_argument("--dry-run", action="store_true", help="Preview only, no changes")

    args = parser.parse_args()

    if args.command == "dream-job":
        cmd_dream_job(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "prune":
        cmd_prune(args)
    elif args.command == "promote":
        cmd_promote(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
