# Backend Skeleton and Integration Contract

Status: bootstrap implementation, 2026-09-19.

This document is the backend handoff baseline. The current priority is an AI-only match that runs reliably from room creation to persisted replay. Human play and a remotely deployed Agent Service remain explicit extension points.

## 1. Runtime boundaries

| Process | Responsibility | State ownership |
|---|---|---|
| API service | Validate requests, create rooms/matches, accept commands, expose reads and SSE | No in-memory source of truth |
| Match Worker | Claim durable match jobs, run the game engine, call agents, persist progress | Lease in PostgreSQL |
| Agent runtime | Build per-player context and return one legal decision | Local implementation today; remote contract reserved |
| Analysis Worker | Claim durable post-game jobs; run Track B scoring and Track C extraction | Retryable job in PostgreSQL |
| PostgreSQL | Rooms, games, jobs, events, snapshots, decisions, commands, outbox | Authoritative durable state |
| Redis | SSE wake-up notifications and optional distributed rate limiting | Never authoritative |
| Frontend | Render projections, issue REST commands, consume SSE | No game-rule decisions |

The expected flow is:

```text
Frontend -> REST command -> API -> PostgreSQL job/command
                                  |
                                  v
                            Match Worker
                                  |
                         Engine -> Agent runtime -> LLM
                                  |
                    events/snapshots/decisions -> PostgreSQL
                                  |
                    Redis notification -> API SSE -> Frontend

Finished match -> post-game job -> Analysis Worker
                                  |-> Track B decision_evaluations / PublishedReview
                                  `-> Track C strategy_knowledge_docs
```

## 2. Stable API surface

New platform endpoints are versioned under `/api/v1`. Existing `/api/*` endpoints remain available while the frontend migrates.

| Endpoint | State | Purpose |
|---|---|---|
| `GET /api/v1/health/live` | Implemented | Process liveness only |
| `GET /api/v1/health/ready` | Implemented | PostgreSQL readiness; Redis is reported separately |
| `GET /api/v1/system/capabilities` | Implemented | Runtime and schema capability discovery |
| `GET /api/v1/matches/{match_id}` | Implemented | Match execution plus latest public projection |
| `POST /api/v1/matches/{match_id}/commands` | Partial | Idempotent pause/resume; cancel is an explicit `501` |
| `GET /api/matches/{match_id}/events` | Implemented | Ordered public event catch-up |
| `GET /api/matches/{match_id}/stream` | Implemented | Resumable SSE snapshots using `Last-Event-ID` |
| `GET /api/v1/agent/capabilities` | Implemented contract | Agent protocol discovery |
| `POST /api/v1/agent/decisions` | Contract only | Returns `501` until remote Agent Service is deployed |
| `GET /api/v1/matches/{match_id}/analysis` | Implemented | Analysis job status and Track B/C coverage |
| `GET /api/v1/matches/{match_id}/decisions` | Implemented | Sanitized decision trace metadata |
| `GET /api/v1/matches/{match_id}/decision-evaluations` | Implemented | Versioned per-step Track B scores |
| `POST /api/v1/matches/{match_id}/analysis/retry` | Implemented | Requeue analysis for a finished match |
| `GET /api/v1/strategies` | Implemented | Query persisted Track C strategy knowledge |
| `GET /api/v1/strategies/{strategy_id}` | Implemented | Read one strategy document |

All platform errors use `application/problem+json` and contain `code`, `detail`, `instance`, and `request_id`. Existing clients can continue reading the `detail` field.

## 3. Middleware

| Middleware | Current behavior | Production evolution |
|---|---|---|
| Request context | Accepts or generates `X-Request-ID`; returns timing headers | Propagate into worker jobs and LLM traces |
| Access logging | Method, path, status, latency, request ID | Emit structured JSON to log aggregation |
| Security headers | Content sniffing, framing, referrer and browser permissions protection | Add CSP at nginx/frontend boundary |
| Body limit | Rejects oversized requests from `Content-Length` | Enforce again at nginx/load balancer |
| CORS | Explicit origins from `CORS_ORIGINS` | Configure deployment domains only |
| Rate limiting | Redis fixed window, disabled by default | Enable per authenticated actor at gateway/API |
| Authentication | `ActorContext` dependency; development mode is anonymous | Replace with JWT/OIDC `TokenVerifier` |

## 4. Persistence contracts

New tables introduced by `004_platform_skeleton.sql`:

- `match_commands`: command ID is the idempotency key; stores status and result.
- `agent_decision_jobs`: durable request/response boundary for a future Agent Service worker.
- `outbox_events`: transactionally records domain events before broker publication.

The Outbox publisher is intentionally not started yet. Rows are durable and queryable, and a later process can publish them to Redis Streams, NATS, RabbitMQ, or Kafka without changing application commands.

`005_analysis_pipeline.sql` adds `decision_evaluations`. Each row is keyed by decision plus evaluator version, making Track B rescoring idempotent and allowing future evaluator upgrades without overwriting historical scores. Track C remains durable in `strategy_knowledge_docs`, including provenance, confidence, lifecycle status, version lineage and usage feedback.

Compatibility note: the legacy `PublishedReview` document is still generated synchronously at game end because its current builder consumes the in-memory event-rich `GameState`. Per-step evaluation and strategy extraction are already asynchronous. Moving `PublishedReview` into the Analysis Worker requires reconstructing the complete event, vote and decision projection from PostgreSQL and is the next Track B migration step.

The persistence policy is intentionally not "store hidden chain of thought". Store the observable decision contract: visible observation, legal actions, parsed action, provider response permitted by policy, validation result, latency/tokens/cost, model/prompt identifiers, score evidence and strategy provenance.

## 5. Agent Service contract

`AgentDecisionRequest` contains an immutable observation, legal actions, agent configuration, and deadline. `AgentDecisionResult` contains the selected action, reasoning, usage and trace metadata. Match code must depend on the `AgentGateway` protocol rather than a concrete HTTP client.

The current Match Worker still uses `LocalAgentRuntime`, preserving existing agent behavior. A remote implementation should provide the same contract, add request deduplication by `request_id`, and never receive another player's private state.

The contract can already be started as an independent process for integration work:

```bash
uvicorn backend.agent_service:app --host 0.0.0.0 --port 8001
```

This process deliberately returns a structured `501` for decisions until the remote runtime adapter is implemented. Its OpenAPI contract and health endpoint are usable now.

## 6. Explicitly unfinished work

- Cooperative match cancellation and safe worker interruption.
- JWT/OIDC token verification and role-based authorization.
- Outbox publisher process and dead-letter handling.
- Remote Agent Service process and `AgentDecisionJob` worker.
- Prometheus metrics, tracing exporter, and centralized JSON logging.
- Alembic as the single authoritative migration runner. SQL migrations and `create_all` coexist during bootstrap.
- Human-player command flow.

These are visible contracts, not hidden TODO behavior. Callers receive capability flags or a structured `501` until an implementation is enabled.

## 7. Local verification

```bash
python -m ruff check backend tests
pytest -q tests/test_engine.py tests/test_api.py
python scripts/e2e_smoke.py
docker compose up -d --build postgres redis backend match-worker analysis-worker
```
