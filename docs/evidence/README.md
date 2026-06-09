# 最新数据结果索引

> 本目录保存最终展示可引用的数据快照。`*.md` 便于阅读，`*.json` 便于复核和二次制图。

## 摘要结果

| 方向 | 当前结果 | 证据文件 |
|---|---:|---|
| 模块验收 | 14 / 14 | `PROJECT_METHOD_EFFECTIVENESS_FACTS.json` |
| 真实 LLM 完成对局 | 78 | `PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json` |
| 真实 LLM 决策 | 1,936 | `PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json` |
| strict formal completed games | 34 | `PROJECT_METHOD_EFFECTIVENESS_FACTS.json` |
| strict formal LLM decisions | 1,059 | `PROJECT_METHOD_EFFECTIVENESS_FACTS.json` |
| Track B showcase 完成对局 | 6 | `PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json` |
| Track B showcase 决策 | 216 | `PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json` |
| 单角色检索 Coverage | 100.00% | `PROJECT_ROLE_RETRIEVAL_FACTS.json` |
| 单角色检索 Effective@3 | 50.00% | `PROJECT_ROLE_RETRIEVAL_FACTS.json` |
| 默认策略 RoleBucketShare | 99.23% | `PROJECT_ROLE_RETRIEVAL_FACTS.json` |
| 策略使用决策质量差异 | +0.0823 | `PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json` |
| 严格分层 weighted delta | +0.0967 | `PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json` |
| Target-seat Seer paired seeds | 5 | `PROJECT_TARGET_SEAT_TRACKC_PILOT.json` |
| Target-seat adjusted delta | +20.6680 | `PROJECT_TARGET_SEAT_TRACKC_PILOT.json` |
| Target-seat process delta | +22.1840 | `PROJECT_TARGET_SEAT_TRACKC_PILOT.json` |

## 本地数据库快照

查询时间：2026-06-09。

| 表/记录 | 数量 |
|---|---:|
| games | 11,730 |
| players | 103,773 |
| game_events | 737,267 |
| game_snapshots | 4,963 |
| agent_decisions | 302,291 |
| evaluations | 126,003 |
| published_reviews | 4,955 |
| strategy_knowledge_docs | 217,310 |
| knowledge_usage_feedback | 195,859 |
| leaderboard_entries | 35 |

策略知识状态：

| 状态 | 数量 |
|---|---:|
| active | 387 |
| candidate | 216,906 |
| deprecated | 17 |

运行时策略反馈：

| 指标 | 数量/比例 |
|---|---:|
| retrieved | 195,859 |
| used | 78,410 |
| helpful | 63,932 |
| used / retrieved | 40.03% |
| helpful / used | 81.54% |

## 文件说明

| 文件 | 内容 |
|---|---|
| `PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.md/json` | 真实 LLM 对局和决策健康汇总 |
| `PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.md/json` | Track B 多层展示与 leaderboard 证据 |
| `PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md` | 单角色检索机制与量化说明 |
| `PROJECT_ROLE_RETRIEVAL_FACTS.json` | 单角色检索机器可读结果 |
| `PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.md/json` | 策略使用与逐决策质量关联分析 |
| `PROJECT_TARGET_SEAT_TRACKC_PILOT.md/json` | Track C target-seat paired pilot |
| `PROJECT_METHOD_EFFECTIVENESS_STATISTICS.md/json` | 方法有效性统计补充 |
| `PROJECT_METHOD_EFFECTIVENESS_FACTS.json` | 聚合事实快照 |
| `PROJECT_PROVIDER_PREFLIGHT.json` | Provider 可用性预检 |

## 使用边界

- 真实 LLM 完成对局、决策健康、复盘产物和检索覆盖率可以作为项目展示结果。
- 策略使用与逐决策质量差异是观测性关联，适合说明策略回流链路价值。
- Target-seat pilot 已展示正向趋势和链路健康，后续扩大 paired seeds 后再作为最终效果确认。
- Track C candidate 是候选知识池，生产 Agent 默认使用 active 策略池；candidate 进入 active 需要质量、聚类或版本验证门禁。
- 不建议在最终展示中展开历史过程日志或中间诊断结果；GitHub 默认文档集只保留最终展示口径。
