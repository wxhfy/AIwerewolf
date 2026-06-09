# 核心模块设计

## 1. WerewolfGame

**模块定位**：后端对局引擎，负责狼人杀规则执行和状态推进。

**输入输出**：

| 输入 | 输出 |
|---|---|
| player_count、seed、角色配置、Agent 工厂、规则配置 | GameState、GameEvent、AgentDecision、GameSnapshot、终局结果 |

**内部流程**：

1. 初始化玩家、角色、人格和状态。
2. 进入阶段状态机。
3. 对每个需要行动的玩家生成 PlayerView。
4. 调用 Agent 并获取 Decision。
5. 校验动作合法性。
6. 结算技能、投票、死亡和胜负。
7. 写入事件、快照和决策审计。
8. 终局后进入 Track B/C 后处理。

**关键设计**：

| 设计 | 说明 |
|---|---|
| 引擎主控 | Agent 只输出行动，不直接修改状态 |
| 阶段状态机 | 夜晚、白天、警长、投票、特殊阶段统一推进 |
| 并行调度 | 投票和部分夜晚动作可批量并行，降低 LLM 等待 |
| 幂等守卫 | 避免刷新、重连或重复调用造成重复结算 |
| 统一审计 | `_record_decision()` 记录所有 Agent 行为 |

**设计收益**：规则一致、流程可复现、便于验收、便于扩展角色、便于回放和复盘。

**验收方式**：`scripts/run_backend_full_strict.py`；当前结果以 `docs/evidence/` 和严格模式命令为准。

**当前限制**：扩展角色仍需补充更多规则测试；长期并发压力测试需要单独运行。

## 2. Visibility / PlayerView

**模块定位**：信息隔离层，连接真实 GameState 与 Agent 输入。

**输入输出**：

| 输入 | 输出 |
|---|---|
| GameState、player_id | PlayerView |

**内部流程**：

1. 读取真实状态。
2. 判断当前玩家身份、阵营和存活状态。
3. 生成 self_player。
4. 裁剪其他玩家公开信息。
5. 过滤 public_events 和 private_events。
6. 生成合法目标 legal_targets。
7. 对狼人补充合法狼队视图。

**关键设计**：

| 设计 | 说明 |
|---|---|
| Truth State 与 PlayerView 分离 | 真实状态不直接给 Agent |
| 私有事件过滤 | 查验、用药等只给合法玩家 |
| 狼队视图 | 仅狼人阵营可见队友身份 |
| legal_targets | 将合法目标显式给 Agent，减少非法输出 |

**设计收益**：防止上帝视角；让推理更接近真实玩家；为赛后复盘提供“当时可见事实”边界。

**验收方式**：`scripts/verify_visibility_strict.py`；当前结果以信息隔离专项验证命令为准。

**当前限制**：每新增角色、私有事件或前端视角，都需要补充隔离测试。

## 3. CognitiveAgent

**模块定位**：AI 玩家认知决策主体。

**输入输出**：

| 输入 | 输出 |
|---|---|
| PlayerView、角色、人格、记忆、策略上下文、LLM client | Decision |

**内部流程**：

1. Observe：PlayerView -> Observation。
2. 更新 Memory 和 BeliefTracker。
3. 根据角色和阶段准备上下文。
4. AgentLoop 调用工具和 LLM。
5. 输出 talk / vote / skill Decision。
6. 对局结束后执行反思。

**关键设计**：

| 设计 | 说明 |
|---|---|
| Observe -> Think -> Act | 决策流程清晰可审计 |
| Memory | 保留近期行动、判断和角色状态 |
| BeliefTracker | 跟踪对其他玩家身份的信念 |
| SocialModel | 管理信任与怀疑关系 |
| Planner | 支持跨阶段战略意图 |
| WolfTeamView | 狼队合法协作信息 |

**设计收益**：支持角色差异、多轮记忆、狼人协作和可解释决策。

**验收方式**：strict mode Agent Decision；数据库 agent_decisions；工具 trace。

**当前限制**：不同 MBTI 与角色组合的长期稳定性需要补测。

## 4. AgentLoop

**模块定位**：工具调用式决策循环。

**输入输出**：

| 输入 | 输出 |
|---|---|
| Observation、Memory、system prompt、action_type、tools、LLM | parsed action、tool trace、retrieved strategy IDs |

**内部流程**：

1. 构建系统上下文和 Observation。
2. 根据 action_type 限制工具轮数。
3. 暴露工具 schema。
4. LLM 选择工具或提交决策。
5. 工具结果进入上下文。
6. 生成最终 Decision。
7. 记录 `_tool_trace`。

**关键设计**：

| 当前工具 | 作用 |
|---|---|
| `search_strategies` | 策略知识检索 |
| `recall_memory` | 记忆查询 |
| `check_rules` | 规则查询 |
| `get_social_info` | 社交信任信息 |
| `analyze_votes` | 投票模式分析 |
| `set_strategic_intent` | 跨阶段意图记录 |
| `submit_decision` | 最终决策提交 |

**设计收益**：降低一次性 Prompt 压力；让 Agent 主动获取信息；tool_trace 可审计；可分析策略是否被实际使用。

**验收方式**：检查 `agent_decisions.metadata` 或 `parsed_action._tool_trace`；strict 验收文档记录 26/27 决策带工具追踪。

**当前限制**：工具调用对过程分和胜率的贡献需要在线 A/B 验证。

## 5. StrategyRetriever

**模块定位**：策略知识检索模块。

**输入输出**：

| 输入 | 输出 |
|---|---|
| keywords、role、phase、mbti、alignment、retrieval_policy、visibility context | top-k strategy docs |

**内部流程**：

1. 从 PostgreSQL active 策略知识构建索引。
2. 根据 Agent 的 `role / mbti / alignment / phase / action_type / keywords` 构造检索上下文。
3. 先用关键词或正则在 situation、strategy、rationale 等字段中召回候选，候选不足时使用 BM25 兜底。
4. 按 RetrievalPolicy 选择候选范围；默认 `hybrid_role_mbti_global` 依次填充 `same_role_same_mbti -> same_role_all_mbti -> global`。
5. 应用质量门禁、去重、Top-K 填充和 4-filter 安全管线。
6. 返回策略摘要或正文，并将 bucket、policy、doc_id 等写入 trace。

**关键设计**：

| 设计 | 说明 |
|---|---|
| BM25 + 倒排索引 | 本地轻量可解释检索 |
| RetrievalPolicy | 支持角色、MBTI、全局和混合策略 |
| 4-filter | confidence / visibility / privacy / applicability |
| candidate 屏蔽 | 对局内默认只用 active 知识 |

**单角色量化结果**：

| 指标 | 当前值 | 来源 |
|---|---:|---|
| 默认 policy | `hybrid_role_mbti_global` | `backend/agents/cognitive/tools.py` |
| query set | 26 | `outputs/retrieval_effectiveness_current/results.json` |
| Coverage | 1.0000 | 同上 |
| Effective@3 | 0.5000 | 同上 |
| P@3 | 0.2564 | 同上 |
| RoleBucketShare | 0.9923 | 同上 |
| GlobalBucketShare | 0.0077 | 同上 |
| `same_role_same_mbti` empty | 22/26 | 同上 |

分角色 Effective@3：Guard 1.0000、Hunter 1.0000、Seer 0.6000、Villager 0.5000、Werewolf 0.2857、Witch 0.2500。该结果说明当前默认检索能稳定覆盖核心角色，且主要从本角色策略桶返回内容；但它是离线弱标注检索指标，不能直接解释为在线胜率提升。

**设计收益**：策略不写死；无需 GPU；可解释；可安全回流。

**验收方式**：`scripts/evaluate_retrieval_policies.py`、`scripts/evaluate_retrieval_policies_llm_judge.py`、tool_trace。

**当前限制**：离线检索分数不能直接说明真实对局效果；在线策略对比需补。

## 6. PostgreSQL Evidence Chain

**模块定位**：系统证据链和实验数据中心。

**输入输出**：

| 输入 | 输出 |
|---|---|
| 对局运行记录、Agent 决策、复盘指标、知识、反馈 | games、players、events、decisions、evaluations、reviews、knowledge docs |

**内部流程**：

1. 初始化 DB schema。
2. 对局开始写 games / players。
3. 运行中写 events / snapshots / decisions / votes。
4. 赛后写 evaluations / published_reviews / leaderboard_entries。
5. 知识回流写 strategy_knowledge_docs / knowledge_usage_feedback。

**关键设计**：

| 表 | 作用 |
|---|---|
| `games` | 对局元数据 |
| `players` | 玩家、角色、人设、存活状态 |
| `game_events` | 事件流 |
| `game_snapshots` | 主持视角与公开视角快照 |
| `agent_decisions` | 决策审计 |
| `evaluations` | 决策质量与复盘指标记录 |
| `published_reviews` | 复盘报告 |
| `strategy_knowledge_docs` | 策略知识 |
| `knowledge_usage_feedback` | 策略使用反馈 |

**设计收益**：可审计、可复盘、可统计、可做实验分析、支撑 Track B/C。

**验收方式**：strict preflight；PostgreSQL 查询。当前 PostgreSQL 快照显示 public base tables 为 22，`agent_decisions=250603`，来源：PostgreSQL 查询，2026-06-07 13:55:01 UTC。

**当前限制**：数据库包含历史和运行中数据；正式指标需按 experiment_id / provider / strict 标记过滤。

## 7. PerStepScorer

**模块定位**：Track B 逐步复盘分析器。

**输入输出**：

| 输入 | 输出 |
|---|---|
| decisions、state、speech_acts、LLM judge 可选 | DecisionScore、ScoredStep、PlayerReviewReport |

**内部流程**：

1. 按 action type 选择 vote / talk / night scorer。
2. 先用确定性规则给出基础分。
3. 对模糊决策可触发 light LLM。
4. 对高影响模糊决策可触发 heavy judge panel。
5. 标记 highlight / mistake。
6. 生成可供 KnowledgeAbstractor 消费的 ScoredStep。

**关键设计**：

| 设计 | 说明 |
|---|---|
| correctness | 目标或发言方向是否正确 |
| reasoning_quality | 推理质量 |
| timeliness | 时机选择 |
| impact | 对局势影响 |
| highlight/mistake | 直接服务复盘和知识抽取 |

**设计收益**：不只看胜负；能定位失误；能为 Track C 提供结构化经验。

**验收方式**：当前本地数据库快照有 `evaluations=126003`，复盘证据文件统一放在 `docs/evidence/`。

**当前限制**：实际 Tier 触发比例、judge agreement 和人工一致性需要补实验。

## 8. Track C Knowledge Layer

**模块定位**：Track C 经验抽取、runtime 策略回流，以及 Wiki/Hermes 增量设计的连接层。

**输入输出**：

| 输入 | 输出 |
|---|---|
| PlayerReviewReport、ScoredStep | AbstractedLesson、StrategyKnowledgeDoc；Wiki source item 属于离线增量层 |

**内部流程**：

1. 从 highlight 提取“应该继续采用的策略”。
2. 从 mistake 提取“应该避免的行为”和正向替代建议。
3. 从 strategy_applied 提取“检索策略是否有帮助”。
4. 对 lesson 去重。
5. 标记 experiment_id。
6. 写入 `strategy_knowledge_docs`，默认 status=candidate。
7. 可选离线层将复盘、策略文档和使用反馈作为 Track C Wiki 的 raw sources。
8. Hermes-style DreamJob 可生成 candidate patch，验证后同步回 runtime 策略池。

Track C 的完整图谱见 [`ENGINEERING_ARCHITECTURE.md`](ENGINEERING_ARCHITECTURE.md)，Wiki/长期知识编译层见 [`wiki/track-c/overview.md`](wiki/track-c/overview.md)。

**关键设计**：

| 设计 | 说明 |
|---|---|
| candidate 默认状态 | 防止新知识直接污染 active |
| source ids | 追溯到 game、step、event |
| role / phase / persona_scope | 支持未来精确检索 |
| quality / confidence | 支持晋级与过滤 |

**Candidate 生效机制**：candidate 代表“已抽取、待验证”的经验，不代表生产对局立即注入。`KnowledgeAbstractor` 默认写入 candidate；`promote_after_store()` 根据质量阈值和角色/类型聚类晋级 active；`retrieval_prod` 构建生产索引时只加载 active，并用 maturity、validated_at、knowledge_epoch 和使用反馈排序。因此 candidate 的主要作用是积累和筛选，active 才是稳定影响下一局 Agent 的策略层。

**设计收益**：复盘经验可沉淀；知识可回流；策略池可控。

**验收方式**：strict 验收文档记录 candidate 增量和 active 零污染；当前本地数据库快照显示 `strategy_knowledge_docs` 为 active 387、candidate 216906、deprecated 17。

**当前限制**：晋级后的真实效果需要 paired seed 对照实验。

## 9. Frontend Console

**模块定位**：观战、交互和演示界面。

**输入输出**：

| 输入 | 输出 |
|---|---|
| REST API、WebSocket snapshot、game report | 玩家卡片、事件时间线、发言区、行动面板、复盘入口 |

**内部流程**：

1. 大厅创建或进入房间。
2. 游戏页订阅 room stream。
3. 按 snapshot 更新阶段、玩家、事件和投票状态。
4. 根据视角显示公开/主持信息。
5. 人类玩家通过 ActionPanel 提交操作。
6. 终局后展示胜负和报告入口。

**关键设计**：

| 设计 | 说明 |
|---|---|
| WebSocket snapshot | 实时展示对局进展 |
| PlayerCard / PlayerRail | 展示玩家状态 |
| EventTimeline | 展示发言、投票、夜晚公开事件 |
| HumanActionBar / ActionPanel | 支持人类玩家动作 |
| Report page | 展示复盘报告 |

**设计收益**：便于演示、调试、验收和后续 replay viewer 扩展。

**验收方式**：前端代码存在，`docs/assets/closure/screenshots/` 有结项展示截图。

**当前限制**：本轮未重新跑 Playwright 视觉验收；WebSocket 延迟和公开/主持视角切换需专项验证。
