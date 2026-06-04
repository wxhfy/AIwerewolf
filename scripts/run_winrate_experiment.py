"""Run 20-game AI vs AI experiment to measure win rate and strategy usage.

Usage:
    python scripts/run_winrate_experiment.py [--games 20] [--start-seed 1001]
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("ignore")

import psycopg2
from backend.engine.game import WerewolfGame
from backend.engine.models import Role

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
OUTPUT_DIR = ROOT / "outputs"


def count_strategy_retrievals(game_id: str) -> int:
    """Count search_strategies tool calls for a completed game."""
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM agent_decisions, "
            "LATERAL jsonb_array_elements("
            "  CASE WHEN parsed_action->'_tool_trace' IS NOT NULL "
            "       THEN parsed_action->'_tool_trace' ELSE '[]'::jsonb END"
            ") AS t "
            "WHERE game_id = %s AND t->>'tool' = 'search_strategies'",
            (game_id,),
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception:
        return -1


def _fmt_pct(d: dict, key: str) -> str:
    """Format a dict value as percentage, safely avoiding nested f-string quotes."""
    val = d.get(key, "N/A")
    if isinstance(val, str):
        return val
    try:
        return f"{float(val):.1%}"
    except (TypeError, ValueError):
        return str(val)


def count_fallback_decisions(game_id: str) -> dict[str, int]:
    """Count LLM vs fallback (heuristic) decisions for a completed game."""
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur = conn.cursor()
        # Total decisions
        cur.execute("SELECT COUNT(*) FROM agent_decisions WHERE game_id = %s", (game_id,))
        total = cur.fetchone()[0]
        # Fallback decisions (parsed_action contains fallback=true or fallback_used=true)
        cur.execute(
            "SELECT COUNT(*) FROM agent_decisions WHERE game_id = %s "
            "AND (parsed_action->>'fallback' = 'true' "
            "OR parsed_action->>'fallback_used' = 'true' "
            "OR raw_output LIKE '%%HEURISTIC_FALLBACK%%')",
            (game_id,),
        )
        fallback = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"total": total, "fallback": fallback, "llm": total - fallback}
    except Exception:
        return {"total": 0, "fallback": 0, "llm": 0}


def _save_incremental(results: list, output_dir: Path) -> None:
    """Save partial results after each game, overwritten each time."""
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp = output_dir / "winrate_report_partial.json"
    tmp.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))


def run_experiment(
    n_games: int = 20,
    start_seed: int = 1001,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run N games and collect per-role statistics and strategy usage."""
    results = []
    total_retrievals = 0
    total_retrieval_games = 0

    role_stats: dict[str, dict[str, list]] = defaultdict(
        lambda: {"wins": [], "survival_days": [], "alive_endgame": [], "team": "", "mbtis": []}
    )
    total_fallback = 0
    total_llm = 0
    high_fallback_games = 0

    for i in range(n_games):
        seed = start_seed + i
        t0 = time.perf_counter()
        print(f"\n{'='*50}", flush=True)
        print(f"Game {i+1}/{n_games}: seed={seed}", flush=True)
        print(f"{'='*50}", flush=True)

        try:
            game = WerewolfGame(seed=seed, player_count=7)
            state = game.play()
            elapsed = time.perf_counter() - t0

            game_id = str(getattr(state, "id", "") or getattr(state, "game_id", ""))
            winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
            days = state.day

            # Per-player stats
            players_info = []
            for p in state.players:
                role = p.role.value
                team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
                won = team == winner
                mbti = (p.persona or {}).get("mbti", "UNKNOWN")

                role_stats[role]["wins"].append(1.0 if won else 0.0)
                role_stats[role]["survival_days"].append(
                    float(days if p.alive else (p.death_day or 0))
                )
                role_stats[role]["alive_endgame"].append(1.0 if p.alive else 0.0)
                role_stats[role]["team"] = team
                role_stats[role]["mbtis"].append(mbti)

                players_info.append({
                    "name": p.name,
                    "role": role,
                    "seat": p.seat,
                    "alive": p.alive,
                    "death_day": p.death_day,
                    "mbti": mbti,
                    "model": getattr(p, "model_name", "unknown"),
                    "won": won,
                })

            # Strategy retrieval count
            retrieval_count = count_strategy_retrievals(game_id)
            if retrieval_count >= 0:
                total_retrievals += retrieval_count
                total_retrieval_games += 1

            # Fallback tracking
            fb = count_fallback_decisions(game_id)
            total_fallback += fb["fallback"]
            total_llm += fb["llm"]
            if fb["total"] > 0 and fb["fallback"] / fb["total"] > 0.3:
                high_fallback_games += 1

            game_result = {
                "game_id": game_id,
                "seed": seed,
                "winner": winner,
                "days": days,
                "duration_s": round(elapsed, 1),
                "strategy_retrievals": retrieval_count,
                "fallback_decisions": fb["fallback"],
                "llm_decisions": fb["llm"],
                "total_decisions": fb["total"],
                "players": players_info,
            }
            results.append(game_result)

            print(f"  Winner: {winner}, Days: {days}, Time: {elapsed:.0f}s", flush=True)
            print(f"  Strategy retrievals: {retrieval_count} | LLM: {fb['llm']} | Fallback: {fb['fallback']}", flush=True)
            for pi in players_info:
                status = "存活" if pi["alive"] else f"D{pi['death_day']}死亡"
                print(f"    Seat {pi['seat']}: {pi['name']} ({pi['role']}, {pi['mbti']}) - {status}", flush=True)

            # Save incremental results after each game
            _save_incremental(results, OUTPUT_DIR)

        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append({"seed": seed, "error": str(e)})

    # Compile summary stats
    stats: dict[str, Any] = {}
    for role, data in sorted(role_stats.items()):
        wins = data["wins"]
        surv = data["survival_days"]
        alive = data["alive_endgame"]
        n = len(wins)
        stats[role] = {
            "team": data["team"],
            "games": n,
            "win_rate": round(sum(wins) / max(n, 1), 4),
            "avg_survival_days": round(sum(surv) / max(n, 1), 2),
            "alive_endgame_rate": round(sum(alive) / max(n, 1), 4),
        }

    # Team-level aggregates
    village_wins = sum(
        d["win_rate"] * d["games"] for _, d in stats.items() if d["team"] == "village"
    )
    village_games = sum(d["games"] for _, d in stats.items() if d["team"] == "village")
    wolf_wins = sum(
        d["win_rate"] * d["games"] for _, d in stats.items() if d["team"] == "wolf"
    )
    wolf_games = sum(d["games"] for _, d in stats.items() if d["team"] == "wolf")

    successful_games = [r for r in results if "error" not in r]
    avg_days = (
        sum(r["days"] for r in successful_games) / len(successful_games)
        if successful_games
        else 0
    )
    avg_retrievals = (
        total_retrievals / total_retrieval_games if total_retrieval_games > 0 else 0
    )

    # LLM-only win rate (exclude high-fallback games)
    llm_games = [r for r in successful_games
                 if r.get("total_decisions", 0) > 0
                 and r.get("fallback_decisions", 0) / r["total_decisions"] <= 0.3]
    llm_village_wins = sum(1 for r in llm_games if r["winner"] == "village")
    llm_wolf_wins = sum(1 for r in llm_games if r["winner"] == "wolf")
    llm_village_wr = llm_village_wins / max(len(llm_games), 1)
    llm_wolf_wr = llm_wolf_wins / max(len(llm_games), 1)

    summary = {
        "total_games": n_games,
        "successful_games": len(successful_games),
        "failed_games": n_games - len(successful_games),
        "village_win_rate": round(village_wins / max(village_games, 1), 4),
        "wolf_win_rate": round(wolf_wins / max(wolf_games, 1), 4),
        "avg_days": round(avg_days, 2),
        "avg_strategy_retrievals_per_game": round(avg_retrievals, 2),
        "total_strategy_retrievals": total_retrievals,
        "per_role": stats,
        "fallback_stats": {
            "total_llm_decisions": total_llm,
            "total_fallback_decisions": total_fallback,
            "fallback_rate": round(total_fallback / max(total_llm + total_fallback, 1), 4),
            "high_fallback_games": high_fallback_games,
            "llm_only_games": len(llm_games),
            "llm_only_village_win_rate": round(llm_village_wr, 4),
            "llm_only_wolf_win_rate": round(llm_wolf_wr, 4),
        },
    }

    return results, summary


def print_report(summary: dict[str, Any]):
    """Print formatted winrate report."""
    stats = summary["per_role"]
    successful = summary["successful_games"]

    print()
    print("=" * 60)
    print(f"  20局胜率报告 ({successful}局成功)")
    print("=" * 60)
    print(f"  总体胜率: 好人 {summary['village_win_rate']:.1%} | 狼人 {summary['wolf_win_rate']:.1%}")
    print(f"  平均天数: {summary['avg_days']}")
    print(f"  平均策略检索: {summary['avg_strategy_retrievals_per_game']} 次/局")
    fb = summary["fallback_stats"]
    print(f"  LLM 决策: {fb['total_llm_decisions']} | Fallback 决策: {fb['total_fallback_decisions']} | Fallback率: {fb['fallback_rate']:.1%}")
    print(f"  高Fallback局(>30%): {fb['high_fallback_games']} | LLM-only局: {fb['llm_only_games']}")
    print(f"  LLM-only 胜率: 好人 {fb['llm_only_village_win_rate']:.1%} | 狼人 {fb['llm_only_wolf_win_rate']:.1%}")
    print()
    print(f"  {'角色':<16s} {'阵营':<6s} {'出场':>4s} {'胜率':>8s} {'存活天':>6s}")
    print("  " + "-" * 50)

    for role, data in sorted(stats.items()):
        team = data["team"]
        games = data["games"]
        wr = f"{data['win_rate']:.1%}"
        sd = f"{data['avg_survival_days']:.1f}"
        print(f"  {role:<16s} {team:<6s} {games:>4d} {wr:>8s} {sd:>6s}")

    print("=" * 60)


def generate_markdown(summary: dict[str, Any], results: list[dict], elapsed_s: float) -> str:
    """Generate Markdown report string."""
    stats = summary["per_role"]
    successful = summary["successful_games"]

    fb = summary.get("fallback_stats", {})
    lines = [
        "# 20局胜率实验报告",
        "",
        f"**生成时间**: {datetime.now(timezone.utc).isoformat()}",
        f"**总耗时**: {elapsed_s:.0f}s ({elapsed_s/60:.1f} min)",
        "",
        "## 总体统计",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 总局数 | {summary['total_games']} |",
        f"| 成功 | {successful} |",
        f"| 失败 | {summary['failed_games']} |",
        f"| 好人胜率 | {summary['village_win_rate']:.1%} |",
        f"| 狼人胜率 | {summary['wolf_win_rate']:.1%} |",
        f"| 平均天数 | {summary['avg_days']} |",
        f"| 平均策略检索/局 | {summary['avg_strategy_retrievals_per_game']} |",
        f"| 总策略检索次数 | {summary['total_strategy_retrievals']} |",
        "",
        "## Fallback 统计",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| LLM 决策总数 | {fb.get('total_llm_decisions', 'N/A')} |",
        f"| Fallback 决策总数 | {fb.get('total_fallback_decisions', 'N/A')} |",
        f"| Fallback 率 | {_fmt_pct(fb, 'fallback_rate')} |",
        f"| 高Fallback局(>30%) | {fb.get('high_fallback_games', 'N/A')} |",
        f"| LLM-only 局数 | {fb.get('llm_only_games', 'N/A')} |",
        f"| LLM-only 好人胜率 | {_fmt_pct(fb, 'llm_only_village_win_rate')} |",
        f"| LLM-only 狼人胜率 | {_fmt_pct(fb, 'llm_only_wolf_win_rate')} |",
        "",
        "## 各角色胜率",
        "",
        "| 角色 | 阵营 | 出场 | 胜率 | 平均存活天 |",
        "|------|------|------|------|-----------|",
    ]

    for role, data in sorted(stats.items()):
        team = data["team"]
        games = data["games"]
        wr = f"{data['win_rate']:.1%}"
        sd = f"{data['avg_survival_days']:.1f}"
        lines.append(f"| {role} | {team} | {games} | {wr} | {sd} |")

    lines += [
        "",
        "## 每局详情",
        "",
        "| # | Seed | 胜者 | 天数 | LLM | Fallback | 策略检索 | 耗时 |",
        "|---|------|------|------|-----|---------|---------|------|",
    ]

    for i, r in enumerate(results):
        if "error" in r:
            lines.append(f"| {i+1} | {r['seed']} | ❌ ERROR | - | - | - |")
        else:
            lines.append(
                f"| {i+1} | {r['seed']} | {r['winner']} | {r['days']} | "
                f"{r.get('llm_decisions', 'N/A')} | {r.get('fallback_decisions', 'N/A')} | "
                f"{r['strategy_retrievals']} | {r['duration_s']}s |"
            )

    lines += [
        "",
        "## 玩家详情",
        "",
    ]

    for r in results:
        if "error" in r:
            continue
        lines.append(f"### Game {r['seed']} — Winner: {r['winner']}, Days: {r['days']}")
        lines.append("")
        lines.append("| Seat | Name | Role | MBTI | Alive | Death Day | Won |")
        lines.append("|------|------|------|------|-------|-----------|-----|")
        for p in r["players"]:
            alive_str = "✅" if p["alive"] else "❌"
            death_str = str(p["death_day"]) if p["death_day"] else "-"
            won_str = "✅" if p["won"] else "❌"
            lines.append(
                f"| {p['seat']} | {p['name']} | {p['role']} | {p['mbti']} | "
                f"{alive_str} | {death_str} | {won_str} |"
            )
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--start-seed", type=int, default=1001)
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Running {args.games} games with seeds {args.start_seed}-{args.start_seed + args.games - 1}...")
    t0 = time.perf_counter()

    results, summary = run_experiment(n_games=args.games, start_seed=args.start_seed)

    elapsed = time.perf_counter() - t0
    print_report(summary)

    # Save JSON report
    json_path = OUTPUT_DIR / "winrate_report.json"
    payload = {
        "summary": summary,
        "results": results,
        "elapsed_s": round(elapsed, 1),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nJSON report: {json_path}")

    # Save Markdown report
    md_content = generate_markdown(summary, results, elapsed)
    md_path = OUTPUT_DIR / "winrate_report.md"
    md_path.write_text(md_content)
    print(f"Markdown report: {md_path}")

    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
