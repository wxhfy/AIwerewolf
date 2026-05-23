---
name: development-issues
description: AI Werewolf 开发过程中真实遇到的问题、根因定位与解决方案；本文件由 AI 与人类持续追加
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-23
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

---

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

---

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

---

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

---

## §I. 用户反复强调或纠正的偏好（沉淀）

> 这一节记录"不是 bug，但用户明确说过 / 反复说过"的稳定偏好，**写代码时直接当硬约束用**。

### 关于 Agent / LLM
- **不要变成启发式 fallback** —— LLM 必须真的跑通；可以拉长思考时间，但要减少 SSE 等待感（推中间「思考中」帧）。
- **Agent 必须真推理**，不要固化说话方式、不要无信息开喷、不要"提示词作弊"塞场外知识。
- **测试要在真实 LLM 场景下做**，光跑启发式不算数。

### 关于 UI / UX
- **严格对齐 wolfcha 设计** —— 阶段命名、角色性格、Persona 系统、刷新逻辑都从 `references/wolfcha` 抠出来，不要自创。
- **UI 风格**：背景米奇奶油色（`#fef3e4`，面板 `#fffdf9`）；事件时间线**最新在上**（新事件往上冒）；可滚动看历史。
- **进入游戏即开始** —— 从 lobby 点开始 → play 页自动开局，不要再点一次。
- **发言/投票需要 `@N号:名字` 格式标注 + 显示时间**（人类玩家可读性硬要求）。
- **后端是真权威** —— localStorage / sessionStorage 只能做"秒开缓存"，所有恢复路径以后端 snapshot 为准。

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

---

*Version 1.0.0 — 2026-05-23 — 初始建立，回溯 4 个核心 session 的 30+ 条问题。后续新增条目按主题节追加。*
