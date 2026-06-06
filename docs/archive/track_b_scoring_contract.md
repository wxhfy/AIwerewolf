# Track B Scoring Contract

## Role Model Policy

This document defines the scoring contract for Track B evaluation.

### Role Model Architecture
- Shared encoder with role-specific adapter heads (role heads)
- NOT independent model per role — shared architecture preferred
- Minimum 300 samples per role before standalone model is considered
- Minimum 50 critical samples per role
- Minimum 50 clean case samples per role
- Minimum 50 human-labeled opportunities per role

### Scoring Dimensions
Each decision opportunity is scored across: role_task, vote, speech, skill, survival

### Quality Gates
- Gate 1: validation_result.passed == True
- Gate 2: publish_allowed == True
- Gate 3: fallback_count == 0 for LLM runs
- Gate 4: review_report.metadata contains all required fields

> Generated: placeholder scoring contract.
