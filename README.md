# AI Werewolf

<p align="center">
  <img src="docs/assets/ai-werewolf-icon.svg" alt="AI Werewolf logo" width="112">
</p>

<p align="center">
  <strong>面向狼人杀博弈的多智能体认知决策与自进化系统</strong><br>
  Play complete games, evaluate every decision, and evolve reusable strategy knowledge.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <img src="https://img.shields.io/badge/db-PostgreSQL%2016-336791?logo=postgresql" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/frontend-Next.js%2014-black?logo=next.js" alt="Next.js">
</p>

## 项目定位

面向狼人杀博弈的多智能体认知决策与自进化系统。项目围绕规则引擎、信息隔离、Agent 决策、赛后评测和策略知识回流构建，将复杂对局拆成可验证、可复盘、可迭代的工程模块。

项目信息：

| 项目 | 内容 |
|---|---|
| GitHub 仓库 | https://github.com/wxhfy/AIwerewolf |
| 小组成员 | 付一涵、穆玉玲、王松磊 |

主线能力：

| 主线 | 项目实现 |
|---|---|
| Play | `WerewolfGame` 负责 7-12 人对局、昼夜阶段、警徽、PK、遗言、猎人开枪、白狼王自爆和真人混战 |
| Evaluate | Track B 基于对局事件和 Agent 决策生成逐步复盘、`PublishedReview`、运行指标和 leaderboard |
| Evolve | Track C 抽取策略知识，维护 `candidate -> active -> deprecated` 生命周期，并通过 `StrategyRetriever` 回流下一局 Agent |
| Interaction | Next.js 前端提供大厅、观战、真人操作、人格配置、单局复盘和统计看板 |

工程架构说明见 [`docs/ENGINEERING_ARCHITECTURE.md`](docs/ENGINEERING_ARCHITECTURE.md)，核心模块说明见 [`docs/PROJECT_MODULE_DESIGN.md`](docs/PROJECT_MODULE_DESIGN.md)。

## 系统架构

系统按“前端体验 -> API 编排 -> 规则引擎 -> Agent 决策 -> 复盘评测 -> 策略进化 -> 数据持久化”组织。前端只负责展示和交互，游戏真相、行动校验、阶段推进和私有信息过滤都在后端完成；Agent 只通过 `PlayerView` 观察局面，并以结构化 `Decision` 表达意图。

设计原则：

| 原则 | 工程体现 |
|---|---|
| 规则由引擎主控 | Agent 只提交 `Decision`，状态推进、行动校验和结算都由 `WerewolfGame` 完成 |
| 信息隔离在后端完成 | `GameState` 投影为 `PlayerView` 和 public snapshot，前端只渲染后端给出的视图 |
| Agent 行为可组合 | Persona、Role、Strategy 三层 Prompt 配合 Memory、BeliefTracker、SocialModel 和工具调用 |
| 复盘证据可追溯 | `GameEvent`、`AgentDecision`、`PublishedReview` 和策略知识形成可回放证据链 |
| 策略迭代有生命周期 | Track C 新策略先进入候选池，赛后自动门禁和批处理治理会将高质量候选晋级为 active，并把未达门禁、过期或超量候选归档为 deprecated |

## 已实现内容

| 方向 | 已实现能力 |
|---|---|
| 对局能力 | 7-12 人狼人杀配置、昼夜流程、警徽竞选、PK、遗言、猎人开枪、白狼王自爆、真人混战 |
| Agent 能力 | 角色化 `CognitiveAgent`、人格配置、记忆、社交模型、工具调用、策略检索和多模型 provider 接入 |
| 复盘能力 | Track B 逐决策质量评估、复盘报告、关键决策展示、leaderboard 和统计看板 |
| 进化能力 | Track C 策略知识抽取、candidate/active/deprecated 生命周期、策略检索回流 |
| 前端能力 | 大厅、对局观战、真人操作、单局复盘、统计看板、人格配置页 |
| 工程能力 | FastAPI REST/WebSocket、SQLAlchemy 持久化、配置化规则、严格信息隔离验证 |

核心模块设计详见 [`docs/PROJECT_MODULE_DESIGN.md`](docs/PROJECT_MODULE_DESIGN.md)，覆盖对局引擎、信息隔离、CognitiveAgent、AgentLoop、StrategyRetriever、PostgreSQL 证据链、PerStepScorer、Track C 知识层和前端控制台。

## Track B：复盘评测

入口：`backend/eval/per_step_scorer.py`, `backend/eval/track_b.py`

Track B 的目标是把“谁赢了”拆解成“每一步如何影响局势”。系统会读取对局事件、Agent 决策、发言、投票和技能使用记录，生成逐步质量评估、关键决策、复盘报告和 leaderboard。

核心输出：

| 输出 | 作用 |
|---|---|
| 逐决策质量评估 | 评价发言、投票、技能、时机和影响 |
| PublishedReview | 生成单局复盘报告和前端可展示材料 |
| Leaderboard | 按模型、Agent 版本、角色和行为维度聚合表现 |
| 决策证据链 | 将复盘结论追溯到具体事件和 Agent 输出 |

## Track C：策略进化

入口：`backend/eval/knowledge_abstractor.py`, `backend/agents/cognitive/retrieval_prod.py`

Track C 的目标是将复盘经验沉淀为可检索策略，并回流到下一局 Agent。系统从 Track B 的高价值片段和改进点中抽取策略知识，先进入 candidate 池，再通过质量、聚类和使用反馈晋级为 active，最后由 `StrategyRetriever` 按角色、阶段和适用条件完成检索。

当前默认检索策略为 `same_role_all_mbti`：在 6 个固定单 Agent 场景的火山 v4flash 轻量 A/B 中，综合质量 8.13，相比无检索 7.33 提升 +0.80；`hybrid_role_mbti_global` 保留为可选分层兜底策略。

## Track C 生命周期

Track C 的策略知识分两层触发：

| 层级 | 触发方式 | 作用 |
|---|---|---|
| 赛后自动门禁 | 每局结束后由 `run_post_game_scoring()` 调用 `promote_after_store(source_game_id=game_id)` | 只处理本局新知识，按质量、聚类和使用反馈把候选晋级为 active，并做轻量归档 |
| 批处理治理 | 本地治理脚本或数据库维护任务 | 对全库执行质量晋级、反馈晋级、active 池剪枝、candidate 池上限治理和未达门禁归档 |

生产 Agent 的策略检索只加载 `active` 策略。`candidate` 是候选知识池，不直接进入下一局 Prompt；批处理治理限制候选堆积，未达门禁、过期或超量候选进入 `deprecated`。

初始策略种子在 `configs/seed_strategies.json`（386 条 active 策略，覆盖 14 个角色），首次启动时加载即可获得基线策略能力。

## 快速开始

### 方式一：Docker 一键启动

```bash
cp .env.example .env
# 编辑 .env 填入 LLM_PROVIDER 和 API Key
docker compose up -d
```

后端 `http://localhost:8000/docs`，前端 `http://localhost:3001`。

### 方式二：手动安装

```bash
cp .env.example .env
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
make dev                              # 后端 http://localhost:8000/docs
```

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev                           # 前端 http://localhost:3001
```

`.env.example` 默认不设置 `DATABASE_URL`，后端会使用 SQLite 本地模式；如需本地 PostgreSQL，先运行 `make db-up`，再取消 `.env` 中 `DATABASE_URL` 示例行的注释。

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
| 后端服务 | Python 3.12+ / FastAPI / WebSocket |
| 游戏引擎 | dataclass + Enum 纯逻辑规则引擎 |
| Agent | `CognitiveAgent` / AgentLoop / Memory / SocialModel / StrategyRetriever |
| LLM 接入 | `backend.llm.create_client()` |
| 数据库 | SQLAlchemy；PostgreSQL 优先，支持 SQLite 本地模式 |
| 前端 | Next.js 14 / React 18 / TypeScript / Tailwind CSS |

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
├── configs/                   # 规则、策略和实验配置
├── docs/                      # 架构、模块、需求和参考文档
└── docs/assets/               # README logo 等轻量项目介绍资产
```

## 仓库内容

| 内容 | 当前位置 |
|---|---|
| 代码仓库 | `backend/`, `frontend/`, `configs/`, `scripts/`, `tests/` |
| 产品原型 | Next.js 前端：大厅、观战、真人操作、复盘、人格配置 |
| Demo 链接 | 本地后端 `http://localhost:8000/docs`，本地前端 `http://localhost:3001` |
| 项目介绍文档 | `docs/FINAL_SHOWCASE_REPORT.md`, `docs/ENGINEERING_ARCHITECTURE.md`, `docs/PROJECT_MODULE_DESIGN.md`, `docs/prd.md` |
| 轻量展示资产 | `docs/assets/ai-werewolf-icon.svg` |

## 文档导航

| 文档 | 说明 |
|---|---|
| [`docs/README.md`](docs/README.md) | 文档阅读顺序和归档说明 |
| [`docs/FINAL_SHOWCASE_REPORT.md`](docs/FINAL_SHOWCASE_REPORT.md) | GitHub 粗略展示报告和核心量化概览 |
| [`docs/ENGINEERING_ARCHITECTURE.md`](docs/ENGINEERING_ARCHITECTURE.md) | 分层架构、运行时序、信息隔离、数据闭环和 Track C 生命周期说明 |
| [`docs/PROJECT_MODULE_DESIGN.md`](docs/PROJECT_MODULE_DESIGN.md) | 核心模块设计与实现说明 |
| [`docs/prd.md`](docs/prd.md) | 需求和系统设计目标 |

## License

MIT © 2026 wxhfy
