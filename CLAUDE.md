# CLAUDE.md — AI Werewolf 项目

> **项目根目录**: `/home/fyh0106/AIwerewolf/`
> **参考仓库**: `/home/fyh0106/AIwerewolf/references/`

## 项目运行模式（**最高优先级，覆盖 skills/ 中的多人协作规则**）

**当前阶段：单人开发**（owner: wxhfy / 付一涵）。

- AI 可在用户授权后**直接 `git push` 到 main**：**无需** PR、**无需** review、**无需** 2 人 approve；merge / rebase / squash / cherry-pick 可自主决定。
- 仍保留的护栏（**任何阶段都不放松**）：
  1. 修改"重灾区"文件（`backend/engine/*`、`backend/protocols/schemas.py`、`backend/db/models.py`、`CLAUDE.md`、`AGENTS.md`、`SKILLS.md`、`skills/*`）前用一句话告知用户范围；
  2. 不得 `git push --force` 到 main；
  3. 不得跳过 hook（`--no-verify` / `--no-gpg-sign`）；
  4. 不得把 API Key、`.env`、Prompt 全文写进 commit / PR / 代码注释；
  5. commit message 仍走 Conventional Commits（`feat / fix / docs / chore / refactor / test / perf`）。
- **当团队规模 ≥ 2 时本段失效**，恢复 `skills/10-git-workflow.md` §一 / §三 / §七 与 `skills/70-ai-collaboration.md` §四的多人 PR 规则。

> 本段显式覆盖：
> - `skills/10-git-workflow.md` §一"main 受保护、禁止直推"
> - `skills/10-git-workflow.md` §三"至少 1 人 approve" + 重灾区"2 人 approve"
> - `skills/10-git-workflow.md` §七"禁止 AI 直接 `git push` 到 main"
> - `skills/70-ai-collaboration.md` §四"AI 必须先问人 → `git push origin main`"

---

## AI 助手开工指引（**必读**）

接到任务后，按下面顺序读，缺一不可：

1. **本文件（CLAUDE.md）** — 项目速查
2. **`SKILLS.md`** — 狼人杀业务知识 + 参考仓库
3. **`skills/README.md`** → 进入 **团队协作规范** 索引：
   - `skills/00-team-overview.md` — **全员必读**：三人横向分工、决策权
   - `skills/10-git-workflow.md` — **全员必读**：分支 / Commit / PR / Review
   - `skills/70-ai-collaboration.md` — **必读**：你（AI）必须遵守的红线
   - 改后端代码：`skills/20-backend-conventions.md`
   - 改前端代码：`skills/30-frontend-conventions.md`
   - 改 Agent：`skills/40-agent-development.md`
   - 改 API / Schema：`skills/50-api-contract.md`（任何跨前后端必读）
   - 写测试：`skills/60-testing-ci.md`

**铁律**：动代码前必须查对应 skills/ 文件；跨模块改动必须先列计划让人类确认。
**披露**：PR 描述里必须说明哪些代码由 AI 生成（详见 `skills/70`）。
**问题追踪（必读 + 必写）**：开发中遇到的任何「问题 → 定位 → 修复」闭环，**必须**在闭环关上的同一次会话内追加一条记录到 [`docs/DEVELOPMENT_ISSUES.md`](docs/DEVELOPMENT_ISSUES.md) 对应主题节（§A 后端引擎 / §B 前端 / §C Agent / §D 数据库 / §E WebSocket / §F DevOps / §G Git / §H 工具坑）；用户用纠正 / 抱怨语气提的反馈（"不对"/"错了"/"应该…"），即便不算 bug 也要进 §I "用户反复强调的偏好" 节。条目模板见该文件顶部，按「现象 / 根因 / 解决方案 / 涉及文件 / 教训」五段填写。用途：累积阶段性总结报告素材 + 防止后续 agent 重犯同错。

---

## 项目概述

AI 狼人杀多智能体对战系统。多 Agent 协作/对抗：每个 Agent 根据扮演角色拥有独立目标、策略与行动空间，在严格信息隔离下推理、发言与决策。

## 项目目标

1. **基础对局引擎** — 回合流转、行动校验、胜负裁决、EventLog
2. **Agent 系统** — 角色化 Agent、信息隔离、独立决策
3. **进阶方向**（三选一）：
   - ① 通用 Agent → 自演化系统
   - ② 评测+复盘 → 多维量化评测 + Leaderboard
   - ③ 自进化 Agent → 对局→分析→优化→再对局循环

## 技术栈（规划）

- **后端**: Python（FastAPI + asyncio）+ WebSocket
- **前端**: Next.js + TypeScript + Tailwind CSS
- **AI**: LLM API 多模型接入
- **配置**: YAML

## 项目结构

```
AIwerewolf/
├── CLAUDE.md              # 本文档（CC入口）
├── AGENTS.md              # Codex入口（内容与CLAUDE.md等价）
├── README.md              # 项目说明
├── SKILLS.md              # 狼人杀业务知识
├── docs/
│   ├── prd.md             # 产品需求规格
│   ├── DATA_FLOW.md       # 端到端数据流
│   ├── DEVELOPMENT_ISSUES.md  # 开发问题追踪
│   ├── backend_acceptance_criteria.md  # 验收标准
│   ├── PROJECT_MODULE_DESIGN.md  # 核心模块设计
│   ├── PROJECT_FINAL_FACTS.json   # 结项数据
│   ├── PROJECT_CLOSURE_FACTS.json # 结项快照
│   ├── experiments/       # 实验报告
│   └── archive/           # 归档（含REFERENCE.md等早期文档）
├── backend/
│   ├── engine/            # 游戏引擎
│   ├── agents/            # AI Agent
│   ├── protocols/         # WebSocket/API 协议
│   ├── eval/              # 评测系统
│   ├── llm/               # LLM 客户端
│   └── db/                # ORM + 持久化
├── frontend/              # Next.js 观战 UI
├── scripts/               # 实验、验证、评测脚本
├── tests/                 # 测试套件
├── configs/               # YAML 配置文件
├── skills/                # 开发规范与协作手册
├── data/                  # 实验数据与知识库
├── logs/                  # 运行日志
├── models/                # 本地模型文件
├── nginx/                 # 反向代理配置
└── references/            # 克隆的参考仓库（gitignored）
```

## 参考仓库速查

所有参考仓库已克隆到 `references/` 目录。详细分析见 `docs/REFERENCE.md`。

### 优先级排序

| 优先级 | 仓库 | 核心价值 |
|--------|------|----------|
| #1 | wolfcha | AI 狼人杀产品形态、双层扮演、Phase 设计、Persona 系统 |
| #2 | xiong35/werewolf | 前后端实时架构、房间系统、事件表 |
| #3 | WereWolfPlus | 多模型评测、Prompt 模板、批量对局 |
| #4 | AIWolfPy | Python Agent 接口规范 |
| #5 | AIWolfSharp | Server/Client 分离架构 |
| #6 | werewolf-brain | 60+ 角色库、平衡算法、夜晚序列 |
| #7 | open_mafia_engine | 事件驱动架构、Python 引擎 |
| #8 | OpenWerewolf | 在线多人房间/大厅设计 |
| #9 | AlecM33/Werewolf | 主持工具参考（GPL-3.0，不可复制） |
| #10 | lykos | 复杂角色扩展、Python Bot |

### 三个最值得深入阅读的文件

1. `/home/fyh0106/AIwerewolf/references/WereWolfPlus/agent_manager/prompts/werewolf_prompt.py` — Google 品质的完整 Prompt 模板（所有动作+角色+JSON Schema）
2. `/home/fyh0106/AIwerewolf/references/wolfcha/src/types/game.ts` — Phase 枚举、Player 类型、Persona 系统定义
3. `/home/fyh0106/AIwerewolf/references/AIWolfPy/aiwolfpy/agentproxy.py` — Agent 接口生命周期（9 个方法）

## 自研核心模块（不可搬参考代码）

- **GameState** — 完整游戏状态
- **PhaseMachine** — 阶段流转
- **ActionValidator** — 行动校验
- **ResolutionEngine** — 行动结算
- **Visibility** — 信息隔离
- **AgentDecision Schema** — 统一决策协议
- **EventLog Schema** — 结构化日志
- **Replay Analyzer** — 复盘分析
- **Evaluation Metrics** — 评测指标

## 关键设计参考

### 阶段流转（来自 wolfcha）
夜晚：NIGHT_START → NIGHT_GUARD_ACTION（守卫+狼+预言家并行）→ NIGHT_WITCH_ACTION → NIGHT_RESOLVE
白天：DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION → DAY_SPEECH → SHERIFF_CLOSING → VOTE → DAY_RESOLVE
特殊：HUNTER_SHOOT / WHITE_WOLF_KING_BOOM / BADGE_TRANSFER / DAY_LAST_WORDS / DAY_PK_SPEECH / GAME_END

### 角色列表（来自多个仓库）
基础：Villager / Werewolf / Seer / Witch / Hunter / Guard
扩展：Idiot / WhiteWolfKing / Cupid / BigBadWolf / WolfCub 等 60+

### Prompt 结构（来自 WereWolfPlus）
GAME 规则 → STATE 状态 → OBSERVATIONS 观察 → 角色策略指引 → JSON Schema 输出

### Agent 接口（来自 AIWolfPy）
initialize → dayStart → {talk, vote} / {attack, guard, divine} → finish

---

## 狼人杀游戏规则（必读，写 UI/逻辑前对照）

> **规则错误是低级错误。** 改任何涉及游戏逻辑的代码前，必须对照本节。

### 核心概念

- **两大阵营**：好人（神民 + 村民） vs 狼人
- **回合制**：黑夜（角色行动）↔ 白天（发言 + 投票）
- **信息隔离**：狼人互相知道；好人互相不知道；预言家可查验；女巫可知死讯

### 角色技能

| 角色 | 阵营 | 夜间技能 | 特殊 |
|------|------|----------|------|
| 村民 | 好人 | 无 | — |
| 预言家 | 好人-神 | 每晚查验一名玩家（狼人/好人） | — |
| 女巫 | 好人-神 | 解药（救人）+ 毒药（杀人），各一瓶 | 不可同夜使用两药 |
| 猎人 | 好人-神 | 被投票放逐或狼杀时可开枪带人 | 被毒死不能开枪 |
| 守卫 | 好人-神 | 每晚守一名玩家（免疫狼刀） | 不可连续两晚守同一人 |
| 白痴 | 好人-神 | 被投票放逐时翻牌免死 | 翻牌后失去投票权 |
| 狼人 | 狼人 | 每晚共同击杀一名玩家 | 可自爆（白天翻牌直接进入黑夜） |
| 白狼王 | 狼人 | 同狼人 | 自爆时可带走一名玩家 |

### ⚠️ 关键规则（前端常出错的地方）

1. **狼刀目标不能是狼人**：狼人击杀的候选目标只能是 **非狼人存活玩家**。狼人不能选择自己或狼队友作为击杀目标。只有在极少数策略场景下才会自刀，且那不是默认行为。

2. **警徽投票的分母不是总人数**：警徽竞选时，候选人只被投、不投票。分母 = 存活人数 − 候选人数。如 8 人 3 候选人 → 分母 = 5。

3. **夜晚行动顺序是固定的**：守卫/狼人/预言家（并行）→ 女巫 → 结算。前端展示时必须按此顺序。

4. **投票结果应在遗言之前**：白天放逐投票结果公布后，被放逐者发表遗言。不能先显示遗言再显示投票结果。

5. **"同守同救"（奶穿）**：若同一玩家同时被守卫守护和女巫解药救，该玩家仍死亡。

### 夜晚阶段顺序

```
NIGHT_START          天黑请闭眼
NIGHT_GUARD_ACTION   守卫/狼人/预言家 并行行动
                     — 守卫选择守护目标
                     — 狼人共同选择击杀目标
                     — 预言家查验一名玩家
NIGHT_WITCH_ACTION   女巫请睁眼 — 获知死讯，决策用药
NIGHT_RESOLVE        黑夜结算 — 确定死亡 & 猎人开枪 & 胜负判定
```

### 白天阶段顺序

```
DAY_START             天亮了 — 公布死讯
DAY_BADGE_SIGNUP      警徽报名（仅第一天）
DAY_BADGE_SPEECH      警徽竞选发言
DAY_BADGE_ELECTION    警徽投票
DAY_SPEECH            自由发言（并行）
DAY_SHERIFF_CLOSING   警长总结
DAY_VOTE              放逐投票
DAY_RESOLVE           投票结算 & 猎人开枪 & 胜负判定
--- 以下为事件触发阶段 ---
DAY_PK_SPEECH         平票 PK 发言
DAY_PK_VOTE           平票 PK 投票
DAY_LAST_WORDS        遗言（如有人被放逐）
BADGE_TRANSFER        警徽移交（警长出局时）
HUNTER_SHOOT          猎人开枪
WHITE_WOLF_KING_BOOM  白狼王自爆
```
HUNTER_SHOOT       猎人开枪
```

### 胜利条件

- **好人赢**：所有狼人出局
- **狼人赢（屠边）**：所有神民出局 或 所有村民出局
- **狼人赢（屠城）**：所有好人出局

### 前端展示的数据流

```
night_actions.wolf_votes:     { wolfId: targetId } — 狼人个人投票（可能不一致）
night_actions.wolf_target_id: 最终击杀目标 ID（权威来源）
gameState.votes:              当前阶段实时投票
gameState.vote_history:       每天的投票结果（持久化）
```

**⚠️ `wolf_votes` 中的 target 可能是狼人个体提出的初始目标，不一定等于最终的 `wolf_target_id`。前端展示时必须以 `wolf_target_id` 为权威来源统一所有狼人行动日志。**

---

## 开发约定

- Python 代码使用 type hints
- 配置使用 YAML 格式
- 事件日志使用结构化 JSON
- 每个 Agent 只能看到其角色允许的信息（信息隔离）
- 参考仓库代码不直接复制，理解后重写
