from __future__ import annotations

from collections import Counter
from random import Random

from backend.agents.base import Agent
from backend.agents.characters import Character
from backend.agents.playbooks import build_role_brief
from backend.agents.profiles import ROLE_PROFILES
from backend.engine.models import ActionType, Decision, Role
from backend.engine.visibility import PlayerView


class HeuristicAgent(Agent):
    """Deterministic baseline agent with role-specific + character-driven behavior.

    Uses character personality (from wolfcha-inspired Persona system) to produce
    diverse, human-like speech patterns across different games.
    """

    def __init__(self, player_id: str, *, seed: int | None = None, character: Character | None = None):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.memory: list[str] = []
        self.rng = Random(seed)
        self.winner: str | None = None
        self.character = character

    def initialize(self, view: PlayerView, game_setting: dict) -> None:
        self.view = view
        char_name = self.character.persona.name if self.character else "Unknown"
        self.memory.append(f"我是{char_name}，角色是{self.role.value}。")
        self.memory.append(build_role_brief(self.role))

    def update(self, view: PlayerView, request: str) -> None:
        self.view = view
        self.memory.append(f"{request} at day {view.day} phase {view.phase}.")
        if view.public_events:
            last_event = view.public_events[-1]
            self.memory.append(f"Observed {last_event['type']} at {last_event['phase']}.")

    def day_start(self) -> None:
        self.memory.append("Day started.")

    def talk(self) -> Decision:
        view = self._view()
        role = self.role
        primary = self._most_suspicious_alive()
        secondary = self._secondary_suspect(primary["id"])
        suspects = self._suspect_names(primary["id"], secondary["id"] if secondary else None)
        profile = ROLE_PROFILES[role]

        # Build base speech from role strategy + character personality
        char = self.character
        style = char.persona.style_label if char else "neutral"
        name = char.persona.name if char else "Player"

        speech, reasoning = self._build_character_speech(
            role=role, style=style, name=name,
            primary=primary, secondary=secondary, suspects=suspects,
            profile=profile,
        )
        return Decision(view.player_id, ActionType.TALK, speech=speech, reasoning=reasoning)

    def _build_character_speech(self, *, role, style, name, primary, secondary, suspects, profile):
        """Build role-appropriate speech with character personality flavor."""
        primary_name = primary["name"]
        secondary_name = secondary["name"] if secondary else primary_name

        # Role-specific core content + character-style wrapper
        if role == Role.WEREWOLF:
            content = self._wolf_speech(primary_name, secondary_name, suspects, style, name, profile)
        elif role == Role.SEER:
            content = self._seer_speech(primary_name, secondary_name, suspects, style, name, profile)
        elif role == Role.WITCH:
            content = self._witch_speech(primary_name, secondary_name, suspects, style, name, profile)
        elif role == Role.HUNTER:
            content = self._hunter_speech(primary_name, secondary_name, suspects, style, name, profile)
        elif role == Role.GUARD:
            content = self._guard_speech(primary_name, secondary_name, suspects, style, name, profile)
        else:
            content = self._villager_speech(primary_name, secondary_name, suspects, style, name, profile)
        return content

    # ---- Character-style speech generators ----

    def _wolf_speech(self, p, s, suspects, style, name, profile):
        templates = {
            "analytical": (f"我仔细看了一圈，{p}的逻辑有结构性矛盾。第一天说A可疑，第二天又跟票A，这不是好人的思维。{s}也得解释。", f"{name}伪装成逻辑分析者"),
            "aggressive": (f"我就直说了——{p}就是狼！走路姿势都是狼！你们不敢点我来点。还有个{s}，也别想跑。", f"{name}装成冲动的平民"),
            "expressive": (f"天哪你们看不出来吗？{p}那个发言，那个眼神（虽然我看不到），但那个心虚的感觉扑面而来！{s}也是。", f"{name}用表演煽动情绪"),
            "insightful": (f"我觉得{p}的潜意识在暴露自己。真正的好人不会这样构建怀疑链。{s}配合得很微妙。", f"{name}用心理分析来误导"),
            "observant": (f"盯了{p}一整天了。不对劲。{s}也不对劲。信我。", f"{name}装成沉默的观察者"),
            "meticulous": (f"我对了一下{p}第1天和第2天发言的时间线，有三处不一致。{s}有一处。结论很简单。", f"{name}制造伪证据链"),
            "provocative": (f"笑死，{p}的发言我都能背下来了——'我觉得'、'可能'、'不确定'。哥们你是玩狼人杀还是来相亲的？{s}也来相亲？", f"{name}用幽默掩盖引导"),
            "persuasive": (f"大家冷静听我说，{p}确实让我有点担心，不是他说的内容有问题，是他为什么要那样说？{s}也是。我们来一起分析一下。", f"{name}假装和事佬来带节奏"),
        }
        speech, reasoning = templates.get(style, templates["analytical"])
        return speech.replace("{p}", p).replace("{s}", s) if "{p}" in speech else speech, reasoning

    def _seer_speech(self, p, s, suspects, style, name, profile):
        checks = self._seer_checks()
        if checks:
            latest = checks[-1]
            target_name = self._name(latest["target_id"])
            if latest["is_wolf"]:
                speech = f"我是预言家。昨晚验了{target_name}，查杀。归票{target_name}，不接受分票。有对跳的现在出来。"
                reasoning = f"{name}强势归票查杀位"
            else:
                speech = f"我是预言家视角。{target_name}是我金水，好人。重点看{suspects}。尤其{s}，你的站边需要解释。"
                reasoning = f"{name}报金水同时归可疑位"
        else:
            speech = f"我还没跳身份但我想说——{suspects}这对组合不干净。{p}先动的手，{s}跟得很默契。各自解释。"
            reasoning = f"{name}以村民角度分析怀疑链"
        return speech, reasoning

    def _witch_speech(self, p, s, suspects, style, name, profile):
        templates = {
            "calm": (f"今晚的死亡信息很关键。{p}和{s}，我需要你们各说清楚为什么要这么投。不着急，我们有时间。", f"{name}冷静分析票型"),
            "aggressive": (f"别跟我绕！{p}你昨晚保的人跟你今天的发言对不上！{s}你也是！", f"{name}强势质问"),
            "default": (f"我不接受模糊票。{p}是我第一嫌疑人，{s}第二。不要跟我说'感觉'，给我逻辑。", f"{name}谨慎分析死亡信息"),
        }
        speech, reasoning = templates.get(style, templates["default"])
        return speech, reasoning

    def _hunter_speech(self, p, s, suspects, style, name, profile):
        speech = f"听好了——我活着的时候你们不归票{p}，等我死了可别怪枪口不长眼。{s}也在我名单上。"
        reasoning = f"{name}用猎人威慑逼票"
        return speech, reasoning

    def _guard_speech(self, p, s, suspects, style, name, profile):
        speech = f"我特别关注谁在利用信息差带节奏。{p}你推进的方向跟我看到的完全不一样。{s}，别不说话。"
        reasoning = f"{name}分析信息差制造者"
        return speech, reasoning

    def _villager_speech(self, p, s, suspects, style, name, profile):
        templates = {
            "analytical": (f"从概率上讲，{suspects}里面有至少一狼。我赌{p}。愿意站我的，说一下理由。", f"{name}用朴素逻辑分析"),
            "aggressive": (f"我就认{p}是狼！你们投不投？不投给我理由！", f"{name}直接冲锋"),
            "expressive": (f"我真的觉得{p}太可疑了！那个发言就是狼队剧本！{s}还帮他圆，更可疑！", f"{name}凭直觉和氛围"),
            "insightful": (f"你有没有觉得{p}的语气变了？第一天他在试探，今天他在引导。{s}是配合的。", f"{name}从心理角度分析"),
            "observant": (f"看{p}。就{p}。理由我整理好了——看票型。", f"{name}少说话但票准"),
            "meticulous": (f"我统计了{p}三轮发言的关键词——'可能'用了7次，'感觉'用了5次。结论：不敢明确表态。", f"{name}细节式推进"),
            "provocative": (f"{p}老师，您的狼人杀水平我是认可的，但您今天的演技我只能给3分。{s}给4分，还有进步空间。", f"{name}用幽默推动归票"),
            "persuasive": (f"我不是针对{p}这个人，我是说他这轮的逻辑确实有问题。大家觉得呢？我们可以一起看。如果他解释清楚了我就换人。", f"{name}温和引导共识"),
        }
        speech, reasoning = templates.get(style, templates["analytical"])
        return speech, reasoning

    def vote(self) -> Decision:
        view = self._view()
        if self.role == Role.WEREWOLF:
            target = self._choose_non_wolf()
            reasoning = "Vote a village-aligned player while avoiding visible wolf coordination."
        else:
            checked_wolf = self._latest_checked_wolf()
            target = checked_wolf or self._most_suspicious_alive()
            reasoning = "Vote the strongest suspect based on private info and public pressure."
        return Decision(view.player_id, ActionType.VOTE, target_id=target["id"], reasoning=reasoning)

    def attack(self) -> Decision:
        view = self._view()
        target = self._choose_priority_village()
        return Decision(
            view.player_id,
            ActionType.ATTACK,
            target_id=target["id"],
            reasoning="Wolves prioritize roles that can reveal or block night actions.",
        )

    def divine(self) -> Decision:
        view = self._view()
        candidates = self._alive_others()
        unchecked = [player for player in candidates if player["id"] not in {check["target_id"] for check in self._seer_checks()}]
        target = self._prefer_non_self(unchecked or candidates)
        return Decision(
            view.player_id,
            ActionType.DIVINE,
            target_id=target["id"],
            reasoning="Check an unverified player who can clarify the vote pool.",
        )

    def guard(self) -> Decision:
        view = self._view()
        candidates = self._alive_others(include_self=True)
        seerish = self._find_public_claim("seer")
        target = seerish or self._prefer_role_name(candidates, ["Seer", "Witch", "Hunter"]) or self._prefer_non_self(candidates)
        return Decision(
            view.player_id,
            ActionType.GUARD,
            target_id=target["id"],
            reasoning="Guard a likely high-value village target.",
        )

    def witch_act(self, victim_id: str | None) -> list[Decision]:
        view = self._view()
        decisions: list[Decision] = []
        if victim_id and view.day <= 1:
            decisions.append(
                Decision(
                    view.player_id,
                    ActionType.WITCH_SAVE,
                    target_id=victim_id,
                    reasoning="Use the heal early to preserve village numbers in the MVP rules.",
                )
            )
        poison_target = self._latest_checked_wolf()
        if poison_target:
            decisions.append(
                Decision(
                    view.player_id,
                    ActionType.WITCH_POISON,
                    target_id=poison_target["id"],
                    reasoning="Poison a privately confirmed wolf when available.",
                )
            )
        if not decisions:
            decisions.append(Decision(view.player_id, ActionType.SKIP, reasoning="Hold potions until stronger evidence appears."))
        return decisions

    def shoot(self) -> Decision:
        view = self._view()
        target = self._most_suspicious_alive()
        return Decision(
            view.player_id,
            ActionType.SHOOT,
            target_id=target["id"],
            reasoning="Hunter shoots the strongest remaining suspect.",
        )

    def finish(self, winner: str | None) -> None:
        self.winner = winner

    @property
    def role(self) -> Role:
        return Role(self._view().self_player["role"])

    def _view(self) -> PlayerView:
        if self.view is None:
            raise RuntimeError("Agent has not been initialized.")
        return self.view

    def _alive_others(self, *, include_self: bool = False) -> list[dict]:
        view = self._view()
        return [
            player
            for player in view.players
            if player["alive"] and (include_self or player["id"] != view.player_id)
        ]

    def _prefer_non_self(self, players: list[dict]) -> dict:
        if not players:
            raise RuntimeError("No legal targets.")
        return sorted(players, key=lambda player: (player["seat"], player["id"]))[0]

    def _choose_non_wolf(self) -> dict:
        view = self._view()
        wolf_ids = {player["id"] for player in view.known_wolves}
        candidates = [player for player in self._alive_others() if player["id"] not in wolf_ids]
        return self._prefer_non_self(candidates)

    def _choose_priority_village(self) -> dict:
        candidates = self._alive_others()
        known_roles = ["Seer", "Witch", "Guard", "Hunter"]
        target = self._prefer_role_name(candidates, known_roles)
        return target or self._choose_non_wolf()

    def _prefer_role_name(self, candidates: list[dict], roles: list[str]) -> dict | None:
        for role in roles:
            for player in candidates:
                if player.get("role") == role:
                    return player
        return None

    def _seer_checks(self) -> list[dict]:
        checks = []
        for event in self._view().private_events:
            payload = event["payload"]
            if payload.get("kind") == "seer_result":
                checks.append(payload)
        return checks

    def _latest_checked_wolf(self) -> dict | None:
        for check in reversed(self._seer_checks()):
            if check.get("is_wolf"):
                player = self._player(check["target_id"])
                if player and player["alive"]:
                    return player
        return None

    def _most_suspicious_alive(self) -> dict:
        candidates = self._alive_others()
        if not candidates:
            raise RuntimeError("No vote target available.")
        accusations = Counter()
        for event in self._view().public_events:
            if event["type"] == "CHAT_MESSAGE":
                content = str(event["payload"].get("speech", "")).lower()
                for player in candidates:
                    if player["name"].lower() in content:
                        accusations[player["id"]] += 1
        if accusations:
            best_id, _ = accusations.most_common(1)[0]
            player = self._player(best_id)
            if player:
                return player
        return self._prefer_non_self(candidates)

    def _secondary_suspect(self, exclude_id: str) -> dict | None:
        candidates = [player for player in self._alive_others() if player["id"] != exclude_id]
        if not candidates:
            return None
        accusations = Counter()
        for event in self._view().public_events:
            if event["type"] != "CHAT_MESSAGE":
                continue
            content = str(event["payload"].get("speech", "")).lower()
            for player in candidates:
                if player["name"].lower() in content:
                    accusations[player["id"]] += 1
        if accusations:
            best_id, _ = accusations.most_common(1)[0]
            return self._player(best_id)
        return self._prefer_non_self(candidates)

    def _suspect_names(self, primary_id: str, secondary_id: str | None) -> str:
        primary = self._name(primary_id)
        if secondary_id is None:
            return primary
        return f"{primary} and {self._name(secondary_id)}"

    def _find_public_claim(self, word: str) -> dict | None:
        for event in reversed(self._view().public_events):
            if event["type"] == "CHAT_MESSAGE" and word in str(event["payload"].get("speech", "")).lower():
                player = self._player(event["payload"].get("actor_id"))
                if player and player["alive"]:
                    return player
        return None

    def _player(self, player_id: str | None) -> dict | None:
        if player_id is None:
            return None
        return next((player for player in self._view().players if player["id"] == player_id), None)

    def _name(self, player_id: str) -> str:
        player = self._player(player_id)
        return player["name"] if player else player_id
