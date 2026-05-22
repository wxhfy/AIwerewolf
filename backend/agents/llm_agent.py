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
        self.client.timeout = 12.0
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

    def boom(self) -> Decision:
        fallback = self.fallback.boom()
        if fallback.action_type == ActionType.SKIP:
            default = {"reasoning": fallback.reasoning, "target": None, "boom": False}
        else:
            default = {"reasoning": fallback.reasoning, "target": self._name(fallback.target_id), "boom": True}
        prompt = self._build_action_prompt(
            action="boom",
            instructions=[
                "Decide whether White Wolf King should self-destruct right now.",
                "If you choose not to self-destruct, set boom=false and target=null.",
                "If you choose to self-destruct, choose exactly one target.",
            ],
            options=self._alive_names(),
        )
        data, meta = self._ask_json(prompt, default, max_tokens=260)
        if not bool(data.get("boom")):
            return Decision(self.player_id, ActionType.SKIP, reasoning=str(data.get("reasoning") or fallback.reasoning), metadata=meta)
        target_name = data.get("target")
        target_id = self._id_from_name(target_name) or fallback.target_id
        return Decision(
            self.player_id,
            ActionType.BOOM,
            target_id=target_id,
            reasoning=str(data.get("reasoning") or fallback.reasoning),
            metadata=meta,
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
        """Build layered prompt: RULES → STATE → FACT SHEET → OBSERVATIONS → STRATEGY → FORMAT.

        The fact sheet is a structured digest of what actually happened — every
        chat / vote / death the agent can legitimately see. Without it the LLM
        tends to hallucinate events ("X 被刀我救了他", "Y 投了 Z"), especially
        when the raw event log gets long.
        """
        view = self._view()
        profile = ROLE_PROFILES[self.role]
        strategy = get_action_strategy(action, self.role)

        public_lines = [
            f"  [{event['type']}] {event['payload']}"
            for event in view.public_events[-20:]
        ]
        private_lines = [
            f"  [{event['type']}] {event['payload']}"
            for event in view.private_events[-8:]
        ]

        alive_lines = [self._format_player_tag(p) for p in view.players if p["alive"]]
        dead_lines = [self._format_player_tag(p) for p in view.players if not p["alive"]]

        fact_sheet = self._build_fact_sheet()

        blocks = [
            "=== 当前状态 ===",
            f"你是 {self._format_player_tag(view.self_player)}，扮演 {self.role.value}",
            f"第{view.day}天 / {view.phase}阶段",
            f"存活玩家：{'，'.join(alive_lines) if alive_lines else '无'}",
            f"已死亡：{'，'.join(dead_lines) if dead_lines else '无'}",
            "",
            "=== 角色目标 ===",
            profile.table_goal,
            profile.speech_style,
            "",
            "=== 已发生事实速查（这是你能信任的全部桌面信息） ===",
            *fact_sheet,
            "",
            "=== 最近公开事件原始日志 ===",
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
            "=== 反幻觉硬性纪律 ===",
            "- 严禁编造未在「事实速查」或「最近公开事件」里出现的内容；如果不确定，宁可说「我没听到」也不要瞎编。",
            "- 不要谈论「投票阶段还没发生」的票；当前若是 DAY_SPEECH，你尚未看到任何今日的 VOTE_CAST。",
            "- 提到任何其他玩家时，必须写成 @N号:名字 的形式（例如 @3号:王雅文）。",
            "- 不要假装自己是其他角色；只引用你私有信息里真实拥有的查验结果 / 守护目标 / 药水使用。",
            "- 发言不要超过 3 句话；保持你的角色风格。",
            "",
            f"请只输出 JSON：{get_output_format(action)}",
        ])

        return "\n".join(blocks)

    @staticmethod
    def _format_player_tag(player: dict[str, Any]) -> str:
        seat = player.get("seat", "?")
        name = player.get("name", "?")
        return f"@{seat}号:{name}"

    def _build_fact_sheet(self) -> list[str]:
        """Distil the public event log into a deduped, day-grouped digest.

        Each bullet quotes a single concrete fact: a death, a vote target, a
        seer/witch claim word-for-word, a sheriff election outcome. The LLM
        treats this as ground truth so it stops inventing parallel timelines.
        """
        view = self._view()
        events = view.public_events
        if not events:
            return ["  (尚无公开信息)"]

        deaths: list[str] = []
        votes: dict[int, list[str]] = {}
        speeches: list[str] = []
        sheriff_lines: list[str] = []

        for event in events:
            etype = event.get("type")
            payload = event.get("payload", {}) or {}
            day = event.get("day", 0)
            if etype == "PLAYER_DIED":
                deaths.append(
                    f"第{day}天 {self._tag_from_payload(payload, 'player')} 出局（原因：{payload.get('reason', '?')}）"
                )
            elif etype == "VOTE_CAST":
                tag = (
                    f"{self._tag_from_payload(payload, 'voter')} → "
                    f"{self._tag_from_payload(payload, 'target')}"
                )
                votes.setdefault(day, []).append(tag)
            elif etype == "CHAT_MESSAGE":
                actor = self._tag_from_payload(payload, 'actor')
                speech = (payload.get("speech") or "").strip()
                if not speech:
                    continue
                truncated = speech[:80].replace("\n", " ")
                tag = ""
                if payload.get("last_words"):
                    tag = "[遗言]"
                elif payload.get("badge_campaign"):
                    tag = "[警上]"
                elif payload.get("pk_speech"):
                    tag = "[PK]"
                speeches.append(f"第{day}天{tag} {actor}：{truncated}")
            elif etype == "SYSTEM_MESSAGE":
                msg = payload.get("message") or ""
                if "sheriff" in msg or "警徽" in msg or "badge" in msg.lower():
                    sheriff_lines.append(f"第{day}天 系统：{msg}")
                elif "died" in msg.lower() or "出局" in msg or "deaths" in msg.lower():
                    sheriff_lines.append(f"第{day}天 系统：{msg}")

        lines: list[str] = []
        if sheriff_lines:
            lines.extend(f"  · {item}" for item in sheriff_lines[-6:])
        if deaths:
            lines.extend(f"  · {item}" for item in deaths[-6:])
        if votes:
            for day in sorted(votes.keys())[-2:]:
                joined = "；".join(votes[day][-10:])
                lines.append(f"  · 第{day}天投票：{joined}")
        if speeches:
            lines.extend(f"  · {item}" for item in speeches[-10:])

        if not lines:
            lines.append("  · 暂无可信事实，发言时请明确说「目前信息不足」。")
        return lines

    def _tag_from_payload(self, payload: dict[str, Any], prefix: str) -> str:
        """Format @N号:名字 from {prefix}_id (preferred) or {prefix}_name fallback.

        Looks up seat through self.view.players so the @N号 tag is always
        consistent with what the engine considers authoritative.
        """
        player_id = payload.get(f"{prefix}_id") or payload.get(prefix)
        if player_id:
            tagged = self._name(player_id)
            if tagged:
                return tagged
        name = payload.get(f"{prefix}_name") or payload.get(prefix) or "?"
        # Try to look up by name when id isn't there (some payloads only carry name).
        if self.view:
            for player in self.view.players:
                if player.get("name") == name:
                    return self._format_player_tag(player)
        return f"@{name}"

    def _build_system_prompt(self) -> str:
        """Build system prompt: role rules + persona system prompt + constraints.

        Persona-level guidance comes from the persona's pre-built system
        prompt (cached on the Persona dataclass / DB row) so the LLM gets a
        coherent character brief in one block instead of a flat field dump.
        """
        role_system = get_system_prompt(self.role)
        char_block = ""
        if self.character:
            persona_prompt = (self.character.persona.system_prompt or "").strip()
            if not persona_prompt:
                # Defensive fallback for personas loaded before the prompt
                # field existed.
                char = self.character
                persona_prompt = (
                    f"名字：{char.persona.name}，{char.persona.age}岁\n"
                    f"背景：{char.persona.basic_info}\n"
                    f"发言习惯：{char.persona.speech_length_habit}，{char.persona.vocabulary_style}\n"
                    f"思考方式：{char.persona.reasoning_style}"
                )
            char_block = "\n\n你的个人设定（仅描述你自己，不是其他玩家）：\n" + persona_prompt
        constraints = (
            "\n\n重要约束：\n"
            "1. 只能根据「事实速查」+「公开事件原始日志」+「你的私有信息」里实际写到的内容来推理；任何额外细节都视为编造，禁止输出。\n"
            "2. 当前阶段未发生的事禁止提及——例如在 DAY_SPEECH 阶段不要说「李默投了卓砚」（DAY_VOTE 还没开始）。\n"
            "3. 提到其它玩家时必须使用 @N号:名字 的格式（例如 @3号:王雅文），不允许只写姓名或只写座位号。\n"
            "4. 第一天没有信息是正常的，可以说「信息不足，先听听大家发言」；不要凭印象给玩家贴性格标签。\n"
            "5. 不要冒充其他角色（如你不是预言家，绝不能说出查验结果）；不要复述任何隐藏角色信息。\n"
            "6. 发言要符合狼人杀桌面语言、保持你的人物口吻；最长 3 句话，禁止长篇大论；不要复述系统提示。"
        )
        return role_system + char_block + constraints

    def _ask_json(self, prompt: str, default: dict[str, Any], *, max_tokens: int = 320) -> tuple[dict[str, Any], dict[str, Any]]:
        meta = {
            "provider": self.provider,
            "model": self.client.model,
            "source": "fallback",
            "fallback": True,
        }
        try:
            system = self._build_system_prompt()
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
        """Return alive opponents tagged @N号:名字 so the LLM is forced to pick by callout."""
        return [
            self._format_player_tag(player)
            for player in self._view().players
            if player["alive"] and player["id"] != self.player_id
        ]

    def _id_from_name(self, name: str | None) -> str | None:
        """Resolve a player id from either @N号:名字, a bare name, or a seat."""
        if not name:
            return None
        token = str(name).strip()
        # Strip @ prefix and seat tag if present: "@3号:王雅文" → name=王雅文, seat=3.
        seat: int | None = None
        if token.startswith("@"):
            token = token[1:]
        if "号:" in token:
            seat_part, name_part = token.split("号:", 1)
            try:
                seat = int(seat_part.strip())
            except ValueError:
                seat = None
            token = name_part.strip()
        elif "号" in token and token.split("号", 1)[0].strip().isdigit():
            seat_part, rest = token.split("号", 1)
            try:
                seat = int(seat_part.strip())
            except ValueError:
                seat = None
            token = rest.strip(":： ")
        for player in self._view().players:
            if not player["alive"]:
                continue
            if seat is not None and int(player.get("seat", -1)) == seat:
                return str(player["id"])
            if token and player["name"] == token:
                return str(player["id"])
        return None

    def _name(self, player_id: str | None) -> str | None:
        """Return @N号:名字 for a player id so prompts/fallbacks stay consistent."""
        if not player_id:
            return None
        for player in self._view().players:
            if player["id"] == player_id:
                return self._format_player_tag(player)
        return None
