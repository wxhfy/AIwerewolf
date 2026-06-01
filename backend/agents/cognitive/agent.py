"""CognitiveAgent — production-grade Werewolf AI using Observe-Think-Act.

Implements the Agent protocol. ALL cognitive work is delegated:
- Observation extraction → observe.py + BeliefTracker
- Reasoning → Pipeline (observe → think → act)
- Memory/Stance → Memory
- Personality → Profile + Humanization
- Strategy → retrieval.py + strategy_bias

This module ONLY handles:
- Agent lifecycle (initialize, update, finish)
- Protocol compliance (talk, vote, attack, etc.)
- State tracking (guard history, witch potions)
- Retry/fallback orchestration
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.humanization import HumanizationProfile, build_humanization_profile
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import (
    Observation, BeliefTracker, observe, format_observation,
)
from backend.agents.cognitive.pipeline import Pipeline, _parse_json_target, _parse_json_array
from backend.agents.cognitive.profiles import Profile, get_profile
from backend.agents.cognitive.prompts import build_system_prompt, build_strategy_bias_block
from backend.engine.models import Decision, ActionType


class CognitiveAgent:
    """Werewolf agent using Observe-Think-Act cognitive architecture.

    Production-grade: integrates Character system, BeliefTracker, Playbooks,
    Humanization, Strategy Bias, and three-tier retry/fallback.

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

    # === Agent Protocol ===

    def initialize(self, view: Any, game_setting: dict) -> None:
        self._view = view
        self.player_name = view.self_player.get("name", self.player_id)
        self.player_seat = view.self_player.get("seat", 0)
        # Track game_id for post-game reflection
        self._game_id = getattr(view, "game_id", "") or str(game_setting.get("game_id", ""))
        self._tracker = BeliefTracker()
        # Warm up strategy retriever (BGE-M3 ~30s one-time, done during setup not first turn)
        self._warm_retriever()

    def _warm_retriever(self) -> None:
        """Pre-build the production retriever so first talk() doesn't incur 30s latency."""
        import logging
        try:
            from backend.agents.cognitive.retrieval_prod import get_retriever
            get_retriever()
        except Exception:
            logging.getLogger(__name__).debug("Retriever warmup skipped (will fall back to TF-IDF)")

    def update(self, view: Any, request: str) -> None:
        self._view = view
        # Clear cached analysis when phase changes (new turn/new action type)
        new_phase = f"{view.day}:{view.phase}"
        if new_phase != self._turn_phase:
            self._pipeline._cached_analysis = ""
            self._turn_phase = new_phase
        self.memory.update_round(view.day, view.phase)
        self._today_speech_count = 0

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
        segments = _parse_json_array(raw)
        if not segments or (len(segments) == 1 and len(segments[0]) < 3):
            # Fallback: use raw text as single speech
            speech = raw.strip()[:500] or "我暂时没有更多信息，先听大家发言。"
            segments = [speech]

        self.memory.add_action("speech", None, segments[0], "")
        self.memory.remember_opening(segments)
        self._today_speech_count += len(segments)

        return self._decision(
            ActionType.TALK,
            speech="\n".join(segments),
            metadata={"segments": segments, "segment_count": len(segments)},
        )

    # ---- Vote ----

    def vote(self) -> Decision:
        obs = self._observe()
        result = self._pipeline.run_vote(obs, self.memory)
        target_id = self._resolve_target(result["target"])
        self.memory.add_action("vote", result["target"], f"投{result['target']}", result["reasoning"])
        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=result["reasoning"])

    # ---- Night actions ----

    def attack(self) -> Decision:
        obs = self._observe()
        extra = self._build_wolf_extra()
        result = self._pipeline.run_night(obs, self.memory, extra)
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
        parsed = _parse_json_target(result)
        target_id = self._resolve_target(parsed["target"]) or (
            self._view.players[0]["id"] if self._view.players else None
        )
        return self._decision(ActionType.SHOOT, target_id=target_id, reasoning=parsed["reasoning"])

    def boom(self) -> Decision:
        return self._decision(ActionType.SKIP, reasoning="不自爆")

    def transfer_badge(self, candidates: List[str]) -> Decision:
        obs = self._observe()
        candidate_strs = []
        for cid in candidates:
            p = self._find_player(cid)
            if p:
                candidate_strs.append(f"{p.get('seat','?')}号:{p.get('name','')}")

        prompt = format_observation(obs) + f"\n\n你已死亡，需将警徽移交给一名存活玩家。\n候选人: {', '.join(candidate_strs)}\n输出 JSON: {{\"reasoning\": \"理由\", \"target\": \"玩家名字\"}}"

        result = self._pipeline.direct_call(prompt)
        parsed = _parse_json_target(result)
        target_id = self._resolve_target(parsed["target"]) or (candidates[0] if candidates else None)
        return self._decision(ActionType.VOTE, target_id=target_id, reasoning=parsed["reasoning"])

    def finish(self, winner: Optional[str]) -> None:
        self.memory.add_action("game_end", None, f"胜者: {winner}", "")
        # Trigger personal post-game reflection (non-blocking — best-effort)
        self._reflect_on_game(winner)

    # === Internal Helpers ===

    def _observe(self) -> Observation:
        """Build observation from current view with belief tracking."""
        return observe(self._view, self.role, tracker=self._tracker)

    def _decision(
        self,
        action_type: ActionType,
        target_id: Optional[str] = None,
        speech: Optional[str] = None,
        reasoning: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Decision:
        """Create a Decision with standard metadata."""
        meta = {"source": "cognitive", "model": "cognitive"}
        if metadata:
            meta.update(metadata)
        return Decision(
            actor_id=self.player_id,
            action_type=action_type,
            target_id=target_id,
            speech=speech,
            reasoning=reasoning[:200],
            metadata=meta,
        )

    def _night_decision(self, result: Dict[str, str], action_type: ActionType) -> Decision:
        """Create a Decision for a night action."""
        target_id = self._resolve_target(result["target"])
        if not target_id:
            for p in self._view.players:
                if p["alive"]:
                    target_id = p["id"]
                    break
        return self._decision(action_type, target_id=target_id, reasoning=result["reasoning"])

    def _resolve_target(self, name: str) -> Optional[str]:
        """Resolve player name to player id."""
        if not name:
            return None
        for p in self._view.players:
            if p.get("name") == name:
                return p["id"]
        return None

    def _find_player(self, player_id: str) -> Optional[dict]:
        """Find player dict by id."""
        for p in self._view.players:
            if p["id"] == player_id:
                return p
        return None

    def _build_wolf_extra(self) -> str:
        """Build extra context for wolf kill decisions."""
        parts = []
        wolf_team = self._view.self_player.get("wolf_team", [])
        if wolf_team:
            parts.append(f"狼队友: {', '.join(wolf_team)}")
        parts.append("作为狼人阵营的一员，选择击杀目标。")
        return "\n".join(parts)

    def _reflect_on_game(self, winner: Optional[str]) -> None:
        """Trigger post-game personal reflection and persist to PostgreSQL.

        Collects real game events from the agent's view + BeliefTracker,
        runs an MBTI-differentiated LLM reflection, and writes structured
        knowledge docs to strategy_knowledge_docs table.

        Failures are logged but never raised — reflection is best-effort
        and must not block game completion.
        """
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
