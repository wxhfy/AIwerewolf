"""Cognitive Agent v3 — StateGraph pipeline with full character + strategy integration.

Integrates three layers:
1. MBTI/Persona — from Character system (personality, speaking style, pressure reactions)
2. Role — from CharacterProfile (role goal, backstory) + RoleProfile (table_goal, speech_style)
3. Strategy — from playbooks.py (action playbooks) + strategy knowledge retrieval
"""

from __future__ import annotations

import json
import os
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
from backend.agents.playbooks import build_role_brief
from backend.agents.profiles import ROLE_PROFILES
from backend.engine.models import Decision, ActionType, Role


class CognitiveAgentV3:
    """Werewolf agent using Observe-Think-Act-Reflect cognitive architecture.

    Three-layer integration:
    - Layer 1: MBTI/Persona — shapes WHO the agent is (personality, style)
    - Layer 2: Role — shapes WHAT the agent wants (goal, strategy)
    - Layer 3: Strategy — shapes HOW the agent acts (playbook, knowledge)
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

        # Build role-specific strategy (match Role enum by value)
        role_enum = Role.VILLAGER
        for r in Role:
            if r.value.lower() == role.lower():
                role_enum = r
                break
        self._role_brief = build_role_brief(role_enum)
        self._role_profile = ROLE_PROFILES.get(role_enum)

        # Build the unified system prompt (3-layer integration)
        self._system_prompt = self._build_system_prompt()

        # Cognitive graph (with integrated system prompt)
        self.graph = build_cognitive_graph(llm, self._system_prompt)

        # Memory system
        self.memory = AgentMemory(player_id, role)

        # Game state
        self.view: Any = None

        # Role-specific state
        self._guard_history: List[str] = []
        self._witch_save_used = False
        self._witch_poison_used = False

    def _build_system_prompt(self) -> str:
        """Build unified system prompt integrating all 3 layers."""

        parts = []

        # === Layer 1: Character/Persona (MBTI + personality) ===
        if self.character:
            p = self.character.persona
            m = self.character.mind

            parts.append(f"【你的身份】")
            parts.append(f"你是{p.name}，{p.age}岁，扮演{self.role}。")
            if p.basic_info:
                parts.append(f"背景：{p.basic_info}")

            # MBTI personality
            if p.mbti:
                parts.append(f"性格类型：{p.mbti}")

            # Speaking style
            if p.vocabulary_style:
                parts.append(f"说话风格：{p.vocabulary_style}")
            if p.speech_length_habit:
                parts.append(f"发言长短：{p.speech_length_habit}")
            if p.reasoning_style:
                parts.append(f"推理方式：{p.reasoning_style}")

            # Decision-making traits (PlayerMind)
            courage_map = {
                "bold": "你不怕站边、敢带节奏",
                "cautious": "你比较谨慎，不会第一个冲票",
                "calculated": "你有把握时才明确表态",
            }
            suspicion_map = {
                "low": "你比较容易起疑，小破绽就能让你锁定目标",
                "medium": "你需要看到连续的可疑行为才会下判断",
                "high": "你倾向于先相信别人的解释",
            }
            logic_map = {
                "shallow": "你凭直觉做判断，不太深究逻辑链条",
                "moderate": "你会盘基本逻辑，但不钻牛角尖",
                "deep": "你喜欢多角度分析，会反复推敲每个细节",
            }

            parts.append(f"态度：{courage_map.get(m.courage, '看情况表态')}")
            parts.append(f"对他人的信任度：{suspicion_map.get(m.suspicion_threshold, '中等')}")
            parts.append(f"推理深度：{logic_map.get(m.logic_depth, '中等')}")

            # Pressure and social habits
            if p.pressure_style:
                parts.append(f"压力下的反应：{p.pressure_style}")
            if p.social_habit:
                parts.append(f"社交习惯：{p.social_habit}")
            if p.wolf_deception_style and self.role.lower() in ("werewolf", "white_wolf_king"):
                parts.append(f"拿狼时的打法：{p.wolf_deception_style}")
            if p.mistake_pattern:
                parts.append(f"你的一个弱点：{p.mistake_pattern}")

        # === Layer 2: Role goal and strategy ===
        char_profile = CHARACTERS.get(self.role, CHARACTERS["Villager"])
        parts.append(f"\n【你的角色目标】")
        parts.append(f"目标：{char_profile.goal}")
        parts.append(f"背景：{char_profile.backstory}")
        if char_profile.speech_style:
            parts.append(f"发言风格：{char_profile.speech_style}")

        # === Layer 3: Strategy (playbook) ===
        parts.append(f"\n【你的策略指南】")
        parts.append(self._role_brief)

        # Role profile (from profiles.py)
        if self._role_profile:
            parts.append(f"\n【桌面表现】")
            parts.append(f"目标：{self._role_profile.table_goal}")
            parts.append(f"发言：{self._role_profile.speech_style}")
            parts.append(f"被质疑时：{self._role_profile.pressure_style}")
            parts.append(f"身份暴露策略：{self._role_profile.reveal_policy}")
            if self._role_profile.wolf_disguise_style and self.role.lower() in ("werewolf", "white_wolf_king"):
                parts.append(f"伪装方式：{self._role_profile.wolf_disguise_style}")

        parts.append(f"\n你正在参与一局狼人杀游戏。请用中文回答。")
        parts.append(f"重要：你的推理过程是内部思考，不要在发言中暴露。发言时只说你观察到的公开信息和你的判断。")

        return "\n".join(parts)

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
            actor_id=self.player_id,
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
            actor_id=self.player_id,
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

        if target_name:
            self._guard_history.append(target_name)
            self.memory.role_memory.setdefault("protection_history", []).append(
                f"D{self.view.day}: 守护{target_name}"
            )

        return self._make_night_decision(state, ActionType.GUARD)

    def witch_act(self, victim_id: str | None) -> List[Decision]:
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
            for p in self.view.players:
                if p["id"] == victim_id:
                    lines.append(f"今晚被刀的是: {p.get('seat', '?')}号:{p['name']}")
                    break

        extra = "\n".join(lines)
        state = self._run_pipeline("night", "witch_act", extra)

        action_json = state.get("action_json", {})
        save = action_json.get("save", False)
        poison_target = action_json.get("poison_target")

        decisions = []

        if save and not self._witch_save_used and victim_id:
            self._witch_save_used = True
            self.memory.role_memory["save_used"] = True
            decisions.append(Decision(
                actor_id=self.player_id,
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
                    actor_id=self.player_id,
                    action_type=ActionType.WITCH_POISON,
                    target_id=target_id,
                    reasoning=state.get("think_result", "")[:100],
                    metadata={"source": "cognitive_v3", "model": "cognitive"},
                ))

        if not decisions:
            decisions.append(Decision(
                actor_id=self.player_id,
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
                SystemMessage(content=self._system_prompt),
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
                    actor_id=self.player_id,
                    action_type=ActionType.SHOOT,
                    target_id=target_id,
                    reasoning=data.get("reasoning", ""),
                    metadata={"source": "cognitive_v3", "model": "cognitive"},
                )
        except Exception:
            pass

        return Decision(
            actor_id=self.player_id,
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
                actor_id=self.player_id,
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
            actor_id=self.player_id,
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
                SystemMessage(content=self._system_prompt),
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
                                actor_id=self.player_id,
                                action_type=ActionType.VOTE,
                                target_id=cid,
                                reasoning=data.get("reasoning", ""),
                                metadata={"source": "cognitive_v3", "model": "cognitive"},
                            )
        except Exception:
            pass

        return Decision(
            actor_id=self.player_id,
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
            actor_id=self.player_id,
            action_type=action_type,
            target_id=target_id,
            reasoning=state.get("think_result", "")[:100],
            metadata={"source": "cognitive_v3", "model": "cognitive"},
        )
