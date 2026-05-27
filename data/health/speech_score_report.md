# SpeechScore Report

**Total speech acts scored**: 813
**Players with speeches**: 392

## Component Averages
| Component | Mean | Description |
|-----------|------|-------------|
| Based on real public events | 24.0 | avg_groundedness |
| Clear accusation/defense/vote guidance | 14.2 | avg_stance_clarity |
| Speech matches later vote | 8.0 | avg_consistency |
| Advances camp objective | 13.6 | avg_strategic_value |
| No private info leaks | 14.9 | avg_information_safety |

## Per-Role Speech Quality
| Role | Players | Avg Quality | Avg Grounded | Avg Stance | Avg Consistency |
|------|---------|-------------|-------------|------------|-----------------|
| Seer | 56 | 76.0 | 24.6 | 14.5 | 8.0 |
| Witch | 56 | 75.3 | 24.1 | 14.4 | 8.0 |
| Guard | 56 | 76.1 | 24.2 | 14.4 | 8.0 |
| Hunter | 56 | 74.7 | 23.7 | 14.1 | 8.0 |
| Werewolf | 112 | 72.6 | 23.7 | 14.0 | 8.0 |
| Villager | 56 | 75.8 | 24.4 | 14.2 | 8.0 |

## Note
- SpeechScore MVP uses rule-based heuristics, not deep learning
- groundedness/stance/consistency/strategic_value/information_safety each 0-25/20/20/20/15
- Total speech_quality range: 0-100