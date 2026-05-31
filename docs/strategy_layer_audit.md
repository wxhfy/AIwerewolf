# Part 5: 策略层实现审计

> 审计日期: 2026-05-28 | 状态: 只读 | 核心问题: Strategy 层是否真实存在？

---

## 5.1 策略相关资源总览

| 资源 | 位置 | 类型 | 是否被代码使用 |
|------|------|------|--------------|
| `strategy_library.yaml` | `configs/strategy_library.yaml` | 静态 YAML (~200条) | ❌ NOT_USED |
| `strategy_bias` | `llm_agent.py:__init__` | dict (运行参数) | ✅ YES |
| `RetrievedStrategyLesson` | `evolution.py` + DB | DB 检索结果 | ✅ YES |
| `RoleStrategyCard` | `evolution.py` + DB | DB 表 (Track C) | ⚠️ 间接 (通过检索) |
| `StrategyKnowledgeDoc` | `evolution.py` + DB | DB 表 (Track C) | ⚠️ 间接 (通过检索) |
| `StrategyPatch` | `evolution.py` + DB | DB 表 (Track C) | ❌ NOT_USED (仅 Track C API) |
| `ACTION_STRATEGIES` | `prompts.py` | 字典 (代码内嵌) | ✅ YES |
| `ACTION_PLAYBOOKS` | `playbooks.py` | 字典 (代码内嵌) | ✅ YES |
| `doubao_strategies.json` | `data/health/doubao_strategies.json` | JSON (提取产物) | ❌ 未知 |

---

## 5.2 逐资源详细审计

### 5.2.1 `configs/strategy_library.yaml` (静态策略库)

**状态: CONFIG_ONLY**

内容: ~200 条中文狼人杀策略，按角色分类:
- General: 38 条 (逻辑/发言/投票/心理)
- Seer: 20 条
- Witch: 16 条
- Hunter: 16 条
- Guard: 14 条
- Werewolf: 35 条
- Villager: 10 条
- BoardConfigs: 6 个板子
- GameTheory: 14 条
- ProPlay: 20 条

**代码引用检查**:
```bash
grep -r "strategy_library" /home/fyh0106/AIwerewolf/backend/ --include="*.py"
# 结果: (空) — 零引用
```

**结论**: 这是一个精心编写的策略知识库，但**后端代码没有读取它**。它可能是计划用于 GraphRAG 策略库的种子数据，或用于人工参考。

---

### 5.2.2 `strategy_bias` (运行时策略偏差)

**状态: IMPLEMENTED**

来源: `create_agents()` 中从 config 读取:
```python
strategy_bias = config.get("strategy_bias") 或 player_config.get("strategy_bias")
# 格式: {"speech_policy": ["...", "..."], "vote_policy": ["..."], ...}
```

注入位置: `llm_agent.py:_build_strategy_bias_block(action)`
- 根据 `STRATEGY_BIAS_PLACEMENT` 环境变量决定放在 system 或 user prompt 中
- 可选择性地按 action 过滤 (sections 参数)
- 语言: "高优先级，必须严格遵守，不得擅自偏离"

**限制**:
- `strategy_bias` 是自由文本 dict，**无 ID 追踪**
- 不写入 DB
- 不在 logs/opportunities/scoring 中记录
- 无法回溯 "这个 Agent 用了哪个策略"

---

### 5.2.3 `RetrievedStrategyLesson` (策略检索)

**状态: IMPLEMENTED**

来源: `llm_agent.py:update()` → `retrieve_strategy_knowledge(query)` → DB

检索查询参数: `role, phase, observation_summary, situation_tags, persona_mbti, persona_style`

注入位置: `llm_agent.py:_build_retrieved_lessons_block()`
- 格式化为 `[doc_id score=X.XX]` 标记块
- 包含: 触发条件、建议、理由
- 决策元数据中记录完整的检索信息

**限制**:
- 依赖 DB 中有策略知识文档 (Track C 产物)
- 检索质量取决于 Track C 策略抽取质量
- 每个 `doc_id` 有追踪但无 `strategy_id` 聚合

---

### 5.2.4 `RoleStrategyCard` (角色策略卡)

**状态: PARTIAL (Track C 产物, 间接使用)**

DB 表结构: `role, version, goal, speech_policy(JSON), vote_policy(JSON), skill_policy(JSON), risk_rules(JSON)`

使用路径:
1. Track C DreamJob 从 review 中提取知识 → 生成 StrategyPatch
2. VersionManager 应用 patch → 创建/更新 RoleStrategyCard
3. Agent 通过 `retrieve_strategy_knowledge()` 间接检索到相关条目

**限制**:
- Agent 不直接使用 RoleStrategyCard
- 通过检索间接访问，不是 "Agent 有 strategy_id: X"
- Track C 仍在实验阶段，策略卡可能质量不一

---

### 5.2.5 `ACTION_STRATEGIES` + `ACTION_PLAYBOOKS` (代码内嵌策略)

**状态: IMPLEMENTED**

这些是硬编码在 Python 中的角色×动作策略文本:
- `ACTION_STRATEGIES[action][role]` — 每个动作×角色的策略指导
- `ACTION_PLAYBOOKS[role]` — 每个角色的策略简述

直接进入 Prompt (通过 `get_action_strategy()` 和 `build_role_brief()`)。

**限制**:
- 不随版本变化 (硬编码)
- 不与 persona 交叉 (同一角色所有人物用同一套)
- 不记录 strategy_id

---

## 5.3 核心判断矩阵

| 问题 | 答案 | 证据 |
|------|------|------|
| Strategy 配置文件存在吗? | ✅ YES | `configs/strategy_library.yaml` (但未使用) |
| strategy_id 存在吗? | ❌ NO | 全项目搜索: 零结果 |
| strategy_name 存在吗? | ❌ NO | 全项目搜索: 零结果 |
| strategy_type 存在吗? | ❌ NO | 全项目搜索: 零结果 |
| 有 role-specific strategy 吗? | ✅ YES | `ACTION_STRATEGIES[action][role]` 是 role-specific |
| 有 persona-specific strategy 吗? | ⚠️ PARTIAL | strategy_bias 可以 per-player 配置, 但不是标准 persona×strategy 映射 |
| 有 strategy_version 吗? | ⚠️ PARTIAL | `optimization.py` 有占位符 "v0", RoleStrategyCard 有 version 字段 |
| 有策略选择逻辑吗? | ⚠️ PARTIAL | strategy_bias 从 config 选择, 检索从 DB 选择, 但没有 "选策略A还是B" 的显式逻辑 |
| 策略对行为产生实际影响吗? | ✅ YES | strategy_bias 进入 Prompt 影响 LLM 输出, 检索知识进入 Prompt |
| 有 GraphRAG 策略检索吗? | ⚠️ PARTIAL | `StrategyKnowledgeStore.retrieve()` 混合向量+BM25+FTS, 但非完整 GraphRAG |
| 有 strategy patch / C 自进化吗? | ✅ YES | `evolution.py` 完整实现 DreamJob → Patch → Validate → A/B Test → Promote |

---

## 5.4 当前 Strategy 数据流

```
config (strategy_bias dict)
  ↓
create_agents() → LLMAgent(strategy_bias)
  ↓
_build_strategy_bias_block() → System/User Prompt 块
  ↓
LLM 输出 (受策略偏差影响)
  ↓
AgentDecision.metadata (记录 retrieval_meta, 但不记录 strategy_bias)

同时:
Track C DreamJob → StrategyKnowledgeDocs → DB
  ↓
RetrieveStrategyKnowledge(query) → RetrievedStrategyLesson
  ↓
_build_retrieved_lessons_block() → User Prompt 块
  ↓
AgentDecision.metadata (记录 doc_id + score)
```

---

## 5.5 最小补齐方案: 使 Strategy 可追踪

要在未来做 "Persona × Role × Strategy" 三层测评，需要以下改动:

### Step 1: 定义 strategy_id
在 `configs/strategy_library.yaml` 中为每条策略定义 `id` 字段，或在 DB 的 `role_strategy_cards` 表用 `(role, version)` 作为复合 ID。

### Step 2: 记录 strategy_id
在以下位置记录:
1. **config/player profile**: `strategy_id: "seer_aggressive_v1"`
2. **LLMAgent**: `self.strategy_id = strategy_id`
3. **AgentDecision.metadata**: 添加 `strategy_id` 字段
4. **DecisionOpportunity**: 添加 `strategy_id` 字段
5. **PlayerScore/player record**: 添加 `strategy_id` 字段

### Step 3: 注入 strategy prompt
在 Prompt Builder 中:
```python
def _build_strategy_prompt(self):
    strategy = load_strategy(self.strategy_id)
    return format_strategy_prompt(strategy)
```

### Step 4: 策略测评
聚合时可以按 `(persona_id, role, strategy_id)` 分组计算 n, raw_win_rate, adjusted_win_lift, avg_role_normalized_pre_action_score 等。

---

## 5.6 关键审计结论

1. ❌ **`strategy_id` 在项目中不存在** — 这是做三层测评的最大障碍
2. ✅ **`strategy_library.yaml` 存在** — 高质量的静态策略库，但代码未使用
3. ✅ **策略偏差机制存在** — `strategy_bias` dict 能影响行为，但无追踪
4. ✅ **策略检索机制存在** — Track C 检索能推荐策略经验
5. ❌ **Strategy 和 MBTI/Persona 未解耦** — 策略不是独立的实验变量
6. ⚠️ **Track C 策略进化有完整实现** — 但处于实验阶段，未用于大规模对局
7. ⚠️ **无法做 Persona × Role × Strategy 三层测评** — 缺 strategy_id 追踪
