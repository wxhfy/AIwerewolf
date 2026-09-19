# AI Werewolf 部署指南

## 1. Docker Compose

依赖：Docker 24+、Docker Compose 2.20+。

```bash
cp .env.example .env
# 配置 LLM_PROVIDER 和对应 API key
docker compose up -d --build
```

Compose 默认启动：

| 服务 | 作用 |
|---|---|
| `postgres` | 对局和任务持久化真相源 |
| `redis` | SSE 唤醒通知和可选限流 |
| `backend` | FastAPI REST/SSE 服务 |
| `match-worker` | 独立执行 AI 对局 |
| `analysis-worker` | 异步执行 Track B 逐步评分和 Track C 策略提取 |
| `frontend` | Next.js 展示层 |
| `nginx` | 统一入口和反向代理 |

访问地址：

- 前端：`http://localhost`
- API：`http://localhost/api`
- Swagger：`http://localhost/api/docs`
- SSE：`http://localhost/api/matches/{match_id}/stream`

常用命令：

```bash
make deploy
make deploy-logs
make deploy-status
make deploy-down
```

## 2. 本地开发

依赖：Python 3.12+、Node.js 20+、npm 10+。

```bash
python -m venv .venv
pip install -r requirements.txt
cp .env.example .env
```

使用 PostgreSQL 和 Redis：

```bash
docker compose up -d postgres redis
```

在 `.env` 中启用本地数据库连接：

```env
DATABASE_URL=postgresql+psycopg2://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf
REDIS_URL=redis://127.0.0.1:6380/0
```

分别启动三个进程：

```bash
# 终端 1
make dev

# 终端 2
python -m backend.workers.match_worker

# 终端 3
python -m backend.workers.analysis_worker

# 终端 4
cd frontend
npm install --legacy-peer-deps
npm run dev
```

本地地址：后端 `http://localhost:8000`，前端 `http://localhost:3001`。

SQLite 只能用于测试或单进程临时演示。API 与 Worker 分进程时必须使用 PostgreSQL，否则不能作为可靠部署。

## 3. Agent Service 契约进程

未来远程 Agent Service 可以先独立启动用于接口联调：

```bash
uvicorn backend.agent_service:app --host 0.0.0.0 --port 8001
```

当前该进程提供 OpenAPI、健康检查和决策契约，但 `/api/v1/agent/decisions` 返回结构化 `501`，模型决策仍由 Match Worker 中的 `LocalAgentRuntime` 执行。

## 4. 健康检查

Docker Compose 统一入口：

```bash
curl http://localhost/api/v1/health/live
curl http://localhost/api/v1/health/ready
curl http://localhost/api/v1/system/capabilities
```

本地直接启动 FastAPI 时：

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/system/capabilities
```

Match Worker 当前通过进程状态、日志、任务 heartbeat 和 lease 判断健康，不监听 HTTP 端口。不要对 Worker 使用后端的 8000 端口健康检查。

## 5. 数据库初始化

启动时 SQLAlchemy 会在 advisory lock 保护下完成当前 bootstrap schema 创建，避免 API 与 Worker 同时启动产生 DDL 竞态。正式生产阶段仍需迁移到 Alembic，并由单独 migration job 执行升级。

## 6. 验证

```bash
python -m ruff check backend tests
pytest -q tests/test_engine.py tests/test_api.py
python scripts/e2e_smoke.py
cd frontend && npm run lint && npm run build
```

## 7. 生产部署边界

当前 Compose 用于开发、联调和单机验收。以下能力尚未完成，因此不能直接宣称生产就绪：

- JWT/OIDC 与 RBAC。
- Alembic 单一迁移机制。
- Outbox Publisher 和死信队列。
- Prometheus/OpenTelemetry 完整接入。
- Kubernetes/Helm、HPA、PDB 和资源限额。
- 3000 QPM、SSE 并发和 LLM 配额联合压测。

生产路线见 [`docs/architecture/PRODUCTION_PLAN.md`](docs/architecture/PRODUCTION_PLAN.md)。
