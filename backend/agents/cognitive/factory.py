"""Factory — creates CognitiveAgent instances with full production capabilities.

Supports:
- Character pool assignment (persona + mind traits)
- Strategy bias injection (A/B testing)
- DB-based profile loading
- LLM client wrapping

Single Responsibility: object construction.
No game logic, no LLM calls — pure wiring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.runnables import Runnable, RunnableLambda

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.profiles import Profile, get_profile, PersonaTraits, MindTraits


def create_cognitive_agent(
    player_id: str,
    role: str,
    llm: Runnable = None,
    player_name: str = "",
    player_seat: int = 0,
    profile: Optional[Profile] = None,
    db_conn_str: str = "",
    strategy_bias: Optional[Dict[str, List[str]]] = None,
    persona: Optional[PersonaTraits] = None,
    mind: Optional[MindTraits] = None,
    *,
    llm_provider: str = "",
    llm_model: str = "",
) -> CognitiveAgent:
    """Create a production-grade CognitiveAgent.

    Args:
        player_id: Unique player identifier.
        role: Role string (e.g., "Seer", "Werewolf").
        llm: LangChain Runnable for LLM calls (primary path).
        player_name: Display name.
        player_seat: Seat number.
        profile: Optional custom profile (falls back to DB or hardcoded).
        db_conn_str: PostgreSQL connection string for loading profiles.
        strategy_bias: Forced policy rules for A/B testing. Dict of section → rules.
        persona: Optional persona traits (from Character pool).
        mind: Optional mind traits (from Character pool).
        llm_provider: Provider name string (e.g. "dsv4flash") — auto-creates client.
        llm_model: Model name when using llm_provider.

    Returns:
        Configured CognitiveAgent ready for game engine use.
    """
    # Resolve LLM: direct Runnable > provider string > error
    if llm is None:
        if llm_provider:
            from backend.llm import create_client
            client = create_client(provider=llm_provider, model=llm_model or None)
            client.timeout = 300.0
            llm = create_llm_from_client(client)
        else:
            raise ValueError(
                "create_cognitive_agent: must provide either llm (Runnable) "
                "or llm_provider (string)"
            )

    # Load profile from DB if not provided
    if profile is None:
        try:
            from backend.agents.cognitive.repository import load_profile_from_db
            profile = load_profile_from_db(role, db_conn_str)
        except Exception:
            profile = get_profile(role)

    # Override profile's persona/mind if provided externally (Character pool)
    if persona is not None:
        profile.persona = persona
    if mind is not None:
        profile.mind = mind

    return CognitiveAgent(
        player_id=player_id,
        role=role,
        llm=llm,
        player_name=player_name,
        player_seat=player_seat,
        profile=profile,
        strategy_bias=strategy_bias,
    )


def create_llm_from_client(client: Any) -> Runnable:
    """Wrap an LLM client into a LangChain Runnable.

    The client must implement chat_sync(messages, max_tokens) -> dict.
    """
    def invoke(messages):
        class Response:
            def __init__(self, content):
                self.content = content

        lc_messages = []
        for msg in messages:
            role = "user" if msg.type == "human" else "system"
            lc_messages.append({"role": role, "content": msg.content})

        resp = client.chat_sync(lc_messages, max_tokens=800)

        if isinstance(resp, dict):
            choices = resp.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
            else:
                content = str(resp)
        else:
            content = str(resp)

        return Response(content)

    return RunnableLambda(invoke)


def create_cognitive_agent_with_character(
    player_id: str,
    role: str,
    llm: Runnable,
    player_name: str = "",
    player_seat: int = 0,
    character: Any = None,  # Character from backend.agents.characters
    strategy_bias: Optional[Dict[str, List[str]]] = None,
) -> CognitiveAgent:
    """Create a CognitiveAgent from a full Character object.

    Bridges the existing Character system (Persona + PlayerMind + Role)
    into the CognitiveAgent's Profile system.

    Args:
        player_id: Unique player identifier.
        role: Role string.
        llm: LangChain Runnable.
        player_name: Display name.
        player_seat: Seat number.
        character: Character object from backend.agents.characters.
        strategy_bias: Optional forced policy rules.

    Returns:
        Configured CognitiveAgent.
    """
    profile = get_profile(role)

    if character is not None:
        p = character.persona
        m = character.mind
        profile.persona = PersonaTraits(
            name=p.name, mbti=p.mbti, gender=p.gender, age=p.age,
            basic_info=p.basic_info, style_label=p.style_label,
            vocabulary_style=p.vocabulary_style,
            speech_length_habit=p.speech_length_habit,
            reasoning_style=p.reasoning_style,
            social_habit=p.social_habit, humor_style=p.humor_style,
            pressure_style=p.pressure_style,
            uncertainty_style=p.uncertainty_style,
            wolf_deception_style=p.wolf_deception_style,
            mistake_pattern=p.mistake_pattern,
            werewolf_experience=p.werewolf_experience,
            trigger_topics=list(p.trigger_topics),
        )
        profile.mind = MindTraits(
            courage=m.courage, memory_bias=m.memory_bias,
            suspicion_threshold=m.suspicion_threshold,
            self_protection=m.self_protection,
            logic_depth=m.logic_depth, table_presence=m.table_presence,
        )

    return CognitiveAgent(
        player_id=player_id, role=role, llm=llm,
        player_name=player_name, player_seat=player_seat,
        profile=profile, strategy_bias=strategy_bias,
    )
