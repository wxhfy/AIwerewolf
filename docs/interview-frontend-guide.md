# AI Werewolf 前端面试讲述指南

> 生成时间：2026-05-26 | 基于项目实际代码与开发记录

---

## 目录

- [一、项目概述（30 秒版本）](#一项目概述30-秒版本)
- [二、面试讲述框架（3-5 分钟）](#二面试讲述框架3-5-分钟)
- [三、技术架构详解](#三技术架构详解)
- [四、核心难点与解决方案](#四核心难点与解决方案)
- [五、个人贡献陈述](#五个人贡献陈述)
- [六、面试官追问预案](#六面试官追问预案)
- [七、可展示的技术亮点](#七可展示的技术亮点)
- [八、项目数据一览](#八项目数据一览)

---

## 一、项目概述（30 秒版本）

> AI 狼人杀多智能体对战平台的**实时观战前端**。7 个 AI 各扮演一个狼人杀角色（狼人、预言家、女巫等），通过 LLM 推理进行发言和投票。前端基于 **Next.js + TypeScript + Tailwind CSS**，通过 **WebSocket** 实时接收游戏状态推送，以 80ms 帧率渲染完整对局过程。

**一句话定调**：这不是简单的 CURD 应用，而是**实时流式数据驱动的复杂游戏状态渲染系统**。

### 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | Next.js 14 (App Router) |
| 语言 | TypeScript (strict) |
| 样式 | Tailwind CSS + 自定义 CSS 动画 |
| 状态管理 | React Context + useMemo 派生 |
| 实时通信 | WebSocket（指数退避重连） |
| 国际化 | 中英双语（自研 i18n） |
| 无障碍 | ARIA 属性 + 键盘导航 + reduced-motion |
| API 通信 | REST（30s 超时 + 可恢复错误 UI） |

---

## 二、面试讲述框架（3-5 分钟）

### 第 1 分钟：背景与定位

```
"这是一个 AI 狼人杀项目——7 个 AI 各扮演一个角色，
在严格信息隔离下通过 LLM 推理进行发言、投票和使用技能。
我的工作是做观战前端，让用户能实时看到 AI 的完整决策过程。

前端不是简单的展示层——
它要处理实时流式数据、复杂游戏状态渲染、
阶段切换动画、WebSocket 断线恢复等多种工程挑战。"
```

### 第 2-3 分钟：架构设计（建议画图）

```
┌─────────────────────────────────────────────────────┐
│                   Python 游戏引擎                     │
│  WerewolfGame.play() 在独立线程中运行                  │
│  每次状态变更 → observer(state) → 序列化为 dict        │
│                       │                              │
│                       ▼                              │
│              线程安全队列 (asyncio.Queue)              │
│                       │                              │
│                       ▼                              │
│         drain_queue() 每 80ms 消费                    │
│         → WebSocket JSON 推送                        │
│                       │                              │
│                       ▼                              │
│  ┌─────────────────────────────────────────────┐     │
│  │           Next.js 前端                        │     │
│  │                                              │     │
│  │  useRoomStream (WebSocket hook)              │     │
│  │    → 接收 snapshot 消息                       │     │
│  │    → 断线时指数退避重连                        │     │
│  │    → setGameState(msg.state)                 │     │
│  │         │                                    │     │
│  │         ▼                                    │     │
│  │  AppContext (全局状态)                         │     │
│  │    gameState / language / viewMode / room     │     │
│  │         │                                    │     │
│  │         ▼                                    │     │
│  │  useGameDerivedState (memoized 派生)          │     │
│  │    按天分组事件 / 分割玩家列表 / 构建候选人Set    │     │
│  │         │                                    │     │
│  │         ▼                                    │     │
│  │  usePhaseTransition (阶段动画)                 │     │
│  │    业务Phase → 视觉PhaseGroup 映射             │     │
│  │    Token 防竞态 + reduced-motion 支持          │     │
│  │         │                                    │     │
│  │         ▼                                    │     │
│  │  React 组件树渲染                              │     │
│  │    PlayerCard / ChatBubble / EventTimeline    │     │
│  │    VoteTargetGrid / PhaseBanner / GameEndPanel│     │
│  └─────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

**关键设计决策**：
- 后端引擎是**同步**的，跑在 Python 线程里；前端通过 WebSocket 拿的是每 80ms 推送的一帧 **GameState 全量快照**
- 所有组件只读 gameState，不做双向绑定 → **单向数据流**，可预测、易调试
- 派生状态统一走 `useGameDerivedState` 的 `useMemo`，避免组件内重复计算

### 第 3-4 分钟：挑一个难点深讲

**建议选"阶段动画系统"（`usePhaseTransition`）**，这是纯前端技术难点：

```
"最有挑战的是阶段切换动画系统。游戏有 20 个阶段，
在白天和夜晚之间来回切换，UI 需要：

1. 播放全屏公告动画（'天黑请闭眼' / '天亮了'）
2. 同步切换 body 主题色（夜间深蓝 vs 白天暖色）
3. 处理各种边界：
   - 首次进入就是夜晚（不是从白天切过来的）
   - 游戏突然结束（可能是夜晚阶段直接结束）
   - 用户开了系统的 reduced-motion 偏好
   - 快速连续切换时旧动画还没播完

核心设计是三层解耦：

第一层：业务阶段 → 视觉阶段组
  20 个 Phase 枚举 → 3 个 VisualPhaseGroup (day | night | end)
  通过 Set.has() 做 O(1) 映射

第二层：Token 递增防止异步竞态
  每次新 transition 开始时 transitionTokenRef.current += 1
  在 setTimeout 回调里检查 token 是否匹配当前值
  不匹配 → 说明有更新的 transition 已经发起了 → 丢弃本次回调

第三层：reduced-motion 支持
  检测 matchMedia('(prefers-reduced-motion: reduce)')
  动画时长从 450ms 降到 150ms

这个设计的价值：
业务加新阶段不用改动画逻辑，动画加新效果不用碰业务代码。"
```

### 第 4-5 分钟：成果收尾

```
"最终效果：
- 从创建房间 → 角色分配 → 实时观战 → 游戏结算，全流程流畅
- AI 的每句话、每张票都实时推到 UI（80ms 推送间隔）
- WebSocket 断开自动重连（指数退避，1s → 30s 封顶）
- 刷新页面也能恢复到当前对局状态（后端快照缓冲 + 前端 hydrate-first）
- 中英双语、全键盘可访问、reduced-motion 友好"
```

---

## 三、技术架构详解

### 3.1 目录结构

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

### 3.2 数据流

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

### 3.3 WebSocket 重连机制

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

### 3.4 刷新页面恢复流程

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

## 四、核心难点与解决方案

### 难点 1：WebSocket 状态同步的边界情况

| 场景 | 问题 | 解决方案 |
|------|------|----------|
| **刷新页面** | 后端开了新局，旧局丢失 | `/prepare` 端点预分配角色 → 前端 hydrate-first → 再开 WS |
| **WebSocket 断开** | 对局卡死，无法恢复 | 后端 `snapshot_buffer` 缓存全量快照；前端指数退避重连 |
| **重连后重复帧** | 事件列表出现重复 | 后端推送全量 buffer 后切 live 模式；前端用事件 ID 去重 |
| **Stale Closure** | `setTimeout` 里的 `runGame` 捕获旧的 `room=null`，无限递归创建房间 | 改用 `await` 返回值，不用 `setTimeout` + 闭包 |
| **React Strict Mode** | `autoStartedRef` 在双 mount 时失效 | 把 `ref.current = true` 移到 `setTimeout` 内部 |

**涉及的核心问题记录**：`DEVELOPMENT_ISSUES.md` 问题 A4（刷新开新局）、E1（对局卡死）、B5（无限创建房间）

### 难点 2：复杂游戏状态的性能优化

**挑战**：`GameState` 是一个巨大的嵌套对象（玩家列表 × 事件数组 × 投票记录 × 夜晚行动 × 警徽状态 × 每日摘要...），每次 WebSocket 推送都是全量替换。如果每个组件都去遍历/过滤，会产生大量重复计算。

**解决方案**：

```typescript
// useGameDerivedState.ts — 集中派生，分散消费
function useGameDerivedState(gameState: GameState | null, humanSeat?: number) {
  // 每个 memo 依赖数组尽量窄
  const dayBlocks = useMemo(
    () => groupEventsByDay(gameState?.events),
    [gameState?.events]  // 只在事件数组变化时重算
  );

  const splitPoint = useMemo(
    () => Math.ceil((gameState?.players?.length || 0) / 2),
    [gameState?.players?.length]  // 只在玩家数量变化时重算
  );

  const badgeCandidateSet = useMemo(
    () => new Set(gameState?.badge?.candidates || []),
    [gameState?.badge?.candidates]  // O(1) 查找候选人
  );

  // ...
}
```

**为什么不上虚拟滚动**：实际对局事件量有限（一局通常 200-500 条事件），虚拟滚动的收益小于复杂度成本。

**Context 的 re-render 问题（已知权衡）**：`AppContext` 的 value 对象每次 render 都重新创建，会导致所有消费者 re-render。当前规模下不是瓶颈；如果状态更复杂，会考虑 `useMemo` 包裹 value 或迁移到 Zustand。

### 难点 3：阶段动画与业务逻辑解耦

**挑战**：游戏有 20 个 Phase 枚举值，UI 需要在白天/黑夜/结束三种视觉态之间切换。还有全屏公告动画、body 主题色、CSS transition 同步等问题。

**核心设计**：

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

  // 播放公告 → 切主题 → 淡出公告
  setTimeout(() => {
    if (transitionTokenRef.current !== currentToken) return; // 被取消了
    setPhaseAnnouncement({ show: true, ... });
    setTimeout(() => {
      if (transitionTokenRef.current !== currentToken) return;
      setVisualPhaseGroup(newGroup);
      setTimeout(() => {
        if (transitionTokenRef.current !== currentToken) return;
        setPhaseAnnouncement({ show: false, ... });
      }, 800);
    }, 120); // 等 overlay 遮住底层再切主题
  }, 0);
}

// 第三层：reduced-motion
const DURATION = reducedMotion ? 150 : 450;
```

**边界情况处理**：
- **首次进入就是夜晚**：播放 "身份已分配，对局即将开始"（1.2s）→ "天黑请闭眼" → 切 night
- **夜晚阶段直接结束**：强制 `visualPhaseGroup = 'end'`，清空所有 timer，短暂显示 "游戏结束" 后淡出
- **连续快速切换**：token 递增使旧回调全部失效

**涉及的核心问题记录**：`DEVELOPMENT_ISSUES.md` 问题 B10（日夜切换割裂）、B14（首夜无缓冲 + 夜晚终局）

### 难点 4：前后端类型一致性

**挑战**：Python dataclass（后端）和 TypeScript interface（前端）需要保持同步：
- 20 个 Phase 枚举值
- 10 个 ActionType
- 11 个 EventType
- 15 个 Role
- 复杂的嵌套结构（GameState 含 10+ 个子对象）

**当前方案**：手动维护两份类型定义（`backend/engine/models.py` ↔ `frontend/types/index.ts`）

**已知局限**：新增角色/阶段时需同时改两端。理想方案是用 OpenAPI/JSON Schema 自动生成，但 MVP 阶段手动维护更快。

**工程上的缓解措施**：
- `backend/engine/roles/registry.py` 做 single source of truth + import-time 校验，漏配立即抛 RuntimeError
- 后端 `/prepare` 返回的快照确保结构完整，前端用 optional chaining 和 nullish coalescing 防御

### 难点 5：LLM 延迟的前端反馈

**挑战**：LLM 思考需要 3-20 秒，前端不能白屏等待。

**解决方案**：
1. 后端在调用 LLM 前先推一帧 `current_speaker_id` 不为空的快照
2. 前端 `PlayerCard` 检测到自己是 `current_speaker_id` → 显示脉动 "思考中" 状态
3. 80ms 推送间隔确保 UI 至少刷新一次，不会 "卡住"

**涉及的核心问题记录**：`DEVELOPMENT_ISSUES.md` 问题 B1（UI 卡死不推帧）、B4（缺"思考中"反馈）

---

## 五、个人贡献陈述

### 建议的面试话术

> "我负责了整个前端的架构设计和核心模块实现：

**架构层面**：
- 选型 Next.js App Router + Tailwind CSS，设计了 WebSocket 驱动的单向数据流架构
- 用 React Context 做全局状态管理，URL 同步关键参数（语言、视角）
- 设计了 `useRoomStream` / `useGameDerivedState` / `usePhaseTransition` 三层 hook 架构，把数据获取、状态派生和动画编排分离

**核心组件**：实现了 PlayerCard（含角色揭示交互和无障碍支持）、ChatBubble（区分系统消息/玩家发言/自己的发言三种样式）、EventTimeline（按天分组 + 死亡摘要 + 事件类型分发）、VoteTargetGrid（响应式网格投票面板）、GameEndPanel（Pointer Events 拖拽浮动按钮 + 结算统计弹窗）等全部游戏 UI 组件

**工程化**：
- 所有组件实现了 ARIA 无障碍属性 + 键盘导航
- 中英双语 i18n 系统
- REST 请求统一 30 秒超时 + 可恢复错误 UI
- WebSocket 指数退避重连（1s → 30s 封顶）
- 阶段动画系统的 token 防竞态 + reduced-motion 支持

**AI 辅助开发**：项目中使用 Claude Code 辅助编程，但架构决策、技术选型、代码审查和质量把控都是我来做的。这让我能以更高效率交付，同时保持代码质量标准。"

### 贡献量化（参考 git 记录）

| 维度 | 数据 |
|------|------|
| 前端文件 | 30+ 个源文件（组件/hooks/lib/types） |
| 核心组件 | 14 个 game 组件 + 3 个 ui 原子组件 |
| 自定义 hooks | 5 个 |
| 解决的 bug | 14 个前端相关问题（见 DEVELOPMENT_ISSUES.md §B） |
| 语言支持 | 中英双语，60+ 翻译键 |

### 关于 AI 辅助的表述建议

面试时不要回避 AI 辅助的事实，而是把它讲成**工程能力**：

> "这个项目中大量使用了 AI 辅助编程。但我的角色不是'让 AI 写代码然后交差'——我负责的是：
> 1. **架构决策**：数据流怎么设计、组件怎么拆分、状态怎么管理
> 2. **质量把控**：每个 AI 生成的组件我都 review 过，确保无障碍、类型安全、边界处理
> 3. **疑难调试**：WebSocket 重连的 stale closure、动画竞态、刷新丢对局——这些复杂 bug 需要人去定位根因
>
> 我们还维护了一个 40KB 的 `DEVELOPMENT_ISSUES.md`，记录了 30+ 个真实踩坑和修复过程。这本身就体现了工程严谨性。"

---

## 六、面试官追问预案

### Q1: 为什么不用 Redux/Zustand？

> "当前状态结构比较简单——核心是单个巨大的 `gameState` 对象 + 几个 UI 标志位（语言、视角、加载状态）。React Context + `useMemo` 派生完全够用。引入状态管理库在这个规模下是过度工程化。
>
> 已知的权衡：Context value 每次 render 重建会导致所有消费者 re-render。当前在 14 个组件规模下不是瓶颈；如果扩展到 50+ 组件，会考虑 `useMemo` 包裹 value 或迁移到 Zustand。"

### Q2: 为什么用 WebSocket 而不是 SSE？

> "两个原因：
> 1. **双向通信需求**：人类玩家模式需要前端提交投票和发言，SSE 是单向的
> 2. **重连机制**：WebSocket 的重连和状态恢复方案更成熟，我们需要指数退避 + 快照缓冲恢复
>
> 如果未来只需要 AI 观战（纯单向），可以考虑 SSE 简化服务端代码。"

### Q3: 你怎么保证 AI 写的代码质量？

> "几个层面：
> 1. **规范先行**：项目有 `skills/30-frontend-conventions.md`（12.8KB），定义了命名、组件结构、类型使用等规范
> 2. **强制检查**：TypeScript strict 模式 + ESLint + `npm run build` 作为质量门禁
> 3. **人工 review**：每个组件我都检查了无障碍属性（ARIA + 键盘 + reduced-motion）、错误边界、null-safe 处理
> 4. **问题追踪**：`DEVELOPMENT_ISSUES.md` 记录了所有踩过的坑和修复方案，防止重复犯错
> 5. **端到端验证**：用 Playwright 做浏览器验证，确认实际渲染效果"

### Q4: 最有挑战的 bug 是什么？

> "刷新页面导致对局丢失（问题 A4）。这个 bug 的根因有三层：
>
> 1. **后端层**：游戏结束时 `RoomManager` 把 game 对象从 `active_games` 中移除，刷新后重连找不到原 game
> 2. **协议层**：WebSocket 的 `action: "start"` 语义模糊——后端分不清 '首次开局' 和 '重连续接'
> 3. **前端层**：play 页的 hydration 时序不对，先清空状态再等 WS，中间出现空白帧
>
> 修了 6 个文件才彻底解决：
> - 新增 `/prepare` 端点做角色预分配，前端拿到初始快照再跳转
> - WebSocket 拆分 `start` / `restart` 两种 action
> - 前端改为 hydrate-first：先进页渲染快照，再按 winner/phase 决定是否开 WS
>
> **教训**：服务端是唯一真权威——客户端缓存只能做'秒开'，所有恢复路径以后端 snapshot 为准。"

### Q5: 阶段动画的 token 机制是什么意思？

> "这是一个防止异步回调竞态的经典模式。场景是这样的：
>
> 用户快速触发两次阶段切换（比如 day → night → day），每次切换都会调用 `setTimeout`。
> 如果不处理，旧的 timer 回调会在新切换之后执行，导致视觉状态被覆盖回旧值。
>
> 解决方案是维护一个递增的 `transitionTokenRef`：
> 1. 每次 `startVisualPhaseTransition()` 调用时 token += 1
> 2. 把所有 timer 的当前 token 存为局部变量
> 3. 回调执行时检查 `transitionTokenRef.current === currentToken`
> 4. 不匹配 → 说明有更新的 transition 已发起 → 丢弃本次回调
>
> 这和 React 内部处理异步更新的方式原理类似（不过 React 用的是 lanes 模型）。"

### Q6: 如果重新做这个项目，你会改什么？

> "三个改进方向：
>
> 1. **类型生成**：用 OpenAPI 从 Python dataclass 自动生成 TypeScript 类型，消除手动同步的维护成本
> 2. **测试覆盖**：当前前端测试偏弱（主要是手动验证 + Playwright smoke test），应该给关键 hook（`useRoomStream`、`usePhaseTransition`）加上单元测试
> 3. **状态管理**：如果组件数量继续增长，迁移到 Zustand 并用 selector 模式精确订阅，避免 Context 的全局 re-render
>
> 但在 MVP 阶段，这些'更好的方案'的工程成本高于收益。快速验证想法比架构完美更重要。"

### Q7: 这个项目里前端最复杂的组件是哪个？

> "从实现复杂度来看是 `usePhaseTransition` hook，但从交互复杂度来看是 **PlayerCard**。
>
> PlayerCard 需要处理的状态组合非常多：
> - 存活 / 死亡（灰度 + 透明度）
> - 发言中（脉动光环）/ 思考中（信息光环）
> - 警长徽章 / 警长候选人徽章
> - 主持人视角的角色揭示（点击翻牌）
> - 人类玩家是否是狼人队友（显示队友名）
> - 响应式布局下的文字截断（line-clamp-2）
>
> 而且所有这些状态都要有对应的无障碍标注（`aria-label` 读出来 '3号 林思远 预言家 正在发言'）。
> 一个卡片组件承载了 12 种视觉状态 + 完整的 ARIA 标注。"

---

## 七、可展示的技术亮点

面试时主动提及以下亮点（按优先级排序）：

### 第一梯队（必讲）

1. **WebSocket 指数退避重连 + 快照缓冲恢复**
   - 断线不影响对局，重连后无缝续接
   - 后端 `snapshot_buffer` 缓存全量历史帧

2. **阶段动画的 token 防竞态设计**
   - 20 个 Phase → 3 个 VisualPhaseGroup 解耦
   - Token 递增防止异步回调覆盖
   - `prefers-reduced-motion` 媒体查询支持

3. **刷新页面不丢对局**
   - `/prepare` 端点预分配角色
   - 前端 hydrate-first 策略
   - 三分支判断（终局 / 未开始 / 进行中）

### 第二梯队（加分项）

4. **全组件无障碍支持**
   - 所有交互元素有 ARIA 属性（role / aria-label / aria-disabled / aria-pressed / aria-modal）
   - 键盘导航（Enter / Space 触发点击）
   - `prefers-reduced-motion` 缩短动画

5. **中英双语 i18n**
   - 60+ 翻译键覆盖所有 UI 文案
   - 阶段名、角色名、系统消息全双语

6. **API 超时与错误恢复**
   - 所有 REST 请求 30s AbortController 超时
   - 超时错误翻译为中文提示
   - 弹窗打开时隐藏背景错误，避免重复渲染

7. **Pointer Events 拖拽**
   - `GameEndPanel` 用 Pointer Events API 实现可拖拽浮动按钮
   - 3px 死区防止误触
   - `dragRef` 用 useRef 避免拖拽中 re-render

### 第三梯队（体现工程素养）

8. **DEVELOPMENT_ISSUES.md 问题追踪**
   - 40KB、30+ 条问题记录，按现象/根因/方案/教训四段式记录
   - 覆盖引擎、前端、Agent、数据库、WebSocket、DevOps、Git 七个领域
   - 体现系统性的工程复盘习惯

9. **AI 辅助开发的工作流**
   - 用 AI 提效但不依赖 AI 做决策
   - 规范文件（skills/）约束 AI 输出质量
   - 每个 AI 生成的组件都要过人工 review

10. **CSS 主题系统**
    - `data-phase` 属性驱动日夜主题切换
    - 统一 450ms transition
    - 夜幕 overlay、结算金色主题等独立视觉态

---

## 八、项目数据一览

### 代码规模

| 指标 | 数据 |
|------|------|
| 前端源文件 | 30+ 个（.tsx / .ts） |
| 游戏组件 | 14 个 |
| 自定义 Hooks | 5 个 |
| TypeScript 类型 | 15 个 enum + 12 个 interface |
| i18n 翻译键 | 60+ 个（中英双语） |

### 技术覆盖

| 领域 | 涉及内容 |
|------|----------|
| 框架 | Next.js 14 App Router, React 18 |
| 语言 | TypeScript (strict mode) |
| 样式 | Tailwind CSS, CSS animations, CSS variables |
| 状态管理 | React Context, useMemo, useRef, useLayoutEffect |
| 实时通信 | WebSocket (指数退避重连) |
| 浏览器 API | Pointer Events, matchMedia, AbortController, URLSearchParams |
| 无障碍 | ARIA roles/labels, keyboard navigation, reduced-motion |
| 国际化 | 自研 i18n (中英双语) |
| 工程化 | ESLint, TypeScript strict, Playwright smoke test |

### 踩过的坑（来自 DEVELOPMENT_ISSUES.md）

| 类别 | 数量 | 典型案例 |
|------|------|----------|
| 前端渲染 | 14 个 | 刷新丢对局、卡片布局混乱、日夜切换割裂 |
| 后端引擎 | 7 个 | 猎人死亡不开枪、PK 递归 KeyError、发言顺序乱 |
| Agent/LLM | 5 个 | fallback 率 65%、场外知识幻觉、遗言传话筒 |
| WebSocket | 3 个 | 对局卡死、LLM 模式连接失败、重连补帧 |
| 数据库 | 3 个 | 以为在用 PG 实际是 SQLite、SQL 列名臆造 |
| DevOps | 3 个 | uvicorn 反复退出、系统代理污染、缺 --reload |
| Git | 9 个 | 脏 main 恢复、垃圾文件 PR、worktree 基线错 |

---

## 附录：关键文件索引

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
| `docs/DEVELOPMENT_ISSUES.md` | 开发问题追踪（30+ 条记录） |
| `skills/30-frontend-conventions.md` | 前端编码规范 |

---

*本文档基于 AI Werewolf 项目实际代码、git 历史和开发记录生成。所有技术细节可追溯至具体文件和 commit。*