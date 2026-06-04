-- ================================================================
-- Manual Migration: Strict Mode Required Schema Changes
-- Created: 2026-06-04
-- Target: PostgreSQL
-- Context: These changes close schema gaps identified during
--          strict-mode backend verification.
-- ================================================================

-- ── 1. agent_decisions: add metadata column for tool_trace ──

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agent_decisions' AND column_name = 'metadata'
    ) THEN
        ALTER TABLE agent_decisions ADD COLUMN metadata JSONB DEFAULT '{}'::jsonb;
        COMMENT ON COLUMN agent_decisions.metadata IS
            'Extensible metadata: tool_trace, auto_injected_strategies, retrieval_used, retrieved_knowledge_ids';
    END IF;
END $$;

-- ── 2. strategy_knowledge_docs: add experiment tracking columns ──

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'strategy_knowledge_docs' AND column_name = 'experiment_id'
    ) THEN
        ALTER TABLE strategy_knowledge_docs ADD COLUMN experiment_id VARCHAR;
        COMMENT ON COLUMN strategy_knowledge_docs.experiment_id IS
            'ID of the experiment that produced this knowledge doc';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'strategy_knowledge_docs' AND column_name = 'source_game_id'
    ) THEN
        ALTER TABLE strategy_knowledge_docs ADD COLUMN source_game_id VARCHAR;
        COMMENT ON COLUMN strategy_knowledge_docs.source_game_id IS
            'ID of the game that produced this knowledge doc (denormalized from source_report_ids[0])';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'strategy_knowledge_docs' AND column_name = 'source_decision_id'
    ) THEN
        ALTER TABLE strategy_knowledge_docs ADD COLUMN source_decision_id VARCHAR;
        COMMENT ON COLUMN strategy_knowledge_docs.source_decision_id IS
            'ID of the decision that triggered this lesson';
    END IF;
END $$;

-- ── 3. experiments table ──

CREATE TABLE IF NOT EXISTS experiments (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    description TEXT,
    tiers JSONB NOT NULL DEFAULT '[]'::jsonb,
    strategy_snapshot_id VARCHAR,
    n_games_per_tier INTEGER DEFAULT 12,
    player_count INTEGER DEFAULT 7,
    model_name VARCHAR,
    prompt_version VARCHAR DEFAULT 'v1',
    agent_version VARCHAR,
    rule_variant VARCHAR DEFAULT 'standard_competition_v1',
    status VARCHAR DEFAULT 'running',
    results JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

-- ── 4. strategy_snapshots table ──

CREATE TABLE IF NOT EXISTS strategy_snapshots (
    id VARCHAR PRIMARY KEY,
    experiment_id VARCHAR,
    active_doc_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    active_count INTEGER NOT NULL DEFAULT 0,
    active_doc_ids_hash VARCHAR NOT NULL,
    quality_distribution JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS ix_snapshots_experiment ON strategy_snapshots(experiment_id);
CREATE INDEX IF NOT EXISTS ix_snapshots_hash ON strategy_snapshots(active_doc_ids_hash);

-- ── 5. Add experiment_id to games table ──

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'games' AND column_name = 'experiment_id'
    ) THEN
        ALTER TABLE games ADD COLUMN experiment_id VARCHAR;
        COMMENT ON COLUMN games.experiment_id IS
            'Experiment ID this game belongs to';
    END IF;
END $$;

-- ── 6. Add indices for common queries ──

CREATE INDEX IF NOT EXISTS ix_strategy_knowledge_experiment
    ON strategy_knowledge_docs(experiment_id)
    WHERE experiment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_strategy_knowledge_source_game
    ON strategy_knowledge_docs(source_game_id)
    WHERE source_game_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_games_experiment
    ON games(experiment_id)
    WHERE experiment_id IS NOT NULL;

-- ================================================================
-- Verification Queries
-- ================================================================

-- After migration, verify:
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name='agent_decisions' AND column_name='metadata';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name='strategy_knowledge_docs' AND column_name IN ('experiment_id','source_game_id','source_decision_id');
-- SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' AND tablename IN ('experiments','strategy_snapshots');
