# Track B Learning-First Scoring Refactor Plan

> Goal: evolve Track B from rule/calibration-driven badcase scoring into a learning-first, evidence-grounded, role-aware decision-quality evaluator.
>
> Scope: Track B scoring only. Do not modify Track C, frontend UI, or core game engine rules during this refactor.

---

## 1. Why refactor

Current Track B has already proven useful through BadCase/CleanCase/Generalization Matrix tests:

- BadCase-001: detects obvious village-power mistakes.
- BadCase-002: detects low-quality werewolf play.
- CleanCase-001: avoids penalizing a class of high-quality wolf play.
- Generalization Matrix: seat-swap, phrase-swap, and leave-one-template-out smoke tests.

The remaining weaknesses are:

1. Speech raw model scores are still too high in many cases.
2. Clean wolf false-positive rate is still non-trivial.
3. Soft calibration remains hand-weighted.
4. Pairwise examples are still limited and mostly synthetic.
5. Leaderboard is not yet a robust model/agent-version capability estimate.

The next system should preserve current strengths while moving quality judgment from hand rules into learned ranking.

---

## 2. Principle

Hard rules are allowed only for:

- game legality;
- schema validity;
- information leakage / visibility safety;
- LLM parse/fallback robustness;
- impossible actions.

Decision quality should be learned from:

- dynamic features;
- private/public context;
- role-objective alignment;
- counterfactual candidates;
- pairwise preferences;
- real replay human calibration.

Do not add more hard caps for quality unless used as temporary safety scaffolding and explicitly reported as such.

---

## 3. External open-source work integration

Open-source social-deduction work should not replace Track B. It should provide pretrained feature extractors and weak signals.

### 3.1 Werewolf Among Us

Use for:

- persuasion strategy features;
- utterance type recognition;
- public evidence grounding;
- attack/defense/persuasion speech signals.

Output component:

```text
SpeechStrategyEncoder
```

### 3.2 WOLF-style deception/suspicion data

Use for:

- deception type classification;
- omission / distortion / fabrication / misdirection features;
- suspicion-delta modeling;
- liar-vs-detector interaction features.

Output components:

```text
DeceptionFeatureExtractor
SuspicionDeltaModel
```

### 3.3 Beyond Survival-style strategy alignment

Use for:

- stance selection;
- speech evaluation tasks;
- voting choice evaluation;
- opponent-role inference.

Output components:

```text
StanceQualityModel
RoleInferenceFeatureExtractor
VoteRationaleModel
```

### 3.4 Avalon-style hidden-role dialogue data

Use for:

- long-horizon hidden-role inference;
- multi-turn consistency;
- public speech to belief-state updates.

Output component:

```text
BeliefStateFeatureExtractor
```

---

## 4. New scoring architecture

```text
GameState / ReplayBundle / PlayerView
        ↓
DecisionOpportunity
        ↓
Feature Extractor Registry
        ├─ BaseActionFeatures
        ├─ VisibilityFeatures
        ├─ PrivateContextFeatures
        ├─ SpeechStrategyFeatures
        ├─ DeceptionFeatures
        ├─ SuspicionDynamicsFeatures
        ├─ RoleObjectiveFeatures
        ├─ VoteCoordinationFeatures
        ├─ SkillTargetValueFeatures
        └─ CounterfactualFeatures
        ↓
Pairwise Preference Dataset
        ↓
DecisionQualityRanker
        ↓
Uncertainty + Light Soft Calibration
        ↓
OpportunityScore
        ↓
PlayerProcessScoreV3
        ↓
Review / Suggestions / Leaderboard
```

---

## 5. Core data contracts

### 5.1 DecisionOpportunityV2

Every scoreable decision must include:

```json
{
  "opportunity_id": "...",
  "game_id": "...",
  "player_id": "P2",
  "role": "Werewolf",
  "phase": "DAY_SPEECH",
  "day": 1,
  "action_type": "speech",
  "chosen_action": {},
  "legal_actions": [],
  "public_context": {},
  "private_context": {},
  "visibility_scope": {},
  "evidence_event_ids": [],
  "source_decision_id": "...",
  "counterfactual_candidates": []
}
```

### 5.2 OpportunityScoreV2

The final opportunity score must preserve raw and adjusted signals:

```json
{
  "opportunity_id": "...",
  "raw_model_q": 0.42,
  "learned_rank_q": 0.40,
  "calibrated_q": 0.37,
  "opportunity_value": 0.82,
  "role_action_z": -0.76,
  "role_action_percentile": 0.22,
  "uncertainty": 0.18,
  "confidence": "medium",
  "features": {},
  "top_feature_contributions": [],
  "counterfactuals": [],
  "calibration": {
    "used": true,
    "hard_cap_used": false,
    "total_delta": -0.03,
    "reasons": []
  },
  "suggestion": "..."
}
```

### 5.3 PairwisePreferenceExample

```json
{
  "pair_id": "...",
  "source": "generalization_matrix|real_replay|human_label|external_pretrain",
  "role": "Werewolf",
  "action_type": "speech",
  "same_context": true,
  "context": {},
  "better": {"opportunity": {}, "reason": "..."},
  "worse": {"opportunity": {}, "reason": "..."},
  "label_confidence": "high|medium|low",
  "human_annotator_id": null
}
```

---

## 6. Feature Extractor Registry

Refactor feature extraction away from one large scoring function.

Recommended modules:

```text
backend/eval/features/base.py
backend/eval/features/private_context.py
backend/eval/features/speech_strategy.py
backend/eval/features/deception.py
backend/eval/features/suspicion.py
backend/eval/features/role_objective.py
backend/eval/features/vote.py
backend/eval/features/skill_target.py
backend/eval/features/counterfactual.py
backend/eval/features/registry.py
```

Each extractor should implement:

```python
class FeatureExtractor(Protocol):
    name: str
    version: str
    def supports(self, opportunity: dict) -> bool: ...
    def extract(self, opportunity: dict, context: dict) -> dict[str, float | int | str]: ...
```

The registry returns one flat feature dict plus provenance:

```json
{
  "features": {"speech_grounding_score": 0.42},
  "feature_sources": {"speech_grounding_score": "speech_strategy:v1"}
}
```

---

## 7. Learning-first model stack

### 7.1 Short term: pairwise-derived binary labels

Use existing sklearn models, but feed stronger pairwise-derived examples.

Bad/good opportunities become low/high quality labels:

```text
worse -> quality 0.10-0.30
better -> quality 0.70-0.95
```

This is acceptable for MVP.

### 7.2 Mid term: true pairwise ranker

Add a ranker that optimizes:

```text
score(better) > score(worse)
```

Potential implementation:

- LightGBM ranker if dependency is allowed;
- sklearn GradientBoosting with pairwise-difference features;
- logistic regression over `features_better - features_worse`.

Recommended MVP:

```text
PairwiseLogisticRanker
```

Input:

```text
x = features_a - features_b
label = 1 if a better than b else 0
```

At inference:

- compute absolute quality with base DQM;
- compute ranking preference against generated counterfactuals;
- combine both.

### 7.3 Long term: text encoder integration

Speech raw_q weakness should be handled by a text encoder pretrained on open-source social-deduction data.

Inputs:

- utterance text;
- public context summary;
- role;
- action type;
- prior stance;
- target player.

Outputs:

```text
speech_strategy_logits
speech_grounding_score
deception_type_logits
stance_consistency_score
suspicion_delta_prediction
```

---

## 8. Training data strategy

### 8.1 Synthetic controlled matrix

Keep using controlled data for regression:

- BadCase-001;
- BadCase-002;
- CleanCase-001;
- generalization matrix variants.

Purpose:

- deterministic regression;
- coverage of rare high-leverage actions;
- anti-overfitting smoke tests.

### 8.2 Open-source pretraining

Use open-source social-deduction data to pretrain speech/deception/role-inference features.

Purpose:

- reduce reliance on templates;
- learn natural language variation;
- improve speech raw_q.

### 8.3 Real replay human pairwise labels

This is mandatory before claiming a robust evaluator.

Sampling target:

```text
speech: 200 pairs
vote: 100 pairs
night kill: 60 pairs
seer release/check: 60 pairs
witch actions: 60 pairs
hunter/guard actions: 60 pairs
ambiguous/tie: 100 pairs
```

Evaluation:

```text
pairwise accuracy >= 0.70
Spearman >= 0.60
clean false positive <= 0.15
bad false negative <= 0.15
calibration dependency <= 0.30
```

---

## 9. ProcessScoreV3

Replace process scoring with a role-normalized, confidence-aware aggregate.

```text
weighted_quality = Σ(value_i * calibrated_q_i) / Σ(value_i)
critical_regret = mean(max_counterfactual_delta over critical opportunities)
role_z = mean(role_action_z_i)
confidence = aggregate_uncertainty(opportunities)
```

Recommended score:

```text
process_score_v3 =
  0.45 * weighted_quality
+ 0.20 * role_normalized_quality
+ 0.15 * speech_quality
+ 0.10 * robustness
+ 0.10 * high_impact_positive_rate
- 0.20 * critical_regret_rate
```

Also output:

```text
sample_count
confidence_interval
low_sample_warning
calibration_dependency_rate
```

---

## 10. GameEvaluationValueScore

Add a separate score for whether a game is useful for training/evaluation.

```json
{
  "game_id": "...",
  "decision_signal": 0.82,
  "reviewability": 0.90,
  "leaderboard_value": 0.62,
  "training_value": 0.88,
  "clean_case_value": 0.40,
  "badcase_value": 0.91,
  "recommended_use": ["badcase_training", "strategy_replay"],
  "not_recommended_use": ["model_capability_leaderboard"]
}
```

This avoids collapsing all games into one vague quality score.

---

## 11. LeaderboardV2

Leaderboard must aggregate by version, not just player.

Keys:

```text
model_id
agent_version
prompt_version
strategy_version
persona_id
role
action_type
seed
```

Metrics:

```text
avg_process_score_v3
avg_role_action_z
critical_mistake_rate
calibration_dependency_rate
raw_model_correct_rate
speech_quality
vote_quality
skill_quality
confidence_interval
sample_count
```

Do not rank entries with low sample count without warning.

---

## 12. Migration plan

### Phase 1: Contracts and registry

- Add DecisionOpportunityV2 / OpportunityScoreV2 schemas.
- Add feature extractor registry.
- Keep old scoring path as legacy.
- Output both legacy and vNext scores.

### Phase 2: Pairwise-first training

- Expand pairwise dataset.
- Add PairwiseLogisticRanker.
- Report raw-vs-calibrated dependency.
- Keep hard_cap_count at 0 for quality scoring.

### Phase 3: Speech/deception pretraining

- Add import/preprocess scripts for external datasets.
- Train SpeechStrategyEncoder / DeceptionFeatureExtractor.
- Add speech features into DQM.

### Phase 4: Real replay calibration

- Build human labeling UI or JSON workflow.
- Label real replay pairs.
- Evaluate human agreement and model agreement.

### Phase 5: LeaderboardV2

- Aggregate by agent/model/prompt/strategy versions.
- Add role/action normalization and confidence intervals.

---

## 13. Required tests

### Regression tests

- Existing BadCase-001.
- Existing BadCase-002.
- Existing CleanCase-001.
- Existing Generalization Matrix.

### New tests

```text
test_feature_registry_outputs_expected_fields
test_no_quality_hard_caps_used
test_pairwise_ranker_prefers_better_action
test_speech_features_change_raw_q
test_real_replay_label_format_valid
test_process_score_v3_role_normalized
test_game_evaluation_value_score
test_leaderboard_v2_grouping
```

---

## 14. Success criteria

Track B vNext is considered successful when:

```text
hard_cap_count = 0 for quality scoring
clean false positive <= 15%
bad false negative <= 15%
speech raw_model_good_bad_separation >= 0.25
pairwise examples >= 300
real replay pairwise accuracy >= 70%
calibration_dependency <= 30%
role-action z stable across seat/phrase swaps
LeaderboardV2 can separate at least two agent/model versions with confidence intervals
```

---

## 15. What not to claim yet

Do not claim:

- full human-expert level evaluation;
- complete general scorer;
- probability-calibrated score;
- complete speech understanding;
- leaderboard validity without multi-seed/version tests.

Safe claim after Phase 2:

```text
Track B provides a learning-first, role-aware decision-quality evaluator with controlled generalization tests and auditable scoring outputs.
```
