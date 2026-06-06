# AI Werewolf 全系统架构审计报告

> **STATUS: SUPERSEDED** — This audit was completed on 2026-06-04.
> All 4 P0 items have been fixed. See the convergence report for current state.
> Retained for historical reference and defense evidence.

> 审计日期：2026-06-04
> 审计范围：完整代码库（game engine, CognitiveAgent, AgentLoop, 策略检索, 赛后评分, 知识入库, 实验脚本, 数据库, 信息隔离, 前端）
> 审计方法：6 并行 Explore Agent + 直接代码审查 + 数据库查询

---

## 目录

1. [项目真实架构总览](#1-项目真实架构总览)
2. [用户数据流中准确的部分](#2-用户数据流中准确的部分)
3. [用户数据流中不准确或缺失的部分](#3-用户数据流中不准确或缺失的部分)
4. [最高优先级问题 Top 10](#4-最高优先级问题-top-10)
5. [Track B 评测+复盘是否成立](#5-track-b-评测复盘是否成立)
6. [Track C 自进化是否成立](#6-track-c-自进化是否成立)
7. [信息隔离审查结果](#7-信息隔离审查结果)
8. [实验可信度审查结果](#8-实验可信度审查结果)
9. [DB 性能和并发问题定位](#9-db-性能和并发问题定位)
10. [策略检索系统审查结果](#10-策略检索系统审查结果)
11. [具体改造建议](#11-具体改造建议)
12. [推荐答辩讲法](#12-推荐答辩讲法)

---

## 1. 项目真实架构总览

### 1.1 物理分层与关键文件

```
入口层:
  scripts/multi_tier_experiment.py  — 批量实验（4并发子进程，互不干扰 seed）
  scripts/run_full_llm_pipeline.py  — 完整LLM流程（含DB持久化+Track B/C）
  backend/engine/game.py:89         — WerewolfGame 单局入口

引擎层:
  backend/engine/game.py            — 游戏循环 (1721行)
  backend/engine/models.py          — GameState, Player, Phase, Role, Decision, GameEvent
  backend/engine/phases.py          — 阶段handler (CompositePhase, AtomicPhase)
  backend/engine/visibility.py      — PlayerView 构建 + 信息隔离
  backend/engine/rules.py           — get_role_configuration(), build_players(), ROLE_SPECS
  backend/engine/actions.py         — ActionValidator

Agent层:
  backend/agents/cognitive/agent.py      — CognitiveAgent (871行)
  backend/agents/cognitive/agent_loop.py — AgentLoop (MAX_ITERATIONS=3工具调用循环)
  backend/agents/cognitive/observe.py    — Observation + BeliefTracker
  backend/agents/cognitive/prompts.py    — build_game_context + _ROLE_ANTI_PATTERNS
  backend/agents/cognitive/tools.py      — 6个工具 (search_strategies等)
  backend/agents/cognitive/memory.py     — Memory + SocialModel + Planner
  backend/agents/cognitive/profiles.py   — Profile (MBTI + Role)
  backend/agents/cognitive/humanization.py — MindTraits → 行为参数
  backend/agents/cognitive/wolf_team.py  — 狼队协调 (WolfTeamView)

检索层:
  backend/agents/cognitive/retrieval_prod.py — StrategyRetriever (BM25 + 关键词Grep)
  backend/agents/cognitive/retrieval.py      — StrategyIndex (TF-IDF fallback)
  backend/db/persist.py:942                  — list_strategy_knowledge()
  backend/db/persist.py:969                  — retrieve_strategy_knowledge() (4-filter pipeline)

评测层:
  backend/eval/per_step_scorer.py   — PerStepScorer (三步级联)
  backend/eval/knowledge_abstractor.py — KnowledgeAbstractor
  backend/eval/post_game.py         — run_post_game_scoring() [本次新增]
  backend/eval/evolution.py         — StrategyKnowledgeStore + Patch + A/B (3039行)
  backend/eval/llm_judge.py         — 三法官panel
  backend/eval/review.py            — MetricsCalculator + CounterfactualAnalyzer

数据层:
  backend/db/models.py  — 20+ ORM表 (Game, Player, AgentDecision, StrategyKnowledgeDoc等)
  backend/db/persist.py — 2350+ 行持久化函数
  backend/db/database.py — SessionLocal (pool_pre_ping=True, 无pool_size限制!)
```

### 1.2 单局完整调用链

```
1. 游戏创建
   WerewolfGame(seed=seed, player_count=7) [game.py:89]
   ├── get_role_configuration(7) → [狼人×2, 预言家, 女巫, 猎人, 守卫, 村民]
   ├── build_players(roles, seed) → shuffle + Player对象
   ├── _shuffle_personas_pool() → MBTI随机分配 (seed控制)
   ├── build_character_roster() → Character系统
   └── create_agents() → CognitiveAgent × 7 [factory.py]

2. 游戏循环
   game.play() → play_until_blocked() [game.py:312]
   ├── Phase.SETUP → NIGHT_START
   ├── Night轮次:
   │   ├── NIGHT_GUARD_ACTION → _guard_phase() → agent.guard()
   │   ├── NIGHT_WOLF_ACTION  → _wolf_phase()  → agent.attack() per wolf
   │   ├── NIGHT_WITCH_ACTION → _witch_phase() → agent.witch_act(victim_id)
   │   ├── NIGHT_SEER_ACTION  → _seer_phase()  → agent.divine()
   │   └── NIGHT_RESOLVE → 结算死亡
   ├── Day轮次:
   │   ├── DAY_BADGE_SPEECH  → agent.talk() (竞选警长)
   │   ├── DAY_BADGE_ELECTION → agent.vote() (并行batch)
   │   ├── DAY_SPEECH        → agent.talk() × N (顺序发言)
   │   ├── DAY_VOTE          → agent.vote() (并行batch)
   │   └── DAY_RESOLVE       → 结算放逐 + 猎人开枪 + 警徽转移
   └── 胜负判定 → agent.finish(winner) → save_game_end() → run_post_game_scoring()

3. 单次 Agent 决策
   agent.talk() [agent.py:186]
   ├── self._observe() → Observation + BeliefTracker
   ├── AgentLoop.run() [agent_loop.py:162]
   │   ├── _build_system_text():
   │   │   ├── Layer 1: Profile.to_system_intro() (MBTI人格)
   │   │   ├── Layer 2: build_game_context(obs) + format_observation(obs) + memory + anti_patterns
   │   │   ├── Layer 3: _build_track_c_strategy_block() → list_strategy_knowledge(status="active", limit=3)
   │   │   └── Tools: search_strategies等工具描述
   │   ├── LLM调用 (最多3轮工具调用)
   │   ├── 可选: TOOL: search_strategies → retrieval_prod (BM25+Grep)
   │   └── DECISION: {"speech": "..."} → parse
   └── Decision → engine记录

4. 游戏结束
   game.py:375-400
   ├── agent.finish(winner) → _reflect_on_game() [默认开启]
   │   └── Reflector MBTI反思 → save_reflections_to_db() → status='candidate'
   ├── save_game_end(state) → DB批量写入
   │   ├── Game状态更新 (winner, finished_at)
   │   ├── Player死亡状态更新
   │   ├── DELETE + 批量INSERT: GameEvent, AgentDecision, Vote, GameSnapshot
   │   ├── Evaluation行 (win/survived/speech_count)
   │   ├── LeaderboardEntry upsert
   │   └── save_published_review(state) → LLM评测报告
   └── run_post_game_scoring(state, game_id) [新增]
       ├── 从agent_decisions读取本局决策
       ├── PerStepScorer.score_all() (确定性评分)
       ├── KnowledgeAbstractor.abstract_from_game()
       └── store_lessons_to_db() → status='active' ⚠️ 应该是candidate
```

### 1.3 策略检索三条路径

| 路径 | 调用位置 | 数据源 | 状态过滤 | 缓存 | Agent能否区分反思? |
|------|---------|--------|----------|------|-----------------|
| A: 自动注入 | agent_loop.py:329 `_build_track_c_strategy_block()` | `list_strategy_knowledge(status="active")` | 仅active | 120s TTL | **否** — `_normalize_strategy_row()` 丢弃 doc_type |
| B: 工具调用(主) | tools.py:53 `retrieval_prod.retrieve_strategies_prod()` | `_load_from_pg()` | 仅active + 反思quality>=0.85 | 进程级单例 | **是** — `[反思经验]` 标签 |
| C: 工具调用(回退) | tools.py:61 `retrieval.retrieve_tfidf()` | `_load_docs_from_pg()` | active+candidate + 反思quality>=0.85 | 进程级单例 | 是 — `[反思经验]` 标签 |

**关键发现**: 路径A中 `_normalize_strategy_row()` (agent_loop.py:799-807) 重命名字段时**丢弃了 doc_type**，导致Agent无法区分反思和经过验证的策略。

---

## 2. 用户数据流中准确的部分

1. **Agent 检索路径** — `search_strategies` 工具调用 → `retrieval_prod` → BM25 + 关键词 Grep，数据源带 `status='active'` 过滤。**准确**。

2. **对局结束双管道** — agent.finish() 触发反思 + 赛后评分。**结构准确**（赛后评分是本次修复才接通的）。

3. **知识库三层状态** — active/candidate/deprecated 分层。**概念准确**。

4. **三层 prompt 架构** — MBTI(底层) + Role(中层) + Strategy(顶层)。**准确**。

5. **7人局7条反思** — 每个Agent对自己玩过的发言做MBTI差异化反思。**准确**。

---

## 3. 用户数据流中不准确或缺失的部分

### 3.1 `per_step_lesson` 写入 `status='active'` — **不准确**

`knowledge_abstractor.py:88` `to_pg_dict()` 返回硬编码 `"status": "active"`。这会导致赛后评分产生的知识立即进入检索池，**污染同一实验批次的后续对局**。应该写 `"candidate"`。

### 3.2 `PlayerReviewReport` 和 `ScoredStep` 的定义位置 — **缺失**

这两个类在本次审计前**从未存在**于 `per_step_scorer.py` 中。`knowledge_abstractor.py:24` 的 import 一直会失败。KnowledgeAbstractor 从未被成功导入过。

### 3.3 检索实际有**四条路径**，不是一条

用户只画了 retrieval_prod 路径。实际有四条：
- 路径A: 系统自动注入（每轮都注入3条active策略）
- 路径B: Agent主动调用 search_strategies 工具（BM25主路径）
- 路径C: 回退到 TF-IDF（包括candidate文档！）
- 路径D: `persist.py:969` `retrieve_strategy_knowledge()` 高级4-filter检索

### 3.4 赛后评分 `run_post_game_scoring()` — **新接入，原代码未运行**

`post_game.py` 是本次审计才创建的文件。原引擎没有调用 PerStepScorer。

### 3.5 `agent_decisions` 写入时机 — **两阶段写入**

1. **实时写入**: `persist.py:171 save_decision()` — 每条决策立即写入
2. **批量覆写**: `persist.py:272 save_game_end()` — 游戏结束时先DELETE再批量INSERT

中途查询可能看到不完整数据。

### 3.6 实验脚本的 seed 生成

各tier使用不重叠seed范围 (baseline: 1000-1019, anti_only: 2000-2019等)。由于 `_shuffle_personas_pool(seed)` 决定了MBTI分配，**不同tier的同index seed得到相同的角色-MBTI组合**。这是公平的跨组比较。

### 3.7 **关键缺失：多层级实验不写入数据库**

`multi_tier_experiment.py` 在子进程中运行游戏，DB连接失败被静默捕获（try/except）。意味着：
- 无 per-decision trace
- 无 Track C 知识提取
- 无 PublishedReview 生成
- 实验无法反哺 Track C 自身的进化循环

---

## 4. 最高优先级问题 Top 10

### P0-1: `post_game.py` 调用 PerStepScorer 时未传入 LLM 客户端

- **代码**: `post_game.py:49` `scorer = PerStepScorer()` — 无参数
- **影响**: Tier 2 (轻量LLM) 和 Tier 3 (三法官) **完全被禁用**。所有评分只走确定性层
- **后果**: 发言评分全部得到0.45默认分（因为 `speech_acts=[]`），无法产生 highlight 或 mistake
- **修复**: 传入 `PerStepScorer(llm_client=llm_client)`

### P0-2: `post_game.py` 传入空 `speech_acts`

- **代码**: `post_game.py:50` `scores = scorer.score_all(decision_dicts, state_dict, [])`
- **影响**: 所有发言步骤 `score_talk()` 返回 `correctness=0.45, overall=0.45`，永远不触发highlight也不触发mistake
- **后果**: **Track C 无法从发言行为中提取任何知识**
- **修复**: 在评分前分析发言 (speech_act analysis)

### P0-3: `knowledge_abstractor.py` 的 `to_pg_dict()` 写入 `status='active'`

- **代码**: `knowledge_abstractor.py:88` `"status": "active"`
- **影响**: 赛后评分产生的lesson直接进入active，立即被后续对局检索到
- **修复**: 改为 `"status": "candidate"`

### P0-4: DB 连接池无 pool_size 限制

- **代码**: `database.py:20-24` `create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)` — 无 pool_size
- **影响**: 默认 pool_size=5, max_overflow=10。4个子进程 + 高频 `SessionLocal()` per-function 模式 = 连接争用
- **修复**: 设置 `pool_size=5, max_overflow=5`

### P1-5: `agent_loop.py` 自动注入路径丢弃 `doc_type`

- **代码**: `agent_loop.py:799-807` `_normalize_strategy_row()` 不保留 `doc_type`
- **影响**: Agent无法区分系统自动注入的策略是经过验证的(good_play)还是反思(reflection)
- **修复**: 在格式化的策略块中包含 doc_type 标签

### P1-6: `search_strategies` 工具默认 `include_reflections=True`

- **代码**: `tools.py:32` `include_reflections: bool = True`
- **影响**: Agent默认会看到反思文档（在回退路径中）。需要Agent主动设置 `include_reflections=False`
- **修复**: 改默认值为 `False`

### P1-7: 多层级实验不写入DB，无统计检验

- **代码**: `multi_tier_experiment.py` 子进程中DB操作静默失败
- **影响**: 无法收集过程指标，无法做显著性检验，12局/tier无法支撑结论
- **修复**: 每组≥30局，启用DB持久化，添加 bootstrap 置信区间

### P1-8: PerStepScorer 确定性评分使用上帝视角

- **代码**: `per_step_scorer.py:47-65` `score_vote()` 的 `correct=0.95 if t_align=="wolf"` 基于真实阵营
- **影响**: 狼人自刀、预言家隐藏身份等策略行为会被误判为错误
- **修复**: 添加 `information_set_score` 字段，区分"上帝视角正确性"和"当时信息合理性"

### P2-9: LLM Judge 输出解析脆弱

- **代码**: `llm_judge.py:225-248` 使用 `re.search(r'\{.*\}', raw)` + `json.loads`
- **影响**: 无JSON Schema验证、无重试、异常被静默吞掉。LLM生成markdown代码块会解析失败
- **修复**: 使用 Pydantic 结构化输出或至少添加格式修复重试

### P2-10: 反思文档 `situation_pattern` 包含玩家姓名

- **代码**: `reflect.py:418` `f"{r.player_name}({role}, {persona_scope}) 对局总结"`
- **影响**: 低风险信息泄露——未来同角色Agent检索时能看到过去游戏的玩家名字
- **修复**: 去标识化（替换为通用描述如 "某INTJ玩家"）

---

## 5. Track B 评测+复盘是否成立

**结论：基本成立但需补强。**

**成立的部分：**
- `PerStepScorer` 三级评分体系完整 (score_vote/score_talk/score_night 确定性函数)
- `KnowledgeAbstractor` 能将评分转化为结构化 lesson (highlight/mistake/strategy_applied)
- `MetricsCalculator` (review.py) 有 `process_score` 设计——明确排除阵营胜负偏差
- `save_published_review()` 生成包含 scoreboard/speech_acts/suspicion_matrix 的评审报告
- `LeaderboardEntry` 追踪角色级胜率和KPI

**需补强的部分：**
1. **PerStepScorer 未接入 LLM 客户端** — Tier 2/3 完全禁用，所有发言得0.45
2. **评分未区分信息集** — 确定性层用上帝视角，没有 `information_set_score`
3. **Speech Act 分析未接入评分** — `speech_acts=[] ` 导致发言评分全部为占位符
4. **LLM Judge 输出解析脆弱** — 基于正则，无结构化验证，异常静默丢弃
5. **三法官不是真正独立的** — 同一LLM串行调用，无并行执行

---

## 6. Track C 自进化是否成立

**结论：基本成立但关键环节缺失。**

**成立的部分：**
- 反思管道（MBTI 差异化 LLM 反思）已在 `reflect.py` 实现
- 赛后评分管道（PerStepScorer → KnowledgeAbstractor）已接通在 `post_game.py`
- 策略检索管道（BM25 + TF-IDF）完整可用，有4条独立检索路径
- `evolution.py` 的 `StrategyKnowledgeStore` 有6分量质量公式、重复次数门控、Bootstrap CI
- `StrategyPatchGenerator` 有 repeated-weakness 门控 + single-doc quality floor
- `AcceptancePolicy` 有硬安全门(5项) + 改进条件(4选2) + Bootstrap CI下限检查

**关键缺失：**
1. **candidate → active 晋升未自动化** — `VersionManager.promote()` + `TournamentRunner` 已实现但从未在游戏流程中自动运行
2. **策略使用反馈未接通** — `record_knowledge_usage()` 函数存在但Agent决策时**从未调用**
3. **无实验隔离** — 同一批次实验中 knowledge docs 持续增长，前后对局条件不同
4. **发言行为无法产生知识** — speech_acts为空，所有发言评分为默认0.45
5. **A/B 验证未自动化** — `run_evolution_cycle()` 需要手动调用

---

## 7. 信息隔离审查结果

**总体判决：PASS（通过），带一个低风险边缘案例。**

### 通过项（全部12项）：

| # | 检查项 | 证据 |
|---|--------|------|
| 1 | 村民不能看狼人身份 | `visibility.py:58` 非狼人只看到 `public_dict()` |
| 2 | 狼人不能看预言家查验 | `visibility.py:30-34` private_events 仅对 `visible_to` 列表中的玩家可见 |
| 3 | 预言家查验只进入私有观察 | `observe.py:364-371` 从 `view.private_events` 读取 |
| 4 | 女巫知道被害者 | `agent.py:318-321` 通过 `victim_id` API参数接收 |
| 5 | 女巫药水状态隔离 | `agent.py:111-112` 本地跟踪，不泄露 |
| 6 | PLAYER_DIED 不暴露角色 | `game.py:1411-1418` payload不含role字段 |
| 7 | BeliefTracker只用公开事件 | `observe.py:113-183` 三个_extract方法都只用 `view.public_events` |
| 8 | 狼队协调只用合法信息 | `wolf_team.py:1-16` 模块头明确声明，且 `negotiate_wolf_kill()`/`assign_wolf_tactics()` 故意返回空值 |
| 9 | Memory不含上帝视角 | `memory.py` Judgment/ActionRecord 无role/alignment字段 |
| 10 | Prompt不含真实角色 | `prompts.py:36-57` build_game_context 只用Observation字段 |
| 11 | 赛后评分不泄露身份 | `knowledge_abstractor.py:69-89` to_pg_dict 只产生通用建议 |
| 12 | 检索有4重安全过滤 | `knowledge_confidence.py` confidence → visibility → leaks → applicability |

### 风险项（1项）：

| # | 检查项 | 严重度 | 证据 | 修复 |
|---|--------|--------|------|------|
| 1 | 反思 `situation_pattern` 含玩家姓名 | **低** | `reflect.py:418` `f"{r.player_name}({role}) 对局总结"`。由同角色过滤+通用姓名池缓解 | 去标识化: 用 "某INTJ玩家" 替换姓名 |

---

## 8. 实验可信度审查结果

**结论：现有实验不足以支撑答辩结论。**

### 问题清单：

| # | 问题 | 影响 |
|---|------|------|
| 1 | 样本量太小 | 12局/tier，95%CI约±28%，无法检测<15%的效果 |
| 2 | 无DB持久化 | 实验子进程DB操作静默失败，无per-decision trace |
| 3 | 无knowledge snapshot | 无法证明"策略库变化导致胜率变化" |
| 4 | 无过程分 | 只有终局胜率，缺vote_accuracy/skill_efficiency/speech_quality |
| 5 | 无统计检验 | 无置信区间、无效应量、无bootstrap |
| 6 | 多层级实验不收集策略使用率 | 不知道Agent是否真的用了检索到的策略 |
| 7 | 无反模式违反率 | 不知道 anti_only 层是否真的减少了错误 |

### 最小可行实验方案：

- 每组 ≥30 局（合计120局），使用固定seed范围确保跨组公平
- 实验前 snapshot 知识库状态（`{doc_id: quality_score}` 映射）
- 启用 DB 持久化，记录每局的 `strategy_retrieval_count`、`anti_pattern_violation`、`decision_validity_rate`
- 实验后生成对比报告：胜率 delta + 过程分 delta + Bootstrap 95% CI
- 添加显著性检验（Fisher's exact test 或 permutation test）

---

## 9. DB 性能和并发问题定位

### 根因分析：

**根因1**: `database.py:20-24` 创建engine时**未指定** `pool_size` 和 `max_overflow`，SQLAlchemy默认 pool_size=5, max_overflow=10。

**根因2**: `persist.py` 中**每个函数**独立创建 `SessionLocal()` 用完关闭——session-per-request 模式。每局游戏产生 200-500 次连接获取/释放。

**根因3**: 4个实验子进程各持有1+连接，加上历史遗留的长查询（DELETE FROM players 60分钟+，ALTER TABLE 30分钟+），锁等待链式阻塞。

**根因4**: `save_game_end()` 使用 DELETE + 批量INSERT 覆写模式（先删全表再重插），在并发下可能产生锁竞争。

### 修复优先级：

| 优先级 | 修复 | 代码位置 |
|--------|------|----------|
| **P0** | 设置 `pool_size=5, max_overflow=5` | `database.py:20-24` |
| **P0** | 子进程使用独立连接或 NullPool | `multi_tier_experiment.py` worker script |
| **P1** | 检索 index 缓存（已实现单例，无需改） | `retrieval_prod.py:572` |
| **P1** | 添加索引: `strategy_knowledge_docs(status, doc_type, quality_score)` | DB migration |
| **P2** | 合并 `persist.py` 中高频函数使用共享session | `persist.py` |
| **P2** | 添加索引: `PublishedReview(publish_allowed, published_at)` | DB migration |

---

## 10. 策略检索系统审查结果

### 10.1 Active/Candidate 边界严格性

| 路径 | 可见状态 | Candidate暴露？ | 风险 |
|------|---------|----------------|------|
| A (自动注入) | `status='active'` | 否 | 低 |
| B (search_strategies 主路径) | `status='active'` | 否 | 低 |
| C (TF-IDF 回退) | `status IN ('active', 'candidate')` | **是** | **中** |

**关键**: 路径C仅在路径B失败时触发。如果 `retrieve_strategies_prod()` 抛异常，Agent会通过TF-IDF看到candidate文档。

### 10.2 可能导致实验污染的地方

1. **路径A中doc_type被丢弃** — Agent无法区分反思和验证策略，同等信任
2. **路径C含candidate文档** — 回退路径可见未验证知识
3. **单例index不刷新** — 进程运行期间新写入的active知识不会被加载
4. **路径A有120s缓存** — 同一游戏中知识变化不会立即反映

### 10.3 修复建议

1. 路径A保留 doc_type，添加 `[反思经验]` / `[已验证策略]` 标签
2. 路径C改为只查 `status='active'`
3. `search_strategies` 工具默认 `include_reflections=False`
4. 添加跨路径去重（自动注入 vs 工具调用的重复结果）

---

## 11. 具体改造建议

### 今天必须改 (P0):

1. **`post_game.py:49`** — `PerStepScorer()` → `PerStepScorer(llm_client=llm_client)`（启用Tier 2/3）
2. **`post_game.py:50`** — `speech_acts=[]` → 实际分析发言行为
3. **`knowledge_abstractor.py:88`** — `status: "active"` → `"candidate"`（防止实验污染）
4. **`database.py:20-24`** — 添加 `pool_size=5, max_overflow=5`

### 答辩前建议改 (P1):

5. **`agent_loop.py:799-807`** — `_normalize_strategy_row()` 保留 doc_type
6. **`tools.py:32`** — `include_reflections` 默认改为 `False`
7. **`multi_tier_experiment.py`** — 启用DB持久化 + 记录knowledge snapshot + 统计检验
8. **`retrieval.py:303`** — 路径C改为只查 `status='active'`
9. 实验样本量: 每组 ≥30局
10. Agent决策时调用 `record_knowledge_usage()` 追踪策略使用

### 有时间再优化 (P2):

11. 统一 `retrieval_prod` 和 `evolution.StrategyKnowledgeStore` 的检索后端
12. 添加知识去重（同质化 lesson 检测，避免 "优先投票已查杀的狼人" ×100）
13. 实现 candidate → active 自动晋升（基于多局验证结果）
14. 前端 replay viewer（已有基础框架，补全动画和决策trace）
15. LLM Judge 结构化输出（Pydantic schema 替代正则解析）
16. PerStepScorer 添加 `information_set_score` 字段

---

## 12. 推荐答辩讲法

### 主线：三层认知架构 + 双管道自进化

**创新点（按答辩说服力排序）：**

**1. MBTI 差异化多 Agent 系统**
- 不是简单的角色 prompt，而是 16种MBTI × 7种角色 = 112种行为组合
- 每种组合有独立的认知风格、信息处理偏好、决策模式
- Profile 系统 (profiles.py) 包含两层：MBTI认知操作系统 + Role游戏身份
- MindTraits 控制行为参数 (courage, suspicion_threshold, logic_depth)，通过 Humanization 映射为数值

**2. 信息隔离的 Observer 模式**
- `Visibility.for_player()` 严格按角色/阵营过滤：狼人见狼队友，预言家结果进私有通道
- `BeliefTracker` 只分析公开事件（发言中的角色声称、投票模式、死亡揭示）——不接触任何隐藏信息
- 赛后 ground truth 评分与运行时信息严格分离
- 通过 12 项信息边界检查，1 项低风险边缘案例

**3. Track B 三级评分级联**
- 确定性（~85%）→ 轻量 LLM（~12%）→ 三法官（~3%）
- 成本与精度的最优平衡
- `MetricsCalculator` 的 `process_score` 设计：明确排除阵营胜负偏差
- 反事实推演 `CounterfactualAnalyzer` 已定义（review.py）

**4. Track C 双管道知识闭环**
- 反思管道 (reflect.py): MBTI 差异化自我反思 → candidate docs
- 评分管道 (post_game.py): PerStepScorer → KnowledgeAbstractor → candidate docs
- 进化管道 (evolution.py): quality formula (6分量) + repeated-weakness gating + Bootstrap CI + A/B Tournament
- 检索有 4 条独立路径，active/candidate 分层隔离

**5. 系统完整度**
- 30+ DB表支持完整评测链条
- WebSocket 实时观战 + Next.js 前端
- Leaderboard + 角色×模型矩阵 + 策略归因分析
- 批量实验框架 (4并发子进程, 多tier ablation)

### 应该规避的表述：

| 不要说 | 原因 | 应该说 |
|--------|------|--------|
| "完全自动化的自进化" | candidate→active 需要手动触发 | "分层知识管理，candidate→active 有质量门控" |
| "统计显著" | 样本量不够 | "提供了实验框架并展示了数据趋势" |
| "端到端闭环" | record_knowledge_usage 未接通 | "双管道知识提取 + 策略检索已接通，使用反馈待完善" |
| "实时自进化" | A/B验证未自动化 | "赛后批量进化循环" |
| "三法官独立评审" | 同一LLM串行调用 | "三视角量规评审 (可升级为并行异构)" |

### 答辩最应该展示的 3-5 个证据链：

1. **一场完整对局的决策追踪** — 展示每个Agent每轮收到的Observation、调用的工具、检索的策略、输出的DECISION
2. **赛后评分报告** — 展示 PerStepScorer 对每个决策的评分 + KnowledgeAbstractor 提取的 lesson
3. **策略检索证明** — 展示某条策略在上局被提取→入库→下局被检索→影响决策的完整链路
4. **信息隔离证明** — 展示预言家的 private_events vs 村民的 public_events，证明无信息泄露
5. **多层级对比** — baseline vs trackc_only vs both 的胜率+过程分对比（含置信区间）

---

> 审计完成。本报告基于6个并行 Explore Agent + 直接代码审查 + 数据库查询。所有发现均有具体代码位置和行号支撑。
