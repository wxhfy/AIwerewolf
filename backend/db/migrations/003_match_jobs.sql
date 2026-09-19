CREATE TABLE IF NOT EXISTS rooms (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    seed INTEGER NOT NULL DEFAULT 7,
    player_count INTEGER NOT NULL DEFAULT 7,
    agent_type VARCHAR NOT NULL DEFAULT 'llm',
    human_seat INTEGER,
    rule_pack_id VARCHAR NOT NULL DEFAULT 'wolfcha-default',
    llm_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR NOT NULL DEFAULT 'idle',
    current_game_id VARCHAR,
    game_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    latest_snapshot JSONB,
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_rooms_status ON rooms (status);
CREATE INDEX IF NOT EXISTS ix_rooms_current_game_id ON rooms (current_game_id);
CREATE INDEX IF NOT EXISTS ix_rooms_updated_at ON rooms (updated_at);

CREATE TABLE IF NOT EXISTS match_jobs (
    id VARCHAR PRIMARY KEY,
    game_id VARCHAR NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
    room_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'queued',
    control_state VARCHAR NOT NULL DEFAULT 'running',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 1,
    worker_id VARCHAR,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_match_jobs_claim ON match_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS ix_match_jobs_room_status ON match_jobs (room_id, status);
CREATE INDEX IF NOT EXISTS ix_match_jobs_worker_id ON match_jobs (worker_id);
CREATE INDEX IF NOT EXISTS ix_match_jobs_lease_expires_at ON match_jobs (lease_expires_at);
