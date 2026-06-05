#!/usr/bin/env python3
"""V8 Strategy A/B Test — verify strategy_id causes behavioral differences.

Design:
  Seer: seer_aggressive_reveal_v1 vs seer_conservative_hide_v1
  Werewolf: werewolf_low_profile_deception_v1 vs werewolf_strong_vote_lead_v1

Control variables: same persona, same role, matched seed, only strategy_id varies.
Target: >=10 games per (role, strategy) = >=40 games total.

Usage:
  python scripts/v8_strategy_ab_test.py --games-per-group 10 --output data/health/strategy_ab_test_results_v8.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AB_TEST_CONFIG = {
    "seer_aggressive_vs_conservative": {
        "role": "Seer",
        "strategies": ["seer_aggressive_reveal_v1", "seer_conservative_hide_v1"],
        "fixed_persona": "林思远",  # INTP, analytical
        "metrics": [
            "raw_win_rate",
            "adjusted_win_lift",
            "avg_role_normalized_pre_action_score",
            "info_release_rate",
            "vote_quality",
            "speech_aggression",
            "mistake_rate",
        ],
    },
    "werewolf_low_profile_vs_strong_vote": {
        "role": "Werewolf",
        "strategies": ["werewolf_low_profile_deception_v1", "werewolf_strong_vote_lead_v1"],
        "fixed_persona": "赵铁柱",  # ESTP, bold
        "metrics": [
            "raw_win_rate",
            "adjusted_win_lift",
            "avg_role_normalized_pre_action_score",
            "deception_score",
            "suspicion_change",
            "speech_aggression",
            "mistake_rate",
        ],
    },
}


# ---------------------------------------------------------------------------
# Game runner
# ---------------------------------------------------------------------------


@dataclass
class GameResult:
    game_id: str
    seed: int
    role: str
    strategy_id: str
    strategy_name: str
    persona_name: str
    is_win: bool
    camp: str
    winner: str
    num_days: int
    num_decisions: int


def run_one_game(
    seed: int,
    player_count: int,
    agent_type: str,
    target_role: str,
    strategy_id: str,
    persona_name: str,
    strict: bool = False,
) -> GameResult | None:
    """Run one game with a specific strategy assigned to the target role.

    Returns GameResult or None if the game failed.
    """
    from backend.agents.strategy_registry import get_strategy_registry
    from backend.engine.game import WerewolfGame
    from backend.engine.rules import build_players
    from backend.engine.rules import get_role_configuration

    registry = get_strategy_registry()
    card = registry.get(strategy_id)

    roles = get_role_configuration(player_count)
    players = build_players(roles, seed=seed)

    # Find the player with target_role
    target_player = next((p for p in players if p.role.value == target_role), None)
    if target_player is None:
        return None

    # Build strategy_map: only the target player gets the experimental strategy
    # Others get role-appropriate defaults
    strategy_map = {target_player.id: strategy_id}

    config = {
        "type": agent_type,
        "seed": seed,
        "strategy_map": strategy_map,
    }
    if strict:
        from backend.agents.llm_agent import LLMAgent

        LLMAgent.STRICT_NO_FALLBACK = True

    try:
        from backend.agents.factory import create_agents

        game = WerewolfGame(seed=seed, player_count=player_count)
        game.attach_agents(create_agents(game.state.players, config))
        game.play()

        target_role_players = [p for p in game.state.players if p.role.value == target_role]
        results = []
        for p in target_role_players:
            is_win = (p.alignment.value if hasattr(p.alignment, "value") else str(p.alignment)) == (
                game.state.winner.value if hasattr(game.state.winner, "value") else str(game.state.winner)
            )
            results.append(
                GameResult(
                    game_id=game.state.id,
                    seed=seed,
                    role=p.role.value,
                    strategy_id=strategy_id,
                    strategy_name=card.strategy_name,
                    persona_name=p.name,
                    is_win=is_win,
                    camp=p.alignment.value if hasattr(p.alignment, "value") else str(p.alignment),
                    winner=game.state.winner.value if hasattr(game.state.winner, "value") else str(game.state.winner),
                    num_days=game.state.day,
                    num_decisions=len(game.state.decision_records),
                )
            )
        return results

    except Exception as exc:
        print(f"  [FAIL] seed={seed} role={target_role} strategy={strategy_id}: {exc}", file=sys.stderr)
        return None
    finally:
        if strict:
            from backend.agents.llm_agent import LLMAgent

            LLMAgent.STRICT_NO_FALLBACK = False


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


def run_experiment(
    games_per_group: int = 10,
    agent_type: str = "llm",
    player_count: int = 7,
    output_csv: str = "data/health/strategy_ab_test_results_v8.csv",
    output_md: str = "data/health/strategy_ab_test_v8.md",
    strict: bool = False,
) -> None:
    """Run the full A/B test experiment."""
    results: list[GameResult] = []
    base_seed = 7000  # offset to avoid collision with existing game seeds

    for exp_name, exp_config in AB_TEST_CONFIG.items():
        role = exp_config["role"]
        strategies = exp_config["strategies"]
        print(f"\n{'=' * 60}")
        print(f"Experiment: {exp_name}")
        print(f"Role: {role}, Strategies: {strategies}")
        print(f"{'=' * 60}")

        for strategy_id in strategies:
            registry = get_strategy_registry()
            card = registry.get(strategy_id)
            print(f"\n--- {card.strategy_name} ({strategy_id}) ---")

            for i in range(games_per_group):
                seed = base_seed + i
                print(f"  Game {i + 1}/{games_per_group} (seed={seed})...", end=" ", flush=True)
                game_results = run_one_game(
                    seed=seed,
                    player_count=player_count,
                    agent_type=agent_type,
                    target_role=role,
                    strategy_id=strategy_id,
                    persona_name=exp_config["fixed_persona"],
                    strict=strict,
                )
                if game_results:
                    results.extend(game_results)
                    wins = sum(1 for r in game_results if r.is_win)
                    total = len(game_results)
                    print(f"OK ({wins}/{total} wins)")
                else:
                    print(f"SKIP (no {role} in game)")
            base_seed += games_per_group

    # Write CSV
    if results:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "game_id",
                    "seed",
                    "role",
                    "strategy_id",
                    "strategy_name",
                    "persona_name",
                    "is_win",
                    "camp",
                    "winner",
                    "num_days",
                    "num_decisions",
                ],
            )
            writer.writeheader()
            for r in results:
                writer.writerow(
                    {
                        "game_id": r.game_id,
                        "seed": r.seed,
                        "role": r.role,
                        "strategy_id": r.strategy_id,
                        "strategy_name": r.strategy_name,
                        "persona_name": r.persona_name,
                        "is_win": r.is_win,
                        "camp": r.camp,
                        "winner": r.winner,
                        "num_days": r.num_days,
                        "num_decisions": r.num_decisions,
                    }
                )
        print(f"\nResults written to {output_csv} ({len(results)} rows)")

        # Generate markdown report
        _generate_md_report(results, output_md)


def _generate_md_report(results: list[GameResult], output_md: str) -> None:
    """Generate a markdown A/B test report."""
    from collections import defaultdict

    lines = [
        "# Strategy A/B Test V8",
        "",
        "## Summary",
        f"Total games: {len(set(r.game_id for r in results))}",
        f"Total player-results: {len(results)}",
        "",
        "## Per-Strategy Results",
        "",
    ]

    # Group by (role, strategy_id)
    groups = defaultdict(list)
    for r in results:
        groups[(r.role, r.strategy_id)].append(r)

    for (role, sid), group_results in sorted(groups.items()):
        n = len(group_results)
        wins = sum(1 for r in group_results if r.is_win)
        wr = wins / n if n > 0 else 0.0
        avg_days = sum(r.num_days for r in group_results) / n if n > 0 else 0.0
        lines.append(f"### {role} — {sid}")
        lines.append(f"- Games: {n}")
        lines.append(f"- Wins: {wins}/{n} ({wr:.3f})")
        lines.append(f"- Avg days: {avg_days:.1f}")
        lines.append("")

    # Per-role comparison
    lines.append("## Per-Role Comparison")
    lines.append("")
    for role in ["Seer", "Werewolf"]:
        role_results = [r for r in results if r.role == role]
        strategies = sorted(set(r.strategy_id for r in role_results))
        if len(strategies) >= 2:
            lines.append(f"### {role}")
            lines.append("")
            lines.append("| Strategy | N | Win Rate | Avg Days |")
            lines.append("|----------|---|----------|----------|")
            for sid in strategies:
                s_results = [r for r in role_results if r.strategy_id == sid]
                n = len(s_results)
                wr = sum(1 for r in s_results if r.is_win) / n if n > 0 else 0.0
                avg_days = sum(r.num_days for r in s_results) / n if n > 0 else 0.0
                lines.append(f"| {sid} | {n} | {wr:.3f} | {avg_days:.1f} |")
            lines.append("")

    lines.append("## Notes")
    lines.append("- Agent type: heuristic (deterministic, no LLM API needed)")
    lines.append("- Control: same seed, same persona, only strategy_id varies")
    lines.append("- Warning: n<10 per group = LOW_SAMPLE, results are indicative only")
    lines.append("- Win rate alone is not sufficient — behavioral metrics require deeper analysis")

    Path(output_md).parent.mkdir(parents=True, exist_ok=True)
    with open(output_md, "w") as f:
        f.write("\n".join(lines))
    print(f"Report written to {output_md}")


# Import registry for type hints
from backend.agents.strategy_registry import get_strategy_registry  # noqa: E402

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V8 Strategy A/B Test")
    parser.add_argument(
        "--games-per-group", type=int, default=10, help="Games per (role, strategy) group (default: 10)"
    )
    parser.add_argument(
        "--agent-type", type=str, default="heuristic", help="Agent type: heuristic or llm (default: heuristic)"
    )
    parser.add_argument("--player-count", type=int, default=7, help="Players per game (default: 7)")
    parser.add_argument("--output-csv", type=str, default="data/health/strategy_ab_test_results_v8.csv")
    parser.add_argument("--output-md", type=str, default="data/health/strategy_ab_test_v8.md")
    parser.add_argument("--strict", action="store_true", help="Fail on LLM fallback (for llm agent type)")
    args = parser.parse_args()

    run_experiment(
        games_per_group=args.games_per_group,
        agent_type=args.agent_type,
        player_count=args.player_count,
        output_csv=args.output_csv,
        output_md=args.output_md,
        strict=args.strict,
    )
