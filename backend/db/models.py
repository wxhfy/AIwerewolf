"""SQLAlchemy models matching the ER diagram."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship

# Pick a JSON type that works on both Postgres (JSONB, indexable) and SQLite.
if os.getenv("DATABASE_URL", "").startswith(("postgres", "postgresql")):
    from sqlalchemy.dialects.postgresql import JSONB as JSON  # type: ignore
else:
    from sqlalchemy.types import JSON  # type: ignore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id = Column(String, primary_key=True, default=_uuid)
    rule_pack_id = Column(String, default="standard")
    status = Column(String, default="waiting", index=True)  # waiting, running, finished
    current_day = Column(Integer, default=0)
    current_phase = Column(String, default="SETUP")
    winner = Column(String, nullable=True, index=True)
    seed = Column(String, default="")
    created_at = Column(DateTime, default=_utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    players = relationship("Player", back_populates="game", cascade="all, delete-orphan")
    events = relationship("GameEvent", back_populates="game", cascade="all, delete-orphan")
    decisions = relationship("AgentDecision", back_populates="game", cascade="all, delete-orphan")
    snapshots = relationship("GameSnapshot", back_populates="game", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="game", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (
        # History listing: ORDER BY created_at DESC LIMIT N (api/history)
        Index("ix_games_created_at_desc", created_at.desc()),
        # Leaderboard / win-rate per rule pack: WHERE status='finished' AND rule_pack_id=?
        Index("ix_games_status_rulepack", "status", "rule_pack_id"),
    )


class Player(Base):
    __tablename__ = "players"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    seat_no = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    is_ai = Column(Boolean, default=True)
    agent_type = Column(String, default="llm")
    model_name = Column(String, default="")
    prompt_version = Column(String, default="v1")
    is_alive = Column(Boolean, default=True)
    death_day = Column(Integer, nullable=True)
    death_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="players")

    __table_args__ = (
        # Roster lookup by seat (frontend renders players grid)
        Index("ix_players_game_seat", "game_id", "seat_no"),
        # Aggregate role win-rate / KPI per (model, role) — used by leaderboard
        Index("ix_players_model_role", "model_name", "role"),
    )


class GameEvent(Base):
    __tablename__ = "game_events"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    seq = Column(Integer, default=0, index=True)  # monotonic ordering inside one game
    ts = Column(Float, default=0.0)  # engine-side timestamp (time()) for replay ordering
    day = Column(Integer, default=0)
    phase = Column(String, default="")
    event_type = Column(String, nullable=False)
    actor_id = Column(String, ForeignKey("players.id"), nullable=True)
    target_id = Column(String, nullable=True)
    visibility = Column(String, default="public")  # public, private
    content = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="events")

    __table_args__ = (
        # Replay: pull every event of one game in sequence order
        Index("ix_events_game_seq", "game_id", "seq"),
        # Filter "all votes / kills / chat in one game"
        Index("ix_events_game_type", "game_id", "event_type"),
        # Phase-level slicing (used by daily-summary builder)
        Index("ix_events_game_day_phase", "game_id", "day", "phase"),
    )


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    player_id = Column(String, ForeignKey("players.id"), nullable=False, index=True)
    day = Column(Integer, default=0)
    phase = Column(String, default="")
    observation = Column(JSON, default=dict)
    legal_actions = Column(JSON, default=list)
    prompt_version = Column(String, default="v1")
    raw_output = Column(Text, default="")
    parsed_action = Column(JSON, default=dict)
    is_valid = Column(Boolean, default=True)
    error_type = Column(String, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="decisions")

    __table_args__ = (
        # Per-player decision timeline within a game (review tooling)
        Index("ix_decisions_game_player_day", "game_id", "player_id", "day"),
        # Failure analytics: WHERE is_valid=false GROUP BY error_type
        Index("ix_decisions_invalid", "is_valid", "error_type"),
    )


class GameSnapshot(Base):
    __tablename__ = "game_snapshots"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    day = Column(Integer, default=0)
    phase = Column(String, default="")
    truth_state = Column(JSON, default=dict)  # full state (moderator view)
    public_state = Column(JSON, default=dict)  # public-visible state
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="snapshots")

    __table_args__ = (
        # Replay panel: jump to a (day, phase) snapshot in one game
        Index("ix_snapshots_game_day_phase", "game_id", "day", "phase"),
    )


class Vote(Base):
    __tablename__ = "votes"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    day = Column(Integer, default=0)
    voter_id = Column(String, ForeignKey("players.id"), nullable=False, index=True)
    target_id = Column(String, nullable=True)
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="votes")

    __table_args__ = (
        # Daily tally / herd-vote detection
        Index("ix_votes_game_day", "game_id", "day"),
    )


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    player_id = Column(String, nullable=True)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, default=0.0)
    comment = Column(String, default="")
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="evaluations")

    __table_args__ = (
        # Slice metric across all games for leaderboard math
        Index("ix_eval_metric_player", "metric_name", "player_id"),
    )


# ---------------------------------------------------------------------------
# Tables reserved for advanced tracks (B: eval+replay, C: self-evolution)
# ---------------------------------------------------------------------------


class AgentVersion(Base):
    """Track different agent configurations / prompt versions used in tournaments.

    Reserved for Track C (self-evolution) — every iteration of an agent
    (prompt rev, model swap, strategy tweak) gets a row here so we can pit
    versions against each other and roll back.
    """

    __tablename__ = "agent_versions"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)              # e.g. "wolf-aggressive-v2"
    agent_type = Column(String, default="llm")        # llm / heuristic / human
    model_name = Column(String, default="")            # e.g. doubao-seed-2.0-pro
    prompt_version = Column(String, default="v1")
    config = Column(JSON, default=dict)                # full hyper-params snapshot
    parent_version_id = Column(String, ForeignKey("agent_versions.id"), nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)


class LeaderboardEntry(Base):
    """Aggregated results per (agent_version, role) for the leaderboard.

    Reserved for Track B (eval + leaderboard). One row per (agent_version_id,
    role) summarising wins / losses / kpi metrics across the tournament.
    """

    __tablename__ = "leaderboard_entries"

    id = Column(String, primary_key=True, default=_uuid)
    agent_version_id = Column(String, ForeignKey("agent_versions.id"), nullable=True, index=True)
    name = Column(String, nullable=False, index=True)  # e.g. "doubao-pro+wolf-v3"
    role = Column(String, default="ALL")
    games_played = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    kpi_speech_quality = Column(Float, default=0.0)     # 发言质量
    kpi_vote_accuracy = Column(Float, default=0.0)      # 投票准确率
    kpi_skill_efficiency = Column(Float, default=0.0)   # 技能使用效率
    kpi_survival_value = Column(Float, default=0.0)     # 存活价值
    extra = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class ReviewReport(Base):
    """Structured post-game review / replay report (Track B).

    Generated by a reviewer agent after each game; surfaces critical mistakes,
    counterfactuals and improvement suggestions. Indexed by game so the
    frontend replay UI can fetch them on demand.
    """

    __tablename__ = "review_reports"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    player_id = Column(String, nullable=True)
    severity = Column(String, default="info")          # info / warn / critical
    day = Column(Integer, default=0)
    phase = Column(String, default="")
    title = Column(String, default="")
    summary = Column(Text, default="")
    counterfactual = Column(Text, default="")
    suggestion = Column(Text, default="")
    metrics = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class PublishedReview(Base):
    """Full Track B review artifact with validation + publish status."""

    __tablename__ = "published_reviews"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, unique=True, index=True)
    status = Column(String, default="draft", index=True)  # draft / approved / needs_revision / rejected
    view_scope = Column(String, default="moderator_view")
    grade = Column(String, default="needs_revision")
    score = Column(Float, default=0.0)
    publish_allowed = Column(Boolean, default=False)
    report_json = Column(JSON, default=dict)
    markdown = Column(Text, default="")
    validation_result = Column(JSON, default=dict)
    replay_bundle = Column(JSON, default=dict)
    speech_acts = Column(JSON, default=list)
    suspicion_matrix = Column(JSON, default=list)
    repair_history = Column(JSON, default=list)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    published_at = Column(DateTime, nullable=True)


class EvolutionRound(Base):
    """One iteration of the self-evolution loop (Track C).

    Persists "before / after" agent versions, the batch of test games, win-rate
    delta, and the human-readable change log so the evolution chain can be
    audited and rolled back to any prior round.
    """

    __tablename__ = "evolution_rounds"

    id = Column(String, primary_key=True, default=_uuid)
    round_no = Column(Integer, nullable=False, index=True)
    baseline_version_id = Column(String, ForeignKey("agent_versions.id"), nullable=True)
    challenger_version_id = Column(String, ForeignKey("agent_versions.id"), nullable=True)
    games_per_round = Column(Integer, default=20)
    baseline_wins = Column(Integer, default=0)
    challenger_wins = Column(Integer, default=0)
    delta_win_rate = Column(Float, default=0.0)
    accepted = Column(Boolean, default=False)
    change_log = Column(Text, default="")
    started_at = Column(DateTime, default=_utcnow)
    finished_at = Column(DateTime, nullable=True)


class Persona(Base):
    """Persistent persona library — sampled per game to populate AI players.

    Fields mirror wolfcha's Persona interface so any wolfcha-authored persona
    can be ingested as-is. New personas can be added with seed_personas() at
    init time or via Track B/C tools later.
    """

    __tablename__ = "personas"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, unique=True, index=True)
    mbti = Column(String, default="")
    gender = Column(String, default="")
    age = Column(Integer, default=0)
    basic_info = Column(Text, default="")
    style_label = Column(String, default="")
    voice_rules = Column(JSON, default=list)
    relationships = Column(JSON, default=list)
    vocabulary_style = Column(String, default="")
    speech_length_habit = Column(String, default="")
    reasoning_style = Column(String, default="")
    social_habit = Column(String, default="")
    humor_style = Column(String, default="")
    pressure_style = Column(String, default="")
    uncertainty_style = Column(String, default="")
    wolf_deception_style = Column(String, default="")
    mistake_pattern = Column(String, default="")
    logic_style = Column(String, default="")
    trigger_topics = Column(JSON, default=list)
    werewolf_experience = Column(String, default="")
    system_prompt = Column(Text, default="")  # ready-to-use system prompt
    is_active = Column(Boolean, default=True)
    source = Column(String, default="wolfcha")  # provenance tag
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
