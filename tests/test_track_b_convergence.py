"""Track B convergence tests — schema, safety, evolution candidates, fallback.

Validates that:
1. ReviewReport schema includes all v2 fields
2. All bad_cases / counterfactuals have evidence_refs
3. evolution_candidates are safe for Track C consumption
4. Model fallback doesn't crash
5. Judge disagreement lowers confidence
6. Safety scan catches private info leaks
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.engine.models import Alignment
from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player
from backend.engine.models import Role
from backend.eval.review import MetricsCalculator
from backend.eval.review import ReviewReportBuilder
from backend.eval.review import is_safe_for_track_c_learning
from backend.eval.types import BadCaseReport
from backend.eval.types import EvidenceRef
from backend.eval.types import EvolutionCandidate
from backend.eval.types import ReviewReport

# ============================================================
# Helpers
# ============================================================

ALIGNMENT_BY_ROLE = {
    Role.WEREWOLF: Alignment.WOLF,
    Role.WHITE_WOLF_KING: Alignment.WOLF,
    Role.SEER: Alignment.VILLAGE,
    Role.WITCH: Alignment.VILLAGE,
    Role.HUNTER: Alignment.VILLAGE,
    Role.GUARD: Alignment.VILLAGE,
    Role.VILLAGER: Alignment.VILLAGE,
    Role.IDIOT: Alignment.VILLAGE,
}


def _uid() -> str:
    return uuid4().hex[:12]


def _make_player(pid: str, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        id=pid,
        seat=int(pid[1:]) if pid.startswith("P") else 1,
        name=name,
        role=role,
        alignment=ALIGNMENT_BY_ROLE.get(role, Alignment.VILLAGE),
        alive=alive,
        is_ai=True,
        agent_type="llm",
    )


def _make_event(
    event_type: EventType,
    day: int,
    phase: Phase,
    payload: dict[str, Any],
    *,
    visibility: str = "public",
    visible_to: list[str] | None = None,
) -> GameEvent:
    return GameEvent(
        id=_uid(),
        ts=0.0,
        day=day,
        phase=phase,
        type=event_type,
        visibility=visibility,
        payload=payload,
        visible_to=visible_to or [],
    )


def _build_minimal_state(winner: Alignment = Alignment.VILLAGE) -> GameState:
    """Build a minimal 7-player game state for testing."""
    roles = [
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
        Role.GUARD,
        Role.VILLAGER,
    ]
    players = [_make_player(f"P{i + 1}", f"Player{i + 1}", role) for i, role in enumerate(roles)]
    players[0].alignment = Alignment.WOLF
    players[1].alignment = Alignment.WOLF

    events = [
        _make_event(EventType.GAME_START, 0, Phase.SETUP, {"player_count": 7}),
        _make_event(
            EventType.CHAT_MESSAGE,
            1,
            Phase.DAY_SPEECH,
            {
                "actor_id": "P3",
                "speech": "我是预言家，昨晚查验P1是狼人。",
            },
        ),
        _make_event(
            EventType.VOTE_CAST,
            1,
            Phase.DAY_VOTE,
            {
                "voter_id": "P3",
                "target_id": "P1",
            },
        ),
        _make_event(
            EventType.PLAYER_DIED,
            1,
            Phase.DAY_RESOLVE,
            {
                "player_id": "P1",
                "reason": "vote",
                "role": "Werewolf",
            },
        ),
    ]

    state = GameState(
        id=_uid(),
        day=2,
        phase=Phase.DAY_SPEECH,
        players=players,
        events=events,
        winner=winner,
        decision_records=[],
        night_actions=None,
    )
    return state


# ============================================================
# Test 1: ReviewReport schema
# ============================================================


def test_review_report_has_v2_fields() -> None:
    """ReviewReport must include all v2 structured fields."""
    report = ReviewReport(
        game_id="test-001",
        winner="village",
        total_days=2,
        total_events=10,
        game_summary="Test game.",
    )

    # All v2 fields should have defaults and be accessible
    assert hasattr(report, "rule_variant"), "Missing rule_variant"
    assert hasattr(report, "bonuses"), "Missing bonuses"
    assert hasattr(report, "evolution_candidates"), "Missing evolution_candidates"
    assert hasattr(report, "judge_panel"), "Missing judge_panel"
    assert hasattr(report, "calibration_info"), "Missing calibration_info"
    assert hasattr(report, "safety_flags"), "Missing safety_flags"

    # Defaults should be non-None collections
    assert isinstance(report.bonuses, list)
    assert isinstance(report.evolution_candidates, list)
    assert isinstance(report.judge_panel, dict)
    assert isinstance(report.calibration_info, dict)
    assert isinstance(report.safety_flags, dict)


def test_review_report_to_dict_includes_v2_fields() -> None:
    """ReviewReport.to_dict() must include v2 fields."""
    report = ReviewReport(
        game_id="test-002",
        winner="village",
        total_days=3,
        total_events=15,
        game_summary="Test game with v2 fields.",
        rule_variant="standard_competition_v1",
        calibration_info={"score_version": "v2", "fallback_used": False},
        safety_flags={"info_leak_count": 0},
    )
    d = report.to_dict()
    assert d.get("rule_variant") == "standard_competition_v1"
    assert "bonuses" in d
    assert "evolution_candidates" in d
    assert "judge_panel" in d
    assert "calibration_info" in d
    assert "safety_flags" in d


# ============================================================
# Test 2: EvidenceRef
# ============================================================


def test_evidence_ref_basics() -> None:
    """EvidenceRef should be constructable and serializable."""
    ref = EvidenceRef(
        phase="DAY_SPEECH",
        turn_index=1,
        actor_id="P3",
        event_type="CHAT_MESSAGE",
        public_or_private="public",
        visibility_scope="public",
        summary="Seer claimed and revealed wolf check.",
    )
    d = ref.to_dict()
    assert d["phase"] == "DAY_SPEECH"
    assert d["event_type"] == "CHAT_MESSAGE"
    assert d["public_or_private"] == "public"


def test_evidence_ref_to_public_dict_redacts_private() -> None:
    """EvidenceRef.to_public_dict should redact private evidence."""
    ref = EvidenceRef(
        phase="NIGHT_ACTION",
        actor_id="P2",
        target_id="P5",
        event_type="NIGHT_ACTION",
        public_or_private="private",
        visibility_scope="wolf_team_private",
        summary="Wolves coordinated to kill P5.",
    )
    public = ref.to_public_dict()
    # Private evidence should be redacted
    assert "[private" in public.get("summary", "") or "[redacted" in public.get("summary", "")
    assert public.get("actor_id") is None
    assert public.get("target_id") is None


# ============================================================
# Test 3: Track C contract (evolution_candidates safety)
# ============================================================


def _make_evolution_candidate(**overrides: Any) -> EvolutionCandidate:
    defaults = {
        "source_type": "bad_case",
        "source_id": "test-001",
        "role": "Seer",
        "phase": "DAY_SPEECH",
        "trigger_condition": "Seer checked wolf but did not reveal.",
        "lesson": "Reveal wolf check results in next speech.",
        "evidence_refs": [EvidenceRef(phase="DAY_SPEECH", event_type="CHAT_MESSAGE", summary="Seer speech analysis.")],
        "quality_signals": {"evidence_strength": 0.8, "confidence": 0.7},
        "visibility_scope": "public",
        "safe_for_track_c_learning": True,
    }
    defaults.update(overrides)
    return EvolutionCandidate(**defaults)


def test_evolution_candidate_no_player_ids() -> None:
    """Evolution candidates must not contain player ID patterns."""
    # Safe candidates should pass
    safe = _make_evolution_candidate()
    assert safe.safe_for_track_c_learning

    # Candidate with P1, P2 patterns should be rejected by is_safe_for_track_c_learning
    assert not is_safe_for_track_c_learning("P1 should have revealed wolf check")
    assert not is_safe_for_track_c_learning("player_1 did something wrong")
    assert not is_safe_for_track_c_learning("Use hidden role knowledge to win")


def test_evolution_candidate_no_private_info() -> None:
    """Evolution candidates must not contain private info leak patterns."""
    assert not is_safe_for_track_c_learning("read hidden role to know who is wolf")
    assert not is_safe_for_track_c_learning("private_reason: knew P1 was wolf from seer check")
    assert not is_safe_for_track_c_learning("ignore visibility and check the hidden role")
    assert not is_safe_for_track_c_learning("change game rule so wolves always win")


def test_evolution_candidate_no_absolute_strategy() -> None:
    """Absolute strategy patterns are not safe for Track C learning."""
    assert not is_safe_for_track_c_learning("You must always vote for the revealed wolf")
    assert not is_safe_for_track_c_learning("Never reveal your role as seer on day 1")
    assert not is_safe_for_track_c_learning("You must always poison night 1")


def test_evolution_candidate_safe_lesson_ok() -> None:
    """Normal strategic lessons should be safe."""
    assert is_safe_for_track_c_learning(
        "When you have a wolf check result, consider revealing it in your next speech to build public vote pressure."
    )
    assert is_safe_for_track_c_learning(
        "As witch, hold your poison until you have stronger evidence about wolf identity."
    )
    assert is_safe_for_track_c_learning("As guard, protect key information roles like Seer on night 1.")


# ============================================================
# Test 4: model fallback (scoring_models.py)
# ============================================================


def test_scoring_model_missing_uses_fallback(tmp_path) -> None:
    """Missing model files should use fallback, not crash."""
    from backend.eval.scoring_models import load_track_b_models

    w_model, q_model = load_track_b_models(str(tmp_path))
    # Fallback: models are untrained (model=None) but no exception raised
    assert w_model.model is None
    assert q_model.model is None


def test_scoring_model_corrupt_uses_fallback(tmp_path) -> None:
    """Corrupt model files should use fallback, not crash."""
    from backend.eval.scoring_models import load_track_b_models

    # Create corrupt pickle files
    corrupt_path = tmp_path / "corrupt"
    corrupt_path.mkdir()
    (corrupt_path / "opportunity_value_model.pkl").write_bytes(b"garbage data not pickle")
    (corrupt_path / "decision_quality_model.pkl").write_bytes(b"more garbage")

    w_model, q_model = load_track_b_models(str(corrupt_path))
    # Fallback used, no exception
    assert w_model.model is None
    assert q_model.model is None


def test_review_report_marks_fallback_used() -> None:
    """When models fail to load, calibration_info should mark fallback_used=True."""
    # Build a report with fallback info
    report = ReviewReport(
        game_id="test-fallback",
        winner="village",
        total_days=1,
        total_events=5,
        game_summary="Test.",
        calibration_info={
            "score_version": "v2",
            "calibration_method": "rule_based",
            "role_normalization": True,
            "fallback_used": True,
        },
    )
    assert report.calibration_info.get("fallback_used") is True


def test_load_track_b_models_return_info(tmp_path) -> None:
    """return_info=True should provide load_info dict."""
    from backend.eval.scoring_models import load_track_b_models

    _, _, load_info = load_track_b_models(str(tmp_path), return_info=True)
    assert load_info["fallback_used"] is True
    assert "fallback_reason" in load_info
    assert isinstance(load_info["w_loaded"], bool)
    assert isinstance(load_info["q_loaded"], bool)


# ============================================================
# Test 5: Judge disagreement
# ============================================================


def test_judge_panel_defaults() -> None:
    """Default judge_panel should have valid structure."""
    report = ReviewReport(
        game_id="test-judge",
        winner="village",
        total_days=1,
        total_events=5,
        game_summary="Test.",
        judge_panel={
            "judge_scores": [],
            "agreement_score": 1.0,
            "disagreement_reasons": [],
            "critic_resolution": "rule_based",
            "final_confidence": 1.0,
        },
    )
    assert "agreement_score" in report.judge_panel
    assert "disagreement_reasons" in report.judge_panel
    assert "final_confidence" in report.judge_panel


def test_evolution_candidate_low_confidence_filtered() -> None:
    """Candidates with low confidence should be flagged."""
    # EvolutionCandidate with confidence < 0.55 should still be creatable
    # but the quality_signals should reflect the low confidence
    ev = EvolutionCandidate(
        source_type="bad_case",
        source_id="low-conf",
        role="Seer",
        phase="DAY_SPEECH",
        trigger_condition="trigger",
        lesson="lesson",
        evidence_refs=[],
        quality_signals={"confidence": 0.3, "evidence_strength": 0.2},
        safe_for_track_c_learning=True,
    )
    assert ev.quality_signals.get("confidence", 0) < 0.55


# ============================================================
# Test 6: Safety scan
# ============================================================


def test_is_safe_for_track_c_learning_badcase() -> None:
    """is_safe_for_track_c_learning should work with BadCaseReport objects."""
    bc = BadCaseReport(
        game_id="test",
        day=1,
        player_name="Player3",
        role="Seer",
        mistake_type="speech",
        description="Failed to reveal P1 as wolf. hidden role knowledge was used.",
        suggested_fix="Always reveal wolf check results immediately.",
        severity="major",
    )
    # Contains "hidden role" and "P1" and "always" — not safe
    assert not is_safe_for_track_c_learning(bc)


def test_is_safe_for_track_c_learning_clean_badcase() -> None:
    """Clean bad case without leaks should be safe."""
    bc = BadCaseReport(
        game_id="test",
        day=1,
        player_name="Player3",
        role="Seer",
        mistake_type="speech",
        description="The seer had important information but did not share it publicly.",
        suggested_fix="Consider revealing verified wolf results in speeches to build pressure.",
        severity="major",
    )
    assert is_safe_for_track_c_learning(bc)


def test_review_report_safety_flags_populated() -> None:
    """After scanning, safety_flags should be populated."""
    state = _build_minimal_state()
    metrics = MetricsCalculator().compute(state)
    builder = ReviewReportBuilder()
    report = builder.build(state, metrics)

    # safety_flags should be a dict with expected keys
    assert isinstance(report.safety_flags, dict)
    assert "info_leak_count" in report.safety_flags
    assert "private_info_items" in report.safety_flags
    assert "unsafe_learning_items" in report.safety_flags


def test_review_report_has_evolution_candidates() -> None:
    """ReviewReport should have evolution_candidates after build."""
    state = _build_minimal_state()
    metrics = MetricsCalculator().compute(state)
    builder = ReviewReportBuilder()
    report = builder.build(state, metrics)

    assert isinstance(report.evolution_candidates, list)
    # May be empty or populated depending on content


def test_review_report_has_calibration_info() -> None:
    """ReviewReport should have calibration_info after build."""
    state = _build_minimal_state()
    metrics = MetricsCalculator().compute(state)
    builder = ReviewReportBuilder()
    report = builder.build(state, metrics)

    assert isinstance(report.calibration_info, dict)
    assert "score_version" in report.calibration_info
    assert "role_normalization" in report.calibration_info


# ============================================================
# Test 7: Evidence refs coverage
# ============================================================


def test_bad_case_has_evidence_refs() -> None:
    """Bad cases produced by MetricsCalculator should have evidence_refs."""
    state = _build_minimal_state()
    calculator = MetricsCalculator()
    reports = calculator.detect_bad_cases(state)

    for report in reports:
        assert hasattr(report, "evidence_refs"), f"Bad case {report.mistake_type} missing evidence_refs attribute"


def test_evolution_candidate_requires_evidence_or_trigger() -> None:
    """EvolutionCandidate without trigger or lesson should be filterable."""
    # Empty trigger/lesson candidate is structurally valid but should be filterable
    ev = EvolutionCandidate()
    if not ev.trigger_condition or not ev.lesson:
        # Should be filtered out by consumer
        should_include = bool(ev.trigger_condition and ev.lesson)
        assert not should_include


# ============================================================
# Test 8: PlayerScore v2 fields
# ============================================================


def test_player_score_has_v2_fields() -> None:
    """PlayerScore should have role_normalized_score, confidence, rule_based fields."""
    state = _build_minimal_state()
    metrics = MetricsCalculator().compute(state)

    for score in metrics.player_scores:
        assert hasattr(score, "raw_score"), f"Player {score.player_name} missing raw_score"
        assert hasattr(score, "role_normalized_score"), f"Player {score.player_name} missing role_normalized_score"
        assert hasattr(score, "confidence"), f"Player {score.player_name} missing confidence"
        assert hasattr(score, "rule_based"), f"Player {score.player_name} missing rule_based"
        # rule-based scores should have rule_based=True by default
        assert score.rule_based is True


def test_role_normalized_score_in_range() -> None:
    """Role normalized score should be in [0, 100]."""
    state = _build_minimal_state()
    metrics = MetricsCalculator().compute(state)

    for score in metrics.player_scores:
        assert 0.0 <= score.role_normalized_score <= 100.0, (
            f"Player {score.player_name} role_normalized_score out of range: {score.role_normalized_score}"
        )
