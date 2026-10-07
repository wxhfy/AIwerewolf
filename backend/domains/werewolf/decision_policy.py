from __future__ import annotations

from typing import Any

from backend.agent_harness.contracts import ActionOption
from backend.agent_harness.contracts import ActionSelection
from backend.agent_harness.contracts import DecisionRequest
from backend.domains.werewolf.strategy import strategy_score_for_option


def apply_role_policy(request: DecisionRequest, selection: ActionSelection) -> ActionSelection:
    """Override only decisions that contradict actor-confirmed role knowledge."""
    selected = _option(request, selection.option_id)
    if selected is None:
        return selection

    replacement: ActionOption | None = None
    reason = ""
    kind = request.decision_point.kind
    role = str(request.domain_metadata.get("role") or "")
    target_id = _target(selected)

    if kind == "werewolf.witch":
        replacement, reason = _witch_self_save(request, selected)
    elif kind == "werewolf.vote" and role in {"Werewolf", "WhiteWolfKing"}:
        replacement, reason = _avoid_wolf_teammate_vote(request, target_id)
    elif role == "Seer" and kind in {"werewolf.vote", "werewolf.divine"}:
        replacement, reason = _respect_seer_results(request, kind, target_id)
    elif role == "Hunter" and kind == "werewolf.shoot":
        replacement, reason = _protect_credible_gold_seer(request, target_id)

    if replacement is None or replacement.option_id == selection.option_id:
        return selection
    return ActionSelection(
        option_id=replacement.option_id,
        response={},
        reasoning=f"Role policy override: {reason}",
        metadata={
            **selection.metadata,
            "policy_overridden": True,
            "policy_original_option_id": selection.option_id,
            "policy_reason": reason,
        },
    )


def _witch_self_save(request: DecisionRequest, selected: ActionOption) -> tuple[ActionOption | None, str]:
    if selected.action_type in {"witch_save", "witch_save_and_poison"}:
        return None, ""
    actor_id = request.actor.actor_id
    save = next(
        (
            option
            for option in request.action_space.options
            if option.action_type == "witch_save" and str(option.parameters.get("target_id") or "") == actor_id
        ),
        None,
    )
    if save is None:
        return None, ""
    return save, "witch_was_the_confirmed_night_victim_and_antidote_was_available"


def _avoid_wolf_teammate_vote(
    request: DecisionRequest,
    target_id: str | None,
) -> tuple[ActionOption | None, str]:
    known_wolves = {
        str(player.get("id") or "") for player in request.information_state.observation.get("known_wolves") or []
    }
    if not target_id or target_id not in known_wolves:
        return None, ""
    candidates = [
        option for option in request.action_space.options if _target(option) and _target(option) not in known_wolves
    ]
    return _best(request, candidates), "public_vote_targeted_a_confirmed_wolf_teammate"


def _respect_seer_results(
    request: DecisionRequest,
    kind: str,
    target_id: str | None,
) -> tuple[ActionOption | None, str]:
    results = _confirmed_seer_results(request)
    if not target_id or target_id not in results:
        return None, ""
    if kind == "werewolf.vote" and results[target_id] is False:
        candidates = [
            option
            for option in request.action_space.options
            if _target(option) not in results or results[_target(option)]
        ]
        return _best(request, candidates), "seer_vote_targeted_a_privately_confirmed_non_wolf"
    if kind == "werewolf.divine":
        candidates = [option for option in request.action_space.options if _target(option) not in results]
        return _best(request, candidates), "seer_attempted_to_repeat_a_completed_check"
    return None, ""


def _protect_credible_gold_seer(
    request: DecisionRequest,
    target_id: str | None,
) -> tuple[ActionOption | None, str]:
    protected = _credible_seers_who_cleared_actor(request)
    if not target_id or target_id not in protected:
        return None, ""
    candidates = [option for option in request.action_space.options if _target(option) not in protected]
    return _best(request, candidates), "hunter_shot_targeted_the_uncontested_seer_who_publicly_cleared_hunter"


def _confirmed_seer_results(request: DecisionRequest) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for event in request.information_state.visible_history:
        payload = dict(event.get("payload") or {})
        if event.get("type") == "PRIVATE_INFO" and payload.get("kind") == "seer_result":
            target_id = str(payload.get("target_id") or "")
            if target_id:
                results[target_id] = bool(payload.get("is_wolf"))
    memory = (request.information_state.private_memory or ({},))[0]
    for fact in memory.get("confirmed_private_facts") or []:
        tags = {str(tag) for tag in fact.get("tags") or []}
        if "seer_result" not in tags:
            continue
        actor_ids = [str(item) for item in fact.get("actor_ids") or [] if item]
        if not actor_ids:
            continue
        summary = str(fact.get("summary") or "").lower()
        results[actor_ids[-1]] = "not wolf" not in summary and "好人" not in summary and "非狼" not in summary
    return results


def _credible_seers_who_cleared_actor(request: DecisionRequest) -> set[str]:
    memory = (request.information_state.private_memory or ({},))[0]
    claims = [
        claim
        for claim in memory.get("recent_claims") or []
        if not claim.get("retracted") and not claim.get("contradicted")
    ]
    seers = {
        str(claim.get("speaker_id") or "")
        for claim in claims
        if claim.get("kind") == "role_claim" and claim.get("value") == "Seer"
    }
    if len(seers) != 1:
        return set()
    actor_id = request.actor.actor_id
    cleared_by = {
        str(claim.get("speaker_id") or "")
        for claim in claims
        if claim.get("kind") == "check_claim"
        and str(claim.get("target_id") or "") == actor_id
        and claim.get("value") == "village"
    }
    return seers & cleared_by


def _best(request: DecisionRequest, options: list[ActionOption]) -> ActionOption | None:
    if not options:
        return None
    memory: dict[str, Any] = (request.information_state.private_memory or ({},))[0]
    return max(
        options,
        key=lambda option: (
            strategy_score_for_option(request, memory, _target(option)),
            option.option_id,
        ),
    )


def _option(request: DecisionRequest, option_id: str) -> ActionOption | None:
    return next((option for option in request.action_space.options if option.option_id == option_id), None)


def _target(option: ActionOption) -> str | None:
    value = option.parameters.get("target_id") or option.parameters.get("poison_target_id")
    return str(value) if value else None
