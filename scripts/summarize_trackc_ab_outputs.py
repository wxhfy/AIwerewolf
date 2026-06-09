#!/usr/bin/env python3
"""Summarize Track C A/B validation outputs into report-ready role trends.

The A/B runner stores raw baseline/candidate game metrics per target role.
This script keeps those raw files intact and derives:

- per-role cumulative win-rate trend CSV
- per-role cumulative score trend CSV
- per-role summary CSV
- optional per-role PNG/SVG charts

Win-rate is computed from the target role's camp: Werewolf wins on wolf winner,
all other default roles win on village winner.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROLE_CN = {
    "Villager": "村民",
    "Seer": "预言家",
    "Witch": "女巫",
    "Hunter": "猎人",
    "Guard": "守卫",
    "Werewolf": "狼人",
}

WOLF_ROLES = {"Werewolf", "WhiteWolfKing"}


def configure_matplotlib_fonts(plt: Any) -> None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    try:
        from matplotlib import font_manager
    except Exception:
        font_manager = None
    for item in candidates:
        path = Path(item)
        if not path.exists():
            continue
        if font_manager is not None:
            font_manager.fontManager.addfont(str(path))
            prop = font_manager.FontProperties(fname=str(path))
            plt.rcParams["font.family"] = prop.get_name()
        else:
            plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        return
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class RoleExperiment:
    path: Path
    role: str
    seeds: list[int]
    baseline_results: list[dict[str, Any]]
    candidate_results: list[dict[str, Any]]
    comparison: dict[str, Any]
    status: str
    strict_no_fallback: bool
    model_pool: str

    @property
    def completed_games(self) -> int:
        return min(len(self.baseline_results), len(self.candidate_results), len(self.seeds))


def load_experiment(path: Path) -> RoleExperiment:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RoleExperiment(
        path=path,
        role=str(payload.get("role") or ""),
        seeds=[int(seed) for seed in payload.get("seeds", [])],
        baseline_results=list(payload.get("baseline_results", []) or []),
        candidate_results=list(payload.get("candidate_results", []) or []),
        comparison=dict(payload.get("comparison", {}) or {}),
        status=str(payload.get("status") or ""),
        strict_no_fallback=bool(payload.get("strict_no_fallback")),
        model_pool=str(payload.get("model_pool") or ""),
    )


def target_camp(role: str) -> str:
    return "wolf" if role in WOLF_ROLES else "village"


def normalized_winner(result: dict[str, Any]) -> str:
    winner = str(result.get("winner") or "").strip().lower()
    if winner in {"wolf", "werewolf", "wolves"}:
        return "wolf"
    if winner in {"village", "villager", "villagers", "good", "town"}:
        return "village"
    return winner


def target_won(role: str, result: dict[str, Any]) -> int:
    return 1 if normalized_winner(result) == target_camp(role) else 0


def player_scores_for_role(result: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [score for score in result.get("player_scores", []) or [] if str(score.get("role") or "") == role]


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(result) or math.isinf(result):
        return 0.0
    return result


def avg_role_field(result: dict[str, Any], role: str, field: str, fallback_field: str | None = None) -> float:
    values: list[float] = []
    for score in player_scores_for_role(result, role):
        value = score.get(field)
        if value is None and fallback_field:
            value = score.get(fallback_field)
        values.append(safe_float(value))
    return avg(values)


def derive_winrate_trend(exp: RoleExperiment) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_wins = 0
    candidate_wins = 0
    for idx in range(exp.completed_games):
        seed = exp.seeds[idx] if idx < len(exp.seeds) else idx + 1
        baseline = exp.baseline_results[idx]
        candidate = exp.candidate_results[idx]
        baseline_wins += target_won(exp.role, baseline)
        candidate_wins += target_won(exp.role, candidate)
        game_index = idx + 1
        baseline_rate = baseline_wins / game_index
        candidate_rate = candidate_wins / game_index
        rows.append(
            {
                "role": exp.role,
                "role_cn": ROLE_CN.get(exp.role, exp.role),
                "seed": seed,
                "game_index": game_index,
                "baseline_target_win": target_won(exp.role, baseline),
                "candidate_target_win": target_won(exp.role, candidate),
                "baseline_winner": normalized_winner(baseline),
                "candidate_winner": normalized_winner(candidate),
                "baseline_cumulative_wins": baseline_wins,
                "candidate_cumulative_wins": candidate_wins,
                "baseline_cumulative_win_rate": round(baseline_rate, 6),
                "candidate_cumulative_win_rate": round(candidate_rate, 6),
                "cumulative_delta": round(candidate_rate - baseline_rate, 6),
                "source_file": str(exp.path),
            }
        )
    return rows


def derive_score_trend(exp: RoleExperiment) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    baseline_score_sum = 0.0
    candidate_score_sum = 0.0
    baseline_task_sum = 0.0
    candidate_task_sum = 0.0
    for idx in range(exp.completed_games):
        seed = exp.seeds[idx] if idx < len(exp.seeds) else idx + 1
        baseline = exp.baseline_results[idx]
        candidate = exp.candidate_results[idx]
        baseline_score = avg_role_field(baseline, exp.role, "adjusted_final_score", "final_score")
        candidate_score = avg_role_field(candidate, exp.role, "adjusted_final_score", "final_score")
        baseline_task = avg_role_field(baseline, exp.role, "role_task_score")
        candidate_task = avg_role_field(candidate, exp.role, "role_task_score")
        baseline_score_sum += baseline_score
        candidate_score_sum += candidate_score
        baseline_task_sum += baseline_task
        candidate_task_sum += candidate_task
        game_index = idx + 1
        baseline_cum_score = baseline_score_sum / game_index
        candidate_cum_score = candidate_score_sum / game_index
        baseline_cum_task = baseline_task_sum / game_index
        candidate_cum_task = candidate_task_sum / game_index
        rows.append(
            {
                "role": exp.role,
                "role_cn": ROLE_CN.get(exp.role, exp.role),
                "seed": seed,
                "game_index": game_index,
                "baseline_target_score": round(baseline_score, 6),
                "candidate_target_score": round(candidate_score, 6),
                "baseline_target_role_task": round(baseline_task, 6),
                "candidate_target_role_task": round(candidate_task, 6),
                "baseline_cumulative_target_score": round(baseline_cum_score, 6),
                "candidate_cumulative_target_score": round(candidate_cum_score, 6),
                "score_cumulative_delta": round(candidate_cum_score - baseline_cum_score, 6),
                "baseline_cumulative_role_task": round(baseline_cum_task, 6),
                "candidate_cumulative_role_task": round(candidate_cum_task, 6),
                "role_task_cumulative_delta": round(candidate_cum_task - baseline_cum_task, 6),
                "source_file": str(exp.path),
            }
        )
    return rows


def derive_summary(
    exp: RoleExperiment,
    winrate_rows: list[dict[str, Any]],
    score_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_scores: list[float] = []
    candidate_scores: list[float] = []
    baseline_tasks: list[float] = []
    candidate_tasks: list[float] = []
    for idx in range(exp.completed_games):
        for score in player_scores_for_role(exp.baseline_results[idx], exp.role):
            baseline_scores.append(safe_float(score.get("adjusted_final_score", score.get("final_score"))))
            baseline_tasks.append(safe_float(score.get("role_task_score")))
        for score in player_scores_for_role(exp.candidate_results[idx], exp.role):
            candidate_scores.append(safe_float(score.get("adjusted_final_score", score.get("final_score"))))
            candidate_tasks.append(safe_float(score.get("role_task_score")))

    final_winrate_row = winrate_rows[-1] if winrate_rows else {}
    final_score_row = score_rows[-1] if score_rows else {}
    baseline_win_rate = safe_float(final_winrate_row.get("baseline_cumulative_win_rate"))
    candidate_win_rate = safe_float(final_winrate_row.get("candidate_cumulative_win_rate"))
    comparison = exp.comparison
    return {
        "role": exp.role,
        "role_cn": ROLE_CN.get(exp.role, exp.role),
        "games": exp.completed_games,
        "baseline_target_win_rate": round(baseline_win_rate, 6),
        "candidate_target_win_rate": round(candidate_win_rate, 6),
        "win_rate_delta": round(candidate_win_rate - baseline_win_rate, 6),
        "baseline_target_avg_score": round(avg(baseline_scores), 6),
        "candidate_target_avg_score": round(avg(candidate_scores), 6),
        "score_delta": round(avg(candidate_scores) - avg(baseline_scores), 6),
        "baseline_target_role_task": round(avg(baseline_tasks), 6),
        "candidate_target_role_task": round(avg(candidate_tasks), 6),
        "role_task_delta": round(avg(candidate_tasks) - avg(baseline_tasks), 6),
        "final_score_cumulative_delta": safe_float(final_score_row.get("score_cumulative_delta")),
        "final_role_task_cumulative_delta": safe_float(final_score_row.get("role_task_cumulative_delta")),
        "target_role_avg_score_delta_pct": safe_float(comparison.get("target_role_avg_score_delta")),
        "role_task_score_delta_pct": safe_float(comparison.get("role_task_score_delta")),
        "candidate_fallback_count": int(safe_float(comparison.get("candidate_fallback_count"))),
        "info_leak_count": int(safe_float(comparison.get("info_leak_count"))),
        "invalid_action_rate": safe_float(comparison.get("invalid_action_rate")),
        "status": exp.status,
        "strict_no_fallback": exp.strict_no_fallback,
        "model_pool": exp.model_pool,
        "positive_win_lift": candidate_win_rate > baseline_win_rate,
        "positive_score_lift": avg(candidate_scores) > avg(baseline_scores),
        "positive_role_task_lift": avg(candidate_tasks) > avg(baseline_tasks),
        "source_file": str(exp.path),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def plot_role_trends(rows: list[dict[str, Any]], assets_dir: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional local visualization
        print(f"Skipping plots: matplotlib unavailable ({exc})")
        return

    assets_dir.mkdir(parents=True, exist_ok=True)
    configure_matplotlib_fonts(plt)
    roles = sorted(
        {str(row["role"]) for row in rows}, key=lambda role: list(ROLE_CN).index(role) if role in ROLE_CN else 99
    )
    for role in roles:
        bucket = [row for row in rows if row["role"] == role]
        x = [int(row["game_index"]) for row in bucket]
        baseline = [safe_float(row["baseline_cumulative_win_rate"]) * 100.0 for row in bucket]
        candidate = [safe_float(row["candidate_cumulative_win_rate"]) * 100.0 for row in bucket]
        fig, ax = plt.subplots(figsize=(7.4, 4.4))
        ax.plot(x, baseline, color="#6b7280", linestyle="--", linewidth=2.2, marker="o", label="baseline")
        ax.plot(x, candidate, color="#15803d", linewidth=2.6, marker="o", label="Track C")
        ax.fill_between(x, baseline, candidate, color="#86efac", alpha=0.22)
        ax.set_title(f"{ROLE_CN.get(role, role)} 20 局累计胜率趋势", fontsize=14)
        ax.set_xlabel("对局序号")
        ax.set_ylabel("累计胜率")
        ax.set_ylim(0, 105)
        ax.set_xlim(1, max(x) if x else 20)
        ax.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.legend(loc="best")
        fig.tight_layout()
        slug = role.lower()
        fig.savefig(assets_dir / f"trackc_ab_role_winrate_trend_{slug}.png", dpi=220, bbox_inches="tight")
        fig.savefig(assets_dir / f"trackc_ab_role_winrate_trend_{slug}.svg", bbox_inches="tight")
        plt.close(fig)


def plot_score_trends(rows: list[dict[str, Any]], assets_dir: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional local visualization
        print(f"Skipping score plots: matplotlib unavailable ({exc})")
        return

    assets_dir.mkdir(parents=True, exist_ok=True)
    configure_matplotlib_fonts(plt)
    roles = sorted(
        {str(row["role"]) for row in rows}, key=lambda role: list(ROLE_CN).index(role) if role in ROLE_CN else 99
    )
    for role in roles:
        bucket = [row for row in rows if row["role"] == role]
        x = [int(row["game_index"]) for row in bucket]
        baseline = [safe_float(row["baseline_cumulative_target_score"]) for row in bucket]
        candidate = [safe_float(row["candidate_cumulative_target_score"]) for row in bucket]
        fig, ax = plt.subplots(figsize=(7.4, 4.4))
        ax.plot(x, baseline, color="#6b7280", linestyle="--", linewidth=2.2, marker="o", label="baseline")
        ax.plot(x, candidate, color="#15803d", linewidth=2.6, marker="o", label="Track C")
        ax.fill_between(x, baseline, candidate, color="#86efac", alpha=0.22)
        ax.set_title(f"{ROLE_CN.get(role, role)} 20 局累计策略分数趋势", fontsize=14)
        ax.set_xlabel("对局序号")
        ax.set_ylabel("累计目标角色分数")
        ax.set_xlim(1, max(x) if x else 20)
        ax.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.legend(loc="best")
        fig.tight_layout()
        slug = role.lower()
        fig.savefig(assets_dir / f"trackc_ab_role_score_trend_{slug}.png", dpi=220, bbox_inches="tight")
        fig.savefig(assets_dir / f"trackc_ab_role_score_trend_{slug}.svg", bbox_inches="tight")
        plt.close(fig)


def discover_inputs(args: argparse.Namespace) -> list[Path]:
    inputs: list[Path] = []
    for item in args.inputs or []:
        path = Path(item)
        if path.is_dir():
            inputs.extend(sorted(path.rglob("c_validation_*.json")))
        else:
            inputs.extend(sorted(Path().glob(str(path))) if any(ch in str(path) for ch in "*?[") else [path])
    if args.root:
        inputs.extend(sorted(Path(args.root).rglob("c_validation_*.json")))
    unique: dict[Path, None] = {}
    for path in inputs:
        if path.name.endswith(".partial_summary.json"):
            continue
        if path.exists() and path.is_file():
            unique[path.resolve()] = None
    return list(unique)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="*", help="Input JSON files, globs, or directories.")
    parser.add_argument("--root", help="Root directory to scan recursively for c_validation_*.json.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--plot", default="true")
    args = parser.parse_args()

    input_paths = discover_inputs(args)
    if not input_paths:
        raise SystemExit("No completed c_validation_*.json files found")

    experiments = [load_experiment(path) for path in input_paths]
    winrate_trend_rows: list[dict[str, Any]] = []
    score_trend_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for exp in experiments:
        winrate_rows = derive_winrate_trend(exp)
        score_rows = derive_score_trend(exp)
        winrate_trend_rows.extend(winrate_rows)
        score_trend_rows.extend(score_rows)
        summary_rows.append(derive_summary(exp, winrate_rows, score_rows))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    winrate_trend_csv = args.output_dir / "trackc_ab_role_winrate_trend_20_games.csv"
    score_trend_csv = args.output_dir / "trackc_ab_role_score_trend_20_games.csv"
    summary_csv = args.output_dir / "trackc_ab_role_summary.csv"
    summary_json = args.output_dir / "trackc_ab_experiment_summary.json"
    write_csv(winrate_trend_csv, winrate_trend_rows)
    write_csv(score_trend_csv, score_trend_rows)
    write_csv(summary_csv, summary_rows)
    summary_json.write_text(
        json.dumps(
            {
                "input_files": [str(path) for path in input_paths],
                "roles": [row["role"] for row in summary_rows],
                "role_count": len(summary_rows),
                "all_positive_win_lift": all(bool(row["positive_win_lift"]) for row in summary_rows),
                "all_positive_score_lift": all(bool(row["positive_score_lift"]) for row in summary_rows),
                "all_positive_role_task_lift": all(bool(row["positive_role_task_lift"]) for row in summary_rows),
                "summary_rows": summary_rows,
                "winrate_trend_csv": str(winrate_trend_csv),
                "score_trend_csv": str(score_trend_csv),
                "summary_csv": str(summary_csv),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.plot.lower() not in {"false", "0", "no", "off"}:
        plot_role_trends(winrate_trend_rows, args.output_dir / "assets")
        plot_score_trends(score_trend_rows, args.output_dir / "assets")

    print(f"Wrote {winrate_trend_csv}")
    print(f"Wrote {score_trend_csv}")
    print(f"Wrote {summary_csv}")
    print(f"Wrote {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
