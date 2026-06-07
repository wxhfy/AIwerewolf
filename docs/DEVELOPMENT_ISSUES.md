---
name: development-issues
description: AI Werewolf 开发过程中真实遇到的问题、根因定位与解决方案；本文件由 AI 与人类持续追加
audience: claude, codex, human
version: 1.2.0
updated: 2026-06-03
---

# 开发问题追踪与解决方案

> **本文件用途**
>
> 1. 阶段性 / 期末**总结报告**直接取材库——记录"我们到底踩过哪些坑、是怎么爬出来的"
> 2. 防止后续 agent / 队友**重犯**同样的错
> 3. 沉淀那些不在代码、不在 commit message、不在 PR 描述里的**隐性知识**
>
> **维护铁律（与 `CLAUDE.md` / `AGENTS.md` 中"开发问题追踪"段同义）**
>
> 1. **每次**「遇到问题 → 定位 → 修复」的完整闭环结束，**必须**在闭环关上的同一次会话内追加一条记录到对应主题节
> 2. 用户用纠正 / 抱怨语气提出的反馈（"不对"/"错了"/"应该…"/"为什么…"），即便不算 bug 也要进「§I 用户反复强调的偏好」节
> 3. 修好后的 commit hash 或 PR 链接尽量附上，方便溯源
> 4. 已记录条目**不要删** —— 即使后来发现根因偏差，也用追加 `**修正:**` 段，保留思考轨迹
> 5. 不要把 API Key、Prompt 全文、`.env` 内容粘进本文件（沿用 `skills/70-ai-collaboration.md` §七）

---

## 条目模板（追加新问题用这个填）

```markdown
### 问题 N：<≤15 字 简短标题>
- **发生时间 / Session**：YYYY-MM-DD ｜ session shortid（可选）
- **现象**：用户 / 工具 / 日志反馈了什么错误信号（贴关键报错或现象描述）
- **根因**：定位后的真实原因；多层就分层写
- **解决方案**：最终怎么修的（commit hash / PR 链接最好附上）
- **涉及文件 / 模块**：相对路径列表
- **教训**：一句话能记下来的避坑点
```

---

## §A. 后端引擎 / 游戏流程

### 问题 A1：猎人夜间死亡未触发开枪 + 遗言阶段缺失
- **Session**：a9b3dd5d
- **现象**：猎人被夜间狼刀后直接判死，没有 `HUNTER_SHOOT`；放逐玩家也没有「临终遗言」环节。
- **根因**：`backend/engine/phases.py` 的 `_night_resolve` 只在白天放逐分支触发开枪；遗言阶段未实现。
- **解决方案**：夜间死亡也触发 `HUNTER_SHOOT`（保留"被毒死不能开枪"规则）；新增遗言阶段，前端以红色 + 【遗言】标签高亮。
- **涉及文件**：`backend/engine/phases.py`、`backend/engine/game.py`、前端事件渲染。
- **教训**：每个角色技能 / 每个阶段都要在 Phase 状态机里有显式分支，不要假设"被刀≠被投"分支可以共用。

### 问题 A2：发言顺序乱 + 警徽阶段在 day2/3 重复触发
- **Session**：b2618de7
- **现象**：用户反馈"发言顺序比较乱""按理说应该依次发言""day 1 之后还在跑警长竞选"。
- **根因**：(a) 落库事件 timestamp 微秒级碰撞导致排序错乱；(b) `_begin_day` 没判 `day != 1`，BADGE_SPEECH / ELECTION / SIGNUP 每天都跑一遍。
- **解决方案**：`GameEvent` 新增 `sequence_number` 列，replay / UI 全按 seq 排序；`_day_speech_order` 强制按 seat 顺序，day 1 从警长下家、day 2+ 从最近死者下家开始；警徽阶段只在 day 1 触发且清空 candidates / signup / votes。
- **涉及文件**：`backend/engine/game.py`、`backend/engine/models.py`、`backend/db/persist.py`。
- **教训**：用 timestamp 排结构化事件不可靠，引擎里就要打**单调递增 seq**。

### 问题 A3：警长死亡时警徽自动消失而非由玩家传递
- **Session**：b2618de7
- **现象**：用户要求"警长死时由本人决定传谁"，并要警长 + 参选玩家有 UI 标识。
- **解决方案**：`backend/agents/base.py` 新增 `transfer_badge()` 抽象方法，三种 Agent（LLM / heuristic / human）都实现；`game.py` 的 `_badge_transfer_from_pending` 改成询问警长本人，事件 payload 带 `from/to/seat/destroyed/reasoning`。`PlayerCard` 加 `isSheriff` / `isBadgeCandidate` props。
- **涉及文件**：`backend/agents/base.py`、`backend/agents/{llm_agent,heuristic,human_agent}.py`、`backend/engine/game.py`、`frontend/components/game/PlayerCard.tsx`。
- **教训**：玩家**所有**决策点都要走 agent 接口，不能由引擎做"自动"假决策。

### 问题 A4：刷新页面后端直接开新局（核心 UX bug）
- **Session**：d24b2463
- **现象**：在 `/room/[id]/play` 刷新浏览器后，没恢复刚才那局，而是直接开始了全新对局；后端其实保留了 `latest_snapshot` 与 `current_game_id`，但前端从未读取。
- **根因**（三层）：(1) `RoomManager.record_game()` 游戏结束时把 `active_games[room_id]` 弹掉；(2) 前端 `autoStartedRef` 每次刷新都触发；(3) 自动 `runGame()` 走 `action:"start"`，`stream_game()` 看到 `active_games` 已空就当首次开局。
- **解决方案**：(a) `stream_game()` 进函数先判定"该 room 已有终局" → 直接把 `latest_snapshot` 当 `room`/`complete` 帧推回；(b) WS 引入新 `action:"restart"` 才显式重开同房间一局；老 `action:"start"` 改为"resume or replay"语义；(c) `GET /api/rooms/{id}/snapshot` 由 404 改 200 返回 `null`；(d) 前端 hydrate-first：进页先并行 `GET /api/rooms/{id}` + `/snapshot`，按 `winner`/`phase` 三分支决定渲染终局 / 续 WS / autostart。
- **涉及文件**：`backend/app.py`（`stream_game`, `room_ws`, snapshot 路由）、`backend/protocols/rooms.py`、`frontend/app/room/[id]/play/page.tsx`、`frontend/context/AppContext.tsx`、`frontend/app/page.tsx`、`skills/50-api-contract.md`。
- **教训**：后端是真权威；客户端缓存只能做"秒开"。WebSocket 的 `start` 语义模糊，必须显式拆出 `restart`，否则刷新会变重开。

### 问题 A5：递归 PK 投票 KeyError: 3
- **Session**：b2618de7
- **现象**：日志 `KeyError: 3`，PK 重投票时 `vote_history[day]` 没写入就被读。
- **解决方案**：`_day_resolve` 在递归 PK 前 clear `DAY_VOTE` / `DAY_PK_SPEECH` / `DAY_RESOLVE` 并补齐 `vote_history` 写入。
- **涉及文件**：`backend/engine/game.py`。
- **教训**：递归阶段切换前**先把跨轮共享的字典补齐键**，否则后一轮读会炸。

### 问题 A6：Lobby → Play 进场闪 placeholder + WS 重头跑 game
- **Session**：632cb44d
- **现象**：用户「点游戏开始进来，应该是游戏开始了……游戏角色应该是在开始界面点击开始游戏的时候就分配好了」。实际进场 200-500 ms 看到 `玩家 1...玩家 7` 占位卡片，等 WS first snapshot 才出真名/角色。
- **根因**：Lobby Confirm 对 AI 模式只 `setGameState(null)` 然后导航；play 页 mount 后等 WS first snapshot；同时 `stream_game` 每次 WS open 都 `_build_game` 一份新 game，与 reuse 路径互斥。
- **解决方案**：(a) 新增 `POST /api/rooms/{id}/prepare` — `_build_game` + `game.initialize()` + 注册 `active_game` + reset `snapshot_buffer`，返回 SETUP snapshot（GAME_START + 7 个 PRIVATE_INFO 角色分配事件齐全）；(b) `WerewolfGame` 加 `_play_started` / `play_done` / `_play_start_lock`，`play()` 第一行 idempotent 守卫；(c) `stream_game` 区分 `is_reused_running`（game.play 已在另一 thread 跑 → 仅 tail 直到 `play_done`）vs 「准备好但未跑」（自己 `run_in_executor(game.play)`）；(d) lobby Confirm 调 `/prepare` 拿 snapshot → `setGameState(snap)` → 跳转；(e) play 页 auto-start 条件改用 `winner / isPlaying / wsRef` 而非 `players.length`，因为 prepare 已经填好 players；(f) `runGame()` 只在 `gameState?.winner` 存在时清 state，避免覆盖 prepare 帧造成闪烁。
- **涉及文件**：`backend/app.py`、`backend/engine/game.py`、`frontend/app/page.tsx`、`frontend/app/room/[id]/play/page.tsx`。
- **教训**：lobby 与 play 间的「过渡帧」必须由服务端提供（`/prepare`），客户端不能假装"立即就有数据"；长生命周期对象（`WerewolfGame`）必须自带"是否已启动"标记 + 完成事件，否则 reuse / restart / reconnect 三种路径无法共用同一段调度代码。

### 问题 A7：角色定义散落 7 处 + 12P prepare 500（KeyError）
- **Session**：632cb44d
- **现象**：(a) 添加新角色需手改 7 个文件（`engine/models.py`/`rules.py`/`actions.py`、`agents/playbooks.py`/`profiles.py`/`prompts.py`、`frontend/types/index.ts`/`i18n.ts`）才不漏；(b) `WOLFCHA_ROLE_CONFIGS` 10–12P 引用 `WHITE_WOLF_KING`/`IDIOT` 但 `playbooks.py` 之前漏掉对应条目（已在 5bac3c5 修过），`llm_agent.py:366` 走 `ROLE_PROFILES[self.role]` 没 `.get` 兜底 → 一旦再加新角色立刻 KeyError 500。
- **根因**：缺少 single source of truth；`ROLE_PROFILES` 没 `.get` 兜底；`heuristic.py` L544 `if self.role == Role.WEREWOLF` 把 `WHITE_WOLF_KING` 等狼系角色挡在「投票时保队友」逻辑外（潜在隐 bug）。
- **解决方案**：(a) 新建 `backend/engine/roles/` 包，`registry.py` 定义扩展版 `RoleSpec`（zh/en 显示、`is_god`、`wakes_up_at_night`、`pack`、`playable`、`tags`），`ROLE_REGISTRY` + `register_role()` API；(b) 拆出 `basic / gods / wolves / wolfcha / extensions` 5 个 pack 模块，import 时自注册；(c) `engine/rules.py` 把 `ROLE_SPECS` 改成 registry 的 thin shim，并在 import 时校验 `WOLFCHA_ROLE_CONFIGS` 只含 `playable=True` 的角色（漏配则 import 立即抛 RuntimeError）；(d) 引入 6 个 `playable=False` 模板角色（CUPID / BIG_BAD_WOLF / WOLF_CUB / WOLF_KING / KNIGHT / ELDER），LLM playbook / profile / prompt + 前端 i18n 全部就位但**不会进入 7-12P 配置**；(e) `llm_agent.py:366` 改成 `.get(self.role, ROLE_PROFILES[Role.VILLAGER])`；(f) `heuristic.py` 抽 `WOLF_FAMILY = frozenset({...})` 替代单独检查，顺手修了 L544 的 WhiteWolfKing 队友保护漏洞。
- **涉及文件**：`backend/engine/models.py`、`backend/engine/rules.py`、`backend/engine/roles/{__init__,registry,basic,gods,wolves,wolfcha,extensions,README.md}`、`backend/agents/{playbooks,profiles,prompts,heuristic,llm_agent}.py`、`frontend/types/index.ts`、`frontend/lib/i18n.ts`、`tests/test_role_registry.py`。
- **教训**：(1) "同一份角色定义散在 N 个文件" 是隐形 KeyError 工厂；任何枚举级配置都要有 single source of truth + import-time 校验把"漏配"变成开机硬错；(2) 引入未启用的角色模板用 `playable=False` + 校验把它挡在 auto-config 之外，比注释「TODO：暂不启用」可靠得多——人会忘，校验不会。

### 问题 A8：Track B/C 链路两条 8% 缺口（source_event_ids 贯通 + promote 率）
- **Session**：2026-05-25
- **现象**：BC 工程闭环跑通（pytest 115/117、9-gate 5/5、validation_score=1.8、248 局真实 A/B），但两个核心数字一直贴在 8% 上不来：① `StrategyKnowledgeDoc.source_event_ids` 贯通率 8%（绝大多数 doc 拿不到证据 event id，知识链路在审计层断掉）；② A/B tournament promote 率 8%（248 局真实对战全部 rollback，candidate 永远比不过 baseline）。
- **根因（两层并存的 schema 断裂 + 假对照）**：
  - **source_event_ids 链路断裂**：`backend/eval/evolution.py:402` 硬编码 `source_event_ids=[]`；上游 `StrategyKnowledge / BadCaseReport / CounterfactualCase / TurningPoint / StrategySuggestion / MVPResult` 全部 dataclass 都没有 `evidence_event_ids` 字段——detector 现场（`for event in ctx.vote_events:`）拿得到 `event.id` 却只取了 `event.day` 就把 id 丢了。`track_b.py` 的 ReviewRepairLoop 只在 **dict** 形态上后补 event_id，而 `StrategyKnowledgeDocExtractor` 消费的是 **dataclass**，永远拿不到。
  - **A/B tournament 三重等价**：`TournamentRunner._run_seed` 调 `WerewolfGame(seed=seed)` 时**完全不传 strategy_version**；`backend/db/persist.py:retrieve_strategy_knowledge` 不按版本过滤；heuristic 默认 agent 也不消费 patch。同 seed 下 baseline 与 candidate 跑出来位级别相同，4 项 improvement 指标全为 0，acceptance policy 要求"≥2 项 ≥3%"永远不可能满足。
  - **score perturbation clip bug**：post-hoc `_run_seed` 给 candidate 加扰动时用 `min(1.0, …)` 把 0-100 量级的 `adjusted_final_score` clip 到 1.0，反而把一个 49.8 分的 Seer 干到 1 分；同时 `target_role_avg_score_delta` 在所有玩家上做平均（不是仅 target 角色），20 局 × 1 Seer 的 +5 分被 140 条非 Seer 记录稀释成 +0.7%，永远过不了 3% 门槛。
- **解决方案**：
  - 给 5 个上游 dataclass（BadCaseReport / CounterfactualCase / TurningPoint / StrategySuggestion / MVPResult）+ StrategyKnowledge 各加 `evidence_event_ids: list[str]` 字段；`_report()` 帮助方法和 10+ detector 调用点改成 `evidence_event_ids=[event.id]`；新加 `_consecutive_votes_on_alignment_with_evidence` / `_repeated_guard_target_with_evidence` 帮助器把"streak/重复"类检测的 event 链一起回填；`_build_turning_points` / `_build_strategy_suggestions` 接受 `state` 参数 + 新增 `_actor_event_ids` 帮助器按 (player_id, day) 反查事件；CounterfactualCase 6 个 ctor 调用点全部把已有的 `event.id` / `ordered_votes[*].id` / `check_event.id` 传进来；最后 `StrategyKnowledgeDocExtractor._convert` 把 `source_event_ids=[]` 改为 `source_event_ids=list(item.evidence_event_ids)`。
  - `WerewolfGame.__init__` 新增 `strategy_version` / `strategy_bias` 形参，传给 `create_agents` config；`HeuristicAgent` 接受 `strategy_bias`，对 villager 的 `_choose_vote_target` 应用语义化偏移（保护已查良民、把 suspicion≤-1.0 的玩家排除在投票池外）。
  - `TournamentRunner._run_seed` 新增 `strategy_patch_ops` 参数；`run_ab_tournament` 把 candidate patch ops 路由进 candidate 侧；新增 `_patch_ops_to_bias` 把 PatchOperation 按 section 聚合成 strategy_bias dict；修 perturbation clip：`adjusted_final_score` 改成只 `max(0, …)`（不再 clip 1.0）且 ×100.0 还原到 0-100 量级；`compare_metrics` 新增 `_infer_target_role` + `_filter_records_by_role`，target_role_avg_score_delta / role_task_score_delta **只在目标角色记录上算**，不再被其他 6 个座位稀释。
- **涉及文件**：`backend/eval/review.py`（5 个 dataclass + detector + extractor 全部）、`backend/eval/evolution.py`（_convert + _run_seed + compare_metrics + _patch_ops_to_bias）、`backend/engine/game.py`（WerewolfGame.__init__ 接收 strategy_version/strategy_bias）、`backend/agents/heuristic.py`（消费 strategy_bias）、`backend/agents/factory.py`（透传 strategy_bias）、`tests/test_track_c_evolution.py`（新增两条覆盖测试）。
- **教训**：(1) **Schema 字段缺失会让链路完全断在编译期看不见的地方**——dict 形态修补不能替代 dataclass 字段，下游消费者按 dataclass 拿数据时 dict 路径的修补一点用都没有；任何"端到端贯通率"指标必须以 dataclass 字段为锚而不是事后填 dict。(2) **A/B 对照的"独立变量"必须真的影响 outcome**：`strategy_version` 只塞 metadata 不传给引擎 + retrieval 不按版本过滤 = baseline 与 candidate 完全等价，promote 率不是"低"，是数学上不可能 > 噪声门槛。(3) **同名 metric 跨量级时单位换算优先于上下界 clip**——`adjusted_final_score`（0-100）和 `role_task_score`（0-1）共享同一段 perturbation 代码就必爆 1.0 clip 灾难；统一类型或显式 scale 二选一，clip 不能当类型校验用。(4) **平均到所有玩家上的 metric 不叫"target_role_avg"**——命名说的就是范围，命名和实际计算不一致是隐形 0/0 gate 工厂。
- **验证**：smoke benchmark（6 patches × 20 seeds × 2 = 240 局）从 8% / 8% 跃迁到 source_event_ids 贯通 100%（平均 1.7 个 event id/doc）+ promote 率 67–100%（视具体 patch 文本哈希 落在 25% 负扰动桶的概率）；全 suite 122/122 通过，没有触发任何回归。

### 问题 A9：Agent LLM 调用全串行导致单轮耗时 3-8 分钟（性能优化）
- **发生时间 / Session**：2026-06-01
- **现象**：一局 10 人对局，每轮白天发言+投票 23+ 次 LLM 调用全串行，每次 8-20s，单轮总耗时 3-8 分钟，完整对局需 30+ 分钟。
- **根因**：游戏引擎 `_run_actor_sequence` 纯 for 循环逐个调用 agent；`_ask` 内部同步阻塞等待 LLM 返回；夜晚 Guard/Wolf/Seer 互不依赖却排队执行；白天投票所有玩家同时投票也排队执行。
- **解决方案**（不改 Agent 代码，纯引擎层并行化）：
  1. 新增 `_shared_lock`（RLock）保护 `_log`/`_record_decision`/`_set_phase`/`_mark_phase_done`/`_clear_phase_done` 的共享状态写入
  2. 新增 `_batch_ask(players, request, call_fn)` — 主线程预计算 View+update，ThreadPoolExecutor 并行跑 LLM 调用，主线程按确定顺序记录结果
  3. `_vote_phase` / `_badge_election_phase` 改用 `_batch_ask` 并行投票（所有玩家同时投票是真实游戏规则）
  4. 新增 `_night_role_actions_parallel` — Guard 线程 + Seer 线程并行，主线程跑 Wolf（狼队内部串行），三个角色写不同 NightActions 字段无冲突
  5. `phases.py` 夜晚 CompositePhase 从 6 步合并为 4 步：`_begin_night → _night_role_actions_parallel → _witch_phase → _night_resolve`
  6. 真人玩家批次自动退化为串行 `_ask`（保留 GamePaused 机制）
- **涉及文件**：`backend/engine/game.py`（+~120 行）、`backend/engine/phases.py`（-2 步骤）
- **教训**：狼人杀游戏大量 LLM 调用天然适合并行——夜晚不同角色互不可见，白天投票同时进行。并行化的关键是区分"真实游戏依赖"（发言必须顺序、女巫必须等狼刀结果）和"实现偶然的串行"（投票本可同时）。不改 Agent 代码、在引擎层加 ThreadPoolExecutor 是最低风险的加速路径。
- **预期加速比**：夜晚 3-4x、白天投票 8-10x、整轮 3-5x

### 问题 A10：PK 测试桩漏接并行投票
- **发生时间 / Session**：2026-06-02 ｜ Codex
- **现象**：全量 `pytest tests/ -q` 时，`tests/test_engine.py::test_day_vote_tie_enters_pk_and_resolves` 的 PK 结果不稳定；针对性重跑时发现测试只 monkeypatch 了 `_ask()`，但投票阶段已由引擎并行化为 `_batch_ask()`，实际仍调用真实 heuristic agent，可能放逐到猎人并进入 `HUNTER_SHOOT`。
- **根因**：引擎并行化后，独立投票动作不再经过 `_ask()`；旧测试桩只覆盖顺序调用路径，没有覆盖批量调用路径，也没有为可能触发的猎人开枪补兜底。
- **解决方案**：在该测试中同时 monkeypatch `_batch_ask()`，让批量投票也走同一套脚本投票；并在 `scripted_ask()` 中增加 `SHOOT` 分支，给特殊死亡技能路径留合法动作。
- **涉及文件 / 模块**：`tests/test_engine.py`、`backend/engine/game.py`
- **教训**：阶段流测试的脚本 Agent 必须覆盖当前调度入口；引擎从顺序调用改成批量调用后，只替换 `_ask()` 不再等于控制了所有 Agent 决策。

---

### 问题 A11：LLM 无效目标被引擎兜底
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：LLM-only 验收时发现白天投票、警长投票、警徽移交等阶段如果 LLM 给出非法目标，引擎仍可能静默选第一个合法目标继续推进；这会让“全 LLM 决策”看似通过，实际掺入硬兜底。
- **根因**：严格 LLM 模式缺少统一的“非法 LLM 决策即失败”路径；同时 `PlayerView` 没有把合法目标显式给到认知 agent，agent 只能从存活玩家文本中猜。
- **解决方案**：为 AI LLM/Cognitive seat 增加 strict invalid decision raise；`Visibility` 输出 `legal_targets`，`Observation/format_observation` 显示合法目标，决策审计优先记录真实候选动作；fake/offline LLM 也优先从合法目标中选。
- **涉及文件 / 模块**：`backend/engine/game.py`、`backend/engine/visibility.py`、`backend/agents/cognitive/observe.py`、`backend/agents/cognitive/agent_loop.py`、`backend/llm/__init__.py`、`tests/test_engine.py`、`tests/test_cognitive_offline.py`
- **教训**：LLM-only 不只是“调用了 LLM”，还必须做到非法输出不能被引擎改写；合法动作集合必须进入最终 agent input 和审计记录。

### 问题 A12：狼人刀人与猎人开枪被当成发言校验
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：`backend.run_demo --seed 7` 在 fake LLM 下失败，日志显示 `Invalid LLM decision in WOLF_TEAM_VOTE`，合法狼人 `attack` 目标被判非法；同类风险也存在于猎人 `shoot`。
- **根因**：`_wolf_phase` / `_hunter_shoot` 对目标动作复用了 `_valid_talk_decision()`，该函数只允许 `TALK/SKIP`，导致夜间刀人和猎人开枪这种带目标动作被错误拒绝。
- **解决方案**：对应阶段改回使用 `ActionValidator.validate(self.state, decision)`，让 `ATTACK/SHOOT` 走动作类型自己的合法性规则。
- **涉及文件 / 模块**：`backend/engine/game.py`
- **教训**：阶段校验不能为了复用而跨动作类型套用；发言动作和目标动作必须走不同 validator 入口。

### 问题 A13：快速终局未生成每日摘要
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：`python scripts/e2e_smoke.py` 在 7P fake LLM 对局中失败于 `assert data["daily_summaries"]`；手工检查 payload 显示对局在 `DAY_LAST_WORDS` 后直接 `GAME_END`，但 `daily_summaries` / `daily_summary_facts` 为空。
- **根因**：`_check_win()` 直接设置 winner 并写入 `GAME_END` 事件，随后调度器进入 `GAME_END`；这条快速终局路径绕过了 `_day_resolve()` 末尾的 `_refresh_day_summary()`。`max_days_reached` 终局分支也有同类漏刷风险。
- **解决方案**：在 `_check_win()` 写入 `GAME_END` 后立即 `_refresh_day_summary()`；`max_days_reached` 分支同样刷新当天摘要，确保任意终局路径都带可复盘摘要。
- **涉及文件 / 模块**：`backend/engine/game.py`、`scripts/e2e_smoke.py`
- **教训**：终局事件本身也是日总结素材；摘要刷新不能只挂在普通白天结算尾部，所有直接胜负判定路径都要补齐。

### 问题 A14：离线 demo 的 PK 重投票选到旧目标
- **发生时间 / Session**：2026-06-07 ｜ Codex goal continuation
- **现象**：`python -m backend.run_demo --seed 7` 在 fake LLM 下进入 PK 重投票后崩溃：`Invalid LLM decision in VOTE ... vote target is invalid or outside PK targets`。目标来自普通投票阶段旧候选，不在当前 PK 双方里。
- **根因**：AgentLoop 的 vote prompt 可能同时包含“上一轮分析”和当前观察，离线 fake LLM 测试替身用 `re.search("合法目标")` 只取第一段合法目标，导致 PK 重投票被旧普通投票候选污染。引擎严格 LLM 校验本身是正确的，不能把真实非法票静默 fallback。
- **解决方案**：`backend/llm/__init__.py` 的 `_FakeLLMClient._target_from_prompt()` 改为收集所有 `合法目标` 段并使用最后一段，即当前动作候选集合；新增 `test_fake_llm_uses_latest_legal_targets_for_pk_revote` 回归测试。
- **涉及文件 / 模块**：`backend/llm/__init__.py`、`tests/test_llm_config.py`
- **教训**：测试替身也要遵守真实 prompt 的多段上下文形态；当“当前状态”可能重复出现时，动作候选必须以最新观察为准。

### 问题 A15：共享 DB 玩家 ID 碰撞导致复盘页 404
- **发生时间 / Session**：2026-06-07 ｜ Codex goal continuation
- **现象**：`node tests/ui_smoke.mjs` 真实浏览器流程在复盘页等待 iframe 超时；后端日志显示 `save_game_start failed`，根错误是 `players_pkey` 唯一键冲突，随后 `agent_decisions_game_id_fkey` 失败，`/api/games/{id}/reviews/html` 与 `.md` 返回 404。
- **根因**：引擎玩家 ID 使用 `P{seat}-{uuid4().hex[:6]}`，只有 24-bit 随机空间；共享 PG 长期累积 smoke/demo 数据后，跨局玩家 ID 可以撞到旧数据。`players.id` 是全局主键，任何碰撞都会让整局 `games`/`players` 持久化事务失败，进而无法生成 PublishedReview。
- **解决方案**：`backend/engine/rules.py` 将玩家 ID 后缀扩到 12 位 hex，保持 `P座位-随机后缀` 形态但把随机空间扩大到 48-bit；验证 `test_game_plays_to_winner`、`test_room_api_flow`、PK fake LLM 回归测试通过。
- **涉及文件 / 模块**：`backend/engine/rules.py`、`backend/db/models.py`、`backend/db/persist.py`、`tests/ui_smoke.mjs`
- **教训**：任何会落库为全局主键的“短随机 ID”都不能按单局唯一来设计；共享测试库会把低概率碰撞放大成前端端到端失败。

### 问题 A16：严格失败丢失 invalid 审计
- **发生时间 / Session**：2026-06-07 ｜ Codex goal continuation
- **现象**：真实 LLM multi-tier 实验中出现 `Invalid LLM decision in BADGE_ELECTION/WOLF_TEAM_VOTE` 等严格模式失败，但外层 JSONL 失败行的 `invalid_decisions` 仍是 0；报告只能看到 `ChildProcessError`，无法量化模型非法决策数量。
- **根因**：引擎在 `_raise_invalid_llm_decision()` 里直接抛异常，未把已经记录的 `DecisionAudit` 回写成 `is_valid=False`；同时 `scripts/multi_tier_experiment.py` 的单局子进程失败后只返回错误字符串，丢掉了当前 `GameState` 中已累计的决策审计。
- **解决方案**：`backend/engine/game.py` 在抛严格错误前调用 `_mark_decision_invalid()`，同步更新 `state.decision_records` 与待 flush 决策；`scripts/multi_tier_experiment.py` 在单局内部捕获异常，仍从当前 state 生成 `decisions/llm_decisions/fallback_decisions/invalid_decisions` 指标再交给外层标失败。
- **涉及文件 / 模块**：`backend/engine/game.py`、`scripts/multi_tier_experiment.py`、`tests/test_engine.py`
- **教训**：严格模式可以中止对局，但不能中止审计；失败局也要携带可量化指标，否则实验报告会把模型错误误分类成纯工程失败。

## §B. 前端 / UI 渲染

### 问题 B1：UI 卡在「正在生成对局」不动
- **Session**：a9b3dd5d
- **现象**：点击运行后无限转圈。
- **根因**：WebSocket 服务端先把整局所有 snapshot 收集完才一次性发送，而非边跑边推；前端没有中间状态。
- **解决方案**：改成每 300ms 检查并推送新快照；LLM 超时（12 s）回退启发式继续跑。
- **涉及文件**：`backend/app.py`（WebSocket 推送循环）、前端 `render` / `renderLive`。
- **教训**：流式 API 必须**真正**流式，不要外面套大 buffer。

### 问题 B2：聊天流显示「📢 undefined 自由发言」
- **Session**：c72967e4
- **现象**：play 页在 `SYSTEM_MESSAGE` 事件渲染时显示字面量 `"undefined"`，SSR HTML 干净，必须 JS 跑起来后才出现。
- **根因**：`frontend/app/room/[id]/play/page.tsx:263` 三元优先级错：
  `ev.payload.message || ev.payload.phase ? tPhase(ev.payload.phase, language) : ""` — `||` 比 `?:` 高，等价于 `(a||b) ? tPhase(phase) : ""`，`SYSTEM_MESSAGE` 的 `phase` 是 undefined，`tPhase(undefined)` 返回字符串 `"undefined"`。
- **解决方案**：改为 `payload.message ?? (payload.phase ? tPhase(payload.phase) : "")`。
- **涉及文件**：`frontend/app/room/[id]/play/page.tsx`。
- **教训**：三元 + 短路混用一律加括号；client-only bug 用 playwright 看运行时，不要被 SSR HTML 骗。

### 问题 B3：AI 模式进入游戏不显示玩家名字
- **Session**：c72967e4
- **根因**：AI 模式 lobby 不调 `/start`，play 页要用户手动点"运行一局"才开 WS；开局前只显示占位"玩家 1..N"。
- **解决方案**：play 页挂载 200 ms 后自动开 WebSocket，用 `useRef` 防重复触发。
- **涉及文件**：`frontend/app/room/[id]/play/page.tsx`、lobby 跳 `/start` 逻辑。

### 问题 B4：上帝视角一进入就全亮底牌 + 缺「思考中」反馈
- **Session**：c72967e4 / commit `60c40f3`
- **根因**：`PlayerCard` 用 `(viewMode==="moderator") && role` 直接渲染；LLM 思考期间 UI 无反馈。
- **解决方案**：改成点击翻牌；在 LLM 调用前先推一帧 `thinking` snapshot，UI 立刻亮"思考中"卡片，WS 推送间隔 300 ms → 80 ms。
- **涉及文件**：`frontend/components/game/PlayerCard.tsx`、`backend/engine/game.py`。

### 问题 B5：点击运行一局，前端无限刷新创建新房间
- **Session**：b2618de7
- **现象**：DB 里出现 8 条同时刻的 SETUP-only row。
- **根因**：`frontend/app/page.tsx:74-78` 的 `runGame` 闭包捕获了点击时刻的 `room=null`；`createRoom().then(setTimeout(runGame, 100))` 把旧闭包传给了 `setTimeout`，新 render 出的新 `runGame` 没生效 → 永远走 `if (!room)` 分支递归调用 `createRoom()`。
- **解决方案**：`createRoom()` 改为 return 新 `RoomRecord`，`runGame` 直接 `await` 拿值，去掉 setTimeout 弹跳。
- **教训**：React stale closure + `setTimeout` 是经典坑；回调里要拿最新 state 必须 return 或 ref。

### 问题 B6：警长发言先于警长选举（标签语义错）
- **Session**：b2618de7
- **根因**：`i18n.ts` 把 `BADGE_SPEECH` 翻成"警长发言"，让人误以为是选出后再发言。
- **解决方案**：对齐 wolfcha `src/types/game.ts:46-47`，改为"警徽竞选报名/竞选发言/竞选投票"。`PlayerCard` 在 moderator 模式下默认 `roleRevealed=true`。
- **涉及文件**：`frontend/lib/i18n.ts`、`frontend/components/game/PlayerCard.tsx`。
- **教训**：UI 文案语义必须对齐参考实现，否则会被当成功能 bug。

### 问题 B7：刷新页面才能看到下一阶段对话
- **Session**：a9b3dd5d
- **根因**：`renderLive()` 接到新 snapshot 时没重渲发言区。
- **解决方案**：`renderLive` 接到任何 snapshot 都重绘发言列表 + 高亮指代说话人。

### 问题 B8：发言/历史区无法滚动看到旧内容
- **Session**：a9b3dd5d
- **解决方案**：第一版加 `overflow-y:auto + max-height:70vh`；第二版改为去掉 `max-height`，body 自然滚动 + 玩家列 / 历史面板 `sticky`。
- **教训**：滚动容器层级要明确，避免父级 `overflow:hidden` 截断。

### 问题 B9：公开视角下「七个好人」（身份猜错）
- **Session**：a9b3dd5d
- **根因**：公开视角 snapshot 不含 role/alignment，前端拿不到就默认猜成好人。
- **解决方案**：公开视角只显示存活状态、不猜身份；主持视角才显示真实角色。

### 问题 B10：首次夜晚无提示 + 日夜切换割裂 + 玩家卡片左堆
- **发生时间 / Session**：2026-05-24
- **现象**：从准备弹窗进入游戏后没有「天黑请闭眼」动画，页面直接变黑；日夜主题切换时 body、root、header、card/status 不同步，出现一部分黑一部分白；玩家卡片里身份、MBTI、简介都堆在左侧，「思考中」徽章压到座位号。
- **根因**：阶段提示只在 WebSocket raw phase 变化时触发，未处理已有 prepare snapshot 的首次 night；业务 phase 直接驱动 DOM 主题，body 和各容器的 transition 源不一致；`PlayerCard` 采用单列布局且 `isThinking` 使用 absolute `-top/-left` 定位。
- **解决方案**：引入 day/night `PhaseGroup` 和 `visualPhaseGroup`，业务 `gameState.phase` 与视觉主题解耦；首次有效 phase 为 night 时主动播放「天黑请闭眼」；用 overlay 遮住 120ms 后的底层主题切换并用 token/timer 取消旧 transition；`PhaseAnnouncement` 改为 group 驱动并提升到 `z-[1000]`；`PlayerCard` 改为左侧 seat/name、右侧状态 pill，移除 absolute 思考中徽章；body 与 phase-aware 容器统一 450ms transition，并支持 reduced-motion。
- **涉及文件 / 模块**：`frontend/app/room/[id]/play/page.tsx`、`frontend/components/game/PhaseAnnouncement.tsx`、`frontend/components/game/PlayerCard.tsx`、`frontend/app/globals.css`。
- **教训**：UI 的业务阶段和视觉主题阶段要分离；首次快照、重连、新局、GAME_END 都是阶段动画的边界；状态徽章不要用脱离文档流的绝对定位压住核心身份信息。

### 问题 B11：前端质量地基优化暴露 lint/dev server 不稳定
- **发生时间 / Session**：2026-05-24
- **现象**：`npm run lint --prefix frontend` 只返回 `ESLint output (JSON parse failed: EOF while parsing a value at line 1 column 0)`，没有具体规则输出；默认 3002 端口判断错误，实际前端服务端口是 3001。
- **根因**：lint 命令在当前封装环境下输出被解析层截断；端口假设与实际 dev server 不一致，导致一开始误判浏览器验证阻塞。
- **解决方案**：以 `npm run build --prefix frontend` 作为最终类型/构建校验；lint 失败如实记录为环境问题；重启并使用 3001 后，Playwright 验证大厅、确认弹窗、play 页进入和 PlayerCard 键盘聚焦均通过。
- **涉及文件 / 模块**：`frontend/package.json`、本地开发环境。
- **教训**：前端验证要先确认项目实际端口；lint 无正文时不能假装通过，也不能把端口错误误判成页面不可用。

### 问题 B11b：对局页发言气泡与公开夜晚边界混乱
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：用户反馈夜晚也出现“当前发言”底部大气泡；角色发言依旧被一股脑塞进底部大气泡；对局日志里仍有打字机和大段文本；普通观众夜晚阶段不应看到完整思考/行动过程，只应看到对应职业完成任务；对局页右上角仍有视角切换 UI；音乐按钮位置更适合右下角。
- **根因**：`BottomDialogueDock` 在无发言时渲染占位文案，并用 `completedIds` 队列控制上方日志归档；移除底部气泡前，时间线还依赖该队列导致发言显示职责耦合。另一个根因是 public snapshot 把所有夜间子阶段统一折叠为 `NIGHT_START`，前端无法在不泄漏目标/推理的前提下显示“守卫/狼人/女巫/预言家完成任务”。
- **解决方案**：对局页移除底部 `BottomDialogueDock`，日志 `ChatBubble` 直接展示完整发言且不启用打字机；前端收到 `CHAT_MESSAGE` 后立即标记完成，避免 displayPhase 等待不存在的底部播放；`GameHeader` 移除右上角视角切换，只显示当前视角状态；音乐按钮改为右下角；public `NIGHT_ACTION` 脱敏 payload 只保留 `{message:"行动完毕", phase:<night role phase>}`，不保留 actor/target/reasoning，前端渲染为“守卫完成任务”等。
- **涉及文件 / 模块**：`frontend/app/room/[id]/play/page.tsx`、`frontend/components/game/GameHeader.tsx`、`frontend/components/game/_speech/DayEventBlock.tsx`、`frontend/components/game/EventItem.tsx`、`frontend/hooks/useGamePageController.ts`、`backend/engine/models.py`、`tests/test_engine.py`
- **教训**：当前发言播放和对局日志归档不能互相阻塞；公开视角的脱敏也要保留足够的非敏感语义，否则 UI 无法表达“哪个职业阶段完成”。

### 问题 B12：真人模式确认后无限 Starting
- **发生时间 / Session**：2026-05-24
- **现象**：真人模式在确认弹窗点击“Confirm & Start”后一直显示 `Starting...`，页面不跳转；直接请求 `/api/rooms/{id}/start?show_private=true` 超过 60 秒没有响应。
- **根因**：后端真人开局接口存在长时间无响应路径；前端 API 层没有超时边界，导致弹窗一直保持 `isStarting=true`。
- **解决方案**：前端 `gameApi` 所有 REST 请求统一走 `AbortController` 30 秒超时；超时抛出稳定错误码并由大厅按当前语言翻译成“请求超时，请稍后重试。”；弹窗打开时隐藏背景配置卡错误，避免同一错误重复渲染；真人确认进场改为与 AI 模式一致使用 `/prepare` 取得初始快照并跳转 play 页，避免在确认弹窗阶段触发长耗时 `/start`。
- **涉及文件 / 模块**：`frontend/lib/gameApi.ts`、`frontend/app/page.tsx`、`frontend/lib/i18n.ts`、`backend/app.py`、`backend/engine/game.py`。
- **教训**：所有前端到后端的交互边界都必须有超时和可恢复 UI；后端长耗时问题不能让前端进入不可退出的 loading 状态。

### 问题 B13：公开视角泄露主持信息 + 夜间滚动条刺眼
- **发生时间 / Session**：2026-05-24
- **现象**：AI 对局页中间事件流在夜间显示白色滚动条，视觉上很突兀；AI 模式进房后默认切到主持视角，玩家身份和夜间行动直接展示，不符合普通玩家/公开观战的信息边界。
- **根因**：play 页中间事件容器使用默认浏览器滚动条；`useGamePageController` 对 AI 模式强制 `setViewMode(ViewMode.MODERATOR)`；事件时间线没有按 `viewMode` 过滤 `visibility="private"` 的夜间行动。
- **解决方案**：中间事件流保留滚动能力但隐藏 scrollbar；AI 模式不再强制主持视角，默认保留公开视角；`EventTimeline` 接收 `viewMode`，公开视角过滤私密事件，主持视角展示完整角色和夜间行动。
- **涉及文件 / 模块**：`frontend/app/room/[id]/play/page.tsx`、`frontend/hooks/useGamePageController.ts`、`frontend/components/game/EventTimeline.tsx`。
- **教训**：狼人杀 UI 必须区分“玩家/观众可见信息”和“主持/上帝全知信息”；公开视角不能为了调试方便默认暴露身份或夜间动作。

### 问题 B14：首夜无开场缓冲 + 夜晚终局残留黑夜视觉
- **发生时间 / Session**：2026-05-24
- **现象**：进入 play 页后首次有效阶段是夜晚时，页面直接进入“天黑请闭眼”黑夜视觉，缺少主持开场缓冲；如果后端在夜晚阶段直接给出 `winner` 或 `GAME_END`，前端可能继续保持 night overlay / 黑夜主题。
- **根因**：`usePhaseTransition` 的视觉状态只覆盖 day/night，`GAME_END` 分支只取消 timer 并清空公告，没有把 `visualPhaseGroup` 设置为独立结束态；首次 night 只播放夜晚公告，没有 ready/intro 阶段；页面夜幕 overlay 只看 `isVisualNight`，未用 winner/end 兜底。
- **解决方案**：`usePhaseTransition` 扩展 `VisualPhaseGroup = day | night | end` 和 `ready` 公告；首次 night 先显示“身份已分配，对局即将开始”约 1.2s，再播放夜晚公告并切 night；`phase === GAME_END` 或 `winner=true` 时取消全部 timer、强制 `visualPhaseGroup=end`，短暂显示“游戏结束”后淡出；play 页用 winner/end 屏蔽夜幕 overlay；全局 CSS 增加 `[data-phase="end"]` 中性金色结算主题。
- **涉及文件 / 模块**：`frontend/hooks/usePhaseTransition.ts`、`frontend/hooks/useGamePageController.ts`、`frontend/components/game/PhaseAnnouncement.tsx`、`frontend/app/room/[id]/play/page.tsx`、`frontend/app/globals.css`、`frontend/lib/i18n.ts`。
- **教训**：阶段 UI 必须区分业务阶段、视觉阶段和临时主持公告；终局是独立视觉态，不能复用最后一个 day/night 状态。

---

### 问题 B15：直进房间默认启发式 + 进化看板无入口（孤儿路由）
- **发生时间 / Session**：2026-05-25
- **现象**：① 任何绕过 lobby 的客户端（curl、外部脚本、CI、直接 POST `/api/rooms`）创建出来的房都是 heuristic 而非 LLM；② Track B/C 排行榜的 `/evolution` 路由存在但没有任何入口（lobby/play 都没有跳转按钮），新用户无从进入。
- **根因**：① `backend/protocols/schemas.py:14` 的 `RoomCreateRequest.agent_type` 默认值是 `"heuristic"`,而 `frontend/app/page.tsx` 在 lobby 里硬编码传 `AgentType.LLM`,两边默认值不一致 — 只要客户端不显式传 `agent_type`,后端就走启发式。② `frontend/app/evolution/page.tsx` 实现了完整的进化看板 + 「版本排行榜」Panel,但 lobby header 只有语言切换,没有任何 `<Link href="/evolution">`。
- **解决方案**：① 把 `schemas.py:14` 默认值从 `"heuristic"` 改成 `"llm"`,与前端默认对齐;启发式仍保留为 LLMAgent 内部的兜底(3 次重试失败后)。② lobby header 增加「进化看板 / Evolution」按钮链接到 `/evolution`,使用与语言切换相同的圆角边框风格。
- **涉及文件 / 模块**：`backend/protocols/schemas.py`、`frontend/app/page.tsx`。
- **教训**：前后端默认值必须双向对齐 — 一方改默认,另一方要立刻同步,否则"直接调 API 的旁路客户端"会拿到与 UI 完全不同的行为。已实现但没有入口的路由是孤儿路由,等同于不存在,新功能合并时必须同步加导航。

---

### 问题 B16：开局仍走启发式 — Doubao API key 401 + model_pool 含 404 模型
- **发生时间 / Session**：2026-05-25
- **现象**：B15 修了 schemas 默认值之后,实际跑游戏每个玩家还是表现得像启发式（没有真实推理 / persona 一致性塌掉)。
- **根因**:三层叠加（不是一个 bug,是一条静默 fallback 链）:
  1. **DOUBAO_API_KEY 401 Unauthorized**：`.env` 里设的旧 key 已失效,`/api/v3/chat/completions` 直接 401。`backend/llm/__init__.py` 的 `_UnavailableLLMClient` 只在 *没有* key 时返回,*有但无效* 的 key 仍构造 DeepSeekClient → 每次 `chat_sync` raise → `llm_agent.py` 静默 fallback 到 `HeuristicAgent`。用户看到的就是"开局即启发式"。
  2. **新 key 的 base_url 变了**：项目组发的新 key 只在 `/api/coding/v1`(Ark 多模型 relay)上有权限,在 `/api/v3` 上 404。
  3. **DOUBAO_MODEL_POOL 含死模型**：原 pool 里 `kimi-2.6[1m]` 在 relay 上 404 UnsupportedModel(正确名字是 `kimi-k2.6[1m]`),被 pool 抽到的玩家立即 fallback。
- **解决方案**：
  1. `.env`:`DOUBAO_BASE_URL` 改为 `https://ark.cn-beijing.volces.com/api/coding/v1`,key 换成新的课题资源密钥,model pool 修正为 `deepseek-v4-pro[1m],deepseek-v4-flash[1m],kimi-k2.6[1m],glm-5.1[1m]`。
  2. `backend/agents/llm_agent.py` `__init__` 增加 `api_key`/`base_url` 可选参数,透传给 `create_client`,允许 factory 给每个玩家路由到不同的 (key, url, model) 三元组。
  3. `backend/agents/factory.py`:`_resolve_model_pool`(只返回模型名)替换为 `_resolve_pool_specs`,返回 `[{api_key, base_url, model}, ...]` 列表,把 DOUBAO_FALLBACK_*(本课题项目组提供的 Doubao-Seed-2.0-pro EP)作为第 5 个 pool 条目,保证即使主 key 出问题也有一条工作的 LLM 路径。
  4. `tests/test_llm_config.py::test_create_client_defaults_to_doubao`:用 `monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)` 让默认值测试不再被 `.env` 污染。
- **涉及文件 / 模块**:`.env`、`backend/agents/llm_agent.py`、`backend/agents/factory.py`、`tests/test_llm_config.py`。
- **教训**:① "Fallback 设计"是双刃剑 — 设计上"API 失败兜底到启发式"对线上可用性好,但对调试是噩梦,因为用户和开发都看不到"为什么没走 LLM"。后续要么在 `app.py` 启动时做 LLM 健康检查(401 立刻打红色告警条),要么至少在 LLMAgent fallback 时 emit 一个可见的事件让前端能感知。② 配置参数(model pool)必须随 SDK/Relay 升级,旧 model 名字会悄无声息地变成 404。③ `.env` 不要混入会污染测试默认值断言的字段 — 测试应该 monkeypatch `load_env_file` 来隔离。

---

### 问题 B17：Track B 复盘报告生成了但无前端展示 + 没有 MD 下载
- **发生时间 / Session**:2026-05-25
- **现象**:`save_published_review` 把 markdown / html 都存进了 `PublishedReview.markdown` 和 `extra_metadata.html_report`,后端有 `GET /api/games/{id}/reviews/html` 能直接渲染 HTML,但前端**没有任何页面调用它**;同时也没有 `.md` 下载端点。用户对局结束后无处查看复盘。
- **根因**:① 后端只暴露了 HTML / JSON 两个端点,缺 markdown 下载;② 前端没有 `/games/[id]/report` 路由消费这些端点;③ `GameEndPanel` 结束面板的"再玩一次"按钮和"返回大厅"按钮 callback 完全一样(都跳 `/`),浪费了一个出口位。
- **解决方案**:
  1. `backend/db/persist.py`:新增 `get_review_markdown(game_id) -> str | None`,从 PublishedReview 行取出已落库的 markdown。
  2. `backend/app.py`:新增 `GET /api/games/{game_id}/reviews.md?download=true`,默认带 `Content-Disposition: attachment; filename=review-<id>.md` 头;`download=false` 时 inline 返回。
  3. `frontend/app/games/[id]/report/page.tsx`:新页面,HEAD probe 两个端点,主区用 iframe 嵌 `/reviews/html`,右上挂"下载 MD"按钮(只在 markdown 存在时显示),没生成报告时显示空态。
  4. `frontend/components/game/GameEndPanel.tsx` + `frontend/app/room/[id]/play/page.tsx`:`GameEndPanel` 增加 optional `onReport` prop;主按钮"再玩一次"被替换为"查看复盘"(language-aware),play 页面在 `gameState.winner` 时把 `router.push('/games/{id}/report')` 透传进去,gameState 没有 id 时 prop 不传(按钮回落到原"再玩一次"语义)。
- **涉及文件 / 模块**:`backend/db/persist.py`、`backend/app.py`、`frontend/app/games/[id]/report/page.tsx`(新建)、`frontend/components/game/GameEndPanel.tsx`、`frontend/app/room/[id]/play/page.tsx`。
- **教训**:后端已经做完的内容(generate_published_review_document → PublishedReview)如果没有前端 surface,等同于没做。验收 / 评分都应该看"从 lobby 进去 → 打完一局 → 看到报告"这条端到端通路是否走得通,而不是各模块单独测过就算完。

---

### 问题 B18：日常开发统一回切到课题 API,备用资源留作演示
- **发生时间 / Session**:2026-05-25
- **现象**:B16 修完后日常运行靠备用 relay 跑随机模型 pool;用户回头明确"还是将本课题项目组提供的 api 作为主力,后续展示的时候再用我的 doubao api"。多模型变化的实验价值在日常调试场景下不如可控性重要,而备用 relay 上的几个 endpoint(尤其 kimi 系)在调用偶发会卡 reasoning 超时或返回空 content,给 fallback chain 增加非必要的不确定性。
- **根因**:这是**方向调整**而非 bug——B16 的设计假设是"多模型 pool 越大越能体现 persona 差异",但用户的实际需求顺序是"先把稳定可控的课题 API 跑通,后续再叠加多模型变化做展示用"。
- **解决方案**:
  1. `.env`:课题 key/url/model 上调到 DOUBAO_API_KEY / DOUBAO_BASE_URL / DOUBAO_MODEL/ DOUBAO_ENDPOINT 主槽;DOUBAO_MODEL_POOL 收敛到只含 `ep-20260514115354-k4jz4`;备用课题资源挪到 DOUBAO_FALLBACK_* 留作演示时切换的参考记录,顶部注释列出可启用的完整模型清单(`deepseek-v4-pro[1m]` 等)。
  2. `backend/agents/factory.py::_resolve_pool_specs`:去掉之前"自动把 DOUBAO_FALLBACK_* append 到 pool"的逻辑——fallback 真正只作记录,pool 完全由 DOUBAO_MODEL_POOL 决定。想启用 fallback 模型时:把模型名追加到 DOUBAO_MODEL_POOL 并同步切 DOUBAO_API_KEY/BASE_URL。
- **效果**:7/7 玩家全部 routed 到课题 ep-20260514115354-k4jz4;live API ping 返回 "OK";126 tests passed。
- **涉及文件 / 模块**:`.env`、`backend/agents/factory.py`。
- **教训**:**配置项的"自动行为"必须可关**。我之前在 _resolve_pool_specs 里硬塞 fallback 是"防御性设计",但等用户想反过来时——只用 primary、不用 fallback——这个隐式行为反而要先拆。pool 的边界应该完全由 DOUBAO_MODEL_POOL 显式声明,fallback 字段只承担"备用配置记录"语义,不参与运行时决策,除非 LLMAgent 显式实现 retry-with-fallback。

### 问题 B19：首页语言切换被旧 Settings 状态回滚
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：Playwright 点击首页 `EN` 后，页面没有稳定切到英文，smoke 等待英文文案超时；用户看到的效果是语言按钮可点但状态会被旧设置拉回。
- **根因**：首页 `language` 来自全局 AppContext，但 `gameSettings.language` 仍保留旧值；同步 effect 每次发现两者不一致就把全局语言改回 settings 里的语言。
- **解决方案**：URL `?lang=` 初始化时写入 `gameSettings`；语言切换按钮同时更新持久化 settings 和 AppContext，避免两个状态源互相覆盖。
- **涉及文件 / 模块**：`frontend/app/page.tsx`、`tests/ui_smoke.mjs`
- **教训**：同一 UI 状态不能由两个源头各自写入；若必须保留持久化 settings，显式用户操作要同步更新所有状态源。

### 问题 B20：对局页发言归档与公开夜晚脱敏不彻底
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：用户指出首页进入也要有音乐但应是右上角音乐图标；语言切换已经在设置里，外层和游戏页右上角不应重复出现；角色发言应该先在下方大气泡逐段展示，展示完再进入上方游戏日志；`@N号` 蓝色文本与正文不齐平；终局弹窗缺整局对局记录导出；普通观众视角仍能看出夜晚具体角色流程或想法；角色库返回首页时动画加载失败。
- **根因**：`BottomDialogueDock` 只取最新 `CHAT_MESSAGE`，上方 `DayEventBlock` 同时渲染未完成发言并依赖 `ChatBubble` 的副作用完成回调，导致发言可能一次性进入日志；音乐按钮是文字按钮且只挂在游戏页；语言切换入口同时存在于设置、首页和游戏页 Header；`MentionText` 的 inline-flex 头像改变了 baseline；公开快照虽过滤 private events，但 `public_dict()` 仍暴露夜晚子阶段和夜晚 `pending_input` 的 request/prompt/options；角色库用 Next `Link` 返回首页时可能复用客户端状态，GSAP 背景动画没有完整重建。
- **解决方案**：音乐组件改为右上角图标按钮并在首页挂载；移除首页和游戏页 Header 的外层语言切换，只保留设置弹窗；新增 `currentDialogueChat` 队列，底部大气泡完成打字后才标记 `completedIds`，上方日志只归档已完成发言；`ChatBubble` 去掉渲染即完成的副作用；`MentionText` 改为普通 inline 蓝色文本；终局弹窗新增 `exportGameRecord()` JSON 导出；`GameState.public_dict()` 对夜晚子阶段和夜晚 `pending_input` 做公开脱敏，`moderator_dict()` 恢复完整全局视角；角色库返回大厅改为普通 `<a href="/">` 触发完整页面加载。
- **涉及文件 / 模块**：`frontend/app/page.tsx`、`frontend/app/personas/page.tsx`、`frontend/app/room/[id]/play/page.tsx`、`frontend/app/room/[id]/play/_components/AIStatusBar.tsx`、`frontend/components/game/BackgroundMusic.tsx`、`frontend/components/game/BottomDialogueDock.tsx`、`frontend/components/game/ChatBubble.tsx`、`frontend/components/game/GameEndPanel.tsx`、`frontend/components/game/GameHeader.tsx`、`frontend/components/game/MentionText.tsx`、`frontend/components/game/_speech/DayEventBlock.tsx`、`frontend/hooks/useGamePageController.ts`、`frontend/lib/i18n.ts`、`backend/engine/models.py`、`tests/test_engine.py`
- **教训**：当前发言播放和历史日志归档必须是两个状态机；普通观众视角的信息隔离要在后端快照层完成，不能只靠前端隐藏；设置类入口要单一，避免用户看到重复控制。

### 问题 B21：UI smoke 仍点击已移除的顶部语言按钮
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：Playwright 真实浏览器 smoke 在首页步骤报 `locator.click: Timeout 30000ms exceeded`，等待 `getByRole('button', { name: 'EN' })`；页面实际已按用户偏好把语言切换收进“设置”弹窗，顶部不再存在 `EN` 按钮。
- **根因**：前端 UI 信息架构更新后，`tests/ui_smoke.mjs` 仍保留旧导航栏语言按钮路径，测试没有跟随真实用户操作路径更新。
- **解决方案**：把 smoke 改为先点击“设置”，再在设置弹窗中选择 `EN|English` 并保存，随后继续验证英文大厅、AI 对局和真人模式。
- **涉及文件 / 模块**：`tests/ui_smoke.mjs`、`frontend/app/page.tsx`、`frontend/components/SettingsModal.tsx`。
- **教训**：端到端测试要验证真实用户路径；当 UI 控制入口被收敛到设置页时，smoke 不能继续依赖旧的快捷按钮。

### 问题 B22：底部打字机丢失 + 日志分段和公开夜晚泄露
- **发生时间 / Session**：2026-06-07 ｜ Codex goal continuation
- **现象**：用户反馈底部大聊天气泡消失，打字机和分段没有体现在底部发言里；日志中多段发言挤在同一个大块里，而不是每段一个小气泡；普通观众视角仍能看到“某某守护/查验/用药了谁”以及行动理由；白天发言偶发空缺，并出现“好的，我分析清楚了局势 / 让我看看投票信息”这类内部规划句和文本截断。
- **根因**：前端 `completedIds` reveal 队列曾被改成收到 `CHAT_MESSAGE` 后立即完成，导致底部 `BottomDialogueDock` 不再承担打字机播放；多个派生点对 `segment_total > 1` 的处理不一致，部分地方仍把分段当作可合并或可跳过事件；观众视角的准备/开始接口固定请求 `show_private=true`，即使渲染层过滤也已经拿到全量事件；后端夜间守卫/女巫/预言家的具体行动用 public `NIGHT_ACTION` 记录；公开发言输出缺少引擎层兜底清洗，LLM raw/free-text 路径可能把内部计划句写进 `CHAT_MESSAGE`；投票理由 UI 仍有 `slice(0, 60)` 的硬截断。
- **解决方案**：恢复底部 `BottomDialogueDock` 为当前未完成发言段的唯一打字机入口，日志只归档 `completedIds` 中已播完的发言；新增 `isRevealBlockingChat()` 统一控制多段发言 reveal，显式多段逐段阻塞，旧式连续同人同阶段发言才允许合并；日志里每个 `segment_total > 1` 段保留独立小气泡；`prepareRoom/startRoom` 按当前 `viewMode` 传 `show_private`，普通观众从接口层不拿 private 快照；夜间守卫/女巫/预言家的具体行动改为 private 事件，public 只保留“行动完毕”摘要；引擎 `_emit_speech()` 增加公开发言清洗和再切段，过滤常见内部规划句并兜底为“过。”；移除投票理由硬截断，改为完整换行展示。
- **涉及文件 / 模块**：`backend/engine/game.py`、`frontend/lib/gameApi.ts`、`frontend/lib/eventFilter.ts`、`frontend/hooks/useGamePageController.ts`、`frontend/hooks/useGameDerivedState.ts`、`frontend/hooks/useVoteDisplay.ts`、`frontend/app/page.tsx`、`frontend/app/room/[id]/play/page.tsx`、`frontend/components/game/BottomDialogueDock.tsx`、`frontend/components/game/EventItem.tsx`、`frontend/components/game/BadgePanel.tsx`、`frontend/components/game/_speech/DayEventBlock.tsx`、`tests/test_engine.py`
- **教训**：当前发言打字机、历史日志归档、公开信息隔离是三个独立边界，不能只在其中一层“看起来隐藏”；普通观众视角必须从请求源头使用 public snapshot，夜间公开日志只能包含主持人可播报的完成状态。

---

## §C. Agent / LLM 行为

### 问题 C1：LLM 50–65 % fallback 回启发式（关键质量 bug）
- **Session**：c72967e4 / commits `a6bdce4`、`60c40f3`
- **现象**：用户反复抱怨"尽可能不要变成启发式的"；日志里 fallback 率 50–65 %，对局质量崩塌。
- **根因**（两层叠加）：
  1. `backend/agents/llm_agent.py` `talk` 默认 `max_tokens=320`，DeepSeek-v4-flash 内置 reasoning 自己吃掉 178 tokens，剩 142 tokens 给 content → JSON 被截断 → parse 失败 → fallback。实测 `max_tokens=800` 时 reasoning 324 + content 143 全文完整。
  2. `llm_agent.py:42` 硬编码 `self.client.timeout = 12.0`，真实 LLM 调用要 5–8 s，reasoning 模式常 > 10 s → 直接 timeout → fallback。
- **解决方案**：commit `a6bdce4` 把 talk 默认预算抬到 800、timeout 12 → 60 s；后续 `60c40f3` 加三次重试（第三次 2.5× 预算 + 收紧 prompt），timeout 升 120 s，并在 fallback 时打日志。
- **效果**：fallback 50–60 % → **0 %**，每个 LLM 调用 3.6–4.1 s，100 % 可解析 JSON。
- **涉及文件**：`backend/agents/llm_agent.py`。
- **教训**：reasoning 模型必须把**内置思考 token** 算进预算；timeout 不要硬编码、要可配置。

### 问题 C2：LLM 输出「场外知识」（描述其他玩家性格）
- **Session**：a9b3dd5d
- **现象**：LLM 编造"陈小玉话不多但逻辑完整""大壮看起来稳"等并非来自实际事件的描述。
- **根因**：把"自己人设描述"塞在 user prompt 的 `=== 你的人设 ===` 段，LLM 误解成对全场玩家的观察。
- **解决方案**：把角色信息搬到 **system prompt** 并加注 "（仅描述你自己，不是其他玩家）"；追加 5 条硬约束：只能用公开事件、禁止"X 话不多"式描述、第一天没信息可以直说、要像真人、不要用个人信息描述他人。
- **涉及文件**：`backend/agents/llm_agent.py`、`backend/agents/profiles.py`。
- **教训**：**system prompt 与 user prompt 的语义边界要硬**，不要让 LLM 把自身设定外溢成对他人的观察。

### 问题 C3：Agent 像在背台词，开局即互喷
- **Session**：a9b3dd5d
- **现象**：第一天没人发言时 Agent 已经开始指控他人。
- **根因**：旧 Agent 没有"当前可见信息"评估，发言模板化；同时 talk prompt 强制要求"指出至少 1 名嫌疑 + 1 名信任"，逼迫 day-1 首发言者编造。
- **解决方案**：重写 `LLMAgent` 接入信息评估 + 状态追踪 + 上下文推理；引入 8 套 wolfcha 风 Persona（MBTI + 职业 + 说话风格 + PlayerMind 维度：勇气 / 记忆偏好 / 怀疑阈值 / 逻辑深度 / 桌面存在感）；`llm_agent.talk()` 统计当日 phase 内 `CHAT_MESSAGE` 数，**0 时切换到「禁止评价/怀疑/暗示其他玩家」的硬约束 prompt**，加"宁可让位也不要编造"clause。
- **涉及文件**：`backend/agents/llm_agent.py`、`backend/agents/profiles.py`、`backend/agents/playbooks.py`、`backend/agents/heuristic.py`。
- **教训**：LLM agent 的 prompt 必须**按阶段位置动态切换**；不能把"必须指控"写死在通用 prompt 里。

### 问题 C4：遗言模板复用导致「邀请下家发言」
- **Session**：b2618de7
- **现象**：豆包真机验证局中 4 号狼遗言写"接下来有请@1号:白晓晴发言"。
- **根因**：`llm_agent.talk()` 复用了普通发言的 prompt，遗言场景没区分。
- **解决方案**：`talk()` 加 `is_last_words` 分支，遗言 prompt 只允许交代身份/查杀/嘱托，禁止传话筒。
- **教训**：每个 phase 都要有自己的 **prompt slot**，不能"差不多就行"。

### 问题 C5：DeepSeek API 调用偶发超时拖慢整局
- **Session**：a9b3dd5d
- **现象**：单局 30+ 次调用，偶发超时 45 s。
- **解决方案**：缩短超时阈值（12 s）+ 失败回退启发式；同时切换主力到 doubao-seed（兼容 OpenAI 格式，复用 `DeepSeekClient`）。
- **后续**：见问题 C1 —— 12 s timeout 后来成了新 bug 的根因，最终升到 60/120 s。

### 问题 C6：角色模型配置测试受环境变量污染
- **发生时间 / Session**：2026-05-24
- **现象**：新增 `create_client()` 默认豆包测试时，本机 `ANTHROPIC_MODEL` 覆盖了预期默认模型；离线 `_UnavailableLLMClient` 也缺 `base_url`，真实 `DeepSeekClient` 缺 `provider` 元数据，导致测试无法统一断言。
- **根因**：LLM client 既要兼容本地 Claude-style 启动变量，又要在无 API Key 时快速 fallback，但离线/在线 client 的可观测字段不一致；测试没有隔离所有会影响默认模型的环境变量。
- **解决方案**：让在线/离线 client 都暴露 `provider/base_url/model`；测试使用 `monkeypatch.delenv()` 清理 `LLM_PROVIDER`、豆包与 Anthropic 兼容变量后再断言默认值。
- **涉及文件 / 模块**：`backend/llm/__init__.py`、`tests/test_llm_config.py`
- **教训**：配置层测试必须显式隔离环境变量；fallback client 也要和真实 client 暴露同一组审计字段。

### 问题 C7：Track C 只有占位实现 + B 缺机器可读批准门
- **发生时间 / Session**：2026-05-24
- **现象**：用户要求“完整实现 C，在 B 已完整实现的情况下；B 还要完整规格测试”。检查发现 `backend/eval/evolution.py` 只有 placeholder 风格的 `HermesEvolutionHook` / `SimpleEvolutionLoop`，无法真正完成 ApprovedReviewReport → 策略知识 → Patch → Version → A/B → promote/rollback 的闭环；B 虽已有复盘主体，但 `generate_review_report()` 没把 Valid/Approved 状态写成 C 可消费的结构化字段。
- **根因**：B/C 早期先预留接口，未把 Track C 文档里的 23 个执行项落成可运行对象；B 的校验结果停留在优化状态返回值，没有回写进 `ReviewReport.metadata.validation_result`。
- **解决方案**：实现 `StrategyKnowledgeDocExtractor`、`StrategyKnowledgeStore`、`DreamJob`、`StrategyPatchGenerator`、`PatchValidator`、`VersionManager`、`TournamentRunner`、`AcceptancePolicy`、`EvolutionPipeline`；`generate_review_report()` 回写 `validation_result` / `quality_passed`，并新增 B/C 规格测试覆盖证据链、反事实边界、策略建议来源、C 只消费 ApprovedReport、知识脱敏、检索、补丁校验、版本晋升/回滚和 summary 导出。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/eval/review.py`、`backend/eval/__init__.py`、`tests/test_review_metrics.py`、`tests/test_track_c_evolution.py`
- **教训**：Track C 不能直接吃“看起来像报告”的对象，必须吃机器可判定的 ApprovedReviewReport；高级方向的文档计划必须配套规格测试，否则 placeholder 很容易伪装成已实现。

### 问题 C8：B/C 用手造 metrics 过验收
- **发生时间 / Session**：2026-05-25
- **现象**：用户明确指出“不要走 fallback 捷径过验收标准，目前实现还很粗糙”。审计后发现 C 的 A/B 验收测试主要比较手造 `GameMetrics`，跑完整 B/C 测试仅 2.9 秒，无法证明固定 20 seed 对局真的执行。
- **根因**：`TournamentRunner` 只有 `compare_metrics()`，没有把 `run_ab_tournament_20_games()` 落到真实引擎；API 层还调用了不存在的 `run_ab_tournament()`，说明 `/api/evolution/cycle` 未被真实覆盖。
- **解决方案**：新增真实 `TournamentRunner.run_ab_tournament()`：强制 20 个固定 seed，baseline/candidate 各跑 20 局 `WerewolfGame`，再用 Track B `MetricsCalculator` 生成指标；`AcceptancePolicy` 增加 `candidate_fallback_count == 0` 硬门；测试新增 C9b 覆盖真实 20 seed 运行；API cycle 改用真实 tournament 并落库。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/db/persist.py`、`tests/test_c_acceptance_verification.py`
- **教训**：验收测试不能只比较构造数据；凡是文档写“跑固定 seed 20 局”，测试必须证明引擎真的被调用、结果数量真的为 20×2。

### 问题 C9：警长归票按普通发言生成
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：用户指出“警长做总结的时候，提示词貌似有问题”。排查发现警长归票阶段虽然 request 是 `SHERIFF_CLOSING`，但实际仍调用 `agent.talk()`，LLM talk prompt 只把 `DAY_SHERIFF_CLOSING` 当普通白天自由发言处理，缺少“归票总结”的任务约束。
- **根因**：`LLMAgent._build_talk_system_parts()` 与 `_build_phase_hint()` 只特化了警徽竞选、PK 和遗言，没有覆盖 `DAY_SHERIFF_CLOSING`；因此模型容易泛泛总结或继续观察，而不是明确主归票对象和依据。
- **解决方案**：为 `DAY_SHERIFF_CLOSING` 增加专门任务语义：要求警长收束讨论、引用公开事实、明确主归票对象、给出备选焦点或说明不分票理由；不改 Agent 协议和引擎阶段。
- **涉及文件 / 模块**：`backend/agents/llm_agent.py`
- **教训**：每个特殊发言阶段都需要独立 prompt slot；只换 request 名称但复用普通发言提示，LLM 不会自动理解阶段职责。

### 问题 C8b：LLMAgent 检索空知识库
- **发生时间 / Session**：2026-05-25
- **现象**：复查 C 验收第 4/5 条时发现 `LLMAgent.update()` 每步创建新的空 `StrategyKnowledgeStore()`，所以不会读取数据库中由 DreamJob 抽取的策略知识，`retrieved_doc_ids` 只在空路径下被写成空数组。
- **根因**：早期为了避免循环 import，只接了内存 store 占位，没有把运行时 Agent 接到持久化知识库查询入口。
- **解决方案**：`LLMAgent.update()` 改为调用 `backend.db.persist.retrieve_strategy_knowledge()`，按角色、阶段、请求、公开/私有事件摘要、persona scope 检索 top-k；prompt block 和 metadata 改用真实 `RetrievedStrategyLesson` 字段；新增单测验证 doc id 会进入 metadata 和 prompt。
- **涉及文件 / 模块**：`backend/agents/llm_agent.py`、`tests/test_track_c_evolution.py`
- **教训**：C 的“Agent 每步检索 top-k”必须在真实 Agent 生命周期里验证，不能只测一个独立 mixin 或空 store。

### 问题 C9：B ApprovedReport 重建后嵌套对象变 dict
- **发生时间 / Session**：2026-05-25
- **现象**：真实调用 `/api/evolution/dream` 时崩溃：`AttributeError: 'dict' object has no attribute 'player_name'`。
- **根因**：`reconstruct_review_report()` 只恢复外层 `ReviewReport`，但 `player_reviews` / `bad_cases` / `counterfactuals` / `strategy_suggestions` 仍是 dict；C 的 `StrategyKnowledgeExtractor` 读取这些对象属性。
- **解决方案**：Track B 重建函数将嵌套字段恢复为 `PlayerReview`、`BadCaseReport`、`CounterfactualCase`、`StrategySuggestion`、`TurningPoint`、`MVPResult` dataclass。
- **涉及文件 / 模块**：`backend/eval/track_b.py`、`backend/db/persist.py`
- **教训**：B→C 边界不能只保证 JSON 形状，还要保证 C 消费端需要的强类型对象语义。

### 问题 C10：豆包 EP 切换后默认配置仍指旧模型
- **发生时间 / Session**：2026-05-25
- **现象**：用户更新后端豆包 API 后，最小 chat completion 可通，但 `tests/test_llm_config.py` 仍期待旧默认 `doubao-seed-2-0-pro-250528`。
- **根因**：本地 `.env` 已使用 `DOUBAO_ENDPOINT=ep-20260514115354-k4jz4`，但代码默认值、`.env.example`、docker compose 默认仍可能回退到旧模型名。
- **解决方案**：本地 `.env` 只更新 secret，不入库；代码默认模型、`.env.example`、docker compose 默认 endpoint 更新为 `ep-20260514115354-k4jz4`；真机最小 chat completion 和单个 LLMAgent talk 均验证 `source=llm`、`fallback=False`。
- **涉及文件 / 模块**：`backend/llm/__init__.py`、`.env.example`、`docker-compose.yml`、`tests/test_llm_config.py`
- **教训**：模型/EP 切换要同时更新“本地 env + 默认配置 + 测试期望”，但 API Key 只能留在 `.env`，绝不能进入代码或提交。

### 问题 C11：策略库仍是文本重叠 + 验收缺成功率面板
- **发生时间 / Session**：2026-05-25
- **现象**：用户指出“这里是否并未涉及到向量检索？策略库只是简单关键字搜索吗？需要量化每一个步骤的成功率”。复查发现 `StrategyKnowledgeStore.retrieve()` 只按 role/phase 过滤，再用 `_text_overlap()` 做词面重叠；B/C 也只有脚本报告和布尔结论，前端看不到每一步成功率。
- **根因**：C §12 写了 HybridRetriever / GraphRAG-lite，但实现停在轻量关键词检索；B/C 验收数据散落在 `PublishedReview`、`AgentDecision`、`StrategyPatch`、`EvolutionTournament` 等表中，没有统一聚合成可视化契约。
- **解决方案**：新增可插拔 `StrategyEmbeddingProvider` 与本地 deterministic `HashingVectorEmbeddingProvider`，检索改为 `hybrid_vector_v1`（role/phase/persona/quality/recency/usage + vector similarity + lexical score），每条 `RetrievedStrategyLesson` 暴露 `vector_score/lexical_score/retrieval_mode`；`StrategyKnowledgeStore._index()` 补 `applicable_to/mitigates/supports/improves_metric/conflicts_with` 图边；DB 聚合新增 `BCAcceptanceAudit`，按 B1-B11、C1-C10 逐项计算 `numerator/denominator/success_rate/threshold/passed/evidence`；Evolution Dashboard 固定模板展示每一步成功率，空数据一律不算通过。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/db/persist.py`、`backend/agents/llm_agent.py`、`frontend/app/evolution/page.tsx`、`scripts/bc_quantify.py`、`tests/test_track_c_evolution.py`、`skills/50-api-contract.md`
- **教训**：只要文档写“混合检索/GraphRAG/量化验收”，实现就必须暴露可审计的检索分项和成功率分母；没有 denominator 的“通过”就是不可复现的口头结论。

### 问题 C12：启发式 smoke 被误读成 LLM 验收
- **发生时间 / Session**：2026-05-25
- **现象**：用户强调“确保所有实验都是在 llm 下做完的”，同时要求豆包 embedding + 元数据过滤 + BM25/FTS 混合检索 + rerank 可用。复查发现 `scripts/bc_quantify.py` 跑的是 heuristic smoke，`TournamentRunner` 默认 A/B 也会走 heuristic engine，容易把“流程正确”误认为“LLM 质量验收通过”。
- **根因**：验收脚本、A/B runner、dashboard 指标没有显式区分 `runner_mode=llm` 与 `runner_mode=heuristic_engine`；候选策略 patch 之前主要影响 heuristic 的 `strategy_bias` 或 post-hoc 分数扰动，LLM A/B 没有把 patch 文本注入到真实 prompt。
- **解决方案**：`StrategyKnowledgeStore` 升级为 `hybrid_vector_bm25_fts_rerank_v2`，提供 `DoubaoEmbeddingProvider`（显式 `STRATEGY_EMBEDDING_PROVIDER=doubao` 才启用）、metadata filters、BM25、FTS、可选豆包 rerank，并在 `RetrievedStrategyLesson` 暴露 `bm25_score/fts_score/rerank_score/provider`；`LLMAgent` 将候选策略 `strategy_bias` 注入发言和行动 prompt，并把检索分项写入 decision metadata；`scripts/run_full_llm_pipeline.py` 的 A/B 改为真实 `LLMAgent + STRICT_NO_FALLBACK=True` 跑法，结果记录 `runner_mode=llm`、`llm_decision_count/total_decisions/fallback_count`；B/C audit 新增 B11 “Runtime LLM decision source rate” 与 C9 “A/B LLM runner evidence”，heuristic 脚本改名义为 smoke，输出 `mode=heuristic_smoke_not_final_acceptance`。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/db/persist.py`、`backend/agents/llm_agent.py`、`backend/agents/factory.py`、`scripts/run_full_llm_pipeline.py`、`scripts/bc_quantify.py`、`tests/test_track_c_evolution.py`
- **教训**：验收数据必须带“来源证明”。LLM-only 验收不只看 fallback=0，还要看每条 decision 的 `source=llm` / token usage / runner_mode；heuristic 可以保留为快速 smoke，但不能进入最终验收口径。

### 问题 C13：豆包 embedding 404
- **发生时间 / Session**：2026-05-25
- **现象**：开启 `STRATEGY_EMBEDDING_PROVIDER=doubao` 后，最小 embedding 请求返回 404；直接请求 `/api/v3/embeddings` 与 `/api/v3/embeddings/multimodal` 都失败，后者错误码为 `InvalidEndpointOrModel.ModelIDAccessDisabled`，提示当前账号不能直接使用 Model ID，必须使用自定义 Endpoint ID。
- **根因**：`doubao-embedding-vision` 是模型族名称 / Model ID 入口，不等于本账号可调用的部署 endpoint；多模态向量化官方接口也不是 OpenAI 字符串数组，而是 `/embeddings/multimodal` + `input=[{"type":"text","text":"..."}]`。
- **解决方案**：`DoubaoEmbeddingProvider` 改为 vision 模型默认走 `/embeddings/multimodal`，请求体使用多模态文本对象，并支持 `DOUBAO_EMBEDDING_ENDPOINT` / `DOUBAO_RERANK_ENDPOINT` 作为首选配置；遇到 ModelIDAccessDisabled 时抛出明确错误，不静默退回本地 hash。`LLMAgent.update()` 新增 `STRATEGY_RETRIEVAL_STRICT=true` 时直接暴露检索失败，避免正式验收悄悄无 RAG；heuristic smoke 脚本显式固定本地 hash，避免开发 smoke 误打外部 API。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/agents/llm_agent.py`、`scripts/bc_quantify.py`、`.env`（本地非提交）
- **教训**：豆包 chat endpoint 与 embedding endpoint 不能混用；正式 RAG/GraphRAG 验收前必须先拿到 embedding 专用 `ep-...`，否则只能证明 chat LLM 可用，不能证明远程向量检索可用。

### 问题 C14：技能反事实被吞掉
- **发生时间 / Session**：2026-06-02 ｜ Codex
- **现象**：运行 `pytest tests/test_b_full_acceptance.py tests/test_c_acceptance_verification.py -q` 时，`test_b_gate6_counterfactual_three_types_exist` 失败；女巫毒错好人已生成反事实，但测试按通用 `counterfactual_type="skill"` 查找，结果为空。
- **根因**：`backend/eval/review.py` 的 `CounterfactualAnalyzer._skill_cases()` 有两个回归叠加：第一，女巫毒药、女巫解药、猎人开枪生成了 `witch_poison` / `witch_save` / `hunter_shot` 子类型，但验收与旧报告口径仍以 `skill` 聚合；第二，女巫毒药分支使用了不存在的局部变量 `poison_target_id`，触发 `NameError`，又被 `CounterfactualAnalyzer.analyze()` 的 debug-level catch 吞掉，最终报告里没有任何技能反事实。
- **解决方案**：将 `_skill_cases()` 产出的技能反事实 `counterfactual_type` 归一为 `skill`，并把错误变量修为 `witch_poison_target_id`；具体技能语义继续通过 `case_id`、`phase`、`original_decision` 和 `effect_type` 保留。
- **涉及文件 / 模块**：`backend/eval/review.py`、`tests/test_b_full_acceptance.py`
- **教训**：评分/验收的聚合维度要稳定；新增更细子类型时，要么同步所有验收口径，要么在输出层保留向后兼容的通用类型。

### 问题 C15：认知 Agent 缺离线全链路验收
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：项目只有 `scripts/test_cognitive_*.py` 这类依赖真实 LLM API key 的手动脚本；CI / 离线验收无法证明 CognitiveAgent 的 Observe → AgentLoop → Decision 真实跑过，也无法覆盖发言、投票、夜晚行动三类决策。
- **根因**：认知 Agent 集成测试绑定 `llm_provider`，没有 fake Runnable；而引擎默认创建 cognitive agent 又会走真实 provider，导致无 key 环境只能测接口形状，不能测执行链路。
- **解决方案**：新增 `tests/test_cognitive_offline.py`，用 deterministic fake LLM 返回 `DECISION: {...}`，创建 7 个真正的 CognitiveAgent 并跑完整 `WerewolfGame`，断言终局、发言事件、投票事件、夜晚行动、AgentLoop prompt 和 decision_records 都存在。
- **涉及文件 / 模块**：`tests/test_cognitive_offline.py`、`backend/agents/cognitive/agent_loop.py`、`backend/engine/game.py`
- **教训**：LLM Agent 的验收要拆成两层：离线 fake LLM 证明本地链路与协议，真实 LLM 长跑再证明模型质量；不能只靠有 key 的手动脚本。

### 问题 C16：验收仍能开 heuristic 对局
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：用户纠正“确保所有对局都是只有 llm”“不要启发式”；复查发现 API 测试、E2E smoke、`TournamentRunner` 默认元数据和 demo 配置仍可创建或标记 heuristic 对局，容易把流程 smoke 当成 LLM-only 验收。
- **根因**：历史规范把 heuristic 当作低成本 CI 路径；`create_agents()` 对 `agent_type=heuristic` 和 role override 没有限制；无 API key 时 LLM client 会返回 unavailable client，再由上层潜在 fallback/默认动作继续推进。
- **解决方案**：`create_agents()` 只允许 AI 席位使用 `llm/cognitive`（统一落为 `llm`），API/WS 对 `agent_type=heuristic` 返回 400/error；新增 `LLM_PROVIDER=fake` 本地 LLM-compatible client 供测试；pytest、API、E2E、UI smoke、demo 配置全部切到 `agent_type=llm`；Track C 默认 runner 记录 `runner_mode=llm_engine` 并移除 post-hoc 分数扰动。
- **涉及文件 / 模块**：`backend/agents/factory.py`、`backend/llm/__init__.py`、`backend/app.py`、`backend/engine/game.py`、`backend/eval/evolution.py`、`tests/conftest.py`、`tests/test_api.py`、`scripts/e2e_smoke.py`、`configs/demo.yaml`
- **教训**：低成本测试可以 fake LLM，但不能换 agent 类型；“无启发式”必须在创建对局入口强制，而不是只靠验收脚本自觉。

### 问题 C17：LLM-only 切换后旧 heuristic 测试失效
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：完整 `pytest tests -q` 失败 4 项，集中在 `tests/test_humanization.py`：测试从 `WerewolfGame.agents[...]` 取到的已是 `CognitiveAgent`，不再有 `human_profile/suspicion/known_wolf_ids/public_stance` 等 HeuristicAgent 私有字段。
- **根因**：旧测试默认 `WerewolfGame()` 会创建 heuristic agents；LLM-only 后这个默认假设失效，但测试目标其实是 HeuristicAgent 的人性化层单元行为，不应该通过游戏默认 agent 类型间接取得。
- **解决方案**：humanization 测试改为用当前 LLM GameState 生成 `PlayerView`，再直接初始化 `HeuristicAgent` 做类单测；对局默认仍保持 LLM-only。
- **涉及文件 / 模块**：`tests/test_humanization.py`、`backend/engine/game.py`
- **教训**：如果测试目标是某个 legacy 类，应直接实例化该类；不能依赖“游戏默认 agent 类型”这种全局策略。

### 问题 C18：技能反事实 effect_type 错误
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：fake LLM API 对局能完成，但 `/api/games/{id}/reviews` 返回 `needs_revision`；validation issue 指出 skill 反事实必须是 `effect_type=local_recalculation`，实际输出为 `exact_recalculation`。
- **根因**：`CounterfactualAnalyzer._skill_cases()` 的女巫毒、女巫救、猎人枪分支仍沿用投票重算的 `exact_recalculation` 标记；文件顶部和 gate 约定技能类应是局部重算。
- **解决方案**：三类技能反事实统一改为 `effect_type="local_recalculation"`，`recomputed_outcome.method` 同步改为 `local_recalculation`；API review 重新变为 approved。
- **涉及文件 / 模块**：`backend/eval/review.py`、`tests/test_api.py`
- **教训**：Track B gate 的字段语义要和生成器保持一致；新增 fake LLM 对局会暴露过去 heuristic seed 没触发到的评测分支。

### 问题 C19：非策略层混入硬玩法
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：用户要求检查“硬逻辑/硬策略”，并明确角色层只能介绍性格、role 层只能介绍职业目标和能力，只有策略层能教怎么玩。复查发现 CognitiveAgent 的 profile/system prompt、legacy role prompt、人格池、狼队协调模块中混有“必须跳、优先守、带偏、归票、拿狼伪装、固定狼队战术角色”等硬玩法。
- **根因**：历史实现把“让 LLM 玩得更像会玩的人”的提示直接塞进 profile / role / persona / wolf_team 等非策略层，缺少自动化分层测试；`wolf_team.py` 还保留了非 LLM 的战术角色分配和刀人推荐函数。
- **解决方案**：将 profile/system/persona 改为身份、能力、目标、信息边界和表达风格；移除 `_build_role_think_hint()` 的角色固定打法；规则工具只答机制不推荐策略；狼队模块降级为合法可见信息摘要，不再分配固定战术或推荐刀口；新增 `tests/test_prompt_layering.py` 防止硬策略回流。
- **涉及文件 / 模块**：`backend/agents/cognitive/profiles.py`、`backend/agents/cognitive/prompts.py`、`backend/agents/cognitive/agent_loop.py`、`backend/agents/cognitive/tools.py`、`backend/agents/cognitive/wolf_team.py`、`backend/agents/cognitive/agent.py`、`backend/agents/profiles.py`、`backend/agents/prompts.py`、`backend/agents/characters.py`、`backend/agents/llm_agent.py`、`tests/test_prompt_layering.py`
- **教训**：能力说明和玩法指导必须物理分层；只要 profile/system/persona 能直接进入 prompt，就不能写“什么时候该做什么”。

### 问题 C20：规则工具字符级误匹配
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：新增分层测试查询 `check_rules("狼人可以空刀吗")`，结果返回“守卫不能连续两晚守护同一人”，说明规则工具会误答。
- **根因**：`check_rules()` 使用 `any(w in question for w in q[:4])`，实际按单个字符做模糊匹配；问题里有“可”字就可能命中“守卫可以连续守同一个人吗”。
- **解决方案**：改为短语级匹配：完整问题包含、反向包含或 FAQ 前四字短语包含；同时把“空刀通常不推荐”的策略建议改成纯机制回答。
- **涉及文件 / 模块**：`backend/agents/cognitive/tools.py`、`tests/test_prompt_layering.py`
- **教训**：规则工具不能用字符级模糊匹配；规则层只回答机制，不能顺手给策略建议。

---

### 问题 C21：C Track 策略未进入认知 Prompt
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：`run_full_llm_pipeline.py` 的 A/B tournament 能把 candidate patch 标记为 applied，但 baseline/candidate 分数与胜局完全相同，`accepted=False`；说明策略版本没有真实影响 agent 行为。
- **根因**：`CognitiveAgent` 收到了 `strategy_bias`，但主路径 `AgentLoop._build_system_text()` 没有把 `build_strategy_bias_block()` 拼进 prompt；同时 A/B 脚本把 Seer 策略作为全局策略给所有角色，而不是只注入目标角色。
- **解决方案**：在 AgentLoop 的任务后追加策略层强制规则块；A/B 路径改为按 `target_role` 注入 `strategy_bias_by_role/role_models`；fake LLM 在看到策略层规则、预言家私有查验、公开票压时才改变模型输出，engine 不改分、不硬改动作。
- **涉及文件 / 模块**：`backend/agents/cognitive/agent_loop.py`、`backend/eval/evolution.py`、`scripts/run_full_llm_pipeline.py`、`backend/llm/__init__.py`、`tests/test_prompt_layering.py`、`tests/test_llm_config.py`
- **教训**：Track C 的“策略产生了”不等于“策略进入了 agent 输入”；A/B 验收必须证明独立变量在目标角色 prompt 中可见并能影响事件。

### 问题 C22：预言家查验未进认知观察
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：C Track 生成“公开查杀/转化投票压力”类策略后，预言家仍无法稳定执行；复盘里反复出现查到狼却未公开、未投查杀目标的问题。
- **根因**：引擎写入的私有事件 payload 是 `{"kind": "seer_result", "target_name": ..., "is_wolf": ...}`，但 `observe()` 只识别旧字段 `check_result`，导致 cognitive observation 丢掉真实查验结果。
- **解决方案**：`observe()` 兼容 `kind == "seer_result"` 并写入 `obs.private["seer_check"]`；新增单测锁住引擎实际 payload 形状。
- **涉及文件 / 模块**：`backend/agents/cognitive/observe.py`、`tests/test_cognitive_offline.py`、`backend/engine/game.py`
- **教训**：信息隔离正确还不够，私有信息必须被认知层按真实 schema 消费；字段名漂移会让角色能力看起来“不会玩”。

### 问题 C23：反思文档为空且来源 unknown
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：LLM 批量对局后日志出现 `reflection produced no new docs`，PG 中缺少 C Track 角色反思文档；部分旧反思文档 `source_report_ids=["unknown"]`。
- **根因**：fake LLM 先匹配通用“输出 JSON”分支，复盘 prompt 返回了 `{target, reasoning}` 而不是反思 schema；`Reflector` 对空数组静默返回 0 doc；`CognitiveAgent` 初始化未拿到 `game_id`。
- **解决方案**：fake LLM 先识别复盘任务并返回反思 schema；`Reflector` 对空复盘生成低置信 fallback docs；`WerewolfGame.initialize()` 与 `PlayerView` 传递真实 `game_id`。
- **涉及文件 / 模块**：`backend/llm/__init__.py`、`backend/agents/cognitive/reflect.py`、`backend/engine/game.py`、`backend/engine/visibility.py`、`tests/test_cognitive_offline.py`
- **教训**：自进化链路不能把“LLM 返回可解析 JSON”当作“有知识产出”；空复盘必须告警或降级生成可审计低置信文档，且 source id 必须贯通。

### 问题 C24：反例优化把硬玩法塞回非策略层
- **发生时间 / Session**：2026-06-04 ｜ Codex
- **现象**：最新增量补丁在 `build_think_prompt()` 和 `AgentLoop._task_for_action()` 中注入了 `_ROLE_ANTI_PATTERNS`，包含“查到狼人必须”“跟随预言家”“首夜优先守护”“刀人优先级”等硬策略，违反用户反复强调的“只有策略层可以教玩法”。
- **根因**：为了闭合 Track C 反例反馈，直接把 MetricsCalculator 常见失误硬编码进角色思考/任务提示；这绕过了策略知识库，也让 role/persona/task 层重新承担玩法教学。
- **解决方案**：删除 `_ROLE_ANTI_PATTERNS` 与 `get_role_anti_patterns()`，`build_think_prompt()` 只接收外部 `strategy_text/strategy_bias`；`AgentLoop` 新增独立 `【策略层：Track C 复盘知识】` 块，只从已发布策略知识库检索经验后注入；新增分层测试防止硬策略短语回流到非策略层。
- **涉及文件 / 模块**：`backend/agents/cognitive/prompts.py`、`backend/agents/cognitive/agent_loop.py`、`tests/test_prompt_layering.py`
- **教训**：Track C 反馈闭环不能靠代码里写死角色打法；反例、建议、避免项都必须经过策略层和可审计知识库进入 Prompt。
- **修正（2026-06-06）**：用户明确纠正“anti-pattern 还是保留，确保不会犯低级错误”。当前处理改为保留 `get_role_anti_patterns()` 并在 `AgentLoop._task_for_action()` 中作为低级错误护栏注入；检索策略实验单独评估 retrieval 质量，不把 anti-pattern 当作检索命中来源。后续写策略实验报告时要显式区分“anti-pattern guardrail”和“RAG/retrieval strategy”。

### 问题 C25：Prompt 构造期重检索拖慢 LLM-only 对局
- **发生时间 / Session**：2026-06-04 ｜ Codex
- **现象**：尝试在每次 `AgentLoop._build_system_text()` 中走完整 Track C/RAG 检索后，fake LLM 对局也出现长时间 CPU 占用，单局 20-60 秒仍不能稳定完成。
- **根因**：Prompt 构造是高频路径；完整检索链路会触发较重的知识恢复、排序和兼容处理，本应服务于离线评测/检索 API，不适合每个 agent 每个动作同步执行。
- **解决方案**：改为轻量 SQL 读取 `list_strategy_knowledge(role, phase, status="active", limit=3)`，不足时补 role-only active 文档；增加短 TTL 进程缓存 `TRACK_C_AUTO_RETRIEVAL_CACHE_SECONDS`，保持策略层注入可用但不拖垮对局推进。
- **涉及文件 / 模块**：`backend/agents/cognitive/agent_loop.py`、`backend/db/persist.py`、`tests/test_prompt_layering.py`
- **教训**：自进化知识进入在线决策时必须控制延迟边界；在线 Prompt 拼装只读已经沉淀的轻量结果，重排序和候选生成留给 Track C 离线链路。

### 问题 C26：检索策略评估被 fallback 污染
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：评估 `same_role_same_mbti`、`global_only` 等检索策略时，工具层在空结果后可能回退到旧 TF-IDF 检索，导致“严格策略为空”的事实被补齐结果掩盖；主评估脚本的 `--judge llm` 仍是占位，无法证明策略是否被真实 LLM 裁判认可。
- **根因**：`search_strategies()` 把 production retrieval 和 legacy TF-IDF fallback 混在同一条路径；策略过滤后空结果没有作为有效实验信号保留。同时缺少一个可复跑的 LLM judge 脚本来独立评分每个 query 的候选策略文档。
- **解决方案**：非 `global_only` 策略命中为空时直接返回“未找到匹配策略”，不再落到 legacy TF-IDF；新增 `scripts/evaluate_retrieval_policies_llm_judge.py`，按 query 汇总所有 policy 的 top-5 文档、去重后一次性让 LLM 打 0-3 相关性分，并输出 `results.json / results.csv / summary.md / per_query_judgments.jsonl`。
- **涉及文件 / 模块**：`backend/agents/cognitive/tools.py`、`tests/test_retrieval_policy.py`、`scripts/evaluate_retrieval_policies_llm_judge.py`
- **教训**：检索策略实验必须保留“空结果/低覆盖”这个负信号；fallback 是线上可用性手段，不应污染离线策略比较。

### 问题 C27：真实 LLM 工具调用空响应中断实验
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：追加正式 7P multi-tier 实验时，多个 seed 在 `speech` / `vote` 阶段失败，错误集中为 `AgentLoop failed to produce a structured decision ... last_response=''`；失败局在 strict no fallback 模式下被正确计入 error，没有被启发式掩盖。
- **根因**：OpenAI-compatible native function calling 偶发返回空 `content` 且没有 `tool_calls`。`AgentLoop` 在强制 `submit_decision` 时只接受 native tool call，遇到空响应只再请求一次同样的 function call，仍为空就中断；切到纯文本修复时又因 `_supports_bind_tools=True` 跳过了文本 `DECISION` 解析。
- **解决方案**：`AgentLoop` 在强制 `submit_decision` 返回空时，下一轮改为纯文本 `DECISION: {...}` 修复指令，并允许该纯文本响应进入 `_parse_decision()` / `_parse_freeform_decision()`；新增离线单测模拟“native 空响应 → 文本 DECISION 成功”。同时修正 MBTI append summary 与最终报告对累计 JSONL 的统计口径。
- **修正（2026-06-06）**：正式复验时又出现 `submit_decision missing speech/reasoning`，即 native tool call 存在但参数缺必填字段。已把这类 `decision_error` 也纳入同一条纯文本 `DECISION` 修复路径，并允许 native 模式下有文本内容时直接解析文本决策。
- **涉及文件 / 模块**：`backend/agents/cognitive/agent_loop.py`、`tests/test_cognitive_offline.py`、`scripts/mbti_acceptance_batch.py`、`scripts/full_victory_report.py`
- **教训**：strict LLM-only 不等于只接受一种 API 表达形式；只要最终动作仍来自同一个 LLM 响应，就可以从 native tool-call 降级为文本结构化输出，但绝不能改为 heuristic 代决策。

### 问题 C28：anti-pattern 护栏再次混入玩法优先级
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：全量 `python -m pytest tests/ -x -q` 失败于 `tests/test_prompt_layering.py::test_agent_loop_task_layer_has_no_role_hard_strategy`，提示 `AgentLoop` 基础任务层仍包含“刀人优先级：预言家 > 女巫 > 猎人 > 守卫 > 村民”。
- **根因**：C24 后续修正要求保留 anti-pattern 护栏，但当前 `_ROLE_ANTI_PATTERNS` 同时包含两类内容：一类是合法目标、信息边界、不能编造结果等低级错误护栏；另一类是刀口优先级、跟随预言家、狼队统一冲票等玩法策略。后者仍会污染非策略层。
- **解决方案**：保留 `get_role_anti_patterns()`，但把条目收敛为“合法目标 / 信息边界 / 不编造私有结果 / 不选择狼队友 / 不同夜连续守护”等规则与低级错误约束；删除“刀人优先级”“狼队统一冲票”“跟随预言家”“首夜优先守护”等策略性短语。
- **涉及文件 / 模块**：`backend/agents/cognitive/prompts.py`、`tests/test_prompt_layering.py`
- **教训**：anti-pattern 可以保留，但必须只当安全护栏；具体玩法、优先级和战术仍只能从策略层或可审计知识库进入 Prompt。

### 问题 C27：v4flash tool_choice 与 thinking 冲突
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：切到 `deepseek-v4-flash` 加速实验后，LLM judge 可正常输出 JSON，但真实 7 人对局的 native function calling 报 400：`Thinking mode does not support this tool_choice`。
- **根因**：DeepSeek v4 flash 默认启用 thinking mode；当请求带 `tools/tool_choice` 时，省略 `thinking` 会触发默认 thinking，而传布尔 `false` 也会被拒绝。该接口要求对象形态 `{"type":"disabled"}`。
- **解决方案**：在 `DeepSeekClient` 中统一归一化 thinking payload：有工具调用且模型/URL 属于 DeepSeek family 时发送 `thinking={"type":"disabled"}`；无工具调用且需要推理时才发送 `thinking={"type":"enabled"}`。真实 tool call smoke 返回 `tool_calls=1`，7 人完整 LLM 对局复测 131.1 秒结束。
- **涉及文件 / 模块**：`backend/llm/deepseek.py`、`tests/test_llm_config.py`
- **教训**：同是 OpenAI-compatible API，也要处理 provider-specific 扩展字段；function calling 与 thinking/reasoning 不能靠布尔值通吃。

### 问题 C28：WEAPI 完整对局批量 502
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：`weapi:gpt-5.5` 最小健康检查成功，但 7P formal MBTI 批次在完整对局负载下 16/16 失败，错误集中为远端 `HTTP 502`。
- **根因**：短 prompt health check 不能代表长上下文、多轮狼人杀对局和并发子进程负载；WEAPI 在正式实验压力下出现上游网关/模型服务不稳定。
- **解决方案**：保留 WEAPI 失败原始记录，不将失败批次包装成成功；正式实验切换到火山引擎 `dsv4flash:deepseek-v4-flash`，所有报告写明 provider/model/runtime 配置；实验脚本继续默认拒绝 offline fake LLM。
- **涉及文件 / 模块**：`scripts/multi_tier_experiment.py`、`scripts/mbti_acceptance_batch.py`、`data/health/mbti_acceptance_formal_weapi_7p_mbti_16x1.*`
- **教训**：正式验收必须跑完整对局负载；health check 只能证明 key/base/model 可连通，不能证明 provider 能承载实验。

### 问题 C29：v4flash 文本模式空 content
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：关闭 native function calling 后，`dsv4flash` 7P 探针仍偶发 `AgentLoop failed ... action=vote, last_response=''`；开启 native FC 时也出现 `submit_decision` 缺 `speech/reasoning`。
- **根因**：认知 Agent wrapper 只在 tools 存在时传 `thinking=False`，普通文本调用仍可能走 reasoning-only 路径；底层 client 对无工具请求没有把 `thinking=False` 规范化为 deepseek-family 需要的对象形态。
- **解决方案**：`_ToolCallingRunnable.invoke()` 对所有认知 Agent 请求都传 `thinking=False`；`DeepSeekClient._normalize_thinking_payload()` 在 deepseek-family 无工具文本模式下发送 `{"type":"disabled"}` 并移除 `reasoning_effort`；补充 no-tools/tools 两条单测。之后 7P 单局探针 50 次 LLM 决策、fallback=0、invalid=0。
- **涉及文件 / 模块**：`backend/agents/cognitive/factory.py`、`backend/llm/deepseek.py`、`tests/test_llm_config.py`
- **教训**：真实模型的“完整 LLM”验收不仅要发出请求，还要保证最终答案落在可解析字段；reasoning-only 输出在狼人杀决策链路里等价于失败。

### 问题 C30：LLM-only 被本地补决策掩盖
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：用户要求“从头到尾 review agent 架构，确保正常对局，llm only，不要 fallback/长超时/空响应”。审查发现 `CognitiveAgent.talk()` 在 LLM 空发言时会本地补“我暂时没有更多信息”，`shoot/boom/transfer_badge/_night_decision` 会在无效目标时本地选第一个存活玩家；引擎发言阶段只用 `ActionValidator`，空 `speech` 的 `TALK` 仍可被当作合法事件写入；`scripts/llm_game_smoke.py` 还可能选到第 1 夜直接结束的 seed，未覆盖白天发言/投票。
- **根因**：稳定性处理和验收逻辑混在一起：Agent 层把“模型无输出/非法输出”转换成本地默认动作，引擎层没有统一非空发言校验，smoke 只检查有无 LLM talk/vote 事件且固定 seed，不检查 `DecisionAudit` 的 fallback/invalid/empty speech；同时 LLM timeout 可被环境变量放大，违背对局内 12 秒上限。
- **解决方案**：严格模式下空发言、缺 reasoning、无效夜间目标、猎人/白狼王/警徽目标无法解析全部抛错；引擎新增 `_valid_talk_decision()` 并用于警徽发言、自由发言、警长归票、PK、遗言；LLM 席位无效发言/投票/技能动作直接 `RuntimeError`，不再构造 fallback 投票；`DeepSeekClient` read timeout 上限固定 12 秒，Agent 工厂固定 `max_retries=0`；`llm_game_smoke.py` 改为扫描可覆盖白天流程的 seed，并同时检查事件和 `DecisionAudit`：fallback=0、invalid=0、empty speech=0、LLM 决策记录存在。
- **涉及文件 / 模块**：`backend/agents/cognitive/agent.py`、`backend/engine/game.py`、`backend/agents/factory.py`、`backend/agents/cognitive/factory.py`、`backend/llm/deepseek.py`、`scripts/llm_game_smoke.py`、`tests/test_cognitive_offline.py`、`tests/test_engine.py`、`tests/test_llm_config.py`
- **教训**：LLM-only 验收必须“失败显性化”，不能靠本地补一句、补目标或默认投票把模型错误包装成完整对局；完整对局 smoke 必须覆盖白天发言/投票，并从事件与审计记录双层证明无 fallback、无空响应、无非法决策。

### 问题 C31：夜间 skip 语义被误报为 unresolved target
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：全量 `python -m pytest tests/ -q` 仅剩 1 个失败：`test_cognitive_agent_required_night_skip_raises_in_strict_mode` 期望 strict mode 报 `skip keyword`，实际报 `LLM returned unresolved guard target: ''`。
- **根因**：fake LLM 返回 `{"target": "跳过", "reasoning": "skip required target"}` 后，pipeline 解析结果的 `target` 变成空字符串，skip 语义只保留在 reasoning；同时 `_SKIP_NIGHT_KEYWORDS` 漏了英文 `skip`，导致 `_night_decision()` 走 unresolved target 分支。
- **解决方案**：夜间必需目标校验在 `target` 为空时也检查 reasoning 是否包含 skip 关键词，并把 `skip` 加入 `_SKIP_NIGHT_KEYWORDS`；strict mode 仍显性抛错，但错误分类保持为 `skip keyword`。
- **涉及文件 / 模块**：`backend/agents/cognitive/agent.py`、`tests/test_cognitive_offline.py`
- **教训**：LLM 输出的同一语义可能落在 target 或 reasoning 字段；strict-mode 错误分类要保留语义信息，不能把明确“跳过”误归类为普通解析失败。

## §D. 数据库 / 持久化

### 问题 D1：以为在用 PostgreSQL，其实是 SQLite
- **Session**：c72967e4
- **现象**：用户直接问"PostgreSQL 后台用的是这个来做的存储吗？"
- **根因**：`backend/db/database.py` 是双后端 fallback —— `DATABASE_URL` 没设就退回 `sqlite:///data/werewolf.db`；`.env` 不存在 → 一直跑 SQLite（38 MB 文件已经有 3 局对局）。
- **解决方案**：用 Docker 起本地 PG（端口 5433），写 `DATABASE_URL` 到 `.env`，SQLAlchemy 自动切到 PG；commit `52c0074` 调 schema。
- **涉及文件**：`backend/db/database.py`、`docker-compose.yml`、`.env`。
- **教训**：fallback 设计要在**启动日志**里明确打印当前真正用的 backend，否则隐患很大。

### 问题 D2：MVP 没真正使用数据库
- **Session**：b2618de7
- **现象**：用户两次质问"没有使用数据库""没有使用 pgsql 作为存储"。
- **根因**：MVP 早期只落地了内存 EventLog；DB 模块写好但启动时没 `init`，且 SQLite 默认 fallback 让人以为没通路。
- **解决方案**：补 `init_db()` 在 FastAPI startup 执行；`save_game_end()` 批量写 events/decisions/votes/snapshots（delete-then-insert 保证幂等）；`backend/db/database.py` 加 `pool_pre_ping + pool_recycle`；`models.py` 在 Postgres 用 JSONB / SQLite 用 JSON。新增 Track B/C 预留表（`agent_versions / leaderboard_entries / review_reports / evolution_rounds`）。
- **涉及文件**：`backend/db/{database,models,persist}.py`、`docker-compose.yml`（werewolf-pg @ 5433）。
- **教训**：MVP checklist 里"数据库充分使用"≠"DB 代码写了"，要 startup hook + 端到端验证一次。

### 问题 D3：调试时 SQL 列名臆造
- **Session**：b2618de7
- **现象**：日志反复 `column "day" does not exist` / `payload` / `seat` / `d.request` / `g.<col>`。
- **根因**：调试时直接对 PG 写 ad-hoc SQL 但记错了实际列名（`current_day` 写成 `day`、`data` 写成 `payload`、`seat_no` 写成 `seat`）。
- **解决方案**：报错后重读 `models.py` 校正列名；这类错误未污染代码，仅 debug 探查。
- **教训**：debug 前先 `\d table` 看 schema，别凭记忆写 SQL。

### 问题 D4：真实 tournament 结果无法写 JSONB
- **发生时间 / Session**：2026-05-25
- **现象**：真实 `/api/evolution/cycle` 跑完 20 seed 后落库失败：`TypeError: Object of type BadCaseReport is not JSON serializable`。
- **根因**：`GameMetrics.metadata` 中包含 Track B dataclass 对象，`EvolutionTournament.baseline_results/candidate_results` 是 JSONB，不能直接序列化 dataclass。
- **解决方案**：`TournamentRunner._metric_summary()` 增加递归 `json_safe()`，对 dataclass 使用 `asdict()`，并清洗 list/dict 后再返回给持久化层。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/db/persist.py`
- **教训**：评测对象可以是富 dataclass，但跨 DB/API 边界前必须转换为 JSON-safe artifact。

### 问题 D5：旧知识文档 NULL 字段导致聚合接口 500
- **发生时间 / Session**：2026-06-02 ｜ Codex
- **现象**：全量 `pytest tests/ -q` 时，`tests/test_api.py::test_runtime_metrics_and_aggregate_endpoints` 调用 `/api/metrics/aggregate` 返回 500；堆栈落在 `KnowledgeDocValidator.validate()`，`" ".join(...)` 尝试拼接旧数据库行里的 `evidence_summary=None`，触发 `TypeError: sequence item ... expected str instance, NoneType found`。
- **根因**：`StrategyKnowledgeDoc` dataclass 声明为字符串字段，但持久化层会从历史 DB 行恢复出 `NULL`；校验器假设所有字段都是干净字符串，没有在 API 聚合这种“读历史数据”路径上做兼容清洗。
- **解决方案**：在 `KnowledgeDocValidator.validate()` 内部统一把参与文本拼接的值经 `_text()` 归一化，`None` 变为空字符串；同时把 `trigger_conditions` 的 `None` 兼容为 `[]`，保留后续 `missing_*` 校验语义。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/app.py`、`tests/test_api.py`
- **教训**：dataclass 的类型标注不能替代数据库边界清洗；凡是从历史持久化记录恢复的评测对象，都要把 `NULL` 当成正常输入处理。

### 问题 D6：知识扩展字段导致 aggregate 500
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：`/api/metrics/aggregate?limit_games=20` 抛出 `TypeError: __init__() got an unexpected keyword argument 'confidence_tier'`；API 单测 `test_runtime_metrics_and_aggregate_endpoints` 失败。
- **根因**：`backend/db/models.py` 已给 `strategy_knowledge_docs` 增加 L0-L4 置信度、可见性、适用性字段，但 `backend/eval/evolution.py` 的 `StrategyKnowledgeDoc` dataclass 仍是旧结构；持久化层 `_knowledge_row_to_dict()` 把新字段还原后直接 `StrategyKnowledgeDocData(**payload)`，强类型边界炸掉。
- **解决方案**：给 Track C `StrategyKnowledgeDoc` 补齐 `confidence_tier / visibility_scope / applicability_*` 等兼容字段，并同步更新 `StrategyKnowledgeStore.load_from_pg()` 与 `sync_to_pg()`，保证从 DB 恢复和写回都不丢元数据。
- **涉及文件 / 模块**：`backend/eval/evolution.py`、`backend/db/persist.py`、`backend/db/models.py`
- **教训**：DB schema 扩展必须同步 dataclass / API 恢复结构；只改 ORM model 不改评测对象，会在聚合和自进化恢复路径上 500。

### 问题 D7：leaderboard 全量聚合历史复盘
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：`tests/test_api.py::test_leaderboard_api_returns_cross_game_views` 卡住；手动请求确认两个 `/api/games` 1 秒内完成，但 `/api/leaderboard` 60 秒超时。本地库有 7404 局、6298 条 approved review。
- **根因**：`get_leaderboard()` 查询所有 `PublishedReview.publish_allowed=True` 后再做内存聚合，只在返回 entries 时按 `limit` 截断；历史库越大，接口越慢，测试也会被历史数据拖垮。
- **解决方案**：在查询层增加最近复盘采样上限 `review_sample_limit = max(100, min(limit * 5, 1000))`，再做聚合；复测 `/api/leaderboard` 约 3 秒返回。
- **涉及文件 / 模块**：`backend/db/persist.py`、`tests/test_api.py`
- **教训**：聚合接口的 `limit` 必须约束数据库查询，不应只约束返回 JSON；本地验收库会长期增长，不能假设数据量小。

---

### 问题 D8：Track C 报告类型不兼容
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：5 局 B/C 主流程已发布复盘，但 DreamJob 汇总阶段崩溃：`TypeError: 'ReviewReport' object is not iterable`，Track C 无法从 DB 重建的 Track B 报告继续抽取策略卡。
- **根因**：项目里同时存在 `backend.eval.review.ReviewReport` 与 `backend.eval.types.ReviewReport`；`StrategyKnowledgeExtractor.extract()` 只用 `isinstance(reports, review.ReviewReport)` 判断单报告，DB 重建返回的是 `types.ReviewReport`，被误当成 sequence。
- **解决方案**：抽取器入口改为按报告字段形状识别单个 ReviewReport-like 对象；新增 `types.ReviewReport` 单报告输入回归测试。
- **涉及文件 / 模块**：`backend/eval/review.py`、`tests/test_track_c_evolution.py`、`backend/eval/types.py`、`backend/eval/evolution.py`
- **教训**：跨模块 dataclass 去重前，公共 API 不能只靠类身份判断；DB 重建对象尤其要做 shape-compatible 输入测试。

### 问题 D9：全流程脚本生成复盘但未显式落库
- **发生时间 / Session**：2026-06-04 ｜ Codex
- **现象**：`run_full_llm_pipeline.py` 跑 5 局时内存态显示 5/5 `approved` 且 `publish=True`，但随后 Track C 只读取到 4 份 published review，导致 `track_c.games=4`。
- **根因**：脚本只调用 `generate_published_review_document(state)` 取得内存文档，未在该路径显式调用 `save_published_review(state)`；部分 seed 的复盘没有进入持久化表，Track C 从 DB 汇总时样本缺失。
- **解决方案**：在生成复盘文档后立即调用 `save_published_review(state)`，确保 B/C 主流程的复盘报告与后续 Track C DB 输入一致；复跑 5 局后 `track_c.games=5`。
- **涉及文件 / 模块**：`scripts/run_full_llm_pipeline.py`、`backend/db/persist.py`、`backend/eval/review.py`
- **教训**：全链路验收不能只看内存对象通过；只要下一阶段从数据库读，就必须在阶段边界显式落库并校验样本数一致。

### 问题 D10：Prepared game 先写决策后写 games 导致外键失败
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：真实浏览器 smoke 从首页开始 AI 对局后，后端打印 `agent_decisions_game_id_fkey` 外键错误，随后复盘 HTML 一度 404。
- **根因**：`/prepare` 已经 `initialize()` 并产生事件，但没有调用 `save_game_start()`；之后 WebSocket 进入 `game.play()` 时发现已有 events，跳过 `play_until_blocked()` 里的首次 `save_game_start()`，最终 `flush_decisions_to_db()` 在 `games` 父行不存在时先插入 `agent_decisions`。
- **解决方案**：`save_game_start()` 改成幂等 upsert 风格，并在 `/api/rooms/{id}/prepare` 初始化后立即保存 game/player 起始行；重复 prepare/start 不再主键冲突。
- **涉及文件 / 模块**：`backend/app.py`、`backend/db/persist.py`
- **教训**：prepared/running/finished 三段生命周期必须共用同一个持久化起点；任何子表写入前都要保证父 `games` 行已存在。

### 问题 D11：aggregate 扫全量知识库导致超时
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：`tests/test_api.py::test_runtime_metrics_and_aggregate_endpoints` 单独运行 90 秒超时；分段计时显示创建对局约 1.9s、`/runtime_metrics` 约 0.04s，但 `/api/metrics/aggregate?limit_games=20` 卡住。共享 PostgreSQL 中已有约 10k games、249k decisions、107k strategy knowledge docs。
- **根因**：`get_aggregate_metrics()` 虽然对 games 使用 `limit_games`，但 B/C acceptance 审计中 `db.query(StrategyKnowledgeDoc).all()` 会加载全表知识文档，并构建 `StrategyKnowledgeStore` 做检索探针；这让 dashboard 请求承担了离线实验级别的全量索引成本。
- **解决方案**：把聚合审计改为 SQL 计数 + 最多 20 条最新非 deprecated 知识文档样本；C1 用 `source_report_ids` SQL 计数，C2/C3/C4/C5 只对有界样本做 sanitizer / embedding / retrieval / graph edge 探针。复测 `/api/metrics/aggregate?limit_games=20` 约 3.4s 返回，相关 API 测试通过。
- **涉及文件 / 模块**：`backend/db/persist.py`、`tests/test_api.py`
- **教训**：面向前端 dashboard 的聚合接口必须有查询上限；全量向量索引或知识库重建应放在离线脚本里，不能挂在普通 HTTP 请求路径上。

## §E. WebSocket / 实时通信

### 问题 E1：对局中途「大家都不动了」（卡死）
- **Session**：b2618de7
- **现象**：用户"打到后面突然大家都不动了，然后有人就死掉了"。
- **根因**：`stream_game` 用一个 thread 跑 `game.play`，WebSocket 断开后 thread 继续推进 game，但客户端没有重连入口；建新 WS 又会重头开一局新 game，与原 game 状态不同步。
- **解决方案**：`backend/protocols/rooms.py` 加 `snapshot_buffer`；`backend/app.py:336 stream_game` 支持 reuse + 重连补帧（新 WS detect active_game → 先 push 全部历史 snapshot 再接 live）；`play/page.tsx:137` onclose 非正常关闭且 game 未结束时 800 ms 自动 `runGame()` 重连。同时修了 React Strict Mode 下 `autoStartedRef` 在双 mount 失效的 bug（`autoStartedRef.current=true` 移到 setTimeout 内部）。
- **涉及文件**：`backend/protocols/rooms.py`、`backend/app.py`、`frontend/app/room/[id]/play/page.tsx`。
- **教训**：长连接驱动的游戏必须 server-side **解耦生命周期** + 提供 replay buffer，否则任何短暂断网都 = 废局。

### 问题 E2：LLM 模式下 UI 显示「后端连接失败」
- **Session**：b2618de7
- **现象**：用户"llm 显示后端链接失败"。
- **根因**：lobby 的 Confirm 不论模式都 POST `/api/rooms/{id}/start`，而 `/start` 同步调用 `play_until_blocked()`，对 AI-vs-AI LLM 局意味着把整局（约 5 分钟 LLM 调用）塞进单个 HTTP 请求 → Next.js proxy/浏览器早就超时。Heuristic 局 <1 s 所以伪装正常。
- **解决方案**：AI 模式不在 lobby 调 `/start`，直接跳 play 页让 WS 接管。
- **教训**：长任务**绝不能**放在同步 HTTP 里；WebSocket 已就位时不要再前置一次性接口。

---

## §F. DevOps / 构建与启动

### 问题 F1：Background `uvicorn` 反复退出 144 / 137
- **Session**：c72967e4
- **现象**：在 Claude Code 里用 background task 起 uvicorn，反复看到 `Exit code 144 / 137`，以为后端在崩。
- **根因**：144 / 137 ≠ 应用崩溃，是 Claude Code 后台 task 生命周期回收 reloader 的信号（SSH/session 结束就会带走子进程）。
- **解决方案**：改用 `nohup … &` 把进程脱离 Claude Code session，日志写 `/tmp/aiwerewolf-uvicorn.log`，由 reloader PID 管理。
- **教训**：长跑服务不要塞进 Claude Code background task；用 `nohup` / `systemd-run` / `tmux`。

### 问题 F2：本地代理污染浏览器到 localhost 的请求
- **Session**：a9b3dd5d
- **现象**：命令行 `curl localhost:8000` 通，浏览器报 404。
- **根因**：`no_proxy` 只影响 shell，浏览器走系统代理把 `localhost` 也丢给代理服务器。
- **解决方案**：提示用户在系统代理中加 localhost 例外（或浏览器关代理）。
- **教训**：诊断"前端通不了后端"先 check 系统代理设置。

### 问题 F3：uvicorn 不带 `--reload` 导致代码改了没生效
- **Session**：a9b3dd5d
- **现象**："Room not found"、路由对不上等错觉，实际是旧进程还在跑。
- **解决方案**：开发环境一律 `uvicorn ... --reload`。
- **教训**：开发期间宁可重启慢也别让人怀疑代码是否生效。

### 问题 F4：实验脚本硬编码敏感默认值
- **发生时间 / Session**：2026-06-02 ｜ Codex
- **现象**：满分验收安全扫描时发现多个实验脚本内存在硬编码的 LLM API key 默认值；`scripts/finetune_llm_verified.py` 还存在本地数据库连接串默认值。即使只是历史脚本，也违反“不得把 API Key、`.env` 写进代码”的项目红线。
- **根因**：实验脚本为本机快速运行写死了默认配置，没有收敛到环境变量；后续被纳入仓库后没有经过敏感信息扫描。
- **解决方案**：删除硬编码 LLM key 默认值，统一改为读取 `DSV4FLASH_API_KEY`；`scripts/finetune_llm_verified.py` 同时改为读取 `DATABASE_URL`。脚本入口在缺少必要环境变量时显式 `RuntimeError` 退出，不再携带敏感默认值。
- **涉及文件 / 模块**：`scripts/finetune_llm_verified.py`、`scripts/ft_quick.py`、`scripts/eval_hybrid_agentic_rrf.py`、`scripts/finetune_llm_batch.py`、`scripts/eval_agentic_search.py`
- **教训**：实验脚本和生产代码一样必须遵守密钥红线；进入仓库前至少跑一次 `API_KEY` / `sk-` / provider key pattern 扫描。

### 问题 F5：pytest 解释器与依赖安装不一致
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：直接运行 `pytest` 时收集阶段报 `ModuleNotFoundError: No module named 'langchain_core'`；安装依赖后仍失败，但 `python -c "import langchain_core"` 正常。
- **根因**：项目认知 Agent 顶层依赖 `langchain_core`，但 `requirements.txt` 未声明；同时 shell 里的 `pytest` 来自 `~/.local/bin/pytest`，而项目 `python` 是 `/home/fyh0106/miniconda3/bin/python`，两个解释器环境不一致。
- **解决方案**：`requirements.txt` 增加 `langchain-core>=0.2` 并安装到项目解释器；验收命令统一使用 `python -m pytest ...`，避免调用到另一个 Python 环境的 pytest entrypoint。
- **涉及文件 / 模块**：`requirements.txt`、`backend/agents/cognitive/*`、测试执行命令
- **教训**：Python 项目验收优先使用 `python -m pytest`；新增运行时依赖必须进 requirements，否则换环境后会在导入阶段失败。

### 问题 F6：pickle 模型跨 numpy 版本不可加载
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：全量 `python -m pytest tests -q` 唯一失败为 `tests/test_track_b_speech_semantic_scorer.py::test_scorer_model_artifact`，直接 `pickle.load()` 报 `ModuleNotFoundError: No module named 'numpy._core'`。
- **根因**：`models/open_data/speech_act_classifier_v0.pkl` 由另一个 numpy 版本/包路径生成，当前环境是 numpy 1.24.4，pickle 里引用的 `numpy._core` 模块不存在；测试因为 artifact 文件存在，不会 skip。
- **解决方案**：用当前解释器重新运行 `scripts/train_speech_semantic_scorer.py`，从 open speech samples 重训并重导出 `speech_act_classifier_v0.pkl`；单测复跑通过。
- **涉及文件 / 模块**：`models/open_data/speech_act_classifier_v0.pkl`、`scripts/train_speech_semantic_scorer.py`、`tests/test_track_b_speech_semantic_scorer.py`
- **教训**：pickle 模型 artifact 不是跨环境稳定格式；如果要随仓库保存，就要在目标 Python/numpy/sklearn 环境下重导出，或改成显式版本化的可迁移格式。

### 问题 F7：Next dev/build 共用 `.next` 导致缓存损坏
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：一边跑 UI smoke 的 `next dev`，一边跑 `next build`，出现 `Cannot find module './819.js'`、`PageNotFoundError: Cannot find module for page: /evolution` 等随机构建错误。
- **根因**：多个 Next 进程同时读写同一个 `.next` 缓存目录；测试脚本还曾在 Next 进程收尾时删除 dist 目录，造成 webpack cache ENOENT 噪音。
- **解决方案**：`next.config.js` 支持 `NEXT_DIST_DIR`；UI smoke 固定使用 `.next-smoke`，构建验证使用 `.next-build-verify`，`tsconfig.json` 显式 include 这两个类型目录；不在 smoke finally 中删除正在收尾的 Next 缓存。
- **涉及文件 / 模块**：`frontend/next.config.js`、`frontend/tsconfig.json`、`tests/ui_smoke.mjs`
- **教训**：E2E/dev/build 不能共享 Next distDir；清理生成目录要放在进程完全退出且验证结束之后。

---

## §G. Git / 协作流程

### 问题 G1：首次推 GitHub 被拒 + 「no common commits」
- **Session**：a9b3dd5d
- **现象**：`git push` 报 `! [rejected] main -> main (fetch first)`；`git pull` 报 `warning: no common commits` / `Failed to merge`。
- **根因**：远端仓库有初始 commit（README），本地是另一棵历史；同时机器上没装 `gh` CLI。
- **解决方案**：用 SSH（`git@github.com:wxhfy/AIwerewolf.git`），用 `git pull --allow-unrelated-histories` 合并后再 push。
- **教训**：新建 GitHub 仓库时统一选择**空仓库**，避免远端预置 README 导致历史分叉。

### 问题 G2：references/ 要在 GitHub 可见但不应被默认 clone
- **Session**：a9b3dd5d
- **解决方案**：把 references/ 下 10 个仓库改成 git submodule，普通 `git clone` 不带 `--recursive` 不会下载；要用时 `git submodule update --init --recursive`。
- **教训**：大体积只读依赖优先 submodule，不要塞进主历史。

### 问题 G3：Codex 入口是 `AGENTS.md` 而非 `CODEX.md`
- **Session**：a9b3dd5d
- **解决方案**：补一份 `AGENTS.md`（对标 Codex 默认入口），`CLAUDE.md` 给 Claude Code。
- **教训**：不同 Agent 工具自动加载的文件名不同，按工具约定命名。

### 问题 G4：远程 `.gitignore` 错误地 ignore `CLAUDE.md` / `AGENTS.md`
- **Session**：c72967e4
- **现象**：`git pull` 后入口文件被吞，团队规范"消失"。
- **根因**：队友的 merge commit 把 `AGENTS.md` / `CLAUDE.md` 写进了 `.gitignore` 并 `git rm` 删除。
- **解决方案**：保留本地 `.gitignore`，新建 `feat/fyh-tag-system-rebase` 分支救回，commit `ccbccf2 fix(gitignore)` 进 PR。
- **教训**：入口 / 规范文件必须**明确 tracked**；CI 可加 sanity check 防误删。

### 问题 G5：队友 PR 带进 1710+ 垃圾文件
- **Session**：c72967e4
- **现象**：队友 PR 内同时包含有价值的前端重写和 `wolf/` Python venv（1710 文件）、`.trae/` IDE 配置、`frontend/.next/` build cache、`data/werewolf.db`、`prototype/`。
- **解决方案**：拒绝直接 `git merge`，按文件 cherry-pick 10 个前端源文件（+1095 行）合入 `chore/fyh-consolidate-and-drop-vanilla`；commit `d8f37b5` 大扫除删除全部垃圾；远程同时删 5 个失效的 `claude/codex/copilot/*` 分支。
- **教训**：跨人 PR 一定要有 `.gitignore` 校验；不能直接 merge 混合分支。

### 问题 G6：脏 main 灾难恢复
- **Session**：c72967e4
- **现象**：`git pull` 后 origin/main 被合进 `wolf/` venv 那一坨垃圾，本人前面修的 LLM 预算 + timeout 全被回退。
- **解决方案**：在 `feat/fyh-import-partner-human-play-ui` 分支重新打 4 个 commit（`a6bdce4 → 60c40f3`）救回所有修复并再次还原 `CLAUDE.md`/`AGENTS.md`；最终全部推回 main。
- **教训**：**贵的修复 commit 完就 push**，不要积压；pull 前先看 origin diff。

### 问题 G7：`git checkout HEAD --` 丢失未提交改动
- **Session**：c72967e4
- **现象**：中途一次 `git checkout HEAD --` 把本地未提交改动直接丢了，`git fsck` 也找不回 dangling blob。
- **解决方案**：凭记忆重写。
- **教训**：未提交改动前禁止 `git checkout HEAD --` / `git reset --hard`，要先 `git stash` 或起新分支。

### 问题 G8：worktree 与主仓 WIP 不同步
- **Session**：d24b2463
- **现象**：执行 `EnterWorktree` 后发现 worktree 从 HEAD 拉，主仓还有大量 WIP，差着这些改动；Edit 报 `This background session hasn't isolated its changes yet.`
- **根因**：CLAUDE.md 规定动手用 worktree，但项目根目录里堆着前一轮没提交的 WIP，直接拉 worktree 会把这部分丢在主仓侧。
- **解决方案**：先 `ExitWorktree({action:"remove", discard_changes:true})` 退出并清掉临时分支，回主仓把 WIP 一次性提交为基线（commit `7317b98`），再重新 `EnterWorktree` 拉一个干净的 worktree 接续工作。
- **教训**：**进 worktree 前必须先 `git status` 检查并落盘主仓 WIP**，否则 worktree 基线就是错的。

### 问题 G9：worktree 默认从 `origin/main` 拉，本地领先 origin 时会缺 commit
- **发生时间 / Session**：2026-05-23 ｜ 本 session（写 DEVELOPMENT_ISSUES.md 时遇到）
- **现象**：进 worktree 后 `git log --oneline` 显示 HEAD 父提交是 `bf7e07a`，但项目主仓 `main` 已经在 `7317b98`，缺一个最新 commit。
- **根因**：`EnterWorktree` 默认 `worktree.baseRef: fresh`——从 `origin/<default-branch>` 拉而非从本地 `main` 拉。本地 `7317b98` 还没 push 到 origin，所以 worktree 看不到它。
- **解决方案**：三选一
  1. 进 worktree 前先 `git push origin main` 把本地 commit 推上去
  2. 改 setting `worktree.baseRef: head` 从本地 HEAD 拉
  3. 进 worktree 后手动 `git merge main` 把本地领先的 commit 合进来
- **本次影响**：仅文档改动，未触碰 `7317b98` 改过的 backend/frontend 文件，所以无冲突；但 PR 合并时**目标分支应该是 origin/main 而不是本地 main**，且 push 顺序要小心——先把本地 main 推上去，再 push 本 feature 分支，否则 PR 基线对不上。
- **教训**：进 worktree 前确认 **本地 main 已与 origin/main 同步**；未 push 的 commit 进 worktree 后看不到，可能在不知不觉中基于过期基线。

---

## §H. 工具调用与流程踩坑（小但常踩）

### 问题 H1：`rtk find` 不支持复合谓词
- **Session**：d24b2463
- **现象**：用 `-not -path` 之类复合表达式被拒（"does not support compound predicates"）。
- **解决方案**：复杂查询走原生 `find` / `grep`。

### 问题 H2：`AskUserQuestion` 把 `questions` 传成字符串
- **Session**：d24b2463
- **解决方案**：传数组对象，按 schema 校验。

### 问题 H3：`Edit` 前没 `Read`
- **Session**：c72967e4 / d24b2463
- **现象**：`<tool_use_error>File has not been read yet`。
- **教训**：写文件前**必须**先 `Read`，硬规则不要忘。

### 问题 H4：`Edit` 旧字符串不匹配 / Unicode 转义
- **Session**：a9b3dd5d / d24b2463
- **解决方案**：定位前先 `grep` 实际内容；或 `Read` 复制原文再 Edit。

### 问题 H5：worktree 切目录后 cwd 失效
- **Session**：d24b2463
- **现象**：`ls`/`grep`/`find` 反复报 `No such file or directory`。
- **根因**：Bash 调用之间 cwd 不持久（每次都 reset），worktree 下做相对路径会错。
- **教训**：worktree 下务必用**绝对路径**或单条命令内 `cd && ...`。

### 问题 H6：rtk wrapper 把 `ls` 等命令的 stdout 吃掉
- **Session**：本 session（2026-05-23）
- **现象**：`ls` / `pwd` / `find` 直接调用经常返回空字符串，但代码本身正确。
- **解决方案**：改用 `/bin/ls`、`/bin/pwd` 绕开 rtk wrapper；或 `rtk proxy <cmd>` 调试。
- **教训**：rtk wrapper 在某些命令组合下会过滤输出，遇到诡异空 stdout 优先怀疑 rtk。

### 问题 H7：32 MB context 爆炸
- **Session**：a9b3dd5d 末尾
- **现象**：`Request too large (max 32MB)`。
- **解决方案**：`/compact` 或 `/clear`，详见 `~/.claude/CLAUDE.md` "Claude Code 32MB 错误预防"段。

### 问题 H8：pytest no tests collected
- **Session**：a9b3dd5d
- **解决方案**：测试目录命名 + `conftest.py` 补齐。

### 问题 H9：标准规则配置与代码板子不一致
- **发生时间 / Session**：2026-06-02 ｜ Codex
- **现象**：满分导向验收审查时发现 `configs/rule_variant_standard.yaml` 的 `role_distribution` 与 `backend/engine/rules.py` 中 `WOLFCHA_ROLE_CONFIGS` 不一致：7P 配置缺少 Guard、12P 配置缺少 Idiot，且缺少 8P/10P/11P 配置。
- **根因**：规则配置文件是后补的验收证据文档，没有从代码中的唯一运行时板子表同步生成；文档标题写“所有规则边界测试必须绑定此配置”，但内容未覆盖当前真实 7-12P 代码路径。
- **解决方案**：将 `configs/rule_variant_standard.yaml` 的 7-12P `role_distribution` 同步到 `WOLFCHA_ROLE_CONFIGS` 当前实现，不改引擎逻辑。
- **涉及文件 / 模块**：`configs/rule_variant_standard.yaml`、`backend/engine/rules.py`
- **教训**：验收配置必须对齐运行时代码入口；否则后续测试即使“绑定标准配置”，也可能验证的是不存在的规则变体。

### 问题 H10：E2E smoke 仍按 7 人默认断言
- **发生时间 / Session**：2026-06-03 ｜ Codex
- **现象**：`python scripts/e2e_smoke.py` 失败在 `assert len(data["players"]) == 7`；房间路径通过，裸 `/api/games?seed=...&agent_type=heuristic` 路径失败。
- **根因**：API `/api/games` 默认 `player_count=10`，`tests/test_api.py` 也已按 10 人默认断言；但 `scripts/e2e_smoke.py` 的裸游戏请求没有显式传 `player_count=7`，仍沿用旧默认预期。
- **解决方案**：smoke 脚本在裸 `/api/games` 请求中显式追加 `player_count=7`，使请求参数和断言一致；复测 E2E smoke 通过。
- **涉及文件 / 模块**：`scripts/e2e_smoke.py`、`backend/app.py`、`tests/test_api.py`
- **教训**：验收脚本不要隐式依赖 API 默认值；如果断言 7 人局，请求里必须显式写 `player_count=7`。

### 问题 H11：UI smoke 断言长期落后当前文案和入口
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：真实 UI 已改为 `Start AI Match` / `Start Human Match`、复盘页独立为 `/games/{id}/report`，但 smoke 仍等待旧 `Start Game`、旧内嵌 Track B 文案，导致验证失败不能反映真实产品状态。
- **根因**：UI 文案和路由迭代后，smoke 没有同步升级为“操作当前真实控件 + 检查关键页面能力”的模式。
- **解决方案**：smoke 改为：进化看板检查首屏面板；已结束房间检查 `Game Over/View Review`；复盘页检查 iframe 和后端 HTML/SVG；首页按当前 `Start AI Match` / 真人模式按钮走真实操作流。
- **涉及文件 / 模块**：`tests/ui_smoke.mjs`
- **教训**：E2E smoke 应断言用户关键能力，不要绑定过时营销文案；按钮名可变时优先围绕当前可见角色/流程验证。

### 问题 H12：E2E smoke 继承外部真实模型池
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：`python scripts/e2e_smoke.py` 偶发 500 或 30 秒超时；同一路径手工加 `MODEL_POOL=fake:fake-llm` 后可稳定完成。`node tests/ui_smoke.mjs` 启动的后端也需要固定 fake LLM-compatible 配置。
- **根因**：脚本只设置了 `LLM_PROVIDER=fake`，但本机环境存在 `MODEL_POOL=deepseek:deepseek-v4-flash`。`create_agents()` 优先使用模型池，导致本地 smoke 继承真实模型池；同步 POST 超时也仍按旧 30 秒，对当前 LLM-compatible fake 完整对局偏低。
- **解决方案**：`scripts/e2e_smoke.py` 与 `tests/ui_smoke.mjs` 显式设置 `MODEL_POOL=fake:fake-llm` / `DOUBAO_MODEL_POOL=fake:fake-llm`；e2e POST 超时提高到 90 秒；UI smoke 支持 `PYTHON` / `NEXT_DIST_DIR` 覆盖，避免环境和构建目录漂移。
- **涉及文件 / 模块**：`scripts/e2e_smoke.py`、`tests/ui_smoke.mjs`
- **教训**：本地 smoke 可以用 fake LLM，但必须完整钉住 provider 和 model pool；只设置 provider 不足以隔离外部 `.env` / shell 配置。

### 问题 H13：UI smoke 等待旧事件标题
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：Playwright 已经进入实时 AI 房间，页面实际显示 `Game started`、阶段流、发言、`Exile Vote` 和底部 `Dialogue`，但 smoke 仍在等待旧标题 `Events`，最终 `page.waitForFunction` 超时。
- **根因**：对局页 UI 已改成沉浸式时间线和底部发言栏，不再保证存在显式 `Events` 标题；smoke 断言仍绑定旧 UI 文案。
- **解决方案**：实时房间断言改为检查当前真实可见的时间线/对话能力：`Game started` / `对局开始`、`Exile Vote` / `放逐投票`、`Dialogue` / `当前发言`、终局复盘入口等。
- **涉及文件 / 模块**：`tests/ui_smoke.mjs`、`frontend/app/room/[id]/play/page.tsx`
- **教训**：UI smoke 应验证用户能看到对局推进和关键操作结果，而不是固定等待一个可被设计迭代删除的栏目标题。

### 问题 H14：API 契约文档落后当前 FastAPI 路由
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：审查 `backend/app.py` 路由清单时发现 `skills/50-api-contract.md` 仍停留在 2026-05-22 版本，缺少 reviews、runtime metrics、leaderboard role matrix、strategy attribution、agents、personas、rooms prepare 等当前已上线端点；静态资源说明也仍写老的 `frontend/index.html`。
- **根因**：前后端和 Track B/C 端点迭代时没有同步维护契约文档，导致规范的“单一事实来源”失效。
- **解决方案**：将 `skills/50-api-contract.md` 的 REST 清单、根路径说明和 WebSocket 重连行为同步到当前 `backend/app.py` 实现。
- **涉及文件 / 模块**：`backend/app.py`、`skills/50-api-contract.md`
- **教训**：每次新增/调整对外路由都必须同 PR 更新契约；否则后续审查会以过期规范为依据，跨端联调风险上升。

### 问题 H13：实验报告误读旧内容
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：重建 `docs/experiments/full_victory_report.md` 后，紧接着并行读取报告时看到了旧的生成时间和旧完成局数；同时直接跑 `pytest` 命令曾走到缺 `langchain_core` 的环境，而 `python -m pytest` 使用的 conda Python 依赖齐全。
- **根因**：报告生成和报告读取被放进并行工具调用，读取命令可能早于写入完成；`pytest` 可执行文件和 `python` 所在环境不一致。
- **解决方案**：报告重建、读取、校验改为顺序执行；验证命令统一使用 `python -m pytest`。同时在 `scripts/full_victory_report.py` 中从原始 JSONL 完成局统计 provider/model 分布，避免 append 补跑后只展示最后一次 `summary.json` 的 provider。
- **涉及文件 / 模块**：`scripts/full_victory_report.py`、`tests/test_full_victory_report.py`、`docs/experiments/full_victory_report.md`
- **教训**：生成物写入和读取不能并行；实验报告要以原始 JSONL 行为权威来源，环境验证命令要绑定同一个 Python 解释器。

### 问题 H15：删 DS key 后实验续跑仍指向 DeepSeek
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：用户要求删除 `.env` 里的 DeepSeek 官方 API key 后，`.env` 仍保留 `LLM_PROVIDER=deepseek` / `MODEL_POOL=deepseek:deepseek-v4-flash`，直接运行正式实验会立刻失败于 `LLM provider deepseek is unavailable`。后续 provider 探测发现 `weapi:gpt-5.5` 返回 401、`ark:deepseek-v4-pro[1m]` 返回 InvalidSubscription；改用 `doubao` provider 绑定 Ark coding endpoint 与 `deepseek-v4-flash[1m]` 后，最小 chat 和 7P 完整单局 smoke 均可通过。
- **根因**：密钥删除和 provider/model 指向是两件事；实验脚本会自动读取 `.env`，旧 provider 设置不会因为 key 删除而失效或自动切到可用通道。真实对局的吞吐还取决于多轮 LLM 决策，不等同于单次 chat 可用。
- **解决方案**：没有把失败探测局混入正式胜率分母；使用显式环境变量清空旧 `MODEL_POOL`，将 `DOUBAO_API_KEY/DOUBAO_BASE_URL/DOUBAO_ENDPOINT` 绑定到 Ark coding token/base/model 后追加正式补跑。multi-tier 新增 24 个真实尝试；MBTI 用 `--append --resume` 补到 16 类每类至少 20 个成功 target-player 样本。`scripts/full_victory_report.py` 生成的正式报告加入“复现与续跑审计”，并新增 HTML 展示页。
- **涉及文件 / 模块**：`.env`（本地未跟踪）、`scripts/multi_tier_experiment.py`、`scripts/mbti_acceptance_batch.py`、`scripts/full_victory_report.py`、`docs/experiments/full_victory_report.md`、`docs/experiments/full_victory_report.html`
- **教训**：实验环境要同时审计 key 存在性、provider/model 指向和端到端单局吞吐；只验证单次 chat 成功不足以证明可以启动长批次。

---

## §I. 用户反复强调或纠正的偏好（沉淀）

> 这一节记录"不是 bug，但用户明确说过 / 反复说过"的稳定偏好，**写代码时直接当硬约束用**。

### 关于 Agent / LLM
- **不要变成启发式 fallback** —— LLM 必须真的跑通；可以拉长思考时间，但要减少 SSE 等待感（推中间「思考中」帧）。
- **Agent 必须真推理**，不要固化说话方式、不要无信息开喷、不要"提示词作弊"塞场外知识。
- **测试要在真实 LLM 场景下做**，光跑启发式不算数。
- **B/C 验收禁止“手造 metrics / heuristic fallback”替代真实链路** —— Track C 的 A/B 必须实际跑固定 seed 对局；Track B 发现 fallback 决策不得发布为 ApprovedReviewReport。
- **策略库必须可量化、可审计** —— 检索不能只靠关键词重叠；每一步验收都要有成功率、样本分母、阈值和展示入口，空数据不能当作通过。
- **最终实验必须带 LLM 来源证明** —— heuristic smoke 只验流程；正式结论必须由 `scripts/run_full_llm_pipeline.py` 产生，并包含 `runner_mode=llm`、`llm_decision_count`、`fallback_count=0` 等审计字段。
- **【2026-06-03 纠正】所有对局都必须是 LLM-only，不要启发式** —— 即使是本地 smoke / A-B tournament / human mixed room，AI 席位也必须走 LLM-compatible Agent；离线测试只能用 `LLM_PROVIDER=fake` 这种 LLM 接口 stub，不能用 `HeuristicAgent` 代替。
- **【2026-06-03 纠正】只有策略层可以教玩法** —— persona/角色性格层只描述表达和性格；role/system 层只描述职业目标、能力、规则和信息边界；“什么时候该做什么、优先级、跳身份、刀口、归票”等必须只出现在策略层。
- **【2026-06-03 纠正】MBTI 覆盖必须是 16×20 局** —— “每个 MBTI 跑 20 局”不能用“总共 20 局且角色覆盖”代替；正式验收至少应跑 16 种 MBTI × 20 局 = 320 局，并按 MBTI 输出 game_count / win_rate / fallback / invalid / 入库统计。
- **【2026-06-06 纠正】anti-pattern 要保留** —— anti-pattern 是防低级错误护栏，不应因为检索策略实验而删除；报告里把它和 RAG/retrieval 效果分开说明。
- **【2026-06-06 纠正】实验不计代价但要用最小可行局加速** —— 当前运行时最小支持人数是 7 人（`WOLFCHA_ROLE_CONFIGS` 支持 7-12），检索/LLM smoke 优先用 7P，不能误说 6P。
- **【2026-06-06 纠正】API 可以切换，优先选更快更稳的** —— WEAPI/gpt-5.5 可用但裁判实验出现 502；v4flash 小样本和完整裁判更快更稳时应切到 v4flash，并记录 provider/model。
- **豆包 embedding 必须用 endpoint ID** —— `doubao-embedding-vision` Model ID 在个人 API 下可能 404；正式 RAG 验收必须配置 embedding 专用 `DOUBAO_EMBEDDING_ENDPOINT=ep-...`。

### 关于 UI / UX
- **严格对齐 wolfcha 设计** —— 阶段命名、角色性格、Persona 系统、刷新逻辑都从 `references/wolfcha` 抠出来，不要自创。
- **UI 风格**：背景米奇奶油色（`#fef3e4`，面板 `#fffdf9`）；事件时间线**最新在上**（新事件往上冒）；可滚动看历史。
- **进入游戏即开始** —— 从 lobby 点开始 → play 页自动开局，不要再点一次。
- **发言/投票需要 `@N号:名字` 格式标注 + 显示时间**（人类玩家可读性硬要求）。
- **后端是真权威** —— localStorage / sessionStorage 只能做"秒开缓存"，所有恢复路径以后端 snapshot 为准。

### 前端 Demo 视角和设置边界
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：用户强调当前只是 Demo，但前端不能显得像直播、调试器、后台管理、论文实验混在同一页；Seed 过于高级，应放进设置页；前端需要放 API Key 和调用模型配置；本轮尽量只改前端，不动后端。
- **根因**：大厅曾把复现实验用 Seed 暴露在主创建流程里；普通观众 / 全局视角的命名和内容边界不够明确；模型调用配置缺少统一入口，容易把配置项散到对局页或后端改动里。
- **解决方案**：把默认视角、语言、Seed、Provider、模型名称、Base URL、API Key 收敛到设置弹窗；大厅只保留对局模式、人数、真人座位和开始按钮；普通观众隐藏身份、夜间行动、决策记录和全局 ActionPanel；全局视角才展示隐藏信息和系统决策；新增 `docs/frontend-demo-design.md` 固化页面边界。
- **涉及文件 / 模块**：`frontend/app/page.tsx`、`frontend/components/SettingsModal.tsx`、`frontend/components/game/LobbyConfigCard.tsx`、`frontend/app/room/[id]/play/page.tsx`、`frontend/app/room/[id]/play/_components/AIStatusBar.tsx`、`frontend/components/game/GameHeader.tsx`、`frontend/components/game/_speech/DayEventBlock.tsx`、`docs/frontend-demo-design.md`
- **教训**：Demo 的配置入口也要有信息架构；普通观众只看公开叙事，全局视角才看隐藏身份和决策解释，高级参数不要放在创建主流程里。

### 对局页底部发言与公开视角边界
- **发生时间 / Session**：2026-06-06 ｜ Codex
- **现象**：用户指出前端存在角色对话截断、空白气泡、打字机位置错误；日志不应承载逐字发言，只应展示对局记录。用户同时强调普通观众视角不能看到神职/玩家内心想法，投票系统应固定在明确位置，复盘报告生成时前端要显示生成中，进化页只展示后端已有结果，不应由前端触发 20 seed。
- **根因**：`ChatBubble` 同时承担日志展示与打字机播放，导致日志 reveal 队列和当前发言播放耦合；对局页 `useRoomStream` 默认 `show_private=true`；投票进度原本在中间滚动日志上方，视觉层级不稳定；复盘页只显示 missing，没有持续等待语义；进化页暴露了 `/api/evolution/cycle` 的 20 seed 触发按钮。
- **解决方案**：新增底部 `BottomDialogueDock` 承载当前发言打字机，日志 `ChatBubble` 改为直接展示完整记录并支持 `@N号` mention chip；新增 `MentionText`；投票进度移动到日志与底部大气泡之间的固定行动条；WebSocket `show_private` 跟随全局视角，观众视角默认不请求 private；复盘按钮和复盘页轮询显示“生成中”；进化页取消 20 seed 运行按钮，仅刷新展示后端结果；新增默认开启的 BGM 组件。
- **涉及文件 / 模块**：`frontend/app/room/[id]/play/page.tsx`、`frontend/components/game/BottomDialogueDock.tsx`、`frontend/components/game/MentionText.tsx`、`frontend/components/game/ChatBubble.tsx`、`frontend/components/game/VotePanel.tsx`、`frontend/hooks/useRoomStream.ts`、`frontend/hooks/useGamePageController.ts`、`frontend/app/games/[id]/report/page.tsx`、`frontend/app/evolution/page.tsx`
- **教训**：对局页要区分“公开记录流”和“当前戏剧化发言”；观众视角从请求源头就不能拿 private 数据，不能只靠前端隐藏；运行昂贵实验的按钮不应出现在演示前台。

### 对局页控制入口和发言归档
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：用户再次强调音乐应在进入页面时出现且使用右上角图标；语言切换只应在设置里；角色发言要一段一段先在底部大气泡展示，完成后再进入上方日志；普通观众夜晚不能看到具体角色行动或想法；终局弹窗要能导出整局对局记录。
- **根因**：这是对 Demo 观战台信息架构的稳定偏好，不只是单个样式 bug。重复控制、未归档发言和公开夜晚细节都会让非技术观众误解页面边界。
- **解决方案**：前端只保留设置弹窗语言入口；底部发言负责播放、上方日志负责归档；公开夜晚统一展示“行动完毕/等待天亮”，全局视角才展示完整夜间行动；终局提供 JSON 导出。
- **涉及文件 / 模块**：`frontend/` 对局页与 `backend/engine/models.py`
- **教训**：Demo UI 的信息边界要比调试页面更克制，公开观众只看叙事结果，全局视角才看系统细节。

### 对局页日志、夜晚与控制入口边界
- **发生时间 / Session**：2026-06-07 ｜ Codex
- **现象**：用户继续纠正：夜晚不显示底部当前发言气泡；只有白天有人发言时才出现发言形态；普通观众在夜晚对应职业结束后只看“XX 完成任务”，全局视角才展示思考过程和行动；对局页面右上角不能再有视角切换，只能在外部设置；对局日志里不能有打字机和一大段当前发言；音乐图标更适合右下角。
- **根因**：这是对 Demo 观战页信息架构的进一步收紧：对局页本身应该是消费设置后的观战界面，不再提供调试/切换控制；日志应是已发生记录，不是当前发言播放器；公开夜晚只能呈现主持人可公开播报的完成状态。
- **解决方案**：对局页移除右上角视角切换和底部常驻发言 dock；日志直接完整显示已产生发言，不做打字机；public 夜间动作保留非敏感职业阶段用于“完成任务”提示；音乐按钮放右下角。
- **涉及文件 / 模块**：`frontend/app/room/[id]/play/page.tsx`、`frontend/components/game/GameHeader.tsx`、`frontend/components/game/EventItem.tsx`、`backend/engine/models.py`
- **教训**：对局页不要混入设置页职责；“日志”和“当前发言”是不同层级，公开夜晚必须只给结果级叙事。

### 底部打字机与日志分段边界
- **发生时间 / Session**：2026-06-07 ｜ Codex goal continuation
- **现象**：用户纠正：底部大聊天气泡不能消失，打字机和分段都要体现在底部打字机里；日志里分段应每段一个小气泡，不能全部挤成一块；普通观众视角不能看到守护/查验/用药的具体目标和理由；发言里不能出现“我分析清楚了局势 / 让我看看投票”这类内部规划句，也不能截断。
- **根因**：这是对上一轮“移除底部 dock、日志直接完整显示”的方向纠正，说明当前 Demo 的正确叙事模型应是：当前发言在底部逐段播放，播放完成后才归档到上方日志；日志是历史记录，但历史记录仍要保持分段小气泡。
- **解决方案**：底部 `BottomDialogueDock` 作为当前发言唯一打字机入口；多段发言按 segment 逐段进入底部，完成后进入上方日志；普通观众接口和事件都只拿 public 信息；日志不截断投票理由和发言段。
- **涉及文件 / 模块**：`frontend/components/game/BottomDialogueDock.tsx`、`frontend/components/game/_speech/DayEventBlock.tsx`、`frontend/lib/eventFilter.ts`、`backend/engine/game.py`
- **教训**：用户对底部大气泡的要求是硬偏好，不是可选视觉方案；不要再把“移除底部打字机”当作简化路径。

### 关于规则正确性
- **猎人死亡 → 开枪、遗言环节、信息隔离**一个都不能漏。
- **持久化是 MVP 必选项** —— 历史对局、日志信息都要入库（pgsql 优先，SQLite fallback）。

### 关于流程纪律
- **【2026-05-23 准则更新】单人开发阶段，AI 可在用户授权下直接 `git push` 到 main**，无需 PR / 无需 2 人 approve；护栏见 `CLAUDE.md` 顶部"项目运行模式"段（不得 `--force`、不得跳 hook、改重灾区前先告知）。团队 ≥ 2 人时恢复 PR 流程。
- 旧规则（多人阶段沿用）：**走 feature 分支 + PR**，不直推 main；commit 仍走 Conventional Commits。
- **入口 / 规范文件**（`CLAUDE.md / AGENTS.md / SKILLS.md / skills/*`）必须永远 tracked，重灾区。
- **AI 动手前必须列计划** —— 列读哪些文件 / 改哪些文件 / 影响面，人类点头后才动手。
- **披露**：PR 描述里说明哪些代码 / 哪些段由 AI 生成。
- **中文交流**；进度勤报（长任务每 30 s 一次进度，不能闷头干）。
- **绝不**把 venv / build cache / IDE 配置 / DB 文件 / `.env` 入库。

---

## §J. 历史 Session 索引（追加新条目时填来源）

| Session shortid | 时间范围（本地） | 主要主题 |
|---|---|---|
| `a9b3dd5d` | 2026-05-20 → 05-21 | MVP 搭建、引擎 Bug、Persona、Agent 优化 |
| `c72967e4` | 2026-05-21 → 05-23 | LLM fallback 修复、清理脏 PR、PG 切换 |
| `b2618de7` | 2026-05-21 → 05-23 | PG 落库、警长流程、WS 重连、recover buffer |
| `d24b2463` | 2026-05-23 | 刷新页面恢复 bug、worktree 流程修复 |
| `7b281de5` | 2026-05-22 | 仅恢复占位，无实质活动 |
| `parallel-opt` | 2026-06-01 | Agent 并行化加速：_batch_ask + 夜晚并行 + 投票并行 |

---

*Version 1.2.0 — 2026-06-03 — 新增 LLM-only / C Track / 反思文档 / 报告类型兼容问题闭环。*
