# 策略使用与逐决策评分关联分析

生成时间：2026-06-09T11:31:45+08:00

本报告从当前 PostgreSQL 快照中联表分析 Track C 策略使用和 Track B 逐决策评分的关系。它使用 `published_reviews.report_json.metadata.per_step_scores[*].decision_id` 连接 `agent_decisions.id` 和 `knowledge_usage_feedback.decision_id`，并排除 fake/offline game。

## 1. 数据规模

| Metric | Value |
| --- | --- |
| decision_rows | 170399 |
| distinct_games | 2482 |
| distinct_players | 19834 |
| feedback_decisions | 3088 |
| used_decisions | 3088 |
| unused_decisions | 167311 |
| retrieved_decisions | 3088 |
| no_retrieval_decisions | 167311 |

## 2. 决策级总体结果

| Comparison | A Count | B Count | A Mean | B Mean | MeanDelta | Bootstrap95CI | CI跨0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| used vs unused | 3088 | 167311 | 0.5847 | 0.5024 | 0.0823 | [0.0764, 0.0882] | False |
| retrieved vs no_retrieval | 3088 | 167311 | 0.5847 | 0.5024 | 0.0823 | [0.0764, 0.0882] | False |
| helpful vs unhelpful among used | 2388 | 700 | 0.5875 | 0.5750 | 0.0125 | [-0.0013, 0.0264] | True |

解释：该表是观测性关联。`used vs unused` 可以说明策略使用决策在当前数据中对应更高或更低的 Track B 分数，但不能单独证明策略使用造成分数变化。

## 3. 混杂控制后的分层结果

| Stratification | Strata | UsedRetained | UnusedRetained | WeightedDelta | MeanDelta | MedianDelta | +/-/0 Strata |
| --- | --- | --- | --- | --- | --- | --- | --- |
| role + action + tier | 19 | 3088 (100.00%) | 165740 | 0.0945 | 0.0797 | 0.0877 | 16/3/0 |
| role + action + tier + day + phase | 58 | 2992 (96.89%) | 106170 | 0.0967 | 0.0708 | 0.0901 | 48/10/0 |

解释：分层统计只在同角色、同动作、同评分层级等可比局面内比较 used 与 unused，再按 used 决策数加权。它不能消除所有混杂，但比总体均值更接近“相似局面下策略使用是否对应更高评分”。

## 4. 按角色分层

| Role | Used | Unused | UsedMean | UnusedMean | Delta | 95CI | CI跨0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Werewolf | 917 | 43698 | 0.5641 | 0.5142 | 0.0499 | [0.0391, 0.0607] | False |
| Villager | 364 | 28311 | 0.5909 | 0.4682 | 0.1227 | [0.1050, 0.1404] | False |
| Guard | 519 | 22465 | 0.6334 | 0.5321 | 0.1013 | [0.0861, 0.1165] | False |
| Witch | 406 | 21709 | 0.5353 | 0.4852 | 0.0500 | [0.0358, 0.0642] | False |
| Seer | 488 | 19533 | 0.6481 | 0.5282 | 0.1200 | [0.1070, 0.1329] | False |
| Hunter | 360 | 17712 | 0.5359 | 0.4813 | 0.0546 | [0.0381, 0.0710] | False |

## 5. 角色内控制后的分层结果

该表在每个角色内部再按 action_type、scoring_tier、day、phase 建立可比 strata，然后比较 strategy-used 与 unused 决策。它比单纯按角色均值更能回答“每个角色是否都有增益趋势”。

| Role | TotalUsed | UsedRetained | Strata | WeightedDelta | MeanDelta | MedianDelta | +/-/0 Strata |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Werewolf | 917 | 899 (98.04%) | 12 | 0.0899 | 0.0732 | 0.1009 | 11/1/0 |
| Guard | 519 | 506 (97.50%) | 11 | 0.1006 | 0.0596 | 0.0667 | 8/3/0 |
| Seer | 488 | 480 (98.36%) | 12 | 0.1272 | 0.0962 | 0.0802 | 11/1/0 |
| Witch | 406 | 403 (99.26%) | 11 | 0.0670 | 0.0437 | 0.0179 | 7/4/0 |
| Villager | 364 | 357 (98.08%) | 8 | 0.1220 | 0.0839 | 0.1123 | 6/2/0 |
| Hunter | 360 | 352 (97.78%) | 8 | 0.0779 | 0.0675 | 0.0746 | 8/0/0 |
| WhiteWolfKing | 34 | 29 (85.29%) | 5 | -0.0095 | 0.0059 | -0.0363 | 2/3/0 |

解释：如果某个角色的 UsedRetained 很低，说明该角色可比 strata 还不足，需要补更多真实局或降低分层粒度。WeightedDelta 仍是观测性指标，不能替代 target-seat paired A/B。

## 6. 按动作类型分层

| Action | Used | Unused | UsedMean | UnusedMean | Delta | 95CI | CI跨0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| talk | 1379 | 67508 | 0.5311 | 0.4241 | 0.1069 | [0.1010, 0.1129] | False |
| vote | 1183 | 60875 | 0.5922 | 0.5057 | 0.0864 | [0.0752, 0.0977] | False |
| attack | 155 | 16901 | 0.7811 | 0.6723 | 0.1088 | [0.0889, 0.1287] | False |
| guard | 144 | 7900 | 0.7550 | 0.6442 | 0.1108 | [0.0945, 0.1271] | False |
| skip | 81 | 6649 | 0.5150 | 0.5155 | -0.0005 | [-0.0006, -0.0004] | False |
| divine | 146 | 5907 | 0.6923 | 0.6517 | 0.0406 | [0.0203, 0.0608] | False |

## 7. 结论边界

| 结论类型 | 内容 |
| --- | --- |
| 当前观测 | 当前非 fake DB 快照中，strategy-used 决策的 Track B 均值高于 unused 决策，且均值差置信区间不跨 0。 |
| 不能写 | 这是观测性关联，仍可能受到检索更常出现在较容易或较晚决策中的混杂影响；不能写成随机因果估计。 |
| 因果证明需要 | 需要 target-seat paired A/B：固定 seed、对手和角色分配，并且只为目标席位开启 Track C。 |
