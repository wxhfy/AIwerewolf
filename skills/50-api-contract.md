---
name: api-contract
description: REST / WebSocket / 内部 Schema 契约,以及变更流程
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# API / WebSocket / Schema 契约

> 契约是**前后端 + Agent + 评测**几个模块的"中央协议"。一旦变更没同步,跨模块就崩。
> 本文件是契约的**单一事实来源**(Single Source of Truth):**先改这里,再改代码**。
> 与代码不一致时,人工 review 必须指出,以本文件为准修正。

---

## 一、变更流程(铁律)

任何对**对外 API**、**WebSocket 消息**、**Decision schema**、**GameEvent schema**、**Phase / Role / ActionType Enum** 的修改:

1. 先在群里说一声(影响面)
2. **同一个 PR 内**,先改本文件,再改代码
3. PR 描述里列出"破坏性变更"清单(如有)
4. **2 人 approve 才能 merge**(见 `10-git-workflow.md` 重灾区表)

**禁止**:在本文件没更新的情况下偷偷改 schema。

---

## 二、当前 REST 路由清单

> 摘自 `backend/app.py`(2026-05-22 版本)。改路由就改这张表。

### 健康检查

| Method | Path | Body / Query | Response |
|--------|------|--------------|----------|
| GET | `/api/health` | — | `{"status": "ok"}` |

### 房间(Room)

| Method | Path | Body / Query | 说明 |
|--------|------|--------------|------|
| POST | `/api/rooms` | `name`, `seed`, `player_count`, `agent_type`, `human_seat`, `rule_pack_id` | 创建房间 |
| GET | `/api/rooms` | — | 列出所有房间 |
| GET | `/api/rooms/{room_id}` | — | 获取房间元信息 |
| GET | `/api/rooms/{room_id}/games` | — | 该房间历史对局 |
| GET | `/api/rooms/{room_id}/snapshot` | `?show_private=bool` | 该房间最新快照 |
| POST | `/api/rooms/{room_id}/games` | `seed`, `show_private`, ... | 在房间内创建新对局 |
| POST | `/api/rooms/{room_id}/start` | `seed`, `show_private`, ... | 开始对局(同步阻塞返回最终结果) |
| POST | `/api/rooms/{room_id}/action` | `payload` (Human 决策) | 提交人类玩家行动 |

### 对局(Game)

| Method | Path | Body / Query | 说明 |
|--------|------|--------------|------|
| POST | `/api/games` | `seed`, `show_private`, `agent_type`, `human_seat`, `player_count`, `rule_pack_id` | 直接创建对局(无房间) |
| GET | `/api/games` | — | 列出活跃对局 |
| GET | `/api/games/{game_id}` | `?show_private=bool` | 获取对局快照 |

### 历史(History,DB 持久化)

| Method | Path | Body / Query | 说明 |
|--------|------|--------------|------|
| GET | `/api/history` | `?limit=int` | 列出 DB 中的历史对局 |
| GET | `/api/history/{game_id}` | — | 获取历史对局摘要 |

### Track C 自进化

| Method | Path | Body / Query | 说明 |
|--------|------|--------------|------|
| GET | `/api/evolution` | `?limit=int` | 进化轮次日志 |
| GET | `/api/evolution/dashboard` | — | Evolution Dashboard 聚合视图 |
| POST | `/api/evolution/dream` | `{report_ids?, from_version?}` | 从 ApprovedReviewReport 聚合知识并生成 candidate patch |
| POST | `/api/evolution/cycle` | `{report_ids?, seeds?}` | 运行 DreamJob + patch + 20 seed A/B + promote/rollback |
| GET | `/api/strategy/knowledge` | `role`, `phase`, `status`, `limit` | 查询策略知识库 |
| POST | `/api/strategy/knowledge/extract/{game_id}` | — | 从单局 ApprovedReviewReport 抽取 StrategyKnowledgeDoc |
| POST | `/api/strategy/knowledge/{doc_id}/deprecate` | `{reason?}` | 降权/废弃策略知识 |
| GET | `/api/strategy/cards` | `role?` | 查询 RoleStrategyCard 版本 |
| POST | `/api/strategy/patches/{patch_id}/apply` | — | 将已校验 patch 应用为 candidate strategy card |

### B/C 量化验收字段

`GET /api/evolution/dashboard` 与 `POST /api/evolution/cycle` 额外返回：

```json
{
  "acceptance_audit": {
    "generated_at": "...",
    "overall_success_rate": 0.95,
    "passed": false,
    "metrics": [
      {
        "track": "B",
        "step_id": "B1",
        "name": "Replay persisted with events and snapshots",
        "numerator": 10,
        "denominator": 10,
        "success_rate": 1.0,
        "threshold": 1.0,
        "passed": true,
        "evidence": "finished games with GameEvent + GameSnapshot rows",
        "details": {}
      }
    ]
  },
  "acceptance_metrics": []
}
```

`GET /api/metrics/aggregate` 在顶层返回同结构 `acceptance` 字段。空样本的 `success_rate=0` 且 `passed=false`，不能把“无数据”当作通过。

### 静态资源

| Method | Path | 说明 |
|--------|------|------|
| GET | `/` | 返回 `frontend/index.html` |
| GET | `/static/...` | `frontend/` 目录所有静态文件 |

---

## 三、命名约定

- **URL** 用 **kebab-case 复数名词** + `{id}` 路径参数
- **JSON 字段** 用 **snake_case**(后端 dataclass 与前端解析保持一致)
- **Enum 值** 用 **UPPER_SNAKE**(`Phase.NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION"`)或 **lowercase**(`ActionType.TALK = "talk"`)——按已有约定

### 禁止

- URL 中包含动词:`/api/games/start`(错)→ `POST /api/rooms/{room_id}/start`(对,动词作为 POST 的子路径)
- 复数 / 单数混用:`/api/game`(错)→ `/api/games`(对)
- 字段大小写漂移:有的地方 `playerId`、有的地方 `player_id`(后端统一 snake_case,前端用什么读什么)

---

## 四、WebSocket 协议

### 端点

| Path | 用途 |
|------|------|
| `/ws/games` | 通用对局流(无房间) |
| `/ws/rooms/{room_id}` | 房间级对局流(推荐) |

### 客户端 → 服务端消息

```json
{
  "action": "start",
  "seed": 7,
  "agent_type": "llm",
  "show_private": false,
  "player_count": 7
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | string | yes | 目前仅 `"start"` |
| `seed` | int | no | 默认 7 |
| `agent_type` | string | no | `"llm"` / `"heuristic"`,默认 `"llm"` |
| `show_private` | bool | no | 主持视角,默认 false |
| `player_count` | int | no | 默认 7 |

未知 `action` → 服务端回 `{"type": "error", "message": "Unsupported action"}`。

### 服务端 → 客户端消息

服务端推送的消息**必须**带 `type` 字段:

| `type` | 触发时机 | 关键字段 |
|--------|----------|----------|
| `status` | 对局开始 / 状态变化 | `status`: `"starting"` / `"running"` / ... |
| `snapshot` | 每个 Phase 流转 | `state`: GameState 快照(见下) |
| `complete` | 对局结束 | `state`: 最终快照(含 `winner`) |
| `error` | 出错 | `message`: 错误描述 |
| `await_human_input` | 等待人类输入 | `seat`、`phase`、`options` |

**新增 `type` 必须在本文件登记**,前端才会知道怎么处理。

### 客户端断线 / 重连

- 客户端断线 → 服务端 silent return(`WebSocketDisconnect`)
- 重连后从 `GET /api/rooms/{room_id}/snapshot` 拉最新状态,**不要**重放历史消息
- 重连频率:指数退避 1s → 2s → 4s → ... → 30s(详见 `30-frontend-conventions.md`)

---

## 五、GameState Snapshot Schema

```python
# backend/engine/models.py 中的 GameState.snapshot(show_private)
{
  "id": "<uuid>",
  "seed": 7,
  "day": 2,
  "phase": "DAY_VOTE",
  "winner": null | "village" | "wolf",
  "players": [
    {"id": "...", "seat": 1, "name": "...", "alive": true, "role": "Seer"(*仅 show_private 或自己*)},
    ...
  ],
  "events": [
    {"type": "PHASE_CHANGED", "phase": "...", "payload": {...}, "visibility": "public", "visible_to": [...]},
    ...
  ],
  "badge": {"holder_id": "...", "history": [...]},
  "daily_summaries": {...},
  ...
}
```

**铁律**:`show_private=false` 时,**绝对不能**在 `players[].role`、`events[].payload` 中泄漏非公开身份。
信息隔离在后端 `Visibility` 层完成,前端只是渲染——不要在前端"补"信息。

---

## 六、Decision Schema(Agent → 引擎)

```python
@dataclass
class Decision:
    player_id: str
    action: ActionType
    target: str | None = None
    speech: str | None = None
    reasoning: str = ""
    save: bool | None = None
```

详见 `40-agent-development.md` 第二节。
Decision 是**内部协议**,不直接对外暴露,但人类玩家输入会经前端转换成 Decision 提交。

### 人类玩家 POST `/api/rooms/{room_id}/action` 的 payload

```json
{
  "action": "vote",
  "target": "<player_id>",
  "speech": "..."
}
```

后端转 Decision 时:`player_id` 取自当前 human_seat 的玩家 id。

---

## 七、Enum 清单(变更要 2 人 approve)

### Phase(`engine/models.py`)

```
SETUP, NIGHT_START, NIGHT_GUARD_ACTION, NIGHT_WOLF_ACTION,
NIGHT_WITCH_ACTION, NIGHT_SEER_ACTION, NIGHT_RESOLVE,
DAY_START, DAY_BADGE_SIGNUP, DAY_BADGE_SPEECH, DAY_BADGE_ELECTION,
DAY_PK_SPEECH, DAY_LAST_WORDS, DAY_SPEECH, DAY_VOTE, DAY_RESOLVE,
BADGE_TRANSFER, HUNTER_SHOOT, WHITE_WOLF_KING_BOOM, GAME_END
```

### Role(`engine/models.py`)

```
VILLAGER, WEREWOLF, WHITE_WOLF_KING, SEER, WITCH, HUNTER, GUARD, IDIOT
```

### Alignment

```
VILLAGE = "village", WOLF = "wolf"
```

### ActionType

```
TALK, VOTE, ATTACK, DIVINE, GUARD, WITCH_SAVE, WITCH_POISON, SHOOT, BOOM, SKIP
```

### EventType

```
GAME_START, PHASE_CHANGED, PRIVATE_INFO, CHAT_MESSAGE, NIGHT_ACTION,
VOTE_CAST, PLAYER_DIED, HUNTER_SHOT, WHITE_WOLF_KING_BOOM,
SYSTEM_MESSAGE, GAME_END
```

**新增 Enum 成员**:在本文件登记 → 引擎 / Visibility / 前端渲染都要相应处理。

---

## 八、版本与兼容

### `rule_pack_id`

当前默认 `"wolfcha-default"`,代表角色配比、夜晚顺序的具体规则集。
未来引入新规则集(`"awesome-12p-v1"`)时:

- 新增 rule_pack 不破坏旧的(同时存在)
- 前端 select 给用户选,默认仍是当前
- DB 持久化必须存 `rule_pack_id`,复盘时按这个回放

### 字段添加 / 删除

| 操作 | 影响 |
|------|------|
| 新增字段(可选) | 非破坏性 → 1 人 approve |
| 删除字段 | 破坏性 → 2 人 approve + 前后端同步改 |
| 重命名字段 | 破坏性 → 同上,**禁止**做"兼容期"双字段 |
| 改类型 | 破坏性 → 同上 |

**禁止**保留 "deprecated" 字段 6 个月以上——21 天项目周期不需要这种弹性。

---

## 九、错误响应规范

```json
{
  "detail": "Game not found"
}
```

| HTTP Status | 何时用 |
|-------------|--------|
| 400 | 客户端输入非法(如 vote 一个死人) |
| 401 | 未授权(暂未启用) |
| 403 | 禁止(暂未启用) |
| 404 | 资源不存在 |
| 409 | 状态冲突(如游戏已结束还要 submit action) |
| 422 | FastAPI 自动:请求体 schema 错误 |
| 500 | 服务端 bug,**不要**主动 raise,出现就修 |

`detail` 必须英文短句,前端 i18n 字典负责翻译。

---

## 十、AI 改契约的红线

- [ ] 改 schema 一定在 PR **同时**改本文件
- [ ] 不引入 URL 中的动词
- [ ] 不混用 snake_case / camelCase
- [ ] 不破坏 `show_private=false` 下的信息隔离
- [ ] 不删除 Enum 成员(只能新增)
- [ ] 错误 detail 用英文短句

详见 `70-ai-collaboration.md`。

---

*Version 1.0.0 — 2026-05-22 — 初始建立,基于 backend/app.py 当前实现。*
