# PairwiseLogisticRanker Debug Report

> 生成时间：2026-05-29
> 测试文件：`tests/test_pairwise_ranker_direction.py`（8 tests）
> 状态：**64/64 全部测试通过**

---

## 一、之前为什么失败

### 根因：特征 delta 过小

**median_abs_delta = 0.0** — 41 个 pairwise examples 中，半数以上 pair 的 better/worse 特征完全一致。

详细诊断：

| 指标 | 值 | 含义 |
|------|:--:|------|
| total_pairs | 41 | — |
| zero_variance_features | 44/51 | 86% 特征在 better/worse 间无差异 |
| all_zero_delta_rows | 24/41 | 59% pair 的 better/worse 特征完全相同 |
| mean_abs_delta | 0.0054 | 接近零 |
| n_features_used (after filtering) | 3-7 | 仅 3-7 个特征有区分度 |

### 分类型诊断

| pair_type | n | degenerate | signal | 原因 |
|-----------|:--:|:----------:|:------:|------|
| wolf_speech_quality | 20 | 4 | **16** | 狼人好/坏发言的特征确实不同 |
| wolf_vote_coordination | 20 | **20** | 0 | 好/坏投票的 feature dict 完全一致 |
| werewolf_kill_target | 1 | 0 | 1 | 唯一一对有信号 |

### wolf_vote_coordination 失败原因

好投票和坏投票来自 variant factory 的不同 fixture。两个 fixture 的 P2 vote 机会虽然有不同 target（Seer vs Guard），但 FeatureRegistry 提取的 key differentiating features（`vote_coordination_failure`）在两个 case 中都为 0，因为：
- 坏 vote（P2→Guard）命中 known_wolf_ids 分支但 target 是 power role → vote_failure -= 0.3 → = 0
- 好 vote（P2→Seer）同样命中 → vote_failure = 0

两者在 feature space 中无法区分。需要让 vote_failure 在 split 场景下显著 > 0。

---

## 二、修复内容

### 2.1 PairwiseLogisticRanker.fit() 改进

1. **零方差特征过滤**：自动移除 better/worse 间无差异的特征
2. **退化 pair 过滤**：自动跳过 max(|delta|) < 1e-6 的 pair
3. **维度安全**：predict/compare_pair 中检查 scaler 维度匹配
4. **诊断输出**：返回 valid_pairs, degenerate_pairs, n_zero_variance_features

### 2.2 修复后结果（speech-only）

| 指标 | 值 |
|------|:--:|
| valid_pairs | 9/12 |
| n_features_used | 3 |
| train_accuracy | 0.75 |
| validation_accuracy | **0.875** |
| heldout_accuracy | —（样本不足） |

### 2.3 模型学到的特征权重

```
speech_grounding_score        +1.85  (接地气的发言更好)
role_goal_conflict_score      -0.35  (角色目标冲突降低质量)
wolf_perspective_leak_score   -0.35  (狼视角泄露降低质量)
```

**方向正确**：高 grounding → 高分，高 conflict/leak → 低分。

---

## 三、Direction Sanity Tests（8/8 PASS）

| 测试 | 结果 | 验证内容 |
|------|:----:|------|
| good_ranks_higher_than_bad | PASS | 清晰特征信号下 P(good>bad) > 0.5 |
| bad_ranks_lower_than_good | PASS | compare_pair(bad, good) < 0.3 |
| compare_pair_works | PASS | compare_pair 正确返回偏好概率 |
| reversed_labels_give_low_accuracy | PASS | 反转标签后模型学反方向 |
| symmetric_augmentation | PASS | clean data 下 train_acc >= 0.70 |
| save_load_preserves_predictions | PASS | 序列化后预测一致 |
| all_zero_features_handled | PASS | 全零特征不崩溃 |
| many_features_no_overfit | PASS | 50+随机特征下仍能学到信号 |

**结论：label/feature direction 正确。失败原因是特征差异不足，不是方向错误。**

---

## 四、是否可以进入主评分

| 条件 | 当前值 | 要求 | 通过? |
|------|:------:|:----:|:----:|
| validation_acc >= 0.65 | 0.875 | ≥ 0.65 | ✅ |
| heldout_acc >= 0.60 | N/A | ≥ 0.60 | ⚠️ LOW_SAMPLE |
| label_direction_suspect | false | false | ✅ |
| feature_delta_too_small | false (filtered) | false | ✅ |
| hard_cap_count | 0 | 0 | ✅ |

**结论：PairwiseLogisticRanker for speech quality can be used as auxiliary signal. But cannot be a primary scoring source due to limited pair types (vote/kill pairs still degenerate).**

---

## 五、下一步

1. Fix vote_coordination pair generation to produce differentiable features
2. Add kill_target value pairs with clear counterfactual gap differences
3. Expand speech pairs to 100+ across more templates and seat configs
4. Add real replay human-labeled pairs
5. Integrate speech ranker signal into ProcessScoreV3 as speech_rank_score
