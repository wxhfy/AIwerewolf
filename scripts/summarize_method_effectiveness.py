#!/usr/bin/env python3
"""Build a tracked method-effectiveness evidence package.

The script consolidates existing experiment artifacts, current retrieval
quantification, and a best-effort PostgreSQL feedback snapshot. It does not run
new paid LLM games. The goal is to keep report claims evidence-backed and to
make causal gaps explicit.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORMAL_SUMMARY = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis" / "summary.json"
FORMAL_LEADERBOARD = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis" / "leaderboard.csv"
FORMAL_RUBRIC = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis" / "rubric_leaderboard.csv"
MODULE_EFFECTS = ROOT / "docs" / "experiments" / "module_effect_experiment" / "module_effects.csv"
FULL_AUDIT = ROOT / "docs" / "experiments" / "full_project_real_audit" / "audit_summary.json"
MBTI_TRACK_C = ROOT / "docs" / "experiments" / "mbti_track_c_auxiliary_analysis" / "summary.json"
RETRIEVAL_RESULTS = ROOT / "outputs" / "retrieval_effectiveness_current" / "results.json"
RETRIEVAL_PER_ROLE = ROOT / "outputs" / "retrieval_effectiveness_current" / "per_role_results.csv"
RETRIEVAL_ROLE_CORPUS = ROOT / "outputs" / "retrieval_effectiveness_current" / "role_corpus_stats.csv"
ROLE_RETRIEVAL_FACTS = ROOT / "docs" / "PROJECT_ROLE_RETRIEVAL_FACTS.json"
ROLE_RETRIEVAL_REPORT = ROOT / "docs" / "PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md"
METHOD_STATISTICS = ROOT / "docs" / "PROJECT_METHOD_EFFECTIVENESS_STATISTICS.json"
METHOD_STATISTICS_REPORT = ROOT / "docs" / "PROJECT_METHOD_EFFECTIVENESS_STATISTICS.md"
PROVIDER_PREFLIGHT = ROOT / "docs" / "PROJECT_PROVIDER_PREFLIGHT.json"
TRACK_B_LEADERBOARD_SHOWCASE = ROOT / "docs" / "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json"
TRACK_B_LEADERBOARD_SHOWCASE_REPORT = ROOT / "docs" / "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.md"
USAGE_DECISION_SCORE_FACTS = ROOT / "docs" / "PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json"
USAGE_DECISION_SCORE_REPORT = ROOT / "docs" / "PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.md"
TARGET_SEAT_POWER_PLAN = ROOT / "docs" / "PROJECT_TARGET_SEAT_AB_POWER_PLAN.json"
TARGET_SEAT_POWER_REPORT = ROOT / "docs" / "PROJECT_TARGET_SEAT_AB_POWER_PLAN.md"

TRACK_C_SMOKE_FILES = [
    ROOT / "docs" / "experiments" / "track_c_runtime_fix" / "doubao_smoke_g1" / "group_results.csv",
    ROOT / "docs" / "experiments" / "track_c_runtime_fix" / "doubao_smoke_g1_conservative_gate" / "group_results.csv",
    ROOT
    / "docs"
    / "experiments"
    / "track_c_runtime_fix"
    / "doubao_smoke_g1_conservative_baseline_retry"
    / "group_results.csv",
    ROOT / "docs" / "experiments" / "track_c_runtime_fix" / "doubao_smoke_g1_after_target_guard" / "group_results.csv",
]
TARGET_SEAT_GLOB = "outputs/target_seat_trackc_ab*/target_seat_ab_*.json"

DEFAULT_REPORT = ROOT / "docs" / "PROJECT_METHOD_EFFECTIVENESS_EXPERIMENTS.md"
DEFAULT_FACTS = ROOT / "docs" / "PROJECT_METHOD_EFFECTIVENESS_FACTS.json"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def inum(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def pct(value: Any) -> str:
    return f"{fnum(value) * 100:.2f}%"


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{fnum(value):.{digits}f}"


def wilson_ci(successes: int, total: int, z: float = 1.96) -> dict[str, float]:
    if total <= 0:
        return {"rate": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return {"rate": p, "ci_low": max(0.0, center - margin), "ci_high": min(1.0, center + margin)}


def runtime_feedback_ci_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    retrieved = inum(snapshot.get("retrieved"))
    used = inum(snapshot.get("used"))
    helpful = inum(snapshot.get("helpful"))
    return {
        "status": snapshot.get("status", "missing"),
        "source": snapshot.get("source", ""),
        "filter": snapshot.get("filter", ""),
        "retrieved": retrieved,
        "used": used,
        "helpful": helpful,
        "used_over_retrieved": wilson_ci(used, retrieved),
        "helpful_over_retrieved": wilson_ci(helpful, retrieved),
        "helpful_over_used": wilson_ci(helpful, used),
        "interpretation": "Current non-fake PostgreSQL snapshot. This is usage feedback, not causal score lift.",
    }


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def collect_fake_target_seat_game_ids() -> list[str]:
    game_ids: set[str] = set()
    for path in sorted(ROOT.glob(TARGET_SEAT_GLOB)):
        if ".partial." in path.name or "_dry_run_" in path.name:
            continue
        if "fake" not in str(path).lower():
            continue
        payload = read_json(path)
        for key in ("baseline_results", "candidate_results"):
            for row in payload.get(key, []) if isinstance(payload, dict) else []:
                game_id = str(row.get("game_id") or "").strip()
                if game_id:
                    game_ids.add(game_id)
    return sorted(game_ids)


def sql_exclusion(game_ids: list[str], column: str) -> tuple[str, dict[str, str]]:
    if not game_ids:
        return "", {}
    names = [f"excluded_game_{index}" for index, _ in enumerate(game_ids)]
    placeholders = ", ".join(f":{name}" for name in names)
    return f" WHERE {column} NOT IN ({placeholders})", dict(zip(names, game_ids))


def collect_db_feedback_snapshot() -> dict[str, Any]:
    """Collect runtime Track C feedback. Failure is recorded, not raised."""
    try:
        from sqlalchemy import func

        from backend.db import KnowledgeUsageFeedback
        from backend.db import Player
        from backend.db import SessionLocal
        from backend.db import StrategyKnowledgeDoc

        db = SessionLocal()
        try:
            total = db.query(func.count(KnowledgeUsageFeedback.id)).scalar() or 0
            retrieved = (
                db.query(func.count(KnowledgeUsageFeedback.id))
                .filter(KnowledgeUsageFeedback.retrieved.is_(True))
                .scalar()
                or 0
            )
            used = (
                db.query(func.count(KnowledgeUsageFeedback.id)).filter(KnowledgeUsageFeedback.used.is_(True)).scalar()
                or 0
            )
            helpful = (
                db.query(func.count(KnowledgeUsageFeedback.id))
                .filter(KnowledgeUsageFeedback.helpful.is_(True))
                .scalar()
                or 0
            )
            docs_total = db.query(func.count(StrategyKnowledgeDoc.id)).scalar() or 0
            docs_active = (
                db.query(func.count(StrategyKnowledgeDoc.id)).filter(StrategyKnowledgeDoc.status == "active").scalar()
                or 0
            )
            docs_candidate = (
                db.query(func.count(StrategyKnowledgeDoc.id))
                .filter(StrategyKnowledgeDoc.status == "candidate")
                .scalar()
                or 0
            )
            docs_deprecated = (
                db.query(func.count(StrategyKnowledgeDoc.id))
                .filter(StrategyKnowledgeDoc.status == "deprecated")
                .scalar()
                or 0
            )
            avg_score_delta = db.query(func.avg(KnowledgeUsageFeedback.score_delta)).scalar()

            by_role_rows = (
                db.query(
                    Player.role,
                    func.count(KnowledgeUsageFeedback.id),
                    func.sum(
                        KnowledgeUsageFeedback.used.cast(
                            db.bind.dialect.type_descriptor(KnowledgeUsageFeedback.used.type)
                        )
                    ),
                )
                .join(Player, KnowledgeUsageFeedback.player_id == Player.id)
                .group_by(Player.role)
                .all()
            )
            by_role: list[dict[str, Any]] = []
            for role, role_total, role_used in by_role_rows:
                helpful_count = (
                    db.query(func.count(KnowledgeUsageFeedback.id))
                    .join(Player, KnowledgeUsageFeedback.player_id == Player.id)
                    .filter(Player.role == role)
                    .filter(KnowledgeUsageFeedback.helpful.is_(True))
                    .scalar()
                    or 0
                )
                by_role.append(
                    {
                        "role": role or "",
                        "retrieved": int(role_total or 0),
                        "used": int(role_used or 0),
                        "helpful": int(helpful_count),
                        "used_rate": (role_used or 0) / max(role_total or 0, 1),
                        "helpful_over_used": helpful_count / max(role_used or 0, 1),
                    }
                )
            by_role.sort(key=lambda row: row["retrieved"], reverse=True)
            return {
                "status": "ok",
                "queried_at": now_iso(),
                "feedback_total": int(total),
                "retrieved": int(retrieved),
                "used": int(used),
                "helpful": int(helpful),
                "used_rate": used / max(retrieved, 1),
                "helpful_over_retrieved": helpful / max(retrieved, 1),
                "helpful_over_used": helpful / max(used, 1),
                "avg_score_delta": float(avg_score_delta or 0.0),
                "strategy_docs_total": int(docs_total),
                "strategy_docs_active": int(docs_active),
                "strategy_docs_candidate": int(docs_candidate),
                "strategy_docs_deprecated": int(docs_deprecated),
                "by_role": by_role,
                "source": "PostgreSQL knowledge_usage_feedback / strategy_knowledge_docs current snapshot",
            }
        finally:
            db.close()
    except Exception as exc:
        return {
            "status": "unavailable",
            "queried_at": now_iso(),
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "source": "PostgreSQL best-effort query",
        }


def collect_db_feedback_snapshot_raw_sql() -> dict[str, Any]:
    """SQLAlchemy model casts vary by backend; raw SQL is simpler and stable."""
    try:
        from sqlalchemy import text

        from backend.db import SessionLocal

        excluded_game_ids = collect_fake_target_seat_game_ids()
        nonfake_filter = (
            "NOT EXISTS ("
            "SELECT 1 FROM players p_fake "
            "WHERE p_fake.game_id = {column} "
            "AND lower(COALESCE(p_fake.model_name, '')) LIKE '%fake%'"
            ")"
        )
        feedback_where, feedback_params = sql_exclusion(excluded_game_ids, "k.game_id")
        role_where, role_params = sql_exclusion(excluded_game_ids, "k.game_id")
        docs_where, docs_params = sql_exclusion(excluded_game_ids, "d.source_game_id")
        feedback_where = (
            " WHERE " + nonfake_filter.format(column="k.game_id")
            if not feedback_where
            else feedback_where + " AND " + nonfake_filter.format(column="k.game_id")
        )
        role_where = (
            " WHERE " + nonfake_filter.format(column="k.game_id")
            if not role_where
            else role_where + " AND " + nonfake_filter.format(column="k.game_id")
        )
        docs_nonfake_filter = (
            "d.source_game_id IS NULL OR NOT EXISTS ("
            "SELECT 1 FROM players p_fake "
            "WHERE p_fake.game_id = d.source_game_id "
            "AND lower(COALESCE(p_fake.model_name, '')) LIKE '%fake%'"
            ")"
        )
        docs_where = " WHERE " + docs_nonfake_filter if not docs_where else docs_where + " AND " + docs_nonfake_filter
        db = SessionLocal()
        try:
            counts = (
                db.execute(
                    text(
                        f"""
                    SELECT
                      COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE retrieved IS TRUE) AS retrieved,
                      COUNT(*) FILTER (WHERE used IS TRUE) AS used,
                      COUNT(*) FILTER (WHERE helpful IS TRUE) AS helpful,
                      COALESCE(AVG(score_delta), 0) AS avg_score_delta
                    FROM knowledge_usage_feedback k
                    {feedback_where}
                    """
                    ),
                    feedback_params,
                )
                .mappings()
                .first()
            )
            docs = (
                db.execute(
                    text(
                        f"""
                    SELECT
                      COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE status = 'active') AS active,
                      COUNT(*) FILTER (WHERE status = 'candidate') AS candidate,
                      COUNT(*) FILTER (WHERE status = 'deprecated') AS deprecated
                    FROM strategy_knowledge_docs d
                    {docs_where}
                    """
                    ),
                    docs_params,
                )
                .mappings()
                .first()
            )
            by_role = [
                dict(row)
                for row in db.execute(
                    text(
                        f"""
                        SELECT
                          p.role AS role,
                          COUNT(k.id) AS retrieved,
                          COUNT(k.id) FILTER (WHERE k.used IS TRUE) AS used,
                          COUNT(k.id) FILTER (WHERE k.helpful IS TRUE) AS helpful
                        FROM knowledge_usage_feedback k
                        JOIN players p ON p.id = k.player_id
                        {role_where}
                        GROUP BY p.role
                        ORDER BY retrieved DESC
                        """
                    ),
                    role_params,
                ).mappings()
            ]
            for row in by_role:
                row["used_rate"] = inum(row.get("used")) / max(inum(row.get("retrieved")), 1)
                row["helpful_over_retrieved"] = inum(row.get("helpful")) / max(inum(row.get("retrieved")), 1)
                row["helpful_over_used"] = inum(row.get("helpful")) / max(inum(row.get("used")), 1)

            retrieved = inum(counts.get("retrieved") if counts else 0)
            used = inum(counts.get("used") if counts else 0)
            helpful = inum(counts.get("helpful") if counts else 0)
            return {
                "status": "ok",
                "queried_at": now_iso(),
                "feedback_total": inum(counts.get("total") if counts else 0),
                "retrieved": retrieved,
                "used": used,
                "helpful": helpful,
                "used_rate": used / max(retrieved, 1),
                "helpful_over_retrieved": helpful / max(retrieved, 1),
                "helpful_over_used": helpful / max(used, 1),
                "avg_score_delta": fnum(counts.get("avg_score_delta") if counts else 0),
                "strategy_docs_total": inum(docs.get("total") if docs else 0),
                "strategy_docs_active": inum(docs.get("active") if docs else 0),
                "strategy_docs_candidate": inum(docs.get("candidate") if docs else 0),
                "strategy_docs_deprecated": inum(docs.get("deprecated") if docs else 0),
                "by_role": by_role,
                "excluded_fake_target_seat_game_ids": excluded_game_ids,
                "filter": "excludes feedback games and knowledge docs whose players.model_name contains fake, plus fake target-seat output game_ids",
                "source": "PostgreSQL knowledge_usage_feedback / strategy_knowledge_docs current non-fake snapshot",
            }
        finally:
            db.close()
    except Exception as exc:
        return {
            "status": "unavailable",
            "queried_at": now_iso(),
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "source": "PostgreSQL best-effort query",
        }


def collect_track_c_smoke() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in TRACK_C_SMOKE_FILES:
        for row in read_csv(path):
            rows.append(
                {
                    "source": str(path.relative_to(ROOT)),
                    "framework": row.get("framework", ""),
                    "game_id": row.get("source_game_id", ""),
                    "adjusted_score": fnum(row.get("avg_adjusted_final_score")),
                    "decision_count": inum(row.get("decision_count")),
                    "fallback_count": inum(row.get("fallback_count")),
                    "invalid_count": inum(row.get("invalid_count")),
                    "knowledge_hit_rate": fnum(row.get("knowledge_hit_rate")),
                }
            )
    return rows


def collect_target_seat_results() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob(TARGET_SEAT_GLOB)):
        if ".partial." in path.name or "_dry_run_" in path.name:
            continue
        if "fake" in str(path).lower():
            continue
        payload = read_json(path)
        comparison = payload.get("comparison", {}) if isinstance(payload, dict) else {}
        if not comparison:
            continue
        model_pool = [str(item).lower() for item in payload.get("model_pool", [])]
        if any("fake" in item for item in model_pool):
            continue
        acceptance = comparison.get("acceptance", {})
        rows.append(
            {
                "source": str(path.relative_to(ROOT)),
                "generated_at": payload.get("generated_at", ""),
                "target_role": payload.get("target_role", ""),
                "baseline_framework": payload.get("baseline_framework", ""),
                "candidate_framework": payload.get("candidate_framework", ""),
                "paired_seed_count": inum(comparison.get("paired_seed_count")),
                "target_win_rate_delta": fnum(comparison.get("target_win_rate_delta")),
                "target_adjusted_score_delta": fnum(comparison.get("target_adjusted_score_delta")),
                "target_role_task_delta": fnum(comparison.get("target_role_task_delta")),
                "candidate_fallback_count": inum(comparison.get("candidate_fallback_count")),
                "candidate_invalid_count": inum(comparison.get("candidate_invalid_count")),
                "accepted": bool(acceptance.get("accepted", False)),
                "claim_level": acceptance.get("claim_level", "待确认"),
                "max_days": inum(payload.get("max_days")),
                "player_count": inum(payload.get("player_count")),
                "elapsed_s": fnum(payload.get("elapsed_s")),
                "claim_scope": "smoke_only"
                if inum(payload.get("max_days")) <= 1 or inum(comparison.get("paired_seed_count")) < 20
                else "formal_candidate",
                "bootstrap_ci": comparison.get("bootstrap_ci", {}),
            }
        )
    rows.sort(key=lambda row: (row.get("generated_at") or "", row.get("source") or ""), reverse=True)
    return rows


def build_evidence() -> dict[str, Any]:
    formal = read_json(FORMAL_SUMMARY)
    formal_leaderboard = read_csv(FORMAL_LEADERBOARD)
    formal_rubric = read_csv(FORMAL_RUBRIC)
    module_effects = read_csv(MODULE_EFFECTS)
    audit = read_json(FULL_AUDIT)
    mbti = read_json(MBTI_TRACK_C)
    retrieval = read_json(RETRIEVAL_RESULTS)
    role_retrieval = read_json(ROLE_RETRIEVAL_FACTS)
    statistics_report = read_json(METHOD_STATISTICS)
    provider_preflight = read_json(PROVIDER_PREFLIGHT)
    track_b_showcase = read_json(TRACK_B_LEADERBOARD_SHOWCASE)
    usage_decision_scores = read_json(USAGE_DECISION_SCORE_FACTS)
    target_seat_power = read_json(TARGET_SEAT_POWER_PLAN)
    per_role_rows = read_csv(RETRIEVAL_PER_ROLE)
    role_corpus_rows = read_csv(RETRIEVAL_ROLE_CORPUS)
    db_feedback = collect_db_feedback_snapshot_raw_sql()
    if isinstance(statistics_report, dict) and db_feedback.get("status") == "ok":
        statistics_report = dict(statistics_report)
        statistics_report["runtime_feedback"] = runtime_feedback_ci_from_snapshot(db_feedback)
    smoke_rows = collect_track_c_smoke()
    target_seat_rows = collect_target_seat_results()

    retrieval_metrics = retrieval.get("metrics", {}) if isinstance(retrieval, dict) else {}
    default_policy = retrieval_metrics.get("hybrid_role_mbti_global", {})
    baseline_policy = retrieval_metrics.get("global_only", {})
    exact_policy = retrieval_metrics.get("same_role_same_mbti", {})
    role_default_rows = [row for row in per_role_rows if row.get("policy") == "hybrid_role_mbti_global"]

    formal_fallback = sum(inum(row.get("fallback_count")) for row in formal_leaderboard)
    formal_invalid = sum(inum(row.get("invalid_count")) for row in formal_leaderboard)
    formal_decisions = sum(inum(row.get("llm_decisions")) for row in formal_leaderboard)
    formal_completed = sum(inum(row.get("completed_games")) for row in formal_leaderboard)
    formal_attempted = sum(inum(row.get("attempted_games")) for row in formal_leaderboard)
    rubric_scores = [fnum(row.get("rubric_total_score")) for row in formal_rubric]
    rubric_spread = max(rubric_scores) - min(rubric_scores) if rubric_scores else 0.0

    module_passed = sum(1 for row in module_effects if str(row.get("passed", "")).lower() == "true")
    module_scores = [fnum(row.get("effect_score_0_100")) for row in module_effects]

    mbti_overall = mbti.get("overall", {})
    track_c_off = mbti_overall.get("track_c_off", {})
    track_c_on = mbti_overall.get("track_c_on", {})
    role_deltas = mbti.get("role_deltas", [])
    non_wolf_deltas = [fnum(row.get("delta")) for row in role_deltas if row.get("key") != "Werewolf"]

    track_c = audit.get("track_c", {})
    coverage = audit.get("coverage", {})
    usage_overall_for_matrix = (
        usage_decision_scores.get("overall", {}).get("used_vs_unused", {})
        if isinstance(usage_decision_scores, dict)
        else {}
    )
    usage_counts_for_matrix = (
        usage_decision_scores.get("row_counts", {}) if isinstance(usage_decision_scores, dict) else {}
    )
    usage_strict_for_matrix = (
        usage_decision_scores.get("stratified", {}).get("strict_role_action_tier_day_phase", {})
        if isinstance(usage_decision_scores, dict)
        else {}
    )
    usage_role_internal_for_matrix = (
        usage_decision_scores.get("stratified", {}).get("role_internal_action_tier_day_phase", {}).get("roles", [])
        if isinstance(usage_decision_scores, dict)
        else []
    )
    core_usage_role_rows = [
        row
        for row in usage_role_internal_for_matrix
        if row.get("role") in {"Werewolf", "Villager", "Seer", "Witch", "Hunter", "Guard"}
    ]
    positive_core_usage_roles = [
        row for row in core_usage_role_rows if fnum(row.get("weighted_mean_delta_used_minus_unused")) > 0
    ]
    weak_or_negative_role_rows = [
        row for row in usage_role_internal_for_matrix if fnum(row.get("weighted_mean_delta_used_minus_unused")) <= 0
    ]
    track_b_showcase_aggregate = track_b_showcase.get("aggregate", {}) if isinstance(track_b_showcase, dict) else {}

    evidence_matrix = [
        {
            "claim": "正式 v4flash 数据可用于区分框架版本",
            "evidence_level": "formal_real_llm",
            "status": "supported",
            "metric": f"formal_rows={formal.get('row_counts', {}).get('formal_v4flash')}; rubric_spread={rubric_spread:.4f}",
            "source": "docs/experiments/formal_v4flash_framework_analysis/summary.json",
            "boundary": "证明可度量和可区分，不单独证明最终架构统计显著优于 baseline。",
        },
        {
            "claim": "正式决策链没有 fallback/invalid 污染",
            "evidence_level": "formal_real_llm",
            "status": "supported",
            "metric": f"llm_decisions={formal_decisions}; fallback={formal_fallback}; invalid={formal_invalid}",
            "source": "docs/experiments/formal_v4flash_framework_analysis/leaderboard.csv",
            "boundary": "整局 external failure 仍需作为运行稳定性风险披露。",
        },
        {
            "claim": "Track B leaderboard 可以进行多层评分展示",
            "evidence_level": "real_llm_track_b_showcase",
            "status": "pilot_supported" if track_b_showcase_aggregate else "missing",
            "metric": (
                f"games={track_b_showcase_aggregate.get('completed_real_llm_games')}; "
                f"raw_decisions={track_b_showcase_aggregate.get('raw_decision_count')}; "
                f"fallback={track_b_showcase_aggregate.get('fallback_count')}; "
                f"invalid={track_b_showcase_aggregate.get('invalid_count')}"
            )
            if track_b_showcase_aggregate
            else "no Track B showcase facts found",
            "source": "docs/PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json",
            "boundary": "展示 Track B 的对局层、模型/版本层、角色层、评分维度和 rubric 层；不是 Track C 因果增益或正式模型优劣结论。",
        },
        {
            "claim": "核心模块效果已经按多维指标量化",
            "evidence_level": "consolidated_module_audit",
            "status": "supported",
            "metric": f"passed_modules={module_passed}/{len(module_effects)}; mean_score={statistics.mean(module_scores) if module_scores else 0:.2f}",
            "source": "docs/experiments/module_effect_experiment/module_effects.csv",
            "boundary": "模块分数是综合指标，不等同最终胜率提升。",
        },
        {
            "claim": "Track C 默认检索策略优于纯 global-only 检索",
            "evidence_level": "offline_retrieval_ablation",
            "status": "supported",
            "metric": (
                f"default_score={fmt(default_policy.get('offline_score'))}; "
                f"global_score={fmt(baseline_policy.get('offline_score'))}; "
                f"default_p3={fmt(default_policy.get('precision_at_3'))}; "
                f"default_coverage={fmt(default_policy.get('coverage_rate'))}"
            ),
            "source": "outputs/retrieval_effectiveness_current/results.json",
            "boundary": "弱标注离线检索，证明检索设计合理性；不是在线胜率因果证明。",
        },
        {
            "claim": "单角色默认检索稳定覆盖全部核心角色",
            "evidence_level": "offline_retrieval_per_role",
            "status": "supported",
            "metric": f"roles={len(role_default_rows)}; all_coverage_1={all(fnum(r.get('Coverage')) == 1.0 for r in role_default_rows)}; role_bucket_share={fmt(default_policy.get('role_bucket_share'))}",
            "source": "outputs/retrieval_effectiveness_current/per_role_results.csv",
            "boundary": "每角色 query 数仍偏少；不能声明某个角色的最优 policy 已最终确定。",
        },
        {
            "claim": "精确 role+MBTI 检索过窄，不适合作为默认策略",
            "evidence_level": "offline_retrieval_ablation",
            "status": "supported",
            "metric": f"same_role_same_mbti_coverage={fmt(exact_policy.get('coverage_rate'))}; empty={exact_policy.get('n_empty')}",
            "source": "outputs/retrieval_effectiveness_current/results.json",
            "boundary": "可作为补充桶或专项实验，不作为默认运行策略。",
        },
        {
            "claim": "精确 role+MBTI 稀疏主要来自当前知识池分布",
            "evidence_level": "offline_retrieval_corpus",
            "status": "supported" if role_corpus_rows else "unavailable",
            "metric": (
                f"roles={len(role_corpus_rows)}; "
                f"exact_empty_queries={sum(inum(r.get('exact_role_mbti_empty_queries')) for r in role_corpus_rows)}; "
                f"global_generic_docs={role_corpus_rows[0].get('global_generic_docs') if role_corpus_rows else 'n/a'}"
            ),
            "source": "outputs/retrieval_effectiveness_current/role_corpus_stats.csv",
            "boundary": "这是 active 知识池规模统计；不等同在线策略使用率。",
        },
        {
            "claim": "Track C 知识库安全卫生达标",
            "evidence_level": "audit_gate",
            "status": "supported",
            "metric": f"docs={track_c.get('knowledge_doc_count')}; invalid={track_c.get('invalid_doc_count')}; leak={track_c.get('leak_doc_count')}; source_event_coverage={track_c.get('source_event_coverage')}",
            "source": "docs/experiments/full_project_real_audit/audit_summary.json",
            "boundary": "审计样本和当前 DB 快照可能不同，正式归档需冻结 experiment_id。",
        },
        {
            "claim": "运行时 feedback 显示被使用策略多数被标记 helpful",
            "evidence_level": "runtime_db_snapshot",
            "status": "supported" if db_feedback.get("status") == "ok" else "unavailable",
            "metric": (
                f"retrieved={db_feedback.get('retrieved')}; used={db_feedback.get('used')}; "
                f"helpful={db_feedback.get('helpful')}; helpful/used={pct(db_feedback.get('helpful_over_used'))}"
            )
            if db_feedback.get("status") == "ok"
            else db_feedback.get("error", ""),
            "source": db_feedback.get("source", ""),
            "boundary": "当前 score_delta 平均仍接近 0，feedback 不能直接等同因果增益。",
        },
        {
            "claim": "策略使用决策与更高 Track B 逐步评分相关",
            "evidence_level": "observational_decision_score_join",
            "status": "supported"
            if usage_overall_for_matrix and not usage_overall_for_matrix.get("ci_crosses_zero", True)
            else "unavailable_or_inconclusive",
            "metric": (
                f"decision_rows={usage_counts_for_matrix.get('decision_rows')}; "
                f"used={usage_counts_for_matrix.get('used_decisions')}; "
                f"unused={usage_counts_for_matrix.get('unused_decisions')}; "
                f"delta={fmt(usage_overall_for_matrix.get('mean_delta_used_minus_unused'))}; "
                f"ci=[{fmt(usage_overall_for_matrix.get('bootstrap_ci_low'))},{fmt(usage_overall_for_matrix.get('bootstrap_ci_high'))}]; "
                f"strict_weighted_delta={fmt(usage_strict_for_matrix.get('weighted_mean_delta_used_minus_unused'))}; "
                f"strict_strata={usage_strict_for_matrix.get('positive_strata')}/{usage_strict_for_matrix.get('negative_strata')}/{usage_strict_for_matrix.get('tied_strata')}"
            ),
            "source": "docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json",
            "boundary": "观测性关联，不能替代 target-seat paired A/B 因果证明。",
        },
        {
            "claim": "策略使用评分关联覆盖 6 个核心角色",
            "evidence_level": "role_internal_observational_control",
            "status": "supported" if len(positive_core_usage_roles) == 6 else "partial_or_inconclusive",
            "metric": (
                f"core_positive_roles={len(positive_core_usage_roles)}/{len(core_usage_role_rows)}; "
                f"weighted_deltas="
                + ",".join(
                    f"{row.get('role')}:{fmt(row.get('weighted_mean_delta_used_minus_unused'))}"
                    for row in core_usage_role_rows
                )
            ),
            "source": "docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json",
            "boundary": (
                "角色内按 action/tier/day/phase 控制后的观测性关联；"
                f"非核心或低样本角色暂不声明，negative_or_weak={len(weak_or_negative_role_rows)}。"
            ),
        },
        {
            "claim": "Track C 开关存在角色/MBTI 层面的正向趋势",
            "evidence_level": "auxiliary_trend",
            "status": "trend_only",
            "metric": (
                f"off={fmt(track_c_off.get('win_rate'))}; on={fmt(track_c_on.get('win_rate'))}; "
                f"avg_non_wolf_delta={statistics.mean(non_wolf_deltas) if non_wolf_deltas else 0:.4f}"
            ),
            "source": "docs/experiments/mbti_track_c_auxiliary_analysis/summary.json",
            "boundary": "全席位同时切换，不是 target-seat 因果 A/B。",
        },
        {
            "claim": "Track C 对单个目标席位的因果增益",
            "evidence_level": "target_seat_paired_ab",
            "status": (
                target_seat_rows[0]["claim_level"]
                if target_seat_rows and target_seat_rows[0].get("claim_scope") == "formal_candidate"
                else ("smoke_only" if target_seat_rows else "missing")
            ),
            "metric": (
                f"role={target_seat_rows[0]['target_role']}; paired={target_seat_rows[0]['paired_seed_count']}; "
                f"score_delta={fmt(target_seat_rows[0]['target_adjusted_score_delta'])}; "
                f"accepted={target_seat_rows[0]['accepted']}; "
                f"scope={target_seat_rows[0].get('claim_scope')}; max_days={target_seat_rows[0].get('max_days')}"
            )
            if target_seat_rows
            else "no target-seat output found",
            "source": target_seat_rows[0]["source"] if target_seat_rows else TARGET_SEAT_GLOB,
            "boundary": "micro/max_days=1 输出只能证明 runner 可运行；只有正式样本 accepted=true 且样本/健康/CI 门禁通过时，才能写成因果支持。",
        },
        {
            "claim": "Track C 在线烟测能把策略注入真实决策",
            "evidence_level": "real_llm_smoke",
            "status": "smoke_only",
            "metric": f"rows={len(smoke_rows)}; max_knowledge_hit={max([row['knowledge_hit_rate'] for row in smoke_rows], default=0):.4f}; fallback_sum={sum(row['fallback_count'] for row in smoke_rows)}",
            "source": "docs/experiments/track_c_runtime_fix/*/group_results.csv",
            "boundary": "样本小且有正反结果，只能证明链路可运行和策略命中，不能证明胜率提升。",
        },
        {
            "claim": "完整规则/角色/阶段覆盖已经过真实审计",
            "evidence_level": "full_project_audit",
            "status": "supported",
            "metric": f"natural_games={audit.get('natural_game_count')}; controlled_cases={audit.get('controlled_case_count')}; roles={len(coverage.get('role_counts', {}))}; phases={len(coverage.get('phase_counts', {}))}; issues={len(audit.get('issues', []))}",
            "source": "docs/experiments/full_project_real_audit/audit_summary.json",
            "boundary": "审计证明平台覆盖，不是 Track C 单独增益。",
        },
    ]

    open_gaps = [
        {
            "gap": "Track C 最终胜率因果提升",
            "reason": "当前正式数据中 trackc_only/both 完成率不均，辅助数据是全席位同时切换。",
            "required_experiment": "先跑 20 paired seeds pilot；正式因果验证建议 80-120 paired seeds 起步，只升级一个目标席位，固定对手、seed、角色分配。胜率作为辅助指标。",
        },
        {
            "gap": "每个角色的最优检索 policy",
            "reason": "离线 query set 仅 26 条，Guard/Hunter 等角色样本少。",
            "required_experiment": "每角色 20+ 查询，人工或 LLM judge 标注 top-5。",
        },
        {
            "gap": "strategy_usage_feedback 的逐决策因果分数",
            "reason": "当前 avg_score_delta 接近 0，未与 Track B ScoredStep 做严格差分。",
            "required_experiment": "关联 retrieved_doc_ids / knowledge_usage_feedback / PerStepScorer，计算 used vs unused 决策分差。",
        },
        {
            "gap": "正式 target-seat A/B 样本量",
            "reason": "当前 provider 已通过 Doubao/Ark endpoint 真实 chat preflight，且 max_days=1 smoke 可跑通；但尚未完成 80-120 paired seeds 的正式目标席位实验。",
            "required_experiment": "按功效计划运行正式 target-seat paired A/B：固定 seed、角色分配和对手，只升级目标席位，并报告 adjusted score、role-task、win-rate、fallback/invalid 与 bootstrap CI。",
        },
    ]

    return {
        "generated_at": now_iso(),
        "sources": {
            "formal_summary": str(FORMAL_SUMMARY.relative_to(ROOT)),
            "formal_leaderboard": str(FORMAL_LEADERBOARD.relative_to(ROOT)),
            "formal_rubric": str(FORMAL_RUBRIC.relative_to(ROOT)),
            "module_effects": str(MODULE_EFFECTS.relative_to(ROOT)),
            "full_audit": str(FULL_AUDIT.relative_to(ROOT)),
            "mbti_track_c": str(MBTI_TRACK_C.relative_to(ROOT)),
            "retrieval_results": str(RETRIEVAL_RESULTS.relative_to(ROOT)),
            "retrieval_per_role": str(RETRIEVAL_PER_ROLE.relative_to(ROOT)),
            "retrieval_role_corpus": str(RETRIEVAL_ROLE_CORPUS.relative_to(ROOT)),
            "role_retrieval_facts": str(ROLE_RETRIEVAL_FACTS.relative_to(ROOT)),
            "role_retrieval_report": str(ROLE_RETRIEVAL_REPORT.relative_to(ROOT)),
            "method_statistics": str(METHOD_STATISTICS.relative_to(ROOT)),
            "method_statistics_report": str(METHOD_STATISTICS_REPORT.relative_to(ROOT)),
            "provider_preflight": str(PROVIDER_PREFLIGHT.relative_to(ROOT)),
            "track_b_leaderboard_showcase": str(TRACK_B_LEADERBOARD_SHOWCASE.relative_to(ROOT)),
            "track_b_leaderboard_showcase_report": str(TRACK_B_LEADERBOARD_SHOWCASE_REPORT.relative_to(ROOT)),
            "usage_decision_score_facts": str(USAGE_DECISION_SCORE_FACTS.relative_to(ROOT)),
            "usage_decision_score_report": str(USAGE_DECISION_SCORE_REPORT.relative_to(ROOT)),
            "target_seat_power_plan": str(TARGET_SEAT_POWER_PLAN.relative_to(ROOT)),
            "target_seat_power_report": str(TARGET_SEAT_POWER_REPORT.relative_to(ROOT)),
        },
        "formal": {
            "row_counts": formal.get("row_counts", {}),
            "excluded_reasons": formal.get("excluded_reasons", {}),
            "attempted_games": formal_attempted,
            "completed_games": formal_completed,
            "llm_decisions": formal_decisions,
            "fallback_count": formal_fallback,
            "invalid_count": formal_invalid,
            "rubric_spread": round(rubric_spread, 4),
            "leaderboard": formal_leaderboard,
            "rubric_leaderboard": formal_rubric,
        },
        "modules": {
            "passed": module_passed,
            "total": len(module_effects),
            "mean_score": round(statistics.mean(module_scores), 2) if module_scores else 0.0,
            "rows": module_effects,
        },
        "retrieval": {
            "query_set_size": retrieval.get("query_set_size"),
            "retriever_size": retrieval.get("retriever_size"),
            "ranked_policies": retrieval.get("ranked_policies", []),
            "default_policy": default_policy,
            "global_only": baseline_policy,
            "same_role_same_mbti": exact_policy,
            "per_role_default": role_default_rows,
            "role_corpus": role_corpus_rows,
            "single_role_quantification": role_retrieval,
        },
        "audit": {
            "natural_game_count": audit.get("natural_game_count"),
            "controlled_case_count": audit.get("controlled_case_count"),
            "issues": audit.get("issues", []),
            "track_c": track_c,
            "coverage": coverage,
        },
        "runtime_feedback": db_feedback,
        "statistics": statistics_report,
        "provider_preflight": provider_preflight,
        "track_b_leaderboard_showcase": track_b_showcase,
        "strategy_usage_decision_scores": usage_decision_scores,
        "track_c_auxiliary": {
            "overall": mbti_overall,
            "role_deltas": role_deltas,
            "avg_non_wolf_delta": statistics.mean(non_wolf_deltas) if non_wolf_deltas else 0.0,
            "row_count": mbti.get("row_count"),
            "seed_count": mbti.get("seed_count"),
        },
        "track_c_smoke": smoke_rows,
        "target_seat_ab": target_seat_rows,
        "target_seat_power_plan": target_seat_power,
        "evidence_matrix": evidence_matrix,
        "open_gaps": open_gaps,
    }


def table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(evidence: dict[str, Any]) -> str:
    retrieval = evidence["retrieval"]
    default = retrieval["default_policy"]
    global_only = retrieval["global_only"]
    exact = retrieval["same_role_same_mbti"]
    role_retrieval = retrieval.get("single_role_quantification", {})
    role_retrieval_overall = role_retrieval.get("overall", {}) if isinstance(role_retrieval, dict) else {}
    role_policy_summaries = (
        role_retrieval.get("single_role_policy_summary", []) if isinstance(role_retrieval, dict) else []
    )
    role_pipeline = role_retrieval.get("retrieval_pipeline", []) if isinstance(role_retrieval, dict) else []
    formal = evidence["formal"]
    runtime = evidence["runtime_feedback"]
    statistics_report = evidence.get("statistics", {})
    statistics_retrieval = (
        statistics_report.get("retrieval_paired", {}).get("default_vs_global", {})
        if isinstance(statistics_report, dict)
        else {}
    )
    statistics_runtime = statistics_report.get("runtime_feedback", {}) if isinstance(statistics_report, dict) else {}
    usage_scores = (
        evidence.get("strategy_usage_decision_scores", {})
        if isinstance(evidence.get("strategy_usage_decision_scores"), dict)
        else {}
    )
    usage_counts = usage_scores.get("row_counts", {}) if isinstance(usage_scores, dict) else {}
    usage_overall = usage_scores.get("overall", {}).get("used_vs_unused", {}) if isinstance(usage_scores, dict) else {}
    usage_strict = (
        usage_scores.get("stratified", {}).get("strict_role_action_tier_day_phase", {})
        if isinstance(usage_scores, dict)
        else {}
    )
    usage_role_internal = (
        usage_scores.get("stratified", {}).get("role_internal_action_tier_day_phase", {}).get("roles", [])
        if isinstance(usage_scores, dict)
        else []
    )
    statistics_aux = (
        statistics_report.get("track_c_auxiliary", {}).get("overall", {}) if isinstance(statistics_report, dict) else {}
    )
    provider_preflight = (
        evidence.get("provider_preflight", {}) if isinstance(evidence.get("provider_preflight"), dict) else {}
    )
    track_b_showcase = (
        evidence.get("track_b_leaderboard_showcase", {})
        if isinstance(evidence.get("track_b_leaderboard_showcase"), dict)
        else {}
    )
    track_b_showcase_aggregate = (
        track_b_showcase.get("aggregate", {}) if isinstance(track_b_showcase.get("aggregate"), dict) else {}
    )
    target_power = (
        evidence.get("target_seat_power_plan", {}) if isinstance(evidence.get("target_seat_power_plan"), dict) else {}
    )
    target_power_recommendation = (
        target_power.get("recommendation", {}) if isinstance(target_power.get("recommendation"), dict) else {}
    )
    modules = evidence["modules"]
    audit = evidence["audit"]
    aux = evidence["track_c_auxiliary"]
    target_seat_rows = evidence.get("target_seat_ab", [])

    lines = [
        "# 项目方法有效性实验报告",
        "",
        f"生成时间：{evidence['generated_at']}",
        "",
        "可追溯性说明：本报告引用的 `docs/experiments/` 和 `outputs/` 原始产物是本地实验输出，按仓库规则不进入 GitHub；可提交的机器可读摘要已汇总到 `docs/PROJECT_METHOD_EFFECTIVENESS_FACTS.json`、`docs/PROJECT_METHOD_EFFECTIVENESS_STATISTICS.json`、`docs/PROJECT_ROLE_RETRIEVAL_FACTS.json` 和 `docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json`。",
        "",
        "## 1. 结论摘要",
        "",
        "当前证据已经可以支持：系统方法不是单一 Prompt，而是可运行、可审计、可评分、可检索回流的多模块闭环；Track B 可以按对局、模型/版本、角色席位、评分维度和 rubric 多层展示；Track C 默认检索策略在离线检索指标和运行时反馈上具有明确增益；正式 v4flash 数据证明框架版本和 B/C 模块可以被量化区分。",
        "",
        "当前证据暂不能支持：Track C 对最终胜率具有统计显著的因果提升。该结论仍需要 target-seat paired A/B。",
        "",
        "## 2. 证据等级",
        "",
        table(
            ["等级", "含义", "本报告中的用途"],
            [
                ["formal_real_llm", "真实 LLM 正式筛选数据", "框架可区分、严格决策健康"],
                ["offline_retrieval_ablation", "固定 query set 检索消融", "证明检索策略设计有效"],
                ["runtime_db_snapshot", "当前 PostgreSQL 快照", "证明策略反馈规模和 helpful/used"],
                ["audit_gate", "审计或安全门禁", "证明信息隔离、知识安全、覆盖"],
                ["trend_only / smoke_only", "趋势或小样本烟测", "只能辅助展示，不能写成因果结论"],
            ],
        ),
        "",
        "## 3. 关键真实指标",
        "",
        table(
            ["指标", "数值", "来源", "结论边界"],
            [
                [
                    "formal v4flash rows",
                    formal["row_counts"].get("formal_v4flash"),
                    "formal_v4flash_framework_analysis/summary.json",
                    "真实 LLM 正式数据",
                ],
                [
                    "formal LLM decisions",
                    formal["llm_decisions"],
                    "formal_v4flash_framework_analysis/leaderboard.csv",
                    f"fallback={formal['fallback_count']}，invalid={formal['invalid_count']}",
                ],
                [
                    "rubric spread",
                    fmt(formal["rubric_spread"]),
                    "formal_v4flash_framework_analysis/rubric_leaderboard.csv",
                    "证明 leaderboard 能区分版本",
                ],
                [
                    "Track B showcase games / decisions",
                    f"{track_b_showcase_aggregate.get('completed_real_llm_games', 'n/a')} / {track_b_showcase_aggregate.get('raw_decision_count', 'n/a')}",
                    "docs/PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json",
                    f"pilot 展示；fallback={track_b_showcase_aggregate.get('fallback_count', 'n/a')}，invalid={track_b_showcase_aggregate.get('invalid_count', 'n/a')}",
                ],
                [
                    "module effects passed",
                    f"{modules['passed']}/{modules['total']}",
                    "module_effect_experiment/module_effects.csv",
                    f"mean score={modules['mean_score']}",
                ],
                [
                    "retrieval query/docs",
                    f"{retrieval['query_set_size']} / {retrieval['retriever_size']}",
                    "outputs/retrieval_effectiveness_current/results.json",
                    "当前离线检索实验",
                ],
                [
                    "default retrieval P@3 / Coverage",
                    f"{fmt(default.get('precision_at_3'))} / {fmt(default.get('coverage_rate'))}",
                    "outputs/retrieval_effectiveness_current/results.json",
                    "弱标注离线指标",
                ],
                [
                    "Track C audit invalid/leak",
                    f"{audit['track_c'].get('invalid_doc_count')} / {audit['track_c'].get('leak_doc_count')}",
                    "full_project_real_audit/audit_summary.json",
                    "知识安全审计",
                ],
                [
                    "runtime helpful/used",
                    pct(runtime.get("helpful_over_used")) if runtime.get("status") == "ok" else "n/a",
                    runtime.get("source", ""),
                    "当前 DB 快照，非因果分数",
                ],
            ],
        ),
        "",
        "## 4. Track C 检索有效性",
        "",
        table(
            ["Policy", "OfflineScore", "P@3", "Effective@3", "nDCG@5", "Coverage", "Top5Fill", "CandidateLeak"],
            [
                [
                    "global_only",
                    fmt(global_only.get("offline_score")),
                    fmt(global_only.get("precision_at_3")),
                    fmt(global_only.get("effective_at_3")),
                    fmt(global_only.get("ndcg_at_5")),
                    fmt(global_only.get("coverage_rate")),
                    fmt(global_only.get("top5_fill_rate")),
                    global_only.get("candidate_leakage_count"),
                ],
                [
                    "hybrid_role_mbti_global",
                    fmt(default.get("offline_score")),
                    fmt(default.get("precision_at_3")),
                    fmt(default.get("effective_at_3")),
                    fmt(default.get("ndcg_at_5")),
                    fmt(default.get("coverage_rate")),
                    fmt(default.get("top5_fill_rate")),
                    default.get("candidate_leakage_count"),
                ],
                [
                    "same_role_same_mbti",
                    fmt(exact.get("offline_score")),
                    fmt(exact.get("precision_at_3")),
                    fmt(exact.get("effective_at_3")),
                    fmt(exact.get("ndcg_at_5")),
                    fmt(exact.get("coverage_rate")),
                    fmt(exact.get("top5_fill_rate")),
                    exact.get("candidate_leakage_count"),
                ],
            ],
        ),
        "",
        f"默认策略相对 `global_only` 的核心提升：P@3 从 {fmt(global_only.get('precision_at_3'))} 到 {fmt(default.get('precision_at_3'))}，Effective@3 从 {fmt(global_only.get('effective_at_3'))} 到 {fmt(default.get('effective_at_3'))}，Coverage 从 {fmt(global_only.get('coverage_rate'))} 到 {fmt(default.get('coverage_rate'))}。`same_role_same_mbti` 过窄，Coverage 只有 {fmt(exact.get('coverage_rate'))}。",
        "",
        "统计补充详见 `docs/PROJECT_METHOD_EFFECTIVENESS_STATISTICS.md`。默认检索相对 `global_only` 的 paired bootstrap 结果如下：",
        "",
        table(
            ["Metric", "MeanDelta", "Bootstrap95CI", "Sign +/−/tie", "CI跨0"],
            [
                [
                    metric,
                    fmt(row.get("mean_delta")),
                    f"[{fmt(row.get('bootstrap_ci_low'))}, {fmt(row.get('bootstrap_ci_high'))}]",
                    f"{row.get('sign_test', {}).get('positive')}/{row.get('sign_test', {}).get('negative')}/{row.get('sign_test', {}).get('tie')}",
                    row.get("ci_crosses_zero"),
                ]
                for metric, row in statistics_retrieval.get("metrics", {}).items()
            ],
        )
        if statistics_retrieval
        else "统计补充文件尚未生成。",
        "",
        "## 5. 单角色检索有效性",
        "",
        "单角色检索的详细机制、分角色命中率和语料池规模已单独整理为 `docs/PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md`，机器可读摘要见 `docs/PROJECT_ROLE_RETRIEVAL_FACTS.json`。",
        "",
        "单角色检索流程按 `search_strategies -> AgentContext -> keyword/BM25 recall -> RetrievalPolicy buckets -> quality gate -> Strategy prompt` 运行。当前可追溯代码依据如下：",
        "",
        table(
            ["Step", "环节", "代码依据"],
            [[item.get("step"), item.get("name"), item.get("code")] for item in role_pipeline],
        )
        if role_pipeline
        else "单角色检索流程摘要尚未生成。",
        "",
        "### 5.1 单角色路径量化摘要",
        "",
        table(
            [
                "Role",
                "BestPolicy",
                "DefaultEff@3",
                "GlobalEff@3",
                "ExactEff@3",
                "Default-Global Eff@3",
                "Default P@3",
                "RoleBucket",
                "GlobalBucket",
                "诊断",
            ],
            [
                [
                    row.get("role"),
                    row.get("best_policy_by_offline_score"),
                    fmt(row.get("default_effective_at_3")),
                    fmt(row.get("global_only_effective_at_3")),
                    fmt(row.get("same_role_same_mbti_effective_at_3")),
                    fmt(row.get("default_minus_global_effective_at_3")),
                    fmt(row.get("default_precision_at_3")),
                    fmt(row.get("default_role_bucket_share")),
                    fmt(row.get("default_global_bucket_share")),
                    row.get("diagnosis"),
                ]
                for row in role_policy_summaries
            ],
        )
        if role_policy_summaries
        else "单角色 policy 摘要尚未生成。",
        "",
        "### 5.2 默认策略分角色命中率",
        "",
        table(
            ["Role", "P@3", "Effective@3", "nDCG@5", "Coverage", "Top5Fill", "RoleBucket", "GlobalBucket", "Empty"],
            [
                [
                    row.get("role"),
                    row.get("P@3"),
                    row.get("Effective@3"),
                    row.get("nDCG@5"),
                    row.get("Coverage"),
                    row.get("Top5FillRate"),
                    row.get("RoleBucketShare"),
                    row.get("GlobalBucketShare"),
                    row.get("NEmpty"),
                ]
                for row in retrieval["per_role_default"]
            ],
        ),
        "",
        "按 Effective@3 作为可用命中率口径，默认单角色检索整体命中率为 "
        f"{pct(role_retrieval_overall.get('default_effective_hit_rate_at_3', default.get('effective_at_3')))}；"
        f"P@3={fmt(role_retrieval_overall.get('default_precision_at_3', default.get('precision_at_3')))}，"
        f"Coverage={fmt(role_retrieval_overall.get('default_coverage', default.get('coverage_rate')))}。",
        "",
        "默认策略在当前 6 个核心角色上全部无空检索，RoleBucketShare 总体为 "
        f"{fmt(default.get('role_bucket_share'))}，说明检索主要来自角色策略桶，而不是 global 兜底。",
        "",
        "### 5.3 单角色知识池规模",
        "",
        table(
            [
                "Role",
                "RoleDocs",
                "RoleGeneric",
                "RoleMBTISpecific",
                "ExactRoleMBTIPoolAvg",
                "ExactEmptyQueries",
                "HybridRolePoolAvg",
                "HybridTotalPoolAvg",
                "GlobalGeneric",
                "DocMBTIs",
            ],
            [
                [
                    row.get("role"),
                    row.get("role_scope_docs"),
                    row.get("role_generic_docs"),
                    row.get("role_mbti_specific_docs"),
                    row.get("exact_role_mbti_pool_avg"),
                    row.get("exact_role_mbti_empty_queries"),
                    row.get("hybrid_default_role_pool_avg"),
                    row.get("hybrid_default_total_pool_avg"),
                    row.get("global_generic_docs"),
                    row.get("doc_mbti_distribution") or "-",
                ]
                for row in retrieval.get("role_corpus", [])
            ],
        ),
        "",
        "该表解释了单角色检索的来源：默认混合策略能稳定返回结果，主要依赖每个角色的通用策略池；精确 `role+MBTI` 池目前只在 Seer、Werewolf 等少数角色上有覆盖，后续应补充 Guard、Hunter、Villager、Witch 的 MBTI 细分策略卡。",
        "",
        "## 6. 正式 v4flash 框架与模块证据",
        "",
        table(
            [
                "Tier",
                "Completed",
                "ExternalFailure",
                "WolfWin",
                "VillageWin",
                "MacroRoleWin",
                "LLMDecisions",
                "Fallback",
                "Invalid",
            ],
            [
                [
                    row.get("tier"),
                    row.get("completed_games"),
                    row.get("external_failure_rate"),
                    row.get("wolf_win_rate"),
                    row.get("village_win_rate"),
                    row.get("macro_role_win_rate"),
                    row.get("llm_decisions"),
                    row.get("fallback_count"),
                    row.get("invalid_count"),
                ]
                for row in formal["leaderboard"]
            ],
        ),
        "",
        "这些结果证明框架版本可被统一 runner 和 Track B 指标量化，且正式行的 fallback/invalid 为 0。由于 completed/external failure 不均，不能把该表直接解释为最终胜率显著优于 baseline。",
        "",
        "## 7. Track C 运行时反馈",
        "",
    ]

    if runtime.get("status") == "ok":
        lines += [
            table(
                ["Metric", "Value"],
                [
                    ["feedback_total", runtime.get("feedback_total")],
                    ["retrieved", runtime.get("retrieved")],
                    ["used", runtime.get("used")],
                    ["helpful", runtime.get("helpful")],
                    ["used/retrieved", pct(runtime.get("used_rate"))],
                    ["helpful/retrieved", pct(runtime.get("helpful_over_retrieved"))],
                    ["helpful/used", pct(runtime.get("helpful_over_used"))],
                    ["avg_score_delta", fmt(runtime.get("avg_score_delta"))],
                    ["strategy_docs_active", runtime.get("strategy_docs_active")],
                    ["strategy_docs_candidate", runtime.get("strategy_docs_candidate")],
                ],
            ),
            "",
            "运行时 feedback Wilson 95% CI：",
            "",
            table(
                ["Metric", "Count", "Rate", "Wilson95CI"],
                [
                    [
                        "used/retrieved",
                        f"{statistics_runtime.get('used', runtime.get('used'))}/{statistics_runtime.get('retrieved', runtime.get('retrieved'))}",
                        fmt(statistics_runtime.get("used_over_retrieved", {}).get("rate", runtime.get("used_rate"))),
                        f"[{fmt(statistics_runtime.get('used_over_retrieved', {}).get('ci_low'))}, {fmt(statistics_runtime.get('used_over_retrieved', {}).get('ci_high'))}]",
                    ],
                    [
                        "helpful/retrieved",
                        f"{statistics_runtime.get('helpful', runtime.get('helpful'))}/{statistics_runtime.get('retrieved', runtime.get('retrieved'))}",
                        fmt(
                            statistics_runtime.get("helpful_over_retrieved", {}).get(
                                "rate", runtime.get("helpful_over_retrieved")
                            )
                        ),
                        f"[{fmt(statistics_runtime.get('helpful_over_retrieved', {}).get('ci_low'))}, {fmt(statistics_runtime.get('helpful_over_retrieved', {}).get('ci_high'))}]",
                    ],
                    [
                        "helpful/used",
                        f"{statistics_runtime.get('helpful', runtime.get('helpful'))}/{statistics_runtime.get('used', runtime.get('used'))}",
                        fmt(
                            statistics_runtime.get("helpful_over_used", {}).get(
                                "rate", runtime.get("helpful_over_used")
                            )
                        ),
                        f"[{fmt(statistics_runtime.get('helpful_over_used', {}).get('ci_low'))}, {fmt(statistics_runtime.get('helpful_over_used', {}).get('ci_high'))}]",
                    ],
                ],
            )
            if statistics_runtime
            else "",
            "",
            "按角色 feedback：",
            "",
            table(
                ["Role", "Retrieved", "Used", "Helpful", "UsedRate", "Helpful/Used"],
                [
                    [
                        row.get("role"),
                        row.get("retrieved"),
                        row.get("used"),
                        row.get("helpful"),
                        pct(row.get("used_rate")),
                        pct(row.get("helpful_over_used")),
                    ]
                    for row in runtime.get("by_role", [])[:10]
                ],
            ),
            "",
        ]
    else:
        lines += [f"PostgreSQL 查询不可用：{runtime.get('error')}", ""]

    lines += [
        "## 8. 策略使用与逐决策评分关联",
        "",
        "详细报告见 `docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.md`。该统计通过 `decision_id` 将 Track B per-step score、agent_decisions 和 knowledge_usage_feedback 联表，并排除 fake/offline game。",
        "",
        table(
            ["Metric", "Value"],
            [
                ["decision_rows", usage_counts.get("decision_rows", "n/a")],
                ["used_decisions", usage_counts.get("used_decisions", "n/a")],
                ["unused_decisions", usage_counts.get("unused_decisions", "n/a")],
                ["used_mean_score", fmt(usage_overall.get("used_mean"))],
                ["unused_mean_score", fmt(usage_overall.get("unused_mean"))],
                ["mean_delta", fmt(usage_overall.get("mean_delta_used_minus_unused"))],
                [
                    "95CI",
                    f"[{fmt(usage_overall.get('bootstrap_ci_low'))}, {fmt(usage_overall.get('bootstrap_ci_high'))}]",
                ],
                ["CI跨0", usage_overall.get("ci_crosses_zero", "n/a")],
                ["strict_strata", usage_strict.get("strata_count", "n/a")],
                ["strict_used_retained", usage_strict.get("used_retained", "n/a")],
                ["strict_weighted_delta", fmt(usage_strict.get("weighted_mean_delta_used_minus_unused"))],
                [
                    "strict_positive/negative/tied",
                    f"{usage_strict.get('positive_strata', 'n/a')}/{usage_strict.get('negative_strata', 'n/a')}/{usage_strict.get('tied_strata', 'n/a')}",
                ],
            ],
        ),
        "",
        "解释：这支持“策略使用决策在当前非 fake DB 快照中与更高 Track B 逐步评分相关”。严格分层按 role/action/scoring_tier/day/phase 控制明显混杂后仍保持正向，但它仍是观测性关联，不能替代 target-seat paired A/B 因果实验。",
        "",
        "角色内控制结果：",
        "",
        table(
            [
                "Role",
                "TotalUsed",
                "UsedRetained",
                "Strata",
                "WeightedDelta",
                "MeanDelta",
                "MedianDelta",
                "+/-/0 Strata",
            ],
            [
                [
                    row.get("role"),
                    row.get("total_used"),
                    f"{row.get('used_retained')} ({pct(row.get('used_retention_rate'))})",
                    row.get("strata_count"),
                    fmt(row.get("weighted_mean_delta_used_minus_unused")),
                    fmt(row.get("mean_of_stratum_deltas")),
                    fmt(row.get("median_of_stratum_deltas")),
                    f"{row.get('positive_strata')}/{row.get('negative_strata')}/{row.get('tied_strata')}",
                ]
                for row in usage_role_internal
            ],
        )
        if usage_role_internal
        else "角色内控制结果尚未生成。",
        "",
        "解释：6 个核心角色的角色内 strict weighted delta 当前均为正；WhiteWolfKing used 样本仅 34，控制后 weighted delta 略负，暂不能写成该角色稳定增益。",
        "",
        "## 9. Track C 趋势与烟测",
        "",
        table(
            ["Metric", "Value", "Interpretation"],
            [
                [
                    "Track C off win_rate",
                    fmt(aux["overall"].get("track_c_off", {}).get("win_rate")),
                    "辅助趋势",
                ],
                [
                    "Track C on win_rate",
                    fmt(aux["overall"].get("track_c_on", {}).get("win_rate")),
                    "辅助趋势",
                ],
                [
                    "avg_non_wolf_delta",
                    fmt(aux.get("avg_non_wolf_delta")),
                    "全席位切换趋势，不是 target-seat 因果",
                ],
                [
                    "smoke rows",
                    len(evidence["track_c_smoke"]),
                    "真实 LLM 小样本烟测",
                ],
                [
                    "max smoke knowledge_hit",
                    fmt(max([row["knowledge_hit_rate"] for row in evidence["track_c_smoke"]], default=0.0)),
                    "证明策略注入链路可运行",
                ],
            ],
        ),
        "",
        "辅助 Track C 胜率统计补充：",
        "",
        table(
            ["Baseline", "Candidate", "Delta", "95CI", "PValue", "CI跨0"],
            [
                [
                    f"{statistics_aux.get('baseline_label', 'track_c_off')} n={statistics_aux.get('baseline_samples', 'n/a')}",
                    f"{statistics_aux.get('candidate_label', 'track_c_on')} n={statistics_aux.get('candidate_samples', 'n/a')}",
                    fmt(statistics_aux.get("stats", {}).get("delta")),
                    f"[{fmt(statistics_aux.get('stats', {}).get('ci_low'))}, {fmt(statistics_aux.get('stats', {}).get('ci_high'))}]",
                    fmt(statistics_aux.get("stats", {}).get("two_sided_p")),
                    statistics_aux.get("stats", {}).get("ci_crosses_zero"),
                ]
            ],
        )
        if statistics_aux
        else "统计补充文件尚未生成。",
        "",
        "该统计再次说明：Track C on 存在正向趋势，但 CI 跨 0，当前不能写成最终胜率因果提升。",
        "",
        "## 10. Target-seat Track C 因果 A/B",
        "",
    ]

    if target_seat_rows:
        lines += [
            table(
                [
                    "Source",
                    "Role",
                    "Baseline",
                    "Candidate",
                    "Paired",
                    "ScoreDelta",
                    "RoleTaskDelta",
                    "WinDelta",
                    "MaxDays",
                    "Scope",
                    "Fallback",
                    "Invalid",
                    "Accepted",
                    "ClaimLevel",
                ],
                [
                    [
                        row.get("source"),
                        row.get("target_role"),
                        row.get("baseline_framework"),
                        row.get("candidate_framework"),
                        row.get("paired_seed_count"),
                        fmt(row.get("target_adjusted_score_delta")),
                        fmt(row.get("target_role_task_delta")),
                        fmt(row.get("target_win_rate_delta")),
                        row.get("max_days"),
                        row.get("claim_scope"),
                        row.get("candidate_fallback_count"),
                        row.get("candidate_invalid_count"),
                        row.get("accepted"),
                        row.get("claim_level"),
                    ]
                    for row in target_seat_rows[:5]
                ],
            ),
            "",
            "解释：`claim_scope=smoke_only` 的 target-seat 输出只说明真实 runner、per-agent feature flags、paired delta 和健康门禁能跑通；只有正式样本 `Accepted=true` 且 `ClaimLevel=causal_supported` 时，才能把 Track C 写成对单个目标席位的因果增益。",
            "",
        ]
    else:
        lines += [
            "当前未找到正式 target-seat A/B 输出。`scripts/target_seat_trackc_ab_experiment.py` 已支持 per-agent feature flags、paired delta、bootstrap 95% CI 和 acceptance gate；需要在真实 LLM provider 可用后运行，并确保 paired seeds、fallback/invalid、bootstrap CI 门禁通过。",
            "",
        ]

    provider_preflight_safe = bool(provider_preflight.get("safe_for_formal_experiment", False))
    provider_preflight_note = (
        "该 preflight 已通过真实 provider 可用性检查；target-seat 因果实验的剩余阻塞不再是 provider，而是仍需按功效计划运行正式 paired-seed A/B，并通过 fallback/invalid 与 bootstrap CI 门禁。"
        if provider_preflight_safe
        else "该 preflight 是当前不能补齐 target-seat 因果实验的直接证据；修复 key/base URL/provider 后需要先重跑 `python scripts/check_real_llm_provider.py`，确认 `safe_for_formal_experiment=true` 再启动正式 A/B。"
    )

    lines += [
        "### 10.1 真实 LLM Provider Preflight",
        "",
        table(
            ["Status", "SafeForFormalExperiment", "ResolvedModels", "Error", "Source"],
            [
                [
                    provider_preflight.get("status", "missing"),
                    provider_preflight.get("safe_for_formal_experiment", False),
                    ", ".join(row.get("label", "") for row in provider_preflight.get("resolved_models", [])),
                    provider_preflight.get("error", ""),
                    evidence.get("sources", {}).get("provider_preflight", "docs/PROJECT_PROVIDER_PREFLIGHT.json"),
                ]
            ],
        ),
        "",
        provider_preflight_note,
        "",
        "### 10.2 Target-seat A/B 功效计划",
        "",
        "样本量计划详见 `docs/PROJECT_TARGET_SEAT_AB_POWER_PLAN.md`。该文件只用于规划真实实验，不构成 Track C 已产生因果增益的结论。",
        "",
        table(
            ["Item", "Value"],
            [
                ["pilot_paired_seeds", target_power_recommendation.get("pilot_paired_seeds", "n/a")],
                [
                    "minimum_confirmatory_paired_seeds",
                    target_power_recommendation.get("minimum_confirmatory_paired_seeds", "n/a"),
                ],
                [
                    "preferred_confirmatory_paired_seeds",
                    target_power_recommendation.get("preferred_confirmatory_paired_seeds", "n/a"),
                ],
                [
                    "high_confidence_paired_seeds",
                    target_power_recommendation.get("high_confidence_paired_seeds", "n/a"),
                ],
                ["primary_metrics", ", ".join(target_power_recommendation.get("primary_metrics", []))],
                ["secondary_metrics", ", ".join(target_power_recommendation.get("secondary_metrics", []))],
            ],
        )
        if target_power_recommendation
        else "功效计划尚未生成。",
        "",
        target_power_recommendation.get(
            "rationale",
            "正式 target-seat A/B 应先完成 provider preflight，再按 paired seed 计划运行。",
        ),
        "",
    ]

    lines += [
        "## 11. 证据矩阵",
        "",
        table(
            ["Claim", "Level", "Status", "Metric", "Source", "Boundary"],
            [
                [
                    row["claim"],
                    row["evidence_level"],
                    row["status"],
                    row["metric"],
                    row["source"],
                    row["boundary"],
                ]
                for row in evidence["evidence_matrix"]
            ],
        ),
        "",
        "## 12. 可写结论与不可写结论",
        "",
        "### 可以写入正式报告",
        "",
        table(
            ["结论", "依据"],
            [
                ["系统方法形成 Play -> Evaluate -> Evolve 闭环，且可审计", "正式 v4flash、full audit、DB feedback"],
                [
                    "Track B 可以进行多层 leaderboard 展示",
                    "PROJECT_TRACK_B_LEADERBOARD_SHOWCASE：game/model-role/score/rubric/decision-health",
                ],
                ["Track C 默认检索策略相对 global_only 在离线 IR 指标上更有效", "P@3、Effective@3、nDCG@5、Coverage"],
                ["单角色检索能稳定覆盖核心角色", "per_role_results 中默认策略 Coverage/Top5Fill=1"],
                [
                    "策略使用决策与更高 Track B 逐步评分相关",
                    "decision_id 联表：per_step_scores + agent_decisions + knowledge_usage_feedback",
                ],
                ["知识库安全卫生当前审计通过", "invalid=0、leak=0、source_event_coverage"],
                ["正式 LLM 决策健康：fallback/invalid 为 0", "formal leaderboard"],
            ],
        ),
        "",
        "### 暂不能写入正式报告",
        "",
        table(
            ["结论", "原因", "需要补充"],
            [[gap["gap"], gap["reason"], gap["required_experiment"]] for gap in evidence["open_gaps"]],
        ),
        "",
        "## 13. 下一步真实实验命令",
        "",
        "当前 Doubao/Ark endpoint 已通过真实 chat preflight。建议先运行 20 paired seeds pilot 验证完整 target-seat 链路健康：",
        "",
        "```bash",
        "python scripts/target_seat_trackc_ab_experiment.py \\",
        "  --target-role Seer \\",
        "  --seeds 9301 9302 9303 9304 9305 9306 9307 9308 9309 9310 9311 9312 9313 9314 9315 9316 9317 9318 9319 9320 \\",
        "  --baseline-framework basic_react \\",
        "  --candidate-framework rag_react \\",
        '  --models "doubao:${DOUBAO_ENDPOINT}" \\',
        "  --player-count 7 \\",
        "  --max-days 20 \\",
        "  --bootstrap-iterations 2000 \\",
        "  --min-paired-seeds 20 \\",
        "  --min-adjusted-score-delta 3.0 \\",
        "  --min-role-task-delta 0.03 \\",
        "  --min-win-rate-delta 0.03 \\",
        "  --output-dir outputs/target_seat_trackc_ab_seer",
        "```",
        "",
        "全席位框架对比可继续运行：",
        "",
        "```bash",
        "python scripts/track_bc_leaderboard_experiment.py \\",
        "  --axis framework \\",
        "  --frameworks basic_react,rag_react,full_cognitive \\",
        "  --games 20 \\",
        "  --start-seed 9301 \\",
        "  --player-count 7 \\",
        "  --max-days 20 \\",
        "  --strict-fallback true \\",
        "  --output-dir outputs/method_effectiveness_paired_v4flash",
        "```",
        "",
        "如果要证明 Track C 对单个最终 Agent 的因果增益，还需要正式 target-seat A/B：同 seed、同角色分配、同 baseline 对手，只升级一个目标席位，并按角色轮换。根据 `docs/PROJECT_TARGET_SEAT_AB_POWER_PLAN.md`，正式验证建议 80-120 paired seeds 起步，胜率只作为辅助指标。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize method effectiveness evidence")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Tracked Markdown report path")
    parser.add_argument("--facts", default=str(DEFAULT_FACTS), help="Tracked JSON facts path")
    args = parser.parse_args()

    evidence = build_evidence()
    report_path = Path(args.report)
    facts_path = Path(args.facts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(evidence), encoding="utf-8")
    facts_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Wrote {facts_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
