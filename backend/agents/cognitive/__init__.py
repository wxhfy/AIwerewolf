"""Cognitive Agent — Observe-Think-Act architecture for Werewolf.

Public API:
    from backend.agents.cognitive import CognitiveAgent, create_cognitive_agent

Design principles:
    - Single Responsibility: each module does ONE thing
    - Open/Closed: extend by adding new strategies, not modifying core
    - Dependency Inversion: agent depends on abstractions (LLM, Memory)
    - Interface Segregation: clean boundaries between observe/think/act
"""

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.factory import create_cognitive_agent

__all__ = ["CognitiveAgent", "create_cognitive_agent"]
