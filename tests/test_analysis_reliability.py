"""Durable Track B/C analysis recovery and API boundary integration tests."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.application.analysis import repository as repository_module
from backend.application.analysis import service as service_module
from backend.application.analysis.repository import AnalysisRepository
from backend.core.errors import install_exception_handlers
from backend.db import database
from backend.db import persist
from backend.db.models import AgentDecision
from backend.db.models import Base
from backend.db.models import DecisionEvaluation
from backend.db.models import Game
from backend.db.models import OutboxEvent
from backend.db.models import TrackCPostGameJob
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.interfaces.http.analysis_api import router


@pytest.fixture
def analysis_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(persist, "SessionLocal", sessions)
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(repository_module, "SessionLocal", sessions)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(database, "init_db", lambda: None)
    with sessions() as db:
        db.add_all(
            [
                Game(id="finished", status="finished", current_phase="GAME_END"),
                Game(id="ongoing", status="running", current_phase="DAY_SPEECH"),
            ]
        )
        db.commit()
    yield sessions
    engine.dispose()


def _due(sessions, *, game_id="finished"):
    with sessions() as db:
        row = db.query(TrackCPostGameJob).filter_by(game_id=game_id).one()
        row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()


def test_claim_requires_finished_match_and_fences_stale_attempt(analysis_db):
    persist.ensure_track_c_post_game_job("ongoing")
    assert persist.claim_track_c_post_game_job("ongoing") is None
    first = persist.claim_track_c_post_game_job("finished")
    assert first["attempts"] == 1
    assert persist.claim_track_c_post_game_job("finished") is None
    with analysis_db() as db:
        db.query(TrackCPostGameJob).filter_by(game_id="finished").update({"locked_at": datetime(2000, 1, 1)})
        db.commit()
    second = persist.claim_track_c_post_game_job("finished", stale_after_seconds=1)
    assert second["attempts"] == 2
    assert second["claim_token"] != first["claim_token"]
    assert not persist.heartbeat_track_c_post_game_job("finished", first["claim_token"])
    assert persist.complete_track_c_post_game_job("finished", claim_token=first["claim_token"]) is None
    assert persist.fail_track_c_post_game_job("finished", "late", claim_token=first["claim_token"]) is None
    assert persist.heartbeat_track_c_post_game_job("finished", second["claim_token"])
    done = persist.complete_track_c_post_game_job("finished", claim_token=second["claim_token"])
    assert done["lifecycle_status"] == "published"
    assert persist.fail_track_c_post_game_job("finished", "late") is None


def test_backoff_exhaustion_and_outbox_redelivery_do_not_revive_failure(analysis_db):
    first = persist.claim_track_c_post_game_job("finished")
    failed = persist.fail_track_c_post_game_job("finished", "transient", claim_token=first["claim_token"])
    assert failed["status"] == "pending"
    assert failed["available_at"]
    assert persist.claim_track_c_post_game_job("finished") is None
    assert persist.list_recoverable_track_c_post_game_jobs() == []
    _due(analysis_db)
    assert len(persist.list_recoverable_track_c_post_game_jobs()) == 1
    for attempt in (2, 3):
        claimed = persist.claim_track_c_post_game_job("finished")
        assert claimed["attempts"] == attempt
        failed = persist.fail_track_c_post_game_job("finished", "transient", claim_token=claimed["claim_token"])
        if attempt < 3:
            _due(analysis_db)
    assert failed["status"] == "failed"
    assert failed["metadata"]["dead_letter"]
    assert persist.ensure_track_c_post_game_job("finished")["status"] == "failed"
    with analysis_db() as db:
        persist._ensure_match_analysis_outbox(db, "finished", source="duplicate")
        db.commit()
    assert persist.dispatch_match_analysis_outbox() == 1
    with analysis_db() as db:
        assert db.query(TrackCPostGameJob).filter_by(game_id="finished").one().status == "failed"


def test_exhausted_worker_crash_becomes_observable_failure(analysis_db):
    with analysis_db() as db:
        db.add(
            TrackCPostGameJob(
                game_id="finished",
                status="running",
                attempts=3,
                max_attempts=3,
                claim_token="dead-worker",
                locked_at=datetime(2000, 1, 1),
            )
        )
        db.commit()
    assert persist.list_recoverable_track_c_post_game_jobs() == []
    with analysis_db() as db:
        row = db.query(TrackCPostGameJob).filter_by(game_id="finished").one()
        assert row.status == "failed"
        assert row.finished_at
        assert row.claim_token is None


def test_outbox_partial_delivery_backoff_and_dead_letter(analysis_db):
    with analysis_db() as db:
        db.add_all(
            [
                OutboxEvent(aggregate_type="match", aggregate_id=game_id, event_type="match.analysis.requested")
                for game_id in ("finished", "missing")
            ]
        )
        db.commit()
    assert persist.dispatch_match_analysis_outbox(max_attempts=2) == 1
    assert persist.dispatch_match_analysis_outbox(max_attempts=2) == 0
    with analysis_db() as db:
        bad = db.query(OutboxEvent).filter_by(aggregate_id="missing").one()
        assert bad.status == "pending"
        assert bad.attempts == 1
        assert bad.last_error == "ValueError: analysis delivery failed"
        bad.available_at = datetime(2000, 1, 1)
        db.commit()
    assert persist.dispatch_match_analysis_outbox(max_attempts=2) == 0
    with analysis_db() as db:
        bad = db.query(OutboxEvent).filter_by(aggregate_id="missing").one()
        assert bad.status == "dead_letter"
        assert bad.attempts == 2
        assert db.query(TrackCPostGameJob).filter_by(game_id="finished").count() == 1


def test_retry_api_errors_and_idempotency_preserve_attempt_budget(analysis_db):
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router)
    client = TestClient(app)
    for match, expected, code in [("missing", 404, "match_not_found"), ("ongoing", 409, "match_not_finished")]:
        response = client.post(f"/api/v1/matches/{match}/analysis/retry")
        assert response.status_code == expected
        assert response.json()["code"] == code
        assert response.headers["content-type"] == "application/problem+json"
    first = persist.claim_track_c_post_game_job("finished")
    assert client.post("/api/v1/matches/finished/analysis/retry").json()["code"] == "analysis_running"
    persist.fail_track_c_post_game_job("finished", "terminal", retryable=False, claim_token=first["claim_token"])
    headers = {"Idempotency-Key": "recovery-1"}
    accepted = client.post("/api/v1/matches/finished/analysis/retry", headers=headers)
    assert accepted.status_code == 202
    second = persist.claim_track_c_post_game_job("finished")
    duplicate = client.post("/api/v1/matches/finished/analysis/retry", headers=headers)
    assert duplicate.status_code == 202
    assert duplicate.json() == accepted.json()
    persist.fail_track_c_post_game_job("finished", "transient", claim_token=second["claim_token"])
    client.post("/api/v1/matches/finished/analysis/retry", headers={"Idempotency-Key": "recovery-2"})
    with analysis_db() as db:
        row = db.query(TrackCPostGameJob).filter_by(game_id="finished").one()
        assert row.attempts == 1
        assert row.available_at
        assert row.last_error == "transient"


def test_summary_coverage_counts_unique_decisions_across_evaluator_versions(analysis_db):
    with analysis_db() as db:
        db.add(AgentDecision(id="decision", game_id="finished", player_id="P1"))
        db.add_all(
            [
                DecisionEvaluation(
                    game_id="finished", decision_id="decision", player_id="P1", evaluator_version=version
                )
                for version in ("v1", "v2")
            ]
        )
        db.commit()
    summary = AnalysisRepository().get_summary("finished")
    assert summary["evaluated_decision_count"] == 1
    assert summary["evaluation_coverage"] == 1


def test_service_retries_coordinator_from_track_b_checkpoint(analysis_db, monkeypatch):
    state = GameState(id="finished", phase=Phase.GAME_END, day=1, players=[])
    calls = []
    monkeypatch.setattr(service_module, "build_post_game_state_from_db", lambda _: state)
    monkeypatch.setattr(
        service_module,
        "run_post_game_scoring",
        lambda *args, **kwargs: calls.append("score") or {"decisions_scored": 2, "lessons_stored": 1},
    )
    monkeypatch.setattr(service_module, "run_agent_reflections", lambda _: calls.append("reflect") or 0)
    monkeypatch.setattr(service_module, "save_post_game_artifacts", lambda *args, **kwargs: calls.append("publish"))

    def fail_coordinator(*args, **kwargs):
        raise RuntimeError("not persisted exception payload")

    monkeypatch.setattr(service_module, "coordinate_evolution", fail_coordinator)
    with pytest.raises(RuntimeError):
        service_module.PostGameAnalysisService().execute("finished")
    with analysis_db() as db:
        row = db.query(TrackCPostGameJob).filter_by(game_id="finished").one()
        assert row.extra_metadata["track_b_complete"]
        assert row.extra_metadata["stage"] == "track_c_coordinator"
        assert row.last_error == "RuntimeError: analysis stage failed"
    _due(analysis_db)
    monkeypatch.setattr(
        service_module,
        "coordinate_evolution",
        lambda *args, **kwargs: {"status": "pending_review", "promoted_count": 0},
    )
    result = service_module.PostGameAnalysisService().execute("finished")
    assert result["status"] == "completed"
    assert result["metadata"]["track_c"]["status"] == "pending_review"
    assert calls == ["score", "reflect", "publish"]
    assert service_module.PostGameAnalysisService().execute("finished") is None


def test_state_rebuild_error_is_retryable_not_stuck_running(analysis_db, monkeypatch):
    def failed_rebuild(_):
        raise RuntimeError("rebuild failed")

    monkeypatch.setattr(service_module, "build_post_game_state_from_db", failed_rebuild)
    with pytest.raises(RuntimeError):
        service_module.PostGameAnalysisService().execute("finished")
    with analysis_db() as db:
        row = db.query(TrackCPostGameJob).filter_by(game_id="finished").one()
        assert row.status == "pending"
        assert row.extra_metadata["stage"] == "state_rebuild"


def test_late_artifact_writer_is_fenced_in_artifact_transaction(analysis_db):
    job = persist.claim_track_c_post_game_job("finished")
    with pytest.raises(persist.AnalysisClaimLost):
        persist.save_post_game_artifacts(
            GameState(id="finished", phase=Phase.GAME_END, day=1, players=[]), claim_token="stale"
        )
    assert persist.heartbeat_track_c_post_game_job("finished", job["claim_token"])


def test_atomic_claim_has_one_winner_across_connections(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine = create_engine(f"sqlite:///{tmp_path / 'claims.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(persist, "SessionLocal", sessions)
    monkeypatch.setattr(persist, "init_db", lambda: None)
    with sessions() as db:
        db.add(Game(id="race", status="finished"))
        db.commit()
    persist.ensure_track_c_post_game_job("race")
    ready = Barrier(2)

    def claim():
        ready.wait(timeout=5)
        return persist.claim_track_c_post_game_job("race")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(result is not None for result in results) == 1
    with sessions() as db:
        assert db.query(TrackCPostGameJob).filter_by(game_id="race").one().attempts == 1
    engine.dispose()


def test_manual_retry_generation_resumes_transients_but_reconsiders_completed_work(analysis_db):
    repository = AnalysisRepository()
    repository.retry("finished", actor_id="operator", idempotency_key="initial")
    first = persist.claim_track_c_post_game_job("finished")
    persist.complete_track_c_post_game_job(
        "finished", claim_token=first["claim_token"], metadata={"track_b_complete": True}
    )
    repository.retry("finished", actor_id="operator", idempotency_key="reconsider")
    second = persist.claim_track_c_post_game_job("finished")
    assert second["metadata"]["retry_generation"] == 1
    assert second["metadata"]["track_b_complete"]
    persist.fail_track_c_post_game_job("finished", "transient", claim_token=second["claim_token"])
    repository.retry("finished", actor_id="operator", idempotency_key="same-work")
    _due(analysis_db)
    third = persist.claim_track_c_post_game_job("finished")
    assert third["metadata"]["retry_generation"] == 1


@pytest.mark.parametrize("calibrated", [False, True])
def test_legacy_cycle_never_bypasses_coordinator_promotion(analysis_db, monkeypatch, calibrated):
    from types import SimpleNamespace

    from backend.db import judge_calibration
    from backend.eval import evolution

    patch = {
        "patch_id": "legacy-patch",
        "patch_type": "role_strategy",
        "target_role": "Seer",
        "from_version": "v1",
        "to_version": "seer-candidate",
        "source_knowledge_doc_ids": ["doc"],
        "operations": [
            {"op": "add", "section": "speech_policy", "new_value": "优先核对公开证据", "rationale": "synthetic test"}
        ],
    }
    monkeypatch.setattr(persist, "run_dream_job", lambda *args, **kwargs: {"candidate_patches": [patch]})
    monkeypatch.setattr(persist, "_build_bc_acceptance_audit_from_db", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        judge_calibration,
        "latest_approved_calibration",
        lambda *args, **kwargs: (
            {"calibration_id": "real-human-calibration", "auto_promotion_allowed": True} if calibrated else None
        ),
    )
    monkeypatch.setenv("TRACK_B_JUDGE_MODEL", "uncalibrated-judge")
    monkeypatch.setenv("LLM_PROVIDER", "provider-under-test")

    def unexpected_promotion(*args, **kwargs):
        pytest.fail("Uncalibrated legacy evolution must not promote")

    monkeypatch.setattr(evolution.VersionManager, "promote", unexpected_promotion)

    class WinningTournament(SimpleNamespace):
        def to_dict(self):
            return vars(self)

    def fake_tournament(self, **kwargs):
        assert kwargs["candidate_patch_ops"][0].new_value == "优先核对公开证据"
        return WinningTournament(
            tournament_id="legacy-tournament",
            baseline_version="v1",
            candidate_version="seer-candidate",
            target_role="Seer",
            seeds=[1, 2],
            baseline_results=[],
            candidate_results=[],
            comparison={},
            decision={"accepted": True},
            status="promoted",
        )

    monkeypatch.setattr(evolution.TournamentRunner, "run_ab_tournament", fake_tournament)
    result = persist.run_evolution_cycle(seeds=[1, 2])
    assert result["summary"]["promoted"] == 0
    assert result["summary"]["pending_review"] == 1
    assert result["patch_results"][0]["patch"]["status"] == "pending_review"
    assert not result["patch_results"][0]["tournament"]["decision"]["accepted"]
    assert result["patch_results"][0]["tournament"]["decision"]["requires_coordinator"]


def test_stale_analysis_cannot_write_scores_or_reflections(analysis_db):
    from backend.application.analysis.reflection_engine import ReflectionResult
    from backend.application.analysis.reflection_engine import save_reflections_to_db

    job = persist.claim_track_c_post_game_job("finished")
    reflection = ReflectionResult(
        player_id="P1",
        player_name="seer",
        role="Seer",
        persona_scope="mbti:INTJ",
        won=True,
        what_worked=["对照公开发言验证推理"],
    )
    with persist.analysis_write_scope("finished", "expired-owner"):
        with pytest.raises(persist.AnalysisClaimLost):
            AnalysisRepository().save_decision_scores("finished", [])
        with pytest.raises(persist.AnalysisClaimLost):
            save_reflections_to_db([reflection], "finished")
    assert persist.heartbeat_track_c_post_game_job("finished", job["claim_token"])


def test_ingested_strategic_knowledge_is_pending_review_and_retry_is_idempotent(analysis_db):
    from backend.db.models import StrategyKnowledgeDoc as KnowledgeRow
    from backend.eval.evolution import StrategyKnowledgeDoc

    doc = StrategyKnowledgeDoc(
        doc_id="lesson",
        doc_type="per_step_lesson",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="公开票型压力",
        trigger_conditions=[],
        recommended_action="优先核验公开证据",
        avoid_action=None,
        rationale="synthetic regression fixture",
        evidence_summary="test-only",
        source_report_ids=["finished"],
        source_item_ids=["decision"],
        source_event_ids=[],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=0.9,
        confidence=0.9,
    )
    with analysis_db() as db:
        persist._upsert_strategy_knowledge_rows(db, [doc])
        db.commit()
    with analysis_db() as db:
        persist._upsert_strategy_knowledge_rows(db, [doc])
        db.commit()
        row = db.query(KnowledgeRow).filter_by(id="lesson").one()
        assert row.status == "pending_review"
        assert row.usage_count == 1
        assert row.quality_score == 0.9
        row.status = "active"
        db.commit()
        persist._upsert_strategy_knowledge_rows(db, [doc])
        db.commit()
        assert row.status == "active"
