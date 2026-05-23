# AI Werewolf

AI 狼人杀多智能体对战系统。每个 Agent 根据扮演角色（狼人 / 预言家 / 女巫 / 猎人 / 守卫 / 村民等）拥有独立目标、策略与行动空间，在严格信息隔离下推理、发言、投票，最终分出胜负。

## 功能特性

- **7~12 人板子** — wolfcha 风格的角色配置（默认 7 人：2 狼 + 预言家 + 女巫 + 猎人 + 守卫 + 村民），更多人数自动加入白狼王/白痴。
- **完整对局流程** — 夜晚守护/狼人刀人/女巫用药/预言家查验/夜晚结算/警长竞选/白天发言/投票/PK 加赛/猎人开枪/白狼王自爆/胜负判定。
- **角色 Agent**
  - `LLMAgent` — 调用方舟 doubao 或 DeepSeek API，按角色定制 Prompt、CoT 推理、JSON 输出解析；解析失败自动回退到启发式 Agent。
  - `HeuristicAgent` — 纯离线启发式策略，作为 fallback 和确定性测试用。
  - `HumanAgent` — 接收前端提交的文字/语音发言、投票、夜晚动作。
- **wolfcha 人设系统** — 每位玩家拥有 Persona（MBTI、年龄、背景、说话风格、压力反应等）+ PlayerMind（勇气、记忆偏好、桌面存在感等），影响发言风格与决策倾向。
- **严格信息隔离** — `Visibility` 为每个 Agent 生成专属 PlayerView，只暴露角色权限内的事件与状态；测试覆盖了村民/狼人/预言家的可见性边界。
- **结构化日志** — 每个事件、决策都写入 `GameEvent` 与 `DecisionAudit`；运行后入库 SQLite（默认）或 Postgres（设置 `DATABASE_URL`）。
- **断点续跑** — 内部使用 per-day 完成集合追踪 phase 完成度，人类玩家随时暂停 → 提交动作 → 自动恢复，不重复触发已完成阶段。
- **WebSocket 实时推送** — 房间维度的快照流，前端按阶段推进事件墙。
- **观战 / 主持视角切换** — 主持视角可看全员身份与私密决策；公开视角严格脱敏。
- **历史对局回看** — `/api/history` 列出全部 finished 局，`/api/history/{id}` 返回发言、投票、死亡、决策计数。

## 快速开始

```bash
# 1. 后端依赖
python -m pip install -r requirements.txt

# 2. 配置 LLM + DB（已提供 .env.example，复制后填上 key）
cp .env.example .env  # 编辑填入 DOUBAO_API_KEY 或 DEEPSEEK_API_KEY

# 3. 起本地 Postgres（推荐；不装也行,会 fallback 到 SQLite）
make db-up

# 4. 本地跑一局（启发式 Agent，秒级出结果）
make demo

# 5. 启动后端 API + WebSocket（端口 8000）
make dev   # 等价 uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 6. 启动前端 Next.js dev server（端口 3001 / 占用就 3002）
cd frontend && npm install --legacy-peer-deps && npm run dev
# 浏览器打开 http://localhost:3001 (或 :3002)
```

一条命令拉起全栈（Postgres + 后端 + 前端）：

```bash
make compose-up    # 等价 docker compose up -d --build
make compose-logs  # 看后端日志
make compose-down
```

> **入口说明**：后端 `http://localhost:8000/` 现在只返回 JSON 提示（指向 :3001/:3002）；
> 真正的 UI 在 Next.js dev server 上，所有页面、组件、样式都在 `frontend/app/` 与 `frontend/components/` 下。

## 三种玩法

### A. 纯 AI 观战
- 顶部选 `AI vs AI`，选 LLM 或 Heuristic Agent，点 `开始游戏`。

### B. 真人 + AI 混战
- 顶部选 `AI + Human`，选你的座位号（1~7），点 `开始游戏`。
- 轮到你时下方会弹出动作面板：
  - 文字输入：直接打字。
  - **语音输入**：点麦克风按钮（🎤），浏览器调用 Web Speech API（Chrome/Edge 支持），识别后自动填入输入框，再次点击停止。
- 投票/夜晚动作时面板会切换为目标选择。

> 上述 UI 全部由 Next.js 前端实现，运行在 `:3001` / `:3002`。

### C. API 直接调用

#### 核心 (MVP)
```bash
curl -X POST "http://localhost:8000/api/rooms?name=Demo&seed=7&player_count=7&agent_type=llm"
curl -X POST "http://localhost:8000/api/rooms/<room_id>/games"
curl "http://localhost:8000/api/history"
curl "http://localhost:8000/api/history/<game_id>"
```

#### 进阶预留（B：评测复盘 / C：自进化）
```bash
# 整局回放（含全部事件+决策，可加 ?show_private=true 看主持视角）
curl "http://localhost:8000/api/replay/<game_id>"
# 单局多维指标（按玩家分组）
curl "http://localhost:8000/api/games/<game_id>/metrics"
# 聚合排行榜（按角色 + agent_type 聚合，可加 ?role=Werewolf）
curl "http://localhost:8000/api/leaderboard"
# 评测 agent 写入的复盘报告（暂为空，待 Track B reviewer 接入）
curl "http://localhost:8000/api/games/<game_id>/reviews"
# Agent 版本注册表（Track C 自进化使用）
curl "http://localhost:8000/api/agents"
curl -X POST "http://localhost:8000/api/agents" -H 'Content-Type: application/json' \
  -d '{"name":"doubao-v1","agent_type":"llm","model_name":"Doubao-Seed-2.0-pro","prompt_version":"v1"}'
# 自进化迭代日志
curl "http://localhost:8000/api/evolution"
```

## 项目结构

```
backend/
  app.py                  # FastAPI 入口 + REST + WebSocket
  engine/
    game.py               # 主对局引擎（阶段流转 / 结算 / 资源恢复）
    models.py             # GameState / Phase / Decision / EventLog dataclass
    phases.py             # PhaseMachine 组合
    rules.py              # 角色配置、人数→板子映射
    visibility.py         # 每个 Agent 的可见信息构造
    actions.py            # ActionValidator
    summary.py            # 每日总结
  agents/
    base.py               # Agent 协议（initialize/update/talk/vote/...）
    llm_agent.py          # LLM Agent + heuristic fallback
    heuristic.py          # 纯启发式 Agent
    human_agent.py        # 真人 Agent
    characters.py         # wolfcha Persona + PlayerMind 系统
    prompts.py            # 各角色 / 各动作的 Prompt 模板
    playbooks.py          # 角色策略简述
  llm/
    deepseek.py           # 统一 LLM 客户端
    __init__.py           # provider 路由（doubao / deepseek）
  db/
    database.py           # SQLAlchemy 引擎（SQLite / Postgres）
    models.py             # ER：games/players/game_events/agent_decisions/votes/snapshots
    persist.py            # 对局结束时批量入库 + history 查询
  protocols/
    rooms.py / schemas.py # RoomManager
frontend/                 # Next.js 14 + React 18 + TS 5 + Tailwind 3
  app/                    # App Router 页面（page.tsx / layout.tsx / globals.css）
  components/
    ui/                   # 通用元件（Badge / Button / Card）
    game/                 # 业务组件（PhaseBanner / PlayerCard / EventItem / DayBlock）
  lib/                    # i18n.ts + utils.ts（cn() 等）
  context/AppContext.tsx  # 全局状态（语言 / 视角 / 当前对局 / WS）
  types/index.ts          # 后端 schema 的 TS 镜像（Phase / Role / EventType / ...）
  tailwind.config.ts      # 极简素雅主题 token
  package.json
configs/
  demo.yaml               # 默认 7 人板子配置
scripts/
  e2e_smoke.py            # AI vs AI 端到端
  human_smoke.py          # 真人座位端到端
  migrate_sqlite_to_pg.py # SQLite → PG 历史数据迁移
tests/
  test_engine.py          # 引擎单元测试（PK / 警徽 / 信息隔离 / 白痴 / 白狼王）
  test_api.py             # FastAPI 集成测试
  test_llm_config.py      # LLM provider 配置
```

## 数据库

**生产/团队开发：PostgreSQL 16（Docker，端口 5433）— 当前默认配置**。SQLite 仅作为零依赖 fallback（`DATABASE_URL` 未设时启用）。

### 起 PG + 接入

```bash
# 1. 起 docker postgres（已有同名容器会复用）
make db-up

# 2. .env 已默认指向本地 PG：
# DATABASE_URL=postgresql+psycopg2://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf

# 3. 初始化 schema + 索引
make db-init

# 4. (可选) 从旧 SQLite 迁移历史对局到 PG（幂等，可重复跑）
make db-migrate

# 5. 进 psql shell 排查
make db-shell
```

或者一行起完整栈：`make compose-up`（postgres + backend）。

### 三人共享同一台 PG

5433 端口已绑 `0.0.0.0`，**同机不同账号**的队友直接连同一个 `werewolf-pg` 容器即可——三人对局数据汇集到一个 db，评测/Leaderboard 自动跨人聚合。

> ⚠️ 默认密码 `wolf_secret_2026` 强度一般，仅适用内网/同机访问。若 5433 对外公网开放，**先**改强密码（同时改 `docker run` env、`.env`、`docker-compose.yml`）。

### Schema（11 张表 + 24 个索引）

**MVP 用到 (7 张)**
- `games` — 一行：id / status / winner / day / seed / 时间戳
- `players` — 每位玩家身份与最终存活状态
- `game_events` — 全部事件（public / private 标记）
- `agent_decisions` — 每次询问的观察 / 原始 LLM 输出 / 解析结果 / 是否合法 / 延迟 / token 数
- `votes` — 每日投票
- `game_snapshots` — 终局完整快照（公开 + 主持双版本）
- `evaluations` — 每局每玩家的 KPI（win / survived / speech_count，可由 reviewer agent 追加更多）

**Track B 评测复盘预留 (2 张)**
- `leaderboard_entries` — 按 `(agent_label, role)` 聚合的胜率与 KPI
- `review_reports` — Reviewer agent 输出的关键决策复盘 / 反事实分析 / 改进建议

**Track C 自进化预留 (2 张)**
- `agent_versions` — Agent 版本登记表（prompt / model / config 快照），支持 parent 链
- `evolution_rounds` — 每轮 baseline vs challenger 的 20 局对战结果，可回溯

### 索引（PG 上自动建立）

按高频查询模式建了 24 个索引：

| 表 | 复合索引 | 用途 |
|---|---|---|
| `games` | `created_at DESC` / `(status, rule_pack_id)` | 历史列表 / 板子级胜率 |
| `players` | `(game_id, seat_no)` / `(model_name, role)` | 座位渲染 / 模型×角色 KPI |
| `game_events` | `(game_id, seq)` / `(game_id, event_type)` / `(game_id, day, phase)` | Replay / 事件筛 / 阶段切片 |
| `agent_decisions` | `(game_id, player_id, day)` / `(is_valid, error_type)` | 复盘 / 失败归因 |
| `game_snapshots` | `(game_id, day, phase)` | 跳到任意阶段 |
| `votes` | `(game_id, day)` / `voter_id` | 票型分析 / 玩家投票画像 |
| `evaluations` | `(metric_name, player_id)` | 跨局指标聚合 |

## 测试

```bash
pytest tests/test_engine.py tests/test_llm_config.py  # 单元
python scripts/e2e_smoke.py                          # AI vs AI 端到端
python scripts/human_smoke.py                        # 真人座位端到端
# UI 浏览器测试（可选）：
# npm install && npx playwright install chromium && npm run test:ui
```

## 扩展

- 新角色：`engine/rules.py` 加 `RoleSpec` 与板子配置，`engine/game.py` 增对应阶段方法。
- 新 Agent：实现 `agents/base.py::Agent` 接口即可，工厂在 `agents/factory.py` 注册。
- 新动作：`engine/actions.py` 注册 `ActionRule`，新阶段在 `engine/phases.py` 加入 PhaseMachine。
- 切换 LLM：`.env` 改 `LLM_PROVIDER`，或在 `backend/llm/__init__.py` 新增 provider 分支。
