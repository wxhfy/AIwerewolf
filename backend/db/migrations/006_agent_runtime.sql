CREATE TABLE IF NOT EXISTS actor_memories (
    id VARCHAR PRIMARY KEY,
    game_id VARCHAR NOT NULL REFERENCES games(id),
    player_id VARCHAR NOT NULL REFERENCES players(id),
    version INTEGER NOT NULL DEFAULT 1,
    last_event_seq INTEGER NOT NULL DEFAULT 0,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_actor_memories_game_player UNIQUE (game_id, player_id)
);

CREATE INDEX IF NOT EXISTS ix_actor_memories_game_updated
    ON actor_memories (game_id, updated_at);

CREATE TABLE IF NOT EXISTS agent_harness_events (
    id VARCHAR PRIMARY KEY,
    game_id VARCHAR NOT NULL REFERENCES games(id),
    player_id VARCHAR NOT NULL REFERENCES players(id),
    request_id VARCHAR NOT NULL,
    seq INTEGER NOT NULL,
    event_type VARCHAR NOT NULL,
    step INTEGER NOT NULL DEFAULT 0,
    timestamp_ms BIGINT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_harness_events_request_seq UNIQUE (request_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_agent_harness_events_request_id
    ON agent_harness_events (request_id);
CREATE INDEX IF NOT EXISTS ix_agent_harness_events_game_player_created
    ON agent_harness_events (game_id, player_id, created_at);
