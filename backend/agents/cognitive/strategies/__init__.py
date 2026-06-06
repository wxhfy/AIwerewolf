"""Role strategy cards — decision-layer configuration independent of MBTI/Persona.

Architecture:
  Personality Layer → controls "how to say" (profiles.py)
  Strategy Layer   → controls "what to do" (strategies/)

Strategy cards are split into:
  - Rule-based: explicit, explainable, stable (e.g., "reveal when checked wolf")
  - Parameter-based: tunable, A/B testable (e.g., risk_tolerance=0.7)
"""

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import StrategyMemory
from backend.agents.cognitive.strategies.base import get_strategy_card
from backend.agents.cognitive.strategies.guard import GuardStrategyCard
from backend.agents.cognitive.strategies.hunter import HunterStrategyCard
from backend.agents.cognitive.strategies.seer import SeerStrategyCard
from backend.agents.cognitive.strategies.villager import VillagerStrategyCard
from backend.agents.cognitive.strategies.werewolf import WerewolfStrategyCard
from backend.agents.cognitive.strategies.witch import WitchStrategyCard

__all__ = [
    "RoleStrategyCard",
    "StrategyMemory",
    "SeerStrategyCard",
    "WitchStrategyCard",
    "HunterStrategyCard",
    "GuardStrategyCard",
    "VillagerStrategyCard",
    "WerewolfStrategyCard",
    "get_strategy_card",
]
