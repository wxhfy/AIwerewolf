"""SQLAlchemy models matching the ER diagram."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, relationship


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
    status = Column(String, default="waiting")  # waiting, running, finished
    current_day = Column(Integer, default=0)
    current_phase = Column(String, default="SETUP")
    winner = Column(String, nullable=True)
    seed = Column(String, default="")
    created_at = Column(DateTime, default=_utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    players = relationship("Player", back_populates="game", cascade="all, delete-orphan")
    events = relationship("GameEvent", back_populates="game", cascade="all, delete-orphan")
    decisions = relationship("AgentDecision", back_populates="game", cascade="all, delete-orphan")
    snapshots = relationship("GameSnapshot", back_populates="game", cascade="all, delete-orphan")
    votes = relationship("Vote", back_populates="game", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="game", cascade="all, delete-orphan")


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


class GameEvent(Base):
    __tablename__ = "game_events"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    day = Column(Integer, default=0)
    phase = Column(String, default="")
    event_type = Column(String, nullable=False)
    actor_id = Column(String, ForeignKey("players.id"), nullable=True)
    target_id = Column(String, nullable=True)
    visibility = Column(String, default="public")  # public, private
    content = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="events")


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


class Vote(Base):
    __tablename__ = "votes"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    day = Column(Integer, default=0)
    voter_id = Column(String, ForeignKey("players.id"), nullable=False)
    target_id = Column(String, nullable=True)
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    game = relationship("Game", back_populates="votes")


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
