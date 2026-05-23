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
        speech_temperature: float = 1.1,
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
        today_chat_count = sum(
            1 for e in view.public_events
            if e.get("day") == view.day
            and e.get("type") == "CHAT_MESSAGE"
            and e.get("phase") == view.phase
        )
        is_first_speaker = today_chat_count == 0
        is_last_words = view.phase == "DAY_LAST_WORDS"

        # --- Wolfcha-style system prompt parts ---
        system_parts = self._build_talk_system_parts(is_last_words)

        # --- Wolfcha-style game context ---
        game_context = self._build_game_context()

        # --- Today's transcript ---
        today_transcript = self._build_today_transcript()

        # --- Self speech ---
        self_speech = self._build_self_speech()

        # --- Speak order hint (wolfcha exact phrasing) ---
        speak_order_hint = self._build_speak_order_hint(is_first_speaker, is_last_words)

        # --- Phase hint ---
        phase_hint = self._build_phase_hint()

        # --- Focus angle (wolfcha exact phrasing) ---
        focus_angle = self._build_perspective_hints_xml()

        # --- User prompt assembly (wolfcha format) ---
        user_prompt_parts = [game_context]
        if today_transcript:
            user_prompt_parts.append("【本日讨论记录】\n" + today_transcript)
        else:
            user_prompt_parts.append(f"【本日讨论记录】\n（暂无，你是第{speak_order_hint.split('个')[0] if '第' in speak_order_hint else '?'}个发言）")
        user_prompt_parts.append("【你本日已说过的话】\n" + (self_speech or "（无）"))
        if phase_hint:
            user_prompt_parts.append(phase_hint)
        user_prompt_parts.append("【发言顺序】\n" + speak_order_hint)
        user_prompt_parts.append("\n轮到你发言，返回JSON数组：")

        full_user_prompt = "\n\n".join(user_prompt_parts)

        # --- Call LLM with wolfcha-style prompt ---
        speech, meta = self._ask_talk_wolfcha(
            system_parts=system_parts,
            user_prompt=full_user_prompt,
            focus_angle=focus_angle,
            fallback_speech=fallback.speech or "",
            max_tokens=1024,
        )
        return Decision(
            self.player_id,
            ActionType.TALK,
            speech=speech,
            reasoning="",
            metadata=meta,
        )

    # ============================================================
    # Wolfcha-style talk prompt builders
    # ============================================================

    def _build_talk_system_parts(self, is_last_words: bool) -> list[dict]:
        """Build wolfcha-style system prompt parts (identity + task + focus + guidelines)."""
        view = self._view()
        p = self.character.persona if self.character else None
        seat = view.self_player.get("seat", "?")
        name = view.self_player.get("name", "?")

        # Part 1: Base identity (wolfcha: prompts.daySpeech.base)
        win_cond = self._build_win_condition()
        persona_text = self._build_persona_section()
        base = (
            f"【身份】\n你是 {seat}号「{name}」\n身份: {self.role.value}\n\n"
            f"【场景】\n这是一个线上狼人杀游戏，玩家通过打字交流。\n\n"
            f"{win_cond}\n\n{persona_text}"
        )

        # Part 2: Task section (wolfcha: prompts.daySpeech.task.section)
        if is_last_words:
            task_line = "你已经出局，现在发表遗言。"
            campaign_req = ""
        else:
            task_line = "现在是白天讨论。请根据当前局势，自主决定这次发言想达到什么效果。"
            campaign_req = ""
        task = (
            "【当前处境】\n"
            "你正在参与一局实时狼人杀。你不是旁观解说，也不是裁判。\n"
            "你只知道自己视角内的信息。你有自己的性格、记忆、阵营目标和当下压力。\n"
            f"现在轮到你发言。{task_line}\n{campaign_req}"
        )

        # Part 3: Guidelines (wolfcha: prompts.daySpeech.guidelines.default)
        guidelines = (
            "【底线规则】\n"
            "- 只基于本局实际信息发言，严禁编造不存在的发言、投票、查验或死亡。\n"
            "- 只讨论当前存活玩家；涉及已出局玩家时只引用公开事实。\n"
            "- 第一个发言不要引用「前面」的话。\n"
            "- 时间线约束：昨夜刀口在今天白天发言前已确定，禁止把今天的上警/跳身份/发言当作昨夜被刀的直接原因。\n"
            "- 用「X号」称呼玩家。\n"
            "- 严禁职业相关类比、行业术语和场外经历，只说狼人杀桌上的话。\n"
            "\n"
            "【发言方式】\n"
            "你可以坦诚、含糊、试探、反驳、带节奏、保护别人、隐藏信息，或者暂时保留判断。\n"
            "你的发言不需要覆盖所有玩家，也不需要显得完美。\n"
            "只说你此刻会在桌上说的话。\n"
            "可以只说一句，也可以分成几条消息；如果你的玩家心智适合，偶尔可以有很短的反应、小动作或 emoji，但不要每轮都装饰。\n"
            "\n"
            "【输出格式】\n"
            "返回 JSON 字符串数组，每个元素是一条消息气泡。"
        )

        return [
            {"text": base, "cacheable": True},
            {"text": task, "cacheable": False},
            {"text": guidelines, "cacheable": True},
        ]

    def _build_game_context(self) -> str:
        """Build wolfcha-style YAML game context."""
        view = self._view()
        seat = view.self_player.get("seat", "?")
        name = view.self_player.get("name", "?")
        total_seats = len(view.players)
        day = view.day

        # Phase text
        phase_map = {
            "DAY_SPEECH": "白天 自由发言",
            "DAY_LAST_WORDS": "白天 遗言",
            "DAY_BADGE_SPEECH": "白天 警徽竞选发言",
            "DAY_PK_SPEECH": "白天 警徽PK发言",
            "NIGHT_START": "夜晚",
        }
        phase_text = phase_map.get(view.phase, view.phase)

        # Alive players list
        alive_players = [p for p in view.players if p["alive"]]
        alive_lines = [f"  {p.get('seat', '?')}号 {p.get('name', '?')}" for p in alive_players]
        alive_list = "\n".join(alive_lines)

        # Dead players list
        dead_players = [p for p in view.players if not p["alive"]]
        dead_lines = []
        for p in dead_players:
            dead_seat = p.get("seat", "?")
            dead_name = p.get("name", "?")
            # Try to find death cause from events
            cause = "死亡"
            for e in view.public_events:
                if e.get("type") == "PLAYER_DIED":
                    payload = e.get("payload", {}) or {}
                    if payload.get("player_id") == p["id"]:
                        reason = payload.get("reason", "")
                        if "vote" in reason.lower() or "投票" in reason:
                            cause = "投票处决"
                        elif "wolf" in reason.lower() or "狼" in reason:
                            cause = "狼人杀死"
                        elif "poison" in reason.lower() or "毒" in reason:
                            cause = "女巫毒死"
                        elif "hunter" in reason.lower() or "猎人" in reason:
                            cause = "猎人开枪"
                        break
            dead_lines.append(f"  {dead_seat}号 {dead_name} ({cause})")
        dead_info = "\n".join(dead_lines) if dead_lines else "无"

        # Sheriff
        sheriff_seat = None
        for p in view.players:
            if p.get("badge") or p.get("is_sheriff"):
                sheriff_seat = p.get("seat")
                break
        sheriff_info = f"{sheriff_seat}号" if sheriff_seat else "无"

        # Rules section
        rules = (
            "【规则提醒】\n"
            "- 阶段顺序：夜晚（狼人刀人）→ 天亮公布死亡 → 自由发言 → 投票。\n"
            "- 狼人出刀可选择队友或自己（允许自刀），后续判断请考虑此可能。\n"
            "- 时间线提醒：昨夜刀口在今天白天开始前已锁定；不要把今天的发言当作昨夜被刀的原因。"
        )

        # History: past transcripts (simplified from events)
        history_lines = ["【历史】"]
        past_days = set()
        for e in view.public_events:
            eday = e.get("day", 0)
            if eday < day and eday not in past_days and e.get("type") == "CHAT_MESSAGE":
                past_days.add(eday)
                payload = e.get("payload", {}) or {}
                speech = (payload.get("speech") or "")[:80]
                if speech:
                    history_lines.append(f"  第{eday}天 {payload.get('actor_name', '?')}：{speech}")
        for e in view.public_events:
            eday = e.get("day", 0)
            if eday < day and e.get("type") == "PLAYER_DIED":
                payload = e.get("payload", {}) or {}
                history_lines.append(f"  第{eday}天 {payload.get('player_name', '?')} 出局")

        # Vote history
        vote_lines = ["【历史投票】"]
        votes_by_day: dict[int, list[str]] = {}
        for e in view.public_events:
            if e.get("type") == "VOTE_CAST":
                eday = e.get("day", 0)
                if eday < day:
                    payload = e.get("payload", {}) or {}
                    voter = payload.get("voter_name", "?")
                    target = payload.get("target_name", "?")
                    votes_by_day.setdefault(eday, []).append(f"{voter}→{target}")
        for vday, votes in sorted(votes_by_day.items()):
            vote_lines.append(f"  第{vday}天投票: {'; '.join(votes[-10:])}")

        # Role-specific private info
        role_info = self._build_role_private_info()

        # Assemble context
        context = (
            f"【当前局势】\n"
            f"第{day}天 {phase_text}\n"
            f"有效座位号范围: 1号-{total_seats}号（共{total_seats}人）\n"
            f"存活玩家:\n{alive_list}\n"
            f"\n"
            f"【出局玩家】\n{dead_info}\n"
            f"\n"
            f"警长: {sheriff_info}\n"
        )
        if role_info:
            context += f"\n{role_info}\n"
        context += f"\n{rules}\n"

        if len(history_lines) > 1:
            context += "\n" + "\n".join(history_lines)
        if len(vote_lines) > 1:
            context += "\n" + "\n".join(vote_lines)

        context += "\n【提醒】发言重点放在存活玩家，可引用死亡原因作为推理依据，但不要过度复盘已出局玩家。"

        return context

    def _build_role_private_info(self) -> str:
        """Build role-specific private info section."""
        view = self._view()
        private = view.private_events
        if not private:
            return ""
        # Seer checks
        seer_checks = []
        for e in private:
            if e.get("type") == "SEER_CHECK":
                payload = e.get("payload", {}) or {}
                eday = e.get("day", 0)
                target = payload.get("target_name", "?")
                result = "狼人" if payload.get("is_wolf") else "好人"
                seer_checks.append(f"第{eday}夜: {target} - {result}")
        if seer_checks:
            return "【查验记录】\n" + "\n".join(seer_checks)
        # Witch potions
        if any(e.get("type") in ("WITCH_SAVE", "WITCH_POISON") for e in private):
            lines = ["【药水状态】"]
            save_used = any(e.get("type") == "WITCH_SAVE" for e in private)
            poison_used = any(e.get("type") == "WITCH_POISON" for e in private)
            lines.append(f"解药: {'已使用' if save_used else '可用'}")
            lines.append(f"毒药: {'已使用' if poison_used else '可用'}")
            for e in private:
                if e.get("type") == "WITCH_SAVE":
                    lines.append(f"你用解药救了 {e.get('payload', {}).get('target_name', '?')}")
                if e.get("type") == "WITCH_POISON":
                    lines.append(f"你用毒药毒了 {e.get('payload', {}).get('target_name', '?')}")
            return "\n".join(lines)
        return ""

    def _build_win_condition(self) -> str:
        """Wolfcha-style win condition text."""
        view = self._view()
        role = self.role.value
        win_map = {
            "werewolf": "【获胜条件】狼人数量 >= 好人数量 时狼人胜利。",
            "white_wolf_king": "【获胜条件】狼人数量 >= 好人数量 时狼人胜利。你白天可选择自爆带走一名玩家，预言家查验你为狼人。",
            "seer": "【获胜条件】放逐所有狼人时好人胜利。你的查验结果只有你知道。",
            "witch": "【获胜条件】放逐所有狼人时好人胜利。你有一瓶解药和一瓶毒药。",
            "hunter": "【获胜条件】放逐所有狼人时好人胜利。你被投票放逐或被狼人击杀时可以开枪；被女巫毒杀时无法开枪。",
            "guard": "【获胜条件】放逐所有狼人时好人胜利。你每晚可以守护一名玩家，不能连续两晚守护同一人。",
            "villager": "【获胜条件】放逐所有狼人时好人胜利。",
            "idiot": "【获胜条件】放逐所有狼人时好人胜利。你被投票放逐时会翻牌免疫，之后失去投票权。",
        }
        return win_map.get(role, "【获胜条件】放逐所有狼人时好人胜利。")

    def _build_persona_section(self) -> str:
        """Wolfcha-style persona section."""
        if not self.character:
            return ""
        p = self.character.persona
        m = self.character.mind
        risk_label = "激进型，喜欢主动质疑" if m.courage == "bold" else ("保守型，喜欢观察" if m.courage == "cautious" else "平衡型")
        voice_rules = ", ".join(p.voice_rules[:3]) if p.voice_rules else p.vocabulary_style
        section = f"【角色设定】\n说话习惯: {voice_rules}\n风格: {risk_label}"
        if p.basic_info:
            section += f"\n背景: {p.basic_info}"
        return section

    def _build_self_speech(self) -> str:
        """Build self-speech reference section."""
        view = self._view()
        my_speeches = []
        for e in view.public_events:
            if (e.get("day") == view.day
                and e.get("type") == "CHAT_MESSAGE"
                and e.get("actor_id") == self.player_id):
                speech = (e.get("payload", {}).get("speech") or "").strip()
                if speech:
                    my_speeches.append(speech)
        if not my_speeches:
            return ""
        return "\n".join(f"  · {s[:120]}" for s in my_speeches[-3:])

    def _build_speak_order_hint(self, is_first: bool, is_last: bool) -> str:
        """Build wolfcha-style speak order hint."""
        view = self._view()
        if is_last:
            # Count today's speakers
            today_speakers = set()
            for e in view.public_events:
                if e.get("day") == view.day and e.get("type") == "CHAT_MESSAGE" and e.get("phase") == view.phase:
                    today_speakers.add(e.get("actor_id", ""))
            total = len(today_speakers) + 1
            return f"你是最后一个发言（第{total}/{total}个），所有人都已经发言完毕，不要说「等X号发言」或「看X号接下来怎么说」这类话。"

        # Get today's speakers in order
        today_spoken = []
        for e in view.public_events:
            if e.get("day") == view.day and e.get("type") == "CHAT_MESSAGE" and e.get("phase") == view.phase:
                actor_id = e.get("actor_id", "")
                p = self._player_by_id(actor_id)
                if p:
                    tag = self._format_player_tag(p)
                    if tag not in today_spoken:
                        today_spoken.append(tag)

        # Not-yet-spoken alive players
        yet_to_speak = []
        for p in view.players:
            if p["alive"] and p["id"] != self.player_id:
                tag = self._format_player_tag(p)
                if tag not in today_spoken:
                    yet_to_speak.append(tag)

        my_pos = len(today_spoken) + 1
        total = my_pos + len(yet_to_speak)

        if is_first or not today_spoken:
            return "你是第1个发言，其他人都还没发言。"

        spoken_list = "、".join(today_spoken[-8:]) if today_spoken else "(无)"
        unspoken_list = "、".join(yet_to_speak[:8]) if yet_to_speak else "(无)"

        return f"你是第{my_pos}/{total}个发言。已发言: {spoken_list}；未发言: {unspoken_list}。"

    def _build_phase_hint(self) -> str:
        """Build phase hint section."""
        view = self._view()
        phase_map = {
            "DAY_BADGE_SPEECH": "你正在进行警徽竞选发言。",
            "DAY_PK_SPEECH": "你正在进行警徽PK发言。",
            "DAY_LAST_WORDS": "你正在发表遗言。",
        }
        hint = phase_map.get(view.phase, "")
        if not hint:
            return ""
        return f"【当前环节】\n{hint}"

    def _build_perspective_hints_xml(self) -> str:
        """Build wolfcha-style focus angle XML block."""
        hints_text = self._build_perspective_hints()
        if not hints_text:
            return ""
        return f"<focus_angle>\n【你的视角】\n{hints_text}\n</focus_angle>"

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
        """Legacy method kept for compatibility — delegates to new wolfcha-style."""
        return self._ask_json_inner(prompt, default, max_tokens=max_tokens, action="talk")

    def _ask_talk_wolfcha(
        self,
        *,
        system_parts: list[dict],
        user_prompt: str,
        focus_angle: str,
        fallback_speech: str,
        max_tokens: int = 1024,
    ) -> tuple[str, dict]:
        """Wolfcha-style talk generation: system parts + user prompt → JSON string array.

        Returns (speech_text, metadata). Speech is joined from parsed JSON array segments.
        """
        meta = {
            "provider": self.provider,
            "model": self.client.model,
            "source": "fallback",
            "fallback": True,
        }
        try:
            # Build system message from parts
            system_content = self._assemble_system_parts(system_parts, focus_angle)
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt},
            ]

            # First attempt: speech temperature 1.1
            resp = self.client.chat_sync(
                messages=messages,
                temperature=self.speech_temperature,
                max_tokens=max_tokens,
                thinking=False,
            )
            text = self.client.parse_response(resp).strip()
            usage = resp.get("usage", {}) if isinstance(resp, dict) else {}

            # Parse JSON string array: ["msg1", "msg2"]
            segments = self._parse_speech_array(text)
            if segments:
                speech = "\n\n".join(segments)
                self.last_error = None
                meta["source"] = "llm"
                meta["fallback"] = False
                meta["raw_text"] = text[:400]
                meta["attempts"] = 1
                meta["segments"] = len(segments)
                meta["usage"] = usage
                return speech, meta

            # Second attempt: retry with lower temp and explicit reminder
            retry_prompt = user_prompt + "\n\n请务必只输出JSON字符串数组，例如: [\"我觉得3号很可疑\", \"他的发言前后矛盾\"]"
            resp2 = self.client.chat_sync(
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": retry_prompt},
                ],
                temperature=0.9,
                max_tokens=max_tokens,
                thinking=False,
            )
            text2 = self.client.parse_response(resp2).strip()
            usage2 = resp2.get("usage", {}) if isinstance(resp2, dict) else {}
            segments2 = self._parse_speech_array(text2)
            if segments2:
                speech = "\n\n".join(segments2)
                self.last_error = None
                meta["source"] = "llm"
                meta["fallback"] = False
                meta["raw_text"] = text2[:400]
                meta["attempts"] = 2
                meta["segments"] = len(segments2)
                meta["usage"] = usage2
                return speech, meta

            # Third attempt: just use raw text as speech (free-text fallback)
            cleaned = self._clean_speech_text(text)
            if cleaned and len(cleaned) >= 2:
                meta["source"] = "llm"
                meta["fallback"] = False
                meta["raw_text"] = text[:400]
                meta["attempts"] = 3
                meta["segments"] = 1
                meta["usage"] = usage
                return cleaned, meta

            self.last_error = "talk_all_attempts_failed"
            meta["error"] = self.last_error
            meta["raw_text"] = text[:400]
            meta["usage"] = usage
            return fallback_speech, meta
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            meta["error"] = self.last_error
            return fallback_speech, meta

    def _assemble_system_parts(self, parts: list[dict], focus_angle: str) -> str:
        """Assemble wolfcha-style system prompt from cacheable/non-cacheable parts."""
        text_parts = [p["text"] for p in parts if p.get("text")]
        if focus_angle:
            text_parts.append(focus_angle)
        return "\n\n".join(text_parts)

    def _parse_speech_array(self, text: str) -> list[str]:
        """Parse LLM output as JSON string array (wolfcha format): [\"msg1\", \"msg2\"]."""
        if not text:
            return []
        # Try direct JSON parse
        try:
            import json as _json
            parsed = _json.loads(text)
            if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
                return [s.strip() for s in parsed if s.strip()]
        except Exception:
            pass
        # Try extracting JSON array from text
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            try:
                import json as _json
                parsed = _json.loads(text[start:end + 1])
                if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
                    return [s.strip() for s in parsed if s.strip()]
            except Exception:
                pass
        # Try extracting individual quoted strings
        return self._extract_quoted_segments(text)

    def _extract_quoted_segments(self, text: str) -> list[str]:
        """Extract Chinese-quoted strings from text fallback."""
        import re
        # Match both "..." and "..." patterns
        segments = []
        for match in re.finditer(r'"([^"]{2,})"', text):
            seg = match.group(1).strip()
            if seg and not seg.startswith("{") and not seg.startswith("["):
                segments.append(seg)
        if not segments:
            # Try Chinese quotes
            for match in re.finditer(r'“([^”]{2,})”', text):
                seg = match.group(1).strip()
                if seg:
                    segments.append(seg)
        return segments

    def _clean_speech_text(self, text: str) -> str:
        """Clean raw speech text from common artifacts."""
        if not text:
            return ""
        # Remove prefixes
        for prefix in ["发言：", "发言:", "我说：", "我说:", "speech：", "speech:"]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        # Remove surrounding quotes
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1].strip()
        # Remove code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]).strip()
        return text

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
