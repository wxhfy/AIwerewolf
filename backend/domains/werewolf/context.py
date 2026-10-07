from __future__ import annotations

from typing import Any

from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import PlannerContext
from backend.domains.werewolf.strategy import build_strategy_snapshot


def build_decision_context_v1(
    request: DecisionRequest,
    planner_context: PlannerContext,
    limits: dict[str, int],
) -> dict[str, Any]:
    """Build one compact, provenance-safe context for a model decision."""
    observation = request.information_state.observation
    memory = (request.information_state.private_memory or ({},))[0]
    players = list(observation.get("players") or [])
    names = {
        str(player.get("id") or ""): str(player.get("name") or player.get("id") or "")
        for player in players
        if player.get("id")
    }
    self_player = dict(observation.get("self_player") or {})
    actor_id = request.actor.actor_id
    names.setdefault(actor_id, str(self_player.get("name") or actor_id))
    ordered_history = sorted(
        request.information_state.visible_history,
        key=lambda event: int(event.get("seq") or 0),
    )
    public_events = [event for event in ordered_history if str(event.get("visibility") or "public") != "private"]
    private_events = [event for event in ordered_history if str(event.get("visibility") or "") == "private"]
    timeline = [
        item
        for item in (_public_event(event, names) for event in public_events[-limits["public_timeline"] :])
        if item is not None
    ]
    strategy = build_strategy_snapshot(request, memory)
    claims = _public_claims(memory, names, limits["public_claims"])
    inferences = _inferences(strategy, memory, names, limits["inferences"])
    agent_state = _agent_state(memory, names, actor_id, claims, limits, public_events=public_events)
    external_knowledge = [
        {
            "source": str(item.get("source") or "retrieval"),
            "version": str(item.get("version") or ""),
            "content": item.get("content"),
            "epistemic_status": "cross_episode_advice_not_current_game_fact",
        }
        for item in list(request.knowledge_context)[: limits["external_knowledge"]]
    ]
    return {
        "schema": "werewolf.decision_context.v1",
        "epistemic_contract": {
            "confirmed_private_facts": "Direct actor knowledge. Trust it, but disclose only when strategy allows.",
            "public_timeline": "Public observations. Speech records what was said, not whether it was true.",
            "public_claims": "Unverified attributed claims. Another speaker's claim is never your own knowledge.",
            "inferences": "Fallible actor-local estimates derived from visible evidence. They are not facts.",
            "external_knowledge": "General cross-episode advice. It cannot establish facts about this match.",
        },
        "identity": {
            "actor_id": actor_id,
            "name": names.get(actor_id, actor_id),
            "seat": self_player.get("seat"),
            "role": request.domain_metadata.get("role") or self_player.get("role"),
            "alignment": request.domain_metadata.get("alignment") or self_player.get("alignment"),
            "agent_definition_id": request.actor.agent_definition_id,
        },
        "game_contract": {
            "player_count": request.domain_metadata.get("player_count") or len(players),
            "role_configuration": dict(request.domain_metadata.get("role_configuration") or {}),
            "role_assignment_visibility": "Role configuration is public; individual assignments are hidden unless publicly claimed or revealed.",
            "claim_semantics": "A role or action claim may be truthful, mistaken, or deceptive. Treat it as attributed speech until independently confirmed.",
        },
        "situation": {
            "day": observation.get("day", request.domain_metadata.get("day")),
            "phase": observation.get("phase", request.domain_metadata.get("phase")),
            "decision_kind": request.decision_point.kind,
            "sequence": request.decision_point.sequence,
            "roster": [_public_player(player) for player in players],
        },
        "confirmed_private_facts": _private_facts(
            request,
            private_events,
            memory,
            names,
            limits["private_facts"],
        ),
        "public_timeline": timeline,
        "public_claims": claims,
        "inferences": inferences,
        "agent_state": agent_state,
        "external_knowledge": external_knowledge,
        "current_task": {
            "decision_frame": _decision_frame(request),
            "guidance": list(strategy.get("decision_guidance") or []),
            "prior_reflections": list(planner_context.reflections)[-2:],
            "remaining_ms": planner_context.remaining_ms,
            "remaining_steps_including_current": max(0, request.budget.max_steps - planner_context.step + 1),
            "conversation_constraint": {
                "respond_to_new_evidence": True,
                "avoid_repeating_recent_public_speech": True,
            },
        },
    }


def project_agent_profile_v1(profile: dict[str, Any]) -> dict[str, Any]:
    """Expose stable traits and soft behavioral preferences to the planner."""
    persona = dict(profile.get("persona") or {})
    fields = (
        "name",
        "mbti",
        "gender",
        "age",
        "style_label",
        "basic_info",
        "voice_rules",
        "reasoning_style",
        "logic_style",
        "speech_length_habit",
        "vocabulary_style",
        "social_habit",
        "humor_style",
        "pressure_style",
        "uncertainty_style",
        "mistake_pattern",
        "courage",
        "memory_bias",
        "suspicion_threshold",
        "self_protection",
        "logic_depth",
        "table_presence",
        "trigger_topics",
        "werewolf_experience",
    )
    projected: dict[str, Any] = {}
    for field in fields:
        value = persona.get(field)
        if not value:
            continue
        if isinstance(value, str):
            projected[field] = str(value).strip()[:180]
        elif isinstance(value, list):
            projected[field] = [str(item).strip()[:100] for item in value[:6] if str(item).strip()]
        else:
            projected[field] = value
    return {
        "persona": projected,
        "behavior": _profile_behavior_v1(projected),
    }


def _profile_behavior_v1(persona: dict[str, Any]) -> dict[str, Any]:
    """Translate descriptive profile fields into soft, auditable tendencies."""
    courage = str(persona.get("courage") or "calculated").lower()
    memory_bias = str(persona.get("memory_bias") or "comprehensive").lower()
    suspicion = str(persona.get("suspicion_threshold") or "medium").lower()
    protection = str(persona.get("self_protection") or "passive").lower()
    depth = str(persona.get("logic_depth") or "moderate").lower()
    length = str(persona.get("speech_length_habit") or "").lower()
    social = str(persona.get("social_habit") or "").lower()
    reasoning = str(persona.get("reasoning_style") or "").lower()
    logic = str(persona.get("logic_style") or "").lower()
    return {
        "cognitive_bias": {
            "recent_event_weight": 0.8 if memory_bias == "recent" else 0.45,
            "first_impression_weight": 0.8 if memory_bias == "first_impression" else 0.35,
            "contradiction_sensitivity": 0.85
            if any(token in reasoning + logic for token in ("矛盾", "证据", "对比", "核对", "排除"))
            else 0.5,
            "emotion_weight": 0.8
            if any(token in reasoning + logic for token in ("情绪", "感觉", "氛围", "动机"))
            else 0.35,
            "authority_follow_weight": 0.7
            if any(token in social for token in ("跟随", "协调", "共识", "保护"))
            else 0.25,
        },
        "decision_style": {
            "risk_tolerance": {"bold": 0.8, "calculated": 0.55, "cautious": 0.25}.get(courage, 0.55),
            "suspicion_threshold": {"low": 0.3, "medium": 0.55, "high": 0.75}.get(suspicion, 0.55),
            "self_defense_intensity": {"aggressive": 0.8, "passive": 0.45, "sacrificial": 0.25}.get(protection, 0.45),
            "reasoning_depth": {"shallow": 0.3, "moderate": 0.55, "deep": 0.85}.get(depth, 0.55),
            "vote_switch_threshold": 0.75 if courage == "cautious" else 0.58,
        },
        "conversation_style": {
            "preferred_sentence_count": 2
            if any(token in length for token in ("短", "简洁", "极短"))
            else 5
            if "长" in length or "故事" in length
            else 3,
            "challenge_frequency": 0.75
            if any(token in social + logic for token in ("辩论", "挑战", "拆", "反击"))
            else 0.35,
            "question_frequency": 0.7
            if any(token in social + reasoning for token in ("提问", "倾听", "询问"))
            else 0.3,
            "must_reference_recent_evidence": True,
            "trigger_topics": list(persona.get("trigger_topics") or [])[:6],
            "known_mistake_pattern": str(persona.get("mistake_pattern") or "")[:180],
        },
    }


def _decision_frame(request: DecisionRequest) -> dict[str, Any]:
    kind = request.decision_point.kind
    common = {
        "freedom": [
            "You may bluff, hedge, pressure, retract, or change your public stance when strategically justified.",
            "Claims are actions in the social game; they do not have to reveal your true private state.",
        ],
        "discipline": [
            "Keep confirmed facts, attributed claims, and your own inferences distinct.",
            "Prefer a coherent stance supported by one or two relevant observations over listing the whole context.",
        ],
    }
    if kind in {"werewolf.talk", "werewolf.badge_speech", "werewolf.pk_speech", "werewolf.sheriff_closing", "werewolf.last_words"}:
        if kind == "werewolf.last_words":
            return {
                **common,
                "objective": "Leave a final, useful public record before elimination: clarify your strongest read, unresolved claim, or actionable clue.",
                "conversation_moves": [
                    "state the most important evidence other players should revisit",
                    "separate confidence from uncertainty and identify what could prove you wrong",
                    "make a final recommendation only when it follows from visible or confirmed evidence",
                ],
                "avoid": [
                    "starting a routine introduction",
                    "repeating the entire day's discussion",
                    "revealing private facts that the role has not publicly claimed",
                ],
            }
        return {
            **common,
            "objective": "Advance your current social strategy with a concise, natural public statement.",
            "conversation_moves": [
                "respond to a relevant new claim, accusation, vote, or question",
                "maintain or revise an earlier read and give the reason when useful",
                "ask, hedge, challenge, ally, disclose, or commit when it fits the moment",
            ],
            "avoid": [
                "treating these moves as a required template",
                "mechanically summarizing every player",
                "repeating your previous speech without new evidence",
            ],
        }
    if kind in {"werewolf.vote", "werewolf.badge_election"}:
        return {
            **common,
            "objective": "Choose the legal target that best advances your current alignment and public strategy.",
            "suggested_structure": [
                "compare the strongest candidate reads",
                "check consistency with your prior public stance",
                "choose one legal option and explain the decisive evidence",
            ],
        }
    if kind in {"werewolf.divine", "werewolf.guard", "werewolf.witch", "werewolf.shoot", "werewolf.boom"}:
        return {
            **common,
            "objective": "Use the role action to maximize expected strategic value under uncertainty.",
            "suggested_structure": [
                "separate confirmed private knowledge from public claims",
                "compare information gain, survival value, and downside risk",
                "choose one legal option without inventing facts",
            ],
        }
    return {
        **common,
        "objective": "Choose one legal action that advances the actor's current strategy.",
    }


def _public_player(player: dict[str, Any]) -> dict[str, Any]:
    result = {key: player.get(key) for key in ("id", "seat", "name", "alive") if player.get(key) is not None}
    persona = dict(player.get("persona") or {})
    if persona.get("style_label"):
        result["public_style"] = persona["style_label"]
    return result


def _private_facts(
    request: DecisionRequest,
    private_events: list[dict[str, Any]],
    memory: dict[str, Any],
    names: dict[str, str],
    limit: int,
) -> list[dict[str, Any]]:
    actor_id = request.actor.actor_id
    facts: list[dict[str, Any]] = [
        {
            "kind": "self_role",
            "subject_id": actor_id,
            "subject_name": names.get(actor_id, actor_id),
            "role": request.domain_metadata.get("role"),
            "alignment": request.domain_metadata.get("alignment"),
            "certainty": "confirmed",
            "disclosure": "private_unless_strategically_claimed",
        }
    ]
    teammates = [
        {
            "id": str(player.get("id") or ""),
            "name": str(player.get("name") or player.get("id") or ""),
        }
        for player in request.information_state.observation.get("known_wolves") or []
        if str(player.get("id") or "") != actor_id
    ]
    if teammates:
        facts.append(
            {
                "kind": "known_wolf_teammates",
                "players": teammates,
                "certainty": "confirmed",
                "disclosure": "never_reveal_as_private_knowledge",
            }
        )

    event_facts: list[dict[str, Any]] = []
    seen_sequences: set[int] = set()
    for event in private_events:
        payload = dict(event.get("payload") or {})
        kind = str(payload.get("kind") or "")
        if kind == "role_assignment":
            continue
        fact: dict[str, Any] = {
            "kind": kind or str(event.get("type") or "private_event").lower(),
            "seq": event.get("seq"),
            "day": event.get("day"),
            "certainty": "confirmed",
            "disclosure": "private",
        }
        target_id = str(payload.get("target_id") or "")
        if target_id:
            fact["target_id"] = target_id
            fact["target_name"] = str(payload.get("target_name") or names.get(target_id) or target_id)
        if kind == "seer_result":
            fact["result"] = "wolf" if bool(payload.get("is_wolf")) else "not_wolf"
        elif payload.get("message"):
            fact["summary"] = str(payload["message"])[:240]
        event_facts.append(fact)
        seen_sequences.add(int(event.get("seq") or 0))
    for item in memory.get("confirmed_private_facts") or []:
        sequence = int(item.get("event_seq") or 0)
        if sequence in seen_sequences:
            continue
        tags = [str(tag) for tag in item.get("tags") or []]
        semantic_kind = next((tag for tag in reversed(tags) if tag != "private"), "private_memory_fact")
        event_facts.append(
            {
                "kind": semantic_kind,
                "seq": sequence,
                "day": item.get("day"),
                "summary": str(item.get("summary") or "")[:240],
                "certainty": "confirmed",
                "disclosure": "private",
            }
        )
    event_facts.sort(key=lambda item: int(item.get("seq") or 0))
    facts.extend(event_facts[-limit:])
    return facts


def _public_event(event: dict[str, Any], names: dict[str, str]) -> dict[str, Any] | None:
    payload = dict(event.get("payload") or {})
    event_type = str(event.get("type") or "")
    base = {"seq": event.get("seq"), "day": event.get("day"), "type": event_type}
    if event_type == "CHAT_MESSAGE":
        actor_id = str(payload.get("actor_id") or payload.get("speaker_id") or "")
        return {
            **base,
            "speaker_id": actor_id,
            "speaker_name": str(
                payload.get("actor_name") or payload.get("speaker_name") or names.get(actor_id) or actor_id
            ),
            "speech": str(payload.get("speech") or payload.get("message") or "")[:600],
            "truth_status": "unverified_speech",
        }
    if event_type == "VOTE_CAST":
        voter_id = str(payload.get("voter_id") or "")
        target_id = str(payload.get("target_id") or "")
        return {
            **base,
            "voter_id": voter_id,
            "voter_name": str(payload.get("voter_name") or names.get(voter_id) or voter_id),
            "target_id": target_id,
            "target_name": str(payload.get("target_name") or names.get(target_id) or target_id),
        }
    if event_type == "PLAYER_DIED":
        player_id = str(payload.get("player_id") or "")
        return {
            **base,
            "player_id": player_id,
            "player_name": str(payload.get("player_name") or names.get(player_id) or player_id),
            "reason": payload.get("reason"),
        }
    if event_type in {"HUNTER_SHOT", "WHITE_WOLF_KING_BOOM", "GAME_END"}:
        return {**base, "summary": str(payload.get("message") or payload)[:300]}
    return None


def _public_claims(memory: dict[str, Any], names: dict[str, str], limit: int) -> list[dict[str, Any]]:
    useful_kinds = {"role_claim", "check_claim", "stance", "vote_commitment", "contradiction", "retraction"}
    claims = [claim for claim in memory.get("recent_claims") or [] if claim.get("kind") in useful_kinds]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for claim in reversed(claims):
        claim_id = str(claim.get("claim_id") or "")
        if claim_id and claim_id in seen:
            continue
        seen.add(claim_id)
        speaker_id = str(claim.get("speaker_id") or "")
        target_id = str(claim.get("target_id") or "")
        result.append(
            {
                "seq": claim.get("event_seq"),
                "speaker_id": speaker_id,
                "speaker_name": names.get(speaker_id, speaker_id),
                "claim_type": claim.get("kind"),
                "target_id": target_id or None,
                "target_name": names.get(target_id, target_id) if target_id else None,
                "value": claim.get("value"),
                "confidence": _confidence_level(claim.get("confidence")),
                "evidence_excerpt": str(claim.get("evidence_text") or "")[:240],
                "claim_id": claim_id or None,
                "status": "retracted"
                if claim.get("retracted")
                else "contradicted"
                if claim.get("contradicted")
                else "unverified",
                "epistemic_status": "speaker_claim_not_actor_fact",
            }
        )
        if len(result) >= limit:
            break
    return list(reversed(result))


def _inferences(
    strategy: dict[str, Any],
    memory: dict[str, Any],
    names: dict[str, str],
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for rank, item in enumerate(list(strategy.get("suspect_ranking") or [])[:limit], start=1):
        suspicion = float(item.get("suspicion_score") or 0.5)
        confidence = float(item.get("confidence") or 0.0)
        result.append(
            {
                "rank": rank,
                "player_id": item.get("player_id"),
                "name": item.get("name"),
                "read": "wolf_lean" if suspicion >= 0.6 else "village_lean" if suspicion <= 0.4 else "uncertain",
                "confidence": "high" if confidence >= 0.7 else "medium" if confidence >= 0.35 else "low",
                "public_contradictions": int(item.get("contradictions") or 0),
                "claimed_roles": list(item.get("claimed_roles") or []),
                "supporting_evidence": _claim_evidence(memory, names, str(item.get("player_id") or ""), 1.0),
                "counter_evidence": _claim_evidence(memory, names, str(item.get("player_id") or ""), -1.0),
                "epistemic_status": "fallible_actor_inference",
            }
        )
    return result


def _claim_evidence(
    memory: dict[str, Any],
    names: dict[str, str],
    player_id: str,
    polarity_sign: float,
) -> list[dict[str, Any]]:
    matching: list[dict[str, Any]] = []
    for claim in memory.get("recent_claims") or []:
        if str(claim.get("target_id") or "") != player_id:
            continue
        polarity = float(claim.get("polarity") or 0.0)
        if polarity * polarity_sign <= 0:
            continue
        speaker_id = str(claim.get("speaker_id") or "")
        matching.append(
            {
                "event_seq": claim.get("event_seq"),
                "claim_id": claim.get("claim_id"),
                "speaker_name": names.get(speaker_id, speaker_id),
                "claim_type": claim.get("kind"),
                "value": claim.get("value"),
                "excerpt": str(claim.get("evidence_text") or "")[:200],
                "status": "retracted"
                if claim.get("retracted")
                else "contradicted"
                if claim.get("contradicted")
                else "unverified",
                "epistemic_status": "attributed_claim_not_confirmed_fact",
            }
        )
    return matching[-2:]


def _agent_state(
    memory: dict[str, Any],
    names: dict[str, str],
    actor_id: str,
    claims: list[dict[str, Any]],
    limits: dict[str, int],
    *,
    public_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    affect = dict(memory.get("affect") or {})
    relationships = sorted(
        (
            dict(item)
            for item in memory.get("relationships") or []
            if max(
                abs(float(item.get("trust") or 0.0)),
                abs(float(item.get("closeness") or 0.0)),
                float(item.get("threat") or 0.0),
                abs(float(item.get("influence") or 0.0)),
                abs(float(item.get("perceived_attitude") or 0.0)),
            )
            >= 0.15
        ),
        key=lambda item: (
            max(
                abs(float(item.get("trust") or 0.0)),
                abs(float(item.get("closeness") or 0.0)),
                float(item.get("threat") or 0.0),
                abs(float(item.get("influence") or 0.0)),
                abs(float(item.get("perceived_attitude") or 0.0)),
            ),
            int(item.get("last_updated_seq") or 0),
        ),
        reverse=True,
    )
    social_reads = [
        {
            "player_id": str(item.get("player_id") or ""),
            "player_name": names.get(str(item.get("player_id") or ""), str(item.get("player_id") or "")),
            "trust": _level(item.get("trust")),
            "threat": _level(item.get("threat")),
            "influence": _level(abs(float(item.get("influence") or 0.0))),
            "attitude": _attitude(item.get("perceived_attitude")),
            "updated_after_seq": item.get("last_updated_seq"),
            "epistemic_status": "subjective_actor_memory",
        }
        for item in relationships[: limits.get("social_reads", 4)]
        if str(item.get("player_id") or "") != actor_id
    ]
    recalled_episodes = [
        {
            "event_id": str(item.get("memory_id") or ""),
            "event_seq": item.get("event_seq"),
            "day": item.get("day"),
            "phase": item.get("phase"),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "summary": str(item.get("content") or "")[:280],
            "actors": [names.get(str(actor), str(actor)) for actor in item.get("actor_ids") or []],
            "epistemic_status": "actor_memory_of_visible_or_self_event",
        }
        for item in list(memory.get("retrieved_episodes") or [])[: limits.get("retrieved_episodes", 3)]
    ]
    own_positions = [item for item in claims if str(item.get("speaker_id") or "") == actor_id][-3:]
    last_action = dict(memory.get("last_action") or {})
    recent_public_speeches = [
        {
            "event_seq": event.get("seq"),
            "day": event.get("day"),
            "phase": event.get("phase"),
            "speech": str((event.get("payload") or {}).get("speech") or "")[:400],
        }
        for event in reversed(public_events or [])
        if str(event.get("type") or "") == "CHAT_MESSAGE"
        and str((event.get("payload") or {}).get("actor_id") or "") == actor_id
        and str((event.get("payload") or {}).get("speech") or "").strip()
    ][:2]
    recent_public_speeches.reverse()
    return {
        "active_goals": [
            str(goal.get("description") or "") for goal in memory.get("active_goals") or [] if goal.get("description")
        ][:3],
        "attention_focus": [
            str(item)[:240] for item in list(memory.get("working_memory") or [])[: limits.get("working_memory", 4)]
        ],
        "recalled_episodes": recalled_episodes,
        "social_reads": social_reads,
        "affect": {
            "confidence": _level(affect.get("confidence")),
            "social_pressure": _level(affect.get("social_pressure")),
            "fear": _level(affect.get("fear")),
            "anger": _level(affect.get("anger")),
            "arousal": _level(affect.get("arousal")),
            "valence": _valence(affect.get("valence")),
        },
        "own_recent_positions": own_positions,
        "recent_public_speeches": recent_public_speeches,
        "social_pressure": _level(affect.get("social_pressure")),
        "confidence": _level(affect.get("confidence")),
        "last_action": {
            key: last_action[key]
            for key in ("sequence", "day", "phase", "action_type", "target_id", "response")
            if key in last_action
        },
    }


def _level(value: Any) -> str:
    number = float(value or 0.0)
    if number >= 0.7:
        return "high"
    if number >= 0.35:
        return "medium"
    return "low"


def _confidence_level(value: Any) -> str:
    number = float(value or 0.0)
    if number >= 0.75:
        return "high"
    if number >= 0.45:
        return "medium"
    return "low"


def _attitude(value: Any) -> str:
    number = float(value or 0.0)
    if number >= 0.3:
        return "warm"
    if number <= -0.3:
        return "guarded"
    return "neutral"


def _valence(value: Any) -> str:
    number = float(value or 0.0)
    if number >= 0.3:
        return "positive"
    if number <= -0.3:
        return "negative"
    return "neutral"
