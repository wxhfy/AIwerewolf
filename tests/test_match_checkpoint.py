from sqlalchemy import create_engine
from sqlalchemy import inspect

from backend.application.matches.executor import build_game
from backend.application.matches.executor import restore_game_from_checkpoint
from backend.application.matches.repository import MatchJobRepository
from backend.db.database import SessionLocal
from backend.db.database import _ensure_compatibility_schema
from backend.db.models import Game
from backend.db.models import GameRoom
from backend.db.models import MatchJob
from backend.db.persist import get_match_checkpoint
from backend.db.persist import init_db
from backend.db.persist import save_game_start
from backend.db.persist import save_match_checkpoint
from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.engine.models import Phase


def test_match_checkpoint_upsert_tracks_latest_cursor() -> None:
    init_db()
    state = GameState(id="checkpoint-game", phase=Phase.DAY_START, day=1, players=[])
    save_game_start(state)

    save_match_checkpoint(
        state.id,
        job_id=None,
        seq=3,
        day=1,
        phase="DAY_START",
        truth={"seq": 3, "private": True},
        public={"seq": 3, "private": False},
        cursor={"last_event_seq": 3},
    )
    save_match_checkpoint(
        state.id,
        job_id=None,
        seq=7,
        day=2,
        phase="DAY_SPEECH",
        truth={"seq": 7},
        public={"seq": 7},
        cursor={"last_event_seq": 7, "decision_request_id": "req-7"},
    )

    checkpoint = get_match_checkpoint(state.id)

    assert checkpoint is not None
    assert checkpoint["seq"] == 7
    assert checkpoint["day"] == 2
    assert checkpoint["phase"] == "DAY_SPEECH"
    assert checkpoint["cursor"]["decision_request_id"] == "req-7"

    with SessionLocal() as db:
        assert db.query(Game).filter(Game.id == state.id).one().status == "running"


def test_game_state_round_trips_through_moderator_checkpoint() -> None:
    game = build_game(seed=17, player_count=7)
    game.state.phase = Phase.DAY_SPEECH
    game.state.day = 2
    game.state.phase_cursor = {"DAY_SPEECH": 3}
    game.state.phase_done = {1: [Phase.NIGHT_START.value], 2: []}
    game.state.events.append(
        GameEvent.create(
            day=2,
            phase=Phase.DAY_SPEECH,
            type=EventType.SYSTEM_MESSAGE,
            visibility="public",
            payload={"message": "checkpoint"},
            seq=1,
        )
    )
    snapshot = game.state.snapshot(show_private=True)
    restored_game = build_game(seed=17, player_count=7, game_id=game.state.id, players=game.state.players)

    assert restore_game_from_checkpoint(
        restored_game,
        {
            "status": "running",
            "seq": snapshot["seq"],
            "truth_state": snapshot,
            "cursor": {"decision_count": 4},
        },
    )
    assert restored_game.state.phase == Phase.DAY_SPEECH
    assert restored_game.state.day == 2
    assert restored_game.state.phase_cursor["__decision_sequence__"] == 4
    assert restored_game.state.phase_done[1] == [Phase.NIGHT_START.value]


def test_expired_lease_requeues_when_checkpoint_and_retry_budget_exist() -> None:
    init_db()
    game_id = "lease-recovery-game"
    room_id = "lease-recovery-room"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="running"))
        db.add(GameRoom(id=room_id, name="recovery"))
        db.add(
            MatchJob(
                id="lease-recovery-job",
                game_id=game_id,
                room_id=room_id,
                status="running",
                attempts=1,
                max_attempts=3,
                worker_id="dead-worker",
                checkpoint_seq=9,
            )
        )
    save_match_checkpoint(
        game_id,
        job_id="lease-recovery-job",
        seq=9,
        day=1,
        phase=Phase.DAY_SPEECH.value,
        truth={"id": game_id, "seq": 9},
        public={"id": game_id, "seq": 9},
    )

    assert MatchJobRepository().fail_expired_leases() == 1
    with SessionLocal() as db:
        row = db.query(MatchJob).filter(MatchJob.id == "lease-recovery-job").one()
        assert row.status == "queued"
        assert row.worker_id is None
        assert row.last_error.endswith("checkpoint seq=9.")


def test_enqueue_applies_retry_budget_to_prepared_job(monkeypatch) -> None:
    init_db()
    game_id = "retry-budget-game"
    room_id = "retry-budget-room"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="prepared"))
        db.add(GameRoom(id=room_id, name="retry-budget"))
        db.add(
            MatchJob(
                id="retry-budget-job",
                game_id=game_id,
                room_id=room_id,
                status="prepared",
                max_attempts=1,
                payload={"match_id": game_id},
            )
        )

    monkeypatch.setenv("MATCH_MAX_ATTEMPTS", "3")
    result = MatchJobRepository().enqueue(game_id=game_id, room_id=room_id)

    assert result["status"] == "queued"
    assert result["max_attempts"] == 3


def test_execution_failure_requeues_from_checkpoint() -> None:
    init_db()
    game_id = "execution-recovery-game"
    room_id = "execution-recovery-room"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="running"))
        db.add(GameRoom(id=room_id, name="recovery"))
        db.add(
            MatchJob(
                id="execution-recovery-job",
                game_id=game_id,
                room_id=room_id,
                status="running",
                attempts=1,
                max_attempts=2,
                worker_id="worker-1",
            )
        )
    save_match_checkpoint(
        game_id,
        job_id="execution-recovery-job",
        seq=4,
        day=1,
        phase=Phase.DAY_START.value,
        truth={"id": game_id, "seq": 4},
        public={"id": game_id, "seq": 4},
    )

    MatchJobRepository().fail("execution-recovery-job", "worker-1", "temporary model failure")
    with SessionLocal() as db:
        row = db.query(MatchJob).filter(MatchJob.id == "execution-recovery-job").one()
        assert row.status == "queued"
        assert row.worker_id is None
        assert "temporary model failure" in row.last_error
        assert "checkpoint seq=4" in row.last_error


def test_legacy_sqlite_schema_gets_recovery_columns() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE match_jobs (id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE agent_decisions (id VARCHAR PRIMARY KEY)")
        _ensure_compatibility_schema(connection)

    inspector = inspect(engine)
    job_columns = {column["name"] for column in inspector.get_columns("match_jobs")}
    decision_columns = {column["name"] for column in inspector.get_columns("agent_decisions")}
    assert "checkpoint_seq" in job_columns
    assert "request_id" in decision_columns
    assert "ix_decisions_request_id" in {index["name"] for index in inspector.get_indexes("agent_decisions")}
