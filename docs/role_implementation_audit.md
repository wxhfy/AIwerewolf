# Part 4: 角色实现审计

> 审计日期: 2026-05-28 | 状态: 只读 | 证据: `backend/engine/roles/`, `backend/agents/prompts.py`, `backend/agents/profiles.py`, `backend/agents/playbooks.py`, `backend/engine/game.py`

---

## 4.1 Werewolf (狼人)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/wolves.py` — 阵营 Wolf, 夜晚行动 ATTACK |
| **夜晚动作** | ATTACK — 狼队讨论后投票决定刀人目标 (`game.py:_wolf_phase()`) |
| **白天动作** | TALK + VOTE |
| **私有信息** | 狼队友列表 (known_wolves), 狼队讨论内容 |
| **技能** | 夜里刀人 (多数决) |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[WEREWOLF]` — 伪装+协作策略 |
| **动作策略** | `ACTION_STRATEGIES["talk"]["Werewolf"]` — 如何伪装村民, 制造混乱 |
| **Playbook** | `ACTION_PLAYBOOKS[WEREWOLF]` — public_debate, vote_logic, night_logic |
| **特殊规则** | 白狼王可自爆 (BOOM), 带人一起死 |

### 关键问题回答

| 问题 | 答案 | 证据 |
|------|------|------|
| 狼人知道狼队友吗? | ✅ YES | `visibility.py:_visible_player()` — 狼队互相看到完整 private_dict() |
| 有协作策略吗? | ✅ YES | `_wolf_phase()` — 狼队讨论后投票, prompt 中有 "与其他狼人配合" |
| 有投票策略吗? | ⚠️ PARTIAL | Heuristic：有 `_wolf_seer_counter_claim()`, LLM：依赖 prompt |
| 有伪装策略吗? | ✅ YES | `prompts.py` — talk 策略含 "伪装成村民" 指导 |

---

## 4.2 Seer (预言家)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/gods.py` — 阵营 Village, 夜晚行动 DIVINE |
| **夜晚动作** | DIVINE — 查验一名玩家身份 (`game.py:_seer_phase()`) |
| **白天动作** | TALK + VOTE |
| **私有信息** | 查验历史 (seer_result 仅对预言家可见) |
| **技能** | 每夜查验一名玩家 (是否是狼人) |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[SEER]` — 信息收集+发布策略 |
| **动作策略** | `ACTION_STRATEGIES["talk"]["Seer"]` — 如何选择性发布查验结果 |
| **Playbook** | `ACTION_PLAYBOOKS[SEER]` — reveal_logic: "查验到狼人就跳, 查验到好人先藏" |

### 关键问题回答

| 问题 | 答案 | 证据 |
|------|------|------|
| 记录查验结果吗? | ✅ YES | `NightActions.seer_result` + PRIVATE_INFO 事件 |
| 有信息释放策略吗? | ✅ YES | prompt 中有 "何时跳身份" 的策略指导 |
| 能看到历史查验吗? | ✅ YES | private_events 中包含历史 PRIVATE_INFO |

---

## 4.3 Witch (女巫)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/gods.py` — 阵营 Village, 夜晚行动 WITCH_SAVE |
| **夜晚动作** | WITCH_SAVE (救人), WITCH_POISON (毒人), SKIP (跳过) — 可返回多个 Decision |
| **白天动作** | TALK + VOTE |
| **私有信息** | 被刀目标 (night_attacked_player), 药物状态 (heal_used/poison_used) |
| **技能** | 救药 1 瓶, 毒药 1 瓶 (one-shot) |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[WITCH]` — 资源管理策略 |
| **动作策略** | `ACTION_STRATEGIES["witch_act"]["Witch"]` — 何时救/何时毒 |
| **Playbook** | `ACTION_PLAYBOOKS[WITCH]` — night_logic: 第一夜通常救人 |

### 关键问题回答

| 问题 | 答案 | 证据 |
|------|------|------|
| 知道被刀目标吗? | ✅ YES | `_witch_phase()` 传递 victim_id, 记录在 Prompt 的私有信息段 |
| 知道药物状态吗? | ✅ YES | `abilities.witch_heal_used` / `witch_poison_used` 追踪 |
| 能选择救/毒/跳过吗? | ✅ YES | `_witch_phase()` 支持多 Decision 返回, 可同时救+毒 |

---

## 4.4 Guard (守卫)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/gods.py` — 阵营 Village, 夜晚行动 GUARD |
| **夜晚动作** | GUARD — 守护一名玩家 (`game.py:_guard_phase()`) |
| **白天动作** | TALK + VOTE |
| **私有信息** | 上一晚守护目标 (last_guard_target_id) |
| **技能** | 每夜守一人, 不能连续守同一人 |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[GUARD]` |
| **动作策略** | `ACTION_STRATEGIES["guard"]["Guard"]` |
| **Playbook** | `ACTION_PLAYBOOKS[GUARD]` — night_logic: 首夜守预言家 |

### 关键问题回答

| 问题 | 答案 | 证据 |
|------|------|------|
| 记录上一晚目标吗? | ✅ YES | `NightActions.last_guard_target_id` |
| 遵守不能连续守同人吗? | ✅ YES | `_guard_phase()` 验证: `if target == last_guard_target_id → fallback` |

---

## 4.5 Hunter (猎人)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/gods.py` — 阵营 Village, 白天行动 SHOOT |
| **夜晚动作** | 无 |
| **白天动作** | TALK + VOTE + SHOOT (死亡时触发) |
| **私有信息** | `hunter_can_shoot` 状态 |
| **技能** | 死亡时开枪带人 (被毒杀除外) |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[HUNTER]` |
| **动作策略** | `ACTION_STRATEGIES["shoot"]["Hunter"]` |
| **Playbook** | `ACTION_PLAYBOOKS[HUNTER]` |

### 关键问题回答

| 问题 | 答案 | 证据 |
|------|------|------|
| 死亡时触发开枪吗? | ✅ YES | `_night_resolve()` 和 `_day_resolve()` 调用 `_hunter_shoot()` |
| 被毒杀时不能开枪吗? | ✅ YES | `_kill()` 中 if reason=="poison": hunter_can_shoot=False |

---

## 4.6 Villager (村民)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/basic.py` — 阵营 Village, 无夜晚行动 |
| **夜晚动作** | 无 |
| **白天动作** | TALK + VOTE |
| **私有信息** | 无 (仅公开信息) |
| **技能** | 无 |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[VILLAGER]` — 推理+投票策略 |
| **动作策略** | `ACTION_STRATEGIES["talk"]["Villager"]` — 分析发言, 找出狼人 |

### 关键问题回答

| 问题 | 答案 | 证据 |
|------|------|------|
| 只有公开信息吗? | ✅ YES | `PlayerView` 中 private_events 为空 (无夜晚行动) |

---

## 4.7 WhiteWolfKing (白狼王)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/wolves.py` — 阵营 Wolf, 白天行动 BOOM |
| **夜晚动作** | ATTACK (与普通狼人相同) |
| **白天动作** | TALK + VOTE + BOOM (自爆, 带人一起死) |
| **私有信息** | 狼队友列表, `white_wolf_king_boom_used` 状态 |
| **技能** | 白天发言中自爆带人 (one-shot), 打断发言/投票流程 |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[WHITE_WOLF_KING]` |
| **动作策略** | `ACTION_STRATEGIES["boom"]["WhiteWolfKing"]` |

---

## 4.8 Idiot (白痴)

| 维度 | 内容 |
|------|------|
| **角色定义** | `backend/engine/roles/wolfcha.py` — 阵营 Village, playable=True |
| **夜晚动作** | 无 |
| **白天动作** | TALK + VOTE (翻牌后失去投票权) |
| **私有信息** | 无 |
| **技能** | 首次被放逐时存活 (翻牌), 之后失去投票权 |
| **系统提示** | `ROLE_SYSTEM_PROMPTS[IDIOT]` |

---

## 4.9 角色实现差异汇总

| 角色 | 独立 System Prompt | 独立 Action Strategy | 独立 Playbook | 引擎逻辑 |
|------|-------------------|---------------------|---------------|---------|
| Werewolf | ✅ | ✅ | ✅ | ✅ _wolf_phase() |
| WhiteWolfKing | ✅ | ✅ (boom) | ✅ | ✅ _white_wolf_king_boom() |
| Seer | ✅ | ✅ (divine) | ✅ | ✅ _seer_phase() |
| Witch | ✅ | ✅ (witch_act) | ✅ | ✅ _witch_phase() |
| Guard | ✅ | ✅ (guard) | ✅ | ✅ _guard_phase() |
| Hunter | ✅ | ✅ (shoot) | ✅ | ✅ _hunter_shoot() |
| Villager | ✅ | ✅ (talk/vote) | ✅ | 无特殊夜逻 |
| Idiot | ✅ | ✅ (talk/vote) | ✅ | ✅ _day_resolve() |

---

## 4.10 关键审计结论

1. ✅ **每个角色有明显不同的 Prompt** — 系统提示、动作策略、策略简述各不相同
2. ✅ **每个角色有独立引擎逻辑** — 夜晚/白天行为在 game.py 中有独立方法
3. ✅ **狼人知道狼队友** — 通过 known_wolves 机制
4. ✅ **预言家记录查验历史** — 通过 NightActions.seer_result + PRIVATE_INFO
5. ✅ **女巫知道被刀目标和药物状态** — 通过 victim_id + abilities
6. ✅ **守卫遵守不能连续守同人规则** — game.py 中有显式验证
7. ✅ **猎人在死亡时触发开枪** — 毒杀除外
8. ✅ **村民只有公开信息** — PlayerView 无私有事件
9. ⚠️ **6 个模板角色未接入引擎** — Cupid/BigBadWolf/WolfCub/WolfKing/Knight/Elder
