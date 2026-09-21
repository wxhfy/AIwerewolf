from __future__ import annotations

from collections import Counter
from collections import defaultdict
from typing import Any

from backend.agent_harness.contracts import DecisionRequest

_UNIQUE_PUBLIC_ROLES = {"Seer", "Witch", "Guard", "Hunter", "Idiot", "WhiteWolfKing"}


def build_strategy_snapshot(request: DecisionRequest, memory: dict[str, Any]) -> dict[str, Any]:
    """Build an actor-scoped, explainable strategy view from subjective memory."""
    observation = request.information_state.observation
    actor_id = request.actor.actor_id
    players = {
        str(player.get("id") or ""): player
        for player in observation.get("players") or []
        if str(player.get("id") or "")
    }
    self_player = dict(observation.get("self_player") or {})
    if actor_id:
        players.setdefault(actor_id, self_player)

    beliefs = {str(item.get("player_id") or ""): item for item in memory.get("beliefs") or []}
    relationships = {str(item.get("player_id") or ""): item for item in memory.get("relationships") or []}
    claims = list(memory.get("recent_claims") or [])
    contradictions = Counter(
        str(claim.get("speaker_id") or "") for claim in claims if claim.get("kind") == "contradiction"
    )
    retractions = Counter(str(claim.get("speaker_id") or "") for claim in claims if claim.get("kind") == "retraction")

    role_claims: dict[str, list[str]] = defaultdict(list)
    for claim in claims:
        if claim.get("kind") != "role_claim" or claim.get("retracted"):
            continue
        speaker_id = str(claim.get("speaker_id") or "")
        role = str(claim.get("value") or "")
        if speaker_id and role and speaker_id not in role_claims[role]:
            role_claims[role].append(speaker_id)
    contested_roles = [
        {"role": role, "claimants": claimants}
        for role, claimants in sorted(role_claims.items())
        if role in _UNIQUE_PUBLIC_ROLES and len(claimants) > 1
    ]
    contested_claimants = {claimant for conflict in contested_roles for claimant in conflict["claimants"]}

    assessments: list[dict[str, Any]] = []
    for player_id, player in players.items():
        if player_id == actor_id or not bool(player.get("alive", True)):
            continue
        belief = beliefs.get(player_id) or {}
        relation = relationships.get(player_id) or {}
        probability = _number(belief, "wolf_probability", 0.5)
        confidence = _number(belief, "confidence", 0.0)
        trust = _number(relation, "trust", 0.0)
        threat = _number(relation, "threat", 0.0)
        influence = _number(relation, "influence", 0.0)
        contradiction_count = contradictions[player_id]
        contested_penalty = 0.08 if player_id in contested_claimants else 0.0
        suspicion = _clamp01(
            0.5
            + (probability - 0.5) * (0.7 + 0.3 * confidence)
            + min(0.18, contradiction_count * 0.07)
            + contested_penalty
            - trust * 0.06
        )
        protection = _clamp01(
            (1.0 - probability) * (0.35 + 0.45 * confidence) + max(0.0, influence) * 0.15 + max(0.0, trust) * 0.12
        )
        wolf_attack = _clamp01(
            (1.0 - probability) * 0.35 + max(0.0, influence) * 0.3 + max(0.0, threat) * 0.2 + confidence * 0.1
        )
        assessments.append(
            {
                "player_id": player_id,
                "name": str(player.get("name") or player_id),
                "wolf_probability": round(probability, 4),
                "confidence": round(confidence, 4),
                "suspicion_score": round(suspicion, 4),
                "protection_value": round(protection, 4),
                "wolf_attack_value": round(wolf_attack, 4),
                "contradictions": contradiction_count,
                "retractions": retractions[player_id],
                "claimed_roles": sorted(role for role, claimants in role_claims.items() if player_id in claimants),
                "evidence_for": list(belief.get("evidence_for") or [])[-3:],
                "evidence_against": list(belief.get("evidence_against") or [])[-2:],
            }
        )

    suspects = sorted(
        assessments,
        key=lambda item: (item["suspicion_score"], item["confidence"], item["player_id"]),
        reverse=True,
    )
    protect = sorted(
        assessments,
        key=lambda item: (item["protection_value"], item["confidence"], item["player_id"]),
        reverse=True,
    )
    attack = sorted(
        (item for item in assessments if not (item["wolf_probability"] >= 0.99 and item["confidence"] >= 0.99)),
        key=lambda item: (item["wolf_attack_value"], item["player_id"]),
        reverse=True,
    )
    return {
        "actor_role": str(request.domain_metadata.get("role") or self_player.get("role") or ""),
        "decision_kind": request.decision_point.kind,
        "suspect_ranking": suspects[:5],
        "protection_ranking": protect[:5],
        "wolf_attack_ranking": attack[:5],
        "role_claims": [{"role": role, "claimants": claimants} for role, claimants in sorted(role_claims.items())],
        "contested_roles": contested_roles,
        "decision_guidance": _decision_guidance(request.decision_point.kind),
        "provenance": "derived_only_from_actor_visible_memory",
    }


def strategy_score_for_option(
    request: DecisionRequest,
    memory: dict[str, Any],
    target_id: str | None,
) -> float:
    if not target_id:
        return 0.0
    snapshot = build_strategy_snapshot(request, memory)
    kind = request.decision_point.kind
    ranking_name = "suspect_ranking"
    score_name = "suspicion_score"
    if kind in {"werewolf.guard", "werewolf.transfer_badge"}:
        ranking_name = "protection_ranking"
        score_name = "protection_value"
    elif kind == "werewolf.wolf_team_vote":
        ranking_name = "wolf_attack_ranking"
        score_name = "wolf_attack_value"
    row = next(
        (item for item in snapshot[ranking_name] if item["player_id"] == target_id),
        None,
    )
    return float(row.get(score_name) or 0.0) if row else 0.0


def _decision_guidance(kind: str) -> list[str]:
    common = [
        "Separate confirmed private facts, public events, speaker claims, and uncertain inference.",
        "Prefer multiple independent signals; a role claim alone is not proof.",
    ]
    if kind in {"werewolf.talk", "werewolf.badge_speech", "werewolf.pk_speech", "werewolf.sheriff_closing"}:
        return common + [
            "State one primary read, cite concrete public evidence, and name one plausible alternative.",
            "Keep the public story consistent with prior commitments and the actor's information boundary.",
        ]
    if kind in {"werewolf.vote", "werewolf.divine", "werewolf.shoot", "werewolf.boom"}:
        return common + ["Compare the top candidates and select the option with the strongest explainable case."]
    if kind in {"werewolf.guard", "werewolf.transfer_badge"}:
        return common + [
            "Protect or transfer toward credible, influential village value without leaking private action."
        ]
    if kind == "werewolf.wolf_team_vote":
        return common + ["Target a credible, influential non-wolf while preserving a plausible public narrative."]
    if kind == "werewolf.witch":
        return common + ["Price potion scarcity and avoid acting only from weak social pressure."]
    return common


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _number(source: dict[str, Any], key: str, default: float) -> float:
    value = source.get(key)
    return default if value is None else float(value)
