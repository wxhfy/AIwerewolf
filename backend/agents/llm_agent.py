from __future__ import annotations

import json
import os
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


class LLMFallbackForbidden(RuntimeError):
    """Raised when LLMAgent.STRICT_NO_FALLBACK=True and a fallback would
    otherwise be returned. Used by the strict acceptance runner to abort the
    game instead of silently degrading to heuristic decisions."""


class LLMAgent(Agent):
    """LLM-backed agent with heuristic fallback.

    The fallback preserves playability if the API is slow, unavailable, or
    produces malformed output.

    For acceptance validation (Track B §34 / Track C §19) we expose
    `STRICT_NO_FALLBACK`. When this class attribute is True, the agent
    raises `LLMFallbackForbidden` instead of silently returning a heuristic
    decision so that the surrounding harness can abort the game and refuse
    to publish data produced by a non-LLM path.
    """

    STRICT_NO_FALLBACK: bool = False

    def __init__(
        self,
        player_id: str,
        *,
        seed: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.4,
        speech_temperature: float = 1.1,
        character: Character | None = None,
        strategy_bias: dict[str, list[str]] | None = None,
    ):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.memory: list[str] = []
        self.rng = Random(seed)
        self.temperature = temperature
        self.speech_temperature = speech_temperature
        self.provider = provider
        # api_key/base_url let factory route each player to a specific pool
        # entry (primary vs course-resource fallback) without polluting the
        # process env. Pass through to create_client only when present so
        # callers that don't care still pick up DOUBAO_* defaults.
        client_kwargs: dict = {}
        if model is not None:
            client_kwargs["model"] = model
        if api_key is not None:
            client_kwargs["api_key"] = api_key
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        self.client = create_client(provider=self.provider, **client_kwargs)
        # DeepSeek-v4-flash uses built-in chain-of-thought; combined with
        # 600-1000 token responses this can take 8–20s end-to-end, and on
        # slow links the second attempt is another 8s on top. 120s gives
        # the retry chain enough headroom to never time out under normal
        # conditions; the engine's snapshot drain runs in parallel so the
        # UI stays responsive while we wait.
        self.client.timeout = 120.0
        self.fallback = HeuristicAgent(player_id, seed=seed, character=character)
        self.character = character
        self.strategy_bias = {key: list(value) for key, value in (strategy_bias or {}).items() if value}
        self.winner: str | None = None
        self.last_error: str | None = None
        self.recent_openings: list[str] = []
        self.current_retrieval: list = []

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
        try:
            from backend.db.persist import retrieve_strategy_knowledge
            from backend.eval.evolution import RetrievedStrategyLesson, StrategyRetrievalQuery

            rows = retrieve_strategy_knowledge(
                StrategyRetrievalQuery(
                    role=self.role.value,
                    phase=view.phase,
                    observation_summary=self._retrieval_observation_summary(view, request),
                    situation_tags=[request, view.phase],
                    persona_mbti=self.character.persona.mbti if self.character else None,
                    persona_style=self.character.persona.style_label if self.character else None,
                    top_k=3,
                )
            )
            self.current_retrieval = [RetrievedStrategyLesson(**row) for row in rows]
        except Exception:
            strict = os.getenv("STRATEGY_RETRIEVAL_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}
            if strict:
                raise
            self.current_retrieval = []

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

        # --- Table-language examples ---
        dialogue_examples = self._build_dialogue_examples(is_first_speaker, is_last_words)

        # --- Style guardrails ---
        style_guardrails = self._build_style_guardrails()
        repeat_guardrails = self._build_repeat_guardrails()

        # --- User prompt assembly (wolfcha format) ---
        user_prompt_parts = [game_context]
        transcript_text = "\n".join(today_transcript) if isinstance(today_transcript, list) else (today_transcript or "")
        if transcript_text:
            user_prompt_parts.append("【本日讨论记录】\n" + transcript_text)
        else:
            user_prompt_parts.append("【本日讨论记录】\n（暂无）")
        user_prompt_parts.append("【你本日已说过的话】\n" + (self_speech or "（无）"))
        if phase_hint:
            user_prompt_parts.append(phase_hint)
        if style_guardrails:
            user_prompt_parts.append(style_guardrails)
        if repeat_guardrails:
            user_prompt_parts.append(repeat_guardrails)
        user_prompt_parts.append("【发言顺序】\n" + speak_order_hint)
        if dialogue_examples:
            user_prompt_parts.append(dialogue_examples)
        retrieval_block = self._build_retrieved_lessons_block()
        if retrieval_block:
            user_prompt_parts.append(retrieval_block)
        # When STRATEGY_BIAS_PLACEMENT=system, _build_talk_system_parts has
        # already injected the bias block into the system prompt; skip the
        # user_prompt copy to avoid double-injection. Default 'user' keeps
        # iter2 behavior intact.
        if self._bias_placement() != "system":
            strategy_bias_block = self._build_strategy_bias_block("talk")
            if strategy_bias_block:
                user_prompt_parts.append(strategy_bias_block)
        user_prompt_parts.append("\n轮到你发言，返回JSON数组：")

        full_user_prompt = "\n\n".join(user_prompt_parts)

        # --- Call LLM with wolfcha-style prompt ---
        speech, meta = self._ask_talk_wolfcha(
            system_parts=system_parts,
            user_prompt=full_user_prompt,
            focus_angle=focus_angle,
            fallback_speech=fallback.speech or "",
            max_tokens=1536,
        )
        # Preserve segment_texts for multi-bubble emission
        if meta.get("segment_texts"):
            meta["segments"] = meta["segment_texts"]
            self._remember_opening(meta["segment_texts"])
        self._attach_retrieval_meta(meta)
        return Decision(
            self.player_id,
            ActionType.TALK,
            speech=speech,
            reasoning="",
            metadata=meta,
        )

    def _attach_retrieval_meta(self, meta: dict[str, Any]) -> None:
        if not self.current_retrieval:
            meta["retrieved_knowledge_ids"] = []
            meta["retrieval_used"] = False
            return
        meta["retrieved_knowledge_ids"] = [item.doc_id for item in self.current_retrieval]
        meta["retrieval_query_summary"] = {
            "role": self.role.value,
            "phase": self._view().phase,
            "top_k": len(self.current_retrieval),
        }
        meta["retrieval_used"] = True
        meta["retrieved_knowledge"] = [
            {
                "doc_id": item.doc_id,
                "score": item.score,
                "retrieval_mode": item.retrieval_mode,
                "vector_score": item.vector_score,
                "lexical_score": item.lexical_score,
                "bm25_score": item.bm25_score,
                "fts_score": item.fts_score,
                "rerank_score": item.rerank_score,
                "embedding_provider": item.embedding_provider,
                "rerank_provider": item.rerank_provider,
                "recommended_action": item.recommendation,
            }
            for item in self.current_retrieval
        ]

    @staticmethod
    def _bias_placement() -> str:
        """Read STRATEGY_BIAS_PLACEMENT env var. 'system' = inject bias as
        system_part (higher LLM priority); anything else = user_prompt
        suffix (legacy/iter2 behavior). Used by iter3 dry-runs without
        perturbing in-flight iter2 batches."""
        return os.getenv("STRATEGY_BIAS_PLACEMENT", "user").strip().lower()

    def _build_strategy_bias_block(self, action: str) -> str:
        if not self.strategy_bias:
            return ""
        action_sections = {
            "talk": ("speech_policy", "risk_rules"),
            "vote": ("vote_policy", "risk_rules"),
            "attack": ("skill_policy", "risk_rules"),
            "divine": ("skill_policy", "risk_rules"),
            "guard": ("skill_policy", "risk_rules"),
            "witch": ("skill_policy", "risk_rules"),
            "shoot": ("skill_policy", "risk_rules"),
            "boom": ("skill_policy", "risk_rules"),
            "transfer_badge": ("speech_policy", "vote_policy", "risk_rules"),
        }
        sections = action_sections.get(action, ("speech_policy", "vote_policy", "skill_policy", "risk_rules"))
        lines = [
            "【本局强制执行的策略规则 — 高优先级,必须严格遵守,不得擅自偏离】",
            "下列规则由本轮策略版本指定,优先级高于你的通用策略直觉。即使你认为某条规则不是最优,你也必须按这些规则的字面意思行动,不要二次判断、不要绕过。这是为了让本轮 A/B 锦标赛能精确归因到策略差异。",
        ]
        for section in sections:
            for item in self.strategy_bias.get(section, [])[:3]:
                lines.append(f"- [{section}] {item}")
        return "\n".join(lines) if len(lines) > 2 else ""

    def _build_retrieved_lessons_block(self) -> str:
        if not self.current_retrieval:
            return ""
        lines = [
            "【Retrieved Lessons】",
            "这些是从已通过校验的历史复盘中抽象出的策略知识，只能作为一般玩法提醒，不能当作本局隐藏身份事实。",
        ]
        for index, item in enumerate(self.current_retrieval, start=1):
            lines.append(
                f"{index}. [{item.doc_id} score={item.score:.2f}] "
                f"触发：{item.trigger}；建议：{item.recommendation}；理由：{item.rationale}"
            )
        return "\n".join(lines)

    def _retrieval_observation_summary(self, view: PlayerView, request: str) -> str:
        public_tail = view.public_events[-8:]
        private_tail = view.private_events[-5:]
        parts = [
            f"request={request}",
            f"day={view.day}",
            f"phase={view.phase}",
            f"role={view.self_player.get('role')}",
        ]
        for event in public_tail:
            payload = event.get("payload") or {}
            parts.append(
                "public:"
                + " ".join(
                    str(payload.get(key) or "")
                    for key in ("message", "speech", "actor_name", "target_name", "reason")
                )
            )
        for event in private_tail:
            payload = event.get("payload") or {}
            parts.append(
                "private:"
                + " ".join(
                    str(payload.get(key) or "")
                    for key in ("kind", "message", "target_name", "action_type")
                )
            )
        return "\n".join(item for item in parts if item.strip())

    # ============================================================
    # Wolfcha-style talk prompt builders
    # ============================================================

    def _build_talk_system_parts(self, is_last_words: bool) -> list[dict]:
        """Build wolfcha-style system prompt parts (identity + light persona + guidelines)."""
        view = self._view()
        seat = view.self_player.get("seat", "?")
        name = view.self_player.get("name", "?")
        phase = view.phase

        # Part 1: Identity + Role strategy + Persona (wolfcha-style combined prompt)
        win_cond = self._build_win_condition()
        persona_hint = self._build_persona_hint()
        base = (
            f"你是 {seat}号「{name}」，身份: {self.role.value}。\n\n"
            f"{win_cond}\n\n"
            f"{persona_hint}"
        )

        # Part 2: Task section (varies by phase)
        if is_last_words:
            task_line = "你已经出局，现在发表遗言——交代身份、留下信息、点出最可疑的人。"
        elif "BADGE" in str(phase):
            task_line = (
                "现在是警徽竞选发言。你不是来点评别人的——你是来争取警徽的。"
                "说明你为什么想拿警徽、你此刻更想看谁、你能不能带队。"
                "像桌上一名真实玩家那样说出你此刻想争取的东西，不需要像演讲稿。"
            )
        elif str(phase) == "DAY_PK_SPEECH":
            task_line = (
                "现在是PK发言。场上已经缩到少数焦点位，你需要更明确地打一个方向。"
                "可以直接反驳冲你的人，也可以解释为什么另一个PK位更该出。"
            )
        else:
            task_line = (
                "现在是白天自由发言。你不是在做总结报告——你是桌子上的玩家。"
                "从上一个发言者的观点切入，认同、质疑、补充都可以。"
                "不需要面面俱到，只说此刻你最在意的一点，并顺手给出你的站边或保留意见。"
            )
        task = (
            "【当前处境】\n"
            "你正在参与一局实时狼人杀。你不是旁观解说，也不是裁判。\n"
            f"现在轮到你发言。{task_line}"
        )

        # Part 3: Lightweight behavior hint
        behavior_hint = self._build_behavior_hint()

        # Part 4: Guidelines
        guidelines = (
            "【底线规则】\n"
            "- 只基于本局实际信息发言，严禁编造。\n"
            "- 用「X号」称呼玩家。\n"
            "- 绝对不要说「请X号发言」「过」「下一位」「接下来有请」——你不是主持人！\n"
            "- 严禁职业相关类比、行业术语和场外经历。\n"
            "- 这是线上打字局。你看不到表情、眼神、手势、语速、小动作、摸牌动作；除非聊天记录里明确写出来，否则禁止提这些观察。\n"
            "- 不要虚构自己“听出来”“看出来”的场外细节，也不要写成剧本旁白。\n"
            "\n"
            "【发言方式】\n"
            "从上一人的观点切入——回应他说的内容，然后自然过渡到你自己的判断。\n"
            "不需要总结全场、不需要逐一点评每个玩家。\n"
            "不需要每次都说「我是X号玩家」开头。\n"
            "至少点名 1 位存活玩家，最好直接说清你更像在保谁、踩谁、还是先观望谁。\n"
            "尽量挂住 1 条真实桌面事实：某人的一句发言、一次投票、一次死亡信息、一次警徽动作。\n"
            "可以分成 2-4 条消息气泡，每条 1-2 句完整的思考；首日信息少时也不要只说空话，要给出一个轻度方向。\n"
            "如果你是第一个发言，第一句不要先解释‘信息少’或‘先观察’，而是直接抛一个你要抓的行为模式、玩家类型或警徽态度。\n"
            "允许保留判断，但保留判断也要说明你接下来重点听谁、盯谁、或者为什么暂时不跟票。\n"
            "语气像真人聊天，可以有语气词、停顿、反问，但不要喊口号，也不要写成总结报告。\n"
            "\n"
            "【输出格式】\n"
            "返回 JSON 字符串数组，每个元素是一条消息气泡。"
        )

        parts = [
            {"text": base, "cacheable": True},
        ]
        if behavior_hint:
            parts.append({"text": behavior_hint, "cacheable": True})
        parts.append({"text": task, "cacheable": False})
        # iter3: when STRATEGY_BIAS_PLACEMENT=system, inject the strategy
        # bias as a non-cacheable system part RIGHT BEFORE guidelines so it
        # rides above transcript noise and persona drift in the LLM's
        # attention. Default 'user' = legacy iter2 placement (user_prompt
        # suffix) so in-flight iter2 batches see no change.
        if self._bias_placement() == "system":
            bias_block = self._build_strategy_bias_block("talk")
            if bias_block:
                parts.append({"text": bias_block, "cacheable": False})
        parts.append({"text": guidelines, "cacheable": True})
        return parts

    def _build_behavior_hint(self) -> str:
        """Behavior traits that make this character play differently from others."""
        if not self.character:
            return ""
        p = self.character.persona
        m = self.character.mind

        # Map cognitive values to natural Chinese behavioral descriptions
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
        table_map = {
            "dominant": "你喜欢主导讨论节奏",
            "balanced": "你在场上既会表达也会倾听",
            "quiet": "你话不多，但发言往往切中要害",
        }

        lines = ["<hidden_traits>"]
        lines.append(f"发言特点：{p.speech_length_habit or '自然长度'}")
        lines.append(f"压力下的反应：{p.pressure_style or '冷静回应'}")
        lines.append(f"推理深度：{logic_map.get(m.logic_depth, '中等')}")
        lines.append(f"态度：{courage_map.get(m.courage, '看情况表态')}")
        lines.append(f"对他人的信任度：{suspicion_map.get(m.suspicion_threshold, '中等')}")
        lines.append(f"桌面风格：{table_map.get(m.table_presence, '随和')}")
        if p.wolf_deception_style and self.role.value.lower() in ("werewolf", "white_wolf_king"):
            lines.append(f"拿狼时的打法：{p.wolf_deception_style}")
        if p.mistake_pattern:
            lines.append(f"你的一个弱点：{p.mistake_pattern}")

        # Round-to-round variation
        moods = [
            "这轮可以轻松一点",
            "这轮直接说重点",
            "这轮先回应前一个人再表态",
            "这轮从一个具体的观察切入",
        ]
        lines.append(moods[self.rng.randint(0, len(moods) - 1)])

        lines.append("以上是你的内在特质——发言时自然流露，不要背诵。</hidden_traits>")
        return "\n".join(lines)

    def _build_persona_hint(self) -> str:
        """Character identity — narrative, not bullet points."""
        if not self.character:
            return ""
        p = self.character.persona
        # Use the pre-built narrative system_prompt for rich identity
        if p.system_prompt:
            return (
                "【你的角色】\n"
                + p.system_prompt
                + "\n\n以上是你的角色设定。这是你的底色——自然内化，不要在发言中逐字复述。"
            )
        # Fallback: build a minimal identity
        lines = [f"你是{p.name}，{p.age}岁{p.gender}。{p.basic_info or ''}"]
        if p.vocabulary_style:
            lines.append(f"说话风格：{p.vocabulary_style}")
        if p.reasoning_style:
            lines.append(f"思考方式：{p.reasoning_style}")
        return "【你的角色】\n" + "\n".join(lines)

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
            "- 时间线提醒：昨夜刀口在今天白天开始前已锁定；不要把今天的发言当作昨夜被刀的原因。\n"
            "\n"
            "【各阶段信息可用性——推理时请牢记】\n"
            "- 第一夜（第0夜→第1天）：狼人刀人时没有任何信息（不知道谁是预言家/女巫/守卫），刀口是随机的。预言家第一夜查验也是盲查。所有人第一天白天开始时信息量极少，怀疑应该比较弱。\n"
            "- 第二夜起：狼人可以根据白天发言选择刀口；预言家可以根据白天发言选择查验目标；女巫可以根据白天信息决定用药。\n"
            "- 白天发言阶段：你只能看到公开的发言和投票结果，看不到其他人的角色和夜间行动。\n"
            "- 遗言：被投票放逐的玩家可以发表遗言，被狼人杀死的玩家通常不能遗言。"
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
        """Wolfcha-style win condition + role strategy combined."""
        role = self.role.value.lower()
        win_map = {
            "werewolf": "【你的阵营】狼人。狼人数量 >= 好人数量时胜利。你知道狼队友是谁，白天伪装好人，夜晚和队友协调刀人。",
            "white_wolf_king": "【你的阵营】白狼王。狼人数量 >= 好人数量时胜利。你白天可自爆带走一名玩家。",
            "seer": "【你的阵营】预言家。放逐所有狼人时好人胜利。每晚查验一人，结果只有你知道。",
            "witch": "【你的阵营】女巫。放逐所有狼人时好人胜利。有一瓶解药和一瓶毒药，各限一次。",
            "hunter": "【你的阵营】猎人。放逐所有狼人时好人胜利。死亡时可开枪带走一人（被毒杀除外）。",
            "guard": "【你的阵营】守卫。放逐所有狼人时好人胜利。每晚守护一人，不能连守同一人。",
            "villager": "【你的阵营】村民。放逐所有狼人时好人胜利。没有特殊能力，靠推理和投票。",
            "idiot": "【你的阵营】白痴。放逐所有狼人时好人胜利。被投票放逐时翻牌免疫，之后失去投票权。",
        }
        base = win_map.get(role, "【你的阵营】好人。放逐所有狼人时胜利。")

        # Add role-specific talk strategy from prompts.py
        from backend.agents.prompts import get_action_strategy
        strategy = get_action_strategy("talk", self.role)
        if strategy:
            base += f"\n\n【你的玩法】{strategy}"
        return base

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
        """Build wolfcha-style speak order hint with 'respond to last speaker' guidance."""
        view = self._view()
        if is_last:
            today_speakers = set()
            for e in view.public_events:
                if e.get("day") == view.day and e.get("type") == "CHAT_MESSAGE" and e.get("phase") == view.phase:
                    today_speakers.add(e.get("actor_id", ""))
            total = len(today_speakers) + 1
            return (
                f"你是最后一个发言（第{total}/{total}个），所有人都已经发言完毕。"
                "不要说「等X号发言」或「看X号接下来怎么说」。"
            )

        # Get today's speakers in order with their speeches
        today_spoken = []
        last_speaker = None
        last_speech = ""
        for e in view.public_events:
            if e.get("day") == view.day and e.get("type") == "CHAT_MESSAGE" and e.get("phase") == view.phase:
                actor_id = e.get("actor_id", "")
                p = self._player_by_id(actor_id)
                if p:
                    tag = self._format_player_tag(p)
                    if tag not in [s[0] for s in today_spoken]:
                        payload = e.get("payload", {}) or {}
                        speech = str(payload.get("speech", ""))[:80]
                        today_spoken.append((tag, speech))
                        last_speaker = tag
                        last_speech = speech

        yet_to_speak = []
        for p in view.players:
            if p["alive"] and p["id"] != self.player_id:
                tag = self._format_player_tag(p)
                if tag not in [s[0] for s in today_spoken]:
                    yet_to_speak.append(tag)

        my_pos = len(today_spoken) + 1
        total = my_pos + len(yet_to_speak)

        if is_first or not today_spoken:
            return "你是第1个发言，其他人都还没发言。"

        spoken_list = "、".join(s[0] for s in today_spoken[-8:])
        unspoken_list = "、".join(yet_to_speak[:8])

        hint = f"你是第{my_pos}/{total}个发言。已发言: {spoken_list}；未发言: {unspoken_list}。"
        # Add "respond to last speaker" guidance
        if last_speaker:
            hint += (
                f"\n上一个发言的是{last_speaker}，他说：「{last_speech}」。"
                "你可以从回应他的观点开始——认同、质疑、补充都可以。"
            )
        return hint

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

    def _build_dialogue_examples(self, is_first: bool, is_last_words: bool) -> str:
        """Short table-style examples to anchor 'human-like but grounded' speech."""
        phase = self._view().phase
        if is_last_words:
            return (
                "【参考语气】\n"
                "- “我这张如果走了，你们重点回头看3号和6号，今天这两张的站边最不干净。”\n"
                "- “身份我先不展开复盘了，就留一句：别把警徽流断在4号这里。”"
            )
        if phase == "DAY_BADGE_SPEECH":
            return (
                "【参考语气】\n"
                "- “这把警徽我想拿，因为我今天能把票型和发言都记住，不会乱归。”\n"
                "- “如果警徽给我，我第一天会先盯2号和5号，这两张的起跳空间最大。”"
            )
        if phase == "DAY_PK_SPEECH":
            return (
                "【参考语气】\n"
                "- “PK到我头上可以，但你们得先解释为什么3号那轮跟票比我还轻却没人追。”\n"
                "- “我这张先不求你们保死，只说一点：今天真要出我，明天请回头看一直顺着我冲的人。”"
            )
        if is_first:
            return "【参考语气】\n" + "\n".join(self._first_speaker_examples())
        return (
            "【参考语气】\n"
            "- “你刚那句我不太认，尤其是你把4号直接保掉这一下有点快。”\n"
            "- “我这轮先不跟着冲6号，我更想听5号为什么昨天那票能下得这么轻。”"
        )

    def _first_speaker_examples(self) -> list[str]:
        """Style-specific openers so first-speaker lines don't all collapse into one template."""
        style = self.character.persona.style_label if self.character else ""
        samples = {
            "aggressive": [
                "- “首麦我先把话放这，等下谁发言太滑，我第一轮就追着打。”",
                "- “别都拿第一天当挡箭牌，后面谁急着抱团我先记一笔。”",
            ],
            "analytical": [
                "- “我先给个筛选标准：谁先偷换概念、谁先乱保人，我就从谁开始盘。”",
                "- “样本少不代表没法听，我先看谁后面发言会和自己的立场对不上。”",
            ],
            "insightful": [
                "- “我今天更想听动机，不是谁声音大，而是谁一开口就在替自己留后路。”",
                "- “首置位先不锤人，但谁急着证明自己是好人，我会先多看一眼。”",
            ],
            "playful": [
                "- “先说好，谁一上来端着正义脸乱保人，我今天先给他挂个问号。”",
                "- “第一麦没材料硬锤，但我可以先埋个钩子，后面谁自己往上撞我就接。”",
            ],
            "observant": [
                "- “我先不站边，等下谁发言像提前备好稿子，我会先记他。”",
                "- “这一轮我只抓不自然的点，谁说得太顺了反而容易进我视线。”",
            ],
            "poetic": [
                "- “今天先不急着下刀口结论，我更想看谁的话像借来的，谁的话是从心里出来的。”",
                "- “第一天像雾里看人，但雾最厚的地方，往往也最值得多盯两眼。”",
            ],
        }
        return samples.get(
            style,
            [
                "- “我先留个观察方向，后面谁最先抢结论、谁最先躲判断，我都会记。”",
                "- “第一天信息少不等于只能过，我更在意谁开口先把自己摘干净。”",
            ],
        )

    def _build_style_guardrails(self) -> str:
        """Map persona traits into concrete table-language constraints."""
        if not self.character:
            return ""
        p = self.character.persona
        rules: list[str] = []
        style = p.style_label
        voice = set(p.voice_rules or [])

        if style in {"aggressive", "commander", "ranger", "tactical", "interrogator"}:
            rules.append("你可以更强势，但强势要落在具体对象和理由上，不要空喊。")
        if style in {"analytical", "matrix", "precise", "meticulous", "strategist", "theorist"}:
            rules.append("你说话要更像在对账：少抒情，多点‘因为/所以/如果’。")
        if style in {"warm", "harmonizer", "mediator", "caretaker", "rallier"}:
            rules.append("你的语气可以柔和，但最后还是要给出一个方向，不要只有安抚。")
        if style in {"poetic", "lyrical", "sensitive"}:
            rules.append("你可以带一点意象或情绪色彩，但核心判断必须清楚，别把发言写成散文。")
        if style in {"playful", "provocative", "tricky", "cosmopolitan", "curious"}:
            rules.append("可以带一点调侃或小钩子，但不要为了有趣牺牲清晰度。")
        if style in {"veteran", "observant", "still_water", "gentle", "observer"}:
            rules.append("你不需要说太多，但短发言里要留一个明确观察点。")

        if "minimal" in voice or p.speech_length_habit.startswith("极短") or p.speech_length_habit == "短":
            rules.append("控制在 2-3 条短气泡内，不要突然变成长篇大论。")
        if "structured" in voice or "precise" in voice or "formal" in voice:
            rules.append("尽量使用先判断后补一句依据的结构。")
        if "comedic" in voice or "witty" in voice or p.humor_style == "sarcastic":
            rules.append("允许一点玩笑或反讽，但整轮最多一句，别每句都抖机灵。")
        if p.uncertainty_style:
            rules.append(f"不确定时，按你的习惯处理：{p.uncertainty_style}。")
        if p.social_habit:
            rules.append(f"桌面互动习惯：{p.social_habit}。")

        if not rules:
            return ""
        return "【你的这轮说话手感】\n" + "\n".join(f"- {item}" for item in rules[:5])

    def _build_repeat_guardrails(self) -> str:
        samples = [item for item in self.recent_openings[-3:] if item]
        if not samples:
            return ""
        return (
            "【避免重复】\n"
            "不要再用你最近几轮这些开头方式：\n"
            + "\n".join(f"- {item}" for item in samples)
            + "\n这轮请换一个切入口。"
        )

    def _build_perspective_hints_xml(self) -> str:
        """Build wolfcha-style focus angle XML block."""
        hints_text = self._build_perspective_hints()
        if not hints_text:
            return ""
        return f"<focus_angle>\n【你的视角】\n{hints_text}\n</focus_angle>"

    def vote(self) -> Decision:
        fallback = self.fallback.vote()
        data = self._target_action(
            "vote",
            fallback,
            "今天必须从存活玩家里投出 1 人。",
            extra_instructions=[
                "优先根据今天桌面上已经发生的真实信息投票：发言矛盾、站边摇摆、警徽表现、历史票型都可以。",
                "reasoning 用 2-4 句中文说清楚：你为什么投这个人、你不投另一个焦点位的原因、你希望好人接下来观察什么。",
                "如果信息仍然不足，也要给出一个当前最差选项，而不是空泛地说都可疑。",
            ],
        )
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

    def _target_action(
        self,
        action: str,
        fallback: Decision,
        instruction: str,
        *,
        extra_instructions: list[str] | None = None,
    ) -> dict[str, Any]:
        instructions = [instruction]
        if extra_instructions:
            instructions.extend(extra_instructions)
        prompt = self._build_action_prompt(
            action=action,
            instructions=instructions,
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
        # iter3: when STRATEGY_BIAS_PLACEMENT=system, bias is already in the
        # system prompt (see _build_system_prompt). Skip the user-prompt copy
        # to avoid double-injection. Default 'user' keeps iter2 behavior.
        if self._bias_placement() != "system":
            strategy_bias_block = self._build_strategy_bias_block(action)
            if strategy_bias_block:
                blocks.extend(["", strategy_bias_block])
        retrieval_block = self._build_retrieved_lessons_block()
        if retrieval_block:
            blocks.extend(["", retrieval_block])

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
        """Generate game-state-aware focus angles (wolfcha-style).

        Each player gets a unique perspective based on: mentions, seat neighbors,
        sheriff status, voting patterns, and speak order position.
        """
        view = self._view()
        seat = int(view.self_player.get("seat", 0))
        day = view.day
        hints: list[str] = []

        # 1. Check if mentioned by others today (highest priority)
        for e in view.public_events:
            if e.get("type") == "CHAT_MESSAGE" and e.get("day") == day:
                payload = e.get("payload", {}) or {}
                speech = str(payload.get("speech", ""))
                if f"@{seat}号" in speech or f"{seat}号" in speech:
                    mentioner_id = e.get("actor_id") or ""
                    mentioner = self._player_by_id(mentioner_id)
                    if mentioner:
                        who = self._format_player_tag(mentioner)
                        hints.append(f"你被{who}点名提到了，可以考虑回应")
                    break

        # 2. Adjacent to dead player
        total = len(view.players)
        dead_seats = [int(p.get("seat", -1)) for p in view.players if not p["alive"]]
        for ds in dead_seats:
            if ds > 0 and (abs(seat - ds) == 1 or abs(seat - ds) == total - 1):
                dead_player = next((p for p in view.players if int(p.get("seat", -1)) == ds), None)
                if dead_player:
                    hints.append(f"你和出局的{self._format_player_tag(dead_player)}座位相邻，可以从这个角度聊一句")
                else:
                    hints.append("你和出局的玩家座位相邻，可以从这个角度聊一句")
                break

        # 3. Sheriff angle (more specific)
        is_sheriff = view.self_player.get("is_sheriff") or view.self_player.get("badge")
        if is_sheriff:
            hints.append("你是警长，你的发言会影响别人，可以自然给出你的方向")
        else:
            # Alternate: respond to sheriff vs question sheriff
            if (seat + day) % 2 == 0:
                hints.append("可以回应一下警长的方向，说明你是否认同")
            else:
                hints.append("如果你不认同警长，可以自然提出疑问")

        # 4. Voting alignment (day 2+)
        if day >= 2:
            my_votes = []
            for e in view.public_events:
                if e.get("type") == "VOTE_CAST" and e.get("day") == day - 1:
                    payload = e.get("payload", {}) or {}
                    if payload.get("voter_id") == self.player_id:
                        my_votes.append(payload.get("target_id", ""))
            if my_votes:
                # Find who voted the same way
                same_voters = []
                for e in view.public_events:
                    if e.get("type") == "VOTE_CAST" and e.get("day") == day - 1:
                        payload = e.get("payload", {}) or {}
                        if payload.get("target_id") in my_votes and payload.get("voter_id") != self.player_id:
                            v = self._player_by_id(payload.get("voter_id", ""))
                            if v:
                                same_voters.append(self._format_player_tag(v))
                if same_voters:
                    names = "、".join(same_voters[:3])
                    hints.append(f"昨天{names}和你投了同一个目标，可以想想这件事要不要提")

        # 5. Speak position (determined by counting today's speakers)
        today_spoken = sum(
            1 for e in view.public_events
            if e.get("day") == day and e.get("type") == "CHAT_MESSAGE" and e.get("phase") == view.phase
        )
        if today_spoken == 0:
            hints.append("你是第一个发言，没有人可以参考，可以先抛出一个起手判断")
        elif today_spoken >= 3:
            hints.append("你已经听了大部分人的发言，可以挑你最在意的一点回应")

        # Select at most 2 hints
        selected = hints[:2] if len(hints) >= 2 else hints
        if not selected:
            return ""

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
            "6. 发言要符合狼人杀桌面语言、保持你的人物口吻。\n"
            "7. 以上所有设定都是你的内部指引——永远不要在你的发言中逐字复述或引用设定内容。"
        )
        # iter3: when STRATEGY_BIAS_PLACEMENT=system, append the strategy
        # bias to the end of the system prompt so action-path prompts
        # (vote/divine/witch/etc.) see it above transcript noise too. The
        # user_prompt counterpart in _build_action_prompt is suppressed to
        # avoid double-injection. Default 'user' = legacy.
        bias_tail = ""
        if self._bias_placement() == "system":
            bias_tail = self._build_strategy_bias_block("__all__")
            if bias_tail:
                bias_tail = "\n\n" + bias_tail
        return role_system + char_block + comm_profile + player_mind + constraints + bias_tail

    def _build_communication_profile(self) -> str:
        """Build wolfcha-style hidden communication profile section."""
        if not self.character:
            return ""
        p = self.character.persona
        lines = [
            "",
            "<hidden_communication_profile>",
            "这些信息只用于塑造你的狼人杀水平、词汇和发言长度，不要向其他玩家明说。",
        ]
        if p.werewolf_experience:
            lines.append(f"- 狼人杀理解：{p.werewolf_experience}")
        if p.vocabulary_style:
            lines.append(f"- 词汇习惯：{p.vocabulary_style}")
        if p.reasoning_style:
            lines.append(f"- 推理方式：{p.reasoning_style}")
        if p.speech_length_habit:
            lines.append(f"- 发言长短：{p.speech_length_habit}")
        if p.pressure_style:
            lines.append(f"- 压力反应：{p.pressure_style}")
        if p.uncertainty_style:
            lines.append(f"- 不确定性：{p.uncertainty_style}")
        if p.mistake_pattern:
            lines.append(f"- 常见误判：{p.mistake_pattern}")
        if p.wolf_deception_style:
            lines.append(f"- 拿狼伪装：{p.wolf_deception_style}")
        lines.append("</hidden_communication_profile>")
        return "\n".join(lines)

    def _build_player_mind_section(self) -> str:
        """Build wolfcha-style hidden player mind section."""
        if not self.character:
            return ""
        m = self.character.mind
        courage_labels = {"bold": "bold", "cautious": "cautious", "calculated": "calculated"}
        lines = [
            "",
            "<hidden_player_mind>",
            "这些信息是你稳定的玩家心智，只用于塑造你如何判断、站边、改口、承压和发言，不要向其他玩家明说。",
            f"- 胆量：{m.courage}",
            f"- 记忆偏好：{m.memory_bias}",
            f"- 怀疑阈值：{m.suspicion_threshold}",
            f"- 自保倾向：{m.self_protection}",
            f"- 逻辑水平：{m.logic_depth}",
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
        total_latency_ms = 0
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
            total_latency_ms += int(resp.get("_latency_ms", 0)) if isinstance(resp, dict) else 0

            # Parse JSON string array: ["msg1", "msg2"]
            segments = self._parse_speech_array(text)
            if segments:
                if not self._looks_generic_speech(segments):
                    speech = "\n\n".join(segments)
                    self.last_error = None
                    meta["source"] = "llm"
                    meta["fallback"] = False
                    meta["raw_text"] = text[:400]
                    meta["attempts"] = 1
                    meta["segment_count"] = len(segments)
                    meta["segment_texts"] = segments
                    meta["usage"] = usage
                    meta["latency_ms"] = total_latency_ms
                    return speech, meta

            # Second attempt: retry with lower temp
            retry_prompt = user_prompt + "\n\n" + self._anti_generic_retry_note() + "\n\n请输出JSON字符串数组。"
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
            total_latency_ms += int(resp2.get("_latency_ms", 0)) if isinstance(resp2, dict) else 0
            segments2 = self._parse_speech_array(text2)
            if segments2:
                if not self._looks_generic_speech(segments2):
                    speech = "\n\n".join(segments2)
                    self.last_error = None
                    meta["source"] = "llm"
                    meta["fallback"] = False
                    meta["raw_text"] = text2[:400]
                    meta["attempts"] = 2
                    meta["segment_count"] = len(segments2)
                    meta["segment_texts"] = segments2
                    meta["usage"] = usage2
                    meta["latency_ms"] = total_latency_ms
                    return speech, meta

            # Third attempt: just use raw text as speech (free-text fallback)
            cleaned = self._clean_speech_text(text)
            if cleaned and len(cleaned) >= 2 and not self._looks_generic_speech([cleaned]):
                meta["source"] = "llm"
                meta["fallback"] = False
                meta["raw_text"] = text[:400]
                meta["attempts"] = 3
                meta["segments"] = 1
                meta["usage"] = usage
                meta["latency_ms"] = total_latency_ms
                return cleaned, meta

            self.last_error = "talk_all_attempts_failed"
            meta["error"] = self.last_error
            meta["raw_text"] = text[:400]
            meta["usage"] = usage
            meta["latency_ms"] = total_latency_ms
            if LLMAgent.STRICT_NO_FALLBACK:
                raise LLMFallbackForbidden(
                    f"Talk fallback would fire for {self.player_id}; "
                    f"error={self.last_error}; raw={text[:120]}"
                )
            return fallback_speech, meta
        except LLMFallbackForbidden:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            meta["error"] = self.last_error
            if LLMAgent.STRICT_NO_FALLBACK:
                raise LLMFallbackForbidden(
                    f"Talk fallback would fire for {self.player_id}; reason={self.last_error}"
                ) from exc
            return fallback_speech, meta

    def _assemble_system_parts(self, parts: list[dict], focus_angle: str) -> str:
        """Assemble wolfcha-style system prompt from cacheable/non-cacheable parts."""
        text_parts = [p["text"] for p in parts if p.get("text")]
        if focus_angle:
            text_parts.append(focus_angle)
        return "\n\n".join(text_parts)

    def _anti_generic_retry_note(self) -> str:
        return (
            "【去模板要求】\n"
            "不要再把“信息少、先观察、重点听X号、暂时不站边”当成整段主体。\n"
            "不要用“第一天……”“首置位信息少……”这类万能开场白起手。\n"
            "请换一种更像真人桌游的起手：\n"
            "1. 直接点一个你要追的行为模式；或\n"
            "2. 明确说你这轮更保谁/踩谁；或\n"
            "3. 直接回应上一位最不合理的一句。\n"
            "允许保留判断，但不能整段都停留在‘再听听看’。"
        )

    def _looks_generic_speech(self, segments: list[str]) -> bool:
        text = " ".join(s.strip() for s in segments if s.strip())
        if not text:
            return True
        generic_markers = [
            "信息少",
            "没有信息",
            "先观察",
            "先听",
            "重点听",
            "暂时不站边",
            "不给站边",
            "不给结论",
            "再听听",
        ]
        opening_markers = ["第一天", "首置位", "首麦", "今天信息少", "首置位信息少"]
        hits = sum(1 for item in generic_markers if item in text)
        opening = text[:20]
        # Strongly discourage the same safe first-day disclaimer pattern.
        starts_generic = any(opening.startswith(item) for item in opening_markers) and (
            "信息" in opening or "观察" in opening or "不站边" in opening or "不给" in opening
        )
        return (
            starts_generic
            or hits >= 3
            or (hits >= 2 and len(text) < 90 and "因为" not in text and "所以" not in text and "但" not in text)
        )

    def _remember_opening(self, segments: list[str]) -> None:
        for segment in segments:
            text = segment.strip().replace("\n", " ")
            if not text:
                continue
            self.recent_openings.append(text[:24])
            self.recent_openings = self.recent_openings[-6:]
            break

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
        total_latency_ms = 0
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
                total_latency_ms += int(response.get("_latency_ms", 0)) if isinstance(response, dict) else 0
                parsed = self._coerce_json(text)
                if parsed is not None:
                    self.last_error = None
                    meta["source"] = "llm"
                    meta["fallback"] = False
                    meta["raw_text"] = text[:400]
                    meta["attempts"] = idx + 1
                    meta["usage"] = last_usage
                    meta["latency_ms"] = total_latency_ms
                    self._attach_retrieval_meta(meta)
                    return parsed, meta
            self.last_error = "json_parse_failed"
            meta["error"] = self.last_error
            meta["raw_text"] = last_text[:400]
            meta["usage"] = last_usage
            meta["latency_ms"] = total_latency_ms
            self._attach_retrieval_meta(meta)
            if LLMAgent.STRICT_NO_FALLBACK:
                raise LLMFallbackForbidden(
                    f"JSON fallback would fire for {self.player_id} action={action}; "
                    f"error={self.last_error}; raw={last_text[:120]}"
                )
            return default, meta
        except LLMFallbackForbidden:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            meta["error"] = self.last_error
            self._attach_retrieval_meta(meta)
            if LLMAgent.STRICT_NO_FALLBACK:
                raise LLMFallbackForbidden(
                    f"JSON fallback would fire for {self.player_id} action={action}; reason={self.last_error}"
                ) from exc
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
