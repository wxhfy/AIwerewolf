#!/usr/bin/env python
"""Translate English strategy knowledge docs to Chinese using LLM batch translation.

Reads all English-only docs (no CJK characters) from strategy_knowledge_docs table,
translates situation_pattern / recommended_action / rationale / avoid_action into
natural Chinese via batch LLM calls, and updates the database in place.

Usage:
    python scripts/translate_strategies.py
    python scripts/translate_strategies.py --batch-size 12 --dry-run
    python scripts/translate_strategies.py --sleep 1.5 --max-tokens 4096
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import StrategyKnowledgeDoc
from backend.llm import create_client

# ── CJK detection ───────────────────────────────────────────────────────────

_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def has_cjk(text: str | None) -> bool:
    """Return True if *text* contains any CJK (Chinese) character."""
    if not text:
        return False
    return bool(_CJK_RE.search(text))


# Fields to translate (in priority order)
_TRANSLATABLE_FIELDS = ("situation_pattern", "recommended_action", "rationale", "avoid_action")


def needs_translation(doc: StrategyKnowledgeDoc) -> set[str]:
    """Return the set of field names that are in English and need translation."""
    needs: set[str] = set()
    for field in _TRANSLATABLE_FIELDS:
        value = getattr(doc, field, None)
        if value and not has_cjk(value):
            needs.add(field)
    return needs


def is_candidate(doc: StrategyKnowledgeDoc) -> bool:
    """A doc is a candidate if at least one translatable field is in English."""
    return len(needs_translation(doc)) > 0


# ── LLM batch translation ────────────────────────────────────────────────────

TRANSLATION_SYSTEM_PROMPT = """You are a professional translator specializing in Werewolf (狼人杀) game strategy content.
Your task is to translate English strategy knowledge entries into natural, fluent Chinese.

Translation guidelines:
1. **Natural Chinese**: Write as a native Chinese werewolf player would express these ideas.
2. **Game terminology**: Use standard Chinese werewolf terms:
   - Seer → 预言家
   - Witch → 女巫
   - Hunter → 猎人
   - Guard → 守卫
   - Villager → 村民
   - Werewolf → 狼人
   - Wolf team → 狼队
   - Check/verify → 查验
   - Vote out → 投票出局 / 归票
   - Save → 救 / 救人
   - Poison → 毒 / 毒杀
   - Protect → 守护
   - Sheriff → 警长
   - Gold water → 金水
   - Kill check → 查杀
   - Speech → 发言
   - Night phase → 夜晚 / 夜间
   - Day phase → 白天
3. **Tone**: Strategy advice should sound authoritative but not stiff.
4. **Preserve meaning**: Do not add or remove strategic content. Translate faithfully.
5. **Output ONLY valid JSON** — no markdown fences, no extra text."""


def build_translation_prompt(docs: list[StrategyKnowledgeDoc]) -> str:
    """Build a user prompt that asks the LLM to translate a batch of docs.

    Only includes fields that are actually in English (no CJK), so the LLM
    doesn't waste tokens re-translating already-Chinese content.
    """
    entries = []
    for doc in docs:
        entry: dict[str, str] = {"doc_id": doc.id}
        english_fields = needs_translation(doc)
        for field in _TRANSLATABLE_FIELDS:
            if field in english_fields:
                value = getattr(doc, field, None)
                entry[field] = value or ""
        entries.append(entry)

    payload = json.dumps(entries, ensure_ascii=False, indent=2)
    field_names = ", ".join(f"`{f}`" for f in _TRANSLATABLE_FIELDS)
    return f"""Translate each strategy entry below from English to Chinese.

For each entry, translate ALL English fields to Chinese. Only the fields present
in each entry need translation — if a field is missing from an entry, skip it.

Return a JSON array with the same doc_id values and translated {field_names} fields.

Input entries:
{payload}"""


def parse_translation_response(raw_text: str) -> list[dict[str, str]]:
    """Parse the LLM response into a list of {doc_id, situation_pattern, ...} dicts."""
    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON array in the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            result = json.loads(match.group(0))
        else:
            raise

    if not isinstance(result, list):
        raise ValueError(f"Expected JSON array, got {type(result).__name__}")

    return result


def translate_batch(
    client: Any,
    docs: list[StrategyKnowledgeDoc],
    max_tokens: int = 4096,
) -> list[dict[str, str]]:
    """Send a batch of docs to the LLM for translation. Returns parsed results."""
    messages = [
        {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
        {"role": "user", "content": build_translation_prompt(docs)},
    ]

    response = client.chat_sync(
        messages=messages,
        temperature=0.3,
        max_tokens=max_tokens,
        thinking=False,
    )
    raw_text = client.parse_response(response)
    return parse_translation_response(raw_text)


# ── Database helpers ─────────────────────────────────────────────────────────


def fetch_english_docs(db) -> list[StrategyKnowledgeDoc]:
    """Fetch all docs that have at least one English field worth translating."""
    all_docs = db.query(StrategyKnowledgeDoc).all()
    candidates = [doc for doc in all_docs if is_candidate(doc)]
    return candidates


def apply_translations(
    db,
    doc_map: dict[str, StrategyKnowledgeDoc],
    translations: list[dict[str, str]],
    doc_english_fields: dict[str, set[str]] | None = None,
) -> int:
    """Apply translation results to the database. Returns count of updated docs.

    Only updates fields that were originally English (in doc_english_fields),
    so already-Chinese content is never overwritten by a re-translation.
    """
    if doc_english_fields is None:
        doc_english_fields = {}

    updated = 0
    for t in translations:
        doc_id = t.get("doc_id", "")
        if not doc_id or doc_id not in doc_map:
            print(f"  [WARN] Unknown doc_id in response: {doc_id!r}")
            continue

        doc = doc_map[doc_id]
        allowed = doc_english_fields.get(doc_id, set(_TRANSLATABLE_FIELDS))
        changed = False

        for field in _TRANSLATABLE_FIELDS:
            new_value = t.get(field)
            if not new_value:
                continue
            # Only update if this field was originally English (needed translation)
            if field in allowed and new_value != getattr(doc, field, None):
                setattr(doc, field, new_value)
                changed = True

        if changed:
            if doc.doc_type != "web_strategy":
                doc.doc_type = "web_strategy"
            updated += 1

    return updated


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate English strategy knowledge docs to Chinese via batch LLM.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=12,
        help="Number of docs per LLM call (default: 12)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        help="Seconds to sleep between LLM calls (default: 1.5)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Max tokens per LLM call (default: 4096)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries per failed batch (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print candidates without calling LLM or updating DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of docs to translate (0 = all). Useful for testing.",
    )
    args = parser.parse_args()

    # ── Connect to DB ────────────────────────────────────────────────────────
    init_db()
    db = SessionLocal()

    try:
        # ── Fetch candidates ─────────────────────────────────────────────────
        print("Fetching English-only strategy knowledge docs...")
        english_docs = fetch_english_docs(db)

        if args.limit > 0:
            english_docs = english_docs[: args.limit]

        doc_type_counts: dict[str, int] = {}
        for doc in english_docs:
            dt = doc.doc_type or "unknown"
            doc_type_counts[dt] = doc_type_counts.get(dt, 0) + 1

        print(f"Found {len(english_docs)} English-only docs:")
        for dt, count in sorted(doc_type_counts.items()):
            print(f"  {dt}: {count}")

        if not english_docs:
            print("No English docs to translate. Exiting.")
            return

        if args.dry_run:
            print("\n[Dry-run] Showing first 5 candidates:")
            for doc in english_docs[:5]:
                print(f"  [{doc.doc_type}] {doc.id}")
                print(f"    role={doc.role}  phase={doc.phase}")
                print(f"    situation_pattern={doc.situation_pattern[:120]}...")
                print(f"    recommended_action={doc.recommended_action[:120]}..." if doc.recommended_action else "")
                print(f"    rationale={doc.rationale[:120]}..." if doc.rationale else "")
            return

        # ── Init LLM client ──────────────────────────────────────────────────
        print("\nInitializing LLM client...")
        client = create_client()
        print(f"  Provider: {client.provider}  Model: {client.model}")

        # ── Batch translate ──────────────────────────────────────────────────
        total_updated = 0
        total_batches = (len(english_docs) + args.batch_size - 1) // args.batch_size

        for batch_idx in range(total_batches):
            start = batch_idx * args.batch_size
            end = min(start + args.batch_size, len(english_docs))
            batch_docs = english_docs[start:end]

            # Build lookup maps for this batch
            doc_map: dict[str, StrategyKnowledgeDoc] = {doc.id: doc for doc in batch_docs}
            doc_english_fields: dict[str, set[str]] = {doc.id: needs_translation(doc) for doc in batch_docs}

            print(f"\nBatch {batch_idx + 1}/{total_batches}: docs {start + 1}-{end} ({len(batch_docs)} entries)")

            success = False
            for attempt in range(1, args.max_retries + 1):
                try:
                    translations = translate_batch(client, batch_docs, max_tokens=args.max_tokens)
                    batch_updated = apply_translations(
                        db,
                        doc_map,
                        translations,
                        doc_english_fields,
                    )
                    db.commit()
                    total_updated += batch_updated
                    print(f"  Translated {batch_updated}/{len(batch_docs)} docs (attempt {attempt})")
                    success = True
                    break
                except json.JSONDecodeError as exc:
                    print(f"  [ERROR] JSON parse failed (attempt {attempt}/{args.max_retries}): {exc}")
                    if attempt < args.max_retries:
                        time.sleep(2)
                except Exception as exc:
                    print(f"  [ERROR] Batch failed (attempt {attempt}/{args.max_retries}): {exc}")
                    db.rollback()
                    if attempt < args.max_retries:
                        time.sleep(2)

            if not success:
                print(f"  [SKIP] Batch {batch_idx + 1} failed all {args.max_retries} retries, skipping.")

            # Progress summary every batch
            if (batch_idx + 1) % 5 == 0 or (batch_idx + 1) == total_batches:
                print(
                    f"\n── Progress: {total_updated}/{len(english_docs)} docs translated "
                    f"({batch_idx + 1}/{total_batches} batches) ──"
                )

            # Rate-limit sleep
            if batch_idx < total_batches - 1:
                time.sleep(args.sleep)

        # ── Final report ─────────────────────────────────────────────────────
        print(f"\n{'=' * 60}")
        print("Translation complete!")
        print(f"  Total English docs found:  {len(english_docs)}")
        print(f"  Successfully translated:   {total_updated}")
        print(f"  Skipped (all retries failed): {len(english_docs) - total_updated}")
        print(f"{'=' * 60}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
