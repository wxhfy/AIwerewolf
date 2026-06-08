# MBTI / Role Track C Auxiliary Analysis

> Generated at: 2026-06-08T03:46:30.950076+00:00

This is auxiliary evidence from player-level JSONL files produced by long-running experiments. Rows contain role, MBTI, win flag, Track C flag, and seed, but not provider/model metadata. Use it for role/persona coverage and trend slides; do not use it alone as v4flash formal proof.

## 1. Coverage

| Metric | Value |
|---|---:|
| Rows | 1043 |
| Seeds | 49 |
| Roles | 6 |
| MBTI types | 16 |
| Track C off rows | 553 |
| Track C on rows | 490 |

## 2. Track C Delta by Role

| Role | Baseline n | Track C n | Baseline win | Track C win | Delta |
|---|---:|---:|---:|---:|---:|
| Guard | 79 | 70 | 15.2% | 22.9% | 7.7% |
| Hunter | 79 | 70 | 15.2% | 22.9% | 7.7% |
| Seer | 79 | 70 | 15.2% | 22.9% | 7.7% |
| Villager | 79 | 70 | 15.2% | 22.9% | 7.7% |
| Werewolf | 158 | 140 | 84.8% | 77.1% | -7.7% |
| Witch | 79 | 70 | 15.2% | 22.9% | 7.7% |

## 3. Top MBTI×Role Positive Deltas

| MBTI×Role | Baseline n | Track C n | Baseline win | Track C win | Delta |
|---|---:|---:|---:|---:|---:|
| Guard+INTP | 2 | 1 | 0.0% | 100.0% | 100.0% |
| Witch+ESFP | 5 | 5 | 0.0% | 60.0% | 60.0% |
| Seer+ESFP | 6 | 6 | 0.0% | 50.0% | 50.0% |
| Witch+ENTP | 6 | 4 | 0.0% | 50.0% | 50.0% |
| Guard+ISFP | 4 | 4 | 0.0% | 50.0% | 50.0% |
| Hunter+INTP | 3 | 4 | 0.0% | 50.0% | 50.0% |
| Witch+ESTP | 3 | 4 | 0.0% | 50.0% | 50.0% |
| Hunter+ENTJ | 3 | 2 | 0.0% | 50.0% | 50.0% |
| Seer+ESTP | 2 | 2 | 0.0% | 50.0% | 50.0% |
| Villager+ENFP | 2 | 2 | 0.0% | 50.0% | 50.0% |
| Witch+INTP | 2 | 2 | 0.0% | 50.0% | 50.0% |
| Guard+ISTP | 7 | 7 | 0.0% | 42.9% | 42.9% |
| Seer+INTP | 7 | 7 | 0.0% | 42.9% | 42.9% |
| Villager+ESTP | 8 | 8 | 0.0% | 37.5% | 37.5% |
| Witch+ESFJ | 7 | 7 | 0.0% | 28.6% | 28.6% |
| Guard+ISFJ | 10 | 8 | 10.0% | 37.5% | 27.5% |
| Seer+ENFP | 5 | 4 | 0.0% | 25.0% | 25.0% |
| Hunter+ESTP | 4 | 4 | 0.0% | 25.0% | 25.0% |
| Seer+INFP | 4 | 4 | 50.0% | 75.0% | 25.0% |
| Villager+ENTJ | 6 | 5 | 0.0% | 20.0% | 20.0% |

## 4. Interpretation

- This dataset supports the presentation claim that the project can analyze role/persona-specific Track C effects.
- It should be paired with the formal v4flash framework analysis for provider/model controlled claims.
- Low-sample MBTI×role cells should be labeled as exploratory.
