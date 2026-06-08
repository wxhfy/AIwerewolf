# AI Werewolf 项目汇报 PPT 大纲

> 生成文件：`AI_Werewolf_Project_Report.pptx`
> 生成日期：2026-06-08

## 1. 封面

AI Werewolf 多智能体狼人杀项目汇报

## 2. 汇报主线

项目定位、架构差异化、核心模块、验收边界

## 3. 项目定位

对战 Play、复盘 Evaluate、进化 Evolve 的研究平台

## 4. 与现有方法的不同

不是单 Prompt 模拟、不是上帝视角 Agent、不是只看胜负统计；核心是规则引擎主控、信息隔离、认知 Agent、复盘知识回流

## 5. 系统总体架构

前端、FastAPI/WebSocket、WerewolfGame、Agent、DB、Track B/C

## 6. 单局对局流程

夜晚、白天、终局与赛后处理

## 7. 核心模块清单

引擎、Visibility、Agent、Track B、Track C、前端

## 8. 信息隔离

GameState 与 PlayerView 分离，92/92 边界检查

## 9. CognitiveAgent

三层 Prompt 与工具调用式决策循环

## 10. 闭环主线

Play -> Evaluate -> Evolve -> Retrieve

## 11. Track B

复盘分析、报告生成、证据引用

## 12. Track C

知识生命周期与安全回流

## 13. 产品化界面

大厅、对局、Human、复盘、进化、Persona

## 14. 自动化验收

pytest、E2E、visibility、frontend、demo、B/C 专项

## 15. 修复与风险

本轮修复项、真实 LLM 长跑和 A/B 补验边界

## 16. 总结与下一步

能玩、能解释、能积累；补真实验收与多局 A/B
