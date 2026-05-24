# AI 狼人杀 Track B：评测 + 复盘 + Valid 校验完整方案

## 0. 本文目标

本文只设计 **Track B：评测 + 复盘系统**，不进入 C 自进化。

Track B 的目标不是让 Agent 变强，而是让系统能够对一局狼人杀进行可信复盘：

```text
对局结束
→ 结构化回放
→ 多维评分
→ 发言语义分析
→ 怀疑度/信念追踪
→ 高光与失误识别
→ 证据链构建
→ 局部反事实推演
→ 结构化复盘报告
→ Valid Agent 校验
→ 不通过则修复重跑
→ 通过后发布
```

最终效果：

```text
1. 能说明每个 Agent 得分多少；
2. 能解释为什么得这个分；
3. 能指出关键高光和关键失误；
4. 能展示每个结论背后的证据；
5. 能做局部反事实推演；
6. 能自动生成复盘报告；
7. 能用 Valid Agent 检查报告是否可信；
8. 校验不通过时能返回修复路径。
```

------

## 1. Track B 的核心问题

Track B 要回答的问题是：

```text
如何系统化评价 Agent 决策质量，而不只看胜负？
```

因此，Track B 不能只做：

```text
狼人赢了 → 狼人高分
好人输了 → 好人低分
```

这种评分太粗糙。

狼人杀是一个信息不对称博弈。一个动作是否合理，不能只看最后结果，还要看：

```text
1. 当时 Agent 能看到什么？
2. 当时公开信息支持什么判断？
3. 这个角色的身份任务是什么？
4. 发言有没有基于事实？
5. 投票有没有符合当时怀疑度？
6. 技能有没有产生局部收益？
7. 有没有信息泄露或编造事实？
8. 如果换一种动作，局部结果是否可能更好？
```

所以 Track B 需要从“结果评价”升级为“过程评价 + 证据评价 + 反事实评价”。

------

## 2. 总体设计原则

### 2.1 分数不由大模型直接决定

LLM 不直接输出：

```text
P3 本局 87 分。
```

原因：

```text
1. 不稳定；
2. 不可复现；
3. 容易被提示词影响；
4. 很难解释为什么是 87 而不是 77；
5. 答辩时经不起追问。
```

正确做法：

```text
规则事实负责打底；
结构化语义分析负责补充；
怀疑度变化负责解释局势；
局部反事实负责衡量影响；
LLM 只做结构化抽取、报告表达和有限语义审核。
```

### 2.2 每个结论必须有证据链

任何高光、失误、建议、反事实，都必须能追溯到原始事件。

```text
没有 evidence_event_ids 的结论，不允许进入正式报告。
```

### 2.3 反事实必须分清“精确重算”和“估计推演”

投票改票可以精确重算。

```text
P4 3 票，P5 2 票；
如果 P2 从 P4 改投 P5；
则 P4 2 票，P5 3 票。
```

这叫 `exact_recalculation`。

但预言家如果公开查杀，其他人是否会跟票，是不确定的。

这只能叫 `estimated`。

报告中必须避免说：

```text
如果预言家公开查杀，好人一定获胜。
```

只能说：

```text
如果预言家公开查杀，目标狼人的公共怀疑度会上升，可能改变当日归票方向。
```

### 2.4 Valid Agent 是报告质量门，不是评分器

Valid Agent 不负责重新打分，不创造新结论。

Valid Agent 只负责检查：

```text
1. 报告是否符合 schema；
2. 事实是否和 replay 一致；
3. 分数是否和结构化评分一致；
4. 证据链是否完整；
5. 反事实是否越界；
6. 策略建议是否有来源；
7. 是否存在信息泄露；
8. 文档是否达到发布质量。
```

------

## 3. Track B 总流程

完整流程如下：

```text
1. Replay Loader
   读取完整对局回放。

2. Metrics Calculator
   计算多维评分。

3. Speech Act Analyzer
   解析发言中的立场、声明、证据、风险。

4. Belief Tracker / Suspicion Matrix
   根据公开信息维护怀疑度变化。

5. Bad Case Detector
   定位关键失误。

6. Highlight Detector
   识别关键高光。

7. Evidence Builder
   给所有复盘结论绑定原始事件证据。

8. Counterfactual Analyzer
   做投票、技能、信息释放三类局部反事实。

9. Review Report Builder
   生成结构化复盘报告。

10. Report Agent
   把结构化报告渲染成 Markdown / 前端可读文本。

11. Valid Agent
   检查事实、证据、分数、反事实和表达是否合法。

12. Repair Loop
   不通过则调用工具补证据、重算、修复报告。

13. Approved Report
   通过后入库并展示。
```

------

## 4. 数据输入：Replay Bundle

Track B 的所有评分和复盘都必须基于统一的回放对象。

### 4.1 ReplayBundle

伪结构：

```python
class ReplayBundle:
    game_id: str
    rule_pack: str
    seed: int | None

    players: list[PlayerRecord]
    events: list[GameEvent]
    decisions: list[AgentDecision]
    votes: list[VoteRecord]
    deaths: list[DeathRecord]

    final_state: dict
    winner: str
    finished_at: str
```

### 4.2 GameEvent

每个事件必须有唯一 `event_id`。

```python
class GameEvent:
    event_id: str
    game_id: str
    seq: int
    day: int
    phase: str
    event_type: str

    actor_id: str | None
    target_id: str | None

    visibility: str
    visible_to: list[str]

    content: dict
    public_text: str | None

    decision_id: str | None
    causal_parent_ids: list[str]
```

事件类型至少包括：

```text
GAME_START
ROLE_ASSIGN
NIGHT_START
WEREWOLF_KILL
SEER_CHECK
WITCH_SAVE
WITCH_POISON
GUARD_PROTECT
HUNTER_SHOT
DAY_START
SPEECH
VOTE_CAST
VOTE_TALLY
EXILE
DEATH
ROLE_REVEAL
GAME_END
```

### 4.3 AgentDecision

Agent 的每次动作都要记录决策过程。

```python
class AgentDecision:
    decision_id: str
    game_id: str
    event_id: str | None

    player_id: str
    role: str
    camp: str
    day: int
    phase: str

    observation_summary: str
    legal_actions: list[dict]
    selected_action: dict

    public_reason: str | None
    private_reason: str | None

    prompt_version: str
    strategy_version: str | None
    persona_id: str | None
    model_name: str | None

    parsed_success: bool
    fallback_used: bool
    error_type: str | None
```

### 4.4 这么做的原因

如果没有统一 ReplayBundle，后续评分模块、反事实模块、报告模块和 Valid Agent 会各读各的数据，很容易出现不一致。

统一 ReplayBundle 后，所有模块都有同一个事实来源：

```text
评分来自 replay；
证据来自 replay；
反事实基于 replay；
报告引用 replay；
Valid Agent 也用 replay 验证报告。
```

### 4.5 预期效果

```text
1. 报告里的每句话都可以回查事件；
2. 评分和复盘不会各说各话；
3. 反事实能基于真实票型和技能记录；
4. Valid Agent 可以做事实校验。
```

------

## 5. 多维评分体系

### 5.1 总分公式

建议使用混合评分：

```text
FinalScore =
  0.35 * RuleOutcomeScore
+ 0.20 * RoleTaskScore
+ 0.15 * BeliefDecisionScore
+ 0.15 * SpeechSemanticScore
+ 0.10 * CounterfactualImpactScore
+ 0.05 * RobustnessScore
```

### 5.2 为什么这样设计

| 分项                      | 为什么需要                     | 解决什么问题                               |
| ------------------------- | ------------------------------ | ------------------------------------------ |
| RuleOutcomeScore          | 胜负、技能、投票等硬事实最可靠 | 保证评分底座稳定                           |
| RoleTaskScore             | 不同角色目标不同               | 避免所有角色共用一个粗糙标准               |
| BeliefDecisionScore       | 狼人杀是信息不对称博弈         | 判断当时这个决策是否基于合理怀疑           |
| SpeechSemanticScore       | 发言是狼人杀核心               | 避免只看关键词和字数                       |
| CounterfactualImpactScore | 关键动作需要衡量影响           | 找出真正改变局部结果的决策                 |
| RobustnessScore           | Agent 工程质量也重要           | 惩罚非法动作、fallback、格式错误、信息泄露 |

------

## 6. RuleOutcomeScore：硬事实分

### 6.1 评价内容

```text
1. 阵营是否获胜；
2. 玩家是否存活到关键阶段；
3. 投票目标最终身份；
4. 技能目标最终身份；
5. 是否有非法动作；
6. 是否触发 fallback；
7. 是否出现信息泄露。
```

### 6.2 伪代码

```python
def compute_rule_outcome_score(player, replay):
    score = 0.0

    if player.camp == replay.winner:
        score += 0.35

    if player.alive_at_end:
        score += 0.10

    score += vote_result_component(player, replay) * 0.25
    score += skill_result_component(player, replay) * 0.20

    if player.invalid_action_count > 0:
        score -= 0.10

    if player.fallback_count > 0:
        score -= min(0.10, 0.03 * player.fallback_count)

    if player.info_leak_count > 0:
        score -= 0.20

    return clamp(score, 0, 1)
```

### 6.3 效果

RuleOutcomeScore 能保证评分有硬事实底座。

它不会评价复杂语义，但可以稳定判断：

```text
谁赢了；
谁投错了；
谁毒错了；
谁开枪误伤了；
谁出现非法动作了。
```

------

## 7. RoleTaskScore：角色任务分

RoleTaskScore 是 Track B 的核心。不同角色必须有不同标准。

------

### 7.1 狼人 Werewolf

评价目标：

```text
隐藏身份、误导好人、推动好人出局、保护或卖队友时机合理。
```

指标：

```text
knife_value：夜晚刀口价值；
deception_score：白天伪装质量；
vote_manipulation：是否推动好人被放逐；
team_coordination：狼队协作是否合理；
exposure_risk：抱团、强保、视角泄露风险。
```

伪代码：

```python
def score_werewolf(player, replay, suspicion):
    knife = score_wolf_kill_value(player, replay)
    vote_push = score_wolf_vote_manipulation(player, replay)
    deception = score_deception(player, suspicion)
    coordination = score_wolf_coordination(player, replay)
    exposure = score_wolf_exposure_risk(player, replay)

    return weighted_sum({
        "knife": (knife, 0.25),
        "vote_push": (vote_push, 0.25),
        "deception": (deception, 0.25),
        "coordination": (coordination, 0.15),
        "exposure_penalty": (-exposure, 0.10),
    })
```

效果：

```text
可以区分“会伪装的狼人”和“只会乱踩的狼人”。
```

------

### 7.2 预言家 Seer

评价目标：

```text
查验高价值目标，并把查验结果转化为公共归票信息。
```

指标：

```text
check_value：查验目标价值；
info_conversion：查验结果是否公开利用；
vote_guidance：是否带队归票；
reveal_timing：跳身份时机；
survival_strategy：是否无意义暴露。
```

伪代码：

```python
def score_seer(player, replay):
    checks = get_seer_checks(player, replay)

    check_value = avg(value_of_checked_target(c.target) for c in checks)
    conversion = score_seer_info_conversion(player, checks, replay)
    guidance = score_vote_guidance_after_claim(player, replay)
    reveal = score_reveal_timing(player, replay)

    return 0.25*check_value + 0.35*conversion + 0.25*guidance + 0.15*reveal
```

效果：

```text
能识别“查到狼但没说”的查杀沉没问题。
```

------

### 7.3 女巫 Witch

评价目标：

```text
救药保关键好人，毒药命中狼人，避免误伤。
```

指标：

```text
save_value：救药价值；
poison_accuracy：毒药命中；
medicine_timing：用药时机；
friendly_fire_penalty：误伤惩罚。
```

伪代码：

```python
def score_witch(player, replay):
    save_value = score_witch_save(player, replay)
    poison_value = score_witch_poison(player, replay)
    timing = score_medicine_timing(player, replay)
    friendly_fire = detect_witch_friendly_fire(player, replay)

    return clamp(
        0.30*save_value +
        0.35*poison_value +
        0.20*timing -
        0.25*friendly_fire,
        0, 1
    )
```

效果：

```text
女巫毒错好人会被明确识别并扣分；毒中狼人会被识别为高光。
```

------

### 7.4 猎人 Hunter

评价目标：

```text
开枪命中狼人，或者在不确定时克制不开枪。
```

指标：

```text
shot_accuracy：是否打中狼人；
shot_basis：开枪依据是否充分；
restraint_score：不确定时是否克制；
endgame_impact：残局影响。
```

伪代码：

```python
def score_hunter(player, replay, suspicion):
    shot = get_hunter_shot(player, replay)

    if not shot:
        return score_hunter_restraint(player, replay, suspicion)

    target_alignment = get_alignment(shot.target)
    accuracy = 1.0 if target_alignment == "wolf" else 0.0
    basis = score_action_basis(shot, suspicion)
    impact = score_endgame_impact(shot, replay)

    return 0.45*accuracy + 0.25*basis + 0.30*impact
```

效果：

```text
不是“开枪就有分”，而是看开枪依据和目标价值。
```

------

### 7.5 村民 Villager

评价目标：

```text
基于公开信息推理，避免盲跟，投票尽量命中狼人。
```

指标：

```text
vote_accuracy：投票命中；
reasoning_groundedness：推理是否基于公开事实；
belief_update：是否根据新信息更新怀疑；
follow_risk：是否无依据跟票。
```

伪代码：

```python
def score_villager(player, replay, speech_acts, suspicion):
    vote_accuracy = score_good_vote_accuracy(player, replay)
    grounding = score_speech_grounding(player, speech_acts)
    belief_update = score_belief_update(player, suspicion)
    follow_risk = score_follow_risk(player, replay)

    return 0.35*vote_accuracy + 0.30*grounding + 0.20*belief_update - 0.15*follow_risk
```

效果：

```text
村民不会因为“没技能”而无法评价。
```

------

## 8. SpeechSemanticScore：发言语义分

### 8.1 为什么需要发言语义分析

纯规则通常只能判断：

```text
发言字数；
是否提到“狼”；
是否点名玩家。
```

这太浅。

真正有价值的发言应该看：

```text
1. 有没有基于真实公开事件；
2. 有没有明确踩谁、保谁、归票谁；
3. 有没有前后逻辑一致；
4. 有没有推动阵营目标；
5. 有没有编造事实或泄露私有信息。
```

### 8.2 发言分公式

```text
SpeechSemanticScore =
  0.25 * groundedness
+ 0.20 * stance_clarity
+ 0.20 * consistency
+ 0.20 * strategic_value
+ 0.15 * info_safety
```

### 8.3 SpeechAct 输出

```python
class SpeechAct:
    event_id: str
    speaker_id: str
    day: int
    phase: str

    claims: list[dict]
    stance: dict
    grounded_event_ids: list[str]

    vote_suggestion: str | None
    defended_players: list[str]
    suspected_players: list[str]

    fabrication_risk: bool
    private_info_leak_risk: bool

    consistency_score: float
    strategic_value: float
```

### 8.4 LLM 的使用边界

LLM 可以做：

```text
抽取 claims；
抽取 stance；
判断发言中提到的事实是否有可能是编造；
判断是否疑似泄露私有信息；
把文本转成结构化 SpeechAct。
```

LLM 不能做：

```text
直接给发言打 87 分；
直接决定谁是 MVP；
直接决定谁犯了 critical 错误。
```

### 8.5 伪代码

```python
def analyze_speech(event, replay):
    extracted = llm_or_rule_extract_speech_act(event.public_text)

    grounded_ids = match_claims_to_events(extracted.claims, replay.events)
    fabrication_risk = len(extracted.claims) > 0 and len(grounded_ids) == 0
    info_leak_risk = detect_private_info_leak(extracted.claims, event, replay)

    return SpeechAct(
        event_id=event.event_id,
        speaker_id=event.actor_id,
        claims=extracted.claims,
        stance=extracted.stance,
        grounded_event_ids=grounded_ids,
        fabrication_risk=fabrication_risk,
        private_info_leak_risk=info_leak_risk,
        consistency_score=compute_consistency(event.actor_id, extracted, replay),
        strategic_value=compute_strategic_value(event.actor_id, extracted, replay),
    )
```

### 8.6 效果

系统可以识别：

```text
空话发言；
无依据强踩；
有证据归票；
狼人的伪装发言；
预言家的查杀释放；
编造不存在投票；
村民说出只有女巫才知道的信息。
```

------

## 9. BeliefDecisionScore：怀疑度决策分

### 9.1 为什么需要 Suspicion Matrix

狼人杀是信息不对称游戏。

一个玩家投错，不一定就是低质量。关键要看：

```text
当时公开信息下，谁的狼面更高？
这个玩家的投票是否符合当时的合理怀疑？
```

### 9.2 SuspicionMatrix

第一版可以先做公共怀疑度：

```python
class SuspicionSnapshot:
    game_id: str
    day: int
    phase: str
    target_scores: dict[str, float]
    evidence_event_ids: dict[str, list[str]]
```

### 9.3 更新规则

```text
1. 投票给好人：投票者风险上升；
2. 投票给狼人：投票者可信度上升；
3. 强保被查杀狼人：保护者风险上升；
4. 公开查杀且命中：目标狼面上升，发言者可信度上升；
5. 发言编造事实：发言者风险上升；
6. 狼人抱团投票：相关玩家风险上升；
7. 角色翻牌后：回溯修正相关怀疑度。
```

### 9.4 伪代码

```python
def update_suspicion(snapshot, event, speech_act=None):
    scores = snapshot.target_scores.copy()

    if event.event_type == "VOTE_CAST":
        target = event.target_id
        actor = event.actor_id
        if is_revealed_good(target):
            scores[actor] += 0.08
        if is_revealed_wolf(target):
            scores[actor] -= 0.08

    if speech_act:
        for target in speech_act.suspected_players:
            scores[target] += 0.05
        for target in speech_act.defended_players:
            if is_publicly_suspected(target):
                scores[event.actor_id] += 0.04
        if speech_act.fabrication_risk:
            scores[event.actor_id] += 0.12
        if speech_act.private_info_leak_risk:
            scores[event.actor_id] += 0.20

    return normalize(scores)
```

### 9.5 BeliefDecisionScore

```python
def score_belief_decision(player, decision, suspicion_before):
    if decision.type == "vote":
        target = decision.selected_action["target"]
        rank = rank_by_suspicion(target, suspicion_before)
        return rank_to_score(rank)

    if decision.type in ["poison", "shoot"]:
        target = decision.selected_action["target"]
        return suspicion_before[target]

    return neutral_score()
```

### 9.6 效果

```text
P2 投错了，但当时 P4 公共狼面最高 → 少扣分；
P3 投错了，而且当时 P5 已被查杀 → 重扣分；
狼人成功让自己怀疑度下降 → 伪装加分；
预言家公开查杀后目标怀疑度上升 → 信息转化加分。
```

------

## 10. BadCaseDetector：失误定位

### 10.1 BadCase 类型

第一版至少覆盖：

```text
GOOD_VOTE_CONFIRMED_GOOD
GOOD_CONTINUOUS_MISVOTE
SEER_WOLF_CHECK_NOT_RELEASED
WITCH_POISON_GOOD
HUNTER_SHOOT_GOOD
WEREWOLF_EXCESSIVE_BUNDLED_VOTE
WEREWOLF_MEANINGLESS_BETRAYAL
SPEECH_FABRICATED_EVENT
PRIVATE_INFO_LEAK_RISK
INVALID_ACTION
LLM_FALLBACK_OVERUSE
```

### 10.2 BadCase 结构

```python
class BadCase:
    bad_case_id: str
    player_id: str
    role: str
    day: int
    phase: str

    bad_case_type: str
    severity: str

    title: str
    summary: str
    evidence_event_ids: list[str]

    score_penalty: float
    suggestion: str
```

### 10.3 伪代码示例：女巫毒好人

```python
def detect_witch_poison_good(replay):
    cases = []
    for event in replay.events:
        if event.event_type != "WITCH_POISON":
            continue
        target = event.target_id
        if get_camp(target) == "good":
            cases.append(BadCase(
                player_id=event.actor_id,
                role="witch",
                day=event.day,
                phase=event.phase,
                bad_case_type="WITCH_POISON_GOOD",
                severity="critical",
                title="女巫毒药误伤好人",
                summary=f"女巫在第 {event.day} 夜毒杀好人 {target}，造成好人阵营额外减员。",
                evidence_event_ids=[event.event_id],
                score_penalty=0.20,
                suggestion="毒药应结合公开票型、查验信息和怀疑度使用，避免单凭直觉盲毒。"
            ))
    return cases
```

### 10.4 效果

BadCaseDetector 是 B 的硬验收核心。

它能展示：

```text
系统不是只统计胜负，而是能自动定位具体失误。
```

------

## 11. HighlightDetector：高光识别

### 11.1 高光类型

```text
SEER_INFO_CONVERSION
WITCH_KEY_SAVE
WITCH_POISON_WOLF
HUNTER_SHOOT_WOLF
WEREWOLF_PUSH_GOOD_EXILE
VILLAGER_CORRECT_VOTE_CHAIN
GUARD_KEY_PROTECT
```

### 11.2 Highlight 结构

```python
class Highlight:
    highlight_id: str
    player_id: str
    role: str
    day: int
    phase: str

    highlight_type: str
    title: str
    summary: str

    evidence_event_ids: list[str]
    score_bonus: float
    impact_level: str
```

### 11.3 伪代码示例：预言家查杀转化

```python
def detect_seer_info_conversion(replay):
    highlights = []
    for check in get_seer_wolf_checks(replay):
        speech = find_public_speech_claiming_check(check)
        vote_result = find_exile_of_target_after_claim(check.target_id)

        if speech and vote_result:
            highlights.append(Highlight(
                player_id=check.actor_id,
                role="seer",
                day=speech.day,
                phase=speech.phase,
                highlight_type="SEER_INFO_CONVERSION",
                title="预言家成功将查杀转化为放逐",
                summary="预言家夜间查验到狼人，并在白天公开信息推动归票，最终狼人出局。",
                evidence_event_ids=[check.event_id, speech.event_id, vote_result.event_id],
                score_bonus=0.12,
                impact_level="high"
            ))
    return highlights
```

### 11.4 效果

HighlightDetector 能让系统不仅“挑错”，也能识别优秀打法。

这对 MVP、Leaderboard 和后续 C 都很重要。

------

## 12. EvidenceBuilder：证据链构建

### 12.1 为什么必须有 EvidenceBuilder

评分和复盘如果没有证据，就变成空口评价。

EvidenceBuilder 的作用是：

```text
把每个结论和原始事件绑定起来。
```

### 12.2 EvidenceItem

```python
class EvidenceItem:
    evidence_id: str
    source_item_id: str
    event_id: str

    evidence_kind: str
    claim: str
    snippet: str | None

    confidence: float
    weight: float
```

### 12.3 伪代码

```python
def build_evidence_for_item(item, replay):
    evidence = []
    for event_id in item.evidence_event_ids:
        event = find_event(replay, event_id)
        if not event:
            continue
        evidence.append(EvidenceItem(
            source_item_id=item.id,
            event_id=event.event_id,
            evidence_kind="raw_event",
            claim=describe_event(event),
            snippet=event.public_text,
            confidence=1.0,
            weight=1.0,
        ))
    return evidence
```

### 12.4 强约束

```text
BadCase 没有证据 → 不允许进入报告；
Highlight 没有证据 → 不允许进入报告；
Counterfactual 没有证据 → 不允许进入报告；
StrategySuggestion 没有来源 → 降级或删除。
```

------

## 13. CounterfactualAnalyzer：局部反事实

反事实分三类。

------

### 13.1 Vote Flip：投票反事实

#### 设计

重新计算当日票型。

```text
原始票型：
P4 3 票，好人出局；
P5 2 票，狼人未出局。

反事实：
如果 P2 从 P4 改投 P5：
P4 2 票；
P5 3 票；
狼人 P5 出局。
```

#### 伪代码

```python
def analyze_vote_flip(day_votes, actual_exile):
    cases = []
    tally = count_votes(day_votes)

    for voter, original_target in day_votes.items():
        for alternative_target in alive_players_except(voter):
            if alternative_target == original_target:
                continue

            new_votes = day_votes.copy()
            new_votes[voter] = alternative_target
            new_tally = count_votes(new_votes)
            new_exile = resolve_vote(new_tally)

            if new_exile != actual_exile:
                cases.append(CounterfactualCase(
                    cf_type="vote_flip",
                    effect_type="exact_recalculation",
                    original_decision={"voter": voter, "target": original_target},
                    alternative_decision={"voter": voter, "target": alternative_target},
                    original_outcome={"exile": actual_exile},
                    counterfactual_outcome={"exile": new_exile},
                    confidence=1.0,
                    evidence_event_ids=get_vote_event_ids(day_votes)
                ))
    return cases
```

#### 效果

能定位 pivot vote：

```text
这一票如果改变，当日出局对象会改变。
```

------

### 13.2 Skill Swap：技能反事实

#### 覆盖场景

```text
女巫毒好人 → 如果不毒，避免友军损失；
女巫没救关键神职 → 如果救，保留信息源；
猎人枪好人 → 如果不开枪，避免扩大损失；
守卫没守关键目标 → 如果守对，可能挡刀。
```

#### 伪代码

```python
def analyze_skill_counterfactual(event, replay):
    if event.event_type == "WITCH_POISON" and is_good(event.target_id):
        return CounterfactualCase(
            cf_type="skill_swap",
            effect_type="local_recalculation",
            original_decision={"action": "poison", "target": event.target_id},
            alternative_decision={"action": "skip_poison"},
            original_outcome={"extra_good_death": event.target_id},
            counterfactual_outcome={"extra_good_death": None},
            confidence=0.9,
            evidence_event_ids=[event.event_id],
            conclusion="如果女巫不使用毒药，至少可以避免这一名好人额外死亡。"
        )
```

#### 注意

技能反事实不能直接说会改变最终胜负，只能说局部结果变化。

------

### 13.3 Info Release：信息释放反事实

#### 覆盖场景

```text
预言家查到狼人，但白天没有公开；
好人阵营因为缺少公共信息而误投。
```

#### 伪代码

```python
def analyze_info_release_counterfactual(seer_check, replay, suspicion):
    if not seer_check.is_wolf:
        return None

    released = did_seer_publicly_release(seer_check, replay)
    if released:
        return None

    before = suspicion.get_score(seer_check.target_id, day=seer_check.day + 1)
    estimated_after = min(1.0, before + 0.30)

    return CounterfactualCase(
        cf_type="info_release",
        effect_type="estimated",
        original_decision={"action": "withhold_check", "target": seer_check.target_id},
        alternative_decision={"action": "public_claim", "target": seer_check.target_id},
        original_outcome={"target_suspicion": before},
        counterfactual_outcome={"estimated_target_suspicion": estimated_after},
        confidence=0.65,
        evidence_event_ids=[seer_check.event_id],
        conclusion="如果预言家公开查杀，目标的公共怀疑度预计会上升，可能改变当日归票方向。"
    )
```

#### 效果

能解释：

```text
预言家不是单纯没发言，而是浪费了可转化为公共共识的信息。
```

------

## 14. ReviewReport：报告结构

### 14.1 ReviewReport JSON

```python
class ReviewReport:
    report_id: str
    game_id: str
    created_at: str

    summary: dict
    scoreboard: list[dict]
    mvp: dict | None

    highlights: list[Highlight]
    bad_cases: list[BadCase]
    counterfactuals: list[CounterfactualCase]
    evidence_items: list[EvidenceItem]

    strategy_suggestions: list[dict]

    quality_gate: dict
    validation_result: dict | None
```

### 14.2 Markdown 章节

```text
# 本局复盘报告

## 1. 本局概览
## 2. 玩家评分榜
## 3. MVP
## 4. 关键高光
## 5. 关键失误
## 6. 反事实推演
## 7. 角色策略建议
## 8. 报告可信度校验
```

### 14.3 为什么要 JSON + Markdown

```text
JSON 给系统和前端用；
Markdown 给人看和答辩展示用；
Valid Agent 同时校验 JSON 和 Markdown，保证二者一致。
```

------

## 15. Valid Agent：校验与修复闭环

### 15.1 Valid Agent 总目标

Valid Agent 负责保证报告可信。

它不是评分器，而是质量门。

### 15.2 Valid Agent 检查维度

```text
1. SchemaValidityGate
2. ReportCompletenessGate
3. EvidenceCoverageGate
4. FactConsistencyGate
5. ScoreConsistencyGate
6. CounterfactualSoundnessGate
7. VisibilitySafetyGate
8. RecommendationGroundingGate
9. PresentationQualityGate
```

------

## 16. SchemaValidityGate

### 检查

```text
ReviewReport 是否符合 schema；
字段类型是否正确；
必填字段是否存在；
列表字段是否为空但被引用。
```

### 效果

防止报告结构坏掉，前端无法渲染。

------

## 17. ReportCompletenessGate

### 检查

Markdown 必须包含：

```text
本局概览；
玩家评分榜；
MVP；
关键高光；
关键失误；
反事实推演；
角色策略建议；
报告可信度校验。
```

### 效果

保证报告可以用于答辩和前端展示。

------

## 18. EvidenceCoverageGate

### 检查

以下对象必须有证据：

```text
BadCase；
Highlight；
CounterfactualCase；
StrategySuggestion；
MVP；
TurningPoint。
```

### 伪代码

```python
def validate_evidence_coverage(report):
    issues = []
    for item in report.bad_cases + report.highlights + report.counterfactuals:
        if not item.evidence_event_ids:
            issues.append(issue(
                gate="EvidenceCoverageGate",
                severity="critical",
                message=f"{item.id} 缺少 evidence_event_ids",
                repair_tool="EvidenceResolveTool"
            ))
    return issues
```

### 效果

防止报告出现“没有证据的评价”。

------

## 19. FactConsistencyGate

### 检查

报告中的事实必须能在 ReplayBundle 中找到。

例如报告说：

```text
P3 在 Day2 投了 P5。
```

必须找到：

```text
event_type = VOTE_CAST
actor_id = P3
target_id = P5
day = 2
```

### 伪代码

```python
def validate_fact_consistency(report, replay):
    issues = []
    claims = extract_fact_claims(report.markdown)

    for claim in claims:
        matched = match_claim_to_replay(claim, replay)
        if not matched:
            issues.append(issue(
                gate="FactConsistencyGate",
                severity="critical",
                message=f"报告中的事实无法在 replay 中找到：{claim.text}",
                repair_tool="ReplayQueryTool"
            ))
    return issues
```

### 效果

防止报告 hallucination。

------

## 20. ScoreConsistencyGate

### 检查

```text
JSON 分数和 Markdown 分数一致；
MVP 和结构化 mvp 字段一致；
排名和 scoreboard 一致；
分项分和总分公式一致。
```

### 伪代码

```python
def validate_score_consistency(report):
    issues = []
    recomputed = recompute_scoreboard(report.score_inputs)

    if report.scoreboard != recomputed:
        issues.append(issue(
            gate="ScoreConsistencyGate",
            severity="critical",
            message="scoreboard 与重算结果不一致",
            repair_tool="ScoreRecomputeTool"
        ))

    markdown_scores = parse_scores_from_markdown(report.markdown)
    if not compare(markdown_scores, report.scoreboard):
        issues.append(issue(
            gate="ScoreConsistencyGate",
            severity="major",
            message="Markdown 中的分数和 JSON 不一致",
            repair_tool="ScoreTableRenderer"
        ))
    return issues
```

### 效果

防止报告里写错分数。

------

## 21. CounterfactualSoundnessGate

### 检查

#### vote_flip

```text
是否真的重算票型；
替代投票是否合法；
新出局结果是否正确；
如果结果不变，不能称为关键反事实。
```

#### skill_swap

```text
原技能是否真实发生；
替代动作是否合法；
是否只描述局部影响；
不能直接推导最终胜负。
```

#### info_release

```text
effect_type 必须是 estimated；
必须引用 suspicion/belief 变化；
不能写成确定性结论。
```

### 伪代码

```python
def validate_counterfactual(cf, replay):
    if cf.cf_type == "vote_flip":
        recalculated = recompute_vote_flip(cf, replay)
        if recalculated != cf.counterfactual_outcome:
            return critical_issue("投票反事实结果与重算结果不一致")

    if cf.cf_type == "info_release":
        if cf.effect_type != "estimated":
            return critical_issue("信息释放反事实必须标记为 estimated")
        if contains_deterministic_claim(cf.conclusion):
            return major_issue("estimated 反事实不能写成必然结果")
```

### 效果

防止反事实吹过头。

------

## 22. VisibilitySafetyGate

### 检查

如果是公开/玩家视角报告，不能泄露：

```text
未公开身份；
狼人队友信息；
预言家未公开查验；
女巫私有刀口；
Agent private_reason；
夜晚私有行动。
```

第一版可以默认 `moderator_view`，但 schema 中必须保留 `view_scope`。

### 效果

保证未来做玩家视角复盘时不破坏信息隔离。

------

## 23. RecommendationGroundingGate

### 检查

每条策略建议必须来自：

```text
BadCase；
Highlight；
CounterfactualCase；
Score Weakness；
EvidenceItem。
```

不允许空泛建议。

不合格：

```text
女巫以后大胆一点。
```

合格：

```text
本局女巫 Day1 毒杀好人 P4，造成好人阵营额外减员。建议女巫在没有公开票型和查验信息支撑时，不要过早使用毒药。
```

------

## 24. PresentationQualityGate

### 检查

```text
是否语言清楚；
是否没有裸露英文枚举；
是否没有 debug 字段；
是否没有大段 JSON 原文；
是否适合前端展示；
是否每段结论简洁可读。
```

------

## 25. ValidationResult

```python
class ValidationIssue:
    issue_id: str
    severity: str  # critical / major / minor / suggestion
    gate: str
    issue_type: str

    location: dict
    message: str
    evidence: list[str]

    required_fix: str
    repair_tool: str | None
    blocking: bool
class ValidationResult:
    report_id: str
    game_id: str

    passed: bool
    grade: str  # pass / needs_revision / reject
    score: float

    issues: list[ValidationIssue]

    required_tools: list[str]
    revision_instructions: list[str]

    publish_allowed: bool
```

------

## 26. Repair Loop

### 26.1 流程

```text
ReportAgent 生成 draft_report
↓
ValidAgent 校验
↓
如果 passed：发布
↓
如果不通过：
  根据 issues 调用 repair tools
  ReportAgent 只重写有问题的章节
  再次 ValidAgent 校验
↓
最多 3 轮
↓
仍失败则 REJECTED
```

### 26.2 伪代码

```python
def run_review_with_validation(game_id, max_rounds=3):
    replay = load_replay(game_id)

    score = compute_metrics(replay)
    speech = analyze_speech(replay)
    suspicion = build_suspicion(replay, speech)
    bad_cases = detect_bad_cases(replay, score, speech, suspicion)
    highlights = detect_highlights(replay, score, speech, suspicion)
    evidence = build_evidence(replay, bad_cases, highlights)
    counterfactuals = analyze_counterfactuals(replay, bad_cases, highlights, suspicion)

    report = build_review_report(
        replay=replay,
        score=score,
        speech=speech,
        suspicion=suspicion,
        bad_cases=bad_cases,
        highlights=highlights,
        evidence=evidence,
        counterfactuals=counterfactuals,
    )

    markdown = render_markdown(report)

    for i in range(max_rounds):
        validation = validate_report(report, markdown, replay)
        if validation.passed:
            return approve(report, markdown, validation)

        tool_outputs = run_repair_tools(validation, replay, report)
        report, markdown = repair_report(report, markdown, validation, tool_outputs)

    final_validation = validate_report(report, markdown, replay)
    return reject(report, markdown, final_validation)
```

------

## 27. Repair Tools

Valid Agent 发现问题后，不能让 Report Agent 自己猜，必须调用工具。

### 27.1 ReplayQueryTool

用途：修复事实错误。

```text
输入：player_id / day / phase / event_type
输出：真实事件列表
```

### 27.2 EvidenceResolveTool

用途：补证据链。

```text
输入：review_item_id
输出：可绑定的 event_id 列表
```

### 27.3 ScoreRecomputeTool

用途：重算分数。

```text
输入：game_id
输出：scoreboard + score breakdown
```

### 27.4 CounterfactualRecomputeTool

用途：重算反事实。

```text
输入：cf_id
输出：重算后的 original_outcome / counterfactual_outcome
```

### 27.5 SpeechActRecheckTool

用途：重查发言语义。

```text
输入：speech_event_id
输出：claims / stance / grounded_events / risk_flags
```

### 27.6 VisibilityCheckTool

用途：检查信息隔离。

```text
输入：report_section / view_scope
输出：是否泄露私有信息
```

------

## 28. Valid Agent Prompt 原则

Valid Agent 的 prompt 必须强调：

```text
1. 你不是复盘作者；
2. 你不是评分器；
3. 你不能创造新事实；
4. 你只审核 report 是否与 replay / score / evidence / counterfactual 一致；
5. 你必须输出结构化 JSON；
6. 发现 critical issue 时 publish_allowed=false。
```

------

## 29. Report Agent 修复原则

Report Agent 修复时必须遵守：

```text
1. 不要重写整篇，除非 Valid Agent 要求；
2. 只修复出问题的 section；
3. 事实必须来自工具输出；
4. 分数必须来自 ScoreRecomputeTool；
5. 证据必须来自 EvidenceResolveTool；
6. 反事实必须来自 CounterfactualRecomputeTool；
7. 证据不足时删除结论或降级为不确定观察。
```

------

## 30. Leaderboard 聚合

B 的最后一步是多局聚合。

### 30.1 聚合维度

```text
role
model
prompt_version
strategy_version
persona
persona_role_pair
```

### 30.2 指标

```python
class LeaderboardEntry:
    scope: str
    key: str

    games_played: int
    win_rate: float

    avg_final_score: float
    avg_rule_outcome_score: float
    avg_role_task_score: float
    avg_belief_decision_score: float
    avg_speech_semantic_score: float
    avg_counterfactual_impact_score: float
    avg_robustness_score: float

    critical_bad_cases_per_game: float
    highlights_per_game: float
    info_leak_count: int
    invalid_action_rate: float
    fallback_rate: float

    best_role: str | None
    weak_role: str | None
```

### 30.3 效果

Leaderboard 能回答：

```text
哪个角色最弱；
哪个模型发言更强；
哪个人格玩狼人更容易暴露；
哪个 prompt 版本更稳定；
哪个 Agent 经常出现信息泄露；
哪个版本关键失误最少。
```

------

## 31. 前端展示计划

Review 页面展示：

```text
1. 报告状态：APPROVED / NEEDS_REVISION / REJECTED；
2. 校验分数；
3. 九个 Quality Gate 通过情况；
4. 玩家评分榜；
5. MVP；
6. 关键高光；
7. 关键失误；
8. 证据链抽屉；
9. 反事实卡片；
10. 角色策略建议。
```

Leaderboard 页面展示：

```text
1. role 榜；
2. persona 榜；
3. persona_role_pair 榜；
4. model / prompt_version 榜；
5. 分项指标对比；
6. 关键失误率；
7. fallback / invalid action / info leak 指标。
```

------

## 32. 测试计划

### 32.1 评分测试

```text
test_rule_outcome_score
测试胜负、投票、技能、非法动作是否正确影响分数。
test_role_task_score
分别测试狼人、预言家、女巫、猎人、村民的角色专项评分。
```

### 32.2 发言分析测试

```text
test_speech_act_grounding
发言引用真实投票，应匹配对应 event_id。
test_speech_fabrication_risk
发言编造不存在事件，应触发 fabrication_risk。
test_private_info_leak_risk
村民说出未公开夜晚刀口，应触发 private_info_leak_risk。
```

### 32.3 怀疑度测试

```text
test_suspicion_vote_update
投好人/投狼人后，怀疑度正确变化。
test_suspicion_public_claim_update
预言家公开查杀后，目标怀疑度上升。
```

### 32.4 BadCase / Highlight 测试

```text
test_witch_poison_good_badcase
女巫毒好人应识别 critical。
test_seer_info_conversion_highlight
预言家查杀公开并推动狼人出局，应识别高光。
```

### 32.5 证据链测试

```text
test_evidence_required
没有 evidence_event_ids 的结论不能进入报告。
```

### 32.6 反事实测试

```text
test_vote_flip_exact
改一票后出局对象改变，应生成 exact_recalculation。
test_info_release_estimated
信息释放反事实必须是 estimated，不能写成必然。
```

### 32.7 Valid Agent 测试

```text
test_fact_consistency_gate
报告引用不存在投票，校验失败。
test_score_consistency_gate
Markdown 分数和 JSON 不一致，校验失败。
test_counterfactual_soundness_gate
estimated 反事实写成确定性，校验失败。
test_repair_loop
第一轮报告缺证据，调用工具修复后第二轮通过。
```

------

## 33. 完整执行顺序

### Step 1：ReplayBundle 稳定

目标：一局游戏结束后能导出完整 replay。

验收：

```text
replay 中包含 players、events、decisions、votes、final_state。
```

------

### Step 2：实现基础多维评分

实现：

```text
RuleOutcomeScore
RoleTaskScore
RobustnessScore
```

验收：

```text
每个玩家都有基础分和角色任务分。
```

------

### Step 3：实现 SpeechActAnalyzer

实现：

```text
claims
stance
grounded_event_ids
fabrication_risk
private_info_leak_risk
```

验收：

```text
每条 SPEECH 都能生成 SpeechAct。
```

------

### Step 4：实现 SuspicionMatrix

实现：

```text
投票更新；
发言立场更新；
公开查杀更新；
翻牌回溯更新。
```

验收：

```text
每个 day/phase 能输出公共怀疑度。
```

------

### Step 5：实现 BadCase / Highlight

实现：

```text
至少 10 类 BadCase；
至少 7 类 Highlight。
```

验收：

```text
构造明显失误局，系统能定位失误。
```

------

### Step 6：实现 EvidenceBuilder

验收：

```text
所有结论都有 evidence_event_ids。
```

------

### Step 7：实现 CounterfactualAnalyzer

实现：

```text
vote_flip exact；
skill_swap local；
info_release estimated。
```

验收：

```text
报告中能出现至少一条反事实。
```

------

### Step 8：实现 ReviewReportBuilder

输出：

```text
review.json
review.md
```

------

### Step 9：实现 ValidAgent

实现九个 Gate。

验收：

```text
故意构造错误报告，ValidAgent 能拦截。
```

------

### Step 10：实现 RepairLoop

验收：

```text
缺证据报告 → 修复 → 再校验 → 通过。
```

------

### Step 11：实现 API / 前端展示

验收：

```text
前端能看到评分、证据、反事实、校验状态。
```

------

### Step 12：实现 Leaderboard

验收：

```text
可以按 role、persona、model、version 聚合多局表现。
```

------

## 34. 最终验收标准

Track B 完成标准：

```text
1. 一局结束后自动生成 ReviewReport；
2. 每个玩家有 FinalScore 和完整分项；
3. 发言有 SpeechAct 分析；
4. 有公共 SuspicionMatrix；
5. 能识别关键 BadCase；
6. 能识别关键 Highlight；
7. 每个结论都有 evidence_event_ids；
8. 能生成 vote_flip / skill_swap / info_release 反事实；
9. ReportAgent 能生成 Markdown；
10. ValidAgent 能校验事实、证据、分数、反事实和信息隔离；
11. 不通过时能进入 RepairLoop；
12. 通过后才能发布；
13. 前端能展示复盘和校验状态；
14. Leaderboard 能跨局聚合。
```

------

## 35. 答辩说明

可以这样讲：

```text
我们的 Track B 不是简单让大模型打分，而是构建了一个证据驱动的混合评测系统。

系统首先基于结构化 ReplayBundle 进行多维评分，包括规则结果、角色任务、怀疑度决策、发言语义、局部反事实影响和鲁棒性指标。

发言部分不会让大模型直接给分，而是抽取 claims、stance、grounded events、fabrication risk 和 private information leak risk，再由规则计算分数。

同时系统维护公共 SuspicionMatrix，用来判断一个投票或技能动作在当时信息条件下是否合理。

复盘部分会自动识别 BadCase 和 Highlight，并为每个结论绑定 evidence_event_ids。

反事实部分分成三类：投票反事实做精确票型重算，技能反事实做局部结果重算，信息释放反事实基于怀疑度进行估计。

最后，我们引入 Valid Agent 作为报告质量门。它不会重新打分，而是检查报告中的事实、证据、分数、反事实边界和信息隔离是否合法。如果报告不通过，就会返回结构化问题并触发 RepairLoop 调用工具修复。只有通过 Valid Agent 的复盘报告才会被发布。
```

这就是完整的 B：

```text
评分有依据；
复盘有证据；
反事实有边界；
报告有验证；
结果能对比。
```