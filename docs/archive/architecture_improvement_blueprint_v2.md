# AI Werewolf 架构改进蓝图 v2

> 日期：2026-06-02  
> 基于：`docs/architecture_scoring_review.md`、原 `solution_blueprint.md` 与进一步审阅意见  
> 范围：后端 + 评测 + Agent + 提交证据链；前端 Replay Viewer 单独规划  
> 推荐定位：**主赛道 Track B：评测 + 复盘；加分亮点：可信知识回流驱动的轻量自进化**

---

## 0. v2 相比原 blueprint 的关键变化

本版本不是对原方案的简单补充，而是将进一步审阅中发现的高风险点直接合并到设计中。

### 0.1 已修正的关键问题

| 编号 | 原问题 | v2 修正 |
|---|---|---|
| G5 | 狼队刀人示例使用 `p.role` / `p.alignment`，有偷看真实身份风险 | 改为只使用 `WolfTeamView + PublicGameState + BeliefTracker` 中合法可见信息 |
| G15 | 知识只按 L0-L4 可信度过滤，不足以防泄露或误用 | 新增 `KnowledgeAccessControl` 和 `KnowledgeApplicability`，检索必须同时满足可信度、权限、适用条件 |
| G3 | 只测试 `PlayerView`，不能覆盖 Memory / Retrieval / Prompt 泄露 | 新增 `final_agent_input` 级别信息隔离测试 |
| G7 | 20 个 Golden Cases 容易被误解为强统计证明 | 改为初版 sanity check；正式报告需给 TPR/FPR 置信区间，并逐步扩展到 50-100 条 |
| G8 | 检索指标可能存在占位数字和数据泄漏 | 明确占位数字不得进入正式文档；按 game_id 切分 train/test |
| G9 | 规则边界测试中出现“取决于规则” | 新增 `configs/rule_variant_standard.yaml`，所有测试绑定明确规则配置 |
| G12 | Leaderboard 指标过多，可能阻塞主线 | 第一版压缩到 8 个核心指标，高级统计作为加分项 |
| 研究引用 | 部分外部参考可能未核验 | 正式文档只保留已核验引用；其余放入“待核验” |

### 0.2 v2 的一句话主线

> 我们做了一个 AI 狼人杀多智能体系统，不只会玩，还能复盘每个关键决策，通过反事实评估定位 bad case，并把经过可信度、权限和适用条件过滤的策略知识回流到下一代 Agent。

三个关键词：

```text
玩 Play       = CognitiveAgent + 角色策略 + 狼队协作 + 信息隔离
评 Evaluate  = 三级评分 + 反事实推演 + Judge 校准 + 结构化报告
进化 Evolve  = L0-L4 知识分层 + 权限过滤 + 回验 + A/B Leaderboard
```

---

## 1. 总体目标与评分对齐

### 1.1 主申报方向

推荐主申报：**评测 + 复盘 Track B**。

原因：当前项目最强的模块是 deterministic replay、CounterfactualAnalyzer、PerStepScorer、LLM Judge、PublishedReviewDocument、Leaderboard 和知识回流。这些能力与“多维评测 → 关键决策复盘 → 反事实推演 → 结构化报告 → Leaderboard”最直接匹配。

### 1.2 自进化的定位

自进化不建议主打“通用 Agent 自主改代码”，而应定位为：

> 评测驱动的策略知识迭代。

也就是：

```text
对局 → 复盘 → 可信知识入库 → 检索使用 → A/B 验证 → Leaderboard 对比
```

这样可以展示自进化能力，但不会被“是否实现代码自修改、自动构建测试、失败回滚”卡住。

### 1.3 本文档优先级原则

按比赛拿分和风险大小，v2 优先级如下：

```text
P0：会影响信息隔离、规则正确性、自进化可信度的问题
P1：会直接影响 Agent 评分和演示说服力的问题
P2：可扩展性、工程完整度、长期优化问题
P3：锦上添花，不阻塞核心 demo
```

---

## 2. G1：角色策略深度 —— 从人格包装到策略编码

### 2.1 问题

当前架构已有 MBTI、PersonaTraits、MindTraits，但这些主要是表达风格层。评分更看重角色策略深度：

- 预言家什么时候跳身份；
- 狼人什么时候悍跳、倒钩、冲票；
- 女巫什么时候救人、毒人；
- 猎人什么时候开枪；
- 村民如何归票、站队、识别矛盾。

### 2.2 v2 方案

将 Agent 拆成两层：

```text
Personality Layer：控制“怎么说”
Strategy Layer：控制“做什么”
```

### 2.3 角色策略卡

建议放在：

```text
backend/agents/cognitive/strategies/
```

示例结构：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class RoleStrategyCard:
    """角色策略卡：独立于 MBTI / Persona 的决策层配置。"""

    role: str

    # 信息策略
    claim_policy: str
    info_release_policy: str

    # 投票策略
    vote_leadership_threshold: float
    vote_follow_threshold: float
    split_vote_tolerance: float

    # 技能策略
    skill_conservation: float
    skill_target_priority: list[str]

    # 风险策略
    risk_tolerance: float
    information_seeking: float

    # 对抗策略，仅狼人等阵营使用
    bluff_timing_preference: str | None = None
    sacrifice_threshold: float | None = None
```

### 2.4 避免“参数堆砌”的改进

不要把角色策略卡设计成一堆无法解释的浮点数。建议分成两类：

```text
规则型策略：明确、可解释、稳定
参数型策略：可调、可 A/B、可评测
```

例如预言家策略：

```python
@dataclass
class SeerStrategyCard(RoleStrategyCard):
    reveal_when_checked_wolf: bool = True
    reveal_when_counter_claimed: bool = True
    reveal_when_self_at_risk_threshold: float = 0.65
    keep_badge_flow_private_until_day: int = 2
```

这样比单纯 `risk_tolerance = 0.7` 更容易向评委解释。

### 2.5 策略记忆

```python
@dataclass
class StrategyMemory:
    """跨回合持久化的策略状态。"""

    current_tactic: str
    suspicion_ranking: list[str]
    trusted_allies: list[str]
    exposed_risk: float
    info_debt: list[str]
    last_claim: str | None = None
    stance_history: list[dict] = None
```

### 2.6 实施路径

| 优先级 | 任务 | 文件 |
|---|---|---|
| P1 | 新建 `strategies/` 包 | `backend/agents/cognitive/strategies/` |
| P1 | 每角色定义默认策略卡 | `seer.py`, `wolf.py`, `witch.py`, `hunter.py`, `villager.py` |
| P1 | `StrategyMemory` 集成进 Memory | `backend/agents/cognitive/memory.py` |
| P1 | Think 阶段注入 strategy context | `backend/agents/cognitive/pipeline.py` |

---

## 3. G2：决策可追溯 —— 结构化 DecisionTrace

### 3.1 问题

完整 chain-of-thought 不适合展示，也不适合跨对局统计。需要把每次决策转成结构化记录。

### 3.2 v2 方案

新增结构化 `DecisionTrace`：

```python
@dataclass
class DecisionTrace:
    decision_id: str
    game_id: str
    agent_id: str
    agent_version: str
    prompt_hash: str
    phase: str
    day: int

    visible_facts: list[str]
    visible_facts_source: str  # PlayerView + AllowedMemory + AllowedRetrieval
    visibility_scope_hash: str

    belief_delta: dict
    candidate_actions: list[dict]
    chosen_action: str
    confidence: float
    rationale: str

    retrieved_strategy_ids: list[str]
    active_playbook: str | None
    strategy_memory_snapshot: dict

    model_name: str
    provider: str
    token_in: int
    token_out: int
    latency_ms: int
    cost_usd: float
```

### 3.3 三条硬约束

#### 约束 1：visible_facts 只来自最终合法输入

```text
PlayerView + AllowedMemory + AllowedRetrieval + AllowedTeamView
```

不得从 raw `GameState` 直接拼接。

#### 约束 2：candidate_actions 来自合法行动空间

```python
candidate_actions = ActionValidator.legal_actions(player_view)
```

不能让 LLM 自己凭空生成行动候选。

#### 约束 3：区分内部版与展示版

```python
DecisionTraceInternal  # 调试用，包含更多元数据
DecisionTracePublic    # 展示用，脱敏、去除私有信息和完整 prompt
```

---

## 4. G3：信息隔离 —— 从 PlayerView 测试升级为 final_agent_input 测试

### 4.1 问题

只测试 `Visibility.for_player()` 不够。真正喂给 Agent 的输入是：

```text
PlayerView + Memory + Retrieval + Profile + TeamView + Prompt Template + Tool Outputs
```

任何一层都可能泄露隐藏信息。

### 4.2 信息分层

| 层级 | 内容 | 可见范围 | Agent Memory | Knowledge Store |
|---|---|---|---|---|
| Public | 发言、投票、死亡公告 | 全员 | 是 | 可脱敏 |
| Private Role | 自己身份、技能状态 | 自己 | 是 | 否 |
| Team Private | 狼队名单、夜聊/战术 | 狼队 | 是 | 仅脱敏统计 |
| Hidden Truth | 他人真实身份 | 仅引擎 | 否 | 否 |
| Post-game Truth | 全局真相 | 复盘模块 | 只进评测 | 可脱敏 |

### 4.3 安全属性清单

```text
P1：狼人不能看到预言家查验结果
P2：村民不能看到狼队名单
P3：死亡玩家不能投票
P4：Agent Memory 不包含 Hidden Truth
P5：策略检索不返回当前对局私有信息
P6：复盘反思结果在对局进行中不可见
P7：HumanAgent 合法视角 = AIPlayer 合法视角
P8：知识回流不会把当前局事实泄露给下一局
P9：final_agent_input 不包含当前玩家不可见的身份、技能和赛后真相
P10：retrieved_docs 全部满足 visibility_scope 和 applicability
```

### 4.4 v2 新增 final_agent_input 测试

```python
def test_final_agent_input_contains_no_hidden_truth():
    state = setup_game_with_hidden_roles()
    player = get_player(state, role="Villager")

    player_view = Visibility.for_player(state, player.id)
    memory = Memory.load_allowed(player.id, state.game_id)
    retrieval_docs = retrieve_for_agent(
        query="who should I trust",
        agent_view=player_view,
        game_context=state.public_context(),
    )

    agent_input = build_agent_input(
        player_view=player_view,
        memory=memory,
        retrieval_docs=retrieval_docs,
        profile=get_profile(player.id),
        team_view=None,
    )

    assert_no_hidden_truth(agent_input, state.hidden_truth)
    assert_no_postgame_truth(agent_input, state.game_id)
```

### 4.5 必须新增的测试文件

```text
tests/test_visibility_player_view.py
tests/test_visibility_final_agent_input.py
tests/test_retrieval_access_control.py
tests/test_memory_no_hidden_truth.py
```

---

## 5. G4：Skill 协议抽象 —— 通用技能接口

### 5.1 问题

角色技能逻辑如果散落在 `roles/`、`actions.py` 和 phase handler 中，加新角色会改动多处代码，不利于展示可扩展架构。

### 5.2 v2 方案

新增 Skill 协议，但不建议一次性大重构。采用渐进迁移。

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Skill(Protocol):
    name: str
    owner_role: Role
    phase: Phase
    priority: int
    visibility_scope: str

    consumes_resource: str | None
    can_target_self: bool
    can_target_dead: bool
    can_execute_when_dead: bool
    rule_variant: str

    def legal_targets(self, state: GameState, actor: Player) -> list[PlayerId]: ...
    def validate(self, action: Action, state: GameState) -> ValidationResult: ...
    def apply(self, action: Action, state: GameState) -> list[GameEvent]: ...
    def summarize_for_actor(self, state: GameState, actor: Player) -> str: ...
    def summarize_for_public(self, event: GameEvent) -> str: ...
```

### 5.3 渐进迁移路线

```text
先做 Skill 协议外壳
  ↓
用 Adapter 包装现有技能逻辑
  ↓
新角色只走 Skill 协议
  ↓
已有角色逐步迁移
```

### 5.4 实施优先级

| 优先级 | 任务 |
|---|---|
| P2 | 新建 `backend/engine/skill.py` |
| P2 | 为 Seer / Witch / Hunter / Guard / Werewolf 写 adapter |
| P2 | 新角色 Cupid / Idiot 只走 Skill 协议 |
| P3 | 逐步替换 `actions.py` 中的 if/elif |

---

## 6. G5：狼队协作 —— 修正版，禁止偷看真实身份

### 6.1 问题

原 blueprint 中 `negotiate_wolf_kill()` 示例使用了：

```python
p.role
p.alignment == VILLAGE
```

这对引擎可见，但对狼人 Agent 不合法。狼人只能知道：

```text
自己身份 + 狼队队友 + 公开发言 + 公开投票 + 公开身份声明 + 狼队夜间战术状态 + belief 推断
```

不能直接读取其他玩家真实身份或真实阵营。

### 6.2 WolfTeamView

```python
@dataclass
class WolfTeamView:
    """狼队合法私有视角，只包含狼人阵营应知道的信息。"""

    alive_wolves: list[str]
    dead_wolves: list[str]

    role_assignments: dict[str, str]
    agreed_kill_target: str | None
    agreed_narrative: str
    contradiction_risks: list[str]
    tactic_phase: str

    # 注意：这里不包含非狼人玩家的真实 role / alignment
    public_claims_summary: dict[str, str]
    public_vote_summary: dict[str, list[str]]
    wolf_beliefs: dict[str, dict]
```

### 6.3 合法刀人协商算法

```python
def negotiate_wolf_kill(
    wolf_view: WolfTeamView,
    public_state: PublicGameState,
    belief_tracker: BeliefTracker,
) -> str:
    """狼队夜间协商刀人目标。只使用狼人合法可见信息。"""

    candidates = [
        p for p in public_state.alive_players
        if p.id not in wolf_view.alive_wolves
    ]

    scored: list[tuple[str, float]] = []

    for p in candidates:
        score = 0.0

        # 只能基于公开声明，而不是真实 role
        if public_claims_role(p.id, "seer", public_state):
            score += 0.40
        if public_claims_role(p.id, "witch", public_state):
            score += 0.25
        if public_claims_role(p.id, "hunter", public_state):
            score += 0.15

        # 基于公开投票与发言影响力
        score += 0.20 * vote_accuracy_estimate(p.id, public_state)
        score += 0.15 * speech_influence_score(p.id, public_state)

        # 基于狼人自己的 belief，而不是真相
        belief = belief_tracker.get_belief(p.id)
        score += 0.20 * belief.prob_god
        score -= 0.10 * belief.prob_wolf  # 狼人认为像狼的人，可能适合留着抗推

        # 正在被抗推的人，先不刀
        if p.id in current_frame_targets(public_state, wolf_view):
            score -= 0.25

        scored.append((p.id, score))

    return max(scored, key=lambda x: x[1])[0]
```

### 6.4 狼队发言协调

```python
def build_wolf_coordination_context(wolf_id: str, team_view: WolfTeamView) -> str:
    """给狼人 Think 阶段注入合法的队伍战术上下文。"""

    lines = [
        "[狼队协调]",
        f"你的战术角色: {team_view.role_assignments[wolf_id]}",
        f"统一口径: {team_view.agreed_narrative}",
        "队友战术分配:",
    ]

    for mate_id, tactic in team_view.role_assignments.items():
        if mate_id != wolf_id:
            lines.append(f"- {mate_id}: {tactic}")

    if team_view.contradiction_risks:
        lines.append("需要避免的矛盾:")
        for risk in team_view.contradiction_risks:
            lines.append(f"- {risk}")

    return "\n".join(lines)
```

### 6.5 必须增加的防泄露测试

```python
def test_wolf_kill_negotiation_does_not_use_hidden_alignment():
    """狼队刀人协商不得读取非狼人玩家真实 alignment。"""
    state = setup_game_with_hidden_roles()
    wolf_view = build_wolf_team_view(state, wolf_id="P1")
    public_state = state.to_public_state()

    with forbid_hidden_fields(["role", "alignment"]):
        target = negotiate_wolf_kill(wolf_view, public_state, belief_tracker)

    assert target in [p.id for p in public_state.alive_players if p.id not in wolf_view.alive_wolves]
```

---

## 7. G6：容错方向修正

### 7.1 正确降级链

```text
CognitiveAgent 主路径
  ↓ 失败：API 超时 / JSON 解析失败 / 非法动作
LLMAgent 降级
  ↓ 仍失败
HeuristicAgent 最终兜底
```

### 7.2 实现示例

```python
async def decide_with_fallback(self, player_view: PlayerView, action_type: str) -> Decision:
    try:
        return await self.decide_cognitive(player_view, action_type)
    except Exception as e:
        logger.warning("CognitiveAgent failed", exc_info=e)
        try:
            return await self.decide_llm_baseline(player_view, action_type)
        except Exception as e2:
            logger.error("LLMAgent failed; falling back to heuristic", exc_info=e2)
            return self.decide_heuristic(player_view, action_type)
```

### 7.3 日志字段

```text
fallback_used
fallback_from
fallback_to
fallback_reason
validation_error_count
```

---

## 8. G7：评测系统防自评 —— Golden Cases + Judge 校准

### 8.1 问题

LLM Judge 评价 LLM Agent 会有偏差。不能只说“三法官 + Critic”就结束，需要可解释的校准流程。

### 8.2 v2 定位

20 个 Golden Cases 只作为初版 sanity check，不作为强统计证明。

正式表述：

```text
初版使用 20 个 Golden Cases 做 Judge sanity check；
后续扩展到 50-100 个 case；
所有 TPR/FPR 都报告置信区间。
```

### 8.3 Golden Cases 示例

```python
GOLDEN_CASES = [
    {
        "id": "GC001",
        "scenario": "预言家首夜查验狼人，第二天白天",
        "decision": "vote checked_wolf",
        "human_label": "correct",
        "confidence": 1.0,
        "rationale": "查验结果是强信号，投票给查验狼人合理。",
    },
    {
        "id": "GC002",
        "scenario": "女巫首夜救人，后来发现救了自刀狼",
        "decision": "use_antidote",
        "human_label": "acceptable",
        "confidence": 0.8,
        "rationale": "首夜无法知道自刀，救人可接受，不能简单判失误。",
    },
    {
        "id": "GC003",
        "scenario": "猎人被投出局，开枪带走已明跳且高可信的预言家",
        "decision": "shoot credible_seer",
        "human_label": "incorrect",
        "confidence": 1.0,
        "rationale": "明显伤害好人阵营。",
    },
]
```

### 8.4 校准报告模板

```markdown
## LLM Judge 可靠性声明

| 指标 | 值 | 95% CI | 说明 |
|---|---:|---:|---|
| TPR | 0.87 | [0.65, 0.97] | 好决策被识别为好的比例 |
| FPR | 0.09 | [0.01, 0.29] | 差决策被误判为好的比例 |
| 样本量 | 20 | - | 初版 sanity check |
| Judge agreement | 0.83 | - | 三法官平均一致性 |

注意：20 条样本置信区间较宽，只用于初版校准；正式展示会继续扩展样本。
```

---

## 9. G8：检索指标可解释性与数据泄漏防控

### 9.1 问题

`NDCG@5=0.942` 是亮点，但如果没有测试集说明、标注方式、baseline 和消融，就容易被追问。

### 9.2 v2 规则

正式文档中不得保留未真实跑出的占位数字。

如果尚未跑评测，写：

```text
待补充：基于真实对局 query 的检索评测。
```

不要写漂亮但不可复现的数字。

### 9.3 防数据泄漏切分

检索评测必须按 `game_id` 切分：

```text
train games：生成 StrategyKnowledgeDoc 知识库
test games：产生 query 和 relevance label
```

不能用同一批对局既生成知识，又评测检索效果。

### 9.4 检索评测模板

```markdown
## 检索系统评测

### 测试集
- Query 数量：待填，来自 test games 的真实 Agent 检索请求
- Query 来源：真实对局去重 query
- Relevance 标注：人工标注，每条 query 标注相关文档
- 知识库规模：待填，来自 train games
- 数据切分：按 game_id 切分，避免同局泄漏

### 结果

| 方法 | NDCG@5 | Recall@5 | MRR | P@5 | 检索延迟 |
|---|---:|---:|---:|---:|---:|
| TF-IDF | 待填 | 待填 | 待填 | 待填 | 待填 |
| BM25 | 待填 | 待填 | 待填 | 待填 | 待填 |
| BGE-M3 | 待填 | 待填 | 待填 | 待填 | 待填 |
| BM25 + BGE-M3 RRF | 待填 | 待填 | 待填 | 待填 | 待填 |

### 消融

| 变体 | NDCG@5 | 变化 |
|---|---:|---:|
| 完整 RRF | 待填 | - |
| 仅 BM25 | 待填 | 待填 |
| 仅 BGE-M3 | 待填 | 待填 |
| 不过滤低可信知识 | 待填 | 待填 |
```

---

## 10. G9：规则边界测试 —— 先冻结规则配置

### 10.1 问题

测试里不能写“取决于规则”。比赛评估看的是你实现的规则是否自洽，而不是狼人杀规则本身有多少变体。

### 10.2 新增标准规则配置

建议新增：

```text
configs/rule_variant_standard.yaml
```

内容示例：

```yaml
name: standard_competition_v1

vote:
  tie_policy: no_exile
  revote_after_tie: true
  second_tie_policy: no_exile
  sheriff_vote_weight: 1.5

witch:
  can_use_both_potions_same_night: false
  can_save_self_first_night: true
  can_save_self_after_first_night: false
  poison_blocks_hunter_shot: true

guard:
  can_guard_same_target_consecutively: false
  same_guard_and_witch_save_causes_death: true

hunter:
  can_shoot_when_voted_out: true
  can_shoot_when_wolf_killed: true
  can_shoot_when_poisoned: false

death:
  last_words_enabled: true
  dead_players_can_vote: false
  dead_players_receive_private_info: false

resolution_order:
  - guard
  - wolf_kill
  - witch_save
  - witch_poison
  - death_settlement
  - hunter_shot
```

### 10.3 规则测试原则

所有边界测试必须引用明确 rule variant：

```python
def test_hunter_poisoned_cannot_shoot(standard_rules):
    state = setup_game(rule_variant=standard_rules)
    # ...
    assert not can_hunter_shoot(state)
```

### 10.4 规则边界清单

| 编号 | 场景 | 期望 |
|---|---|---|
| E01 | 普通平票 | 无人出局或进入 PK，按配置执行 |
| E02 | PK 后再次平票 | 无人出局 |
| E03 | 警长票权重打破平票 | 警长票侧生效 |
| E04 | 女巫同夜救毒 | 按配置禁止或允许 |
| E05 | 药水已用再次使用 | 非法动作 |
| E06 | 守卫连续守同一人 | 非法或无效，按配置 |
| E07 | 同守同救 | 按配置结算 |
| E08 | 猎人被刀 | 可开枪 |
| E09 | 猎人被毒 | 不可开枪 |
| E10 | 死亡玩家投票 | 不可投票 |
| E11 | 狼刀 + 救 + 毒 + 守卫同夜结算 | 按 resolution_order |
| E12 | 终局狼人数量达到胜利条件 | 狼人胜利 |

---

## 11. G10：监控日志产品化

### 11.1 AgentDecisionLog

```python
class AgentDecisionLog(Base):
    __tablename__ = "agent_decision_logs"

    id: str
    trace_id: str
    game_id: str
    agent_id: str
    day: int
    phase: str
    action_type: str

    chosen_action: str
    confidence: float
    rationale: str

    model_name: str
    provider: str
    token_in: int
    token_out: int
    latency_ms: int
    cost_usd: float

    validation_errors: int
    fallback_used: bool
    fallback_reason: str | None
    error_type: str | None

    visibility_scope_hash: str
    redaction_version: str
    retrieved_doc_ids: list[str]
    strategy_memory_snapshot: dict

    prompt_hash: str
    prompt_template_version: str
    agent_version: str
    random_seed: int
```

### 11.2 Prompt 保存规则

不要长期保存完整 prompt 明文。建议保存：

```text
prompt_hash
prompt_template_version
redacted_prompt_snapshot
```

full prompt 只在本地调试或短期审计环境中保存。

### 11.3 GameHealthReport

```python
@dataclass
class GameHealthReport:
    game_id: str
    total_decisions: int
    fallback_count: int
    fallback_rate: float
    validation_error_rate: float

    avg_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    avg_confidence: float

    isolation_violations: int
    visibility_hash_collisions: int

    avg_retrieved_docs: float
    zero_retrieval_rate: float

    def is_healthy(self) -> bool:
        return (
            self.fallback_rate < 0.10
            and self.validation_error_rate < 0.05
            and self.isolation_violations == 0
            and self.p95_latency_ms < 5000
        )
```

---

## 12. G11：主线收束 —— 玩、评、进化

所有文档、README、答辩 PPT 和 demo 应统一到下面结构。

```text
玩 Play
├── CognitiveAgent
├── RoleStrategyCard
├── WolfTeamView
├── BeliefTracker
├── StrategyMemory
└── Strategy Retrieval

评 Evaluate
├── deterministic replay
├── CounterfactualAnalyzer
├── PerStepScorer
├── LLM Judge + Golden Cases 校准
├── DecisionTrace
└── PublishedReviewDocument

进化 Evolve
├── StrategyKnowledgeDoc
├── KnowledgeConfidence
├── KnowledgeAccessControl
├── KnowledgeApplicability
├── Contradiction Detection
├── Back-testing
└── Leaderboard
```

---

## 13. G12：Leaderboard 多维度化 —— 第一版压缩到 8 个核心指标

### 13.1 第一版核心指标

| 指标 | 说明 |
|---|---|
| win_rate | 总体胜率 |
| village_win_rate | 好人阵营胜率 |
| wolf_win_rate | 狼人阵营胜率 |
| avg_decision_score | PerStepScorer 平均分 |
| bad_case_rate | bad case 比例 |
| skill_efficiency | 神职技能收益 |
| vote_contribution | 投票贡献 |
| cost_per_game | 每局成本 |

### 13.2 展示模板

```markdown
| 版本 | 胜率 | 好人胜率 | 狼人胜率 | 决策分 | BadCase | 技能收益 | 投票贡献 | 成本/局 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cognitive_v3 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| cognitive_v2 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| llm_baseline | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
| heuristic | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |
```

### 13.3 高级指标作为 P3

这些可以作为加分项，但不阻塞第一版：

```text
95% CI
bootstrap
Bradley-Terry
Pareto frontier
知识利用率
版本回溯图
```

---

## 14. G13：MBTI 复盘重新定位

### 14.1 定位

MBTI 复盘不作为核心技术卖点，而是：

```text
Multi-Perspective Reflection，用于丰富 Agent 行为多样性。
```

### 14.2 规则

1. MBTI 复盘输出标记为 `L4_speculative`。
2. 不进入 Agent 决策检索索引。
3. 不计入决策质量评分。
4. 文档篇幅不超过 5%。
5. 展示时放在“Agent 风格多样性”而非“策略能力”。

### 14.3 数据字段

```python
perspective_type: Literal["strategic", "mbti_styled"]
```

只有 `strategic` 视角可以进入 Track B 正式评测链路。

---

## 15. G14：Track B / Track C 主次明确化

### 15.1 推荐表述

> 本项目主攻“评测 + 复盘”：通过确定性 replay、反事实推演、级联评分和结构化报告，定位 Agent 在发言、投票、技能使用、阵营协作中的关键失误。进一步，我们将复盘结果沉淀为带可信度和权限控制的策略知识，作为轻量自进化能力。

### 15.2 不要声称

除非真实实现，否则不要声称：

```text
自主读代码 → 改代码 → 自动构建测试 → 失败回滚
```

当前项目应主张：

```text
评测驱动的策略知识迭代
```

---

## 16. G15：知识可信度与入库纠错 —— v2 完整方案

### 16.1 核心问题

复盘不一定正确。如果 Reflector / CounterfactualAnalyzer 的输出被直接写入 StrategyKnowledgeDoc，再被下一局 Agent 检索使用，就可能形成：

```text
错误复盘 → 错误知识 → 错误检索 → 错误决策 → 更多错误复盘
```

所以自进化闭环必须承认：

> 复盘结论是有噪声的，不能直接等同于事实。

### 16.2 五级可信度分层

| 层级 | 名称 | 定义 | 示例 | 使用规则 |
|---|---|---|---|---|
| L0 | 可验证事实 | engine log 直接确认 | P3 第 2 天投 P5 | 可用，但仍受 visibility_scope 限制 |
| L1 | 规则性结论 | L0 + 规则推导 | 死亡玩家投票是非法动作 | 可用，但仍受 visibility_scope 限制 |
| L2 | 统计性洞察 | 多局统计，有样本量 | 女巫首夜救人胜率提升 n=50 | 可检索，展示 CI |
| L3 | 策略性判断 | LLM Judge / Reflector 单局评价 | 女巫不救 P5 是失误 | 高共识、高置信、未被拒绝才可检索 |
| L4 | 推测性洞察 | 低共识或缺证据 | 发言风格暗示 P5 像狼 | 不进入决策检索 |

### 16.3 v2 新增：KnowledgeAccessControl

可信不等于可见。L0/L1 也可能是私有事实，所以必须加权限控制。

```python
@dataclass
class KnowledgeAccessControl:
    visibility_scope: Literal[
        "public",
        "self_private",
        "wolf_team_private",
        "postgame_only",
        "global_deidentified",
    ]
    source_game_ids: list[str]
    allowed_roles: list[str] | None
    allowed_phases: list[str] | None
    deidentified: bool
    contains_current_game_private_info: bool = False
```

### 16.4 v2 新增：KnowledgeApplicability

策略知识必须知道自己适用于什么局面，防止错误泛化。

```python
@dataclass
class KnowledgeApplicability:
    role: str | None
    phase: str | None
    rule_variant: str
    min_players: int | None
    max_players: int | None
    required_public_facts: list[str]
    forbidden_public_facts: list[str]
    required_private_state: list[str]
    strategy_context: list[str]
```

示例：

```text
“女巫首夜救人通常合理”只在以下条件下适用：
- 当前角色是女巫；
- 女巫有解药；
- 当晚有人被刀；
- 当前规则允许首夜救人；
- 没有强烈自刀狼证据；
- 对局规则配置与生成该知识的规则兼容。
```

### 16.5 完整 StrategyKnowledgeDoc

```python
@dataclass
class StrategyKnowledgeDoc:
    id: str
    content: str
    confidence: KnowledgeConfidence
    access_control: KnowledgeAccessControl
    applicability: KnowledgeApplicability
    source_game_ids: list[str]
    version: str
    status: Literal["pending", "active", "disputed", "deprecated", "promoted"]
    score: float = 0.0
```

### 16.6 检索过滤 v2

检索必须同时满足：

```text
可信度允许 + 权限允许 + 不泄露当前局私有信息 + 适用条件匹配
```

```python
def retrieve_for_agent(
    query: str,
    agent_view: PlayerView,
    game_context: GameContext,
    top_k: int = 5,
) -> list[StrategyKnowledgeDoc]:
    candidates = hybrid_search(query, top_k * 5)

    filtered: list[StrategyKnowledgeDoc] = []
    for doc in candidates:
        if not confidence_allowed(doc.confidence):
            continue

        if not visibility_allowed(doc.access_control, agent_view):
            continue

        if leaks_current_game_private_info(doc, game_context):
            continue

        if not applicability_matches(doc.applicability, game_context):
            continue

        if doc.status in {"disputed", "deprecated"}:
            continue

        filtered.append(doc)

    return rerank(filtered)[:top_k]
```

### 16.7 confidence_allowed

```python
def confidence_allowed(kc: KnowledgeConfidence) -> bool:
    if kc.tier == "L4_speculative":
        return False

    if kc.human_verdict == "rejected":
        return False

    if kc.tier == "L3_strategic":
        if kc.judge_agreement is not None and kc.judge_agreement < 0.67:
            return False
        if kc.confidence_score is not None and kc.confidence_score < 0.70:
            return False

    return True
```

### 16.8 L3 不能靠 LLM 自信升级

L3 只能靠多局证据升级为 L2。升级条件建议：

```text
- 多局重复出现；
- 样本量达到阈值；
- 效应方向稳定；
- 与 L0/L1 事实不冲突；
- 至少部分样本经过人工抽查；
- 使用该知识的 Agent 在 A/B 中有提升。
```

### 16.9 矛盾检测优化

不要全量 pairwise 比较。流程：

```text
1. embedding / BM25 找 top-N 近似相关知识
2. L0/L1 用结构化规则判断冲突
3. L3/L4 才调用轻量 LLM 判断冲突
4. 冲突知识进入 disputed，不直接删除
```

状态机：

```text
pending → active → disputed → deprecated
              ↓
           promoted
```

### 16.10 回验 Back-testing

回验必须先检查 applicability：

```python
def backtest_knowledge(doc: StrategyKnowledgeDoc, new_game: GameState) -> KnowledgeVerdict:
    if not applicability_matches(doc.applicability, new_game.to_context()):
        return KnowledgeVerdict(status="not_applicable")

    if doc.confidence.tier == "L2_statistical":
        return update_statistical_evidence(doc, new_game)

    if doc.confidence.tier == "L3_strategic":
        return evaluate_strategy_consistency(doc, new_game)

    return KnowledgeVerdict(status="skipped")
```

### 16.11 置信度衰减

```python
def decay_confidence(doc: StrategyKnowledgeDoc) -> None:
    kc = doc.confidence

    if kc.tier == "L3_strategic":
        if kc.games_since_creation > 50 and kc.times_upvoted == 0:
            kc.tier = "L4_speculative"
            doc.status = "deprecated"

        if kc.contradiction_count >= 3 and kc.times_upvoted < kc.contradiction_count:
            kc.tier = "L4_speculative"
            doc.status = "disputed"
```

### 16.12 与现有模块对接

| 现有模块 | v2 角色 | 产出层级 |
|---|---|---|
| Engine log | 生成可验证事实 | L0 |
| Tier 1 deterministic scorer | 规则性结论 | L0 / L1 |
| Tier 2 light LLM | 单 judge 策略判断 | L3 |
| Tier 3 heavy LLM | 多 judge 策略判断 | L3 |
| CounterfactualAnalyzer | 反事实标注 | L3，需标注 verified 状态 |
| Reflector MBTI | 风格化反思 | L4 |
| PublishedReviewDocument | 正式报告 | 只展示 L0-L3，L4 不进入正式结论 |
| Retrieval | 策略检索 | 加可信度、权限、适用条件过滤 |

---

## 17. 前端问题说明

原 blueprint 范围不含前端，因此它没有完全解决上一轮评价中“前端体验偏弱”的问题。

本 v2 仍以后端、Agent、评测为核心，但建议单独新增：

```text
docs/replay_viewer_plan.md
```

最低版本 Replay Viewer 需要支持：

- 玩家状态盘；
- 阶段时间轴；
- 发言记录；
- 投票流向；
- 上帝视角 / 玩家合法视角切换；
- DecisionTrace 面板；
- bad case 高亮；
- 反事实结果展示；
- Leaderboard 页面。

---

## 18. 实施路线图 v2

### Phase 1：P0 安全与可信闭环修复，1-2 天

| 优先级 | 改动 | 涉及文件 | 目标 |
|---|---|---|---|
| P0 | 修 G5 狼队刀人逻辑，禁止读取真实身份 | `agents/cognitive/wolf_team.py` | 消除信息泄露 |
| P0 | 新增 `KnowledgeAccessControl` | `db/models.py`, migration | 防知识泄露 |
| P0 | 新增 `KnowledgeApplicability` | `db/models.py`, migration | 防策略误用 |
| P0 | 检索过滤 v2 | `agents/cognitive/retrieval.py` | 可信 + 权限 + 适用条件 |
| P0 | final_agent_input 信息隔离测试 | `tests/test_visibility_final_agent_input.py` | 证明无泄露 |
| P0 | 容错方向修正 | `agents/factory.py` / `agent.py` | 工程正确性 |
| P0 | 冻结标准规则配置 | `configs/rule_variant_standard.yaml` | 测试可复现 |

### Phase 2：P1 评测与展示证据，2-3 天

| 优先级 | 改动 | 涉及文件 | 目标 |
|---|---|---|---|
| P1 | RoleStrategyCard | `agents/cognitive/strategies/` | 策略深度 |
| P1 | DecisionTrace | `protocols/schemas.py`, `db/models.py` | 可追溯 |
| P1 | Golden Cases 初版 | `eval/golden_cases.py` | Judge 校准 |
| P1 | Judge 校准报告 | `eval/llm_judge.py` | 防自评自嗨 |
| P1 | 检索评测模板 | `eval/retrieval_eval.py` | 指标可信 |
| P1 | 信息隔离报告 | `docs/information_isolation_tests.md` | 提交证据 |
| P1 | 角色策略文档 | `docs/role_strategy_playbook.md` | 提交证据 |

### Phase 3：P2 可扩展与工程完整度，2-4 天

| 优先级 | 改动 | 涉及文件 | 目标 |
|---|---|---|---|
| P2 | Skill Protocol + adapter | `engine/skill.py` | 可扩展 |
| P2 | 规则边界测试 | `tests/test_rules.py` | 规则正确性 |
| P2 | AgentDecisionLog | `db/models.py` | 可观测性 |
| P2 | GameHealthReport | `eval/health.py` | 工程完整度 |
| P2 | Leaderboard 8 指标 | `eval/leaderboard.py` | 版本对比 |
| P2 | contradiction detection | `eval/knowledge_quality.py` | 知识纠错 |
| P2 | back-testing | `eval/knowledge_quality.py` | 知识回验 |

### Phase 4：P3 加分与前端展示，后续

| 优先级 | 改动 | 目标 |
|---|---|---|
| P3 | Replay Viewer plan / MVP | 前端体验 |
| P3 | Bootstrap CI / Bradley-Terry | Leaderboard 高级化 |
| P3 | 更大 Golden Cases 集 | Judge 可信度 |
| P3 | A/B Tournament 自动化 | 自进化证据 |

---

## 19. 最终提交证据包建议

```text
docs/
  architecture_scoring_review.md
  architecture_improvement_blueprint_v2.md
  role_strategy_playbook.md
  information_isolation_tests.md
  evaluation_methodology.md
  golden_cases_report.md
  retrieval_evaluation_report.md
  leaderboard_sample.md
  replay_viewer_plan.md

configs/
  rule_variant_standard.yaml

tests/
  test_visibility_player_view.py
  test_visibility_final_agent_input.py
  test_retrieval_access_control.py
  test_memory_no_hidden_truth.py
  test_rules.py

demo/
  demo_script.md
  screenshots/
    replay_view.png
    decision_trace.png
    counterfactual_report.png
    leaderboard.png
```

---

## 20. 风险清单

| 风险 | 等级 | 应对 |
|---|---|---|
| 狼队逻辑偷看真实身份 | 高 | G5 修正 + 测试禁止访问 hidden fields |
| 知识回流放大错误 | 高 | G15 可信度 + 权限 + 适用条件 + 回验 |
| Retrieval 泄露赛后真相 | 高 | AccessControl + final_agent_input 测试 |
| 规则变体不明确 | 高 | 冻结 standard rule variant |
| LLM Judge 自评偏差 | 中高 | Golden Cases + TPR/FPR + CI |
| 检索指标不可复现 | 中高 | 按 game_id 切分 + baseline + 消融 |
| 前端体验仍弱 | 中 | 单独补 Replay Viewer MVP |
| 指标过多导致延期 | 中 | Leaderboard 第一版只做 8 指标 |
| 外部引用无法核验 | 中 | 正式文档只保留已核验引用 |

---

## 21. 最终判断

v2 方案的核心不是“再加几个模块”，而是把原先最容易被质疑的闭环补上安全阀：

```text
不是所有复盘都可信；
不是所有可信知识都可见；
不是所有可见知识都适用于当前局面；
不是所有知识都应该永久保留。
```

因此最终闭环应升级为：

```text
对局
  → 结构化 DecisionTrace
  → 三级评测 + 反事实复盘
  → L0-L4 知识分层
  → 权限与适用条件过滤
  → 矛盾检测 / 回验 / 衰减
  → A/B Leaderboard 验证
  → 下一代 Agent 检索使用
```

这比原始“复盘 → 入库 → 检索 → 进化”更可信，也更适合答辩。

---

## 附录 A：v2 完整闭环架构

```text
PLAY
├── CognitiveAgent
│   ├── Profile / Personality Layer
│   ├── RoleStrategyCard / Strategy Layer
│   ├── BeliefTracker
│   ├── StrategyMemory
│   ├── WolfTeamView（仅合法狼队信息）
│   └── Fallback: Cognitive → LLM → Heuristic
├── Game Engine
│   ├── PhaseManager
│   ├── ActionValidator
│   ├── Visibility.for_player()
│   └── Skill Protocol
└── DecisionTrace
    ├── visible_facts
    ├── candidate_actions
    ├── chosen_action
    └── confidence / rationale

EVALUATE
├── deterministic replay
├── Tier 1: rule scorer
├── Tier 2: light LLM
├── Tier 3: heavy LLM panel
├── Golden Cases calibration
├── CounterfactualAnalyzer
├── Information Isolation Audit
└── PublishedReviewDocument

EVOLVE
├── StrategyKnowledgeDoc
│   ├── KnowledgeConfidence: L0-L4
│   ├── KnowledgeAccessControl
│   ├── KnowledgeApplicability
│   └── status: pending / active / disputed / deprecated / promoted
├── Retrieval Filter
│   ├── confidence_allowed
│   ├── visibility_allowed
│   ├── leaks_current_game_private_info
│   └── applicability_matches
├── Contradiction Detection
├── Back-testing
├── Confidence Decay
└── Leaderboard
```

---

## 附录 B：引用与资料处理原则

正式提交材料中，外部研究引用遵循以下原则：

1. 只保留已核验论文、官网或正式技术报告。
2. 未核验项目名放入待核验列表，不进入核心论证。
3. 不用外部引用替代本项目自己的实验数据。
4. 所有漂亮指标必须可复现，否则写“待补充”。

待核验或谨慎引用的名称包括：

```text
PORTAL
DVM
Zalando Postmortem Pipeline
Rootly / OperatorMesh 2025
Agent Evaluation Beyond Win-Rates
Cohere Bradley-Terry 2025
EvaRAG / UDCG 2025
```

这些可以作为后续资料补充，但不应在正式答辩中作为核心依据。