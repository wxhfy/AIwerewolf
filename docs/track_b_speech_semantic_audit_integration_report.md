# Track B Speech Semantic Audit Integration Report

## Scope

Speech semantic analysis is an audit-only signal for Track B review reports.
It summarizes speech-act probabilities and profile-level communication
patterns, but it is not part of the final decision-quality score.

## No Final Q Impact Policy

The speech semantic audit pipeline does NOT affect `final_q` scoring.
Semantic audit outputs are isolated from the scoring pathway:

- `final_q` is not modified by semantic audit results.
- Speech semantic probabilities are logged as audit features only.
- Profile aggregation does not affect pairwise rankings.
- Leaderboard and process-score calculations do not consume these audit-only fields.

This report explicitly states that speech semantic audit data does not affect
scoring outcomes. NO direct impact on leaderboard ranking, `process_score`, or
`final_q` is allowed.

## Evidence Paths

- Metrics: `data/open/combined/speech_act_classifier_v0_metrics.json`
- Audit example generator: `scripts/generate_speech_semantic_audit_examples.py`
- Profile aggregation: `scripts/analyze_profile_speech_semantics.py`
- Scorer implementation: `backend/eval/heads/speech_semantic.py`

