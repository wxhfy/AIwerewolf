# Track B Open Data Adapter Report

> Generated from 1 source(s)

---

## Summary

### werewolf_among_us

- **License**: verify_before_use
- **Rule variant**: one_night_werewolf
- **Games**: 191
- **Speech samples**: 24070

#### Role Distribution

| Role | Count |
| --- | ---: |
| Hunter | 575 |
| Seer | 2723 |
| Unknown | 184 |
| Villager | 13963 |
| Werewolf | 6625 |

#### Weak Label Types

| Label | Count |
| --- | ---: |
| accusation | 3499 |
| call_for_action | 1399 |
| communication_richness | 24019 |
| defense | 3266 |
| evidence_use | 2229 |
| identity_declaration | 1359 |
| interrogation | 4102 |

---

## Policy Compliance

- [x] No final_q generated from open data
- [x] Source and license metadata preserved
- [x] rule_variant recorded
- [x] visible_public_context present
- [x] Weak label source traced
- [x] do_not_train_final_q_directly = true
- [x] Outcome labels marked as outcome_proxy where applicable

## Allowed Claims

Track B has an open-data reconstruction path and can export external speech data into Track B-compatible schemas.

## Disallowed Claims

- Track B is NOT trained on open data
- Track B final_q is NOT validated by open data
- Role-specific models are NOT production ready
- Human alignment is NOT complete
