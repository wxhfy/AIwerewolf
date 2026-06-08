# Full-Score Experiment Audit

> Date: 2026-06-08
>
> Scope: judge whether the current AI Werewolf project has experiment evidence for the full-score tier in `REQUIREMENTS.md`.

## 1. Current Evidence Status

| Requirement dimension | Weight | Current status | Evidence |
|---|---:|---|---|
| Single Agent ability | 20 | Strong design evidence; partial quantitative evidence | Role/persona/strategy layered CognitiveAgent; Track B player scoring; real v4flash Agent probe generated a non-fallback decision with reasoning and Track C retrieval. |
| Multi-Agent collaboration/system design | 20 | Strong architecture evidence; partial behavior quantification | `Visibility / PlayerView`, strict isolation 92/92, role/skill engine, wolf/team and social model code; v4flash formal rows cover all core roles. |
| Engineering completeness | 30 | Strong evidence | Local gate: `python scripts/verify_visibility_strict.py` passed 92/92; `python -m pytest tests/test_track_bc_leaderboard_experiment.py -q` passed; ruff passed for experiment scripts/tests; generated reports and CSVs. |
| Advanced Track B/C | 30 | Track B leaderboard implemented and demonstrated; Track C outcome evidence is incomplete | Formal v4flash analysis keeps 59 strict rows and excludes 44 mixed/pro/deepseek rows; leaderboard distinguishes tiers. Completion is uneven, so do not claim statistically significant Track C superiority yet. |

## 2. Experiments Archived for This Report

### 2.1 Gate Checks

| Check | Result |
|---|---|
| `python scripts/verify_visibility_strict.py` | 92 passed, 0 failed |
| `python -m pytest tests/test_track_bc_leaderboard_experiment.py -q` | 4 passed |
| `ruff check scripts/analyze_formal_experiment_results.py scripts/track_bc_leaderboard_experiment.py tests/test_track_bc_leaderboard_experiment.py` | passed |
| `ruff format --check ...` | passed |

### 2.2 Real v4flash Endpoint Probe

The available Volcengine endpoint is accessed through the project `doubao` provider using `DOUBAO_ENDPOINT`.

| Probe | Result |
|---|---|
| Minimal chat | returned `OK` |
| Agent decision probe | real LLM `source=llm`, `fallback=false`, provider `doubao`, endpoint model, latency 15022 ms |
| Visibility during probe | viewer saw own role, no other-role fields, no known wolves |
| Track C retrieval during probe | 3 strategy docs retrieved for Guard / Day Speech |
| Emitted event | 1 public chat event, no fallback |

### 2.3 Formal v4flash Historical Result Analysis

Generated artifacts:

- `docs/experiments/formal_v4flash_framework_analysis/report.md`
- `docs/experiments/formal_v4flash_framework_analysis/summary.json`
- `docs/experiments/formal_v4flash_framework_analysis/leaderboard.csv`
- `docs/experiments/formal_v4flash_framework_analysis/rubric_leaderboard.csv`

Strict evidence filter:

| Bucket | Rows |
|---|---:|
| Raw rows | 103 |
| Kept formal v4flash rows | 59 |
| Excluded rows | 44 |

Excluded rows:

- non-Volcengine provider `deepseek`: 20
- pro model row: 24

Formal v4flash leaderboard:

| Rank | Tier | Completed | Failed | Completion | Wolf Win | Village Win | Macro Role Win | LLM Decisions | Fallback | Invalid |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | anti_only | 11 | 2 | 84.6% | 63.6% | 36.4% | 40.9% | 362 | 0 | 0 |
| 2 | baseline | 9 | 4 | 69.2% | 55.6% | 44.4% | 46.3% | 281 | 0 | 0 |
| 3 | trackc_only | 7 | 6 | 53.8% | 71.4% | 28.6% | 35.7% | 188 | 0 | 0 |
| 4 | both / cognitive_full | 7 | 13 | 35.0% | 57.1% | 42.9% | 45.2% | 228 | 0 | 0 |

Rubric leaderboard:

| Rank | Tier | Total | Single Agent /20 | Multi-Agent /20 | Engineering /30 | B/C /30 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | anti_only | 75.13 | 17.96 | 15.00 | 24.00 | 18.16 |
| 2 | baseline | 65.08 | 14.14 | 15.00 | 19.94 | 16.00 |
| 3 | both / cognitive_full | 63.71 | 16.52 | 15.00 | 14.15 | 18.03 |
| 4 | trackc_only | 63.60 | 8.00 | 15.00 | 20.28 | 20.32 |

## 3. Interpretation

The current evidence proves:

- The experiment infrastructure can produce framework/version leaderboards.
- The leaderboard can distinguish `baseline`, `anti_only`, `trackc_only`, and `both`.
- Formal kept rows are v4flash-only and have `fallback=0`, `invalid=0`.
- Track C retrieval is connected to real Agent decisions.
- The system has strong engineering and information-isolation evidence.

The current evidence does not yet prove:

- `cognitive_full` is statistically superior to `baseline`.
- Track C significantly improves overall win rate.
- Human/LLM review agreement is high enough for a final validity claim.
- Frontend latency/visual experience has been freshly measured in this turn.

## 4. Full-Score Boundary

Current project status: near full-score architecture and engineering evidence, but not fully proven full-score experimentally.

Reason:

- The full-score B requirement says the leaderboard should distinguish model/Agent versions. This is implemented and shown.
- The full-score C requirement asks for 20-game improved final-vs-initial evidence. Current filtered v4flash historical rows are useful but uneven by tier; they should not be used to claim significant Track C superiority.
- The full-score engineering requirement is strongly supported by strict visibility, tests, docs, and runnable frontend/backend architecture, but a final presentation should still include fresh frontend screenshots or UI smoke if time allows.

## 5. Next Formal Run Needed

Run this when API load is low:

```bash
export EXPERIMENT_MODEL_POOL="doubao:${DOUBAO_ENDPOINT}"
python scripts/track_bc_leaderboard_experiment.py \
  --axis framework \
  --frameworks basic_react,anti_only,trackc_only,cognitive_full \
  --games 20 \
  --start-seed 4101 \
  --player-count 7 \
  --max-days 5 \
  --output-dir outputs/track_bc_framework_v4flash_20 \
  --skip-client-check
```

Required success criteria:

- 20 requested seeds per framework.
- Balanced completion across frameworks.
- `fallback_count=0`, `invalid_count=0` in accepted rows.
- `leaderboard.json` and `rubric_leaderboard.csv` generated.
- `cognitive_full` or a clearly named final agent version shows positive paired delta against `basic_react`, or the report honestly states the ablation result is negative.
