# AI Werewolf 产品需求文档

更新日期：2026-09-20。

## 1. 产品目标

AI Werewolf 是一个可观测、可复盘、可迭代的多智能体狼人杀平台。当前产品只承诺 AI-only 对局完整可用，优先保证对局状态正确、信息隔离可靠、执行过程可恢复、结果可审计。

核心闭环：

```text
创建 AI 房间
-> 准备并持久化初始对局
-> Match Worker 异步执行
-> Agent 根据 PlayerView 决策
-> 事件/快照/决策写入 PostgreSQL
-> SSE 向前端交付有序状态
-> Track B 复盘
-> Track C 策略知识回流
```

## 2. 用户与使用场景

### 2.1 研究者或开发者

- 配置人数、规则包、随机种子、模型和人格。
- 启动 AI 对局并观察阶段推进。
- 查询事件、Agent 决策、模型消耗和复盘报告。
- 对比模型、角色、人格和策略版本表现。

### 2.2 观战用户

- 从大厅创建或进入 AI 房间。
- 查看公开玩家状态、阶段、发言、投票和胜负。
- 网络中断后恢复到最新持久化状态。

### 2.3 真人玩家

真人参与不是当前版本功能。创建真人席位和提交真人行动会返回 `501`。

## 3. 当前功能范围

| 模块 | 当前产品行为 |
|---|---|
| 房间 | 创建、查询并持久化 AI 房间配置 |
| 对局准备 | 生成角色、玩家和初始 `seq=0` 快照 |
| 对局启动 | 写入 durable `match_jobs`，HTTP 请求立即返回 |
| 对局执行 | 独立 Match Worker 领取任务并驱动 `WerewolfGame` |
| Agent | `LocalAgentRuntime` 为每个席位创建隔离的 `AgentHarness`，通过狼人杀适配器调用 LLM provider |
| 角色记忆 | 保存工作记忆、情景记忆、信念、关系、情绪和目标；按人格与当前决策动态裁剪上下文 |
| 信息隔离 | 后端生成 public snapshot 和角色安全 `PlayerView` |
| 实时展示 | 前端通过 SSE 获取有序快照，支持序列恢复 |
| 持久化 | 保存房间、游戏、事件、快照、决策、任务和复盘数据 |
| 控制命令 | `command_id` 幂等；暂停、恢复可用；取消暂未实现 |
| 复盘进化 | 保留 Track B/C 现有能力和接口 |

## 4. 页面范围

| 页面 | 路由 | 当前状态 |
|---|---|---|
| 大厅 | `/` | 可用，AI-only |
| 对局观战 | `/room/[id]/play` | 可用 |
| 真人操作 | `/room/[id]/human` | 不属于当前可用范围 |
| 复盘仪表盘 | `/eval/dashboard` | 可用 |
| 单局报告 | `/games/[id]/report` | 可用 |
| 人格管理 | `/personas` | 可用 |

前端只负责展示和输入，不承担游戏规则、隐藏信息判断或 Agent 编排。

## 5. 关键交互

### 5.1 创建并运行对局

1. 前端调用 `POST /api/rooms` 创建 AI 房间。
2. 调用 `POST /api/rooms/{room_id}/prepare` 获取初始快照。
3. 调用 `POST /api/rooms/{room_id}/start` 提交执行任务。
4. 使用 `GET /api/matches/{match_id}/stream` 接收 SSE。
5. 断线时携带 `Last-Event-ID` 或 `after_seq` 恢复。
6. 完成后通过游戏、回放和复盘接口读取结果。

### 5.2 对局控制

`POST /api/v1/matches/{match_id}/commands` 接收：

- `command_id`：幂等键。
- `type`：当前支持 `pause`、`resume`；`cancel` 返回 `501`。
- `expected_seq`：可选乐观并发控制。
- `payload`：命令扩展数据。

## 6. Agent 产品边界

- 当前执行路径是 Match Worker 内的 `LocalAgentRuntime`。
- Agent 只接收角色安全观察和合法动作集合。
- Agent 记忆只消费角色安全 `InformationState`，不能直接查询主持人数据库。
- Agent 返回结构化行动，最终合法性由游戏引擎判断。
- 远程 Agent transport 尚未实现，也不暴露占位 HTTP 接口。
- 浏览器不得提交或持久化真实 API Key；密钥由部署环境管理。

## 7. 质量要求

- 对局必须能够推进到 `GAME_END`，或以可查询的失败状态终止。
- Worker 崩溃不得删除已写入的事件和快照。
- Redis 不可用时，持久化数据仍应完整；SSE 可以降级轮询数据库。
- 相同 `command_id` 不得造成重复状态转换。
- 公开接口不得泄露其他角色的私有信息。
- 未实现能力必须明确返回错误，不得静默降级为另一套规则。

## 8. 后续版本

优先级顺序：

1. 真实 LLM provider 集成与失败恢复测试。
2. Alembic、Outbox Publisher、结构化日志、指标和链路追踪。
3. 远程 Agent Service 与 durable decision jobs。
4. 3000 QPM 控制面压测和容量报告。
5. Kubernetes 部署。
6. 真人对局、超时、掉线重连和托管策略。

架构实现状态以 [`architecture/BACKEND_SKELETON.md`](architecture/BACKEND_SKELETON.md) 为准。
