# AI Werewolf — 端到端数据流 & 证据链

> 2026-06-05 | 验证: STRICT MODE PASSED | 全链路贯通

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
│   decision: {speech, vote_target, skill_target}                      │
│   model / tokens_used / latency_ms                                   │
└──────────────┬──────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ PHASE 2: 赛后评分 (Track B)                                            │
│                                                                      │
│ post_game.py / track_b.py                                            │
│   │  PerStepScorer.score_all(decisions, state, speech_acts)           │
│   │                                                                  │
│   ├── Tier 1 deterministic (85%):                                     │
│   │    vote: target alignment → correctness                           │
│   │    talk: speech_act stance + risk_flags + grounded_event_ids      │
│   │    night: action_type match against target role                   │
│   │                                                                  │
│   ├── Tier 2 light LLM (12%):                                        │
│   │    ambiguous decisions (correctness ∈ [0.25, 0.75])               │
│   │    → single Judge LLM → light_llm_score / 10.0                    │
│   │                                                                  │
│   └── Tier 3 heavy LLM (3%):                                         │
│       high-impact + ambiguous (impact > 0.5)                          │
│       → 3-judge panel with trimmed mean + Critic review               │
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
│   │  rerank by quality_score                                           │
│   ▼                                                                  │
│ Agent Prompt — Layer 3 策略层注入                                       │
│   → 下一局 CognitiveAgent 使用升级后的策略                                │
│   → Track C 自进化闭环                                                  │
└──────────────────────────────────────────────────────────────────────┘
```

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
DecisionScore (Track B 评分)
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
| `ScoredStep` 覆盖率 | 27/27 (100%) | 所有决策都被评分 |
| `source_event_ids` 贯通 | 100% | 知识文档回链到原始事件 |
| `source_game_ids` 贯通 | 100% | 知识文档回链到来源对局 |
| Active 池零污染 | 1065→1065 (delta=0) | strict mode 验证通过 |

---

## 验证结果

### Strict Mode Full Pipeline

```
$ python scripts/run_backend_full_strict.py
Game edbde010 | 7 players | 1 day | Village wins | 1553s
Active pool: 1065 → 1065 (delta=0)
Candidate pool: +194
Knowledge lessons: 99
STRICT MODE: PASSED
```

### 模块验收矩阵

| 模块 | 状态 | 关键指标 |
|------|------|----------|
| DB | ✅ | 21 表, FK 约束完整 |
| LLM | ✅ | doubao-seed-2.0-pro OK |
| Game Engine | ✅ | 全流程跑通, 无跳过/死循环 |
| Agent Decision | ✅ | 26/27 带完整工具追踪 |
| Information Isolation | ✅ | 92/92 边界检查通过 |
| Strategy Retrieval | ✅ | Agent search < 500ms, 4-filter 正确 |
| Track B Scoring | ✅ | 100% 覆盖率, 三级级联正确 |
| Track B Review | ✅ | PublishedReview approved |
| Track C Knowledge | ✅ | 99 lessons, candidate 写入正确 |
| Track C Evolution | ⚠️ | Promote 逻辑正确, 待更多对局验证 |
| Experiment | ✅ | 4 tier 各 ≥ 12 局, Bootstrap 95% CI |
| Preflight | ✅ | 7/7 项预检通过 |
| Error Handling | ✅ | 降级链 + SAVEPOINT + 幂等守卫 |

---

*由小爪整理 (๑•̀ㅂ•́)و✧*
