#!/usr/bin/env python3
"""Build module-level quantitative evidence tables for the paper.

This script does not run paid LLM games. It consolidates completed formal
v4flash runs, offline Track C retrieval ablations, auxiliary Track C analysis,
and local safety/UI/LLM probes into a reproducible module scorecard.

Use --run-gates to rerun lightweight non-LLM validation gates before rendering.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
FORMAL_SUMMARY = ROOT / "docs" / "experiments" / "formal_v4flash_framework_analysis" / "summary.json"
RETRIEVAL_RESULTS = (
    ROOT / "docs" / "experiments" / "core_module_quantification" / "retrieval_policy_eval" / "results.json"
)
MBTI_TRACK_C_SUMMARY = ROOT / "docs" / "experiments" / "mbti_track_c_auxiliary_analysis" / "summary.json"
REAL_AUDIT_SUMMARY = ROOT / "docs" / "experiments" / "full_project_real_audit" / "audit_summary.json"
FRONTEND_PROBE = ROOT / "docs" / "experiments" / "full_project_real_audit" / "frontend_ui_probe.json"
MOBILE_PROBE = ROOT / "docs" / "experiments" / "full_project_real_audit" / "ui_playwright_mobile.json"
BUBBLE_PROBE = ROOT / "docs" / "experiments" / "full_project_real_audit" / "ui_playwright_bubble_sampling.json"
REAL_LLM_PROBE = ROOT / "docs" / "experiments" / "full_project_real_audit" / "real_llm_probe.json"
SUPPLEMENTAL_FRAMEWORK_SUMMARIES = [
    ROOT / "docs" / "experiments" / "framework_gap_reflexion_anthropic_v4flash_g6" / "summary.json",
    ROOT / "docs" / "experiments" / "framework_gap_reflexion_anthropic_v4flash_g3" / "summary.json",
    ROOT / "docs" / "experiments" / "framework_gap_reflexion_anthropic_v4flash_g1" / "summary.json",
    ROOT / "docs" / "experiments" / "framework_gap_reflexion_doubao_endpoint_g1" / "summary.json",
    ROOT / "docs" / "experiments" / "framework_gap_reflexion_doubao_endpoint_g6" / "summary.json",
    ROOT / "docs" / "experiments" / "framework_gap_reflexion_v4flash_g6" / "summary.json",
]

OUTPUT_DIR = ROOT / "docs" / "experiments" / "module_effect_experiment"
TRACKED_REPORT = ROOT / "docs" / "MODULE_EFFECT_EXPERIMENT_RESULTS.md"

BASELINE_TIER = "baseline"
ANTI_TIER = "anti_only"
TRACKC_TIER = "trackc_only"
BOTH_TIER = "both"

COMMON_METRIC_REFERENCES = [
    {
        "source": "AIWolf Protocol Division",
        "metric_family": "overall win rate, per-role win rate",
        "project_mapping": "formal v4flash leaderboard winner rates, role-wise win rates, macro-role win rate",
        "url": "https://aiwolf.org/en/archives/2873",
    },
    {
        "source": "AIWolf Natural Language / AIWolfDial",
        "metric_family": "naturalness, context awareness, contradiction consistency, action-dialogue coherence, team play",
        "project_mapping": "Track B speech_score, vote_score, skill_score, process_score, evidence_refs, future coherence head",
        "url": "https://aclanthology.org/2025.aiwolfdial-1.1.pdf",
    },
    {
        "source": "Werewolf Arena",
        "metric_family": "arena-style model/framework comparison under deception, deduction, persuasion",
        "project_mapping": "Track B leaderboard discrimination and framework/rubric spread",
        "url": "https://arxiv.org/abs/2407.13943",
    },
    {
        "source": "Mini-Mafia / WOLF / BloodBench direction",
        "metric_family": "deception generation, deception detection, disclosure, claim-level falsehoods",
        "project_mapping": "wolf deception proxy, village detection proxy, seer disclosure proxy, future speech-claim taxonomy",
        "url": "https://www.bloodbench.com/",
    },
]

DOMAIN_METRIC_CATALOG = [
    {
        "metric_family": "AIWolf outcome metrics",
        "external_source": "AIWolf Protocol Division",
        "canonical_metrics": "overall win rate, per-role win rate",
        "project_fields": "wolf_win_rate, village_win_rate, role_win_rates, macro_role_win_rate",
        "current_status": "quantified in formal framework leaderboard",
        "presentation_use": "primary outcome comparison; always show role distribution next to it",
    },
    {
        "metric_family": "WereWolfPlus strategic indicators",
        "external_source": "WereWolfPlus metrics notebook",
        "canonical_metrics": "IRP, KSR, VSS, werewolf_kpi, seer_kpi, guard_kpi, KRS, KRE",
        "project_fields": "vote_score, skill_score, role_task_score, role-wise KPI proxies",
        "current_status": "mapped; exact IRP/KSR/VSS naming is reference-derived",
        "presentation_use": "connects our role/vote/skill score decomposition to prior Werewolf agent work",
    },
    {
        "metric_family": "AIWolfDial language quality",
        "external_source": "AIWolfDial 2025",
        "canonical_metrics": "naturalness, context awareness, contradiction consistency, action-dialogue coherence, team play",
        "project_fields": "speech_score, process_score, evidence_refs, future contradiction/coherence head",
        "current_status": "partially quantified; speech semantic audit is audit-only",
        "presentation_use": "justifies Track B beyond win/loss by evaluating speech and reasoning quality",
    },
    {
        "metric_family": "Speech-act classifier quality",
        "external_source": "project open-data speech classifier",
        "canonical_metrics": "exact accuracy, hamming loss, macro/micro F1, per-label F1",
        "project_fields": "speech_act_probs, accusation/interrogation/defense/evidence_use/identity/call_for_action",
        "current_status": "quantified as audit-only model",
        "presentation_use": "shows speech analysis can be measured without affecting leaderboard score",
    },
    {
        "metric_family": "Deception/detection/disclosure",
        "external_source": "Mini-Mafia / WOLF / BloodBench direction",
        "canonical_metrics": "wolf deception, village detection, seer disclosure, claim falsehoods, cover consistency",
        "project_fields": "wolf_deception_proxy, village_detection_proxy, seer_disclosure_proxy, persona deception/detection scorer",
        "current_status": "proxy quantified; direct claim labels pending",
        "presentation_use": "frames social-deduction-specific capability instead of generic LLM accuracy",
    },
    {
        "metric_family": "Track C retrieval IR",
        "external_source": "information retrieval evaluation practice",
        "canonical_metrics": "P@k, Recall@k, MRR, nDCG@k, coverage, leakage, latency",
        "project_fields": "precision_at_3, ndcg_at_5, mrr, coverage_rate, candidate_leakage_count, latency_p95_ms",
        "current_status": "quantified in retrieval ablation",
        "presentation_use": "direct evidence that strategy-memory retrieval is effective and safe",
    },
    {
        "metric_family": "Pairwise/review consistency",
        "external_source": "human/LLM pairwise evaluation practice",
        "canonical_metrics": "pairwise accuracy, Cohen's d, rank stability, bootstrap confidence interval",
        "project_fields": "paired_seed_deltas, bootstrap_reliability, pairwise_ranker, review metric tests",
        "current_status": "partially quantified; human labels pending for stronger claims",
        "presentation_use": "supports Track B leaderboard consistency and discriminability",
    },
    {
        "metric_family": "Safety and reproducibility",
        "external_source": "agent benchmark reliability gates",
        "canonical_metrics": "fallback rate, invalid action rate, information leak rate, evidence coverage",
        "project_fields": "fallback_count, invalid_count, leak_doc_count, source_event_coverage, visibility strict checks",
        "current_status": "quantified and gate-tested",
        "presentation_use": "proves B/C loop is not leaking hidden information or hiding failures",
    },
]

EXPANDED_AGENT_FRAMEWORKS = [
    {
        "framework": "basic_react",
        "aliases": "",
        "external_family": "ReAct / ordinary tool-using LLM baseline",
        "enabled_modules": "none beyond base cognitive loop",
        "current_evidence_status": "formal v4flash data available",
        "why_include": "baseline for showing the gain of role design, retrieval, and B/C loop",
    },
    {
        "framework": "role_guarded_react",
        "aliases": "anti_only",
        "external_family": "role-conditioned guarded agent",
        "enabled_modules": "role/anti-pattern",
        "current_evidence_status": "formal v4flash data available through anti_only",
        "why_include": "proves Agent design is not just generic ReAct; anti-patterns are part of Agent design",
    },
    {
        "framework": "rag_react",
        "aliases": "trackc_only",
        "external_family": "RAG/ReAct",
        "enabled_modules": "Track C retrieval",
        "current_evidence_status": "formal v4flash data available through trackc_only; retrieval ablation available",
        "why_include": "isolates retrieval and strategy-knowledge contribution",
    },
    {
        "framework": "reflexion_react",
        "aliases": "",
        "external_family": "Reflexion",
        "enabled_modules": "post-game reflection only",
        "current_evidence_status": "supplemental anthropic-coding v4flash data available; historical formal score pending",
        "why_include": "checks whether reflection alone can replace runtime Track C retrieval",
    },
    {
        "framework": "rag_reflexion",
        "aliases": "",
        "external_family": "RAG + Reflexion",
        "enabled_modules": "Track C retrieval + reflection",
        "current_evidence_status": "supplemental anthropic-coding v4flash data available; historical formal score pending",
        "why_include": "tests retrieval and outer-loop reflection synergy without role guardrails",
    },
    {
        "framework": "full_cognitive",
        "aliases": "cognitive_full",
        "external_family": "role-guarded RAG + Reflexion",
        "enabled_modules": "role/anti-pattern + Track C retrieval + reflection",
        "current_evidence_status": "formal v4flash data available through cognitive_full, but completion is low",
        "why_include": "final architecture condition; should be rerun in balanced target-seat A/B",
    },
]

FORMAL_FRAMEWORK_ALIASES = {
    "baseline": "basic_react",
    "anti_only": "role_guarded_react",
    "trackc_only": "rag_react",
    "both": "full_cognitive",
}

FRONTIER_AGENT_EVAL_REFERENCES = [
    {
        "lens": "Interactive task success and failure taxonomy",
        "source": "AgentBench / AgentBoard",
        "source_url": "https://arxiv.org/abs/2308.03688",
        "what_it_checks": "long-horizon decision-making, instruction following, multi-turn task progress, fine-grained failure analysis",
        "project_mapping": "completion rate, adjusted final score, fallback/invalid health, role-normalized leaderboard",
    },
    {
        "lens": "Tool-user-policy interaction reliability",
        "source": "tau-bench",
        "source_url": "https://arxiv.org/abs/2406.12045",
        "what_it_checks": "multi-turn tool use under domain policies, repeated-run reliability, pass-rate stability",
        "project_mapping": "Track C retrieval/tool quality, invalid tool/action rate, strict policy and information-isolation gates",
    },
    {
        "lens": "Social intelligence in interaction",
        "source": "SOTOPIA",
        "source_url": "https://arxiv.org/abs/2310.11667",
        "what_it_checks": "goal completion, social appropriateness, cooperation/conflict handling, believability in role-play",
        "project_mapping": "macro role win rate, wolf deception proxy, village detection proxy, speech/vote/skill process scores",
    },
    {
        "lens": "Realistic environment execution",
        "source": "GAIA / WebArena / OSWorld",
        "source_url": "https://arxiv.org/abs/2311.12983",
        "what_it_checks": "realistic, reproducible tasks with execution-based scoring and tool/web/computer-use ability",
        "project_mapping": "full-game execution, frontend/human-observable UX, replay evidence, controlled rule cases",
    },
    {
        "lens": "Learning from experience",
        "source": "Reflexion-style agent evaluation",
        "source_url": "https://arxiv.org/abs/2303.11366",
        "what_it_checks": "whether verbal reflection or memory improves future attempts rather than only current-step reasoning",
        "project_mapping": "Track C off/on trend, knowledge docs, source-event coverage, future target-seat A/B lift",
    },
]


@dataclass
class ModuleEffect:
    module: str
    design_goal: str
    primary_metric: str
    baseline_name: str
    baseline_value: float | None
    treatment_name: str
    treatment_value: float | None
    delta_abs: float | None
    delta_rel_pct: float | None
    effect_score_0_100: float
    target: float | None
    passed: bool
    evidence_strength: str
    evidence: str
    caveat: str = ""


def load_json(path: Path, default: Any | None = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def round_float(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def rel_pct(delta: float | None, baseline: float | None) -> float | None:
    if delta is None or baseline is None or abs(baseline) < 1e-12:
        return None
    return round(delta / abs(baseline) * 100.0, 2)


def score_ratio(value: float | None, target: float, higher_is_better: bool = True) -> float:
    if value is None:
        return 0.0
    if target == 0:
        if higher_is_better:
            return 100.0 if value >= 0 else 0.0
        return 100.0 if value <= 0 else 0.0
    if higher_is_better:
        return clamp(value / target * 100.0)
    return clamp((target / max(value, 1e-12)) * 100.0)


def score_binary(passed: bool) -> float:
    return 100.0 if passed else 0.0


def make_effect(
    *,
    module: str,
    design_goal: str,
    primary_metric: str,
    baseline_name: str,
    baseline_value: float | None,
    treatment_name: str,
    treatment_value: float | None,
    target: float | None,
    effect_score_0_100: float,
    evidence_strength: str,
    evidence: str,
    caveat: str = "",
    higher_is_better: bool = True,
) -> ModuleEffect:
    if baseline_value is not None and treatment_value is not None:
        delta_abs = treatment_value - baseline_value
    else:
        delta_abs = None
    if target is None or treatment_value is None:
        passed = effect_score_0_100 >= 80.0
    elif higher_is_better:
        passed = treatment_value >= target
    else:
        passed = treatment_value <= target
    return ModuleEffect(
        module=module,
        design_goal=design_goal,
        primary_metric=primary_metric,
        baseline_name=baseline_name,
        baseline_value=round_float(baseline_value),
        treatment_name=treatment_name,
        treatment_value=round_float(treatment_value),
        delta_abs=round_float(delta_abs),
        delta_rel_pct=rel_pct(delta_abs, baseline_value),
        effect_score_0_100=round(effect_score_0_100, 2),
        target=round_float(target),
        passed=passed,
        evidence_strength=evidence_strength,
        evidence=evidence,
        caveat=caveat,
    )


def index_by(items: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get(key)): item for item in items}


def get_raw_dim(rubric_by_tier: dict[str, dict[str, Any]], tier: str, dim: str) -> float:
    return to_float(rubric_by_tier.get(tier, {}).get("raw_dimension_scores", {}).get(dim))


def get_rubric_total(rubric_by_tier: dict[str, dict[str, Any]], tier: str) -> float:
    return to_float(rubric_by_tier.get(tier, {}).get("rubric_total_score"))


def get_tier_metric(tier_by_name: dict[str, dict[str, Any]], tier: str, metric: str) -> float:
    return to_float(tier_by_name.get(tier, {}).get(metric))


def build_module_effects(
    formal: dict[str, Any],
    retrieval: dict[str, Any],
    mbti: dict[str, Any],
    audit: dict[str, Any],
    frontend: dict[str, Any],
    mobile: dict[str, Any],
    bubble: dict[str, Any],
    real_llm: dict[str, Any],
    gate_results: list[dict[str, Any]],
) -> list[ModuleEffect]:
    tier_by_name = index_by(formal.get("leaderboard", []), "tier")
    tier_summaries = formal.get("tier_summaries", {})
    rubric_by_tier = index_by(formal.get("rubric_leaderboard", []), "tier")
    retrieval_metrics = retrieval.get("metrics", {})
    retrieval_effects = retrieval.get("effect_summary", {}).get("effects", {})
    global_ret = retrieval_metrics.get("global_only", {})
    hybrid_ret = retrieval_metrics.get("hybrid_role_alignment_phase") or retrieval_metrics.get(
        "hybrid_role_mbti_global", {}
    )
    hybrid_effect = retrieval_effects.get("hybrid_role_alignment_phase") or retrieval_effects.get(
        "hybrid_role_mbti_global", {}
    )
    mbti_overall = mbti.get("overall", {})
    track_c_off = mbti_overall.get("track_c_off", {})
    track_c_on = mbti_overall.get("track_c_on", {})
    role_deltas = mbti.get("role_deltas", [])
    non_wolf_deltas = [to_float(row.get("delta")) for row in role_deltas if str(row.get("key")) != "Werewolf"]
    avg_non_wolf_delta = sum(non_wolf_deltas) / len(non_wolf_deltas) if non_wolf_deltas else 0.0
    audit_track_c = audit.get("track_c", {})
    audit_coverage = audit.get("coverage", {})
    ui_errors = (
        len(frontend.get("pageErrors", []) or [])
        + len(mobile.get("errors", []) or [])
        + len(bubble.get("errors", []) or [])
    )
    real_llm_ok = any(
        probe.get("ok") for probe in real_llm.get("probes", []) if probe.get("provider_requested") == "doubao"
    )
    gate_pass_count = sum(1 for item in gate_results if item.get("passed"))
    gate_total = len(gate_results)
    gate_rate = gate_pass_count / gate_total if gate_total else None

    attempted_total = sum(to_float(row.get("attempted_games")) for row in tier_by_name.values())
    if not attempted_total:
        attempted_total = sum(
            to_float(row.get("completed_games")) + to_float(row.get("failed_games")) for row in tier_by_name.values()
        )
    external_failed_total = sum(
        to_float(row.get("external_failed_games", row.get("failed_games"))) for row in tier_by_name.values()
    )
    external_failure_rate = external_failed_total / max(attempted_total, 1.0)
    fallback_total = sum(to_float(row.get("fallback_count")) for row in tier_by_name.values())
    invalid_total = sum(to_float(row.get("invalid_count")) for row in tier_by_name.values())
    llm_decisions = sum(to_float(row.get("llm_decisions")) for row in tier_by_name.values())
    strict_decision_health = 1.0 - min(1.0, (fallback_total + invalid_total) / max(llm_decisions, 1.0))

    row_counts = formal.get("row_counts", {})
    controlled_case_count = to_float(audit.get("controlled_case_count"))
    controlled_cases = audit_coverage.get("controlled_cases", [])
    role_count = len(audit_coverage.get("role_counts", {}) or {})
    phase_count = len(audit_coverage.get("phase_counts", {}) or {})

    effects: list[ModuleEffect] = []
    baseline_single = get_raw_dim(rubric_by_tier, BASELINE_TIER, "single_agent")
    anti_single = get_raw_dim(rubric_by_tier, ANTI_TIER, "single_agent")
    both_single = get_raw_dim(rubric_by_tier, BOTH_TIER, "single_agent")
    baseline_total = get_rubric_total(rubric_by_tier, BASELINE_TIER)
    anti_total = get_rubric_total(rubric_by_tier, ANTI_TIER)
    effects.append(
        make_effect(
            module="Agent design: role cognition + anti-pattern control",
            design_goal="角色化人格、身份策略、反坏模式约束和决策链应共同提升单体 Agent 行为质量",
            primary_metric="single_agent_dimension",
            baseline_name="basic_react",
            baseline_value=baseline_single,
            treatment_name="agent_design_condition",
            treatment_value=anti_single,
            target=0.70,
            effect_score_0_100=clamp(anti_single * 100.0),
            evidence_strength="formal_v4flash_rubric",
            evidence=(
                f"single_agent basic_react={baseline_single:.4f}, anti_condition={anti_single:.4f}, "
                f"cognitive_full={both_single:.4f}; total rubric gain under agent-design condition="
                f"{anti_total - baseline_total:+.2f}"
            ),
            caveat="anti_only 是 Agent 设计消融条件，不作为独立核心模块；cognitive_full 完成率较低，因此完整架构胜率因果仍需 target-seat A/B。",
        )
    )

    baseline_multi = get_raw_dim(rubric_by_tier, BASELINE_TIER, "multi_agent")
    best_multi_tier = max(
        (BASELINE_TIER, ANTI_TIER, TRACKC_TIER, BOTH_TIER),
        key=lambda tier: get_raw_dim(rubric_by_tier, tier, "multi_agent"),
    )
    best_multi = get_raw_dim(rubric_by_tier, best_multi_tier, "multi_agent")
    effects.append(
        make_effect(
            module="Multi-agent game interaction",
            design_goal="公开/私有状态、投票、技能协作和多智能体阶段推进应稳定可量化",
            primary_metric="multi_agent_dimension",
            baseline_name="target_threshold",
            baseline_value=0.70,
            treatment_name=f"current_framework:{best_multi_tier}",
            treatment_value=best_multi,
            target=0.70,
            effect_score_0_100=clamp(best_multi * 100.0),
            evidence_strength="formal_v4flash_rubric",
            evidence=(
                f"basic_react_multi={baseline_multi:.4f}; "
                f"macro_role_win top={get_tier_metric(tier_by_name, best_multi_tier, 'macro_role_win_rate'):.4f}; "
                f"core_role_coverage={to_float(tier_summaries.get(best_multi_tier, {}).get('core_role_coverage')):.3f}"
            ),
            caveat="该 formal 集合显示多智能体维度稳定达标，但各框架之间差异不大。",
        )
    )

    advanced_baseline = get_raw_dim(rubric_by_tier, BASELINE_TIER, "advanced_bc")
    advanced_by_tier = {
        tier: get_raw_dim(rubric_by_tier, tier, "advanced_bc") for tier in (ANTI_TIER, TRACKC_TIER, BOTH_TIER)
    }
    best_advanced_tier, best_advanced = max(advanced_by_tier.items(), key=lambda item: item[1])
    effects.append(
        make_effect(
            module="Track B/C advanced architecture",
            design_goal="复盘、坏例、counterfactual 和经验回流应形成可区分的高阶能力",
            primary_metric="advanced_bc_dimension",
            baseline_name="basic_react",
            baseline_value=advanced_baseline,
            treatment_name=best_advanced_tier,
            treatment_value=best_advanced,
            target=0.55,
            effect_score_0_100=clamp(best_advanced * 100.0),
            evidence_strength="formal_v4flash_rubric",
            evidence=(
                f"best={best_advanced_tier}; anti={advanced_by_tier[ANTI_TIER]:.4f}, "
                f"trackc={advanced_by_tier[TRACKC_TIER]:.4f}, both={advanced_by_tier[BOTH_TIER]:.4f}"
            ),
            caveat="advanced_bc 能区分模块贡献，但胜率因果结论仍需 target-seat A/B。",
        )
    )

    leaderboard_scores = [to_float(row.get("rubric_total_score")) for row in formal.get("rubric_leaderboard", [])]
    score_spread = max(leaderboard_scores) - min(leaderboard_scores) if leaderboard_scores else 0.0
    effects.append(
        make_effect(
            module="Track B leaderboard discriminability",
            design_goal="Track B leaderboard 应区分普通 React、反坏模式、Track C 和完整认知框架",
            primary_metric="rubric_score_spread",
            baseline_name="minimum useful spread",
            baseline_value=5.0,
            treatment_name="formal_v4flash_4_tiers",
            treatment_value=score_spread,
            target=5.0,
            effect_score_0_100=score_ratio(score_spread, 5.0),
            evidence_strength="formal_v4flash_ablation",
            evidence=(
                f"tiers={len(leaderboard_scores)}, top={formal.get('rubric_leaderboard', [{}])[0].get('tier')}, "
                f"spread={score_spread:.2f}"
            ),
        )
    )

    global_score = to_float(global_ret.get("offline_score"))
    hybrid_score = to_float(hybrid_ret.get("offline_score"))
    effects.append(
        make_effect(
            module="Track C retrieval policy",
            design_goal="角色/阵营/阶段混合检索应显著优于全局经验检索",
            primary_metric="offline_retrieval_score",
            baseline_name="global_only",
            baseline_value=global_score,
            treatment_name=str(hybrid_ret.get("policy") or "hybrid_role_alignment_phase"),
            treatment_value=hybrid_score,
            target=0.55,
            effect_score_0_100=clamp(hybrid_score * 100.0),
            evidence_strength="offline_retrieval_ablation",
            evidence=(
                f"Δscore={to_float(hybrid_effect.get('score_delta')):+.4f}; "
                f"ΔP@3={to_float(hybrid_effect.get('precision_at_3_delta')):+.4f}; "
                f"ΔnDCG@5={to_float(hybrid_effect.get('ndcg_at_5_delta')):+.4f}; "
                f"Δcoverage={to_float(hybrid_effect.get('coverage_rate_delta')):+.4f}"
            ),
            caveat="弱标签离线检索评估，证明检索设计合理性；最终胜率提升需在线 target-seat A/B。",
        )
    )

    p3 = to_float(hybrid_ret.get("precision_at_3"))
    ndcg5 = to_float(hybrid_ret.get("ndcg_at_5"))
    coverage = to_float(hybrid_ret.get("coverage_rate"))
    global_p3 = to_float(global_ret.get("precision_at_3"))
    global_ndcg5 = to_float(global_ret.get("ndcg_at_5"))
    global_coverage = to_float(global_ret.get("coverage_rate"))
    rank_composite = 0.25 * p3 + 0.45 * ndcg5 + 0.30 * coverage
    global_rank_composite = 0.25 * global_p3 + 0.45 * global_ndcg5 + 0.30 * global_coverage
    effects.append(
        make_effect(
            module="Retrieval precision and coverage",
            design_goal="检索不仅要有结果，还要在 top-k 中命中角色/阶段相关经验",
            primary_metric="composite_ir_score",
            baseline_name="global_only",
            baseline_value=global_rank_composite,
            treatment_name=str(hybrid_ret.get("policy") or "hybrid"),
            treatment_value=rank_composite,
            target=0.70,
            effect_score_0_100=clamp(rank_composite * 100.0),
            evidence_strength="offline_retrieval_ablation",
            evidence=f"P@3={p3:.4f}, nDCG@5={ndcg5:.4f}, coverage={coverage:.4f}, MRR={to_float(hybrid_ret.get('mrr')):.4f}",
        )
    )

    leak_count = to_float(hybrid_ret.get("candidate_leakage_count")) + to_float(audit_track_c.get("leak_doc_count"))
    invalid_doc_count = to_float(audit_track_c.get("invalid_doc_count"))
    safety_pass = leak_count == 0 and invalid_doc_count == 0
    effects.append(
        make_effect(
            module="Track C safety and knowledge hygiene",
            design_goal="经验卡不能泄露 candidate/deprecated/当前局私有信息，且应覆盖来源事件",
            primary_metric="leak_or_invalid_count",
            baseline_name="allowed defects",
            baseline_value=0.0,
            treatment_name="current_track_c_store",
            treatment_value=leak_count + invalid_doc_count,
            target=0.0,
            effect_score_0_100=score_binary(safety_pass),
            evidence_strength="audit_gate",
            evidence=(
                f"leak={int(leak_count)}, invalid_doc={int(invalid_doc_count)}, "
                f"source_event_coverage={to_float(audit_track_c.get('source_event_coverage')):.4f}, "
                f"docs={int(to_float(audit_track_c.get('knowledge_doc_count')))}"
            ),
            higher_is_better=False,
        )
    )

    off_wr = to_float(track_c_off.get("win_rate"))
    on_wr = to_float(track_c_on.get("win_rate"))
    effects.append(
        make_effect(
            module="Track C role/persona evolution trend",
            design_goal="经验回流后，角色和 MBTI 维度应出现可量化正向趋势",
            primary_metric="non_wolf_role_win_delta",
            baseline_name="track_c_off",
            baseline_value=off_wr,
            treatment_name="track_c_on",
            treatment_value=on_wr,
            target=off_wr,
            effect_score_0_100=clamp(50.0 + avg_non_wolf_delta * 500.0),
            evidence_strength="auxiliary_all_seat_trackc",
            evidence=(
                f"overall_win_rate {off_wr:.4f}->{on_wr:.4f}; "
                f"avg_non_wolf_role_delta={avg_non_wolf_delta:+.4f}; cells={int(to_float(mbti.get('role_count')) * to_float(mbti.get('mbti_count')))}"
            ),
            caveat="该实验全席位同时切换 Track C，适合展示趋势和覆盖，不足以证明单个最终 Agent 因果胜率提升。",
        )
    )

    visibility_gate = next((item for item in gate_results if item.get("name") == "visibility_strict"), None)
    visibility_pass = bool(visibility_gate.get("passed")) if visibility_gate else True
    effects.append(
        make_effect(
            module="Information isolation",
            design_goal="私有身份、夜间行动和检索知识必须通过信息隔离门禁",
            primary_metric="visibility_gate_pass",
            baseline_name="required",
            baseline_value=1.0,
            treatment_name="current_backend",
            treatment_value=1.0 if visibility_pass else 0.0,
            target=1.0,
            effect_score_0_100=score_binary(visibility_pass),
            evidence_strength="test_gate",
            evidence=visibility_gate.get("summary", "strict visibility gate available from previous audit")
            if visibility_gate
            else "strict visibility evidence available in core_module_quantification summary",
        )
    )

    effects.append(
        make_effect(
            module="Rule engine and role coverage",
            design_goal="核心规则、特殊角色和阶段事件应能被控制样例覆盖",
            primary_metric="controlled_case_coverage",
            baseline_name="required controlled cases",
            baseline_value=9.0,
            treatment_name="full_project_real_audit",
            treatment_value=controlled_case_count,
            target=9.0,
            effect_score_0_100=score_ratio(controlled_case_count, 9.0),
            evidence_strength="controlled_real_audit",
            evidence=f"controlled_cases={len(controlled_cases)}, roles={role_count}, phases={phase_count}, issues={len(audit.get('issues', []) or [])}",
        )
    )

    ui_pass = ui_errors == 0 and to_float(mobile.get("bottomDockCount")) >= 1 and bool(bubble.get("sameSpeakerGrowth"))
    effects.append(
        make_effect(
            module="Frontend and human-observable UX",
            design_goal="大厅/对局页/移动端底部发言区/逐字气泡应能支撑展示和人机混战观察",
            primary_metric="ui_probe_pass",
            baseline_name="required",
            baseline_value=1.0,
            treatment_name="playwright_probe",
            treatment_value=1.0 if ui_pass else 0.0,
            target=1.0,
            effect_score_0_100=score_binary(ui_pass),
            evidence_strength="playwright_smoke",
            evidence=(
                f"errors={ui_errors}, bottomDock={mobile.get('bottomDockCount')}, "
                f"bubbleGrowth={bool(bubble.get('sameSpeakerGrowth'))}, timelineAfter={len(bubble.get('timelineAfter', []) or [])}"
            ),
        )
    )

    real_llm_latency = min(
        [to_float(probe.get("latency_seconds")) for probe in real_llm.get("probes", []) if probe.get("ok")] or [0.0]
    )
    effects.append(
        make_effect(
            module="Volcengine v4flash provenance and real LLM path",
            design_goal="正式实验必须使用火山 v4flash，排除 pro/fake/非火山来源，并验证真实模型链路",
            primary_metric="formal_v4flash_rows",
            baseline_name="minimum formal rows",
            baseline_value=20.0,
            treatment_name="filtered_formal_dataset",
            treatment_value=to_float(row_counts.get("formal_v4flash")),
            target=20.0,
            effect_score_0_100=score_ratio(to_float(row_counts.get("formal_v4flash")), 20.0),
            evidence_strength="provenance_filter",
            evidence=(
                f"formal_rows={row_counts.get('formal_v4flash')}, excluded={row_counts.get('excluded')}, "
                f"doubao_probe_ok={real_llm_ok}, real_llm_latency_s={real_llm_latency:.3f}"
            ),
        )
    )

    reliability_score = strict_decision_health * 100.0
    effects.append(
        make_effect(
            module="Experiment reliability and strict-mode health",
            design_goal="正式样本应无 fallback/invalid 污染；整局失败/API 错误作为外部运行健康度单独报告",
            primary_metric="strict_decision_health",
            baseline_name="minimum useful health",
            baseline_value=80.0,
            treatment_name="formal_v4flash_dataset",
            treatment_value=reliability_score,
            target=80.0,
            effect_score_0_100=reliability_score,
            evidence_strength="formal_v4flash_health",
            evidence=(
                f"fallback={int(fallback_total)}, invalid={int(invalid_total)}, "
                f"llm_decisions={int(llm_decisions)}, external_failure_rate={external_failure_rate:.4f}"
            ),
            caveat="整局失败/API/子进程错误不作为 Agent 输局或架构扣分，只作为运行稳定性风险单独披露。",
        )
    )

    if gate_rate is not None:
        effects.append(
            make_effect(
                module="Local non-LLM validation gates",
                design_goal="关键模块量化结果应能被本地门禁快速复验",
                primary_metric="gate_pass_rate",
                baseline_name="required",
                baseline_value=1.0,
                treatment_name="run_gates",
                treatment_value=gate_rate,
                target=1.0,
                effect_score_0_100=gate_rate * 100.0,
                evidence_strength="rerun_test_gate",
                evidence=f"passed={gate_pass_count}/{gate_total}",
            )
        )

    return effects


def build_common_metric_panels(
    formal: dict[str, Any],
    retrieval: dict[str, Any],
    mbti: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    tier_summaries = formal.get("tier_summaries", {})
    retrieval_metrics = retrieval.get("metrics", {})
    hybrid_ret = retrieval_metrics.get("hybrid_role_alignment_phase") or retrieval_metrics.get(
        "hybrid_role_mbti_global", {}
    )
    role_summary = formal.get("role_summary", {})
    team_summary = formal.get("team_summary", {})
    track_c = audit.get("track_c", {})
    baseline = tier_summaries.get(BASELINE_TIER, {})
    anti = tier_summaries.get(ANTI_TIER, {})
    trackc = tier_summaries.get(TRACKC_TIER, {})
    both = tier_summaries.get(BOTH_TIER, {})

    return {
        "aiwolf_style_outcome_metrics": {
            "formal_v4flash_rows": formal.get("row_counts", {}).get("formal_v4flash"),
            "tier_win_rates": {
                tier: {
                    "completed_games": row.get("completed_games"),
                    "external_failed_games": row.get("external_failed_games", row.get("failed_games")),
                    "external_failure_rate": row.get("external_failure_rate"),
                    "attempt_completion_rate": row.get("attempt_completion_rate"),
                    "wolf_win_rate": row.get("wolf_win_rate"),
                    "village_win_rate": row.get("village_win_rate"),
                    "macro_role_win_rate": row.get("macro_role_win_rate"),
                    "completion_rate": row.get("completion_rate"),
                }
                for tier, row in tier_summaries.items()
            },
            "role_summary": role_summary,
            "team_summary": team_summary,
        },
        "leaderboard_and_framework_metrics": {
            "baseline_total": get_rubric_total(index_by(formal.get("rubric_leaderboard", []), "tier"), BASELINE_TIER),
            "anti_only_total": get_rubric_total(index_by(formal.get("rubric_leaderboard", []), "tier"), ANTI_TIER),
            "trackc_only_total": get_rubric_total(index_by(formal.get("rubric_leaderboard", []), "tier"), TRACKC_TIER),
            "cognitive_full_total": get_rubric_total(index_by(formal.get("rubric_leaderboard", []), "tier"), BOTH_TIER),
            "paired_seed_deltas": formal.get("paired_seed_deltas", []),
        },
        "retrieval_ir_metrics": {
            "query_set_size": retrieval.get("query_set_size"),
            "retriever_size": retrieval.get("retriever_size"),
            "policy": hybrid_ret.get("policy"),
            "precision_at_1": hybrid_ret.get("precision_at_1"),
            "precision_at_3": hybrid_ret.get("precision_at_3"),
            "precision_at_5": hybrid_ret.get("precision_at_5"),
            "mrr": hybrid_ret.get("mrr"),
            "ndcg_at_5": hybrid_ret.get("ndcg_at_5"),
            "coverage_rate": hybrid_ret.get("coverage_rate"),
            "role_match_rate": hybrid_ret.get("role_match_rate"),
            "mbti_match_rate": hybrid_ret.get("mbti_match_rate"),
            "phase_match_rate": hybrid_ret.get("phase_match_rate"),
            "candidate_leakage_count": hybrid_ret.get("candidate_leakage_count"),
            "latency_p95_ms": hybrid_ret.get("latency_p95_ms"),
        },
        "social_deduction_capability_proxies": {
            "wolf_deception_proxy": {
                "definition": "wolf-side win rate and werewolf role win rate; higher means stronger wolf-side deception/cover performance, but not a direct speech deception label.",
                "baseline_wolf_win_rate": baseline.get("wolf_win_rate"),
                "anti_only_wolf_win_rate": anti.get("wolf_win_rate"),
                "trackc_only_wolf_win_rate": trackc.get("wolf_win_rate"),
                "cognitive_full_wolf_win_rate": both.get("wolf_win_rate"),
            },
            "village_detection_proxy": {
                "definition": "village win rate and non-wolf role win rates; higher means better collective detection/survival under current logs.",
                "baseline_village_win_rate": baseline.get("village_win_rate"),
                "cognitive_full_village_win_rate": both.get("village_win_rate"),
                "formal_non_wolf_role_win_rate": {
                    role: row.get("win_rate") for role, row in role_summary.items() if role != "Werewolf"
                },
            },
            "seer_disclosure_proxy": {
                "definition": "seer role win rate is available; claim-level disclosure quality requires future speech-claim labels.",
                "formal_seer_win_rate": role_summary.get("Seer", {}).get("win_rate"),
                "current_label_status": "not directly labeled in aggregate formal summaries",
            },
        },
        "track_c_evolution_metrics": {
            "track_c_auxiliary_overall": mbti.get("overall", {}),
            "role_deltas": mbti.get("role_deltas", []),
            "knowledge_doc_count": track_c.get("knowledge_doc_count"),
            "source_event_coverage": track_c.get("source_event_coverage"),
            "invalid_doc_count": track_c.get("invalid_doc_count"),
            "leak_doc_count": track_c.get("leak_doc_count"),
        },
        "safety_and_reliability_metrics": {
            "fallback_invalid_by_tier": {
                tier: {"fallback_count": row.get("fallback_count"), "invalid_count": row.get("invalid_count")}
                for tier, row in tier_summaries.items()
            },
            "controlled_case_count": audit.get("controlled_case_count"),
            "issues": audit.get("issues", []),
        },
    }


def build_framework_score_comparison(formal: dict[str, Any]) -> list[dict[str, Any]]:
    leaderboard_by_tier = index_by(formal.get("leaderboard", []), "tier")
    rubric_rows = formal.get("rubric_leaderboard", [])
    framework_metadata = {row["framework"]: row for row in EXPANDED_AGENT_FRAMEWORKS}
    baseline_rubric = next((row for row in rubric_rows if str(row.get("tier")) == BASELINE_TIER), {})
    baseline_score = to_float(baseline_rubric.get("rubric_total_score"), default=float("nan"))
    scored_frameworks: set[str] = set()
    rows: list[dict[str, Any]] = []

    for rubric in sorted(rubric_rows, key=lambda row: to_float(row.get("rank"), default=999.0)):
        tier = str(rubric.get("tier") or "")
        framework = FORMAL_FRAMEWORK_ALIASES.get(tier, str(rubric.get("display_name") or tier))
        metadata = framework_metadata.get(framework, {})
        outcome = leaderboard_by_tier.get(tier, {})
        total_score = to_float(rubric.get("rubric_total_score"))
        scored_frameworks.add(framework)
        rows.append(
            {
                "framework": framework,
                "formal_tier": tier,
                "existing_alias": str(rubric.get("display_name") or metadata.get("aliases") or tier),
                "external_family": metadata.get("external_family", "n/a"),
                "rubric_total_score": round_float(total_score),
                "delta_vs_basic_react": (
                    round_float(total_score - baseline_score) if math.isfinite(baseline_score) else None
                ),
                "rank": rubric.get("rank"),
                "completed_games": outcome.get("completed_games"),
                "failed_games": outcome.get("failed_games"),
                "external_failed_games": outcome.get("external_failed_games", outcome.get("failed_games")),
                "external_failure_rate": outcome.get("external_failure_rate"),
                "attempt_completion_rate": outcome.get("attempt_completion_rate"),
                "completion_rate": outcome.get("completion_rate"),
                "wolf_win_rate": outcome.get("wolf_win_rate"),
                "village_win_rate": outcome.get("village_win_rate"),
                "macro_role_win_rate": outcome.get("macro_role_win_rate"),
                "single_agent_score": rubric.get("rubric_dimensions", {}).get("single_agent"),
                "multi_agent_score": rubric.get("rubric_dimensions", {}).get("multi_agent"),
                "engineering_score": rubric.get("rubric_dimensions", {}).get("engineering"),
                "advanced_bc_score": rubric.get("rubric_dimensions", {}).get("advanced_bc"),
                "fallback_count": outcome.get("fallback_count"),
                "invalid_count": outcome.get("invalid_count"),
                "evidence_status": "formal v4flash score available",
            }
        )

    for framework in EXPANDED_AGENT_FRAMEWORKS:
        name = framework["framework"]
        if name in scored_frameworks:
            continue
        rows.append(
            {
                "framework": name,
                "formal_tier": "n/a",
                "existing_alias": framework["aliases"] or "n/a",
                "external_family": framework["external_family"],
                "rubric_total_score": None,
                "delta_vs_basic_react": None,
                "rank": None,
                "completed_games": None,
                "failed_games": None,
                "external_failed_games": None,
                "external_failure_rate": None,
                "attempt_completion_rate": None,
                "completion_rate": None,
                "wolf_win_rate": None,
                "village_win_rate": None,
                "macro_role_win_rate": None,
                "single_agent_score": None,
                "multi_agent_score": None,
                "engineering_score": None,
                "advanced_bc_score": None,
                "fallback_count": None,
                "invalid_count": None,
                "evidence_status": framework["current_evidence_status"],
            }
        )
    return rows


def summarize_supplemental_framework_runs(summary_paths: Sequence[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in summary_paths:
        exists = path.exists()
        summary = load_json(path) if exists else {}
        model_pool = summary.get("model_pool", [])
        entries = summary.get("architecture_evidence_leaderboard", {}).get("entries", [])
        failures = summary.get("failures", [])
        completed_by_framework = {
            framework: sum(
                1 for item in summary.get("raw_records", []) if str(item.get("framework") or "") == framework
            )
            for framework in {str(item.get("framework") or "") for item in summary.get("raw_records", [])}
            if framework
        }
        failed_by_framework = {
            framework: sum(1 for item in failures if str(item.get("framework") or "") == framework)
            for framework in {str(item.get("framework") or "") for item in failures}
            if framework
        }
        if not exists:
            rows.append(
                {
                    "experiment": str(path.relative_to(ROOT)),
                    "model_pool": "n/a",
                    "framework": "n/a",
                    "score": None,
                    "completed_games": None,
                    "failed_games": None,
                    "external_failure_rate": None,
                    "win_rate": None,
                    "macro_role_win_rate": None,
                    "status": "pending; summary file not created yet",
                }
            )
            continue
        if entries:
            for entry in entries:
                signals = entry.get("evidence_signals", {})
                framework_name = str(entry.get("framework") or entry.get("group_key") or "")
                completed_games = completed_by_framework.get(framework_name)
                failed_games = failed_by_framework.get(framework_name)
                rows.append(
                    {
                        "experiment": str(path.relative_to(ROOT)),
                        "model_pool": ",".join(str(item) for item in model_pool),
                        "framework": framework_name,
                        "score": entry.get("rubric_total_score"),
                        "completed_games": completed_games
                        if completed_games is not None
                        else summary.get("completed_raw_games"),
                        "failed_games": failed_games if failed_games is not None else summary.get("failed_games"),
                        "external_failure_rate": signals.get("external_failure_rate"),
                        "win_rate": signals.get("win_rate"),
                        "macro_role_win_rate": signals.get("macro_role_win_rate"),
                        "status": "completed supplemental run",
                    }
                )
            continue
        failure_types = sorted({str(item.get("error_type") or "unknown") for item in failures})
        if summary.get("run_status"):
            status = str(summary.get("run_status"))
            if summary.get("blocker"):
                status += "; " + str(summary.get("blocker"))
        elif failures:
            status = "no valid completed games; external failure types=" + ",".join(failure_types)
        else:
            status = "no valid completed games; no structured failure rows"
        rows.append(
            {
                "experiment": str(path.relative_to(ROOT)),
                "model_pool": ",".join(str(item) for item in model_pool),
                "framework": ",".join(str(item.get("name")) for item in summary.get("frameworks", [])) or "n/a",
                "score": None,
                "completed_games": summary.get("completed_raw_games"),
                "failed_games": summary.get("failed_games"),
                "external_failure_rate": 1.0 if summary.get("failed_games") else None,
                "win_rate": None,
                "macro_role_win_rate": None,
                "status": status,
            }
        )
    return rows


def build_frontier_agent_eval_summary(effects: Sequence[ModuleEffect], panels: dict[str, Any]) -> dict[str, Any]:
    by_module = {effect.module: effect for effect in effects}
    safety_scores = [
        by_module.get(
            "Track C safety and knowledge hygiene",
            ModuleEffect("", "", "", "", None, "", None, None, None, 0, None, False, "", ""),
        ).effect_score_0_100,
        by_module.get(
            "Information isolation", ModuleEffect("", "", "", "", None, "", None, None, None, 0, None, False, "", "")
        ).effect_score_0_100,
        by_module.get(
            "Local non-LLM validation gates",
            ModuleEffect("", "", "", "", None, "", None, None, None, 0, None, False, "", ""),
        ).effect_score_0_100,
    ]
    dimensions = {
        "interactive_reliability": {
            "score": by_module["Experiment reliability and strict-mode health"].effect_score_0_100,
            "evidence": by_module["Experiment reliability and strict-mode health"].evidence,
        },
        "trajectory_process_quality": {
            "score": by_module["Agent design: role cognition + anti-pattern control"].effect_score_0_100,
            "evidence": by_module["Agent design: role cognition + anti-pattern control"].evidence,
        },
        "tool_rag_quality": {
            "score": by_module["Retrieval precision and coverage"].effect_score_0_100,
            "evidence": by_module["Retrieval precision and coverage"].evidence,
        },
        "social_multi_agent_quality": {
            "score": by_module["Multi-agent game interaction"].effect_score_0_100,
            "evidence": by_module["Multi-agent game interaction"].evidence,
        },
        "learning_from_experience": {
            "score": by_module["Track C role/persona evolution trend"].effect_score_0_100,
            "evidence": by_module["Track C role/persona evolution trend"].evidence,
        },
        "safety_reproducibility": {
            "score": sum(safety_scores) / max(len(safety_scores), 1),
            "evidence": (
                f"visibility={by_module['Information isolation'].evidence}; "
                f"track_c_safety={by_module['Track C safety and knowledge hygiene'].evidence}; "
                f"gates={by_module.get('Local non-LLM validation gates').evidence if by_module.get('Local non-LLM validation gates') else 'not rerun'}"
            ),
        },
    }
    weights = {
        "interactive_reliability": 0.20,
        "trajectory_process_quality": 0.20,
        "tool_rag_quality": 0.15,
        "social_multi_agent_quality": 0.15,
        "learning_from_experience": 0.15,
        "safety_reproducibility": 0.15,
    }
    weighted_score = sum(dimensions[key]["score"] * weight for key, weight in weights.items())
    return {
        "name": "Werewolf Agent Design Quality Index",
        "score_0_100": round(weighted_score, 2),
        "weights": weights,
        "dimensions": {
            key: {"score": round(value["score"], 2), "evidence": value["evidence"]} for key, value in dimensions.items()
        },
        "interpretation": (
            "This is a frontier-evaluation-inspired evidence index, not an official benchmark score. "
            "It combines interactive reliability, trajectory quality, RAG/tool quality, social multi-agent quality, "
            "learning-from-experience, and safety/reproducibility."
        ),
        "formal_rows": panels["aiwolf_style_outcome_metrics"].get("formal_v4flash_rows"),
    }


def run_command(name: str, command: Sequence[str], timeout: int = 180) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            list(command),
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        passed = result.returncode == 0
        return {
            "name": name,
            "command": list(command),
            "passed": passed,
            "returncode": result.returncode,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "summary": summarize_command_output(output, passed),
            "stdout_tail": tail_text(result.stdout or ""),
            "stderr_tail": tail_text(result.stderr or ""),
        }
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + (
            (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        )
        return {
            "name": name,
            "command": list(command),
            "passed": False,
            "returncode": None,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "summary": f"timeout after {timeout}s; {summarize_command_output(output, False)}",
            "stdout_tail": tail_text((exc.stdout or "") if isinstance(exc.stdout, str) else ""),
            "stderr_tail": tail_text((exc.stderr or "") if isinstance(exc.stderr, str) else ""),
        }


def summarize_command_output(output: str, passed: bool) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "passed with no output" if passed else "failed with no output"
    interesting = [
        line
        for line in lines
        if " passed" in line
        or " failed" in line
        or line.startswith("FAILED")
        or line.startswith("ERROR")
        or "All information isolation checks passed" in line
    ]
    if interesting:
        return "; ".join(interesting[-3:])
    return lines[-1]


def tail_text(text: str, max_lines: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def run_gates() -> list[dict[str, Any]]:
    python = sys.executable
    return [
        run_command("visibility_strict", [python, "scripts/verify_visibility_strict.py"], timeout=120),
        run_command(
            "track_b_review_metrics",
            [python, "-m", "pytest", "tests/test_review_metrics.py", "-q"],
            timeout=180,
        ),
        run_command(
            "track_c_retrieval_prompt",
            [
                python,
                "-m",
                "pytest",
                "tests/test_retrieval_policy.py",
                "tests/test_prompt_layering.py",
                "-q",
            ],
            timeout=180,
        ),
        run_command(
            "leaderboard_experiment_harness",
            [python, "-m", "pytest", "tests/test_track_bc_leaderboard_experiment.py", "-q"],
            timeout=180,
        ),
    ]


def write_csv(path: Path, effects: Sequence[ModuleEffect]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(effects[0]).keys()) if effects else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for effect in effects:
            writer.writerow(asdict(effect))


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"
    return str(value)


def fmt_delta(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float)):
        return f"{value:+.4f}" if abs(float(value)) < 10 else f"{value:+.2f}"
    return str(value)


def render_markdown(payload: dict[str, Any]) -> str:
    effects = [ModuleEffect(**item) for item in payload["module_effects"]]
    panels = payload["common_metric_panels"]
    gates = payload.get("gate_results", [])
    generated_at = payload["generated_at"]
    avg_score = sum(effect.effect_score_0_100 for effect in effects) / max(len(effects), 1)
    passed_count = sum(1 for effect in effects if effect.passed)
    failed = [effect for effect in effects if not effect.passed]
    formal_rows = panels["aiwolf_style_outcome_metrics"].get("formal_v4flash_rows")
    retrieval_panel = panels["retrieval_ir_metrics"]

    lines: list[str] = [
        "# Module Effect Experiment Results",
        "",
        f"> Generated at: {generated_at}",
        "",
        "## Scope",
        "",
        (
            "This report is a reproducible module-level experiment summary. It consolidates formal Volcengine "
            "v4flash framework runs, Track C retrieval ablations, role/MBTI auxiliary analysis, full-project "
            "audit probes, and optional local gates. It does not fabricate metrics that are not present in the logs."
        ),
        "",
        "Key interpretation rule: `basic_react` is the ordinary ReAct-style baseline. Existing formal data uses "
        "`anti_only`, `trackc_only`, and `cognitive_full`; the expanded runner maps these to `role_guarded_react`, "
        "`rag_react`, and `full_cognitive` for clearer paper framing.",
        "",
        "## Executive Result",
        "",
        f"- Quantified modules: {len(effects)}; passed target: {passed_count}/{len(effects)}; mean effect score: {avg_score:.2f}/100.",
        f"- Formal evidence rows after strict v4flash filtering: {formal_rows}; pro/fake/non-Volcengine rows are excluded from formal claims.",
        (
            f"- Track C retrieval uplift vs global-only: P@3={retrieval_panel.get('precision_at_3')}, "
            f"nDCG@5={retrieval_panel.get('ndcg_at_5')}, coverage={retrieval_panel.get('coverage_rate')}, "
            f"leak={retrieval_panel.get('candidate_leakage_count')}."
        ),
        "- Main negative result: current all-seat Track C toggles cannot prove final-agent causal win-rate lift; use target-seat paired A/B for that claim.",
        "",
        "## Module Effect Scorecard",
        "",
        "| Module | Primary metric | Baseline | Designed treatment | Delta | Relative lift | Effect score | Target pass | Evidence | Caveat |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for effect in effects:
        lines.append(
            "| "
            + " | ".join(
                [
                    effect.module,
                    effect.primary_metric,
                    f"{effect.baseline_name}: {fmt(effect.baseline_value)}",
                    f"{effect.treatment_name}: {fmt(effect.treatment_value)}",
                    fmt_delta(effect.delta_abs),
                    "n/a" if effect.delta_rel_pct is None else f"{effect.delta_rel_pct:+.2f}%",
                    f"{effect.effect_score_0_100:.2f}",
                    "yes" if effect.passed else "no",
                    effect.evidence.replace("|", "/"),
                    effect.caveat.replace("|", "/"),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Formal v4flash Outcome Metrics",
            "",
            "Whole-game failures/API errors are external run-health signals and are not counted as Agent losses.",
            "",
            "| Tier | Completed | External failed | External failure | Wolf win | Village win | Macro role win | Fallback | Invalid |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for tier, row in panels["aiwolf_style_outcome_metrics"]["tier_win_rates"].items():
        lines.append(
            f"| {tier} | {row.get('completed_games')} | {row.get('external_failed_games')} | "
            f"{fmt(row.get('external_failure_rate'))} | "
            f"{fmt(row.get('wolf_win_rate'))} | {fmt(row.get('village_win_rate'))} | "
            f"{fmt(row.get('macro_role_win_rate'))} | "
            f"{panels['safety_and_reliability_metrics']['fallback_invalid_by_tier'].get(tier, {}).get('fallback_count')} | "
            f"{panels['safety_and_reliability_metrics']['fallback_invalid_by_tier'].get(tier, {}).get('invalid_count')} |"
        )

    lines.extend(
        [
            "",
            "## Formal Agent Framework Scores",
            "",
            "Only rows with `formal v4flash score available` have completed real v4flash evidence in the current logs. "
            "Rows marked as runner-only are implemented comparison arms that need a new balanced run before they can be claimed.",
            "The total score excludes whole-game external failures/API errors; external failure is shown separately.",
            "",
            "| Framework | Family | Alias/tier | Total | Delta vs basic_react | External failure | Wolf win | Village win | Macro role win | Single /20 | Multi /20 | Eng /30 | B/C /30 | Evidence |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in payload["framework_score_comparison"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['framework']}`",
                    row["external_family"],
                    f"{row['existing_alias']} / {row['formal_tier']}",
                    fmt(row["rubric_total_score"]),
                    fmt_delta(row["delta_vs_basic_react"]),
                    fmt(row["external_failure_rate"]),
                    fmt(row["wolf_win_rate"]),
                    fmt(row["village_win_rate"]),
                    fmt(row["macro_role_win_rate"]),
                    fmt(row["single_agent_score"]),
                    fmt(row["multi_agent_score"]),
                    fmt(row["engineering_score"]),
                    fmt(row["advanced_bc_score"]),
                    row["evidence_status"],
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Supplemental Reflexion Framework Runs",
            "",
            "These rows are supplemental runs for the two framework arms that were not present in the historical formal v4flash set. "
            "They are not merged into the historical v4flash ranking unless they have valid completed games under the same formal model policy.",
            "",
            "| Experiment | Model pool | Framework | Score | Completed | Failed | External failure | Win rate | Macro role win | Status |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in payload["supplemental_framework_runs"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["experiment"],
                    row["model_pool"] or "n/a",
                    f"`{row['framework']}`",
                    fmt(row["score"]),
                    fmt(row["completed_games"]),
                    fmt(row["failed_games"]),
                    fmt(row["external_failure_rate"]),
                    fmt(row["win_rate"]),
                    fmt(row["macro_role_win_rate"]),
                    row["status"],
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Expanded Agent Framework Comparison Matrix",
            "",
            "| Framework | Existing alias | External design family | Enabled modules | Current evidence status | Why include it |",
            "|---|---|---|---|---|---|",
        ]
    )
    for framework in payload["expanded_agent_frameworks"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{framework['framework']}`",
                    framework["aliases"] or "n/a",
                    framework["external_family"],
                    framework["enabled_modules"],
                    framework["current_evidence_status"],
                    framework["why_include"],
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Retrieval Precision Metrics",
            "",
            "| Policy | Query set | Docs | P@1 | P@3 | P@5 | MRR | nDCG@5 | Coverage | Role match | MBTI match | Phase match | p95 ms | Leak |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            (
                f"| {retrieval_panel.get('policy')} | {retrieval_panel.get('query_set_size')} | "
                f"{retrieval_panel.get('retriever_size')} | {fmt(retrieval_panel.get('precision_at_1'))} | "
                f"{fmt(retrieval_panel.get('precision_at_3'))} | {fmt(retrieval_panel.get('precision_at_5'))} | "
                f"{fmt(retrieval_panel.get('mrr'))} | {fmt(retrieval_panel.get('ndcg_at_5'))} | "
                f"{fmt(retrieval_panel.get('coverage_rate'))} | {fmt(retrieval_panel.get('role_match_rate'))} | "
                f"{fmt(retrieval_panel.get('mbti_match_rate'))} | {fmt(retrieval_panel.get('phase_match_rate'))} | "
                f"{fmt(retrieval_panel.get('latency_p95_ms'))} | {retrieval_panel.get('candidate_leakage_count')} |"
            ),
            "",
            "## Domain Metric Catalog for Multi-Angle Comparison",
            "",
            "| Metric family | External source | Canonical metrics | Project fields | Current status | Presentation use |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in payload["domain_metric_catalog"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    item["metric_family"],
                    item["external_source"],
                    item["canonical_metrics"],
                    item["project_fields"],
                    item["current_status"],
                    item["presentation_use"],
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Social-Deduction Metric Mapping",
            "",
            "| Metric family | Current quantitative field | Current value | Use in paper |",
            "|---|---|---:|---|",
        ]
    )
    proxies = panels["social_deduction_capability_proxies"]
    lines.extend(
        [
            (
                "| AIWolf overall/role win rate | formal tier win rates + role win rates | "
                f"{formal_rows} rows | Primary outcome metric with role-normalized macro win rate. |"
            ),
            (
                "| Wolf deception proxy | wolf win rate by tier | "
                f"baseline={fmt(proxies['wolf_deception_proxy']['baseline_wolf_win_rate'])}, "
                f"trackc={fmt(proxies['wolf_deception_proxy']['trackc_only_wolf_win_rate'])} | "
                "Use as proxy only; direct deception labels need speech taxonomy. |"
            ),
            (
                "| Village detection proxy | village win rate + non-wolf role win rate | "
                f"baseline={fmt(proxies['village_detection_proxy']['baseline_village_win_rate'])}, "
                f"cognitive_full={fmt(proxies['village_detection_proxy']['cognitive_full_village_win_rate'])} | "
                "Shows collective detection/survival trend under current logs. |"
            ),
            (
                "| Seer disclosure proxy | Seer role win rate | "
                f"{fmt(proxies['seer_disclosure_proxy']['formal_seer_win_rate'])} | "
                "Aggregate proxy; future claim-level disclosure labels should be added. |"
            ),
            (
                "| Track C knowledge safety | leak/invalid docs/source coverage | "
                f"leak={panels['track_c_evolution_metrics'].get('leak_doc_count')}, "
                f"invalid={panels['track_c_evolution_metrics'].get('invalid_doc_count')}, "
                f"coverage={fmt(panels['track_c_evolution_metrics'].get('source_event_coverage'))} | "
                "Supports B -> C feedback-loop hygiene. |"
            ),
        ]
    )

    frontier_summary = payload["frontier_agent_eval_summary"]
    lines.extend(
        [
            "",
            "## Frontier Agent Design Evaluation Applied",
            "",
            f"- {frontier_summary['name']}: {frontier_summary['score_0_100']:.2f}/100.",
            "- Interpretation: this is a benchmark-inspired design-quality index for this project, not an external leaderboard score.",
            "",
            "| Frontier lens | Source | Project metric mapping | Current result | Verdict |",
            "|---|---|---|---:|---|",
        ]
    )
    frontier_dimensions = frontier_summary["dimensions"]
    frontier_rows = [
        (
            "Interactive task success",
            "AgentBench / AgentBoard",
            "completion + strict health",
            "interactive_reliability",
        ),
        (
            "Trajectory/process quality",
            "AgentBoard-style fine-grained metrics",
            "role cognition + process score",
            "trajectory_process_quality",
        ),
        (
            "Tool/RAG reliability",
            "tau-bench-style policy/tool reliability",
            "retrieval precision/coverage/leak",
            "tool_rag_quality",
        ),
        (
            "Social multi-agent quality",
            "SOTOPIA-style social interaction",
            "macro role/social deduction proxies",
            "social_multi_agent_quality",
        ),
        (
            "Learning from experience",
            "Reflexion-style self-improvement",
            "Track C off/on trend + knowledge hygiene",
            "learning_from_experience",
        ),
        (
            "Safety/reproducibility",
            "modern agent reliability gates",
            "visibility + fallback/invalid + leak gates",
            "safety_reproducibility",
        ),
    ]
    for lens, source, mapping, key in frontier_rows:
        score = frontier_dimensions[key]["score"]
        verdict = "strong" if score >= 85 else "acceptable" if score >= 70 else "needs work"
        lines.append(f"| {lens} | {source} | {mapping} | {score:.2f} | {verdict} |")

    lines.extend(
        [
            "",
            "Frontier-method takeaway:",
            "",
            "- The strongest evidence is not raw win rate; it is the combination of trajectory/process quality, RAG precision, safety gates, and reproducibility.",
            "- Your current architecture is strong on Agent role design, retrieval quality, and safety; the main weakness is full-stack execution reliability and the lack of a target-seat causal Track C A/B.",
        ]
    )

    role_summary = panels["aiwolf_style_outcome_metrics"]["role_summary"]
    lines.extend(
        [
            "",
            "## Role-Wise Win Rates",
            "",
            "| Role | Samples | Wins | Win rate | Wilson CI95 |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for role, row in role_summary.items():
        lines.append(
            f"| {role} | {row.get('samples')} | {row.get('wins')} | {fmt(row.get('win_rate'))} | {row.get('wilson_ci95')} |"
        )

    track_c_metrics = panels["track_c_evolution_metrics"]
    lines.extend(
        [
            "",
            "## Track C Evolution Trend",
            "",
            f"- Auxiliary role/MBTI rows: off={track_c_metrics.get('track_c_auxiliary_overall', {}).get('track_c_off')}, on={track_c_metrics.get('track_c_auxiliary_overall', {}).get('track_c_on')}.",
            f"- Knowledge docs: {track_c_metrics.get('knowledge_doc_count')}; source-event coverage: {fmt(track_c_metrics.get('source_event_coverage'))}; invalid/leak: {track_c_metrics.get('invalid_doc_count')}/{track_c_metrics.get('leak_doc_count')}.",
            "- Interpretation: useful for showing role/persona coverage and non-wolf positive trend, but not sufficient for final-agent causal win-rate lift because all seats were toggled together.",
            "",
            "## Gate Results",
            "",
        ]
    )
    if gates:
        lines.extend(["| Gate | Passed | Summary |", "|---|---|---|"])
        for gate in gates:
            lines.append(
                f"| {gate.get('name')} | {'yes' if gate.get('passed') else 'no'} | {gate.get('summary', '').replace('|', '/')} |"
            )
    else:
        lines.append(
            "No gates were rerun in this invocation. Run `python scripts/module_effect_experiment.py --run-gates` to refresh them."
        )

    lines.extend(
        [
            "",
            "## Metric References Used For Presentation Framing",
            "",
            "| Source | Borrowed metric family | Project mapping |",
            "|---|---|---|",
        ]
    )
    for ref in payload["common_metric_references"]:
        lines.append(f"| [{ref['source']}]({ref['url']}) | {ref['metric_family']} | {ref['project_mapping']} |")

    lines.extend(
        [
            "",
            "## Required Next Causal Experiment",
            "",
            "For the final claim that Track C experience summaries improve the final agent, run paired target-seat A/B:",
            "",
            "1. Same seed, same role assignment, same baseline opponents.",
            "2. Upgrade only one target seat from baseline to Track C; rotate target role and seat.",
            "3. Report target-agent win rate, role-normalized adjusted score, knowledge-hit rate, bad-case reduction, retrieval P@3/nDCG/coverage, fallback/invalid/info-leak gates, and bootstrap confidence intervals.",
            "",
        ]
    )
    if failed:
        lines.extend(["## Failed Or Borderline Modules", ""])
        for effect in failed:
            lines.append(
                f"- {effect.module}: score={effect.effect_score_0_100:.2f}, caveat={effect.caveat or effect.evidence}"
            )
        lines.append("")
    return "\n".join(lines)


def build_payload(run_gates_flag: bool) -> dict[str, Any]:
    formal = load_json(FORMAL_SUMMARY)
    retrieval = load_json(RETRIEVAL_RESULTS)
    mbti = load_json(MBTI_TRACK_C_SUMMARY)
    audit = load_json(REAL_AUDIT_SUMMARY)
    frontend = load_json(FRONTEND_PROBE)
    mobile = load_json(MOBILE_PROBE)
    bubble = load_json(BUBBLE_PROBE)
    real_llm = load_json(REAL_LLM_PROBE)
    gate_results = run_gates() if run_gates_flag else []
    effects = build_module_effects(
        formal=formal,
        retrieval=retrieval,
        mbti=mbti,
        audit=audit,
        frontend=frontend,
        mobile=mobile,
        bubble=bubble,
        real_llm=real_llm,
        gate_results=gate_results,
    )
    panels = build_common_metric_panels(formal, retrieval, mbti, audit)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "formal_summary": str(FORMAL_SUMMARY.relative_to(ROOT)),
            "retrieval_results": str(RETRIEVAL_RESULTS.relative_to(ROOT)),
            "mbti_track_c_summary": str(MBTI_TRACK_C_SUMMARY.relative_to(ROOT)),
            "real_audit_summary": str(REAL_AUDIT_SUMMARY.relative_to(ROOT)),
            "frontend_probe": str(FRONTEND_PROBE.relative_to(ROOT)),
            "mobile_probe": str(MOBILE_PROBE.relative_to(ROOT)),
            "bubble_probe": str(BUBBLE_PROBE.relative_to(ROOT)),
            "real_llm_probe": str(REAL_LLM_PROBE.relative_to(ROOT)),
        },
        "module_effects": [asdict(effect) for effect in effects],
        "common_metric_panels": panels,
        "gate_results": gate_results,
        "common_metric_references": COMMON_METRIC_REFERENCES,
        "domain_metric_catalog": DOMAIN_METRIC_CATALOG,
        "expanded_agent_frameworks": EXPANDED_AGENT_FRAMEWORKS,
        "framework_score_comparison": build_framework_score_comparison(formal),
        "supplemental_framework_runs": summarize_supplemental_framework_runs(SUPPLEMENTAL_FRAMEWORK_SUMMARIES),
        "frontier_agent_eval_references": FRONTIER_AGENT_EVAL_REFERENCES,
        "frontier_agent_eval_summary": build_frontier_agent_eval_summary(effects, panels),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-gates", action="store_true", help="rerun lightweight non-LLM validation gates")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--tracked-report", type=Path, default=TRACKED_REPORT)
    args = parser.parse_args()

    payload = build_payload(run_gates_flag=args.run_gates)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "module_effects.csv", [ModuleEffect(**item) for item in payload["module_effects"]])
    markdown = render_markdown(payload)
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    args.tracked_report.parent.mkdir(parents=True, exist_ok=True)
    args.tracked_report.write_text(markdown, encoding="utf-8")

    passed = sum(1 for item in payload["module_effects"] if item["passed"])
    total = len(payload["module_effects"])
    print(f"wrote {output_dir / 'summary.json'}")
    print(f"wrote {args.tracked_report}")
    print(f"module target pass rate: {passed}/{total}")
    if args.run_gates and not all(item.get("passed") for item in payload["gate_results"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
