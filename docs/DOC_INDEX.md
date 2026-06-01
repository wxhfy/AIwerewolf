# AI Werewolf 文档索引

> 最后更新：2026-06-01

---

## 📚 核心文档

| 文档 | 用途 | 位置 |
|------|------|------|
| **README.md** | 项目总览、三大轨道介绍、快速开始 | `/README.md` |
| **REQUIREMENTS.md** | 课题需求文档（课程作业要求） | `/REQUIREMENTS.md` |
| **TODO.md** | 待办事项、开发计划 | `/TODO.md` |
| **AGENTS.md** | AI Agent 开发规范（给 Claude/Copilot 看的） | `/AGENTS.md` |
| **CLAUDE.md** | Claude Code 特定配置 | `/CLAUDE.md` |
| **SKILLS.md** | 技能模块文档 | `/SKILLS.md` |

---

## 🏗️ 架构设计

| 文档 | 内容 | 位置 |
|------|------|------|
| **prd.md** | 产品需求文档（详细功能规格） | `docs/prd.md` |
| **full-interaction-design.md** | 完整交互设计（UI/UX 流程） | `docs/full-interaction-design.md` |
| **architecture_cognitive_agent_v2.md** | 认知 Agent 架构设计 v2 | `docs/architecture_cognitive_agent_v2.md` |
| **retrieval_final_design.md** | 策略检索系统设计 | `docs/retrieval_final_design.md` |
| **prompt_strategy_injection_v8.md** | Prompt 策略注入设计 v8 | `docs/prompt_strategy_injection_v8.md` |
| **REFERENCE.md** | 参考资料 | `docs/REFERENCE.md` |

---

## 🎮 Track A — 基础对局引擎

| 文档 | 内容 | 位置 |
|------|------|------|
| **prompt_composition_audit.md** | Prompt 组成审计 | `docs/prompt_composition_audit.md` |
| **role_implementation_audit.md** | 角色实现审计 | `docs/role_implementation_audit.md` |
| **strategy_layer_audit.md** | 策略层审计 | `docs/strategy_layer_audit.md` |

---

## 📊 Track B — 评测复盘

| 文档 | 内容 | 位置 |
|------|------|------|
| **track_b_complete.md** | Track B 完成报告 | `docs/track_b_complete.md` |
| **track_b_rubric_alignment.md** | 评分标准对齐 | `docs/track_b_rubric_alignment.md` |
| **track_b_rubric_demo_report.md** | 评分演示报告 | `docs/track_b_rubric_demo_report.md` |
| **persona_role_strategy_eval_readiness.md** | 人设-角色-策略评估就绪度 | `docs/persona_role_strategy_eval_readiness.md` |
| **werewolf_scoring_benchmark_v7.md** | 评分基准 v7 | `docs/werewolf_scoring_benchmark_v7.md` |

### 核心模块（代码）
| 模块 | 功能 | 位置 |
|------|------|------|
| **ProcessScoreV3** | 角色归一化、置信度感知评分 | `backend/eval/process_score_v3.py` |
| **HybridScorer** | 规则+LLM+反事实混合评分 | `backend/eval/hybrid_scorer.py` |
| **PerStepScorer** | 逐步评分器（发言/投票/夜间行动） | `backend/eval/per_step_scorer.py` |
| **PersonaScorer** | 人设一致性评分 | `backend/eval/persona_scorer.py` |
| **StrategyScorer** | 策略影响评分 | `backend/eval/strategy_scorer.py` |
| **EloRating** | 跨局 Elo 排名 | `backend/eval/elo_rating.py` |
| **ScoreCalibrator** | Ridge 回归校准 | `backend/eval/calibration.py` |
| **V3Report** | V3 报告生成工具 | `backend/eval/v3_report.py` |

---

## 🧬 Track C — 自进化 Agent

| 文档 | 内容 | 位置 |
|------|------|------|
| **Track_C_Evolution_Agent_Plan.md** | Track C 进化 Agent 计划 | `docs/Track_C_Evolution_Agent_Plan.md` |

---

## 🔧 运维 & 问题

| 文档 | 内容 | 位置 |
|------|------|------|
| **DEVELOPMENT_ISSUES.md** | 开发问题记录（70KB，很详细） | `docs/DEVELOPMENT_ISSUES.md` |
| **project_risk_and_next_steps.md** | 项目风险与后续步骤 | `docs/project_risk_and_next_steps.md` |
| **full_project_audit_summary.md** | 全项目审计摘要 | `docs/full_project_audit_summary.md` |

---

## 📁 Skills（开发规范）

| 文档 | 内容 | 位置 |
|------|------|------|
| **00-team-overview.md** | 团队概览 | `skills/00-team-overview.md` |
| **10-git-workflow.md** | Git 工作流 | `skills/10-git-workflow.md` |
| **20-backend-conventions.md** | 后端规范 | `skills/20-backend-conventions.md` |
| **30-frontend-conventions.md** | 前端规范 | `skills/30-frontend-conventions.md` |
| **40-agent-development.md** | Agent 开发指南 | `skills/40-agent-development.md` |
| **50-api-contract.md** | API 契约 | `skills/50-api-contract.md` |
| **60-testing-ci.md** | 测试与 CI | `skills/60-testing-ci.md` |
| **70-ai-collaboration.md** | AI 协作指南 | `skills/70-ai-collaboration.md` |

---

## 🎯 快速导航

### 我想了解...
- **项目是什么** → `README.md`
- **作业要求** → `REQUIREMENTS.md`
- **怎么跑起来** → `README.md` 快速开始
- **代码规范** → `skills/` 目录
- **有什么问题** → `docs/DEVELOPMENT_ISSUES.md`

### 我要做...
- **改游戏逻辑** → `backend/engine/` + `docs/prompt_composition_audit.md`
- **改 Agent 策略** → `backend/agents/` + `docs/role_implementation_audit.md`
- **改评分系统** → `backend/eval/` + `docs/track_b_complete.md`
- **改前端** → `frontend/` + `docs/full-interaction-design.md`

### 我要查...
- **Track B 进度** → `docs/track_b_complete.md`
- **Track C 进度** → `docs/Track_C_Evolution_Agent_Plan.md`
- **已知问题** → `docs/DEVELOPMENT_ISSUES.md`
- **项目风险** → `docs/project_risk_and_next_steps.md`

---

## 📂 源码目录对应

```
AIwerewolf/
├── backend/
│   ├── agents/          # Agent 实现（LLM/Heuristic/Human）
│   ├── engine/          # 游戏引擎（核心逻辑）
│   ├── eval/            # 评测系统（Track B/C）
│   ├── llm/             # LLM 客户端封装
│   ├── db/              # 数据库模型
│   └── app.py           # FastAPI 后端入口
├── frontend/            # Next.js 前端
├── docs/                # 文档目录（本索引）
├── scripts/             # 脚本工具
├── tests/               # 测试用例
├── configs/             # 配置文件
└── data/                # 数据文件
```

---

*本文档由小爪自动整理 (๑•̀ㅂ•́)و✧*
