<p align="center">
  <img src="docs/assets/ai-werewolf-icon.svg" alt="AI 狼人杀图标" width="112">
</p>

# AI 狼人杀

<p align="center"><strong>面向非对称信息博弈的多智能体认知决策、完整回放与策略演化平台</strong></p>

AI 狼人杀不是把多个模型简单接到聊天室里，而是一套由后端状态机主持、严格裁剪角色视角、异步执行完整对局并保存全流程证据的研究与工程系统。当前主线聚焦 **纯 AI 对局闭环**，真人对战暂不开放。

## 项目目标

系统围绕四个目标设计：

1. **正确运行**：游戏规则、阶段推进、合法动作与胜负判断由确定性领域引擎控制。
2. **严格隔离**：每个角色只能看到公共事实、依法可见的私有事实和自身主观记忆。
3. **完整留痕**：房间、任务、事件、快照、模型决策、角色记忆和赛后产物均可持久化和审计。
4. **持续演化**：对局完成后通过 Track B 复盘评估，再由 Track C 抽取和治理可复用策略知识。

## 当前能力

| 能力 | 状态 |
|---|---|
| 7-12 人纯 AI 对局 | 已实现 |
| 警徽、PK、遗言、猎人开枪、白狼王自爆等流程 | 已实现 |
| 独立 Match Worker 与数据库 lease | 已实现 |
| REST 命令与 SSE 有序状态流 | 已实现，支持断线续读 |
| 对局事件、快照、Agent 决策持久化 | 已实现 |
| 动态角色认知记忆 | 已实现，按角色隔离并持久化 |
| 发言声明、站边、承诺与矛盾证据图 | 已实现，驱动主观概率更新 |
| Harness 独立事件流、修复与超时降级 | 已实现，可按请求审计 |
| Track B 逐步复盘、报告和运行指标 | 已实现 |
| Track C 策略知识抽取与检索回流 | 已实现现有链路 |
| 真人与 AI 混战 | 暂停开放，接口明确返回 `501` |
| 远程 Agent Service | 尚未实现，当前使用进程内 Harness Runtime |
| JWT/OIDC、Alembic、独立 Outbox Publisher | 规划中 |
| Kubernetes 与 3000 QPM 正式验收 | 目标已定义，尚未完成压测 |

## 总体架构

```text
浏览器展示层
  -> REST：创建房间、准备/启动对局、查询回放
  -> SSE：按 seq 消费后端公开状态

FastAPI 应用层
  -> 校验命令、持久化房间和任务、提供查询投影
  -> HTTP 请求不直接执行整场对局

Match Worker
  -> 领取 match_jobs 并独占一局
  -> WerewolfGame 确定性状态机推进阶段
  -> Visibility 生成角色安全 PlayerView
  -> ActorMemoryService 更新角色主观记忆
  -> AgentHarness 组织上下文并调用 LLM
  -> 校验动作后回交领域引擎

PostgreSQL
  -> 房间、游戏、任务、命令、事件、快照
  -> Agent 决策、角色记忆、Outbox 与赛后产物

Analysis Worker
  -> Track B 复盘和评分
  -> Track C 策略抽取、治理和知识回流
```

核心原则是：**前端只展示，API 管生命周期，领域引擎管真相，Agent 只做受约束决策，数据库保存可恢复事实。** Redis 只用于通知与短期协调，不保存唯一一份对局状态。

完整的设计理念、职责边界和信息流见 [`docs/architecture/SYSTEM_AND_AGENT_DESIGN.md`](docs/architecture/SYSTEM_AND_AGENT_DESIGN.md)。

## Agent 设计

每个 AI 席位拥有独立的 Harness 和认知记忆，但不拥有游戏真相。一次决策链路如下：

```text
PlayerView
  -> WerewolfDecisionAdapter
  -> DecisionRequest + ActionSpace
  -> ActorMemoryService
  -> AgentHarness
  -> LLMActionPlanner
  -> Schema/Rule Validation
  -> ResolvedAction
```

- 状态机负责身份、夜间行动和主持人真相的隔离，不依赖提示词保密。
- 记忆分为工作记忆、情景记忆、信念、关系、情绪、目标和自身行动。
- 检索窗口和权重由人格、角色、当前情绪和决策类型动态计算，不给不同角色写死统一比例。
- 普通决策使用一步模型调用；女巫、开枪、自爆、移交警徽等高影响决策允许一次受预算约束的反思步骤。
- 非法 JSON 或非法响应允许一次低成本修复；模型超时或修复失败时降级到服务端合法动作并完整标记，不中断整局。
- 不拉取子 Agent，避免额外时延和不可控信息扩散。
- 模型输出只是候选动作，最终合法性和状态变更始终由领域引擎决定。

## 对局信息流

1. 前端创建房间，后端持久化房间配置。
2. 前端请求准备对局，后端生成玩家、角色和 `seq=0` 初始快照。
3. 前端请求启动，API 写入 `match_jobs` 后立即返回。
4. Match Worker 使用 lease 领取任务并构建领域引擎和各席位 Agent。
5. 引擎推进到决策点，Visibility 为行动角色生成安全视角。
6. 记忆服务吸收角色可见事件，Harness 组装有限上下文并调用模型。
7. Harness 解析、校验并返回动作；引擎应用动作并产生新事件。
8. 事件、快照、决策、Harness 轨迹和角色记忆持续写入 PostgreSQL；同一步记忆只提交一次。
9. SSE 从持久化快照按 `seq` 向前端交付，断线后可以继续读取。
10. 对局结束事务写入最终状态和 Outbox 事实，后续分析异步执行。

## 技术栈

| 层级 | 当前技术 |
|---|---|
| 前端 | Next.js 16、React 18、TypeScript、Tailwind CSS |
| API | Python 3.12+、FastAPI、Uvicorn |
| 领域引擎 | Python dataclass、Enum、确定性状态机 |
| Agent | 自研可迁移 Harness、结构化动作协议、动态认知记忆 |
| 模型接入 | OpenAI-compatible / Anthropic-compatible 客户端适配 |
| 数据库 | SQLAlchemy、PostgreSQL；SQLite 仅用于单进程测试 |
| 通知 | Redis，可降级为数据库轮询 |
| 本地编排 | Docker Compose |
| 生产方向 | Kubernetes、OpenTelemetry、Prometheus、Alembic |

## 项目结构

```text
AIwerewolf/
├── backend/
│   ├── interfaces/          # HTTP、SSE 与错误协议
│   ├── application/         # 对局生命周期、Worker 编排、Agent Runtime
│   ├── engine/              # 游戏规则、状态机、角色和可见性
│   ├── agent_harness/       # 通用 Harness 契约、规划和校验
│   ├── agent_memory/        # 动态认知记忆、检索与持久化
│   ├── agents/              # 狼人杀角色适配和兼容 Agent
│   ├── db/                  # SQLAlchemy 模型、Repository 和持久化
│   ├── eval/                # Track B/C 复盘与策略演化
│   ├── llm/                 # 模型供应商客户端
│   └── workers/             # Match Worker 与 Analysis Worker
├── frontend/                # Next.js 展示层
├── configs/                 # 游戏、模型、人格和记忆配置
├── tests/                   # 单元、集成、契约和端到端测试
├── docs/                    # 产品、架构、部署和协作文档
├── docker-compose.yml
└── Makefile
```

## 快速启动

### Docker Compose

```bash
cp .env.example .env
# 在 .env 中配置 LLM_PROVIDER 和对应 API Key
docker compose up -d --build
```

默认入口：

- 前端：`http://localhost`
- API：`http://localhost/api`
- Swagger：`http://localhost/api/docs`
- 后端开发端口：`http://localhost:8000/docs`

### 本地开发

```bash
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres redis
```

分别启动：

```bash
# REST / SSE API
make dev

# AI 对局执行器
python -m backend.workers.match_worker

# 异步分析执行器
python -m backend.workers.analysis_worker

# 前端
cd frontend
npm install --legacy-peer-deps
npm run dev
```

SQLite 只适用于测试和单进程演示。API 与 Worker 分进程运行时应使用 PostgreSQL。

## 主要接口

| 接口 | 用途 |
|---|---|
| `GET /api/v1/health/live` | 进程存活检查 |
| `GET /api/v1/health/ready` | 数据库和 Redis 就绪检查 |
| `GET /api/v1/system/capabilities` | 查询当前部署能力 |
| `POST /api/rooms` | 创建纯 AI 房间 |
| `POST /api/rooms/{room_id}/prepare` | 创建并持久化初始对局 |
| `POST /api/rooms/{room_id}/start` | 提交 Match Worker 任务 |
| `GET /api/matches/{match_id}/events` | 查询有序事件 |
| `GET /api/matches/{match_id}/stream` | 订阅 SSE 状态流 |
| `POST /api/v1/matches/{match_id}/commands` | 幂等暂停或恢复 |
| `GET /api/replay/{game_id}` | 查询持久化回放 |
| `GET /api/games/{game_id}/reviews` | 查询赛后复盘 |

启动本地 API 后，可在 Swagger 中查看当前代码生成的完整接口定义。

## 配置

常用配置入口：

- `.env.example`：数据库、Redis、模型供应商和 Worker 环境变量模板。
- `configs/game.yaml`：默认游戏配置。
- `configs/cognitive_memory.yaml`：角色记忆边界、显著性和动态检索机制。
- `configs/personas.yaml`：Agent 人格样本。
- `configs/strategy_knowledge.yaml`：策略知识配置。

API Key 只能通过本地 `.env` 或部署平台 Secret 注入，不得提交到 Git。

## 验证

```bash
python -m ruff check backend tests scripts
pytest -q
python -m backend.run_demo --seed 7
python scripts/e2e_smoke.py
cd frontend && npm run lint && npm run build
```

验收重点不是“接口能返回”，而是完整对局能推进至 `GAME_END`，并且数据库可以查到事件、快照、Agent 决策、角色记忆和最终胜方。

## 文档

| 文档 | 说明 |
|---|---|
| [`docs/architecture/SYSTEM_AND_AGENT_DESIGN.md`](docs/architecture/SYSTEM_AND_AGENT_DESIGN.md) | 整体架构、Agent 设计、理念、信息流与预期效果 |
| [`docs/architecture/BACKEND_SKELETON.md`](docs/architecture/BACKEND_SKELETON.md) | 后端接口、中间件、数据表和实现边界 |
| [`docs/architecture/COGNITIVE_MEMORY.md`](docs/architecture/COGNITIVE_MEMORY.md) | 动态角色记忆与上下文裁剪 |
| [`docs/architecture/MODEL_VALIDATION_2026-09-20.md`](docs/architecture/MODEL_VALIDATION_2026-09-20.md) | 免费模型接入与真实对局验证 |
| [`docs/architecture/PRODUCTION_PLAN.md`](docs/architecture/PRODUCTION_PLAN.md) | 3000 QPM 生产化路线 |
| [`REQUIREMENTS.md`](REQUIREMENTS.md) | 当前需求与验收标准 |
| [`docs/prd.md`](docs/prd.md) | 产品范围和用户流程 |
| [`DEPLOY.md`](DEPLOY.md) | 部署、运行和健康检查 |
| [`docs/architecture/COLLABORATION.md`](docs/architecture/COLLABORATION.md) | 前端、后端平台与 Agent 的协作边界 |

## 当前限制

- 真人输入、超时托管和断线重连尚未开放。
- 远程 Agent Service transport 尚未实现。
- Outbox 当前保证终局事务内写入，独立 Publisher、重试治理和死信队列仍待完成。
- 启动时仍使用 SQLAlchemy bootstrap 建表，正式生产需要统一迁移到 Alembic。
- 3000 QPM 是设计目标，不代表当前已经通过容量验收。

## 许可证

MIT
