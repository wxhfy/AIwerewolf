# Retrieval Policy Design

> Track C 策略检索的分层 Policy 架构设计文档
> 日期：2026-06-05

## 设计目标

AIwerewolf 的 Agent 检索策略知识时，不应该无差别地看到所有策略。我们需要分层检索：Agent 优先看到与自己角色、MBTI、阵营相关的策略，全局通用策略作为兜底。

## Retrieval Policy 枚举

```python
class RetrievalPolicy(str, Enum):
    GLOBAL_ONLY = "global_only"
    SELF_MBTI_ONLY = "self_mbti_only"
    SAME_ROLE_ALL_MBTI = "same_role_all_mbti"
    SAME_ROLE_SAME_MBTI = "same_role_same_mbti"
    HYBRID_ROLE_MBTI_GLOBAL = "hybrid_role_mbti_global"
    HYBRID_ROLE_ALIGNMENT_PHASE = "hybrid_role_alignment_phase"
```

## 各 Policy 过滤逻辑

### Policy A: GLOBAL_ONLY

只检索全局通用策略。
```
role == "global" OR role is None
```
**用途**: 基线对照。测试"没有任何个性化检索"的效果。

### Policy B: SELF_MBTI_ONLY

只检索与 Agent 相同 MBTI 的策略。
```
mbti_scope == current_mbti OR mbti_scope is empty
```
**用途**: 测试"只读自己人格 wiki"是否有效。预期风险：数据稀疏。

### Policy C: SAME_ROLE_ALL_MBTI

检索同角色的所有策略，不限制 MBTI。
```
role == current_role OR role == "global"
```
**用途**: 测试"同职业经验优先"是否比 MBTI 隔离更有效。

### Policy D: SAME_ROLE_SAME_MBTI

最严格：同角色 + 同 MBTI。
```
role == current_role AND mbti_scope == current_mbti
```
**用途**: 最个性化。预期风险：数据极度稀疏。

### Policy E: HYBRID_ROLE_MBTI_GLOBAL（推荐默认）

3 层分层检索：
```
Bucket 1: same_role + same_mbti     (最优先)
Bucket 2: same_role + any_mbti      (次优)
Bucket 3: global                    (兜底)
```

自动注入配比 (top-3): 1:1:1
主动搜索配比 (top-5): 2:2:1

### Policy F: HYBRID_ROLE_ALIGNMENT_PHASE

在 Policy E 基础上增加 phase 约束：
```
Bucket 1: same_role + same_mbti + same_phase
Bucket 2: same_role + any_mbti
Bucket 3: same_alignment + any_mbti
Bucket 4: global
```

## Agent Context

每次检索传入 `AgentContext`：
```python
@dataclass
class AgentContext:
    player_id: str
    role: str           # "Seer", "Werewolf", etc.
    alignment: str      # "village" or "wolf"
    mbti: str           # "INTJ", "ENFP", etc.
    phase: str          # "DAY_SPEECH", etc.
    action_type: str    # "talk", "vote", "attack", etc.
    day: int
    alive_status: bool
    keywords: list[str]
```

## Scope 字段来源

当前 schema 没有专门的 `mbti_scope`、`role_scope` 等字段。最小兼容方案从现有列推导：

| Scope 字段 | 来源 |
|-----------|------|
| `role_scope` | `role` 列 (role="global" 表示 any) |
| `mbti_scope` | 从 `persona_scope` 解析 ("mbti:INTJ+role:Werewolf" → "INTJ") |
| `alignment_scope` | 从 `role` 推导 (Werewolf→wolf, 其他→village) |
| `phase_scope` | `phase` 列 (phase="global" 表示 any) |
| `action_scope` | 当前 schema 不支持，预留为空 |

## 检索 API 入口

所有检索入口都接受 `retrieval_policy` 和 `agent_context` 参数：

- `retrieve_strategies_prod(role, phase, ..., retrieval_policy, agent_context, mbti, alignment)`
- `StrategyRetriever.search_with_keywords(keywords, ..., retrieval_policy, agent_context)`
- `tools.search_strategies(keywords, ..., retrieval_policy)`

默认 `retrieval_policy=GLOBAL_ONLY` 保持向后兼容。

## Trace 记录

每次检索返回扩展 dict：
```
doc_id, situation, strategy, quality, doc_type,
rank, bucket, retrieval_policy,
role_scope, mbti_scope, phase_scope, alignment_scope, action_scope,
source_game_id, source_decision_id, status
```

AgentLoop tool_trace 增加：`policy`, `bucket`, `mbti`, `role`。

## 实验评估

两种评估方式：

1. **离线检索精度** (`scripts/evaluate_retrieval_policies.py`):
   - 固定 26 条 query set (6 角色 × 4+ MBTI)
   - 计算 P@1/3/5, Recall@3/5, MRR, nDCG@3/5, Coverage Rate
   - 弱标注 + LLM judge 相关性打分

2. **在线对局效果** (`scripts/run_retrieval_policy_ablation.py`):
   - 7 组 × N 局 paired seed comparison
   - 指标: process_score, vote_accuracy, speech_quality, skill_efficiency
   - Bootstrap 95% CI + Cohen's d + permutation test

## 文件清单

| 文件 | 角色 |
|------|------|
| `backend/agents/cognitive/retrieval_prod.py` | RetrievalPolicy + filter_by_policy + 改造后的 API |
| `backend/agents/cognitive/tools.py` | search_strategies 支持 retrieval_policy |
| `backend/agents/cognitive/agent_loop.py` | AgentLoop 传递 mbti/alignment 到检索 |
| `scripts/evaluate_retrieval_policies.py` | 离线检索精度评估 |
| `scripts/run_retrieval_policy_ablation.py` | 在线对局效果消融 |
| `docs/retrieval_policy_design.md` | 本文档 |
| `docs/retrieval_grep_analysis.md` | Grep 检索精度分析 |
