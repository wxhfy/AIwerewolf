# 架构设计指南

> 日期：2026-06-08
> 目的：说明 AI Werewolf 的整体架构、与常见做法的差异、核心设计优势和可运行验证入口。

## 1. 架构主线

AI Werewolf 的核心不是“调用几个 LLM 轮流说话”，而是把狼人杀拆成一套可验证的多智能体系统：

```text
规则引擎主控
  -> 信息隔离投影
  -> 角色化 Agent 决策
  -> 结构化事件与决策审计
  -> 赛后复盘与知识回流
  -> 下一局策略检索
```

这条链路让系统同时具备四个能力：

- **能正确玩**：规则、阶段、技能、胜负由引擎统一裁决。
- **能公平玩**：每个 Agent 只能看到自己身份允许的信息。
- **能解释**：每一步发言、投票、技能行动都有事件、理由和证据链。
- **能积累**：赛后经验进入 runtime 策略池，并在后续对局中被检索使用；Track C Wiki/Hermes 提供长期知识编译和候选策略演进的增量设计。

## 2. 与常见方法的不同

| 常见方法 | 典型问题 | AI Werewolf 的设计 |
|---|---|---|
| 单 Prompt/单脚本模拟一局 | LLM 容易拿到上帝视角，规则和状态混在 prompt 里，难以复盘 | 规则由 `WerewolfGame` 控制，Agent 只提交意图；真实状态和玩家视图严格分离 |
| AIWolf 风格回调 Agent | 生命周期清晰，但 Agent 内部思考通常是黑箱，产品观战和赛后分析能力弱 | 保留 Agent 生命周期思想，同时加入 Memory、SocialModel、Planner、Tool Loop 和决策审计 |
| 普通狼人杀房间系统 | 实时交互成熟，但主要服务真人局，缺少 Agent 策略、私有上下文和知识回流 | 房间/WebSocket 只是外层，核心是可审计的 Agent Team 和信息不对称建模 |
| 只看胜负统计 | 胜负受随机身份、座位和队友影响大，无法知道哪一步打得好或坏 | 每个关键行为进入赛后复盘，报告高光、失误、证据和可替代行动 |
| 硬编码角色逻辑 | MVP 容易，但新增角色会牵动大量 if/else | 角色元数据、阶段、行动校验、技能结算分层，新增角色优先走 registry/config |
| 把全部历史塞进上下文 | 成本高、噪声大，还可能污染当前局信息边界 | Agent 只通过工具按需检索经过 confidence / visibility / privacy / applicability 过滤的 active 策略；Wiki/Hermes 作为离线知识组织与候选策略设计层 |

## 3. 核心架构分层

### 3.1 规则层：引擎主控

入口：`backend/engine/`

`WerewolfGame` 是状态唯一写入者。Agent 不能直接修改 `GameState`，只能提交 `Decision`。引擎负责：

- 阶段推进：夜晚行动、白天发言、投票、特殊阶段、终局。
- 行动校验：角色、存活状态、目标合法性、技能次数。
- 行动结算：守卫、狼人、女巫、预言家、猎人、白狼王等。
- 胜负判定：狼人阵营和好人阵营的终局条件。
- 事件记录：每次行动生成结构化 `GameEvent`。

设计优势：规则正确性收敛到一个地方，LLM 输出再不稳定也不能破坏游戏状态。

### 3.2 信息隔离层：Truth State -> PlayerView

入口：`backend/engine/visibility.py`

系统同时维护三类视图：

- `GameState`：完整真相，只供引擎、持久化和终局复盘使用。
- `PlayerView`：给某个玩家/Agent 的局部视角。
- Public snapshot：给观众和前端的公开视角。

关键边界：

- 村民看不到隐藏身份。
- 狼人只看到狼队队友和合法狼队信息。
- 预言家只看到自己的查验结果。
- 女巫只看到自己被通知的受害者和用药状态。
- 公开视图不暴露夜间子阶段细节和未公开能力状态。

设计优势：狼人杀的核心是信息不对称；把信息过滤做成中心化投影，比在每个调用点临时裁剪更可靠。

### 3.3 Agent 层：人格、身份、策略三层认知

入口：`backend/agents/cognitive/`

Agent 决策链路：

```text
PlayerView
  -> Observation
  -> Memory / BeliefTracker / SocialModel / Planner
  -> AgentLoop tools
  -> Decision
```

三层认知结构：

| 层 | 作用 | 例子 |
|---|---|---|
| Persona / MBTI | 控制表达风格、风险偏好、合作倾向 | 激进狼人、谨慎村民、强势预言家 |
| Role Identity | 定义身份目标、技能边界和反模式 | 预言家查验、女巫用药、猎人开枪 |
| Strategy Knowledge | 动态加载历史经验和当前阶段策略 | 警徽流、归票、倒钩、表水、抗推 |

设计优势：角色差异不是换一段台词，而是身份目标、可见信息、技能动作、社交策略和记忆状态都不同。

### 3.4 工具调用层：按需检索而不是塞满上下文

入口：`backend/agents/cognitive/agent_loop.py`

Agent 可调用的工具包括：

- `search_strategies`
- `recall_memory`
- `check_rules`
- `get_social_info`
- `analyze_votes`
- `set_strategic_intent`
- `submit_decision`

设计优势：上下文更短、更聚焦；策略知识可以独立迭代；工具 trace 也能进入赛后审计。

### 3.5 Track B/C 层：从对局日志到可验证策略进化

入口：`backend/eval/`

对局结束后，系统把 `GameEvent`、`AgentDecision`、快照和角色结果组织成复盘数据，再进入 Track C 的 runtime 策略池。新增的 Wiki/Hermes 设计作为离线知识编译和候选策略演进层，不绕过现有生命周期门控。

```text
GameEvent / AgentDecision / Snapshot
  -> DecisionScore / ScoredStep
  -> PublishedReview
  -> StrategyKnowledgeDoc(candidate/active/deprecated)
  -> StrategyRetriever / Agent Prompt Layer 3

Optional offline layer:
  -> Track C Wiki (Markdown strategy pages)
  -> Hermes DreamJob / StrategyPatch / A/B tournament
  -> candidate StrategyKnowledgeDoc
```

设计优势：系统不仅能展示“谁赢了”，还能解释“关键转折在哪一步、当时可见信息是什么、下一局可以学到什么”。PostgreSQL 策略池负责对局时低延迟、安全过滤和归因；Wiki/Hermes 层负责长期知识组织、人工审核和候选 patch 设计。

详细设计见 [`TRACK_C_HERMES_LLM_WIKI_DESIGN.md`](TRACK_C_HERMES_LLM_WIKI_DESIGN.md)。

### 3.6 产品层：同一套引擎服务 AI、真人和观战

入口：`backend/app.py`, `backend/protocols/rooms.py`, `frontend/`

前端和后端通过 REST + WebSocket 对接：

- `/`：创建房间、设置 AI/Human 模式。
- `/room/[id]/play`：观战主界面，展示阶段、玩家、发言、投票和事件流。
- `/room/[id]/human`：真人玩家操作界面。
- `/games/[id]/report`：单局复盘报告。
- `/eval/dashboard`：多局统计和排行榜。
- Track C 后端/API/脚本/wiki：策略知识、实验结果、Wiki 入口和知识回流路径。
- `/personas`：人格配置入口。

设计优势：真人玩家、AI 玩家、观众和赛后报告共用同一套状态流，不需要分别维护几套逻辑。

## 4. 设计优势总结

| 优势 | 来自哪个设计 | 体现 |
|---|---|---|
| 规则稳定 | 引擎主控，Agent 只输出意图 | LLM 不能直接改状态，非法行动会被校验 |
| 信息可信 | `GameState` / `PlayerView` 分离 | Agent 输入天然不含越权信息 |
| 角色可扩展 | RoleRegistry + Phase/Action/Skill 分层 | 新角色不需要把规则写进 Prompt |
| 决策可解释 | GameEvent + AgentDecision + Review | 可回放每一步、查看理由和证据 |
| 策略可迭代 | StrategyKnowledgeDoc + Retriever + Track C Wiki/Hermes 增量层 | 赛后经验能沉淀、审核并进入下一局策略层 |
| 交互完整 | Room + WebSocket + HumanAgent | AI 对局、真人混战、观战和复盘共用同一架构 |
| 工程可验证 | pytest + E2E + UI smoke + visibility strict | 不依赖人工目测判断系统是否跑通 |

## 5. 模块证据索引

| 模块 | 入口 | 说明 |
|---|---|---|
| 游戏引擎 | `backend/engine/game.py` | 初始化、阶段推进、结算、胜负判定 |
| 阶段管理 | `backend/engine/phase_manager.py` | 夜晚、白天、特殊阶段组合调度 |
| 行动校验 | `backend/engine/actions.py` | 角色、存活、目标合法性 |
| 角色注册 | `backend/engine/roles/registry.py` | `RoleSpec`、可玩角色、模板角色 |
| 信息隔离 | `backend/engine/visibility.py` | 真实状态到玩家视图的裁剪 |
| Agent 主体 | `backend/agents/cognitive/agent.py` | Observe -> Think -> Act -> Reflect |
| Agent Loop | `backend/agents/cognitive/agent_loop.py` | 工具调用、策略检索、最终决策 |
| 记忆系统 | `backend/agents/cognitive/memory.py` | 多轮记忆、近期发言、角色状态 |
| 社交判断 | `backend/agents/cognitive/social_model.py` | 信任、怀疑、声称和矛盾信号 |
| 狼队协作 | `backend/agents/cognitive/wolf_team.py` | 狼人专属安全视图 |
| 真人玩家 | `backend/agents/human_agent.py` | HumanAgent 生命周期契约 |
| 后端服务 | `backend/app.py` | REST、WebSocket、房间、报告和看板接口 |
| 房间管理 | `backend/protocols/rooms.py` | 房间状态、active game、snapshot buffer |
| 持久化 | `backend/db/` | games、events、decisions、reviews、knowledge |
| 复盘系统 | `backend/eval/` | 赛后分析、报告生成、知识抽取 |
| 对局 UI | `frontend/app/room/[id]/play/page.tsx` | 观战主界面 |
| Human UI | `frontend/app/room/[id]/human/page.tsx` | 真人操作界面 |
| 复盘 UI | `frontend/app/games/[id]/report/page.tsx` | 单局报告页 |

## 6. 推荐演示路线

1. 首页 `/`：创建房间，展示 AI/Human 模式、玩家数量、模型配置和房间入口。
2. 对局页 `/room/[id]/play`：展示昼夜流转、角色状态、发言、投票、技能行动和事件流。
3. 真人页 `/room/[id]/human`：展示真人席位如何查看身份、选择目标、提交行动。
4. 复盘页 `/games/[id]/report`：展示对局结束后的关键决策、证据链和改进建议。
5. 统计页 `/eval/dashboard`：展示多局结果、排行榜和对比数据。
6. Track C wiki / 报告 / 脚本：展示策略知识、实验结果、候选 patch 设计和知识回流路径。
7. 人格页 `/personas`：展示不同 MBTI 人格与角色行为差异。

## 7. 可运行验证命令

离线基础检查：

```bash
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake \
python -m pytest tests/test_api.py tests/test_llm_config.py -q
```

信息隔离专项：

```bash
python scripts/verify_visibility_strict.py
```

后端 E2E：

```bash
python scripts/e2e_smoke.py
```

前端检查：

```bash
cd frontend
npm run lint
npm run build
node ../tests/ui_smoke.mjs
```

真实 LLM + PostgreSQL 严格验收：

```bash
python scripts/run_backend_full_strict.py
```

## 8. GitHub 仓库交付边界

建议进入 GitHub 的内容：

- 源码、测试、配置模板、CI workflow。
- README、PRD、数据流、模块设计、产品技术文档、验收报告、架构设计指南。
- 最终报告使用的 SVG 图表和演示大纲。
- 若课程或展示需要，PPT/PDF 可作为正式展示材料保留。

保持 local-only 或 ignored 的内容：

- `.env`、API Key、私有账号、真实密钥。
- `data/`、`logs/`、`references/`、`models/`、`.venv/`、`node_modules/`、`.next/`。
- 大体积模型文件、临时运行日志、临时截图和 PNG 导出。

当前 `.gitignore` 已覆盖高风险目录，文档引用应优先指向可复现命令、正式报告和源码入口。
