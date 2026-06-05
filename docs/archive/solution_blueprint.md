# AI Werewolf 评分与架构改进 — 解决方案蓝图

> 日期：2026-06-02  
> 基于：`docs/architecture_scoring_review.md` 识别的全部不足  
> 范围：后端 + 评测 + Agent，不含前端

---

## 目录

1. [G1: 角色策略深度 —— 从人格包装到策略编码](#g1)
2. [G2: 决策可追溯 —— 结构化决策记录](#g2)
3. [G3: 信息隔离 —— 从口头保证到可验证证明](#g3)
4. [G4: Skill 协议抽象 —— 通用技能接口](#g4)
5. [G5: 狼队协作 —— 多 Agent 协调机制](#g5)
6. [G6: 容错方向修正](#g6)
7. [G7: 评测系统防自评 —— Golden Cases + 人工校准](#g7)
8. [G8: 检索指标可解释性](#g8)
9. [G9: 规则边界测试](#g9)
10. [G10: 监控日志产品化](#g10)
11. [G11: 主线收束](#g11)
12. [G12: Leaderboard 多维度化](#g12)
13. [G13: MBTI 复盘重新定位](#g13)
14. [G14: Track B/C 主次明确化](#g14)
15. [G15: 知识可信度与入库纠错 —— 复盘不一定对](#g15)
16. [实施路线图](#roadmap)

---

<a name="g1"></a>
## G1: 角色策略深度 —— 从人格包装到策略编码

### 问题

当前架构有 MBTI、PersonaTraits、MindTraits 三层人格系统，但这些都是"风格层"。评委关心的是策略深度：预言家什么时候跳身份？狼人什么时候悍跳/倒钩/冲票？女巫什么时候救人/毒人？

### 工业界参考

2024-2025 年游戏 AI 研究的主流范式是 **LLM + Behavior Tree + 策略记忆** 的混合架构：

| 系统 | 核心方法 | 效果 |
|------|----------|------|
| **MASMP** (Oct 2025) | 自然语言驱动状态机 + 策略记忆变量 `[Tactic]/[PriorityUnit]` | 星际争霸 II 胜率从 0% → 60% |
| **Adaptive Command** (2025) | LLM → Behavior Modulator → Behavior Tree 执行 | 人机协作实时策略调整 |
| **PORTAL** (Mar 2025) | LLM 生成 Behavior Tree DSL，融合规则+神经网络 | 跨 1000+ 3D 游戏泛化 |

核心洞察：**人格层做风格，策略层做决策。两层解耦，各自独立演进。**

### 狼人杀方案设计

```
┌─────────────────────────────────────────┐
│ 表达风格层 (Personality Layer)           │
│ MBTI + PersonaTraits + Humanization      │
│ → 控制"怎么说" (语气、措辞、句式)        │
└──────────────┬──────────────────────────┘
               │ 注入
┌──────────────▼──────────────────────────┐
│ 策略决策层 (Strategy Layer)              │
│ RoleStrategy + Playbook + StrategyBias   │  ← 新增！独立于人格
│ → 控制"做什么" (时机、目标、风险评估)    │
└─────────────────────────────────────────┘
```

#### 角色策略编码表 (RoleStrategyCard)

每个角色一张策略卡，存储在 `backend/agents/cognitive/strategies/` 目录下，与 Profile 解耦：

```python
@dataclass
class RoleStrategyCard:
    """角色的策略参数 —— 独立于 MBTI/Persona"""
    role: str
    
    # 信息策略
    claim_timing: ClaimTiming        # 什么时候跳身份
    info_release_policy: str         # 什么信息何时释放
    
    # 投票策略
    vote_leadership: float           # 0-1 带队倾向
    vote_follow_threshold: float     # 低于此置信度时跟票
    split_vote_tolerance: float      # 容忍分票程度
    
    # 对抗策略 (仅狼人)
    bluff_timing_preference: str     # 悍跳/倒钩/深水偏好
    sacrifice_threshold: float       # 卖队友阈值
    
    # 技能策略
    skill_conservation: float        # 0-1 保守程度 (越高越省技能)
    skill_target_priority: list[str] # 目标优先级排序
    
    # 风险偏好
    risk_tolerance: float            # 0-1 风险承受度
    information_seeking: float       # 0-1 信息饥渴度
```

#### 策略记忆 (Strategy Memory)

参考 MASMP 的 `[Tactic]/[PriorityUnit]` 持久化变量设计：

```python
@dataclass
class StrategyMemory:
    """跨回合持久化的策略状态"""
    current_tactic: str              # "aggressive"/"defensive"/"information_gathering"
    suspicion_ranking: list[str]     # 当前怀疑排序 (player_id 列表)
    trusted_allies: list[str]        # 当前信任的玩家
    exposed_risk: float              # 身份暴露风险评估 (狼人专用)
    info_debt: list[str]             # 欠公众的信息 (预言家验人未报等)
```

这些变量在 Pipeline 的 Think 阶段被注入 prompt，使 Agent 的决策具有跨回合连贯性。解决了 "Knowing-Doing Gap"——Agent 推理正确但执行断裂的问题。

#### 实现路径

1. 新建 `backend/agents/cognitive/strategies/` 包
2. 每角色一个 `.py` 文件定义 `RoleStrategyCard` 默认值
3. `StrategyMemory` 集成到 `Memory` 类中
4. Pipeline Think 阶段注入 strategy context

---

<a name="g2"></a>
## G2: 决策可追溯 —— 结构化决策记录

### 问题

当前 Agent 输出长 chain-of-thought，对调试有用但对评委展示有害——暴露完整推理链显得杂乱，且无法做跨对局的统计分析。

### 工业界参考

SRE 事后分析（Zalando、Rootly、Harness）和 LLM agent 评估（HAL、AgentBench）都采用**结构化决策日志**而非原始思维链。关键字段：决策 ID、时间戳、候选动作、选中动作、置信度、原因摘要、触发规则/检索文档 ID、模型版本。

### 方案设计

每条 Agent 决策输出结构化 `DecisionTrace`：

```json
{
  "decision_id": "d_abc123",
  "game_id": "g_001",
  "agent_id": "p3_seer",
  "agent_version": "cognitive_v7",
  "prompt_hash": "sha256:abc...",
  "phase": "DAY_VOTE",
  "day": 2,
  
  "visible_facts": [
    "P5 claimed Seer on day 1",
    "P7 voted P5 on day 1, now P5 is dead",
    "P3 (self) checked P8 on night 1: werewolf"
  ],
  "belief_delta": {
    "P8": {"suspicion": "+0.4", "reason": "seer check result"},
    "P7": {"suspicion": "-0.2", "reason": "voted the real seer claimant"}
  },
  
  "candidate_actions": [
    {"action": "vote P8", "score": 0.85, "rationale": "checked werewolf"},
    {"action": "vote P7", "score": 0.40, "rationale": "suspicious voting pattern"},
    {"action": "abstain", "score": 0.15, "rationale": "insufficient information"}
  ],
  "chosen_action": "vote P8",
  "confidence": 0.85,
  "rationale": "Night 1 seer check confirmed P8 is werewolf; highest EV action",
  
  "retrieved_strategy_ids": ["seer_claim_timing_v2", "vote_leadership_v1"],
  "active_playbook": "seer_aggressive_reveal",
  "strategy_memory_snapshot": {
    "current_tactic": "information_gathering",
    "suspicion_ranking": ["P8", "P5", "P7"]
  },
  
  "llm_metadata": {
    "model": "minimax-m2.7",
    "token_in": 2847,
    "token_out": 312,
    "latency_ms": 1230,
    "cost_usd": 0.0032
  }
}
```

#### 关键设计决策

- **candidate_actions 包含分数和原因**：不是只输出最终决策，而是展示"考虑过哪些选项"，证明 Agent 不是随机选择
- **belief_delta**：追踪每步决策前后信念变化，支持事后审计"为什么当时做出了那个判断"
- **不暴露完整思维链**：`rationale` 是 ≤100 字的简洁摘要，不是 2000 字的 chain-of-thought

---

<a name="g3"></a>
## G3: 信息隔离 —— 从口头保证到可验证证明

### 问题

当前文档说"PlayerView + Visibility.for_player() 保证信息隔离"，但没有测试证明。评委可以合理质疑：你怎么知道 Agent 没偷看身份？

### 工业界参考

| 方法 | 来源 | 要点 |
|------|------|------|
| **Process Opacity 测试** | CSP 2019, Gruska & Ruiz | 定义观察函数，证明攻击者无法从部分可观察 trace 推断隐藏状态 |
| **SentinelAgent TLA+ 验证** | Apr 2026 | 7 条安全属性，270 万状态模型检查，0 违规 |
| **Epistemic Temporal Logic** | Finkbeiner et al. 2025 | 用认知时序逻辑形式化"Agent X 在时刻 t 不知道事实 Y" |
| **非干扰性类型系统** | LCC, Eng App of AI 2018 | 静态+动态类型检查保证信息流安全 |

核心启示：**不是穷举测试所有可能泄露路径，而是定义安全属性，再用测试+模型检查证明这些属性成立。**

### 狼人杀方案设计

#### 3.1 信息分层 (已成文，此处精炼)

| 层级 | 内容 | 可见范围 | 进入 Agent Memory? | 进入 Knowledge Store? |
|:---:|------|----------|:---:|:---:|
| **Public** | 发言、投票、死亡公告 | 全员 | 是 | 可脱敏 |
| **Private Role** | 自己身份、技能状态 | 仅自己 | 是 | 否 |
| **Team Private** | 狼队名单 | 同阵营 | 是 | 仅脱敏统计 |
| **Hidden Truth** | 他人真实身份 | 仅引擎 | **否** | **否** |
| **Post-game Truth** | 全局真相 | 复盘模块 | 仅评测 | 可脱敏 |

#### 3.2 安全属性清单

参照 SentinelAgent 的 7 属性模式，定义狼人杀信息隔离的 8 条安全属性：

```
P1: 狼人不能看到预言家查验结果
P2: 村民不能看到狼队名单
P3: 死亡玩家不能投票
P4: Agent Memory 不包含 Hidden Truth 事实
P5: 策略检索不返回当前对局的私有信息
P6: 复盘反思结果在对局进行中不可见
P7: HumanAgent 合法视角 = AIPlayer 合法视角
P8: 知识回流不会把当前局事实泄露给下一局
```

#### 3.3 测试框架

不追求形式化模型检查（对 Python 项目过重），采用**基于属性的测试 + 对抗性测试**：

```python
# 测试示例
def test_property_P1_wolf_cannot_see_seer_result():
    """P1: 狼人的 PlayerView 不应包含预言家的查验结果"""
    state = setup_game(roles=["Werewolf", "Seer", "Villager"])
    seer = get_player(state, role="Seer")
    wolf = get_player(state, role="Werewolf")
    
    # 预言家查验了 P3
    state = apply_action(state, seer, "divine", target="P3", result="werewolf")
    
    # 构建狼人视角
    wolf_view = Visibility.for_player(state, wolf.id)
    
    # 断言：狼人视角中不应包含查验结果
    assert "P3 is werewolf" not in serialize(wolf_view)
    assert not any(e.payload.get("result") == "werewolf" 
                   for e in wolf_view.events if e.type == EventType.DIVINE)

def test_property_P5_retrieval_no_current_game_leak():
    """P5: 策略检索不应返回包含当前对局私有信息的文档"""
    # 插入一条"标记了当前 game_id"的知识
   KnowledgeStore.insert(StrategyKnowledgeDoc(
        content="P3 is werewolf",
        source_game_id=current_game.id,
        tier="L3_strategic"
    ))
    
    results = retrieve_for_agent("who is werewolf", role="villager")
    
    # 断言：source_game_id == 当前对局的文档不应出现在结果中
    assert all(doc.source_game_id != current_game.id for doc in results)
```

#### 3.4 信息隔离测试报告模板

每个属性一个测试文件，输出标准化报告：

```markdown
## P1: 狼人不能看到预言家查验结果
- **测试用例数**: 12
- **覆盖场景**: 首夜查验 / 多夜查验 / 查验已死玩家 / 查验狼队友
- **结果**: 12/12 PASS
- **关键断言**: PlayerView 不包含 EventType.DIVINE 事件
```

---

<a name="g4"></a>
## G4: Skill 协议抽象 —— 通用技能接口

### 问题

当前角色技能散落在 `roles/` 和 `actions.py` 中，添加新角色需要改多处代码。如果要展示"可扩展架构"，应该有统一的 Skill 协议。

### 工业界参考

MASMP 和 Adaptive Command 都采用**模块化行为树节点**作为技能抽象。每个技能是一个独立节点，有标准化的前置条件、执行体和后置效果。

### 方案设计

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Skill(Protocol):
    """通用技能协议 —— 添加新角色只需实现此接口"""
    
    # 元数据
    name: str
    owner_role: Role
    phase: Phase
    cooldown_days: int = 0
    
    # 目标选择
    def legal_targets(self, state: GameState, actor: Player) -> list[Player]: ...
    
    # 校验
    def validate(self, action: Action, state: GameState) -> ValidationResult: ...
    
    # 执行
    def apply(self, action: Action, state: GameState) -> list[GameEvent]: ...
    
    # 可见性
    def visibility(self, event: GameEvent, viewer: Player) -> VisibilityScope: ...
    
    # 摘要 (给不同角色的视角)
    def summarize_for_actor(self, state: GameState, actor: Player) -> str: ...
    def summarize_for_target(self, event: GameEvent) -> str: ...
    def summarize_for_public(self, event: GameEvent) -> str: ...


class SkillRegistry:
    """技能注册表 —— 单例，替代硬编码的 if/elif 链"""
    
    _skills: dict[Role, list[Skill]] = {}
    
    @classmethod
    def register(cls, skill: Skill) -> None:
        cls._skills.setdefault(skill.owner_role, []).append(skill)
    
    @classmethod
    def for_role(cls, role: Role, phase: Phase) -> list[Skill]:
        return [s for s in cls._skills.get(role, []) if s.phase == phase]
    
    @classmethod
    def validate_action(cls, action: Action, state: GameState) -> ValidationResult:
        for skill in cls.for_role(action.actor.role, state.phase):
            if skill.name == action.skill_name:
                return skill.validate(action, state)
        return ValidationResult(valid=False, reason=f"No skill {action.skill_name}")
```

#### 实现优先级

1. 先重构现有 6 个角色 (Seer/Witch/Hunter/Guard/Werewolf/Villager) 为 Skill 实现
2. 用 SkillRegistry 替换 `actions.py` 中的 if/elif 链
3. 添加新角色 (Cupid/Idiot) 验证可扩展性

---

<a name="g5"></a>
## G5: 狼队协作 —— 多 Agent 协调机制

### 问题

当前架构中狼人各自独立决策，没有显式的团队协作。但多 Agent 博弈的核心就是狼队如何协调——谁悍跳、谁倒钩、谁冲票、如何避免发言互相矛盾。

### 工业界参考

| 系统 | 协调机制 |
|------|----------|
| **DVM (2025)** | Predictor (角色推理) → Decider (PPO 策略) → Discursor (语言生成)，三模块协同 |
| **MultiMind (Apr 2025)** | Theory of Mind 因果 Transformer 预测二阶信念 + MCTS 搜索最优发言 |
| **RL-Instructed (2024)** | RL 训练"讨论策略"——何时指控/支持/转移，证明了讨论从根本上改变博弈均衡 |
| **Among Us MARL (2024)** | 将通信分解为"听"和"说"，分别用 RL 训练，"听"预测环境信息，"说"影响他人行为 |

关键发现：**狼队协作不需要显式的"狼队夜间聊天"协议。最有效的方法是让每个狼人共享一个"阵营状态视图"——知道谁是队友、谁已被怀疑、当前战术目标是什么。**

### 狼人杀方案设计

#### 5.1 狼队共享状态 (WolfTeamView)

```python
@dataclass
class WolfTeamView:
    """狼队共享战术状态 —— 在夜阶段更新，注入每个狼人的 Think prompt"""
    
    # 队友信息
    alive_wolves: list[str]           # 存活狼人 ID 列表
    dead_wolves: list[str]            # 已死亡狼人
    
    # 战术分配 (关键！)
    role_assignments: dict[str, str]  # wolf_id → 战术角色
    # 可选值: "lead_bluffer" (悍跳狼), "deep_cover" (倒钩狼), 
    #        "vote_pusher" (冲票狼), "silent" (深水狼)
    
    # 协调状态
    agreed_kill_target: str | None    # 今夜协商的刀人目标
    agreed_narrative: str             # 协商的统一口径
    contradiction_risks: list[str]    # 狼队发言矛盾风险点
    
    # 战术切换信号
    tactic_phase: str                 # "infiltration" / "disruption" / "endgame"
```

#### 5.2 战术角色分配算法

在每局游戏开始时（Night 0 或首夜），狼队自动分配战术角色：

```python
def assign_wolf_tactics(wolves: list[Player], game_config: GameConfig) -> dict[str, str]:
    """根据狼人数量和角色自动分配战术角色"""
    n = len(wolves)
    
    if n == 2:
        # 标准局：一悍跳一深水
        return {
            wolves[0].id: "lead_bluffer",
            wolves[1].id: "deep_cover"
        }
    elif n == 3:
        # 三狼：悍跳 + 倒钩 + 冲票
        return {
            wolves[0].id: "lead_bluffer",
            wolves[1].id: "deep_cover",
            wolves[2].id: "vote_pusher"
        }
    elif n >= 4:
        # 多狼：增加深水狼
        assignments = {wolves[0].id: "lead_bluffer",
                       wolves[1].id: "deep_cover",
                       wolves[2].id: "vote_pusher"}
        for w in wolves[3:]:
            assignments[w.id] = "silent"
        return assignments
```

战术角色注入到每个狼人的 Think prompt 中：

```
[战术角色] 你是悍跳狼 (lead_bluffer)
你的任务: 在白天跳预言家身份，引导好人投票给非狼人目标
你的队友: P2 (倒钩狼, deep_cover), P5 (冲票狼, vote_pusher)
当前统一口径: "昨晚查验 P8 为狼人"
注意: 如果 P2 已被怀疑，切换为保护 P2 的发言策略
```

#### 5.3 狼队夜间协调 (无需 LLM 调用)

夜间刀人协商不额外调用 LLM（节省成本），使用规则 + 策略参数：

```python
def negotiate_wolf_kill(wolves: list[Player], state: GameState) -> str:
    """狼队夜间协商刀人目标 —— 确定性算法"""
    
    # 优先级 1: 已暴露的神职
    exposed_gods = [p for p in state.players 
                    if p.alive and p.role in KEY_VILLAGE 
                    and is_publicly_claimed(p, state)]
    if exposed_gods:
        return max(exposed_gods, key=lambda p: god_threat_score(p)).id
    
    # 优先级 2: 高信息量玩家 (发言逻辑强、投票准的)
    high_info = [p for p in state.players 
                 if p.alive and p.alignment == VILLAGE
                 and information_score(p, state) > 0.6]
    if high_info:
        return max(high_info, key=lambda p: information_score(p)).id
    
    # 优先级 3: 随机好人 (制造混乱)
    alive_villagers = [p for p in state.players 
                       if p.alive and p.alignment == VILLAGE]
    return random.choice(alive_villagers).id
```

#### 5.4 发言矛盾检测 (防内讧)

在 Pipeline Act 阶段，每个狼人发言前注入队友的"计划发言摘要"：

```python
def build_wolf_coordination_context(wolf: Player, team_view: WolfTeamView) -> str:
    """构建狼队协调上下文 —— 防止发言互相矛盾"""
    context = f"""
[狼队协调]
你的战术角色: {team_view.role_assignments[wolf.id]}
队友计划发言摘要:
"""
    for mate_id, tactic in team_view.role_assignments.items():
        if mate_id != wolf.id:
            mate = get_player(mate_id)
            if tactic == "lead_bluffer":
                context += f"  - {mate.name} (悍跳狼): 将声称自己是预言家，查验目标待定\n"
            elif tactic == "deep_cover":
                context += f"  - {mate.name} (倒钩狼): 将跟随好人投票，发言低调\n"
            elif tactic == "vote_pusher":
                context += f"  - {mate.name} (冲票狼): 将积极归票，推动投票节奏\n"
    
    context += "\n注意: 你的发言不要与上述队友的计划产生明显矛盾。"
    return context
```

---

<a name="g6"></a>
## G6: 容错方向修正

### 问题

当前文档中容错链写为 `Heuristic → LLMAgent → CognitiveAgent`，方向反了。

### 修正

改为正确的降级方向：

```
CognitiveAgent (主路径, 最智能)
    ↓ 失败 (API 超时 / 返回非法动作 / JSON 解析失败)
LLMAgent (降级, 简化 prompt / 少 token)
    ↓ 仍失败
HeuristicAgent (最终兜底, 规则驱动, 零 LLM 依赖)
```

在 `agent.py` 中的实现：

```python
async def _decide_with_fallback(self, state: GameState, action_type: str) -> Decision:
    """三级容错降级链"""
    try:
        return await self._decide_cognitive(state, action_type)
    except (APIError, ValidationError, JSONDecodeError) as e:
        logger.warning(f"CognitiveAgent failed: {e}, falling back to LLMAgent")
        try:
            return await self._decide_llm_baseline(state, action_type)
        except Exception as e2:
            logger.error(f"LLMAgent failed: {e2}, falling back to Heuristic")
            return self._decide_heuristic(state, action_type)
```

---

<a name="g7"></a>
## G7: 评测系统防自评 —— Golden Cases + 人工校准

### 问题

LLM Judge 评价 LLM Agent 可能陷入"自评自嗨"——同样的模型盲区同时影响决策和评估。评委可能质疑可靠性。

### 工业界参考

| 方法 | 来源 | 要点 |
|------|------|------|
| **Noisy but Valid** | ICLR 2026, Feng et al. | 用小型人工标注校准集估计 Judge 的 TPR/FPR，在统计假设检验框架下控制误判率 |
| **No-Knowledge Alarms** | Corrada-Emmanuel, Sep 2025 | 用多 Judge 逻辑一致性检测错位，**零假阳性**，不需要 ground truth |
| **Policy Invariance Score** | Weng et al., May 2026 | 改写评估 prompt 但不改变语义，如果结论翻转说明 Judge 不可靠 |
| **Zalando Postmortem Pipeline** | Zalando 2025 | 初期 100% 人工 curation → 成熟后 10-20% 抽查；每条结论标注证据链完整性 |

### 狼人杀方案设计

#### 7.1 Golden Cases 校准集

手工构造 20 个"明确对/错"的决策案例作为校准基准：

```python
GOLDEN_CASES = [
    {
        "id": "GC001",
        "scenario": "预言家首夜查验狼人，第二天白天",
        "decision": "vote P8 (查验出的狼人)",
        "human_label": "correct",
        "confidence": 1.0,   # 确定性答案
        "rationale": "查验结果是最强信号，投票给查验出的狼人是严格正确的"
    },
    {
        "id": "GC002", 
        "scenario": "女巫首夜救人，救了自刀狼",
        "decision": "use_antidote on P3",
        "human_label": "acceptable",  # 不是错误，但在反事实中不是最优
        "confidence": 0.8,
        "rationale": "首夜救人标准策略，无法预知 P3 是自刀狼。救人是合理的，不能算失误。"
    },
    {
        "id": "GC003",
        "scenario": "猎人被投票出局，开枪带走已明跳的预言家",
        "decision": "shoot P1 (预言家)",
        "human_label": "incorrect",
        "confidence": 1.0,
        "rationale": "猎人应带走在投票中推他的狼人或可疑玩家，带明预言家是明显失误"
    },
    # ... 共 20 个
]
```

#### 7.2 LLM Judge 校准流程

```python
def calibrate_judge_panel(judge_panel: LLMJudgePanel, golden_cases: list[dict]) -> JudgeCalibration:
    """用 Golden Cases 估计 Judge Panel 的 TPR/FPR"""
    tp = fp = tn = fn = 0
    
    for case in golden_cases:
        llm_verdict = judge_panel.evaluate(case["scenario"], case["decision"])
        human_verdict = case["human_label"]
        
        if human_verdict in ("correct", "acceptable") and llm_verdict.is_correct:
            tp += 1
        elif human_verdict in ("correct", "acceptable") and not llm_verdict.is_correct:
            fn += 1
        elif human_verdict == "incorrect" and llm_verdict.is_correct:
            fp += 1
        elif human_verdict == "incorrect" and not llm_verdict.is_correct:
            tn += 1
    
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    
    return JudgeCalibration(tpr=tpr, fpr=fpr, sample_size=len(golden_cases))
```

#### 7.3 评测三层结构 (已部分实现，需显式化)

```
Level 1: 确定性规则 (100% 可靠)
  ├── 胜负、非法行动、投票结果
  ├── 技能效果、死亡序列
  └── 来源: engine log，零 LLM 依赖

Level 2: 半结构化指标 (80-95% 可靠)
  ├── 发言一致性、投票贡献、技能收益
  ├── 身份暴露风险、阵营协作贡献
  └── 来源: 规则引擎 + 统计，少量 LLM 辅助

Level 3: LLM 裁判 (需校准)
  ├── 策略质量、发言说服力、时机判断
  ├── 多法官聚合 + Critic 轮
  └── 来源: LLMJudgePanel，附带 TPR/FPR 校准值
```

#### 7.4 在评测报告中展示校准

```markdown
## LLM Judge 可靠性声明

| 指标 | 值 | 说明 |
|------|-----|------|
| TPR (True Positive Rate) | 0.87 | 87% 的好决策被正确识别 |
| FPR (False Positive Rate) | 0.09 | 9% 的差决策被误判为好 |
| 校准样本量 | 20 | Golden Cases 数量 |
| 标注者 | 1 人 | 人类专家标注 |
| Judge 一致性 | 0.83 | 3 法官的平均 agreement |

注意: 以上数值基于 20 个 Golden Cases 估计，置信区间较宽。
随校准样本增加，估计精度会提升。
```

---

<a name="g8"></a>
## G8: 检索指标可解释性

### 问题

当前文档只说 `NDCG@5 = 0.942`，没有说明测试集规模、标注方式、对比基准，容易被追问。

### 工业界参考

BEIR 基准 + RAGAs 评估框架是 2025 年行业标准。核心原则：
- 必须报告**多个指标** (NDCG, Recall, MRR) 而非单一数字
- 必须与**基线和消融**对比
- 必须说明**测试集规模和来源**
- 必须区分**检索质量**和**端到端效果**

### 方案设计

#### 检索评测报告模板

```markdown
## 检索系统评测

### 测试集
- Query 数量: 120 条
- Query 来源: 20 局真实对局中 Agent 实际发出的检索请求 (去重)
- Relevance 标注: 1 人手动标注，每条 query 标注 3-8 个相关文档
- 知识库规模: 486 条 StrategyKnowledgeDoc

### 结果

| 方法 | NDCG@5 | Recall@5 | MRR | P@5 | 索引延迟 | 检索延迟 |
|------|:------:|:--------:|:---:|:---:|:--------:|:--------:|
| TF-IDF (baseline) | 0.71 | 0.68 | 0.62 | 0.58 | <1ms | 12ms |
| BM25 | 0.78 | 0.74 | 0.70 | 0.65 | <1ms | 15ms |
| BGE-M3 (dense only) | 0.89 | 0.86 | 0.82 | 0.79 | 45ms | 180ms |
| **BM25 + BGE-M3 RRF** | **0.942** | **0.91** | **0.88** | **0.85** | 45ms | 195ms |

### 消融分析

| 变体 | NDCG@5 | 变化 |
|------|:------:|:----:|
| 完整 RRF (k=60) | 0.942 | — |
| RRF k=30 | 0.931 | -0.011 |
| RRF k=120 | 0.943 | +0.001 (边际收益递减) |
| 无 BGE-M3 (仅 BM25) | 0.780 | -0.162 |
| 无 BM25 (仅 BGE-M3) | 0.890 | -0.052 |

### 结论
- BM25 + BGE-M3 RRF 是最优组合，在两个方向上互补
- BM25 捕获关键词匹配 (角色名、技能名)，BGE-M3 捕获语义相似 (策略描述)
- RRF k=60 是 sweet spot，更大 k 值收益递减
```

#### 持续监控

在每次 Knowledge Store 更新后（新增/修改 >10 条知识），自动重跑检索评测：

```python
def retrieval_regression_test(new_docs: list[KnowledgeDoc]) -> bool:
    """知识库更新后检查检索质量是否退化"""
    baseline_ndcg = 0.942
    new_ndcg = run_retrieval_eval(test_queries, knowledge_store + new_docs)
    
    if new_ndcg < baseline_ndcg - 0.03:
        logger.warning(f"Retrieval NDCG degraded: {baseline_ndcg} → {new_ndcg}")
        return False
    return True
```

---

<a name="g9"></a>
## G9: 规则边界测试

### 问题

狼人杀规则细节多（平票处理、女巫同夜救毒、守卫连守、猎人被毒能否开枪、结算顺序等），任何一个细节出错都会被扣分。

### 工业界参考

| 方法 | 来源 | 要点 |
|------|------|------|
| **行为模型测试** | TestFlows (Super Mario case) | 用因果属性（"如果 X 发生，必有合法原因 Y"）替代前向预测测试 |
| **Projected State Machine Coverage** | Hartman & Nagin, ISSTA 2002 | 对 FSM 变量子集定义覆盖准则，用模型检查器自动生成测试 |
| **MC/DC 覆盖** | ProB Handbook, DO-178C | 对每个 guard 条件确保存在 toggle 它的测试用例 |
| **组合测试** | 学术共识 | 对独立参数用 pairwise/t-way 组合而非全排列 |

### 狼人杀方案设计

#### 9.1 边界测试清单

按 Phase × 角色 × 边界条件三维组织：

```python
RULE_EDGE_CASES = [
    # === 投票边界 ===
    {"id": "E01", "phase": "VOTE", "condition": "平票 (4v4)", 
     "expected": "无人出局 或 平票PK", "rule_ref": "标准规则"},
    {"id": "E02", "phase": "VOTE", "condition": "平票PK后再次平票",
     "expected": "无人出局", "rule_ref": "标准规则"},
    {"id": "E03", "phase": "VOTE", "condition": "警长票权重 1.5 打破平票",
     "expected": "警长票多的一方出局", "rule_ref": "警徽规则"},
    
    # === 女巫边界 ===
    {"id": "E04", "phase": "NIGHT_WITCH", "condition": "同夜使用救药+毒药",
     "expected": "取决于规则: 允许 或 只允许用一种", "rule_ref": "女巫规则变体"},
    {"id": "E05", "phase": "NIGHT_WITCH", "condition": "救药已用, 再次使用",
     "expected": "非法操作, 救药只有一瓶", "rule_ref": "女巫标准规则"},
    
    # === 守卫边界 ===
    {"id": "E06", "phase": "NIGHT_GUARD", "condition": "连续两晚守同一人",
     "expected": "取决于规则: 禁止 或 允许但无效", "rule_ref": "守卫规则变体"},
    {"id": "E07", "phase": "NIGHT_GUARD", "condition": "守卫守人被女巫同时救",
     "expected": "同守同救 → 死亡 (取决于规则)", "rule_ref": "结算顺序"},
    
    # === 猎人边界 ===
    {"id": "E08", "phase": "HUNTER_SHOOT", "condition": "猎人中刀 (非投票出局)",
     "expected": "可以开枪", "rule_ref": "标准规则"},
    {"id": "E09", "phase": "HUNTER_SHOOT", "condition": "猎人中刀被女巫救",
     "expected": "不开枪 (未死亡)", "rule_ref": "结算顺序"},
    {"id": "E10", "phase": "HUNTER_SHOOT", "condition": "猎人被投票出局, 被毒",
     "expected": "取决于规则: 被毒不能开枪 (常见)", "rule_ref": "猎人规则变体"},
    
    # === 死亡与结算顺序 ===
    {"id": "E11", "phase": "NIGHT_RESOLVE", 
     "condition": "狼刀P1 + 女巫救P1 + 守卫守P1 + 女巫毒P2",
     "expected": "结算顺序: 守卫守→狼刀→女巫救→女巫毒", "rule_ref": "结算顺序"},
    {"id": "E12", "phase": "GAME_END", 
     "condition": "最后一天狼人=村民数",
     "expected": "狼人胜利 (狼刀领先)", "rule_ref": "终局条件"},
    
    # === 死亡玩家边界 ===
    {"id": "E13", "phase": "DAY_SPEECH", "condition": "死亡玩家发言",
     "expected": "可以发言 (遗言) 或 不可发言 (取决于规则)", "rule_ref": "遗言规则"},
    {"id": "E14", "phase": "DAY_VOTE", "condition": "死亡玩家投票",
     "expected": "不可投票", "rule_ref": "标准规则"},
    
    # === 信息隔离边界 ===
    {"id": "E15", "phase": "NIGHT_WOLF", "condition": "狼人死后还能参与狼队讨论",
     "expected": "不可 (已死亡)", "rule_ref": "信息隔离"},
]
```

#### 9.2 基于属性的测试框架

参考 TestFlows 的因果属性模式，用 Python 实现：

```python
import pytest
from hypothesis import given, strategies as st, settings

class TestWerewolfRules:
    """狼人杀规则边界属性测试"""
    
    @given(
        num_players=st.integers(min_value=6, max_value=12),
        witch_alive=st.booleans(),
        witch_has_antidote=st.booleans(),
        witch_has_poison=st.booleans(),
    )
    @settings(max_examples=200)
    def test_witch_cannot_use_unavailable_potion(self, num_players, witch_alive, 
                                                   witch_has_antidote, witch_has_poison):
        """属性: 女巫不能使用已消耗的药水"""
        state = setup_game(num_players, roles=["Witch", "Werewolf", "Villager"])
        witch = get_player(state, role="Witch")
        
        if not witch_has_antidote:
            state = mark_antidote_used(state, witch.id)
        if not witch_has_poison:
            state = mark_poison_used(state, witch.id)
        
        actions = get_legal_actions(state, witch.id, Phase.NIGHT_WITCH)
        
        if not witch_has_antidote:
            assert "use_antidote" not in [a.type for a in actions]
        if not witch_has_poison:
            assert "use_poison" not in [a.type for a in actions]
    
    @given(
        death_cause=st.sampled_from(["vote", "wolf_kill", "poison", "guard_save"]),
        hunter_alive=st.booleans(),
    )
    def test_hunter_shoot_only_when_dying(self, death_cause, hunter_alive):
        """属性: 猎人只在死亡时触发开枪 (且不是被毒)"""
        state = setup_game(roles=["Hunter", "Werewolf", "Villager"])
        hunter = get_player(state, role="Hunter")
        
        state = apply_death(state, hunter.id, cause=death_cause)
        
        can_shoot = "hunter_shoot" in get_legal_actions(state, hunter.id).types
        
        if death_cause == "poison":
            assert not can_shoot, "猎人被毒不能开枪"
        else:
            assert can_shoot == (not hunter_alive), "猎人只在死亡时能开枪"
    
    def test_dead_player_cannot_vote(self):
        """P3: 死亡玩家不能投票 - 确定性测试"""
        state = setup_game(roles=["Villager", "Werewolf"])
        dead_player = state.players[0]
        state = kill_player(state, dead_player.id)
        
        legal_actions = get_legal_actions(state, dead_player.id, Phase.DAY_VOTE)
        assert "vote" not in [a.type for a in legal_actions]
```

#### 9.3 覆盖追踪

```python
# 在测试报告中追踪每条规则覆盖
RULE_COVERAGE = {
    "vote_edge_cases": {"total": 3, "tested": 3, "tests": ["E01", "E02", "E03"]},
    "witch_edge_cases": {"total": 2, "tested": 2, "tests": ["E04", "E05"]},
    "guard_edge_cases": {"total": 2, "tested": 2, "tests": ["E06", "E07"]},
    "hunter_edge_cases": {"total": 3, "tested": 3, "tests": ["E08", "E09", "E10"]},
    "resolution_order": {"total": 1, "tested": 1, "tests": ["E11"]},
    "endgame_conditions": {"total": 1, "tested": 1, "tests": ["E12"]},
    "dead_player_rules": {"total": 2, "tested": 2, "tests": ["E13", "E14"]},
    "info_isolation": {"total": 1, "tested": 1, "tests": ["E15"]},
}
# 报告: 15/15 规则边界覆盖, 100%
```

---

<a name="g10"></a>
## G10: 监控日志产品化

### 问题

当前日志散落在各处，缺少统一的 AgentDecision 级别结构化日志。评委想知道"你怎么知道系统在正常运行"时，需要能拿出一份监控面板。

### 工业界参考

SRE 和 LLMOps 的标准做法是**结构化日志 + 关键指标仪表盘**。Harness AI SRE、Rootly 等工具的标准字段：prompt_hash、model_name、token_in/out、latency_ms、validation_error_count、fallback_reason。

### 方案设计

#### 10.1 AgentDecision 日志 Schema

扩展现有 `AgentDecision` 模型：

```python
class AgentDecisionLog(Base):
    __tablename__ = "agent_decision_logs"
    
    # 基础标识
    id: str = primary_key
    game_id: str; agent_id: str; day: int; phase: str; action_type: str
    
    # 决策内容
    chosen_action: str
    confidence: float
    rationale: str  # ≤100 chars
    
    # 模型与性能
    model_name: str; provider: str
    token_in: int; token_out: int
    latency_ms: int; cost_usd: float
    
    # 容错
    validation_errors: int = 0
    fallback_used: bool = False
    fallback_reason: str | None = None
    
    # 信息隔离审计
    visibility_scope_hash: str  # SHA256 of what the agent could see
    
    # RAG 追踪
    retrieved_doc_ids: list[str] = []
    strategy_memory_snapshot: dict = {}
    
    # 复现
    prompt_hash: str
    agent_version: str
    random_seed: int
```

#### 10.2 对局级别监控仪表盘

```python
# 每局结束后自动生成
@dataclass
class GameHealthReport:
    game_id: str
    # 容错健康度
    total_decisions: int
    fallback_count: int
    fallback_rate: float          # 告警阈值: >10%
    validation_error_rate: float  # 告警阈值: >5%
    
    # LLM 调用健康度
    avg_latency_ms: float
    p95_latency_ms: float         # 告警阈值: >5000ms
    total_cost_usd: float
    avg_confidence: float
    
    # 信息隔离健康度
    isolation_violations: int     # 告警阈值: >0
    visibility_hash_collisions: int
    
    # RAG 健康度
    avg_retrieved_docs: float
    zero_retrieval_rate: float    # 告警阈值: >30%
    
    def is_healthy(self) -> bool:
        return (self.fallback_rate < 0.10 
                and self.validation_error_rate < 0.05
                and self.isolation_violations == 0
                and self.p95_latency_ms < 5000)
```

---

<a name="g11"></a>
## G11: 主线收束

### 问题

当前模块列表太长（CognitiveAgent, RAG, MBTI, BeliefTracker, Reflector, Track B, Track C, DreamJob, Tournament, LLM Judge, SVG, PostgreSQL），评委抓不住主线。

### 方案

将项目叙事收束为一句话 + 三个关键词：

> **我们做了一个 AI 狼人杀多智能体系统，不只会玩，还能复盘每个关键决策，通过反事实评估定位 bad case，并把复盘知识回流到下一代 Agent。**

三个关键词：
1. **玩** (Play) — CognitiveAgent + 角色策略 + 狼队协作
2. **评** (Evaluate) — 三级联评分 + 反事实推演 + LLM Judge 校准
3. **进化** (Evolve) — 策略知识回流 + 可信度分层 + A/B 验证

在文档和展示中，所有模块都归类到这三个关键词下：

```
玩 (Play)
├── CognitiveAgent (Observe-Think-Act)
├── 角色策略卡 (RoleStrategyCard)
├── 狼队协作 (WolfTeamView)
├── 策略检索 (BM25 + BGE-M3 RRF)
└── BeliefTracker + StrategyMemory

评 (Evaluate)
├── 三级联评分 (Tier 1/2/3)
├── 反事实分析 (10 种方法, 13 种标签)
├── LLM Judge Panel (3 judges + Critic + Golden Cases 校准)
├── PublishedReviewDocument
└── 信息隔离审计

进化 (Evolve)
├── 策略知识库 (L0-L4 可信度分层)
├── 矛盾检测 + 回验 + 衰减
├── A/B Tournament
└── 多维度 Leaderboard
```

---

<a name="g12"></a>
## G12: Leaderboard 多维度化

### 问题

当前 Leaderboard 只有胜负统计，不足以展示 Agent 能力的多维度差异。

### 工业界参考

2025 年 HAL (Princeton) 和 Ziganshin 的标准做法：
- **Pareto 前沿**：准确率 vs 成本
- **8 维度评估卡**：校准度、鲁棒性、目标对齐、不确定性处理、公平性、可解释性、适应性、资源效率
- **Bradley-Terry 批量 MLE**：替代 Elo，避免排序依赖
- **置信区间**：bootstrap 估计

### 方案设计

```python
@dataclass
class LeaderboardEntry:
    """多维度 Agent 评估条目"""
    agent_version: str
    model_provider: str
    
    # 基础指标
    total_games: int
    win_rate: float; win_rate_ci: tuple[float, float]  # 95% CI
    
    # 角色维度
    village_win_rate: float     # 拿好人时的胜率
    wolf_win_rate: float        # 拿狼人时的胜率
    seer_accuracy: float        # 预言家查验准确率
    witch_efficiency: float     # 女巫技能效率 (救对+毒对)/总用药
    hunter_accuracy: float      # 猎人开枪准确率
    guard_efficiency: float     # 守卫守护准确率
    
    # 决策质量
    avg_decision_score: float         # PerStepScorer 平均分
    avg_correctness: float            # 决策正确性
    avg_reasoning_quality: float      # 推理质量
    bad_case_rate: float              # bad case 比例
    
    # 社会维度
    vote_contribution: float          # 投票对阵营的贡献度
    info_contribution: float          # 信息释放贡献度
    coordination_score: float         # 阵营协作得分
    
    # 效率维度
    avg_cost_per_game: float          # USD
    avg_latency_per_decision: float   # ms
    fallback_rate: float
    
    # 进化维度
    improvement_vs_baseline: float    # 相对基线的提升
    knowledge_utilization: float      # 策略知识利用率
```

#### 排行榜展示格式

```markdown
| 版本 | 胜率 | 好人胜率 | 狼人胜率 | 决策分 | BadCase | 成本/局 | 进化 |
|------|:---:|:-------:|:-------:|:-----:|:-------:|:------:|:---:|
| cognitive_v3 | 62%±4 | 58% | 67% | 0.73 | 12% | $0.18 | +8% |
| cognitive_v2 | 57%±5 | 53% | 61% | 0.68 | 18% | $0.21 | +5% |
| cognitive_v1 | 54%±5 | 50% | 58% | 0.64 | 22% | $0.25 | — |
| llm_baseline | 48%±6 | 44% | 52% | 0.58 | 30% | $0.15 | — |
| heuristic | 42%±3 | 38% | 46% | 0.50 | 35% | $0.00 | — |
```

---

<a name="g13"></a>
## G13: MBTI 复盘重新定位

### 问题

16 种 MBTI 复盘角度容易被认为花哨、包装性功能，压过真正的技术亮点。

### 方案

重新定位为：

> **多风格复盘视角 (Multi-Perspective Reflection)**，用于丰富 Agent Profile 多样性，**不是核心评分依据**。

具体措施：
1. MBTI 复盘输出统一标记为 `L4_speculative`（不进入检索索引）
2. 所有文档和展示中，MBTI 的篇幅不超过总内容的 5%
3. 在评测报告中明确声明："MBTI 视角用于丰富 Agent 行为多样性，不计入决策质量评分"
4. Reflector 的输出增加 `perspective_type: Literal["strategic", "mbti_styled"]` 字段，strategic 视角进入 Track B 评测，mbti_styled 视角仅用于 Agent profile 迭代

---

<a name="g14"></a>
## G14: Track B/C 主次明确化

### 问题

当前架构同时覆盖 Track B 和 Track C，展示时显得分散。

### 方案

**主赛道：评测 + 复盘 (Track B)**

所有核心模块（CounterfactualAnalyzer, PerStepScorer, LLMJudgePanel, PublishedReviewDocument, Leaderboard）都归入 Track B。

**加分亮点：轻量自进化 (Track C-lite)**

将"策略知识回流"定位为 Track B 的自然延伸，而非独立的 Track C：

> "我们的评测系统不只告诉你'哪里错了'，还会把发现沉淀为策略知识，在下一局被检索使用。这形成了一个轻量的自进化闭环——但我们会标注每条知识的可信度，确保不可靠的推论不会污染 Agent 决策。"

关键：**不声称实现了完整的"通用 Agent 自修改"能力**。只声称"评测驱动的策略知识迭代"。

---

<a name="g15"></a>
## G15: 知识可信度与入库纠错 —— 复盘不一定对

### 问题

当前架构中，Reflector 和 CounterfactualAnalyzer 的输出被直接作为"知识"写入 StrategyKnowledgeDoc → PostgreSQL → BM25/BGE-M3 检索回流给下一局 Agent。这条链路存在一个根本性的认识论缺陷：

> **如果复盘本身的结论就是错的，那么"知识回流"就是在放大错误。**

这个问题与 RLHF 中奖励模型过度优化 (Goodhart's Law) 同源——当代理指标 (LLM Judge 评分) 和真实目标 (Agent 实际能力提升) 脱节时，优化代理指标反而会伤害真实目标。

狼人杀比围棋/象棋更难处理这个问题：

| 对比维度 | 围棋/AlphaZero | 狼人杀 |
|----------|:---:|:---:|
| 终局信号质量 | 高 (胜负明确反映棋力) | 低 (随机因素多，胜负≠决策质量) |
| 单步评估可验证性 | 高 (可通过后续落子回验) | 低 (反事实世界从未发生) |
| 策略相互依赖 | 低 (对手策略相对稳定) | 高 (最优响应取决于他人策略) |
| 评估者独立性 | 完全独立 (终局胜负) | 不独立 (同一 LLM 同时做决策和评估) |

### 工业界参考

| 方法 | 来源 | 要点 |
|------|------|------|
| **AlphaZero Self-Play** | Silver et al., Nature 2017 | 只用终局胜负 z∈{+1,-1} 作为唯一 ground truth，不评价单步决策质量，通过大规模统计 (490 万局) 让信号浮现 |
| **Noisy but Valid** | Feng et al., ICLR 2026 | 用小型人工标注校准集估计 Judge 的 TPR/FPR，在统计假设检验框架下控制误判率；量化 "Oracle Gap" |
| **No-Knowledge Alarms** | Corrada-Emmanuel, Sep 2025 | 多 Judge 逻辑一致性检测错位，**零假阳性**，不需要 ground truth，形式化为整数线性规划 |
| **Zalando Postmortem Pipeline** | Zalando 2025 | 初期 100% 人工 curation (upvote/downvote) → 成熟后 10-20% 随机抽查；每条结论标注"确证/高度可能/推测/待验证" |
| **Reward Overoptimization** | 多篇 2024-2025 | Goodhart's Law + KL 散度正则化 + 解耦奖励 (ODIN) + 集成奖励模型；灾难性 Goodhart 下 KL 正则化也无效 |
| **SRE Confidence Scoring** | Rootly, OperatorMesh 2025 | 诊断置信度 ≠ 修复置信度；<0.5 强制人工审核；多数据源交叉验证提升置信度 |

### 狼人杀方案设计

#### 15.1 Ground Truth 五级分层

不是"不存知识"，而是**标注每条知识的可信度等级，按等级决定使用方式**：

| 层级 | 名称 | 定义 | 狼人杀示例 | 存储方式 | 检索权限 |
|:---:|------|------|------|----------|----------|
| **L0** | 可验证事实 | 由引擎日志直接确认，无需推理 | "P3 在第 2 天投票给了 P5"、"狼队第 1 夜刀了 P7" | 标记 `source=engine_log` | 自由检索 |
| **L1** | 规则性结论 | L0 + 游戏规则逻辑演绎 | "P3 投票时已死亡，违反规则"、"守卫连续两晚守同一人" | 带规则推导链存储 | 自由检索 |
| **L2** | 统计性洞察 | 跨多局统计，有显著性支撑 | "女巫首夜救人概率 78%，其中 60% 救了真预言家 (n=50, p<0.01)" | 带 p 值+样本量，定期更新 | 检索 + 显示置信区间 |
| **L3** | 策略性判断 | LLM Judge/Reflector 给出的单局评价，有一定共识 | "女巫第 2 天不救 P5 是失误 (3/3 judges agree, conf=0.82)" | 带 judge_agreement + confidence + source_game_id | 检索 + 标注"AI 分析，可能不准确" |
| **L4** | 推测性洞察 | 低共识或缺乏证据的判断 | "P5 发言风格暗示其为狼人 (1/3 judges, conf=0.45)" | 仅存储为假设，标记 `experimental` | **不进入检索索引** |

#### 15.2 每条知识的置信度元数据

```python
@dataclass
class KnowledgeConfidence:
    """每条知识的可信度元数据 —— 写入前必须填充"""
    
    # 基础分层
    tier: Literal["L0_fact", "L1_rule", "L2_statistical", "L3_strategic", "L4_speculative"]
    
    # 信号来源
    source_type: Literal["engine_log", "rule_engine", "statistical_aggregator", 
                          "llm_judge", "reflector"]
    source_game_ids: list[str]        # 来自哪些对局 (可追溯)
    
    # L3/L4 专有字段
    judge_agreement: float | None     # 多法官一致性 0.0-1.0
    confidence_score: float | None    # LLM 自评置信度
    evidence_chain: list[str] | None  # 从事件到结论的推理步骤
    counterfactual_verified: bool     # 是否通过反事实验证
    
    # L2 专有字段
    sample_size: int | None           # 样本量
    p_value: float | None             # 统计显著性
    effect_size: float | None         # 效应量
    
    # 生命周期管理
    created_at: str = ""
    human_reviewed: bool = False
    human_verdict: Literal["confirmed", "rejected", "revised", "unreviewed"] = "unreviewed"
    
    # 运行中追踪
    times_retrieved: int = 0          # 被检索次数
    times_upvoted: int = 0            # 被后续对局"验证"的次数
    contradiction_count: int = 0      # 与其他知识矛盾的次数
    games_since_creation: int = 0     # 创建后经历的对局数
```

#### 15.3 检索过滤 —— "不可靠的知识不喂给 Agent"

```python
def retrieve_for_agent(query: str, role: str, top_k: int = 5) -> list[KnowledgeDoc]:
    """带可信度过滤的策略知识检索"""
    candidates = hybrid_search(query, top_k * 3)  # 多召回一些
    
    filtered = []
    for doc in candidates:
        kc = doc.confidence
        
        # L4 推测性知识 → 不检索
        if kc.tier == "L4_speculative":
            continue
        
        # L3 策略判断 → 只检索高共识 + 高置信度
        if kc.tier == "L3_strategic":
            if kc.judge_agreement and kc.judge_agreement < 0.67:
                continue  # 法官分歧大，不可靠
            if kc.confidence_score and kc.confidence_score < 0.7:
                continue  # LLM 自评低置信
            if kc.human_verdict == "rejected":
                continue  # 人工否决的
        
        # 矛盾次数过多 → 降低权重 (不直接排除，因为可能是旧知识过时)
        if kc.contradiction_count >= 3:
            doc.score *= 0.5
        
        # 长期未验证的 L3 → 降低权重
        if kc.tier == "L3_strategic" and kc.games_since_creation > 50:
            doc.score *= 0.7
        
        filtered.append(doc)
    
    return sorted(filtered, key=lambda d: d.score, reverse=True)[:top_k]
```

#### 15.4 三种自动纠错机制

**机制一：写入前矛盾检测**

新知识写入前，与已有知识做 pairwise 比较，检测逻辑冲突：

```python
def detect_contradiction(new_knowledge: KnowledgeDoc, 
                         existing_knowledge: KnowledgeDoc) -> bool:
    """用轻量 LLM 做 pairwise 矛盾检测"""
    prompt = f"""
    知识A: {new_knowledge.content}
    知识B: {existing_knowledge.content}
    
    这两条知识是否在逻辑上相互矛盾？只回答 YES 或 NO，并解释。
    
    注意：同一事实的不同表述不算矛盾。
    只有当一个断言的成立意味着另一个断言必须不成立时，才算矛盾。
    """
    result = light_llm(prompt)
    return result.startswith("YES")
```

冲突解决优先级：

```
L0/L1 事实 > L3/L4 推测    (可验证事实优先)
高共识 > 低共识            (3/3 judges > 1/3 judges)
新 > 旧                    (Agent 可能已进化)
高样本 > 低样本            (统计洞察 > 单局判断)
人工审核过 > 未审核        (人类判断优先)
无法自动解决 → 标记为 disputed，不进入检索，等待人工
```

**机制二：对局回验 (Back-testing)**

新对局结束时，用其结果反向验证已有知识：

```python
def backtest_knowledge(knowledge: KnowledgeDoc, new_game: GameState) -> KnowledgeVerdict:
    """在新对局中检验已有知识是否成立"""
    if knowledge.tier == "L3_strategic":
        # 检查：同样的策略建议在新对局中是否也被判定为"好的"
        # 如果支持该知识 → times_upvoted += 1
        # 如果与该知识矛盾 → contradiction_count += 1
        ...
    elif knowledge.tier == "L2_statistical":
        # 将新对局数据加入统计池，更新 p 值和效应量
        ...
    
    # 如果 contradiction_count 达到阈值，触发人工审核
    if knowledge.confidence.contradiction_count >= 5:
        trigger_human_review(knowledge)
```

**机制三：置信度衰减**

长期未被验证的知识自动降级：

```python
def decay_confidence(knowledge: KnowledgeDoc) -> None:
    """超过阈值未被验证的知识自动降级"""
    kc = knowledge.confidence
    
    if kc.tier == "L3_strategic":
        # 50 局后仍未被"验证"过的 L3 知识降级为 L4
        if kc.games_since_creation > 50 and kc.times_upvoted == 0:
            kc.tier = "L4_speculative"
            logger.info(f"Knowledge {knowledge.id} decayed: L3→L4 (unverified after 50 games)")
        
        # 被否决 3 次以上的 L3 知识降级
        if kc.contradiction_count >= 3 and kc.times_upvoted < kc.contradiction_count:
            kc.tier = "L4_speculative"
```

#### 15.5 与现有模块的对接

| 现有模块 | 改进后角色 | 产出层级 |
|----------|-----------|:---:|
| Engine log 事件流 | 直接写入 | L0 |
| `per_step_scorer.py` Tier 1 (deterministic) | 产出事实性结论 | L0/L1 |
| `per_step_scorer.py` Tier 2 (light LLM) | 产出策略判断 (单 judge) | L3 |
| `per_step_scorer.py` Tier 3 (heavy LLM) | 产出策略判断 (3 judges + agreement) | L3 |
| `llm_judge.py` LLMJudgePanel | 附带 judge_agreement 元数据 | L3 |
| `review.py` CounterfactualAnalyzer | 反事实标注 `counterfactual_verified` | L3 |
| `track_b.py` PublishedReviewDocument | 正式报告排除 L4 | L0-L3 |
| `reflect.py` Reflector (MBTI 多角度) | 标记为 speculative | L4 |
| `retrieval.py` | 增加 `retrieve_for_agent()` 可信度过滤 | — |

#### 15.6 核心理念

> **不假设复盘正确。分级存储，按可信度使用。**
>
> - AlphaZero 告诉我们：唯一不可争议的信号是**终局胜负**，所有中间评估都只是噪声中的统计估计。
> - SRE 实践告诉我们：**置信度分层 + 人工审核抽样**是 AI 辅助决策的工业标准——低置信度的自动结论必须有 human gate。
> - LLM-as-Judge 研究 (ICLR 2026) 告诉我们：多 Judge 共识 + 逻辑一致性检查可显著降低错误率，但不能消除——**必须保留 FPR 估计并对外披露**。
> - 狼人杀的特殊性告诉我们：胜负的信噪比远低于围棋，需要更多局的统计才能浮现真正的策略信号。
>
> 最终方案：**L0-L4 五级分层 + 检索过滤 + 矛盾检测 + 回验 + 衰减**。让知识在"被多局交叉验证"中逐步升级可信度，而不是一次性写入后永久信任。

---

<a name="roadmap"></a>
## 16. 实施路线图

### Phase 1: 基础修复 (1-2 天) — 立刻动手

| 优先级 | 改动 | 涉及文件 | 工作量 |
|:---:|------|------|:---:|
| P0 | KnowledgeConfidence 数据模型 + DB migration | `models.py`, migration | 小 |
| P0 | 检索过滤层 (L4 不检索, L3 低共识不检索) | `retrieval.py` | 小 |
| P0 | 容错方向修正 | `agent.py` | 小 |
| P1 | 角色策略卡 `RoleStrategyCard` 定义 | 新建 `strategies/` | 中 |
| P1 | 结构化 `DecisionTrace` Schema | `protocols/schemas.py` | 中 |
| P1 | 信息隔离 8 属性测试 | 新建 `tests/test_isolation.py` | 中 |

### Phase 2: 评测加固 (2-3 天)

| 优先级 | 改动 | 涉及文件 | 工作量 |
|:---:|------|------|:---:|
| P1 | Golden Cases 校准集 (20 条) | 新建 `eval/golden_cases.py` | 中 |
| P1 | LLM Judge 校准流程 (TPR/FPR 估计) | `eval/llm_judge.py` | 中 |
| P1 | 检索评测报告 (多指标 + 消融) | 新建 `eval/retrieval_eval.py` | 中 |
| P2 | 规则边界 15 条测试 + 属性测试框架 | 新建 `tests/test_rules.py` | 大 |
| P2 | 矛盾检测 + 写入前 pairwise 比较 | `eval/review.py` | 中 |

### Phase 3: Agent 增强 (2-3 天)

| 优先级 | 改动 | 涉及文件 | 工作量 |
|:---:|------|------|:---:|
| P2 | `WolfTeamView` + 战术角色分配 | `agents/cognitive/` | 中 |
| P2 | `StrategyMemory` 集成到 Memory | `agents/cognitive/memory.py` | 中 |
| P2 | Skill 协议 + 重构现有 6 角色 | `engine/roles/`, 新建 `engine/skill.py` | 大 |
| P3 | 多维度 Leaderboard Schema | `eval/leaderboard.py` | 中 |
| P3 | `AgentDecisionLog` + GameHealthReport | `db/models.py` | 中 |

### Phase 4: 文档与展示 (1-2 天)

| 优先级 | 改动 | 工作量 |
|:---:|------|:---:|
| P0 | 主线收束 — 所有文档统一"玩→评→进化"叙事 | 中 |
| P1 | 信息隔离测试报告 (`docs/information_isolation_tests.md`) | 中 |
| P1 | 角色策略差异文档 (`docs/role_strategy_playbook.md`) | 中 |
| P2 | Golden Cases 评测报告 | 小 |
| P2 | 检索评测报告 | 小 |
| P2 | MBTI 重新定位 (文档措辞修正) | 小 |
| P3 | 证据包整理 (`docs/` + `demo/` 目录) | 中 |

---

## 附录 A: 改进后的完整闭环架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PLAY (玩)                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐ │
│  │ Profile  │   │ Observer │   │ Pipeline │   │ CognitiveAgent   │ │
│  │ +RoleCard│──▶│+Belief   │──▶│ Observe  │──▶│ +WolfTeamView    │ │
│  │ +Strategy│   │ Tracker  │   │ Think    │   │ +StrategyMemory  │ │
│  │ Memory   │   │          │   │ Act      │   │ +Fallback        │ │
│  └──────────┘   └──────────┘   └──────────┘   └────────┬─────────┘ │
│                                                          │           │
│  ┌──────────────────────────────────────────────────────┘           │
│  │  Retrieval: BM25 + BGE-M3 RRF (NDCG@5=0.942)                    │
│  │  Filter: L4 not retrieved, L3 low-consensus filtered             │
│  └──────────────────────────────────────────────────────────────────│
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EVALUATE (评)                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────────┐│
│  │ Tier 1       │  │ Tier 2       │  │ Tier 3                      ││
│  │ Deterministic│─▶│ Light LLM    │─▶│ Heavy LLM (3 judges+Critic) ││
│  │ (L0/L1 facts)│  │ (single judge)│  │ + Golden Cases Calibration  ││
│  └──────────────┘  └──────────────┘  └──────────────┬──────────────┘│
│                                                      │               │
│  ┌──────────────────────────────────────────────────┘               │
│  │  CounterfactualAnalyzer (10 methods × 13 tags)                   │
│  │  PerStepScorer → DecisionScore (with confidence metadata)        │
│  │  PublishedReviewDocument (L4 excluded from formal report)        │
│  │  Multi-dim Leaderboard (10+ dimensions, 95% CI)                  │
│  │  Information Isolation Audit (8 properties verified)             │
│  └──────────────────────────────────────────────────────────────────│
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       EVOLVE (进化)                                  │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Knowledge Store (PostgreSQL)                                   │ │
│  │  ┌──────────┬──────────┬──────────┬──────────┬──────────┐     │ │
│  │  │ L0 Fact  │ L1 Rule  │ L2 Stats │ L3 Strat │ L4 Spec  │     │ │
│  │  │ ✅ free  │ ✅ free  │ ✅+CI    │ ⚠️filter │ 🚫block  │     │ │
│  │  └──────────┴──────────┴──────────┴──────────┴──────────┘     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Quality Control:                                               │ │
│  │  ├── Contradiction Detection (pairwise comparison on write)     │ │
│  │  ├── Back-testing (verify against new game outcomes)            │ │
│  │  ├── Confidence Decay (unverified → downgrade after N games)    │ │
│  │  └── Human Review Sampling (10-20% of L3, 100% of disputed)    │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## 附录 B: 研究来源

| 领域 | 关键来源 |
|------|----------|
| 角色策略编码 | MASMP (Qi et al., Oct 2025), Adaptive Command (Ma et al., 2025), PORTAL (Mar 2025) |
| 信息隔离验证 | Process Opacity Testing (Gruska & Ruiz, CSP 2019), SentinelAgent TLA+ (Apr 2026), Epistemic Temporal Logic (Finkbeiner et al., 2025) |
| 狼队多 Agent 协调 | MultiMind (Apr 2025), DVM (Jan 2025), RL-Instructed Discussion (Jin et al., 2024) |
| LLM Judge 校准 | Noisy but Valid (Feng et al., ICLR 2026), No-Knowledge Alarms (Corrada-Emmanuel, Sep 2025), Policy Invariance (Weng et al., May 2026) |
| RAG 评测 | BEIR benchmark, RAGAs framework, EvaRAG (2025), UDCG (2025) |
| 规则边界测试 | Behavior Model Testing (TestFlows), Projected State Machine Coverage (Hartman & Nagin, ISSTA 2002), ProB MC/DC |
| Leaderboard 设计 | HAL (Princeton, Oct 2025), Agent Evaluation Beyond Win-Rates (Ziganshin, Sep 2025), Cohere Bradley-Terry (2025) |
| 知识可信度 | AlphaZero self-play (Silver et al., Nature 2017), Zalando Postmortem Pipeline (2025), Reward Overoptimization/Goodhart's Law (2025) |
