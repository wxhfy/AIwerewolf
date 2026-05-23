"""Optional LangGraph-based evaluator-optimizer workflow for review reports.

This module must not make langgraph a hard dependency. Import errors are
captured so the rest of the evaluation stack can continue using the plain
Python `ReportOptimizer` fallback.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.eval.review import (
    ReportEvaluationResult,
    ReportEvaluator,
    ReportGenerator,
    ReportOptimizationState,
    ReportOptimizer,
    ReviewQualityChecker,
    ReviewReport,
)

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - exercised by availability tests
    END = START = StateGraph = None
    LANGGRAPH_AVAILABLE = False


class LangGraphReportOptimizer:
    """Optional StateGraph-based report optimizer.

    When langgraph is unavailable, callers should use `create_report_optimizer()`
    or check `LANGGRAPH_AVAILABLE` before constructing this class.
    """

    def __init__(
        self,
        generator: ReportGenerator | None = None,
        evaluator: ReportEvaluator | None = None,
        quality_checker: ReviewQualityChecker | None = None,
    ) -> None:
        if not LANGGRAPH_AVAILABLE:
            raise ImportError("langgraph is not installed; use ReportOptimizer fallback instead.")
        self.generator = generator or ReportGenerator()
        self.evaluator = evaluator or ReportEvaluator()
        self.quality_checker = quality_checker or ReviewQualityChecker()
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(ReportOptimizationState)
        graph.add_node("generate_report", self._generate_report_node)
        graph.add_node("evaluate_report", self._evaluate_report_node)
        graph.add_node("revise_report", self._revise_report_node)
        graph.add_node("final_quality_gate", self._final_quality_gate_node)
        graph.add_edge(START, "generate_report")
        graph.add_edge("generate_report", "evaluate_report")
        graph.add_conditional_edges(
            "evaluate_report",
            self._route_after_evaluation,
            {
                "final_quality_gate": "final_quality_gate",
                "revise_report": "revise_report",
            },
        )
        graph.add_edge("revise_report", "evaluate_report")
        graph.add_edge("final_quality_gate", END)
        return graph.compile()

    def optimize(
        self,
        report: ReviewReport,
        *,
        review_context: dict[str, Any] | None = None,
        max_iterations: int = 2,
    ) -> ReportOptimizationState:
        state = ReportOptimizationState(
            game_id=report.game_id,
            review_report=report,
            review_context=review_context or {},
            max_iterations=max_iterations,
        )
        return self.graph.invoke(state)

    def _generate_report_node(self, state: ReportOptimizationState) -> ReportOptimizationState:
        feedback = state.feedback_history[-1].feedback if state.feedback_history else ""
        return replace(
            state,
            iteration=state.iteration + 1,
            draft_markdown=self.generator.generate(state.review_report, feedback),
        )

    def _evaluate_report_node(self, state: ReportOptimizationState) -> ReportOptimizationState:
        result = self.evaluator.evaluate(state.review_report, state.draft_markdown)
        return replace(
            state,
            evaluator_result=result,
            feedback_history=[*state.feedback_history, result],
        )

    def _revise_report_node(self, state: ReportOptimizationState) -> ReportOptimizationState:
        feedback = state.evaluator_result.feedback if state.evaluator_result else ""
        revised = self.generator.generate(state.review_report, feedback)
        return replace(state, draft_markdown=revised)

    def _final_quality_gate_node(self, state: ReportOptimizationState) -> ReportOptimizationState:
        final_gate = self.quality_checker.check(state.review_report, state.draft_markdown)
        evaluator_passed = state.evaluator_result.grade == "pass" if state.evaluator_result else False
        return replace(
            state,
            final_markdown=state.draft_markdown,
            evaluator_result=final_gate,
            feedback_history=[*state.feedback_history, final_gate],
            quality_passed=final_gate.grade == "pass" and evaluator_passed,
        )

    def _route_after_evaluation(self, state: ReportOptimizationState) -> str:
        if state.evaluator_result and state.evaluator_result.grade == "pass":
            return "final_quality_gate"
        if state.iteration < state.max_iterations:
            return "revise_report"
        return "final_quality_gate"


def create_report_optimizer(
    *,
    prefer_langgraph: bool = True,
    generator: ReportGenerator | None = None,
    evaluator: ReportEvaluator | None = None,
    quality_checker: ReviewQualityChecker | None = None,
) -> ReportOptimizer | LangGraphReportOptimizer:
    """Create the best available report optimizer without hard dependency risk."""

    if prefer_langgraph and LANGGRAPH_AVAILABLE:
        return LangGraphReportOptimizer(
            generator=generator,
            evaluator=evaluator,
            quality_checker=quality_checker,
        )
    return ReportOptimizer(
        generator=generator,
        evaluator=evaluator,
        quality_checker=quality_checker,
    )
