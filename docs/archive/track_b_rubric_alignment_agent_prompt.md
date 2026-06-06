# Track B Rubric Alignment Agent Prompt

> Give this document to a fresh local agent. The task is to **converge** Track B back to the project rubric, not to add more scoring modules.
>
> Expected output: `docs/track_b_rubric_alignment.md`

---

## 1. Task Goal

You are working in the `wxhfy/AIwerewolf` repository.

Track B has grown a lot: FeatureRegistry, PairwiseRanker, RankerConfidenceGate, ProcessScoreV3, GameEvaluationValue, human label pipeline, many tests, many reports, and many `data/health` artifacts.

The current concern is that the system is becoming too scattered. It may be technically impressive, but the project rubric is much simpler and more concrete:

```text
Multi-dimensional evaluation: speech / vote / skill
  -> key decision review
  -> counterfactual reasoning
  -> structured report
  -> leaderboard
```

This task is to create a convergence document that realigns Track B to that rubric.

Do not add more functionality. Do not add more features. Do not add more rankers. This is a design and prioritization task.

---

## 2. Rubric To Align With

The target rubric has three levels.

### Highest level

```text
Multi-dimensional evaluation: speech / vote / skill
  -> key decision review
  -> counterfactual reasoning
  -> structured report
  -> leaderboard
```

A high-scoring system should:

```text
Construct games with obvious mistakes, precisely locate those mistakes, and provide improvement suggestions.
The leaderboard should distinguish capabilities across different model / agent versions.
```

### Middle level

```text
Basic multi-dimensional scoring and report output exist,
but review depth is insufficient or leaderboard is incomplete.
```

### Lowest level

```text
Only win/loss statistics exist; no multi-dimensional evaluation capability.
```

---

## 3. Current Track B Components

The current system may include:

- `final_q`
- `raw_model_q`
- `calibrated_q`
- `learned_rank_q`
- `process_score_v2`
- `process_score_v3`
- legacy score / MetricsCalculator score
- `role_action_z`
- FeatureRegistry
- BaseActionFeatures
- PrivateContextFeatures
- VoteQualityFeatures
- night-action target features
- PairwiseRanker
- PerActionRankers
- RankerConfidenceGate
- GameEvaluationValue
- BadCase / CleanCase / Generalization Matrix
- human pairwise label pipeline
- many docs/reports/plans
- many `data/health` artifacts

You should classify which of these are part of the rubric mainline and which are support / audit / future work.

---

## 4. Files To Read

Read these files if they exist.

### Core scoring

```text
backend/eval/scoring_models.py
backend/eval/process_score_v3.py
backend/eval/pairwise_ranker.py
backend/eval/review.py
backend/eval/track_b.py
```

### Features

```text
backend/eval/features/registry.py
backend/eval/features/base.py
backend/eval/features/private_context.py
backend/eval/features/vote.py
backend/eval/features/kill.py
```

If `kill.py` does not exist, find the night-action target-value feature file.

### Human labels

```text
backend/eval/human_label_validator.py
data/health/human_pairwise_labels_template.jsonl
```

### Scripts

```text
scripts/run_pipeline.py
scripts/evaluate_track_b_vnext.py
scripts/build_human_pairwise_queue.py
scripts/evaluate_human_pairwise_agreement.py
scripts/validate_human_pairwise_labels.py
```

Some scripts may not exist. If missing, mention that.

### Docs

```text
docs/track_b_vnext_design_review.md
docs/track_b_learning_first_refactor_plan.md
docs/track_b_ranker_contribution_and_human_label_plan.md
docs/track_b_real_replay_human_pairwise_plan.md
docs/track_b_vnext_eval_report.md
```

---

## 5. Non-Goals

Do **not** do these things:

- do not add a new scorer;
- do not add a new feature extractor;
- do not add a new ranker;
- do not expand pairwise data;
- do not modify Track C;
- do not modify frontend UI;
- do not refactor the game engine;
- do not delete existing modules;
- do not promote PairwiseRanker to primary scoring;
- do not claim human validation is complete when only a pipeline or sample labels exist;
- do not treat synthetic fixture validation as real replay reliability;
- do not produce a metrics-only report.

---

## 6. Required Output

Create:

```text
docs/track_b_rubric_alignment.md
```

The document must use the structure below.

---

# Track B Rubric Alignment

## 1. Rubric Restatement

Restate the rubric clearly.

Highest level:

```text
Multi-dimensional evaluation: speech / vote / skill
  -> key decision review
  -> counterfactual reasoning
  -> structured report
  -> leaderboard.

The system can construct games with obvious mistakes, precisely locate those mistakes, and provide improvement suggestions.
The leaderboard can distinguish capabilities across different model / agent versions.
```

Middle level:

```text
Basic multi-dimensional scoring and report output exist,
but review depth is insufficient or leaderboard is incomplete.
```

Lowest level:

```text
Only win/loss statistics exist; no multi-dimensional evaluation capability.
```

---

## 2. Current Track B Capability Against Rubric

Create a table:

```markdown
| Rubric Item | Current Status | Evidence | Gap |
|---|---|---|---|
| Multi-dimensional evaluation | ... | ... | ... |
| Speech scoring | ... | ... | ... |
| Vote scoring | ... | ... | ... |
| Skill / role-action scoring | ... | ... | ... |
| Night-action scoring | ... | ... | ... |
| Key decision review | ... | ... | ... |
| Counterfactual reasoning | ... | ... | ... |
| Structured report | ... | ... | ... |
| Leaderboard | ... | ... | ... |
| Obvious mistake localization | ... | ... | ... |
| Improvement suggestions | ... | ... | ... |
| Agent/model version distinction | ... | ... | ... |
```

Be honest. If something is only supported in controlled fixtures, say so.

---

## 3. Mainline Modules

Define the Track B rubric mainline as only these five modules:

### 3.1 MultiDimensionalScorer

Purpose:

- score speech;
- score vote;
- score skill / role action;
- score night action if applicable.

Canonical output:

```text
OpportunityScore.final_q
```

### 3.2 CriticalDecisionReviewer

Purpose:

- locate key mistakes;
- provide severity;
- attach evidence;
- explain why the decision matters.

### 3.3 CounterfactualReviewer

Purpose:

- provide a better alternative action;
- explain why it is better;
- estimate regret / gap / expected improvement.

### 3.4 StructuredReportGenerator

Purpose:

- output a replay/report that directly answers:
  - who made the mistake;
  - when;
  - what they did;
  - why it was bad;
  - what they should have done instead.

### 3.5 LeaderboardEvaluator

Purpose:

- compare agent/model versions across games;
- use role-normalized process score;
- include sample count and confidence interval;
- avoid ranking based on a single game.

---

## 4. Supporting Modules

Classify these as support, not mainline:

| Module | Role | Mainline or Support | Notes |
|---|---|---|---|
| FeatureRegistry | Converts opportunities to features | Support | Feeds scorer; not a user-facing scoring goal |
| PairwiseRanker | Auxiliary preference signal | Support / audit | Not primary scoring |
| RankerConfidenceGate | Protects final score from weak ranker | Support | Should remain conservative |
| GameEvaluationValue | Classifies game usage | Support / report helper | Does not score player ability |
| Human label pipeline | Future validation/training | Support | Pipeline ready does not mean validation done |
| role_action_z | Normalization/audit | Support | Not final score |
| pairwise expansion data | Controlled training/eval data | Support | Not proof of real reliability |
| BadCase/CleanCase | Regression and controlled validation | Support to mainline | Useful, but not real replay proof |

Add any missing modules found in code.

---

## 5. What Is Overbuilt Or Too Scattered

List areas where Track B currently exceeds the immediate rubric requirement.

Potential items:

- PairwiseRanker is useful but heavier than required for the rubric;
- GameEvaluationValue is useful but not central;
- Human label pipeline is forward-looking but not current rubric proof;
- too many docs/reports/plans;
- too many score fields;
- `data/health` may contain too many intermediate artifacts;
- multiple process scores / legacy scores may confuse agents;
- some feature extractors may be too close to hand-written rules.

For each item, choose an action:

```text
KEEP
DOWNGRADE_TO_AUDIT
ARCHIVE
FUTURE_WORK
MERGE_OR_SIMPLIFY
```

---

## 6. Canonical Scores

Declare the canonical score contract for rubric alignment.

### Primary scores

```text
opportunity.final_q
player.process_score_v3
leaderboard.entry_score   # future multi-game aggregate
```

### Audit-only scores

```text
raw_model_q
calibrated_q
learned_rank_q
role_action_z
process_score_v2
legacy score
MetricsCalculator score
GameEvaluationValue sub-scores
```

### Rule

No new module should create a new primary score without updating this rubric alignment document.

---

## 7. Rubric-Focused Next Work

The next work should focus only on the rubric mainline.

### 7.1 Improve CounterfactualReviewer

Requirements:

- every critical mistake should include at least one better alternative;
- explain why the alternative is better;
- include expected improvement or regret/gap;
- avoid hidden/future information when reviewing PreAction decisions.

### 7.2 Improve StructuredReportGenerator

Requirements:

- generate one full badcase replay report;
- report should be readable without opening debug JSON;
- include multi-dimensional score summary;
- include key mistakes;
- include counterfactual alternatives;
- include improvement suggestions.

### 7.3 Build Minimal LeaderboardEvaluator

Requirements:

- compare at least two agent/model versions;
- run the same seeds or same replay set;
- aggregate `process_score_v3`;
- role-normalize where possible;
- show sample count and confidence interval;
- explicitly mark low sample.

---

## 8. What Not To Do Next

Explicitly say these are not next priorities:

- do not add another ranker;
- do not add another score field;
- do not expand GameEvaluationValue;
- do not keep adding synthetic badcases without leaderboard validation;
- do not let PairwiseRanker dominate `final_q`;
- do not treat the human label pipeline as current validation success;
- do not create another large planning doc before producing a rubric-aligned report.

---

## 9. Current Rubric Level

Answer which level Track B currently satisfies.

Suggested honest framing:

```text
Track B is above the basic multi-dimensional scoring level and is close to the first half of the highest rubric level: it can score multiple decision types and locate obvious mistakes in controlled cases.

It does not yet fully satisfy the highest rubric level because leaderboard-based agent/model version distinction is not complete, and real replay validation remains pending.
```

Adjust if the code evidence says otherwise.

---

## 10. Immediate Action Plan

List exactly three next actions.

Recommended actions:

1. Generate one full structured badcase replay report aligned to the rubric.
2. Implement or consolidate CounterfactualReviewer output for every critical mistake in that report.
3. Run a minimal two-agent-version leaderboard comparison using the same seeds or replay set.

Do not list more than three.

---

## 11. Final Judgment

State the conclusion clearly.

Example:

```text
Track B has overbuilt supporting infrastructure relative to the current rubric. The right next step is not more scoring machinery, but convergence around the rubric mainline: multi-dimensional scoring, critical decision review, counterfactual review, structured reports, and leaderboard comparison.
```

---

## 7. Optional Checks

You may run:

```bash
pytest -q
python scripts/evaluate_track_b_vnext.py --all
```

But the output document should be a design/prioritization document, not a test log.

---

## 8. Final Response

After creating `docs/track_b_rubric_alignment.md`, summarize:

- whether the current system is too scattered;
- which modules are mainline;
- which modules are support/audit;
- what the next three actions are.
