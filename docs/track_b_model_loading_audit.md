# Track B Model Loading Audit

> 生成时间：2026-05-28
> 审计范围：`backend/eval/scoring_models.py` + 所有训练脚本 + 所有 data/health/ 产物

## 一、训练数据清单

| 文件 | 行数 | 内容 |
|------|:---:|------|
| `data/health/labeled_opportunities.jsonl` | 641 | LLM 标注的 opportunity，含 `label.quality_score` (0-100) |
| `data/health/eval_gold_set.jsonl` | 234 | 人工审核过的金标评估集 |
| `data/health/eval_silver_set.jsonl` | 155 | 银标评估集 |
| `data/health/benchmark_dataset_v5.jsonl` | 1799 | V5 benchmark 数据集（含 feature + label） |
| `data/health/human_reviewed_labels_v6.jsonl` | 655 | V6 人工复核标签 |
| `data/health/opportunities.jsonl` | — | 全量 opportunity 提取结果 |
| `data/health/opportunity_scores_v2/v3/v4.jsonl` | — | 各版本预计算机会分数 |
| `data/health/player_scores_v2/v3/v4/v7_fixed_win.jsonl` | — | 各版本预计算玩家分数 |

**结论：训练数据充足。** 641 条 LLM 标注 + 234 金标 + 1799 benchmark = 足够训练 `DecisionQualityModel`（sklearn LogisticRegression / GradientBoostingClassifier）。

## 二、模型产物清单

| 预期路径 | 存在？ |
|----------|:------:|
| `data/health/opportunity_value_model.pkl` | **不存在** |
| `data/health/decision_quality_model.pkl` | **不存在** |
| `data/health/models/*.pkl` | **目录不存在** |
| 任何 `.pkl`/`.pickle`/`.joblib`/`.model` 文件 | **全项目零个** |

**结论：没有任何训练好的模型文件被持久化。**

## 三、当前 0.5 fallback 的具体代码路径

### 路径 1：`calculate_process_score()` 模型未传入（第 327-328 行）

```python
# backend/eval/scoring_models.py:327-328
w = w_model.predict(X)[0] if w_model else 0.5   # ← w_model=None → 0.5
q = q_model.predict(X)[0] if q_model else 0.5   # ← q_model=None → 0.5
```

### 路径 2：`predict()` 模型未训练（第 201-202, 234-235, 268-269 行）

```python
# backend/eval/scoring_models.py:201-202 (OpportunityValueModel)
def predict(self, X):
    if self.model is None or not hasattr(self.model, 'classes_'):
        return np.full(len(X), 0.5)  # ← 未 fit 或未 load → 0.5

# backend/eval/scoring_models.py:234-235 (DecisionQualityModel)
def predict(self, X):
    if self.model is None or not hasattr(self.model, 'classes_'):
        return np.full(len(X), 0.5)  # ← 未 fit 或未 load → 0.5

# backend/eval/scoring_models.py:268-269 (MistakeSeverityModel)
def predict(self, X):
    if self.model is None or not hasattr(self.model, 'coef_'):
        return np.full(len(X), 0.5)  # ← 未 fit 或未 load → 0.5
```

### 路径 3：Bayesian smoothing 默认均值（第 340 行）

```python
# backend/eval/scoring_models.py:340
mu_role = 0.5  # Default mean; should be calibrated per role
```

### 路径 4：speech_scores 缺失（第 345 行）

```python
# backend/eval/scoring_models.py:345
speech = speech_scores.get(player_id, 0.5) if speech_scores else 0.5
```

**以上四条路径全部是 silent fallback，不产生任何警告。**

## 四、BadCase-001 为什么没用上训练模型

### 根因分析

1. **`train_and_ablate.py` 从不保存模型**（第 632-636 行）

```python
# scripts/train_and_ablate.py:632-636
# Save models
ovm_path = out_dir / "opportunity_value_model.pkl"
dqm_path = out_dir / "decision_quality_model.pkl"
# (Models will be saved in their class methods)  ← 这行注释是假的！
```

训练函数 `train_opportunity_value_model()` 和 `train_decision_quality_model()` 内部创建 `model = OpportunityValueModel()`，调用 `model.fit()`，但**从不调用 `model.save()`**。

2. **没有统一的 `load_track_b_models()` 函数**

整个项目中没有任何函数用于加载预训练模型。`scoring_models.py` 中的 `save()`/`load()` 方法定义了但从未被调用。

3. **BadCase-001 测试创建未训练模型**

```python
# tests/test_track_b_badcase_regression.py:test_badcase_001_process_scores_from_opportunities
w_model = OpportunityValueModel()  # ← model.model = None
q_model = DecisionQualityModel()   # ← model.model = None
results = calculate_process_score(opp_dicts, w_model, q_model)
# → w_model.predict() → np.full(len(X), 0.5)
# → q_model.predict() → np.full(len(X), 0.5)
```

4. **V7 pipeline 不使用 sklearn 模型**

`v7_private_context.py` 使用 rule-based 函数（`score_witch_save_v7()` 等），不训练/加载 sklearn 模型。V7 产物（`player_scores_v7_fixed_win.jsonl`）是预计算的启发式分数，不是模型预测。

### 完整因果链

```
train_and_ablate.py 训练模型
  → model.fit() 成功（在内存中）
  → model.save() 从未被调用
  → 进程退出，模型丢失
  → 硬盘上无 .pkl 文件

BadCase-001 测试
  → 创建未训练的 OpportunityValueModel() / DecisionQualityModel()
  → 未调用 model.load()（因为无文件可加载）
  → predict() 检测到 model.model is None
  → 返回 np.full(len(X), 0.5)
  → process_score 对所有玩家几乎相同
```

## 五、V3-V7 "训练" 实际产出的是什么

| 版本 | 脚本 | 实际产出 | 是否保存模型 |
|------|------|----------|:----------:|
| V3 | `v3_full_pipeline.py` | opportunity_scores_v3.jsonl, player_scores_v3.jsonl | 否 |
| V4 | `v4_benchmark.py` | opportunity_scores_v4.jsonl, player_scores_v4.jsonl, pairwise_candidates | 否 |
| V5 | `v5_benchmark.py` | benchmark_dataset_v5.jsonl (带 feature + label) | 否 |
| V6 | `v6_benchmark_ready.py` | human_reviewed_labels_v6.jsonl | 否 |
| V7 | `v7_private_context.py` | player_scores_v7_fixed_win.jsonl, visibility snapshots | 否 |
| — | `train_and_ablate.py` | model_metrics.json, feature_importance.md (in-memory only) | **代码写了路径但从未调用 save()** |

**所有 V3-V7 产出的 player_scores/opportunity_scores 都是 rule-based 启发式分数，或者是单独 LLM 调用打的分，不是 sklearn 模型预测。**

## 六、当前 V7 分数的真实来源

`player_scores_v7_fixed_win.jsonl` 中的分数来自 `v7_private_context.py` 的 rule-based scorers：

| 动作 | 评分函数 | 类型 |
|------|----------|:----:|
| witch_save | `score_witch_save_v7()` | Rule-based (private context aware) |
| witch_poison | `score_witch_poison_v7()` | Rule-based |
| seer_check | `score_seer_check_v7()` | Rule-based |
| seer_release | Rule-based | Heuristic |
| hunter_shot | `score_hunter_shot_v7()` | Rule-based |
| guard_protect | `score_guard_protect_v7()` | Rule-based |
| werewolf_kill | Rule-based | Heuristic |
| vote | Rule-based | Alignment-based |
| speech | Keyword-based | Heuristic |

**不是 trained sklearn model。不是 model-assisted labels。是 rule-based scorer + precomputed jsonl。**

## 七、修复建议

### PR 1: 修复模型保存（`scripts/train_and_ablate.py`）

在 `main()` 函数的第 632-636 行，将注释替换为实际的 model.save() 调用：

```python
# Before (line 632-636):
ovm_path = out_dir / "opportunity_value_model.pkl"
dqm_path = out_dir / "decision_quality_model.pkl"
# (Models will be saved in their class methods)

# After:
ovm_path = out_dir / "opportunity_value_model.pkl"
dqm_path = out_dir / "decision_quality_model.pkl"
ovm_model.save(ovm_path)
dqm_model.save(dqm_path)
print(f"Models saved to {ovm_path} and {dqm_path}")
```

### PR 2: 新增模型加载函数（`backend/eval/scoring_models.py`）

```python
def load_track_b_models(model_dir: str | Path = "data/health") -> tuple[OpportunityValueModel, DecisionQualityModel]:
    """Load trained Track B models from disk.
    
    Returns (w_model, q_model). Raises FileNotFoundError if models missing.
    """
    model_dir = Path(model_dir)
    w_model = OpportunityValueModel()
    w_path = model_dir / "opportunity_value_model.pkl"
    if w_path.exists():
        w_model.load(w_path)
    else:
        raise FileNotFoundError(f"OpportunityValueModel not found at {w_path}. Run train_and_ablate.py first.")
    
    q_model = DecisionQualityModel()
    q_path = model_dir / "decision_quality_model.pkl"
    if q_path.exists():
        q_model.load(q_path)
    else:
        raise FileNotFoundError(f"DecisionQualityModel not found at {q_path}. Run train_and_ablate.py first.")
    
    return w_model, q_model
```

### PR 3: BadCase-001 测试加载模型

修改 `test_badcase_001_process_scores_from_opportunities`，在模型存在时加载训练模型，不存在时 FAIL（不允许 silent 0.5）。

### PR 4: 把 predict() 的 silent fallback 改成 warning

```python
# scoring_models.py:201
def predict(self, X):
    if self.model is None or not hasattr(self.model, 'classes_'):
        import warnings
        warnings.warn(f"{self.__class__.__name__}.predict() called on untrained model, returning 0.5")
        return np.full(len(X), 0.5)
```

## 八、结论

| 问题 | 答案 |
|------|------|
| A. 训练数据存在吗？ | **是**，641 labeled + 234 gold + 1799 benchmark |
| B. 训练模型文件存在吗？ | **否**，全项目零个 .pkl 文件 |
| C. BadCase-001 为什么没加载？ | 因为没有可加载的模型文件 |
| D. V3-V7 "训练" 实际产出是什么？ | 预计算 JSONL 分数（rule-based），不是可泛化 sklearn 模型 |
| E. V7 分数来源？ | **Rule-based scorers**（`v7_private_context.py` 中的启发式函数），不是 trained model |
| F. 建议默认 0.5 改 warning？ | **是**，silent fallback 掩盖了模型缺失问题 |
