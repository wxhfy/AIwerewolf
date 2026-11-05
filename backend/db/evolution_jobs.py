"""Durable coordinator state; tournament workers never write these tables."""

from sqlalchemy import JSON
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint

from backend.db.models import Base
from backend.db.models import _utcnow


class EvolutionRun(Base):
    __tablename__ = "track_c_coordinator_runs"

    id = Column(String, primary_key=True)
    game_id = Column(String, nullable=False, index=True)
    input_hash = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    stage = Column(String, nullable=False, default="evidence")
    attempts = Column(Integer, nullable=False, default=0)
    owner_token = Column(String, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=False, default="")
    result = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class EvolutionArtifact(Base):
    __tablename__ = "track_c_coordinator_artifacts"

    id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False, index=True)
    node_key = Column(String, nullable=False)
    artifact_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    __table_args__ = (UniqueConstraint("run_id", "node_key", name="uq_track_c_artifact_node"),)


class EvolutionRoleHead(Base):
    """CAS fencing point for serialized promotion of a role strategy."""

    __tablename__ = "track_c_role_heads"

    role = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
