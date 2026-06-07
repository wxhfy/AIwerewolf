# 《AI 狼人杀多智能体对战与自进化系统项目结项报告》

## 摘要

AI Werewolf 是一个 AI 狼人杀多智能体对战与自进化系统。系统已经具备完整 AI 对局、角色化 Agent、严格信息隔离、决策审计、赛后评分复盘、知识抽取与策略回流能力，并通过 FastAPI / WebSocket 与 Next.js 前端提供观战与交互入口。

本项目主线是 Play -> Evaluate -> Evolve：Play 阶段由 `WerewolfGame` 推进一局狼人杀并调用 `CognitiveAgent` 决策；Evaluate 阶段将每一步决策落入 PostgreSQL 并由 Track B 评分复盘；Evolve 阶段由 Track C 将高光和失误抽象为策略知识，进入 `strategy_knowledge_docs` 的 candidate / active 生命周期，再回流到下一局 Agent 的策略层。

最终验收以真实输出和数据库为准：`python scripts/run_backend_full_strict.py` 在 2026-06-06 重新运行并通过 strict mode，生成 1 局 7 人真实 LLM 对局，记录 26 条 AgentDecision、68 条 GameEvent、102 条 candidate lessons；`python scripts/verify_visibility_strict.py` 通过 92/92 项信息隔离检查；`python scripts/evaluate_retrieval_policies.py --output outputs/retrieval_policy_eval --judge weak` 完成 935 条 active 策略文档、26 个查询的离线检索评估；`data/experiment/batch_summary.json` 记录 20/20 局批量实验成功。数据来源见 `docs/PROJECT_CLOSURE_DATA_AUDIT.md`。

报告视觉素材已经生成在 `docs/assets/closure/`：包括项目图标、产品架构图、Play-Evaluate-Evolve 闭环图、数据库证据链图、真实 strict 对局总览截图和真实 Track B 复盘报告截图。真实对局截图来自 strict 对局 `f8933174-01f9-409d-8bff-c15c0576761b` 的 `/api/replay/{game_id}`、`/api/games/{game_id}/reviews/html` 和 `outputs/backend_e2e_report.json`，不使用 demo、mock、fake 或 heuristic 数据。

## 视觉摘要

![产品总体架构图](assets/closure/screenshots/architecture.png)

![真实 strict 对局总览](assets/closure/screenshots/real-game-overview.png)

![真实 Track B 复盘报告截图](assets/closure/screenshots/strict-game-review.png)

## 1. 项目概览

### 1.1 系统定位

AI Werewolf 的定位是“会玩、能复盘、可积累策略”的 AI 狼人杀系统。它不是单个聊天机器人，而是一组在信息不对称规则下行动的多智能体：每个玩家只有 `PlayerView` 授权的信息，必须在狼人杀阶段流转中发言、投票、使用技能，并通过公开事件和私有信息形成推理。

系统覆盖的核心产品能力包括：

| 能力 | 说明 | 证据 |
|---|---|---|
| 完整对局 | 夜晚、白天、警长、投票、猎人开枪、胜负判定 | `backend/engine/game.py::WerewolfGame`，`outputs/backend_e2e_report.json` |
| 多智能体 | 每个玩家独立 Agent 决策 | `backend/agents/cognitive/agent.py::CognitiveAgent` |
| 信息隔离 | 每个 Agent 只看自己合法视图 | `backend/engine/visibility.py::Visibility.for_player`，`outputs/visibility_strict_report.log` |
| 决策审计 | observation、legal actions、raw output、parsed action、tokens、latency 入库 | `backend/db/models.py::AgentDecision`，PostgreSQL `agent_decisions` |
| 赛后评分 | PerStepScorer 生成 DecisionScore / ScoredStep | `backend/eval/per_step_scorer.py` |
| 复盘报告 | PublishedReview 保存 Markdown / JSON / replay bundle | `backend/db/models.py::PublishedReview` |
| 知识回流 | AbstractedLesson 存入 strategy_knowledge_docs | `backend/eval/knowledge_abstractor.py::store_lessons_to_db` |
| 前端观战 | 房间页、游戏页、玩家卡片、事件时间线 | `frontend/app/room/[id]/play/page.tsx`，`frontend/components/game/*` |

### 1.2 项目完成内容

已完成内容按产品能力划分如下。

| 产品能力 | 当前完成状态 | 主要文件 |
|---|---|---|
| 后端游戏引擎 | 完成标准 7-12 人配置和核心阶段流转 | `backend/engine/game.py`，`backend/engine/rules.py`，`configs/rule_variant_standard.yaml` |
| 角色系统 | 基础角色可运行，WhiteWolfKing / Idiot 在规则配置中可用；部分扩展角色为 template | `backend/engine/models.py`，`backend/engine/roles/*` |
| Agent 决策 | CognitiveAgent 支持 talk / vote / attack / divine / guard / witch_act | `backend/agents/cognitive/agent.py` |
| AgentLoop 工具调用 | 支持策略检索、规则查询、历史回看、公开事件分析、投票分析、私有信息读取 | `backend/agents/cognitive/agent_loop.py`，`backend/agents/cognitive/tools.py` |
| 策略检索 | BM25 + 倒排索引 + RetrievalPolicy + 4-filter | `backend/agents/cognitive/retrieval_prod.py` |
| 审计落库 | PostgreSQL 22 张表，覆盖游戏、玩家、事件、决策、评分、复盘、知识、进化 | `backend/db/models.py`，`backend/db/persist.py` |
| Track B | 三级评分级联、结构化复盘、PublishedReview | `backend/eval/per_step_scorer.py`，`backend/eval/track_b.py` |
| Track C | 知识抽取、candidate / active / deprecated 生命周期、promotion / tournament 基础设施 | `backend/eval/knowledge_abstractor.py`，`backend/eval/evolution.py` |
| API / WebSocket | 房间、游戏、流式快照、进化接口 | `backend/app.py` |
| 前端 | Next.js 观战页、房间页、玩家状态、投票/行动面板、事件时间线 | `frontend/app/page.tsx`，`frontend/hooks/useGamePageController.ts` |
| 验收脚本 | strict、visibility、retrieval、winrate、multi-tier、leaderboard 等脚本 | `scripts/run_backend_full_strict.py`，`scripts/verify_visibility_strict.py`，`scripts/evaluate_retrieval_policies.py` |

### 1.3 项目主线

Play：`WerewolfGame` 创建玩家、分配角色、按阶段推进，所有 AI 玩家通过 `Visibility.for_player()` 获取视图后交给 `CognitiveAgent` 决策。严格验收局 `f8933174-01f9-409d-8bff-c15c0576761b` 完成 7 人 1 天对局，狼人胜，耗时 461.9 秒。来源：`outputs/backend_e2e_report.json`。

Evaluate：每个 Agent 决策由 `_record_decision()` 记录并由 `flush_decisions_to_db()` 入库；Track B 使用 `PerStepScorer`、`DecisionScore`、`ScoredStep` 和 `generate_published_review_document()` 生成复盘。严格验收局生成 21 条 evaluation、1 条 published review、34 条 leaderboard entries。来源：`outputs/backend_e2e_report.json`。

Evolve：Track C 使用 `KnowledgeAbstractor` 和 `store_lessons_to_db()` 将 scored steps 与 Agent reflection 抽象为知识文档。严格验收局新增 102 条 candidate lessons，其中 `per_step_lesson` 25 条、`reflection` 77 条；active pool 935 -> 935，candidate pool 19256 -> 19358。来源：`outputs/backend_e2e_report.json`。

## 2. 产品能力总览

### 2.1 AI 自动对局能力

`backend/engine/game.py::WerewolfGame` 是对局主控。它负责初始化玩家、分配角色、切换阶段、收集夜晚动作、处理白天发言与投票、结算死亡和胜负。阶段覆盖 NIGHT_START、NIGHT_GUARD_ACTION、NIGHT_WOLF_ACTION、NIGHT_WITCH_ACTION、NIGHT_SEER_ACTION、NIGHT_RESOLVE、DAY_START、DAY_BADGE_*、DAY_SPEECH、DAY_VOTE、DAY_RESOLVE、HUNTER_SHOOT、WHITE_WOLF_KING_BOOM、GAME_END 等。

严格验收局显示该能力已完整跑通：7 名玩家，26 条决策，68 条事件，6 条投票，最终 `GAME_END`。来源：`outputs/backend_e2e_report.json` 与 PostgreSQL `game_events` 单局查询。

### 2.2 多角色 Agent 能力

当前运行角色以代码和配置为准：

| 角色 | 状态 | 证据 |
|---|---|---|
| Villager | 可运行 | `backend/engine/roles/basic.py`，`configs/rule_variant_standard.yaml` |
| Werewolf | 可运行 | `backend/engine/roles/wolves.py` |
| Seer | 可运行 | `backend/engine/roles/gods.py` |
| Witch | 可运行 | `backend/engine/roles/gods.py` |
| Hunter | 可运行 | `backend/engine/roles/gods.py` |
| Guard | 可运行 | `backend/engine/roles/gods.py` |
| WhiteWolfKing | 可运行于 10-12 人配置 | `backend/engine/actions.py`，`backend/engine/game.py::_white_wolf_king_boom`，`configs/rule_variant_standard.yaml` |
| Idiot | 可运行于 11-12 人配置 | `backend/engine/game.py`，`backend/engine/actions.py` |
| Cupid / BigBadWolf / WolfCub / WolfKing / Knight / Elder | template，仅注册与 Prompt / i18n 预留，未进入自动配置 | `backend/engine/roles/wolfcha.py`，`backend/engine/roles/extensions.py` |

### 2.3 信息隔离能力

信息隔离由 `backend/engine/visibility.py::Visibility.for_player()` 实现。每个玩家获得 `PlayerView`，其中包含：

| 视图 | 内容 |
|---|---|
| self_player | 自己的完整角色、阵营和状态 |
| wolf_team | 仅狼人阵营可见的队友信息 |
| other players | 公开状态，不暴露未公开身份 |
| public_events | 只包含允许公开的事件 |
| private_events | 只包含当前玩家合法可见的私有事件 |

重新运行 `python scripts/verify_visibility_strict.py` 后，`outputs/visibility_strict_report.log` 显示 92 passed、0 failed。该结果支撑“信息隔离边界验证通过”，但不等价于形式化安全证明。

### 2.4 角色化推理与发言能力

`CognitiveAgent` 负责 Observe -> Think -> Act。核心实现位于：

| 模块 | 职责 | 文件 |
|---|---|---|
| CognitiveAgent | 角色动作入口：talk / vote / attack / divine / guard / witch_act | `backend/agents/cognitive/agent.py` |
| Observation / BeliefTracker | 将 PlayerView 转成可推理观察，并维护身份信念 | `backend/agents/cognitive/observe.py` |
| Memory | 保存短期和长期记忆 | `backend/agents/cognitive/memory.py` |
| WolfTeamView | 狼队合法可见的协作视角 | `backend/agents/cognitive/wolf_team.py` |
| Humanization | 发言风格、人设化表达 | `backend/agents/cognitive/humanization.py` |
| AgentLoop | 工具调用循环和决策 JSON 生成 | `backend/agents/cognitive/agent_loop.py` |

### 2.5 策略检索能力

策略检索由 `backend/agents/cognitive/retrieval_prod.py` 提供。核心组件包括 `RetrievalPolicy`、`StrategyRetriever` 和 `retrieve_strategies_prod()`。底层使用 `jieba` 分词、BM25、倒排索引和规则重排，不依赖 GPU。

重新运行命令：

```bash
python scripts/evaluate_retrieval_policies.py --output outputs/retrieval_policy_eval --judge weak
```

结果文件 `outputs/retrieval_policy_eval/results.json` 显示：query set 26，retriever size 935 active docs；`same_role_same_mbti` offline score 0.7561、P@3 0.4744、nDCG@5 0.9783、coverage 1.0、candidate leakage 0，排名第一。

### 2.6 决策审计能力

审计数据模型在 `backend/db/models.py::AgentDecision`。当前表字段包括 `game_id`、`player_id`、`day`、`phase`、`observation`、`legal_actions`、`prompt_version`、`raw_output`、`parsed_action`、`is_valid`、`latency_ms`、`prompt_tokens`、`completion_tokens`、`candidate_actions`、`visible_facts`、`confidence`、`prompt_hash`、`cost_usd`、`model_name`、`provider`、`metadata`。

严格验收局记录 26 条决策，26 条均有 parsed action；报告产物确认 23 条带 tool trace。来源：`outputs/backend_e2e_report.json`。数据库快照显示 `agent_decisions` 全量 188248 条，均有 `parsed_action`。来源：PostgreSQL 快照，查询时间 `2026-06-06 10:45:50 UTC`。

### 2.7 赛后评分能力

Track B 主要由 `backend/eval/per_step_scorer.py` 与 `backend/eval/track_b.py` 实现。关键对象：

| 对象 | 作用 |
|---|---|
| `DecisionScore` | 单步评分维度，如 correctness、reasoning、impact |
| `ScoredStep` | 结构化步骤，标记 highlight / mistake |
| `PerStepScorer` | 对决策序列执行评分级联 |
| `generate_published_review_document()` | 生成可发布复盘报告 |

严格验收局生成 `evaluation_count=21`、`review_count=1`。数据库快照中 `evaluations=63129`、`published_reviews=2625`。注意：全库包含历史 fake / 空 provider 决策，不应用于证明全部为真实 LLM 实验。

### 2.8 复盘报告能力

复盘报告落入 `published_reviews`。当前模型字段包括 `status`、`view_scope`、`grade`、`score`、`publish_allowed`、`report_json`、`markdown`、`validation_result`、`replay_bundle`、`speech_acts`、`suspicion_matrix`、`repair_history`、`metadata`。

严格验收局 PublishedReview 为 1 条，`status=approved`、`score=1.0`、`publish_allowed=True`。来源：`outputs/backend_e2e_report.json`。

### 2.9 知识抽取与自进化能力

Track C 由 `KnowledgeAbstractor`、`AbstractedLesson`、`store_lessons_to_db()`、`StrategyKnowledgeDoc`、`promote_candidates()` 和 `TournamentRunner` 组成。知识生命周期为 candidate -> active -> deprecated。

严格验收局新增 102 条 candidate lessons，没有污染 active pool。数据库快照中 `strategy_knowledge_docs=20575`，其中 active 935、candidate 19456、deprecated 184。来源：PostgreSQL 快照，查询时间 `2026-06-06 10:45:50 UTC`。

### 2.10 前端观战能力

前端位于 `frontend/`，技术栈为 Next.js 14.2.32、React 18、TypeScript、Tailwind CSS、Recharts、motion。主要入口：

| 页面 / 组件 | 功能 |
|---|---|
| `frontend/app/page.tsx` | Lobby / 房间入口 |
| `frontend/app/room/[id]/play/page.tsx` | 游戏页 |
| `frontend/hooks/useRoomStream.ts` | 房间流式数据 |
| `frontend/hooks/useGamePageController.ts` | 游戏页状态控制 |
| `frontend/components/game/EventTimeline.tsx` | 事件时间线 |
| `frontend/components/game/PlayerCard.tsx` | 玩家卡片 |
| `frontend/components/game/ActionPanel.tsx` | 人类动作面板 |

前端功能目前作为产品 UI 能力说明，不把它作为实验指标；本轮未重新跑 Playwright 视觉验收。

## 3. 系统架构

### 3.1 总体架构

```text
Frontend (Next.js / React)
  -> FastAPI / WebSocket (backend/app.py)
  -> WerewolfGame (backend/engine/game.py)
  -> Visibility / PlayerView (backend/engine/visibility.py)
  -> CognitiveAgent (backend/agents/cognitive/agent.py)
  -> AgentLoop / Tools / StrategyRetriever
  -> PostgreSQL (backend/db/models.py)
  -> Track B PerStepScorer / PublishedReview
  -> Track C KnowledgeAbstractor / strategy_knowledge_docs
  -> StrategyRetriever 回流到下一局 Agent Prompt Layer 3
```

### 3.2 核心模块关系

`WerewolfGame` 是流程主控，不把规则决策交给 Agent。Agent 只在被请求时返回发言、投票或技能动作。每次请求前，引擎调用 `Visibility.for_player()` 生成合法视图；Agent 内部用 `AgentLoop.run()` 组织工具调用和 LLM 输出；引擎用 `_record_decision()` 审计决策，用 `_check_win()` 判定胜负。赛后由 Track B/Track C 使用数据库记录和终局状态继续处理。

### 3.3 Play -> Evaluate -> Evolve 闭环

| 阶段 | 输入 | 输出 | 核心实现 |
|---|---|---|---|
| Play | 规则配置、玩家、角色、人设、策略库 | GameEvent、AgentDecision、GameSnapshot | `WerewolfGame`，`CognitiveAgent` |
| Evaluate | 决策日志、终局状态、事件流 | DecisionScore、ScoredStep、PublishedReview、Leaderboard | `PerStepScorer`，`track_b.py` |
| Evolve | ScoredStep、反思、复盘 | AbstractedLesson、StrategyKnowledgeDoc | `KnowledgeAbstractor`，`evolution.py` |
| Retrieval 回流 | active 策略文档、当前 PlayerView | 策略片段注入 Agent Prompt Layer 3 | `StrategyRetriever` |

### 3.4 端到端数据流

| 步骤 | 关键文件 / 函数 | 数据 |
|---|---|---|
| 前端进入房间 | `backend/app.py`，`frontend/app/room/[id]/play/page.tsx` | room / snapshot / websocket frame |
| 引擎创建对局 | `WerewolfGame.__init__()` | state、players、roles |
| 生成玩家视图 | `Visibility.for_player()` | `PlayerView` |
| Agent 更新观察 | `CognitiveAgent.update()` | observation、memory、belief |
| 工具调用决策 | `AgentLoop.run()` | tool trace、retrieved strategies |
| 返回动作 | `Decision` | talk / vote / attack / divine / guard / witch |
| 审计记录 | `WerewolfGame._record_decision()` | decision record |
| 落库 | `WerewolfGame.flush_decisions_to_db()`，`backend/db/persist.py` | `agent_decisions` |
| 评分 | `PerStepScorer`，`_compute_per_step_scores()` | `DecisionScore` / `ScoredStep` |
| 复盘 | `generate_published_review_document()` | `published_reviews` |
| 知识抽取 | `KnowledgeAbstractor`，`store_lessons_to_db()` | `strategy_knowledge_docs(candidate)` |
| 晋级与回流 | `promote_candidates()`，`StrategyRetriever` | `strategy_knowledge_docs(active)` -> Prompt Layer 3 |

## 4. 核心模块介绍

### 4.1 WerewolfGame 对局引擎

职责：管理狼人杀阶段、动作请求、事件记录、投票结算、死亡结算和胜负判定。输入是规则配置、玩家数、seed、Agent 工厂和角色配置；输出是终局 `GameState`、事件流、决策记录和数据库写入。

关键实现：`_ask()` 调用单个 Agent，`_batch_ask()` 并行收集可并行动作，`_record_decision()` 统一审计，`flush_decisions_to_db()` 落库，`_check_win()` 判断胜负。

完成状态：strict mode 已通过。严格验收局 7 玩家、1 天、狼胜、461.9 秒、68 事件、26 决策。来源：`outputs/backend_e2e_report.json`。

### 4.2 Visibility / PlayerView 信息隔离

职责：把真实状态裁剪为每个 Agent 合法可见的 `PlayerView`。输入是真实 `GameState` 和 player_id；输出是自身份、公开玩家、狼人队友、合法目标、公开/私有事件。

关键实现：`PlayerView`、`Visibility.for_player()`、`Visibility._legal_targets()`。完成状态：`outputs/visibility_strict_report.log` 记录 92 passed、0 failed。

### 4.3 CognitiveAgent

职责：把 PlayerView 转化为角色化行动。输入是 observation、角色、人设、历史和可用工具；输出是 `Decision`。

关键实现：`talk()`、`vote()`、`attack()`、`divine()`、`guard()`、`witch_act()`、`_decision()`、`_reflect_on_game()`。完成状态：strict mode 中真实 LLM provider 为 doubao，模型 `ep-20260514115354-k4jz4`，完成 26 条决策。来源：`outputs/backend_e2e_report.json`。

### 4.4 AgentLoop 与工具调用

职责：在 Agent 决策前组织工具调用和策略注入。输入是 observation、action type、工具集和 LLM client；输出是结构化 action JSON、tool trace 与检索知识 ID。

关键实现：`AgentLoop.run()`、`_inject_tool_trace()`、`_retrieve_track_c_strategy_lessons()`。严格验收局报告显示 23 条决策带 tool trace，23 条有 retrieved knowledge metadata。来源：`outputs/backend_e2e_report.json` 与单局 PostgreSQL metadata 查询。

### 4.5 StrategyRetriever 策略检索

职责：按角色、MBTI、阶段、阵营和安全约束检索可用策略。输入是 query、role、phase、persona、visibility context；输出 top-k strategy docs。

关键实现：`RetrievalPolicy`、`StrategyRetriever`、`retrieve_strategies_prod()`。离线评估显示 `same_role_same_mbti` 排名第一，`hybrid_role_mbti_global` 排名第二且 p50 延迟 18.03 ms。来源：`outputs/retrieval_policy_eval/results.json`。

### 4.6 PostgreSQL 数据与证据链

职责：保存对局、玩家、事件、快照、决策、评分、复盘、知识、进化和 leaderboard。当前 PostgreSQL 有 22 张表：`agent_decisions`、`agent_versions`、`evaluations`、`evolution_rounds`、`evolution_tournaments`、`experiments`、`game_events`、`game_snapshots`、`games`、`knowledge_usage_feedback`、`leaderboard_entries`、`persona_role_adapters`、`personas`、`players`、`published_reviews`、`review_reports`、`role_strategy_cards`、`strategy_graph_links`、`strategy_knowledge_docs`、`strategy_patches`、`strategy_snapshots`、`votes`。

快照数据：`games=9001`、`players=79887`、`game_events=442880`、`agent_decisions=188248`、`evaluations=63129`、`published_reviews=2625`、`strategy_knowledge_docs=20575`。来源：PostgreSQL 全量查询，查询时间 `2026-06-06 10:45:50 UTC`。注意：查询时后台仍有本仓库对局进程写库，因此该数值是时刻快照。

### 4.7 Track B 赛后评分

职责：把决策序列转换成可读、可追踪、可入库的评分与复盘。输入为 `agent_decisions`、事件和终局状态；输出为 `evaluations`、`published_reviews`、leaderboard 和供 Track C 使用的 scored steps。

完成状态：strict mode 单局生成 21 条 evaluation、1 条 review，报告状态通过。来源：`outputs/backend_e2e_report.json`。

### 4.8 Track C 知识自进化

职责：将复盘经验抽象为策略知识，并通过 candidate / active / deprecated 生命周期控制风险。输入为 `ScoredStep`、玩家反思和复盘；输出为 `strategy_knowledge_docs`。

完成状态：strict mode 单局新增 102 条 candidate lessons，active delta 为 0。数据库快照显示 active 935、candidate 19456、deprecated 184。来源：`outputs/backend_e2e_report.json` 和 PostgreSQL 快照。

### 4.9 前端观战与交互

职责：展示房间、玩家、事件、阶段、投票和行动面板。输入为 REST / WebSocket snapshot；输出为观战 UI 和人类玩家动作。

完成状态：代码实现存在。本轮新增了报告素材截图：`docs/assets/closure/screenshots/strict-game-review.png` 是后端真实 Track B review HTML 截图，`docs/assets/closure/screenshots/real-game-overview.png` 是由真实 replay + strict JSON 生成的对局总览截图。仍需注意：本轮没有完成完整前端交互回归、WebSocket 断线恢复或多视口 Playwright 产品验收，因此前端不写“全流程 UI 已验收”的实验型结论。

## 5. 验收结果与实验数据

### 5.1 数据来源说明

本报告采用以下证据等级：

| 来源 | 用途 | 是否用于正式指标 |
|---|---|---|
| `outputs/backend_e2e_report.json` | strict mode 全链路验收 | 是 |
| `outputs/visibility_strict_report.log` | 信息隔离验收 | 是 |
| `outputs/retrieval_policy_eval/results.json` | 检索策略离线评估 | 是 |
| `data/experiment/batch_summary.json` | 20 局批量实验 | 是 |
| PostgreSQL 全量查询 | 数据库规模、证据链规模 | 是，标注查询时刻 |
| 文档记录 | 架构和设计说明 | 是，但不直接当实验数字 |
| demo / fake / dry_run / heuristic 文件 | 风险审计 | 不用于正式结论 |

### 5.2 Strict Mode 全链路验收

| 指标 | 值 | 来源 |
|---|---:|---|
| 命令 | `python scripts/run_backend_full_strict.py` | `outputs/backend_e2e_strict.log` |
| 结果 | PASS | `outputs/backend_e2e_report.json` |
| 开始时间 | 2026-06-06T10:30:06.870608+00:00 | 同上 |
| 完成时间 | 2026-06-06T10:37:53.558328+00:00 | 同上 |
| LLM provider | doubao | 同上 |
| LLM model | `ep-20260514115354-k4jz4` | 同上 |
| game_id | `f8933174-01f9-409d-8bff-c15c0576761b` | 同上 |
| 玩家数 | 7 | 同上 |
| 胜方 | wolf | 同上 |
| 天数 | 1 | 同上 |
| 耗时 | 461.9 秒 | 同上 |
| AgentDecision | 26 | 同上 |
| GameEvent | 68 | 同上 |
| votes | 6 | 同上 |
| tool trace 决策 | 23 | 同上 |
| new lessons | 102 | 同上 |
| per_step_lesson | 25 | 同上 |
| reflection | 77 | 同上 |
| active docs | 935 -> 935 | 同上 |
| candidate docs | 19256 -> 19358 | 同上 |
| knowledge usage records | 138 | 同上 |
| evaluations | 21 | 同上 |
| published reviews | 1 | 同上 |
| leaderboard entries | 34 | 同上 |

警告：strict 日志扫描命中 `fallback` 3 次、`unavailable` 1 次、`skip` 2 次、`disabled` 1 次。报告检查上下文后，这些命中包含源码关键词扫描和 post-game 已有 lessons 的跳过日志；正式报告可写“有风险关键词命中，已列入审计”，不应写成“无任何风险词”。

### 5.3 模块验收结果

| 模块 | 状态 | 真实数据来源 | 关键指标 | 说明 | 风险 |
|---|---|---|---|---|---|
| DB | 通过 | PostgreSQL 快照 | 22 表，9001 games | 后台仍在写库，数值为时刻快照 | 文档旧口径写 21 表 |
| LLM | 通过 | `outputs/backend_e2e_report.json` | provider=doubao | strict health check 通过 | WEAPI 兼容性未确认 |
| Game Engine | 通过 | strict report | 7P / 1 day / GAME_END | 完整跑通 | 单局验收，不代表高并发极限 |
| Agent Decision | 通过 | strict report / DB | 单局 26，全库 188248 | parsed action 入库 | 全库含 fake/空 provider 历史数据 |
| Information Isolation | 通过 | visibility log | 92/92 | 边界 smoke 通过 | 非形式化证明 |
| Strategy Retrieval | 通过 | retrieval eval | 935 docs / 26 queries | same_role_same_mbti 排名第一 | 弱标签离线评估 |
| Track B Scoring | 通过 | strict report | 21 evaluations | 单局评分链路可用 | 全量 tier 分布未重新统计 |
| Track B Review | 通过 | strict report | 1 approved review | 可发布复盘生成 | 单局验收 |
| Track C Knowledge | 通过 | strict report | 102 candidate lessons | active 未污染 | 晋级效果需更多实验 |
| Track C Evolution | 部分 | DB / code | 6 rounds / 6 tournaments | 基础设施存在 | 当前 multi-tier 原始数据不一致 |
| Experiment | 部分 | batch summary | 20/20 成功 | 多局稳定性有数据 | multi-tier 不可正式引用 |
| Report Export | 通过 | outputs | JSON/MD report 生成 | strict 自动导出 | 无 |
| Preflight | 通过 | strict report | imports/db/llm/tables passed | 与 strict 集成 | 无 |
| Error Handling | 部分 | code / issue log | SAVEPOINT / warnings | 有问题追踪 | 未做系统化故障注入 |
| Configuration Validity | 通过 | YAML / code | 7-12 人配置 | 标准规则配置存在 | 扩展角色 template 不可声称已启用 |
| Concurrency / Multi-Game | 部分 | code / DB | `_batch_ask`、多 running games | 有并行设计 | 本轮未做压测 |
| Frontend | 部分 | code + closure screenshots | Next.js UI / review screenshot | 观战链路实现；已补真实 review/overview 截图 | 未做完整交互回归 |

### 5.4 多局实验结果

正式采用 `data/experiment/batch_summary.json`。该文件记录 20 局，seeds 300-319，completed_at 为 `2026-06-04T06:05:55.914516`。

| 指标 | 值 | 来源 |
|---|---:|---|
| total_games | 20 | `data/experiment/batch_summary.json` |
| successful | 20 | 同上 |
| failed | 0 | 同上 |
| village wins | 8 | 同上 |
| wolf wins | 12 | 同上 |
| village win rate | 40.0% | 本地重新统计 |
| wolf win rate | 60.0% | 本地重新统计 |
| avg days | 3.05 | 本地重新统计 |
| min / max days | 2 / 5 | 本地重新统计 |
| avg duration | 2308.39 秒 | 本地重新统计 |
| avg alive end | 3.1 | 本地重新统计 |
| role counts | Guard 20, Hunter 20, Seer 20, Villager 20, Werewolf 40, Witch 20 | 本地重新统计 |

44 个 `data/experiment/game_state_seed*.json` 可解析，胜方为 village 18、wolf 26，平均事件数 116.1364；但这些文件来自 seeds 300-319、400-412、600-610 三组，缺少统一 summary metadata，因此仅作为原始状态文件发现，不作为一个正式“44 局同一实验”结论。

### 5.5 多方案 / 多 Tier 对比结果

正式可写的多方案对比是检索策略离线评估：

| Rank | Policy | Offline Score | P@3 | nDCG@5 | Coverage | Candidate Leak |
|---:|---|---:|---:|---:|---:|---:|
| 1 | same_role_same_mbti | 0.7561 | 0.4744 | 0.9783 | 1.0000 | 0 |
| 2 | hybrid_role_mbti_global | 0.7199 | 0.3590 | 0.9655 | 1.0000 | 0 |
| 3 | same_role_all_mbti | 0.7198 | 0.3590 | 0.9652 | 1.0000 | 0 |
| 4 | hybrid_role_alignment_phase | 0.6929 | 0.4103 | 0.9543 | 1.0000 | 0 |
| 5 | self_mbti_only | 0.6686 | 0.3077 | 0.9388 | 1.0000 | 0 |
| 6 | global_only | -0.2808 | 0.0769 | 0.3077 | 0.3077 | 0 |

`data/experiment/multi_tier/` 当前 JSONL 为 0 字节；`data/experiment/multi_tier_bak_13g/summary.json` 显示每个 tier `game_count=0`、`error_count=1`，与备份 JSONL 里 13 条记录不一致。因此不能写“multi-tier 方案优于 baseline”或“48 局多 tier 实验结论”。

### 5.6 结果总结

有数据支撑的结论：

| 可以写入报告的结论 | 数据来源 |
|---|---|
| 系统可以完成完整真实 LLM 对局并通过 strict mode | `outputs/backend_e2e_report.json` |
| 决策、事件、评分、复盘和知识抽取链路可贯通 | `outputs/backend_e2e_report.json` |
| 信息隔离 smoke 通过 92/92 | `outputs/visibility_strict_report.log` |
| 20 局批量实验 20/20 成功，狼胜 12、好人胜 8 | `data/experiment/batch_summary.json` |
| 离线检索评估中 `same_role_same_mbti` 排名第一 | `outputs/retrieval_policy_eval/results.json` |
| PostgreSQL 已保存完整证据链规模数据 | PostgreSQL 快照 |

不建议写入的结论：

| 不建议写入报告的结论 | 原因 |
|---|---|
| 自进化显著提升胜率 | 当前没有一致、充分的 A/B 原始数据 |
| multi-tier 明显优于 baseline | 当前 multi-tier 原始数据不一致 |
| 所有全库决策都是真实 LLM-only | 全库 provider 包含 fake 和空值历史记录 |
| winrate 20 局 seed2001 完整成功 | 当前只有 log，尾部显示完成 2 局，JSON/MD 不存在 |
| 所有前端流程已视觉验收 | 本轮只生成结项报告素材截图，未做完整前端交互回归 |

## 6. 设计取舍与方案说明

| 设计点 | 采用方案 | 替代方案 | 取舍说明 | 数据/证据 | 证据等级 |
|---|---|---|---|---|---|
| Game Engine 独立控制流程 | `WerewolfGame` 主控阶段 | Agent 自由驱动 | 规则和胜负由引擎保证，Agent 只做合法动作 | strict PASS，`game.py` | A |
| PlayerView 信息隔离 | 每人裁剪视图 | 直接传全量状态 | 防止私有信息泄露 | 92/92 visibility | A |
| CognitiveAgent | Observe-Think-Act | 单 prompt Agent | 便于接入记忆、工具和反思 | strict 26 决策 | B |
| Persona / Role / Strategy 三层 | 表达、身份、策略分层 | 混合提示词 | 避免人设污染玩法规则 | code + docs | C |
| AgentLoop 工具调用 | 最多多轮工具查询 | 单次 LLM 输出 | 可以主动查规则、历史和策略 | tool trace 23 | B |
| BM25 + 倒排索引 | 本地轻量检索 | embedding-only / 外部向量库 | 可审计、低延迟、无 GPU | retrieval eval | A |
| hybrid_role_mbti_global | 作为工程候选策略 | global_only | 覆盖和角色匹配更好 | retrieval eval 排名第 2 | A |
| 4-filter 安全管线 | confidence / visibility / leak / applicability | 只按相似度 | 控制知识泄露和适用范围 | code + strict active delta 0 | B |
| 三级评分级联 | deterministic + LLM judge | 全 LLM / 全规则 | 成本和精度折中 | strict 21 evaluations | B |
| candidate -> active -> deprecated | 知识分层生命周期 | 直接写 active | 防止新知识污染下一局 | active delta 0 | A |
| 前端观战控制台 | Next.js + WebSocket snapshot | CLI only | 可产品化展示对局过程 | frontend code | C |
| strict mode | 端到端验收脚本 | 零散单测 | 用一条链路验证 DB/LLM/游戏/评分/知识 | strict PASS | A |

## 7. 项目成果总结

### 7.1 已完成成果

- 完成 AI 狼人杀多智能体系统主体：后端引擎、Agent、策略检索、评分复盘、知识回流、数据库证据链、前端观战。
- 完成 strict mode 真实链路验收，输出 JSON / Markdown / log。
- 完成信息隔离验证，92 项通过。
- 完成 20 局批量实验统计。
- 完成检索策略离线评估。
- 建立 PostgreSQL 证据链，覆盖对局、玩家、事件、快照、决策、评分、复盘、知识和进化表。

### 7.2 项目价值

系统价值在于把狼人杀从“单次 LLM 角色扮演”推进到可观测、可审计、可复盘和可积累知识的多智能体产品形态。每个 Agent 的动作都有可追踪输入输出；赛后不仅能看到胜负，还能追溯关键决策、生成评分和复盘；复盘内容可以沉淀为策略知识，并经安全过滤后回到下一局。

### 7.3 当前限制

| 限制 | 说明 | 证据 |
|---|---|---|
| LLM 延迟 | 20 局实验平均 2308.39 秒/局，单次 LLM 调用仍是主要耗时 | `data/experiment/batch_summary.json` |
| Track C 效果验证不足 | 知识抽取跑通，但晋级后胜率提升没有可靠多局 A/B 证据 | multi-tier 审计 |
| Embedding / WEAPI 口径 | 当前 strict 用 doubao；WEAPI health check 未形成正式 JSON 响应证据 | 本轮审计 |
| 全库数据混杂 | 历史数据含 fake provider、空 provider、demo/open-data 文件 | PostgreSQL provider 查询、风险扫描 |
| 前端完整交互验收缺失 | 有实现代码，并已生成结项报告用真实对局截图；但未跑完整 UI 回归、断线恢复和多视口截图 | 本轮只覆盖报告素材截图 |
| 文档与当前数据存在旧口径差异 | 文档曾写 21 表、旧 strict 指标；当前 DB 实测 22 表 | PostgreSQL `information_schema` |

### 7.4 后续方向

- 固化实验协议：将 LLM-only、多局、fallback=0、JSON 报告存在作为正式实验必备条件。
- 重跑一致的 multi-tier / A-B tournament，输出每 tier 原始 JSONL 和 summary，避免文档数字脱离原始数据。
- 为 Track C 增加晋级后回归评估，区分“能抽取知识”和“知识确实提升表现”。
- 将本轮报告素材截图扩展为完整前端 Playwright 验收，覆盖观战页、复盘页、多视口和 WebSocket 断线恢复。
- 将数据库统计脚本产品化，生成固定时间戳的 `PROJECT_CLOSURE_FACTS.json`，避免后台任务写库造成口径漂移。

## 附录

### 附录 A 关键文件索引

| 类别 | 文件 |
|---|---|
| 引擎 | `backend/engine/game.py`，`backend/engine/visibility.py`，`backend/engine/rules.py`，`backend/engine/actions.py` |
| Agent | `backend/agents/cognitive/agent.py`，`backend/agents/cognitive/agent_loop.py`，`backend/agents/cognitive/tools.py` |
| 检索 | `backend/agents/cognitive/retrieval_prod.py` |
| 评分 | `backend/eval/per_step_scorer.py`，`backend/eval/track_b.py` |
| 知识 | `backend/eval/knowledge_abstractor.py`，`backend/eval/evolution.py` |
| 数据库 | `backend/db/models.py`，`backend/db/persist.py` |
| API | `backend/app.py` |
| 前端 | `frontend/app/page.tsx`，`frontend/app/room/[id]/play/page.tsx`，`frontend/components/game/*` |
| 配置 | `configs/rule_variant_standard.yaml`，`configs/strategy_library.yaml` |

### 附录 B 验收命令

```bash
python scripts/run_backend_full_strict.py
python scripts/verify_visibility_strict.py
python scripts/evaluate_retrieval_policies.py --output outputs/retrieval_policy_eval --judge weak
```

### 附录 C 数据库核心表

`games`、`players`、`game_events`、`game_snapshots`、`agent_decisions`、`evaluations`、`published_reviews`、`strategy_knowledge_docs`、`knowledge_usage_feedback`、`leaderboard_entries`、`experiments`、`evolution_rounds`、`evolution_tournaments`。

### 附录 D 原始数据文件清单

正式使用：`outputs/backend_e2e_report.json`、`outputs/backend_e2e_report.md`、`outputs/backend_e2e_strict.log`、`outputs/visibility_strict_report.log`、`outputs/retrieval_policy_eval/results.json`、`outputs/retrieval_policy_eval/results.csv`、`outputs/retrieval_policy_eval/summary.md`、`outputs/retrieval_policy_eval/per_query_details.jsonl`、`data/experiment/batch_summary.json`。

### 附录 E 数据统计 SQL / 命令

```sql
SELECT count(*) FROM games;
SELECT count(*) FROM agent_decisions;
SELECT status, count(*) FROM strategy_knowledge_docs GROUP BY status;
SELECT COALESCE(parsed_action::jsonb->>'action_type', parsed_action::jsonb->>'type', parsed_action::jsonb->>'action'), count(*) FROM agent_decisions GROUP BY 1;
```

### 附录 F 图表数据表

详见 `docs/PROJECT_CLOSURE_FIGURES.md`。

视觉素材清单：

| 素材 | 路径 | 来源 |
|---|---|---|
| 项目图标 | `docs/assets/closure/ai-werewolf-icon.svg` / `docs/assets/closure/screenshots/ai-werewolf-icon.png` | deterministic SVG |
| 产品架构图 | `docs/assets/closure/architecture.svg` / `docs/assets/closure/screenshots/architecture.png` | 当前系统模块 |
| Play-Evaluate-Evolve 闭环图 | `docs/assets/closure/play-evaluate-evolve.svg` / `docs/assets/closure/screenshots/play-evaluate-evolve.png` | strict report |
| 数据库证据链图 | `docs/assets/closure/database-evidence-chain.svg` / `docs/assets/closure/screenshots/database-evidence-chain.png` | 数据库模型 / 证据链 |
| 真实对局总览截图 | `docs/assets/closure/screenshots/real-game-overview.png` | replay API + strict report |
| 真实复盘报告截图 | `docs/assets/closure/screenshots/strict-game-review.png` | backend review HTML |

### 附录 G 不建议写入正式报告的数据

`data/experiment/heuristic_20games.json`、`data/experiment/dry_run_*.log`、`data/health/llm_batch_acceptance_fake_*`、`docs/experiments/demo_artifacts/*`、`outputs/winrate_experiment_seed2001.log` 的完整 20 局结论、`data/experiment/multi_tier*` 的方案优劣结论。
