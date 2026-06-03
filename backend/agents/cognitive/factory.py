"""Factory — creates CognitiveAgent instances with full production capabilities.

Supports:
- Character pool assignment (persona + mind traits)
- Strategy bias injection (A/B testing)
- DB-based profile loading
- LLM client wrapping with native function calling (bind_tools)
- Tool call parsing from OpenAI-compatible API responses

Single Responsibility: object construction.
No game logic, no LLM calls — pure wiring.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.profiles import Profile, get_profile, PersonaTraits, MindTraits

logger = logging.getLogger(__name__)


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
            client.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))
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


class _ToolCallingRunnable(Runnable):
    """LangChain Runnable wrapping an OpenAI-compatible client with native function calling.

    Supports bind_tools() → returns a new Runnable with tools attached.
    When invoked, sends tools as function definitions in the API payload
    and parses tool_calls from the response into AIMessage.tool_calls.
    """

    def __init__(self, client: Any, tool_schemas: List[Dict] | None = None):
        self._client = client
        self._tool_schemas = tool_schemas or []

    @property
    def provider(self) -> str:
        return str(getattr(self._client, "provider", "") or "")

    @property
    def model(self) -> str:
        return str(getattr(self._client, "model", "") or "")

    def bind_tools(self, tool_schemas: List[Dict]) -> "_ToolCallingRunnable":
        """Return a new Runnable with the given tools bound for function calling."""
        return _ToolCallingRunnable(self._client, tool_schemas)

    def invoke(self, messages: List[BaseMessage], config=None, **kwargs) -> AIMessage:
        """Invoke the LLM with optional function calling.

        When tool_schemas are bound, includes them as function definitions
        and parses tool_calls from the response into AIMessage.tool_calls.
        """
        # Convert LangChain messages to API dict format
        api_messages = []
        for msg in messages:
            role = _msg_role(msg)
            entry: Dict[str, Any] = {"role": role, "content": _msg_content(msg)}
            # Tool messages must include tool_call_id
            if role == "tool" and hasattr(msg, 'tool_call_id'):
                entry["tool_call_id"] = msg.tool_call_id
            # AIMessage may carry tool_calls from previous turns
            if role == "assistant" and hasattr(msg, 'tool_calls') and msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            api_messages.append(entry)

        # Build call parameters explicitly (avoid **payload issues with httpx serialization)
        max_tokens = kwargs.get("max_tokens", 1500)
        temperature = kwargs.get("temperature", 0.7)
        tools = self._tool_schemas if self._tool_schemas else None

        resp = self._client.chat_sync(
            messages=api_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            tool_choice="auto" if tools else None,
        )

        # Parse response
        if not isinstance(resp, dict):
            return AIMessage(content=str(resp))

        choice = resp.get("choices", [{}])[0]
        msg_data = choice.get("message", {})
        content = msg_data.get("content", "") or ""

        # Parse native tool_calls from API response
        raw_tool_calls = msg_data.get("tool_calls", [])
        tool_calls = []
        if raw_tool_calls:
            for tc in raw_tool_calls:
                tc_id = tc.get("id", f"call_{len(tool_calls)}")
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                fn_args = fn.get("arguments", "{}")
                if isinstance(fn_args, str):
                    try:
                        fn_args = json.loads(fn_args)
                    except json.JSONDecodeError:
                        fn_args = {}
                tool_calls.append({
                    "id": tc_id,
                    "name": fn_name,
                    "args": fn_args,
                })
            if tool_calls:
                logger.debug(
                    f"Native function calling: {len(tool_calls)} tool call(s) — "
                    f"{', '.join(tc['name'] for tc in tool_calls)}"
                )

        if tool_calls:
            return AIMessage(content=content, tool_calls=tool_calls)
        return AIMessage(content=content)


def _msg_role(msg: BaseMessage) -> str:
    """Map LangChain message type to API role string."""
    type_map = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}
    return type_map.get(msg.type, "user")


def _msg_content(msg: BaseMessage) -> str:
    """Extract content from a LangChain message, including tool_call_id for ToolMessages."""
    content = msg.content if hasattr(msg, 'content') else str(msg)
    if isinstance(content, list):
        # Handle multimodal content lists
        text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return " ".join(text_parts) if text_parts else str(content)
    return str(content) if content else ""


def create_llm_from_client(client: Any) -> _ToolCallingRunnable:
    """Wrap an LLM client into a LangChain Runnable with native function calling.

    The client must implement chat_sync(messages, max_tokens, ...) -> dict.
    The API must support OpenAI-compatible function calling (tools/tool_choice).
    """
    return _ToolCallingRunnable(client)


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
            wolf_deception_style="",
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
