# AI Werewolf — Learned Evaluator Review Report v1

**Games reviewed**: 3
**Players reviewed**: 21
**Scoring system**: Opportunity-aware learned evaluation (Track B v2)

## Scoring Components
- **ProcessScore** = 0.40 × RoleProcessScore + 0.20 × SpeechScore + 0.15 × CounterfactualImpact + 0.15 × (1−MistakePenalty) + 0.10 × Robustness
- **RoleProcessScore**: Bayesian-smoothed opportunity-level w(o)×q(o)
- **SpeechScore**: groundedness + stance_clarity + consistency + strategic_value + information_safety
- **CounterfactualImpact**: vote_flip + skill_swap what-if analysis
- **Model confidence**: α = total_weight / (total_weight + k), k=2.0

---
## Guard — P1

| Metric | Value |
|--------|-------|
| FinalScore | **47.6** |
| ProcessScore | 56.0 |
| RoleProcessScore | 52.6 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 6 (weight=5.0) |
| Model Confidence | 0.71 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [guard_protect] D1 — score=0.800
2. [vote] D1 — score=0.624
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.312
2. [vote] D2 — score=0.312
3. [guard_protect] D2 — score=0.300

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Werewolf — P4

| Metric | Value |
|--------|-------|
| FinalScore | **40.3** |
| ProcessScore | 47.4 |
| RoleProcessScore | 36.7 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.150 |
| Opportunities | 6 (weight=5.0) |
| Model Confidence | 0.72 |
| Won | ✗ |

### Top 3 Good Opportunities
1. [werewolf_kill] D1 — score=0.400
2. [speech] D1 — score=0.312
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [werewolf_kill] D2 — score=0.200
2. [werewolf_kill] D3 — score=0.200
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 决策质量偏低，建议参考策略库中同角色高质量案例
- 存在较多低质量决策，减少无依据的随机行为
- 重点关注werewolf_kill类型决策的改善

---

## Werewolf — P6

| Metric | Value |
|--------|-------|
| FinalScore | **38.7** |
| ProcessScore | 45.5 |
| RoleProcessScore | 33.7 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.200 |
| Opportunities | 6 (weight=5.2) |
| Model Confidence | 0.72 |
| Won | ✗ |

### Top 3 Good Opportunities
1. [werewolf_kill] D1 — score=0.400
2. [speech] D1 — score=0.312
3. [werewolf_kill] D2 — score=0.200

### Top 3 Bad Opportunities
1. [werewolf_kill] D3 — score=0.200
2. [vote] D1 — score=0.156
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 决策质量偏低，建议参考策略库中同角色高质量案例
- 存在较多低质量决策，减少无依据的随机行为
- 重点关注werewolf_kill类型决策的改善

---

## Witch — P5

| Metric | Value |
|--------|-------|
| FinalScore | **46.4** |
| ProcessScore | 54.6 |
| RoleProcessScore | 50.9 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.050 |
| Opportunities | 6 (weight=5.0) |
| Model Confidence | 0.72 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [witch_poison] D3 — score=1.000
2. [witch_save] D1 — score=0.500
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.312
2. [witch_save] D2 — score=0.300
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注vote类型决策的改善

---

## Seer — P2

| Metric | Value |
|--------|-------|
| FinalScore | **49.0** |
| ProcessScore | 57.7 |
| RoleProcessScore | 56.7 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 6 (weight=4.8) |
| Model Confidence | 0.71 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [seer_check] D1 — score=0.800
2. [vote] D1 — score=0.624
3. [seer_release] D1 — score=0.500

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.312
2. [speech] D1 — score=0.312
3. [vote] D1 — score=0.312

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Villager — P3

| Metric | Value |
|--------|-------|
| FinalScore | **50.6** |
| ProcessScore | 59.5 |
| RoleProcessScore | 61.2 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 3 (weight=2.2) |
| Model Confidence | 0.52 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [vote] D1 — score=0.624
2. [vote] D1 — score=0.624
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.624
2. [vote] D1 — score=0.624
3. [speech] D1 — score=0.312

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Hunter — P7

| Metric | Value |
|--------|-------|
| FinalScore | **46.7** |
| ProcessScore | 55.0 |
| RoleProcessScore | 51.8 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.050 |
| Opportunities | 5 (weight=4.0) |
| Model Confidence | 0.66 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [hunter_shot] D3 — score=1.000
2. [vote] D1 — score=0.312
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.312
2. [vote] D3 — score=0.312
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注vote类型决策的改善

---

## Guard — P4

| Metric | Value |
|--------|-------|
| FinalScore | **45.2** |
| ProcessScore | 53.2 |
| RoleProcessScore | 47.4 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.050 |
| Opportunities | 8 (weight=6.6) |
| Model Confidence | 0.77 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [vote] D2 — score=0.780
2. [guard_protect] D1 — score=0.400
3. [guard_protect] D2 — score=0.400

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.312
2. [speech] D2 — score=0.312
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注vote类型决策的改善

---

## Werewolf — P2

| Metric | Value |
|--------|-------|
| FinalScore | **40.8** |
| ProcessScore | 47.9 |
| RoleProcessScore | 38.0 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.150 |
| Opportunities | 8 (weight=6.4) |
| Model Confidence | 0.76 |
| Won | ✗ |

### Top 3 Good Opportunities
1. [werewolf_kill] D1 — score=0.400
2. [speech] D1 — score=0.312
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [werewolf_kill] D2 — score=0.200
2. [werewolf_kill] D3 — score=0.200
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 决策质量偏低，建议参考策略库中同角色高质量案例
- 存在较多低质量决策，减少无依据的随机行为
- 重点关注werewolf_kill类型决策的改善

---

## Werewolf — P7

| Metric | Value |
|--------|-------|
| FinalScore | **42.2** |
| ProcessScore | 49.7 |
| RoleProcessScore | 40.4 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.100 |
| Opportunities | 8 (weight=6.2) |
| Model Confidence | 0.76 |
| Won | ✗ |

### Top 3 Good Opportunities
1. [werewolf_kill] D1 — score=0.400
2. [vote] D1 — score=0.312
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [speech] D2 — score=0.312
2. [werewolf_kill] D2 — score=0.200
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注werewolf_kill类型决策的改善

---

## Witch — P5

| Metric | Value |
|--------|-------|
| FinalScore | **46.3** |
| ProcessScore | 54.4 |
| RoleProcessScore | 48.6 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 5 (weight=3.6) |
| Model Confidence | 0.65 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [witch_save] D1 — score=0.500
2. [speech] D1 — score=0.312
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.312
2. [vote] D1 — score=0.312
3. [speech] D1 — score=0.312

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Seer — P6

| Metric | Value |
|--------|-------|
| FinalScore | **43.3** |
| ProcessScore | 50.9 |
| RoleProcessScore | 41.7 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.050 |
| Opportunities | 5 (weight=4.2) |
| Model Confidence | 0.68 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [seer_check] D1 — score=0.400
2. [seer_check] D2 — score=0.400
3. [vote] D1 — score=0.312

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.312
2. [speech] D1 — score=0.312
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注vote类型决策的改善

---

## Hunter — P3

| Metric | Value |
|--------|-------|
| FinalScore | **48.8** |
| ProcessScore | 57.5 |
| RoleProcessScore | 58.0 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.050 |
| Opportunities | 7 (weight=5.2) |
| Model Confidence | 0.72 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [hunter_shot] D3 — score=1.000
2. [vote] D2 — score=0.780
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [speech] D2 — score=0.312
2. [vote] D3 — score=0.312
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注vote类型决策的改善

---

## Villager — P1

| Metric | Value |
|--------|-------|
| FinalScore | **46.6** |
| ProcessScore | 54.8 |
| RoleProcessScore | 51.4 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.050 |
| Opportunities | 5 (weight=3.6) |
| Model Confidence | 0.64 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [vote] D2 — score=0.780
2. [vote] D1 — score=0.312
3. [speech] D1 — score=0.312

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.312
2. [speech] D2 — score=0.312
3. [vote] D1 — score=0.156

### Role-Specific Advice
- 重点关注vote类型决策的改善

---

## Guard — P6

| Metric | Value |
|--------|-------|
| FinalScore | **49.2** |
| ProcessScore | 57.9 |
| RoleProcessScore | 57.2 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 5 (weight=3.0) |
| Model Confidence | 0.60 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [guard_protect] D1 — score=0.640
2. [vote] D1 — score=0.500
3. [guard_protect] D2 — score=0.320

### Top 3 Bad Opportunities
1. [guard_protect] D2 — score=0.320
2. [vote] D1 — score=0.200
3. [speech] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Werewolf — P3

| Metric | Value |
|--------|-------|
| FinalScore | **45.7** |
| ProcessScore | 53.7 |
| RoleProcessScore | 46.8 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 5 (weight=2.7) |
| Model Confidence | 0.57 |
| Won | ✗ |

### Top 3 Good Opportunities
1. [werewolf_kill] D1 — score=0.400
2. [speech] D1 — score=0.200
3. [speech] D1 — score=0.200

### Top 3 Bad Opportunities
1. [speech] D1 — score=0.200
2. [vote] D1 — score=0.200
3. [speech] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Werewolf — P4

| Metric | Value |
|--------|-------|
| FinalScore | **44.9** |
| ProcessScore | 52.8 |
| RoleProcessScore | 44.4 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 5 (weight=3.4) |
| Model Confidence | 0.63 |
| Won | ✗ |

### Top 3 Good Opportunities
1. [werewolf_kill] D1 — score=0.400
2. [werewolf_kill] D2 — score=0.400
3. [vote] D1 — score=0.200

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.200
2. [speech] D1 — score=0.200
3. [vote] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Witch — P1

| Metric | Value |
|--------|-------|
| FinalScore | **51.5** |
| ProcessScore | 60.6 |
| RoleProcessScore | 64.1 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 5 (weight=3.1) |
| Model Confidence | 0.61 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [witch_poison] D2 — score=0.950
2. [vote] D1 — score=0.500
3. [witch_save] D1 — score=0.450

### Top 3 Bad Opportunities
1. [witch_save] D1 — score=0.450
2. [speech] D1 — score=0.200
3. [speech] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Seer — P7

| Metric | Value |
|--------|-------|
| FinalScore | **49.9** |
| ProcessScore | 58.7 |
| RoleProcessScore | 59.2 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 5 (weight=3.2) |
| Model Confidence | 0.62 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [seer_check] D1 — score=0.720
2. [vote] D1 — score=0.400
3. [vote] D1 — score=0.400

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.400
2. [seer_check] D2 — score=0.360
3. [speech] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Hunter — P2

| Metric | Value |
|--------|-------|
| FinalScore | **49.3** |
| ProcessScore | 58.0 |
| RoleProcessScore | 57.6 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 3 (weight=1.3) |
| Model Confidence | 0.39 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [vote] D1 — score=0.500
2. [speech] D1 — score=0.200
3. [speech] D1 — score=0.200

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.500
2. [speech] D1 — score=0.200
3. [speech] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---

## Villager — P5

| Metric | Value |
|--------|-------|
| FinalScore | **48.7** |
| ProcessScore | 57.4 |
| RoleProcessScore | 55.9 |
| SpeechScore | 50.0 |
| CounterfactualImpact | +0.000 |
| MistakePenalty | 0.000 |
| Opportunities | 3 (weight=1.4) |
| Model Confidence | 0.41 |
| Won | ✓ |

### Top 3 Good Opportunities
1. [vote] D1 — score=0.500
2. [vote] D1 — score=0.200
3. [speech] D1 — score=0.200

### Top 3 Bad Opportunities
1. [vote] D1 — score=0.500
2. [vote] D1 — score=0.200
3. [speech] D1 — score=0.200

### Role-Specific Advice
- 整体表现稳定，继续保持

---
