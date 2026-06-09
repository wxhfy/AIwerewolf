# 策略使用与逐决策评分关联摘要

生成时间：2026-06-09T11:31:45+08:00

本文件是最终展示用摘要，对应机器可读快照：`PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json`。

## 1. 数据规模

| Metric | Value |
|---|---:|
| decision_rows | 170,399 |
| distinct_games | 2,482 |
| distinct_players | 19,834 |
| used_decisions | 3,088 |
| unused_decisions | 167,311 |

## 2. 总体结果

| Comparison | Used Count | Unused Count | Used Mean | Unused Mean | Mean Delta | Bootstrap95CI |
|---|---:|---:|---:|---:|---:|---|
| used vs unused | 3,088 | 167,311 | 0.5847 | 0.5024 | +0.0823 | [0.0764, 0.0882] |

展示口径：策略被实际使用的决策，在当前数据快照中对应更高的 Track B 逐步评分。该结果适合说明策略回流链路的实际价值。

## 3. 分层控制结果

| Stratification | Strata | UsedRetained | WeightedDelta | +/-/0 Strata |
|---|---:|---:|---:|---|
| role + action + tier | 19 | 3,088 | +0.0945 | 16 / 3 / 0 |
| role + action + tier + day + phase | 58 | 2,992 | +0.0967 | 48 / 10 / 0 |

## 4. 角色内控制结果

| Role | UsedRetained | Strata | WeightedDelta |
|---|---:|---:|---:|
| Seer | 480 | 12 | +0.1272 |
| Villager | 357 | 8 | +0.1220 |
| Guard | 506 | 11 | +0.1006 |
| Werewolf | 899 | 12 | +0.0899 |
| Hunter | 352 | 8 | +0.0779 |
| Witch | 403 | 11 | +0.0670 |

展示口径：6 个核心角色在角色内控制后均呈现正向 weighted delta。最终报告中建议把它写成“观测性关联 + 策略回流价值证据”，并与 target-seat paired A/B 作为后续确认链路衔接。
