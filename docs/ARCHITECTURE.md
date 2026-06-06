# AI Werewolf — 系统架构

> 2026-06-05 | 当前版本: `feat/strategy-enhance` (已合并 main)
> 验证状态: STRICT MODE PASSED | Game `edbde010` | 7 人 1 天 | Village 胜

---

## 一句话主线

> 我们做了一个 AI 狼人杀多智能体系统，不只会玩，还能复盘每个关键决策，通过反事实评估定位 bad case，并把经过可信度、权限和适用条件过滤的策略知识回流到下一代 Agent。

```
Play    = CognitiveAgent + RoleStrategyCard + WolfTeamView + BeliefTracker
Evaluate = 三级评分级联 + 反事实推演 + Judge 校准 + 结构化报告
Evolve  = L0-L4 知识分层 + 4-filter 安全管线 + 回验 + A/B Leaderboard
```

---

## 1. 系统总览

```
┌────────────────────────────────────────────────────────────┐
│                      Game Engine                            │
│  WerewolfGame ── Phase State Machine ── _batch_ask (并行)   │
│  rules.yaml → RoleRegistry → build_players()               │
└──────────────┬─────────────────────────────────────────────┘
               │ PlayerView (信息隔离)
               ▼
┌──────────────────────────────────────────────────────────────┐
│                    CognitiveAgent                             │
│  Observe ──→ Think (AgentLoop) ──→ Act (Decision)            │
│  ┌─────────┐  ┌──────────────┐  ┌──────────────────┐        │
│  │ Layer 1 │  │ Layer 2      │  │ Layer 3           │        │
│  │ MBTI    │→│ Role Identity│→│ Strategy + Tools   │        │
│  │ Persona │  │ + 能力边界    │  │ (检索/规则查询)    │        │
│  └─────────┘  └──────────────┘  └──────────────────┘        │
│  Memory + BeliefTracker + WolfTeamView + Humanization        │
└──────────────┬───────────────────────────────────────────────┘
               │ agent_decisions (PostgreSQL)
               ▼
┌──────────────────────────────────────────────────────────────┐
│              Track B — 赛后过程评分                            │
│  PerStepScorer (三级级联)                                     │
│  Tier 1 deterministic (85%) → Tier 2 light LLM (12%)          │
│  → Tier 3 3-judge panel + Critic (3%)                        │
│  CounterfactualAnalyzer → PublishedReview → Leaderboard       │
└──────────────┬───────────────────────────────────────────────┘
               │ ScoredStep[] → KnowledgeAbstractor
               ▼
┌──────────────────────────────────────────────────────────────┐
│              Track C — 知识自进化                              │
│  AbstractedLesson → strategy_knowledge_docs (candidate)       │
│  → promote.py → active → 4-filter retrieval → Agent Prompt    │
│  L0_fact / L1_rule / L2_statistical / L3_strategic / L4_spec  │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Game Engine — 对局引擎

**文件**: `backend/engine/game.py` (1721 行)

### 阶段状态机

```
NIGHT: START → GUARD → WOLF → WITCH → SEER → RESOLVE
DAY:   START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION
       → DAY_SPEECH → VOTE → RESOLVE
SPECIAL: HUNTER_SHOOT / WHITE_WOLF_KING_BOOM / BADGE_TRANSFER / GAME_END
```

### 并行调度

夜晚 Guard/Seer 并行执行，狼队内部串行；白天投票全玩家并行 (`_batch_ask`)。
所有共享状态写入由 `_shared_lock` (RLock) 保护。

### 幂等守卫

- `_check_win()`: `if self.state.winner is not None: return True`
- `_begin_night()` / `_begin_day()`: `_phase_done()` 检查防止 resume 时重复执行

### 信息隔离

`backend/engine/visibility.py` — 三级视图:
- **self_player**: 完整信息
- **wolf_team**: 狼同伴信息 (仅狼阵营)
- **other**: 仅公开信息

92 项边界检查全部通过 (`verify_visibility_strict.py`)。

---

## 3. CognitiveAgent — 认知 Agent

**目录**: `backend/agents/cognitive/`

### Observe-Think-Act 架构

```
PlayerView → Observation → AgentLoop (max 3 tool-call iterations) → Decision
```

### 三层 Prompt 架构

| Layer | 内容 | 职责 |
|-------|------|------|
| **Layer 1: Persona** | MBTI + 职业 + 说话风格 + PlayerMind | 控制"怎么说" |
| **Layer 2: Role Identity** | 角色身份 + 能力边界 + 胜利条件 | 定义"我是谁" |
| **Layer 3: Strategy + Tools** | 检索到的策略 + 6 个工具函数 | 指导"怎么玩" |

**关键设计**: 三层严格分离，Persona 和 Role 层不包含任何玩法指导，所有策略知识只从 Layer 3 (检索/策略卡) 进入。

### 工具调用 (Tool Calling)

Agent 通过 6 个工具函数主动获取信息:
- `search_strategies(query)` — 检索策略知识库
- `check_rules(question)` — 查询游戏规则
- `review_my_history()` — 查看自己的发言历史
- `review_public_events()` — 查看公开事件
- `analyze_vote_pattern()` — 分析投票模式
- `get_private_info()` — 获取私有信息 (查验结果等)

### 关键模块

| 模块 | 文件 | 功能 |
|------|------|------|
| BeliefTracker | `observe.py` | 维护对其他玩家的身份信念 |
| Memory | `memory.py` | 短期记忆 (近 N 轮) + 长期记忆 |
| WolfTeamView | `wolf_team.py` | 狼队安全协调 (只含合法可见信息) |
| Humanization | `humanization.py` | 人格化发言 (语气词、情绪波动) |
| StrategyRetriever | `retrieval_prod.py` | Agent 工具调用检索 (BM25 + 倒排索引) |

---

## 4. Strategy Retrieval — 策略检索

**文件**: `backend/agents/cognitive/retrieval_prod.py` + `knowledge_confidence.py`

### 检索架构

Agent 通过 `search_strategies` 工具主动检索策略知识，底层使用 BM25 + 关键词倒排索引，经 4-filter 安全管线过滤后返回 top_k 结果。

```
Agent tool call (search_strategies) → BM25 + 倒排索引 → 4-filter 安全管线 → top_k
```

### 4-Filter 安全管线

1. **confidence_allowed**: L0-L3 可检索, L4_speculative 禁止, rejected 禁止
2. **visibility_allowed**: 按角色/阵营过滤 (public/self_private/wolf_team_private/postgame_only)
3. **leaks_current_game_private_info**: 防止当前局私有信息泄露
4. **applicability_matches**: 按 role/phase/rule_variant/player_count 匹配

### 知识分层 (L0-L4)

| Tier | 类型 | 示例 | 可检索 |
|------|------|------|--------|
| L0 | 可验证事实 | "5 号第 2 天投票给了 3 号" | ✅ |
| L1 | 规则推导 | "女巫首夜用药后无法自救" | ✅ |
| L2 | 统计洞察 | "12 人局守卫首夜空守胜率 +3.2% (n=240)" | ✅ |
| L3 | 策略判断 | "被查杀时先跳身份再归票" | ✅ (需 agreement ≥ 0.67) |
| L4 | 推测 | "可能可以尝试..." | ❌ 禁止 |

---

## 5. Track B — 赛后过程评分

**目录**: `backend/eval/`

### 三级评分级联

```
Tier 1: Deterministic (85%)          Tier 2: Light LLM (12%)         Tier 3: Heavy LLM (3%)
┌─────────────────────────┐    ┌──────────────────────┐    ┌──────────────────────────┐
│ Hard-rule scoring        │    │ Single Judge LLM      │    │ 3-Judge Panel + Critic   │
│ • 空发言 → 0 分          │    │ • correctness ∈       │    │ • 高影响力 + 低一致性     │
│ • 投狼 → 0.95 correctness│ →  │   [0.3, 0.7]         │ →  │ • trimmed mean 聚合       │
│ • 毒狼 → 0.95            │    │ • 归一化 /10.0        │    │ • Critic 分歧 > 0.3 介入  │
│ 零成本, 100% 可复现       │    │ 低成本, 高覆盖率       │    │ 高精度, 逐决策评分         │
└─────────────────────────┘    └──────────────────────┘    └──────────────────────────┘
```

### 核心评分维度

| 维度 | 权重 | 考察内容 |
|------|------|----------|
| correctness | 40-55% | 决策是否正确 (投票目标/技能目标) |
| reasoning_quality | 20-35% | 推理链路质量 |
| timeliness | 10% | 时机选择 |
| impact | 15% | 决策影响力 |

### CounterfactualAnalyzer

三类反事实推演:
- **vote**: 如果投了不同目标会怎样
- **skill**: 如果用了不同技能目标会怎样 (effect_type=local_recalculation)
- **speech**: 如果说了不同内容会怎样

### 输出物

- **PublishedReview**: status=approved, HTML + Markdown 报告
- **Leaderboard**: 跨局排名, 最近 100 局采样聚合
- **Evaluation**: 21 条/局的细粒度评分记录

---

## 6. Track C — 知识自进化

**文件**: `backend/eval/knowledge_abstractor.py` + `evolution.py`

### 闭环数据流

```
Game → agent_decisions → PerStepScorer → ScoredStep[]
  → KnowledgeAbstractor → AbstractedLesson[]
  → strategy_knowledge_docs (status=candidate)
  → promote.py → active
  → StrategyRetriever → Agent Prompt → 下一局
```

### 知识生命周期

```
candidate ──promote──→ active ──decay──→ deprecated
                │                    │
                └──usage feedback───┘
                 (3+ uses 全无效 → deprecated)
```

### 质量保障

- **SAVEPOINT 逐条隔离**: 单条 INSERT 失败不回滚整批
- **Dedup 检查**: `source_game_id` 查询防止重复提取
- **TIER_EXPERIMENT_ID 隔离**: 实验期间不同 tier 知识池互不污染
- **promote_candidates**: 跳过已被 usage feedback 降级的文档

---

## 7. 数据库

**PostgreSQL** @ `127.0.0.1:5433/werewolf` | **21 张表**

### 核心表

| 类别 | 表名 | 用途 |
|------|------|------|
| 对局 | `games`, `players`, `game_events`, `game_snapshots` | 对局记录 |
| Agent | `agent_decisions`, `agent_versions` | 决策追踪 |
| 评测 | `evaluations`, `review_reports`, `published_reviews`, `leaderboard_entries` | Track B |
| 知识 | `strategy_knowledge_docs`, `strategy_graph_links`, `role_strategy_cards`, `strategy_patches` | Track C |
| 进化 | `evolution_tournaments`, `evolution_rounds`, `knowledge_usage_feedback`, `strategy_snapshots` | Track C |
| 人设 | `personas`, `persona_role_adapters` | Persona |
| 实验 | `experiments` | 多 Tier 对比 |

### 关键约束

- `knowledge_usage_feedback` 三外键 (game_id, player_id, knowledge_doc_id)
- `agent_decisions.metadata` (JSONB) 含 tool_trace + strategy IDs
- strategy_knowledge_docs 状态流转: candidate → active → deprecated

---

## 8. 信息隔离

**文件**: `backend/engine/visibility.py`

### 三级视图矩阵

| 信息类型 | 自己 | 狼队友 | 其他玩家 |
|----------|------|--------|----------|
| 自己的角色/技能 | ✅ | ❌ | ❌ |
| 狼同伴身份 | — | ✅ | ❌ |
| 查验结果 | ✅ | ❌ | ❌ |
| 夜间行动 (公开) | ✅ | ✅ | ✅ |
| 夜间行动 (私密) | ✅ | ❌ | ❌ |
| 发言/投票 | ✅ | ✅ | ✅ |
| 死亡公告 | ✅ | ✅ | ✅ |

### 验证

92 项边界检查 (`verify_visibility_strict.py`) 全部通过。

---

## 9. 错误处理 & 韧性

### LLM 降级链

```
主模型 (doubao-seed-2.0-pro)
  → 备用模型 (DOUBAO_FALLBACK_*)
  → HeuristicAgent (最终兜底)
```

### 其他保障

- LLM 调用: 指数退避重试 (120s timeout)
- DB 连接: 子进程 try/except + pool_pre_ping
- 批量写入: SAVEPOINT 逐行隔离
- 并发: `_STRATEGY_LOCK` 保护全局可变字典
- 配置: 9 个 env flag 控制 strict/fail-fast 行为

---

## 10. 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 + FastAPI + WebSocket |
| 前端 | Next.js 15 + React 19 + Tailwind CSS |
| 数据库 | PostgreSQL 15 (Docker @ 5433) |
| LLM | 火山方舟 doubao-seed-2.0-pro |
| 检索 | Agent 工具调用检索, BM25 + 倒排索引 (GPU-free) |
| 评测 | scikit-learn + LLM Judge Panel |

---

## 11. 关键文件索引

```
backend/
├── engine/game.py                   # 游戏引擎 (1721 行)
├── engine/visibility.py             # 信息隔离
├── agents/cognitive/agent.py        # CognitiveAgent
├── agents/cognitive/agent_loop.py   # Observe-Think-Act 主循环
├── agents/cognitive/observe.py      # Observation + BeliefTracker
├── agents/cognitive/retrieval_prod.py # Agent 工具调用检索 + 4-filter
├── agents/cognitive/tools.py        # 6 个工具函数
├── agents/cognitive/wolf_team.py    # 狼队协调
├── eval/per_step_scorer.py          # 三级评分级联
├── eval/llm_judge.py                # LLM Judge Panel
├── eval/review.py                   # 复盘系统 (CounterfactualAnalyzer)
├── eval/knowledge_abstractor.py     # 知识提取
├── eval/knowledge_confidence.py     # 4-filter + L0-L4 可信度
├── eval/evolution.py                # 知识生命周期管理
├── eval/post_game.py                # 赛后评分入口
├── db/models.py                     # ORM (21 张表)
└── ops/preflight.py                 # 7 项启动预检
```

---

*由小爪整理 (๑•̀ㅂ•́)و✧*
