"""Context-aware heuristic agent with suspicion tracking and information evaluation.

Each agent maintains:
- suspicion_scores: per-player suspicion based on accumulated evidence
- known_facts: what this agent definitively knows (seer checks, wolf teammates, etc.)
- round_context: what happened this round (deaths, speeches, votes)

Behavior adapts to available information:
- Day 1 / no info → cautious, observe, ask questions
- Have evidence → build case, push suspects
- Late game / close to win → aggressive push
"""

from __future__ import annotations

from collections import Counter
from random import Random

import math
import re
from random import Random

from backend.agents.base import Agent
from backend.agents.characters import Character
from backend.agents.humanization import (
    HumanizationProfile,
    build_humanization_profile,
    build_stance_summary,
)
from backend.agents.playbooks import build_role_brief
from backend.engine.models import ActionType, Decision, Role
from backend.engine.visibility import PlayerView


# Wolf-family role set — kept in one place so the heuristic agent doesn't
# silently downgrade new wolf roles (WhiteWolfKing, WolfKing, BigBadWolf,
# WolfCub) to villager logic. The registry is the source of truth at runtime
# but this constant lets the heuristic short-circuit without re-importing.
WOLF_FAMILY: frozenset[Role] = frozenset({
    Role.WEREWOLF,
    Role.WHITE_WOLF_KING,
    Role.WOLF_KING,
    Role.BIG_BAD_WOLF,
    Role.WOLF_CUB,
})


class HeuristicAgent(Agent):
    """Context-aware agent that reasons from available information.

    Key principles:
    - Day 1 with no info → observe, don't accuse blindly
    - Each piece of evidence updates suspicion incrementally
    - Speech reflects actual reasoning, not templates
    - Different roles use different evidence sources
    """

    def __init__(self, player_id: str, *, seed: int | None = None, character: Character | None = None,
                 strategy_bias: dict[str, list[str]] | None = None):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.strategy_bias = {k: list(v) for k, v in (strategy_bias or {}).items() if v}
        # IMPORTANT: do NOT mix strategy_bias into the RNG seed. Empirically the
        # heuristic's wolf-kill and divine-target picks are quite sensitive to
        # the RNG path, and a hash-derived seed shift produces randomly-worse
        # candidates roughly as often as randomly-better ones — net zero, but
        # noisier scores that make the AcceptancePolicy gate harder to pass.
        # Keep the seed identical; only let strategy_bias change *semantically*
        # motivated decisions (see `_choose_vote_target`).
        self.rng = Random(seed)
        self.winner: str | None = None
        self.character = character
        self.human_profile = build_humanization_profile(character)
        # Suspicion tracking: player_id → score (higher = more suspicious)
        self.suspicion: dict[str, float] = {}
        # What we definitively know
        self.known_wolf_ids: set[str] = set()  # seer checks or wolf teammates
        self.known_good_ids: set[str] = set()  # seer gold checks
        # Round tracking
        self.last_speeches: list[dict] = []  # speeches heard this round
        # Persistent stance memory across rounds
        self.public_stance: dict[str, Any] = {
            "suspects": {},       # player_id -> {score, reason, day}
            "trusted": {},        # player_id -> {score, reason, day}
            "grudges": {},        # player_id -> float
            "last_vote_target": None,
            "tunnel_target": None,  # for first_impression types
            "follow_player": None,
        }
        self._last_vote_reasoning = ""
        self._current_request = ""

    # ---- Agent lifecycle ----

    def initialize(self, view: PlayerView, game_setting: dict) -> None:
        self.view = view
        self._init_suspicion()
        char_name = self.character.persona.name if self.character else "Player"
        role = self.role.value
        # Wolves know their teammates
        if self.role in WOLF_FAMILY:
            for w in view.known_wolves:
                if w["id"] != self.player_id:
                    self.known_good_ids.add(w["id"])  # Wolf teammates are "good" from wolf perspective

    def update(self, view: PlayerView, request: str) -> None:
        self.view = view
        self._current_request = request
        # Track new speeches since last update
        self.last_speeches = [
            e for e in view.public_events[-7:]
            if e.get("type") == "CHAT_MESSAGE"
            and e.get("payload", {}).get("actor_id") != self.player_id
        ]
        # Update suspicion from public events
        self._update_suspicion_from_events()
        # Update private knowledge
        for e in view.private_events[-3:]:
            payload = e.get("payload", {})
            if payload.get("kind") == "seer_result":
                tid = payload.get("target_id")
                if tid:
                    if payload.get("is_wolf"):
                        self.known_wolf_ids.add(tid)
                        self.suspicion[tid] = 10.0
                    else:
                        self.known_good_ids.add(tid)
                        self.suspicion[tid] = -10.0

    def _update_suspicion_from_events(self) -> None:
        """Learn from public events: votes, deaths, speech patterns.

        Applies human_profile multipliers so different personalities weigh
        evidence differently. Also maintains public_stance grudges/suspects.
        """
        view = self._view()
        recent = view.public_events[-20:]
        my_name = view.self_player.get("name", "")
        hp = self.human_profile

        # Decay existing suspicion based on memory_bias
        decay = 0.9 if hp.stubbornness >= 1.0 else 0.5 if hp.stubbornness <= 0.3 else 0.7
        for pid in self.suspicion:
            if pid not in self.known_wolf_ids and pid not in self.known_good_ids:
                self.suspicion[pid] *= decay

        for e in recent:
            if e.get("type") == "VOTE_CAST":
                voter = e.get("payload", {}).get("voter_id")
                target = e.get("payload", {}).get("target_id")
                if voter and target and target != self.player_id:
                    self._adjust_suspicion(voter, 0.2 * hp.suspicion_gain, "voted")
                    self._adjust_suspicion(target, 0.15 * hp.suspicion_gain, "voted_against")
                    if target in self.known_good_ids:
                        self._adjust_suspicion(voter, 0.5 * hp.suspicion_gain, "voted_known_good")
                    # If someone I trust voted for someone, that target gets a follow bonus
                    if voter in self.public_stance.get("trusted", {}):
                        self._adjust_suspicion(target, 0.15 * hp.follow_weight, "trusted_voted")

            if e.get("type") == "PLAYER_DIED":
                pid = e.get("payload", {}).get("player_id")
                reason = e.get("payload", {}).get("reason", "")
                if pid and pid not in self.known_wolf_ids:
                    if reason == "wolf":
                        self._adjust_suspicion(pid, -0.5 * hp.suspicion_gain, "killed_by_wolf")
                    elif reason == "vote":
                        self._adjust_suspicion(pid, -0.3 * hp.suspicion_gain, "voted_out")

            if e.get("type") == "CHAT_MESSAGE":
                speech = e.get("payload", {}).get("speech", "")
                actor = e.get("payload", {}).get("actor_id")
                if actor and actor != self.player_id:
                    # Vague/fence-sitting speech
                    vague = sum(1 for w in ["可能吧", "不确定", "再看看", "不好说"] if w in speech)
                    if vague >= 2:
                        self._adjust_suspicion(actor, 0.15 * hp.suspicion_gain, "vague")
                    # Aggressive early accusations without evidence
                    if view.day <= 1 and ("是狼" in speech or "查杀" in speech or "票他" in speech):
                        if actor not in self.known_wolf_ids and actor not in self.known_good_ids:
                            self._adjust_suspicion(actor, 0.1 * hp.suspicion_gain, "early_aggression")
                    # Track who mentions our name -> grudge
                    if my_name in speech:
                        grudge_delta = 0.25 * hp.grudge_weight
                        self._adjust_suspicion(actor, grudge_delta, f"mentioned_me")
                        if actor not in self.public_stance["grudges"]:
                            self.public_stance["grudges"][actor] = 0.0
                        self.public_stance["grudges"][actor] += grudge_delta

        # Update public_stance suspects/trusted from suspicion scores
        self._sync_stance_from_suspicion(view)

    def day_start(self) -> None:
        pass

    def finish(self, winner: str | None) -> None:
        self.winner = winner

    # ---- Core decision methods ----

    def talk(self) -> Decision:
        view = self._view()
        role = self.role
        my_name = view.self_player.get("name", "Player")
        day = view.day
        alive_count = sum(1 for p in view.players if p["alive"])
        hp = self.human_profile

        # STEP 1: Assess what information we actually have
        info_level = self._assess_information()

        # STEP 2: Build speech based on information + game state + role strategy
        speech, reasoning = self._build_contextual_speech(
            role=role, day=day, info_level=info_level,
            alive_count=alive_count, my_name=my_name,
        )

        # STEP 3: Split into segments for multi-bubble emission
        segments = self._split_into_segments(speech, hp)
        meta = {
            "segments": segments,
            "segment_count": len(segments),
            "source": "heuristic",
            "humanization_profile": {
                "vote_temperature": hp.vote_temperature,
                "analysis_depth": hp.analysis_depth,
                "speech_mode": f"{hp.speech_min_segments}-{hp.speech_max_segments}",
            },
        }
        # Include stance summary for debugging / LLM context sharing
        try:
            meta["stance_summary"] = build_stance_summary(self.public_stance, self.player_id, view)
        except Exception:
            pass

        return Decision(view.player_id, ActionType.TALK, speech=speech, reasoning=reasoning, metadata=meta)

    def _split_into_segments(self, speech: str, hp: HumanizationProfile) -> list[str]:
        """Split a concatenated speech into natural multi-bubble segments."""
        if not speech.strip():
            return ["（沉默）"]

        # Split by sentence boundaries
        raw = re.split(r"(?<=[。！？])", speech)
        sentences = [s.strip() for s in raw if s.strip()]
        if not sentences:
            return [speech.strip()]

        target = self.rng.randint(hp.speech_min_segments, hp.speech_max_segments)
        target = min(target, len(sentences))  # can't have more segments than sentences

        if target <= 1:
            return ["".join(sentences)]

        # Distribute sentences into target segments
        segments: list[str] = []
        per_seg = max(1, len(sentences) // target)
        for i in range(target):
            start = i * per_seg
            end = start + per_seg if i < target - 1 else len(sentences)
            seg = "".join(sentences[start:end]).strip()
            if seg:
                segments.append(seg)

        # Ensure we don't exceed max_segments
        if len(segments) > hp.speech_max_segments:
            # Merge last segments
            overflow = segments[hp.speech_max_segments - 1:]
            segments = segments[:hp.speech_max_segments - 1]
            segments.append("".join(overflow).strip())

        return segments if segments else [speech.strip()]

    def vote(self) -> Decision:
        view = self._view()
        target = self._choose_vote_target()
        reasoning = getattr(self, "_last_vote_reasoning", "") or f"Voting {target['name']}"
        return Decision(view.player_id, ActionType.VOTE, target_id=target["id"],
                       reasoning=reasoning)

    def attack(self) -> Decision:
        view = self._view()
        target = self._choose_wolf_kill_target()
        day = view.day
        reason = "盲刀，排除队友后随机选择" if day <= 1 else f"狼人集火{target['name']}"
        return Decision(view.player_id, ActionType.ATTACK, target_id=target["id"],
                       reasoning=reason)

    def divine(self) -> Decision:
        view = self._view()
        target = self._choose_divine_target()
        return Decision(view.player_id, ActionType.DIVINE, target_id=target["id"],
                       reasoning=f"Check {target['name']} to clarify the board")

    def guard(self) -> Decision:
        view = self._view()
        target = self._choose_guard_target()
        return Decision(view.player_id, ActionType.GUARD, target_id=target["id"],
                       reasoning=f"Guard {target['name']} as likely village priority")

    def witch_act(self, victim_id: str | None) -> list[Decision]:
        view = self._view()
        decisions: list[Decision] = []
        # Save on night 0 or if victim might be important
        if victim_id and (view.day <= 1):
            decisions.append(Decision(view.player_id, ActionType.WITCH_SAVE, target_id=victim_id,
                             reasoning="Save early to preserve village numbers"))
        # Poison only if we have confirmed wolf info
        poison_candidates = sorted(self.suspicion.items(), key=lambda x: x[1], reverse=True)
        for pid, score in poison_candidates:
            if score >= 3.0 and pid != victim_id:
                p = self._player(pid)
                if p and p["alive"]:
                    decisions.append(Decision(view.player_id, ActionType.WITCH_POISON, target_id=pid,
                                     reasoning=f"Poison {p['name']} based on high suspicion ({score:.1f})"))
                    break
        if not decisions:
            decisions.append(Decision(view.player_id, ActionType.SKIP, reasoning="Hold potions, not enough evidence"))
        return decisions

    def shoot(self) -> Decision:
        view = self._view()
        # Shoot the most suspicious alive player
        target = self._highest_suspicion_alive()
        return Decision(view.player_id, ActionType.SHOOT, target_id=target["id"],
                       reasoning=f"Hunter shoots {target['name']} as strongest suspect")

    def boom(self) -> Decision:
        view = self._view()
        if self.role != Role.WHITE_WOLF_KING:
            return Decision(view.player_id, ActionType.SKIP, reasoning="Not White Wolf King")
        # Only boom when wolves are losing badly: more village alive than wolves by a large margin
        # and the White Wolf King himself is under heavy suspicion (likely to be voted out anyway)
        target = self._highest_suspicion_alive()
        my_suspicion_on_me = sum(1 for p in view.players if p["alive"] and p["id"] != self.player_id)
        wolf_alive = sum(1 for p in view.players if p["alive"] and p.get("alignment") == "wolf")
        village_alive = sum(1 for p in view.players if p["alive"] and p.get("alignment") != "wolf")
        # Boom only when: day >= 4 AND wolves are outnumbered AND I'm heavily suspected
        should_boom = (
            view.day >= 4
            and village_alive > wolf_alive + 2
            and self.suspicion.get(self.player_id, 0) >= 2.0
        )
        if should_boom:
            return Decision(
                view.player_id,
                ActionType.BOOM,
                target_id=target["id"],
                reasoning=f"White Wolf King self-destructs to force out {target['name']}",
            )
        return Decision(view.player_id, ActionType.SKIP, reasoning="Hold the boom for a higher-value timing.")

    def transfer_badge(self, candidates: list[str]) -> Decision:
        """Pick a successor for the sheriff badge from the given candidate ids.

        Fallback heuristic: prefer a village-aligned candidate, then lowest
        seat. Empty candidate list → SKIP (badge destroyed).
        """
        view = self._view()
        if not candidates:
            return Decision(view.player_id, ActionType.SKIP, reasoning="No alive successor available; badge destroyed.")
        cand_players = [p for p in view.players if p["id"] in candidates]
        # Village preference uses whatever we know — for own-team it's confident,
        # for others we just lean on the `alignment` field if present (only true
        # in moderator/private views; otherwise this is a no-op and seat order wins).
        village_first = sorted(
            cand_players,
            key=lambda p: (
                0 if str(p.get("alignment") or "").lower() == "village" else 1,
                int(p.get("seat") or 999),
            ),
        )
        winner = village_first[0]
        return Decision(
            view.player_id,
            ActionType.VOTE,
            target_id=winner["id"],
            reasoning=f"Transfer badge to seat {winner.get('seat')} ({winner.get('name')}) by seat order, village preference.",
        )

    # ---- Information assessment ----

    def _assess_information(self) -> str:
        """Determine how much actionable information we have."""
        if self.known_wolf_ids:
            return "strong"
        view = self._view()
        # Check if we have suspects from public_stance
        if self.public_stance.get("suspects"):
            top_score = max(info["score"] for info in self.public_stance["suspects"].values())
            if top_score >= 2.0:
                return "moderate"
            if top_score >= 1.0:
                return "limited"
        if view.day >= 3 and any(s >= 2.0 for s in self.suspicion.values()):
            return "moderate"
        if view.day >= 2 and any(s >= 1.0 for s in self.suspicion.values()):
            return "limited"
        if view.day >= 2:
            return "limited"
        return "none"

    def _init_suspicion(self) -> None:
        view = self._view()
        for p in view.players:
            if p["id"] != self.player_id:
                self.suspicion[p["id"]] = 0.0

    def _adjust_suspicion(self, player_id: str, delta: float, reason: str = "") -> None:
        if player_id in self.suspicion:
            self.suspicion[player_id] += delta

    def _sync_stance_from_suspicion(self, view: PlayerView) -> None:
        """Sync public_stance suspects/trusted from current suspicion scores."""
        hp = self.human_profile
        st = self.public_stance
        day = view.day

        # Clear stale entries — but keep tunnel_target for first_impression types
        st["suspects"] = {}
        st["trusted"] = {}

        for pid, score in self.suspicion.items():
            if pid in self.known_wolf_ids:
                st["suspects"][pid] = {"score": 10.0, "reason": "已知狼人", "day": day}
            elif pid in self.known_good_ids:
                st["trusted"][pid] = {"score": 10.0, "reason": "已知好人", "day": day}
            elif score >= 1.0 * (1.5 / max(hp.suspicion_gain, 0.1)):
                # Suspicious threshold adjusted by personality
                st["suspects"][pid] = {"score": round(score, 2), "reason": "累积怀疑", "day": day}
            elif score <= -0.5:
                st["trusted"][pid] = {"score": round(abs(score), 2), "reason": "行为偏好人", "day": day}

        # Maintain tunnel_target for first_impression types
        if hp.stubbornness >= 1.0 and st["suspects"]:
            top = max(st["suspects"].items(), key=lambda x: x[1]["score"])
            old_tunnel = st.get("tunnel_target")
            if old_tunnel is None or top[1]["score"] >= 2.5:
                st["tunnel_target"] = top[0]

    # ---- Speech construction ----

    # Map the 37 persona style_labels down to ~8 archetypes that have rich
    # template coverage.  Without this, unrecognized labels fall through to the
    # bare default of each function, making 80 % of the roster sound identical.
    _STYLE_ARCHETYPE: dict[str, str] = {
        # analytical family
        "academic": "analytical",
        "analytical": "analytical",
        "archivist": "analytical",
        "meticulous": "analytical",
        "precise": "analytical",
        "matrix": "analytical",
        "theorist": "analytical",
        "strategist": "analytical",
        "deconstructive": "analytical",
        # aggressive family
        "aggressive": "aggressive",
        "interrogator": "aggressive",
        "debater": "aggressive",
        "provocative": "provocative",
        # observant family
        "observant": "observant",
        "observer": "observant",
        "gentle": "observant",
        "still_water": "observant",
        "sensitive": "observant",
        # persuasive family
        "persuasive": "persuasive",
        "rallier": "persuasive",
        "mediator": "persuasive",
        "harmonizer": "persuasive",
        "commander": "persuasive",
        "anchor": "persuasive",
        "caretaker": "persuasive",
        # expressive family
        "expressive": "expressive",
        "energetic": "expressive",
        "playful": "expressive",
        "curious": "expressive",
        "cosmopolitan": "expressive",
        "lyrical": "expressive",
        "poetic": "expressive",
        "tricky": "expressive",
        # insightful family
        "insightful": "insightful",
        # lone wolves that map to closest archetype
        "veteran": "analytical",
        "tactical": "analytical",
        "ranger": "aggressive",
        "neutral": "analytical",
    }

    @staticmethod
    def _normalize_style(style_label: str | None) -> str:
        if not style_label:
            return "neutral"
        return HeuristicAgent._STYLE_ARCHETYPE.get(style_label, "neutral")

    # 语气词/口头禅：每种风格有开头词、连接词、结尾词
    _STYLE_INTERJECTIONS: dict[str, dict[str, list[str]]] = {
        "analytical": {
            "starters": ["嗯，", "那么，", "所以说，", "你看，", "简单来说，"],
            "connectors": ["而且", "另外", "不过话说回来", "值得注意的是"],
            "tags": ["对吧。", "你们想想。", "仔细看就知道了。", "数据不会骗人。"],
        },
        "aggressive": {
            "starters": ["我说，", "喂，", "得了吧，", "你听好了，", "我就直说了——"],
            "connectors": ["再说了", "更离谱的是", "说白了", "关键是"],
            "tags": ["懂？", "自己掂量。", "别装了。", "我说完了。"],
        },
        "observant": {
            "starters": ["哦，", "唔，", "嗯……", "这个嘛，", "说实话，"],
            "connectors": ["不过", "话说回来", "仔细想想", "倒是"],
            "tags": ["吧。", "先这样。", "再看看。", "不好说。"],
        },
        "persuasive": {
            "starters": ["大家听我说，", "我觉得吧，", "你想想，", "说真的，"],
            "connectors": ["而且呢", "更重要的是", "换个角度想", "其实"],
            "tags": ["对吧？", "你说是不是？", "大家觉得呢？", "你们说呢？"],
        },
        "expressive": {
            "starters": ["哇，", "天哪，", "哎呀，", "不是吧，", "我的天，"],
            "connectors": ["而且你知道吗", "更夸张的是", "然后呢", "最离谱的是"],
            "tags": ["！真的！", "～太离谱了！", "你们说是不是！", "哎呦喂！"],
        },
        "insightful": {
            "starters": ["你想想，", "有意思的是，", "说白了，", "换个角度看，"],
            "connectors": ["更深一层", "往回看", "本质上", "归根结底"],
            "tags": ["你们品品。", "细想一下就知道了。", "这个信号很关键。"],
        },
        "provocative": {
            "starters": ["切，", "哈，", "我说，", "得了吧，", "搞笑呢？"],
            "connectors": ["更搞笑的是", "然后呢", "问题是", "最逗的是"],
            "tags": ["就这？", "自己想想吧。", "谁信啊。", "我话放这了。"],
        },
        "neutral": {
            "starters": ["嗯，", "那个，", "就是，", "我觉得，"],
            "connectors": ["而且", "不过", "话说回来", "另外"],
            "tags": ["吧。", "你们看看。", "先这样。"],
        },
    }

    def _add_interjections(self, speech: str, style: str, rng: Random) -> str:
        """给发言添加自然的语气词，让对话更有活人气息。"""
        interjections = self._STYLE_INTERJECTIONS.get(style, self._STYLE_INTERJECTIONS["neutral"])

        # 按句号拆分
        sentences = re.split(r"(?<=[。！？])", speech)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return speech

        result = []
        for i, sent in enumerate(sentences):
            # 第一句：30%概率加开头语气词
            if i == 0 and rng.random() < 0.3:
                starter = rng.choice(interjections["starters"])
                # 避免重复：如果句子已经以语气词开头就不加
                if not any(sent.startswith(s.rstrip("，")) for s in interjections["starters"]):
                    sent = starter + sent

            # 中间句子：20%概率加连接词
            elif 0 < i < len(sentences) - 1 and rng.random() < 0.2:
                connector = rng.choice(interjections["connectors"])
                sent = connector + "，" + sent

            # 最后一句：25%概率加结尾语气词（替换句号）
            elif i == len(sentences) - 1 and rng.random() < 0.25:
                tag = rng.choice(interjections["tags"])
                # 替换末尾标点
                if sent.endswith(("。", "！", "？")):
                    sent = sent[:-1] + tag
                else:
                    sent = sent + tag

            result.append(sent)

        return "".join(result)

    def _gather_event_facts(self) -> dict:
        """Extract concrete recent events from public_events for speech references.

        Returns a dict with keys like 'vote_tally', 'executed', 'night_deaths',
        'badge_holder', 'seer_claims', 'quiet_players', 'recent_voters'.
        """
        view = self._view()
        if not view:
            return {}

        facts: dict[str, Any] = {}
        day = view.day
        events = view.public_events

        # 1. Yesterday's vote tally
        vote_events = [
            e for e in events
            if e.get("type") == "VOTE_CAST"
            and not e.get("payload", {}).get("badge_election")
            and e.get("day", 0) == day - 1
        ]
        if vote_events:
            vote_targets: Counter[str] = Counter()
            voter_map: dict[str, list[str]] = {}
            for ve in vote_events:
                vp = ve.get("payload", {})
                target_name = vp.get("target_name", "")
                voter_name = vp.get("voter_name", "")
                if target_name:
                    vote_targets[target_name] += 1
                    voter_map.setdefault(target_name, []).append(voter_name)
            if vote_targets:
                facts["vote_tally"] = vote_targets
                facts["vote_voter_map"] = voter_map
                top_voted = vote_targets.most_common(1)[0]
                facts["top_voted_name"] = top_voted[0]
                facts["top_voted_count"] = top_voted[1]

        # 2. Who was executed (voted out) yesterday
        executed_events = [
            e for e in events
            if e.get("type") == "PLAYER_DIED"
            and e.get("payload", {}).get("reason") == "vote"
            and e.get("day", 0) == day - 1
        ]
        if executed_events:
            facts["executed_name"] = executed_events[-1].get("payload", {}).get("player_name", "")

        # 3. Last night's deaths
        night_deaths = [
            e for e in events
            if e.get("type") == "PLAYER_DIED"
            and e.get("payload", {}).get("reason") in ("wolf", "poison")
            and e.get("day", 0) == day
        ]
        if night_deaths:
            facts["night_death_names"] = [
                e.get("payload", {}).get("player_name", "?") for e in night_deaths
            ]

        # 4. Badge holder
        badge_events = [
            e for e in events
            if e.get("type") == "SYSTEM_MESSAGE"
            and "sheriff" in e.get("payload", {}).get("message", "").lower()
        ]
        if badge_events:
            msg = badge_events[-1].get("payload", {}).get("message", "")
            # "{name} won the badge election and becomes sheriff."
            parts = msg.split(" won")
            if parts:
                facts["badge_holder_name"] = parts[0].strip()

        # 5. Seer claims in recent speeches
        seer_claims = []
        for s in self.last_speeches[-5:]:
            text = s.get("payload", {}).get("speech", "")
            speaker = s.get("payload", {}).get("actor_name", "")
            if self._detect_seer_self_claim(text):
                target = self._extract_seer_target(text, "")
                seer_claims.append({"claimer": speaker, "target": target})
        if seer_claims:
            facts["seer_claims"] = seer_claims

        # 6. Who hasn't spoken this round
        speakers_this_round = {
            s.get("payload", {}).get("actor_name", "")
            for s in self.last_speeches
            if s.get("day", 0) == day
        }
        my_name = self._player(self.player_id)
        my_name_str = my_name.get("name", "") if my_name else ""
        all_names = {
            p.get("name", "") for p in view.players if p.get("alive", True)
        }
        quiet_names = all_names - speakers_this_round - {my_name_str}
        if quiet_names:
            facts["quiet_players"] = list(quiet_names)

        # 7. My own vote last round
        my_vote_events = [
            e for e in events
            if e.get("type") == "VOTE_CAST"
            and e.get("payload", {}).get("voter_id") == self.player_id
            and not e.get("payload", {}).get("badge_election")
            and e.get("day", 0) == day - 1
        ]
        if my_vote_events:
            facts["my_last_vote_target"] = my_vote_events[-1].get("payload", {}).get("target_name", "")

        return facts

    def _build_event_reference(self, facts: dict, *, style: str = "neutral", rng: Random | None = None) -> str:
        """Build a natural Chinese phrase referencing a concrete recent event.

        Picks at most 2 event types to reference (to avoid overly long speeches).
        """
        rng = rng or self.rng
        options: list[str] = []

        # Reference yesterday's vote tally
        if "top_voted_name" in facts and "top_voted_count" in facts:
            name = facts["top_voted_name"]
            count = facts["top_voted_count"]
            tag = self._tag_by_name(name)
            vote_refs = [
                f"昨天{tag}拿了{count}票",
                f"上一轮{tag}被投了{count}票",
            ]
            if len(facts.get("vote_tally", {})) > 1:
                second = facts["vote_tally"].most_common(2)[1] if len(facts["vote_tally"]) > 1 else None
                if second:
                    vote_refs.append(
                        f"昨天{tag}拿了{count}票，{self._tag_by_name(second[0])}也有{second[1]}票，票比较散"
                    )
            options.append(("vote", rng.choice(vote_refs)))

        # Reference who was executed
        if "executed_name" in facts:
            tag = self._tag_by_name(facts["executed_name"])
            exec_refs = [
                f"昨天{tag}被票出去了",
                f"上一轮{tag}出局，翻牌之后大家可以看看身份",
            ]
            options.append(("exec", rng.choice(exec_refs)))

        # Reference night deaths
        if "night_death_names" in facts:
            names = facts["night_death_names"]
            tags = "、".join(self._tag_by_name(n) for n in names)
            if len(names) == 1:
                death_refs = [
                    f"昨晚{tags}被刀了，这个刀口值得琢磨",
                    f"昨晚{tags}倒牌，狼人的刀型有想法",
                    f"今天起来{tags}没了，得想想为什么狼要刀他",
                ]
            else:
                death_refs = [
                    f"昨晚{tags}都倒了，双死局信息量很大",
                    f"今天双死——{tags}，狼这刀有说法",
                ]
            options.append(("death", rng.choice(death_refs)))

        # Reference seer claims
        if "seer_claims" in facts:
            for claim in facts["seer_claims"][:1]:
                claimer_tag = self._tag_by_name(claim["claimer"])
                target_tag = self._tag_by_name(claim["target"]) if claim["target"] else ""
                if target_tag:
                    options.append(("seer", f"{claimer_tag}跳预言家说验了{target_tag}，这个信息很关键"))
                else:
                    options.append(("seer", f"{claimer_tag}跳了预言家，先记下来"))

        if not options:
            return ""

        # Pick at most 2 different event types to keep speeches concise
        rng.shuffle(options)
        selected = options[:2]
        return " ".join(item[1] for item in selected)

    def _build_contextual_speech(self, *, role, day, info_level, alive_count, my_name):
        """Build speech from actual context: what do I know? what just happened?"""
        view = self._view()
        char = self.character
        raw_style = char.persona.style_label if char else "neutral"
        style = self._normalize_style(raw_style)
        # Re-seed per-turn so different days produce different picks even when
        # the underlying suspicion landscape barely changed.
        local_rng = Random(hash((self.player_id, view.day, view.phase, info_level)))

        # Gather concrete events for speech references
        event_facts = self._gather_event_facts()

        # Gather what just happened
        deaths_today = [e for e in view.public_events[-5:]
                       if e.get("type") == "PLAYER_DIED" and e.get("day") == day]
        recent_speeches = self.last_speeches

        # Build the speech organically
        parts: list[str] = []

        # 1. React to deaths
        is_badge_campaign = getattr(self, "_current_request", "") == "BADGE_SPEECH"
        if is_badge_campaign:
            parts.append(self._badge_campaign_speech(style, my_name, role, local_rng))
            speech = " ".join(parts).strip()
            reasoning = f"{my_name}({role.value}) badge campaign speech"
            return speech, reasoning

        is_last_words = getattr(self, "_current_request", "") == "LAST_WORDS"
        if is_last_words:
            parts.append(self._last_words_speech(style, my_name, role, local_rng))
            speech = " ".join(parts).strip()
            reasoning = f"{my_name}({role.value}) last words"
            return speech, reasoning

        if deaths_today:
            dead_names = [e.get("payload", {}).get("player_name", "?") for e in deaths_today]
            parts.append(self._reaction_to_death(style, dead_names, local_rng))

        # 1b. Inject a concrete event reference (vote tally, night deaths, seer claims)
        event_ref = self._build_event_reference(event_facts, style=style, rng=local_rng)
        if event_ref:
            parts.append(event_ref)

        # 2. State our position based on information level
        if info_level == "none":
            parts.append(self._day1_observation(style, my_name, recent_speeches, alive_count, event_facts, local_rng))
        elif info_level == "strong":
            parts.append(self._strong_push(role, my_name, alive_count))
        else:
            parts.append(self._developing_case(role, style, my_name, recent_speeches, alive_count, local_rng, event_facts))

        # 2b. Wolves: proactively fake Seer claim — replaces normal speech
        if self.role in WOLF_FAMILY and day >= 1:
            wolf_claim = self._wolf_seer_counter_claim(local_rng)
            if wolf_claim:
                speech = wolf_claim
                reasoning = f"{my_name}({role.value}) wolf fake Seer claim"
                return speech, reasoning

        # 3. Respond to specific players — keep it sparse so it doesn't drown
        # the speech in echo lines.
        response = self._respond_to_others(style, my_name, local_rng)
        if response:
            parts.append(response)

        # 4. Call to action — single closer per speech, style-aware.
        if info_level == "strong":
            parts.append(self._call_vote())
        elif day >= 2:
            parts.append(self._call_discussion(style, local_rng))
        else:
            parts.append(self._opening_close(style, local_rng))

        # 5. 给每个部分添加语气词，让发言更自然
        parts = [self._add_interjections(p, style, local_rng) for p in parts]

        speech = " ".join(parts).strip()
        reasoning = f"{my_name}({role.value}) day{day} info={info_level}: {'push' if info_level == 'strong' else 'observe' if info_level == 'none' else 'analyze'}"
        return speech, reasoning

    def _badge_campaign_speech(self, style: str, my_name: str, role: Role, rng: Random) -> str:
        """Short badge campaign pitch — distinct from normal day speech."""
        templates: dict[str, list[str]] = {
            "analytical": [
                "我竞选警长。我的优势是分析型打法，每轮会整理票型和发言逻辑。如果当上警长，我会带大家梳理证据。",
                "我参选警长。我习惯系统性分析，拿到警徽后我会带领大家逐条对账，不让信息散掉。",
                "我想拿警徽。理由很简单——我会记票型记发言，不给狼人浑水摸鱼的机会。",
                "我上警。拿到警徽后每轮我会做信息汇总，帮大家理清头绪。",
                "我竞选。我相信数据比感觉可靠，拿到警徽后我会记录每个人的发言变化。",
                "我要拿警徽。好人需要有人整理信息，我有这个习惯和能力。",
            ],
            "aggressive": [
                "我上警！这警徽必须给一个敢带队的人。我不怕踩人、不怕背锅，跟我就行。",
                "警长我拿。谁想带队就亮牌说话，我绝不让划水的人混着过。",
                "我要警徽！狼人想藏？在我这儿藏不住。我带队票人从不犹豫。",
                "上警！好人别怂，警徽给我，今天我就盯着那些不说话的。",
                "我竞选警长。我的风格是直接——谁有问题我点谁，不搞虚的。",
            ],
            "observant": [
                "我参选警长。虽然话不多，但我一直在观察每个人的状态。警徽交给我，我会认真对待。",
                "我想竞选警长。我习惯少说话多看事，但这个位置不能交给不清楚的人。",
                "上警。我看人比较稳，不会轻易被带节奏。",
            ],
            "persuasive": [
                "大家好，我想竞选警长。我的风格是让大家都有说话的空间，然后凝聚共识。希望大家支持我。",
                "我上警！我相信好人是多数，我的任务是把大家的想法整合起来，做出最好的决定。",
                "我想当警长。我不搞个人英雄主义，我会让每个人的声音都被听到。",
            ],
            "expressive": [
                "我来竞选警长啦！我超有热情的，而且直觉很准！选我你不会后悔～",
                "警长我来！我虽然活泼但我脑子转得快，狼人别想在我眼皮底下耍花招！",
                "我要上警！气氛和判断力我都有，警徽给我我们好人一定赢！",
            ],
            "insightful": [
                "我竞选警长。我的强项是看透发言背后的动机。拿到警徽后，我会把每天的信息做深层分析。",
                "我想拿警徽。我的视角比较独特，能发现别人注意不到的破绽。",
                "上警。我相信自己对人的判断，也相信能把好人的力量组织起来。",
            ],
            "provocative": [
                "警长我拿！不敢上警的我都记着。狼人你跳不跳？不跳我就带队了。",
                "我要警徽。谁觉得我不行，现在就说出来——不然就投票。我带队不怕得罪人。",
                "上警！我就一句话——跟我的都是好兄弟，不跟的等会儿自己解释。",
            ],
        }
        lines = templates.get(style, templates["analytical"])
        return rng.choice(lines)

    def _last_words_speech(self, style: str, my_name: str, role: Role, rng: Random) -> str:
        """Last words before elimination — more emotional, less analytical."""
        templates: dict[str, list[str]] = {
            "analytical": [
                "好吧我走了。回去看看我的发言，我没有说谎。好人加油。",
                "既然票出来了，我只说一句——我的身份你们之后会知道的。",
                "没关系的，被票出去也是游戏的一部分。希望我的身份能帮大家理清思路。",
            ],
            "aggressive": [
                "行，票我。等翻牌你们就知道谁在乱带了。我记住今天投我的人。",
                "好，我出去。投我的人里面至少一狼，你们自己品。",
                "没话说。我的身份就是最好的回击。好人别散。",
            ],
            "observant": [
                "我走了。没什么好说的，身份会替我说话。",
                "好的。大家冷静，看我的身份再判断。",
                "行吧。希望我的离场能帮好人看清局势。",
            ],
            "persuasive": [
                "虽然被票了但我还是相信好人的判断。我走后请大家重新整理一下信息。",
                "没关系大家，游戏继续。我的身份是清白的，好人别灰心。",
                "好的我理解。不管怎么样，好人还有机会，别放弃。",
            ],
            "expressive": [
                "呜哇我被票了！不过没关系～好人加油，我的身份你们看了就知道！",
                "好吧好吧我走了！别忘了我之前说的话哦，好人必胜！",
                "啊我被出局了！没事，游戏继续，我要看看谁是狼！",
            ],
            "insightful": [
                "我走了。临走前说一句——注意那些说话滴水不漏的人。",
                "好的。我的判断可能不够准确，但我的用心是好的。好人再见。",
                "我接受这个结果。希望我的身份能给大家一个新的视角。",
            ],
            "provocative": [
                "票我？行，翻牌之后谁尴尬谁知道。好人看清楚。",
                "好得很。我出去之后，投我的人一个都别想跑。",
                "有意思。我的身份会让某些人后悔的。好人别被带偏。",
            ],
            "neutral": [
                "好的我走了。我的身份是清白的，大家继续加油。",
                "行，票我结果已定。希望好人能从我的身份得到线索。",
                "没关系的。翻牌之后请大家重新梳理逻辑。",
            ],
        }
        lines = templates.get(style, templates["neutral"])
        return rng.choice(lines)

    def _reaction_to_death(self, style: str, dead_names: list[str], rng: Random) -> str:
        tags = "、".join(self._tag_by_name(name) for name in dead_names)
        templates_by_style = {
            "analytical": [
                f"{tags}走了，得回看昨晚的目标选择。狼刀他不是随机的，一定有逻辑在里面，等会儿我盘一下。",
                f"{tags}的离场说明刀型不是随机的。昨晚谁在带节奏、谁在划水，和这个刀口对照一下会有发现。",
                f"{tags}死了——这刀型有规律。我想回看他最后几轮的发言，看看他是不是踩到了真狼。",
            ],
            "observant": [
                f"{tags}死了。昨晚的刀口值得琢磨，我先记下来，等会儿对照发言看。",
                f"{tags}走了。狼人选这个目标一定有原因，我想想他之前说了什么。",
                f"{tags}没了。这个刀口信息量不小，先不急着下结论，但我会重点回忆他的发言。",
            ],
            "meticulous": [
                f"{tags}的死要列入今天的判断依据。我会把他之前的发言和票型做交叉对比，看看有没有线索。",
                f"先记一笔——{tags}昨晚没撑住。等一下我会把他的离场和昨天的发言做详细对照。",
                f"{tags}的位置很特殊，值得重点回顾。他之前的每一次投票、每一段发言都不能放过。",
            ],
            "insightful": [
                f"{tags}先走，节奏一下子变了。狼这刀有想法，不是随便选的——他要么是踩到了狼，要么是挡了狼的路。",
                f"{tags}的位置很关键，狼显然有目的。我需要重新审视昨晚的发言，看看谁最有可能是下刀的人。",
            ],
            "persuasive": [
                f"我们少了{tags}，今天更要凝聚。大家不要慌，把昨晚的信息整理一下，好人的机会还在。",
                f"{tags}走了，大家心里都有数。失去他很可惜，但别散，集中精力分析刀口。",
            ],
            "aggressive": [
                f"{tags}没了，今天就别再装死。狼刀他说明他们急了，今天的发言谁含糊我直接盯。",
                f"刀{tags}的人心里有数。今天必须有人站出来解释，别想划水过去。",
                f"{tags}出局了，今天的发言别给我打太极。谁最想让他死，自己掂量。",
            ],
            "expressive": [
                f"哇{tags}竟然走了！心痛一下。不过狼人选这个目标一定有说法，我得好好想想。",
                f"不是吧{tags}没了？狼太狠了吧！这个刀口我先记着，等会儿看谁最可疑。",
            ],
            "provocative": [
                f"{tags}领盒饭了，狼这刀是要送票。谁最想让他死？自己站出来说说。",
                f"{tags}被刀了，说明狼急了或者狼很自信。不管哪种，今天都得有人交代。",
            ],
        }
        lines = templates_by_style.get(style, [
            f"昨晚{tags}死了，刀口值得琢磨。狼人选他一定有原因，我想听听大家怎么看。",
            f"{tags}走了，今天得好好分析。他之前的发言和票型都要重新过一遍。",
            f"{tags}没了，这个刀口信息量不小。大家说说自己的判断，别藏着。",
        ])
        return rng.choice(lines)

    def _opening_close(self, style: str, rng: Random) -> str:
        templates = {
            "analytical": [
                "大家先把信息摆出来，方便我比对。我倾向先听完一轮再下判断，信息量上来之前不急着定方向。",
                "先听全了再盘。每个人说一下自己关注谁、为什么，这样后面才有东西可以对照。",
                "信息量上来之前我不急着定方向。大家按顺序说，把想法讲清楚，不要只报名字不给理由。",
            ],
            "observant": [
                "先看一圈，我先听。第一天信息太少，但发言状态本身就是信息。看看今天风向再说。",
                "不急开口，我先观察一下大家的状态。谁紧张、谁放松、谁在刻意表演，我心里有数。",
                "先观望一轮。我想看看每个人的发言节奏和措辞，这些比具体内容更能说明问题。",
            ],
            "meticulous": [
                "每个人最好都说一个最关注的对象，我会把今天的发言记下来对照。大家一个个来，把想法说清楚。",
                "先收集信息，不急下结论。但每个人至少说一个关注对象，不表态本身就是一种表态。",
                "首轮发言很关键，后面都要拿来对照的。我希望大家留个初步印象，不要光说'先听听'就完了。",
            ],
            "insightful": [
                "先听听大家对桌面的感觉。今天的微表情比内容更值得在意，谁在试探、谁在装，我能感觉到。",
                "我想先感受一下场上的气氛。第一天不是没信息——发言状态本身就是信息。先听。",
                "开局发言能看出一个人的底色。谁在主动带节奏、谁在被动跟风，一眼就看得出来。",
            ],
            "persuasive": [
                "大家放松，按顺序说就好。想到什么先说什么，别憋着。第一天最重要的是让大家都有说话的机会。",
                "别紧张，说错了也没事。每个人说一下自己怎么看这局，别急着互踩，先建立信任。",
                "第一天轻松点，大家说说初步感觉就行。不用太有压力，但每个人至少说一两句。",
            ],
            "aggressive": [
                "不要划水，话讲明白。今天谁含糊我就盯谁，痛快点，有话直说。",
                "今天谁含糊我就盯谁。不发言不代表安全，恰恰相反，沉默的人我重点关注。",
                "痛快点，有话直说。我懒得听废话，每个人把自己的判断摆出来，别藏着掖着。",
            ],
            "expressive": [
                "来嘛大家轮流说说～我超想知道你们怎么看的！第一天好紧张呀，都别藏着！",
                "我超想知道你们怎么看的！气氛好紧张，大家都放松聊嘛，我想听听每个人的想法。",
                "来来来都别藏着！第一天大家都说说嘛，我直觉很准的，等会儿我来判断谁最可疑～",
            ],
            "provocative": [
                "谁先怂谁先说。我等着有人来跟我对线，谁敢第一个亮牌？",
                "我等着有人来跟我对线。第一天就是最好的试金石，谁敢说话、谁在躲，一眼就看得出来。",
                "谁敢第一个亮牌？我话放这——今天不发言的人明天我重点关注。",
            ],
            "neutral": [
                "大家都说说自己的判断，我听完再定方向。一个个来吧，把想法摆明面上。",
                "先听完所有人的发言再做判断。每个人至少说一两句，不表态也是一种表态。",
                "我觉得现在还早，多听听再决定。但每个人最好都说一下自己的关注对象。",
            ],
        }
        lines = templates.get(style, templates["neutral"])
        return rng.choice(lines)

    def _day1_observation(self, style: str, my_name: str, speeches: list[dict], alive: int,
                          event_facts: dict | None = None, rng: Random | None = None) -> str:
        """Day 1: no info yet. Observe behavior, ask questions, don't accuse."""
        rng = rng or self.rng
        event_facts = event_facts or {}
        speakers = set()
        for s in speeches:
            speakers.add(s.get("payload", {}).get("actor_name", ""))
        quiet_count = alive - len(speakers) - 1  # minus self

        # Build event-specific additions
        event_suffix = ""
        quiet_names = event_facts.get("quiet_players", [])
        badge_name = event_facts.get("badge_holder_name", "")
        if quiet_names and len(quiet_names) <= 3:
            quiet_tags = "、".join(self._tag_by_name(n) for n in quiet_names[:3])
            event_suffix += f" {quiet_tags}还没开口，想听听他们的。"
        elif quiet_count > 0:
            event_suffix += f" 还有{quiet_count}个人没表态。"
        if badge_name:
            event_suffix += f" 警长{self._tag_by_name(badge_name)}可以先带个节奏。"

        observations = {
            "analytical": [
                f"第一天没什么信息，我先听听大家的发言。{alive}个人在场，有{quiet_count}个还没说话，我想听听他们的看法。首轮重点不是站边，是看发言状态和逻辑一致性。{event_suffix}",
                f"开局信息有限，大家按顺序聊。我重点关注发言态度——谁在试探、谁在划水、谁在刻意回避问题。{event_suffix.strip()}",
                f"第一天信息不多，我不急着下判断。我的策略是先观察后分析，{alive}人局先收集信息。{event_suffix.strip()}",
                f"首轮大家放松聊，我会留意谁在刻意回避问题。{quiet_count}人还在观望，等他们表态之后我再整理思路。{event_suffix.strip()}",
            ],
            "observant": [
                f"第一轮，先看。{alive}个人在场，我注意有人还没开口，不急下定论。先听一圈再说。{event_suffix.strip()}",
                f"开局不急，先听一圈。第一天信息太少，但发言状态本身就是信息。{event_suffix.strip()}",
                f"先观望一轮。我想看看每个人的发言节奏和措辞，这些比具体内容更能说明问题。{event_suffix.strip()}",
            ],
            "meticulous": [
                f"第一天信息不足，我建议每人都说一下自己最关注谁，这样后面复盘有依据。{alive}个人，我希望每人都留个初步印象。{event_suffix.strip()}",
                f"首轮发言很关键，后面都要拿来对照的。我希望大家至少说一个关注对象，不要光说'先听听'就完了。{event_suffix.strip()}",
                f"第一天别急着踩人，但每个人最好表态。不表态本身就是一种表态，我会记下来的。{event_suffix.strip()}",
            ],
            "insightful": [
                f"第一天是最能看出谁在试探的阶段。我想先听听所有人的发言再做判断。{quiet_count}个人还没说话，我等他们。{event_suffix.strip()}",
                f"开局发言能看出一个人的底色。谁在主动带节奏、谁在被动跟风，一眼就看得出来。{event_suffix.strip()}",
                f"第一天不是没信息——发言状态本身就是信息。谁紧张、谁放松、谁在刻意表演，我都看在眼里。{event_suffix.strip()}",
            ],
            "persuasive": [
                f"大家好，第一天我们先互相认识一下。每个人说一下自己怎么看这局，别急着互踩。{alive}个人，慢慢来。{event_suffix.strip()}",
                f"开局先聊开，别紧张。想到什么先说什么，别憋着。第一天最重要的是让大家都有说话的机会。{event_suffix.strip()}",
                f"第一天轻松点，大家说说初步感觉就行。不用太有压力，但每个人至少说一两句。{event_suffix.strip()}",
            ],
            "aggressive": [
                f"第一天我不急着定人，但看了一圈，有人已经很活跃有人完全沉默。沉默的别忘了发言，我记着呢。{event_suffix.strip()}",
                f"开局不踩人不代表不观察。{quiet_count}个人还没开口，我等你们。谁含糊我就盯谁。{event_suffix.strip()}",
                f"第一天我不推人，但我记着谁在躲。不发言不代表安全，恰恰相反，沉默的人我重点关注。{event_suffix.strip()}",
            ],
            "expressive": [
                f"哇第一天好紧张！我还不知道该怀疑谁呢，先听听大家都怎么说吧。{alive}个人，今天一定很精彩！{event_suffix.strip()}",
                f"好激动！第一天大家都放松聊嘛，我超想知道你们怎么看的！{event_suffix.strip()}",
                f"第一天！气氛好紧张呀，我都不知道该看谁。先听大家说，我直觉很准的～{event_suffix.strip()}",
            ],
            "provocative": [
                f"第一天就图一乐，先看看谁会跳、谁会缩。我话放这——今天不发言的人明天我重点关注。{event_suffix.strip()}",
                f"开局就是最好的试金石。谁敢说话、谁在躲，一眼就看得出来。我已经有了初步名单。{event_suffix.strip()}",
                f"第一天我不点名，但心里已经有数了。谁在试探、谁在装，我先不说，你们自己品。{event_suffix.strip()}",
            ],
            "neutral": [
                f"第一天我还没什么头绪，先听完大家的发言再整理思路。{quiet_count}个人还没说，等他们。{event_suffix.strip()}",
                f"首轮发言很重要，我需要了解每个人的基本立场。先听一轮，不急着表态。{event_suffix.strip()}",
                f"第一轮我不急着表态。{alive}人局，信息还不够，大家多聊聊，我听着呢。{event_suffix.strip()}",
            ],
        }
        options = observations.get(style, observations.get("neutral", observations["analytical"]))
        return rng.choice(options) if isinstance(options, list) else options

    def _strong_push(self, role: Role, my_name: str, alive: int) -> str:
        """We have strong evidence — push hard on our target.

        Seers do NOT automatically reveal their role.  They only claim openly
        when it is safe or necessary (late game, multiple checks, or when the
        village is losing).  Otherwise they push with conviction but keep
        their identity hidden so they survive another night.
        """
        if self.known_wolf_ids:
            wolf_id = next(iter(self.known_wolf_ids))
            wolf = self._player(wolf_id)
            if wolf and wolf["alive"]:
                tag = self._tag(wolf)
                if role == Role.SEER:
                    day = self._view().day
                    village_alive = sum(
                        1 for p in self._view().players
                        if p["alive"] and p.get("alignment") != "wolf"
                    )
                    wolf_alive = sum(
                        1 for p in self._view().players
                        if p["alive"] and p.get("role") in ("Werewolf", "WhiteWolfKing")
                    )
                    # Reveal only when: late game, multiple checks, or village is outnumbered
                    should_reveal = (
                        day >= 3
                        or len(self.known_wolf_ids) >= 2
                        or village_alive <= wolf_alive + 2
                    )
                    if should_reveal:
                        return f"我是预言家，昨晚验了{tag}，查杀！今天全票出{tag}，不接受分票。有对跳的出来，我等着。"
                    else:
                        # Push hard without revealing role — survive to check again
                        return f"我基本确定{tag}是狼人。今天必须出他，原因我后面会说明。信我这一轮，不要分票。"
                else:
                    return f"我强烈怀疑{tag}是狼。今天的票应该集中在他身上，不要分散。我有比较强的把握，大家信我。"
        return "我有比较强的把握，今天的票型要集中。大家不要分散投票，跟着我的判断走。"

    def _developing_case(self, role: Role, style: str, my_name: str, speeches: list[dict], alive: int,
                         rng: Random, event_facts: dict | None = None) -> str:
        """Some information, building a case but not certain."""
        top = self._highest_suspicion_alive()
        score = self.suspicion.get(top["id"], 0)
        tag = self._tag(top)

        if score >= 2.5:
            lines = [
                f"我重点怀疑{tag}。他的票型和发言对不上，前后矛盾的地方不少。大家回去看他之前的发言，逻辑断裂很明显。",
                f"我越来越觉得{tag}有问题。他的几次站边都比较微妙，而且每次投票都踩在最安全的位置上。{tag}就是我今天想推的人。",
                f"我把票暂时挂在{tag}头上。证据链短但方向对，他的行为模式不像是好人。欢迎反驳，但请拿出实质证据。",
                f"我不绕弯子，{tag}是我今天的第一目标。他这几轮的表现越来越像狼，大家回头看他的发言就知道了。",
                f"{tag}的几次站边都比较微妙，我心里基本定了。今天就看他怎么回应，如果继续含糊，那基本没跑了。",
            ]
            return rng.choice(lines)
        elif score >= 1.5:
            lines = [
                f"我比较关注{tag}，但还不完全确定。他的发言有几个点让我不太舒服，不过我愿意听他的解释。大家也说说对他怎么看。",
                f"暂时指向{tag}，有几个点让我不太舒服。证据还差一点，但方向是对的。有人有补充信息吗？",
                f"我对{tag}留了个心眼，今天会重点听他怎么回应。目前最像问题选手的是他，但我还要再确认。",
                f"{tag}在我这里有点问题，不过我不锁死。他的行为模式有些奇怪，但可能是我多想了。先听他自己怎么说。",
                f"我会把注意力放在{tag}身上。他之前的几次表态和投票有矛盾，我想看看他今天怎么解释。",
            ]
            return rng.choice(lines)
        elif score >= 0.8:
            lines = [
                f"我还不太确定，但{tag}稍微引起了我的注意。目前线索不多，但他的几个举动让我多看了两眼。继续观察。",
                f"信息有限，不过{tag}有点微妙。他的发言风格和其他人不太一样，但不代表他就是狼。先不急着下结论。",
                f"我把{tag}先放在观察名单里。暂时在我视野里，但不代表他就一定是狼，原因后面会展开。",
            ]
            return rng.choice(lines)
        else:
            lines = [
                "信息还不够，我想再听一轮发言。大家都把自己的怀疑对象说清楚，不要光说'先听听'就完了。",
                "现在线索比较分散，我建议大家先回顾一下前面的发言，看看有没有矛盾。每个人至少说一个关注对象。",
                "我还需要更多信息。每个人说说自己最怀疑谁、为什么，这样后面复盘才有依据。",
                "现在判断比较困难，我希望这轮发言大家能多给一些具体的信息。不要泛泛而谈，要有具体的怀疑对象和理由。",
                "信息密度不够，我想多听几个人的真实想法。现在谁都不好定，但我想听听后置位有没有新信息。",
                "我还在收集信息阶段，不急着站边。目前手里的线索太碎，我先不点名，想多观察一轮。",
                "今天发言信息量偏少，我希望没发言的几位多说几句。不表态本身就是一种表态，我会记下来。",
            ]
            return rng.choice(lines)

    def _respond_to_others(self, style: str, my_name: str, rng: Random) -> str:
        """Respond naturally to what other players said.

        Capped so the speech doesn't end up as a long echo chain — at most
        one response is appended, and even that only when something specific
        actually triggers it.
        """
        if not self.last_speeches:
            return ""
        latest = self.last_speeches[-1]
        speaker_name = latest.get("payload", {}).get("actor_name", "")
        speaker_tag = self._tag_by_name(speaker_name)
        speech_text = latest.get("payload", {}).get("speech", "")

        claims_seer = self._detect_seer_self_claim(speech_text)
        if claims_seer:
            claimed_target = self._extract_seer_target(speech_text, my_name)
            if claimed_target:
                target_tag = self._tag_by_name(claimed_target)
                return f"{speaker_tag}跳预言家说验了{target_tag}。先记下，看有没有人对跳。"
            return f"{speaker_tag}跳预言家了。等等看有没有反跳的。"

        if my_name and my_name in speech_text:
            pushbacks = [
                f"{speaker_tag}点我了，我没什么好藏的，发言可以回头查。",
                f"{speaker_tag}怀疑我，那等会儿我会把我的逻辑摆给你看。",
                f"我听到了{speaker_tag}的怀疑，先不急着自证，看他下一句怎么接。",
            ]
            return rng.choice(pushbacks)

        top = self._highest_suspicion_alive()
        top_name = top.get("name") or ""
        if top_name and top_name in speech_text and rng.random() < 0.5:
            top_tag = self._tag(top)
            echoes = [
                f"{speaker_tag}对{top_tag}的怀疑我能接住。",
                f"{speaker_tag}提到的{top_tag}，我也有类似看法。",
                f"和{speaker_tag}一样，我也对{top_tag}存疑。",
            ]
            return rng.choice(echoes)

        return ""

    @staticmethod
    def _detect_seer_self_claim(text: str) -> bool:
        """Return True only when the speaker EXPLICITLY claims to be the Seer.

        Pure "查杀"/"金水" mentions are too noisy — wolves and villagers parrot
        those words constantly. We instead require a self-identifier ("我是
        预言家"/"我跳预言家") OR a paired self-verb ("我查了"/"我验了"/"昨晚
        验了") within the same speech.
        """
        if not text:
            return False
        strong = ("我是预言家", "我跳预言家", "我跳预", "我跳P", "I am the Seer", "I'm the Seer")
        if any(phrase in text for phrase in strong):
            return True
        verb_pairs = (
            ("昨晚", "查"),
            ("我查", "了"),
            ("我验", "了"),
            ("我昨晚", "查"),
            ("我昨晚", "验"),
        )
        for left, right in verb_pairs:
            if left in text and right in text and text.index(left) < text.index(right):
                return True
        return False

    def _extract_seer_target(self, speech_text: str, my_name: str) -> str | None:
        """Pull the actually-claimed target out of the speech.

        Falls back to None when we can't find any player name in the speech —
        previously we'd return the speaker's name itself, which produced the
        nonsense "X 跳预言家说验了 X" lines.
        """
        view = self._view()
        for player in view.players:
            name = player.get("name")
            if not name or name == my_name:
                continue
            if name in speech_text:
                return name
        return None

    def _call_vote(self) -> str:
        target = self._highest_suspicion_alive()
        return f"我的票归{self._tag(target)}。"

    def _call_discussion(self, style: str = "neutral", rng: Random | None = None) -> str:
        rng = rng or self.rng
        templates = {
            "analytical": [
                "大家把票型说清楚，不要随便挂。我要听理由，不要只报名字，每个人说一下自己的判断逻辑。",
                "我希望听到大家具体的怀疑链条。每个人都把自己的判断逻辑讲一下，这样后面复盘才有依据。",
                "我要听理由，不要只报名字。每个人说一下你最怀疑谁、为什么，不要泛泛而谈。",
            ],
            "observant": [
                "谁有要补的，先说。都讲完再投，不急。还有没说话的吗？",
                "都讲完再投。我想看看大家的真实判断，不要跟风，每个人说自己的想法。",
                "还有没说话的吗？不表态也是一种表态，我会记下来的。",
            ],
            "meticulous": [
                "请大家说一下今天最值得复盘的发言。把今天的票向理由列一下，每个人说一个你最在意的细节。",
                "每个人说一个你最在意的细节。我要把今天的发言和前两天的做对照，看看有没有矛盾。",
                "把今天的票向理由列一下。不要只说'我觉得他可疑'，要说具体哪里可疑。",
            ],
            "insightful": [
                "想听听大家心里真正在意的人。把心里最沉的那一票讲出来，别藏着。",
                "别藏着，谁让你最不舒服？说出来，不要闷在心里，信息共享对好人有利。",
                "把心里最沉的那一票讲出来。我想看看大家的真实判断，不要跟风。",
            ],
            "persuasive": [
                "不要互相伤害，每人讲讲自己的判断。大家心平气和地把怀疑摆出来，放松，说错了没关系。",
                "大家心平气和地把怀疑摆出来。放松，说错了没关系，重要的是真实。",
                "放松，说错了没关系，重要的是真实。每个人说一下自己怎么看，不要有压力。",
            ],
            "aggressive": [
                "话讲明白，不准划水。谁含糊我下个就盯谁，痛快点，别跟我绕。",
                "谁含糊我下个就盯谁。该表态了，别躲。每个人把自己的判断摆出来。",
                "痛快点，别跟我绕。该表态了，别躲。不发言的人我默认有问题。",
            ],
            "expressive": [
                "来嘛把心里话都说出来呀～别藏！都说说！我好想知道你们都在想什么！",
                "别藏！都说说！我好想知道你们都在想什么，大家都放松聊嘛～",
                "我好想知道你们都在想什么！每个人说说自己的想法嘛，别闷着～",
            ],
            "provocative": [
                "不发言的我已经记本上了。今天谁敢不站队？我等着看谁敢跟我对票。",
                "今天谁敢不站队？我等着看谁敢跟我对票。不表态的人我重点关注。",
                "我等着看谁敢跟我对票。不发言的我已经记本上了，别以为沉默就安全。",
            ],
        }
        lines = templates.get(style, [
            "大家各自说说自己的票向，不要跟风。都聊聊自己怎么想的，别藏着。",
            "都聊聊自己怎么想的，别藏着。一个个把判断理由说清楚，不要只报名字。",
            "一个个把判断理由说清楚。每个人说一下你最怀疑谁、为什么。",
        ])
        return rng.choice(lines)

    # ---- Target selection ----

    def _choose_vote_target(self) -> dict:
        """Choose vote target using probabilistic weighted sampling.

        No longer always picks max(suspicion). Instead builds composite scores
        from suspicion, grudges, stance consistency, recency, and follow signals,
        then samples via softmax with personality-driven temperature.
        """
        view = self._view()
        hp = self.human_profile
        day = view.day

        # If we know a wolf (seer check), always vote them
        for wid in self.known_wolf_ids:
            p = self._player(wid)
            if p and p["alive"]:
                return p

        # Wolves: vote a non-wolf
        if self.role in WOLF_FAMILY:
            return self._choose_non_wolf()

        # Build composite scores for all alive others
        candidates = self._alive_others()
        if not candidates:
            return {"id": "", "name": "nobody", "alive": True}

        scores: dict[str, float] = {}
        for p in candidates:
            pid = p["id"]
            if pid in self.known_good_ids:
                scores[pid] = -10.0
                continue
            if pid in self.known_wolf_ids:
                scores[pid] = 10.0
                continue

            base = self.suspicion.get(pid, 0.0)
            # Grudge bonus: did they recently point at me?
            grudge = self.public_stance["grudges"].get(pid, 0.0) * hp.grudge_weight
            # Stance consistency: did I publicly suspect them last round?
            stance_bonus = 0.0
            if pid in self.public_stance["suspects"]:
                stance_bonus = 0.3 * hp.stubbornness
            # Recency bonus: mentioned in last 3 speeches?
            recency = 0.0
            for s in self.last_speeches[-3:]:
                if pid in str(s.get("payload", {}).get("speech", "")):
                    recency = 0.2 * hp.recency_weight
                    break
            # Follow bonus: do my trusted players suspect them?
            follow = 0.0
            for trusted_id in self.public_stance.get("trusted", {}):
                if trusted_id in self.public_stance.get("suspects", {}):
                    # Check if trusted player voted for this candidate
                    for e in view.public_events[-5:]:
                        if e.get("type") == "VOTE_CAST":
                            pl = e.get("payload", {})
                            if pl.get("voter_id") == trusted_id and pl.get("target_id") == pid:
                                follow = 0.3 * hp.follow_weight
                                break

            # Tunnel bonus for first_impression types
            tunnel = 0.0
            if pid == self.public_stance.get("tunnel_target"):
                tunnel = 0.5

            scores[pid] = base + grudge + stance_bonus + recency + follow + tunnel

        # Day 1 without strong info: increase temperature for vote scattering
        temp = hp.vote_temperature
        has_strong_info = bool(self.known_wolf_ids) or bool(self.known_good_ids)
        if day <= 1 and not has_strong_info:
            temp += 0.5

        # If all scores are negative/zero, fall back to uniform random
        max_score = max(scores.values()) if scores else 0
        if max_score <= 0:
            return self.rng.choice(candidates) if candidates else {"id": "", "name": "nobody", "alive": True}

        # Softmax-weighted sampling
        chosen = self._softmax_sample(scores, temp)

        # Generate human-like reasoning
        reasoning = self._build_vote_reasoning(chosen, scores, candidates)
        self.public_stance["last_vote_target"] = chosen

        p = self._player(chosen)
        if p:
            # Attach reasoning to be picked up by vote()
            self._last_vote_reasoning = reasoning
            return p
        return candidates[0] if candidates else {"id": "", "name": "nobody", "alive": True}

    def _softmax_sample(self, scores: dict[str, float], temperature: float) -> str:
        """Sample a player_id from scores using softmax probabilities."""
        temp = max(temperature, 0.05)  # prevent division by zero
        entries = list(scores.items())
        weights = [math.exp(min(s / temp, 50)) for _, s in entries]  # cap to avoid overflow
        total = sum(weights)
        if total <= 0:
            return entries[0][0]
        probs = [w / total for w in weights]
        # Use self.rng for reproducibility
        r = self.rng.random()
        cumulative = 0.0
        for (pid, _), prob in zip(entries, probs):
            cumulative += prob
            if r <= cumulative:
                return pid
        return entries[-1][0]

    def _build_vote_reasoning(self, chosen: str, scores: dict[str, float], candidates: list[dict]) -> str:
        """Generate a human-like vote reasoning string."""
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        top_pid, top_score = sorted_scores[0] if sorted_scores else ("", 0)
        p = self._player(chosen)
        tag = self._tag(p) if p else "?"

        if chosen == top_pid and top_score >= 2.0:
            return f"{tag}的问题最明显，先挂他"
        elif chosen == top_pid:
            return f"我比较在意{tag}，票先挂这里"
        elif chosen in self.public_stance.get("grudges", {}):
            return f"{tag}刚才点我的方式不太对，我想听听他怎么解释"
        elif self.public_stance.get("follow_player"):
            follow_tag = self._tag(self._player(self.public_stance["follow_player"]))
            return f"我跟{follow_tag}的判断，先看看{tag}的反应"
        else:
            return f"我不是完全锁死{tag}，但这轮他回应压力的方式最别扭，先挂他"

    def _choose_wolf_kill_target(self) -> dict:
        """Wolves choose kill target: night 0 blind, then strategic.

        Night 0 (no speeches yet): random non-wolf target — blind kill.
        Night 1+: evaluate based on daytime speech for power role claims.
        """
        candidates = self._alive_others()
        view = self._view()

        # Night 0 (day 0): blind kill — exclude teammates, pick randomly
        if view.day <= 1:
            wolf_ids = {p["id"] for p in view.known_wolves}
            non_wolves = [p for p in candidates if p["id"] not in wolf_ids]
            return self.rng.choice(non_wolves) if non_wolves else self.rng.choice(candidates)

        # Night 1+: strategic targeting based on daytime behavior
        # Score candidates by: claim detection + discussion leadership + random factor
        claim_scores: dict[str, float] = {}
        for c in candidates:
            score = self.rng.uniform(0, 0.5)  # base random factor
            for e in view.public_events[-20:]:
                if e.get("type") == "CHAT_MESSAGE":
                    speech = e.get("payload", {}).get("speech", "")
                    speaker = e.get("payload", {}).get("actor_name", "")
                    # Someone claiming a power role (not the speaker themselves unless it matches)
                    if ("预言家" in speech or "查验" in speech or "查杀" in speech) and c["name"] in speech:
                        score += 1.0
                    # Leading discussion: the speaker names specific targets
                    if speaker == c["name"] and ("怀疑" in speech or "票" in speech or "推" in speech):
                        score += 0.5
            claim_scores[c["id"]] = score

        # Pick top-scored candidate with some randomness
        sorted_targets = sorted(claim_scores.items(), key=lambda x: -x[1])
        # Top 2 candidates, random choice between them
        top_n = min(3, len(sorted_targets))
        chosen_id = self.rng.choice([t[0] for t in sorted_targets[:top_n]])
        p = self._player(chosen_id)
        return p if p else candidates[0]

    def _choose_divine_target(self) -> dict:
        """Seer: check a high-value unknown target."""
        candidates = self._alive_others()
        # Prioritize unchecked players who are vocal
        already_checked = set()
        for e in self._view().private_events:
            tid = e.get("payload", {}).get("target_id")
            if tid:
                already_checked.add(tid)
        unchecked = [c for c in candidates if c["id"] not in already_checked]
        if unchecked:
            return self.rng.choice(unchecked)
        return self.rng.choice(candidates)

    def _choose_guard_target(self) -> dict:
        """Guard: protect likely village power role or self."""
        candidates = self._alive_others(include_self=True)
        # Look for Seer claims
        for c in candidates:
            for e in self._view().public_events[-10:]:
                if e.get("type") == "CHAT_MESSAGE":
                    if "预言家" in e.get("payload", {}).get("speech", "") and c["name"] in e.get("payload", {}).get("speech", ""):
                        return c
        # Guard self or random good-looking player
        me = self._player(self.player_id)
        return me if me and me["alive"] else self.rng.choice(candidates)

    def _highest_suspicion_alive(self) -> dict:
        alive = [p for p in self._alive_others() if p["id"] not in self.known_good_ids]
        if not alive:
            alive = self._alive_others()
        if not alive:
            return {"id": "", "name": "nobody", "alive": True}
        return max(alive, key=lambda p: self.suspicion.get(p["id"], 0))

    def _choose_non_wolf(self) -> dict:
        view = self._view()
        wolf_ids = {p["id"] for p in view.known_wolves}
        candidates = [p for p in self._alive_others() if p["id"] not in wolf_ids]
        return self.rng.choice(candidates) if candidates else self._alive_others()[0]

    def _pick_wolf_fake_seer_target(self) -> dict | None:
        """Pick a non-wolf alive player for a wolf to claim as their Seer check target."""
        view = self._view()
        wolf_ids = {p["id"] for p in view.known_wolves}
        candidates = [
            p for p in self._alive_others()
            if p["id"] not in wolf_ids and p["id"] != self.player_id
        ]
        return self.rng.choice(candidates) if candidates else None

    def _wolf_seer_counter_claim(self, rng: Random) -> str | None:
        """Wolves: proactively fake Seer claim or counter-claim existing ones."""
        view = self._view()
        if self.role not in WOLF_FAMILY:
            return None
        if view.day < 1:
            return None
        hp = self.human_profile
        if hp.risk_appetite == "low" and rng.random() < 0.7:
            return None

        # Scan for existing Seer claims
        seer_already_claimed = False
        for e in view.public_events[-15:]:
            if e.get("type") == "CHAT_MESSAGE":
                if self._detect_seer_self_claim(e.get("payload", {}).get("speech", "")):
                    seer_already_claimed = True
                    break

        # Proactive claim: wolves can initiate a fake Seer claim even with no
        # real Seer having spoken yet — this is a classic wolf tactic.
        if not seer_already_claimed:
            # Only on day 1-3, and not too often
            if view.day > 3:
                return None
            if rng.random() > 0.08:  # ~8% chance per wolf per round
                return None
        else:
            # Counter-claim an existing Seer
            if rng.random() > 0.35:
                return None

        fake_target = self._pick_wolf_fake_seer_target()
        if not fake_target:
            return None
        fake_tag = self._tag(fake_target)
        fake_name = fake_target.get("name", "?")

        # Pick strategy: 金水 (good) or 查杀 (wolf) for the target
        if seer_already_claimed:
            # Counter-claim: undermine the real Seer
            return f"我是真预言家。昨晚验了{fake_tag}，金水。刚才跳预言家那个是悍跳狼，今天出他。"
        else:
            # Proactive fake claim
            if rng.random() < 0.4:
                # Claim someone is wolf (查杀) — aggressive play
                return f"我是预言家，昨晚验了{fake_tag}，查杀！今天全票出{fake_tag}。有对跳的出来。"
            else:
                # Claim someone is good (金水) — build credibility
                return f"我是预言家。昨晚验了{fake_tag}，金水。好人别分票，跟着我的查验走。"

    def _extract_name_from_speech(self, text: str) -> str | None:
        """Extract a player name mentioned in speech."""
        for p in self._view().players:
            if p["name"] in text:
                return p["name"]
        return None

    # ---- Helpers ----

    @property
    def role(self) -> Role:
        return Role(self._view().self_player["role"])

    def _view(self) -> PlayerView:
        if self.view is None:
            raise RuntimeError("Agent not initialized")
        return self.view

    def _alive_others(self, *, include_self: bool = False) -> list[dict]:
        view = self._view()
        return [p for p in view.players if p["alive"] and (include_self or p["id"] != view.player_id)]

    def _player(self, player_id: str) -> dict | None:
        return next((p for p in self._view().players if p["id"] == player_id), None)

    @staticmethod
    def _tag(player: dict | None) -> str:
        """Return @N号:名字 callout for a player dict (or empty string)."""
        if not player:
            return ""
        seat = player.get("seat", "?")
        name = player.get("name", "?")
        return f"@{seat}号:{name}"

    def _tag_by_name(self, name: str) -> str:
        """Resolve raw player name → @N号:名字 (falls back to bare name)."""
        if not name:
            return ""
        for p in self._view().players:
            if p.get("name") == name:
                return self._tag(p)
        return name

    def _init_suspicion(self) -> None:
        view = self._view()
        for p in view.players:
            if p["id"] != self.player_id:
                self.suspicion[p["id"]] = 0.0
