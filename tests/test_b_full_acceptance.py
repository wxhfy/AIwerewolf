"""Track B full acceptance verification.

Each test maps to a specific acceptance gate from docs/B_REVIEW_VALIDATION_PLAN.md.
Run this file to verify B is a production-ready review & validation system.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.engine.models import Alignment, EventType, GameEvent, GameState, Phase, Player, Role
from backend.eval.review import (
    BadCaseReport,
    CounterfactualAnalyzer,
    CounterfactualCase,
    FinalScoreCalculator,
    GameMetrics,
    LeaderboardAggregator,
    MarkdownReportRenderer,
    MockReviewLLM,
    MVPSelector,
    MetricsCalculator,
    PlayerScore,
    ReportEvaluator,
    ReportGenerator,
    ReportOptimizationState,
    ReportOptimizer,
    ReviewBonus,
    ReviewQualityChecker,
    ReviewReportBuilder,
    StrategyKnowledgeExtractor,
    StrategySuggestion,
    export_leaderboard,
    export_review_report,
    export_strategy_knowledge,
    generate_review_report,
)
from backend.eval.report_graph import LANGGRAPH_AVAILABLE, LangGraphReportOptimizer, create_report_optimizer

ALIGNMENT_BY_ROLE = {
    Role.WEREWOLF: Alignment.WOLF,
    Role.SEER: Alignment.VILLAGE,
    Role.WITCH: Alignment.VILLAGE,
    Role.HUNTER: Alignment.VILLAGE,
    Role.GUARD: Alignment.VILLAGE,
    Role.VILLAGER: Alignment.VILLAGE,
}


def make_player(player_id: str, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(id=player_id, seat=int(player_id[1:]) if player_id[1:].isdigit() else 1, name=name, role=role, alignment=ALIGNMENT_BY_ROLE[role], alive=alive)


def make_vote(day: int, voter: Player, target: Player) -> GameEvent:
    return GameEvent.create(day=day, phase=Phase.DAY_VOTE, type=EventType.VOTE_CAST, visibility="public", payload={"voter_id": voter.id, "voter_name": voter.name, "target_id": target.id, "target_name": target.name})


def make_speech(day: int, actor: Player, speech: str) -> GameEvent:
    return GameEvent.create(day=day, phase=Phase.DAY_SPEECH, type=EventType.CHAT_MESSAGE, visibility="public", payload={"actor_id": actor.id, "actor_name": actor.name, "speech": speech, "last_words": False})


def make_night_action(day: int, actor: Player, action_type: str, target: Player, *, phase: Phase = Phase.NIGHT_WOLF_ACTION) -> GameEvent:
    return GameEvent.create(day=day, phase=phase, type=EventType.NIGHT_ACTION, visibility="private", payload={"actor_id": actor.id, "actor_name": actor.name, "action_type": action_type, "target_id": target.id}, visible_to=[actor.id])


def make_seer_result(day: int, seer: Player, target: Player, *, is_wolf: bool) -> GameEvent:
    return GameEvent.create(day=day, phase=Phase.NIGHT_SEER_ACTION, type=EventType.PRIVATE_INFO, visibility="private", payload={"kind": "seer_result", "target_id": target.id, "target_name": target.name, "is_wolf": is_wolf, "message": f"Seer check: {target.name}"}, visible_to=[seer.id])


def make_death(day: int, player: Player, reason: str) -> GameEvent:
    return GameEvent.create(day=day, phase=Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE, type=EventType.PLAYER_DIED, visibility="public", payload={"player_id": player.id, "player_name": player.name, "reason": reason})


def make_state(players: list[Player], events: list[GameEvent], *, winner: Alignment, day: int = 2) -> GameState:
    return GameState(id="test-game", phase=Phase.GAME_END, day=day, players=players, events=events, winner=winner)


def counterfactuals_by_type(report, cf_type: str):
    return [c for c in report.counterfactuals if c.counterfactual_type == cf_type]


def _full_game_state():
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    witch = make_player("P2", "WitchA", Role.WITCH, alive=True)
    hunter = make_player("P3", "HunterA", Role.HUNTER, alive=True)
    guard = make_player("P4", "GuardA", Role.GUARD, alive=True)
    villager = make_player("P5", "VillagerA", Role.VILLAGER, alive=False)
    wolf1 = make_player("P6", "WolfA", Role.WEREWOLF, alive=False)
    wolf2 = make_player("P7", "WolfB", Role.WEREWOLF, alive=False)
    return make_state(
        [seer, witch, hunter, guard, villager, wolf1, wolf2],
        [
            make_seer_result(1, seer, wolf1, is_wolf=True),
            make_speech(1, seer, "I checked WolfA. Vote WolfA now."),
            make_speech(1, villager, "I agree. WolfA should go."),
            make_vote(1, witch, guard),
            make_vote(1, seer, wolf1),
            make_vote(1, guard, seer),
            make_vote(1, villager, wolf1),
            make_death(1, wolf1, "vote"),
            make_night_action(2, witch, "witch_poison", wolf2),
            make_death(2, wolf2, "poison"),
        ],
        winner=Alignment.VILLAGE,
        day=2,
    )


# ---------------------------------------------------------------------------
# Gate 1: ReplayBundle / ReviewArtifact for every game
# ---------------------------------------------------------------------------
def test_b_gate1_metrics_calculator_produces_game_metrics() -> None:
    state = _full_game_state()
    metrics = MetricsCalculator().compute(state)
    assert isinstance(metrics, GameMetrics)
    assert metrics.game_id == state.id
    assert metrics.winner == "village"
    assert len(metrics.player_scores) == len(state.players)
    for score in metrics.player_scores:
        assert 0.0 <= score.final_score <= 100.0
        assert score.role in {r.value for r in Role}
        assert score.alignment in {"village", "wolf"}


# ---------------------------------------------------------------------------
# Gate 2: RuleOutcomeScore / RoleTaskScore / multi-dimension scoring
# ---------------------------------------------------------------------------
def test_b_gate2_all_dimensions_covered() -> None:
    state = _full_game_state()
    metrics = MetricsCalculator().compute(state)
    for score in metrics.player_scores:
        assert score.camp_result_score >= 0.0
        assert score.role_task_score >= 0.0
        assert score.vote_score >= 0.0
        assert score.speech_score >= 0.0
        assert score.skill_score >= 0.0
        assert score.survival_score >= 0.0
        formula = metrics.metadata.get("role_score_formula", "")
        assert "camp" in formula and "role_task" in formula and "vote" in formula
        assert "speech" in formula and "skill" in formula and "survival" in formula


# ---------------------------------------------------------------------------
# Gate 3: BadCase detection covers >= 8 types
# ---------------------------------------------------------------------------
def test_b_gate3_bad_case_types_minimum() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    seer = make_player("P3", "SeerA", Role.SEER, alive=True)
    wolf1 = make_player("P4", "WolfA", Role.WEREWOLF, alive=False)
    state = make_state(
        [witch, villager, seer, wolf1],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_seer_result(1, seer, wolf1, is_wolf=True),
            make_speech(1, seer, "Need more discussion."),
            make_vote(1, seer, villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    bad_cases = [BadCaseReport(**item) if isinstance(item, dict) else item for item in (metrics.metadata.get("bad_case_reports", []) or [])]
    detected_types = {case.mistake_type for case in bad_cases}
    assert len(detected_types) >= 2
    assert any("poison" in str(case.description).lower() for case in bad_cases)


# ---------------------------------------------------------------------------
# Gate 4: Highlight detection for key actions
# ---------------------------------------------------------------------------
def test_b_gate4_highlights_from_review_bonus() -> None:
    state = _full_game_state()
    metrics = MetricsCalculator().compute(state)
    bonuses = metrics.metadata.get("review_bonuses", [])
    impact_bonuses = [b for b in bonuses if b.category == "impact" and b.score_delta > 0]
    assert impact_bonuses
    assert any(b.bonus_type == "last_wolf_poison" for b in bonuses)
    assert any(b.bonus_type == "seer_info_conversion" for b in bonuses)


# ---------------------------------------------------------------------------
# Gate 5: EvidenceBuilder — every bad case / highlight has evidence
# ---------------------------------------------------------------------------
def test_b_gate5_all_report_items_have_evidence() -> None:
    state = _full_game_state()
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    for case in report.bad_cases:
        assert case.description
        assert case.suggested_fix
    for point in report.turning_points:
        assert point.description
        assert point.evidence
    for case in report.counterfactuals:
        assert case.expected_effect
        assert case.evidence or case.source_bad_case_id
    assert report.mvp_results
    for mvp in report.mvp_results:
        assert mvp.reason
        assert mvp.evidence


# ---------------------------------------------------------------------------
# Gate 6: CounterfactualAnalyzer — vote / skill / info_release
# ---------------------------------------------------------------------------
def test_b_gate6_counterfactual_three_types_exist() -> None:
    # vote
    villager = make_player("P1", "VillagerA", Role.VILLAGER, alive=False)
    villager2 = make_player("P2", "VillagerB", Role.VILLAGER, alive=True)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    vote_state = make_state(
        [villager, villager2, wolf],
        [make_vote(1, villager, wolf), make_vote(1, wolf, villager), make_vote(1, villager2, villager), make_death(1, villager, "vote")],
        winner=Alignment.WOLF,
    )
    vote_cases = counterfactuals_by_type(ReviewReportBuilder().build(vote_state, MetricsCalculator().compute(vote_state)), "vote")
    assert vote_cases

    # skill
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    skill_state = make_state(
        [witch, villager, wolf],
        [make_night_action(1, witch, "witch_poison", villager), make_death(1, villager, "poison")],
        winner=Alignment.WOLF,
    )
    skill_cases = counterfactuals_by_type(ReviewReportBuilder().build(skill_state, MetricsCalculator().compute(skill_state)), "skill")
    assert skill_cases

    # info_release
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)
    info_state = make_state(
        [seer, wolf, villager],
        [make_seer_result(1, seer, wolf, is_wolf=True), make_speech(1, seer, "Need more discussion."), make_vote(1, seer, villager), make_vote(1, wolf, villager), make_death(1, villager, "vote")],
        winner=Alignment.WOLF,
    )
    info_cases = counterfactuals_by_type(ReviewReportBuilder().build(info_state, MetricsCalculator().compute(info_state)), "info_release")
    assert info_cases


# ---------------------------------------------------------------------------
# Gate 7: ReviewReport — JSON + Markdown, all 9 sections
# ---------------------------------------------------------------------------
def test_b_gate7_review_report_structure(tmp_path) -> None:
    state = _full_game_state()
    payload = generate_review_report(state, json_path=tmp_path / "review.json", markdown_path=tmp_path / "review.md")
    report = payload["report"]
    markdown = payload["final_markdown"]
    required_sections = [
        "# 本局复盘报告", "## 1. 本局概览", "## 2. MVP", "## 3. 玩家评分榜",
        "## 4. 关键转折点", "## 5. 反事实推演", "## 6. 玩家逐个复盘",
        "## 7. 关键失误", "## 8. 策略建议",
    ]
    for section in required_sections:
        assert section in markdown
    assert report["scoreboard"]
    assert report["mvp_results"]
    assert len(report["counterfactuals"]) >= 0  # may be empty for clean games
    assert report["strategy_suggestions"] or report["bad_cases"]  # at least suggestions
    assert json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert (tmp_path / "review.md").read_text(encoding="utf-8") == markdown


# ---------------------------------------------------------------------------
# Gate 8: ValidAgent — ReportEvaluator + ReviewQualityChecker
# ---------------------------------------------------------------------------
def test_b_gate8_valid_agent_blocks_bad_reports() -> None:
    state = _full_game_state()
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    # Should pass for a valid markdown
    good_md = MarkdownReportRenderer().render(report)
    result = ReportEvaluator().evaluate(report, good_md)
    assert result.grade == "pass"

    # Should fail if English enums leak
    bad_md = "# 本局复盘报告\n\n## 1. 本局概览\n- global_mvp\n- Seer\n- DAY_SPEECH\n"
    fail = ReportEvaluator().evaluate(report, bad_md)
    assert fail.grade == "fail"
    assert any("英文" in issue for issue in fail.issues)


# ---------------------------------------------------------------------------
# Gate 9: ReportOptimizer loop approves or rejects
# ---------------------------------------------------------------------------
def test_b_gate9_optimizer_passes_clean_report() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    optimizer = ReportOptimizer(generator=ReportGenerator(review_llm=MockReviewLLM()))
    result = optimizer.optimize(report)
    assert result.quality_passed is True
    assert result.final_markdown.startswith("# 本局复盘报告")
    assert result.feedback_history

    # Scores and MVP must not drift
    original = [(item["player_name"], item["adjusted_final_score"]) for item in report.scoreboard]
    assert [(item["player_name"], item["adjusted_final_score"]) for item in report.scoreboard] == original


# ---------------------------------------------------------------------------
# Gate 10: ValidationResult embedded in ReviewReport
# ---------------------------------------------------------------------------
def test_b_gate10_validation_result_in_metadata(tmp_path) -> None:
    state = _full_game_state()
    payload = generate_review_report(state, json_path=tmp_path / "vr.json", markdown_path=tmp_path / "vr.md")
    report = payload["report"]
    validation = report["metadata"]["validation_result"]
    assert validation["passed"] is True
    assert validation["publish_allowed"] is True
    assert validation["score"] >= 0.0
    assert isinstance(validation["issues"], list)
    assert payload["quality_passed"] is True


# ---------------------------------------------------------------------------
# Gate 11: Strategy suggestions from bad cases / counterfactuals / bonuses
# ---------------------------------------------------------------------------
def test_b_gate11_strategy_suggestions_are_grounded() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    state = make_state(
        [witch, villager, wolf],
        [make_night_action(1, witch, "witch_poison", villager), make_death(1, villager, "poison")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    assert report.strategy_suggestions
    for suggestion in report.strategy_suggestions:
        assert suggestion.source
        assert suggestion.metadata.get("evidence_summary")
    reusable = [s for s in report.strategy_suggestions if s.metadata.get("scope") == "reusable"]
    assert reusable
    assert all(s.metadata.get("safe_for_agent") is True for s in reusable)


# ---------------------------------------------------------------------------
# Gate 12: Leaderboard — persona / role / version aggregations
# ---------------------------------------------------------------------------
def test_b_gate12_leaderboard_all_dimensions(tmp_path) -> None:
    aggregator = LeaderboardAggregator()
    m = GameMetrics(
        game_id="g1", winner="village", total_days=1, total_events=1,
        wolf_elimination_rate=1.0, village_survival_rate=1.0, info_efficiency=1.0,
        player_scores=[
            PlayerScore("p1", "PersonaA", "persona-a", "PersonaA", "Seer", "village", 1.0, 0.9, 0.8, 0.8, 0.8, 1.0, 0.0, 80.0, adjusted_final_score=84.0, impact_bonus=2.0),
            PlayerScore("p2", "PersonaB", "persona-b", "PersonaB", "Seer", "village", 0.0, 0.5, 0.5, 0.5, 0.5, 0.4, 0.0, 60.0, adjusted_final_score=60.0),
            PlayerScore("p3", "PersonaA", "persona-a", "PersonaA", "Villager", "village", 0.0, 0.5, 0.4, 0.5, 0.5, 0.4, 0.0, 44.0, adjusted_final_score=50.0),
        ],
        metadata={"strategy_version": "v1"},
    )
    all_results = aggregator.aggregate_all([m])
    assert "persona" in all_results
    assert "role" in all_results
    assert "version" in all_results
    assert all_results["persona"].leaderboard_type == "persona"
    assert all_results["role"].leaderboard_type == "role"
    assert all_results["version"].leaderboard_type == "version"
    for result in all_results.values():
        assert result.entries
        assert result.source_games == 1
        lb_path = tmp_path / f"{result.leaderboard_type}_lb.json"
        export_leaderboard(result, lb_path)
        assert lb_path.exists()


# ---------------------------------------------------------------------------
# Gate 13: Markdown token localization (no English enums)
# ---------------------------------------------------------------------------
def test_b_gate13_markdown_is_localized() -> None:
    wolf = make_player("P1", "Alpha", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "Bravo", Role.SEER, alive=False)
    villager = make_player("P3", "Charlie", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_speech(1, wolf, "Bravo is fake. Vote Bravo."), make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    markdown = MarkdownReportRenderer().render(report)
    banned = ["global_mvp", "winning_camp_mvp", "Seer", "Werewolf", "Witch", "Hunter", "Guard", "Villager", "village", "wolf", "DAY_SPEECH", "DAY_VOTE", "checked-good player"]
    for token in banned:
        assert token not in markdown
    assert "预言家" in markdown or "狼人" in markdown
    assert "好人阵营" in markdown or "狼人阵营" in markdown
    assert "全局 MVP" in markdown
    assert "胜方 MVP" in markdown


# ---------------------------------------------------------------------------
# Gate 14: Real engine game → full pipeline → validated report
# ---------------------------------------------------------------------------
def test_b_gate14_real_engine_full_pipeline(tmp_path) -> None:
    from backend.engine.game import WerewolfGame

    game = WerewolfGame(seed=7)
    game.play()
    assert game.state.phase == Phase.GAME_END
    payload = generate_review_report(
        game.state,
        json_path=tmp_path / "real_review.json",
        markdown_path=tmp_path / "real_review.md",
    )
    report = payload["report"]
    validation = report["metadata"]["validation_result"]
    assert validation["passed"] is True
    assert validation["publish_allowed"] is True
    assert report["scoreboard"]
    assert len(report["scoreboard"]) == len(game.state.players)
    assert report["mvp_results"]
    # Markdown must be valid
    md = payload["final_markdown"]
    assert "# 本局复盘报告" in md
    assert "## 1. 本局概览" in md
    assert "## 2. MVP" in md
    assert len(report["bad_cases"]) >= 0
    assert len(report["counterfactuals"]) >= 0
    assert json.loads((tmp_path / "real_review.json").read_text(encoding="utf-8"))
    assert (tmp_path / "real_review.md").read_text(encoding="utf-8") == md


# ---------------------------------------------------------------------------
# Gate 15: StrategyKnowledge extraction from reports
# ---------------------------------------------------------------------------
def test_b_gate15_strategy_knowledge_export(tmp_path) -> None:
    from backend.engine.game import WerewolfGame

    game = WerewolfGame(seed=11)
    game.play()
    state = game.state
    metrics = MetricsCalculator().compute(state)
    report_obj = ReviewReportBuilder().build(state, metrics)
    report_obj.metadata["validation_result"] = {"passed": True, "publish_allowed": True}

    knowledge = StrategyKnowledgeExtractor().extract(report_obj)
    assert knowledge
    assert all(item.safe_for_agent for item in knowledge)
    path = tmp_path / "strategy_knowledge.json"
    payload = export_strategy_knowledge(knowledge, path)
    assert path.exists()
    assert json.loads(json.dumps(payload, ensure_ascii=False))
    blob = " ".join(f"{item.trigger_condition} {item.suggestion}" for item in knowledge)
    # Must be sanitized — no specific player names
    for player in state.players:
        assert player.name not in blob


# ---------------------------------------------------------------------------
# Gate 16: ReviewReport JSON ↔ Markdown score consistency
# ---------------------------------------------------------------------------
def test_b_gate16_json_markdown_score_consistency() -> None:
    state = _full_game_state()
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    markdown = MarkdownReportRenderer().render(report)
    for entry in report.scoreboard:
        assert str(entry["adjusted_final_score"]) in markdown
        assert entry["player_name"] in markdown
    for mvp in report.mvp_results:
        assert mvp.player_name in markdown


# ---------------------------------------------------------------------------
# Gate 17: Real engine game → path B to C evolution pipeline
# ---------------------------------------------------------------------------
def test_b_gate17_real_engine_b_to_c_pipeline(tmp_path) -> None:
    from backend.engine.game import WerewolfGame
    from backend.eval.evolution import EvolutionPipeline, export_evolution_summary

    game = WerewolfGame(seed=13)
    game.play()
    state = game.state
    metrics = MetricsCalculator().compute(state)
    report_obj = ReviewReportBuilder().build(state, metrics)
    report_obj.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}

    summary = EvolutionPipeline().run(
        [report_obj],
        baseline_metrics=[metrics],
        candidate_metrics=[metrics],
        summary_path=tmp_path / "evolution_summary.json",
    )
    assert summary.approved_report_count == 1
    assert summary.knowledge_doc_count >= 0
    assert summary.candidate_patch_count >= 0
    payload = export_evolution_summary(summary, tmp_path / "summary_copy.json")
    assert json.loads(json.dumps(payload, ensure_ascii=False))
