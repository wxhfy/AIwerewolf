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
# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 配置 LLM API（已提供 .env.example，复制后填上 key）
cp .env.example .env  # 编辑填入 DOUBAO_API_KEY 或 DEEPSEEK_API_KEY

# 3. 本地跑一局（启发式 Agent，秒级出结果）
python -m backend.run_demo --seed 7

# 4. 启动后端服务
uvicorn backend.app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```

## 三种玩法

### A. 纯 AI 观战
- 顶部选 `AI vs AI`，选 LLM 或 Heuristic Agent，点 `开始游戏`。

### B. 真人 + AI 混战
- 顶部选 `AI + Human`，选你的座位号（1~7），点 `开始游戏`。
- 轮到你时下方会弹出动作面板：
  - 文字输入：直接打字。
  - **语音输入**：点麦克风按钮（🎤），浏览器调用 Web Speech API（Chrome/Edge 支持），识别后自动填入输入框，再次点击停止。
- 投票/夜晚动作时面板会切换为目标选择。

### C. API 直接调用

```bash
curl -X POST "http://localhost:8000/api/rooms?name=Demo&seed=7&player_count=7&agent_type=llm"
curl -X POST "http://localhost:8000/api/rooms/<room_id>/games"
curl "http://localhost:8000/api/history"
curl "http://localhost:8000/api/history/<game_id>"
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
frontend/
  index.html              # 单页观战 / 互动 UI
  app.js                  # 状态机、WebSocket、语音输入、i18n
  style.css               # wolfcha 风格视觉
configs/
  demo.yaml               # 默认 7 人板子配置
scripts/
  e2e_smoke.py            # AI vs AI 端到端
  human_smoke.py          # 真人座位端到端
tests/
  test_engine.py          # 引擎单元测试（PK / 警徽 / 信息隔离 / 白痴 / 白狼王）
  test_api.py             # FastAPI 集成测试
  test_llm_config.py      # LLM provider 配置
```

## 数据库

默认 SQLite，文件在 `data/werewolf.db`。如需切换 Postgres：

```bash
export DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/werewolf
```

每局结束时入库的内容：
- `games` — 一行：id / status / winner / day / seed / 时间戳
- `players` — 每位玩家身份与最终存活状态
- `game_events` — 全部事件（public + private 标记）
- `agent_decisions` — 每次询问的观察 / 原始 LLM 输出 / 解析结果 / 是否合法 / 延迟
- `votes` — 每日投票
- `game_snapshots` — 终局完整快照（公开 + 主持双版本）

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
