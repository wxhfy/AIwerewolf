# AI Werewolf 文档索引

> 2026-06-05

---

## 展示文档（给评委）

| 文档 | 内容 |
|------|------|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | 系统架构总览 — CognitiveAgent + 三级评分 + 知识自进化 |
| **[DATA_FLOW.md](DATA_FLOW.md)** | 端到端数据流 & 证据链 — Game → Decision → Score → Knowledge → 检索闭环 |
| **[backend_acceptance_criteria.md](backend_acceptance_criteria.md)** | 后端验收标准 — 18/22 Verified, STRICT MODE PASSED |
| **[evidence_chain_demo.md](evidence_chain_demo.md)** | 证据链演示 — 单条决策的完整追溯 |

---

## 产品 & 设计

| 文档 | 内容 |
|------|------|
| **[prd.md](prd.md)** | 产品需求规格 V1.3 — 规则引擎、角色系统、Agent 设计 |
| **[product_backend_spec.md](product_backend_spec.md)** | 后端产品规格 — 核心能力描述 |
| **[backend_user_journey.md](backend_user_journey.md)** | 用户旅程 — 从大厅到复盘 |
| **[REFERENCE.md](REFERENCE.md)** | 参考资料 — 研究文献、开源项目 |

---

## 实验 & 协议

| 文档 | 内容 |
|------|------|
| **[experiment_protocol.md](experiment_protocol.md)** | 实验协议 — Multi-Tier 对比设计 |
| **[retrieval_policy_design.md](retrieval_policy_design.md)** | 检索策略设计 — MBTI-scoped 检索 |
| **[experiments/track_c_acceptance_report.md](experiments/track_c_acceptance_report.md)** | Track C 验收报告 |

---

## 运维 & 问题

| 文档 | 内容 |
|------|------|
| **[DEVELOPMENT_ISSUES.md](DEVELOPMENT_ISSUES.md)** | 开发问题追踪 — 50+ 条踩坑记录与解决方案 |
| **[architecture_audit_20260604.md](architecture_audit_20260604.md)** | 2026-06-04 全系统架构审计 (已被后续修复 supersede) |

---

## 源码导航

```
backend/
├── engine/          # 游戏引擎 (game.py, visibility.py, models.py)
├── agents/cognitive/ # CognitiveAgent (agent.py, agent_loop.py, observe.py, retrieval_prod.py)
├── eval/            # 评测系统 (per_step_scorer.py, llm_judge.py, knowledge_abstractor.py)
├── db/              # 数据库 (models.py, database.py, persist.py)
└── ops/             # 运维 (preflight.py)

frontend/            # Next.js 观战 UI

configs/
├── rule_variant_standard.yaml  # 标准规则配置
└── strategy_library.yaml      # 策略知识库 (187 条)

scripts/
├── run_backend_full_strict.py  # 全量严格验证
├── run_full_llm_pipeline.py    # 完整 LLM 流程
└── multi_tier_experiment.py    # 多 Tier 对比实验
```

---

## 历史文档

开发过程中的设计文档和中间报告已归档至 [`archive/`](archive/):
- 架构设计: `architecture_improvement_blueprint_v2.md`, `solution_blueprint.md`
- Track B 报告 17 篇: `track_b_design.md`, `track_b_*.md`
- 旧版设计: `prompt_strategy_injection_v8.md`, `retrieval_final_design.md`

---

*由小爪整理 (๑•̀ㅂ•́)و✧*
