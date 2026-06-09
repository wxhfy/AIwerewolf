"""V3 Single-Game HTML Renderer.

Reads single_game_data_<game_id>.json → renders self-contained HTML
with 12 modules, inline CSS, inline JS, embedded matplotlib SVG charts.

Usage:
  python scripts/render_single_game_html.py --game-id <id>
  python scripts/render_single_game_html.py --all
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


class V3SingleGameHTMLRenderer:
    def __init__(self, data: dict):
        self.d = data

    def render(self) -> str:
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Werewolf Review · {self._esc(self.d["game_id"][:8])}</title>
  {self._render_css()}
</head>
<body>
  <div class="report">
    {self._render_header_overview()}
    {self._render_camp_advantage()}
    {self._render_timeline()}
    {self._render_scoreboard()}
    {self._render_suspicion_heatmap()}
    {self._render_vote_flow()}
    {self._render_good_opportunities()}
    {self._render_bad_opportunities()}
    {self._render_counterfactual_panel()}
    {self._render_player_cards()}
    {self._render_valid_agent_panel()}
  </div>
  {self._render_evidence_drawer()}
  {self._render_js()}
</body>
</html>"""

    # ------------------------------------------------------------------
    # Module 1: Header Overview
    # ------------------------------------------------------------------

    def _render_header_overview(self) -> str:
        d = self.d
        drama = d.get("drama_score", {})
        winner = d.get("winner", "unknown")
        winner_label = "好人阵营" if winner == "village" else "狼人阵营" if winner == "wolf" else winner
        winner_class = "win-good" if winner == "village" else "win-wolf"

        return f"""
    <header class="report-header">
      <div class="header-top">
        <h1>AI 狼人杀复盘报告</h1>
        <span class="game-id">Game: {self._esc(d["game_id"][:12])}</span>
      </div>
      <div class="metric-cards">
        <div class="mcard {winner_class}">
          <div class="mcard-label">获胜</div>
          <div class="mcard-value">{winner_label}</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">MVP</div>
          <div class="mcard-value">{self._esc(d["mvp"]["player_id"]) if d.get("mvp") else "—"} / {self._esc(d["mvp"]["role"]) if d.get("mvp") else "—"}</div>
          <div class="mcard-sub">{d["mvp"]["final_score"]:.1f}分</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">精彩指数</div>
          <div class="mcard-value">{drama.get("score", "—")} / 100</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">总天数</div>
          <div class="mcard-value">{d.get("total_days", "—")} 天</div>
        </div>
        <div class="mcard">
          <div class="mcard-label">Valid Agent</div>
          <div class="mcard-value grade grade-{d.get("valid_grade", "B").lower()}">Grade {d.get("valid_grade", "—")}</div>
        </div>
      </div>
      {self._render_drama_moments(drama)}
    </header>"""

    def _render_drama_moments(self, drama: dict) -> str:
        moments = drama.get("top_moments", [])
        if not moments:
            return ""
        items = "\n".join(
            f"<li>D{m['day']} {m['phase']}: {self._esc(m['label'])} — CampAdvantage swing {m['delta']:+.3f}</li>"
            for m in moments[:3]
        )
        return f"""
      <div class="drama-moments">
        <strong>看点：</strong>
        <ul>{items}</ul>
      </div>"""

    # ------------------------------------------------------------------
    # Module 2: Camp Advantage Curve
    # ------------------------------------------------------------------

    def _render_camp_advantage(self) -> str:
        points = self.d.get("camp_advantage", [])
        if not points:
            return '<section class="module"><h2>阵营走势</h2><p>暂无数据</p></section>'

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            # Try to use Chinese font
            # Use Noto Sans CJK SC for Chinese glyph support
            plt.rcParams["font.family"] = "sans-serif"
            plt.rcParams["font.sans-serif"] = [
                "Noto Sans CJK SC",
                "Noto Serif CJK SC",
                "DejaVu Sans",
            ]

            fig, ax = plt.subplots(figsize=(10, 3.5))
            x = [p["seq"] for p in points]
            y = [p["advantage"] for p in points]

            ax.plot(x, y, color="#9c5d2c", linewidth=2, zorder=2)
            ax.fill_between(
                x,
                y,
                0,
                alpha=0.08,
                color="#9c5d2c",
                where=[v >= 0 for v in y],
            )
            ax.fill_between(
                x,
                y,
                0,
                alpha=0.05,
                color="#9f3f3f",
                where=[v < 0 for v in y],
            )
            ax.axhline(0, color="#e5d3bd", linewidth=1, zorder=1)

            # Annotate key events (top 5 by |delta|)
            key = sorted(points, key=lambda p: abs(p["delta"]), reverse=True)[:5]
            for p in key:
                ax.annotate(
                    f"D{p['day']} {p['label']}",
                    (p["seq"], p["advantage"]),
                    textcoords="offset points",
                    xytext=(0, 12 if p["advantage"] >= 0 else -18),
                    fontsize=7,
                    ha="center",
                    color="#7a6c62",
                    arrowprops={
                        "arrowstyle": "->",
                        "color": "#d8b08d",
                        "lw": 0.8,
                    },
                )

            ax.set_xlabel("Event Sequence", fontsize=8, color="#7a6c62")
            ax.set_ylabel("Camp Advantage", fontsize=8, color="#7a6c62")
            ax.set_title(
                "Camp Advantage Curve — 好人优势 / 狼人优势",
                fontsize=10,
                color="#1f1a17",
                fontweight="bold",
            )
            ax.tick_params(labelsize=7, colors="#7a6c62")
            ax.set_ylim(-1.1, 1.1)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

            buf = io.BytesIO()
            fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
            plt.close(fig)
            buf.seek(0)
            svg = buf.read().decode("utf-8")
            # Strip XML declaration
            svg = "\n".join(l for l in svg.splitlines() if not l.startswith("<?xml"))
            return f'<section class="module"><h2>阵营走势</h2><div class="chart-container">{svg}</div></section>'
        except Exception as e:
            return f'<section class="module"><h2>阵营走势</h2><p>Chart render error: {self._esc(str(e))}</p></section>'

    # ------------------------------------------------------------------
    # Module 3: Interactive Timeline
    # ------------------------------------------------------------------

    def _render_timeline(self) -> str:
        events = self.d.get("events", [])
        if not events:
            return '<section class="module"><h2>对局时间线</h2><p>暂无数据</p></section>'

        # Group events by day/night phase
        public_events = [e for e in events if e.get("visibility") == "public"]
        groups: list[tuple[str, str, list[dict]]] = []
        current_label = ""
        current_key = ""
        current_group: list[dict] = []

        for e in public_events:
            day = e.get("day", 0)
            phase = str(e.get("phase", ""))
            key = f"D{day}-{phase}"
            if "NIGHT" in phase:
                label = f"Night {day}"
            elif "DAY" in phase:
                label = f"Day {day}"
            else:
                label = key

            if key != current_key:
                if current_group:
                    groups.append((current_key, current_label, current_group))
                current_key = key
                current_label = label
                current_group = [e]
            else:
                current_group.append(e)

        if current_group:
            groups.append((current_key, current_label, current_group))

        sections = ""
        for _key, label, group in groups:
            cards = ""
            for e in group:
                etype = e.get("event_type", "")
                payload = e.get("payload", {})
                actor = payload.get("actor_name", payload.get("voter_name", ""))
                target = payload.get("target_name", payload.get("player_name", ""))
                speech = payload.get("speech", payload.get("message", ""))
                action = payload.get("action_type", "")
                reason = payload.get("reasoning", payload.get("reason", ""))

                # Color class
                color_class = {
                    "CHAT_MESSAGE": "tl-blue",
                    "VOTE_CAST": "tl-green",
                    "PLAYER_DIED": "tl-red",
                    "HUNTER_SHOT": "tl-orange",
                    "GAME_START": "tl-gray",
                    "GAME_END": "tl-gray",
                }.get(etype, "tl-gray")

                detail_parts = []
                if actor:
                    detail_parts.append(f"<strong>{self._esc(str(actor))}</strong>")
                if action:
                    detail_parts.append(f"[{self._esc(str(action))}]")
                if target:
                    detail_parts.append(f"→ {self._esc(str(target))}")
                if speech:
                    detail_parts.append(f'<span class="tl-speech">{self._esc(str(speech)[:120])}</span>')
                if reason:
                    detail_parts.append(f'<span class="tl-reason">{self._esc(str(reason)[:100])}</span>')
                detail = " · ".join(detail_parts) or self._esc(etype)

                cards += f"""
                <div class="tl-card {color_class}">
                  <span class="tl-type">{self._esc(str(etype))}</span>
                  <span class="tl-detail">{detail}</span>
                </div>"""

            sections += f"""
            <div class="tl-group">
              <div class="tl-group-header">{self._esc(label)}</div>
              {cards}
            </div>"""

        return f"""<section class="module">
    <h2>对局时间线</h2>
    <div class="timeline">{sections}</div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 4: Scoreboard
    # ------------------------------------------------------------------

    def _render_scoreboard(self) -> str:
        sb = self.d.get("scoreboard", [])
        if not sb:
            return '<section class="module"><h2>玩家评分榜</h2><p>暂无数据</p></section>'

        rows = ""
        for i, p in enumerate(sb):
            rank = i + 1
            conf = p.get("model_confidence", 0.5)
            conf_warn = ""
            if conf <= 0.5:
                conf_warn = " ⚠ LOW"
            elif conf <= 0.65:
                conf_warn = " (medium)"

            rows += f"""
            <tr class="{"sb-won" if p.get("won") else "sb-lost"}">
              <td class="sb-rank">#{rank}</td>
              <td class="sb-player">{self._esc(p.get("player_id", "?"))}</td>
              <td class="sb-role">{self._esc(p.get("role", "?"))}</td>
              <td class="sb-score sb-final">{p["final_score"]:.1f}</td>
              <td class="sb-score">{p["process_score"]:.1f}</td>
              <td class="sb-score">{p["role_process_score"]:.1f}</td>
              <td class="sb-score">{p["speech_score"]:.1f}</td>
              <td class="sb-score">{p["counterfactual_impact"]:+.3f}</td>
              <td class="sb-score">{p["mistake_penalty"]:.3f}</td>
              <td class="sb-conf">{conf:.2f}{conf_warn}</td>
            </tr>"""

        return f"""<section class="module">
    <h2>玩家评分榜</h2>
    <div class="table-wrap">
    <table class="sb-table">
      <thead>
        <tr>
          <th>#</th><th>Player</th><th>Role</th>
          <th>Final</th><th>Process</th><th>RolePro</th>
          <th>Speech</th><th>CF Impact</th><th>Penalty</th>
          <th>Conf</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 5: Suspicion Heatmap
    # ------------------------------------------------------------------

    def _render_suspicion_heatmap(self) -> str:
        snaps = self.d.get("suspicion_snapshots", [])
        if not snaps:
            return '<section class="module"><h2>怀疑度热力图</h2><p>暂无数据</p></section>'

        player_ids = list(snaps[0].get("target_scores", {}).keys())
        # Sample snapshots to not overflow (max 30 columns)
        step = max(1, len(snaps) // 25)
        sampled = snaps[::step]
        if len(sampled) > 30:
            sampled = sampled[:30]

        header = "".join(
            f"<th>{self._esc(str(s.get('day', 0)))}/{self._esc(str(s.get('phase', ''))[:4])}</th>" for s in sampled
        )

        rows = ""
        for pid in player_ids:
            cells = ""
            for s in sampled:
                score = s.get("target_scores", {}).get(pid, 0.5)
                # Color: red=high suspicion, green=low suspicion
                r = int(score * 220 + 35)
                g = int((1 - score) * 180 + 45)
                b = int((1 - abs(score - 0.5) * 2) * 80 + 30)
                color = f"rgb({r},{g},{b})"
                cells += f'<td style="background:{color}" title="{score:.3f}">{score:.2f}</td>'

            name = self._esc(str(pid[:8]))
            rows += f"<tr><td class='hm-name'>{name}</td>{cells}</tr>"

        return f"""<section class="module">
    <h2>怀疑度热力图</h2>
    <div class="table-wrap">
    <table class="heatmap">
      <thead><tr><th></th>{header}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    </div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 6: Vote Flow
    # ------------------------------------------------------------------

    def _render_vote_flow(self) -> str:
        vf = self.d.get("vote_flows", {})
        if not vf:
            return '<section class="module"><h2>投票流向</h2><p>暂无数据</p></section>'

        panels = ""
        for day_str, votes in vf.items():
            votes_list = votes if isinstance(votes, list) else []
            rows = ""
            for v in votes_list:
                pivot_mark = " 🔑 PIVOT" if v.get("is_pivot") else ""
                impact = v.get("impact", 0)
                impact_mark = f" (impact: {impact:.1f})" if impact > 0.3 else ""
                rows += f"""
                <tr>
                  <td>{self._esc(v.get("voter_name", v.get("voter_id", "?")))}</td>
                  <td>→</td>
                  <td class="{"pivot" if v.get("is_pivot") else ""}">{self._esc(v.get("target_name", v.get("target_id", "?")))}{pivot_mark}{impact_mark}</td>
                </tr>"""

            panels += f"""
            <div class="vote-panel">
              <h3>Day {day_str}</h3>
              <table class="vote-table">
                {rows}
              </table>
            </div>"""

        return f"""<section class="module">
    <h2>投票流向</h2>
    <div class="vote-flow">{panels}</div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 7: Top Good Opportunities
    # ------------------------------------------------------------------

    def _render_good_opportunities(self) -> str:
        opps = self.d.get("top_good_opportunities", [])
        if not opps:
            return '<section class="module"><h2>关键操作高光</h2><p>暂无数据</p></section>'

        cards = ""
        for i, o in enumerate(opps):
            cards += f"""
            <div class="opp-card good">
              <div class="opp-rank">#{i + 1}</div>
              <div class="opp-body">
                <div class="opp-header">
                  <strong>{self._esc(o["player_id"])}</strong>
                  <span class="role-tag">{self._esc(o["role"])}</span>
                  <span class="type-tag">{self._esc(o["type"])}</span>
                  <span class="day-tag">Day {o.get("day", "?")}</span>
                </div>
                <div class="opp-score">Score: {o["score"]:.3f}</div>
              </div>
            </div>"""

        return f"""<section class="module">
    <h2>关键操作高光</h2>
    <div class="opp-grid">{cards}</div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 8: Top Bad Opportunities
    # ------------------------------------------------------------------

    def _render_bad_opportunities(self) -> str:
        opps = self.d.get("top_bad_opportunities", [])
        if not opps:
            return '<section class="module"><h2>关键失误</h2><p>暂无数据</p></section>'

        cards = ""
        for i, o in enumerate(opps):
            cards += f"""
            <div class="opp-card bad">
              <div class="opp-rank">#{i + 1}</div>
              <div class="opp-body">
                <div class="opp-header">
                  <strong>{self._esc(o["player_id"])}</strong>
                  <span class="role-tag">{self._esc(o["role"])}</span>
                  <span class="type-tag">{self._esc(o["type"])}</span>
                  <span class="day-tag">Day {o.get("day", "?")}</span>
                </div>
                <div class="opp-score">Score: {o["score"]:.3f}</div>
              </div>
            </div>"""

        return f"""<section class="module">
    <h2>关键失误</h2>
    <div class="opp-grid">{cards}</div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 9: Counterfactual Panel
    # ------------------------------------------------------------------

    def _render_counterfactual_panel(self) -> str:
        cfs = self.d.get("counterfactuals", [])
        if not cfs:
            return '<section class="module"><h2>反事实推演</h2><p>暂无数据</p></section>'

        vote_flips = [c for c in cfs if c.get("type") == "vote_flip"]
        skill_swaps = [c for c in cfs if c.get("type") == "skill_swap"]

        def render_cf_group(title: str, items: list) -> str:
            if not items:
                return f"<h3>{title}</h3><p>暂无</p>"
            rows = "\n".join(
                f"""<tr>
                  <td>{self._esc(c.get("player_id", "?"))}</td>
                  <td>{self._esc(c.get("role", "?"))}</td>
                  <td>{self._esc(str(c.get("original_target", "?")))}</td>
                  <td>→ {self._esc(str(c.get("alternative_target", "?")))}</td>
                  <td>{c.get("impact_value", 0):+.3f}</td>
                  <td>{c.get("confidence", 0):.2f}</td>
                </tr>"""
                for c in items[:10]
            )
            return f"<h3>{title}</h3><table class='cf-table'><thead><tr><th>Player</th><th>Role</th><th>Original</th><th>Alternative</th><th>Impact</th><th>Conf</th></tr></thead><tbody>{rows}</tbody></table>"

        return f"""<section class="module">
    <h2>反事实推演</h2>
    {render_cf_group("Vote Flip", vote_flips)}
    {render_cf_group("Skill Swap", skill_swaps)}
    </section>"""

    # ------------------------------------------------------------------
    # Module 10: Player Cards
    # ------------------------------------------------------------------

    def _render_player_cards(self) -> str:
        cards = self.d.get("player_cards", [])
        if not cards:
            return '<section class="module"><h2>玩家卡片</h2><p>暂无数据</p></section>'

        html = ""
        for pc in cards:
            radar = pc.get("radar", {})
            radar_svg = self._render_radar_svg(radar)

            good_actions = "\n".join(
                f'<li class="pa-good">{self._esc(a["type"])} D{a.get("day", "?")} — {a["score"]:.3f}</li>'
                for a in pc.get("top3_good", [])[:3]
            )
            bad_actions = "\n".join(
                f'<li class="pa-bad">{self._esc(a["type"])} D{a.get("day", "?")} — {a["score"]:.3f}</li>'
                for a in pc.get("top3_bad", [])[:3]
            )
            advice = "\n".join(f"<li>{self._esc(a)}</li>" for a in pc.get("advice", [])[:3])

            conf = pc.get("model_confidence", 0.5)
            conf_class = "conf-low" if conf <= 0.5 else "conf-mid" if conf <= 0.65 else "conf-high"

            html += f"""
            <div class="player-card">
              <div class="pc-header">
                <h3>{self._esc(pc.get("name", pc.get("player_id", "?")))}</h3>
                <span class="pc-role">{self._esc(pc.get("role", "?"))}</span>
                <span class="pc-alignment {"align-good" if pc.get("alignment") == "village" else "align-wolf"}">{self._esc(pc.get("alignment", "?"))}</span>
              </div>
              <div class="pc-body">
                <div class="pc-radar">{radar_svg}</div>
                <div class="pc-stats">
                  <div class="pc-score"><span>Final</span><strong>{pc.get("final_score", 0):.1f}</strong></div>
                  <div class="pc-score"><span>Process</span><strong>{pc.get("process_score", 0):.1f}</strong></div>
                  <div class="pc-score"><span>Speech</span><strong>{pc.get("speech_score", 0):.1f}</strong></div>
                  <div class="pc-score"><span>CF Impact</span><strong>{pc.get("counterfactual_impact", 0):+.3f}</strong></div>
                  <div class="pc-score"><span>Confidence</span><strong class="{conf_class}">{conf:.2f}</strong></div>
                </div>
              </div>
              <div class="pc-actions">
                <div class="pc-good"><strong>Top Good:</strong><ul>{good_actions}</ul></div>
                <div class="pc-bad"><strong>Top Bad:</strong><ul>{bad_actions}</ul></div>
              </div>
              {f'<div class="pc-advice"><strong>建议：</strong><ul>{advice}</ul></div>' if pc.get("advice") else ""}
            </div>"""

        return f"""<section class="module">
    <h2>玩家卡片</h2>
    <div class="player-cards-grid">{html}</div>
    </section>"""

    def _render_radar_svg(self, radar: dict) -> str:
        dims = ["role_task", "speech", "vote", "skill", "counterfactual", "robustness"]
        labels = ["角色任务", "发言", "投票", "技能", "反事实", "鲁棒性"]
        values = [radar.get(d, 50) for d in dims]

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np

            n = len(dims)
            angles = [i * 2 * np.pi / n for i in range(n)]
            values_plot = values + [values[0]]
            angles_plot = angles + [angles[0]]

            fig, ax = plt.subplots(figsize=(2.5, 2.5), subplot_kw={"polar": True})
            ax.set_theta_offset(np.pi / 2)
            ax.set_theta_direction(-1)

            ax.fill(angles_plot, values_plot, alpha=0.15, color="#9c5d2c")
            ax.plot(angles_plot, values_plot, color="#9c5d2c", linewidth=1.5)
            ax.set_xticks(angles)
            ax.set_xticklabels(labels, fontsize=5, color="#7a6c62")
            ax.set_ylim(0, 100)
            ax.set_yticks([25, 50, 75])
            ax.set_yticklabels(["25", "50", "75"], fontsize=4, color="#c4b5a5")
            ax.spines["polar"].set_visible(False)

            buf = io.BytesIO()
            fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True, dpi=72)
            plt.close(fig)
            buf.seek(0)
            return buf.read().decode("utf-8")
        except Exception:
            return "<svg width='200' height='200'><text x='10' y='100'>Radar unavailable</text></svg>"

    # ------------------------------------------------------------------
    # Module 11: Valid Agent Panel
    # ------------------------------------------------------------------

    def _render_valid_agent_panel(self) -> str:
        v = self.d.get("validation", {})
        passed = v.get("passed", False)
        grade = v.get("grade", "B")
        issues = v.get("issues", [])

        issue_rows = ""
        for iss in issues:
            issue_rows += f"""
            <tr>
              <td>{self._esc(iss.get("type", "?"))}</td>
              <td>{self._esc(iss.get("player_id", "—"))}</td>
              <td>{self._esc(iss.get("detail", ""))}</td>
            </tr>"""

        status_icon = "✓" if passed else "✗"
        status_class = "pass" if passed else "fail"

        return f"""<section class="module">
    <h2>Valid Agent 校验</h2>
    <div class="valid-agent">
      <div class="va-summary {status_class}">
        <span class="va-icon">{status_icon}</span>
        <span class="va-grade">Grade: {grade}</span>
        <span class="va-status">publish_allowed: {str(v.get("publish_allowed", passed)).lower()}</span>
      </div>
      {f'<h3>Issues ({len(issues)})</h3><table class="va-table"><thead><tr><th>Type</th><th>Player</th><th>Detail</th></tr></thead><tbody>{issue_rows}</tbody></table>' if issues else "<p>No issues found.</p>"}
    </div>
    </section>"""

    # ------------------------------------------------------------------
    # Module 12: Evidence Drawer (rendered as hidden overlay, toggled by JS)
    # ------------------------------------------------------------------

    def _render_evidence_drawer(self) -> str:
        ev = self.d.get("evidence_map", {})
        if not ev:
            return ""

        items = ""
        for eid, event in list(ev.items())[:50]:
            payload_str = json.dumps(event.get("payload", {}), ensure_ascii=False)
            items += f"""
            <div class="ev-item" id="ev-{self._esc(eid)}">
              <h4>{self._esc(event.get("event_type", "?"))} — D{event.get("day", "?")} {self._esc(str(event.get("phase", "")))}</h4>
              <pre>{self._esc(payload_str[:500])}</pre>
            </div>"""

        return f"""
    <div class="evidence-drawer" id="evidence-drawer">
      <div class="ev-overlay">
        <div class="ev-content">
          <span class="ev-close" onclick="closeEvidence()">✕</span>
          <h3>原始证据</h3>
          <div class="ev-list">{items}</div>
        </div>
      </div>
    </div>"""

    # ------------------------------------------------------------------
    # CSS (inline)
    # ------------------------------------------------------------------

    def _render_css(self) -> str:
        return """
    <style>
      :root {
        --bg: #f7efe4;
        --paper: #fffaf3;
        --ink: #1f1a17;
        --muted: #7a6c62;
        --line: #e5d3bd;
        --accent: #9c5d2c;
        --accent-soft: #d8b08d;
        --danger: #9f3f3f;
        --success: #2d7d55;
        --warning: #c4821e;
        --shadow: 0 2px 12px rgba(71,49,26,0.1);
      }
      * { box-sizing:border-box; margin:0; padding:0; }
      body {
        margin:0; font-family:"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif;
        background: radial-gradient(circle at top left, rgba(156,93,44,0.06), transparent 36%),
                    linear-gradient(180deg, #fbf5ec 0%, var(--bg) 100%);
        color: var(--ink); line-height:1.55; padding-bottom:4rem;
      }
      .report { max-width:1100px; margin:0 auto; padding:2rem 1.5rem; }

      /* Header */
      .report-header { margin-bottom:2rem; }
      .header-top { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:1.5rem; }
      .header-top h1 { font-size:1.8rem; color: var(--accent); }
      .game-id { font-size:0.8rem; color: var(--muted); font-family:monospace; }

      /* Metric Cards */
      .metric-cards { display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:1rem; }
      .mcard {
        flex:1 1 140px; background: var(--paper); border-radius:10px;
        padding:1rem; text-align:center; box-shadow:var(--shadow);
        border:1px solid var(--line);
      }
      .mcard-label { font-size:0.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; }
      .mcard-value { font-size:1.2rem; font-weight:700; margin:0.25rem 0; }
      .mcard-sub { font-size:0.75rem; color:var(--muted); }
      .win-good .mcard-value { color: var(--success); }
      .win-wolf .mcard-value { color: var(--danger); }
      .grade-a { color: var(--success); }
      .grade-b { color: var(--warning); }

      .drama-moments { background:var(--paper); border-radius:8px; padding:0.8rem 1.2rem;
        border-left:3px solid var(--accent); font-size:0.85rem; margin-top:0.5rem; }
      .drama-moments ul { margin:0.3rem 0 0 1.2rem; }

      /* Modules */
      .module { background:var(--paper); border-radius:12px; padding:1.5rem;
        margin-bottom:1.5rem; box-shadow:var(--shadow); border:1px solid var(--line); }
      .module h2 { font-size:1.1rem; color:var(--accent); margin-bottom:1rem;
        padding-bottom:0.5rem; border-bottom:2px solid var(--line); }
      .module h3 { font-size:0.95rem; color:var(--muted); margin:0.8rem 0 0.4rem; }
      .chart-container { overflow-x:auto; }
      .chart-container svg { max-width:100%; height:auto; }

      /* Timeline */
      .timeline { display:flex; flex-direction:column; gap:0.5rem; }
      .tl-group { margin-bottom:0.8rem; }
      .tl-group-header { font-weight:700; font-size:0.85rem; color:var(--accent);
        padding:0.3rem 0.6rem; background:rgba(156,93,44,0.06); border-radius:4px; margin-bottom:0.3rem; }
      .tl-card { display:flex; gap:0.5rem; padding:0.35rem 0.6rem; font-size:0.8rem;
        border-left:3px solid var(--line); margin-bottom:0.15rem; }
      .tl-card.tl-blue { border-left-color:#4a90c4; }
      .tl-card.tl-green { border-left-color:var(--success); }
      .tl-card.tl-red { border-left-color:var(--danger); }
      .tl-card.tl-orange { border-left-color:#e08a2e; }
      .tl-card.tl-gray { border-left-color:#b0a090; }
      .tl-type { font-weight:600; min-width:90px; color:var(--muted); font-size:0.7rem; }
      .tl-speech { color:var(--muted); font-style:italic; }
      .tl-reason { color:var(--accent-soft); font-size:0.7rem; }

      /* Scoreboard */
      .sb-table { width:100%; border-collapse:collapse; font-size:0.8rem; }
      .sb-table th { background:rgba(156,93,44,0.08); padding:0.45rem 0.4rem;
        text-align:center; font-weight:600; color:var(--muted); font-size:0.7rem; }
      .sb-table td { padding:0.4rem; text-align:center; border-bottom:1px solid var(--line); }
      .sb-rank { font-weight:700; color:var(--accent); }
      .sb-player { text-align:left !important; font-family:monospace; }
      .sb-role { text-align:left !important; font-size:0.75rem; }
      .sb-score { font-family:monospace; font-size:0.78rem; }
      .sb-final { font-weight:700; color:var(--accent); }
      .sb-conf { font-size:0.7rem; }
      .sb-won { background:rgba(45,125,85,0.04); }
      .sb-lost { background:rgba(159,63,63,0.03); }

      /* Heatmap */
      .heatmap { border-collapse:collapse; font-size:0.65rem; }
      .heatmap th { font-size:0.55rem; color:var(--muted); padding:0.2rem 0.3rem; writing-mode:vertical-rl; }
      .heatmap td { padding:0.3rem 0.4rem; text-align:center; font-family:monospace; }
      .hm-name { font-weight:600; text-align:left !important; font-size:0.7rem; }

      /* Vote Flow */
      .vote-flow { display:flex; flex-wrap:wrap; gap:1rem; }
      .vote-panel { flex:1 1 200px; }
      .vote-table { width:100%; font-size:0.8rem; border-collapse:collapse; }
      .vote-table td { padding:0.2rem 0.3rem; border-bottom:1px solid var(--line); }
      .vote-table .pivot { color:var(--danger); font-weight:600; }

      /* Opportunity Cards */
      .opp-grid { display:flex; flex-direction:column; gap:0.5rem; }
      .opp-card { display:flex; gap:0.8rem; padding:0.6rem 0.8rem; border-radius:8px; align-items:center; }
      .opp-card.good { background:rgba(45,125,85,0.06); border:1px solid rgba(45,125,85,0.2); }
      .opp-card.bad { background:rgba(159,63,63,0.06); border:1px solid rgba(159,63,63,0.2); }
      .opp-rank { font-size:1.5rem; font-weight:700; color:var(--accent); min-width:2rem; text-align:center; }
      .opp-header { display:flex; gap:0.4rem; align-items:center; flex-wrap:wrap; }
      .role-tag { font-size:0.7rem; background:var(--accent-soft); color:#fff; padding:0.1rem 0.4rem; border-radius:4px; }
      .type-tag { font-size:0.7rem; background:rgba(156,93,44,0.12); color:var(--accent); padding:0.1rem 0.4rem; border-radius:4px; }
      .day-tag { font-size:0.7rem; color:var(--muted); }
      .opp-score { font-size:0.85rem; font-family:monospace; color:var(--accent); margin-top:0.15rem; }

      /* Player Cards */
      .player-cards-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:1rem; }
      .player-card { background:var(--bg); border-radius:10px; padding:1rem; border:1px solid var(--line); }
      .pc-header { display:flex; gap:0.5rem; align-items:baseline; margin-bottom:0.5rem; }
      .pc-header h3 { margin:0; font-size:1rem; }
      .pc-role { font-size:0.75rem; color:var(--accent); font-weight:600; }
      .pc-alignment { font-size:0.7rem; padding:0.1rem 0.4rem; border-radius:3px; }
      .align-good { background:rgba(45,125,85,0.15); color:var(--success); }
      .align-wolf { background:rgba(159,63,63,0.15); color:var(--danger); }
      .pc-body { display:flex; gap:1rem; align-items:center; }
      .pc-radar { flex:0 0 130px; }
      .pc-radar svg { width:130px; height:130px; }
      .pc-stats { display:flex; flex-direction:column; gap:0.15rem; font-size:0.75rem; }
      .pc-score { display:flex; justify-content:space-between; gap:1rem; }
      .pc-score span { color:var(--muted); }
      .pc-score strong { font-family:monospace; }
      .pc-actions { display:flex; gap:1rem; margin-top:0.5rem; font-size:0.72rem; }
      .pc-good { flex:1; }
      .pc-bad { flex:1; }
      .pc-actions ul { list-style:none; padding:0; }
      .pc-actions li { padding:0.15rem 0; }
      .pa-good { color:var(--success); }
      .pa-bad { color:var(--danger); }
      .pc-advice { margin-top:0.5rem; font-size:0.72rem; color:var(--muted); }
      .pc-advice ul { padding-left:1rem; }
      .conf-low { color:var(--danger); }
      .conf-mid { color:var(--warning); }
      .conf-high { color:var(--success); }

      /* Valid Agent */
      .va-summary { display:flex; gap:1rem; align-items:center; padding:0.8rem 1rem;
        border-radius:8px; font-size:0.9rem; margin-bottom:0.5rem; }
      .va-summary.pass { background:rgba(45,125,85,0.08); }
      .va-summary.fail { background:rgba(159,63,63,0.08); }
      .va-icon { font-size:1.5rem; }
      .va-grade { font-weight:700; }
      .va-status { font-family:monospace; font-size:0.8rem; color:var(--muted); }
      .va-table { width:100%; font-size:0.8rem; border-collapse:collapse; margin-top:0.5rem; }
      .va-table th { text-align:left; padding:0.3rem; color:var(--muted); border-bottom:1px solid var(--line); }
      .va-table td { padding:0.3rem; border-bottom:1px solid var(--line); }

      /* Counterfactuals */
      .cf-table { width:100%; font-size:0.8rem; border-collapse:collapse; }
      .cf-table th { text-align:left; padding:0.3rem; color:var(--muted); border-bottom:2px solid var(--line); }
      .cf-table td { padding:0.3rem; border-bottom:1px solid var(--line); font-family:monospace; font-size:0.75rem; }
      .cf-table td:first-child, .cf-table td:nth-child(2) { font-family:inherit; }

      /* Evidence Drawer */
      .evidence-drawer { display:none; position:fixed; top:0; left:0; width:100%; height:100%;
        background:rgba(0,0,0,0.5); z-index:1000; }
      .evidence-drawer.open { display:block; }
      .ev-overlay { display:flex; align-items:center; justify-content:center; height:100%; }
      .ev-content { background:var(--paper); max-width:700px; max-height:80vh;
        overflow-y:auto; border-radius:12px; padding:1.5rem; position:relative; }
      .ev-close { position:absolute; top:0.5rem; right:0.8rem; font-size:1.2rem;
        cursor:pointer; color:var(--muted); }
      .ev-item { margin-bottom:0.8rem; padding-bottom:0.8rem; border-bottom:1px solid var(--line); }
      .ev-item h4 { font-size:0.85rem; margin-bottom:0.3rem; }
      .ev-item pre { font-size:0.7rem; background:var(--bg); padding:0.5rem; border-radius:4px;
        white-space:pre-wrap; word-break:break-all; }

      /* Responsive */
      @media (max-width:768px) {
        .report { padding:1rem 0.5rem; }
        .metric-cards { gap:0.5rem; }
        .mcard { flex:1 1 100px; padding:0.6rem; }
        .player-cards-grid { grid-template-columns:1fr; }
        .vote-flow { flex-direction:column; }
        .sb-table { font-size:0.6rem; }
      }
    </style>"""

    # ------------------------------------------------------------------
    # JS (inline)
    # ------------------------------------------------------------------

    def _render_js(self) -> str:
        return """
    <script>
    function toggleEvidence() {
      var d = document.getElementById('evidence-drawer');
      d.classList.toggle('open');
    }
    function closeEvidence() {
      var d = document.getElementById('evidence-drawer');
      d.classList.remove('open');
    }
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') closeEvidence();
    });
    </script>"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _esc(s: str) -> str:
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", default=None, help="Single game ID")
    ap.add_argument("--all", action="store_true", help="Render all games")
    ap.add_argument(
        "--data-dir",
        default="data/health/reports",
        help="Directory with single_game_data_*.json files",
    )
    args = ap.parse_args()

    data_dir = ROOT / args.data_dir
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        return 1

    if args.game_id:
        data_files = [data_dir / f"single_game_data_{args.game_id}.json"]
    else:
        data_files = sorted(data_dir.glob("single_game_data_*.json"))
        if not args.all:
            print(f"Found {len(data_files)} files. Use --all to render all, or --game-id for one.")
            data_files = data_files[:1]
            print(f"Rendering first: {data_files[0].name}")

    for df in data_files:
        if not df.exists():
            print(f"  SKIP: {df} not found")
            continue

        print(f"  Rendering {df.name}...", end=" ", flush=True)
        data = load_json(df)
        renderer = V3SingleGameHTMLRenderer(data)
        html = renderer.render()

        out_path = data_dir / f"review_game_{data['game_id']}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"→ {out_path.name} ({len(html):,} bytes)")

    print("Done!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
