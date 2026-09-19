# AI Werewolf

多智能体狼人杀研究与工程平台。当前主线是 **AI-only 对局闭环**：创建房间、持久化任务、独立 Worker 执行、Agent 决策、事件与快照入库、SSE 展示、赛后复盘和策略知识回流。

## 当前状态

| 能力 | 状态 |
|---|---|
| 7-12 人 AI 对局 | 已实现并完成端到端验证 |
| 独立 Match Worker | 已实现，任务状态持久化在 PostgreSQL |
| 对局事件、快照、Agent 决策持久化 | 已实现 |
| REST 命令 + SSE 状态流 | 已实现，支持 `Last-Event-ID` 恢复 |
| Track B 复盘与报告 | 已实现 |
| Track C 策略知识抽取与检索回流 | 已实现现有链路 |
| 真人与 AI 混战 | 暂停开放，接口明确返回 `501` |
| 独立远程 Agent Service | 契约与启动骨架已提供，决策执行尚未启用 |
| JWT/OIDC、Outbox Publisher、Kubernetes | 规划中 |
| 3000 QPM 生产验收 | 目标已定义，尚未完成正式压测 |

## 架构

```text
Frontend
  -> REST commands / queries
  -> SSE ordered snapshots

FastAPI API Service
  -> PostgreSQL rooms, matches, commands, events, snapshots
  -> Redis notifications and optional rate limiting

Match Worker
  -> WerewolfGame domain engine
  -> LocalAgentRuntime -> CognitiveAgent -> LLM provider
  -> persisted events, decisions and post-game artifacts
```

PostgreSQL 是持久化真相源。Redis 只承担通知、限流和短期协调，不保存唯一一份对局状态。前端只渲染后端投影，不负责规则判断、阶段推进或隐藏信息推断。

详细边界见 [`docs/architecture/README.md`](docs/architecture/README.md)，接口与中间件状态见 [`docs/architecture/BACKEND_SKELETON.md`](docs/architecture/BACKEND_SKELETON.md)。

## 快速启动

### Docker Compose

```bash
cp .env.example .env
# 在 .env 中配置 LLM provider 与对应 API key
docker compose up -d --build
```

默认入口：

- 前端：`http://localhost`
- API：`http://localhost/api`
- Swagger：`http://localhost/api/docs`
- 直连后端开发端口：`http://localhost:8000/docs`

### 本地开发

```bash
python -m venv .venv
pip install -r requirements.txt
make dev
```

另开终端：

```bash
python -m backend.workers.match_worker
```

前端：

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

SQLite 仅用于单进程测试和临时演示。API 与 Worker 分进程运行时应使用 PostgreSQL。

## 主要接口

| 接口 | 用途 |
|---|---|
| `GET /api/v1/health/live` | 进程存活检查 |
| `GET /api/v1/health/ready` | 数据库与 Redis 就绪状态 |
| `GET /api/v1/system/capabilities` | 当前部署能力发现 |
| `POST /api/rooms` | 创建 AI 房间 |
| `POST /api/rooms/{room_id}/prepare` | 创建并持久化初始对局 |
| `POST /api/rooms/{room_id}/start` | 将对局提交给 Match Worker |
| `GET /api/matches/{match_id}/events` | 读取有序事件 |
| `GET /api/matches/{match_id}/stream` | SSE 状态流 |
| `POST /api/v1/matches/{match_id}/commands` | 幂等暂停、恢复；取消暂未实现 |
| `GET /api/replay/{game_id}` | 查询持久化回放 |

## 验证

```bash
python -m ruff check backend tests
pytest -q tests/test_engine.py tests/test_api.py
python scripts/e2e_smoke.py
cd frontend && npm run lint && npm run build
```

当前基线：后端 45 个测试通过，独立 API + Worker E2E 通过，Docker PostgreSQL + Redis 对局可推进至 `GAME_END`。

## 文档

| 文档 | 说明 |
|---|---|
| [`REQUIREMENTS.md`](REQUIREMENTS.md) | 当前需求范围与验收标准 |
| [`DEPLOY.md`](DEPLOY.md) | 部署与运行方式 |
| [`docs/prd.md`](docs/prd.md) | 产品范围和用户流程 |
| [`docs/architecture/README.md`](docs/architecture/README.md) | 当前架构真相源 |
| [`docs/architecture/BACKEND_SKELETON.md`](docs/architecture/BACKEND_SKELETON.md) | 后端接口、中间件与未实现边界 |
| [`docs/architecture/COLLABORATION.md`](docs/architecture/COLLABORATION.md) | 三方协作边界 |
| [`docs/architecture/PRODUCTION_PLAN.md`](docs/architecture/PRODUCTION_PLAN.md) | 3000 QPM 生产化路线 |

`docs/final_delivery/` 与 `docs/FINAL_SHOWCASE_REPORT.md` 是历史展示材料，不代表当前运行架构。

## License

MIT
