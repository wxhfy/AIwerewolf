CREATE TABLE IF NOT EXISTS match_commands (
    id VARCHAR PRIMARY KEY,
    match_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    command_type VARCHAR NOT NULL,
    actor_id VARCHAR NOT NULL DEFAULT 'anonymous',
    expected_seq INTEGER,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR NOT NULL DEFAULT 'accepted',
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_match_commands_match_created ON match_commands (match_id, created_at);
CREATE INDEX IF NOT EXISTS ix_match_commands_status ON match_commands (status);

CREATE TABLE IF NOT EXISTS agent_decision_jobs (
    id VARCHAR PRIMARY KEY,
    request_id VARCHAR NOT NULL UNIQUE,
    match_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_id VARCHAR NOT NULL,
    action_type VARCHAR NOT NULL,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload JSONB,
    status VARCHAR NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    worker_id VARCHAR,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_jobs_claim ON agent_decision_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS ix_agent_decision_jobs_match_id ON agent_decision_jobs (match_id);

CREATE TABLE IF NOT EXISTS outbox_events (
    id VARCHAR PRIMARY KEY,
    aggregate_type VARCHAR NOT NULL,
    aggregate_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_outbox_publish ON outbox_events (status, available_at, created_at);
CREATE INDEX IF NOT EXISTS ix_outbox_aggregate_id ON outbox_events (aggregate_id);
