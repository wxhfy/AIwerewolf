# Track B Speech Act Classifier v0 Report

## Purpose

`speech_act_classifier_v0` provides audit-only speech-act features for Track B
review reports. It is used to inspect communication patterns such as accusation,
interrogation, defense, evidence use, identity declaration, and call-for-action.

## Current Contract

- The classifier output is audit-only.
- Metrics are expected at `data/open/combined/speech_act_classifier_v0_metrics.json`.
- Generated audit examples must set `audit_only=true`.
- Generated audit examples must not contain `final_q`.
- Downstream profile aggregation summarizes audit features without changing
  scoring or leaderboard results.

## Required Labels

- `accusation`
- `interrogation`
- `defense`
- `evidence_use`
- `identity_declaration`
- `call_for_action`

## Evidence Paths

- Metrics JSON: `data/open/combined/speech_act_classifier_v0_metrics.json`
- Audit examples script: `scripts/generate_speech_semantic_audit_examples.py`
- Profile analyzer: `scripts/analyze_profile_speech_semantics.py`
- Integration policy: `docs/track_b_speech_semantic_audit_integration_report.md`

