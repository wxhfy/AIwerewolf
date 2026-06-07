# 设计取舍说明

## 1. 设计取舍总览

证据等级：

- A：有真实实验数据 + 验收结果 + 代码实现。
- B：有验收结果 + 代码实现。
- C：有代码实现 + 设计文档。
- D：主要是设计判断，暂无实验数据。

| 设计点 | 采用方案 | 替代方案 | 取舍说明 | 证据等级 |
|---|---|---|---|---|
| Game Engine 独立控制流程 | `WerewolfGame` 统一推进阶段和结算 | Agent 自由决定流程 | 保证规则一致、动作合法、胜负判定可审计 | A |
| PlayerView 信息隔离 | 每个 Agent 只拿裁剪视图 | 传完整状态给 Agent | 防止私有身份和查验泄漏 | A |
| CognitiveAgent | Observe -> Think -> Act | 单 prompt / heuristic agent | 支持记忆、信念、工具、反思和角色动作 | B |
| 三层 Prompt | Persona / Role / Strategy 分层 | 人设、身份、策略混写 | 避免性格层夹带玩法，策略只从 Layer 3 进入 | C |
| AgentLoop 工具调用 | 多轮工具调用后输出动作 | 单次 LLM 输出 | 允许 Agent 主动查策略、规则、历史和投票模式 | B |
| BM25 + 倒排索引 | 本地轻量检索 | embedding-only / 外部向量服务 | 可审计、低延迟、部署简单 | A |
| `hybrid_role_mbti_global` | 作为可选策略之一 | `global_only` | 兼顾角色、MBTI 和全局补充，离线结果优于 global_only | A |
| 4-filter 安全管线 | confidence / visibility / no leak / applicability | 只按相似度 top-k | 控制错误知识、私有信息和不适用策略进入 Prompt | B |
| 三级评分级联 | deterministic + light LLM + heavy judge | 全规则或全 LLM | 平衡成本、覆盖和细粒度复盘 | B |
| candidate / active 隔离 | 新知识先进入 candidate | 直接写 active | 防止赛后新抽取知识污染下一局正式检索池 | A |
| 前端观战控制台 | Next.js + WebSocket snapshot | CLI / 静态报告 | 支持产品化演示和人类交互 | C |
| strict mode | 端到端验收脚本 | 只跑单测或手动试用 | 把 DB、LLM、对局、评分、知识、报告连成一条验收链 | A |

## 2. 核心取舍说明

### 2.1 Game Engine 独立控制流程

当前采用 `backend/engine/game.py::WerewolfGame` 作为对局主控，引擎负责阶段切换、合法动作请求、夜晚和白天结算、特殊阶段处理和 `_check_win()` 胜负判定。替代方案是让 Agent 通过自然语言或工具调用推动流程，但这会让规则边界、阶段幂等和胜负结果难以审计。当前方案把 Agent 限制在 talk / vote / attack / divine / guard / witch 等动作点，游戏流程由引擎保证。证据来源是 strict mode 真实对局 PASS、单局 68 条事件和 `game.py` 关键函数。数据充分性：对“链路跑通”充分；对高并发压力不充分。

### 2.2 PlayerView 信息隔离

当前采用 `Visibility.for_player()` 为每个玩家生成 `PlayerView`。视图中只包含自身份、公开信息、合法目标、公开事件和当前角色允许的私有信息；狼人额外获得狼队视图。替代方案是给 Agent 全量 state 再靠 prompt 要求“不许偷看”，但 LLM 无法提供强约束。当前方案把信息隔离放在代码层，而不是提示词层。证据来源是 `backend/engine/visibility.py` 和 `outputs/visibility_strict_report.log` 的 92/92 通过。数据充分性：对 smoke 边界充分；对所有未来角色扩展仍需新增测试。

### 2.3 CognitiveAgent

当前采用 `CognitiveAgent` 管理角色化行动，入口包括 `talk()`、`vote()`、`attack()`、`divine()`、`guard()`、`witch_act()`，内部经过 `_decision()` 调用 AgentLoop，并在终局调用 `_reflect_on_game()`。替代方案是每种角色写独立 Agent 或只使用一个通用 Prompt。当前方案保留统一接口，同时允许角色策略差异进入工具和策略层。证据来源是 `backend/agents/cognitive/agent.py` 和 strict mode 26 条真实决策。数据充分性：对基础角色和 strict 单局充分；对 16 MBTI x 20 局完整覆盖仍不足。

### 2.4 三层 Prompt

当前采用 Persona / Role / Strategy 三层结构：Persona 控制表达风格，Role 定义身份、能力边界和胜利目标，Strategy 才注入玩法建议和检索知识。替代方案是把性格、身份、策略混在一个 system prompt 中。当前方案的主要收益是减少“人设层教玩法”和“角色层夹带策略”的污染，便于审计策略来自哪里。证据来源是 `backend/agents/cognitive/prompts.py`、`backend/agents/prompts.py`、`configs/strategy_library.yaml` 和用户偏好记录。数据充分性：主要是代码和设计证据，缺少直接对照实验。

### 2.5 AgentLoop 工具调用

当前采用 `backend/agents/cognitive/agent_loop.py::AgentLoop.run()` 组织工具调用，工具包括策略检索、规则查询、历史回看、公开事件回看、投票模式分析和私有信息读取。替代方案是只让 LLM 一次性输出动作。当前方案让 Agent 在决策前主动补充局内证据和策略知识，且工具追踪可审计。strict 报告显示单局 23 条决策带 tool trace。数据充分性：对“工具链路可用”充分；对工具调用带来的胜率提升尚无可靠 A/B。

### 2.6 BM25 + 倒排索引

当前采用 `StrategyRetriever` 的本地 BM25 和倒排索引。替代方案是 embedding-only、外部向量数据库或纯关键词。当前方案无需 GPU，部署简单，返回结果和过滤条件可解释；对中文术语用 `jieba` 注册狼人杀领域词。离线评估中 935 active docs、26 queries 的结果显示 `same_role_same_mbti` 得分最高，`global_only` 明显较差。数据充分性：对离线检索选型充分；对真实对局提升不足。

### 2.7 `hybrid_role_mbti_global`

`hybrid_role_mbti_global` 保留为检索策略候选，综合角色、MBTI 与全局知识。替代方案是只取同角色、只取同 MBTI 或完全 global。离线评估中该策略 offline score 0.7199，排名第二，coverage 1.0，candidate leakage 0，且 p50 latency 18.03 ms。当前默认推荐在评估文件中是 `same_role_same_mbti`，因此报告应写“hybrid 是强候选和工程取舍之一”，不写“hybrid 当前最优”。数据充分性：离线充分，线上不足。

### 2.8 4-filter

当前采用 confidence、visibility、no current-game private leak、applicability 四类过滤，把策略知识限制在允许的可信度、可见范围、角色/阶段/玩家数和规则条件内。替代方案是只按相似度 top-k 注入。当前方案牺牲部分召回，换取知识安全和信息隔离一致性。证据来源是 `backend/agents/cognitive/retrieval_prod.py`、`backend/eval/evolution.py` 和 strict 单局 active delta 0。数据充分性：对工程安全链路充分；对误杀率/漏召回率需要更多专项实验。

### 2.9 三级评分

当前采用 `PerStepScorer` 的三级评分级联：确定性规则处理明确决策，轻量 LLM 处理模糊判断，重型 judge panel 处理高影响和低一致性案例。替代方案是全部规则打分或全部 LLM 打分。当前方案控制成本，同时保留对复杂发言和反事实的评价能力。strict 单局生成 21 条 evaluation 和 1 条 approved review。数据充分性：对链路跑通充分；全量 tier 触发比例本轮未重算。

### 2.10 candidate / active 隔离

当前 Track C 将新抽取知识先写入 candidate，后续经 promotion / feedback / tournament 机制进入 active 或 deprecated。替代方案是赛后立即写 active 并进入下一局检索。当前方案防止单局错误经验污染正式策略池。strict 单局 active 935 -> 935，candidate 19256 -> 19358，新增 102 条 candidate lessons。数据充分性：对隔离机制充分；对晋级后收益不足。

### 2.11 前端观战控制台

当前前端采用 Next.js / React / Tailwind，按房间、游戏页、玩家卡片、事件时间线、行动面板组织产品界面。替代方案是只提供 CLI 或静态报告。当前方案利于演示完整对局、查看阶段和事件，并为人类玩家交互保留入口。证据来源是 `frontend/app/room/[id]/play/page.tsx`、`frontend/hooks/useGamePageController.ts`、`frontend/components/game/*`。本轮还生成了报告素材截图 `docs/assets/closure/screenshots/strict-game-review.png` 与 `docs/assets/closure/screenshots/real-game-overview.png`，但它们是结项素材截图，不等价于完整端到端 UI 回归。数据充分性：有代码实现和报告截图；完整交互验收仍不足。

### 2.12 strict mode

当前采用 `scripts/run_backend_full_strict.py` 作为收敛验收入口，检查 imports、DB、tables、LLM client、active docs、真实对局、评分、知识抽取和报告导出。替代方案是分散运行单测和手动试用。strict mode 的价值是把关键链路连成一个可复跑验收产物。2026-06-06 重新运行结果为 PASS，输出 `outputs/backend_e2e_report.json/.md` 和 `outputs/backend_e2e_strict.log`。数据充分性：对单链路验收充分；对长期稳定性仍需多局实验。

## 3. 可放入报告正文的设计取舍摘要

本项目采用“引擎主控 + Agent 决策 + 审计闭环”的产品架构。`WerewolfGame` 独立控制狼人杀阶段和规则结算，保证对局流程可复现；每个 Agent 只接收 `PlayerView`，信息隔离在代码层完成，而不是依赖 prompt 自律。Agent 采用 Observe -> Think -> Act，并通过 AgentLoop 工具调用检索策略、查询规则、回看历史和分析票型。策略知识使用 BM25 + 倒排索引实现轻量可审计检索，并经过 confidence、visibility、no leak、applicability 四类过滤后进入 Prompt 的策略层。赛后 Track B 对决策进行分步评分和复盘，Track C 将高光和失误抽象为 candidate 知识，后续再晋级为 active，避免新知识直接污染正式策略池。strict mode 作为端到端验收标准，把 DB、LLM、对局、评分、知识抽取和报告导出统一成可复跑证据链。
