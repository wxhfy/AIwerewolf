# AI狼人杀 — 多智能体协作与博弈需求规格（V1.3）

## 变更说明

V1.3 针对第二轮评审修复：
- 多智能体：似然函数校准基准、二阶信念更新规则、DD 策略冲突检测与角色分配子协议、Persona 全维度决策映射、信号博弈成本结构、怀疑度提取函数、协作评分更新规则、2步前瞻游戏树、反事实推理形式化
- 规则层：伤害矩阵补行、女巫双药同目标规则、守护/解药资源消耗声明、DEATH_ANNOUNCE 多死排序、自定义小规模平衡性
- 工程层：wss 强制、信念初始化、Persona 采样区间、降级模板兜底策略、CHECK 约束修正、scope 映射表、席位状态机补充

---

## 一、游戏规则引擎

### 1.1 角色系统（基础 6 角色，架构支持扩展至 60+）

| 角色 | 阵营 | 能力 | 使用限制 |
|------|------|------|----------|
| 村民 | 好人 | 无特殊能力，靠发言推理投票 | — |
| 狼人 | 狼人 | 夜晚击杀一人；内部可交流协商；自刀不推荐但技术上允许 | 每晚一次 |
| 预言家 | 好人 | 夜晚查验一人身份（好人/狼人）；**被刀当夜查验仍有效** | 每晚一次 |
| 女巫 | 好人 | 拥有一瓶解药和一瓶毒药；**每夜最多使用一瓶药**（两药不可同夜使用） | 解药仅首夜可自救；其余夜不可自救 |
| 猎人 | 好人 | 被投票出局/被狼刀时可开枪带走一人；被女巫毒杀不能开枪 | 一次 |
| 守卫 | 好人 | 夜晚守护一人不被**狼刀**；允许自守 | 不可连续两晚守同一人（含自己） |

**扩展角色**（已实现）：白痴、白狼王、狼美人、预言家学徒等。详见 `configs/rule_variant_standard.yaml`。

**伤害与防护交互矩阵**：

| 伤害来源 | 守卫守护 | 女巫解药 | 结果 | 资源消耗 |
|----------|----------|----------|------|----------|
| 狼刀 | ✓ | — | 玩家存活 | 守护消耗 |
| 狼刀 | — | ✓ | 玩家存活 | 解药消耗 |
| 狼刀 | ✓ | ✓ | 玩家死亡（同守同救 / 奶穿） | 守护+解药均消耗 |
| 狼刀 + 女巫毒 | ✓ | ✓ | 玩家死亡（毒药不受守护/解药影响） | 守护+解药+毒药均消耗 |
| 狼刀 + 女巫毒 | — | — | 玩家死亡（猎人按刀优先可开枪） | 毒药消耗 |
| 猎人子弹 | ✓ | — | 玩家死亡（子弹不可防护） | 守护消耗 |
| 女巫毒 | ✓ | — | 玩家死亡（毒药不可防护） | 守护+毒药均消耗 |

**猎人细节规则**：
- 被猎人开枪击杀的玩家不触发自身技能（防止连锁反应）
- 猎人开枪后立即判定胜负
- 同夜被刀+被毒：以"刀优先"判定（允许开枪），**毒药无论结果均被消耗**
- **夜晚猎人开枪仅在"猎人因狼刀实际死亡"时触发**（被解药救活不开枪）

### 1.2 游戏流程

```
WAITING → ROLE_ASSIGN → [NIGHT → DAY → VOTE]… → GAME_OVER

NIGHT 子阶段（守卫→并行角色行动→女巫→结算）：
  NIGHT_START → NIGHT_GUARD_ACTION（守卫/狼人/预言家并行）→ NIGHT_WITCH_ACTION
  → NIGHT_RESOLVE（结算死亡 & 猎人夜间开枪 & 胜负判定）

DAY 子阶段（仅第一天有警徽竞选）：
  DAY_START（公布死讯）→ DAY_BADGE_SIGNUP（警徽报名）→ DAY_BADGE_SPEECH（竞选发言）
  → DAY_BADGE_ELECTION（警徽投票）→ DAY_SPEECH（并行自由发言）
  → DAY_SHERIFF_CLOSING（警长总结）→ DAY_VOTE（放逐投票）
  → DAY_RESOLVE（结算投票 & 猎人白天开枪 & 胜负判定）

特殊阶段（事件触发）：
  DAY_PK_SPEECH / DAY_PK_VOTE（平票PK）
  DAY_LAST_WORDS（被放逐者遗言）
  BADGE_TRANSFER（警长出局时移交警徽）
  HUNTER_SHOOT（猎人死亡开枪）
  WHITE_WOLF_KING_BOOM（白狼王自爆）
  GAME_END

规则：夜晚所有行动视为同时发生。角色在夜晚死亡不影响其当晚行动的有效性。
     例：被狼刀的预言家仍可获得查验结果；被刀女巫仍可使用药品。

CHECK_WIN 触发时机（四处）：
  - 夜晚结算完成后（NIGHT_RESOLVE，含猎人夜间开枪后）
  - 投票淘汰后（DAY_RESOLVE）
  - 猎人白天开枪后（HUNTER_SHOOT）
  - 白狼王自爆后（WHITE_WOLF_KING_BOOM）
胜负一旦触发，立即中断当前阶段，进入 GAME_END。
```

### 1.3 角色分配算法

```
输入：玩家总数 N（6-18），固定模板或自定义
输出：角色分配

固定模板：
  - 6 人局：2狼 + 1预言 + 1女巫 + 2民
  - 9 人局：3狼 + 1预言 + 1女巫 + 1猎人 + 3民
  - 12 人局：4狼 + 1预言 + 1女巫 + 1猎人 + 1守卫 + 4民

自定义 N 人：
  规则：
  - 狼人数 = max(1, ceil(N * 0.3))，确保小规模局狼人比例 ≥ 30%
  - 神职数 = min(4, N - 狼人数 - 1)，按 预言家→女巫→猎人→守卫 优先级
  - 剩余 = 村民
  - 随机打乱后分配
  - 人类玩家与 AI 玩家统一随机分配角色，不区分

角色偏好：V1 不支持玩家偏好角色选择，后续版本规划。
```

### 1.4 胜负判定

| 条件 | 结果 |
|------|------|
| 存活狼人数 ≥ 存活好人数 | 狼人阵营获胜 |
| 所有狼人死亡 | 好人阵营获胜 |
| 最大轮次（20 个完整昼夜循环）达到 | 平局 |

---

## 二、游戏细节规则

### 2.1 发言顺序

- 发言阶段为并行进行：所有存活玩家同时生成发言内容（不按轮播，同时输出）
- 发言内容基于各自 PlayerView 独立生成，不依赖同轮其他玩家发言
- 发言阶段结束后进入警长总结（DAY_SHERIFF_CLOSING），仅警长发言
- 若需要多轮发言，通过第二天额外 DAY_SPEECH 阶段实现

### 2.2 投票平票处理

```
第一次投票平票：
  → 平票者进入 PK 发言（各 1 轮，发言顺序按座位号）
  → PK 投票（仅可投平票者）
  → PK 投票中猎人被出局同样触发白天开枪
  → 再次平票 → 无人出局，进入夜晚
全体弃权或 0 票 → 无人出局，进入夜晚
```

### 2.3 死亡玩家状态机

```
ALIVE → DEAD(遗言阶段，如适用) → SPECTATOR

死亡玩家：
  - 失去发言权、投票权、夜晚行动权
  - 可继续观看游戏并接收所有公开事件（广播）
  - 猎人死亡开枪仅在被刀/被票时触发一次
  - 客户端 UI 自动切换为观战模式

遗言规则：
  - 首个夜晚（第一轮）所有死亡玩家均有一次遗言机会，发言顺序按座位号
  - 被投票出局的玩家无遗言
  - 被猎人开枪击杀者无遗言
  - 遗言后转入 SPECTATOR 状态
```

### 2.4 狼人内部决策机制

```
狼人夜间协商 + 击杀流程：

1. WOLF_DISCUSS 阶段：
   - 所有存活狼人通过私密频道进行多轮对话
   - DD 协商协议（详见 3.4.1），含策略冲突检测与角色分配子协议
   - 平票时在平票目标中随机选择（含狼人自身，因允许自刀）

2. 协商结束后进入内部投票：
   - 每只狼提名一个击杀目标（或弃权）
   - 简单多数决 → 得票最多者为击杀目标
   - 投票窗口：讨论结束后 30s 收集期

3. 若仅剩 1 只狼存活：跳过 WOLF_DISCUSS，直接进入 WOLF_KILL

4. 超时无结果：随机选择一名存活非狼玩家
```

### 2.5 阶段时长与超时处理

| 阶段 | 默认时长 | 超时行为 |
|------|----------|----------|
| 守卫选择 | 20s | 本轮不守护 |
| 狼人讨论+击杀 | 60s | 随机选择非狼目标 |
| 预言家查验 | 20s | 本轮不查验 |
| 女巫行动 | 25s | 本轮不使用药品 |
| 猎人开枪（夜间/白天） | 20s | 随机选择一名存活玩家 |
| 每人发言 | 90s | 自动结束当前发言 |
| 投票 | 30s | 视为弃权 |
| PK 发言（每人） | 60s | 自动结束 |
| PK 投票 | 30s | 视为弃权 |
| 狼人内部投票收集 | 30s | 未投票狼人视为弃权 |

房主可配置全局时长倍率：x0.5（快速模式）/ x1（标准）/ x2（慢速模式）。

### 2.6 房主干预权限

- 手动提前结束当前阶段（跳过剩余时间）
- 暂停/恢复游戏（仅限非关键阶段）
- 将断线超时的人类玩家替换为 AI
- 将 AI 席位转让给观战/新加入的人类玩家

> 注意：房主干预和定时器到期同时发生时，游戏引擎加锁（asyncio.Lock 或 DB 行锁）防止竞态。

### 2.7 旁观者权限

| 权限项 | 规则 |
|--------|------|
| 可接收事件 | 仅公开广播事件（与村民信息视野相同） |
| 可发言/投票 | 否 |
| 旁观者聊天 | 独立频道，仅旁观者之间可见 |
| 上帝视角 | 仅在游戏结束后可用，展示所有私密信息 |
| 数量限制 | 硬上限 200 人/房间，房主可调低 |
| 防作弊 | 同 IP 不能同时作为玩家和旁观者在同一房间 |

---

## 三、多 Agent 系统

### 3.1 Agent 个体能力

```
Agent 实例 = 身份 + 记忆模块 + 信念模型(含二阶更新) + 策略人格(全维度映射) + 决策引擎(含游戏树搜索) + LLM 接口

┌──────────────────────────────────────────────┐
│              Agent 实例                       │
│                                              │
│  ① 记忆模块 (Memory)                          │
│     - 角色身份（自己知道）                     │
│     - 角色专属记录（查验/用药/守护/开枪）       │
│     - 所有公开对话历史                         │
│     - 所有公开事件（死亡/投票/淘汰）            │
│     - 私密对话（狼人频道）                     │
│     - 私人推理笔记                             │
│     - 协作记忆二维信任评分矩阵及其更新日志       │
│       trust(j) = (coop, decp)，含 last_update 时间│
│     V1 范围：单局有效，局结束清除               │
│                                              │
│  ② 信念模型 (Belief Model)                    │
│     一阶信念：P_i(role_k | player_j)           │
│       初始化（好人对任何非己玩家）：             │
│         均匀分布 + 基于角色分配概率的 Dirichlet 先验 │
│         (给定总人数，各角色出现概率已知)         │
│       初始化（狼人对已知队友）：P(队友, 狼)=1.0  │
│       初始化（预言家查验后）：硬更新为 1.0      │
│                                              │
│     一阶贝叶斯更新：                           │
│       P_i(role_k | E) ∝ P(E | role_k) × P_i(role_k)  │
│       似然 P(E | role_k) 由 LLM 估计 + 基准校准： │
│         calibrated_likelihood = (1-α) × llm_estimate │
│                                + α × heuristic_prior │
│         α = 0.3（校准权重），heuristic_prior 预设： │
│           好人的投票命中狼人概率 ≈ 0.35           │
│           狼人的投票命中好人概率 ≈ 0.55           │
│           预言家的查验结果准确率 ≈ 1.0             │
│         （详见 3.1.1 校准基准表）                │
│                                              │
│     二阶信念：P_i(P_j(role_k) = p)             │
│        语义：Agent i 对"Agent j 对 role_k 的信念"的分布 │
│        存储为 Beta 分布参数 α_ijk, β_ijk        │
│        期望值 E[P_j(role_k)] ≈ α/(α+β)        │
│        二阶更新规则（观测 j 的公开行为 a_j）：    │
│          α'_ijk = α_ijk + η × P(j 做 a_j | j 认为 role_k)│
│          β'_ijk = β_ijk + η × (1 - P(j 做 a_j | j 认为 role_k))│
│          η = 0.1（学习率），P(j做a|j认为role_k) 由 LLM 估计 │
│        （详见 3.1.2 二阶更新推导）               │
│                                              │
│  ③ 策略人格 (Persona) — 全维度量化+决策映射      │
│     Persona = (risk_tolerance, leadership_bias,│
│                deception_preference,              │
│                emotional_expressiveness,          │
│                logical_depth, coop_tendency)      │
│     每维度 ∈ [0, 1]                             │
│                                              │
│     角色约束区间（其余维度随机采样）：            │
│       狼人：deception_preference ∈ [0.6, 1.0]    │
│       预言家：leadership_bias ∈ [0.6, 1.0]       │
│       女巫：risk_tolerance ∈ [0.4, 0.8]           │
│       猎人：risk_tolerance ∈ [0.6, 1.0]           │
│       守卫：coop_tendency ∈ [0.5, 1.0]           │
│       村民：无约束，均匀分布                      │
│                                              │
│     全维度 → 决策参数映射：                      │
│       risk_tolerance → 行动激进系数 ra：          │
│         影响查验/击杀/投票的目标选择概率分布      │
│         ra = 0.5 + 0.5 × risk_tolerance          │
│       leadership_bias → 带票意愿系数 rl：         │
│         发言中主导议题的概率：rl × 发言权重       │
│       deception_preference → 伪装倾向系数 rd：    │
│         狼人选择高风险高收益策略(如跳预言家)的概率 │
│         好人用于检测伪装的敏感度 = rd × 阈值调节   │
│       emotional_expressiveness → 情感强度 re：    │
│         发言中情感词密度 = base + re × range      │
│       logical_depth → 推理深度系数 ld：           │
│         发言中推理链长度 = 1 + floor(ld × 4)     │
│         前瞻搜索深度 = 1 + floor(ld × 2)         │
│       coop_tendency → 从众系数 rc：               │
│         跟从多数人投票的概率系数                  │
│         信任他人发言的阈值 = 0.5 - 0.3 × rc       │
│                                              │
│  ④ 决策引擎 (Decision Engine)                  │
│     输入：(Memory, Belief, Persona, GameState) │
│     输出：结构化行动决策                         │
│     流程：                                     │
│       1. 可选行动枚举（基于 GameState + Role）   │
│       2. 对每行动计算评估值：                   │
│          value(a) = expected_benefit(a, Belief, Memory) │
│                   - risk_cost(a, Persona)        │
│          Benefit 基于信念模型估计收益             │
│          Risk 基于 Persona 参数调节               │
│       3. 协作记忆加权：                          │
│          若行动 a 涉及信任某玩家 j：              │
│          调节系数 w_j = 1 + (coop(j)-0.5) × rc    │
│          若行动 a 涉及怀疑某玩家 j：             │
│          调节系数 w_j = 1 + (decp(j)-0.5) × ri    │
│          (ri = 1 - rc)                           │
│       4. 选择 value(a) 最高的行动                │
│       5. 生成自然语言理由 → 输出决策              │
│     规划能力（游戏树搜索，详见 3.1.3 节）         │
│     容错：LLM 失败 → 降级为角色规则策略          │
│                                              │
│  ⑤ LLM 接口                                   │
│     - 独立模型配置（每 Agent 可不同）             │
│     - 异步调用，超时处理                        │
│     - 结构化输出 JSON Schema 约束 + 校验         │
└──────────────────────────────────────────────┘
```

### 3.1.1 似然函数校准基准表

| 场景 | Heuristic Prior P(E\|role) | 说明 |
|------|---------------------------|------|
| 狼人投中好人 | 0.55 | 狼人有意避开队友 |
| 好人投中狼人 | 0.35 | 好人推理有一定命中率 |
| 好人投中好人 | 0.55 | 好人可能误投 |
| 狼人投中狼人 | 0.10 | 狼人通常不投队友 |
| 预言家查验结果 | 1.00 | 硬信息，无噪声 |
| 玩家弃权 | 0.05 | 小概率弃权 |
| 发言与投票行为一致 | 0.70 | 多数玩家言行一致 |
| 发言与投票行为矛盾 | 0.15 | 偏离预期的小概率事件 |

`calibrated_likelihood = 0.7 × llm_estimate + 0.3 × heuristic_prior`

LLM 返回的 estimate 被校准权重约束在合理区间内，避免完全依赖 LLM 的不可控输出。

### 3.1.2 二阶信念更新规则（形式化）

```
给定：
  Agent i 观测到 Agent j 的公开行为 a_j（发言、投票、弃权等）
  i 的二阶信念：P_i(P_j(role_k) = p)，建模为 Beta(α_ijk, β_ijk)
  期望值：E_i[P_j(role_k)] = α_ijk / (α_ijk + β_ijk)

更新规则（行为似然驱动的 Beta 更新）：
  α'_ijk = α_ijk + η × likelihood_weight
  β'_ijk = β_ijk + η × (1 - likelihood_weight)

  其中：
    η = 0.1（学习率，控制每次观测对二阶信念的影响）
    likelihood_weight = P(j 的行为 a_j | j 的信念 P_j(role_k) = 1)
      即：如果 j 完全相信 player k 是 role_k，j 做行为 a_j 的概率

举例：
  i 观测到 j 投了 k 的票 →
  如果 k 是狼人，j 投 k 的行为可通过"j 认为 k 是狼人"解释 →
  i 的二阶信念 α_ij_wolf 增加，即 i 更相信"j 认为 k 是狼人"

用途：二阶信念用于预测 j 的未来行为、判断 j 的阵营立场、评估 j 的阵营一致性。
```

### 3.1.3 游戏树搜索（2 步前瞻）

```
前端式 2 步前瞻：

输入：当前 GameState S、当前 Agent i
输出：当前最优行动 a*

算法：
  1. 枚举 Agent i 的当前可选行动 A = {a_1, a_2, ...}
  2. 对每个 a ∈ A：
     a. 模拟执行 a → 中间状态 S'
     b. 在 S' 中考虑其他玩家的可能反应：
        - 利用信念模型预测最可能的集体行动 a_others'
        - 若存在多个高概率分支（概率 > 0.2），对 top-2 分支加权
     c. 应用 a_others' → 状态 S''
     d. 评估 S'' 对 Agent i 的价值 V(S'')：
        阵营胜率变化 + 个人存活概率 + 信息收益
        V(S'') = w_win × ΔP_win + w_survive × ΔP_survive_i + w_info × info_gain
  3. 选择 V 最高的行动 → 返回 a*
  4. 若搜索空间过大（> 20 行动），降级为贪婪（仅前瞻 1 步）

信息收益 (info_gain) 的计算：
  I(a) = H(Belief_before) - H(Belief_after_a)
  其中 H 是信念分布的熵：H(P) = -Σ P(role) × log(P(role))
```

### 3.1.4 反事实推理（形式化定义）

```
反事实推理：评估"如果 X 不是 role_k，那么世界会是什么样"

流程：
  1. 选择候选命题 φ："player_j 是 role_k"
  2. 在信念模型中临时翻转：P'_i(role_k | j) = 0, 重新归一化所有概率
  3. 推算翻转后的世界状态：
     - 如果 j 不是狼人，那么 j 过去的行为就"不是狼人行为"
     - 检查翻转后：j 的历史行为是否与翻转后的身份更一致？
  4. 计算一致性差异：
     consistency_diff = Σ_action of j | P(action | 翻转身份) - P(action | 原身份) |
  5. 若 consistency_diff > 0（翻转后行为更合理），则降低对"j 是 role_k"的信念
  6. 输出结论和一致性差异分数，供决策引擎使用
```

### 3.2 结构化输出 JSON Schema（按阶段）

**投票决策**：
```json
{
  "vote_target": "3号",
  "reasoning": {
    "analysis": "3号今天发言前后矛盾...",
    "belief_update": {"3号": {"狼人": 0.72}},
    "second_order_inference": "我认为5号也认为3号是狼，因为5号在上一轮质疑了3号的逻辑",
    "strategic_plan": "投出3号后，下轮关注5号反应"
  },
  "confidence": 0.85
}
```

**夜晚行动**（狼人）：
```json
{
  "kill_target": "2号",
  "deception_plan": "shadow_support",
  "deception_target": "4号",
  "reasoning": {
    "analysis": "2号发言引导投票方向，疑似预言家",
    "strategic_plan": "杀2号削弱好人推理，白天支持4号判断以伪装好人"
  },
  "confidence": 0.78
}
```

**发言**：
```json
{
  "speech": "我觉得今天2号的发言需要注意...",
  "speech_strategy": "signal_innocence",
  "suspicion_target": "3号",
  "suspicion_score": 0.65,
  "next_strategy": "观察3号对此发言的反应以更新二阶信念"
}
```

### 3.3 降级策略细则

当 LLM 调用失败或超时时，每种角色使用预设的规则策略：

| 角色 | 夜晚降级 | 白天降级 |
|------|----------|----------|
| 狼人 | 基于信念模型的 top-1 非狼嫌疑人 | 发言从模板库随机（同局不重复），投票从众 |
| 预言家 | 查验信念最不确定的存活玩家 | 公布最新一条查验结果 |
| 女巫 | 解药首夜必救；毒药投信念 top-1 狼人 | 发言从模板库随机 |
| 守卫 | 守护信念最高的存活好人 | 发言从模板库随机 |
| 猎人 | 无 | 被触发时开枪打信念 top-1 狼人 |
| 村民 | 无 | 发言从模板库随机，投票跟从多数 |

每个角色模板库 ≥ 15 条，含不同情绪变体。存储于 `degraded_speech_templates` 表。
同局已用模板不重复。**兜底策略**：模板耗尽时，对已用模板做参数化替换（换玩家编号、换角色名）生成新变体。
降级事件计数计入 `game_players.llm_degradation_count`。

### 3.4 多 Agent 协作机制

#### 3.4.1 狼人动态协商 (Dynamic Deliberation, DD)

```
协商协议（回合制，最多 3 轮）：

第 0 阶段 — 角色分配子协议（防策略冲突）：
  服务端列出可选 deception_plan 槽位：["impersonate_seer", "impersonate_witch",
    "impersonate_hunter", "shadow_support", "agitate", "low_profile"]
  每只狼按 preference 排序提交 3 个偏好 slot
  服务端做 Gale-Shapley 稳定匹配：
    优先匹配每只狼的第一偏好 → 若冲突（两只狼抢 impersonate_seer），
    比较狼人的 deception_preference，高者得，低者退到第二偏好
  匹配结果私密通知各狼（只有狼人知道同伴分配了什么角色）
  确保：同一 deception_plan 最多一只狼执行（shadow_support 和 low_profile 可多人）

第 1 轮 — 提案阶段：
  每只狼提交策略提案 P = (kill_target, deception_plan, deception_target)
  deception_plan 与 kill_target 的关联一致性校验：
    若 deception_plan = "shadow_support" 且 deception_target = kill_target，
    则标记为 inconsistent，需要重选 deception_target（不能白天支持你要杀的人）

第 2 轮 — 反提案/修正：
  支持 + 补充 | 反对 + 修正案 | 让步

第 3 轮 — 确认/投票：
  共识 → 执行 | 分歧 → 投票多数决（平票随机含自刀）

仅 1 狼 → 跳过协商，直接决策。
```

#### 3.4.2 好人信号博弈 (Signaling Game)

| 信号类型 | 发送者 | 信号成本 | 狼人模仿成本 | 接收者可信度计算 |
|----------|--------|----------|-------------|-----------------|
| 预言家公告 | 预言家/假预言家 | 暴露自身成为狼人目标（存活 -1 轮期望） | 暴露后需持续产出"查验结果"且不能出错 | cred = `leadership_bias(发送者) × (1 - P(假预言家)) × 查验结果一致性` |
| 女巫暗语 | 女巫 | 中等（暗示知道死亡详情，被狼人警惕） | 只能泛泛而谈，缺乏具体细节 | cred = `发言与已知事实的匹配条数 / 预期匹配条数` |
| 村民推理链 | 村民/狼人 | 低（只是分析发言） | 低 | cred = `推理链的一致性（无前后矛盾）` |
| 质疑跟随 | 任何人 | 几乎为零 | 几乎为零 | cred = `0.3`（廉价交谈，默认不可信） |

信号可信度阈值：> 0.6 视为可信信号并相应更新信念模型。

#### 3.4.3 协作记忆评分更新规则

```
cooperation_score(j) 和 deception_score(j) 的更新规则：

初始化：coop(j) = 0.5, decp(j) = 0.5（中性）

触发事件 → 增量：
  1. j 的投票与我一致且结果正确（好人投狼、狼人投好人）→ coop(j) += 0.05
  2. j 的投票与我一致但结果错误 → coop(j) += 0.02（仅有限信任）
  3. j 的投票与我相反且我正确 → decp(j) += 0.07
  4. j 的发言与我私下推理一致 → coop(j) += 0.03
  5. j 公开质疑我的发言 → decp(j) += 0.04
  6. j 被预言家确认为狼人 → decp(j) = 1.0（硬更新）
  7. j 被预言家确认为好人 → coop(j) = 0.9（信任 boost）

时间衰减（每轮）：
  coop(j) *= 0.95（记忆逐渐淡化）
  decp(j) *= 0.95

边界：coop, decp ∈ [0, 1]

在决策引擎中：
  - 投票时：若 trust(j) = coop - decp > 0.3，更倾向跟票 j
  - 发言时：若 decp(j) > 0.5，在发言中点名怀疑 j
  - 查验时（预言家）：若 decp(j) > 0.6，优先查验 j
```

#### 3.4.4 多 Agent 博弈能力矩阵

| 博弈能力 | 实现机制 |
|----------|----------|
| 身份伪装 | DD 协议 deception_plan + Gale-Shapley 角色分配 + LLM 生成角色一致发言 |
| 反伪装检测 | 信念模型对比"声称身份"与"行为似然"的 KL 散度，阈值触发怀疑 |
| 信任构建 | cooperation_score 累积 + 发言引用链 + 投票一致性统计 |
| 廉价交谈利用 | 信号博弈可信度评分，低成本信号加权低（默认 0.3） |
| 选择性信息披露 | 决策引擎评估：公开信息的收益（引导投票）vs 风险（存活期望下降） |
| 二阶推理 | 二阶信念 Beta 分布 + 行为似然驱动更新（见 3.1.2） |
| 反事实推理 | 临时翻转信念 → 推算行为一致性差异 → 调整置信度（见 3.1.4） |
| 策略规划 | 游戏树 2 步前瞻 + 信息收益评估（见 3.1.3） |

### 3.5 博弈质量评测指标（可操作化）

**辅助函数**：
```
suspicion_score(i, j) = Belief_i(j).get("狼人", 0) / (Belief_i(j).get("狼人", 0) + Belief_i(j).get("村民", 1))
                        × (1 - Belief_i(j).get("预言家", 0))
  公式将"狼人概率"映射到 [0,1] 的怀疑度，扣减神职概率（若玩家认为 j 是预言家，降低怀疑度）
```

| # | 指标 | 计算公式 | 说明 |
|---|------|----------|------|
| 1 | 投票准确率（好人） | \|好人投狼票\| / \|好人总投票\| | 仅统计好人。跟预言家投票且目标为狼人 → 计入跟票命中 |
| 2 | 投票一致性（狼人） | \|与狼人多数一致的票\| / \|狼人总投票\| | 测量狼队协调度 |
| 3 | 伪装成功率 | \|狼人 j 在存活轮次中 suspicion_score(i,j) < 0.5（对所有 i）的轮次\| / \|j 存活总轮次\| | 狼人被全体好人低怀疑的比例 |
| 4 | 反伪装检测率 | \|好人信念 Top-3 怀疑度中含 ≥ 1 狼人的轮次\| / \|总轮次\| | 好人整体推理准确度 |
| 5 | 信号可信度 | \|预言家公布后 1 轮内 ≥ 1 个（非预言家）跟票的轮次\| / \|公布查验轮次\| | 跟票 = 投票目标与预言家相同 |
| 6 | LLM 降级率 | 降级次数 / 总决策次数 | 各角色分别统计 |
| 7 | 协商共识率（狼人） | 第一轮提案即一致的次数 / 协商总次数 | 测量狼人协作效率 |
| 8 | 信息利用效率 | KL(Belief_i \|\| TrueRole) 的下降趋势 | 仅上帝视角离线计算 |

---

## 四、消息总线

### 4.1 事件类型

| 事件 | scope 枚举值 | 说明 |
|------|-------------|------|
| GAME_START | broadcast | 游戏开始 |
| ROLE_ASSIGNED | single | 告知玩家本人角色 |
| WOLF_TEAMMATE | werewolf | 告知狼人队友是谁 |
| NIGHT_START | broadcast | 夜晚开始 |
| GUARD_PROTECT | single | 守卫守护目标 |
| WOLF_DISCUSSION | werewolf | 狼人协商消息 |
| WOLF_KILL_TARGET | werewolf | 狼人击杀目标 |
| WOLF_INTERNAL_VOTE | werewolf | 狼人内部投票详情 |
| SEER_CHECK_RESULT | single | 预言家查验结果 |
| WITCH_INFO | single | 女巫得知死亡信息 |
| WITCH_ANTIDOTE | single | 女巫使用解药 |
| WITCH_POISON | single | 女巫使用毒药 |
| HUNTER_DEATH_INFO | single | 猎人死亡通知 |
| HUNTER_SHOOT_PRIVATE | single | 猎人开枪私下通知 |
| NIGHT_RESOLVE | broadcast | 夜晚结算完成 |
| DEATH_ANNOUNCE | broadcast | 公布死亡（多死按座位号） |
| PLAYER_SPEECH | broadcast | 某玩家发言内容 |
| LAST_WORDS | broadcast | 玩家遗言（多死按座位号） |
| VOTE_PHASE_START | broadcast | 投票阶段开始 |
| VOTE_CAST | broadcast_delayed | 投票结束后公布 |
| VOTE_TIE | broadcast | 平票—PK环节 |
| PLAYER_ELIMINATED | broadcast | 投票出局 |
| HUNTER_SHOOT | broadcast | 猎人开枪 |
| PHASE_CHANGE | broadcast | 阶段切换 |
| PLAYER_DEAD | broadcast | 玩家死亡（UI切换） |
| GAME_OVER | broadcast | 游戏结束 |
| TIMER_TICK | broadcast | 倒计时同步 |
| TIMER_CONFIG | broadcast | 计时器配置 |
| HOST_INTERVENE | broadcast | 房主干预 |
| PLAYER_DISCONNECT | broadcast | 玩家断线 |
| PLAYER_RECONNECT | broadcast | 玩家重连 |
| PLAYER_REPLACED_BY_AI | broadcast | 人类被AI替补 |
| TOKEN_REFRESH_REQUIRED | single | 通知刷新JWT |
| GAME_STATE_SNAPSHOT | single | 重连快照 |

**scope 枚举 → 路由映射**：
- `broadcast` / `broadcast_delayed` → 所有存活+死亡(观战)+旁观者
- `single` → 仅目标玩家连接
- `werewolf` → role=WEREWOLF 的存活玩家连接
- `spectator` → 仅旁观者连接

### 4.2 消息路由规则

- **broadcast**：推送给所有存活玩家 + 死亡玩家（观战）+ 旁观者
- **single**：仅推送给目标玩家的连接
- **werewolf**：仅推送给 role=WEREWOLF 的存活玩家
- **broadcast_delayed**：收集阶段内所有同类事件（如投票），阶段结束后一次性广播
- **spectator**：仅旁观者连接

---

## 五、房间系统

| 功能 | 说明 |
|------|------|
| 创建房间 | 房主设置：房间名、人数配置（模板/自定义）、每席位指定人类或 AI |
| 加入房间 | 输入房间码/列表选择 |
| 席位管理 | 房主可调整某席位：人类→AI（断线替补），AI→人类（中途加入）。席位状态机保证原子化（见 7.4 节） |
| AI 配置 | 每 AI 席位独立配置：模型、API Key、人格偏好 |
| 准备状态 | 所有人准备后房主可开局 |
| 旁观模式 | 满员后允许旁观者加入（硬上限 200 人/房间） |
| 房间日志 | 房间内历史对局简要记录 |

---

## 六、用户系统

| 功能 | 说明 |
|------|------|
| 注册/登录 | 邮箱 + 密码，JWT 认证（access token 15min + refresh token 7d） |
| 密码安全 | bcrypt 哈希（cost factor ≥ 12），密码 ≥ 8 位且含字母和数字 |
| 登出 | 登出接口，access token 加入黑名单（Redis，TTL = 剩余有效期 + 60s grace） |
| 个人资料 | 昵称、头像、战绩概览 |
| 对局历史 | 每局的角色、胜负、存活轮数 |
| 排行榜 | 按胜率/场次排序，可按角色筛选 |
| AI 配置库 | 保存常用 Agent 配置（模型、参数），开局时一键选用 |
| 对局回放 | 两种模式：玩家视角、上帝视角（游戏结束 24 小时后可用）；仅当局参与者可查看 |

---

## 七、断线重连机制

### 7.1 心跳与断线判定

```
  - 客户端每 10s 发送 WebSocket ping
  - 服务端 30s 内未收到任何消息 → 判定断线
  - 断线立即广播 PLAYER_DISCONNECT 事件
```

### 7.2 重连流程

```
  1. 客户端建立 WebSocket，首条消息发送 authenticate {jwt, game_id, last_event_seq}
  2. 服务端验证 JWT + game_id + 用户属于此房间
  3. 发送 GAME_STATE_SNAPSHOT（见 7.5 节）
  4. 补发 last_event_seq 之后的事件，严格按接收者 role 过滤 scope
     last_event_seq 以服务端记录的 last_delivered_seq 为准（防恶意客户端拉全量历史）
  5. 客户端恢复 UI，进入正常流程
  6. 广播 PLAYER_RECONNECT
```

### 7.3 断线期间行为

| 阶段 | 行为 |
|------|------|
| 发言（轮到该玩家） | 超时跳过 |
| 投票 | 超时弃权 |
| 夜晚行动 | 超时不行动 / 狼人随机杀 |
| 非关键阶段 | 30s 宽限期 |
| 重连宽限期 | 30s 内重连恢复；超时→AI 替补 |

### 7.4 席位状态机（原子化）

```
HUMAN_ACTIVE → HUMAN_DISCONNECTED → (30s后) AI_STANDBY → (自动) AI_ACTIVE
HUMAN_DISCONNECTED + 重连 → HUMAN_ACTIVE（宽限期内）

关键约束：
  - AI_STANDBY → AI_ACTIVE 自动转换（无需房主确认，游戏不中断）
  - HUMAN_DISCONNECTED → AI_STANDBY 和 HUMAN_DISCONNECTED → HUMAN_ACTIVE 使用
    SELECT ... FOR UPDATE 行锁确保串行执行
```

### 7.5 游戏状态快照格式

```json
{
  "game_id": "...",
  "current_phase": "SPEECH",
  "round_number": 3,
  "speech_round": 2,
  "current_speaker": "4号",
  "phase_deadline": "2026-05-20T14:30:00Z",
  "players": [
    {"seat": 1, "name": "张三", "is_alive": true, "is_human": true},
    {"seat": 2, "name": "AI_Alpha", "is_alive": true, "is_human": false}
  ],
  "my_seat": 3,
  "my_role": "预言家",
  "recent_events_summary": [
    "第2天夜晚 2号玩家死亡",
    "第3天白天 发言第1轮 1号说：..."
  ],
  "vote_history": {"第2天": {"1号": "3号", "3号": "5号"}}
}
```

---

## 八、AI 模型配置

| 配置项 | 说明 |
|--------|------|
| 提供商 | OpenAI / Anthropic / DeepSeek / 通义千问 / Ollama |
| API Key | 独立配置（每 Agent 可不同） |
| 模型名称 | gpt-4o, claude-sonnet-4-6, deepseek-v3 等 |
| 参数 | temperature, max_tokens, timeout（默认 30s） |
| 人格偏好 | 可选固定人格，否则按角色约束区间随机采样 |

### 8.1 API Key 安全方案

- **加密**：AES-256-GCM，密钥由环境变量 `API_KEY_ENCRYPTION_KEY` 注入
- **存储**：仅密文 `api_key_encrypted`
- **API 返回**：脱敏 `sk-a***b1c2`
- **日志**：强制正则脱敏
- **内存**：`bytearray` zero-out + `ulimit -c 0` + 异常堆栈避开 Key 变量
- **权限**：仅 Agent 运行时解密，明文不落持久化存储

---

## 九、通信协议

| 协议 | 用途 |
|------|------|
| REST API | 用户认证、房间 CRUD、席位管理、对局历史查询、排行榜 |
| WebSocket (wss://) | 游戏实时事件推送、发言、投票、阶段推进、计时器 |

### 9.1 WebSocket 认证方案

- **连接**：强制 `wss://`（TLS 1.2+）
- **认证**：首条应用消息 `{"type": "authenticate", "jwt": "...", "game_id": "...", "last_event_seq": 42}`，5s 超时断开
- **映射**：`ws_connection_id → user_id → room_id → seat_id/permission`
- **鉴权**：逐消息 scope 校验，见 4.2 节路由规则
- **刷新**：JWT < 5min 到期 → 推送 TOKEN_REFRESH_REQUIRED → 客户端发 `{"type": "refresh_token", "jwt": "..."}`，另加 60s grace period 防网络延迟
- **跨房间防护**：逐消息校验 room_id
- **竞态防护**：房主干预/定时器 用 `asyncio.Lock` 或 DB 行锁串行化

---

## 十、数据持久化 (PostgreSQL)

| 实体 | 内容 |
|------|------|
| users | id, email, nickname, password_hash, avatar, created_at |
| rooms | id, name, config(JSON), status, created_by, created_at |
| room_seats | id, room_id, seat_index, player_type, user_id(NULLABLE), agent_config_id(NULLABLE), seat_status, CHECK(NOT (user_id IS NOT NULL AND agent_config_id IS NOT NULL)) |
| games | id, room_id, player_count, roles_config, winner, rounds, started_at, ended_at |
| game_players | game_id, user_id(NULLABLE), agent_config_id(NULLABLE), role, is_human, survived_rounds, vote_accuracy, llm_degradation_count, CHECK(NOT (user_id IS NOT NULL AND agent_config_id IS NOT NULL)) |
| game_events | game_id, seq(PER-GAME递增), timestamp, event_type, data(JSON), scope(broadcast/single/werewolf/broadcast_delayed/spectator) |
| spectators | id, user_id, room_id, ip_address, joined_at |
| agent_configs | id, user_id, name, provider, model, api_key_encrypted, params(JSON) |
| degraded_speech_templates | id, role, emotion, content, usage_count |
| rankings | user_id, total_games, wins, win_rate, favorite_role, current_streak |

---

## 十一、评测与实验

| 功能 | 说明 |
|------|------|
| 批量对战 | 指定模型组合，自动 N 局对战，记录全部数据 |
| 胜率矩阵 | 按模型/角色/人格维度的交叉统计 |
| 博弈质量 | 8 项可量化指标（见 3.5 节） |
| 策略对比 | 控制变量法统计同一角色不同人格的胜率差异 |
| 对局导出 | JSON/CSV 格式 |

---

## 十二、非功能需求

| 类别 | 要求 |
|------|------|
| 并发 | 多房间同时运行，每房间 ≤ 18 玩家 + 200 旁观 |
| 延迟 | WebSocket 推送 < 500ms |
| LLM 容错 | 单 Agent 失败降级规则策略（含 15+ 模板 + 参数化兜底） |
| 安全 | API Key AES-256-GCM + 内存 zero-out + 日志脱敏；JWT 双 token；wss:// 强制 TLS 1.2+；逐消息 scope 鉴权；密码 bcrypt ≥ 12 |
| 扩展性 | 新角色实现 RoleHandler 接口；新事件注册到消息总线 |
| 中文 | 系统提示词、UI、降级模板以中文为主 |
