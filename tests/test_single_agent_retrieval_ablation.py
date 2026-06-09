from __future__ import annotations

from scripts import evaluate_single_agent_retrieval_ablation as ablation


def test_parse_judgment_clamps_scores_and_completes_ranking() -> None:
    raw = """
    ```json
    {
      "scores": {
        "A": {"overall": 11, "role_fit": 9, "strategic_depth": 8, "actionability": 7, "information_safety": 6},
        "B": {"overall": 4, "role_fit": 3, "strategic_depth": 2, "actionability": 1, "information_safety": 0}
      },
      "ranking": ["B"],
      "summary": "B 更保守"
    }
    ```
    """

    result = ablation.parse_judgment(raw, ["A", "B", "C"])

    assert result["scores"]["A"]["overall"] == 10.0
    assert result["scores"]["C"]["overall"] == 0.0
    assert result["ranking"] == ["B", "A", "C"]


def test_aggregate_reports_policy_delta_against_no_retrieval() -> None:
    rows = [
        {
            "variants": [
                {"policy": "no_retrieval", "rank": 2, "retrieved_doc_count": 0, "judge": _score(5.0)},
                {"policy": "global_only", "rank": 3, "retrieved_doc_count": 4, "judge": _score(6.0)},
                {"policy": "same_role_all_mbti", "rank": 4, "retrieved_doc_count": 4, "judge": _score(7.0)},
                {"policy": "hybrid_role_mbti_global", "rank": 1, "retrieved_doc_count": 4, "judge": _score(8.0)},
            ]
        }
    ]

    result = ablation.aggregate(rows)

    assert result["best_policy"] == "hybrid_role_mbti_global"
    assert result["policy_metrics"]["hybrid_role_mbti_global"]["delta_vs_no_retrieval"] == 3.0
    assert result["policy_metrics"]["hybrid_role_mbti_global"]["win_count"] == 1


def _score(overall: float) -> dict[str, float]:
    return {
        "overall": overall,
        "role_fit": overall,
        "strategic_depth": overall,
        "actionability": overall,
        "information_safety": overall,
    }
