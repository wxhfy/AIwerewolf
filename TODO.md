# TODO

## Current Goal

- Keep the AI Werewolf game fully playable end to end.
- Preserve verified flows: CLI, HTTP API, room flow, WebSocket spectator updates, browser interaction.
- Continue aligning implementation with `AGENTS.md`, `SKILLS.md`, and the referenced repositories.

## P0 Gameplay

- Expand phase coverage toward the `wolfcha` phase model:
  - Badge signup / badge speech / badge election
  - PK speech
  - Last words
- Raise role realism using `WereWolfPlus` action templates:
  - Role-specific debate templates
  - Stronger vote reasoning
  - Better wolf deception lines
- Introduce structured per-role memory instead of only event-local heuristics.

## P0 Product

- Keep the room-based spectator flow stable.
- Expose richer replay APIs:
  - Current game snapshot
  - Historical game list per room
  - Structured day summaries and facts
- Preserve dual-language support in all new UI surfaces.

## P0 Verification

- Maintain four verification layers on every major change:
  - `pytest -q`
  - `python scripts/e2e_smoke.py`
  - `npm run test:ui`
  - Manual CLI run of `python -m backend.run_demo --config configs/demo.yaml`

## P1 Review / RAG

- Build a GraphRAG-based replay layer on top of `backend/eval/review.py`.
- Convert replay artifacts into graph entities:
  - Player nodes
  - Day / phase nodes
  - Claim edges
  - Vote edges
  - Suspicion edges
  - Contradiction edges
  - Kill / save / guard / divine edges
- Add review queries such as:
  - Which statements most strongly predicted the winning side?
  - Which votes contradicted later public claims?
  - Which players repeatedly pushed low-information eliminations?
  - Which night actions changed the game outcome most?

## P1 Hermes Self-Evolution

- Use `backend/eval/evolution.py` as the interface boundary.
- Planned Hermes-style outer loop:
  1. Export `ReviewArtifact` from a finished game
  2. Use GraphRAG to retrieve decisive mistakes and strong patterns
  3. Generate prompt / memory / policy deltas per role
  4. Version the updated strategy set
  5. Replay updated agents against a frozen baseline
  6. Promote only if metrics improve
- Keep evolution outputs auditable:
  - Strategy version
  - Observations
  - Proposed changes
  - Replay results

## P1 Multi-Agent Optimization Interfaces

- Keep optimizer logic behind `backend/agents/optimization.py`.
- Planned compatible optimization schemes:
  - GraphRAG-guided replay tuning
  - Hermes self-evolution outer loop
  - Self-play policy iteration
  - Population-based prompt search
  - Role-specific memory tuning
  - Multi-agent coordination policy optimization
- All future optimizers should emit structured patches rather than directly mutating engine code.

## P1 Evaluation

- Add role-level metrics:
  - Seer: useful checks, true-positive check rate
  - Witch: save value, poison precision
  - Guard: protection value
  - Werewolf: survival, deception success, vote steering value
  - Villager: vote precision, claim consistency
- Add game-level metrics:
  - Win rate
  - Average day count
  - Information efficiency
  - Contradiction resolution quality

## P2 Architecture

- Replace the static frontend with a proper Next.js + TypeScript + Tailwind app when the protocol stabilizes.
- Introduce persistent storage for rooms, games, and replay artifacts.
- Add multi-room management and reconnect-safe spectator sessions.
