# AI Werewolf 最终交付包说明

> 日期：2026-06-09
> 用途：说明 GitHub 仓库、文档、演示材料和验证命令如何共同展示 AI Werewolf 的完整系统能力。

## 1. 最终交付物

| 交付物 | 文件/目录 | 作用 |
|---|---|---|
| GitHub 首页 | `README.md` | 项目定位、分层架构、快速开始、Demo 路线、最新结果 |
| 最终展示报告 | `docs/FINAL_SHOWCASE_REPORT.md` | 精简成果报告，包含最新可引用数据和展示建议 |
| 文档导航 | `docs/README.md` | 正式文档阅读顺序、证据索引和归档说明 |
| 工程架构图谱 | `docs/ENGINEERING_ARCHITECTURE.md` | 分层架构图、运行时序图、信息隔离图、数据闭环图 |
| 核心模块设计 | `docs/PROJECT_MODULE_DESIGN.md` | 模块职责、输入输出、内部流程和设计收益 |
| 数据证据 | `docs/evidence/` | 真实 LLM、Track B、Track C、检索、策略使用结果 |
| 产品原型 | `frontend/` | 大厅、观战、真人操作、复盘、看板、人格配置 |
| 后端服务 | `backend/` | FastAPI、WebSocket、对局引擎、Agent、评测与持久化 |
| 自动化验证 | `.github/workflows/ci.yml`, `tests/` | lint、pytest、前端构建、UI smoke |
| 展示材料 | `docs/presentations/`, `docs/assets/` | PPT/PDF、小型 SVG/HTML 展示资产 |

## 2. 当前可展示结果

| 方向 | 当前结果 | 证据 |
|---|---:|---|
| 本地数据库 games | 11,730 | `docs/evidence/README.md` |
| 本地数据库 agent_decisions | 302,291 | `docs/evidence/README.md` |
| 本地数据库 published_reviews | 4,955 | `docs/evidence/README.md` |
| 本地数据库 strategy_knowledge_docs | 217,310 | `docs/evidence/README.md` |
| 真实 LLM 完成对局 | 78 | `docs/evidence/PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json` |
| 真实 LLM 决策 | 1,936 | `docs/evidence/PROJECT_REAL_LLM_FRAMEWORK_EVIDENCE.json` |
| strict formal completed games | 34 | `docs/evidence/PROJECT_METHOD_EFFECTIVENESS_FACTS.json` |
| strict formal fallback / invalid | 0 / 0 | `docs/evidence/PROJECT_METHOD_EFFECTIVENESS_FACTS.json` |
| Track B showcase 完成对局 | 6 | `docs/evidence/PROJECT_TRACK_B_LEADERBOARD_SHOWCASE.json` |
| 单角色检索 Coverage | 100.00% | `docs/evidence/PROJECT_ROLE_RETRIEVAL_FACTS.json` |
| 策略使用决策质量差异 | +0.0823 | `docs/evidence/PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json` |
| Target-seat Seer adjusted delta | +20.6680 | `docs/evidence/PROJECT_TARGET_SEAT_TRACKC_PILOT.json` |

## 3. 推荐展示路线

1. README 首屏：说明项目定位、Play -> Evaluate -> Evolve 主线和最新结果。
2. 架构图谱：展示分层架构图，强调规则引擎、信息隔离、Agent 决策和评测进化层的分离。
3. 前端 Demo：从大厅进入对局页，展示观战、阶段流转、事件流和真人操作入口。
4. Track B：展示单局复盘、leaderboard 和多维评分面板。
5. Track C：展示策略知识生命周期、单角色检索和 target-seat pilot。
6. Evidence：打开 `docs/evidence/README.md` 说明数据结果来自哪些文件。

## 4. GitHub 仓库边界

应保留：

- 源码：`backend/`、`frontend/`、`scripts/`、`tests/`、`configs/`。
- 配置模板：`.env.example`、`docker-compose.yml`、`Makefile`、CI workflow。
- 正式文档：README、需求、最终展示报告、架构图谱、模块设计、交付说明和 evidence。
- 展示资产：小型 SVG、HTML、PPT/PDF。

不应保留：

- `.env`、真实 API Key、本地数据库、私有日志。
- `data/`、`logs/`、`references/`、`models/`、`.venv/`、`node_modules/`、`.next/`。
- 大体积模型文件、临时截图、实验输出 JSONL、数据库备份。
- 过长过程日志、过期实验和内部诊断材料；这些材料不进入 GitHub 默认交付文档集。

## 5. 自检命令

```bash
git status --short --branch
git grep -n -I -E 'wolf_secret_2026|sk-[A-Za-z0-9]|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|Bearer [A-Za-z0-9._-]{20,}|API_KEY=[^<[:space:]]|SECRET_KEY=[^<[:space:]]|PASSWORD=[^<[:space:]]' -- . ':!frontend/package-lock.json' || true
git ls-files | rg '(^|/)(\.env$|__pycache__|node_modules|\.next|data/|models/|references/|\.db$|\.sqlite$|\.log$|\.jsonl$|outputs/)' || true
ruff check backend/ scripts/ tests/ configs/
ruff format --check backend/ scripts/ tests/ configs/
python -m pytest tests/test_api.py tests/test_llm_config.py -q
cd frontend && npm run lint && npm run build
```

## 6. 当前结论

当前交付包已经具备完整工程化 Demo 的形态：项目说明、运行方式、前后端代码、分层架构图、模块设计、真实 LLM 数据结果、复盘与策略回流证据、演示图表、PPT/PDF 和自动化验证入口。最终展示应突出架构设计、证据链和 Play -> Evaluate -> Evolve 闭环，不展开所有中间实验过程。
