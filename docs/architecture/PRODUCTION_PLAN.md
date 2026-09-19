# Production Target and Delivery Plan

## Final Objective

Deliver an AI Werewolf platform that can be deployed to a production environment, sustains at least 3,000 inbound API requests per minute (50 requests per second) under the defined workload, and can scale horizontally without changing game or agent business logic.

This target covers the control plane: room queries, match commands, replay queries, and SSE connection setup. LLM throughput is a separate capacity dimension because it depends on provider quotas, latency, token volume, and the number of decisions per match.

## Required Service Boundaries

```text
Browser
  -> API service: authentication, commands, queries, idempotency
  -> SSE service: ordered durable delivery and reconnect

PostgreSQL
  -> authoritative matches, commands, events, snapshots, traces, outbox

Redis
  -> rate limits, short leases, wake-up notifications, ephemeral cache

MatchRunner workers
  -> load state, execute deterministic domain transitions, commit events

Agent workers
  -> consume decision jobs, call model providers, validate and persist results

Post-game workers
  -> review, evaluation, report generation, strategy extraction
```

API instances must be stateless. A process restart must not lose a match, change event order, or require an in-memory room object to recover.

## Capacity Contract

The initial production sizing target is:

| Dimension | Acceptance target |
|---|---|
| Inbound API traffic | 3,000 QPM sustained for 30 minutes |
| Command endpoints | p95 below 300 ms excluding queued model execution |
| Query endpoints | p95 below 200 ms for indexed common queries |
| Error rate | below 0.5% excluding intentional 4xx responses |
| SSE reconnect | resume from `Last-Event-ID` with no gaps or duplicates |
| Event durability | acknowledged domain events survive process restart |
| Command idempotency | repeated `command_id` produces one state transition |
| Availability | rolling deployment without dropping durable match progress |

The load test must model realistic endpoint ratios, payload sizes, database state, and concurrent SSE connections. A single empty health endpoint benchmark does not satisfy this target.

## Scaling Rules

- Scale API and SSE replicas horizontally behind the ingress.
- Partition match ownership with short Redis leases, but recover ownership from PostgreSQL.
- Scale MatchRunner workers by runnable-match queue depth.
- Scale Agent workers separately by provider, model, quota, and latency class.
- Apply per-user, per-match, and per-provider rate limits.
- Use PostgreSQL connection pooling and bounded worker concurrency. Do not let every SSE connection hold a database connection.
- Store ordered events with unique `(match_id, seq)` and use an outbox row in the same transaction.
- Publish only a wake-up signal through Redis; consumers always recover payloads from PostgreSQL.
- Snapshot periodically or at meaningful phase boundaries, not once for every token chunk.

## Delivery Stages

### Stage 1: Durable vertical slice

- Persist match start, ordered events, snapshots, final state, and agent traces.
- Replace the frontend AI-match SSE path with REST start plus SSE delivery.
- Resume SSE by sequence number.
- Run PostgreSQL and Redis through Docker Compose.

### Stage 2: Process separation

- Replace FastAPI background threads with durable `match_jobs` and independent MatchRunner processes. Implemented for AI-only matches.
- Add `decision_jobs` and independent Agent workers.
- Add command idempotency, optimistic `expected_seq`, leases, retries, and dead-letter handling.
- Add a transactional outbox and Redis wake-up delivery.

### Stage 3: Production platform

- Add authentication, authorization, request IDs, structured logs, metrics, traces, and alerting.
- Replace startup schema mutation with versioned Alembic migrations.
- Add PgBouncer or an equivalent pooler, backups, restore drills, and retention policies.
- Add Kubernetes manifests or Helm charts, readiness/liveness probes, resource limits, disruption budgets, and autoscaling.
- Add API, worker, database, provider-failure, and SSE reconnect load tests.

### Stage 4: Capacity acceptance

- Run a production-like 3,000 QPM test for 30 minutes.
- Record latency percentiles, error rate, queue depth, database saturation, Redis latency, worker utilization, and LLM-provider throttling.
- Perform API, runner, Redis, and PostgreSQL restart tests during active matches.
- Approve release only when the capacity contract and recovery tests pass.

## Current Status

Stage 1 is complete for AI-only matches. The API writes a durable `match_jobs`
record and an independent Match Worker process owns game execution. The current
Agent Runtime remains an in-process adapter inside the Match Worker; extracting
`decision_jobs` and an independent Agent Service is the next boundary.

Human matches are intentionally disabled during this stage. Their command,
timeout, reconnection, and state-rehydration contracts will be designed after
the AI-only execution path is stable.
