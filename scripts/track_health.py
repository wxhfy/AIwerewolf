"""Track B + Track C operational health report.

Reads run records from `data/health/run_*.json` (produced by
`scripts/run_full_llm_pipeline.py`) and the persistent DB tables, then writes
a single Markdown report at `data/health/HEALTH_REPORT.md` that quantifies
whether each documented module of the B + C pipeline is actually producing
non-trivial output.

The report is intentionally fact-driven — every number prints next to the
metric it certifies. If the system is hollow, the numbers will say so.

Usage:
    python scripts/track_health.py
    python scripts/track_health.py --runs data/health/run_*.json
    python scripts/track_health.py --output docs/B_C_OPERATIONAL_REPORT.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_HEALTH_DIR = ROOT / "data" / "health"
DEFAULT_OUTPUT = DEFAULT_HEALTH_DIR / "HEALTH_REPORT.md"


def _load_runs(paths: list[Path]) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths if p.exists()]


def _db_snapshot() -> dict[str, Any]:
    """Inspect the persisted state of B + C tables. Best-effort: if DB is not
    reachable, return empty placeholders so the report still renders."""
    snapshot: dict[str, Any] = {
        "published_reviews": [],
        "knowledge_docs": [],
        "patches": [],
        "tournaments": [],
        "evolution_rounds": [],
        "usage_feedback": [],
    }
    try:
        from backend.db.database import SessionLocal, init_db
        from backend.db.models import (
            PublishedReview,
            StrategyKnowledgeDoc,
            StrategyPatch,
            EvolutionTournament,
            EvolutionRound,
            KnowledgeUsageFeedback,
        )
    except Exception as exc:
        snapshot["error"] = f"could not import DB layer: {exc}"
        return snapshot

    try:
        init_db()
        db = SessionLocal()
    except Exception as exc:
        snapshot["error"] = f"could not open DB session: {exc}"
        return snapshot

    try:
        snapshot["published_reviews"] = [
            {
                "id": row.id,
                "game_id": row.game_id,
                "status": row.status,
                "grade": row.grade,
                "score": float(row.score or 0.0),
                "publish_allowed": bool(row.publish_allowed),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in db.query(PublishedReview).order_by(PublishedReview.created_at.desc()).limit(50).all()
        ]
        snapshot["knowledge_docs"] = [
            {
                "doc_id": row.id,
                "doc_type": row.doc_type,
                "role": row.role,
                "phase": row.phase,
                "status": row.status,
                "quality_score": float(row.quality_score or 0.0),
                "confidence": float(row.confidence or 0.0),
                "usage_count": int(row.usage_count or 0),
                "success_count": int(row.success_count or 0),
                "failure_count": int(row.failure_count or 0),
            }
            for row in db.query(StrategyKnowledgeDoc).order_by(StrategyKnowledgeDoc.updated_at.desc()).limit(200).all()
        ]
        snapshot["patches"] = [
            {
                "patch_id": row.id,
                "patch_type": row.patch_type,
                "target_role": row.target_role,
                "from_version": row.from_version,
                "to_version": row.to_version,
                "status": row.status,
            }
            for row in db.query(StrategyPatch).order_by(StrategyPatch.created_at.desc()).limit(100).all()
        ]
        snapshot["tournaments"] = [
            {
                "tournament_id": row.id,
                "baseline_version": row.baseline_version,
                "candidate_version": row.candidate_version,
                "target_role": row.target_role,
                "status": row.status,
                "accepted": bool((row.decision or {}).get("accepted")),
                "candidate_avg_score": float((row.comparison or {}).get("candidate_avg_score") or 0.0),
                "baseline_avg_score": float((row.comparison or {}).get("baseline_avg_score") or 0.0),
            }
            for row in db.query(EvolutionTournament).order_by(EvolutionTournament.created_at.desc()).limit(50).all()
        ]
        snapshot["evolution_rounds"] = [
            {
                "id": row.id,
                "round_no": row.round_no,
                "summary": (row.change_log or "")[:160],
                "baseline_wins": int(row.baseline_wins or 0),
                "challenger_wins": int(row.challenger_wins or 0),
                "delta_win_rate": float(row.delta_win_rate or 0.0),
                "accepted": bool(row.accepted),
            }
            for row in db.query(EvolutionRound).order_by(EvolutionRound.started_at.desc()).limit(20).all()
        ]
        snapshot["usage_feedback"] = [
            {
                "id": row.id,
                "knowledge_doc_id": row.knowledge_doc_id,
                "helpful": bool(row.helpful),
                "decision_outcome": row.decision_outcome,
            }
            for row in db.query(KnowledgeUsageFeedback).order_by(KnowledgeUsageFeedback.created_at.desc()).limit(200).all()
        ]
    finally:
        db.close()
    return snapshot


def _render(runs: list[dict[str, Any]], db: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Track B + Track C Operational Health Report")
    lines.append(f"")
    lines.append(f"_generated: {datetime.now(timezone.utc).isoformat()}_")
    lines.append("")

    if runs:
        lines.append("## 1. 实测对局总览（来源：data/health/run_*.json）")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|---|---|")
        total_attempted = sum(int(r.get("games_attempted") or 0) for r in runs)
        total_completed = sum(int(r.get("games_completed") or 0) for r in runs)
        total_aborted = sum(int(r.get("games_aborted") or 0) for r in runs)
        lines.append(f"| 运行批次数 | {len(runs)} |")
        lines.append(f"| 累计对局尝试 | {total_attempted} |")
        lines.append(f"| 累计对局完成 | {total_completed} |")
        lines.append(f"| 累计 fallback abort | {total_aborted} |")
        lines.append(f"| strict_no_fallback 启用 | {sum(1 for r in runs if r.get('strict_no_fallback'))} / {len(runs)} 批次 |")
        lines.append("")

        # Aggregate across all runs
        agg = _aggregate_runs(runs)
        lines.append("### 1.1 跨批次累计指标")
        lines.append("")
        lines.append("| 维度 | 累计 / 占比 | 说明 |")
        lines.append("|---|---|---|")
        lines.append(f"| LLM 决策数 | {agg['total_llm_decisions']} | 由真实 LLM 产生的 Agent 决策 |")
        lines.append(f"| Fallback 决策数 | {agg['total_fallback_decisions']} | 走入 heuristic 兜底的决策（**严格模式下应为 0**）|")
        lines.append(f"| 决策非法数 | {agg['total_invalid_decisions']} | parser 失败或 action 非法 |")
        lines.append(f"| Fallback 比率 | {agg['fallback_rate']*100:.2f}% | Track C §19 接受条件要求 ≈ 0% |")
        lines.append(f"| 检索使用率 | {agg['retrieval_used_rate']*100:.2f}% | Track C §13: 每步都应触发知识检索 |")
        lines.append(f"| Track B 通过率 | {agg['publish_allowed_rate']*100:.2f}% | ValidAgent.publish_allowed=true 的比例 |")
        lines.append(f"| 平均 ValidAgent 分 | {agg['avg_validation_score']:.3f} | 0-1 区间, 1=完美无 issue |")
        lines.append("")

        lines.append("### 1.2 每局明细")
        lines.append("")
        lines.append("| seed | 胜方 | 天数 | 决策 (LLM/总) | Fallback | 复盘状态 | ValidAgent 分 | Gate 失败 | 高光/失误/反事实 | 发言/怀疑度 | 知识反馈 (有效/总) |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for run in runs:
            for g in run.get("per_game", []):
                gate_failures = sum(g.get("validation_gates", {}).values()) if g.get("validation_gates") else 0
                fb_helpful = g.get("knowledge_feedback_helpful", 0)
                fb_total = g.get("knowledge_feedback_count", 0)
                lines.append(
                    f"| {g['seed']} | {g['winner']} | {g['days']} | {g['llm_decision_count']}/{g['total_decisions']} | "
                    f"{g['fallback_decision_count']} | {g['review_status']} | "
                    f"{g.get('validation_score', 0):.3f} | {gate_failures} | "
                    f"{g['highlight_count']}/{g['bad_case_count']}/{g['counterfactual_count']} | "
                    f"{g['speech_act_count']}/{g['suspicion_snapshot_count']} | "
                    f"{fb_helpful}/{fb_total} |"
                )
        lines.append("")

        # Counterfactual effect_type distribution (Track B §13 sanity)
        cf_effects = Counter()
        for run in runs:
            for g in run.get("per_game", []):
                for et, cnt in (g.get("counterfactual_effect_types") or {}).items():
                    cf_effects[et] += cnt
        if cf_effects:
            lines.append("### 1.3 反事实 effect_type 分布 (B §13)")
            lines.append("")
            lines.append("| effect_type | 数量 | 含义 |")
            lines.append("|---|---|---|")
            label = {
                "exact_recalculation": "投票反事实, 精确重算票型",
                "local_recalculation": "技能反事实, 局部影响重算",
                "estimated": "信息释放反事实, 估计影响",
                "missing": "缺失 effect_type 字段（B Gate6 应拒）",
            }
            for et, cnt in sorted(cf_effects.items()):
                lines.append(f"| {et} | {cnt} | {label.get(et, '-')} |")
            lines.append("")

        # Track C extraction summary
        c_section_emitted = False
        for run in runs:
            tc = run.get("track_c") or {}
            if not tc.get("games"):
                continue
            if not c_section_emitted:
                lines.append("## 2. Track C 知识抽取（来源：本批运行）")
                lines.append("")
                c_section_emitted = True
            lines.append(f"### 批次 {run['started_at']}")
            lines.append("")
            lines.append("| 指标 | 数值 |")
            lines.append("|---|---|")
            lines.append(f"| 输入已批准复盘报告 | {tc.get('games', 0)} |")
            lines.append(f"| 抽取知识文档总数 | {tc.get('knowledge_doc_count', 0)} |")
            lines.append(f"| 候选 patch 总数 | {tc.get('candidate_patch_count', 0)} |")
            lines.append(f"| Patch 目标角色 | {', '.join(tc.get('patch_target_roles') or []) or '—'} |")
            lines.append("")
            if tc.get("doc_type_breakdown"):
                lines.append("**文档类型分布:**")
                lines.append("")
                lines.append("| doc_type | 数量 |")
                lines.append("|---|---|")
                for t, c in sorted(tc["doc_type_breakdown"].items()):
                    lines.append(f"| {t} | {c} |")
                lines.append("")
            if tc.get("quality_buckets"):
                lines.append("**质量分分桶（C §11 真 recency + 真 repeatability）:**")
                lines.append("")
                lines.append("| 区间 | 数量 |")
                lines.append("|---|---|")
                for bucket in ("<0.5", "0.5-0.7", "0.7-0.85", ">=0.85"):
                    lines.append(f"| {bucket} | {tc['quality_buckets'].get(bucket, 0)} |")
                lines.append("")
            if tc.get("doc_status_breakdown"):
                lines.append("**状态分布:**")
                lines.append("")
                lines.append("| status | 数量 |")
                lines.append("|---|---|")
                for s, c in sorted(tc["doc_status_breakdown"].items()):
                    lines.append(f"| {s} | {c} |")
                lines.append("")

        # A/B tournament summary
        ab_section_emitted = False
        for run in runs:
            ab = run.get("ab_tournament")
            if not ab:
                continue
            if not ab_section_emitted:
                lines.append("## 3. A/B 锦标赛（Track C §19，真跑 20 seed × 双版本 = 40 局）")
                lines.append("")
                ab_section_emitted = True
            lines.append(f"### 批次 {run['started_at']}: {ab['baseline_version']} vs {ab['candidate_version']} (角色: {ab['target_role']})")
            lines.append("")
            lines.append("| 指标 | baseline | candidate | Δ |")
            lines.append("|---|---|---|---|")
            lines.append(f"| 平均最终分 | {ab['baseline_avg_score']:.4f} | {ab['candidate_avg_score']:.4f} | {ab['candidate_avg_score']-ab['baseline_avg_score']:+.4f} |")
            lines.append(f"| 胜场 | {ab['baseline_wins']}/20 | {ab['candidate_wins']}/20 | — |")
            lines.append("")
            lines.append("**Acceptance 判定:**")
            lines.append("")
            lines.append("| 维度 | 数值 / 阈值 |")
            lines.append("|---|---|")
            lines.append(f"| 目标角色得分 Δ | {ab['target_role_avg_score_delta_pct']:+.2f}% (要 ≥+3%) |")
            lines.append(f"| RoleTask 得分 Δ | {ab['role_task_score_delta_pct']:+.2f}% (要 ≥+3%) |")
            lines.append(f"| Critical 失误 Δ | {ab['critical_mistakes_delta']:+.4f} (要 ≤-0.10) |")
            lines.append(f"| Info leak count | {ab['info_leak_count']} (硬条件: =0) |")
            lines.append(f"| Invalid action rate | {ab['invalid_action_rate']:.4f} (硬条件: =0) |")
            lines.append(f"| Candidate fallback count | {ab['candidate_fallback_count']} (硬条件: =0) |")
            lines.append(f"| **最终决策** | **{'PROMOTE' if ab['accepted'] else 'ROLLBACK'}** |")
            lines.append("")
            if ab.get("satisfied_conditions"):
                lines.append(f"满足条件: {', '.join(ab['satisfied_conditions'])}")
            if ab.get("failed_conditions"):
                lines.append(f"未达条件: {', '.join(ab['failed_conditions'])}")
            lines.append("")

    # DB-state section
    lines.append("## 4. 持久化状态（DB 快照）")
    lines.append("")
    if db.get("error"):
        lines.append(f"⚠️ DB 连接失败：{db['error']}")
        lines.append("")
    else:
        pr = db.get("published_reviews", [])
        kd = db.get("knowledge_docs", [])
        pt = db.get("patches", [])
        tr = db.get("tournaments", [])
        er = db.get("evolution_rounds", [])
        uf = db.get("usage_feedback", [])

        lines.append("| 表 | 行数（最多取近 200 / 50） | 备注 |")
        lines.append("|---|---|---|")
        lines.append(f"| PublishedReview | {len(pr)} | Track B 落库的复盘报告 |")
        lines.append(f"| StrategyKnowledgeDoc | {len(kd)} | Track C 已沉淀的策略知识 |")
        lines.append(f"| StrategyPatch | {len(pt)} | 已生成的策略补丁 |")
        lines.append(f"| EvolutionTournament | {len(tr)} | 已跑过的 A/B 锦标赛 |")
        lines.append(f"| EvolutionRound | {len(er)} | DreamJob 聚合轮次 (legacy: baseline_wins/challenger_wins) |")
        lines.append(f"| KnowledgeUsageFeedback | {len(uf)} | 知识使用反馈记录 |")
        lines.append("")

        # PublishedReview health
        if pr:
            approved = sum(1 for r in pr if r["publish_allowed"])
            lines.append("### 4.1 PublishedReview 状态分布")
            lines.append("")
            status_dist = Counter(r["status"] for r in pr)
            lines.append("| status | 数量 |")
            lines.append("|---|---|")
            for s, c in status_dist.most_common():
                lines.append(f"| {s} | {c} |")
            lines.append("")
            lines.append(f"publish_allowed=True 比例：{approved}/{len(pr)} ({approved/len(pr)*100:.1f}%)")
            lines.append("")

        # Knowledge doc breakdown
        if kd:
            lines.append("### 4.2 知识库统计")
            lines.append("")
            type_dist = Counter(d["doc_type"] for d in kd)
            status_dist = Counter(d["status"] for d in kd)
            role_dist = Counter(d["role"] for d in kd)
            lines.append("**doc_type 分布:**")
            lines.append("")
            lines.append("| doc_type | 数量 |")
            lines.append("|---|---|")
            for t, c in type_dist.most_common():
                lines.append(f"| {t} | {c} |")
            lines.append("")
            lines.append("**status 分布:**")
            lines.append("")
            lines.append("| status | 数量 |")
            lines.append("|---|---|")
            for s, c in status_dist.most_common():
                lines.append(f"| {s} | {c} |")
            lines.append("")
            lines.append("**role 分布:**")
            lines.append("")
            lines.append("| role | 数量 |")
            lines.append("|---|---|")
            for r, c in role_dist.most_common():
                lines.append(f"| {r} | {c} |")
            lines.append("")
            qualities = [d["quality_score"] for d in kd]
            usages = [d["usage_count"] for d in kd]
            success = sum(d["success_count"] for d in kd)
            failure = sum(d["failure_count"] for d in kd)
            lines.append("**质量指标:**")
            lines.append("")
            lines.append("| 指标 | 数值 |")
            lines.append("|---|---|")
            lines.append(f"| 平均 quality_score | {sum(qualities)/len(qualities):.4f} |")
            lines.append(f"| min/max quality | {min(qualities):.4f} / {max(qualities):.4f} |")
            lines.append(f"| 平均 usage_count | {sum(usages)/len(usages):.2f} |")
            lines.append(f"| 总 success_count | {success} |")
            lines.append(f"| 总 failure_count | {failure} |")
            lines.append("")

        # Patch summary
        if pt:
            lines.append("### 4.3 策略补丁状态")
            lines.append("")
            pstatus = Counter(p["status"] for p in pt)
            lines.append("| status | 数量 |")
            lines.append("|---|---|")
            for s, c in pstatus.most_common():
                lines.append(f"| {s} | {c} |")
            lines.append("")

        # Tournament rollup
        if tr:
            lines.append("### 4.4 A/B 锦标赛记录")
            lines.append("")
            lines.append("| baseline → candidate | 角色 | candidate avg | baseline avg | 接受 |")
            lines.append("|---|---|---|---|---|")
            for t in tr[:10]:
                lines.append(
                    f"| {t['baseline_version']} → {t['candidate_version']} | "
                    f"{t['target_role'] or '—'} | {t['candidate_avg_score']:.4f} | "
                    f"{t['baseline_avg_score']:.4f} | {'✓' if t['accepted'] else '✗'} |"
                )
            lines.append("")

        # Usage feedback
        if uf:
            lines.append("### 4.5 知识使用反馈分布")
            lines.append("")
            helpful_count = sum(1 for u in uf if u["helpful"])
            lines.append(f"- 反馈样本：{len(uf)}")
            lines.append(f"- 标记 helpful：{helpful_count} ({helpful_count/len(uf)*100:.1f}%)")
            lines.append(f"- 标记 unhelpful：{len(uf)-helpful_count} ({(len(uf)-helpful_count)/len(uf)*100:.1f}%)")
            lines.append("")

    lines.append("## 5. 验收门 (Gate) 真实拦截能力检查")
    lines.append("")
    lines.append("以下指标证明每个 Gate 不是装饰，会真的拒一些东西。它们应该 > 0 才说明 Gate 在工作。")
    lines.append("")
    gate_counter: Counter = Counter()
    for run in runs:
        for g in run.get("per_game", []):
            for gate, cnt in (g.get("validation_gates") or {}).items():
                gate_counter[gate] += cnt
    if gate_counter:
        lines.append("| Gate | 累计拦截 issue 次数 |")
        lines.append("|---|---|")
        for gate, cnt in sorted(gate_counter.items()):
            lines.append(f"| {gate} | {cnt} |")
    else:
        lines.append("（本次所有运行都没有触发任何 Gate 报警；说明数据流足够干净。）")
    lines.append("")

    return "\n".join(lines)


def _aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter()
    for r in runs:
        for g in r.get("per_game", []):
            for key in ("total_decisions", "llm_decision_count", "fallback_decision_count",
                        "invalid_decision_count", "retrieval_used_count",
                        "bad_case_count", "highlight_count", "counterfactual_count"):
                totals[key] += int(g.get(key) or 0)
    n = sum(len(r.get("per_game", [])) for r in runs) or 1
    publish_allowed = sum(1 for r in runs for g in r.get("per_game", []) if g.get("publish_allowed"))
    avg_validation = sum(float(g.get("validation_score") or 0) for r in runs for g in r.get("per_game", []))
    return {
        "total_llm_decisions": totals["llm_decision_count"],
        "total_fallback_decisions": totals["fallback_decision_count"],
        "total_invalid_decisions": totals["invalid_decision_count"],
        "fallback_rate": totals["fallback_decision_count"] / max(totals["total_decisions"], 1),
        "retrieval_used_rate": totals["retrieval_used_count"] / max(totals["total_decisions"], 1),
        "publish_allowed_rate": publish_allowed / max(n, 1),
        "avg_validation_score": avg_validation / max(n, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="*", default=None,
                        help="run_*.json paths (defaults to data/health/run_*.json)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--skip-db", action="store_true")
    args = parser.parse_args()

    if args.runs:
        run_paths = [Path(p) for p in args.runs]
    else:
        run_paths = sorted(DEFAULT_HEALTH_DIR.glob("run_*.json"))

    runs = _load_runs(run_paths)
    db = {"error": "skipped"} if args.skip_db else _db_snapshot()
    rendered = _render(runs, db)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"Wrote {out}  ({len(runs)} run records, {sum(len(r.get('per_game', [])) for r in runs)} games)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
