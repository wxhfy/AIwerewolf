# AI Werewolf — UX Audit Report v2

> **日期**: 2026-05-29  
> **版本**: v2（经独立 subagent 审查后修订）  
> **审计方法**: 完整游戏事件时序追踪（HTTP API 直连后端，114 事件 / 47.5s）+ 前后端全量代码深度审查 + 7 人 AI 局实测

---

## 执行摘要

本报告识别出 **3 个 P0 阻塞级问题**（白狼王无限循环、阶段零间隔切换、fetch 失败时页面无声僵死）、**8 个 P1 高优先级问题**（GameEndPanel 指针捕获未释放、sessionKey 过频破坏动画、iOS 裁剪、缺失错误边界、缺失加载状态等）以及 16 个中低优先级问题。

最关键的体验缺口是：**游戏页面的三个核心 UX 状态（加载中 / 空状态 / 错误恢复）全部缺失**。用户首次进入游戏时面对空白画面无反馈；网络出问题时页面静默僵死无重试入口；加上阶段间零间隔导致的动画重叠，整体观战体验远未达到可用标准。

---

## 分类体系说明

| 优先级 | 含义 | 示例 |
|--------|------|------|
| P0 | 阻塞发布：游戏逻辑错误或用户无法完成核心流程 | 白狼王死循环、页面静默僵死 |
| P1 | 严重影响体验但可绕过 | 动画失效、按钮不可用、iOS 裁剪 |
| P2 | 中等影响：缺少应有的能力 | 缺少 ARIA、无心跳检测 |
| P3 | 锦上添花：改进但不影响使用 | CSS 细节调整 |

---

## P0 — 阻塞级（3 项）

### P0-1: 白狼王自爆导致无限循环（游戏逻辑错误）

**文件**: `backend/engine/game.py:311-333`, `game.py:985`, `phases.py:30-34`

**现象**: 白狼王在发言阶段使用自爆技能后，游戏进入无限循环，不断递增 day 直到 `max_days`（默认 8），最终以超时判狼胜——无论场上实际好人是否占优。

**根因**: 白狼王自爆后设置 `interrupt_phase_cycle = True`（game.py:985），`CompositePhase` 检测到此标记立即 break（phases.py:33），此时 phase 为 `WHITE_WOLF_KING_BOOM`。但 `WHITE_WOLF_KING_BOOM` 无独立 handler（phases.py:37-68 未注册），被 `play_until_blocked` 的路由分发到 NIGHT_START bucket（game.py:312-313），触发 `_begin_night()` 递增 day。`_begin_night` 将 phase 设为 NIGHT_START，CompositePhase 再次因 `interrupt_phase_cycle` 中断……如此循环直到 `day >= max_days`。

**修复方案**（具体步骤）:

1. 在 `_hunter_shoot_from_pending`（game.py:862-869）和 `_badge_transfer_from_pending`（game.py:988-1055）末尾添加 `self._check_win()`，使爆炸后的胜利立即可检测
2. 为 `WHITE_WOLF_KING_BOOM` 注册独立的 AtomicPhase handler（phases.py:37），在 handler 末尾显式清除 `interrupt_phase_cycle` 并将 phase 状态正确过渡到 DAY_RESOLVE
3. 在 `play_until_blocked` while 循环**每次迭代开始时**重置 `interrupt_phase_cycle = False`（防御性修复）

### P0-2: 多个阶段零间隔切换（动画完全失效）

**文件**: `backend/engine/game.py:311-350`

**现象**: 实测中发现 8 个相邻阶段转换间隔为 0ms：

| 阶段转换 | 实测间隔 | 用户体验影响 |
|----------|----------|-------------|
| NIGHT_RESOLVE → DAY_START | 0ms | 死亡公告 + 天亮同时到达，覆盖层叠影 |
| DAY_START → DAY_BADGE_SIGNUP | 0ms | 天亮后无停顿即进警长竞选 |
| DAY_BADGE_SIGNUP → DAY_BADGE_SPEECH | 0ms | 竞选报名和发言无缝衔接 |
| DAY_RESOLVE → DAY_LAST_WORDS | 0ms | 放逐公告和遗言在同一帧 |
| DAY_RESOLVE → NIGHT_START | 0ms | 白天结束立即天黑，无过渡 |
| NIGHT_START → NIGHT_GUARD_ACTION | 0ms | 黑夜动画同帧进入守卫行动 |
| NIGHT_GUARD_ACTION → NIGHT_WOLF_ACTION | 0ms | D2 夜间行动间无间隔 |

**根因**: `CompositePhase.run()`（phases.py:30-34）在一次调用中顺序执行所有子步骤（例如 NIGHT_START composite 包含 begin_night + guard + wolf + witch + seer + resolve 共 6 步），步骤之间无任何延迟。Observer 在每个步骤的 `_log()` 中触发，一次性推送大量快照到前端。

**修复方案**: 不是在 while 循环中加 `time.sleep()`，而是在 `AtomicPhase.run()` 末尾添加一个可配置的 `after_emit_delay_ms`（默认 100-200ms），确保每个原子阶段完成后前端有至少一帧的时间处理和渲染。

### P0-3: 游戏页加载失败时静默僵死（无错误恢复）

**文件**: `frontend/hooks/useGamePageController.ts:75-79`, `app/room/[id]/play/page.tsx`

**现象**: 当 `fetchRoom(roomId)` 失败时，错误被 `.catch(() => {})` 静默吞掉。用户进入游戏页后看到：
- StatusTitle 显示"已就绪"
- GameHeader 正常渲染
- 玩家栏显示占位卡片
- 事件时间线空白
- **无任何错误提示、无重试按钮、无返回链接**

用户无法判断是网络慢还是出了错，唯一的出路是手动改 URL 退回大厅。

**修复方案**:
1. 在 `useGamePageController` 中新增 `fetchError` 状态，fetch 失败时设置错误信息
2. 在 `page.tsx` 中添加内联错误条组件：显示错误描述 + "重试"按钮（调用 `fetchRoom` 重试）+ "返回大厅"按钮
3. 加入超时检测：若状态为"已就绪"且 5 秒内无任何 snapshot 到达，自动展示错误条

---

## P1 — 高优先级（8 项）

### P1-1: GameEndPanel 浮动按钮指针捕获未释放（移动端核心路径被破坏）

**文件**: `frontend/components/game/GameEndPanel.tsx:54-86`

**现象**: 结束时出现的浮动按钮（可拖动）使用了 Pointer Events API 实现拖拽，但 `onPointerUp`（line 75）**未调用 `releasePointerCapture()`**。这导致元素持续独占指针事件，拖拽后按钮再也无法点击。此外缺少 `touch-action: none` CSS，移动端浏览器可能在拖拽时触发页面滚动。

**修复**:
- `onPointerUp` 中添加 `event.currentTarget.releasePointerCapture(event.pointerId)`
- 容器加 `touch-action: none`
- 将 `onPointerUp` 逻辑改为在 `onLostPointerCapture` 中执行

### P1-2: sessionKey 过频变化导致 PhaseAnnouncement 动画失效

**文件**: `frontend/hooks/useGamePageController.ts:34`

`sessionKey = roomId:gameState.id`。`gameState.id` 在每个 WebSocket snapshot 上变化，导致 `usePhaseTransition` 在**每个消息**上执行重置逻辑。昼夜转场动画（"天黑请闭眼"/"天亮了"）要么闪烁要么根本不播放。

**修复**: `sessionKey` 应只依赖 `roomId`。用户在同一个房间内只有一个连续的游戏流。或者用 ref 在首次 snapshot 时记录 `gameInstanceId`，后续不变。

### P1-3: iOS Safari 底部被裁剪

**文件**: `frontend/app/room/[id]/play/page.tsx:22`

`h-screen` 在 iOS Safari 中将地址栏高度计入 viewport，导致页面底部被遮挡。`h-dvh` 使用动态视口高度。

**修复**: `h-screen` → `h-dvh`，并添加降级方案：`h-screen [height:100dvh]` 兼容老浏览器。

### P1-4: 无 ErrorBoundary（组件崩溃 → 白屏）

**文件**: `frontend/app/room/[id]/play/page.tsx`

游戏页组件树无 `<ErrorBoundary>` 包裹层。任何子组件（`DramaticOverlay`、`GameEndPanel`、`EventTimeline`等）的渲染异常都会导致整页白屏，用户丢失当前对局上下文。

**修复**: 用 React Error Boundary 包裹主要内容区域，捕获错误后显示降级 UI（"游戏加载出错" + 重试 + 返回大厅）。

### P1-5: 游戏启动阶段无加载反馈

**文件**: `frontend/app/room/[id]/play/page.tsx:61-81`

从用户进入游戏页到 WebSocket 连接并收到首个 snapshot，中间有 2-5 秒的空白期（agent 初始化 + LLM 预热）。当前 UI 显示"已就绪"文字 + 空白时间线 + 占位玩家卡，无旋转动画、骨架屏或任何进度指示。

**修复**:
1. 将 `autoStartedRef` 的 200ms 硬编码延迟改为监听 WebSocket `status` 消息
2. 在首帧到达前显示骨架屏（玩家卡 + 时间线占位）
3. 首帧到达后自然过渡到真实内容

### P1-6: 猎人开枪后漏调 `_check_win()`

**文件**: `backend/engine/game.py:852-860`

猎人白天开枪击杀最后一只狼后，`_check_win()` 未被调用。游戏多跑一整轮 NIGHT_START → DAY_START（守卫护人、女巫用药、预言家验人全多执行一次），浪费计算且泄露不应有的私有信息。

**修复**: 在 `_hunter_shoot`（game.py:895）末尾、`badge_transfer` 处理之后添加 `self._check_win()`。

### P1-7: 移动端玩家栏位置不当

**文件**: `frontend/app/room/[id]/play/page.tsx:109-119`

`MobilePlayerRail` 在 DOM 中位于事件时间线下方，移动端用户需滚动完所有事件才能看到存活玩家状态。玩家状态是观战核心信息，应始终可见。

**修复**: 将 `MobilePlayerRail` 移到页面顶部（`GameHeader` 正下方），或设计为折叠式浮层常驻顶部。

### P1-8: 覆盖层缺少 ARIA live region

**文件**: `frontend/components/game/DramaticOverlay.tsx`, `PhaseAnnouncement.tsx`

死亡/放逐/阶段转换等关键游戏事件对屏幕阅读器用户完全不可见。覆盖层为纯视觉设计。

**修复**:
- `DramaticOverlay` 添加 `role="alert"` / `aria-live="assertive"`
- `PhaseAnnouncement` 容器添加 `aria-live="polite"`

---

## P2 — 中等优先级（12 项）

### 用户体验

| ID | 问题 | 文件:行 | 修复方向 |
|----|------|---------|---------|
| P2-U1 | PK 平票重投无任何视觉提示 | game.py:800-806 | PK 环节开始时发 SYSTEM_MESSAGE "进入 PK 发言" |
| P2-U2 | DramaticOverlay 消息解析脆断（字符串匹配） | DramaticOverlay.tsx:47-72 | 改用 EventType 或结构化 payload |
| P2-U3 | DramaticOverlay 无卸载清理（嵌套 setTimeout 不释放） | DramaticOverlay.tsx:84-88 | useEffect cleanup 中 clearTimeout |
| P2-U4 | GameEndPanel 硬编码双语绕过 i18n | GameEndPanel.tsx:130 | 改用 `t()` |
| P2-U5 | 夜间系统消息 `bg-background` 对比度偏低 | ChatBubble.tsx:26 | 夜间模式使用专属背景色 |
| P2-U6 | 三列布局在平板（768-1024px）无过渡 | page.tsx:47-106 | 增加 md 断点的两列布局 |
| P2-U7 | 大厅无对局历史列表（后端已有 `game_history` 字段） | app/page.tsx | 添加历史对局列表入口 |

### 组件健壮性

| ID | 问题 | 文件:行 | 修复方向 |
|----|------|---------|---------|
| P2-R1 | CountdownTimer 副作用在 setState 回调内 | CountdownTimer.tsx:29-37 | 移到 setInterval 回调体外 |
| P2-R2 | CountdownTimer 无 ARIA progressbar 属性 | CountdownTimer.tsx | 添加 role/aria-valuenow/aria-valuemax |
| P2-R3 | fetchRoom 无 AbortController 取消 | useGamePageController.ts:75-79 | 添加 AbortController |
| P2-R4 | ActionPanel 提交按钮缺少加载 spinner | ActionPanel.tsx:163 | 禁用时显示 spinner |
| P2-R5 | VoteTargetGrid 无 `aria-selected` | VoteTargetGrid.tsx | 选中卡片添加 aria-selected |

---

## P3 — 低优先级（8 项）

| ID | 问题 | 文件:行 |
|----|------|---------|
| P3-1 | 阶段公告背景硬编码 RGB（应使用 CSS 变量） | globals.css:112-130 |
| P3-2 | `--warning` 颜色映射到 gold（语义不当，应为 amber） | tailwind.config.ts:28 |
| P3-3 | 无打印样式（游戏页打印后布局错乱） | globals.css |
| P3-4 | `<html lang>` 硬编码不随语言动态切换 | layout.tsx:16 |
| P3-5 | PlayerCard 角色隐藏时 Badge 仍带主题色（应中性灰） | PlayerCard.tsx:43 |
| P3-6 | `t()` 缺翻译时返回内部 key 名（应 fallback 到英文） | i18n.ts:426 |
| P3-7 | WebSocket 无心跳检测（合盖后可能数分钟才触发 onclose） | useRoomStream.ts |
| P3-8 | `h-screen` 覆盖浏览器默认字号 17px（影响可访问性） | globals.css:176 |

---

## 优先级汇总

| 优先级 | 数量 | 关键项 |
|--------|------|--------|
| **P0** | 3 | WWK 无限循环、阶段零间隔切换、fetch 失败静默僵死 |
| **P1** | 8 | GameEndPanel 指针泄漏、sessionKey 破坏动画、iOS 裁剪、无 ErrorBoundary、无加载状态、猎人 win-check 缺失、移动端玩家栏位置、ARIA live 缺失 |
| **P2** | 12 | PK 提示、DramaticOverlay 解析/清理、i18n 硬编码、夜间对比度、平板布局、对局历史、CountdownTimer 副作用/ARIA、fetch 取消、spinner、aria-selected |
| **P3** | 8 | CSS 变量化、warning 色、打印、lang、Badge 色、i18n fallback、WS 心跳、font-size |

**总计: 31 项**

---

## 附录 A — 测试局完整追踪数据

```
对局配置: 7 人 · AI 对战 (llm) · Seed 999 · 角色池 wolfcha-default

总耗时: 47.5s | 事件数: 114 | 结束 Day: 2 | 胜者: wolf
存活: 3/7

阶段时间线 (27 phases, 8 个零间隔):
  +    0ms  D1  NIGHT_START          ← 零间隔
  +    0ms  D1  NIGHT_GUARD_ACTION    ← 零间隔
  + 1757ms  D1  NIGHT_WOLF_ACTION     (LLM 决策 1.8s)
  + 3405ms  D1  NIGHT_WITCH_ACTION    (LLM 决策 3.4s)
  + 1187ms  D1  NIGHT_SEER_ACTION     (LLM 决策 1.2s)
  + 1588ms  D1  NIGHT_RESOLVE         (结算)
  +    0ms  D1  DAY_START             ← 零间隔
  +    0ms  D1  DAY_BADGE_SIGNUP      ← 零间隔
  +    0ms  D1  DAY_BADGE_SPEECH      ← 零间隔
  + 5339ms  D1  DAY_BADGE_ELECTION    (警长竞选)
  + 7236ms  D1  DAY_SPEECH            (7人发言)
  + 9301ms  D1  DAY_VOTE              (7人投票)
  + 5665ms  D1  DAY_RESOLVE           (PK 平票→重投)
  +    0ms  D1  DAY_PK_SPEECH         ← 零间隔
  + 1423ms  D1  DAY_VOTE              (PK 投票)
  + 4515ms  D1  DAY_RESOLVE
  +    0ms  D1  DAY_LAST_WORDS        ← 零间隔
  + 1102ms  D1  DAY_RESOLVE
  +    1ms  D2  NIGHT_START           (Day 2 开始)
  +    0ms  D2  NIGHT_GUARD_ACTION    ← 零间隔
  +    0ms  D2  NIGHT_WOLF_ACTION     ← 零间隔
  + 1460ms  D2  NIGHT_WITCH_ACTION
  +  693ms  D2  NIGHT_SEER_ACTION
  +  802ms  D2  NIGHT_RESOLVE

系统消息序列:
  D1 [NIGHT_START       ] Night 1 begins.
  D1 [NIGHT_RESOLVE     ] No one died last night.        ← 平安夜
  D1 [DAY_START         ] Day 1 begins.
  D1 [DAY_BADGE_SIGNUP  ] Badge signup opens.
  D1 [DAY_BADGE_ELECTION] 林思远 won sheriff election.
  D1 [DAY_PK_SPEECH     ] Vote tie → PK speeches.
  D1 [DAY_LAST_WORDS    ] 陶若安 was voted out.
  D2 [NIGHT_START       ] Night 2 begins.
  D2 [NIGHT_RESOLVE     ] Night deaths: 林思远.
  D2 [BADGE_TRANSFER    ] 林思远 passes badge to 莫离.

事件分布:
  CHAT_MESSAGE:   29   (发言)
  PHASE_CHANGED:  27   (阶段切换)
  PRIVATE_INFO:   17   (角色信息)
  VOTE_CAST:      16   (投票)
  SYSTEM_MESSAGE: 10   (公告)
  NIGHT_ACTION:    9   (夜间行动)
  PLAYER_DIED:     3   (玩家死亡)
  GAME_START:       1
  HUNTER_SHOT:      1
  GAME_END:         1
```

---

## 附录 B — 审查方法论

1. **时序追踪**: 通过 Python raw socket 直连后端 HTTP API（绕过 Next.js 代理以避免超时截断），创建 7 人 AI 局，记录完整的 114 事件序列，分析每个 PHASE_CHANGED 之间的时间间隔
2. **前端代码审查**: 遍历所有前端源文件（components、hooks、lib、types、app），检查：加载/空状态/错误状态处理、动画时序、可访问性属性、i18n 覆盖、响应式布局、CSS 变量使用
3. **后端代码审查**: 遍历引擎核心文件（game.py、phase_manager.py、phases.py），追踪完整 play_until_blocked 循环、CompositePhase 分发、事件发射、观察者模式
4. **边界场景推理**: 白狼王自爆、PK 平票递归、猎人被毒杀、女巫解药毒药互斥、idiot 翻牌免疫等特殊路径逐行审查

**已知局限**: 无实际浏览器测试（无截图），未进行 Lighthouse/Axe 自动化扫描，未进行真人可用性测试

---

## 附录 C — 代码质量笔记（非 UX 问题，供开发参考）

以下项目在 v1 中被归为 UX 问题，但实际属于代码质量/类型安全范畴，不直接影响用户体验，移入此附录：

| 项 | 说明 | 文件 |
|----|------|------|
| `PendingInput.action_type` 类型过宽 | `string` → `ActionType` | types/index.ts:174 |
| `RoomRecord.status` 无联合类型 | 应限定 `"waiting"` 等 | types/index.ts:213 |
| `GameEvent.visible_to` 非可选 | 公开事件无此字段 | types/index.ts:129 |
| `useGameDerivedState` useMemo 无效 | 依赖整个 gameState，每帧计算 | useGameDerivedState.ts:37 |
| `useAutoScroll` 无 ResizeObserver | 内容尺寸变化不跟踪 | useAutoScroll.ts |
| `format()` 花括号值可能干扰模板 | 极端边界 case | i18n.ts:433 |
| `warning` 色映射到 gold | 语义偏离（非用户可见） | tailwind.config.ts:28 |
| 页面 `data-phase` 属性在 html 和 div 上重复 | 冗余但不影响行为 | page.tsx:22, usePhaseTransition.ts:120 |
