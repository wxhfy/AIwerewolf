# Track C 策略检索有效性量化报告

生成时间：2026-06-09  
本次实验输出：`outputs/retrieval_effectiveness_current/`  
评估脚本：`scripts/evaluate_retrieval_policies.py`

## 1. 当前检索方式

当前 Track C 策略检索主路径是 `StrategyRetriever`，代码入口位于 `backend/agents/cognitive/retrieval_prod.py`，Agent 工具入口为 `backend/agents/cognitive/tools.py` 中的 `search_strategies`。

整体流程如下：

```text
Agent 当前视角 / PlayerView
  -> Observation
  -> AgentLoop 判断是否需要策略
  -> search_strategies(keywords, retrieval_policy, role, phase, mbti, alignment)
  -> StrategyRetriever.search_with_keywords()
  -> 倒排索引 keyword grep
  -> 候选不足时 BM25 full-text fallback
  -> RetrievalPolicy 分桶过滤
  -> 质量阈值与安全过滤
  -> top-k 策略进入 Agent Prompt 的 Strategy 层
```

该方案不是向量数据库检索，而是面向当前知识库规模的轻量检索：PostgreSQL 中的 active 策略文档会被加载到内存，构建倒排索引和 BM25 索引。Agent 提供关键词后，系统先在 `situation`、`strategy`、`rationale` 等字段上做关键词匹配，再按角色、MBTI、阶段、阵营和质量进行过滤与排序。

单个角色检索的核心逻辑是 `RetrievalPolicy`：

| 策略 | 单角色检索方式 | 主要特点 |
|---|---|---|
| `global_only` | 只取 `role_scope` 为 global/any/空的策略 | 全局兜底，但角色针对性弱 |
| `self_mbti_only` | 只取 MBTI 匹配或无 MBTI 限定的策略 | 个性化强，但可能跨角色 |
| `same_role_all_mbti` | 只取当前角色策略，不限制 MBTI | 角色匹配最稳定 |
| `same_role_same_mbti` | 当前角色 + 当前 MBTI 同时匹配 | 最窄，容易查空 |
| `hybrid_role_mbti_global` | 当前角色同 MBTI -> 当前角色全 MBTI -> global | 当前默认推荐，兼顾角色、人格和兜底 |
| `hybrid_role_alignment_phase` | 当前角色同 MBTI 同阶段 -> 当前角色 -> 同阵营 -> global | 更细粒度，但延迟更高 |

严格模式下，策略进入运行时还会经过 confidence、visibility、current-game leak、applicability/status 四类安全过滤，避免 candidate 池污染 active 检索和当前局私密信息泄漏。

## 2. 量化指标口径

检索类系统通常用排名质量、覆盖率、召回能力、延迟和下游有效性共同衡量。传统信息检索常用 Precision@K、Recall@K、MRR、MAP、nDCG 等指标；Stanford IR Book 将排名检索评估与 Precision@K、R-precision、MAP 等指标联系起来。BEIR 这类现代检索基准也强调跨任务、多数据集和 nDCG 等排名指标。RAG/Agent 场景还需要关注 context precision、context recall、faithfulness、工具调用使用率和下游任务质量。

参考资料：

- Stanford IR Book, Evaluation of ranked retrieval results: https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-ranked-retrieval-results-1.html
- BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models: https://arxiv.org/abs/2104.08663
- Ragas available metrics: https://docs.ragas.io/en/v0.4.2/concepts/metrics/available_metrics/

本项目当前采用如下指标：

| 指标 | 含义 | 本项目用途 |
|---|---|---|
| P@1 | 第一条策略是否相关 | 衡量首条注入是否可靠 |
| P@3 | top-3 中相关策略占比 | 衡量 Prompt 注入策略的精度 |
| Effective@3 | top-3 中至少有一条相关策略的查询比例 | 更接近“这次检索是否可用”的有效率 |
| MRR | 第一条相关策略出现位置的倒数均值 | 衡量相关策略是否排在前面 |
| nDCG@5 | 考虑相关性等级和排名折损 | 衡量整体排序质量 |
| Coverage | 非空检索比例 | 衡量策略是否查得到 |
| RoleMatch | top-5 结果角色匹配率 | 衡量单角色检索纯度 |
| MBTIMatch | top-5 结果 MBTI 匹配率 | 衡量人格定制程度 |
| PhaseMatch | top-5 结果阶段匹配率 | 衡量情境贴合度 |
| AvgResultsPerQuery | 每个查询平均返回策略条数 | 衡量 top-k 是否被充分填充 |
| Top5FillRate | top-5 结果槽位填充率 | 防止“少量精确命中”被误读成稳定检索 |
| BucketShare | top-5 结果来自各优先桶的比例 | 解释单角色检索是精确命中还是兜底命中 |
| CandidateLeak | candidate 策略泄漏数 | 衡量 Track C 安全边界 |
| LatencyP95ms | P95 检索延迟 | 衡量运行时成本 |
| Helpful/Used | 已使用策略中被反馈为 helpful 的比例 | 衡量运行时有效反馈 |

说明：本次离线实验使用脚本内的规则弱标注，相关性分为 0-3。该标注适合比较不同检索策略的相对效果，但不能替代人工标注或 LLM judge 的最终评估。

## 3. 本次离线对比实验

数据来源：`outputs/retrieval_effectiveness_current/results.csv`、`outputs/retrieval_effectiveness_current/results.json`。  
Query set：26 个固定查询，覆盖 6 类角色、4 类 MBTI 和典型发言/投票/夜间行动场景。  
检索知识库：本次脚本实际加载 374 条 active 策略文档。  
Baseline：`global_only`。

| Rank | Policy | OfflineScore | P@1 | P@3 | Effective@3 | nDCG@5 | Coverage | RoleMatch | MBTIMatch | Top5Fill | CandidateLeak | P95 延迟 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `hybrid_role_mbti_global` | 0.6991 | 0.2308 | 0.2564 | 0.5000 | 0.9567 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 | 34.29ms |
| 2 | `hybrid_role_alignment_phase` | 0.6982 | 0.2308 | 0.2564 | 0.5000 | 0.9576 | 1.0000 | 0.9923 | 1.0000 | 1.0000 | 0 | 18.75ms |
| 3 | `same_role_all_mbti` | 0.6850 | 0.1923 | 0.2179 | 0.4615 | 0.9566 | 1.0000 | 1.0000 | 0.9000 | 0.9923 | 0 | 119.28ms |
| 4 | `self_mbti_only` | 0.6179 | 0.0385 | 0.1667 | 0.3846 | 0.9216 | 1.0000 | 0.4769 | 1.0000 | 1.0000 | 0 | 25.97ms |
| 5 | `global_only` | -0.1450 | 0.1154 | 0.1282 | 0.1538 | 0.4938 | 0.5000 | 0.5000 | 0.5000 | 0.2615 | 0 | 19.86ms |
| 6 | `same_role_same_mbti` | -0.3812 | 0.0769 | 0.0769 | 0.0769 | 0.1535 | 0.1538 | 0.1538 | 0.1538 | 0.1000 | 0 | 36.60ms |

本次实验的主要结果：

1. 综合效果最高的是 `hybrid_role_mbti_global`，OfflineScore 为 0.6991。
2. 最高 nDCG@5 是 `hybrid_role_alignment_phase`，为 0.9576；但综合分略低于 `hybrid_role_mbti_global`，且多一层阵营/阶段桶，适合作为后续在线 A/B 候选。
3. 与 `global_only` 相比，默认推荐策略 `hybrid_role_mbti_global` 的 P@3 从 0.1282 提升到 0.2564，Effective@3 从 0.1538 提升到 0.5000，nDCG@5 从 0.4938 提升到 0.9567，Coverage 从 0.5000 提升到 1.0000。
4. `same_role_same_mbti` 虽然看起来最个性化，但 26 个查询中 22 个为空，Coverage 和 Top5Fill 都只有 0.1538，不适合作为默认运行策略。

## 4. 单个角色检索机制与量化

数据来源：`outputs/retrieval_effectiveness_current/per_role_results.csv`、`outputs/retrieval_effectiveness_current/results.json`、`outputs/retrieval_effectiveness_current/per_query_details.jsonl`。

### 4.1 单个角色是如何检索的

单个角色检索不是直接在全库里取最高分，而是把“当前角色上下文”作为过滤和排序条件传入检索器。一次检索会带上：

- `role`：当前玩家角色，例如 Werewolf、Seer、Witch；
- `mbti`：当前玩家人格类型；
- `phase`：当前游戏阶段；
- `alignment`：阵营；
- `action_type`：当前动作类型；
- `keywords`：Agent 在 AgentLoop 中主动给出的搜索关键词。

默认策略 `hybrid_role_mbti_global` 的单角色路径如下：

```text
当前角色 + 当前 MBTI 精确策略
  -> 当前角色通用策略
  -> global / any 通用策略
  -> 质量阈值过滤
  -> top-k 注入 Strategy Prompt
```

这意味着同一个关键词在 Werewolf 和 Seer 身上会进入不同的角色桶。以 `警徽流` 为例，狼人会优先检索狼人悍跳、抢警徽和伪装发言相关策略；预言家会优先检索报验人、警徽流安排和对跳应对策略。只有当前角色策略不足时，系统才会使用 global 兜底。

### 4.2 每个角色的最优策略

| 角色 | 综合分最高 | P@3 最高 | Effective@3 最高 | nDCG@5 最高 |
|---|---|---|---|---|
| Guard | `same_role_all_mbti` | `same_role_all_mbti` | `same_role_all_mbti` | `same_role_all_mbti` |
| Hunter | `same_role_all_mbti` | `self_mbti_only` | `self_mbti_only` | `global_only` |
| Seer | `hybrid_role_mbti_global` | `hybrid_role_mbti_global` | `same_role_all_mbti` | `hybrid_role_mbti_global` |
| Villager | `hybrid_role_mbti_global` | `global_only` | `same_role_all_mbti` | `same_role_all_mbti` |
| Werewolf | `hybrid_role_mbti_global` | `same_role_same_mbti` | `hybrid_role_mbti_global` | `same_role_all_mbti` |
| Witch | `hybrid_role_mbti_global` | `global_only` | `self_mbti_only` | `same_role_all_mbti` |

说明：部分角色查询数较少，单项指标最高不等于可以直接替换默认策略。默认策略选择以综合分、覆盖率、角色匹配率、安全性和稳定性为主。

### 4.3 默认策略在每个角色上的表现

默认策略为 `hybrid_role_mbti_global`。

| 角色 | 查询数 | P@1 | P@3 | Effective@3 | nDCG@5 | Coverage | RoleMatch | MBTIMatch | Top5Fill | Empty |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Guard | 2 | 0.0000 | 0.5000 | 1.0000 | 0.8821 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |
| Hunter | 2 | 0.0000 | 0.5000 | 1.0000 | 0.8785 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |
| Seer | 5 | 0.2000 | 0.3333 | 0.6000 | 0.9544 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |
| Villager | 6 | 0.5000 | 0.2778 | 0.5000 | 0.9780 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |
| Werewolf | 7 | 0.2857 | 0.1429 | 0.2857 | 0.9931 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |
| Witch | 4 | 0.0000 | 0.0833 | 0.2500 | 0.9406 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0 |

### 4.4 单角色检索路径量化

该表解释每个角色默认检索时到底从哪一层取到了策略。RoleBucket 包括“当前角色 + 当前 MBTI 精确策略”和“当前角色通用策略”；GlobalBucket 是全局兜底。

| 角色 | AvgResults | Top5Fill | ExactRoleMBTI | RoleBucket | AlignmentBucket | GlobalBucket | Empty | Bucket Distribution |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Guard | 5.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0 | `same_role_all_mbti:1.00` |
| Hunter | 5.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0 | `same_role_all_mbti:1.00` |
| Seer | 5.00 | 1.00 | 0.20 | 1.00 | 0.00 | 0.00 | 0 | `same_role_all_mbti:0.80; same_role_same_mbti:0.20` |
| Villager | 5.00 | 1.00 | 0.00 | 0.97 | 0.00 | 0.03 | 0 | `same_role_all_mbti:0.97; global:0.03` |
| Werewolf | 5.00 | 1.00 | 0.23 | 1.00 | 0.00 | 0.00 | 0 | `same_role_all_mbti:0.77; same_role_same_mbti:0.23` |
| Witch | 5.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0 | `same_role_all_mbti:1.00` |

### 4.5 单角色知识池规模

数据来源：`outputs/retrieval_effectiveness_current/role_corpus_stats.csv`。

该表统计每个角色在关键词匹配前可用的 active 知识池。`RoleDocs` 表示该角色 active 文档总量，`RoleGeneric` 表示无 MBTI 限定的同角色文档，`RoleMBTISpecific` 表示带 MBTI 限定的同角色文档。`ExactRoleMBTIPoolAvg` 是当前 query set 中精确 `role+MBTI` 池的平均大小；`HybridRolePoolAvg` 是默认混合策略在当前跨 MBTI 关闭设置下可使用的角色池平均大小。

| 角色 | RoleDocs | RoleGeneric | RoleMBTISpecific | ExactRoleMBTIPoolAvg | ExactEmptyQueries | HybridRolePoolAvg | HybridTotalPoolAvg | GlobalGeneric | Doc MBTI Distribution |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Guard | 49 | 38 | 11 | 0.00 | 2 | 38.00 | 73.00 | 35 | `ISTJ:11` |
| Hunter | 39 | 28 | 11 | 0.00 | 2 | 28.00 | 63.00 | 35 | `ESTP:11` |
| Seer | 54 | 37 | 17 | 6.80 | 3 | 43.80 | 78.80 | 35 | `INTJ:17` |
| Villager | 18 | 16 | 2 | 0.00 | 6 | 16.00 | 51.00 | 35 | `INTP:2` |
| Werewolf | 51 | 33 | 18 | 7.71 | 4 | 40.71 | 75.71 | 35 | `INTJ:18` |
| Witch | 42 | 28 | 14 | 0.00 | 4 | 28.00 | 63.00 | 35 | `ISTJ:14` |

这组数据解释了 `same_role_same_mbti` 过窄的原因：当前 active 知识库中的 MBTI 细分文档主要集中在少数 MBTI，例如 Seer/Werewolf 的 INTJ、Witch/Guard 的 ISTJ、Hunter 的 ESTP。默认策略没有直接放弃这些精确知识，而是先查精确桶，再用同角色通用桶和 global 兜底填满 top-k，因此能在保持角色纯度的同时避免空检索。

单角色结论：

1. 默认策略在 6 个角色上均无空检索，Coverage、RoleMatch、MBTIMatch 和 Top5Fill 均为 1.0000，说明它可以稳定为每个角色提供可用策略。
2. 默认策略几乎全部来自角色桶：总 RoleBucketShare 为 0.9923，GlobalBucketShare 只有 0.0077，说明系统主要依赖角色定制策略，而不是泛化兜底。
3. Seer 和 Werewolf 有一部分命中来自精确角色+MBTI 桶，分别为 0.20 和 0.23；Guard、Hunter、Villager、Witch 主要依赖同角色通用策略，后续可补充更多 MBTI 细分卡片。
4. Werewolf 和 Witch 的 P@3 分别为 0.1429 和 0.0833，说明虽然能稳定查到角色策略，但弱标注下 top-3 精度仍偏低；后续应优先补狼人被查杀、悍跳、倒钩、自爆，以及女巫救/毒/跳身份等细分策略。
5. `same_role_same_mbti` 的返回文档都来自精确桶，但 26 个查询中 22 个为空，Coverage 和 Top5Fill 均为 0.1538，因此只能作为补充实验策略，不能作为默认运行策略。

## 5. 运行时反馈与真实对局证据

### 5.1 数据库反馈表

数据来源：PostgreSQL `knowledge_usage_feedback`、`strategy_knowledge_docs`、`players` 全量查询。  
查询时间：2026-06-09。

| 指标 | 数值 |
|---|---:|
| `knowledge_usage_feedback` 总数 | 180707 |
| retrieved | 180707 |
| used | 73388 |
| helpful | 59804 |
| used / retrieved | 40.61% |
| helpful / retrieved | 33.09% |
| helpful / used | 81.49% |
| active 策略文档 | 387 |
| candidate 策略文档 | 193073 |

这说明：在历史反馈表中，并非每条 retrieved 策略都会被实际使用；但一旦进入 used 集合，约 81.49% 被记录为 helpful。需要注意，当前 `score_delta` 平均为 0.0，说明反馈表还没有形成可直接做因果增益分析的分数差字段。

### 5.2 按玩家角色统计的运行时反馈

数据来源：PostgreSQL `knowledge_usage_feedback` join `players`。

| 玩家角色 | retrieved | used | helpful | used_rate | helpful/retrieved | helpful/used |
|---|---:|---:|---:|---:|---:|---:|
| Werewolf | 31812 | 20595 | 16889 | 64.74% | 53.09% | 82.01% |
| Villager | 18051 | 11071 | 8812 | 61.33% | 48.82% | 79.60% |
| Seer | 16968 | 10092 | 7161 | 59.48% | 42.20% | 70.96% |
| Witch | 15828 | 10554 | 9415 | 66.68% | 59.48% | 89.21% |
| Guard | 15201 | 9723 | 8281 | 63.96% | 54.48% | 85.17% |
| Hunter | 14037 | 8984 | 7058 | 64.00% | 50.28% | 78.56% |
| WhiteWolfKing | 3845 | 1745 | 1712 | 45.38% | 44.53% | 98.11% |

在线反馈的角色差异：

1. Witch、Guard 的 helpful/used 较高，分别为 89.21% 和 85.17%，说明被使用的策略反馈质量较好。
2. Seer 的 helpful/used 为 70.96%，低于其他核心角色，后续应优先补充预言家查验、警徽流、对跳和信息发布策略。
3. Werewolf 的 retrieved 和 used 数量最高，说明狼队场景是检索使用最频繁的部分，但离线 P@3 仍偏低，值得继续做狼人细分策略增强。

### 5.3 已有真实对局烟测

数据来源：`docs/experiments/track_c_runtime_fix/` 下的 `group_results.csv`。

| 来源 | Framework | game_id | Adjusted Score | Decision | Fallback | Invalid | Knowledge Hit |
|---|---|---|---:|---:|---:|---:|---:|
| `doubao_smoke_g1/group_results.csv` | `trackc_only` | `70ff46ee-13fa-423f-b41f-9c66f16d9c10` | 66.498571 | 46 | 0 | 0 | 0.913043 |
| `doubao_smoke_g1_conservative_gate/group_results.csv` | `trackc_only` | `3917c9e6-ed88-4a33-a707-3c3fcc657520` | 63.920000 | 50 | 0 | 0 | 0.920000 |
| `doubao_smoke_g1_conservative_baseline_retry/group_results.csv` | `basic_react` | `9f67eda3-8ee1-47a0-83a3-ce83daedf241` | 47.501429 | 34 | 0 | 0 | 0.000000 |
| `doubao_smoke_g1_after_target_guard/group_results.csv` | `basic_react` | `2724db62-7c05-4dfd-bc7d-41b86dc16d95` | 62.508571 | 44 | 0 | 0 | 0.000000 |
| `doubao_smoke_g1_after_target_guard/group_results.csv` | `trackc_only` | `e50783f2-9e66-4a96-9ae3-dd3b1b5794e8` | 47.878571 | 52 | 0 | 0 | 0.826923 |

这些数据说明 Track C 运行时确实能把策略注入到大量决策中，且 conservative gate 后单局 smoke 的 knowledge hit 达到 0.92、fallback 和 invalid 为 0。但这些都是小样本烟测，不能直接写成“Track C 必然提升胜率”的最终结论。

## 6. 可以写入正式报告的结论

| 结论 | 依据 |
|---|---|
| 当前检索不是向量库，而是 PostgreSQL active 策略文档 + 内存倒排索引 + BM25 fallback + RetrievalPolicy 分桶。 | `backend/agents/cognitive/retrieval_prod.py`、`backend/agents/cognitive/tools.py` |
| 默认推荐策略 `hybrid_role_mbti_global` 在本次 26 查询离线实验中综合分最高。 | `outputs/retrieval_effectiveness_current/results.csv` |
| `hybrid_role_mbti_global` 相对 `global_only` 明显提升 P@3、Effective@3、nDCG@5 和 Coverage。 | `outputs/retrieval_effectiveness_current/results.csv` |
| 单角色检索上，默认策略所有角色 Coverage=1.0，RoleMatch=1.0，MBTIMatch=1.0。 | `outputs/retrieval_effectiveness_current/per_role_results.csv` |
| `same_role_same_mbti` 过窄，当前 26 查询中 22 个为空，不适合作为默认策略。 | `outputs/retrieval_effectiveness_current/results.csv` |
| 运行时反馈表中 helpful/used 为 81.49%，说明被实际使用的策略多数被反馈为有帮助。 | PostgreSQL `knowledge_usage_feedback` 全量查询 |

## 7. 暂不能写成最终结论的内容

| 暂不能写的结论 | 原因 | 后续补充方式 |
|---|---|---|
| Track C 显著提升最终胜率 | 当前真实对局对比样本太少，且存在旧版 Track C 跑低的记录 | 跑 20-50 局 paired seeds，比较 Track C vs baseline |
| 某个角色一定适合某个单独策略 | 部分角色查询数只有 2-4 条，小样本波动大 | 扩展每角色 20+ 查询，增加人工/LLM judge |
| helpful/used 可以直接等同真实决策提升率 | 当前反馈表 `score_delta` 为 0.0，缺少逐决策因果差分 | 将 PerStepScorer 分数和 retrieved_doc_ids 逐决策关联 |
| `hybrid_role_alignment_phase` 一定优于默认策略 | nDCG@5 略高，但 P95 延迟更高，综合分略低 | 做在线 A/B，加入延迟、工具调用和最终评分 |

## 8. 后续实验建议

1. 扩充离线 query set：每个核心角色至少 20 个查询，覆盖发言、投票、技能、警徽、被怀疑、对跳、残局等场景。
2. 补 LLM judge 或人工标注：对每条 query 的 top-5 策略打 0-3 分，减少规则弱标注偏差。
3. 运行 paired-seed 对局实验：对比 `global_only`、`same_role_all_mbti`、`hybrid_role_mbti_global`、`hybrid_role_alignment_phase`，至少 20 局。
4. 增加逐决策归因：将 `agent_decisions.retrieved_doc_ids`、`knowledge_usage_feedback` 和 Track B `ScoredStep` 关联，计算每条策略的真实 score_delta。
5. 单角色专项实验：优先补 Werewolf、Witch、Seer，因为离线 P@3 或在线 helpful/used 暴露了更明显优化空间。
