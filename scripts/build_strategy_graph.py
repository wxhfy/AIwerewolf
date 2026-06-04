#!/usr/bin/env python3
"""Build strategy graph links using LLM analysis, with incremental DB commits.

Each batch of LLM-discovered relationships is committed to DB immediately
so rate-limit crashes don't lose progress.

Usage:
    python scripts/build_strategy_graph.py              # full run
    python scripts/build_strategy_graph.py --limit 30   # stop after 30 links
    python scripts/build_strategy_graph.py --dry-run    # preview only
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
os.environ.setdefault("DATABASE_URL", DB_URL)

from backend.llm import create_client  # noqa: E402

EDGE_TYPES = ["depends_on", "conflicts_with", "complements", "upgrades_to"]

SYSTEM_PROMPT = """你是一个狼人杀策略分析师。分析以下策略条目之间的关系。

策略关系类型：
- depends_on: 策略B的执行需要策略A作为前置条件
- conflicts_with: 策略A和策略B不能同时使用
- complements: 策略A和策略B配合使用效果更好
- upgrades_to: 策略B是策略A的进阶版本

对于每组策略，找出所有有意义的关联关系。输出JSON数组：
[
  {"source_idx": 0, "target_idx": 3, "edge_type": "depends_on", "rationale": "必须先查验身份才能根据查验结果调整发言策略", "weight": 0.85},
  {"source_idx": 2, "target_idx": 5, "edge_type": "conflicts_with", "rationale": "自刀战术与表水策略矛盾", "weight": 0.90}
]

要求：
1. 只包含有意义的关系，不要为凑数而添加无关关联
2. rationale要用中文简要说明关系原因（10-30字）
3. weight在0.70-0.95之间，根据关系确定性
4. 每条策略最多与2-3条其他策略建立关系
5. 至少找到N/3条关系（N为策略数量）
6. 同一对策略之间只选最显著的一种关系类型"""


def fetch_docs(limit: int = 600) -> list[dict]:
    """Fetch active strategy docs from PostgreSQL."""
    import psycopg2
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT id, role, phase, situation_pattern, recommended_action, rationale,
                  doc_type, quality_score, trigger_conditions
           FROM strategy_knowledge_docs
           WHERE status = 'active'
           ORDER BY quality_score DESC
           LIMIT %s""",
        (limit,),
    )
    rows = []
    for row in cur.fetchall():
        rows.append({
            "id": row[0], "role": row[1], "phase": row[2],
            "situation": str(row[3] or ""), "action": str(row[4] or ""),
            "rationale": str(row[5] or ""), "doc_type": str(row[6] or ""),
            "quality": float(row[7] or 0.8), "triggers": row[8] or [],
        })
    cur.close()
    conn.close()
    logger.info("Fetched %d active docs", len(rows))
    return rows


def format_doc(doc: dict, idx: int) -> str:
    """Format a single doc for LLM prompt."""
    return (
        f"[{idx}] role={doc['role']} phase={doc['phase']} type={doc['doc_type']}\n"
        f"    situation: {doc['situation'][:120]}\n"
        f"    action: {doc['action'][:150]}\n"
        f"    rationale: {doc['rationale'][:100]}"
    )


def insert_links(conn, links: list[dict]) -> int:
    """Insert links into strategy_graph_links. Returns count inserted."""
    if not links:
        return 0
    cur = conn.cursor()
    count = 0
    for link in links:
        try:
            cur.execute(
                """INSERT INTO strategy_graph_links
                   (id, source_id, source_type, target_id, target_type, edge_type, weight, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    str(uuid4()),
                    link["source_id"],
                    link.get("source_type", "strategy_knowledge_doc"),
                    link["target_id"],
                    link.get("target_type", "strategy_knowledge_doc"),
                    link["edge_type"],
                    link.get("weight", 0.8),
                    json.dumps(link.get("metadata", {}), ensure_ascii=False),
                ),
            )
            count += cur.rowcount
        except Exception as e:
            logger.warning("Failed insert %s->%s: %s",
                           link.get("source_id", "?")[:12],
                           link.get("target_id", "?")[:12], e)
    conn.commit()
    cur.close()
    return count


def get_existing_pairs(conn) -> set:
    """Get set of (source_id, target_id) pairs already in graph."""
    cur = conn.cursor()
    cur.execute("SELECT source_id, target_id FROM strategy_graph_links")
    pairs = {(row[0], row[1]) for row in cur.fetchall()}
    cur.close()
    return pairs


def group_by_role(docs: list[dict]) -> dict[str, list[dict]]:
    """Group docs by role."""
    groups: dict[str, list[dict]] = {}
    for d in docs:
        groups.setdefault(d["role"], []).append(d)
    return groups


def call_llm(client, prompt: str, max_retries: int = 3) -> str | None:
    """Call LLM with retries."""
    for attempt in range(max_retries):
        try:
            response = client.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=4096,
                thinking=False,
            )
            return client.parse_response(response).strip()
        except Exception as e:
            err = str(e)
            if "429" in err:
                wait = min(30, (2 ** attempt) * 5 + random.uniform(1, 3))
                logger.warning("Rate limited, waiting %.1fs...", wait)
                time.sleep(wait)
            elif attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error("LLM call failed: %s", err[:200])
    return None


def parse_links(raw: str, docs_in_batch: list[dict], existing_pairs: set) -> list[dict]:
    """Parse LLM response into validated link dicts."""
    text = raw.strip()

    # Strip code fences
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    # Find JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]

    try:
        suggestions = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract individual objects
        objs = re.findall(r'\{[^{}]*\}', text)
        suggestions = []
        for o in objs:
            try:
                suggestions.append(json.loads(o))
            except json.JSONDecodeError:
                pass

    links = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        si = s.get("source_idx") or s.get("source_index") or s.get("source")
        ti = s.get("target_idx") or s.get("target_index") or s.get("target")
        if si is None or ti is None:
            continue
        try:
            si, ti = int(si), int(ti)
        except (ValueError, TypeError):
            continue
        if si < 0 or ti < 0 or si >= len(docs_in_batch) or ti >= len(docs_in_batch):
            continue
        if si == ti:
            continue

        edge_type = str(s.get("edge_type", "") or s.get("type", "")).strip().lower()
        if edge_type not in EDGE_TYPES:
            continue

        src_id = docs_in_batch[si]["id"]
        tgt_id = docs_in_batch[ti]["id"]
        if (src_id, tgt_id) in existing_pairs:
            continue

        weight = float(s.get("weight", 0.8))
        weight = max(0.5, min(1.0, weight))

        rationale = str(s.get("rationale", "") or s.get("reason", "")).strip()
        if not rationale or len(rationale) < 5:
            continue

        links.append({
            "source_id": src_id,
            "target_id": tgt_id,
            "source_type": "strategy_knowledge_doc",
            "target_type": "strategy_knowledge_doc",
            "edge_type": edge_type,
            "weight": weight,
            "metadata": {"rationale": rationale, "confidence": weight},
        })
        existing_pairs.add((src_id, tgt_id))

    return links


def process_role_batch(
    client, conn, docs: list[dict], role_name: str, existing_pairs: set,
    batch_size: int = 25,
) -> int:
    """Process docs for one role in batches. Returns total new links."""
    total_links = 0
    num_batches = math.ceil(len(docs) / batch_size)

    for batch_idx in range(num_batches):
        batch_docs = docs[batch_idx * batch_size:(batch_idx + 1) * batch_size]
        if len(batch_docs) < 3:
            continue

        # Format docs for prompt
        doc_str = "\n\n".join(format_doc(d, i) for i, d in enumerate(batch_docs))
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"以下是{role_name}角色的{len(batch_docs)}条策略：\n\n{doc_str}\n\n"
            f"请分析这些策略之间的关系。至少找出{max(2, len(batch_docs)//4)}条有效关系。\n"
            f"直接输出JSON数组：\n["
        )

        raw = call_llm(client, prompt)
        if raw is None:
            logger.warning("  %s batch %d/%d: LLM failed", role_name, batch_idx + 1, num_batches)
            continue

        links = parse_links(raw, batch_docs, existing_pairs)
        if links:
            inserted = insert_links(conn, links)
            total_links += inserted
            logger.info("  %s batch %d/%d: %d links (total=%d)",
                        role_name, batch_idx + 1, num_batches, inserted, total_links)
        else:
            logger.info("  %s batch %d/%d: 0 valid links parsed", role_name, batch_idx + 1, num_batches)

        if batch_idx < num_batches - 1:
            time.sleep(random.uniform(2.0, 4.0))

    return total_links


def process_cross_role_batches(
    client, conn, role_groups: dict[str, list[dict]], existing_pairs: set,
    samples_per_role: int = 20,
) -> int:
    """Create cross-role batches mixing docs from different roles."""
    total_links = 0
    roles = list(role_groups.keys())
    # Create mixed batches of 2-3 roles each
    cross_batches = []
    for i in range(0, len(roles), 3):
        batch_roles = roles[i:i + 3]
        batch_docs = []
        for r in batch_roles:
            docs = role_groups[r][:samples_per_role]
            batch_docs.extend(docs)
        if len(batch_docs) >= 5:
            cross_batches.append((batch_roles, batch_docs))

    for batch_idx, (batch_roles, batch_docs) in enumerate(cross_batches):
        role_label = "+".join(batch_roles[:2])
        doc_str = "\n\n".join(format_doc(d, i) for i, d in enumerate(batch_docs))
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"以下是{role_label}等角色的{len(batch_docs)}条交叉策略：\n\n{doc_str}\n\n"
            f"重点寻找跨角色的关系：冲突（狼人策略vs好人策略）、互补（好人之间配合）、依赖关系。\n"
            f"至少找出{max(3, len(batch_docs)//5)}条有效关系。\n"
            f"直接输出JSON数组：\n["
        )

        raw = call_llm(client, prompt)
        if raw is None:
            continue

        links = parse_links(raw, batch_docs, existing_pairs)
        if links:
            inserted = insert_links(conn, links)
            total_links += inserted
            logger.info("  cross-role %d/%d (%s): %d links (total=%d)",
                        batch_idx + 1, len(cross_batches), role_label, inserted, total_links)

        time.sleep(random.uniform(2.0, 4.0))

    return total_links


def main():
    ap = argparse.ArgumentParser(description="Build strategy knowledge graph")
    ap.add_argument("--limit", type=int, default=0, help="Stop after N total links")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--doc-limit", type=int, default=600, help="Max docs to load")
    args = ap.parse_args()

    # Load docs
    docs = fetch_docs(limit=args.doc_limit)
    if args.dry_run:
        roles = group_by_role(docs)
        print(f"Loaded {len(docs)} docs across {len(roles)} roles")
        for r, dlist in sorted(roles.items(), key=lambda x: -len(x[1])):
            print(f"  {r}: {len(dlist)} docs, ~{math.ceil(len(dlist)/args.batch_size)} batches")
        return 0

    # Group by role
    role_groups = group_by_role(docs)
    logger.info("Processing %d docs across %d roles", len(docs), len(role_groups))

    # Create LLM client
    client = create_client()
    logger.info("LLM: provider=%s model=%s",
                getattr(client, "provider", "?"), getattr(client, "model", "?"))

    # Connect to DB
    import psycopg2
    conn = psycopg2.connect(DB_URL)
    existing_pairs = get_existing_pairs(conn)
    logger.info("Existing graph links: %d", len(existing_pairs))

    total_links = 0
    target = args.limit or 100

    # Phase 1: Within-role analysis (major roles first)
    logger.info("\n=== Phase 1: Within-role analysis ===")
    priority_roles = ["Werewolf", "Seer", "Witch", "Villager", "Hunter", "Guard", "WhiteWolfKing"]
    other_roles = [r for r in role_groups if r not in priority_roles and len(role_groups[r]) >= 3]
    all_roles = priority_roles + other_roles

    for role in all_roles:
        if role not in role_groups:
            continue
        if args.limit and total_links >= args.limit:
            break
        role_docs = role_groups[role]
        if len(role_docs) < 3:
            continue
        logger.info("\n--- %s (%d docs) ---", role, len(role_docs))
        added = process_role_batch(
            client, conn, role_docs, role, existing_pairs,
            batch_size=args.batch_size,
        )
        total_links += added
        time.sleep(random.uniform(1.5, 3.0))

    # Phase 2: Cross-role analysis
    if not args.limit or total_links < args.limit:
        logger.info("\n=== Phase 2: Cross-role analysis ===")
        added = process_cross_role_batches(
            client, conn, role_groups, existing_pairs,
            samples_per_role=min(20, args.batch_size),
        )
        total_links += added

    # Summary
    cur = conn.cursor()
    cur.execute("SELECT edge_type, count(*) FROM strategy_graph_links GROUP BY edge_type")
    by_type = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()
    conn.close()

    print("\n" + "=" * 50)
    print(f"  Strategy Graph Build Complete")
    print(f"  Total links created: {total_links}")
    print(f"  Existing links: {sum(by_type.values())}")
    for et in EDGE_TYPES:
        print(f"    {et}: {by_type.get(et, 0)}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
