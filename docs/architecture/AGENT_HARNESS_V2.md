# 非对称信息环境 Agent Harness 设计

本文档描述当前 Agent Harness 的设计原则、上下文组织、执行循环、能力边界、狼人杀适配方式、质量评估和 Track C 策略进化方案。该框架不只服务狼人杀，也适用于阿瓦隆、密封竞价、外交谈判等信息不对称、长时运行、多角色环境。

当前结论不是“设计已经结束”，而是：**执行主链路已经完整，通用契约方向正确；上下文治理、语义理解、策略评测和离线演进仍需继续增强。**

## 设计目标

- 游戏环境拥有完整隐藏状态，智能体永远拿不到主持人全局状态。
- 环境先生成角色可见信息和合法动作，再调用模型。
- 模型只能选择服务端生成的动作编号，不能自行发明目标或修改规则参数。
- 每次执行都产生可审计事件，便于回放、评估和复现。
- 智能体运行时不直接访问数据库、Redis、文件系统或任意网络。
- 角色记忆按对局和角色隔离，由服务端维护，不依赖提示词自觉保密。
- Agent 能在明确预算内进行反思、渐进加载 Skill、调用只读工具和提交动作。
- 实时对局优先稳定和低时延，复杂搜索与多 Agent 协作放到离线 Track C。

## 1. 责任边界

```text
Environment / Game Engine
  拥有：全局真相、状态机、合法动作、胜负规则
  不拥有：模型策略和人格表达

Visibility / Domain Adapter
  拥有：角色可见信息裁剪、领域契约转换
  不拥有：模型推理和数据库基础设施

Agent Harness
  拥有：上下文装配、预算、Skill/Tool 循环、输出校验、审计事件
  不拥有：主持人真相、规则推进、任意基础设施权限

LLM Planner
  拥有：在给定上下文和能力内选择下一步
  不拥有：数据库、Redis、文件系统、网络和动作参数解释权

Track B / Track C
  拥有：赛后评价、策略抽取、实验、版本晋升
  不拥有：实时对局状态推进
```

核心原则是“环境约束能力，模型消费能力”。模型不能靠提示词声明自己看不到全局数据，而是根本收不到全局数据。

## 核心数据契约

`DecisionRequest` 包含当前角色、决策点、角色可见信息、合法动作、记忆范围、人格、领域元数据和执行预算。隐藏字段必须从数据中彻底移除，而不是依赖提示词要求模型忽略。

封闭动作由服务端提供不可变参数：

```json
{"option_id":"vote:P3","action_type":"vote","parameters":{"target_id":"P3"}}
```

发言等开放内容使用受约束响应结构。`HarnessResult` 包含一个经过校验的 `ResolvedAction` 和追加式执行事件，游戏引擎仍会进行最终领域校验。

### 契约为什么可迁移

Harness 不理解“狼人”“女巫”或“查杀”。它只理解：

- `InformationState`：当前 Actor 合法拥有的信息。
- `ActionSpace`：环境生成的合法动作集合。
- `MemoryScope`：记忆所属的环境、Episode 和 Actor。
- `HarnessBudget`：最大步数、工具次数、Skill 次数、输出和 Deadline。
- `HarnessStep`：反思、加载 Skill、调用工具或提交动作。

更换游戏时应替换 Adapter、Visibility 和领域工具，而不是复制 Harness。

## 2. 上下文如何组织

当前上下文不是一段不断追加的聊天记录，而是每个决策点重新装配的 `Context Envelope`。顺序和所有权如下：

| 层 | 内容 | 所有者 | 是否可被模型修改 |
|---|---|---|---|
| L0 身份与策略边界 | Actor、Agent 定义、Policy Tag、Deadline | Harness | 否 |
| L1 当前观察 | 天数、阶段、自己、可见玩家、合法目标 | Visibility / Adapter | 否 |
| L2 近期可见历史 | 最近公开事件和该角色私有事件 | Memory Service | 否 |
| L3 主观认知 | 工作记忆、信念、关系、情绪、目标、声明与证据图 | Actor Memory | 间接更新 |
| L4 检索记忆 | 与当前决策相关的情景记忆 | Retriever | 否 |
| L5 跨局策略 | Track C 已发布且适用的策略知识 | Knowledge Retriever | 否 |
| L6 渐进能力 | Skill 目录、已加载 Skill、工具结果 | Harness | 只能请求 |
| L7 合法动作 | `option_id`、固定参数和开放响应 Schema | Environment | 否 |

Planner 的 Payload 中包含 `context_manifest`，记录本次实际装配的层、数量上限、包含数量、剩余步数和剩余时间。这样可以回答“模型为什么没有看到某条信息”，也能对上下文长度和裁剪效果做指标统计。

### 上下文优先级

冲突时采用以下优先级：

```text
环境事实与合法动作
  > 当前角色私有事实
  > 当前公开事实
  > 结构化主观记忆
  > 检索到的跨局策略
  > 人格风格偏好
```

Track C 的策略只能提供建议，不能覆盖当前对局事实；人格只能改变表达和风险偏好，不能改变角色身份和合法动作。

### 裁剪与压缩

目前采用结构化窗口而不是全文摘要：

- 可见历史最多注入最近 10 条关键事件。
- 信念最多 8 个，关系最多 6 个。
- 最近声明和证据边各 8 条。
- 情景检索最多 4 条。
- 数据库保留完整状态，Prompt 只携带决策窗口。

后续需要继续补充真正的 Token Budget Manager：在模型上下文接近上限时，按层级缩减，而不是对整个 Prompt 粗暴截断。压缩结果必须保留来源 ID、时间范围和被省略数量。

### 对开源 Harness 的吸收

当前设计参考了本地 `references/` 中的通用 Agent 项目，但没有直接套用编码 Agent 的文件系统能力：

| 参考项目 | 吸收的设计 | 在本项目中的变化 |
|---|---|---|
| Deep Agents | Middleware、渐进 Skill、隔离 Subagent、上下文管理 | 使用领域安全工具，不开放文件系统和 Shell |
| Pi | 每轮上下文转换、追加式 Session、Compaction、工具结果回灌 | 每个游戏决策重新装配 Actor Context，不复制完整对话线程 |
| Codex | 有界工具执行、事件流、线程压缩、沙箱边界 | 游戏规则本身充当更严格的动作沙箱 |
| DeepSeek Harness | 插件化上下文、结果裁剪、Skill/Subagent/Timeout | 保留插件思想，实时路径限制循环深度 |

最重要的共同点不是“工具越多越好”，而是：上下文可变换、能力渐进披露、工具有权限边界、执行可恢复、结果可审计。

## 运行流程

```text
游戏引擎产生决策点
  -> Visibility 生成角色安全 PlayerView
  -> WerewolfDecisionAdapter 生成 DecisionRequest
  -> ActorMemoryService 更新并检索角色记忆
  -> AgentHarness 调用结构化模型规划器
  -> 校验动作编号和开放响应结构
  -> 转换为引擎 Decision
  -> 游戏引擎确定性应用动作
  -> 决策、执行轨迹和角色记忆写入 PostgreSQL
```

### Direct 模式

默认实时模式为 `direct`：

- 普通决策一步模型调用。
- 女巫、猎人开枪、白狼王自爆和警徽移交等高影响决策，最多先进行一次紧凑反思。
- 不加载额外 Skill，不调用额外工具。
- 目标是控制时延、失败面和模型调用次数。

### Agentic 模式

实验模式为 `agentic`：

```text
观察上下文
  -> 可选加载 1 个 Skill
  -> 可选调用 1 个只读角色视角工具
  -> 提交 1 个合法动作
```

当前提供：

- `werewolf.evidence_reasoning`：证据、声明、承诺和矛盾的通用推理方法。
- `werewolf.role.<role>`：按角色渐进加载的策略说明。
- `werewolf.inspect_player_evidence`：读取当前 Actor 已有的目标玩家信念、关系、声明和证据边。

工具只消费 `InformationState`，不能查主持人数据库。Agentic 模式普通决策最多 3 步，高影响决策最多 4 步，最多 1 次 Skill 和 1 次工具调用。是否默认开启必须由 A/B 数据决定，不能因为“更像 Agent”就直接牺牲整局时延。

模型返回非法 JSON、非法动作或错误响应结构时，规划器最多执行一次小上下文修复调用。若模型超时、修复仍失败或 deadline 耗尽，运行时从服务端已经生成的合法动作空间中产生确定性兜底，并写入 `fallback_used` 和错误原因。格式错误和上游抖动因此只影响单步质量，不再终止整局。

## 同时决策

投票、密封行动和同轮互不可见发言必须从同一个冻结状态生成。系统先收集完整批次结果，再按确定顺序应用动作，避免后执行角色看到同批次前一个角色的行动。

## 角色记忆

记忆系统不是完整历史重放。每次决策只携带动态数量的近期事件、工作记忆、主观信念、社会关系、情绪状态、当前目标、相关情景记忆和上一次自身行动。

参数由 `configs/cognitive_memory.yaml` 版本化管理，并根据人格、情绪和阶段动态派生。详细设计见 [`COGNITIVE_MEMORY.md`](COGNITIVE_MEMORY.md)。

### 记忆不是事实库

- 情景记忆记录“这个角色经历了什么”。
- 信念记录“这个角色目前认为谁像狼人”。
- 声明图记录“谁对谁说了什么”。
- Track C 策略记录“过去实验中什么方法更有效”。

四者不能混成一个文本块。尤其是信念和策略都可能错误，必须保留置信度、来源和版本。

## 技能与工具

Skill 是可信策略说明，按决策类型和角色范围渐进加载。工具只能读取当前角色已经拥有的信息投影，不能查询主持人数据库。

操作空间应分成两类：

1. **认知操作**：加载策略、检查证据、比较声明、检索记忆。这些操作可以扩展，但必须只读、有预算、可审计。
2. **环境动作**：发言、投票、查验、守护、用药、开枪。这些动作必须由环境预生成并最终校验。

模型的自由度应该主要增加在认知操作和开放发言内容上，而不是允许它发明游戏规则或任意目标。

## 3. 发言理解如何加深

### 当前实现

`SpeechInterpreter` 已经能从角色可见发言中提取：

- 跳身份与角色声明；
- 查验、查杀和金水声明；
- 怀疑、支持和站边；
- 投票承诺；
- 撤回和改口；
- 角色声明冲突、立场冲突、发言与实际投票冲突；
- 声明到玩家的证据图，并据此更新主观信念。

当前主要依赖保守规则，优点是快、确定、可复现；缺点是无法稳定理解隐含指代、反讽、条件句、复杂逻辑链和中文口语省略。

### 目标语义结构

下一阶段不要只给发言打一个“好/坏”标签，而应形成结构化 Speech Act：

```json
{
  "speaker_id": "P2",
  "act_type": "accuse",
  "target_ids": ["P5"],
  "proposition": "P5 is likely wolf",
  "polarity": 0.8,
  "certainty": 0.6,
  "source_type": "vote_history",
  "evidence_refs": ["event-31", "vote-12"],
  "commitment": {"action": "vote", "target_id": "P5"},
  "condition": null,
  "temporal_scope": "today",
  "is_retraction": false
}
```

推荐两级管线：

```text
Tier 0 规则解析
  -> 高频明确表达，低时延、全量执行

Tier 1 小模型语义解析
  -> 只处理规则低置信度、复杂长句和高影响发言
  -> 严格 JSON Schema
  -> 结果必须引用原文片段和可见事件 ID
  -> 异步写回声明图，不能阻塞当前发言落库
```

### 发言理解验收指标

- 声明类型 Macro-F1。
- 目标玩家识别 F1。
- 否定、条件和撤回识别 F1。
- 承诺与实际投票矛盾检测 Precision / Recall。
- 证据引用有效率。
- 语义解析加入后，下一位 Agent 的决策质量提升量。
- 误解析导致的错误信念更新率。

没有标注集之前，不能声称语义理解“成熟”。应先抽取真实对局样本，建立双人标注和争议仲裁集。

## 4. 策略质量如何评测

当前 Track B 已有三级级联：确定性规则、轻量单 Judge、高影响三 Judge + Critic。Track C 已有配对 Seed、Bootstrap 置信区间、安全硬门槛和策略版本晋升。这些基础是正确的，但仍不能只看胜率。

策略质量应至少包含：

| 维度 | 示例指标 |
|---|---|
| 合法与安全 | 非法动作、信息泄漏、Fallback、超时 |
| 信息利用 | 是否使用已有查验、投票、承诺和矛盾 |
| 逻辑一致 | 发言内部一致、跨轮一致、发言投票一致 |
| 角色任务 | 预言家验人价值、女巫药效、狼人刀口价值 |
| 社交效果 | 发言后票型变化、可信度变化、误导或说服效果 |
| 策略归因 | 策略是否被检索、是否被采用、采用后效果 |
| 鲁棒性 | 不同 Seat、Persona、模型和 Seed 下是否稳定 |
| 效率 | Token、模型调用数、P50/P95 时延、失败率 |

晋升一个策略必须使用同 Seed、同座位、同角色分配的配对实验。先过信息泄漏、非法动作和角色任务不退化等硬门槛，再看平均提升、非退化 Seed 比例和 Bootstrap 区间。Judge 模型需要用人工标注集做相关性和校准验证，不能让“生成策略的同一个模型”无约束地决定自己是否优秀。

## 5. Track C 是否使用子 Agent

可以，而且适合放在离线异步 Pipeline；不建议放在实时对局的每次决策中。

目标 DAG：

```text
Analysis Worker 接收已批准复盘
  -> Evidence Miner：抽取可复现证据和失败模式
  -> Strategy Proposer[N]：并行提出多个候选策略 Patch
  -> Red-Team Critic[N]：检查信息泄漏、过拟合、互相矛盾
  -> Experiment Designer：生成配对 Seed、角色和 Persona 分层方案
  -> Tournament Worker[N]：并行运行 baseline / candidate
  -> Judge + Statistics：评分、Bootstrap、稳定性和成本分析
  -> Gatekeeper：唯一有权晋升或回滚版本
```

子 Agent 协同的约束：

- 每个子 Agent 使用新的隔离上下文，只收到完成任务需要的材料。
- 子 Agent 不直接写策略主表，返回有 Schema 的候选 Artifact。
- Coordinator 是唯一状态机和写入者，保证幂等、重试和版本一致性。
- Proposal、Critic 和 Tournament 可以并行；Promotion 必须串行。
- 模型调用并发受 Provider 和预算控制，数据库写入使用任务 ID 和版本号去重。
- 子 Agent 的价值主要是扩大候选策略搜索和并行实验，不是模拟角色在实时局内开会。

实际加速上，Tournament Worker 的多 Seed 对局最适合横向扩展；Evidence Miner 和多个 Proposer 也可并行。统计聚合与版本晋升本身不是性能瓶颈。

## 安全边界

- 可见性由环境代码执行。
- 合法动作由环境代码生成。
- 记忆写入只消费当前角色的 `InformationState`。
- 私有记忆不能跨角色、跨对局读取。
- 模型输出不能改变角色身份、决策点或动作参数。
- 原始隐藏思维链不作为系统事实保存。

## 当前实现

```text
backend/agent_harness/             通用执行内核
backend/agent_memory/              角色认知记忆
backend/domains/werewolf/          狼人杀适配器和模型规划器
backend/application/agents/        本地运行时接线
backend/game_runtime/              通用环境执行契约
```

每次 Harness 运行还会把追加式事件独立写入 `agent_harness_events`。`agent_decisions` 保存领域决策结果，`agent_harness_events` 保存运行步骤，两者职责不同，避免把完整执行轨迹长期塞在单个 JSON 元数据字段中。

当前生产路径以内嵌方式运行于 Match Worker。未来如需拆分远程智能体服务，只替换传输适配器，不改变 `DecisionRequest` 和 `HarnessResult`。

## 6. 当前成熟度判断

| 能力 | 当前状态 | 判断 |
|---|---|---|
| AI 整局执行 | 真实 GLM 7 人局 46/46 模型决策成功 | 已可用 |
| 信息隔离 | Visibility + Actor InformationState | 核心边界已成立 |
| 合法动作 | 服务端 ActionSpace + 双重校验 | 已可用 |
| 持久化审计 | 决策、记忆、Harness Event、快照 | 已可用 |
| 上下文组织 | 已分层并输出 Manifest | 可用，仍缺 Token 级预算器 |
| Skill / Tool | 通用循环已接通，狼人杀支持可配置 Agentic 模式 | 实验阶段 |
| 发言语义 | 规则型声明图和矛盾检测 | 基础可用，深层语义不足 |
| Track B | 三级评分和 Judge Panel | 可用，需人工校准 |
| Track C | 知识、Patch、配对实验和晋升门槛 | 基础可用，缺并行 Coordinator |
| 生产容量 | 尚未完成联合压测和模型容量验收 | 未完成 |

因此，当前设计足以继续迭代和跑实验，但还不足以宣布“高质量通用 Agent 平台已经完成”。下一阶段的优先级应是：

1. 建立发言语义标注集和质量基线。
2. 实现低置信度语义解析器及增量声明图写入。
3. 给 Context Envelope 增加 Token 预算、压缩记录和 Prompt 指纹。
4. 用 `direct` 对 `agentic` 做配对 A/B，验证额外操作是否值得时延。
5. 实现 Track C Coordinator 和并行 Tournament Worker。
6. 用人工标注校准 Judge，再允许策略自动晋升。

真实 GLM 链路结果见 [`MODEL_VALIDATION_GLM.md`](MODEL_VALIDATION_GLM.md)。
