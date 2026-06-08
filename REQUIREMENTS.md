# AI Werewolf 项目需求与设计目标

## 1. 项目定位

AI Werewolf 是一个多智能体狼人杀系统。项目目标不是做一个单 prompt 聊天 demo，而是构建一套可运行、可观战、可复盘、可迭代的 Agent Team 架构：

```text
规则引擎主控
  -> 信息隔离投影
  -> 角色化 Agent 决策
  -> 结构化事件与决策审计
  -> 赛后复盘与知识回流
  -> 下一局策略检索
```

系统中的每个 AI 玩家拥有独立角色、人格、可见信息、记忆和策略来源，需要在信息不对称条件下完成发言、投票和技能行动。系统同时支持真人玩家加入，与 AI 混合对局。

## 2. 核心需求

| 需求 | 目标 | 当前实现入口 |
|---|---|---|
| 完整对局引擎 | 能完成标准狼人杀流程，覆盖夜晚行动、白天发言、投票、死亡和胜负判定 | `backend/engine/game.py` |
| 严格信息隔离 | 每个 Agent 只能看到角色允许的信息，避免上帝视角 | `backend/engine/visibility.py` |
| 角色化 Agent | 不同角色有不同目标、技能、行动空间和策略倾向 | `backend/agents/cognitive/` |
| 工具调用决策 | Agent 可按需检索策略、回忆记忆、查询规则、分析票型并提交结构化行动 | `backend/agents/cognitive/agent_loop.py` |
| 决策证据链 | 保存事件、视图、原始输出、解析行动、工具 trace 和复盘结果 | `backend/db/`, `backend/eval/` |
| 策略知识回流 | 从赛后复盘中抽取经验，进入 candidate / active / deprecated 生命周期 | `backend/eval/knowledge_abstractor.py`, `backend/eval/evolution.py` |
| 前端体验 | 支持大厅、观战、真人操作、单局报告、复盘仪表盘和人格管理 | `frontend/app/` |
| 可验证工程 | 通过 pytest、ruff、Next.js build、UI smoke 和 strict run 检查主要链路 | `tests/`, `.github/workflows/ci.yml` |

## 3. 与常见方法的不同

| 常见方法 | 局限 | 本项目设计 |
|---|---|---|
| 单 prompt 模拟一整局 | 状态、规则和角色知识混在上下文里，容易泄露隐藏信息，也难以复盘 | 引擎保存真实状态，Agent 只拿 `PlayerView`，行动由引擎校验和结算 |
| 简单回调式 Agent | 生命周期清晰，但 Agent 内部记忆、社交判断和工具使用不够透明 | `CognitiveAgent` 拆出 Memory、BeliefTracker、SocialModel、Planner 和 AgentLoop |
| 普通狼人杀房间系统 | 适合真人局，但不关注 Agent 私有上下文、策略回流和决策审计 | 房间/WebSocket 只是外层，核心是可审计的多 Agent 对局与复盘链路 |
| 只统计胜负 | 胜负受角色、座位、队友和随机种子影响，无法解释关键行为 | Track B 把发言、投票、技能行动整理成可追溯步骤和关键复盘 |
| 硬编码角色逻辑 | 新增角色会牵动大量 if/else，Prompt 和规则容易不一致 | RoleRegistry、Phase、ActionValidator、Resolution 分层管理 |
| 把历史经验全塞进 prompt | 上下文噪声大，成本高，还可能污染当前局信息边界 | StrategyRetriever 按角色、阶段、人格和可见性过滤后按需注入 |

## 4. 架构优势

| 优势 | 说明 |
|---|---|
| 规则稳定 | `WerewolfGame` 是状态唯一写入者，LLM 输出不能直接修改真实状态 |
| 信息可信 | `GameState`、`PlayerView`、public snapshot 分离，隐藏身份和私有事件有明确边界 |
| 行为差异明显 | Persona 控制表达风格，Role 控制身份目标，Strategy 控制玩法经验 |
| 多 Agent 协作可观察 | 狼队视图、发言、票型、社交怀疑和工具 trace 可在赛后查看 |
| 新角色可扩展 | 角色元数据、技能、阶段和前端展示都有固定接入点 |
| 复盘可落地 | 单局报告能定位关键行为、证据和可替代行动，不只展示胜负 |
| 策略可迭代 | 复盘经验进入知识库，后续对局通过工具检索回流到 Agent 策略层 |
| 工程可交付 | 后端、前端、数据库、测试、CI、配置模板和文档均有明确入口 |

## 5. 功能范围

### 5.1 游戏与角色

- 支持 7-12 人局规则配置。
- 基础可玩角色包括 Villager、Werewolf、Seer、Witch、Hunter、Guard。
- WhiteWolfKing、Idiot 已进入部分配置；Cupid、BigBadWolf、WolfCub、WolfKing、Knight、Elder 作为模板角色保留扩展入口。
- 支持警徽、PK、遗言、猎人开枪、白狼王自爆等扩展阶段。

### 5.2 Agent

- AI 席位默认使用 LLM-compatible `CognitiveAgent`。
- 测试环境允许 `_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake`。
- 正式对局不允许静默 heuristic fallback。
- Agent 输出统一走 `Decision`，由引擎校验后执行。

### 5.3 前端

当前前端页面：

| 页面 | 路由 |
|---|---|
| 大厅 | `/` |
| 对局观战 | `/room/[id]/play` |
| 真人操作 | `/room/[id]/human` |
| 复盘仪表盘 | `/eval/dashboard` |
| 单局报告 | `/games/[id]/report` |
| 人格管理 | `/personas` |

Track C 的策略知识和回流能力通过后端 API、脚本和报告材料呈现，不作为独立前端页面承诺。

## 6. 运行与验证

本地启动：

```bash
pip install -r requirements.txt
cp .env.example .env
make dev
cd frontend && npm install && npm run dev
```

常用检查：

```bash
ruff check backend/ scripts/ tests/ configs/
ruff format --check backend/ scripts/ tests/ configs/
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake python -m pytest tests/ -q
cd frontend && npm run lint && npm run build
```

专项验证：

```bash
python scripts/verify_visibility_strict.py
python scripts/run_backend_full_strict.py
```

## 7. 交付边界

进入 GitHub 的内容应是完整、干净、可复现的项目代码与文档：

- 源码、测试、配置模板、CI workflow。
- README、PRD、架构设计、数据流、模块设计、产品技术文档、验收报告。
- 小型 SVG/HTML 图表和演示大纲。

不进入 GitHub 的内容：

- `.env`、API Key、真实账号、私有日志。
- `data/`、`logs/`、`references/`、`models/`、`.venv/`、`node_modules/`、`.next/`。
- 大体积模型文件、临时截图、实验输出 JSONL、数据库备份。
