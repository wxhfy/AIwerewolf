"""Factory function to create CognitiveAgent instances from game config."""

from __future__ import annotations

from typing import Any

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.graph import build_cognitive_graph


def create_cognitive_agent(
    player_id: str,
    role: str,
    llm_provider: str = "dsv4flash",
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    character: Any = None,
    player_name: str = "",
    player_seat: int = 0,
) -> CognitiveAgent:
    """Create a CognitiveAgent with the specified LLM backend.

    Args:
        player_id: The player's unique ID
        role: The player's role (e.g., "Werewolf", "Seer")
        llm_provider: LLM provider name ("dsv4flash", "deepseek", "doubao")
        llm_model: Model name override
        llm_api_key: API key override
        llm_base_url: Base URL override
        character: Character/persona object
        player_name: Player display name
        player_seat: Player seat number

    Returns:
        Configured CognitiveAgent instance
    """
    # Create the LLM using the existing backend
    from backend.llm import create_client

    client = create_client(
        provider=llm_provider,
        model=llm_model,
        api_key=llm_api_key,
        base_url=llm_base_url,
    )

    # Wrap the client in a LangChain-compatible Runnable
    from langchain_core.messages import BaseMessage
    from langchain_core.runnables import RunnableLambda

    def llm_invoke(messages: list[BaseMessage]) -> Any:
        """Call the LLM client with LangChain messages."""
        # Convert LangChain messages to the format expected by the client
        lc_messages = []
        for msg in messages:
            if hasattr(msg, 'content'):
                role = "user" if msg.type == "human" else "system"
                lc_messages.append({"role": role, "content": msg.content})

        # Call the client
        response = client.chat_sync(lc_messages, max_tokens=500)

        # Create a response-like object
        class LLMResponse:
            def __init__(self, content: str):
                self.content = content

        # Extract the response text
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
            else:
                content = str(response)
        else:
            content = str(response)

        return LLMResponse(content)

    llm = RunnableLambda(llm_invoke)

    # Create the agent
    agent = CognitiveAgent(
        player_id=player_id,
        role=role,
        llm=llm,
        player_name=player_name,
        player_seat=player_seat,
        character=character,
    )

    return agent
