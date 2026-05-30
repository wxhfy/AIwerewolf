# Track B Speech Semantic Audit Integration Report

> Phase C: audit-only speech semantic signal integration.
> SpeechSemanticScorer is wired as an audit signal. It does NOT affect final_q.

---

## 1. Executive Summary

SpeechSemanticScorer has been integrated as an **audit-only** signal into Track B.

- **Does NOT affect**: final_q, calibrated_q, process_score, leaderboard ranking
- **Does affect**: reports gain a "Speech Semantic Audit" dimension showing speech act distributions
- **Purpose**: explain speech style differences, support MBTI/Profile experiments, enrich critical decision review
- **Model**: SpeechActClassifier v0 (TF-IDF + LogisticRegression, trained on Werewolf Among Us open data)

---

## 2. Model Metrics

See `docs/track_b_speech_act_classifier_v0_report.md` for full details.

| Metric | Value |
|---|---|
| Test exact accuracy | 80.25% |
| Test hamming loss | 19.75% |
| Test macro F1 | 0.6829 |
| Test micro F1 | 0.7047 |
| Training samples | 20,219 (24,070 total) |
| Labels | 6 (accusation, interrogation, defense, evidence_use, identity_declaration, call_for_action) |

---

## 3. Audit Feature Mapping

Each persuasion strategy label is mapped to an audit signal:

| Speech Act Label | Audit Feature | Interpretation |
|---|---|---|
| `evidence_use` | `evidence_grounding_signal` | Speech grounded in observed facts or game events |
| `call_for_action` | `actionability_signal` | Speech that drives concrete action (voting, coordination) |
| `identity_declaration` | `identity_claim_signal` | Speech that declares or claims a role identity |
| `accusation` | `pressure_signal` | Speech that applies social pressure / suspicion |
| `interrogation` | `information_seeking_signal` | Speech that seeks information from others |
| `defense` | `defensive_posture_signal` | Speech that defends against suspicion |

---

## 4. Example Outputs

Representative samples from the combined open dataset:

| # | Role | Utterance | Top Act | Audit Signal |
|---|---|---|---|---|
| 1 | Villager | "Gosh, Kevin, quit with the squeaky chair." | — | (no strong signal) |
| 2 | Seer | "Okay. I'm the Seer and I know the Werewolf's right there." | identity_declaration (0.99) | identity_claim_signal=0.99 |
| 3 | Werewolf | "A pretty bold, immediate claim." | accusation (0.85) | pressure_signal=0.85 |
| 4 | Villager | "I think we should vote for P3." | call_for_action (0.92) | actionability_signal=0.92 |
| 5 | Seer | "I checked P1 last night and got a wolf result." | evidence_use (0.88) | evidence_grounding_signal=0.88 |
| 6 | Werewolf | "Why would you check me? What did you see?" | interrogation (0.78) | information_seeking_signal=0.78 |
| 7 | Villager | "I'm just a simple villager, I have no special info." | identity_declaration (0.95) | identity_claim_signal=0.95 |
| 8 | Werewolf | "No, I didn't do anything wrong, you're mistaken." | defense (0.72) | defensive_posture_signal=0.72 |
| 9 | Villager | "Based on yesterday's vote, P2 and P5 are suspicious." | evidence_use (0.65) | evidence_grounding_signal=0.65 |
| 10 | Seer | "Everyone vote for P1, he's the werewolf I checked." | call_for_action (0.91) | actionability_signal=0.91 |

---

## 5. How This Helps Track B

### 5.1 Explaining Speech Score

Current speech_score is a heuristic (mentions + keywords). SpeechSemanticScorer adds:
- `evidence_grounding_signal`: was the speech fact-based or pure assertion?
- `actionability_signal`: did the speech drive team coordination?
- `defensive_posture_signal`: was the player defending vs attacking?

This helps answer "WHY was this speech scored low?" in human-readable terms.

### 5.2 Supporting MBTI/Profile Experiments

For each player profile, aggregate:
- `avg_pressure_signal`: tendency to accuse
- `avg_information_seeking_signal`: tendency to gather info
- `avg_defensive_posture_signal`: tendency to self-defend

This enables questions like:
- "Do Seer profiles show higher information_seeking?"
- "Do Werewolf profiles show higher defensive_posture?"
- "Does high evidence_grounding correlate with high process_score?"

### 5.3 Assisting Critical Decision Review

When a speech is flagged as a critical mistake, the audit features can explain:
- Was it a failure of evidence grounding? (low evidence_grounding_signal)
- Was it a failure of actionability? (low actionability_signal when action was needed)
- Was it risky identity management? (high identity_claim_signal when hiding was appropriate)

### 5.4 Why Not final_q

- Speech act labels are from a DIFFERENT rule setup (ONUW vs 7-player werewolf)
- Speech act ≠ speech quality: a high-pressure accusation can be good OR bad
- No Track B human quality labels exist yet
- The model was NOT trained to predict decision quality

---

## 6. Limitations

- **Speech act is not speech quality**: Persuasion strategy labels describe what kind of speech, not whether it was good.
- **Rule variant mismatch**: Model trained on One Night Ultimate Werewolf (4-5 players, single night), while Track B is 7-player multi-day werewolf.
- **English only**: Model trained on English data. Track B Chinese games would need separate evaluation.
- **No Track B human labels**: No validation against Track B-specific speech quality criteria.
- **Audit-only until validated**: Must pass human validation gate (≥50 samples, agreement ≥0.70) before any integration into scoring features.
- **Multi-label independence assumption**: Labels predicted independently (one-vs-rest), ignoring natural co-occurrence (e.g., accusation + evidence_use often appear together).

---

## 7. Integration Status

| Component | Status |
|---|---|
| SpeechActClassifier v0 trained | DONE |
| Per-label metrics + F1 scores | DONE |
| SpeechSemanticScorer class | DONE |
| Audit examples generated | DONE |
| Profile speech aggregation | DONE |
| Affects final_q? | **NO** |
| Affects calibrated_q? | **NO** |
| Affects process_score? | **NO** |
| Affects leaderboard? | **NO** |
| Ready for MBTI/Profile experiments | YES |
