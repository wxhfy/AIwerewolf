# Track B Ranker Contribution and Human Pairwise Labeling Plan

> Goal: safely integrate the per-action pairwise rankers as bounded auxiliary signals, while preparing a real-replay human labeling path for future promotion decisions.
>
> Current status: PairwiseLogisticRanker has improved from speech-only auxiliary to stable auxiliary across speech, vote, and night-action categories. It is still not a primary scoring source because vote pair degeneracy remains above the target and real replay human labels are not available yet.

---

## 1. Current status

Latest implementation status:

```text
77 tests passed
hard_cap_count = 0
```

Implemented components:

- expanded vote quality features;
- expanded night-action target-value features;
- pairwise expansion data for vote and night-action examples;
- per-action rankers:
  - SpeechPairwiseRanker;
  - VotePairwiseRanker;
  - NightActionPairwiseRanker;
  - Global fallback ranker.

Current metrics:

| Metric | Current | Target |
|---|---:|---:|
| effective pairs | 110 | >= 80 |
| vote degenerate rate | <= 35% | <= 20% |
| night-action degenerate rate | <= 25% | <= 20% |
| hard cap count | 0 | 0 |

Interpretation:

```text
PairwiseRanker is a stable auxiliary signal.
It should not be promoted to primary scoring until real replay human pairwise validation exists.
```

---

## 2. Design principle

The ranker may influence final scoring only through a confidence gate.

It must never overwrite the existing score directly.

Recommended final quality formula:

```text
final_q = (1 - ranker_weight) * calibrated_q + ranker_weight * learned_rank_q
```

Where:

- `calibrated_q` remains the current main quality signal;
- `learned_rank_q` is an auxiliary learned ranking signal;
- `ranker_weight` is assigned by RankerConfidenceGate;
- if the ranker is not eligible, `ranker_weight = 0` and `final_q = calibrated_q`.

---

## 3. RankerConfidenceGate

Add a confidence gate that decides whether a per-action ranker can affect scoring.

### 3.1 Inputs

```json
{
  "action_type": "vote",
  "pair_type": "wolf_vote_coordination",
  "effective_pair_count": 70,
  "degenerate_pair_rate": 0.35,
  "validation_acc": 0.66,
  "heldout_acc": 0.61,
  "low_sample": false,
  "hard_cap_count": 0
}
```

### 3.2 Output

```json
{
  "eligible": false,
  "weight": 0.0,
  "confidence": "debug_only",
  "reasons": ["degenerate_pair_rate_above_medium_gate"]
}
```

### 3.3 Gate levels

#### High confidence

Requirements:

```text
effective_pair_count >= 50
degenerate_pair_rate <= 0.20
validation_acc >= 0.70
heldout_acc >= 0.65
hard_cap_count == 0
```

Action:

```text
weight = 0.15
confidence = high
```

#### Medium confidence

Requirements:

```text
effective_pair_count >= 30
degenerate_pair_rate <= 0.30
validation_acc >= 0.65
heldout_acc >= 0.60
hard_cap_count == 0
```

Action:

```text
weight = 0.10
confidence = medium
```

#### Low confidence

Requirements:

```text
effective_pair_count >= 15
degenerate_pair_rate <= 0.40
validation_acc >= 0.60
hard_cap_count == 0
```

Action:

```text
weight = 0.05
confidence = low
```

#### Debug only

Any condition below low-confidence gate.

Action:

```text
weight = 0.0
confidence = debug_only
```

### 3.4 Expected current gating

Expected status at this phase:

| Action family | Expected gate | Notes |
|---|---|---|
| speech | low/medium/high | depends on current heldout metrics |
| night-action | low/medium | current degeneration is near target |
| vote | debug-only or low | vote degeneration is still too high |
| global fallback | debug-only | do not rely on mixed low-sample ranker |

---

## 4. OpportunityScore integration

Every scored opportunity should preserve all score components.

### 4.1 Required fields

```json
{
  "opportunity_id": "...",
  "raw_model_q": 0.71,
  "calibrated_q": 0.68,
  "learned_rank_q": 0.59,
  "final_q": 0.671,
  "ranker_contribution": {
    "used": true,
    "action_ranker": "speech",
    "eligible": true,
    "weight": 0.10,
    "confidence": "medium",
    "final_delta": -0.009,
    "reasons": ["medium_confidence_gate_passed"]
  }
}
```

### 4.2 Bounded influence

Constraints:

```text
single opportunity abs(final_q - calibrated_q) <= 0.15
average process-score delta <= 0.05
hard_cap_count = 0
```

If a ranker contribution violates the bound, the audit must report a warning.

---

## 5. ProcessScoreV3 integration

ProcessScoreV3 should support two tracks:

```text
process_score_v3_without_ranker
process_score_v3_with_ranker
ranker_delta
ranker_coverage_rate
ranker_debug_only_rate
```

Rules:

1. `process_score_v3_without_ranker` remains the baseline.
2. `process_score_v3_with_ranker` uses `final_q` only when RankerConfidenceGate permits contribution.
3. Report both values in all summaries.
4. Do not hide large deltas.
5. If ranker delta is high, emit a warning.

Recommended warning thresholds:

```text
abs(avg_process_delta) > 0.05
max_single_opportunity_delta > 0.15
vote_ranker_weight > 0 when vote degeneration > 0.40
```

---

## 6. Ranker contribution audit

Add a vNext evaluation suite:

```bash
python scripts/evaluate_track_b_vnext.py --suite ranker_contribution
```

Output files:

```text
data/health/ranker_contribution_audit.json
docs/track_b_ranker_contribution_audit.md
```

### 6.1 Required metrics

```text
total_opportunities
ranker_used_count
ranker_used_rate
debug_only_count
debug_only_rate
max_single_delta
avg_process_delta
hard_cap_count
```

### 6.2 By action type

For each action family:

```json
{
  "action_type": "vote",
  "count": 120,
  "eligible_count": 12,
  "avg_weight": 0.02,
  "avg_abs_delta": 0.008,
  "confidence_distribution": {
    "high": 0,
    "medium": 0,
    "low": 12,
    "debug_only": 108
  }
}
```

### 6.3 Expected audit conclusion

The expected current conclusion should be conservative:

```text
PairwiseRanker contributes only when confidence gates pass. It remains an auxiliary signal and is not yet the primary scoring source.
```

---

## 7. Human pairwise label schema

A real replay human labeling path is required before promoting pairwise rankers into primary scoring.

Add documentation:

```text
docs/track_b_human_pairwise_label_schema.md
```

Add template:

```text
data/health/human_pairwise_labels_template.jsonl
```

### 7.1 Schema

```json
{
  "label_id": "label_000001",
  "game_id": "game_xxx",
  "source": "real_replay",
  "role": "Werewolf",
  "action_type": "vote",
  "day": 2,
  "phase": "DAY_VOTE",
  "context_summary": "Only information visible at decision time should be used.",
  "visible_public_context": {},
  "visible_private_context": {},
  "option_a": {
    "opportunity_id": "opp_a",
    "action": {},
    "evidence_event_ids": []
  },
  "option_b": {
    "opportunity_id": "opp_b",
    "action": {},
    "evidence_event_ids": []
  },
  "label": "A_BETTER",
  "confidence": "high",
  "reason": "Option A better matches the role objective under the visible context.",
  "annotator_id": "annotator_001",
  "created_at": "2026-05-29T00:00:00Z"
}
```

### 7.2 Allowed labels

```text
A_BETTER
B_BETTER
TIE
UNCERTAIN
```

### 7.3 Rules for annotators

1. Judge only from visible public context and visible private context.
2. Do not use future outcome information.
3. Do not use hidden information unavailable to the actor.
4. Always provide a reason.
5. Use `TIE` when actions are equivalent.
6. Use `UNCERTAIN` when there is not enough evidence.
7. Include evidence event IDs when possible.

---

## 8. Human label validation

Add a validator:

```text
validate_human_pairwise_labels(path)
```

Minimum checks:

1. required fields exist;
2. label is valid;
3. confidence is valid;
4. reason is non-empty;
5. role/action type are valid;
6. visible public context exists;
7. visible private context exists;
8. option_a and option_b both exist;
9. each option has an action payload;
10. evidence_event_ids field exists;
11. future-info warning if detectable.

Add tests:

```text
tests/test_track_b_human_pairwise_schema.py
```

Required cases:

- valid template passes;
- missing reason fails;
- invalid label fails;
- TIE is allowed;
- UNCERTAIN is allowed;
- missing visible context fails.

---

## 9. Required tests

Add tests:

```text
tests/test_track_b_ranker_contribution.py
tests/test_track_b_human_pairwise_schema.py
```

Minimum assertions:

1. high-degeneration ranker becomes debug-only;
2. low/medium/high gates assign correct weight;
3. opportunity score keeps raw/calibrated/learned/final fields;
4. single-step ranker delta is bounded;
5. ProcessScoreV3 reports with-ranker and without-ranker values;
6. ranker contribution audit runs;
7. human label template passes validation;
8. invalid human label examples fail validation.

---

## 10. Commands

Run:

```bash
python scripts/evaluate_track_b_vnext.py --suite ranker_contribution
python scripts/evaluate_track_b_vnext.py --all

pytest tests/test_track_b_ranker_contribution.py -q
pytest tests/test_track_b_human_pairwise_schema.py -q
```

Full regression:

```bash
pytest tests/test_track_b_badcase_regression.py \
       tests/test_track_b_badcase_wolf_regression.py \
       tests/test_track_b_cleancase_wolf_regression.py \
       tests/test_track_b_generalization_matrix.py \
       tests/test_track_b_model_loading.py \
       tests/test_track_b_learning_refactor.py \
       tests/test_pairwise_ranker_direction.py \
       tests/test_track_b_vote_kill_features.py \
       tests/test_track_b_pairwise_expansion.py \
       tests/test_track_b_vnext_evaluation.py \
       tests/test_track_b_ranker_contribution.py \
       tests/test_track_b_human_pairwise_schema.py -q
```

---

## 11. Acceptance criteria

### Minimum

```text
RankerConfidenceGate implemented
Opportunity score outputs raw/calibrated/learned/final fields
ProcessScoreV3 reports with-ranker and without-ranker values
ranker contribution audit runs
human pairwise schema document exists
human label template exists
all existing tests pass
hard_cap_count = 0
```

### Target

```text
ranker_used_rate is non-zero but bounded
avg_process_delta <= 0.05
max_single_delta <= 0.15
vote ranker does not dominate when vote degeneration remains high
human label validator passes template and rejects invalid labels
```

### Promotion threshold

The pairwise ranker may affect the main ProcessScore only when:

```text
real replay human labels exist
heldout_acc >= 0.70
clean false positive <= 15%
bad false negative <= 15%
calibration_dependency <= 30%
```

Until then, report it as:

```text
stable auxiliary signal, not primary scoring source
```
