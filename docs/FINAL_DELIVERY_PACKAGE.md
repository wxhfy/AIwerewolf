# AI Werewolf 交付包说明

## 1. GitHub 交付内容

| 类型 | 文件/目录 | 作用 |
|---|---|---|
| 项目首页 | `README.md` | 项目定位、核心能力、快速开始、Demo 路线和仓库边界 |
| 架构说明 | `docs/ENGINEERING_ARCHITECTURE.md` | 分层架构、运行时序、信息隔离和数据闭环 |
| 展示概览 | `docs/FINAL_SHOWCASE_REPORT.md` | 粗略展示系统能力、模块和本地汇总口径 |
| 模块设计 | `docs/PROJECT_MODULE_DESIGN.md` | 核心模块职责、输入输出、内部流程和设计收益 |
| 需求文档 | `docs/prd.md` | 系统目标、功能范围和验收要求 |
| 前端代码 | `frontend/` | 大厅、观战、真人操作、复盘、看板和人格配置 |
| 后端代码 | `backend/` | FastAPI、WebSocket、规则引擎、Agent、评测和持久化 |
| 自动化验证 | `.github/workflows/ci.yml`, `tests/` | lint、pytest、前端构建和 smoke 测试入口 |

## 2. 不进入 GitHub 的内容

| 类型 | 处理方式 |
|---|---|
| 原始实验数据 | 保留在本地，例如 evidence、JSONL、CSV、数据库快照和运行日志 |
| 交付演示附件 | 单独提交，例如 PPT/PDF、截图、长篇答辩稿和过程报告 |
| 私有配置 | 保留在本地，例如 `.env`、API Key、真实数据库连接和本地参考仓库 |
| 构建产物 | 通过 `.gitignore` 排除，例如 `.next/`、`node_modules/`、缓存和临时输出 |

## 3. 推荐演示路线

1. 打开 `README.md`，说明项目定位和 Play -> Evaluate -> Evolve 主线。
2. 打开 `docs/ENGINEERING_ARCHITECTURE.md`，展示分层架构、运行时序、信息隔离和 Track C 生命周期。
3. 启动后端和前端，从大厅进入对局页，展示观战、阶段流转和事件流。
4. 打开单局复盘页和统计看板，展示 Track B 复盘和 leaderboard 能力。
5. 打开 `docs/PROJECT_MODULE_DESIGN.md`，说明规则引擎、Agent、Track B 和 Track C 的模块边界。

## 4. 运行入口

```bash
pip install -r requirements.txt
cp .env.example .env
make dev
```

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

默认入口：

| 服务 | 地址 |
|---|---|
| 后端 API | `http://localhost:8000/docs` |
| 前端 | `http://localhost:3001` |

## 5. 清洁度自检

提交前建议执行：

```bash
git status --short --ignored
git ls-files | rg '(^|/)(\.env$|__pycache__/|node_modules/|\.next/|data/|models/|outputs/|references/|docs/evidence/|docs/experiments/|docs/presentations/|docs/assets/(readme|closure|final_report)/|docs/wiki/)|\.(db|sqlite|log|jsonl|pptx|pdf|png|jpe?g)$'
```

若第二条命令输出数据、日志、PPT/PDF、evidence 或实验目录，说明仓库边界需要继续清理。
