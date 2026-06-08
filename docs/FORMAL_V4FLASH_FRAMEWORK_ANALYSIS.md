# Formal v4flash Framework Experiment Analysis

> Generated at: 2026-06-08T03:38:52.667146+00:00
> Source directory: `data/experiment/multi_tier/formal_dsv4flash_7p_tier_6x_v2`

## 1. Evidence Filter

Formal rows keep only Volcengine v4flash records: provider in `dsv4flash/doubao`, model text contains `deepseek-v4-flash`, and model text does not contain `pro`.

| Bucket | Rows |
|---|---:|
| Raw rows | 103 |
| Formal v4flash rows | 59 |
| Excluded rows | 44 |

Excluded reasons:

- non-Volcengine provider: deepseek: 20
- pro model row: 24

## 2. Track B/C Framework Leaderboard

| Rank | Tier | Completed | Failed | Completion | Wolf Win | Village Win | Macro Role Win | LLM Decisions | Fallback | Invalid |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `anti_only` / anti_only | 11 | 2 | 84.6% | 63.6% | 36.4% | 40.9% | 362 | 0 | 0 |
| 2 | `baseline` / basic_react | 9 | 4 | 69.2% | 55.6% | 44.4% | 46.3% | 281 | 0 | 0 |
| 3 | `trackc_only` / trackc_only | 7 | 6 | 53.8% | 71.4% | 28.6% | 35.7% | 188 | 0 | 0 |
| 4 | `both` / cognitive_full | 7 | 13 | 35.0% | 57.1% | 42.9% | 45.2% | 228 | 0 | 0 |

## 3. Rubric Leaderboard

Mapped to `REQUIREMENTS.md`: single Agent 20%, multi-Agent/system 20%, engineering 30%, advanced B/C 30%.

| Rank | Tier | Total | Single Agent /20 | Multi-Agent /20 | Engineering /30 | B/C /30 | Key Evidence |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `anti_only` / anti_only | 75.13 | 17.96 | 15.00 | 24.00 | 18.16 | complete=84.6%; wolf=63.6%; macro_role=40.9%; fallback=0; invalid=0 |
| 2 | `baseline` / basic_react | 65.08 | 14.14 | 15.00 | 19.94 | 16.00 | complete=69.2%; wolf=55.6%; macro_role=46.3%; fallback=0; invalid=0 |
| 3 | `both` / cognitive_full | 63.71 | 16.52 | 15.00 | 14.15 | 18.03 | complete=35.0%; wolf=57.1%; macro_role=45.2%; fallback=0; invalid=0 |
| 4 | `trackc_only` / trackc_only | 63.60 | 8.00 | 15.00 | 20.28 | 20.32 | complete=53.8%; wolf=71.4%; macro_role=35.7%; fallback=0; invalid=0 |

## 4. Paired Seed Deltas

### anti_only vs baseline

- Paired seeds: 8
- Avg wolf-win delta: 0.0
- Avg village-win delta: 0.0
- Positive wolf-delta seeds: 1
- Same-winner seeds: 6

### trackc_only vs baseline

- Paired seeds: 6
- Avg wolf-win delta: 0.166667
- Avg village-win delta: -0.166667
- Positive wolf-delta seeds: 2
- Same-winner seeds: 3

### both vs baseline

- Paired seeds: 6
- Avg wolf-win delta: 0.0
- Avg village-win delta: 0.0
- Positive wolf-delta seeds: 1
- Same-winner seeds: 4

### both vs anti_only

- Paired seeds: 6
- Avg wolf-win delta: -0.166667
- Avg village-win delta: 0.166667
- Positive wolf-delta seeds: 1
- Same-winner seeds: 3

## 5. Interpretation Against Rubric

- Single Agent: evidence comes from real LLM decisions, role coverage, and no fallback in formal rows. This report does not inspect prompt text directly; use `docs/EXPERIMENT_SECTION_DESIGN.md` and code references for prompt-layer evidence.
- Multi-Agent: evidence comes from role/team outcome, role coverage, paired seeds, and strict information isolation gate. The strongest claim is that the platform supports role-differentiated multi-agent experiments; direct deception/detection scoring still needs the Track B semantic audit output.
- Engineering: formal rows show real v4flash games with fallback=0; failed rows remain visible in completion-rate penalties. Visibility strict was run separately and passed 92/92.
- Advanced B/C: Track B/C variants are distinguishable in the leaderboard, but this filtered historical dataset has uneven completion by tier. Treat Track C outcome claims as evidence, not final significance proof.

## 6. Conclusion Boundary

Use this report for the project presentation as a formal experiment audit. Do not claim `cognitive_full` is statistically superior unless the 20-seed paired runner completes with balanced completion across all four frameworks. The current evidence is enough to show the leaderboard can distinguish framework versions and that B/C modules are experimentally testable under v4flash.
