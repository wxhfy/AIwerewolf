# AI Werewolf 当前架构

本文档是系统分层、信息流和技术选型的架构速查。完整设计说明见 [`SYSTEM_AND_AGENT_DESIGN.md`](SYSTEM_AND_AGENT_DESIGN.md)，生产路线见 [`PRODUCTION_PLAN.md`](PRODUCTION_PLAN.md)，智能体框架见 [`AGENT_HARNESS_V2.md`](AGENT_HARNESS_V2.md)，角色记忆见 [`COGNITIVE_MEMORY.md`](COGNITIVE_MEMORY.md)，狼人杀策略层见 [`WEREWOLF_STRATEGY.md`](WEREWOLF_STRATEGY.md)，智谱官方与 SiliconFlow 托管 GLM 整局实测见 [`MODEL_VALIDATION_GLM.md`](MODEL_VALIDATION_GLM.md)，其他免费模型历史验证见 [`MODEL_VALIDATION_2026-09-20.md`](MODEL_VALIDATION_2026-09-20.md)。

## 系统边界

```text
浏览器展示层
  -> REST 命令与查询
  -> SSE 有序状态流

FastAPI 接口层
  -> 应用服务
  -> PostgreSQL 房间、任务、命令和查询投影

Match Worker
  -> 游戏领域引擎
  -> 角色可见性投影
  -> Agent Harness 与角色记忆
  -> LLM Provider

Analysis Worker
  -> Track B 逐步评分与复盘
  -> Track C 策略抽取和知识治理

基础设施
  -> PostgreSQL 持久化真相源
  -> Redis 通知和可选协调
```

## 分层职责

### 展示层

Next.js 前端只展示后端投影、提交命令和消费 SSE。前端不得推进阶段、修正规则、推断隐藏身份或组织智能体上下文。

### 应用层

FastAPI 和应用服务负责房间与对局生命周期、命令幂等、任务入队、查询、错误协议和 SSE。HTTP 请求不得同步执行整场对局。

### 领域层

游戏领域层负责确定性状态转换、行动合法性、信息可见性、死亡结算和胜负判断。领域层不依赖 FastAPI、Redis 或前端类型。

### 智能体层

狼人杀适配器把 `PlayerView` 转换成 `DecisionRequest` 和合法 `ActionSpace`。角色记忆服务只消费角色可见信息，构造有限认知上下文。Agent Harness 调用模型并返回校验后的动作，不能直接修改游戏状态。

### 基础设施层

Repository、LLM Client、Redis 通知、数据库持久化和 Worker 属于基础设施适配器。PostgreSQL 保存唯一权威状态；Redis 不保存不可恢复的唯一数据。

## 对局信息流

```text
1. 前端创建房间并准备对局。
2. API 持久化初始玩家和 seq=0 快照。
3. 启动接口写入 match_jobs 后立即返回。
4. Match Worker 使用数据库 lease 领取任务。
5. 游戏引擎推进到需要角色决策的位置。
6. 后端裁剪 PlayerView，记忆服务更新角色主观状态。
7. Agent Harness 执行一步决策或高影响两步反思，并处理修复和超时降级。
8. 引擎校验并应用动作，写入事件、快照、决策、Harness 轨迹和角色记忆。
9. SSE 从持久化投影读取并按 seq 交付前端。
10. 对局完成后异步执行 Track B/C。
```

SSE 是交付通道，不是持久化机制。断线恢复始终从 PostgreSQL 按序列读取。

## 事务发件箱

Match Worker 不直接调用 Analysis Worker。对局完成事实、任务状态和 `outbox_events` 在同一事务提交。中继器随后创建可重试分析任务：提交前崩溃不会产生伪完成，提交后崩溃可以幂等重试。

## 进程、线程和协程

- 进程：API、Match Worker、Analysis Worker 分别部署和扩缩容。
- 线程：单局中仅用于并行等待互不依赖的阻塞模型调用。
- 协程：用于 HTTP、SSE、Redis 通知等网络等待。

一个 Match Worker 同时拥有一局对局；对局并发通过增加 Worker 副本实现。

## 当前智能体路径

```text
LocalAgentRuntime
  -> WerewolfDecisionAdapter
  -> ActorMemoryService
  -> AgentHarness
  -> LLMActionPlanner
  -> ResolvedAction
```

当前不使用子智能体。普通决策一步，高影响决策最多两步；发言证据提取、记忆更新与检索全部由确定性服务端逻辑执行。

## 技术选型

| 范围 | 技术 | 决策 |
|---|---|---|
| 前端 | Next.js、React、TypeScript | 保留 |
| 控制 API | Python、FastAPI、Uvicorn | 保留 |
| 实时状态 | SSE | 已实现 |
| 对局执行 | 独立 Python Match Worker | 已实现 |
| 智能体运行时 | Python | 已实现 |
| 权威数据 | PostgreSQL | 多进程环境必需 |
| 通知协调 | Redis | 可选增强，不作真相源 |
| 本地编排 | Docker Compose | 当前主要环境 |
| 生产编排 | Kubernetes | 后续阶段 |
| 数据迁移 | Alembic | 待替换启动时建表 |
| 可观测性 | 结构化日志、OpenTelemetry | 逐步接入 |

当前性能瓶颈主要是模型时延、上下文长度和数据库事务，不是 Python 本身。现阶段不引入 Go；只有独立 SSE 网关、超高吞吐事件分发或 CPU 密集模拟经过压测证明需要时，才拆出单独服务。

## 数据模型基线

```text
rooms
games
match_jobs
match_commands
game_events
game_snapshots
agent_decisions
actor_memories
agent_harness_events
outbox_events
track_c_post_game_jobs
```

每个事件具有唯一 `(game_id, seq)`，每个角色记忆具有唯一 `(game_id, player_id)`。

## 当前限制

- 真人输入、掉线重连和托管尚未开放。
- 远程智能体传输尚未实现。
- Outbox 独立发布和死信队列尚未完成。
- JWT/OIDC、Alembic、Kubernetes 和 3000 QPM 正式压测尚未完成。
