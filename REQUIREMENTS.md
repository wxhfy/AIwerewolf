# AI Werewolf 当前需求规格

## 1. 当前交付目标

系统首先交付稳定的 AI-only 狼人杀闭环：多个 LLM Agent 在严格信息隔离下完成一局游戏，所有关键状态和行为均可持久化、查询、回放和复盘。

当前不把真人对战、远程 Agent Service 和 Kubernetes 作为已完成功能。远程 Agent 仅作为未来传输适配器，不预留伪实现接口。

## 2. 功能需求

| 编号 | 需求 | 当前状态 |
|---|---|---|
| FR-01 | 支持 7-12 人 AI 对局和配置化角色组合 | 已实现 |
| FR-02 | 引擎负责阶段推进、行动校验、死亡结算和胜负判断 | 已实现 |
| FR-03 | 每个 Agent 只接收角色允许的 `PlayerView` | 已实现 |
| FR-04 | AI Harness 根据角色安全视角和服务端合法动作空间产生结构化决策 | 已实现 |
| FR-05 | 房间、任务、事件、快照、决策和结果写入 PostgreSQL | 已实现 |
| FR-06 | API 接收命令后立即返回，由独立 Match Worker 执行对局 | 已实现 |
| FR-07 | 前端通过 REST 启动对局，通过 SSE 接收有序状态 | 已实现 |
| FR-08 | SSE 支持按序列号恢复，不依赖内存状态补发 | 已实现 |
| FR-09 | Track B 生成复盘、报告和运行指标 | 已实现 |
| FR-10 | Track C 抽取、治理并检索策略知识 | 已实现现有链路 |
| FR-11 | 命令支持 `command_id` 幂等和 `expected_seq` 冲突检测 | 暂停/恢复已实现 |
| FR-12 | 真人加入 AI 对局 | 暂停开放 |
| FR-13 | Agent 可通过同一 `DecisionRequest` / `HarnessResult` 契约迁移到远程服务 | 后续适配器 |

## 3. 非功能需求

- PostgreSQL 是多进程环境唯一持久化真相源。
- Redis 故障不得导致已经提交的对局记录丢失。
- API 实例不得在内存中持有不可恢复的对局真相。
- Match Worker 通过数据库任务和 lease 获取所有权。
- 每局事件的 `(game_id, seq)` 必须唯一且单调有序。
- 所有公开投影必须在后端完成信息过滤。
- 未实现能力必须返回明确的 `501` 或 capability flag，不得伪装成功。
- 错误响应使用 `application/problem+json`，包含稳定错误码和 `request_id`。
- 生产目标为 3000 QPM，但必须通过正式压测后才能宣称达标。

## 4. 分层约束

```text
Frontend presentation
  -> REST / SSE contracts
Application and API
  -> lifecycle, commands, queries, idempotency
Domain and Agent contracts
  -> rules, visibility, decisions
Infrastructure
  -> PostgreSQL, Redis, providers, workers
```

- 前端不得推进阶段、修正事件顺序或推断隐藏角色。
- Agent 不得直接修改游戏状态或读写数据库。
- 游戏领域层不得依赖 FastAPI、Redis 或前端类型。
- API 不得同步占用 HTTP 请求执行整场对局。

## 5. 验收标准

一次 AI-only 验收必须覆盖：

1. 创建房间并持久化。
2. 准备初始角色和 `seq=0` 快照。
3. 启动接口创建 durable `match_jobs` 任务。
4. 独立 Worker 领取并执行任务。
5. Agent 完成发言、投票和角色技能决策。
6. 对局推进至 `GAME_END`。
7. 事件、快照、决策、胜方和复盘结果可从数据库查询。
8. API 或前端重连后可按序列恢复状态。

## 6. 当前不在验收范围

- 真人输入、真人掉线重连和真人超时托管。
- 远程 Agent Service 的实际模型调用。
- Outbox 独立发布和死信处理。
- JWT/OIDC 和生产 RBAC。
- Kubernetes、自动扩缩容和滚动升级。
- 3000 QPM 正式容量验收。

详细实施状态见 [`docs/architecture/BACKEND_SKELETON.md`](docs/architecture/BACKEND_SKELETON.md)。
