# AI Werewolf 项目面试完整讲述指南

> 生成时间：2026-05-26 | 基于项目实际代码与开发记录
> 合并自 `interview-frontend-guide.md` + `agent-system-design.md`

---

## 目录

- [一、项目概述](#一项目概述)
- [二、面试讲述框架（3-5 分钟）](#二面试讲述框架3-5-分钟)

**Part A — 前端**

- [A1. 前端技术架构](#a1-前端技术架构)
- [A2. 前端核心难点与解决方案](#a2-前端核心难点与解决方案)
- [A3. 个人贡献陈述](#a3-个人贡献陈述)
- [A4. 面试官追问预案（前端）](#a4-面试官追问预案前端)

**Part B — Agent 系统**

- [B1. 设计目标与整体架构](#b1-设计目标与整体架构)
- [B2. 信息隔离 —— 架构级安全保障](#b2-信息隔离--架构级安全保障)
- [B3. 双层扮演架构（wolfcha 风格）](#b3-双层扮演架构wolfcha-风格)
- [B4. Prompt 工程详解](#b4-prompt-工程详解)
- [B5. 防幻觉多层防御体系](#b5-防幻觉多层防御体系)
- [B6. 关注角度系统](#b6-关注角度系统)
- [B7. LLM 调用与重试策略](#b7-llm-调用与重试策略)
- [B8. HeuristicAgent 兜底机制](#b8-heuristicagent-兜底机制)
- [B9. 角色定义系统（Role Registry）](#b9-角色定义系统role-registry)
- [B10. Agent 完整生命周期](#b10-agent-完整生命周期)
- [B11. 面试官追问预案（Agent）](#b11-面试官追问预案agent)

**Part C — 综合**

- [C1. 可展示的技术亮点清单](#c1-可展示的技术亮点清单)
- [C2. 项目数据一览](#c2-项目数据一览)
- [C3. 踩过的关键坑汇总](#c3-踩过的关键坑汇总)
- [附录：关键文件索引](#附录关键文件索引)

---

## 一、项目概述

### 一句话总结

> AI 狼人杀多智能体对战平台。7 个 AI 各扮演一个狼人杀角色（狼人、预言家、女巫等），在严格信息隔离下通过 LLM 推理进行发言、投票和使用技能。前端基于 **Next.js + TypeScript + Tailwind CSS**，通过 **WebSocket** 实时接收游戏状态推送，以 80ms 帧率渲染完整对局过程。

**一句话定调**：这不是简单的 CURD 应用，而是**实时流式数据驱动的复杂游戏状态渲染系统**。

### 技术栈总览

| 层级 | 前端 | 后端/Agent |
|------|------|------------|
| 框架 | Next.js 14 (App Router) | Python FastAPI + asyncio |
| 语言 | TypeScript (strict) | Python (type hints) |
| 样式 | Tailwind CSS + CSS 动画 | — |
| 状态管理 | React Context + useMemo | 纯 dataclass GameState |
| 实时通信 | WebSocket（指数退避重连） | WebSocket + 线程安全队列 |
| LLM | — | doubao (Seed 2.0) / deepseek (v4 Flash) |
| 数据库 | — | SQLite / PostgreSQL (SQLAlchemy) |
| 国际化 | 自研 i18n（中英双语） | — |
| 无障碍 | ARIA + 键盘 + reduced-motion | — |

---

## 二、面试讲述框架（3-5 分钟）

### 第 1 分钟：背景与定位

```
"这是一个 AI 狼人杀项目——7 个 AI 各扮演一个角色，
在严格信息隔离下通过 LLM 推理进行发言、投票和使用技能。
我的工作涵盖了前端观战系统和部分 Agent 设计。

前端不是简单的展示层——它要处理实时流式数据、
复杂游戏状态渲染、阶段切换动画、WebSocket 断线恢复。

Agent 系统的核心命题是让 7 个 AI 展现出不同的
人格和推理方式，产生真实可信的对局过程。"
```

### 第 2-3 分钟：架构全景图

```
┌──────────────────────────────────────────────────────┐
│                  Python 游戏引擎                       │
│  WerewolfGame.play() 在独立线程中运行                  │
│  每次状态变更 → observer(state) → 序列化为 dict        │
│                      │                               │
│                      ▼                               │
│    Visibility.for_player() → PlayerView（信息隔离）    │
│                      │                               │
│                      ▼                               │
│    LLMAgent.talk() / vote() / attack()               │
│    ├─ 双层扮演: Role + Character(Persona+PlayerMind)   │
│    ├─ Prompt 分片组装（wolfcha 风格）                   │
│    └─ 3 次渐进式重试 + Heuristic fallback             │
│                      │                               │
│                      ▼                               │
│              线程安全队列 → 80ms 消费                   │
│              → WebSocket JSON 推送                    │
│                      │                               │
│                      ▼                               │
│  ┌────────────────────────────────────────────┐      │
│  │           Next.js 前端                       │      │
│  │                                             │      │
│  │  useRoomStream → WebSocket + 指数退避重连    │      │
│  │       │                                     │      │
│  │       ▼                                     │      │
│  │  AppContext → useGameDerivedState (memoized) │      │
│  │       │                                     │      │
│  │       ▼                                     │      │
│  │  usePhaseTransition → 阶段动画 + token 防竞态│      │
│  │       │                                     │      │
│  │       ▼                                     │      │
│  │  PlayerCard / ChatBubble / EventTimeline ... │      │
│  └────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────┘
```

**关键设计决策**：
- 后端引擎是**同步**的，跑在 Python 线程里；前端通过 WebSocket 拿每 80ms 推送的全量快照
- Agent 永远不接触 `GameState`，只拿到 `PlayerView`（信息隔离是架构级而非 Prompt 级）
- 前端所有组件只读 gameState，单向数据流，可预测易调试

### 第 3-4 分钟：挑一个难点深讲

**建议选"阶段动画系统"**（纯前端）或 **"双层扮演架构"**（Agent 系统），根据面试岗位选择。

### 第 4-5 分钟：成果收尾

```
"最终效果：
- 完整对局流程：创建房间 → 角色分配 → 实时观战 → 结算
- AI 每句话、每张票实时推送（80ms 间隔）
- 30+ 个人格 × 8 种思维模式 × 7 种角色 = 1680 种玩家画像
- WebSocket 断线自动重连（指数退避 1s→30s）
- 刷新页面不丢对局（hydrate-first 策略）
- LLM fallback 率从 65% 优化到 0%
- 中英双语、全键盘可访问、reduced-motion 友好"
```

---

---

# Part A — 前端

---

## A1. 前端技术架构

### A1.1 目录结构

```
frontend/
  app/
    layout.tsx              # 根布局：<AppProvider> 包裹全局上下文
    page.tsx                # 大厅页：创建房间、配置参数、确认开局
    globals.css             # 全局样式 + 日夜主题 + 动画关键帧
    room/[id]/play/         # 对局页面（动态路由）
  components/
    game/
      PlayerCard.tsx        # 玩家卡片（角色揭示、警徽、思考中状态）
      ChatBubble.tsx        # 发言气泡（系统消息/玩家消息/自己发言）
      EventTimeline.tsx     # 事件时间线（按天分组 + 死亡摘要）
      DayBlock.tsx          # 单天事件块
      EventItem.tsx         # 单个事件条目（投票/夜晚行动等）
      PhaseBanner.tsx       # 阶段横幅（日/夜图标 + 阶段名）
      PhaseAnnouncement.tsx # 全屏阶段公告动画
      VoteTargetGrid.tsx    # 投票目标网格
      ActionPanel.tsx       # 人类玩家操作面板
      GameHeader.tsx        # 游戏顶栏
      GameEndPanel.tsx      # 结算面板（可拖拽浮动按钮 + 弹窗）
      CountdownTimer.tsx    # 倒计时组件
      LobbyConfigCard.tsx   # 大厅配置卡片
      PrepareModal.tsx      # 确认开局弹窗
      PlayerRail.tsx        # 玩家侧栏
    ui/
      Badge.tsx / Button.tsx / Card.tsx  # 通用 UI 原子组件
  context/
    AppContext.tsx           # 全局状态（语言/视角/游戏状态/房间）
  hooks/
    useRoomStream.ts         # WebSocket 连接 + 自动重连
    useGameDerivedState.ts   # 派生状态计算（memoized）
    usePhaseTransition.ts    # 阶段切换动画编排
    useGamePageController.ts # 对局页面控制器
    useAutoScroll.ts         # 自动滚动
  lib/
    gameApi.ts              # REST API 客户端（含超时处理）
    gamePhase.ts            # 阶段分类工具（Set-based O(1) 查询）
    gameView.ts             # 视图模型转换
    i18n.ts                 # 中英双语翻译
    utils.ts                # 通用工具（cn() 类名合并等）
  types/
    index.ts                # TypeScript 类型定义（镜像 Python 模型）
```

### A1.2 数据流

```
WebSocket 消息
  │
  ▼
useRoomStream.onmessage
  ├─ msg.type === "snapshot" → setGameState(msg.state)
  ├─ msg.type === "complete" → setGameState + 清理连接
  ├─ msg.type === "room"     → setRoom(msg.room)
  └─ msg.type === "error"    → 错误状态
  │
  ▼
AppContext (gameState 更新)
  │
  ├─▶ useGameDerivedState(gameState)
  │     ├─ dayBlocks: Map<day, events[]>（按天分组）
  │     ├─ leftPlayers / rightPlayers（双列布局分割）
  │     ├─ badgeCandidateSet（O(1) 查找候选人）
  │     ├─ humanPlayer / wolfTeammates（人类玩家相关）
  │     └─ aliveCount / activeSpeakerId / sheriffId
  │
  ├─▶ usePhaseTransition(gameState.phase, sessionKey)
  │     ├─ visualPhaseGroup: 'day' | 'night' | 'end'
  │     ├─ phaseAnnouncement: {show, message, subMessage}
  │     └─ data-phase 属性 → CSS 主题切换
  │
  └─▶ React 组件（只读 props，不修改 gameState）
```

### A1.3 WebSocket 重连机制

```
断开连接
  │
  ├─ 游戏已结束 (winner != null) → 不重连
  ├─ 正常关闭 (code 1000/1001) → 不重连
  └─ 异常断开 → 指数退避重连
       │
       ├─ 第 1 次：1s 后重连
       ├─ 第 2 次：2s 后重连
       ├─ 第 3 次：4s 后重连
       ├─ 第 4 次：8s 后重连
       ├─ 第 5 次：16s 后重连
       └─ 第 6+ 次：30s 封顶

重连时：
  后端 snapshot_buffer 保留全部历史快照
  → 新 WebSocket 连接先收到全量 buffer
  → 再切换到 live 模式接收新帧
  → 前端无缝恢复
```

### A1.4 刷新页面恢复流程

```
用户刷新 /room/[id]/play
  │
  ├─ 并行请求：
  │    GET /api/rooms/{id}        → RoomRecord
  │    GET /api/rooms/{id}/snapshot → GameState | null
  │
  └─ 三分支判断：
       ├─ winner 已存在 → 渲染终局面板（不连 WS）
       ├─ phase 在 SETUP/GAME_END → 渲染初始状态（不连 WS）
       └─ 对局进行中 → 渲染快照 + 打开 WebSocket 续接
```

---

## A2. 前端核心难点与解决方案

### 难点 1：WebSocket 状态同步的边界情况

| 场景 | 问题 | 解决方案 |
|------|------|----------|
| **刷新页面** | 后端开了新局，旧局丢失 | `/prepare` 端点预分配角色 → 前端 hydrate-first → 再开 WS |
| **WebSocket 断开** | 对局卡死，无法恢复 | 后端 `snapshot_buffer` 缓存全量快照；前端指数退避重连 |
| **重连后重复帧** | 事件列表出现重复 | 后端推送全量 buffer 后切 live 模式；前端用事件 ID 去重 |
| **Stale Closure** | `setTimeout` 里的 `runGame` 捕获旧的 `room=null`，无限递归创建房间 | 改用 `await` 返回值，不用 `setTimeout` + 闭包 |
| **React Strict Mode** | `autoStartedRef` 在双 mount 时失效 | 把 `ref.current = true` 移到 `setTimeout` 内部 |

涉及的问题记录：A4（刷新开新局）、E1（对局卡死）、B5（无限创建房间）

### 难点 2：复杂游戏状态的性能优化

**挑战**：`GameState` 是一个巨大的嵌套对象，每次 WebSocket 推送都是全量替换。

**解决方案**：集中派生，分散消费。

```typescript
function useGameDerivedState(gameState: GameState | null, humanSeat?: number) {
  // 每个 memo 依赖数组尽量窄
  const dayBlocks = useMemo(
    () => groupEventsByDay(gameState?.events),
    [gameState?.events]
  );

  const splitPoint = useMemo(
    () => Math.ceil((gameState?.players?.length || 0) / 2),
    [gameState?.players?.length]
  );

  const badgeCandidateSet = useMemo(
    () => new Set(gameState?.badge?.candidates || []),
    [gameState?.badge?.candidates]
  );
}
```

**为什么不上虚拟滚动**：实际对局事件量有限（200-500 条），虚拟滚动收益小于复杂度成本。

**Context 的 re-render 问题（已知权衡）**：`AppContext` 的 value 对象每次 render 重建，所有消费者 re-render。当前 14 组件规模不是瓶颈；扩展到 50+ 组件会考虑 `useMemo` 包裹 value 或迁移 Zustand。

### 难点 3：阶段动画与业务逻辑解耦

**挑战**：游戏有 20 个 Phase 枚举值，UI 需要在白天/黑夜/结束三种视觉态之间切换。

**核心设计**：三层解耦。

```typescript
// 第一层：20 个 Phase → 3 个 VisualPhaseGroup
const nightPhases = new Set([
  'NIGHT_START', 'NIGHT_GUARD_ACTION', 'NIGHT_WOLF_ACTION',
  'NIGHT_WITCH_ACTION', 'NIGHT_SEER_ACTION', 'NIGHT_RESOLVE'
]);
const dayPhases = new Set([
  'DAY_START', 'DAY_BADGE_SIGNUP', 'DAY_BADGE_SPEECH',
  'DAY_BADGE_ELECTION', 'DAY_SPEECH', 'DAY_VOTE',
  'DAY_RESOLVE', 'DAY_LAST_WORDS', 'DAY_PK_SPEECH',
  'HUNTER_SHOOT', 'WHITE_WOLF_KING_BOOM', 'BADGE_TRANSFER'
]);

function getPhaseGroup(phase?: string): 'day' | 'night' | 'end' | 'other' {
  if (!phase || phase === 'GAME_END') return 'end';
  if (nightPhases.has(phase)) return 'night';
  if (dayPhases.has(phase)) return 'day';
  return 'other';
}

// 第二层：Token 防竞态
function startVisualPhaseTransition(newGroup: VisualPhaseGroup) {
  cancelPhaseTransition(); // token += 1，清空所有旧 timer
  const currentToken = transitionTokenRef.current;

  setTimeout(() => {
    if (transitionTokenRef.current !== currentToken) return; // 被取消了
    // 播放公告 → 切主题 → 淡出公告
  }, 0);
}

// 第三层：reduced-motion 支持
const DURATION = reducedMotion ? 150 : 450;
```

**边界情况**：
- **首次进入就是夜晚**：播放 "身份已分配"（1.2s）→ "天黑请闭眼" → 切 night
- **夜晚直接结束**：强制 `visualPhaseGroup = 'end'`，清空所有 timer
- **连续快速切换**：token 递增使旧回调全部失效

### 难点 4：前后端类型一致性

- 20 个 Phase 枚举值、10 个 ActionType、11 个 EventType、15 个 Role
- **当前方案**：手动维护两份类型定义（`backend/engine/models.py` ↔ `frontend/types/index.ts`）
- **缓解措施**：后端 Role Registry 做 import-time 校验；前端用 optional chaining 防御

### 难点 5：LLM 延迟的前端反馈

- LLM 思考需 3-20 秒，前端不能白屏等待
- 后端在调用 LLM 前先推 `current_speaker_id` 快照 → 前端 PlayerCard 显示脉动 "思考中"
- 80ms 推送间隔确保 UI 至少刷新一次

---

## A3. 个人贡献陈述

### 建议的面试话术

> "我负责了整个前端的架构设计和核心模块实现：

**架构层面**：
- 选型 Next.js App Router + Tailwind CSS，设计了 WebSocket 驱动的单向数据流架构
- 用 React Context 做全局状态管理，URL 同步关键参数
- 设计了 `useRoomStream` / `useGameDerivedState` / `usePhaseTransition` 三层 hook 架构，把数据获取、状态派生和动画编排分离

**核心组件**：实现了 PlayerCard（含角色揭示交互和无障碍支持）、ChatBubble（区分系统消息/玩家发言/自己的发言）、EventTimeline（按天分组 + 死亡摘要 + 事件类型分发）、VoteTargetGrid（响应式网格投票面板）、GameEndPanel（Pointer Events 拖拽浮动按钮 + 结算统计弹窗）等全部游戏 UI 组件

**工程化**：
- 所有组件实现了 ARIA 无障碍属性 + 键盘导航
- 中英双语 i18n 系统
- REST 请求统一 30 秒超时 + 可恢复错误 UI
- WebSocket 指数退避重连
- 阶段动画系统的 token 防竞态 + reduced-motion 支持

**AI 辅助开发**：项目中使用 Claude Code 辅助编程，但架构决策、技术选型、代码审查和质量把控都是我来做的。"

### 关于 AI 辅助的表述建议

> "这个项目中大量使用了 AI 辅助编程。但我的角色不是'让 AI 写代码然后交差'——我负责的是：
> 1. **架构决策**：数据流怎么设计、组件怎么拆分、状态怎么管理
> 2. **质量把控**：每个 AI 生成的组件我都 review 过，确保无障碍、类型安全、边界处理
> 3. **疑难调试**：WebSocket 重连的 stale closure、动画竞态、刷新丢对局——这些复杂 bug 需要人去定位根因
>
> 我们还维护了一个 40KB 的 `DEVELOPMENT_ISSUES.md`，记录了 30+ 个真实踩坑和修复过程。"

---

## A4. 面试官追问预案（前端）

### Q: 为什么不用 Redux/Zustand？

> "当前状态结构比较简单——核心是单个巨大的 `gameState` 对象 + 几个 UI 标志位。React Context + `useMemo` 派生完全够用。已知权衡是 Context value 每次 render 重建导致全量 re-render，当前规模不是瓶颈。扩展到 50+ 组件会考虑 `useMemo` 包裹 value 或迁移 Zustand。"

### Q: 为什么用 WebSocket 而不是 SSE？

> "两个原因：1) 人类玩家模式需要前端提交投票和发言，SSE 是单向的；2) WebSocket 的重连和状态恢复方案更成熟。如果纯 AI 观战（单向），可以考虑 SSE 简化服务端。"

### Q: 怎么保证 AI 写的代码质量？

> "几个层面：1) 规范文件 `skills/30-frontend-conventions.md` 约束；2) TypeScript strict + ESLint + `npm run build` 门禁；3) 人工 review（无障碍、错误边界、null-safe）；4) `DEVELOPMENT_ISSUES.md` 防止重复犯错；5) Playwright 端到端验证。"

### Q: 最有挑战的 bug？

> "刷新页面导致对局丢失（问题 A4）。三层根因：后端 game 对象生命周期管理、WebSocket start 语义模糊、前端 hydration 时序。修了 6 个文件：新增 `/prepare` 端点、拆分 `start`/`restart` action、前端 hydrate-first。教训：服务端是唯一真权威——客户端缓存只能做秒开。"

### Q: 阶段动画的 token 机制？

> "防异步回调竞态的经典模式。每次新 transition token+=1，timer 回调检查 token 是否匹配当前值，不匹配说明有更新的 transition 已发起，丢弃本次回调。和 React 内部 lanes 模型原理类似。"

### Q: 如果重新做，会改什么？

> "1) OpenAPI 自动生成类型；2) 给关键 hook 加单元测试；3) 组件增长后迁移 Zustand。但 MVP 阶段这些方案的成本高于收益——快速验证比架构完美更重要。"

### Q: 最复杂的组件？

> "从实现复杂度看是 `usePhaseTransition` hook，从交互复杂度看是 **PlayerCard**。一个卡片承载了 12 种视觉状态（存活/死亡/发言中/思考中/警长/候选人/角色揭示/队友标记...）+ 完整 ARIA 标注。"

---

---

# Part B — Agent 系统

---

## B1. 设计目标与整体架构

### 核心命题

> **让 7 个 AI 在严格信息隔离下，扮演各自的狼人杀角色，展现出不同的人格和推理方式，产生真实可信、有差异化的对局过程。**

这意味着 Agent 不能是"7 个一模一样的 GPT 在说话"，而必须满足：

1. **信息隔离**：每个 Agent 只能看到自己角色应该知道的信息
2. **角色差异化**：不同角色有不同的胜利条件、行动能力和策略
3. **人格差异化**：同一角色由不同人格扮演，会产生不同的发言和行为
4. **防幻觉**：LLM 不能编造不存在的游戏事件
5. **高可用**：LLM API 不稳定时对局不能中断

### 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    游戏引擎 WerewolfGame                  │
│                                                         │
│  Phase 推进 → _ask(player, request, action_fn)           │
│    │                                                    │
│    ├─ 1. Visibility.for_player(state, id) → PlayerView │
│    ├─ 2. agent.update(view, request)                   │
│    ├─ 3. agent.talk() / vote() / attack() ...          │
│    ├─ 4. ActionValidator.validate(decision)            │
│    └─ 5. 执行 Decision，记录 DecisionAudit              │
│                                                         │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent (Protocol)                       │
│                                                         │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │  LLMAgent   │  │ HeuristicAgent│  │  HumanAgent  │  │
│  │  (主力)      │  │   (兜底)       │  │  (人类玩家)   │  │
│  │             │  │              │  │              │  │
│  │ LLM调用     │  │ 规则引擎      │  │ WebSocket   │  │
│  │ + 人格系统   │  │ + 嫌疑打分    │  │ 等待输入     │  │
│  │ + Prompt工程 │  │ + 角色模板    │  │              │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                │                  │          │
│         │    fallback ──→│                  │          │
│         │   (LLM失败时)   │                  │          │
└─────────┼────────────────┼──────────────────┼──────────┘
          │                │                  │
          ▼                ▼                  ▼
       Decision          Decision          Decision
```

### Agent 协议（Protocol，非 ABC）

```python
class Agent(Protocol):
    def initialize(view: PlayerView, game_setting: dict) -> None: ...
    def update(view: PlayerView, request: str) -> None: ...
    def day_start() -> None: ...
    def talk() -> Decision: ...
    def vote() -> Decision: ...
    def attack() -> Decision: ...
    def divine() -> Decision: ...
    def guard() -> Decision: ...
    def witch_act(victim_id: str) -> list[Decision]: ...
    def shoot() -> Decision: ...
    def boom() -> Decision: ...
    def transfer_badge(candidates: list[str]) -> Decision: ...
    def finish(winner: str) -> None: ...
```

使用 Protocol 而非 ABC：不需要继承关系，只要对象满足接口就能被引擎调用。HeuristicAgent、LLMAgent、HumanAgent 各自独立实现，互不依赖。

---

## B2. 信息隔离 —— 架构级安全保障

**Agent 永远接触不到 `GameState`，只能拿到 `PlayerView`**。

```
Visibility.for_player(state, player_id) → PlayerView {
    self_player: dict,        # private_dict() — 自己的完整信息
    players: list[dict],      # 按角色过滤后的其他玩家信息
    public_events: list[dict],# 所有 visibility="public" 的事件
    private_events: list[dict],# visibility="private" 且该玩家在 visible_to 中
    known_wolves: list[dict], # 仅狼阵营可见
}
```

| 查看者 vs 目标 | 看到什么 |
|---|---|
| 自己看自己 | `private_dict()` — 完整信息（角色、阵营、人格） |
| 狼队友看狼队友 | `private_dict()` — 狼人互相认识 |
| 其他所有情况 | `public_dict()` — 仅公开信息（名字、座位号、存活状态） |

**设计价值**：这不是"靠 Prompt 让 LLM 假装不知道"——这是在**架构层面**物理隔离了信息。即使 LLM 想作弊，它拿到的 `PlayerView` 里根本没有不该看到的数据。

---

## B3. 双层扮演架构（wolfcha 风格）

### 核心思想

**角色（Role）决定"你要赢"，人格（Character）决定"你怎么说话"**。

```
Agent = Role + Character
         │       │
         │       └─ Persona (25 个维度) + PlayerMind (6 个维度)
         │          → 决定说话风格、推理方式、压力反应、桌面表现
         │
         └─ Role (7 个可选角色)
            → 决定胜利条件、行动能力、策略指引
```

### Layer 1: Role（角色层）

每个角色有：
- `ROLE_SYSTEM_PROMPT`：角色定位
- `ACTION_STRATEGIES`：每个行动的策略（talk/vote/attack/divine/guard/shoot/boom）
- `ROLE_PROFILES`：战术画像（table_goal/speech_style/pressure_style/reveal_policy）
- `Playbook`：行动剧本

例如预言家：查验策略"优先查验高影响力位、警长位、主动带节奏位"；投票策略"如果有查杀，优先投票查杀目标"。

### Layer 2: Character（人格层）

#### Persona（25 个维度）

```python
@dataclass
class Persona:
    # 基本信息
    mbti: str              # "INTJ", "ENFP" ...
    name: str              # 林思远, 大壮 ...
    basic_info: str        # 背景故事
    # 说话风格
    vocabulary_style: str  # "学术化" / "大白话" / "极简"
    speech_length_habit: str
    reasoning_style: str   # "逻辑链条式" / "直觉快判"
    # 社交行为
    social_habit: str / humor_style: str
    # 压力应对
    pressure_style: str / uncertainty_style: str
    # 狼人伪装 + 弱点
    wolf_deception_style: str / mistake_pattern: str
    # ... 共 25 个维度
```

#### PlayerMind（6 个维度）

```python
@dataclass
class PlayerMind:
    courage: str             # "bold" / "cautious" / "calculated"
    memory_bias: str         # "recent" / "first_impression" / "comprehensive"
    suspicion_threshold: str # "low" / "medium" / "high"
    self_protection: str     # "aggressive" / "passive" / "sacrificial"
    logic_depth: str         # "shallow" / "moderate" / "deep"
    table_presence: str      # "dominant" / "balanced" / "quiet"
```

### 人格池：30+ 个预定义角色

| 人格 | MBTI | 职业 | 风格标签 | 说话特点 |
|------|------|------|----------|----------|
| 林思远 | INTJ | 数据分析师 | analytical | 用词精准、逻辑链条式 |
| 大壮 | ESTP | 建筑工头 | aggressive | 大白话直球、吼就完了 |
| 赵铁柱 | ISTP | 汽修师傅 | observant | 极简，像修车报告 |
| 苏晓晓 | ESFP | 戏剧学院学生 | expressive | 像在讲故事 |
| 李默 | ISTJ | 会计 | meticulous | 像在做审计报告 |
| 周星野 | ENTP | 脱口秀演员 | provocative | 幽默辛辣 |

### 8 种思维模板（PlayerMind 池）

```
激进直觉型: bold + first_impression + low suspicion + aggressive + shallow + dominant
深度分析型: calculated + comprehensive + medium + passive + deep + balanced
谨慎保守型: cautious + recent + high + sacrificial + moderate + quiet
... 共 8 种
```

### 组合空间

每个 Agent = 1 Persona × 1 PlayerMind × 1 Role = **30+ × 8 × 7 = 1680+ 种可能的玩家画像**。

---

## B4. Prompt 工程详解

### 发言 Prompt（talk）—— System Prompt 分片 + 动态组装

```
┌────────────────────────────────────────────────────┐
│              System Prompt（分片组装）               │
├────────────────────────────────────────────────────┤
│  Part 1 [cacheable]: 身份 + 胜利条件 + 角色策略      │
│  Part 2 [cacheable]: 角色设定（来自 Persona）         │
│  Part 3 [non-cacheable]: 任务描述（按阶段动态变化）    │
│    自由发言 / 警徽竞选 / 遗言                         │
│  Part 4 [cacheable]: 行为特征 <hidden_traits>        │
│    "这轮可以从一个具体的观察切入" ← 每轮随机变化        │
│  Part 5 [cacheable]: 底线规则 + 输出格式              │
│    "绝对不要说「请X号发言」「过」「下一位」"             │
│    "返回 JSON 字符串数组，每个元素是一条消息气泡"       │
├────────────────────────────────────────────────────┤
│              User Prompt                            │
├────────────────────────────────────────────────────┤
│  【当前局势】存活/出局玩家、警长、规则提醒              │
│  【历史】发言摘要 + 投票记录                          │
│  【角色私有信息】查验记录 / 药水状态                   │
│  【本日讨论记录】已发言者内容（最后 10 条）             │
│  【你本日已说过的话】防止重复                         │
│  【发言顺序】"第 M/N 个，上一个 XX 说：..."            │
│  <focus_angle> 动态关注角度                          │
└────────────────────────────────────────────────────┘
```

**关键设计细节**：
1. **Prompt 分片标记 cacheable**：身份、人格、规则标记 `cacheable: True`；任务描述标记 `cacheable: False`
2. **发言顺序感知**：统计已发言/未发言者，传递上一个发言者内容，引导 Agent 回应而非自言自语
3. **JSON 数组输出**：`["第一段", "第二段"]`，每段为独立气泡
4. **每轮随机 mood**：防止同一人格每轮说话节奏完全一样

### 行动决策 Prompt（vote/attack/divine/guard 等）

采用完全不同的**分层信息块**结构：

```
=== 当前状态 ===（玩家列表、存活/死亡、阶段）
=== 角色目标 ===（来自 ROLE_PROFILES）
=== 已发生事实速查 === ← 防幻觉核心！
=== 今日发言记录 ===
=== 本轮关注角度 ===
=== 最近公开事件原始日志 ===（最近 20 条）
=== 你的私有信息 ===（查验/药水/狼队友）
=== 行动策略 ===
=== 反幻觉硬性纪律 ===（5 条硬约束）
请只输出 JSON：{"reasoning": "...", "target": "玩家名字"}
```

---

## B5. 防幻觉多层防御体系

| 层级 | 机制 | 解决的问题 |
|------|------|------------|
| **L1: 事实速查** | 去重+按天分组+截断，标记为"唯一事实来源" | LLM 编造不存在的游戏事件 |
| **L2: 反幻觉纪律** | 5 条硬约束：禁止编造、禁止跨阶段引用、强制 @N号:名字 | 全面行为边界 |
| **L3: System/User 边界** | 自身人设放 system prompt | LLM 把自身设定外溢成对他人观察 |
| **L4: Phase 动态切换** | 当日发言数=0 时禁止评价/怀疑 | 第一天没信息就指控他人 |
| **L5: 遗言独立分支** | 禁止"请X号发言""下一位" | 遗言写"有请@1号发言" |
| **L6: 时间线提示** | Prompt 中加入阶段信息可用性规则 | LLM 不理解时序约束 |
| **L7: 私有信息隔离** | 查验/用药通过 private_events 传递 | LLM 访问不该知道的信息 |
| **L8: Heuristic fallback** | LLM 全部失败后切规则 Agent | API 故障时对局不中断 |

---

## B6. 关注角度系统

`_build_perspective_hints()` 是让 7 个 Agent **说不同话**的关键机制。每次发言前，动态分析游戏状态，最多选 2 条注入 `<focus_angle>`：

```
1. 被点名回应（最高优先级）— 扫描当日发言中的 @N号 引用
2. 座位相邻死者 — 检测环形座位相邻关系
3. 警长关系（奇偶日交替）— 奇数日回应、偶数日质疑
4. 投票一致性（day 2+）— 分析昨日跟票关系
5. 发言位置感知 — 第一个 vs 靠后发言
```

**效果示例**：

```
Agent A（被点名）：回应点名人 + 邻座死者角度
Agent B（警长）：给出方向 + 首发言起手判断
Agent C（跟票者）：提及跟票关系 + 综合回应
```

---

## B7. LLM 调用与重试策略

### 发言的重试策略（3 次渐进式）

```
第 1 次：temperature=1.1（高随机性）, max_tokens=1536
  → JSON 数组解析成功 ✓

第 2 次：temperature=0.9, max_tokens=1536
  追加 "请输出JSON字符串数组"
  → 成功 ✓

第 3 次：raw text fallback
  清洗前缀/引号/代码块，文本 ≥ 2 字符即使用
  → 失败 → HeuristicAgent fallback
```

### 行动决策的重试策略

```
第 1 次：temperature=0.4（低随机性）, max_tokens=640
第 2 次：temperature=0.2, max_tokens=960（1.5x）
第 3 次：temperature=0.1, max_tokens=1600（2.5x）
全部失败 → HeuristicAgent fallback
```

### Timeout 设置的关键教训

- 原始：`timeout=12s` → DeepSeek-v4-flash 内置 CoT 消耗 8-13s → **fallback 率 65%**
- 修复：`timeout=120s`，给两次完整推理链路留足余量 → **fallback 率 0%**

---

## B8. HeuristicAgent 兜底机制

```
每次行动的标准流程：
┌──────────────────────────────────────────┐
│ 1. fallback = self.fallback.attack()     │  ← 预先生成备用决策
│ 2. LLM 调用（最多 3 次重试）               │
│ 3. 成功 → 返回 LLM 决策                   │
│ 4. 失败 → 返回 fallback 决策              │
│    （meta 中标记 source="fallback"）       │
└──────────────────────────────────────────┘
```

HeuristicAgent 核心：嫌疑度打分（投票/发言/死亡关联分析）+ 已知信息追踪 + 角色行为模板 + 人格参数调整。

**效果**：修复前 fallback 率 50-65%，修复后 0%（仅 API 完全不可用时触发）。

---

## B9. 角色定义系统（Role Registry）

### 问题：角色定义散落 7 个文件

加一个新角色需手动改：`models.py` / `rules.py` / `actions.py` / `playbooks.py` / `profiles.py` / `prompts.py` / 前端 `types/index.ts`。漏一处 = KeyError 500。

### 解决方案

```
backend/engine/roles/
  registry.py      → RoleSpec dataclass + ROLE_REGISTRY + register_role()
  basic.py         → Villager
  gods.py          → Seer, Witch, Hunter, Guard
  wolves.py        → Werewolf, WhiteWolfKing
  wolfcha.py       → Idiot
  extensions.py    → 6 个模板角色 (playable=False)
```

**Import-time 校验**：配置引用的角色必须 `playable=True`，漏配 → `import` 时直接 `RuntimeError`（开机硬错）。

**LLM Agent 兜底**：`ROLE_PROFILES.get(self.role, ROLE_PROFILES[Role.VILLAGER])`，新角色缺配也不会炸。

---

## B10. Agent 完整生命周期

```
GAME START
  Factory: create_agents() → 抽取 Persona+PlayerMind → LLMAgent
  engine: agent.initialize(view) → 存储身份 + 角色剧本

EACH PHASE:
  engine: agent.update(view, request) → 更新感知
  夜晚: guard() / attack() / divine() / witch_act()
  白天: talk() → wolfcha 式 Prompt → LLM → 多段发言
        vote() → 分层信息块 Prompt → LLM → Decision
  特殊: shoot() / boom() / transfer_badge()

GAME END:
  engine: agent.finish(winner) → 记录结果
```

### Agent 系统设计亮点总结

| 亮点 | 技术价值 |
|------|----------|
| **信息隔离是架构级的** | 不是"靠 Prompt 假装不知道"，PlayerView 物理隔离 |
| **双层扮演** | Role+Character 独立抽取，1680 种玩家画像 |
| **防幻觉 8 层防御** | 从"经常编造"到"基本可信" |
| **动态关注角度** | 7 个人说不同的话，不会同质化 |
| **Prompt 分片 + 缓存标记** | 支持 LLM prompt caching，降成本 |
| **3 次渐进式重试** | 温度降低 + token 放大，容错性强 |
| **Heuristic 兜底** | API 完全故障时对局不中断 |
| **发言顺序感知** | Agent 学会"回应"而非"自言自语" |
| **Role Registry** | Single source of truth + import-time 校验 |
| **决策审计** | 原始输出/耗时/token/fallback 全记录 |

---

## B11. 面试官追问预案（Agent）

### Q: 为什么用双层扮演而不是单一 Prompt？

> "如果只用角色 Prompt（'你是预言家'），7 个同角色 Agent 说话会一模一样。双层扮演把'战略目标'和'表达风格'解耦——Role 决定你要赢，Character 决定你怎么说话。30+ Persona × 8 PlayerMind × 7 Role = 1680 种组合，每局都是不同的'人物搭配'。"

### Q: 防幻觉体系里最有效的是哪一层？

> "事实速查（L1）和 Phase 动态切换（L4）。事实速查把游戏事件去重、分组、截断，强制 LLM 只从这里引用。Phase 切换解决了最尴尬的问题——第一天没人发言时 LLM 就开始指控别人。统计当日发言数，0 时直接禁止评价和怀疑。"

### Q: LLM 调用失败怎么办？

> "每次行动前先让 HeuristicAgent 生成备用决策。LLM 有 3 次渐进式重试（降温度 + 加 token + 最后 raw text）。全部失败就用备用决策。修复前 fallback 率 65%（timeout 太短 + token 不够），修复后 0%。"

### Q: 30+ 个人格是怎么设计的？

> "参考了 wolfcha 的 Persona + PlayerMind 双接口。Persona 25 个维度覆盖身份背景和表达风格，PlayerMind 6 个维度覆盖思维模式。每个角色有真实职业背景和性格——数据分析师林思远用逻辑链条式推理，建筑工头大壮用大白话直球。这些不是随便编的——每个维度都在 prompt 的特定位置被引用。"

### Q: Role Registry 为什么重要？

> "之前角色定义散落在 7 个文件里，加一个新角色漏改一处就是 KeyError 500。重构后 registry 是 single source of truth，import 时校验 playable 状态——漏配变成开机硬错而非运行时炸。这是'把人会犯的错交给机器检查'的典型案例。"

---

---

# Part C — 综合

---

## C1. 可展示的技术亮点清单

### 第一梯队（必讲）

1. **WebSocket 指数退避重连 + 快照缓冲恢复** — 断线无缝续接
2. **阶段动画的 token 防竞态** — 20 Phase → 3 VisualPhaseGroup + 异步安全
3. **刷新页面不丢对局** — /prepare + hydrate-first + 三分支判断
4. **双层扮演架构** — Role+Character 解耦，1680 种玩家画像
5. **防幻觉 8 层防御体系** — 从 65% fallback 到 0%

### 第二梯队（加分项）

6. **全组件无障碍支持** — ARIA + 键盘 + reduced-motion
7. **中英双语 i18n** — 60+ 翻译键
8. **API 超时与错误恢复** — 30s AbortController + 可恢复 UI
9. **Pointer Events 拖拽** — GameEndPanel 浮动按钮
10. **发言顺序感知** — Agent 学会回应前一个人

### 第三梯队（体现工程素养）

11. **DEVELOPMENT_ISSUES.md** — 40KB、30+ 条问题记录
12. **AI 辅助开发工作流** — 规范约束 + 人工 review
13. **CSS 主题系统** — data-phase 驱动日夜切换
14. **Role Registry** — Single source of truth + import-time 校验
15. **决策审计系统** — DecisionAudit 完整记录每次 LLM 调用

---

## C2. 项目数据一览

### 代码规模

| 指标 | 前端 | Agent/后端 |
|------|------|------------|
| 源文件 | 30+ 个 (.tsx/.ts) | 43 个 (.py) |
| 核心组件 | 14 个 game + 3 个 ui | — |
| 自定义 Hooks | 5 个 | — |
| 角色人格 | — | 30+ Persona + 8 PlayerMind |
| TypeScript 类型 | 15 enum + 12 interface | — |
| i18n 翻译键 | 60+ 个 | — |
| Agent 协议方法 | — | 13 个生命周期方法 |

### 技术覆盖

| 领域 | 涉及内容 |
|------|----------|
| 前端框架 | Next.js 14 App Router, React 18 |
| 前端语言 | TypeScript (strict mode) |
| 样式 | Tailwind CSS, CSS animations, CSS variables |
| 状态管理 | React Context, useMemo, useRef, useLayoutEffect |
| 实时通信 | WebSocket (指数退避重连) |
| 浏览器 API | Pointer Events, matchMedia, AbortController, URLSearchParams |
| 无障碍 | ARIA roles/labels, keyboard navigation, reduced-motion |
| 国际化 | 自研 i18n (中英双语) |
| LLM 集成 | doubao (Seed 2.0) / deepseek (v4 Flash) |
| Prompt 工程 | 分片缓存、动态组装、分层信息块、XML 标签 |
| Agent 架构 | Protocol、双层扮演、信息隔离、兜底机制 |
| 角色系统 | Role Registry、import-time 校验、playable 标记 |
| 工程化 | ESLint, TypeScript strict, Playwright, pytest |

---

## C3. 踩过的关键坑汇总

| 类别 | 数量 | 典型案例 |
|------|------|----------|
| 前端渲染 | 14 个 | 刷新丢对局、日夜切换割裂、Stale Closure 无限创建房间 |
| 后端引擎 | 7 个 | 猎人死亡不开枪、PK 递归 KeyError、发言顺序乱 |
| Agent/LLM | 5 个 | **fallback 率 65%**、场外知识幻觉、开局即互喷、遗言传话筒 |
| WebSocket | 3 个 | 对局卡死、LLM 模式连接失败、重连补帧 |
| 数据库 | 3 个 | 以为在用 PG 实际是 SQLite、SQL 列名臆造 |
| DevOps | 3 个 | uvicorn 反复退出、系统代理污染、缺 --reload |
| Git | 9 个 | 脏 main 恢复、垃圾文件 PR、worktree 基线错 |

### Agent 方向最严重的 5 个坑

1. **LLM fallback 率 65%**（C1）：`max_tokens=320` 被 reasoning 吃光 + `timeout=12s` 太短 → 修复后 0%
2. **LLM 输出场外知识**（C2）：人设放 user prompt 导致误解 → 移至 system prompt + 5 条硬约束
3. **开局即互喷**（C3）：强制要求"指出嫌疑"但 day 1 没信息 → Phase 动态切换
4. **遗言传话筒**（C4）：遗言复用普通发言 prompt → 独立分支
5. **角色定义散落 7 处**（A7）：加角色漏配 KeyError → Role Registry

---

## 附录：关键文件索引

### 前端

| 文件 | 说明 |
|------|------|
| `frontend/hooks/useRoomStream.ts` | WebSocket 连接管理 + 指数退避重连 |
| `frontend/hooks/useGameDerivedState.ts` | Memoized 派生状态计算 |
| `frontend/hooks/usePhaseTransition.ts` | 阶段动画编排 + token 防竞态 |
| `frontend/components/game/PlayerCard.tsx` | 玩家卡片（12 种视觉状态 + 无障碍） |
| `frontend/components/game/EventTimeline.tsx` | 事件时间线（按天分组 + 类型分发） |
| `frontend/components/game/GameEndPanel.tsx` | 结算面板（Pointer Events 拖拽） |
| `frontend/context/AppContext.tsx` | 全局状态 + URL 同步 |
| `frontend/lib/gameApi.ts` | REST API 客户端（30s 超时） |
| `frontend/lib/gamePhase.ts` | Phase → PhaseGroup 分类（Set-based） |
| `frontend/types/index.ts` | 前端类型定义（镜像 Python 模型） |

### Agent / 后端

| 文件 | 行数 | 说明 |
|------|------|------|
| `backend/agents/base.py` | ~80 | Agent 协议定义（Protocol） |
| `backend/agents/llm_agent.py` | ~1523 | LLM Agent 完整实现（核心文件） |
| `backend/agents/characters.py` | ~1062 | 人格系统：Persona + PlayerMind + 30+ 角色池 |
| `backend/agents/prompts.py` | ~254 | 角色提示词 + 行动策略 + 输出格式 |
| `backend/agents/profiles.py` | ~200 | 角色战术画像 |
| `backend/agents/playbooks.py` | ~300 | 角色行动剧本 |
| `backend/agents/heuristic.py` | ~600 | 启发式 Agent（嫌疑打分 + 模板发言） |
| `backend/agents/factory.py` | ~80 | Agent 工厂函数 |
| `backend/engine/visibility.py` | ~80 | 信息隔离层 |
| `backend/engine/roles/registry.py` | ~80 | 角色注册表 |
| `backend/llm/__init__.py` | ~60 | LLM 客户端工厂 |
| `backend/llm/deepseek.py` | ~200 | DeepSeek HTTP 客户端 |

### 规范 / 文档

| 文件 | 说明 |
|------|------|
| `docs/DEVELOPMENT_ISSUES.md` | 开发问题追踪（40KB、30+ 条记录） |
| `skills/30-frontend-conventions.md` | 前端编码规范（12.8KB） |
| `skills/40-agent-development.md` | Agent 开发指南（8.6KB） |

---

*本文档基于 AI Werewolf 项目实际代码、git 历史和开发记录生成。所有技术细节可追溯至具体文件和 commit。*