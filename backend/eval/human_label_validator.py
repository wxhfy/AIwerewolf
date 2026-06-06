"""Human pairwise label validator — validates schema and content rules.

Used to validate real-replay human pairwise labels before ingestion.
"""

from __future__ import annotations

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
