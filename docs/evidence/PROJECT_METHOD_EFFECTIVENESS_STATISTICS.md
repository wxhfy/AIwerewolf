# 方法有效性统计摘要

生成时间：2026-06-09T11:32:32+08:00

本文件是最终展示用摘要，对应机器可读快照：`PROJECT_METHOD_EFFECTIVENESS_STATISTICS.json`。

## 1. 检索策略 paired 统计

对比：`hybrid_role_mbti_global` vs `global_only`，paired queries=26。

| Metric | BaselineMean | CandidateMean | MeanDelta | Bootstrap95CI |
|---|---:|---:|---:|---|
| precision_at_3 | 0.1282 | 0.2564 | +0.1282 | [-0.0256, 0.2692] |
| effective_at_3 | 0.1538 | 0.5000 | +0.3462 | [0.1538, 0.5769] |
| ndcg_at_5 | 0.4938 | 0.9567 | +0.4630 | [0.2648, 0.6622] |
| coverage | 0.5000 | 1.0000 | +0.5000 | [0.3077, 0.6923] |

展示口径：默认混合检索策略在固定 query set 上提升 Coverage、Effective@3 和 nDCG@5，能支撑“单角色检索策略有效覆盖核心角色”的叙事。

## 2. 运行时 feedback

| Metric | Count | Rate | Wilson95CI |
|---|---:|---:|---|
| used / retrieved | 51,383 / 133,281 | 38.55% | [38.29%, 38.81%] |
| helpful / retrieved | 41,192 / 133,281 | 30.91% | [30.66%, 31.15%] |
| helpful / used | 41,192 / 51,383 | 80.17% | [79.82%, 80.51%] |

展示口径：运行时 feedback 说明策略被大量检索、部分进入实际决策，且 used 后的 helpful 标记比例较高。它用于说明链路健康，不替代 target-seat A/B。

## 3. 策略使用与逐决策评分

| Metric | Value |
|---|---:|
| decision_rows | 170,399 |
| used_decisions | 3,088 |
| unused_decisions | 167,311 |
| used_mean | 0.5847 |
| unused_mean | 0.5024 |
| mean_delta | +0.0823 |
| strict_weighted_delta | +0.0967 |
| strict_positive / negative / tied strata | 48 / 10 / 0 |

展示口径：当前非 fake DB 快照中，strategy-used 决策与更高 Track B 逐步评分相关；严格分层控制 role/action/tier/day/phase 后仍保持正向。
