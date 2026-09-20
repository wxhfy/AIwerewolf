# 后端骨架与集成契约

状态：AI 对局主链路已实现，更新日期为 2026-09-20。

## 运行进程

| 进程或组件 | 责任 | 状态归属 |
|---|---|---|
| API 服务 | 校验请求、管理房间、接收命令、提供查询和 SSE | 不持有内存真相 |
| Match Worker | 领取任务、运行游戏、调用智能体、持久化进度 | PostgreSQL lease |
| Agent Runtime | 构造角色上下文、维护记忆、返回合法决策 | 每席位隔离 |
| Analysis Worker | 执行 Track B/C 和可选复盘 | PostgreSQL 可重试任务 |
| PostgreSQL | 房间、对局、任务、事件、快照、决策、记忆、发件箱 | 权威持久化状态 |
| Redis | SSE 唤醒和可选协调 | 非权威状态 |
| 前端 | 展示投影、提交 REST 命令、消费 SSE | 仅界面状态 |

## 核心接口

| 接口 | 状态 | 用途 |
|---|---|---|
| `GET /api/v1/health/live` | 已实现 | 进程存活检查 |
| `GET /api/v1/health/ready` | 已实现 | PostgreSQL 和 Redis 状态 |
| `GET /api/v1/system/capabilities` | 已实现 | 部署能力发现 |
| `POST /api/rooms` | 已实现 | 创建 AI 房间 |
| `POST /api/rooms/{room_id}/prepare` | 已实现 | 持久化初始对局 |
| `POST /api/rooms/{room_id}/start` | 已实现 | 提交 Match Job |
| `GET /api/v1/matches/{match_id}` | 已实现 | 对局状态和最新公开投影 |
| `POST /api/v1/matches/{match_id}/commands` | 部分实现 | 暂停、恢复；取消返回 `501` |
| `GET /api/matches/{match_id}/events` | 已实现 | 有序事件补拉 |
| `GET /api/matches/{match_id}/stream` | 已实现 | 可恢复 SSE |
| `GET /api/v1/matches/{match_id}/analysis` | 已实现 | 分析任务状态 |
| `GET /api/v1/matches/{match_id}/decisions` | 已实现 | 脱敏决策轨迹 |

错误统一使用 `application/problem+json`，包含稳定错误码和 `request_id`。

## 中间件

| 中间件 | 当前行为 |
|---|---|
| 请求上下文 | 接收或生成 `X-Request-ID`，返回耗时头 |
| 访问日志 | 记录方法、路径、状态、时延和请求编号 |
| 安全响应头 | 防止内容嗅探、嵌套页面和不必要浏览器权限 |
| 请求体限制 | 拒绝超过配置上限的请求 |
| CORS | 只允许配置的来源 |
| 限流 | Redis 固定窗口，可关闭 |
| 身份上下文 | 开发模式匿名，生产待接 JWT/OIDC |

## 持久化约束

- PostgreSQL 是唯一多进程真相源。
- 事件 `(game_id, seq)` 唯一且有序。
- 命令使用 `command_id` 幂等。
- 决策保存角色当时可见观察、合法动作、解析动作、模型元数据和校验结果。
- `actor_memories` 保存角色主观记忆，不保存主持人全局状态。
- 不要求保存模型隐藏思维链。

## 智能体契约

`DecisionRequest` 只包含角色可见数据、合法动作和动态记忆上下文。`HarnessResult` 返回一个校验后的动作。未来远程传输必须复用同一契约、按 `request_id` 去重，并保持角色隔离。

## 明确未完成

- 协作式取消和 Worker 安全中断。
- JWT/OIDC 和角色权限。
- Outbox Publisher 与死信队列。
- 远程 Agent Harness 传输。
- Prometheus/OpenTelemetry 完整输出。
- Alembic 单一迁移机制。
- 真人玩家命令与断线恢复。

## 本地验证

```bash
python -m ruff check backend tests
pytest -q
python -m backend.run_demo --seed 7
python scripts/e2e_smoke.py
```
