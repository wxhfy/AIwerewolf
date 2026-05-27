# CounterfactualImpact Report

**Total counterfactuals**: 976
  - Vote flip: 863
  - Skill swap: 113
**Mean absolute impact**: 0.310

## Top Impact Players
| Player ID | Role | Total Impact | N Counterfactuals |
|-----------|------|-------------|-------------------|
| P6-4ae04e | Werewolf | +2.000 | 4 |
| P1-0db4f8 | Witch | +1.600 | 5 |
| P5-956c01 | Witch | -1.600 | 4 |
| P6-9bc1da | Werewolf | +1.500 | 3 |
| P7-8a2b79 | Werewolf | +1.500 | 3 |
| P5-e3d4ca | Guard | -1.500 | 4 |
| P6-8bd83a | Villager | -1.500 | 4 |
| P7-8cff13 | Hunter | -1.500 | 4 |
| P7-9da2b3 | Werewolf | +1.500 | 3 |
| P4-dd1b1b | Hunter | -1.500 | 3 |

## Methodology
- vote_flip: what if one player voted differently? Impact = alignment change value
- skill_swap: what if witch poisoned/saved a different target?
- Impact values in [-1, 1] range, where + = improvement over actual
- Confidence is low (0.5-0.6) for MVP; needs better causal modeling