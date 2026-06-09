# 项目方法有效性实验报告

生成时间：2026-06-09T16:24:07+08:00

可追溯性说明：本报告引用的 `docs/experiments/` 和 `outputs/` 原始产物是本地实验输出，按仓库规则不进入 GitHub；可提交的机器可读摘要已汇总到 `docs/PROJECT_METHOD_EFFECTIVENESS_FACTS.json`、`docs/PROJECT_METHOD_EFFECTIVENESS_STATISTICS.json`、`docs/PROJECT_ROLE_RETRIEVAL_FACTS.json` 和 `docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json`。

## 1. 结论摘要

当前证据已经可以支持：系统方法不是单一 Prompt，而是可运行、可审计、可评分、可检索回流的多模块闭环；Track B 可以按对局、模型/版本、角色席位、评分维度和 rubric 多层展示；Track C 默认检索策略在离线检索指标和运行时反馈上具有明确增益；正式 v4flash 数据证明框架版本和 B/C 模块可以被量化区分。

当前证据暂不能支持：Track C 对最终胜率具有统计显著的因果提升。该结论仍需要 target-seat paired A/B。

## 2. 证据等级

| 等级 | 含义 | 本报告中的用途 |
| --- | --- | --- |
| formal_real_llm | 真实 LLM 正式筛选数据 | 框架可区分、严格决策健康 |
| offline_retrieval_ablation | 固定 query set 检索消融 | 证明检索策略设计有效 |
| runtime_db_snapshot | 当前 PostgreSQL 快照 | 证明策略反馈规模和 helpful/used |
| audit_gate | 审计或安全门禁 | 证明信息隔离、知识安全、覆盖 |
| trend_only / smoke_only | 趋势或小样本烟测 | 只能辅助展示，不能写成因果结论 |

## 3. 关键真实指标

| 指标 | 数值 | 来源 | 结论边界 |
| --- | --- | --- | --- |
| formal v4flash rows | 59 | formal_v4flash_framework_analysis/summary.json | 真实 LLM 正式数据 |
| formal LLM decisions | 1059 | formal_v4flash_framework_analysis/leaderboard.csv | fallback=0，invalid=0 |
| rubric spread | 11.5286 | formal_v4flash_framework_analysis/rubric_leaderboard.csv | 证明 leaderboard 能区分版本 |
| Track B showcase games / decisions / panels | 6 / 216 / 7 | docs/PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json | pilot 多层展示；panels=7，fallback=0，invalid=0 |
| module effects passed | 14/14 | module_effect_experiment/module_effects.csv | mean score=90.79 |
| retrieval query/docs | 26 / 374 | outputs/retrieval_effectiveness_current/results.json | 当前离线检索实验 |
| default retrieval P@3 / Coverage | 0.2564 / 1.0000 | outputs/retrieval_effectiveness_current/results.json | 弱标注离线指标 |
| Track C audit invalid/leak | 0 / 0 | full_project_real_audit/audit_summary.json | 知识安全审计 |
| runtime helpful/used | 80.20% | PostgreSQL knowledge_usage_feedback / strategy_knowledge_docs current non-fake snapshot | 当前 DB 快照，非因果分数 |

## 4. Track C 检索有效性

| Policy | OfflineScore | P@3 | Effective@3 | nDCG@5 | Coverage | Top5Fill | CandidateLeak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| global_only | -0.1450 | 0.1282 | 0.1538 | 0.4938 | 0.5000 | 0.2615 | 0 |
| hybrid_role_mbti_global | 0.6991 | 0.2564 | 0.5000 | 0.9567 | 1.0000 | 1.0000 | 0 |
| same_role_same_mbti | -0.3812 | 0.0769 | 0.0769 | 0.1535 | 0.1538 | 0.1000 | 0 |

默认策略相对 `global_only` 的核心提升：P@3 从 0.1282 到 0.2564，Effective@3 从 0.1538 到 0.5000，Coverage 从 0.5000 到 1.0000。`same_role_same_mbti` 过窄，Coverage 只有 0.1538。

统计补充详见 `docs/PROJECT_METHOD_EFFECTIVENESS_STATISTICS.md`。默认检索相对 `global_only` 的 paired bootstrap 结果如下：

| Metric | MeanDelta | Bootstrap95CI | Sign +/−/tie | CI跨0 |
| --- | --- | --- | --- | --- |
| precision_at_3 | 0.1282 | [-0.0256, 0.2692] | 10/3/13 | True |
| effective_at_3 | 0.3462 | [0.1538, 0.5769] | 10/1/15 | False |
| ndcg_at_5 | 0.4630 | [0.2648, 0.6622] | 14/8/4 | False |
| coverage | 0.5000 | [0.3077, 0.6923] | 13/0/13 | False |

## 5. 单角色检索有效性

单角色检索的详细机制、分角色命中率和语料池规模已单独整理为 `docs/PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md`，机器可读摘要见 `docs/PROJECT_ROLE_RETRIEVAL_FACTS.json`。

单角色检索流程按 `search_strategies -> AgentContext -> keyword/BM25 recall -> RetrievalPolicy buckets -> quality gate -> Strategy prompt` 运行。当前可追溯代码依据如下：

| Step | 环节 | 代码依据 |
| --- | --- | --- |
| 1 | Agent 工具调用 | backend/agents/cognitive/tools.py |
| 2 | 构造 AgentContext | backend/agents/cognitive/retrieval_prod.py |
| 3 | 关键词召回 | backend/agents/cognitive/retrieval_prod.py |
| 4 | RetrievalPolicy 分桶 | backend/agents/cognitive/retrieval_prod.py |
| 5 | 质量门禁与 Top-K 填充 | backend/agents/cognitive/retrieval_prod.py |
| 6 | 严格模式安全过滤 | backend/eval/knowledge_confidence.py |
| 7 | Prompt 注入与反馈记录 | backend/agents/cognitive/agent_loop.py |

### 5.1 单角色路径量化摘要

| Role | BestPolicy | DefaultEff@3 | GlobalEff@3 | ExactEff@3 | Default-Global Eff@3 | Default P@3 | RoleBucket | GlobalBucket | 诊断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Guard | same_role_all_mbti | 1.0000 | 0.0000 | 0.0000 | 1.0000 | 0.5000 | 1.0000 | 0.0000 | 当前默认检索命中充分；主要补强方向是扩充 role+MBTI 细分卡，减少对角色通用池的依赖。 |
| Hunter | same_role_all_mbti | 1.0000 | 0.5000 | 0.0000 | 0.5000 | 0.5000 | 1.0000 | 0.0000 | 当前默认检索命中充分；主要补强方向是扩充 role+MBTI 细分卡，减少对角色通用池的依赖。 |
| Seer | hybrid_role_mbti_global | 0.6000 | 0.0000 | 0.2000 | 0.6000 | 0.3333 | 1.0000 | 0.0000 | 当前默认检索覆盖稳定，但 Top-3 高相关密度不足；应补充该角色关键阶段/动作的高质量策略卡。 |
| Villager | hybrid_role_mbti_global | 0.5000 | 0.3333 | 0.0000 | 0.1667 | 0.2778 | 0.9667 | 0.0333 | 当前默认检索覆盖稳定，但 Top-3 高相关密度不足；应补充该角色关键阶段/动作的高质量策略卡。 |
| Werewolf | hybrid_role_mbti_global | 0.2857 | 0.0000 | 0.1429 | 0.2857 | 0.1429 | 1.0000 | 0.0000 | 当前默认检索依赖角色通用池；精确 role+MBTI 池过窄，需要按常见人格补足策略。 |
| Witch | hybrid_role_mbti_global | 0.2500 | 0.2500 | 0.0000 | 0.0000 | 0.0833 | 1.0000 | 0.0000 | 当前默认检索依赖角色通用池；精确 role+MBTI 池过窄，需要按常见人格补足策略。 |

### 5.2 默认策略分角色命中率

| Role | P@3 | Effective@3 | nDCG@5 | Coverage | Top5Fill | RoleBucket | GlobalBucket | Empty |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Guard | 0.5000 | 1.0000 | 0.8821 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0 |
| Hunter | 0.5000 | 1.0000 | 0.8785 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0 |
| Seer | 0.3333 | 0.6000 | 0.9544 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0 |
| Villager | 0.2778 | 0.5000 | 0.9780 | 1.0000 | 1.0000 | 0.9667 | 0.0333 | 0 |
| Werewolf | 0.1429 | 0.2857 | 0.9931 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0 |
| Witch | 0.0833 | 0.2500 | 0.9406 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0 |

按 Effective@3 作为可用命中率口径，默认单角色检索整体命中率为 50.00%；P@3=0.2564，Coverage=1.0000。

默认策略在当前 6 个核心角色上全部无空检索，RoleBucketShare 总体为 0.9923，说明检索主要来自角色策略桶，而不是 global 兜底。

### 5.3 单角色知识池规模

| Role | RoleDocs | RoleGeneric | RoleMBTISpecific | ExactRoleMBTIPoolAvg | ExactEmptyQueries | HybridRolePoolAvg | HybridTotalPoolAvg | GlobalGeneric | DocMBTIs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Guard | 49 | 38 | 11 | 0.0 | 2 | 38.0 | 73.0 | 35 | ISTJ:11 |
| Hunter | 39 | 28 | 11 | 0.0 | 2 | 28.0 | 63.0 | 35 | ESTP:11 |
| Seer | 54 | 37 | 17 | 6.8 | 3 | 43.8 | 78.8 | 35 | INTJ:17 |
| Villager | 18 | 16 | 2 | 0.0 | 6 | 16.0 | 51.0 | 35 | INTP:2 |
| Werewolf | 51 | 33 | 18 | 7.71 | 4 | 40.71 | 75.71 | 35 | INTJ:18 |
| Witch | 42 | 28 | 14 | 0.0 | 4 | 28.0 | 63.0 | 35 | ISTJ:14 |

该表解释了单角色检索的来源：默认混合策略能稳定返回结果，主要依赖每个角色的通用策略池；精确 `role+MBTI` 池目前只在 Seer、Werewolf 等少数角色上有覆盖，后续应补充 Guard、Hunter、Villager、Witch 的 MBTI 细分策略卡。

## 6. 正式 v4flash 框架与模块证据

| Tier | Completed | ExternalFailure | WolfWin | VillageWin | MacroRoleWin | LLMDecisions | Fallback | Invalid |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 9 | 0.307692 | 0.555556 | 0.444444 | 0.462963 | 281 | 0 | 0 |
| both | 7 | 0.65 | 0.571429 | 0.428571 | 0.452381 | 228 | 0 | 0 |
| anti_only | 11 | 0.153846 | 0.636364 | 0.363636 | 0.409091 | 362 | 0 | 0 |
| trackc_only | 7 | 0.461538 | 0.714286 | 0.285714 | 0.357143 | 188 | 0 | 0 |

这些结果证明框架版本可被统一 runner 和 Track B 指标量化，且正式行的 fallback/invalid 为 0。由于 completed/external failure 不均，不能把该表直接解释为最终胜率显著优于 baseline。

## 7. Track C 运行时反馈

| Metric | Value |
| --- | --- |
| feedback_total | 137368 |
| retrieved | 137368 |
| used | 51496 |
| helpful | 41301 |
| used/retrieved | 37.49% |
| helpful/retrieved | 30.07% |
| helpful/used | 80.20% |
| avg_score_delta | 0.0000 |
| strategy_docs_active | 387 |
| strategy_docs_candidate | 216374 |

运行时 feedback Wilson 95% CI：

| Metric | Count | Rate | Wilson95CI |
| --- | --- | --- | --- |
| used/retrieved | 51496/137368 | 0.3749 | [0.3723, 0.3774] |
| helpful/retrieved | 41301/137368 | 0.3007 | [0.2982, 0.3031] |
| helpful/used | 41301/51496 | 0.8020 | [0.7986, 0.8054] |

按角色 feedback：

| Role | Retrieved | Used | Helpful | UsedRate | Helpful/Used |
| --- | --- | --- | --- | --- | --- |
| Werewolf | 20395 | 15304 | 11989 | 75.04% | 78.34% |
| Witch | 10378 | 8103 | 7294 | 78.08% | 90.02% |
| Guard | 10115 | 7322 | 6441 | 72.39% | 87.97% |
| Seer | 9545 | 6775 | 4528 | 70.98% | 66.83% |
| Hunter | 8617 | 6693 | 5349 | 77.67% | 79.92% |
| Villager | 8371 | 6424 | 4998 | 76.74% | 77.80% |
| WhiteWolfKing | 486 | 138 | 117 | 28.40% | 84.78% |

## 8. 策略使用与逐决策评分关联

详细报告见 `docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.md`。该统计通过 `decision_id` 将 Track B per-step score、agent_decisions 和 knowledge_usage_feedback 联表，并排除 fake/offline game。

| Metric | Value |
| --- | --- |
| decision_rows | 170399 |
| used_decisions | 3088 |
| unused_decisions | 167311 |
| used_mean_score | 0.5847 |
| unused_mean_score | 0.5024 |
| mean_delta | 0.0823 |
| 95CI | [0.0764, 0.0882] |
| CI跨0 | False |
| strict_strata | 58 |
| strict_used_retained | 2992 |
| strict_weighted_delta | 0.0967 |
| strict_positive/negative/tied | 48/10/0 |

解释：这支持“策略使用决策在当前非 fake DB 快照中与更高 Track B 逐步评分相关”。严格分层按 role/action/scoring_tier/day/phase 控制明显混杂后仍保持正向，但它仍是观测性关联，不能替代 target-seat paired A/B 因果实验。

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

解释：6 个核心角色的角色内 strict weighted delta 当前均为正；WhiteWolfKing used 样本仅 34，控制后 weighted delta 略负，暂不能写成该角色稳定增益。

## 9. Track C 趋势与烟测

| Metric | Value | Interpretation |
| --- | --- | --- |
| Track C off win_rate | 0.3508 | 辅助趋势 |
| Track C on win_rate | 0.3784 | 辅助趋势 |
| avg_non_wolf_delta | 0.0643 | 全席位切换趋势，不是 target-seat 因果 |
| smoke rows | 5 | 真实 LLM 小样本烟测 |
| max smoke knowledge_hit | 0.9200 | 证明策略注入链路可运行 |

辅助 Track C 胜率统计补充：

| Baseline | Candidate | Delta | 95CI | PValue | CI跨0 |
| --- | --- | --- | --- | --- | --- |
| track_c_off n=553 | track_c_on n=518 | 0.0276 | [-0.0301, 0.0852] | 0.3489 | True |

该统计再次说明：Track C on 存在正向趋势，但 CI 跨 0，当前不能写成最终胜率因果提升。

## 10. Target-seat Track C 因果 A/B

| Source | SummarySource | Role | Baseline | Candidate | Paired | ScoreDelta | RoleTaskDelta | ProcessDelta | WinDelta | MaxDays | Scope | Decisions | Fallback | Invalid | Accepted | ClaimLevel |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| outputs/target_seat_trackc_ab_seer_ark_pilot_20260609/target_seat_ab_Seer_20260609T082838Z.json | docs/PROJECT_TARGET_SEAT_TRACKC_PILOT.json | Seer | basic_react | rag_react | 5 | 20.6680 | 0.2830 | 22.1840 | 0.0000 | 20 | real_llm_pilot_only | 201 | 0 | 0 | False | ci_not_positive |
| outputs/target_seat_trackc_ab_seer_smoke3_maxday1/target_seat_ab_Seer_20260609T042435Z.json |  | Seer | basic_react | rag_react | 3 | -1.2000 | 0.0867 | n/a | 0.0000 | 1 | smoke_only |  | 0 | 0 | False | ci_not_positive |
| outputs/target_seat_trackc_ab_seer_maxday1_probe/target_seat_ab_Seer_20260609T034156Z.json |  | Seer | basic_react | rag_react | 1 | 0.0000 | 0.0000 | n/a | 0.0000 | 1 | smoke_only |  | 0 | 0 | False | ci_not_positive |

解释：`claim_scope=real_llm_pilot_only` 表示真实 LLM target-seat A/B 已跑通，并能展示目标席位 paired delta、per-agent feature flags 和健康门禁；但样本量仍小，bootstrap CI 下界跨 0，不能写成因果支持。只有正式样本 `Accepted=true` 且 `ClaimLevel=causal_supported` 时，才能把 Track C 写成对单个目标席位的因果增益。

### 10.1 真实 LLM Provider Preflight

| Status | SafeForFormalExperiment | ResolvedModels | Error | Source |
| --- | --- | --- | --- | --- |
| ok | True | doubao:ep-<redacted> | None | docs/PROJECT_PROVIDER_PREFLIGHT.json |

该 preflight 已通过真实 provider 可用性检查；target-seat 因果实验的剩余阻塞不再是 provider，而是仍需按功效计划运行正式 paired-seed A/B，并通过 fallback/invalid 与 bootstrap CI 门禁。

### 10.2 Target-seat A/B 功效计划

样本量计划详见 `docs/PROJECT_TARGET_SEAT_AB_POWER_PLAN.md`。该文件只用于规划真实实验，不构成 Track C 已产生因果增益的结论。

| Item | Value |
| --- | --- |
| pilot_paired_seeds | 20 |
| minimum_confirmatory_paired_seeds | 80 |
| preferred_confirmatory_paired_seeds | 120 |
| high_confidence_paired_seeds | 200 |
| primary_metrics | target_adjusted_score_delta, target_role_task_delta |
| secondary_metrics | target_win_rate_delta, target_process_score_delta |

20 个 paired seeds 适合验证 pipeline 和健康门禁，不适合直接作为最终因果证明。除非真实 paired 方差很低，否则评分和 role-task 指标通常需要 80+ paired seeds；胜率差所需样本显著更大，应作为辅助指标。

## 11. 证据矩阵

| Claim | Level | Status | Metric | Source | Boundary |
| --- | --- | --- | --- | --- | --- |
| 正式 v4flash 数据可用于区分框架版本 | formal_real_llm | supported | formal_rows=59; rubric_spread=11.5286 | docs/experiments/formal_v4flash_framework_analysis/summary.json | 证明可度量和可区分，不单独证明最终架构统计显著优于 baseline。 |
| 正式决策链没有 fallback/invalid 污染 | formal_real_llm | supported | llm_decisions=1059; fallback=0; invalid=0 | docs/experiments/formal_v4flash_framework_analysis/leaderboard.csv | 整局 external failure 仍需作为运行稳定性风险披露。 |
| Track B 可以进行多层复盘与评分展示 | real_llm_track_b_showcase | pilot_supported | games=6; raw_decisions=216; panels=7; panel_names=对局层,模型/版本层,玩家/角色席位层,评分维度层,Rubric 层,决策健康层,复盘展示层; fallback=0; invalid=0 | docs/PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json | 展示 Track B 的对局层、模型/版本层、玩家/角色席位层、评分维度层、rubric 层、决策健康层和复盘产物层；不是 Track C 因果增益或正式模型优劣结论。 |
| 核心模块效果已经按多维指标量化 | consolidated_module_audit | supported | passed_modules=14/14; mean_score=90.79 | docs/experiments/module_effect_experiment/module_effects.csv | 模块分数是综合指标，不等同最终胜率提升。 |
| Track C 默认检索策略优于纯 global-only 检索 | offline_retrieval_ablation | supported | default_score=0.6991; global_score=-0.1450; default_p3=0.2564; default_coverage=1.0000 | outputs/retrieval_effectiveness_current/results.json | 弱标注离线检索，证明检索设计合理性；不是在线胜率因果证明。 |
| 单角色默认检索稳定覆盖全部核心角色 | offline_retrieval_per_role | supported | roles=6; all_coverage_1=True; role_bucket_share=0.9923 | outputs/retrieval_effectiveness_current/per_role_results.csv | 每角色 query 数仍偏少；不能声明某个角色的最优 policy 已最终确定。 |
| 精确 role+MBTI 检索过窄，不适合作为默认策略 | offline_retrieval_ablation | supported | same_role_same_mbti_coverage=0.1538; empty=22 | outputs/retrieval_effectiveness_current/results.json | 可作为补充桶或专项实验，不作为默认运行策略。 |
| 精确 role+MBTI 稀疏主要来自当前知识池分布 | offline_retrieval_corpus | supported | roles=6; exact_empty_queries=21; global_generic_docs=35 | outputs/retrieval_effectiveness_current/role_corpus_stats.csv | 这是 active 知识池规模统计；不等同在线策略使用率。 |
| Track C 知识库安全卫生达标 | audit_gate | supported | docs=131; invalid=0; leak=0; source_event_coverage=0.9924 | docs/experiments/full_project_real_audit/audit_summary.json | 审计样本和当前 DB 快照可能不同，正式归档需冻结 experiment_id。 |
| 运行时 feedback 显示被使用策略多数被标记 helpful | runtime_db_snapshot | supported | retrieved=137368; used=51496; helpful=41301; helpful/used=80.20% | PostgreSQL knowledge_usage_feedback / strategy_knowledge_docs current non-fake snapshot | 当前 score_delta 平均仍接近 0，feedback 不能直接等同因果增益。 |
| 策略使用决策与更高 Track B 逐步评分相关 | observational_decision_score_join | supported | decision_rows=170399; used=3088; unused=167311; delta=0.0823; ci=[0.0764,0.0882]; strict_weighted_delta=0.0967; strict_strata=48/10/0 | docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json | 观测性关联，不能替代 target-seat paired A/B 因果证明。 |
| 策略使用评分关联覆盖 6 个核心角色 | role_internal_observational_control | supported | core_positive_roles=6/6; weighted_deltas=Werewolf:0.0899,Guard:0.1006,Seer:0.1272,Witch:0.0670,Villager:0.1220,Hunter:0.0779 | docs/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json | 角色内按 action/tier/day/phase 控制后的观测性关联；非核心或低样本角色暂不声明，negative_or_weak=1。 |
| Track C 开关存在角色/MBTI 层面的正向趋势 | auxiliary_trend | trend_only | off=0.3508; on=0.3784; avg_non_wolf_delta=0.0643 | docs/experiments/mbti_track_c_auxiliary_analysis/summary.json | 全席位同时切换，不是 target-seat 因果 A/B。 |
| Track C 对单个目标席位的因果增益 | target_seat_paired_ab | real_llm_pilot_only | role=Seer; paired=5; score_delta=20.6680; role_task_delta=0.2830; fallback=0; invalid=0; accepted=False; scope=real_llm_pilot_only; max_days=20 | docs/PROJECT_TARGET_SEAT_TRACKC_PILOT.json | 当前最强 target-seat 证据是 5-pair 真实 LLM pilot：趋势正向且健康门禁通过，但 CI gate 未通过；只有 accepted=true 且样本/健康/CI 门禁通过时，才能写成因果支持。 |
| Track C 在线烟测能把策略注入真实决策 | real_llm_smoke | smoke_only | rows=5; max_knowledge_hit=0.9200; fallback_sum=0 | docs/experiments/track_c_runtime_fix/*/group_results.csv | 样本小且有正反结果，只能证明链路可运行和策略命中，不能证明胜率提升。 |
| 完整规则/角色/阶段覆盖已经过真实审计 | full_project_audit | supported | natural_games=9; controlled_cases=9; roles=8; phases=21; issues=0 | docs/experiments/full_project_real_audit/audit_summary.json | 审计证明平台覆盖，不是 Track C 单独增益。 |

## 12. 可写结论与不可写结论

### 可以写入正式报告

| 结论 | 依据 |
| --- | --- |
| 系统方法形成 Play -> Evaluate -> Evolve 闭环，且可审计 | 正式 v4flash、full audit、DB feedback |
| Track B 可以进行多层复盘与评分展示 | PROJECT_TRACK_B_LEADERBOARD_SHOWCASE：game/model-role/score/rubric/decision-health/review-artifacts |
| Track C 默认检索策略相对 global_only 在离线 IR 指标上更有效 | P@3、Effective@3、nDCG@5、Coverage |
| 单角色检索能稳定覆盖核心角色 | per_role_results 中默认策略 Coverage/Top5Fill=1 |
| 策略使用决策与更高 Track B 逐步评分相关 | decision_id 联表：per_step_scores + agent_decisions + knowledge_usage_feedback |
| 知识库安全卫生当前审计通过 | invalid=0、leak=0、source_event_coverage |
| 正式 LLM 决策健康：fallback/invalid 为 0 | formal leaderboard |

### 暂不能写入正式报告

| 结论 | 原因 | 需要补充 |
| --- | --- | --- |
| Track C 最终胜率因果提升 | 当前正式数据中 trackc_only/both 完成率不均；真实 target-seat 5-pair pilot 呈正向评分趋势但 CI 跨 0，且胜率 delta 为 0。 | 先跑 20 paired seeds pilot；正式因果验证建议 80-120 paired seeds 起步，只升级一个目标席位，固定对手、seed、角色分配。胜率作为辅助指标。 |
| 每个角色的最优检索 policy | 离线 query set 仅 26 条，Guard/Hunter 等角色样本少。 | 每角色 20+ 查询，人工或 LLM judge 标注 top-5。 |
| strategy_usage_feedback 的逐决策因果分数 | 当前 avg_score_delta 接近 0，未与 Track B ScoredStep 做严格差分。 | 关联 retrieved_doc_ids / knowledge_usage_feedback / PerStepScorer，计算 used vs unused 决策分差。 |
| 正式 target-seat A/B 样本量 | 当前已有 Seer 5-pair 真实 LLM pilot：adjusted +20.668、role-task +0.283、fallback/invalid=0，但 CI gate 未通过；尚未完成 20-pair pilot 或 80-120 paired seeds 正式验证。 | 按功效计划运行正式 target-seat paired A/B：固定 seed、角色分配和对手，只升级目标席位，并报告 adjusted score、role-task、win-rate、fallback/invalid 与 bootstrap CI。 |

## 13. 下一步真实实验命令

当前 Doubao/Ark endpoint 已通过真实 chat preflight。建议先运行 20 paired seeds pilot 验证完整 target-seat 链路健康：

```bash
python scripts/target_seat_trackc_ab_experiment.py \
  --target-role Seer \
  --seeds 9301 9302 9303 9304 9305 9306 9307 9308 9309 9310 9311 9312 9313 9314 9315 9316 9317 9318 9319 9320 \
  --baseline-framework basic_react \
  --candidate-framework rag_react \
  --models "doubao:${DOUBAO_ENDPOINT}" \
  --player-count 7 \
  --max-days 20 \
  --bootstrap-iterations 2000 \
  --min-paired-seeds 20 \
  --min-adjusted-score-delta 3.0 \
  --min-role-task-delta 0.03 \
  --min-win-rate-delta 0.03 \
  --output-dir outputs/target_seat_trackc_ab_seer
```

全席位框架对比可继续运行：

```bash
python scripts/track_bc_leaderboard_experiment.py \
  --axis framework \
  --frameworks basic_react,rag_react,full_cognitive \
  --games 20 \
  --start-seed 9301 \
  --player-count 7 \
  --max-days 20 \
  --strict-fallback true \
  --output-dir outputs/method_effectiveness_paired_v4flash
```

如果要证明 Track C 对单个最终 Agent 的因果增益，还需要正式 target-seat A/B：同 seed、同角色分配、同 baseline 对手，只升级一个目标席位，并按角色轮换。根据 `docs/PROJECT_TARGET_SEAT_AB_POWER_PLAN.md`，正式验证建议 80-120 paired seeds 起步，胜率只作为辅助指标。
