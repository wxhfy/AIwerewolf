# Learned Evaluator Ablation Report

## Systems Compared
- **A**: Old Rule Baseline (camp_result + role_task + vote + speech + skill + survival)
- **B**: Opportunity-Only Rule (w(o) × q(o) with heuristic rules)
- **C**: Opportunity + Small Models (w(o) rule, q(o) from LightGBM/LogisticRegression)

## Per-Role Cohen's d (Good vs Bad Separation)
| Role | A (Old Rule) | B (Rule Opp) | C (Small Models) | Target |
|------|-------------|-------------|------------------|--------|
| Werewolf | 2.757 | 0.000 | 0.000 | >=0.5 |
| Seer | 1.257 | 0.000 | 0.000 | >=0.5 |
| Witch | 1.855 | 0.000 | 0.000 | >=0.5 |
| Guard | 2.260 | 0.000 | 0.000 | >=0.3 |
| Hunter | 2.286 | 0.000 | 0.000 | >=0.5 |
| Villager | 2.352 | 0.000 | 0.000 | >=0.5 |

## Pairwise Accuracy
DecisionQualityModel mean pairwise accuracy: 0.000

## Witch / Guard / Hunter Improvement
| Role | Old Rule Issue | New Model Fix | Status |
|------|---------------|---------------|--------|
| Witch | Outcome-dependent (poison=bad if hit good regardless of evidence) | Evidence-weighted quality score | Pending validation |
| Guard | Only scored on 'did guard block a kill' | Strategy quality scored regardless of wolf target | Pending validation |
| Hunter | Low-opportunity, max 1 shot/game | Restraint + shot quality weighted by suspicion | Pending validation |