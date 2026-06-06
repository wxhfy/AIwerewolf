"""Run Track C (DreamJob → patch → tournament) on a specific set of LLM games.

Critical safety:
- Pulls approved published_reviews only from the supplied game_ids (defaults
  to all all-LLM games created today). Avoids the heuristic AB-tournament
  contamination from concurrent tenants on the shared DB.
- Uses TournamentRunner._run_seed for the A/B side, which now creates
  LLM-backed CognitiveAgents. Local no-cost verification may set
  LLM_PROVIDER=fake, but the game path must still be LLM-compatible and
  must not fall back to HeuristicAgent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from backend.db.database import SessionLocal
from backend.eval.evolution import AcceptancePolicy
from backend.eval.evolution import DreamJob
from backend.eval.evolution import PatchOperation
from backend.eval.evolution import StrategyKnowledgeStore
from backend.eval.evolution import TournamentRunner
from backend.eval.track_b import reconstruct_review_report


def load_my_game_ids(label: str | None) -> list[str]:
    if label:
        path = ROOT / "data" / "health" / f"llm_batch_{label}.jsonl"
        if path.exists():
            ids: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if "game_id" in record:
                        ids.append(record["game_id"])
                except json.JSONDecodeError:
                    continue
            return ids
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
            SELECT g.id FROM games g
            WHERE g.status='finished' AND g.created_at >= '2026-05-25 12:00:00'
              AND EXISTS (SELECT 1 FROM players p WHERE p.game_id=g.id AND p.agent_type='llm')
              AND NOT EXISTS (SELECT 1 FROM players p WHERE p.game_id=g.id AND p.agent_type!='llm')
            ORDER BY g.created_at
        """)
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()


def load_approved_reports(game_ids: list[str]) -> list[Any]:
    if not game_ids:
        return []
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""
            SELECT report_json FROM published_reviews
            WHERE game_id IN :gids AND publish_allowed = true
        """),
            {"gids": tuple(game_ids)},
        ).fetchall()
        reports: list[Any] = []
        for (rj,) in rows:
            if not rj:
                continue
            try:
                reports.append(reconstruct_review_report(rj))
            except Exception as exc:
                print(f"  ! reconstruct fail: {exc}")
        return reports
    finally:
        db.close()


def run_dream(reports: list[Any]) -> dict[str, Any]:
    """Build knowledge docs + candidate patches from approved reports."""
    print("\n=== Stage 1: DreamJob (knowledge extraction) ===")
    store = StrategyKnowledgeStore()
    job = DreamJob(store=store)
    result = job.run(reports)
    print(f"  reports → docs: {len(reports)} → {len(result.knowledge_docs)}")
    print(f"  candidate patches: {len(result.candidate_patches)}")
    doc_types: dict[str, int] = {}
    doc_statuses: dict[str, int] = {}
    for doc in result.knowledge_docs:
        doc_types[doc.doc_type] = doc_types.get(doc.doc_type, 0) + 1
        doc_statuses[doc.status] = doc_statuses.get(doc.status, 0) + 1
    print(f"  doc_types: {doc_types}")
    print(f"  doc_statuses: {doc_statuses}")
    patches_by_role: dict[str, int] = {}
    for p in result.candidate_patches:
        patches_by_role[p.target_role or "global"] = patches_by_role.get(p.target_role or "global", 0) + 1
    print(f"  patches_by_target_role: {patches_by_role}")

    return {
        "docs": result.knowledge_docs,
        "patches": result.candidate_patches,
        "doc_types": doc_types,
        "doc_statuses": doc_statuses,
        "patches_by_role": patches_by_role,
        "summary": result.summary.summary,
    }


def run_one_tournament(patch_target_role: str | None = "Seer") -> dict[str, Any]:
    """Run a fixed-seed 20-game LLM-only A/B tournament with a candidate
    patch on a target role.
    """
    print(f"\n=== Stage 2: A/B Tournament (target_role={patch_target_role}, llm-only) ===")
    runner = TournamentRunner(acceptance_policy=AcceptancePolicy())
    seeds = list(range(201, 221))  # 20 seeds disjoint from our LLM batch

    candidate_ops = [
        PatchOperation(
            op="add",
            section="speech_policy",
            new_value=("如果预言家手里有金水/查杀,优先公开报金水保护好人,再用查杀给狼施压;务必让信息传到票上。"),
            rationale="LLM 复盘多次提到神职信息没转化为投票指引,导致跟票失败。",
        )
    ]
    print("  fixed seeds 201-220 (llm engine)")

    baseline = [
        runner._run_seed(seed=s, strategy_version=f"{patch_target_role}_v1", target_role=patch_target_role)
        for s in seeds
    ]
    candidate = [
        runner._run_seed(
            seed=s,
            strategy_version=f"{patch_target_role}_v2_cand",
            target_role=patch_target_role,
            strategy_patch_ops=candidate_ops,
        )
        for s in seeds
    ]

    comparison = runner.compare_metrics(
        baseline_version=f"{patch_target_role}_v1",
        candidate_version=f"{patch_target_role}_v2_cand",
        baseline_metrics=baseline,
        candidate_metrics=candidate,
    )
    decision = runner.acceptance_policy.decide(comparison)

    print(f"  baseline_avg_score: {comparison.baseline_avg_score}")
    print(f"  candidate_avg_score: {comparison.candidate_avg_score}")
    print(f"  baseline_wins: {comparison.baseline_wins}  candidate_wins: {comparison.candidate_wins}")
    print(f"  target_role Δscore_pct: {comparison.target_role_avg_score_delta}")
    print(f"  role_task Δscore_pct: {comparison.role_task_score_delta}")
    print(f"  critical_mistakes Δ: {comparison.critical_mistakes_delta}")
    print(f"  accepted: {decision.accepted}")
    print(f"  satisfied conditions: {decision.satisfied_conditions}")
    print(f"  failed conditions: {decision.failed_conditions}")

    return {
        "baseline_avg_score": comparison.baseline_avg_score,
        "candidate_avg_score": comparison.candidate_avg_score,
        "baseline_wins": comparison.baseline_wins,
        "candidate_wins": comparison.candidate_wins,
        "delta_target_role_pct": comparison.target_role_avg_score_delta,
        "delta_role_task_pct": comparison.role_task_score_delta,
        "critical_mistakes_delta": comparison.critical_mistakes_delta,
        "accepted": decision.accepted,
        "satisfied_conditions": list(decision.satisfied_conditions),
        "failed_conditions": list(decision.failed_conditions),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=None)
    ap.add_argument("--skip-tournament", action="store_true")
    ap.add_argument("--tournament-role", default="Seer")
    args = ap.parse_args()

    game_ids = load_my_game_ids(args.label)
    print(f"Track C run — game_ids: {len(game_ids)} (label={args.label})")

    if not game_ids:
        print("No LLM games found; aborting.")
        return 1

    reports = load_approved_reports(game_ids)
    print(f"approved reports: {len(reports)}")
    if not reports:
        print("No approved review reports; aborting.")
        return 1

    dream_result = run_dream(reports)

    tournament_result = None
    if not args.skip_tournament:
        tournament_result = run_one_tournament(args.tournament_role)

    print("\n=== Summary ===")
    print(f"  source games: {len(game_ids)}")
    print(f"  approved reports: {len(reports)}")
    print(f"  knowledge_docs: {len(dream_result['docs'])}")
    print(f"  candidate_patches: {len(dream_result['patches'])}")
    if tournament_result:
        print(f"  tournament Δscore_pct(target_role): {tournament_result['delta_target_role_pct']}")
        print(f"  tournament accepted: {tournament_result['accepted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
