# 参考工作整理

## 1. 参考说明

本项目参考了已有狼人杀产品、AIWolf Agent 接口、多模型对比框架、事件驱动游戏引擎以及通用 Agent / RAG / LLM 复核相关思想。参考的方式主要是设计借鉴和工程化改造，不直接复制 GPL 代码，也不把某篇论文方法完整复现为研究结论。

报告正文可使用如下表述：

> 本项目在设计过程中参考了若干已有 Agent 与信息检索相关思想，例如工具调用式推理、检索增强生成、赛后反思和 LLM 复核等。项目并未直接复现某一论文方法，而是结合狼人杀信息不对称对局场景，将这些思想工程化为 AgentLoop、StrategyRetriever、PerStepScorer 和 KnowledgeAbstractor 等模块。

## 2. 参考方向表

| 参考方向 | 代表工作 | 项目中借鉴的思想 | 对应模块 | 引用信息完整度 |
|---|---|---|---|---|
| AI 狼人杀产品 | oil-oil/wolfcha | 阶段枚举、AI 人格、双层扮演、产品化体验 | Phase、Persona、Frontend | GitHub 信息完整 |
| 房间与实时通信 | xiong35/werewolf | 房间、WebSocket、断线重连、事件表 | FastAPI/WebSocket、Room、Frontend | GitHub 信息完整 |
| 多模型狼人杀对比 | Char-lotte-Xia/WereWolfPlus | Prompt 分层、动作 schema、批量对局、模型对比 | Prompt、Track B、Experiment | GitHub 信息完整 |
| Agent 生命周期接口 | AIWolfPy | initialize/update/dayStart/talk/vote/attack/divine/guard/finish 生命周期 | Agent interface | GitHub 信息完整 |
| 多语言 Agent 平台 | AIWolfSharp | Server/Client 分离、IPlayer 接口、Agent 测试 | Agent interface、测试 | GitHub 信息完整 |
| 规则与角色库 | werewolf-brain | 角色库、权重平衡、夜晚行动序列 | RoleRegistry、rules config | 许可待补全 |
| 事件驱动游戏引擎 | open_mafia_engine | 事件系统、phase cycle、可扩展游戏定义 | WerewolfGame、GameEvent | 许可待补全 |
| 在线房间系统 | OpenWerewolf | 房间/大厅、多玩家同步 | Frontend、Room API | GitHub 信息完整 |
| 复杂狼人杀 Bot | lykos | 复杂角色扩展、文本命令交互 | 扩展角色参考 | GitHub 信息完整 |
| 主持工具 | AlecM33/Werewolf | 主持人/旁观视角设计参考 | Frontend Console | GPL-3.0，禁止直接复制 |
| 工具调用式推理 | ReAct / Tool Calling / Building Effective Agents | 推理中调用工具，工具结果进入下一轮决策 | AgentLoop | 待补全论文/文章引用 |
| 检索增强生成 | RAG / BM25 / IR | 外部知识检索后注入上下文 | StrategyRetriever | 待补全正式引用 |
| 自反思 Agent | Reflexion | 从复盘经验中生成可复用记忆 | Track C | 待补全正式引用 |
| 终身学习 Agent | Voyager | 从交互中沉淀技能库并复用 | Track C | 待补全正式引用 |
| LLM 复核 | LLM-as-a-Judge / multi-review panel | 用 LLM 辅助复核复杂决策和报告质量 | PerStepScorer / LLMReviewPanel | 待补全正式引用 |
| 社交推理游戏 AI | Werewolf / Avalon / Diplomacy 相关多智能体博弈 | 信息不对称、欺骗、阵营协作 | Agent 策略、对比实验 | 待补全正式引用 |
| Persona-based Agent | Persona prompting / role-playing agents | 人格风格与角色身份分离 | Persona / Role Prompt | 待补全正式引用 |

## 3. 参考仓库借鉴点

### 3.1 wolfcha

来源：本地 `references/wolfcha/` 参考仓库与 `SKILLS.md` 的项目参考说明。

wolfcha 提供了 AI 狼人杀产品化的参考，包括完整阶段枚举、Persona 生成、双层扮演、游戏状态管理和产品 UI。AI Werewolf 借鉴其“人格 + 身份”分离思想，但进一步加入了 Track B/C 的复盘和知识回流。

对应模块：`backend/engine/`、`backend/agents/cognitive/prompts.py`、`frontend/`。

### 3.2 xiong35/werewolf

该项目提供房间、WebSocket、事件表、断线重连和历史对局的全栈参考。AI Werewolf 在产品结构上保留大厅、房间、对局页和事件流思路，并结合 AI 对局加入 Agent 决策审计。

对应模块：`backend/app.py`、`backend/protocols/rooms.py`、`frontend/app/room/[id]/play/page.tsx`。

### 3.3 WereWolfPlus

WereWolfPlus 对 Prompt 模板、动作 schema、YAML 配置、多模型批量对局有较强参考价值。AI Werewolf 借鉴其“规则 -> 状态 -> 观察 -> 策略 -> 输出格式”的 Prompt 层次，并扩展为 Persona / Role / Strategy 三层结构。

对应模块：`backend/agents/cognitive/prompts.py`、`scripts/multi_tier_experiment.py`、`backend/eval/`。

### 3.4 AIWolfPy / AIWolfSharp

AIWolf 系列项目提供标准 Agent 生命周期接口。AI Werewolf 保留了 talk、vote、attack、divine、guard、finish 等动作点，并将其工程化为 CognitiveAgent 和 WerewolfGame 的交互协议。

对应模块：`backend/agents/base.py`、`backend/agents/cognitive/agent.py`。

### 3.5 werewolf-brain / open_mafia_engine

werewolf-brain 提供角色库、夜晚序列和权重平衡思路；open_mafia_engine 提供事件驱动和 phase cycle 的参考。AI Werewolf 没有直接复制规则库，而是用自己的 RoleRegistry、ActionValidator 和 PhaseMachine 风格实现。

对应模块：`backend/engine/roles/`、`backend/engine/actions.py`、`backend/engine/game.py`。

## 4. 待补全引用

以下参考方向需要在正式报告或答辩 PPT 中补全标准引用信息：

| 方向 | 待补内容 |
|---|---|
| ReAct | 作者、年份、论文/链接 |
| Reflexion | 作者、年份、论文/链接 |
| Voyager | 作者、年份、论文/链接 |
| RAG | 代表论文/系统引用 |
| BM25 | 经典 IR 引用 |
| LLM-as-a-Judge | 代表论文/benchmark 引用 |
| Social deduction game AI | Werewolf / Avalon / Diplomacy 相关工作 |
| Persona-based Agent | Persona prompting / role-playing agent 相关工作 |

## 5. 许可证注意事项

| 项目 | 许可证状态 | 使用边界 |
|---|---|---|
| wolfcha | MIT | 可参考设计，避免直接粘贴实现 |
| xiong35/werewolf | MIT | 可参考产品流程 |
| OpenWerewolf | Apache 2.0 | 可参考房间系统 |
| AlecM33/Werewolf | GPL-3.0 | 不可直接复制代码 |
| werewolf-brain | 待核对 | 只做设计参考 |
| open_mafia_engine | 待核对 | 只做设计参考 |
