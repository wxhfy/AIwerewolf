# Part 1: 核心目录结构审计

> 审计日期: 2026-05-28 | 状态: 只读 | 证据: 文件系统扫描

---

## 1.1 顶层目录

| 目录/文件 | 用途 | 状态 |
|-----------|------|------|
| `backend/` | Python 后端 (引擎+Agent+评测+LLM+DB) | ✅ 完整 |
| `frontend/` | Next.js 14 前端 (观战+评测+进化 UI) | ✅ 完整 |
| `configs/` | YAML 配置文件 | ✅ 有内容 |
| `scripts/` | 53 个 Python 脚本 (批量/评测/修复/验证) | ⚠️ 碎片化 |
| `tests/` | 11 个测试文件 (pytest + Playwright) | ✅ 覆盖 Track A/B/C |
| `docs/` | 设计文档 + PRD + 方案 | ✅ 有内容 |
| `data/` | 对局数据 + 评测产物 + 策略库 | ✅ 289 个文件 |
| `skills/` | 团队协作规范 (8 个 md) | ✅ 完整 |
| `references/` | 克隆的参考仓库 (gitignored) | ✅ 10 个仓库 |
| `backups/` | 备份文件 | - |
| `.claude/` | Claude Code 工作树 | - |

---

## 1.2 Backend 核心模块

| module_path | module_purpose | key_files | current_status | risk_or_todo |
|-------------|---------------|-----------|----------------|-------------|
| `backend/engine/` | 游戏引擎 (对局流转/结算/可见性) | `game.py` (1400行), `phases.py`, `models.py`, `visibility.py`, `actions.py`, `rules.py`, `summary.py` | ✅ IMPLEMENTED | 模板角色 (Cupid/BigBadWolf等) 未接入引擎 |
| `backend/engine/roles/` | 角色注册表 | `registry.py`, `basic.py`, `gods.py`, `wolves.py`, `wolfcha.py`, `extensions.py` | ✅ IMPLEMENTED | 6个模板角色 playable=False |
| `backend/agents/` | Agent 系统 (LLM+启发式+人类) | `llm_agent.py` (2060行), `heuristic.py`, `human_agent.py`, `characters.py`, `profiles.py`, `prompts.py`, `playbooks.py`, `factory.py`, `humanization.py`, `optimization.py` | ✅ IMPLEMENTED | Strategy ID 未记录 |
| `backend/llm/` | LLM 客户端 | `deepseek.py` (统一客户端), `__init__.py` (provider路由), `env.py` (.env加载) | ✅ IMPLEMENTED | - |
| `backend/db/` | 数据库层 | `models.py` (21张表), `database.py`, `persist.py`, `persona_db.py` | ✅ IMPLEMENTED | - |
| `backend/eval/` | Track B+C 评测+进化 | `review.py` (4165行), `track_b.py` (1455行), `evolution.py` (2017行), `opportunity.py`, `scoring_models.py`, `report_graph.py`, `embedding_retrieval.py`, `v3_report.py` | ✅ IMPLEMENTED | `camp_won` bug, `mistake_penalty` 占位符 |
| `backend/protocols/` | 通信协议 | `rooms.py` (RoomManager), `schemas.py` | ✅ IMPLEMENTED | - |
| `backend/app.py` | FastAPI 入口 (30+路由+2WS) | (单文件) | ✅ IMPLEMENTED | - |
| `backend/run_demo.py` | 命令行 Demo | (单文件) | ✅ IMPLEMENTED | - |

---

## 1.3 关键代码位置速查

### 对局引擎
- **文件**: `backend/engine/game.py` — `WerewolfGame` 类 (~1400行)
- **阶段流转**: `backend/engine/phases.py` — `default_phase_handlers()` 返回 CompositePhase
- **状态定义**: `backend/engine/models.py` — `GameState`, `Player`, `Decision`, `GameEvent` 等
- **信息隔离**: `backend/engine/visibility.py` — `Visibility.for_player()` 构建 `PlayerView`

### Agent 逻辑
- **Agent 协议**: `backend/agents/base.py` — `Agent` Protocol
- **LLM Agent**: `backend/agents/llm_agent.py` — `LLMAgent` 类 (~2060行)
- **启发式 Agent**: `backend/agents/heuristic.py` — `HeuristicAgent` 类
- **人类 Agent**: `backend/agents/human_agent.py` — `HumanAgent` 类
- **Agent 工厂**: `backend/agents/factory.py` — `create_agents()`

### Prompt 模板
- **系统提示**: `backend/agents/prompts.py` — `ROLE_SYSTEM_PROMPTS` (7角色)
- **动作策略**: `backend/agents/prompts.py` — `ACTION_STRATEGIES` (action×role 嵌套字典)
- **输出格式**: `backend/agents/prompts.py` — `TALK_OUTPUT_INSTRUCTIONS`, `TARGET_OUTPUT_FORMAT`, `WITCH_OUTPUT_FORMAT`
- **角色配置**: `backend/agents/profiles.py` — `ROLE_PROFILES` (每个角色的 table_goal, speech_style)
- **策略简述**: `backend/agents/playbooks.py` — `ACTION_PLAYBOOKS` (每个角色的行动策略)

### Persona / MBTI 配置
- **Persona 数据**: `backend/agents/characters.py` — `PERSONA_POOL` (30+ 人物，含 MBTI/背景/性格)
- **PlayerMind 数据**: `backend/agents/characters.py` — `MIND_POOL` (8 个心智配置)
- **Persona 模板**: `backend/agents/profiles.py` — (无独立 Persona 模板，profiles 是 Role 配置)
- **DB 持久化**: `backend/db/persona_db.py` — `seed_personas()` 写入 `personas` 表
- **MBTI 描述**: `backend/agents/characters.py` — `build_system_prompt()` 内含 16 种 MBTI 描述

### Strategy 配置
- **策略库 (YAML)**: `configs/strategy_library.yaml` — 10 个分类, ~200 条中文策略条目
- **策略知识文档 (DB)**: `backend/eval/evolution.py` — `StrategyKnowledgeDoc`
- **角色策略卡 (DB)**: `backend/eval/evolution.py` — `RoleStrategyCard`
- **策略偏差注入**: `backend/agents/llm_agent.py` — `_build_strategy_bias_block()`
- **策略检索**: `backend/agents/llm_agent.py` — `retrieve_strategy_knowledge()`
- **⚠️ `strategy_id` 字段在整个项目中不存在** — 策略偏差通过 `strategy_bias` dict 传入，无 ID 追踪

### B 评分实现
- **Review 引擎**: `backend/eval/review.py` — `MetricsCalculator`, `ReviewReportBuilder`, `ReviewBonusDetector`, `CounterfactualAnalyzer`
- **Track B 发布**: `backend/eval/track_b.py` — `ReplayBundleBuilder`, `ValidationGate`, `ReviewRepairLoop`, `HTMLReviewRenderer`
- **机会提取**: `backend/eval/opportunity.py` — `OpportunityExtractor`
- **评分模型**: `backend/eval/scoring_models.py` — `OpportunityValueModel`, `DecisionQualityModel`
- **V3 报告**: `backend/eval/v3_report.py` — `compute_camp_advantage_curve`, `compute_drama_score` 等
- **检索**: `backend/eval/embedding_retrieval.py` — `BGEM3Provider`, `OpportunityIndex`

### HTML 报告生成
- **Track B HTML**: `backend/eval/track_b.py` — `HTMLReviewRenderer`
- **单局复盘**: `scripts/render_single_game_html.py` + `scripts/build_single_game_report_data.py`
- **Dashboard**: `scripts/render_dashboard_html.py` + `scripts/build_dashboard_data.py`
- **V7 交付物**: `scripts/generate_v7_deliverables.py`
- **MBTI 看板**: `scripts/fix_mbti_metrics_v2.py`

---

## 1.4 Frontend 模块

| module_path | module_purpose | key_files | current_status |
|-------------|---------------|-----------|----------------|
| `frontend/app/` | Next.js 14 App Router 页面 | `page.tsx` (/), `layout.tsx`, `globals.css` | ✅ IMPLEMENTED |
| `frontend/app/eval/dashboard/` | Track B 评测看板 | `page.tsx` | ✅ IMPLEMENTED |
| `frontend/app/evolution/` | Track C 进化看板 | `page.tsx` | ✅ IMPLEMENTED |
| `frontend/app/games/[id]/report/` | 单局复盘报告 | `page.tsx` | ✅ IMPLEMENTED |
| `frontend/app/room/[id]/play/` | 实时对局页 | `page.tsx` | ✅ IMPLEMENTED |
| `frontend/components/game/` | 游戏业务组件 (16个) | `ActionPanel`, `ChatBubble`, `DayBlock`, `EventTimeline`, `PlayerCard`, `VoteTargetGrid` 等 | ✅ IMPLEMENTED |
| `frontend/components/ui/` | 通用 UI 组件 | `Badge`, `Button`, `Card` | ✅ IMPLEMENTED |

### 前端→后端路由映射

| 前端页面 | 后端路由 |
|----------|----------|
| `/` (首页) | `GET /api/health`, `GET /api/rooms`, `POST /api/rooms` |
| `/room/[id]/play` | `POST /api/rooms/{id}/prepare`, `POST /api/rooms/{id}/start`, `POST /api/rooms/{id}/action`, `WS /ws/rooms/{id}` |
| `/games/[id]/report` | `GET /api/games/{id}`, `GET /api/games/{id}/reviews`, `GET /api/games/{id}/reviews/html`, `GET /api/games/{id}/metrics` |
| `/eval/dashboard` | `GET /api/metrics/aggregate`, `GET /api/leaderboard`, `GET /api/leaderboard/role_matrix`, `GET /api/eval/role-scores` |
| `/evolution` | `GET /api/evolution`, `GET /api/evolution/dashboard`, `GET /api/strategy/knowledge`, `GET /api/strategy/cards` |

---

## 1.5 Scripts 碎片化问题

`scripts/` 目录有 **53 个 Python 脚本**，其中:

- **可重用 (3个)**: `track_health.py`, `run_full_llm_pipeline.py`, `render_single_game_html.py`
- **一次性实验 (~40个)**: `v2_benchmark.py` 到 `v7_private_context.py` 的版本递增脚本
- **修复脚本 (~5个)**: `fix_mbti_winrate.py`, `fix_mbti_metrics_v2.py`, `rescore_with_weights.py` 等
- **数据生成 (~5个)**: `generate_v7_deliverables.py`, `build_v3_features.py`, `extract_opportunities.py` 等

**风险**: 脚本之间通过硬编码路径读取 `data/health/` 中的文件，缺乏明确的依赖声明。如果需要从头跑 B 评分 pipe，需要知道正确的调用顺序。

---

## 1.6 data/health/ 评测产物

289 个文件，核心分类:

| 类别 | 示例文件 | 用途 |
|------|---------|------|
| 评分 Gate | `scoring_validity_gate_v{1-7}.md/json` | 各版本 Gate 结果 |
| 机会数据 | `opportunities.jsonl`, `opportunities_v3_features.jsonl` | 决策机会 + 特征 |
| 玩家分数 | `player_scores_v{2-7}.jsonl` | 各版本玩家评分 |
| 基准测试 | `benchmark_dataset_v{5,6}.jsonl` | 标注数据集 |
| MBTI 分析 | `mbti_performance_dashboard_v7*.html`, `mbti_role_matrix_v7*.csv` | MBTI 看板 |
| HTML 报告 | `reports/review_game_*.html` (60+) | 单局复盘 |
| 审计报告 | `*_audit*.md`, `*_report*.md` | 各阶段审计 |
| 策略数据 | `doubao_strategies.json` | 豆包提取的策略 |

---

## 1.7 特别标注

### 对局引擎在哪里？
✅ `backend/engine/game.py` — `WerewolfGame` 类，~1400行完整实现

### Agent 逻辑在哪里？
✅ `backend/agents/llm_agent.py` (LLM), `backend/agents/heuristic.py` (启发式)

### Prompt 模板在哪里？
✅ `backend/agents/prompts.py` — 所有角色/动作的 Prompt 模板

### 角色配置在哪里？
✅ `backend/engine/roles/` (角色注册表) + `backend/agents/profiles.py` (角色行为配置)

### Persona / MBTI 配置在哪里？
✅ `backend/agents/characters.py` — 30+ 人物，含 MBTI + 背景经历

### Strategy 配置在哪里？
⚠️ `configs/strategy_library.yaml` (静态策略库) + `backend/eval/evolution.py` (DB策略知识)
⚠️ **`strategy_id` 字段不存在于项目中** — 策略偏差通过 `strategy_bias` dict 注入

### B 评分实现在哪里？
✅ `backend/eval/review.py` + `backend/eval/track_b.py` + `scripts/v[2-7]_*.py`

### HTML 报告生成在哪里？
✅ `scripts/render_single_game_html.py`, `scripts/render_dashboard_html.py`, `scripts/generate_v7_deliverables.py`
