"""Strategy retrieval — semantic search for relevant strategies.

Single Responsibility: find the most relevant strategy entries
for a given game situation from the PostgreSQL knowledge base.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def retrieve_strategies(
    role: str,
    phase: str,
    situation: str = "",
    limit: int = 3,
    conn_str: str = "",
) -> List[Dict[str, str]]:
    """Retrieve relevant strategies from the knowledge base.

    Args:
        role: Current role (e.g., "Seer", "Werewolf")
        phase: Current phase (e.g., "DAY_SPEECH", "NIGHT_ACTION")
        situation: Optional situation description for better matching
        limit: Max entries to return
        conn_str: PostgreSQL connection string

    Returns:
        List of strategy dicts with 'situation' and 'strategy' keys
    """
    try:
        import psycopg2
        conn = psycopg2.connect(conn_str or "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf")
        c = conn.cursor()

        # Strategy 1: exact role + phase match
        c.execute("""
            SELECT situation_pattern, recommended_action, quality_score
            FROM strategy_knowledge_docs
            WHERE status = 'active'
              AND (role = %s OR role = 'global')
              AND (phase = %s OR phase = 'global')
            ORDER BY quality_score DESC, RANDOM()
            LIMIT %s
        """, (role, phase, limit))

        results = []
        for situation_pattern, recommended_action, quality in c.fetchall():
            results.append({
                "situation": situation_pattern or "",
                "strategy": recommended_action or "",
                "quality": quality or 0.8,
            })

        conn.close()
        return results

    except Exception:
        return []


def format_strategies_for_prompt(strategies: List[Dict[str, str]]) -> str:
    """Format retrieved strategies into prompt text."""
    if not strategies:
        return ""

    lines = ["=== 相关策略参考 ==="]
    for i, s in enumerate(strategies, 1):
        lines.append(f"{i}. 场景：{s['situation']}")
        lines.append(f"   策略：{s['strategy']}")
        lines.append("")

    return "\n".join(lines)
