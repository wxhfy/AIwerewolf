# Retrieval Policy Experiment Protocol

> 检索策略对比实验的完整协议
> 日期：2026-06-05

## 实验目标

比较不同 Retrieval Policy 对 Agent 决策质量的影响，选出最佳默认策略。

## 实验组

| 组别 | Policy | 说明 |
|------|--------|------|
| baseline_no_trackc | 关闭 Track C | 不注入策略，不提供 search_strategies 工具 |
| global_only | GLOBAL_ONLY | 仅检索全局通用策略 |
| self_mbti_only | SELF_MBTI_ONLY | 仅检索自己 MBTI 的策略 |
| same_role_all_mbti | SAME_ROLE_ALL_MBTI | 同角色所有 MBTI |
| same_role_same_mbti | SAME_ROLE_SAME_MBTI | 同角色同 MBTI |
| hybrid_role_mbti_global | HYBRID_ROLE_MBTI_GLOBAL | 3 层混合（推荐默认） |
| hybrid_role_alignment_phase | HYBRID_ROLE_ALIGNMENT_PHASE | 4 层 + phase 约束 |

## 约束条件

1. **不允许 fallback** — 严格模式 `ALLOW_FALLBACK=false`
2. **不允许 candidate 进入对局检索** — 只检索 `status=active` 文档
3. **固定 active 策略池** — 实验前 snapshot
4. **固定 seed 集合** — 所有组相同 seeds
5. **固定模型和 MBTI 分配**

## 离线评估

```bash
python scripts/evaluate_retrieval_policies.py
```

### 离线权重

```
offline_score =
  0.30 × nDCG@5
+ 0.20 × Precision@3
+ 0.15 × CoverageRate
+ 0.15 × AverageRelevance
+ 0.10 × RoleMatchRate
+ 0.05 × MBTIMatchRate
- 1.00 × CandidateLeakagePenalty
```

## 在线评估

```bash
# Smoke test
python scripts/run_retrieval_policy_ablation.py --games 1

# Small experiment
python scripts/run_retrieval_policy_ablation.py --games 5

# Full experiment
python scripts/run_retrieval_policy_ablation.py --games 20
```

### 统计方法

- Paired seed comparison
- Bootstrap 95% CI (10,000 resamples)
- Cohen's d 效应量
- Permutation test p-value (10,000 permutations)

### 在线评分权重

```
online_score =
  0.30 × process_score
+ 0.20 × vote_accuracy
+ 0.15 × speech_quality
+ 0.15 × skill_efficiency
+ 0.10 × strategy_usage_quality
- 0.05 × invalid_action_rate
- 0.05 × cost_penalty
```

### 最终评分

```
final_score = 0.45 × offline_score + 0.55 × online_score
```

## 离线评估结果 (2026-06-05)

**Query set**: 26 queries (6 角色 × 4 MBTI)
**Retriever**: 1065 docs from PostgreSQL

### 综合排名

| Rank | Policy | Offline Score | P@3 | nDCG@5 | Coverage | RoleMatch | MBTIMatch | P@1 | MRR |
|------|--------|:-------------:|:---:|:------:|:--------:|:---------:|:---------:|:---:|:---:|
| 1 | `same_role_same_mbti` | **0.7614** | 0.49 | 0.97 | 1.00 | 1.00 | 0.92 | 0.54 | 0.60 |
| 2 | `hybrid_role_mbti_global` | **0.7412** | 0.47 | 0.94 | 1.00 | 1.00 | 0.84 | 0.42 | 0.59 |
| 3 | `same_role_all_mbti` | **0.7364** | 0.45 | 0.94 | 1.00 | 1.00 | 0.84 | 0.46 | 0.61 |
| 4 | `hybrid_role_alignment_phase` | **0.7114** | 0.50 | 0.94 | 1.00 | 0.65 | 0.86 | 0.42 | 0.59 |
| 5 | `self_mbti_only` | **0.6963** | 0.41 | 0.95 | 1.00 | 0.61 | 1.00 | 0.50 | 0.61 |
| 6 | `global_only` | **0.0386** | 0.38 | 0.67 | 0.69 | 0.69 | 0.69 | 0.35 | 0.42 |

### 完整指标明细

| Metric | global_only | self_mbti | same_role_all | same_role_same | hybrid_role_mbti | hybrid_align_phase |
|--------|:-----------:|:----------:|:------------:|:-------------:|:----------------:|:------------------:|
| P@1 | 0.346 | 0.500 | 0.462 | **0.538** | 0.423 | 0.423 |
| P@3 | 0.385 | 0.410 | 0.449 | **0.494** | 0.474 | 0.500 |
| P@5 | 0.370 | 0.392 | 0.462 | **0.512** | 0.462 | 0.431 |
| R@3 | 0.500 | 0.692 | 0.731 | 0.615 | 0.731 | **0.769** |
| R@5 | 0.500 | 0.808 | 0.846 | 0.731 | 0.846 | **0.846** |
| MRR | 0.417 | 0.606 | **0.610** | 0.602 | 0.591 | 0.592 |
| nDCG@3 | 0.650 | 0.877 | 0.861 | **0.931** | 0.867 | 0.885 |
| nDCG@5 | 0.670 | 0.946 | 0.939 | **0.970** | 0.938 | 0.941 |
| Avg Relevance | 1.06 | 1.39 | 1.46 | **1.51** | 1.46 | 1.43 |
| Role Match | 0.69 | 0.61 | **1.00** | **1.00** | **1.00** | 0.65 |
| MBTI Match | 0.69 | **1.00** | 0.84 | 0.92 | 0.84 | 0.86 |
| Phase Match | 0.48 | 0.64 | 0.61 | **0.73** | 0.64 | 0.62 |
| Coverage | 0.69 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Diversity | 0.59 | 0.51 | 0.72 | **0.87** | 0.74 | 0.68 |
| Empty (N) | 8 | 0 | 0 | 0 | 0 | 0 |
| Leak (N) | 0 | 0 | 0 | 0 | 0 | 0 |
| P50 Latency (ms) | 29.7 | 31.2 | 42.6 | 37.2 | 29.6 | 29.1 |

### 假设验证

| ID | 假设 | 预期 | 实际 | 结论 |
|----|------|------|------|------|
| H1 | SELF_MBTI sparse | coverage < 50% | coverage 100%, P@3=0.41 | **推翻** — MBTI 标签稀疏导致几乎所有 doc 通过 |
| H2 | SAME_ROLE stable | coverage > 90% | coverage 100%, P@3=0.45 | **证实** — 同角色检索覆盖率完美 |
| H3 | SAME_ROLE_MBTI sparse | coverage < 30% | coverage 100%, P@3=0.49 | **推翻** — 同上，MBTI 空值导致高覆盖率 |
| H4 | HYBRID best default | best balance | P@3=0.47, nDCG5=0.94, coverage 100% | **部分证实** — offline 第二但更稳健 |
| H5 | ALIGNMENT_PHASE narrow | coverage < 60% | coverage 100%, RoleMatch 0.65 | **部分证实** — RoleMatch 下降明显 |

### 关键发现

1. **所有非 global_only 的 policy 覆盖率都是 100%** — 因为当前 DB 中大部分 doc 的 mbti_scope 为空，空值在过滤时被当作"匹配所有 MBTI"
2. **`same_role_same_mbti` 离线得分最高** (0.7614)，但随着 MBTI 标注增加覆盖率会下降
3. **`hybrid_role_mbti_global` 更稳健** (0.7412) — 有全局 fallback，适合作为默认策略
4. **`global_only` 严重不足** — Coverage 仅 69%，8/26 queries 空结果
5. **H1/H3 被推翻的原因** — 当前 MBTI 标签覆盖率低，需要更大规模标注后重新验证

### 推荐默认策略

**`hybrid_role_mbti_global`** — 尽管离线分略低于 `same_role_same_mbti`，但分层结构保证了 MBTI 标签增加后覆盖率不下降。`same_role_same_mbti` 在当前稀疏标签下表现好，但随标注密度提升会趋于严格。

## 在线评估

```bash
# Smoke test
python scripts/run_retrieval_policy_ablation.py --games 1

# Small experiment
python scripts/run_retrieval_policy_ablation.py --games 5

# Full experiment
python scripts/run_retrieval_policy_ablation.py --games 20
```

### 统计方法

- Paired seed comparison
- Bootstrap 95% CI (10,000 resamples)
- Cohen's d 效应量
- Permutation test p-value (10,000 permutations)

### 在线评分权重

```
online_score =
  0.30 × process_score
+ 0.20 × vote_accuracy
+ 0.15 × speech_quality
+ 0.15 × skill_efficiency
+ 0.10 × strategy_usage_quality
- 0.05 × invalid_action_rate
- 0.05 × cost_penalty
```

### 最终评分

```
final_score = 0.45 × offline_score + 0.55 × online_score
```

## 输出

- `outputs/retrieval_policy_eval/results.json` — 离线评估
- `outputs/retrieval_policy_eval/results.csv` — 离线 CSV
- `outputs/retrieval_policy_eval/summary.md` — 离线总结
- `outputs/retrieval_policy_ablation/results.json` — 在线评估
- `outputs/retrieval_policy_ablation/summary.md` — 在线总结

## 最终离线评估 (2026-06-05, with MBTI+Action+Quality weighting)

| Rank | Policy | Score | P@3 | nDCG@5 | Cov | Empty | Leak |
|------|--------|:-----:|:---:|:------:|:---:|:-----:|:----:|
| 1 | `same_role_same_mbti` | **0.7685** | 0.52 | 0.98 | 1.00 | 0 | 0 |
| 2 | `hybrid_role_mbti_global` | **0.7455** | 0.49 | 0.94 | 1.00 | 0 | 0 |
| 3 | `same_role_all_mbti` | **0.7406** | 0.46 | 0.94 | 1.00 | 0 | 0 |
| 4 | `hybrid_role_alignment_phase` | **0.7095** | 0.49 | 0.94 | 1.00 | 0 | 0 |
| 5 | `self_mbti_only` | **0.6976** | 0.41 | 0.95 | 1.00 | 0 | 0 |
| 6 | `global_only` | **0.0592** | 0.37 | 0.71 | 0.73 | 7 | 0 |

### 关键结论

1. **Candidate Leakage: 所有 policy = 0** ✓
2. **Coverage: 非 global_only 全部 100%** ✓ (MBTI 空值导致，标注增加后会分化)
3. **Empty: 只有 global_only 有 7/26 空结果** ✗ (不应作为默认策略)
4. **推荐 `hybrid_role_mbti_global`** — 离线第二 (0.7455)，分层 fallback 最稳健

### 答辩一句话

```
同职业经验优先，自己 MBTI 经验加权，全局高质量策略兜底，
带质量门槛的 1:1:1 分桶填充。
```
