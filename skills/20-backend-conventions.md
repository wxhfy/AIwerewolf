---
name: backend-conventions
description: Python / FastAPI / dataclass / Enum / Protocol / DB / LLM 层代码规范
audience: claude, codex, human
version: 1.0.0
updated: 2026-05-22
---

# 后端开发规范

> 适用范围：`backend/` 目录下所有 Python 代码。
> 风格基线：参考已有文件 `backend/engine/models.py`、`backend/agents/base.py`、`backend/app.py`、`backend/protocols/schemas.py`。

---

## 一、文件级约定

每个 `.py` 文件第一行必须是：

```python
from __future__ import annotations
```

这样 type hints 都可以用 `list[int]` / `dict[str, Any]` / `int | None` 风格，不需要 `Optional` / `List`。

**导入顺序**（PEP 8）：

1. 标准库
2. 第三方库（fastapi、pydantic、sqlalchemy 等）
3. 本项目（`from backend.xxx import ...`）

每组之间空一行，组内按字母序。

---

## 二、目录结构与职责（已存在，不要乱改）

```
backend/
├── app.py               # FastAPI 入口，只放路由与极薄装配
├── run_demo.py          # CLI 入口
├── engine/              # 游戏引擎（纯逻辑，不依赖 FastAPI / DB）
│   ├── models.py        # dataclass + Enum 数据模型
│   ├── game.py          # WerewolfGame 主循环
│   ├── phases.py        # 阶段处理器
│   ├── phase_manager.py # 阶段流转
│   ├── actions.py       # 行动注册与校验
│   ├── rules.py         # 角色配置
│   ├── visibility.py    # 信息隔离 PlayerView
│   ├── config.py        # YAML 配置加载
│   └── summary.py       # 每日总结生成
├── agents/              # Agent 实现（见 40-agent-development.md）
├── protocols/           # 对外协议（HTTP / WebSocket）
│   ├── schemas.py       # 请求/响应 dataclass
│   └── rooms.py         # 房间管理
├── db/                  # DB 持久化（sqlalchemy）
├── llm/                 # LLM 客户端封装
└── eval/                # 评测与复盘
```

### 跨层依赖规则

```
app.py
  ↓
protocols  ←  agents
  ↓           ↓
        engine
          ↑
        rules / models
```

- `engine/` **不能** import `protocols/` / `app.py` / `db/` / `llm/`（保持纯逻辑可测）
- `agents/` 可以 import `engine/` 的模型，**不能**反向
- `db/` 是独立层，只被 `app.py` 与 `protocols/` 引用
- 出现新模块（如 `eval/`）时，在本节登记依赖方向

---

## 三、命名

| 对象 | 风格 | 例 |
|------|------|---|
| 模块 / 文件 | `snake_case.py` | `phase_manager.py` |
| 类 | `PascalCase` | `WerewolfGame` / `HeuristicAgent` |
| 函数 / 变量 | `snake_case` | `play_until_blocked` / `human_seat` |
| 常量 | `UPPER_SNAKE` | `MAX_DAYS = 8` |
| Enum 成员 | `UPPER_SNAKE`（值用字符串） | `Phase.NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION"` |
| 私有函数 | 前缀 `_` | `_build_game` |
| 类型别名 | `PascalCase` | `RoomId = str` |

### Enum 总是继承 str

```python
class Phase(str, Enum):
    NIGHT_START = "NIGHT_START"
```

这样 JSON 序列化和字符串比较都没问题。

---

## 四、类型注解

**所有公共函数与方法**必须有完整的参数与返回值注解：

```python
def create_game(
    seed: int = 7,
    show_private: bool = False,
    agent_type: str = "llm",
    human_seat: int | None = None,
) -> dict[str, Any]:
    ...
```

**dataclass 字段必须有类型**。可变默认值用 `field(default_factory=...)`：

```python
@dataclass
class RoomRecord:
    id: str
    game_history: list[str] = field(default_factory=list)
    latest_snapshot: dict[str, Any] | None = None
```

`Any` 仅用于真正不可控的外部数据（如 YAML、JSON 输入），其他场景必须收紧。

---

## 五、数据模型选型

| 场景 | 选什么 |
|------|--------|
| 内部游戏状态、协议 schema | `@dataclass`（已选定，不要改） |
| FastAPI 请求体（带 validation） | 在路由签名直接列参数，复杂时再考虑 Pydantic |
| DB 表 | `sqlalchemy` Declarative（见 `backend/db/models.py`） |
| 枚举 | `class XxxEnum(str, Enum)` |

**不要混用** Pydantic 和 dataclass 表达同一个东西。要么全用 dataclass + 手写 `to_dict()`，要么单独场景用 Pydantic。

---

## 六、Agent 接口（Protocol）

```python
class Agent(Protocol):
    player_id: str
    def initialize(self, view: PlayerView, game_setting: dict) -> None: ...
    def talk(self) -> Decision: ...
    ...
```

新增 Agent 类型时，**实现** Protocol 即可，不要继承——这是 duck typing 的好处。详见 `40-agent-development.md`。

---

## 七、FastAPI 路由约定

### URL 风格

- 资源用复数名词：`/api/games`、`/api/rooms`
- 嵌套子资源：`/api/rooms/{room_id}/games`
- 动作用查询参数 / POST body，**不要** 在 URL 里塞动词（`/api/games/start` 这种禁止）
- 所有路由都挂在 `/api/` 前缀下

### 函数签名

```python
@app.post("/api/games")
def create_game(
    seed: int = 7,
    show_private: bool = False,
    agent_type: str = "llm",
    human_seat: int | None = None,
    player_count: int = 7,
    rule_pack_id: str = "wolfcha-default",
):
    ...
```

- 路由函数**只做装配**：解析参数 → 调引擎 → 序列化返回
- 业务逻辑必须放进 `engine/` 或独立模块
- 异步路由用 `async def`，同步用 `def`（FastAPI 都支持）

### 错误处理

```python
raise HTTPException(status_code=404, detail="Game not found")
```

- 4xx 用于客户端错误，5xx 用于服务端错误
- `detail` 用英文短句（前端有 i18n 字典负责翻译）
- **不要**把内部异常 `str(e)` 直接塞进 detail（可能泄漏 stack）

### 启动钩子

```python
@app.on_event("startup")
def _initialize_database() -> None:
    try:
        init_db()
    except Exception:
        pass
```

启动期失败要**记日志**，但不能阻断启动——除非是 hard requirement。

---

## 八、DB 层

- ORM：sqlalchemy 2.0+
- 表定义在 `backend/db/models.py`
- 写入接口在 `backend/db/persist.py`，**所有 commit / rollback 都在这一层**
- `app.py` / `engine/` 不直接 `session.add()`，必须通过 `persist.py` 暴露的函数

### 后端选择（生产 = PG，开发 fallback = SQLite）

`backend/db/database.py` 按 `DATABASE_URL` 环境变量自动路由：

```python
if os.getenv("DATABASE_URL"):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
else:
    engine = create_engine(f"sqlite:///data/werewolf.db", ...)
```

- **当前默认 PG**：`.env` 已配 `DATABASE_URL=postgresql+psycopg2://werewolf:****@127.0.0.1:5433/werewolf`
- **三人共享同一台 PG**：5433 容器（`werewolf-pg`，docker volume `werewolf-pg-data` 持久化），同机不同账号都连这一个 db
- **快速命令**：`make db-up` / `make db-shell` / `make db-init` / `make db-migrate`

### 写新表时

- 在 `backend/db/models.py` 新增 `Base` 子类
- `Column(..., index=True)` 给单列加索引
- 复合索引或 DESC 索引用 `Index()` + `__table_args__`：

```python
__table_args__ = (
    Index("ix_events_game_seq", "game_id", "seq"),
    Index("ix_games_created_at_desc", created_at.desc()),
)
```

- **JSON 字段**已自动按 dialect 切换（PG 用 `JSONB`、SQLite 用 `JSON`），不要手写 `JSONB`
- 加完字段或索引后跑 `make db-init`（已存在的表会跳过，新索引需走 `scripts/` 或手工 `Index.create(checkfirst=True)` 推到运行中的 PG）

### 索引设计原则

- **查询驱动**：每个索引要对应一个真实的查询模式（在注释里点名是哪个 API/复盘点）
- **复合索引列序**：选择性高的列在前（如 `game_id` 比 `day` 选择性高）
- **不要为低基数列单建索引**（如 `is_alive` 只有 true/false），复合在前列即可
- 改 `models.py` 的索引必须在 PG 上验证：`docker exec werewolf-pg psql -U werewolf -d werewolf -c "\d <table>"`

### Schema 迁移（轻量手工）

项目目前**没有 Alembic**——21 天小项目，schema 变化用以下流程：

1. 改 `backend/db/models.py`（加列 / 加索引 / 加表）
2. 跑 `make db-init` 让 SQLAlchemy 创建尚未存在的对象
3. **现有表加列要手工 `ALTER TABLE`**（SQLAlchemy 默认不会改已存在表的列）
4. PR 描述写清楚 schema 变更，方便队友 `make db-init` 同步
5. 破坏性变更（删列、改类型）→ 先发群里，避免别人没同步导致跑挂

### 失败容忍

DB 操作要**包 try/except 给出降级**——游戏对局本身能跑就行，DB 是观测层。例：

```python
@app.get("/api/history")
def game_history(limit: int = 20):
    from backend.db.persist import list_games as db_list_games
    try:
        return db_list_games(limit=limit)
    except Exception:
        return []
```

### 历史数据迁移

如果之前用 SQLite 跑过，切到 PG 时：

```bash
make db-migrate    # 等价 python scripts/migrate_sqlite_to_pg.py
```

脚本特性：
- **幂等**：按 `id` 跳过已存在行，可重复跑
- **列对齐**：源表缺少的列由模型默认值补齐（适配早期 SQLite schema）
- **自动备份**：完成后把 `data/werewolf.db` 拷贝为 `data/werewolf.db.bak`

---

## 九、LLM 层

- 统一封装在 `backend/llm/`
- **绝对禁止** 在 `agents/llm_agent.py` 之外直接 import OpenAI/方舟 SDK
- Prompt 模板放在 `backend/agents/prompts.py`，**不要散落在 LLM 调用处**
- API Key 通过 `backend/llm/env.py` 读 `.env`，**永远不进代码、不进 commit**

### LLM 调用失败的降级策略

LLM 超时 / 报错时，Agent 必须能给出**确定性的 fallback**（启发式动作 / 随机合法动作），让游戏不卡死。详见 `40-agent-development.md`。

---

## 十、配置与常量

- 游戏可调参数（人数、角色配比、轮次上限）→ YAML，例 `configs/demo.yaml`
- 代码内魔术数字 → 抽成模块顶部常量（`UPPER_SNAKE`）
- Path 拼接用 `pathlib.Path`，不要字符串拼接

```python
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
```

---

## 十一、注释与 docstring

参考 base.py 的极简风格：

```python
class Agent(Protocol):
    """AIWolf-inspired lifecycle used by the local game engine."""
```

- **公共类 / 公共函数**：1-3 行 docstring 说明用途，**不要写参数表**（看类型注解即可）
- **行内注释**：只写"为什么"，不写"什么"——代码自己说明
- **禁止** 重复代码内容的注释（`x = x + 1  # 把 x 加一`）
- **禁止** 留 `TODO` 而不开 issue，要 TODO 就 `# TODO(alice): xxx (#issue-123)`

---

## 十二、日志

- 当前项目用 `print` 较少，未来引入要走 `logging.getLogger(__name__)`
- 事件日志走 `backend/engine/models.py` 的 `GameEvent`，**不要**用日志来记业务事件
- DEBUG 日志可以多，但生产开关靠环境变量

---

## 十三、测试可见性

为了让 `engine/` 易测：

- 引擎主函数都接 `seed: int` 让对局确定性可复现
- 没有全局状态，所有状态都挂在 `GameState` 上
- 时间依赖用 `time()` 注入，不要 hardcode `datetime.now()`

详见 `60-testing-ci.md`。

---

## 十四、AI 改后端的红线

让 AI 写后端代码时，至少检查：

- [ ] 文件首行有 `from __future__ import annotations`
- [ ] 类型注解齐全，没有出现 `Any` 滥用
- [ ] 没有在 `engine/` 里 import `protocols/` / `db/` / `llm/`
- [ ] Enum 都 `(str, Enum)` 继承
- [ ] dataclass 用了 `field(default_factory=...)` 而非可变默认值
- [ ] 路由 URL 名词化、`/api/` 前缀
- [ ] LLM 调用有 fallback
- [ ] 注释没有"AI 自动生成"/"由 Claude 添加"等无意义信息
- [ ] 没有把 API Key、Prompt 文件全文塞进代码

详见 `70-ai-collaboration.md`。

---

*Version 1.0.0 — 2026-05-22 — 初始建立。*
