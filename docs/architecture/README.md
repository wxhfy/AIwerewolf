# AI Werewolf V2 Architecture

This document is the current architecture and technology-selection source of truth.

Production capacity and delivery gates are defined in `PRODUCTION_PLAN.md`.
The three-owner write scopes and integration contract are defined in `COLLABORATION.md`.

## Target Boundaries

The system has four code layers and three independent ownership areas.

```text
Browser
  -> REST commands and queries
  -> SSE ordered event stream

FastAPI interfaces
  -> application services
  -> game domain and agent contracts

Match Worker
  -> game domain
  -> AgentRuntime

Infrastructure adapters
  -> PostgreSQL
  -> Redis
  -> LLM providers
```

The implemented AI-only deployment has separate API and Match Worker
processes. The Agent Runtime is currently a local adapter inside each Match
Worker process and preserves the existing CognitiveAgent behavior.

### Presentation layer

The Next.js frontend renders public or player-specific projections. It submits commands through REST and reduces ordered SSE events into UI state. It does not start backend threads, evaluate rules, or decide visibility.

### Application layer

The FastAPI application owns room and match lifecycle, command validation, authorization, idempotency, transaction boundaries, runner scheduling, queries, and event-stream endpoints. It coordinates work but does not implement game rules.

### Domain and agent layer

The game domain owns deterministic state transitions, action legality, visibility, win conditions, and domain events. The AgentRuntime receives a role-safe `PlayerView` and a `DecisionRequest`, then returns a `DecisionResult`. Agents never mutate match state or access match tables directly.

### Infrastructure layer

Adapters implement repositories, Redis coordination, outbox delivery, LLM clients, telemetry, and deployment integration. PostgreSQL is the durable source of truth. Redis accelerates coordination and delivery but is not authoritative storage.

## Runtime Flow

```text
1. Frontend POSTs a command with command_id and expected_seq.
2. Application validates and persists the command.
3. Match Worker obtains a lease and loads the match specification and persisted state.
4. Domain handles the command and emits ordered events.
5. AgentRuntime is called only when the domain emits a decision request.
6. Events, snapshots, decision traces, and outbox rows commit in one transaction.
7. Outbox delivery publishes a Redis notification.
8. SSE reads durable events and pushes them in seq order.
9. Reconnecting clients resume with Last-Event-ID or after_seq.
```

SSE is a delivery channel, not persistence. Recovery always reads PostgreSQL.

## Process, Thread, and Coroutine Model

These mechanisms solve different problems and must not be used interchangeably.

### Processes

- FastAPI API instances are stateless operating-system processes.
- Match Workers are separate processes that claim durable `match_jobs` rows.
- A Worker crash does not terminate the API or remove persisted jobs, events,
  snapshots, or decision traces.
- Worker process count is the primary horizontal scaling control for matches.

### Threads

- A match may use bounded threads when independent Agents can call blocking
  LLM providers concurrently during one phase.
- Threads belong inside one Worker-owned match. They do not own rooms, HTTP
  connections, or cross-match scheduling.
- The API must not start background threads to run matches.

### Coroutines

- FastAPI and SSE use async coroutines for HTTP and streaming I/O.
- Coroutines efficiently wait for Redis notifications, disconnects, and
  network writes without assigning one thread per SSE connection.
- The synchronous game engine and blocking model clients run in Match Worker
  processes, never on the API event loop.

In short: processes isolate and scale matches, threads parallelize bounded
blocking Agent calls inside a match, and coroutines serve HTTP/SSE I/O.

## Current AI-Only Boundary

```text
POST /rooms/{id}/prepare
  -> persist prepared roster and snapshot seq=0
POST /rooms/{id}/start
  -> insert idempotent match_jobs row and return immediately
Match Worker
  -> SELECT ... FOR UPDATE SKIP LOCKED
  -> rebuild the exact prepared roster
  -> create existing CognitiveAgents through LocalAgentRuntime
  -> execute game and persist ordered events, snapshots, and decisions
  -> mark the job completed or failed
SSE
  -> read PostgreSQL projections and resume by sequence
```

Human-seat creation and `/action` commands currently return `501`. Human
reconnection and command recovery will be designed after the AI path is stable.

LLM credentials are deployment secrets owned by the Agent Runtime environment.
Browser-provided API keys are neither persisted in rooms nor copied into
`match_jobs`; room configuration may select an allowed provider/model only.

## Technology Selection

| Concern | Selection | Decision |
|---|---|---|
| Frontend | Next.js, React, TypeScript | Keep |
| HTTP API | Python, FastAPI, Uvicorn | Keep |
| Live updates | SSE over HTTP | Implemented for AI-only matches |
| Match execution | Independent Python Match Worker | Implemented for AI-only matches |
| Agent runtime | Python | Keep close to the LLM and evaluation ecosystem |
| Durable data | PostgreSQL | Required outside isolated tests |
| Coordination | PostgreSQL leases + Redis notifications | Worker lease is implemented in PostgreSQL; Redis notifications and optional rate limiting are implemented |
| Schema migration | Alembic | Add; stop relying on startup table creation |
| Local orchestration | Docker Compose | Primary local environment |
| Production orchestration | Kubernetes | Add after service boundaries and health checks stabilize |
| Observability | OpenTelemetry and structured logs | Add incrementally |

SQLite remains acceptable for unit tests and disposable demos, not for the multi-process runtime.

## Python and Go Decision

Python is not the current scaling bottleneck. The expensive operations are LLM latency, database access, serialization, and match execution. FastAPI remains the control API while Match Worker processes scale independently.

Do not introduce Go in the first V2 slice. A second language adds duplicated contracts, build pipelines, telemetry, deployment images, and operational ownership before the architecture is stable.

Go becomes justified only when measurements show one of these isolated components is capacity-limited:

- an SSE gateway maintaining very large numbers of concurrent connections;
- a high-throughput Redis or event fan-out service;
- a CPU-heavy simulation service that cannot be solved with process scaling or optimized Python code.

If that happens, replace only that adapter or service. Game rules, agent orchestration, prompts, evaluation, and LLM integration should remain in Python.

## Middleware Baseline

FastAPI should use a small, explicit middleware chain:

1. Trusted proxy and forwarded-header handling at the ingress boundary.
2. Request ID and correlation ID propagation.
3. Structured access and error logging.
4. Authentication and actor context.
5. Command idempotency and optimistic sequence checks in the application layer.
6. Rate limiting backed by Redis for public or expensive endpoints.
7. OpenTelemetry tracing and metrics.
8. Central exception-to-problem-response mapping.

CORS is needed only when frontend and API use different origins. Compression and proxy buffering must be configured carefully for SSE; event responses require immediate flushing and heartbeat support.

## Data Model Baseline

```text
rooms
matches
match_commands
match_events
match_snapshots
agent_decision_traces
outbox_events
post_game_jobs
```

Every match event has a unique `(match_id, seq)`. Commands have a unique `command_id`. Snapshots record the last included sequence. Outbox rows are written in the same transaction as domain events.

## Ownership

| Owner | Write scope |
|---|---|
| Frontend | `frontend/`, UI tests, generated client bindings |
| Backend/platform | API, application, domain, persistence, Redis, workers, deployment, shared contracts |
| Agent/evaluation | agent runtime, prompts, provider adapters, memory, evaluation, agent tests |

No cross-owner review is required. Shared contracts are versioned by the backend/platform owner; other owners request contract changes instead of editing shared schemas concurrently.

## First Vertical Slice

```text
create match
-> submit one idempotent command
-> runner loads match
-> fake agent returns one decision
-> domain emits event seq=1
-> PostgreSQL transaction stores event and outbox
-> Redis wakes delivery
-> SSE sends event
-> frontend reducer renders it
-> process restart recovers the same match
```

Do not migrate all existing endpoints before this slice passes integration tests.
