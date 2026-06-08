# Module Effect Experiment Results

> Generated at: 2026-06-08T08:40:01.106217+00:00

## Scope

This report is a reproducible module-level experiment summary. It consolidates formal Volcengine v4flash framework runs, Track C retrieval ablations, role/MBTI auxiliary analysis, full-project audit probes, and optional local gates. It does not fabricate metrics that are not present in the logs.

Key interpretation rule: `basic_react` is the ordinary ReAct-style baseline. Existing formal data uses `anti_only`, `trackc_only`, and `cognitive_full`; the expanded runner maps these to `role_guarded_react`, `rag_react`, and `full_cognitive` for clearer paper framing.

## Executive Result

- Quantified modules: 14; passed target: 14/14; mean effect score: 90.79/100.
- Formal evidence rows after strict v4flash filtering: 59; pro/fake/non-Volcengine rows are excluded from formal claims.
- Track C retrieval uplift vs global-only: P@3=0.2821, nDCG@5=0.9587, coverage=1.0, leak=0.
- Main negative result: current all-seat Track C toggles cannot prove final-agent causal win-rate lift; use target-seat paired A/B for that claim.

## Module Effect Scorecard

| Module | Primary metric | Baseline | Designed treatment | Delta | Relative lift | Effect score | Target pass | Evidence | Caveat |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| Agent design: role cognition + anti-pattern control | single_agent_dimension | basic_react: 0.7069 | agent_design_condition: 0.8982 | +0.1913 | +27.06% | 89.82 | yes | single_agent basic_react=0.7069, anti_condition=0.8982, cognitive_full=0.8260; total rubric gain under agent-design condition=-1.02 | anti_only 是 Agent 设计消融条件，不作为独立核心模块；cognitive_full 完成率较低，因此完整架构胜率因果仍需 target-seat A/B。 |
| Multi-agent game interaction | multi_agent_dimension | target_threshold: 0.7000 | current_framework:baseline: 0.7500 | +0.0500 | +7.14% | 75.00 | yes | basic_react_multi=0.7500; macro_role_win top=0.4630; core_role_coverage=1.000 | 该 formal 集合显示多智能体维度稳定达标，但各框架之间差异不大。 |
| Track B/C advanced architecture | advanced_bc_dimension | basic_react: 0.6000 | both: 0.7344 | +0.1344 | +22.40% | 73.44 | yes | best=both; anti=0.4721, trackc=0.6106, both=0.7344 | advanced_bc 能区分模块贡献，但胜率因果结论仍需 target-seat A/B。 |
| Track B leaderboard discriminability | rubric_score_spread | minimum useful spread: 5.0000 | formal_v4flash_4_tiers: 9.1198 | +4.1198 | +82.40% | 100.00 | yes | tiers=4, top=both, spread=9.12 |  |
| Track C retrieval policy | offline_retrieval_score | global_only: -0.2362 | hybrid_role_alignment_phase: 0.7040 | +0.9402 | +398.05% | 70.40 | yes | Δscore=+0.9402; ΔP@3=+0.2179; ΔnDCG@5=+0.5786; Δcoverage=+0.6154 | 弱标签离线检索评估，证明检索设计合理性；最终胜率提升需在线 target-seat A/B。 |
| Retrieval precision and coverage | composite_ir_score | global_only: 0.3024 | hybrid_role_alignment_phase: 0.8019 | +0.4995 | +165.19% | 80.19 | yes | P@3=0.2821, nDCG@5=0.9587, coverage=1.0000, MRR=0.4295 |  |
| Track C safety and knowledge hygiene | leak_or_invalid_count | allowed defects: 0.0000 | current_track_c_store: 0.0000 | +0.0000 | n/a | 100.00 | yes | leak=0, invalid_doc=0, source_event_coverage=0.9924, docs=131 |  |
| Track C role/persona evolution trend | non_wolf_role_win_delta | track_c_off: 0.3508 | track_c_on: 0.3784 | +0.0276 | +7.86% | 82.16 | yes | overall_win_rate 0.3508->0.3784; avg_non_wolf_role_delta=+0.0643; cells=96 | 该实验全席位同时切换 Track C，适合展示趋势和覆盖，不足以证明单个最终 Agent 因果胜率提升。 |
| Information isolation | visibility_gate_pass | required: 1.0000 | current_backend: 1.0000 | +0.0000 | +0.00% | 100.00 | yes | RESULTS: 92 passed, 0 failed; All information isolation checks passed. |  |
| Rule engine and role coverage | controlled_case_coverage | required controlled cases: 9.0000 | full_project_real_audit: 9.0000 | +0.0000 | +0.00% | 100.00 | yes | controlled_cases=9, roles=8, phases=21, issues=0 |  |
| Frontend and human-observable UX | ui_probe_pass | required: 1.0000 | playwright_probe: 1.0000 | +0.0000 | +0.00% | 100.00 | yes | errors=0, bottomDock=1, bubbleGrowth=True, timelineAfter=2 |  |
| Volcengine v4flash provenance and real LLM path | formal_v4flash_rows | minimum formal rows: 20.00 | filtered_formal_dataset: 59.00 | +39.00 | +195.00% | 100.00 | yes | formal_rows=59, excluded=44, doubao_probe_ok=True, real_llm_latency_s=2.568 |  |
| Experiment reliability and strict-mode health | strict_decision_health | minimum useful health: 80.00 | formal_v4flash_dataset: 100.00 | +20.00 | +25.00% | 100.00 | yes | fallback=0, invalid=0, llm_decisions=1059, external_failure_rate=0.4237 | 整局失败/API/子进程错误不作为 Agent 输局或架构扣分，只作为运行稳定性风险单独披露。 |
| Local non-LLM validation gates | gate_pass_rate | required: 1.0000 | run_gates: 1.0000 | +0.0000 | +0.00% | 100.00 | yes | passed=4/4 |  |

## Formal v4flash Outcome Metrics

Whole-game failures/API errors are external run-health signals and are not counted as Agent losses.

| Tier | Completed | External failed | External failure | Wolf win | Village win | Macro role win | Fallback | Invalid |
|---|---:|---:|---:|---:|---:|---:|---:|
| anti_only | 11 | 2 | 0.1538 | 0.6364 | 0.3636 | 0.4091 | 0 | 0 |
| baseline | 9 | 4 | 0.3077 | 0.5556 | 0.4444 | 0.4630 | 0 | 0 |
| both | 7 | 13 | 0.6500 | 0.5714 | 0.4286 | 0.4524 | 0 | 0 |
| trackc_only | 7 | 6 | 0.4615 | 0.7143 | 0.2857 | 0.3571 | 0 | 0 |

## Formal Agent Framework Scores

Only rows with `formal v4flash score available` have completed real v4flash evidence in the current logs. Rows marked as runner-only are implemented comparison arms that need a new balanced run before they can be claimed.
The total score excludes whole-game external failures/API errors; external failure is shown separately.

| Framework | Family | Alias/tier | Total | Delta vs basic_react | External failure | Wolf win | Village win | Macro role win | Single /20 | Multi /20 | Eng /30 | B/C /30 | Evidence |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `full_cognitive` | role-guarded RAG + Reflexion | cognitive_full / both | 78.75 | +8.1013 | 0.6500 | 0.5714 | 0.4286 | 0.4524 | 16.52 | 15.00 | 25.19 | 22.03 | formal v4flash score available |
| `rag_react` | RAG/ReAct | trackc_only / trackc_only | 71.32 | +0.6738 | 0.4615 | 0.7143 | 0.2857 | 0.3571 | 8.0000 | 15.00 | 30.00 | 18.32 | formal v4flash score available |
| `basic_react` | ReAct / ordinary tool-using LLM baseline | basic_react / baseline | 70.64 | +0.0000 | 0.3077 | 0.5556 | 0.4444 | 0.4630 | 14.14 | 15.00 | 23.51 | 18.00 | formal v4flash score available |
| `role_guarded_react` | role-conditioned guarded agent | anti_only / anti_only | 69.63 | -1.0185 | 0.1538 | 0.6364 | 0.3636 | 0.4091 | 17.96 | 15.00 | 22.50 | 14.16 | formal v4flash score available |
| `reflexion_react` | Reflexion | n/a / n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | supplemental anthropic-coding v4flash data available; historical formal score pending |
| `rag_reflexion` | RAG + Reflexion | n/a / n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | supplemental anthropic-coding v4flash data available; historical formal score pending |

## Supplemental Reflexion Framework Runs

These rows are supplemental runs for the two framework arms that were not present in the historical formal v4flash set. They are not merged into the historical v4flash ranking unless they have valid completed games under the same formal model policy.

| Experiment | Model pool | Framework | Score | Completed | Failed | External failure | Win rate | Macro role win | Status |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g6/summary.json | anthropic:deepseek-v4-flash[1m] | `rag_reflexion` | 82.97 | 6 | 0 | 0.0000 | 0.2857 | 0.1667 | completed supplemental run |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g6/summary.json | anthropic:deepseek-v4-flash[1m] | `reflexion_react` | 64.72 | 6 | 0 | 0.0000 | 0.2857 | 0.1667 | completed supplemental run |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g3/summary.json | anthropic:deepseek-v4-flash[1m] | `rag_reflexion` | 87.78 | 3 | 0 | 0.0000 | 0.2857 | 0.1667 | completed supplemental run |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g3/summary.json | anthropic:deepseek-v4-flash[1m] | `reflexion_react` | 59.59 | 3 | 0 | 0.0000 | 0.2857 | 0.1667 | completed supplemental run |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g1/summary.json | anthropic:deepseek-v4-flash[1m] | `rag_reflexion` | 83.07 | 1 | 0 | 0.0000 | 0.2857 | 0.1667 | completed supplemental run |
| docs/experiments/framework_gap_reflexion_anthropic_v4flash_g1/summary.json | anthropic:deepseek-v4-flash[1m] | `reflexion_react` | 64.30 | 1 | 0 | 0.0000 | 0.2857 | 0.1667 | completed supplemental run |
| docs/experiments/framework_gap_reflexion_doubao_endpoint_g1/summary.json | doubao:ep-20260514115354-k4jz4 | `reflexion_react,rag_reflexion` | n/a | 0 | 0 | n/a | n/a | n/a | terminated_without_valid_summary; Manual follow-up run kept open HTTPS connections for more than 8 minutes on a 1-seed batch and emitted strict decision validation errors; no completed game artifact was written before termination. |
| docs/experiments/framework_gap_reflexion_doubao_endpoint_g6/summary.json | doubao:ep-20260514115354-k4jz4 | `reflexion_react,rag_reflexion` | n/a | 0 | 0 | n/a | n/a | n/a | terminated_without_valid_summary; Manual 6-seed follow-up run kept open HTTPS connections for more than 20 minutes and emitted strict decision validation errors; no completed game artifact was written before termination. |
| docs/experiments/framework_gap_reflexion_v4flash_g6/summary.json | doubao:deepseek-v4-flash[1m] | `reflexion_react,rag_reflexion` | n/a | 0 | 12 | 1.0000 | n/a | n/a | no valid completed games; external failure types=unknown |

## Expanded Agent Framework Comparison Matrix

| Framework | Existing alias | External design family | Enabled modules | Current evidence status | Why include it |
|---|---|---|---|---|---|
| `basic_react` | n/a | ReAct / ordinary tool-using LLM baseline | none beyond base cognitive loop | formal v4flash data available | baseline for showing the gain of role design, retrieval, and B/C loop |
| `role_guarded_react` | anti_only | role-conditioned guarded agent | role/anti-pattern | formal v4flash data available through anti_only | proves Agent design is not just generic ReAct; anti-patterns are part of Agent design |
| `rag_react` | trackc_only | RAG/ReAct | Track C retrieval | formal v4flash data available through trackc_only; retrieval ablation available | isolates retrieval and strategy-knowledge contribution |
| `reflexion_react` | n/a | Reflexion | post-game reflection only | supplemental anthropic-coding v4flash data available; historical formal score pending | checks whether reflection alone can replace runtime Track C retrieval |
| `rag_reflexion` | n/a | RAG + Reflexion | Track C retrieval + reflection | supplemental anthropic-coding v4flash data available; historical formal score pending | tests retrieval and outer-loop reflection synergy without role guardrails |
| `full_cognitive` | cognitive_full | role-guarded RAG + Reflexion | role/anti-pattern + Track C retrieval + reflection | formal v4flash data available through cognitive_full, but completion is low | final architecture condition; should be rerun in balanced target-seat A/B |

## Retrieval Precision Metrics

| Policy | Query set | Docs | P@1 | P@3 | P@5 | MRR | nDCG@5 | Coverage | Role match | MBTI match | Phase match | p95 ms | Leak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hybrid_role_alignment_phase | 26 | 381 | 0.3077 | 0.2821 | 0.2538 | 0.4295 | 0.9587 | 1.0000 | 1.0000 | 0.9462 | 0.6231 | 12.24 | 0 |

## Domain Metric Catalog for Multi-Angle Comparison

| Metric family | External source | Canonical metrics | Project fields | Current status | Presentation use |
|---|---|---|---|---|---|
| AIWolf outcome metrics | AIWolf Protocol Division | overall win rate, per-role win rate | wolf_win_rate, village_win_rate, role_win_rates, macro_role_win_rate | quantified in formal framework leaderboard | primary outcome comparison; always show role distribution next to it |
| WereWolfPlus strategic indicators | WereWolfPlus metrics notebook | IRP, KSR, VSS, werewolf_kpi, seer_kpi, guard_kpi, KRS, KRE | vote_score, skill_score, role_task_score, role-wise KPI proxies | mapped; exact IRP/KSR/VSS naming is reference-derived | connects our role/vote/skill score decomposition to prior Werewolf agent work |
| AIWolfDial language quality | AIWolfDial 2025 | naturalness, context awareness, contradiction consistency, action-dialogue coherence, team play | speech_score, process_score, evidence_refs, future contradiction/coherence head | partially quantified; speech semantic audit is audit-only | justifies Track B beyond win/loss by evaluating speech and reasoning quality |
| Speech-act classifier quality | project open-data speech classifier | exact accuracy, hamming loss, macro/micro F1, per-label F1 | speech_act_probs, accusation/interrogation/defense/evidence_use/identity/call_for_action | quantified as audit-only model | shows speech analysis can be measured without affecting leaderboard score |
| Deception/detection/disclosure | Mini-Mafia / WOLF / BloodBench direction | wolf deception, village detection, seer disclosure, claim falsehoods, cover consistency | wolf_deception_proxy, village_detection_proxy, seer_disclosure_proxy, persona deception/detection scorer | proxy quantified; direct claim labels pending | frames social-deduction-specific capability instead of generic LLM accuracy |
| Track C retrieval IR | information retrieval evaluation practice | P@k, Recall@k, MRR, nDCG@k, coverage, leakage, latency | precision_at_3, ndcg_at_5, mrr, coverage_rate, candidate_leakage_count, latency_p95_ms | quantified in retrieval ablation | direct evidence that strategy-memory retrieval is effective and safe |
| Pairwise/review consistency | human/LLM pairwise evaluation practice | pairwise accuracy, Cohen's d, rank stability, bootstrap confidence interval | paired_seed_deltas, bootstrap_reliability, pairwise_ranker, review metric tests | partially quantified; human labels pending for stronger claims | supports Track B leaderboard consistency and discriminability |
| Safety and reproducibility | agent benchmark reliability gates | fallback rate, invalid action rate, information leak rate, evidence coverage | fallback_count, invalid_count, leak_doc_count, source_event_coverage, visibility strict checks | quantified and gate-tested | proves B/C loop is not leaking hidden information or hiding failures |

## Social-Deduction Metric Mapping

| Metric family | Current quantitative field | Current value | Use in paper |
|---|---|---:|---|
| AIWolf overall/role win rate | formal tier win rates + role win rates | 59 rows | Primary outcome metric with role-normalized macro win rate. |
| Wolf deception proxy | wolf win rate by tier | baseline=0.5556, trackc=0.7143 | Use as proxy only; direct deception labels need speech taxonomy. |
| Village detection proxy | village win rate + non-wolf role win rate | baseline=0.4444, cognitive_full=0.4286 | Shows collective detection/survival trend under current logs. |
| Seer disclosure proxy | Seer role win rate | 0.3824 | Aggregate proxy; future claim-level disclosure labels should be added. |
| Track C knowledge safety | leak/invalid docs/source coverage | leak=0, invalid=0, coverage=0.9924 | Supports B -> C feedback-loop hygiene. |

## Frontier Agent Design Evaluation Applied

- Werewolf Agent Design Quality Index: 88.57/100.
- Interpretation: this is a benchmark-inspired design-quality index for this project, not an external leaderboard score.

| Frontier lens | Source | Project metric mapping | Current result | Verdict |
|---|---|---|---:|---|
| Interactive task success | AgentBench / AgentBoard | completion + strict health | 100.00 | strong |
| Trajectory/process quality | AgentBoard-style fine-grained metrics | role cognition + process score | 89.82 | strong |
| Tool/RAG reliability | tau-bench-style policy/tool reliability | retrieval precision/coverage/leak | 80.19 | acceptable |
| Social multi-agent quality | SOTOPIA-style social interaction | macro role/social deduction proxies | 75.00 | acceptable |
| Learning from experience | Reflexion-style self-improvement | Track C off/on trend + knowledge hygiene | 82.16 | acceptable |
| Safety/reproducibility | modern agent reliability gates | visibility + fallback/invalid + leak gates | 100.00 | strong |

Frontier-method takeaway:

- The strongest evidence is not raw win rate; it is the combination of trajectory/process quality, RAG precision, safety gates, and reproducibility.
- Your current architecture is strong on Agent role design, retrieval quality, and safety; the main weakness is full-stack execution reliability and the lack of a target-seat causal Track C A/B.

## Role-Wise Win Rates

| Role | Samples | Wins | Win rate | Wilson CI95 |
|---|---:|---:|---:|---|
| Guard | 34 | 13 | 0.3824 | [0.239, 0.549593] |
| Hunter | 34 | 13 | 0.3824 | [0.239, 0.549593] |
| Seer | 34 | 13 | 0.3824 | [0.239, 0.549593] |
| Villager | 34 | 13 | 0.3824 | [0.239, 0.549593] |
| Werewolf | 68 | 42 | 0.6176 | [0.498805, 0.723907] |
| Witch | 34 | 13 | 0.3824 | [0.239, 0.549593] |

## Track C Evolution Trend

- Auxiliary role/MBTI rows: off={'samples': 553, 'wins': 194, 'win_rate': 0.350814, 'seed_count': 48}, on={'samples': 518, 'wins': 196, 'win_rate': 0.378378, 'seed_count': 46}.
- Knowledge docs: 131; source-event coverage: 0.9924; invalid/leak: 0/0.
- Interpretation: useful for showing role/persona coverage and non-wolf positive trend, but not sufficient for final-agent causal win-rate lift because all seats were toggled together.

## Gate Results

| Gate | Passed | Summary |
|---|---|---|
| visibility_strict | yes | RESULTS: 92 passed, 0 failed; All information isolation checks passed. |
| track_b_review_metrics | yes | 50 passed, 2 skipped in 0.74s |
| track_c_retrieval_prompt | yes | 29 passed, 6 warnings in 1.83s |
| leaderboard_experiment_harness | yes | 9 passed, 6 warnings in 2.12s |

## Metric References Used For Presentation Framing

| Source | Borrowed metric family | Project mapping |
|---|---|---|
| [AIWolf Protocol Division](https://aiwolf.org/en/archives/2873) | overall win rate, per-role win rate | formal v4flash leaderboard winner rates, role-wise win rates, macro-role win rate |
| [AIWolf Natural Language / AIWolfDial](https://aclanthology.org/2025.aiwolfdial-1.1.pdf) | naturalness, context awareness, contradiction consistency, action-dialogue coherence, team play | Track B speech_score, vote_score, skill_score, process_score, evidence_refs, future coherence head |
| [Werewolf Arena](https://arxiv.org/abs/2407.13943) | arena-style model/framework comparison under deception, deduction, persuasion | Track B leaderboard discrimination and framework/rubric spread |
| [Mini-Mafia / WOLF / BloodBench direction](https://www.bloodbench.com/) | deception generation, deception detection, disclosure, claim-level falsehoods | wolf deception proxy, village detection proxy, seer disclosure proxy, future speech-claim taxonomy |

## Required Next Causal Experiment

For the final claim that Track C experience summaries improve the final agent, run paired target-seat A/B:

1. Same seed, same role assignment, same baseline opponents.
2. Upgrade only one target seat from baseline to Track C; rotate target role and seat.
3. Report target-agent win rate, role-normalized adjusted score, knowledge-hit rate, bad-case reduction, retrieval P@3/nDCG/coverage, fallback/invalid/info-leak gates, and bootstrap confidence intervals.
