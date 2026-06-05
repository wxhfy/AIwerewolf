# Track B Open Data Reconstruction and Role-Model Plan

> Goal: converge Track B around a clear scoring route, then use open Werewolf / social-deduction datasets to reconstruct the data Track B actually needs.
>
> This is **not** a plan to directly dump open data into `DecisionQualityModel`.
>
> This is a plan to turn open data into Track B-compatible small datasets: speech quality, vote decision, counterfactual pairwise preference, value impact, and role/action-specific training data.

---

## 1. Current Track B Position

Track B has already converged into the following practical route:

```text
B-Core:
  DecisionOpportunity
    -> feature extraction
    -> OpportunityValueModel: w
    -> DecisionQualityModel: raw_model_q
    -> SoftCalibrator: calibrated_q
    -> final_q

B-Review:
  final_q
    -> CriticalDecision
    -> CounterfactualCase
    -> ImprovementSuggestion
    -> StructuredReport

B-Leaderboard:
  multi-game process scores
    -> role/action breakdown
    -> low sample warning
    -> leaderboard ranking
```

Important current fact:

```text
final_q is currently effectively calibrated_q.
PairwiseRanker is debug/audit-only until it has enough reliable data.
```

The currently useful external-facing dimensions are:

```text
1. Speech quality
2. Vote quality
3. Skill / role-action quality
4. Night-action / target-value quality
5. Critical mistake rate
6. Counterfactual regret / improvement gap
```

Current known weaknesses:

```text
1. Speech semantic quality is weak.
2. Vote pair degeneracy remains non-trivial.
3. PairwiseRanker has insufficient reliable human preference data.
4. Real replay human validation is still missing.
5. Calibration weights still carry too much of the scoring burden.
```

Therefore the next data work should not be more synthetic badcases. It should be open-data reconstruction plus targeted small datasets.

---

## 2. Candidate Open Datasets and Paths

This section lists candidate datasets or paper/project entry points. A local agent must verify actual download availability, license, and data schema before using them.

### 2.1 Werewolf Among Us

Primary path:

```text
Paper: https://arxiv.org/abs/2212.08279
Project / data site: https://persuasion-deductiongame.socialai-data.org
```

Known contents from paper/project description:

```text
- 199 dialogue transcriptions and videos
- 26,647 utterance-level persuasion strategy annotations
- game-level outcome annotations
- dataset, code, and models are stated to be available at the project site
```

Best Track B use:

```text
SpeechQualityDataset
CommunicationQualityHead
PersuasionStrategyScorer
SpeechSemanticScorer
```

Likely fields to extract:

```text
utterance
speaker/player
round/turn
persuasion strategy label
dialogue context
game outcome
```

Track B mapping:

```text
utterance -> speech DecisionOpportunity
persuasion strategy -> speech weak label
game outcome -> outcome weak label, not final_q
```

Risks:

```text
- role setup may differ from current 7-player Track B setup
- multimodal assets may have license or access constraints
- persuasion strategy is not the same as decision quality
- must not use final game outcome as direct quality label
```

Priority:

```text
P0 for speech semantic data.
```

---

### 2.2 WOLF: Werewolf-based Observations for LLM Deception and Falsehoods

Primary path:

```text
Paper: https://arxiv.org/abs/2512.09187
```

Known contents from paper description:

```text
- 100 runs
- 7,320 statements
- role-grounded agents
- statement-level honesty / deceptiveness signals
- deception taxonomy: omission, distortion, fabrication, misdirection
- suspicion dynamics across rounds
- structured logs preserving prompts, outputs, and state transitions
```

Best Track B use:

```text
SpeechQualityDataset
DeceptionHead
IdentityManagementHead
SuspicionUpdateScorer
WolfSpeechQuality features
```

Likely fields to extract:

```text
statement
speaker role
round/phase
self-assessed honesty
peer-rated deceptiveness
suspicion scores
deception type
state transition
```

Track B mapping:

```text
statement -> speech DecisionOpportunity
deception type -> deception_risk / identity_management weak label
suspicion delta -> suspicion_update weak label
peer-rated deceptiveness -> human/social perception weak label
```

Risks:

```text
- dataset release path must be verified
- roles differ from current Track B setup: WOLF includes Doctor rather than Guard/Witch/Hunter depending on setup
- deception is not always bad for werewolves; role-aware mapping is required
- peer suspicion may be noisy
```

Priority:

```text
P0/P1 for speech deception and suspicion features.
```

---

### 2.3 Beyond Survival

Primary path:

```text
Paper: https://arxiv.org/abs/2510.11389
```

Known contents from paper description:

```text
- human-verified multimodal Werewolf dataset
- 100+ hours of video
- 32.4M utterance tokens
- 15 rule variants
- strategy-alignment evaluation
- speech evaluation
- decision evaluation for voting choices and opponent-role inference
```

Best Track B use:

```text
SpeechQualityDataset
VoteDecisionDataset
RoleInferenceDataset
StrategyAlignmentEvaluator
```

Likely fields to extract:

```text
utterances
role claims
vote choices
opponent-role inference
winning faction strategy references
rule variant metadata
```

Track B mapping:

```text
speech evaluation item -> speech quality sample
vote choice -> vote DecisionOpportunity
opponent-role inference -> role inference / belief state sample
winning faction strategy -> weak strategy-alignment target
```

Risks:

```text
- actual dataset download availability must be verified
- 15 rule variants require rule_variant normalization
- strategy alignment is not identical to Track B final_q
- multimodal video data may be heavy and may require special access
```

Priority:

```text
P1 after Werewolf Among Us / WOLF adapter exists.
```

---

### 2.4 Deep Wolf / AIWolf-style Logs

Primary path:

```text
Deep Wolf paper: https://arxiv.org/abs/2302.10646
AIWolf / AIWolfDial references must be verified separately.
```

Known contents from paper description:

```text
- logs from 15 human players
- value network trained to predict posterior probability of winning
- candidate-action evaluation in a given phase
- voting target selection via value network
```

Best Track B use:

```text
ValueImpactDataset
VoteTargetValueScorer
CandidateActionValueHead
```

Likely fields to extract:

```text
game phase
candidate action
vote target
posterior win probability proxy
role
outcome
```

Track B mapping:

```text
candidate action -> CandidateAction
posterior win probability -> value_impact weak label
vote target -> vote target sample
```

Risks:

```text
- human logs may not be publicly downloadable
- win probability is not process quality
- value network targets must remain auxiliary
- role/rule setup may differ from current Track B
```

Priority:

```text
P2, after speech and vote data adapters.
```

---

### 2.5 Werewolf Arena

Primary path:

```text
Paper: https://arxiv.org/abs/2407.13943
```

Best Track B use:

```text
Leaderboard design reference
agent/model comparison reference
not primary training data for opportunity scoring
```

Use:

```text
Reference only for tournament / arena design.
Do not use as core training data unless logs are available and convertible.
```

---

## 3. What Dataset We Actually Need

Track B does not need one giant dataset. It needs several small, clean, purpose-specific datasets.

### 3.1 SpeechQualityDataset

Purpose:

```text
Fix the current weak speech scoring problem.
```

Canonical schema:

```json
{
  "sample_id": "speech_000001",
  "source": "werewolf_among_us",
  "license": "verify_before_use",
  "rule_variant": "unknown_or_dataset_specific",
  "game_id": "...",
  "turn_id": "...",
  "phase": "DAY_DISCUSSION",
  "player_id": "...",
  "role": "Werewolf|Villager|Seer|Witch|Guard|Hunter|Unknown",
  "utterance": "...",
  "visible_public_context": {},
  "visible_private_context": {},
  "weak_labels": {
    "evidence_grounding": null,
    "stance_consistency": null,
    "persuasion_strategy": null,
    "deception_type": null,
    "identity_leak_risk": null,
    "communication_quality": null
  },
  "weak_label_source": "open_dataset_annotation|heuristic|llm_judge|unknown",
  "do_not_train_final_q_directly": true
}
```

Training target:

```text
SpeechSemanticScorer, audit-only first.
```

Outputs:

```text
speech_semantic_q
evidence_grounding_q
stance_consistency_q
deception_risk_q
identity_leak_risk_q
```

Initial use:

```text
Audit-only; compare against current speech score.
Do not affect final_q until validated.
```

---

### 3.2 VoteDecisionDataset

Purpose:

```text
Reduce vote degeneracy and improve vote target quality evaluation.
```

Canonical schema:

```json
{
  "sample_id": "vote_000001",
  "source": "beyond_survival_or_aiwolf",
  "license": "verify_before_use",
  "rule_variant": "...",
  "game_id": "...",
  "phase": "DAY_VOTE",
  "player_id": "...",
  "role": "...",
  "visible_public_context": {},
  "visible_private_context": {},
  "vote_target": "P3",
  "candidate_targets": ["P1", "P2", "P3", "P4"],
  "weak_labels": {
    "matches_public_evidence": null,
    "matches_private_info": null,
    "target_alignment": null,
    "wagon_value": null,
    "vote_consistency": null,
    "outcome_value_proxy": null
  },
  "weak_label_source": "heuristic|open_dataset_annotation|outcome_proxy|human",
  "do_not_train_final_q_directly": true
}
```

Training target:

```text
VoteTargetScorer / VoteDecisionHead.
```

Initial use:

```text
Audit-only features for vote quality.
Use to generate better pairwise candidates.
```

---

### 3.3 CounterfactualPairwiseDataset

Purpose:

```text
Train HumanPreferenceHead / PairwiseRanker only after weak labels are validated.
```

Canonical schema:

```json
{
  "pair_id": "pair_000001",
  "source": "open_dataset_reconstructed|track_b_replay|human",
  "license": "verify_before_use",
  "rule_variant": "...",
  "game_id": "...",
  "role": "Werewolf",
  "action_type": "vote|speech|skill|night_action",
  "visible_context": {},
  "option_a": {
    "action": {},
    "rationale": "..."
  },
  "option_b": {
    "action": {},
    "rationale": "..."
  },
  "label": "A_BETTER|B_BETTER|TIE|UNCERTAIN",
  "label_source": "weak_label|human|llm_judge",
  "confidence": "high|medium|low",
  "reason": "...",
  "do_not_enable_ranker_without_gate": true
}
```

Training target:

```text
HumanPreferenceHead / PairwiseAuxiliaryRanker.
```

Initial use:

```text
Debug/audit only.
RankerConfidenceGate must remain active.
```

---

### 3.4 ValueImpactDataset

Purpose:

```text
Estimate whether an action likely improves game/team value.
```

Canonical schema:

```json
{
  "sample_id": "value_000001",
  "source": "deep_wolf_or_aiwolf_style_logs",
  "license": "verify_before_use",
  "rule_variant": "...",
  "state_id": "...",
  "phase": "DAY_VOTE",
  "role": "...",
  "visible_context": {},
  "candidate_action": {},
  "future_outcome": {
    "winner": "village|wolf|unknown",
    "survival": null
  },
  "weak_labels": {
    "win_probability_proxy": null,
    "team_value_delta_proxy": null,
    "survival_proxy": null
  },
  "weak_label_source": "outcome_proxy|value_network|human",
  "not_process_quality_label": true
}
```

Training target:

```text
ValueImpactHead.
```

Initial use:

```text
Auxiliary only.
Never replace process quality.
```

---

### 3.5 RoleActionDataset

Purpose:

```text
Support role/action-specific calibration and future role heads.
```

Canonical schema:

```json
{
  "sample_id": "role_action_000001",
  "source": "track_b_or_open_reconstructed",
  "role": "Seer",
  "action_type": "claim_or_info_release",
  "visible_context": {},
  "actual_action": {},
  "candidate_actions": [],
  "features": {},
  "weak_labels": {
    "role_goal_alignment": null,
    "information_use": null,
    "risk_control": null,
    "timing": null,
    "counterfactual_gap": null
  },
  "human_label": null
}
```

Training target:

```text
Role adapters or role-specific calibration heads.
```

Initial use:

```text
Diagnostics and calibration, not separate production models yet.
```

---

## 4. Reconstruction Pipeline

Use this pipeline for every open dataset.

```text
Raw Open Dataset
  -> DatasetAdapter
  -> OpenGameLog
  -> CanonicalGameEvent
  -> VisibilityState
  -> DecisionOpportunity
  -> WeakLabelGenerator
  -> Track B small datasets
  -> Audit-only scorer training
  -> Human sample validation
  -> Optional integration into B-Core
```

### 4.1 DatasetAdapter

Responsibilities:

```text
- read raw dataset format
- record source and license
- record rule_variant
- normalize player IDs
- normalize roles
- normalize phases
- normalize utterances/votes/actions
```

Must not:

```text
- generate final_q
- use future information for PreAction labels
- silently drop license metadata
```

### 4.2 CanonicalGameEvent

Canonical event format:

```json
{
  "event_id": "...",
  "source": "...",
  "game_id": "...",
  "timestamp_or_turn": 12,
  "phase": "DAY_DISCUSSION|DAY_VOTE|NIGHT|ROLE_ACTION",
  "actor": "P3",
  "role_if_visible": "Unknown|Seer|Werewolf|...",
  "event_type": "speech|vote|skill|night_action|claim|system",
  "payload": {},
  "visibility": {
    "public": true,
    "private_to": []
  },
  "raw_ref": "..."
}
```

### 4.3 Visibility Reconstruction

Visibility is mandatory.

For every DecisionOpportunity, construct:

```text
visible_public_context
visible_private_context
unavailable_future_context
```

Rules:

```text
- PreAction scoring may only use visible_public_context + visible_private_context.
- Postgame truth may exist in raw data but must be separated.
- If visibility cannot be reconstructed, mark visibility_confidence = low.
- Low visibility samples are allowed for pretraining, but not for final validation.
```

### 4.4 DecisionOpportunity Extraction

Extract opportunities by event type:

```text
speech -> SpeechQualityDataset
vote -> VoteDecisionDataset
skill -> RoleActionDataset
night_action -> RoleActionDataset / ValueImpactDataset
claim/info release -> RoleActionDataset
```

Each opportunity should include:

```text
role
action_type
actual_action
visible context
candidate actions if reconstructable
weak labels if available
source metadata
```

### 4.5 Weak Label Generation

Weak labels must be typed and traceable.

Allowed weak label sources:

```text
open_dataset_annotation
heuristic
outcome_proxy
llm_judge
human
```

Each weak label must include:

```text
label value
label source
confidence
reason or rule name
whether future information was used
```

---

## 5. Weak Label Strategy

### 5.1 Speech Weak Labels

Sources:

```text
Werewolf Among Us persuasion annotations
WOLF deception taxonomy and suspicion dynamics
Beyond Survival speech evaluation items
Track B LLM replay speech
```

Possible labels:

```text
evidence_grounding
stance_consistency
claim_consistency
persuasion_strategy
deception_type
identity_leak_risk
suspicion_delta
communication_quality
```

Mapping examples:

```text
persuasion strategy -> communication style features
deception taxonomy -> deception / identity-management features
suspicion delta -> social impact feature
claim consistency -> evidence grounding / stance consistency
```

Do not:

```text
- treat deception as always bad; for werewolf roles, deception may be good.
- treat persuasive speech as always good; it must align with role objective.
```

### 5.2 Vote Weak Labels

Sources:

```text
vote logs
public claims
role inference labels
outcome proxy
Track B visible context
```

Possible labels:

```text
matches_public_evidence
matches_private_info
target_alignment
wagon_value
vote_consistency
known_wolf_target
wasted_vote
```

Do not:

```text
- use true role if the voter could not know it.
- label every winning-side vote as good.
```

### 5.3 Skill / Role Action Weak Labels

Sources:

```text
role action logs
public/private context
known information state
Track B role heuristics
```

Possible labels:

```text
role_goal_alignment
information_use
risk_control
timing_quality
target_value
counterfactual_gap
```

Do not:

```text
- hard-code final_q from a role heuristic.
- ignore rule_variant differences.
```

### 5.4 Value Impact Weak Labels

Sources:

```text
outcome logs
candidate action win-probability proxy
Deep Wolf style value prediction
```

Possible labels:

```text
win_probability_proxy
team_value_delta_proxy
survival_proxy
```

Do not:

```text
- call this decision quality.
- use value labels as direct final_q labels.
```

### 5.5 Pairwise Weak Labels

Sources:

```text
counterfactual generation
heuristic preference
human review
LLM judge as weak label only
```

Possible construction:

```text
public-evidence-aligned vote > unsupported vote
known-wolf vote > vote elsewhere
high-value night target > low-value night target
safe skill action > obvious friendly-fire skill action
```

Do not:

```text
- train production PairwiseRanker without human validation.
- enable ranker contribution without RankerConfidenceGate.
```

---

## 6. Training Plan

### 6.1 Do Not Train One Giant Model First

Do not start with:

```text
all open data -> DecisionQualityModel -> final_q
```

That will mix incompatible labels:

```text
persuasion strategy
outcome proxy
deception label
vote target
role action
quality label
```

Instead, train small heads.

---

### 6.2 Phase 1: Adapter Only

Goal:

```text
Convert one open dataset into Track B small datasets.
```

Recommended first target:

```text
Werewolf Among Us -> SpeechQualityDataset
```

Why:

```text
Track B's weakest current dimension is speech semantic quality.
Werewolf Among Us has utterance-level persuasion annotations and dialogue context.
```

Output:

```text
data/open/track_b_open_speech_samples.jsonl
data/open/track_b_open_opportunities.jsonl
docs/track_b_open_data_adapter_report.md
```

No model training required in Phase 1.

---

### 6.3 Phase 2: SpeechSemanticScorer

Train a small speech model using open speech samples.

Candidate models:

```text
TF-IDF + LogisticRegression
sentence embedding + LogisticRegression
small transformer embedding + shallow MLP
LLM judge labels -> distilled classifier, if license allows
```

Outputs:

```text
speech_semantic_q
evidence_grounding_q
stance_consistency_q
deception_risk_q
identity_leak_risk_q
```

Use:

```text
Audit-only at first.
Compare against current speech_score and critical mistakes.
```

Promotion gate:

```text
- human-reviewed speech sample >= 50
- agreement >= 0.70 on good/medium/bad speech quality
- no systematic role bias
- improves speech separation without increasing CleanCase false positives
```

---

### 6.4 Phase 3: VoteDecisionScorer

Use Beyond Survival / AIWolf-style vote data if available.

Outputs:

```text
vote_target_quality_q
vote_evidence_alignment_q
vote_wagon_value_q
vote_consistency_q
```

Use:

```text
Audit-only, then feature input to DQM after validation.
```

Promotion gate:

```text
- reduces vote degeneracy
- improves vote pair separation
- does not punish strategic bus / valid cut plays
```

---

### 6.5 Phase 4: ValueImpactHead

Use Deep Wolf / AIWolf-style value data if available.

Outputs:

```text
value_impact_q
team_value_delta_proxy
```

Use:

```text
Auxiliary feature only.
Never replace process quality.
```

Promotion gate:

```text
- correlates with game outcome but does not dominate final_q
- improves night target and vote target ranking
```

---

### 6.6 Phase 5: HumanPreferenceHead / PairwiseRanker

Use reconstructed pairwise samples plus human-reviewed labels.

Outputs:

```text
preference_q
learned_rank_q
```

Use:

```text
Only through RankerConfidenceGate.
```

Promotion gate:

```text
real replay usable pairs >= 100
heldout accuracy >= 0.70
clean false positive <= 15%
bad false negative <= 15%
inter-annotator agreement measured
```

---

## 7. How To Use Reconstructed Data In Track B

### 7.1 Initial Use: Audit Features

At first, all open-data-trained outputs must be audit-only.

```json
{
  "open_data_features": {
    "speech_semantic_q": 0.72,
    "stance_consistency_q": 0.65,
    "deception_risk_q": 0.44,
    "source_model": "speech_semantic_v0",
    "audit_only": true
  }
}
```

They should appear in reports as:

```text
experimental semantic speech signal
```

not as final score.

---

### 7.2 Second Use: DQM Input Feature

After validation, the outputs can become DQM features.

```text
DecisionQualityModel input += speech_semantic_q / vote_target_quality_q / value_impact_q
```

This is safer than directly replacing DQM.

---

### 7.3 Third Use: Calibration Reduction

If DQM becomes more discriminative, gradually reduce calibration dependency.

Example target:

```text
speech calibration dependency decreases
raw_q speech separation increases
CleanCase false positive does not rise
```

---

### 7.4 Fourth Use: HumanPreferenceHead

Only human-reviewed pairwise data should move PairwiseRanker out of debug-only.

Weak labels alone are not enough.

---

## 8. Should We Build One Small Model Per Role?

Short answer:

```text
Possible, but not as fully separate models at the current stage.
```

### 8.1 Why Per-Role Models Are Attractive

Werewolf roles have very different objectives:

```text
Seer: information discovery and release
Witch: potion timing and target risk
Guard: protection timing and target prediction
Hunter: shot discipline
Werewolf: deception, coordination, night target value
Villager: inference, voting, discussion quality
```

So a single global model may blur role-specific quality.

A seer hiding a wolf check and a werewolf hiding private information should not be evaluated with the same meaning.

### 8.2 Why Fully Separate Per-Role Models Are Risky Now

Current data is too small.

Risks:

```text
- each role gets too few samples
- role models overfit fixtures
- calibration becomes inconsistent across roles
- role score comparability becomes worse
- maintenance cost increases
```

A separate model per role only makes sense when each role has enough samples.

Suggested minimum before training a standalone role model:

```text
>= 300 labeled opportunities per role
>= 50 critical / counterfactual examples per role
>= 50 clean examples per role
human-reviewed validation set per role
```

Track B does not have this yet.

### 8.3 Recommended Architecture: Shared Model + Role Heads

Use a shared encoder / shared feature model, then role-specific heads or adapters.

```text
SharedFeatureEncoder
  -> common quality representation
  -> SeerHead
  -> WitchHead
  -> GuardHead
  -> HunterHead
  -> WerewolfHead
  -> VillagerHead
```

This is better than six independent models.

Benefits:

```text
- shared data improves low-sample roles
- role heads capture role-specific scoring
- outputs remain comparable
- easier to maintain
```

### 8.4 Even Better: Role x Action Heads

Some quality logic depends more on action type than role.

Recommended hierarchy:

```text
Global shared encoder
  -> action heads:
       SpeechHead
       VoteHead
       SkillHead
       NightActionHead
  -> role adapters:
       SeerAdapter
       WitchAdapter
       GuardAdapter
       HunterAdapter
       WerewolfAdapter
       VillagerAdapter
```

This matches Track B's actual rubric dimensions.

### 8.5 Practical v1 Plan

Do not train role models yet. Instead:

```text
1. keep current DQM as global baseline
2. add role_id and action_type features
3. train action-specific audit heads first
4. add role-specific calibration reports
5. only train role heads after enough role-labeled data exists
```

Role-specific model status:

```text
Current stage: diagnostics only
Next stage: role-specific calibration tables
Later: shared model + role heads
Not now: independent model per role
```

### 8.6 Role-Specific Output Contract

Even before separate models, reports should output role-specific breakdown:

```json
{
  "role_breakdown": {
    "Seer": {
      "info_release_score": 0.72,
      "vote_alignment_score": 0.68,
      "critical_mistake_rate": 0.15
    },
    "Werewolf": {
      "deception_quality": 0.64,
      "night_target_quality": 0.70,
      "coordination_score": 0.58
    }
  }
}
```

This gives the benefit of role-aware evaluation without overfitting role-specific models.

---

## 9. Fully Converged B Route

Track B should now be described as follows:

```text
Track B evaluates agent process quality at the decision-opportunity level.
It uses calibrated single-step quality scores for speech, vote, skill, and night actions,
then explains critical mistakes through counterfactual review,
and aggregates multi-game results into profile/model leaderboards.
```

Canonical score fields:

```text
Primary:
- opportunity.final_q
- player.process_score
- leaderboard.entry_score

Audit-only:
- raw_model_q
- calibrated_q
- learned_rank_q
- role_action_z
- open_data_semantic_q
- value_impact_q
- legacy scores
```

Canonical B components:

```text
B-Core:
  feature extraction -> raw_q -> calibrated_q/final_q

B-Review:
  critical decision -> counterfactual -> suggestion -> report

B-Leaderboard:
  multi-game process score -> role/action breakdown -> ranking

B-Data:
  open data reconstruction -> small datasets -> audit heads -> validated features
```

What not to do:

```text
- do not add more synthetic badcase patches before open-data reconstruction
- do not add another final score
- do not promote PairwiseRanker without human labels
- do not train independent role models before role data is sufficient
- do not use outcome proxy as process quality
```

---

## 10. Implementation Plan

### Phase 0: Documentation and Contract

Create or update:

```text
docs/track_b_scoring_contract.md
docs/track_b_open_data_reconstruction_and_role_models_plan.md
```

Purpose:

```text
freeze score field definitions
freeze open-data integration policy
freeze role-model policy
```

### Phase 1: Open Data Adapter Prototype

Add files:

```text
backend/eval/open_data/__init__.py
backend/eval/open_data/schema.py
backend/eval/open_data/adapters/__init__.py
backend/eval/open_data/adapters/werewolf_among_us_adapter.py
scripts/build_track_b_open_dataset.py
tests/test_track_b_open_data_adapter.py
```

Prototype target:

```text
Werewolf Among Us speech samples
```

Output:

```text
data/open/track_b_open_speech_samples.jsonl
data/open/track_b_open_opportunities.jsonl
```

Do not train models yet.

### Phase 2: SpeechSemanticScorer v0

Add audit-only scorer:

```text
backend/eval/heads/speech_semantic.py
```

Output fields:

```text
speech_semantic_q
evidence_grounding_q
stance_consistency_q
```

Report only. No final_q impact.

### Phase 3: Human Validation Sample

Sample:

```text
50 open-data speech samples
50 Track B real replay speech samples
```

Human labels:

```text
good / medium / bad
reason
visible context used
```

Acceptance:

```text
agreement >= 0.70 before integration
```

### Phase 4: DQM Feature Integration

Only after Phase 3 passes:

```text
DQM features += speech_semantic_q, stance_consistency_q, evidence_grounding_q
```

Evaluate:

```text
speech separation improves
calibration dependency decreases
clean false positives do not rise
```

### Phase 5: Vote / Value / Role Heads

Repeat for:

```text
VoteDecisionDataset
ValueImpactDataset
RoleActionDataset
```

Keep all new heads audit-only until validated.

---

## 11. Tests Required

Add tests:

```text
tests/test_track_b_open_data_adapter.py
tests/test_track_b_open_data_schema.py
tests/test_track_b_role_model_policy.py
```

Minimum checks:

```text
- source exists
- license metadata exists
- rule_variant exists
- visible_public_context exists
- weak_label_source exists
- no final_q generated from open data adapter
- outcome labels are marked outcome_proxy
- role model policy does not allow independent role model when sample count is too small
```

---

## 12. Success Criteria

### Minimum

```text
- at least one open dataset adapter designed or prototyped
- 100 speech samples exported to Track B schema
- no final_q generated from open data
- license and source metadata preserved
- visibility fields present
- docs explain role model policy
```

### Target

```text
- 1,000+ speech samples exported
- SpeechSemanticScorer v0 audit-only
- 50-sample human validation set prepared
- initial agreement report generated
```

### Do Not Claim

Do not claim:

```text
Track B is trained on open data
Track B final_q is validated by open data
role-specific models are production ready
human alignment is complete
```

Allowed claim after Phase 1:

```text
Track B has an open-data reconstruction path and can export external speech/vote data into Track B-compatible schemas.
```

Allowed claim after Phase 2:

```text
Track B has an audit-only semantic speech signal trained from reconstructed open data.
```

Allowed claim only after human validation:

```text
SpeechSemanticScorer shows initial alignment with human review.
```
