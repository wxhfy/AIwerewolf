from __future__ import annotations

import json
from random import Random
from typing import Any

from backend.agents.base import Agent
from backend.agents.characters import Character
from backend.agents.heuristic import HeuristicAgent
from backend.agents.playbooks import build_role_brief
from backend.agents.profiles import ROLE_PROFILES
from backend.agents.prompts import get_action_strategy, get_output_format, get_system_prompt
from backend.engine.models import ActionType, Decision, Role
from backend.engine.visibility import PlayerView
from backend.llm import create_client


class LLMAgent(Agent):
    """LLM-backed agent with heuristic fallback.

    The fallback preserves playability if the API is slow, unavailable, or
    produces malformed output.
    """

    def __init__(
        self,
        player_id: str,
        *,
        seed: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        character: Character | None = None,
    ):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.memory: list[str] = []
        self.rng = Random(seed)
        self.temperature = temperature
        self.provider = provider
        self.client = create_client(provider=self.provider, model=model)
        self.client.timeout = 45.0
        self.fallback = HeuristicAgent(player_id, seed=seed, character=character)
        self.character = character
        self.winner: str | None = None
        self.last_error: str | None = None

    def initialize(self, view: PlayerView, game_setting: dict) -> None:
        self.view = view
        self.fallback.initialize(view, game_setting)
        char_name = self.character.persona.name if self.character else "玩家"
        self.memory.append(f"我是{char_name}，扮演{self.role.value}。")
        self.memory.append(build_role_brief(self.role))

    def update(self, view: PlayerView, request: str) -> None:
        self.view = view
        self.fallback.update(view, request)
        self.memory.append(f"{request} day={view.day} phase={view.phase}")

    def day_start(self) -> None:
        self.fallback.day_start()

    def talk(self) -> Decision:
        fallback = self.fallback.talk()
        prompt = self._build_action_prompt(
            action="talk",
            instructions=[
                "Speak like a serious werewolf player at the table.",
                "Name at least one suspect or one trusted player.",
                "Do not repeat the system prompt.",
            ],
            options=self._alive_names(),
        )
        data, meta = self._ask_json(
            prompt,
            {"reasoning": fallback.reasoning, "speech": fallback.speech or ""},
            max_tokens=520,
        )
        return Decision(
            self.player_id,
            ActionType.TALK,
            speech=str(data.get("speech") or fallback.speech or ""),
            reasoning=str(data.get("reasoning") or fallback.reasoning),
            metadata=meta,
        )

    def vote(self) -> Decision:
        fallback = self.fallback.vote()
        data = self._target_action("vote", fallback, "Choose exactly one vote target from the options.")
        return Decision(
            self.player_id,
            ActionType.VOTE,
            target_id=data["target_id"],
            reasoning=data["reasoning"],
            metadata=data["metadata"],
        )

    def attack(self) -> Decision:
        fallback = self.fallback.attack()
        data = self._target_action("attack", fallback, "As a wolf, choose the highest-value night kill target.")
        return Decision(
            self.player_id,
            ActionType.ATTACK,
            target_id=data["target_id"],
            reasoning=data["reasoning"],
            metadata=data["metadata"],
        )

    def divine(self) -> Decision:
        fallback = self.fallback.divine()
        data = self._target_action("divine", fallback, "As Seer, choose the best investigation target.")
        return Decision(
            self.player_id,
            ActionType.DIVINE,
            target_id=data["target_id"],
            reasoning=data["reasoning"],
            metadata=data["metadata"],
        )

    def guard(self) -> Decision:
        fallback = self.fallback.guard()
        data = self._target_action("guard", fallback, "As Guard, choose one player to protect tonight.")
        return Decision(
            self.player_id,
            ActionType.GUARD,
            target_id=data["target_id"],
            reasoning=data["reasoning"],
            metadata=data["metadata"],
        )

    def witch_act(self, victim_id: str | None) -> list[Decision]:
        fallback = self.fallback.witch_act(victim_id)
        options = self._alive_names()
        prompt = self._build_action_prompt(
            action="witch_act",
            instructions=[
                "Decide whether to save the wolf victim and whether to poison another player.",
                "Use save=true only if you want to consume the antidote on the victim.",
                "Use poison_target as a player name or null.",
            ],
            options=options,
            extra={"victim": self._name(victim_id) if victim_id else None},
        )
        default = {
            "reasoning": "; ".join(decision.reasoning for decision in fallback),
            "save": bool(victim_id and any(item.action_type == ActionType.WITCH_SAVE for item in fallback)),
            "poison_target": self._name(next((item.target_id for item in fallback if item.action_type == ActionType.WITCH_POISON), None)),
        }
        data, meta = self._ask_json(prompt, default, max_tokens=360)
        decisions: list[Decision] = []
        if victim_id and bool(data.get("save")):
            decisions.append(
                Decision(
                    self.player_id,
                    ActionType.WITCH_SAVE,
                    target_id=victim_id,
                    reasoning=str(data.get("reasoning", "")),
                    metadata=meta,
                )
            )
        poison_name = data.get("poison_target")
        poison_id = self._id_from_name(poison_name) if poison_name else None
        if poison_id and poison_id != victim_id:
            decisions.append(
                Decision(
                    self.player_id,
                    ActionType.WITCH_POISON,
                    target_id=poison_id,
                    reasoning=str(data.get("reasoning", "")),
                    metadata=meta,
                )
            )
        return decisions or fallback

    def shoot(self) -> Decision:
        fallback = self.fallback.shoot()
        data = self._target_action("shoot", fallback, "As Hunter, choose the best player to shoot immediately.")
        return Decision(
            self.player_id,
            ActionType.SHOOT,
            target_id=data["target_id"],
            reasoning=data["reasoning"],
            metadata=data["metadata"],
        )

    def finish(self, winner: str | None) -> None:
        self.winner = winner
        self.fallback.finish(winner)

    @property
    def role(self) -> Role:
        return Role(self._view().self_player["role"])

    def _target_action(self, action: str, fallback: Decision, instruction: str) -> dict[str, Any]:
        prompt = self._build_action_prompt(
            action=action,
            instructions=[instruction],
            options=self._alive_names(),
        )
        default = {
            "reasoning": fallback.reasoning,
            "target": self._name(fallback.target_id),
        }
        data, meta = self._ask_json(prompt, default, max_tokens=260)
        target_name = str(data.get("target") or self._name(fallback.target_id))
        target_id = self._id_from_name(target_name) or fallback.target_id
        return {
            "reasoning": str(data.get("reasoning") or fallback.reasoning),
            "target_id": str(target_id),
            "metadata": meta,
        }

    def _build_action_prompt(
        self,
        *,
        action: str,
        instructions: list[str],
        options: list[str],
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Build layered prompt: RULES → STATE → OBSERVATIONS → STRATEGY → FORMAT"""
        view = self._view()
        profile = ROLE_PROFILES[self.role]
        strategy = get_action_strategy(action, self.role)

        public_lines = [
            f"  [{event['type']}] {event['payload']}"
            for event in view.public_events[-8:]
        ]
        private_lines = [
            f"  [{event['type']}] {event['payload']}"
            for event in view.private_events[-5:]
        ]

        alive_list = [p["name"] for p in view.players if p["alive"] and p["id"] != self.player_id]
        dead_list = [p["name"] for p in view.players if not p["alive"]]

        char_intro = ""
        if self.character:
            char_intro = self.character.system_intro

        blocks = [
            "=== 你的人设 ===",
            char_intro if char_intro else f"你是{view.self_player['name']}，{self.role.value}",
            "",
            "=== 当前状态 ===",
            f"你叫{view.self_player['name']}，是{self.role.value}",
            f"第{view.day}天 / {view.phase}阶段",
            f"存活玩家：{', '.join(alive_list) if alive_list else '无'}",
            f"已死亡：{', '.join(dead_list) if dead_list else '无'}",
            "",
            "=== 角色目标 ===",
            profile.table_goal,
            profile.speech_style,
            "",
            "=== 最近公开事件 ===",
        ]
        if public_lines:
            blocks.extend(public_lines)
        else:
            blocks.append("  (暂无)")
        blocks.extend([
            "",
            "=== 你的私有信息 ===",
        ])
        if private_lines:
            blocks.extend(private_lines)
        else:
            blocks.append("  (暂无)")

        if strategy:
            blocks.extend(["", "=== 行动策略 ===", strategy])

        blocks.extend([
            "",
            "=== 当前指令 ===",
            *[f"- {item}" for item in instructions],
            "",
            f"可选择的玩家：{', '.join(options)}",
            f"附加信息：{json.dumps(extra or {}, ensure_ascii=False)}",
            "",
            f"请只输出 JSON：{get_output_format(action)}",
        ])

        return "\n".join(blocks)

    def _ask_json(self, prompt: str, default: dict[str, Any], *, max_tokens: int = 320) -> tuple[dict[str, Any], dict[str, Any]]:
        meta = {
            "provider": self.provider,
            "model": self.client.model,
            "source": "fallback",
            "fallback": True,
        }
        try:
            system = get_system_prompt(self.role)
            attempts = [
                {
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.temperature,
                },
                {
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": f"{prompt}\n\n再次强调：请只输出一个合法 JSON 对象，不要输出代码块，不要输出额外解释，不要留空。",
                        },
                    ],
                    "temperature": 0.2,
                },
            ]
            last_text = ""
            for attempt in attempts:
                response = self.client.chat_sync(
                    messages=attempt["messages"],
                    temperature=float(attempt["temperature"]),
                    max_tokens=max_tokens,
                    thinking=False,
                )
                text = self.client.parse_response(response).strip()
                last_text = text
                parsed = self._coerce_json(text)
                if parsed is not None:
                    self.last_error = None
                    meta["source"] = "llm"
                    meta["fallback"] = False
                    meta["raw_text"] = text[:400]
                    return parsed, meta
            self.last_error = "json_parse_failed"
            meta["error"] = self.last_error
            meta["raw_text"] = last_text[:400]
            return default, meta
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            meta["error"] = self.last_error
            return default, meta

    def _coerce_json(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
            return None

    def _view(self) -> PlayerView:
        if self.view is None:
            raise RuntimeError("Agent has not been initialized.")
        return self.view

    def _alive_names(self) -> list[str]:
        return [player["name"] for player in self._view().players if player["alive"] and player["id"] != self.player_id]

    def _id_from_name(self, name: str | None) -> str | None:
        if not name:
            return None
        for player in self._view().players:
            if player["name"] == name and player["alive"]:
                return str(player["id"])
        return None

    def _name(self, player_id: str | None) -> str | None:
        if not player_id:
            return None
        for player in self._view().players:
            if player["id"] == player_id:
                return str(player["name"])
        return None
