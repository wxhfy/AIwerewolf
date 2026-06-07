# 数据来源审计报告

## 1. 扫描范围

本轮审计基于当前仓库、输出文件和本地 PostgreSQL。扫描范围：

| 范围 | 内容 |
|---|---|
| 文档 | `README.md`、`docs/DOC_INDEX.md`、`docs/PROJECT_STATUS.md`、`docs/ARCHITECTURE.md`、`docs/DATA_FLOW.md`、`docs/backend_acceptance_criteria.md`、`docs/evidence_chain_demo.md`、`docs/experiment_protocol.md`、`docs/retrieval_policy_design.md`、`docs/experiments/`、`docs/goal.md` |
| 后端 | `backend/app.py`、`backend/engine/`、`backend/agents/`、`backend/agents/cognitive/`、`backend/eval/`、`backend/db/`、`backend/ops/` |
| 前端 | `frontend/` |
| 配置 | `configs/` |
| 脚本 | `scripts/run_backend_full_strict.py`、`scripts/verify_visibility_strict.py`、`scripts/evaluate_retrieval_policies.py`、`scripts/run_winrate_experiment.py`、`scripts/multi_tier_experiment.py`、`scripts/promote.py`、`scripts/analyze_score_distributions.py` 及相关 eval / retrieval / experiment 脚本 |
| 输出目录 | `outputs/`、`data/experiment/`、`data/health/`、`reports/`、`logs/`、`artifacts/`、`docs/experiments/` |
| 数据库 | PostgreSQL container `werewolf-pg`，database `werewolf` |

风险关键词扫描范围覆盖文件名与关键输出内容，关键词包括：`fallback`、`mock`、`dummy`、`sample`、`demo`、`placeholder`、`fake`、`heuristic`、`dry_run`、`test_only`、`synthetic`、`simulated`、`estimated`、`approx`、`TODO`、`待确认`。

## 2. 找到的原始数据文件

| 文件 | 类型 | 内容 | 可解析 | 是否正式数据 | 风险关键词 | 说明 |
|---|---|---|---|---|---|---|
| `outputs/backend_e2e_report.json` | JSON | strict mode 全链路报告 | 是 | 是 | fallback/unavailable 在 log_scan | 作为 strict 验收主来源 |
| `outputs/backend_e2e_report.md` | Markdown | strict mode 人读报告 | 是 | 是 | fallback/unavailable | 与 JSON 一致，辅助引用 |
| `outputs/backend_e2e_strict.log` | LOG | strict 运行日志 | 是 | 是，限上下文审计 | fallback/skip/unavailable/disabled | 不直接做指标，做风险解释 |
| `outputs/visibility_strict_report.log` | LOG | 信息隔离 smoke | 是 | 是 | 无文件名风险 | 92 passed / 0 failed |
| `outputs/retrieval_policy_eval/results.json` | JSON | 检索策略评估 | 是 | 是 | 无文件名风险 | 26 queries / 935 docs |
| `outputs/retrieval_policy_eval/results.csv` | CSV | 检索策略指标表 | 是 | 是 | 无文件名风险 | 与 JSON 一致 |
| `outputs/retrieval_policy_eval/summary.md` | Markdown | 检索评估摘要 | 是 | 是 | 无文件名风险 | 辅助引用 |
| `outputs/retrieval_policy_eval/per_query_details.jsonl` | JSONL | 每 query 细节 | 是 | 是 | 无文件名风险 | 可支撑细查 |
| `data/experiment/batch_summary.json` | JSON | 20 局批量实验摘要 | 是 | 是 | 无文件名风险 | 20/20 成功，seeds 300-319 |
| `data/experiment/game_state_seed*.json` | JSON | 44 个 game state 文件 | 是 | 部分 | 无文件名风险 | 缺统一实验 metadata，不聚合成正式 44 局结论 |
| `data/experiment/multi_tier/*.jsonl` | JSONL | multi-tier 当前输出 | 文件存在但 0 字节 | 否 | 无文件名风险 | 不能用于正式对比 |
| `data/experiment/multi_tier_bak_13g/*.jsonl` | JSONL | multi-tier 备份记录 | 是 | 否 | 无文件名风险 | 与 summary 冲突 |
| `data/experiment/multi_tier_bak_13g/summary.json` | JSON | multi-tier 备份摘要 | 是 | 否 | 无文件名风险 | 每 tier game_count=0, error_count=1 |
| `outputs/winrate_experiment_seed2001.log` | LOG | winrate 脚本日志 | 是 | 否 | 无文件名风险 | 日志尾部显示只完成 2 局，JSON/MD 不存在 |
| `outputs/winrate_experiment.log` | LOG | winrate 简短日志 | 是 | 否 | 无文件名风险 | 信息不足 |
| `data/experiment/heuristic_20games.json` | JSON | heuristic 20 局 | 是 | 否 | heuristic | 不可支持 LLM-only 正式结论 |
| `data/experiment/dry_run_*.log` | LOG | dry run | 是 | 否 | dry_run | 只能作为调试记录 |
| `data/health/llm_batch_acceptance_fake_*` | JSON/JSONL | fake acceptance | 是 | 否 | fake | 不能作真实 LLM 数据 |
| `data/health/human_pairwise_labels_sample.jsonl` | JSONL | sample labels | 是 | 否 | sample | 只能作样例 |
| `data/health/track_b_rubric_demo_summary.json` | JSON | demo rubric | 是 | 否 | demo | 只能作展示 |
| `docs/experiments/demo_artifacts/*` | HTML | demo 报告 | 是 | 否 | demo | 不能作正式实验 |
| `docs/assets/closure/*.svg` | SVG | 结项图标、架构图、闭环图、证据链图 | 是 | 是，作为图表素材 | 无 | 由 `scripts/generate_closure_visual_assets.py` 确定性生成 |
| `docs/assets/closure/real-game-snapshot.html` | HTML | 真实 strict 对局总览页面 | 是 | 是，作为截图源 | 无 | 来源为 replay API + strict report |
| `docs/assets/closure/strict-game-review.html` | HTML | 真实 Track B 复盘页面 | 是 | 是，作为截图源 | 无 | 来源为后端 review HTML 接口 |
| `docs/assets/closure/screenshots/*.png` | PNG | 结项图表截图和真实对局截图 | 是 | 是，作为报告图片 | 无 | 由 `scripts/capture_closure_screenshots.js` 使用 Playwright 生成 |

目录文件扫描摘要：

| 目录 | 文件数 | 非空文件 | 0 字节文件 | 文件名风险命中 |
|---|---:|---:|---:|---|
| `outputs` | 10 | 10 | 0 | 无 |
| `data/experiment` | 191 | 187 | 4 | dry_run 4，heuristic 1 |
| `data/health` | 351 | 345 | 6 | fake 6，demo 1，sample 1，error 2 |
| `logs` | 1 | 1 | 0 | 无 |
| `docs/experiments` | 5 | 5 | 0 | demo 4 |

## 3. 数据库连接与查询结果

数据库可连接。连接方式：Docker 容器 `werewolf-pg`，命令：

```bash
docker exec werewolf-pg psql -U werewolf -d werewolf
```

查询时刻：`2026-06-06 10:45:50 UTC`。查询时发现仍有本仓库相关后台对局进程写库，因此数据库统计全部按“查询时刻快照”使用。

### 3.1 表清单

当前 public schema 有 22 张 base table：

`agent_decisions`、`agent_versions`、`evaluations`、`evolution_rounds`、`evolution_tournaments`、`experiments`、`game_events`、`game_snapshots`、`games`、`knowledge_usage_feedback`、`leaderboard_entries`、`persona_role_adapters`、`personas`、`players`、`published_reviews`、`review_reports`、`role_strategy_cards`、`strategy_graph_links`、`strategy_knowledge_docs`、`strategy_patches`、`strategy_snapshots`、`votes`。

文档历史口径有“21 张表”，当前实测为 22 张，报告采用数据库实测并标注不一致。

### 3.2 核心表记录数

| 表 | 记录数 |
|---|---:|
| `games` | 9001 |
| `players` | 79887 |
| `game_events` | 442880 |
| `game_snapshots` | 2633 |
| `agent_decisions` | 188248 |
| `evaluations` | 63129 |
| `published_reviews` | 2625 |
| `strategy_knowledge_docs` | 20575 |
| `knowledge_usage_feedback` | 52191 |
| `leaderboard_entries` | 34 |
| `experiments` | 0 |
| `evolution_rounds` | 6 |
| `evolution_tournaments` | 6 |

### 3.3 关键分布

| 指标 | 分布 |
|---|---|
| game status | finished 8987，running 14 |
| winner | village 2655，wolf 6332，空 14 |
| knowledge status | active 935，candidate 19456，deprecated 184 |
| players by role | Guard 8994，Hunter 9001，Seer 9001，Villager 20257，Werewolf 18009，WhiteWolfKing 5624，Witch 9001 |
| decisions by action | vote 74057，talk 68986，attack 18018，skip 10039，guard 8482，divine 6407，shoot 1544，witch_save 520，witch_poison 131，boom 64 |

### 3.4 关键 SQL

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE'
ORDER BY table_name;

SELECT 'games', count(*) FROM games
UNION ALL SELECT 'players', count(*) FROM players
UNION ALL SELECT 'game_events', count(*) FROM game_events
UNION ALL SELECT 'agent_decisions', count(*) FROM agent_decisions
UNION ALL SELECT 'strategy_knowledge_docs', count(*) FROM strategy_knowledge_docs;

SELECT status, count(*)
FROM strategy_knowledge_docs
GROUP BY status
ORDER BY status;

SELECT COALESCE(parsed_action::jsonb->>'action_type',
                parsed_action::jsonb->>'type',
                parsed_action::jsonb->>'action') AS action_kind,
       count(*)
FROM agent_decisions
GROUP BY action_kind
ORDER BY count(*) DESC;
```

## 4. 文档记录但无原始数据的指标

| 指标 | 文档来源 | 数值 | 是否找到原始数据 | 是否建议写入正式报告 |
|---|---|---:|---|---|
| 旧 strict Game `edbde010`、Village 胜、1553s | `docs/ARCHITECTURE.md` / `docs/DATA_FLOW.md` | 旧口径 | 本轮有新 strict 输出 | 否，改用 `outputs/backend_e2e_report.json` |
| strict active 1065 -> 1065 | `docs/DATA_FLOW.md` | 旧口径 | 本轮 strict 为 935 -> 935 | 否 |
| 每局 99 lessons | `docs/PROJECT_STATUS.md` / `docs/DATA_FLOW.md` | 99 | 本轮 strict 为 102 | 否，写本轮 102 |
| PostgreSQL 21 张表 | `README.md` / `docs/PROJECT_STATUS.md` | 21 | 当前实测 22 | 否，写 22 并说明差异 |
| Track B tier 85/12/3 分布 | `docs/ARCHITECTURE.md` | 设计/文档值 | 本轮未全量重算 | 可作为设计说明，不能当本轮统计 |
| source_event_ids 100% 贯通 | `docs/DATA_FLOW.md` | 文档值 | 本轮未重新统计全量 | 不作为正式量化结论 |
| 48/80 multi-tier 结论 | 历史文档/可能历史报告 | 不稳定 | 当前原始文件不支持 | 否 |

## 5. fallback / mock / demo 风险检查

### 5.1 文件级风险

| 风险来源 | 结论 |
|---|---|
| `data/experiment/heuristic_20games.json` | heuristic 数据，不能支撑 LLM-only 实验 |
| `data/experiment/dry_run_*.log` | dry run 调试文件，不作为正式指标 |
| `data/health/llm_batch_acceptance_fake_*` | fake acceptance，不能作为真实验收 |
| `data/health/human_pairwise_labels_sample.jsonl` | sample 标签，仅作样例 |
| `data/health/track_b_rubric_demo_summary.json` | demo summary，仅展示 |
| `docs/experiments/demo_artifacts/*` | demo HTML，不作正式报告指标 |
| `outputs/winrate_experiment_seed2001.log` | 缺 JSON/MD，尾部显示仅 2 局完成 |
| `data/experiment/multi_tier*` | 当前 JSONL 为空或 summary 冲突 |

### 5.2 strict 日志风险词

`outputs/backend_e2e_report.json` 的 `log_scan`：

| 关键词 | 次数 | 处理 |
|---|---:|---|
| fallback | 3 | 写入审计，不写“完全无风险词” |
| disabled | 1 | 写入审计 |
| skip | 2 | 包含后处理已有 lessons 的跳过上下文 |
| unavailable | 1 | 写入审计 |

## 6. 最终采用的数据源

| 核心指标 | 最终来源 | 采用理由 |
|---|---|---|
| strict mode 是否通过 | `outputs/backend_e2e_report.json` | 本轮重新运行生成，结构化 |
| strict 单局对局数据 | `outputs/backend_e2e_report.json` | 与 strict log 一致 |
| 信息隔离验证 | `outputs/visibility_strict_report.log` | 本轮重新运行，明确 92/92 |
| 检索策略指标 | `outputs/retrieval_policy_eval/results.json` | 本轮重新运行，JSON/CSV/MD 齐全 |
| 20 局稳定性 | `data/experiment/batch_summary.json` | 原始 summary 可解析且 20/20 成功 |
| 数据库规模 | PostgreSQL 全量查询 | 输出文件不能替代全库规模 |
| 多 tier 结论 | 不采用 | 原始文件不一致 |
| winrate seed2001 结论 | 不采用 | 只完成 2 局且缺 JSON/MD |
| 报告图标 / 架构图 | `docs/assets/closure/*.svg` 和 `docs/assets/closure/screenshots/*.png` | 可复跑脚本生成，可编辑源文件与 PNG 截图同时保留 |
| 真实对局截图 | `docs/assets/closure/screenshots/real-game-overview.png`、`docs/assets/closure/screenshots/strict-game-review.png` | 来源为 strict JSON、replay API、review HTML |

## 7. 不建议使用的数据

| 数据 | 不建议原因 |
|---|---|
| `data/experiment/heuristic_20games.json` | heuristic，不符合真实 LLM-only 结论要求 |
| `data/experiment/dry_run_*.log` | dry run，不是正式实验 |
| `data/health/llm_batch_acceptance_fake_*` | fake 数据 |
| `docs/experiments/demo_artifacts/*` | demo 展示文件 |
| `outputs/winrate_experiment_seed2001.log` 的 20 局结论 | 当前缺 `outputs/winrate_report.json/.md`，日志尾部仅 2 局统计 |
| `data/experiment/multi_tier/` | JSONL 为 0 字节 |
| `data/experiment/multi_tier_bak_13g/` | summary 与 JSONL 记录不一致 |
| 历史文档中的旧 strict 数字 | 被本轮 strict 输出覆盖 |
