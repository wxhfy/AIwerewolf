# Track B Open Data Full Pipeline and Convergence Plan

> Purpose: make Track B stop patching and converge around a data-first route.
>
> This document defines what data to download, how to split it, how to convert it into Track B datasets, how to train small models, how to use those models, and why role-specific models should be delayed until there is enough role/action data.

---

## 1. Final Track B Route

Track B should now be described with four stable parts.

```text
B-Core:
  DecisionOpportunity
    -> feature extraction
    -> OpportunityValueModel: opportunity weight w
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
    -> profile/model leaderboard

B-Data:
  open data reconstruction
    -> small task datasets
    -> audit-only small heads
    -> human validation
    -> optional integration into B-Core
```

Canonical primary scores:

```text
opportunity.final_q
player.process_score
leaderboard.entry_score
```

Audit-only / intermediate scores:

```text
raw_model_q
calibrated_q
learned_rank_q
role_action_z
speech_semantic_q
value_impact_q
legacy scores
```

Current fact:

```text
final_q is currently effectively calibrated_q.
PairwiseRanker remains debug/audit-only until human-validated preference data exists.
```

---

## 2. Why Open Data Reconstruction Is Needed

Current Track B data is still dominated by:

```text
- hand-built labeled_opportunities
- BadCase fixtures
- CleanCase fixtures
- synthetic pairwise expansions
- small real LLM leaderboard smoke tests
```

Current weaknesses:

```text
1. Speech semantic scoring is weak.
2. Vote quality still has degeneracy.
3. PairwiseRanker lacks reliable human preference labels.
4. Real replay validation is limited.
5. Calibration carries too much of the real scoring burden.
```

Therefore, open data should be used to build task-specific datasets rather than directly training final_q.

Do not do:

```text
open data -> DecisionQualityModel -> final_q
```

Do this instead:

```text
open data
  -> canonical schema
  -> small task datasets
  -> audit-only task heads
  -> human validation
  -> optional DQM feature integration
```

---

## 3. Data Sources To Download or Verify

The local agent should create a machine-readable manifest at:

```text
docs/track_b_open_data_sources_manifest.yaml
```

and use it to download and process data.

### 3.1 Source A: Werewolf Among Us

Status:

```text
Primary source. Use first.
Already partially adapted in Phase 1.
```

Paths:

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

Local raw directory:

```text
data/external/raw/werewolf_among_us/
```

Track B outputs:

```text
data/open/werewolf_among_us/track_b_open_game_logs.jsonl
data/open/werewolf_among_us/track_b_open_speech_samples.jsonl
data/open/werewolf_among_us/track_b_open_speech_act_labels.jsonl
```

Use for:

```text
SpeechQualityDataset
SpeechActClassifier
PersuasionStrategyScorer
SpeechSemanticScorer v0
```

Do not use for:

```text
final_q direct training
skill scoring
night-action scoring
role-action scoring outside speech without extra labels
```

Priority:

```text
P0
```

---

### 3.2 Source B: WOLF

Status:

```text
Candidate source. Verify release location and license before use.
```

Path:

```text
Paper: https://arxiv.org/abs/2512.09187
```

Known contents from paper description:

```text
- 100 runs
- 7,320 statements
- role-grounded agents
- self-assessed honesty
- peer-rated deceptiveness
- deception taxonomy: omission, distortion, fabrication, misdirection
- suspicion dynamics across rounds
- structured logs with prompts, outputs, and state transitions
```

Local raw directory:

```text
data/external/raw/wolf/
```

Track B outputs:

```text
data/open/wolf/track_b_open_speech_samples.jsonl
data/open/wolf/track_b_open_deception_samples.jsonl
data/open/wolf/track_b_open_suspicion_samples.jsonl
```

Use for:

```text
DeceptionHead
IdentityManagementHead
SuspicionUpdateScorer
Werewolf speech / deception audit
```

Role-aware warning:

```text
Deception is not automatically bad.
For Werewolf, good deception may be high-quality.
For Villager/Seer, deception may be low-quality depending on context.
```

Priority:

```text
P1 after Werewolf Among Us speech pipeline is stable.
```

---

### 3.3 Source C: Beyond Survival

Status:

```text
Candidate source. Verify actual data release, access requirements, and license.
```

Path:

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

Local raw directory:

```text
data/external/raw/beyond_survival/
```

Track B outputs:

```text
data/open/beyond_survival/track_b_open_speech_samples.jsonl
data/open/beyond_survival/track_b_open_vote_samples.jsonl
data/open/beyond_survival/track_b_open_role_inference_samples.jsonl
data/open/beyond_survival/track_b_open_strategy_alignment_samples.jsonl
```

Use for:

```text
VoteDecisionDataset
SpeechQualityDataset
RoleInferenceDataset
StrategyAlignmentEvaluator
```

Priority:

```text
P1/P2 depending on actual data availability.
```

---

### 3.4 Source D: Deep Wolf / AIWolf-style Logs

Status:

```text
Candidate source. Verify whether human logs are downloadable.
```

Path:

```text
Paper: https://arxiv.org/abs/2302.10646
```

Known contents from paper description:

```text
- game logs from 15 human players
- value network trained to predict posterior probability of winning
- candidate-action evaluation by game phase
- voting-target selection from value prediction
```

Local raw directory:

```text
data/external/raw/deep_wolf_aiwolf/
```

Track B outputs:

```text
data/open/deep_wolf_aiwolf/track_b_open_vote_samples.jsonl
data/open/deep_wolf_aiwolf/track_b_open_value_samples.jsonl
data/open/deep_wolf_aiwolf/track_b_open_candidate_action_samples.jsonl
```

Use for:

```text
ValueImpactHead
VoteTargetValueScorer
CandidateActionValueHead
```

Do not use for:

```text
process quality labels
final_q labels
human preference labels
```

Priority:

```text
P2
```

---

### 3.5 Source E: Werewolf Arena

Status:

```text
Reference source. Use for leaderboard design first; use data only if logs are actually available.
```

Path:

```text
Paper: https://arxiv.org/abs/2407.13943
```

Use for:

```text
Leaderboard design
arena-style model/profile comparison
turn-taking / bidding reference
```

Priority:

```text
Design reference, not primary training data.
```

---

### 3.6 Source F: Track B Native Real LLM Games

Status:

```text
Must be treated as first-class data.
```

Local raw directory:

```text
data/replays/raw_llm_games/
```

Track B outputs:

```text
data/open/track_b_native/track_b_real_opportunities.jsonl
data/open/track_b_native/track_b_real_speech_samples.jsonl
data/open/track_b_native/track_b_real_vote_samples.jsonl
data/open/track_b_native/track_b_real_critical_decisions.jsonl
data/open/track_b_native/track_b_real_counterfactual_pairs.jsonl
```

Use for:

```text
final Track B validation
human pairwise review
profile/model leaderboard
calibration dependency reduction
```

Priority:

```text
P0, together with Werewolf Among Us.
```

---

## 4. One-Time Download and Processing Layout

Use this directory structure.

```text
data/
  external/
    raw/
      werewolf_among_us/
      wolf/
      beyond_survival/
      deep_wolf_aiwolf/
      werewolf_arena/
    checksums/
    licenses/
    manifests/

  open/
    werewolf_among_us/
    wolf/
    beyond_survival/
    deep_wolf_aiwolf/
    track_b_native/
    combined/

  splits/
    open_data/
      speech_train_games.txt
      speech_val_games.txt
      speech_test_games.txt
      vote_train_games.txt
      vote_val_games.txt
      vote_test_games.txt

models/
  open_data/
    speech_act_classifier_v0.pkl
    speech_semantic_scorer_v0.pkl
    vote_decision_scorer_v0.pkl
    value_impact_head_v0.pkl
```

The local agent should add scripts:

```text
scripts/download_track_b_open_sources.py
scripts/build_track_b_open_datasets.py
scripts/audit_track_b_open_datasets.py
scripts/train_speech_semantic_scorer.py
scripts/evaluate_open_data_heads.py
```

Recommended commands:

```bash
python scripts/download_track_b_open_sources.py --manifest docs/track_b_open_data_sources_manifest.yaml --all
python scripts/build_track_b_open_datasets.py --all
python scripts/audit_track_b_open_datasets.py --all
python scripts/train_speech_semantic_scorer.py --source data/open/combined/track_b_open_speech_samples.jsonl
```

Important:

```text
The downloader must support unavailable sources gracefully.
If a dataset cannot be downloaded automatically, it should write a TODO entry and continue.
```

---

## 5. Canonical Schemas

All adapters must write canonical Track B schemas.

### 5.1 CanonicalGameEvent

```json
{
  "event_id": "...",
  "source": "werewolf_among_us",
  "license": "verify_before_use",
  "rule_variant": "one_night_ultimate_werewolf",
  "game_id": "...",
  "turn_index": 12,
  "phase": "DAY_DISCUSSION",
  "actor": "P3",
  "role_if_known_to_dataset": "Werewolf",
  "event_type": "speech|vote|skill|night_action|claim|system",
  "payload": {},
  "visibility": {
    "public": true,
    "private_to": []
  },
  "raw_ref": "..."
}
```

### 5.2 VisibilityState

```json
{
  "visibility_id": "...",
  "game_id": "...",
  "player_id": "P3",
  "phase": "DAY_DISCUSSION",
  "visible_public_context": {},
  "visible_private_context": {},
  "hidden_or_future_context": {},
  "visibility_confidence": "high|medium|low"
}
```

### 5.3 DecisionOpportunity

```json
{
  "opportunity_id": "...",
  "source": "...",
  "game_id": "...",
  "player_id": "...",
  "role": "...",
  "phase": "...",
  "action_type": "speech|vote|skill|night_action|claim_or_info_release",
  "actual_action": {},
  "candidate_actions": [],
  "visible_public_context": {},
  "visible_private_context": {},
  "weak_labels": {},
  "weak_label_source": "open_dataset_annotation|heuristic|outcome_proxy|llm_judge|human|none",
  "do_not_train_final_q_directly": true
}
```

### 5.4 SpeechQualitySample

```json
{
  "sample_id": "speech_000001",
  "source": "werewolf_among_us",
  "license": "verify_before_use",
  "rule_variant": "...",
  "game_id": "...",
  "turn_id": "...",
  "phase": "DAY_DISCUSSION",
  "player_id": "...",
  "role": "Werewolf|Seer|Villager|Hunter|Unknown",
  "utterance": "...",
  "visible_public_context": {},
  "visible_private_context": {},
  "weak_labels": {
    "accusation": 0,
    "interrogation": 0,
    "defense": 0,
    "evidence_use": 0,
    "identity_declaration": 0,
    "call_for_action": 0
  },
  "weak_label_source": "open_dataset_annotation",
  "do_not_train_final_q_directly": true
}
```

### 5.5 VoteDecisionSample

```json
{
  "sample_id": "vote_000001",
  "source": "beyond_survival_or_track_b_native",
  "license": "verify_before_use",
  "rule_variant": "...",
  "game_id": "...",
  "phase": "DAY_VOTE",
  "player_id": "...",
  "role": "...",
  "visible_public_context": {},
  "visible_private_context": {},
  "vote_target": "P3",
  "candidate_targets": ["P1", "P2", "P3"],
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

### 5.6 CounterfactualPairwiseSample

```json
{
  "pair_id": "pair_000001",
  "source": "track_b_native|open_dataset_reconstructed|human",
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

### 5.7 ValueImpactSample

```json
{
  "sample_id": "value_000001",
  "source": "deep_wolf_aiwolf_or_track_b_native",
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

### 5.8 RoleActionSample

```json
{
  "sample_id": "role_action_000001",
  "source": "track_b_native|open_dataset_reconstructed",
  "role": "Seer|Witch|Guard|Hunter|Werewolf|Villager",
  "action_type": "skill|night_action|claim_or_info_release|vote|speech",
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
  "human_label": null,
  "do_not_train_final_q_directly": true
}
```

---

## 6. Dataset Build Plan

### 6.1 Build All Available Data First

The build script should produce all possible datasets, even if some are empty due to missing sources.

```text
data/open/combined/track_b_open_speech_samples.jsonl
data/open/combined/track_b_open_vote_samples.jsonl
data/open/combined/track_b_open_pairwise_samples.jsonl
data/open/combined/track_b_open_value_samples.jsonl
data/open/combined/track_b_open_role_action_samples.jsonl
data/open/combined/track_b_open_opportunities.jsonl
```

Each output file must include:

```text
source
license
rule_variant
weak_label_source
visibility_confidence
do_not_train_final_q_directly
```

### 6.2 Dataset Quality Audit

Produce:

```text
data/open/combined/track_b_open_data_audit.json
docs/track_b_open_data_audit_report.md
```

Audit fields:

```text
total samples by dataset
source distribution
license completeness
rule_variant distribution
role distribution
action_type distribution
weak label distribution
visibility completeness
future-info leakage risk
empty text/action count
samples per game
train/val/test split by game_id
```

### 6.3 Split Policy

All splits must be by game_id.

Do not split by utterance.

```text
train: 70% games
val: 15% games
test: 15% games
```

Reason:

```text
utterance-level random split leaks context across train/test.
```

---

## 7. Training Plan

### 7.1 Stage 1: SpeechActClassifier

Input:

```text
data/open/combined/track_b_open_speech_samples.jsonl
```

Model:

```text
TF-IDF + LogisticRegression
multi-label or multiclass depending on labels
```

Output:

```text
models/open_data/speech_act_classifier_v0.pkl
data/open/combined/speech_act_classifier_v0_metrics.json
docs/track_b_speech_act_classifier_v0_report.md
```

Labels:

```text
accusation
interrogation
defense
evidence_use
identity_declaration
call_for_action
```

Use:

```text
audit-only SpeechSemanticScorer
```

Not use:

```text
final_q
calibrated_q
ProcessScoreV3
```

Promotion condition:

```text
human-reviewed speech sample >= 50
agreement >= 0.70
clean false positive does not rise
```

---

### 7.2 Stage 2: SpeechSemanticScorer

Transform speech act probabilities into audit features.

```text
evidence_use -> evidence_grounding_signal
call_for_action -> actionability_signal
identity_declaration -> identity_claim_signal
accusation -> pressure_signal
interrogation -> information_seeking_signal
defense -> defensive_posture_signal
```

Output schema:

```json
{
  "speech_act_probs": {},
  "audit_features": {},
  "audit_only": true,
  "source_model": "speech_act_classifier_v0"
}
```

Use in reports:

```text
Speech Semantic Audit section
MBTI/Profile behavior analysis
Leaderboard action-type breakdown
```

---

### 7.3 Stage 3: VoteDecisionScorer

Input:

```text
data/open/combined/track_b_open_vote_samples.jsonl
```

Train only after vote samples exist and have enough weak labels.

Output:

```text
vote_target_quality_q
vote_evidence_alignment_q
vote_wagon_value_q
vote_consistency_q
```

Use:

```text
audit-only, then DQM input after validation
```

Promotion condition:

```text
reduces vote degeneracy
does not punish strategic bus / valid cut plays
human-reviewed vote samples >= 50
```

---

### 7.4 Stage 4: ValueImpactHead

Input:

```text
data/open/combined/track_b_open_value_samples.jsonl
```

Output:

```text
value_impact_q
team_value_delta_proxy
```

Use:

```text
night target / vote target auxiliary feature
```

Never use as:

```text
process quality
final_q replacement
```

---

### 7.5 Stage 5: HumanPreferenceHead / PairwiseRanker

Input:

```text
data/open/combined/track_b_open_pairwise_samples.jsonl
human-reviewed pairwise labels
```

Use:

```text
PairwiseRanker through RankerConfidenceGate only
```

Promotion condition:

```text
real replay usable pairs >= 100
heldout accuracy >= 0.70
clean false positive <= 15%
bad false negative <= 15%
inter-annotator agreement measured
```

---

## 8. How These Datasets Are Used In Track B

### 8.1 Immediate Use

```text
open data -> audit-only reports
```

Examples:

```text
Speech Semantic Audit in rubric reports
MBTI/Profile speech-act distribution
leaderboard behavior dimension explanation
```

### 8.2 Medium-Term Use

```text
validated audit heads -> DQM input features
```

Example:

```text
DecisionQualityModel features += speech_semantic_q, evidence_grounding_signal, stance_consistency_q
```

### 8.3 Long-Term Use

```text
human-validated pairwise / role-action datasets -> preference and role heads
```

Only after:

```text
human agreement measured
role/action sample count sufficient
clean false positives controlled
```

---

## 9. Role-Specific Models: Decision

Question:

```text
Should Track B create one small model per role?
```

Answer:

```text
Not yet. Use shared heads with role adapters later.
```

### 9.1 Why Role Models Are Tempting

Roles have different objectives:

```text
Seer: information discovery and release
Witch: potion timing and target risk
Guard: protection timing and target prediction
Hunter: shot discipline
Werewolf: deception, coordination, night target value
Villager: inference, voting, discussion quality
```

### 9.2 Why Independent Role Models Are Too Early

Risks:

```text
- insufficient samples per role
- overfitting to fixtures
- inconsistent calibration across roles
- worse cross-role comparability
- high maintenance cost
```

Minimum data requirement for standalone role model:

```text
>= 300 labeled opportunities per role
>= 50 critical mistakes per role
>= 50 clean examples per role
>= 50 human-reviewed validation examples per role
```

Track B does not have this yet.

### 9.3 Recommended Architecture

Use:

```text
SharedFeatureEncoder
  -> Action Heads:
       SpeechHead
       VoteHead
       SkillHead
       NightActionHead
  -> Role Adapters:
       SeerAdapter
       WitchAdapter
       GuardAdapter
       HunterAdapter
       WerewolfAdapter
       VillagerAdapter
```

This gives role-awareness without fragmenting data.

### 9.4 Current Role Plan

Now:

```text
role-specific diagnostics only
```

Next:

```text
role-specific calibration tables
```

Later:

```text
shared model + role adapters
```

Not now:

```text
six independent role models
```

---

## 10. Implementation Tasks For Local Agent

### Task 1: Data Source Manifest

Create:

```text
docs/track_b_open_data_sources_manifest.yaml
```

Example:

```yaml
sources:
  werewolf_among_us:
    priority: P0
    paper_url: "https://arxiv.org/abs/2212.08279"
    project_url: "https://persuasion-deductiongame.socialai-data.org"
    raw_dir: "data/external/raw/werewolf_among_us"
    expected_outputs:
      - "data/open/werewolf_among_us/track_b_open_speech_samples.jsonl"
    license_status: "verify_before_use"
    auto_download: "best_effort"

  wolf:
    priority: P1
    paper_url: "https://arxiv.org/abs/2512.09187"
    raw_dir: "data/external/raw/wolf"
    license_status: "verify_before_use"
    auto_download: "manual_or_todo_until_release_found"

  beyond_survival:
    priority: P1
    paper_url: "https://arxiv.org/abs/2510.11389"
    raw_dir: "data/external/raw/beyond_survival"
    license_status: "verify_before_use"
    auto_download: "manual_or_todo_until_release_found"

  deep_wolf_aiwolf:
    priority: P2
    paper_url: "https://arxiv.org/abs/2302.10646"
    raw_dir: "data/external/raw/deep_wolf_aiwolf"
    license_status: "verify_before_use"
    auto_download: "manual_or_todo_until_release_found"

  werewolf_arena:
    priority: reference
    paper_url: "https://arxiv.org/abs/2407.13943"
    raw_dir: "data/external/raw/werewolf_arena"
    license_status: "reference_only"
```

### Task 2: One-Time Downloader

Create:

```text
scripts/download_track_b_open_sources.py
```

Requirements:

```text
- read manifest
- create raw directories
- download known direct resources where possible
- write TODO files where no direct download path exists
- preserve license metadata
- never fail the whole pipeline because one source is unavailable
```

### Task 3: Unified Dataset Builder

Create:

```text
scripts/build_track_b_open_datasets.py
```

Requirements:

```text
- run all available adapters
- output all combined dataset files
- preserve source/license/rule_variant metadata
- no final_q generation
- no hard labels unless human-provided
```

### Task 4: Dataset Audit

Create:

```text
scripts/audit_track_b_open_datasets.py
```

Outputs:

```text
data/open/combined/track_b_open_data_audit.json
docs/track_b_open_data_audit_report.md
```

### Task 5: Train SpeechActClassifier

Create or use:

```text
scripts/train_speech_semantic_scorer.py
```

Requirements:

```text
- split by game_id
- train TF-IDF + LogisticRegression
- save model
- output metrics
- audit-only
```

### Task 6: SpeechSemanticScorer Integration

Create:

```text
backend/eval/heads/speech_semantic.py
```

Requirements:

```text
- returns speech act probabilities
- returns audit features
- audit_only = true
- does not return final_q
```

---

## 11. Tests Required

Add or update:

```text
tests/test_track_b_open_data_full_pipeline.py
tests/test_track_b_open_data_sources_manifest.py
tests/test_track_b_speech_semantic_scorer.py
tests/test_track_b_role_model_policy.py
```

Minimum assertions:

```text
- manifest exists
- every source has priority, paper_url, raw_dir, license_status
- downloader creates raw directories or TODO files
- combined dataset builder does not generate final_q
- every output sample has source/license/rule_variant
- every output sample has weak_label_source
- splits are by game_id
- SpeechSemanticScorer returns audit_only=true
- role-model policy blocks standalone role models with insufficient samples
```

---

## 12. Success Criteria

### Minimum

```text
- manifest exists
- downloader exists
- all raw dirs created
- unavailable sources create TODO files
- Werewolf Among Us speech samples remain available
- combined speech dataset exists
- no open data file contains final_q
- dataset audit report exists
```

### Target

```text
- all available open data sources are registered
- 24k+ speech samples included in combined speech dataset
- SpeechActClassifier v0 trained
- audit-only SpeechSemanticScorer exists
- MBTI/Profile report can display speech act distribution
```

### Do Not Claim

Do not claim:

```text
Track B final_q is trained on open data
Track B is human-validated
open data directly proves scoring validity
role-specific models are production ready
```

Allowed claim after this phase:

```text
Track B has a unified open-data reconstruction pipeline and an audit-only speech semantic signal source.
```

---

## 13. Local Agent Prompt

Use this prompt for the local coding agent:

```text
You are working in wxhfy/AIwerewolf.

Task: implement the Track B open-data full pipeline from docs/track_b_open_data_full_pipeline_and_convergence_plan.md.

Do not modify final_q, calibrated_q, ProcessScoreV3, or PairwiseRanker.
Do not add hard caps.
Do not train independent role models.
Do not use outcome labels as process-quality labels.

Implement Phase A:
1. Create docs/track_b_open_data_sources_manifest.yaml.
2. Create scripts/download_track_b_open_sources.py.
3. Create scripts/build_track_b_open_datasets.py.
4. Create scripts/audit_track_b_open_datasets.py.
5. Make all known raw data dirs under data/external/raw/.
6. For unavailable sources, create TODO files instead of failing.
7. Merge existing Werewolf Among Us speech data into data/open/combined/track_b_open_speech_samples.jsonl.
8. Produce data/open/combined/track_b_open_data_audit.json.
9. Produce docs/track_b_open_data_audit_report.md.
10. Add tests for manifest, downloader, dataset builder, no-final_q policy, and role-model policy.

Then implement Phase B only if Phase A passes:
1. Train SpeechActClassifier v0 from combined speech samples.
2. Use game_id split only.
3. Save models/open_data/speech_act_classifier_v0.pkl.
4. Save metrics to data/open/combined/speech_act_classifier_v0_metrics.json.
5. Implement backend/eval/heads/speech_semantic.py.
6. Keep output audit_only=true.
7. Do not affect final_q.

Run:
pytest tests/test_track_b_open_data_full_pipeline.py -q
pytest tests/test_track_b_speech_semantic_scorer.py -q
pytest -q
```
