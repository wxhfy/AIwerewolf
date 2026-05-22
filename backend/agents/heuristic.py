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

from backend.agents.base import Agent
from backend.agents.characters import Character
from backend.agents.playbooks import build_role_brief
from backend.engine.models import ActionType, Decision, Role
from backend.engine.visibility import PlayerView


class HeuristicAgent(Agent):
    """Context-aware agent that reasons from available information.

    Key principles:
    - Day 1 with no info → observe, don't accuse blindly
    - Each piece of evidence updates suspicion incrementally
    - Speech reflects actual reasoning, not templates
    - Different roles use different evidence sources
    """

    def __init__(self, player_id: str, *, seed: int | None = None, character: Character | None = None):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.rng = Random(seed)
        self.winner: str | None = None
        self.character = character
        # Suspicion tracking: player_id → score (higher = more suspicious)
        self.suspicion: dict[str, float] = {}
        # What we definitively know
        self.known_wolf_ids: set[str] = set()  # seer checks or wolf teammates
        self.known_good_ids: set[str] = set()  # seer gold checks
        # Round tracking
        self.last_speeches: list[dict] = []  # speeches heard this round

    # ---- Agent lifecycle ----

    def initialize(self, view: PlayerView, game_setting: dict) -> None:
        self.view = view
        self._init_suspicion()
        char_name = self.character.persona.name if self.character else "Player"
        role = self.role.value
        # Wolves know their teammates
        if self.role in {Role.WEREWOLF, Role.WHITE_WOLF_KING}:
            for w in view.known_wolves:
                if w["id"] != self.player_id:
                    self.known_good_ids.add(w["id"])  # Wolf teammates are "good" from wolf perspective

    def update(self, view: PlayerView, request: str) -> None:
        self.view = view
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
        """Learn from public events: votes, deaths, speech patterns."""
        view = self._view()
        recent = view.public_events[-20:]
        my_name = view.self_player.get("name", "")

        for e in recent:
            if e.get("type") == "VOTE_CAST":
                voter = e.get("payload", {}).get("voter_id")
                target = e.get("payload", {}).get("target_id")
                voter_name = e.get("payload", {}).get("voter_name", "")
                if voter and target and target != self.player_id:
                    # Voting increases mutual suspicion
                    self._adjust_suspicion(voter, 0.2, "voted")
                    # Being voted for increases suspicion
                    self._adjust_suspicion(target, 0.15, "voted_against")
                    # If someone voted for a known good player, they're more suspicious
                    if target in self.known_good_ids:
                        self._adjust_suspicion(voter, 0.5, "voted_known_good")

            if e.get("type") == "PLAYER_DIED":
                pid = e.get("payload", {}).get("player_id")
                reason = e.get("payload", {}).get("reason", "")
                if pid and pid not in self.known_wolf_ids:
                    if reason == "wolf":
                        self._adjust_suspicion(pid, -0.5, "killed_by_wolf")
                    elif reason == "vote":
                        self._adjust_suspicion(pid, -0.3, "voted_out")

            if e.get("type") == "CHAT_MESSAGE":
                speech = e.get("payload", {}).get("speech", "")
                actor = e.get("payload", {}).get("actor_id")
                actor_name = e.get("payload", {}).get("actor_name", "")
                if actor and actor != self.player_id:
                    # Vague/fence-sitting speech
                    vague = sum(1 for w in ["可能吧", "不确定", "再看看", "不好说"] if w in speech)
                    if vague >= 2:
                        self._adjust_suspicion(actor, 0.15, "vague")
                    # Aggressive early accusations (day 1) without evidence
                    if view.day <= 1 and ("是狼" in speech or "查杀" in speech or "票他" in speech):
                        if actor not in self.known_wolf_ids and actor not in self.known_good_ids:
                            self._adjust_suspicion(actor, 0.1, "early_aggression")
                    # Track who mentions our name (could be pushing us)
                    if my_name in speech:
                        self._adjust_suspicion(actor, 0.25, f"mentioned_me")

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

        # STEP 1: Assess what information we actually have
        info_level = self._assess_information()

        # STEP 2: Build speech based on information + game state + role strategy
        speech, reasoning = self._build_contextual_speech(
            role=role, day=day, info_level=info_level,
            alive_count=alive_count, my_name=my_name,
        )
        return Decision(view.player_id, ActionType.TALK, speech=speech, reasoning=reasoning)

    def vote(self) -> Decision:
        view = self._view()
        target = self._choose_vote_target()
        return Decision(view.player_id, ActionType.VOTE, target_id=target["id"],
                       reasoning=f"Voting {target['name']} based on suspicion score {self.suspicion.get(target['id'], 0):.1f}")

    def attack(self) -> Decision:
        view = self._view()
        target = self._choose_wolf_kill_target()
        return Decision(view.player_id, ActionType.ATTACK, target_id=target["id"],
                       reasoning=f"Wolves target {target['name']} as highest-value village player")

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
        target = self._highest_suspicion_alive()
        if self._view().day >= 3 or self.suspicion.get(target["id"], 0.0) >= 2.5:
            return Decision(
                view.player_id,
                ActionType.BOOM,
                target_id=target["id"],
                reasoning=f"White Wolf King self-destructs to force out {target['name']}",
            )
        return Decision(view.player_id, ActionType.SKIP, reasoning="Hold the boom for a higher-value timing.")

    # ---- Information assessment ----

    def _assess_information(self) -> str:
        """Determine how much actionable information we have."""
        if self.known_wolf_ids:
            return "strong"
        view = self._view()
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

    # ---- Speech construction ----

    def _build_contextual_speech(self, *, role, day, info_level, alive_count, my_name):
        """Build speech from actual context: what do I know? what just happened?"""
        view = self._view()
        char = self.character
        style = char.persona.style_label if char else "neutral"
        # Re-seed per-turn so different days produce different picks even when
        # the underlying suspicion landscape barely changed.
        local_rng = Random(hash((self.player_id, view.day, view.phase, info_level)))

        # Gather what just happened
        deaths_today = [e for e in view.public_events[-5:]
                       if e.get("type") == "PLAYER_DIED" and e.get("day") == day]
        recent_speeches = self.last_speeches

        # Build the speech organically
        parts: list[str] = []

        # 1. React to deaths
        if deaths_today:
            dead_names = [e.get("payload", {}).get("player_name", "?") for e in deaths_today]
            parts.append(self._reaction_to_death(style, dead_names, local_rng))

        # 2. State our position based on information level
        if info_level == "none":
            parts.append(self._day1_observation(style, my_name, recent_speeches, alive_count))
        elif info_level == "strong":
            parts.append(self._strong_push(role, my_name, alive_count))
        else:
            parts.append(self._developing_case(role, style, my_name, recent_speeches, alive_count, local_rng))

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

        speech = " ".join(parts).strip()
        reasoning = f"{my_name}({role.value}) day{day} info={info_level}: {'push' if info_level == 'strong' else 'observe' if info_level == 'none' else 'analyze'}"
        return speech, reasoning

    def _reaction_to_death(self, style: str, dead_names: list[str], rng: Random) -> str:
        tags = "、".join(self._tag_by_name(name) for name in dead_names)
        templates_by_style = {
            "analytical": [f"{tags}走了，得回看昨晚的目标选择。", f"{tags}的离场说明刀型不是随机。"],
            "observant": [f"{tags}死了。", f"{tags}走了。"],
            "meticulous": [f"{tags}的死要列入今天的判断依据。", f"先记一笔——{tags}昨晚没撑住。"],
            "insightful": [f"{tags}先走，节奏一下子变了。", f"{tags}的位置很关键，狼显然有目的。"],
            "persuasive": [f"我们少了{tags}，今天更要凝聚。", f"{tags}走了，大家心里都有数。"],
            "aggressive": [f"{tags}死得不冤吧？狼的刀很明显。", f"{tags}没了，今天就别再装死。"],
            "expressive": [f"哇{tags}竟然走了！心痛一下。", f"{tags}没撑住，我都看哭了。"],
            "provocative": [f"{tags}领盒饭了，狼这刀是要送票。", f"{tags}走了，刀型挺直白。"],
        }
        lines = templates_by_style.get(style, [f"昨晚{tags}死了。"])
        return rng.choice(lines)

    def _opening_close(self, style: str, rng: Random) -> str:
        templates = {
            "analytical": ["大家先把信息摆出来，方便我比对。", "我倾向先听完一轮再下判断。"],
            "observant": ["先看一圈。", "我先听。"],
            "meticulous": ["每个人最好都说一个最关注的对象。", "我会把今天的发言记下来对照。"],
            "insightful": ["先听听大家对桌面的感觉。", "今天的微表情比内容更值得在意。"],
            "persuasive": ["大家放松，按顺序说就好。", "想到什么先说什么，别憋。"],
            "aggressive": ["不要划水，话讲明白。", "今天谁含糊我就盯谁。"],
            "expressive": ["来嘛大家轮流说说～", "我超想知道你们怎么看的！"],
            "provocative": ["谁先怂谁先说。", "我等着有人来跟我对线。"],
        }
        lines = templates.get(style, ["大家先说说自己的看法吧。"])
        return rng.choice(lines)

    def _day1_observation(self, style: str, my_name: str, speeches: list[dict], alive: int) -> str:
        """Day 1: no info yet. Observe behavior, ask questions, don't accuse."""
        # Count who's spoken and who hasn't
        speakers = set()
        for s in speeches:
            speakers.add(s.get("payload", {}).get("actor_name", ""))
        quiet_count = alive - len(speakers) - 1  # minus self

        observations = {
            "analytical": f"第一天没什么信息，我先听听大家的发言。{alive}个人，有{quiet_count}个还没说话，我想听听他们的看法。",
            "observant": f"第一轮，先看。{alive}个人在场，我注意到有人还没开口，不急下定论。",
            "meticulous": f"第一天信息不足。我建议每人都说一下自己最关注谁，这样后面复盘有依据。现在有{quiet_count}人还没表态。",
            "insightful": f"第一天是最能看出谁在试探的阶段。我想先听听所有人的发言再做判断，现在{quiet_count}个人还没说话。",
            "persuasive": f"大家好，第一天我们先互相认识一下。每个人说一下自己怎么看这局，别急着互踩。",
            "aggressive": f"第一天我不急着定人，但看了一圈，有人已经很活跃有人完全沉默。沉默的别忘了发言。",
            "expressive": f"哇第一天好紧张！我还不知道该怀疑谁呢，先听听大家都怎么说吧～",
            "provocative": f"第一天就图一乐，先看看谁会跳、谁会缩。我话放这——今天不发言的人明天我重点关注。",
        }
        return observations.get(style, observations["analytical"])

    def _strong_push(self, role: Role, my_name: str, alive: int) -> str:
        """We have strong evidence — push hard on our target."""
        if self.known_wolf_ids:
            wolf_id = next(iter(self.known_wolf_ids))
            wolf = self._player(wolf_id)
            if wolf and wolf["alive"]:
                tag = self._tag(wolf)
                if role == Role.SEER:
                    return f"我是预言家，昨晚验了{tag}，查杀！今天全票出{tag}，不接受分票。有对跳的出来。"
                else:
                    return f"我强烈怀疑{tag}是狼。今天的票应该集中在他身上。"
        return "我有比较强的把握，今天的票型要集中。"

    def _developing_case(self, role: Role, style: str, my_name: str, speeches: list[dict], alive: int, rng: Random) -> str:
        """Some information, building a case but not certain."""
        top = self._highest_suspicion_alive()
        score = self.suspicion.get(top["id"], 0)
        tag = self._tag(top)

        if score >= 2.5:
            lines = [
                f"我重点怀疑{tag}。他的票型和发言对不上，前后矛盾的地方不少。",
                f"我越来越觉得{tag}有问题。大家回去看他之前的发言，逻辑断裂很明显。",
                f"{tag}就是我今天想推的人。理由已经说了——他的行为模式不像是好人。",
                f"我把票暂时挂在{tag}头上。证据链短但方向对，欢迎反驳。",
                f"{tag}的几次站边都比较微妙，我心里基本定了。",
            ]
            return rng.choice(lines)
        elif score >= 1.5:
            lines = [
                f"我比较关注{tag}，但还不完全确定。大家也说说对他怎么看。",
                f"暂时指向{tag}，有几个点让我不太舒服。但我愿意听他的解释。",
                f"{tag}的发言让我有点在意，证据还差一点。有人有补充信息吗？",
                f"我对{tag}留了个心眼，今天会重点听他怎么回应。",
                f"目前最像问题选手的是{tag}，但我还要再确认。",
            ]
            return rng.choice(lines)
        elif score >= 0.8:
            lines = [
                f"我还不太确定，但{tag}稍微引起了我的注意。继续观察。",
                f"目前线索不多，但{tag}的几个举动让我多看了两眼。",
                f"信息有限，不过{tag}有点微妙。先不急着下结论。",
                f"我把{tag}先放在观察名单里，原因后面会展开。",
            ]
            return rng.choice(lines)
        else:
            lines = [
                f"信息还不够，我想再听一轮发言。大家都把自己的怀疑对象说清楚。",
                f"现在线索比较分散，我建议大家先回顾一下前面的发言，看看有没有矛盾。",
                f"我还需要更多信息。每个人说说自己最怀疑谁、为什么。",
                f"现在判断比较困难。我希望这轮发言大家能多给一些具体的信息。",
                f"信息密度不够，我想多听几个人的真实想法。",
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
            "analytical": ["大家把票型说清楚，不要随便挂。", "我希望听到大家具体的怀疑链条。"],
            "observant": ["谁有要补的，先说。", "都讲完再投。"],
            "meticulous": ["请大家说一下今天最值得复盘的发言。", "把今天的票向理由列一下。"],
            "insightful": ["想听听大家心里真正在意的人。", "把心里最沉的那一票讲出来。"],
            "persuasive": ["不要互相伤害，每人讲讲自己的判断。", "大家心平气和地把怀疑摆出来。"],
            "aggressive": ["话讲明白，不准划水。", "谁含糊我下个就盯谁。"],
            "expressive": ["来嘛把心里话都说出来呀～", "别藏！都说说！"],
            "provocative": ["不发言的我已经记本上了。", "今天谁敢不站队？"],
        }
        lines = templates.get(style, ["大家各自说说自己的票向，不要跟风。"])
        return rng.choice(lines)

    # ---- Target selection ----

    def _choose_vote_target(self) -> dict:
        """Choose vote target based on actual evidence."""
        view = self._view()
        # If we know a wolf (seer check), vote them
        for wid in self.known_wolf_ids:
            p = self._player(wid)
            if p and p["alive"]:
                return p
        # Wolves: vote a non-wolf
        if self.role == Role.WEREWOLF:
            return self._choose_non_wolf()
        # Otherwise vote highest suspicion
        return self._highest_suspicion_alive()

    def _choose_wolf_kill_target(self) -> dict:
        """Wolves choose kill target: prioritize likely power roles."""
        candidates = self._alive_others()
        # Target players who seem like Seer/Witch (those making strong claims)
        for c in candidates:
            for e in self._view().public_events[-10:]:
                if e.get("type") == "CHAT_MESSAGE":
                    speech = e.get("payload", {}).get("speech", "")
                    if ("预言家" in speech or "查验" in speech or "查杀" in speech) and c["name"] in speech:
                        return c
        # Fallback: highest influence player
        return self._highest_suspicion_alive() if self.rng.random() < 0.5 else self._choose_non_wolf()

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
