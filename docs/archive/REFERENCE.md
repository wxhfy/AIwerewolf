# 参考仓库分析报告

> 分析时间：2026-05-20 | 用途：AI 狼人杀全栈产品开发参考

---

## P0 — 最优先参考

### 1. wolfcha (oil-oil/wolfcha) — AI 狼人杀产品标杆

- **GitHub**: https://github.com/oil-oil/wolfcha
- **许可**: MIT ✅ 可直接参考
- **技术栈**: Next.js 16 + TypeScript + Tailwind CSS 4 + Radix UI + Jotai + Framer Motion
- **产品形态**: 1 真人 vs N AI 的在线狼人杀，AI 角色有双层扮演（人格+身份）

**核心架构亮点**：

| 模块 | 文件 | 功能 |
|------|------|------|
| 状态管理 | `src/store/game-machine.ts` | Jotai atom，localStorage 持久化 |
| 游戏逻辑 | `src/lib/game-master.ts` | 纯函数：角色分配、阶段流转、胜负判定、死亡处理 |
| 流控 | `src/lib/game-flow-controller.ts` | FlowToken 模式防过期回调，支持暂停/恢复 |
| 阶段管理 | `src/game/core/PhaseManager.ts` | Phase 枚举 → GamePhase 类映射 |
| 角色人格 | `src/lib/character-generator.ts` | MBTI + 背景故事 + 说话风格 + 狼人杀经验 |
| AI 对话 | `src/lib/llm.ts` + `/api/chat` | 流式 LLM 调用代理 |

**阶段设计（完整）**：
```
夜晚：NIGHT_START → NIGHT_GUARD_ACTION → NIGHT_WOLF_ACTION
    → NIGHT_WITCH_ACTION → NIGHT_SEER_ACTION → NIGHT_RESOLVE

白天：DAY_START → DAY_BADGE_SIGNUP → DAY_BADGE_SPEECH
    → DAY_BADGE_ELECTION → DAY_SPEECH → DAY_VOTE → DAY_RESOLVE

特殊：HUNTER_SHOOT → WHITE_WOLF_KING_BOOM → BADGE_TRANSFER → GAME_END
```

**角色类型**：Villager / Werewolf / Seer / Witch / Hunter / Guard / Idiot / WhiteWolfKing

**Agent 人设系统** (Persona)：MBTI、性别、年龄、基础信息、声音规则、关系、逻辑风格、触发话题、社交习惯、幽默风格、狼人杀经验、词汇风格、推理风格、发言长度、压力风格、不确定性风格、错误模式、狼人欺骗风格

**我们最该学的**：
1. FlowToken 模式（防止异步操作在游戏重置后污染状态）
2. 双层扮演机制（人格层 + 身份层）
3. Phase 枚举设计（完整且可扩展）
4. Persona 系统的维度设计
5. AI 语音 + 头像 + TTS 的沉浸式体验

---

### 2. xiong35/werewolf — 线下狼人杀全栈参考

- **GitHub**: https://github.com/xiong35/werewolf
- **许可**: MIT ✅
- **技术栈**: Koa + Socket.IO + Vue3 + TypeScript
- **产品形态**: 线下真人面杀辅助工具

**核心架构**：
```
werewolf-backend/src/
├── handlers/http/gameActHandlers/    # 每个游戏动作独立 handler
│   ├── WolfKill.ts, WitchAct.ts
│   ├── ExileVote.ts, SheriffElect.ts
│   └── DayDiscuss.ts
├── models/PlayerModel.ts, RoomModel.ts
├── ws/index.ts                       # WebSocket
├── utils/checkGameOver.ts, getVoteResult.ts
└── routes/gameRoutes.ts, roomRoutes.ts
```

**前端页面**：Home → CreateRoom → JoinRoom → WaitRoom → Play → Review → ReviewDetail

**功能清单（全部产品级）**：
- 全自动发牌、无需主持人
- 警长竞选系统
- 6 种角色：守卫/猎人/预言家/女巫/村民/狼人
- 游戏中事件表查看
- 断线重连（页面刷新恢复）
- 历史对局查看

**我们最该学的**：
1. 房间/大厅/对局的完整产品流程
2. WebSocket 实时多人通信
3. 游戏动作的 handler 拆分模式
4. 事件表（EventLog）作为产品功能
5. 断线重连机制

---

### 3. WereWolfPlus (Char-lotte-Xia) — 多模型评测体系

- **GitHub**: https://github.com/Char-lotte-Xia/WereWolfPlus
- **技术栈**: Python + YAML 配置 + DSGBench 框架
- **产品形态**: 可配置多模型对战的狼人杀评测平台

**核心模块**：

| 模块 | 功能 |
|------|------|
| `agent_manager/agents/` | Agent 基类，trajectory 追踪 |
| `agent_manager/llm_models/` | LLM 模型抽象层 |
| `agent_manager/prompts/werewolf_prompt.py` | **完整的 Prompt 模板（Google 品质）** |
| `agent_eval/agent_eval.py` | 评测指标计算 |
| `configs/llm_configs/` | YAML 格式模型配置 |
| `configs/eval_configs/` | YAML 格式游戏配置 |
| `run_tasks_parallel.py` | 批量并行对局 |
| `calc_score.py` | 胜率/得分统计 |

**Prompt 模板覆盖的动作（完整）**：
bid / debate / vote / investigate(预言家) / remove(狼人) / protect(守卫) / save(女巫救) / poison(女巫毒) / shoot(猎人) / summarize / pseudo_vote / elect(选警长) / sheriff_vote / sheriff_summarize / run_for_sheriff / sheriff_debate / determine_statement_order / badge_flow

每个 prompt 包含：GAME 规则 → STATE 状态 → OBSERVATIONS 观察 → 角色特定策略 → JSON Schema 输出格式

**配置示例结构**：
```yaml
eval:
  num_matches: 10  # 批量对局数
  output_path: ./output/
game:
  game_name: WereWolfEnv
  good_model_config: model_a.yaml
  bad_model_config: model_b.yaml  # 阵营模型可不同！
agent:
  - agent_name: WereWolfAgent
    agent_nick: Seer
    agent_model_config: model_a.yaml
```

**我们最该学的**：
1. Prompt 模板的分层结构（规则→状态→观察→策略→输出）
2. YAML 配置化 Agent 和模型
3. 批量对局 + 并行评测
4. 阵营可配置不同模型（好/坏阵营用不同 LLM）
5. Message Pool 经验检索系统
6. 动作 → Prompt → Schema 的完整映射

---

### 4. AIWolfPy — Python Agent 接口规范

- **GitHub**: https://github.com/aiwolf/AIWolfPy
- **技术栈**: Python + TCP Socket + JSON
- **用途**: AIWolf 比赛平台的 Python Agent SDK

**核心接口（AgentProxy 生命周期）**：
```
NAME → ROLE → INITIALIZE → [每轮循环] →
  DAILY_INITIALIZE →
    {TALK, WHISPER, VOTE} (白天) / {ATTACK, GUARD, DIVINE} (夜晚) →
  DAILY_FINISH →
FINISH
```

**Agent 方法契约**：
```python
class Agent:
    def initialize(base_info, diff_data, game_setting)
    def update(base_info, diff_data, request)
    def dayStart()
    def vote() -> int       # 返回 target agent idx
    def attack() -> int     # 狼人刀人
    def guard() -> int      # 守卫保护
    def divine() -> int     # 预言家查验
    def talk() -> str       # 白天发言
    def whisper() -> str    # 狼人私语
    def finish()
```

**我们最该学的**：
1. Agent 接口抽象（9 个方法覆盖全部角色）
2. GameInfoParser（游戏信息解析为 pandas DataFrame）
3. 信息增量更新（diff_data 只给变化部分）

---

### 5. AIWolfSharp — C# 完整实现参考

- **GitHub**: https://github.com/AIWolfSharp/AIWolfSharp
- **技术栈**: C# (.NET) + 多项目解决方案
- **架构**: ServerStarter / ClientStarter / DirectStarter（三种启动模式）

**项目拆分**：AIWolfLibCommon（公共库）、AIWolfLibServer、AIWolfLibClient、AgentTester、NativePlayer、CSPlayer、PythonPlayer、VBPlayer

**我们最该学的**：
1. Server/Client 分离架构
2. AgentTester 独立测试工具
3. 多语言 Player 支持（C#, VB, Python）

---

## P1 — 辅助参考

### 6. OpenWerewolf — 在线多人房间系统

- **GitHub**: https://github.com/JamesCraster/OpenWerewolf
- **许可**: Apache 2.0 ✅
- **技术栈**: Node.js + TypeScript + WebSocket
- **核心**: `core/` 游戏逻辑, `client/` 前端, `games/` 规则配置
- **参考点**: 房间/大厅设计、多人实时同步、游戏配置化

### 7. AlecM33/Werewolf — 主持工具参考

- **GitHub**: https://github.com/AlecM33/Werewolf
- **许可**: GPL-3.0 ⚠️ 不可直接复制代码
- **技术栈**: Express + Socket.IO + Redis + Docker
- **参考点**: 主持人/旁观/角色信息展示、Docker 部署

### 8. werewolf-brain — 规则/卡牌/平衡系统

- **GitHub**: https://github.com/lycan-city/werewolf-brain
- **许可**: (检查)
- **技术栈**: Node.js 库
- **核心价值**：
  - 60+ 角色定义，每个有权重值（正=好人，负=狼人）
  - 夜晚调用序列（sequence.json）：42 步标准流程
  - 角色→夜晚动作绑定（bindings.json）
  - 自动生成对局剧本（moderator.js）
  - 板子平衡算法（weight balance）

**角色权重示例**：
| 角色 | 权重 | 阵营 |
|------|------|------|
| Seer (预言家) | +7 | 好人 |
| Witch (女巫) | +4 | 好人 |
| Hunter (猎人) | +3 | 好人 |
| Villager (村民) | +1 | 好人 |
| Werewolf (狼人) | -6 | 狼人 |
| Wolf Cub (狼崽) | -8 | 狼人 |
| Big Bad Wolf | -9 | 狼人 |
| Cupid (丘比特) | -2 | 第三方 |

### 9. open_mafia_engine — 事件驱动架构

- **GitHub**: https://github.com/open-mafia/open_mafia_engine
- **许可**: (检查)
- **技术栈**: Python + Poetry
- **核心模块**：
  - `core/event_system.py` — 事件系统
  - `core/state.py` — 游戏状态
  - `core/phase_cycle.py` — 阶段流转
  - `core/outcome.py` — 胜负判定
  - `built_in/phases.py` — 内置阶段
  - `built_in/kills.py` — 击杀逻辑
  - `built_in/voting.py` — 投票逻辑
  - `built_in/protect.py` — 保护逻辑
- **参考点**: 声明式游戏定义、事件驱动、可扩展引擎

### 10. lykos — Python 狼人杀 Bot

- **GitHub**: https://github.com/lykoss/lykos
- **技术栈**: Python + IRC
- **结构**: `roles/` 角色定义, `gamemodes/` 游戏模式, `src/` 核心逻辑
- **参考点**: 复杂角色扩展、文本命令交互

---

## 综合开发建议

### 技术栈推荐

| 层 | 推荐 | 来源 |
|----|------|------|
| 前端 | Next.js + TypeScript + Tailwind | wolfcha |
| 实时通信 | WebSocket (Socket.IO) | xiong35/werewolf |
| 后端规则引擎 | Python (FastAPI + asyncio) | open_mafia_engine + AIWolfPy |
| Agent 框架 | Python + Pydantic | AIWolfPy + WereWolfPlus |
| 配置管理 | YAML | WereWolfPlus |
| 事件日志 | 结构化 JSON | WereWolfPlus + xiong35 |
| AI 接入 | LLM API 代理层 | wolfcha |

### 自研核心（不可直接搬）

1. **GameState** — 完整游戏状态机
2. **PhaseMachine** — 阶段流转引擎
3. **ActionValidator** — 行动合法性校验
4. **ResolutionEngine** — 行动结算引擎
5. **Visibility** — 信息隔离层（每个 Agent 只能看到该看的）
6. **AgentDecision Schema** — 统一的 Agent 决策协议
7. **EventLog Schema** — 结构化日志
8. **Replay Analyzer** — 复盘分析器
9. **Evaluation Metrics** — 多维度评测指标

### 玩法和可玩性关键

1. **角色多样性**：基于 werewolf-brain 的 60+ 角色库设计板子
2. **双层扮演**：参考 wolfcha 的人格+身份机制
3. **警长系统**：参考 WereWolfPlus 的竞选/发言/投票/移交完整流程
4. **发言竞价**：WereWolfPlus 的 BIDDING 机制（抢发言优先级）
5. **自爆机制**：WhiteWolfKing 自爆直接进入黑夜
6. **猎人开枪**：死后可选择带走一人
7. **信息不对称**：严格按角色分配可见信息
