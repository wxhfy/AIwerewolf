# Track B Rubric Alignment

> 生成时间: 2026-05-29
> 基于对 `track-b-vnext-scoring` 分支全部核心源码的审查。
> 本文档目的在于**收敛**，不增加任何新功能。

---

## 1. Rubric Restatement

### 最高级

```
Multi-dimensional evaluation: speech / vote / skill
  -> key decision review
  -> counterfactual reasoning
  -> structured report
  -> leaderboard.

The system can construct games with obvious mistakes, precisely locate those mistakes,
and provide improvement suggestions.
The leaderboard can distinguish capabilities across different model / agent versions.
```

### 中间级

```
Basic multi-dimensional scoring and report output exist,
but review depth is insufficient or leaderboard is incomplete.
```

### 最低级

```
Only win/loss statistics exist; no multi-dimensional evaluation capability.
```

---

## 2. Current Track B Capability Against Rubric

| Rubric Item | Current Status | Evidence | Gap |
|---|---|---|---|
| Multi-dimensional evaluation | **PASS** | 6-dim formula: camp(0.10)+role_task(0.40)+vote(0.20)+speech(0.10)+skill(0.10)+survival(0.10), per-role task formulas | Formula weight tuning needs real-game calibration |
| Speech scoring | **PASS** | `_speech_score()`: mentions + keywords + hit count; `SpeechActAnalyzer`: stance/claim/risk; `compute_speech_scores()`: heuristic with private-info penalties | Heuristic only; no semantic quality model |
| Vote scoring | **PASS** | `_vote_score()`: alignment-based precision; 21 VoteQualityFeatures; vote_coordination_failure detection | Only tested on controlled fixtures |
| Skill / role-action scoring | **PASS_WITH_LIMITATIONS** | Per-role `_skill_score()`: kill_value/check_value/save_value/poison_value/shot_value/guard_value; `_role_task_score()` with per-role decomposition | Guard save detection heuristic; Hunter shot value binary |
| Night-action scoring | **PASS_WITH_LIMITATIONS** | KillTargetValueFeatures (10 features); calibrate_decision_quality penalties for witch_poison/hunter_shot | No real replay night-action label data |
| Key decision review | **PASS** | `BadCaseDetector`: 7 rules (wolf-cross-vote, village-vote-checked-good, witch-poison-village, seer-withhold-wolf, hunter-shot-village, guard-key-protect, wolf-kill-low-value); `TurningPoint` extraction | Rules are static; no learned mistake detection |
| Counterfactual reasoning | **PASS_WITH_LIMITATIONS** | `CounterfactualCase`: local counterfactual with vote_flip/skill/info_release types; `CounterfactualSoundnessGate` validation; effect_type tagging (exact_recalculation/local_recalculation/estimated) | Only vote_flip has recomputed tally; skill/info_release are estimated only |
| Structured report | **PASS** | `MarkdownReportRenderer`: 9-chapter Chinese report; `HTMLReviewRenderer`: SVG visual agent with banner/timeline/heatmap; `ReviewReport` dataclass with typed fields | HTML is impressive but rendering logic is 500+ lines; frontend integration pending |
| Leaderboard | **PASS_WITH_LIMITATIONS** | `LeaderboardAggregator`: persona/role/version aggregates with role-normalized scores, sample counts; `LeaderboardResult` with source_games count | No multi-game CLI runner; aggregation only from ReviewReport metadata; no confidence intervals on leaderboard entries |
| Obvious mistake localization | **PASS** | BadCaseDetector catches: wolf-cross-vote, seer-withhold, witch-poison-town, hunter-shot-town; each with day/player/severity/evidence/fix | Limited to 7 pattern types; no speech-logic mistake detection |
| Improvement suggestions | **PASS** | `StrategySuggestion`: target_type + suggestion + priority + evidence; per-role `suggestions` in PlayerReview | Suggestions are template-based, not LLM-generated |
| Agent/model version distinction | **NOT_YET** | `LeaderboardAggregator.aggregate_version()` exists but reads from metadata fields (`strategy_version`/`agent_version`) that are not reliably populated; no multi-version comparison run | No two versions have been run and compared; purely structural readiness |

### Honest Assessment

**Track B satisfies the "middle level" of the rubric fully, and partially satisfies the "highest level" (first half).**

- Multi-dimensional scoring across speech/vote/skill: **done**
- Key decision review with mistake localization: **done** (7 static rules)
- Counterfactual reasoning with alternatives: **done** (structurally, with validation gates)
- Structured report with Chinese markdown + HTML: **done**
- Leaderboard aggregation: **structurally complete** but **not yet validated with real multi-version data**
- Agent/model version distinction: **not yet demonstrated**

---

## 3. Mainline Modules

Define the Track B rubric mainline as five modules. Everything else is support.

### 3.1 MultiDimensionalScorer

**Current implementation**: `MetricsCalculator._build_player_score()` in `review.py:1507-1577`

Purpose:
- Score speech (mentions + keywords heuristic)
- Score vote (alignment precision)
- Score skill/role action (per-role kill/check/save/poison/shot/guard value)
- Score night action if applicable (kill target value, counterfactual gap)

Canonical output:
```
PlayerScore.final_score (0-100)
PlayerScore.process_score (outcome-independent, 0-100)
```

### 3.2 CriticalDecisionReviewer

**Current implementation**: `BadCaseDetector.detect_bad_cases()` in `review.py:1188-1430`

Purpose:
- Locate key mistakes (7 pattern types across all roles)
- Provide severity (critical/major/minor)
- Attach evidence (event IDs)
- Explain why the decision matters (description + suggested_fix)

Canonical output:
```
BadCaseReport { game_id, day, player_name, role, mistake_type, description, suggested_fix, severity, evidence_event_ids }
```

### 3.3 CounterfactualReviewer

**Current implementation**: `CounterfactualCase` generation + `CounterfactualSoundnessGate` in `review.py:269-291` + `track_b.py:1032-1061`

Purpose:
- Provide a better alternative action
- Explain why it is better
- Estimate regret/gap/expected improvement
- Tag effect_type (exact_recalculation for votes, local_recalculation for skills, estimated for info_release)

Canonical output:
```
CounterfactualCase { case_id, counterfactual_type, original_decision, alternative_decision, expected_effect, effect_type, recomputed_outcome, confidence }
```

### 3.4 StructuredReportGenerator

**Current implementation**: `generate_review_report()` → `MarkdownReportRenderer` + `HTMLReviewRenderer` in `review.py:3191-3408` + `track_b.py:264-637`

Purpose:
- Output a replay/report that directly answers:
  - Who made the mistake
  - When
  - What they did
  - Why it was bad
  - What they should have done instead

Canonical output:
```
PublishedReviewDocument { review_report (JSON) + markdown + html_report }
```

### 3.5 LeaderboardEvaluator

**Current implementation**: `LeaderboardAggregator` in `review.py:3567-3816`

Purpose:
- Compare agent/model versions across games
- Use role-normalized process score
- Include sample count (games_played)
- Include confidence-critical stats (critical_mistakes)

**Current gap**: No confidence intervals on entries; `aggregate_version()` reads from metadata that is not reliably populated.

Canonical output:
```
LeaderboardResult { leaderboard_type, entries: [LeaderboardEntry], source_games, generated_at }
```

---

## 4. Supporting Modules

| Module | Location | Role | Mainline or Support | Notes |
|---|---|---|---|---|
| FeatureRegistry | `features/registry.py` | Converts opportunities to feature vectors | Support | Feeds scorer; not user-facing |
| BaseActionFeatures | `features/base.py` | 30 structural features | Support | Role/action/game-context encoding |
| PrivateContextFeatures | `features/private_context.py` | 20 private-context features + 8 wolf dynamic features | Support | Regex-based known-wolf parsing; feeds calibration |
| VoteQualityFeatures | `features/vote.py` | 21 vote-specific features | Support | Alignment/coordination/evidence features |
| KillTargetValueFeatures | `features/kill.py` | 10 night-kill features | Support | Role value + counterfactual gap |
| ModelFeatures (scoring_models) | `scoring_models.py` | 55+ feature vector for learned models | Support | Duplicates FeatureRegistry features; one should be canonical |
| DecisionQualityModel | `scoring_models.py` | GradientBoostingClassifier for q(o) | Support | Feeds raw_model_q; requires real training data |
| calibrate_decision_quality | `scoring_models.py` | 8 fixed penalty weights | Support | Hardcoded weights (0.55/0.50/0.40 etc.) — borderline "hand-written rule" |
| ProcessScoreV3 | `process_score_v3.py` | Role-normalized z-score + critical regret | Support / audit | Adds value but creates score proliferation |
| PairwiseRanker | `pairwise_ranker.py` | Logistic regression on pairwise differences | Support / audit | Not primary scoring; currently 59% degenerate pairs |
| RankerConfidenceGate | `pairwise_ranker.py` | 4-level gating for ranker contribution | Support | Correctly conservative; protects final_q |
| GameEvaluationValue | `process_score_v3.py` | Game triage for training/eval use | Support / report helper | Does not score player ability |
| ReplayBundleBuilder | `track_b.py` | Converts GameState to structured replay | Support (infra) | Pipeline infrastructure |
| SpeechActAnalyzer | `track_b.py` | Stance/claim/risk analysis | Support | Feeds suspicion matrix + report |
| SuspicionMatrixBuilder | `track_b.py` | Public suspicion tracking | Support | Feeds heatmap + fact consistency |
| TrackBValidator | `track_b.py` | 9+1 Gate validation | Support (quality gate) | Blocking gates prevent bad reports from publishing |
| ReviewRepairLoop | `track_b.py` | Evidence backfill + markdown repair | Support (quality gate) | Auto-fixes minor issues |
| HTMLReviewRenderer | `track_b.py` | SVG visual report agent | Support (presentation) | Impressive but >500 lines |
| Human label pipeline | `human_label_validator.py` + 4 scripts | Schema validation + pairwise labeling | Support (future) | Pipeline ready ≠ validation done |
| data/health/* | 30+ files | Model artifacts, reports, CSVs | Support (artifacts) | Many intermediate artifacts; needs cleanup |
| docs/track_b_*.md | 8+ docs | Design reviews, eval reports, audit docs | Support (docs) | Scattered; some superseded |

---

## 5. What Is Overbuilt Or Too Scattered

| Item | Issue | Action |
|---|---|---|
| **PairwiseRanker + PerActionRankers** | Useful but heavier than rubric requires; 59% degenerate pairs; not needed for baseline scoring | **KEEP as audit** — do not promote to primary scoring |
| **ProcessScoreV3** | Adds role-normalized z-score + critical regret + GameEvaluationValue; creates score proliferation alongside v1/v2/legacy | **DOWNGRADE_TO_AUDIT** — use only for cross-game comparison, not per-game reports |
| **FeatureRegistry + 4 extractors vs ModelFeatures** | Two parallel feature systems: FeatureRegistry (81 features across 4 extractors) and ModelFeatures (55 features in scoring_models.py). Feature names overlap but are not synchronized. | **MERGE_OR_SIMPLIFY** — designate one canonical feature source |
| **GameEvaluationValue** | Game triage is useful but not central to rubric; recommended_use list is speculative without real replay data | **KEEP as report helper** — do not expand |
| **Human label pipeline** | 4 scripts + validator + sample labels; forward-looking but no real labels exist | **KEEP as future work** — explicitly mark as "pipeline ready, data absent" |
| **calibrate_decision_quality()** | 8 fixed penalty weights (0.55, 0.50, 0.40, 0.30, 0.60×leak, 0.65×overprotection, 0.55×vote_failure, 0.75×kill_gap) — these are hand-written rules masquerading as calibration | **KEEP with warning** — reduce weights as training data grows |
| **data/health/ directory** | 30+ files: CSVs, JSONs, PKLs, markdown reports; many from intermediate stages (v1_1, v2, v5, v6, v7) | **ARCHIVE** — keep model PKLs, archive old reports |
| **docs/track_b_*.md** | 8+ docs; some are intermediate design docs superseded by vnext design review | **ARCHIVE** — keep design_review + eval_report + rubric_alignment; archive implementation_audit, model_loading_audit |
| **Multiple process scores** | process_score (v1), process_score_v2, ProcessScoreV3; three formulas with different weights; confusing for agents | **SIMPLIFY** — declare process_score_v3 as canonical for cross-game; keep legacy in review.py for per-game reports |
| **scoring_models.py calculate_process_score + calculate_process_score_v2** | Two process score functions in same file; v1 uses 0.40/0.20/0.15/0.15/0.10 weights; v2 uses 0.55/0.15/0.10/0.10/0.10-0.25cr-0.15mr; neither matches review.py's formula | **KEEP with warning** — add docstring cross-reference; do not add v4 |

---

## 6. Canonical Scores

### Primary scores (rubric-facing)

```
opportunity.final_q          → from MultiDimensionalScorer (per-opportunity)
player.final_score           → from review.py _build_player_score (per-player, per-game, 0-100)
player.process_score          → from review.py (outcome-independent, 0-100)
leaderboard.avg_adjusted_final_score → from LeaderboardAggregator (multi-game aggregate)
```

### Audit-only scores (not rubric-facing)

```
raw_model_q           → DecisionQualityModel.predict()
calibrated_q          → calibrate_decision_quality()
learned_rank_q        → PairwiseRanker.predict_rank()
process_score_v3      → ProcessScoreV3 (cross-game comparison)
role_action_z          → ProcessScoreV3 role-normalized z-score
process_score (v1)     → scoring_models.calculate_process_score()
process_score_v2       → scoring_models.calculate_process_score_v2()
GameEvaluationValue sub-scores  → decision_signal, reviewability, training_value, etc.
```

### Rule

No new module should create a new primary score without updating this document.

---

## 7. Rubric-Focused Next Work

Three actions only:

### 7.1 Generate One Full Structured Badcase Replay Report

**Current gap**: The pipeline (`generate_published_review_document`) exists but has only been run on test fixtures. No real LLM game has produced a complete PublishedReviewDocument with HTML.

**Action**:
- Run one real LLM game (6-player, wolfcha rules)
- Pass through the full pipeline: `ReplayBundleBuilder` → `generate_review_report` → `TrackBValidator` → `ReviewRepairLoop` → `HTMLReviewRenderer`
- Save the output as `data/health/sample_real_replay_report.json` + `.html`
- Verify the HTML renders correctly in a browser

### 7.2 Consolidate CounterfactualReviewer Output

**Current gap**: Counterfactuals exist in `ReviewReport.counterfactuals` but:
- Only vote_flip has `exact_recalculation` with `recomputed_outcome.new_tally`
- Skill counterfactuals have no recomputed outcome
- Info_release counterfactuals are estimated only
- No counterfactual connects to `process_score` impact

**Action**:
- For every `BadCaseReport` with severity=critical, ensure at least one `CounterfactualCase` exists
- For vote_flip counterfactuals: verify `recomputed_outcome` is populated
- For skill counterfactuals: add at minimum `expected_effect` with estimated score delta
- Link counterfactual to the source BadCaseReport via `source_bad_case_id`

### 7.3 Run a Minimal Two-Agent-Version Leaderboard Comparison

**Current gap**: `LeaderboardAggregator.aggregate_version()` reads `strategy_version`/`agent_version` from metadata, but no two versions have been run and compared. The leaderboard is structurally ready but unvalidated.

**Action**:
- Run 3 games with heuristic agent ("baseline")
- Run 3 games with LLM agent (same seeds or same role assignments for fairness)
- Aggregate via `LeaderboardAggregator.aggregate_version()`
- Verify `LeaderboardResult` shows distinguishable scores between versions
- Document result in `docs/track_b_leaderboard_smoke_test.md`

---

## 8. What Not To Do Next

Explicitly NOT next priorities:

- Do NOT add another ranker (PairwiseRanker is sufficient as audit tool)
- Do NOT add another score field (final_score + process_score is sufficient)
- Do NOT expand GameEvaluationValue (it works for triage)
- Do NOT add synthetic badcases without leaderboard validation
- Do NOT let PairwiseRanker dominate `final_q` (gate correctly prevents this)
- Do NOT treat the human label pipeline as current validation success
- Do NOT create another large planning doc before producing a rubric-aligned report
- Do NOT add a new feature extractor (81 features across 4 extractors is enough)
- Do NOT delete existing modules (they work; just downgrade to support)

---

## 9. Current Rubric Level

**Track B is at the "middle level" of the rubric and partially into the "highest level."**

It exceeds the middle level because:
- Multi-dimensional scoring (speech/vote/skill/night-action) is implemented and tested on fixtures
- Key decision review with mistake localization works for 7 pattern types
- Counterfactual reasoning is structurally complete with validation gates
- Structured reports (Chinese markdown + HTML with SVG visuals) are generated

It does NOT yet fully satisfy the highest level because:
- Leaderboard-based agent/model version distinction is structurally ready but **not yet demonstrated with real multi-version data**
- Real replay validation remains pending (only controlled fixtures tested)
- Mistake localization is limited to 7 static patterns; does not detect speech-logic errors

The gap from "middle" to "highest" is **not about missing scoring machinery** — it's about **validating existing machinery on real LLM games** and **demonstrating version distinction on a leaderboard**.

---

## 10. Immediate Action Plan

1. **Generate one real LLM game replay report** (full pipeline: game → bundle → review → validate → repair → HTML).
2. **Ensure every critical BadCase has a linked CounterfactualCase** with explicit expected_effect and, for vote_flip, recomputed tally.
3. **Run 3+3 games (heuristic vs LLM agent) and produce a version-comparison leaderboard** showing distinguishable scores.

---

## 11. Final Judgment

Track B has overbuilt supporting infrastructure (FeatureRegistry, PairwiseRanker, ProcessScoreV3, human label pipeline) relative to the current rubric, while the rubric mainline (MultiDimensionalScorer, CriticalDecisionReviewer, CounterfactualReviewer, StructuredReportGenerator, LeaderboardEvaluator) is functionally complete but under-validated.

The right next step is **not more scoring machinery**, but **convergence**: validate the existing mainline on real LLM games, link counterfactuals to badcases, and demonstrate that the leaderboard can distinguish between agent versions.

The system is architecturally sound. It needs **validation**, not **expansion**.
