# Track B MBTI/Profile Evaluation v0 Report

> Base model: deepseek-v4-pro[1m]
> Total games: 12
> Source: real_llm_game (same-profile mode)
> Generated: 2026-05-30T08:51:35

---

## 1. Executive Summary

- **最高 process score**: **ISTJ-conservative** (ISTJ) — 57.98
- **最低 process score**: ENFP-social-chaotic (ENFP) — 56.11
- **分差**: 1.87
- **发言最高**: ENTJ-shotcaller (0.58)
- **投票最高**: ISTJ-conservative (0.62)
- **技能最高**: ISTJ-conservative (0.62)
- **存活最高**: ENTJ-shotcaller (0.85)

> ⚠️ **重要提示**: MBTI 标签是 strategy profiles（策略画像），不是心理学真实性验证。
> 每个 profile 仅 3 局，属于低样本 smoke test。

---

## 2. Experiment Setup

| 参数 | 值 |
| --- | --- |
| **底座模型** | deepseek-v4-pro[1m] |
| **Profiles** | 4 个 MBTI-style strategy profiles |
| **每 profile 局数** | 3 |
| **模式** | same-profile（同局所有玩家使用相同 profile） |
| **单局玩家数** | 7 |
| **来源** | real_llm_game |
| **评分来源** | review.py MetricsCalculator process_score |

### Profiles

| Profile | MBTI | Style | Description |
| --- | --- | --- | --- |
| ISTJ-conservative | ISTJ | passive | 证据优先、低风险、稳定执行、不冒进 |
| ENTJ-shotcaller | ENTJ | aggressive | 强势归票，主动领导，快速决策，善于推动票型 |
| INTJ-strategist | INTJ | analytical | 长线规划，重视证据和反事实推理，发言精准克制 |
| ENFP-social-chaotic | ENFP | chaotic | 高互动、多发言、信息开放、容易被新发言影响 |

---

## 3. Profile Leaderboard

| Rank | Profile | Games | Process | Speech | Vote | Skill | Survival | Critical Rate | Win Rate | CI (95%) | Warning |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | ISTJ-conservative | 3 | 57.98 | 0.57 | 0.62 | 0.62 | 0.83 | 0.29 | 0.67 | [47.57, 68.39] | LOW_SAMPLE |
| 2 | ENTJ-shotcaller | 3 | 57.95 | 0.58 | 0.61 | 0.59 | 0.85 | 0.24 | 1.0 | [48.45, 67.45] | LOW_SAMPLE |
| 3 | INTJ-strategist | 3 | 56.27 | 0.58 | 0.61 | 0.59 | 0.85 | 0.29 | 1.0 | [46.25, 66.29] | LOW_SAMPLE |
| 4 | ENFP-social-chaotic | 3 | 56.11 | 0.58 | 0.6 | 0.61 | 0.79 | 0.33 | 0.67 | [44.81, 67.41] | LOW_SAMPLE |

---

## 4. Speech Act Distribution

> 来自 SpeechSemanticScorer v0 (audit-only, 不影响主分)

| Profile | Evidence Grounding | Actionability | Identity Claim | Pressure | Info Seeking | Defensive |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ISTJ-conservative | 0.192 | 0.098 | 0.084 | 0.161 | 0.469 | 0.368 |
| ENTJ-shotcaller | 0.192 | 0.098 | 0.084 | 0.161 | 0.469 | 0.368 |
| INTJ-strategist | 0.192 | 0.098 | 0.084 | 0.161 | 0.469 | 0.368 |
| ENFP-social-chaotic | 0.192 | 0.098 | 0.084 | 0.161 | 0.469 | 0.368 |

---

## 5. Expected vs Observed

| Profile | Expected Behavior | Observed Pattern | Match? |
| --- | --- | --- | --- |
| ISTJ-conservative | 低 critical mistake rate, 低 identity_claim | evidence=0.19, action=0.10, critical_rate=0.29 | partial |
| ENTJ-shotcaller | 高 actionability, 高 pressure, 高 vote_score | evidence=0.19, action=0.10, critical_rate=0.24 | weak |
| INTJ-strategist | 高 evidence_grounding, 低 defensive_posture, 低 critical mistake rate | evidence=0.19, action=0.10, critical_rate=0.29 | weak |
| ENFP-social-chaotic | 高 information_seeking, 高 defensive_posture, speech 波动大 | evidence=0.19, action=0.10, critical_rate=0.33 | partial |

---

## 6. Dimension Breakdown

| Profile | Main Strength | Main Weakness | Evidence |
| --- | --- | --- | --- |
| ISTJ-conservative | 存活 (0.83) | 发言 (0.57) | avg_survival_score=0.83, avg_speech_score=0.57 |
| ENTJ-shotcaller | 存活 (0.85) | 发言 (0.58) | avg_survival_score=0.85, avg_speech_score=0.58 |
| INTJ-strategist | 存活 (0.85) | 发言 (0.58) | avg_survival_score=0.85, avg_speech_score=0.58 |
| ENFP-social-chaotic | 存活 (0.79) | 发言 (0.58) | avg_survival_score=0.79, avg_speech_score=0.58 |

---

## 7. Role Breakdown

| Profile | Role | Samples | Low Sample |
| --- | --- | ---: | --- |
| ISTJ-conservative | Guard | 3 |  |
| ISTJ-conservative | Hunter | 3 |  |
| ISTJ-conservative | Seer | 3 |  |
| ISTJ-conservative | Villager | 3 |  |
| ISTJ-conservative | Werewolf | 6 |  |
| ISTJ-conservative | Witch | 3 |  |
| ENTJ-shotcaller | Guard | 3 |  |
| ENTJ-shotcaller | Hunter | 3 |  |
| ENTJ-shotcaller | Seer | 3 |  |
| ENTJ-shotcaller | Villager | 3 |  |
| ENTJ-shotcaller | Werewolf | 6 |  |
| ENTJ-shotcaller | Witch | 3 |  |
| INTJ-strategist | Guard | 3 |  |
| INTJ-strategist | Hunter | 3 |  |
| INTJ-strategist | Seer | 3 |  |
| INTJ-strategist | Villager | 3 |  |
| INTJ-strategist | Werewolf | 6 |  |
| INTJ-strategist | Witch | 3 |  |
| ENFP-social-chaotic | Guard | 3 |  |
| ENFP-social-chaotic | Hunter | 3 |  |
| ENFP-social-chaotic | Seer | 3 |  |
| ENFP-social-chaotic | Villager | 3 |  |
| ENFP-social-chaotic | Werewolf | 6 |  |
| ENFP-social-chaotic | Witch | 3 |  |

---

## 8. Representative Reviews

### ISTJ-conservative (ISTJ)

- **蓝知怀** (Villager) Day 3 — minor
  - 描述: 蓝知怀 voted villager-side players in consecutive rounds.
  - 建议: Reassess why your reads keep landing on villagers and compare your vote path with public flips.

- **司南** (Hunter) Day 1 — major
  - 描述: 司南 voted a checked-good player 齐慕白.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

### ENTJ-shotcaller (ENTJ)

- **蓝知怀** (Villager) Day 3 — minor
  - 描述: 蓝知怀 voted villager-side players in consecutive rounds.
  - 建议: Reassess why your reads keep landing on villagers and compare your vote path with public flips.

- **司南** (Hunter) Day 1 — major
  - 描述: 司南 voted a checked-good player 齐慕白.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

### INTJ-strategist (INTJ)

- **蓝知怀** (Villager) Day 1 — major
  - 描述: 蓝知怀 voted a checked-good player 苏晓晓.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

- **司南** (Hunter) Day 1 — major
  - 描述: 司南 voted a checked-good player 齐慕白.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

### ENFP-social-chaotic (ENFP)

- **蓝知怀** (Villager) Day 3 — minor
  - 描述: 蓝知怀 voted villager-side players in consecutive rounds.
  - 建议: Reassess why your reads keep landing on villagers and compare your vote path with public flips.

- **司南** (Hunter) Day 1 — major
  - 描述: 司南 voted a checked-good player 齐慕白.
  - 建议: Respect confirmed good information and reevaluate the read chain before voting.

---

## 9. Validity Evidence

### 9.1 Sensitivity

不同 profile 是否产生可见的维度差异？

- Process score 跨 profile 范围: **1.87** 分
- Speech audit evidence_grounding 范围: **0.0**
- 存在维度级差异: 有限

### 9.2 Specificity

差异是否落在预期维度？

见 §5 Expected vs Observed 表。

### 9.3 Reviewability

见 §8 Representative Reviews。

### 9.4 Robustness

- 每个 profile 仅 3 局，趋势不可靠
- 同一 profile 内各 seed 间存在随机波动
- 需要 ≥10 局/profile 才能做稳健性判断
- 当前仅提供方向性信号

---

## 10. Limitations

- **MBTI 标签是 strategy profiles**，不是心理学真实性验证
- **低样本**: 每个 profile 仅 3 局，不构成统计显著结论
- **SpeechSemanticScorer 是 audit-only**，不影响 process score
- **speech act ≠ speech quality**：发言行为分类不等于发言质量
- **无人工验证**: 没有 human pairwise labels 或 speech quality labels
- **same-profile 模式**: 同局内所有玩家使用相同 profile，未测试 mixed-profile 对抗
- **PairwiseRanker 保持 audit/debug only**

---

## 11. Next Steps

1. **扩样本**: 每个 profile 至少 10 局
2. **Mixed-profile rotation**: 同局内混合不同 profile 对抗
3. **人工复核**: 30 个 critical decisions 的 human review
4. **Speech semantic human validation**: ≥50 speech samples with human quality labels
5. **Cross-model**: 在固定 profile 下比较不同底座模型
