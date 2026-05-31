# Part 3: Agent 构成审计

> 审计日期: 2026-05-28 | 状态: 只读 | 证据: `backend/agents/` 全部 11 个文件

---

## 3.1 Agent 组成层次

当前一个 Agent 由以下层次构成:

```
Persona (人物设定) ──── 来自 PERSONA_POOL (30+人物)
  ├── mbti, gender, age, name
  ├── basic_info (背景经历)
  ├── style_label, voice_rules
  ├── vocabulary_style, speech_length_habit
  ├── reasoning_style, social_habit, humor_style
  ├── pressure_style, uncertainty_style
  ├── wolf_deception_style, mistake_pattern
  ├── trigger_topics, werewolf_experience
  └── logic_style

PlayerMind (心智参数) ──── 来自 MIND_POOL (8种配置)
  ├── courage, memory_bias
  ├── suspicion_threshold, self_protection
  ├── logic_depth, table_presence

Role (角色) ──── 来自 Role Registry + Profiles
  ├── ROLE_SYSTEM_PROMPTS (系统提示)
  ├── ROLE_PROFILES (table_goal + speech_style)
  ├── ACTION_STRATEGIES (动作策略)
  └── ACTION_PLAYBOOKS (策略简述)

Strategy (策略) ──── ⚠️ 分散在多个来源, 无统一 strategy_id
  ├── strategy_bias (dict, 从 config 传入)
  ├── RetrievedStrategyLesson (从 DB 检索)
  ├── RoleStrategyCard (从 DB, Track C 产物)
  └── strategy_library.yaml (静态参考, ~200条)

Model (模型) ──── 来自 LLM Client
  ├── provider: doubao / deepseek
  ├── model: 从 DOUBAO_MODEL_POOL 或配置
  ├── temperature: 0.4 (决策) / 1.1 (发言)
  └── max_tokens: 1536 (发言) / 512 (决策)

Heuristic Fallback ──── LLM 失败时的回退
  └── HeuristicAgent (纯规则, 确定性)
```

---

## 3.2 Prompt 拼接流程

### 发言 (Talk) 路径

```
1. System Prompt (系统部分):
   ├── [BASE]       身份: "你是 N号[名字], 角色: [role]" + 胜利条件
   ├── [PERSONA]    _build_persona_hint() → persona.system_prompt
   │                (包含 背景/MBTI/性格/风格/经验 全部)
   ├── [BEHAVIOR]   _build_behavior_hint() → <hidden_traits>
   │                (Persona + PlayerMind 映射为行为描述)
   ├── [TASK]       阶段特定任务说明
   ├── [BIAS]       strategy_bias_block (当 placement=system 时)
   └── [GUIDELINES] 底层规则约束

2. User Prompt (用户部分, 按顺序):
   ├── [STATE]      _build_game_context()
   │                (存活/死亡/警长/规则/历史/投票/私密信息)
   ├── [STANCE]     _build_stance_block()
   │                (立场连续性总结, 来自 heuristic fallback)
   ├── [PERSONALITY] _build_personality_decision_block()
   │                ("这些不是装饰—它们必须影响你的决策")
   ├── [TODAY]      今日发言记录
   ├── [SELF]       自己的发言历史
   ├── [PHASE]      阶段提示
   ├── [STYLE]      风格约束 (从 Persona 映射)
   ├── [REPEAT]     防重复开头
   ├── [ORDER]      发言顺序提示
   ├── [EXAMPLES]   对话示例 (阶段特定)
   ├── [RETRIEVED]  检索到的策略经验 (从 DB)
   ├── [BIAS]       strategy_bias_block (当 placement=user 时)
   └── [END]        结束指令

3. LLM Call → parse JSON array → return speech text
```

### 投票/技能 (Vote/Attack/Divine/Guard/Shoot) 路径

```
1. System Prompt (非交谈动作):
   ├── [ROLE]       get_system_prompt(role) → 角色系统提示
   ├── [CHARACTER]  persona.system_prompt (完整人设)
   ├── [COMM]       <hidden_communication_profile> (Persona字段XML)
   ├── [MIND]       <hidden_player_mind> (PlayerMind字段XML)
   ├── [CONSTRAINTS] 7条硬性规则
   └── [BIAS]       strategy_bias (当 placement=system 时)

2. User Prompt:
   ├── [STATE]      当前状态 (角色/天/阶段/存活/死亡)
   ├── [GOAL]       ROLE_PROFILES[role].table_goal + speech_style
   ├── [FACTS]      已发生事实速查
   ├── [SPEECHES]   今日发言记录
   ├── [EVENTS]     最近公开事件原始日志
   ├── [PRIVATE]    你的私有信息
   ├── [STRATEGY]   get_action_strategy(action, role) → 动作策略
   ├── [BIAS]       strategy_bias_block (可选)
   ├── [RETRIEVED]  检索经验 (可选)
   ├── [INSTRUCTION] 当前指令
   ├── [ANTI_HALLUCINATION] 反幻觉硬性纪律
   └── [FORMAT]     输出格式 JSON Schema

3. LLM Call → parse JSON → return Decision(target_id, reasoning)
```

---

## 3.3 逐层验证: Persona / MBTI / Background 是否进入 Prompt？

| 层次 | 是否进入 Prompt | 证据 |
|------|---------------|------|
| Persona (人设整体) | ✅ YES | `_build_persona_hint()` 使用 `persona.system_prompt` 完整注入 |
| MBTI | ✅ YES | `characters.py:build_system_prompt()` 生成 MBTI 描述 (如 "INTJ: 理性战略家") |
| Background (背景经历) | ✅ YES | `persona.basic_info` → system_prompt → "背景: {basic_info}" |
| Gender / Age | ✅ YES | `persona.name`, `persona.gender`, `persona.age` 全部注入 |
| Style Labels | ✅ YES | `persona.style_label` → `style_guardrails` + `behavior_hint` |
| Speech Habit | ✅ YES | `persona.speech_length_habit` → `personality_decision_block` |
| Pressure Style | ✅ YES | `persona.pressure_style` → `behavior_hint` |
| Wolf Deception | ✅ YES | `persona.wolf_deception_style` → 狼人专属行为提示 |
| Mistake Pattern | ✅ YES | `persona.mistake_pattern` → `behavior_hint` |
| PlayerMind | ✅ YES | `_build_player_mind_section()` → `<hidden_player_mind>` XML |

**结论**: Persona + MBTI + Background 三层**完整进入 Prompt**，不是只存不用。

---

## 3.4 逐层验证: Role Prompt 是否进入 Prompt？

| 层次 | 是否进入 Prompt | 证据 |
|------|---------------|------|
| 角色系统提示 | ✅ YES (非交谈动作) | `get_system_prompt(role)` → System Prompt 第一部分 |
| 角色胜利条件 | ✅ YES (交谈) | `_build_win_condition()` → 含 `get_action_strategy("talk", role)` |
| 角色桌面目标 | ✅ YES (行动) | `ROLE_PROFILES[role].table_goal` → 行动 Prompt |
| 角色策略 | ✅ YES (行动) | `get_action_strategy(action, role)` → 行动 Prompt "行动策略" 段 |
| 角色 Playbook | ✅ YES (初始化) | `build_role_brief(role)` → `self.memory[0]` |

**结论**: Role Prompt **完整进入**，每个角色有独立系统提示和动作策略。

---

## 3.5 逐层验证: Strategy 是否进入 Prompt？

| 层次 | 是否进入 Prompt | 证据 | 状态 |
|------|---------------|------|------|
| strategy_bias | ✅ YES | `_build_strategy_bias_block()` → system 或 user prompt | IMPLEMENTED |
| RetrievedStrategyLesson | ✅ YES | `_build_retrieved_lessons_block()` → user prompt | IMPLEMENTED |
| RoleStrategyCard (DB) | ⚠️ INDIRECT | 通过 retrieve_strategy_knowledge() 检索进入 | IMPLEMENTED (Track C) |
| strategy_library.yaml | ❌ NO | 静态 YAML, 代码中未读取使用 | CONFIG_ONLY |
| **strategy_id** | ❌ NO | **字段不存在于整个项目** | NOT_FOUND |

**关键发现**: `strategy_id` 在项目中**完全不存��**。策略偏差通过 `strategy_bias` dict (文本指令) 传入，但没有追踪 ID。检索到的策略知识有 `doc_id`，但这不等同于 `strategy_id`。

---

## 3.6 Agent Memory

每个 Agent 的 memory:

| 层次 | 内容 | 来源 |
|------|------|------|
| `self.memory` | 字符串列表, 逐步追加 | `LLMAgent` |
| `memory[0]` | 角色简要 (`build_role_brief(role)`) | `initialize()` 时写入 |
| `memory[N]` | 每日总结追加 | `day_start()` 时写入 |
| `self.view` | 当前 PlayerView | `update()` 时覆盖 |
| Heuristic Stance | public_stance (suspected/trusted/grudges) | HeuristicAgent 追踪 |
| DB Strategy Knowledge | 检索到的策略经验 | `retrieve_strategy_knowledge()` |

**注意**: `self.memory` 是累积的文本列表，但在 Prompt 中如何被使用取决于各 Prompt 构建函数。发言路径有明确的 "自己的发言历史" 段，投票路径有 "已发生事实速查"。

---

## 3.7 最终 Prompt 组装位置

| 组件 | 组装位置 | 文件:行号 |
|------|---------|-----------|
| 发言 System Parts | `_build_talk_system_parts()` | `llm_agent.py` |
| 发言 User Parts | `talk()` 方法内联拼接 | `llm_agent.py` |
| 发言 LLM Call | `_ask_talk_wolfcha()` | `llm_agent.py` |
| 行动 System Prompt | `_build_system_prompt()` | `llm_agent.py` |
| 行动 User Prompt | `_build_action_prompt()` | `llm_agent.py` |
| 行动 LLM Call | `_ask_json()` → `_ask_json_inner()` | `llm_agent.py` |
| 策略偏差注入 | `_build_strategy_bias_block()` | `llm_agent.py` |
| 检索策略注入 | `_build_retrieved_lessons_block()` | `llm_agent.py` |

---

## 3.8 Agent 三层结构总结

```
当前: Agent = Persona/Profile × Role × (strategy_bias + retrieved_knowledge)

但标记为:
  当前: Agent = Persona × Role × ???Strategy???

原因:
  - strategy_id 不存在
  - strategy_name 不存在
  - strategy_type 不存在
  - strategy_bias 是自由文本 dict, 不在 DB 中追踪
  - strategy_library.yaml 是参考文档, 代码未使用
  - retrieved_knowledge 有 doc_id 但无 strategy 维度的聚合

这导致:
  - 无法做 "Persona × Role × Strategy" 三层测评
  - 只能做 "Persona × Role" 二层测评
  - MBTI Dashboard 实际上是 Persona × Role 评测
```

---

## 3.9 关键审计结论

1. ✅ **Persona + MBTI + Background 完整进入 Prompt** — 30+人物, 每个有完整人设注入
2. ✅ **Role Prompt 完整进入** — 每个角色有独立系统提示 + 动作策略
3. ✅ **PlayerMind 参数化影响决策** — courage/suspicion/memory_bias 映射到行为参数
4. ⚠️ **Strategy 层半存在** — strategy_bias + 检索知识可用, 但无 strategy_id 追踪
5. ❌ **strategy_id 不存在** — 无法做 Persona × Role × Strategy 三层测评
6. ✅ **有 memory 机制** — 角色简要 + 每日总结 + 立场追踪
7. ✅ **Agent 能看到历史** — 发言/投票/技能信息通过 view + game_context 暴露
8. ✅ **LLM 失败有回退** — HeuristicAgent 作为 fallback, temperature 递减重试
