# PlayerCard 重构 + 投票 UI 优化 设计规格

> 日期：2026-06-03 | 分支：`roy/ux-optimization`

## 问题诊断

1. **PlayerCard 布局抖动**：所有标签（角色、思考中、发言中、警长、竞选、已发言、投票信息）挤在右上角一个 `flex-wrap` 容器内，任何标签出现/消失触发重排
2. **投票信息散落**：`voteTargetName`（已投→X）、`voteCount`（N票）、`hasVoted`（已投票）全部塞在卡片内部，与投票组件职责重叠
3. **信息层级混乱**：过程状态（思考中）和身份标签（狼人/女巫）混在同一区域，右下角完全空置

## 设计目标

1. PlayerCard 任何状态下布局稳定不抖动
2. 投票过程/结果在中间叙事区独立展示
3. 玩家卡片只保留玩家自身信息

---

## 一、PlayerCard：CSS Grid 3 行固定布局

### Grid 结构

```
grid-template-areas:
  "identity  badges"
  "persona   persona"
  "proc      result"
grid-template-columns: 1fr auto
grid-template-rows: auto auto auto
```

### 各区域职责

| 区域 | grid-area | 内容 | 固定约束 |
|------|-----------|------|----------|
| `identity` | 顶行左 | 座位号圆圈 + 姓名 + "我"标签 | — |
| `badges` | 顶行右 | 角色标签（村民/狼人/女巫…）、警长标签 | `min-w-[72px]`，只放身份标签 |
| `persona` | 中行 | MBTI + style_label / basic_info（line-clamp-2） | `min-h-[1.5em]` |
| `proc` | 底行左 | 思考中、发言中、行动中、警徽竞选 | `min-h-[20px]`，opacity 过渡 |
| `result` | 底行右 | 已死亡、已用药、已开枪、已发言 | `min-h-[20px]`，opacity 过渡 |

### 关键规则

- **badges 区域**永远不渲染过程状态（思考中、发言中、警徽竞选）
- **proc/result** 内容为空时保留 min-h，不 collapse
- **isSpeaking 高亮**：使用 `outline`（不占盒模型），不用 `ring-[3px]`
- **scale-[1.02]** 删除，避免与相邻卡片重叠
- **所有动画**包在 `@media (prefers-reduced-motion: no-preference)` 内
- **焦点指示器**：`focus-visible:outline-2 focus-visible:outline-primary`

### 内容迁移

| 标签 | 当前位置 | 目标区域 |
|------|----------|----------|
| 角色标签 | 右上 flex-wrap | `badges` |
| 警长 | 右上 flex-wrap | `badges` |
| "我" | 左上（名字旁） | `badges` |
| 思考中 | 右上 flex-wrap | `proc` |
| 发言中 | 右上 flex-wrap | `proc` |
| 警徽竞选 | 右上 flex-wrap | `proc` |
| 已死亡 | 无（仅有 opacity） | `result` |
| 已发言 | 右上 flex-wrap | `result` |
| ~~已投票~~ | ~~右上~~ | **删除（移入中间面板）** |
| ~~投票目标名~~ | ~~右上~~ | **删除** |
| ~~票数~~ | ~~右上~~ | **删除** |
| 狼队友 | 中部下方 | `result` 或独立行（保持现有位置） |

### Props 变更

| 操作 | Props |
|------|-------|
| **删除** | `voteCount`、`voteTargetName`、`hasVoted` |
| **保留** | 其余所有 prop（`player`、`isSpeaking`、`isThinking`、`isSheriff`、`isBadgeCandidate`、`hasSpoken`、`wolfTeammates`、`showOwnRole`、`selectable`、`isTarget`、`onSelectTarget`、`onClick`、`isSelected`） |

---

## 二、VotePanel：投票进行中面板

### 插入位置

中间叙事区（EventTimeline 上方或内部），响应 `gameState.phase === "VOTE"` 且投票未结束时展示。

### UI 结构

```
┌─────────────────────────────────┐
│  🗳 投票放逐          已投 N/M   │  ← 标题 + 进度
│  ─────────────────────────────  │
│  已投票关系卡片（flex-wrap 流）    │
│  [3号 → 8号] [5号 → 3号]        │  ← min-h-[44px] 每张
│  [7号 → 8号]                    │
│  ─────────────────────────────  │
│  ⏳ 等待投票: X号, Y号, Z号      │  ← 未投票列表
└─────────────────────────────────┘
```

### 数据来源

- `gameState.votes: Record<string, string>` — 投票关系（voterId → targetId）
- `gameState.players` — 玩家姓名/座位映射
- `gameState.phase_cursor` — 当前投票的 actor 列表

### 交互规则

- 玩家卡片可点击选择目标（复用现有 `selectable`/`isTarget` 逻辑）
- 选择后底部 ActionPanel 显示"确认投票 / 取消"
- 确认后卡片选中态高亮 + 面板更新
- 非投票阶段面板隐藏

### 约束

- 每张投票关系卡片 `min-h-[44px]`（触控规范）
- 进度条使用现有组件或简单 CSS
- 金色强调线（`border-primary`）

---

## 三、VoteResultPanel：投票结算面板

### 插入位置

投票结束后替换 VotePanel 展示。

### UI 结构

```
┌─────────────────────────────────┐
│  📊 投票结果                     │
│  ─────────────────────────────  │
│  候选人行（每人一行）:            │
│  [编号] · 姓名          N票     │
│  ← 投票者1, 投票者2, ...        │
│  ─────────────────────────────  │
│  🚫 N号 姓名 被放逐              │  ← 结算结果
└─────────────────────────────────┘
```

### 数据来源

- `gameState.votes` — 以系统返回为准，不前端推算人数
- `gameState.vote_history` — 历史投票（若有警长票/加权票，取最终结果）
- `gameState.players` — 死亡/放逐状态更新

### 过渡

- VotePanel 消失 → skeleton 占位（200ms）→ VoteResultPanel 出现
- skeleton 避免异步数据到达前的空白闪烁

### 状态流转

```
投票开始 → VotePanel 出现 → 玩家卡片可点击
         → 选择 + 确认 → 进度更新
投票结束 → VotePanel fade-out → skeleton → VoteResultPanel fade-in
结算完成 → 被放逐玩家卡片变死亡（opacity + result 标签更新）
```

---

## 四、涉及文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `components/game/PlayerCard.tsx` | 重构 | Grid 布局、移除 vote props、动画修正 |
| `components/game/PlayerRail.tsx` | 修改 | 移除 vote 相关 props 传递 |
| `components/game/PlayerRail.tsx` (MobilePlayerRail) | 修改 | 同上 |
| `components/game/VotePanel.tsx` | **新建** | 投票进行中面板 |
| `components/game/VoteResultPanel.tsx` | **新建** | 投票结算面板 |
| `app/room/[id]/play/page.tsx` | 修改 | 中间区插入投票面板 |
| `app/room/[id]/human/page.tsx` | 修改 | 同上 |
| `hooks/useGameDerivedState.ts` | 修改 | voteCount/voteTarget 数据保留但传给中间组件 |

### 不改

- 后端数据结构（`GameState.votes`、`PendingInput` 等全部不动）
- `EventTimeline.tsx` 核心逻辑
- `ActionPanel.tsx` 投票交互逻辑（只配合选中态）
- `HumanStageArea.tsx` 整体骨架
- AI 观战页布局骨架

---

## 五、验收标准

1. **布局稳定性**：PlayerCard 在任意阶段切换时，身份标签、姓名、人设不发生位移
2. **投票信息分离**：PlayerCard 不再显示"已投→X""N票""已投票"
3. **VotePanel**：投票阶段中间出现进度面板，已投票关系正确展示
4. **VoteResultPanel**：投票结束后出现结果面板，票数以系统数据为准
5. **CSS Grid 正确**：4 个 `grid-area` 互不干扰，空内容区域不 collapse
6. **动画合规**：`prefers-reduced-motion` 下无 pulse/scale 动画，isSpeaking 用 outline 不用 ring
7. **触控合规**：投票关系卡片 ≥44px 高度
8. **焦点合规**：PlayerCard focus-visible 可见指示器
9. **编译通过**：`npx tsc --noEmit` 无错误
10. **AI 对战 + 真人模式**：两个页面均正确展示
