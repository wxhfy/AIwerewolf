# AI Werewolf 文档导航

> 这是评审和展示优先阅读的文档入口。历史过程材料已从 GitHub 默认文档集移除，避免默认阅读路径过长。

## 推荐阅读顺序

| 顺序 | 文档 | 用途 |
|---:|---|---|
| 1 | [`FINAL_SHOWCASE_REPORT.md`](FINAL_SHOWCASE_REPORT.md) | 最终展示用精简报告，包含最新关键结果 |
| 2 | [`ENGINEERING_ARCHITECTURE.md`](ENGINEERING_ARCHITECTURE.md) | 分层架构图、运行时序图、信息隔离图、数据闭环图 |
| 3 | [`PROJECT_MODULE_DESIGN.md`](PROJECT_MODULE_DESIGN.md) | 核心模块设计与实现入口 |
| 4 | [`evidence/README.md`](evidence/README.md) | 最新数据结果和证据文件索引 |
| 5 | [`FINAL_DELIVERY_PACKAGE.md`](FINAL_DELIVERY_PACKAGE.md) | 代码仓库、Demo、技术文档和展示材料交付清单 |

## 当前正式文档

| 类型 | 文件 |
|---|---|
| 最终展示 | `FINAL_SHOWCASE_REPORT.md` |
| 架构图谱 | `ENGINEERING_ARCHITECTURE.md` |
| 模块设计 | `PROJECT_MODULE_DESIGN.md` |
| 交付说明 | `FINAL_DELIVERY_PACKAGE.md` |
| 需求文档 | `prd.md` |
| 参考工作 | `PROJECT_REFERENCES.md` |
| 展示材料 | `presentations/` |
| 数据证据 | `evidence/` |

## 数据口径

最新可引用结果统一放在 [`evidence/`](evidence/)：

- `PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.*`：真实 LLM 对局与决策健康汇总。
- `PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.*`：Track B 多层复盘与 leaderboard 展示。
- `PROJECT_ROLE_RETRIEVAL_FACTS.json`：单角色策略检索量化结果。
- `PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.*`：策略使用与逐决策质量关联分析。
- `PROJECT_TARGET_SEAT_TRACKC_PILOT.*`：Track C target-seat pilot 结果。
- `PROJECT_METHOD_EFFECTIVENESS_FACTS.json`：方法有效性聚合事实快照。

## 文档清理策略

过程报告、长篇分析和历史设计记录不作为最终展示默认入口。需要追溯时使用 Git history 或本地副本；GitHub 仓库保留正式文档、最新 evidence 和可运行项目代码。

保留原则：

| 默认展示 | 归档 |
|---|---|
| 精简、最新、可展示、能直接支撑报告 | 过长、过期、过程性、诊断性材料 |
| 有明确数据来源和边界 | 中间尝试、旧口径、重复叙事 |
| 评审能在 5-10 分钟内理解 | 需要开发者背景才能读懂 |

## 报告写作建议

最终报告建议按以下结构写：

1. 项目定位：多智能体狼人杀，不是单 Prompt 游戏。
2. 分层架构：前端体验层、API 编排层、规则引擎层、Agent 认知层、评测进化层、数据层。
3. 核心实现：`WerewolfGame`、`PlayerView`、`CognitiveAgent`、`AgentLoop`、`StrategyRetriever`、Track B、Track C。
4. 展示结果：数据库规模、真实 LLM 对局、Track B、Track C、检索和策略使用。
5. 产品演示：大厅、观战、真人操作、复盘、看板。
6. 后续建议：扩大 target-seat paired A/B、补强角色策略卡、补充前端图表。
