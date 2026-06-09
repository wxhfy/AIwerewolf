# 改进效果分析

## 1. 已有真实验收结果

本文件区分三类数据：

- **当前真实快照**：本轮可直接读取的本地文件或 PostgreSQL 查询结果。
- **项目验收文档记录**：已有验收报告中记录的结果，但当前仓库根目录未找到对应 `outputs/` 原始文件。
- **占位模板**：用于展示未来图表结构，不能写入正式结论。

### 1.1 strict mode 验收记录

| 指标 | 结果 | 数据状态 | 来源 |
|---|---:|---|---|
| strict mode | PASSED | 项目验收文档记录 | `docs/backend_acceptance_criteria.md` |
| 验收命令 | `python scripts/run_backend_full_strict.py` | 项目验收文档记录 | 同上 |
| game_id | `edbde010` | 项目验收文档记录 | 同上 |
| player_count | 7 | 项目验收文档记录 | 同上 |
| days | 1 | 项目验收文档记录 | 同上 |
| winner | Village | 项目验收文档记录 | 同上 |
| duration | 1553s | 项目验收文档记录 | 同上 |
| AgentDecision 工具追踪 | 26/27 | 项目验收文档记录 | 同上 |
| Track B ScoredStep 覆盖 | 27/27 | 项目验收文档记录 | 同上 |
| Track C lessons | 99 | 项目验收文档记录 | 同上 |
| Candidate 增量 | +194 | 项目验收文档记录 | 同上 |
| Active 池变化 | 1065 -> 1065 | 项目验收文档记录 | 同上 |
| 信息隔离检查 | 92 项通过 | 项目验收文档记录 | 同上 |

说明：当前仓库根目录未找到 `outputs/` 目录，因此 strict 的 JSON 原始输出未在本轮复查。正式报告前建议重新运行 `scripts/run_backend_full_strict.py`，生成并冻结 `outputs/backend_e2e_report.json`。

### 1.2 当前 PostgreSQL 快照

查询时间：2026-06-07 13:55:01 UTC。来源：本地 Docker 容器 `werewolf-pg`，database `werewolf`。

| 指标 | 当前值 |
|---|---:|
| public base tables | 22 |
| games | 10429 |
| players | 92479 |
| game_events | 598582 |
| game_snapshots | 3835 |
| agent_decisions | 250603 |
| evaluations | 95790 |
| published_reviews | 3827 |
| strategy_knowledge_docs | 4258 |
| knowledge_usage_feedback | 127537 |
| leaderboard_entries | 34 |

策略知识状态分布：

| status | count |
|---|---:|
| active | 401 |
| candidate | 3856 |
| deprecated | 1 |

游戏状态分布：

| status | count |
|---|---:|
| finished | 10189 |
| running | 240 |

胜方分布：

| winner | count |
|---|---:|
| village | 3015 |
| wolf | 7174 |
| 空 / running | 240 |

注意：当前数据库快照与 `docs/backend_acceptance_criteria.md` 中的 strict 验收口径不同，不能混合成同一实验结论。数据库包含历史实验、运行中对局、不同 provider 和不同配置记录，正式统计必须按时间、experiment_id、provider 和 strict 标记过滤。

### 1.3 当前文件实验结果

`data/experiment/batch_summary.json` 记录 20 局批量实验。

| 指标 | 值 | 来源 |
|---|---:|---|
| completed_at | 2026-06-04T06:05:55.914516 | `data/experiment/batch_summary.json` |
| total_games | 20 | 同上 |
| successful | 20 | 同上 |
| failed | 0 | 同上 |
| completion_rate | 100% | 同上 |
| village wins | 8 | 同上 |
| wolf wins | 12 | 同上 |
| avg_days | 3.05 | 同上 |
| min_days | 2 | 同上 |
| max_days | 5 | 同上 |
| avg_duration_s | 2308.39 | 同上 |

角色统计：

| Role | Count | Wins | Win Rate |
|---|---:|---:|---:|
| Guard | 20 | 8 | 40.0% |
| Hunter | 20 | 8 | 40.0% |
| Seer | 20 | 8 | 40.0% |
| Villager | 20 | 8 | 40.0% |
| Werewolf | 40 | 24 | 60.0% |
| Witch | 20 | 8 | 40.0% |

该结果可以用于说明“存在 20 局成功运行记录”，但该文件未包含逐局 AgentDecision 数、Track B/C 产出、fallback 次数和策略使用统计，因此不能证明 Track C 效果。

## 2. 各阶段改进效果

| 改进 | 改进前 | 改进后 | 效果指标 | 数据状态 |
|---|---|---|---|---|
| Game Engine 独立化 | 对局流程容易被脚本或 Agent 输出影响 | `WerewolfGame` 控制阶段与结算 | strict 全流程 PASS、finished games | 文档记录 + 当前 DB 快照 |
| PlayerView 信息隔离 | Agent 可能看到不该看到的身份或私有事件 | `Visibility.for_player()` 裁剪局部视图 | 92 项隔离检查通过 | 项目验收文档记录 |
| 决策审计 | 对局结束后难以追踪每步行为 | `agent_decisions` 入库 | 当前 DB 250603 条决策 | 当前 DB 快照 |
| CognitiveAgent | 单 Prompt / heuristic 难以表达角色差异 | Observe -> Think -> Act | strict AgentDecision verified | 文档记录 |
| 三层 Prompt | 人设、身份、策略混写 | Persona / Role / Strategy 分离 | 策略来源可审计 | 设计与代码证据 |
| AgentLoop 工具调用 | 一次性 Prompt 难以按需补信息 | 工具调用循环 | 26/27 tool trace 文档记录 | 文档记录 |
| StrategyRetriever | 静态策略无法回流 | BM25 + policy + 4-filter | 检索策略评估报告 | 实验报告 |
| hybrid_role_mbti_global | global_only 覆盖不足 | 角色/MBTI/全局分层 | Coverage / P@3 / nDCG@5 | 检索报告 |
| 单角色检索量化 | 只知道总体 policy 排名，无法说明单个角色实际从哪里命中 | 统计 DefaultEff@3、RoleBucket、GlobalBucket、ExactEmptyQueries | Effective@3 / Coverage / RoleBucketShare | 真实离线检索结果 |
| 4-filter | 相似度 top-k 可能泄露或不适用 | confidence / visibility / privacy / applicability | candidate leakage / active 池污染 | 文档记录，需补专项统计 |
| PerStepScorer | 胜负无法解释行为质量 | 逐步复盘分析 | 27/27 ScoredStep 覆盖 | 文档记录 |
| KnowledgeAbstractor | 复盘无法回到下一局 | lesson -> candidate docs | lessons 数、candidate 增量 | 文档记录 |
| candidate/active 隔离 | 新 lesson 可能污染正式策略池 | candidate 默认隔离 | active delta=0 | 文档记录 |
| strict mode | 分散测试无法证明闭环 | 端到端验收脚本 | PASS / FAIL | 文档记录 |

## 3. 多局实验结果

### 3.1 可引用真实数据：20 局 batch summary

| 实验 | 局数 | 完成率 | 平均天数 | 平均耗时 | 胜方分布 | 数据状态 |
|---|---:|---:|---:|---:|---|---|
| seeds 300-319 batch | 20 | 100% | 3.05 | 2308.39s | Village 8 / Wolf 12 | 真实数据，来源：`data/experiment/batch_summary.json` |

可写结论：该批次证明项目有连续 20 局成功运行记录。

不可写结论：该批次不能证明 Track C 或某检索策略提升，因为文件未记录对照组、策略使用、fallback、Track B/C 逐局产出。

### 3.2 受限真实数据：multi-tier

来源：`data/experiment/multi_tier/formal_dsv4flash_7p_tier_6x_v2/summary.json`。

| Tier | 完成局 | 失败数 | Village 胜率 | Wolf 胜率 | LLM 决策 | Fallback | Invalid |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 18 | 4 | 33.3% | 66.7% | 580 | 0 | 0 |
| anti_only | 20 | 2 | 20.0% | 80.0% | 573 | 0 | 0 |
| trackc_only | 13 | 13 | 30.8% | 69.2% | 363 | 0 | 0 |
| both | 13 | 20 | 23.1% | 76.9% | 392 | 0 | 0 |

结论边界：该结果只能作为“已有多层级实验记录”；由于完成局数和失败数不均，不能作为稳定性能对比或提升证明。

### 3.3 多局实验占位模板

以下为多局实验结果展示模板，数值为占位示例，后续需用真实实验替换。该模板按当前已有 20 局 batch summary 和 multi-tier 记录的量级编排，用于可视化排版，不写入正式结论。

![多局稳定性占位图表](assets/final_report/placeholder-stability.svg)

| 实验方案 | 局数 | 完成率 | 平均天数 | 平均事件数 | 平均决策数 | 平均 ScoredStep | 平均 lessons | 平均 candidate 增量 | fallback 次数 | invalid 次数 | 胜方分布 | 数据状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| baseline（占位） | 20 | 95% | 2.8 | 58 | 30 | 30 | 0 | 0 | 0 | 0 | Village 9 / Wolf 11 | 占位，后续替换 |
| anti_only（占位） | 20 | 96% | 2.7 | 57 | 29 | 29 | 0 | 0 | 0 | 0 | Village 8 / Wolf 12 | 占位，后续替换 |
| trackc_only（占位） | 20 | 96% | 2.9 | 61 | 31 | 31 | 80 | 150 | 0 | 0 | Village 10 / Wolf 10 | 占位，后续替换 |
| both（占位） | 20 | 95% | 3.0 | 63 | 32 | 32 | 85 | 160 | 0 | 0 | Village 11 / Wolf 9 | 占位，后续替换 |
| hybrid_retrieval（占位） | 20 | 96% | 2.9 | 62 | 32 | 32 | 82 | 155 | 0 | 0 | Village 10 / Wolf 10 | 占位，后续替换 |

后续替换方式：运行 `scripts/run_winrate_experiment.py` 或 `scripts/multi_tier_experiment.py`，按 `experiment_id` 关联 PostgreSQL 的 `games`、`game_events`、`agent_decisions`、`evaluations`、`published_reviews`、`strategy_knowledge_docs` 与 `knowledge_usage_feedback` 后生成真实表。

## 4. 方案对比结果

### 4.1 检索策略已有报告

来源：`docs/experiments/retrieval_policy_results.md`。

| 评估口径 | 主要记录 | 数据状态 |
|---|---|---|
| 离线弱标注 | Query set 26，知识库规模 924，`hybrid_role_mbti_global` 与 `hybrid_role_alignment_phase` 并列第一 | 实验报告 |
| 在线 LLM 复核 | `same_role_all_mbti` 第一，`hybrid_role_mbti_global` 第二，失败 query 0/26 | 实验报告 |

可写结论：角色优先并带回退的混合检索在弱标注和 LLM 复核结果中优于纯 global_only。

不可写结论：不能把检索评估分数解释为真实对局胜率提升。

### 4.2 单角色检索量化结果

来源：`outputs/retrieval_effectiveness_current/results.json`、`outputs/retrieval_effectiveness_current/per_role_results.csv`、`outputs/retrieval_effectiveness_current/role_corpus_stats.csv`、`docs/PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md`。

![单角色检索路径与量化结果](assets/final_report/single-role-retrieval.svg)

默认策略 `hybrid_role_mbti_global` 的单角色路径为：`same_role_same_mbti -> same_role_all_mbti -> global`。当前离线 query set 中，默认策略 Coverage 为 1.0000，Effective@3 为 0.5000，P@3 为 0.2564，RoleBucketShare 为 0.9923，GlobalBucketShare 为 0.0077。精确 `same_role_same_mbti` 作为唯一策略时 Coverage 只有 0.1538，空检索 22/26，说明它适合作为优先桶，但当前不适合单独作为默认检索范围。

| Role | DefaultEff@3 | GlobalEff@3 | ExactEff@3 | Default P@3 | Coverage | RoleBucket | GlobalBucket | 诊断 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Guard | 1.0000 | 0.0000 | 0.0000 | 0.5000 | 1.0000 | 1.0000 | 0.0000 | 当前命中充分，需补 role+MBTI 细分卡 |
| Hunter | 1.0000 | 0.5000 | 0.0000 | 0.5000 | 1.0000 | 1.0000 | 0.0000 | 当前命中充分，需补 role+MBTI 细分卡 |
| Seer | 0.6000 | 0.0000 | 0.2000 | 0.3333 | 1.0000 | 1.0000 | 0.0000 | 覆盖稳定，Top-3 高相关密度仍需提升 |
| Villager | 0.5000 | 0.3333 | 0.0000 | 0.2778 | 1.0000 | 0.9667 | 0.0333 | 覆盖稳定，需扩充村民关键局面策略 |
| Werewolf | 0.2857 | 0.0000 | 0.1429 | 0.1429 | 1.0000 | 1.0000 | 0.0000 | 相关性是主要短板，需补狼人阶段/动作策略 |
| Witch | 0.2500 | 0.2500 | 0.0000 | 0.0833 | 1.0000 | 1.0000 | 0.0000 | 相关性是主要短板，需补救/毒关键局面策略 |

可写结论：默认单角色检索可以稳定覆盖 6 个核心角色，并且检索结果主要来自本角色策略桶。结论边界：每个角色 query 数仍偏少，当前结果是离线弱标注检索有效性，不是在线对局因果提升。

### 4.3 方案对比占位模板

以下为方案对比展示模板，数值为占位示例，后续需用真实在线对局实验替换。该表用于展示汇报图表结构，不用于证明某一检索策略在线最优。

![检索策略对比占位图表](assets/final_report/placeholder-retrieval-policy.svg)

| 方案 | 平均决策分 | P@3 | nDCG@5 | 策略命中率 | 策略使用率 | 平均知识产出 | 对局完成率 | 平均检索延迟 | candidate 泄露数 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| global_only（占位） | 0.62 | 0.42 | 0.50 | 40% | 25% | 20 | 90% | 25ms | 0 | 仅全局策略 |
| same_role_all_mbti（占位） | 0.68 | 0.76 | 0.81 | 75% | 45% | 35 | 92% | 30ms | 0 | 同角色策略 |
| same_role_same_mbti（占位） | 0.70 | 0.78 | 0.83 | 78% | 48% | 36 | 88% | 32ms | 0 | 可能受 MBTI 稀疏影响 |
| hybrid_role_mbti_global（占位） | 0.71 | 0.80 | 0.85 | 80% | 50% | 38 | 92% | 35ms | 0 | 角色 + MBTI + 全局兜底 |
| hybrid_role_alignment_phase（占位） | 0.69 | 0.76 | 0.82 | 76% | 46% | 34 | 90% | 37ms | 0 | 约束更细 |

## 5. 结论边界

### 5.1 已经有真实证据的内容

| 内容 | 证据 |
|---|---|
| 系统具备完整 Play -> Evaluate -> Evolve 架构 | 代码、README、`docs/DATA_FLOW.md` |
| 数据库证据链已落地 | PostgreSQL 当前快照，22 表和核心记录数 |
| 存在 20 局成功运行实验 | `data/experiment/batch_summary.json` |
| 存在检索策略对比报告 | `docs/experiments/retrieval_policy_results.md` |
| strict mode 有项目验收文档记录 | `docs/backend_acceptance_criteria.md` |

### 5.2 需要后续补实验的内容

| 内容 | 当前不足 | 补充方式 |
|---|---|---|
| Track C 是否提升整体胜率 | multi-tier 完成数不均 | 重新跑 paired seed 多局实验 |
| 检索策略在线最优 | 主要是离线/LLM 复核 | 跑在线 ablation |
| Track B 复盘分析有效性 | 缺人工一致性 | 抽样标注 + agreement |
| 前端展示稳定性 | 本轮未跑视觉验收 | Playwright + WebSocket 延迟 |
| active 池质量变化 | 当前快照和历史验收口径不同 | 冻结 snapshot 并记录 promotion |

### 5.3 目前只能作为设计判断的内容

| 设计判断 | 原因 |
|---|---|
| 三层 Prompt 更利于策略回流 | 有代码和问题记录，但缺直接对照实验 |
| AgentLoop 工具调用提升决策质量 | 有 tool_trace，但缺工具开关 A/B |
| 4-filter 降低策略污染风险 | 有机制和 active 隔离记录，但缺误杀/漏召回率 |
