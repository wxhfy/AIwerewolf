# AI Werewolf

AI 狼人杀多智能体对战系统。CognitiveAgent (Observe-Think-Act) 在严格信息隔离下推理、发言、投票，
赛后通过三级评分级联定位关键失误，复盘结果沉淀为带可信度和权限控制的策略知识，回流到下一代 Agent。

> **当前版本**: `main` @ `40a76fe` | **验证**: STRICT MODE PASSED | **文档**: 已收敛

---

## 三条轨道

| Track | 名称 | 状态 | 核心模块 |
|-------|------|------|----------|
| **A** | 基础对局 | ✅ | `backend/engine/game.py`, `backend/agents/cognitive/` |
| **B** | 评测复盘 | ✅ | `backend/eval/per_step_scorer.py`, `backend/eval/track_b.py` |
| **C** | 自进化 | ✅ | `backend/eval/knowledge_abstractor.py`, `backend/eval/evolution.py` |

```
Play    = CognitiveAgent + RoleStrategyCard + WolfTeamView + BeliefTracker
Evaluate = 三级评分级联 + 反事实推演 + Judge 校准 + 结构化报告
Evolve  = L0-L4 知识分层 + 4-filter 安全管线 + 回验 + A/B Leaderboard
```

---

## 快速开始

```bash
# 1. 后端依赖
python -m pip install -r requirements.txt

# 2. 配置
cp .env.example .env  # 填入 DOUBAO_API_KEY

# 3. 启动 PostgreSQL
make db-up
make db-init

# 4. 启动预检
python -m backend.ops.preflight

# 5. 跑一局完整 LLM 对局
python scripts/run_full_llm_pipeline.py

# 6. 启动后端
make dev   # uvicorn backend.app:app --port 8000 --reload

# 7. 启动前端
cd frontend && npm install --legacy-peer-deps && npm run dev
# 浏览器打开 http://localhost:3001
```

---

## 架构速览

```
Game Engine (WerewolfGame, parallel _batch_ask)
  → PlayerView (3-view 信息隔离, 92 项检查)
  → CognitiveAgent (Observe → AgentLoop → Decision)
    ├── Layer 1: MBTI Persona (怎么说)
    ├── Layer 2: Role Identity (我是谁)
    └── Layer 3: Strategy + Tools (怎么玩)
  → agent_decisions (PostgreSQL, 含 tool_trace + strategy IDs)
  → PerStepScorer (Tier1→Tier2→Tier3 cascade)
  → KnowledgeAbstractor (candidate lessons)
  → StrategyRetriever (BM25 + 4-filter → Agent Prompt → 下一局)
```

详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 和 [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md)。

---

## 核心命令

```bash
# 全量严格验证
python scripts/run_backend_full_strict.py

# 多 Tier 对比实验
python scripts/multi_tier_experiment.py

# 信息隔离验证
python scripts/verify_visibility_strict.py

# 全量测试
pytest tests/ -q

# 数据库连接
psql -h 127.0.0.1 -p 5433 -U werewolf -d werewolf
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 + FastAPI + WebSocket |
| 前端 | Next.js 15 + React 19 + Tailwind CSS |
| 数据库 | PostgreSQL 15 (Docker @ 5433) |
| LLM | 火山方舟 doubao-seed-2.0-pro (ep-20260514115354-k4jz4) |
| 检索 | BM25 + 关键词倒排索引 (GPU-free) |
| 评测 | scikit-learn + LLM Judge Panel (三法官 + Critic) |

---

## 数据库 (21 张表)

| 类别 | 表 |
|------|-----|
| 对局 | `games`, `players`, `game_events`, `game_snapshots` |
| Agent | `agent_decisions`, `agent_versions` |
| 评测 | `evaluations`, `review_reports`, `published_reviews`, `leaderboard_entries` |
| 知识 | `strategy_knowledge_docs`, `strategy_graph_links`, `role_strategy_cards`, `strategy_patches` |
| 进化 | `evolution_tournaments`, `evolution_rounds`, `knowledge_usage_feedback`, `strategy_snapshots` |
| 人设 | `personas`, `persona_role_adapters` |
| 实验 | `experiments` |

---

## 文档

| 文档 | 内容 |
|------|------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 系统架构总览 |
| [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) | 端到端数据流 & 证据链 |
| [`docs/backend_acceptance_criteria.md`](docs/backend_acceptance_criteria.md) | 后端验收标准 |
| [`docs/DEVELOPMENT_ISSUES.md`](docs/DEVELOPMENT_ISSUES.md) | 开发问题追踪 (50+ 条) |
| [`docs/DOC_INDEX.md`](docs/DOC_INDEX.md) | 文档索引 |
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | 项目状态速览 |

---

## 项目结构

```
backend/
├── engine/               # 游戏引擎 (game.py, visibility.py)
├── agents/cognitive/     # CognitiveAgent (Observe-Think-Act)
├── eval/                 # 评测系统 (PerStepScorer, Judge, KnowledgeAbstractor)
├── db/                   # 数据库 (models, database, persist)
├── llm/                  # LLM 客户端
└── ops/                  # 运维 (preflight.py)

frontend/                 # Next.js 观战 UI

configs/
├── rule_variant_standard.yaml
└── strategy_library.yaml

scripts/
├── run_backend_full_strict.py
├── multi_tier_experiment.py
└── verify_visibility_strict.py
```
