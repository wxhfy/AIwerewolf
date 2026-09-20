# Changelog

All notable changes to AI Werewolf are recorded here.

## [Unreleased] - 2026-09-20

### Added

- Portable Agent Harness with typed decision requests, middleware, policy,
  validation, tools, skills, events, and runtime metrics.
- Werewolf domain adapter that converts an information-filtered `PlayerView`
  into Harness input and converts validated Harness output into engine decisions.
- PostgreSQL-backed match execution with durable jobs, snapshots, events,
  resumable SSE delivery, and asynchronous analysis jobs.
- Explicit application, domain, runtime, persistence, and interface boundaries.

### Changed

- AI matches now follow one execution path: REST command -> Match Worker ->
  Harness Runtime -> deterministic game engine -> PostgreSQL -> SSE projection.
- The game engine no longer creates agents, calls model providers, or owns
  application lifecycle concerns.
- PostgreSQL is the authoritative state store; Redis is optional coordination,
  notification, and rate-limiting infrastructure.
- Demo and experiment entry points construct games through the application
  configuration layer.

### Removed

- Legacy agent hierarchy and its duplicated planning, memory, and fallback
  implementations.
- Placeholder standalone Agent Service and its unused HTTP contracts.
- WebSocket game delivery and obsolete compatibility paths.
- Historical delivery reports, generated evidence, stale experiment scripts,
  and tests coupled to removed agent implementations.
