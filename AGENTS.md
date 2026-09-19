# AI Werewolf Engineering Guide

This file contains only repository-level rules that are still required.

## Current Working Model

- Three owners work independently: frontend, backend/platform, and agent/evaluation.
- Each owner may commit, push, and merge changes in their own branch without review or approval from the other owners.
- The backend/platform owner maintains shared REST, SSE, event, agent, and database contracts.
- Cross-owner integration is contract-driven. Do not edit another owner's implementation to bypass a contract mismatch.
- Human review is optional. Automated checks for the changed workstream remain required.

## Architecture Direction

- Frontend: presentation only; submit commands through REST and consume ordered events through SSE.
- Application layer: room and match lifecycle, command validation, authorization, idempotency, scheduling, and queries.
- Domain layer: deterministic game rules, visibility, state transitions, and domain events.
- Agent runtime: consume `DecisionRequest` plus role-safe `PlayerView`, and return `DecisionResult`.
- Infrastructure: PostgreSQL persistence, Redis coordination, LLM providers, and external delivery adapters.
- PostgreSQL is the durable source of truth. Redis is never the only copy of match state or events.
- Domain and agent code must not import FastAPI, SQLAlchemy repositories, Redis clients, or frontend types.

The target design is documented in `docs/architecture/README.md`.

## Repository Safety

- Never commit `.env`, API keys, local databases, logs, model files, or generated experiment output.
- Do not force-push `main` and do not bypass hooks.
- Preserve unrelated local changes.
- Use Conventional Commits: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, or `chore`.

## Verification

Run checks appropriate to the changed workstream:

```bash
make lint
make test
python -m backend.run_demo --seed 7
cd frontend && npm run lint && npm run build
```

Contract and persistence changes require integration tests. Visibility changes require explicit information-isolation tests.
