from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

try:
    from sqlalchemy.dialects.postgresql import JSONB
except Exception:  # pragma: no cover - optional dialect import
    JSONB = None

from backend.db import database
from backend.db import persist
from backend.db.models import AgentDecision
from backend.db.models import Base
from backend.db.models import Evaluation
from backend.db.models import Game
from backend.db.models import GameEvent
from backend.db.models import GameSnapshot
from backend.db.models import LeaderboardEntry
from backend.db.models import Player
from backend.db.models import TrackCPostGameJob
from backend.db.models import Vote
from backend.engine.models import Alignment
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player as EnginePlayer
from backend.engine.models import Role
from backend.eval import knowledge_abstractor
from backend.eval.evolution import StrategyKnowledgeDoc

if JSONB is not None:

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
        return "JSON"


def _sqlite_sessionmaker():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Game.__table__,
            Player.__table__,
            GameEvent.__table__,
            AgentDecision.__table__,
            Vote.__table__,
            GameSnapshot.__table__,
            Evaluation.__table__,
            LeaderboardEntry.__table__,
            TrackCPostGameJob.__table__,
        ],
    )
    return engine, sessionmaker(bind=engine)


@dataclass
class _FakeKnowledgeRow:
    id: str
    doc_type: str
    role: str
    quality_score: float
    status: str = "candidate"
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    updated_at: datetime | None = None
    created_at: datetime | None = None


class _FakeQuery:
    def __init__(self, rows: list[_FakeKnowledgeRow], query_number: int):
        self._rows = rows
        self._query_number = query_number

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self) -> list[_FakeKnowledgeRow]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[_FakeKnowledgeRow]):
        self._rows = rows
        self._query_count = 0
        self.committed = False
        self.rolled_back = False

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        self._query_count += 1
        return _FakeQuery(self._rows, self._query_count)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


def test_promote_after_store_does_not_auto_promote_reflections(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow("reflection-high", "reflection", "Seer", 0.99),
        _FakeKnowledgeRow("lesson-high", "per_step_lesson", "Seer", 0.91),
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    promoted = knowledge_abstractor.promote_after_store()

    by_id = {row.id: row for row in rows}
    assert promoted == 1
    assert by_id["reflection-high"].status == "candidate"
    assert by_id["lesson-high"].status == "active"
    assert session.committed


def test_promote_after_store_triggers_source_and_global_lifecycle(monkeypatch) -> None:
    calls = []

    def fake_lifecycle(**kwargs):
        calls.append(kwargs)
        return {
            "feedback_promoted": 1,
            "quality_promoted": 2,
            "cluster_promoted": 3,
        }

    monkeypatch.setattr(knowledge_abstractor, "run_strategy_knowledge_lifecycle", fake_lifecycle)

    promoted = knowledge_abstractor.promote_after_store(source_game_id="game-1")

    assert promoted == 12
    assert calls == [
        {"source_game_id": "game-1"},
        {"maintenance_batch_size": knowledge_abstractor.AUTO_MAINTENANCE_BATCH_SIZE},
    ]


def test_promote_after_store_without_source_runs_single_global_lifecycle(monkeypatch) -> None:
    calls = []

    def fake_lifecycle(**kwargs):
        calls.append(kwargs)
        return {
            "feedback_promoted": 1,
            "quality_promoted": 0,
            "cluster_promoted": 0,
        }

    monkeypatch.setattr(knowledge_abstractor, "run_strategy_knowledge_lifecycle", fake_lifecycle)

    promoted = knowledge_abstractor.promote_after_store()

    assert promoted == 1
    assert calls == [{"maintenance_batch_size": knowledge_abstractor.AUTO_MAINTENANCE_BATCH_SIZE}]


def test_lifecycle_feedback_can_promote_candidate(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow(
            "feedback-good",
            "per_step_lesson",
            "Seer",
            0.76,
            usage_count=3,
            success_count=3,
        )
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.95,
        cluster_threshold=0.75,
        feedback_min_usage=3,
        feedback_success_rate=0.70,
    )

    assert result["feedback_promoted"] == 1
    assert rows[0].status == "active"
    assert session.committed


def test_lifecycle_fake_session_accepts_maintenance_batch_size(monkeypatch) -> None:
    rows = [_FakeKnowledgeRow("quality-good", "per_step_lesson", "Seer", 0.91)]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(maintenance_batch_size=1)

    assert result["quality_promoted"] == 1
    assert rows[0].status == "active"
    assert session.committed


def test_lifecycle_feedback_promotion_still_requires_cluster_quality(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow(
            "feedback-low-quality",
            "per_step_lesson",
            "Seer",
            0.74,
            usage_count=3,
            success_count=3,
        )
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.95,
        cluster_threshold=0.75,
        feedback_min_usage=3,
        feedback_success_rate=0.70,
    )

    assert result["feedback_promoted"] == 0
    assert rows[0].status == "candidate"
    assert session.committed


def test_lifecycle_feedback_can_deprecate_harmful_candidate(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow(
            "feedback-bad",
            "per_step_lesson",
            "Seer",
            0.70,
            usage_count=5,
            success_count=1,
            failure_count=4,
        )
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.95,
        cluster_threshold=0.90,
        feedback_deprecation_min_usage=5,
        feedback_deprecation_failure_rate=0.70,
    )

    assert result["feedback_deprecated"] == 1
    assert rows[0].status == "deprecated"
    assert session.committed


def test_lifecycle_deprecates_stale_unused_candidates(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow(
            "stale-candidate",
            "per_step_lesson",
            "Guard",
            0.70,
            updated_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.95,
        cluster_threshold=0.90,
        deprecation_threshold=0.60,
        stale_days=45,
    )

    assert result["stale_deprecated"] == 1
    assert rows[0].status == "deprecated"
    assert session.committed


def test_lifecycle_prunes_excess_candidates(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    rows = [
        _FakeKnowledgeRow(f"candidate-{idx}", "per_step_lesson", "Seer", quality, updated_at=now)
        for idx, quality in enumerate([0.70, 0.69, 0.68, 0.67, 0.66], start=1)
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.95,
        cluster_threshold=0.90,
        candidate_cap_per_role_type=2,
        candidate_total_cap=20,
        deprecation_threshold=0.60,
        stale_days=365,
    )

    assert result["candidate_pruned"] == 3
    assert [row.status for row in rows].count("candidate") == 2
    assert [row.status for row in rows].count("deprecated") == 3


def test_lifecycle_active_pool_cap_demotes_lowest_quality(monkeypatch) -> None:
    rows = [
        _FakeKnowledgeRow("active-1", "per_step_lesson", "Seer", 0.90, status="active"),
        _FakeKnowledgeRow("active-2", "per_step_lesson", "Seer", 0.80, status="active"),
        _FakeKnowledgeRow("active-3", "per_step_lesson", "Seer", 0.70, status="active"),
        _FakeKnowledgeRow("active-4", "per_step_lesson", "Seer", 0.60, status="active"),
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        active_cap_per_role_type=2,
        candidate_cap_per_role_type=10,
        candidate_total_cap=20,
        deprecation_threshold=0.50,
    )

    assert result["active_demoted"] == 2
    by_id = {row.id: row for row in rows}
    assert by_id["active-1"].status == "active"
    assert by_id["active-2"].status == "active"
    assert by_id["active-3"].status == "candidate"
    assert by_id["active-4"].status == "candidate"


def test_lifecycle_dry_run_rolls_back_status_changes(monkeypatch) -> None:
    rows = [_FakeKnowledgeRow("quality-good", "per_step_lesson", "Seer", 0.91)]
    session = _FakeSession(rows)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(dry_run=True)

    assert result["quality_promoted"] == 1
    assert rows[0].status == "candidate"
    assert session.rolled_back
    assert not session.committed


def _create_minimal_strategy_knowledge_table(session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE strategy_knowledge_docs (
                id TEXT PRIMARY KEY,
                doc_type TEXT,
                role TEXT,
                quality_score FLOAT,
                status TEXT,
                usage_count INTEGER,
                success_count INTEGER,
                failure_count INTEGER,
                source_game_id TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
    )


def test_lifecycle_sql_path_updates_real_session(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    now = datetime.now(timezone.utc)
    _create_minimal_strategy_knowledge_table(session)
    session.execute(
        text(
            """
            INSERT INTO strategy_knowledge_docs (
                id, doc_type, role, quality_score, status,
                usage_count, success_count, failure_count, created_at, updated_at
            )
            VALUES
                ('feedback-good', 'per_step_lesson', 'Seer', 0.76, 'candidate', 3, 3, 0, :now, :now),
                ('feedback-low-quality', 'per_step_lesson', 'Seer', 0.74, 'candidate', 3, 3, 0, :now, :now),
                ('harmful-active', 'per_step_lesson', 'Guard', 0.70, 'active', 5, 1, 4, :now, :now)
            """
        ),
        {"now": now},
    )
    session.commit()
    monkeypatch.setattr(database, "SessionLocal", lambda: TestingSession())

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.95,
        cluster_threshold=0.75,
        feedback_min_usage=3,
        feedback_success_rate=0.70,
        feedback_deprecation_min_usage=5,
        feedback_deprecation_failure_rate=0.70,
        candidate_cap_per_role_type=20,
        candidate_total_cap=20,
        deprecation_threshold=0.60,
        stale_days=365,
    )

    verify = TestingSession()
    by_id = dict(verify.execute(text("SELECT id, status FROM strategy_knowledge_docs")).fetchall())
    verify.close()
    session.close()
    engine.dispose()

    assert result["feedback_promoted"] == 1
    assert result["feedback_deprecated"] == 1
    assert result["active_after"] == 1
    assert result["candidate_after"] == 1
    assert result["deprecated_after"] == 1
    assert by_id == {
        "feedback-good": "active",
        "feedback-low-quality": "candidate",
        "harmful-active": "deprecated",
    }


def test_lifecycle_sql_path_respects_candidate_maintenance_batch(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    now = datetime.now(timezone.utc)
    _create_minimal_strategy_knowledge_table(session)
    session.execute(
        text(
            """
            INSERT INTO strategy_knowledge_docs (
                id, doc_type, role, quality_score, status,
                usage_count, success_count, failure_count, created_at, updated_at
            )
            VALUES
                ('recent-candidate', 'per_step_lesson', 'Seer', 0.95, 'candidate', 0, 0, 0, :now, :now),
                ('older-candidate', 'per_step_lesson', 'Seer', 0.96, 'candidate', 0, 0, 0, :older, :older)
            """
        ),
        {"now": now, "older": now - timedelta(days=1)},
    )
    session.commit()
    monkeypatch.setattr(database, "SessionLocal", lambda: TestingSession())

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.90,
        cluster_threshold=0.75,
        candidate_cap_per_role_type=20,
        candidate_total_cap=20,
        deprecation_threshold=0.60,
        stale_days=365,
        maintenance_batch_size=1,
    )

    verify = TestingSession()
    by_id = dict(verify.execute(text("SELECT id, status FROM strategy_knowledge_docs")).fetchall())
    verify.close()
    session.close()
    engine.dispose()

    assert result["quality_promoted"] == 1
    assert by_id == {
        "recent-candidate": "active",
        "older-candidate": "candidate",
    }


def test_lifecycle_sql_path_can_scope_to_source_game(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    now = datetime.now(timezone.utc)
    _create_minimal_strategy_knowledge_table(session)
    session.execute(
        text(
            """
            INSERT INTO strategy_knowledge_docs (
                id, doc_type, role, quality_score, status,
                usage_count, success_count, failure_count, source_game_id, created_at, updated_at
            )
            VALUES
                ('game-scope-candidate', 'per_step_lesson', 'Seer', 0.95, 'candidate', 0, 0, 0, 'game-1', :now, :now),
                ('other-game-candidate', 'per_step_lesson', 'Seer', 0.96, 'candidate', 0, 0, 0, 'game-2', :now, :now)
            """
        ),
        {"now": now},
    )
    session.commit()
    monkeypatch.setattr(database, "SessionLocal", lambda: TestingSession())

    result = knowledge_abstractor.run_strategy_knowledge_lifecycle(
        quality_threshold=0.90,
        cluster_threshold=0.75,
        candidate_cap_per_role_type=20,
        candidate_total_cap=20,
        deprecation_threshold=0.60,
        stale_days=365,
        source_game_id="game-1",
    )

    verify = TestingSession()
    by_id = dict(verify.execute(text("SELECT id, status FROM strategy_knowledge_docs")).fetchall())
    verify.close()
    session.close()
    engine.dispose()

    assert result["quality_promoted"] == 1
    assert by_id == {
        "game-scope-candidate": "active",
        "other-game-candidate": "candidate",
    }


class _UpsertQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._session.row


class _UpsertSession:
    def __init__(self, row=None):
        self.row = row
        self.added = []

    def query(self, *_args, **_kwargs):
        return _UpsertQuery(self)

    def add(self, row):
        self.row = row
        self.added.append(row)


def _strategy_doc(doc_id: str, report_id: str, item_id: str, event_id: str) -> StrategyKnowledgeDoc:
    return StrategyKnowledgeDoc(
        doc_id=doc_id,
        doc_type="per_step_lesson",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="公开票型压力下的预言家发言",
        trigger_conditions=["公开票型压力"],
        recommended_action="白天基于公开票型明确归票。",
        avoid_action=None,
        rationale="复盘证据显示公开归票提高协同。",
        evidence_summary="approved evidence",
        source_report_ids=[report_id],
        source_item_ids=[item_id],
        source_event_ids=[event_id],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=0.8,
        confidence=0.8,
        status="candidate",
        source_game_id=report_id,
        source_decision_id=item_id,
    )


def test_upsert_strategy_knowledge_preserves_report_item_event_ids() -> None:
    session = _UpsertSession()

    persist._upsert_strategy_knowledge_rows(session, [_strategy_doc("doc-1", "game-1", "item-1", "event-1")])
    persist._upsert_strategy_knowledge_rows(session, [_strategy_doc("doc-2", "game-2", "item-2", "event-2")])

    assert sorted(session.row.source_report_ids) == ["game-1", "game-2"]
    assert sorted(session.row.source_item_ids) == ["item-1", "item-2"]
    assert sorted(session.row.source_event_ids) == ["event-1", "event-2"]
    assert session.row.source_game_id == "game-1"
    assert session.row.source_decision_id == "item-1"


class _UsageQuery:
    def __init__(self, doc):
        self._doc = doc

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._doc


class _UsageSession:
    def __init__(self, doc):
        self.doc = doc
        self.rows = []
        self.committed = False

    def add(self, row):
        row.id = "usage-row"
        self.rows.append(row)

    def query(self, *_args, **_kwargs):
        return _UsageQuery(self.doc)

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_record_knowledge_usage_retrieval_trace_is_neutral(monkeypatch) -> None:
    doc = type(
        "Doc",
        (),
        {
            "id": "doc-1",
            "usage_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "status": "active",
            "quality_score": 0.9,
        },
    )()
    session = _UsageSession(doc)
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: session)

    result = persist.record_knowledge_usage(
        {
            "game_id": "game-1",
            "player_id": "player-1",
            "knowledge_doc_id": "doc-1",
            "retrieved": True,
            "used": False,
            "metadata": {"feedback_stage": "retrieval_trace"},
        }
    )

    assert result["knowledge_doc_id"] == "doc-1"
    assert doc.usage_count == 0
    assert doc.success_count == 0
    assert doc.failure_count == 0
    assert doc.status == "active"
    assert session.committed


def test_save_game_end_creates_track_c_post_game_job(monkeypatch) -> None:
    engine, TestingSession = _sqlite_sessionmaker()
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: TestingSession())

    state = GameState(
        id="job-game-1",
        phase=Phase.GAME_END,
        day=2,
        players=[
            EnginePlayer(id="P1", seat=1, name="狼人", role=Role.WEREWOLF, alignment=Alignment.WOLF),
            EnginePlayer(id="P2", seat=2, name="预言家", role=Role.SEER, alignment=Alignment.VILLAGE),
        ],
        winner=Alignment.VILLAGE,
    )
    persist.save_game_start(state)
    persist.save_game_end(state)

    session = TestingSession()
    job = session.query(TrackCPostGameJob).filter(TrackCPostGameJob.game_id == "job-game-1").one()
    session.close()
    engine.dispose()

    assert job.status == "pending"
    assert job.attempts == 0


def test_track_c_post_game_job_claim_complete_and_recoverable(monkeypatch) -> None:
    engine, TestingSession = _sqlite_sessionmaker()
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: TestingSession())

    session = TestingSession()
    session.add(Game(id="job-game-2", status="finished", current_day=3, current_phase="GAME_END", winner="wolf"))
    session.commit()
    session.close()

    created = persist.ensure_track_c_post_game_job("job-game-2", source="test")
    claimed = persist.claim_track_c_post_game_job("job-game-2")
    recoverable_running = persist.list_recoverable_track_c_post_game_jobs(limit=10, stale_after_seconds=900)
    completed = persist.complete_track_c_post_game_job("job-game-2", lessons_stored=4, promoted_count=2)
    recoverable_completed = persist.list_recoverable_track_c_post_game_jobs(limit=10, stale_after_seconds=900)
    engine.dispose()

    assert created["status"] == "pending"
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert recoverable_running == []
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["lessons_stored"] == 4
    assert completed["promoted_count"] == 2
    assert recoverable_completed == []


def test_track_c_post_game_job_stale_running_is_recoverable(monkeypatch) -> None:
    engine, TestingSession = _sqlite_sessionmaker()
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: TestingSession())

    old = datetime.now(timezone.utc) - timedelta(hours=2)
    session = TestingSession()
    session.add(Game(id="job-game-3", status="finished", current_day=3, current_phase="GAME_END", winner="wolf"))
    session.add(
        TrackCPostGameJob(
            game_id="job-game-3",
            status="running",
            attempts=1,
            max_attempts=3,
            locked_at=old,
            updated_at=old,
        )
    )
    session.commit()
    session.close()

    recoverable = persist.list_recoverable_track_c_post_game_jobs(limit=10, stale_after_seconds=60)
    claimed = persist.claim_track_c_post_game_job("job-game-3", stale_after_seconds=60)
    engine.dispose()

    assert [job["game_id"] for job in recoverable] == ["job-game-3"]
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 2


def test_build_post_game_state_from_db_reconstructs_minimal_truth(monkeypatch) -> None:
    engine, TestingSession = _sqlite_sessionmaker()
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: TestingSession())

    session = TestingSession()
    session.add(Game(id="job-game-4", status="finished", current_day=4, current_phase="GAME_END", winner="village"))
    session.add_all(
        [
            Player(id="P1", game_id="job-game-4", seat_no=1, name="白狼王", role="WhiteWolfKing", is_alive=False),
            Player(id="P2", game_id="job-game-4", seat_no=2, name="女巫", role="Witch", is_alive=True),
        ]
    )
    session.commit()
    session.close()

    state = persist.build_post_game_state_from_db("job-game-4")
    engine.dispose()

    assert state is not None
    assert state.id == "job-game-4"
    assert state.phase == Phase.GAME_END
    assert state.winner == Alignment.VILLAGE
    assert [player.id for player in state.players] == ["P1", "P2"]
    assert state.players[0].role == Role.WHITE_WOLF_KING
    assert state.players[0].alignment == Alignment.WOLF
    assert state.players[1].alignment == Alignment.VILLAGE


def test_startup_recovery_runs_pending_track_c_job(monkeypatch) -> None:
    from backend import app as app_module

    engine, TestingSession = _sqlite_sessionmaker()
    monkeypatch.setattr(persist, "init_db", lambda: None)
    monkeypatch.setattr(persist, "SessionLocal", lambda: TestingSession())
    monkeypatch.setattr("backend.app.init_db", lambda: None)

    session = TestingSession()
    session.add(Game(id="job-game-5", status="finished", current_day=1, current_phase="GAME_END", winner="village"))
    session.add(Player(id="P1", game_id="job-game-5", seat_no=1, name="村民", role="Villager", is_alive=True))
    session.add(AgentDecision(game_id="job-game-5", player_id="P1", day=1, phase="DAY_SPEECH"))
    session.add(TrackCPostGameJob(game_id="job-game-5", status="pending", attempts=0, max_attempts=3))
    session.commit()
    session.close()

    calls = []

    def fake_run_post_game_scoring(state, game_id, *, return_details=False):
        calls.append((state.id, game_id, return_details))
        return {"lessons_stored": 3, "promoted_count": 1}

    monkeypatch.setattr("backend.app.run_post_game_scoring", fake_run_post_game_scoring, raising=False)
    monkeypatch.setattr("backend.eval.post_game.run_post_game_scoring", fake_run_post_game_scoring)

    recovered = app_module._recover_track_c_post_game_jobs()
    verify = TestingSession()
    job = verify.query(TrackCPostGameJob).filter(TrackCPostGameJob.game_id == "job-game-5").one()
    verify.close()
    engine.dispose()

    assert recovered == 1
    assert calls == [("job-game-5", "job-game-5", True)]
    assert job.status == "completed"
    assert job.lessons_stored == 3
    assert job.promoted_count == 1
