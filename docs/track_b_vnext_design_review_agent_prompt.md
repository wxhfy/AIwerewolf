# Track B vNext Design Review Agent Prompt

> Give this document to a fresh local agent. The task is a design review, not a metric-only audit.
>
> Target branch: `track-b-vnext-scoring`
>
> Expected output: `docs/track_b_vnext_design_review.md`

---

## 1. Task Goal

You are reviewing the `track-b-vnext-scoring` branch in the `wxhfy/AIwerewolf` repository.

This is **not** a task to add new features. This is **not** a task to only run tests. This is a design review of Track B vNext scoring.

The goal is to answer:

1. Is Track B still moving in the right direction?
2. Is the scoring system becoming more accurate and more learnable, or just more complex?
3. Is PairwiseRanker being used safely as an auxiliary signal, or has it been over-promoted?
4. Does the system still follow the principle of dynamic learning instead of hard-rule scoring?
5. Is this branch suitable to become the new base for future Track B work?

---

## 2. Project Background

Track B is intended to evaluate AI Werewolf agent decision quality.

It should not only count win/loss. It should evaluate process quality:

- speech quality;
- vote quality;
- skill/action quality;
- night-action target quality;
- private information release;
- role-objective alignment;
- key mistake localization;
- counterfactual review;
- structured reports;
- future leaderboard support across agent/model versions.

The scoring philosophy is:

```text
visible context + role objective + action opportunity
  -> dynamic features
  -> learned / pairwise / ranker signals
  -> bounded score contribution
  -> reviewable process score
```

The system should avoid turning into:

- a pile of hard-coded rules;
- a synthetic fixture overfitting system;
- a scoring system whose final score cannot be explained;
- a test-heavy framework with weak real replay reliability.

---

## 3. Current Branch Summary

The branch reportedly adds or changes:

- `backend/eval/features/`
  - feature registry;
  - base features;
  - private-context features;
  - vote quality features;
  - night-action / target-value features.
- `backend/eval/pairwise_ranker.py`
  - `PairwiseLogisticRanker`;
  - per-action rankers;
  - `RankerConfidenceGate`;
  - bounded contribution logic.
- `backend/eval/process_score_v3.py`
  - `ProcessScoreV3`;
  - `GameEvaluationValue`.
- `backend/eval/human_label_validator.py`
  - human pairwise label validation.
- scripts:
  - `run_pipeline.py`;
  - `evaluate_track_b_vnext.py`;
  - human pairwise queue / validation / agreement scripts if present.
- tests:
  - BadCase / CleanCase / Generalization Matrix;
  - model loading;
  - learning refactor;
  - pairwise direction;
  - vote/night-action features;
  - pairwise expansion;
  - ranker contribution;
  - human label schema / pipeline.
- docs:
  - Track B reports and plans.
- `data/health/`:
  - models, pairwise examples, label templates, reports.

Reported latest status:

```text
95 tests passed
PairwiseRanker = stable auxiliary signal
PairwiseRanker is not primary scoring source
Human pairwise pipeline ready, real labels pending
```

Do not assume the report is correct. Verify the design.

---

## 4. Files to Review

Read these files first if they exist.

### Core scoring

```text
backend/eval/scoring_models.py
backend/eval/process_score_v3.py
backend/eval/pairwise_ranker.py
backend/eval/review.py
backend/eval/track_b.py
```

### Feature system

```text
backend/eval/features/registry.py
backend/eval/features/base.py
backend/eval/features/private_context.py
backend/eval/features/vote.py
backend/eval/features/kill.py
```

If `kill.py` does not exist, locate the night-action / target-value feature extractor.

### Human label pipeline

```text
backend/eval/human_label_validator.py
data/health/human_pairwise_labels_template.jsonl
```

### Pipelines and evaluation scripts

```text
scripts/run_pipeline.py
scripts/evaluate_track_b_vnext.py
scripts/build_human_pairwise_queue.py
scripts/evaluate_human_pairwise_agreement.py
scripts/validate_human_pairwise_labels.py
```

Some scripts may not exist. If a file is missing, write that in the report.

### Tests

```text
tests/test_track_b_badcase_regression.py
tests/test_track_b_badcase_wolf_regression.py
tests/test_track_b_cleancase_wolf_regression.py
tests/test_track_b_generalization_matrix.py
tests/test_track_b_learning_refactor.py
tests/test_pairwise_ranker_direction.py
tests/test_track_b_vote_kill_features.py
tests/test_track_b_pairwise_expansion.py
tests/test_track_b_ranker_contribution.py
tests/test_track_b_human_pairwise_schema.py
tests/test_track_b_vnext_evaluation.py
```

### Docs

```text
docs/track_b_learning_first_refactor_plan.md
docs/track_b_vnext_eval_report.md
docs/pairwise_ranker_debug_report.md
docs/track_b_ranker_contribution_and_human_label_plan.md
docs/track_b_real_replay_human_pairwise_plan.md
```

---

## 5. Core Review Questions

### 5.1 Has Track B drifted from its goal?

Judge whether the current system still serves:

- agent decision-quality evaluation;
- role-objective alignment;
- visible-information-based decision assessment;
- key decision review;
- future model/agent leaderboard.

Or whether it has become:

- an over-engineered test harness;
- a synthetic fixture scoring system;
- a feature/report pile with unclear final score meaning;
- a system that is complex but not more reliable.

Choose one:

```text
NO_DRIFT
MINOR_DRIFT
MAJOR_DRIFT
SEVERE_DRIFT
```

Explain your reasoning.

---

### 5.2 Is the scoring flow clear?

Reconstruct the actual score path in the code.

Expected conceptual path:

```text
Game / Replay
  -> DecisionOpportunity
  -> FeatureRegistry
  -> raw_model_q
  -> calibrated_q
  -> learned_rank_q
  -> RankerConfidenceGate
  -> final_q
  -> ProcessScoreV3
  -> Report / Leaderboard
```

Check whether these terms are clearly separated:

- `raw_model_q`;
- `calibrated_q`;
- `learned_rank_q`;
- `final_q`;
- `process_score_v2`;
- `process_score_v3`;
- legacy score;
- leaderboard score.

Look for problems:

- `learned_rank_q` overwrites `calibrated_q`;
- final score source is ambiguous;
- process v2/v3/legacy are mixed without naming clarity;
- ranker/calibration/badcase penalties duplicate the same effect;
- the report cannot explain where a final score came from.

---

### 5.3 Is PairwiseRanker used correctly?

Review:

- `PairwiseLogisticRanker`;
- per-action rankers;
- `RankerConfidenceGate`;
- contribution formula;
- tests and reports.

Answer:

1. Is PairwiseRanker currently auxiliary, primary, or debug-only?
2. Is the confidence gate implemented conservatively enough?
3. Are weights `0.05 / 0.10 / 0.15` reasonable?
4. Is vote ranker blocked or downweighted when degeneracy is high?
5. Is learned-rank contribution bounded?
6. Should ranker currently affect `final_q`, or only audit output?

Choose a recommendation:

```text
KEEP_AS_IS
LOWER_WEIGHTS
AUDIT_ONLY_UNTIL_REAL_LABELS
SIMPLIFY_RANKER
BLOCK_PRIMARY_USE
```

Explain why.

---

### 5.4 Is FeatureRegistry useful or over-complex?

Review:

- feature count;
- feature provenance;
- feature overlap;
- readability;
- generalization risk;
- player-id / seat shortcut risk;
- hidden-information leakage risk.

Pay special attention to:

- `VoteQualityFeatures`;
- night-action target-value features;
- `PrivateContextFeatures`;
- wolf-specific features;
- `role_goal_conflict_score`;
- `vote_coordination_failure`;
- `vote_strategic_bus_score`;
- `kill_target_value_gap` or equivalent.

Classify important features as:

```text
KEEP
MERGE
EXPERIMENTAL
REMOVE_OR_REWRITE
```

---

### 5.5 Is there hard-rule regression?

Hard rules are acceptable for:

- game legality;
- schema validation;
- information isolation;
- impossible actions;
- parse/fallback handling.

Hard rules are risky for:

- speech quality;
- vote quality;
- night-action target quality;
- skill/action quality;
- role strategy quality.

Search for patterns such as:

```text
min(q, ...)
max penalty
q = fixed value
hard_cap
forced score
keyword -> fixed low score
BadCase -> fixed cap
```

Answer:

1. Is hard-rule scoring returning?
2. Which files contain it?
3. Is it legality/safety logic or quality-scoring logic?
4. Must it be fixed before merge?

---

### 5.6 Is validation over-dependent on synthetic fixtures?

Judge whether current evidence comes mostly from:

- BadCase;
- CleanCase;
- Generalization Matrix;
- synthetic pairwise examples.

Check whether there are actual real-replay human labels.

If real labels are missing, the report must say:

```text
Current validation proves controlled validation, not real replay scoring reliability.
```

Also check:

- pairwise examples are diverse or templated;
- vote/night-action expansions are strategically varied;
- human label pipeline is only a schema or has real annotations;
- docs overclaim human validation.

---

### 5.7 Is ProcessScoreV3 ready to be the current process score?

Review:

- formula;
- with-ranker / without-ranker outputs;
- confidence interval;
- low-sample warnings;
- role normalization;
- effect of ranker contribution;
- suitability for leaderboard.

Choose one:

```text
PRIMARY_CURRENT_SCORE
EXPERIMENTAL_ALONGSIDE_LEGACY
KEEP_LEGACY_PRIMARY
REWORK_REQUIRED
```

Explain the choice.

---

### 5.8 Does GameEvaluationValue add value?

Review whether `GameEvaluationValue` actually helps classify game usage:

- badcase training;
- clean benchmark;
- pairwise training;
- leaderboard evaluation;
- strategy replay;
- human review.

Judge whether it is:

```text
KEEP
KEEP_AS_REPORT_HELPER
EXPERIMENTAL_ONLY
REMOVE_FOR_NOW
```

Explain whether it is currently meaningful or just rule-based categorization.

---

### 5.9 Is the human label pipeline correct?

Review:

- schema;
- validator;
- sample labels;
- queue builder if present;
- agreement evaluator if present.

Check that it supports:

- `A_BETTER`;
- `B_BETTER`;
- `TIE`;
- `UNCERTAIN`;
- visible public context;
- visible private context;
- reason field;
- evidence event IDs;
- multiple annotators;
- future inter-annotator agreement.

Check that it prevents:

- hidden/future information in PreAction labeling;
- empty reasons;
- pretending sample labels are real validation.

---

### 5.10 Is the branch mergeable?

Choose one:

```text
PASS
PASS_WITH_WARNINGS
BLOCKED
```

Use this standard:

#### PASS

- architecture direction is correct;
- PairwiseRanker is not overused;
- human validation is not overclaimed;
- no obvious hidden-information leakage;
- no hard-rule quality scoring regression.

#### PASS_WITH_WARNINGS

- direction is correct;
- real replay labels are pending;
- data/model artifacts may need cleanup;
- PairwiseRanker remains auxiliary;
- some modules may be over-complex but not blocking.

#### BLOCKED

- PairwiseRanker directly becomes primary score;
- `learned_rank_q` overwrites `calibrated_q`;
- quality scores are mostly hard capped;
- PreAction features use future/hidden information;
- docs claim human validation is done without real labels;
- tests depend on non-reproducible large artifacts;
- final score path is too unclear to explain.

---

## 6. Helpful Commands

Use commands if useful, but do not make the report just a command output dump.

```bash
git status
git log --oneline -5
pytest -q
python scripts/evaluate_track_b_vnext.py --all
python scripts/evaluate_track_b_vnext.py --suite ranker_contribution
python scripts/evaluate_track_b_vnext.py --suite human_pairwise
```

Search for risky patterns:

```bash
grep -RInE "min\(.*q|min\(.*score|hard_cap|forced.*score|force.*q|final_q\s*=\s*learned_rank_q|calibrated_q\s*=\s*learned_rank_q" backend/eval scripts || true

grep -RInE "winner|final_result|game_result|actual_role|true_role|after_game|postgame|future" backend/eval/features backend/eval scripts || true

git ls-files "*.pkl" "*.pickle" "*.joblib" "data/health/*" | xargs -r ls -lh
```

Inspect generated reports:

```bash
sed -n '1,220p' docs/track_b_vnext_eval_report.md
sed -n '1,220p' docs/pairwise_ranker_debug_report.md
sed -n '1,220p' docs/track_b_ranker_contribution_and_human_label_plan.md
sed -n '1,220p' docs/track_b_real_replay_human_pairwise_plan.md
```

---

## 7. Required Output

Create this file:

```text
docs/track_b_vnext_design_review.md
```

Use this structure:

```markdown
# Track B vNext Design Review

## 1. Executive Summary

Recommendation: PASS / PASS_WITH_WARNINGS / BLOCKED

One-paragraph summary.

## 2. What This Branch Does Well

- ...

## 3. Main Design Risks

For each risk:

### Risk N: title

- Severity: high / medium / low
- Description:
- Impact:
- Related files:
- Recommendation:

## 4. Scoring Flow Review

Explain the actual score path.

State whether raw_model_q / calibrated_q / learned_rank_q / final_q / process_score_v3 are clear.

## 5. PairwiseRanker Review

State whether it is primary, auxiliary, or debug.

State whether confidence gates are sufficient.

## 6. Feature System Review

List key features to keep, merge, mark experimental, or remove.

## 7. Hard Rule / Soft Learning Boundary

State whether hard-rule regression exists.

## 8. Synthetic vs Real Replay Validation

State what is validated and what is not.

## 9. ProcessScoreV3 Review

State whether it should be primary, experimental, or alongside legacy.

## 10. GameEvaluationValue Review

State whether it should be kept.

## 11. Human Label Pipeline Review

State whether schema and validation are adequate.

## 12. Merge Recommendation

Recommendation: PASS / PASS_WITH_WARNINGS / BLOCKED

### Must Fix Before Merge

1. ...

### Can Fix After Merge

1. ...

### Should Not Do

1. ...

## 13. Suggested Next Step

Top 3 next actions.
```

---

## 8. Review Tone

Be direct and skeptical.

Do not treat test success as proof of design correctness.

Do not overstate human validation.

Do not recommend new modules unless necessary.

Prefer simplifying and clarifying the scoring path over adding more complexity.

If something cannot be confirmed from code, write:

```text
Unable to confirm from current code; requires manual inspection.
```

---

## 9. Expected Likely Outcome

Based on current branch summary, the likely result may be:

```text
PASS_WITH_WARNINGS
```

Possible warnings:

- real replay human labels are still pending;
- PairwiseRanker is still auxiliary;
- vote ranker may remain weak;
- data/model artifacts in `data/health` may need cleanup;
- synthetic fixture validation remains dominant;
- GameEvaluationValue may still be smoke-level.

Do not force this conclusion. Review the actual code and decide.
