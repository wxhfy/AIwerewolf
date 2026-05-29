# Track B BadCase-002 狼人低质量局回归报告

> 生成时间：2026-05-28
> 测试文件：`tests/test_track_b_badcase_wolf_regression.py`（9 tests）
> 统一 Pipeline：`scripts/run_pipeline.py`
> 状态：**26/26 全部 Track B 测试通过**（11 BadCase-001 + 9 BadCase-002 + 6 model loading）

---

## 一、与 BadCase-001 的核心区别

| 维度 | BadCase-001 (神职集体送局) | BadCase-002 (狼人低质量局) |
|------|--------------------------|---------------------------|
| 被测方 | 好人神职（Seer/Witch/Guard/Hunter） | 狼人（Werewolf） |
| 核心目标 | 证明神职坏操作得低分 | 证明狼人坏操作不天然高分 |
| 校准方式 | 初期使用 hard cap（已移除） | **纯 soft calibration**，零 hard cap |
| 动态特征 | private_context (10 fields) | + wolf-specific (6 fields) |
| 评分驱动 | 规则兜底 + 私有上下文 aware | **量化特征值 × 权重**，模型学习 |

---

## 二、BadCase-002 时间线

```
N1: P1+P2 狼人刀 P7 (低价值村民)
    P3 Seer 查验 P1 = wolf
    P4 Witch 救 P7, P5 Guard 守 P3

D1: P3 公开跳预言家："P1 是狼人，今天出 P1"
    P1 狼人发言："我们狼……不是，我是说好人这边不可能这么快被查到。昨晚刀口也不是这么回事。"
       → 暴露狼视角、口误
    P2 狼人发言："P1 一定是好人，谁投 P1 谁就有问题。我就保 P1 了。"
       → 硬保被查杀队友、零证据
    P4-P7 按查杀投票

D1 投票: Wolves split (P1→P3, P2→P5), Village unified (→P1)
    P1 被放逐

N2: P2 刀 P7 (再次低价值，无视已暴露预言家 P3)
    P4 Witch 毒 P2

结果: Village wins. 狼人因自身低质量操作输掉。
```

---

## 三、动态 Wolf 特征（6 个，纯量化）

| 特征 | 类型 | 取值范围 | 计算方式 |
|------|:----:|:------:|----------|
| `wolf_perspective_leak_score` | float | [0, 1] | 发言中狼视角关键词密度 + 对夜刀的异常确定性 |
| `teammate_overprotection` | float | [0, 1] | 是否 hard-defend 已知狼队友 + 是否缺乏公共证据 |
| `vote_coordination_failure` | float | [0, 1] | 狼队投票是否协同（分裂/投票狼队友/浪费票） |
| `night_kill_target_value` | float | [0, 1] | 刀口目标的动态价值（Seer>Witch>Guard>Hunter>Villager） |
| `counterfactual_target_gap` | float | [0, 1] | 当前目标 vs 可选最佳目标的价值差 |
| `speech_grounding_score` | float | [0, 1] | 发言是否引用公共事实而非纯断言 |

### BadCase-002 实际特征值

| 机会 | leak | overprotect | vote_fail | kill_value | kill_gap | grounding |
|------|:----:|:----------:|:---------:|:----------:|:--------:|:---------:|
| P1 speech (狼视角暴露) | **0.90** | 0.00 | — | — | — | 0.44 |
| P2 speech (硬保队友) | 0.00 | **0.70** | — | — | — | 0.51 |
| P1 vote (投票分裂) | — | — | 0.20 | — | — | — |
| P2 vote (投票分裂) | — | — | **0.40** | — | — | — |
| P1 N1 kill (刀村民) | — | — | — | 0.25 | **0.70** | — |
| P2 N2 kill (刀村民) | — | — | — | 0.25 | **0.70** | — |

---

## 四、Calibration：纯 Soft，零 Hard Cap

### 设计原则

```
calibrated_q = raw_model_q - Σ(penalty_weight_i × feature_value_i)
```

每个 penalty 的权重是固定的比例系数，效果与特征值成正比：
- `wolf_perspective_leak`: 0.50 × leak_score (0.90 → -0.45)
- `teammate_overprotection`: 0.50 × overprotection (0.70 → -0.35)
- `vote_coordination_failure`: 0.50 × vote_failure (0.40 → -0.20)
- `low_value_kill_target`: 0.70 × kill_gap (0.70 → -0.49)
- `speech_ungrounded`: 0.30 × (0.50 - grounding) (0.44 → -0.02)
- `witch_poison_target_village`: -0.55 (fixed for binary signal)
- `hunter_shot_target_village`: -0.55 (fixed for binary signal)
- `private_info_withheld`: -0.50 (fixed for binary signal)
- `voted_elsewhere_despite_known_wolf`: -0.50 (fixed for binary signal)
- `consecutive_same_guard_target`: -0.40 (fixed for binary signal)

**无 `min(q, X)` 硬封顶。**

### BadCase-002 raw → calibrated 对照

| 机会 | raw_q | penalty | calibrated_q | 原因 |
|------|:-----:|:------:|:-----------:|------|
| P1 speech (狼视角暴露) | 0.994 | -0.470 | **0.524** | leak(0.45) + ungrounded(0.02) |
| P2 speech (硬保队友) | 0.994 | -0.368 | **0.626** | overprotect(0.35) + ungrounded(0.02) |
| P1 vote (分裂) | 0.645 | -0.100 | **0.545** | vote_failure(0.10) |
| P2 vote (分裂) | 0.659 | -0.200 | **0.459** | vote_failure(0.20) |
| P1 N1 kill (低价值) | 0.966 | -0.466 | **0.500** | kill_gap(0.49) - speech_ungrounded(0.024) |
| P2 N2 kill (低价值) | 0.927 | -0.420 | **0.507** | kill_gap(0.49) - speech_ungrounded(0.07) |

### BadCase-001 对照（确认无回归）

| 机会 | raw_q | penalty | calibrated_q |
|------|:-----:|:------:|:-----------:|
| P3 speech (隐藏查杀) | 0.996 | -0.518 | **0.478** |
| P3 vote (不投已知狼) | 0.401 | -1.00 | **0.000** |
| P6 hunter_shot (打死预言家) | 0.976 | -0.550 | **0.426** |
| P4 witch_poison (毒死守卫) | 0.956 | -0.550 | **0.406** |
| P5 guard d2 (连续自守) | 0.768 | -0.400 | **0.368** |

---

## 五、测试结果（9/9 PASS）

| 测试 | 状态 | 验证内容 |
|------|:----:|------|
| test_badcase_002_wolf_low_quality_scores_low | PASS | P1 MetricsCalculator ≤70, P3 > P1 |
| test_badcase_002_detects_wolf_perspective_leak | PASS | P1 leak_score=0.90 > 0.30 |
| test_badcase_002_detects_teammate_overprotection | PASS | P2 overprotection=0.70 > 0.30, gap ≥0.05 |
| test_badcase_002_detects_vote_coordination_failure | PASS | P2 vote_fail=0.40 ≥0.30, ≥1 vote cal≤0.60 |
| test_badcase_002_low_value_kill | PASS | N2 kill gap≥0.30, cal≤0.55 |
| test_badcase_002_dynamic_features_nonzero | PASS | 6/6 dynamic features active |
| test_badcase_002_uses_soft_calibration | PASS | Hard caps ≤3, most are soft |
| test_badcase_002_process_score_v2_separates | PASS | P3 > P1, P3 > P2 |
| test_badcase_002_pairwise_candidates_generated | PASS | 4 candidates with bad/good descriptions |

---

## 六、Pairwise Candidates（可用于训练）

| # | 类型 | 坏决策 | 好反事实 |
|:--:|------|--------|----------|
| 1 | wolf_speech_quality | 硬保被查杀队友，无证据 | 轻切割："P1 发言确实差，先听投票" |
| 2 | wolf_vote_coordination | 分裂投票 P1→P3, P2→P5 | 统一投票 P3（暴露预言家） |
| 3 | werewolf_kill_target | 刀 P7 村民（暴露预言家存活） | 刀 P3 暴露预言家 |
| 4 | wolf_speech_grounding | 纯断言"P3 假预言家"无引用 | 引用投票记录质疑"P3 昨天的发言与投票不一致" |

写入 `data/health/badcase_002_pairwise_candidates.jsonl`。

---

## 七、Process Score V2

| 玩家 | 角色 | calibrated_process | speech | 说明 |
|------|------|:-----------------:|:------:|------|
| P1 | Werewolf | 0.545 | 0.45 | 狼视角暴露+投票分裂 |
| P2 | Werewolf | 0.543 | 0.40 | 硬保队友+投票分裂+低价值刀 |
| P3 | Seer | 0.730 | 0.65 | 正确查杀+公开+投票狼人 |
| P4 | Witch | 0.556 | 0.65 | 毒狼人（正确） |
| P5 | Guard | 0.612 | 0.65 | 守预言家（正确） |
| P6 | Hunter | 0.640 | 0.65 | 投票狼人 |
| P7 | Villager | 0.650 | 0.65 | 投票狼人 |

P3-P1 gap = 0.185。狼人不因"是狼"天然高分，好人正确操作得分高于狼人低质量操作。

---

## 八、已知限制

| 限制 | 影响 | 方向 |
|------|------|------|
| 模型对 speech 全打 0.99+ | speech 的 raw_q 无区分度 | 将 speech content embeddings 加入训练 |
| calibration weights 手动设定 | 不是数据驱动 | 用 pairwise labels 学习 penalty weights |
| counterfactual_target_gap 依赖 game_features | 可能含有 post-hoc 信息 | 从 PreAction 视角重算 available targets |
| pairwise candidates 未纳入训练 | 模型未从对比中学习 | 集成到 train stage，使用 pairwise loss |
| hard cap count = 0 (完全 soft) | — | ✅ |

---

## 九、运行命令

```bash
# 运行 BadCase-002 测试
pytest tests/test_track_b_badcase_wolf_regression.py -v

# 生成 pairwise candidates
python -c "from tests.test_track_b_badcase_wolf_regression import *; ..."

# 统一 pipeline
python scripts/run_pipeline.py --stage score
```

---

## 十、结论

**BadCase-002 证明 Track B 对狼人低质量操作也能降分，不因"是狼"天然高分。**

核心机制：
1. **6 个动态 wolf 特征**量化狼人操作质量（非规则判断）
2. **纯 soft calibration**（penalty = weight × feature_value），零 hard cap
3. **4 条 pairwise candidates**为后续模型训练提供对比信号
4. **53 维 ModelFeatures**（37 base + 10 private-context + 6 wolf-specific）全部可被模型学习
5. 狼人 P1/P2 即使投"对"了目标（wolf vote for village），其狼视角暴露和硬保队友仍然拉低分数
