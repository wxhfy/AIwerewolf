CREATE TABLE IF NOT EXISTS decision_evaluations (
    id VARCHAR PRIMARY KEY,
    game_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    decision_id VARCHAR NOT NULL REFERENCES agent_decisions(id) ON DELETE CASCADE,
    player_id VARCHAR NOT NULL,
    day INTEGER NOT NULL DEFAULT 0,
    phase VARCHAR NOT NULL DEFAULT '',
    action_type VARCHAR NOT NULL DEFAULT '',
    role VARCHAR NOT NULL DEFAULT '',
    correctness DOUBLE PRECISION NOT NULL DEFAULT 0,
    reasoning_quality DOUBLE PRECISION NOT NULL DEFAULT 0,
    timeliness DOUBLE PRECISION NOT NULL DEFAULT 0,
    impact DOUBLE PRECISION NOT NULL DEFAULT 0,
    overall_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    scoring_tier VARCHAR NOT NULL DEFAULT 'deterministic',
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    alternative TEXT NOT NULL DEFAULT '',
    is_highlight BOOLEAN NOT NULL DEFAULT FALSE,
    is_mistake BOOLEAN NOT NULL DEFAULT FALSE,
    evaluator_version VARCHAR NOT NULL DEFAULT 'per-step-v1',
    evaluator_model VARCHAR,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_decision_evaluation_version UNIQUE (decision_id, evaluator_version)
);

CREATE INDEX IF NOT EXISTS ix_decision_evaluations_game_id ON decision_evaluations (game_id);
CREATE INDEX IF NOT EXISTS ix_decision_evaluations_decision_id ON decision_evaluations (decision_id);
CREATE INDEX IF NOT EXISTS ix_decision_evaluations_player_id ON decision_evaluations (player_id);
CREATE INDEX IF NOT EXISTS ix_decision_evaluations_overall_score ON decision_evaluations (overall_score);
CREATE INDEX IF NOT EXISTS ix_decision_evaluations_scoring_tier ON decision_evaluations (scoring_tier);
CREATE INDEX IF NOT EXISTS ix_decision_evaluations_game_player ON decision_evaluations (game_id, player_id);
CREATE INDEX IF NOT EXISTS ix_decision_evaluations_game_score ON decision_evaluations (game_id, overall_score);
