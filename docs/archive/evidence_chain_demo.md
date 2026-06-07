# 证据链展示

答辩展示的核心不是胜率提升的数字，而是这条**从失误到改进的可追溯链路**：

```
某局发言/投票失误
→ PerStepScorer 标出低分 (is_mistake=True, score ≤ 0.30)
→ KnowledgeAbstractor 生成 lesson (situation_pattern + recommended_action)
→ lesson 进入 candidate 池 (暂不污染 active)
→ 人工/规则审核后晋升 active
→ 后续对局 Agent 检索到该策略 (search_strategies 命中)
→ 决策 trace 记录 strategy_id (parsed_action._tool_trace)
→ 对应行为不再犯错 (后续局该 pattern 的 score 提升)
```

## 证据链模板

| 步骤 | 数据来源 | 示例 |
|------|---------|------|
| **Game ID** | `games.id` | `game-abc123` |
| **Player** | `players.name` | `3号-张飞 (Villager)` |
| **Phase** | `agent_decisions.phase` | `DAY_SPEECH` (Day 2 发言阶段) |
| **Observation** | `agent_decisions.observation` | 看到 2 号跳预言家查杀 7 号，4 号对跳预言家发 5 号金水 |
| **Auto-injected Strategies** | `parsed_action._auto_injected_strategies` | `["doc-villager-001", "doc-anti-empty-speech-003"]` |
| **Tool Search Query** | `parsed_action._tool_trace[0].keywords` | `["被查杀应对", "多人对跳预言家", "好人表水"]` |
| **Retrieved Strategy Docs** | `parsed_action._tool_trace[0].result_summary` | `"被查杀时先表水说明身份和逻辑，不要直接反踩；多人对跳时观察双方逻辑一致性判断真预言家"` |
| **Decision** | `agent_decisions.raw_output` | `"我是3号村民张飞，2号和4号都跳了预言家。2号说查杀了7号，但2号昨天发言就有问题...我觉得4号更可信。我投2号。"` |
| **Score** | `evaluations.overall_score` | `0.32` — 被标记为 is_mistake |
| **Score Reason** | `evaluations.evidence` | `["错误归票：2号实际是真预言家，4号是狼人悍跳。村民未正确辨别真假预言家。", "推理链不完整：说2号发言有问题但未具体指出。"]` |
| **Mistake Type** | `scored_steps.mistake_type` | `"wrong_vote"` + `"fabrication"` (声称2号发言有问题但无事实依据) |
| **Generated Lesson** | `strategy_knowledge_docs.content` | `"在多人对跳预言家时，不要仅凭直觉选边。检查：①查验逻辑是否自洽 ②查验信息是否与已知事实一致 ③发言人的过往行为是否一貫。先列出双方的逻辑优劣势，再做判断。"` |
| **Lesson Target Role** | `strategy_knowledge_docs.target_role` | `"global"` (适用于所有好人阵营角色) |
| **Lesson Situation** | `strategy_knowledge_docs.situation_pattern` | `"多人对跳预言家，需要判断真预言家"` |
| **Lesson Status** | `strategy_knowledge_docs.status` | `candidate` |
| **Lesson Confidence** | `strategy_knowledge_docs.confidence_score` | `0.72` (基于单一 source，暂未晋升) |
| **Active Pool Changed?** | snapshot diff | `No` — candidate lesson 未晋升，active 池不变 |
| **Next Game Retrieval** | 后续局 agent_decisions._tool_trace | `"-- 检索到 candidate lesson（来自 game-abc123）"` 或 `"active 池中暂无匹配策略"` |
| **Promotion Event** | `strategy_patches` 表 | `"lesson-xyz: candidate → active, 审核人: wxhfy, 理由: 3个独立 source 确认有效"` |
| **Post-Promotion Effect** | 后续多局对比 | 同类场景的 decision score 从 0.32 提升至 0.71 |

## 答辩展示建议

### 建议 1：展示一场完整对局的决策追踪
- 任选一局 7 人标准局，随机选一个 Agent（如 3号-张飞-村民）
- 展示该 Agent 在每个阶段的完整链路：
  - Night 1：Observation（无信息） → Decision（无行动/村民无夜晚技能）
  - Day 1 Speech：Observation（看到警长竞选） → Strategy Hit → Decision（发言文本）
  - Day 1 Vote：Observation（听完所有发言） → Strategy Hit → Decision（投票目标）
  - Day 2 Speech：Observation（看到死亡信息+查验信息） → Strategy Hit → Decision（更新推理）
- 建议使用时间线可视化（HTML 报告中的决策追踪视图）

### 建议 2：展示赛后评分报告
- 打开 `review_report.json`（PlayerReviewReport）
- 展示 Mistake List：哪些决策得了低分、为什么低分
- 展示 Highlight List：哪些决策得了高分、为什么高分
- 展示 Counterfactual：对关键失误的"如果当时这样做..."反事实推演
- 使用 HTML dashboard 中的颜色编码（红色=失误、绿色=高光、黄色=模糊）

### 建议 3：展示策略检索证明
- 选择连续两局：Game 1 中产生了某个 lesson，Game 2 中该 lesson 被检索到
- 展示 Game 1 的 KnowledgeAbstractor 输出（AbstractedLesson）
- 展示 Game 2 的 tool_trace（search_strategies 命中了该 lesson）
- 展示 Game 2 的 decision 中引用了该 lesson 的内容
- 对比 Game 1 和 Game 2 同类决策的 score 差异

### 建议 4：展示信息隔离证明
- 同时打开两个 Agent 的 PlayerView（如预言家 vs 村民）
- 预言家视图：包含查验结果（private_events 中有"查验7号是狼人"）
- 村民视图：无查验结果，只知道公开信息
- 用 JSON diff 工具展示差异，证明信息隔离严格有效
- 也可展示狼队的 known_wolves 字段，证明狼同伴信息未泄露

### 建议 5：展示多 Tier 对比
- 用实验结果的对比表格展示四组差异
- 重点展示：both 组在 invalid_action_count 上显著低于 baseline（p < 0.01）
- 展示 strategy_usage_count：trackc_only 组的策略使用次数分布
- 展示 Bootstrap 95% CI 图表：四组的 process_score 分布区间
- 展示 Cohen's d 效应量：both vs baseline 的 d 值（预期中到大效应）

### 建议 6：展示一个 Bad Case 的完整修复闭环
- 挑选一个典型 bad case（如：狼人悍跳预言家时不报查验细节，导致发言空洞被识别为假）
- 展示完整闭环：
  1. Game N：该失误发生 → score=0.28, mistake_type="empty_speech"
  2. KnowledgeAbstractor 生成 lesson："狼人悍跳预言家时必须编造完整的查验细节（查验对象、查验理由、查验结果），否则容易被好人识破"
  3. Lesson 写入 candidate
  4. 人工审核后晋升 active
  5. Game N+K：另一狼人在类似情境中检索到该 lesson → 编造了完整查验细节
  6. 该 decision 的 speech_quality score 从 0.28 提升到 0.76
- 这是答辩中"自进化"能力的最有力证据

## 答辩文件清单

准备以下文件供评委翻阅：

| 文件 | 内容 | 用途 |
|------|------|------|
| `game_report_<id>.json` | 单局完整报告（decisions + scores + lessons） | 证据溯源 |
| `review_report_<id>.json` | 单局 PlayerReviewReport（Mistakes + Highlights + Counterfactuals） | 复盘展示 |
| `dashboard.html` | 可视化 HTML dashboard（决策追踪 + 评分分布 + 知识增长） | 演示用 |
| `experiment_results.json` | 多 Tier 实验结果 + 统计检验 | 量化对比 |
| `isolation_check_result.json` | 信息隔离 12 项检查结果 | 系统完整度证明 |
| `evolution_loop_verify.json` | Track C 闭环验证（lesson → retrieval → improvement） | 自进化能力证明 |
| `strategy_snapshot_<ts>.json` | 实验时的策略库快照 | 实验可复现证明 |
| `leaderboard.json` | 四 Tier 三维排名 | Leaderboard 效果展示 |

## 关键答辩论点

1. **"我们不只是让 AI 玩狼人杀，我们是让 AI 玩完之后能复盘、能改进、能避免下次犯同样的错。"**
   - 支撑：证据链模板从 Score → Lesson → Retrieval → Improvement 的完整闭环

2. **"信息隔离不是嘴上说说——我们有 12 项自动化检查。"**
   - 支撑：`isolation_check_result.json` + PlayerView diff 可视化

3. **"Track C 的自进化是轻量的：不 fine-tune 模型，不改 prompt 代码，只增删策略文档。"**
   - 支撑：策略库三层隔离 + candidate 默认不污染 active + 晋升需人工审核

4. **"实验结果可以复现——我们有固定的 seed range 和 strategy snapshot。"**
   - 支撑：`strategy_snapshot_<ts>.json` + experiment protocol 文档

5. **"Bad case 不只是被标记为错误——它被转化为可检索的知识，在后续对局中阻止同类错误。"**
   - 支撑：Bad Case 完整修复闭环演示
