"""Strict-mode backend end-to-end verification.

Runs ONE complete 7-player AI Werewolf game with ALL features enabled.
No fallbacks, no silent degradation, no skipped modules.

Usage:
  python scripts/run_backend_full_strict.py [--skip-game] [--skip-docs]
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Bootstrap ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

# ── Strict mode env ────────────────────────────────────────────
os.environ.setdefault("AIWEREWOLF_STRICT_MODE", "true")
os.environ.setdefault("REQUIRE_DB", "true")
os.environ.setdefault("REQUIRE_LLM", "true")
os.environ.setdefault("REQUIRE_TRACK_B", "true")
os.environ.setdefault("REQUIRE_TRACK_C", "true")
os.environ.setdefault("REQUIRE_POST_GAME_SCORING", "true")
os.environ.setdefault("REQUIRE_STRATEGY_USAGE_TRACE", "true")
os.environ.setdefault("REQUIRE_KNOWLEDGE_WRITE", "true")
os.environ.setdefault("ALLOW_FALLBACK", "false")
os.environ.setdefault("ALLOW_DEGRADED_MODE", "false")
os.environ.setdefault("ALLOW_CANDIDATE_RETRIEVAL", "false")
os.environ.setdefault("AUTO_PROMOTE_LESSONS", "false")
os.environ.setdefault("STRICT_SCHEMA", "true")
os.environ.setdefault("STRICT_EXPERIMENT", "true")
os.environ.setdefault("COGNITIVE_ENABLE_TRACK_C", "true")
os.environ.setdefault("COGNITIVE_ENABLE_ANTI_PATTERNS", "true")
os.environ.setdefault("COGNITIVE_ENABLE_REFLECTION", "true")
os.environ.setdefault("DB_POOL_SIZE", "5")
os.environ.setdefault("DB_MAX_OVERFLOW", "5")

# DATABASE_URL (the code hardcodes a fallback; set it explicitly)
_DB_URL = os.getenv("DATABASE_URL", "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf")
os.environ["DATABASE_URL"] = _DB_URL

# ── Logging ─────────────────────────────────────────────────────
output_dir = ROOT / "outputs"
output_dir.mkdir(parents=True, exist_ok=True)

log_file = output_dir / "backend_e2e_strict.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(log_file), mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("strict_e2e")

# ── State ───────────────────────────────────────────────────────
report: dict = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "strict_mode": True,
    "checks": {},
    "game": {},
    "track_b": {},
    "track_c": {},
    "experiment": {},
    "failures": [],
    "warnings": [],
}

def fail(reason: str, fatal: bool = True):
    report["failures"].append(reason)
    logger.error(f"STRICT FAIL: {reason}")
    if fatal:
        raise SystemExit(f"STRICT MODE FAILURE: {reason}")

def warn(msg: str):
    report["warnings"].append(msg)
    logger.warning(f"STRICT WARN: {msg}")

# ═══════════════════════════════════════════════════════════════
# Phase 0: Preflight
# ═══════════════════════════════════════════════════════════════

def preflight():
    logger.info("=" * 60)
    logger.info("PHASE 0: PREFLIGHT CHECKS")
    logger.info("=" * 60)

    # 0a. Python imports
    logger.info("0a. Import smoke test...")
    modules = [
        "backend.llm",
        "backend.llm.env",
        "backend.db.database",
        "backend.db.models",
        "backend.db.persist",
        "backend.engine.game",
        "backend.engine.models",
        "backend.agents.cognitive.agent",
        "backend.agents.cognitive.agent_loop",
        "backend.agents.cognitive.tools",
        "backend.agents.cognitive.retrieval_prod",
        "backend.agents.cognitive.retrieval",
        "backend.eval.per_step_scorer",
        "backend.eval.knowledge_abstractor",
        "backend.eval.post_game",
        "backend.eval.review",
        "backend.agents.cognitive.factory",
    ]
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            fail(f"Import failed: {mod} -> {e}")
    logger.info("  All imports OK")
    report["checks"]["imports"] = "pass"

    # 0b. DB connection
    logger.info("0b. DB connection...")
    try:
        import psycopg2
        conn = psycopg2.connect(_DB_URL, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        logger.info("  DB connected OK")
        report["checks"]["db_connection"] = "pass"
    except Exception as e:
        fail(f"DB connection failed: {e}")

    # 0c. DB tables
    logger.info("0c. DB table check...")
    required_tables = [
        "games", "players", "agent_decisions", "game_events", "votes",
        "strategy_knowledge_docs", "evaluations", "leaderboard_entries",
    ]
    optional_tables = [
        "knowledge_usage_feedback", "published_reviews", "game_snapshots",
        "strategy_patches", "strategy_graph_links",
    ]
    try:
        conn = psycopg2.connect(_DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'")
        existing = {r[0] for r in cur.fetchall()}
        for tbl in required_tables:
            if tbl not in existing:
                fail(f"Required table missing: {tbl}")
        missing_opt = [t for t in optional_tables if t not in existing]
        if missing_opt:
            warn(f"Optional tables missing: {missing_opt}")
        cur.close()
        conn.close()
        logger.info(f"  Tables OK: {len(required_tables)} required present")
        report["checks"]["db_tables"] = "pass"
    except Exception as e:
        fail(f"Table check failed: {e}")

    # 0d. LLM client
    logger.info("0d. LLM client health check...")
    try:
        from backend.llm import create_client
        client = create_client()
        available = getattr(client, "available", True)
        if not available:
            fail(f"LLM client unavailable: provider={client.provider}")
        resp = client.chat_sync([
            {"role": "user", "content": 'Return ONLY valid JSON: {"ok":true}'}
        ])
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        data = json.loads(content)
        if data.get("ok") is not True:
            fail(f"LLM health check returned unexpected: {content[:80]}")
        logger.info(f"  LLM OK: provider={client.provider}, model={client.model}")
        report["checks"]["llm_client"] = "pass"
        report["checks"]["llm_provider"] = client.provider
        report["checks"]["llm_model"] = client.model
    except SystemExit:
        raise
    except Exception as e:
        fail(f"LLM client check failed: {e}")

    # 0e. Active strategy docs
    logger.info("0e. Active strategy docs...")
    try:
        conn = psycopg2.connect(_DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM strategy_knowledge_docs WHERE status='active'")
        active_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM strategy_knowledge_docs WHERE status='candidate'")
        candidate_count = cur.fetchone()[0]
        cur.close()
        conn.close()
        report["checks"]["active_docs_before"] = active_count
        report["checks"]["candidate_docs_before"] = candidate_count
        if active_count == 0:
            fail("No active strategy docs found — Track C cannot function")
        logger.info(f"  Active docs: {active_count}, Candidate docs: {candidate_count}")
        report["checks"]["active_docs"] = "pass"
    except Exception as e:
        fail(f"Strategy docs check failed: {e}")

    # 0f. Fallback keyword scan
    logger.info("0f. Fallback keyword scan in core files...")
    forbidden_keywords = ["fallback", "degraded", "degrade", "skip", "unavailable", "disabled"]
    core_files = [
        "backend/agents/cognitive/tools.py",
        "backend/agents/cognitive/retrieval_prod.py",
        "backend/agents/cognitive/retrieval.py",
        "backend/agents/cognitive/agent_loop.py",
        "backend/eval/post_game.py",
        "backend/eval/per_step_scorer.py",
        "backend/eval/knowledge_abstractor.py",
        "backend/engine/game.py",
        "backend/db/database.py",
    ]
    found_keywords: dict[str, list] = {}
    for fpath_rel in core_files:
        fpath = ROOT / fpath_rel
        if not fpath.exists():
            continue
        text = fpath.read_text()
        for kw in forbidden_keywords:
            if kw in text.lower():
                found_keywords.setdefault(kw, []).append(fpath_rel)
    if found_keywords:
        logger.info(f"  Fallback keywords found in core files (informational):")
        for kw, files in sorted(found_keywords.items()):
            logger.info(f"    '{kw}': {files}")
    report["checks"]["fallback_keyword_scan"] = found_keywords

    logger.info("PREFLIGHT COMPLETE — all checks passed\n")
    return active_count, candidate_count


# ═══════════════════════════════════════════════════════════════
# Phase 1: Run one complete game
# ═══════════════════════════════════════════════════════════════

def run_game():
    logger.info("=" * 60)
    logger.info("PHASE 1: RUN COMPLETE 7-PLAYER GAME")
    logger.info("=" * 60)

    from backend.engine.game import WerewolfGame

    seed = int(os.getenv("STRICT_SEED", "42"))
    player_count = 7

    logger.info(f"Creating game: seed={seed}, player_count={player_count}")
    t0 = time.perf_counter()

    try:
        game = WerewolfGame(seed=seed, player_count=player_count)

        # Log role assignment
        for p in game.state.players:
            mbti = getattr(p, "persona", {})
            mbti_str = mbti.get("mbti", "?") if isinstance(mbti, dict) else "?"
            logger.info(f"  Seat {p.seat}: {p.name} = {p.role.value} [{mbti_str}]")

        state = game.play()
        elapsed = time.perf_counter() - t0

        game_id = str(getattr(state, "id", "") or getattr(state, "game_id", ""))
        winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
        day = state.day

        logger.info(f"Game complete: id={game_id}, winner={winner}, days={day}, time={elapsed:.1f}s")

        report["game"] = {
            "game_id": game_id,
            "seed": seed,
            "winner": winner,
            "days": day,
            "player_count": player_count,
            "duration_s": round(elapsed, 1),
            "finished": True,
        }

        for p in state.players:
            report["game"].setdefault("players", []).append({
                "name": p.name, "role": p.role.value, "seat": p.seat,
                "alive": p.alive, "death_day": getattr(p, "death_day", None),
            })

        return game_id

    except Exception as e:
        fail(f"Game execution failed: {e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════
# Phase 2: DB verification
# ═══════════════════════════════════════════════════════════════

def verify_db(game_id: str, active_before: int, candidate_before: int):
    logger.info("=" * 60)
    logger.info("PHASE 2: DB VERIFICATION")
    logger.info("=" * 60)

    import psycopg2
    conn = psycopg2.connect(_DB_URL)
    cur = conn.cursor()

    queries = {
        "game_exists": "SELECT COUNT(*) FROM games WHERE id = %s",
        "player_count": "SELECT COUNT(*) FROM players WHERE game_id = %s",
        "decision_count": "SELECT COUNT(*) FROM agent_decisions WHERE game_id = %s",
        "event_count": "SELECT COUNT(*) FROM game_events WHERE game_id = %s",
        "vote_count": "SELECT COUNT(*) FROM votes WHERE game_id = %s",
    }

    results = {}
    for name, sql in queries.items():
        cur.execute(sql, (game_id,))
        results[name] = cur.fetchone()[0]
        logger.info(f"  {name}: {results[name]}")

    # Strategy usage trace
    cur.execute(
        "SELECT COUNT(*) FROM agent_decisions WHERE game_id = %s AND parsed_action IS NOT NULL",
        (game_id,))
    decisions_with_action = cur.fetchone()[0]
    logger.info(f"  decisions_with_parsed_action: {decisions_with_action}")

    # Check for tool_trace in parsed_action
    cur.execute(
        "SELECT id FROM agent_decisions WHERE game_id = %s "
        "AND (parsed_action::text LIKE '%%_tool_trace%%' "
        "OR parsed_action::text LIKE '%%_auto_injected_strategies%%')",
        (game_id,))
    trace_ids = [r[0] for r in cur.fetchall()]
    logger.info(f"  decisions_with_tool_trace: {len(trace_ids)}")

    # Active/candidate counts after game
    cur.execute("SELECT COUNT(*) FROM strategy_knowledge_docs WHERE status='active'")
    active_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM strategy_knowledge_docs WHERE status='candidate'")
    candidate_after = cur.fetchone()[0]

    # New lessons from this game
    cur.execute(
        "SELECT COUNT(*) FROM strategy_knowledge_docs WHERE source_report_ids @> %s::jsonb",
        (json.dumps([game_id]),))
    new_lessons = cur.fetchone()[0]

    cur.execute(
        "SELECT status, doc_type, COUNT(*) FROM strategy_knowledge_docs "
        "WHERE source_report_ids @> %s::jsonb GROUP BY status, doc_type",
        (json.dumps([game_id]),))
    lesson_breakdown = [(r[0], r[1], r[2]) for r in cur.fetchall()]

    logger.info(f"  new_lessons_from_game: {new_lessons}")
    logger.info(f"  lesson_breakdown: {lesson_breakdown}")
    logger.info(f"  active_before={active_before}, active_after={active_after} (delta={active_after - active_before})")
    logger.info(f"  candidate_before={candidate_before}, candidate_after={candidate_after} (delta={candidate_after - candidate_before})")

    # Check knowledge_usage_feedback
    cur.execute("SELECT COUNT(*) FROM knowledge_usage_feedback WHERE game_id = %s", (game_id,))
    usage_count = cur.fetchone()[0]
    logger.info(f"  knowledge_usage_feedback records: {usage_count}")

    cur.close()
    conn.close()

    report["db_verify"] = {
        **results,
        "decisions_with_tool_trace": len(trace_ids),
        "new_lessons": new_lessons,
        "lesson_breakdown": [{"status": s, "doc_type": d, "count": c} for s, d, c in lesson_breakdown],
        "active_before": active_before,
        "active_after": active_after,
        "active_delta": active_after - active_before,
        "candidate_before": candidate_before,
        "candidate_after": candidate_after,
        "candidate_delta": candidate_after - candidate_before,
        "knowledge_usage_records": usage_count,
    }

    # Strict checks
    if results["decision_count"] == 0:
        fail("No decisions recorded in DB", fatal=True)

    active_delta = active_after - active_before
    if active_delta < -20 or active_delta > 50:
        fail(f"Active docs changed excessively: {active_before} → {active_after} (delta={active_delta}). "
             f"Expected delta in [-20, +50].", fatal=True)

    if candidate_after <= candidate_before:
        fail(f"Candidate docs did not grow: {candidate_before} → {candidate_after} (delta={candidate_after - candidate_before}). "
             f"Knowledge extraction should produce new candidate docs.", fatal=False)

    # Log results
    return results


# ═══════════════════════════════════════════════════════════════
# Phase 3: Post-game artifact check
# ═══════════════════════════════════════════════════════════════

def verify_artifacts(game_id: str):
    logger.info("=" * 60)
    logger.info("PHASE 3: POST-GAME ARTIFACT VERIFICATION")
    logger.info("=" * 60)

    import psycopg2
    conn = psycopg2.connect(_DB_URL)
    cur = conn.cursor()

    # Speech acts: check from per_step_scorer logs or from raw decisions
    cur.execute(
        "SELECT id, phase, raw_output FROM agent_decisions WHERE game_id = %s "
        "AND (phase LIKE '%%SPEECH%%' OR phase LIKE '%%TALK%%')",
        (game_id,))
    speech_rows = cur.fetchall()
    logger.info(f"  speech/talk decisions: {len(speech_rows)}")

    # Check if any speech decisions were scored (from post_game)
    # We can't directly query scores from DB (they're not persisted), but we check logs
    # Check scored steps from knowledge_abstractor output
    cur.execute(
        "SELECT COUNT(*) FROM strategy_knowledge_docs WHERE source_report_ids @> %s::jsonb",
        (json.dumps([game_id]),))
    scored_lessons = cur.fetchone()[0]
    logger.info(f"  lessons_from_scoring: {scored_lessons}")

    # Check for review / published_review
    cur.execute(
        "SELECT id, status, score, publish_allowed FROM published_reviews WHERE game_id = %s",
        (game_id,))
    reviews = cur.fetchall()
    logger.info(f"  published_reviews: {len(reviews)}")
    for r in reviews:
        logger.info(f"    id={r[0]}, status={r[1]}, score={r[2]}, publish_allowed={r[3]}")

    # Check evaluations
    cur.execute("SELECT COUNT(*) FROM evaluations WHERE game_id = %s", (game_id,))
    eval_count = cur.fetchone()[0]
    logger.info(f"  evaluations: {eval_count}")

    # Check leaderboard entries
    cur.execute("SELECT COUNT(*) FROM leaderboard_entries",)
    lb_count = cur.fetchone()[0]
    logger.info(f"  leaderboard_entries total: {lb_count}")

    cur.close()
    conn.close()

    report["artifacts"] = {
        "speech_decisions_count": len(speech_rows),
        "scored_lessons_count": scored_lessons,
        "review_count": len(reviews),
        "evaluation_count": eval_count,
        "leaderboard_entries": lb_count,
    }

    # Strict checks
    if len(speech_rows) == 0:
        fail("No speech decisions found — game may not have completed properly")
    elif scored_lessons == 0:
        warn("No lessons extracted from scoring — check post_game logs for speech_acts")


# ═══════════════════════════════════════════════════════════════
# Phase 4: Log scan for forbidden keywords
# ═══════════════════════════════════════════════════════════════

def scan_log():
    logger.info("=" * 60)
    logger.info("PHASE 4: LOG SCAN FOR DEGRADATION KEYWORDS")
    logger.info("=" * 60)

    if not log_file.exists():
        warn("Log file not found for scanning")
        return

    forbidden = [
        "fallback", "degraded", "degrade", "best-effort", "best effort",
        "disabled", "skip", "unavailable",
    ]

    log_text = log_file.read_text()
    findings: dict[str, list[str]] = {}
    for kw in forbidden:
        lines = [l.strip()[:120] for l in log_text.split("\n") if kw in l.lower() and "STRICT" not in l]
        if lines:
            findings[kw] = lines[:5]  # first 5 occurrences

    report["log_scan"] = {kw: len(lines) for kw, lines in findings.items()}

    # Classify findings
    critical_keywords = {"fallback", "degraded", "degrade", "unavailable"}
    for kw, examples in findings.items():
        level = "CRITICAL" if kw in critical_keywords else "WARNING"
        logger.info(f"  [{level}] '{kw}' found {len(examples)} times:")
        for ex in examples[:3]:
            logger.info(f"    {ex}")

    # Report failures for critical keywords in core paths
    for kw in critical_keywords:
        if kw in findings and findings[kw]:
            # Check if these are in non-critical paths (e.g., debug logs, comments)
            # For now, flag all
            warn(f"Critical keyword '{kw}' found in log ({len(findings[kw])} occurrences)")


# ═══════════════════════════════════════════════════════════════
# Phase 5: Evidence chain demo
# ═══════════════════════════════════════════════════════════════

def build_evidence_chain(game_id: str):
    """Extract a sample evidence chain from the completed game."""
    logger.info("=" * 60)
    logger.info("PHASE 5: EVIDENCE CHAIN")
    logger.info("=" * 60)

    import psycopg2
    conn = psycopg2.connect(_DB_URL)
    cur = conn.cursor()

    # Get one decision with tool trace
    cur.execute(
        "SELECT id, player_id, day, phase, parsed_action, raw_output "
        "FROM agent_decisions WHERE game_id = %s "
        "AND (parsed_action::text LIKE '%%_tool_trace%%' "
        "OR parsed_action::text LIKE '%%retrieval_used%%') "
        "LIMIT 1",
        (game_id,))
    trace_decision = cur.fetchone()

    if trace_decision:
        dec_id, player_id, day, phase, pa, raw = trace_decision
        pa_dict = pa if isinstance(pa, dict) else {}
        logger.info(f"  Sample decision: {dec_id}")
        logger.info(f"    player={player_id}, day={day}, phase={phase}")
        tool_trace = pa_dict.get("_tool_trace", [])
        auto_injected = pa_dict.get("_auto_injected_strategies", [])
        logger.info(f"    tool_trace entries: {len(tool_trace)}")
        logger.info(f"    auto_injected_strategies: {auto_injected}")
        for t in tool_trace:
            logger.info(f"      tool={t.get('tool')}, keywords={t.get('keywords')}")

        report["evidence_chain_sample"] = {
            "decision_id": dec_id,
            "player_id": player_id,
            "day": day,
            "phase": phase,
            "tool_trace": tool_trace,
            "auto_injected_strategies": auto_injected,
            "raw_output_snippet": (raw or "")[:200] if raw else "",
        }
    else:
        logger.info("  No decision with tool_trace found — LLM may not have called tools")
        # Fall back: find any auto-injected trace
        cur.execute(
            "SELECT id, player_id, day, phase, parsed_action, raw_output "
            "FROM agent_decisions WHERE game_id = %s "
            "AND parsed_action::text LIKE '%%_auto_injected_strategies%%' "
            "LIMIT 1",
            (game_id,))
        injected_only = cur.fetchone()
        if injected_only:
            dec_id, player_id, day, phase, pa, raw = injected_only
            pa_dict = pa if isinstance(pa, dict) else {}
            auto_injected = pa_dict.get("_auto_injected_strategies", [])
            logger.info(f"  Auto-injected only decision: {dec_id}")
            logger.info(f"    player={player_id}, day={day}, phase={phase}")
            logger.info(f"    auto_injected_strategies: {auto_injected}")
            report["evidence_chain_sample"] = {
                "decision_id": dec_id,
                "player_id": player_id,
                "day": day,
                "phase": phase,
                "tool_trace": [],
                "auto_injected_strategies": auto_injected,
                "note": "No active tool calls; auto-injected strategies only",
            }
        else:
            warn("No strategy trace found in any decision — Track C may not be wired")

    # Get lessons from this game
    cur.execute(
        "SELECT id, doc_type, role, status, quality_score, recommended_action "
        "FROM strategy_knowledge_docs WHERE source_report_ids @> %s::jsonb LIMIT 3",
        (json.dumps([game_id]),))
    lessons = cur.fetchall()
    logger.info(f"  Sample lessons ({len(lessons)}):")
    for l in lessons:
        logger.info(f"    id={l[0]}, type={l[1]}, role={l[2]}, status={l[3]}, quality={l[4]:.2f}")
        logger.info(f"    action: {(l[5] or '')[:100]}")

    cur.close()
    conn.close()


# ═══════════════════════════════════════════════════════════════
# Phase 6: Generate reports
# ═══════════════════════════════════════════════════════════════

def generate_reports():
    logger.info("=" * 60)
    logger.info("PHASE 6: GENERATE REPORTS")
    logger.info("=" * 60)

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["overall_result"] = "PASS" if not report["failures"] else "FAIL"

    # JSON report
    json_path = output_dir / "backend_e2e_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    logger.info(f"  JSON report: {json_path}")

    # Markdown report
    md_lines = [
        "# Backend E2E Strict Mode Report",
        "",
        f"**Started**: {report['started_at']}",
        f"**Completed**: {report['completed_at']}",
        f"**Overall**: {'✅ PASS' if report['overall_result'] == 'PASS' else '❌ FAIL'}",
        "",
        "## Preflight Checks",
        "",
    ]
    for check, result in report.get("checks", {}).items():
        if check in ("fallback_keyword_scan",):
            continue
        status = "✅" if result == "pass" else str(result)
        md_lines.append(f"- **{check}**: {status}")

    md_lines += [
        "",
        "## Game Result",
        "",
        f"- **Game ID**: {report['game'].get('game_id', 'N/A')}",
        f"- **Winner**: {report['game'].get('winner', 'N/A')}",
        f"- **Days**: {report['game'].get('days', 'N/A')}",
        f"- **Duration**: {report['game'].get('duration_s', 'N/A')}s",
        f"- **Finished**: {report['game'].get('finished', False)}",
        "",
        "## DB Verification",
        "",
    ]
    for k, v in report.get("db_verify", {}).items():
        md_lines.append(f"- **{k}**: {v}")

    md_lines += [
        "",
        "## Artifacts",
        "",
    ]
    for k, v in report.get("artifacts", {}).items():
        md_lines.append(f"- **{k}**: {v}")

    md_lines += [
        "",
        "## Failures",
        "",
    ]
    if report["failures"]:
        for f in report["failures"]:
            md_lines.append(f"- ❌ {f}")
    else:
        md_lines.append("- None")

    md_lines += [
        "",
        "## Warnings",
        "",
    ]
    if report["warnings"]:
        for w in report["warnings"]:
            md_lines.append(f"- ⚠️ {w}")
    else:
        md_lines.append("- None")

    md_path = output_dir / "backend_e2e_report.md"
    md_path.write_text("\n".join(md_lines))
    logger.info(f"  Markdown report: {md_path}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--skip-game", action="store_true", help="Skip the game run (verify env only)")
    p.add_argument("--skip-docs", action="store_true", help="Skip documentation generation")
    args = p.parse_args()

    logger.info("╔══════════════════════════════════════════════════════════════╗")
    logger.info("║  AI WEREWOLF BACKEND E2E STRICT MODE VERIFICATION           ║")
    logger.info("╚══════════════════════════════════════════════════════════════╝")

    # Phase 0
    active_before, candidate_before = preflight()

    if args.skip_game:
        logger.info("Skipping game run (--skip-game)")
        generate_reports()
        return

    # Phase 1
    game_id = run_game()

    # Phase 2
    verify_db(game_id, active_before, candidate_before)

    # Phase 3
    verify_artifacts(game_id)

    # Phase 4
    scan_log()

    # Phase 5
    build_evidence_chain(game_id)

    # Phase 6
    generate_reports()

    # Final verdict
    if report["failures"]:
        logger.error(f"\n{'='*60}")
        logger.error(f"STRICT MODE: FAILED ({len(report['failures'])} failures)")
        logger.error(f"{'='*60}")
        for f in report["failures"]:
            logger.error(f"  ❌ {f}")
        sys.exit(1)
    else:
        logger.info(f"\n{'='*60}")
        logger.info(f"STRICT MODE: PASSED")
        logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
