# AI Werewolf 架构评估与评分对齐报告

> 日期：2026-06-02  
> 目标：评估当前 AI Werewolf 架构是否对齐项目初始目标、比赛评分标准与加分方向，并指出主要风险与优先改进路线。

---

## 1. 总体结论

当前架构整体方向是正确的，并且已经明显对齐比赛的核心目标：**Agent 调优能力 + 多智能体系统设计能力 + 工程实现完整度**。

从架构主线看，系统已经形成了比较完整的闭环：

```text
Game Engine → Agent Decision → Eval Review → Knowledge Evolution → Agent(next game)
     ↑                                                                    │
     └──────────── Strategy Retrieval(BM25/BGE/TF-IDF over PG) ───────────┘
```

这说明当前项目并不是一个普通的“狼人杀游戏 Demo”，而是一个偏研究和平台化的 **狼人杀多智能体评测、复盘、自进化系统**。

如果最初目标是：

> 做一个 AI 狼人杀多智能体系统，重点展示 Agent 决策、博弈策略、评测复盘、自我改进能力，并在比赛评分中尽可能拿高分。

那么当前架构与目标是高度一致的。

但如果最初目标只是：

> 快速做一个能演示的人机狼人杀小游戏。

那么当前架构已经明显偏重，复杂度较高。当前更适合作为“狼人杀 Agent 研究平台”来申报和展示。

**核心判断：当前架构具备冲击高分的潜力，但最大风险不是架构不够，而是可验证证据、前端展示、进阶方向收束和数据证明还不够硬。**

---

## 2. 与评分标准的对齐情况

评分规则中，Agent 相关能力合计 70%，工程相关能力合计 30%。当前架构最强的地方也正好集中在 Agent 决策、多 Agent 系统、评测复盘和知识演进闭环上。

### 2.1 单 Agent 能力，20%

#### 当前匹配度：强

当前 CognitiveAgent 已经包含：

- Profile：MBTI、PersonaTraits、MindTraits；
- BeliefTracker：角色声称、矛盾检测、投票模式；
- Memory：Humanization、Playbook、立场连续性；
- Pipeline：AgentLoop / 3-Step Chain；
- Retrieval：BM25 + BGE-M3 RRF；
- Reflector：多角度复盘并写入 PostgreSQL。

这能够覆盖评分标准中的：

- Prompt 设计质量；
- 角色人设；
- 角色策略差异；
- 决策链路可追溯；
- bad case 分析；
- 迭代调优过程。

#### 预估得分

设计层面：**16–18 / 20**

#### 主要风险

1. **人格设定不等于策略深度**

   MBTI、Persona、Humanization 可以提升自然度，但评委更关心的是狼人杀策略：

   - 预言家什么时候跳身份；
   - 狼人什么时候悍跳、倒钩、冲票；
   - 女巫什么时候救人、毒人；
   - 猎人什么时候开枪；
   - 村民如何归票、站队、识别矛盾。

   因此人格层应该作为表达风格，而不是核心策略证明。

2. **不同角色策略需要显式展示**

   建议补充一张角色策略表：

   | 角色 | 核心目标 | 信息优势 | 主要风险 | 发言策略 | 投票策略 | 技能策略 |
   |---|---|---|---|---|---|---|
   | 狼人 | 混淆视听、抗推好人 | 知道狼队 | 被查杀、站错队 | 伪装、倒钩、悍跳 | 保护狼队或牺牲队友 | 夜刀高价值目标 |
   | 预言家 | 建立可信验人链 | 查验结果 | 过早暴露被刀 | 控制跳身份时机 | 带队归票 | 查验高信息量玩家 |
   | 女巫 | 最大化药效 | 药品状态 | 误救狼、误毒神 | 隐藏身份、观察矛盾 | 跟随高可信信息 | 救/毒阈值判断 |
   | 猎人 | 死后带走高疑似狼 | 可开枪 | 被骗枪 | 威慑发言 | 压力投票 | 开枪置信度判断 |
   | 村民 | 通过公共信息推理 | 无私有信息 | 被带节奏 | 盘逻辑、找矛盾 | 跟随可信队伍 | 无技能 |

3. **决策可追溯不应依赖完整思维链**

   建议输出结构化决策记录，而不是暴露长 chain-of-thought：

   ```json
   {
     "phase": "DAY_VOTE",
     "agent_id": 3,
     "role": "seer",
     "visible_facts": ["P5 claimed seer", "P7 contradicted P5 vote"],
     "belief_delta": {"P5": "+wolf_suspicion", "P7": "+villager_suspicion"},
     "candidate_actions": ["vote P5", "vote P8", "abstain"],
     "chosen_action": "vote P5",
     "confidence": 0.74,
     "rationale": "P5's claim conflicts with prior vote pattern and timing",
     "retrieved_strategy_ids": ["seer_claim_timing_v2"],
     "prompt_version": "seer_v4.1",
     "agent_version": "cognitive_v7"
   }
   ```

---

### 2.2 多 Agent 协作与系统设计，20%

#### 当前匹配度：强

当前架构中已经有：

- PlayerView；
- Visibility.for_player()；
- BeliefTracker；
- 角色注册表；
- ActionValidator；
- PhaseManager；
- GameEvent / AgentDecision / ReviewReport 等数据结构。

这些设计能够对应评分标准中的：

- 公共信息和私有信息管理；
- 上下文维护；
- 技能调度；
- 多 Agent 通信；
- Agent 间博弈行为；
- 信息隔离。

#### 预估得分

设计层面：**16–18 / 20**

#### 主要风险

1. **公共信息 / 私有信息 / 阵营信息边界需要更硬**

   建议明确如下信息分层：

   | 信息类型 | 示例 | 谁能看到 | 是否进入 Agent Memory | 是否进入 Strategy Knowledge |
   |---|---|---|---|---|
   | Public | 白天发言、投票、死亡 | 全员 | 是 | 可脱敏进入 |
   | Private Role | 自己身份、技能状态 | 自己 | 是 | 不可跨局泄露 |
   | Team Private | 狼队名单、夜聊 | 狼队 | 是 | 只可脱敏统计 |
   | Hidden Truth | 其他人真实身份 | 引擎 | 否 | 否 |
   | Post-game Truth | 全局真相 | 赛后评测 | 只进评测 | 可脱敏进入 |

2. **狼人团队协作要单独突出**

   多 Agent 博弈不能只是每个 Agent 独立决策。建议补充：

   - 狼队夜间如何协商刀人；
   - 谁悍跳、谁倒钩、谁冲票；
   - 狼队成员如何避免发言互相矛盾；
   - 狼人如何通过公共发言误导好人阵营。

3. **技能抽象建议升级为通用 Skill 协议**

   当前有 roles 注册表，但如果要体现可扩展性，建议补充类似：

   ```python
   class Skill(Protocol):
       name: str
       owner_role: Role
       phase: Phase
       visibility_scope: VisibilityScope

       def legal_targets(self, state: GameState, actor: Player) -> list[PlayerId]: ...
       def validate(self, action: Action, state: GameState) -> ValidationResult: ...
       def apply(self, action: Action, state: GameState) -> list[GameEvent]: ...
       def summarize_for_actor(self, state: GameState, actor: Player) -> str: ...
       def summarize_for_public(self, event: GameEvent) -> str: ...
   ```

4. **BeliefTracker 不能读取真实身份**

   BeliefTracker 应只追踪“当前 Agent 相信谁是什么身份”，不能读取引擎中的真实身份。这个点如果出错，会严重影响信息隔离评分。

---

### 2.3 工程实现与系统完整度，30%

#### 当前匹配度：中强

当前 engine 结构较完整：

- models.py；
- game.py；
- phase_manager.py；
- phases.py；
- actions.py；
- visibility.py；
- rules.py；
- roles/。

数据库层也覆盖：

- Game；
- Player；
- GameEvent；
- AgentDecision；
- Evaluation；
- LeaderboardEntry；
- ReviewReport；
- StrategyKnowledgeDoc；
- EvolutionRound。

这说明当前项目不是单纯靠 prompt 伪造规则，而是有实际对局引擎、状态机、合法性校验、信息隔离和评测数据结构。

#### 预估得分

设计层面：**22–26 / 30**

#### 主要风险

1. **三层容错表述需要修正**

   当前文档中有一处表述为：

   ```text
   Heuristic → LLMAgent → CognitiveAgent
   ```

   这个方向容易让人误解为“从启发式升级到 CognitiveAgent”。但容错通常应该是主路径失败后降级。

   建议改为：

   ```text
   CognitiveAgent 主路径 → LLMAgent 降级 → HeuristicAgent 最终兜底
   ```

2. **前端体验证据偏弱**

   评分亮点中特别提到前端体验、动画、状态可视化、非技术人员可理解。当前架构中虽然有 PublishedReviewDocument、SVG 可视化、HumanAgent，但还需要一个更明确的 Replay Viewer。

   建议至少提供：

   - 阶段时间轴；
   - 玩家状态盘；
   - Agent 决策面板；
   - 上帝视角 / 玩家合法视角切换；
   - bad case 高亮；
   - 反事实结果展示；
   - Leaderboard 页面。

3. **监控和日志需要产品化**

   建议在 AgentDecision 或日志系统中明确记录：

   | 字段 | 用途 |
   |---|---|
   | prompt_hash | 复现某次决策 |
   | model_name / provider | 比较模型能力 |
   | token_in / token_out / cost | 成本控制 |
   | latency_ms | 性能评估 |
   | validation_error_count | 检查非法行动 |
   | fallback_reason | 证明容错有效 |
   | visibility_scope_hash | 检查信息隔离 |
   | retrieved_doc_ids | 证明 RAG 生效 |
   | agent_version | Leaderboard 对比 |
   | random_seed | 对局复现 |

4. **规则边界测试必须补齐**

   狼人杀很容易在规则细节上被扣分。建议至少覆盖：

   - 平票如何处理；
   - 女巫同夜救/毒规则；
   - 守卫是否能连续守同一人；
   - 猎人被毒是否能开枪；
   - 狼刀、女巫救、毒、守卫保护的结算顺序；
   - 白痴、警长、遗言、警徽流等规则变体；
   - 死亡玩家是否还能发言、投票、接收信息；
   - Agent 非法行动时如何修正或跳过。

5. **并发和锦标赛调度需要具体化**

   TournamentRunner 是加分点，但需要说明：

   - 多局并发如何调度；
   - LLM 调用如何限流；
   - 失败如何重试；
   - 是否支持断点续跑；
   - random seed 是否可复现。

---

### 2.4 进阶课题完成度，30%

当前架构同时覆盖了两个方向：

- Track B：评测 + 复盘；
- Track C：自进化 Agent。

但比赛进阶课题是三选一。建议明确主线，否则展示时会显得分散。

#### 推荐主线

建议主申报方向选择：

> **评测 + 复盘**

并将自进化 Agent 作为加分亮点。

理由：当前已有 deterministic replay、CounterfactualAnalyzer、MetricsCalculator、PerStepScorer、LLM Judge、PublishedReviewDocument、LeaderboardEntry，这些能力与“评测 + 复盘”的评分要求最直接匹配。

#### 预估得分

如果主打“评测 + 复盘”：**25–28 / 30**

#### 必须补充的证据

1. **构造一局明显失误对局**

   示例：

   - 预言家第一天没有跳身份，导致好人崩盘；
   - 女巫误毒真预言家；
   - 狼人过早冲票暴露团队；
   - 村民跟错归票导致神职出局。

2. **系统自动定位失误**

   报告中应明确：

   - 出错 phase；
   - 出错 agent；
   - 原始 action；
   - 错误原因；
   - 替代 action；
   - 预期收益变化。

3. **生成结构化报告和 Leaderboard**

   Leaderboard 应能区分：

   - cognitive_v1；
   - cognitive_v2；
   - llm_baseline；
   - heuristic_baseline；
   - 不同模型 provider。

#### 不建议主打通用 Agent

通用 Agent 的评分要求是：

```text
读懂自身代码 → 改代码 → 自动构建测试 → 失败回滚 → 过程可审核
```

当前架构更像是“策略知识演进”和“Agent 行为演进”，而不是明确的代码自修改、CI、测试、回滚闭环。

因此除非已经实现真实 code patch、自动测试、失败回滚，否则不建议把“通用 Agent”作为主申报方向。

---

## 3. 与评判亮点的对应关系

| 亮点方向 | 当前匹配度 | 评价 |
|---|---:|---|
| 策略深度 | 高 | BeliefTracker、Memory、Retrieval、Playbook、Reflector 能支撑策略深度，但要补角色级策略样例。 |
| 工程完整度超预期 | 中高 | 引擎、DB、LLM 抽象、评测系统强；错误处理、并发、监控告警需要更显式。 |
| 前端体验出色 | 偏弱 / 未知 | 当前只看到 SVG、PublishedReviewDocument、HumanAgent，缺少完整可视化前端证据。 |
| 可扩展架构 | 高 | Protocol、角色注册表、Phase Handler、Eval 分层都不错，建议补 Skill interface。 |
| 人机交互 | 中 | HumanAgent 存在，但需要真人加入对局的 UI、状态同步和权限控制。 |
| 进阶课题独创性 | 高 | 反事实复盘、级联评分、知识演进闭环是亮点，但必须用数据证明效果。 |

---

## 4. 当前架构的主要问题

### 4.1 主线略分散

当前同时包含：

- CognitiveAgent；
- RAG；
- MBTI；
- BeliefTracker；
- Reflector；
- Track B；
- Track C；
- DreamJob；
- Tournament；
- LLM Judge；
- SVG；
- PostgreSQL。

这些模块本身有价值，但展示时容易让评委抓不到主线。

建议将项目主线收束为：

> 我们做了一个 AI 狼人杀多智能体系统，不只会玩，还能复盘每个关键决策，通过反事实评估定位 bad case，并把复盘知识回流到下一代 Agent。

这条主线比堆模块名更容易拿高分。

---

### 4.2 评测系统要避免“自评自嗨”

LLM Judge、三法官、Critic、trimmed-mean 是好设计，但评委可能会担心：LLM 评价 LLM 是否可靠。

建议将评测拆成三层：

1. **确定性规则层**
   - 胜负；
   - 非法行动；
   - 投票结果；
   - 技能效果；
   - 死亡顺序。

2. **半结构化指标层**
   - 发言一致性；
   - 投票贡献；
   - 技能收益；
   - 身份暴露风险；
   - 阵营协作贡献。

3. **LLM 裁判层**
   - 只评价难以规则化的策略质量；
   - 使用多法官聚合；
   - 输出可审计 reason；
   - 必须保留输入片段和版本号。

建议准备 golden cases：

| Case | 人类标注失误 | 系统是否识别 | 反事实是否合理 |
|---|---|---|---|
| 女巫误毒真预言家 | 是 | 是 | 改毒狼人则好人胜率上升 |
| 狼人过早冲票暴露 | 是 | 是 | 倒钩策略更优 |
| 预言家未报验人 | 是 | 是 | 提前跳身份可保留警徽流 |
| 村民跟错归票 | 是 | 是 | 改投悍跳狼可避免神职出局 |

---

### 4.3 信息隔离是高危点

Visibility.for_player() 是正确方向，但需要用测试证明没有泄露。

建议新增以下测试：

```text
test_wolf_cannot_see_seer_result
test_villager_cannot_see_wolf_team
test_dead_player_cannot_vote
test_agent_memory_does_not_include_hidden_truth
test_strategy_retrieval_does_not_return_current_game_private_info
test_postgame_reflection_is_not_visible_during_game
test_human_player_view_matches_agent_player_view
```

尤其要注意：

```text
Knowledge Evolution → Strategy Retrieval → Agent
```

这条回流链路不能把赛后全局真相泄露给下一局或当前局 Agent。策略知识可以学习模式，但不能泄露当前对局事实。

---

### 4.4 检索指标需要可解释

当前文档中出现：

```text
BM25 + BGE-M3 RRF, NDCG@5 = 0.942
```

这是亮点，但也可能被追问：

- 测试集多少条 query？
- relevance label 谁标注？
- 与 BM25-only、BGE-only、TF-IDF-only 的对比是什么？
- query 来自真实对局还是人工构造？
- 是否存在过拟合？

建议补充检索评测表：

| 方法 | NDCG@5 | Recall@5 | MRR | 成本 | 延迟 |
|---|---:|---:|---:|---:|---:|
| TF-IDF | 0.71 | 0.68 | 0.62 | 低 | 低 |
| BM25 | 0.78 | 0.74 | 0.70 | 低 | 低 |
| BGE-M3 | 0.89 | 0.86 | 0.82 | 中 | 中 |
| BM25 + BGE RRF | 0.942 | 0.91 | 0.88 | 中 | 中 |

---

### 4.5 MBTI 复盘不应成为核心卖点

16 MBTI 复盘角度是有趣功能，但容易被认为是包装性功能。

建议将其定位为：

> 多风格 Agent profile 与复盘视角。

不要让它压过：

- bad case 定位；
- 反事实推演；
- 策略补丁；
- A/B 验证；
- Leaderboard 提升。

---

### 4.6 Track B 和 Track C 需要主次关系

当前架构同时覆盖 Track B 和 Track C。建议最终表述为：

> 主赛道：评测 + 复盘。  
> 加分亮点：复盘知识自动回流，形成轻量自进化。

不要反过来。因为自进化 Agent 需要更多对局数据证明，而评测 + 复盘更贴合当前已经设计出的模块。

---

## 5. 预估得分

以下评分基于“架构已基本实现并可演示”的假设。如果只是文档设计，没有可运行 Demo，分数需要明显下调。

| 维度 | 权重 | 当前预估 | 原因 |
|---|---:|---:|---|
| 单 Agent 能力 | 20 | 16–18 | CognitiveAgent 设计强，但需展示角色策略差异、prompt 迭代和 bad case。 |
| 多 Agent 协作 | 20 | 16–18 | 信息隔离、BeliefTracker、角色系统不错；狼队协作和通信机制需要补证据。 |
| 工程完整度 | 30 | 22–26 | 引擎、DB、LLM 抽象强；前端、并发、监控、测试材料不足。 |
| 进阶课题：评测 + 复盘 | 30 | 25–28 | 反事实、级联评分、报告、Leaderboard 非常贴题；需 golden cases 和实际报告。 |
| 总分 | 100 | 79–90 | 取决于实现完成度、演示质量和证据强度。 |

如果补齐：

- 前端 Replay Viewer；
- 信息隔离测试；
- 角色策略样例；
- Leaderboard；
- 20 局 A/B 数据；
- 结构化 bad case 报告；

则有机会进入：

```text
88–94 分区间
```

如果只是代码能跑但展示弱、没有清晰 demo 和报告样例，可能落在：

```text
70–80 分区间
```

如果信息隔离或规则结算有严重错误，可能被压到：

```text
60–70 分区间
```

---

## 6. 最优先改进项

### 6.1 做一个评委视角演示脚本

演示不要从代码架构开始，而是从一局具体对局开始：

1. 启动一局 9 人狼人杀；
2. 展示每个 Agent 的合法视角；
3. 展示一轮发言和投票；
4. 展示某个 Agent 的结构化决策原因；
5. 展示对局结束后的 bad case；
6. 展示反事实：如果当时改投，结果如何变化；
7. 展示报告生成；
8. 展示 Agent v1/v2 Leaderboard 对比。

---

### 6.2 补充角色策略差异文档

每个角色至少给出：

- prompt 摘要；
- 策略目标；
- 行为偏好；
- 典型 bad case；
- 改进前后对比。

这是单 Agent 能力中最容易拿分的部分。

---

### 6.3 补充信息隔离测试报告

单独增加一个文档：

```text
docs/information_isolation_tests.md
```

核心问题是：

> 如何证明 Agent 没有偷看身份？

建议报告包括：

- 测试名；
- 输入状态；
- 当前玩家视角；
- 禁止出现的信息；
- 实际输出；
- 结论。

---

### 6.4 明确主赛道是评测 + 复盘

推荐表述：

> 本项目主攻“评测 + 复盘”：通过确定性 replay、反事实推演、级联评分和结构化报告，定位 Agent 在发言、投票、技能使用、阵营协作中的关键失误。进一步，我们将复盘结果沉淀为策略知识，作为自进化加分能力。

---

### 6.5 把 Leaderboard 做实

Leaderboard 不要只统计胜负。建议字段：

| Agent 版本 | 胜率 | 好人胜率 | 狼人胜率 | 平均发言分 | 投票贡献 | 技能收益 | bad case 数 | 成本 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cognitive_v1 | - | - | - | - | - | - | - | - |
| cognitive_v2 | - | - | - | - | - | - | - | - |
| llm_baseline | - | - | - | - | - | - | - | - |
| heuristic_baseline | - | - | - | - | - | - | - | - |

---

### 6.6 补 Replay Viewer

最低可接受版本：

- 左侧玩家列表；
- 中间时间轴；
- 右侧 Agent 决策详情；
- 底部发言记录；
- 支持切换“上帝视角 / 玩家视角”；
- 支持高亮 bad case；
- 支持查看反事实结果。

---

### 6.7 修正文档中容易被质疑的表述

| 当前表述 | 风险 | 建议 |
|---|---|---|
| Heuristic → LLMAgent → CognitiveAgent | 容错方向像反了 | CognitiveAgent → LLMAgent → HeuristicAgent |
| LLMAgent 遗留生产级 | “遗留”和“生产级”冲突 | Stable Baseline / Legacy Baseline |
| 16 MBTI 复盘角度 | 可能显得花哨 | 多风格复盘视角，非核心评分依据 |
| NDCG@5=0.942 | 若无证明会被追问 | 附检索评测集和对比实验 |
| 13 种反事实标签 vs 10 种反事实方法 | 数字不一致 | 说明 13 tags 如何映射到 10 analyzers |

---

### 6.8 准备可审核证据包

建议最终提交材料包含：

```text
docs/
  architecture_scoring_review.md
  scoring_alignment.md
  role_strategy_playbook.md
  information_isolation_tests.md
  evaluation_methodology.md
  bad_case_report_sample.md
  leaderboard_sample.md

demo/
  demo_script.md
  demo_video.mp4
  screenshots/
    replay_view.png
    decision_trace.png
    counterfactual_report.png
    leaderboard.png

tests/
  engine_rule_tests.md
  visibility_tests.md
  replay_determinism_tests.md
  evolution_ab_tests.md
```

---

## 7. 最终建议

当前架构已经不是“能不能做出来”的问题，而是“如何让评委相信它真的有效”的问题。

需要弱化的内容：

- 过多人格化包装；
- 过多模块名堆叠；
- 没有数据支撑的漂亮指标；
- 对 Track B 和 Track C 的并列叙述。

需要强化的内容：

- 一局真实对局的完整回放；
- 一个明确 bad case 的自动复盘；
- 一次反事实推演；
- 一个 Agent 版本提升的 Leaderboard；
- 一个信息隔离测试报告；
- 一个可运行、可复现、可审核的 demo。

推荐最终申报定位：

> **主线：AI 狼人杀多智能体评测 + 复盘系统。**  
> **亮点：反事实推演 + 级联评分 + 策略知识回流 + 轻量自进化。**

这个定位最稳，也最容易对应评分标准。