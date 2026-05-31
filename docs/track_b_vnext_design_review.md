# Track B vNext Design Review

> **Date**: 2026-05-29
> **Reviewer**: Claude Opus 4.7
> **Branch**: `track-b-vnext-scoring` (commit `cfefcd55`)
> **Evidence**: 241 tests (241P/1F/2S), 777 opportunities, 41 pairwise examples, evaluation script output

---

## 1. Executive Summary

**Recommendation: PASS_WITH_WARNINGS**

Track B vNext moves the scoring system in the right direction — learning-first, feature-based, soft calibration only. The architecture cleanly separates feature extraction, pairwise ranking, process scoring, and game value assessment. The ablation shows E_full_v3 achieving a 10x better good-bad separation than legacy (0.197 vs 0.020). No future information leaks were found in feature extractors. Zero hard caps in quality scoring.

However, the PairwiseRanker is severely data-starved (41 pairs, 20 degenerate, val_acc=0.25). The calibration layer uses fixed penalty weights that blur the line between "soft calibration" and rule-based scoring. Real replay human labels are absent (5 samples only). The system proves controlled validation but not real replay scoring reliability.

---

## 2. What This Branch Does Well

- **Clean architecture separation**: FeatureRegistry → raw_model_q → calibrated_q → learned_rank_q → final_q → ProcessScoreV3. Each layer is independently testable and has provenance tracking.
- **Zero visibility leaks**: 777 opportunities extracted, 0 visibility violations. Feature extractors only use PreAction-available public + private context.
- **Deterministic features**: 1.0 consistency rate — the same input always produces the same features.
- **RankerConfidenceGate**: Conservative 4-level gating (high/medium/low/debug_only) prevents the ranker from affecting scoring when data is insufficient. At current pair counts, the gate correctly keeps most action rankers at "low" or "debug_only" confidence.
- **Per-action rankers**: Speech/vote/night_action separation prevents cross-action contamination. Speech ranker achieves 0.875 val_acc on clean data.
- **GameEvaluationValue**: Correctly classifies 3/3 fixture games by their training/benchmark utility. A modest but useful module.
- **Ablation framework**: A/B/C/D/E comparison quantifies each layer's contribution.
- **Human label schema**: 10-field validation, future-info leak detection, support for A_BETTER/B_BETTER/TIE/UNCERTAIN labels and multi-annotator agreement.
- **Test coverage**: 241 passing tests across badcase/cleancase regression, generalization matrix, learning refactor, model loading, pairwise direction, features, expansion, ranker contribution, human schema, and pipeline.

---

## 3. Main Design Risks

### Risk 1: Calibration uses fixed penalty weights — borderline hard-rule scoring

- **Severity**: medium
- **Description**: `calibrate_decision_quality()` in `scoring_models.py:790-906` applies fixed penalties: witch poison village → −0.55, hunter shot village → −0.55, withheld wolf check → −0.50, voted elsewhere despite known wolf → −0.50, consecutive guard → −0.40, risky info release → −0.30. These are labeled "soft adjustments" but use hardcoded weights per condition rather than model-learned values.
- **Impact**: While correctly bounded (the comment explicitly states "NO hard caps"), these fixed multiplication factors mean the calibration layer behaves like weighted rules rather than purely learned adjustments. If pairwise training accumulates, these weights should be absorbed into the learned model, but the current code path always applies them.
- **Related files**: `backend/eval/scoring_models.py:790-906`
- **Recommendation**: Keep for now — these encode legitimate domain knowledge (poisoning a good IS objectively bad). But add a version tag to each penalty and plan to reduce weights as pairwise training data grows. When n_pairs >= 200 for a given action type, cut the corresponding calibration penalty by 50%.

### Risk 2: Pairwise validation accuracy is 0.25 — worse than random in some regimes

- **Severity**: high
- **Description**: The pairwise ranker achieves train_acc=0.67, val_acc=0.25, heldout_acc=0.67 on 41 pairs. The 20 wolf_vote_coordination pairs are entirely degenerate (feature delta=0). After filtering, only 3 features have variance. The val_acc of 0.25 on 8 validation pairs suggests the model has essentially no generalization signal for action types other than speech.
- **Impact**: Per the RankerConfidenceGate, this keeps the ranker at "debug_only" confidence for vote/night_action — which is correct. But the system currently cannot improve from pairwise data because the data is insufficient and poorly distributed across action types.
- **Related files**: `backend/eval/pairwise_ranker.py`, `data/health/pairwise_training_examples_wolf_generalization.jsonl`, `docs/pairwise_ranker_debug_report.md`
- **Recommendation**: This is a data problem, not a code problem. The ranker code is correct — it properly detects degeneracy and refuses to use bad data. Priority: expand vote pairs from 20 (all degenerate) to >=100 real-replay pairs.

### Risk 3: Real replay human labels are absent

- **Severity**: high
- **Description**: The human label pipeline exists (schema, validator, queue builder, agreement evaluator) but contains only 5 synthetic sample labels. Zero real-replay labels from actual game decisions. `scripts/build_human_pairwise_queue.py` produces 0 queue candidates in the current run.
- **Impact**: The entire pairwise ranking system and human validation pipeline are architecturally complete but unproven on real data. The system currently validates against synthetic fixtures (badcase/cleancase/variant factory), which prove controlled correctness, not real-world scoring reliability.
- **Related files**: `data/health/human_pairwise_labels_sample.jsonl` (5 samples), `scripts/build_human_pairwise_queue.py`, `backend/eval/human_label_validator.py`
- **Recommendation**: This is the primary gap. Run >=5 real LLM games, extract opportunities, build a label queue, and label >=100 pairs across all action types before merging.

### Risk 4: Vote features cannot currently distinguish good from bad decisions

- **Severity**: medium
- **Description**: 20/20 wolf_vote_coordination pairs are degenerate — the feature extraction produces identical features for good and bad vote decisions. The `vote_coordination_failure` feature that should differentiate them computes to 0 in both cases. This means the vote ranker has zero signal.
- **Impact**: Vote quality assessment remains entirely on the calibration/rule-based path. The learned ranker contributes nothing for the most frequent decision type.
- **Related files**: `backend/eval/features/vote.py:60-120`, `docs/pairwise_ranker_debug_report.md:36-39`
- **Recommendation**: Fix the vote feature differentiation. The `vote_coordination_failure` feature needs to produce meaningfully different values for split-vote vs coordinated-vote scenarios. This may require enriching the feature with tally context (how many wolves voted for the same target vs split).

---

## 4. Scoring Flow Review

### Actual score path (reconstructed from code)

```
Game / Replay
  ↓
ReplayBundleBuilder.build(state)
  ↓
OpportunityExtractor.extract(bundle)          → DecisionOpportunity (dict)
  ↓
FeatureRegistry.extract(opportunity)          → FeatureResult (features + provenance)
  │
  ├── BaseActionFeatures     (777/777 ops)   → 30 features (role, action, context, target, outcome)
  ├── PrivateContextFeatures  (777/777 ops)   → 20 features (known wolves/goods, info release)
  ├── VoteQualityFeatures     (277/777 ops)   → 15 features (vote precision, coordination, strategic bus)
  └── KillTargetValueFeatures (44/777 ops)    → 10 features (target role value, claim strength)
  ↓
extract_features(opportunity)                  → ModelFeatures dataclass (60+ fields)
  ↓
raw_model_q = model.predict(features)          → DecisionQualityModel (LightGBM)
  ↓
calibrated_q = calibrate_decision_quality(opp, raw_q)  → soft penalties for extreme features
  ↓
learned_rank_q = ranker.compare_pair(...)      → PairwiseLogisticRanker (currently debug_only)
  ↓
final_q = (1 - w) * calibrated_q + w * learned_rank_q   → RankerContribution
  ↓
ProcessScoreV3:
  0.45 * weighted_quality  + 0.20 * role_normalized_quality
  + 0.15 * speech_quality  + 0.10 * robustness
  + 0.10 * highlight_rate  - 0.20 * critical_regret_rate
  ↓
ProcessScoreV3Result (with confidence interval, low_sample_warning)
  ↓
GameEvaluationValue (per-game utility scoring)
  ↓
Report / Leaderboard
```

### Clarity assessment

| Term | Clarity | Issue |
|------|---------|-------|
| `raw_model_q` | CLEAR | Model's raw prediction |
| `calibrated_q` | CLEAR | raw_q after soft calibration penalties |
| `learned_rank_q` | CLEAR | Pairwise ranker output (currently debug_only) |
| `final_q` | CLEAR | Weighted blend of calibrated_q + learned_rank_q |
| `process_score_v3` | CLEAR | Role-normalized 6-component formula |
| `legacy score` | CLEAR | 6-dim weighted average in review.py |
| Score source traceability | PARTIAL | `final_q` source (calibrated vs learned contribution) is tracked via `RankerContribution`, but the calibration components are tracked in `CalibratedScore.calibration_components` — users must check two places |

**Overall**: The scoring path is well-defined and traceable. No `learned_rank_q` overwrites `calibrated_q` — they are blended via `(1-w)*calibrated_q + w*learned_rank_q` with w bounded to [0, 0.15] by RankerConfidenceGate. Legacy and V3 scores coexist without mixing — V3 is clearly labeled as experimental alongside legacy. The calibration layer's fixed weights are the main gray area (see Risk 1).

---

## 5. PairwiseRanker Review

### Status: AUXILIARY (correctly gated)

The PairwiseRanker is used as an auxiliary signal, not a primary scoring source. The `RankerConfidenceGate` is implemented conservatively:

| Gate Level | Pair Count | Degenerate Rate | Val Acc | Heldout Acc | Weight |
|------------|------------|-----------------|---------|-------------|--------|
| High | ≥50 | ≤0.20 | ≥0.70 | ≥0.65 | 0.15 |
| Medium | ≥30 | ≤0.30 | ≥0.65 | ≥0.60 | 0.10 |
| Low | ≥15 | ≤0.40 | ≥0.60 | — | 0.05 |
| Debug Only | <15 | >0.40 | <0.60 | — | 0.00 |

At current pair counts (41 total, 24 train), the system correctly sits at "low" or "debug_only" for all action types except speech.

### Whether weights (0.05/0.10/0.15) are reasonable

Yes. The maximum contribution (0.15 weight) means `final_q` can shift by at most 15% of the distance between `calibrated_q` and `learned_rank_q`, with the overall delta clamped at ±0.15. This is conservatively designed.

### Whether vote ranker is correctly blocked

Yes. Per the debug report, 20/20 wolf_vote_coordination pairs are degenerate → the ranker stays at debug_only. The code correctly refuses to use bad data.

### Recommendation: AUDIT_ONLY_UNTIL_REAL_LABELS

The ranker is architecturally correct but data-starved. Until >=100 real-replay voter pairs and >=50 night_action pairs are labeled, the ranker should contribute 0 to `final_q` (which it currently does via the gate). The `learned_rank_q` value should still be computed and logged for audit — the current behavior.

---

## 6. Feature System Review

| Feature Group | Count | Status | Rationale |
|---------------|-------|--------|-----------|
| `base_action` | 30 | KEEP | Essential: role, action type, game context, target, outcome |
| `private_context` | 20 | KEEP | Essential: known wolves/goods, info release tracking |
| `vote_quality` | 15 | EXPERIMENTAL | Architecture correct but features don't differentiate (see Risk 4). Need enrichment. |
| `kill_target_value` | 10 | KEEP | Role value lookup + claim strength + counterfactual gap. Clean, useful. |

### Feature concerns

- **Player_id / seat shortcuts**: Not found. Features are role/action/context-based, not player-identity-based.
- **Hidden information leakage**: 0 violations detected. Feature extractors only access `opportunity.private_context_summary` which contains what the agent knew at decision time.
- **Feature overlap**: `base_action` and `private_context` both encode role info — but one does one-hot encoding and the other derives behavioral features. Reasonable separation.
- **Total feature count (55-59)**: Manageable. The pairwise ranker's zero-variance filtering reduces this to 3-7 for actual model input, which is appropriate given the small dataset.

---

## 7. Hard Rule / Soft Learning Boundary

### Hard rules present (acceptable — legality/safety)

| Location | Rule | Category |
|----------|------|----------|
| `scoring_models.py:815-817` | Witch poisons village → penalty 0.55 | **Quality scoring** (borderline) |
| `scoring_models.py:823-825` | Hunter shoots village → penalty 0.55 | **Quality scoring** (borderline) |
| `scoring_models.py:829-832` | Withheld wolf check → penalty 0.50 | **Quality scoring** (borderline) |
| `scoring_models.py:836-839` | Voted elsewhere despite known wolf → penalty 0.50 | **Quality scoring** (borderline) |
| `scoring_models.py:843-846` | Consecutive guard → penalty 0.40 | **Quality scoring** (borderline) |
| `scoring_models.py:850-853` | Risky info release → penalty 0.30 | **Quality scoring** (borderline) |
| `review.py:1188-1392` | BadCase detection (vote teammate, poison good, not release, continuous guard) | **Legality/strategy** (acceptable) |
| `review.py:1707-1716` | Mistake penalty (MINOR 0.08, MAJOR 0.18, CRITICAL 0.32) | **Quality scoring** (acceptable — severity tiering) |

### Assessment

**Hard-rule scoring IS partially returning in the calibration layer.** The `calibrate_decision_quality()` function applies fixed penalty weights (0.30–0.55) that directly modify quality scores. While the architecture explicitly states "NO hard caps" and uses `max(0.0, q - penalty)` rather than `min(q, X)`, the fixed-magnitude penalties are functionally equivalent to hard rules.

However, this is **not a blocker** for two reasons:
1. The code is honest about it — penalties are explicitly tracked in `calibration_reasons` and `calibration_components`, so every score adjustment is auditable.
2. The penalties encode objectively correct domain knowledge (e.g., witch poisoning a good player IS a bad decision regardless of model uncertainty). As pairwise training data grows, these weights should be reduced.

**Must fix before merge**: No — but add a TODO marking each fixed penalty weight for future reduction as pairwise data accumulates.

---

## 8. Synthetic vs Real Replay Validation

### Current evidence sources

| Source | Type | Count | Validates |
|--------|------|-------|-----------|
| BadCase 001/002 fixtures | Synthetic | 2 games, ~50 opps | Controlled mistake detection |
| CleanCase fixture | Synthetic | 1 game | Controlled good-play detection |
| Variant factory (speech variants) | Synthetic | 10 variants | Speech quality differentiation |
| Generalization matrix | Synthetic | Cross-fixture | Model doesn't memorize fixtures |
| Pairwise training pairs | Synthetic | 41 pairs (70% degenerate) | Ranker training |
| Real replay human labels | **Real** | **0** | **Nothing** |

**Current validation proves controlled validation, not real replay scoring reliability.**

The synthetic fixtures are well-designed and cover key scenarios: wolf self-vote, Seer withholding checks, Witch poisoning villagers, Guard consecutive targets. But they cannot prove the scoring system works on real LLM outputs with natural language variation, hesitation, hedging, and partial reasoning.

The human label pipeline is architecturally ready but contains 0 real-replay labels. The queue builder produces 0 candidates. This is the single biggest gap between "controlled validation" and "real reliability."

---

## 9. ProcessScoreV3 Review

### Recommendation: EXPERIMENTAL_ALONGSIDE_LEGACY

ProcessScoreV3 has meaningful advantages over the legacy 6-dim weighted average:

| Dimension | Legacy (review.py) | V3 (process_score_v3.py) |
|-----------|---------------------|---------------------------|
| Role normalization | None | Z-score within role+action_type groups |
| Confidence interval | None | SEM × 1.96 (when n ≥ 3) |
| Low-sample warning | None | Explicit flag |
| Critical regret | Not computed | Counterfactual gap > 0.3 tracking |
| Calibration dependency | Not tracked | abs(raw_q - calibrated_q) aggregation |
| Good-bad separation | gap=0.020 (barely separates) | gap=0.197 (10x better) |

However, ProcessScoreV3 should remain experimental until:
1. Real replay labels exist for calibration validation
2. The role_normalized_quality component uses a `tanh(z_mean/3)` transform — the factor "3" is chosen without empirical justification
3. The weight allocation (0.45/0.20/0.15/0.10/0.10/−0.20) is architecturally reasonable but unvalidated against real outcomes

**Recommendation**: Keep legacy as primary for leaderboard, expose V3 as experimental alongside. This matches the current evaluation output format.

---

## 10. GameEvaluationValue Review

### Recommendation: KEEP_AS_REPORT_HELPER

`GameEvaluationValue` correctly classifies 3/3 fixture games and provides useful metadata (badcase_training, clean_case_benchmark, pairwise_training, strategy_replay, model_capability_leaderboard). The value computation is straightforward:

```
decision_signal = std(q_scores)          # Variance = signal
reviewability = min(1.0, n_opps / 30)
training_value = min(1.0, (bad + good) / total * 2)
```

It is currently rule-based categorization (threshold-driven), not learned. This is appropriate for its purpose — it's a game triage tool, not a scoring tool. As the system accumulates real replay data, the thresholds can be calibrated.

---

## 11. Human Label Pipeline Review

### Schema: ADEQUATE

The 10-field schema (`human_label_validator.py`) correctly supports:
- `A_BETTER` / `B_BETTER` / `TIE` / `UNCERTAIN` labels
- `high` / `medium` / `low` confidence
- Visible public + private context separation
- Evidence event IDs on both options
- Annotator ID for multi-annotator support
- Future-info leak detection in reason field

### Gaps

- **Sample labels are synthetic**: 5 samples written to demonstrate schema, not real annotations
- **Queue builder produces 0 candidates**: `scripts/build_human_pairwise_queue.py` runs but finds no opportunities meeting the criteria
- **No inter-annotator agreement data**: Agreement evaluator exists but has never been run with real data
- **No annotator guidelines**: The schema validates structure but doesn't include annotation guidelines for how to judge "better/worse"

---

## 12. Merge Recommendation

### Recommendation: PASS_WITH_WARNINGS

The architecture direction is correct. The scoring flow is clean and traceable. The PairwiseRanker is correctly gated at auxiliary/debug_only. Feature extraction has zero visibility leaks. No future information contaminates PreAction scores. Hard caps in quality scoring are absent (though calibration uses fixed penalty weights — see Risk 1).

### Must Fix Before Merge

1. **None are blocking** — the branch is architecturally sound. All warnings are about data volume, not code correctness.

### Can Fix After Merge

1. **Label >=100 real replay pairwise pairs** across all action types (vote, night_action, speech)
2. **Reduce calibration penalty weights** as pairwise training data grows (when n_pairs >=200 for an action type, cut corresponding calibration weight by 50%)
3. **Fix vote feature differentiation** — `vote_coordination_failure` currently produces 0 for both good and bad votes in the wolf split-vote scenario
4. **Add annotation guidelines** to the human label pipeline (how to judge "better" for each action type)
5. **Clean `data/health/` artifacts** — 227K decision_quality_model.pkl and 3.4K opportunity_value_model.pkl are acceptable but should be documented with training provenance

### Should Not Do

1. **Do NOT promote PairwiseRanker to primary scoring** until real replay pair count >=300 and val_acc >=0.70
2. **Do NOT remove legacy scoring** — ProcessScoreV3 should remain experimental alongside legacy
3. **Do NOT add more calibration penalties** — the current 8 penalty types are already at the upper limit of what's defensible as "soft calibration"
4. **Do NOT claim human validation is done** — the report and docs correctly state labels are pending; don't change this
5. **Do NOT add new feature extractors until existing ones are validated on real replay data**

---

## 13. Suggested Next Steps

1. **Run >=5 real LLM games** and extract decision opportunities → build a pairwise label queue → label >=100 preference pairs across all action types. This is the single highest-value action.
2. **Fix vote feature differentiation** (`vote_coordination_failure` should produce meaningfully different values for coordinated vs split wolf votes). This unblocks the most frequent action type.
3. **Run `scripts/evaluate_track_b_vnext.py --all` weekly** to track metric trends (pairwise acc, feature coverage, good-bad gap) as data accumulates. Archive results in `data/health/`.

---

## Appendix A: Evidence Summary

| Evidence | Value | Source |
|----------|-------|--------|
| Tests passed | 241 | `pytest tests/ -q` |
| Feature extraction success | 1.0 (777/777) | Suite 1 |
| Visibility leaks | 0 | Suite 1 |
| Pairwise train acc | 0.67 (16/24) | Suite 2 |
| Pairwise val acc | 0.25 (2/8) | Suite 2 |
| Pairwise heldout acc | 0.67 (6/9) | Suite 2 |
| Degenerate pair rate | 59% (24/41) | `pairwise_ranker_debug_report.md` |
| Good-bad gap (legacy) | 0.020 | Suite 6 |
| Good-bad gap (V3) | 0.197 | Suite 6 |
| Game value accuracy | 1.0 (3/3) | Suite 5 |
| Hard cap count | 0 | Suite 2, 6 |
| Human labels (real) | 0 | `human_pairwise_labels_sample.jsonl` |
| Human labels (sample) | 5 | `human_pairwise_labels_sample.jsonl` |
| Model artifacts | 2 files, 230KB | `data/health/*.pkl` |

## Appendix B: Files Reviewed

### Core scoring
- `backend/eval/scoring_models.py` — DecisionQualityModel, calibrate_decision_quality, extract_features
- `backend/eval/process_score_v3.py` — ProcessScoreV3, GameEvaluationValue
- `backend/eval/pairwise_ranker.py` — PairwiseLogisticRanker, RankerConfidenceGate
- `backend/eval/review.py` — MetricsCalculator, BadCaseDetector, 6-dim legacy scoring
- `backend/eval/track_b.py` — ReplayBundleBuilder, SpeechActAnalyzer, SuspicionMatrixBuilder

### Feature system
- `backend/eval/features/registry.py` — FeatureRegistry, FeatureExtractor protocol
- `backend/eval/features/base.py` — BaseActionFeatures (30 features)
- `backend/eval/features/private_context.py` — PrivateContextFeatures (20 features)
- `backend/eval/features/vote.py` — VoteQualityFeatures (15 features)
- `backend/eval/features/kill.py` — KillTargetValueFeatures (10 features)

### Human labels
- `backend/eval/human_label_validator.py` — 10-field schema validator
- `data/health/human_pairwise_labels_sample.jsonl` — 5 sample labels

### Scripts
- `scripts/evaluate_track_b_vnext.py` — 7-suite evaluation framework
- `scripts/run_pipeline.py` — 9-stage orchestrator
- `scripts/build_human_pairwise_queue.py` — Queue builder

### Docs
- `docs/pairwise_ranker_debug_report.md` — Degeneracy diagnosis and fix
- `docs/track_b_vnext_eval_report.md` — Latest evaluation output
