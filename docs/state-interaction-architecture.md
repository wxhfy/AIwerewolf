# 状态同步与前端交互 — 架构设计

> **目标：** 从专业前端工程角度，定义状态分层、同步机制、Hook 组合、交互状态机的标准化设计。
> **当前分支：** `roy/ux-optimization`（2026-06-04）
> **阅读前提：** 已阅读 [`DESIGN.md`](./DESIGN.md)，了解当前 UI 组件树和主题系统。

---

## 1. 状态分层架构

### 1.1 五层模型

```
┌──────────────────────────────────────────────────────────────┐
│ L5: Presentation Layer  (组件渲染)                            │
│     GamePage → StatusBar / EventTimeline / PlayerRail / ...  │
│     职责: 接收派生数据，纯渲染，不持有业务状态                    │
├──────────────────────────────────────────────────────────────┤
│ L4: Derived State Layer (派生计算)                            │
│     useGameDerivedState / useVoteDisplay / useSpeakerStatus   │
│     职责: useMemo 纯计算，输入 → 输出，零副作用                  │
├──────────────────────────────────────────────────────────────┤
│ L3: Coordination Layer (协调层)                               │
│     usePhaseTransition / useTypewriterQueue / useWinnerPanel  │
│     职责: 管理时序、缓冲、状态机转换                             │
├──────────────────────────────────────────────────────────────┤
│ L2: Data Access Layer (数据接入)                              │
│     useGameStream / useRoomAPI                                │
│     职责: WebSocket 生命周期、REST 请求、重连、背压              │
├──────────────────────────────────────────────────────────────┤
│ L1: External Data Sources                                    │
│     WebSocket (streaming snapshots) / REST API (room CRUD)    │
└──────────────────────────────────────────────────────────────┘
```

**铁律：**
- 上层可以 import 下层，反之禁止
- L4 层必须是纯函数/纯 useMemo，不包含 useEffect
- L3 层不直接操作 DOM，只管理状态机
- L2 层是唯一可以调用 `fetch` / `new WebSocket` 的层

### 1.2 对比当前架构

| 维度 | 当前 | 目标 |
|---|---|---|
| Hook 数量 | 1 个 God Hook (35 返回值) | 6–8 个聚焦 Hook |
| 派生逻辑位置 | 混在 Controller 和 page.tsx | 集中在 L4 层 |
| 状态机显式化 | 隐式（if/else + setTimeout） | 显式（typed state + guarded transitions） |
| 测试可用性 | 零（全部耦合 WebSocket + Context） | L4 层可纯函数测试，L3 层可 mock 测试 |
| 投票逻辑 | 3 个组件各自重复计算 | 1 个共享 hook |

---

## 2. Hook 拆分设计

### 2.1 目标架构

```
useGamePage(roomId)                       ← 编排层（唯一顶层 hook）
├── useRoomAPI(roomId)                    ← L2: 房间 CRUD + 重试
├── useGameStream(roomId, params)         ← L2: WebSocket + 背压缓冲
├── usePhaseTransition(                   ← L3: 昼夜转场状态机
│     gameState,
│     hasWinner,
│     reduceMotion?
│   )
├── useTypewriterQueue()                  ← L3: 打字机队列状态机
├── useWinnerPanel()                      ← L3: 游戏结束 UI 状态
├── useGameDerivedState(displayState)     ← L4: 玩家/事件派生
├── useVoteDisplay(gameState, isLocked)   ← L4: 投票 UI 状态派生
├── useSpeakerStatus(gameState)           ← L4: 发言状态派生
└── useAutoScroll(eventCount)             ← UI: 滚动行为
```

### 2.2 各 Hook 契约

#### `useGameStream(roomId, params) → StreamAPI`

```typescript
interface StreamAPI {
  // 输出
  gameState: GameState | null;      // 当前有效快照
  isConnected: boolean;
  error: StreamError | null;

  // 缓冲接口（供 L3 调用）
  bufferSnapshot: (state: GameState) => void;
  getIsBuffering: () => boolean;

  // 控制
  run: (config: RunConfig) => void;
  close: () => void;
}

type StreamError =
  | { type: "CONNECTION_LOST"; attempt: number }
  | { type: "PROTOCOL_ERROR"; message: string }
  | { type: "TIMEOUT" };
```

**关键设计变更：** 当前 `useRoomStream` 直接写 `AppContext.setGameState`。新设计中它只暴露 `gameState` 给调用方，不再穿透到全局 Context。由 `useGamePage` 决定何时写入 Context。

#### `usePhaseTransition(gameState, hasWinner, opts?) → PhaseAPI`

```typescript
interface PhaseAPI {
  // 视觉状态
  visualPhaseGroup: "day" | "night" | "end";
  phaseAnnouncement: PhaseAnnouncementState | null;

  // 转场状态机
  transitionState: TransitionState;
  blinkPhase: BlinkPhase;

  // 数据缓冲（只读）
  displayGameState: GameState | null;  // 冻结态，供 L4 消费

  // 快照缓冲接口（供 L2 调用）
  snapshotBufferRef: React.MutableRefObject<GameState | null>;

  // 完成信号（供 L2 消费）
  flushSignalRef: React.MutableRefObject<GameState | null>;
}

// 显式状态机
type TransitionState =
  | { type: "IDLE" }
  | { type: "ANNOUNCING"; group: PhaseAnnouncementGroup; since: number }
  | { type: "BLINKING"; direction: "closing" | "opening"; startedAt: number }
  | { type: "PAUSED"; since: number }
  | { type: "SETTLING"; target: "day" | "night"; remaining: number };
```

**关键设计变更：** 转场状态机从隐式（多个 useState + setTimeout）变为显式 `TransitionState` 联合类型。每个状态携带必要的上下文，状态转换有明确的 precondition。

#### `useTypewriterQueue() → TypewriterAPI`

```typescript
interface TypewriterQueue {
  // 队列状态
  completedIds: ReadonlySet<string>;
  currentBlockingPhase: string | null;       // 打字机当前卡在哪个阶段
  isBlocked: boolean;                        // true = 有未完成的消息

  // 进度
  totalChatMessages: number;
  completedChatMessages: number;

  // 操作
  markComplete: (eventId: string) => void;   // 标记一条消息完成
  forceUnblock: () => void;                  // 超时强制放行（15s）

  // 超时状态
  stuckDuration: number | null;              // 当前卡了多久（ms）
}
```

**关键设计变更：** `completedIds` 不再直接暴露 mutable Set。改用 `markComplete` 方法封装内部状态更新（Set.add + completedTick 递增）。

#### `useVoteDisplay(gameState, isLocked) → VoteDisplay`

```typescript
type VoteDisplay =
  | { mode: "HIDDEN" }
  | { mode: "LIVE_VOTING";     // VotePanel 实时投票
      votes: Record<string, string>;
      phase: string;
      isBadgeElection: boolean;  // true → 由 BadgePanel 展示
    }
  | { mode: "RESULT";          // VoteResultPanel 汇总
      votes: Record<string, string>;
      day: number;
    };

interface VoteDisplayAPI {
  display: VoteDisplay;
  // 供 BadgePanel 共享的派生数据
  revealedEvents: GameEvent[];
  voteTally: Map<string, { count: number; voters: string[] }>;
}
```

**关键设计变更：** 投票 UI 显示逻辑从 page.tsx 的条件判断和 EventTimeline/BadgePanel 的重复计算中提取出来。三个投票组件只消费 `useVoteDisplay` 的输出。

#### `useSpeakerStatus(gameState) → SpeakerStatus`

```typescript
interface SpeakerStatus {
  title: string;              // 状态栏主文本
  subtitle: string | null;    // 副文本（具体玩家信息）
  mode: "IDLE" | "PENDING_THINKING" | "PENDING_SPEAKING" | "PENDING_ACTING"
      | "PHASE_LABEL" | "WAITING_VOTE" | "SPEECH_IN_PROGRESS";
}
```

提取 `deriveStatusText` 为独立 hook，可单独测试。

---

## 3. 核心状态机

### 3.1 昼夜转场状态机

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
              ┌──────────┐    phase change    ┌────────┴──┐
   session    │          │   detected         │            │
   reset ────→│  IDLE    │───────────────────→│ ANNOUNCING │
              │          │                    │            │
              └──────────┘                    └─────┬──────┘
                    ▲                               │ announce timer
                    │                               │ (1200ms + 400ms fade)
                    │                               ▼
              ┌─────┴──────┐                  ┌──────────┐
              │            │   open complete  │          │
              │  SETTLING  │←─────────────────│ BLINKING │
              │            │                  │          │
              └─────┬──────┘                  └────┬─────┘
                    │                              │
                    │ settling timer               │ close complete
                    │ (night:1100ms/day:600ms)     │
                    ▼                              ▼
              ┌──────────┐                  ┌──────────┐
              │          │                  │          │
              │  IDLE    │                  │  PAUSED  │
              │  + flush │                  │ (150ms)  │
              └──────────┘                  └──────────┘
                                                 │
                                                 │ night: → SETTLING
                                                 │ day: → BLINKING(opening)
                                                 │
```

**状态转换表：**

| From | To | Guard | Action |
|---|---|---|---|
| IDLE | ANNOUNCING | `nextGroup !== prevGroup` | freeze snapshot, show announcement |
| ANNOUNCING | BLINKING(closing) | timer expired (1600ms) | hide announcement, start blink |
| BLINKING(closing) | PAUSED | `onCloseComplete` | set blinkPhase="paused" |
| PAUSED | SETTLING | `onPauseComplete` && target=night | set blinkPhase=null, start settling timer |
| PAUSED | BLINKING(opening) | `onPauseComplete` && target=day | set blinkPhase="opening" |
| BLINKING(opening) | SETTLING | `onOpenComplete` | set blinkPhase=null, start settling timer |
| SETTLING | IDLE | timer expired | flush buffered state, unlock UI |
| ANY | IDLE | sessionKey changed | cancel all timers, reset |

**防止竞态的 Token 模式：**

```typescript
function createTransitionToken(): Token {
  let cancelled = false;
  return {
    get valid() { return !cancelled; },
    cancel() { cancelled = true; },
  };
}

// 使用
function startBlink(next: "day" | "night") {
  const token = createTransitionToken();
  setTimeout(() => {
    if (!token.valid) return;   // ← 如果更新的转场已触发，静默丢弃
    enterState("BLINKING");
  }, 1600);
}
```

### 3.2 打字机队列状态机

```
              ┌──────────┐
              │          │
     reset ──→│  IDLE    │
              │          │
              └────┬─────┘
                   │ new CHAT_MESSAGE event arrives
                   ▼
              ┌──────────┐    onTypewriterComplete
              │          │─────────────────────┐
              │  TYPING  │                     │
              │          │←────────────────────┘
              └────┬─────┘    next CHAT_MESSAGE
                   │          (same phase)
                   │
                   │ all visible CHAT_MESSAGEs completed
                   ▼
              ┌──────────┐
              │          │    phase changed
              │  IDLE    │──────────────────→ ...
              │          │
              └──────────┘

              ┌──────────┐    STUCK_DURATION exceeded (15s)
              │          │─────────────────────────────┐
              │  TYPING  │                             │
              │  (stuck) │←────────────────────────────┘
              └──────────┘    force-complete all
                              pending messages
```

**为什么是队列而不是并行？**

多人发言是顺序的。并行打字机在视觉上混乱，观看者无法同时阅读多个气泡。正确做法：当前气泡完成 → 下一个出现（无动画，直接显示）。

### 3.3 投票展示状态机

```
                          ┌──────────┐
                          │          │
               game reset │  HIDDEN  │
                     ────→│          │
                          └────┬─────┘
                               │
          ┌────────────────────┼──────────────────────┐
          │ phase enters       │ phase enters          │ phase enters
          │ BADGE_ELECTION     │ DAY_VOTE              │ DAY_RESOLVE
          ▼                    ▼                       │ + vote_history populated
    ┌──────────────┐   ┌──────────────┐               ▼
    │              │   │              │         ┌──────────────┐
    │ BADGE_VOTING │   │ LIVE_VOTING  │         │              │
    │ (BadgePanel) │   │ (VotePanel)  │         │   RESULT     │
    │              │   │              │         │ (VoteResult) │
    └──────┬───────┘   └──────┬───────┘         └──────┬───────┘
           │                  │                        │
           │ phase leaves     │ phase leaves           │ new phase OR
           │ BADGE_ELECTION   │ DAY_VOTE               │ scroll away
           ▼                  ▼                        ▼
    ┌──────────────┐   ┌──────────────┐         ┌──────────────┐
    │              │   │              │         │              │
    │   HIDDEN     │   │   HIDDEN     │         │   HIDDEN     │
    │              │   │              │         │              │
    └──────────────┘   └──────────────┘         └──────────────┘
```

**同时显示规则：**
- `BADGE_VOTING` 和 `LIVE_VOTING` 互斥（永远不会同时出现）
- `RESULT` 可以和上述任一并存（但 `isLocked=true` 时不显示）

---

## 4. 状态同步模式

### 4.1 WebSocket 快照与 UI 动画的同步

这是整个系统最核心的同步问题。WebSocket 以 **不可控频率** 推送 `GameState` 快照，UI 动画需要 **1.5–3 秒** 完成转场。

**模式：Snapshot Buffer with Freeze Window**

```
时间轴:
  WS推送:   S0    S1  S2    S3         S4  S5
            │     │   │     │          │   │
  UI状态:   │◄── freeze window ──────►│   │
            │     │   │     │          │   │
  渲染:     S0    S0  S0    S0         S5  S5
            │                          │
            └── 动画开始               └── 动画结束 + flush
```

**实现（伪代码）：**

```typescript
class SnapshotBuffer {
  private frozen: GameState | null = null;
  private pending: GameState | null = null;

  // L2 调用：WebSocket 收到新快照
  onSnapshot(state: GameState): void {
    if (this.isFrozen) {
      this.pending = state;  // 覆盖，只保留最新
    } else {
      this.commit(state);     // 直接提交到渲染
    }
  }

  // L3 调用：转场开始
  freeze(currentState: GameState): void {
    this.frozen = currentState;
  }

  // L3 调用：转场结束
  thaw(): GameState | null {
    this.frozen = null;
    const next = this.pending;
    this.pending = null;
    return next;  // 返回缓冲的最新快照（可能为 null）
  }

  get displayState(): GameState | null {
    return this.frozen ?? this.latestCommitted;
  }

  private get isFrozen(): boolean {
    return this.frozen !== null;
  }
}
```

### 4.2 打字机进度与 "当前阶段" 的同步

**问题：** `gameState.phase` 是后端真实阶段，但前端打字机可能还在播放旧阶段的消息。如果组件直接用 `gameState.phase`，会出现面板与事件流不同步。

**模式：Display Phase（阻塞阶段）**

```typescript
function computeDisplayPhase(
  events: GameEvent[],
  completedIds: ReadonlySet<string>
): string | null {
  let prevActor = "";
  let prevPhase = "";

  for (const event of events) {
    if (event.type !== "CHAT_MESSAGE") continue;

    const actor = event.payload.actor_id || "";
    const ph = event.phase || "";

    // 跳过合并段（与 mergeConsecutiveChats 一致）
    if (actor === prevActor && ph === prevPhase) continue;
    prevActor = actor;
    prevPhase = ph;

    if (!completedIds.has(event.id)) {
      return ph;  // ← 阻塞点：这个阶段的消息还没播完
    }
  }

  return null;  // 全部播完，可使用 gameState.phase
}
```

**消费方：**
- `BadgePanel` 用 `displayPhase || gameState.phase` 判断当前展示
- `EventTimeline` 用 `displayPhase` 判断 revealIndex 边界
- `StatusBar` **不用** displayPhase — 状态栏应反映最新后端状态（发言者）

### 4.3 转场期间的 UI 冻结

| 组件/行为 | 冻结期间行为 | 解冻后行为 |
|---|---|---|
| PlayerRail | 卡片状态冻结（不高亮新发言者） | 接收最新派生状态 |
| EventTimeline | 事件列表冻结（不追加新消息） | 批量追加缓冲期事件 |
| BadgePanel | 面板隐藏或冻结 | 重新计算并显示 |
| VotePanel | 隐藏（投票不应在转场中展示） | 根据最新 phase 决定显示 |
| StatusBar | **不冻结** — 状态栏反映实时后端状态 | — |
| 用户交互 | `pointer-events-none` | 恢复正常 |

---

## 5. 组件通信模式

### 5.1 Prop Drilling vs Context vs Events

| 场景 | 模式 | 理由 |
|---|---|---|
| 页面参数（roomId, mode） | URL params → `useParams()` | Next.js 标准做法 |
| 全局偏好（language, viewMode） | AppContext | 跨页面持久化 |
| 游戏状态（gameState） | AppContext | 多组件消费，WebSocket 单一写入 |
| 派生状态（derived, voteDisplay） | Prop drilling（1 层） | 从 `useGamePage` → `<GamePage>` → 子组件 |
| 打字机完成事件 | Callback prop `onChatComplete` | 单向：ChatBubble → useTypewriterQueue |
| 转场锁状态 | Prop drilling | `isLocked` → EventTimeline, PlayerRail |
| 滚动事件 | Local callback `handleScroll` | 纯 UI，不影响全局状态 |

**原则：Prop drilling 不超过 2 层。超过 2 层 → 提取为子组件的 hook。**

### 5.2 GamePage 编排模式

```tsx
export default function GamePage() {
  const params = useParams<{ id: string }>();
  const game = useGamePage(params.id);

  return (
    <ErrorBoundary>
      <div data-phase={game.phase.visualGroup}>
        {/* L3: 转场动画（覆盖层，z=1500） */}
        <DayNightBlinkTransition
          blinkPhase={game.phase.blinkPhase}
          onCloseComplete={game.phase.onCloseComplete}
        />
        <PhaseOverlayCoordinator
          announcement={game.phase.announcement}
        />

        {/* L5: 顶栏 */}
        <GameHeader
          roomId={game.roomId}
          day={game.state?.day}
          language={app.language}
          canRun={game.actions.canRun}
          onRun={game.actions.run}
        />

        {/* L5: 三栏布局 */}
        <div className="flex flex-1">
          <PlayerRail side="left" state={game.derived.left} />
          <MainColumn>
            <StatusBar status={game.speaker.status} />
            <BadgePanel display={game.vote.badge} />
            <VotePanel display={game.vote.live} />
            <VoteResultPanel display={game.vote.result} />
            <EventTimeline
              dayBlocks={game.derived.dayBlocks}
              completedIds={game.typewriter.completedIds}
              onChatComplete={game.typewriter.markComplete}
            />
          </MainColumn>
          <PlayerRail side="right" state={game.derived.right} />
        </div>

        <GameEndPanel state={game.winner} />
      </div>
    </ErrorBoundary>
  );
}
```

**page.tsx 只做编排：** 每个子组件接收明确的、类型安全的 props，不自行计算业务逻辑。

---

## 6. 错误处理策略

### 6.1 分层错误边界

```
<ErrorBoundary fallback={<GameCrash />}>          ← L0: 整页级
  <ErrorBoundary fallback={<HeaderSkeleton />}>    ← L1: 顶栏级
    <GameHeader />
  </ErrorBoundary>
  <div className="flex-1">
    <ErrorBoundary fallback={<RailSkeleton />}>    ← L1: PlayerRail 级
      <PlayerRail side="left" />
    </ErrorBoundary>
    <ErrorBoundary fallback={<TimelineSkeleton />}> ← L1: 时间线级
      <EventTimeline />
    </ErrorBoundary>
    <ErrorBoundary fallback={<RailSkeleton />}>
      <PlayerRail side="right" />
    </ErrorBoundary>
  </div>
</ErrorBoundary>
```

### 6.2 错误分类

| 错误类型 | 来源 | 恢复策略 |
|---|---|---|
| WebSocket 断开 | L2 useGameStream | 自动重连（指数退避，max 30s），状态栏提示 |
| WebSocket 协议错误 | L2 useGameStream | 显示错误 toast，手动重试按钮 |
| REST API 超时 | L2 useRoomAPI | 重试按钮 |
| 打字机超时（15s 无进展） | L3 useTypewriterQueue | 强制完成当前阶段所有消息 |
| 组件渲染崩溃 | L5 任意组件 | ErrorBoundary 捕获，显示降级 UI |
| 无效 gameState | L3 usePhaseTransition | 跳过处理，保持当前状态 |

---

## 7. 可测试性设计

### 7.1 测试策略矩阵

| 层级 | 测试类型 | Mock 范围 | 示例 |
|---|---|---|---|
| L4 派生层 | 纯函数单测 | 无 mock | `computeDisplayPhase(events, completedIds)` |
| L3 协调层 | Hook 集成测试 | mock L2 输入 | `usePhaseTransition(mockState, false)` |
| L2 数据层 | 集成测试 | mock WebSocket/REST | `useGameStream(roomId)` with MSW |
| L5 渲染层 | 组件测试 | mock 所有 props | `<PlayerCard player={mockPlayer} />` |
| 端到端 | E2E (Playwright) | 真实后端 | 完整一局 AI 对战 |

### 7.2 依赖注入点

```typescript
// 当前：硬编码依赖
function usePhaseTransition(sessionKey, gameState, hasWinner) {
  const reduceMotion = window.matchMedia("...").matches;  // ← 不可 mock
  // ...
}

// 改进：可注入
function usePhaseTransition(
  sessionKey: string,
  gameState: GameState | null,
  hasWinner: boolean,
  deps: {
    reduceMotion: () => boolean;       // 默认: window.matchMedia
    scheduleTimeout: typeof setTimeout; // 默认: globalThis.setTimeout
  } = defaultDeps
) { ... }
```

---

## 8. 迁移路径

### 8.1 阶段 1：无破坏性清理（本次可做）

| 步骤 | 动作 | 影响 |
|---|---|---|
| 1 | `git rm PhaseBanner.tsx DayBlock.tsx` | 无影响（死代码） |
| 2 | 提取 `deriveStatusText` → `lib/deriveStatusText.ts` | page.tsx 减 170 行 |
| 3 | 提取 `useVoteDisplay` hook | 消除 BadgePanel/VotePanel/EventTimeline 重复逻辑 |
| 4 | BadgePanel 改用共享 hook | 不影响渲染结果 |

### 8.2 阶段 2：Hook 拆分（需要测试验证）

| 步骤 | 动作 | 风险 |
|---|---|---|
| 5 | `useGamePageController` → 拆出 `useTypewriterQueue` | 中（打字机核心逻辑） |
| 6 | `useGamePageController` → 拆出 `useWinnerPanel` | 低（独立功能） |
| 7 | 引入 `TransitionState` 显式状态机替代多 useState | 高（转场核心，需完整回归测试） |
| 8 | `useRoomStream` → 重构为 `useGameStream`（不直接写 Context） | 中（数据流改动） |

### 8.3 阶段 3：架构升级（稳定性优先，可择机进行）

| 步骤 | 动作 |
|---|---|
| 9 | 引入组件级 ErrorBoundary |
| 10 | 添加 L4 层纯函数单测 |
| 11 | 引入 `useSyncedRef` 消除 state/ref 双生 |

---

## 9. 与现有设计的对比

| 设计要素 | 当前实现 | 提案设计 | 收益 |
|---|---|---|---|
| 转场状态 | 6 个独立 useState + 隐式 setTimeout 链 | 1 个 `TransitionState` 联合类型 | 可穷举、可测试、可调试（DevTools 中一目了然） |
| 打字机 | `completedIds` Set + `completedTick` 版本号 | `useTypewriterQueue` 封装 | 隔离变化，防止直接操作内部 Set |
| 投票 | 3 个组件各自计算 `revealedEvents` | `useVoteDisplay` 共享 hook | 消除 ~80 行重复代码 |
| 数据流 | `useRoomStream` 穿透写 Context | `useGameStream` 返回 + `useGamePage` 决定写 Context | L2 可独立测试，无全局副作用 |
| 错误处理 | 1 个全局 ErrorBoundary | 分层 ErrorBoundary + 分类错误 | 组件级降级，不白屏 |
| Hook 大小 | 1 个返回 35 字段 | 8 个各返回 4–8 字段 | 每个 hook 可独立理解和测试 |
