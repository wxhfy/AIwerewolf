# AI 对战观战模式 — 架构文档

## 数据流

```
用户在大厅 → 创建房间 → 准备（返回角色快照）→ 进入游戏页
  → WebSocket ws://localhost:3001/ws/rooms/{id}
  → 发送 { action:"start", delay_ms:800 }
  → 后端 stream_game() 在独立线程跑 game.play()
  → observer 回调在每个 _log() 后推送快照
  → drain_queue() 每 80ms 拉取队列发送到前端
```

## 组件树

```
app/room/[id]/play/page.tsx
├── PhaseOverlayCoordinator      ← 统一管理 DramaticOverlay + PhaseAnnouncement
├── GameHeader                   ← 房间号 / 天数 / 昼夜 / 视角切换
├── MobilePlayerRail             ← 移动端顶部水平玩家栏
├── <3列布局 flex-1>
│   ├── PlayerRail(left)         ← 左半玩家卡
│   ├── <main>
│   │   ├── StatusBar            ← 当前阶段 + 行动玩家 + 存活数
│   │   ├── BadgePanel           ← 警徽竞选 / 投票进度面板
│   │   └── EventTimeline        ← 事件时间线（打字机顺序播放）
│   └── PlayerRail(right)        ← 右半玩家卡
└── GameEndPanel                 ← 结束弹窗 + 悬浮入口
```

## 核心机制

### 1. 打字机队列

**文件**: `hooks/useTypewriter.ts`, `components/game/EventTimeline.tsx`

- `EventTimeline` 维护 `completedIds` Set，追踪已完成打字的消息 ID
- `revealIndex`：找到第一个未完成的 CHAT_MESSAGE，**后面所有事件隐藏**
- 只有 `revealIndex` 指向的气泡获得 `animate={true}`
- 当前气泡打完 → `onComplete` → `completedIds` 更新 → 父组件重渲染 → `revealIndex` 前移 → 下一个气泡
- 非 chat 事件（系统消息、投票记录）在当前 chat 完成后一起出现
- `useTypewriter` 使用 `requestAnimationFrame` 驱动，35 字/秒，最长 4 秒强制完成

### 2. 多段发言合并

**文件**: `components/game/EventTimeline.tsx` — `mergeConsecutiveChats()`

- 同一玩家同一 phase 连续 CHAT_MESSAGE → 合并为一个气泡（`\n\n` 拼接）
- 解决后端 LLM 多 segment 输出变成多个独立气泡的问题

### 3. Phase 同步

**文件**: `hooks/useGamePageController.ts`, `hooks/useGameDerivedState.ts`

- `displayPhase`：最早未完成 CHAT_MESSAGE 的 phase，若无则取 `gameState.phase`
- `revealedEvents`：只统计 `revealIndex` 之前的事件（与打字机同步）
- StatusBar / BadgePanel / PlayerCard 都从同一数据源派生，避免多组件不同步

### 4. 动画协调

**文件**: `components/game/PhaseOverlayCoordinator.tsx`

- `DramaticOverlay`（死亡/放逐公告）优先于 `PhaseAnnouncement`（天亮/天黑）
- 死亡公告活跃时抑制阶段提示，淡出后 300ms 再释放

### 5. 转场时序

**文件**: `hooks/usePhaseTransition.ts`

```
覆盖层 fade-in (400ms)
  → 完全显现 → 切换 data-phase 主题
  → 停留 1200ms（用户阅读）
  → fade-out (400ms)
```

### 6. 系统消息翻译

**文件**: `components/game/EventTimeline.tsx` — `translateSystemMessage()`

- 后端英文消息（"Badge signup opens..."、"was voted out" 等）→ 前端中文翻译
- 支持 12 种模式匹配

## 后端改动（本轮）

| 文件 | 改动 | 目的 |
|------|------|------|
| `engine/game.py` | `interrupt_phase_cycle` 每轮重置 + `_check_win()` | 修复白狼王自爆无限循环 |
| `engine/game.py` | `time.sleep(phase_delay_ms/1000)` 在关键节点 | 死亡/投票/猎人开枪后停顿 |
| `engine/phases.py` | CompositePhase 步骤间微延迟 (≥80ms) | 阶段切换不再 0ms 瞬跳 |
| `app.py` | `delay_ms` 从 WebSocket 透传到 game engine | 前端速度滑块控制后端节奏 |
| `app.py` | `game.phase_delay_ms = delay_ms` 覆盖复用游戏 | 修复 /prepare 预创建游戏延迟不生效 |

## 前端改动（本轮）

| 文件 | 改动 |
|------|------|
| `hooks/useTypewriter.ts` | 新建：rAF 打字机，`completedRef` 保护，`onCompleteRef` 防重跑 |
| `components/game/EventTimeline.tsx` | `mergeConsecutiveChats`, `revealIndex`, 系统消息翻译 |
| `components/game/BadgePanel.tsx` | 新建：警徽竞选/投票进度面板 |
| `components/game/DramaticOverlay.tsx` | 新建：死亡/放逐公告覆盖层 |
| `components/game/PhaseOverlayCoordinator.tsx` | 新建：统一动画编排 |
| `components/game/ChatBubble.tsx` | 打字机接入 + `React.memo` + 队列模式 |
| `hooks/useGamePageController.ts` | `displayPhase`, `completedIds`, `retryRoom` |
| `hooks/useGameDerivedState.ts` | `revealedEvents`, `spokenInPhase`, `voteCount`, `voteTarget` |
| `hooks/usePhaseTransition.ts` | 转场时序统一 |
| `components/game/GameEndPanel.tsx` | 自动弹窗 + 胜利原因 + 悬浮入口 |
| `components/game/PlayerCard.tsx` | 发言/投票状态 + 视觉增强 |
| `components/ui/ErrorBoundary.tsx` | 新建：崩溃降级 |
| `lib/i18n.ts` | 新增 retry/viewReview/winReason 等 key |
| `app/room/[id]/play/page.tsx` | `displayPhase`, `ErrorBoundary`, iOS dvh |

## 文件清单

```
frontend/
├── app/room/[id]/play/page.tsx        ← AI 观战页面
├── app/room/[id]/human/page.tsx       ← 真人模式页面（独立分支）
├── components/game/
│   ├── EventTimeline.tsx              ← 事件时间线（打字机）
│   ├── ChatBubble.tsx                 ← 聊天气泡
│   ├── BadgePanel.tsx                 ← 警徽/投票面板
│   ├── DramaticOverlay.tsx            ← 死亡公告覆盖层
│   ├── PhaseOverlayCoordinator.tsx    ← 动画协调器
│   ├── PhaseAnnouncement.tsx          ← 阶段提示（天亮/天黑）
│   ├── GameEndPanel.tsx               ← 结束弹窗
│   ├── GameHeader.tsx                 ← 顶部栏
│   ├── PlayerCard.tsx                 ← 玩家卡
│   ├── PlayerRail.tsx                 ← 玩家栏
│   ├── ActionPanel.tsx                ← 真人操作面板
│   ├── HumanStagePanel.tsx            ← [旧] 真人舞台
│   ├── RealStageArea.tsx              ← [旧] 真人舞台
│   ├── EventItem.tsx                  ← 事件条目
│   ├── CountdownTimer.tsx             ← 倒计时
│   └── VoteTargetGrid.tsx             ← 投票网格
├── hooks/
│   ├── useTypewriter.ts               ← 打字机 hook
│   ├── usePhaseTransition.ts          ← 转场动画
│   ├── useGamePageController.ts       ← 游戏页控制器
│   ├── useGameDerivedState.ts         ← 派生状态
│   └── useRoomStream.ts               ← WebSocket 流
├── lib/
│   ├── i18n.ts                        ← 国际化
│   ├── api.ts                         ← API URL 构建
│   ├── gameApi.ts                     ← HTTP API 调用
│   └── gamePhase.ts                   ← 阶段分组
├── context/AppContext.tsx             ← 全局状态
└── middleware.ts                      ← POST action 代理
```
