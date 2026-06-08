# Track B/C Architecture Evidence Metrics

> Purpose: provide defensible architecture evidence for showing that Track B
> replay analysis and Track C evolution are useful, non-redundant parts of the
> AI Werewolf architecture.
>
> Retrieval date: 2026-06-08.

## 1. Recommended Slide-Level Metric Groups

| Group | What to show | Why it supports the architecture |
|---|---|---|
| Outcome | Overall win rate, role-wise win rate, macro/micro/weighted role win rate | Aligns with AIWolf contest practice; shows that the system remains game-competitive. |
| Process quality | Track B process indicators, vote/speech/skill/survival sub-indicators, adjusted final result | Shows Track B is not only reading win/loss noise; it analyzes decisions and role execution. |
| Role fairness | Role-normalized result, role distribution audit, per-role deltas | Prevents misleading claims caused by role imbalance or strong/weak role assignment. |
| Speech-action consistency | Contradiction rate, speech-action coherence, claim-action alignment | Matches AIWolf NLP evaluation criteria and shows why replay-level analysis is necessary. |
| Deception/detection/disclosure | Wolf deception quality, village detection quality, seer information disclosure quality | Matches recent Mini-Mafia/WOLF-style capability decomposition. |
| Counterfactual evidence | Counterfactual count per game, counterfactual target gap, bad-case severity distribution | Shows Track B produces actionable explanations rather than opaque scalar outputs. |
| Track C usage and safety | Knowledge hit rate, strategy adoption rate, safe-for-learning rate, info-leak rate | Shows C is connected to B and guarded by information-isolation filters. |
| Reliability | LLM-review agreement, bootstrap CI, rank stability, repeated-run variance | Shows the analysis pipeline is consistent enough for academic comparison. |

## 2. Consistency and Reliability Metrics to Add to Reports

These are the most useful consistency metrics for replay analysis.

| Metric | Definition | Display form |
|---|---|---|
| LLM-review agreement | Correlation/agreement among human labels, LLM review outputs, or rule-based vs LLM-review outputs | Pearson/Spearman/Kendall table; mean absolute difference |
| Rank stability | Whether leaderboard order remains stable under bootstrap resampling of games/seeds | Kendall tau or top-1/top-3 stability |
| Test-retest stability | Same logs analyzed repeatedly by the review pipeline | mean/std of final result and rank |
| Role-normalized stability | Rank/result after controlling for role assignment | role-normalized result delta |
| Internal sensitivity | Result changes when removing one sub-indicator dimension | ablation tornado chart |
| Convergent validity | Process indicator correlation with win rate, role win rate, MVP/bad-case counts | scatter or correlation heatmap |
| Discriminant validity | Whether different models/frameworks separate in Track B leaderboard | effect size + bootstrap CI |
| Evidence coverage | Percent of reasons, bad cases, suggestions, and counterfactuals with event evidence refs | coverage bar |
| Safety consistency | fallback_count, invalid_count, info_leak_count, private-evidence redaction pass rate | health-gate table |

Recommended thresholds for formal reporting:

- `fallback_count = 0` and `invalid_count = 0` for games used as real LLM evidence.
- At least 20 seeds per condition for trend claims; larger if claiming statistical significance.
- Show confidence intervals for win rate and adjusted final result.
- Report role distribution next to every model/framework comparison.
- Formal Volcengine runs should use v4flash only, for example
  `EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash"` or
  `EXPERIMENT_MODEL_POOL="doubao:${DOUBAO_ENDPOINT}"`; do not use v4-pro in the final evidence path.

## 3. Frontline Metrics from Recent Social-Deduction Work

| Source direction | Metrics worth borrowing | How to map into this project |
|---|---|---|
| AIWolf Protocol Division | overall win rate, per-role win rate | Already covered by leaderboard; add macro/micro/weighted role win rates. |
| AIWolf Natural Language Division | naturalness, context-awareness, consistency/no contradiction, action-dialogue coherence, character/profile consistency, team play | Map to speech_score, speech-action coherence, contradiction detector, persona consistency, wolf-team coordination. |
| Werewolf Arena | arena-style model comparison, strategic communication, dynamic speaking behavior | Use `--axis model` leaderboard and speech/vote influence metrics. |
| Mini-Mafia | role-specific parameters: deception, detection, disclosure | Map to wolf deception score, villager/wolf-detection score, seer disclosure score. |
| WOLF benchmark | statement-level deception taxonomy, peer-rated deceptiveness, longitudinal suspicion/trust dynamics | Add deception labels per speech and trust-shift curves from public statements. |
| BloodBench | role claims, fabricated info, false accusation, false defense, team cover, strategic bluff; cover-story consistency and evil-team coordination | Add claim taxonomy to speech audit and wolf-team coordination metrics. |
| Strategy Bench | deception index and detection index across social deduction games | Present separate wolf-side and village-side indexes instead of only one overall score. |
| Human-aligned social-deduction strategy benchmarks | human-aligned tactics, voting alignment, teammate coordination, persuasion effectiveness | Add "human-aligned strategy rate" and compare Track B suggestions against a hand-labeled tactic checklist. |
| Multimodal/veracity Werewolf benchmarks | truthfulness/veracity, role-consistent statements, evidence groundedness | Use as inspiration for speech truthfulness and evidence-ref coverage; do not claim multimodal coverage unless UI/audio/video inputs are actually evaluated. |
| Human-baseline deception studies | deception quality against human baselines, detectability, persuasion under suspicion | Add human-baseline pairwise preference only when enough annotated samples exist. |
| Avalon/social deduction ablations | win rate plus engagement, persuasion, leadership, sharing/camouflage behavior | Use as optional cross-game inspiration: discussion leadership, persuasion success, information sharing rate. |

## 4. Suggested Figures for the Presentation

1. **Track B Leaderboard Discrimination**
   - x-axis: model/framework variant.
   - y-axis: win rate and adjusted final result.
   - Include role distribution audit below the chart.

2. **Track C Non-Redundancy A/B**
   - compare `basic_react` vs `cognitive_full`.
   - show paired seed delta for adjusted final result, win rate, knowledge hit rate, bad-case count.

3. **Role-Normalized Performance Radar**
   - role task, vote, speech, skill, survival, deception/detection.
   - one radar per framework variant.

4. **Speech-Action Coherence**
   - contradiction rate and action-dialogue alignment.
   - useful because AIWolf NLP explicitly evaluates this.

5. **B -> C Feedback Loop**
   - bad cases -> counterfactuals -> strategy docs -> retrieval hits -> result delta.
   - show counts and conversion rates, not just screenshots.

6. **Deception/Detection/Disclosure Decomposition**
   - werewolf deception, villager detection, seer disclosure.
   - connects directly to recent Mini-Mafia/WOLF benchmark framing.

7. **Safety/Reliability Gate**
   - fallback, invalid action, info leak, private evidence redaction, evidence-ref coverage.
   - shows strict information isolation and reproducibility.

8. **Review Consistency**
   - Spearman/Kendall rank correlation across LLM-review runs or repeated runs.
   - shows that the analysis pipeline is stable enough for comparison.

## 5. Current Project Mapping

Already implemented or directly available:

- `PlayerScore`: `camp_result_score`, `role_task_score`, `vote_score`, `speech_score`, `skill_score`,
  `survival_score`, `process_score`, `adjusted_final_score`, `semantic_highlight_bonus`,
  `confidence`, `judge_agreement`, `evidence_refs`.
- `RoleMetrics`: `vote_precision`, `useful_ability_uses`, `deception_score`, role mistakes.
- `GameMetrics`: winner, total days/events, wolf elimination rate, village survival rate, info efficiency.
- `LeaderboardAggregator`: persona/role/version aggregation and role-normalized persona score.
- New experiment runner: `scripts/track_bc_leaderboard_experiment.py`.
  - model/framework/combined axes;
  - role distribution audit;
  - macro/micro role win rate per group;
  - paired seed delta;
  - seed bootstrap confidence intervals and rank-stability estimates.

Recommended next implementation if time permits:

- Add weighted-micro role win rate when the formal experiment uses non-uniform target role weights.
- Add a speech claim/deception taxonomy audit head: role claim, false accusation, false defense,
  info fabrication, team cover, strategic bluff, honest claim.
- Add contradiction and speech-action coherence rates as first-class Track B report fields.
- Add `evidence_ref_coverage` and `track_c_safe_conversion_rate` to Track C dashboard.

## 6. References for the Presentation

- AIWolf contest protocol division uses win rate and per-role win rates as objective measures:
  https://aiwolf.org/en/archives/2873
- AIWolf contest natural language criteria include natural expression, context-aware dialogue,
  contradiction consistency, action-dialogue coherence, and character consistency:
  https://aiwolf.org/en/4th-international-aiwolf-contest
- AIWolfDial 2025 adds macro/micro/role-wise win rates, LLM-based review criteria, and team-play evidence:
  https://aclanthology.org/2025.aiwolfdial-1.1.pdf
- AIWolfDial workshop proceedings include validation of LLM-review reliability against human evaluation:
  https://aclanthology.org/2025.aiwolfdial-1.pdf
- Werewolf Arena frames Werewolf as an LLM benchmark for deception, deduction, persuasion, and arena-style model comparison:
  https://arxiv.org/abs/2407.13943
- Mini-Mafia decomposes social deduction into deception, detection, and disclosure capabilities:
  https://arxiv.org/abs/2509.23023
- WOLF proposes statement-level deception production/detection and longitudinal suspicion dynamics:
  https://arxiv.org/abs/2512.09187
- BloodBench emphasizes claim-level deception labels and game-level behavior traces:
  https://www.bloodbench.com/
- Strategy Bench reports deception and detection indexes across social deduction games:
  https://strategy.freysa.ai/
- Newer social-deduction benchmark directions worth citing in limitations/related work include human-aligned
  strategy evaluation, veracity/truthfulness, and human-baseline deception quality. Use these as motivation
  for future Track B metric heads unless the corresponding annotations are actually run.

## 7. Current Quantified Evidence Snapshot

The current full-module quantification output is stored under
`docs/experiments/core_module_quantification/`. It should be treated as the
paper/presentation scorecard for the existing completed runs, not as a final
claim of statistically significant Track C win-rate lift.

Key quantitative results:

| Module | Metric | Current value | Target | Interpretation |
|---|---:|---:|---:|---|
| Track C retrieval | offline score | 0.7040 | 0.55 | Passes the retrieval-quality gate. |
| Retrieval ranking | nDCG@5 | 0.9587 | 0.80 | Hybrid retrieval ranks relevant lessons near the top. |
| Retrieval precision | P@3 | 0.2821 | 0.20 | Conservative weak-label precision; useful for comparing policies. |
| Retrieval coverage | coverage | 1.0000 | 0.80 | No empty result among the 26 query scenarios. |
| Retrieval safety | candidate leakage | 0 | 0 | No candidate/deprecated leakage in offline evaluation. |
| Retrieval latency | p95 latency | 12.24 ms | 50 ms | Low enough for live agent prompt injection. |
| Formal evidence provenance | v4flash rows | 59 | 20 | Formal evidence uses Volcengine v4flash rows after filtering. |
| Exclusion audit | excluded rows | 44 | report | 20 official DeepSeek rows and 24 pro rows excluded. |
| Architecture evidence coverage | dimensions | 4 | 4 | Covers single-agent behavior, multi-agent behavior, engineering reliability, and B/C loop evidence. |
| Track B leaderboard | top-tier completion | 0.8462 | 0.60 | Leaderboard can separate framework/agent variants. |
| Framework separation | architecture evidence spread | 11.5286 | 5.0 | Variants are separable under the architecture evidence summary. |
| Agent role behavior | single-agent dimension | 0.8982 | 0.70 | Role behavior is strongly measurable in completed formal rows. |
| Multi-agent behavior | multi-agent dimension | 0.7500 | 0.70 | Interaction and role-normalized social deduction are measurable. |
| Advanced B/C ability | advanced dimension | 0.6054 | 0.55 | B/C modules contribute measurable high-level signals. |
| Engineering reliability | fallback/invalid count | 0 / 0 | 0 / 0 | Formal completed rows have no fallback or invalid-action contamination. |
| Track C role/persona analysis | role-MBTI cells | 96 | 96 | Covers 6 roles x 16 MBTI types in auxiliary analysis. |
| Track C auxiliary trend | average non-wolf role delta | +0.0643 | > 0 | Positive trend for non-wolf roles, but not a causal final-agent lift. |
| Information isolation | strict visibility gate | pass | pass | `scripts/verify_visibility_strict.py` passed. |
| Prompt/retrieval wiring | retrieval prompt tests | 19 passed | pass | Auto-injected Track C uses production retrieval policy. |
| Track B consistency | review metric tests | 49 passed, 2 skipped | pass | Role scoring, counterfactuals, MVP, and report gates are covered. |
| Experiment harness | leaderboard tests | 5 passed | pass | v4flash/pro/fake filtering and leaderboard output are covered. |

Track C diagnosis:

- The earlier MBTI/role experiment toggled Track C for every seat, so camp win
  rate is zero-sum. It measures balance shift, not final-agent-vs-initial-agent
  lift.
- The runtime retrieval path previously allowed low-quality fill and bypassed
  the production retrieval policy during auto-injection. This has been changed
  so auto-injected lessons use role/alignment/phase-aware production retrieval
  and skip low-quality fill by default.
- The filtered formal v4flash historical set proves leaderboard
  discriminability and module measurability, but `cognitive_full` superiority
  still needs a paired target-seat A/B design.

Final Track C causal experiment:

Use paired seeds, fixed baseline opponents, and only one target seat upgraded
from baseline to Track C in each paired game. Rotate the target across role and
seat assignments. Report target-agent win rate, role-normalized adjusted final
score, knowledge-hit rate, bad-case reduction, retrieval P@3/nDCG/coverage,
fallback/invalid/info-leak gates, and bootstrap confidence intervals. This is
the correct experiment for the claim that experience summaries improve final
agent performance.
