# Part 9: Persona × Role × Strategy 测评可行性审计

> 审计日期: 2026-05-28 | 状态: 只读 | 核心问题: 当前能否做三层测评？

---

## 9.1 三层测评所需字段

### 目标聚合维度

| 维度 | 含义 | 当前是否可用 |
|------|------|------------|
| persona_id | 人设标识 | ✅ YES (在 opportunity + player record 中) |
| persona_name | 人设名称 | ✅ YES |
| mbti | MBTI 类型 | ✅ YES (在 persona 中) |
| background_profile | 背景经历 | ✅ YES (persona.basic_info) |
| role | 角色 | ✅ YES |
| strategy_id | 策略标识 | ❌ NOT_FOUND |
| strategy_name | 策略名称 | ❌ NOT_FOUND |
| strategy_type | 策略类型 | ❌ NOT_FOUND |
| prompt_version | Prompt 版本 | ✅ YES (在 AgentDecision 中) |
| model_name | 模型名称 | ✅ YES (在 ReplayBundle 中) |
| game_id | 对局 ID | ✅ YES |
| camp | 阵营 | ✅ YES (可从 role 推导) |
| is_win | 是否获胜 | ✅ YES (V7 fixed 回填) |
| pre_action_score | 预动作分数 | ✅ YES |
| process_score | 过程分数 | ✅ YES |
| outcome_impact_score | 结果影响分数 | ✅ YES |
| confidence | 置信度 | ✅ YES (per-opportunity) |

---

## 9.2 当前能做 Persona × Role 评测吗？

**答案: ✅ YES，但有条件**

条件:
1. 使用 V7 fixed player_scores (已回填 is_win + camp)
2. 使用 role-normalized PreAction (使跨角色可比)
3. 使用 role-adjusted win lift (排除角色阵营基线)
4. 过滤 n≥10 的 persona×role 组合

**当前实现**: MBTI Dashboard v7 实际上就是 Persona × Role 评测:
- 按 MBTI 聚合 (16 种 × role 分布)
- 指标: CampBalWR, RoleNormPre, RoleAdjLift, Composite
- n≥10 过滤后: 14 types

---

## 9.3 当前能做 Persona × Role × Strategy 评测吗？

**答案: ❌ NO**

**原因**: `strategy_id` 字段在项目中不存在。

虽然有以下策略相关机制:
- `strategy_bias` dict (运行时偏差)
- `RetrievedStrategyLesson` (DB 检索)
- `RoleStrategyCard` (DB Track C 产物)

但都**没有追踪 ID**:
- `strategy_bias` 不写入 AgentDecision/Opportunity
- 检索知识有 `doc_id` 但不是 `strategy_id`
- 策略卡有 `(role, version)` 但不是 `strategy_id`

---

## 9.4 缺失字段清单

| 字段 | 缺在哪里 | 必须修改的代码 |
|------|---------|--------------|
| `strategy_id` | 整个项目 | `factory.py` (注入), `llm_agent.py` (记录), `opportunity.py` (提取), 评分脚本 (聚合) |
| `strategy_name` | 整个项目 | 同上 |
| `strategy_type` | 整个项目 | 同上 |

---

## 9.5 当前 MBTI Dashboard 是否只是 Persona × Role？

**答案: ✅ YES**

MBTI Dashboard v7 的聚合维度是:
```
MBTI → (aggregate over roles played by that MBTI)
```

虽然显示了 Role×Camp 矩阵, 但:
- Composite 是跨角色聚合的
- 每个 MBTI 可能玩过多种角色 (Werewolf/Seer/Witch/...)
- 样本量按 MBTI 而非 (MBTI, Role) 计算

**实际测评单位**: Persona (MBTI) × (所有玩过的角色)
**不是**: Persona (MBTI) × 单个 Role × Strategy

---

## 9.6 推荐目标矩阵

当 Strategy 补齐后，最终测评矩阵建议为:

| 维度 | 字段 | 来源 |
|------|------|------|
| persona_name | str | Player.persona.name |
| mbti | str (16种之一) | Persona.mbti |
| role | str (8种角色) | Player.role |
| strategy_name | str | **NEED: strategy_id → lookup name** |
| strategy_type | str | **NEED: 策略分类** |
| n | int | COUNT(DISTINCT game_id) |
| raw_win_rate | float | SUM(is_win) / n |
| adjusted_win_lift | float | is_win - expected_wr(role, camp) |
| avg_role_normalized_pre_action_score | float | AVG(score - mean(score\|role)) |
| avg_process_score | float | AVG(process_score) |
| mistake_rate | float | SUM(mistakes) / n |
| confidence_level | str (HIGH/MEDIUM/LOW) | 6-factor confidence |
| low_confidence_reason | str | 具体原因 |

---

## 9.7 Strategy 补齐计划

### Phase 1: 定义 strategy_id (1-2天)

1. 为 `configs/strategy_library.yaml` 中每条策略定义 `id`
2. 生成 `strategy_id` → `(name, type, role_scope)` 的映射表
3. 在 demo/game config 中增加 `strategy_id` 字段

示例:
```yaml
# configs/strategy_library.yaml
seer:
  core_strategy:
    - id: "seer_aggressive_v1"
      name: "激进跳身份"
      type: "info_release"
      applicable_roles: ["Seer"]
      content: "查验到狼人后立即跳身份发布信息..."
    - id: "seer_conservative_v1"
      name: "保守隐藏"
      type: "info_release"
      applicable_roles: ["Seer"]
      content: "查验到好人后隐藏，只发布狼人信息..."
```

### Phase 2: 记录 strategy_id (1-2天)

修改以下文件:
1. **`backend/agents/factory.py`**: `create_agents()` 读取 `strategy_id` 并传递
2. **`backend/agents/llm_agent.py`**: `__init__()` 接受 `strategy_id`, 在 `_build_strategy_bias_block()` 中注入, 在 `_record_decision()` metadata 中记录
3. **`backend/agents/heuristic.py`**: 类似记录
4. **`backend/eval/opportunity.py`**: `DecisionOpportunity` 增加 `strategy_id` 字段
5. **评分脚本**: 聚合时按 `strategy_id` 分组

### Phase 3: 验证策略影响 (1-2天)

1. 用不同 strategy_id 运行对比实验 (同一 seed, 同一 persona)
2. 验证 AgentDecision 中 strategy_id 是否正确记录
3. 验证评分聚合时 strategy_id 是否可用

---

## 9.8 关键审计结论

1. ✅ **Persona × Role 评测已实现** — MBTI Dashboard v7 就是
2. ❌ **Persona × Role × Strategy 评测不可行** — strategy_id 不存在
3. ⚠️ **4 个字段可从 config 回填**: role, camp, persona, mbti
4. ❌ **3 个字段必须修改代码**: strategy_id, strategy_name, strategy_type
5. ✅ **MBTI Dashboard 是 Persona × Role (跨角色聚合)** — 不是三层
6. ⚠️ **Strategy 补齐约需 3-6 个开发日** — Phase 1-3 如上
