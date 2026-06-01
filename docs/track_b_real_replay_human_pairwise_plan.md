# Track B Real Replay Human Pairwise Pipeline Plan

> Goal: build the first real-replay human pairwise labeling loop for Track B, so PairwiseRanker can eventually be validated against human judgment instead of only controlled synthetic cases.
>
> Current status: RankerConfidenceGate and human label schema are implemented. PairwiseRanker is a stable auxiliary signal, not a primary scoring source.

---

## 1. Current status

Current system status:

```text
95 tests passed
RankerConfidenceGate implemented
Human pairwise label schema implemented
Human label validator implemented
PairwiseRanker safely contributes only through bounded confidence gates
```

Current scoring formula:

```text
final_q = (1 - weight) * calibrated_q + weight * learned_rank_q
```

Current boundary:

```text
PairwiseRanker remains a stable auxiliary signal.
It must not be promoted to primary scoring until real replay human validation passes.
```

---

## 2. Why this phase matters

Synthetic BadCase, CleanCase, and Generalization Matrix tests prove controlled behavior, but they do not prove real-world evaluation reliability.

To promote PairwiseRanker, Track B needs evidence that model preferences match human judgments on real replay decisions.

This phase builds the minimum loop:

```text
real replay opportunities
  -> pairwise candidate queue
  -> human labels
  -> validation
  -> model-human agreement report
  -> vNext evaluation integration
```

---

## 3. Scope

This phase should add:

1. a queue builder for human pairwise candidates;
2. a human label sample file;
3. a label validation command;
4. a model-human agreement command;
5. a vNext evaluation suite for human pairwise validation;
6. tests for graceful skip when real labels are unavailable.

Out of scope:

- Track C changes;
- frontend UI;
- core engine refactor;
- changing primary scoring logic;
- promoting PairwiseRanker to primary scoring.

---

## 4. Human pairwise queue

### 4.1 Script

Add:

```text
scripts/build_human_pairwise_queue.py
```

### 4.2 Inputs

Use available sources when present:

```text
data/health/opportunities.jsonl
data/health/opportunity_scores*.jsonl
data/health/replay bundles
existing Track B scored outputs
```

If no real replay data exists, the script should produce a low-sample warning and exit cleanly.

### 4.3 Output

```text
data/health/human_pairwise_queue.jsonl
```

### 4.4 Candidate schema

Each candidate should follow the human label schema, but remain unlabeled:

```json
{
  "label_id": "label_candidate_000001",
  "game_id": "game_xxx",
  "source": "real_replay",
  "role": "Werewolf",
  "action_type": "vote",
  "day": 2,
  "phase": "DAY_VOTE",
  "context_summary": "Only visible information at decision time should be used.",
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
  "label": "UNLABELED",
  "confidence": "medium",
  "reason": "",
  "annotator_id": "",
  "created_at": ""
}
```

---

## 5. Candidate selection strategy

Prioritize candidate pairs that will be informative for validation.

### 5.1 Pair matching

Prefer pairs with:

1. same role;
2. same action type;
3. similar day and phase;
4. similar public context;
5. available private context when relevant;
6. complete action payload;
7. evidence event IDs.

### 5.2 Pair priority

High-value candidates:

1. model score gap is large but confidence is low;
2. `calibrated_q` and `learned_rank_q` disagree;
3. RankerConfidenceGate marks action as low or debug-only;
4. action type is under-validated;
5. role-action z-score is extreme;
6. opportunity has critical-review tags;
7. human-readable context is sufficient for annotation.

### 5.3 Action type coverage

Queue should attempt to cover:

```text
speech
vote
night_action
seer_release
witch_poison
guard_protect
hunter_shot
```

If an action type has too few candidates, report low sample.

### 5.4 Exclusion rules

Do not include pairs with:

- missing visible context;
- missing action payload;
- future information in PreAction context;
- only player ID difference with strategically equivalent actions;
- no evidence event field;
- impossible comparison across unrelated roles/actions unless explicitly marked.

---

## 6. Human label sample file

Add:

```text
data/health/human_pairwise_labels_sample.jsonl
```

Include at least 5 valid examples:

1. `A_BETTER`;
2. `B_BETTER`;
3. `TIE`;
4. `UNCERTAIN`;
5. a low-confidence example.

Requirements:

- must pass the validator;
- `reason` must be non-empty;
- visible public/private context fields must exist;
- evidence event IDs field must exist;
- no future information should be used.

---

## 7. Label validation command

Add:

```text
scripts/validate_human_pairwise_labels.py
```

Usage:

```bash
python scripts/validate_human_pairwise_labels.py \
  --input data/health/human_pairwise_labels_sample.jsonl
```

Output:

```text
data/health/human_pairwise_validation_result.json
```

Expected structure:

```json
{
  "total": 5,
  "valid": 5,
  "invalid": 0,
  "errors": [],
  "label_distribution": {
    "A_BETTER": 1,
    "B_BETTER": 1,
    "TIE": 1,
    "UNCERTAIN": 1
  }
}
```

Validation should reject:

- missing required fields;
- invalid label;
- empty reason for labeled examples;
- missing visible context;
- missing action payload;
- missing evidence event IDs field;
- invalid confidence value.

---

## 8. Model-human agreement evaluation

Add:

```text
scripts/evaluate_human_pairwise_agreement.py
```

### 8.1 Inputs

```text
human label JSONL
opportunity scores JSONL
ranker predictions if available
```

Example usage:

```bash
python scripts/evaluate_human_pairwise_agreement.py \
  --labels data/health/human_pairwise_labels_sample.jsonl
```

### 8.2 Output

```text
data/health/human_pairwise_agreement.json
docs/track_b_human_pairwise_agreement_report.md
```

### 8.3 Metrics

Report:

```text
total_labeled_pairs
usable_pairs
model_pairwise_accuracy
calibrated_q_accuracy
learned_rank_q_accuracy
final_q_accuracy
by_action_type_accuracy
tie_count
uncertain_count
low_sample_warning
disagreement_examples
```

### 8.4 Usable pairs

Exclude from accuracy:

```text
TIE
UNCERTAIN
invalid labels
```

They should still be counted and reported.

### 8.5 First-round thresholds

Do not overclaim in the first round.

Initial target:

```text
usable_pairs >= 20
final_q_accuracy >= 0.60
```

If `usable_pairs < 20`, report low sample and do not claim validation success.

---

## 9. vNext evaluation integration

Extend:

```text
scripts/evaluate_track_b_vnext.py
```

Add suite:

```bash
python scripts/evaluate_track_b_vnext.py --suite human_pairwise
```

Behavior:

1. If real human labels exist, run agreement evaluation.
2. If only sample labels exist, run sample validation and mark as smoke test.
3. If no labels exist, output skipped with clear reason.
4. Do not fail the full evaluation when labels are absent.

Update:

```text
docs/track_b_vnext_eval_report.md
```

Add a Human Pairwise Validation section.

---

## 10. Tests

Add:

```text
tests/test_track_b_human_pairwise_pipeline.py
```

Required tests:

1. `test_build_human_pairwise_queue_runs`
2. `test_human_pairwise_queue_schema`
3. `test_human_pairwise_label_sample_validates`
4. `test_validate_human_pairwise_labels_script`
5. `test_evaluate_human_pairwise_agreement_runs`
6. `test_vnext_human_pairwise_suite_skips_without_labels`
7. `test_human_pairwise_agreement_handles_tie_uncertain`

Testing rule:

- tests must not require real replay labels to exist;
- tests should verify graceful skip when labels are missing;
- sample labels may be used for smoke tests only.

---

## 11. Commands

Build candidate queue:

```bash
python scripts/build_human_pairwise_queue.py \
  --output data/health/human_pairwise_queue.jsonl
```

Validate sample labels:

```bash
python scripts/validate_human_pairwise_labels.py \
  --input data/health/human_pairwise_labels_sample.jsonl
```

Evaluate agreement:

```bash
python scripts/evaluate_human_pairwise_agreement.py \
  --labels data/health/human_pairwise_labels_sample.jsonl
```

Run vNext human pairwise suite:

```bash
python scripts/evaluate_track_b_vnext.py --suite human_pairwise
python scripts/evaluate_track_b_vnext.py --all
```

Run tests:

```bash
pytest tests/test_track_b_human_pairwise_pipeline.py -q
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
       tests/test_track_b_human_pairwise_schema.py \
       tests/test_track_b_human_pairwise_pipeline.py -q
```

---

## 12. Acceptance criteria

### Minimum

```text
human_pairwise_queue.jsonl can be generated or skipped with low-sample warning
human_pairwise_labels_sample.jsonl passes validation
validation script runs
agreement script runs
vNext human_pairwise suite runs or gracefully skips
all existing tests pass
```

### Target

```text
>= 50 human label candidates generated
>= 5 sample labels validated
usable labeled pairs >= 20 after real annotation
final_q_accuracy >= 0.60 on first real-labeled sample
at least 5 disagreement examples are reported
```

### Promotion threshold

PairwiseRanker can be considered for stronger scoring influence only when:

```text
real replay usable pairs >= 100
final_q_accuracy >= 0.70
learned_rank_q_accuracy >= 0.65
clean false positive <= 15%
bad false negative <= 15%
inter-annotator agreement is measured
```

Until then, report:

```text
human pairwise pipeline is ready; real replay labels pending
```

---

## 13. Reporting language

Allowed conclusion before real labels:

```text
The human pairwise validation pipeline is implemented and ready for annotation.
```

Not allowed before real labels:

```text
PairwiseRanker is validated on human judgment.
```

Allowed conclusion after first small labeled batch:

```text
Initial human pairwise validation is directionally positive but low-sample.
```

Not allowed after small batch:

```text
PairwiseRanker is fully reliable.
```
