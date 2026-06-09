"""Tests for the humanization layer: personality profiles, multi-segment speech,
probabilistic voting, stance tracking, and 10-player game initialization."""

from __future__ import annotations

from backend.agents.characters import Character
from backend.agents.characters import Persona
from backend.agents.characters import PlayerMind
from backend.agents.heuristic import HeuristicAgent
from backend.agents.humanization import build_humanization_profile
from backend.agents.humanization import build_stance_summary
from backend.engine.game import WerewolfGame
from backend.engine.models import Player
from backend.engine.models import Role
from backend.engine.visibility import Visibility


def _bold_character() -> Character:
    return Character(
        persona=Persona(
            mbti="ESTP",
            gender="male",
            age=32,
            name="TestBold",
            basic_info="test",
            style_label="aggressive",
        ),
        mind=PlayerMind(
            courage="bold",
            memory_bias="first_impression",
            suspicion_threshold="low",
            self_protection="aggressive",
            logic_depth="shallow",
            table_presence="dominant",
        ),
    )


def _cautious_character() -> Character:
    return Character(
        persona=Persona(
            mbti="ISFJ",
            gender="female",
            age=25,
            name="TestCautious",
            basic_info="test",
            style_label="observant",
        ),
        mind=PlayerMind(
            courage="cautious",
            memory_bias="recent",
            suspicion_threshold="high",
            self_protection="sacrificial",
            logic_depth="moderate",
            table_presence="quiet",
        ),
    )


def _heuristic_agent_for(game: WerewolfGame, player: Player) -> HeuristicAgent:
    agent = HeuristicAgent(
        player.id,
        seed=player.seat,
        character=game.characters.get(player.id),
    )
    view = Visibility().for_player(game.state, player.id)
    agent.initialize(view, {"game_id": game.state.id})
    return agent


class TestHumanizationProfile:
    def test_different_personas_produce_different_profiles(self) -> None:
        bold = build_humanization_profile(_bold_character())
        cautious = build_humanization_profile(_cautious_character())

        # Bold: lower vote temperature, higher grudge, lower self-protection
        assert bold.vote_temperature < cautious.vote_temperature
        assert bold.grudge_weight > cautious.grudge_weight
        assert bold.self_protection_weight < cautious.self_protection_weight
        # Bold/dominant: more speech segments
        assert bold.speech_max_segments >= cautious.speech_max_segments
        # Bold has higher risk appetite
        assert bold.risk_appetite == "high"
        assert cautious.risk_appetite == "low"

    def test_default_profile_when_no_character(self) -> None:
        profile = build_humanization_profile(None)
        assert profile.vote_temperature == 0.8
        assert profile.suspicion_gain == 1.0
        assert profile.speech_max_segments >= 2

    def test_first_impression_memory_is_stubborn(self) -> None:
        char = Character(
            persona=Persona(
                mbti="INTJ", gender="male", age=30, name="Stubborn", basic_info="test", style_label="analytical"
            ),
            mind=PlayerMind(
                courage="calculated",
                memory_bias="first_impression",
                suspicion_threshold="medium",
                self_protection="passive",
                logic_depth="deep",
                table_presence="balanced",
            ),
        )
        profile = build_humanization_profile(char)
        assert profile.stubbornness >= 1.0
        assert profile.recency_weight < 1.0


class TestHeuristicSegments:
    def test_talk_produces_segments(self) -> None:
        game = WerewolfGame(seed=3, player_count=7)
        game.initialize()
        villager = next(p for p in game.state.players if p.role == Role.VILLAGER)
        agent = _heuristic_agent_for(game, villager)
        decision = agent.talk()
        segments = decision.metadata.get("segments", [])
        assert isinstance(segments, list)
        assert len(segments) >= 1
        assert all(isinstance(s, str) and len(s) > 0 for s in segments)

    def test_segments_dont_exceed_personality_max(self) -> None:
        game = WerewolfGame(seed=3, player_count=7)
        game.initialize()
        villager = next(p for p in game.state.players if p.role == Role.VILLAGER)
        agent = _heuristic_agent_for(game, villager)
        hp = agent.human_profile
        decision = agent.talk()
        segments = decision.metadata.get("segments", [])
        assert len(segments) <= hp.speech_max_segments


class TestProbabilisticVoting:
    def test_vote_not_always_same_target(self) -> None:
        """With softmax sampling, votes should vary across runs."""
        game = WerewolfGame(seed=7, player_count=7)
        game.initialize()
        game.state.day = 2
        villager = next(p for p in game.state.players if p.role == Role.VILLAGER)
        agent = _heuristic_agent_for(game, villager)
        # Give all others a moderate suspicion so no single candidate dominates
        for p in game.state.players:
            if p.id != villager.id:
                agent.suspicion[p.id] = 1.0

        targets: set[str] = set()
        for _ in range(50):
            decision = agent.vote()
            targets.add(decision.target_id)

        # With softmax at moderate temperature, should hit at least 2 targets
        assert len(targets) >= 2, f"Only hit {len(targets)} targets across 50 votes"

    def test_day1_vote_scattering(self) -> None:
        """Day 1 with no info: votes should scatter across candidates."""
        game = WerewolfGame(seed=7, player_count=7)
        game.initialize()
        game.state.day = 1
        # Collect vote targets from all village players
        targets: dict[str, int] = {}
        for player in game.state.players:
            if player.role in (Role.VILLAGER, Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD):
                agent = _heuristic_agent_for(game, player)
                decision = agent.vote()
                targets[decision.target_id] = targets.get(decision.target_id, 0) + 1

        # At least 2 different targets should receive votes (scattered)
        assert len(targets) >= 2, f"All village votes went to {targets}"

    def test_known_wolf_always_voted(self) -> None:
        """When a seer finds a wolf, vote should always target that wolf."""
        game = WerewolfGame(seed=5, player_count=7)
        game.initialize()
        seer = next(p for p in game.state.players if p.role == Role.SEER)
        agent = _heuristic_agent_for(game, seer)
        # Mark a specific player as known wolf
        wolf = next(p for p in game.state.players if p.role == Role.WEREWOLF)
        agent.known_wolf_ids.add(wolf.id)
        agent.suspicion[wolf.id] = 10.0

        for _ in range(20):
            decision = agent.vote()
            assert decision.target_id == wolf.id


class Test10PlayerInit:
    def test_default_10_player_game(self) -> None:
        game = WerewolfGame(seed=7)
        assert len(game.state.players) == 10
        roles = [p.role for p in game.state.players]
        assert roles.count(Role.WEREWOLF) == 2
        assert roles.count(Role.WHITE_WOLF_KING) == 1
        assert roles.count(Role.SEER) == 1
        assert roles.count(Role.WITCH) == 1
        assert roles.count(Role.HUNTER) == 1
        assert roles.count(Role.GUARD) == 1
        assert roles.count(Role.VILLAGER) == 3

    def test_7_player_override(self) -> None:
        game = WerewolfGame(seed=7, player_count=7)
        assert len(game.state.players) == 7
        roles = [p.role for p in game.state.players]
        assert roles.count(Role.WEREWOLF) == 2
        assert roles.count(Role.VILLAGER) == 1


class TestPublicStance:
    def test_stance_summary_renders(self) -> None:
        stance = {
            "suspects": {"A": {"score": 2.5, "reason": "投票矛盾", "day": 2}},
            "trusted": {"B": {"score": 10.0, "reason": "已知好人", "day": 1}},
            "grudges": {"C": 0.5},
            "last_vote_target": "A",
            "tunnel_target": "A",
        }
        summary = build_stance_summary(stance, "self")
        assert "怀疑" in summary
        assert "信任" in summary
        assert "上一轮你投了" in summary
        assert "点过你的人" in summary

    def test_grudges_accumulate_when_mentioned(self) -> None:
        game = WerewolfGame(seed=7, player_count=7)
        game.initialize()
        villager = next(p for p in game.state.players if p.role == Role.VILLAGER)
        agent = _heuristic_agent_for(game, villager)

        assert agent.public_stance["grudges"] == {}
        # Simulate being mentioned by another player's speech
        other = next(p for p in game.state.players if p.id != villager.id)
        agent.view.public_events.append(
            {
                "type": "CHAT_MESSAGE",
                "payload": {
                    "actor_id": other.id,
                    "actor_name": other.name,
                    "speech": f"我怀疑{villager.name}有问题",
                },
            }
        )
        agent._update_suspicion_from_events()
        assert other.id in agent.public_stance["grudges"]


class TestEngineIntegration:
    def test_10_player_game_runs_to_completion(self) -> None:
        game = WerewolfGame(seed=7)
        state = game.play()
        assert state.winner is not None
        assert state.phase.value == "GAME_END"
        assert len(state.players) == 10
        # Verify segments in chat messages
        chat_events = [e for e in state.events if e.type.value == "CHAT_MESSAGE"]
        assert chat_events
        # At least some events should have segment info in metadata
        assert any(e.payload.get("segment_index") is not None for e in chat_events)
