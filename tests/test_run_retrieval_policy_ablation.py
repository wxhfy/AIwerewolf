from __future__ import annotations

from scripts.run_retrieval_policy_ablation import POLICIES
from scripts.run_retrieval_policy_ablation import PolicyStats
from scripts.run_retrieval_policy_ablation import _ablation_evidence_status
from scripts.run_retrieval_policy_ablation import _build_ablation_summary


def _stats(policy: str, *, completed: int, total: int, errors: int = 0, score: float = 0.0) -> PolicyStats:
    return PolicyStats(
        policy=policy,
        n_games=total,
        n_completed=completed,
        n_errors=errors,
        avg_process_score=score,
    )


def test_retrieval_policy_ablation_summary_does_not_recommend_when_incomplete() -> None:
    stats = {
        "baseline_no_trackc": _stats("baseline_no_trackc", completed=0, total=1, errors=1),
        "global_only": _stats("global_only", completed=0, total=1, errors=1),
    }

    summary = _build_ablation_summary(stats, comparisons=[], n_games=1)

    assert _ablation_evidence_status(stats) == "incomplete_online_ablation"
    assert "No policy recommendation is made" in summary
    assert "recommended default policy" not in summary


def test_retrieval_policy_ablation_summary_can_recommend_only_when_complete() -> None:
    stats = {
        policy: _stats(policy, completed=2, total=2, score=float(index))
        for index, policy in enumerate(POLICIES, start=1)
    }

    summary = _build_ablation_summary(stats, comparisons=[], n_games=2)

    assert _ablation_evidence_status(stats) == "complete_online_ablation"
    assert "Highest observed average process score" in summary
    assert f"`{POLICIES[-1]}`" in summary
