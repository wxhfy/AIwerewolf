"""Run 20-game AI vs AI experiment to measure win rate and strategy usage.

Usage:
    python scripts/run_winrate_experiment.py [--games 20] [--start-seed 2001]
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time
import traceback
import warnings
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))  # Ensure .env is found by load_env_file()

warnings.filterwarnings("ignore")

import psycopg2

from backend.engine.game import WerewolfGame

DB_URL = "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf"
OUTPUT_DIR = ROOT / "outputs"
PER_GAME_TIMEOUT_SECONDS = 45 * 60  # 45 minutes per game

# ═══════════════════════════════════════════════════════════════
# Phase Observer — logs every phase transition for debugging hangs
# ═══════════════════════════════════════════════════════════════


def _phase_observer_factory(seed: int):
    """Return an observer callback that logs phase transitions with timestamps."""

    t0 = time.perf_counter()

    def observer(state):
        elapsed = time.perf_counter() - t0
        phase = state.phase.value if hasattr(state.phase, "value") else str(state.phase)
        alive = sum(1 for p in state.players if p.alive)
        current_speaker = getattr(state, "current_speaker_id", None)
        speaker_str = f" speaker={current_speaker[-6:]}" if current_speaker else ""
        print(
            f"  [seed={seed}] PHASE: {phase} | day={state.day} | alive={alive} | elapsed={elapsed:.0f}s{speaker_str}",
            flush=True,
        )

    return observer


# ═══════════════════════════════════════════════════════════════
# Per-game runner (runs in a subprocess for timeout isolation)
# ═══════════════════════════════════════════════════════════════


def _run_one_game(seed: int) -> dict[str, Any]:
    """Run a single game and return its result dict. Called via multiprocessing."""
    os.chdir(str(ROOT))

    t0 = time.perf_counter()
    print(f"\n{'=' * 50}", flush=True)
    print(f"Game seed={seed} START at {datetime.now().isoformat()}", flush=True)
    print(f"{'=' * 50}", flush=True)

    try:
        game = WerewolfGame(seed=seed, player_count=7)

        # Log role assignments
        for p in game.state.players:
            mbti = getattr(p, "persona", {})
            mbti_str = mbti.get("mbti", "?") if isinstance(mbti, dict) else "?"
            print(f"  (seed={seed}) Seat {p.seat}: {p.name} = {p.role.value} [{mbti_str}]", flush=True)

        # Attach phase observer for detailed progress logging
        game.observer = _phase_observer_factory(seed)

        state = game.play()
        elapsed = time.perf_counter() - t0

        game_id = str(getattr(state, "id", "") or getattr(state, "game_id", ""))
        winner = state.winner.value if hasattr(state.winner, "value") else str(state.winner)
        days = state.day

        # Per-player stats
        players_info = []
        role_side: dict[str, str] = {}
        for p in state.players:
            role = p.role.value
            team = "wolf" if role in ("Werewolf", "WhiteWolfKing") else "village"
            won = team == winner
            mbti = (p.persona or {}).get("mbti", "UNKNOWN")

            role_side[role] = team

            players_info.append(
                {
                    "name": p.name,
                    "role": role,
                    "seat": p.seat,
                    "alive": p.alive,
                    "death_day": p.death_day,
                    "mbti": mbti,
                    "model": getattr(p, "model_name", "unknown"),
                    "won": won,
                    "team": team,
                }
            )

        # Strategy retrieval count
        retrieval_count = _count_strategy_retrievals(game_id)
        fb = _count_fallback_decisions(game_id)

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

        print(f"  (seed={seed}) DONE: Winner={winner}, Days={days}, Time={elapsed:.0f}s", flush=True)
        for pi in players_info:
            status = "存活" if pi["alive"] else f"D{pi['death_day']}死亡"
            print(f"    Seat {pi['seat']}: {pi['name']} ({pi['role']}, {pi['mbti']}) - {status}", flush=True)

        return game_result

    except Exception as e:
        print(f"  (seed={seed}) FAILED: {e}", flush=True)
        traceback.print_exc()
        return {"seed": seed, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# DB query helpers (module-level so multiprocessing can pickle)
# ═══════════════════════════════════════════════════════════════


def _count_strategy_retrievals(game_id: str) -> int:
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


def _count_fallback_decisions(game_id: str) -> dict[str, int]:
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM agent_decisions WHERE game_id = %s", (game_id,))
        total = cur.fetchone()[0]
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


# ═══════════════════════════════════════════════════════════════
# Experiment orchestrator
# ═══════════════════════════════════════════════════════════════


def _save_incremental(results: list, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp = output_dir / "winrate_report_partial.json"
    tmp.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))


def run_experiment(
    n_games: int = 20,
    start_seed: int = 2001,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run N games, each with a 45-minute timeout via subprocess."""
    results: list[dict[str, Any]] = []
    total_retrievals = 0
    total_retrieval_games = 0
    total_fallback = 0
    total_llm = 0
    high_fallback_games = 0
    timeout_games = 0

    role_stats: dict[str, dict[str, list]] = defaultdict(
        lambda: {"wins": [], "survival_days": [], "alive_endgame": [], "team": "", "mbtis": []}
    )

    for i in range(n_games):
        seed = start_seed + i
        print(f"\n{'#' * 60}", flush=True)
        print(f"# Game {i + 1}/{n_games}: seed={seed} — starting subprocess", flush=True)
        print(f"{'#' * 60}", flush=True)

        t0 = time.perf_counter()

        # Run game in a subprocess with timeout
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=_run_one_game_in_proc, args=(seed, ROOT))
        proc.start()
        proc.join(timeout=PER_GAME_TIMEOUT_SECONDS)

        if proc.is_alive():
            # Timeout — kill and mark
            print(f"  (seed={seed}) TIMEOUT after {PER_GAME_TIMEOUT_SECONDS}s — killing subprocess", flush=True)
            proc.kill()
            proc.join(timeout=10)
            if proc.is_alive():
                print(f"  (seed={seed}) WARNING: subprocess did not die after kill, continuing...", flush=True)
            timeout_games += 1
            results.append({"seed": seed, "error": "timeout", "duration_s": PER_GAME_TIMEOUT_SECONDS})
            _save_incremental(results, OUTPUT_DIR)
            continue

        elapsed = time.perf_counter() - t0

        # Subprocess completed normally; read result from shared file
        result_file = OUTPUT_DIR / f"game_result_seed{seed}.json"
        if result_file.exists():
            try:
                game_result = json.loads(result_file.read_text())
                results.append(game_result)

                if "error" not in game_result:
                    # Accumulate stats
                    retrieval_count = game_result.get("strategy_retrievals", -1)
                    if retrieval_count >= 0:
                        total_retrievals += retrieval_count
                        total_retrieval_games += 1

                    fb_fallback = game_result.get("fallback_decisions", 0)
                    fb_llm = game_result.get("llm_decisions", 0)
                    fb_total = game_result.get("total_decisions", 0)
                    total_fallback += fb_fallback
                    total_llm += fb_llm
                    if fb_total > 0 and fb_fallback / fb_total > 0.3:
                        high_fallback_games += 1

                    for pi in game_result.get("players", []):
                        role = pi["role"]
                        team = pi.get("team", "village")
                        won = pi.get("won", False)
                        role_stats[role]["wins"].append(1.0 if won else 0.0)
                        role_stats[role]["survival_days"].append(
                            float(game_result["days"]) if pi["alive"] else float(pi.get("death_day", 0))
                        )
                        role_stats[role]["alive_endgame"].append(1.0 if pi["alive"] else 0.0)
                        role_stats[role]["team"] = team
                        role_stats[role]["mbtis"].append(pi.get("mbti", "UNKNOWN"))

                    print(
                        f"  (seed={seed}) RESULT: Winner={game_result['winner']}, "
                        f"Days={game_result['days']}, "
                        f"Time={game_result['duration_s']}s ({elapsed:.0f}s wall)",
                        flush=True,
                    )
                else:
                    print(f"  (seed={seed}) ERROR: {game_result['error']}", flush=True)

                # Clean up temp file
                result_file.unlink(missing_ok=True)
            except Exception as e:
                print(f"  (seed={seed}) Failed to read result file: {e}", flush=True)
                results.append({"seed": seed, "error": f"result_read_error: {e}"})
        else:
            # Process ended but no result file — exited with error
            exitcode = proc.exitcode
            results.append({"seed": seed, "error": f"subprocess_exitcode={exitcode}"})

        _save_incremental(results, OUTPUT_DIR)

    # ── Compile summary ──
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

    village_wins = sum(d["win_rate"] * d["games"] for _, d in stats.items() if d["team"] == "village")
    village_games = sum(d["games"] for _, d in stats.items() if d["team"] == "village")
    wolf_wins = sum(d["win_rate"] * d["games"] for _, d in stats.items() if d["team"] == "wolf")
    wolf_games = sum(d["games"] for _, d in stats.items() if d["team"] == "wolf")

    successful_games = [r for r in results if "error" not in r]
    avg_days = sum(r["days"] for r in successful_games) / len(successful_games) if successful_games else 0
    avg_retrievals = total_retrievals / total_retrieval_games if total_retrieval_games > 0 else 0

    # LLM-only win rate (exclude high-fallback games)
    llm_games = [
        r
        for r in successful_games
        if r.get("total_decisions", 0) > 0 and r.get("fallback_decisions", 0) / r["total_decisions"] <= 0.3
    ]
    llm_village_wins = sum(1 for r in llm_games if r["winner"] == "village")
    llm_wolf_wins = sum(1 for r in llm_games if r["winner"] == "wolf")
    llm_village_wr = llm_village_wins / max(len(llm_games), 1)
    llm_wolf_wr = llm_wolf_wins / max(len(llm_games), 1)

    summary = {
        "total_games": n_games,
        "successful_games": len(successful_games),
        "failed_games": n_games - len(successful_games),
        "timeout_games": timeout_games,
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


def _run_one_game_in_proc(seed: int, root: Path) -> None:
    """Top-level function for multiprocessing.Process target (must be picklable)."""
    os.chdir(str(root))
    sys.path.insert(0, str(root))

    result = _run_one_game(seed)
    output_dir = root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = output_dir / f"game_result_seed{seed}.json"
    result_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))


# ═══════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════


def _fmt_pct(d: dict, key: str) -> str:
    val = d.get(key, "N/A")
    if isinstance(val, str):
        return val
    try:
        return f"{float(val):.1%}"
    except (TypeError, ValueError):
        return str(val)


def print_report(summary: dict[str, Any]):
    stats = summary["per_role"]
    successful = summary["successful_games"]

    print()
    print("=" * 60)
    print(f"  20局胜率报告 ({successful}局成功, {summary.get('timeout_games', 0)}局超时)")
    print("=" * 60)
    print(f"  总体胜率: 好人 {summary['village_win_rate']:.1%} | 狼人 {summary['wolf_win_rate']:.1%}")
    print(f"  平均天数: {summary['avg_days']}")
    print(f"  平均策略检索: {summary['avg_strategy_retrievals_per_game']} 次/局")
    fb = summary["fallback_stats"]
    print(
        f"  LLM 决策: {fb['total_llm_decisions']} | Fallback 决策: {fb['total_fallback_decisions']} | Fallback率: {fb['fallback_rate']:.1%}"
    )
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
    stats = summary["per_role"]
    successful = summary["successful_games"]
    fb = summary.get("fallback_stats", {})

    lines = [
        "# 20局胜率实验报告",
        "",
        f"**生成时间**: {datetime.now(timezone.utc).isoformat()}",
        f"**总耗时**: {elapsed_s:.0f}s ({elapsed_s / 60:.1f} min)",
        "",
        "## 总体统计",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 总局数 | {summary['total_games']} |",
        f"| 成功 | {successful} |",
        f"| 失败 | {summary['failed_games']} |",
        f"| 超时 | {summary.get('timeout_games', 0)} |",
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
            err_msg = r["error"]
            lines.append(f"| {i + 1} | {r['seed']} | ❌ {err_msg} | - | - | - | - | - |")
        else:
            lines.append(
                f"| {i + 1} | {r['seed']} | {r['winner']} | {r['days']} | "
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
                f"| {p['seat']} | {p['name']} | {p['role']} | {p['mbti']} | {alive_str} | {death_str} | {won_str} |"
            )
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--start-seed", type=int, default=2001)
    args = parser.parse_args()

    # Force 'spawn' context for subprocess isolation
    multiprocessing.set_start_method("spawn", force=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Running {args.games} games with seeds {args.start_seed}-{args.start_seed + args.games - 1}...", flush=True)
    print(f"Per-game timeout: {PER_GAME_TIMEOUT_SECONDS}s ({PER_GAME_TIMEOUT_SECONDS / 60:.0f} min)", flush=True)
    print(f"Output dir: {OUTPUT_DIR}", flush=True)
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
    print(f"\nJSON report: {json_path}", flush=True)

    # Save Markdown report
    md_content = generate_markdown(summary, results, elapsed)
    md_path = OUTPUT_DIR / "winrate_report.md"
    md_path.write_text(md_content)
    print(f"Markdown report: {md_path}", flush=True)

    print(f"\nTotal time: {elapsed:.0f}s ({elapsed / 60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
