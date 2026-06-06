# AI Werewolf — 前端 UI 设计文档

> 基于 `roy/ux-optimization` 分支当前代码（2026-06-04）
> 本文档描述 UI 架构、组件树、数据流、动画时序和关键设计决策。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  Next.js 14 App Router (pages/)                         │
│  ├─ page.tsx              — 大厅（创建房间/开始对局）      │
│  ├─ room/[id]/play/       — AI 对战观战页（主战场）        │
│  ├─ room/[id]/human/      — 真人参与页                    │
│  ├─ games/[id]/report/    — 复盘报告页                    │
│  └─ evolution/            — 进化看板                      │
├─────────────────────────────────────────────────────────┤
│  Context (AppContext)                                    │
│  ├─ language / viewMode / agentType                      │
│  ├─ room / gameState / isPlaying                         │
│  └─ speed / seed                                         │
├─────────────────────────────────────────────────────────┤
│  Hooks (业务逻辑层)                                       │
│  ├─ useGamePageController  — 游戏页总控（组合所有子hook）  │
│  ├─ usePhaseTransition     — 昼夜转场动画协调器            │
│  ├─ useRoomStream          — WebSocket 通信管理           │
│  ├─ useGameDerivedState    — 衍生状态计算（发言者/狼队友等）│
│  ├─ useAutoScroll          — 事件区自动滚动               │
│  ├─ useTypewriter          — 打字机逐字播放               │
│  └─ useHumanDisplayState   — 真人模式显示状态派生          │
├─────────────────────────────────────────────────────────┤
│  Components (UI 组件层)                                   │
│  ├─ game/   — 游戏核心组件（见 §3 组件树）                 │
│  └─ ui/     — 基础 UI 组件（Button/Card/Badge/ErrorBoun…）│
└─────────────────────────────────────────────────────────┘
```

---

## 2. 页面路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | `app/page.tsx` | 大厅：配置游戏参数、创建房间、启动对局 |
| `/room/[id]/play?mode=ai` | `app/room/[id]/play/page.tsx` | AI 对战观战页（核心页面） |
| `/room/[id]/play?mode=human&human_seat=N` | 同上 | 真人参与模式 |
| `/room/[id]/human` | `app/room/[id]/human/page.tsx` | 真人模式独立页面 |
| `/games/[id]/report` | `app/games/[id]/report/page.tsx` | 复盘报告 |
| `/evolution` | `app/evolution/page.tsx` | 进化看板 |

---

## 3. 组件树（主力页面：`room/[id]/play`）

```
GamePage
├── DayNightBlinkTransition        ← 昼夜眨眼转场（z=1500，覆盖全屏）
├── PhaseOverlayCoordinator        ← 协调 DramaticOverlay + PhaseAnnouncement
│   ├── DramaticOverlay            ← 死亡/淘汰戏剧化蒙层
│   └── PhaseAnnouncement          ← "天黑请闭眼"/"天亮了" 全屏公告
├── [fetchError 面板]              ← z=1100 错误重试弹层
├── GameHeader                     ← 顶栏：房间ID / 天数 / 视角切换 / Run按钮
├── MobilePlayerRail               ← 移动端底部玩家横滚条（<lg 可见）
├── <flex-1 三栏布局>
│   ├── PlayerRail (left)          ← 左列：座位 1~N/2 的玩家卡片
│   ├── <main 中列>
│   │   ├── StatusBar              ← 状态栏（"X号 YYY 发言中"）
│   │   ├── BadgePanel            ← 警徽竞选面板（发言进度 + 投票统计）
│   │   ├── VotePanel             ← 放逐投票实时面板（进度条 + 投票关系）
│   │   ├── VoteResultPanel       ← 投票结果汇总（柱状图，投票完成后显示）
│   │   ├── <scrollable div>      ← 可滚动事件区
│   │   │   ├── EventTimeline     ← 事件时间线（按天分组）
│   │   │   │   └── DayEventBlock ← 单天事件块（EventTimeline.tsx 内联函数）
│   │   │   │       ├── 天标头
│   │   │   │       ├── 狼队商议（inline）
│   │   │   │       └── TimelineEvent（内联函数，循环渲染每条事件）
│   │   │   │           ├── ChatBubble     ← 发言气泡（打字机动画）
│   │   │   │           ├── EventItem      ← 系统/行动事件
│   │   │   │           └── (VOTE_CAST → null, 由上方面板展示)
│   │   │   └── ThinkingBubble     ← AI 思考中动画
│   │   └── ActionPanel            ← 真人模式操作面板（发言/投票/目标选择）
│   └── PlayerRail (right)         ← 右列：座位 N/2+1~N 的玩家卡片
├── GameEndPanel                   ← 游戏结束浮窗（可拖拽的结算球）
```

---

## 4. 布局系统

### 三栏布局（桌面端 ≥1024px）

```
┌────────────┬──────────────────────────┬────────────┐
│ PlayerRail │  StatusBar               │ PlayerRail │
│  (left)    │  BadgePanel              │  (right)   │
│  w=21%     │  VotePanel               │  w=21%     │
│            │  VoteResultPanel         │            │
│            │  ┌────────────────────┐  │            │
│            │  │ EventTimeline      │  │            │
│            │  │ (scrollable,flex-1)│  │            │
│            │  └────────────────────┘  │            │
│            │  ActionPanel (if human)  │            │
└────────────┴──────────────────────────┴────────────┘
```

- **PlayerRail**: 固定宽度 21%，min-width 150px，内部可滚动。左侧座位 1~N/2，右侧座位 N/2+1~N。
- **中列 (main)**: flex-1，最小宽度 0（防止溢出）。上方固定面板（StatusBar/BadgePanel/VotePanel），下方 EventTimeline 占用剩余空间并滚动。
- **移动端 (<1024px)**: PlayerRail 隐藏，改为 MobilePlayerRail（底部横滚条）。

### 数据来源
- `splitPoint = Math.ceil(players.length / 2)` — 在 `useGameDerivedState` 中计算
- `leftPlayers = seat ≤ splitPoint`, `rightPlayers = seat > splitPoint`

---

## 5. 主题系统（Day/Night/End 三态切换）

通过 `<html data-phase="...">` 属性驱动 CSS 变量切换，**无需 JS 逐组件传色**。

### CSS 变量（定义在 `globals.css` `:root`）

| 变量 | Day | Night | End |
|---|---|---|---|
| `--color-bg` | `#F8F5F0` 素雅米白 | `#0F0E0C` 深黑 | `#F6F0E3` 暖金 |
| `--color-card` | `#FAF7F2` | `#1C1A17` | `#FFF9EC` |
| `--color-primary` | `#8B5A2B` 棕 | `#E8C84A` 金 | `#9A6A12` 暖棕 |
| `--color-text` | `#2D2A24` | `#F5F0E8` | `#2F2617` |
| `--color-border` | `rgba(139,90,43,0.1)` | `rgba(212,175,55,0.15)` | `rgba(154,106,18,0.18)` |

### 切换机制

```typescript
// usePhaseTransition.ts → useLayoutEffect
document.documentElement.setAttribute("data-phase", visualPhaseGroup);
// visualPhaseGroup ∈ {"day" | "night" | "end"}
```

### 过渡动画

所有 `[data-phase-aware]` 容器自动获得 CSS transition：
```css
[data-phase-aware] {
  transition: background-color 450ms ease-in-out,
              color 450ms ease-in-out,
              border-color 450ms ease-in-out;
}
```

### 星空效果

夜晚模式自动显示 CSS 星空粒子：
```css
.night-stars::before { /* radial-gradient 星星 */ }
[data-phase="night"] .night-stars::before { opacity: 1; }
```

---

## 6. 昼夜转场动画系统（最复杂的子系统）

### 架构

```
usePhaseTransition (hook)            ← 中央协调器
  ├─ 检测 gameState.phase → PhaseGroup 变化
  ├─ 管理 BlinkPhase 状态机
  ├─ 管理 PhaseAnnouncement 显示/隐藏
  ├─ 管理 isTransitioning 锁（冻结 UI）
  └─ 管理 frozenState/pendingState 缓冲

DayNightBlinkTransition (component)  ← 纯渲染，接收 blinkPhase
PhaseAnnouncement (component)        ← 全屏文字公告
PhaseOverlayCoordinator (component)  ← 协调 DramaticOverlay 与 PhaseAnnouncement 优先级
```

### BlinkPhase 状态机

```
null ──→ "closing" ──→ "paused" ──→ "opening" ──→ null
                (350ms)     (150ms)      (450ms)

Day→Night: closing → paused → _finishBlink("night")
Night→Day: closing → paused → opening → _finishBlink("day")
```

### 完整时序（修复后 v2）

**Day → Night（白天→黑夜）：**

```
t=0      显示 "天黑请闭眼" 全屏公告（opacity 1.0）
t=1200   公告开始淡出（opacity → 0, 400ms）
t=1600   公告移除 → 眨眼动画启动（closing, 350ms）
t=1950   闭眼完成 → pause（全黑停顿, 150ms）
t=2100   _finishBlink("night"):
           - blinkPhase = null, isBlinking = false
           - 保持 isTransitioning = true（settling 期 1000ms + 100ms 缓冲）
t=3200   isTransitioning = false → UI 解锁 → 事件渲染
```

**Night → Day（黑夜→白天）：**

```
t=0      显示 "天亮了" 全屏公告（opacity 1.0）
t=1200   公告淡出
t=1600   眨眼动画启动（closing → paused → opening, 共 950ms）
t=2550   _finishBlink("day"):
           - 保持 isTransitioning = true（settling 期 500ms + 100ms 缓冲）
t=3150   isTransitioning = false → UI 解锁
```

**首次入场（准备→第一夜）：**

```
t=0      显示 "身份已分配，对局即将开始"（ready, 1000ms）
t=1400   显示 "天黑请闭眼"（night, 公告持续 1200ms）
t=2600   公告淡出开始（400ms）
t=3000   公告移除 → 眨眼动画启动（closing, 350ms）
t=3350   闭眼完成 → pause（全黑停顿, 150ms）
t=3500   _finishBlink("night"):
           - blinkPhase = null, isBlinking = false
           - 保持 isTransitioning = true（settling 期 1000ms+100ms缓冲）
t=4600   isTransitioning = false → UI 解锁 → 事件渲染
```

### 转场锁机制

转场期间（`isBlinking || isTransitioning === true`）：

| 行为 | 状态 |
|---|---|
| `displayGameState` | 返回冻结的旧状态（`frozenStateRef`） |
| WebSocket 快照 | 缓冲到 `pendingStateRef`（只保留最新一份） |
| 事件时间线渲染 | 暂停（旧数据保持显示） |
| PlayerRail 高亮 | 暂停更新 |
| 用户交互（VotePanel/ActionPanel） | `pointer-events-none` |

### 动画参数

| 参数 | 值 | 说明 |
|---|---|---|
| `ANNOUNCE_DISPLAY_MS` | 1200ms | 公告阅读时间 |
| `ANNOUNCE_FADE_MS` | 400ms | 公告淡出时间 |
| `CLOSE_DURATION` | 0.35s | 闭眼动画时长 |
| `PAUSE_DURATION` | 150ms | 全黑停顿 |
| `OPEN_DURATION` | 0.45s | 睁眼动画时长 |
| `SETTLE_NIGHT` | 1000ms | 黑夜 settling 期（实际释放 +100ms=1100ms） |
| `SETTLE_DAY` | 500ms | 白天 settling 期（实际释放 +100ms=600ms） |
| — | +100ms | `_finishBlink` setTimeout 统一追加的缓冲量 |

### reduced-motion 降级

当系统偏好 `prefers-reduced-motion: reduce` 时：
- 跳过眨眼动画
- 只显示阶段公告（`showAnnouncement`）
- 公告结束后直接切换视觉阶段
- 全局 CSS：所有 animation/transition 降为 1ms

---

## 7. 事件时间线 & 打字机系统

### EventTimeline 架构

```
EventTimeline
  └── DayEventBlock（按 day 分组）
        ├── 天标头（🌅 第 N 天）
        ├── 狼队商议区（inline, 仅当天 + 有 NIGHT_WOLF 阶段）
        │     ├── 🐺 商议中
        │     ├── ▸ P1 选择击杀 3 号
        │     └── ✓ 最终决定击杀 3 号 XXX
        └── TimelineEvent（按 revealIndex 逐个展示）
              ├── ChatBubble     ← 发言气泡（打字机逐字播放）
              ├── EventItem      ← NIGHT_ACTION / PLAYER_DIED 等
              ├── PHASE_CHANGED  ← 系统阶段消息
              └── VOTE_CAST      → null（不在时间线内展示）
```

### 打字机逐字播放（Typewriter）

`ChatBubble` 组件在 `animate=true` 时启动打字机效果：
- 由 `useTypewriter` hook 驱动（`requestAnimationFrame` 循环）
- 默认 35 字符/秒（约 28.6ms/字符）
- 播放完成后调用 `onChatComplete(eventId)` → 将 eventId 加入 `completedIds` Set
- `completedIds` 的变化触发 `revealIndex` 前进 → 解锁下一条消息

### revealIndex 机制

```typescript
// 找到第一个未完成的 CHAT_MESSAGE，前面的全部可见
let revealIndex = timelineEvents.length;
for (let i = 0; i < timelineEvents.length; i++) {
  if (e.type === CHAT_MESSAGE && !completedIds.has(e.id)) {
    revealIndex = i; break;
  }
}
visibleEvents = timelineEvents.slice(0, revealIndex + 1);
```

- **CHAT_MESSAGE** 事件逐个解锁（打字机完成一个才显示下一个）
- **系统/行动事件** 批量出现（不单独阻塞队列）

### 连续发言合并（mergeConsecutiveChats）

同一玩家在同一 phase 的连续 CHAT_MESSAGE 会被合并为一个气泡，避免 AI 分段输出时出现多个重复头像。

---

## 8. 投票系统

### 组件职责分离

| 组件 | 触发阶段 | 位置 | 职责 |
|---|---|---|---|
| **BadgePanel** | `DAY_BADGE_SPEECH` / `DAY_BADGE_SIGNUP` / `DAY_BADGE_ELECTION` | 滚动区上方 | 警徽竞选发言进度 + 候选人票数 |
| **VotePanel** | `DAY_VOTE` / `DAY_PK_SPEECH投票`（排除 BADGE） | 滚动区上方 | 放逐投票实时进度（进度条 + 投票关系卡片） |
| **VoteResultPanel** | 投票完成后（`vote_history` 存在） | 滚动区上方 | 投票结果柱状图汇总（始终可见，不沉底） |

### 数据来源

```
实时投票:  gameState.votes       ← 当前阶段投票（阶段切换后清空）
历史投票:  gameState.vote_history ← Record<day, Record<voter→target>>
警徽投票:  gameState.badge.votes  ← 使用 badge 子对象
```

### VoteResultPanel 显示逻辑（修复后）

```typescript
// 从 vote_history 取最新一天且有数据的投票结果
const latestDayWithVotes = Math.max(...Object.keys(voteHistory).map(Number));
const showVoteResult =
  latestCompletedVotes && Object.keys(latestCompletedVotes).length > 0 &&
  !isVotePanelVisible &&           // 不与实时投票面板重叠
  !controller.isTransitioning;     // 转场期间不显示
```

---

## 9. 数据流

> 简图。完整状态流转（含背压机制、flush 路径、ref/state 分工）见 [§13 状态管理](#13-状态管理)。

### WebSocket → Context → Hooks → Components

```
WebSocket message
  │  blink 期间 → bufferSnapshot  (pendingStateRef)
  │  正常期间   → setGameState    (AppContext)
  ▼
AppContext.gameState ──── usePhaseTransition ──→ displayGameState ──→ useGameDerivedState
  ▲                            │                                           │
  │                            └── flushResultRef (转场结束回写)              │
  │                                                                         ▼
  └──────────── useGamePageController ◄────────────────────────── derived state → Components
```

### PendingInput → StatusBar

```typescript
deriveStatusText(gameState, language):
  if pending_input && pending.phase === gameState.phase:  // 阶段校验（修复后）
    → "X号 XXX 发言中" / "思考中" / "投票中" / "行动中"
  elif NIGHT_*:
    → tPhaseStatus(phase)  // "守卫行动中" 等
  elif DAY_*:
    if VOTE phase: → "等待 X号 XXX 投票"
    elif SPEECH phase: → current_speaker_id → "X号 XXX 发言中"
    else: → tPhaseStatus(phase)
```

---

## 10. 玩家卡片系统（PlayerCard）

### 状态指示

| 状态 | 视觉表现 |
|---|---|
| **发言中** (pendingInput) | 绿色脉冲光环 + ✓ 标记 |
| **思考中** (activeSpeakerId) | 思考气泡动画 |
| **已发言** (spokenInPhase) | "已发言" 文字标记（灰色） |
| **警长** (sheriffId) | 金色警徽边框 + ☆ 标记 |
| **警徽候选人** (badgeCandidateSet) | 金色虚线边框 |
| **死亡** (!alive) | 黑白滤镜 + 灰底 |
| **狼队友** (humanMode) | 🐺 标记 |

### 显示模式

| 模式 | 角色可见 | 身份标签 |
|---|---|---|
| 公开视角 (PUBLIC) | 所有人隐藏 | "身份隐藏" |
| 主持视角 (MODERATOR) | 揭示所有角色 | 角色名 + 阵营色 |
| 真人模式 (humanMode) | 仅自己可见 | 显示自己的角色 |

---

## 11. 国际化（i18n）

### 架构

```typescript
// lib/i18n.ts
translations = { [Language.ZH]: {...}, [Language.EN]: {...} }

t(key, language)        // 静态翻译
format(template, values) // 参数化翻译 "{name} 发言中"
tRole(role, language)   // 角色名翻译
tPhase(phase, language) // 阶段名翻译（叙述性）
tPhaseStatus(phase, language) // 阶段状态翻译（实时动作）
```

### 翻译覆盖

- 游戏 UI：标题、按钮、标签
- 阶段名称：叙述性（如 "天黑请闭眼"）vs 实时动作（如 "守卫行动中"）
- 角色名称：8 种基础角色 + 6 种模板角色
- 狼队商议：商议中 / 投票 / 最终决定

---

## 12. 动画系统

### 动画清单

| 动画 | 实现方式 | 时长 |
|---|---|---|
| DayNightBlinkTransition | Framer Motion (motion.div) | 350ms close + 150ms pause + 450ms open |
| PhaseAnnouncement 淡入淡出 | CSS transition (opacity, scale) | 400ms fade |
| 星空粒子 (night) | CSS radial-gradient + opacity transition | 800ms |
| 主题色切换 | CSS transition on [data-phase-aware] | 450ms |
| ChatBubble 打字机 | requestAnimationFrame 逐字输出 | 35 字符/秒（≈28.6ms/char） |
| VoteResultPanel 柱状图 | CSS transition (width) | 700ms ease-out |
| PlayerCard 发言脉冲 | Tailwind `animate-[pulse_1s_ease-in-out_infinite]` | 1s infinite |
| 加载 spinner | CSS animation (spin) | 1s infinite |
| 思考气泡 (ThinkingBubble) | CSS animation (dotPulse) | 1.4s staggered |

### Framer Motion vs CSS

| 技术 | 场景 |
|---|---|
| **Framer Motion** (`motion/react`) | DayNightBlinkTransition（复杂时序链） |
| **CSS transition** | 主题色切换、面板淡入 |
| **CSS animation** | 脉冲（PlayerCard `pulse 1s`）、加载 spinner、思考气泡 dotPulse；GameEndPanel 奖杯 `breathe 2s` |
| **requestAnimationFrame** | 打字机（精确逐字控制） |

---

## 13. 状态管理

> **核心复杂度**不在 AppContext（10 个字段），而在 **4 个 hooks 层共计 30+ 个状态/ref**，以及它们之间的协调时序。

### 13.1 状态全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                      状态所有权分布                                │
├──────────────────────────────────────────────────────────────────┤
│ AppContext (10)                                                   │
│   language / viewMode / agentType / room / gameState /           │
│   isConnected / isPlaying / speed / seed                          │
├──────────────────────────────────────────────────────────────────┤
│ usePhaseTransition (6 state + 13 ref)                             │
│   state: visualPhaseGroup / phaseAnnouncement / isBlinking /     │
│          blinkPhase / isTransitioning                             │
│   ref:   frozenStateRef / pendingStateRef / flushResultRef /     │
│          transitionTokenRef / targetPhaseRef / lastPhaseGroupRef… │
├──────────────────────────────────────────────────────────────────┤
│ useGamePageController (5 state + 8 ref)                           │
│   state: showWinnerPanel / fetchError / completedTick /          │
│          phaseTimeoutTick / ballPos / statusTitle                 │
│   ref:   completedIds(Set) / winnerShownRef / autoStartedRef /   │
│          latestGameStateRef / phaseFirstSeenRef / dragRef         │
├──────────────────────────────────────────────────────────────────┤
│ useRoomStream (0 state + 3 ref)                                   │
│   ref:   wsRef / reconnectAttemptRef / reconnectTimerRef          │
├──────────────────────────────────────────────────────────────────┤
│ useGameDerivedState (0 state, pure useMemo)                      │
│ useAutoScroll (0 state + 2 ref)                                   │
│   ref:   scrollRef / autoScrollRef                               │
└──────────────────────────────────────────────────────────────────┘
```

### 13.2 AppContext（跨页面全局状态）

```typescript
interface AppContextType {
  // 用户偏好
  language: Language;          // zh | en — 持久化到 URL
  viewMode: ViewMode;          // public | moderator
  agentType: AgentType;        // llm | heuristic（UI 默认 llm，忽略 URL 回退）

  // 房间 & 游戏
  room: RoomRecord | null;     // 当前房间元数据
  gameState: GameState | null; // 当前游戏快照（WebSocket 推送写入）

  // 连接状态
  isConnected: boolean;
  isPlaying: boolean;

  // 对局参数
  speed: number;               // AI 延迟 ms（默认 800）
  seed: number;                // 随机种子（默认 7）
}
```

**读写者：**
- **写入**: `useRoomStream`（gameState, isPlaying, room）、`AppProvider`（URL 初始化）、大厅页（room, seed, speed）
- **读取**: 所有组件通过 `useAppContext()` 消费

### 13.3 数据流（精确版）

```
WebSocket message
  │
  ▼
useRoomStream.onmessage ─────────────────────────────────────────────┐
  │  blink 期间? → bufferSnapshot(msg.state)  // 写入 pendingStateRef │
  │  正常期间    → setGameState(msg.state)     // 写入 AppContext      │
  ▼                                                                   │
AppContext.gameState  ◄─── flushResultRef ──── usePhaseTransition ───┘
  │                              (转场结束后，通过 effect 回写)
  ▼
useGamePageController
  │  gameState ──→ usePhaseTransition(sessionKey, gameState, hasWinner)
  │                   │
  │                   ├─→ visualPhaseGroup  → data-phase 属性
  │                   ├─→ phaseAnnouncement → PhaseOverlayCoordinator
  │                   ├─→ blinkPhase        → DayNightBlinkTransition
  │                   ├─→ isTransitioning   → UI 锁
  │                   └─→ displayGameState  → effectiveState（冻结态）
  │
  ├─→ effectiveState ──→ useGameDerivedState
  │                         │
  │                         ├─→ dayBlocks        → EventTimeline
  │                         ├─→ left/rightPlayers → PlayerRail
  │                         ├─→ activeSpeakerId  → PlayerCard 高亮
  │                         ├─→ aliveCount       → StatusBar
  │                         └─→ spokenInPhase    → PlayerCard 标记
  │
  └─→ displayPhase (useMemo) ──→ BadgePanel 同步打字机进度
        │                         (基于 completedIds 计算阻塞阶段)
        └─→ phaseTimeoutTick     (15s 无进展强制放行)
```

### 13.4 转场背压（Backpressure）机制

这是整个状态管理中最关键的协调逻辑。核心矛盾：

> WebSocket 以任意速率推送快照，但 UI 需要 1.5–3s 来完成昼夜转场动画。

**三阶段缓冲：**

```
阶段 A: 正常期
  gameState 直接写入 AppContext → UI 实时渲染

阶段 B: 眨眼期 (isBlinking=true, isTransitioning=true)
  frozenStateRef = gameState  // 冻结旧状态
  WebSocket 快照 → bufferSnapshot() → pendingStateRef  // 缓冲，只保留最新
  displayGameState = frozenStateRef  // UI 看到冻结画面

阶段 C: Settling 期 (isBlinking=false, isTransitioning=true)
  blink 动画完成，UI 锁仍保持
  继续缓冲 WebSocket 快照到 pendingStateRef

阶段 D: 释放
  flushResultRef = pendingStateRef  // 写入 ref
  setIsTransitioning(false)
  → useGamePageController effect 检测到 !isBlinking && !isTransitioning
  → setGameState(flushResultRef.current)
  → AppContext 更新 → 全 UI 重渲染
```

**关键 ref 说明：**

| ref | 类型 | 生命周期 | 用途 |
|---|---|---|---|
| `frozenStateRef` | `GameState \| null` | blink 开始时设置，_finishBlink 清 null | 冻结转场前的状态，UI 在转场期间渲染此快照 |
| `pendingStateRef` | `GameState \| null` | blink 期间 WebSocket 写入，释放时清 null | 接收转场期间到达的最新快照（只保留最后一份） |
| `flushResultRef` | `GameState \| null` | _finishBlink settling 写入，effect 消费 | 桥接 usePhaseTransition → useGamePageController |
| `transitionTokenRef` | `number` | 每次转场递增 | 取消旧的 setTimeout 回调（令牌模式） |
| `lastPhaseGroupRef` | `PhaseGroup` | 跨渲染持久 | 比较前后 phase group 以检测变化 |

### 13.5 打字机完成追踪

```typescript
// useGamePageController
const [completedIds] = useState<Set<string>>(() => new Set());
const completedIdsRef = useRef(completedIds);  // 保持同一引用
const [completedTick, setCompletedTick] = useState(0);

// ChatBubble 打字机完成时调用
onChatComplete = (eventId: string) => {
  completedIdsRef.current.add(eventId);
  setCompletedTick(n => n + 1);  // 触发依赖更新
};
```

**为什么需要 `completedTick` 计数器？**
- `Set.add()` 不改变引用，React 无法检测变化
- `completedTick` 作为"版本号"强制触发 `useMemo` 重计算
- 所有依赖 `completedIds` 的派生计算（`displayPhase`, `revealedEvents`, `BadgePanel`）通过 `completedTick` 感知更新

**displayPhase 计算（useMemo）：**

```
遍历 gameState.events:
  跳过 mergeConsecutiveChats 合并段（同玩家同 phase 连续发言的第二段+）
  找到第一个类型为 CHAT_MESSAGE 且不在 completedIds 中的事件
  → 返回该事件的 phase（即"阻塞阶段"）
  → 如果全部完成，返回 gameState.phase（最新阶段）
```

**用途：** `BadgePanel` 用 `displayPhase` 而非 `gameState.phase` 来判断当前展示的阶段，确保面板数据与打字机进度同步。

### 13.6 阶段超时保护

```typescript
const PHASE_TIMEOUT_MS = 15000;  // 15s
const phaseFirstSeenRef = useRef<{ phase: string; timestamp: number }>(...);
const [phaseTimeoutTick, setPhaseTimeoutTick] = useState(0);
const stuckPhaseRef = useRef<string>("");
```

**场景：** 某 CHAT_MESSAGE 事件永远不到达（网络丢包/AI 崩溃），打字机永久阻塞。

**机制：**
1. `displayPhase` 变化时记录 `{ phase, timestamp }`
2. 15s 后若 `displayPhase` 未前进 → 触发 `phaseTimeoutTick`
3. effect 将 `stuckPhaseRef` 对应的所有 CHAT_MESSAGE 强制标记为完成
4. 队列解锁，游戏继续

### 13.7 会话隔离（新房间重置）

```typescript
// usePhaseTransition
const lastSessionKeyRef = useRef("");

useEffect(() => {
  if (lastSessionKeyRef.current !== sessionKey) {
    // 新房间：重置所有转场状态
    cancelPhaseTransition();
    setPhaseAnnouncement(null);
    setBlinkPhase(null);
    setIsBlinking(false);
    setIsTransitioning(false);
    frozenStateRef.current = null;
    pendingStateRef.current = null;
    flushResultRef.current = null;
    lastPhaseGroupRef.current = "other";
    hasHandledFirstPhaseRef.current = false;
    handledEndSessionKeyRef.current = null;
    setVisualPhaseGroup("day");
    lastSessionKeyRef.current = sessionKey;
  }
}, [sessionKey, ...]);
```

### 13.8 useState vs useRef 选择原则

| 用 useState | 用 useRef |
|---|---|
| 需要触发重渲染 | 不需要触发重渲染 |
| 渲染结果依赖该值 | 值只被回调/effect 消费 |
| 例：`visualPhaseGroup`（驱动 data-phase） | 例：`frozenStateRef`（只在回调中读取） |
| 例：`blinkPhase`（驱动 Framer Motion） | 例：`transitionTokenRef`（令牌模式） |
| 例：`completedTick`（触发 useMemo） | 例：`pendingStateRef`（缓冲） |

**常见误区：**
- `completedIds` 是 `useState<Set>`，但它本身不触发更新 — 是配套的 `completedTick` 触发
- `isBlinking` 同时有 state 和 ref（`isBlinkingRef`）— state 驱动渲染，ref 在 WebSocket 回调中同步读取（避免闭包陷阱）

### 13.9 URL 同步

```
URL: /room/:id/play?mode=ai&lang=zh&agent_type=llm&room=:id
     ↑              ↑       ↑    ↑            ↑
     Next.js路由    模式   语言  Agent类型    房间ID
```

- **写入方向：** `useEffect` → `window.history.replaceState` → URL query string
- **读取方向：** `useEffect` → `URLSearchParams` → Context state
- **去重：** `agent_type` 从 URL 读取时忽略 `heuristic`（强制 LLM）
- **触发时机：** `language`、`agentType`、`room` 任意变化时

---

## 14. 后端通信

### REST API（通过 Next.js rewrites 代理）

```
浏览器 fetch("/api/rooms")
  → Next.js server-side rewrite
  → http://localhost:8000/api/rooms
  → FastAPI

rewrites 配置 (next.config.js):
  /api/:path* → BACKEND_ORIGIN/api/:path*
  /ws/:path*  → BACKEND_ORIGIN/ws/:path*
```

### WebSocket 协议

```
ws://frontend-host/ws/rooms/:roomId
  → Next.js rewrite
  → ws://backend-host/ws/rooms/:roomId

消息格式:
  → { action: "start", seed, agent_type, show_private, delay_ms }
  ← { type: "snapshot", state: GameState }
  ← { type: "complete", state, room }
  ← { type: "error", message }
```

---

## 15. 关键设计决策

### ✅ 为什么用 CSS 变量而不是 Tailwind 暗色模式？
- 需要 **三态切换**（day/night/end），不限于二元 dark mode
- CSS 变量比 `dark:` 前缀更灵活，组件无需感知当前主题
- Tailwind `bg-primary/10` 等透明度语法可直接使用 CSS 变量

### ✅ 为什么转场期间要冻结 UI？
- 防止 "守卫请睁眼" 在背景变黑前渲染（视觉不一致）
- 防止玩家卡片高亮和角色日志跨阶段跳跃
- 用户看到流畅的昼夜切换而非突兀的数据变化

### ✅ 为什么 VoteResultPanel 从时间线内移到上方？
- 投票结果是关键信息，不应因新事件推入而沉到底部
- 与 VotePanel 形成对称：实时投票在投票中显示，结果汇总在投票后显示

### ✅ 为什么用打字机逐字播放？
- 模拟真人阅读节奏，避免大量文字瞬间出现
- 通过 `revealIndex` 机制控制事件流的节奏感
- `mergeConsecutiveChats` 避免 AI 分段输出时出现重复气泡

### ✅ 为什么 PhaseAnnouncement 只显示一次？
- 修复前：`startBlinkTransition`（眨眼前）和 `_finishBlink`（settling 期）各显示一次
- 修复后：只在眨眼前显示，眨眼动画本身（黑屏/亮屏）已充分传达昼夜切换

---

## 16. 修复历史

| 日期 | 问题 | 修复 |
|---|---|---|
| 2026-06-04 | "天黑请闭眼"重复两次 | `_finishBlink` 移除重复公告 |
| 2026-06-04 | "天亮了"重复两次 | 同上 |
| 2026-06-04 | 投票结果沉在底部 | VoteResultPanel 移到滚动区上方 |
| 2026-06-04 | 投票组件重叠 | VotePanel 排除 BADGE 阶段 |
| 2026-06-04 | 状态栏发言者错位 | `pending_input` 增加阶段匹配校验 |
| 2026-06-04 | 游戏结束公告潜在重复 | `_finishBlink` 不再设置 end 公告 |

---

## 17. 文件索引

```
frontend/
├── app/
│   ├── globals.css              ← 主题 CSS 变量 + 动画 + 星空
│   ├── layout.tsx               ← RootLayout（AppProvider 包裹）
│   ├── page.tsx                 ← 大厅页
│   └── room/[id]/
│       ├── play/page.tsx        ← 游戏观战页（核心，~425行）
│       └── human/page.tsx       ← 真人模式页
├── components/
│   ├── game/
│   │   ├── DayNightBlinkTransition.tsx  ← 昼夜眨眼动画
│   │   ├── PhaseAnnouncement.tsx        ← 阶段全屏公告
│   │   ├── PhaseOverlayCoordinator.tsx  ← 蒙层协调器
│   │   ├── DramaticOverlay.tsx          ← 死亡/淘汰蒙层
│   │   ├── GameHeader.tsx               ← 顶栏
│   │   ├── PlayerRail.tsx               ← 玩家列（左右）
│   │   ├── PlayerCard.tsx               ← 玩家卡片
│   │   ├── EventTimeline.tsx            ← 事件时间线
│   │   ├── ChatBubble.tsx               ← 发言气泡（打字机）
│   │   ├── EventItem.tsx                ← 系统/行动事件
│   │   ├── ThinkingBubble.tsx           ← AI 思考气泡
│   │   ├── BadgePanel.tsx               ← 警徽竞选面板
│   │   ├── VotePanel.tsx                ← 放逐投票实时面板
│   │   ├── VoteResultPanel.tsx          ← 投票结果汇总面板
│   │   ├── VoteTargetGrid.tsx           ← 投票目标网格
│   │   ├── ActionPanel.tsx              ← 真人操作面板
│   │   ├── GameEndPanel.tsx             ← 游戏结束面板
│   │   ├── CountdownTimer.tsx           ← 倒计时
│   │   ├── LobbyConfigCard.tsx          ← 大厅配置卡片
│   │   ├── HumanStageArea.tsx           ← 真人阶段区域
│   │   ├── PrepareModal.tsx             ← 大厅确认弹窗（page.tsx 引用）
│   │   ├── PhaseBanner.tsx              ← ⚠️ 死代码（无引用）
│   │   └── DayBlock.tsx                 ← ⚠️ 死代码（无引用，EventTimeline 内联了 DayEventBlock）
│   └── ui/
│       ├── Button.tsx, Card.tsx, Badge.tsx
│       ├── ErrorBoundary.tsx
│       └── HtmlLang.tsx
├── context/
│   └── AppContext.tsx           ← 全局状态
├── hooks/
│   ├── useGamePageController.ts ← 游戏页总控
│   ├── usePhaseTransition.ts    ← 昼夜转场协调器
│   ├── useRoomStream.ts         ← WebSocket 管理
│   ├── useGameDerivedState.ts   ← 衍生状态计算
│   ├── useAutoScroll.ts         ← 自动滚动
│   ├── useTypewriter.ts         ← 打字机
│   └── useHumanDisplayState.ts  ← 真人模式显示状态
├── lib/
│   ├── i18n.ts                  ← 国际化
│   ├── gameApi.ts               ← REST API 封装
│   ├── api.ts                   ← API URL 构造
│   ├── gamePhase.ts             ← 阶段分组（day/night/end）
│   ├── gameView.ts              ← 观战视图工具
│   ├── eventFilter.ts           ← 事件过滤
│   └── utils.ts                 ← 通用工具（cn, truncate）
├── types/
│   └── index.ts                 ← 全部 TypeScript 类型定义
└── middleware.ts                 ← Next.js 中间件
```
