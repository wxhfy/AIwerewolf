"""SQLAlchemy models matching the ER diagram."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from datetime import timezone

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship

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
    """Structured decision trace for every agent action.

    v2: Now includes full DecisionTrace fields (candidate_actions, visible_facts,
    confidence, prompt_hash, cost_usd) per blueprints §G2 and §G10.
    """

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

    # ---- v2 DecisionTrace fields (blueprints §G2 + §G10) ----
    candidate_actions = Column(JSON, nullable=True, comment="List of {action, score, rationale} considered")
    visible_facts = Column(JSON, nullable=True, comment="List of facts visible to agent at decision time")
    confidence = Column(Float, nullable=True, comment="Agent self-reported confidence 0.0-1.0")
    prompt_hash = Column(String, nullable=True, comment="SHA256 of the assembled prompt")
    cost_usd = Column(Float, nullable=True, comment="Estimated USD cost for this LLM call")
    model_name = Column(String, nullable=True, comment="LLM model used (e.g. doubao-seed-2.0-pro)")
    provider = Column(String, nullable=True, comment="LLM provider (e.g. doubao, deepseek)")
    decision_metadata = Column(
        "metadata", JSON, nullable=True, default=dict, comment="AgentDecision metadata dict (tool traces, strategy IDs)"
    )

    game = relationship("Game", back_populates="decisions")

    __table_args__ = (
        Index("ix_decisions_game_player_day", "game_id", "player_id", "day"),
        Index("ix_decisions_invalid", "is_valid", "error_type"),
        Index("ix_decisions_model", "model_name", "provider"),
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
    name = Column(String, nullable=False)  # e.g. "wolf-aggressive-v2"
    agent_type = Column(String, default="llm")  # llm / heuristic / human
    model_name = Column(String, default="")  # e.g. doubao-seed-2.0-pro
    prompt_version = Column(String, default="v1")
    config = Column(JSON, default=dict)  # full hyper-params snapshot
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
    kpi_speech_quality = Column(Float, default=0.0)  # 发言质量
    kpi_vote_accuracy = Column(Float, default=0.0)  # 投票准确率
    kpi_skill_efficiency = Column(Float, default=0.0)  # 技能使用效率
    kpi_survival_value = Column(Float, default=0.0)  # 存活价值
    extra = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# NOTE: This ORM table is not written by the production pipeline. Use PublishedReview instead.
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
    severity = Column(String, default="info")  # info / warn / critical
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


class StrategyKnowledgeDoc(Base):
    """Sanitized Track C strategy knowledge extracted from approved reviews.

    v2: Now carries the full L0-L4 confidence tier + access control +
    applicability metadata so the 4-filter retrieval pipeline
    (knowledge_confidence.retrieve_for_agent) can gate every retrieval.
    """

    __tablename__ = "strategy_knowledge_docs"

    id = Column(String, primary_key=True, default=_uuid)
    doc_type = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False, index=True)
    phase = Column(String, default="", index=True)
    persona_scope = Column(String, nullable=True, index=True)
    situation_pattern = Column(Text, default="")
    trigger_conditions = Column(JSON, default=list)
    recommended_action = Column(Text, default="")
    avoid_action = Column(Text, nullable=True)
    rationale = Column(Text, default="")
    evidence_summary = Column(Text, default="")
    source_report_ids = Column(JSON, default=list)
    source_item_ids = Column(JSON, default=list)
    source_event_ids = Column(JSON, default=list)
    counterfactual_ids = Column(JSON, default=list)
    expected_metric_effects = Column(JSON, default=list)
    quality_score = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    usage_count = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    status = Column(String, default="candidate", index=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # ---- L0-L4 Confidence Tier (knowledge_confidence.KnowledgeConfidence) ----
    confidence_tier = Column(
        String,
        default="L3_strategic",
        index=True,
        comment="L0_fact | L1_rule | L2_statistical | L3_strategic | L4_speculative",
    )
    judge_agreement = Column(Float, nullable=True, comment="Inter-judge agreement 0.0-1.0 (L3)")
    times_upvoted = Column(Integer, default=0)
    contradiction_count = Column(Integer, default=0)
    games_since_creation = Column(Integer, default=0)
    human_verdict = Column(String, nullable=True, comment="confirmed | rejected | revised | unreviewed")

    # ---- Access Control (knowledge_confidence.KnowledgeAccessControl) ----
    visibility_scope = Column(
        String,
        default="public",
        index=True,
        comment="public | self_private | wolf_team_private | postgame_only | global_deidentified",
    )
    allowed_roles = Column(JSON, nullable=True, comment="Roles allowed for self_private scope")
    deidentified = Column(Boolean, default=False, comment="Player IDs removed")
    contains_current_game_private_info = Column(Boolean, default=False)

    # ---- Applicability (knowledge_confidence.KnowledgeApplicability) ----
    applicability_role = Column(String, nullable=True, comment="Required role, None=any")
    applicability_phase = Column(String, nullable=True, comment="Required phase, None=any")
    min_players = Column(Integer, nullable=True)
    max_players = Column(Integer, nullable=True)
    required_public_facts = Column(JSON, default=list)
    forbidden_public_facts = Column(JSON, default=list)
    required_private_state = Column(JSON, default=list)

    __table_args__ = (
        Index("ix_strategy_knowledge_role_phase_status", "role", "phase", "status"),
        Index("ix_strategy_knowledge_tier_scope", "confidence_tier", "visibility_scope"),
    )


# NOTE: Only populated by scripts/build_strategy_graph.py, not the game pipeline.
class StrategyGraphLink(Base):
    """GraphRAG-lite edge between strategy knowledge entities."""

    __tablename__ = "strategy_graph_links"

    id = Column(String, primary_key=True, default=_uuid)
    source_id = Column(String, nullable=False, index=True)
    source_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False)
    edge_type = Column(String, nullable=False, index=True)
    weight = Column(Float, default=1.0)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)


class RoleStrategyCard(Base):
    """Versioned role-level strategy card used by retrieval-enhanced agents."""

    __tablename__ = "role_strategy_cards"

    id = Column(String, primary_key=True, default=_uuid)
    role = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    parent_version = Column(String, nullable=True)
    goal = Column(Text, default="")
    speech_policy = Column(JSON, default=list)
    vote_policy = Column(JSON, default=list)
    skill_policy = Column(JSON, default=list)
    risk_rules = Column(JSON, default=list)
    retrieval_policy = Column(JSON, default=dict)
    status = Column(String, default="active", index=True)
    created_from_patch_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (Index("ix_role_strategy_role_version", "role", "version"),)


# NOTE: ORM table has no insert path in production. Data class exists in eval/evolution.py.
class PersonaRoleAdapter(Base):
    """Versioned persona-role compensation layer."""

    __tablename__ = "persona_role_adapters"

    id = Column(String, primary_key=True, default=_uuid)
    persona_scope = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, index=True)
    compensation_rules = Column(JSON, default=list)
    risk_warnings = Column(JSON, default=list)
    style_adjustments = Column(JSON, default=list)
    status = Column(String, default="active", index=True)
    created_from_patch_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class StrategyPatch(Base):
    """Track C patch proposed by DreamJob and validated before A/B."""

    __tablename__ = "strategy_patches"

    id = Column(String, primary_key=True, default=_uuid)
    patch_type = Column(String, nullable=False, index=True)
    target_role = Column(String, nullable=True, index=True)
    target_persona_scope = Column(String, nullable=True, index=True)
    from_version = Column(String, default="v1")
    to_version = Column(String, default="")
    source_report_ids = Column(JSON, default=list)
    source_knowledge_doc_ids = Column(JSON, default=list)
    source_evidence_ids = Column(JSON, default=list)
    operations = Column(JSON, default=list)
    expected_effects = Column(JSON, default=list)
    safety_checks = Column(JSON, default=dict)
    validation_result = Column(JSON, default=dict)
    status = Column(String, default="proposed", index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class EvolutionTournament(Base):
    """A/B tournament comparison between baseline and candidate versions."""

    __tablename__ = "evolution_tournaments"

    id = Column(String, primary_key=True, default=_uuid)
    baseline_version = Column(String, nullable=False, index=True)
    candidate_version = Column(String, nullable=False, index=True)
    target_role = Column(String, nullable=True, index=True)
    seeds = Column(JSON, default=list)
    baseline_results = Column(JSON, default=list)
    candidate_results = Column(JSON, default=list)
    comparison = Column(JSON, default=dict)
    decision = Column(JSON, default=dict)
    status = Column(String, default="completed", index=True)
    created_at = Column(DateTime, default=_utcnow)


class KnowledgeUsageFeedback(Base):
    """Per-decision feedback for strategy knowledge retrieval quality."""

    __tablename__ = "knowledge_usage_feedback"

    id = Column(String, primary_key=True, default=_uuid)
    game_id = Column(String, ForeignKey("games.id"), nullable=False, index=True)
    decision_id = Column(String, nullable=True, index=True)
    player_id = Column(String, ForeignKey("players.id"), nullable=False, index=True)
    knowledge_doc_id = Column(String, ForeignKey("strategy_knowledge_docs.id"), nullable=False, index=True)
    retrieved = Column(Boolean, default=True)
    used = Column(Boolean, default=False)
    decision_outcome = Column(String, default="")
    score_delta = Column(Float, default=0.0)
    helpful = Column(Boolean, default=False)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)


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
