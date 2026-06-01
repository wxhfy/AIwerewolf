# AI Werewolf

AI 狼人杀多智能体对战系统。每个 Agent 根据扮演角色（狼人 / 预言家 / 女巫 / 猎人 / 守卫 / 村民 / 白痴 / 白狼王）拥有独立目标、策略与行动空间，在严格信息隔离下推理、发言、投票，最终分出胜负。

> 项目分三条轨道：**Track A 基础对局**（✅ 完成）/ **Track B 评测复盘**（✅ 完成）/ **Track C 自进化 Agent**（✅ 完成）。三条轨道均已落地代码、API、前端面板和测试，不再是"预留"。

---

## 三大轨道速览

| Track | 名称 | 后端入口 | 前端面板 | 验收脚本 |
|---|---|---|---|---|
| **A** | 基础对局引擎 | `backend/engine/` + `backend/app.py` | `/`、`/room/[id]/play` | `scripts/e2e_smoke.py`、`scripts/human_smoke.py` |
| **B** | 评测 + 复盘 + 校验 | `backend/eval/review.py`、`track_b.py` | `/eval/dashboard`、`/games/[id]/report` | `scripts/bc_quantify.py`、`scripts/bc_repair_loop_check.py` |
| **C** | 自进化 Agent | `backend/eval/evolution.py` | `/evolution` | `scripts/track_c_verify.py`、`scripts/c_real_llm_ab_validation.py` |

---

## 功能特性

### Track A — 对局引擎
- **7~12 人板子** — wolfcha 风格（默认 7 人：2 狼 + 预言家 + 女巫 + 猎人 + 守卫 + 村民），更多人数自动加入白狼王/白痴。
- **完整对局流程** — 夜晚守护/狼人刀人/女巫用药/预言家查验/夜晚结算/警长竞选/白天发言/投票/PK 加赛/猎人开枪/白狼王自爆/胜负判定。
- **三类 Agent**
  - `LLMAgent` — 调用方舟 doubao 或 DeepSeek API，按角色定制 Prompt、CoT 推理、JSON 输出解析；解析失败自动回退到启发式 Agent。
  - `HeuristicAgent` — 纯离线启发式策略，作为 fallback 和确定性测试用。
  - `HumanAgent` — 接收前端提交的文字/语音发言、投票、夜晚动作。
- **wolfcha 人设系统** — 每位玩家拥有 Persona（MBTI、年龄、背景、说话风格、压力反应）+ PlayerMind（勇气、记忆偏好、桌面存在感等），影响发言风格与决策倾向。
- **严格信息隔离** — `Visibility` 为每个 Agent 生成专属 PlayerView，只暴露角色权限内的事件与状态。
- **结构化日志 + 断点续跑** — 全部事件、决策入 `GameEvent` / `AgentDecision`；per-day 完成集合追踪 phase，真人随时暂停 → 提交动作 → 自动恢复。
- **WebSocket 实时推送** — 房间维度快照流；前端按阶段推进事件墙。
- **观战 / 主持视角切换** — 主持可看全员身份与私密决策；公开视角严格脱敏。

### Track B — 评测复盘（已实装）
- **多维玩家分**（`eval/review.py`） — process_score（0~100，惩罚错投/泄露/逻辑漏洞）+ outcome_bonus（0/100，阵营胜负）+ final_score（综合），分离"过程质量"与"结果偏差"。
- **ProcessScoreV3**（`eval/process_score_v3.py`） — 角色归一化、置信度感知的玩家过程评分，替代简单加权平均。
- **HybridScorer**（`eval/hybrid_scorer.py`） — 规则锁定 + LLM 证据校验 + 统计校准的混合评分框架（参考 Rulers 论文）。
- **PerStepScorer**（`eval/per_step_scorer.py`） — 逐步评分器，对发言/投票/夜间行动进行细粒度评分。
- **PersonaScorer**（`eval/persona_scorer.py`） — 人设一致性评分，评估玩家是否符合角色设定。
- **StrategyScorer**（`eval/strategy_scorer.py`） — 策略影响评分，评估策略检索和应用效果。
- **EloRating**（`eval/elo_rating.py`） — Elo 评分系统，支持跨局排名。
- **ScoreCalibrator**（`eval/calibration.py`） — Ridge 回归 + 分位数映射的评分校准。
- **角色 KPI + 跨局排行**（`eval/track_b.py`） — `/api/leaderboard`、`/api/leaderboard/role_matrix`、`/api/metrics/aggregate` 支持按 `agent_label × role × seed × 时间窗` 多维聚合。
- **Reviewer Agent** — 自动生成关键决策复盘 / 反事实分析 / 改进建议；输出落 `review_reports` 表，可拉 Markdown / HTML / JSON。
- **校验闭环**（B Repair Loop） — 复盘报告先过 ValidationGate（事实一致、引用完整、配额平衡），失败回炉重写；`scripts/bc_repair_loop_check.py` 跟踪通过率。
- **评分区分度实验**（`scripts/score_discrimination_experiment.py`） — 验证好/差对局的分数分布可分离；`configs/discrimination_strategies.yaml` 配置候选打分策略。
- **前端面板** — `/eval/dashboard` 展示 leaderboard + 角色矩阵 + 时间趋势；`/games/[id]/report` 展示单局复盘报告。

#### Learned Evaluator v1（`learned-evaluator-v1`）
- **机会级决策质量建模**（`backend/eval/opportunity.py`） — 2461 条 DecisionOpportunity，覆盖 6 角色 × 10 种机会类型。
- **DecisionQualityModel**（`backend/eval/scoring_models.py`） — GradientBoosting + GroupKFold（by game_id），Pairwise Accuracy 91.8%。
- **BGE-M3 相似案例检索**（`backend/eval/embedding_retrieval.py`） — 本地模型 `/home/4T-3/PLM/bge-m3/`，anti-leakage GroupKFold 内建索引。
- **SpeechScore**（`scripts/compute_speech_and_counterfactual.py`） — groundedness + stance_clarity + consistency + strategic_value + information_safety。
- **CounterfactualImpact** — vote_flip + skill_swap 反事实分析。
- **已知问题**：Guard d=-0.127，Hunter d=0.349，embedding 检索增益有限（+0.007 paw）。详见 `data/health/learned_evaluator_ablation_report_d.md`。

### Track C — 自进化 Agent（已实装）
- **策略知识库**（`StrategyKnowledgeDoc`） — Reviewer 通过的复盘 → 抽取策略片段 → 入库，按角色/阶段/标签检索。
- **角色策略卡 + Persona 适配器**（`RoleStrategyCard` / `PersonaRoleAdapter`） — 每个角色×Persona 维护独立策略 profile。
- **进化循环** — `/api/evolution/cycle` 触发一轮 baseline vs challenger 对局；通过 `EvolutionTournament` 记录战绩并回滚不达标 patch。
- **Strategy Patch 流水线** — `StrategyPatch` 描述对策略卡的增量改动 → ValidationGate 校验 → `/api/strategy/patches/{id}/apply` 落库。
- **知识反馈环**（`KnowledgeUsageFeedback`） — Agent 实战中调用某条策略时打分（是否帮到决策），反哺下一轮 patch 候选排序。
- **前端面板** — `/evolution` 展示 evolution 轮次、策略卡 diff、tournament 胜率。

---

## 快速开始

```bash
# 1. 后端依赖
python -m pip install -r requirements.txt

# 2. 配置 LLM + DB（已提供 .env.example，复制后填上 key）
cp .env.example .env  # 编辑填入 DOUBAO_API_KEY 或 DEEPSEEK_API_KEY

# 3. 起本地 Postgres（推荐；不装也行,会 fallback 到 SQLite）
make db-up
make db-init       # 建表 + 索引

# 4. 本地跑一局（启发式 Agent，秒级出结果）
make demo

# 5. 启动后端 API + WebSocket（端口 8000）
make dev   # 等价 uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# 6. 启动前端 Next.js dev server（端口 3001 / 占用就 3002）
cd frontend && cp .env.example .env.local   # 关键：告诉前端后端在哪
                                            # 默认 NEXT_PUBLIC_BACKEND_ORIGIN=http://localhost:8000
npm install --legacy-peer-deps && npm run dev
# 浏览器打开 http://localhost:3001 (或 :3002)
```

> ⚠️ **必须设 `NEXT_PUBLIC_BACKEND_ORIGIN`**：未设时前端会回退到 `window.location.origin`（即前端自己的 3001/3002 端口）去 fetch `/api/*`，全部返回 404/500，看起来像"后端坏了"。dev 默认值是 `http://localhost:8000`；docker compose 部署时统一反代到同源，可留空。

一条命令拉起全栈（Postgres + 后端 + 前端）：

```bash
make compose-up    # 等价 docker compose up -d --build
make compose-logs  # 看后端日志
make compose-down
```

> **入口说明**：后端 `http://localhost:8000/` 现在只返回 JSON 提示（指向 :3001/:3002）；
> 真正的 UI 在 Next.js dev server 上，所有页面、组件、样式都在 `frontend/app/` 与 `frontend/components/` 下。

---

## 三种玩法（玩家视角）

### A. 纯 AI 观战
- 顶部选 `AI vs AI`，选 LLM 或 Heuristic Agent，点 `开始游戏`。

### B. 真人 + AI 混战
- 顶部选 `AI + Human`，选你的座位号（1~7），点 `开始游戏`。
- 轮到你时下方会弹出动作面板：
  - 文字输入：直接打字。
  - **语音输入**：点麦克风按钮（🎤），浏览器调用 Web Speech API（Chrome/Edge 支持），识别后自动填入输入框。
- 投票/夜晚动作时面板会切换为目标选择。

### C. API 直接调用

#### 核心对局（Track A）
```bash
curl -X POST "http://localhost:8000/api/rooms?name=Demo&seed=7&player_count=7&agent_type=llm"
curl -X POST "http://localhost:8000/api/rooms/<room_id>/games"
curl "http://localhost:8000/api/history"
curl "http://localhost:8000/api/history/<game_id>"
curl "http://localhost:8000/api/replay/<game_id>"          # 整局回放（?show_private=true 看主持视角）
```

#### 评测复盘（Track B）
```bash
curl "http://localhost:8000/api/games/<game_id>/metrics"               # 单局多维指标
curl "http://localhost:8000/api/games/<game_id>/runtime_metrics"       # LLM 延迟 / token / 失败率
curl "http://localhost:8000/api/metrics/aggregate?role=Werewolf"       # 跨局聚合
curl "http://localhost:8000/api/leaderboard"                           # 排行榜（按 agent×role）
curl "http://localhost:8000/api/leaderboard/role_matrix"               # 角色矩阵
curl "http://localhost:8000/api/strategy/attribution"                  # 策略归因
curl "http://localhost:8000/api/games/<game_id>/reviews"               # 复盘 JSON
curl "http://localhost:8000/api/games/<game_id>/reviews/html"          # 复盘 HTML
curl "http://localhost:8000/api/games/<game_id>/reviews.md"            # 复盘 Markdown
curl "http://localhost:8000/api/eval/role-scores"                      # 角色分数分布
```

#### 自进化（Track C）
```bash
curl "http://localhost:8000/api/agents"                                # Agent 版本注册表
curl -X POST "http://localhost:8000/api/agents" -H 'Content-Type: application/json' \
  -d '{"name":"doubao-v1","agent_type":"llm","model_name":"Doubao-Seed-2.0-pro","prompt_version":"v1"}'
curl "http://localhost:8000/api/evolution"                             # 进化迭代日志
curl "http://localhost:8000/api/evolution/dashboard"                   # 进化看板数据
curl -X POST "http://localhost:8000/api/evolution/cycle"               # 触发一轮 baseline vs challenger
curl -X POST "http://localhost:8000/api/evolution/dream"               # 离线 dream replay
curl "http://localhost:8000/api/strategy/knowledge"                    # 策略知识库
curl "http://localhost:8000/api/strategy/cards"                        # 角色策略卡
curl -X POST "http://localhost:8000/api/strategy/knowledge/extract/<game_id>"
curl -X POST "http://localhost:8000/api/strategy/patches/<patch_id>/apply"
curl "http://localhost:8000/api/personas"                              # 人设库
```

---

## 项目结构

```
backend/
  app.py                  # FastAPI 入口 + REST + WebSocket（40+ 路由）
  run_demo.py             # 启发式 demo 入口
  engine/
    game.py               # 主对局引擎（阶段流转 / 结算 / 资源恢复）
    models.py             # GameState / Phase / Decision / EventLog dataclass
    phases.py             # PhaseMachine 组合
    rules.py              # 角色配置、人数→板子映射
    visibility.py         # 每个 Agent 的可见信息构造
    actions.py            # ActionValidator
    summary.py            # 每日总结
  agents/
    base.py               # Agent 协议
    factory.py            # Agent 工厂（按 agent_type 创建 / 多模型池抽样）
    llm_agent.py          # LLM Agent + heuristic fallback + 策略检索
    heuristic.py          # 纯启发式 Agent
    human_agent.py        # 真人 Agent
    characters.py         # wolfcha Persona + PlayerMind
    profiles.py           # Persona 模板与默认配置
    prompts.py            # 各角色 / 各动作的 Prompt 模板
    playbooks.py          # 角色策略简述
    optimization.py       # Prompt 微调辅助
  llm/
    deepseek.py           # 统一 LLM 客户端
    env.py                # .env 加载
    __init__.py           # provider 路由（doubao / deepseek）
  db/
    database.py           # SQLAlchemy 引擎（SQLite / Postgres）
    models.py             # 21 张表（见下方"数据库"段）
    persist.py            # 对局结束批量入库 + history / leaderboard / 复盘查询
    persona_db.py         # Persona 持久化
  eval/                   # Track B + Track C 主战场
    review.py             # ReviewArtifact / RoleMetrics / Leaderboard / BadCaseDetector
    track_b.py            # ReplayBundle / SpeechActs / SuspicionMatrix / ValidationGate / RepairLoop
    evolution.py          # StrategyKnowledgeDoc / RoleStrategyCard / StrategyPatch / EvolutionRound
    report_graph.py       # 复盘可视化图谱
  protocols/
    rooms.py / schemas.py # RoomManager + 通信 schema

frontend/                 # Next.js 14 + React 18 + TS 5 + Tailwind 3
  app/
    page.tsx              # 首页（lobby / 历史对局）
    layout.tsx / globals.css
    room/[id]/play/       # 对局页（实时观战 / 真人操作）
    eval/dashboard/       # Track B 评测看板
    games/[id]/report/    # 单局复盘报告
    evolution/            # Track C 进化看板
  components/
    ui/                   # 通用元件
    game/                 # 业务组件（PhaseBanner / PlayerCard / EventItem / DayBlock / ChatBubble / VoteTargetGrid 等）
  lib/                    # i18n.ts + utils.ts
  context/AppContext.tsx  # 全局状态
  types/index.ts          # 后端 schema TS 镜像

configs/
  demo.yaml                            # 默认 7 人板子
  discrimination_strategies.yaml       # 评分区分度候选策略 (Track B)
  discrimination_strategies_iter3.yaml # 迭代 3 版本

scripts/
  # 端到端冒烟
  e2e_smoke.py / human_smoke.py / llm_agent_smoke.py / llm_game_smoke.py
  # 批量对局
  llm_batch.py / run_full_llm_pipeline.py / run_phase_f_parallel.py
  # Track B 验收
  bc_quantify.py / bc_repair_loop_check.py / score_discrimination_experiment.py
  analyze_my_batch.py / analyze_score_distributions.py
  # Track C 验收
  track_c_verify.py / c_real_llm_ab_validation.py
  # 运维 / 健康
  track_health.py / migrate_sqlite_to_pg.py

tests/
  conftest.py
  test_engine.py                  # 引擎单元（PK / 警徽 / 信息隔离 / 白痴 / 白狼王）
  test_api.py                     # FastAPI 集成
  test_llm_config.py              # LLM provider 配置
  test_role_registry.py           # 角色注册表
  test_review_metrics.py          # Track B 评分
  test_track_b_pipeline.py        # Track B 流水线（review → validate → repair → publish）
  test_b_full_acceptance.py       # Track B 验收
  test_track_c_evolution.py       # Track C 进化循环
  test_c_acceptance_verification.py  # Track C 验收
  ui_smoke.mjs                    # 前端 smoke (Playwright)

docs/
  REFERENCE.md                    # 参考仓库分析
  prd.md                          # 产品需求
  full-interaction-design.md      # 交互设计
  B_REVIEW_VALIDATION_PLAN.md     # Track B 完整方案
  Track_C_Evolution_Agent_Plan.md # Track C 完整方案
  B_C_OPERATIONAL_REPORT.md       # Track B/C 运维报告
  DEVELOPMENT_ISSUES.md           # 开发坑记录（必读必写）
  DOC_INDEX.md                    # 文档索引（详见 docs/DOC_INDEX.md）
  PROJECT_STATUS.md               # 项目状态速览

skills/                           # 团队协作规范（详见 skills/README.md）
  00-team-overview.md / 10-git-workflow.md / 20-backend-conventions.md
  30-frontend-conventions.md / 40-agent-development.md / 50-api-contract.md
  60-testing-ci.md / 70-ai-collaboration.md
```

---

## 数据库

**生产/团队开发：PostgreSQL 16（Docker，端口 5433）— 当前默认配置**。SQLite 仅作为零依赖 fallback（`DATABASE_URL` 未设时启用）。

### 起 PG + 接入

```bash
make db-up         # 起 docker postgres（已有同名容器会复用）
make db-init       # 建 21 张表 + 索引
make db-migrate    # （可选）SQLite → PG 历史数据迁移，幂等
make db-shell      # 进 psql 排查
```

或者一行起完整栈：`make compose-up`（postgres + backend）。

### 三人共享同一台 PG

5433 端口已绑 `0.0.0.0`，**同机不同账号**的队友直接连同一个 `werewolf-pg` 容器即可——对局数据汇集到一个 db，评测/Leaderboard 自动跨人聚合。

> ⚠️ 默认密码 `wolf_secret_2026` 强度一般，仅适用内网/同机访问。若 5433 对外公网开放，**先**改强密码（同时改 `docker run` env、`.env`、`docker-compose.yml`）。

### Schema（21 张表）

**Track A 对局（7 张）**
- `games` / `players` / `game_events` / `agent_decisions` / `votes` / `game_snapshots` / `evaluations`

**Track B 评测复盘（4 张）**
- `leaderboard_entries` — 按 `(agent_label, role)` 聚合的胜率与 KPI
- `review_reports` — Reviewer 原始输出
- `published_reviews` — 通过 ValidationGate 后的发布版本
- `agent_versions` — Agent 版本注册表（prompt / model / config 快照，支持 parent 链）

**Track C 自进化（9 张）**
- `strategy_knowledge_docs` — 抽取出的策略片段
- `strategy_graph_links` — 策略之间的依赖/冲突关系
- `role_strategy_cards` — 每个角色的活跃策略卡
- `persona_role_adapters` — Persona × Role 适配器
- `strategy_patches` — 策略卡增量改动提案
- `evolution_rounds` — baseline vs challenger 单轮
- `evolution_tournaments` — 多轮 tournament 汇总
- `knowledge_usage_feedback` — 策略实战反馈
- `personas` — 人设库

详见 `backend/db/models.py`；索引按高频查询模式建立（`backend/db/persist.py` 中触发）。

---

## 测试

```bash
# 单元 + 引擎
pytest tests/test_engine.py tests/test_llm_config.py tests/test_role_registry.py

# Track B（review → metrics → pipeline → 全验收）
pytest tests/test_review_metrics.py tests/test_track_b_pipeline.py tests/test_b_full_acceptance.py

# Track C（evolution → 全验收）
pytest tests/test_track_c_evolution.py tests/test_c_acceptance_verification.py

# 端到端
python scripts/e2e_smoke.py            # AI vs AI
python scripts/human_smoke.py          # 真人座位

# 验收脚本（产线健康）
python scripts/bc_quantify.py          # Track B 评分量化
python scripts/bc_repair_loop_check.py # Track B Repair Loop 通过率
python scripts/track_c_verify.py       # Track C 进化循环冒烟
python scripts/track_health.py         # 全链路健康

# 前端 smoke（可选）：
# npm install && npx playwright install chromium && node tests/ui_smoke.mjs
```

---

## 扩展

- **新角色**：`engine/rules.py` 加 `RoleSpec` 与板子配置，`engine/game.py` 增对应阶段方法。
- **新 Agent**：实现 `agents/base.py::Agent` 接口，`agents/factory.py` 注册。
- **新动作**：`engine/actions.py` 注册 `ActionRule`，新阶段在 `engine/phases.py` 加入 PhaseMachine。
- **切换 LLM**：`.env` 改 `LLM_PROVIDER`，或在 `backend/llm/__init__.py` 新增 provider 分支。
- **新评测指标（Track B）**：`eval/review.py` 加 metric 计算，`eval/track_b.py` 注入 ValidationGate / Repair Loop。
- **新策略来源（Track C）**：`eval/evolution.py` 加 `StrategyKnowledgeDoc` 抽取器，新增 PatchOperation 类型。

---

## 文档地图

| 想做 | 看哪里 |
|---|---|
| 上手项目 / 速查 | 本 README + [`CLAUDE.md`](CLAUDE.md) |
| 团队协作规范（必读） | [`skills/README.md`](skills/README.md) → 各 `skills/*.md` |
| 业务知识（角色 / 阶段 / Prompt） | [`SKILLS.md`](SKILLS.md) + [`docs/REFERENCE.md`](docs/REFERENCE.md) |
| Track B 完整方案 | [`docs/track_b_complete.md`](docs/track_b_complete.md) |
| Track C 完整方案 | [`docs/Track_C_Evolution_Agent_Plan.md`](docs/Track_C_Evolution_Agent_Plan.md) |
| 开发踩坑记录 | [`docs/DEVELOPMENT_ISSUES.md`](docs/DEVELOPMENT_ISSUES.md)（必读必写） |
| 文档索引 | [`docs/DOC_INDEX.md`](docs/DOC_INDEX.md) |
| 项目状态 | [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) |
| 待办 | [`TODO.md`](TODO.md) |
