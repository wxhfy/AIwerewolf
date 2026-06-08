# AI狼人杀 — 需求规格 V2.0

> **V2.0 变更**：精简至与当前代码实现一致。移除了研究级博弈论形式化内容（二阶推理、游戏树搜索、反事实推理、DD协商协议、信号博弈），移除了未实现的用户系统/断线重连/旁观者等模块。新增真人vs AI混战模式。

---

## 一、游戏规则引擎

### 1.1 角色系统

| 角色 | 阵营 | 能力 | 使用限制 |
|------|------|------|----------|
| 村民 | 好人 | 无特殊能力 | — |
| 狼人 | 狼人 | 夜晚击杀一人 | 不推荐自刀 |
| 预言家 | 好人 | 夜晚查验一人身份（好人/狼人） | 每晚一次 |
| 女巫 | 好人 | 解药+毒药各一瓶，**每夜最多用一瓶** | 首夜可自救 |
| 猎人 | 好人 | 被投/被刀时可开枪带走一人 | 被毒不能开枪 |
| 守卫 | 好人 | 夜晚守护一人不被狼刀 | 不可连续两晚守同一人 |

**扩展角色**（已实现）：白痴、白狼王、狼美人等。详见 `configs/rule_variant_standard.yaml`。

### 1.2 伤害交互矩阵

| 伤害来源 | 守卫守护 | 女巫解药 | 结果 |
|----------|----------|----------|------|
| 狼刀 | ✓ | — | 存活 |
| 狼刀 | — | ✓ | 存活 |
| 狼刀 | ✓ | ✓ | **死亡（同守同救/奶穿）** |
| 女巫毒 | ✓/— | ✓/— | 死亡（毒药不可防护） |
| 猎人子弹 | ✓/— | ✓/— | 死亡（子弹不可防护） |

### 1.3 游戏流程

```
WAITING → ROLE_ASSIGN → [NIGHT → DAY → VOTE]… → GAME_END

夜晚（守卫+狼人+预言家并行 → 女巫 → 结算）：
  NIGHT_START → NIGHT_GUARD_ACTION → NIGHT_WITCH_ACTION → NIGHT_RESOLVE

白天（仅第一天有警徽竞选）：
  DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION
  → DAY_SPEECH（并行发言）→ SHERIFF_CLOSING → DAY_VOTE → DAY_RESOLVE

特殊阶段（事件触发）：PK_SPEECH/PK_VOTE（平票）、LAST_WORDS（遗言）、
  BADGE_TRANSFER（警徽移交）、HUNTER_SHOOT（猎人开枪）、WHITE_WOLF_KING_BOOM
```

### 1.4 胜负判定

| 条件 | 结果 |
|------|------|
| 存活狼人数 ≥ 存活好人数 | 狼人获胜 |
| 所有狼人死亡 | 好人获胜 |
| 20 个完整昼夜循环达到 | 平局 |

### 1.5 角色分配

- 7-12 人局固定模板，详见 `configs/rule_variant_standard.yaml`
- 支持自定义角色配置

### 1.6 发言机制

- 并行发言：所有存活玩家同时生成发言（基于各自 PlayerView）
- 不依赖同轮其他玩家发言，确保信息隔离

### 1.7 投票平票处理

- 第一次平票 → PK 发言 → PK 投票
- 再次平票 → 无人出局，进入夜晚

### 1.8 遗言规则

- 夜晚死亡玩家有遗言机会
- 被投票出局的玩家无遗言

---

## 二、Agent 系统

### 2.1 认知架构

```
CognitiveAgent = Observe → Think → Act

输入：PlayerView（信息隔离后的局部视图）
输出：Decision（talk / vote / attack / divine / guard / witch_act）

核心组件：
  - Memory：多轮记忆、策略状态、立场追踪
  - BeliefTracker：声明/矛盾/投票模式追踪
  - SocialModel：信任/欺骗信号检测
  - Planner：跨阶段战略意图管理
  - AgentLoop：6 工具调用式推理循环 + 结构化决策输出
```

### 2.2 工具系统 (AgentLoop)

| 工具 | 作用 |
|------|------|
| `search_strategies` | 策略知识检索（BM25 + 倒排索引） |
| `recall_memory` | 历史记忆查询 |
| `check_rules` | 游戏规则查询 |
| `get_social_info` | 社交信任信息 |
| `analyze_votes` | 投票模式分析 |
| `set_strategic_intent` | 跨阶段意图记录 |
| *(强制输出)* | 最终决策结构化输出（非工具调用） |

### 2.3 三层 Prompt 架构

```
Layer 1  MBTI 人格  → 决定"怎么思考"（认知风格、说话方式）
Layer 2  Role 身份  → 定义"我是谁"（角色技能、胜利条件）
Layer 3  策略知识  → 教"怎么赢"（BM25 检索历史经验）
```

### 2.4 策略检索 (StrategyRetriever)

- BM25 + 倒排索引，无需 GPU
- RetrievalPolicy：支持角色/MBTI/全局/混合策略
- 4-filter 安全管线：confidence / visibility / privacy / applicability
- candidate/active 知识隔离

### 2.5 LLM 降级策略

当 LLM 调用失败时，strict mode 直接报错，非 strict mode 使用启发式降级：

| 角色 | 降级行为 |
|------|---------|
| 狼人 | 随机选择非狼目标击杀 |
| 预言家 | 随机查验 |
| 女巫 | 保守策略（不盲目用药） |
| 守卫 | 优先自守 |
| 村民 | 弃权投票 + 被动发言 |

由环境变量 `AIWEREWOLF_STRICT_MODE` 控制（默认开启）。

### 2.6 真人 vs AI 混战

- `HumanAgent`：暂停游戏等待真人输入
- 引擎支持 `pending_input` / `submit_human_action` 机制
- 前端 `/room/[id]/play?mode=human` 提供操作面板

---

## 三、评测系统 (Track B & C)

### 3.1 Track B：赛后评分

- **PerStepScorer**：逐步评价每个决策（talk/vote/skill）
- 三级级联：确定性规则 → light LLM → heavy LLM judge panel
- 输出：DecisionScore（correctness/reasoning/timeliness/impact）
- ScoredStep：标记 highlight（高分）和 mistake（低分）
- 生成 PublishedReview（Markdown + HTML 复盘报告）

### 3.2 Track C：知识进化

- **KnowledgeAbstractor**：从 highlight/mistake 提取经验
- 写入 `strategy_knowledge_docs`（status=candidate）
- promote.py 管理 candidate → active → deprecated 生命周期
- 知识回流到下一局 Agent 的策略检索中

### 3.3 PostgreSQL 证据链

核心表（23 张）：games、players、game_events、game_snapshots、agent_decisions、evaluations、published_reviews、strategy_knowledge_docs、knowledge_usage_feedback、leaderboard_entries 等。

每条决策可追溯到：GameEvent → AgentDecision → DecisionScore → ScoredStep → AbstractedLesson → StrategyKnowledgeDoc。

---

## 四、通信与前端

### 4.1 WebSocket 实时推送

- `/ws/games`：游戏状态快照实时流
- 支持 public/private 视角切换
- snapshot buffer 支持重连恢复

### 4.2 REST API

- 房间 CRUD（`/api/rooms`）
- 对局管理（`/api/games`）
- 复盘报告（`/api/games/{id}/reviews`）
- 回放数据（`/api/replay/{game_id}`）

### 4.3 事件类型

| 事件 | 说明 |
|------|------|
| GAME_START / GAME_END | 游戏开始/结束 |
| PHASE_CHANGED | 阶段切换 |
| PRIVATE_INFO | 私有信息（查验/用药结果） |
| CHAT_MESSAGE / NIGHT_ACTION | 发言/夜晚行动 |
| VOTE_CAST / PLAYER_DIED | 投票/死亡 |
| HUNTER_SHOT / WHITE_WOLF_KING_BOOM | 特殊技能 |

事件通过 `visibility`（public/private）+ `visible_to[]` 控制可见范围。

### 4.4 前端页面

| 路由 | 说明 |
|------|------|
| `/` | 大厅（创建/进入房间） |
| `/room/[id]/play` | 对局观战 + 真人操作面板 |
| `/evolution` | 策略进化面板 |
| `/eval/dashboard` | 评测仪表盘 |
| `/games/[id]/report` | 单局复盘报告 |
| `/personas` | MBTI 人格配置 |

---

## 五、配置与部署

### 5.1 技术栈

| 层 | 技术 |
|------|------|
| 后端 | Python 3.8+ · FastAPI · WebSocket |
| 前端 | Next.js 14 · React 18 · Tailwind CSS |
| 数据库 | PostgreSQL 16（Docker） |
| LLM | Anthropic/OpenAI 兼容端点（DeepSeek / 豆包） |

### 5.2 启动方式

```bash
cp .env.example .env   # 配置 LLM 密钥
make dev               # 启动后端 http://localhost:8000
cd frontend && npm run dev  # 启动前端 http://localhost:3001
python scripts/llm_game_smoke.py --seed 1  # 跑一局
```

### 5.3 阶段超时（仅混战模式生效）

| 阶段 | 默认时长 |
|------|----------|
| 守卫选择 | 20s |
| 狼人讨论+击杀 | 60s |
| 预言家查验 | 20s |
| 女巫行动 | 25s |
| 猎人开枪 | 20s |
| 发言（每人） | 90s |
| 投票 | 30s |

---

*V2.0 — 精简至与代码实现一致。V1.3 中的形式化博弈论内容（似然校准、二阶信念、游戏树、反事实推理、DD协商协议、信号博弈）属于研究规划方向，未纳入当前工程实现。*
