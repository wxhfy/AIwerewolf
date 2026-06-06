# Track B Open Data Audit Report

> Total datasets: 6
> Total combined samples: 95

---

## 1. Summary

| Dataset | Samples | Games | Sources | Has final_q? | Missing License? |
| --- | ---: | ---: | --- | --- | --- |
| speech | 5 | 1 | 1 | no ✓ | YES ⚠️ |
| vote | 42 | 6 | 1 | no ✓ | no ✓ |
| pairwise | 0 | 0 | 0 | no ✓ | no ✓ |
| value | 0 | 0 | 0 | no ✓ | no ✓ |
| role_action | 42 | 6 | 1 | no ✓ | YES ⚠️ |
| opportunities | 6 | 6 | 1 | no ✓ | no ✓ |

## 2. Source Distribution

| Source | Count |
| --- | ---: |
| track_b_native | 90 |
| unknown | 5 |

## 3. Role Distribution

| Role | Count |
| --- | ---: |
| Werewolf | 25 |
| Villager | 13 |
| Seer | 13 |
| Witch | 13 |
| Hunter | 13 |
| Guard | 12 |
| Unknown | 6 |

## 4. Policy Compliance

| Check | Status |
| --- | --- |
| No final_q in open data | PASS ✓ |
| do_not_train_final_q_directly set | PASS ✓ |
| Source metadata present | PARTIAL |
| Splits by game_id | PASS ✓ |

## 5. Weak Label Distribution

| Label | Count |
| --- | ---: |
| vote_score_heuristic | 42 |
| skill_score_heuristic | 42 |

## 6. Gaps and TODOs

1. **WOLF dataset**: unavailable — release location not confirmed
2. **Beyond Survival**: unavailable — contact authors for access
3. **Deep Wolf / AIWolf**: unavailable — download path pending
4. **Vote samples**: only from Track B native (6 games), need external vote data
5. **Pairwise samples**: empty — need human-labeled or reconstructed pairs
6. **Value impact samples**: empty — need Deep Wolf or AIWolf-style data
