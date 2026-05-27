# Embedding Retrieval Evaluation (Phase D)

**Model**: BGE-M3 (/home/4T-3/PLM/bge-m3/)
**Dim**: 1024
**Good cases**: 447, **Bad cases**: 193
**Retrieval features**: neighbor similarity to good/bad cases

## Anti-Leakage
Each GroupKFold test split retrieves from train-split-only index.

## Results
| Metric | C (Base) | D (+Retrieval) | Delta |
|--------|----------|----------------|-------|
| Accuracy | 0.8438 | 0.8452 | +0.0014 |
| Pairwise Acc | 0.9183 | 0.9181 | -0.0002 |
| Folds | 5 | 5 | |