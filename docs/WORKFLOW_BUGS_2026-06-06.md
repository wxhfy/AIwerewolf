# AI 狼人杀代码审查 Bug 汇总

> 从 4 个子 agent 审查结果中提取，已排除 3 个已修复的 bug（奶穿、狼刀狼队友、屠边判定）

---

## 📋 审查覆盖

| Agent | 文件 | 状态 | 问题数 |
|-------|------|------|--------|
| #1 | `backend/engine/rules.py` | ✅ 完成 | 7 条（2 Critical, 2 High, 2 Medium, 1 Low） |
| #2 | `backend/engine/game.py` | ✅ 完成 | 10 条（2 Critical, 2 High, 3 Medium, 3 Low） |
| #3 | `backend/engine/models.py` | ✅ 完成 | 7 条（1 High, 2 Medium, 4 Low） |
| #4 | `backend/engine/visibility.py` | ❌ 无有效输出 | API 安全拦截 |

---

## 🔴 Critical 级别（2 条）

### C1. Agent 线程安全缺失
**严重性**: Critical  
**位置**: `backend/engine/game.py:1358-1416` (`_batch_ask`)  
**问题**: `_batch_ask` 在主线程调用 `agent.update(view, request)` 后，将 `call_fn(agent)` 提交给 ThreadPoolExecutor。`agent.update()` 会修改 agent 内部状态（对话历史、记忆），但多线程并发访问同一 agent 对象时无锁保护。如果 observer 回调或嵌套阶段在并行批次完成前再次调用该 agent，会导致状态损坏。  
**影响**: Agent 对话历史损坏、决策上下文错乱  
**修复**: 添加每个 agent 的独占锁：`self._agent_locks: dict[str, threading.RLock]`，用 `with self._agent_locks[player.id]:` 包裹 `agent.update()` 和 `call_fn(agent)`

---

### C2. 夜晚行动并发竞态条件
**严重性**: Critical  
**位置**: `backend/engine/game.py:618-693` (`_night_role_actions_parallel`)  
**问题**: Guard + Seer 在后台线程运行，Wolf 在主线程运行，三者并发写入 `state.night_actions`（Guard 写 `guard_target_id`，Wolf 写 `wolf_votes/wolf_target_id`，Seer 写 `seer_target_id`）。`_shared_lock` 只保护 `_log()` 和 `_set_phase()`，不保护 `NightActions` 字段赋值。Wolf 队内投票依赖顺序可见性（每个狼人看到前一个狼的投票），但并发 Guard/Seer 线程可能导致 PlayerView 不一致。  
**影响**: `state.night_actions` 字段竞态写入，Wolf 协作数据损坏  
**修复**: 用 `with self._shared_lock:` 包裹 `_guard_phase`、`_wolf_phase`、`_seer_phase` 中所有 `state.night_actions` 字段赋值

---

## 🟠 High 级别（5 条）

### H1. 投票结果与遗言顺序错误
**严重性**: High  
**位置**: `backend/engine/game.py:1077-1080` (`_day_resolve`)  
**问题**: 代码先调用 `_last_words_phase(target_id)`（L1077），再记录 "was voted out"（L1080）。标准狼人杀流程：公布投票结果 → 被放逐者遗言 → 出局。当前玩家看到遗言时还不知道谁被投出。  
**影响**: 违反 CLAUDE.md 规则"投票结果应在遗言之前"，观战体验混乱  
**修复**: 将 L1080 的 `self._log(...)` 移到 L1077 之前

---

### H2. Wolf 队信息泄露风险
**严重性**: High  
**位置**: `backend/engine/game.py:777-793` (`_wolf_phase`)  
**问题**: Wolf 阶段用 `_run_actor_sequence`（顺序执行），每个狼人看到前面狼的投票。但 `_wolf_phase` 在主线程运行时，Guard/Seer 后台线程并发修改 `state.night_actions`。狼人的 PlayerView（由 `Visibility.for_player` 构建）可能读到部分更新的状态快照。  
**影响**: Wolf 协作假设一致性，但并发 Guard/Seer 写入可能导致 view 不一致  
**修复**: 要么串行化整个夜晚序列（移除并行），要么对所有 `NightActions` 读写加锁

---

### H3. 8 人局配置狼侧偏强
**严重性**: High  
**位置**: `backend/engine/rules.py:54-116` (`WOLFCHA_ROLE_CONFIGS`)  
**问题**: 8 人局配置 3W + 3G + 2V（狼人占 37.5%），标准狼人杀平衡比例为 25-30%。3 狼只需杀 2 个好人就达到 3v3 平局，早期胜率过高。  
**影响**: 8 人局狼人胜率统计上显著偏高，游戏体验失衡  
**修复**: 改为 2W + 4G + 2V（25%），与 7P/10P 配置一致

---

### H4. 屠边胜利条件缺失
**严重性**: High  
**位置**: `backend/engine/game.py:1581-1599` (`_check_win`)  
**问题**: 仅检查狼人数 ≥ 好人数（平局条件），未实现"屠边"：所有神民出局或所有村民出局时狼人立即获胜。例如 5 神全灭 + 3 村民存活 vs 2 狼，狼应立即获胜，但当前代码会等到 2v2 平局。  
**影响**: 游戏拖长，失去"屠边"的戏剧性结局  
**修复**: 在平局检查前添加：`if not alive_gods or not alive_villagers: winner = Alignment.WOLF, reason = '屠边'`

---

### H5. public_dict() 泄露角色能力状态
**严重性**: High  
**位置**: `backend/engine/models.py:332-338` (`GameState.public_dict`)  
**问题**: `public_dict()` 暴露 `role_abilities`（`witch_heal_used`, `hunter_can_shoot`, `idiot_revealed` 等），玩家可推测场上有女巫/猎人/白痴。  
**影响**: 打破信息隔离，玩家通过公开 API 推测角色配置  
**修复**: 将 `role_abilities` 移到 `moderator_dict()` 专用，前端只在裁判/观众视角展示

---

## 🟡 Medium 级别（7 条）

### M1. 多猎人同时死亡只开一枪
**严重性**: Medium  
**位置**: `backend/engine/game.py:894-904` (`_night_resolve`) 和 `1098-1106` (`_day_resolve`)  
**问题**: 循环遍历死者，若 `role==HUNTER` 则设置 `pending_hunter_id`。如果两个猎人同时死亡（如一个被刀、一个被毒），`pending_hunter_id` 被覆盖，只有最后一个开枪。  
**影响**: 标准配置只有 1 个猎人，但自定义配置或 bug 导致 2+ 猎人时规则违反  
**修复**: 改为 `pending_hunter_ids: list[str]`，循环积累所有猎人 ID

---

### M2. 守卫重复守护限制未传递给 Agent
**严重性**: Medium  
**位置**: `backend/engine/game.py:707-714` (`_guard_phase`)  
**问题**: 守卫不能连续两晚守同一人（L707 检查），但 `legal_targets` 仍包含上次守护对象。守卫 Agent 收到的候选目标列表包含非法选项，决策被静默拒绝。  
**影响**: 守卫 LLM agent 重复选择非法目标，浪费 token，决策日志混乱  
**修复**: `visibility.py` 的 `_legal_targets` 中，为 `NIGHT_GUARD_ACTION` 过滤掉 `state.night_actions.last_guard_target_id`

---

### M3. 猎人开枪 → 警徽移交 → 游戏结束后阶段恢复错误
**严重性**: Medium  
**位置**: `backend/engine/game.py:1098-1106` (`_day_resolve`)  
**问题**: 如果猎人开枪（L1100）→ 警徽移交（L1102）→ `_check_win` 设置 winner，阶段仍恢复为 `DAY_RESOLVE`（L1105）而非 `GAME_END`。  
**影响**: 事件日志中阶段顺序混乱，游戏逻辑正确但可观测性差  
**修复**: 在猎人开枪和警徽移交后检查 `if self.state.winner is not None: return`

---

### M4. actions.py 缺少 Alignment 导入
**严重性**: Medium  
**位置**: `backend/engine/actions.py:1-8, 63`  
**问题**: L63 使用 `Alignment.WOLF` 但未 import `Alignment`，靠 Python 延迟绑定（通过 GameState 导入链）工作。静态分析（mypy/pyright）失败。  
**影响**: 类型检查失败，重构 models.py 时可能意外破坏 actions.py  
**修复**: 添加 `from backend.engine.models import Alignment`

---

### M5. wolf_votes 与 wolf_target_id 数据不一致
**严重性**: Medium  
**位置**: `backend/engine/models.py:263-271` (`NightActions`)  
**问题**: `wolf_votes` 是 `dict[str, str]`（狼 ID → 提议目标），`wolf_target_id` 是最终共识。如果狼投票分歧，`wolf_votes` 包含未被采纳的目标，前端可能误读。  
**影响**: 裁判 UI 或日志显示不一致数据  
**修复**: 为 `NightActions` 添加 docstring："`wolf_votes` 是个人提议（可能冲突），`wolf_target_id` 是多数票结果（权威来源）"

---

### M6. Wolf 阶段并发状态读取不一致
**严重性**: Medium  
**位置**: `backend/engine/game.py:777-793` (`_wolf_phase`)  
**问题**: Wolf 顺序投票时每个狼看到前面狼的投票（`previous_votes`），但同时 Guard/Seer 后台线程在写 `state.night_actions`，狼的 `PlayerView` 可能读到部分更新状态。  
**影响**: Wolf 协作假设一致视图，但并发写入可能导致不一致  
**修复**: 文档化字段所有权（wolf_votes 只由主线程修改，Guard/Seer 只碰各自字段），或对所有读写加锁

---

### M7. 夜晚阶段顺序非显而易见
**严重性**: Medium  
**位置**: `backend/engine/phases.py:46-56`  
**问题**: 夜晚行动顺序（守卫 → 狼人 → 女巫 → 预言家 → 结算）在并行执行模型下不明显。Guard/Wolf/Seer 并行运行，女巫串行。代码审查者需要追踪 `_night_role_actions_parallel` 实现才能验证顺序合规。  
**影响**: 代码可维护性差，未来修改可能意外破坏顺序依赖  
**修复**: 在 `phases.py` L50-54 添加注释："并行执行保留逻辑依赖：Guard/Wolf/Seer 写不同字段（独立），女巫依赖 wolf_target_id 因此后执行"

---

## 🟢 Low 级别（7 条）

### L1. Wolf 自刀在 legal_targets 中
**严重性**: Low  
**位置**: `backend/engine/visibility.py:81-87` (`_legal_targets`)  
**问题**: `NIGHT_WOLF_ACTION` 的 `legal_targets` 包含所有存活玩家，包括狼队友。CLAUDE.md 明确规定"狼刀目标不能是狼人"。  
**影响**: LLM Agent 收到包含狼队友的候选列表，虽然 ActionValidator 会拒绝，但增加提示混乱  
**修复**: `_legal_targets` 中为 `NIGHT_WOLF_ACTION` 过滤 `alignment != Alignment.WOLF`

---

### L2. _night_role_actions_parallel 文档误导
**严重性**: Low  
**位置**: `backend/engine/game.py:618-627` (docstring)  
**问题**: Docstring 说"Wolf 内部投票是顺序的所以保持同步"，但实际 Wolf 在主线程、Guard/Seer 在后台线程并发修改状态。  
**影响**: 维护者误解并发模型  
**修复**: 重写 docstring："Guard/Seer 并行（线程池），Wolf 主线程顺序投票，三者时间重叠，需锁保护状态修改"

---

### L3. Wolf 投票平局打破规则未文档化
**严重性**: Low  
**位置**: `backend/engine/game.py:777-793` (`_majority_target`)  
**问题**: `_majority_target` 使用 `sorted(tied)[0]` 字典序选择第一个目标，无随机性。2 狼投不同目标时始终选 ID 较小者。  
**影响**: 确定性平局打破可能不符合传统狼人杀（讨论或裁判随机）  
**修复**: 文档化平局规则，或改用 `self.rng.choice(tied)` 随机化

---

### L4. 原子 phase 枚举值无 handler
**严重性**: Low  
**位置**: `backend/engine/phases.py:46-77`  
**问题**: `default_phase_handlers()` 只定义 `NIGHT_START`、`DAY_START`、`HUNTER_SHOOT`、`BADGE_TRANSFER`。原子阶段（`NIGHT_GUARD_ACTION`、`DAY_VOTE` 等）在 Phase 枚举中但无 handler。如果代码调用 `phase_manager.run(Phase.DAY_VOTE)` 会 KeyError。  
**影响**: 未来代码误用原子阶段会崩溃  
**修复**: 添加注释："只有复合阶段和特殊阶段有 handler，原子阶段是复合阶段内部步骤，不应传给 phase_manager.run()"

---

### L5. public_dict/moderator_dict 不处理 None 集合
**严重性**: Low  
**位置**: `backend/engine/models.py:312-344`  
**问题**: `list(self.badge.candidates)` 假设 candidates 非 None。如果意外设置 `badge.candidates = None`，会 TypeError。  
**影响**: 当前代码用 `field(default_factory)` 初始化，不会 None，但缺乏防御性  
**修复**: 改为 `list(self.badge.candidates or [])`

---

### L6. votes dict 包含已死玩家的旧投票
**严重性**: Low  
**位置**: `backend/engine/game.py:986, 1700-1708`  
**问题**: 如果玩家在投票阶段中途死亡（如白天狼自爆），其旧投票留在 `state.votes`。`_eligible_day_voters()` 阻止死者投新票，但旧条目未清理。  
**影响**: 审计日志或前端"谁投了票"列表可能包含已死玩家  
**修复**: 每次投票阶段开始时 `state.votes = {}`（L462/478/1059 已实现），或死亡后 `state.votes = {k:v for k,v in state.votes.items() if state.player(k).alive}`

---

### L7. moderator_dict 不包含 decision_records
**严重性**: Low  
**位置**: `backend/engine/models.py:356-372`  
**问题**: `moderator_dict()` 包含 `night_actions` 和 `events`，但不含 `decision_records`（agent 决策 + prompt + 推理 + 延迟）。复盘分析需要审计轨迹。  
**影响**: 导出 moderator_dict 会丢失决策审计数据  
**修复**: 添加 `'decision_records': [r.__dict__ for r in self.decision_records]`（可选参数 `include_audit=False` 避免实时 WS 帧过大）

---

## 📊 统计

- **Critical**: 2 条（Agent 线程安全、夜晚并发竞态）
- **High**: 5 条（遗言顺序、Wolf 信息泄露、8P 失衡、屠边缺失、角色能力泄露）
- **Medium**: 7 条（多猎人、守卫限制、阶段恢复、导入缺失、数据不一致、并发读、顺序非显然）
- **Low**: 7 条（Wolf 自刀提示、文档误导、平局规则、原子 phase、None 处理、死者投票、审计缺失）

**总计**: 21 条新问题（不含 3 个已修复）

---

## ⚠️ 优先级建议

1. **立即修复（Critical）**: C1 Agent 线程安全、C2 夜晚并发竞态
2. **本周修复（High）**: H1 遗言顺序、H2 Wolf 信息泄露、H5 角色能力泄露、H4 屠边条件
3. **下周修复（High-Medium）**: H3 8P 平衡、M1-M4（多猎人、守卫限制、阶段恢复、导入）
4. **技术债（Medium-Low）**: 其余 10 条
