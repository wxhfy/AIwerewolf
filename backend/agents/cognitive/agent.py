"""Cognitive Agent — Observe-Think-Act architecture for Werewolf.

This agent replaces the single-prompt approach with a three-stage
cognitive pipeline:
1. OBSERVE: Extract key signals from game state (no judgments)
2. THINK: Analyze situation, evaluate players, consider strategy
3. ACT: Generate concrete action (speech/vote/night action)

Each stage is a separate LLM call with a focused prompt, ensuring
the agent "sees before judging" and "thinks before acting".
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.act import (
    build_badge_speech_prompt,
    build_night_action_prompt,
    build_speech_prompt,
    build_vote_prompt,
)
from backend.agents.cognitive.memory import AgentMemory
from backend.agents.cognitive.observe import build_observe_prompt
from backend.agents.cognitive.state import GameObservation, build_observation, format_observation_text
from backend.agents.cognitive.think import build_think_prompt
from backend.engine.models import Decision, ActionType


class CognitiveAgent:
    """Werewolf agent using Observe-Think-Act cognitive architecture.

    Unlike the single-prompt LLMAgent, this agent makes three focused
    LLM calls per decision:
    - Observe: What do I see? (facts + signals + gaps)
    - Think: What does it mean? (analysis + judgment + strategy)
    - Act: What do I do? (concrete action)
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

        # Memory system
        self.memory = AgentMemory(player_id, role)

        # Current game state
        self.view: Any = None
        self.current_observation: GameObservation | None = None

        # Role-specific state
        self._seer_checks: list[dict] = []
        self._guard_history: list[str] = []
        self._witch_save_used: bool = False
        self._witch_poison_used: bool = False
        self._wolf_kill_targets: list[str] = []

    def initialize(self, view: Any, game_setting: dict) -> None:
        """Initialize the agent with game start info."""
        self.view = view
        self.player_name = view.self_player.get("name", self.player_id)
        self.player_seat = view.self_player.get("seat", 0)

        # Initialize role memory
        if self.role == "Seer":
            self.memory.role_memory["check_history"] = []
        elif self.role == "Witch":
            self.memory.role_memory["save_used"] = False
            self.memory.role_memory["poison_used"] = False
            self.memory.role_memory["saves"] = []
            self.memory.role_memory["poisons"] = []
        elif self.role == "Guard":
            self.memory.role_memory["protection_history"] = []
        elif self.role == "Werewolf":
            self.memory.role_memory["kill_targets"] = []
            self.memory.role_memory["partner_info"] = ""

    def update(self, view: Any, request: str) -> None:
        """Update the agent with new game state."""
        self.view = view
        self.memory.update_round(view.day, view.phase)

    def _call_llm(self, prompt: str, system_msg: str = "") -> str:
        """Call the LLM with a prompt."""
        messages = []
        if system_msg:
            messages.append(SystemMessage(content=system_msg))
        messages.append(HumanMessage(content=prompt))

        try:
            response = self.llm.invoke(messages)
            return response.content.strip()
        except Exception as e:
            return f"[LLM Error: {e}]"

    def _observe(self, obs: GameObservation) -> str:
        """Stage 1: Observe — extract key signals from game state."""
        prompt = build_observe_prompt(obs)
        return self._call_llm(
            prompt,
            "你是一个狼人杀游戏的观察者。仔细观察游戏状态，提取关键信号和事实。不要做判断，只描述观察。用中文回答。"
        )

    def _think(self, obs: GameObservation, observe_result: str) -> str:
        """Stage 2: Think — analyze situation and generate judgments."""
        # Build enhanced think prompt with observation results
        memory_text = self.memory.format_for_prompt()

        player_lines = []
        for p in obs.alive_players:
            if p.player_id == self.player_id:
                player_lines.append(f"  {p.seat}号:{p.name} = 你自己（{self.role}）")
                continue
            prev = self.memory.get_player_judgment(p.name)
            prev_note = f" [上次: {prev.judgment}({prev.confidence:.0%})]" if prev else ""
            player_lines.append(f"  {p.seat}号:{p.name}{prev_note}")

        # Strategic context
        alive_count = len(obs.alive_players)
        if obs.day == 1:
            day_strategy = "第一天信息极少，以收集信息为主"
        elif obs.day == 2:
            day_strategy = "第二天有投票和死亡信息，可以形成初步判断"
        else:
            day_strategy = f"第{obs.day}天中后期，需要明确站边"

        phase_strategy = ""
        if "SPEECH" in obs.phase:
            phase_strategy = "发言阶段：需要给出判断方向"
        elif "VOTE" in obs.phase:
            phase_strategy = "投票阶段：做出最终决定"
        elif "NIGHT" in obs.phase:
            phase_strategy = "夜间：执行角色技能"

        prompt = f"""你是 {obs.player_seat}号:{obs.player_name}，身份={self.role}，第{obs.day}天 {obs.phase}阶段。

=== 我的观察 ===
{observe_result}

=== 玩家列表 ===
{chr(10).join(player_lines)}

=== 战略背景 ===
存活 {alive_count} 人。{day_strategy}。{phase_strategy}

{f"=== 我的记忆 ==={chr(10)}{memory_text}" if memory_text else ""}

请分析：
1. 当前局势的关键矛盾是什么？
2. 每个存活玩家的可疑程度（高/中/低/不确定）
3. 你最怀疑谁？为什么？
4. 推荐的行动方向

用 3-5 句话总结你的分析。"""

        return self._call_llm(
            prompt,
            "你是一个狼人杀游戏的分析师。基于观察结果进行推理分析。用中文回答。"
        )

    def _act_speech(self, obs: GameObservation, think_result: str) -> Decision:
        """Stage 3a: Generate a speech."""
        # Build style hint from character
        style_hint = ""
        if self.character and hasattr(self.character, 'persona'):
            persona = self.character.persona
            if hasattr(persona, 'speech_style') and persona.speech_style:
                style_hint = persona.speech_style

        prompt = build_speech_prompt(obs, think_result, style_hint)
        result = self._call_llm(
            prompt,
            "你是一个狼人杀玩家。像在桌面上说话一样发言。用中文回答。不要输出JSON。"
        )

        # Clean up speech
        speech = result.strip()
        # Remove common prefixes
        for prefix in ["发言：", "发言:", "我的发言：", "我的发言:"]:
            if speech.startswith(prefix):
                speech = speech[len(prefix):].strip()
        # Remove quotes
        if speech.startswith('"') and speech.endswith('"'):
            speech = speech[1:-1].strip()

        # Record action
        self.memory.add_action("speech", None, speech, think_result[:100])

        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.TALK,
            reasoning=think_result[:200],
            metadata={"speech": speech, "source": "cognitive", "model": "cognitive-agent"},
        )

    def _act_vote(self, obs: GameObservation, think_result: str) -> Decision:
        """Stage 3b: Generate a vote."""
        prompt = build_vote_prompt(obs, think_result)
        result = self._call_llm(
            prompt,
            "你是一个狼人杀玩家。投票决定谁出局。输出JSON格式。"
        )

        # Parse JSON
        target_name = None
        reasoning = think_result[:100]
        try:
            # Try to extract JSON from the response
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                data = json.loads(json_match.group())
                target_name = data.get("target", "")
                reasoning = data.get("reasoning", reasoning)
        except (json.JSONDecodeError, KeyError):
            # Fallback: try to find a name in the text
            for p in obs.alive_players:
                if p.name in result and p.player_id != self.player_id:
                    target_name = p.name
                    break

        # Find target player
        target_id = None
        for p in obs.alive_players:
            if p.name == target_name and p.player_id != self.player_id:
                target_id = p.player_id
                break

        # Fallback: vote for the first alive non-self player
        if not target_id:
            for p in obs.alive_players:
                if p.player_id != self.player_id:
                    target_id = p.player_id
                    target_name = p.name
                    break

        # Record action
        self.memory.add_action("vote", target_name, f"投{target_name}", reasoning)

        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.VOTE,
            target_id=target_id,
            reasoning=reasoning,
            metadata={"source": "cognitive", "model": "cognitive-agent"},
        )

    def _act_night(self, obs: GameObservation, think_result: str, action_type: str) -> Decision:
        """Stage 3c: Generate a night action."""
        # Build extra info based on role
        extra_info = ""
        if self.role == "Witch":
            extra_info = self._get_witch_info(obs)
        elif self.role == "Guard":
            extra_info = self._get_guard_info()

        prompt = build_night_action_prompt(obs, think_result, action_type, extra_info)
        result = self._call_llm(
            prompt,
            "你是一个狼人杀玩家。执行夜间行动。输出JSON格式。"
        )

        # Parse JSON
        target_name = None
        reasoning = think_result[:100]
        save = False
        poison_target = None

        try:
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                data = json.loads(json_match.group())
                target_name = data.get("target", "")
                reasoning = data.get("reasoning", reasoning)
                save = data.get("save", False)
                poison_target = data.get("poison_target")
        except (json.JSONDecodeError, KeyError):
            pass

        # Handle witch special case
        if self.role == "Witch":
            return self._handle_witch_action(obs, save, poison_target, reasoning)

        # Find target
        target_id = None
        for p in obs.alive_players:
            if p.name == target_name:
                target_id = p.player_id
                break

        # Determine action type
        if action_type == "wolf_attack":
            atype = ActionType.ATTACK
            self.memory.add_action("wolf_attack", target_name, f"刀{target_name}", reasoning)
        elif action_type == "seer_check":
            atype = ActionType.DIVINE
            self._seer_checks.append({"target": target_name, "day": obs.day})
            self.memory.role_memory.setdefault("check_history", []).append(
                f"D{obs.day}: 查验{target_name}"
            )
            self.memory.add_action("seer_check", target_name, f"查验{target_name}", reasoning)
        elif action_type == "guard_protect":
            atype = ActionType.GUARD
            self._guard_history.append(target_name)
            self.memory.role_memory.setdefault("protection_history", []).append(
                f"D{obs.day}: 守护{target_name}"
            )
            self.memory.add_action("guard_protect", target_name, f"守护{target_name}", reasoning)
        else:
            atype = ActionType.ATTACK

        return Decision(
            actor_id=self.player_id,
            action_type=atype,
            target_id=target_id,
            reasoning=reasoning,
            metadata={"source": "cognitive", "model": "cognitive-agent"},
        )

    def _get_witch_info(self, obs: GameObservation) -> str:
        """Get witch-specific information."""
        lines = []
        if self._witch_save_used:
            lines.append("解药已使用")
        else:
            lines.append("解药可用")

        if self._witch_poison_used:
            lines.append("毒药已使用")
        else:
            lines.append("毒药可用")

        # Check if someone died tonight
        for event in (self.view.private_events if self.view else []):
            payload = event.get("payload", {}) or {}
            if "victim_id" in payload:
                victim_id = payload["victim_id"]
                victim = next((p for p in obs.alive_players if p.player_id == victim_id), None)
                if victim:
                    lines.append(f"今晚被刀的是: {victim.seat}号:{victim.name}")

        return "\n".join(lines)

    def _get_guard_info(self) -> str:
        """Get guard-specific information."""
        if self._guard_history:
            last_protected = self._guard_history[-1]
            return f"上一晚守护的是: {last_protected}\n不能连续两晚守护同一人"
        return "第一晚，可以守护任何人"

    def _handle_witch_action(
        self, obs: GameObservation, save: bool, poison_target: str | None, reasoning: str
    ) -> Decision:
        """Handle witch's save/poison decision."""
        decisions = []

        if save and not self._witch_save_used:
            # Find tonight's victim
            victim_id = None
            for event in (self.view.private_events if self.view else []):
                payload = event.get("payload", {}) or {}
                if "victim_id" in payload:
                    victim_id = payload["victim_id"]
                    break

            if victim_id:
                self._witch_save_used = True
                self.memory.role_memory["save_used"] = True
                self.memory.role_memory.setdefault("saves", []).append(f"D{obs.day}")
                self.memory.add_action("witch_save", None, "使用解药", reasoning)

                return Decision(
                    actor_id=self.player_id,
                    action_type=ActionType.WITCH_SAVE,
                    target_id=victim_id,
                    reasoning=reasoning,
                    metadata={"source": "cognitive", "model": "cognitive-agent"},
                )

        if poison_target and not self._witch_poison_used:
            # Find poison target
            target_id = None
            for p in obs.alive_players:
                if p.name == poison_target:
                    target_id = p.player_id
                    break

            if target_id:
                self._witch_poison_used = True
                self.memory.role_memory["poison_used"] = True
                self.memory.role_memory.setdefault("poisons", []).append(
                    f"D{obs.day}: 毒{poison_target}"
                )
                self.memory.add_action("witch_poison", poison_target, f"毒{poison_target}", reasoning)

                return Decision(
                    actor_id=self.player_id,
                    action_type=ActionType.WITCH_POISON,
                    target_id=target_id,
                    reasoning=reasoning,
                    metadata={"source": "cognitive", "model": "cognitive-agent"},
                )

        # Skip action
        self.memory.add_action("witch_skip", None, "不用药", reasoning)
        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.SKIP,
            reasoning=reasoning,
            metadata={"source": "cognitive", "model": "cognitive-agent"},
        )

    # === Public API (matching Agent protocol) ===

    def day_start(self) -> None:
        """Called when a new day starts."""
        pass

    def talk(self) -> Decision:
        """Generate a speech during the day phase."""
        obs = build_observation(self.view, self.role)
        self.current_observation = obs

        # Observe
        observe_result = self._observe(obs)

        # Think
        think_result = self._think(obs, observe_result)

        # Act
        return self._act_speech(obs, think_result)

    def vote(self) -> Decision:
        """Generate a vote during the voting phase."""
        obs = build_observation(self.view, self.role)
        self.current_observation = obs

        # Observe
        observe_result = self._observe(obs)

        # Think
        think_result = self._think(obs, observe_result)

        # Act
        return self._act_vote(obs, think_result)

    def attack(self) -> Decision:
        """Wolf: choose a kill target at night."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)
        return self._act_night(obs, think_result, "wolf_attack")

    def divine(self) -> Decision:
        """Seer: choose a check target at night."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)
        return self._act_night(obs, think_result, "seer_check")

    def guard(self) -> Decision:
        """Guard: choose a protection target at night."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)
        return self._act_night(obs, think_result, "guard_protect")

    def witch_act(self, victim_id: str | None) -> list[Decision]:
        """Witch: decide to save and/or poison."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)
        decision = self._act_night(obs, think_result, "witch_act")
        return [decision]

    def shoot(self) -> Decision:
        """Hunter: choose a shoot target."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)

        prompt = f"""你是猎人，已经死亡，可以开枪带走一名玩家。

=== 你的分析 ===
{think_result}

=== 可选目标 ===
{', '.join(f'{p.seat}号:{p.name}' for p in obs.alive_players)}

选择你要带走的玩家。输出 JSON：
{{"reasoning": "理由", "target": "玩家名字"}}"""

        result = self._call_llm(prompt, "你是猎人，选择开枪目标。输出JSON。")

        target_name = None
        reasoning = think_result[:100]
        try:
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                data = json.loads(json_match.group())
                target_name = data.get("target", "")
                reasoning = data.get("reasoning", reasoning)
        except (json.JSONDecodeError, KeyError):
            pass

        target_id = None
        for p in obs.alive_players:
            if p.name == target_name:
                target_id = p.player_id
                break

        if not target_id and obs.alive_players:
            target_id = obs.alive_players[0].player_id

        self.memory.add_action("shoot", target_name, f"开枪打{target_name}", reasoning)

        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.SHOOT,
            target_id=target_id,
            reasoning=reasoning,
            metadata={"source": "cognitive", "model": "cognitive-agent"},
        )

    def boom(self) -> Decision:
        """White Wolf King: decide whether to self-destruct."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)

        prompt = f"""你是白狼王，可以在白天自爆带走一名玩家。

=== 你的分析 ===
{think_result}

现在是否要自爆？如果自爆，带走谁？

输出 JSON：
{{"reasoning": "理由", "boom": true/false, "target": "玩家名字或null"}}"""

        result = self._call_llm(prompt, "你是白狼王，决定是否自爆。输出JSON。")

        boom = False
        target_name = None
        reasoning = think_result[:100]
        try:
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                data = json.loads(json_match.group())
                boom = data.get("boom", False)
                target_name = data.get("target")
                reasoning = data.get("reasoning", reasoning)
        except (json.JSONDecodeError, KeyError):
            pass

        if not boom:
            return Decision(
                actor_id=self.player_id,
                action_type=ActionType.SKIP,
                reasoning="不自爆",
                metadata={"source": "cognitive", "model": "cognitive-agent"},
            )

        target_id = None
        for p in obs.alive_players:
            if p.name == target_name:
                target_id = p.player_id
                break

        self.memory.add_action("boom", target_name, f"自爆带走{target_name}", reasoning)

        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.BOOM,
            target_id=target_id,
            reasoning=reasoning,
            metadata={"source": "cognitive", "model": "cognitive-agent"},
        )

    def transfer_badge(self, candidates: list[str]) -> Decision:
        """Transfer sheriff badge on death."""
        obs = build_observation(self.view, self.role)
        observe_result = self._observe(obs)
        think_result = self._think(obs, observe_result)

        candidate_names = []
        for cid in candidates:
            p = next((pp for pp in obs.alive_players if pp.player_id == cid), None)
            if p:
                candidate_names.append(f"{p.seat}号:{p.name}")

        prompt = f"""你已死亡，需要将警徽移交给一名存活玩家。

=== 你的分析 ===
{think_result}

=== 候选人 ===
{', '.join(candidate_names)}

选择警徽继承人。输出 JSON：
{{"reasoning": "理由", "target": "玩家名字"}}"""

        result = self._call_llm(prompt, "选择警徽继承人。输出JSON。")

        target_name = None
        reasoning = think_result[:100]
        try:
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                data = json.loads(json_match.group())
                target_name = data.get("target", "")
                reasoning = data.get("reasoning", reasoning)
        except (json.JSONDecodeError, KeyError):
            pass

        target_id = None
        for cid in candidates:
            p = next((pp for pp in obs.alive_players if pp.player_id == cid), None)
            if p and p.name == target_name:
                target_id = cid
                break

        if not target_id and candidates:
            target_id = candidates[0]

        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.VOTE,
            target_id=target_id,
            reasoning=reasoning,
            metadata={"source": "cognitive", "model": "cognitive-agent"},
        )

    def finish(self, winner: str | None) -> None:
        """Called when the game ends."""
        self.memory.add_round_summary([f"游戏结束，胜者: {winner}"])
