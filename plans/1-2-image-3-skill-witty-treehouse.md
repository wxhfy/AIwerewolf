# 狼人杀前端重构计划：大厅 → 准备 → 对局 + 人机交互

## Context

当前前端只有一个观战页面（page.tsx），缺少大厅(P01)、准备页(P03)、人机交互UI（发言输入/投票/倒计时）、明显日夜切换。后端已完整支持人机模式（`POST /api/rooms` 传 `human_seat`，`POST /api/rooms/{id}/action` 提交人类操作，返回含 `pending_input` 的快照）。需重构前端路由和组件来匹配。

## 路由架构

```
/                           → Lobby Page (新)
/room/[id]/prepare          → Preparation Page (新)
/room/[id]/play             → Game Board Page (从当前 page.tsx 重构)
```

所有页面通过 `layout.tsx` 的 `<AppProvider>` 共享状态。

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `app/page.tsx` | 大厅页，替代当前观战页 |
| 新建 | `app/room/[id]/prepare/page.tsx` | 准备确认页 |
| 新建 | `app/room/[id]/play/page.tsx` | 游戏对局页（从当前page.tsx搬过来并增强） |
| 删除 | `app/page.tsx` | 迁到 `/room/[id]/play` |
| 新建 | `components/game/ChatBubble.tsx` | 聊天气泡 |
| 新建 | `components/game/ActionPanel.tsx` | 人机操作面板（发言/投票/夜晚行动） |
| 新建 | `components/game/CountdownTimer.tsx` | 60秒倒计时条 |
| 新建 | `components/game/VoteTargetGrid.tsx` | 投票目标选择网格 |
| 修改 | `app/globals.css` | 增强日夜切换视觉效果 |
| 修改 | `lib/i18n.ts` | 新增大厅/准备/人机交互翻译键 |
| 修改 | `context/AppContext.tsx` | 新增 humanSeat 状态 |

## Task A: 大厅页 (`/`)

- 游戏配置表单：玩家数量(7-12)、Agent类型(启发式/LLM)、模式(AI对战/真人参与)、座位号(1-N)、Seed
- 语言切换（中/EN）
- 「开始游戏」按钮 → `POST /api/rooms?...&human_seat=X` → `router.push(/room/{id}/prepare)`
- Footer: AI Werewolf 品牌

## Task B: 准备页 (`/room/[id]/prepare`)

- 显示房间摘要：玩家数、Agent类型、种子、真人座位
- 座位预览网格（占位卡片 1-N）
- 「确认开始」→ `POST /api/rooms/{id}/start?show_private=true` → 获得 snapshot → `router.push(/room/{id}/play)`
- 「返回大厅」链接

## Task C: 对局页重构 (`/room/[id]/play`)

- 保留三栏布局（左22% 玩家 + 中 flex-1 + 右15% 玩家）
- 顶部栏：品牌 + 阶段/天数 + 模式/视角切换 + AI模式运行按钮
- 中间：状态条 + ChatBubble事件流(AI模式继续用旧EventItem) + ActionPanel(当pending_input存在时)
- 人机模式：用 HTTP 轮替（`POST /action` → 新snapshot），不用WebSocket
- AI模式：保持WebSocket

## Task D: 人机交互组件

**ChatBubble** — 发言聊天气泡，左对齐（他人）/右对齐（自己），圆形头像 + 名字 + 内容

**ActionPanel** — 根据 `pending_input.action_type` 动态渲染：
- `speech`: 提示"轮到你了" + textarea + CountdownTimer + 提交
- `vote`: 提示"投票放逐" + VoteTargetGrid + 提交
- 夜晚行动: 目标下拉 + 女巫额外救药选项 + 提交
- 提交：`POST /api/rooms/{id}/action` {target_id, speech, save} → 刷新snapshot

**CountdownTimer** — 60秒倒计时条，正常(棕色)→20s警告(琥珀)→10s危险(红)，归零自动提交

**VoteTargetGrid** — 存活玩家卡片网格，点击选中(金色边框)，适配 `PlayerCard` 现有 `isSelected` prop

## Task E: 日夜视觉增强

- 夜晚CSS变量改为暗色调：`--color-bg: #1A1816`，`--color-card: #24211E`
- 金色主色：`--color-primary: #D4AF37`
- 文字反色：`--color-text: #EDE8E0`
- 夜晚叠加层：径向渐变遮罩 + 星星粒子(CSS伪元素)
- 800ms过渡动画
- 头部栏显示白天/夜晚图标 + 文字标签

## Task F: 收尾

- i18n新增键：humanMode, aiMode, playerCountLabel, humanSeatLabel, enterPrepare, confirmStart, yourTurn, typeSpeech, voteExile, selectTarget, submitAction, timeLeft, timeOut, nightPhaseBanner, dayPhaseBanner, chatLabel
- AppContext新增 `humanSeat` 状态
- TypeScript全量检查

## 验证方式

1. `npx tsc --noEmit` 零错误
2. 启动前后端，访问 `http://localhost:3001`
3. 大厅页 → 配置参数 → 创建房间
4. 准备页 → 确认 → 进入对局
5. 人机模式：发言输入 + 倒计时 + 投票选择 + 夜晚行动
6. 日夜切换：CSS变量明显变化 + 星星粒子 + 头部图标
7. `curl http://localhost:3001/api/health` → `{"status":"ok"}`
