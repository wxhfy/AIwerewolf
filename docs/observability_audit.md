# Part 7: 日志与可观测性审计

> 审计日期: 2026-05-28 | 状态: 只读 | 核心问题: 能否追踪每个 Agent 的输入/输出/决策？

---

## 7.1 日志类型与位置

| 日志类型 | 存储位置 | 格式 | 是否持久化 |
|----------|---------|------|-----------|
| 游戏事件 (GameEvent) | DB `game_events` 表 + 内存 `GameState.events` | SQL/JSON | ✅ |
| Agent 决策 (AgentDecision) | DB `agent_decisions` 表 | SQL/JSON | ✅ |
| 决策审计 (DecisionAudit) | 内存 `GameState.decision_records` | Python dataclass | ⚠️ 仅内存，对局结束写入 DB |
| 投票记录 (Vote) | DB `votes` 表 | SQL | ✅ |
| 游戏快照 (GameSnapshot) | DB `game_snapshots` 表 | JSON | ✅ |
| 评测报告 (PublishedReview) | DB `published_reviews` 表 | JSON+Markdown | ✅ |
| 知识反馈 (KnowledgeUsageFeedback) | DB `knowledge_usage_feedback` 表 | SQL | ✅ |
| 批量日志 | `data/health/llm_batch_*.jsonl` | JSONL | ✅ |
| 多种子日志 | `data/health/multi_seed_*.log` | 文本 | ✅ |
| LLM Request/Response | 无独立存储 | - | ❌ NOT_STORED |

---

## 7.2 逐类型详细审计

### 7.2.1 游戏事件 (GameEvent)

**记录时机**: 每个游戏动作发生时立即记录 (`_log()` / `_log_decision()`)

**包含字段**:
```python
id, timestamp, day, phase, event_type, visibility, actor_id, target_id, payload, visible_to
```

**覆盖范围**:
| 事件类型 | 是否记录 |
|----------|---------|
| GAME_START | ✅ |
| PHASE_CHANGED | ✅ |
| PRIVATE_INFO (角色分配/查验结果/夜晚信息) | ✅ |
| CHAT_MESSAGE (发言) | ✅ |
| NIGHT_ACTION (夜晚动作) | ✅ |
| VOTE_CAST (投票) | ✅ |
| PLAYER_DIED (死亡) | ✅ |
| HUNTER_SHOT (猎人开枪) | ✅ |
| WHITE_WOLF_KING_BOOM (白狼王自爆) | ✅ |
| SYSTEM_MESSAGE | ✅ |
| GAME_END | ✅ |

**可追溯性**:
- ✅ 每个 event 有 event_id (UUID)
- ✅ 每个 event 关联 day/phase/actor_id
- ✅ visibility 字段区分 public/private
- ✅ visible_to 字段列出可查看的玩家

### 7.2.2 Agent 决策 (AgentDecision)

**记录时机**: `_record_decision()` → 对局结束时批量写入 DB

**包含字段**:
```python
game_id, player_id, day, phase,
observation (JSON),        # ← 当时的完整可见状态
legal_actions (JSON),       # ← 当时允许的行动列表
prompt_version,             # ← Prompt 版本号
raw_output,                 # ← LLM 原始输出文本 (✅ 记录了!)
parsed_action (JSON),       # ← 解析后的结构化决策 (✅ 记录了!)
is_valid, error_type,      # ← 是否有效/解析失败原因
latency_ms,                 # ← LLM 延迟
prompt_tokens, completion_tokens  # ← Token 用量
```

**可追溯性**:
- ✅ 每个 decision 有 decision_id (来源 `decision_records`)
- ✅ 关联 player_id / role / day / phase
- ✅ 记录 LLM 原始输出 (raw_output)
- ✅ 记录结构化决策 (parsed_action)
- ❌ **不记录完整 final prompt** — observation 包含状态快照，但不包含完整的 system + user prompt 文本
- ✅ 记录 token 用量和延迟

### 7.2.3 决策审计 (DecisionAudit)

**记录时机**: `_record_decision()` — 每次 Agent 决策后立即记录在内存中

**包含字段**:
```python
observation_snapshot,  # 当时状态
prompt_version,        # Prompt 版本
raw_output,            # LLM 原始输出
parsed_action,         # 结构化决策
error,                 # 解析错误
latency_ms,            # 延迟
token_usage            # Token 用量
```

**注意**: `observation_snapshot` 是状态快照，**不是完整 prompt**。完整 prompt (system + user) 在 `_ask_talk_wolfcha()` 或 `_ask_json()` 中生成但**不单独存储**。

### 7.2.4 私有信息记录

- ✅ 夜晚信息通过 PRIVATE_INFO 事件记录
- ✅ 狼人团队信息通过 known_wolves 在 PlayerView 中暴露
- ✅ V7 private context scoring 有 `visibility_context_snapshots_v7.jsonl`
- ❌ **private context 不单独存日志文件** — 它嵌入在 GameEvent + PlayerView.private_events 中

### 7.2.5 Opportunity Extraction Log

**文件**: `data/health/opportunities.jsonl`

每条包含:
```python
opportunity_id, game_id, player_id, role, persona_id,
opportunity_type, chosen_action,
public_context_summary, private_context_summary,
target_features, game_features, outcome_features,
evidence_event_ids, source_decision_id
```

- ✅ 每个机会关联 evidence_event_ids (可追踪回原始事件)
- ✅ 记录 persona_id
- ❌ 不记录 strategy_id (字段不存在)
- ⚠️ `camp_won` 始终为 None (bug, `outcome_features_builder` 未接收 winner)

### 7.2.6 Scoring Log

**各版本中间文件**: `data/health/opportunity_scores_v{2-7}.jsonl`

每条包含:
```python
opportunity_id, pre_action_score, outcome_impact_score,
final_score, confidence, quality_level
```

- ✅ 分数可追踪到 opportunity_id → decision_id → event_ids
- ⚠️ 版本间文件命名不一致 (v2到v7独立文件)
- ❌ 无统一 scoring log 表

### 7.2.7 Valid Agent Log

**文件**: `data/health/validation_result.json` + `data/health/validation_result_v2.json`

- ✅ 记录每局的 agent validation (解析成功率/回退次数/信息泄露/无效动作)
- ⚠️ 两个文件版本，不清楚哪个是当前版本

---

## 7.3 可追溯性矩阵

| 问题 | 答案 | 证据 |
|------|------|------|
| 每个 action 有 event_id? | ✅ YES | GameEvent.id (UUID) |
| 每个 decision 能追溯到 actor/role/phase? | ✅ YES | AgentDecision 有 player_id/day/phase |
| 记录 final prompt? | ❌ NO | observation_snapshot 有状态但不含完整 prompt 文本 |
| 记录 Agent 输出原文? | ✅ YES | raw_output + parsed_action |
| 记录结构化 decision JSON? | ✅ YES | parsed_action (JSON) |
| 记录 evidence_event_ids? | ✅ YES | DecisionOpportunity.evidence_event_ids |
| 能从 HTML 报告点击回原始事件? | ⚠️ PARTIAL | HTML 中有 event_id 引用，但无可点击链接 |
| 能验证信息隔离? | ✅ YES | VisibilitySafetyGate 检查私有信息泄露 |
| 能追踪 LLM token 用量? | ✅ YES | prompt_tokens + completion_tokens |
| 能追踪 LLM 延迟? | ✅ YES | latency_ms |
| 能追踪 Persona? | ✅ YES | persona_id 在 opportunity + player record 中 |
| 能追踪 Strategy? | ❌ NO | strategy_id 不存在 |

---

## 7.4 可观测性缺口

### P0: Final Prompt 未记录
**影响**: 无法事后审查 Prompt 是否包含污染信息、是否正确注入 Persona/Strategy。
**建议**: 在 `_record_decision()` 中增加 `full_prompt` 字段 (可选, 因为 prompt 可能很长)。

### P1: Strategy ID 未追踪
**影响**: 无法做策略维度的测评。
**建议**: 见 Part 5 最小补齐方案。

### P1: 无统一 Scoring Log 表
**影响**: 各版本分数分散在独立文件中，难以跨版本对比。
**建议**: 在 DB 中增加 `opportunity_scores` 表，统一存储各版本分数。

### P2: LLM Request/Response 无独立存储
**影响**: 无法事后分析 LLM 调用失败原因。
**建议**: 增加 `llm_call_logs` 表或在 `agent_decisions` 中增加 `system_prompt` / `user_prompt` 字段。

---

## 7.5 关键审计结论

1. ✅ **游戏事件日志完整** — 所有事件类型有 EventType 枚举, 带 UUID + 时间戳
2. ✅ **Agent 决策有审计追踪** — raw_output + parsed_action + latency + tokens
3. ❌ **Final Prompt 未记录** — 只有 observation_snapshot, 无完整 system + user prompt
4. ✅ **结构化 Decision JSON 被记录** — parsed_action 字段
5. ✅ **evidence_event_ids 被记录** — Opportunity 可追踪回原始事件
6. ⚠️ **HTML 报告不能直接跳转到原始事件** — event_id 有但无超链接
7. ✅ **信息隔离可验证** — VisibilitySafetyGate
8. ❌ **Strategy 不可追踪** — strategy_id 不存在
