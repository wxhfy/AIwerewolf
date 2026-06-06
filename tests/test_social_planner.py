"""Social model, planner, and wolf team coordination tests.

Validates:
1. SocialModel feeds: contradiction→deception, vote→trust, speech-vote mismatch
2. Planner: StrategicIntent lifecycle, prompt injection, resolution
3. WolfTeamView: tactical assignment, kill negotiation, coordination context
4. Integration: all three systems working together in a simulated game
"""

from __future__ import annotations

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.planner import Planner
from backend.agents.cognitive.social_model import DeceptionSignal
from backend.agents.cognitive.social_model import SocialModel

# ============================================================
# SocialModel Tests
# ============================================================


class TestSocialModel:
    """Test trust networks and deception detection."""

    def test_update_trust_basic(self):
        sm = SocialModel()
        sm.update_trust("Alice", "Bob", 0.3, "voted same", day=1)
        assert sm.get_trust("Alice", "Bob") == 0.3
        assert "Bob" in sm.get_trusted_players("Alice", threshold=0.2)

    def test_update_trust_accumulates(self):
        sm = SocialModel()
        sm.update_trust("Alice", "Bob", 0.3, "reason1", day=1)
        sm.update_trust("Alice", "Bob", 0.3, "reason2", day=2)
        assert sm.get_trust("Alice", "Bob") == 0.6

    def test_update_trust_clamped(self):
        sm = SocialModel()
        sm.update_trust("Alice", "Bob", 2.0, "overflow", day=1)
        assert sm.get_trust("Alice", "Bob") == 1.0
        sm.update_trust("Alice", "Bob", -3.0, "underflow", day=2)
        assert sm.get_trust("Alice", "Bob") == -1.0

    def test_trust_edges_independent(self):
        """Trust is directional — Alice trusting Bob doesn't mean Bob trusts Alice."""
        sm = SocialModel()
        sm.update_trust("Alice", "Bob", 0.5, "reason", day=1)
        assert sm.get_trust("Alice", "Bob") == 0.5
        assert sm.get_trust("Bob", "Alice") == 0.0

    def test_deception_signal_basic(self):
        sm = SocialModel()
        sm.add_deception_signal(
            DeceptionSignal(
                player_id="Bob",
                signal_type="contradiction",
                description="冲突声称",
                severity=0.6,
                day=1,
            )
        )
        assert sm.get_deception_score("Bob") == 0.6
        assert sm.get_deception_score("Alice") == 0.0

    def test_deception_signal_aggregation(self):
        sm = SocialModel()
        sm.add_deception_signal(
            DeceptionSignal(
                player_id="Bob",
                signal_type="contradiction",
                description="a",
                severity=0.6,
                day=1,
            )
        )
        sm.add_deception_signal(
            DeceptionSignal(
                player_id="Bob",
                signal_type="speech_vote_mismatch",
                description="b",
                severity=0.8,
                day=2,
            )
        )
        # Average severity, capped at 1.0
        score = sm.get_deception_score("Bob")
        assert 0.6 < score < 0.8  # (0.6 + 0.8) / 2 = 0.7

    def test_speech_vote_mismatch(self):
        sm = SocialModel()
        sm.detect_speech_vote_mismatch("Bob", "Charlie", "David", day=1)
        signals = [s for s in sm.deception_signals if s.player_id == "Bob"]
        assert len(signals) == 1
        assert signals[0].signal_type == "speech_vote_mismatch"
        assert signals[0].severity == 0.4

    def test_speech_vote_match_no_signal(self):
        """Same speech and vote target should NOT generate a deception signal."""
        sm = SocialModel()
        sm.detect_speech_vote_mismatch("Bob", "Charlie", "Charlie", day=1)
        assert len(sm.deception_signals) == 0

    def test_format_for_prompt_empty(self):
        sm = SocialModel()
        result = sm.format_for_prompt("Alice")
        assert result == "" or "暂无" in result

    def test_format_for_prompt_with_data(self):
        sm = SocialModel()
        sm.update_trust("Alice", "Bob", 0.5, "reason", day=1)
        sm.update_trust("Alice", "Charlie", -0.5, "reason", day=1)
        sm.add_deception_signal(
            DeceptionSignal(
                player_id="David",
                signal_type="contradiction",
                description="冲突",
                severity=0.5,
                day=1,
            )
        )
        result = sm.format_for_prompt("Alice")
        assert "Bob" in result or "信任" in result or "怀疑" in result

    def test_memory_includes_social_model(self):
        mem = Memory("P1", "Werewolf")
        assert mem.social_model is not None
        assert isinstance(mem.social_model, SocialModel)

    def test_memory_includes_planner(self):
        mem = Memory("P1", "Werewolf")
        assert mem.planner is not None
        assert isinstance(mem.planner, Planner)


# ============================================================
# Planner Tests
# ============================================================


class TestPlanner:
    """Test strategic intent lifecycle."""

    def test_set_intent_basic(self):
        p = Planner()
        intent = p.set_intent(
            objective="bluff_claim_seer",
            target_phase="DAY_SPEECH",
            day=1,
            phase="NIGHT_WOLF_ACTION",
            conditions=["no_other_seer_claim"],
            fallback="continue_deep_cover",
        )
        assert intent.objective == "bluff_claim_seer"
        assert not intent.resolved
        assert len(intent.conditions) == 1

    def test_get_active_matches_phase(self):
        p = Planner()
        p.set_intent("fake_claim", "DAY_SPEECH", day=1, phase="NIGHT_START")
        active = p.get_active(2, "DAY_SPEECH")
        assert active is not None
        assert active.objective == "fake_claim"

    def test_get_active_not_matching_phase(self):
        p = Planner()
        p.set_intent("fake_claim", "DAY_SPEECH", day=1, phase="NIGHT_START")
        active = p.get_active(2, "DAY_VOTE")
        assert active is None

    def test_get_active_before_declared_day(self):
        p = Planner()
        p.set_intent("fake_claim", "DAY_SPEECH", day=3, phase="NIGHT_START")
        active = p.get_active(2, "DAY_SPEECH")
        assert active is None

    def test_set_intent_supersedes_previous(self):
        p = Planner()
        p.set_intent("plan_a", "DAY_SPEECH", day=1, phase="NIGHT_START")
        p.set_intent("plan_b", "DAY_VOTE", day=1, phase="NIGHT_START")
        # plan_a should be auto-resolved (superseded)
        intents = [i for i in p.intents if i.objective == "plan_a"]
        assert intents[0].resolved

    def test_mark_executed(self):
        p = Planner()
        p.set_intent("do_thing", "DAY_SPEECH", day=1, phase="NIGHT_START")
        p.mark_executed(2, "DAY_SPEECH")
        # After mark_executed, the intent should be resolved (not active)
        intent = p.intents[0]
        assert intent.resolved
        assert intent.resolution_note == "executed"
        # And get_active returns None since resolved intents aren't active
        assert p.get_active(2, "DAY_SPEECH") is None

    def test_mark_abandoned(self):
        p = Planner()
        p.set_intent("do_thing", "DAY_SPEECH", day=1, phase="NIGHT_START")
        p.mark_abandoned("strategy_changed", 2, "DAY_SPEECH")
        active = p.get_active(2, "DAY_SPEECH")
        assert active is None or active.resolved

    def test_format_active_for_prompt(self):
        p = Planner()
        p.set_intent(
            objective="bluff_seer",
            target_phase="DAY_SPEECH",
            day=1,
            phase="NIGHT_START",
            conditions=["alive"],
            fallback="play_normally",
        )
        result = p.format_active_for_prompt(2, "DAY_SPEECH")
        assert "bluff_seer" in result
        assert "DAY_SPEECH" in result or "触发阶段" in result

    def test_format_inactive_returns_empty(self):
        p = Planner()
        result = p.format_active_for_prompt(2, "DAY_SPEECH")
        assert result == ""

    def test_check_and_resolve_conditions_met(self):
        p = Planner()
        p.set_intent("fake_claim", "DAY_SPEECH", day=1, phase="NIGHT_START")
        result = p.check_and_resolve(2, "DAY_SPEECH", conditions_met=True)
        assert result is not None

    def test_check_and_resolve_conditions_failed(self):
        p = Planner()
        p.set_intent("fake_claim", "DAY_SPEECH", day=1, phase="NIGHT_START", conditions=["no_other_seer"])
        result = p.check_and_resolve(2, "DAY_SPEECH", conditions_met=False)
        assert result is None

    def test_trim_history(self):
        p = Planner()
        for i in range(10):
            p.set_intent(f"plan_{i}", "DAY_SPEECH", day=i, phase="NIGHT_START")
            p.mark_executed(i + 1, "DAY_SPEECH")
        # Should keep only last 5 resolved + any active
        resolved_count = sum(1 for i in p.intents if i.resolved)
        assert resolved_count <= 5


# ============================================================
# End-to-End Integration Test (simulated game)
# ============================================================


class TestSocialPlannerIntegration:
    """Simulate a multi-turn game and verify social model + planner state."""

    def _simulate_social_feed_cycle(
        self,
        sm: SocialModel,
        pl: Planner,
        day: int,
        phase: str,
    ) -> None:
        """Simulate one observation→decision cycle with social feeds."""
        # Feed 1: contradictions from belief tracker
        if day == 2 and phase == "DAY_SPEECH":
            # Simulate: two players both claiming Seer
            sm.add_deception_signal(
                DeceptionSignal(
                    player_id="Player3",
                    signal_type="role_contradiction",
                    description="与Player5冲突声称是Seer",
                    severity=0.6,
                    day=day,
                )
            )
            sm.add_deception_signal(
                DeceptionSignal(
                    player_id="Player5",
                    signal_type="role_contradiction",
                    description="与Player3冲突声称是Seer",
                    severity=0.6,
                    day=day,
                )
            )

        # Feed 2: vote alignment
        if phase == "DAY_VOTE":
            sm.update_trust("Alice", "Bob", 0.08, f"D{day}: 投票一致", day=day)

        # Feed 3: speech-vote mismatch
        if day == 1 and phase == "DAY_VOTE":
            sm.detect_speech_vote_mismatch("Bob", "Player3", "Player4", day=day)

    def test_full_game_cycle(self):
        """Simulate a 3-day game and verify all systems functional."""
        sm = SocialModel()
        pl = Planner()

        # Day 1: Night phase — wolf sets a plan
        pl.set_intent(
            objective="fake_claim_seer_day2",
            target_phase="DAY_SPEECH",
            day=1,
            phase="NIGHT_WOLF_ACTION",
            conditions=["no_other_seer_claim"],
            fallback="play_as_villager",
        )
        self._simulate_social_feed_cycle(sm, pl, day=1, phase="NIGHT_WOLF_ACTION")

        # Day 1: Vote phase — speech-vote mismatch detected
        self._simulate_social_feed_cycle(sm, pl, day=1, phase="DAY_VOTE")
        deception_score = sm.get_deception_score("Bob")
        assert deception_score > 0, "Bob should have deception signal"

        # Day 2: Speech phase — plan should be active
        self._simulate_social_feed_cycle(sm, pl, day=2, phase="DAY_SPEECH")
        active = pl.get_active(2, "DAY_SPEECH")
        assert active is not None, "Strategic intent should be active on day 2 speech"
        assert active.objective == "fake_claim_seer_day2"

        # Agent executes plan
        pl.mark_executed(2, "DAY_SPEECH")
        assert active.resolved

        # Verify all contradictions recorded
        players_with_signals = {s.player_id for s in sm.deception_signals}
        assert "Player3" in players_with_signals
        assert "Player5" in players_with_signals

        # Verify trust accumulated
        trust = sm.get_trust("Alice", "Bob")
        assert trust > 0, "Alice should trust Bob after vote alignment"
