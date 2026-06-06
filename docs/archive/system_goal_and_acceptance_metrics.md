# AI Werewolf 系统目标、满分验收指标与改进报告

> 生成时间：2026-06-02  
> 评估口径：基于当前仓库真实代码、测试、配置和本轮可运行验证；以满分档为目标，MVP 与及格线只作为中间状态。

## 1. 项目最终目标

当前项目主线应定义为：

> AI Werewolf 是一个 AI 狼人杀多智能体系统，不只要能自主完成一局狼人杀，还要能复盘关键决策，通过反事实评估定位 bad case，并把经过可信度、权限和适用条件过滤的策略知识回流到下一代 Agent。

这条主线在当前仓库中**部分成立**：

| 能力 | 当前判断 | 证据 | 缺口 |
|---|---|---|---|
| 自主完成一局 | 代码已实现 / 测试已覆盖 | `backend/engine/game.py::WerewolfGame`、`backend.run_demo`、`tests/test_engine.py` | 缺 50 局标准配置完成率报告 |
| 多角色 Agent | 代码已实现 / 测试已覆盖 | `backend/engine/models.py::Role`、`backend/engine/rules.py::WOLFCHA_ROLE_CONFIGS`、`backend/agents/playbooks.py`、`tests/test_role_registry.py` | 角色行为差异缺批量量化 |
| 信息隔离 | 代码已实现 / 测试已覆盖 | `backend/engine/visibility.py::Visibility.for_player`、`tests/test_visibility_final_agent_input.py` | Memory/Retrieval/Prompt 全链路正式报告不足 |
| 复盘与反事实 | 代码已实现 / 测试已覆盖 | `backend/eval/review.py::ReviewReportBuilder`、`CounterfactualAnalyzer`、`tests/test_b_full_acceptance.py` | Track B artifact 与报告文件仍不完整 |
| 轻量自进化 | 设计中已有 / 代码已实现 / 部分测试覆盖 | `backend/eval/evolution.py::EvolutionPipeline`、`TournamentRunner`、`StrategyKnowledgeDoc` | 缺正式 LLM-only 20 局 A/B 提升证据 |

## 2. 目标与基础要求对齐

| 模块 | MVP 线 | 及格线 | 满分线 | 当前状态 | 证据路径 | 风险 |
|---|---|---|---|---|---|---|
| 角色 Agent | 5 种核心角色可行动 | 角色 prompt / 行动逻辑有差异 | 角色策略、trace、bad case、行为分布可量化 | 已完成 | `backend/agents/prompts.py`、`profiles.py`、`playbooks.py` | 满分量化不足 |
| 对局引擎 | 完整跑完 1 局 | 核心边界有测试 | 50 局完成率 ≥95%，规则边界 ≥95% | 部分完成 | `backend/engine/game.py`、`actions.py`、`rules.py` | 全量测试仍失败 |
| 信息隔离 | 不给 Agent 完整 GameState | PlayerView 无明显泄露 | final_agent_input / Memory / Retrieval / Prompt 泄露数 0 | 部分完成 | `backend/engine/visibility.py`、`tests/test_visibility_final_agent_input.py` | RAG/Memory 全链路仍需报告 |
| 可观测性 | 有事件日志 | 决策输入/输出可查 | ≥95% 决策有完整 DecisionTrace | 部分完成 | `DecisionAudit`、`DecisionTrace`、`ReviewReport` | trace 字段覆盖率未统计 |
| 前端 UI | 可观战 | 可看阶段、玩家、事件 | Replay Viewer 含 bad case、反事实、视角切换 | 部分完成 | `frontend/app/*`、`components/game/*` | Playwright smoke 未稳定通过 |
| 评测复盘 | 有报告对象 | B 规格测试通过 | Golden Cases + Leaderboard + 发布报告可复现 | 部分完成 | `backend/eval/review.py`、`tests/test_b_full_acceptance.py` | artifact / docs 缺失 |
| 轻量自进化 | 有策略知识库 | C 规格测试通过 | 20 局 A/B 显著提升、可回滚 | 部分完成 | `backend/eval/evolution.py`、`tests/test_c_acceptance_verification.py` | LLM-only A/B 缺失 |

## 3. MVP / 及格 / 满分三层验收标准

| 优先级 | 指标 | MVP 标准 | 及格标准 | 满分标准 | 当前状态 |
|---|---|---|---|---|---|
| P0 | game_completion_rate | 单局可到 `GAME_END` | 10 局无崩溃 | 50 局完成率 ≥95% | 部分完成 |
| P0 | role_strategy_coverage | 5 核心角色可行动 | 5 核心角色 prompt/playbook 差异化 | 5 角色均有 StrategyCard、trace、bad case 和量化行为差异 | 部分完成 |
| P0 | information_isolation | PlayerView 不含隐藏身份 | 自动化测试覆盖玩家视角 | PlayerView、Memory、Retrieval、Prompt、final_agent_input 泄露数 0 | 部分完成 |
| P0 | secret_hygiene | 不提交 API key | 扫描无 provider key | CI 阻断密钥、外部 key 已轮换 | 部分完成 |
| P1 | decision_trace_coverage | 保存事件和决策 | 保存 raw output、action、model、latency | ≥95% 决策含 visible_facts、candidate_actions、confidence、prompt_hash、cost | 部分完成 |
| P1 | review_report_generation | 能生成复盘对象 | B 规格测试通过 | 报告 artifact 可复现，Golden Cases TPR ≥80% / FPR ≤20% | 部分完成 |
| P1 | counterfactual_coverage | 有少量反事实 | 覆盖 vote / skill / info release | 覆盖投票、技能、发言策略、身份暴露等关键类型并有证据链 | 部分完成 |
| P1 | evolution_ab | 有策略知识回流 | C 规格测试通过 | 20 局 A/B 有显著、可解释提升，支持回滚 | 部分完成 |
| P2 | frontend_replay | 有观战界面 | build 通过，主要页面存在 | 浏览器 smoke + 截图证明 Replay Viewer 可解释 | 部分完成 |
| P2 | docs_runability | README 可启动 | 关键命令可运行 | clean machine runbook + artifact + demo 视频/截图 | 部分完成 |

## 4. MVP Checklist 完成度

| Checklist | 当前状态 | 证据路径 | 是否有测试 | 风险 | 下一步 |
|---|---|---|---|---|---|
| 至少 5 种角色 | 已完成 | `backend/engine/models.py::Role`、`backend/engine/rules.py` | `tests/test_role_registry.py` | 扩展角色不可直接启用 | 继续保持 `playable` 校验 |
| 完整对局流程 | 已完成 | `backend/engine/game.py`、`backend.run_demo` | `tests/test_engine.py` | 缺 50 局统计 | 加 batch runner 报告 |
| 信息隔离有效 | 已完成 | `backend/engine/visibility.py` | `tests/test_visibility_final_agent_input.py` | RAG/Memory 全链路报告不足 | 补 retrieval/memory 泄露报告 |
| 对局日志完整 | 部分完成 | `GameEvent`、`DecisionAudit`、`ReviewReport` | B/C 测试间接覆盖 | DecisionTrace 满分字段未量化 | 统一 trace schema |
| 前端界面 | 部分完成 | `frontend/app/room/[id]/play`、`eval/dashboard`、`games/[id]/report` | `npm run build --prefix frontend` | Playwright smoke 失败 | 修前端 smoke |
| 进阶课题 | 部分完成 | `backend/eval/review.py`、`backend/eval/evolution.py` | B/C 规格测试 34 项通过 | artifact / LLM-only A/B 缺失 | 优先修 Track B artifact |

## 5. 当前架构总览

| 模块 | 解决的问题 | 为什么需要它 | 当前实现状态 | 证据路径 | 主要风险 |
|---|---|---|---|---|---|
| GameState / GameEvent | 保存对局状态与事件 | 复盘、前端、胜负判定都依赖同一事实源 | 代码已实现 | `backend/engine/models.py` | 事件到报告的覆盖率需统计 |
| Phase 状态机 | 控制夜晚/白天/特殊阶段 | 狼人杀阶段多，必须显式流转 | 代码已实现 | `backend/engine/game.py` | 批量边界报告不足 |
| Role Registry | 角色定义与可玩性 | 防止配置散落和未启用角色误入局 | 代码已实现 | `backend/engine/roles/*` | 模板角色不可直接启用 |
| ActionValidator | 校验动作合法性 | 防止 Agent 非法目标/非法技能打断对局 | 代码已实现 | `backend/engine/actions.py` | 非法动作恢复率未统计 |
| Agent 接口 | 统一 talk/vote/attack/divine/guard 等生命周期 | 便于 LLM、heuristic、human 互换 | 代码已实现 | `backend/agents/base.py` | 部分扩展技能仍需统一 |
| CognitiveAgent | 组合观察、信念、策略 | 提升单 Agent 推理结构化程度 | 代码已实现 | `backend/agents/cognitive/agent.py` | 真实 LLM 对局证据不足 |
| RoleStrategy / StrategyMemory | 区分角色目标与历史经验 | 避免所有角色共用一个 prompt | 代码已实现 | `backend/agents/cognitive/strategies/base.py` | 行为差异量化不足 |
| BeliefTracker | 维护信念而非真相 | 信息不对称游戏不能把 truth 当 belief | 代码已实现 | `backend/agents/cognitive/observe.py`、`belief_state.py` | belief_delta 覆盖率未量化 |
| PlayerView / Visibility | 信息隔离 | 防止村民偷看狼队、狼人偷看查验 | 测试已覆盖 | `backend/engine/visibility.py` | Retrieval/Memory 链路需补测 |
| WolfTeamView | 狼队协作 | 狼人需要合法共享队友与刀人信息 | 代码已实现 | `backend/agents/cognitive/wolf_team.py` | 战术效果缺量化 |
| DecisionAudit / DecisionTrace | 决策可追溯 | 复盘不能只看 LLM 原文 | 部分实现 | `backend/engine/models.py`、`backend/eval/types.py` | 满分字段缺覆盖率 |
| ReviewReport | 多维评测复盘 | 不能只用胜负评价决策 | 测试已覆盖 | `backend/eval/review.py` | 发布报告 artifact 缺失 |
| CounterfactualAnalyzer | 反事实推演 | 好结果中也可能有坏决策 | 测试已覆盖 | `CounterfactualAnalyzer` | 全量 artifact 仍阻塞 |
| LLM Judge / Golden Cases | 校准评测质量 | 自动复盘也可能误判 | 部分实现 | `tests/test_b_full_acceptance.py` | 数据/模型 artifact 不完整 |
| StrategyKnowledgeDoc / Retrieval | 策略知识回流 | 复盘结论要能被下一局利用 | 代码已实现 | `backend/eval/evolution.py`、`backend/db/persist.py` | 可信度/权限未完全持久化 |
| L0-L4 知识可信度 | 防止错误复盘污染 | 不是所有复盘都可信 | 设计/代码已有 | `backend/eval/knowledge_confidence.py` | runtime 链路未完全证明 |
| Leaderboard | 比较模型/版本 | 进阶评测需要横向对比 | 代码已实现 | `backend/eval/types.py`、`backend/db/models.py` | 缺发布样例报告 |
| 数据库模型 | 持久化对局与评测 | 支持回放、审计、版本回滚 | 代码已实现 | `backend/db/models.py` | schema 与新 trace/tier 需评审 |
| 前端 UI / Replay Viewer | 让评委看懂对局 | 非技术展示需要可视化 | 部分实现 | `frontend/app/*` | smoke 和截图证据不足 |

## 6. 核心设计方案与设计理由

**PlayerView / Visibility**：狼人杀的核心难点是信息不对称，不能把完整 `GameState` 传给 Agent。`Visibility.for_player()` 用 `PlayerView` 裁剪玩家列表、已知狼队、私有事件和公开事件，避免村民看到狼队名单，也避免狼人看到预言家查验结果。满分还需要证明 Memory、Retrieval、Prompt、final_agent_input 四层都没有 hidden truth。

**BeliefTracker**：Agent 应维护“相信谁像什么身份”，而不是真实身份。实现上 `BeliefState` / `BeliefTracker` 区分公开声称、历史行为、矛盾和投票模式，为后续归票、站队、反欺骗提供基础。

**RoleStrategyCard**：人格层控制“怎么说”，策略层控制“做什么”。`RoleStrategyCard` 与 `playbooks.py` 把狼人伪装、预言家报验、女巫用药、猎人开枪、平民站边拆开，避免单 prompt 扁平化。

**DecisionTrace / DecisionAudit**：只存原始 LLM 输出无法复盘“看到什么、可选什么、为何这么选”。当前 `DecisionAudit` 已记录 observation、raw_output、parsed_action、model/token/latency；满分还要补 candidate_actions、confidence、prompt_hash、cost 覆盖率。

**CounterfactualAnalyzer**：只看胜负会误判，例如好人赢了但女巫毒错人仍是坏决策。`CounterfactualAnalyzer` 生成 vote、skill、info_release 等反事实，用替代行动解释局势差异。

**L0-L4 知识可信度**：复盘结论可能错误，直接进入知识库会污染下一局。`knowledge_confidence.py` 已有 tier/access/applicability 设计，但持久化和运行时检索链路还需要统一。

## 7. 相比普通方案的优势

| 普通方案 | 普通方案怎么做 | 当前项目怎么做 | 当前项目优势 | 代价 / 复杂度 | 是否值得保留 |
|---|---|---|---|---|---|
| 普通规则狼人杀游戏 | 只实现规则、房间和胜负 | `backend/engine` 之外还有 `backend/eval`、`DecisionAudit`、`CounterfactualAnalyzer` | 能解释 Agent 为什么赢/输，而不是只给终局 | 评测链路和 artifact 管理更复杂 | 值得 |
| 所有角色共用一个 Prompt | 一套通用 prompt 填入角色名 | `backend/agents/prompts.py`、`profiles.py`、`playbooks.py`、`RoleStrategyCard` 分层 | 狼人伪装、预言家报验、女巫用药等策略可区分 | 维护多个角色模板和测试 | 值得 |
| 只统计胜负的 Agent 对战 | win/loss 作为主要指标 | `ReviewReportBuilder` 输出发言、投票、技能、bad case、反事实 | 能发现“赢了但做错”的关键决策 | 需要 Golden Cases 和校准 | 值得 |
| 无信息隔离测试的多 Agent | 直接传全局状态或只做 UI 隐藏 | `Visibility.for_player` + `tests/test_visibility_final_agent_input.py` | 防止 hidden truth 进入 Agent 输入 | 需要维护 PlayerView / final input 测试 | 必须保留 |
| 无知识可信度控制的自进化 | 复盘结论直接入库并注入下一局 | `knowledge_confidence.py` 设计 L0-L4、access、applicability | 降低错误复盘污染下一代策略的风险 | DB / retrieval runtime 链路需继续闭环 | 值得，但需补 P1-4 |
| 无前端或黑盒日志方案 | 只能看 CLI 输出或原始 JSON | `frontend/app/room/[id]/play`、`eval/dashboard`、`games/[id]/report` | 非技术评委能看阶段、玩家、事件和报告 | 需要 Playwright smoke 和截图证据 | 值得 |

## 8. 进阶课题方向判断

| 方向 | 满分验收标准覆盖度 | 当前匹配度 | 已有证据 | 缺口 | 风险 | 是否建议主打 |
|---|---|---|---|---|---|---|
| A. 通用 Agent | 部分完成 | 低 | 开发过程可审核，但产品没有代码自修改闭环 | 缺 sandbox、回滚、自动改代码目标 | 高 | 不建议 |
| B. 评测 + 复盘 | 部分完成 | 高 | `ReviewReport`、`CounterfactualAnalyzer`、Leaderboard、B 规格测试 | Track B artifact / 发布报告缺失 | 中 | 建议主打 |
| C. 自进化 Agent | 部分完成 | 中 | `StrategyKnowledgeDoc`、`TournamentRunner`、C 规格测试 | LLM-only A/B 与显著胜率提升缺失 | 中高 | 作为轻量自进化加分 |

结论：展示材料应主打 **B. 评测 + 复盘**，把 C 称为“评测驱动的轻量策略知识迭代”，不要声称 A 或 C 已满分。

**评判亮点满分验收表**

| 亮点 | 满分验收标准 | 当前状态 | 证据路径 | 加分潜力 | 缺口 | 大改待办 | 优先级 |
|---|---|---|---|---|---|---|---|
| 策略深度 | 每个角色有明确博弈策略，狼人能伪装，好人能站队/交叉验证 | 部分完成 | `backend/agents/playbooks.py`、`backend/agents/cognitive/strategies/*` | 高 | 角色行为差异和样例对局量化不足 | P2-1、P1-6 | P2 |
| 工程完整度超预期 | fallback、并发、监控、成本、延迟、异常恢复可记录 | 部分完成 | `WerewolfGame._batch_ask`、`DecisionAudit`、`backend/eval/types.py` | 中 | cost、candidate_actions、trace 覆盖率不足 | P1-5 | P1 |
| 前端体验 | Replay Viewer 能让非技术人员看懂对局和关键决策 | 部分完成 | `frontend/app/*`、`components/game/*` | 中 | Playwright smoke 与截图 artifact 缺失 | P1-3、P2-2 | P1 |
| 可扩展架构 | 新增角色或规则变体改动小，有 registry / rule variant | 部分完成 | `backend/engine/roles/*`、`configs/rule_variant_standard.yaml` | 中 | 规则配置未绑定 CI，模板角色不能直接启用 | P2-4、P3-2 | P2 |
| 人机交互 | 真人可加入，与 Agent 混合博弈，权限正确 | 部分完成 | `backend/agents/human_agent.py`、`frontend/app/room/[id]/play` | 中 | 浏览器级人机流程截图不足 | P1-3 | P2 |
| 进阶独创性 | 反事实、知识可信度、A/B、Leaderboard 可验证 | 部分完成 | `backend/eval/review.py`、`backend/eval/evolution.py`、`backend/db/models.py` | 高 | LLM-only A/B 和发布报告缺失 | P0-2、P1-1、P1-6 | P0/P1 |

## 9. 评分标准满分对齐分析

| 评分维度 | 权重 | 满分标准摘要 | 当前预估得分 | 证据 | 主要扣分点 |
|---|---:|---|---:|---|---|
| 单 Agent 能力 | 20 | 角色策略差异显著、决策可追溯、有量化评估、能分析 bad case | 15 | prompt/profile/playbook、BeliefState、DecisionAudit、B 测试 | 决策 trace 满分字段和 LLM-only 质量证据不足 |
| 多 Agent 协作与系统设计 | 20 | 上下文清晰、信息隔离、技能抽象、主动博弈与协作 | 16 | Visibility、ActionValidator、WolfTeamView、RoleRegistry | 好人协作/欺骗检测量化不足，RAG/Memory 泄露报告不足 |
| 工程实现与系统完整度 | 30 | 全流程稳定、边界完善、信息隔离测试无泄露、前端好用、文档齐全 | 20 | demo、targeted pytest、frontend build、DB/API | 全量测试失败，Playwright smoke 不稳定，50 局报告缺失 |
| 进阶课题完成度 | 30 | 选定方向达到完整闭环，推荐评测+复盘 | 20 | B/C 规格测试 34 passed、Review/Evolution 模块 | Track B artifact/报告缺失，Golden Cases 和 LLM A/B 不完整 |
| 总分 | 100 | 满分导向综合评分 | 71 | 当前仓库 + 本轮验证 | 不能按 MVP 通过虚高评分 |

**9.1 单 Agent 能力子项矩阵**

| 子项 | 满分验收标准 | 当前状态 | 当前证据 | 缺口 | 大改待办 | 预估贡献 |
|---|---|---|---|---|---|---:|
| 角色 Prompt / 策略独立性 | 5 核心角色均有独立 Prompt 或 StrategyCard | 已完成 | `prompts.py`、`playbooks.py`、`strategies/*` | 扩展角色未全部 playable | P3-2 | 3/3 |
| 角色行为差异 | 行动分布和策略模板差异显著 | 部分完成 | playbook / profile 差异存在 | 缺批量行为分布报告 | P2-1、P1-6 | 2/3 |
| 决策可追溯 | ≥95% 决策有结构化 trace | 部分完成 | `DecisionAudit`、`DecisionTrace` | trace 满分字段覆盖率未统计 | P1-5 | 2/4 |
| 候选动作记录 | 记录 candidate_actions 和选择理由 | 部分完成 | `parsed_action`、`reasoning` | candidate_actions 不稳定 | P1-5 | 1/2 |
| 信念变化记录 | 决策前后有 belief_delta 或等价记录 | 部分完成 | `BeliefState`、`BeliefTracker` | belief_delta 覆盖率未量化 | P1-5 | 1/2 |
| bad case 能力 | Golden Cases TPR ≥80%，FPR ≤20%，带 CI | 部分完成 | B 规格测试通过 | artifact / open data / CI 缺失 | P0-2、P2-1 | 3/6 |

**9.2 多 Agent 协作与系统设计子项矩阵**

| 子项 | 满分验收标准 | 当前状态 | 当前证据 | 缺口 | 大改待办 | 预估贡献 |
|---|---|---|---|---|---|---:|
| 公共 / 私有信息分离 | GameState、PlayerView、TeamView、Truth 明确隔离 | 已完成 | `Visibility.for_player`、`PlayerView` | RAG/Memory 报告不足 | P1-4 | 4/4 |
| final_agent_input 安全 | PlayerView + Memory + Retrieval + Prompt 无 hidden truth | 部分完成 | `tests/test_visibility_final_agent_input.py` | Retrieval/Memory 注入链路需更强证据 | P1-4 | 3/4 |
| 历史管理 | 每个 Agent 有摘要或 Memory，不粗暴无限拼接 | 部分完成 | `BeliefState`、`cognitive/observe.py` | 长局上下文压力未量化 | P1-5 | 2/3 |
| 技能抽象 | 技能调度清晰，新增角色改动小 | 部分完成 | `ActionValidator`、`RoleRegistry`、`WerewolfGame` | 部分技能仍在 engine 分支中 | P3-2 | 2/3 |
| 狼队协作 | 合法 WolfTeamView、协作刀人、统一口径 | 部分完成 | `wolf_team.py`、wolf vote events | 战术分配效果未量化 | P1-6 | 2/3 |
| 好人协作 / 反欺骗 | 归票、站队、交叉验证、矛盾检测 | 部分完成 | `BeliefTracker`、review bad cases | 样例和指标不足 | P2-1 | 3/3 |

**9.3 工程实现与系统完整度子项矩阵**

| 子项 | 满分验收标准 | 当前状态 | 当前证据 | 缺口 | 大改待办 | 预估贡献 |
|---|---|---|---|---|---|---:|
| 对局全流程稳定 | 50 局完成率 ≥95% | 部分完成 | `backend.run_demo` 单局完成 | 缺 50 局报告 | P2-3 | 3/5 |
| Phase / 规则边界 | Phase transition 100%，边界覆盖 ≥95% | 部分完成 | `tests/test_engine.py`、B/C targeted tests | full suite 不绿 | P0-2 | 4/6 |
| 非法动作恢复 | 非法动作拦截、fallback、不中断 | 部分完成 | `ActionValidator`、fallback vote | 恢复率未统计 | P2-3 | 2/3 |
| 信息隔离无泄露 | PlayerView / Memory / Retrieval / final input 泄露数 0 | 部分完成 | final input tests 通过 | 全链路报告不足 | P1-4 | 4/5 |
| 可观测性 | fallback、token、latency、cost、retrieved docs 可记录 | 部分完成 | `DecisionAudit` | cost/coverage 缺口 | P1-5 | 3/5 |
| 前端观战 / 可解释 | Replay Viewer 支持核心交互和截图证据 | 部分完成 | Next build 通过 | Playwright smoke 失败 | P1-3、P2-2 | 2/4 |
| 文档可运行 / 代码质量 | clean runbook、CI、全量测试稳定 | 部分完成 | README、reports | full suite 失败 | P0-2、P1-1 | 2/2 |

**9.4 进阶课题子项矩阵**

| 子项 | 满分验收标准 | 当前状态 | 当前证据 | 缺口 | 大改待办 | 预估贡献 |
|---|---|---|---|---|---|---:|
| 多维评测 | 发言、投票、技能、协作、质量全覆盖 | 部分完成 | `ReviewReportBuilder`、B tests | artifact/report 缺失 | P1-1 | 4/5 |
| 关键决策复盘 | 定位影响胜负或局势的关键行动 | 部分完成 | bad case / turning point code | Golden Cases 公开证据不足 | P2-1 | 4/5 |
| 反事实推演 | 覆盖投票、技能、发言策略、身份暴露 | 部分完成 | `CounterfactualAnalyzer`、B gate pass | full suite artifact 阻塞 | P0-2 | 4/5 |
| Leaderboard | 区分模型 / Agent / 版本能力 | 部分完成 | `LeaderboardEntry`、API routes | 样例发布报告不足 | P1-1 | 2/4 |
| 知识可信度 | L0-L4、access、applicability 完整 | 部分完成 | `knowledge_confidence.py` | 持久化 runtime 链路不足 | P1-4 | 3/5 |
| A/B 验证 | 20 局以上显著提升，可回滚 | 部分完成 | `TournamentRunner`、C tests | LLM-only A/B 缺失 | P1-6 | 3/6 |

## 10. 当前可量化测试能力

| 命令 | 结果 | 说明 |
|---|---|---|
| `pytest tests/test_role_registry.py tests/test_visibility_final_agent_input.py -q` | 17 passed | 角色注册与 final_agent_input 信息隔离目标测试通过 |
| `python -m backend.run_demo --seed 7` | 到 `GAME_END`，winner=`wolf` | 单局 heuristic demo 可完成 |
| `pytest tests/test_b_full_acceptance.py tests/test_c_acceptance_verification.py -q` | 34 passed in 53.82s | B/C 规格验收测试通过 |
| `pytest tests/test_api.py::test_runtime_metrics_and_aggregate_endpoints tests/test_engine.py::test_day_vote_tie_enters_pk_and_resolves -q` | 2 passed | 本轮修复的 API 聚合和 PK 测试回归通过 |
| `npm run build --prefix frontend` | passed | Next.js 构建和类型检查通过 |
| `python -m py_compile ...` | passed | 本轮修改 Python 文件语法检查通过 |
| `pytest tests/ -q` | 30 failed, 300 passed, 32 skipped, 86 warnings in 215.21s | 当前全量仍不绿；失败集中在 Track B 模型 artifact / open data / 发布报告 / vnext 报告 / UI smoke，均已进入 backlog |
| `rg "ark-[A-Za-z0-9-]{20,}|sk-[A-Za-z0-9]{20,}"` | 无命中 | 本轮移除硬编码 LLM provider key pattern |

## 11. 系统验收指标总表

| 优先级 | 指标 | MVP 标准 | 及格标准 | 满分标准 | 量化方式 | 对应模块 | 当前状态 | 证据路径 | 风险 | 大改待办 |
|---|---|---|---|---|---|---|---|---|---|---|
| P0 | API key hygiene | 不提交 key | 扫描无 provider key | CI secret scan + key rotation | `rg` + CI | DevOps | 部分完成 | `scripts/*` | 外部轮换未确认 | P0-1 |
| P0 | 完整对局 | 1 局完成 | 多 seed smoke | 50 局 ≥95% | batch runner | Engine | 部分完成 | `backend.run_demo` | 长跑缺失 | P2-3 |
| P0 | 信息隔离 | PlayerView 裁剪 | 自动化无泄露 | 全链路泄露数 0 | pytest + report | Visibility | 部分完成 | `tests/test_visibility_final_agent_input.py` | RAG/Memory 未闭环 | P1-4 |
| P0 | Track B artifact | 可加载模型 | Track B 测试通过 | artifact manifest 可复现 | pytest | Eval | 未完成 | `data/health/*.pkl` | pickle/env 不兼容 | P0-2 |
| P1 | ReviewReport | 可生成报告 | B 规格通过 | 发布报告可复现 | pytest + docs | Eval | 部分完成 | `backend/eval/review.py` | 报告 artifact 缺失 | P1-1 |
| P1 | Counterfactual | 有反事实 | vote/skill/info 通过 | 多类型反事实有证据链 | pytest | Eval | 部分完成 | `CounterfactualAnalyzer` | full artifact 阻塞 | P1-1 |
| P1 | Evolution A/B | 有 pipeline | C 规格通过 | LLM 20 局 A/B 显著提升 | tournament report | Eval | 部分完成 | `backend/eval/evolution.py` | LLM-only 缺失 | P1-6 |
| P1 | DecisionTrace | 有决策日志 | 有模型/延迟/token | ≥95% 满字段覆盖 | coverage script | Observability | 部分完成 | `DecisionAudit` | schema 未统一 | P1-5 |
| P1 | Frontend smoke | build 通过 | 主要页面可访问 | 截图/demo 覆盖核心交互 | Playwright | Frontend | 部分完成 | `frontend/app/*` | screenshot 失败 | P1-3 |
| P2 | Golden Cases | 有用例 | 能识别明显错误 | TPR/FPR + CI | labeled dataset | Eval | 部分完成 | `tests/test_b_full_acceptance.py` | 数据缺口 | P2-1 |

## 12. 当前系统完成度评分表

| 项目 | 当前状态 | 保守结论 |
|---|---|---|
| MVP 可交付性 | 已完成 | 角色、流程、信息隔离、日志、前端基础都存在，单局可跑 |
| 及格线 | 部分完成 | 关键模块齐全，B/C targeted tests 通过，但全量测试不绿 |
| 满分线 | 部分完成 | 需要修复 artifact、LLM-only 报告、DecisionTrace 覆盖、前端 smoke |
| 当前总分 | 部分完成 | 约 71/100，主打 B/C 有竞争力但不能称满分 |

## 13. 已执行的小改

| 文件 | 改动内容 | 改动等级 | 为什么安全 | 如何验证 | 是否已测试 |
|---|---|---|---|---|---|
| `configs/rule_variant_standard.yaml` | 7-12P 配置对齐 `WOLFCHA_ROLE_CONFIGS` | S1 | 只改配置证据，不改引擎逻辑 | YAML 与代码表比对 | 已测试 |
| `backend/eval/review.py` | 技能反事实类型归一为 `skill`，修 `witch_poison_target_id` | S2 | 保留语义字段，恢复旧验收口径 | B/C 规格测试 | 已测试 |
| `backend/eval/evolution.py` | `KnowledgeDocValidator` 兼容 DB 旧行 `None` | S2 | 只在校验文本拼接前做归一化 | API 聚合目标测试 | 已测试 |
| `tests/test_engine.py` | PK 测试同时接 `_batch_ask`，补 `SHOOT` 分支 | S2 | 测试桩补完整，不改产品逻辑 | engine 目标测试 | 已测试 |
| `scripts/finetune_llm_verified.py` 等 5 个脚本 | 移除硬编码 LLM key 默认值，改环境变量 | S2 | 不改算法，只改配置来源 | secret pattern scan + py_compile | 已测试 |
| `docs/DEVELOPMENT_ISSUES.md` | 记录 A10/C14/D5/F4/H9 闭环 | S1 | 文档追加 | 人工检查 | 已完成 |
| `docs/system_improvement_backlog.md` | 建立 S3 大改清单 | S1 | 文档新增 | 本报告引用 | 已完成 |

## 14. 需要大改的事项

大改事项已写入 `docs/system_improvement_backlog.md`。核心清单：

| 编号 | 问题 | 优先级 | 影响 |
|---|---|---|---|
| P0-1 | 敏感配置彻底治理与外部 key 轮换 | P0 | 安全红线 |
| P0-2 | Track B 模型 artifact / env 不兼容 | P0 | 全量测试与评测复现 |
| P1-1 | 缺失 Track B 发布报告 | P1 | 展示与复盘证据 |
| P1-3 | 前端 Playwright smoke 不稳定 | P1 | UI 满分证据 |
| P1-4 | 知识可信度/权限/适用条件未完全持久化 | P1 | C 方向满分 |
| P1-5 | DecisionTrace 覆盖率未量化 | P1 | 可观测性和单 Agent 满分 |
| P1-6 | 正式 LLM-only 验收证据缺失 | P1 | 用户硬要求和进阶评分 |

## 15. 主要风险与 P0 修复项

1. **安全风险**：历史 hardcoded LLM key 已从代码移除，但必须外部轮换；默认 DB 密码/连接串需要统一治理。
2. **全量测试风险**：Track B 模型 artifact 不兼容仍是最大阻塞；不能用 B/C targeted pass 替代 full suite。
3. **验收证据风险**：缺 LLM-only 批量对局、50 局稳定性、Golden Cases CI、Replay Viewer 截图。
4. **知识污染风险**：L0-L4/access/applicability 设计已有，但运行时持久化检索链路还需闭环。
5. **评分表述风险**：当前可称“B/C 规格测试通过、轻量自进化设计和代码路径存在”，不能称“自进化已显著提升胜率”。

## 16. 下一步建议

| 优先级 | 下一步任务 | 验收方式 |
|---|---|---|
| P0 | 轮换曾暴露外部 key，清理默认 DB 密码策略，加入 CI secret scan | secret scan 通过，外部 key 轮换确认，CI 阻断敏感 pattern |
| P0 | 重训或 pin Track B model artifact 环境 | `tests/test_track_b_*` / `tests/test_vnext_*` 不再因 pickle/env 失败 |
| P1 | 生成 Track B 发布报告和 vnext 报告 artifact | 缺失 docs 文件由脚本可复现生成，相关测试通过 |
| P1 | 修前端 Playwright smoke 与截图输出 | smoke 在本地/CI 通过，artifact 截图可查看 |
| P1 | 生成 20 局 LLM-only 批量验收报告 | `runner_mode=llm`、`fallback_count=0`、token/latency/cost 完整 |
| P1 | 统一 `DecisionAudit` / `DecisionTrace` runtime schema | ≥95% 决策 trace 满字段覆盖率报告 |
| P1 | 接通 `KnowledgeConfidence` / access / applicability 到 DB 检索和 prompt 注入 | L4 检索阻断率 100%，权限/适用性测试通过 |
| P2 | 生成 50 局标准配置稳定性报告 | 完成率 ≥95%，异常局有日志 |
| P2 | Golden Cases 标签、TPR/FPR 与 CI | TPR ≥80%，FPR ≤20%，带样本数和置信区间 |
| P3 | 继续冻结未接入引擎的模板角色 | 新角色启用前必须有技能结算和边界测试 |
