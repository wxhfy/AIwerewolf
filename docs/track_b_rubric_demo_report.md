# Track B Rubric Demo Report v0

> 生成时间: 2026-05-29T18:08:24.411299
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
| **game_id** (badcase-001) | `badcase-001-c15c30cd03af` |
| **source** (badcase-001) | `controlled_fixture_replay` |
| **agent_version** (badcase-001) | `fixture-heuristic-v1` |
| **model_id** (badcase-001) | `fixture` |
| **seed** (badcase-001) | `N/A` |
| **role_setup** (badcase-001) | {"P1": "Werewolf", "P2": "Werewolf", "P3": "Seer", "P4": "Witch", "P5": "Guard", "P6": "Hunter", "P7": "Villager"} |
| **winner** (badcase-001) | `wolf` |
| **total_opportunities** (badcase-001) | 24 |
| **total_critical_decisions** (badcase-001) | 5 |
| **game_id** (badcase-002) | `badcase-002-5b47bf731bf6` |
| **source** (badcase-002) | `controlled_fixture_replay` |
| **agent_version** (badcase-002) | `fixture-heuristic-v1` |
| **model_id** (badcase-002) | `fixture` |
| **seed** (badcase-002) | `N/A` |
| **role_setup** (badcase-002) | {"P1": "Werewolf", "P2": "Werewolf", "P3": "Seer", "P4": "Witch", "P5": "Guard", "P6": "Hunter", "P7": "Villager"} |
| **winner** (badcase-002) | `village` |
| **total_opportunities** (badcase-002) | 22 |
| **total_critical_decisions** (badcase-002) | 2 |
| **game_id** (cleancase-001) | `cleancase-001-a62cbcafaa0d` |
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
| **证据** | 5aba2aeb-4354-4fd3-9223-4b731a212ccf |
| **反事实推演** | CF-004 |

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
| **证据** | 5aba2aeb-4354-4fd3-9223-4b731a212ccf, 125f7538-f5f0-4e2a-a94d-d17957423853 |
| **反事实推演** | CF-004 |

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
| **证据** | f473c9e9-467e-4bfe-8b28-82065c12b55e |
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
| **证据** | fae8d82b-05b6-43ec-af00-b9b140f069fe, 5bd0419b-4f8a-41e4-be35-8b36f10b4971 |
| **反事实推演** | CF-008 |

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
| **证据** | 7c3d9c05-bd98-4394-8672-24b636dfbc2e |
| **反事实推演** | CF-003 |

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
| **证据** | 9a0f8cb5-371e-4b39-b3d7-13103fa172dd |
| **反事实推演** | CF-005 |

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
| **证据** | ff1e4f4c-b482-4b96-beb4-6787e91eea99 |
| **反事实推演** | CF-005 |

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
| **证据** | 32e2215f-6ba3-4ae7-b2d0-2ee77202cea2 |
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
| **证据** | a660ab90-646d-46fc-8a08-8958c97f3896 |
| **反事实推演** | CF-007 |

---

## 5. Counterfactual Review

### badcase-001

#### CF-001: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | local_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | 女巫A poisoned villager-side player 守卫A. |
| **更优方案** | If 女巫A had held poison or redirected onto a higher-confidence wolf target, 守卫A might survive the night. |
| **预期效果** | Village-side numbers and public information from 守卫A would likely be preserved. |
| **置信度** | 0.88 |
| **关联关键决策** | CD-003 |
| **重算结果** | {"avoided_death": "P5", "village_survivors_delta": 1} |
| **可见性安全** | 是 |
| **受影响玩家** | 女巫A, 守卫A |

#### CF-002: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | local_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | The witch did not save key role 女巫A on night 2. |
| **更优方案** | If the witch had saved 女巫A, the village might retain a high-value Witch for the next day. |
| **预期效果** | Preserving 女巫A could keep more public or private information online. |
| **置信度** | 0.7 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"avoided_death": "P4", "preserved_role": "Witch"} |
| **可见性安全** | 是 |
| **受影响玩家** | 女巫A, 女巫A |

#### CF-003: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | local_recalculation |
| **天数** | 第 1 天 |
| **原始决策** | 猎人A shot villager-side player 预言家A. |
| **更优方案** | If 猎人A had held the shot or targeted a higher-confidence wolf read, the trade could avoid friendly fire. |
| **预期效果** | Village-side resources would not be lost to the hunter shot on 预言家A. |
| **置信度** | 0.9 |
| **关联关键决策** | CD-005 |
| **重算结果** | {"avoided_friendly_fire": "P3"} |
| **可见性安全** | 是 |
| **受影响玩家** | 猎人A, 预言家A |

#### CF-004: info_release

| 字段 | 值 |
| --- | --- |
| **类型** | info_release |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A held the wolf result on 狼人A instead of releasing it publicly. |
| **更优方案** | If 预言家A had announced the wolf check on 狼人A during day 1, the village might align votes earlier. |
| **预期效果** | Publicly releasing the check would likely improve vote convergence onto 狼人A and reduce good-player misvotes; this is an estimated local effect. |
| **置信度** | 0.84 |
| **关联关键决策** | CD-001, CD-002 |
| **重算结果** | {"estimated_target_suspicion_delta": "+0.30"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A |

#### CF-008: skill [SYNTHETIC]

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

#### CF-005: info_release

| 字段 | 值 |
| --- | --- |
| **类型** | info_release |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A held the wolf result on 狼人A instead of releasing it publicly. |
| **更优方案** | If 预言家A had announced the wolf check on 狼人A during day 1, the village might align votes earlier. |
| **预期效果** | Publicly releasing the check would likely improve vote convergence onto 狼人A and reduce good-player misvotes; this is an estimated local effect. |
| **置信度** | 0.84 |
| **关联关键决策** | CD-006, CD-007 |
| **重算结果** | {"estimated_target_suspicion_delta": "+0.30"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A |

### cleancase-001

#### CF-006: skill

| 字段 | 值 |
| --- | --- |
| **类型** | skill |
| **效果类型** | local_recalculation |
| **天数** | 第 2 天 |
| **原始决策** | The witch did not save key role 女巫A on night 2. |
| **更优方案** | If the witch had saved 女巫A, the village might retain a high-value Witch for the next day. |
| **预期效果** | Preserving 女巫A could keep more public or private information online. |
| **置信度** | 0.7 |
| **关联关键决策** | UNLINKED |
| **重算结果** | {"avoided_death": "P4", "preserved_role": "Witch"} |
| **可见性安全** | 是 |
| **受影响玩家** | 女巫A, 女巫A |

#### CF-007: info_release

| 字段 | 值 |
| --- | --- |
| **类型** | info_release |
| **效果类型** | estimated |
| **天数** | 第 1 天 |
| **原始决策** | 预言家A held the wolf result on 狼人A instead of releasing it publicly. |
| **更优方案** | If 预言家A had announced the wolf check on 狼人A during day 1, the village might align votes earlier. |
| **预期效果** | Publicly releasing the check would likely improve vote convergence onto 狼人A and reduce good-player misvotes; this is an estimated local effect. |
| **置信度** | 0.84 |
| **关联关键决策** | CD-009 |
| **重算结果** | {"estimated_target_suspicion_delta": "+0.30"} |
| **可见性安全** | 是 |
| **受影响玩家** | 预言家A, 狼人A |

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
