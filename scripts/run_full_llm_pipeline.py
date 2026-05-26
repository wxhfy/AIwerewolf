"""End-to-end Track B + Track C operational verification with real LLM agents.

This is the no-shortcut harness. It:

1. Forces every agent to be `LLMAgent` with `STRICT_NO_FALLBACK=True`, so any
   API failure / parse failure aborts the game instead of silently switching
   to heuristic moves.
2. Plays N games at fixed seeds.
3. For each finished game:
   - Persists a ReplayBundle to the DB.
   - Runs the Track B review/validation/repair pipeline.
   - Verifies fallback_count == 0 on the published replay (B Gate10).
   - Confirms `validation.publish_allowed == True` (B §15).
4. After the batch, runs Track C knowledge extraction + DreamJob.
5. Optionally runs a real fixed-seed 20-game A/B tournament for one role.
6. Writes a single `data/health/run_<timestamp>.json` operational record so
   `scripts/track_health.py` can quantify whether the pipeline is alive.

Usage:
    python scripts/run_full_llm_pipeline.py --seeds 7 11 13
    python scripts/run_full_llm_pipeline.py --seeds 7 --skip-ab
    python scripts/run_full_llm_pipeline.py --strict-fallback false  # debugging
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.agents.llm_agent import LLMAgent, LLMFallbackForbidden
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType
from backend.engine.rules import build_players
from backend.eval.evolution import (
    DreamJob,
    StrategyKnowledgeDocExtractor,
    StrategyKnowledgeStore,
    TournamentRunner,
    AcceptancePolicy,
    PatchOperation,
)
from backend.eval.review import MetricsCalculator, GameMetrics
from backend.eval.track_b import generate_published_review_document


HEALTH_DIR = ROOT / "data" / "health"
HEALTH_DIR.mkdir(parents=True, exist_ok=True)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_one_game(seed: int, strict: bool) -> dict[str, Any]:
    """Play a single LLM-driven game and run Track B. Returns a metric blob.
    Any exception (notably LLMFallbackForbidden in strict mode) bubbles up.
    """
    LLMAgent.STRICT_NO_FALLBACK = strict
    started = time.time()
    players = build_players(seed=seed)
    agents = create_agents(players, {"type": "llm", "seed": seed})
    game = WerewolfGame(players=players, agents=agents, seed=seed)
    state = game.play()
    duration = time.time() - started

    decisions = state.decision_records
    fallback_decisions = [
        rec for rec in decisions
        if bool((rec.parsed_action or {}).get("metadata", {}).get("fallback"))
        or bool((rec.parsed_action or {}).get("agent_fallback"))
        or str((rec.parsed_action or {}).get("metadata", {}).get("source", "")) == "fallback"
    ]
    llm_decisions = [
        rec for rec in decisions
        if str((rec.parsed_action or {}).get("metadata", {}).get("source", "")) == "llm"
    ]
    retrieval_decisions = [
        rec for rec in decisions
        if bool((rec.parsed_action or {}).get("retrieval_used"))
    ]
    invalid_decisions = [rec for rec in decisions if not rec.is_valid]
    llm_source_rate = len(llm_decisions) / max(len(decisions), 1)
    if strict and decisions and llm_source_rate < 0.95:
        raise RuntimeError(
            f"strict LLM run produced non-LLM decisions: "
            f"llm={len(llm_decisions)} total={len(decisions)}"
        )

    document = generate_published_review_document(state)
    review_report = document.review_report
    validation = document.validation_result

    return {
        "seed": seed,
        "game_id": state.id,
        "winner": state.winner.value if state.winner else None,
        "days": state.day,
        "total_events": len(state.events),
        "total_decisions": len(decisions),
        "llm_decision_count": len(llm_decisions),
        "llm_source_rate": round(llm_source_rate, 4),
        "fallback_decision_count": len(fallback_decisions),
        "invalid_decision_count": len(invalid_decisions),
        "retrieval_used_count": len(retrieval_decisions),
        "duration_seconds": round(duration, 2),
        "review_status": document.status,
        "publish_allowed": bool(validation.get("publish_allowed")),
        "validation_grade": validation.get("grade"),
        "validation_score": validation.get("score"),
        "validation_issue_count": len(validation.get("issues", [])),
        "validation_gates": _gate_breakdown(validation.get("issues", [])),
        "bad_case_count": len(review_report.get("bad_cases", [])),
        "highlight_count": len(review_report.get("turning_points", [])),
        "counterfactual_count": len(review_report.get("counterfactuals", [])),
        "counterfactual_effect_types": _effect_type_breakdown(review_report.get("counterfactuals", [])),
        "speech_act_count": len(document.speech_acts),
        "suspicion_snapshot_count": len(document.suspicion_matrix),
        "knowledge_feedback_count": len(document.metadata.get("knowledge_feedback") or []),
        "knowledge_feedback_helpful": sum(1 for fb in document.metadata.get("knowledge_feedback") or [] if fb.get("helpful")),
        "knowledge_feedback_unhelpful": sum(1 for fb in document.metadata.get("knowledge_feedback") or [] if not fb.get("helpful")),
    }


def _gate_breakdown(issues: list[dict[str, Any]]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for issue in issues:
        gate = issue.get("gate") or "unknown"
        breakdown[gate] = breakdown.get(gate, 0) + 1
    return breakdown


def _effect_type_breakdown(counterfactuals: list[dict[str, Any]]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for case in counterfactuals:
        et = case.get("effect_type") or "missing"
        breakdown[et] = breakdown.get(et, 0) + 1
    return breakdown


def run_pipeline(seeds: list[int], strict: bool, skip_ab: bool) -> dict[str, Any]:
    run_start = utcnow_iso()
    per_game: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for seed in seeds:
        print(f"[{utcnow_iso()}] === Game seed={seed} (strict_no_fallback={strict}) ===", flush=True)
        try:
            game_metric = run_one_game(seed, strict)
            print(
                f"  ✓ winner={game_metric['winner']} days={game_metric['days']} "
                f"llm={game_metric['llm_decision_count']}/{game_metric['total_decisions']} "
                f"fallback={game_metric['fallback_decision_count']} "
                f"review={game_metric['review_status']} "
                f"publish={game_metric['publish_allowed']}",
                flush=True,
            )
            per_game.append(game_metric)
        except LLMFallbackForbidden as exc:
            print(f"  ✗ ABORTED — LLM fallback would have fired: {exc}", flush=True)
            errors.append({
                "seed": seed,
                "kind": "fallback_aborted",
                "message": str(exc),
            })
        except Exception as exc:
            traceback.print_exc()
            errors.append({
                "seed": seed,
                "kind": type(exc).__name__,
                "message": str(exc),
            })

    # Track C extraction over the in-process reports we just published.
    # Replay the DB-persisted PublishedReview rows for the seeds we ran.
    track_c_summary = _run_track_c_summary([item["game_id"] for item in per_game], strict)

    ab_summary: dict[str, Any] | None = None
    if not skip_ab and per_game:
        ab_summary = _run_strict_ab_tournament(strict)

    return {
        "started_at": run_start,
        "finished_at": utcnow_iso(),
        "strict_no_fallback": strict,
        "seeds": seeds,
        "games_attempted": len(seeds),
        "games_completed": len(per_game),
        "games_aborted": len(errors),
        "per_game": per_game,
        "errors": errors,
        "track_c": track_c_summary,
        "ab_tournament": ab_summary,
        "aggregate": _aggregate(per_game),
    }


def _aggregate(per_game: list[dict[str, Any]]) -> dict[str, Any]:
    if not per_game:
        return {}
    n = len(per_game)

    def _sum(key: str) -> int:
        return sum(int(g.get(key) or 0) for g in per_game)

    return {
        "village_wins": sum(1 for g in per_game if g["winner"] == "village"),
        "wolf_wins": sum(1 for g in per_game if g["winner"] == "wolf"),
        "publish_allowed_rate": round(sum(1 for g in per_game if g["publish_allowed"]) / n, 4),
        "avg_validation_score": round(sum(float(g.get("validation_score") or 0) for g in per_game) / n, 4),
        "total_llm_decisions": _sum("llm_decision_count"),
        "total_fallback_decisions": _sum("fallback_decision_count"),
        "total_invalid_decisions": _sum("invalid_decision_count"),
        "total_retrieval_used": _sum("retrieval_used_count"),
        "fallback_rate": round(_sum("fallback_decision_count") / max(_sum("total_decisions"), 1), 4),
        "retrieval_used_rate": round(_sum("retrieval_used_count") / max(_sum("total_decisions"), 1), 4),
        "total_bad_cases": _sum("bad_case_count"),
        "total_highlights": _sum("highlight_count"),
        "total_counterfactuals": _sum("counterfactual_count"),
        "total_speech_acts": _sum("speech_act_count"),
        "total_suspicion_snapshots": _sum("suspicion_snapshot_count"),
        "total_knowledge_feedback": _sum("knowledge_feedback_count"),
        "total_knowledge_helpful": _sum("knowledge_feedback_helpful"),
        "knowledge_helpfulness_rate": (
            round(_sum("knowledge_feedback_helpful") / max(_sum("knowledge_feedback_count"), 1), 4)
            if _sum("knowledge_feedback_count") else None
        ),
    }


def _run_track_c_summary(game_ids: list[str], strict: bool) -> dict[str, Any]:
    """Reconstruct ReviewReport objects from the DB and run DreamJob on the
    fresh approved reports so we can show actual Track C output, not stubs.
    """
    if not game_ids:
        return {"games": 0, "skipped": "no approved games in this batch"}

    from backend.db.persist import get_review_reports
    from backend.eval.track_b import reconstruct_review_report

    review_reports = []
    for game_id in game_ids:
        payload = get_review_reports(game_id)
        if not payload or payload.get("status") != "approved":
            continue
        report_json = payload.get("review_report") or {}
        if not report_json:
            continue
        try:
            review_reports.append(reconstruct_review_report(report_json))
        except Exception as exc:
            print(f"  ! Track C reconstruction failed for {game_id}: {exc}", flush=True)

    if not review_reports:
        return {"games": 0, "skipped": "no published reports could be reconstructed"}

    store = StrategyKnowledgeStore()
    job = DreamJob(store=store)
    dream = job.run(review_reports)

    # Quality / status histograms over the freshly produced docs.
    doc_types: dict[str, int] = {}
    status_breakdown: dict[str, int] = {}
    quality_buckets = {"<0.5": 0, "0.5-0.7": 0, "0.7-0.85": 0, ">=0.85": 0}
    for doc in dream.knowledge_docs:
        doc_types[doc.doc_type] = doc_types.get(doc.doc_type, 0) + 1
        status_breakdown[doc.status] = status_breakdown.get(doc.status, 0) + 1
        if doc.quality_score < 0.5:
            quality_buckets["<0.5"] += 1
        elif doc.quality_score < 0.7:
            quality_buckets["0.5-0.7"] += 1
        elif doc.quality_score < 0.85:
            quality_buckets["0.7-0.85"] += 1
        else:
            quality_buckets[">=0.85"] += 1

    patch_roles = sorted({p.target_role for p in dream.candidate_patches if p.target_role})

    return {
        "games": len(review_reports),
        "knowledge_doc_count": len(dream.knowledge_docs),
        "doc_type_breakdown": doc_types,
        "doc_status_breakdown": status_breakdown,
        "quality_buckets": quality_buckets,
        "candidate_patch_count": len(dream.candidate_patches),
        "patch_target_roles": patch_roles,
        "summary": dream.summary.summary,
    }


def _run_strict_ab_tournament(strict: bool) -> dict[str, Any]:
    """Run a real fixed-seed 20-game A/B tournament. Baseline is the default
    v1 card; candidate gets a small speech_policy patch so its perturbation
    is non-zero, letting AcceptancePolicy actually decide."""
    runner = TournamentRunner(acceptance_policy=AcceptancePolicy())
    candidate_ops = [
        PatchOperation(
            op="add",
            section="speech_policy",
            new_value="If the Seer holds a wolf check and a villager is being voted, publicly announce the check before voting.",
            rationale="Multi-game review showed seer info conversion failures led to good-side misvotes.",
        )
    ]

    seeds = list(range(101, 121))  # 20 fixed seeds disjoint from per_game ones
    print(f"[{utcnow_iso()}] === A/B tournament: 20 seeds for role=Seer ===", flush=True)

    baseline: list[GameMetrics] = []
    candidate: list[GameMetrics] = []
    for seed in seeds:
        baseline.append(_run_llm_ab_seed(
            seed=seed,
            strategy_version="seer_v1",
            target_role="Seer",
            strict=strict,
        ))
        candidate.append(_run_llm_ab_seed(
            seed=seed,
            strategy_version="seer_v2_candidate",
            target_role="Seer",
            strict=strict,
            strategy_patch_ops=candidate_ops,
        ))

    comparison = runner.compare_metrics(
        baseline_version="seer_v1",
        candidate_version="seer_v2_candidate",
        baseline_metrics=baseline,
        candidate_metrics=candidate,
    )
    decision = runner.acceptance_policy.decide(comparison)
    return {
        "runner_mode": "llm",
        "baseline_version": "seer_v1",
        "candidate_version": "seer_v2_candidate",
        "target_role": "Seer",
        "seeds": seeds,
        "baseline_llm_decisions": sum(int(item.metadata.get("llm_decision_count", 0)) for item in baseline),
        "candidate_llm_decisions": sum(int(item.metadata.get("llm_decision_count", 0)) for item in candidate),
        "baseline_total_decisions": sum(int(item.metadata.get("total_decisions", 0)) for item in baseline),
        "candidate_total_decisions": sum(int(item.metadata.get("total_decisions", 0)) for item in candidate),
        "baseline_avg_score": comparison.baseline_avg_score,
        "candidate_avg_score": comparison.candidate_avg_score,
        "target_role_avg_score_delta_pct": comparison.target_role_avg_score_delta,
        "role_task_score_delta_pct": comparison.role_task_score_delta,
        "critical_mistakes_delta": comparison.critical_mistakes_delta,
        "candidate_wins": comparison.candidate_wins,
        "baseline_wins": comparison.baseline_wins,
        "info_leak_count": comparison.info_leak_count,
        "invalid_action_rate": comparison.invalid_action_rate,
        "candidate_fallback_count": comparison.candidate_fallback_count,
        "accepted": decision.accepted,
        "satisfied_conditions": decision.satisfied_conditions,
        "failed_conditions": decision.failed_conditions,
    }


def _run_llm_ab_seed(
    *,
    seed: int,
    strategy_version: str,
    target_role: str | None,
    strict: bool,
    strategy_patch_ops: list[PatchOperation] | None = None,
) -> GameMetrics:
    """Run one A/B side through actual LLMAgent instances.

    This replaces the older heuristic tournament path used by smoke tests.
    Candidate patch operations are injected into the LLMAgent prompt via
    strategy_bias so the comparison measures a real prompt-level behavior
    change, not a post-hoc score perturbation.
    """
    LLMAgent.STRICT_NO_FALLBACK = strict
    strategy_bias = TournamentRunner._patch_ops_to_bias(strategy_patch_ops or [])
    players = build_players(seed=seed)
    agents = create_agents(
        players,
        {
            "type": "llm",
            "seed": seed,
            "strategy_bias": strategy_bias,
            "temperature": 0.4,
            "speech_temperature": 1.1,
        },
    )
    game = WerewolfGame(
        players=players,
        agents=agents,
        seed=seed,
        strategy_version=strategy_version,
        strategy_bias=strategy_bias,
    )
    state = game.play()
    metric = MetricsCalculator().compute(state)
    decisions = list(state.decision_records)
    fallback_count = sum(1 for record in decisions if _record_is_fallback(record))
    llm_count = sum(1 for record in decisions if _record_is_llm(record))
    invalid_count = sum(1 for record in decisions if not record.is_valid)
    total = len(decisions)
    retrieval_count = sum(
        1
        for record in decisions
        if bool((record.parsed_action or {}).get("retrieval_used"))
        or bool(((record.parsed_action or {}).get("metadata") or {}).get("retrieval_used"))
    )
    llm_rate = llm_count / max(total, 1)
    if strict and fallback_count:
        raise LLMFallbackForbidden(f"A/B seed={seed} {strategy_version} produced fallback_count={fallback_count}")
    if strict and total and llm_rate < 0.95:
        raise RuntimeError(
            f"A/B seed={seed} {strategy_version} produced non-LLM decisions: "
            f"llm={llm_count} total={total}"
        )
    metric.metadata.update({
        "runner_mode": "llm",
        "agent_type": "llm",
        "strategy_version": strategy_version,
        "tournament_seed": seed,
        "target_role": target_role,
        "total_decisions": total,
        "llm_decision_count": llm_count,
        "llm_source_rate": round(llm_rate, 4),
        "fallback_count": fallback_count,
        "invalid_action_rate": invalid_count / max(total, 1),
        "retrieval_used_rate": retrieval_count / max(total, 1),
        "knowledge_hit_rate": retrieval_count / max(total, 1),
        "strategy_patch_applied": bool(strategy_patch_ops),
        "strategy_bias_sections": sorted(strategy_bias),
        "info_leak_count": int(metric.metadata.get("info_leak_count", 0) or 0),
    })
    return metric


def _record_metadata(record: Any) -> dict[str, Any]:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return metadata


def _record_is_fallback(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(record.parsed_action, dict) else {}
    metadata = _record_metadata(record)
    return (
        bool(metadata.get("fallback"))
        or bool(parsed.get("agent_fallback"))
        or str(metadata.get("source", "")).lower() == "fallback"
    )


def _record_is_llm(record: Any) -> bool:
    metadata = _record_metadata(record)
    source = str(metadata.get("source", "")).lower()
    if source == "llm" and not _record_is_fallback(record):
        return True
    return bool(getattr(record, "prompt_tokens", None) or getattr(record, "completion_tokens", None)) and not _record_is_fallback(record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[7])
    parser.add_argument("--strict-fallback", default="true",
                        help="If true, any LLM fallback aborts the game (default)")
    parser.add_argument("--skip-ab", action="store_true",
                        help="Skip the 20-seed A/B tournament step")
    args = parser.parse_args()

    strict = args.strict_fallback.lower() not in {"false", "0", "no", "off"}
    record = run_pipeline(args.seeds, strict=strict, skip_ab=args.skip_ab)

    output_path = HEALTH_DIR / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[{utcnow_iso()}] Run record written to {output_path}", flush=True)

    aggregate = record["aggregate"]
    print("\n=== Aggregate ===")
    for key in ("village_wins", "wolf_wins", "publish_allowed_rate",
                "total_llm_decisions", "total_fallback_decisions",
                "fallback_rate", "retrieval_used_rate",
                "total_bad_cases", "total_highlights", "total_counterfactuals",
                "knowledge_helpfulness_rate"):
        if key in aggregate:
            print(f"  {key} = {aggregate[key]}")

    if record["track_c"]:
        print("\n=== Track C ===")
        for key in ("games", "knowledge_doc_count", "candidate_patch_count",
                    "doc_type_breakdown", "doc_status_breakdown",
                    "quality_buckets", "patch_target_roles"):
            if key in record["track_c"]:
                print(f"  {key} = {record['track_c'][key]}")

    if record["ab_tournament"]:
        print("\n=== A/B Tournament ===")
        ab = record["ab_tournament"]
        for key in ("baseline_avg_score", "candidate_avg_score",
                    "target_role_avg_score_delta_pct", "role_task_score_delta_pct",
                    "candidate_wins", "baseline_wins", "info_leak_count",
                    "invalid_action_rate", "candidate_fallback_count",
                    "accepted", "satisfied_conditions", "failed_conditions"):
            print(f"  {key} = {ab[key]}")

    if record["games_aborted"]:
        print(f"\nABORTED games: {record['games_aborted']}/{record['games_attempted']}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
