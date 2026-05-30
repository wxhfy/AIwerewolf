# Track B Open Data Audit Report

> Total datasets: 6
> Total combined samples: 24202

---

## 1. Summary

| Dataset | Samples | Games | Sources | Has final_q? | Missing License? |
| --- | ---: | ---: | --- | --- | --- |
| speech | 24112 | 18 | 2 | no ✓ | no ✓ |
| vote | 42 | 6 | 1 | no ✓ | no ✓ |
| pairwise | 0 | 0 | 0 | no ✓ | no ✓ |
| value | 0 | 0 | 0 | no ✓ | no ✓ |
| role_action | 42 | 6 | 1 | no ✓ | YES ⚠️ |
| opportunities | 6 | 6 | 1 | no ✓ | no ✓ |

## 2. Source Distribution

| Source | Count |
| --- | ---: |
| werewolf_among_us | 24070 |
| track_b_native | 132 |

## 3. Role Distribution

| Role | Count |
| --- | ---: |
| Villager | 13981 |
| Werewolf | 6661 |
| Seer | 2741 |
| Hunter | 593 |
| Unknown | 190 |
| Guard | 18 |
| Witch | 18 |

## 4. Policy Compliance

| Check | Status |
| --- | --- |
| No final_q in open data | PASS ✓ |
| do_not_train_final_q_directly set | PASS ✓ |
| Source metadata present | PASS ✓ |
| Splits by game_id | PASS ✓ |

## 5. Weak Label Distribution

| Label | Count |
| --- | ---: |
| communication_richness | 24019 |
| interrogation | 4102 |
| accusation | 3499 |
| defense | 3266 |
| evidence_use | 2229 |
| call_for_action | 1399 |
| identity_declaration | 1359 |
| speech_score_heuristic | 42 |
| vote_score_heuristic | 42 |
| skill_score_heuristic | 42 |

## 6. Gaps and TODOs

1. **WOLF dataset**: unavailable — release location not confirmed
2. **Beyond Survival**: unavailable — contact authors for access
3. **Deep Wolf / AIWolf**: unavailable — download path pending
4. **Vote samples**: only from Track B native (6 games), need external vote data
5. **Pairwise samples**: empty — need human-labeled or reconstructed pairs
6. **Value impact samples**: empty — need Deep Wolf or AIWolf-style data
