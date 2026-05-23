# AGENTS.md — AI Werewolf 项目

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

1. **本文件（AGENTS.md）** — 项目速查
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

> 本文件与 `CLAUDE.md` **内容等价**，仅入口名不同（Claude Code 读 `CLAUDE.md`，Codex 通常读本文件）。改一份要同步改另一份。

---

## 项目概述

AI 狼人杀多智能体对战系统 — 多 Agent 在信息不对称下协作/对抗。每个 Agent 扮演狼人杀角色（狼人、预言家、女巫等），拥有独立目标、策略和行动空间。

## 技术栈

- **后端**: Python（FastAPI + asyncio）+ WebSocket
- **前端**: Next.js + TypeScript + Tailwind CSS
- **AI**: LLM API 多模型接入
- **配置**: YAML

## 项目结构

```
AIwerewolf/
├── CLAUDE.md / AGENTS.md  # Agent 指令文件
├── SKILLS.md              # 完整开发手册
├── README.md
├── docs/REFERENCE.md      # 参考仓库分析
├── backend/
│   ├── engine/            # 游戏引擎 (状态机/规则/裁决)
│   ├── agents/            # AI Agent (角色/策略/记忆)
│   ├── protocols/         # WebSocket/API 协议
│   └── eval/              # 评测系统
├── frontend/              # 观战 UI
├── configs/               # YAML 配置文件
└── references/            # 克隆的参考仓库 (gitignored)
```

## 参考仓库速查

全部在 `AIwerewolf/references/`：

| 优先级 | 仓库 | 目录名 | 核心价值 |
|--------|------|--------|----------|
| #1 | oil-oil/wolfcha | `wolfcha/` | AI狼人杀产品、22个Phase、双层扮演、Persona系统 |
| #2 | xiong35/werewolf | `werewolf/` | 前后端架构、WebSocket、房间系统、断线重连 |
| #3 | Char-lotte-Xia/WereWolfPlus | `WereWolfPlus/` | 多模型评测、18种Prompt模板、批量对局 |
| #4 | aiwolf/AIWolfPy | `AIWolfPy/` | Python Agent接口规范、9方法生命周期 |
| #5 | AIWolfSharp/AIWolfSharp | `AIWolfSharp/` | Server/Client分离、IPlayer接口 |
| #6 | lycan-city/werewolf-brain | `werewolf-brain/` | 60+角色库、权重平衡、42步夜晚序列 |
| #7 | open-mafia/open_mafia_engine | `open_mafia_engine/` | Python事件驱动引擎 |
| #8 | JamesCraster/OpenWerewolf | `OpenWerewolf/` | 在线多人房间/大厅 |
| #9 | AlecM33/Werewolf | `Werewolf/` | 主持工具 (⚠️GPL-3.0) |
| #10 | lykoss/lykos | `lykos/` | Python IRC Bot、复杂角色 |

### 最关键的3个文件 (相对路径)

1. `AIwerewolf/references/WereWolfPlus/agent_manager/prompts/werewolf_prompt.py`
   - 完整Prompt模板: 18种动作 × 多角色 × JSON Schema
   - 包含: GAME规则→STATE状态→OBSERVATIONS→角色策略→输出格式
   
2. `AIwerewolf/references/wolfcha/src/types/game.ts`
   - Phase枚举(22个阶段)、Player类型、Persona系统定义
   
3. `AIwerewolf/references/AIWolfPy/aiwolfpy/agentproxy.py`
   - Agent接口: initialize→update→dayStart→{talk/vote/attack/divine/guard}→finish

## 狼人杀核心规则

### 角色
基础6角色: Villager / Werewolf / Seer / Witch / Hunter / Guard
扩展: Idiot / WhiteWolfKing / Cupid / BigBadWolf 等60+(见werewolf-brain)

### 阶段流转
```
夜晚: NIGHT_START → GUARD → WOLF → WITCH → SEER → NIGHT_RESOLVE
白天: DAY_START → BADGE_SIGNUP → BADGE_SPEECH → BADGE_ELECTION → DAY_SPEECH → VOTE → DAY_RESOLVE
特殊: HUNTER_SHOOT / WHITE_WOLF_KING_BOOM / BADGE_TRANSFER / GAME_END
```

### 胜负条件
- 好人胜: 所有狼人被投票出局
- 狼人胜: 狼人数量 ≥ 存活好人数量

## 自研核心模块

| 模块 | 职责 |
|------|------|
| GameState | 完整游戏状态(阶段/轮次/玩家/角色/投票记录) |
| PhaseMachine | 阶段流转引擎(超时/跳过/转换) |
| ActionValidator | 行动合法性校验 |
| ResolutionEngine | 行动结算(按优先级: 守护→刀人→用药→查验→判定死亡) |
| Visibility | 信息隔离层(每个Agent只看角色允许的信息) |
| AgentDecision | 统一决策输出(reasoning+action_type+target+speech) |
| EventLog | 结构化游戏事件(round/phase/timestamp/actor/targets/public/private) |

## Agent 接口契约

```python
class Agent:
    def initialize(base_info, game_setting)  # 初始化
    def update(base_info, diff_data, request) # 增量更新
    def dayStart()                            # 天亮
    def talk() -> str                         # 公开发言
    def whisper() -> str                      # 狼人私语
    def vote() -> int                         # 投票放逐
    def attack() -> int                       # 狼人刀人
    def divine() -> int                       # 预言家查验
    def guard() -> int                        # 守卫守护
    def finish()                              # 对局结束
```

## Prompt 分层结构

```
GAME规则(固定) → STATE状态(轮次/角色/存活) → OBSERVATIONS私有观察 → DEBATE本轮发言 → 角色策略指引 → JSON Schema输出
```

## 开发约定

- Python type hints 必须
- 配置用 YAML
- 日志用结构化 JSON
- 严格信息隔离: 每个Agent只能看角色允许的信息
- 参考仓库代码理解设计后重写，不直接复制
- GPL许可证的代码不可用(AlecM33/Werewolf, GreyWolfDev/Werewolf)

## 开发路线

1. **MVP**: GameState + PhaseMachine + 6人CLI对战 + EventLog
2. **Agent**: 标准化接口 + LLM集成 + 信息隔离
3. **产品化**: WebSocket + 前端UI + 房间系统
4. **进阶**: 评测体系 + Leaderboard + 自进化

## 排查指南

| 问题 | 去哪里看 |
|------|----------|
| Agent接口怎么写? | `AIwerewolf/references/AIWolfPy/aiwolfpy/agentproxy.py` |
| Prompt模板? | `AIwerewolf/references/WereWolfPlus/agent_manager/prompts/werewolf_prompt.py` |
| 角色定义和平衡? | `AIwerewolf/references/werewolf-brain/src/data/cards.json` |
| 夜晚动作顺序? | `AIwerewolf/references/werewolf-brain/src/data/sequence.json` |
| 阶段怎么设计? | `AIwerewolf/references/wolfcha/src/types/game.ts` |
| 信息隔离怎么做? | `AIwerewolf/references/werewolf/werewolf-backend/src/models/PlayerModel.ts` (getPublic方法) |
| WebSocket事件定义? | `AIwerewolf/references/werewolf/werewolf-frontend/shared/WSEvents.ts` |
| 评测指标? | `AIwerewolf/references/WereWolfPlus/agent_eval/agent_eval.py` |
| 事件驱动架构? | `AIwerewolf/references/open_mafia_engine/open_mafia_engine/core/` |
