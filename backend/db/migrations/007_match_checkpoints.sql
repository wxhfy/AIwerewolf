ALTER TABLE match_jobs ADD COLUMN IF NOT EXISTS checkpoint_seq INTEGER;
ALTER TABLE agent_decisions ADD COLUMN IF NOT EXISTS request_id VARCHAR;
CREATE INDEX IF NOT EXISTS ix_decisions_request_id ON agent_decisions (request_id);

CREATE TABLE IF NOT EXISTS match_checkpoints (
    id VARCHAR PRIMARY KEY,
    game_id VARCHAR NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
    job_id VARCHAR REFERENCES match_jobs(id) ON DELETE SET NULL,
    seq INTEGER NOT NULL,
    day INTEGER NOT NULL DEFAULT 0,
    phase VARCHAR NOT NULL DEFAULT '',
    status VARCHAR NOT NULL DEFAULT 'running',
    truth_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    public_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_match_checkpoints_game_seq
    ON match_checkpoints (game_id, seq);
