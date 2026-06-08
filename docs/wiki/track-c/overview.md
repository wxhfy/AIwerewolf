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
3. Runtime retrieval injects only lifecycle-approved and safety-filtered strategies into agents.

## Evidence

- Canonical design: [Track C Hermes + LLM Wiki Design](../../TRACK_C_HERMES_LLM_WIKI_DESIGN.md)
- Runtime knowledge table: `strategy_knowledge_docs`
- Evolution code: `backend/eval/evolution.py`
- Retrieval code: `backend/agents/cognitive/retrieval_prod.py`

## Runtime Candidates

No wiki-authored runtime candidates have been approved yet. Existing runtime candidates still come from `KnowledgeAbstractor`, `DreamJob`, and database lifecycle tools.

## Conflicts

- Wiki content must not bypass information-isolation and lifecycle filtering.
- Human-edited notes must not be synchronized as `active`; they must start as `candidate`.

## Open Questions

- Implement `scripts/wiki_ingest_track_c.py`.
- Implement `scripts/wiki_lint_track_c.py`.
- Implement `scripts/wiki_sync_strategy_docs.py`.
