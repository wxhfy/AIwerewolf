# 对局页细节微调

## Context

当前对局页有四个细节问题需要改进，提升观看/游玩体验。

## 改动清单

### 1. 自动滚动到最新消息

**文件**: `frontend/app/room/[id]/play/page.tsx`

- 事件滚动容器加 `ref`（`scrollRef`）
- `useEffect` 监听 `gameState.events.length`，变化时自动 `scrollTop = scrollHeight`
- 用户手动上滚 > 50px 时暂停自动滚动，滚回底部恢复

### 2. 系统消息与用户消息分离

**文件**: `frontend/components/game/ChatBubble.tsx`、`frontend/app/room/[id]/play/page.tsx`

三种消息样式：
- **系统消息**（PHASE_CHANGED, GAME_START, GAME_END, SYSTEM_MESSAGE）：居中、小字号、带阶段图标、不同字体
- **用户发言**（CHAT_MESSAGE）：保持现有聊天气泡样式
- **进程记录**（VOTE_CAST, PLAYER_DIED, NIGHT_ACTION, HUNTER_SHOT 等）：色条样式

ChatBubble 扩展：新增 `type: "system" | "chat" | "action"` prop。系统消息用 `isSystem` prop 居中渲染。

### 3. 投票/行动实时展示

**文件**: `frontend/components/game/VoteTargetGrid.tsx`、`frontend/components/game/ActionPanel.tsx`

VoteTargetGrid 上方显示当前已有投票记录（从 `gameState.votes` 读取），展示"X号已投Y号"。

### 4. 玩家卡片角色标签

**文件**: `frontend/components/game/PlayerCard.tsx`、`frontend/app/room/[id]/play/page.tsx`

- PlayerCard 新增 `showRole?: boolean` prop
- 当 `showRole=true` 时，公开视角也显示自己的角色名（右下角小标签）
- 狼人额外显示 "🐺 队友: 张三, 李四"
- 从 gameState.players 中筛选同阵营玩家获得狼队友列表
- PlayerCard 新增 `wolfTeammates?: string[]` prop

## 验证

1. `npx tsc --noEmit` 零错误
2. AI 模式运行一局 → 聊天区自动滚到最新消息
3. 人机模式 → 投票时显示投票进度
4. 公开视角 → 自己卡片显示角色标签
