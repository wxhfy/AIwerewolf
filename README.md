# AI Werewolf

多智能体狼人杀 — 对战 · 复盘 · 进化

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)
[![CI](https://img.shields.io/badge/CI-lint%20%2B%20test-brightgreen)](.github/workflows/ci.yml)
[![PostgreSQL](https://img.shields.io/badge/db-PostgreSQL%2016-336791?logo=postgresql)](https://www.postgresql.org/)
[![Next.js](https://img.shields.io/badge/frontend-Next.js%2014-black?logo=next.js)](https://nextjs.org/)

---

## 项目概述

每个 AI 玩家拥有独立的 MBTI 人格、角色技能和认知架构，在严格信息隔离下进行推理、对话和决策。支持真人 vs AI 混战模式。赛后通过 LLM 复核和结构化复盘，提取策略知识沉淀到知识库，回流到下一代 Agent。

### 架构主线

项目围绕 **规则引擎主控 → 信息隔离投影 → 角色化 Agent 决策 → 结构化复盘 → 策略知识回流** 展开。核心设计目标是让 AI 狼人杀既能正确运行，又能证明每个 Agent 在它应当知道的信息范围内做决策。

| 架构优势 | 项目体现 |
|------|------|
| 规则稳定 | `WerewolfGame` 是状态唯一写入者，Agent 只提交行动意图 |
| 信息可信 | `GameState` 与 `PlayerView` 分离，隐藏身份和私有事件不会进入 Agent 输入 |
| 角色可扩展 | RoleRegistry、Phase、Action、Skill 分层，新增角色不需要把规则写进 Prompt |
| 决策可解释 | GameEvent、AgentDecision、PublishedReview 串起可回放证据链 |
| 策略可迭代 | 赛后经验沉淀为版本化 StrategyKnowledgeDoc，经 Retriever 注入下一局；Track C Wiki/Hermes 承接长期知识编译 |

完整架构说明见 [`docs/ARCHITECTURE_DESIGN_GUIDE.md`](docs/ARCHITECTURE_DESIGN_GUIDE.md)。

### 与常见方案的区别

| 常见方案 | 本项目设计 |
|------|------|
| 把狼人杀做成单轮 Prompt 或脚本裁判 | 规则引擎主控状态和裁决，Agent 只表达可验证的行动意图 |
| 直接把全量历史塞给模型 | 公共信息、私有信息、角色技能和历史记忆分层投影，避免身份和夜晚事件泄露 |
| 角色差异主要依赖 Prompt 文案 | MBTI 人格、角色约束、技能调度和策略检索拆成独立层，行为差异可配置、可测试 |
| 赛后只输出胜负或自然语言总结 | 对局事件、决策、复盘、反事实和知识回流结构化保存，能追溯到具体回合和行动 |
| 新策略直接覆盖旧策略 | Track C 使用 raw / refined / canonical 生命周期、版本组和 supersede 关系，优先使用经过验证的后期策略 |

### 三层架构

```
Layer 1  MBTI 人格    →  决定"怎么思考"（认知风格、说话方式）
Layer 2  Role 身份    →  定义"我是谁"（角色技能、胜利条件、反模式清单）
Layer 3  Track C 策略 →  教"怎么赢"（Retriever 加载已验证的版本化策略；Wiki/Hermes 承接长期知识设计）
```

Track C 不把每次复盘总结都当作最终策略。新经验先进入 `raw` 候选层，经过复盘验证后提升为 `refined`，稳定策略再沉淀为 `canonical`；后续版本通过 `version_group`、`doc_version` 和 `supersedes_doc_ids` 关联旧策略，使越往后的有效经验更容易被检索到，同时避免未经验证的新总结压过稳定知识。

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM
cp .env.example .env
# 编辑 .env，设置 LLM_PROVIDER 和对应 API Key（如 DOUBAO_API_KEY / DEEPSEEK_API_KEY）

# 3. 启动 PostgreSQL（Docker，端口 5433）
docker run -d --name werewolf-pg \
  -e POSTGRES_USER=werewolf \
  -e POSTGRES_PASSWORD=werewolf_dev_password \
  -e POSTGRES_DB=werewolf \
  -p 5433:5432 postgres:16-alpine

# 4. 初始化 / 迁移数据库结构
python scripts/migrate_v2_columns.py

# 5. 启动后端
make dev
# → http://localhost:8000/docs

# 6. 启动前端（另开终端）
cd frontend && npm install && npm run dev
# → http://localhost:3001
```

### 跑一局完整对局

```bash
# 严格模式，单局
python scripts/llm_game_smoke.py --seed 1 --max-seed 1

# 多层级消融实验
python scripts/run_experiment.py --games 12
```

---

## 技术栈

| 层 | 技术 |
|------|------|
| 后端 | Python 3.8+ · FastAPI · WebSocket |
| 前端 | Next.js 14 · React 18 · Tailwind CSS |
| 数据库 | PostgreSQL 16（Docker，端口 5433） |
| LLM | `backend.llm.create_client()` 统一接入，支持 doubao / dsv4flash / ark / deepseek / anthropic / weapi / mimo |
| 检索 | BM25 + 倒排索引 · Agent 工具调用 |
| 复盘 | LLM 复核 · 反事实推演 |

### LLM 客户端

`backend/llm/` 支持多种 API 格式和 provider：

| Client | 格式 | 端点 |
|--------|:---:|------|
| `AnthropicClient` | Anthropic Messages API | Anthropic-compatible endpoints |
| `DeepSeekClient` | OpenAI Chat Completions | Volcengine Ark / DeepSeek / OpenAI-compatible endpoints |

Provider 通过 `.env` 中 `LLM_PROVIDER` 切换；`LLM_PROVIDER=fake` 仅用于 `_TEST_ALLOW_FAKE_LLM=true` 的测试环境。

---

## 项目结构

```
AIwerewolf/
├── backend/
│   ├── engine/              # 游戏引擎（WerewolfGame, PlayerView, 阶段流转）
│   ├── agents/cognitive/    # CognitiveAgent（Observe → Think → Act）
│   ├── eval/                # 复盘分析（LLM 复核、报告、知识提取）
│   ├── llm/                 # LLM 客户端（Anthropic + OpenAI 双格式）
│   ├── db/                  # ORM + 持久化
│   └── protocols/           # WebSocket / Room
├── frontend/                # Next.js 观战 UI
│   └── app/
│       ├── page.tsx          # 大厅
│       ├── room/[id]/play/   # 对局观战
│       └── eval/dashboard/   # 复盘仪表盘
├── scripts/                 # 实验、基准测试、验证
├── tests/                   # 测试套件
├── configs/                 # 规则配置
├── docs/                    # 文档、实验报告
└── data/                    # 本地实验数据（.gitignore，不进入 GitHub）
```

---

## 关键页面

| 页面 | 路由 | 说明 |
|------|------|------|
| 大厅 | `/` | 创建对局、进入房间 |
| 对局观战 | `/room/[id]/play` | 实时观战，主持/观众视角切换 |
| 人类玩家 | `/room/[id]/human` | 人类玩家操作面板 |
| 复盘仪表盘 | `/eval/dashboard` | 单局报告、对局统计 |
| 单局复盘 | `/games/[id]/report` | 完整复盘报告 |
| 人格管理 | `/personas` | MBTI 人格配置 |

---

## 对局验证

```bash
# 完整对局（真实 LLM）
python scripts/llm_game_smoke.py --seed 1 --max-seed 3

# 离线测试（无 API 调用）
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake pytest tests/ -q

# 后端严格验证
python scripts/run_backend_full_strict.py

# CI 检查
ruff check backend/ scripts/ tests/ configs/
ruff format --check backend/ scripts/ tests/ configs/
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [`prd.md`](docs/prd.md) | 产品需求规格（V2.0） |
| [`PROJECT_MODULE_DESIGN.md`](docs/PROJECT_MODULE_DESIGN.md) | 核心模块设计 |
| [`DATA_FLOW.md`](docs/DATA_FLOW.md) | 端到端数据流 |
| [`ARCHITECTURE_DESIGN_GUIDE.md`](docs/ARCHITECTURE_DESIGN_GUIDE.md) | 架构设计、差异化与证据索引 |
| [`TRACK_C_HERMES_LLM_WIKI_DESIGN.md`](docs/TRACK_C_HERMES_LLM_WIKI_DESIGN.md) | Track C 的 Hermes 自进化外循环 + LLM Wiki 增量设计 |
| [`FINAL_DELIVERY_PACKAGE.md`](docs/FINAL_DELIVERY_PACKAGE.md) | GitHub 最终交付包、展示路线和仓库边界 |
| [`PRODUCT_TECH_DOC.md`](docs/PRODUCT_TECH_DOC.md) | 产品技术文档 |
| [`PROJECT_ACCEPTANCE_REPORT.md`](docs/PROJECT_ACCEPTANCE_REPORT.md) | 项目总体验收报告 |
| [`OPTIMIZATION_BENCHMARK.md`](docs/OPTIMIZATION_BENCHMARK.md) | API 调用优化基准 |
| [`backend_acceptance_criteria.md`](docs/backend_acceptance_criteria.md) | B/C 验收标准 |

---

## License

MIT © 2026 wxhfy
