# Prompt Strategy Injection V8

## Injection Points

1. **Talk system parts** — between base identity and behavior_hint
2. **Action prompt (user)** — after 角色目标 and before 事实速查
3. **Action system prompt** — after constraints and before bias_tail

## Strategy Card Block Format



## Distinction from strategy_bias

-  — experiment variable, has strategy_id, tracked in logs
-  — free-text per-action bias dict, no ID tracking, optional
-  — DB lookups, has doc_id but NOT strategy_id

## Example: 激进信息释放 (seer_aggressive_reveal_v1)

- Type: info_release
- Roles: Seer
- Tips: 14, Risks: 4
- Summary: 查验到狼人立即跳身份发布信息,报查验+留警徽流+聊心路历程,抢占信息主动权

### Policy Tips (first 5)

1. 首轮必须上警竞选警徽,防止悍跳狼误导好人
2. 发言三部曲:报查验→留警徽流→聊心路历程
3. 警徽流留两轮:警上一个+警下一个,防止狼两连爆
4. 查验逻辑:两好人撕警徽,两查杀外置位给,一好一杀给好人
5. 查到狼当天或次日首发位主动PR,直接报X号是狼

### Risk Notes (first 3)

1. 查到狼必须当天或次日PR,不留隔夜
2. PR后必须用查验逻辑反驳质疑,不能退缩
3. 面对悍跳狼不能退缩,必须坚定表达正确信息

---

## Example: 保守用药 (witch_conservative_save_v1)

- Type: resource_management
- Roles: Witch
- Tips: 11, Risks: 4
- Summary: 解药留给关键身份,毒药仅用于确认狼人,第一夜谨慎用药,白天隐藏身份

### Policy Tips (first 5)

1. 解药留给关键身份(预言家/猎人/守卫),毒药只用在确认是狼的玩家
2. 第一夜禁解药(除非死者是预言家)
3. 白天少发言,禁止主动暴露女巫身份
4. 发言基于预言家PR逻辑,不要凭空怀疑
5. 毒人前必须有≥2条证据(查验+投票+发言)

### Risk Notes (first 3)

1. 禁止保留药剂,药用完算赢是错误思路
2. 禁止考虑用药顺序,随便用也是错误
3. 首夜双药(解毒且开毒)的女巫胜率比单开毒药高18.5%

---

## Example: 悍跳带队冲锋 (werewolf_strong_vote_lead_v1)

- Type: vote_lead
- Roles: Werewolf, WhiteWolfKing
- Tips: 26, Risks: 0
- Summary: 悍跳狼+冲锋狼体系:冒充预言家争夺警徽,引导好人内斗,统一冲票行动,自爆时机把握

### Policy Tips (first 5)

1. 竞选警长时悍跳预言家,获取发言主导权
2. 报验人选择:前置位边缘平民(反水概率≈0)
3. 警徽流留上警玩家,符合预言家逻辑
4. 状态复刻:语速平稳,警徽流处故意停顿模拟思考
5. 退水预案:真预言家报验人是狼队友时立刻退水

---

## Example: 逻辑分析投票 (villager_logic_vote_v1)

- Type: logic_vote
- Roles: Villager, Idiot
- Tips: 11, Risks: 0
- Summary: 作为票型决定者,清晰表水+推理逻辑+关注票型一致性,阳光发言减少队友误投

### Policy Tips (first 5)

1. 村民是票型决定者,不要只'跟着投'
2. 表水:清晰说出心路历程和推理逻辑
3. 不要乱穿衣服(冒充神职),乱跳会导致神职暴露
4. 阳光发言减少队友浪费投票机会
5. 首轮老老实实表水,但不能太划水

---

## Verification

- [x] [STRATEGY_CARD] block injected in talk system parts
- [x] [STRATEGY_CARD] block injected in action prompt (user)
- [x] [STRATEGY_CARD] block injected in action system prompt
- [x] Distinct from strategy_bias (strategy_card has ID, bias does not)
- [x] Fallback when strategy_card does not apply to role (_validate_strategy_for_role)
- [x] 4 prompt examples generated (Seer/Witch/Werewolf/Villager)
