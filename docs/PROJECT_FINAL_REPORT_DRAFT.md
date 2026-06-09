# AI Werewolf 项目报告草稿

## 摘要

AI Werewolf 是一个面向狼人杀信息不对称场景的多智能体系统。系统支持完整狼人杀对局、严格玩家视图隔离、角色化 LLM Agent、真人玩家混战、实时观战、单局复盘、策略知识抽取和下一局检索回流。

项目主线不是“让几个模型轮流发言”，而是把狼人杀拆成一条可验证的工程链路：

```text
规则引擎主控
  -> 信息隔离投影
  -> 角色化 Agent 决策
  -> 结构化事件与决策审计
  -> 赛后复盘与知识回流
  -> 下一局策略检索
```

这条链路使系统能够回答三类问题：

- 对局是否按狼人杀规则正确推进。
- Agent 是否只基于自己当时可见的信息做决策。
- 赛后经验是否能够被结构化沉淀，并在下一局被安全使用。

## 1. 项目定位

### 1.1 系统目标

AI Werewolf 的目标是构建一个可运行、可观察、可解释、可迭代的 Agent Team。每个玩家都有独立角色、人格风格、局内记忆和策略上下文，需要在隐藏身份、阵营对抗和不完整信息下完成公开发言、投票、夜晚行动和特殊技能。

### 1.2 当前能力

| 能力 | 当前实现 | 入口 |
|---|---|---|
| 完整对局 | 7-12 人局、夜晚行动、白天发言、投票、胜负判定、警徽/PK/遗言/特殊技能 | `backend/engine/game.py` |
| 信息隔离 | `GameState` 到 `PlayerView` 的中心化裁剪，公开/私有/狼队视图分离 | `backend/engine/visibility.py` |
| 角色化 Agent | Observe -> Think -> Act，包含 Memory、BeliefTracker、SocialModel、Planner、WolfTeamView | `backend/agents/cognitive/` |
| 工具调用 | 策略检索、记忆查询、规则查询、票型分析、社交信息读取、战略意图记录 | `backend/agents/cognitive/agent_loop.py` |
| 决策审计 | 保存 observation、legal actions、raw output、parsed action、tool trace、model、latency | `backend/db/` |
| 赛后复盘 | 将发言、投票、技能行动组织成可回放步骤、关键行为和复盘报告 | `backend/eval/` |
| 知识回流 | 从复盘中抽取 lesson，进入 runtime 策略池并检索回流；Track C Wiki/Hermes 作为增量设计层承接长期知识编译和候选策略验证 | `backend/eval/knowledge_abstractor.py`, `backend/eval/evolution.py`, `docs/TRACK_C_HERMES_LLM_WIKI_DESIGN.md` |
| 产品界面 | 大厅、观战页、真人操作页、复盘仪表盘、单局报告、人格管理 | `frontend/app/` |

## 2. 与现有方法的不同

| 现有方法 | 常见局限 | AI Werewolf 的设计 |
|---|---|---|
| 单 Prompt 模拟整局 | 规则、状态和角色信息都塞进上下文，容易出现上帝视角和规则漂移 | 引擎是真实状态唯一写入者，Agent 只提交行动意图 |
| AIWolf 风格回调 Agent | 生命周期清晰，但内部记忆、社交判断和工具使用通常不可见 | 保留生命周期思想，同时加入认知状态、工具 trace 和决策审计 |
| 真人狼人杀房间系统 | 实时体验成熟，但缺少 Agent 私有上下文和赛后知识回流 | 房间系统作为产品外壳，核心是可审计的 Agent Team |
| 只统计胜负 | 胜负受身份、座位和随机种子影响大，难解释关键转折 | 每个关键行为都有事件、视图、行动和复盘链路 |
| 硬编码角色行为 | 新角色会引入大量 if/else，Prompt 和规则容易不一致 | RoleRegistry、Phase、Action、Skill 分层扩展 |
| 把历史经验直接塞进 Prompt | 噪声高、成本高，也可能污染当前局信息边界 | StrategyRetriever 只将通过生命周期和安全过滤的 active 策略按需注入；Wiki/Hermes 作为离线知识组织与候选策略设计层 |

## 3. 核心架构

### 3.1 规则引擎主控

`WerewolfGame` 负责初始化玩家、分配角色、推进阶段、校验行动、结算技能、处理死亡和判定胜负。Agent 不能直接修改 `GameState`，只能返回结构化 `Decision`。

设计优势：

- LLM 输出不稳定也不会破坏真实状态。
- 行动合法性在统一位置校验。
- 新阶段和新角色有明确扩展点。
- 对局可复现、可回放、可测试。

### 3.2 信息隔离层

系统同时维护三种视图：

| 视图 | 用途 |
|---|---|
| `GameState` | 引擎和持久化使用的完整真相 |
| `PlayerView` | 某个玩家/Agent 当时可见的局部信息 |
| Public snapshot | 前端观众看到的公开状态 |

狼人杀的核心是信息不对称。把信息过滤集中在 `Visibility.for_player()`，比在每个调用点临时裁剪更可靠，也让赛后复盘能够知道 Agent 当时到底看到了什么。

### 3.3 角色化 Agent

`CognitiveAgent` 采用 Observe -> Think -> Act：

```text
PlayerView
  -> Observation
  -> Memory / BeliefTracker / SocialModel / Planner
  -> AgentLoop tools
  -> Decision
```

Agent 的上下文分为三层：

| 层 | 作用 |
|---|---|
| Persona / MBTI | 控制表达风格、风险偏好和合作倾向 |
| Role Identity | 定义身份目标、技能边界和反模式 |
| Strategy Knowledge | 动态加载当前阶段可用策略 |

设计优势是角色差异不只体现在台词，而体现在目标、可见信息、技能动作、记忆状态和社交判断上。

### 3.4 工具调用与策略检索

AgentLoop 暴露的工具包括：

- `search_strategies`
- `recall_memory`
- `check_rules`
- `get_social_info`
- `analyze_votes`
- `set_strategic_intent`
- `submit_decision`

策略知识使用 BM25 + 倒排索引检索，并经过四层过滤：

| 过滤 | 目的 |
|---|---|
| confidence | 只让可靠知识进入对局 |
| visibility | 避免越权可见性 |
| privacy | 防止当前局私有信息泄漏 |
| applicability | 匹配角色、阶段、人数和规则条件 |

单角色检索的默认路径是 `hybrid_role_mbti_global`。当某个 Agent 请求策略时，系统先构造包含 `role / MBTI / alignment / phase / action_type / keywords` 的 `AgentContext`，再按关键词或正则从策略知识字段召回候选；候选不足时使用 BM25 全文检索兜底。随后 RetrievalPolicy 依次尝试 `same_role_same_mbti`、`same_role_all_mbti` 和 `global` 三个桶，并通过质量门禁、去重和 Top-K 填充后进入 Agent 的 Strategy 层。

当前离线量化显示，默认单角色检索在 26 条弱标注查询上 Coverage 为 100.00%，Effective@3 为 50.00%，P@3 为 0.2564；Top-5 结果中 99.23% 来自角色桶，global 兜底占 0.77%。分角色 Effective@3 为 Guard 1.0000、Hunter 1.0000、Seer 0.6000、Villager 0.5000、Werewolf 0.2857、Witch 0.2500。该结果可用于说明“当前检索主要按角色生效并稳定返回结果”，但不能写成在线胜率提升结论。

来源：`outputs/retrieval_effectiveness_current/results.json`、`outputs/retrieval_effectiveness_current/per_role_results.csv`、`outputs/retrieval_effectiveness_current/role_corpus_stats.csv`、`docs/PROJECT_ROLE_RETRIEVAL_QUANTIFICATION.md`。代码依据：`backend/agents/cognitive/retrieval_prod.py`、`backend/agents/cognitive/tools.py`、`backend/eval/knowledge_confidence.py`。

### 3.5 证据链与复盘

单步决策的证据链：

```text
GameEvent
  -> AgentDecision
  -> DecisionScore / ScoredStep
  -> PublishedReview
  -> AbstractedLesson
  -> StrategyKnowledgeDoc

Optional offline layer:
  -> Track C Wiki
  -> Hermes DreamJob / StrategyPatch
  -> candidate StrategyKnowledgeDoc
```

复盘层的价值不在于替代胜负，而在于解释胜负：哪些发言影响了站队，哪次投票改变了局势，哪个技能目标更合理，哪些经验可以沉淀到后续对局。

### 3.6 知识回流

Track C 将复盘结果转成策略知识。当前 runtime 策略池用 `candidate / active / deprecated` 控制实际注入 Agent 的知识；新增的 Wiki/Hermes 设计分成两个增量层：Wiki/Hermes 增量层负责把复盘、实验和使用反馈编译成 Markdown 策略百科，并为后续 candidate patch 提供设计入口。

## 4. 产品界面

当前前端由 Next.js 14 实现，主要页面如下：

| 页面 | 路由 | 作用 |
|---|---|---|
| 大厅 | `/` | 创建房间、选择玩家数量、AI/Human 模式和模型配置 |
| 对局观战 | `/room/[id]/play` | 展示阶段、玩家、发言、投票、死亡和事件流 |
| 真人操作 | `/room/[id]/human` | 真人玩家查看身份、选择目标、提交行动 |
| 复盘仪表盘 | `/eval/dashboard` | 查看多局数据、leaderboard 和复盘入口 |
| 单局报告 | `/games/[id]/report` | 查看单局关键行为、证据链和改进建议 |
| 人格管理 | `/personas` | 管理 MBTI/persona 配置 |

Track C 的 runtime 策略知识和回流能力通过后端 API、脚本和报告材料呈现，不承诺独立前端页面；新增的 Wiki 骨架使用 `docs/wiki/` Markdown 形态承载，可通过 Obsidian 本地浏览和人工审核。

## 5. 当前证据

已有项目文档记录：

- `docs/backend_acceptance_criteria.md` 记录 strict mode 已通过一次完整链路。
- 历史记录显示 7 人局可跑到终局，并生成复盘、知识 lessons 和候选知识。
- 当前 PostgreSQL 快照包含大量 `games`、`agent_decisions`、`evaluations`、`published_reviews` 和 `strategy_knowledge_docs` 记录。
- `data/experiment/batch_summary.json` 记录过 20/20 局成功运行的批量对局。

结论边界：

- 历史数据库包含不同时间、不同配置和运行中对局，正式统计必须按 experiment_id、provider、时间窗口和 strict 标记过滤。
- 当前多层级实验完成数不均，不能夸大为稳定提升结论。
- 若要论证某个策略版本更强，应使用 paired seeds、固定模型、固定角色配置和可重复输出目录。

## 6. 推荐展示主线

建议展示时按以下顺序：

1. 架构总览：为什么不是普通 prompt demo。
2. 一局对局：大厅 -> 观战页 -> 事件流 -> 投票/技能 -> 终局。
3. 信息隔离：同一阶段主持视角、狼人视角、村民视角字段差异。
4. Agent 决策：展示 tool_trace、memory、strategy retrieval 和 final decision。
5. 单局复盘：展示关键行为、证据链、替代行动和经验抽取。
6. 知识回流：candidate -> active -> StrategyRetriever -> 下一局策略注入；Wiki/Hermes 作为后续扩展路线。
7. 工程验证：pytest、ruff、Next.js build、visibility strict、backend strict run。

## 7. 后续实验计划

正式对比实验建议固定：

- 同一 LLM provider 和 model。
- 同一 player_count。
- 同一组 paired seeds。
- 同一角色配置。
- 记录 fallback、invalid、info leak、completion rate、role distribution。

推荐对照组：

| 组 | 配置 |
|---|---|
| `basic_react` | 关闭 Track C、anti-pattern、reflection；只保留基础工具或全局策略 |
| `anti_only` | 只开启角色反模式约束 |
| `trackc_only` | 只开启策略知识检索与注入 |
| `cognitive_full` | Track C + anti-pattern + reflection + hybrid retrieval |

推荐指标：

- win rate 和分角色 win rate。
- role-normalized process result。
- vote / speech / skill / survival 子指标。
- knowledge hit rate 和 strategy adoption rate。
- fallback / invalid / info leak。
- bootstrap CI 和 rank stability。

这些实验用于证明架构设计的增益：角色化 Agent 是否比基础 Agent 更稳，复盘是否能解释关键行为，知识回流是否真的进入后续决策。

## 8. 交付边界

GitHub 仓库应保留：

- 源码、测试、配置模板、CI workflow。
- README、PRD、架构设计、数据流、模块设计、产品技术文档、验收报告。
- 小型 SVG/HTML 图表和演示大纲。

GitHub 仓库不应保留：

- `.env`、API Key、真实账号、私有日志。
- `data/`、`logs/`、`references/`、`models/`、`.venv/`、`node_modules/`、`.next/`。
- 大体积模型文件、临时截图、实验输出 JSONL、数据库备份。
