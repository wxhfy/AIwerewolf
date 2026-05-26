"""Quantitative B/C heuristic smoke audit.

Runs the full Track B -> Track C pipeline with two cohorts:
  (1) Heuristic-only engine games (deterministic ground truth)
  (2) Mocked LLM failures injected into otherwise-real decisions
      to confirm that the AgentRobustnessGate actually blocks fallback paths.

Outputs a JSON-friendly summary with success rates for each stage so we can
see, step by step, whether B/C is actually working end-to-end or just looks
green because the suite uses deterministic helpers everywhere.

This script is deliberately NOT the final acceptance runner. Production
acceptance must use scripts/run_full_llm_pipeline.py so every game and A/B
tournament row carries LLM decision-source evidence.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Tests sometimes leak DB state; isolate to an in-memory store for this run.
os.environ.setdefault("AIWEREWOLF_DB_URL", "sqlite:///:memory:")
os.environ.setdefault("STRATEGY_EMBEDDING_PROVIDER", "hashing")
os.environ.setdefault("STRATEGY_RERANK_PROVIDER", "off")
os.environ.setdefault("STRATEGY_RERANK_STRICT", "false")

from backend.engine.game import WerewolfGame
from backend.engine.models import (
    Alignment,
    DecisionAudit,
    GameState,
    Phase,
    Role,
)
from backend.eval.evolution import (
    ABComparison,
    AcceptancePolicy,
    DreamJob,
    EvolutionPipeline,
    KnowledgeDocValidator,
    PatchValidator,
    RoleStrategyCard,
    StrategyKnowledgeDocExtractor,
    StrategyKnowledgeStore,
    StrategyRetrievalQuery,
    TournamentRunner,
    VersionManager,
)
from backend.eval.review import (
    GameMetrics,
    MetricsCalculator,
    ReviewReportBuilder,
)
from backend.eval.track_b import (
    generate_published_review_document,
    ReplayBundleBuilder,
    ReviewRepairLoop,
    SpeechActAnalyzer,
    SuspicionMatrixBuilder,
    TrackBValidator,
)


def step(name: str, total: int) -> Callable[[Callable[[], Any]], dict[str, Any]]:
    def runner(fn: Callable[[], Any]) -> dict[str, Any]:
        successes = 0
        failures = 0
        errors: list[str] = []
        artifact: Any = None
        wall = 0.0
        for i in range(total):
            t0 = time.perf_counter()
            try:
                artifact = fn() if i == total - 1 else fn()
                successes += 1
            except Exception as exc:  # noqa: BLE001 - we want everything
                failures += 1
                errors.append(f"{type(exc).__name__}: {exc}")
            wall += time.perf_counter() - t0
        rate = successes / max(total, 1)
        print(
            f"[{name:>40}] success={successes:>3}/{total} "
            f"rate={rate*100:6.2f}%  avg_ms={wall*1000/max(total,1):7.1f}"
        )
        return {
            "name": name,
            "samples": total,
            "success": successes,
            "failure": failures,
            "success_rate": rate,
            "errors": errors[:3],
            "avg_ms": wall * 1000 / max(total, 1),
            "artifact": artifact,
        }
    return runner


def build_heuristic_game(seed: int) -> WerewolfGame:
    game = WerewolfGame(seed=seed)
    game.play()
    if game.state.phase != Phase.GAME_END:
        raise RuntimeError(f"game did not finish: phase={game.state.phase}")
    return game


def heuristic_validation(seed: int) -> dict[str, Any]:
    game = build_heuristic_game(seed)
    doc = generate_published_review_document(game.state)
    return {
        "passed": doc.validation_result["passed"],
        "publish_allowed": doc.validation_result["publish_allowed"],
        "status": doc.status,
        "issues": len(doc.validation_result.get("issues", [])),
        "score": doc.validation_result["score"],
    }


def fallback_injection(seed: int) -> dict[str, Any]:
    """Confirm that injecting a single fallback decision blocks publishing."""
    game = build_heuristic_game(seed)
    player = game.state.players[0]
    game.state.decision_records.append(
        DecisionAudit(
            id=f"injected-{seed}",
            game_id=game.state.id,
            player_id=player.id,
            day=1,
            phase=Phase.DAY_SPEECH.value,
            request="TALK",
            observation={},
            legal_actions=[],
            prompt_version="v1",
            raw_output=None,
            parsed_action={
                "action_type": "talk",
                "speech": "fallback speech",
                "metadata": {"source": "fallback", "fallback": True},
            },
            is_valid=True,
            error_type=None,
            latency_ms=None,
            prompt_tokens=None,
            completion_tokens=None,
            created_at=0.0,
        )
    )
    doc = generate_published_review_document(game.state)
    return {
        "publish_allowed": doc.validation_result["publish_allowed"],
        "status": doc.status,
        "gates_triggered": sorted(
            {issue.get("gate") for issue in doc.validation_result.get("issues", [])}
        ),
    }


def invalid_decision_injection(seed: int) -> dict[str, Any]:
    """Confirm an invalid decision also blocks publishing."""
    game = build_heuristic_game(seed)
    player = game.state.players[0]
    game.state.decision_records.append(
        DecisionAudit(
            id=f"invalid-{seed}",
            game_id=game.state.id,
            player_id=player.id,
            day=1,
            phase=Phase.DAY_SPEECH.value,
            request="TALK",
            observation={},
            legal_actions=[],
            prompt_version="v1",
            raw_output=None,
            parsed_action={"action_type": "talk"},
            is_valid=False,
            error_type="parse_failure",
            latency_ms=None,
            prompt_tokens=None,
            completion_tokens=None,
            created_at=0.0,
        )
    )
    doc = generate_published_review_document(game.state)
    return {
        "publish_allowed": doc.validation_result["publish_allowed"],
        "gates_triggered": sorted(
            {issue.get("gate") for issue in doc.validation_result.get("issues", [])}
        ),
    }


def fact_consistency_check(seed: int) -> dict[str, Any]:
    """Inject a bogus evidence_event_id; expect FactConsistencyGate to flag it."""
    game = build_heuristic_game(seed)
    state = game.state
    bundle = ReplayBundleBuilder().build(state)
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    payload = json.loads(json.dumps(_to_jsonable(report)))
    # Inject an unknown evidence id into the first available section
    target_section = None
    for key in ("bad_cases", "turning_points", "counterfactuals", "mvp_results"):
        if payload.get(key):
            payload[key][0]["evidence_event_ids"] = ["FAKE_EVENT_DOES_NOT_EXIST"]
            target_section = key
            break
    if target_section is None:
        return {"skipped": True, "reason": "no report sections with items"}
    validator = TrackBValidator()
    sa = SpeechActAnalyzer().analyze(state)
    sm = SuspicionMatrixBuilder().build(state, sa)
    result = validator.validate(
        report_id="bogus-id",
        game_id=state.id,
        replay_bundle=bundle,
        review_report=payload,
        markdown="",
        speech_acts=sa,
        suspicion_matrix=sm,
        view_scope="moderator_view",
    )
    gates = sorted({i.gate for i in result.issues})
    return {
        "target_section": target_section,
        "passed": result.passed,
        "publish_allowed": result.publish_allowed,
        "gates_triggered": gates,
        "fact_gate_present": "FactConsistencyGate" in gates,
    }


def evidence_coverage_check(seed: int) -> dict[str, Any]:
    """Strip evidence; expect EvidenceCoverageGate critical."""
    game = build_heuristic_game(seed)
    state = game.state
    bundle = ReplayBundleBuilder().build(state)
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    payload = json.loads(json.dumps(_to_jsonable(report)))
    target_section = None
    for key in ("bad_cases", "turning_points", "counterfactuals", "mvp_results", "strategy_suggestions"):
        if payload.get(key):
            payload[key][0]["evidence_event_ids"] = []
            target_section = key
            break
    if target_section is None:
        return {"skipped": True}
    validator = TrackBValidator()
    sa = SpeechActAnalyzer().analyze(state)
    sm = SuspicionMatrixBuilder().build(state, sa)
    result = validator.validate(
        report_id="cov-id",
        game_id=state.id,
        replay_bundle=bundle,
        review_report=payload,
        markdown="",
        speech_acts=sa,
        suspicion_matrix=sm,
        view_scope="moderator_view",
    )
    gates = sorted({i.gate for i in result.issues})
    return {
        "target_section": target_section,
        "passed": result.passed,
        "publish_allowed": result.publish_allowed,
        "gates_triggered": gates,
        "evidence_gate_present": "EvidenceCoverageGate" in gates,
    }


def repair_loop_recovery(seed: int) -> dict[str, Any]:
    """Strip every evidence_event_id and let the repair loop refill them."""
    game = build_heuristic_game(seed)
    state = game.state
    bundle = ReplayBundleBuilder().build(state)
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    payload = json.loads(json.dumps(_to_jsonable(report)))
    sections = ("bad_cases", "turning_points", "counterfactuals", "strategy_suggestions", "mvp_results")
    stripped = 0
    for key in sections:
        for item in payload.get(key, []):
            if item.get("evidence_event_ids"):
                item["evidence_event_ids"] = []
                stripped += 1
    validator = TrackBValidator()
    sa = SpeechActAnalyzer().analyze(state)
    sm = SuspicionMatrixBuilder().build(state, sa)
    loop = ReviewRepairLoop()
    repaired_payload, _, validation, history = loop.run(
        replay_bundle=bundle,
        review_report=payload,
        markdown="",
        speech_acts=sa,
        suspicion_matrix=sm,
        validator=validator,
        view_scope="moderator_view",
    )
    refilled = 0
    for key in sections:
        for item in repaired_payload.get(key, []):
            if item.get("evidence_event_ids"):
                refilled += 1
    return {
        "stripped": stripped,
        "repaired_with_evidence": refilled,
        "rounds": len(history),
        "publish_allowed_after_repair": validation.publish_allowed,
        "issues_after": len(validation.issues),
    }


def knowledge_round_trip(seed: int) -> dict[str, Any]:
    """B report -> Knowledge docs -> sanitizer -> retrieval works."""
    game = build_heuristic_game(seed)
    state = game.state
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    report.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}
    docs = StrategyKnowledgeDocExtractor().extract([report])
    if not docs:
        raise RuntimeError("no knowledge docs extracted from approved report")
    validator = KnowledgeDocValidator()
    issues_total = 0
    leaked_player_name = False
    player_names = {p.name for p in state.players}
    for doc in docs:
        issues_total += len(validator.validate(doc))
        blob = f"{doc.situation_pattern} {doc.recommended_action} {doc.rationale}"
        if any(n in blob for n in player_names):
            leaked_player_name = True
    store = StrategyKnowledgeStore()
    store.upsert_many(docs)
    query = StrategyRetrievalQuery(
        role=docs[0].role,
        phase=docs[0].phase,
        observation_summary=docs[0].situation_pattern,
        situation_tags=list(docs[0].tags or [])[:3],
    )
    retrieved = store.retrieve(query)
    return {
        "docs_extracted": len(docs),
        "validator_issues": issues_total,
        "player_name_leak": leaked_player_name,
        "retrieval_hits": len(retrieved),
        "top_score": round(retrieved[0].score, 4) if retrieved else None,
        "retrieval_mode": retrieved[0].retrieval_mode if retrieved else None,
        "top_vector_score": round(retrieved[0].vector_score, 4) if retrieved else None,
        "top_lexical_score": round(retrieved[0].lexical_score, 4) if retrieved else None,
        "top_bm25_score": round(retrieved[0].bm25_score, 4) if retrieved else None,
        "top_fts_score": round(retrieved[0].fts_score, 4) if retrieved else None,
        "top_rerank_score": round(retrieved[0].rerank_score, 4) if retrieved else None,
        "embedding_provider": retrieved[0].embedding_provider if retrieved else None,
        "rerank_provider": retrieved[0].rerank_provider if retrieved else None,
    }


def db_persisted_retrieval() -> dict[str, Any]:
    """Persist knowledge to the real DB and re-retrieve via the DB query."""
    from backend.db.database import init_db, SessionLocal
    from backend.db.persist import _upsert_strategy_knowledge_rows, retrieve_strategy_knowledge

    # Build at least one approved report so we have something to write.
    game = build_heuristic_game(99)
    metrics = MetricsCalculator().compute(game.state)
    report = ReviewReportBuilder().build(game.state, metrics)
    report.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}
    docs = StrategyKnowledgeDocExtractor().extract([report])
    init_db()
    db = SessionLocal()
    try:
        _upsert_strategy_knowledge_rows(db, list(docs))
        db.commit()
    finally:
        db.close()
    target_role = docs[0].role
    target_phase = docs[0].phase
    rows = retrieve_strategy_knowledge(
        StrategyRetrievalQuery(
            role=target_role,
            phase=target_phase,
            observation_summary="generic table observation",
            situation_tags=list(docs[0].tags)[:3],
            top_k=5,
        )
    )
    return {
        "docs_persisted": len(docs),
        "rows_retrieved": len(rows),
        "role": target_role,
        "phase": target_phase,
        "retrieval_mode": rows[0].get("retrieval_mode") if rows else None,
        "top_vector_score": rows[0].get("vector_score") if rows else None,
        "top_lexical_score": rows[0].get("lexical_score") if rows else None,
        "top_bm25_score": rows[0].get("bm25_score") if rows else None,
        "top_fts_score": rows[0].get("fts_score") if rows else None,
        "top_rerank_score": rows[0].get("rerank_score") if rows else None,
        "embedding_provider": rows[0].get("embedding_provider") if rows else None,
        "rerank_provider": rows[0].get("rerank_provider") if rows else None,
    }


def evolution_full_pipeline() -> dict[str, Any]:
    games = [build_heuristic_game(seed) for seed in (7, 11)]
    reports = []
    metrics_all = []
    for game in games:
        m = MetricsCalculator().compute(game.state)
        metrics_all.append(m)
        r = ReviewReportBuilder().build(game.state, m)
        r.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}
        reports.append(r)

    summary = EvolutionPipeline().run(
        reports,
        baseline_metrics=metrics_all[:1],
        candidate_metrics=metrics_all[1:],
    )
    return {
        "approved_reports": summary.approved_report_count,
        "knowledge_docs": summary.knowledge_doc_count,
        "candidate_patches": summary.candidate_patch_count,
        "promoted": summary.promoted_versions,
        "rolled_back": summary.rolled_back_versions,
        "has_leaderboard": summary.leaderboard is not None,
    }


def tournament_real_20() -> dict[str, Any]:
    """The 'real' Track C A/B tournament: 20 fixed seeds, both sides through the engine."""
    runner = TournamentRunner()
    tournament = runner.run_ab_tournament(
        baseline_version="seer_v1",
        candidate_version="seer_v2_candidate",
        target_role="Seer",
        seeds=list(range(1, 21)),
    )
    cmp = tournament.comparison
    return {
        "seeds": len(tournament.seeds),
        "baseline_games": len(tournament.baseline_results),
        "candidate_games": len(tournament.candidate_results),
        "candidate_fallback_count": cmp["candidate_fallback_count"],
        "baseline_avg_score": cmp.get("baseline_avg_score"),
        "candidate_avg_score": cmp.get("candidate_avg_score"),
        "info_leak_count": cmp.get("info_leak_count"),
        "invalid_action_rate": cmp.get("invalid_action_rate"),
        "status": tournament.status,
    }


def acceptance_rejects_fallback() -> dict[str, Any]:
    comp = ABComparison(
        baseline_version="v1",
        candidate_version="v2",
        total_games=20,
        baseline_wins=10,
        candidate_wins=14,
        baseline_avg_score=60.0,
        candidate_avg_score=72.0,
        target_role_avg_score_delta=12.0,
        role_task_score_delta=30.0,
        critical_mistakes_delta=-0.5,
        info_leak_count=0,
        invalid_action_rate=0.0,
        candidate_fallback_count=1,
    )
    decision = AcceptancePolicy().decide(comp)
    return {
        "accepted_with_fallback": decision.accepted,
        "satisfied": decision.satisfied_conditions[:],
        "rejected_for_fallback": not decision.accepted,
    }


def _to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_jsonable(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


def main() -> None:
    summary: dict[str, Any] = {}

    summary["heuristic_pipeline_publish"] = step(
        "S1: heuristic game -> publish", 10
    )(lambda: heuristic_validation(7 + int(time.time_ns() % 1000)))

    summary["fallback_blocks_publish"] = step(
        "S2: inject fallback blocks publish", 10
    )(lambda: fallback_injection(13 + int(time.time_ns() % 1000)))

    summary["invalid_blocks_publish"] = step(
        "S3: invalid decision blocks publish", 10
    )(lambda: invalid_decision_injection(31 + int(time.time_ns() % 1000)))

    summary["fact_gate_catches_bogus_id"] = step(
        "S4: fact gate catches bogus event id", 10
    )(lambda: fact_consistency_check(41 + int(time.time_ns() % 1000)))

    summary["evidence_gate_catches_strip"] = step(
        "S5: evidence gate catches missing evidence", 10
    )(lambda: evidence_coverage_check(53 + int(time.time_ns() % 1000)))

    summary["repair_loop_recovers"] = step(
        "S6: repair loop restores publishability", 10
    )(lambda: repair_loop_recovery(67 + int(time.time_ns() % 1000)))

    summary["knowledge_round_trip"] = step(
        "S7: B report -> knowledge -> retrieval", 10
    )(lambda: knowledge_round_trip(73 + int(time.time_ns() % 1000)))

    summary["db_persisted_retrieval"] = step(
        "S8: DB persist + retrieve", 1
    )(db_persisted_retrieval)

    summary["evolution_full_pipeline"] = step(
        "S9: EvolutionPipeline.run()", 1
    )(evolution_full_pipeline)

    summary["tournament_real_20"] = step(
        "S10: real 20-seed A/B tournament", 1
    )(tournament_real_20)

    summary["acceptance_rejects_fallback"] = step(
        "S11: AcceptancePolicy rejects fallback>0", 1
    )(acceptance_rejects_fallback)

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "heuristic_smoke_not_final_acceptance",
        "final_acceptance_runner": "scripts/run_full_llm_pipeline.py",
        "summary": {k: {kk: vv for kk, vv in v.items() if kk != "artifact"} for k, v in summary.items()},
        "last_artifacts": {k: _to_jsonable(v.get("artifact")) for k, v in summary.items()},
    }
    out_path = os.path.join(ROOT, "bc_quantify_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print()
    print(f"summary written -> {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
