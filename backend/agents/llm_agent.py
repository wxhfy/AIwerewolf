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
        speech_temperature: float = 1.0,
        character: Character | None = None,
    ):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.memory: list[str] = []
        self.rng = Random(seed)
        self.temperature = temperature
        self.speech_temperature = speech_temperature
        self.provider = provider
        self.client = create_client(provider=self.provider, model=model)
        # DeepSeek-v4-flash uses built-in chain-of-thought; combined with
        # 600-1000 token responses this can take 8–20s end-to-end, and on
        # slow links the second attempt is another 8s on top. 120s gives
        # the retry chain enough headroom to never time out under normal
        # conditions; the engine's snapshot drain runs in parallel so the
        # UI stays responsive while we wait.
        self.client.timeout = 120.0
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
        view = self._view()
        # Count today's public speeches in the current phase so the first
        # speaker doesn't fabricate accusations against people who haven't
        # said anything yet. "前言不搭后语" came from this exact gap.
        today_chat_count = sum(
            1 for e in view.public_events
            if e.get("day") == view.day
            and e.get("type") == "CHAT_MESSAGE"
            and e.get("phase") == view.phase
        )
        is_first_speaker = today_chat_count == 0
        # Last words are spoken by a just-eliminated player; they don't have a
        # turn to pass and aren't supposed to invite the next speaker, since
        # the floor goes back to the moderator after they finish. Without this
        # branch the LLM kept tacking on "接下来有请@X号:名字 发言" because the
        # generic speech template encourages floor handoff.
        is_last_words = view.phase == "DAY_LAST_WORDS"

        # Build speak order awareness (wolfcha-style)
        today_speakers = [
            self._format_player_tag(self._player_by_id(e.get("actor_id")))
            for e in view.public_events
            if e.get("day") == view.day
            and e.get("type") == "CHAT_MESSAGE"
            and e.get("phase") == view.phase
        ]
        yet_to_speak = [
            self._format_player_tag(p) for p in view.players
            if p["alive"] and p["id"] != self.player_id
            and self._format_player_tag(p) not in today_speakers
        ]

        speak_order_hint = ""
        if is_last_words:
            pass  # handled by instructions below
        elif is_first_speaker:
            speak_order_hint = "你是本轮第一个发言的人，没有人已经说过话，你可以先给出初步印象。"
        elif yet_to_speak:
            spoken_str = "、".join(today_speakers[-6:]) if today_speakers else "(无人)"
            pending_str = "、".join(yet_to_speak[:6])
            speak_order_hint = (
                f"已有发言：{spoken_str}。尚未发言：{pending_str}。"
                "你可以回应前人的观点，或补充他们没提到的角度。"
            )

        # Build perspective hints (wolfcha-style focus angle)
        perspective_hints = self._build_perspective_hints()

        if is_last_words:
            instructions = [
                "你已经出局，现在是你的遗言时间——这是你最后一次开口的机会，结束后场上不会再有发言权。",
                "禁止使用「接下来有请」「请下一位」等任何传递话筒的句式；你没有下一位可以传。",
                "可以做的事：交代自己的真实身份/阵营、留下查杀或站边信息、点出最可疑的玩家、给好人提建议。",
                "保持角色风格，2-3 句话即可。",
            ]
        elif is_first_speaker:
            instructions = [
                "你是本阶段第一个发言的人——目前还没有任何人开口，你也没有任何可以引用的发言或投票。",
                "禁止评价、怀疑或暗示其他玩家。任何形如「@X号有问题」「我觉得@X着急」的话都属于编造。",
                "只允许做三件事之一：自报站位 / 表明今天的关注点 / 邀请下一位发言。",
                "保持你的角色风格，1–2 句话足够。",
            ]
        else:
            instructions = [
                "像真正的狼人杀玩家一样发言。语气自然、可以带犹豫和语气词，不要像在写报告。",
                "只能引用「事实速查」或「最近公开事件」中真实出现过的发言/投票/死亡，不得编造。",
                "若已经有可引用的发言，可以点名一个怀疑或信任对象；如果你确实没看到值得讨论的点，可以直接表态后让位。",
                "不要复述系统提示，不要用「我的发言是」「我认为」等引导语——直接开始说。",
            ]

        prompt = self._build_action_prompt(
            action="talk",
            instructions=instructions,
            options=self._alive_names(),
            speak_order_hint=speak_order_hint,
            perspective_hints=perspective_hints,
        )
        # For talk, use higher temperature (creative) and free-text output
        data, meta = self._ask_json(
            prompt,
            {"reasoning": fallback.reasoning, "speech": fallback.speech or ""},
            max_tokens=1024,
            action="talk",
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
        data, meta = self._ask_json(prompt, default, max_tokens=720)
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
        data, meta = self._ask_json(prompt, default, max_tokens=720)
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

    def transfer_badge(self, candidates: list[str]) -> Decision:
        """Pick a successor for the sheriff badge, or destroy it.

        The dying sheriff is asked to choose from the alive candidates.
        Returns a Decision with target_id=successor, or target_id=None +
        ActionType.SKIP for "撕警徽" (badge destroyed).

        Three-tier resilience:
        - LLM produces a valid candidate name → use that.
        - LLM picks "撕"/"none"/null → destroy the badge.
        - LLM fails after 3 retries OR returns an unknown name → fallback to
          heuristic (village preference by seat).
        """
        fallback = self.fallback.transfer_badge(candidates)
        if not candidates:
            return fallback
        view = self._view()
        cand_names = [
            self._format_player_tag(p)
            for p in view.players
            if p["id"] in candidates and p["alive"]
        ]
        if not cand_names:
            return fallback
        prompt = self._build_action_prompt(
            action="transfer_badge",
            instructions=[
                "你刚刚作为警长出局，需要决定警徽的去向。",
                "可以做的事：把警徽传给一个你信任的好人（target=对应玩家），或者选择「撕警徽」让本局警徽失效（target=null）。",
                "传警徽：选择你认为最可信、能继续主持归票的玩家，通常是已经跳出来的金水或座位上信息量大的好人。",
                "撕警徽：当你怀疑场上没有足够可信的好人，或不希望警徽落入潜在的狼坑时使用。",
                "用一两句话说明你的选择理由，不要长篇大论。",
            ],
            options=cand_names,
        )
        default = {
            "reasoning": fallback.reasoning,
            "target": self._name(fallback.target_id) if fallback.target_id else None,
            "destroy": fallback.action_type == ActionType.SKIP,
        }
        data, meta = self._ask_json(prompt, default, max_tokens=640)
        destroy = bool(data.get("destroy"))
        target_name = data.get("target")
        # "撕"/"none" / null all mean destroy the badge.
        if destroy or not target_name or str(target_name).strip().lower() in {"none", "null", "撕", "撕警徽"}:
            return Decision(
                self.player_id,
                ActionType.SKIP,
                reasoning=str(data.get("reasoning") or fallback.reasoning),
                metadata=meta,
            )
        target_id = self._id_from_name(target_name)
        if target_id not in candidates:
            # LLM hallucinated a name not on the candidate list — fall back.
            return Decision(
                fallback.actor_id,
                fallback.action_type,
                target_id=fallback.target_id,
                reasoning=fallback.reasoning,
                metadata=meta,
            )
        return Decision(
            self.player_id,
            ActionType.VOTE,
            target_id=target_id,
            reasoning=str(data.get("reasoning") or fallback.reasoning),
            metadata=meta,
        )

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
        data, meta = self._ask_json(prompt, default, max_tokens=640)
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
        speak_order_hint: str = "",
        perspective_hints: str = "",
    ) -> str:
        """Build layered prompt: RULES → STATE → FACT SHEET → OBSERVATIONS → STRATEGY → FORMAT.

        The fact sheet is a structured digest of what actually happened — every
        chat / vote / death the agent can legitimately see. Without it the LLM
        tends to hallucinate events ("X 被刀我救了他", "Y 投了 Z"), especially
        when the raw event log gets long.
        """
        view = self._view()
        profile = ROLE_PROFILES.get(self.role, ROLE_PROFILES[Role.VILLAGER])
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

        # Build today's transcript (wolfcha-style) for speak order awareness
        today_transcript = self._build_today_transcript()

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
        ]

        # Add today's transcript (wolfcha-style)
        if today_transcript:
            blocks.extend(["", "=== 今日发言记录 ===", *today_transcript])

        # Add speak order hint
        if speak_order_hint:
            blocks.extend(["", "=== 发言顺序 ===", speak_order_hint])

        # Add perspective hints
        if perspective_hints:
            blocks.extend(["", "=== 本轮关注角度 ===", perspective_hints])

        blocks.extend([
            "",
            "=== 最近公开事件原始日志 ===",
        ])
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

    def _player_by_id(self, player_id: str | None) -> dict[str, Any] | None:
        """Find a player dict by id from the current view."""
        if not player_id:
            return None
        for p in self._view().players:
            if p["id"] == player_id:
                return p
        return None

    def _build_today_transcript(self) -> list[str]:
        """Build today's speech transcript (wolfcha-style)."""
        view = self._view()
        today_chats = [
            e for e in view.public_events
            if e.get("day") == view.day
            and e.get("type") == "CHAT_MESSAGE"
            and e.get("phase") == view.phase
        ]
        if not today_chats:
            return []

        lines: list[str] = []
        for e in today_chats[-10:]:
            actor_id = e.get("actor_id") or ""
            payload = e.get("payload", {}) or {}
            speech_text = (payload.get("speech") or "").strip()
            if not speech_text:
                continue
            tag = self._format_player_tag(self._player_by_id(actor_id) or {"seat": "?", "name": actor_id})
            truncated = speech_text[:120].replace("\n", " ")
            lines.append(f"  {tag}：{truncated}")
        return lines

    def _build_perspective_hints(self) -> str:
        """Generate unique analytical angles for each player (wolfcha-style focus angle).

        Returns a string with 1-2 specific hints so every player doesn't say the
        same thing. Uses seat number and day as seeds for deterministic variation.
        """
        view = self._view()
        seat = int(view.self_player.get("seat", 0))
        day = view.day
        hints: list[str] = []

        # Check if this player was mentioned by others
        for e in view.public_events:
            if e.get("type") == "CHAT_MESSAGE" and e.get("day") == day:
                payload = e.get("payload", {}) or {}
                speech = str(payload.get("speech", ""))
                if f"@{seat}号" in speech or f"{seat}号" in speech:
                    mentioner_id = e.get("actor_id") or ""
                    mentioner = self._player_by_id(mentioner_id)
                    if mentioner:
                        hints.append(f"玩家 {self._format_player_tag(mentioner)} 提到了你，可以考虑回应。")
                    break

        # Adjacent to dead player
        dead_seats = [int(p.get("seat", -1)) for p in view.players if not p["alive"]]
        if any(abs(seat - ds) == 1 or abs(seat - ds) == len(view.players) - 1 for ds in dead_seats if ds > 0):
            hints.append("你坐在一位已出局玩家的旁边，可以评论这个位置的局势。")

        # Sheriff angle
        is_sheriff = view.self_player.get("is_sheriff", False) or view.self_player.get("badge")
        if is_sheriff:
            hints.append("你是警长，发言有影响力。可以给归票方向。")
        elif seat % 2 == view.day % 2:
            hints.append("关注警长的归票，看是否合理。")
        else:
            hints.append("警长的发言是否让你信服？可以表态。")

        # Voting pattern (day 2+)
        if day >= 2:
            hints.append(f"回顾昨天的投票和发言，看有没有人前后不一致。")

        # Select at most 2 hints deterministically
        selected = []
        for i, h in enumerate(hints):
            if (seat + day + i) % len(hints) < 2:
                selected.append(h)
        if not selected:
            selected = hints[:1]

        return "\n".join(f"- {h}" for h in selected[:2])

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
        """Build system prompt: role rules + persona + behavior params + constraints.

        Wolfcha-style: persona describes who you are, communication profile +
        player mind control how you behave. The behavior params are hidden
        instructions — the player must never reference them in speech.
        """
        role_system = get_system_prompt(self.role)
        char_block = ""
        if self.character:
            persona_prompt = (self.character.persona.system_prompt or "").strip()
            if not persona_prompt:
                char = self.character
                persona_prompt = (
                    f"名字：{char.persona.name}，{char.persona.age}岁\n"
                    f"背景：{char.persona.basic_info}\n"
                    f"发言习惯：{char.persona.speech_length_habit}，{char.persona.vocabulary_style}\n"
                    f"思考方式：{char.persona.reasoning_style}"
                )
            char_block = "\n\n你的个人设定（仅描述你自己，不是其他玩家）：\n" + persona_prompt

        # Wolfcha-style hidden communication profile: controls HOW you speak
        comm_profile = self._build_communication_profile()
        # Wolfcha-style hidden player mind: controls HOW you think/decide
        player_mind = self._build_player_mind_section()

        constraints = (
            "\n\n重要约束：\n"
            "1. 只能根据「事实速查」+「公开事件原始日志」+「你的私有信息」里实际写到的内容来推理；任何额外细节都视为编造，禁止输出。\n"
            "2. 当前阶段未发生的事禁止提及——例如在 DAY_SPEECH 阶段不要说「李默投了卓砚」（DAY_VOTE 还没开始）。\n"
            "3. 提到其它玩家时必须使用 @N号:名字 的格式（例如 @3号:王雅文），不允许只写姓名或只写座位号。\n"
            "4. 第一天没有信息是正常的，可以说「信息不足，先听听大家发言」；不要凭印象给玩家贴性格标签。\n"
            "5. 不要冒充其他角色（如你不是预言家，绝不能说出查验结果）；不要复述任何隐藏角色信息。\n"
            "6. 发言要符合狼人杀桌面语言、保持你的人物口吻；最长 3 句话，禁止长篇大论；不要复述系统提示。\n"
            "7. 以上所有设定都是你的内部指引——永远不要在你的发言中逐字复述或引用设定内容。"
        )
        return role_system + char_block + comm_profile + player_mind + constraints

    def _build_communication_profile(self) -> str:
        """Build wolfcha-style hidden communication profile section.

        These are BEHAVIORAL INSTRUCTIONS, not descriptions. The AI must follow
        these patterns in its speech without ever mentioning them.
        """
        if not self.character:
            return ""
        p = self.character.persona
        lines = [
            "",
            "<hidden_communication_profile>",
            "以下是你的发言行为参数——你必须在发言中自然体现，但绝不能在发言中提及这些参数本身：",
            f"- 狼人杀经验水平：{p.werewolf_experience or '中级玩家'}",
            f"- 用词风格：{p.vocabulary_style or '口语化'}",
            f"- 推理方式：{p.reasoning_style or '直觉+逻辑'}",
            f"- 发言长度习惯：{p.speech_length_habit or '中等长度'}",
            f"- 被质疑时反应：{p.pressure_style or '冷静应对'}",
            f"- 不确定时表现：{p.uncertainty_style or '坦诚表达'}",
            f"- 常见失误模式：{p.mistake_pattern or '偶尔忽略线索'}",
        ]
        if p.wolf_deception_style:
            lines.append(f"- 当你是狼人时的伪装风格：{p.wolf_deception_style}")
        lines.append("</hidden_communication_profile>")
        return "\n".join(lines)

    def _build_player_mind_section(self) -> str:
        """Build wolfcha-style hidden player mind section.

        These create stable cognitive biases that affect decision-making
        but must never be explicitly stated in character speech.
        """
        if not self.character:
            return ""
        m = self.character.mind
        courage_map = {
            "bold": "敢正面质疑他人，不畏惧对立",
            "cautious": "谨慎站边，为避免过早暴露立场而保持模糊",
            "calculated": "只在把握较大时才明确表态",
        }
        memory_map = {
            "first_impression": "第一印象对你影响很大，后面很难改观",
            "recent": "最近发生的事情对你影响最大，容易忘记前几天的事",
            "selective": "你只记住与你观点一致的事，忽略反例",
            "comprehensive": "你能记住大部分关键事件",
        }
        suspicion_map = {
            "low": "你很容易怀疑别人，一点破绽就能让你锁定目标",
            "medium": "你需要观察到连续可疑行为才会怀疑",
            "high": "你倾向于相信别人，除非证据确凿",
        }
        lines = [
            "",
            "<hidden_player_mind>",
            "以下是你的认知风格参数——它们影响你如何分析和决策，但绝不能在发言中提及：",
            f"- 勇气程度：{courage_map.get(m.courage, m.courage)}",
            f"- 记忆倾向：{memory_map.get(m.memory_bias, m.memory_bias)}",
            f"- 怀疑阈值：{suspicion_map.get(m.suspicion_threshold, m.suspicion_threshold)}",
            f"- 自我保护倾向：{m.self_protection}",
            f"- 分析深度：{m.logic_depth}",
            f"- 桌面存在感：{m.table_presence}",
            "</hidden_player_mind>",
        ]
        return "\n".join(lines)

    def _ask_json(self, prompt: str, default: dict[str, Any], *, max_tokens: int = 640, action: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
        if action == "talk":
            return self._ask_talk(prompt, default, max_tokens=max_tokens)
        return self._ask_json_inner(prompt, default, max_tokens=max_tokens, action=action)

    def _ask_talk(self, prompt: str, default: dict[str, Any], *, max_tokens: int = 640) -> tuple[dict[str, Any], dict[str, Any]]:
        """Handle talk action with free-text output at high temperature."""
        meta = {
            "provider": self.provider,
            "model": self.client.model,
            "source": "fallback",
            "fallback": True,
        }
        try:
            system = self._build_system_prompt()
            # First attempt: free text at speech temperature
            response = self.client.chat_sync(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.speech_temperature,
                max_tokens=max_tokens,
                thinking=False,
            )
            text = self.client.parse_response(response).strip()
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            # Remove common prefixes (model sometimes adds them despite instructions)
            for prefix in ["发言：", "发言:", "我说：", "我说:", "speech：", "speech:"]:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            # Remove surrounding quotes
            if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
                text = text[1:-1].strip()
            # Remove ``` blocks
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

            if text and len(text) >= 2:
                self.last_error = None
                meta["source"] = "llm"
                meta["fallback"] = False
                meta["raw_text"] = text[:400]
                meta["attempts"] = 1
                meta["usage"] = usage
                return {"speech": text, "reasoning": ""}, meta

            # Second attempt: try JSON format (some models prefer structured output)
            json_prompt = prompt + "\n\n输出格式：{\"speech\": \"你的发言\"}"
            response2 = self.client.chat_sync(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json_prompt},
                ],
                temperature=0.8,
                max_tokens=max_tokens,
                thinking=False,
            )
            text2 = self.client.parse_response(response2).strip()
            usage2 = response2.get("usage", {}) if isinstance(response2, dict) else {}
            parsed = self._coerce_json(text2)
            if parsed and parsed.get("speech"):
                self.last_error = None
                meta["source"] = "llm"
                meta["fallback"] = False
                meta["raw_text"] = text2[:400]
                meta["attempts"] = 2
                meta["usage"] = usage2
                return {"speech": str(parsed["speech"]), "reasoning": str(parsed.get("reasoning", ""))}, meta

            self.last_error = "talk_parse_failed"
            meta["error"] = self.last_error
            meta["raw_text"] = text[:400]
            meta["usage"] = usage
            return default, meta
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            meta["error"] = self.last_error
            return default, meta

    def _ask_json_inner(self, prompt: str, default: dict[str, Any], *, max_tokens: int = 640, action: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
        meta = {
            "provider": self.provider,
            "model": self.client.model,
            "source": "fallback",
            "fallback": True,
        }
        try:
            system = self._build_system_prompt()
            # Use high temperature for speech, normal for other actions
            is_talk = (action == "talk")
            base_temp = self.speech_temperature if is_talk else self.temperature
            # Three escalating attempts. For talk, we don't drop temperature as
            # aggressively because we want to preserve natural variation.
            attempts = [
                {
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": base_temp,
                },
                {
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": f"{prompt}\n\n再次强调：请只输出一个合法 JSON 对象，不要输出代码块，不要输出额外解释，不要留空。",
                        },
                    ],
                    "temperature": max(0.4, base_temp - 0.3) if is_talk else 0.2,
                },
                {
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": (
                                f"{prompt}\n\n"
                                "你之前两次都没有输出可解析的 JSON。这一次：\n"
                                "1. 不要思考太久——把回答控制在两三句话以内\n"
                                "2. 直接输出 JSON 对象，第一个字符必须是 '{'\n"
                                "3. 字段值用合法的 JSON 字符串/数字/null，不要省略字段\n"
                            ),
                        },
                    ],
                    "temperature": 0.3 if is_talk else 0.1,
                },
            ]
            last_text = ""
            last_usage: dict[str, Any] = {}
            # Token budgets: 1.0× → 1.5× → 2.5× of the base.
            budget_multipliers = [1.0, 1.5, 2.5]
            for idx, attempt in enumerate(attempts):
                attempt_max = int(max_tokens * budget_multipliers[idx])
                response = self.client.chat_sync(
                    messages=attempt["messages"],
                    temperature=float(attempt["temperature"]),
                    max_tokens=attempt_max,
                    thinking=False,
                )
                text = self.client.parse_response(response).strip()
                last_text = text
                last_usage = response.get("usage", {}) if isinstance(response, dict) else {}
                parsed = self._coerce_json(text)
                if parsed is not None:
                    self.last_error = None
                    meta["source"] = "llm"
                    meta["fallback"] = False
                    meta["raw_text"] = text[:400]
                    meta["attempts"] = idx + 1
                    meta["usage"] = last_usage
                    return parsed, meta
            self.last_error = "json_parse_failed"
            meta["error"] = self.last_error
            meta["raw_text"] = last_text[:400]
            meta["usage"] = last_usage
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
