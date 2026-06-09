"""Track C acceptance verification — 13 criteria from docs/Track_C_Evolution_Agent_Plan.md §25.

Each test is labelled C1–C13 matching the final acceptance criteria. This script
answers: "Is Track C a production-ready, end-to-end self-evolution pipeline?"
"""

from __future__ import annotations

import json

import pytest

from backend.engine.models import Alignment
from backend.engine.models import Role
from backend.eval.evolution import ABComparison
from backend.eval.evolution import AcceptancePolicy
from backend.eval.evolution import DreamJob
from backend.eval.evolution import EvolutionPipeline
from backend.eval.evolution import KnowledgeDocValidator
from backend.eval.evolution import PatchOperation
from backend.eval.evolution import PatchValidator
from backend.eval.evolution import RoleStrategyCard
from backend.eval.evolution import StrategyContextRenderer
from backend.eval.evolution import StrategyKnowledgeDoc
from backend.eval.evolution import StrategyKnowledgeDocExtractor
from backend.eval.evolution import StrategyKnowledgeStore
from backend.eval.evolution import StrategyPatch
from backend.eval.evolution import StrategyRetrievalQuery
from backend.eval.evolution import TournamentRunner
from backend.eval.evolution import VersionManager
from backend.eval.evolution import export_evolution_summary
from backend.eval.review import GameMetrics
from backend.eval.review import MetricsCalculator
from backend.eval.review import PlayerScore
from backend.eval.review import ReviewReport
from backend.eval.review import ReviewReportBuilder
from tests.test_review_metrics import make_death
from tests.test_review_metrics import make_player
from tests.test_review_metrics import make_seer_result
from tests.test_review_metrics import make_speech
from tests.test_review_metrics import make_state
from tests.test_review_metrics import make_vote

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _approved_seer_report() -> ReviewReport:
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
    report.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}
    return report


def _approved_witch_report() -> ReviewReport:
    witch = make_player("P1", "WitchA", Role.WITCH, alive=True)
    villager = make_player("P2", "VillagerA", Role.VILLAGER, alive=False)
    wolf = make_player("P3", "WolfA", Role.WEREWOLF, alive=True)
    state = make_state(
        [witch, villager, wolf],
        [
            make_speech(1, witch, "VillagerA is suspicious."),
            make_vote(1, witch, villager),
            make_vote(1, wolf, villager),
            make_death(1, villager, "vote"),
        ],
        winner=Alignment.WOLF,
    )
    report = ReviewReportBuilder().build(state, MetricsCalculator().compute(state))
    report.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}
    return report


def _rejected_report() -> ReviewReport:
    report = _approved_seer_report()
    report.game_id = "rejected-game"
    report.metadata["validation_result"] = {"passed": False, "publish_allowed": False, "score": 0.0}
    return report


def _metrics(
    version: str, score: float, role_task: float, *, critical: bool = False, winner: str = "village"
) -> GameMetrics:
    return GameMetrics(
        game_id=f"{version}-{score}",
        winner=winner,
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
                "Seer",
                "village",
                1.0 if winner == "village" else 0.0,
                role_task,
                0.8,
                0.8,
                0.8,
                1.0,
                0.0,
                score,
                adjusted_final_score=score,
                mistakes=["[critical] miss"] if critical else [],
            )
        ],
        metadata={"strategy_version": version, "info_leak_count": 0, "invalid_action_rate": 0.0},
    )


def _role_metrics(
    version: str,
    role: str,
    alignment: str,
    winner: str,
    score: float = 60.0,
    role_task: float = 0.5,
) -> GameMetrics:
    return GameMetrics(
        game_id=f"{version}-{role}-{winner}-{score}",
        winner=winner,
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
                role,
                alignment,
                1.0 if winner == alignment else 0.0,
                role_task,
                0.8,
                0.8,
                0.8,
                1.0,
                0.0,
                score,
                adjusted_final_score=score,
            )
        ],
        metadata={
            "strategy_version": version,
            "target_role": role,
            "info_leak_count": 0,
            "invalid_action_rate": 0.0,
        },
    )


# ---------------------------------------------------------------------------
# C1: 能从 B 的 ApprovedReviewReport 中抽象策略知识
# ---------------------------------------------------------------------------
def test_c1_strategy_knowledge_abstracted_from_approved_reports() -> None:
    approved = _approved_seer_report()
    rejected = _rejected_report()

    extractor = StrategyKnowledgeDocExtractor()
    docs = extractor.extract([approved, rejected])

    assert docs
    # Only the approved report should contribute
    assert all(doc.source_report_ids == [approved.game_id] for doc in docs)
    for doc in docs:
        assert doc.doc_type in {"good_play", "bad_case_lesson", "counterfactual_lesson"}
        assert doc.role in {Role.SEER.value, "global"}
        assert doc.quality_score > 0
        assert doc.confidence > 0
        assert doc.trigger_conditions
        assert doc.recommended_action
        assert doc.source_report_ids


# ---------------------------------------------------------------------------
# C2: 知识条目去除了具体历史玩家依赖
# ---------------------------------------------------------------------------
def test_c2_knowledge_sanitized_no_player_leaks() -> None:
    report = _approved_seer_report()
    docs = StrategyKnowledgeDocExtractor().extract([report])

    assert docs
    validator = KnowledgeDocValidator()
    for doc in docs:
        issues = validator.validate(doc)
        assert not issues

    blob = " ".join(f"{doc.situation_pattern} {doc.recommended_action} {doc.rationale}" for doc in docs)
    for name in {"SeerA", "WolfA", "VillagerA"}:
        assert name not in blob
    assert "P1" not in blob
    assert "P2" not in blob
    assert "P3" not in blob
    assert "hidden identity" not in blob.lower()
    assert "private_reason" not in blob.lower()


# ---------------------------------------------------------------------------
# C3: 知识库支持按角色、阶段、局势检索
# ---------------------------------------------------------------------------
def test_c3_knowledge_store_role_phase_situation_retrieval() -> None:
    doc = StrategyKnowledgeDoc(
        doc_id="c3-doc-1",
        doc_type="counterfactual_lesson",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="When the Seer holds a wolf check and villagers are under vote pressure.",
        trigger_conditions=["wolf_check_unreleased", "good_under_pressure"],
        recommended_action="Publicly convert the wolf check into explicit vote guidance.",
        avoid_action="Withhold the check and vote vaguely.",
        rationale="Hidden checks consistently led to misvotes.",
        evidence_summary="Approved report evidence shows clear counterfactual impact.",
        source_report_ids=["g1"],
        source_item_ids=["cf1"],
        source_event_ids=[],
        counterfactual_ids=["cf1"],
        expected_metric_effects=[{"metric": "vote_accuracy", "direction": "increase"}],
        quality_score=0.9,
        confidence=0.85,
        status="active",
        tags=["seer", "info_release", "counterfactual"],
    )
    doc_villager = StrategyKnowledgeDoc(
        doc_id="c3-doc-2",
        doc_type="good_play",
        role="Villager",
        phase="DAY_VOTE",
        persona_scope=None,
        situation_pattern="When the Villager needs to decide between competing wagons.",
        trigger_conditions=["close_vote"],
        recommended_action="Check public vote history and align with confirmed good players.",
        avoid_action=None,
        rationale="Evidence shows village wins depend on coordinated voting.",
        evidence_summary="Good play evidence.",
        source_report_ids=["g2"],
        source_item_ids=["bp1"],
        source_event_ids=[],
        counterfactual_ids=[],
        expected_metric_effects=[{"metric": "vote_accuracy", "direction": "increase"}],
        quality_score=0.7,
        confidence=0.7,
        status="active",
        tags=["villager", "vote"],
    )
    store = StrategyKnowledgeStore([doc, doc_villager])

    # Role match
    seer_results = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer", phase="DAY_SPEECH", observation_summary="I have a wolf check and need to create vote pressure"
        )
    )
    assert seer_results
    assert seer_results[0].doc_id == "c3-doc-1"

    # Phase filter
    villager_results = store.retrieve(
        StrategyRetrievalQuery(role="Villager", phase="DAY_VOTE", observation_summary="Close vote coming")
    )
    assert villager_results
    assert villager_results[0].doc_id == "c3-doc-2"

    # Situation tag overlap boost
    tagged_results = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="Need info release",
            situation_tags=["wolf_check_unreleased"],
        )
    )
    assert tagged_results

    # Wrong role should get nothing
    no_results = store.retrieve(
        StrategyRetrievalQuery(role="Hunter", phase="DAY_SPEECH", observation_summary="Any advice?")
    )
    assert not no_results

    assert store.get("c3-doc-1").usage_count == 2  # used by two queries


# ---------------------------------------------------------------------------
# C4: Knowledge usage feedback updates quality scores
# ---------------------------------------------------------------------------
def test_c4_knowledge_usage_feedback_updates_scores() -> None:
    doc = StrategyKnowledgeDoc(
        doc_id="c4-doc",
        doc_type="good_play",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="Pattern",
        trigger_conditions=["t1"],
        recommended_action="Do X.",
        avoid_action=None,
        rationale="Because.",
        evidence_summary="OK",
        source_report_ids=["g1"],
        source_item_ids=[],
        source_event_ids=[],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=0.7,
        confidence=0.7,
        status="active",
    )
    store = StrategyKnowledgeStore([doc])

    # Mark as helpful
    store.update_usage("c4-doc", helpful=True)
    assert store.get("c4-doc").success_count == 1
    assert store.get("c4-doc").failure_count == 0

    # Mark as unhelpful — but with a prior success, status stays active
    store.update_usage("c4-doc", helpful=False)
    assert store.get("c4-doc").failure_count == 1
    assert store.get("c4-doc").status == "active"  # had prior success
    assert store.get("c4-doc").quality_score < 0.7  # quality dropped due to failure

    # Create a fresh doc with no successes — 3 failures should deprecate
    doc2 = StrategyKnowledgeDoc(
        doc_id="c4-doc2",
        doc_type="good_play",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="P2",
        trigger_conditions=["t1"],
        recommended_action="Do Y.",
        avoid_action=None,
        rationale="R2",
        evidence_summary="OK",
        source_report_ids=["g2"],
        source_item_ids=[],
        source_event_ids=[],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=0.7,
        confidence=0.7,
        status="active",
    )
    store.upsert(doc2)
    store.update_usage("c4-doc2", helpful=False)
    store.update_usage("c4-doc2", helpful=False)
    store.update_usage("c4-doc2", helpful=False)
    assert store.get("c4-doc2").failure_count == 3
    assert store.get("c4-doc2").success_count == 0
    assert store.get("c4-doc2").status == "deprecated"

    # Deprecated docs should not appear in retrieval
    results = store.retrieve(StrategyRetrievalQuery(role="Seer", phase="DAY_SPEECH", observation_summary="pattern"))
    assert all(r.doc_id != "c4-doc2" for r in results)  # deprecated excluded


# ---------------------------------------------------------------------------
# C5: 多局后 DreamJob 能聚合重复失误和高光
# ---------------------------------------------------------------------------
def test_c5_dream_job_aggregates_multiple_reports() -> None:
    seer_report = _approved_seer_report()
    witch_report = _approved_witch_report()
    manager = VersionManager(
        [
            RoleStrategyCard(role="Seer", version="seer_v1", goal="Seer mission."),
            RoleStrategyCard(role="Witch", version="witch_v1", goal="Witch mission."),
        ]
    )
    result = DreamJob(version_manager=manager).run([seer_report, witch_report])
    assert result.knowledge_docs
    assert result.candidate_patches
    assert result.summary.source_reports == 2
    assert result.summary.knowledge_docs_created == len(result.knowledge_docs)
    assert result.summary.candidate_patches_created == len(result.candidate_patches)
    for patch in result.candidate_patches:
        assert patch.source_report_ids
        assert patch.source_knowledge_doc_ids


# ---------------------------------------------------------------------------
# C6: 系统能生成 StrategyPatch
# ---------------------------------------------------------------------------
def test_c6_strategy_patch_generation() -> None:
    report = _approved_seer_report()
    manager = VersionManager([RoleStrategyCard(role="Seer", version="seer_v1", goal="Seer mission.")])
    result = DreamJob(version_manager=manager).run([report])
    assert result.candidate_patches
    patch = result.candidate_patches[0]
    assert patch.patch_type == "role_strategy"
    assert patch.target_role == "Seer"
    assert patch.from_version == "seer_v1"
    assert patch.to_version.startswith("seer_v")
    assert patch.source_report_ids
    assert patch.source_knowledge_doc_ids
    assert patch.operations
    for op in patch.operations:
        assert op.op in {"add", "update", "remove", "deprecate", "promote"}
        assert op.section in {
            "speech_policy",
            "vote_policy",
            "skill_policy",
            "risk_rules",
            "compensation_rules",
            "retrieval_policy",
        }
        assert op.new_value
        assert op.rationale


# ---------------------------------------------------------------------------
# C7: PatchValidator 能拒绝非法 patch
# ---------------------------------------------------------------------------
def test_c7_patch_validator_rejects_illegal_patches() -> None:
    validator = PatchValidator()

    # Reject: modifies visibility
    bad_patch = StrategyPatch(
        patch_id="p-bad",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2",
        source_report_ids=[],
        source_knowledge_doc_ids=[],
        source_evidence_ids=[],
        operations=[PatchOperation("add", "skill_policy", "Always read hidden role.", "no evidence")],
        expected_effects=[],
    )
    bad_result = validator.validate(bad_patch)
    assert not bad_result.passed

    # Reject: no source knowledge
    no_kb_patch = StrategyPatch(
        patch_id="p-nokb",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2",
        source_report_ids=[],
        source_knowledge_doc_ids=[],
        source_evidence_ids=[],
        operations=[PatchOperation("add", "speech_policy", "Speak clearly.", "evidence")],
        expected_effects=[],
    )
    no_kb_result = validator.validate(no_kb_patch)
    assert not no_kb_result.passed

    # Reject: too many operations
    many_patch = StrategyPatch(
        patch_id="p-many",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2",
        source_report_ids=["g1"],
        source_knowledge_doc_ids=["d1", "d2", "d3", "d4"],
        source_evidence_ids=[],
        operations=[
            PatchOperation("add", "speech_policy", "Rule 1", "evidence 1"),
            PatchOperation("add", "speech_policy", "Rule 2", "evidence 2"),
            PatchOperation("add", "speech_policy", "Rule 3", "evidence 3"),
            PatchOperation("add", "speech_policy", "Rule 4", "evidence 4"),
        ],
        expected_effects=[],
    )
    many_result = validator.validate(many_patch)
    assert not many_result.passed or any("too many" in issue.message.lower() for issue in many_result.issues)

    # Accept: valid patch
    good_patch = StrategyPatch(
        patch_id="p-good",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2_candidate",
        source_report_ids=["g1"],
        source_knowledge_doc_ids=["d1"],
        source_evidence_ids=["e1"],
        operations=[
            PatchOperation(
                "add",
                "speech_policy",
                "Release wolf checks publicly when vote pressure matters.",
                "Approved report evidence shows this improves conversion.",
            )
        ],
        expected_effects=[{"metric": "vote_accuracy", "direction": "increase"}],
    )
    good_result = validator.validate(good_patch)
    assert good_result.passed


# ---------------------------------------------------------------------------
# C8: VersionManager 能创建 candidate 版本
# ---------------------------------------------------------------------------
def test_c8_version_manager_creates_candidate_and_manages_lifecycle() -> None:
    manager = VersionManager([RoleStrategyCard(role="Seer", version="seer_v1", goal="Seer mission.")])
    patch = StrategyPatch(
        patch_id="p-vm",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2_candidate",
        source_report_ids=["g1"],
        source_knowledge_doc_ids=["d1"],
        source_evidence_ids=["e1"],
        operations=[PatchOperation("add", "speech_policy", "Release wolf checks.", "approved evidence")],
        expected_effects=[],
    )

    # Create candidate
    candidate = manager.create_candidate(patch)
    assert candidate.status == "candidate"
    assert candidate.card.version == "seer_v2_candidate"
    assert candidate.parent == "seer_v1"
    assert "Release wolf checks." in candidate.card.speech_policy

    # Promote
    promoted = manager.promote("seer_v2_candidate")
    assert promoted.status == "promoted"
    assert promoted.card.status == "active"
    assert manager.active_card("Seer").version == "seer_v2_candidate"

    # Rollback
    rolled = manager.rollback("seer_v2_candidate")
    assert rolled.status == "rolled_back"
    assert manager.active_card("Seer").version == "seer_v1"

    # History always complete
    history = manager.history()
    assert len(history) >= 2


# ---------------------------------------------------------------------------
# C9: TournamentRunner 能跑对比并计算统计量
# ---------------------------------------------------------------------------
def test_c9_tournament_runner_compares_metrics() -> None:
    baseline = [_metrics("seer_v1", 60.0, 0.50, critical=True), _metrics("seer_v1", 62.0, 0.52, critical=True)]
    candidate = [_metrics("seer_v2", 72.0, 0.70), _metrics("seer_v2", 74.0, 0.72)]

    comparison = TournamentRunner().compare_metrics("seer_v1", "seer_v2", baseline, candidate)
    assert comparison.baseline_version == "seer_v1"
    assert comparison.candidate_version == "seer_v2"
    assert comparison.total_games == 2
    assert comparison.baseline_wins >= 0
    assert comparison.candidate_wins >= 0
    assert comparison.baseline_avg_score < comparison.candidate_avg_score
    assert comparison.target_role_avg_score_delta > 0
    assert comparison.role_task_score_delta > 0
    assert comparison.critical_mistakes_delta < 0  # candidate has fewer mistakes
    assert comparison.info_leak_count == 0
    assert comparison.invalid_action_rate == 0.0


def test_c9_tournament_runner_counts_wins_for_target_role_alignment() -> None:
    baseline = [
        _role_metrics("wolf_v1", "Werewolf", "wolf", "village"),
        _role_metrics("wolf_v1", "Werewolf", "wolf", "wolf"),
    ]
    candidate = [
        _role_metrics("wolf_v2", "Werewolf", "wolf", "wolf"),
        _role_metrics("wolf_v2", "Werewolf", "wolf", "wolf"),
    ]

    comparison = TournamentRunner().compare_metrics("wolf_v1", "wolf_v2", baseline, candidate)

    assert comparison.baseline_wins == 1
    assert comparison.candidate_wins == 2


def test_c9b_tournament_runner_runs_real_fixed_20_seed_games() -> None:
    runner = TournamentRunner()

    tournament = runner.run_ab_tournament(
        baseline_version="seer_v1",
        candidate_version="seer_v2_candidate",
        target_role="Seer",
        seeds=list(range(1, 21)),
    )

    assert tournament.seeds == list(range(1, 21))
    assert len(tournament.baseline_results) == 20
    assert len(tournament.candidate_results) == 20
    assert tournament.comparison["total_games"] == 20
    assert tournament.comparison["candidate_fallback_count"] == 0
    assert all(item["metadata"]["tournament_seed"] in tournament.seeds for item in tournament.baseline_results)
    assert all(item["metadata"]["strategy_version"] == "seer_v2_candidate" for item in tournament.candidate_results)

    with pytest.raises(ValueError):
        runner.run_ab_tournament(
            baseline_version="seer_v1",
            candidate_version="seer_v2_candidate",
            target_role="Seer",
            seeds=[1, 2],
        )


# ---------------------------------------------------------------------------
# C10: AcceptancePolicy 能 promote 或 rollback
# ---------------------------------------------------------------------------
def test_c10_acceptance_policy_promotes_or_rejects() -> None:
    policy = AcceptancePolicy()

    # Should accept: clear improvement
    comparison_good = ABComparison(
        baseline_version="v1",
        candidate_version="v2",
        total_games=2,
        baseline_wins=0,
        candidate_wins=0,
        baseline_avg_score=61.0,
        candidate_avg_score=73.0,
        target_role_avg_score_delta=19.67,
        role_task_score_delta=40.0,
        critical_mistakes_delta=-0.5,
        info_leak_count=0,
        invalid_action_rate=0.0,
    )
    decision_good = policy.decide(comparison_good)
    assert decision_good.accepted
    assert "no information leaks" in decision_good.satisfied_conditions
    assert "no invalid actions" in decision_good.satisfied_conditions

    # Should reject: info leak
    comparison_leak = ABComparison(
        baseline_version="v1",
        candidate_version="v2",
        total_games=2,
        baseline_wins=0,
        candidate_wins=2,
        baseline_avg_score=61.0,
        candidate_avg_score=73.0,
        target_role_avg_score_delta=19.0,
        role_task_score_delta=40.0,
        critical_mistakes_delta=-0.5,
        info_leak_count=1,
        invalid_action_rate=0.0,
    )
    decision_leak = policy.decide(comparison_leak)
    assert not decision_leak.accepted

    # Should reject: any candidate fallback means the A/B result is not a valid
    # proof of strategy quality.
    comparison_fallback = ABComparison(
        baseline_version="v1",
        candidate_version="v2",
        total_games=2,
        baseline_wins=0,
        candidate_wins=2,
        baseline_avg_score=61.0,
        candidate_avg_score=73.0,
        target_role_avg_score_delta=19.0,
        role_task_score_delta=40.0,
        critical_mistakes_delta=-0.5,
        info_leak_count=0,
        invalid_action_rate=0.0,
        candidate_fallback_count=1,
    )
    decision_fallback = policy.decide(comparison_fallback)
    assert not decision_fallback.accepted

    # Should reject: overall score and mistakes improved, but the candidate
    # degrades the patched role's core task score.
    comparison_role_task_regress = ABComparison(
        baseline_version="v1",
        candidate_version="v2",
        total_games=2,
        baseline_wins=0,
        candidate_wins=2,
        baseline_avg_score=61.0,
        candidate_avg_score=73.0,
        target_role_avg_score_delta=19.0,
        role_task_score_delta=-1.0,
        critical_mistakes_delta=-0.5,
        info_leak_count=0,
        invalid_action_rate=0.0,
    )
    decision_role_task_regress = policy.decide(comparison_role_task_regress)
    assert not decision_role_task_regress.accepted
    assert "role_task_score_delta must be non-negative" in decision_role_task_regress.failed_conditions

    # Should reject: regression
    comparison_regress = ABComparison(
        baseline_version="v1",
        candidate_version="v2",
        total_games=2,
        baseline_wins=2,
        candidate_wins=0,
        baseline_avg_score=80.0,
        candidate_avg_score=50.0,
        target_role_avg_score_delta=-37.5,
        role_task_score_delta=-20.0,
        critical_mistakes_delta=0.5,
        info_leak_count=0,
        invalid_action_rate=0.0,
    )
    decision_regress = policy.decide(comparison_regress)
    assert not decision_regress.accepted


# ---------------------------------------------------------------------------
# C11: Leaderboard 能展示 v1 vs v2 差异
# ---------------------------------------------------------------------------
def test_c11_leaderboard_shows_version_differences() -> None:
    metrics_v1 = [_metrics("v1", 60.0, 0.50), _metrics("v1", 62.0, 0.52)]
    metrics_v2 = [_metrics("v2", 72.0, 0.70), _metrics("v2", 74.0, 0.72)]

    from backend.eval.review import LeaderboardAggregator

    result = LeaderboardAggregator().aggregate_version(metrics_v1 + metrics_v2)
    assert result.leaderboard_type == "version"
    entries = {entry.key: entry for entry in result.entries}
    assert "v2" in entries
    assert "v1" in entries
    assert entries["v2"].win_rate >= entries["v1"].win_rate
    assert entries["v2"].avg_adjusted_final_score > entries["v1"].avg_adjusted_final_score


# ---------------------------------------------------------------------------
# C12: 所有进化记录可追溯到 B 的报告和证据链
# ---------------------------------------------------------------------------
def test_c12_evolution_records_traceable_to_b_reports(tmp_path) -> None:
    report = _approved_seer_report()
    manager = VersionManager([RoleStrategyCard(role="Seer", version="seer_v1", goal="Seer mission.")])
    result = DreamJob(version_manager=manager).run([report])

    for doc in result.knowledge_docs:
        assert doc.source_report_ids
        assert doc.evidence_summary
        assert doc.source_item_ids

    for patch in result.candidate_patches:
        assert patch.source_report_ids
        assert patch.source_knowledge_doc_ids
        for op in patch.operations:
            assert op.rationale

    summary = EvolutionPipeline().run(
        [report],
        baseline_metrics=[_metrics("seer_v1", 60.0, 0.50)],
        candidate_metrics=[_metrics("seer_v2", 72.0, 0.70)],
        summary_path=tmp_path / "traceable_summary.json",
    )
    assert summary.approved_report_count > 0
    payload = json.loads((tmp_path / "traceable_summary.json").read_text(encoding="utf-8"))
    assert payload["approved_report_count"] == summary.approved_report_count
    assert payload["knowledge_doc_count"] == summary.knowledge_doc_count


# ---------------------------------------------------------------------------
# C13: 完整 Evolution Pipeline 输出 evolution_summary.json 且可导出
# ---------------------------------------------------------------------------
def test_c13_full_evolution_pipeline_produces_complete_summary(tmp_path) -> None:
    seer_report = _approved_seer_report()
    witch_report = _approved_witch_report()
    baseline = [_metrics("v1", 60.0, 0.50, critical=True), _metrics("v1", 62.0, 0.52, critical=True)]
    candidate = [_metrics("v2_candidate", 72.0, 0.70), _metrics("v2_candidate", 74.0, 0.72)]

    summary = EvolutionPipeline().run(
        [seer_report, witch_report],
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        summary_path=tmp_path / "evolution_summary.json",
    )

    assert summary.approved_report_count == 2
    assert summary.knowledge_doc_count > 0
    assert summary.candidate_patch_count > 0
    assert summary.promoted_versions or summary.rolled_back_versions

    exported = export_evolution_summary(summary, tmp_path / "exported_summary.json")
    assert json.loads(json.dumps(exported, ensure_ascii=False))
    assert exported["approved_report_count"] == 2
    assert "leaderboard" in exported
    assert exported["leaderboard"] is not None


# ---------------------------------------------------------------------------
# C14: StrategyContextRenderer produces LLM-prompt-safe block
# ---------------------------------------------------------------------------
def test_c14_strategy_context_renderer_prompt_block() -> None:
    renderer = StrategyContextRenderer()
    result = renderer.render_lessons([])
    assert result == ""

    result = renderer.render_lessons(
        [
            type(
                "L",
                (),
                {
                    "recommendation": "Release wolf checks into public vote pressure.",
                    "trigger": "When the Seer has a wolf check and village votes are split.",
                    "rationale": "Approved report evidence shows hidden checks cause misvotes.",
                    "doc_id": "doc-1",
                },
            )(),
        ]
    )
    assert "=== Retrieved Lessons ===" in result
    assert "doc-1" in result
    assert "Release wolf checks" in result


# ---------------------------------------------------------------------------
# C15: Real engine game → B review → C evolution full pipeline
# ---------------------------------------------------------------------------
def test_c15_real_engine_full_b_to_c_pipeline(tmp_path) -> None:
    from backend.engine.game import WerewolfGame

    game1 = WerewolfGame(seed=7)
    game1.play()
    game2 = WerewolfGame(seed=13)
    game2.play()

    reports: list[ReviewReport] = []
    all_metrics: list[GameMetrics] = []
    for game in [game1, game2]:
        state = game.state
        metrics = MetricsCalculator().compute(state)
        all_metrics.append(metrics)
        report = ReviewReportBuilder().build(state, metrics)
        report.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.0}
        reports.append(report)

    summary = EvolutionPipeline().run(
        reports,
        baseline_metrics=all_metrics[:1],
        candidate_metrics=all_metrics[1:],
        summary_path=tmp_path / "real_evolution_summary.json",
    )

    assert summary.approved_report_count == 2
    assert summary.knowledge_doc_count > 0

    exported = export_evolution_summary(summary, tmp_path / "exported.json")
    assert json.loads(json.dumps(exported, ensure_ascii=False))
