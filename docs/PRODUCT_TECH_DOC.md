# AI 狼人杀 — 产品技术文档

> **版本**：V2.1 · **更新日期**：2026-06-08 · **许可**：MIT © 2026 wxhfy
>
> **面向读者**：技术团队成员、项目评审老师、潜在合作者

---

## 一、产品概述

### 1.1 产品定位与目标

**AI Werewolf 是一个多智能体狼人杀研究平台**。它将三件事打通成一条闭环：让一桌 AI **对战（Play）**、对每个玩家的每一步**复盘（Evaluate）**、再把复盘出的经验回流给下一代 Agent 实现**进化（Evolve）**。

每个 AI 玩家拥有独立的 MBTI 人格（16 种）、角色技能（狼人/预言家/女巫/猎人/守卫/村民/白痴/白狼王等）和认知架构，在严格信息隔离下进行推理、对话和决策。系统同时支持真人 vs AI 混战模式。

### 1.2 架构亮点摘要

完整架构说明见 [`ARCHITECTURE_DESIGN_GUIDE.md`](ARCHITECTURE_DESIGN_GUIDE.md)。

| 架构优势 | 技术抓手 | 可核验证据 |
|---|---|---|
| 规则稳定 | `WerewolfGame` 主控状态，Agent 只提交行动意图 | `backend/engine/` |
| 信息可信 | `GameState` / `PlayerView` / public snapshot 三视图分离 | `backend/engine/visibility.py` |
| 角色化 Agent | 三层 Prompt、角色策略、工具调用式决策、决策 trace | `backend/agents/cognitive/`, `/games/[id]/report` |
| 可解释进化 | 赛后分析、反事实推演、结构化报告、Leaderboard、B->C 知识回流 | `backend/eval/`, `/eval/dashboard`, `scripts/track_bc_leaderboard_experiment.py` |
| 产品闭环 | API/WebSocket、PostgreSQL、Next.js 前端、Human 模式、CI 和 smoke | `backend/`, `frontend/`, `tests/`, `scripts/e2e_smoke.py` |

### 1.3 与常见方案的不同

| 常见方案 | 主要局限 | 本项目设计 |
|---|---|---|
| 只用 Prompt 模拟一局 | 规则、状态和推理混在上下文里，容易泄漏隐藏身份 | 引擎主控规则，Agent 只拿裁剪后的 `PlayerView` |
| 普通 AIWolf 回调 Agent | 生命周期清晰，但内部思考和赛后分析多为黑箱 | 增加 Memory、SocialModel、Planner、AgentLoop 和决策审计 |
| 真人狼人杀房间系统 | 实时交互成熟，但缺少 Agent 私有上下文和策略回流 | 房间层复用同一套引擎，AI/Human/观战/复盘共用状态流 |
| 只统计胜负 | 难以定位哪一步造成局势变化 | 复盘层逐步分析发言、投票和技能行为，并给出证据链 |
| 硬编码角色逻辑 | 新角色会牵动大量条件分支 | RoleRegistry、Phase、Action、Skill 分层降低扩展成本 |

### 1.4 核心特性

| 特性 | 说明 |
|------|------|
| **完整游戏引擎** | 15+ 细分阶段，回合流转、行动校验、技能结算、胜负判定 |
| **严格信息隔离** | 三视图体系（观众/上帝/玩家），Agent 永远获取不到越权信息 |
| **三层认知架构** | MBTI 人格 + Role 身份 + 策略知识，决定 Agent 如何思考与行动 |
| **工具调用式决策** | Agent 通过 7 种工具主动检索信息，而非被动接收全部上下文 |
| **分层复盘分析** | 确定性规则、轻量 LLM 和高影响决策复核组合，兼顾成本与质量 |
| **知识自进化** | 经验提炼 → 入库（候选池）→ 质量筛选 → 晋升（活跃池）→ 检索注入 |
| **证据全链追溯** | 每条决策从引擎事件 → Agent 决策 → 复盘分析 → 知识抽取，全链路可追溯 |
| **真人 vs AI 混战** | HumanAgent 暂停对局等待输入，支持人类玩家加入博弈 |

### 1.5 技术架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                      前端 (Next.js 14)                            │
│    大厅 │ 对局观战 │ 人类操作面板 │ 复盘仪表盘 │ 复盘报告 │ 人格管理  │
├──────────────────────────────────────────────────────────────────┤
│                    WebSocket + REST API                           │
├──────────────────────────────────────────────────────────────────┤
│                      后端 (FastAPI)                               │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌────────────┐ │
│  │ 游戏引擎  │  │ 认知Agent     │  │ 复盘系统    │  │ 知识进化    │ │
│  │ GameState │  │ Observe→Think│  │ Tier 1/2/3  │  │ Abstract→   │ │
│  │ PhaseM.  │  │ →Act→Reflect │  │ LLM Review  │  │ Promote→    │ │
│  │ Resolver │  │ AgentLoop    │  │ Counterfact │  │ Retrieve    │ │
│  └──────────┘  └──────────────┘  └────────────┘  └────────────┘ │
├──────────────────────────────────────────────────────────────────┤
│                   PostgreSQL 16 (20 张核心 ORM 表)                 │
│   games │ players │ events │ decisions │ evaluations │ knowledge │
├──────────────────────────────────────────────────────────────────┤
│               LLM 接入层 (统一 create_client provider)              │
│      doubao · dsv4flash · ark · deepseek · anthropic · weapi · mimo │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、系统架构

### 2.1 整体架构

系统采用**前后端分离 + 实时推送**架构：

- **后端**：Python 3.8+ / FastAPI / WebSocket，负责游戏引擎、Agent 推理、复盘分析和知识管理
- **前端**：Next.js 14 / React 18 / Tailwind CSS，负责观战 UI 和人类交互
- **数据库**：PostgreSQL 16（Docker 部署），当前代码映射 20 张核心 ORM 表；历史实验数据库可包含额外实验快照表
- **LLM 层**：统一客户端抽象，支持 Anthropic Messages API 与 OpenAI Chat Completions 兼容格式

### 2.2 两层正交的设计主线

系统可从两个互相垂直的角度理解：

**主线 A — 单个玩家"脑子"的三层认知架构**（纵向）：

```
Layer 1  MBTI 人格    →  决定"怎么思考"（认知风格、说话方式、冒险/保守倾向）
Layer 2  Role 身份    →  定义"我是谁"（角色技能、胜利条件、反模式清单）
Layer 3  策略知识     →  教"怎么赢"（运行时动态检索历史经验，注入当前决策）
```

**主线 B — 系统的三 Track 研究闭环**（横向）：

```
Play（对战）→ Evaluate（复盘）→ Evolve（进化）→ Play（下一局，更强）
```

两条主线的交叉点，正是本项目的核心研究问题：**给 Agent 叠上"人格 + 角色 + 可进化的策略知识"这三层，它真的会打得更好吗？**

### 2.3 技术栈

| 层 | 技术 | 说明 |
|------|------|------|
| 后端框架 | Python 3.8+ · FastAPI · WebSocket | 异步高性能 |
| 前端框架 | Next.js 14 · React 18 · Tailwind CSS | 现代响应式 UI |
| 数据库 | PostgreSQL 16（Docker，端口 5433） | 结构化持久化，FK 约束完整 |
| LLM 接入 | `backend.llm.create_client()` | doubao / dsv4flash / ark / deepseek / anthropic / weapi / mimo |
| 测试模型 | `LLM_PROVIDER=fake` | 仅 `_TEST_ALLOW_FAKE_LLM=true` 的测试环境可用 |
| 检索 | BM25 + 倒排索引 | 轻量级，无需 GPU，500ms 内响应 |
| 复盘 | LLM 复核 · 反事实推演 | 三级分析级联，成本可控 |
| 配置 | YAML | 规则配置、角色模板、策略库 |
| CI/CD | GitHub Actions | lint（ruff）+ 测试（pytest）|

---

## 三、核心模块

### 3.1 游戏引擎（WerewolfGame）

**定位**：整个系统的规则底座，负责回合流转、行动校验、技能结算和胜负判定。

**关键设计决策**：

| 决策 | 说明 | 理由 |
|------|------|------|
| 阶段状态机 | 15+ 阶段独立建模，根据行动结果决定转换 | 避免长串 if/else，扩展新角色改动面小 |
| 夜晚同时发生 | 守卫/狼人/预言家并行行动，结算时视为同时 | 符合真实狼人杀裁判规则，防止"先执行先生效"的悖论 |
| 信息三视图 | 同一 GameState 提供观众视图/上帝视图/玩家视图 | 把过滤逻辑收敛到一处实现，防止多处调用中泄漏 |
| 引擎主控 | Agent 只输出行动，不直接修改状态 | 保证状态一致性，便于审计和复盘 |
| 幂等守卫 | `_check_win()` 和阶段转换均带防重检查 | 避免重连或异常重试造成重复结算 |

**夜晚·标准流程**：

```
NIGHT_START → NIGHT_GUARD_ACTION（守卫） → NIGHT_WITCH_ACTION（女巫）→ NIGHT_RESOLVE（结算）
                 ↕ 与狼人/预言家并行              ↑
              NIGHT_WOLF_ACTION（狼人）          获知死讯后决定用药
              NIGHT_SEER_ACTION（预言家）
```

**白天·标准流程**：

```
DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION    # 警徽竞选（仅第一天）
         → DAY_SPEECH（并行发言）→ SHERIFF_CLOSING → DAY_VOTE → DAY_RESOLVE
```

**伤害交互矩阵**：

| 伤害来源 | 守卫守护 | 女巫解药 | 结果 |
|----------|:--------:|:--------:|------|
| 狼刀 | ✓ | — | 存活 |
| 狼刀 | — | ✓ | 存活 |
| 狼刀 | ✓ | ✓ | **死亡（奶穿）** |
| 女巫毒 | ✓/— | ✓/— | 死亡（不可防护） |
| 猎人子弹 | ✓/— | ✓/— | 死亡（不可防护） |

### 3.2 信息隔离层（PlayerView / Visibility）

**定位**：连接真实 GameState 与 Agent 输入的信息隔离层，是研究可信度的"命门"。

**内部流程**：

1. 读取真实 GameState
2. 判断当前玩家身份、阵营和存活状态
3. 裁剪其他玩家的公开信息（屏蔽不合法身份）
4. 过滤 public_events 和 private_events
5. 生成合法目标列表 `legal_targets`（减少 Agent 非法输出）
6. 对狼人补充合法狼队视图（队友身份 + 协同信息）

**关键指标**：92/92 边界检查全部通过，严格模式已验证"Agent 永远获取不到越权信息"。

### 3.3 认知 Agent（CognitiveAgent）

**定位**：每个 AI 玩家的"大脑"，负责把玩家视图、角色目标、历史记忆和策略知识转化为可执行决策。

**认知循环**：

```
Observe（观察）→ Think（思考/规划）→ Act（行动）→ Reflect（反思）
```

**核心组件**：

| 组件 | 功能 |
|------|------|
| **Memory** | 多轮记忆、策略状态、立场追踪，解决"金鱼记忆"问题 |
| **BeliefTracker** | 概率模型追踪"我认为某人是某角色"，随观察做贝叶斯更新 |
| **SocialModel** | 信任/欺骗信号检测，管理与其他玩家的关系 |
| **Planner** | 跨阶段战略意图管理，保证决策的连贯性 |
| **Persona (MBTI)** | 6 维连续人格（冒险倾向、领导欲、欺骗偏好、情绪表达、逻辑深度、合作倾向）|

### 3.4 工具调用循环（AgentLoop）

**定位**：让 Agent 主动按需检索信息，而非被动接收全部上下文。

**设计要点**：每次决策最多迭代 3 轮，在"思考充分"和"成本/延迟可控"之间取平衡。

| 工具 | 作用 | 阶段 |
|------|------|------|
| `search_strategies` | 从知识库检索策略经验 | 全部 |
| `recall_memory` | 查询历史记忆 | 全部 |
| `check_rules` | 查询游戏规则 | 全部 |
| `get_social_info` | 获取对其他玩家的社交信任信息 | 白天 |
| `analyze_votes` | 分析历史投票模式 | 投票阶段 |
| `set_strategic_intent` | 记录跨阶段战术意图 | 全部 |
| `submit_decision` | 提交最终决策（talk/vote/skill）| 全部 |

**验收指标**：严格模式下 26/27 条决策带完整工具追踪链条（96.3%）。

### 3.5 策略检索（StrategyRetriever）

**定位**：BM25 + 倒排索引的轻量级策略知识检索引擎。

**4-filter 安全管线**：

```
confidence_allowed ──→ visibility_allowed ──→ privacy_safe ──→ applicability_matches
  (L0-L3 可用)          (公开/自己/狼队)        (不泄漏当前局信息)   (角色/阶段/规则匹配)
```

**关键数据**：当前活跃知识池 401 条，候选池 3856 条，检索延迟 < 500ms。

### 3.6 复盘分析系统（Track B）

**定位**：分析每个玩家的关键决策，生成结构化复盘报告。

**三级分析级联**：

| 档位 | 占比 | 处理方式 | 成本 |
|------|:---:|------|------|
| Tier 1 确定性规则 | ~85% | 纯规则判定（投票对错、发言立场、技能匹配）| 零 LLM 成本 |
| Tier 2 轻量 LLM | ~12% | 单 LLM 对模糊地带复核 | 低 |
| Tier 3 多裁判复核 | ~3% | 多路 LLM + Critic 复核，截尾均值 | 高 |

**分析维度**：correctness（正确性）、reasoning_quality（推理质量）、timeliness（时机选择）、impact（局势影响）

**关键指标**：历史离线实验中，赢家与输家的复盘指标区分达到大效应量（Cohen's d 最高 2.76），六角色全部 p < 0.0001；100% 决策覆盖率。

### 3.7 知识进化（Track C）

**定位**：把 Track B 的复盘结论沉淀为可复用的策略知识，回流到下一代 Agent。

**闭环流程**：

```
Track B 复盘 ──→ KnowledgeAbstractor 提取经验 ──→ 写入 candidate 候选池
                                                        │
                                               promote.py 质量筛选
                                                        │
                                                        ▼
                                           active 活跃池 ──→ StrategyRetriever
                                                                     │
                                                        ┌────────────┘
                                                        ▼
                                              下一局 Agent 检索使用
```

**知识生命周期**：`candidate → active → deprecated`；同时带有 L0–L4 置信分级。

**防污染机制**：
1. 新知识默认入 candidate 池，不直接污染 active
2. 4-filter 安全管线严格防止当前局私密信息泄漏
3. `TIER_EXPERIMENT_ID` 隔离不同实验的知识池

**关键指标**：单局提炼约 99 条知识；活跃知识池零污染（935→935, delta=0）；知识回链原始事件 100%。

---

## 四、数据流与证据链

### 4.1 端到端数据流

```
Game Engine (_ask → _record_decision)
     │
     ▼
agent_decisions 表（25 万+ 条记录，含 tool_trace + strategy IDs）
     │
     ▼
PerStepScorer.score_all() — Tier 1 → Tier 2 → Tier 3
     │
     ▼
DecisionScore[] → ScoredStep[] → PlayerReviewReport[]
     │
     ▼
KnowledgeAbstractor.abstract_from_game() → AbstractedLesson[]
     │
     ▼
strategy_knowledge_docs 表（status=candidate）
     │  promote.py
     ▼
active 知识池 → StrategyRetriever → AgentLoop → 下一局决策
```

### 4.2 单条决策追溯链路

```
GameEvent（引擎事件）
  └─ event_id: "evt_abc123", type: "VOTE_CAST", payload: {voter_id, target_id}

AgentDecision（Agent 决策记录）
  └─ observation: PlayerView, _tool_trace: [...], decision: {vote_target: "player_3"}

DecisionScore（Track B 决策质量指标）
  └─ correctness: 0.85, scoring_tier: "deterministic"

ScoredStep（结构化步骤）
  └─ is_highlight: true, retrieved_strategies: [{doc_id, title}]

AbstractedLesson（Track C 经验提炼）
  └─ lesson_abstract: "归票策略有效", source_event_ids: ["evt_abc123"]

StrategyKnowledgeDoc（持久化知识）
  └─ confidence_tier: "L3_strategic", status: "candidate"
```

### 4.3 贯通率指标

| 指标 | 当前值 | 说明 |
|------|--------|------|
| 决策工具调用追踪覆盖 | 96.3%（26/27） | 每条决策带完整工具调用链 |
| ScoredStep 覆盖率 | 100%（27/27） | 全部决策均进入复盘步骤 |
| source_event_ids 贯通 | 100% | 知识文档全部回链到原始事件 |
| source_game_ids 贯通 | 100% | 知识文档全部回链到来源对局 |
| Active 池零污染 | delta=0 | Strict 模式验收通过 |

---

## 五、通信与前端

### 5.1 WebSocket 实时推送

- **端点**：`/ws/games`
- **机制**：后端"观察者 + 快照队列"模式，对局同步推进，每约 80ms 推送快照
- **视角**：支持 public（公开）和 private（主持/玩家）视角切换
- **重连**：snapshot buffer 缓冲历史快照，重连客户端先追上历史再跟实时帧

### 5.2 事件类型

| 事件 | 说明 | 可见范围 |
|------|------|----------|
| `GAME_START` / `GAME_END` | 游戏开始/结束 | public |
| `PHASE_CHANGED` | 阶段切换 | public |
| `PRIVATE_INFO` | 私有信息（查验/用药结果） | private, visible_to[] |
| `CHAT_MESSAGE` | 玩家发言 | public |
| `NIGHT_ACTION` | 夜晚行动（仅公开部分） | public |
| `VOTE_CAST` | 投票动作 | public |
| `PLAYER_DIED` | 玩家死亡公告 | public |
| `HUNTER_SHOT` / `WHITE_WOLF_KING_BOOM` | 特殊技能触发 | public |

### 5.3 REST API 概览

| 路由 | 方法 | 说明 |
|------|:---:|------|
| `/api/rooms` | GET/POST | 房间列表 / 创建房间 |
| `/api/rooms/{id}` | GET/PUT/DELETE | 房间详情 / 更新配置 / 删除 |
| `/api/games` | GET/POST | 对局列表 / 创建对局 |
| `/api/games/{id}` | GET | 对局详情（含快照和事件） |
| `/api/games/{id}/reviews` | GET | 对局复盘报告 |
| `/api/replay/{game_id}` | GET | 对局回放数据 |
| `/api/rooms/{id}/action` | POST | 人类玩家提交操作（混战模式） |
| `/api/evolution/status` | GET | Track C 知识进化状态 |
| `/api/eval/dashboard` | GET | 复盘仪表盘数据 |

### 5.4 前端页面路由

| 路由 | 说明 | 对应 Track |
|------|------|------------|
| `/` | 大厅（创建/进入房间） | Play |
| `/room/[id]/play` | 对局观战 + 真人操作面板 | Play |
| `/room/[id]/human` | 人类玩家专用操作界面 | Play |
| `/games/[id]/report` | 单局完整复盘报告 | Evaluate |
| `/eval/dashboard` | 复盘仪表盘（统计与对比） | Evaluate |
| `/personas` | MBTI 人格管理 | 配置 |

---

## 六、部署与配置

### 6.1 环境要求

| 组件 | 要求 |
|------|------|
| Python | ≥ 3.8 |
| Node.js | ≥ 18（前端） |
| PostgreSQL | 16（Docker 或本地安装） |
| Docker | 可选（用于 PostgreSQL） |
| LLM API Key | 配置所选 provider 对应的 API Key（如 DOUBAO_API_KEY / DEEPSEEK_API_KEY） |

### 6.2 快速启动

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 配置 LLM 密钥
cp .env.example .env
# 编辑 .env，设置 LLM_PROVIDER 和对应 API Key
#   LLM_PROVIDER='doubao'
#   DOUBAO_API_KEY=<your-api-key>

# 3. 启动 PostgreSQL（Docker，端口 5433）
docker run -d --name werewolf-pg \
  -e POSTGRES_USER=werewolf \
  -e POSTGRES_PASSWORD=werewolf_dev_password \
  -e POSTGRES_DB=werewolf \
  -p 5433:5432 postgres:16-alpine

# 4. 启动后端（端口 8000）
make dev
# Swagger UI → http://localhost:8000/docs

# 5. 启动前端（另开终端，端口 3001）
cd frontend && npm install && npm run dev
# → http://localhost:3001

# 6. 验证：跑一局完整对局
python scripts/llm_game_smoke.py --seed 1 --max-seed 1
```

### 6.3 LLM 配置

| 变量 | 说明 | 示例 |
|------|------|------|
| `LLM_PROVIDER` | 提供商选择 | `doubao` / `dsv4flash` / `ark` / `deepseek` / `anthropic` / `weapi` / `mimo` / `fake` |
| `DOUBAO_API_KEY` | 豆包/方舟 API 密钥 | `<your-key>` |
| `DOUBAO_BASE_URL` | 豆包/方舟 API 端点 | `https://ark.cn-beijing.volces.com/api/v3` |
| `DOUBAO_MODEL` | 模型名称 | `Doubao-Seed-2.0-pro` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `<your-key>` |
| `DEEPSEEK_MODEL` | DeepSeek 模型名 | `deepseek-v4-flash` |
| `AIWEREWOLF_STRICT_MODE` | 严格模式 | `true`（正式实验默认） |
| `ALLOW_FALLBACK` | 是否允许 heuristic fallback | `false`（正式实验默认） |

正式对局 AI 席位为 LLM-only：`agent_type=heuristic` 会被拒绝；strict 模式下 LLM 超时、解析失败或非法目标不应静默替换为启发式动作。`LLM_PROVIDER=fake` 仅用于 `_TEST_ALLOW_FAKE_LLM=true` 的测试环境。

### 6.4 数据库配置

- **数据库名**：`werewolf`
- **用户/密码**：`werewolf` / `werewolf_dev_password`
- **端口**：`5433`（避免与本地 PostgreSQL 冲突）
- **初始化**：`backend/ops/preflight.py` + 7 项预检（imports、db_connection、db_tables、db_write、llm_client、active_strategies、pool_config）
- **幂等守卫**：`init_db()` 通过 `_db_initialized` 标记防止重复建表

### 6.5 阶段超时配置（混战模式）

| 阶段 | 默认时长 |
|------|:------:|
| 守卫选择 | 20s |
| 狼人讨论 + 击杀 | 60s |
| 预言家查验 | 20s |
| 女巫行动 | 25s |
| 猎人开枪 | 20s |
| 自由发言（每人） | 90s |
| 投票 | 30s |

---

## 七、测试与验证

### 7.1 测试策略

| 层级 | 工具 | 覆盖范围 |
|------|------|----------|
| 单元测试 | pytest（39 个 test 文件 / 约 397 个测试函数，2026-06-08 审计） | 引擎逻辑、信息隔离、数据模型、检索算法 |
| 集成测试 | `scripts/run_backend_full_strict.py` | 全链路端到端验证 |
| 离线测试 | `_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake pytest tests/ -q` | 无 API 依赖的确定性测试 |
| 冒烟测试 | `scripts/llm_game_smoke.py --seed 1 --max-seed 3` | 真实 LLM 对局完整性 |
| 批量实验 | `scripts/run_experiment.py --games 12` | 多层级消融实验 |
| CI | GitHub Actions（lint + test） | 每次 push 自动执行 |

### 7.2 验收标准矩阵

| 模块 | 状态 | 关键指标 |
|------|:---:|------|
| 数据库 | ✅ | 当前代码 20 张核心 ORM 表，历史实验快照可含额外表；FK 约束完整 |
| LLM | ✅ | LLM provider 可用；正式对局 LLM-only / strict no-fallback |
| 游戏引擎 | ✅ | 全流程跑通，无跳过/死循环 |
| Agent 决策 | ✅ | 26/27 带完整工具追踪（96.3%） |
| 信息隔离 | ✅ | 92/92 边界检查通过 |
| 策略检索 | ✅ | 检索 < 500ms，4-filter 正确过滤 |
| Track B 复盘分析 | ✅ | 100% 决策覆盖率，三级分析级联正确 |
| Track B 复盘 | ✅ | PublishedReview approved |
| Track C 知识 | ✅ | 99 lessons/局，candidate 写入正确，active 零污染 |
| 错误处理 | ✅ | strict/no-fallback 样本标记 + SAVEPOINT + 幂等守卫 |
| 配置有效性 | ✅ | YAML 语法正确，角色与注册表一致 |
| 并发 | ✅ | 4 局同时运行不冲突，独立 game_id + DB 连接 |
| 预检 | ✅ | 7/7 项预检通过 |

### 7.3 CI/CD

```bash
# Lint 检查
ruff check backend/ scripts/ tests/ configs/
ruff format --check backend/ scripts/ tests/ configs/

# 测试执行
pytest tests/ -q
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake pytest tests/ -q  # 离线模式
```

---

## 八、项目现状与路线图

### 8.1 当前进展

**已完成（V2.0）**：

- ✅ 完整游戏引擎（15+ 阶段、信息隔离、多角色、真人混战）
- ✅ 认知 Agent（Observe→Think→Act + 工具调用 + 信念/人格/记忆）
- ✅ 32 个命名角色（16 型 MBTI），狼队协同
- ✅ Track B 复盘系统（三级分析级联 + LLM 复核 + 反事实复盘 + PublishedReview）
- ✅ Track C 知识进化（提炼 → 入库 → 晋级 → 检索注入 → 闭环验证）
- ✅ 全栈观战 UI 与断线重连
- ✅ PostgreSQL 证据链（当前 20 张核心 ORM 表；历史快照含 25 万+ 条 agent_decisions）
- ✅ Strict Mode 全链路验收（edbde010 局：7 人 / 村民胜 / 1553s / PASS）

**当前数据快照（2026-06-07）**：

| 指标 | 值 |
|------|-----|
| 严格验收局 | edbde010：7 人 / 村民胜 / 1553s / strict PASS |
| 批量稳定性 | 20/20 局完成（seeds 300–319） |
| 信息隔离 | 92/92 边界检查通过 |
| 知识闭环 | 99 lessons/局，active 池零污染 |
| 工程规模 | 后端约 5 万行，39 个 pytest 文件 / 约 397 个测试函数，CI 完备 |

### 8.2 待办事项（规划中）

| 优先级 | 事项 | 说明 |
|:------:|------|------|
| P0 | Track B/C 在线 A/B 验证 | 扩样本到 50+ 局/tier，对核心命题下定论 |
| P0 | 法官一致性人工抽样 | 验证 Scoring 分数与人工判断对齐度 |
| P1 | 自进化外循环 | 多轮进化迭代，胜率趋势验证 |
| P1 | Paired Seed 对照实验 | 量化分层认知 / 知识回流的净效果 |
| P1 | 角色级细分指标 | 按角色统计胜率 + 过程分 |
| P2 | 知识图谱复盘层 | 基于策略文档构建图谱关系 |
| P2 | Self-play 策略迭代 | 让 Agent 通过自对弈提升 |
| P2 | 前端 Playwright 视觉验收 | 补充自动化视觉测试 |

---

## 附录 A：项目结构速查

```
AIwerewolf/
├── backend/
│   ├── engine/                # 游戏引擎（WerewolfGame, PlayerView, 阶段流转）
│   ├── agents/cognitive/      # CognitiveAgent（Observe→Think→Act）
│   ├── eval/                  # 复盘系统（LLM 复核, 报告, 知识提取）
│   ├── llm/                   # LLM 客户端（create_client provider）
│   ├── db/                    # ORM + 持久化（20 张核心 ORM 表）
│   ├── protocols/             # WebSocket / Room 协议
│   └── ops/                   # 运维工具（preflight, health check）
├── frontend/                  # Next.js 观战 UI
│   └── app/
│       ├── page.tsx            # 大厅
│       ├── room/[id]/play/     # 对局观战 + 混战操作
│       └── eval/dashboard/     # 复盘仪表盘
├── scripts/                   # 实验 / 验证 / 冒烟脚本
├── tests/                     # 39 个 test 文件 / 约 397 个测试函数（pytest）
├── configs/                   # YAML 规则配置 + 策略库
├── docs/                      # 技术文档 + 实验报告
└── data/                      # 实验数据 + 知识库
```

## 附录 B：关键参考文献

| 优先级 | 项目 | 核心借鉴 |
|:------:|------|----------|
| #1 | wolfcha | Phase 设计、Persona/MBTI 系统、前端产品形态 |
| #2 | WereWolfPlus | 分层 Prompt 模板、多模型对比、YAML 配置化 |
| #3 | AIWolfPy / AIWolfSharp | Agent 生命周期接口规范 |
| #4 | xiong35/werewolf | 实时通信架构、房间系统、信息隔离 |
| #5 | werewolf-brain | 60+ 角色库、夜晚序列、权重平衡 |
| #6 | open_mafia_engine | 事件驱动架构 |
| #7 | OpenWerewolf | 房间/大厅设计 |

> **设计原则**：理解设计、自己重写、不复制代码、不引入 GPL。

---

*本文与 `prd.md`、`PROJECT_MODULE_DESIGN.md`、`DATA_FLOW.md`、`PRODUCT_INTRO.md` 互补而非重复。当前实现以仓库代码和 skills/ 契约文档为准；历史实验快照会在文中显式标注。*
