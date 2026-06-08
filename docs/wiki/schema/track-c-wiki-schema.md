# Track C Wiki Schema

Track C wiki pages should be Markdown files with YAML frontmatter.

## Required Frontmatter

```yaml
---
type: strategy_wiki
scope: overview
status: draft
source_docs: []
source_reports: []
last_compiled: 2026-06-08
tags:
  - track-c
---
```

## Required Sections

```text
# Title

## Current Consensus

## Evidence

## Runtime Candidates

## Conflicts

## Open Questions
```

## Runtime Rule

Wiki pages do not directly enter Agent prompts. Only candidates synchronized into `strategy_knowledge_docs` and promoted through the existing lifecycle can become runtime strategies.
