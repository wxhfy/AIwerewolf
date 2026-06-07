# AI Werewolf

多智能体狼人杀 — 对战 · 复盘 · 进化

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)
[![CI](https://img.shields.io/badge/CI-lint%20%2B%20test-brightgreen)](.github/workflows/ci.yml)
[![PostgreSQL](https://img.shields.io/badge/db-PostgreSQL%2016-336791?logo=postgresql)](https://www.postgresql.org/)
[![Next.js](https://img.shields.io/badge/frontend-Next.js%2014-black?logo=next.js)](https://nextjs.org/)

---

## 项目概述

每个 AI 玩家拥有独立的 MBTI 人格、角色技能和认知架构，在严格信息隔离下进行推理、对话和决策。赛后通过 LLM Judge 复盘，提取策略知识沉淀到知识库，回流到下一代 Agent。

### 三层架构

```
Layer 1  MBTI 人格    →  决定"怎么思考"（认知风格、说话方式）
Layer 2  Role 身份    →  定义"我是谁"（角色技能、胜利条件、反模式清单）
Layer 3  Track C 策略 →  教"怎么赢"（动态检索知识库，加载历史对局经验）
```

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM
cp .env.example .env
# 编辑 .env，设置 ANTHROPIC_AUTH_TOKEN 和 ANTHROPIC_BASE_URL

# 3. 启动 PostgreSQL（Docker，端口 5433）
docker run -d --name werewolf-pg \
  -e POSTGRES_USER=werewolf \
  -e POSTGRES_PASSWORD=wolf_secret_2026 \
  -e POSTGRES_DB=werewolf \
  -p 5433:5432 postgres:16-alpine

# 4. 启动后端
make dev
# → http://localhost:8000/docs

# 5. 启动前端（另开终端）
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
| LLM | Anthropic-format 端点：DeepSeek V4 Pro/Flash via `api.deepseek.com/anthropic` |
| 检索 | BM25 + 倒排索引 · Agent 工具调用 |
| 评测 | LLM Judge Panel · 反事实推演 |

### LLM 客户端

`backend/llm/` 支持多种 API 格式：

| Client | 格式 | 端点 |
|--------|:---:|------|
| `AnthropicClient` | Anthropic Messages API | `api.deepseek.com/anthropic` · `ark.cn-beijing.volces.com/api/coding/v1` |
| `DeepSeekClient` | OpenAI Chat Completions | `ark.cn-beijing.volces.com/api/v3` · `api.deepseek.com` |

Provider 通过 `.env` 中 `LLM_PROVIDER` 切换（`anthropic` / `doubao` / `deepseek`）。

---

## 项目结构

```
AIwerewolf/
├── backend/
│   ├── engine/              # 游戏引擎（WerewolfGame, PlayerView, 阶段流转）
│   ├── agents/cognitive/    # CognitiveAgent（Observe → Think → Act）
│   ├── eval/                # 评测（LLM Judge, 复盘, 知识提取）
│   ├── llm/                 # LLM 客户端（Anthropic + OpenAI 双格式）
│   ├── db/                  # ORM + 持久化
│   └── protocols/           # WebSocket / Room
├── frontend/                # Next.js 观战 UI
│   └── app/
│       ├── page.tsx          # 大厅
│       ├── evolution/        # 策略进化面板
│       ├── room/[id]/play/   # 对局观战
│       └── eval/dashboard/   # 评测仪表盘
├── scripts/                 # 实验、基准测试、验证
├── tests/                   # 测试套件
├── configs/                 # 规则配置
├── docs/                    # 文档、实验报告
└── data/                    # 实验数据、知识库
```

---

## 关键页面

| 页面 | 路由 | 说明 |
|------|------|------|
| 大厅 | `/` | 创建对局、进入房间 |
| 对局观战 | `/room/[id]/play` | 实时观战，主持/观众视角切换 |
| 人类玩家 | `/room/[id]/human` | 人类玩家操作面板 |
| 策略进化 | `/evolution` | 消融实验、策略卡片、知识库、B/C 验收 |
| 评测仪表盘 | `/eval/dashboard` | 单局报告、对局统计 |
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
| [`backend_acceptance_criteria.md`](docs/backend_acceptance_criteria.md) | B/C 验收标准 |
| [`DEVELOPMENT_ISSUES.md`](docs/DEVELOPMENT_ISSUES.md) | 开发问题追踪与教训 |
| [`DATA_FLOW.md`](docs/DATA_FLOW.md) | 端到端数据流 |
| [`OPTIMIZATION_BENCHMARK.md`](docs/OPTIMIZATION_BENCHMARK.md) | API 调用优化效果基准 |
| [`prd.md`](docs/prd.md) | 产品需求文档 |
| [`experiments/`](docs/experiments/) | 实验报告（多层级胜率、Track C 验收） |

---

## License

MIT © 2025 wxhfy
