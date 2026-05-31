"""Cognitive Agent v3 — uses the StateGraph cognitive pipeline.

Drop-in replacement for LLMAgent. Implements the full Agent protocol
using Observe → Think → Act → Reflect for each decision.

Key improvements:
- Focused prompts (each LLM call does ONE thing)
- Character system shapes personality
- Structured memory persists across rounds
- Reflection catches bad outputs
- Compatible with existing game engine
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableLambda

from backend.agents.cognitive.graph_v3 import (
    CHARACTERS,
    CognitiveGraph,
    GameState,
    build_cognitive_graph,
)
from backend.agents.cognitive.memory import AgentMemory
from backend.agents.cognitive.state import GameObservation, build_observation, format_observation_text
from backend.engine.models import Decision, ActionType


class CognitiveAgentV3:
    """Werewolf agent using Observe-Think-Act-Reflect cognitive architecture.

    Each decision goes through:
    1. OBSERVE: Extract facts and signals (no judgments)
    2. THINK: Analyze situation, evaluate players
    3. ACT: Generate concrete action
    4. REFLECT: Check output quality, retry if needed
    """

    def __init__(
        self,
        player_id: str,
        role: str,
        llm: Runnable,
        player_name: str = "",
        player_seat: int = 0,
        character: Any = None,
    ):
        self.player_id = player_id
        self.role = role
        self.llm = llm
        self.player_name = player_name
        self.player_seat = player_seat
        self.character = character

        # Cognitive graph
        self.graph = build_cognitive_graph(llm)

        # Memory system
        self.memory = AgentMemory(player_id, role)

        # Game state
        self.view: Any = None

        # Role-specific state
        self._guard_history: List[str] = []
        self._witch_save_used = False
        self._witch_poison_used = False

    def initialize(self, view: Any, game_setting: dict) -> None:
        self.view = view
        self.player_name = view.self_player.get("name", self.player_id)
        self.player_seat = view.self_player.get("seat", 0)

    def update(self, view: Any, request: str) -> None:
        self.view = view
        self.memory.update_round(view.day, view.phase)

    def _build_state(self, phase: str, action_type: str = "", extra_info: str = "") -> GameState:
        """Build initial GameState from current view."""
        obs = build_observation(self.view, self.role)
        obs_text = format_observation_text(obs)

        return GameState(
            observation_text=obs_text,
            game_phase=phase,
            role=self.role,
            player_name=self.player_name,
            player_seat=self.player_seat,
            extra_info=extra_info,
            memory_text=self.memory.format_for_prompt(),
        )

    def _run_pipeline(self, phase: str, action_type: str = "", extra_info: str = "") -> GameState:
        """Run the cognitive pipeline."""
        state = self._build_state(phase, action_type, extra_info)
        return self.graph.invoke(state)

    def talk(self) -> Decision:
        state = self._run_pipeline("speech")
        speech = state.get("speech_text", "")

        self.memory.add_action("speech", None, speech, state.get("think_result", "")[:100])

        return Decision(
            player_id=self.player_id,
            action_type=ActionType.TALK,
            reasoning=state.get("think_result", "")[:200],
            metadata={"speech": speech, "source": "cognitive_v3", "model": "cognitive"},
        )

    def vote(self) -> Decision:
        state = self._run_pipeline("vote")
        target_name = state.get("vote_target", "")
        reasoning = state.get("think_result", "")[:100]

        # Find target player
        target_id = None
        for p in self.view.players:
            if p.get("name") == target_name and p["id"] != self.player_id:
                target_id = p["id"]
                break

        # Fallback
        if not target_id:
            for p in self.view.players:
                if p["id"] != self.player_id and p["alive"]:
                    target_id = p["id"]
                    target_name = p["name"]
                    break

        self.memory.add_action("vote", target_name, f"投{target_name}", reasoning)

        return Decision(
            player_id=self.player_id,
            action_type=ActionType.VOTE,
            target_id=target_id,
            reasoning=reasoning,
            metadata={"source": "cognitive_v3", "model": "cognitive"},
        )

    def attack(self) -> Decision:
        state = self._run_pipeline("night", "wolf_attack")
        return self._make_night_decision(state, ActionType.ATTACK)

    def divine(self) -> Decision:
        state = self._run_pipeline("night", "seer_check")
        return self._make_night_decision(state, ActionType.DIVINE)

    def guard(self) -> Decision:
        extra = f"上一晚守护: {self._guard_history[-1]}" if self._guard_history else "第一晚"
        state = self._run_pipeline("night", "guard_protect", extra)
        target_name = state.get("night_target", "")

        # Track guard history
        if target_name:
            self._guard_history.append(target_name)
            self.memory.role_memory.setdefault("protection_history", []).append(
                f"D{self.view.day}: 守护{target_name}"
            )

        return self._make_night_decision(state, ActionType.GUARD)

    def witch_act(self, victim_id: str | None) -> List[Decision]:
        # Build witch-specific info
        lines = []
        if self._witch_save_used:
            lines.append("解药已使用")
        else:
            lines.append("解药可用")
        if self._witch_poison_used:
            lines.append("毒药已使用")
        else:
            lines.append("毒药可用")

        # Find victim name
        if victim_id:
            for p in self.view.players:
                if p["id"] == victim_id:
                    lines.append(f"今晚被刀的是: {p.get('seat', '?')}号:{p['name']}")
                    break

        extra = "\n".join(lines)
        state = self._run_pipeline("night", "witch_act", extra)

        # Parse witch action
        action_json = state.get("action_json", {})
        save = action_json.get("save", False)
        poison_target = action_json.get("poison_target")

        decisions = []

        if save and not self._witch_save_used and victim_id:
            self._witch_save_used = True
            self.memory.role_memory["save_used"] = True
            decisions.append(Decision(
                player_id=self.player_id,
                action_type=ActionType.WITCH_SAVE,
                target_id=victim_id,
                reasoning=state.get("think_result", "")[:100],
                metadata={"source": "cognitive_v3", "model": "cognitive"},
            ))

        if poison_target and not self._witch_poison_used:
            target_id = None
            for p in self.view.players:
                if p["name"] == poison_target:
                    target_id = p["id"]
                    break
            if target_id:
                self._witch_poison_used = True
                decisions.append(Decision(
                    player_id=self.player_id,
                    action_type=ActionType.WITCH_POISON,
                    target_id=target_id,
                    reasoning=state.get("think_result", "")[:100],
                    metadata={"source": "cognitive_v3", "model": "cognitive"},
                ))

        if not decisions:
            decisions.append(Decision(
                player_id=self.player_id,
                action_type=ActionType.SKIP,
                reasoning="不用药",
                metadata={"source": "cognitive_v3", "model": "cognitive"},
            ))

        return decisions

    def shoot(self) -> Decision:
        obs = build_observation(self.view, self.role)
        obs_text = format_observation_text(obs)

        targets = [f"{p.get('seat', '?')}号:{p['name']}" for p in self.view.players if p["alive"]]
        prompt = f"""{obs_text}

你已死亡，可开枪带走一人。
可选目标: {', '.join(targets)}
输出 JSON: {{"reasoning": "理由", "target": "玩家名字"}}"""

        try:
            resp = self.llm.invoke([
                SystemMessage(content=CHARACTERS.get("Hunter", CHARACTERS["Villager"]).system_prompt()),
                HumanMessage(content=prompt),
            ])
            m = re.search(r'\{[^}]+\}', resp.content)
            if m:
                data = json.loads(m.group())
                target_name = data.get("target", "")
                target_id = None
                for p in self.view.players:
                    if p["name"] == target_name:
                        target_id = p["id"]
                        break
                if not target_id and self.view.players:
                    target_id = self.view.players[0]["id"]
                return Decision(
                    player_id=self.player_id,
                    action_type=ActionType.SHOOT,
                    target_id=target_id,
                    reasoning=data.get("reasoning", ""),
                    metadata={"source": "cognitive_v3", "model": "cognitive"},
                )
        except Exception:
            pass

        # Fallback
        return Decision(
            player_id=self.player_id,
            action_type=ActionType.SHOOT,
            target_id=self.view.players[0]["id"] if self.view.players else None,
            reasoning="猎人开枪",
            metadata={"source": "cognitive_v3", "model": "cognitive"},
        )

    def boom(self) -> Decision:
        state = self._run_pipeline("night", "wolf_boom")
        action_json = state.get("action_json", {})
        if not action_json.get("boom", False):
            return Decision(
                player_id=self.player_id,
                action_type=ActionType.SKIP,
                reasoning="不自爆",
                metadata={"source": "cognitive_v3", "model": "cognitive"},
            )
        target_name = action_json.get("target", "")
        target_id = None
        for p in self.view.players:
            if p["name"] == target_name:
                target_id = p["id"]
                break
        return Decision(
            player_id=self.player_id,
            action_type=ActionType.BOOM,
            target_id=target_id,
            reasoning=action_json.get("reasoning", ""),
            metadata={"source": "cognitive_v3", "model": "cognitive"},
        )

    def transfer_badge(self, candidates: List[str]) -> Decision:
        obs = build_observation(self.view, self.role)
        obs_text = format_observation_text(obs)

        candidate_names = []
        for cid in candidates:
            for p in self.view.players:
                if p["id"] == cid:
                    candidate_names.append(f"{p.get('seat', '?')}号:{p['name']}")

        prompt = f"""{obs_text}

你已死亡，需将警徽移交给一名存活玩家。
候选人: {', '.join(candidate_names)}
输出 JSON: {{"reasoning": "理由", "target": "玩家名字"}}"""

        try:
            resp = self.llm.invoke([
                SystemMessage(content="选择警徽继承人。输出JSON。"),
                HumanMessage(content=prompt),
            ])
            m = re.search(r'\{[^}]+\}', resp.content)
            if m:
                data = json.loads(m.group())
                target_name = data.get("target", "")
                for cid in candidates:
                    for p in self.view.players:
                        if p["id"] == cid and p["name"] == target_name:
                            return Decision(
                                player_id=self.player_id,
                                action_type=ActionType.VOTE,
                                target_id=cid,
                                reasoning=data.get("reasoning", ""),
                                metadata={"source": "cognitive_v3", "model": "cognitive"},
                            )
        except Exception:
            pass

        return Decision(
            player_id=self.player_id,
            action_type=ActionType.VOTE,
            target_id=candidates[0] if candidates else None,
            reasoning="警徽移交",
            metadata={"source": "cognitive_v3", "model": "cognitive"},
        )

    def day_start(self) -> None:
        pass

    def finish(self, winner: str | None) -> None:
        self.memory.add_round_summary([f"游戏结束，胜者: {winner}"])

    def _make_night_decision(self, state: GameState, action_type: ActionType) -> Decision:
        target_name = state.get("night_target", "")
        target_id = None
        for p in self.view.players:
            if p["name"] == target_name:
                target_id = p["id"]
                break
        if not target_id:
            for p in self.view.players:
                if p["alive"]:
                    target_id = p["id"]
                    break
        return Decision(
            player_id=self.player_id,
            action_type=action_type,
            target_id=target_id,
            reasoning=state.get("think_result", "")[:100],
            metadata={"source": "cognitive_v3", "model": "cognitive"},
        )
