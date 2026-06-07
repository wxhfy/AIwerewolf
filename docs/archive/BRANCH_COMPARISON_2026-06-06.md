# 分支对比报告：origin/main vs feat/settings-page

**生成时间**: 2026-06-06 23:15  
**共同祖先**: `05b32d1` (fix: SSL retry + inter-game cooldown)

---

## 📊 总体差异统计

| 指标 | 远程 main | 本地 feat/settings-page |
|------|-----------|------------------------|
| **新增提交** | 5 个 | 6 个 |
| **新增文件** | 104 个 | 5 个 |
| **修改文件** | 25 个 | 20 个 |
| **总代码变更** | +15,916 -251 | +2,193 -183 |

---

## 🔀 提交历史对比

### 远程 main 独有（5个提交）

1. **0f38a56** - `feat: warm tone daytime speech cards + night mode adaptation`
   - UI 优化：暖色调白天发言卡片
   
2. **a444c59** - `fix: resolve DAY_RESOLVE infinite loop — distinguish resume from day advance`
   - **Critical Bug 修复**：DAY_RESOLVE 无限循环
   
3. **b00c56f** - `feat: UX优化 — 重构发言/时间线组件，新增投票面板、状态栏`
   - 大规模 UX 重构（roy 的工作）
   
4. **6777886** - `feat: 真人模式独立页面 + 大厅狼人杀主题 + 阶段同步修复`
   - 真人模式页面
   
5. **4a64d39** - `feat: 全面优化游戏体验 — 打字机队列、阶段同步、UI面板、转场动画`
   - 游戏体验优化

### 本地 feat/settings-page 独有（6个提交）

1. **797af99** - `fix: 修复10个核心bug (3 Critical已修 + 7 High/Medium新修)`
   - **10 个核心 bug 修复**
   
2. **8a825cf** - `fix: 修复3个狼人杀核心规则bug (Critical)`
   - **3 个 Critical 规则 bug**
   
3. **b616725** - `feat: 添加设置页面 - 主持/全局视角、中英文、自定义API Key`
   - 设置页面功能
   
4. **f54b64c** - `fix: last-resort fallback was broken`
   
5. **16d53de** - `perf: parallel day speeches`
   
6. **65e6f91** - `fix: fallback JSON extraction`

---

## 📁 文件差异详情

### 本地独有新增文件（5个）

```
✅ docs/CODE_REVIEW_BUGS_2026-06-06.md         (手动审查发现的 3 个 Critical bugs)
✅ docs/SUMMARY_2026-06-06.md                  (工作总结)
✅ docs/WORKFLOW_BUGS_2026-06-06.md            (Workflow 发现的 21 个 bugs)
✅ frontend/components/SettingsModal.tsx       (设置页面组件)
⚠️  .env.backup.1780715278                     (备份文件，应该 gitignore)
```

### 远程独有新增文件（104个）

#### Agent Skills（80+个文件）
```
📂 .agents/skills/ui-designer/                  (UI 设计技能)
   - SKILL.md
   - assets/app-overview-generator.md
   - assets/design-system.md
   - assets/vibe-design-template.md

📂 .agents/skills/vercel-react-best-practices/  (React 最佳实践)
   - SKILL.md, README.md, AGENTS.md
   - rules/async-*.md (8个异步规则)
   - rules/bundle-*.md (7个打包规则)
   - rules/client-*.md (4个客户端规则)
   - rules/js-*.md (15个 JS 优化规则)
   - rules/rendering-*.md (12个渲染规则)
   - rules/rerender-*.md (15个重渲染规则)
   - rules/server-*.md (9个服务器规则)
```

#### 文档（13个）
```
📄 docs/DESIGN.md                              (设计文档)
📄 docs/agent-system-design.md                 (Agent 系统设计)
📄 docs/ai-spectate-architecture.md            (AI 观战架构)
📄 docs/interview-frontend-guide.md            (前端面试指南)
📄 docs/interview-master-guide.md              (主持面试指南)
📄 docs/plan-speech-sync-fix.md                (发言同步修复计划)
📄 docs/state-interaction-architecture.md      (状态交互架构)
📄 docs/unified-game-page-design.md            (统一游戏页面设计)
📄 docs/ux-audit-report-2026-05-29.md          (UX 审计报告)
📄 docs/ux-test-report-2026-05-23.md           (UX 测试报告)
📄 docs/html_plan/AI-Werewolf-human-ai-design-v2.html
📂 docs/superpowers/specs/                      (3个设计规范)
```

#### 图片资源（7个）
```
🖼️ 2.png
🖼️ game.png
🖼️ Snipaste_2026-05-28_09-52-44.png
🖼️ frontend/pho/*.png (4个)
🖼️ frontend/public/portraits/1.svg
```

---

## ⚔️ 共同修改的文件（冲突风险分析）

### 🔴 **高冲突风险**（核心引擎）

#### 1. `backend/engine/game.py`
- **本地改动**: +289 -163 行（并发安全 + 奶穿 + 屠边 + Agent 锁）
- **远程改动**: -24 行（DAY_RESOLVE 无限循环修复）
- **冲突概率**: ⚠️ **极高** — 都在 `_begin_night()` 和阶段逻辑
- **远程关键修复**: 
  ```python
  # 远程的修复（解决无限循环）
  if self._phase_done(Phase.NIGHT_START) and self.state.phase.value.startswith("NIGHT"):
      return
  ```
- **本地的修复**:
  ```python
  # 本地简化了条件（可能重新引入 bug）
  if self._phase_done(Phase.NIGHT_START):
      return
  ```
- **⚠️ 问题**: 本地的简化版本可能不能正确处理 DAY_RESOLVE → NIGHT_START 的转换！

#### 2. `backend/engine/phases.py`
- **本地改动**: 小幅修改
- **远程改动**: 小幅修改
- **冲突概率**: 🟡 中等

#### 3. `backend/app.py`
- **本地改动**: +21 行（可能是调试/配置）
- **远程改动**: +3 -1 行
- **冲突概率**: 🟡 中等

### 🟡 **中等冲突风险**（LLM 相关）

#### 4. `backend/llm/deepseek.py`
- **本地改动**: +335 行（新增 DeepSeek 支持）
- **远程改动**: +4 -1 行（小修改）
- **冲突概率**: 🟢 低（改动区域不同）

#### 5. `backend/llm/__init__.py`
- **本地改动**: +10 -1 行
- **远程改动**: 可能有变化
- **冲突概率**: 🟡 中等

### 🟢 **低冲突风险**（前端）

#### 6-12. 前端组件
```
frontend/app/page.tsx                          (本地：设置页面集成)
frontend/hooks/useRoomStream.ts                (本地：小修改)
frontend/hooks/useGameDerivedState.ts          (远程：大改)
frontend/hooks/usePhaseTransition.ts           (远程：大改)
frontend/components/game/*                     (远程：UI 大重构)
```
- **冲突概率**: 🟡 中等（前端有较多 UX 重构）

---

## 🚨 **Critical 发现**

### 1. DAY_RESOLVE 无限循环 Bug（已被远程修复，本地可能重新引入）

**远程的修复（a444c59）**:
```python
# 精确的条件：只有在 NIGHT 阶段才跳过
if self._phase_done(Phase.NIGHT_START) and self.state.phase.value.startswith("NIGHT"):
    return
```

**本地的修改（797af99）**:
```python
# 简化的条件（可能有问题）
if self._phase_done(Phase.NIGHT_START):
    return
```

**⚠️ 风险**: 本地的简化可能导致 DAY_RESOLVE → NIGHT_START 转换时，day 不递增，重新进入无限循环！

### 2. 并发安全修复冲突

本地大量修改了并发逻辑（ThreadPoolExecutor + Agent 锁），远程也修改了阶段流转。这两个改动可能互相影响。

---

## 📋 **修改文件分类汇总**

### 本地独有修改（9个）
```
backend/agents/cognitive/agent_loop.py        (认知循环)
backend/agents/cognitive/reflect.py           (反思)
backend/db/persist.py                         (持久化)
backend/engine/actions.py                     (行动验证)
backend/engine/models.py                      (模型定义)
backend/engine/rules.py                       (规则 - 8人局平衡)
backend/eval/llm_judge.py                     (评测)
frontend/components/SettingsModal.tsx         (设置页面)
frontend/types/index.ts                       (类型定义)
```

### 远程独有修改（8个）
```
frontend/app/globals.css                      (全局样式)
frontend/app/layout.tsx                       (布局)
frontend/app/room/[id]/play/_components/*     (游戏页面组件 x3)
frontend/components/game/*                    (游戏组件 x9)
frontend/hooks/*                              (Hooks x3)
frontend/lib/*                                (工具函数 x2)
frontend/next.config.js                       (Next.js 配置)
```

### 共同修改（7个，冲突热点）
```
🔴 backend/engine/game.py                     (核心引擎 - 高冲突)
🟡 backend/engine/phases.py                   (阶段管理 - 中冲突)
🟡 backend/app.py                             (应用入口 - 中冲突)
🟡 backend/llm/deepseek.py                    (LLM 集成 - 低冲突)
🟡 frontend/app/page.tsx                      (首页 - 中冲突)
🟡 frontend/hooks/useRoomStream.ts            (房间流 - 低冲突)
```

---

## 💡 **合并策略建议**

### 🎯 **推荐方案：谨慎合并（Merge with Manual Review）**

#### Step 1: 先把本地备份
```bash
git branch feat/settings-page-backup
```

#### Step 2: 合并远程 main
```bash
git merge origin/main
```

#### Step 3: 手动解决冲突（重点关注）

**必须手动检查的文件**:
1. ✅ `backend/engine/game.py` 的 `_begin_night()` 方法
   - 保留远程的精确条件检查（避免无限循环）
   - 同时保留本地的并发安全修复
   
2. ✅ `backend/engine/phases.py`
   - 合并双方的阶段逻辑改动
   
3. ✅ `frontend/app/page.tsx`
   - 保留本地的设置页面集成
   - 同时保留远程的 UX 改进

#### Step 4: 运行完整测试
```bash
# 启动后端
cd backend && python app.py

# 启动前端
cd frontend && npm run dev

# 测试关键场景
1. 创建 8 人局
2. 运行完整游戏（检查 DAY_RESOLVE 是否还有无限循环）
3. 检查设置页面是否正常
4. 检查 UI 是否正常
```

#### Step 5: 提交合并结果
```bash
git add .
git commit -m "merge: 合并 origin/main (UX优化) + feat/settings-page (核心bug修复)"
git push origin feat/settings-page
```

---

## 🔍 **需要特别注意的代码段**

### ⚠️ 关键冲突点 1: `_begin_night()` 方法

**远程版本**（正确处理无限循环）:
```python
def _begin_night(self) -> None:
    # Resume guard: skip re-init ONLY when resuming mid-night (phase is still
    # a NIGHT_* step from a restored snapshot). When the previous day just
    # ended (phase == DAY_RESOLVE / HUNTER_SHOOT / BADGE_TRANSFER), we MUST
    # advance to the next night — phase_done[current_day] alone can't tell
    # these apart because both have NIGHT_START marked done for the current
    # day. Without the phase check, day stays at 1 and play_until_blocked
    # spins forever on DAY_RESOLVE → run(NIGHT_START) → skip.
    if self._phase_done(Phase.NIGHT_START) and self.state.phase.value.startswith("NIGHT"):
        return
    self.state.day = self.state.day + 1
    # ...
```

**本地版本**（简化了条件）:
```python
def _begin_night(self) -> None:
    # Resume safety: use _phase_done which checks current day.
    # On first call (day=0): phase_done[0] empty → proceed → day→1 → mark day 1.
    # On resume (day=1): phase_done[1] has NIGHT_START → skip (already started).
    if self._phase_done(Phase.NIGHT_START):
        return
    self.state.day = self.state.day + 1
    # ...
```

**⚠️ 合并时必须**:
- 采用远程的完整条件检查
- 同时保留本地的其他并发安全改动

---

## 📈 **代码质量对比**

| 维度 | 本地 feat/settings-page | 远程 origin/main |
|------|------------------------|------------------|
| **Bug 修复** | ✅ 10 个核心 bug（Critical 级别） | ✅ 1 个 Critical（无限循环） |
| **新功能** | ✅ 设置页面 | ✅ 大规模 UX 优化 + Agent skills |
| **性能优化** | ✅ 并发安全（ThreadPoolExecutor + 锁） | ⚠️ 可能有并发问题 |
| **文档** | ✅ 3 份详细 bug 报告 | ✅ 13 份设计/架构文档 |
| **测试覆盖** | ⚠️ 未提及 | ⚠️ 未提及 |
| **风险** | 🔴 可能重新引入无限循环 bug | 🟡 缺少并发安全修复 |

---

## ✅ **最终建议**

### 优先级排序

1. **🔴 立即处理**: 合并时必须保留远程的 `_begin_night()` 精确条件检查
2. **🟡 重点测试**: 合并后完整运行一局游戏，验证无限循环已修复
3. **🟢 可选**: 将远程的 Agent skills 和文档也拉下来（对开发很有帮助）

### 时间估算

- 合并操作: 10-15 分钟
- 冲突解决: 30-45 分钟
- 完整测试: 20-30 分钟
- **总计**: 1-1.5 小时

---

生成时间: 2026-06-06 23:15  
生成者: 小爪 🐾
