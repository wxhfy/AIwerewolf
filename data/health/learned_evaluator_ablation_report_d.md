# Learned Evaluator Ablation Report — System D

**Date**: 2026-05-27

## Systems Compared
- **C**: Opportunity + Small Models (base features)
- **D**: Opportunity + Small Models + BGE-M3 Retrieval Features

## Performance
| Metric | C | D | Delta |
|--------|---|---|-------|
| Accuracy | 0.8438 | 0.8452 | +0.0014 |
| Pairwise Acc | 0.9183 | 0.9181 | -0.0002 |

## Per-Fold
| Fold | C Acc | C Paw | D Acc | D Paw |
|------|-------|-------|-------|-------|
| 0 | 0.8519 | 0.9123 | 0.8519 | 0.9120 |
| 1 | 0.8070 | 0.8967 | 0.8070 | 0.8957 |
| 2 | 0.8729 | 0.9516 | 0.8729 | 0.9510 |
| 3 | 0.8702 | 0.9457 | 0.8702 | 0.9457 |
| 4 | 0.8169 | 0.8852 | 0.8239 | 0.8861 |

## Verdict: ⚠ No improvement yet
- C pairwise: 0.9183 → D pairwise: 0.9181 (Δ=-0.0002)
- Retrieval features add similarity-to-good/bad-cases signals
- Benefit is limited when labeled data is small (more data → better retrieval)