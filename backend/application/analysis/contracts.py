from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import Field


class AnalysisJobView(BaseModel):
    status: str = "not_scheduled"
    attempts: int = 0
    max_attempts: int = 0
    last_error: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class MatchAnalysisResponse(BaseModel):
    match_id: str
    match_status: str
    job: AnalysisJobView
    decision_count: int = 0
    evaluated_decision_count: int = 0
    evaluation_coverage: float = 0.0
    average_score: float | None = None
    highlight_count: int = 0
    mistake_count: int = 0
    review_status: str | None = None
    strategy_counts: dict[str, int] = Field(default_factory=dict)


class DecisionTraceItem(BaseModel):
    id: str
    player_id: str
    day: int
    phase: str
    action_type: str
    is_valid: bool
    error_type: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    model_name: str | None = None
    provider: str | None = None
    created_at: str | None = None


class DecisionEvaluationItem(BaseModel):
    id: str
    decision_id: str
    player_id: str
    day: int
    phase: str
    action_type: str
    role: str
    correctness: float
    reasoning_quality: float
    timeliness: float
    impact: float
    overall_score: float
    scoring_tier: str
    evidence: list[str] = Field(default_factory=list)
    alternative: str = ""
    is_highlight: bool
    is_mistake: bool
    evaluator_version: str
    evaluator_model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyKnowledgeItem(BaseModel):
    id: str
    doc_type: str
    role: str
    phase: str
    status: str
    maturity: str
    situation_pattern: str
    recommended_action: str
    rationale: str
    quality_score: float
    confidence: float
    confidence_tier: str
    source_game_id: str | None = None
    source_decision_id: str | None = None
    doc_version: str
    created_at: str | None = None


class AnalysisRetryResponse(BaseModel):
    match_id: str
    status: str
    requested_by: str
