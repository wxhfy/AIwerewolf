# Track B BadCase-001 回归测试报告

> 生成时间：2026-05-28
> 统一 Pipeline：`scripts/run_pipeline.py`
> 训练模型：`data/health/decision_quality_model.pkl` (232 KB) + `opportunity_value_model.pkl` (3 KB)
> 测试状态：**17/17 测试通过**（11 badcase + 6 model loading）

---

## 一、使用的 Track B 模块

| 模块 | 用途 |
|------|------|
| `backend.eval.review.MetricsCalculator` | 多维度玩家评分 + BadCase 检测（rule-based） |
| `backend.eval.track_b.ReplayBundleBuilder` | 从 GameState 构建 replay bundle |
| `backend.eval.track_b.generate_published_review_document` | 完整 Track B pipeline（bundle → report → validate → publish） |
| `backend.eval.opportunity.OpportunityExtractor` | 从 replay bundle 提取 DecisionOpportunity（24 个） |
| `backend.eval.scoring_models.OpportunityValueModel` | 机会价值模型（LogisticRegression, 640 样本） |
| `backend.eval.scoring_models.DecisionQualityModel` | 决策质量模型（GradientBoostingClassifier, 47 维特征, 640 样本） |
| `backend.eval.scoring_models.load_track_b_models` | 统一模型加载函数 |
| `backend.eval.scoring_models.calibrate_decision_quality` | **NEW** Rule-backed calibration layer |
| `backend.eval.scoring_models.compute_speech_scores` | **NEW** Heuristic speech scoring |
| `backend.eval.scoring_models.calculate_process_score_v2` | **NEW** Private-context-aware process score |
| `scripts/run_pipeline.py` | 统一 v2-V7 pipeline 编排器（9 stages） |

---

## 二、统一 Pipeline 架构

### Stage 流程

```
Stage 1: extract      从 game replays 提取 DecisionOpportunity
Stage 2: features     构建 V3 特征向量（47 维 ModelFeatures，含 10 个 private-context）
Stage 3: labels       硬负样本挖掘 + pairwise 反事实生成 (V4)
Stage 4: benchmark    统一 benchmark 数据集 (V5)
Stage 5: review       人工审核优先级队列 (V6)
Stage 6: private_ctx  V7 私有上下文感知评分
Stage 7: train        训练 sklearn OpportunityValueModel + DecisionQualityModel
Stage 8: score        用校准模型对全量 opportunity 打分（含 raw+calibrated 双输出）
Stage 9: deliverables 生成 pipeline_summary.json + 最终分数文件
```

### 模型产物

| 文件 | 大小 | 内容 |
|------|:----:|------|
| `data/health/opportunity_value_model.pkl` | 3 KB | LogisticRegression (OVM, 47 features) |
| `data/health/decision_quality_model.pkl` | 232 KB | GradientBoostingClassifier (DQM, 47 features) |
| `data/health/opportunity_scores_trained.jsonl` | ~15 MB | 2461 个 opportunity（raw_q + calibrated_q + reasons） |
| `data/health/player_scores_trained.jsonl` | ~90 KB | 392 名玩家（legacy + calibrated process_score） |
| `data/health/pipeline_summary.json` | — | Pipeline 运行摘要 |

---

## 三、新增 Private-Context Features

### ModelFeatures 扩展（37 → 47 维）

```python
# V7-aware private-context features (10 new fields)
private_has_confirmed_wolf: int       # Agent 知道至少一个狼人
private_has_confirmed_good: int       # Agent 知道至少一个好人
target_is_private_confirmed_wolf: int # 目标对象是私有已知狼
target_is_private_confirmed_good: int # 目标对象是私有已知好人
private_info_should_release: int      # 存在应释放的关键信息（如查杀）
private_info_was_released: int        # 发言中实际释放了信息
private_info_withheld: int            # 应释放但未释放
voted_elsewhere_despite_known_wolf: int # Seer 知道狼但不投
risky_private_info_release: int       # Witch/Guard 不必要地公开身份
consecutive_same_guard_target: int    # Guard 连续守护同一目标
```

### 提取源

从 `DecisionOpportunity.private_context_summary` 解析，此字段在 BadCase-001 fixture 中已有数据：
- P3 speech: `{"private": "昨晚查验 P1 是狼人"}`
- P3 vote: `{"private": "我知道 P1 是狼但没有公开"}`

### BadCase-001 P3 机会的 private context features

```
P3 d1 speech:  private_has_confirmed_wolf=1
               private_info_should_release=1
               private_info_withheld=1

P3 d1 vote:    private_has_confirmed_wolf=1
               private_info_should_release=1
               private_info_withheld=1
               voted_elsewhere_despite_known_wolf=1
```

---

## 四、Calibration Layer

### 设计

`calibrate_decision_quality(opportunity, raw_q) → CalibratedScore`

Rule-backed calibration 在模型预测之后应用角色/动作/私有上下文规则：

| Rule | 触发条件 | 上限 |
|------|----------|:----:|
| witch_poisoned_good | Witch poison → village target | q ≤ 0.20 |
| hunter_shot_good | Hunter shot → village target | q ≤ 0.20 |
| private_info_withheld | Seer should release but didn't | q ≤ 0.25 |
| voted_elsewhere_despite_known_wolf | Seer knew wolf, voted village | q ≤ 0.25 |
| risky_private_info_release | Witch/Guard exposed secrets in speech | q ≤ 0.35 |
| consecutive_same_guard_target | Guard self-guard N2+ or repeated target | q ≤ 0.35 |

输出同时保留 `raw_model_q`、`calibrated_q`、`calibration_reasons`。

### BadCase-001 raw → calibrated 对照

| 机会 | raw_q | calibrated_q | 原因 |
|------|:-----:|:-----------:|------|
| P3 d1 speech (隐藏查杀) | 0.9962 | **0.2500** | private_info_withheld |
| P3 d1 vote (不投已知狼) | 0.4013 | **0.2500** | private_info_withheld, voted_elsewhere_despite_known_wolf |
| P4 d1 speech (泄露女巫信息) | 0.9957 | **0.3500** | risky_private_info_release |
| P5 d1 speech (暴露守卫身份) | 0.9927 | **0.3500** | risky_private_info_release |
| P6 d1 hunter_shot (打死预言家) | 0.9764 | **0.2000** | hunter_shot_good |
| P4 d2 witch_poison (毒死守卫) | 0.9564 | **0.2000** | witch_poisoned_good |
| P5 d2 guard (连续自守) | 0.7682 | **0.3500** | consecutive_same_guard_target |
| P1 d2 werewolf_kill (刀女巫) | 0.9882 | **0.9882** | —（狼人好操作，不校准） |
| P1 d1 vote (推猎人出局) | 0.7648 | **0.7648** | —（狼人好操作，不校准） |

**6/6 个关键坏操作被校准到 ≤ 0.35，2/2 个狼人好操作保持 > 0.75。**

---

## 五、实际跑分结果

### 5.1 MetricsCalculator 玩家分数（rule-based）

| 玩家 | 角色 | process_score | vote | speech | skill | role_task | mistake |
|------|------|:----------:|:----:|:------:|:-----:|:---------:|:-------:|
| P1 | Werewolf | **91.00** | 1.00 | 0.55 | 0.80 | 0.96 | 0.00 |
| P2 | Werewolf | **88.78** | 1.00 | 0.35 | 0.80 | 0.96 | 0.00 |
| P3 | Seer | **13.52** | 0.00 | 0.35 | 0.73 | 0.40 | 0.18 |
| P4 | Witch | **0.00** | 0.00 | 0.35 | 0.20 | 0.28 | 0.32 |
| P5 | Guard | **0.00** | 0.00 | 0.35 | 0.00 | 0.10 | 0.18 |
| P6 | Hunter | **9.26** | 1.00 | 0.35 | 0.00 | 0.34 | 0.32 |
| P7 | Villager | **22.78** | 0.00 | 0.55 | 0.50 | 0.00 | 0.00 |

分离度：P1-P3 = 77.48, P1-P6 = 81.74

### 5.2 Heuristic Speech Scores（非训练模型）

| 玩家 | speech_score | 解读 |
|------|:----------:|------|
| P1 | **0.90** | 归票语言，提及玩家和"有问题"关键词 |
| P2 | **0.75** | 简短跟票，提及 P6 和"不对劲" |
| P3 | **0.60** | 隐藏查杀（penalty -0.30）+ 提及 P6（+0.25） |
| P4 | **0.45** | 泄露女巫信息（penalty -0.30）+ 提及 P5/P7（+0.25） |
| P5 | **0.35** | 暴露守卫身份（penalty -0.30）+ 提及"守卫"关键词（+0.15） |
| P6 | **0.50** | 仅情绪威胁，无 game reasoning，无 ID mentions |
| P7 | **0.90** | 跟风狼人，提及 P1/P6 + "狼"关键词 |

> **注意：speech_score 是 heuristic，不是人工标注模型。** 当前规则：base 0.50 + ID mentions 0.25 + game keywords 0.15 - risky/withheld penalties 0.30。

### 5.3 calibrated_process_score（v2，含 private-context）

| 玩家 | 角色 | legacy_process | calibrated_process | speech | mistake | 说明 |
|------|------|:------------:|:-----------------:|:------:|:-------:|------|
| P1 | Werewolf | 0.7310 | **0.8966** | 0.90 | 0.00 | 狼人好操作，校准无影响 |
| P2 | Werewolf | 0.7010 | **0.8816** | 0.75 | 0.00 | 同上 |
| P3 | Seer | 0.6148 | **0.6160** | 0.60 | 0.18 | withheld+voted_elsewhere penalties |
| P4 | Witch | 0.6023 | **0.4127** | 0.45 | 0.17 | critical poison + risky speech |
| P5 | Guard | 0.5420 | **0.3604** | 0.35 | 0.15 | consecutive guard + risky speech |
| P6 | Hunter | 0.6195 | **0.4008** | 0.50 | 0.20 | critical hunter shot |
| P7 | Villager | 0.6185 | **0.5285** | 0.90 | 0.00 | 跟风狼人但 speech 无 penalty |

**分离度**：
- P1.calibrated - P3.calibrated = **0.2806**（目标 ≥ 0.25） ✓
- P1.calibrated - P6.calibrated = **0.4958**（目标 ≥ 0.35） ✓

### 5.4 Published Review Validation

```
Status: approved · Grade: pass · Score: 1.00 · Issues: 0
```

---

## 六、BadCase 检测（5/5 全部命中）

| BadCase | 严重度 | 玩家 | 描述 |
|---------|:------:|------|------|
| seer_withheld_confirmed_wolf | major | P3 Seer | 查验出狼人但未公开发布信息 |
| **seer_ignored_confirmed_wolf_vote** | **major** | **P3 Seer** | **明知 P1 是狼却投票 P6（NEW!）** |
| witch_poisoned_village_power | critical | P4 Witch | 毒药杀死了好人阵营守卫 |
| guard_consecutive_same_target | major | P5 Guard | 连续两晚守护同一目标（自己） |
| hunter_shot_key_village_power | critical | P6 Hunter | 开枪打死了好人阵营预言家 |

**seer_ignored_confirmed_wolf_vote 已从 GAP 中移除，现在正式命中。**

---

## 七、全量数据 Role-Level 统计（calibrated_q, 2461 opps, 392 players）

| 角色 | 平均 calibrated_q | 标准差 | 玩家数 |
|------|:------:|:------:|:------:|
| Werewolf | **0.9051** | 0.0913 | 112 |
| Witch | 0.8739 | 0.0718 | 56 |
| Seer | 0.8662 | 0.0589 | 56 |
| Hunter | 0.8551 | 0.0974 | 56 |
| Villager | 0.8241 | 0.0824 | 56 |
| Guard | 0.6480 | 0.1288 | 56 |

---

## 八、测试覆盖（17 tests）

### BadCase-001 回归测试（11 tests）

| 测试 | 状态 |
|------|:----:|
| test_badcase_001_scores_are_separated | PASS |
| test_badcase_001_detects_seer_withheld_wolf_check | PASS |
| test_badcase_001_detects_witch_poisoned_village_power | PASS |
| test_badcase_001_detects_hunter_shot_key_village_power | PASS |
| test_badcase_001_detects_guard_consecutive_same_target | PASS |
| test_badcase_001_detects_seer_voted_against_checked_wolf | **PASS（不再是 GAP）** |
| test_badcase_001_wolves_score_high_for_good_play | PASS |
| test_badcase_001_opportunities_extracted | PASS |
| test_badcase_001_process_scores_from_opportunities | PASS（loads trained model, FAILs if missing） |
| test_badcase_001_seer_release_opportunity_low | PASS |
| test_badcase_001_guard_consecutive_opportunities | PASS |

### 模型加载测试（6 tests）

| 测试 | 状态 |
|------|:----:|
| test_model_files_exist_or_skip | PASS |
| test_load_track_b_models_returns_trained_models | PASS |
| test_decision_quality_model_predictions_vary | PASS |
| test_badcase_001_key_opportunities_score_low_with_models | **PASS（calibrated_q, 5/5 ≤ 0.35）** |
| test_untrained_model_predict_emits_warning | PASS |
| test_load_track_b_models_raises_if_missing | PASS |

---

## 九、已知限制

| 限制 | 影响 | 修复方向 |
|------|------|----------|
| Speech 仍是 heuristic | 无法评估发言逻辑质量 | 人工标注 speech quality labels |
| Outcome impact proxy = 0.5 | process_score 公式最后一项是占位符 | 集成 counterfactual_impact |
| DQM 对 speech 全打 0.99+ | 模型没有 speech content features | 将 speech text embeddings 加入 ModelFeatures |
| calibration rules 手动维护 | 新角色/新动作需手写规则 | 长期用 pairwise training + private-context 特征替代校准 |
| LOW_CONF: witch_save, seer_speech | 样本少，校准规则粗粒度 | 更多标注数据 |
| 旧模型（37 维）与新特征（47 维）不兼容 | 需重新训练 | load 时检查 feature count，给出 clear error |

---

## 十、运行命令

```bash
# 统一 pipeline
python scripts/run_pipeline.py                        # 全流程
python scripts/run_pipeline.py --stage train          # 训练模型（含 47 维 features）
python scripts/run_pipeline.py --stage score          # 打分（raw + calibrated 双输出）

# 回归测试
pytest tests/test_track_b_badcase_regression.py -v    # 11 tests
pytest tests/test_track_b_model_loading.py -v         # 6 tests
```

---

## 十一、结论

### 已验证的能力

1. **Private-context features 进入 ModelFeatures**：10 个新字段从 `private_context_summary` 提取，旧模型不兼容时明确报错。

2. **Calibration layer 正确覆盖 6/6 坏操作**：hunter_shot→0.20, witch_poison→0.20, withheld→0.25, voted_elsewhere→0.25, risky_speech→0.35, consecutive_guard→0.35。

3. **BadCase 检测 5/5 全命中**：新增 `seer_ignored_confirmed_wolf_vote` 规则，结束 GAP 状态。

4. **Speech scores 不再全 0.5**：heuristic 根据内容/私有信息 penalties 产生差异化分数（0.35-0.90）。

5. **calibrated_process_score_v2 有效拉开差距**：P1=0.90 vs P5=0.36, P1-P6=0.50。比 legacy formula 的 separation 更明显。

6. **统一 pipeline 可跑**：`run_pipeline.py --stage score` 自动输出 raw_q + calibrated_q + calibration_reasons。

### 结论声明

**BadCase-001 显示 Track B 在 private-context-aware calibration 后能识别显著坏操作。**

这不是完整高手评测——seer speech 的隐藏查杀识别仍依赖规则而非模型 learned features，speech 评分仍是 heuristic。但 calibration layer 提供了短期可用的 bridge，让明显坏操作在模型输出上得到正确低分，同时保留 raw_model_q 供后续模型迭代。
