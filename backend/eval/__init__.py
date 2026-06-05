"""Evaluation, review, and future self-improvement interfaces.

Module structure (decoupled):
  types.py               DATA:   Shared dataclasses + labels (zero logic)
  game_replay.py         ENGINE: Deterministic night/vote/hunter replay
  review.py              LOGIC:  Metrics + detection + counterfactuals + builder
  track_b.py             PUBLISH: Validation + repair loop + publishing
  evolution.py           TRACK C: DreamJob + self-evolution + tournament
  knowledge_confidence.py SAFETY: L0-L4 tiers + AccessControl + Applicability
"""

from backend.eval.evolution import ABComparison
from backend.eval.evolution import AcceptanceDecision
from backend.eval.evolution import AcceptancePolicy
from backend.eval.evolution import DreamJob
from backend.eval.evolution import DreamResult
from backend.eval.evolution import DreamSummary
from backend.eval.evolution import EvolutionHook
from backend.eval.evolution import EvolutionPipeline
from backend.eval.evolution import EvolutionRecord
from backend.eval.evolution import EvolutionSummary
from backend.eval.evolution import HermesEvolutionHook
from backend.eval.evolution import KnowledgeDocValidator
from backend.eval.evolution import PatchOperation
from backend.eval.evolution import PatchValidationIssue
from backend.eval.evolution import PatchValidationResult
from backend.eval.evolution import PatchValidator
from backend.eval.evolution import RetrievedStrategyLesson
from backend.eval.evolution import RoleStrategyCard
from backend.eval.evolution import SimpleEvolutionLoop
from backend.eval.evolution import StrategyContextRenderer
from backend.eval.evolution import StrategyKnowledgeDoc
from backend.eval.evolution import StrategyKnowledgeDocExtractor
from backend.eval.evolution import StrategyKnowledgeStore
from backend.eval.evolution import StrategyPatch
from backend.eval.evolution import StrategyPatchGenerator
from backend.eval.evolution import StrategyRetrievalQuery
from backend.eval.evolution import StrategyVersion
from backend.eval.evolution import TournamentRunner
from backend.eval.evolution import VersionManager
from backend.eval.evolution import export_evolution_summary
from backend.eval.evolution import load_strategy_knowledge
from backend.eval.game_replay import NightActionsSnapshot
from backend.eval.game_replay import VoteSnapshot
from backend.eval.game_replay import replay_hunter_shot
from backend.eval.game_replay import replay_night_with_change
from backend.eval.game_replay import replay_vote_with_swap
from backend.eval.report_graph import LANGGRAPH_AVAILABLE
from backend.eval.report_graph import LangGraphReportOptimizer
from backend.eval.report_graph import create_report_optimizer
from backend.eval.review import CounterfactualAnalyzer
from backend.eval.review import CounterfactualCase
from backend.eval.review import GameMetrics
from backend.eval.review import GraphRAGReviewProvider
from backend.eval.review import LeaderboardAggregator
from backend.eval.review import LeaderboardEntry
from backend.eval.review import LeaderboardResult
from backend.eval.review import MarkdownReportRenderer
from backend.eval.review import MetricsCalculator
from backend.eval.review import MockReviewLLM
from backend.eval.review import MVPResult
from backend.eval.review import MVPSelector
from backend.eval.review import PersonaMetrics
from backend.eval.review import PlayerReview
from backend.eval.review import PlayerScore
from backend.eval.review import ReportEvaluationResult
from backend.eval.review import ReportEvaluator
from backend.eval.review import ReportGenerator
from backend.eval.review import ReportOptimizationState
from backend.eval.review import ReportOptimizer
from backend.eval.review import ReviewArtifact
from backend.eval.review import ReviewBonus
from backend.eval.review import ReviewBonusDetector
from backend.eval.review import ReviewProvider
from backend.eval.review import ReviewQualityChecker
from backend.eval.review import ReviewReport
from backend.eval.review import ReviewReportBuilder
from backend.eval.review import StrategyKnowledge
from backend.eval.review import StrategyKnowledgeExtractor
from backend.eval.review import StrategySuggestion
from backend.eval.review import TurningPoint
from backend.eval.review import export_leaderboard
from backend.eval.review import export_review_report
from backend.eval.review import export_strategy_knowledge
from backend.eval.review import generate_review_report
from backend.eval.types import COUNTERFACTUAL_TYPE_LABELS
from backend.eval.types import BadCaseReport
from backend.eval.types import CounterfactualCase
from backend.eval.types import DecisionTrace
from backend.eval.types import GameMetrics
from backend.eval.types import ReviewReport

__all__ = [
    "ABComparison",
    "AcceptanceDecision",
    "AcceptancePolicy",
    "DreamJob",
    "DreamResult",
    "DreamSummary",
    "EvolutionHook",
    "EvolutionPipeline",
    "EvolutionRecord",
    "EvolutionSummary",
    "CounterfactualAnalyzer",
    "CounterfactualCase",
    "GameMetrics",
    "GraphRAGReviewProvider",
    "LeaderboardAggregator",
    "LeaderboardEntry",
    "LeaderboardResult",
    "HermesEvolutionHook",
    "KnowledgeDocValidator",
    "LANGGRAPH_AVAILABLE",
    "LangGraphReportOptimizer",
    "MarkdownReportRenderer",
    "MockReviewLLM",
    "MetricsCalculator",
    "MVPResult",
    "MVPSelector",
    "PatchOperation",
    "PatchValidationIssue",
    "PatchValidationResult",
    "PatchValidator",
    "PersonaMetrics",
    "PlayerReview",
    "PlayerScore",
    "ReportEvaluationResult",
    "ReportEvaluator",
    "ReportGenerator",
    "ReportOptimizationState",
    "ReportOptimizer",
    "RetrievedStrategyLesson",
    "ReviewReport",
    "ReviewReportBuilder",
    "RoleStrategyCard",
    "ReviewBonus",
    "ReviewBonusDetector",
    "ReviewArtifact",
    "ReviewQualityChecker",
    "ReviewProvider",
    "SimpleEvolutionLoop",
    "StrategyContextRenderer",
    "StrategyKnowledge",
    "StrategyKnowledgeDoc",
    "StrategyKnowledgeDocExtractor",
    "StrategyKnowledgeExtractor",
    "StrategyKnowledgeStore",
    "StrategyPatch",
    "StrategyPatchGenerator",
    "StrategyRetrievalQuery",
    "StrategySuggestion",
    "StrategyVersion",
    "TournamentRunner",
    "TurningPoint",
    "VersionManager",
    "create_report_optimizer",
    "export_evolution_summary",
    "export_leaderboard",
    "export_review_report",
    "export_strategy_knowledge",
    "generate_review_report",
    "load_strategy_knowledge",
]
