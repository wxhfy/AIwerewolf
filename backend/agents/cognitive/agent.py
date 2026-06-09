"""CognitiveAgent — production-grade Werewolf AI using Observe-Think-Act.

Implements the Agent protocol. ALL cognitive work is delegated:
- Observation extraction → observe.py + BeliefTracker
- Reasoning → Pipeline (observe → think → act)
- Memory/Stance → Memory (includes SocialModel + Planner)
- Personality → Profile + Humanization
- Strategy → retrieval.py + strategy_bias
- Wolf coordination → wolf_team.py (legal visible information only)
- Multi-turn planning → planner.py (StrategicIntent)

This module ONLY handles:
- Agent lifecycle (initialize, update, finish)
- Protocol compliance (talk, vote, attack, etc.)
- State tracking (guard history, witch potions)
- Social model wiring (trust updates, deception detection)
- LLM-only error propagation
"""

from __future__ import annotations

import json
import os as _os
import re
from typing import Any

from langchain_core.runnables import Runnable

from backend.agents.cognitive import trace_keys
from backend.agents.cognitive.agent_loop import get_last_loop_trace
from backend.agents.cognitive.humanization import build_humanization_profile
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import BeliefTracker
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import format_observation
from backend.agents.cognitive.observe import observe
from backend.agents.cognitive.pipeline import Pipeline
from backend.agents.cognitive.pipeline import parse_json_array
from backend.agents.cognitive.pipeline import parse_json_target
from backend.agents.cognitive.profiles import Profile
from backend.agents.cognitive.profiles import get_profile
from backend.agents.cognitive.prompts import build_strategy_bias_block
from backend.agents.cognitive.prompts import build_system_prompt
from backend.agents.cognitive.social_model import DeceptionSignal
from backend.engine.models import ActionType
from backend.engine.models import Decision


class CognitiveAgent:
    """Werewolf agent using Observe-Think-Act cognitive architecture.

    Production-grade: integrates Character system, BeliefTracker, Playbooks,
    Humanization, and Strategy Bias.

    LLM-only game mode: failures raise instead of degrading to heuristic decisions.
    Implements the full Agent protocol.
    """

    _MAX_REQUIRED_ACTION_REPAIR_ROUNDS = 3
    _NO_ACTION_TARGET_KEYWORDS = {
        "弃票",
        "弃权",
        "abstain",
        "pass",
        "none",
        "null",
        "无",
        "空",
        "不行动",
        "跳过",
    }
    _BOOM_SKIP_KEYWORDS = {"不爆", "不自爆", "放弃", "不炸", "跳过"}
    _WITCH_NO_POISON_KEYWORDS = {"", "none", "null", "无", "不用", "不毒", "跳过"}
    _SPEECH_ACCUSATION_KEYWORDS = ("狼", "坏人", "可疑", "票", "出", "查杀", "铁狼")
    _ROLE_CLAIM_KEYWORDS = (
        "我是预言家",
        "我是女巫",
        "我是守卫",
        "我是猎人",
        "我是白痴",
        "我跳预言家",
        "我起跳",
        "查了",
        "查验",
        "查杀",
    )
    _SELF_ACCUSATION_KEYWORDS = ("是狼", "查杀", "怀疑", "投", "出")
    _MAJOR_EVENT_KEYWORDS = ("自爆", "翻牌")

    def __init__(
        self,
        player_id: str,
        role: str,
        llm: Runnable,
        player_name: str = "",
        player_seat: int = 0,
        profile: Profile | None = None,
        strategy_bias: dict[str, list[str]] | None = None,
        fallback_heuristic: Any = None,
        strict_no_fallback: bool = True,
        retrieval_policy: str = "",
        feature_flags: dict[str, bool] | None = None,
    ):
        self.player_id = player_id
        self.role = role
        self._llm = llm
        self.player_name = player_name
        self.player_seat = player_seat

        # Profile (WHO the agent is — integrated Character system)
        self._profile = profile or get_profile(role)

        # Humanization (behavioral parameters derived from persona + mind)
        self._humanization = build_humanization_profile(self._profile.persona, self._profile.mind)

        # System prompt (built once from Profile.to_system_intro())
        self._system_prompt = build_system_prompt(role, self._profile)

        # Strategy bias (forced policy for A/B testing)
        self._strategy_bias = strategy_bias or {}
        self._feature_flags = dict(feature_flags or {})

        # Fallback configuration
        self._fallback_heuristic = fallback_heuristic
        self._strict_no_fallback = strict_no_fallback

        # Fallback tracking (for monitoring)
        self._fallback_count = 0
        self._fallback_reasons: list[str] = []
        self._validation_error_count = 0

        # Pipeline (stateless cognitive engine — now persona-aware)
        self._pipeline = Pipeline(
            llm,
            self._system_prompt,
            self._strategy_bias,
            persona_mbti=(self._profile.persona.mbti if self._profile.persona else ""),
            persona_style=(self._profile.persona.style_label if self._profile.persona else ""),
            retrieval_policy=retrieval_policy,
            player_id=player_id,
            feature_flags=self._feature_flags,
        )

        # Memory (persists across rounds — includes humanization + playbook)
        self.memory = Memory(player_id, role, humanization=self._humanization)

        # BeliefTracker (stateful claim/contradiction/vote tracking)
        self._tracker = BeliefTracker()

        # Game state (set by engine via initialize/update)
        self._view: Any = None

        # Role-specific tracking
        self._guard_history: list[str] = []
        self._witch_save_used = False
        self._witch_poison_used = False

        # Speech memory (anti-repeat)
        self._today_speech_count = 0

        # Game tracking (for post-game reflection)
        self._game_id = ""
        self._turn_phase = ""  # Track phase changes for analysis cache invalidation

        # Wolf team coordination (legal visible information, no fixed tactics)
        self._wolf_team_view: Any = None
        self._wolf_tactics: dict[str, str] = {}

        # Speech targets for social model (speech-vote mismatch detection)
        self._last_speech_targets: list[str] = []

    # === Agent Protocol ===

    def initialize(self, view: Any, game_setting: dict) -> None:
        self._view = view
        self.player_name = view.self_player.get("name", self.player_id)
        self.player_seat = view.self_player.get("seat", 0)
        # Track game_id for post-game reflection
        self._game_id = getattr(view, "game_id", "") or str(game_setting.get("game_id", ""))
        self._tracker = BeliefTracker()

        # Wolf team view is built on-demand in attack() from current PlayerView
        # (legally visible teammate list + public events + belief tracker).

    def update(self, view: Any, request: str) -> None:
        self._view = view
        # Clear cached analysis when phase changes (new turn/new action type)
        new_phase = f"{view.day}:{view.phase}"
        if new_phase != self._turn_phase:
            # Check if an active intent's target phase was in the previous phase
            # and mark it as missed if the target has now passed without execution
            if self._turn_phase:
                old_phase = self._turn_phase.split(":", 1)[-1] if ":" in self._turn_phase else ""
                active = self.memory.planner.get_active(view.day, old_phase)
                if active and not active.resolved:
                    active.resolved = True
                    active.resolution_note = f"phase_passed_to_{view.phase}"
            self._pipeline._cached_analysis = ""
            self._turn_phase = new_phase
        self.memory.update_round(view.day, view.phase)
        self._today_speech_count = 0
        self._last_speech_targets = []

    def day_start(self) -> None:
        pass

    # ---- Talk (multi-bubble) ----

    def talk(self) -> Decision:
        obs = self._observe()
        today_chat_count = sum(
            1
            for e in self._view.public_events
            if e.get("day") == self._view.day and e.get("type") == "CHAT_MESSAGE" and e.get("phase") == self._view.phase
        )
        is_first = today_chat_count == 0
        is_last_words = self._view.phase == "DAY_LAST_WORDS"

        result = self._pipeline.run_speech(obs, self.memory, is_first, is_last_words)
        raw = result.get("speech", "")
        reasoning = result.get("reasoning", "")

        # Parse multi-bubble speech. LLM-only mode must not synthesize a
        # replacement utterance locally; an empty or unusable model response is
        # an acceptance failure.
        segments = parse_json_array(raw)
        if not segments or (len(segments) == 1 and len(segments[0]) < 3):
            import logging

            _logger = logging.getLogger(__name__)
            _logger.warning(
                "LLM speech unusable for %s(%s): raw_len=%s, segments_parsed=%s",
                self.player_name,
                self._profile.role,
                len(raw),
                len(segments) if segments else 0,
            )
            raise RuntimeError(f"LLM speech response is empty or too short for {self.player_name}")
        if not str(reasoning or "").strip():
            raise RuntimeError(f"LLM speech decision missing reasoning for {self.player_name}")

        self.memory.add_action("speech", None, segments[0], reasoning)
        self.memory.remember_opening(segments)
        self._today_speech_count += len(segments)

        # Record speech content for social model mismatch detection
        self._last_speech_targets = segments

        # Mark strategic intent as executed if this was the target phase
        self._mark_active_intent_executed_if_target_phase_contains("SPEECH")

        return self._decision(
            ActionType.TALK,
            speech="\n".join(segments),
            reasoning=reasoning,
            metadata=trace_keys.loop_metadata_from_result(
                result, {"segments": segments, "segment_count": len(segments)}
            ),
        )

    # ---- Vote ----

    @staticmethod
    def _skip_optimisations_enabled() -> bool:
        return _os.getenv("_DISABLE_SKIP_OPTIMISATIONS") != "1"

    @staticmethod
    def _single_legal_target(obs: Observation) -> Any | None:
        legal_target_ids = {player.id for player in obs.legal_targets}
        if len(legal_target_ids) == 1:
            return obs.legal_targets[0]
        return None

    def vote(self) -> Decision:
        obs = self._observe()
        legal_target_ids = {player.id for player in obs.legal_targets}

        # ── Optimisation: skip LLM when there is only one legal target ──
        only_target = self._single_legal_target(obs)
        if self._skip_optimisations_enabled() and only_target:
            only_target_id = only_target.id
            reasoning = f"唯一合法目标 {only_target.seat}号:{only_target.name}，无需LLM决策"
            self._record_vote_followups(only_target_id, only_target_id, reasoning)
            return self._decision(ActionType.VOTE, target_id=only_target_id, reasoning=reasoning)

        # ── Optimisation: reuse tentative_vote from speech if nothing changed ──
        if self._skip_optimisations_enabled():
            tentative = self._pipeline.get_tentative_vote()
            if tentative and tentative.get("raw"):
                tentative_target = self._resolve_target(tentative["raw"])
                if tentative_target and tentative_target in legal_target_ids:
                    if not self._has_meaningful_new_info_since_speech(obs):
                        reasoning = f"发言立场未变: 投{tentative_target}（" + tentative["raw"] + "）"
                        self._record_vote_followups(tentative_target, tentative_target, reasoning)
                        return self._decision(ActionType.VOTE, target_id=tentative_target, reasoning=reasoning)

        result = self._pipeline.run_vote(
            obs,
            self.memory,
            vote_temperature=self._humanization.vote_temperature,
        )
        target_id = self._resolve_target(result["target"])
        if legal_target_ids and target_id not in legal_target_ids:
            target_id = None
        # Abstention: return empty vote as Decision (not dict)
        if not target_id:
            return self._decision(
                ActionType.VOTE,
                target_id="",
                reasoning=result.get("reasoning", "弃票"),
                metadata=trace_keys.loop_metadata_from_result(result),
            )
        self._record_vote_followups(result["target"], result["target"], result["reasoning"])

        return self._decision(
            ActionType.VOTE,
            target_id=target_id,
            reasoning=result["reasoning"],
            metadata=trace_keys.loop_metadata_from_result(result),
        )

    def _record_vote_followups(self, memory_target: str, content_target: str, reasoning: str) -> None:
        self.memory.add_action("vote", memory_target, f"投{content_target}", reasoning)
        self._detect_speech_vote_mismatch()
        self._mark_active_intent_executed_if_target_phase_contains("VOTE")

    # ---- Night actions ----

    def attack(self) -> Decision:
        # Build WolfTeamView each night for coordinated wolf play
        if "wolf" in self.role.lower():
            known = getattr(self._view, "known_wolves", [])
            if known:
                try:
                    from backend.agents.cognitive.wolf_team import build_wolf_team_view

                    all_wolf_ids = [self.player_id] + [w.get("id", w.get("player_id", "")) for w in known]
                    all_alive = [p["id"] for p in self._view.players if p.get("alive")]
                    self._wolf_team_view = build_wolf_team_view(
                        wolf_ids=all_wolf_ids,
                        all_alive_ids=all_alive,
                        belief_tracker=self._tracker,
                        public_events=self._view.public_events,
                    )
                except Exception:
                    import logging

                    _logger = logging.getLogger(__name__)
                    _logger.warning(f"build_wolf_team_view failed for {self.player_name}, using None", exc_info=True)
                    self._wolf_team_view = None

        obs = self._observe()

        # ── Optimisation: skip LLM when there is only one legal target ──
        only_target = self._single_legal_target(obs)
        if self._skip_optimisations_enabled() and only_target:
            reasoning = f"唯一合法击杀目标 {only_target.seat}号:{only_target.name}，无需LLM决策"
            return self._night_decision({"target": only_target.id, "reasoning": reasoning}, ActionType.ATTACK)

        extra = self._build_wolf_extra()
        result = self._pipeline.run_night(obs, self.memory, extra)

        # Mark strategic intent as executed if this was the target phase
        self._mark_active_intent_executed_if_target_phase_contains("NIGHT", "WOLF")

        return self._night_decision(result, ActionType.ATTACK)

    def divine(self) -> Decision:
        obs = self._observe()

        # ── Optimisation: skip LLM when there is only one legal target ──
        only_target = self._single_legal_target(obs)
        if self._skip_optimisations_enabled() and only_target:
            reasoning = f"唯一合法查验目标 {only_target.seat}号:{only_target.name}，无需LLM决策"
            return self._night_decision({"target": only_target.id, "reasoning": reasoning}, ActionType.DIVINE)

        result = self._pipeline.run_night(obs, self.memory)
        return self._night_decision(result, ActionType.DIVINE)

    def guard(self) -> Decision:
        extra = ""
        if self._guard_history:
            extra = f"上一晚守护: {self._guard_history[-1]}\n不能连续两晚守护同一人。"
        else:
            extra = "第一晚守护，没有历史限制。"
        obs = self._observe()

        # ── Optimisation: skip LLM when there is only one legal target ──
        only_target = self._single_legal_target(obs)
        if only_target:
            reasoning = f"唯一合法守护目标 {only_target.seat}号:{only_target.name}，无需LLM决策"
            self._record_guard_protection(only_target.id)
            return self._night_decision({"target": only_target.id, "reasoning": reasoning}, ActionType.GUARD)

        result = self._pipeline.run_night(obs, self.memory, extra)
        decision = self._night_decision(result, ActionType.GUARD)
        if decision.target_id:
            self._record_guard_protection(decision.target_id)
        return decision

    def _record_guard_protection(self, target_id: str) -> None:
        self._guard_history.append(target_id)
        self.memory.role_state.setdefault("protections", []).append(f"D{self.memory.day}: {target_id}")

    def witch_act(self, victim_id: str | None) -> list[Decision]:
        # ── Optimisation: skip LLM when no potions available ──
        if self._skip_optimisations_enabled() and self._witch_save_used and self._witch_poison_used:
            return [self._decision(ActionType.SKIP, reasoning="双药已用，无需LLM决策")]

        lines = self._witch_status_lines(victim_id)

        obs = self._observe()
        targets = [self._player_label(p) for p in obs.alive if p.id != self.player_id]
        prompt = (
            format_observation(obs)
            + "\n\n"
            + self._strategy_bias_text("witch_act")
            + "\n\n"
            + "\n".join(lines)
            + "\n\n你是女巫，请决定本晚是否用药。"
            + "\n规则：一晚最多使用一瓶药；如果 save=true，poison_target 必须为 null。"
            + "\n如果不用药，输出 save=false 且 poison_target=null。"
            + f"\n可毒目标: {', '.join(targets) if targets else '无'}"
            + '\n只输出 JSON 对象：{"reasoning": "理由", "save": false, "poison_target": null}'
        )
        raw = self._pipeline.direct_call(prompt, max_tokens=360)
        try:
            data = self._parse_witch_json(raw)
        except ValueError:
            if self._strict_no_fallback:
                raise
            return [self._decision(ActionType.SKIP, reasoning="女巫输出解析失败")]

        data = self._repair_witch_decision_if_needed(data, obs, victim_id, targets)

        reasoning = str(data.get("reasoning") or "").strip()
        if not reasoning:
            raise RuntimeError("LLM witch decision missing reasoning")
        save, poison_text, no_poison = self._witch_decision_flags(data)

        if save and not victim_id:
            raise RuntimeError("LLM witch decision requested save without wolf victim")
        if save and self._witch_save_used:
            raise RuntimeError("LLM witch decision requested already-used antidote")
        if poison_text and not no_poison and self._witch_poison_used:
            raise RuntimeError("LLM witch decision requested already-used poison")
        if save and poison_text and not no_poison:
            raise RuntimeError("LLM witch decision attempted to use antidote and poison in one night")

        decisions: list[Decision] = []
        if save and victim_id:
            self._witch_save_used = True
            self.memory.role_state["save_used"] = True
            decisions.append(self._decision(ActionType.WITCH_SAVE, target_id=victim_id, reasoning=reasoning))
        elif poison_text and not no_poison:
            poison_id = self._resolve_target(poison_text)
            if not poison_id:
                raise RuntimeError(f"LLM returned unresolved poison target: {poison_text!r}")
            self._witch_poison_used = True
            decisions.append(self._decision(ActionType.WITCH_POISON, target_id=poison_id, reasoning=reasoning))
        else:
            decisions.append(self._decision(ActionType.SKIP, reasoning=reasoning))

        return decisions

    def _repair_witch_decision_if_needed(
        self,
        data: dict[str, Any],
        obs: Observation,
        victim_id: str | None,
        poison_targets: list[str],
    ) -> dict[str, Any]:
        error = self._witch_decision_error(data, victim_id)
        rounds = 0
        while error and rounds < self._MAX_REQUIRED_ACTION_REPAIR_ROUNDS:
            rounds += 1
            status_lines = self._witch_status_lines(victim_id)
            repair_prompt = (
                format_observation(obs)
                + "\n\n"
                + self._strategy_bias_text("witch_act")
                + "\n\n上一次女巫用药输出无法执行，原因: "
                + error
                + "\n上一次输出: "
                + self._json_for_prompt(data)
                + "\n当前药品状态:\n"
                + "\n".join(status_lines)
                + "\n规则：一晚最多使用一瓶药；已使用的药不能再次使用；如果 save=true，poison_target 必须为 null。"
                + "\n如果当前不适合或不能用药，输出 save=false 且 poison_target=null。"
                + f"\n可毒目标: {', '.join(poison_targets) if poison_targets else '无'}"
                + '\n请重新只输出 JSON 对象：{"reasoning": "理由", "save": false, "poison_target": null}'
            )
            raw = self._pipeline.direct_call(repair_prompt, max_tokens=300)
            data = self._parse_witch_json(raw)
            error = self._witch_decision_error(data, victim_id)
        return data

    def _witch_decision_error(self, data: dict[str, Any], victim_id: str | None) -> str:
        reasoning = str(data.get("reasoning") or "").strip()
        if not reasoning:
            return "缺少 reasoning"
        save, poison_text, no_poison = self._witch_decision_flags(data)
        if save and not victim_id:
            return "没有被刀玩家但请求使用解药"
        if save and self._witch_save_used:
            return "解药已使用但再次请求解药"
        if poison_text and not no_poison and self._witch_poison_used:
            return "毒药已使用但再次请求毒药"
        if save and poison_text and not no_poison:
            return "同一晚同时请求解药和毒药"
        return ""

    def _witch_decision_flags(self, data: dict[str, Any]) -> tuple[bool, str, bool]:
        save = bool(data.get("save"))
        poison = data.get("poison_target")
        poison_text = "" if poison is None else str(poison).strip()
        return save, poison_text, self._is_no_poison_target(poison_text)

    def _witch_status_lines(self, victim_id: str | None) -> list[str]:
        lines = [
            "解药已使用" if self._witch_save_used else "解药可用",
            "毒药已使用" if self._witch_poison_used else "毒药可用",
        ]
        if victim_id:
            victim = self._find_player(victim_id)
            if victim:
                lines.append(f"今晚被刀的是: {self._player_dict_label(victim)}")
        return lines

    @staticmethod
    def _parse_witch_json(text: str) -> dict[str, Any]:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"LLM witch decision did not contain JSON: {text[:120]!r}")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM witch decision JSON invalid: {text[:120]!r}") from exc
        if not isinstance(data, dict):
            raise ValueError("LLM witch decision JSON must be an object")
        return data

    def shoot(self) -> Decision:
        obs = self._observe()
        targets = self._player_labels(obs.alive)
        prompt = (
            format_observation(obs)
            + "\n\n"
            + self._strategy_bias_text("shoot")
            + f'\n\n你已死亡，可开枪带走一人。\n可选: {", ".join(targets)}\n输出 JSON: {{"reasoning": "理由", "target": "玩家名字"}}'
            "\n注意：猎人开枪阶段不能选择跳过、无、none、null、pass。必须从可选玩家中选择一名目标。"
        )

        result = self._pipeline.direct_call(prompt)
        parsed = parse_json_target(result)
        parsed_target = self._parsed_target_text(parsed)
        target_id = self._resolve_target(parsed_target)
        if not target_id:
            parsed = self._repair_required_shoot_target(obs, parsed)
            parsed_target = self._parsed_target_text(parsed)
            target_id = self._resolve_target(parsed_target)
        if not target_id:
            is_explicit_no_action = self._normalised_target_text(parsed_target) in self._NO_ACTION_TARGET_KEYWORDS
            if self._strict_no_fallback:
                detail = (
                    "explicit no-action is not legal for hunter shoot" if is_explicit_no_action else "unresolved target"
                )
                raise RuntimeError(f"LLM returned invalid shoot target ({detail}): {parsed['target']!r}")
            target_id = None
        return self._decision(ActionType.SHOOT, target_id=target_id, reasoning=parsed["reasoning"])

    def _repair_required_shoot_target(self, obs: Observation, parsed: dict[str, Any]) -> dict[str, Any]:
        """Ask the same LLM once to replace an invalid hunter target.

        This is a format/contract repair, not a heuristic fallback: the LLM
        must still choose a legal target and provide reasoning.
        """

        legal_targets = self._player_labels(obs.legal_targets or obs.alive)
        if not legal_targets:
            return parsed
        repair_prompt = (
            format_observation(obs)
            + "\n\n"
            + self._strategy_bias_text("shoot")
            + "\n\n上一次猎人开枪输出无法执行："
            + self._json_for_prompt(parsed)
            + "\n猎人开枪是强制目标行动，不能输出“无/跳过/none/null/pass/不行动”。"
            + f"\n合法目标仅限: {', '.join(legal_targets)}"
            + '\n请重新输出 JSON，格式必须为 {"reasoning": "为什么选择该目标", "target": "目标玩家名字或N号:名字"}。'
        )
        repaired = self._pipeline.direct_call(repair_prompt)
        return self._parse_required_target_repair(repaired, obs.legal_targets or obs.alive)

    def boom(self, targets: list[str] | None = None) -> Decision:
        """White Wolf King self-detonate — kill self + one target during day.

        The White Wolf King can choose to self-detonate, taking one other
        player with them. This is a strategic choice — the agent evaluates
        whether the situation warrants it via LLM reasoning.
        """
        obs = self._observe()
        target_list = self._player_labels(obs.alive)
        extra_parts = [
            "你是白狼王，可在白天自爆带走一名玩家。",
            f"可带走的目标: {', '.join(target_list)}",
            "如果认为当前局势自爆有利（比如能带走关键神职、扭转局势），"
            '输出 {{"reasoning": "自爆理由", "target": "目标玩家名字"}}',
            '如果认为不宜自爆，输出 {{"reasoning": "不自爆的理由", "target": "不爆"}}',
        ]
        prompt = format_observation(obs) + "\n\n" + "\n".join(extra_parts)
        bias_text = self._strategy_bias_text("boom")
        if bias_text:
            prompt = format_observation(obs) + "\n\n" + bias_text + "\n\n" + "\n".join(extra_parts)

        result = self._pipeline.direct_call(prompt)
        parsed = parse_json_target(result)
        raw_target = (parsed.get("target") or "").strip()

        # White Wolf King may choose NOT to self-detonate
        if self._is_boom_skip_target(raw_target):
            return self._decision(
                ActionType.SKIP,
                reasoning=parsed.get("reasoning", "不自爆"),
            )

        target_id = self._resolve_target(raw_target)
        if not target_id:
            if self._strict_no_fallback:
                raise RuntimeError(f"LLM returned unresolved boom target: {raw_target!r}")
            target_id = None
        return self._decision(
            ActionType.BOOM,
            target_id=target_id,
            reasoning=parsed.get("reasoning", ""),
        )

    def transfer_badge(self, candidates: list[str]) -> Decision:
        obs = self._observe()
        candidate_strs = []
        candidate_players = []
        for cid in candidates:
            p = self._find_player(cid)
            if p:
                candidate_players.append(p)
                candidate_strs.append(self._player_label(p))

        prompt = (
            format_observation(obs)
            + "\n\n"
            + self._strategy_bias_text("transfer_badge")
            + f'\n\n你已死亡，需将警徽移交给一名存活玩家。\n候选人: {", ".join(candidate_strs)}\n输出 JSON: {{"reasoning": "理由", "target": "玩家名字"}}'
        )

        result = self._pipeline.direct_call(prompt)
        parsed = parse_json_target(result)
        parsed_target = self._parsed_target_text(parsed)
        target_id = self._resolve_target(parsed_target)
        rounds = 0
        while (not target_id or target_id not in candidates) and rounds < self._MAX_REQUIRED_ACTION_REPAIR_ROUNDS:
            rounds += 1
            repair_prompt = (
                format_observation(obs)
                + "\n\n"
                + self._strategy_bias_text("transfer_badge")
                + "\n\n上一次警徽移交目标无法执行: "
                + self._json_for_prompt(parsed)
                + f"\n候选人仅限: {', '.join(candidate_strs)}"
                + '\n请重新只输出 JSON: {"reasoning": "理由", "target": "候选人名字或N号:名字"}'
            )
            repaired = self._pipeline.direct_call(repair_prompt)
            parsed = self._parse_required_target_repair(repaired, candidate_players)
            parsed_target = self._parsed_target_text(parsed)
            target_id = self._resolve_target(parsed_target)
        if not target_id or target_id not in candidates:
            if self._strict_no_fallback:
                raise RuntimeError(f"LLM returned unresolved badge target: {parsed_target!r}")
            target_id = None
        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=parsed["reasoning"])

    def finish(self, winner: str | None) -> None:
        self.memory.add_action("game_end", None, f"胜者: {winner}", "")
        # Trigger personal post-game reflection (opt-in via COGNITIVE_ENABLE_REFLECTION)
        self._reflect_on_game(winner)

    # === Internal Helpers ===

    def _observe(self) -> Observation:
        """Build observation from current view with belief tracking.

        Also syncs social model: contradictions from the belief tracker
        become deception signals, and vote alignment updates trust scores.
        """
        obs = observe(self._view, self.role, tracker=self._tracker)
        self._sync_social_from_tracker(obs)
        self._update_trust_from_events(obs)
        return obs

    def _strategy_bias_text(self, action: str) -> str:
        action_map = {
            "shoot": "shoot",
            "boom": "attack",
            "transfer_badge": "vote",
        }
        return build_strategy_bias_block(self._strategy_bias, action_map.get(action, action))

    # ---- Social Model Feeds ----

    def _sync_social_from_tracker(self, obs: Observation) -> None:
        """Feed 1: BeliefTracker contradictions → SocialModel deception signals.

        When multiple players claim the same unique role, all claimants
        get flagged for potential deception.
        """
        for c in obs.contradictions:
            for claimant_name in c.claimants:
                # Don't flag self
                if claimant_name == self.player_name:
                    continue
                signal = DeceptionSignal(
                    player_id=claimant_name,
                    signal_type="role_contradiction",
                    description=f"与{', '.join(c.claimants)}冲突声称是{c.role}",
                    severity=0.6,
                    day=obs.day,
                )
                self.memory.social_model.add_deception_signal(signal)

    def _update_trust_from_events(self, obs: Observation) -> None:
        """Feed 2: Vote alignment updates trust scores.

        Players who vote the same way gain slight trust.
        Players who vote against the agent lose slight trust.
        """
        # Vote alignment: same target → slight trust
        today_votes = [v for v in obs.votes if v.day == obs.day]
        my_vote = next(
            (v for v in today_votes if self._voter_identity_matches_self(v.voter_name, v.voter_id)),
            None,
        )
        if my_vote and my_vote.target_name:
            my_target = my_vote.target_name
            for v in today_votes:
                voter_name = v.voter_name or v.voter_id
                if self._voter_label_matches_self(voter_name):
                    continue
                if v.target_name == my_target:
                    self.memory.social_model.update_trust(
                        self.player_name,
                        voter_name,
                        +0.08,
                        f"D{obs.day}: 投票一致投{my_target}",
                        day=obs.day,
                    )
                elif my_target and v.target_name:
                    # Voted differently — slight distrust
                    self.memory.social_model.update_trust(
                        self.player_name,
                        voter_name,
                        -0.03,
                        f"D{obs.day}: 投票分歧",
                        day=obs.day,
                    )

        # Accusations in speeches: if someone names the agent as suspicious
        for speech in obs.speeches:
            if self._speech_from_other_accuses_self(speech):
                self.memory.social_model.update_trust(
                    self.player_name,
                    speech.player_name,
                    -0.10,
                    f"D{obs.day}: {speech.player_name}在发言中指控你",
                    day=obs.day,
                )

    def _detect_speech_vote_mismatch(self) -> None:
        """Feed 3: Check if the agent's own speech accused someone different
        from who they voted for, and record the mismatch for social tracking."""
        # Get recent speech and vote actions
        speech_actions = [a for a in self.memory.actions if a.action_type == "speech" and a.day == self.memory.day]
        vote_actions = [a for a in self.memory.actions if a.action_type == "vote" and a.day == self.memory.day]

        for speech_a in speech_actions:
            speech_text = speech_a.content
            # Extract named targets from speech (simple heuristic)
            speech_targets = set()
            for p in self._view.players:
                name = p.get("name", "")
                if name and name in speech_text:
                    # Check if mentioned in accusatory context
                    if self._speech_accuses_player(speech_text, name):
                        speech_targets.add(name)

            for vote_a in vote_actions:
                vote_target = vote_a.target
                if speech_targets and vote_target and vote_target not in speech_targets:
                    # Agent accused X in speech but voted Y
                    for st in list(speech_targets)[:1]:  # just record one mismatch
                        self.memory.social_model.detect_speech_vote_mismatch(
                            player_id=self.player_name,
                            speech_target=st,
                            vote_target=vote_target,
                            day=self.memory.day,
                        )

    def _has_meaningful_new_info_since_speech(self, obs) -> bool:
        """Check if there are meaningful new events since this agent's last speech.

        Returns True if there's a reason to re-evaluate the vote (new role claims,
        being accused, etc.). Returns False when it's safe to reuse the tentative vote.

        Used by Plan A optimisation (speech→vote skip).
        """
        my_speeches = [s for s in obs.speeches if s.player_id == self.player_id]
        if not my_speeches:
            # Agent hasn't spoken yet this day → must call LLM
            return True
        my_last_speech = my_speeches[-1]

        # Check for speeches AFTER this agent's last speech
        later_speeches = [
            s
            for s in obs.speeches
            if s.player_id != self.player_id and obs.speeches.index(s) > obs.speeches.index(my_last_speech)
        ]

        for speech in later_speeches:
            content = speech.content.lower()
            # Someone claimed a power role (预言家/女巫/守卫/猎人/白痴)
            if self._has_keyword(content, self._ROLE_CLAIM_KEYWORDS):
                return True
            # Someone accused this agent specifically
            if self._speech_accuses_self(content):
                return True
            # Major event: self-explosion, badge transfer, etc.
            if self._has_keyword(content, self._MAJOR_EVENT_KEYWORDS):
                return True

        # Check for new role claims from belief tracker
        for claim in getattr(obs, "role_claims", []) or []:
            if self._role_claim_requires_vote_rethink(claim):
                return True

        return False

    @staticmethod
    def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _speech_accuses_player(speech_text: str, name: str) -> bool:
        phrases = (f"投{name}", f"出{name}", f"{name}是狼", f"怀疑{name}", f"查杀{name}")
        return any(phrase in speech_text for phrase in phrases)

    def _speech_accuses_self(self, speech_content: str) -> bool:
        content = speech_content.lower()
        my_name = self.player_name.lower()
        return bool(my_name and my_name in content and self._has_keyword(content, self._SELF_ACCUSATION_KEYWORDS))

    def _speech_from_other_accuses_self(self, speech: Any) -> bool:
        return (
            self.player_name in speech.content
            and speech.player_name != self.player_name
            and self._has_keyword(speech.content, self._SPEECH_ACCUSATION_KEYWORDS)
        )

    def _role_claim_requires_vote_rethink(self, claim: Any) -> bool:
        return claim.player_name != self.player_name and "预言家" in str(getattr(claim, "claimed_role", "") or "")

    def _voter_identity_matches_self(self, voter_name: Any, voter_id: Any) -> bool:
        return voter_name == self.player_name or voter_id == self.player_id

    def _voter_label_matches_self(self, voter_label: Any) -> bool:
        return voter_label == self.player_name or voter_label == self.player_id

    def _decision(
        self,
        action_type: ActionType,
        target_id: str | None = None,
        speech: str | None = None,
        reasoning: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Decision:
        """Create a Decision with standard metadata."""
        meta = self._base_decision_metadata()
        if metadata:
            meta.update(metadata)
        direct_retrieved = trace_keys.knowledge_id_list(meta.get(trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS, []))
        if direct_retrieved:
            self._record_strategy_usage(direct_retrieved)
        self._merge_compat_loop_trace_metadata(meta)

        return Decision(
            actor_id=self.player_id,
            action_type=action_type,
            target_id=target_id,
            speech=speech,
            reasoning=reasoning[:200],
            metadata=meta,
        )

    def _merge_compat_loop_trace_metadata(self, meta: dict[str, Any]) -> None:
        # Prefer per-decision metadata carried from AgentLoop; the global trace
        # path remains only as compatibility for older Pipeline/direct callers.
        try:
            needs_compat_trace = not any(key in meta for key in trace_keys.DECISION_TRACE_KEYS)
            trace = get_last_loop_trace(self.player_id)
            if trace and not needs_compat_trace:
                trace = {}
            if trace:
                self._record_strategy_usage(trace_keys.compat_metadata_from_trace(meta, trace))
        except Exception:
            pass  # trace injection is best-effort

    def _base_decision_metadata(self) -> dict[str, Any]:
        provider = str(getattr(self._llm, "provider", "") or "")
        model = str(getattr(self._llm, "model", "") or "cognitive")
        return {
            "source": "llm",
            "provider": provider,
            "model": model,
            "fallback": False,
        }

    def _mark_active_intent_executed_if_target_phase_contains(self, *phase_tokens: str) -> None:
        active = self.memory.planner.get_active(self.memory.day, self.memory.phase)
        if active and all(token in active.target_phase for token in phase_tokens):
            self.memory.planner.mark_executed(self.memory.day, self.memory.phase)

    async def decide_with_fallback(
        self,
        action_type: str,
        player_view: Any,
        **kwargs: Any,
    ) -> Decision:
        """Execute a decision through the cognitive path.

        Strict mode raises on failure so LLM-only games do not silently
        degrade to heuristic or pass-through decisions.
        """
        import logging

        _log = logging.getLogger(__name__)

        # Primary: CognitiveAgent
        last_error: Exception | None = None
        try:
            return await self._decide_cognitive(action_type, player_view, **kwargs)
        except Exception as e:
            last_error = e
            _log.warning(f"CognitiveAgent.{action_type} failed for {self.player_name}: {e}")
            self._fallback_count += 1
            self._fallback_reasons.append(f"{action_type}: {type(e).__name__}")
            if self._strict_no_fallback:
                raise RuntimeError(
                    f"CognitiveAgent.{action_type} failed in LLM-only mode for {self.player_name}"
                ) from e

        if self._fallback_heuristic is not None:
            try:
                _log.info(f"Falling back to HeuristicAgent for {self.player_name}.{action_type}")
                decision = getattr(self._fallback_heuristic, action_type, lambda: None)()
                if decision is not None:
                    decision.metadata.update(self._fallback_metadata("heuristic", str(last_error)[:200]))
                    return decision
            except Exception as e2:
                _log.error(f"HeuristicAgent fallback also failed for {self.player_name}: {e2}")
                self._validation_error_count += 1

        # Absolute last resort: provide a pass/skip action
        if self._strict_no_fallback:
            raise RuntimeError(f"All fallbacks exhausted for {self.player_name}.{action_type}")

        _log.critical(f"Returning pass for {self.player_name}.{action_type}")
        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.SKIP,
            reasoning="fallback exhausted",
            metadata=self._fallback_metadata("pass", "all fallbacks exhausted"),
        )

    @staticmethod
    def _fallback_metadata(fallback_to: str, reason: str) -> dict[str, Any]:
        return {
            "fallback_used": True,
            "fallback_from": "cognitive",
            "fallback_to": fallback_to,
            "fallback_reason": reason,
        }

    async def _decide_cognitive(
        self,
        action_type: str,
        player_view: Any,
        **kwargs: Any,
    ) -> Decision:
        """Execute cognitive decision (internal, called by decide_with_fallback)."""
        self._view = player_view
        method = self._cognitive_action_method(action_type)
        return method(**kwargs) if kwargs else method()

    def _cognitive_action_method(self, action_type: str) -> Any:
        method_map = {
            "talk": self.talk,
            "vote": self.vote,
            "attack": self.attack,
            "divine": self.divine,
            "guard": self.guard,
            "shoot": self.shoot,
            "boom": self.boom,
            "witch_act": self.witch_act,
            "transfer_badge": self.transfer_badge,
        }
        method = method_map.get(action_type)
        if method is None:
            raise ValueError(f"Unknown action_type: {action_type}")
        return method

    # Night actions where "skip" is a valid strategic choice
    _SKIP_NIGHT_KEYWORDS = {
        "空守",
        "不守",
        "跳过",
        "空过",
        "放弃",
        "不救",
        "不用",
        "不毒",
        "不验",
        "不打",
        "不刀",
        "不查",
        "none",
        "null",
        "skip",
        "无",
        "空",
        "pass",
        "NONE",
        "None",
    }

    def _night_decision(self, result: dict[str, str], action_type: ActionType) -> Decision:
        """Create a Decision for a night action.

        LLM-only mode requires a legal target for night actions that the engine
        requests. Local target synthesis would hide empty or invalid model
        output, so strict mode raises instead.
        """
        target_id: str | None = None
        repair_reason = ""
        for _ in range(self._MAX_REQUIRED_ACTION_REPAIR_ROUNDS + 1):
            target_id, repair_reason = self._required_night_target_status(result)
            if not repair_reason:
                break
            result = self._repair_required_night_target(result, action_type, repair_reason)

        raw_target = (result.get("target") or "").strip()
        if repair_reason == "skip keyword or empty required target":
            if self._strict_no_fallback:
                raise RuntimeError(f"LLM returned skip keyword for required {action_type.value} target: {raw_target!r}")
            target_id = None
        elif repair_reason == "unresolved required target":
            if self._strict_no_fallback:
                raise RuntimeError(f"LLM returned unresolved {action_type.value} target: {result['target']!r}")
        elif repair_reason == "target outside legal target set":
            target_id = self._resolve_target(raw_target)
            if self._strict_no_fallback:
                raise RuntimeError(
                    f"LLM returned illegal {action_type.value} target: {result['target']!r} -> {target_id!r}"
                )
            target_id = None

        return self._decision(
            action_type,
            target_id=target_id,
            reasoning=result.get("reasoning", ""),
            metadata=trace_keys.loop_metadata_from_result(result),
        )

    def _required_night_target_status(self, result: dict[str, str]) -> tuple[str | None, str]:
        raw_target = (result.get("target") or "").strip()
        reasoning = str(result.get("reasoning", "") or "")
        reasoning_mentions_skip = any(keyword and keyword in reasoning for keyword in self._SKIP_NIGHT_KEYWORDS)
        if raw_target in self._SKIP_NIGHT_KEYWORDS or (not raw_target and reasoning_mentions_skip):
            return None, "skip keyword or empty required target"

        target_id = self._resolve_target(raw_target)
        if not target_id:
            return None, "unresolved required target"
        if target_id not in self._legal_target_ids():
            return target_id, "target outside legal target set"
        return target_id, ""

    def _repair_required_night_target(
        self,
        result: dict[str, str],
        action_type: ActionType,
        reason: str,
    ) -> dict[str, str]:
        """Ask the LLM once to repair a required night target."""

        if not self._view:
            return result
        legal_targets = getattr(self._view, "legal_targets", []) or []
        if not legal_targets:
            return result
        legal_target_lines = [self._player_label(player) for player in legal_targets if player.get("id")]
        if not legal_target_lines:
            return result

        obs = self._observe()
        repair_prompt = (
            format_observation(obs)
            + f"\n\n上一次夜间行动无法执行，原因: {reason}。"
            + "\n上一次输出: "
            + self._json_for_prompt(result)
            + f"\n当前动作: {action_type.value}。这是强制目标行动，不能输出“无/跳过/none/null/pass/不行动”。"
            + f"\n合法目标仅限: {', '.join(legal_target_lines)}"
            + '\n请重新输出 JSON，格式必须为 {"reasoning": "为什么选择该目标", "target": "目标玩家名字或N号:名字"}。'
        )
        repaired = self._pipeline.direct_call(repair_prompt)
        return self._parse_required_target_repair(repaired, legal_targets)

    def _parse_required_target_repair(self, text: str, legal_targets: list[Any]) -> dict[str, str]:
        """Parse a repaired target only when the LLM names a legal target."""

        parsed = parse_json_target(text)
        if self._resolve_target(parsed.get("target", "")) in self._legal_target_ids():
            return parsed

        for player in legal_targets:
            name, seat = self._player_name_and_seat(player)
            if not name:
                continue
            if self._required_target_text_matches_player(text, name, seat):
                reasoning = parsed.get("reasoning") or text.strip()[:300] or "required_target_repair_text_match"
                return {"target": name, "reasoning": reasoning}
        return parsed

    @staticmethod
    def _required_target_text_matches_player(text: str, name: str, seat: str) -> bool:
        patterns = [re.escape(name)]
        if seat:
            patterns.extend([rf"(?<!\d){re.escape(seat)}\s*号", rf"seat\s*{re.escape(seat)}\b"])
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    def _legal_target_ids(self) -> set[str]:
        if not self._view:
            return set()
        return {str(p.get("id", "") or "") for p in getattr(self._view, "legal_targets", []) if p.get("id")}

    def _resolve_target(self, name: str) -> str | None:
        """Resolve player name to player id."""
        if not name:
            return None
        candidate = self._normalised_target_text(name, strip_mention=True)
        # No-action keywords: agent explicitly chooses not to act
        if candidate in self._NO_ACTION_TARGET_KEYWORDS:
            return None
        for p in self._candidate_players_for_target_resolution():
            if self._target_matches_player(candidate, p):
                return p["id"]
        return None

    def _candidate_players_for_target_resolution(self) -> list[dict[str, Any]]:
        visible_players = list(getattr(self._view, "players", []) or [])
        legal_players = list(getattr(self._view, "legal_targets", []) or [])
        by_id = {str(p.get("id", "") or ""): p for p in visible_players}
        for p in legal_players:
            player_id = str(p.get("id", "") or "")
            by_id.setdefault(player_id, p)
        return list(by_id.values())

    @staticmethod
    def _target_matches_player(candidate: str, player: dict[str, Any]) -> bool:
        player_name = str(player.get("name", "")).strip()
        player_id = str(player.get("id", "")).strip()
        seat = str(player.get("seat", "")).strip()
        seat_label = f"{seat}号" if seat else ""
        player_name_lower = player_name.lower()
        player_id_lower = player_id.lower()
        seat_label_lower = seat_label.lower()
        return (
            candidate == player_name_lower
            or candidate == player_id_lower
            or candidate == seat
            or candidate == seat_label_lower
            or (player_name_lower and player_name_lower in candidate)
            or (seat_label_lower and seat_label_lower in candidate)
        )

    @staticmethod
    def _normalised_target_text(value: Any, *, strip_mention: bool = False) -> str:
        text = str(value or "").strip().lower()
        return text.lstrip("@") if strip_mention else text

    @staticmethod
    def _parsed_target_text(parsed: dict[str, Any]) -> str:
        return str(parsed.get("target") or "").strip()

    @staticmethod
    def _json_for_prompt(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @classmethod
    def _player_labels(cls, players: list[Any]) -> list[str]:
        return [cls._player_label(player) for player in players]

    @classmethod
    def _player_label(cls, player: Any) -> str:
        if isinstance(player, dict):
            return cls._player_dict_label(player)
        return cls._player_info_label(player)

    @staticmethod
    def _player_info_label(player: Any) -> str:
        return f"{player.seat}号:{player.name}"

    @staticmethod
    def _player_dict_label(player: dict[str, Any]) -> str:
        return f"{player.get('seat', '?')}号:{player.get('name', '')}"

    @staticmethod
    def _player_name_and_seat(player: Any) -> tuple[str, str]:
        if hasattr(player, "name"):
            return str(getattr(player, "name", "") or ""), str(getattr(player, "seat", "") or "")
        return str(player.get("name", "") or ""), str(player.get("seat", "") or "")

    @classmethod
    def _is_no_poison_target(cls, value: Any) -> bool:
        return cls._normalised_target_text(value) in cls._WITCH_NO_POISON_KEYWORDS

    @classmethod
    def _is_boom_skip_target(cls, value: Any) -> bool:
        text = cls._normalised_target_text(value)
        return not text or text in cls._BOOM_SKIP_KEYWORDS

    def _find_player(self, player_id: str) -> dict[str, Any] | None:
        """Find player dict by id."""
        for p in self._view.players:
            if p["id"] == player_id:
                return p
        return None

    def _build_wolf_extra(self) -> str:
        """Build extra context for wolf kill decisions.

        Uses only legally visible information:
        - known_wolves from PlayerView (teammates' private_dict)
        - Public events (speeches, votes, deaths)
        - BeliefTracker inferences
        - WolfTeamView (legal wolf-team context, no fixed tactic recommendations)
        - StrategicIntent (multi-turn plans)

        Does NOT access any non-wolf player's true role or alignment.
        """
        parts = []
        # Use known_wolves from view (only populated for wolf-aligned players)
        known_wolves = getattr(self._view, "known_wolves", [])
        if known_wolves:
            wolf_names = [w.get("name", w.get("id", "?")) for w in known_wolves]
            parts.append(f"狼队友: {', '.join(wolf_names)}")

        # Optional LLM-declared tactic labels. The non-strategy layer never
        # assigns or describes a fixed wolf plan.
        if self._wolf_tactics:
            my_tactic = self._wolf_tactics.get(self.player_id, "")
            if my_tactic:
                parts.append(f"你的狼队标签: {my_tactic}")

        # Include legal wolf-team context if available
        if self._wolf_team_view is not None:
            from backend.agents.cognitive.wolf_team import build_wolf_coordination_context

            coord_ctx = build_wolf_coordination_context(self.player_id, self._wolf_team_view)
            parts.append(coord_ctx)

        parts.append("作为狼人阵营的一员，选择击杀目标。")
        parts.append("注意：你只能基于公开发言、投票和狼队内部信息做判断，不能查看其他玩家的真实身份。")
        return "\n".join(parts)

    def _record_strategy_usage(self, doc_ids: list[str]) -> None:
        """Best-effort record of auto-injected strategy knowledge usage."""
        if not doc_ids or not self._game_id:
            return
        try:
            from backend.db.persist import record_knowledge_usage

            for doc_id in doc_ids:
                if not doc_id:
                    continue
                record_knowledge_usage(
                    {
                        "game_id": self._game_id,
                        "player_id": self.player_id,
                        "knowledge_doc_id": doc_id,
                        "retrieved": True,
                        "used": False,
                        "metadata": {
                            "phase": self._view.phase if self._view else "",
                            "role": self.role,
                            "action_type": "auto_injected",
                            "feedback_stage": "retrieval_trace",
                        },
                    }
                )
        except Exception:
            pass  # best-effort, never block decision flow

    def _reflect_on_game(self, winner: str | None) -> None:
        """Trigger post-game personal reflection and persist to PostgreSQL.

        Controlled via COGNITIVE_ENABLE_REFLECTION (default: enabled).
        When enabled, collects real game events from the agent's view +
        BeliefTracker, runs an MBTI-differentiated LLM reflection, and
        writes structured knowledge docs as 'candidate' status.
        Set COGNITIVE_ENABLE_REFLECTION=false to disable.

        Failures are logged but never raised — reflection is best-effort
        and must not block game completion.
        """
        if not self._reflection_enabled():
            return
        import logging

        _log = logging.getLogger(__name__)

        try:
            from backend.agents.cognitive.reflect import Reflector
            from backend.agents.cognitive.reflect import save_reflections_to_db

            # Determine win/loss
            won = self._did_agent_win(winner)

            # Collect real game events from view + belief tracker
            game_events = self._collect_game_events()
            decisions = self._collect_decisions()

            agent_state = self._reflection_agent_state(won, decisions, game_events)

            reflector = Reflector(self._llm)
            results = reflector.reflect_game(
                game_id=self._reflection_game_id(),
                agent_states=[agent_state],
            )
            if results:
                saved = save_reflections_to_db(results, self._reflection_game_id())
                if saved > 0:
                    _log.info(self._reflection_success_log_message(saved))
                else:
                    _log.warning(f"Agent {self.player_name}: reflection produced no new docs")
                    if self._require_knowledge_write():
                        _log.error("STRICT FAIL: Reflection produced 0 knowledge docs")
        except Exception as e:
            _log.error(f"Reflection failed for {self.player_name}: {e}")

    def _did_agent_win(self, winner: str | None) -> bool:
        if not (winner and self._profile):
            return False
        alignment = "wolf" if "wolf" in self.role.lower() else "village"
        return winner == alignment

    def _reflection_enabled(self=None) -> bool:
        if isinstance(self, CognitiveAgent) and "COGNITIVE_ENABLE_REFLECTION" in self._feature_flags:
            return bool(self._feature_flags["COGNITIVE_ENABLE_REFLECTION"])
        val = _os.getenv("COGNITIVE_ENABLE_REFLECTION", "").strip().lower()
        return val not in ("0", "false", "no", "off")

    @staticmethod
    def _require_knowledge_write() -> bool:
        return _os.getenv("REQUIRE_KNOWLEDGE_WRITE", "").lower() == "true"

    def _reflection_agent_state(
        self,
        won: bool,
        decisions: list[dict[str, Any]],
        game_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "role": self.role,
            "persona": self._profile.persona if self._profile else None,
            "mind": self._profile.mind if self._profile else None,
            "won": won,
            "decisions": decisions,
            "game_events": game_events,
        }

    def _profile_mbti_label(self) -> str:
        return self._profile.persona.mbti if self._profile and self._profile.persona else "?"

    def _reflection_success_log_message(self, saved: int) -> str:
        return (
            f"Agent {self.player_name}({self.role}, "
            f"MBTI={self._profile_mbti_label()}) "
            f"reflection: {saved} knowledge docs saved to PostgreSQL"
        )

    def _reflection_game_id(self) -> str:
        return self._game_id or "unknown"

    def _collect_game_events(self) -> list[dict[str, Any]]:
        """Collect game events visible to this agent for post-game reflection."""
        events = []
        if self._view is None:
            return events

        # Public events (what everyone sees)
        for e in self._view.public_events[-30:]:
            etype = e.get("type", "")
            events.append(
                {
                    "type": etype,
                    "day": e.get("day", 0),
                    "phase": e.get("phase", ""),
                    "description": self._public_event_description(e),
                }
            )

        # Private events (what only this agent knows)
        for e in self._view.private_events[-10:]:
            private_event = self._private_event_reflection_entry(e)
            if private_event:
                events.append(private_event)

        # Belief tracker findings
        if self._tracker.contradictions:
            for c in self._tracker.contradictions:
                events.append(self._contradiction_reflection_entry(c, self._view.day if self._view else 0))

        return events

    @staticmethod
    def _public_event_description(event: dict[str, Any]) -> str:
        payload = event.get("payload", {}) or {}
        etype = event.get("type", "")
        if etype == "CHAT_MESSAGE":
            speaker = payload.get("actor_name", "") or payload.get("speaker", "")
            speech = (payload.get("speech", "") or "")[:120]
            return f"{speaker}: {speech}"
        if etype == "VOTE_CAST":
            voter = payload.get("voter_name", "")
            target = payload.get("target_name", "")
            return f"{voter} 投票给 {target}"
        if etype == "PLAYER_DIED":
            name = payload.get("player_name", "")
            cause = payload.get("cause", payload.get("reason", "?"))
            return f"{name} 死亡({cause})"
        return str(payload)[:120]

    @staticmethod
    def _private_event_reflection_entry(event: dict[str, Any]) -> dict[str, Any] | None:
        payload = event.get("payload", {}) or {}
        kind = payload.get("kind", "")
        if kind == "seer_result":
            target = payload.get("target_name", "?")
            is_wolf = payload.get("is_wolf", False)
            return {
                "type": "PRIVATE_SEER",
                "day": event.get("day", 0),
                "description": f"查验 {target}: {'狼人' if is_wolf else '好人'}",
            }
        if kind == "witch_save":
            return {
                "type": "PRIVATE_WITCH",
                "day": event.get("day", 0),
                "description": f"解药救人: {payload.get('target_name', '?')}",
            }
        return None

    @staticmethod
    def _contradiction_reflection_entry(contradiction: Any, day: int) -> dict[str, Any]:
        return {
            "type": "CONTRADICTION",
            "day": day,
            "description": contradiction.description,
        }

    def _collect_decisions(self) -> list[dict[str, Any]]:
        """Collect this agent's decisions for post-game reflection."""
        return [self._decision_reflection_entry(action) for action in self.memory.get_recent_actions(30)]

    @staticmethod
    def _decision_reflection_entry(action: Any) -> dict[str, Any]:
        return {
            "action_type": action.action_type,
            "target": action.target or "",
            "speech": action.content,
            "day": action.day,
            "phase": action.phase,
        }
