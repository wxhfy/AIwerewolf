"""CognitiveAgent — drop-in replacement for LLMAgent.

Implements the Agent protocol using the Observe-Think-Act pipeline.

This module is the ONLY one that knows about:
- Agent protocol (talk, vote, attack, etc.)
- Decision dataclass
- Game engine integration

All cognitive work is delegated to Pipeline.
All memory work is delegated to Memory.
All observation work is delegated to observe.py.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, observe, format_observation
from backend.agents.cognitive.pipeline import Pipeline
from backend.agents.cognitive.profiles import Profile, get_profile
from backend.agents.cognitive.prompts import build_system_prompt
from backend.engine.models import Decision, ActionType


class CognitiveAgent:
    """Werewolf agent using Observe-Think-Act cognitive architecture.

    Implements the full Agent protocol. All cognitive work is delegated
    to the Pipeline module. This class only handles:
    - Agent lifecycle (initialize, update, finish)
    - Protocol compliance (talk, vote, attack, etc.)
    - State tracking (guard history, witch potions)
    """

    def __init__(
        self,
        player_id: str,
        role: str,
        llm: Runnable,
        player_name: str = "",
        player_seat: int = 0,
        profile: Optional[Profile] = None,
    ):
        self.player_id = player_id
        self.role = role
        self._llm = llm
        self.player_name = player_name
        self.player_seat = player_seat

        # Profile (WHO the agent is)
        self._profile = profile or get_profile(role)

        # System prompt (built once)
        self._system_prompt = build_system_prompt(role, self._profile)

        # Pipeline (stateless cognitive engine)
        self._pipeline = Pipeline(llm, self._system_prompt)

        # Memory (persists across rounds)
        self.memory = Memory(player_id, role)

        # Game state (set by engine via initialize/update)
        self._view: Any = None

        # Role-specific tracking
        self._guard_history: List[str] = []
        self._witch_save_used = False
        self._witch_poison_used = False

    # === Agent Protocol ===

    def initialize(self, view: Any, game_setting: dict) -> None:
        self._view = view
        self.player_name = view.self_player.get("name", self.player_id)
        self.player_seat = view.self_player.get("seat", 0)

    def update(self, view: Any, request: str) -> None:
        self._view = view
        self.memory.update_round(view.day, view.phase)

    def day_start(self) -> None:
        pass

    def talk(self) -> Decision:
        obs = self._observe()
        speech = self._pipeline.run_speech(obs, self.memory)
        self.memory.add_action("speech", None, speech, "")
        return self._decision(ActionType.TALK, speech=speech)

    def vote(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_vote(obs, obs, self.memory)
        target_id = self._resolve_target(result["target"])
        self.memory.add_action("vote", result["target"], f"投{result['target']}", result["reasoning"])
        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=result["reasoning"])

    def attack(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_night(obs, self.memory)
        return self._night_decision(result, ActionType.ATTACK)

    def divine(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_night(obs, self.memory)
        return self._night_decision(result, ActionType.DIVINE)

    def guard(self) -> Decision:
        extra = f"上一晚守护: {self._guard_history[-1]}" if self._guard_history else "第一晚"
        obs = self._observe()
        result = self._pipeline.run_night(obs, self.memory, extra)
        if result["target"]:
            self._guard_history.append(result["target"])
            self.memory.role_state.setdefault("protections", []).append(
                f"D{self.memory.day}: {result['target']}"
            )
        return self._night_decision(result, ActionType.GUARD)

    def witch_act(self, victim_id: Optional[str]) -> List[Decision]:
        lines = []
        if self._witch_save_used:
            lines.append("解药已使用")
        else:
            lines.append("解药可用")
        if self._witch_poison_used:
            lines.append("毒药已使用")
        else:
            lines.append("毒药可用")
        if victim_id:
            victim = self._find_player(victim_id)
            if victim:
                lines.append(f"今晚被刀的是: {victim.get('seat','?')}号:{victim.get('name','')}")

        obs = self._observe()
        result = self._pipeline.run_night(obs, self.memory, "\n".join(lines))

        decisions = []
        # Parse witch-specific JSON
        try:
            m = re.search(r'\{[^}]+\}', result.get("reasoning", ""))
            if m:
                data = json.loads(m.group())
                save = data.get("save", False)
                poison = data.get("poison_target")

                if save and not self._witch_save_used and victim_id:
                    self._witch_save_used = True
                    self.memory.role_state["save_used"] = True
                    decisions.append(self._decision(ActionType.WITCH_SAVE, target_id=victim_id))

                if poison and not self._witch_poison_used:
                    poison_id = self._resolve_target(poison)
                    if poison_id:
                        self._witch_poison_used = True
                        decisions.append(self._decision(ActionType.WITCH_POISON, target_id=poison_id))
        except (json.JSONDecodeError, KeyError):
            pass

        if not decisions:
            decisions.append(self._decision(ActionType.SKIP, reasoning="不用药"))

        return decisions

    def shoot(self) -> Decision:
        obs = self._observe()
        targets = [f"{p.seat}号:{p.name}" for p in obs.alive]
        prompt = format_observation(obs) + f"\n\n你已死亡，可开枪带走一人。\n可选: {', '.join(targets)}\n输出 JSON: {{\"reasoning\": \"理由\", \"target\": \"玩家名字\"}}"

        result = self._pipeline._call(self._system_prompt, prompt)
        parsed = _parse_json(result)
        target_id = self._resolve_target(parsed["target"]) or (self._view.players[0]["id"] if self._view.players else None)
        return self._decision(ActionType.SHOOT, target_id=target_id, reasoning=parsed["reasoning"])

    def boom(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_night(obs, self.memory)
        # For boom, we need a separate prompt asking if they want to self-destruct
        # For now, skip (boom decision needs special handling)
        return self._decision(ActionType.SKIP, reasoning="不自爆")

    def transfer_badge(self, candidates: List[str]) -> Decision:
        obs = self._observe()
        candidate_names = []
        for cid in candidates:
            p = self._find_player(cid)
            if p:
                candidate_names.append(f"{p.get('seat','?')}号:{p.get('name','')}")

        prompt = format_observation(obs) + f"\n\n你已死亡，需将警徽移交给一名存活玩家。\n候选人: {', '.join(candidate_names)}\n输出 JSON: {{\"reasoning\": \"理由\", \"target\": \"玩家名字\"}}"

        result = self._pipeline._call(self._system_prompt, prompt)
        parsed = _parse_json(result)
        target_id = self._resolve_target(parsed["target"]) or (candidates[0] if candidates else None)
        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=parsed["reasoning"])

    def finish(self, winner: Optional[str]) -> None:
        self.memory.add_action("game_end", None, f"胜者: {winner}", "")

    # === Internal Helpers ===

    def _observe(self) -> Observation:
        """Build observation from current view."""
        return observe(self._view, self.role)

    def _decision(
        self,
        action_type: ActionType,
        target_id: Optional[str] = None,
        speech: Optional[str] = None,
        reasoning: str = "",
    ) -> Decision:
        """Create a Decision with standard metadata."""
        return Decision(
            actor_id=self.player_id,
            action_type=action_type,
            target_id=target_id,
            speech=speech,
            reasoning=reasoning[:200],
            metadata={"source": "cognitive", "model": "cognitive"},
        )

    def _night_decision(self, result: Dict[str, str], action_type: ActionType) -> Decision:
        """Create a Decision for a night action."""
        target_id = self._resolve_target(result["target"])
        if not target_id:
            for p in self._view.players:
                if p["alive"]:
                    target_id = p["id"]
                    break
        return self._decision(action_type, target_id=target_id, reasoning=result["reasoning"])

    def _resolve_target(self, name: str) -> Optional[str]:
        """Resolve player name to player id."""
        if not name:
            return None
        for p in self._view.players:
            if p.get("name") == name:
                return p["id"]
        return None

    def _find_player(self, player_id: str) -> Optional[dict]:
        """Find player dict by id."""
        for p in self._view.players:
            if p["id"] == player_id:
                return p
        return None


def _parse_json(text: str) -> Dict[str, str]:
    """Extract target and reasoning from JSON in text."""
    try:
        m = re.search(r'\{[^}]+\}', text)
        if m:
            data = json.loads(m.group())
            return {
                "target": data.get("target", ""),
                "reasoning": data.get("reasoning", ""),
            }
    except (json.JSONDecodeError, KeyError):
        pass
    return {"target": "", "reasoning": text[:100]}
