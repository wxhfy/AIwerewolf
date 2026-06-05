from backend.engine.game import WerewolfGame
from backend.eval.review import generate_review_report
from backend.eval.track_b import ReplayBundleBuilder
from backend.eval.track_b import ReviewRepairLoop
from backend.eval.track_b import SpeechActAnalyzer
from backend.eval.track_b import SuspicionMatrixBuilder
from backend.eval.track_b import TrackBValidator
from backend.eval.track_b import generate_published_review_document


def test_track_b_pipeline_generates_publishable_review_document() -> None:
    state = WerewolfGame(seed=9).play()

    document = generate_published_review_document(state)

    assert document.status == "approved"
    assert document.validation_result["passed"] is True
    assert document.validation_result["publish_allowed"] is True
    assert document.review_report["scoreboard"]
    assert document.review_report["bad_cases"] or document.review_report["turning_points"]
    assert document.speech_acts
    assert document.suspicion_matrix
    assert "## 10. 报告可信度校验" in document.markdown
    assert "html_report" in document.metadata
    assert "Track B Review" in document.metadata["html_report"]
    assert "玩家评分榜" in document.metadata["html_report"]


def test_track_b_review_items_have_evidence_event_ids() -> None:
    state = WerewolfGame(seed=13).play()
    document = generate_published_review_document(state)
    report = document.review_report

    for section_name in ["mvp_results", "turning_points", "bad_cases", "counterfactuals", "strategy_suggestions"]:
        for item in report.get(section_name, []):
            assert item.get("evidence_event_ids"), f"{section_name} missing evidence"


def test_track_b_repair_loop_can_fix_missing_evidence_and_publish() -> None:
    state = WerewolfGame(seed=15).play()
    replay_bundle = ReplayBundleBuilder().build(state)
    generated = generate_review_report(state)
    review_report = generated["report"]
    if review_report["bad_cases"]:
        review_report["bad_cases"][0]["evidence_event_ids"] = []

    validator = TrackBValidator()
    speech_acts = SpeechActAnalyzer().analyze(state)
    suspicion_matrix = SuspicionMatrixBuilder().build(state, speech_acts)
    loop = ReviewRepairLoop()

    report, markdown, validation, repair_history = loop.run(
        replay_bundle=replay_bundle,
        review_report=review_report,
        markdown=generated["final_markdown"],
        speech_acts=speech_acts,
        suspicion_matrix=suspicion_matrix,
        validator=validator,
        view_scope="moderator_view",
    )

    assert validation.passed is True
    assert validation.publish_allowed is True
    assert repair_history
    assert report["bad_cases"][0]["evidence_event_ids"]
    assert "## 10. 报告可信度校验" in markdown
