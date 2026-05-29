# Part 8: B 方向完整实现审计

> 审计日期: 2026-05-28 | 状态: 只读 | 范围: V1→V7 全链条

---

## 8.1 B 评分系统模块清单

| 模块 | 文件路径 | 输入 | 输出 | 是否实现 | 当前版本 | 验证结果 |
|------|---------|------|------|---------|---------|---------|
| Opportunity Extraction | `backend/eval/opportunity.py` | ReplayBundle (from DB) | `opportunities.jsonl` (2461 条) | ✅ IMPLEMENTED | V1 | `camp_won` bug |
| Pre-Action Scoring | `scripts/compute_v2_scores.py` | opportunities + replay bundle | `opportunity_scores_v2.jsonl` | ✅ IMPLEMENTED | V2 | 0 后验污染 |
| Outcome-Impact Scoring | `scripts/compute_v2_scores.py` (同一脚本) | post-outcome features | per-type outcome functions | ✅ IMPLEMENTED | V2 | 与 PreAction 分离 |
| V3 Feature Builder | `scripts/build_v3_features.py` | opportunities + DB replay | `opportunities_v3_features.jsonl` | ✅ IMPLEMENTED | V3 | 46 特征, 中文分析 |
| Role-Action Scorers | `scripts/v3_full_pipeline.py` | V3 features + labels | per-role-action LogisticRegression | ✅ IMPLEMENTED | V3 | GroupKFold |
| Hard Negative Mining | `scripts/v4_label_expansion.py` | opportunities + scores | `hard_negative_candidates_v4.jsonl` (671) | ✅ IMPLEMENTED | V4 | 难度分群 |
| Pairwise Label Generation | `scripts/v4_label_expansion.py` (同一脚本) | counterfactual pairs | `pairwise_candidates_v4.jsonl` (739) | ✅ IMPLEMENTED | V4 | 反事实对 |
| V4 Benchmark | `scripts/v4_benchmark.py` | 扩展数据集 | `scoring_validity_gate_v4.md/json` | ✅ IMPLEMENTED | V4 | 8/12 PASS |
| Dataset Normalization | `scripts/v5_benchmark.py` | 所有标签 | `benchmark_dataset_v5.jsonl` | ✅ IMPLEMENTED | V5 | 统一 schema |
| Label Quality Audit | `scripts/v5_benchmark.py` (同一脚本) | 数据集 | `label_quality_audit_v5.md` | ✅ IMPLEMENTED | V5 | easy/medium/hard 分类 |
| Generalization Validation | `scripts/v5_benchmark.py` | GroupKFold split | `generalization_report_v5.md` | ✅ IMPLEMENTED | V5 | Train-Test Gap 0.053 |
| Confidence Model | `scripts/v5_benchmark.py` | 6-factor 公式 | `confidence_model_v5.md` | ✅ IMPLEMENTED | V5 | 6因子 |
| Calibration Report | `scripts/v5_benchmark.py` | isotonic regression | `calibration_v5.md` | ✅ IMPLEMENTED | V5 | ECE=0.166 |
| V6 Model-Assisted Review | `scripts/v6_benchmark_ready.py` | 未审核样本 | `human_reviewed_labels_v6.jsonl` | ✅ IMPLEMENTED | V6 | AI 代人工 |
| V6 Hard Negative Rebalance | `scripts/v6_benchmark_ready.py` | 数据集 | `benchmark_dataset_v6.jsonl` | ✅ IMPLEMENTED | V6 | easy neg: 0.648→0.067 |
| Private-Context-Aware Scoring | `scripts/v7_private_context.py` | replay bundle | `visibility_context_snapshots_v7.jsonl` | ✅ IMPLEMENTED | V7 | 0 visibility violations |
| Visibility Audit | `scripts/v7_private_context.py` (同一) | 所有 snapshot | `visibility_context_report_v7.md` | ✅ IMPLEMENTED | V7 | 0 violations |
| Counterfactual Validity | `scripts/compute_speech_and_counterfactual.py` | DB replay events | `counterfactual_impacts.json` (976条) | ✅ IMPLEMENTED | V2 | vote_flip + skill_swap |
| Valid Agent | `backend/eval/track_b.py::TrackBValidator` | PublishedReview | `validation_result.json` | ✅ IMPLEMENTED | V1 | 10个 Gate |
| MBTI Dashboard | `scripts/fix_mbti_metrics_v2.py` | player_scores + replay | `mbti_performance_dashboard_v7_metrics_fixed.html` | ✅ IMPLEMENTED | V7 Fixed | n≥10 filter, Wilson CI |
| Scoring Appendix | `scripts/generate_v7_deliverables.py` | 各版本 Gate | `scoring_validity_appendix_v7.html` | ✅ IMPLEMENTED | V7 | V1→V7 evolution |
| Single Game Review HTML | `scripts/render_single_game_html.py` + `scripts/build_single_game_report_data.py` | replay bundle + scores | `review_game_<id>.html` (60+) | ✅ IMPLEMENTED | V3 Renderer | 12-module HTML |
| Label Backlog | `scripts/generate_v7_deliverables.py` | 各角色标注缺口 | `v7_1_label_backlog.md` | ✅ IMPLEMENTED | V7 | 待标注列表 |

---

## 8.2 V1→V7 进化路径

| 版本 | 核心变化 | 关键指标 | 产物 |
|------|---------|---------|------|
| **V1** | Rule-based 整局评分 | 后验污染严重 | `review_with_learned_scores.md` |
| **V2** | PreAction/OutcomeImpact 分离, 0后验污染 | Witch d=0.536, Guard d=0.203 | `opportunity_scores_v2.jsonl` |
| **V3** | 46个预动作特征, 中文发言分析, 怀疑矩阵 | VotePreQuality std=0.227 | `opportunities_v3_features.jsonl` |
| **V4** | 难负样本挖掘, 反事实对生成, 按角色动作训练 LR | 8/12 PASS | `opportunity_scores_v4.jsonl` |
| **V5** | 数据归一化, 标签质量审计, GroupKFold, 6因子置信度 | Train-Test Gap 0.053 | `benchmark_dataset_v5.jsonl` |
| **V6** | AI代人工review, 难负样本重平衡, easy neg 0.067 | 8/12 PASS | `benchmark_dataset_v6.jsonl` |
| **V7** | 私有上下文感知评分 (Witch/Seer), 0 visibility violations | PaW 0.877 | `scoring_validity_gate_v7.md` |

---

## 8.3 当前 Gate 状态 (V7)

| 指标 | 值 | Gate |
|------|-----|------|
| Overall PaW | 0.877 | ✅ PASS |
| Test PaW (GroupKFold) | 0.877 | ✅ PASS |
| Train-Test Gap | 0.053 | ✅ PASS |
| Post-Outcome Contamination | 0 violations | ✅ PASS |
| Visibility Violations | 0 violations | ✅ PASS |
| Role-Actions PASS | 8 of 12 | ⚠️ PASS_WITH_LIMITATIONS |
| VotePreQuality std | 0.268 | ✅ PASS |
| ECE | 0.166 | ⚠️ RANKING ONLY |

### Role-Action Gate 详情

| Role-Action | Cohen's d | Status | 原因 |
|-------------|----------|--------|------|
| Vote | 1.40 | ✅ PASS | 样本充足 |
| Guard Protect | 0.96 | ✅ PASS | 133 labeled |
| Werewolf Kill | 0.82 | ✅ PASS | 样本充足 |
| Witch Poison | 0.71 | ✅ PASS | 样本充足 |
| Speech | 0.68 | ✅ PASS | 注意: 0 labeled speech samples |
| Seer Check | 0.52 | ⚠️ PASS | 仅12 labeled, d基于rule |
| Hunter Shot | 0.31 | ⚠️ LOW_CONF | 12 labeled, 1 bad |
| Witch Save | 0.28 | ⚠️ LOW_CONF | 私有上下文可用, 仅1 bad label |
| Seer Release | 0.15 | ⚠️ LOW_CONF | 私有上下文可用, 0 bad labels |
| Hunter Restraint | N/A | ⚠️ LOW_CONF | 样本不足 |

---

## 8.4 关键审计问题回答

### Q1: B 是不是完整跑通？
**A**: ⚠️ **PARTIALLY** — 核心评分 pipe 跑通了 (V1→V7)，但:
- V2→V7 脚本是独立的一次性脚本，非统一管道
- 需要手动按顺序运行多个脚本
- 中间文件有版本命名不一致 (v2/v3/v4/.../v7 独立文件)

### Q2: V1→V7 的产物是否都在？
**A**: ✅ **YES** — 各版本的主要产物都在 `data/health/` 中:
- `scoring_validity_gate_v{2-7}.md` — 各版本 Gate 报告
- `opportunity_scores_v{2-7}.jsonl` — 各版本分数
- `benchmark_dataset_v{5,6}.jsonl` — 各版本数据集
- `player_scores_v{2-7}.jsonl` — 各版本玩家分数

### Q3: 当前最终推荐使用哪个版本？
**A**: **V7** — `scripts/v7_private_context.py` 是最新版本，支持私有上下文感知评分 (Witch/Seer)。

### Q4: 当前 Gate 状态是什么？
**A**: **PASS_WITH_LIMITATIONS** — 8/12 role-actions PASS, 4个 LOW_CONF。

### Q5: 哪些 role-action PASS？
**A**: Vote, Guard Protect, Werewolf Kill, Witch Poison, Speech (⚠️ unvalidated), Seer Check (⚠️ low sample)。

### Q6: 哪些 LOW_CONF？
**A**: Witch Save (仅1个bad label), Seer Release (0 bad labels), Hunter Shot (仅12 labeled, 1 bad), Hunter Restraint (样本不足)。

### Q7: 是否有 fake metric / fallback metric？
**A**: ⚠️ **有**:
- 当 labeled 样本不足时，部分 role-action 用 rule-based scoring 作为 fallback
- `calculate_process_score()` 中 `mistake_penalty` 和 `counterfactual_impact` 硬编码为 0.0 (占位符)
- MBTI Dashboard 的 composite 公式是自定义权重，非校准后概率

### Q8: 是否仍然存在后验污染？
**A**: ✅ **NO** — V2 起实现 PreAction/OutcomeImpact 分离，`FORBIDDEN_PRE_FEATURES` 列表验证，0 violations。

### Q9: 是否仍然存在 visibility violation？
**A**: ✅ **NO** — V7 有 `visibility_context_report_v7.md` 确认 0 violations。

### Q10: Score 是 ranking 还是 probability？
**A**: **RANKING ONLY** — 官方声明: "Scores are RANKING scores, NOT probability estimates"。ECE=0.166 说明校准不足。

### Q11: Speech scoring 是否已验证？
**A**: ❌ **NO** — "0 labeled speech samples"。Speech score 的 d=0.68 可能基于特征差异而非真实质量差异。

### Q12: MBTI dashboard 是否使用 V7 scores？
**A**: ⚠️ **PARTIALLY** — V7 fixed (`fix_mbti_metrics_v2.py`) 使用 V4 player_scores 回填 is_win 和 camp，并计算 role-normalized PreAction 和 role-adjusted win lift。使用的是 role-normalized 原始 PreAction 而非 role-action model scores。

### Q13: 单局复盘是否使用 V7 scores？
**A**: ⚠️ **PARTIALLY** — `render_single_game_html.py` 使用 `generate_v7_deliverables.py` 的输出，该脚本引用 V7 的 player_scores 和 opportunity_scores。

---

## 8.5 架构限制 (不可修复)

| 限制 | 原因 | 影响 |
|------|------|------|
| Witch Save LOW_CONF | 坏人决策极少 (wolves don't miss often) | 无法在高置信度下评估女巫救药质量 |
| Seer Release LOW_CONF | 信息发布策略难以标注好坏 | 无法评估预言家信息释放 |
| Hunter Shot LOW_CONF | 开枪机会极少 (12 labeled, 1 bad) | 样本太少无法训练模型 |
| ECE=0.166 (RANKING ONLY) | 分数分布不均匀，校准困难 | 分数只能用于排序不能当概率 |
| Cross-role 不可比 | Role-normalized 后也不能完全公平 | MBTI Dashboard 受角色分布影响 |
| Speech 未验证 | 0 labeled speech samples | Speech score 的 d=0.68 不可信 |
| Model-assisted review 非真人工 | AI 代标的标签可能存在偏见 | 标签质量需要人工验证 |

---

## 8.6 数据流总图

```
Game Engine → GameState
  ↓
track_b.py: ReplayBundleBuilder → ReplayBundle (DB: published_reviews.replay_bundle)
  ↓
opportunity.py: OpportunityExtractor → opportunities.jsonl (2461条)
  ↓
build_v3_features.py → opportunities_v3_features.jsonl (46 features)
  ↓ (分支1: 人工标注)
label_opportunities.py → eval_gold_set.jsonl (234) + eval_silver_set.jsonl (155)
  ↓ (分支2: 难负样本)
v4_label_expansion.py → hard_negative_candidates_v4.jsonl (671) + pairwise_candidates_v4.jsonl (739)
  ↓
v3_full_pipeline.py / v5_benchmark.py → per-role-action LR models
  ↓
v7_private_context.py → visibility_context_snapshots_v7.jsonl + opportunity_scores_v7.jsonl
  ↓
compute_v2_scores.py / scoring_models.py → player_scores_v7.jsonl
  ↓
fix_mbti_metrics_v2.py → mbti_performance_dashboard_v7_metrics_fixed.html
generate_v7_deliverables.py → scoring_validity_appendix_v7.html + review_game_*.html
```

---

## 8.7 关键审计结论

1. ✅ **B 方向 V1→V7 完整实现** — 16 个模块全部落地代码
2. ✅ **V7 是当前最新版本** — 支持私有上下文感知评分
3. ⚠️ **不是统一管道** — 脚本碎片化, 需要手动串联
4. ⚠️ **Gate PASS_WITH_LIMITATIONS** — 8/12 PASS, 4 LOW_CONF
5. ❌ **Speech scoring 未验证** — 0 labeled samples
6. ❌ **部分 fallback metric 存在** — mistake_penalty/counterfactual_impact 硬编码 0
7. ✅ **0 后验污染 + 0 visibility violations** — 核心安全保证成立
8. ⚠️ **Score 是 RANKING ONLY** — 不可解释为概率
9. ❌ **Model-assisted review 不是真人工** — 标签质量最终依赖人工验证
