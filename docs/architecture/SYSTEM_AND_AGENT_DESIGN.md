# 系统架构与 Agent 设计说明

更新日期：2026-09-20。

本文档统一说明 AI 狼人杀当前的系统架构、完整 Pipeline、Agent Harness、角色认知记忆、持久化和演进方向。它回答三个问题：系统如何流转、为什么这样设计、这样设计能解决什么问题。

## 1. 设计目标

AI 狼人杀属于长时运行、非对称信息、多角色并发决策的系统。它与普通聊天应用的区别是：模型不能拥有主持人全局视角，任何一步错误都可能污染后续整局，而且一局可能持续较长时间，不能依赖单个 HTTP 连接和单进程内存存活。

因此当前架构遵循以下目标：

1. 领域规则确定：模型负责策略，不负责规则和状态推进。
2. 信息隔离可信：角色能看到什么由后端状态机裁剪，不依赖提示词自觉保密。
3. 长任务可恢复：HTTP 只提交任务，对局由独立 Worker 执行。
4. 全链路可审计：事件、快照、决策、记忆和赛后产物均可查询。
5. 实时展示有序：前端只消费后端投影，不自行拼接游戏真相。
6. Agent 可迁移：狼人杀规则通过适配器接入通用 Harness，不把框架写死在单个游戏里。
7. 性能可演进：先消除错误耦合，再根据压测拆服务，而不是提前堆叠微服务。

## 2. 设计理念

### 2.1 真相、认知和展示分离

系统同时存在三类状态：

- **主持人真相**：完整角色、夜间动作、技能状态和胜负条件，只属于领域引擎。
- **角色认知**：公共事实、角色私有事实、主观信念、关系和情绪，每个角色彼此隔离。
- **公开展示**：允许观战用户和前端看到的投影。

三者不能使用同一个无边界 JSON。领域引擎先生成权威状态，再由 Visibility 生成公开快照或指定角色的 `PlayerView`。这样即使提示词错误，模型也拿不到不该看到的数据。

### 2.2 命令与执行分离

启动一局对战是长任务。API 将启动请求转成持久化 `match_jobs`，立即向前端返回；Match Worker 再领取任务执行。这样可以避免：

- HTTP 超时导致前端误判失败；
- API 重启让整局丢失；
- 多个 API 实例争抢同一局；
- 慢模型占满 Web 请求进程。

### 2.3 推送通道与数据真相分离

SSE 负责把状态及时送达浏览器，但不是数据库。所有可恢复快照先写 PostgreSQL，再通过通知唤醒 SSE。断线后客户端使用 `Last-Event-ID` 或序列号继续读取，Redis 丢消息也不会丢失对局事实。

### 2.4 模型决策与规则执行分离

模型只返回结构化候选动作。Harness 校验 Schema 和动作空间，领域引擎再次校验业务合法性并应用状态变更。任何模型都不能直接写数据库、修改玩家存活状态或跳转游戏阶段。

### 2.5 实时主链路保持短小

当前不为每一步拉取子 Agent，也不在实时决策中执行赛后分析。每次行动最多进行一次主模型调用；记忆更新、检索、合法性校验和状态推进全部使用确定性代码。其效果是减少时延、费用、失败点和上下文泄露风险。

## 3. 分层架构

```text
浏览器展示层（Next.js）
  -> REST / SSE
接口与应用层（FastAPI）
  -> 生命周期、幂等、任务提交、查询、错误协议
Match Worker
  -> 领取任务、心跳、执行整局
领域层（WerewolfGame）
  -> 阶段状态机、角色规则、可见性、行动校验、胜负判断
Agent 层
  -> Adapter -> Memory -> Harness -> LLM -> Validation
持久化与分析层
  -> PostgreSQL、Redis 通知、Outbox、Track B/C
```

### 3.1 展示层

前端只做三件事：提交用户命令、查询后端投影、展示 SSE 状态。前端不推进天数、不决定行动是否合法、不还原夜间隐藏事件，也不把本地缓存当作权威状态。

### 3.2 接口与应用层

FastAPI 负责协议和用例编排，包括房间生命周期、任务提交、命令幂等、查询投影、健康检查、统一错误格式和 SSE。它不包含狼人杀规则，也不在请求线程中同步执行整局。

### 3.3 领域层

`WerewolfGame` 是确定性状态机，负责阶段转换、技能使用、投票结算、死亡结算和胜负判断。领域层不依赖 FastAPI、Redis、浏览器组件或具体模型供应商。

### 3.4 Agent 层

Agent 层接收角色安全视角和合法动作空间，组织有限上下文并产出结构化决策。它可以改变策略，但不能改变规则。

### 3.5 持久化与基础设施层

PostgreSQL 是多进程环境的唯一真相源。Redis 只承担通知和短期协调。LLM Client、Repository、Worker 和外部模型均通过适配器接入，不向领域层泄漏基础设施细节。

## 4. 完整 Pipeline

### 4.1 创建与准备

```text
前端 POST /api/rooms
  -> API 校验 AI-only 配置
  -> 保存 room

前端 POST /api/rooms/{room_id}/prepare
  -> 应用服务创建 game_id、角色和玩家
  -> 保存 players 与 seq=0 快照
  -> 返回公开初始状态
```

准备阶段已经落库，因此后续 API 或 Worker 重启仍可查询初始状态。

### 4.2 启动与领取

```text
前端 POST /api/rooms/{room_id}/start
  -> API 幂等创建 match_jobs
  -> 立即返回 match_id 和 queued/running 状态

Match Worker 轮询数据库
  -> 使用 lease 原子领取任务
  -> 定期 heartbeat
  -> 一个 Worker 在同一时刻拥有一局
```

对局级并发通过增加 Worker 进程或副本实现；单局内部只在多个决策互不依赖时并发等待模型结果。

### 4.3 单步 Agent 决策

```text
WerewolfGame 到达决策点
  -> Visibility.build_player_view(actor_id)
  -> WerewolfDecisionAdapter.build_request(...)
  -> ActorMemoryService.prepare(...)
  -> AgentHarness.run(...)
  -> LLMActionPlanner 单次调用模型
  -> Schema 与 ActionSpace 校验
  -> ResolvedAction
  -> ActorMemoryService.record_result(...)
  -> WerewolfGame.apply(action)
```

失败时由 Harness 记录错误和回退信息；模型输出不能绕过引擎校验。

### 4.4 持久化与 SSE

每次状态变化都会产生单调递增的 `seq`：

```text
领域事件
  -> game_events
  -> game_snapshots.truth_state
  -> game_snapshots.public_state
  -> agent_decisions
  -> actor_memories
  -> Redis 可选通知
  -> SSE 按 seq 读取公开快照
```

SSE 客户端掉线后不会要求 Worker 重放内存消息，而是从 PostgreSQL 查询大于已确认序列的记录。

### 4.5 终局与异步分析

对局进入 `GAME_END` 后，最终游戏状态、任务完成状态和 `outbox_events` 在同一事务提交。后续 Analysis Worker 再执行 Track B/C，避免赛后分析阻塞实时对局。

当前已具备事务内 Outbox 写入边界；独立 Publisher、完整重试治理和死信队列仍是后续生产化工作。

## 5. Agent Harness 设计

### 5.1 通用契约

Harness 不认识“狼人”“预言家”等具体规则，它只认识以下抽象：

- `DecisionRequest`：一次决策所需的角色安全信息。
- `InformationState`：观察、可见历史和私有认知上下文。
- `ActionSpace`：本次允许的动作类型、目标和参数约束。
- `HarnessResult`：解析后的动作、原始输出、耗时、错误和审计信息。

狼人杀适配器负责把 `PlayerView` 转换成这些通用契约。因此未来可以替换游戏适配器，把同一 Harness 用于其他非对称信息、回合制、多角色场景。

### 5.2 角色 Agent 如何构建

每个席位在对局启动时完成以下组合：

```text
通用 Harness
+ 角色安全 PlayerView
+ 当前合法 ActionSpace
+ 角色 playbook
+ 人格参数
+ 当前单局认知记忆
+ 可选跨局策略知识
= 本次角色 Agent 决策上下文
```

身份不是一个拥有全局数据库权限的独立服务账号，而是领域引擎授予的一组观察权限、合法动作和策略偏好。

### 5.3 为什么当前不使用子 Agent

狼人杀单步决策通常具有明确动作空间，主要瓶颈是模型首包和推理时延。为每步再启动规划、批判或检索子 Agent，会增加调用次数、费用、超时概率和信息隔离面。目前更合适的做法是：服务端确定性记忆 + 一次主模型决策 + 强校验。

当未来任务确实需要多阶段工具使用，并且压测证明收益高于延迟时，可以在 Harness 内新增可配置策略，而不改变领域和 API 契约。

## 6. 角色认知记忆

### 6.1 记忆块

| 记忆块 | 作用 |
|---|---|
| 工作记忆 | 当前决策最需要关注的少量信息 |
| 情景记忆 | 角色亲历事件的时间、来源、显著性和情绪色彩 |
| 信念 | 对其他玩家身份的主观概率、置信度和证据 |
| 社会关系 | 信任、亲近、威胁、影响力和感知态度 |
| 情绪 | 愉悦、唤醒、支配、恐惧、愤怒、自信和压力 |
| 目标 | 角色长期目标、当前目标和未来意图 |
| 自身行动 | 上次行动、目标和理由 |

### 6.2 动态而非固定比例

每次决策的注意窗口、检索数量、衰减速度和检索权重由以下因素共同计算：

```text
基础边界
+ memory_bias
+ logic_depth
+ suspicion_threshold
+ pressure_style
+ self_protection
+ courage
+ 当前情绪
+ 当前行动类型
```

配置定义上下限和基础显著性，运行时生成并归一化最终权重。这让谨慎、冲动、社交敏感或逻辑型人格自然呈现不同记忆行为，而不是给所有角色写死统一上下文比例。

### 6.3 隔离和持久化

Reducer 只能消费 `DecisionRequest.information_state`，不能直接查主持人数据库。`actor_memories` 按 `(game_id, player_id)` 保存当前结构化认知状态；数据库可保留完整状态，而 Prompt 只加载动态窗口，从而兼顾审计与上下文成本。

## 7. 并发、进程、线程和协程

- **进程**：API、Match Worker、Analysis Worker 独立运行和扩缩容，故障边界清楚。
- **线程**：现有同步模型客户端在互不依赖的多角色决策中可并行等待；线程不共享并修改领域状态。
- **协程**：FastAPI、SSE、Redis 通知等 I/O 链路使用异步能力。
- **数据库锁与 lease**：保证一局只被一个 Worker 推进。

当前主要时延来自模型调用和上下文长度，而不是 Python 规则计算。现阶段继续使用 Python 能降低跨语言维护成本；只有压测证明 SSE 网关、事件分发或 CPU 密集模拟成为独立瓶颈时，才考虑用 Go 拆分对应服务。

## 8. 持久化模型

核心表及职责：

| 表 | 职责 |
|---|---|
| `rooms` | 房间配置和生命周期 |
| `games` | 对局权威状态和最终结果 |
| `players` | 席位、角色和存活状态 |
| `match_jobs` | 可领取、可恢复的对局任务 |
| `match_commands` | 幂等暂停、恢复等控制命令 |
| `game_events` | 按 `seq` 排序的领域事件 |
| `game_snapshots` | 主持人快照和公开快照 |
| `agent_decisions` | 模型输入摘要、输出、解析结果和耗时 |
| `actor_memories` | 每个角色的隔离认知状态 |
| `outbox_events` | 与业务事务一致提交的后续工作事实 |
| Track B/C 表 | 复盘、评分、策略知识和反馈 |

## 9. 这样设计的效果

| 原问题 | 当前设计带来的效果 |
|---|---|
| 前端事件顺序混乱 | 后端生成单调 `seq`，前端只按序消费公开投影 |
| HTTP 长连接承载整局 | API 只提交任务，Worker 独立执行和恢复 |
| Agent 可能看到全局信息 | Visibility 和角色级 InformationState 从数据层隔离 |
| 模型输出直接污染游戏 | 两级校验后才允许领域引擎应用动作 |
| 重启后对局和记忆丢失 | 事件、快照、任务、决策和角色记忆均持久化 |
| 上下文无限增长 | 数据库保留完整记忆，Prompt 使用动态窗口和检索结果 |
| 赛后分析阻塞对局 | 终局事实通过 Outbox 边界交给异步分析 |
| 前后端高度耦合 | REST/SSE 契约连接展示层和应用层，规则不进入前端 |
| Harness 只能用于狼人杀 | 通用决策契约与狼人杀 Adapter 分离 |

## 10. 当前限制与后续顺序

当前 Pipeline 已具备纯 AI 对局的主要闭环，但距离正式生产环境仍有以下差距：

1. 用 Alembic 取代启动时建表，形成唯一迁移链路。
2. 完成 Outbox Publisher、指数重试、幂等消费和死信治理。
3. 补齐 OpenTelemetry、Prometheus、结构化日志和告警。
4. 对 API、SSE、数据库和模型调用分别压测，再进行 3000 QPM 联合容量验收。
5. 增加 JWT/OIDC、RBAC、Secret 管理和审计策略。
6. 需要跨机器独立扩展 Agent 时，再实现远程 Transport Adapter。
7. 生产边界稳定后再引入 Kubernetes、HPA、PDB 和滚动升级。

## 11. 验收标准

一条完整的 AI 对局 Pipeline 至少需要验证：

1. 房间和初始快照成功落库。
2. 启动请求只创建任务，不阻塞整局。
3. Match Worker 能领取任务并持续心跳。
4. 所有 Agent 只收到角色安全信息。
5. 模型行动经过 Harness 与领域引擎校验。
6. 对局最终进入 `GAME_END`。
7. 数据库可查到最终胜方、连续事件、快照、Agent 决策和角色记忆。
8. SSE 能按 `seq` 交付，断线后可以续读。
9. 对局完成后产生可重试的异步分析事实。

具体接口和实现状态见 [`BACKEND_SKELETON.md`](BACKEND_SKELETON.md)，角色记忆细节见 [`COGNITIVE_MEMORY.md`](COGNITIVE_MEMORY.md)，生产路线见 [`PRODUCTION_PLAN.md`](PRODUCTION_PLAN.md)。
