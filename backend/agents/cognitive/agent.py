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
import os
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.humanization import HumanizationProfile, build_humanization_profile
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.agent_loop import get_last_loop_trace
from backend.agents.cognitive.observe import (
    Observation, BeliefTracker, observe, format_observation,
)
from backend.agents.cognitive.pipeline import Pipeline, parse_json_target, parse_json_array
from backend.agents.cognitive.planner import StrategicIntent
from backend.agents.cognitive.profiles import Profile, get_profile
from backend.agents.cognitive.prompts import build_system_prompt
from backend.agents.cognitive.social_model import DeceptionSignal
from backend.engine.models import Decision, ActionType


class CognitiveAgent:
    """Werewolf agent using Observe-Think-Act cognitive architecture.

    Production-grade: integrates Character system, BeliefTracker, Playbooks,
    Humanization, and Strategy Bias.

    LLM-only game mode: failures raise instead of degrading to heuristic decisions.
    Implements the full Agent protocol.
    """

    def __init__(
        self,
        player_id: str,
        role: str,
        llm: Runnable,
        player_name: str = "",
        player_seat: int = 0,
        profile: Optional[Profile] = None,
        strategy_bias: Optional[Dict[str, List[str]]] = None,
        fallback_heuristic: Any = None,
        strict_no_fallback: bool = True,
    ):
        self.player_id = player_id
        self.role = role
        self._llm = llm
        self.player_name = player_name
        self.player_seat = player_seat

        # Profile (WHO the agent is — integrated Character system)
        self._profile = profile or get_profile(role)

        # Humanization (behavioral parameters derived from persona + mind)
        self._humanization = build_humanization_profile(
            self._profile.persona, self._profile.mind
        )

        # System prompt (built once from Profile.to_system_intro())
        self._system_prompt = build_system_prompt(role, self._profile)

        # Strategy bias (forced policy for A/B testing)
        self._strategy_bias = strategy_bias or {}

        # Fallback configuration
        self._fallback_heuristic = fallback_heuristic
        self._strict_no_fallback = strict_no_fallback

        # Fallback tracking (for monitoring)
        self._fallback_count = 0
        self._fallback_reasons: list[str] = []
        self._validation_error_count = 0

        # Pipeline (stateless cognitive engine — now persona-aware)
        self._pipeline = Pipeline(
            llm, self._system_prompt, self._strategy_bias,
            persona_mbti=(self._profile.persona.mbti if self._profile.persona else ""),
            persona_style=(self._profile.persona.style_label if self._profile.persona else ""),
        )

        # Memory (persists across rounds — includes humanization + playbook)
        self.memory = Memory(player_id, role, humanization=self._humanization)

        # BeliefTracker (stateful claim/contradiction/vote tracking)
        self._tracker = BeliefTracker()

        # Game state (set by engine via initialize/update)
        self._view: Any = None

        # Role-specific tracking
        self._guard_history: List[str] = []
        self._witch_save_used = False
        self._witch_poison_used = False

        # Speech memory (anti-repeat)
        self._today_speech_count = 0

        # Game tracking (for post-game reflection)
        self._game_id = ""
        self._turn_phase = ""  # Track phase changes for analysis cache invalidation

        # Wolf team coordination (legal visible information, no fixed tactics)
        self._wolf_team_view: Any = None
        self._wolf_tactics: Dict[str, str] = {}

        # Speech targets for social model (speech-vote mismatch detection)
        self._last_speech_targets: List[str] = []

    # === Agent Protocol ===

    def initialize(self, view: Any, game_setting: dict) -> None:
        self._view = view
        self.player_name = view.self_player.get("name", self.player_id)
        self.player_seat = view.self_player.get("seat", 0)
        # Track game_id for post-game reflection
        self._game_id = getattr(view, "game_id", "") or str(game_setting.get("game_id", ""))
        self._tracker = BeliefTracker()

        # Wire wolf team coordination with legally visible teammate list only.
        if "wolf" in self.role.lower():
            known = getattr(view, 'known_wolves', [])
            if known:
                all_wolf_ids = [self.player_id] + [
                    w.get("id", w.get("player_id", "")) for w in known
                    if w.get("id", w.get("player_id", "")) != self.player_id
                ]
                alive_ids = [p["id"] for p in view.players if p.get("alive")]

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
            1 for e in self._view.public_events
            if e.get("day") == self._view.day
            and e.get("type") == "CHAT_MESSAGE"
            and e.get("phase") == self._view.phase
        )
        is_first = today_chat_count == 0
        is_last_words = self._view.phase == "DAY_LAST_WORDS"

        raw = self._pipeline.run_speech(obs, self.memory, is_first, is_last_words)

        # Parse multi-bubble speech
        segments = parse_json_array(raw)
        if not segments or (len(segments) == 1 and len(segments[0]) < 3):
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning(
                f"Speech parse fallback for {self.player_name}({self._profile.role}): "
                f"raw_len={len(raw)}, segments_parsed={len(segments) if segments else 0}"
            )
            speech = raw.strip()[:500] or "我暂时没有更多信息，先听大家发言。"
            segments = [speech]

        self.memory.add_action("speech", None, segments[0], "")
        self.memory.remember_opening(segments)
        self._today_speech_count += len(segments)

        # Record speech content for social model mismatch detection
        self._last_speech_targets = segments

        # Mark strategic intent as executed if this was the target phase
        active = self.memory.planner.get_active(self.memory.day, self.memory.phase)
        if active and "SPEECH" in active.target_phase:
            self.memory.planner.mark_executed(self.memory.day, self.memory.phase)

        return self._decision(
            ActionType.TALK,
            speech="\n".join(segments),
            metadata={"segments": segments, "segment_count": len(segments)},
        )

    # ---- Vote ----

    def vote(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_vote(
            obs, self.memory,
            vote_temperature=self._humanization.vote_temperature,
        )
        target_id = self._resolve_target(result["target"])
        if not target_id and self._strict_no_fallback:
            raise RuntimeError(f"LLM returned unresolved vote target: {result['target']!r}")
        self.memory.add_action("vote", result["target"], f"投{result['target']}", result["reasoning"])

        # Feed 3: Detect speech-vote mismatch and update social model
        self._detect_speech_vote_mismatch()

        # Mark strategic intent as executed if this was the target phase
        active = self.memory.planner.get_active(self.memory.day, self.memory.phase)
        if active and "VOTE" in active.target_phase:
            self.memory.planner.mark_executed(self.memory.day, self.memory.phase)

        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=result["reasoning"])

    # ---- Night actions ----

    def attack(self) -> Decision:
        # Build WolfTeamView each night for coordinated wolf play
        if "wolf" in self.role.lower():
            known = getattr(self._view, 'known_wolves', [])
            if known:
                try:
                    from backend.agents.cognitive.wolf_team import build_wolf_team_view
                    all_wolf_ids = [self.player_id] + [
                        w.get("id", w.get("player_id", "")) for w in known
                    ]
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
                    _logger.warning(
                        f"build_wolf_team_view failed for {self.player_name}, "
                        f"using None", exc_info=True
                    )
                    self._wolf_team_view = None

        obs = self._observe()
        extra = self._build_wolf_extra()
        result = self._pipeline.run_night(obs, self.memory, extra)

        # Mark strategic intent as executed if this is the target phase
        active = self.memory.planner.get_active(self.memory.day, self.memory.phase)
        if active and "NIGHT" in active.target_phase and "WOLF" in active.target_phase:
            self.memory.planner.mark_executed(self.memory.day, self.memory.phase)

        return self._night_decision(result, ActionType.ATTACK)

    def divine(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_night(obs, self.memory)
        return self._night_decision(result, ActionType.DIVINE)

    def guard(self) -> Decision:
        extra = ""
        if self._guard_history:
            extra = f"上一晚守护: {self._guard_history[-1]}\n不能连续两晚守护同一人。"
        else:
            extra = "第一晚守护，没有历史限制。"
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

        result = self._pipeline.direct_call(prompt)
        parsed = parse_json_target(result)
        target_id = self._resolve_target(parsed["target"])
        if not target_id and self._strict_no_fallback:
            raise RuntimeError(f"LLM returned unresolved shoot target: {parsed['target']!r}")
        target_id = target_id or (self._view.players[0]["id"] if self._view.players else None)
        return self._decision(ActionType.SHOOT, target_id=target_id, reasoning=parsed["reasoning"])

    def boom(self, targets: list[str] | None = None) -> Decision:
        """White Wolf King self-detonate — kill self + one target during day.

        The White Wolf King can choose to self-detonate, taking one other
        player with them. This is a strategic choice — the agent evaluates
        whether the situation warrants it via LLM reasoning.
        """
        obs = self._observe()
        target_list = [f"{p.seat}号:{p.name}" for p in obs.alive]
        extra_parts = [
            "你是白狼王，可在白天自爆带走一名玩家。",
            f"可带走的目标: {', '.join(target_list)}",
            "如果认为当前局势自爆有利（比如能带走关键神职、扭转局势），"
            "输出 {{\"reasoning\": \"自爆理由\", \"target\": \"目标玩家名字\"}}",
            "如果认为不宜自爆，输出 {{\"reasoning\": \"不自爆的理由\", \"target\": \"不爆\"}}",
        ]
        prompt = format_observation(obs) + "\n\n" + "\n".join(extra_parts)

        result = self._pipeline.direct_call(prompt)
        parsed = parse_json_target(result)
        raw_target = (parsed.get("target") or "").strip()

        # White Wolf King may choose NOT to self-detonate
        if not raw_target or raw_target in ("不爆", "不自爆", "放弃", "不炸", "跳过"):
            return self._decision(
                ActionType.SKIP,
                reasoning=parsed.get("reasoning", "不自爆"),
            )

        target_id = self._resolve_target(raw_target)
        if not target_id and self._strict_no_fallback:
            raise RuntimeError(f"LLM returned unresolved boom target: {raw_target!r}")
        target_id = target_id or (self._view.players[0]["id"] if self._view.players else None)
        return self._decision(
            ActionType.BOOM,
            target_id=target_id,
            reasoning=parsed.get("reasoning", ""),
        )

    def transfer_badge(self, candidates: List[str]) -> Decision:
        obs = self._observe()
        candidate_strs = []
        for cid in candidates:
            p = self._find_player(cid)
            if p:
                candidate_strs.append(f"{p.get('seat','?')}号:{p.get('name','')}")

        prompt = format_observation(obs) + f"\n\n你已死亡，需将警徽移交给一名存活玩家。\n候选人: {', '.join(candidate_strs)}\n输出 JSON: {{\"reasoning\": \"理由\", \"target\": \"玩家名字\"}}"

        result = self._pipeline.direct_call(prompt)
        parsed = parse_json_target(result)
        target_id = self._resolve_target(parsed["target"])
        if not target_id and self._strict_no_fallback:
            raise RuntimeError(f"LLM returned unresolved badge target: {parsed['target']!r}")
        target_id = target_id or (candidates[0] if candidates else None)
        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=parsed["reasoning"])

    def finish(self, winner: Optional[str]) -> None:
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
            (v for v in today_votes if v.voter_name == self.player_name
             or v.voter_id == self.player_id),
            None,
        )
        if my_vote and my_vote.target_name:
            my_target = my_vote.target_name
            for v in today_votes:
                voter_name = v.voter_name or v.voter_id
                if voter_name == self.player_name or voter_name == self.player_id:
                    continue
                if v.target_name == my_target:
                    self.memory.social_model.update_trust(
                        self.player_name, voter_name, +0.08,
                        f"D{obs.day}: 投票一致投{my_target}",
                        day=obs.day,
                    )
                elif my_target and v.target_name:
                    # Voted differently — slight distrust
                    self.memory.social_model.update_trust(
                        self.player_name, voter_name, -0.03,
                        f"D{obs.day}: 投票分歧",
                        day=obs.day,
                    )

        # Accusations in speeches: if someone names the agent as suspicious
        for speech in obs.speeches:
            if self.player_name in speech.content and speech.player_name != self.player_name:
                # Check for accusatory language
                accusatory = any(w in speech.content for w in
                    ["狼", "坏人", "可疑", "票", "出", "查杀", "铁狼"])
                if accusatory:
                    self.memory.social_model.update_trust(
                        self.player_name, speech.player_name, -0.10,
                        f"D{obs.day}: {speech.player_name}在发言中指控你",
                        day=obs.day,
                    )

    def _detect_speech_vote_mismatch(self) -> None:
        """Feed 3: Check if the agent's own speech accused someone different
        from who they voted for, and record the mismatch for social tracking."""
        # Get recent speech and vote actions
        speech_actions = [a for a in self.memory.actions
                          if a.action_type == "speech" and a.day == self.memory.day]
        vote_actions = [a for a in self.memory.actions
                        if a.action_type == "vote" and a.day == self.memory.day]

        for speech_a in speech_actions:
            speech_text = speech_a.content
            # Extract named targets from speech (simple heuristic)
            speech_targets = set()
            for p in self._view.players:
                name = p.get("name", "")
                if name and name in speech_text:
                    # Check if mentioned in accusatory context
                    for phrase in [f"投{name}", f"出{name}", f"{name}是狼",
                                   f"怀疑{name}", f"查杀{name}"]:
                        if phrase in speech_text:
                            speech_targets.add(name)
                            break

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

    def _decision(
        self,
        action_type: ActionType,
        target_id: Optional[str] = None,
        speech: Optional[str] = None,
        reasoning: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Decision:
        """Create a Decision with standard metadata."""
        provider = str(getattr(self._llm, "provider", "") or "")
        model = str(getattr(self._llm, "model", "") or "cognitive")
        meta = {
            "source": "llm",
            "provider": provider,
            "model": model,
            "fallback": False,
        }
        if metadata:
            meta.update(metadata)

        # Inject agent-loop tool trace + auto-injected strategies
        try:
            trace = get_last_loop_trace(self.player_id)
            if trace:
                if trace.get("tool_trace"):
                    meta["_tool_trace"] = trace["tool_trace"]
                if trace.get("auto_injected_strategies"):
                    meta["_auto_injected_strategies"] = trace["auto_injected_strategies"]
                    meta["retrieval_used"] = True
                # Use merged retrieved_knowledge_ids (auto-injected + tool-called) if available
                merged = trace.get("retrieved_knowledge_ids", trace.get("auto_injected_strategies", []))
                if merged:
                    meta["retrieved_knowledge_ids"] = merged
                # Best-effort: record knowledge usage for all retrieved strategies
                self._record_strategy_usage(merged)
        except Exception:
            pass  # trace injection is best-effort

        return Decision(
            actor_id=self.player_id,
            action_type=action_type,
            target_id=target_id,
            speech=speech,
            reasoning=reasoning[:200],
            metadata=meta,
        )

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
            _log.warning(
                f"CognitiveAgent.{action_type} failed for {self.player_name}: {e}"
            )
            self._fallback_count += 1
            self._fallback_reasons.append(f"{action_type}: {type(e).__name__}")
            if self._strict_no_fallback:
                raise RuntimeError(
                    f"CognitiveAgent.{action_type} failed in LLM-only mode for {self.player_name}"
                ) from e

        if self._fallback_heuristic is not None:
            try:
                _log.info(
                    f"Falling back to HeuristicAgent for {self.player_name}.{action_type}"
                )
                decision = getattr(self._fallback_heuristic, action_type, lambda: None)()
                if decision is not None:
                    decision.metadata["fallback_used"] = True
                    decision.metadata["fallback_from"] = "cognitive"
                    decision.metadata["fallback_to"] = "heuristic"
                    decision.metadata["fallback_reason"] = str(last_error)[:200]
                    return decision
            except Exception as e2:
                _log.error(
                    f"HeuristicAgent fallback also failed for {self.player_name}: {e2}"
                )
                self._validation_error_count += 1

        # Absolute last resort: provide a pass/skip action
        if self._strict_no_fallback:
            raise RuntimeError(
                f"All fallbacks exhausted for {self.player_name}.{action_type}"
            )

        _log.critical(f"Returning pass for {self.player_name}.{action_type}")
        return Decision(
            actor_id=self.player_id,
            action_type=ActionType.SKIP,
            reasoning="fallback exhausted",
            metadata={
                "fallback_used": True,
                "fallback_from": "cognitive",
                "fallback_to": "pass",
                "fallback_reason": "all fallbacks exhausted",
            },
        )

    async def _decide_cognitive(
        self,
        action_type: str,
        player_view: Any,
        **kwargs: Any,
    ) -> Decision:
        """Execute cognitive decision (internal, called by decide_with_fallback)."""
        self._view = player_view
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
        return method(**kwargs) if kwargs else method()

    # Night actions where "skip" is a valid strategic choice
    _SKIP_NIGHT_KEYWORDS = {"空守", "不守", "跳过", "空过", "放弃", "不救", "不用", "不毒", "不验", "不刀"}

    def _night_decision(self, result: Dict[str, str], action_type: ActionType) -> Decision:
        """Create a Decision for a night action.

        Handles strategic skip keywords (空守, 不救, etc.) by mapping them
        to self-target for Guard and first-alive for other roles.
        """
        raw_target = (result.get("target") or "").strip()
        if raw_target in self._SKIP_NIGHT_KEYWORDS:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(
                f"Night skip keyword '{raw_target}' from {self.player_name}({self._profile.role}) "
                f"for {action_type.value} — picking fallback target"
            )
            # Prefer self for Guard; first alive for others
            if action_type == ActionType.GUARD:
                target_id = self.player_id
            else:
                target_id = ""
                for p in self._view.players:
                    if p.get("alive"):
                        target_id = p.get("id", "")
                        break
        else:
            target_id = self._resolve_target(raw_target)

        if not target_id and self._strict_no_fallback:
            raise RuntimeError(
                f"LLM returned unresolved {action_type.value} target: {result['target']!r}"
            )
        if not target_id:
            for p in self._view.players:
                if p.get("alive"):
                    target_id = p.get("id", "")
                    break
        return self._decision(action_type, target_id=target_id, reasoning=result.get("reasoning", ""))

    def _resolve_target(self, name: str) -> Optional[str]:
        """Resolve player name to player id."""
        if not name:
            return None
        candidate = str(name).strip().lstrip("@")
        for p in self._view.players:
            player_name = str(p.get("name", "")).strip()
            player_id = str(p.get("id", "")).strip()
            seat = str(p.get("seat", "")).strip()
            seat_label = f"{seat}号" if seat else ""
            if (
                candidate == player_name
                or candidate == player_id
                or candidate == seat
                or candidate == seat_label
                or (player_name and player_name in candidate)
                or (seat_label and seat_label in candidate)
            ):
                return p["id"]
        return None

    def _find_player(self, player_id: str) -> Optional[dict]:
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
        known_wolves = getattr(self._view, 'known_wolves', [])
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
            coord_ctx = build_wolf_coordination_context(
                self.player_id, self._wolf_team_view
            )
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
                record_knowledge_usage({
                    "game_id": self._game_id,
                    "player_id": self.player_id,
                    "knowledge_doc_id": doc_id,
                    "retrieved": True,
                    "used": False,
                    "metadata": {
                        "phase": self._view.phase if self._view else "",
                        "role": self.role,
                        "action_type": "auto_injected",
                    },
                })
        except Exception:
            pass  # best-effort, never block decision flow

    def _reflect_on_game(self, winner: Optional[str]) -> None:
        """Trigger post-game personal reflection and persist to PostgreSQL.

        Controlled via COGNITIVE_ENABLE_REFLECTION (default: enabled).
        When enabled, collects real game events from the agent's view +
        BeliefTracker, runs an MBTI-differentiated LLM reflection, and
        writes structured knowledge docs as 'candidate' status.
        Set COGNITIVE_ENABLE_REFLECTION=false to disable.

        Failures are logged but never raised — reflection is best-effort
        and must not block game completion.
        """
        import os
        val = os.getenv("COGNITIVE_ENABLE_REFLECTION", "").strip().lower()
        if val in ("0", "false", "no", "off"):
            return
        import logging
        _log = logging.getLogger(__name__)

        try:
            from backend.agents.cognitive.reflect import (
                Reflector, save_reflections_to_db,
            )

            # Determine win/loss
            won = False
            if winner and self._profile:
                alignment = "wolf" if "wolf" in self.role.lower() else "village"
                won = winner == alignment

            # Collect real game events from view + belief tracker
            game_events = self._collect_game_events()
            decisions = self._collect_decisions()

            agent_state = {
                "player_id": self.player_id,
                "player_name": self.player_name,
                "role": self.role,
                "persona": self._profile.persona if self._profile else None,
                "mind": self._profile.mind if self._profile else None,
                "won": won,
                "decisions": decisions,
                "game_events": game_events,
            }

            reflector = Reflector(self._llm)
            results = reflector.reflect_game(
                game_id=self._game_id or "unknown",
                agent_states=[agent_state],
            )
            if results:
                saved = save_reflections_to_db(results, self._game_id or "unknown")
                if saved > 0:
                    _log.info(
                        f"Agent {self.player_name}({self.role}, "
                        f"MBTI={self._profile.persona.mbti if self._profile and self._profile.persona else '?'}) "
                        f"reflection: {saved} knowledge docs saved to PostgreSQL"
                    )
                else:
                    _log.warning(
                        f"Agent {self.player_name}: reflection produced no new docs"
                    )
                    if os.getenv("REQUIRE_KNOWLEDGE_WRITE", "").lower() == "true":
                        _log.error("STRICT FAIL: Reflection produced 0 knowledge docs")
        except Exception as e:
            _log.error(f"Reflection failed for {self.player_name}: {e}")

    def _collect_game_events(self) -> List[Dict[str, Any]]:
        """Collect game events visible to this agent for post-game reflection."""
        events = []
        if self._view is None:
            return events

        # Public events (what everyone sees)
        for e in self._view.public_events[-30:]:
            payload = e.get("payload", {}) or {}
            desc = ""
            etype = e.get("type", "")
            if etype == "CHAT_MESSAGE":
                speaker = payload.get("actor_name", "") or payload.get("speaker", "")
                speech = (payload.get("speech", "") or "")[:120]
                desc = f"{speaker}: {speech}"
            elif etype == "VOTE_CAST":
                voter = payload.get("voter_name", "")
                target = payload.get("target_name", "")
                desc = f"{voter} 投票给 {target}"
            elif etype == "PLAYER_DIED":
                name = payload.get("player_name", "")
                cause = payload.get("cause", payload.get("reason", "?"))
                desc = f"{name} 死亡({cause})"
            else:
                desc = str(payload)[:120]
            events.append({
                "type": etype,
                "day": e.get("day", 0),
                "phase": e.get("phase", ""),
                "description": desc,
            })

        # Private events (what only this agent knows)
        for e in self._view.private_events[-10:]:
            payload = e.get("payload", {}) or {}
            kind = payload.get("kind", "")
            if kind == "seer_result":
                target = payload.get("target_name", "?")
                is_wolf = payload.get("is_wolf", False)
                events.append({
                    "type": "PRIVATE_SEER",
                    "day": e.get("day", 0),
                    "description": f"查验 {target}: {'狼人' if is_wolf else '好人'}",
                })
            elif kind == "witch_save":
                events.append({
                    "type": "PRIVATE_WITCH",
                    "day": e.get("day", 0),
                    "description": f"解药救人: {payload.get('target_name', '?')}",
                })

        # Belief tracker findings
        if self._tracker.contradictions:
            for c in self._tracker.contradictions:
                events.append({
                    "type": "CONTRADICTION",
                    "day": self._view.day if self._view else 0,
                    "description": c.description,
                })

        return events

    def _collect_decisions(self) -> List[Dict[str, Any]]:
        """Collect this agent's decisions for post-game reflection."""
        decisions = []
        for a in self.memory.get_recent_actions(30):
            decisions.append({
                "action_type": a.action_type,
                "target": a.target or "",
                "speech": a.content,
                "day": a.day,
                "phase": a.phase,
            })
        return decisions
