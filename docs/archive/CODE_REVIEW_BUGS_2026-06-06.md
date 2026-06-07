# AI Werewolf 代码审查 - Bug 报告

**审查时间**: 2026-06-06 19:30 - 进行中  
**审查方式**: 手动代码审查 + 7-agent 并行 workflow（运行中）  
**审查者**: Claude Opus 4.8 (max effort)

---

## 🔴 Critical Bugs（必须立即修复）

### Bug #1: 奶穿规则未实现 ⭐️⭐️⭐️⭐️⭐️

**位置**: `backend/engine/game.py:866-875` `_night_resolve()`

**CLAUDE.md 规则**:
> "同守同救"（奶穿）：若同一玩家同时被守卫守护和女巫解药救，该玩家仍死亡。

**当前代码**:
```python
if (
    wolf_target_id
    and not self.state.night_actions.witch_save          # 女巫没救
    and wolf_target_id != self.state.night_actions.guard_target_id  # 守卫没守
):
    deaths.append({"player_id": wolf_target_id, "reason": "wolf"})
```

**问题**:
- 守卫守了 X **或** 女巫救了 X → X 存活
- **正确规则**: 守卫守了 X **且** 女巫救了 X → X 死亡（奶穿）

**影响**: 
- 影响 100% 的游戏
- 违反狼人杀核心规则
- 可能让玩家永生（同时被守卫和女巫保护）

**修复方案**:
```python
def _night_resolve(self) -> None:
    # ... 前面代码保持不变 ...
    
    wolf_target_id = self.state.night_actions.wolf_target_id
    guard_target_id = self.state.night_actions.guard_target_id
    witch_save = self.state.night_actions.witch_save
    
    # 奶穿判定：同时被守和被救 = 死亡
    both_guarded_and_saved = (
        wolf_target_id 
        and witch_save 
        and wolf_target_id == guard_target_id
    )
    
    if wolf_target_id:
        if both_guarded_and_saved:
            # 奶穿：同守同救 → 死
            deaths.append({"player_id": wolf_target_id, "reason": "milk_through"})
            self._log(
                EventType.SYSTEM_MESSAGE, 
                "public", 
                {"message": f"Guard and witch both protected {self.state.player(wolf_target_id).name}, resulting in death (奶穿)."}
            )
        elif not witch_save and wolf_target_id != guard_target_id:
            # 既没被守也没被救 → 死
            deaths.append({"player_id": wolf_target_id, "reason": "wolf"})
        # else: 只被守或只被救（但不同时）→ 活
    
    # ... 后续代码保持不变 ...
```

**测试用例**:
```python
# 场景 1: 只有守卫守
wolf_target = "P1"
guard_target = "P1"
witch_save = False
→ 预期: P1 存活

# 场景 2: 只有女巫救
wolf_target = "P1"
guard_target = "P2"
witch_save = True
→ 预期: P1 存活

# 场景 3: 同守同救（奶穿）
wolf_target = "P1"
guard_target = "P1"
witch_save = True
→ 预期: P1 死亡（当前 bug：P1 存活）

# 场景 4: 既没守也没救
wolf_target = "P1"
guard_target = "P2"
witch_save = False
→ 预期: P1 死亡
```

**边界情况**:
- 奶穿的猎人应该能开枪（因为本质是狼刀，不是毒死）
- 建议使用 `reason="milk_through"` 而不是 `"poison"`

---

### Bug #2: 狼人可以刀狼队友 ⭐️⭐️⭐️⭐️⭐️

**位置**: `backend/engine/actions.py:52-59` `ActionValidator.validate()`

**CLAUDE.md 规则 #1**:
> 狼刀目标不能是狼人：狼人击杀的候选目标只能是 **非狼人存活玩家**。狼人不能选择自己或狼队友作为击杀目标。

**当前代码**:
```python
if target.id == actor.id and decision.action_type in {
    ActionType.VOTE,
    ActionType.ATTACK,    # 只检查了不能刀【自己】
    ActionType.DIVINE,
    ActionType.WITCH_POISON,
    ActionType.SHOOT,
}:
    return False
```

**问题**:
- ATTACK 只验证了 `target != self`
- **没有验证 `target.alignment != WOLF`**
- 狼人可以击杀自己的队友

**影响**:
- 影响 100% 的狼人局
- 违反基本规则
- 狼人可能误杀队友（特别是 LLM agent 可能犯此错误）
- `_majority_target()` 也没有过滤，会直接采纳狼队友作为目标

**修复方案**:

**方案 A: 在 ActionValidator 中修复（推荐）**
```python
# backend/engine/actions.py

class ActionValidator:
    def validate(self, state: GameState, decision: Decision) -> bool:
        rule = ACTION_RULES[decision.action_type]
        actor = state.player(decision.actor_id)
        
        # ... 前面的验证保持不变 ...
        
        if rule.requires_target:
            if decision.target_id is None:
                return False
            try:
                target = state.player(decision.target_id)
            except KeyError:
                return False
            if not target.alive:
                return False
            
            # 禁止自杀
            if target.id == actor.id and decision.action_type in {
                ActionType.VOTE,
                ActionType.ATTACK,
                ActionType.DIVINE,
                ActionType.WITCH_POISON,
                ActionType.SHOOT,
            }:
                return False
            
            # ✅ 新增：禁止狼人刀狼队友
            if decision.action_type == ActionType.ATTACK:
                from backend.engine.models import Alignment
                if target.alignment == Alignment.WOLF:
                    return False
        
        return True
```

**方案 B: 在 _wolf_phase 中兜底过滤（双重保险）**
```python
# backend/engine/game.py:779

self.state.night_actions.wolf_target_id = self._majority_target(self.state.night_actions.wolf_votes)

# ✅ 新增：兜底检查，如果目标是狼则随机选非狼玩家
final_target = self.state.player(self.state.night_actions.wolf_target_id)
if final_target.alignment == Alignment.WOLF:
    logger.warning(f"Wolf team voted for teammate {final_target.name}, fallback to non-wolf target")
    non_wolves = [p for p in self.state.alive_players if p.alignment != Alignment.WOLF]
    if non_wolves:
        self.state.night_actions.wolf_target_id = self.rng.choice(non_wolves).id
```

**测试用例**:
```python
# 7人局：2狼（P1, P2）+ 5好人（P3-P7）

# 场景 1: 狼刀自己
actor = P1 (Wolf)
target = P1 (Wolf)
→ 预期: validate() 返回 False（当前：False，正确）

# 场景 2: 狼刀狼队友
actor = P1 (Wolf)
target = P2 (Wolf)
→ 预期: validate() 返回 False（当前 bug：True）

# 场景 3: 狼刀好人
actor = P1 (Wolf)
target = P3 (Villager)
→ 预期: validate() 返回 True
```

---

## 🟡 High Priority Bugs（需要尽快修复）

### Bug #3: 胜利条件不完整 - 缺少"屠边"判定 ⭐️⭐️⭐️⭐️

**位置**: `backend/engine/game.py:1581-1599` `_check_win()`

**CLAUDE.md 胜利条件**:
- **好人赢**: 所有狼人出局 ✅ (已实现)
- **狼人赢（屠边）**: 所有神民出局 **或** 所有村民出局 ❌ (未实现)
- **狼人赢（屠城）**: 所有好人出局 ✅ (已实现，通过人数平局)

**当前代码**:
```python
def _check_win(self) -> bool:
    alive_wolves = [p for p in self.state.alive_players if p.alignment == Alignment.WOLF]
    alive_village = [p for p in self.state.alive_players if p.alignment == Alignment.VILLAGE]
    
    if not alive_wolves:
        winner = Alignment.VILLAGE  # ✅ 正确
    elif len(alive_wolves) >= len(alive_village):
        winner = Alignment.WOLF  # ⚠️ 只检查了人数平局
```

**问题**:
- 只检查了 `wolves >= village`（人数平局 = 屠城）
- **没有检查"屠边"** (所有神出局 或 所有村民出局)

**影响**:
- 狼人可能提前胜利但游戏继续（例如：2狼 + 3村民 + 0神，狼已屠边但未达平局）
- 游戏可能拖得过长

**修复方案**:
```python
def _check_win(self) -> bool:
    if self.state.winner is not None:
        return True
    
    alive_wolves = [p for p in self.state.alive_players if p.alignment == Alignment.WOLF]
    alive_village = [p for p in self.state.alive_players if p.alignment == Alignment.VILLAGE]
    
    winner: Alignment | None = None
    reason = ""
    
    # 好人赢：所有狼死
    if not alive_wolves:
        winner = Alignment.VILLAGE
        reason = "all_wolves_dead"
    
    # 狼人赢：屠城（人数平局或狼人更多）
    elif len(alive_wolves) >= len(alive_village):
        winner = Alignment.WOLF
        reason = "wolves_reached_parity"
    
    # ✅ 新增：狼人赢 - 屠边
    else:
        # 区分神民和平民
        gods = [p for p in alive_village if p.role in {Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD, Role.IDIOT}]
        villagers = [p for p in alive_village if p.role == Role.VILLAGER]
        
        if not gods and villagers:
            # 所有神出局，只剩村民
            winner = Alignment.WOLF
            reason = "all_gods_dead"
        elif not villagers and gods:
            # 所有村民出局，只剩神
            winner = Alignment.WOLF
            reason = "all_villagers_dead"
    
    if winner:
        self.state.winner = winner
        self._log(EventType.GAME_END, "public", {"winner": winner.value, "reason": reason})
        return True
    
    return False
```

**测试用例**:
```python
# 场景 1: 所有狼死 → 好人赢
alive: 5 好人 (任意角色)
→ 预期: VILLAGE 赢

# 场景 2: 人数平局 → 狼人赢（屠城）
alive: 2 狼 + 2 好人
→ 预期: WOLF 赢

# 场景 3: 所有神死，剩村民 → 狼人赢（屠边）
alive: 2 狼 + 3 村民 + 0 神
→ 预期: WOLF 赢（当前 bug：游戏继续）

# 场景 4: 所有村民死，剩神 → 狼人赢（屠边）
alive: 2 狼 + 0 村民 + 3 神
→ 预期: WOLF 赢（当前 bug：游戏继续）

# 场景 5: 神民都有，狼人少数 → 游戏继续
alive: 2 狼 + 2 村民 + 3 神
→ 预期: 游戏继续
```

---

## 📝 待确认问题（需要进一步验证）

### Issue #1: 奶穿的猎人能否开枪？

**位置**: `backend/engine/game.py:1549-1550` `_kill()`

**当前逻辑**:
```python
if player.role == Role.HUNTER and reason == "poison":
    self.state.abilities.hunter_can_shoot = False
```

**问题**:
- 奶穿应该用什么 `reason`？
- 如果用 `"milk_through"`，猎人可以开枪（符合规则，因为本质是狼刀）
- 如果用 `"poison"` 或 `"wolf"`，可能会有歧义

**建议**:
- 奶穿使用 `reason="milk_through"`
- 猎人可以开枪（因为是狼刀+守卫+女巫的复合，但主因是狼刀）

---

### Issue #2: 投票结果是否在遗言之前公布？

**CLAUDE.md 规则 #4**:
> 投票结果应在遗言之前：白天放逐投票结果公布后，被放逐者发表遗言。不能先显示遗言再显示投票结果。

**需要检查**: `_day_resolve()` 和 `_last_words_phase()` 的调用顺序

**位置**: `backend/engine/game.py:1077-1078`

```python
self._last_words_phase(target_id)  # line 1077
self._kill(target_id, "vote")      # line 1078
```

**当前逻辑**:
1. `_day_resolve()` 统计投票
2. `_last_words_phase()` 被放逐者遗言
3. `_kill()` 标记死亡
4. 日志记录 "X was voted out"

**疑问**: 投票结果的日志是在哪里记录的？需要确认是在遗言前还是后。

---

## 🔍 Workflow 审查进行中

7 个子 agent 正在并行审查：
1. ✅ 规则引擎 (`backend/engine/rules.py`)
2. 🔄 游戏流程 (`backend/engine/game.py`) - 运行中
3. 🔄 数据模型 (`backend/engine/models.py`) - 运行中
4. 🔄 信息隔离 (`backend/engine/visibility.py`) - 运行中
5. 🔄 Agent 系统 (`backend/agents/`) - 运行中
6. 🔄 API 设计 (`backend/app.py`) - 运行中
7. 🔄 前端集成 (`frontend/`) - 运行中

Workflow 完成后将整合所有发现的问题。

---

## 📊 Bug 统计（目前手动发现）

| 级别 | 数量 | 问题 |
|------|------|------|
| 🔴 Critical | 2 | 奶穿规则、狼刀队友 |
| 🟡 High | 1 | 屠边判定 |
| 📝 待确认 | 2 | 奶穿猎人、投票顺序 |
| **总计** | **5** | |

---

**下一步**:
1. 等待 workflow 完成（预计 5-10 分钟）
2. 整合 workflow 发现的问题
3. 按优先级修复 bugs
4. 编写测试用例验证
5. 更新 `docs/DEVELOPMENT_ISSUES.md`

**报告更新时间**: 2026-06-06 19:45
