# Track B Scoring Contract

> Generated: 2026-05-29
> Freezes score field definitions, open-data integration policy, and role-model policy.

---

## 1. Canonical Score Fields

### Primary (rubric-facing)

| Field | Source | Definition |
|---|---|---|
| `opportunity.final_q` | `DecisionQualityModel.predict() + calibrate()` | Per-opportunity decision quality ∈ [0,1] |
| `player.final_score` | `review.py _build_player_score()` | Per-player, per-game 6-dim weighted score (0-100) |
| `player.process_score` | `review.py _build_player_score()` | Outcome-independent decision quality score (0-100) |
| `leaderboard.entry_score` | `LeaderboardAggregator` | Multi-game aggregate process score |

### Audit-only (not rubric-facing)

| Field | Source | Purpose |
|---|---|---|
| `raw_model_q` | `DecisionQualityModel.predict()` | Raw sklearn model output before calibration |
| `calibrated_q` | `calibrate_decision_quality()` | After soft rule-backed penalty adjustments |
| `learned_rank_q` | `PairwiseRanker.predict_rank()` | Pairwise preference signal (debug/audit only) |
| `process_score_v3` | `ProcessScoreV3` | Role-normalized cross-game comparison |
| `role_action_z` | `ProcessScoreV3` | Within-role-action z-score |
| `open_data_semantic_q` | Future `SpeechSemanticScorer` | Open-data-trained speech signal |
| `value_impact_q` | Future `ValueImpactHead` | Outcome-proxy value signal (auxiliary) |

### Rule

No new module shall create a new primary score without updating this contract.

---

## 2. Open Data Integration Policy

### Reconstruction Pipeline

```
Raw Open Dataset → DatasetAdapter → OpenGameLog → CanonicalGameEvent
  → DecisionOpportunity → Track B small dataset
```

### Required metadata

Every sample from open data MUST include:
- `source`: dataset name
- `license`: verified license
- `rule_variant`: original game rule set
- `visible_public_context`: public info at decision time
- `visible_private_context`: private info at decision time
- `weak_label_source`: how labels were derived
- `do_not_train_final_q_directly`: true

### Prohibited

- Generating `final_q` from open data
- Using post-game outcome as process quality label
- Silently dropping license/rule_variant metadata
- Training production models without human validation

### Promotion Gates

| Component | Gate |
|---|---|
| SpeechSemanticScorer | ≥50 human-reviewed samples, agreement ≥0.70 |
| VoteDecisionScorer | Reduces vote degeneracy, no strategic-bus false positives |
| PairwiseRanker (production) | ≥100 real replay pairs, heldout acc ≥0.70, human agreement measured |
| ValueImpactHead | Auxiliary only, never replaces process quality |

---

## 3. Role Model Policy

### Current stage: diagnostics only

- Role-specific calibration tables in reports
- No independent per-role models

### Minimum before training a standalone role model

- ≥300 labeled opportunities per role
- ≥50 critical / counterfactual examples per role
- ≥50 clean examples per role
- Human-reviewed validation set per role

### Recommended architecture (future)

```
SharedFeatureEncoder → RoleHeads (Seer/Witch/Guard/Hunter/Werewolf/Villager)
```

Not: six independent models.

### Role-specific output contract

Even before separate models, reports must include:
```json
{
  "role_breakdown": {
    "Seer": {"info_release_score": 0.72, "vote_alignment_score": 0.68},
    "Werewolf": {"deception_quality": 0.64, "night_target_quality": 0.70}
  }
}
```

---

## 4. B-Core Route

```
DecisionOpportunity → feature extraction → raw_model_q → calibrated_q → final_q
```

## 5. B-Review Route

```
final_q → CriticalDecision → CounterfactualCase → ImprovementSuggestion → StructuredReport
```

## 6. B-Leaderboard Route

```
multi-game process_score → role/action breakdown → low_sample_warning → leaderboard ranking
```

## 7. B-Data Route

```
open data → reconstruction → small datasets → audit heads → validated features → optional DQM integration
```

---

## 8. What Not To Do

- Do not add more synthetic badcase patches before open-data reconstruction
- Do not add another final score field
- Do not promote PairwiseRanker without human labels
- Do not train independent role models without sufficient role data
- Do not use outcome proxy as process quality
