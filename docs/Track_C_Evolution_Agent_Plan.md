# AI 狼人杀 Track C：自进化 Agent 完整实现方案

> 本文基于 Track B「评测 + 复盘 + Valid 校验」的输出，设计 Track C「自进化 Agent」的完整工程方案。  
> 核心目标：让 Agent 在多局迭代中持续提升，而不是只做一次性复盘。

---

## 0. 先定结论

Track C 不应该做成：

```text
Agent 自己改代码
Agent 自己改游戏规则
Agent 直接训练模型权重
每一步都生成一个新 Prompt
让大模型凭感觉说自己进化了
```

Track C 应该做成：

```text
对局
→ B 路径评测复盘
→ Valid Agent 审核通过
→ 从复盘中抽象策略知识
→ 写入角色策略知识库
→ 下一局角色 Agent 检索使用
→ 多局聚合后生成 Strategy Patch
→ 固定 seed A/B 对战验证
→ 提升则晋升版本，否则回滚
```

一句话：

> **B 是反馈函数，C 是基于反馈函数的策略记忆与版本进化系统。**

---

## 1. Track C 的目标

课题 C 的要求是：

```text
Agent 能否在多局迭代中持续提升胜率？
自动“对局 → 分析 → 调整 → 再对局”闭环；
策略适应性；
A/B 对战验证；
版本回溯；
终局 Agent 与初始 Agent 对战 20 局，胜率显著提升。
```

因此，Track C 必须产出：

```text
1. 策略知识库；
2. 角色策略版本；
3. 策略补丁；
4. 自动进化流程；
5. A/B 对战实验；
6. 版本晋升和回滚；
7. 可解释的进化记录；
8. Leaderboard 对比。
```

最终要能回答：

```text
1. Agent 从哪些局里学到了什么？
2. 学到的经验是否是抽象玩法，而不是泄露历史身份？
3. 新策略改了什么？
4. 为什么改？
5. 改完是否真的提升？
6. 如果没提升，是否能回滚？
```

---

## 2. C 与 B 的边界

### 2.1 B 负责什么

B 负责：

```text
评分；
复盘；
Bad Case；
Highlight；
Evidence；
Counterfactual；
ReviewReport；
ValidAgent 校验。
```

B 的输出是：

```text
ApprovedReviewReport
```

注意，只有通过 Valid Agent 的报告才能进入 C。

### 2.2 C 负责什么

C 负责：

```text
从 ApprovedReviewReport 中抽象策略知识；
把策略知识写入知识库；
让 Agent 在后续对局中检索相关经验；
聚合多局复盘生成策略补丁；
用 A/B 对战验证补丁；
通过后晋升新版本；
失败后回滚。
```

### 2.3 为什么必须先 B 后 C

如果没有 B，C 的进化就是玄学：

```text
没有评分，不知道谁表现好；
没有 Bad Case，不知道哪里错；
没有 Evidence，不知道结论是否可信；
没有 Counterfactual，不知道替代动作是否可能更好；
没有 Valid Agent，不知道复盘报告是否可靠。
```

所以 C 的第一条硬规则是：

```text
只消费 ApprovedReviewReport，不消费 DraftReport 或 FailedReport。
```

---

## 3. 进化对象到底是什么？

你现在系统里有两类模板：

```text
1. Persona / MBTI 人格模板；
2. Role / 身份角色模板，例如狼人、预言家、女巫、猎人、村民。
```

Track C 的关键是：**不要进化错对象。**

---

## 4. 三层 Agent 结构

Agent 应拆成三层：

```text
PersonaStyle：人格表达层
RoleStrategy：角色策略层
PersonaRoleAdapter：人格-角色适配层
```

### 4.1 PersonaStyle：稳定层

PersonaStyle 包括：

```text
MBTI；
姓名；
年龄；
背景；
说话风格；
推理方式；
社交习惯；
压力反应；
怀疑阈值；
逻辑深度；
桌面存在感。
```

这一层原则上不进化。

原因：

```text
1. 保持人物一致性；
2. 保持观战体验；
3. 避免一局之后 INTJ 变 ENFP 这种人设漂移；
4. 让同一人格在不同版本中仍然可对比。
```

允许微调的不是 MBTI 本体，而是该人格在某个角色下的补偿提醒。

---

### 4.2 RoleStrategy：主进化层

RoleStrategy 是主要进化对象。

它描述：

```text
某个身份在不同阶段如何赢。
```

例如预言家的 RoleStrategy：

```text
查验策略；
跳身份策略；
查杀释放策略；
金水保护策略；
归票策略；
被抗推时的应对策略。
```

狼人 RoleStrategy：

```text
夜晚刀口策略；
白天伪装策略；
队友保护策略；
卖队友策略；
抱团投票风险控制；
抗推时反打策略。
```

这层是 C 的核心。

---

### 4.3 PersonaRoleAdapter：副进化层

PersonaRoleAdapter 描述：

```text
某种人格玩某个角色时，应该补偿哪些倾向。
```

例如：

```text
INTJ + Seer：
容易过度分析、过度隐藏信息。
补偿策略：查到狼且好人被集火时，减少隐藏倾向，明确公开查杀。

ESTP + Werewolf：
容易过早强推，暴露攻击性。
补偿策略：首日没有强证据时，采用轻踩 + 观察票型，不要直接强打。

ENFJ + Witch：
容易心软，毒药犹豫。
补偿策略：当目标公共怀疑度高且连续票型异常时，允许更果断使用毒药。
```

这一层适合进化，但频率应该低于 RoleStrategy。

---

## 5. 不同层级的进化频率

```text
PersonaStyle：基本不变；
RoleStrategy：主要进化对象，多局后可改；
PersonaRoleAdapter：当同人格+同角色反复出现同类问题时才改；
StrategyKnowledgeDoc：每局复盘都可以新增 candidate；
StrategyPatch：多局聚合后才生成；
StrategyVersion：A/B 通过后才晋升。
```

一句话：

> **每一步只检索策略知识，不生成 patch；每局可以沉淀知识；多局后才生成策略 patch。**

---

## 6. C 总体架构

```text
ApprovedReviewReport
  ↓
StrategyKnowledgeExtractor
  ↓
Sanitizer / Abstractor
  ↓
StrategyKnowledgeStore
  ↓
HybridRetriever / GraphRAG-lite
  ↓
RoleAgent Retrieval Context
  ↓
Game Run With Retrieved Lessons
  ↓
DreamJob / Multi-Game Aggregation
  ↓
StrategyPatchGenerator
  ↓
PatchValidator
  ↓
VersionManager
  ↓
TournamentRunner
  ↓
AcceptancePolicy
  ↓
Promote / Rollback
```

---

## 7. C 的核心闭环

完整闭环如下：

```text
1. Run Games
   运行一批对局。

2. Track B Review
   每局生成 ApprovedReviewReport。

3. Knowledge Extraction
   从高光、失误、反事实、建议中抽象 StrategyKnowledgeDoc。

4. Knowledge Indexing
   写入策略知识库，建立 role / phase / tactic / failure mode / metric 的关系。

5. Retrieval-Enhanced Agent
   下一局 Agent 根据当前角色、阶段、局势检索 top-k 策略知识。

6. DreamJob
   多局后聚合知识和复盘，发现重复失败模式与稳定高光模式。

7. Patch Generation
   生成 RoleStrategyPatch 或 PersonaRoleAdapterPatch。

8. Patch Validation
   检查是否违反规则、信息隔离、角色权限、修改范围。

9. A/B Tournament
   固定 seed，让 baseline 与 candidate 对战 20 局。

10. Acceptance
   满足提升条件则 promote，否则 rollback。
```

---

## 8. StrategyKnowledgeDoc：策略知识条目

### 8.1 设计目的

StrategyKnowledgeDoc 是 C 的基础。

它不是原始日志，不是完整复盘报告，而是从复盘中抽象出的“玩法知识”。

它应该像狼人杀版 LLM-Wiki / Skill：

```text
在什么局势下；
什么角色；
应该做什么；
不要做什么；
为什么；
证据来自哪些局；
可信度多少。
```

---

### 8.2 Schema

```python
class StrategyKnowledgeDoc:
    doc_id: str
    doc_type: str
    # good_play / bad_case_lesson / counterfactual_lesson / accepted_patch

    role: str
    phase: str
    persona_scope: str | None
    # None 表示所有人格适用；
    # INTJ / ESTP / ENFJ 表示仅适用于某类人格；
    # INTJ+Seer 表示人格-角色适配知识。

    situation_pattern: str
    trigger_conditions: list[str]

    recommended_action: str
    avoid_action: str | None

    rationale: str
    evidence_summary: str

    source_report_ids: list[str]
    source_item_ids: list[str]
    source_event_ids: list[str]
    counterfactual_ids: list[str]

    expected_metric_effects: list[dict]
    # 例如 info_conversion 增加、misvote_rate 下降

    quality_score: float
    confidence: float

    usage_count: int
    success_count: int
    failure_count: int

    status: str
    # candidate / active / deprecated / superseded

    tags: list[str]
    created_at: str
    updated_at: str
```

---

### 8.3 示例：预言家 Bad Case 知识

```json
{
  "doc_type": "bad_case_lesson",
  "role": "seer",
  "phase": "DAY_SPEECH",
  "persona_scope": null,
  "situation_pattern": "预言家已查到狼人，且白天有好人被集火",
  "trigger_conditions": [
    "has_wolf_check=true",
    "good_player_under_pressure=true",
    "wolf_target_not_publicly_exposed=true"
  ],
  "recommended_action": "公开查杀目标，并给出明确归票建议",
  "avoid_action": "继续模糊发言或只说还要观察",
  "rationale": "复盘显示，查杀信息不释放会导致好人阵营无法形成公共共识，增加误投概率。",
  "evidence_summary": "多局复盘中，预言家查到狼但未公开，后续均出现好人误投或查验信息沉没。",
  "expected_metric_effects": [
    {"metric": "seer_info_conversion", "direction": "increase"},
    {"metric": "good_misvote_rate", "direction": "decrease"}
  ],
  "quality_score": 0.91,
  "confidence": 0.86,
  "status": "candidate",
  "tags": ["seer", "info_release", "vote_guidance", "bad_case"]
}
```

---

### 8.4 示例：狼人 Good Play 知识

```json
{
  "doc_type": "good_play",
  "role": "werewolf",
  "phase": "DAY_SPEECH",
  "persona_scope": null,
  "situation_pattern": "狼队友被轻度怀疑，但场上还没有强证据",
  "trigger_conditions": [
    "teammate_under_light_pressure=true",
    "no_confirmed_wolf_check=true",
    "public_suspicion_spread=true"
  ],
  "recommended_action": "弱保护队友，同时给出基于公开事实的替代怀疑目标",
  "avoid_action": "无脑强保队友或连续抱团投票",
  "rationale": "弱保护可以降低队友压力，同时避免狼队投票轨迹过于一致。",
  "expected_metric_effects": [
    {"metric": "wolf_exposure_risk", "direction": "decrease"},
    {"metric": "vote_manipulation", "direction": "increase"}
  ],
  "quality_score": 0.84,
  "confidence": 0.78,
  "status": "candidate",
  "tags": ["werewolf", "team_coordination", "deception"]
}
```

---

## 9. Knowledge Extraction：从 B 报告抽象知识

### 9.1 输入

只允许输入：

```text
ApprovedReviewReport
```

不允许输入：

```text
DraftReport；
RejectedReport；
未通过 Valid Agent 的报告；
原始私有日志。
```

---

### 9.2 转换规则

```text
Highlight → good_play
BadCase → bad_case_lesson
CounterfactualCase → counterfactual_lesson
Repeated Weak Metric → weakness_lesson
Promoted StrategyPatch → accepted_patch
```

---

### 9.3 伪代码

```python
def extract_knowledge_from_report(report):
    docs = []

    for highlight in report.highlights:
        docs.append(make_good_play_doc(highlight, report))

    for bad_case in report.bad_cases:
        docs.append(make_bad_case_lesson_doc(bad_case, report))

    for cf in report.counterfactuals:
        docs.append(make_counterfactual_lesson_doc(cf, report))

    for weakness in detect_score_weaknesses(report.scoreboard):
        docs.append(make_weakness_lesson_doc(weakness, report))

    docs = [sanitize_doc(doc) for doc in docs]
    docs = [abstract_doc(doc) for doc in docs]
    docs = [score_doc_quality(doc) for doc in docs]

    return docs
```

---

## 10. Sanitizer：知识脱敏与抽象

### 10.1 为什么需要 Sanitizer

如果直接把复盘内容写进知识库，会出现严重问题：

```text
历史局 P5 是狼人 → 下一局 P5 也可疑
某个玩家使用过女巫毒药 → 未来局泄露身份
某局狼人队友是谁 → 未来局被错误引用
```

所以知识库只能存“抽象玩法”，不能存“具体历史身份依赖”。

---

### 10.2 Sanitizer 规则

必须删除或替换：

```text
具体玩家编号；
具体座位依赖；
具体历史隐藏身份；
未公开私有信息细节；
private_reason；
只能在主持人视角知道的事实。
```

保留：

```text
角色；
阶段；
局势模式；
触发条件；
推荐动作；
避免动作；
证据摘要；
指标影响；
可信度。
```

---

### 10.3 伪代码

```python
def sanitize_doc(doc):
    doc.situation_pattern = replace_player_ids_with_roles(doc.situation_pattern)
    doc.recommended_action = remove_specific_player_reference(doc.recommended_action)
    doc.avoid_action = remove_specific_player_reference(doc.avoid_action)

    doc.evidence_summary = abstract_evidence(doc.evidence_summary)
    doc.source_event_ids = keep_for_audit_only(doc.source_event_ids)

    assert not contains_hidden_identity_leak(doc)
    assert not contains_specific_seat_dependency(doc)

    return doc
```

---

## 11. Knowledge Quality Score：知识质量评分

每条知识必须有质量分。

### 11.1 公式

```text
quality_score =
  0.30 * evidence_strength
+ 0.20 * counterfactual_support
+ 0.20 * repeatability
+ 0.15 * metric_relevance
+ 0.10 * validation_confidence
+ 0.05 * recency
```

### 11.2 各项解释

```text
evidence_strength：
证据链数量和质量。

counterfactual_support：
是否有局部反事实支持。

repeatability：
是否在多局中重复出现。

metric_relevance：
是否影响关键指标，如胜率、角色任务分、失误率。

validation_confidence：
B 报告 Valid Agent 校验分。

recency：
较新的策略略微加权。
```

### 11.3 伪代码

```python
def score_knowledge_doc(doc, reports):
    evidence_strength = min(1.0, len(doc.source_event_ids) / 3)
    cf_support = 1.0 if doc.counterfactual_ids else 0.3
    repeatability = count_similar_docs(doc) / max_required_repeats
    metric_relevance = estimate_metric_relevance(doc.expected_metric_effects)
    validation_confidence = avg_report_validation_score(doc.source_report_ids)
    recency = compute_recency(doc.created_at)

    return (
        0.30 * evidence_strength +
        0.20 * cf_support +
        0.20 * repeatability +
        0.15 * metric_relevance +
        0.10 * validation_confidence +
        0.05 * recency
    )
```

---

## 12. Strategy Knowledge Store：策略知识库

### 12.1 第一版不做完整 GraphRAG

第一版做 GraphRAG-lite。

原因：

```text
完整 GraphRAG 成本高；
21 天个人开发周期不适合重型图谱；
策略知识条目数量前期不会很大；
先用轻量图 + 混合检索足够。
```

---

### 12.2 节点类型

```text
Role
Phase
Persona
SituationPattern
Tactic
FailureMode
Metric
KnowledgeDoc
StrategyPatch
```

---

### 12.3 边类型

```text
applicable_to：知识适用于某角色/阶段；
mitigates：策略缓解某失败模式；
causes：失败模式导致某结果；
supports：证据支持某策略；
supersedes：新策略替代旧策略；
improves_metric：策略提升某指标；
conflicts_with：策略之间存在冲突。
```

---

### 12.4 检索输入

每次 Agent 决策前，构造检索 query：

```python
class StrategyRetrievalQuery:
    role: str
    phase: str
    persona_mbti: str | None
    persona_style: str | None

    observation_summary: str
    situation_tags: list[str]
    private_role_state_summary: str | None

    legal_action_types: list[str]
    top_k: int = 3
```

注意：

```text
private_role_state_summary 只能包含当前 Agent 合法可见的私有信息；
不能包含上帝视角；
不能包含其他玩家隐藏身份。
```

---

### 12.5 检索打分

```text
retrieval_score =
  0.30 * role_match
+ 0.20 * phase_match
+ 0.20 * situation_similarity
+ 0.10 * persona_adapter_match
+ 0.10 * quality_score
+ 0.05 * recency
+ 0.05 * usage_success_rate
```

### 12.6 伪代码

```python
def retrieve_strategy_knowledge(query):
    candidates = search_by_role_phase(query.role, query.phase)

    scored = []
    for doc in candidates:
        score = 0
        score += 0.30 * exact_match(doc.role, query.role)
        score += 0.20 * exact_match(doc.phase, query.phase)
        score += 0.20 * text_similarity(doc.situation_pattern, query.observation_summary)
        score += 0.10 * persona_match(doc.persona_scope, query.persona_mbti)
        score += 0.10 * doc.quality_score
        score += 0.05 * recency_score(doc)
        score += 0.05 * usage_success_rate(doc)

        scored.append((score, doc))

    return top_k(scored, query.top_k)
```

---

## 13. Agent 如何使用知识

### 13.1 每一步 Agent 做什么

每一步只做：

```text
构造 observation；
生成 situation tags；
检索 top-k StrategyKnowledgeDoc；
拼入 prompt；
生成动作；
ActionValidator 校验；
记录 retrieved_knowledge_ids。
```

每一步不生成 StrategyPatch。

---

### 13.2 Prompt 结构

```text
[Hard Rules]
你只能使用当前 observation 中的信息；
不能使用历史局具体身份；
不能违反角色合法动作；
最终动作必须来自 legal_actions。

[Role Strategy]
当前角色的基础策略。

[Persona Style]
当前人格的说话风格和行为倾向。

[Persona-Role Adapter]
该人格玩当前角色时需要注意的补偿策略。

[Retrieved Lessons]
1. ...
2. ...
3. ...

[Current Observation]
...

[Legal Actions]
...

[Output Schema]
...
```

---

### 13.3 决策记录

AgentDecision 必须记录：

```text
retrieved_knowledge_ids；
retrieval_query_summary；
retrieval_used；
selected_action；
reason；
```

这样后续 B 可以评估：

```text
这条知识是否被用到；
用了之后是否改善表现；
知识是否需要降权或废弃。
```

---

## 14. StrategyCard：角色策略版本

### 14.1 RoleStrategyCard

```python
class RoleStrategyCard:
    role: str
    version: str
    parent_version: str | None

    goal: str

    speech_policy: list[str]
    vote_policy: list[str]
    skill_policy: list[str]
    risk_rules: list[str]
    retrieval_policy: dict

    status: str
    # active / candidate / deprecated

    created_from_patch_id: str | None
```

---

### 14.2 PersonaRoleAdapter

```python
class PersonaRoleAdapter:
    adapter_id: str
    persona_scope: str
    role: str
    version: str

    compensation_rules: list[str]
    risk_warnings: list[str]
    style_adjustments: list[str]

    status: str
```

示例：

```json
{
  "persona_scope": "INTJ",
  "role": "seer",
  "compensation_rules": [
    "当已经查到狼人，且白天好人被明显集火时，不要因过度隐藏而错失信息释放窗口。",
    "如果自己成为抗推焦点，应优先公开关键查验信息。"
  ],
  "risk_warnings": [
    "避免因为追求完整逻辑链而延迟公开查杀。"
  ]
}
```

---

## 15. DreamJob：多局离线整理

DreamJob 是 C 的核心调度任务。

### 15.1 输入

```text
最近 N 局 ApprovedReviewReport；
当前 active StrategyKnowledgeDoc；
当前 active RoleStrategyCard；
当前 active PersonaRoleAdapter；
Leaderboard 指标。
```

---

### 15.2 输出

```text
新增 StrategyKnowledgeDoc；
待验证 StrategyPatch；
知识降权/废弃建议；
进化摘要 DreamSummary。
```

---

### 15.3 DreamJob 流程

```text
1. 收集最近 N 局 ApprovedReviewReport；
2. 聚合同类 BadCase；
3. 聚合同类 Highlight；
4. 聚合反事实结论；
5. 抽象成 StrategyKnowledgeDoc；
6. 去重、合并、打分；
7. 发现重复弱点；
8. 生成 StrategyPatch；
9. 通过 PatchValidator；
10. 标记为 candidate；
11. 等待 A/B 验证。
```

---

### 15.4 伪代码

```python
def run_dream_job(report_ids):
    reports = load_approved_reports(report_ids)

    docs = []
    for report in reports:
        docs.extend(extract_knowledge_from_report(report))

    docs = [sanitize_doc(d) for d in docs]
    docs = merge_similar_docs(docs)
    docs = score_docs(docs)

    saved_docs = knowledge_store.upsert_many(docs)

    weakness_clusters = cluster_repeated_weaknesses(reports, saved_docs)
    patches = []

    for cluster in weakness_clusters:
        patch = propose_patch_from_cluster(cluster)
        validation = validate_patch(patch)
        if validation.passed:
            patches.append(save_candidate_patch(patch))

    return DreamResult(
        knowledge_docs=saved_docs,
        candidate_patches=patches,
        summary=build_dream_summary(saved_docs, patches),
    )
```

---

## 16. StrategyPatch：策略补丁

### 16.1 Patch 类型

```text
RoleStrategyPatch：
修改某角色通用策略。

PersonaRoleAdapterPatch：
修改某人格+角色组合的补偿策略。

RetrievalPolicyPatch：
修改某角色检索知识的 top_k、权重、过滤规则。

KnowledgeStatusPatch：
将某些知识从 candidate 晋升 active，或 deprecated。
```

---

### 16.2 StrategyPatch Schema

```python
class StrategyPatch:
    patch_id: str
    patch_type: str
    # role_strategy / persona_role_adapter / retrieval_policy / knowledge_status

    target_role: str | None
    target_persona_scope: str | None

    from_version: str
    to_version: str

    source_report_ids: list[str]
    source_knowledge_doc_ids: list[str]
    source_evidence_ids: list[str]

    operations: list[PatchOperation]
    expected_effects: list[dict]

    safety_checks: dict
    status: str
    # proposed / validated / applied / promoted / rejected / rolled_back
```

---

### 16.3 PatchOperation

```python
class PatchOperation:
    op: str
    # add / update / remove / deprecate / promote

    section: str
    # speech_policy / vote_policy / skill_policy / risk_rules / compensation_rules / retrieval_policy

    old_value: str | None
    new_value: str

    rationale: str
```

---

### 16.4 示例：预言家策略补丁

```json
{
  "patch_type": "role_strategy",
  "target_role": "seer",
  "from_version": "seer_v1",
  "to_version": "seer_v2_candidate",
  "operations": [
    {
      "op": "add",
      "section": "speech_policy",
      "new_value": "如果已经查到狼人，且当天已有好人被明显集火，应公开查杀并给出归票建议。",
      "rationale": "多局复盘显示，查杀信息不释放会造成好人误投。"
    }
  ],
  "expected_effects": [
    {"metric": "seer_info_conversion", "direction": "increase"},
    {"metric": "good_misvote_rate", "direction": "decrease"}
  ]
}
```

---

## 17. PatchValidator：补丁合法性校验

StrategyPatch 必须经过安全校验。

### 17.1 校验项

```text
1. 不允许修改游戏规则；
2. 不允许修改角色权限；
3. 不允许绕过信息隔离；
4. 不允许要求读取真实隐藏身份；
5. 不允许针对历史具体玩家或座位；
6. 每次最多修改 1~3 条策略；
7. 必须有 ApprovedReviewReport 支撑；
8. 必须有 Evidence 或 KnowledgeDoc 支撑；
9. 不能和 active 策略发生严重冲突；
10. 不能引入过于绝对的策略，例如“永远跳身份”。
```

---

### 17.2 伪代码

```python
def validate_patch(patch):
    issues = []

    if modifies_game_rule(patch):
        issues.append(critical("Patch 试图修改游戏规则"))

    if modifies_visibility(patch):
        issues.append(critical("Patch 试图绕过信息隔离"))

    if contains_specific_player_reference(patch):
        issues.append(major("Patch 包含历史具体玩家依赖"))

    if len(patch.operations) > 3:
        issues.append(major("单次 Patch 修改过多"))

    if not patch.source_knowledge_doc_ids:
        issues.append(critical("Patch 缺少知识来源"))

    if has_absolute_instruction(patch):
        issues.append(major("Patch 包含过度绝对策略"))

    return PatchValidationResult(
        passed=not any(i.severity == "critical" for i in issues),
        issues=issues
    )
```

---

## 18. VersionManager：版本管理

### 18.1 版本状态

```text
active：当前正式使用；
candidate：候选版本；
promoted：通过 A/B 后晋升；
rejected：验证失败；
rolled_back：曾经上线但回滚；
deprecated：废弃。
```

### 18.2 版本流转

```text
v1 active
  ↓ apply patch
v2_candidate
  ↓ A/B pass
v2 active / promoted

或：

v2_candidate
  ↓ A/B fail
rejected
  ↓ keep v1 active
```

---

## 19. TournamentRunner：A/B 对战

### 19.1 为什么必须 A/B

C 的评分标准要求：

```text
终局 Agent 与初始 Agent 对战 20 局，胜率显著提升。
```

所以不能只说“策略更合理”，必须跑实验。

---

### 19.2 实验设置

```text
baseline：旧版本；
candidate：新版本；
board：固定板子；
seeds：固定 20 个；
seat_policy：镜像座位或轮换座位；
agents：除目标版本外其他条件尽量一致；
```

### 19.3 指标

```text
camp_win_rate；
target_role_avg_score；
role_task_score；
critical_mistakes_per_game；
vote_accuracy；
skill_accuracy；
info_leak_count；
invalid_action_rate；
retrieval_used_rate；
knowledge_hit_rate；
```

---

### 19.4 接受条件

硬条件：

```text
info_leak_count == 0；
invalid_action_rate == 0。
```

提升条件，满足至少两项：

```text
target_role_avg_score 提升 >= 3%；
critical_mistakes_per_game 下降 >= 10%；
role_task_score 提升 >= 3%；
camp_win_rate 不下降超过 5%；
```

如果想更严格，可以要求：

```text
candidate 在 20 局中的综合分均值 > baseline；
且没有新增 critical 类风险。
```

---

### 19.5 伪代码

```python
def run_ab_tournament(baseline_version, candidate_version, seeds):
    baseline_results = []
    candidate_results = []

    for seed in seeds:
        baseline_game = run_game(strategy_version=baseline_version, seed=seed)
        candidate_game = run_game(strategy_version=candidate_version, seed=seed)

        baseline_review = run_track_b_review(baseline_game)
        candidate_review = run_track_b_review(candidate_game)

        baseline_results.append(extract_metrics(baseline_review))
        candidate_results.append(extract_metrics(candidate_review))

    comparison = compare_results(baseline_results, candidate_results)
    decision = acceptance_policy(comparison)

    if decision.accept:
        promote(candidate_version)
    else:
        rollback(candidate_version)

    return comparison
```

---

## 20. Knowledge Usage Feedback：知识使用反馈

每次 Agent 检索知识后，要记录：

```text
retrieved_doc_ids；
used_doc_ids；
decision_outcome；
score_delta；
whether_helpful；
```

### 20.1 为什么

知识库不是越大越好。  
有些知识可能误导 Agent，需要降权或废弃。

### 20.2 更新规则

```text
如果某条知识被使用后，相关指标提升 → success_count +1；
如果使用后导致 BadCase → failure_count +1；
如果多次失败 → status = deprecated；
如果多次成功 → status = active 或提高 quality_score。
```

### 20.3 伪代码

```python
def update_knowledge_usage(decision, review):
    for doc_id in decision.retrieved_knowledge_ids:
        doc = knowledge_store.get(doc_id)

        if decision_led_to_highlight(decision, review):
            doc.success_count += 1

        if decision_led_to_badcase(decision, review):
            doc.failure_count += 1

        doc.quality_score = recompute_quality(doc)

        if doc.failure_count >= 3 and doc.success_count == 0:
            doc.status = "deprecated"

        knowledge_store.update(doc)
```

---

## 21. C 的 Valid Gates

Track C 也需要校验，但校验对象不是报告，而是：

```text
KnowledgeDoc；
StrategyPatch；
A/B Experiment；
Version Promotion。
```

### 21.1 KnowledgeDoc Valid Gate

检查：

```text
是否来自 ApprovedReviewReport；
是否去除了具体玩家依赖；
是否没有隐藏身份泄露；
是否有 evidence；
是否有 quality_score；
是否有 trigger_conditions。
```

### 21.2 Patch Valid Gate

检查：

```text
是否修改了合法策略字段；
是否有证据来源；
是否不修改规则；
是否不绕过信息隔离；
是否不包含绝对策略；
是否修改范围可控。
```

### 21.3 Promotion Valid Gate

检查：

```text
A/B 是否跑满 20 局；
是否满足硬条件；
是否满足提升条件；
是否没有新增 critical 风险；
是否保存可回滚版本。
```

---

## 22. C 的前端展示

### 22.1 Evolution Dashboard

展示：

```text
当前 active 版本；
candidate 版本；
patch diff；
patch 来源证据；
patch 校验结果；
A/B 实验结果；
promote / rollback 状态。
```

### 22.2 Knowledge Wiki

展示：

```text
按角色查看玩法知识；
按阶段查看策略；
查看某条知识来源于哪些复盘；
查看使用次数、成功次数、失败次数；
查看 active / candidate / deprecated 状态。
```

### 22.3 Version Leaderboard

展示：

```text
版本；
局数；
胜率；
平均总分；
角色任务分；
关键失误率；
信息泄露次数；
非法动作率；
是否晋升。
```

---

## 23. C 实现阶段计划

### 阶段 C1：复盘转知识

目标：

```text
ApprovedReviewReport → StrategyKnowledgeDoc
```

验收：

```text
一份通过 Valid 的复盘报告，可以抽出 good_play、bad_case_lesson、counterfactual_lesson。
```

---

### 阶段 C2：策略知识库

目标：

```text
StrategyKnowledgeDoc 可存储、检索、降权、废弃。
```

验收：

```text
按 role + phase + situation 能检索 top-k 策略知识。
```

---

### 阶段 C3：Agent 检索增强

目标：

```text
Agent 决策前能检索相关策略知识，并记录 retrieved_doc_ids。
```

验收：

```text
AgentDecision 中能看到本步使用了哪些策略知识。
```

---

### 阶段 C4：DreamJob

目标：

```text
多局复盘 → 聚合弱点 → 生成 candidate patch。
```

验收：

```text
最近 N 局预言家多次查杀沉没，系统能生成 seer_v2_candidate patch。
```

---

### 阶段 C5：PatchValidator + VersionManager

目标：

```text
Patch 可校验、可应用、可回滚。
```

验收：

```text
非法 patch 被拒绝；
合法 patch 生成 candidate version。
```

---

### 阶段 C6：A/B Tournament

目标：

```text
候选版本与基线版本固定 20 局对战。
```

验收：

```text
输出 comparison summary；
满足条件 promote；
不满足 rollback。
```

---

## 24. 最终 C Pipeline

```text
1. run_games(batch_id)
2. run_B_review_for_each_game()
3. filter approved reports
4. extract_strategy_knowledge()
5. index_knowledge()
6. run_games_with_retrieval()
7. dream_job_aggregate()
8. propose_strategy_patch()
9. validate_patch()
10. create_candidate_version()
11. run_ab_tournament_20_games()
12. acceptance_policy()
13. promote_or_rollback()
14. update_leaderboard()
```

---

## 25. 最终验收标准

Track C 完成标准：

```text
1. 能从 B 的 ApprovedReviewReport 中抽象策略知识；
2. 知识条目去除了具体历史玩家依赖；
3. 知识库支持按角色、阶段、局势检索；
4. Agent 每步能检索 top-k 策略知识；
5. AgentDecision 记录 retrieved_doc_ids；
6. 多局后 DreamJob 能聚合重复失误和高光；
7. 系统能生成 StrategyPatch；
8. PatchValidator 能拒绝非法 patch；
9. VersionManager 能创建 candidate 版本；
10. TournamentRunner 能跑固定 seed 20 局 A/B；
11. AcceptancePolicy 能 promote 或 rollback；
12. Leaderboard 能展示 v1 vs v2 差异；
13. 所有进化记录可追溯到 B 的报告和证据链。
```

---

## 26. 给本地 Agent 的执行指令

```text
当前任务：实现 Track C 自进化 Agent。前提是 Track B 已经能生成 ApprovedReviewReport。

请严格按顺序执行：

1. 不要训练模型权重。
2. 不要让 Agent 修改代码。
3. 不要修改游戏规则、角色权限、信息隔离。
4. 不要进化 PersonaStyle 本体，例如 MBTI、姓名、背景、基础语气。
5. 主要进化 RoleStrategyCard。
6. 次要进化 PersonaRoleAdapter。
7. 每一步 Agent 只做知识检索，不生成 StrategyPatch。
8. StrategyPatch 只能在一局结束后或多局 DreamJob 聚合后生成。
9. 所有知识必须来自 ApprovedReviewReport。
10. 所有知识必须经过 sanitize，删除具体历史玩家和隐藏身份依赖。
11. 实现 StrategyKnowledgeDoc。
12. 实现 KnowledgeExtractor：
    - Highlight → good_play
    - BadCase → bad_case_lesson
    - Counterfactual → counterfactual_lesson
13. 实现 KnowledgeStore，支持 upsert/search/deprecate/link。
14. 实现 Agent 决策前检索 top-k StrategyKnowledgeDoc。
15. AgentDecision 记录 retrieved_knowledge_ids。
16. 实现 DreamJob，聚合多局知识，发现重复弱点。
17. 实现 StrategyPatchGenerator。
18. 实现 PatchValidator。
19. 实现 VersionManager。
20. 实现 TournamentRunner，固定 20 个 seed 对比 baseline 与 candidate。
21. 实现 AcceptancePolicy：
    - info_leak_count == 0
    - invalid_action_rate == 0
    - 至少两个核心指标提升
22. 实现 promote / rollback。
23. 实现 Version Leaderboard。
24. 输出 evolution_summary.json。
```

---

## 27. 答辩口径

可以这样讲：

```text
我们的 C 方向不是让 Agent 自己改代码，也不是直接训练模型权重，而是基于 B 的评测复盘结果构建可验证的策略进化闭环。

系统首先只消费通过 Valid Agent 校验的复盘报告，从高光、失误和反事实中抽象出 StrategyKnowledgeDoc。知识条目会去除具体历史玩家和隐藏身份依赖，只保留抽象玩法，例如“预言家查到狼且好人被集火时，应公开查杀并归票”。

下一局 Agent 在决策前，会根据自身角色、阶段和局势检索相关策略知识，作为当前决策上下文的一部分。但每一步不会直接修改策略版本。

当多局复盘发现重复失误或稳定高光时，DreamJob 会生成 StrategyPatch。Patch 只能修改 RoleStrategyCard 或 PersonaRoleAdapter，不能修改游戏规则、角色权限或信息隔离。Patch 通过校验后成为 candidate 版本，并与 baseline 在固定 20 个 seed 下进行 A/B 对战。只有在关键指标提升且没有新增信息泄露和非法动作时，candidate 才会晋升为 active，否则回滚。

因此，整个 C 闭环是可解释、可验证、可回溯的。
```

---

## 28. 与 B 的关系总结

```text
B 给 C 提供：
- 分数；
- BadCase；
- Highlight；
- Evidence；
- Counterfactual；
- Validated ReviewReport。

C 使用 B 的输出：
- 抽象策略知识；
- 检索增强 Agent；
- 生成策略补丁；
- A/B 验证；
- 版本晋升或回滚。
```

最终闭环：

```text
B 让 Agent 知道“错在哪里、为什么错”；
C 让 Agent 把这些教训变成“下一局怎么做”。
```
