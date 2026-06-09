---
type: strategy_wiki
scope: overview
status: draft
source_docs: []
source_reports: []
last_compiled: 2026-06-08
tags:
  - track-c
  - llm-wiki
  - hermes-evolution
---

# Track C Overview

## Current Consensus

Track C is a three-layer system:

1. LLM Wiki compiles post-game evidence into readable strategy knowledge.
2. Hermes-style evolution proposes candidate strategy patches and validates them.
3. Runtime retrieval injects only lifecycle-approved, versioned, and safety-filtered strategies into agents.

Runtime strategy knowledge is versioned:

- `raw`: original post-game lessons or wiki-synced candidates.
- `refined`: promoted knowledge with enough evidence to use in games.
- `canonical`: validated accepted patches or long-term strategy cards.

The retriever prefers validated refined/canonical descendants within the same strategy theme, while unvalidated new candidates remain lower priority. Newer knowledge is treated as more refined only after validation.

## Evidence

- Runtime lifecycle diagrams: `../../ENGINEERING_ARCHITECTURE.md`
- Module design: `../../PROJECT_MODULE_DESIGN.md`
- Runtime knowledge table: `strategy_knowledge_docs`
- Evolution code: `backend/eval/evolution.py`
- Retrieval code: `backend/agents/cognitive/retrieval_prod.py`

## Runtime Candidates

No wiki-authored runtime candidates have been approved yet. Existing runtime candidates still come from `KnowledgeAbstractor`, `DreamJob`, and database lifecycle tools.

## Conflicts

- Wiki content must not bypass information-isolation and lifecycle filtering.
- Human-edited notes must not be synchronized as `active`; they must start as `candidate`.
- Superseded old strategy docs should not remain in runtime prompts after a refined/canonical successor is accepted.

## Open Questions

- Implement `scripts/wiki_ingest_track_c.py`.
- Implement `scripts/wiki_lint_track_c.py`.
- Implement `scripts/wiki_sync_strategy_docs.py`.
