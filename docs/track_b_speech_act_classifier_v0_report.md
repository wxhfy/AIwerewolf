# Track B SpeechActClassifier v0 Report

> Generated from open data (Werewolf Among Us) via Phase B training pipeline.
> Model: TF-IDF + MultiOutputClassifier(LogisticRegression)
> Status: audit-only, does not affect final_q

---

## 1. Dataset

| Property | Value |
|---|---|
| Source | `bolinlai/Werewolf-Among-Us` (HuggingFace) |
| Rule variant | One Night Ultimate Werewolf |
| Total utterances | 24,070 (with persuasion strategy annotations) |
| Games | 191 |
| License | verify_before_use |

### Label Distribution

| Label | Count | % of samples |
|---|---|---|
| interrogation | 4,102 | 17.0% |
| accusation | 3,499 | 14.5% |
| defense | 3,266 | 13.6% |
| evidence_use | 2,229 | 9.3% |
| call_for_action | 1,399 | 5.8% |
| identity_declaration | 1,359 | 5.6% |

Note: labels are multi-label (one utterance can have multiple labels). 24,019 of 24,070 samples have at least one label.

### Game-ID Split

| Split | Games | Samples |
|---|---|---|
| Train | ~70% | 20,219 |
| Val | ~15% | 2,356 |
| Test | ~15% | 1,495 |

Split is by game_id (NOT by utterance) to prevent context leakage.

---

## 2. Model

| Property | Value |
|---|---|
| Type | TF-IDF + MultiOutputClassifier(LogisticRegression) |
| Vocabulary size | 5,000 |
| N-gram range | (1, 2) |
| Max features | 5,000 |
| Class weight | balanced |
| Multi-label strategy | one-vs-rest (MultiOutputClassifier) |

---

## 3. Performance

### Overall

| Metric | Train | Val | Test |
|---|---|---|---|
| Exact accuracy | 84.43% | 80.01% | **80.25%** |
| Hamming loss | — | 19.99% | **19.75%** |
| Macro F1 | — | — | **0.6829** |
| Micro F1 | — | — | **0.7047** |

Exact accuracy = fraction of samples where ALL 6 labels match perfectly.
Hamming loss = fraction of individual labels that are wrong (lower = better).

### Per-Label (Test Set)

| Label | Support | Precision | Recall | F1 |
|---|---|---|---|---|
| identity_declaration | 99 | 0.7273 | 0.7273 | **0.7273** |
| call_for_action | 69 | 0.7246 | 0.7246 | **0.7246** |
| accusation | 232 | 0.7198 | 0.7198 | **0.7198** |
| evidence_use | 141 | 0.6525 | 0.6525 | **0.6525** |
| interrogation | 219 | 0.5434 | 0.5434 | **0.5434** |
| defense | 157 | 0.5159 | 0.5159 | **0.5159** |

---

## 4. Strongest Labels

1. **identity_declaration** (F1=0.7273): Role claims ("I am the Seer", "I'm a Villager"). Distinctive keyword patterns make this easy.
2. **call_for_action** (F1=0.7246): Voting/killing directives ("vote for...", "let's kill..."). Strong imperative patterns.
3. **accusation** (F1=0.7198): Accusing others ("you're a werewolf", "lying"). Rich vocabulary of suspicion terms.

## 5. Weakest Labels

1. **defense** (F1=0.5159): Defensive speech is more nuanced and context-dependent. "I didn't do it" overlaps with identity claims and evidence use.
2. **interrogation** (F1=0.5434): Questions ("did you look?", "what did you see?") are syntactically diverse and overlap with other acts.
3. **evidence_use** (F1=0.6525): Evidence-based reasoning uses past-tense observation verbs, but the boundary with accusation is blurry.

---

## 6. Limitations

- **Rule variant mismatch**: ONUW (One Night) differs from Track B's 7-player multi-day werewolf. Speech patterns may differ.
- **English only**: the dataset is English-language. Track B Chinese games would need a separate or multilingual model.
- **Speech act != speech quality**: Persuasion strategy labels describe WHAT kind of speech, not HOW GOOD it is.
- **Audit-only**: this model must never affect final_q, calibrated_q, or process_score.
- **No Track B human labels**: no validation against Track B-specific speech quality criteria.
- **Multi-label correlation**: labels are predicted independently (one-vs-rest), ignoring co-occurrence patterns.
