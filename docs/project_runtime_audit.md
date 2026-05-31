# Part 0: 项目运行入口审计

> 审计日期: 2026-05-28 | 审计范围: 全项目 | 状态: 只读

---

## 0.1 必需环境变量

| 变量 | 用途 | 是否必需 |
|------|------|----------|
| `DOUBAO_API_KEY` | 豆包 LLM API Key (主力模型) | 跑 LLM Agent 必需 |
| `DOUBAO_BASE_URL` | 豆包 API 地址 | 有默认值 `ark.cn-beijing.volces.com/api/v3` |
| `DOUBAO_ENDPOINT` | 豆包端点 ID | 有默认值 `ep-20260514115354-k4jz4` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key (备选) | 如果用 deepseek provider |
| `DATABASE_URL` | PostgreSQL 连接串 | 未设则 fallback 到 SQLite |
| `NEXT_PUBLIC_BACKEND_ORIGIN` | 前端连后端的地址 | 前端必需，默认 `http://localhost:8000` |
| `LLM_PROVIDER` | LLM provider 选择 | 默认 `doubao` |

**配置文件**: `.env.example` **存在** (项目根目录)。

---

## 0.2 依赖安装

```bash
# 后端依赖
pip install -r requirements.txt

# requirements.txt 内容 (仅 6 行):
# fastapi>=0.111, uvicorn[standard]>=0.30, PyYAML>=5.4, pytest>=8.2, sqlalchemy>=2.0, psycopg2-binary>=2.9

# 前端依赖
cd frontend && npm install --legacy-peer-deps
```

**注意**: `requirements.txt` 仅 6 行，实际运行脚本还需要:
- `httpx` (LLM 客户端)
- `scikit-learn` (Track B 评分模型)
- `numpy`, `pandas` (Track B 数据处理)
- `FlagEmbedding` (BGE-M3 检索)
- `matplotlib` (SVG 图表)
- 等

这些依赖在 `requirements.txt` 中**未列出**，需要从实际 import 中推断。

---

## 0.3 数据库

```bash
# 方式 1: PostgreSQL (推荐，docker)
docker run -d --name werewolf-pg \
  -e POSTGRES_USER=werewolf -e POSTGRES_PASSWORD=wolf_secret_2026 \
  -e POSTGRES_DB=werewolf -p 5433:5432 postgres:16

# 方式 2: SQLite (零依赖，默认 fallback)
# DATABASE_URL 留空即可，自动使用 data/werewolf.db

# 初始化表结构
python -c "from backend.db.database import init_db; init_db()"
```

---

## 0.4 后端启动

```bash
# 开发模式
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 入口文件: backend/app.py
# FastAPI app, 版本 0.2.0
# CORS: 全开 (*)
# 路由数量: 30+ REST + 2 WebSocket
```

---

## 0.5 前端启动

```bash
cd frontend
cp .env.example .env.local
# 确保 NEXT_PUBLIC_BACKEND_ORIGIN=http://localhost:8000
npm install --legacy-peer-deps
npm run dev
# 浏览器打开 http://localhost:3001 (或 :3002)
```

---

## 0.6 运行一局游戏

```bash
# 方式 1: 纯启发式 Agent (秒级，不需要 LLM API)
python -m backend.run_demo --seed 7

# 方式 2: 通过 API (后端必须先启动)
curl -X POST "http://localhost:8000/api/rooms?name=Demo&seed=7&player_count=7&agent_type=heuristic"
curl -X POST "http://localhost:8000/api/rooms/<room_id>/games"

# 方式 3: WebSocket (前端 UI 自动调用)
# 打开 http://localhost:3001 → 选 AI vs AI → 开始游戏

# 入口文件:
# - 命令行: backend/run_demo.py
# - API: backend/app.py → _build_game() → WerewolfGame(...).play()
# - WebSocket: backend/app.py → /ws/rooms/{room_id}
```

**当前状态**: `make demo` 命令在 README 中提到但 **Makefile 不存在**。实际命令是 `python -m backend.run_demo --seed 7`。

---

## 0.7 运行多局实验

```bash
# 主批量脚本
python scripts/run_full_llm_pipeline.py --seeds 10 --strict

# 并行批量
python scripts/run_phase_f_parallel.py

# LLM 批量对局
python scripts/llm_batch.py

# 各脚本独立运行，无统一入口
# 每个脚本有自己的参数，需要分别查看 --help
```

**当前状态**: 有多个批量脚本但**无统一 `make batch` 或等效命令**。每个脚本是独立的一次性实验工具。

---

## 0.8 运行 B 评分 (Track B)

```bash
# V7 完整评分 pipe (需要先有 DB 中的游戏数据)
python scripts/v7_private_context.py      # V7-1~8: private context scoring
python scripts/generate_v7_deliverables.py # 生成所有 V7 交付物

# V6 评分
python scripts/v6_benchmark_ready.py

# V5 评分
python scripts/v5_benchmark.py

# 评分模型训练
python scripts/train_and_ablate.py
python scripts/v3_full_pipeline.py

# 机会提取
python scripts/extract_opportunities.py
python scripts/build_v3_features.py
```

**当前状态**: 评分 pipe 分散在多个独立脚本中，按版本号 (V2→V7) 递增，无统一入口。每个脚本读写 `data/health/` 中的中间文件。

---

## 0.9 生成 MBTI Dashboard

```bash
# 最新版本 (V7, Metrics Fixed)
python scripts/fix_mbti_metrics_v2.py

# 输出文件:
# data/health/mbti_performance_dashboard_v7_metrics_fixed.html
```

---

## 0.10 生成单局复盘 HTML

```bash
# 单个游戏
python scripts/render_single_game_html.py --game-id <game_id>

# 批量 (通过 generate_v7_deliverables.py)
python scripts/generate_v7_deliverables.py

# 输出文件:
# data/health/reports/review_game_<game_id>.html
```

---

## 0.11 当前能否一键跑通？

| 步骤 | 状态 | 问题 |
|------|------|------|
| 后端启动 | ✅ 可跑 | `uvicorn backend.app:app` |
| 前端启动 | ✅ 可跑 | `npm run dev` |
| 跑一局 (启发式) | ✅ 可跑 | `python -m backend.run_demo` |
| 跑一局 (LLM) | ⚠️ 需 API Key | 需要 `DOUBAO_API_KEY` |
| 跑一局 (前端 UI) | ✅ 可跑 | WebSocket 自动驱动 |
| 批量对局 | ⚠️ 碎片化 | 多个脚本，无统一入口 |
| B 评分完整 pipe | ⚠️ 碎片化 | V2→V7 独立脚本，需手动串联 |
| MBTI Dashboard | ✅ 可跑 | `fix_mbti_metrics_v2.py` |
| 单局复盘 HTML | ✅ 可跑 | 依赖 DB 中有游戏数据 |
| Docker 全栈 | ⚠️ 缺 Makefile | `docker-compose.yml` 存在但无 Makefile |

### 缺失步骤 (按优先级)

1. **Makefile 不存在** — README 引用了 `make demo`, `make dev`, `make db-up` 等命令，但项目根目录**没有 Makefile**。需要创建或更新 README。
2. **requirements.txt 不完整** — 缺少 `httpx`, `scikit-learn`, `numpy`, `pandas`, `matplotlib`, `FlagEmbedding` 等。
3. **无统一 B 评分入口** — 用户需要知道先跑哪个脚本、后跑哪个脚本，中间文件格式不明确。
4. **无 .env.example** — 虽然文件存在但我无法确认内容 (需要 LLM API key 模板)。

---

## 0.12 关键入口文件速查

| 功能 | 文件 | 命令 |
|------|------|------|
| 后端 API | `backend/app.py` | `uvicorn backend.app:app --port 8000` |
| 命令行 Demo | `backend/run_demo.py` | `python -m backend.run_demo --seed 7` |
| 前端 Dev | `frontend/` | `npm run dev` (端口 3001) |
| 游戏引擎 | `backend/engine/game.py` | (被 app.py/run_demo.py 调用) |
| Agent 创建 | `backend/agents/factory.py` | (被 game.py 调用) |
| LLM 客户端 | `backend/llm/deepseek.py` | (被 llm_agent.py 调用) |
| B 评分核心 | `backend/eval/review.py` | (被 track_b.py/各脚本调用) |
| B 评测发布 | `backend/eval/track_b.py` | (被 persist.py 调用) |
| C 自进化 | `backend/eval/evolution.py` | (被 API/脚本调用) |
