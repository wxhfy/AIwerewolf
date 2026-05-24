from __future__ import annotations

import json

from backend.engine.models import Alignment, Role
from backend.eval.evolution import (
    AcceptancePolicy,
    DreamJob,
    EvolutionPipeline,
    KnowledgeDocValidator,
    PatchOperation,
    PatchValidator,
    RoleStrategyCard,
    StrategyContextRenderer,
    StrategyKnowledgeDoc,
    StrategyKnowledgeDocExtractor,
    StrategyKnowledgeStore,
    StrategyPatch,
    StrategyRetrievalQuery,
    TournamentRunner,
    VersionManager,
    export_evolution_summary,
    load_strategy_knowledge,
)
from backend.eval.review import GameMetrics, MetricsCalculator, PlayerScore, ReviewReportBuilder
from tests.test_review_metrics import make_death, make_player, make_seer_result, make_speech, make_state, make_vote


def _approved_report():
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


def _metrics(version: str, score: float, role_task: float, *, critical: bool = False, winner: str = "village") -> GameMetrics:
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


def test_c_extracts_sanitized_docs_only_from_approved_reports() -> None:
    approved = _approved_report()
    rejected = _approved_report()
    rejected.game_id = "rejected"
    rejected.metadata["validation_result"] = {"passed": False, "publish_allowed": False}

    docs = StrategyKnowledgeDocExtractor().extract([approved, rejected])
    assert docs
    assert all(doc.source_report_ids == [approved.game_id] for doc in docs)
    blob = " ".join(f"{doc.situation_pattern} {doc.recommended_action} {doc.evidence_summary}" for doc in docs)
    assert "SeerA" not in blob
    assert "WolfA" not in blob
    assert "VillagerA" not in blob
    assert all(not KnowledgeDocValidator().validate(doc) for doc in docs)


def test_knowledge_store_retrieves_by_role_phase_and_updates_usage(tmp_path) -> None:
    doc = StrategyKnowledgeDoc(
        doc_id="doc-1",
        doc_type="counterfactual_lesson",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="When the Seer holds a wolf check and villagers are under pressure.",
        trigger_conditions=["wolf_check_unreleased"],
        recommended_action="Publicly convert the check into vote pressure.",
        avoid_action=None,
        rationale="Evidence showed hidden checks created misvotes.",
        evidence_summary="Approved report evidence.",
        source_report_ids=["g1"],
        source_item_ids=["cf1"],
        source_event_ids=[],
        counterfactual_ids=["cf1"],
        expected_metric_effects=[{"metric": "speech_semantic_score", "direction": "increase"}],
        quality_score=0.9,
        confidence=0.85,
        status="active",
        tags=["seer", "info_release"],
    )
    store = StrategyKnowledgeStore([doc])
    lessons = store.retrieve(StrategyRetrievalQuery(role="Seer", phase="DAY_SPEECH", observation_summary="I have a wolf check and need vote pressure"))
    assert lessons[0].doc_id == "doc-1"
    assert store.get("doc-1").usage_count == 1

    store.update_usage("doc-1", helpful=True)
    assert store.get("doc-1").success_count == 1

    path = tmp_path / "knowledge.json"
    store.to_json(path)
    loaded = load_strategy_knowledge(path)
    assert loaded.get("doc-1") is not None


def test_dream_job_generates_valid_candidate_patch_and_version() -> None:
    report = _approved_report()
    manager = VersionManager([RoleStrategyCard(role="Seer", version="seer_v1", goal="Convert information into village wins.")])
    dream = DreamJob(version_manager=manager)

    result = dream.run([report])
    assert result.knowledge_docs
    assert result.candidate_patches
    assert all(patch.status == "applied" for patch in result.candidate_patches)
    candidate_versions = [version for version in manager.history() if version.status == "candidate"]
    assert candidate_versions
    assert any("public" in " ".join(version.card.speech_policy + version.card.skill_policy).lower() for version in candidate_versions)


def test_patch_validator_rejects_rule_visibility_and_absolute_changes() -> None:
    patch = StrategyPatch(
        patch_id="patch-bad",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2_candidate",
        source_report_ids=["g1"],
        source_knowledge_doc_ids=["doc-1"],
        source_evidence_ids=[],
        operations=[
            PatchOperation(
                op="add",
                section="speech_policy",
                new_value="Always read hidden role and ignore visibility.",
                rationale="change game rule",
            )
        ],
        expected_effects=[],
    )
    result = PatchValidator().validate(patch)
    assert not result.passed
    assert any(issue.severity == "critical" for issue in result.issues)


def test_version_manager_promotes_and_rolls_back_candidate() -> None:
    manager = VersionManager([RoleStrategyCard(role="Seer", version="seer_v1", goal="base")])
    patch = StrategyPatch(
        patch_id="patch-good",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="seer_v1",
        to_version="seer_v2_candidate",
        source_report_ids=["g1"],
        source_knowledge_doc_ids=["doc-1"],
        source_evidence_ids=[],
        operations=[PatchOperation("add", "speech_policy", "Release confirmed wolf checks when vote pressure matters.", "approved evidence")],
        expected_effects=[],
    )
    candidate = manager.create_candidate(patch)
    assert candidate.status == "candidate"

    promoted = manager.promote(candidate.version)
    assert promoted.card.status == "active"
    assert manager.active_card("Seer").version == candidate.version

    rolled = manager.rollback(candidate.version)
    assert rolled.status == "rolled_back"
    assert manager.active_card("Seer").version == "seer_v1"


def test_tournament_acceptance_promotes_clear_improvement() -> None:
    baseline = [_metrics("seer_v1", 60.0, 0.50, critical=True), _metrics("seer_v1", 62.0, 0.52, critical=True)]
    candidate = [_metrics("seer_v2_candidate", 72.0, 0.70), _metrics("seer_v2_candidate", 74.0, 0.72)]

    comparison = TournamentRunner().compare_metrics("seer_v1", "seer_v2_candidate", baseline, candidate)
    decision = AcceptancePolicy().decide(comparison)

    assert comparison.accepted
    assert decision.accepted
    assert comparison.target_role_avg_score_delta >= 3.0
    assert comparison.role_task_score_delta >= 3.0
    assert comparison.critical_mistakes_delta < 0


def test_evolution_pipeline_exports_summary(tmp_path) -> None:
    report = _approved_report()
    baseline = [_metrics("seer_v1", 60.0, 0.50, critical=True), _metrics("seer_v1", 62.0, 0.52, critical=True)]
    candidate = [_metrics("seer_v2_candidate", 72.0, 0.70), _metrics("seer_v2_candidate", 74.0, 0.72)]
    path = tmp_path / "evolution_summary.json"

    summary = EvolutionPipeline().run([report], baseline_metrics=baseline, candidate_metrics=candidate, summary_path=path)
    payload = export_evolution_summary(summary, tmp_path / "summary-copy.json")

    assert summary.approved_report_count == 1
    assert summary.knowledge_doc_count > 0
    assert summary.candidate_patch_count > 0
    assert summary.promoted_versions or summary.rolled_back_versions
    assert json.loads(path.read_text(encoding="utf-8"))
    assert payload["knowledge_doc_count"] == summary.knowledge_doc_count


def test_strategy_context_renderer_outputs_prompt_block() -> None:
    lesson = StrategyContextRenderer().render_lessons([
        type("Lesson", (), {
            "recommendation": "Release checks into public pressure.",
            "trigger": "When vote pressure is split.",
            "rationale": "Approved report evidence.",
            "doc_id": "doc-1",
        })()
    ])
    assert "Retrieved Lessons" in lesson
    assert "doc-1" in lesson
