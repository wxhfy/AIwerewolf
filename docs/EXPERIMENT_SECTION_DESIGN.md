# 展示/论文后半截实验部分设计

> 目标：用一组可复现实验证明 AI Werewolf 的系统架构、Agent 框架、角色化 Agent 设计，以及 Track B / Track C 的合理性和优越性。
>
> 口径：正式实验统一使用火山引擎 v4flash 路线，不使用 pro 系列模型。若本地 `.env` 的 provider 名称不同，以实际可用的 v4flash endpoint 为准，但报告中只写清 provider、model、日期、commit 和实验 ID，不写 API Key。
>
> 检索日期：2026-06-08。

## 1. 实验叙事主线

论文/展示后半截建议围绕四个可检验主张展开，而不是堆功能截图。

| 主张 | 要证明什么 | 核心实验 | 通过标准 |
|---|---|---|---|
| C1 架构有效 | 系统不是 prompt demo，而是完整 Play -> Review -> Evolve 闭环 | E0 架构与安全门控实验 | 完成率高，fallback/invalid/info leak 为 0，日志和复盘可追溯 |
| C2 Agent 设计有效 | 角色化认知 Agent 优于普通 ReAct/单 prompt 框架 | E1 framework ablation，E2 role/persona/coordination audit | `cognitive_full` 在 paired seeds 上胜率或过程分高于 `basic_react`，且角色行为差异可解释 |
| C3 Track B 合理且非冗余 | Track B 不只是胜负统计，能区分模型/agent 版本并稳定定位好坏决策 | E3 Track B discrimination + consistency | leaderboard 可区分版本；复盘一致性、证据覆盖、角色归一化结果成立 |
| C4 Track C 合理且非冗余 | 当前 runtime 检索回流能把复盘经验安全带入下一局；Wiki/Hermes 增量层提供长期知识编译和候选策略验证路径 | E4 Track C ablation + B->C funnel | `trackc_only` 或 `cognitive_full` 相对关闭 Track C 的组有正向 delta；安全过滤通过；Wiki/Hermes 以候选策略验证结果补充 |

展示时建议把结论写成：

> 在同一 v4flash 模型、同一 seed、同一角色配置下，普通 ReAct baseline、只开 anti-pattern、只开 Track C、完整 cognitive framework 形成一组逐步增强的对照。若完整框架在角色归一化过程分、胜率、知识命中率和错误率上同时优于 baseline，就能说明 B/C Track 不是冗余设计，而是在复盘分析、解释和 runtime 策略回流层各自提供增益；Wiki/Hermes 增量层则用后续 candidate patch 验证结果补充长期进化证据。

本项目实验输出包含两张 leaderboard：

| Leaderboard | 输出文件 | 用途 |
|---|---|---|
| Track B 原始 leaderboard | `leaderboard.json` | 展示复盘分析系统能区分不同模型/Agent/framework 版本 |
| Architecture evidence leaderboard | `architecture_evidence_leaderboard.json` / `architecture_evidence_leaderboard.csv` | 按 Agent、协作、工程、B/C 闭环整理架构证据 |

Architecture evidence leaderboard 的定位是展示层：它把同一组实验结果整理成架构证据，而不是替代 Track B 原始结果。每一行同时保留原始 evidence signals，包括胜率、角色归一化过程分、分角色胜率、知识命中率、fallback、invalid 和 bootstrap 稳定性。

## 2. 前沿指标依据与本项目映射

| 外部依据 | 关键指标/观点 | 本项目对应指标 |
|---|---|---|
| AIWolf Protocol Division | 以总体胜率和分角色胜率排名，避免只看单一身份结果 | `win_rate`、`role_win_rates`、macro/micro role win rate |
| AIWolf Natural Language Division | 评价自然表达、上下文一致、无矛盾、发言与投票/攻击/查验一致、角色一致性 | `speech_score`、speech-action coherence、contradiction rate、persona consistency |
| AIWolfDial 2025 | 自然语言狼人杀继续使用宏/微/分角色胜率，并引入 LLM review 和人工评价一致性 | Track B judge agreement、rank stability、human pairwise agreement |
| Werewolf Arena | 竞技式多模型对战，强调 deception、deduction、persuasion 和 arena-style comparison | `--axis model` / `--axis framework` leaderboard，投票影响力、发言策略质量 |
| Mini-Mafia | 将社交推理拆成 deception、detection、disclosure 三类能力 | 狼人欺骗、好人识别、预言家信息披露指标 |
| WOLF | 语句级 deception production/detection、长期 suspicion/trust dynamics | speech act audit、deception taxonomy、trust/suspicion 曲线 |
| Strategy Bench | 将 deception index 和 detection index 分开展示，并跨游戏做 normalized ranking | wolf-side deception index、village-side detection index |

正式展示引用：

- AIWolf 2022 Protocol Division 结果页列出 `win_rate` 和各角色胜率：https://aiwolf.org/en/archives/2873
- AIWolf Natural Language Division 评价标准包含自然、上下文、一致性、行动-对话一致：https://aiwolf.org/en/4th-international-aiwolf-contest
- Werewolf Arena 将狼人杀作为 LLM deception/deduction/persuasion 竞技 benchmark：https://arxiv.org/abs/2407.13943
- Mini-Mafia 用 deception / disclosure / detection 三参数解释胜率：https://arxiv.org/abs/2509.23023
- WOLF 用语句级 deception taxonomy 和 suspicion dynamics 评价狼人杀多智能体：https://arxiv.org/abs/2512.09187
- Strategy Bench 展示 deception/detection index：https://strategy.freysa.ai/

## 3. 统一实验设置

| 项 | 正式设置 |
|---|---|
| 模型 | v4flash only |
| 对局人数 | 主实验 7P；泛化实验可补 9P/12P |
| seeds | 主实验每条件至少 20 个 paired seeds；论文级更稳建议 50 个 |
| 角色配置 | 使用 `get_role_configuration(player_count)`，每组 seed 保持一致 |
| fallback | 正式结果要求 `fallback_count=0` |
| invalid action | 正式结果要求 `invalid_count=0` 或单独列为 failed run |
| 信息隔离 | 每轮实验前后跑 `scripts/verify_visibility_strict.py` |
| 数据记录 | 保存 output dir、commit hash、provider/model、start/end time、framework、seed、role distribution |
| 排除规则 | crash、fallback、invalid、API timeout 不静默删除，进入 failure table |

推荐正式模型池：

```bash
export EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash"
```

如果你的火山引擎 endpoint 在项目里映射为 `doubao` provider，则使用实际 endpoint，避免写死不可用的模型别名：

```bash
export EXPERIMENT_MODEL_POOL="doubao:${DOUBAO_ENDPOINT}"
```

不要在正式实验里混入 fake、heuristic、dry-run 或其他模型族。若要展示 leaderboard 区分模型，优先写成“区分 agent/framework 版本”；只有在确认两个 v4flash endpoint 都是真实可用且可解释时，才做 endpoint variant 对比。

## 4. 实验 E0：架构与安全门控

### 目标

证明系统具备完整工程闭环：能稳定完成真实 LLM 对局，Agent 只接收合法视图，Track B/C 后处理能落库和导出，前端不是静态假图。

### 命令

```bash
python scripts/verify_visibility_strict.py
_TEST_ALLOW_FAKE_LLM=true LLM_PROVIDER=fake python -m pytest tests/test_api.py tests/test_cognitive_offline.py -q
cd frontend && npm run build
```

正式 LLM 环境可补：

```bash
export EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash"
python scripts/run_full_llm_pipeline.py --seeds 3001 3002 3003
```

### 指标

| 指标 | 含义 | 展示方式 |
|---|---|---|
| completed_games / requested_games | 真实可运行性 | gate table |
| fallback_count | LLM 失败是否被静默替代 | 必须为 0 |
| invalid_action_count | Agent 输出是否被引擎强行兜底 | 必须为 0 或列为失败 |
| info_leak_count | private 信息是否进入公开视图或 Track C | 必须为 0 |
| review_export_success | Track B 报告是否可导出 | pass/fail |
| knowledge_docs_created | Track C 是否能抽取 candidate lesson | count |

### 图表

1. Architecture gate table：DB / Engine / Agent / Visibility / Track B / Track C / Frontend。
2. Play -> Evaluate -> Evolve 数据链图：GameEvent -> AgentDecision -> PublishedReview -> StrategyKnowledgeDoc -> StrategyRetriever，并在旁路标注 Wiki/Hermes 增量层。
3. 信息隔离 diff：同一阶段主持视角、狼视角、村民视角字段差异。

### 结论模板

> E0 不直接证明 Agent 更强，但证明实验平台可信：正式样本中没有 fallback、invalid action 和信息泄露，因此后续胜率、过程分和知识回流差异可以归因于 framework/Agent 配置，而不是系统兜底或数据泄露。

## 5. 实验 E1：框架优越性主实验

### 目标

回答展示里最重要的问题：普通 ReAct/单 prompt 框架和我们完整 cognitive framework 谁更强。

### 对照组

| 组名 | 配置 | 用途 |
|---|---|---|
| `basic_react` | 关闭 Track C、anti-pattern、reflection；retrieval=`global_only` | 普通 ReAct/基础 LLM baseline |
| `role_guarded_react` | 只开角色 anti-pattern；关闭 Track C/reflection | 对齐“角色约束/guarded agent”范式，验证 Agent 角色设计贡献 |
| `rag_react` | 只开 Track C 策略检索/注入；关闭 anti-pattern/reflection | 对齐 RAG/ReAct Agent，验证检索回流贡献 |
| `reflexion_react` | 只开赛后反思写入；关闭 runtime Track C/anti-pattern | 对齐 Reflexion，验证外循环反思不是 runtime 检索的替代品 |
| `rag_reflexion` | Track C 检索 + reflection；关闭 anti-pattern | 对齐 RAG + Reflexion，验证检索/反思组合贡献 |
| `full_cognitive` | Track C + anti-pattern + reflection + hybrid retrieval | 我们完整框架：Role-guarded RAG + Reflexion |

兼容旧实验名：`anti_only` = `role_guarded_react`，`trackc_only` = `rag_react`，`cognitive_full` = `full_cognitive`。论文里建议用新名字展示，避免把 `anti_only` 误解成独立于 Agent 设计之外的模块。

### 命令

```bash
export EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash"
python scripts/track_bc_leaderboard_experiment.py \
  --axis framework \
  --frameworks basic_react,role_guarded_react,rag_react,reflexion_react,rag_reflexion,full_cognitive \
  --games 20 \
  --start-seed 4101 \
  --player-count 7 \
  --max-days 5 \
  --output-dir outputs/track_bc_framework_v4flash_20
```

预算足够时补 50 seeds：

```bash
python scripts/track_bc_leaderboard_experiment.py \
  --axis framework \
  --frameworks basic_react,role_guarded_react,rag_react,reflexion_react,rag_reflexion,full_cognitive \
  --games 50 \
  --start-seed 5101 \
  --player-count 7 \
  --max-days 5 \
  --output-dir outputs/track_bc_framework_v4flash_50
```

### 主指标

| 指标 | 说明 | 为什么能证明框架 |
|---|---|---|
| win_rate | 阵营胜率 | 最直观 outcome，但不能单独使用 |
| adjusted_final_score | Track B 角色归一化过程分 | 过滤角色强弱和偶然胜负噪声 |
| macro_role_win_rate | 各角色平均胜率 | 防止只靠强势角色取胜 |
| role_distribution_audit | 每组角色分布 | 证明对照公平 |
| paired_delta | 同 seed 下 candidate - baseline | 支持因果对比 |
| bootstrap CI / rank stability | 置信区间和排序稳定性 | 防止小样本误判 |
| fallback/invalid/knowledge_hit_rate | 运行质量和策略使用 | 证明不是靠兜底取胜 |

### Architecture Evidence Leaderboard 映射

`scripts/track_bc_leaderboard_experiment.py` 会额外生成 `architecture_evidence_leaderboard.json/csv`。它把实验结果按架构证据组织，方便解释“为什么这个设计比普通方法更强”：

| 架构维度 | 实验信号 |
|---|---|
| 单 Agent 决策能力 | adjusted result、vote/speech/skill indicators、核心角色覆盖、fallback/invalid health |
| 多 Agent 协作能力 | macro role win rate、win rate、vote/skill indicators、狼人协作与阵营行为 |
| 工程闭环完整性 | completion rate、fallback/invalid health、role distribution audit、seat samples |
| 复盘与知识回流 | Track B 排名/区分度、knowledge hit rate、paired delta、bootstrap rank stability |

展示时把 Architecture evidence leaderboard 放在 Track B leaderboard 后面。Track B 表回答“系统是否能复盘分析和区分版本”，Architecture evidence 表回答“这些结果如何支撑架构优势”。

### 展示图表

1. Framework leaderboard bar：x=`basic_react/role_guarded_react/rag_react/reflexion_react/rag_reflexion/full_cognitive`，y=`adjusted_final_score`。
2. Paired seed delta slope：每个 seed 从 baseline 到 full 的变化。
3. Role-normalized radar：vote/speech/skill/survival/deception/detection。
4. Reliability strip：bootstrap CI + rank stability。

### 通过标准

架构展示建议满足至少三条：

- `full_cognitive` 的 adjusted_final_score 高于 `basic_react`。
- `full_cognitive` 的 paired_delta 为正，bootstrap CI 不完全偏负。
- `full_cognitive` 的 fallback/invalid 不高于 baseline。
- `rag_react` 相对 `basic_react` 有正向过程分、知识命中收益或检索质量收益。
- `role_guarded_react` 能降低明显坏案例、非法行为或角色反模式。
- `rag_reflexion` 优于 `rag_react` 或至少提高知识写入/复用指标，证明反思外循环的补充价值。

## 6. 实验 E2：Agent 设计有效性

### 目标

证明 Agent 不是同质化 LLM bot，而是具备角色目标、记忆、社交判断、工具调用和狼人团队协作。

### 子实验 E2.1：角色行为差异

输入：E1 的 `game_runs.jsonl` 和 Track B player scores。

指标：

| 指标 | 计算方式 | 解释 |
|---|---|---|
| role_task_score by role | 按 Villager/Seer/Witch/Hunter/Werewolf 聚合 | 不同角色是否完成不同任务 |
| speech profile distance | 不同角色发言 act 分布的 JS divergence | 是否真的有角色化发言 |
| vote precision by role | 票型命中 wolf 或保护好人阵营的比例 | 推理质量 |
| skill useful use rate | 预言家查验、女巫救/毒、守卫守护等有效使用率 | 技能角色质量 |
| wolf deception score | 狼人发言与投票是否成功降低怀疑 | 狼队伪装能力 |

图表：

- 每角色 KPI radar。
- 角色发言/投票行为热力图。
- 预言家信息披露 timeline。

### 子实验 E2.2：记忆与社交判断

指标：

| 指标 | 来源 | 展示 |
|---|---|---|
| memory_update_count | AgentDecision metadata / tool_trace | 每局趋势 |
| suspicion_shift_accuracy | 发言后怀疑对象是否向真实狼人收敛 | trust/suspicion curve |
| vote_after_suspicion_alignment | 公开怀疑与实际投票一致率 | coherence bar |
| self_consistency | 同一 Agent 的发言、推理、投票是否互相矛盾 | contradiction rate |

可选命令：

```bash
python scripts/analyze_score_distributions.py
python scripts/evaluate_track_b_vnext.py
```

### 子实验 E2.3：狼人团队协作

指标：

| 指标 | 说明 |
|---|---|
| wolf_attack_consensus_rate | 狼队夜间刀口一致程度 |
| wolf_cover_consistency | 狼人白天互保/切割是否与团队策略一致 |
| wolf_vote_split_control | 狼队投票分散是否降低连坐风险 |
| wolf_survival_days | 狼人平均存活天数 |

展示结论：

> 如果狼人组在 `cognitive_full` 下更少出现无意义互踩、刀口分裂和发言-投票矛盾，就能证明 Agent 设计中的 WolfTeamView、Memory、Planner 和 role-specific prompt 带来了多智能体协作收益。

## 7. 实验 E3：Track B 复盘分析有效性与一致性

### 目标

证明 Track B 不是冗余的“赛后文本总结”，而是一个能区分 Agent 版本、定位关键错误、稳定复现决策质量指标的复盘分析模块。

### E3.1 Leaderboard Discrimination

使用 E1 输出即可。若 `leaderboard_summary.can_distinguish=true`，说明 Track B leaderboard 能区分不同 Agent/framework 版本。

正式报告展示：

| 字段 | 解释 |
|---|---|
| rank | framework/version 排名 |
| adjusted_final_score | 主要过程分 |
| win_rate | 辅助 outcome |
| role-normalized score | 角色归一化 |
| evidence coverage | 每个判断是否有事件引用 |
| paired_delta | 同 seed 差异 |

### E3.2 复盘一致性

命令：

```bash
python scripts/evaluate_track_b_vnext.py
python scripts/evaluate_human_pairwise_agreement.py
```

指标：

| 指标 | 建议阈值 | 含义 |
|---|---:|---|
| judge_agreement | 越高越好，正式报告写实际值 | 多路 LLM 复核内部一致性 |
| Spearman/Kendall rank corr | > 0.6 可作为展示级证据 | leaderboard 重跑排序稳定 |
| mean absolute score diff | 越低越好 | 同一 replay 多次复盘结果漂移 |
| human pairwise agreement | 报告实际值，不夸大 | 与人工偏好一致程度 |
| evidence_ref_coverage | 目标 > 0.9 | 复盘结论是否有日志证据 |

### E3.3 决策解释能力

指标：

| 指标 | 对应展示 |
|---|---|
| bad_case_count | “Track B 能找出关键失误” |
| counterfactual_count | “Track B 能给出替代行动” |
| turning_point_count | “Track B 能定位转折点” |
| speech_action_contradiction_rate | “Track B 不是只看胜负” |
| role_specific_mistake_count | “Track B 懂角色任务” |

### 图表

1. Track B leaderboard：版本区分。
2. Review agreement boxplot：一致性。
3. Bad case waterfall：失误 -> 影响 -> counterfactual。
4. Evidence coverage bar：复盘证据链完整性。

### 结论模板

> Track B 的价值不在于替代胜率，而在于解释胜率。它能在胜负相同的对局中区分发言、投票和技能质量，并把错误转成带证据的 bad case / counterfactual，为 Track C 提供可学习输入。

## 8. 实验 E4：Track C 非冗余性与自进化收益

### 目标

证明 Track C 不是“多写一个知识库”，而是能把 Track B 复盘转成 runtime 可检索策略；Wiki/Hermes 增量层则负责把复盘、策略文档和使用反馈编译成长期策略共识，并通过外循环验证候选策略。

### E4.1 Track C 开关对照

从 E1 中取这两个对比：

| 对比 | 证明 |
|---|---|
| `basic_react` vs `trackc_only` | 单独开启 Track C 是否有收益 |
| `anti_only` vs `cognitive_full` | 在同样静态护栏下，Track C 是否额外有收益 |

核心指标：

| 指标 | 解释 |
|---|---|
| knowledge_hit_rate | 策略知识是否真的进入决策 |
| strategy_adoption_rate | Agent 输出是否采纳检索策略 |
| adjusted_final_score_delta | 知识回流是否改善过程质量 |
| bad_case_rate_delta | 是否减少同类失误 |
| role_task_score_delta | 是否特别改善对应角色任务 |
| info_leak_count | Track C 是否泄露当前局 private 信息 |

### E4.2 B -> C 漏斗

命令：

```bash
python scripts/promote.py --mode quality
python scripts/promote.py --mode feedback
```

指标：

| 漏斗阶段 | 指标 |
|---|---|
| Track B outputs | highlights, mistakes, counterfactuals, strategy suggestions |
| Candidate extraction | knowledge_docs_created, sanitized_count, rejected_count |
| Safety filter | private-info reject count, absolute-strategy reject count |
| Promotion | candidate -> active promotion rate |
| Usage | retrieval hit, adoption, helpful feedback |
| Outcome | paired score/win delta |

展示图表：

1. B->C conversion funnel。
2. Knowledge status Sankey：candidate / active / deprecated。
3. Knowledge usage scatter：hit rate vs adjusted score。
4. 同类 bad case 复发率变化。

### E4.3 检索策略对照

命令：

```bash
python scripts/evaluate_retrieval_policies.py
python scripts/evaluate_retrieval_policies_llm_judge.py
python scripts/run_retrieval_policy_ablation.py --games 20
```

对照：

- `global_only`
- `same_role_all_mbti`
- `same_role_same_mbti`
- `hybrid_role_mbti_global`
- `hybrid_role_alignment_phase`

指标：

- P@3 / nDCG@5 / coverage。
- retrieval latency。
- online adjusted_final_score。
- knowledge_hit_rate。
- candidate leakage count。

结论模板：

> 如果 hybrid role/MBTI/global retrieval 在 coverage 和在线过程分上优于 global_only，同时没有 candidate/private leakage，说明 Track C 的知识作用不是“塞更多文本”，而是经过角色、阶段、人格和安全过滤后的结构化策略回流。

## 9. 实验 E5：Track B/C 联合证明

### 目标

把 B 和 C 的分工讲清楚：B 负责“复盘与归因”，C 负责“抽象与回流”。两者不是重复模块。

### 联合分析

| 问题 | 分析方法 | 支撑结论 |
|---|---|---|
| B 能否区分版本 | E1 leaderboard + E3 rank stability | B 是复盘层 |
| B 的错误是否能转成 C 的知识 | bad cases -> candidate docs 追踪 | B 是 C 的上游 |
| C 是否真的被 Agent 使用 | tool_trace / retrieved_count / knowledge_hit_rate | C 进入在线决策 |
| C 是否改善 B 的后续决策质量指标 | paired seed quality delta | C 反哺 B 指标 |
| C 是否安全 | private evidence redaction + unsafe reject | C 不污染信息隔离 |

### 关键图

一张闭环证据图即可：

```text
AgentDecision
  -> Track B per-step score
  -> bad case / counterfactual / strategy suggestion
  -> Track C candidate/runtime knowledge
  -> safety filter + promotion
  -> StrategyRetriever hit
  -> next-game AgentDecision
  -> improved Track B score

Optional offline layer:
  PublishedReview / strategy docs / usage feedback
    -> Track C Wiki
    -> Hermes candidate patch
    -> candidate StrategyKnowledgeDoc
```

每条箭头旁边放真实计数：`N decisions`、`N bad cases`、`N candidates`、`N active`、`knowledge_hit_rate`、`score_delta`。

## 10. 统计方法

| 分析 | 方法 |
|---|---|
| 胜率差异 | paired seed difference；Wilson CI 或 bootstrap CI |
| 过程分差异 | paired delta mean、bootstrap CI、Cliff's delta |
| leaderboard 稳定性 | seed bootstrap rank stability、Kendall tau |
| 多组比较 | Holm-Bonferroni 修正；展示级可写为探索性分析 |
| 角色公平 | role distribution audit + role-normalized score |
| 一致性 | test-retest review std、Spearman/Kendall rank corr、human/LLM agreement |
| 异常处理 | failed runs 单独统计，不静默丢弃 |

论文里避免写“显著提升”除非 CI 和检验支持。展示里可以写“在 20 seeds 上观察到稳定正向趋势”。

## 11. 结果文件与图表清单

主实验会产出：

| 文件 | 用途 |
|---|---|
| `outputs/track_bc_framework_v4flash_20/summary.json` | 总结指标 |
| `outputs/track_bc_framework_v4flash_20/leaderboard.json` | leaderboard 表 |
| `outputs/track_bc_framework_v4flash_20/architecture_evidence_leaderboard.json` | 按架构证据整理后的 leaderboard |
| `outputs/track_bc_framework_v4flash_20/architecture_evidence_leaderboard.csv` | 可直接画展示柱状图 |
| `outputs/track_bc_framework_v4flash_20/group_results.csv` | 画图表 |
| `outputs/track_bc_framework_v4flash_20/game_runs.jsonl` | 逐局审计 |
| `outputs/track_bc_framework_v4flash_20/academic_report.md` | 展示/论文直接引用草稿 |

建议图表顺序：

1. 实验矩阵：四个 claim 对应四组实验。
2. 架构安全门控：fallback/invalid/info leak 全 0。
3. Framework ablation leaderboard：`basic_react` 到 `cognitive_full`。
4. Paired seed delta：每个 seed 的增益线。
5. Role-normalized performance：分角色胜率和过程分。
6. Agent behavior radar：vote/speech/skill/survival/deception/detection。
7. Track B consistency：review agreement + rank stability。
8. Track B bad-case evidence：一条真实错误的证据链。
9. Track C funnel：B 输出 -> LLM Wiki -> Hermes candidate -> active -> retrieval hit。
10. Track C A/B：关闭/开启 Track C 的 quality delta。
11. Safety/reliability：private leakage、candidate leakage、fallback、invalid。
12. Threats to validity：样本量、单模型、角色随机性、LLM API 漂移。

## 12. 论文实验章节写作骨架

### 12.1 Experimental Setup

写清：

- 所有正式对局使用 v4flash。
- 固定 player count、role configuration、start seed、max days。
- 每个 condition 使用同一组 paired seeds。
- 记录 provider/model、代码 commit、输出目录、运行时间。
- 失败对局不删除，列入 failure table。

### 12.2 Baselines and Variants

写四组：

1. `basic_react`：普通 LLM/ReAct baseline。
2. `anti_only`：只加静态角色反模式约束。
3. `trackc_only`：只加 Track C 策略检索。
4. `cognitive_full`：完整架构。

### 12.3 Metrics

分四类写：

- Outcome：win rate、role win rate。
- Process：Track B adjusted result、vote/speech/skill/survival。
- Social deduction：deception、detection、disclosure、speech-action coherence。
- Reliability/safety：bootstrap、rank stability、judge agreement、fallback、invalid、info leak。

### 12.4 Main Results

用 E1 表和图说明完整框架强于 baseline。不要只放胜率，一定同时放 role-normalized score 和 safety gates。

### 12.5 Agent Design Analysis

用 E2 展示角色行为差异、狼人协作、记忆/怀疑曲线。这里是证明 Agent 设计的核心。

### 12.6 Track B Validity

用 E3 展示 leaderboard 能区分版本、决策质量指标一致、有 evidence refs、有 bad case/counterfactual。

### 12.7 Track C Evolution

用 E4 展示知识抽取漏斗、检索命中、开启 Track C 后的 paired delta 和安全过滤。

### 12.8 Ablation and Robustness

用 7P 主实验，补 9P/12P 或 retrieval policy ablation。若时间不够，写成 appendix/future validation。

### 12.9 Limitations

必须诚实写：

- 20 seeds 是展示级证据，不等价于大规模竞赛结论。
- 单一 v4flash 模型不能证明所有模型通用。
- LLM API 有时间漂移，应冻结日期、模型版本和输出文件。
- Track B 的人工一致性若样本小，只能作为 sanity check。

## 13. 最小可交付实验包

如果时间只够跑一组，优先跑这一条：

```bash
export EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash"
python scripts/track_bc_leaderboard_experiment.py \
  --axis framework \
  --frameworks basic_react,anti_only,trackc_only,cognitive_full \
  --games 20 \
  --start-seed 4101 \
  --player-count 7 \
  --max-days 5 \
  --output-dir outputs/track_bc_framework_v4flash_20
```

如果本机火山 endpoint 只通过 `DOUBAO_ENDPOINT` 暴露，则把第一行替换为：

```bash
export EXPERIMENT_MODEL_POOL="doubao:${DOUBAO_ENDPOINT}"
```

然后补三条校验：

```bash
python scripts/verify_visibility_strict.py
python -m pytest tests/test_track_bc_leaderboard_experiment.py -q
ruff check scripts/track_bc_leaderboard_experiment.py tests/test_track_bc_leaderboard_experiment.py
```

这一组足够支撑展示中的核心图：

- 普通框架 vs 我们框架的胜率/过程分对比。
- Track B leaderboard 可区分版本。
- Architecture evidence leaderboard 对齐 Agent 决策、多 Agent 协作、工程闭环、复盘与知识回流四个架构维度。
- Track C knowledge hit 与 quality delta。
- role distribution 和 bootstrap reliability。

## 14. 架构答辩时的表达方式

推荐说法：

> 我们没有只展示一个能玩的狼人杀 demo，而是把系统拆成可检验的四层：规则引擎和信息隔离保证实验平台可信；CognitiveAgent 通过角色身份、记忆、社交判断和工具检索形成差异化策略；Track B 把胜负拆成逐步可解释复盘；Track C 把 Track B 的复盘结果编译为 LLM Wiki 策略知识，经 Hermes-style 外循环验证后变成下一局可检索的 runtime 策略。实验上，我们用同一 v4flash 模型和 paired seeds 比较 basic ReAct、anti-only、Track-C-only 和 cognitive-full 四组，报告胜率、角色归一化过程分、分角色胜率、leaderboard 区分度、知识命中率、bootstrap 稳定性以及信息泄露/兜底失败门控。因此 B/C 不是冗余模块，而是分别承担“可解释复盘”和“安全回流提升”的职责。

不建议说：

- “Track C 显著提升胜率”，除非真实结果和统计检验支持。
- “我们超过所有模型”，除非跑了多模型 arena。
- “绝对无泄露”，更稳妥写“本实验的 strict visibility checks 未发现泄露”。
- “人工偏好高度一致”，除非 `evaluate_human_pairwise_agreement.py` 已有足够样本。
