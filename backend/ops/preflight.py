"""Preflight checks for strict-mode backend verification.

Usage:
    from backend.ops.preflight import run_preflight
    results = run_preflight()
    if not results["all_pass"]: sys.exit(1)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from backend.db.database import DEFAULT_DB_URL as _DEFAULT_DB


def run_preflight(db_url: str = "", strict: bool = True) -> dict[str, Any]:
    """Run all preflight checks. Returns dict with results."""
    db_url = db_url or os.getenv("DATABASE_URL", _DEFAULT_DB)
    strict_mode = strict or os.getenv("AIWEREWOLF_STRICT_MODE", "").lower() == "true"

    results: dict[str, Any] = {"all_pass": True, "checks": {}}

    checks = [
        ("imports", lambda: _check_imports()),
        ("db_connection", lambda: _check_db_connection(db_url)),
        ("db_tables", lambda: _check_db_tables(db_url)),
        ("db_write", lambda: _check_db_write(db_url, strict_mode)),
        ("llm_client", lambda: _check_llm_client(strict_mode)),
        ("active_strategies", lambda: _check_active_strategies(db_url, strict_mode)),
        ("pool_config", lambda: _check_pool_config(strict_mode)),
    ]

    for name, fn in checks:
        try:
            status, detail = fn()
            results["checks"][name] = {"status": "pass" if status else "fail", "detail": detail}
            if not status and strict_mode:
                results["all_pass"] = False
                logger.error(f"PREFLIGHT FAIL [{name}]: {detail}")
            elif not status:
                logger.warning(f"PREFLIGHT WARN [{name}]: {detail}")
            else:
                logger.info(f"PREFLIGHT OK [{name}]: {detail}")
        except Exception as e:
            results["checks"][name] = {"status": "fail", "detail": str(e)}
            if strict_mode:
                results["all_pass"] = False
                logger.error(f"PREFLIGHT ERROR [{name}]: {e}")

    return results


def _check_imports() -> tuple[bool, str]:
    modules = [
        "backend.llm",
        "backend.db.database",
        "backend.db.models",
        "backend.db.persist",
        "backend.engine.game",
        "backend.engine.models",
        "backend.engine.visibility",
        "backend.agents.cognitive.agent",
        "backend.agents.cognitive.agent_loop",
        "backend.agents.cognitive.tools",
        "backend.agents.cognitive.retrieval_prod",
        "backend.agents.cognitive.retrieval",
        "backend.eval.per_step_scorer",
        "backend.eval.knowledge_abstractor",
        "backend.eval.post_game",
        "backend.eval.review",
    ]
    failed = []
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            failed.append(f"{mod}: {e}")
    if failed:
        return False, f"Failed imports: {failed}"
    return True, f"All {len(modules)} modules imported"


def _check_db_connection(db_url: str) -> tuple[bool, str]:
    import psycopg2

    try:
        conn = psycopg2.connect(db_url, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return True, "PostgreSQL connected"
    except Exception as e:
        return False, f"DB connection failed: {e}"


def _check_db_tables(db_url: str) -> tuple[bool, str]:
    required = [
        "games",
        "players",
        "agent_decisions",
        "game_events",
        "votes",
        "strategy_knowledge_docs",
        "evaluations",
        "leaderboard_entries",
    ]
    import psycopg2

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'")
        existing = {r[0] for r in cur.fetchall()}
        missing = [t for t in required if t not in existing]
        cur.close()
        conn.close()
        if missing:
            return False, f"Missing tables: {missing}"
        return True, f"All {len(required)} required tables present"
    except Exception as e:
        return False, f"Table check failed: {e}"


def _check_db_write(db_url: str, strict: bool) -> tuple[bool, str]:
    import psycopg2

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM strategy_knowledge_docs LIMIT 1")
        cur.close()
        conn.close()
        return True, "DB readable"
    except Exception as e:
        if strict:
            return False, f"DB read failed: {e}"
        return False, f"DB read failed: {e}"


def _check_llm_client(strict: bool) -> tuple[bool, str]:
    try:
        from backend.llm import create_client

        client = create_client()
        available = getattr(client, "available", True)
        if not available:
            if strict:
                return False, f"LLM client unavailable: provider={client.provider}"
            return False, f"LLM client unavailable: provider={client.provider}"

        # Health check
        resp = client.chat_sync([{"role": "user", "content": 'Return ONLY: {"ok":true}'}])
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        data = json.loads(content)
        if data.get("ok") is not True:
            return False, f"LLM health check unexpected: {content[:80]}"

        return True, f"provider={client.provider}, model={client.model}"
    except Exception as e:
        if strict:
            return False, f"LLM check failed: {e}"
        return False, f"LLM check failed: {e}"


def _check_active_strategies(db_url: str, strict: bool) -> tuple[bool, str]:
    import psycopg2

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM strategy_knowledge_docs WHERE status='active'")
        active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM strategy_knowledge_docs WHERE status='candidate'")
        candidate = cur.fetchone()[0]
        cur.close()
        conn.close()
        if active == 0 and strict:
            return False, "No active strategy docs"
        return True, f"active={active}, candidate={candidate}"
    except Exception as e:
        return False, f"Strategy check failed: {e}"


def _check_pool_config(strict: bool) -> tuple[bool, str]:
    pool_size = os.getenv("DB_POOL_SIZE", "5")
    max_overflow = os.getenv("DB_MAX_OVERFLOW", "5")
    if strict and int(pool_size) > 5:
        return False, f"DB_POOL_SIZE={pool_size} too high for strict mode"
    return True, f"pool_size={pool_size}, max_overflow={max_overflow}"
