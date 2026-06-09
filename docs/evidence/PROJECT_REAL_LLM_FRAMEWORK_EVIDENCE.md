# 真实 LLM 框架实验汇总

生成时间：2026-06-09T15:36:46+08:00

本文件汇总 `track_bc_leaderboard_experiment.py` 及相关真实 LLM 框架实验产物。它只读取已有输出，不调用 LLM，不写数据库。报告重点是区分“可引用证据”和“暂不能写入结论的实验”。

原始实验输出位于 `.gitignore` 覆盖的本地 `docs/experiments/` 与 `outputs/` 目录；本文件和配套 JSON 是可提交的聚合事实快照。

## 1. 总览

| 指标 | 值 |
| --- | --- |
| run_count | 24 |
| completed_raw_games | 78 |
| failed_games | 80 |
| total_decisions | 1936 |
| total_fallback | 0 |
| total_invalid | 0 |
| formal_candidate_runs | 0 |
| smoke_runs | 7 |
| running_no_completed_games | 0 |

## 2. Run 级证据边界

| Run | Status | Scope | Games/Framework | MaxDays | Completed | Failed | Fallback | Invalid | MeanKnowledgeHit | ClaimLevel |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| docs/experiments/formal_v4flash_framework_analysis | complete | formal_analysis_with_failures | 0 | None | 34 | 25 | 0 | 0 | 0.0000 | formal_framework_quantified |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g1 | complete | smoke_only | 1 | 1 | 2 | 0 | 0 | 0 | 0.4000 | pipeline_health_only |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g3 | complete | smoke_only | 3 | 1 | 6 | 0 | 0 | 0 | 0.4000 | pipeline_health_only |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g6 | complete | smoke_only | 6 | 1 | 12 | 0 | 0 | 0 | 0.4000 | pipeline_health_only |
| docs/experiments/framework_gap_reflexion_doubao_endpoint_g1 | complete | smoke_only | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | pipeline_health_only |
| docs/experiments/framework_gap_reflexion_doubao_endpoint_g6 | complete | smoke_only | 0 | 0 | 0 | 0 | 0 | 0 | 0.0000 | pipeline_health_only |
| docs/experiments/framework_gap_reflexion_v4flash_g6 | complete | incomplete_with_failures | 6 | 5 | 0 | 12 | 0 | 0 | 0.0000 | operational_diagnostics |
| docs/experiments/track_c_runtime_fix/doubao_smoke_g1 | complete | incomplete_with_failures | 1 | 8 | 1 | 1 | 0 | 0 | 0.9130 | operational_diagnostics |
| docs/experiments/track_c_runtime_fix/doubao_smoke_g1_after_target_guard | complete | low_sample_or_partial | 1 | 8 | 2 | 0 | 0 | 0 | 0.4135 | trend_only |
| docs/experiments/track_c_runtime_fix/doubao_smoke_g1_conservative_baseline_retry | complete | low_sample_or_partial | 1 | 8 | 1 | 0 | 0 | 0 | 0.0000 | trend_only |
| docs/experiments/track_c_runtime_fix/doubao_smoke_g1_conservative_gate | complete | incomplete_with_failures | 1 | 8 | 1 | 1 | 0 | 0 | 0.9200 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_leaderboard_ark_framework_g5_20260609 | partial | low_sample_or_partial | 5 | 20 | 5 | 0 | 0 | 0 | 0.0542 | trend_only |
| outputs/final_showcase_report/real_experiment_leaderboard_ark_probe_basic_g1_20260609 | complete | smoke_only | 1 | 1 | 1 | 0 | 0 | 0 | 0.0000 | pipeline_health_only |
| outputs/final_showcase_report/real_experiment_leaderboard_pilot_doubao_g1_20260609 | complete | incomplete_with_failures | 1 | 3 | 0 | 3 | 0 | 0 | 0.0000 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_leaderboard_throttled_probe_doubao_g1_20260609 | complete | smoke_only | 1 | 1 | 0 | 1 | 0 | 0 | 0.0000 | pipeline_health_only |
| outputs/final_showcase_report/real_experiment_model_leaderboard_ark_full_cognitive_g1_20260609 | complete | low_sample_or_partial | 1 | 3 | 1 | 0 | 0 | 0 | 0.9118 | trend_only |
| outputs/final_showcase_report/real_experiment_real_llm_g1 | complete | incomplete_with_failures | 1 | 8 | 2 | 1 | 0 | 0 | 0.4000 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_real_llm_g1_after_agentloop_repair | complete | incomplete_with_failures | 1 | 8 | 2 | 1 | 0 | 0 | 0.7068 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_real_llm_g1_after_reasoning_repair | complete | low_sample_or_partial | 1 | 8 | 3 | 0 | 0 | 0 | 0.5690 | trend_only |
| outputs/final_showcase_report/real_experiment_real_llm_g1_after_shoot_repair | complete | incomplete_with_failures | 1 | 8 | 1 | 2 | 0 | 0 | 0.8000 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_real_llm_g1_after_target_repair | complete | incomplete_with_failures | 1 | 8 | 1 | 2 | 0 | 0 | 0.0000 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_real_llm_g5_doubao_v1 | partial | incomplete_with_failures | 5 | 20 | 2 | 1 | 0 | 0 | 0.0000 | operational_diagnostics |
| outputs/final_showcase_report/real_experiment_real_llm_g5_doubao_v2 | partial | low_sample_or_partial | 5 | 20 | 1 | 0 | 0 | 0 | 0.0000 | trend_only |
| outputs/final_showcase_report/real_experiment_real_llm_g5_doubao_v3 | complete | incomplete_with_failures | 5 | 20 | 0 | 30 | 0 | 0 | 0.0000 | operational_diagnostics |

## 3. 分组指标

### docs/experiments/formal_v4flash_framework_analysis

证据边界：正式 v4flash 二次分析可证明框架版本、决策健康和工程指标可量化；但各 tier 失败率不均，不能写成 Track C 胜率因果提升。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tier:anti_only | 11 | 69.6252 | 0.3636 | 362 | 0 | 0 | 0.0000 |
| tier:baseline | 9 | 70.6437 | 0.4444 | 281 | 0 | 0 | 0.0000 |
| tier:both | 7 | 78.7450 | 0.4286 | 228 | 0 | 0 | 0.0000 |
| tier:trackc_only | 7 | 71.3175 | 0.2857 | 188 | 0 | 0 | 0.0000 |

### docs/experiments/framework_gap_reflexion_anthropic_v4flash_g1

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:rag_reflexion | 1 | 39.1571 | 0.2857 | 5 | 0 | 0 | 0.8000 |
| framework:reflexion_react | 1 | 37.5429 | 0.2857 | 5 | 0 | 0 | 0.0000 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:rag_reflexion | framework:reflexion_react | 1 | -1.6143 | 0.0000 |

### docs/experiments/framework_gap_reflexion_anthropic_v4flash_g3

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:rag_reflexion | 3 | 38.9381 | 0.2857 | 15 | 0 | 0 | 0.8000 |
| framework:reflexion_react | 3 | 37.2048 | 0.2857 | 15 | 0 | 0 | 0.0000 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:rag_reflexion | framework:reflexion_react | 3 | -1.7333 | 0.0000 |

### docs/experiments/framework_gap_reflexion_anthropic_v4flash_g6

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:rag_reflexion | 6 | 37.5929 | 0.2857 | 30 | 0 | 0 | 0.8000 |
| framework:reflexion_react | 6 | 37.5786 | 0.2857 | 30 | 0 | 0 | 0.0000 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:rag_reflexion | framework:reflexion_react | 6 | -0.0143 | 0.0000 |

### docs/experiments/framework_gap_reflexion_doubao_endpoint_g1

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

当前没有完成局分组指标。

### docs/experiments/framework_gap_reflexion_doubao_endpoint_g6

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

当前没有完成局分组指标。

### docs/experiments/framework_gap_reflexion_v4flash_g6

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

当前没有完成局分组指标。

### docs/experiments/track_c_runtime_fix/doubao_smoke_g1

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:trackc_only | 1 | 66.4986 | 0.7143 | 46 | 0 | 0 | 0.9130 |

### docs/experiments/track_c_runtime_fix/doubao_smoke_g1_after_target_guard

证据边界：样本量或完成度不足，只能作为趋势/链路证据。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 62.5086 | 0.7143 | 44 | 0 | 0 | 0.0000 |
| framework:trackc_only | 1 | 47.8786 | 0.2857 | 52 | 0 | 0 | 0.8269 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:basic_react | framework:trackc_only | 1 | -14.6300 | -0.4286 |

### docs/experiments/track_c_runtime_fix/doubao_smoke_g1_conservative_baseline_retry

证据边界：样本量或完成度不足，只能作为趋势/链路证据。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 47.5014 | 0.2857 | 34 | 0 | 0 | 0.0000 |

### docs/experiments/track_c_runtime_fix/doubao_smoke_g1_conservative_gate

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:trackc_only | 1 | 63.9200 | 0.7143 | 50 | 0 | 0 | 0.9200 |

### outputs/final_showcase_report/real_experiment_leaderboard_ark_framework_g5_20260609

证据边界：样本量或完成度不足，只能作为趋势/链路证据。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 5 | 49.0909 | 0.3714 | 182 | 0 | 0 | 0.0542 |

### outputs/final_showcase_report/real_experiment_leaderboard_ark_probe_basic_g1_20260609

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 38.3143 | 0.2857 | 5 | 0 | 0 | 0.0000 |

### outputs/final_showcase_report/real_experiment_leaderboard_pilot_doubao_g1_20260609

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

当前没有完成局分组指标。

Failure types：`{"HTTPStatusError": 3}`

### outputs/final_showcase_report/real_experiment_leaderboard_throttled_probe_doubao_g1_20260609

证据边界：max_days<=1，只能证明 runner、feature flag 和指标写入链路可运行。

当前没有完成局分组指标。

Failure types：`{"HTTPStatusError": 1}`

### outputs/final_showcase_report/real_experiment_model_leaderboard_ark_full_cognitive_g1_20260609

证据边界：样本量或完成度不足，只能作为趋势/链路证据。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| model:anthropic:deepseek-v4-flash[1m] | 1 | 31.4325 | 0.2500 | 34 | 0 | 0 | 0.9118 |
| model:anthropic:deepseek-v4-pro[1m] | 1 | 42.4267 | 0.3333 | 34 | 0 | 0 | 0.9118 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| model:anthropic:deepseek-v4-flash[1m] | model:anthropic:deepseek-v4-pro[1m] | 1 | 10.9942 | 0.0833 |

### outputs/final_showcase_report/real_experiment_real_llm_g1

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 31.0743 | 0.2857 | 30 | 0 | 0 | 0.0000 |
| framework:full_cognitive | 1 | 38.3143 | 0.2857 | 5 | 0 | 0 | 0.8000 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:basic_react | framework:full_cognitive | 1 | 7.2400 | 0.0000 |

Failure types：`{"RuntimeError": 1}`

### outputs/final_showcase_report/real_experiment_real_llm_g1_after_agentloop_repair

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:full_cognitive | 1 | 35.3843 | 0.2857 | 44 | 0 | 0 | 0.6136 |
| framework:trackc_only | 1 | 37.0286 | 0.2857 | 5 | 0 | 0 | 0.8000 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:full_cognitive | framework:trackc_only | 1 | 1.6443 | 0.0000 |

Failure types：`{"RuntimeError": 1}`

### outputs/final_showcase_report/real_experiment_real_llm_g1_after_reasoning_repair

证据边界：样本量或完成度不足，只能作为趋势/链路证据。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 48.4771 | 0.2857 | 27 | 0 | 0 | 0.0000 |
| framework:full_cognitive | 1 | 60.1586 | 0.2857 | 33 | 0 | 0 | 0.8182 |
| framework:trackc_only | 1 | 45.2443 | 0.2857 | 27 | 0 | 0 | 0.8889 |

Paired delta：

| Baseline | Candidate | PairedSeeds | ScoreDelta | WinDelta |
| --- | --- | --- | --- | --- |
| framework:basic_react | framework:full_cognitive | 1 | 11.6814 | 0.0000 |

### outputs/final_showcase_report/real_experiment_real_llm_g1_after_shoot_repair

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:trackc_only | 1 | 38.3143 | 0.2857 | 5 | 0 | 0 | 0.8000 |

Failure types：`{"RuntimeError": 2}`

### outputs/final_showcase_report/real_experiment_real_llm_g1_after_target_repair

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 49.8957 | 0.2857 | 27 | 0 | 0 | 0.0000 |

Failure types：`{"RuntimeError": 2}`

### outputs/final_showcase_report/real_experiment_real_llm_g5_doubao_v1

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 2 | 57.9707 | 0.5000 | 92 | 0 | 0 | 0.0000 |

Failure types：`{"ReadTimeout": 1}`

### outputs/final_showcase_report/real_experiment_real_llm_g5_doubao_v2

证据边界：样本量或完成度不足，只能作为趋势/链路证据。

| Group | Rows | Score | WinRate | Decision | Fallback | Invalid | KnowledgeHit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| framework:basic_react | 1 | 53.9586 | 0.2857 | 35 | 0 | 0 | 0.0000 |

### outputs/final_showcase_report/real_experiment_real_llm_g5_doubao_v3

证据边界：存在整局失败，不能写成方法效果结论；可用于定位稳定性问题。

当前没有完成局分组指标。

Failure types：`{"HTTPStatusError": 30}`

## 4. 可写结论与边界

| 可以写入报告的内容 | 证据条件 |
| --- | --- |
| 真实 LLM 框架实验 runner 可记录 completed/failed/fallback/invalid/knowledge hit | 本文件 run 级表和分组表 |
| fallback/invalid 为 0 的完成局具备决策健康证据 | 对应 run 的 Fallback/Invalid 列为 0 |
| Track C/RAG 相关框架能产生 knowledge hit | 分组表中 KnowledgeHit > 0 |

| 暂不能写入的内容 | 原因 |
| --- | --- |
| Track C 对胜率有统计显著因果提升 | 当前全席位框架对比不能隔离单个目标席位，仍需 target-seat paired A/B |
| 正在运行且无完成局的实验结果 | `running_no_completed_games` 只能说明输出目录已创建 |
| max_days<=1 的实验代表完整对局能力 | 该类实验只是 smoke，不覆盖完整局长和终局稳定性 |
