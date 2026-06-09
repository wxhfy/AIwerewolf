#!/usr/bin/env python3
"""V8 Strategy Dashboard — adds Strategy section to MBTI dashboard.

Does NOT rebuild the full dashboard; only generates the strategy-focused
HTML module that can be embedded or viewed standalone.

Usage:
  python scripts/v8_strategy_dashboard.py
"""

from __future__ import annotations

import csv
from pathlib import Path


def build_strategy_html(
    ab_test_md: str = "data/health/strategy_ab_test_v8.md",
    matrix_csv: str = "data/health/persona_role_strategy_matrix_v8.csv",
    output_html: str = "data/health/mbti_performance_dashboard_v8_strategy.html",
) -> str:
    """Build a standalone strategy section HTML."""

    # Read A/B test results from CSV
    results: list[dict] = []
    try:
        with open(matrix_csv, newline="") as f:
            results = list(csv.DictReader(f))
    except FileNotFoundError:
        pass

    # Summary stats
    total_configs = len({r["strategy_id"] for r in results})
    total_groups = len(results)

    rows_html = ""
    for r in sorted(results, key=lambda x: (x["role"], x["strategy_id"])):
        conf_class = {
            "INSUFFICIENT": "low-conf",
            "LOW_SAMPLE": "low-conf",
            "MEDIUM": "pass",
        }.get(r["confidence_level"], "")
        rows_html += (
            f"<tr>"
            f"<td>{r['persona_name']}</td>"
            f"<td>{r['role']}</td>"
            f"<td>{r['strategy_name']}</td>"
            f"<td>{r['n']}</td>"
            f"<td>{float(r['raw_win_rate']) * 100:.1f}%</td>"
            f"<td class='{conf_class}'>{r['confidence_level']}</td>"
            f"</tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>V8 Strategy Dashboard — AI Werewolf</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ color: #ff6b6b; margin-bottom: 10px; }}
  h2 {{ color: #ffd93d; margin: 30px 0 15px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h3 {{ color: #6bcb77; margin: 20px 0 10px; }}
  .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 15px 0; }}
  .card {{ background: #16213e; border: 1px solid #333; border-radius: 8px; padding: 15px; }}
  .card .label {{ font-size: 0.8em; color: #888; }}
  .card .value {{ font-size: 1.5em; font-weight: bold; color: #ffd93d; }}
  table {{ width: 100%; border-collapse: collapse; margin: 15px 0; background: #16213e; border-radius: 8px; overflow: hidden; }}
  th {{ background: #0f3460; padding: 10px; text-align: left; font-weight: 600; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #333; }}
  tr:hover {{ background: #1a3a5c; }}
  .pass {{ color: #6bcb77; }}
  .low-conf {{ color: #ff6b6b; }}
  .warn {{ color: #ffd93d; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; font-weight: bold; }}
  .badge-pass {{ background: #6bcb7733; color: #6bcb77; }}
  .badge-warn {{ background: #ffd93d33; color: #ffd93d; }}
  .badge-fail {{ background: #ff6b6b33; color: #ff6b6b; }}
  .gate-banner {{ background: #16213e; border: 2px solid #ffd93d; border-radius: 8px; padding: 15px; margin: 15px 0; }}
</style>
</head>
<body>
<div class="container">

<h1>V8 Strategy Dashboard</h1>

<div class="gate-banner">
  <strong>Gate: PASS_WITH_LIMITATIONS</strong> |
  Scores are RANKING only, NOT probability |
  4 role-actions LOW_CONF |
  <span class="badge badge-warn">EXPLORATORY</span>
  <span class="badge badge-warn">LOW_SAMPLE</span>
</div>

<!-- Module 1: Strategy Overview -->
<h2>1. Strategy Overview</h2>
<div class="card-grid">
  <div class="card">
    <div class="label">Total Strategy Cards</div>
    <div class="value">11</div>
  </div>
  <div class="card">
    <div class="label">Role-Specific Cards</div>
    <div class="value">9</div>
  </div>
  <div class="card">
    <div class="label">General Cards</div>
    <div class="value">2</div>
  </div>
  <div class="card">
    <div class="label">Strategy Types</div>
    <div class="value">8</div>
  </div>
  <div class="card">
    <div class="label">Configs Tested (A/B)</div>
    <div class="value">{total_configs}</div>
  </div>
  <div class="card">
    <div class="label">Persona×Role×Strategy Groups</div>
    <div class="value">{total_groups}</div>
  </div>
</div>

<!-- Module 2: Best Strategy per Role -->
<h2>2. Strategy Cards by Role</h2>
<table>
  <tr><th>Role</th><th>Strategy ID</th><th>Name</th><th>Type</th><th>Tips</th></tr>
  <tr><td>Seer</td><td>seer_aggressive_reveal_v1</td><td>激进信息释放</td><td>info_release</td><td>14+4r</td></tr>
  <tr><td>Seer</td><td>seer_conservative_hide_v1</td><td>保守信息隐藏</td><td>info_release</td><td>6</td></tr>
  <tr><td>Witch</td><td>witch_conservative_save_v1</td><td>保守用药</td><td>resource_management</td><td>11+4r</td></tr>
  <tr><td>Witch</td><td>witch_aggressive_poison_v1</td><td>激进用药</td><td>resource_management</td><td>3</td></tr>
  <tr><td>Hunter</td><td>hunter_restraint_v1</td><td>猎人不跳</td><td>threat</td><td>9+3r</td></tr>
  <tr><td>Guard</td><td>guard_key_role_protect_v1</td><td>关键神守</td><td>protection</td><td>8+2r</td></tr>
  <tr><td>Werewolf</td><td>werewolf_low_profile_deception_v1</td><td>低调深水伪装</td><td>deception</td><td>20</td></tr>
  <tr><td>Werewolf</td><td>werewolf_strong_vote_lead_v1</td><td>悍跳带队冲锋</td><td>vote_lead</td><td>26</td></tr>
  <tr><td>Villager</td><td>villager_logic_vote_v1</td><td>逻辑分析投票</td><td>logic_vote</td><td>11</td></tr>
  <tr><td>All</td><td>general_basic_logic_v1</td><td>通用基础逻辑</td><td>general</td><td>22</td></tr>
  <tr><td>All</td><td>general_game_theory_v1</td><td>博弈论视角</td><td>game_theory</td><td>9</td></tr>
</table>

<!-- Module 3: Persona × Role × Strategy Matrix -->
<h2>3. Persona × Role × Strategy Matrix</h2>
<table>
  <tr><th>Persona</th><th>Role</th><th>Strategy</th><th>N</th><th>Win Rate</th><th>Confidence</th></tr>
  {rows_html if rows_html else '<tr><td colspan="6">No A/B test data yet. Run <code>scripts/v8_strategy_ab_test.py</code> first.</td></tr>'}
</table>

<!-- Module 4: Strategy A/B Test Summary -->
<h2>4. Strategy A/B Test (Heuristic, 20 games)</h2>
<table>
  <tr><th>Role</th><th>Strategy A</th><th>WR A</th><th>Strategy B</th><th>WR B</th><th>Δ</th><th>N per group</th></tr>
  <tr>
    <td>Seer</td>
    <td>aggressive_reveal</td><td>20.0%</td>
    <td>conservative_hide</td><td>60.0%</td>
    <td class="low-conf">+40.0%</td>
    <td><span class="badge badge-warn">5</span></td>
  </tr>
  <tr>
    <td>Werewolf</td>
    <td>low_profile_deception</td><td>60.0%</td>
    <td>strong_vote_lead</td><td>40.0%</td>
    <td class="low-conf">-20.0%</td>
    <td><span class="badge badge-warn">10</span></td>
  </tr>
</table>
<p class="warn">⚠️ n < 10 = LOW_SAMPLE. Results are indicative, not conclusive.</p>

<!-- Module 5: Strategy Failure Cases -->
<h2>5. Known Strategy Limitations</h2>
<table>
  <tr><th>Issue</th><th>Strategy</th><th>Reason</th></tr>
  <tr>
    <td><span class="badge badge-warn">LOW_CONF</span></td>
    <td>Witch strategies</td>
    <td>Witch Save LOW_CONF (1 bad label). Strategy evaluation limited.</td>
  </tr>
  <tr>
    <td><span class="badge badge-warn">LOW_CONF</span></td>
    <td>Hunter strategy</td>
    <td>Hunter Shot LOW_CONF (1 bad label). Cannot validate shooting strategy.</td>
  </tr>
  <tr>
    <td><span class="badge badge-warn">UNVALIDATED</span></td>
    <td>All speech-related strategies</td>
    <td>Speech quality has 0 labeled samples. Strategy effect on speech quality unknown.</td>
  </tr>
  <tr>
    <td><span class="badge badge-warn">HEURISTIC ONLY</span></td>
    <td>A/B test results</td>
    <td>Current A/B test used heuristic agents. LLM agent results may differ.</td>
  </tr>
</table>

<!-- Module 6: Low-Confidence Strategy Groups -->
<h2>6. Low-Confidence Warning</h2>
<div class="gate-banner">
  <p>The following strategy evaluations are downgraded:</p>
  <ul>
    <li><strong>Seer strategies</strong> — Seer Release LOW_CONF, d=0.15, 0 bad labels</li>
    <li><strong>Witch strategies</strong> — Witch Save LOW_CONF, d=0.28, 1 bad label</li>
    <li><strong>Hunter strategy</strong> — Hunter Shot LOW_CONF, d=0.31, 12 labeled (1 bad)</li>
    <li><strong>A/B test sample</strong> — n=5 per Seer group, n=10 per Werewolf group (each game has 2 wolves)</li>
  </ul>
  <p>Do NOT claim one strategy is definitively 'best'. Use 'under current sample, X outperforms Y'.</p>
</div>

</div>
</body>
</html>"""

    Path(output_html).parent.mkdir(parents=True, exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)
    return output_html


if __name__ == "__main__":
    out = build_strategy_html()
    print(f"Strategy dashboard: {out}")
