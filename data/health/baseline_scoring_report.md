# Track B Baseline Scoring Report (Phase 0)

**Generated**: 2026-05-27
**Data**: 56 clean LLM games, 392 player scores (6-player config × 56)
**Scoring System**: Old Rule-Based (v1)

---

## 1. Overall Metrics

| Role     | N   | Win%  | Rule Mean | Rule SD | Adj Mean | Adj SD | Impact | Penalty |
|----------|-----|-------|-----------|---------|----------|--------|--------|---------|
| Guard    | 56  | 50.0% | 48.7      | 21.7    | 51.1     | 22.5   | 2.0    | 0.0     |
| Hunter   | 56  | 50.0% | 49.5      | 25.2    | 50.3     | 26.1   | 0.8    | 0.0     |
| Seer     | 56  | 50.0% | 42.1      | 18.2    | 41.5     | 18.0   | 0.1    | 0.8     |
| Villager | 56  | 50.0% | 34.8      | 26.1    | 35.5     | 27.1   | 0.6    | 0.3     |
| Werewolf | 112 | 50.0% | 72.7      | 18.1    | 73.6     | 19.0   | 1.0    | 0.0     |
| Witch    | 56  | 50.0% | 53.2      | 30.2    | 56.1     | 31.6   | 3.2    | 0.1     |

## 2. Good/Bad Separation (Winner vs Loser)

| Role     | Good Mean | Bad Mean | Mean Diff | Cohen's d | Welch p | Verdict |
|----------|-----------|----------|-----------|-----------|---------|---------|
| Guard    | 67.9      | 34.3     | 33.6      | 2.260     | <0.0001 | ✓       |
| Hunter   | 69.9      | 30.7     | 39.2      | 2.286     | <0.0001 | ✓       |
| Seer     | 51.1      | 31.9     | 19.3      | 1.257     | <0.0001 | ✓       |
| Villager | 56.1      | 14.9     | 41.2      | 2.352     | <0.0001 | ✓       |
| Werewolf | 89.0      | 58.3     | 30.7      | 2.757     | <0.0001 | ✓       |
| Witch    | 77.7      | 34.6     | 43.1      | 1.855     | <0.0001 | ✓       |

## 3. Score Distribution

| Role     | Min  | Q25  | Median | Q75  | Max   |
|----------|------|------|--------|------|-------|
| Guard    | 0.0  | 33.9 | 47.4   | 68.3 | 95.7  |
| Hunter   | 0.0  | 32.2 | 50.2   | 75.1 | 93.3  |
| Seer     | 0.0  | 31.2 | 39.7   | 55.2 | 87.0  |
| Villager | 0.0  | 11.2 | 28.0   | 62.3 | 78.6  |
| Werewolf | 10.2 | 61.0 | 69.8   | 93.8 | 100.0 |
| Witch    | 0.0  | 38.1 | 57.1   | 82.2 | 100.0 |

## 4. Known Issues (Pre-Migration)

1. **Camp result dominates**: 25% of rule_score is "which side won". Cohen's d values are inflated by outcome, not decision quality.
2. **Role imbalance**: Werewolf mean (73.6) vs Villager mean (35.5) = 38-point gap. Wolves always get high scores, villagers always low.
3. **Witch/Guard/Hunter lack differentiation**: These low-opportunity roles are coin-flips; the score doesn't capture whether a Witch's poison or Guard's protect was strategically sound.
4. **Score floor at 0.0**: Every role has min=0.0, indicating scoring failures where players get zero credit regardless of contribution.
5. **Hand-crafted weights**: 0.25/0.25/0.12/0.12/0.12/0.08/0.06 weights are arbitrary, not learned from data.
6. **Seer is punished**: Lowest mean score (41.5) despite being the most information-critical role.

## 5. Target Improvements (Phase 1-7)

| Metric | Current | Target |
|--------|---------|--------|
| Witch Cohen's d (process) | <0.5 | ≥0.5 |
| Guard Cohen's d (process) | <0.3 | ≥0.3 |
| Hunter Cohen's d (process) | <0.5 | ≥0.5 |
| Role score gap (max-min mean) | 38.1 | <20 |
| Score floor | 0.0 | >20.0 |
| Pairwise accuracy | N/A | ≥70% |

## 6. Scoring Formula (Old)

```
rule_score = 0.25*camp_result + 0.25*role_task + 0.12*vote + 0.12*speech 
           + 0.12*skill + 0.08*survival + 0.06*info_efficiency

adjusted_final_score = rule_score + impact_bonus - review_penalty + semantic_highlight_bonus
```

**Camp result scoring:**
- village win → all village players get camp_result=100
- wolf win → all wolf players get camp_result=100
- This means 25% of every player's score is predetermined by which team they're on.
