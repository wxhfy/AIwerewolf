# AI Werewolf — 端到端数据流 & 证据链

> 2026-06-05 | 验证: STRICT MODE PASSED | 全链路贯通
>
> 口径说明（2026-06-08）：本文主体记录 2026-06-05 strict run 的证据链快照。当前代码侧协议以 `backend/engine/models.py`、`backend/db/models.py`、`skills/40-agent-development.md`、`skills/50-api-contract.md` 为准；当前 ORM 映射为 20 张核心表，历史实验数据库可能含额外实验/快照表。

---

## 完整数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 1: 对局执行                                                     │
│                                                                     │
│ Game Engine (game.py)                                               │
│   │  _ask() → CognitiveAgent._decision() → AgentLoop.run()          │
│   │  _record_decision() → DecisionAudit (含 tool_trace + strategy IDs)│
│   ▼                                                                 │
│ agent_decisions 表                                                   │
│   observation: PlayerView (Agent 看到的完整信息)                       │
│   parsed_action._tool_trace: [{tool, query, results}]                │
│   parsed_action._auto_injected_strategies: [strategy_doc_ids]        │
│   raw_output: LLM 原始输出                                            │
│   decision: {speech, target_id/action payload by action_type}         │
│   model / tokens_used / latency_ms                                   │
└──────────────┬──────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PHASE 2: 赛后复盘分析 (Track B)                                               │
│                                                                      │
│ post_game.py / track_b.py                                            │
│   │  PerStepScorer.score_all(decisions, state, speech_acts)           │
│   │                                                                  │
│   ├── Tier 1 deterministic (85%):                                     │
│   │    vote: target alignment → correctness                           │
│   │    talk: speech_act stance + risk_flags + grounded_event_ids      │
│   │    night: action_type match against target role                   │
│   │                                                                  │
│   ├── Tier 2 light LLM review (12%):                                 │
│   │    ambiguous decisions (correctness ∈ [0.25, 0.75])               │
│   │    → single LLM review → light_llm_score / 10.0                   │
│   │                                                                  │
│   └── Tier 3 heavy LLM (3%):                                         │
│       high-impact + ambiguous (impact > 0.5)                          │
│       → 3-review panel with trimmed mean + Critic review              │
│       → heavy_llm_score / 10.0 + judge_agreement (std)                │
│                                                                      │
│   ▼                                                                  │
│ DecisionScore[] → ScoredStep[] (is_highlight / is_mistake 标记)       │
│   step_id | step_type | day | phase | role | step_score               │
│   is_highlight: score ≥ 0.75                                         │
│   is_mistake: score ≤ 0.30 + mistake_type                            │
│   retrieved_strategies: [strategy docs used]                          │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PHASE 3: 结构化复盘报告                                                │
│                                                                      │
│ track_b.py → generate_published_review_document()                     │
│   │                                                                  │
│   ├── PlayerReviewReport (per player)                                  │
│   │    game_id | player_id | role | persona_style | persona_mbti      │
│   │    scored_steps: [ScoredStep ...]                                 │
│   │                                                                  │
│   ├── CounterfactualAnalyzer                                          │
│   │    vote counterfactuals: "如果投了 X 会怎样"                        │
│   │    skill counterfactuals: "如果毒了 Y 会怎样" (effect_type=local)   │
│   │    speech counterfactuals: "如果发言内容不同"                        │
│   │                                                                  │
│   └── PublishedReview                                                 │
│        status=approved | score=1.0 | publish_allowed=True              │
│        markdown_report + html_report                                  │
│        validation_result + quality_passed                              │
│                                                                      │
│   ▼                                                                  │
│ evaluations 表 (21 条/局) + review_reports + published_reviews         │
│ leaderboard_entries 表 (34 条/局)                                     │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PHASE 4: 知识提取 (Track C)                                            │
│                                                                      │
│ KnowledgeAbstractor.abstract_from_game()                               │
│   │                                                                  │
│   ├── Per-step extraction (from ScoredStep):                          │
│   │    is_highlight → "这个决策好在哪里"                                │
│   │    is_mistake → "这个失误根因是什么 + 如何避免"                       │
│   │                                                                  │
│   ├── Reflection extraction (from CognitiveAgent._reflect_on_game()):  │
│   │    "这局我学到了什么"                                              │
│   │                                                                  │
│   └── AbstractedLesson[]                                              │
│        lesson_abstract | lesson_tags | evidence_event_ids              │
│        confidence_tier | visibility_scope | applicability_*            │
│                                                                      │
│   ▼                                                                  │
│ store_lessons_to_db()                                                 │
│   │  SAVEPOINT per row (逐条隔离)                                       │
│   │  Dedup check: source_game_id + source_report_ids                  │
│   │  experiment_id = TIER_EXPERIMENT_ID                               │
│   ▼                                                                  │
│ strategy_knowledge_docs 表 (status=candidate)                          │
│   maturity=raw | knowledge_epoch | version_group | doc_version          │
│   27 per_step + 72 reflection = 99 条/局                               │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PHASE 5: 知识进化                                                      │
│                                                                      │
│ promote.py (--mode quality/cluster/feedback/prune)                     │
│   │  candidate → active (晋级)                                         │
│   │  active → deprecated (quality decay / usage feedback)              │
│   ▼                                                                  │
│ strategy_knowledge_docs (status=active)                                │
│   L0-L3 可信度 + visibility_scope + applicability_conditions            │
│   quality_score | times_upvoted | contradiction_count                  │
│   maturity=refined/canonical | validated_at | supersedes_doc_ids        │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PHASE 6: 检索闭环                                                       │
│                                                                      │
│ StrategyRetriever (retrieval_prod.py)                                  │
│   │  Agent 工具调用检索 (BM25 + 倒排索引)                                │
│   │  4-filter 安全管线:                                                 │
│   │    1. confidence_allowed (L0-L3 only, L4/rejected blocked)         │
│   │    2. visibility_allowed (public/self/wolf/postgame)                │
│   │    3. leaks_current_game_private_info (no current-game leak)        │
│   │    4. applicability_matches (role/phase/rule/player_count)          │
│   │  rerank by relevance + quality + feedback + validated recency      │
│   │  filter superseded docs; raw candidates cannot outrank validated   │
│   │  refined/canonical descendants by recency alone                    │
│   ▼                                                                  │
│ Agent Prompt — Layer 3 策略层注入                                       │
│   → 下一局 CognitiveAgent 使用升级后的策略                                │
│   → Track C 自进化闭环                                                  │
└──────────────────────────────────────────────────────────────────────┘
```

Track C 的 Wiki/Hermes 增量设计详见 [`TRACK_C_HERMES_LLM_WIKI_DESIGN.md`](TRACK_C_HERMES_LLM_WIKI_DESIGN.md)。Wiki 只负责知识编译、人工审核和展示；正在对局的 Agent 仍只从经过生命周期和安全过滤的 runtime strategy pool 检索策略。

---

## 证据链 (Evidence Chain)

### 单条决策的完整追溯链路

```
GameEvent (引擎事件)
  event_id: "evt_abc123"
  type: "VOTE_CAST"
  payload: {voter_id, target_id, vote_weight}
       │
       ▼
AgentDecision (Agent 决策记录)
  decision_id: "dec_xyz789"
  observation: {PlayerView at decision time}
  parsed_action._tool_trace: [{tool: "search_strategies", query: "归票策略"}]
  parsed_action._auto_injected_strategies: ["doc_001", "doc_002"]
  decision: {vote_target: "player_3"}
       │
       ▼
DecisionScore (Track B 决策质量记录)
  decision_id: "dec_xyz789"
  correctness: 0.85
  scoring_tier: "deterministic"
  evidence: ["Target=Werewolf(wolf)", "Good vote!"]
       │
       ▼
ScoredStep (结构化步骤)
  step_id: "step_dec_xyz789"
  is_highlight: true (score ≥ 0.75)
  strategy_applied: true
  retrieved_strategies: [{doc_id: "doc_001", title: "归票策略"}]
       │
       ▼
AbstractedLesson (Track C 知识)
  source_event_ids: ["evt_abc123"]
  source_decision_ids: ["dec_xyz789"]
  lesson_abstract: "投票阶段归票狼人...时策略doc_001有效"
  evidence_event_ids: ["evt_abc123"]
       │
       ▼
StrategyKnowledgeDoc (持久化知识)
  id: "doc_new_001"
  source_game_ids: ["edbde010"]
  source_event_ids: ["evt_abc123"]
  confidence_tier: "L3_strategic"
  status: "candidate"
```

### 贯通率验证

| 指标 | 值 | 说明 |
|------|-----|------|
| `agent_decisions` 含 tool_trace | 26/27 (96.3%) | 每条决策带完整工具调用追踪 |
| `ScoredStep` 覆盖率 | 27/27 (100%) | 所有决策均进入复盘链路 |
| `source_event_ids` 贯通 | 100% | 知识文档回链到原始事件 |
| `source_game_ids` 贯通 | 100% | 知识文档回链到来源对局 |
| Active 池零污染 | 935→935 (delta=0) | strict mode 验证通过 |

---

## 验证结果

### Strict Mode Full Pipeline

```
$ python scripts/run_backend_full_strict.py
Game edbde010 | 7 players | 1 day | Village wins | 1553s
Active pool: 935 → 935 (delta=0)
Candidate pool: +194
Knowledge lessons: 99
STRICT MODE: PASSED
```

### 模块验收矩阵

| 模块 | 状态 | 关键指标 |
|------|------|----------|
| DB | ✅ | 历史 strict run 表结构通过；当前代码口径为 20 张核心 ORM 表 |
| LLM | ✅ | doubao-seed-2.0-pro OK |
| Game Engine | ✅ | 全流程跑通, 无跳过/死循环 |
| Agent Decision | ✅ | 26/27 带完整工具追踪 |
| Information Isolation | ✅ | 92/92 边界检查通过 |
| Strategy Retrieval | ✅ | Agent search < 500ms, 4-filter 正确 |
| Track B Review | ✅ | 100% 覆盖率, 三级复核链路正确 |
| Track B Review | ✅ | PublishedReview approved |
| Track C Knowledge | ✅ | 99 lessons, candidate 写入正确 |
| Track C Evolution | ⚠️ | Promote 逻辑正确, 待更多对局验证 |
| Experiment | ✅ | 4 tier 各 ≥ 12 局, Bootstrap 95% CI |
| Preflight | ✅ | 7/7 项预检通过 |
| Error Handling | ✅ | LLM strict/no-fallback 路径 + SAVEPOINT + 幂等守卫 |

---

*历史 strict run 证据链快照；当前接口以代码和 skills/50-api-contract.md 为准。*
