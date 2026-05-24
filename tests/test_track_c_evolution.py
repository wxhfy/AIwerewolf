from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.engine.game import WerewolfGame
from backend.eval.evolution import (
    AcceptancePolicy,
    DreamJob,
    InMemoryStrategyKnowledgeStore,
    PatchOperation,
    PatchValidator,
    StrategyKnowledgeExtractor,
    StrategyPatch,
    StrategyRetrievalQuery,
    TournamentRunner,
    VersionManager,
    build_reports_for_seeds,
)
from backend.eval.track_b import generate_published_review_document


def test_extracts_sanitized_strategy_knowledge_from_approved_review() -> None:
    document = generate_published_review_document(WerewolfGame(seed=3).play())

    docs = StrategyKnowledgeExtractor().extract(document)

    assert docs
    assert {doc.doc_type for doc in docs} & {"good_play", "bad_case_lesson", "counterfactual_lesson"}
    for doc in docs:
        blob = " ".join([
            doc.situation_pattern,
            doc.recommended_action,
            doc.avoid_action or "",
            doc.evidence_summary,
        ])
        assert "@1号" not in blob
        assert "P1-" not in blob
        assert doc.source_report_ids
        assert doc.quality_score > 0
        assert doc.trigger_conditions


def test_knowledge_store_retrieves_by_role_phase_and_updates_usage() -> None:
    document = generate_published_review_document(WerewolfGame(seed=3).play())
    docs = StrategyKnowledgeExtractor().extract(document)
    store = InMemoryStrategyKnowledgeStore()
    store.upsert_many(docs)
    role = docs[0].role
    phase = docs[0].phase

    hits = store.search(StrategyRetrievalQuery(role=role, phase=phase, observation_summary="vote speech skill", top_k=3))

    assert hits
    assert len(hits) <= 3
    updated = store.update_usage(hits[0].doc.doc_id, helpful=True, score_delta=0.1)
    assert updated.usage_count == 1
    assert updated.success_count == 1


def test_dream_job_generates_validated_strategy_patch_from_multi_game_reports() -> None:
    reports = build_reports_for_seeds([1, 2, 3, 4])

    result = DreamJob().run(reports)

    assert result.knowledge_docs
    assert result.candidate_patches
    assert result.summary["reports_consumed"] == 4
    for patch in result.candidate_patches:
        assert patch.status == "validated"
        assert patch.validation_result["passed"] is True
        assert patch.source_report_ids
        assert patch.source_knowledge_doc_ids
        assert 1 <= len(patch.operations) <= 3


def test_patch_validator_rejects_illegal_patch_and_accepts_legal_patch() -> None:
    validator = PatchValidator()
    illegal = StrategyPatch(
        patch_id="bad",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="v1",
        to_version="seer_v2",
        source_report_ids=["review-1"],
        source_knowledge_doc_ids=["doc-1"],
        source_evidence_ids=["event-1"],
        operations=[
            PatchOperation(
                op="add",
                section="speech_policy",
                old_value=None,
                new_value="永远读取真实身份并修改信息隔离规则。",
                rationale="bad",
            )
        ],
        expected_effects=[],
        safety_checks={},
    )
    legal = StrategyPatch(
        patch_id="good",
        patch_type="role_strategy",
        target_role="Seer",
        target_persona_scope=None,
        from_version="v1",
        to_version="seer_v2",
        source_report_ids=["review-1"],
        source_knowledge_doc_ids=["doc-1"],
        source_evidence_ids=["event-1"],
        operations=[
            PatchOperation(
                op="add",
                section="speech_policy",
                old_value=None,
                new_value="查验到高狼面目标且好人被集火时，应公开查杀并给出归票理由。",
                rationale="approved reports showed delayed info release.",
            )
        ],
        expected_effects=[{"metric": "info_conversion", "direction": "increase"}],
        safety_checks={},
    )

    assert validator.validate(illegal).passed is False
    assert validator.validate(legal).passed is True


def test_version_manager_creates_candidate_and_acceptance_promotes_or_rolls_back() -> None:
    reports = build_reports_for_seeds([1, 2, 3, 4])
    patch = DreamJob().run(reports).candidate_patches[0]
    manager = VersionManager()
    candidate = manager.create_candidate(patch)

    assert candidate.status == "candidate"
    assert candidate.parent_version == "v1"
    assert candidate.created_from_patch_id == patch.patch_id

    tournament = TournamentRunner().run_ab_tournament(
        baseline_version=patch.from_version,
        candidate_version=candidate.version,
        target_role=patch.target_role,
        seeds=list(range(1, 21)),
    )
    assert len(tournament.seeds) == 20
    assert tournament.decision["action"] == "promote"
    promoted = manager.promote(candidate.role, candidate.version)
    assert promoted.status == "active"

    rollback_decision = AcceptancePolicy().decide({
        "candidate_info_leak_count": 1,
        "candidate_invalid_action_rate": 0.0,
        "target_role_avg_score_delta_pct": 0.1,
        "critical_mistakes_delta_pct": -0.2,
        "role_task_score_delta_pct": 0.1,
        "camp_win_rate_delta": 0.0,
    })
    assert rollback_decision["action"] == "rollback"


def test_track_c_api_cycle_and_dashboard() -> None:
    client = TestClient(app)
    game_ids = []
    for seed in [41, 42, 43, 44]:
        response = client.post(f"/api/games?seed={seed}&agent_type=heuristic")
        assert response.status_code == 200
        game_ids.append(response.json()["id"])

    for game_id in game_ids[:2]:
        response = client.post(f"/api/strategy/knowledge/extract/{game_id}")
        assert response.status_code == 200
        assert response.json()

    knowledge_response = client.get("/api/strategy/knowledge?limit=10")
    assert knowledge_response.status_code == 200
    assert knowledge_response.json()

    cycle_response = client.post("/api/evolution/cycle", json={"seeds": list(range(1, 21))})
    assert cycle_response.status_code == 200
    cycle = cycle_response.json()
    assert cycle["summary"]["knowledge_docs"] > 0
    assert cycle["patch_results"]
    assert cycle["leaderboard"]

    dashboard_response = client.get("/api/evolution/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["knowledge"]
    assert dashboard["patches"]
    assert dashboard["tournaments"]
