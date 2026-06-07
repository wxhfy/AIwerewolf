# AI 对战 / 真人参与 — UI 统一设计方案

> 当前两套页面各自维护，共享 80% 结构但存在 **7 处差异** 和 **2 处关键 bug**。
> 目标：合并为单一 `GamePage`，通过 `mode` 参数派发差异行为。

---

## 1. 当前状态：双页面 diff

### 1.1 结构对比

```
play/page.tsx (AI, 253行)          human/page.tsx (真人, 241行)
─────────────────────────────      ─────────────────────────────
useGamePageController              useGamePageController          ← ✅ 相同
deriveStatusText                   useHumanDisplayState           ← ❌ 不同 StatusBar 实现
controller.voteDisplay             手动 isVotePanelVisible         ← ❌ 投票逻辑重复
controller.completedIdsRef         独立 completedRef              ← 🐛 打字机重复实现！
controller.onChatComplete          独立 onComplete                ← 🐛 打字机重复实现！
controller.scroll (autoScroll)     (无)                           ← ❌ 真人缺自动滚动
VoteResultPanel ✅                 VoteResultPanel ❌              ← ❌ 真人缺投票结果
—                                  selectedTarget/submitted/speech ← 真人专用状态
—                                  role reveal overlay            ← 真人专用
—                                  ActionBar                      ← 真人专用
PlayerRail (isHumanMode=false)     PlayerRail (isHumanMode=true)  ← ✅ 仅 props 差异
EventTimeline (非 hideDayHeaders)  EventTimeline (hideDayHeaders)  ← ⚠️ 行为差异
ThinkingBubble (all AI)           ThinkingBubble (skip human)     ← ⚠️ 条件差异
```

### 1.2 两个关键 Bug

**Bug 1: 真人页自建打字机，与 Controller 脱节**

```typescript
// human/page.tsx L97-99 — 完全独立的打字机实现
const completedRef = useRef<Set<string>>(new Set());
const [, ct] = useState(0);
const onComplete = useCallback(..., []);

// 但 controller 已有:
controller.completedIdsRef   // ← 被忽略
controller.onChatComplete    // ← 被忽略
controller.displayPhase      // ← 被忽略（真人 StatusBar 自己算 PHASE_LABEL）
```

后果：`controller.displayPhase` 在真人模式下永远不会更新，`BadgePanel` 收到的 completedIds 是空的。

**Bug 2: 真人页投票逻辑未同步修复**

```typescript
// human/page.tsx L69-75 — 缺少 BADGE 排除
const isVotePanelVisible = (phase.includes("VOTE") || phase.includes("ELECTION"));
// AI 页已修复为: && !phase.includes("BADGE")
```

---

## 2. 统一方案：单一 GamePage 组件

### 2.1 目标架构

```
app/room/[id]/play/page.tsx          ← 唯一游戏页面
  │  ?mode=ai     → AI 对战模式
  │  ?mode=human  → 真人参与模式
  │
  ├── 共享层（100% 复用）
  │   ├── DayNightBlinkTransition
  │   ├── PhaseOverlayCoordinator
  │   ├── GameHeader
  │   ├── PlayerRail (left/right)
  │   ├── BadgePanel
  │   ├── EventTimeline
  │   ├── VotePanel / VoteResultPanel
  │   ├── GameEndPanel
  │   └── ThinkingBubble
  │
  └── 差异层（按 mode 条件渲染）
      ├── StatusBar          → deriveStatusText | HumanStatusBar
      ├── PlayerRail props   → selectable / onSelectTarget
      ├── EventTimeline props → hideDayHeaders
      ├── ThinkingBubble      → skipHumanPlayer
      ├── ActionBar (human only)
      └── RoleRevealOverlay (human only)
```

### 2.2 组件差异矩阵

| 组件 | AI 模式 | 真人模式 | 统一方式 |
|---|---|---|---|
| **StatusBar** | `deriveStatusText(gameState)` | `HumanStatusBar` (含 cycle/phaseLabel/actor) | `mode === "human" ? <HumanStatusBar /> : <AIStatusBar />` |
| **VotePanel** | `controller.voteDisplay` | `controller.voteDisplay` | ✅ 统一使用 centralized hook |
| **VoteResultPanel** | 投票完成后显示 | 投票完成后显示 | ✅ 统一（真人模式也应看到结果） |
| **PlayerRail** | `isHumanMode=false` | `isHumanMode=true` + `selectable` | props 驱动 |
| **EventTimeline** | `hideDayHeaders` 不传 | `hideDayHeaders` | props 驱动 |
| **ThinkingBubble** | 所有 pending speech | 跳过自己 | 条件：`seat !== humanSeat` |
| **ActionBar** | 无 | 发言输入 / 目标选择 / 提交 | `mode === "human" && isMyTurn && <HumanActionBar />` |
| **RoleReveal** | 无 | 3s 身份揭示 | `mode === "human" && <RoleRevealOverlay />` |
| **AutoScroll** | `controller.scroll` | `controller.scroll` | ✅ 统一（真人页当前缺失） |

### 2.3 统一后的 GamePage 伪代码

```tsx
export default function GamePage() {
  const params = useParams<{ id: string }>();
  const mode = useSearchParams().get("mode") || "ai";
  const ctrl = useGamePageController(params.id);
  const { gameState, derived, phase, scroll, voteDisplay } = ctrl;
  const isHuman = mode === "human";

  // ── Human-specific derived state ──
  const humanPlayer = isHuman
    ? gameState?.players?.find(p => p.seat === ctrl.humanSeat)
    : undefined;
  const humanDisplay = useHumanDisplayState(gameState, humanPlayer, ctrl.viewMode);

  // ── Human action state ──
  const [selectedTarget, setSelectedTarget] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [speech, setSpeech] = useState("");
  const [revealDone, setRevealDone] = useState(false);

  // ── Shared layout ──
  return (
    <ErrorBoundary>
      <div data-phase={phase.visualPhaseGroup}>
        <DayNightBlinkTransition ... />
        <PhaseOverlayCoordinator ... />
        {ctrl.fetchError && <FetchErrorPanel ... />}
        {showNightOverlay && <NightOverlay />}

        <GameHeader
          isHumanMode={isHuman}
          canRun={!isHuman && !ctrl.isPlaying && !gameState?.winner}
          ...
        />

        <MobilePlayerRail ... />

        <div className="flex flex-1">
          <PlayerRail side="left"
            isHumanMode={isHuman}
            selectable={isHuman && needsTarget && !submitted}
            selectedTargetId={selectedTarget}
            onSelectTarget={setSelectedTarget}
            ...
          />

          <main>
            {/* ═══ StatusBar: mode-polymorphic ═══ */}
            {isHuman
              ? <HumanStatusBar display={humanDisplay} displayPhase={ctrl.displayPhase} ... />
              : <AIStatusBar gameState={gameState} derived={derived} language={ctrl.language} />
            }

            <BadgePanel
              gameState={gameState}
              completedIds={ctrl.completedIdsRef.current}
              ...
            />

            {/* ═══ Vote: unified ═══ */}
            {voteDisplay.mode.type === "LIVE_VOTING" && <VotePanel ... />}
            {voteDisplay.mode.type === "RESULT" && <VoteResultPanel ... />}

            <div ref={scroll.scrollRef} onScroll={scroll.handleScroll} className="timeline-scroll">
              <EventTimeline
                dayBlocks={derived.dayBlocks}
                completedIds={ctrl.completedIdsRef.current}
                onChatComplete={ctrl.onChatComplete}
                isHumanMode={isHuman}
                humanSeat={ctrl.humanSeat}
                hideDayHeaders={isHuman}  // 真人模式隐藏天标头
                ...
              />
              <ThinkingBubble
                playerName={...}
                skipIfHuman={isHuman && pending?.seat === ctrl.humanSeat}
              />
            </div>

            {/* ═══ Human Action Bar ═══ */}
            {isHuman && isMyTurn && revealDone && !submitted && (
              <HumanActionBar
                needsTarget={needsTarget}
                isSpeech={isSpeech}
                speech={speech}
                setSpeech={setSpeech}
                selectedTarget={selectedTarget}
                setSelectedTarget={setSelectedTarget}
                onSubmit={submitAction}
                pending={gameState?.pending_input}
              />
            )}
            {submitted && <SubmittedIndicator />}
          </main>

          <PlayerRail side="right" ... />  {/* same as left */}
        </div>

        {/* ═══ Role Reveal (human only) ═══ */}
        {isHuman && !revealDone && humanPlayer && (
          <RoleRevealOverlay
            role={humanPlayer.role}
            alignment={humanPlayer.alignment}
            seat={humanPlayer.seat}
            name={humanPlayer.name}
            wolfTeammates={humanDisplay.wolfTeammates}
            onRevealed={() => setRevealDone(true)}
          />
        )}

        <GameEndPanel ... />
      </div>
    </ErrorBoundary>
  );
}
```

### 2.4 关键修复

| 修复 | 当前问题 | 统一后 |
|---|---|---|
| **打字机** | 真人页自建 `completedRef`，controller 的 `completedIdsRef` 被忽略 | 统一使用 `ctrl.completedIdsRef` + `ctrl.onChatComplete` |
| **投票逻辑** | 真人页手动计算，缺少 BADGE 排除 + 无 VoteResultPanel | 统一使用 `ctrl.voteDisplay` |
| **自动滚动** | 真人页缺失 | 统一使用 `controller.scroll` |
| **StatusBar** | 两套完全不同的实现 | 拆分 `AIStatusBar` / `HumanStatusBar` 子组件，page 层按 mode 选择 |

### 2.5 真人专用 UI 组件

#### HumanStatusBar

```tsx
function HumanStatusBar({ display, displayPhase, language }: Props) {
  return (
    <div className="...">
      <span>{display.cycle} · {display.phaseLabel}</span>
      {display.currentActor && (
        <span>
          · {display.currentActor.seat}号 {display.currentActor.name}
          {display.isMyTurn && display.canAct ? "轮到你了" : "行动中"}
        </span>
      )}
      <span>存活: {display.aliveCount}/{display.totalCount}</span>
    </div>
  );
}
```

#### HumanActionBar

```tsx
function HumanActionBar({
  isSpeech, speech, setSpeech, needsTarget,
  selectedTarget, selectedPlayer, setSelectedTarget,
  onSubmit, pending, language
}: Props) {
  if (isSpeech) return <SpeechInput ... />;
  return <TargetSelector ... />;
}
```

#### RoleRevealOverlay

```tsx
function RoleRevealOverlay({ role, alignment, seat, name, wolfTeammates }: Props) {
  // 3s 自动消失的身份揭示蒙层
  useEffect(() => {
    const t = setTimeout(() => onRevealed(), 3000);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-center justify-center">
      <p className="text-5xl">{alignment === "wolf" ? "🐺" : "🏘️"}</p>
      <p className="text-3xl font-bold">{tRole(role)}</p>
      <p>{seat}号 {name}</p>
      {wolfTeammates.length > 0 && <p>狼队友：{wolfTeammates.join(" · ")}</p>}
    </div>
  );
}
```

---

## 3. 文件变更计划

### 删除

```
frontend/app/room/[id]/human/page.tsx  → 删除（功能合并到 play/page.tsx）
```

### 修改

```
frontend/app/room/[id]/play/page.tsx    → 合并两个页面
  + HumanStatusBar 子组件
  + HumanActionBar 子组件
  + RoleRevealOverlay 子组件
  + mode 分支逻辑
  + useHumanDisplayState 调用
```

### 新建（可选拆分）

```
frontend/app/room/[id]/play/_components/
  AIStatusBar.tsx          ← page.tsx 当前的 StatusBar 定义
  HumanStatusBar.tsx       ← human/page.tsx 当前的 StatusBar 定义
  HumanActionBar.tsx       ← 真人操作栏（发言输入 + 目标选择 + 提交）
  RoleRevealOverlay.tsx    ← 身份揭示蒙层
```

### 路由变更

```
/room/[id]/play?mode=ai      → 不变
/room/[id]/play?mode=human   → 新路由（原 /room/[id]/human → 重定向）
/room/[id]/human             → 301 → /room/[id]/play?mode=human
```

---

## 4. 迁移风险评估

| 风险 | 级别 | 缓解措施 |
|---|---|---|
| StatusBar 行为差异 | 低 | 拆分为两个子组件，互不影响 |
| 打字机统一 | 中 | 移除真人页 `completedRef`，改为 controller 的；需回归测试打字机 |
| 自动滚动新增 | 低 | 纯新增功能，不影响现有行为 |
| VoteResultPanel 新增 | 低 | 纯新增，真人模式也能看到投票结果 |
| 路由变更 | 低 | 保留 `/room/[id]/human` 做 301 重定向 |

---

## 5. 收益

| 指标 | 统一前 | 统一后 |
|---|---|---|
| 游戏页面文件 | 2 个（play/human 各 250 行） | 1 个（~350 行 play/page.tsx + 4 个子组件） |
| 打字机实现 | 2 套（1 套 bug） | 1 套 |
| 投票逻辑 | 2 套（1 套缺修复） | 1 套 |
| 共享框架代码 | 80% 重复 | 0% 重复 |
| 修复同步 | 需要改两个文件 | 改一个文件 |
| 真人模式功能缺失 | 无自动滚动、无投票结果 | 补齐 |
