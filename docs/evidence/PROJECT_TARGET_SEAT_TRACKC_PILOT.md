# Target-seat Track C 真实 LLM Pilot 证据

生成时间：2026-06-09T17:15:35+08:00

本文档汇总当前可用的 target-seat Track C 真实 LLM paired A/B pilot。它是 Track C 因果验证的阶段性证据，不是最终因果证明。

```mermaid
flowchart LR
    accTitle: Target Seat Track C Pilot
    accDescr: This diagram shows a paired target-seat A/B setup where only one target agent uses Track C while all other seats remain baseline.
    seed[Same Seed / Same Roster] --> base[Baseline Game: all seats basic_react]
    seed --> cand[Candidate Game: target seat rag_react]
    base --> score[Target Seat Scores]
    cand --> score
    score --> delta[Paired Deltas]
    delta --> gates[Acceptance Gates]
    gates --> report[Tracked Pilot Evidence]
```

## 1. 实验定位

| 项目 | 值 |
| --- | --- |
| Source | outputs/target_seat_trackc_ab_seer_ark_pilot_20260609/target_seat_ab_Seer_20260609T082838Z.json |
| Raw source tracked | False |
| Claim scope | pipeline_pilot_not_accepted |
| Runner | target_seat_trackc_ab_experiment.py |
| Target role | Seer |
| Baseline -> Candidate | basic_react -> rag_react |
| Player count / max days | 7 / 20 |
| Model pool | anthropic:deepseek-v4-flash[1m] |

## 2. 核心结果

| Metric | Value | Interpretation |
| --- | --- | --- |
| Paired seeds | 20 | 20-pair pipeline pilot 已完成；仍未达到 80-120 paired seeds 正式验证建议规模。 |
| Completed baseline/candidate | 20 / 20 | 两侧均完成。 |
| Adjusted delta | 6.0120 | 目标席位均值正向趋势。 |
| Role-task delta | 0.1008 | 目标角色任务分均值正向趋势。 |
| Process delta | 6.5290 | 过程分均值正向趋势。 |
| Target win delta | 0.0000 | 本 pilot 中胜率没有变化，胜率只作辅助指标。 |
| Candidate decisions | 752 | candidate 侧真实决策数。 |
| Fallback / invalid | 0 / 0 | 健康门禁通过。 |
| Accepted | False | ci_not_positive |

## 3. Bootstrap CI 与验收门禁

| Delta | Mean | CI95Low | CI95High | CI crosses zero |
| --- | --- | --- | --- | --- |
| adjusted_final_score | 6.0120 | -6.3681 | 17.6161 | True |
| role_task_score | 0.1008 | -0.0534 | 0.2458 | True |
| process_score | 6.5290 | -6.4924 | 19.5370 | True |
| target_win_rate | 0.0000 | 0.0000 | 0.0000 | True |

| Gate | Passed |
| --- | --- |
| enough_samples | True |
| strict_health | True |
| score_gate | True |
| role_task_gate | True |
| win_gate | False |
| ci_gate | False |
| improvement_gate | True |

解释：score、role-task、health 和 improvement gate 均通过，但 CI gate 未通过，因此 `accepted=false`，`claim_level=ci_not_positive`。

## 4. Paired Seed 明细

| Seed | Seat | BaseWinner | CandWinner | AdjustedDelta | RoleTaskDelta | ProcessDelta | CandDecisions | CandFallback | CandInvalid |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9801 | 4 | wolf | wolf | 36.8200 | -0.1750 | 40.9100 | 34 | 0 | 0 |
| 9802 | 4 | wolf | wolf | -2.8800 | -0.1750 | -3.2000 | 35 | 0 | 0 |
| 9803 | 7 | wolf | wolf | 58.9000 | 0.7300 | 65.4400 | 37 | 0 | 0 |
| 9804 | 1 | wolf | wolf | 30.1000 | 0.7300 | 29.5500 | 62 | 0 | 0 |
| 9805 | 4 | wolf | wolf | -19.6000 | 0.3050 | -21.7800 | 33 | 0 | 0 |
| 9806 | 3 | wolf | wolf | -20.7800 | 0.2600 | -23.0900 | 28 | 0 | 0 |
| 9807 | 5 | wolf | wolf | 4.8800 | 0.0583 | 5.4200 | 59 | 0 | 0 |
| 9808 | 3 | wolf | wolf | 0.0000 | 0.0000 | 0.0000 | 41 | 0 | 0 |
| 9809 | 2 | wolf | wolf | 21.2300 | 0.5100 | 23.6000 | 35 | 0 | 0 |
| 9810 | 3 | wolf | wolf | 30.0200 | 0.0450 | 30.3600 | 47 | 0 | 0 |
| 9811 | 4 | wolf | wolf | -26.7000 | 0.0000 | -29.6800 | 33 | 0 | 0 |
| 9812 | 1 | wolf | wolf | -61.0700 | -0.8600 | -63.9600 | 5 | 0 | 0 |
| 9813 | 7 | wolf | wolf | -3.7900 | 0.1750 | -4.2200 | 45 | 0 | 0 |
| 9814 | 6 | wolf | wolf | 14.1100 | -0.1750 | 17.0200 | 28 | 0 | 0 |
| 9815 | 4 | wolf | wolf | 38.7000 | 0.1750 | 41.6700 | 45 | 0 | 0 |
| 9816 | 3 | wolf | wolf | 30.2600 | 0.0900 | 31.4000 | 48 | 0 | 0 |
| 9817 | 6 | wolf | wolf | -0.1900 | 0.0583 | -0.2200 | 51 | 0 | 0 |
| 9818 | 6 | wolf | wolf | -16.2900 | 0.0050 | -15.8800 | 29 | 0 | 0 |
| 9819 | 2 | wolf | wolf | 6.8300 | 0.2600 | 7.5900 | 23 | 0 | 0 |
| 9820 | 2 | wolf | wolf | -0.3100 | 0.0000 | -0.3500 | 34 | 0 | 0 |

## 5. 可写结论与边界

可以写入报告：

| 结论 |
| --- |
| 真实 LLM target-seat paired A/B runner 已在 Seer 目标席位上跑通。 |
| 本 pilot 中 baseline/candidate 各完成 20 局，candidate fallback/invalid 为 0/0。 |
| candidate 相对 baseline 的目标席位 adjusted/process/role-task 指标呈正向均值趋势。 |

暂不能写入报告：

| 结论 |
| --- |
| 不能写成 Track C 已经获得单目标席位因果增益。 |
| 不能写成 Track C 已经提升最终胜率。 |
| 不能把 20 paired seeds pipeline pilot 替代 80-120 paired seeds 的正式验证。 |

边界说明：

| 说明 |
| --- |
| 该 pilot 是真实 LLM target-seat A/B 阶段性证据。由于 bootstrap CI 下界仍跨 0，acceptance.accepted=false，只能写成正向趋势和链路健康，不能写成 causal_supported。 |
| 当前已完成 20 paired seeds pipeline pilot；下一步按功效计划扩到 80-120 paired seeds，并轮换 Seer/Witch/Guard/Werewolf/Hunter/Villager。 |
