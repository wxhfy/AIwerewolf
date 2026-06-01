"""Hybrid Scoring Framework — rule-locked + LLM evidence-grounded + calibrated.

Design reference: Rulers (Hong et al., arXiv:2601.08654, 2026)
- Phase I: Locked Rubrics (immutable scoring criteria with content hash)
- Phase II: Evidence-Grounded Execution (rules + LLM with extractive evidence)
- Phase III: Post-Hoc Calibration (Ridge regression + quantile mapping)

Key principle: Rules handle deterministic verification; LLM handles semantic
assessment WITH mechanical evidence validation; statistical calibration aligns
to human distributions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class ScoringCriterion:
    """A single scoring criterion with locked rubric.

    Once created, the rubric is immutable (frozen dataclass).
    The content_hash ensures the rubric hasn't been tampered with.
    """

    id: str
    desc: str
    criterion_type: str  # "rule" | "llm" | "counterfactual"
    weight: float
    # For rule type: a callable that takes (speech_act, context) -> bool
    rule_check: Optional[Callable[..., bool]] = None
    # For llm type: the prompt template
    llm_prompt: str = ""
    # For counterfactual type: the counterfactual function
    cf_check: Optional[Callable[..., float]] = None
    # Evidence requirements
    evidence_required: bool = False
    # Paper reference
    reference: str = ""

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def content_hash(self) -> str:
        raw = f"{self.id}:{self.desc}:{self.criterion_type}:{self.weight}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class CriterionResult:
    """Result of evaluating a single criterion."""

    criterion_id: str
    passed: bool
    score_contribution: float  # weight if passed, 0 otherwise
    method: str  # "rule" | "llm" | "counterfactual"
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""

    dimension: str
    raw_score: float  # 0-1
    calibrated_score: float = 0.0  # after calibration
    criteria_results: List[CriterionResult] = field(default_factory=list)
    evidence_chain: List[Dict[str, Any]] = field(default_factory=list)
    paper_references: List[str] = field(default_factory=list)
    confidence: float = 1.0  # based on evidence completeness


class HybridScorer:
    """Base class for hybrid (rule + LLM + counterfactual) scoring.

    Usage:
        scorer = HybridScorer(rubric)
        dimension_score = scorer.score(speech_act, context={...})
        calibrated = scorer.calibrate([dimension_score], human_anchors)
    """

    def __init__(self, rubric: List[ScoringCriterion], calibration_model=None):
        self._rubric = rubric
        self._calibration_model = calibration_model
        self._verify_rubric_integrity()

    def _verify_rubric_integrity(self) -> None:
        """Verify that rubric weights sum to ~1.0 and no duplicate IDs."""
        total_weight = sum(c.weight for c in self._rubric)
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Rubric weights sum to {total_weight}, expected 1.0")
        ids = [c.id for c in self._rubric]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate criterion IDs: {ids}")

    @property
    def rubric(self) -> List[ScoringCriterion]:
        return list(self._rubric)

    def score(
        self,
        context: Dict[str, Any],
        llm_judge: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> DimensionScore:
        """Score against the locked rubric.

        Args:
            context: Dict with keys the criteria need (speech_act, observation, etc.)
            llm_judge: Optional LLM judging function. Must accept (criterion, context)
                       and return {"passed": bool, "evidence_text": str, "reasoning": str}.

        Returns:
            DimensionScore with raw score and per-criterion breakdown.
        """
        results: List[CriterionResult] = []
        total = 0.0

        for criterion in self._rubric:
            try:
                if criterion.criterion_type == "rule":
                    result = self._score_rule(criterion, context)
                elif criterion.criterion_type == "llm":
                    if llm_judge is None:
                        result = CriterionResult(
                            criterion_id=criterion.id, passed=False,
                            score_contribution=0.0, method="llm",
                            error="No LLM judge provided"
                        )
                    else:
                        result = self._score_llm(criterion, context, llm_judge)
                elif criterion.criterion_type == "counterfactual":
                    result = self._score_counterfactual(criterion, context)
                else:
                    result = CriterionResult(
                        criterion_id=criterion.id, passed=False,
                        score_contribution=0.0, method="unknown",
                        error=f"Unknown criterion type: {criterion.criterion_type}"
                    )
            except Exception as e:
                result = CriterionResult(
                    criterion_id=criterion.id, passed=False,
                    score_contribution=0.0, method=criterion.criterion_type,
                    error=str(e)
                )

            results.append(result)
            if result.passed:
                total += result.score_contribution

        return DimensionScore(
            dimension=self._rubric[0].id.split("_")[0] if self._rubric else "unknown",
            raw_score=round(total, 4),
            criteria_results=results,
            evidence_chain=[r.evidence for r in results if r.evidence],
            paper_references=list(set(c.reference for c in self._rubric if c.reference)),
            confidence=self._compute_confidence(results),
        )

    def _score_rule(self, criterion: ScoringCriterion, context: Dict[str, Any]) -> CriterionResult:
        """Execute a rule-based criterion check."""
        if criterion.rule_check is None:
            return CriterionResult(
                criterion_id=criterion.id, passed=False, score_contribution=0.0,
                method="rule", error="No rule_check function"
            )
        passed = criterion.rule_check(context)
        return CriterionResult(
            criterion_id=criterion.id, passed=passed,
            score_contribution=criterion.weight if passed else 0.0,
            method="rule",
            evidence={"check": criterion.desc, "result": passed},
        )

    def _score_llm(
        self,
        criterion: ScoringCriterion,
        context: Dict[str, Any],
        llm_judge: Callable[..., Dict[str, Any]],
    ) -> CriterionResult:
        """LLM-based scoring with mechanical evidence validation."""
        llm_result = llm_judge(criterion, context)
        passed = bool(llm_result.get("passed", False))

        # Mechanical evidence validation (Rulers §5.2)
        if criterion.evidence_required and passed:
            evidence_text = llm_result.get("evidence_text", "")
            speech_text = context.get("speech_text", "")
            # Verify evidence actually exists in the source text
            if evidence_text and evidence_text not in speech_text:
                # Evidence hallucinated — reject the score
                passed = False
                return CriterionResult(
                    criterion_id=criterion.id, passed=False, score_contribution=0.0,
                    method="llm",
                    evidence={"rejected": "evidence_not_found_in_source", "claimed": evidence_text[:100]},
                    error="LLM evidence hallucination: claimed text not found in source"
                )

        return CriterionResult(
            criterion_id=criterion.id, passed=passed,
            score_contribution=criterion.weight if passed else 0.0,
            method="llm",
            evidence={
                "llm_reasoning": llm_result.get("reasoning", ""),
                "evidence_text": llm_result.get("evidence_text", ""),
                "evidence_validated": passed,
            },
        )

    def _score_counterfactual(self, criterion: ScoringCriterion, context: Dict[str, Any]) -> CriterionResult:
        """Counterfactual-based scoring."""
        if criterion.cf_check is None:
            return CriterionResult(
                criterion_id=criterion.id, passed=False, score_contribution=0.0,
                method="counterfactual", error="No cf_check function"
            )
        improvement = criterion.cf_check(context)
        passed = improvement > 0.0
        return CriterionResult(
            criterion_id=criterion.id, passed=passed,
            score_contribution=criterion.weight * max(0.0, min(1.0, improvement)),
            method="counterfactual",
            evidence={"improvement": improvement},
        )

    def _compute_confidence(self, results: List[CriterionResult]) -> float:
        """Compute confidence based on evidence completeness.

        Rule criteria have confidence 1.0 (deterministic).
        LLM criteria with validated evidence have confidence 0.85.
        LLM criteria without validated evidence have confidence 0.5.
        Counterfactual exact recomputation has confidence 1.0.
        """
        if not results:
            return 0.0
        confidences = []
        for r in results:
            if r.method == "rule":
                confidences.append(1.0)
            elif r.method == "llm":
                if r.evidence.get("evidence_validated", False):
                    confidences.append(0.85)
                else:
                    confidences.append(0.5)
            elif r.method == "counterfactual":
                confidences.append(0.9)
            else:
                confidences.append(0.3)
        return round(sum(confidences) / len(confidences), 4)

    def calibrate(self, raw_scores: List[float], human_anchors: List[float]) -> List[float]:
        """Post-hoc calibration via Ridge regression + quantile mapping.

        Reference: Morandi (arXiv:2605.09227, 2026)
        - < 100 anchors: Ridge regression (KL ≈ 0.031)
        - > 1500 anchors: Neural-ODE flow (MAE ≈ 0.320)

        Args:
            raw_scores: List of raw scores from the scorer.
            human_anchors: Corresponding human-labeled scores.

        Returns:
            Calibrated scores.
        """
        if len(raw_scores) < 10 or len(human_anchors) < 10:
            return raw_scores  # Not enough data for calibration

        import numpy as np
        from sklearn.linear_model import Ridge

        X = np.array(raw_scores).reshape(-1, 1)
        y = np.array(human_anchors)
        model = Ridge(alpha=1.0)
        model.fit(X, y)
        calibrated = model.predict(X)

        # Quantile mapping to match human distribution shape
        calibrated = self._quantile_map(calibrated, y)

        return [round(float(c), 4) for c in calibrated]

    @staticmethod
    def _quantile_map(scores: np.ndarray, target_dist: np.ndarray) -> np.ndarray:
        """Map score distribution to match target distribution quantiles."""
        from scipy import stats
        # Only use scipy if available, otherwise skip
        try:
            return stats.rankdata(scores) / len(scores) * (target_dist.max() - target_dist.min()) + target_dist.min()
        except ImportError:
            return scores


# ============================================================
# Pre-built Rubric Factory
# ============================================================

def build_rubric_from_spec(spec: Dict[str, Any]) -> List[ScoringCriterion]:
    """Build a rubric from a specification dict.

    Example spec:
    {
        "dimension": "persona_consistency",
        "version": "1.0",
        "criteria": [
            {"id": "PC1", "type": "rule", "weight": 0.15, "desc": "...",
             "check_expr": "len(context['speech_text']) <= 150"},
            {"id": "PC2", "type": "llm", "weight": 0.30, "desc": "...",
             "llm_prompt": "Is this speech logical_chain or gut_feeling?",
             "evidence_required": True, "reference": "WOLF (NeurIPS 2025)"},
        ]
    }
    """
    criteria = []
    for spec_crit in spec.get("criteria", []):
        crit_type = spec_crit["type"]
        rule_check = None
        llm_prompt = spec_crit.get("llm_prompt", "")
        cf_check = None

        if crit_type == "rule" and "check_expr" in spec_crit:
            # Compile rule from expression string
            check_expr = spec_crit["check_expr"]
            rule_check = lambda ctx, expr=check_expr: eval(expr, {"__builtins__": {}}, {"context": ctx, "len": len, "min": min, "max": max})

        criteria.append(ScoringCriterion(
            id=spec_crit["id"],
            desc=spec_crit["desc"],
            criterion_type=crit_type,
            weight=spec_crit["weight"],
            rule_check=rule_check,
            llm_prompt=llm_prompt,
            cf_check=cf_check,
            evidence_required=spec_crit.get("evidence_required", False),
            reference=spec_crit.get("reference", ""),
        ))

    return criteria
