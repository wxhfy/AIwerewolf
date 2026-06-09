# AI Werewolf

<p align="center">
  <img src="docs/assets/ai-werewolf-icon.svg" alt="AI Werewolf logo" width="112">
</p>

<p align="center">
  <strong>面向社会推理博弈的多智能体狼人杀研究平台</strong><br>
  Play complete games, evaluate every decision, and evolve reusable strategy knowledge.
</p>

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-blue)](https://www.python.org/)
[![CI](https://img.shields.io/badge/CI-lint%20%2B%20test-brightgreen)](.github/workflows/ci.yml)
[![PostgreSQL](https://img.shields.io/badge/db-PostgreSQL%2016-336791?logo=postgresql)](https://www.postgresql.org/)
[![Next.js](https://img.shields.io/badge/frontend-Next.js%2014-black?logo=next.js)](https://nextjs.org/)

## 项目定位

AI Werewolf 是一个面向多智能体博弈研究和工程展示的狼人杀系统。项目围绕规则引擎、信息隔离、Agent 决策、赛后评测和策略知识回流构建，将复杂对局拆成可验证、可复盘、可迭代的工程模块。

主线能力：

| 主线 | 项目实现 |
|---|---|
| Play | `WerewolfGame` 负责 7-12 人对局、昼夜阶段、警徽、PK、遗言、猎人开枪、白狼王自爆和真人混战 |
| Evaluate | Track B 基于对局事件和 Agent 决策生成逐步复盘、`PublishedReview`、运行指标和 leaderboard |
| Evolve | Track C 抽取策略知识，维护 `candidate -> active -> deprecated` 生命周期，并通过 `StrategyRetriever` 回流下一局 Agent |
| Interaction | Next.js 前端提供大厅、观战、真人操作、人格配置、单局复盘和统计看板 |

工程架构说明见 [`docs/ENGINEERING_ARCHITECTURE.md`](docs/ENGINEERING_ARCHITECTURE.md)，核心模块说明见 [`docs/PROJECT_MODULE_DESIGN.md`](docs/PROJECT_MODULE_DESIGN.md)。

## 系统架构

AI Werewolf 按“前端体验 -> API 编排 -> 规则引擎 -> Agent 决策 -> 复盘评测 -> 策略进化 -> 数据持久化”组织。前端只负责展示和交互，游戏真相、行动校验、阶段推进和私有信息过滤都在后端完成；Agent 只通过 `PlayerView` 观察局面，并以结构化 `Decision` 表达意图。

设计原则：

| 原则 | 工程体现 |
|---|---|
| 规则由引擎主控 | Agent 只提交 `Decision`，状态推进、行动校验和结算都由 `WerewolfGame` 完成 |
| 信息隔离在后端完成 | `GameState` 投影为 `PlayerView` 和 public snapshot，前端只渲染后端给出的视图 |
| Agent 行为可组合 | Persona、Role、Strategy 三层 Prompt 配合 Memory、BeliefTracker、SocialModel 和工具调用 |
| 复盘证据可追溯 | `GameEvent`、`AgentDecision`、`PublishedReview` 和策略知识形成可回放证据链 |
| 策略迭代有生命周期 | Track C 新策略先进入候选池，赛后自动门禁和批处理治理会将高质量候选晋级为 active，并把低质、过期或超量候选归档为 deprecated |

## 已实现内容

| 方向 | 已实现能力 |
|---|---|
| 对局能力 | 7-12 人狼人杀配置、昼夜流程、警徽竞选、PK、遗言、猎人开枪、白狼王自爆、真人混战 |
| Agent 能力 | 角色化 `CognitiveAgent`、人格配置、记忆、社交模型、工具调用、策略检索和真实 LLM provider 接入 |
| 复盘能力 | Track B 逐决策评分、复盘报告、关键决策展示、leaderboard 和统计看板 |
| 进化能力 | Track C 策略知识抽取、candidate/active/deprecated 生命周期、策略检索回流 |
| 前端能力 | 大厅、对局观战、真人操作、单局复盘、统计看板、人格配置页 |
| 工程能力 | FastAPI REST/WebSocket、SQLAlchemy 持久化、配置化规则、pytest/ruff/CI、严格信息隔离验证 |

## 核心模块

### 对局引擎

入口：`backend/engine/game.py`

`WerewolfGame` 是游戏状态的唯一写入者，负责初始化玩家、分配角色、推进昼夜阶段、结算技能、处理投票和判断胜负。Agent 不能直接修改状态，只能提交 `Decision`，再由引擎按当前阶段和规则裁决。

### 阶段与行动规则

入口：`backend/engine/phases.py`, `backend/engine/actions.py`

阶段系统覆盖夜晚守卫、狼人行动、女巫行动、预言家查验、白天发言、警徽竞选、PK、投票、遗言和特殊技能。行动规则层负责检查 actor、target、技能次数和阶段约束，保证 LLM 输出不会绕过游戏规则。

### 信息隔离

入口：`backend/engine/visibility.py`

系统将完整 `GameState` 投影为每个玩家自己的 `PlayerView`。狼人只看到狼队可见信息，预言家只看到自己的查验结果，观众公开视图会隐藏夜晚具体行动，信息边界由后端强制保证。

### 角色注册与能力元数据

入口：`backend/engine/roles/registry.py`

RoleRegistry 是角色能力和展示信息的单一事实来源。可玩角色、模板角色、阵营、技能、夜晚顺序和前端展示都围绕它组织，方便后续扩展新角色而不破坏主流程。

### Agent 运行时

入口：`backend/agents/cognitive/`

`CognitiveAgent` 将角色目标、人格风格、短期记忆、信任判断、工具调用和策略检索组合起来，再调用真实 LLM provider 生成结构化决策。AgentLoop 将“观察 -> 思考 -> 调工具 -> 输出 Decision”固定成可审计流程，便于复盘和调试。

### 持久化与审计

入口：`backend/db/models.py`, `backend/db/persist.py`

系统将对局、玩家、事件、快照、Agent 决策、复盘报告、指标和策略知识写入数据库。这个审计链让一局游戏可以被回放、复盘、统计，也让 Track B 和 Track C 不依赖临时日志。

### 前端体验

入口：`frontend/app/`, `frontend/components/`, `frontend/hooks/`

前端提供大厅、观战页、真人操作页、单局复盘页、统计看板和人格配置页。它只渲染后端给出的 public/private snapshot，不自行推断隐藏信息，从产品层配合后端信息隔离。

## Track B：复盘评测

入口：`backend/eval/per_step_scorer.py`, `backend/eval/track_b.py`

Track B 的目标是把“谁赢了”拆解成“每一步为什么好或不好”。系统会读取对局事件、Agent 决策、发言、投票和技能使用记录，生成逐步评分、关键决策、复盘报告和 leaderboard。

核心输出：

| 输出 | 作用 |
|---|---|
| 逐决策评分 | 评价发言、投票、技能、时机和影响 |
| PublishedReview | 生成单局复盘报告和前端可展示材料 |
| Leaderboard | 按模型、Agent 版本、角色和行为维度聚合表现 |
| 决策证据链 | 将复盘结论追溯到具体事件和 Agent 输出 |

## Track C：策略进化

入口：`backend/eval/knowledge_abstractor.py`, `backend/agents/cognitive/retrieval_prod.py`

Track C 的目标是将复盘经验沉淀为可检索策略，并回流到下一局 Agent。系统从 Track B 的高光和失误中抽取策略知识，先进入 candidate 池，再通过质量、聚类和使用反馈晋级为 active，最后由 `StrategyRetriever` 按角色、阶段和适用条件完成检索。

## Track C 生命周期

Track C 的策略知识分两层触发：

| 层级 | 触发方式 | 作用 |
|---|---|---|
| 赛后自动门禁 | 每局结束后由 `run_post_game_scoring()` 调用 `promote_after_store(source_game_id=game_id)` | 只处理本局新知识，按质量、聚类和使用反馈把候选晋级为 active，并做轻量归档 |
| 批处理治理 | `python scripts/promote.py --mode lifecycle --apply` | 对全库执行质量晋级、反馈晋级、active 池剪枝、candidate 池上限治理和低质归档 |

生产 Agent 的策略检索默认只加载 `active` 策略。`candidate` 是待验证知识池，不会直接污染下一局 Prompt；批处理治理会限制候选堆积，低质、过期或超量候选进入 `deprecated`。

## 快速开始

### 1. 安装后端依赖

```bash
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，设置 `LLM_PROVIDER` 和对应 provider 的 API Key。正式 Demo 和结果统计使用真实 LLM provider。

### 2. 启动 PostgreSQL

```bash
docker run -d --name werewolf-pg \
  -e POSTGRES_USER=werewolf \
  -e POSTGRES_PASSWORD=werewolf_dev_password \
  -e POSTGRES_DB=werewolf \
  -p 5433:5432 postgres:16-alpine

python scripts/migrate_v2_columns.py
```

未配置 `DATABASE_URL` 时，后端会使用 SQLite 本地模式，适合轻量本地验证。

### 3. 启动后端

```bash
make dev
# http://localhost:8000/docs
```

### 4. 启动前端

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
# http://localhost:3001
```

如果 3001 被占用：

```bash
PORT=3002 npm run dev
```

## Demo 路线

| 入口 | 路由 | 展示内容 |
|---|---|---|
| API 文档 | `http://localhost:8000/docs` | 后端接口、房间、对局、复盘、策略知识 API |
| 大厅 | `http://localhost:3001/` | 创建房间、选择 AI/Human 席位、进入对局 |
| 对局观战 | `/room/[id]/play` | 阶段流转、玩家状态、发言、投票、事件流、观众视角 |
| 真人操作 | `/room/[id]/human` | 真人玩家身份视图、目标选择、行动提交 |
| 单局复盘 | `/games/[id]/report` | PublishedReview、关键决策、证据链和回放信息 |
| 统计看板 | `/eval/dashboard` | 多局统计、leaderboard、角色与策略对比 |
| 人格配置 | `/personas` | MBTI 人格与 Agent 行为参数 |

## 技术栈

| 层 | 技术 |
|---|---|
| 后端服务 | Python 3.8+ / FastAPI / WebSocket |
| 游戏引擎 | dataclass + Enum 纯逻辑规则引擎 |
| Agent | `CognitiveAgent` / AgentLoop / Memory / SocialModel / StrategyRetriever |
| LLM 接入 | `backend.llm.create_client()` |
| 数据库 | SQLAlchemy；PostgreSQL 优先，支持 SQLite 本地模式 |
| 前端 | Next.js 14 / React 18 / TypeScript / Tailwind CSS |
| 测试与质量 | pytest / ruff / frontend lint / build / GitHub Actions |

## 验证命令

| 目标 | 命令 |
|---|---|
| 后端配置测试 | `python -m pytest tests/test_llm_config.py -q` |
| 信息隔离专项 | `python scripts/verify_visibility_strict.py` |
| 后端 E2E smoke | `python scripts/e2e_smoke.py` |
| 严格模式验收 | `python scripts/run_backend_full_strict.py` |
| 后端 lint | `ruff check backend/ scripts/ tests/ configs/` |
| 前端构建 | `cd frontend && npm run build` |

## 项目结构

```text
AIwerewolf/
├── backend/
│   ├── app.py                 # FastAPI / REST / WebSocket
│   ├── engine/                # WerewolfGame、规则、阶段、信息隔离
│   ├── agents/cognitive/      # CognitiveAgent、AgentLoop、Memory、Retriever
│   ├── eval/                  # Track B/C 复盘评测与知识进化
│   ├── db/                    # SQLAlchemy models 和持久化
│   └── protocols/             # Room schema 和 RoomManager
├── frontend/
│   ├── app/                   # Next.js App Router 页面
│   ├── components/            # UI 和 game 组件
│   ├── hooks/                 # 对局流和真人操作 hooks
│   └── types/                 # 后端契约 TS 镜像
├── scripts/                   # smoke、实验、迁移、报告和验证脚本
├── tests/                     # pytest 和 UI smoke
├── configs/                   # 规则、策略和实验配置
├── docs/                      # 架构、模块、需求和参考文档
└── docs/assets/               # README logo 等轻量项目介绍资产
```

## 仓库内容

| 内容 | 当前位置 |
|---|---|
| 代码仓库 | `backend/`, `frontend/`, `scripts/`, `tests/`, `configs/` |
| 产品原型 | Next.js 前端：大厅、观战、真人操作、复盘、人格配置 |
| Demo 链接 | 本地后端 `http://localhost:8000/docs`，本地前端 `http://localhost:3001` |
| 项目介绍文档 | `docs/FINAL_SHOWCASE_REPORT.md`, `docs/FINAL_DELIVERY_PACKAGE.md`, `docs/ENGINEERING_ARCHITECTURE.md`, `docs/PROJECT_MODULE_DESIGN.md`, `docs/prd.md` |
| 轻量展示资产 | `docs/assets/ai-werewolf-icon.svg` |

## 文档导航

| 文档 | 说明 |
|---|---|
| [`docs/README.md`](docs/README.md) | 文档阅读顺序和归档说明 |
| [`docs/FINAL_SHOWCASE_REPORT.md`](docs/FINAL_SHOWCASE_REPORT.md) | GitHub 粗略展示报告和核心量化概览 |
| [`docs/FINAL_DELIVERY_PACKAGE.md`](docs/FINAL_DELIVERY_PACKAGE.md) | 仓库交付内容和清洁边界 |
| [`docs/ENGINEERING_ARCHITECTURE.md`](docs/ENGINEERING_ARCHITECTURE.md) | 分层架构、运行时序、信息隔离、数据闭环和 Track C 生命周期说明 |
| [`docs/PROJECT_MODULE_DESIGN.md`](docs/PROJECT_MODULE_DESIGN.md) | 核心模块设计与实现说明 |
| [`docs/prd.md`](docs/prd.md) | 需求和系统设计目标 |

## GitHub 仓库边界

应进入仓库的是源码、测试、配置模板、CI、README、粗略展示文档和必要的小型 logo 资产；不应进入仓库的是 `.env`、真实 API Key、本地数据库、运行日志、实验输出、evidence 快照、截图、PPT/PDF、长篇过程材料、`data/`、`references/`、`.venv/`、`node_modules/` 和 `.next/`。

提交前可检查：

```bash
git status --short --ignored
git ls-files | rg '(^|/)(\.env$|__pycache__/|node_modules/|\.next/|data/|models/|outputs/|references/|docs/evidence/|docs/experiments/|docs/presentations/|docs/assets/(readme|closure|final_report)/|docs/wiki/)|\.(db|sqlite|log|jsonl|pptx|pdf|png|jpe?g)$'
```

## License

MIT © 2026 wxhfy
