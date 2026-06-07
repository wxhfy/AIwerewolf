# 实验结果汇总

## 1. Strict Mode 单局全链路验收

命令：

```bash
python scripts/run_backend_full_strict.py
```

来源文件：

- `outputs/backend_e2e_report.json`
- `outputs/backend_e2e_report.md`
- `outputs/backend_e2e_strict.log`

| 指标 | 结果 |
|---|---:|
| overall_result | PASS |
| strict_mode | true |
| started_at | 2026-06-06T10:30:06.870608+00:00 |
| completed_at | 2026-06-06T10:37:53.558328+00:00 |
| LLM provider | doubao |
| LLM model | `ep-20260514115354-k4jz4` |
| game_id | `f8933174-01f9-409d-8bff-c15c0576761b` |
| seed | 42 |
| player_count | 7 |
| winner | wolf |
| days | 1 |
| duration_s | 461.9 |
| finished | true |
| decision_count | 26 |
| event_count | 68 |
| vote_count | 6 |
| decisions_with_tool_trace | 23 |
| knowledge_usage_records | 138 |
| active docs before / after | 935 / 935 |
| active_delta | 0 |
| candidate docs before / after | 19256 / 19358 |
| candidate_delta | 102 |
| new_lessons | 102 |
| per_step_lesson | 25 |
| reflection | 77 |
| evaluation_count | 21 |
| review_count | 1 |
| leaderboard_entries | 34 |

单局玩家结果：

| Seat | Name | Role | Alive | Death Day |
|---:|---|---|---|---|
| 1 | 白栖月 | Werewolf | true |  |
| 2 | 袁汐 | Witch | false | 1 |
| 3 | 宋知野 | Hunter | false | 1 |
| 4 | 墨小染 | Seer | false | 1 |
| 5 | 顾景行 | Villager | true |  |
| 6 | 蓝知怀 | Werewolf | true |  |
| 7 | 南柯辞 | Guard | true |  |

事件摘要来自 PostgreSQL 单局查询：

| 类别 | 说明 |
|---|---|
| SETUP | 1 条 GAME_START，7 条 PRIVATE_INFO |
| NIGHT | Guard / Wolf / Witch / Seer / Resolve 阶段均进入 |
| DAY | Badge signup / speech / election / day speech / vote / resolve 均进入 |
| Special | Hunter shoot 触发，Game end 触发 |
| Vote | DAY_VOTE 6 条，DAY_BADGE_ELECTION 3 条 |

风险说明：strict 报告中 `warnings` 包含 `fallback` 和 `unavailable` 关键词命中；`log_scan` 还有 `skip`、`disabled`。本报告将它们作为风险审计，不把该局描述为“无任何风险关键词”。

## 2. 多局稳定性实验

正式采用文件：`data/experiment/batch_summary.json`。该文件 `completed_at=2026-06-04T06:05:55.914516`，包含 seeds 300-319 的 20 局结果。

| 指标 | 值 |
|---|---:|
| total_games | 20 |
| successful | 20 |
| failed | 0 |
| seeds | 300-319 |
| village wins | 8 |
| wolf wins | 12 |
| village win rate | 40.0% |
| wolf win rate | 60.0% |
| avg days | 3.05 |
| min days | 2 |
| max days | 5 |
| avg duration_s | 2308.39 |
| min duration_s | 1728.4 |
| max duration_s | 3520.5 |
| avg alive end | 3.1 |

角色统计：

| Role | Count | Win Rate |
|---|---:|---:|
| Guard | 20 | 40.0% |
| Hunter | 20 | 40.0% |
| Seer | 20 | 40.0% |
| Villager | 20 | 40.0% |
| Werewolf | 40 | 60.0% |
| Witch | 20 | 40.0% |

MBTI 出场统计：

| MBTI | Count |
|---|---:|
| ENFJ | 18 |
| ENFP | 5 |
| ENTJ | 7 |
| ENTP | 14 |
| ESFJ | 6 |
| ESFP | 2 |
| ESTJ | 8 |
| ESTP | 14 |
| INFJ | 9 |
| INFP | 5 |
| INTJ | 11 |
| INTP | 10 |
| ISFJ | 4 |
| ISFP | 10 |
| ISTJ | 12 |
| ISTP | 5 |

补充发现：`data/experiment/game_state_seed*.json` 有 44 个可解析文件，分为 seeds 300-319、400-412、600-610 三组，胜方 village 18、wolf 26，平均事件数 116.1364。由于缺少统一实验 summary，不把它聚合为“44 局正式实验”。

## 3. 多 Tier / 多方案对比实验

### 3.1 Multi-tier

当前不建议写入正式结论。

| 数据源 | 状态 | 结论 |
|---|---|---|
| `data/experiment/multi_tier/*.jsonl` | 4 个 JSONL 均为 0 字节 | 不可用 |
| `data/experiment/multi_tier_bak_13g/*.jsonl` | 有 13 条备份记录 | 与 summary 不一致 |
| `data/experiment/multi_tier_bak_13g/summary.json` | `games_per_tier=1`，`total_games=4`，每 tier `game_count=0`、`error_count=1` | 不能支撑对比 |

不能写：

- baseline / anti_only / trackc_only / both 的胜率优劣。
- Track C 明显提升表现。
- 多 tier 实验已经完成稳定对比。

### 3.2 Winrate seed2001

`outputs/winrate_experiment_seed2001.log` 记录脚本原计划运行 20 局 seeds 2001-2020，但当前缺失 `outputs/winrate_report.json` 和 `outputs/winrate_report.md`。日志尾部只显示 2 局完成统计，平均天数 2.0，village 100%，wolf 0%，总耗时 7032 秒。

结论：不能写成完整 20 局 winrate 结果，只能写“发现一份未完成/不完整的 winrate log”。

## 4. Strategy Retrieval 实验

命令：

```bash
python scripts/evaluate_retrieval_policies.py --output outputs/retrieval_policy_eval --judge weak
```

来源：

- `outputs/retrieval_policy_eval/results.json`
- `outputs/retrieval_policy_eval/results.csv`
- `outputs/retrieval_policy_eval/summary.md`
- `outputs/retrieval_policy_eval/per_query_details.jsonl`

| 指标 | 值 |
|---|---:|
| query_set_size | 26 |
| retriever_size | 935 active docs |
| judge | weak rule-based labeling |
| candidate leakage | 0 for all policies |

策略排名：

| Rank | Policy | Offline Score | P@1 | P@3 | P@5 | nDCG@5 | Coverage | p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | same_role_same_mbti | 0.7561 | 0.4615 | 0.4744 | 0.4385 | 0.9783 | 1.0000 | 27.90 | 43.63 |
| 2 | hybrid_role_mbti_global | 0.7199 | 0.3846 | 0.3590 | 0.3385 | 0.9655 | 1.0000 | 18.03 | 30.35 |
| 3 | same_role_all_mbti | 0.7198 | 0.3846 | 0.3590 | 0.3385 | 0.9652 | 1.0000 | 22.73 | 38.50 |
| 4 | hybrid_role_alignment_phase | 0.6929 | 0.4231 | 0.4103 | 0.3769 | 0.9543 | 1.0000 | 17.16 | 31.49 |
| 5 | self_mbti_only | 0.6686 | 0.4231 | 0.3077 | 0.3538 | 0.9388 | 1.0000 | 24.89 | 50.42 |
| 6 | global_only | -0.2808 | 0.0769 | 0.0769 | 0.0769 | 0.3077 | 0.3077 | 24.05 | 42.73 |

可写结论：在当前弱标签离线评估里，same_role_same_mbti 综合得分最高；global_only 覆盖率和得分最低；所有策略 candidate leakage 为 0。

不可写结论：不能把离线弱标签分数解释成真实对局胜率提升。

## 5. Track B 评分实验

严格验收局可写：

| 指标 | 值 | 来源 |
|---|---:|---|
| evaluation_count | 21 | `outputs/backend_e2e_report.json` |
| review_count | 1 | `outputs/backend_e2e_report.json` |
| published review status | approved | strict DB verify / report |
| publish_allowed | true | strict DB verify / report |
| score | 1.0 | strict DB verify / report |

数据库快照可写：

| 表 | 记录数 | 来源 |
|---|---:|---|
| `evaluations` | 63129 | PostgreSQL 快照 |
| `published_reviews` | 2625 | PostgreSQL 快照 |

限制：本轮未重新统计全量 Track B tier 分布、highlight/mistake 比例、judge agreement 分布；这些不能作为正式量化结论。

## 6. Track C 知识实验

严格验收局：

| 指标 | 值 | 来源 |
|---|---:|---|
| new_lessons | 102 | `outputs/backend_e2e_report.json` |
| per_step_lesson | 25 | 同上 |
| reflection | 77 | 同上 |
| active_before / after | 935 / 935 | 同上 |
| active_delta | 0 | 同上 |
| candidate_before / after | 19256 / 19358 | 同上 |
| candidate_delta | 102 | 同上 |
| knowledge_usage_records | 138 | 同上 |

数据库快照：

| status | count |
|---|---:|
| active | 935 |
| candidate | 19456 |
| deprecated | 184 |

限制：可以写“知识抽取链路可用、candidate 隔离有效”；不能写“知识回流显著提升胜率”，因为当前 multi-tier / A-B 原始数据不足。

## 7. 图表数据

### 7.1 Strict mode 指标

| Metric | Value |
|---|---:|
| decisions | 26 |
| events | 68 |
| votes | 6 |
| tool_trace_decisions | 23 |
| new_lessons | 102 |
| evaluations | 21 |
| reviews | 1 |
| leaderboard_entries | 34 |

### 7.2 20 局胜方分布

| Winner | Games |
|---|---:|
| village | 8 |
| wolf | 12 |

### 7.3 20 局天数分布

原始逐局天数在 `data/experiment/batch_summary.json` 的 `results[*].days`。聚合：

| Metric | Value |
|---|---:|
| avg_days | 3.05 |
| min_days | 2 |
| max_days | 5 |

### 7.4 知识库状态

| Status | Count |
|---|---:|
| active | 935 |
| candidate | 19456 |
| deprecated | 184 |

### 7.5 检索策略得分

| Policy | Score |
|---|---:|
| same_role_same_mbti | 0.7561 |
| hybrid_role_mbti_global | 0.7199 |
| same_role_all_mbti | 0.7198 |
| hybrid_role_alignment_phase | 0.6929 |
| self_mbti_only | 0.6686 |
| global_only | -0.2808 |

## 8. 可写结论与不可写结论

| 可以写入报告的结论 | 数据来源 |
|---|---|
| strict mode 全链路通过 | `outputs/backend_e2e_report.json` |
| 系统能完成真实 LLM 7 人标准局 | `outputs/backend_e2e_report.json` |
| 决策审计、评分、复盘、知识抽取链路跑通 | `outputs/backend_e2e_report.json` |
| 信息隔离 smoke 92/92 通过 | `outputs/visibility_strict_report.log` |
| 20 局批量实验 20/20 成功，狼胜 12、好人胜 8 | `data/experiment/batch_summary.json` |
| 检索策略离线评估 same_role_same_mbti 最优 | `outputs/retrieval_policy_eval/results.json` |
| active 知识池在 strict 单局中未被 candidate 污染 | `outputs/backend_e2e_report.json` |

| 不建议写入报告的结论 | 原因 |
|---|---|
| Track C 显著提升胜率 | 缺一致可用 A/B 原始数据 |
| multi-tier both 方案优于 baseline | 当前 multi-tier 文件为空或冲突 |
| seed2001 winrate 20 局完成 | 缺 JSON/MD，log 只显示 2 局完成 |
| 全库所有决策均为 LLM-only | provider 分布含 fake 和空值 |
| 所有前端体验已验收 | 本轮只生成结项报告素材截图，未做完整 Playwright 交互回归 |
