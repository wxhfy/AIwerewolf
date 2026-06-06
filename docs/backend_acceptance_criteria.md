# 后端验收标准

> 最后更新: 2026-06-05 | 验证方式: `scripts/run_backend_full_strict.py`
> 最新结果: **STRICT MODE: PASSED** | Game `edbde010` | 7 人 1 天 | Village 胜 | 1553s
> Active 池: 1065→1065 (delta=0 零污染) | Candidate 池: +194 | 知识课程: 99 条

| 模块 | Status | 验收条件 | 失败条件 | 对应命令 | 输出文件 |
|------|--------|---------|---------|---------|---------|
| **DB** | ✅ Verified | PostgreSQL 可连接，21 张表存在（games/players/game_events/agent_decisions/game_snapshots/votes/evaluations/agent_versions/leaderboard_entries/review_reports/published_reviews/strategy_knowledge_docs/strategy_graph_links/role_strategy_cards/persona_role_adapters/strategy_patches/evolution_tournaments/knowledge_usage_feedback/evolution_rounds/personas/experiments/strategy_snapshots）；FK 约束完整（knowledge_usage_feedback 三外键） | 连接失败或表缺失 | `scripts/run_backend_full_strict.py` Phase 0 | `backend_e2e_report.json` |
| **LLM** | ✅ Verified | 客户端可用（doubao-seed-2.0-pro），health check JSON 返回 `ok`，同步调用 `chat_sync()` 返回合法响应 | client unavailable 或 health check 失败，或响应为空 | `create_client().chat_sync()` | - |
| **LLM 降级链** | ✅ Verified | 主模型可用时使用主模型；主模型失败后自动降级到备选模型；备选模型也失败时降级到 heuristic；9 个 env flag 控制 strict/fail-fast 行为 | 主模型不可用时对局直接崩溃，无降级逻辑 | Game Health Report 中的 `agent_downgrade_count` | `game_health_report.json` |
| **Game Engine** | ✅ Verified | 标准 7 人局全流程跑通（NIGHT_START → NIGHT_WOLF_ACTION → NIGHT_WITCH_ACTION → NIGHT_SEER_ACTION → NIGHT_GUARD_ACTION → NIGHT_RESOLVE → DAY_START → DAY_SPEECH → VOTE → DAY_RESOLVE → GAME_END），所有阶段按规则顺序执行，无跳过或死循环；赢棋检测在 _kill() 后立即触发；_check_win() 幂等守卫 | 阶段卡死、对局无法完成、技能结算错误 | `scripts/run_backend_full_strict.py` Phase 1 | `outputs/backend_e2e_report.json` |
| **Agent Decision** | ✅ Verified | 每个 Agent 在每个阶段产出合法决策（发言非空、投票目标为存活玩家、技能目标合法）；决策写入 `agent_decisions` 表含 metadata 列（tool_trace + strategy IDs）；26/27 决策带有完整工具追踪 | Agent 无响应超时后无降级；产出非法决策；decision 记录缺失关键字段 | `test_cognitive_agent.py` / `agent_loop.py` | `agent_decisions` 表 |
| **Information Isolation** | ✅ Verified | 92 项边界检查全部通过（verify_visibility_strict.py）；三级视图（自己/狼队友/其他）；非狼阵营看不到 `known_wolves`；村民看不到任何 private_events | 任意一项信息泄露 | `visibility.py` 的 `for_player()` 方法 | `isolation_check_result.json` |
| **Strategy Retrieval** | ✅ Verified | BM25 + 倒排索引检索在 500ms 内返回结果；4-filter 安全管线（confidence→visibility→privacy→applicability）正确过滤；applicability_matches 支持 global role 和空 phase；工具调用在 strict 模式下不崩溃（空结果返回友好提示） | 检索超时 > 2s；4-filter 过滤所有结果（已修复）；candidate/deprecated 文档泄露 | `retrieval_prod.py` + `knowledge_confidence.py` | `retrieval_eval_results.json` |
| **Anti-Pattern Injection** | ✅ Verified | 当开启 anti_pattern 时，角色策略卡的 anti_pattern 层正确注入到 LLM prompt 中；覆盖 6 个基础角色（Seer/Witch/Hunter/Guard/Villager/Werewolf）+ WhiteWolfKing | anti_pattern 未注入或被忽略；反模式文本被截断 | `test_cognitive_integration.py` | `anti_pattern_injection_verify.json` |
| **Knowledge Snapshot** | ⚠️ Partially | 实验前可创建 strategy_snapshot，记录当前 active docs 的 id + active_count；实验期间 TIER_EXPERIMENT_ID 隔离防止交叉污染。TODO: 添加 content_hash 支持 | snapshot 创建失败或内容为空；实验期间 active 池被新 lesson 污染 | `multi_tier_experiment.py` 子进程中的 DB count 查询 | 写入 JSONL 的 `strategy_snapshot` 字段 |
| **Track B Scoring (PerStepScorer)** | ✅ Verified | Tier 1 对所有决策产出初始 correctness 分（100% 覆盖率，27/27）；Tier 2 对 ambiguous 决策触发单 Judge LLM（light_llm_score 正确归一化 /10.0）；Tier 3 对 high-impact 决策触发三 Judge Panel（score_step_with_panel 逐决策评分，非全游戏评分）；每个 ScoredStep 包含 is_mistake/is_highlight 标记 | 评分缺失；Tier 分级逻辑错误；is_mistake 标记与实际判断偏离 > 30% | `per_step_scorer.py` + `llm_judge.py` | `scored_steps.json` |
| **Track B Review (PlayerReviewReport)** | ✅ Verified | 每局产出 1 份 PublishedReview（status=approved, score=1.0）；21 条 Evaluation 记录；34 条 LeaderboardEntry；PlayerReviewReport 含 ScoredStep 列表 + 角色 + persona 信息 | 玩家 report 缺失；report 中 step_id 与 agent_decisions 无法对应 | `track_b.py` `generate_published_review_document()` | `review_report.json` |
| **Track C Knowledge (KnowledgeAbstractor)** | ✅ Verified | 每局赛后从 ScoredStep 提取 lessons（27 per_step + 72 reflection = 99 条）；lessons 正确写入 `strategy_knowledge_docs` 表 status='candidate'（P0 bug 已修复）；SAVEPOINT 逐条隔离防止单条失败回滚整批；source_game_id + experiment_id 正确传播 | 赛后未产出任何 lesson；lesson 错误自动晋升到 active | `knowledge_abstractor.py` + `track_b.py` `_extract_and_store_knowledge()` | `abstracted_lessons.jsonl` |
| **Track C Evolution Loop** | ⚠️ Partially | candidate lesson 可通过 `promote.py --mode quality/cluster/feedback/prune` 晋升到 active；`update_usage()` 基于实际使用反馈降级（3+ 次使用全部无效 → deprecated）；`promote_candidates()` 不会重提已被 usage 降级的文档；权威生命周期文档化在 evolution.py 顶部 | 晋升逻辑失效；active 池被低质量 lesson 污染 | `evolution.py` + `scripts/promote.py` | `evolution_loop_verify.json` |
| **Experiment (多 Tier 对比)** | ✅ Verified | 4 个 Tier 至少各 12 局完成（默认）；跨 Tier 同 offset seed 保证 MBTI 分配公平；TIER_EXPERIMENT_ID 隔离各 tier 知识池；输出 Bootstrap 95% CI + 描述性统计 | 任何 Tier 未完成；seed 映射错误；跨 tier 知识污染 | `multi_tier_experiment.py` | `summary.json` + `{tier}.jsonl` |
| **Experiment Leaderboard** | 📋 Planned | 按胜率 + 过程分 + 策略使用率三维排名，Tier 间可区分；至少 one tier 在至少 one metric 上显著优于 baseline（p < 0.05） | 所有 tier 无显著差异；排名与预期方向相反 | `multi_tier_experiment.py` + 统计检验 | `leaderboard.json` |
| **Report Export** | ✅ Verified | 支持导出结构化 JSON 报告（`outputs/backend_e2e_report.json`）+ Markdown 报告（`outputs/backend_e2e_report.md`）；含 game 信息、db_verify、artifacts、evidence_chain_sample、log_scan；整体 PASS/FAIL 判定 | 报告导出失败或数据不完整 | `scripts/run_backend_full_strict.py` Phase 6 | `outputs/backend_e2e_report.json` + `.md` |
| **Preflight / Health Check** | ✅ Verified | `backend/ops/preflight.py` 7 项预检：imports、db_connection、db_tables、db_write、llm_client、active_strategies、pool_config；`init_db()` 幂等守卫 `_db_initialized` | 任意一项预检失败 | `backend/ops/preflight.py` | `preflight.log` |
| **Error Handling / Resilience** | ✅ Verified | LLM 调用重试（指数退避）；DB 连接断开由子进程 try/except 处理；SAVEPOINT 逐行隔离 INSERT 失败；`_check_win()` 幂等守卫防重复 GAME_END；`_witch_phase()` 丢弃无效决策时 WARNING 日志 | 未捕获异常导致进程退出；error log 丢失 | Game Health Report 中的 `error_count` | JSONL 中的 `error` 字段 |
| **Configuration Validity** | ✅ Verified | `rule_variant_standard.yaml` 语法正确、7-12 人角色分配与 RoleRegistry 一致、阶段顺序符合狼人杀规则；`strategy_library.yaml` 187 条策略全部 ≤ 60 字符、BoardConfigs/VillageCoordination/ProPlay 已接入 StrategyRegistry | 配置文件解析失败；角色名不存在；字段缺失 | 引擎初始化时自动校验 | `config_validation.log` |
| **Concurrency / Multi-Game** | ✅ Verified | 同时运行 4 局不冲突（独立 game_id + 独立 agent_decisions + 独立 DB 连接）；`_STRATEGY_LOCK` 线程锁保护全局可变字典；连接池 10+10=20 | 竞态导致数据写错行、game_id 冲突、DB 死锁 | `multi_tier_experiment.py` 4 tier 并行子进程 | 每个 tier 独立 JSONL |

## 完整数据流验证

```
Game Engine (game.py)
  │  _ask() → agent._decision() → AgentLoop.run()
  │  _record_decision() → DecisionAudit (含 metadata)
  ▼
AgentDecision (PostgreSQL agent_decisions 表)
  │  post_game.py / track_b.py 读取
  ▼
PerStepScorer.score_all()
  │  Tier1 deterministic → Tier2 light_llm → Tier3 heavy_llm
  ▼
DecisionScore[] → ScoredStep[] → PlayerReviewReport[]
  │  _extract_and_store_knowledge() (track_b.py)
  ▼
KnowledgeAbstractor.abstract_from_game()
  │  → AbstractedLesson[] → store_lessons_to_db()
  ▼
StrategyKnowledgeDoc (PostgreSQL strategy_knowledge_docs 表)
  │  status=candidate → promote.py → active
  ▼
StrategyRetriever (BM25 + 倒排索引)
  │  retrieve_strategies_prod() → 4-filter safety → AgentLoop.run()
  ▼
下一局 Agent Prompt (Track C 自进化闭环)
```

## LLM Judge 补充说明

- **Critic round**: 已通过 `score_step_with_panel()` 实现 — 三法官分别评分 → trimmed mean 聚合 → 可选 Critic 审查分歧 > 0.3 时介入（权重 25%）
- **Judge 输出解析**: 使用 `re.search(r'\{.*\}', raw)` + `json.loads`，对 markdown 代码块格式敏感
- **三法官串行调用**: 同一 LLM 以不同 system prompt 调用三次，非真正并行异构
- **PerStepScore.judge_agreement**: 新增字段记录三法官标准差，供质量评估
