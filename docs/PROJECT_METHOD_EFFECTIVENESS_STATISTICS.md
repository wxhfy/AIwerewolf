# 项目方法有效性统计补充报告

生成时间：2026-06-09T11:32:32+08:00

本报告只基于已有实验产物重新计算统计量，不运行新对局、不调用 LLM、不写数据库。它用于把“可证明的有效性”“趋势证据”和“尚未证明的因果结论”分开。

## 1. 检索策略 paired bootstrap

对比：`hybrid_role_mbti_global` vs `global_only`；paired queries=26。

| Metric | BaselineMean | CandidateMean | MeanDelta | Bootstrap95CI | Sign +/−/tie | SignP | CI跨0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| precision_at_3 | 0.1282 | 0.2564 | 0.1282 | [-0.0256, 0.2692] | 10/3/13 | 0.0923 | True |
| effective_at_3 | 0.1538 | 0.5000 | 0.3462 | [0.1538, 0.5769] | 10/1/15 | 0.0117 | False |
| ndcg_at_5 | 0.4938 | 0.9567 | 0.4630 | [0.2648, 0.6622] | 14/8/4 | 0.2863 | False |
| coverage | 0.5000 | 1.0000 | 0.5000 | [0.3077, 0.6923] | 13/0/13 | 0.0002 | False |

解释：默认检索策略在固定 query set 上相对 `global_only` 提升了 P@3、Effective@3、nDCG@5 和 Coverage。该证据支持“检索设计有效”，但不等价于在线胜率因果提升。

对比：`same_role_same_mbti` vs `hybrid_role_mbti_global`；paired queries=26。

| Metric | DefaultMean | ExactMean | MeanDelta | Bootstrap95CI | Sign +/−/tie | SignP |
| --- | --- | --- | --- | --- | --- | --- |
| precision_at_3 | 0.2564 | 0.0769 | -0.1795 | [-0.2949, -0.0641] | 1/11/14 | 0.0063 |
| effective_at_3 | 0.5000 | 0.0769 | -0.4231 | [-0.6154, -0.2308] | 0/11/15 | 0.0010 |
| ndcg_at_5 | 0.9567 | 0.1535 | -0.8032 | [-0.9226, -0.6639] | 0/22/4 | 0.0000 |
| coverage | 1.0000 | 0.1538 | -0.8462 | [-0.9615, -0.6923] | 0/22/4 | 0.0000 |

解释：精确 `same_role_same_mbti` 相对默认混合策略显著更稀疏，可作为优先个性化桶，但不适合作为唯一检索策略。

## 2. Track C 辅助胜率趋势

| Baseline | Candidate | BaselineRate | CandidateRate | Delta | Normal95CI | PValue | CI跨0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| track_c_off n=553 wins=194 | track_c_on n=518 wins=196 | 0.3508 | 0.3784 | 0.0276 | [-0.0301, 0.0852] | 0.3489 | True |

解释：辅助数据中 Track C on 的胜率高于 off，但 95% CI 跨 0，且这是全席位同时切换，不是 target-seat paired A/B。因此只能写成趋势证据，不能写成最终因果结论。

## 3. 运行时 feedback Wilson CI

| Metric | Count | Rate | Wilson95CI | Source |
| --- | --- | --- | --- | --- |
| used/retrieved | 51383/133281 | 0.3855 | [0.3829, 0.3881] | PostgreSQL knowledge_usage_feedback / strategy_knowledge_docs current non-fake snapshot |
| helpful/retrieved | 41192/133281 | 0.3091 | [0.3066, 0.3115] | excludes games whose players.model_name contains fake |
| helpful/used | 41192/51383 | 0.8017 | [0.7982, 0.8051] | 当前非 fake DB 快照 |

解释：运行时 feedback 说明策略被大量检索、部分进入实际决策，且 used 后的 helpful 标记比例较高。它是运行链路有效性的证据，不是随机对照因果分数。

## 4. 策略使用与 Track B 逐决策评分

| Metric | Value |
| --- | --- |
| decision_rows | 170399 |
| used_decisions | 3088 |
| unused_decisions | 167311 |
| used_mean | 0.5847 |
| unused_mean | 0.5024 |
| mean_delta | 0.0823 |
| 95CI | [0.0764, 0.0882] |
| CI跨0 | False |
| strict_strata | 58 |
| strict_used_retained | 2992 |
| strict_weighted_delta | 0.0967 |
| strict_positive/negative/tied | 48/10/0 |

解释：该统计把 Track B per-step score 与 knowledge usage feedback 通过 decision_id 联表。严格分层按 role/action/scoring_tier/day/phase 控制明显混杂后仍保持正向；这仍是观测性关联，不是因果证明。

角色内控制结果：

| Role | TotalUsed | UsedRetained | Strata | WeightedDelta | MeanDelta | MedianDelta | +/-/0 Strata |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Werewolf | 917 | 899 (98.04%) | 12 | 0.0899 | 0.0732 | 0.1009 | 11/1/0 |
| Guard | 519 | 506 (97.50%) | 11 | 0.1006 | 0.0596 | 0.0667 | 8/3/0 |
| Seer | 488 | 480 (98.36%) | 12 | 0.1272 | 0.0962 | 0.0802 | 11/1/0 |
| Witch | 406 | 403 (99.26%) | 11 | 0.0670 | 0.0437 | 0.0179 | 7/4/0 |
| Villager | 364 | 357 (98.08%) | 8 | 0.1220 | 0.0839 | 0.1123 | 6/2/0 |
| Hunter | 360 | 352 (97.78%) | 8 | 0.0779 | 0.0675 | 0.0746 | 8/0/0 |
| WhiteWolfKing | 34 | 29 (85.29%) | 5 | -0.0095 | 0.0059 | -0.0363 | 2/3/0 |

解释：6 个核心角色的角色内 strict weighted delta 当前均为正。WhiteWolfKing 样本量低且 weighted delta 略负，暂不作为稳定增益结论。

## 5. 正式 v4flash 健康度

| Metric | Value | Interpretation |
| --- | --- | --- |
| attempted/completed | 59/34 | 真实 LLM 正式样本 |
| external_failure_rate | 0.4237 | 外部服务稳定性风险 |
| llm_decisions | 1059 | 正式决策规模 |
| fallback_rate | 0.0000 | strict 决策健康 |
| invalid_rate | 0.0000 | strict 决策健康 |
| rubric_score_spread | 11.5286 | 框架版本可区分 |

## 6. 结论边界

| Claim | Status | Boundary |
| --- | --- | --- |
| 默认检索策略相对 global_only 有统计支持的检索指标提升 | supported_by_paired_retrieval_statistics | 仅证明离线检索相关性和覆盖率，不证明最终胜率因果提升。 |
| Track C 开关提升最终胜率 | not_proven | 辅助 all-seat 数据 CI 跨 0，且不是 target-seat paired A/B。 |
| 运行时策略反馈显示策略被大量使用且 helpful/used 较高 | supported_as_runtime_feedback | helpful 不是随机对照因果分数，不能替代 Track B 差分或 target-seat A/B。 |
| 使用策略的决策与更高 Track B 逐步评分相关 | supported_as_observational_association | 观测性联表统计，不能替代 target-seat 随机/配对因果实验。 |
