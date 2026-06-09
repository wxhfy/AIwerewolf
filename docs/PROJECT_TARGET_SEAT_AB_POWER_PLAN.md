# Target-seat Track C A/B 功效计划

生成时间：2026-06-09T11:23:50+08:00

本文件用于规划后续真实 target-seat Track C 因果 A/B 实验。它只估计样本量，不运行游戏、不调用 LLM，也不构成 Track C 已经产生因果增益的结论。

## 1. 当前 Runner 验收门槛

| Gate | Default |
| --- | --- |
| min_paired_seeds | 20 |
| min_adjusted_score_delta | 3.0 |
| min_role_task_delta | 0.03 |
| min_win_rate_delta | 0.03 |
| require_positive_ci | True |
| strict_health | candidate_fallback_count == 0 and candidate_invalid_count == 0 |

代码依据：`scripts/target_seat_trackc_ab_experiment.py`。这些门槛表示 runner 目前可以接受 20 个 paired seeds 的结果，但 20 局更适合作为 pipeline pilot，而不是最终因果证明。

## 2. 现有评分方差快照

来源：PostgreSQL published_reviews.report_json.metadata.player_scores, excluding games whose players.model_name contains fake。

| Role | N | AdjustedMean | AdjustedSD | RoleTaskMean | RoleTaskSD | ProcessMean | ProcessSD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Werewolf | 5668 | 68.80 | 26.48 | 0.7401 | 0.1904 | 66.77 | 26.18 |
| Villager | 4581 | 30.36 | 30.22 | 0.4702 | 0.2539 | 29.36 | 29.45 |
| Seer | 2830 | 38.61 | 28.76 | 0.5973 | 0.2758 | 37.24 | 28.17 |
| Witch | 2830 | 39.62 | 22.44 | 0.5065 | 0.1546 | 39.73 | 22.09 |
| Hunter | 2830 | 37.76 | 31.72 | 0.6056 | 0.2076 | 37.14 | 30.62 |
| Guard | 2822 | 41.65 | 21.71 | 0.6175 | 0.2244 | 37.14 | 21.39 |
| WhiteWolfKing | 871 | 52.71 | 19.25 | 0.6316 | 0.1178 | 51.61 | 20.60 |

说明：该表是非 fake 历史评分分布。它提供目标角色评分波动的上界参考，但不是 paired A/B 的真实差分方差；真实 paired delta 方差必须由后续 A/B 输出补齐。

## 3. Adjusted Score 样本量情景

以下为 80% power 的 paired mean delta 情景表。数值表示需要的 paired seeds 数；这是功效计划，不是实验结果。

| PairedDeltaSD | Delta=3 | Delta=5 | Delta=8 | Delta=10 |
| --- | --- | --- | --- | --- |
| 5.0 | 22 | 8 | 4 | 2 |
| 10.0 | 88 | 32 | 13 | 8 |
| 15.0 | 197 | 71 | 28 | 18 |
| 20.0 | 349 | 126 | 50 | 32 |
| 25.0 | 546 | 197 | 77 | 50 |
| 30.0 | 785 | 283 | 111 | 71 |

90% power 对应样本量如下：

| PairedDeltaSD | Delta=3 | Delta=5 | Delta=8 | Delta=10 |
| --- | --- | --- | --- | --- |
| 5.0 | 30 | 11 | 5 | 3 |
| 10.0 | 117 | 43 | 17 | 11 |
| 15.0 | 263 | 95 | 37 | 24 |
| 20.0 | 467 | 169 | 66 | 43 |
| 25.0 | 730 | 263 | 103 | 66 |
| 30.0 | 1051 | 379 | 148 | 95 |

## 4. Role-task Score 样本量情景

Role-task 是 0-1 量纲，更适合作为目标席位行为质量的主指标之一。以下为 80% power 情景表。

| PairedDeltaSD | Delta=0.03 | Delta=0.05 | Delta=0.08 | Delta=0.10 |
| --- | --- | --- | --- | --- |
| 0.05 | 22 | 8 | 4 | 2 |
| 0.1 | 88 | 32 | 13 | 8 |
| 0.15 | 197 | 71 | 28 | 18 |
| 0.2 | 349 | 126 | 50 | 32 |
| 0.25 | 546 | 197 | 77 | 50 |
| 0.3 | 785 | 283 | 111 | 71 |

## 5. Target Win Rate 样本量情景

胜率是离散且高噪声指标。以下以 paired binary signed delta 近似估计；DiscordanceRate 表示同一 seed 下 baseline/candidate 胜负不一致的比例。

| DiscordanceRate | Delta=0.03 | Delta=0.05 | Delta=0.08 | Delta=0.10 |
| --- | --- | --- | --- | --- |
| 0.2 | 1737 | 621 | 238 | 150 |
| 0.3 | 2609 | 935 | 361 | 228 |
| 0.4 | 3481 | 1248 | 483 | 307 |
| 0.5 | 4353 | 1562 | 606 | 385 |

结论边界：如果只希望证明 3%-5% 的胜率差，所需 paired seeds 远高于当前 runner 默认 20。因此胜率应作为参考指标，主结论应优先基于 adjusted score、role-task score、fallback/invalid 健康门禁和 bootstrap CI。

## 6. 推荐实验规模

| 级别 | PairedSeeds | 用途 |
| --- | --- | --- |
| pilot | 20 | 验证 provider、runner、per-agent feature flags、fallback/invalid 和输出格式 |
| minimum_confirmatory | 80 | 检测中等 adjusted score / role-task 改进，仍需报告 CI 和角色分层结果 |
| preferred_confirmatory | 120 | 推荐正式结项补实验规模，兼顾成本和统计稳定性 |
| high_confidence | 200 | 用于更小效应或跨角色轮换的高置信验证 |

20 个 paired seeds 适合验证 pipeline 和健康门禁，不适合直接作为最终因果证明。除非真实 paired 方差很低，否则评分和 role-task 指标通常需要 80+ paired seeds；胜率差所需样本显著更大，应作为辅助指标。

## 7. 推荐命令模板

provider preflight 通过后，先跑 pilot：

```bash
python scripts/target_seat_trackc_ab_experiment.py \
  --target-role Seer \
  --seeds 9301 9302 9303 9304 9305 9306 9307 9308 9309 9310 9311 9312 9313 9314 9315 9316 9317 9318 9319 9320 \
  --baseline-framework basic_react \
  --candidate-framework rag_react \
  --player-count 7 \
  --max-days 20 \
  --bootstrap-iterations 2000 \
  --min-paired-seeds 20 \
  --output-dir outputs/target_seat_trackc_ab_seer_pilot
```

正式补实验建议至少 80 个 paired seeds，并保持同 seed、同角色分配、同 baseline 对手，只升级一个目标席位。若目标是跨角色结论，应按 Seer/Werewolf/Witch/Guard/Hunter/Villager 分别运行，再做角色分层汇总。

## 8. 不能据此书写的结论

- 不能把本文件中的样本量情景写成 Track C 已经提升胜率或评分。
- 不能用 20 paired seeds 的 pilot 结果直接替代最终因果实验，除非实际 paired delta 很大且 bootstrap CI 明确为正。
- 不能只看 target win rate；狼人杀单局胜负噪声高，必须同时报告目标席位评分、role-task、fallback/invalid 和 CI。
