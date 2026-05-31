"""Factory — creates CognitiveAgent instances.

Single Responsibility: object construction.
No game logic, no LLM calls — pure wiring.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.runnables import Runnable, RunnableLambda

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.profiles import Profile, get_profile


def create_cognitive_agent(
    player_id: str,
    role: str,
    llm: Runnable,
    player_name: str = "",
    player_seat: int = 0,
    profile: Optional[Profile] = None,
) -> CognitiveAgent:
    """Create a CognitiveAgent.

    Args:
        player_id: Unique player identifier
        role: Role string (e.g., "Seer", "Werewolf")
        llm: LangChain Runnable for LLM calls
        player_name: Display name
        player_seat: Seat number
        profile: Optional custom profile (defaults to role-based)

    Returns:
        Configured CognitiveAgent ready for game engine use
    """
    return CognitiveAgent(
        player_id=player_id,
        role=role,
        llm=llm,
        player_name=player_name,
        player_seat=player_seat,
        profile=profile,
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

        resp = client.chat_sync(lc_messages, max_tokens=500)

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
