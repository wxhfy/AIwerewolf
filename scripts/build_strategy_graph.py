#!/usr/bin/env python3
"""
Build strategy graph links by analyzing strategy knowledge docs with LLM.

Finds relationships (depends_on, conflicts_with, complements, upgrades_to)
between strategy documents and populates the strategy_graph_links table.

Usage:
    python scripts/build_strategy_graph.py [--dry-run] [--limit N] [--role ROLE]

The script reads all active + candidate strategy_knowledge_docs, groups them
by role, and uses LLM batch processing to identify meaningful relationships.
Results are written to the strategy_graph_links table with deduplication.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from collections import defaultdict
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"

BATCH_SIZE = 25  # docs per LLM call
MIN_RELATIONSHIPS_TARGET = 100
MAX_RELATIONSHIPS_TARGET = 150

RATE_LIMIT_SLEEP_MIN = 1.0
RATE_LIMIT_SLEEP_MAX = 2.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0

# Doc types with high strategic content — prioritized for graph building
PRIORITY_DOC_TYPES = [
    "role_strategy",
    "strategy_suggestion",
    "good_play",
    "bad_case_lesson",
    "counterfactual_lesson",
    "advanced_technique",
]

# Roles with enough docs for meaningful intra-role relationships
MAJOR_ROLES = [
    "Werewolf",
    "Seer",
    "Witch",
    "Villager",
    "Guard",
    "Hunter",
    "WhiteWolfKing",
    "Cupid",
    "Knight",
    "Idiot",
    "WolfBeauty",
    "global",
]

# Cross-role pairs for targeted analysis (conflicts / counters)
CROSS_ROLE_PAIRS = [
    ("Werewolf", "Seer"),
    ("Werewolf", "Witch"),
    ("Werewolf", "Guard"),
    ("Werewolf", "Villager"),
    ("Werewolf", "Hunter"),
    ("Seer", "Witch"),
    ("WhiteWolfKing", "Werewolf"),
    ("Cupid", "Werewolf"),
    ("Cupid", "Villager"),
    ("Werewolf", "global"),
    ("Seer", "global"),
    ("Witch", "global"),
]

# Edge types
EDGE_DEPENDS_ON = "depends_on"
EDGE_CONFLICTS_WITH = "conflicts_with"
EDGE_COMPLEMENTS = "complements"
EDGE_UPGRADES_TO = "upgrades_to"

ALL_EDGE_TYPES = [EDGE_DEPENDS_ON, EDGE_CONFLICTS_WITH, EDGE_COMPLEMENTS, EDGE_UPGRADES_TO]

# LLM prompt templates
SYSTEM_PROMPT = """You are a game strategy analyst for Werewolf (狼人杀). You analyze strategy documents and identify relationships between them.

There are 4 relationship types:
1. "depends_on": Strategy A is a prerequisite for strategy B (B assumes A has been executed)
2. "conflicts_with": Strategy A and B cannot be used together (they recommend opposing actions in the same situation)
3. "complements": Strategy A and B work better together (synergistic, can be combined)
4. "upgrades_to": Strategy B is an advanced/improved version of strategy A (similar goal, B is better)

For each pair of strategies, analyze whether a relationship exists. Only output relationships where you are reasonably confident (confidence >= 0.6). Do NOT output relationships for every pair — only the meaningful ones.

Focus especially on:
- Within-role: strategies for the same role that build on each other or offer alternatives
- Cross-role: strategies from different roles that counter or depend on each other
- Global strategies that apply to specific role strategies

Output ONLY a JSON array of objects. Each object must have:
- source_id: the ID of the source strategy document
- target_id: the ID of the target strategy document
- edge_type: one of "depends_on", "conflicts_with", "complements", "upgrades_to"
- weight: float 0-1, how strong the relationship is
- rationale: string explanation (must be non-empty, max 200 chars)

Example output:
```json
[
  {
    "source_id": "abc123",
    "target_id": "def456",
    "edge_type": "depends_on",
    "weight": 0.85,
    "rationale": "Strategy B assumes the player has already executed strategy A's night action"
  }
]
```"""


def _build_user_prompt(docs: list[dict], context_hint: str) -> str:
    """Build a user prompt listing strategy documents for relationship analysis."""
    lines = [
        context_hint,
        "",
        "Below are strategy documents. Each has an ID, role, type, and content.",
        "Analyze them and output relationships as JSON.",
        "",
        "DOCUMENTS:",
        "=" * 60,
    ]
    for i, doc in enumerate(docs, 1):
        content = _summarize_doc(doc)
        lines.append(
            f"[{i}] id={doc['id']} | role={doc['role']} | type={doc['doc_type']}"
        )
        lines.append(f"    content: {content}")
        lines.append("")
    lines.append("OUTPUT (JSON array only):")
    return "\n".join(lines)


def _summarize_doc(doc: dict) -> str:
    """Build a compact content summary from strategy doc fields."""
    parts = []
    if doc.get("recommended_action"):
        parts.append(f"Action: {doc['recommended_action'][:300]}")
    if doc.get("rationale"):
        parts.append(f"Rationale: {doc['rationale'][:300]}")
    if doc.get("avoid_action"):
        parts.append(f"Avoid: {doc['avoid_action'][:200]}")
    if doc.get("situation_pattern"):
        parts.append(f"Situation: {doc['situation_pattern'][:200]}")
    if doc.get("phase"):
        parts.append(f"Phase: {doc['phase']}")
    if doc.get("tags"):
        try:
            tags = json.loads(doc["tags"]) if isinstance(doc["tags"], str) else doc["tags"]
            if isinstance(tags, list) and tags:
                parts.append(f"Tags: {', '.join(str(t) for t in tags[:8])}")
        except (json.JSONDecodeError, TypeError):
            pass
    if doc.get("doc_type"):
        parts.append(f"Type: {doc['doc_type']}")
    result = " | ".join(parts)
    if len(result) > 800:
        result = result[:797] + "..."
    return result


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(DB_URL)


def fetch_docs(conn, doc_types: Optional[list[str]] = None,
               roles: Optional[list[str]] = None) -> list[dict]:
    """Fetch strategy docs from the database."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    query = """
        SELECT id, role, doc_type, status, phase,
               recommended_action, avoid_action, rationale,
               situation_pattern, tags
        FROM strategy_knowledge_docs
        WHERE status IN ('active', 'candidate')
    """
    params: list = []
    if doc_types:
        placeholders = ",".join(["%s"] * len(doc_types))
        query += f" AND doc_type IN ({placeholders})"
        params.extend(doc_types)
    if roles:
        placeholders = ",".join(["%s"] * len(roles))
        query += f" AND role IN ({placeholders})"
        params.extend(roles)
    query += " ORDER BY role, doc_type"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def fetch_existing_pairs(conn) -> set[tuple]:
    """Fetch existing (source_id, target_id, edge_type) triples for dedup."""
    cur = conn.cursor()
    cur.execute("SELECT source_id, target_id, edge_type FROM strategy_graph_links")
    rows = cur.fetchall()
    cur.close()
    return set(rows)


def insert_links(conn, links: list[dict]) -> int:
    """Insert links into strategy_graph_links. Returns count inserted."""
    if not links:
        return 0
    cur = conn.cursor()
    count = 0
    for link in links:
        try:
            cur.execute(
                """
                INSERT INTO strategy_graph_links
                    (id, source_id, source_type, target_id, target_type,
                     edge_type, weight, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    link["source_id"],
                    link["source_type"],
                    link["target_id"],
                    link["target_type"],
                    link["edge_type"],
                    link["weight"],
                    json.dumps(link.get("metadata", {})),
                ),
            )
            count += cur.rowcount
        except Exception as e:
            logger.warning("Failed to insert link %s -> %s: %s",
                           link.get("source_id", "?")[:12],
                           link.get("target_id", "?")[:12], e)
    conn.commit()
    cur.close()
    return count


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def create_llm_client():
    """Create an LLM client using the project's standard factory."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend.llm import create_client
    client = create_client()
    logger.info("LLM client created: provider=%s model=%s",
                getattr(client, "provider", "unknown"),
                getattr(client, "model", "unknown"))
    return client


def call_llm(client, system_prompt: str, user_prompt: str,
             temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Call the LLM and return the text content."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = client.chat_sync(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = client.parse_response(response)
    usage = response.get("usage", {})
    latency = response.get("_latency_ms", 0)
    logger.debug("LLM call: %d prompt tokens, %d completion tokens, %d ms",
                 usage.get("prompt_tokens", 0),
                 usage.get("completion_tokens", 0),
                 latency)
    return content


def call_llm_with_retry(client, system_prompt: str, user_prompt: str,
                        temperature: float = 0.3,
                        max_tokens: int = 4096) -> str:
    """Call LLM with retry and exponential backoff."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return call_llm(client, system_prompt, user_prompt,
                            temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning("LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                               attempt, MAX_RETRIES, e, wait)
                time.sleep(wait)
            else:
                logger.error("LLM call failed after %d attempts: %s", MAX_RETRIES, e)
    raise last_error  # type: ignore[misc]


def extract_json(text: str) -> list[dict]:
    """Extract and parse JSON array from LLM response text."""
    # Try to find JSON in code blocks
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # Try direct JSON parse
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("relationships"), list):
            return parsed["relationships"]
        if isinstance(parsed, dict) and isinstance(parsed.get("links"), list):
            return parsed["links"]
        if isinstance(parsed, dict):
            # Maybe it's a single relationship
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Try to find JSON array with regex
    array_match = re.search(r"\[[\s\S]*\]", text)
    if array_match:
        try:
            parsed = json.loads(array_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try line-by-line JSON objects
    lines = text.strip().split("\n")
    objects = []
    for line in lines:
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if "source_id" in obj and "target_id" in obj:
                    objects.append(obj)
            except json.JSONDecodeError:
                continue
    if objects:
        return objects

    logger.warning("Could not extract JSON from LLM response (first 300 chars): %s",
                   text[:300])
    return []


def validate_link(link: dict, valid_ids: set[str]) -> Optional[dict]:
    """Validate and normalize a single link. Returns None if invalid."""
    required = ["source_id", "target_id", "edge_type"]
    for field in required:
        if field not in link:
            return None

    source_id = link["source_id"]
    target_id = link["target_id"]
    edge_type = link["edge_type"]

    # Check IDs exist in our doc set
    if source_id not in valid_ids or target_id not in valid_ids:
        return None

    # Check edge type
    if edge_type not in ALL_EDGE_TYPES:
        return None

    # Self-loops are invalid
    if source_id == target_id:
        return None

    weight = float(link.get("weight", 0.7))
    weight = max(0.0, min(1.0, weight))

    rationale = str(link.get("rationale", link.get("reason", "")))[:500]
    if not rationale.strip():
        return None

    confidence = float(link.get("confidence", link.get("metadata", {}).get("confidence", weight)))
    confidence = max(0.0, min(1.0, confidence))

    return {
        "source_id": source_id,
        "source_type": "strategy_knowledge_doc",
        "target_id": target_id,
        "target_type": "strategy_knowledge_doc",
        "edge_type": edge_type,
        "weight": round(weight, 4),
        "metadata": {
            "rationale": rationale,
            "confidence": round(confidence, 4),
        },
    }


def dedup_links(raw_links: list[dict], valid_ids: set[str],
                existing_pairs: set[tuple]) -> list[dict]:
    """Validate and deduplicate links."""
    validated = []
    seen = set()

    for link in raw_links:
        valid = validate_link(link, valid_ids)
        if valid is None:
            continue

        key = (valid["source_id"], valid["target_id"], valid["edge_type"])
        if key in seen:
            continue
        if key in existing_pairs:
            continue
        seen.add(key)
        validated.append(valid)

    return validated


# ---------------------------------------------------------------------------
# Batch strategies
# ---------------------------------------------------------------------------


def create_batches(docs: list[dict], batch_size: int = BATCH_SIZE) -> list[list[dict]]:
    """Split docs into batches of roughly equal size."""
    batches = []
    for i in range(0, len(docs), batch_size):
        batches.append(docs[i:i + batch_size])
    return batches


def create_mixed_batches(docs_by_role: dict[str, list[dict]],
                         batch_size: int = BATCH_SIZE) -> list[list[dict]]:
    """Create batches that mix docs from different roles (for cross-role discovery)."""
    # Shuffle: take one doc from each role in round-robin order
    roles = sorted(docs_by_role.keys())
    all_docs = []
    role_indices = {r: 0 for r in roles}

    max_per_role = max(len(docs_by_role[r]) for r in roles) if roles else 0
    for _ in range(max_per_role):
        for role in roles:
            idx = role_indices[role]
            if idx < len(docs_by_role[role]):
                all_docs.append(docs_by_role[role][idx])
                role_indices[role] += 1

    return create_batches(all_docs, batch_size)


def build_context_hint_for_batch(batch: list[dict]) -> str:
    """Build a context hint describing the batch."""
    roles = sorted(set(d["role"] for d in batch))
    types = sorted(set(d["doc_type"] for d in batch))
    role_str = ", ".join(roles[:8])
    if len(roles) > 8:
        role_str += f" (+{len(roles) - 8} more)"
    type_str = ", ".join(types[:5])
    if len(types) > 5:
        type_str += f" (+{len(types) - 5} more)"

    return (
        f"You are analyzing {len(batch)} strategy documents across roles [{role_str}] "
        f"and types [{type_str}]. Find ALL meaningful relationships "
        f"({', '.join(ALL_EDGE_TYPES)}) among these documents. "
        f"Output ONLY a JSON array."
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def stats_by_edge_type(links: list[dict]) -> dict[str, int]:
    """Count links by edge type."""
    counts: dict[str, int] = defaultdict(int)
    for link in links:
        counts[link["edge_type"]] += 1
    return dict(counts)


def stats_by_role_pair(links: list[dict], docs_by_id: dict[str, dict]) -> dict[str, int]:
    """Count links by role pair (role_a <-> role_b)."""
    counts: dict[str, int] = defaultdict(int)
    for link in links:
        src_doc = docs_by_id.get(link["source_id"], {})
        tgt_doc = docs_by_id.get(link["target_id"], {})
        role_a = src_doc.get("role", "?")
        role_b = tgt_doc.get("role", "?")
        pair = f"{role_a} <-> {role_b}"
        counts[pair] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def print_summary(links: list[dict], docs_by_id: dict[str, dict]):
    """Print a summary of the generated links."""
    print("\n" + "=" * 70)
    print("  STRATEGY GRAPH BUILD — SUMMARY")
    print("=" * 70)
    print(f"  Total links created: {len(links)}")

    print("\n  Breakdown by edge_type:")
    print("  " + "-" * 40)
    edge_counts = stats_by_edge_type(links)
    for et in ALL_EDGE_TYPES:
        count = edge_counts.get(et, 0)
        bar = "#" * min(count, 50)
        print(f"  {et:20s} | {count:5d} {bar}")
    other = sum(v for k, v in edge_counts.items() if k not in ALL_EDGE_TYPES)
    if other:
        print(f"  {'(other)':20s} | {other:5d}")

    print("\n  Top role pairs:")
    print("  " + "-" * 40)
    pair_counts = stats_by_role_pair(links, docs_by_id)
    for pair, count in list(pair_counts.items())[:15]:
        print(f"  {pair:35s} | {count:4d}")

    # Sample links
    print("\n  Sample links (first 5):")
    print("  " + "-" * 40)
    for link in links[:5]:
        src = docs_by_id.get(link["source_id"], {})
        tgt = docs_by_id.get(link["target_id"], {})
        src_role = src.get("role", "?")
        tgt_role = tgt.get("role", "?")
        print(f"  [{link['edge_type']:15s}] {src_role}({link['source_id'][:8]}...) "
              f"-> {tgt_role}({link['target_id'][:8]}...) "
              f"w={link['weight']:.2f}")
        print(f"    rationale: {link['metadata']['rationale'][:120]}")

    print("=" * 70)


def main(dry_run: bool = False, limit: Optional[int] = None,
         target_role: Optional[str] = None):
    """Main entry point."""
    logger.info("Starting strategy graph build...")

    # --- Step 1: Connect to DB ---
    conn = get_connection()
    conn.autocommit = False
    logger.info("Connected to database")

    try:
        # --- Step 2: Fetch existing links for dedup ---
        existing_pairs = fetch_existing_pairs(conn)
        logger.info("Existing links in DB: %d", len(existing_pairs))

        # --- Step 3: Fetch strategy docs ---
        # Filter by target_role if specified
        roles_filter = [target_role] if target_role else None

        # Pass 1: Fetch priority doc types (role_strategy, etc.)
        priority_docs = fetch_docs(conn, doc_types=PRIORITY_DOC_TYPES,
                                   roles=roles_filter)
        logger.info("Fetched %d priority docs (role_strategy + key types)", len(priority_docs))

        # Count by role
        by_role: dict[str, list[dict]] = defaultdict(list)
        for doc in priority_docs:
            by_role[doc["role"]].append(doc)

        role_counts = sorted(
            [(role, len(docs)) for role, docs in by_role.items()],
            key=lambda x: -x[1],
        )
        logger.info("Priorty docs by role:")
        for role, count in role_counts:
            logger.info("  %-15s: %d docs", role, count)

        # --- Step 4: Build doc lookup ---
        docs_by_id: dict[str, dict] = {d["id"]: d for d in priority_docs}
        valid_ids = set(docs_by_id.keys())
        logger.info("Total unique doc IDs: %d", len(valid_ids))

        # --- Step 5: Create LLM client ---
        client = create_llm_client()

        # --- Step 6: Process batches ---
        all_links: list[dict] = []

        # ---- Pass 1: Within-role role_strategy batches (depends_on, upgrades_to, complements) ----
        logger.info("\n=== PASS 1: Within-role role_strategy analysis ===")
        rs_docs = [d for d in priority_docs if d["doc_type"] == "role_strategy"]
        rs_by_role: dict[str, list[dict]] = defaultdict(list)
        for d in rs_docs:
            rs_by_role[d["role"]].append(d)
        logger.info("role_strategy docs: %d across %d roles", len(rs_docs), len(rs_by_role))

        for role, docs in sorted(rs_by_role.items()):
            if len(docs) < 2:
                continue
            batches = create_batches(docs, BATCH_SIZE)
            for bi, batch in enumerate(batches):
                hint = (
                    f"You are analyzing {len(batch)} STRATEGY documents all for role '{role}'. "
                    f"Find within-role relationships: depends_on, upgrades_to, complements, "
                    f"and conflicts_with. Output ONLY a JSON array."
                )
                links = _process_batch(client, batch, hint, valid_ids, existing_pairs)
                all_links.extend(links)
                logger.info("  [within-role %s batch %d] found %d links, total=%d",
                            role, bi + 1, len(links), len(all_links))
                _rate_limit_sleep()

        # ---- Pass 2: Cross-role role_strategy batches (conflicts_with, depends_on) ----
        logger.info("\n=== PASS 2: Cross-role role_strategy analysis ===")
        # Mix all role_strategy docs and batch them
        rs_mixed_batches = create_mixed_batches(rs_by_role, batch_size=BATCH_SIZE)
        logger.info("Mixed role_strategy batches: %d", len(rs_mixed_batches))

        for bi, batch in enumerate(rs_mixed_batches):
            roles_in_batch = sorted(set(d["role"] for d in batch))
            hint = (
                f"You are analyzing {len(batch)} STRATEGY documents across roles "
                f"[{', '.join(roles_in_batch[:8])}]. Focus on CROSS-ROLE relationships: "
                f"conflicts_with (e.g., Werewolf strats that Seer strats counter), "
                f"depends_on (e.g., global strats that role strats depend on), "
                f"and complements. Output ONLY a JSON array."
            )
            links = _process_batch(client, batch, hint, valid_ids, existing_pairs)
            all_links.extend(links)
            logger.info("  [cross-role batch %d/%d] found %d links, total=%d",
                        bi + 1, len(rs_mixed_batches), len(links), len(all_links))
            _rate_limit_sleep()

        # ---- Pass 3: Within-role for major roles (good_play, bad_case_lesson, etc.) ----
        logger.info("\n=== PASS 3: Within-role non-strategy doc analysis ===")
        other_docs = [d for d in priority_docs if d["doc_type"] != "role_strategy"]
        other_by_role: dict[str, list[dict]] = defaultdict(list)
        for d in other_docs:
            other_by_role[d["role"]].append(d)

        for role in MAJOR_ROLES:
            docs = other_by_role.get(role, [])
            if len(docs) < 5:
                continue
            batches = create_batches(docs, BATCH_SIZE)
            for bi, batch in enumerate(batches[:2]):  # max 2 batches per role to control cost
                hint = (
                    f"You are analyzing {len(batch)} gameplay documents for role '{role}' "
                    f"(types: good_play, bad_case_lesson, strategy_suggestion, etc.). "
                    f"Find within-role relationships: complements (plays that work together), "
                    f"upgrades_to (improved versions of plays), depends_on (prerequisites). "
                    f"Output ONLY a JSON array."
                )
                links = _process_batch(client, batch, hint, valid_ids, existing_pairs)
                all_links.extend(links)
                logger.info("  [within-role %s batch %d] found %d links, total=%d",
                            role, bi + 1, len(links), len(all_links))
                _rate_limit_sleep()

        # ---- Pass 4: Targeted cross-role pairs ----
        logger.info("\n=== PASS 4: Targeted cross-role pair analysis ===")
        for role_a, role_b in CROSS_ROLE_PAIRS:
            docs_a = priority_docs  # Use all docs, filtered to the pair
            docs_pair = [d for d in docs_a if d["role"] in (role_a, role_b)]
            if len(docs_pair) < 10:
                continue
            # Sample to keep batches manageable
            if len(docs_pair) > 60:
                # Prioritize role_strategy + strategy_suggestion
                priority = [d for d in docs_pair
                            if d["doc_type"] in ("role_strategy", "strategy_suggestion")]
                others = [d for d in docs_pair
                          if d["doc_type"] not in ("role_strategy", "strategy_suggestion")]
                docs_pair = priority + others[:60 - len(priority)]

            batches = create_batches(docs_pair, BATCH_SIZE)
            for bi, batch in enumerate(batches[:1]):  # max 1 batch per pair
                hint = (
                    f"You are analyzing {len(batch)} documents across roles [{role_a}] "
                    f"and [{role_b}]. Focus on CROSS-ROLE relationships: "
                    f"conflicts_with (strategies from {role_a} that counter {role_b} or vice versa), "
                    f"depends_on, and complements. Output ONLY a JSON array."
                )
                links = _process_batch(client, batch, hint, valid_ids, existing_pairs)
                all_links.extend(links)
                logger.info("  [cross-pair %s<->%s batch %d] found %d links, total=%d",
                            role_a, role_b, bi + 1, len(links), len(all_links))
                _rate_limit_sleep()

            # Early stop if we've reached the target
            if len(all_links) >= MAX_RELATIONSHIPS_TARGET:
                logger.info("Reached target of %d links, stopping early", MAX_RELATIONSHIPS_TARGET)
                break

        # Apply limit if specified
        if limit and len(all_links) > limit:
            all_links = all_links[:limit]
            logger.info("Applied limit: keeping first %d links", limit)

        # --- Step 7: Insert into DB ---
        logger.info("\n=== Inserting links into database ===")
        if dry_run:
            logger.info("DRY RUN: would insert %d links (skipping)", len(all_links))
        else:
            inserted = insert_links(conn, all_links)
            logger.info("Inserted %d links into strategy_graph_links", inserted)

        # --- Step 8: Print summary ---
        print_summary(all_links, docs_by_id)

        # --- Step 9: Verify count from DB ---
        if not dry_run:
            final_pairs = fetch_existing_pairs(conn)
            logger.info("Final link count in DB: %d", len(final_pairs))

        if len(all_links) < MIN_RELATIONSHIPS_TARGET:
            logger.warning(
                "Only generated %d links (target: %d). Try re-running or adjusting batch sizes.",
                len(all_links), MIN_RELATIONSHIPS_TARGET
            )

    finally:
        conn.close()
        logger.info("Database connection closed")

    return len(all_links)


def _process_batch(client, batch: list[dict], context_hint: str,
                   valid_ids: set[str], existing_pairs: set[tuple]) -> list[dict]:
    """Process a single batch: call LLM, parse, validate, dedup."""
    system = SYSTEM_PROMPT
    user = _build_user_prompt(batch, context_hint)

    try:
        raw_text = call_llm_with_retry(client, system, user, temperature=0.3, max_tokens=4096)
    except Exception as e:
        logger.error("Failed to process batch after retries: %s", e)
        return []

    raw_links = extract_json(raw_text)
    if not raw_links:
        logger.warning("No valid links extracted from LLM response")
        logger.debug("Raw response (first 500 chars): %s", raw_text[:500])
        return []

    validated = dedup_links(raw_links, valid_ids, existing_pairs)
    # Update existing_pairs to avoid duplicates within the same run
    for link in validated:
        existing_pairs.add((link["source_id"], link["target_id"], link["edge_type"]))

    logger.debug("  raw=%d validated=%d links", len(raw_links), len(validated))
    return validated


def _rate_limit_sleep():
    """Sleep to respect rate limits."""
    import random
    delay = random.uniform(RATE_LIMIT_SLEEP_MIN, RATE_LIMIT_SLEEP_MAX)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build strategy graph links using LLM analysis"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze but do not write to database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of links to insert",
    )
    parser.add_argument(
        "--role",
        type=str,
        default=None,
        help="Only process strategies for this role",
    )
    args = parser.parse_args()

    count = main(
        dry_run=args.dry_run,
        limit=args.limit,
        target_role=args.role,
    )
    print(f"\nDone. Total links processed: {count}")
