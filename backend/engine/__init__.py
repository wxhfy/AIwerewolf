"""Extensible game engine for AI Werewolf."""

from backend.engine.game import WerewolfGame
from backend.engine.models import Alignment, Phase, Role

__all__ = ["Alignment", "Phase", "Role", "WerewolfGame"]
