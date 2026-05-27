# Label Quality Report (Phase 2)

**Total labeled**: 215
**Golden cases**: 118
**Real API-labeled**: 97

## Per Role
| Role | Count | Target | Status |
|------|-------|--------|--------|
| Witch | 24 | 100 | NEED 76 |
| Guard | 15 | 100 | NEED 85 |
| Hunter | 131 | 80 | OK |
| Seer | 14 | 70 | NEED 56 |
| Werewolf | 18 | 70 | NEED 52 |
| Villager | 13 | 60 | NEED 47 |

## Per Task Type
| Type | Count |
|------|-------|
| single_action | 167 |
| speech_quality | 45 |
| mistake_severity | 3 |

## Quality Score Distribution
Mean: 61.5
Median: 75.0
Std: 28.2
Min: 0.0, Max: 99.0

## Hunter Golden Cases
| Case Type | Count |
|-----------|-------|
| shot_wolf | 0 |
| shot_good | 0 |
| vote_wolf | 32 |
| vote_good | 76 |
| speech_good | 10 |

## Notes
- Hunter >= 80: OK (golden cases supplemented)
- Golden cases use heuristically-assigned labels from game outcome
- Real API labels for non-Hunter roles