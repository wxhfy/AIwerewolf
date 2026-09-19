# Three-Owner Collaboration Contract

The project has three independent owners. No cross-owner code review is required, so stability comes from strict write scopes, versioned contracts, and automated integration checks.

## Frontend Owner

Write scope: `frontend/`.

Responsibilities:

- Render server-provided public or player-specific projections.
- Submit REST commands with `command_id` and `expected_seq`.
- Consume SSE in sequence order and reconnect with `Last-Event-ID`.
- Keep UI-only state such as selected tabs, animation progress, and local form input.
- Generate or consume typed API bindings and add reducer/reconnect tests.

The frontend must not infer hidden roles, advance phases, repair event order, or make agent decisions.

## Backend and Platform Owner

Write scope: API, application services, game domain, persistence, workers, deployment, and shared contracts.

Responsibilities:

- Own REST/SSE schemas and compatibility versions.
- Enforce authentication, authorization, visibility, idempotency, and optimistic concurrency.
- Persist commands, ordered events, snapshots, outbox rows, and match status.
- Run Match Worker scheduling, leases, recovery, and post-game jobs.
- Operate PostgreSQL, Redis, observability, migrations, CI, Docker, and Kubernetes assets.
- Publish contract fixtures and integration-test environments for the other owners.

## Agent and Evaluation Owner

Write scope: agent runtime, prompts, memory, provider adapters, evaluation, and agent tests.

Responsibilities:

- Consume a versioned `DecisionRequest` containing only role-safe `PlayerView` data.
- Return a versioned `DecisionResult`; never mutate game state directly.
- Record model, provider, prompt version/hash, parsed result, validation result, usage, latency, cost, and fallback reason.
- Handle provider-specific quotas, retries, timeouts, and circuit breakers behind one runtime interface.
- Maintain offline fake-model fixtures and quality/evaluation suites.

## Shared Contract Workflow

1. Backend publishes the schema change and version.
2. Frontend and Agent owners update against generated types or fixtures in their own branches.
3. Each branch runs its own unit checks.
4. Contract tests run against all three implementations before deployment.
5. Breaking changes require a version transition or a coordinated release flag, even though no human review is required.

## Mandatory Integration Artifacts

- OpenAPI document for REST endpoints.
- JSON Schema or equivalent typed definitions for commands, events, snapshots, `DecisionRequest`, and `DecisionResult`.
- Example public, player, and moderator fixtures.
- Reconnect and duplicate-command test cases.
- A Docker Compose environment with PostgreSQL, Redis, API, Match Worker, and frontend. Add the Agent Service container when remote execution is implemented.
- A load-test scenario and a production readiness report.

Independent development means owners do not block on approvals. It does not mean contracts, migrations, or integration tests are optional.
