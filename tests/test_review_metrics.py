from __future__ import annotations

import json

import pytest

from backend.engine.models import Alignment
from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.engine.models import Phase
from backend.engine.models import Player
from backend.engine.models import Role
from backend.eval.report_graph import LANGGRAPH_AVAILABLE
from backend.eval.report_graph import LangGraphReportOptimizer
from backend.eval.report_graph import create_report_optimizer
from backend.eval.review import CounterfactualAnalyzer
from backend.eval.review import FinalScoreCalculator
from backend.eval.review import GameMetrics
from backend.eval.review import LeaderboardAggregator
from backend.eval.review import MarkdownReportRenderer
from backend.eval.review import MetricsCalculator
from backend.eval.review import MockReviewLLM
from backend.eval.review import MVPSelector
from backend.eval.review import PlayerScore
from backend.eval.review import ReportEvaluator
from backend.eval.review import ReportGenerator
from backend.eval.review import ReportOptimizer
from backend.eval.review import ReviewBonus
from backend.eval.review import ReviewQualityChecker
from backend.eval.review import ReviewReportBuilder
from backend.eval.review import StrategyKnowledgeExtractor
from backend.eval.review import export_leaderboard
from backend.eval.review import export_review_report
from backend.eval.review import export_strategy_knowledge

ALIGNMENT_BY_ROLE = {
    Role.WEREWOLF: Alignment.WOLF,
    Role.SEER: Alignment.VILLAGE,
    Role.WITCH: Alignment.VILLAGE,
    Role.HUNTER: Alignment.VILLAGE,
    Role.GUARD: Alignment.VILLAGE,
    Role.VILLAGER: Alignment.VILLAGE,
}


def make_player(player_id: str, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        id=player_id,
        seat=int(player_id[1:]) if player_id[1:].isdigit() else 1,
        name=name,
        role=role,
        alignment=ALIGNMENT_BY_ROLE[role],
        alive=alive,
    )


def make_vote(day: int, voter: Player, target: Player, *, phase: Phase = Phase.DAY_VOTE) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.VOTE_CAST,
        visibility="public",
        payload={
            "voter_id": voter.id,
            "voter_name": voter.name,
            "target_id": target.id,
            "target_name": target.name,
        },
    )


def make_speech(day: int, actor: Player, speech: str, *, last_words: bool = False) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.DAY_SPEECH,
        type=EventType.CHAT_MESSAGE,
        visibility="public",
        payload={
            "actor_id": actor.id,
            "actor_name": actor.name,
            "speech": speech,
            "last_words": last_words,
        },
    )


def make_night_action(
    day: int, actor: Player, action_type: str, target: Player, *, phase: Phase = Phase.NIGHT_WOLF_ACTION
) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=phase,
        type=EventType.NIGHT_ACTION,
        visibility="private",
        payload={
            "actor_id": actor.id,
            "actor_name": actor.name,
            "action_type": action_type,
            "target_id": target.id,
        },
        visible_to=[actor.id],
    )


def make_seer_result(day: int, seer: Player, target: Player, *, is_wolf: bool) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.NIGHT_SEER_ACTION,
        type=EventType.PRIVATE_INFO,
        visibility="private",
        payload={
            "kind": "seer_result",
            "target_id": target.id,
            "target_name": target.name,
            "is_wolf": is_wolf,
            "message": f"Seer check: {target.name}",
        },
        visible_to=[seer.id],
    )


def make_death(day: int, player: Player, reason: str) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.DAY_RESOLVE if reason == "vote" else Phase.NIGHT_RESOLVE,
        type=EventType.PLAYER_DIED,
        visibility="public",
        payload={
            "player_id": player.id,
            "player_name": player.name,
            "reason": reason,
        },
    )


def make_hunter_shot(day: int, hunter: Player, target: Player) -> GameEvent:
    return GameEvent.create(
        day=day,
        phase=Phase.HUNTER_SHOOT,
        type=EventType.HUNTER_SHOT,
        visibility="public",
        payload={
            "hunter_id": hunter.id,
            "hunter_name": hunter.name,
            "target_id": target.id,
            "target_name": target.name,
        },
    )


def make_state(players: list[Player], events: list[GameEvent], *, winner: Alignment, day: int = 2) -> GameState:
    return GameState(
        id="test-game",
        phase=Phase.GAME_END,
        day=day,
        players=players,
        events=events,
        winner=winner,
    )


def score_by_name(metrics, name: str):
    return next(score for score in metrics.player_scores if score.player_name == name)


def bonuses_for_player(metrics, player_id: str):
    return [bonus for bonus in metrics.metadata["review_bonuses"] if bonus.player_id == player_id]


def counterfactuals_by_type(report, counterfactual_type: str):
    return [case for case in report.counterfactuals if case.counterfactual_type == counterfactual_type]


def test_werewolf_with_vote_contribution_scores_higher_than_idle_wolf() -> None:
    wolf_lead = make_player("P1", "LeadWolf", Role.WEREWOLF, alive=True)
    wolf_idle = make_player("P2", "IdleWolf", Role.WEREWOLF, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)
    seer = make_player("P4", "SeerA", Role.SEER, alive=False)

    state = make_state(
        [wolf_lead, wolf_idle, villager, seer],
        [
            make_speech(1, wolf_lead, "VillagerA is my wolf read. Vote VillagerA."),
            make_vote(1, wolf_lead, villager),
            make_vote(1, wolf_idle, wolf_lead),
            make_night_action(1, wolf_lead, "attack", seer),
            make_night_action(1, wolf_idle, "attack", seer),
            make_death(1, seer, "wolf"),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )

    metrics = MetricsCalculator().compute(state)
    assert score_by_name(metrics, "LeadWolf").final_score > score_by_name(metrics, "IdleWolf").final_score


def test_seer_checking_wolf_and_releasing_info_gets_higher_role_task_score() -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)

    released_state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "I am SeerA. WolfA is checked wolf. Vote WolfA."),
            make_vote(1, seer, wolf),
            make_death(1, wolf, "vote"),
        ],
        winner=Alignment.VILLAGE,
    )
    hidden_state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "Need more discussion before I vote."),
            make_vote(1, seer, wolf),
            make_death(1, wolf, "vote"),
        ],
        winner=Alignment.VILLAGE,
    )

    released_score = score_by_name(MetricsCalculator().compute(released_state), "SeerA")
    hidden_score = score_by_name(MetricsCalculator().compute(hidden_state), "SeerA")
    assert released_score.role_task_score > hidden_score.role_task_score


def test_witch_poisoning_villager_generates_mistake_penalty() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)

    state = make_state(
        [witch, wolf, villager],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )

    metrics = MetricsCalculator().compute(state)
    witch_score = score_by_name(metrics, "WitchA")
    assert witch_score.mistake_penalty > 0
    assert any("critical" in mistake for mistake in witch_score.mistakes)


def test_villager_hitting_wolf_scores_better_than_consecutive_good_votes() -> None:
    villager_good = make_player("P1", "VillagerGood", Role.VILLAGER, alive=True)
    villager_bad = make_player("P2", "VillagerBad", Role.VILLAGER, alive=True)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=False)
    seer = make_player("P4", "SeerA", Role.SEER, alive=False)

    state = make_state(
        [villager_good, villager_bad, wolf, seer],
        [
            make_speech(1, villager_good, "WolfA is suspicious, I will vote WolfA."),
            make_speech(1, villager_bad, "SeerA feels wrong to me."),
            make_vote(1, villager_good, wolf),
            make_vote(1, villager_bad, seer),
            make_vote(2, villager_bad, seer),
            make_death(1, wolf, "vote"),
            make_death(2, seer, "vote"),
        ],
        winner=Alignment.VILLAGE,
        day=2,
    )

    metrics = MetricsCalculator().compute(state)
    assert score_by_name(metrics, "VillagerGood").vote_score > score_by_name(metrics, "VillagerBad").vote_score


def test_persona_role_normalized_score_is_not_raw_win_rate() -> None:
    calculator = MetricsCalculator()
    player_scores = [
        PlayerScore(
            "p1", "PersonaA", "persona-a", "PersonaA", "Seer", "village", 1.0, 0.9, 0.8, 0.8, 0.9, 1.0, 0.0, 82.0
        ),
        PlayerScore(
            "p2", "PersonaA", "persona-a", "PersonaA", "Villager", "village", 0.0, 0.5, 0.4, 0.5, 0.5, 0.4, 0.0, 44.0
        ),
        PlayerScore(
            "p3", "PersonaB", "persona-b", "PersonaB", "Seer", "village", 0.0, 0.4, 0.5, 0.5, 0.5, 0.4, 0.0, 60.0
        ),
        PlayerScore(
            "p4", "PersonaB", "persona-b", "PersonaB", "Villager", "village", 1.0, 0.6, 0.6, 0.6, 0.5, 1.0, 0.0, 50.0
        ),
    ]

    persona_metrics = calculator.aggregate_persona_metrics(player_scores)
    persona_a = next(item for item in persona_metrics if item.persona_id == "persona-a")
    assert persona_a.role_normalized_score != persona_a.raw_win_rate


def test_ordinary_correct_actions_do_not_repeat_highlight_bonus() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=True)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=False)
    wolf_two = make_player("P4", "WolfB", Role.WEREWOLF, alive=True)

    state = make_state(
        [witch, villager, wolf, wolf_two],
        [
            make_speech(1, villager, "WolfA seems suspicious."),
            make_vote(1, villager, witch),
            make_vote(1, witch, villager),
            make_night_action(1, witch, "witch_poison", wolf),
            make_death(1, wolf, "poison"),
        ],
        winner=Alignment.VILLAGE,
    )

    metrics = MetricsCalculator().compute(state)
    assert bonuses_for_player(metrics, witch.id) == []
    assert bonuses_for_player(metrics, villager.id) == []


def test_key_actions_generate_impact_bonuses() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    guard = make_player("P4", "GuardA", Role.GUARD, alive=True)
    wolf1 = make_player("P5", "WolfA", Role.WEREWOLF, alive=False)
    wolf2 = make_player("P6", "WolfB", Role.WEREWOLF, alive=False)

    state = make_state(
        [witch, seer, villager, guard, wolf1, wolf2],
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

    metrics = MetricsCalculator().compute(state)
    witch_bonuses = bonuses_for_player(metrics, witch.id)
    seer_bonuses = bonuses_for_player(metrics, seer.id)
    villager_bonuses = bonuses_for_player(metrics, villager.id)

    assert any(bonus.bonus_type == "last_wolf_poison" and bonus.category == "impact" for bonus in witch_bonuses)
    assert any(bonus.bonus_type == "seer_info_conversion" and bonus.category == "impact" for bonus in seer_bonuses)
    assert any(bonus.bonus_type == "decisive_vote" and bonus.category == "impact" for bonus in villager_bonuses)


def test_wolf_pushing_real_seer_out_gets_impact_bonus() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)

    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )

    metrics = MetricsCalculator().compute(state)
    wolf_bonuses = bonuses_for_player(metrics, wolf.id)
    assert any(bonus.bonus_type == "wolf_power_role_push" for bonus in wolf_bonuses)


def test_bonus_validation_and_caps_are_enforced() -> None:
    player_scores = [
        PlayerScore("p1", "A", "A", "A", "Villager", "village", 1.0, 0.8, 0.8, 0.8, 0.8, 1.0, 0.0, 70.0),
    ]
    bonuses = [
        ReviewBonus("p1", "no_evidence", 4.0, "invalid", [], 0.9, category="impact"),
        ReviewBonus("p1", "low_confidence", 4.0, "invalid", ["weak"], 0.4, category="impact"),
        ReviewBonus("p1", "too_large_positive", 8.0, "cap", ["e1"], 0.9, category="impact"),
        ReviewBonus("p1", "semantic", 4.0, "ok", ["e2"], 0.9, category="semantic"),
        ReviewBonus("p1", "extra_positive", 4.0, "cap total", ["e3"], 0.9, category="impact"),
        ReviewBonus("p1", "too_large_negative", -8.0, "cap", ["e4"], 0.9, category="penalty"),
        ReviewBonus("p1", "extra_negative", -8.0, "cap total", ["e5"], 0.9, category="penalty"),
    ]

    adjusted = FinalScoreCalculator().apply(player_scores, bonuses)[0]
    assert adjusted.impact_bonus + adjusted.semantic_highlight_bonus <= 10.0
    assert adjusted.review_penalty <= 10.0
    assert adjusted.adjusted_final_score == 70.0


def test_mvp_selection_uses_adjusted_score_and_bonus_weights() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=False)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=True)
    seer = make_player("P3", "SeerA", Role.SEER, alive=True)
    state = make_state([wolf, villager, seer], [], winner=Alignment.VILLAGE)

    wolf_score = PlayerScore(
        "P1", "WolfA", "wolf", "WolfA", "Werewolf", "wolf", 0.0, 0.9, 0.8, 0.8, 0.8, 0.2, 0.0, 74.0
    )
    villager_score = PlayerScore(
        "P2", "VillagerA", "villager", "VillagerA", "Villager", "village", 1.0, 0.7, 0.6, 0.6, 0.5, 1.0, 0.0, 76.0
    )
    seer_score = PlayerScore("P3", "SeerA", "seer", "SeerA", "Seer", "village", 1.0, 0.8, 0.8, 0.8, 0.8, 1.0, 0.0, 79.0)
    wolf_score.adjusted_final_score = 90.0
    wolf_score.impact_bonus = 10.0
    wolf_score.semantic_highlight_bonus = 5.0
    villager_score.adjusted_final_score = 83.0
    villager_score.impact_bonus = 1.0
    villager_score.semantic_highlight_bonus = 0.0
    seer_score.adjusted_final_score = 84.0
    seer_score.impact_bonus = 2.0
    seer_score.semantic_highlight_bonus = 1.0

    bonuses = [
        ReviewBonus("P1", "big_swing", 5.0, "swing", ["wolf forced huge swing"], 0.9, category="impact"),
        ReviewBonus("P1", "semantic", 2.0, "fake claim", ["wolf sold the fake line"], 0.9, category="semantic"),
        ReviewBonus("P3", "small_impact", 2.0, "seer lead", ["seer closed the vote"], 0.9, category="impact"),
    ]

    results = MVPSelector().select(state, [wolf_score, villager_score, seer_score], bonuses)
    global_mvp = next(item for item in results if item.mvp_type == "global_mvp")
    winning_mvp = next(item for item in results if item.mvp_type == "winning_camp_mvp")

    assert global_mvp.player_id == "P1"
    assert winning_mvp.alignment == "village"
    assert winning_mvp.player_id != global_mvp.player_id


def test_review_report_builder_generates_sorted_scoreboard_and_reviews() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=True)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=False)
    wolf_two = make_player("P4", "WolfB", Role.WEREWOLF, alive=True)

    state = make_state(
        [witch, villager, wolf, wolf_two],
        [
            make_speech(1, villager, "WolfA is suspicious, vote WolfA."),
            make_vote(1, witch, villager),
            make_vote(1, villager, wolf),
            make_death(1, wolf, "vote"),
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )

    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    assert report.game_id == state.id
    assert report.scoreboard
    adjusted_scores = [entry["adjusted_final_score"] for entry in report.scoreboard]
    assert adjusted_scores == sorted(adjusted_scores, reverse=True)

    witch_review = next(item for item in report.player_reviews if item.player_id == witch.id)
    assert witch_review.mistakes
    assert witch_review.suggestions
    assert witch_review.speech_summary
    assert witch_review.rule_score_reasons
    assert witch_review.adjustment_reasons
    assert witch_review.score_summary
    assert report.counterfactuals


def test_turning_points_can_be_built_from_impact_bonus_and_critical_bad_case() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    wolf1 = make_player("P4", "WolfA", Role.WEREWOLF, alive=False)
    wolf2 = make_player("P5", "WolfB", Role.WEREWOLF, alive=False)

    state = make_state(
        [witch, seer, villager, wolf1, wolf2],
        [
            make_seer_result(1, seer, wolf1, is_wolf=True),
            make_speech(1, seer, "I checked WolfA. Vote WolfA now."),
            make_vote(1, villager, seer),
            make_vote(1, seer, wolf1),
            make_vote(1, witch, wolf1),
            make_death(1, wolf1, "vote"),
            make_night_action(2, witch, "witch_poison", wolf2),
            make_death(2, wolf2, "poison"),
        ],
        winner=Alignment.VILLAGE,
        day=2,
    )

    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    assert any("最后一狼毒杀" in point.title or "查验信息转化" in point.title for point in report.turning_points)

    mispoison_state = make_state(
        [witch, villager, wolf2],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )
    mispoison_metrics = MetricsCalculator().compute(mispoison_state)
    mispoison_report = ReviewReportBuilder().build(mispoison_state, mispoison_metrics)
    assert any("致命失误" in point.title for point in mispoison_report.turning_points)


def test_markdown_renderer_contains_required_sections_and_json_is_serializable(tmp_path) -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)

    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    markdown = MarkdownReportRenderer().render(report)
    assert "本局复盘报告" in markdown
    assert "MVP" in markdown
    assert "玩家评分榜" in markdown
    assert "关键转折点" in markdown
    assert "反事实推演" in markdown
    assert "玩家逐个复盘" in markdown

    json_path = tmp_path / "review.json"
    markdown_path = tmp_path / "review.md"
    payload = export_review_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json.loads(json.dumps(payload, ensure_ascii=False))
    assert json_path.exists()
    assert markdown_path.exists()


def test_vote_counterfactual_generated_for_wrong_villager_exile() -> None:
    villager = make_player("P1", "VillagerA", Role.VILLAGER, alive=False)
    villager_two = make_player("P2", "VillagerB", Role.VILLAGER, alive=True)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)

    state = make_state(
        [villager, villager_two, wolf],
        [
            make_vote(1, villager, wolf),
            make_vote(1, wolf, villager),
            make_vote(1, villager_two, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    vote_cases = counterfactuals_by_type(report, "vote")
    assert vote_cases
    assert any("WolfA" in case.alternative_decision for case in vote_cases)


def test_witch_mispoison_generates_skill_counterfactual() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)

    state = make_state(
        [witch, villager, wolf],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    skill_cases = counterfactuals_by_type(report, "skill")
    assert any("held poison" in case.alternative_decision for case in skill_cases)


def test_hunter_friendly_fire_generates_skill_counterfactual() -> None:
    hunter = make_player("P1", "HunterA", Role.HUNTER, alive=False)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)

    state = make_state(
        [hunter, villager, wolf],
        [
            make_hunter_shot(1, hunter, villager),
            make_death(1, villager, "shot"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    skill_cases = counterfactuals_by_type(report, "skill")
    assert any("held the shot" in case.alternative_decision for case in skill_cases)


def test_seer_hidden_wolf_check_generates_info_release_counterfactual() -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)

    state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "Need more discussion before I vote."),
            make_vote(1, seer, villager),
            make_vote(1, wolf, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    info_cases = counterfactuals_by_type(report, "info_release")
    assert info_cases
    assert any("announced the wolf check" in case.alternative_decision for case in info_cases)


def test_counterfactual_analyzer_can_run_directly() -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)
    state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_vote(1, seer, villager),
            make_vote(1, wolf, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    cases = CounterfactualAnalyzer().analyze(
        state,
        metrics,
        bad_cases=report.bad_cases,
        turning_points=report.turning_points,
        review_bonuses=metrics.metadata["review_bonuses"],
    )
    assert cases


def test_leaderboard_aggregator_builds_persona_leaderboard_from_game_metrics() -> None:
    aggregator = LeaderboardAggregator()
    metrics_a = GameMetrics(
        game_id="g1",
        winner="village",
        total_days=2,
        total_events=5,
        wolf_elimination_rate=1.0,
        village_survival_rate=0.5,
        info_efficiency=0.8,
        player_scores=[
            PlayerScore(
                "p1",
                "PersonaA",
                "persona-a",
                "PersonaA",
                "Seer",
                "village",
                1.0,
                0.9,
                0.8,
                0.8,
                0.8,
                1.0,
                0.0,
                80.0,
                adjusted_final_score=84.0,
                impact_bonus=2.0,
            ),
            PlayerScore(
                "p2",
                "PersonaB",
                "persona-b",
                "PersonaB",
                "Seer",
                "village",
                0.0,
                0.5,
                0.5,
                0.5,
                0.5,
                0.4,
                0.0,
                60.0,
                adjusted_final_score=60.0,
                mistakes=["[critical] miss"],
            ),
        ],
        metadata={"strategy_version": "v1"},
    )
    metrics_b = GameMetrics(
        game_id="g2",
        winner="village",
        total_days=2,
        total_events=5,
        wolf_elimination_rate=1.0,
        village_survival_rate=0.5,
        info_efficiency=0.8,
        player_scores=[
            PlayerScore(
                "p3",
                "PersonaA",
                "persona-a",
                "PersonaA",
                "Villager",
                "village",
                0.0,
                0.5,
                0.4,
                0.5,
                0.5,
                0.4,
                0.0,
                44.0,
                adjusted_final_score=50.0,
            ),
            PlayerScore(
                "p4",
                "PersonaB",
                "persona-b",
                "PersonaB",
                "Villager",
                "village",
                1.0,
                0.6,
                0.6,
                0.6,
                0.5,
                1.0,
                0.0,
                50.0,
                adjusted_final_score=58.0,
            ),
        ],
        metadata={"strategy_version": "v2"},
    )

    result = aggregator.aggregate_persona([metrics_a, metrics_b])
    persona_a = next(entry for entry in result.entries if entry.key == "persona-a")

    assert result.leaderboard_type == "persona"
    assert persona_a.games_played == 2
    assert persona_a.avg_adjusted_final_score == 67.0
    assert persona_a.role_normalized_score != persona_a.win_rate


def test_leaderboard_aggregator_builds_role_leaderboard_sorted_by_adjusted_score() -> None:
    aggregator = LeaderboardAggregator()
    metrics = GameMetrics(
        game_id="g3",
        winner="village",
        total_days=2,
        total_events=5,
        wolf_elimination_rate=1.0,
        village_survival_rate=0.5,
        info_efficiency=0.8,
        player_scores=[
            PlayerScore(
                "p1",
                "A",
                "a",
                "A",
                "Seer",
                "village",
                1.0,
                0.9,
                0.8,
                0.8,
                0.8,
                1.0,
                0.0,
                80.0,
                adjusted_final_score=85.0,
            ),
            PlayerScore(
                "p2",
                "B",
                "b",
                "B",
                "Villager",
                "village",
                1.0,
                0.6,
                0.6,
                0.6,
                0.5,
                1.0,
                0.0,
                55.0,
                adjusted_final_score=60.0,
            ),
        ],
    )

    result = aggregator.aggregate_role([metrics])
    assert result.entries[0].display_name == "Seer"
    assert result.entries[0].metadata["avg_role_task_score"] > result.entries[1].metadata["avg_role_task_score"]


def test_leaderboard_aggregator_builds_version_leaderboard_from_review_reports() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)

    state_v1 = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    metrics_v1 = MetricsCalculator().compute(state_v1)
    metrics_v1.metadata["strategy_version"] = "v1"
    report_v1 = ReviewReportBuilder().build(state_v1, metrics_v1)
    report_v1.metadata["strategy_version"] = "v1"

    state_v2 = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "I checked WolfA. Vote WolfA now."),
            make_vote(1, seer, wolf),
            make_vote(1, villager, wolf),
            make_death(1, wolf, "vote"),
        ],
        winner=Alignment.VILLAGE,
    )
    metrics_v2 = MetricsCalculator().compute(state_v2)
    metrics_v2.metadata["strategy_version"] = "v2"
    report_v2 = ReviewReportBuilder().build(state_v2, metrics_v2)
    report_v2.metadata["strategy_version"] = "v2"

    result = LeaderboardAggregator().aggregate_version([report_v1, report_v2])
    v2_entry = next(entry for entry in result.entries if entry.key == "v2")

    assert result.leaderboard_type == "version"
    assert v2_entry.games_played > 0
    assert "avg_counterfactual_count" in v2_entry.metadata


def test_leaderboard_export_is_json_serializable(tmp_path) -> None:
    result = LeaderboardAggregator().aggregate_persona(
        [
            GameMetrics(
                game_id="g4",
                winner="village",
                total_days=1,
                total_events=1,
                wolf_elimination_rate=1.0,
                village_survival_rate=1.0,
                info_efficiency=1.0,
                player_scores=[
                    PlayerScore(
                        "p1",
                        "PersonaA",
                        "persona-a",
                        "PersonaA",
                        "Villager",
                        "village",
                        1.0,
                        0.6,
                        0.7,
                        0.6,
                        0.5,
                        1.0,
                        0.0,
                        65.0,
                        adjusted_final_score=70.0,
                    ),
                ],
            )
        ]
    )
    path = tmp_path / "leaderboard.json"
    payload = export_leaderboard(result, path)

    assert json.loads(json.dumps(payload, ensure_ascii=False))
    assert path.exists()


def test_strategy_knowledge_extractor_extracts_from_strategy_suggestions() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)

    knowledge = StrategyKnowledgeExtractor().extract(report)
    assert knowledge
    assert any(item.source_type == "strategy_suggestion" for item in knowledge)
    assert all(item.safe_for_agent for item in knowledge)


def test_strategy_knowledge_extractor_extracts_from_bad_cases_and_sets_priority() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    state = make_state(
        [witch, villager, wolf],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    knowledge = StrategyKnowledgeExtractor().extract(report)
    bad_case_items = [item for item in knowledge if item.source_type == "bad_case"]
    assert bad_case_items
    assert any(item.target_role == "Witch" and item.priority == "high" for item in bad_case_items)


def test_strategy_knowledge_extractor_extracts_from_counterfactuals() -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)
    state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "Need more discussion before I vote."),
            make_vote(1, seer, villager),
            make_vote(1, wolf, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    knowledge = StrategyKnowledgeExtractor().extract(report)
    counterfactual_items = [item for item in knowledge if item.source_type == "counterfactual"]
    assert counterfactual_items
    assert any(item.target_role == "Seer" for item in counterfactual_items)


def test_strategy_knowledge_is_sanitized_and_safe_for_agent(tmp_path) -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    knowledge = StrategyKnowledgeExtractor().extract(report)
    text_blob = " ".join(f"{item.trigger_condition} {item.suggestion} {item.evidence_summary}" for item in knowledge)
    assert "SeerA" not in text_blob
    assert "WolfA" not in text_blob
    assert "VillagerA" not in text_blob
    assert "is wolf" not in text_blob.lower()
    assert "is seer" not in text_blob.lower()
    assert all(item.safe_for_agent for item in knowledge)

    path = tmp_path / "strategy_knowledge.json"
    payload = export_strategy_knowledge(knowledge, path)
    assert json.loads(json.dumps(payload, ensure_ascii=False))
    assert path.exists()


def test_markdown_report_is_fully_localized_and_human_readable() -> None:
    wolf = make_player("P1", "Alpha", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "Bravo", Role.SEER, alive=False)
    villager = make_player("P3", "Charlie", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "Bravo is fake. Vote Bravo."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    markdown = MarkdownReportRenderer().render(report)

    banned_tokens = [
        "global_mvp",
        "winning_camp_mvp",
        "Seer",
        "Werewolf",
        "Witch",
        "Hunter",
        "Guard",
        "Villager",
        "village",
        "wolf",
        "DAY_SPEECH",
        "DAY_VOTE",
        "checked-good player",
    ]
    for token in banned_tokens:
        assert token not in markdown

    assert "预言家" in markdown or "狼人" in markdown
    assert "好人阵营" in markdown or "狼人阵营" in markdown
    assert "全局 MVP" in markdown
    assert "胜方 MVP" in markdown


def test_reusable_strategy_suggestions_are_desensitized() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    reusable = [item for item in report.strategy_suggestions if item.metadata.get("scope") == "reusable"]
    assert reusable
    assert all(item.metadata.get("safe_for_agent") is True for item in reusable)
    assert all(
        "WolfA" not in item.suggestion and "SeerA" not in item.suggestion and "VillagerA" not in item.suggestion
        for item in reusable
    )


def test_bonus_conflicts_do_not_generate_generic_seer_release_advice() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    wolf1 = make_player("P4", "WolfA", Role.WEREWOLF, alive=False)
    wolf2 = make_player("P5", "WolfB", Role.WEREWOLF, alive=False)

    state = make_state(
        [witch, seer, villager, wolf1, wolf2],
        [
            make_seer_result(1, seer, wolf1, is_wolf=True),
            make_speech(1, seer, "I checked WolfA. Vote WolfA now."),
            make_vote(1, villager, seer),
            make_vote(1, seer, wolf1),
            make_vote(1, witch, wolf1),
            make_death(1, wolf1, "vote"),
            make_night_action(2, witch, "witch_poison", wolf2),
            make_death(2, wolf2, "poison"),
        ],
        winner=Alignment.VILLAGE,
        day=2,
    )

    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    seer_review = next(item for item in report.player_reviews if item.player_name == "SeerA")
    assert any("公共压力" in item or "查杀信息" in item for item in seer_review.highlights)
    assert all("更早公开" not in item for item in seer_review.suggestions)


def test_markdown_player_review_no_longer_renders_debug_style_subscores() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    markdown = MarkdownReportRenderer().render(report)

    assert "阵营结果分" not in markdown
    assert "角色任务分" not in markdown
    assert "投票分 0." not in markdown
    assert "硬规则得分原因" not in markdown
    assert "额外分数原因" not in markdown
    assert "分数概览" in markdown
    assert "得分解读" in markdown
    assert "| 维度 | 说明 |" in markdown
    assert "| 类别 | 分值 | 说明 |" in markdown


def test_guard_successful_block_generates_review_bonus_and_turning_point() -> None:
    guard = make_player("P1", "GuardA", Role.GUARD, alive=True)
    wolf_a = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    wolf_b = make_player("P3", "WolfB", Role.WEREWOLF, alive=True)
    seer = make_player("P4", "SeerA", Role.SEER, alive=True)

    state = make_state(
        [guard, wolf_a, wolf_b, seer],
        [
            make_night_action(1, guard, "guard", seer, phase=Phase.NIGHT_GUARD_ACTION),
            make_night_action(1, wolf_a, "attack", seer),
            make_night_action(1, wolf_b, "attack", seer),
            make_speech(1, seer, "I survived the night and still have information."),
        ],
        winner=Alignment.VILLAGE,
        day=1,
    )

    metrics = MetricsCalculator().compute(state)
    guard_bonuses = bonuses_for_player(metrics, guard.id)
    assert any(bonus.bonus_type == "guard_block_kill" for bonus in guard_bonuses)

    report = ReviewReportBuilder().build(state, metrics)
    assert any("守卫挡刀" in point.title for point in report.turning_points)


def test_villager_vote_chain_bonus_appears_after_multiple_correct_votes() -> None:
    villager = make_player("P1", "VillagerA", Role.VILLAGER, alive=True)
    wolf_a = make_player("P2", "WolfA", Role.WEREWOLF, alive=False)
    wolf_b = make_player("P3", "WolfB", Role.WEREWOLF, alive=False)
    seer = make_player("P4", "SeerA", Role.SEER, alive=True)

    state = make_state(
        [villager, wolf_a, wolf_b, seer],
        [
            make_vote(1, villager, wolf_a),
            make_death(1, wolf_a, "vote"),
            make_vote(2, villager, wolf_b),
            make_death(2, wolf_b, "vote"),
        ],
        winner=Alignment.VILLAGE,
        day=2,
    )

    metrics = MetricsCalculator().compute(state)
    villager_bonuses = bonuses_for_player(metrics, villager.id)
    assert any(bonus.bonus_type == "villager_vote_chain" for bonus in villager_bonuses)


def test_no_evidence_no_template_suggestions() -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=True)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=False)
    state = make_state(
        [seer, villager, wolf],
        [
            make_vote(1, seer, wolf),
            make_vote(1, villager, wolf),
            make_death(1, wolf, "vote"),
        ],
        winner=Alignment.VILLAGE,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    assert not report.bad_cases
    assert not report.counterfactuals
    assert not report.strategy_suggestions
    assert all(not review.suggestions for review in report.player_reviews)


def test_each_player_has_at_most_two_suggestions() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    state = make_state(
        [witch, villager, wolf],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    assert all(len(review.suggestions) <= 2 for review in report.player_reviews)


def test_review_report_markdown_does_not_embed_leaderboard_and_metadata_marks_boundary() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [
            make_speech(1, wolf, "SeerA is fake. Vote SeerA."),
            make_vote(1, wolf, seer),
            make_vote(1, villager, seer),
            make_death(1, seer, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    markdown = MarkdownReportRenderer().render(report)

    assert "Persona Leaderboard" not in markdown
    assert "Role Leaderboard" not in markdown
    assert "Version Leaderboard" not in markdown
    assert report.metadata["leaderboard_available"] is True
    assert "LeaderboardAggregator" in report.metadata["leaderboard_note"]
    assert "跨局表现请查看 Leaderboard 输出" in markdown


def test_report_evaluator_rejects_english_enum_markdown() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    report = ReviewReportBuilder().build(
        make_state(
            [wolf, seer, villager],
            [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
            winner=Alignment.WOLF,
        ),
        MetricsCalculator().compute(
            make_state(
                [wolf, seer, villager],
                [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
                winner=Alignment.WOLF,
            )
        ),
    )
    bad_markdown = "# 本局复盘报告\n\n## 1. 本局概览\n- global_mvp\n- Seer\n- DAY_SPEECH\n"
    result = ReportEvaluator().evaluate(report, bad_markdown)
    assert result.grade == "fail"
    assert any("英文枚举" in issue or "英文角色" in issue for issue in result.issues)


def test_report_evaluator_rejects_template_suggestions() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    markdown = MarkdownReportRenderer().render(report) + "\n- 发言更明确\n"
    result = ReportEvaluator().evaluate(report, markdown)
    assert result.grade == "fail"
    assert any("模板化建议" in issue for issue in result.issues)


def test_report_optimizer_retries_after_first_failure() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    class FlakyGenerator:
        def __init__(self) -> None:
            self.calls = 0
            self.good = MarkdownReportRenderer()

        def generate(self, report, feedback="") -> str:
            self.calls += 1
            if self.calls == 1:
                return "# 本局复盘报告\n\n- global_mvp\n- Seer\n- DAY_VOTE\n"
            return self.good.render(report)

    generator = FlakyGenerator()
    optimizer = ReportOptimizer(
        generator=generator, evaluator=ReportEvaluator(), quality_checker=ReviewQualityChecker()
    )
    state_result = optimizer.optimize(report, max_iterations=2)
    assert generator.calls == 2
    assert state_result.iteration == 2
    assert state_result.quality_passed is True


def test_report_optimizer_respects_max_iterations() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    class BadGenerator:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, report, feedback="") -> str:
            self.calls += 1
            return "# bad\nSeer\nglobal_mvp\n"

    generator = BadGenerator()
    optimizer = ReportOptimizer(
        generator=generator, evaluator=ReportEvaluator(), quality_checker=ReviewQualityChecker()
    )
    state_result = optimizer.optimize(report, max_iterations=2)
    assert generator.calls == 2
    assert state_result.iteration == 2
    assert state_result.quality_passed is False


def test_final_quality_gate_is_called() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    class CountingChecker(ReviewQualityChecker):
        def __init__(self) -> None:
            self.calls = 0

        def check(self, report, markdown):
            self.calls += 1
            return super().check(report, markdown)

    checker = CountingChecker()
    optimizer = ReportOptimizer(
        generator=ReportGenerator(review_llm=MockReviewLLM()), evaluator=ReportEvaluator(), quality_checker=checker
    )
    optimizer.optimize(report, max_iterations=2)
    assert checker.calls == 1


def test_report_optimizer_does_not_modify_scores_or_mvp() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    original_scores = [(item["player_name"], item["adjusted_final_score"]) for item in report.scoreboard]
    original_mvp = [(item.player_name, item.mvp_type, item.mvp_score) for item in report.mvp_results]
    state_result = ReportOptimizer(generator=ReportGenerator(review_llm=MockReviewLLM())).optimize(report)
    assert [(item["player_name"], item["adjusted_final_score"]) for item in report.scoreboard] == original_scores
    assert [(item.player_name, item.mvp_type, item.mvp_score) for item in report.mvp_results] == original_mvp
    assert state_result.final_markdown


def test_mock_review_llm_pipeline_runs_without_real_llm() -> None:
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
    state_result = optimizer.optimize(report)
    assert state_result.final_markdown.startswith("# 本局复盘报告")
    assert state_result.feedback_history


def test_b_full_spec_report_has_validation_result_and_single_game_evidence(tmp_path) -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)
    state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "Need more discussion before I vote."),
            make_vote(1, seer, villager),
            make_vote(1, wolf, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )

    from backend.eval.review import generate_review_report

    payload = generate_review_report(
        state,
        json_path=tmp_path / "review.json",
        markdown_path=tmp_path / "review.md",
    )
    report = payload["report"]
    markdown = payload["final_markdown"]
    validation = report["metadata"]["validation_result"]

    assert validation["passed"] is True
    assert validation["publish_allowed"] is True
    assert payload["quality_passed"] is True
    assert report["scoreboard"]
    assert report["mvp_results"]
    assert report["bad_cases"]
    assert report["counterfactuals"]
    assert report["strategy_suggestions"]
    assert "本局复盘报告" in markdown
    assert "玩家评分榜" in markdown
    assert "反事实推演" in markdown
    assert "SeerA" in markdown
    assert "WolfA" in markdown
    assert json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert (tmp_path / "review.md").read_text(encoding="utf-8") == markdown


def test_b_quality_checker_rejects_missing_sections_and_score_drift() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    bad_markdown = "# 本局复盘报告\n\n## 1. 本局概览\n- global_mvp\n"

    result = ReviewQualityChecker().check(report, bad_markdown)
    assert result.grade == "fail"
    assert any("缺少章节" in issue for issue in result.issues)
    assert any("英文枚举" in issue for issue in result.issues)


def test_b_counterfactual_soundness_marks_info_release_estimated() -> None:
    seer = make_player("P1", "SeerA", Role.SEER, alive=True)
    wolf = make_player("P2", "WolfA", Role.WEREWOLF, alive=True)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=False)
    state = make_state(
        [seer, wolf, villager],
        [
            make_seer_result(1, seer, wolf, is_wolf=True),
            make_speech(1, seer, "Need more discussion before I vote."),
            make_vote(1, seer, villager),
            make_vote(1, wolf, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    info_cases = counterfactuals_by_type(report, "info_release")

    assert info_cases
    assert all(case.confidence < 1.0 for case in info_cases)
    assert all(
        "expected" in case.expected_effect.lower() or "would likely" in case.expected_effect.lower()
        for case in info_cases
    )


def test_b_strategy_suggestions_are_grounded_in_review_items() -> None:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    state = make_state(
        [witch, villager, wolf],
        [
            make_night_action(1, witch, "witch_poison", villager),
            make_death(1, villager, "poison"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))

    assert report.strategy_suggestions
    assert all(item.source for item in report.strategy_suggestions)
    assert all(item.metadata.get("evidence_summary") for item in report.strategy_suggestions)
    assert any(
        item.metadata.get("source_type") in {"bad_case", "counterfactual"} for item in report.strategy_suggestions
    )


def test_create_report_optimizer_falls_back_when_langgraph_unavailable() -> None:
    optimizer = create_report_optimizer()
    if LANGGRAPH_AVAILABLE:
        assert isinstance(optimizer, LangGraphReportOptimizer)
    else:
        assert isinstance(optimizer, ReportOptimizer)


@pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph is not installed")
def test_langgraph_report_optimizer_can_compile_and_invoke() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    optimizer = LangGraphReportOptimizer(generator=ReportGenerator(review_llm=MockReviewLLM()))
    result = optimizer.optimize(report, max_iterations=2)
    assert result.final_markdown.startswith("# 本局复盘报告")
    assert result.feedback_history


@pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph is not installed")
def test_langgraph_report_optimizer_matches_plain_optimizer_core_output() -> None:
    wolf = make_player("P1", "WolfA", Role.WEREWOLF, alive=True)
    seer = make_player("P2", "SeerA", Role.SEER, alive=False)
    villager = make_player("P3", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf, seer, villager],
        [make_vote(1, wolf, seer), make_vote(1, villager, seer), make_death(1, seer, "vote")],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    plain = ReportOptimizer(generator=ReportGenerator(review_llm=MockReviewLLM())).optimize(report, max_iterations=2)
    graph = LangGraphReportOptimizer(generator=ReportGenerator(review_llm=MockReviewLLM())).optimize(
        report, max_iterations=2
    )
    assert graph.quality_passed == plain.quality_passed
    assert graph.final_markdown == plain.final_markdown


def test_review_pipeline_exposes_wolf_team_internal_votes() -> None:
    wolf1 = make_player("P1", "WolfOne", Role.WEREWOLF, alive=True)
    wolf2 = make_player("P2", "WolfTwo", Role.WEREWOLF, alive=True)
    seer = make_player("P3", "SeerA", Role.SEER, alive=False)
    villager = make_player("P4", "VillagerA", Role.VILLAGER, alive=True)
    state = make_state(
        [wolf1, wolf2, seer, villager],
        [
            GameEvent.create(
                day=1,
                phase=Phase.NIGHT_WOLF_ACTION,
                type=EventType.PRIVATE_INFO,
                visibility="private",
                payload={
                    "kind": "wolf_attack_tally",
                    "target_id": seer.id,
                    "target_name": seer.name,
                    "votes": {wolf1.id: seer.id, wolf2.id: seer.id},
                },
                visible_to=[wolf1.id, wolf2.id],
            ),
            make_night_action(1, wolf1, "attack", seer),
            make_night_action(1, wolf2, "attack", seer),
            make_death(1, seer, "wolf"),
        ],
        winner=Alignment.WOLF,
    )
    metrics = MetricsCalculator().compute(state)
    assert metrics.metadata["wolf_team_votes"]
    assert metrics.metadata["wolf_team_votes"][0]["unanimous"] is True

    report = ReviewReportBuilder().build(state, metrics)
    assert report.metadata["wolf_team_votes"]
    assert report.metadata["wolf_team_votes"][0]["target_name"] == "SeerA"
