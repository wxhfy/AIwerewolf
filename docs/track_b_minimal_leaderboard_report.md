# Track B Minimal Leaderboard Demo Report

> 生成时间: 2026-05-29T21:56:44
> 评分方法: review.py MetricsCalculator process_score (outcome-independent)
> 来源: real_llm_game
> 总局数: 6

---

## 1. Executive Summary

- **排名第一**: **llm-dsv4pro-v1**（deepseek-v4-pro[1m]）— avg process score 57.7
- **排名第二**: llm-dsv4flash-v1（deepseek-v4-flash[1m]）— avg process score 55.98
- **分差**: 1.72 分
- **主要差异维度**: 待分析
- **样本量**: 每个版本 3 局，共 6 局
- **差异维度**: avg_skill_score (-0.02), avg_survival_score (+0.06)

> ⚠️ **重要提示**: 这是一个低样本量的 Leaderboard smoke test（每个版本仅 3 局），
> 不是统计可靠的正式 benchmark。排名和分差可能随更多对局而变化。

---

## 2. Experiment Setup

| 参数 | 值 |
| --- | --- |
| **Agent 版本** | llm-dsv4pro-v1, llm-dsv4flash-v1 |
| **模型** | deepseek-v4-pro[1m], deepseek-v4-flash[1m] |
| **每版本局数** | 3 |
| **Seeds** | [100, 200, 300] |
| **单局玩家数** | 7 |
| **最高天数** | 5 |
| **来源** | real_llm_game |
| **角色分配** | 7人标准局：狼人×2 + 预言家 + 女巫 + 守卫 + 猎人 + 村民 |
| **评分来源** | review.py MetricsCalculator (6-dim formula) |
| **排名指标** | outcome-independent process_score（不受阵营胜负影响） |

---

## 3. Leaderboard

| Rank | Agent Version | Model | Games | Avg Process | Speech | Vote | Skill | Survival | Critical Mistake Rate | Confidence (95%) | Warning |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | llm-dsv4pro-v1 | deepseek-v4-pro[1m] | 3 | 57.7 | 0.58 | 0.61 | 0.59 | 0.85 | 0.24 | [48.14, 67.26] | LOW_SAMPLE |
| 2 | llm-dsv4flash-v1 | deepseek-v4-flash[1m] | 3 | 55.98 | 0.59 | 0.6 | 0.61 | 0.79 | 0.33 | [44.82, 67.14] | LOW_SAMPLE |

---

## 4. Role Breakdown

### llm-dsv4pro-v1

| Role | Samples | Avg Process | Avg Vote | Avg Speech | Avg Skill | Low Sample |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Seer | 3 | 87.73 | 0.92 | 0.78 | 0.8 |  |
| Witch | 3 | 60.77 | 0.22 | 0.51 | 0.72 |  |
| Guard | 3 | 27.92 | 0.56 | 0.54 | 0.0 |  |
| Hunter | 3 | 47.26 | 0.5 | 0.53 | 0.5 |  |
| Werewolf | 6 | 71.84 | 0.85 | 0.58 | 0.82 |  |
| Villager | 3 | 36.57 | 0.36 | 0.58 | 0.5 |  |

### llm-dsv4flash-v1

| Role | Samples | Avg Process | Avg Vote | Avg Speech | Avg Skill | Low Sample |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Seer | 3 | 80.39 | 0.92 | 0.78 | 0.73 |  |
| Witch | 3 | 59.39 | 0.22 | 0.5 | 0.7 |  |
| Guard | 3 | 14.18 | 0.33 | 0.52 | 0.0 |  |
| Hunter | 3 | 57.48 | 0.61 | 0.56 | 0.67 |  |
| Werewolf | 6 | 75.8 | 0.88 | 0.59 | 0.84 |  |
| Villager | 3 | 28.82 | 0.36 | 0.59 | 0.5 |  |

---

## 5. Per-Game Summary

| Game ID | Version | Seed | Winner | Days | Events | Bad Cases | CFs | Avg Process |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `cb62c1c5` | llm-dsv4flash-v1 | 100 | village | 3 | 163 | 2 | 3 | 58.4757 |
| `85391f0c` | llm-dsv4flash-v1 | 200 | village | 3 | 174 | 3 | 1 | 51.4486 |
| `c622c396` | llm-dsv4flash-v1 | 300 | wolf | 3 | 147 | 2 | 3 | 58.0171 |
| `4afe583d` | llm-dsv4pro-v1 | 100 | village | 3 | 164 | 2 | 3 | 59.0814 |
| `6bd86b71` | llm-dsv4pro-v1 | 200 | village | 3 | 173 | 3 | 1 | 51.3214 |
| `75f49e38` | llm-dsv4pro-v1 | 300 | village | 2 | 124 | 0 | 0 | 62.7114 |

---

## 6. Representative Critical Mistakes

### llm-dsv4flash-v1 — seed=100

- **蓝知怀**（Villager）Day 3
  - 类型: vote
  - 严重程度: minor
  - 描述: 蓝知怀 voted villager-side players in consecutive rounds.
  - 建议: Reassess why your reads keep landing on villagers and compare your vote path with public flips.

- **穆冬青**（Guard）Day 1
  - 类型: vote
  - 严重程度: major
  - 描述: 穆冬青 voted a checked-good player 蓝知怀.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

### llm-dsv4flash-v1 — seed=200

- **司南**（Hunter）Day 2
  - 类型: vote
  - 严重程度: major
  - 描述: 司南 voted a checked-good player 齐慕白.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

- **鲁西门**（Guard）Day 1
  - 类型: vote
  - 严重程度: major
  - 描述: 鲁西门 voted a checked-good player 司南.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

### llm-dsv4flash-v1 — seed=300

- **陈小玉**（Villager）Day 1
  - 类型: vote
  - 严重程度: major
  - 描述: 陈小玉 voted a checked-good player 墨小染.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

- **陶若安**（Guard）Day 1
  - 类型: vote
  - 严重程度: major
  - 描述: 陶若安 voted a checked-good player 墨小染.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

### llm-dsv4pro-v1 — seed=100

- **蓝知怀**（Villager）Day 3
  - 类型: vote
  - 严重程度: minor
  - 描述: 蓝知怀 voted villager-side players in consecutive rounds.
  - 建议: Reassess why your reads keep landing on villagers and compare your vote path with public flips.

- **穆冬青**（Guard）Day 1
  - 类型: vote
  - 严重程度: major
  - 描述: 穆冬青 voted a checked-good player 蓝知怀.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

---

## 7. Interpretation

### llm-dsv4pro-v1 vs llm-dsv4flash-v1

**llm-dsv4pro-v1** 的 avg_process_score 高出 **1.72 分**。

#### 优势维度
- **发言**: 基本持平（0.58 vs 0.59）
- **投票**: 基本持平（0.61 vs 0.6）
- **技能**: -0.02（0.59 vs 0.61）— llm-dsv4flash-v1 略优
- **存活**: +0.06（0.85 vs 0.79）

#### llm-dsv4flash-v1 的主要弱点
- 关键错误率高出 0.09（0.33 vs 0.24）

#### 可信度评估

- 每个版本仅 3 局，样本量不足以得出统计显著结论
- 需要至少 10+10 局才能进行初步正式对比
- 排名方向性可信，但精确分差不可靠
- 建议固定 seeds 和角色轮换来减少角色分配的随机差异

---

## 8. Rubric Alignment

| Rubric Item | Status | Evidence |
| --- | --- | --- |
| Multi-dimensional evaluation | **PASS** | 6-dim formula: speech/vote/skill/survival/role_task/mistake_penalty |
| Key decision review | **PASS** | BadCaseDetector identifies critical mistakes per game |
| Counterfactual reasoning | **PASS** | Pipeline generates counterfactuals for each bad case |
| Structured report | **PASS** | Markdown + HTML reports via generate_published_review_document |
| Leaderboard | **PASS_SMOKE** | 6 real LLM games, 2 agent versions compared, low-sample smoke test |

---

## 9. Limitations

- **样本量不足**: 每个版本仅 3 局，不构成统计显著 benchmark
- **角色分布不均**: 同一 seed 下角色固定，角色分配可能影响 agent 表现
- **没有真实人工标注**: human pairwise labels pending
- **PairwiseRanker 未参与主评分**: 仅为辅助信号
- **ProcessScoreV3 未使用**: 当前使用 review.py MetricsCalculator process_score
- **单一模型族对比**: 两个版本都是 DeepSeek V4 系列，差异有限
- **不是正式 benchmark**: 仅作为 pipeline smoke test 和基础设施验证

---

## 10. Next Steps

1. **扩样本**: 每个版本至少 10 局，使用固定 seed 集和角色轮换
2. **加真实 LLM agent**: 接入更多模型（如 DeepSeek V3.2, Doubao Seed 2.0）进行跨模型族对比
3. **加 Human pairwise validation**: 收集真实人工标注来校准评分
4. **提升到正式 benchmark**: 10+ games × 3+ model families + human labels + ProcessScoreV3
