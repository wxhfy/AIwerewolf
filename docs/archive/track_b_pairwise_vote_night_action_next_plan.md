# Track B Pairwise Vote and Night-Action Next Plan

> Status after VoteQualityFeatures + NightActionTargetValueFeatures repair.
>
> Current conclusion: PairwiseLogisticRanker has improved from speech-only auxiliary to broader auxiliary, but it is still not ready to be the primary scoring source.

---

## 1. Current status

Recent repair added:

- vote quality features;
- night-action target-value features;
- default feature registration;
- tests for vote/night-action feature deltas.

Latest test status:

```text
69 tests passed
hard_cap_count = 0
```

Observed improvements:

| Metric | Before | After | Notes |
|---|---:|---:|---|
| total features | 51 | 71 | +20 vote/night-action features |
| used features | 7 | 25 | more learnable signal |
| valid pairs | 12 | 16 | +33% |
| degenerate pairs | 12 | 8 | -33% |
| vote degenerate rate | 100% | 65% | improved but still high |
| night-action degenerate rate | unknown | 0% | fixed for current fixture set |
| speech degenerate rate | 20% | 20% | stable |
| E_full_v3 gap | 0.197 | 0.197 | stable |

Current interpretation:

```text
PairwiseLogisticRanker can now be used as a broader auxiliary signal.
It should still not be used as the primary scoring source because vote pairs remain mostly degenerate.
```

---

## 2. What is fixed

### 2.1 Ranker direction

Direction tests pass. The ranker is not failing because labels are reversed.

### 2.2 Speech pair learning

Speech pairs have useful signal. Learned weights have sensible direction:

- `speech_grounding_score` positive;
- `role_goal_conflict_score` negative;
- `wolf_perspective_leak_score` negative.

### 2.3 Night-action pair feature deltas

Night-action pairs now produce non-zero deltas. Target-value features are useful for target ranking.

### 2.4 Vote pair partial repair

Vote degenerate rate fell from 100% to 65% after selecting more informative vote examples and adding vote features. This proves the feature path works, but the dataset still lacks enough vote diversity.

---

## 3. Remaining blocker

The main blocker is still vote-pair quality.

```text
vote degenerate rate = 65%
```

This means many vote good/bad pairs still look identical to the feature registry.

Likely causes:

1. pair generation still produces same target or strategically equivalent vote context;
2. vote features do not yet encode enough stance/evidence/wagon context;
3. clean/good vote examples are too narrow;
4. `vote_coordination_failure` is still too coarse;
5. pairwise training has too few effective vote examples.

---

## 4. Next target

Move PairwiseRanker from:

```text
broader auxiliary signal
```

to:

```text
stable auxiliary signal across speech, vote, and night action
```

Do not promote it to primary scoring until the following are met:

```text
vote degenerate rate <= 20%
night-action degenerate rate <= 20%
heldout pairwise accuracy >= 0.65
validation pairwise accuracy >= 0.70
effective pair count >= 80
hard_cap_count = 0
```

---

## 5. Phase A: Vote pair generation repair

### Goal

Create vote pair examples where better/worse choices differ in strategic meaning, not just in label.

### Add vote pair templates

Generate at least 80 vote pairs across these categories:

| Pair type | Minimum pairs | Lower-quality example | Higher-quality example |
|---|---:|---|---|
| wolf_split_vote | 15 | team scatters votes and fails to protect role objective | coordinated vote or strategic bus |
| wolf_bad_overprotection_vote | 10 | vote to over-protect exposed teammate with no route | cut exposed teammate |
| wolf_good_bus_vote | 10 | waste vote away from exposed teammate | bus exposed teammate to reduce linkage |
| wolf_wagon_building | 10 | lone vote on low-value target | join/build wagon on high-value opposing target |
| village_known_wolf_vote | 10 | vote away from public checked wolf | vote checked wolf |
| seer_private_info_vote | 10 | seer votes away from private known wolf | seer votes known wolf |
| speech_vote_consistency | 10 | vote contradicts own stated target | vote matches prior stated target |
| evidence_based_vote | 5 | vote without public evidence | vote supported by public claim/tell |

### Requirements

For every generated pair:

- same role;
- same day/phase;
- similar public context;
- different vote target or different strategic vote meaning;
- no direct player-id shortcut feature;
- include `reason`;
- include `pair_type`;
- include `same_context=true` where valid.

### Output

```text
data/health/pairwise_vote_expansion_examples.jsonl
```

---

## 6. Phase B: Improve VoteQualityFeatures

Add or strengthen these vote features:

1. `vote_target_pressure_score`
   - how much public pressure the target has.

2. `vote_target_public_claimed_role_value`
   - whether target has publicly claimed seer/witch/guard/hunter.

3. `vote_public_checked_wolf_target`
   - public evidence says target is wolf.

4. `vote_away_from_public_checked_wolf`
   - public checked wolf exists but actor votes elsewhere.

5. `vote_private_known_wolf_target`
   - private info says target is wolf.

6. `vote_away_from_private_known_wolf`
   - actor knows a wolf privately but votes elsewhere.

7. `vote_prior_speech_target_match`
   - vote target matches actor's prior speech target.

8. `vote_prior_speech_target_conflict`
   - vote contradicts actor's prior speech target.

9. `vote_wagon_effectiveness_score`
   - vote contributes to plausible elimination.

10. `vote_strategic_bus_score`
   - wolf votes exposed teammate in a strategically reasonable cut.

11. `vote_bad_save_teammate_score`
   - wolf votes to save exposed teammate when no plausible route exists.

12. `vote_coordination_context_score`
   - improved coordination score that accounts for whether coordination is actually strategically desirable.

### Key rule

Do not treat all wolf vote splitting as bad.

Examples that should not be penalized automatically:

- strategic bus of a checked teammate;
- deepwolf avoiding over-coordination;
- endgame vote consistent with prior stance;
- split vote used to avoid linkage when teammate is doomed.

---

## 7. Phase C: Night-action pair expansion

Night-action degenerate rate is currently 0%, but sample coverage is still narrow.

Add at least 40 night-action target pairs:

| Pair type | Minimum pairs | Lower-quality | Higher-quality |
|---|---:|---|---|
| exposed_seer_alive | 10 | select low-value villager | select exposed seer |
| exposed_witch_alive | 8 | select low-value villager | select witch |
| guard_context | 6 | select likely protected target | select lower-risk high-value target |
| narrative_consistency | 6 | selection contradicts public stance | selection supports next-day narrative |
| endgame_vote_math | 5 | select low-impact player | select swing vote / confirmed good |
| low_info_night | 5 | arbitrary villager selection | high-influence speaker selection |

Output:

```text
data/health/pairwise_night_action_expansion_examples.jsonl
```

---

## 8. Phase D: Effective pair metrics

Update pairwise debug to always report:

```text
total_pair_count
effective_pair_count
degenerate_pair_count
degenerate_pair_rate
effective_pair_count_by_type
degenerate_pair_rate_by_type
median_abs_delta_by_type
top_delta_features_by_type
zero_variance_feature_count_by_type
```

A pair should be considered effective if:

```text
mean_abs_feature_delta > epsilon
```

and at least one non-ID strategic feature differs.

---

## 9. Phase E: Per-action auxiliary rankers

Do not rely only on one global PairwiseLogisticRanker.

Add optional per-action rankers:

```text
SpeechPairwiseRanker
VotePairwiseRanker
NightActionPairwiseRanker
SkillPairwiseRanker
```

MVP implementation can reuse `PairwiseLogisticRanker` with filtered training data.

Report:

```text
ranker_type
pair_type_count
validation_acc
heldout_acc
low_sample
```

Use global ranker only when per-action sample count is too low.

---

## 10. Phase F: Evaluation gates

After expansion, rerun:

```bash
python scripts/evaluate_track_b_vnext.py --suite pairwise_debug
python scripts/evaluate_track_b_vnext.py --suite pairwise
python scripts/evaluate_track_b_vnext.py --suite opportunity
python scripts/evaluate_track_b_vnext.py --suite ablation
python scripts/evaluate_track_b_vnext.py --all
```

Expected improvements:

| Metric | Current | Target |
|---|---:|---:|
| vote degenerate rate | 65% | <= 20% |
| night-action degenerate rate | 0% | <= 20% |
| valid pairs | 16 | >= 80 |
| used features | 25 | >= 30 |
| validation_acc | variable | >= 0.70 |
| heldout_acc | variable | >= 0.65 |
| hard_cap_count | 0 | 0 |

---

## 11. Required tests

Add or update:

```text
tests/test_track_b_vote_pair_expansion.py
tests/test_track_b_night_action_pair_expansion.py
tests/test_track_b_pairwise_effective_pairs.py
tests/test_track_b_per_action_rankers.py
```

Minimum assertions:

1. vote expansion generates at least 80 pairs;
2. night-action expansion generates at least 40 pairs;
3. vote degenerate rate is below 30% in generated data;
4. night-action degenerate rate is below 20% in generated data;
5. no player-id shortcut fields are used;
6. effective pair metrics are written;
7. per-action ranker training runs without failure;
8. hard_cap_count remains 0.

---

## 12. Reporting

Update:

```text
docs/pairwise_ranker_debug_report.md
docs/track_b_vnext_eval_report.md
```

Add new report:

```text
docs/track_b_pairwise_vote_night_action_expansion_report.md
```

Report must include:

- vote pair expansion counts;
- night-action pair expansion counts;
- degenerate rate before/after;
- effective pair count;
- top learned vote features;
- top learned night-action features;
- per-action ranker metrics;
- whether PairwiseRanker can remain broader auxiliary;
- whether it can be promoted to primary scoring.

Expected answer for now is likely:

```text
PairwiseRanker remains auxiliary, but now covers speech, vote, and night action with lower degeneracy.
```

Do not promote to primary scoring until real replay human pairwise validation exists.

---

## 13. Success criteria

### Minimum

```text
vote degenerate rate <= 30%
night-action degenerate rate <= 20%
effective_pair_count >= 60
hard_cap_count = 0
all existing tests pass
```

### Target

```text
vote degenerate rate <= 20%
night-action degenerate rate <= 20%
effective_pair_count >= 80
validation_acc >= 0.70
heldout_acc >= 0.65
per-action vote ranker accuracy >= 0.65
per-action night-action ranker accuracy >= 0.70
```

### Promotion threshold

PairwiseRanker can affect main ProcessScore only when:

```text
real replay pairwise labels exist
heldout_acc >= 0.70
clean false positive <= 15%
bad false negative <= 15%
calibration_dependency <= 30%
```

Until then, use it as an auxiliary signal only.
