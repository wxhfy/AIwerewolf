ALTER TABLE game_snapshots
    ADD COLUMN IF NOT EXISTS seq INTEGER NOT NULL DEFAULT 0;

WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY created_at, id) AS new_seq
    FROM game_snapshots
)
UPDATE game_snapshots AS snapshot
SET seq = ranked.new_seq
FROM ranked
WHERE snapshot.id = ranked.id;

WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY seq, created_at, id) AS new_seq
    FROM game_events
)
UPDATE game_events AS event
SET seq = ranked.new_seq
FROM ranked
WHERE event.id = ranked.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_game_events_game_seq
    ON game_events (game_id, seq);

CREATE UNIQUE INDEX IF NOT EXISTS uq_game_snapshots_game_seq
    ON game_snapshots (game_id, seq);
