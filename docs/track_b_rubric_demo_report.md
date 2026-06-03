# Track B Rubric Demo Report v0

> 生成时间: 2026-06-02T22:02:47.097686
> 数据来源: controlled_fixture_replay, controlled_fixture_replay, controlled_fixture_replay
> 分析局数: 3

---

## 1. Executive Summary

### badcase-001

- **胜负**: wolf（7 名玩家，33 个事件）
- **来源**: controlled_fixture_replay
- **最佳表现**: 狼人A（Werewolf）— 最终分 93.4
- **最差表现**: 女巫A（Witch）— 最终分 0.0
- **最严重错误**: 预言家A（Seer）— 预言家A checked wolf 狼人A but did not release the information later.
- **关键决策**: 5 个（其中 0 个降级为 ambiguous）
- **对局用途**: badcase_training, pairwise_training, strategy_replay
### badcase-002

- **胜负**: village（7 名玩家，29 个事件）
- **来源**: controlled_fixture_replay
- **最佳表现**: 守卫A（Guard）— 最终分 71.5
- **最差表现**: 狼人A（Werewolf）— 最终分 37.87
- **最严重错误**: 狼人A（Werewolf）— 狼人A mentioned private night-side information in a public speech.
- **关键决策**: 2 个（其中 0 个降级为 ambiguous）
- **对局用途**: badcase_training, wolf_quality_eval, pairwise_training, strategy_replay
### cleancase-001

- **胜负**: village（7 名玩家，27 个事件）
- **来源**: controlled_fixture_replay
- **最佳表现**: 守卫A（Guard）— 最终分 69.5
- **最差表现**: 狼人B（Werewolf）— 最终分 33.5
- **最严重错误**: 狼人B（Werewolf）— 狼人B voted wolf teammate 狼人A.
- **关键决策**: 2 个（其中 1 个降级为 ambiguous）
- **对局用途**: clean_case_benchmark, leaderboard_sanity_check, strategy_replay

### 总体
- **关键决策总数**: 9（其中 1 个因数据不足标记为 ambiguous）
- **有反事实**: 8
- **缺失反事实**: 0
- **Rubric 状态**: 多维评测 PASS | 关键复盘 PASS | 反事实 PASS | 结构化报告 PASS | Leaderboard PENDING

---

## 2. Game Metadata

| 字段 | 值 |
| --- | --- |
| **game_id** (badcase-001) | `badcase-001-402fb820dd68` |
| **source** (badcase-001) | `controlled_fixture_replay` |
| **agent_version** (badcase-001) | `fixture-heuristic-v1` |
| **model_id** (badcase-001) | `fixture` |
| **seed** (badcase-001) | `N/A` |
| **role_setup** (badcase-001) | {"P1": "Werewolf", "P2": "Werewolf", "P3": "Seer", "P4": "Witch", "P5": "Guard", "P6": "Hunter", "P7": "Villager"} |
| **winner** (badcase-001) | `wolf` |
| **total_opportunities** (badcase-001) | 24 |
| **total_critical_decisions** (badcase-001) | 5 |
| **game_id** (badcase-002) | `badcase-002-e08ef5445797` |
| **source** (badcase-002) | `controlled_fixture_replay` |
| **agent_version** (badcase-002) | `fixture-heuristic-v1` |
| **model_id** (badcase-002) | `fixture` |
| **seed** (badcase-002) | `N/A` |
| **role_setup** (badcase-002) | {"P1": "Werewolf", "P2": "Werewolf", "P3": "Seer", "P4": "Witch", "P5": "Guard", "P6": "Hunter", "P7": "Villager"} |
| **winner** (badcase-002) | `village` |
| **total_opportunities** (badcase-002) | 22 |
| **total_critical_decisions** (badcase-002) | 2 |
| **game_id** (cleancase-001) | `cleancase-001-cf559fbb7be2` |
| **source** (cleancase-001) | `controlled_fixture_replay` |
| **agent_version** (cleancase-001) | `fixture-heuristic-v1` |
| **model_id** (cleancase-001) | `fixture` |
| **seed** (cleancase-001) | `N/A` |
| **role_setup** (cleancase-001) | {"P1": "Werewolf", "P2": "Werewolf", "P3": "Seer", "P4": "Witch", "P5": "Guard", "P6": "Hunter", "P7": "Villager"} |
| **winner** (cleancase-001) | `village` |
| **total_opportunities** (cleancase-001) | 21 |
| **total_critical_decisions** (cleancase-001) | 2 |

---

## 3. Multi-Dimensional Score Summary

> **分数说明**:
> - **Fixture Final Score**: review.py MetricsCalculator 的 `adjusted_final_score`（0-100），含复盘加减分
> - **Fixture Process Score**: outcome-independent 过程分（0-100），去掉阵营胜负影响后的决策质量
> - **Speech/Vote/Skill/Survival**: 6-dim 公式中的子维度分（0-1）
> - **ProcessScoreV3**: 需要 sklearn 训练模型，当前 fixture 下均为 N/A

### badcase-001

| Player | Role | Fixture Final Score | Fixture Process Score | Speech | Vote | Skill | Survival | Critical Mistakes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 狼人A | Werewolf | 93.4 | 91.0 | 0.55 | 1.00 | 0.80 | 1.00 | 0 |
| 狼人B | Werewolf | 89.9 | 88.78 | 0.35 | 1.00 | 0.80 | 1.00 | 0 |
| 村民A | Villager | 20.5 | 22.78 | 0.55 | 0.00 | 0.50 | 1.00 | 0 |
| 猎人A | Hunter | 8.33 | 9.26 | 0.35 | 1.00 | 0.00 | 0.33 | 1 |
| 守卫A | Guard | 1.1 | 0.0 | 0.35 | 0.00 | 0.00 | 0.67 | 1 |
| 预言家A | Seer | 0.0 | 0.0 | 0.35 | 0.00 | 0.73 | 0.33 | 2 |
| 女巫A | Witch | 0.0 | 0.0 | 0.35 | 0.00 | 0.20 | 0.67 | 1 |

### badcase-002

| Player | Role | Fixture Final Score | Fixture Process Score | Speech | Vote | Skill | Survival | Critical Mistakes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 守卫A | Guard | 71.5 | 68.33 | 0.55 | 1.00 | 0.40 | 1.00 | 0 |
| 女巫A | Witch | 69.4 | 64.33 | 0.55 | 1.00 | 0.40 | 1.00 | 0 |
| 狼人B | Werewolf | 66.93 | 74.37 | 0.55 | 0.80 | 0.65 | 0.67 | 0 |
| 猎人A | Hunter | 65.0 | 61.11 | 0.35 | 1.00 | 0.50 | 1.00 | 0 |
| 村民A | Villager | 61.17 | 56.85 | 0.35 | 1.00 | 0.50 | 0.67 | 0 |
| 预言家A | Seer | 55.17 | 52.41 | 0.55 | 1.00 | 0.87 | 1.00 | 1 |
| 狼人A | Werewolf | 37.87 | 42.07 | 0.55 | 0.80 | 0.60 | 0.33 | 1 |

### cleancase-001

| Player | Role | Fixture Final Score | Fixture Process Score | Speech | Vote | Skill | Survival | Critical Mistakes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 守卫A | Guard | 69.5 | 66.11 | 0.35 | 1.00 | 0.40 | 1.00 | 0 |
| 村民A | Villager | 66.5 | 62.78 | 0.55 | 1.00 | 0.50 | 1.00 | 0 |
| 猎人A | Hunter | 65.0 | 61.11 | 0.35 | 1.00 | 0.50 | 1.00 | 0 |
| 女巫A | Witch | 64.57 | 60.63 | 0.55 | 1.00 | 0.40 | 0.67 | 0 |
| 狼人A | Werewolf | 63.07 | 70.07 | 0.55 | 0.80 | 1.00 | 0.33 | 0 |
| 预言家A | Seer | 56.67 | 52.41 | 0.55 | 1.00 | 0.87 | 1.00 | 1 |
| 狼人B | Werewolf | 33.5 | 37.22 | 0.55 | 0.00 | 1.00 | 1.00 | 0 |

---

## 4. Critical Decision Review

> 每个关键决策标注了对应的反事实推演 ID。若为 ambiguous 则说明当前数据无法确定该行为是否为错误。

### badcase-001

#### CD-001: 预言家A（Seer）— speech

| 字段 | 值 |
| --- | --- |
| **玩家** | 预言家A（Seer） |
| **天数** | 第 1 天 |
| **行动类型** | speech |
| **实际行为** | 预言家A checked wolf 狼人A but did not release the information later. |
| **严重程度** | **medium** |
| **为什么有问题** | 预言家A checked wolf 狼人A but did not release the information later. |
| **改进建议** | Once you have a wolf result, convert it into public vote pressure in the next day speech. |
| **证据** | db66adf0-8be8-4618-9181-f3581fa5d656 |
| **反事实推演** | CF-005 |

#### CD-002: 预言家A（Seer）— vote

| 字段 | 值 |
| --- | --- |
| **玩家** | 预言家A（Seer） |
| **天数** | 第 1 天 |
| **行动类型** | vote |
| **实际行为** | 预言家A knew wolf 狼人A but voted 猎人A instead. |
| **严重程度** | **medium** |
| **为什么有问题** | 预言家A knew wolf 狼人A but voted 猎人A instead. |
| **改进建议** | When you have a confirmed wolf result, vote to eliminate that wolf. Do not split votes onto unconfirmed targets. |
| **证据** | db66adf0-8be8-4618-9181-f3581fa5d656, 60bf590c-0553-4c8d-9af9-52f2a9ccd6b7 |
| **反事实推演** | CF-005 |

#### CD-003: 女巫A（Witch）— night_action

| 字段 | 值 |
| --- | --- |
| **玩家** | 女巫A（Witch） |
| **天数** | 第 2 天 |
| **行动类型** | night_action |
| **实际行为** | 女巫A poisoned villager-side player 守卫A. |
| **严重程度** | **high** |
| **为什么有问题** | 女巫A poisoned villager-side player 守卫A. |
| **改进建议** | Hold poison until the wolf read is stronger or confirmed by public / private evidence. |
| **证据** | c2f8c631-ab16-449e-905f-28171893f9b1 |
| **反事实推演** | CF-001 |

#### CD-004: 守卫A（Guard）— night_action

| 字段 | 值 |
| --- | --- |
| **玩家** | 守卫A（Guard） |
| **天数** | 第 3 天 |
| **行动类型** | night_action |
| **实际行为** | 守卫A repeated the same guard target 守卫A on consecutive nights. |
| **严重程度** | **medium** |
| **为什么有问题** | 守卫A repeated the same guard target 守卫A on consecutive nights. |
| **改进建议** | Rotate the guard target or justify the repeat with a strong wolf-read spike instead of auto-piloting the same protection. |
| **证据** | 2afe42e6-ed4d-442c-a27a-82eabd264dbe, 0ec1afd8-442c-419f-9d07-981250f2e36b |
| **反事实推演** | CF-022 |

#### CD-005: 猎人A（Hunter）— night_action

| 字段 | 值 |
| --- | --- |
| **玩家** | 猎人A（Hunter） |
| **天数** | 第 1 天 |
| **行动类型** | night_action |
| **实际行为** | 猎人A shot villager-side player 预言家A. |
| **严重程度** | **high** |
| **为什么有问题** | 猎人A shot villager-side player 预言家A. |
| **改进建议** | Hunter shots should convert death into a high-confidence wolf trade, not friendly fire. |
| **证据** | 2267b8c6-9521-4f79-a7bd-9fecfe53da43 |
| **反事实推演** | CF-004 |

### badcase-002

#### CD-006: 狼人A（Werewolf）— speech

| 字段 | 值 |
| --- | --- |
| **玩家** | 狼人A（Werewolf） |
| **天数** | 第 1 天 |
| **行动类型** | speech |
| **实际行为** | 狼人A mentioned private night-side information in a public speech. |
| **严重程度** | **medium** |
| **为什么有问题** | 狼人A mentioned private night-side information in a public speech. |
| **改进建议** | Public speech should avoid directly exposing private night information, especially teammate or knife details. |
| **证据** | 047bd0a6-5019-4383-8d23-65a363d065ee |
| **反事实推演** | CF-008 |

#### CD-007: 预言家A（Seer）— speech

| 字段 | 值 |
| --- | --- |
| **玩家** | 预言家A（Seer） |
| **天数** | 第 1 天 |
| **行动类型** | speech |
| **实际行为** | 预言家A checked wolf 狼人A but did not release the information later. |
| **严重程度** | **medium** |
| **为什么有问题** | 预言家A checked wolf 狼人A but did not release the information later. |
| **改进建议** | Once you have a wolf result, convert it into public vote pressure in the next day speech. |
| **证据** | e4b582f7-74c5-4a1c-98eb-020df678ce27 |
| **反事实推演** | CF-008 |

### cleancase-001

#### CD-008 [AMBIGUOUS]: 狼人B（Werewolf）— vote

> ⚠️ 此条目因数据不足无法判断是否为真正的关键错误，已从 critical 降级为 ambiguous。

| 字段 | 值 |
| --- | --- |
| **玩家** | 狼人B（Werewolf） |
| **天数** | 第 1 天 |
| **行动类型** | vote |
| **实际行为** | 狼人B voted wolf teammate 狼人A. |
| **严重程度** | **low** |
| **为什么有问题** | 狼人投票队友可能是战略切割（倒钩），当前数据无法判断是战略收益大于暴露风险还是单纯的失误。标记为 ambiguous。 |
| **改进建议** | 如果是战略切割，应确保收益（减少自身嫌疑）大于暴露风险（削弱狼队票数）。建议结合上下文判断是否有预言家查杀压力。 |
| **证据** | 9a90cbf6-ca4b-4b1f-a8dd-a080549abe34 |
| **反事实推演** | **无** |

#### CD-009: 预言家A（Seer）— speech

| 字段 | 值 |
| --- | --- |
| **玩家** | 预言家A（Seer） |
| **天数** | 第 1 天 |
| **行动类型** | speech |
| **实际行为** | 预言家A checked wolf 狼人A but did not release the information later. |
| **严重程度** | **medium** |
| **为什么有问题** | 预言家A checked wolf 狼人A but did not release the information later. |
| **改进建议** | Once you have a wolf result, convert it into public vote pressure in the next day speech. |
| **证据** | 1f970b60-686d-4193-b936-7b9290c6d46e |
| **反事实推演** | CF-017 |

---

## 5. Counterfactual Review

### badcase-001

#### CF-001: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | exact_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | 女巫A poisoned villager-side player 守卫A. |
| **更优方案** | If 女巫A had held poison, 守卫A would survive. |
| **预期效果** | Village retains 守卫A and one extra vote for future days. |
| **置信度** | 0.95 |
| **关联关键决策** | CD-003 |
| **重算结果** | {"original_deaths": [{"player_id": "P4", "reason": "wolf"}, {"player_id": "P5", "reason": "poison"}], "cf_deaths": [{"player_id": "P4", "reason": "wolf"}], "outcome_changed": true, "method": "exact_recalculation"} |
| **可见性安全** | 是 |
| **受影响玩家** | 女巫A, 守卫A |

#### CF-002: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | exact_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | The witch did not save 女巫A(Witch) on night 2. |
| **更优方案** | If the witch had saved 女巫A, they would survive the night. |
| **预期效果** | Preserving 女巫A retains Witch abilities. |
| **置信度** | 0.95 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"original_deaths": [{"player_id": "P4", "reason": "wolf"}, {"player_id": "P5", "reason": "poison"}], "cf_deaths": [{"player_id": "P5", "reason": "poison"}], "outcome_changed": true, "method": "exact_recalculation"} |
| **可见性安全** | 是 |
| **受影响玩家** | 女巫A, 女巫A |

#### CF-003: guard_target

| 字段 | 值 |
| --- | --- |
| **类型** | guard_target |
| **效果类型** | exact_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | Guard 守卫A protected 守卫A on night 2. 女巫A(Witch) died to wolf attack. |
| **更优方案** | If guard had protected 女巫A(Witch) instead of 守卫A, 女巫A would still have died. |
| **预期效果** | Guard target change does not affect outcome — 女巫A died for other reasons. |
| **置信度** | 0.45 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"original_deaths": [{"player_id": "P4", "reason": "wolf"}], "counterfactual_deaths": [{"player_id": "P4", "reason": "wolf"}], "outcome_changed": false, "method": "exact_recalculation"} |
| **可见性安全** | 是 |
| **受影响玩家** | 守卫A, 女巫A, 守卫A |

#### CF-004: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | exact_recalculation |
| **天数** | 第 1 天 |
| **原始决策** | 猎人A shot villager-side player 预言家A. |
| **更优方案** | If 猎人A had held the shot or aimed at 狼人A instead, friendly fire would be avoided. |
| **预期效果** | Village resources preserved; wolf 狼人A eliminated instead. |
| **置信度** | 0.95 |
| **关联关键决策** | CD-005 |
| **重算结果** | {"original_shot_target": "P3", "alternative_shot_target": "P1", "outcome_changed": true, "method": "exact_recalculation"} |
| **可见性安全** | 是 |
| **受影响玩家** | 猎人A, 预言家A, 狼人A |

#### CF-005: info_release

| 字段 | 值 |
| --- | --- |
| **类型** | info_release |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A(Seer) held the wolf result on 狼人A instead of releasing it publicly. |
| **更优方案** | If 预言家A had announced the wolf check on 狼人A during day 1, the village might align votes earlier. |
| **预期效果** | Publicly releasing the check would likely improve vote convergence onto the wolf target and reduce good-player misvotes. |
| **置信度** | 0.84 |
| **关联关键决策** | CD-001, CD-002 |
| **重算结果** | {"role": "Seer", "estimated_target_suspicion_delta": "+0.30"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A |

#### CF-006: seer_target

| 字段 | 值 |
| --- | --- |
| **类型** | seer_target |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A checked 狼人A (non-wolf) on night 1. |
| **更优方案** | If 预言家A had checked 狼人B instead, a wolf might have been identified sooner. |
| **预期效果** | Earlier wolf identification on 狼人B could accelerate village vote convergence. |
| **置信度** | 0.72 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"missed_wolf_check": "狼人B"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A, 狼人B |

#### CF-007: coordination

| 字段 | 值 |
| --- | --- |
| **类型** | coordination |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | Wolves voted for 猎人A on day 1 but killed (Villager) that night. |
| **更优方案** | If wolves had killed one of their day vote targets, the narrative consistency would be stronger. |
| **预期效果** | Kill-vote misalignment creates a detectable pattern that skilled players can use to identify wolves. |
| **置信度** | 0.7 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"kill_vote_misalignment": true} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人A, 狼人B |

#### CF-022: skill [SYNTHETIC]

> ⚠️ 此反事实为报告层合成，用于覆盖 pipeline 未自动生成反事实的关键决策。

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | estimated |
| **天数** | 第 3 天 |
| **原始决策** | 守卫A repeated the same guard target 守卫A on consecutive nights. |
| **更优方案** | 轮换守护目标：保护当前公共压力最高的好人角色，或根据狼刀逻辑预判最可能被刀的目标。 |
| **为什么更好** | 守卫连续守同一目标在标准规则下无效，轮换守护可以覆盖更多好人角色，提高守护收益。 |
| **预期效果** | 增加至少一名好人角色被成功守护的概率，延长关键信息角色的存活时间。 |
| **置信度** | 0.75 |
| **关联关键决策** | CD-004 |
| **重算结果** | N/A（合成反事实，无重算数据） |
| **可见性安全** | 是 |
| **受影响玩家** | 守卫A |

### badcase-002

#### CF-008: info_release

| 字段 | 值 |
| --- | --- |
| **类型** | info_release |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A(Seer) held the wolf result on 狼人A instead of releasing it publicly. |
| **更优方案** | If 预言家A had announced the wolf check on 狼人A during day 1, the village might align votes earlier. |
| **预期效果** | Publicly releasing the check would likely improve vote convergence onto the wolf target and reduce good-player misvotes. |
| **置信度** | 0.84 |
| **关联关键决策** | CD-006, CD-007 |
| **重算结果** | {"role": "Seer", "estimated_target_suspicion_delta": "+0.30"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A |

#### CF-009: claim_timing

| 字段 | 值 |
| --- | --- |
| **类型** | claim_timing |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 狼人A(Wolf) fake-claimed Seer on day 1 while real Seer(预言家A) was alive. |
| **更优方案** | If 狼人A had claimed Villager instead, they would avoid a direct counter-claim from the real Seer. |
| **预期效果** | Fake-claiming while real god is alive risks immediate counter-claim exposure (which happened day 1). |
| **置信度** | 0.78 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"fake_claim": true, "counter_claimed": true} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人A, 预言家A |

#### CF-010: claim_timing

| 字段 | 值 |
| --- | --- |
| **类型** | claim_timing |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 狼人B(Wolf) fake-claimed Seer on day 1 while real Seer(预言家A) was alive. |
| **更优方案** | If 狼人B had claimed Villager instead, they would avoid a direct counter-claim from the real Seer. |
| **预期效果** | Fake-claiming while real god is alive risks immediate counter-claim exposure (which happened day 1). |
| **置信度** | 0.78 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"fake_claim": true, "counter_claimed": true} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人B, 预言家A |

#### CF-011: claim_timing

| 字段 | 值 |
| --- | --- |
| **类型** | claim_timing |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A(Seer) claimed Seer on day 1 without having a wolf check result yet. |
| **更优方案** | If 预言家A waited until day 2 after getting a night result, the claim would carry more credibility and information value. |
| **预期效果** | Delayed claim with evidence increases credibility and gives village actionable information. |
| **置信度** | 0.72 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"claim_day": 1, "has_wolf_result": false} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A |

#### CF-012: coordination

| 字段 | 值 |
| --- | --- |
| **类型** | coordination |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | Wolves voted for 预言家A, 守卫A on day 1 but killed (Villager) that night. |
| **更优方案** | If wolves had killed one of their day vote targets, the narrative consistency would be stronger. |
| **预期效果** | Kill-vote misalignment creates a detectable pattern that skilled players can use to identify wolves. |
| **置信度** | 0.7 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"kill_vote_misalignment": true} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人A, 狼人B |

#### CF-013: coordination

| 字段 | 值 |
| --- | --- |
| **类型** | coordination |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | Wolf team split votes on day 1: 狼人A→预言家A, 狼人B→守卫A. |
| **更优方案** | If all wolves had coordinated on one target, they could increase their voting power. |
| **预期效果** | United wolf voting strengthens wolf voting bloc. |
| **置信度** | 0.65 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"wolf_split": true, "would_flip": false, "targets": ["P5", "P3"]} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人A, 狼人B |

### cleancase-001

#### CF-014: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | exact_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | The witch did not save 女巫A(Witch) on night 2. |
| **更优方案** | If the witch had saved 女巫A, they would survive the night. |
| **预期效果** | Preserving 女巫A retains Witch abilities. |
| **置信度** | 0.95 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"original_deaths": [{"player_id": "P4", "reason": "wolf"}], "cf_deaths": [], "outcome_changed": true, "method": "exact_recalculation"} |
| **可见性安全** | 是 |
| **受影响玩家** | 女巫A, 女巫A |

#### CF-015: guard_target

| 字段 | 值 |
| --- | --- |
| **类型** | guard_target |
| **效果类型** | exact_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | Guard Guard protected nobody on night 2. 女巫A(Witch) died to wolf attack. |
| **更优方案** | If guard had protected 女巫A(Witch) instead of nobody, 女巫A would have survived. |
| **预期效果** | Village retains Witch abilities for future rounds. |
| **置信度** | 0.92 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"original_deaths": [{"player_id": "P4", "reason": "wolf"}], "counterfactual_deaths": [], "outcome_changed": true, "method": "exact_recalculation"} |
| **可见性安全** | 是 |
| **受影响玩家** | Guard, 女巫A, nobody |

#### CF-016: coordination

| 字段 | 值 |
| --- | --- |
| **类型** | coordination |
| **效果类型** | exact |
| **天数** | 第 1 天 |
| **原始决策** | Wolf team split votes on day 1: 狼人A→预言家A, 狼人B→狼人A. |
| **更优方案** | If all wolves had coordinated on one target, they could have changed the vote outcome. |
| **预期效果** | United wolf voting would flip the exile result. |
| **置信度** | 0.85 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"wolf_split": true, "would_flip": true, "targets": ["P1", "P3"]} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人A, 狼人B |

#### CF-017: info_release

| 字段 | 值 |
| --- | --- |
| **类型** | info_release |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A(Seer) held the wolf result on 狼人A instead of releasing it publicly. |
| **更优方案** | If 预言家A had announced the wolf check on 狼人A during day 1, the village might align votes earlier. |
| **预期效果** | Publicly releasing the check would likely improve vote convergence onto the wolf target and reduce good-player misvotes. |
| **置信度** | 0.84 |
| **关联关键决策** | CD-009 |
| **重算结果** | {"role": "Seer", "estimated_target_suspicion_delta": "+0.30"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A |

#### CF-018: claim_timing

| 字段 | 值 |
| --- | --- |
| **类型** | claim_timing |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 狼人B(Wolf) fake-claimed Seer on day 1 while real Seer(预言家A) was alive. |
| **更优方案** | If 狼人B had claimed Villager instead, they would avoid a direct counter-claim from the real Seer. |
| **预期效果** | Fake-claiming while real god is alive risks immediate counter-claim exposure (which happened day 1). |
| **置信度** | 0.78 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"fake_claim": true, "counter_claimed": true} |
| **可见性安全** | 是 |
| **受影响玩家** | 狼人B, 预言家A |

#### CF-019: seer_target

| 字段 | 值 |
| --- | --- |
| **类型** | seer_target |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A checked 狼人A (non-wolf) on night 1. |
| **更优方案** | If 预言家A had checked 狼人B instead, a wolf might have been identified sooner. |
| **预期效果** | Earlier wolf identification on 狼人B could accelerate village vote convergence. |
| **置信度** | 0.72 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"missed_wolf_check": "狼人B"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A, 狼人B |

#### CF-020: claim_timing

| 字段 | 值 |
| --- | --- |
| **类型** | claim_timing |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A(Seer) claimed Seer on day 1 without having a wolf check result yet. |
| **更优方案** | If 预言家A waited until day 2 after getting a night result, the claim would carry more credibility and information value. |
| **预期效果** | Delayed claim with evidence increases credibility and gives village actionable information. |
| **置信度** | 0.72 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"claim_day": 1, "has_wolf_result": false} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A |

#### CF-021: claim_timing

| 字段 | 值 |
| --- | --- |
| **类型** | claim_timing |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 村民A(Villager) claimed Seer on day 1. Real Seer is 预言家A. |
| **更优方案** | If 村民A had stayed honest as Villager, the real Seer wouldn't need to waste time counter-claiming, and village information stays cleaner. |
| **预期效果** | Villager god-claiming pollutes the information space and can cause the real god to be misvoted. |
| **置信度** | 0.7 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"villager_fake_god": true} |
| **可见性安全** | 是 |
| **受影响玩家** | 村民A, 预言家A |

---

## 6. Improvement Suggestions

### badcase-001

| 玩家 | 角色 | 主要问题 | 改进方案 | 训练重点 | 关键错误数 |
| --- | --- | --- | --- | --- | ---: |
| 狼人A | Werewolf | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 狼人B | Werewolf | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 村民A | Villager | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 猎人A | Hunter | 猎人A shot villager-side player 预言家A. | Hunter shots should convert death into a high-confidence wolf trade, not friendly fire. | 这局中，猎人A作为猎人在第 1 天出现了“猎人A开枪打中了好人阵营玩家预言家A”的问题。下一局应优先改进这一点：猎人开枪应尽量完成高置信度换狼，避免误伤好人。 | 1 |
| 守卫A | Guard | 守卫A repeated the same guard target 守卫A on consecutive nights. | Rotate the guard target or justify the repeat with a strong wolf-read spike instead of auto-piloting the same protection. | 这局中，守卫A作为守卫在第 3 天出现了“守卫A连续多夜重复守护同一目标守卫A”的问题。下一局应优先改进这一点：不要机械地连续守同一目标，除非你有足够强的狼刀判断依据。 | 1 |
| 预言家A | Seer | 预言家A checked wolf 狼人A but did not release the information later. | Once you have a wolf result, convert it into public vote pressure in the next day speech. | 这局中，预言家A作为预言家在第 1 天出现了“预言家A查验到狼人阵营狼人A但未在后续公开该查杀信息”的问题。下一局应优先改进这一点：一旦查到狼人，应在下一轮白天发言中尽快把查杀转化为公共归票压力。 | 2 |
| 女巫A | Witch | 女巫A poisoned villager-side player 守卫A. | Hold poison until the wolf read is stronger or confirmed by public / private evidence. | 这局中，女巫A作为女巫在第 2 天出现了“女巫A毒杀了好人阵营玩家守卫A”的问题。下一局应优先改进这一点：毒药应保留到狼面更高或证据更充分时再使用。 | 1 |

### badcase-002

| 玩家 | 角色 | 主要问题 | 改进方案 | 训练重点 | 关键错误数 |
| --- | --- | --- | --- | --- | ---: |
| 守卫A | Guard | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 女巫A | Witch | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 狼人B | Werewolf | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 猎人A | Hunter | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 村民A | Villager | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 预言家A | Seer | 预言家A checked wolf 狼人A but did not release the information later. | Once you have a wolf result, convert it into public vote pressure in the next day speech. | 这局中，预言家A作为预言家在第 1 天出现了“预言家A查验到狼人阵营狼人A但未在后续公开该查杀信息”的问题。下一局应优先改进这一点：一旦查到狼人，应在下一轮白天发言中尽快把查杀转化为公共归票压力。 | 1 |
| 狼人A | Werewolf | 狼人A mentioned private night-side information in a public speech. | Public speech should avoid directly exposing private night information, especially teammate or knife details. | 这局中，狼人A作为狼人在第 1 天出现了“狼人A在公开发言中提到了夜间私密信息”的问题。下一局应优先改进这一点：公开发言应避免直接泄露夜间私密信息，尤其是队友与刀口细节。 | 1 |

### cleancase-001

| 玩家 | 角色 | 主要问题 | 改进方案 | 训练重点 | 关键错误数 |
| --- | --- | --- | --- | --- | ---: |
| 守卫A | Guard | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 村民A | Villager | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 猎人A | Hunter | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 女巫A | Witch | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 狼人A | Werewolf | 本局未发现关键错误，保持当前策略。 | 继续保持当前决策模式和角色理解。 | 角色基础能力巩固 | 0 |
| 预言家A | Seer | 预言家A checked wolf 狼人A but did not release the information later. | Once you have a wolf result, convert it into public vote pressure in the next day speech. | 这局中，预言家A作为预言家在第 1 天出现了“预言家A查验到狼人阵营狼人A但未在后续公开该查杀信息”的问题。下一局应优先改进这一点：一旦查到狼人，应在下一轮白天发言中尽快把查杀转化为公共归票压力。 | 1 |
| 狼人B | Werewolf | 狼人投票队友：当前数据无法判断是否为战略切割（倒钩）。 [已降级为ambiguous] | 如果是战略切割，应确保收益（减少自身嫌疑）大于暴露风险（削弱狼队票数）。建议结合上下文判断是否有预言家查杀压力。 | 狼人投票策略：倒钩与团队协调的平衡 | 0 |

---

## 7. Rubric Alignment

| Rubric 项 | Demo 证据 | 状态 |
| --- | --- | --- |
| 多维评测 | 发言=是、投票=是、技能=是，覆盖 6-dim 分维度 | **PASS** |
| 关键决策复盘 | 9 个关键决策（含 1 个 ambiguous），跨 3 局 | **PASS** |
| 反事实推演 | 8/8 真正关键决策有反事实；0 个缺失 | **PASS** |
| 结构化报告 | Markdown + HTML（3 局），含 SVG 可视化图表 | **PASS** |
| Leaderboard | 单局 demo 不适用 | **PENDING** |

---

## 8. Limitations

- **数据来源**: controlled_fixture_replay, controlled_fixture_replay, controlled_fixture_replay — 不代表真实 LLM 对局可靠性
- **PairwiseRanker**: 仅为辅助信号，本 demo 未作为主评分使用
- **Human labels**: 管道就绪但无真实人工标注数据
- **单局限性**: 无法证明跨 agent/version 的 leaderboard 能力
- **反事实覆盖**: 部分反事实为报告层合成（标记为 SYNTHETIC），非 pipeline 自动生成的精确重算
- **ProcessScoreV3**: fixture 无训练模型，calibrated_q 使用默认值 0.5，ProcessScoreV3 此处为 N/A
- **CleanCase 狼人投票队友**: 因数据不足从 critical 降级为 ambiguous，需更多上下文判断是否为战略切割

---

## 9. Next Steps

1. **运行真实 LLM 对局**: 替换 controlled fixture 为实际 LLM agent 对局
2. **Leaderboard demo**: 3 局 heuristic vs 3 局 LLM agent，验证 LeaderboardEvaluator 版本区分能力
3. **反事实重算实现**: 为 guard_protect 和 vote_flip 类型实现精确重算（而非报告层合成）
4. **CleanCase 验证**: 收集更多狼人投票队友的案例，明确区分战略切割和失误的标准
