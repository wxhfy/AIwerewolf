from __future__ import annotations

from collections import Counter
from random import Random

from backend.agents.base import Agent
from backend.engine.models import ActionType, Decision, Role
from backend.engine.visibility import PlayerView


class HeuristicAgent(Agent):
    """Deterministic baseline agent with role-specific behavior.

    This agent is intentionally simple and offline. LLM agents can later reuse
    the same lifecycle and return the same Decision objects.
    """

    def __init__(self, player_id: str, *, seed: int | None = None):
        self.player_id = player_id
        self.view: PlayerView | None = None
        self.memory: list[str] = []
        self.rng = Random(seed)
        self.winner: str | None = None

    def initialize(self, view: PlayerView, game_setting: dict) -> None:
        self.view = view
        self.memory.append(f"Initialized as {self.role.value}.")

    def update(self, view: PlayerView, request: str) -> None:
        self.view = view
        self.memory.append(f"{request} at day {view.day} phase {view.phase}.")

    def day_start(self) -> None:
        self.memory.append("Day started.")

    def talk(self) -> Decision:
        view = self._view()
        role = self.role
        if role == Role.WEREWOLF:
            target = self._choose_non_wolf()
            speech = f"I think {target['name']} is steering attention too neatly. We should pressure that seat today."
            reasoning = "As wolf, redirect suspicion toward a non-wolf while sounding analytical."
        elif role == Role.SEER:
            checks = self._seer_checks()
            if checks:
                latest = checks[-1]
                result = "wolf" if latest["is_wolf"] else "not wolf"
                target_name = self._name(latest["target_id"])
                speech = f"My read is based on night information: {target_name} checked as {result}."
                reasoning = "Share seer information to help village converge."
            else:
                speech = "I want claims and vote reasons kept concrete; wolves benefit from vague pressure."
                reasoning = "No check result yet, so push for accountable discussion."
        elif role == Role.WITCH:
            speech = "I am tracking who pushes easy votes. Today I prefer voting from evidence, not silence alone."
            reasoning = "Witch should protect key village roles and avoid exposing potions too early."
        elif role == Role.HUNTER:
            speech = "Do not force a fast pile-on. If I am pressured, I will still leave a clear suspect list."
            reasoning = "Hunter can deter opportunistic votes."
        elif role == Role.GUARD:
            speech = "The cleanest path is comparing vote logic across seats, especially sudden switches."
            reasoning = "Guard should avoid exposing protection choices."
        else:
            speech = "I am looking for contradictions between speeches and votes. Quiet consensus is dangerous."
            reasoning = "Villager contributes public pressure without private information."
        return Decision(view.player_id, ActionType.TALK, speech=speech, reasoning=reasoning)

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
