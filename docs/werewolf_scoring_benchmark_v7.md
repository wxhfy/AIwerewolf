# Werewolf Scoring Benchmark V7

**Date**: 2026-05-28 · **Gate**: PASS_WITH_LIMITATIONS

> **EXPLORATORY**: Scores are ranking scores, not calibrated probabilities.
> **LOW_CONF**: Witch save, Seer release, Seer check, Hunter shot.

## V1 → V7 Evolution

| Ver | Gate | PaW | ECE | Key Innovation | Remaining Issue |
|---|---|---|---|---|---|
| V1 | PARTIAL_PASS | 0.721 | 0.199 | Rule-based scoring with target_alignment | Post-outcome contamination; Witch d=-0.15; Guard vote d=2.39 |
| V2 | PASS_WITH_LIMITS | 0.763 | 0.294 | Pre/Outcome decomposition; 0 post-outcome violations | VotePreQuality std=0.011; only 1 role-action validated |
| V3 | PASS_WITH_LIMITS | 0.815 | 0.205 | 46 pre-action features from replay events; per-role-action ML | 2 role-actions validated; non-Guard roles sparse |
| V4 | PASS | 0.893 | 0.166 | Hard negative mining + pairwise generation; 11 models trained | Easy negatives rule-generated; Witch/Seer LOW_CONF |
| V5 | PASS_WITH_LIMITS | 0.878 | 0.166 | Dataset normalization; generalization validation; confidence model | Easy neg ratio 0.648; human review 21.6% |
| V6 | PASS_WITH_LIMITS | 0.877 | N/A | Model-assisted review; hard negative rebalance; easy ratio→0.067 | Human review 57.4%; Witch save/Seer release still LOW_CONF |
| V7 | PASS_WITH_LIMITS | 0.877 | N/A | Private-context-aware scoring; 0 visibility violations; 89.5% coverage | Witch save (1 bad label); Seer release (0 bad labels); Hunter shot LOW_CONF |

## Score Decomposition

- **PreActionScore (65%)**: Pre-action features only (public + actor-private)
- **OutcomeImpactScore (20%)**: Post-outcome features, explicitly separated
- **SpeechQualityScore (10%)**: Heuristic, unvalidated
- **RobustnessBonus (5%)**: Feature coverage + evidence support

## V7 Private Context

- Witch: night_attacked_player, save/poison state (from wolf_attack_tally + decisions)
- Seer: checks_history, latest_check_result (from seer_result events)
- Visibility violations: **0**
- Private context coverage: **89.5%** (2203/2461)

## Role-Action Matrix

| Role | Action | n | d | PaW | Status |
|---|---|---|---|---|---|
| Guard | protect | 46 | 0.96 | 0.64 | PASS |
| Guard | vote | 114 | 1.40 | 0.76 | PASS |
| Werewolf | kill | 255 | 0.37 | 0.65 | PASS |
| Werewolf | vote | 225 | 0.95 | 0.76 | PASS |
| Witch | vote | 77 | 0.37 | 0.63 | PASS |
| Villager | vote | 111 | 2.84 | 0.77 | PASS |
| Hunter | vote | 84 | 1.04 | 0.74 | PASS |
| Seer | vote | 29 | 0.99 | 0.83 | PASS |
| Witch | save | 96 | -0.19 | N/A | LOW_CONF |
| Seer | release | 43 | -0.58 | 0.43 | LOW_CONF |
| Seer | check | 12 | N/A | N/A | LOW_CONF |
| Hunter | shot | 12 | N/A | N/A | LOW_CONF |

## Gate V7

- **Post-outcome contamination = 0**: PASS — 0 violations across all versions since V2
- **Visibility violation = 0**: PASS — V7: 0 violations; private context is visibility-safe
- **Test PaW >= 0.85**: PASS — 0.877 (GroupKFold by game_id)
- **Train-test gap <= 0.10**: PASS — 0.053
- **Easy negative ratio <= 0.60**: PASS — 0.067 (V6 rebalance)
- **Human/model-reviewed >= 50%**: PASS — 57.4%
- **Counterfactual exact = 100%**: PASS — Vote flip 100%, Skill swap 100%
- **Valid Agent critical = 0**: PASS — Only hunter_low_confidence (non-critical)
- **Confidence model implemented**: PASS — 6-factor model covering all scores
- **>= 8 role-actions PASS/PARTIAL**: WEAK — 8 PASS, but 4 LOW_CONF
- **Witch save or Seer release PARTIAL**: WEAK — Private context correct, insufficient bad labels
- **Calibration**: WEAK — Scores are RANKING only, NOT probability

## Why Not BENCHMARK_READY

Architecture is complete (0 contamination, 0 visibility violations, PaW=0.877).
Remaining: label sparsity for Witch save (>1 bad label needed), Seer release (>0 bad labels needed).

## Next Steps
1. Label >=10 Witch save bad decisions
2. Label >=10 Seer release bad decisions
3. Run >=20 more games for Hunter shot
4. Replace model-assisted review with human expert review