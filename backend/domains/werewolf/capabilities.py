from __future__ import annotations

from typing import Any

from backend.agent_harness import Skill
from backend.agent_harness import SkillRegistry
from backend.agent_harness import ToolGateway
from backend.agent_harness import ToolSpec
from backend.agent_harness.policy import CapabilityPolicy
from backend.agent_harness.tools import TrustedToolContext

EVIDENCE_TOOL = "werewolf.inspect_player_evidence"
EVIDENCE_SKILL = "werewolf.evidence_reasoning"

_ROLE_GUIDANCE = {
    "villager": "Build public cases from claims, vote consistency, and changes of stance. Avoid certainty without evidence.",
    "werewolf": "Maintain a plausible public worldview, coordinate only through legal private information, and avoid perspective leaks.",
    "whitewolfking": "Balance public credibility against the timing value of a legal self-detonation target.",
    "seer": "Track checks exactly, distinguish private certainty from public persuasion, and plan claim timing.",
    "witch": "Value limited medicine, separate public inference from private victim information, and avoid leaking night knowledge.",
    "hunter": "Preserve shot value, track credible suspects, and do not imply unavailable trigger information.",
    "guard": "Protect high-value village roles using only visible evidence and never reveal the actual protected target as fact.",
    "idiot": "Use public reasoning normally while accounting for the role's survival and voting constraints.",
}


def role_skill_name(role: str) -> str:
    return f"werewolf.role.{role.strip().lower()}"


def build_skill_registry() -> SkillRegistry:
    skills = [
        Skill(
            name=EVIDENCE_SKILL,
            description="Compare claims, commitments, contradictions, and source reliability before acting.",
            instructions=(
                "Separate observed facts from speaker claims and your own beliefs. Prefer multiple independent actor-visible "
                "signals. Treat role claims as claims, not truth. Cite the strongest evidence and one plausible alternative."
            ),
            environment_ids=frozenset({"werewolf"}),
            required_policy_tags=frozenset({"role-safe-view"}),
            priority=20,
        )
    ]
    for role, instructions in _ROLE_GUIDANCE.items():
        skills.append(
            Skill(
                name=role_skill_name(role),
                description=f"Role-specific strategic guidance for {role}.",
                instructions=instructions,
                environment_ids=frozenset({"werewolf"}),
                required_policy_tags=frozenset({"role-safe-view"}),
                priority=10,
            )
        )
    return SkillRegistry(skills)


def build_tool_gateway() -> ToolGateway:
    return ToolGateway(
        [
            ToolSpec(
                name=EVIDENCE_TOOL,
                description=(
                    "Inspect bounded beliefs, relationships, claims, and evidence edges about one player. "
                    "The result is derived only from the current actor's information state."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"player_id": {"type": "string"}},
                    "required": ["player_id"],
                    "additionalProperties": False,
                },
                handler=_inspect_player_evidence,
                capabilities=frozenset({"actor_information_state"}),
            )
        ]
    )


def build_capability_policy() -> CapabilityPolicy:
    return CapabilityPolicy(allowed_tools=frozenset({EVIDENCE_TOOL}))


def _inspect_player_evidence(context: TrustedToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    player_id = str(arguments.get("player_id") or "").strip()
    visible_players = {
        str(player.get("id") or "") for player in context.information_state.observation.get("players") or []
    }
    self_player = context.information_state.observation.get("self_player") or {}
    visible_players.add(str(self_player.get("id") or ""))
    if not player_id or player_id not in visible_players:
        raise ValueError("player_id must identify a player visible to the actor")

    memory = (context.information_state.private_memory or ({},))[0]
    belief = next(
        (item for item in memory.get("beliefs") or [] if str(item.get("player_id") or "") == player_id),
        {},
    )
    relationship = next(
        (item for item in memory.get("relationships") or [] if str(item.get("player_id") or "") == player_id),
        {},
    )
    claims = [
        item
        for item in memory.get("recent_claims") or []
        if player_id in {str(item.get("speaker_id") or ""), str(item.get("target_id") or "")}
    ][-8:]
    edges = [
        item
        for item in memory.get("evidence_graph") or []
        if player_id in {str(item.get("source_player_id") or ""), str(item.get("target_player_id") or "")}
    ][-8:]
    return {
        "player_id": player_id,
        "belief": belief,
        "relationship": relationship,
        "claims": claims,
        "evidence_edges": edges,
        "source": "actor_information_state",
    }
