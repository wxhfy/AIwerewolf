"""Human pairwise label validator — validates schema and content rules.

Used to validate real-replay human pairwise labels before ingestion.
"""

from __future__ import annotations

import math
from typing import Any

VALID_LABELS = {"A_BETTER", "B_BETTER", "TIE", "UNCERTAIN"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_ROLES = {"Werewolf", "WhiteWolfKing", "Seer", "Witch", "Guard", "Hunter", "Villager"}
VALID_ACTION_TYPES = {
    "speech",
    "vote",
    "werewolf_kill",
    "seer_check",
    "seer_release",
    "witch_save",
    "witch_poison",
    "guard_protect",
    "hunter_shot",
}


def validate_human_pairwise_label(label: dict[str, Any]) -> list[str]:
    """Validate a single human pairwise label. Returns list of errors (empty = valid)."""
    errors: list[str] = []

    # Required fields
    required = [
        "label_id",
        "game_id",
        "source",
        "role",
        "action_type",
        "label",
        "confidence",
        "reason",
        "option_a",
        "option_b",
        "visible_public_context",
        "visible_private_context",
    ]
    for field in required:
        if field not in label:
            errors.append(f"missing_required_field:{field}")

    if errors:
        return errors

    # Label validity
    if label["label"] not in VALID_LABELS:
        errors.append(f"invalid_label:{label['label']}")

    # Confidence validity
    if label["confidence"] not in VALID_CONFIDENCE:
        errors.append(f"invalid_confidence:{label['confidence']}")

    # Role validity
    if label["role"] not in VALID_ROLES:
        errors.append(f"invalid_role:{label['role']}")

    # Action type validity
    if label["action_type"] not in VALID_ACTION_TYPES:
        errors.append(f"invalid_action_type:{label['action_type']}")

    # Reason non-empty
    if not str(label.get("reason", "")).strip():
        errors.append("empty_reason")

    # Options exist
    for opt_key in ["option_a", "option_b"]:
        opt = label.get(opt_key, {})
        if not isinstance(opt, dict):
            errors.append(f"{opt_key}_not_dict")
        elif "action" not in opt:
            errors.append(f"{opt_key}_missing_action")
        elif "opportunity_id" not in opt:
            errors.append(f"{opt_key}_missing_opportunity_id")

    # Visible context exists
    for ctx_key in ["visible_public_context", "visible_private_context"]:
        if not label.get(ctx_key):
            errors.append(f"empty_{ctx_key}")

    # Future-info leak check (basic)
    reason = str(label.get("reason", "")).lower()
    future_kw = [
        "after the game",
        "we know now",
        "turned out to be",
        "ended up being",
        "post-game",
        "with hindsight",
        "最終結果",
        "賽後",
    ]
    for kw in future_kw:
        if kw in reason:
            errors.append(f"possible_future_info_leak:{kw}")

    return errors


def validate_human_pairwise_labels(labels: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a batch of human pairwise labels."""
    results = {"total": len(labels), "valid": 0, "invalid": 0, "errors_by_label": {}}
    for label in labels:
        errs = validate_human_pairwise_label(label)
        if errs:
            results["invalid"] += 1
            results["errors_by_label"][label.get("label_id", "unknown")] = errs
        else:
            results["valid"] += 1
    return results


def validate_judge_calibration_dataset(dataset: Any) -> list[str]:
    """Validate scalar, role-visible human labels before a Judge sees any sample.

    Scores are normalized to [0, 1]. Train/validation split is explicit and
    grouped by game, so nearby decisions from one game cannot contaminate the
    held-out agreement measurements. Synthetic provenance is always explicit.
    """
    if not isinstance(dataset, dict):
        return ["dataset_not_object"]
    errors: list[str] = []
    if not str(dataset.get("dataset_id", "")).strip():
        errors.append("missing_dataset_id")
    if not isinstance(dataset.get("synthetic"), bool):
        errors.append("synthetic_must_be_explicit_boolean")
    if dataset.get("annotation_source") not in {"human", "synthetic"}:
        errors.append("invalid_annotation_source")
    if dataset.get("synthetic") is False and dataset.get("annotation_source") != "human":
        errors.append("real_dataset_requires_human_source")
    samples = dataset.get("samples")
    if not isinstance(samples, list) or not samples:
        return errors + ["samples_must_be_nonempty_list"]
    ids: set[str] = set()
    game_splits: dict[str, str] = {}
    for index, sample in enumerate(samples):
        prefix = f"sample[{index}]"
        if not isinstance(sample, dict):
            errors.append(f"{prefix}:not_object")
            continue
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id.strip():
            errors.append(f"{prefix}:missing_sample_id")
        elif sample_id in ids:
            errors.append(f"{prefix}:duplicate_sample_id")
        else:
            ids.add(sample_id)
        game_id = sample.get("game_id")
        split = sample.get("split")
        if not isinstance(game_id, str) or not game_id.strip():
            errors.append(f"{prefix}:missing_game_id")
        elif game_id in game_splits and game_splits[game_id] != split:
            errors.append(f"{prefix}:game_crosses_splits")
        else:
            game_splits[game_id] = split
        if split not in {"train", "validation"}:
            errors.append(f"{prefix}:invalid_split")
        if not isinstance(sample.get("annotator_id"), str) or not sample["annotator_id"].strip():
            errors.append(f"{prefix}:missing_annotator_id")
        if sample.get("confidence") not in VALID_CONFIDENCE:
            errors.append(f"{prefix}:invalid_confidence")
        value = sample.get("human_score")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            errors.append(f"{prefix}:human_score_out_of_range")
        decision = sample.get("decision")
        if not isinstance(decision, dict):
            errors.append(f"{prefix}:invalid_decision")
        elif not isinstance(decision.get("raw_text"), str) or not decision.get("action_type"):
            errors.append(f"{prefix}:decision_requires_action_and_text")
        context = sample.get("visible_context")
        if not isinstance(context, dict) or not isinstance(context.get("visible_info"), str):
            errors.append(f"{prefix}:missing_visible_context")
    return errors
