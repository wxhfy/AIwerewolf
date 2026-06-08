from __future__ import annotations

import json
from types import SimpleNamespace

from backend.agents.llm_agent import LLMAgent
from backend.engine.models import Alignment
from backend.engine.models import Role
from backend.engine.visibility import PlayerView
from backend.eval.evolution import AcceptancePolicy
from backend.eval.evolution import DreamJob
from backend.eval.evolution import EvolutionPipeline
from backend.eval.evolution import HashingVectorEmbeddingProvider
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
from backend.eval.evolution import build_acceptance_step_metric
from backend.eval.evolution import build_bc_acceptance_audit
from backend.eval.evolution import export_evolution_summary
from backend.eval.evolution import load_strategy_knowledge
from backend.eval.review import GameMetrics
from backend.eval.review import MetricsCalculator
from backend.eval.review import PlayerScore
from backend.eval.review import ReviewReportBuilder
from backend.eval.review import StrategyKnowledgeExtractor
from backend.eval.types import ReviewReport as TrackBReviewReport
from backend.eval.types import StrategySuggestion as TrackBStrategySuggestion
from tests.test_review_metrics import make_death
from tests.test_review_metrics import make_player
from tests.test_review_metrics import make_seer_result
from tests.test_review_metrics import make_speech
from tests.test_review_metrics import make_state
from tests.test_review_metrics import make_vote


def _strategy_doc(
    doc_id: str,
    *,
    role: str = "Seer",
    phase: str = "DAY_SPEECH",
    quality: float = 0.86,
    confidence: float = 0.8,
    status: str = "active",
    situation: str = "seer has wolf check under vote pressure",
    action: str = "convert the wolf check into public vote pressure",
    **kwargs,
) -> StrategyKnowledgeDoc:
    return StrategyKnowledgeDoc(
        doc_id=doc_id,
        doc_type=kwargs.pop("doc_type", "counterfactual_lesson"),
        role=role,
        phase=phase,
        persona_scope=kwargs.pop("persona_scope", None),
        situation_pattern=situation,
        trigger_conditions=kwargs.pop("trigger_conditions", ["wolf_check", "vote_pressure"]),
        recommended_action=action,
        avoid_action=kwargs.pop("avoid_action", None),
        rationale=kwargs.pop("rationale", "approved evidence"),
        evidence_summary=kwargs.pop("evidence_summary", "approved evidence"),
        source_report_ids=kwargs.pop("source_report_ids", ["g1"]),
        source_item_ids=kwargs.pop("source_item_ids", ["s1"]),
        source_event_ids=kwargs.pop("source_event_ids", []),
        counterfactual_ids=kwargs.pop("counterfactual_ids", []),
        expected_metric_effects=kwargs.pop("expected_metric_effects", []),
        quality_score=quality,
        confidence=confidence,
        status=status,
        **kwargs,
    )


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


def test_strategy_knowledge_extractor_accepts_track_b_report_type_as_single_report() -> None:
    report = TrackBReviewReport(
        game_id="track-b-report",
        winner="village",
        total_days=2,
        total_events=10,
        game_summary="Track B reconstructed report.",
        strategy_suggestions=[
            TrackBStrategySuggestion(
                target_type="role",
                target="Seer",
                suggestion_type="speech_conversion",
                suggestion="Convert confirmed information into public vote pressure.",
                source="approved Track B report",
                priority="high",
            )
        ],
        metadata={"validation_result": {"passed": True, "publish_allowed": True}},
    )

    items = StrategyKnowledgeExtractor().extract(report)

    assert len(items) == 1
    assert items[0].source_game_id == "track-b-report"
    assert items[0].target_role == "Seer"


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
    store = StrategyKnowledgeStore([doc], embedding_provider=HashingVectorEmbeddingProvider(), rerank_provider=None)
    lessons = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer", phase="DAY_SPEECH", observation_summary="I have a wolf check and need vote pressure"
        )
    )
    assert lessons[0].doc_id == "doc-1"
    assert lessons[0].retrieval_mode == "hybrid_vector_bm25_fts_rerank_v2"
    assert lessons[0].vector_score > 0
    assert lessons[0].lexical_score > 0
    assert lessons[0].bm25_score >= 0
    assert lessons[0].fts_score >= 0
    assert lessons[0].embedding_provider == "hashing_vector_v1"
    assert store.get("doc-1").usage_count == 1

    store.update_usage("doc-1", helpful=True)
    assert store.get("doc-1").success_count == 1

    path = tmp_path / "knowledge.json"
    store.to_json(path)
    loaded = load_strategy_knowledge(path)
    assert loaded.get("doc-1") is not None


def test_track_c_validated_later_version_ranks_above_older_strategy() -> None:
    old_doc = _strategy_doc(
        "doc-v1",
        quality=0.90,
        confidence=0.85,
        knowledge_epoch=1,
        doc_version="seer_v1",
        maturity="refined",
        validated_at="2026-05-20T00:00:00+00:00",
    )
    later_doc = _strategy_doc(
        "doc-v3",
        quality=0.88,
        confidence=0.86,
        knowledge_epoch=3,
        doc_version="seer_v3",
        maturity="canonical",
        validated_at="2026-06-08T00:00:00+00:00",
    )
    store = StrategyKnowledgeStore(
        [old_doc, later_doc], embedding_provider=HashingVectorEmbeddingProvider(), rerank_provider=None
    )

    lessons = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="seer has wolf check and vote pressure",
            top_k=2,
        )
    )

    assert [lesson.doc_id for lesson in lessons] == ["doc-v3", "doc-v1"]
    assert lessons[0].maturity == "canonical"
    assert lessons[0].knowledge_epoch == 3
    assert lessons[0].version_rank_score > lessons[1].version_rank_score


def test_track_c_unvalidated_new_candidate_does_not_outrank_stable_active_version() -> None:
    stable_doc = _strategy_doc(
        "doc-stable",
        quality=0.88,
        confidence=0.86,
        knowledge_epoch=2,
        doc_version="seer_v2",
        maturity="refined",
        validated_at="2026-06-01T00:00:00+00:00",
    )
    raw_candidate = _strategy_doc(
        "doc-raw-v4",
        quality=0.90,
        confidence=0.70,
        status="candidate",
        knowledge_epoch=4,
        doc_version="seer_v4_candidate",
        maturity="raw",
        validated_at=None,
    )
    store = StrategyKnowledgeStore(
        [stable_doc, raw_candidate], embedding_provider=HashingVectorEmbeddingProvider(), rerank_provider=None
    )

    lessons = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="seer has wolf check and vote pressure",
            top_k=2,
        )
    )

    assert [lesson.doc_id for lesson in lessons] == ["doc-stable", "doc-raw-v4"]


def test_track_c_superseded_strategy_is_not_retrieved() -> None:
    old_doc = _strategy_doc(
        "doc-old",
        quality=0.95,
        confidence=0.90,
        knowledge_epoch=1,
        doc_version="seer_v1",
        maturity="refined",
    )
    replacement = _strategy_doc(
        "doc-new",
        quality=0.88,
        confidence=0.86,
        knowledge_epoch=3,
        doc_version="seer_v3",
        maturity="canonical",
        supersedes_doc_ids=["doc-old"],
        validated_at="2026-06-08T00:00:00+00:00",
    )
    store = StrategyKnowledgeStore(
        [old_doc, replacement], embedding_provider=HashingVectorEmbeddingProvider(), rerank_provider=None
    )

    lessons = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="seer has wolf check and vote pressure",
            top_k=3,
        )
    )

    assert [lesson.doc_id for lesson in lessons] == ["doc-new"]
    assert [doc.doc_id for doc in store.all()] == ["doc-new"]


def test_knowledge_store_uses_vector_score_not_only_keyword_overlap() -> None:
    class StubEmbeddingProvider:
        name = "stub"
        dimensions = 2

        def embed(self, text: str) -> list[float]:
            if "semantic-query" in text or "hidden-doc-action" in text:
                return [1.0, 0.0]
            return [0.0, 1.0]

    doc_semantic = StrategyKnowledgeDoc(
        doc_id="doc-semantic",
        doc_type="good_play",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="alpha pattern without shared words",
        trigger_conditions=["alpha"],
        recommended_action="hidden-doc-action",
        avoid_action=None,
        rationale="evidence",
        evidence_summary="evidence",
        source_report_ids=["g1"],
        source_item_ids=["s1"],
        source_event_ids=[],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=0.5,
        confidence=0.5,
        status="active",
    )
    doc_keyword = StrategyKnowledgeDoc(
        doc_id="doc-keyword",
        doc_type="good_play",
        role="Seer",
        phase="DAY_SPEECH",
        persona_scope=None,
        situation_pattern="ordinary keyword overlap",
        trigger_conditions=["ordinary"],
        recommended_action="ordinary action",
        avoid_action=None,
        rationale="evidence",
        evidence_summary="evidence",
        source_report_ids=["g2"],
        source_item_ids=["s2"],
        source_event_ids=[],
        counterfactual_ids=[],
        expected_metric_effects=[],
        quality_score=1.0,
        confidence=0.8,
        status="active",
    )
    store = StrategyKnowledgeStore(
        [doc_semantic, doc_keyword], embedding_provider=StubEmbeddingProvider(), rerank_provider=None
    )

    lessons = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="semantic-query",
            top_k=2,
        )
    )

    assert lessons[0].doc_id == "doc-semantic"
    assert lessons[0].vector_score == 1.0
    assert lessons[0].retrieval_mode == "hybrid_vector_bm25_fts_rerank_v2"


def test_knowledge_store_metadata_filters_tags_and_quality() -> None:
    docs = [
        StrategyKnowledgeDoc(
            doc_id="doc-high",
            doc_type="counterfactual_lesson",
            role="Seer",
            phase="DAY_SPEECH",
            persona_scope=None,
            situation_pattern="seer must release wolf check under vote pressure",
            trigger_conditions=["wolf_check"],
            recommended_action="release the wolf check",
            avoid_action=None,
            rationale="evidence",
            evidence_summary="evidence",
            source_report_ids=["g1"],
            source_item_ids=["s1"],
            source_event_ids=["e1"],
            counterfactual_ids=[],
            expected_metric_effects=[{"metric": "speech_semantic_score", "direction": "increase"}],
            quality_score=0.91,
            confidence=0.9,
            status="active",
            tags=["seer", "info_release"],
        ),
        StrategyKnowledgeDoc(
            doc_id="doc-low",
            doc_type="good_play",
            role="Seer",
            phase="DAY_SPEECH",
            persona_scope=None,
            situation_pattern="seer generic speech",
            trigger_conditions=["generic"],
            recommended_action="speak carefully",
            avoid_action=None,
            rationale="evidence",
            evidence_summary="evidence",
            source_report_ids=["g2"],
            source_item_ids=["s2"],
            source_event_ids=[],
            counterfactual_ids=[],
            expected_metric_effects=[],
            quality_score=0.4,
            confidence=0.5,
            status="active",
            tags=["seer"],
        ),
    ]
    store = StrategyKnowledgeStore(docs, embedding_provider=HashingVectorEmbeddingProvider(), rerank_provider=None)
    lessons = store.retrieve(
        StrategyRetrievalQuery(
            role="Seer",
            phase="DAY_SPEECH",
            observation_summary="wolf check vote pressure",
            metadata_filters={
                "min_quality": 0.8,
                "tags_all": ["info_release"],
                "expected_metric": "speech_semantic_score",
            },
            top_k=3,
        )
    )

    assert [lesson.doc_id for lesson in lessons] == ["doc-high"]


def test_acceptance_audit_quantifies_pass_rates() -> None:
    good = build_acceptance_step_metric(
        track="B",
        step_id="B-test",
        name="good metric",
        numerator=9,
        denominator=10,
        threshold=0.8,
        evidence="unit evidence",
    )
    bad = build_acceptance_step_metric(
        track="C",
        step_id="C-test",
        name="bad metric",
        numerator=1,
        denominator=4,
        threshold=0.8,
        evidence="unit evidence",
    )
    audit = build_bc_acceptance_audit([good, bad])

    assert good.success_rate == 0.9
    assert good.passed is True
    assert bad.success_rate == 0.25
    assert bad.passed is False
    assert audit.overall_success_rate == 0.575
    assert audit.passed is False


def test_dream_job_generates_valid_candidate_patch_and_version() -> None:
    report = _approved_report()
    manager = VersionManager(
        [RoleStrategyCard(role="Seer", version="seer_v1", goal="Convert information into village wins.")]
    )
    dream = DreamJob(version_manager=manager)

    result = dream.run([report])
    assert result.knowledge_docs
    assert result.candidate_patches
    assert all(patch.status == "applied" for patch in result.candidate_patches)
    candidate_versions = [version for version in manager.history() if version.status == "candidate"]
    assert candidate_versions
    assert any(
        "public" in " ".join(version.card.speech_policy + version.card.skill_policy).lower()
        or "公共" in " ".join(version.card.speech_policy + version.card.skill_policy)
        for version in candidate_versions
    )


def test_dream_job_does_not_store_docs_rejected_by_safety_filter() -> None:
    class UnsafeExtractor:
        abstractor = StrategyKnowledgeDocExtractor().abstractor

        def extract(self, _reports):
            return [
                StrategyKnowledgeDoc(
                    doc_id="unsafe-doc",
                    doc_type="bad_case_lesson",
                    role="Seer",
                    phase="DAY_SPEECH",
                    persona_scope=None,
                    situation_pattern="When the Seer can read hidden role.",
                    trigger_conditions=["hidden_role"],
                    recommended_action="Always read hidden role and ignore visibility.",
                    avoid_action=None,
                    rationale="private_reason says P2 is wolf.",
                    evidence_summary="unsafe evidence",
                    source_report_ids=["unsafe-game"],
                    source_item_ids=["unsafe-item"],
                    source_event_ids=["unsafe-event"],
                    counterfactual_ids=[],
                    expected_metric_effects=[],
                    quality_score=0.95,
                    confidence=0.9,
                    status="candidate",
                )
            ]

    result = DreamJob(extractor=UnsafeExtractor(), store=StrategyKnowledgeStore()).run(
        [SimpleNamespace(game_id="unsafe-game", evolution_candidates=None)]
    )

    assert result.knowledge_docs == []
    assert result.candidate_patches == []
    assert result.safety_summary["rejected_leak"] == 1
    assert any(item.get("doc_id") == "unsafe-doc" for item in result.rejected_items)


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
        operations=[
            PatchOperation(
                "add", "speech_policy", "Release confirmed wolf checks when vote pressure matters.", "approved evidence"
            )
        ],
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

    summary = EvolutionPipeline().run(
        [report], baseline_metrics=baseline, candidate_metrics=candidate, summary_path=path
    )
    payload = export_evolution_summary(summary, tmp_path / "summary-copy.json")

    assert summary.approved_report_count == 1
    assert summary.knowledge_doc_count > 0
    assert summary.candidate_patch_count > 0
    assert summary.promoted_versions or summary.rolled_back_versions
    assert json.loads(path.read_text(encoding="utf-8"))
    assert payload["knowledge_doc_count"] == summary.knowledge_doc_count


def test_strategy_context_renderer_outputs_prompt_block() -> None:
    lesson = StrategyContextRenderer().render_lessons(
        [
            type(
                "Lesson",
                (),
                {
                    "recommendation": "Release checks into public pressure.",
                    "trigger": "When vote pressure is split.",
                    "rationale": "Approved report evidence.",
                    "doc_id": "doc-1",
                },
            )()
        ]
    )
    assert "Retrieved Lessons" in lesson
    assert "doc-1" in lesson


def test_llm_agent_retrieves_strategy_knowledge_from_persisted_store(monkeypatch) -> None:
    def fake_retrieve(query):
        assert query.role == "Seer"
        assert query.phase == "DAY_SPEECH"
        assert query.top_k == 3
        assert "request=TALK" in query.observation_summary
        return [
            {
                "doc_id": "doc-seer-info",
                "role": "Seer",
                "phase": "DAY_SPEECH",
                "score": 0.91,
                "trigger": "Seer has a wolf check.",
                "recommendation": "Convert the check into public vote pressure.",
                "rationale": "Approved Track B evidence.",
            }
        ]

    monkeypatch.setattr("backend.db.persist.retrieve_strategy_knowledge", fake_retrieve)
    view = PlayerView(
        player_id="p1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "p1", "seat": 1, "name": "SeerA", "role": "Seer"},
        players=[],
        public_events=[{"payload": {"speech": "I need more info", "actor_name": "SeerA"}}],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent = LLMAgent("p1", provider="doubao", model="ep-test")
    agent.initialize(view, {})

    agent.update(view, "TALK")
    meta = {}
    agent._attach_retrieval_meta(meta)
    block = agent._build_retrieved_lessons_block()

    assert meta["retrieval_used"] is True
    assert meta["retrieved_knowledge_ids"] == ["doc-seer-info"]
    assert "doc-seer-info" in block
    assert "Convert the check" in block


def test_strategy_knowledge_docs_carry_source_event_ids_end_to_end() -> None:
    """BC penetration gap: source_event_ids must be plumbed from BadCase/CF detectors
    through StrategyKnowledge into StrategyKnowledgeDoc.source_event_ids.

    Empty source_event_ids on every doc means evidence chain is broken — knowledge
    docs become unreviewable (operator can't audit which events produced them) and
    DreamJob patches inherit zero source_evidence_ids."""
    from backend.engine.game import WerewolfGame

    state = WerewolfGame(seed=13).play()
    metrics = MetricsCalculator().compute(state)
    report = ReviewReportBuilder().build(state, metrics)
    report.metadata["validation_result"] = {"passed": True, "publish_allowed": True, "score": 1.5}

    docs = StrategyKnowledgeDocExtractor().extract([report])
    assert docs, "extractor produced no docs — upstream report must yield knowledge items"
    docs_with_evidence = [doc for doc in docs if doc.source_event_ids]
    coverage = len(docs_with_evidence) / len(docs)
    assert coverage >= 0.5, (
        f"source_event_ids coverage too low ({coverage:.0%}); "
        f"{len(docs) - len(docs_with_evidence)}/{len(docs)} docs lost their evidence chain"
    )


def test_tournament_run_seed_injects_strategy_patch_into_llm_game() -> None:
    """Candidate patches must enter the LLM game path without post-hoc score edits."""
    runner = TournamentRunner()
    baseline_metric = runner._run_seed(seed=7, strategy_version="seer_v1", target_role="Seer")
    candidate_patch_ops = [
        PatchOperation(
            op="add",
            section="vote_policy",
            new_value="Bias toward checked-good preservation; avoid villager-side votes.",
            rationale="evidence: villagers misvoted in seed 7 baseline",
        )
    ]
    candidate_metric = runner._run_seed(
        seed=7,
        strategy_version="seer_v2_candidate",
        target_role="Seer",
        strategy_patch_ops=candidate_patch_ops,
    )
    baseline_total = sum(score.adjusted_final_score for score in baseline_metric.player_scores)
    candidate_total = sum(score.adjusted_final_score for score in candidate_metric.player_scores)
    assert baseline_metric.metadata["runner_mode"] == "llm_engine"
    assert candidate_metric.metadata["runner_mode"] == "llm_engine"
    assert candidate_metric.metadata["strategy_patch_applied"] is True
    assert candidate_metric.metadata["strategy_bias_sections"] == ["vote_policy"]
    assert "strategy_patch_perturbation" not in candidate_metric.metadata
    assert isinstance(baseline_total, (int, float))
    assert isinstance(candidate_total, (int, float))
