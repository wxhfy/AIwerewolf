# 发言两阶段状态同步修复方案

## 目标

修复发言流程中 **状态栏 / 玩家卡片气泡 / 聊天区域** 三个 UI 层在 thinking→speaking→finished 三个阶段的一致性。

## 背景

### 数据流

```
gameState.pending_input (后端: "轮到谁行动")
    ↓
CHAT_MESSAGE 事件 (后端: AI 生成完回复)
    ↓
打字机完成 (前端: onChatComplete → completedIds.add + completedTick++)
```

### 核心状态源

`useGameDerivedState.ts` 的 `speakerState`:
```ts
{ state: "thinking" | "speaking" | "finished", speakerId: string | null }
```
- thinking: pending_input 存在，CHAT_MESSAGE 事件未到达
- speaking: CHAT_MESSAGE 事件已到达，打字机未完成
- finished: 打字机完成 (completedIds 包含该事件 ID)

### 三个 UI 层应该如何同步

| speakerState | 状态栏 | 玩家卡片气泡 | 聊天区域 |
|---|---|---|---|
| thinking | "X号 玩家 思考中" | "思考中" badge | "正在组织语言..." 占位 |
| speaking | "X号 玩家 发言中" | "发言中" badge | 打字机逐字输出 |
| finished | 阶段名称 | badge 消失 | 文本完整展示 |

---

## 发现的 7 个问题

### Bug A 🔴: `speakerState` 无法检测 finished → speaking 卡住不消失

**文件**: `useGameDerivedState.ts:147`

**根因**: `speakerState` 的 useMemo deps 缺少 `completedTick`:
```ts
}, [gameState?.phase, gameState?.pending_input?.player_id, gameState?.events, completedIds]);
```
`completedIds` 是 Set，通过 `.add()` 原地修改，引用不变。React 的 referential equality 检查认为 deps 没变，永远不重新计算。所以 `speakerState` 永远停在 "speaking"。

**影响**: 玩家卡片的 "发言中" badge 在打字机播完后仍不消失，直到下一个事件触发 gameState.events 变化。

**修复**: 添加 `completedTick` 到 deps。

### Bug B 🔴: `HumanStatusBar` 未解构 `speakerState`

**文件**: `HumanStatusBar.tsx:24`

**根因**: Props 定义了 `speakerState` 和 `players`，但函数签名解构遗漏：
```ts
export function HumanStatusBar({ display, displayPhase, language }: HumanStatusBarProps) {
```
JSX 中引用了 `speakerState` 和 `players`（43-46行），但它们是 `undefined`，导致 TypeScript 编译报错 4 个。

**修复**: 解构 `speakerState` 和 `players`。

### Bug C 🟡: `deriveStatusText` 不消费 `speakerState` — AI状态栏自判断逻辑与 speakerState 不同步

**文件**: `deriveStatusText.ts`

**根因**: `deriveStatusText` 自己检查 `CHAT_MESSAGE` 事件存在性来判断 thinking/speaking，但对 `finished` 状态无感知（不了解 `completedIds`）。这导致：
- thinking → speaking 切换正常 ✅
- speaking → finished 切换缺失 ❌（状态栏仍显示"发言中"）

**修复**: 给 `deriveStatusText` 传入 `speakerState` 参数，在 speech 阶段优先用它判断。

### Bug D 🟡: `DayEventBlock` 思考占位文案硬编码

**文件**: `DayEventBlock.tsx:301`

**根因**: 
```ts
content={language === "zh" ? "正在组织语言..." : "Thinking..."}
```
i18n 已有 `organizingSpeech` key，`ThinkingBubble.tsx` 也在用。DayEventBlock 重复硬编码。

**修复**: 使用 `t("organizingSpeech", language)`.

### Bug E 🟡: `ThinkingBubble` header 显示 "发言中" 而非 "思考中"

**文件**: `ThinkingBubble.tsx:24`

**根因**:
```ts
headerRight={t("playerSpeaking", language)}
```
ThinkingBubble 只在 thinking 阶段渲染，header 应显示 "思考中"。

**修复**: 改为 `t("playerThinking", language)`.

### Bug F 🟡: `page.tsx` 底部 ThinkingBubble 重复判断逻辑

**文件**: `page.tsx:215-234`

**根因**: 手动检查 `pending_input` + 无 CHAT_MESSAGE 来决定是否显示，与 `speakerState` 逻辑重复。

**修复**: 直接用 `derived.speakerState.state === "thinking"` 替代手动判断。注意保持 `isHuman && pi.seat === controller.humanSeat` 的跳过逻辑。

### Bug G 🟢: ChatBubble 空发言兜底 (已在前一步修复)

已修复，三层渲染策略：有内容→正常渲染 / 打字机启动中→光标 / 无内容→("发言完毕，过").

---

## 修改文件清单 (7 files)

| # | 文件 | 改动 | 风险 |
|---|---|---|---|
| 1 | `useGameDerivedState.ts` | speakerState deps 加 `completedTick` | 低 |
| 2 | `HumanStatusBar.tsx` | 解构 `speakerState`, `players` | 低 (修复 TS 报错) |
| 3 | `deriveStatusText.ts` | 新增 `speakerState?` 参数，speech 阶段优先用它 | 中 (纯函数签名变更) |
| 4 | `AIStatusBar.tsx` | 传 `derived.speakerState` 给 `deriveStatusText` | 低 |
| 5 | `DayEventBlock.tsx` | 硬编码 → `t("organizingSpeech", language)` | 低 |
| 6 | `ThinkingBubble.tsx` | headerRight 从 "发言中" → "思考中" | 低 |
| 7 | `page.tsx` | 底部 ThinkingBubble 改用 `speakerState` 判定 | 中 (影响渲染条件) |

---

## 不变更的部分

- `PlayerRail` / `PlayerCard`: 已正确消费 `speakerState`，无需改动
- `MobilePlayerRail`: 同 PlayerRail 逻辑，无需改动
- `BadgePanel`: 独立组件，不受影响
- 投票阶段各组件: 不涉及 speech，不受影响
- 夜间阶段各组件: 不涉及 speech，不受影响
- `EventTimeline` / `TimelineEvent`: 已正确传递 `speakerState` 给 `DayEventBlock`
- `ChatBubble`: 已在上一步完成兜底修复
- i18n 字典: 所需 key 全部已存在 (`playerThinking`, `playerSpeaking`, `organizingSpeech`, `playerThinkingStatus`, `playerSpeakingStatus`)

---

## 验证方式

1. `npx tsc --noEmit` 零错误
2. 逻辑验证: thinking→speaking→finished 三个阶段各有明确的触发条件，三者互斥且覆盖 speech 阶段所有状态
3. 组件间一致性: 状态栏/卡片/聊天区三者读取同一个 `speakerState` 对象
