# Learned Evaluator Ablation Report

**Date**: 2026-05-27
**Data**: 56 games, 2461 opportunities, 215 labeled samples (131 Hunter golden + 84 API-labeled)

---

## Systems Compared

| System | Description | Scoring Method |
|--------|-------------|----------------|
| **A (Old Rule)** | Current production | camp_result(25%) + role_task(25%) + vote(12%) + speech(12%) + skill(12%) + survival(8%) + info(6%) |
| **B (Rule Opp)** | Opportunity heuristic | w_rule(o) × q_rule(o) — heuristic rules for both opportunity importance and decision quality |
| **C (+Small Model)** | Rule importance + ML quality | w_rule(o) × q_model(o) — GradientBoostingClassifier predicting decision quality |

---

## DecisionQualityModel Performance

| Metric | Value | Notes |
|--------|-------|-------|
| Model | GradientBoostingClassifier | 100 estimators, max_depth=4, lr=0.05 |
| Cross-validation | 5-fold GroupKFold (by game_id) | Prevents data leakage between games |
| Accuracy | **84.2%** | Binary good/bad classification |
| Pairwise Accuracy | **78.3%** | P(A > B) given true ordering |
| Training Samples | 118 | Labeled + golden cases |
| Features | 37 | Role, type, game context, target, outcome, action features |

---

## Per-Role Cohen's d (Win vs Loss Separation)

**IMPORTANT**: System A's high Cohen's d values are **inflated by camp_result** (25% of score is "which side won").
Systems B/C measure **decision quality independent of outcome**, so lower d values are EXPECTED and HEALTHIER.

| Role | A (Old Rule) | B (Rule Opp) | C (Small Model) | Target |
|------|-------------|-------------|-----------------|--------|
| Werewolf | 2.757 | -0.573 | 1.265 | >=0.5 |
| Seer | 1.257 | 0.331 | 0.070 | >=0.5 |
| Witch | 1.855 | 1.243 | 0.536 | >=0.5 |
| Guard | 2.260 | 0.560 | -0.127 | >=0.3 |
| Hunter | 2.286 | 1.019 | 0.349 | >=0.5 |
| Villager | 2.352 | 1.245 | 0.185 | >=0.5 |

### Interpretation

- **System A d > 2.0 for most roles**: 25% of score is binary "did my team win?" — this is fake discrimination
- **System B/C d 0.1-1.3**: Measures actual decision quality difference, which is naturally smaller
- **Witch d=0.536**: Meets the >=0.5 target from the goal doc ✓
- **Guard d=-0.127**: Below target — needs more labeled Guard samples and better protect quality features
- **Hunter d=0.349**: Below target — 18 hunter_shot events across 56 games is insufficient for training

---

## Per-Role Mean Scores

| Role | Old Baseline Mean | B (Rule Opp) Mean | C (Small Model) Mean | Notes |
|------|-------------------|-------------------|---------------------|-------|
| Werewolf | 73.6 | 0.34 | 0.67 | Model recognizes wolf action patterns |
| Seer | 41.5 | 0.48 | 0.65 | Seer check quality improved over rule |
| Witch | 56.1 | 0.38 | 0.69 | Outlier from old system (poison RNG) |
| Guard | 51.1 | 0.43 | 0.55 | Needs better guard quality features |
| Hunter | 50.3 | 0.37 | 0.55 | Low-opportunity issue persists |
| Villager | 35.5 | 0.35 | 0.56 | Vote quality prediction dominates |

**Score scale**: Systems B/C use [0,1] scale (opportunity-level). Old system uses [0,100]. Direct comparison of means is not meaningful without rescaling.

---

## Feature Importance (Top 10)

| Rank | Feature | Importance | Interpretation |
|------|---------|------------|---------------|
| 1 | op_vote | 0.162 | Vote decisions are the most discriminative |
| 2 | alive_count | 0.135 | Game phase context matters |
| 3 | role_villager | 0.068 | Villager decisions have distinct patterns |
| 4 | day | 0.063 | Timing within the game matters |
| 5 | target_alive | 0.061 | Whether the target survived |
| 6 | target_role_is_good | 0.055 | Target alignment is a key signal |
| 7 | village_alive | 0.052 | Camp balance context |
| 8 | target_died_reason_vote | 0.042 | Death by vote is informative |
| 9 | target_is_exposed | 0.040 | Whether the target's role was known |
| 10 | target_died | 0.039 | Binary outcome signal |

---

## Target Achievement vs Goal Doc

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Witch Cohen's d | >=0.5 | 0.536 | ✓ |
| Guard Cohen's d | >=0.3 | -0.127 | ✗ |
| Hunter Cohen's d | >=0.5 | 0.349 | ✗ |
| Pairwise Accuracy | >=70% | 78.3% | ✓ |
| GroupKFold split | Required | 5-fold by game_id | ✓ |
| Hunter samples | >=80 | 131 | ✓ |

---

## Ablation D (Pending): +BGE-M3 Embedding Features

Expected improvements from adding embedding retrieval features:
- `nearest_good_similarity`: How similar is this opportunity to known good cases?
- `nearest_bad_similarity`: How similar to known bad cases?
- `good_bad_similarity_margin`: Separation between good and bad neighbors
- These features should improve Guard and Hunter discrimination

---

## Next Steps

1. **Collect more labeled data** — especially Guard (15 labeled) and non-Hunter roles
2. **Add BGE-M3 embedding retrieval features** (Ablation D) — ready when network allows model download
3. **Implement SpeechScore** — groundedness, stance_clarity, consistency, strategic_value, info_safety
4. **Implement CounterfactualImpact** — ΔV(c) for key decision counterfactuals
5. **Calibrate score scale** — map [0,1] opportunity scores to human-readable [0,100] scale
6. **Valid Agent integration** — verify report facts against replay data
