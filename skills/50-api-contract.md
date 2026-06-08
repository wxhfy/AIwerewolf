---
name: api-contract
description: REST / WebSocket / 内部 Schema 契约，以及变更流程
audience: claude, codex, human
version: 2.0.0
updated: 2026-06-08
---

# API / WebSocket / Schema 契约

> 契约是前后端、Agent、复盘分析和 DB 之间的中央协议。改 `backend/app.py`、`backend/engine/models.py`、`backend/agents/base.py`、`backend/protocols/schemas.py` 或 `frontend/types/index.ts` 时，必须同步本文件。

---

## 一、变更流程

任何对以下内容的修改都必须同步文档和测试：

- 对外 REST API
- WebSocket 消息
- `GameState` snapshot schema
- `Decision` / `GameEvent` / `PendingInput`
- `Phase` / `Role` / `Alignment` / `ActionType` / `EventType`
- 内部 Agent Protocol

要求：

1. 先说明影响面；
2. 同一提交内更新本文件和前端 TS 镜像；
3. 增加或修正 API / schema 测试；
4. 不破坏 `show_private=false` 的信息隔离。

---

## 二、当前 REST 路由清单

单一事实来源：`backend/app.py`。以下摘自 2026-06-08 当前实现。

### 健康与根路径

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| GET | `/` | — | 后端状态 JSON；UI 由 Next.js 服务提供（默认 `http://localhost:3001`） |
| GET | `/api/health` | — | DB/LLM provider 基本健康检查 |

### 对局 Game

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| POST | `/api/games` | `seed`, `show_private`, `agent_type`, `human_seat`, `player_count`, `rule_pack_id` | 创建并运行一局无房间对局；human seat 会运行到 pending input |
| GET | `/api/games` | — | 列出内存中的 active/recorded games |
| GET | `/api/games/{game_id}` | `show_private` | 获取内存对局快照 |
| GET | `/api/replay/{game_id}` | `show_private` | 获取 DB 持久化回放 payload |
| GET | `/api/games/{game_id}/metrics` | — | 单局 Track B 多维指标 |
| GET | `/api/games/{game_id}/runtime_metrics` | — | 单局运行时指标（延迟、tokens、有效决策等） |
| GET | `/api/games/{game_id}/reviews` | — | 复盘报告聚合 payload |
| GET | `/api/games/{game_id}/reviews/status` | — | 复盘产物生成状态；总是返回 200，`pending/ready` 用于前端轮询，避免 HTML/MD 资源未生成时产生 404 噪音 |
| GET | `/api/games/{game_id}/reviews/html` | — | 复盘 HTML，`text/html` |
| GET | `/api/games/{game_id}/reviews.md` | `download` | 复盘 Markdown；默认 attachment 下载 |

### 历史 History

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| GET | `/api/history` | `limit` | 列出 DB 中历史对局 |
| GET | `/api/history/{game_id}` | — | 获取历史对局摘要 |

### 房间 Room

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| POST | `/api/rooms` | `name`, `seed`, `player_count`, `agent_type`, `human_seat`, `rule_pack_id` | 创建房间 |
| GET | `/api/rooms` | — | 列出所有内存房间 |
| GET | `/api/rooms/{room_id}` | — | 获取房间元信息 |
| GET | `/api/rooms/{room_id}/games` | — | 该房间历史对局 |
| GET | `/api/rooms/{room_id}/snapshot` | — | 该房间 latest snapshot；当前实现无 `show_private` 参数 |
| POST | `/api/rooms/{room_id}/games` | `show_private` | 在房间内创建并运行新对局 |
| POST | `/api/rooms/{room_id}/prepare` | `show_private` | 创建 SETUP/角色预览快照，不推进完整对局 |
| POST | `/api/rooms/{room_id}/start` | `show_private` | 开始或恢复真人/同步对局，运行到 pending 或终局 |
| POST | `/api/rooms/{room_id}/action` | body `{action,target,speech}`, query `show_private` | 提交人类玩家行动 |

### Track B / Leaderboard / Eval

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| GET | `/api/metrics/aggregate` | `limit_games` | 跨局聚合指标，含 B/C acceptance 摘要 |
| GET | `/api/leaderboard` | `role`, `limit` | 聚合 leaderboard |
| GET | `/api/leaderboard/role_matrix` | `limit_games`, `llm_only`, `since_iso` | 按 agent/role 聚合胜率矩阵 |
| GET | `/api/strategy/attribution` | `limit_games`, `llm_only`, `since_iso`, `top_k` | 策略知识检索使用与归因 |
| GET | `/api/eval/role-scores` | `role` | 读取角色复盘指标区分实验结果 |

### Track C / Strategy

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| GET | `/api/agents` | — | Agent version 列表 |
| POST | `/api/agents` | `{name, agent_type, model_name, prompt_version, config, parent_version_id?, notes?}` | 注册 Agent version |
| GET | `/api/evolution` | `limit` | 进化轮次日志 |
| GET | `/api/evolution/dashboard` | — | Evolution dashboard 聚合视图 |
| POST | `/api/evolution/dream` | `{report_ids?, from_version?}` | 从 ApprovedReviewReport 聚合知识并生成 candidate patch |
| POST | `/api/evolution/cycle` | `{report_ids?, seeds?}` | 运行 DreamJob + patch + A/B + promote/rollback |
| GET | `/api/strategy/knowledge` | `role`, `phase`, `status`, `limit` | 查询策略知识库 |
| POST | `/api/strategy/knowledge/extract/{game_id}` | — | 从单局 review 抽取 StrategyKnowledgeDoc |
| POST | `/api/strategy/knowledge/{doc_id}/deprecate` | `{reason?}` | 降权/废弃策略知识 |
| GET | `/api/strategy/cards` | `role` | 查询 RoleStrategyCard 版本 |
| POST | `/api/strategy/patches/{patch_id}/apply` | — | 将已校验 patch 应用为 candidate strategy card |

### Persona Library

| Method | Path | Query / Body | 说明 |
|---|---|---|---|
| GET | `/api/personas` | — | 查询 persona library |
| POST | `/api/personas` | persona payload | 新增 persona |
| PUT | `/api/personas/{name}` | persona payload | 更新 persona |
| DELETE | `/api/personas/{name}` | — | 软删除 persona |

---

## 三、命名约定

- URL 用 kebab-case 复数名词 + `{id}` 路径参数。
- JSON 字段保持后端输出的 snake_case；前端 TS interface 也使用 snake_case。
- Enum 值按代码：Phase/EventType 为 `UPPER_SNAKE`，Role 为 `PascalCase` 字符串，ActionType 为 lowercase。
- 路由允许资源下的动作子路径（如 `/api/rooms/{room_id}/start`），但不要新增 `/api/games/start` 这类全局动词路由。

---

## 四、WebSocket 协议

### 端点

| Path | 用途 |
|---|---|
| `/ws/games` | 通用无房间对局流 |
| `/ws/rooms/{room_id}` | 房间级对局流；支持 active game 复用和 snapshot buffer 补帧 |

### 客户端 -> 服务端

```json
{
  "action": "start",
  "seed": 7,
  "agent_type": "llm",
  "show_private": false,
  "player_count": 7,
  "delay_ms": 800
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `action` | string | yes | 当前仅 `"start"` |
| `seed` | int | no | 默认 7 或 room.seed |
| `agent_type` | string | no | AI 席位只允许 `"llm"`；legacy `"cognitive"` 会归一化为 `"llm"` |
| `show_private` | bool | no | 是否使用主持视角 |
| `player_count` | int | no | `/ws/games` 默认 7；room ws 使用房间人数 |
| `delay_ms` | number | no | 每阶段展示延迟，默认 800 |

未知 action 返回：

```json
{"type": "error", "message": "Unsupported action"}
```

真人房间不通过 room WebSocket 推进：

```json
{"type": "error", "message": "Human rooms use /api/rooms/{room_id}/start and /action."}
```

### 服务端 -> 客户端

| `type` | 关键字段 | 说明 |
|---|---|---|
| `status` | `status`, `seed?`, `agent_type?` | 对局开始/状态消息 |
| `room` | `room` | room ws 开始时推送房间状态 |
| `snapshot` | `state`, `room_id?` | 每次状态更新 |
| `stream_token` | `player_id`, `player_name`, `delta`, `finish_reason?` | LLM 流式 token，用于前端即时展示 |
| `complete` | `state?`, `room?` | 对局结束 |
| `error` | `message` | 错误 |

`await_human_input` 不是当前 WebSocket 主路径消息；真人输入通过 REST `pending_input` + `/action` 流程处理。

### 重连

- 客户端断线：服务端捕获 `WebSocketDisconnect` 后返回。
- `/ws/rooms/{room_id}` 若已有未结束 active game，会复用同一局。
- 重连客户端会先收到 `snapshot_buffer` 中已有快照，再继续跟 live frames。
- 非 WebSocket 恢复可读取 `GET /api/rooms/{room_id}/snapshot`。

---

## 五、GameState Snapshot Schema

单一事实来源：`backend/engine/models.py` 的 `GameState.public_dict()` / `moderator_dict()` / `snapshot()`，前端镜像：`frontend/types/index.ts`。

### Public snapshot (`show_private=false`)

```json
{
  "id": "<uuid>",
  "phase": "DAY_SPEECH",
  "day": 1,
  "players": [
    {
      "id": "P1-...",
      "seat": 1,
      "name": "Ada",
      "alive": true,
      "is_ai": true,
      "agent_type": "llm",
      "persona": {"style_label": "...", "mbti": "..."}
    }
  ],
  "events": [],
  "votes": {},
  "vote_history": {},
  "day_history": {},
  "badge": {
    "holder_id": null,
    "candidates": [],
    "signup": {},
    "votes": {},
    "history": {},
    "revote_count": 0
  },
  "daily_summaries": {},
  "daily_summary_facts": {},
  "current_speaker_id": null,
  "pk_targets": [],
  "pk_source": null,
  "pending_input": null,
  "winner": null,
  "alive_count": 7,
  "event_count": 0,
  "last_event": null
}
```

Public 视角不包含：

- `players[].role`
- `players[].alignment`
- `night_actions`
- `role_abilities`
- `phase_cursor`
- private events

夜间子阶段 public phase 会折叠为 `NIGHT_START`，夜间行动 event payload 会脱敏为“行动完毕”。

### Moderator snapshot (`show_private=true`)

在 public snapshot 基础上额外包含或替换：

- `players[]` 使用 `private_dict()`，包含 `role`、`alignment`、完整 `persona`
- `events` 包含 public/private 全量事件
- `pending_input` 为真实 pending input
- `night_actions`
- `role_abilities`
- `phase_cursor`
- 真实 `phase`

---

## 六、核心内部 Schema

### Decision（Agent -> 引擎）

```python
@dataclass
class Decision:
    actor_id: str
    action_type: ActionType
    target_id: str | None = None
    speech: str | None = None
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

Decision 是内部协议，不直接对外暴露。人类玩家输入经 `submit_human_action()` 转换为当前 human seat 的 Decision。

### Human action payload

`POST /api/rooms/{room_id}/action`

```json
{
  "action": "vote",
  "target": "<player_id>",
  "speech": "..."
}
```

### GameEvent

```python
@dataclass
class GameEvent:
    id: str
    ts: float
    day: int
    phase: Phase
    type: EventType
    visibility: str
    payload: dict[str, Any]
    visible_to: list[str] = field(default_factory=list)
```

### PendingInput

```python
@dataclass
class PendingInput:
    player_id: str
    player_name: str
    seat: int
    request: str
    phase: str
    action_type: str
    prompt: str
    options: list[dict[str, Any]]
    can_skip: bool
    placeholder: str | None
```

---

## 七、Enum 清单（变更要同步前端）

### Phase

```
SETUP
NIGHT_START
NIGHT_GUARD_ACTION
NIGHT_WOLF_ACTION
NIGHT_WITCH_ACTION
NIGHT_SEER_ACTION
NIGHT_RESOLVE
DAY_START
DAY_BADGE_SIGNUP
DAY_BADGE_SPEECH
DAY_BADGE_ELECTION
DAY_PK_SPEECH
DAY_LAST_WORDS
DAY_SPEECH
DAY_SHERIFF_CLOSING
DAY_VOTE
DAY_RESOLVE
BADGE_TRANSFER
HUNTER_SHOOT
WHITE_WOLF_KING_BOOM
GAME_END
```

### Role

```
Villager
Werewolf
WhiteWolfKing
Seer
Witch
Hunter
Guard
Idiot
Cupid
BigBadWolf
WolfCub
WolfKing
Knight
Elder
```

其中 `Cupid`、`BigBadWolf`、`WolfCub`、`WolfKing`、`Knight`、`Elder` 当前是模板角色，不进入默认 7-12P 自动配置。

### Alignment

```
village
wolf
```

### ActionType

```
talk
vote
attack
divine
guard
witch_save
witch_poison
shoot
boom
skip
```

### EventType

```
GAME_START
PHASE_CHANGED
PRIVATE_INFO
CHAT_MESSAGE
NIGHT_ACTION
VOTE_CAST
PLAYER_DIED
HUNTER_SHOT
WHITE_WOLF_KING_BOOM
SYSTEM_MESSAGE
GAME_END
```

---

## 八、Agent Protocol（内部）

详见 `skills/40-agent-development.md`。当前协议额外包含 `transfer_badge(candidates: list[str]) -> Decision`，新增 Agent 类型不能漏实现。

正式对局 AI 席位只能使用 LLM-compatible agent；`agent_type=heuristic` 应返回 400 / error。

---

## 九、错误响应规范

```json
{"detail": "Game not found"}
```

| HTTP Status | 何时用 |
|---|---|
| 400 | 客户端输入非法，或 agent_type 被拒绝 |
| 401 | 未授权（暂未启用） |
| 403 | 禁止（暂未启用） |
| 404 | 资源不存在 |
| 409 | 状态冲突，如房间没有 active game |
| 422 | FastAPI 自动请求 schema 错误 |
| 500 | 服务端 bug 或 DB 历史读取失败 |

`detail` 用英文短句，前端负责展示和翻译。

---

## 十、AI 改契约的红线

- [ ] 改 schema 同时改本文件和 `frontend/types/index.ts`。
- [ ] 不破坏 `show_private=false` 信息隔离。
- [ ] 不新增未登记 WebSocket `type`。
- [ ] 不混用 `playerId` / `player_id` 字段风格。
- [ ] 不把 private payload 交给 public snapshot 后让前端过滤。
- [ ] 不把 legacy Decision 字段（`player_id/action/target/save`）写回代码。

---

*Version 2.0.0 — 2026-06-08 — 同步当前 `backend/app.py`、`engine/models.py`、`agents/base.py`、`frontend/types/index.ts`。*
