"""V3 Multi-Game Dashboard HTML Renderer.

Reads dashboard_data.json → renders self-contained HTML with 8 modules,
inline CSS, inline JS, embedded matplotlib SVG charts.

Usage:
  python scripts/render_dashboard_html.py [--data data/health/dashboard_data.json]
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class V3DashboardHTMLRenderer:
    def __init__(self, data: dict):
        self.d = data

    def render(self) -> str:
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Werewolf · Scoring Validity Dashboard</title>
  {self._render_css()}
</head>
<body>
  <div class="dashboard">
    <header class="dash-header">
      <h1>AI Werewolf 多局测评有效性看板</h1>
      <p class="subtitle">Scoring Validity Dashboard — Learned Evaluator v1</p>
    </header>
    {self._render_data_scale()}
    {self._render_ablation()}
    {self._render_role_cohens_d()}
    {self._render_role_action_matrix()}
    {self._render_calibration()}
    {self._render_leaderboard()}
    {self._render_valid_agent_summary()}
    {self._render_known_limits()}
  </div>
  {self._render_js()}
</body>
</html>"""

    # ------------------------------------------------------------------
    # Module 1: Data Scale Cards
    # ------------------------------------------------------------------

    def _render_data_scale(self) -> str:
        ds = self.d.get("data_scale", {})
        cards = [
            ("游戏数", ds.get("games", 0)),
            ("玩家记录", ds.get("players", 0)),
            ("决策机会", ds.get("opportunities", 0)),
            ("标注样本", ds.get("labeled_samples", 0)),
            ("发言分析", ds.get("speech_entries", 0)),
            ("反事实", ds.get("counterfactuals", 0)),
            ("角色数", len(ds.get("roles", []))),
            ("机会类型", len(ds.get("opportunity_types", []))),
        ]
        items = "\n".join(
            f'<div class="scard"><div class="scard-value">{val}</div><div class="scard-label">{label}</div></div>'
            for label, val in cards
        )
        return f"""<section class="module">
    <h2>数据规模</h2>
    <div class="scale-cards">{items}</div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 2: Ablation Comparison
    # ------------------------------------------------------------------

    def _render_ablation(self) -> str:
        ab = self.d.get("ablation", {})
        if not ab:
            return '<section class="module"><h2>Ablation 对比</h2><p>暂无数据</p></section>'

        labels = []
        paw_values = []
        witch_d_values = []
        guard_d_values = []
        hunter_d_values = []
        for key, val in ab.items():
            labels.append(val.get("label", key))
            paw_values.append(val.get("pairwise_acc", 0))
            witch_d_values.append(val.get("witch_d", 0))
            guard_d_values.append(val.get("guard_d", 0))
            hunter_d_values.append(val.get("hunter_d", 0))

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np

            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [
                "Noto Sans CJK SC",
                "Noto Serif CJK SC",
                "DejaVu Sans",
            ]

            fig, axes = plt.subplots(1, 2, figsize=(10, 4))

            # Left: Pairwise Accuracy
            x = np.arange(len(labels))
            colors_paw = ["#c4b5a5", "#d8b08d", "#9c5d2c", "#9c5d2c"]
            bars = axes[0].bar(x, paw_values, color=colors_paw, edgecolor="white")
            axes[0].set_ylabel("Pairwise Accuracy", fontsize=9, color="#7a6c62")
            axes[0].set_title("Pairwise Accuracy by Variant", fontsize=10, fontweight="bold")
            axes[0].set_xticks(x)
            axes[0].set_xticklabels(labels, fontsize=7, rotation=15)
            axes[0].set_ylim(0.7, 1.0)
            for bar, val in zip(bars, paw_values):
                axes[0].text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.005,
                    f"{val:.3f}",
                    ha="center",
                    fontsize=7,
                    color="#1f1a17",
                )

            # Right: Cohen's d by role
            x2 = np.arange(3)
            width = 0.2
            variants = ["A", "C", "D"]
            variant_map = {
                "A": "A_old_rule",
                "C": "C_small_model",
                "D": "D_with_embedding",
            }
            for i, (vkey, vname) in enumerate(variants):
                vdata = ab.get(variant_map[vkey], {})
                offset = (i - 1) * width
                axes[1].bar(
                    x2 + offset,
                    [vdata.get("witch_d", 0), vdata.get("guard_d", 0), vdata.get("hunter_d", 0)],
                    width,
                    label=vkey,
                    color=[colors_paw[i + 1]],
                    edgecolor="white",
                )
            axes[1].set_xticks(x2)
            axes[1].set_xticklabels(["Witch", "Guard", "Hunter"], fontsize=8)
            axes[1].set_ylabel("Cohen's d", fontsize=9, color="#7a6c62")
            axes[1].set_title("Cohen's d by Role & Variant", fontsize=10, fontweight="bold")
            axes[1].legend(fontsize=7)
            axes[1].axhline(0.3, color="#e5d3bd", linestyle="--", linewidth=1, label="d=0.3 target")
            axes[1].axhline(0.5, color="#9c5d2c", linestyle="--", linewidth=1, alpha=0.5, label="d=0.5 target")

            for ax in axes:
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.tick_params(labelsize=7, colors="#7a6c62")

            buf = io.BytesIO()
            fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
            plt.close(fig)
            buf.seek(0)
            svg = "\n".join(l for l in buf.read().decode("utf-8").splitlines() if not l.startswith("<?xml"))
            chart = f'<div class="chart-container">{svg}</div>'
        except Exception as e:
            chart = f"<p>Chart error: {self._esc(str(e))}</p>"

        # Table summary
        rows = ""
        for key, val in ab.items():
            retrieval_note = ""
            if val.get("retrieval_gain_paw"):
                retrieval_note = f' <span class="note">(retrieval +{val["retrieval_gain_paw"]:.3f} PaW)</span>'
            rows += f"""<tr>
              <td>{self._esc(val["label"])}</td>
              <td>{val["pairwise_acc"]:.4f}</td>
              <td>{val["witch_d"]:.3f}</td>
              <td>{val["guard_d"]:.3f}</td>
              <td>{val["hunter_d"]:.3f}</td>
              <td>{val.get("overall_d", 0):.3f}</td>
              <td>{retrieval_note}</td>
            </tr>"""

        table = f"""<table class="ab-table">
          <thead><tr><th>Variant</th><th>Pairwise Acc</th><th>Witch d</th><th>Guard d</th><th>Hunter d</th><th>Overall d</th><th>Notes</th></tr></thead>
          <tbody>{rows}</tbody></table>"""

        return f"""<section class="module">
    <h2>Ablation 对比</h2>
    {chart}
    {table}
    </section>"""

    # ------------------------------------------------------------------
    # Module 3: Role-wise Cohen's d
    # ------------------------------------------------------------------

    def _render_role_cohens_d(self) -> str:
        rd = self.d.get("role_cohens_d", {})
        if not rd:
            return '<section class="module"><h2>角色区分度</h2><p>暂无数据</p></section>'

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np

            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [
                "Noto Sans CJK SC",
                "Noto Serif CJK SC",
                "DejaVu Sans",
            ]

            roles = list(rd.keys())
            d_vals = [rd[r]["cohens_d"] for r in roles]
            colors = []
            for r in roles:
                conf = rd[r].get("confidence", "high")
                if conf == "low":
                    colors.append("#9f3f3f")  # red for low confidence
                elif conf == "medium":
                    colors.append("#c4821e")  # yellow for medium
                else:
                    colors.append("#2d7d55")  # green for high

            fig, ax = plt.subplots(figsize=(8, 3.5))
            y_pos = np.arange(len(roles))
            bars = ax.barh(y_pos, d_vals, color=colors, edgecolor="white", height=0.5)

            # Add target lines
            ax.axvline(0.3, color="#e5d3bd", linestyle="--", linewidth=1.5)
            ax.axvline(0.5, color="#9c5d2c", linestyle="--", linewidth=1, alpha=0.5)
            ax.text(0.31, len(roles) - 0.3, "d=0.3", fontsize=7, color="#c4b5a5")
            ax.text(0.51, len(roles) - 0.3, "d=0.5", fontsize=7, color="#9c5d2c")

            for bar, val, role in zip(bars, d_vals, roles):
                gap = rd[role].get("gap", 0)
                note = rd[role].get("note", "")
                ax.text(
                    val + 0.02,
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:.3f} (gap={gap:.1f}) {'⚠' if rd[role].get('confidence') in ('low', 'medium') else ''}",
                    va="center",
                    fontsize=7,
                    color="#1f1a17",
                )
                if note:
                    ax.text(
                        val + 0.02,
                        bar.get_y() + bar.get_height() / 2 - 0.25,
                        note,
                        va="center",
                        fontsize=5.5,
                        color="#7a6c62",
                        style="italic",
                    )

            ax.set_yticks(y_pos)
            ax.set_yticklabels(roles, fontsize=9)
            ax.set_xlabel("Cohen's d", fontsize=9, color="#7a6c62")
            ax.set_title("Role-Wise Cohen's d (Good vs Bad)", fontsize=10, fontweight="bold")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.tick_params(labelsize=8, colors="#7a6c62")
            ax.set_xlim(0, max(d_vals) * 1.4 + 0.1)

            buf = io.BytesIO()
            fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
            plt.close(fig)
            buf.seek(0)
            svg = "\n".join(l for l in buf.read().decode("utf-8").splitlines() if not l.startswith("<?xml"))
            chart = f'<div class="chart-container">{svg}</div>'
        except Exception as e:
            chart = f"<p>Chart error: {self._esc(str(e))}</p>"

        return f"""<section class="module">
    <h2>角色区分度</h2>
    {chart}
    <p class="chart-note">绿色=高置信 · 橙色=中置信(Guard) · 红色=低置信(Hunter) · 虚线=目标阈值</p>
    </section>"""

    # ------------------------------------------------------------------
    # Module 4: Role-Action Matrix
    # ------------------------------------------------------------------

    def _render_role_action_matrix(self) -> str:
        ra = self.d.get("role_action_matrix", {})
        rows = ra.get("rows", [])
        if not rows:
            return '<section class="module"><h2>Role-Action 矩阵</h2><p>暂无数据</p></section>'

        # Build table
        all_roles = {r["role"] for r in rows}
        all_actions = {r["action_type"] for r in rows}

        # Build lookup
        cell_map = {(r["role"], r["action_type"]): r for r in rows}

        header = "<th></th>" + "".join(f"<th>{self._esc(a)}</th>" for a in all_actions)
        tbody = ""
        for role in all_roles:
            cells = f"<td class='ram-role'>{self._esc(role)}</td>"
            for action in all_actions:
                cell = cell_map.get((role, action))
                if cell is None:
                    cells += '<td class="ram-na">—</td>'
                else:
                    _gap = cell["gap"]
                    d = cell["cohens_d"]
                    n = cell["n_samples"]
                    # Color by d
                    if d >= 0.4:
                        cls = "ram-good"
                    elif d >= 0.2:
                        cls = "ram-mid"
                    elif n >= 10:
                        cls = "ram-weak"
                    else:
                        cls = "ram-low-n"

                    title = f"n={n} good={cell['good_mean']:.3f} bad={cell['bad_mean']:.3f} d={d:.3f}"
                    cells += f'<td class="{cls}" title="{self._esc(title)}">{d:.2f}<br><small>n={n}</small></td>'
            tbody += f"<tr>{cells}</tr>"

        return f"""<section class="module">
    <h2>Role-Action 评测矩阵</h2>
    <div class="table-wrap">
    <table class="ram-table">
      <thead><tr>{header}</tr></thead>
      <tbody>{tbody}</tbody>
    </table>
    </div>
    <p class="chart-note">单元格: Cohen's d (上) / 样本量 n (下) · 颜色: 绿=d>=0.4 · 黄=0.2-0.4 · 红=d<0.2</p>
    </section>"""

    # ------------------------------------------------------------------
    # Module 5: Calibration Chart
    # ------------------------------------------------------------------

    def _render_calibration(self) -> str:
        cal = self.d.get("calibration", {})
        bins = cal.get("bins", [])
        if not bins:
            return '<section class="module"><h2>校准曲线</h2><p>暂无数据</p></section>'

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [
                "Noto Sans CJK SC",
                "Noto Serif CJK SC",
                "DejaVu Sans",
            ]

            fig, ax = plt.subplots(figsize=(6, 4))
            x = [b["pred_mean"] for b in bins]
            y = [b["good_rate"] for b in bins]
            sizes = [max(b["n"], 5) * 3 for b in bins]

            ax.plot(x, y, color="#9c5d2c", linewidth=2, marker="o", markersize=8, zorder=3)
            ax.plot([0, 1], [0, 1], color="#e5d3bd", linestyle="--", linewidth=1, zorder=1, label="Perfect calibration")
            ax.scatter(x, y, s=sizes, color="#9c5d2c", alpha=0.3, zorder=2)

            for i, b in enumerate(bins):
                ax.annotate(
                    f"n={b['n']}",
                    (x[i], y[i]),
                    textcoords="offset points",
                    xytext=(8, 4),
                    fontsize=6,
                    color="#7a6c62",
                )

            ax.set_xlabel("Predicted Score (mean)", fontsize=9, color="#7a6c62")
            ax.set_ylabel("Empirical Good Rate", fontsize=9, color="#7a6c62")
            ax.set_title("Calibration: Predicted vs Actual Good Rate", fontsize=10, fontweight="bold")
            ax.legend(fontsize=7)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.tick_params(labelsize=7, colors="#7a6c62")
            ax.set_xlim(0.2, 0.7)
            ax.set_ylim(0, 1)

            buf = io.BytesIO()
            fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
            plt.close(fig)
            buf.seek(0)
            svg = "\n".join(l for l in buf.read().decode("utf-8").splitlines() if not l.startswith("<?xml"))
            chart = f'<div class="chart-container">{svg}</div>'
        except Exception as e:
            chart = f"<p>Chart error: {self._esc(str(e))}</p>"

        return f"""<section class="module">
    <h2>校准曲线</h2>
    {chart}
    </section>"""

    # ------------------------------------------------------------------
    # Module 6: Leaderboard
    # ------------------------------------------------------------------

    def _render_leaderboard(self) -> str:
        lb = self.d.get("leaderboard", {})
        if not lb:
            return '<section class="module"><h2>Leaderboard</h2><p>暂无数据</p></section>'

        # Overall top 10
        top10 = lb.get("_overall_top10", [])
        top_rows = "\n".join(
            f"""<tr>
              <td>{i + 1}</td>
              <td>{self._esc(r["player_id"][:16])}</td>
              <td>{self._esc(r["role"])}</td>
              <td>{self._esc(r.get("game_id", "")[:12])}</td>
              <td class="lb-score">{r["final_score"]:.1f}</td>
              <td class="lb-score">{r["process_score"]:.1f}</td>
              <td>{"W" if r.get("won") else "L"}</td>
            </tr>"""
            for i, r in enumerate(top10)
        )

        # By role
        role_tabs = ""
        role_content = ""
        for i, (role, data) in enumerate(sorted(lb.items(), key=lambda x: x[0] != "_overall_top10")):
            if role.startswith("_"):
                continue
            top3 = data.get("top3", [])
            rows = "\n".join(
                f"""<tr>
                  <td>{j + 1}</td>
                  <td>{self._esc(r["player_id"][:16])}</td>
                  <td>{r["final_score"]:.1f}</td>
                  <td>{r["process_score"]:.1f}</td>
                  <td>{r["role_process_score"]:.1f}</td>
                  <td>{r["speech_score"]:.1f}</td>
                  <td>{r["model_confidence"]:.2f}</td>
                </tr>"""
                for j, r in enumerate(top3)
            )
            active = "active" if i == 0 else ""
            role_tabs += f'<button class="lb-tab {active}" onclick="switchTab(\'{role}\')">{self._esc(role)}</button>'
            role_content += f"""<div class="lb-panel {active}" id="lb-{self._esc(role)}">
            <h4>{self._esc(role)} — Mean Final: {data["mean_final"]:.1f} | Mean Process: {data["mean_process"]:.1f} | Mean Speech: {data["mean_speech"]:.1f}</h4>
            <table class="lb-table">
              <thead><tr><th>#</th><th>Player</th><th>Final</th><th>Process</th><th>RolePro</th><th>Speech</th><th>Conf</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
            </div>"""

        return f"""<section class="module">
    <h2>Leaderboard</h2>
    <div class="lb-tabs">{role_tabs}</div>
    {role_content}
    <h3 style="margin-top:1.5rem">Overall Top 10</h3>
    <table class="lb-table">
      <thead><tr><th>#</th><th>Player</th><th>Role</th><th>Game</th><th>Final</th><th>Process</th><th>Win</th></tr></thead>
      <tbody>{top_rows}</tbody>
    </table>
    </section>"""

    # ------------------------------------------------------------------
    # Module 7: Valid Agent Summary
    # ------------------------------------------------------------------

    def _render_valid_agent_summary(self) -> str:
        vs = self.d.get("valid_agent", {})
        pg = self.d.get("per_game_validation", {})

        issues = vs.get("issues", [])
        issue_rows = "\n".join(
            f"<li><strong>{self._esc(i.get('type', '?'))}:</strong> {self._esc(i.get('detail', ''))}</li>"
            for i in issues
        )

        recs = vs.get("recommendations", [])
        rec_rows = "\n".join(f"<li>{self._esc(r)}</li>" for r in recs)

        return f"""<section class="module">
    <h2>Valid Agent 通过情况</h2>
    <div class="va-summary {"pass" if vs.get("passed") else "fail"}">
      <span class="va-icon">{"✓" if vs.get("passed") else "✗"}</span>
      <span class="va-grade">Grade: {vs.get("grade", "?")}</span>
      <span class="va-score">Score: {vs.get("score", 0):.2f}</span>
      <span class="va-status">publish_allowed: {str(vs.get("publish_allowed", False)).lower()}</span>
    </div>
    <div class="va-details">
      <div class="va-col">
        <h3>Per-Game Stats</h3>
        <table class="va-table">
          <tr><td>Total games validated</td><td>{pg.get("total", 0)}</td></tr>
          <tr><td>Passed</td><td>{pg.get("passed", 0)}</td></tr>
          <tr><td>Grade A</td><td>{pg.get("grade_a", 0)}</td></tr>
          <tr><td>Grade B</td><td>{pg.get("grade_b", 0)}</td></tr>
        </table>
      </div>
      <div class="va-col">
        <h3>Issues</h3>
        <ul>{issue_rows if issues else "<li>No issues</li>"}</ul>
      </div>
      <div class="va-col">
        <h3>Recommendations</h3>
        <ul>{rec_rows if recs else "<li>None</li>"}</ul>
      </div>
    </div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 8: Known Limits (HONEST DISCLOSURE)
    # ------------------------------------------------------------------

    def _render_known_limits(self) -> str:
        limits = self.d.get("known_limits", [])
        if not limits:
            return ""

        cards = ""
        for lim in limits:
            status_class = {
                "LOW CONFIDENCE": "limit-danger",
                "MEDIUM CONFIDENCE": "limit-warn",
                "MARGINAL GAIN": "limit-warn",
                "RULE-BASED": "limit-info",
                "EARLY STAGE": "limit-info",
            }.get(lim.get("status", ""), "limit-info")

            cards += f"""
            <div class="limit-card {status_class}">
              <h3>{self._esc(lim.get("component", "?"))}</h3>
              <div class="limit-status">{self._esc(lim.get("status", "?"))}</div>
              <p class="limit-detail">{self._esc(lim.get("detail", ""))}</p>
              <p class="limit-rec">→ {self._esc(lim.get("recommendation", ""))}</p>
            </div>"""

        return f"""<section class="module">
    <h2>已知局限 (Honest Disclosure)</h2>
    <div class="limit-grid">{cards}</div>
    </section>"""

    # ------------------------------------------------------------------
    # CSS
    # ------------------------------------------------------------------

    def _render_css(self) -> str:
        return """
    <style>
      :root {
        --bg: #f7efe4; --paper: #fffaf3; --ink: #1f1a17; --muted: #7a6c62;
        --line: #e5d3bd; --accent: #9c5d2c; --accent-soft: #d8b08d;
        --danger: #9f3f3f; --success: #2d7d55; --warning: #c4821e;
        --shadow: 0 2px 12px rgba(71,49,26,0.1);
      }
      * { box-sizing:border-box; margin:0; padding:0; }
      body {
        margin:0; font-family:"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif;
        background: radial-gradient(circle at top left, rgba(156,93,44,0.06), transparent 36%),
                    linear-gradient(180deg, #fbf5ec 0%, var(--bg) 100%);
        color: var(--ink); line-height:1.55; padding-bottom:4rem;
      }
      .dashboard { max-width:1100px; margin:0 auto; padding:2rem 1.5rem; }

      .dash-header { margin-bottom:2rem; text-align:center; }
      .dash-header h1 { font-size:1.8rem; color:var(--accent); }
      .subtitle { font-size:0.85rem; color:var(--muted); margin-top:0.3rem; }

      .module { background:var(--paper); border-radius:12px; padding:1.5rem;
        margin-bottom:1.5rem; box-shadow:var(--shadow); border:1px solid var(--line); }
      .module h2 { font-size:1.1rem; color:var(--accent); margin-bottom:1rem;
        padding-bottom:0.5rem; border-bottom:2px solid var(--line); }
      .module h3 { font-size:0.95rem; color:var(--muted); margin:0.8rem 0 0.4rem; }
      .module h4 { font-size:0.8rem; color:var(--muted); margin-bottom:0.4rem; }
      .chart-container { overflow-x:auto; }
      .chart-container svg { max-width:100%; height:auto; }
      .chart-note { font-size:0.7rem; color:var(--muted); margin-top:0.4rem; }
      .note { font-size:0.65rem; color:var(--danger); }

      /* Scale cards */
      .scale-cards { display:flex; flex-wrap:wrap; gap:0.8rem; }
      .scard { flex:1 1 120px; background:var(--bg); border-radius:8px; padding:1rem;
        text-align:center; border:1px solid var(--line); }
      .scard-value { font-size:1.6rem; font-weight:700; color:var(--accent); }
      .scard-label { font-size:0.7rem; color:var(--muted); margin-top:0.2rem; }

      /* Tables */
      .table-wrap { overflow-x:auto; }
      .ab-table, .lb-table, .va-table { width:100%; border-collapse:collapse; font-size:0.8rem; }
      .ab-table th, .lb-table th { background:rgba(156,93,44,0.08); padding:0.4rem 0.5rem;
        text-align:center; font-weight:600; color:var(--muted); font-size:0.7rem; }
      .ab-table td, .lb-table td { padding:0.4rem 0.5rem; text-align:center;
        border-bottom:1px solid var(--line); }
      .lb-score { font-family:monospace; font-weight:600; color:var(--accent); }
      .va-table td { padding:0.3rem 0.5rem; border-bottom:1px solid var(--line); }
      .va-table td:first-child { font-weight:600; color:var(--muted); }

      /* Role-Action Matrix */
      .ram-table { border-collapse:collapse; font-size:0.75rem; }
      .ram-table th { background:rgba(156,93,44,0.08); padding:0.3rem 0.5rem;
        font-size:0.65rem; color:var(--muted); }
      .ram-table td { padding:0.35rem 0.5rem; text-align:center; border:1px solid var(--line); }
      .ram-role { font-weight:600; color:var(--accent); text-align:left !important; }
      .ram-good { background:rgba(45,125,85,0.12); }
      .ram-mid { background:rgba(196,130,30,0.08); }
      .ram-weak { background:rgba(159,63,63,0.06); }
      .ram-low-n { background:rgba(156,93,44,0.04); color:var(--muted); }
      .ram-na { color:var(--muted); font-style:italic; }

      /* Leaderboard tabs */
      .lb-tabs { display:flex; gap:0.3rem; margin-bottom:0.8rem; flex-wrap:wrap; }
      .lb-tab { padding:0.35rem 0.8rem; border:1px solid var(--line); background:var(--bg);
        border-radius:6px; cursor:pointer; font-size:0.75rem; color:var(--muted); }
      .lb-tab.active { background:var(--accent); color:#fff; border-color:var(--accent); }
      .lb-panel { display:none; }
      .lb-panel.active { display:block; }

      /* Valid Agent */
      .va-summary { display:flex; gap:1rem; align-items:center; padding:0.8rem 1rem;
        border-radius:8px; font-size:0.9rem; margin-bottom:1rem; }
      .va-summary.pass { background:rgba(45,125,85,0.08); }
      .va-summary.fail { background:rgba(159,63,63,0.08); }
      .va-icon { font-size:1.5rem; }
      .va-grade { font-weight:700; }
      .va-score { font-family:monospace; }
      .va-status { font-family:monospace; font-size:0.8rem; color:var(--muted); }
      .va-details { display:flex; gap:1.5rem; flex-wrap:wrap; }
      .va-col { flex:1 1 250px; font-size:0.8rem; }
      .va-col ul { padding-left:1.2rem; }
      .va-col li { margin-bottom:0.2rem; }

      /* Known Limits */
      .limit-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:1rem; }
      .limit-card { border-radius:10px; padding:1rem; border:1px solid var(--line); }
      .limit-card.limit-danger { border-left:4px solid var(--danger); background:rgba(159,63,63,0.04); }
      .limit-card.limit-warn { border-left:4px solid var(--warning); background:rgba(196,130,30,0.04); }
      .limit-card.limit-info { border-left:4px solid var(--accent-soft); background:rgba(156,93,44,0.03); }
      .limit-card h3 { margin:0 0 0.3rem; font-size:0.9rem; }
      .limit-status { font-size:0.7rem; font-weight:700; padding:0.15rem 0.5rem;
        display:inline-block; border-radius:4px; margin-bottom:0.4rem; }
      .limit-danger .limit-status { background:rgba(159,63,63,0.15); color:var(--danger); }
      .limit-warn .limit-status { background:rgba(196,130,30,0.15); color:var(--warning); }
      .limit-info .limit-status { background:rgba(156,93,44,0.1); color:var(--accent); }
      .limit-detail { font-size:0.78rem; color:var(--ink); line-height:1.5; margin-bottom:0.3rem; }
      .limit-rec { font-size:0.75rem; color:var(--muted); font-style:italic; }

      @media (max-width:768px) {
        .dashboard { padding:1rem 0.5rem; }
        .va-details { flex-direction:column; }
        .limit-grid { grid-template-columns:1fr; }
      }
    </style>"""

    # ------------------------------------------------------------------
    # JS
    # ------------------------------------------------------------------

    def _render_js(self) -> str:
        return """
    <script>
    function switchTab(role) {
      document.querySelectorAll('.lb-tab').forEach(function(btn) {
        btn.classList.remove('active');
        if (btn.textContent === role) btn.classList.add('active');
      });
      document.querySelectorAll('.lb-panel').forEach(function(panel) {
        panel.classList.remove('active');
      });
      var target = document.getElementById('lb-' + role);
      if (target) target.classList.add('active');
    }
    </script>"""

    @staticmethod
    def _esc(s: str) -> str:
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/health/dashboard_data.json", help="Dashboard JSON path")
    ap.add_argument("--output", default="data/health/scoring_validity_dashboard.html", help="Output HTML")
    args = ap.parse_args()

    data_path = ROOT / args.data
    if not data_path.exists():
        print(f"Dashboard data not found: {data_path}")
        return 1

    print(f"Loading {data_path}...")
    data = load_json(data_path)

    renderer = V3DashboardHTMLRenderer(data)
    html = renderer.render()

    out_path = ROOT / args.output
    out_path.write_text(html, encoding="utf-8")
    print(f"Dashboard → {out_path} ({out_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
