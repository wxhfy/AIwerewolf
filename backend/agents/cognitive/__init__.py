"""Cognitive Agent — production-grade modular architecture for Werewolf AI.

Fully integrated: LLMAgent-quality prompts + Character system + BeliefTracker
+ Humanization + Playbooks + Strategy Bias + three-tier retry/fallback.

Module structure:
    profiles.py     WHO:  Role + PersonaTraits + MindTraits (integrated Character system)
    humanization.py MAP:  Personality → behavioral parameters
    repository.py   DATA: Load strategy data from PostgreSQL
    observe.py      SEE:  Extract facts + belief tracking (claims/contradictions/votes)
    memory.py       MEM:  Persist judgments/actions + humanization + playbook
    prompts.py      TELL: Build wolfcha-quality prompts for each phase
    pipeline.py     THINK: Orchestrate LLM calls (observe→think→act)
    agent.py        ACT:  Agent protocol implementation
    factory.py      MAKE: Object construction with Character pool support
    retrieval.py    FIND: TF-IDF vector search over strategy knowledge base
    retrieval_prod.py FIND: BM25 + keyword grep strategy retrieval (GPU-free)
    reflect.py      LEARN: Post-game MBTI-differentiated reflection + knowledge extraction

Data flow:
    Game Engine
        ↓ PlayerView
    observe.py + BeliefTracker → Observation
        ↓
    prompts.py + memory.py(humanization + playbook) + profiles.py → Prompt
        ↓
    pipeline.py → AgentLoop (tool-calling LLM with self-termination) + strategy retrieval + bias
        ↓
    agent.py → Decision
        ↓
    Game Engine

Key design principles:
    - High cohesion: each module has ONE responsibility
    - Low coupling: modules depend only on type definitions, not implementations
    - Backward compatible: CognitiveAgent interface unchanged, new params optional
    - LLMAgent independent: LLMAgent unchanged during integration
"""

from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.factory import create_cognitive_agent
from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.agents.cognitive.factory import create_llm_from_client
from backend.agents.cognitive.humanization import HumanizationProfile
from backend.agents.cognitive.humanization import build_humanization_profile
from backend.agents.cognitive.memory import ActionRecord
from backend.agents.cognitive.memory import Judgment
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import BeliefTracker
from backend.agents.cognitive.observe import Contradiction
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import RoleClaim
from backend.agents.cognitive.observe import format_observation
from backend.agents.cognitive.observe import observe
from backend.agents.cognitive.profiles import PROFILES
from backend.agents.cognitive.profiles import MindTraits
from backend.agents.cognitive.profiles import PersonaTraits
from backend.agents.cognitive.profiles import Profile
from backend.agents.cognitive.profiles import get_profile
from backend.agents.cognitive.prompts import build_game_context
from backend.agents.cognitive.prompts import build_system_prompt
from backend.agents.cognitive.reflect import ReflectionResult
from backend.agents.cognitive.reflect import Reflector
from backend.agents.cognitive.reflect import reflections_to_knowledge_docs
from backend.agents.cognitive.reflect import save_reflections_to_db
from backend.agents.cognitive.repository import load_profile_from_db
from backend.agents.cognitive.repository import load_profiles_from_db
from backend.agents.cognitive.retrieval import StrategyIndex
from backend.agents.cognitive.retrieval import format_strategies_for_prompt
from backend.agents.cognitive.retrieval import get_index
from backend.agents.cognitive.retrieval import rebuild_index
from backend.agents.cognitive.retrieval import retrieve_strategies

__all__ = [
    # Agent
    "CognitiveAgent",
    # Factory
    "create_cognitive_agent",
    "create_cognitive_agent_with_character",
    "create_llm_from_client",
    # Profiles
    "Profile",
    "PersonaTraits",
    "MindTraits",
    "get_profile",
    "PROFILES",
    # Humanization
    "HumanizationProfile",
    "build_humanization_profile",
    # Observation
    "Observation",
    "BeliefTracker",
    "observe",
    "format_observation",
    "RoleClaim",
    "Contradiction",
    # Memory
    "Memory",
    "Judgment",
    "ActionRecord",
    # Prompts
    "build_system_prompt",
    "build_game_context",
    # Repository
    "load_profiles_from_db",
    "load_profile_from_db",
    # Retrieval
    "retrieve_strategies",
    "format_strategies_for_prompt",
    "get_index",
    "rebuild_index",
    "StrategyIndex",
    # Reflection
    "Reflector",
    "ReflectionResult",
    "reflections_to_knowledge_docs",
    "save_reflections_to_db",
]
