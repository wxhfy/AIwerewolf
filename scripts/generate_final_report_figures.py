"""Generate final-delivery report figures from local evidence JSON files.

The report uses Mermaid for structural diagrams and these matplotlib figures
for numeric results. Figures intentionally avoid interpretive conclusion
sentences; the Markdown body explains the results.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "docs" / "final_delivery"
EVIDENCE = DELIVERY / "evidence"
ASSETS = DELIVERY / "assets"

FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

COLORS = {
    "bg": "#f7f4ed",
    "panel": "#fffaf2",
    "grid": "#d8c6a2",
    "text": "#2a2118",
    "muted": "#6a5a46",
    "blue": "#2f7fd3",
    "green": "#1f7a3a",
    "amber": "#bd8719",
    "red": "#b44949",
    "gray": "#9a8f80",
}


def leaderboard_source(data: dict) -> dict:
    if "source" in data:
        return data["source"]
    return data["source_summary"]


def leaderboard_rankings(data: dict) -> list[dict]:
    return data.get("model_rankings") or data.get("model_rankings_top6") or []


def leaderboard_decision_totals(data: dict) -> dict:
    if "decision_health" in data:
        return data["decision_health"]["totals"]
    rankings = leaderboard_rankings(data)
    return {
        "decision_count": sum(float(r.get("decision_count", 0)) for r in rankings),
        "fallback_count": sum(float(r.get("fallback_count", 0)) for r in rankings),
        "invalid_count": sum(float(r.get("invalid_count", 0)) for r in rankings),
    }


def retrieval_rows(data: dict) -> list[dict]:
    if "aggregate" in data:
        return data["aggregate"]["ranked_policies"]
    best = data["best_policy_metrics"]
    baseline = best["avg_overall"] - best["delta_vs_baseline"]
    return [
        {
            "policy": "same_role_all_mbti",
            "avg_overall": best["avg_overall"],
            "avg_role_fit": best["avg_role_fit"],
            "avg_strategic_depth": best["avg_strategic_depth"],
            "avg_actionability": best["avg_actionability"],
            "avg_information_safety": best["avg_information_safety"],
            "win_count": best["win_count"],
            "delta_vs_no_retrieval": best["delta_vs_baseline"],
        },
        {
            "policy": "baseline",
            "avg_overall": baseline,
            "avg_role_fit": None,
            "avg_strategic_depth": None,
            "avg_actionability": None,
            "avg_information_safety": None,
            "win_count": None,
            "delta_vs_no_retrieval": 0.0,
        },
    ]


def retrieval_best_policy(data: dict) -> str:
    if "aggregate" in data:
        return data["aggregate"]["best_policy"]
    return data["best_policy"]


def usage_overall(data: dict) -> dict:
    if "overall" in data:
        return data["overall"]["used_vs_unused"]
    item = data["overall_positive_result"]
    return {
        "used_count": item["strategy_used_count"],
        "unused_count": item["baseline_count"],
        "used_mean": item["strategy_used_mean"],
        "unused_mean": item["baseline_mean"],
        "used_median": None,
        "unused_median": None,
        "mean_delta_used_minus_unused": item["mean_delta"],
        "bootstrap_ci_low": item["ci"][0],
        "bootstrap_ci_high": item["ci"][1],
    }


def usage_roles(data: dict) -> list[dict]:
    if "by_role" in data:
        return data["by_role"]
    rows = []
    for row in data["positive_by_role"]:
        rows.append(
            {
                "role": row["role"],
                "used_mean": row["strategy_used_mean"],
                "unused_mean": row["baseline_mean"],
                "mean_delta_used_minus_unused": row["delta"],
                "used_count": None,
                "unused_count": None,
            }
        )
    return rows


def load_json(name: str) -> dict:
    with (EVIDENCE / name).open(encoding="utf-8") as f:
        return json.load(f)


def setup_style() -> None:
    font_manager.fontManager.addfont(FONT_REGULAR)
    font_manager.fontManager.addfont(FONT_BOLD)
    font_name = FontProperties(fname=FONT_REGULAR).get_name()
    mpl.rcParams.update(
        {
            "font.family": font_name,
            "font.sans-serif": [font_name, "DejaVu Sans"],
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "svg.hashsalt": "aiwerewolf-final-delivery",
            "figure.facecolor": COLORS["bg"],
            "axes.facecolor": COLORS["panel"],
            "axes.edgecolor": COLORS["grid"],
            "axes.labelcolor": COLORS["muted"],
            "xtick.color": COLORS["muted"],
            "ytick.color": COLORS["muted"],
            "text.color": COLORS["text"],
            "axes.titleweight": "bold",
        }
    )


def bold_font(size: int) -> FontProperties:
    return FontProperties(fname=FONT_BOLD, size=size)


def regular_font(size: int) -> FontProperties:
    return FontProperties(fname=FONT_REGULAR, size=size)


def finish(fig: plt.Figure, filename: str) -> None:
    out = ASSETS / filename
    fig.savefig(
        out,
        format="svg",
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
        metadata={"Date": "2026-06-10"},
    )
    plt.close(fig)
    print(f"wrote {out.relative_to(ROOT)}")


def add_bar_labels(ax: plt.Axes, fmt: str = "{:,.0f}") -> None:
    for patch in ax.patches:
        width = patch.get_width()
        height = patch.get_height()
        if height >= width:
            x = patch.get_x() + patch.get_width() / 2
            y = patch.get_y() + height
            ax.text(x, y, fmt.format(height), ha="center", va="bottom", fontsize=10)
        else:
            x = patch.get_x() + width
            y = patch.get_y() + patch.get_height() / 2
            ax.text(x, y, fmt.format(width), ha="left", va="center", fontsize=10)


def plot_core_dashboard() -> None:
    coverage = load_json("TRACK_B_DB_COVERAGE.json")
    leaderboard = load_json("leaderboard_data_current.json")
    retrieval = load_json("PROJECT_SINGLE_AGENT_RETRIEVAL_LLM_ABLATION.json")
    usage = load_json("PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json")

    summary = coverage["summary"]
    source = leaderboard_source(leaderboard)
    best = retrieval_rows(retrieval)[0]
    used = usage_overall(usage)

    fig = plt.figure(figsize=(15, 9), constrained_layout=True)
    fig.suptitle("AI Werewolf 核心证据数据看板", fontproperties=bold_font(24), x=0.03, ha="left")
    subfigs = fig.subfigures(2, 2, wspace=0.08, hspace=0.14)

    ax = subfigs[0, 0].subplots()
    labels = ["非 fake 对局", "PublishedReview", "有逐步评分对局", "逐决策评分"]
    values = [
        summary["nonfake_games"],
        summary["published_reviews"],
        summary["games_with_per_step_scores"],
        summary["per_step_scores"],
    ]
    ax.bar(labels, values, color=[COLORS["blue"], COLORS["amber"], COLORS["green"], COLORS["red"]])
    ax.set_title("Track B 覆盖规模", fontproperties=bold_font(15))
    ax.set_ylabel("数量")
    ax.tick_params(axis="x", labelrotation=16)
    ax.grid(axis="y", alpha=0.25)
    add_bar_labels(ax)

    ax = subfigs[0, 1].subplots()
    labels = ["唯一对局", "席位样本", "模型数", "结构化决策"]
    values = [
        source["game_count"],
        source["player_samples"],
        source.get("model_count", len(leaderboard_rankings(leaderboard))),
        int(leaderboard_decision_totals(leaderboard)["decision_count"]),
    ]
    ax.bar(labels, values, color=[COLORS["blue"], COLORS["green"], COLORS["amber"], COLORS["red"]])
    ax.set_title("当前模型榜样本", fontproperties=bold_font(15))
    ax.grid(axis="y", alpha=0.25)
    add_bar_labels(ax)

    ax = subfigs[1, 0].subplots()
    labels = ["active 文档", "A/B 场景", "最优策略分", "相对无检索"]
    values = [
        retrieval["retriever_size"],
        retrieval["scenario_count"],
        best["avg_overall"],
        best["delta_vs_no_retrieval"],
    ]
    ax.bar(labels, values, color=[COLORS["green"], COLORS["blue"], COLORS["amber"], COLORS["red"]])
    ax.set_title("Track C 检索证据", fontproperties=bold_font(15))
    ax.grid(axis="y", alpha=0.25)
    for patch, value in zip(ax.patches, values):
        ax.text(
            patch.get_x() + patch.get_width() / 2,
            patch.get_height(),
            f"{value:,.2f}" if value < 20 else f"{value:,.0f}",
            ha="center",
            va="bottom",
            fontsize=10,
        )

    ax = subfigs[1, 1].subplots()
    labels = ["使用策略决策", "未使用策略决策"]
    values = [used["used_count"], used["unused_count"]]
    ax.bar(labels, values, color=[COLORS["green"], COLORS["gray"]])
    ax.set_title("策略使用记录", fontproperties=bold_font(15))
    ax.grid(axis="y", alpha=0.25)
    add_bar_labels(ax)
    ax.text(
        0.02,
        0.88,
        f"平均分差 +{used['mean_delta_used_minus_unused']:.3f}\n95% CI [{used['bootstrap_ci_low']:.3f}, {used['bootstrap_ci_high']:.3f}]",
        transform=ax.transAxes,
        fontproperties=regular_font(11),
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#ffffff", "edgecolor": COLORS["grid"]},
    )

    finish(fig, "core-evidence-dashboard.svg")


def plot_leaderboard() -> None:
    data = load_json("leaderboard_data_current.json")
    rankings = leaderboard_rankings(data)[:8]
    labels = [r["model"].replace("anthropic:", "").replace("[1m]", "") for r in rankings]
    scores = [r["avg_score"] for r in rankings]
    win_rates = [r["win_rate"] * 100 for r in rankings]

    fig, axes = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw={"width_ratios": [1.35, 1]})
    fig.suptitle("当前模型榜结果快照", fontproperties=bold_font(24), x=0.03, ha="left")

    ax = axes[0]
    y = list(range(len(labels)))[::-1]
    ax.barh(y, scores[::-1], color=COLORS["blue"])
    ax.set_yticks(y, labels[::-1], fontproperties=regular_font(10))
    ax.set_xlabel("平均分")
    ax.set_title("Top 8 模型平均分", fontproperties=bold_font(15))
    ax.grid(axis="x", alpha=0.25)
    for yi, value in zip(y, scores[::-1]):
        ax.text(value + 0.8, yi, f"{value:.1f}", va="center", fontsize=10)

    ax = axes[1]
    x = range(len(labels))
    ax.plot(x, win_rates, marker="o", color=COLORS["green"], linewidth=2.6, label="胜率")
    ax.bar(x, [r["knowledge_hit_rate"] * 100 for r in rankings], color=COLORS["amber"], alpha=0.65, label="知识命中率")
    ax.set_xticks(x, [f"R{r['rank']}" for r in rankings])
    ax.set_ylim(0, 100)
    ax.set_ylabel("%")
    ax.set_title("胜率与知识命中率", fontproperties=bold_font(15))
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False)
    totals = leaderboard_decision_totals(data)
    source = leaderboard_source(data)
    ax.text(
        0.03,
        0.06,
        f"样本：{source['game_count']} 局 / {source['player_samples']} 席位 / {source.get('model_count', len(leaderboard_rankings(data)))} 模型\n"
        f"fallback={int(totals['fallback_count'])}, invalid={int(totals['invalid_count'])}",
        transform=ax.transAxes,
        fontproperties=regular_font(10),
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#ffffff", "edgecolor": COLORS["grid"]},
    )
    finish(fig, "leaderboard-snapshot.svg")


def plot_retrieval_ablation() -> None:
    data = load_json("PROJECT_SINGLE_AGENT_RETRIEVAL_LLM_ABLATION.json")
    rows = retrieval_rows(data)
    labels = [r["policy"] for r in rows]

    fig, axes = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw={"width_ratios": [1, 1.2]})
    fig.suptitle("单 Agent 策略检索 A/B", fontproperties=bold_font(24), x=0.03, ha="left")

    ax = axes[0]
    values = [r["avg_overall"] for r in rows]
    colors = [COLORS["green"] if r["policy"] == retrieval_best_policy(data) else COLORS["blue"] for r in rows]
    ax.bar(labels, values, color=colors)
    ax.set_ylim(0, 10)
    ax.set_ylabel("综合分")
    ax.set_title("检索策略综合分", fontproperties=bold_font(15))
    ax.tick_params(axis="x", labelrotation=18)
    ax.grid(axis="y", alpha=0.25)
    for patch, value in zip(ax.patches, values):
        ax.text(patch.get_x() + patch.get_width() / 2, value + 0.12, f"{value:.2f}", ha="center", fontsize=10)

    ax = axes[1]
    best = rows[0]
    dims = ["role_fit", "strategic_depth", "actionability", "information_safety"]
    names = ["角色适配", "策略深度", "可执行性", "信息安全"]
    vals = [best[f"avg_{dim}"] for dim in dims]
    ax.barh(names, vals, color=[COLORS["green"], COLORS["blue"], COLORS["amber"], COLORS["red"]])
    ax.set_xlim(0, 10)
    ax.set_xlabel("评分")
    ax.set_title(f"最优策略维度：{best['policy']}", fontproperties=bold_font(15))
    ax.grid(axis="x", alpha=0.25)
    for patch, value in zip(ax.patches, vals):
        ax.text(value + 0.12, patch.get_y() + patch.get_height() / 2, f"{value:.2f}", va="center", fontsize=10)
    ax.text(
        0.02,
        0.06,
        f"场景数：{data['scenario_count']}；active 文档：{data['retriever_size']}；相对无检索：+{best['delta_vs_no_retrieval']:.2f}",
        transform=ax.transAxes,
        fontproperties=regular_font(10),
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#ffffff", "edgecolor": COLORS["grid"]},
    )
    finish(fig, "retrieval-ablation-chart.svg")


def plot_strategy_usage() -> None:
    data = load_json("PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json")
    overall = usage_overall(data)
    roles = usage_roles(data)

    fig, axes = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw={"width_ratios": [0.9, 1.3]})
    fig.suptitle("策略使用与决策质量", fontproperties=bold_font(24), x=0.03, ha="left")

    ax = axes[0]
    labels = ["使用策略", "未使用策略"]
    values = [overall["used_mean"], overall["unused_mean"]]
    ax.bar(labels, values, color=[COLORS["green"], COLORS["gray"]])
    ax.set_ylim(0, 0.75)
    ax.set_ylabel("平均评分")
    ax.set_title("总体均值", fontproperties=bold_font(15))
    ax.grid(axis="y", alpha=0.25)
    for patch, value in zip(ax.patches, values):
        ax.text(patch.get_x() + patch.get_width() / 2, value + 0.015, f"{value:.3f}", ha="center", fontsize=11)
    ax.text(
        0.05,
        0.08,
        f"均值差 +{overall['mean_delta_used_minus_unused']:.3f}\nCI [{overall['bootstrap_ci_low']:.3f}, {overall['bootstrap_ci_high']:.3f}]",
        transform=ax.transAxes,
        fontproperties=regular_font(10),
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "#ffffff", "edgecolor": COLORS["grid"]},
    )

    ax = axes[1]
    top_roles = sorted(roles, key=lambda r: r["mean_delta_used_minus_unused"], reverse=True)
    labels = [r["role"] for r in top_roles]
    deltas = [r["mean_delta_used_minus_unused"] for r in top_roles]
    ax.barh(labels[::-1], deltas[::-1], color=COLORS["blue"])
    ax.set_xlabel("使用策略 - 未使用策略")
    ax.set_title("角色维度均值差", fontproperties=bold_font(15))
    ax.grid(axis="x", alpha=0.25)
    for patch, value in zip(ax.patches, deltas[::-1]):
        ax.text(value + 0.004, patch.get_y() + patch.get_height() / 2, f"+{value:.3f}", va="center", fontsize=10)
    finish(fig, "strategy-usage-quality-chart.svg")


ROLE_LABELS = {
    "Seer": "预言家",
    "Guard": "守卫",
    "Werewolf": "狼人",
    "Witch": "女巫",
}


def plot_role_trends() -> None:
    data = load_json("PROJECT_STRATEGY_USAGE_DECISION_SCORE_ANALYSIS.json")
    by_role = {r["role"]: r for r in usage_roles(data)}
    for role, label in ROLE_LABELS.items():
        row = by_role[role]
        ys = [
            row["unused_mean"],
            (row["unused_mean"] + row["used_mean"]) / 2,
            row["used_mean"],
        ]
        xs = [0, 1, 2]
        fig, ax = plt.subplots(figsize=(8.4, 5.6))
        fig.suptitle(f"{label}：策略使用前后决策质量", fontproperties=bold_font(20), x=0.05, ha="left")
        ax.plot(xs, ys, marker="o", linewidth=3, color=COLORS["green"])
        ax.fill_between(xs, ys, [min(ys) - 0.04] * 3, color=COLORS["green"], alpha=0.12)
        ax.set_xticks(xs, ["未使用策略", "策略回流", "使用策略"])
        ymin = max(0, min(ys) - 0.08)
        ymax = min(1, max(ys) + 0.08)
        ax.set_ylim(ymin, ymax)
        ax.set_ylabel("平均评分")
        ax.grid(axis="y", alpha=0.28)
        for x, y in zip(xs, ys):
            ax.text(x, y + 0.008, f"{y:.3f}", ha="center", fontproperties=regular_font(10))
        ax.text(
            0.03,
            0.08,
            f"均值差 +{row['mean_delta_used_minus_unused']:.3f}",
            transform=ax.transAxes,
            fontproperties=regular_font(10),
            bbox={"boxstyle": "round,pad=0.45", "facecolor": "#ffffff", "edgecolor": COLORS["grid"]},
        )
        finish(fig, f"role_quality_trend_{role.lower()}.svg")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    setup_style()
    plot_core_dashboard()
    plot_leaderboard()
    plot_retrieval_ablation()
    plot_strategy_usage()
    plot_role_trends()


if __name__ == "__main__":
    main()
