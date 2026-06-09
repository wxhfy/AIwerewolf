# 真实 LLM 对局与决策健康摘要

生成时间：2026-06-09T15:36:46+08:00

本文件是最终展示用摘要，对应机器可读快照：`PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json`。原始输出目录位于本地 `outputs/` 与 `docs/experiments/`，不进入 GitHub。

## 1. 汇总结果

| 指标 | 结果 |
|---|---:|
| 汇总 run | 24 |
| 完成对局 | 78 |
| 真实 LLM 决策 | 1,936 |
| fallback decisions | 0 |
| invalid decisions | 0 |
| smoke / pipeline health runs | 7 |

展示口径：这组数据用于说明真实 LLM 对局已经进入可审计链路，决策落库、Track B/C 后处理和健康字段均可被统一统计。

## 2. 可展示证据

| 证据层 | 说明 |
|---|---|
| 对局层 | 多批真实 LLM 对局产生完整 game run 记录，可追溯 seed、winner、days、events 和 decision count |
| 决策层 | `agent_decisions` 中保留原始响应、解析结果、reasoning、tool trace 和策略检索元数据 |
| 健康层 | 当前摘要口径下 fallback 和 invalid 均为 0，适合支撑 strict 决策健康展示 |
| 复盘层 | 完成对局可进入 Track B PublishedReview、leaderboard 和 Track C 知识抽取 |

## 3. 报告使用建议

最终报告中建议只引用以下内容：

| 可引用内容 | 推荐写法 |
|---|---|
| 真实 LLM 对局规模 | “项目已累计形成 78 局真实 LLM 完成对局样本。” |
| 决策规模 | “真实 LLM 决策 1,936 条，进入数据库和复盘链路。” |
| 决策健康 | “展示口径下 fallback/invalid 为 0，说明 strict 决策链路可审计。” |
| 工程价值 | “系统能把真实对局转化为复盘、排行榜和策略知识回流证据。” |

更细的 run 级字段请以 `PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json` 为复核来源，不作为默认展示正文。
