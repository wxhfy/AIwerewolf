# 文档导航

## 推荐阅读顺序

| 顺序 | 文档 | 用途 |
|---:|---|---|
| 1 | [`../README.md`](../README.md) | 项目定位、核心能力和运行方式 |
| 2 | [`FINAL_SHOWCASE_REPORT.md`](FINAL_SHOWCASE_REPORT.md) | 粗略展示报告和核心量化概览 |
| 3 | [`ENGINEERING_ARCHITECTURE.md`](ENGINEERING_ARCHITECTURE.md) | 分层架构图、运行时序图、信息隔离图、数据闭环图 |
| 4 | [`PROJECT_MODULE_DESIGN.md`](PROJECT_MODULE_DESIGN.md) | 核心模块职责、输入输出、内部流程和设计收益 |
| 5 | [`prd.md`](prd.md) | 项目需求、系统目标和验收范围 |

## 检索精度证据

StrategyRetriever 已在正式文档中单独说明设计与评估口径：

| 文档 | 覆盖内容 |
|---|---|
| [`PROJECT_MODULE_DESIGN.md`](PROJECT_MODULE_DESIGN.md#5-strategyretriever) | `same_role_all_mbti` 默认策略、action_scope、上下文重排和量化表 |
| [`ENGINEERING_ARCHITECTURE.md`](ENGINEERING_ARCHITECTURE.md#7-strategyretriever-检索策略) | 检索流程图、策略对比和指标边界 |
| [`FINAL_SHOWCASE_REPORT.md`](FINAL_SHOWCASE_REPORT.md#5-量化概览多模型对局) | 结项展示用指标摘要 |

当前本地评估来源为 `outputs/retrieval_precision_after_high_precision_default_final/results.json`（local-only ignored）：26 条弱标注 query、374 条 active strategy docs，`same_role_all_mbti` P@3=1.0000、Effective@3=1.0000、nDCG@5=0.9885、Coverage=1.0000。
