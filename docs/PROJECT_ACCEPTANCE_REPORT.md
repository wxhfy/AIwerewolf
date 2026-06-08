# AI Werewolf 项目总体验收报告

> 验收日期：2026-06-08
> 验收范围：对局引擎、Agent 决策、信息隔离、后端 API/WebSocket、前端展示、Track B 复盘分析、Track C 知识回流、报告导出。
> 验收方式：以当前工作区代码为准，使用本地 fake LLM provider 进行可复现自动化验证；真实外部 LLM/生产 PostgreSQL 长跑实验作为补充验收项。

## 1. 验收结论

本轮验收结论：系统主体功能达到交付演示与答辩验收要求。

已验证能力包括：

| 验收项 | 结论 | 本轮证据 |
|---|---:|---|
| 对局引擎完整流转 | 通过 | `python -m backend.run_demo --seed 7` 到达 `GAME_END`，10 名玩家、157 条事件，包含发言与投票 |
| 全量后端/复盘测试 | 通过 | `python -m pytest tests/ -q`：449 passed, 27 skipped |
| 后端 API 与房间流程 | 通过 | `python scripts/e2e_smoke.py`：E2E smoke passed |
| 信息隔离 | 通过 | `python scripts/verify_visibility_strict.py`：92 passed, 0 failed |
| 前端静态质量 | 通过 | `npm run lint` 通过；`npm run build` 通过，生成 7 个 App Router 路由 |
| 前端浏览器流程 | 通过 | `node tests/ui_smoke.mjs`：UI smoke passed |
| Track B/C 关键链路 | 通过 | `tests/test_api.py tests/test_b_full_acceptance.py tests/test_track_c_evolution.py`：42 passed |
| 复盘报告导出 | 通过 | UI smoke 验证 `/games/{id}/report`、`/reviews/html`、`/reviews.md` |
| 知识回流路径 | 通过 | 修复后完整局 + `save_published_review()` 无知识抽取异常 |

本轮发现并修复的问题：

| 问题 | 影响 | 修复 |
|---|---|---|
| 缺失 `docs/track_b_speech_semantic_audit_integration_report.md` | 全量 pytest 失败 | 恢复 Track B speech semantic audit 集成报告 |
| 缺失 `docs/track_b_speech_act_classifier_v0_report.md` | speech semantic 专项测试失败 | 恢复 speech act classifier v0 报告 |
| Track C `StrategyKnowledgeDocData` 缺 `experiment_id` | 赛后知识回流非致命失败 | 在 `backend/eval/evolution.py` 增加字段并在持久化层传递 |
| `AbstractedLesson.to_pg_dict()` 与 Track C dataclass 字段不匹配 | 知识抽取非致命失败 | 补齐 `doc_id`、`counterfactual_ids`、`expected_metric_effects`，使用原生 JSON list |
| 知识 upsert 合并时将字符串时间写入 DateTime | 知识回流序列化失败 | ORM 合并使用 `_now()`，输出层兼容字符串/DateTime |
| UI smoke 等待旧版进化页文案 | 浏览器 smoke 假失败 | 更新 smoke 断言以匹配当前 `Strategy Evolution` 页面 |

## 2. 自动化验收明细

### 2.1 Python 测试

命令：

```bash
_TEST_ALLOW_FAKE_LLM=true \
LLM_PROVIDER=fake \
AIWEREWOLF_DEFAULT_AGENT_TYPE=llm \
MODEL_POOL=fake:fake-llm \
DOUBAO_MODEL_POOL=fake:fake-llm \
python -m pytest tests/ -q
```

结果：

```text
449 passed, 27 skipped, 26 warnings in 229.29s
```

覆盖重点：

- `tests/test_engine.py`：阶段流转、胜负、警长、PK、白狼王、白痴、公开快照脱敏。
- `tests/test_api.py`：创建对局、房间流程、human action、runtime metrics、leaderboard、非法 heuristic 拒绝。
- `tests/test_visibility_final_agent_input.py`：最终 Agent 输入不能包含隐藏真相。
- `tests/test_b_full_acceptance.py`：Track B 复盘分析、复盘报告、证据引用、B->C 管线。
- `tests/test_track_c_evolution.py` / `test_c_acceptance_verification.py`：知识抽象、检索、DreamJob、patch、tournament、acceptance audit。
- `tests/test_webapp.py` 与 `tests/ui_smoke.mjs`：前端构建和浏览器 smoke。

说明：warning 主要来自依赖 deprecation、未注册 slow marker、测试刻意验证模型 artifact 缺失/损坏 fallback，未构成本轮阻塞。

### 2.2 Demo 对局

命令：

```bash
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake \
AIWEREWOLF_DEFAULT_AGENT_TYPE=llm \
MODEL_POOL=fake:fake-llm DOUBAO_MODEL_POOL=fake:fake-llm \
python -m backend.run_demo --seed 7
```

抽样结果：

| 字段 | 值 |
|---|---|
| phase | `GAME_END` |
| winner | `wolf` |
| players | 10 |
| events | 157 |
| has_chat | true |
| has_vote | true |
| public role leak | false |

### 2.3 后端 E2E Smoke

命令：

```bash
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake \
AIWEREWOLF_DEFAULT_AGENT_TYPE=llm \
MODEL_POOL=fake:fake-llm DOUBAO_MODEL_POOL=fake:fake-llm \
python scripts/e2e_smoke.py
```

结果：

```text
E2E smoke passed
```

覆盖：

- `/api/health`
- `/api/rooms`
- `/api/rooms/{room_id}/games`
- `/api/rooms/{room_id}/snapshot`
- `/api/games`
- `/api/games/{game_id}`
- 多 seed 完整对局结束校验

### 2.4 信息隔离专项

命令：

```bash
python scripts/verify_visibility_strict.py
```

结果：

```text
RESULTS: 92 passed, 0 failed
All information isolation checks passed.
```

覆盖：

- 村民不可见预言家查验、女巫受害者、狼队沟通。
- 狼人只可见狼队信息，不可见预言家和女巫私有信息。
- 预言家只可见自己的查验结果。
- 女巫只可见被刀信息和自己用药信息。
- 守卫只可见自己的守护行为。
- public event 不泄露角色分配或查验结果。

### 2.5 前端构建与浏览器 Smoke

命令：

```bash
cd frontend && npm run lint
cd frontend && NEXT_PUBLIC_BACKEND_ORIGIN=http://127.0.0.1:8000 BACKEND_ORIGIN=http://127.0.0.1:8000 npm run build
node tests/ui_smoke.mjs
```

结果：

```text
npm run lint: passed
npm run build: passed
node tests/ui_smoke.mjs: UI smoke passed
```

构建路由：

| 路由 | 类型 | 说明 |
|---|---|---|
| `/` | Static | 大厅 / 创建房间 |
| `/eval/dashboard` | Static | 复盘看板 |
| `/personas` | Static | Persona 库 |
| `/games/[id]/report` | Dynamic | 单局复盘报告 |
| `/room/[id]/play` | Dynamic | AI 对局观战页 |
| `/room/[id]/human` | Dynamic | 真人参与入口 |

UI smoke 覆盖：

- 完成对局 room snapshot 到达 `GAME_END`。
- 复盘页 iframe 可加载。
- 后端 HTML 复盘页面包含报告与 SVG 视觉资产。
- 首页中英文切换。
- AI 模式创建房间、prepare、进入房间、WebSocket 对局。
- Human 模式创建房间、进入 human play 页面并展示可操作状态。

## 3. 已实现模块清单

| 模块 | 文件/目录 | 职责 | 验收状态 |
|---|---|---|---|
| 游戏引擎 | `backend/engine/game.py` | 初始化、阶段推进、结算、胜负、事件记录 | 通过 |
| 数据模型 | `backend/engine/models.py` | Role/Phase/Action/Event/GameState/Decision | 通过 |
| 阶段管理 | `backend/engine/phase_manager.py`, `phases.py` | 夜晚/白天/特殊阶段组合调度 | 通过 |
| 动作校验 | `backend/engine/actions.py` | 角色、存活、目标合法性 | 通过 |
| 角色配置 | `backend/engine/roles/`, `rules.py` | 基础角色、扩展角色模板、7-12P 配置 | 通过 |
| 信息隔离 | `backend/engine/visibility.py` | GameState -> PlayerView 裁剪 | 通过 |
| Agent 协议 | `backend/agents/base.py` | Agent 接口与 Decision 契约 | 通过 |
| Cognitive Agent | `backend/agents/cognitive/` | Observe/Memory/Planner/Social/Tools/LLM loop | 通过 |
| Agent 工厂 | `backend/agents/factory.py` | LLM-only agent 创建、人类席位接入 | 通过 |
| LLM 客户端 | `backend/llm/` | 多 provider 统一客户端，fake 测试保护 | 通过 |
| API 服务 | `backend/app.py` | FastAPI REST/WebSocket/报告/看板接口 | 通过 |
| 房间管理 | `backend/protocols/rooms.py` | 房间、active game、snapshot buffer | 通过 |
| DB 持久化 | `backend/db/` | games/events/decisions/reviews/knowledge | 通过 |
| Track B 复盘分析 | `backend/eval/per_step_scorer.py`, `track_b.py` | 决策质量指标、复盘报告、证据引用 | 通过 |
| Track C 自进化 | `backend/eval/evolution.py`, `knowledge_abstractor.py` | lesson 抽取、知识生命周期、patch/tournament | 通过 |
| 前端大厅 | `frontend/app/page.tsx` | 配置房间、AI/Human 模式、设置 | 通过 |
| 对局页 | `frontend/app/room/[id]/play/page.tsx` | 三栏玩家、事件流、状态栏、投票/发言/结果 | 通过 |
| Human 模式 | `frontend/app/room/[id]/human/`, hooks | 真人行动输入、身份揭示、目标选择 | 通过 |
| 复盘页 | `frontend/app/games/[id]/report/page.tsx` | iframe 嵌入 HTML 复盘、Markdown 下载 | 通过 |
| Persona 页 | `frontend/app/personas/page.tsx` | 人格库查看/维护入口 | 通过 |
| Smoke 脚本 | `scripts/e2e_smoke.py`, `tests/ui_smoke.mjs` | 后端和浏览器端到端验收 | 通过 |

## 4. 核心设计说明

### 4.1 Play -> Evaluate -> Evolve 闭环

系统不是只跑单局游戏，而是完整闭环：

```text
Play 对局执行
  -> GameEvent / AgentDecision / Snapshot 落库
Evaluate 赛后复盘
  -> DecisionScore / ScoredStep / PublishedReview
Evolve 经验抽取
  -> StrategyKnowledgeDoc(candidate/active/deprecated)
Retrieve 下一局策略回流
  -> StrategyRetriever 注入 Agent 策略层
```

该设计使系统具备三个能力：能玩、能解释、能积累。

### 4.2 引擎主控，Agent 只输出意图

`WerewolfGame` 是规则唯一主控。Agent 只能通过 `Decision` 表达 `talk/vote/attack/divine/guard/witch/shoot/boom/skip` 等意图，不能直接修改 `GameState`。

收益：

- 阶段和结算可复现。
- LLM 输出非法时可被校验。
- 角色扩展只需要接入 Phase/Action/Resolution。
- 赛后可以用事件和决策审计还原过程。

### 4.3 Truth State 与 PlayerView 分离

`GameState` 保存完整真相；`Visibility.for_player()` 为每个 Agent 裁剪局部 `PlayerView`。

关键边界：

- 自己可见自己的 role/alignment。
- 狼人可见狼队队友。
- 预言家只可见自己的查验。
- 女巫只可见自己被通知的夜间受害者和用药。
- 公开快照隐藏夜间子阶段细节和角色能力状态。

该设计是狼人杀信息不对称的工程核心。

### 4.4 CognitiveAgent：Observe -> Think -> Act

Agent 决策链路：

```text
PlayerView
  -> Observation
  -> Memory / BeliefTracker / SocialModel / Planner
  -> AgentLoop tools
  -> Decision
```

工具包括：

- `search_strategies`
- `recall_memory`
- `check_rules`
- `get_social_info`
- `analyze_votes`
- `set_strategic_intent`
- `submit_decision`

收益：

- 每个 Agent 有角色、人设、记忆和社交判断。
- 工具调用 trace 可审计。
- 策略回流不需要改模型权重。

### 4.5 三层 Prompt

Prompt 分层：

| 层 | 作用 |
|---|---|
| Persona / MBTI | 控制表达风格和认知倾向 |
| Role Identity | 定义身份、阵营、技能、胜利条件 |
| Strategy + Tools | 注入当前可用策略、反模式、检索结果 |

Track C 产生的新知识只进入 Strategy 层，避免污染身份规则和人格风格。

### 4.6 Track B：逐步复盘而不是只看胜负

Track B 关注每一步行为质量：

- 发言是否提供有效信息。
- 投票是否命中高价值目标。
- 夜间技能是否合理。
- 是否出现信息泄露、非法目标、无效发言、错误站边。
- 是否有可引用证据和 counterfactual。

输出包括 `DecisionScore`、`ScoredStep`、`PlayerReviewReport`、`PublishedReview`，支撑复盘和排行榜。

### 4.7 Track C：知识抽取与安全回流

Track C 从 Track B 的高光和失误中抽取 lesson，形成 `strategy_knowledge_docs`。

生命周期：

```text
candidate -> active -> deprecated
```

安全约束：

- 不把当前局私有信息作为下一局公共策略。
- 保留 source_game/source_event/source_item 证据链。
- 默认写 candidate，避免新经验直接污染 active 池。
- 检索侧使用 confidence / visibility / privacy / applicability 过滤。

## 5. 设计历程

项目设计从“跑通一局”逐步演进为“可分析、可复盘、可自进化”的系统。

| 阶段 | 初始问题 | 设计演进 | 当前结果 |
|---|---|---|---|
| 基础对局 | 零散规则无法完整结算 | 建立 `WerewolfGame` 与 Phase 状态机 | 夜晚、白天、投票、胜负跑通 |
| 信息隔离 | Agent 容易获得上帝视角 | 引入 `Visibility` 和 `PlayerView` | 每个 Agent 只看身份允许的信息 |
| 决策审计 | 对局结束后无法解释行为 | 建立 GameEvent、AgentDecision、Snapshot | 每步行为可回放、可分析 |
| 角色化 Agent | 简单 Agent 行为单薄 | CognitiveAgent + Memory + SocialModel | 角色差异和推理过程可记录 |
| Prompt 分层 | 人设、身份、策略混杂 | Persona / Role / Strategy 三层 | 策略可独立实验和回流 |
| 策略检索 | 策略写死在 Prompt 中 | StrategyRetriever + RetrievalPolicy | active 知识可动态进入决策 |
| Track B | 胜负不能解释质量 | PerStepScorer + PublishedReview | 能定位高光、失误和证据 |
| Track C | 复盘不能复用 | KnowledgeAbstractor + knowledge docs | 形成 Play-Evaluate-Evolve 闭环 |
| strict/smoke | 分散测试无法证明整体 | pytest + e2e + UI smoke + visibility strict | 当前本地验收闭环通过 |

设计演进总结：系统先把规则控制权从 LLM 中抽离到引擎，再把真实状态与可见状态分离，随后通过审计链条将每个 Agent 行为结构化，最后把复盘结果抽象为下一局可检索的策略知识。这个演进路径保证了工程正确性、狼人杀公平性和进阶课题的可解释性。

## 6. 风险与补验项

| 风险/未覆盖项 | 当前状态 | 建议 |
|---|---|---|
| 真实外部 LLM 长跑 | 本轮使用 fake LLM 复现验证 | 答辩前用真实 provider 跑 7P/9P/12P 各 1 局，并保存输出 |
| 生产 PostgreSQL 严格验收 | 本轮依赖当前本地 DB，可通过 SQLite/PG fallback | 使用 `scripts/run_backend_full_strict.py` 在真实 DB + 真实 LLM 下再跑一次 |
| 长时间并发/多人重连压力 | UI smoke 覆盖单浏览器和 WebSocket 基础路径 | 补 2-3 个并发 WS/reconnect 手测 |
| Track C 晋级效果 | 单元/集成测试验证 lifecycle 和 B->C 路径 | 用固定 seed A/B 记录 active 策略晋级后的胜率变化 |
| 模型 artifact warning | 测试中允许模型缺失 fallback | 若正式展示训练模型，应补齐 artifact 并记录版本 |
| 旧材料中的实验数字 | 存在历史报告和 DB 快照 | 最终论文/答辩只引用带日期、命令、输出文件的数字 |

## 7. 可放入最终交付报告的摘要

本项目完成了一个 AI 狼人杀多智能体对战与自进化系统。系统以 `WerewolfGame` 为规则核心，支持从夜晚行动、白天发言、投票放逐到胜负判定的完整对局流程；以 `Visibility / PlayerView` 保证每个 Agent 只能看到身份允许的信息；以 `CognitiveAgent` 和 AgentLoop 实现角色化决策、记忆、社交判断和工具调用；以 PostgreSQL 保存事件、快照、决策和复盘证据链；以 Track B 对每一步决策进行赛后复盘分析并生成复盘报告；以 Track C 将高光和失误抽象为策略知识，通过 candidate/active/deprecated 生命周期管理后回流到下一局策略检索层。

本轮验收在本地可复现环境下完成，核心自动化结果为：全量 pytest `449 passed, 27 skipped`，后端 E2E smoke passed，信息隔离专项 `92 passed, 0 failed`，前端 lint/build passed，Playwright UI smoke passed。系统已具备答辩演示所需的完整对局、观战 UI、复盘报告、复盘看板和策略进化闭环。
