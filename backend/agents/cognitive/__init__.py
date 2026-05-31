"""Cognitive Agent — clean, modular architecture for Werewolf AI.

Module structure:
    profiles.py     WHO:  Role definitions (fallback, hardcoded)
    repository.py   DATA: Load strategy data from PostgreSQL
    observe.py      SEE:  Extract facts from game state
    memory.py       MEM:  Persist judgments/actions across rounds
    prompts.py      TELL: Build prompts for each phase
    pipeline.py     THINK: Orchestrate LLM calls (observe→think→act)
    agent.py        ACT:  Agent protocol implementation
    factory.py      MAKE: Object construction

Data flow:
    Game Engine
        ↓ PlayerView
    observe.py → Observation
        ↓
    prompts.py + memory.py + profiles.py → Prompt
        ↓
    pipeline.py → LLM calls → Result
        ↓
    agent.py → Decision
        ↓
    Game Engine

Database integration:
    role_strategy_cards (PostgreSQL)
        ↓
    repository.py → Profile
        ↓
    factory.py → CognitiveAgent
"""

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.factory import create_cognitive_agent
from backend.agents.cognitive.repository import load_profiles_from_db, load_profile_from_db

__all__ = [
    "CognitiveAgent",
    "create_cognitive_agent",
    "load_profiles_from_db",
    "load_profile_from_db",
]
