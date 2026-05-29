# Track B vNext Evaluation Report
> Generated: 2026-05-29T14:08:36
> Opportunities: 777
> Models: available

## Executive Summary

- **feature**: PASS
- **pairwise**: PASS_WITH_LIMITATIONS
- **opportunity**: PASS
- **process**: PASS
- **game_value**: PASS
- **ablation**: PASS

**Most suites pass with limitations. System is functional but not fully proven.**

## Suite Details

### feature — PASS
- **total_opportunities**: 777
- **feature_extraction_success_rate**: 1.0
- **avg_feature_count**: 55.1
- **feature_provenance_coverage**: 1.0
- **extractor_usage**: {"base_action:v1": 777, "private_context:v2": 777, "vote_quality:v1": 277, "kill_target_value:v1": 44}
- **deterministic_consistency_rate**: 1.0
- **visibility_leak_count**: 0
- **by_action_type**: [10 items]

### pairwise — PASS_WITH_LIMITATIONS
- **total_pairs**: 41
- **train_pairs**: 24
- **val_pairs**: 8
- **heldout_pairs**: 9
- **train_accuracy**: 0.6667
- **validation_accuracy**: 0.25
- **heldout_accuracy**: 0.6667
- **by_pair_type_accuracy**: {"wolf_vote_coordination": 0.2727, "wolf_speech_quality": 0.8333}
- **clean_false_positive_rate**: 0.0
- **bad_false_negative_rate**: 0.0
- **hard_cap_count**: 0
- **ranker_feature_count**: 0
- **Warnings**: ['heldout < 0.70']

### opportunity — PASS
- **by_action_type**: [10 items]
- **overall_good_mean_raw**: 0.9232
- **overall_bad_mean_raw**: 0.5012
- **overall_good_mean_cal**: 0.9153
- **overall_bad_mean_cal**: 0.2038
- **mean_calibrated_gap**: 0.7443

### process — PASS
- **n_players**: 92
- **comparison_table**: [15 items]
- **legacy_mean_gap**: 0.0493
- **v3_mean_gap**: 0.1123
- **v3_has_confidence**: True
- **v3_low_sample_count**: 1

### game_value — PASS
- **test_cases**: [3 items]
- **use_recommendation_accuracy**: 1.0
- **n_cases**: 3

### ablation — PASS
- **systems**: [5 items]
- **hard_cap_count**: 0

## Limitations

- Real replay human labels: NOT available (synthetic fixtures only)
- Speech raw_q: still near ceiling for many cases
- Clean FP rate: may be elevated with limited pairwise data
- Calibration dependency: soft penalties still provide significant adjustment
- Sample sizes: some action types have < 10 labeled examples

## Next Steps

1. Label real replay pairwise preferences (target >=300 pairs)
2. Integrate external speech/deception pretrained features
3. Reduce calibration dependency through more pairwise training
4. Add multi-seed/version LeaderboardV2 evaluation
5. Regular evaluation runs to track metric trends