# AI Werewolf 最终交付包说明

> 日期：2026-06-08
> 用途：说明 GitHub 仓库、文档、演示材料和验证命令如何共同展示 AI Werewolf 的完整系统能力。

## 1. 外部交付模式调研

调研对象包括 GitHub 官方 README 建议、字节青训营 / MarsCode 公开介绍，以及公开可访问的青训营项目展示材料。结论是：这类全栈/AI 实战项目通常不是只交一份代码，而是交一个能被快速理解、运行、验证和展示的项目包。

| 来源 | 可借鉴点 | 本项目对应做法 |
|---|---|---|
| GitHub README 官方说明 | README 应说明项目为什么有用、能做什么、如何开始使用、如何获取帮助、谁维护项目；仓库根目录 README 会被 GitHub 自动展示 | 根目录 `README.md` 放项目概览、快速开始、技术栈、关键页面、验证命令和文档索引 |
| 豆包 MarsCode X 字节青训营公开介绍 | 训练营覆盖前端、后端、AI，强调学习 AI、使用 AI、高效写码和完整实战场景 | 项目交付同时覆盖 FastAPI 后端、Next.js 前端、LLM Agent、复盘分析和策略回流 |
| 第六届字节青训营公开介绍 | 项目经历、团队协作、可直接运行的项目作品、实战技能是核心价值 | 仓库保留源码、配置模板、CI、启动命令、演示路线、验收报告和 PPT/PDF |
| 青训营项目汇报文档示例 | 常见结构包括技术栈、功能模块、项目关键点、项目预览、不足之处 | 本项目以 `PRODUCT_TECH_DOC.md`、`PROJECT_MODULE_DESIGN.md`、`PROJECT_FINAL_REPORT_DRAFT.md` 和 `PROJECT_EFFECT_ANALYSIS.md` 覆盖这些内容 |
| 青训营后端项目 GitHub 示例 | 公开项目常写项目介绍、成员/贡献、开发规约、技术选型、架构设计、部署、Demo 视频、总结反思和未来演进 | 本项目保留开发规范、架构设计、部署配置、验收报告、演示路线、限制边界和后续实验计划 |

参考链接：

- GitHub Docs: <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes>
- 火山引擎开发者社区：<https://developer.volcengine.com/articles/7419203646996348979>
- 第六届字节跳动青训营暑假专场：<https://www.1024code.com/youthcamp-bytedance>
- 青训营多人博客系统汇报文档示例：<https://juejin.cn/post/7002933726942330916>
- 青训营极简抖音后端项目示例：<https://github.com/guanjunyou/douyin-microservice>

## 2. 本项目最终交付物

| 交付物 | 文件/目录 | 作用 | 当前状态 |
|---|---|---|---|
| GitHub 首页 | `README.md` | 让访问者快速知道项目是什么、怎么启动、有哪些页面、去哪看详细文档 | 已具备 |
| 项目需求与范围 | `REQUIREMENTS.md`, `docs/prd.md` | 说明项目定位、核心需求、功能范围和交付边界 | 已具备 |
| 架构与差异化 | `docs/ARCHITECTURE_DESIGN_GUIDE.md` | 解释与常见方法不同在哪里、设计优势是什么、模块入口在哪里 | 已具备 |
| 核心模块设计 | `docs/PROJECT_MODULE_DESIGN.md` | 逐模块说明职责、输入输出、内部流程、验收方式和限制 | 已具备 |
| 端到端数据流 | `docs/DATA_FLOW.md` | 展示 GameEvent、AgentDecision、复盘、知识回流之间的证据链 | 已具备 |
| 产品技术文档 | `docs/PRODUCT_TECH_DOC.md` | 覆盖产品定位、技术栈、核心流程、部署配置和工程能力 | 已具备 |
| 项目报告草稿 | `docs/PROJECT_FINAL_REPORT_DRAFT.md` | 可作为最终报告正文基础，重点讲系统能力和架构设计 | 已具备 |
| 验收报告 | `docs/PROJECT_ACCEPTANCE_REPORT.md`, `docs/backend_acceptance_criteria.md` | 说明后端、前端、信息隔离、复盘、知识回流等模块的验证方式 | 已具备 |
| 实验与复盘材料 | `docs/EXPERIMENT_SECTION_DESIGN.md`, `docs/PROJECT_EFFECT_ANALYSIS.md`, `docs/TRACK_BC_PRESENTATION_METRICS.md` | 说明实验设计、现有证据、结论边界和后续可补实验 | 已具备 |
| 图表资产 | `docs/assets/final_report/*.svg` | 提供架构图、模块图、证据链图、运行流程图和占位实验图 | 已具备 |
| 演示材料 | `docs/presentations/AI_Werewolf_Project_Report.pptx`, `docs/presentations/AI_Werewolf_Project_Report.pdf`, `docs/presentations/AI_Werewolf_Project_Report_outline.md` | 可直接用于展示或答辩 | 已具备 |
| 前端说明 | `frontend/README.md` | 说明前端启动、页面结构、API 代理和运行方式 | 已具备 |
| 配置模板 | `.env.example`, `docker-compose.yml`, `Makefile` | 提供本地和 Docker 启动入口，不包含真实密钥 | 已具备 |
| 自动化验证 | `.github/workflows/ci.yml`, `tests/`, `tests/ui_smoke.mjs` | 提供 lint、pytest、前端 build 和 UI smoke 验证 | 已具备 |

## 3. 展示叙事主线

最终展示建议按以下顺序展开：

1. **项目定位**：AI Werewolf 是信息不对称下的多 Agent 对战系统，不是单 prompt 游戏 demo。
2. **架构主线**：规则引擎主控 -> 信息隔离 -> 角色化 Agent -> 决策审计 -> 复盘 -> 知识回流。
3. **与现有方法不同**：对比单 prompt、普通 AIWolf 回调 Agent、真人房间系统、只看胜负统计、硬编码角色逻辑。
4. **系统运行**：从大厅创建房间，到观战页看到发言、投票、夜晚行动和终局。
5. **真人混战**：展示 `/room/[id]/human` 如何让真人玩家和 AI 进入同一局。
6. **复盘报告**：展示 `/games/[id]/report` 中的关键行为、证据链和建议。
7. **知识回流**：说明 Track C 如何把复盘经验转为候选策略知识，再经检索进入后续对局。
8. **验证结果**：展示 pytest、ruff、Next.js build、UI smoke、visibility strict 和 strict run 的验证入口。

## 4. GitHub 仓库应保持的样子

GitHub 仓库中应该保留：

- 源码：`backend/`、`frontend/`、`scripts/`、`tests/`、`configs/`。
- 配置模板：`.env.example`、`docker-compose.yml`、`Makefile`、CI workflow。
- 正式文档：根目录 README/需求/变更日志，`docs/` 下的正式设计、数据流、产品技术、验收、报告和展示材料。
- 小型图表资产：SVG、HTML、PPT/PDF。

GitHub 仓库中不应保留：

- `.env`、API Key、真实账号、私有日志。
- `data/`、`logs/`、`references/`、`models/`、`.venv/`、`node_modules/`、`.next/`。
- 大体积模型文件、临时截图、实验输出 JSONL、数据库备份。
- 带旧评分规则口径、内部临时审计口径、未验证夸大结论的草稿。

## 5. 最终自检命令

提交前建议执行：

```bash
git status --short --branch
git grep -n -I -E '评分标准|评分权重|课程评价标准|Rubric|rubric|满分|奖金|评委|评审团|打分|SCORING_RUBRIC|展示指南|进化看板|策略进化面板|frontend/app/evolution' -- '*.md' '*.mdx' '*.html' '*.svg' || true
git grep -n -I -E 'wolf_secret_2026|sk-[A-Za-z0-9]|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|Bearer [A-Za-z0-9._-]{20,}|API_KEY=[^<[:space:]]|SECRET_KEY=[^<[:space:]]|PASSWORD=[^<[:space:]]' -- . ':!frontend/package-lock.json' || true
git ls-files | rg '(^|/)(\.env$|__pycache__|node_modules|\.next|data/|models/|references/|\.db$|\.sqlite$|\.log$|\.jsonl$|outputs/)' || true
ruff check backend/ scripts/ tests/ configs/
ruff format --check backend/ scripts/ tests/ configs/
python -m pytest tests/test_track_bc_leaderboard_experiment.py tests/test_api.py tests/test_llm_config.py -q
cd frontend && npm run lint && npm run build
node tests/ui_smoke.mjs
```

## 6. 当前结论

当前交付包已经能覆盖一个全栈/AI 实战项目通常需要的内容：项目说明、运行方式、前后端代码、架构设计、差异化说明、模块设计、数据流、验收报告、实验计划、演示图表、PPT/PDF 和自动化验证入口。

最终答辩或展示中应重点讲架构设计和证据链，不应复述外部评分规则，也不应把尚未平衡完成的实验写成已证明的显著提升结论。
