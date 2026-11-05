"""Small offline fixtures exercise orchestration; they are not production evidence."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from backend.application.evolution import coordinator as module
from backend.application.evolution.coordinator import CoordinatorLeaseLost
from backend.application.evolution.coordinator import TrackCCoordinator
from backend.application.evolution.tournament import TournamentTask
from backend.application.evolution.tournament import TournamentWorker
from backend.db.evolution_jobs import EvolutionArtifact
from backend.db.evolution_jobs import EvolutionRoleHead
from backend.db.evolution_jobs import EvolutionRun
from backend.db.models import Base
from backend.db.models import EvolutionTournament
from backend.db.models import RoleStrategyCard as CardRow
from backend.db.models import StrategyKnowledgeDoc as KnowledgeRow
from backend.eval.evolution import RoleStrategyCard
from backend.eval.evolution import TournamentRunner
from backend.eval.review import GameMetrics
from backend.eval.review import PlayerScore
from backend.eval.types import EvidenceRef
from backend.eval.types import EvolutionCandidate
from backend.eval.types import ReviewReport


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'coordinator.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "init_db", lambda: None)
    yield factory
    engine.dispose()


def report(game_id="source"):
    return ReviewReport(
        game_id=game_id,
        winner="village",
        total_days=2,
        total_events=10,
        game_summary="Offline test fixture",
        metadata={"validation_result": {"passed": True, "publish_allowed": True}},
        evolution_candidates=[
            EvolutionCandidate(
                source_id="public-vote-evidence",
                source_type="counterfactual",
                role="Seer",
                phase="DAY_VOTE",
                trigger_condition="Public vote evidence is available before a vote.",
                lesson="Compare public vote evidence before announcing a conditional position.",
                evidence_refs=[EvidenceRef(event_type="VOTE_CAST", summary="Public evidence was not used.")],
                quality_signals={"confidence": 0.9, "judge_agreement": 0.9},
            )
        ],
    )


def metric(seed=1, candidate=False, **metadata):
    return GameMetrics(
        game_id=f"fixture-{seed}-{candidate}",
        winner="village",
        total_days=1,
        total_events=5,
        wolf_elimination_rate=1,
        village_survival_rate=1,
        info_efficiency=1,
        player_scores=[
            PlayerScore(
                player_id="fixture-seer",
                player_name="Fixture",
                persona_id=None,
                persona_name=None,
                role="Seer",
                alignment="village",
                camp_result_score=1,
                role_task_score=0.8 if candidate else 0.5,
                vote_score=0.7,
                speech_score=0.7,
                skill_score=0.7,
                survival_score=1,
                mistake_penalty=0,
                final_score=80 if candidate else 50,
                adjusted_final_score=80 if candidate else 50,
            )
        ],
        metadata={
            "target_role": "Seer",
            "tournament_seed": seed,
            "lineup_hash": "fixture-lineup",
            "phase": "GAME_END",
            "synthetic": False,
            "model_assignments": [{"seat": 1, "provider": "fixture-real", "model": "fixture-llm"}],
            "invalid_action_count": 0,
            "fallback_count": 0,
            "info_leak_count": 0,
            "patch_caused_fallback_count": 0,
            "rule_violation_count": 0,
            "invalid_action_rate": 0,
            **metadata,
        },
    )


class FixtureWorker:
    """Injected deterministic test metrics, never used by default runtime."""

    def __init__(self, *, fail_seed=None, synthetic=False, invalid=False):
        self.calls = []
        self.fail_seed = fail_seed
        self.synthetic = synthetic
        self.invalid = invalid
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def execute(self, task):
        with self.lock:
            self.calls.append(task.seed)
            self.active += 1
            self.max_active = max(self.active, self.max_active)
        try:
            time.sleep(0.005)
            if self.fail_seed == task.seed:
                raise RuntimeError("retry fixture")
            baseline, candidate = metric(task.seed), metric(task.seed, True, invalid_action_count=int(self.invalid))
            candidate.metadata["invalid_action_rate"] = int(self.invalid)
            baseline.metadata["strategy_version"] = task.baseline.version
            candidate.metadata["strategy_version"] = task.candidate.version
            for item in (baseline, candidate):
                item.metadata["synthetic"] = self.synthetic
                item.metadata["model_assignments"] = [
                    {"seat": 1, "provider": task.provider, "model": "fake-llm" if self.synthetic else "fixture-llm"}
                ]
            return {
                "schema_version": "paired-tournament-v1",
                "task_id": task.task_id,
                "seed": task.seed,
                "synthetic": self.synthetic,
                "lineup_hash": "fixture-lineup",
                "baseline": asdict(baseline),
                "candidate": asdict(candidate),
            }
        finally:
            with self.lock:
                self.active -= 1


def coordinator(sessions, worker, *, seeds=None, **kwargs):
    return TrackCCoordinator(
        session_factory=sessions,
        tournament_worker=worker,
        seeds=seeds or [7, 11, 19],
        provider="fixture-real",
        judge_model="fixture-judge",
        **kwargs,
    )


def approved_profile(*_args, **_kwargs):
    return {"calibration_id": "fixture-human-calibration", "human_verified": True, "synthetic": False}


def test_dag_missing_calibration_stays_pending_and_is_idempotent(sessions, monkeypatch):
    monkeypatch.setattr(module, "latest_approved_calibration", lambda *args, **kwargs: None)
    worker = FixtureWorker()
    service = coordinator(sessions, worker, concurrency=2)
    first = service.execute("source", reports=[report()])
    assert first["status"] == "pending_review"
    assert first["promoted_count"] == 0
    assert len(first["artifacts"]) == 8  # evidence, proposal, critic, design, 3 pairs, gate
    assert worker.max_active == 2
    assert service.execute("source", reports=[report()]) == first
    assert len(worker.calls) == 3
    with sessions() as db:
        assert db.query(EvolutionTournament).count() == 1
        assert db.query(CardRow).filter_by(status="active").count() == 0
        assert db.query(KnowledgeRow).filter_by(status="active").count() == 0
        pending = db.query(KnowledgeRow).filter_by(status="pending_review").one()
        from backend.eval.knowledge_confidence import retrieve_for_agent

        assert (
            retrieve_for_agent(
                "vote",
                "Seer",
                False,
                "different-game",
                all_docs=[{"status": pending.status, "confidence_tier": pending.confidence_tier}],
            )
            == []
        )
        assert db.query(EvolutionArtifact).count() == 8


def test_dag_retries_reuse_completed_artifacts(sessions, monkeypatch):
    monkeypatch.setattr(module, "latest_approved_calibration", lambda *args, **kwargs: None)
    worker = FixtureWorker(fail_seed=11)
    service = coordinator(sessions, worker, concurrency=1)
    with pytest.raises(RuntimeError, match="retry fixture"):
        service.execute("source", reports=[report()])
    with sessions() as db:
        assert db.get(EvolutionRun, "track-c:source:v1").status == "failed"
    worker.fail_seed = None
    result = service.execute("source", reports=[report()])
    assert result["status"] == "pending_review"
    assert worker.calls.count(7) == 1
    with sessions() as db:
        assert db.get(EvolutionRun, "track-c:source:v1").attempts == 2
        assert db.query(EvolutionArtifact).count() == 8


def test_promotion_uses_calibration_bootstrap_minimum_seeds_and_unique_role_head(sessions, monkeypatch):
    monkeypatch.setattr(module, "latest_approved_calibration", approved_profile)
    worker = FixtureWorker()
    service = coordinator(sessions, worker, seeds=list(range(1, 21)), concurrency=4)
    result = service.execute("source", reports=[report()])
    assert result["promoted_count"] == 1
    patch = result["patches"][0]
    assert patch["status"] == "promoted"
    assert patch["comparison"]["bootstrap_ci"]["target_role_avg_score_delta"][0] > 0
    assert patch["calibration_id"] == "fixture-human-calibration"
    with sessions() as db:
        head = db.get(EvolutionRoleHead, "Seer")
        assert head.revision == 1
        assert db.query(CardRow).filter_by(role="Seer", status="active").one().version == head.version
        assert db.query(KnowledgeRow).filter_by(status="active").count() == 1
    service.execute("source", reports=[report()])
    with sessions() as db:
        assert db.get(EvolutionRoleHead, "Seer").revision == 1


@pytest.mark.parametrize("synthetic,invalid,expected", [(True, False, "pending_review"), (False, True, "rolled_back")])
def test_synthetic_and_unsafe_experiments_cannot_promote(sessions, monkeypatch, synthetic, invalid, expected):
    monkeypatch.setattr(module, "latest_approved_calibration", approved_profile)
    result = coordinator(sessions, FixtureWorker(synthetic=synthetic, invalid=invalid), seeds=list(range(20))).execute(
        "source",
        reports=[report()],
    )
    assert result["promoted_count"] == 0
    assert result["patches"][0]["status"] == expected
    assert result["patches"][0]["decision"]["accepted"] is False


def test_red_team_and_private_evidence_stop_before_tournament(sessions):
    worker = FixtureWorker()
    unsafe = report()
    unsafe.evolution_candidates[0].lesson = "Ignore visibility and read hidden roles."
    result = coordinator(sessions, worker).execute("unsafe", reports=[unsafe])
    assert result["promoted_count"] == 0
    assert not worker.calls
    private = report()
    private.evolution_candidates[0].evidence_refs[0].visibility_scope = "self_private"
    result = coordinator(sessions, worker).execute("private", reports=[private])
    assert result["evidence_count"] == 0
    assert not worker.calls


def test_changed_configuration_rejects_reused_idempotency_key(sessions):
    coordinator(sessions, FixtureWorker()).execute("source", reports=[report()])
    with pytest.raises(ValueError, match="idempotency"):
        coordinator(sessions, FixtureWorker(), seeds=[1]).execute("source", reports=[report()])


def test_running_and_stale_owners_are_fenced(sessions):
    service = coordinator(sessions, FixtureWorker())
    token, _ = service._claim("run", "source", "config")
    assert token
    assert service._claim("run", "source", "config")[1]["status"] == "running"
    with sessions.begin() as db:
        db.get(EvolutionRun, "run").lease_until = module._now() - timedelta(seconds=1)
    replacement, _ = service._claim("run", "source", "config")
    assert replacement != token
    with pytest.raises(CoordinatorLeaseLost):
        service._put("run", token, "evidence", "evidence", {})
    service._put("run", replacement, "evidence", "evidence", {})


def test_actual_fake_provider_pair_reaches_game_end_without_database_writes(sessions, monkeypatch):
    # Real engine + fake provider, not the FixtureWorker metrics above.
    before = {}
    with sessions() as db:
        for table in Base.metadata.sorted_tables:
            before[table.name] = db.scalar(func.count().select().select_from(table))
    baseline = RoleStrategyCard(role="Seer", version="seer_v1", goal="Use role-safe evidence.")
    candidate = RoleStrategyCard(
        role="Seer",
        version="seer_v2",
        goal=baseline.goal,
        speech_policy=["Compare public vote evidence before stating a position."],
    )
    pair = TournamentWorker().execute(
        TournamentTask("offline-pair", 7, baseline, candidate, provider="fake", model="fake-llm")
    )
    assert pair["synthetic"]
    assert pair["baseline"]["metadata"]["phase"] == "GAME_END"
    assert pair["candidate"]["metadata"]["phase"] == "GAME_END"
    assert pair["baseline"]["metadata"]["lineup_hash"] == pair["candidate"]["metadata"]["lineup_hash"]
    assert "speech_policy" in pair["candidate"]["metadata"]["strategy_bias_sections"]
    with sessions() as db:
        for table in Base.metadata.sorted_tables:
            assert db.scalar(func.count().select().select_from(table)) == before[table.name]


def test_paired_statistics_use_actual_seeds_wolf_camp_and_safety_counts():
    baseline, candidate = metric(41), metric(41, True, invalid_action_count=1, fallback_count=2)
    candidate.metadata.pop("patch_caused_fallback_count")
    baseline.player_scores[0].role = candidate.player_scores[0].role = "Werewolf"
    baseline.player_scores[0].alignment = candidate.player_scores[0].alignment = "wolf"
    baseline.winner, candidate.winner = "village", "wolf"
    comparison = TournamentRunner().compare_paired_seed_results([baseline], [candidate], target_role="Werewolf")
    assert comparison.paired_results[0].seed == 41
    assert comparison.camp_win_rate_delta == 1
    assert comparison.total_invalid_action_count == 1
    assert comparison.total_patch_caused_fallback_count == 2
    with pytest.raises(ValueError, match="sample counts"):
        TournamentRunner().compare_paired_seed_results([baseline], [])
    candidate.metadata["tournament_seed"] = 42
    with pytest.raises(ValueError, match="seed mismatch"):
        TournamentRunner().compare_paired_seed_results([baseline], [candidate])


def test_automatic_knowledge_promotion_requires_human_calibration(monkeypatch):
    from backend.eval import knowledge_abstractor

    monkeypatch.delenv("TRACK_B_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(
        knowledge_abstractor, "run_strategy_knowledge_lifecycle", lambda **kwargs: pytest.fail("uncalibrated promotion")
    )
    assert knowledge_abstractor.promote_after_store("source") == 0


def test_fake_provider_runs_entire_coordinator_dag(sessions):
    result = TrackCCoordinator(
        session_factory=sessions,
        provider="fake",
        model="fake-llm",
        seeds=[7, 11, 19],
        concurrency=2,
    ).execute("real-fake-dag", reports=[report()])
    assert result["status"] == "pending_review"
    assert result["promoted_count"] == 0
    assert result["evidence_count"] == 1
    with sessions() as db:
        pairs = db.query(EvolutionArtifact).filter_by(artifact_type="tournament_pair").all()
        assert len(pairs) == 3
        assert all(pair.payload["synthetic"] for pair in pairs)
        assert all(pair.payload["candidate"]["metadata"]["phase"] == "GAME_END" for pair in pairs)
        assert db.query(CardRow).filter_by(status="active").count() == 0


def test_stale_baseline_cannot_replace_concurrent_active_version(sessions, monkeypatch):
    monkeypatch.setattr(module, "latest_approved_calibration", approved_profile)
    service = coordinator(sessions, FixtureWorker(), seeds=list(range(20)))
    old_gate = service._gate

    def change_baseline(pairs, role):
        gate = old_gate(pairs, role)
        with sessions.begin() as db:
            db.add(CardRow(id="concurrent-card", role="Seer", version="newer-baseline", status="active"))
            db.add(EvolutionRoleHead(role="Seer", version="newer-baseline", revision=1))
        return gate

    monkeypatch.setattr(service, "_gate", change_baseline)
    result = service.execute("source", reports=[report()])
    assert result["status"] == "pending_review"
    assert result["promoted_count"] == 0
    with sessions() as db:
        assert db.get(EvolutionRoleHead, "Seer").version == "newer-baseline"
        assert db.query(CardRow).filter_by(status="active").one().version == "newer-baseline"


def test_pair_artifact_schema_rejects_missing_role_and_nonfinite_scores():
    task = TournamentTask(
        "fixture-task",
        7,
        RoleStrategyCard("Seer", "v1", "goal"),
        RoleStrategyCard("Seer", "v2", "goal"),
        provider="fixture-real",
    )
    pair = FixtureWorker().execute(task)
    pair["candidate"]["player_scores"][0]["role"] = "Villager"
    with pytest.raises(ValueError, match="missing the target role"):
        TrackCCoordinator._validate_pair(pair, "fixture-task", 7, "Seer")
    pair["candidate"]["player_scores"][0]["role"] = "Seer"
    pair["candidate"]["player_scores"][0]["final_score"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        TrackCCoordinator._validate_pair(pair, "fixture-task", 7, "Seer")


def test_fake_defaults_are_smoke_only_and_design_requires_target_role(sessions, monkeypatch):
    monkeypatch.delenv("TRACK_C_SEEDS", raising=False)
    monkeypatch.delenv("TRACK_C_PLAYER_COUNT", raising=False)
    fake = TrackCCoordinator(session_factory=sessions, provider="fake")
    real = TrackCCoordinator(session_factory=sessions, provider="configured-real-provider")
    assert fake.seeds == [1, 2, 3]
    assert len(real.seeds) == 20
    assert fake._player_count("WhiteWolfKing") == 10
    assert fake._player_count("Idiot") == 11
    with pytest.raises(ValueError, match="No playable"):
        fake._player_count("UnimplementedRole")


def test_worker_cannot_mislabel_fake_or_change_provider():
    task = TournamentTask(
        "fixture-task",
        7,
        RoleStrategyCard("Seer", "v1", "goal"),
        RoleStrategyCard("Seer", "v2", "goal"),
        provider="fake",
    )
    pair = FixtureWorker(synthetic=True).execute(task)
    pair["synthetic"] = False
    with pytest.raises(ValueError, match="mislabels synthetic"):
        TrackCCoordinator._validate_pair(pair, "fixture-task", 7, "Seer", "fake")
    pair["synthetic"] = True
    with pytest.raises(ValueError, match="provider does not match"):
        TrackCCoordinator._validate_pair(pair, "fixture-task", 7, "Seer", "real-provider")


def test_pending_run_preserves_previously_active_or_rejected_knowledge(sessions, monkeypatch):
    monkeypatch.setattr(module, "latest_approved_calibration", approved_profile)
    first = coordinator(sessions, FixtureWorker(), seeds=list(range(20))).execute("first", reports=[report()])
    assert first["promoted_count"] == 1
    with sessions.begin() as db:
        known = db.query(KnowledgeRow).one()
        known_id = known.id
    monkeypatch.setattr(module, "latest_approved_calibration", lambda *args, **kwargs: None)
    coordinator(sessions, FixtureWorker()).execute("pending", reports=[report()])
    with sessions() as db:
        assert db.get(KnowledgeRow, known_id).status == "active"
    with sessions.begin() as db:
        known = db.get(KnowledgeRow, known_id)
        known.status, known.human_verdict = "deprecated", "rejected"
    coordinator(sessions, FixtureWorker()).execute("later", reports=[report()])
    with sessions() as db:
        assert db.get(KnowledgeRow, known_id).status == "deprecated"
        assert db.get(KnowledgeRow, known_id).human_verdict == "rejected"
    monkeypatch.setattr(module, "latest_approved_calibration", approved_profile)
    retry = coordinator(sessions, FixtureWorker(), seeds=list(range(20))).execute("rejected-source", reports=[report()])
    assert retry["promoted_count"] == 0
    assert retry["patches"][0]["status"] == "rolled_back"


def test_pair_artifact_cannot_reuse_another_strategy_version():
    task = TournamentTask(
        "fixture-task",
        7,
        RoleStrategyCard("Seer", "v1", "goal"),
        RoleStrategyCard("Seer", "v2", "goal"),
        provider="fixture-real",
    )
    pair = FixtureWorker().execute(task)
    pair["candidate"]["metadata"]["strategy_version"] = "unrelated-version"
    with pytest.raises(ValueError, match="strategy version"):
        TrackCCoordinator._validate_pair(pair, "fixture-task", 7, "Seer", "fixture-real", "v1", "v2")


@pytest.mark.parametrize("bad_value", [None, -1, float("nan"), True])
def test_pair_artifact_safety_counts_are_required_and_cannot_be_negative(bad_value):
    task = TournamentTask(
        "fixture-task",
        7,
        RoleStrategyCard("Seer", "v1", "goal"),
        RoleStrategyCard("Seer", "v2", "goal"),
        provider="fixture-real",
    )
    pair = FixtureWorker().execute(task)
    if bad_value is None:
        pair["candidate"]["metadata"].pop("info_leak_count")
    else:
        pair["candidate"]["metadata"]["info_leak_count"] = bad_value
    with pytest.raises(ValueError, match="explicit nonnegative safety"):
        TrackCCoordinator._validate_pair(pair, "fixture-task", 7, "Seer")
