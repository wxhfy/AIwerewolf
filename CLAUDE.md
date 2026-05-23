# CLAUDE.md — AI Werewolf 项目

> **项目根目录**: `/home/fyh0106/AIwerewolf/`
> **参考仓库**: `/home/fyh0106/AIwerewolf/references/`

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
├── CLAUDE.md              # 本文档
├── README.md              # 项目说明
├── docs/
│   └── REFERENCE.md       # 参考仓库详细分析
├── backend/
│   ├── engine/            # 游戏引擎
│   ├── agents/            # AI Agent
│   ├── protocols/         # 通信协议
│   └── eval/              # 评测系统
├── frontend/              # 观战 UI
├── configs/               # 配置文件
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
夜晚：NIGHT_START → GUARD → WOLF → WITCH → SEER → NIGHT_RESOLVE
白天：DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION → DAY_SPEECH → VOTE → DAY_RESOLVE
特殊：HUNTER_SHOOT / WHITE_WOLF_KING_BOOM / BADGE_TRANSFER / GAME_END

### 角色列表（来自多个仓库）
基础：Villager / Werewolf / Seer / Witch / Hunter / Guard
扩展：Idiot / WhiteWolfKing / Cupid / BigBadWolf / WolfCub 等 60+

### Prompt 结构（来自 WereWolfPlus）
GAME 规则 → STATE 状态 → OBSERVATIONS 观察 → 角色策略指引 → JSON Schema 输出

### Agent 接口（来自 AIWolfPy）
initialize → dayStart → {talk, vote} / {attack, guard, divine} → finish

## 开发约定

- Python 代码使用 type hints
- 配置使用 YAML 格式
- 事件日志使用结构化 JSON
- 每个 Agent 只能看到其角色允许的信息（信息隔离）
- 参考仓库代码不直接复制，理解后重写
