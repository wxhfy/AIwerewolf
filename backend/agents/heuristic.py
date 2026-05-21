from __future__ import annotations

from collections import Counter
from random import Random

from backend.agents.base import Agent
from backend.agents.playbooks import build_role_brief
from backend.agents.profiles import ROLE_PROFILES
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
        if role == Role.WEREWOLF:
            target = self._choose_non_wolf()
            speech = (
                f"My strongest push today is {target['name']}. {target['name']} has been too comfortable shaping the table "
                f"without taking real risk. My second watch point is {suspects}. I want the vote to stay on a concrete civilian-looking slot."
            )
            reasoning = f"{profile.table_goal} {profile.wolf_disguise_style}"
        elif role == Role.SEER:
            checks = self._seer_checks()
            if checks:
                latest = checks[-1]
                result = "wolf" if latest["is_wolf"] else "not wolf"
                target_name = self._name(latest["target_id"])
                if latest["is_wolf"]:
                    speech = (
                        f"I am claiming Seer. Last night I checked {target_name} and the result is wolf. "
                        f"My vote is locked there unless someone can overturn the check with a stronger chain."
                    )
                else:
                    speech = (
                        f"I am reading the board from a Seer perspective. {target_name} checked as not wolf, "
                        f"so I want pressure on {suspects} instead. Everyone should now state a clear vote path."
                    )
                reasoning = profile.table_goal
            else:
                speech = (
                    f"I want every seat to give one hard suspect and one backup suspect. Right now I dislike {suspects} "
                    f"because the pressure they create is broad but not accountable."
                )
                reasoning = profile.speech_style
        elif role == Role.WITCH:
            speech = (
                f"I am not accepting lazy consensus today. {primary['name']} is my first suspect and "
                f"{secondary['name'] if secondary else primary['name']} is second, because I care more about who is steering votes than who is merely quiet."
            )
            reasoning = profile.table_goal
        elif role == Role.HUNTER:
            speech = (
                f"Do not rush a blind pile-on. If this table wants to execute, I want it on {primary['name']}. "
                f"If that flips wrong, I will remember exactly who protected {secondary['name'] if secondary else primary['name']}."
            )
            reasoning = profile.pressure_style
        elif role == Role.GUARD:
            speech = (
                f"The clean path is to compare who opened pressure and who only arrived after it was safe. "
                f"Right now {primary['name']} and {secondary['name'] if secondary else primary['name']} form the dirtiest pair for me."
            )
            reasoning = profile.table_goal
        else:
            speech = (
                f"I do not want a soft day. My vote preference is {primary['name']} first, "
                f"{secondary['name'] if secondary else primary['name']} second. Anyone opposing that should explain a cleaner wolf line."
            )
            reasoning = profile.speech_style
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
