# AI Werewolf 文档导航

## 推荐阅读顺序

| 顺序 | 文档 | 用途 |
|---:|---|---|
| 1 | [`../README.md`](../README.md) | 项目定位、核心能力、运行方式和仓库边界 |
| 2 | [`FINAL_SHOWCASE_REPORT.md`](FINAL_SHOWCASE_REPORT.md) | 粗略展示报告和核心量化概览 |
| 3 | [`FINAL_DELIVERY_PACKAGE.md`](FINAL_DELIVERY_PACKAGE.md) | 仓库交付内容和清洁边界 |
| 4 | [`ENGINEERING_ARCHITECTURE.md`](ENGINEERING_ARCHITECTURE.md) | 分层架构图、运行时序图、信息隔离图、数据闭环图 |
| 5 | [`PROJECT_MODULE_DESIGN.md`](PROJECT_MODULE_DESIGN.md) | 核心模块职责、输入输出、内部流程和设计收益 |
| 6 | [`prd.md`](prd.md) | 项目需求、系统目标和验收范围 |

## 当前正式文档

| 类型 | 文件 |
|---|---|
| 粗略展示 | `FINAL_SHOWCASE_REPORT.md` |
| 交付边界 | `FINAL_DELIVERY_PACKAGE.md` |
| 架构图谱 | `ENGINEERING_ARCHITECTURE.md` |
| 模块设计 | `PROJECT_MODULE_DESIGN.md` |
| 需求文档 | `prd.md` |

## 仓库边界

GitHub 仓库默认不存放实验数据和交付附件。以下内容只保留在本地或单独提交渠道：

- 原始 evidence、评估 JSON/JSONL/CSV、数据库快照和运行日志
- PPT/PDF、截图、长篇过程报告和答辩附件
- API Key、`.env`、本地参考仓库、构建产物和缓存目录

## 文档清理策略

过程报告、长篇分析和历史设计记录不作为仓库默认入口。需要追溯时使用 Git history 或本地副本；GitHub 仓库保留项目介绍文档和可运行项目代码。

保留原则：

| GitHub 保留 | 本地保留 |
|---|---|
| 项目定位、架构、模块、需求、参考设计和粗略展示文档 | 实验结果、答辩附件、截图、PPT/PDF |
| 源码、测试、配置模板和 CI | 数据库、日志、evidence、实验输出 |
| README logo 等必要轻量资产 | 生成图表、临时图片和过程材料 |
