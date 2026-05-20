# AI Werewolf 开发技能手册

> 本文档是给 AI Agent（Claude Code / Codex / 其他）的开发速查手册。
> 当 Agent 接到狼人杀相关开发任务时，**先读本文档**了解全局背景和参考资源。

---

## 一、项目背景

### 课题定位
**AI 狼人杀 — 多智能体协作与博弈的 Agent Team 实战**

基于多 Agent 协作框架，构建一个能够自主完成信息不对称博弈的狼人杀 Agent Team 系统。核心在于多智能体的协作/对抗与交互机制设计：每个 Agent 根据其扮演角色（狼人、预言家、女巫等）拥有独立的目标、策略与行动空间，在严格信息隔离的约束下进行推理、发言与决策。

### 核心模块
| 模块 | 说明 |
|------|------|
| 对局引擎 | 回合流转、行动校验、胜负裁决 |
| Agent 系统 | 角色化 AI Agent、信息隔离、独立决策 |
| 结构化日志 | 全程可观测 EventLog |
| 观战 UI | 纯 AI 对战 / 人机混战，实时博弈展示 |

### 进阶方向（三选一，后续确定）
1. **通用 Agent** — "读懂自己→修改自己→运行自己"自演化
2. **评测+复盘** — 多维量化评测 + Leaderboard
3. **自进化 Agent** — "对局→分析→优化→再对局"循环

---

## 二、技术栈规划

| 层 | 推荐技术 | 理由 |
|----|----------|------|
| 后端引擎 | Python (FastAPI + asyncio) | AIWolfPy、open_mafia_engine 都是 Python |
| 实时通信 | WebSocket (Socket.IO 或原生) | xiong35/werewolf 用 Socket.IO 很成熟 |
| 前端 | Next.js + TypeScript + Tailwind CSS | wolfcha 的最佳实践 |
| Agent | Python + Pydantic | 类型安全、序列化方便 |
| LLM 接入 | API 代理层（统一多模型） | wolfcha 的 `/api/chat` 模式 |
| 配置 | YAML | WereWolfPlus 的 YAML 配置体系很灵活 |
| 日志 | 结构化 JSON | 可序列化、可回放 |

---

## 三、参考仓库速查（已下载）

> 所有仓库在 `references/` 目录下。**不要直接复制代码**，理解设计思路后重写。

### P0 — 最优先参考

#### #1 wolfcha (`references/wolfcha/`)
**AI 狼人杀产品标杆** — 1 真人 vs N AI，双层扮演，完整产品体验
- Phase 枚举：22 个阶段（NIGHT_START → GUARD → WOLF → WITCH → SEER → NIGHT_RESOLVE → DAY_START → BADGE_SIGNUP → BADGE_SPEECH → ... → GAME_END）
- 角色：Villager / Werewolf / Seer / Witch / Hunter / Guard / Idiot / WhiteWolfKing
- **最有价值文件**：
  - `src/types/game.ts` — Player/Phase/Role/Persona 类型定义（完整）
  - `src/lib/game-master.ts` — 纯函数游戏逻辑（setupPlayers, transitionPhase, checkWinCondition, tallyVotes）
  - `src/game/core/PhaseManager.ts` — Phase → GamePhase 类映射
  - `src/lib/game-flow-controller.ts` — FlowToken 模式防止过期回调
  - `src/lib/character-generator.ts` — AI 人格生成器（MBTI + 背景）

#### #2 xiong35/werewolf (`references/werewolf/`)
**线下狼人杀全栈产品** — Koa + Socket.IO + Vue3，真人面杀辅助
- 前后端分离（werewolf-backend / werewolf-frontend）
- 共享类型定义在 `werewolf-frontend/shared/`
- 功能：房间系统、警长竞选、事件表、断线重连、历史对局
- **最有价值文件**：
  - `werewolf-frontend/shared/GameDefs.ts` — GameStatus 枚举（20+ 状态）、TIMEOUT 配置
  - `werewolf-frontend/shared/ModelDefs.ts` — Room/Player/CharacterStatus 接口
  - `werewolf-backend/src/models/RoomModel.ts` — Room 类（房间生命周期）
  - `werewolf-backend/src/handlers/http/gameActHandlers/` — 每个游戏动作独立 handler

#### #3 WereWolfPlus (`references/WereWolfPlus/`)
**多模型评测框架** — YAML 配置化对战，批量并行评测
- 每阵营可配置不同 LLM 模型
- 完整 Prompt 模板（18 种动作 × 多种角色）
- 评测指标：胜率/IRP/KSR/VSS/角色 KPI
- **最有价值文件**：
  - `agent_manager/prompts/werewolf_prompt.py` — **最重要！** Google 品质的完整 Prompt 模板
  - `games/werewolf/werewolf_env.py` — Gym 风格的 WereWolfEnv
  - `games/werewolf/model.py` — Player/GameView/Round 数据模型
  - `games/werewolf/game.py` — GameMaster 类（eliminate/exile/check_winner）

#### #4 AIWolfPy (`references/AIWolfPy/`)
**Python Agent 接口规范** — AIWolf 比赛平台的 Python SDK
- Agent 生命周期：NAME→ROLE→INITIALIZE→[DAILY_INITIALIZE→{TALK/VOTE/ATTACK/DIVINE/GUARD}→DAILY_FINISH]→FINISH
- 9 个 Agent 方法：initialize / update / dayStart / talk / whisper / vote / attack / divine / guard / finish
- **最有价值文件**：
  - `aiwolfpy/agentproxy.py` — AgentProxy（协议解析 + Agent 委托）
  - `python_simple_sample.py` — 最小完整 Agent 示例

#### #5 AIWolfSharp (`references/AIWolfSharp/`)
**C# 完整实现** — Server/Client 分离，多语言 Player 支持
- IPlayer 接口：11 个方法（含 MediumResult / DivineResult）
- GameInfo / GameSetting 富数据类（Day/Role/VoteList/AttackVoteList/StatusMap/...）
- **最有价值文件**：
  - `AIWolfLibCommon/Data/IPlayer.cs` — 标准化 Agent 接口
  - `AIWolfLibCommon/Net/GameInfo.cs` — 游戏状态数据结构

### P1 — 辅助参考

#### #6 werewolf-brain (`references/werewolf-brain/`)
**规则/角色/板子库** — 60+ 角色 + 权重平衡 + 夜晚序列
- 每个角色有权重值（正=好人，负=狼人）
- 42 步标准夜晚调用序列（sequence.json）
- 角色→夜晚动作绑定（bindings.json）
- **最有价值文件**：
  - `src/data/cards.json` — 60+ 角色及权重
  - `src/data/sequence.json` — 夜晚调用序列
  - `src/data/bindings.json` — 角色→动作映射
  - `src/moderator.js` — 从牌组生成夜晚剧本

#### #7 open_mafia_engine (`references/open_mafia_engine/`)
**Python 事件驱动引擎** — 声明式游戏定义，可扩展
- 核心：event_system / state / game / phase_cycle / outcome
- 内置：phases / kills / voting / protect / information
- **最有价值文件**：
  - `open_mafia_engine/core/event_system.py`
  - `open_mafia_engine/core/phase_cycle.py`
  - `open_mafia_engine/built_in/phases.py`

#### #8 OpenWerewolf (`references/OpenWerewolf/`)
**在线多人房间系统** — Node.js + TypeScript，Apache 2.0
- 房间/大厅设计、多人实时同步

#### #9 AlecM33/Werewolf (`references/Werewolf/`)
**主持工具** — Socket.IO + Redis + Express
- ⚠️ GPL-3.0 许可证，不可直接复制代码
- 参考：主持人/旁观/角色信息展示

#### #10 lykos (`references/lykos/`)
**Python IRC Bot** — 复杂角色扩展、文本命令交互
- roles/ 角色定义、gamemodes/ 游戏模式

---

## 四、狼人杀游戏开发核心知识点

### 4.1 基础规则

**人数**：6-12 名玩家（含 1 名主持人）
**阵营**：好人阵营（村民 + 神职）vs 狼人阵营
**轮次**：黑夜 → 白天 → 黑夜 → ... 交替进行

**胜负条件**：
- 好人获胜：所有狼人被投票出局
- 狼人获胜：狼人数量 ≥ 存活的好人数量（屠边）

### 4.2 标准角色能力

| 角色 | 阵营 | 能力 | 使用次数 |
|------|------|------|----------|
| 村民 Villager | 好人 | 无特殊能力，靠推理和投票 | — |
| 狼人 Werewolf | 狼人 | 黑夜刀人；狼人间可私语 | 每夜 1 次 |
| 预言家 Seer | 好人 | 黑夜查验一名玩家身份（好人/狼人） | 每夜 1 次 |
| 女巫 Witch | 好人 | 解药（救人）+ 毒药（毒人） | 各 1 次/局 |
| 猎人 Hunter | 好人 | 死亡时可开枪带走一人 | 1 次/局 |
| 守卫 Guard | 好人 | 黑夜守护一名玩家，不能连续守同一人 | 每夜 1 次 |
| 白痴 Idiot | 好人 | 被投票放逐时不死亡，但失去投票权 | 1 次/局 |
| 白狼王 WhiteWolfKing | 狼人 | 白天可自爆直接进入黑夜 | 1 次/局 |
| 丘比特 Cupid | 第三方 | 首夜连接两人成为情侣 | 1 次/局 |

### 4.3 扩展角色库（来自 werewolf-brain）

角色权重体系用于板子平衡：
- 正值 = 好人阵营有利，负值 = 狼人阵营有利
- 板子总权重接近 0 表示平衡

**高级狼人角色**（值 < -5）：
Big Bad Wolf(-9)、Wolf Man(-9)、Wolf Cub(-8)、Vampire(-7)、Werewolf(-6)、Bogeyman(-6)、Minion(-6)、Dream Wolf(-5)

**高级好人角色**（值 > 3）：
Seer(7)、Leprechaun(5)、The Count(5)、Witch(4)、Apprentice Seer(4)、Chupacabra(4)

**第三方/中立角色**（值接近 0）：
Cupid(-2)、Fortune Teller(0)、Hoodlum(0)、Little Girl(0)、Old Man(0)

### 4.4 夜晚流程顺序（来自 werewolf-brain sequence.json）

```
1. 狼人变身 (Lycan)
2. 硬汉不死 (Tough Guy)  
3. 被诅咒者 (Cursed)
4. 猎人 (Hunter)
5. 水果兽 (Fruit Brute)
6. 学徒预言家 (Apprentice Seer)
7. 病人 (Diseased)
8. 大坏狼 (Big Bad Wolf)
9. 狼人 (Wolf Man)
10. 爪牙 (Minion)
11. 丘比特 (Cupid)
12. 情侣互认 (Lovebirds)
...（共 42 步）...
最后：狼人刀人 (Werewolves) → 女巫 (Witch) → 预言家 (Seer) → 会议 (Meeting)
```

### 4.5 白天流程

```
DAY_START（天亮，公布死讯）
  ↓
BADGE_SIGNUP（警长竞选报名）
  ↓
BADGE_SPEECH（竞选发言）
  ↓
BADGE_ELECTION（投票选警长）
  ↓
DAY_SPEECH（轮流发言 / 自由讨论）
  ↓
DAY_VOTE（投票放逐）
  ↓
DAY_RESOLVE（公布投票结果，被放逐者遗言）
```

---

## 五、自研核心模块设计

### 5.1 GameState（游戏状态）
```python
class GameState:
    phase: Phase                    # 当前阶段
    round: int                      # 当前轮次
    players: list[Player]           # 所有玩家
    alive_players: set[int]         # 存活玩家（seat → id）
    role_map: dict[int, Role]       # 座位 → 角色
    vote_history: list[VoteRecord]  # 投票记录
    kill_history: list[KillRecord]  # 死亡记录
    sheriff: int | None             # 警长座位
    couple: tuple[int, int] | None  # 情侣
```

### 5.2 PhaseMachine（阶段机）
- 状态：每个 Phase 是独立状态
- 转换：根据行动结果和规则决定下一个 Phase
- 超时：每个 Phase 有最大执行时间
- 跳过：某些 Phase 在条件不满足时跳过（如无警长则跳过 BADGE_TRANSFER）

### 5.3 ActionValidator（行动校验）
- 每个行动检查：当前 Phase 是否允许、角色是否有权限、目标是否合法
- 非法行动返回错误，不影响游戏状态

### 5.4 ResolutionEngine（结算引擎）
- 收集所有玩家行动 → 按优先级排序 → 逐一结算
- 结算顺序：守卫守护 → 狼人刀人 → 女巫用药 → 预言家查验 → 判定死亡

### 5.5 Visibility（信息隔离）
每个 Agent 能看到的信息取决于其角色：
| 角色 | 可见信息 |
|------|----------|
| 狼人 | 同伴身份、狼人私语、夜晚刀人结果 |
| 预言家 | 查验结果 |
| 女巫 | 夜晚死者（被刀的玩家） |
| 守卫 | 自己的守护记录 |
| 村民 | 仅公开信息（发言、投票、死亡公告） |
| 猎人 | 同村民 + 被毒死时不能开枪 |

### 5.6 AgentDecision Schema
```python
class AgentDecision(BaseModel):
    """Agent 的统一决策输出"""
    reasoning: str                # 推理过程
    action_type: ActionType       # 行动类型
    target: int | None            # 目标玩家 seat
    speech: str | None            # 发言内容（TALK/WHISPER 时）
    vote_target: int | None       # 投票目标
```

### 5.7 EventLog Schema
```python
class GameEvent(BaseModel):
    """结构化游戏事件"""
    round: int                    # 轮次
    phase: Phase                  # 阶段
    timestamp: float              # 时间戳
    event_type: str               # 事件类型
    actor: int | None             # 行动者 seat
    targets: list[int]            # 目标
    public_data: dict             # 公开数据
    private_data: dict            # 仅特定角色可见数据
```

---

## 六、Prompt 工程参考（来自 WereWolfPlus）

### 6.1 Prompt 分层结构
```
GAME 规则（固定）
  ↓
STATE 当前状态（轮次/角色/存活玩家）
  ↓
OBSERVATIONS 私有观察（之前获得的信息）
  ↓
DEBATE_SO_FAR 本轮发言内容
  ↓
角色特定策略指引
  ↓
JSON Schema 输出格式
```

### 6.2 全部动作 Prompt 清单
| 动作 | 英文 | 阶段 | 谁用 |
|------|------|------|------|
| 发言竞价 | bid | 白天 | 所有人 |
| 公开发言 | debate | 白天 | 所有人 |
| 投票放逐 | vote | 白天 | 所有人 |
| 选警长 | elect | 白天 | 所有人 |
| 警长投票 | sheriff_vote | 白天 | 警长 |
| 警长总结 | sheriff_summarize | 白天 | 警长 |
| 竞选发言 | sheriff_debate | 白天 | 候选人 |
| 竞选报名 | run_for_sheriff | 白天 | 所有人 |
| 警长移交 | badge_flow | 白天 | 警长 |
| 查验身份 | investigate | 黑夜 | 预言家 |
| 刀人 | remove | 黑夜 | 狼人 |
| 守护 | protect | 黑夜 | 守卫 |
| 救人 | save | 黑夜 | 女巫 |
| 毒人 | poison | 黑夜 | 女巫 |
| 开枪 | shoot | 死亡时 | 猎人 |
| 总结记忆 | summarize | 每轮结束 | 所有人 |
| 伪投票 | pseudo_vote | 白天 | 所有人 |
| 发言顺序 | determine_statement_order | 白天 | 警长 |

---

## 七、开发路线图（建议）

### Phase 1：最小可玩原型 (MVP)
- [ ] GameState + PhaseMachine（6 人局，基础 6 角色）
- [ ] 单机 CLI 对战（所有 Agent 本地运行）
- [ ] 基础 EventLog 输出
- [ ] 对局结束判定

### Phase 2：Agent 系统
- [ ] Agent 接口标准化（基于 AIWolfPy 的 9 方法）
- [ ] LLM Prompt 集成（基于 WereWolfPlus 模板）
- [ ] 信息隔离层
- [ ] 角色特定策略

### Phase 3：产品化
- [ ] WebSocket 实时通信
- [ ] 前端观战 UI
- [ ] 房间/大厅系统
- [ ] 历史对局回放

### Phase 4：进阶
- [ ] 评测体系（胜率/IRP/KSR/VSS）
- [ ] 批量对局 + Leaderboard
- [ ] 自进化循环

---

## 八、常见问题排查

### Q: Agent 接口应该参考什么？
→ `references/AIWolfPy/aiwolfpy/agentproxy.py` — 9 个方法的 Agent 生命周期
→ `references/AIWolfSharp/AIWolfLibCommon/Data/IPlayer.cs` — 标准化接口

### Q: Prompt 怎么写？
→ `references/WereWolfPlus/agent_manager/prompts/werewolf_prompt.py` — 18 种动作的完整 prompt 模板

### Q: 角色有哪些？怎么平衡？
→ `references/werewolf-brain/src/data/cards.json` — 60+ 角色权重

### Q: 游戏阶段怎么设计？
→ `references/wolfcha/src/types/game.ts` — Phase 枚举（22 个阶段）
→ `references/wolfcha/src/game/phases/` — 每个 Phase 的实现

### Q: 信息隔离怎么做？
→ `references/xiong35/werewolf/werewolf-backend/src/models/PlayerModel.ts` — `getPublic()` 方法
→ `references/WereWolfPlus/games/werewolf/model.py` — GameView 类

### Q: WebSocket 事件怎么定义？
→ `references/xiong35/werewolf/werewolf-frontend/shared/WSEvents.ts`

### Q: 评测指标有哪些？
→ `references/WereWolfPlus/games/werewolf/metrics.py`（如存在）或 `agent_eval/agent_eval.py`

---

## 九、禁止行为

- ❌ 直接复制参考仓库的代码（理解设计后重写）
- ❌ 忽略信息隔离（每个 Agent 只能看到其角色允许的信息）
- ❌ 使用 GPL 许可证的代码（AlecM33/Werewolf、GreyWolfDev/Werewolf）
- ❌ 忽略 Phase 超时机制（防止游戏卡死）
- ❌ 用 pandas 做游戏状态管理（过度设计，用简单 dict 即可）
