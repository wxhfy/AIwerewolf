"""Cognitive Agent — Observe-Think-Act architecture for Werewolf.

This module provides a three-stage cognitive pipeline that replaces
the single-prompt approach:
1. OBSERVE: Extract key signals (facts + signals + gaps)
2. THINK: Analyze situation (judgment + strategy)
3. ACT: Generate concrete action (speech/vote/night action)

Usage:
    from backend.agents.cognitive import CognitiveAgent, create_cognitive_agent

    agent = create_cognitive_agent(
        player_id="player1",
        role="Seer",
        llm_provider="dsv4flash",
    )
"""

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.factory import create_cognitive_agent
from backend.agents.cognitive.graph_v2 import CognitiveState, CharacterProfile, CHARACTER_PROFILES, build_cognitive_graph_v2
from backend.agents.cognitive.memory import AgentMemory
from backend.agents.cognitive.state import GameObservation, build_observation

__all__ = [
    "CognitiveAgent",
    "create_cognitive_agent",
    "CognitiveState",
    "CharacterProfile",
    "CHARACTER_PROFILES",
    "build_cognitive_graph_v2",
    "AgentMemory",
    "GameObservation",
    "build_observation",
]
