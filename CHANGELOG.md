# 变更日志

本文件记录 AI Werewolf 的重要变更。

## 尚未发布 - 2026-09-20

### 新增

- 可迁移 Agent Harness，包括类型化决策请求、中间件、策略、校验、工具、技能和执行事件。
- 狼人杀领域适配器，把角色安全 `PlayerView` 转换为 Harness 输入和合法动作。
- 动态角色认知记忆，包括工作记忆、情景记忆、主观信念、社会关系、情绪和目标。
- `actor_memories` PostgreSQL 持久化和 Worker 重启恢复能力。
- PostgreSQL Match Job、快照、事件、可恢复 SSE 和异步分析任务。

### 变更

- AI 对局统一为 REST 命令、Match Worker、Harness Runtime、游戏引擎、PostgreSQL、SSE 一条路径。
- 游戏引擎不再创建智能体或直接调用模型。
- 每次模型调用只携带动态近期窗口和检索记忆，不再重复发送完整事件历史。
- 记忆参数集中在 `configs/cognitive_memory.yaml`，最终权重由人格和情绪动态派生。
- PostgreSQL 是权威状态源，Redis 只承担通知和可选协调。

### 删除

- 旧智能体层级及其重复的规划、记忆和降级实现。
- 占位远程 Agent Service 和无实现的 HTTP 接口。
- WebSocket 对局交付和历史兼容路径。
- 过期实验脚本、生成报告和耦合旧智能体实现的测试。
