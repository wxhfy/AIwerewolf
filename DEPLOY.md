# AI Werewolf 部署指南

## 1. Docker Compose

依赖：Docker 24+、Docker Compose 2.20+。

```bash
cp .env.example .env
# 配置 LLM_PROVIDER 和对应的 API Key
docker compose up -d --build
```

Compose 默认服务：

| 服务 | 作用 |
|---|---|
| `postgres` | 对局、任务、事件和快照的持久化真相源 |
| `redis` | SSE 唤醒通知、协调和可选限流 |
| `backend` | FastAPI REST/SSE 服务 |
| `match-worker` | 独立消费任务并执行 AI 对局 |
| `analysis-worker` | 异步执行 Track B/C 分析任务 |
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
docker compose up -d postgres redis
```

在 `.env` 中配置本地服务：

```env
DATABASE_URL=postgresql+psycopg2://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf
REDIS_URL=redis://127.0.0.1:6380/0
```

分别启动四个进程：

```bash
# 终端 1：REST/SSE API
make dev

# 终端 2：AI 对局执行器
python -m backend.workers.match_worker

# 终端 3：异步分析执行器
python -m backend.workers.analysis_worker

# 终端 4：前端
cd frontend
npm install --legacy-peer-deps
npm run dev
```

后端地址为 `http://localhost:8000`，前端地址为 `http://localhost:3001`。
SQLite 仅用于测试或单进程临时演示；API 与 Worker 分进程运行时必须使用 PostgreSQL。

## 3. Agent Harness 运行方式

当前 Agent Harness 内嵌于 Match Worker，不暴露独立 HTTP 服务。每次决策的调用边界是：

```text
Match Worker
  -> Harness Runtime
  -> Werewolf Decision Adapter
  -> LLM Client
  -> Decision Validation
  -> Deterministic Game Engine
```

这一边界允许未来把 Harness 替换成独立服务，但当前不维护空实现或 `501` 占位接口。
模型只能接收后端状态机裁剪后的 `PlayerView`，不能直接读取数据库或主持人全局状态。

## 4. 健康检查

Docker Compose 统一入口：

```bash
curl http://localhost/api/v1/health/live
curl http://localhost/api/v1/health/ready
curl http://localhost/api/v1/system/capabilities
```

本地直接启动 FastAPI：

```bash
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
curl http://localhost:8000/api/v1/system/capabilities
```

Match Worker 通过日志、任务 heartbeat 和 lease 判断健康状态，不监听 HTTP 端口。

## 5. 数据库初始化

启动时 SQLAlchemy 会在 advisory lock 保护下完成 bootstrap schema 创建，避免 API 与 Worker
并发启动时产生 DDL 竞争。正式生产环境仍需迁移到 Alembic，并通过单独的 migration job
执行升级。

## 6. 验证

```bash
python -m ruff check backend tests scripts
pytest -q
python -m backend.run_demo --seed 7
python scripts/e2e_smoke.py
cd frontend && npm run lint && npm run build
```

依赖本地 Track B 数据集或生成产物的测试默认跳过；需要运行时设置：

```bash
RUN_EXTERNAL_DATA_TESTS=true pytest -q
```

## 7. 生产部署边界

当前 Compose 用于开发、联调和单机验收。生产上线前仍需完成：

- JWT/OIDC 与 RBAC。
- Alembic 单一迁移机制。
- Outbox Publisher、重试与死信队列。
- Prometheus/OpenTelemetry 完整接入。
- Kubernetes/Helm、HPA、PDB 和资源限额。
- 3000 QPM、SSE 并发与 LLM 配额联合压测。

生产路线见 [`docs/architecture/PRODUCTION_PLAN.md`](docs/architecture/PRODUCTION_PLAN.md)。
