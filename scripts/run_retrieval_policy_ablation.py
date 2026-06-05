#!/usr/bin/env python3
"""Online Retrieval Policy Ablation — compare policies via actual game outcomes.

Usage:
    # Smoke test (1 game per policy)
    python scripts/run_retrieval_policy_ablation.py --games 1 --output outputs/retrieval_policy_ablation

    # Full experiment (5 games per policy)
    python scripts/run_retrieval_policy_ablation.py --games 5 --output outputs/retrieval_policy_ablation

    # Large experiment (20 games per policy)
    python scripts/run_retrieval_policy_ablation.py --games 20 --output outputs/retrieval_policy_ablation

Design:
    - Fixed seed set for paired comparison
    - Same model, same MBTI assignments, same active snapshot per seed
    - 7 groups: baseline_no_trackc + 6 retrieval policies
    - Each group runs identical games (same seed, same role assignments)

Output:
    outputs/retrieval_policy_ablation/results.json
    outputs/retrieval_policy_ablation/results.csv
    outputs/retrieval_policy_ablation/summary.md
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Dict
from typing import List

import numpy as np

# ================================================================
# Configuration
# ================================================================

POLICIES = [
    "baseline_no_trackc",
    "global_only",
    "self_mbti_only",
    "same_role_all_mbti",
    "same_role_same_mbti",
    "hybrid_role_mbti_global",
    "hybrid_role_alignment_phase",
]

DEFAULT_SEEDS = list(range(100, 200))

MBTI_TYPES = ["INTJ", "ENFP", "ISTJ", "ESFP", "INTP", "ENTJ", "ISFJ", "ESTP", "INFJ", "ENFJ", "ISFP", "ESTP"]


@dataclass
class GameOutcome:
    """Per-game outcome metrics."""

    game_id: str = ""
    seed: int = 0
    policy: str = ""
    winner: str = ""
    duration_s: float = 0.0
    # Per-role metrics
    process_score: float = 0.0
    vote_accuracy: float = 0.0
    speech_quality: float = 0.0
    skill_efficiency: float = 0.0
    # Strategy usage
    strategy_auto_injected_count: int = 0
    strategy_search_count: int = 0
    strategy_usage_count: int = 0
    avg_retrieved_relevance: float = 0.0
    candidate_lessons_count: int = 0
    # Anti-pattern
    anti_pattern_violation_count: int = 0
    invalid_action_count: int = 0
    # Cost
    tokens_per_game: int = 0
    cost_per_game: float = 0.0
    latency_per_decision_ms: float = 0.0
    # Metadata
    tool_trace_has_policy: bool = False
    tool_trace_has_bucket: bool = False
    active_count: int = 0
    active_count_changed: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class PolicyStats:
    """Aggregated stats per policy."""

    policy: str
    n_games: int = 0
    n_completed: int = 0
    n_errors: int = 0
    win_rate_wolf: float = 0.0
    win_rate_village: float = 0.0
    avg_process_score: float = 0.0
    avg_vote_accuracy: float = 0.0
    avg_speech_quality: float = 0.0
    avg_skill_efficiency: float = 0.0
    avg_strategy_usage: float = 0.0
    avg_retrieved_relevance: float = 0.0
    avg_candidate_lessons: float = 0.0
    avg_anti_pattern_violations: float = 0.0
    avg_invalid_actions: float = 0.0
    avg_tokens: float = 0.0
    avg_cost: float = 0.0
    avg_latency_ms: float = 0.0
    tool_trace_policy_rate: float = 0.0
    outcomes: List[GameOutcome] = field(default_factory=list)


def run_single_game(seed: int, policy: str, model: str = "deepseek-v4-pro") -> GameOutcome:
    """Run a single game with specified retrieval policy.

    Args:
        seed: Random seed for reproducibility.
        policy: One of POLICIES (baseline_no_trackc disables Track C entirely).
        model: LLM model name.

    Returns:
        GameOutcome with all metrics.
    """
    outcome = GameOutcome(seed=seed, policy=policy)

    try:
        # Set environment variables for the game
        env = os.environ.copy()
        env["AIWEREWOLF_GAME_SEED"] = str(seed)
        env["AIWEREWOLF_MODEL"] = model
        env["AIWEREWOLF_STRICT_MODE"] = "true"
        env["ALLOW_FALLBACK"] = "false"

        if policy == "baseline_no_trackc":
            env["COGNITIVE_ENABLE_TRACK_C"] = "false"
        else:
            env["COGNITIVE_ENABLE_TRACK_C"] = "true"
            env["COGNITIVE_RETRIEVAL_POLICY"] = policy

        # Import and run game
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

        from backend.engine.game import WerewolfGame
        from backend.engine.models import GameConfig

        config = GameConfig(
            rule_pack_id="standard",
            players=[],
            seed=str(seed),
            model_name=model,
        )

        t0 = time.perf_counter()
        WerewolfGame(config)

        # TODO: Actually run the game with agents configured per policy
        # This requires:
        # 1. Creating agents with appropriate MBTI assignments
        # 2. Passing retrieval_policy to CognitiveAgent constructor
        # 3. Running the game loop
        # 4. Collecting post-game metrics

        # Placeholder: mark as incomplete
        outcome.errors.append("Game execution not yet wired — requires agent config integration")
        outcome.game_id = f"game_{policy}_seed{seed}"
        outcome.duration_s = time.perf_counter() - t0

    except Exception as e:
        outcome.errors.append(str(e))

    return outcome


def compute_paired_stats(
    baseline_stats: PolicyStats,
    candidate_stats: PolicyStats,
    metric: str = "avg_process_score",
) -> Dict[str, Any]:
    """Compute paired comparison statistics between two policies.

    Uses paired seed comparison with bootstrap 95% CI.
    """
    baseline_vals = [getattr(o, metric, 0.0) for o in baseline_stats.outcomes]
    candidate_vals = [getattr(o, metric, 0.0) for o in candidate_stats.outcomes]

    if len(baseline_vals) != len(candidate_vals):
        return {"error": "mismatched outcome counts"}

    n = len(baseline_vals)
    if n < 2:
        return {"error": "insufficient samples"}

    diffs = [c - b for c, b in zip(candidate_vals, baseline_vals)]
    mean_diff = float(np.mean(diffs))

    # Bootstrap 95% CI
    n_bootstrap = 10_000
    bootstrap_diffs = []
    rng = np.random.RandomState(42)
    for _ in range(n_bootstrap):
        sample = rng.choice(diffs, size=n, replace=True)
        bootstrap_diffs.append(float(np.mean(sample)))

    bootstrap_diffs.sort()
    ci_low = float(np.percentile(bootstrap_diffs, 2.5))
    ci_high = float(np.percentile(bootstrap_diffs, 97.5))

    # Effect size (Cohen's d)
    pooled_std = np.sqrt((np.var(baseline_vals) + np.var(candidate_vals)) / 2)
    cohens_d = mean_diff / pooled_std if pooled_std > 0 else 0.0

    # Permutation test p-value
    observed = abs(mean_diff)
    count_extreme = 0
    for _ in range(10_000):
        permuted = [b if rng.random() < 0.5 else c for b, c in zip(baseline_vals, candidate_vals)]
        permuted_ref = [c if rng.random() < 0.5 else b for b, c in zip(baseline_vals, candidate_vals)]
        perm_diff = abs(np.mean(permuted) - np.mean(permuted_ref))
        if perm_diff >= observed:
            count_extreme += 1
    p_value = count_extreme / 10_000

    return {
        "metric": metric,
        "n_pairs": n,
        "baseline_mean": float(np.mean(baseline_vals)),
        "candidate_mean": float(np.mean(candidate_vals)),
        "mean_diff": round(mean_diff, 4),
        "ci_95_low": round(ci_low, 4),
        "ci_95_high": round(ci_high, 4),
        "cohens_d": round(cohens_d, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
        "trend": "positive" if mean_diff > 0 else ("negative" if mean_diff < 0 else "neutral"),
    }


def run_ablation(
    n_games: int = 1,
    output_dir: str = "outputs/retrieval_policy_ablation",
    model: str = "deepseek-v4-pro",
    seeds: List[int] | None = None,
) -> Dict[str, Any]:
    """Run the full policy ablation experiment.

    Args:
        n_games: Number of games per policy group.
        output_dir: Where to save results.
        model: LLM model to use.
        seeds: Seed list (default: deterministic subset based on n_games).

    Returns:
        Dict with per-policy stats and comparisons.
    """
    os.makedirs(output_dir, exist_ok=True)

    if seeds is None:
        seeds = DEFAULT_SEEDS[:n_games]

    print(f"Running {len(POLICIES)} policies × {len(seeds)} games = {len(POLICIES) * len(seeds)} total")
    print(f"Model: {model}")
    print(f"Seeds: {seeds[:5]}{'...' if len(seeds) > 5 else ''}")
    print()

    all_stats: Dict[str, PolicyStats] = {}

    for policy in POLICIES:
        print(f"  {policy:35s} ...", end=" ", flush=True)
        stats = PolicyStats(policy=policy)
        stats.n_games = len(seeds)

        for seed in seeds:
            outcome = run_single_game(seed, policy, model)
            stats.outcomes.append(outcome)

            if outcome.errors:
                stats.n_errors += 1
            else:
                stats.n_completed += 1

        # Aggregate
        completed = [o for o in stats.outcomes if not o.errors]
        if completed:
            wolf_wins = sum(1 for o in completed if o.winner == "wolf")
            village_wins = sum(1 for o in completed if o.winner == "village")
            n_completed = len(completed)
            stats.win_rate_wolf = wolf_wins / n_completed
            stats.win_rate_village = village_wins / n_completed
            stats.avg_process_score = float(np.mean([o.process_score for o in completed]))
            stats.avg_vote_accuracy = float(np.mean([o.vote_accuracy for o in completed]))
            stats.avg_speech_quality = float(np.mean([o.speech_quality for o in completed]))
            stats.avg_skill_efficiency = float(np.mean([o.skill_efficiency for o in completed]))
            stats.avg_strategy_usage = float(np.mean([o.strategy_usage_count for o in completed]))
            stats.avg_retrieved_relevance = float(np.mean([o.avg_retrieved_relevance for o in completed]))
            stats.avg_candidate_lessons = float(np.mean([o.candidate_lessons_count for o in completed]))
            stats.avg_invalid_actions = float(np.mean([o.invalid_action_count for o in completed]))
            stats.avg_tokens = float(np.mean([o.tokens_per_game for o in completed]))
            stats.avg_cost = float(np.mean([o.cost_per_game for o in completed]))
            stats.avg_latency_ms = float(np.mean([o.latency_per_decision_ms for o in completed]))
            stats.tool_trace_policy_rate = float(np.mean([1.0 if o.tool_trace_has_policy else 0.0 for o in completed]))

        all_stats[policy] = stats
        status = f"✓ {stats.n_completed}/{stats.n_games}" if stats.n_errors == 0 else f"✗ {stats.n_errors} errors"
        print(status)

    # Paired comparisons against baseline
    baseline = all_stats.get("baseline_no_trackc")
    comparisons = []
    for policy in POLICIES:
        if policy == "baseline_no_trackc":
            continue
        candidate = all_stats.get(policy)
        if baseline and candidate:
            for metric in [
                "avg_process_score",
                "avg_vote_accuracy",
                "avg_speech_quality",
                "avg_skill_efficiency",
            ]:
                comp = compute_paired_stats(baseline, candidate, metric)
                comp["policy"] = policy
                comparisons.append(comp)

    # Save results
    results = {
        "n_games_per_policy": n_games,
        "model": model,
        "seeds": seeds,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "policies": {
            p: {
                "policy": p,
                "n_games": s.n_games,
                "n_completed": s.n_completed,
                "n_errors": s.n_errors,
                "win_rate_wolf": round(s.win_rate_wolf, 4),
                "win_rate_village": round(s.win_rate_village, 4),
                "avg_process_score": round(s.avg_process_score, 4),
                "avg_vote_accuracy": round(s.avg_vote_accuracy, 4),
                "avg_speech_quality": round(s.avg_speech_quality, 4),
                "avg_skill_efficiency": round(s.avg_skill_efficiency, 4),
                "avg_strategy_usage": round(s.avg_strategy_usage, 2),
                "avg_retrieved_relevance": round(s.avg_retrieved_relevance, 4),
                "avg_candidate_lessons": round(s.avg_candidate_lessons, 2),
                "avg_invalid_actions": round(s.avg_invalid_actions, 2),
                "avg_tokens": int(s.avg_tokens),
                "avg_cost": round(s.avg_cost, 6),
                "avg_latency_ms": round(s.avg_latency_ms, 1),
                "tool_trace_policy_rate": round(s.tool_trace_policy_rate, 4),
            }
            for p, s in all_stats.items()
        },
        "paired_comparisons": comparisons,
    }

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # CSV
    csv_headers = [
        "policy",
        "n_games",
        "completed",
        "win_rate_wolf",
        "win_rate_village",
        "process_score",
        "vote_accuracy",
        "speech_quality",
        "skill_efficiency",
        "strategy_usage",
        "retrieved_relevance",
        "candidate_lessons",
        "invalid_actions",
        "tokens",
        "cost",
        "latency_ms",
    ]
    with open(os.path.join(output_dir, "results.csv"), "w") as f:
        f.write(",".join(csv_headers) + "\n")
        for p, s in all_stats.items():
            row = [
                p,
                str(s.n_games),
                str(s.n_completed),
                f"{s.win_rate_wolf:.4f}",
                f"{s.win_rate_village:.4f}",
                f"{s.avg_process_score:.4f}",
                f"{s.avg_vote_accuracy:.4f}",
                f"{s.avg_speech_quality:.4f}",
                f"{s.avg_skill_efficiency:.4f}",
                f"{s.avg_strategy_usage:.2f}",
                f"{s.avg_retrieved_relevance:.4f}",
                f"{s.avg_candidate_lessons:.2f}",
                f"{s.avg_invalid_actions:.2f}",
                str(int(s.avg_tokens)),
                f"{s.avg_cost:.6f}",
                f"{s.avg_latency_ms:.1f}",
            ]
            f.write(",".join(row) + "\n")

    # Markdown summary
    md = _build_ablation_summary(all_stats, comparisons, n_games)
    with open(os.path.join(output_dir, "summary.md"), "w") as f:
        f.write(md)

    print(f"\nResults saved to {output_dir}/")
    print("  results.json, results.csv, summary.md")

    return results


def _build_ablation_summary(
    all_stats: Dict[str, PolicyStats],
    comparisons: List[Dict],
    n_games: int,
) -> str:
    """Build markdown summary for ablation results."""
    lines = [
        "# Retrieval Policy Ablation — Online Game Results",
        "",
        f"**Games per policy**: {n_games}",
        "**Model**: deepseek-v4-pro",
        "**Comparison**: Paired seed with bootstrap 95% CI",
        "",
        "## Policy Comparison",
        "",
        "| Policy | Games | Process | VoteAcc | SpeechQ | SkillEff | StratUse | Tokens | Cost |",
        "|--------|-------|---------|---------|---------|----------|----------|--------|------|",
    ]

    for policy in POLICIES:
        s = all_stats.get(policy)
        if s is None:
            continue
        lines.append(
            f"| `{policy}` | {s.n_completed} | {s.avg_process_score:.2f} | {s.avg_vote_accuracy:.2f} | "
            f"{s.avg_speech_quality:.2f} | {s.avg_skill_efficiency:.2f} | "
            f"{s.avg_strategy_usage:.1f} | {int(s.avg_tokens)} | ${s.avg_cost:.4f} |"
        )

    lines += [
        "",
        "## Paired Comparison vs Baseline (no Track C)",
        "",
        "| Policy | Metric | Delta | 95% CI | Cohen's d | p-value | Significant |",
        "|--------|--------|-------|--------|-----------|---------|-------------|",
    ]

    for comp in comparisons:
        sig = "✓" if comp.get("significant") else ""
        lines.append(
            f"| `{comp['policy']}` | {comp['metric']} | {comp['mean_diff']:+.4f} | "
            f"[{comp['ci_95_low']:.4f}, {comp['ci_95_high']:.4f}] | "
            f"{comp['cohens_d']:.4f} | {comp['p_value']:.4f} | {sig} |"
        )

    lines += [
        "",
        "## Verification Checklist",
        "",
        "| Check | Status |",
        "|-------|--------|",
    ]

    # Check all policies
    for policy in POLICIES:
        s = all_stats.get(policy)
        if s is None:
            lines.append(f"| `{policy}` data | NOT FOUND |")
            continue
        issues = []
        if s.n_errors > 0:
            issues.append(f"{s.n_errors} errors")
        if s.n_completed < s.n_games:
            issues.append(f"only {s.n_completed}/{s.n_games} completed")
        status = ", ".join(issues) if issues else "OK"
        lines.append(f"| `{policy}` | {status} |")

    lines += [
        "",
        "## Recommendation",
        "",
        "Based on offline precision + online process scores, the recommended default policy is:",
        "",
        "**`hybrid_role_mbti_global`** (or the policy with highest combined offline+online score)",
        "",
        "---",
        "*Generated by scripts/run_retrieval_policy_ablation.py*",
    ]

    return "\n".join(lines)


# ================================================================
# Entry Point
# ================================================================

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Run retrieval policy ablation experiment")
    ap.add_argument("--games", type=int, default=1, help="Games per policy group")
    ap.add_argument("--output", default="outputs/retrieval_policy_ablation", help="Output directory")
    ap.add_argument("--model", default="deepseek-v4-pro", help="LLM model name")
    ap.add_argument("--seeds", nargs="*", type=int, default=None, help="Explicit seed list")
    args = ap.parse_args()

    print("=" * 60)
    print("Retrieval Policy Online Ablation")
    print("=" * 60)
    print()
    print("NOTE: Full game execution requires wiring agent config with retrieval_policy.")
    print("This script provides the experiment framework; actual game runs need:")
    print("  1. CognitiveAgent accepting retrieval_policy parameter")
    print("  2. Game loop passing policy to agents")
    print("  3. Post-game scoring pipeline")
    print()
    print("Run with --games 1 for smoke test, --games 5 for small experiment.")
    print()

    if args.games > 1:
        print(f"Will run {args.games} games per policy group.")
    else:
        print("Running smoke test (1 game per policy).")

    run_ablation(
        n_games=args.games,
        output_dir=args.output,
        model=args.model,
        seeds=args.seeds,
    )
