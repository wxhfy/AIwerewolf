#!/usr/bin/env python3
"""Generate project-closure visual assets from real AI Werewolf evidence.

The script is intentionally deterministic: it reads the strict-mode report and
the persisted replay endpoint for a real game, then emits editable SVG/HTML
assets under docs/assets/closure/.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "assets" / "closure"
STRICT_REPORT = ROOT / "outputs" / "backend_e2e_report.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url: str, timeout: float = 10.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def safe_fetch_json(url: str) -> dict[str, Any] | None:
    try:
        return fetch_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[warn] cannot fetch {url}: {exc}")
        return None


def safe_fetch_text(url: str) -> str | None:
    try:
        return fetch_text(url)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[warn] cannot fetch {url}: {exc}")
        return None


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"[write] {path.relative_to(ROOT)}")


def trunc(text: Any, n: int = 150) -> str:
    value = "" if text is None else str(text)
    value = " ".join(value.replace("\n", " / ").split())
    return value if len(value) <= n else value[: n - 1] + "…"


def phase_label(phase: str) -> str:
    return phase.replace("_", " ").title()


def alignment_for_role(role: str) -> str:
    return "wolf" if "Wolf" in role or role in {"Werewolf", "WhiteWolfKing"} else "village"


def event_summary(event: dict[str, Any], player_names: dict[str, str]) -> str:
    content = event.get("content") or {}
    etype = event.get("type") or event.get("event_type") or ""
    actor = player_names.get(event.get("actor_id") or "", event.get("actor_id") or "")
    target = player_names.get(event.get("target_id") or "", event.get("target_id") or "")

    if etype == "CHAT_MESSAGE":
        return trunc(content.get("speech"), 190)
    if etype == "VOTE_CAST":
        return f"{actor or content.get('voter_name', 'unknown')} -> {target or content.get('target_name', 'unknown')}: {trunc(content.get('reasoning'), 130)}"
    if etype == "PLAYER_DIED":
        return f"{content.get('player_name') or target} died by {content.get('reason')}"
    if etype == "HUNTER_SHOT":
        return f"Hunter shot {target or content.get('target_name', 'unknown')}: {trunc(content.get('reasoning'), 130)}"
    if etype == "NIGHT_ACTION":
        action_type = content.get("action_type") or content.get("kind") or "night action"
        target_obj = content.get("target") or {}
        target_name = target_obj.get("name") if isinstance(target_obj, dict) else target
        return f"{actor or content.get('actor_name', 'unknown')} {action_type} {target_name or target or 'skip'}"
    if etype == "GAME_END":
        return f"Winner: {content.get('winner')}; reason: {content.get('reason')}"
    if etype == "SYSTEM_MESSAGE":
        return trunc(content.get("message"), 180)
    if etype == "PRIVATE_INFO":
        return trunc(content.get("message") or content.get("kind"), 180)
    if etype == "PHASE_CHANGED":
        return phase_label(content.get("phase") or event.get("phase") or "")
    return trunc(content, 180)


def metric_card(label: str, value: Any, source: str = "") -> str:
    return f"""
    <div class="metric-card">
      <div class="metric-value">{escape(str(value))}</div>
      <div class="metric-label">{escape(label)}</div>
      {f'<div class="metric-source">{escape(source)}</div>' if source else ""}
    </div>
    """


def generate_icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024" role="img" aria-label="AI Werewolf icon">
  <defs>
    <linearGradient id="bg" x1="80" x2="944" y1="80" y2="944" gradientUnits="userSpaceOnUse">
      <stop stop-color="#2b1f48"/>
      <stop offset="0.55" stop-color="#53385f"/>
      <stop offset="1" stop-color="#9c5d2c"/>
    </linearGradient>
    <linearGradient id="moon" x1="260" x2="760" y1="170" y2="760" gradientUnits="userSpaceOnUse">
      <stop stop-color="#fffaf3"/>
      <stop offset="1" stop-color="#f0d8b6"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="24" stdDeviation="28" flood-color="#1b1228" flood-opacity="0.38"/>
    </filter>
  </defs>
  <rect width="1024" height="1024" rx="224" fill="url(#bg)"/>
  <circle cx="512" cy="476" r="282" fill="url(#moon)" opacity="0.96" filter="url(#shadow)"/>
  <path d="M295 526c40-106 91-179 154-220l34 101c19-4 39-4 58 0l34-101c64 42 114 115 154 220 26 68-4 165-78 214-38 25-83 38-139 38s-101-13-139-38c-74-49-104-146-78-214Z" fill="#2b1f48"/>
  <path d="M390 541c45-42 91-63 138-63s93 21 138 63c-30 77-74 116-138 116s-108-39-138-116Z" fill="#fffaf3" opacity="0.94"/>
  <circle cx="438" cy="542" r="30" fill="#9f3f3f"/>
  <circle cx="586" cy="542" r="30" fill="#9f3f3f"/>
  <path d="M500 583h24l-12 19-12-19Z" fill="#2b1f48"/>
  <path d="M447 653c45 30 85 30 130 0" fill="none" stroke="#2b1f48" stroke-width="24" stroke-linecap="round"/>
  <path d="M247 814h530" stroke="#f6c27a" stroke-width="34" stroke-linecap="round"/>
  <path d="M319 814c35-58 72-88 111-88 35 0 64 21 82 64 18-43 47-64 82-64 39 0 76 30 111 88" fill="none" stroke="#fffaf3" stroke-width="28" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def generate_architecture_svg() -> str:
    boxes = [
        ("Frontend", "Next.js / React\\nRoom, Game, Timeline", 80, 110, "#fffaf3"),
        ("FastAPI", "REST + WebSocket\\nbackend/app.py", 360, 110, "#fffaf3"),
        ("WerewolfGame", "Phase machine\\n_actions + resolution", 640, 110, "#fffaf3"),
        ("PlayerView", "Visibility.for_player\\nself/public/private", 220, 330, "#f8efe4"),
        ("CognitiveAgent", "Observe - Think - Act\\nrole decisions", 500, 330, "#f8efe4"),
        ("AgentLoop", "tools + LLM\\ntrace + strategy ids", 780, 330, "#f8efe4"),
        ("PostgreSQL", "22 tables\\ncomplete evidence chain", 220, 550, "#eef7f1"),
        ("Track B", "PerStepScorer\\nPublishedReview", 500, 550, "#eef7f1"),
        ("Track C", "KnowledgeAbstractor\\ncandidate -> active", 780, 550, "#eef7f1"),
        ("StrategyRetriever", "BM25 + inverted index\\n4-filter", 500, 760, "#f4edf8"),
    ]
    arrows = [
        (300, 180, 360, 180),
        (580, 180, 640, 180),
        (760, 270, 360, 330),
        (440, 400, 500, 400),
        (720, 400, 780, 400),
        (920, 520, 920, 550),
        (780, 620, 720, 620),
        (500, 620, 440, 620),
        (360, 550, 360, 490),
        (610, 720, 610, 760),
        (500, 830, 360, 490),
    ]
    arrow_svg = "\n".join(
        f'<path d="M{x1} {y1} L{x2} {y2}" stroke="#8f7b6b" stroke-width="4" marker-end="url(#arrow)" fill="none"/>'
        for x1, y1, x2, y2 in arrows
    )
    box_svg = []
    for title, subtitle, x, y, color in boxes:
        lines = subtitle.split("\\n")
        text_lines = "\n".join(
            f'<text x="{x + 110}" y="{y + 82 + i * 25}" text-anchor="middle" font-size="19" fill="#6f6259">{escape(line)}</text>'
            for i, line in enumerate(lines)
        )
        box_svg.append(
            f"""<g>
  <rect x="{x}" y="{y}" width="220" height="130" rx="18" fill="{color}" stroke="#dcc7ae" stroke-width="2"/>
  <text x="{x + 110}" y="{y + 42}" text-anchor="middle" font-size="26" font-weight="700" fill="#2c211b">{escape(title)}</text>
  {text_lines}
</g>"""
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="950" viewBox="0 0 1080 950" role="img" aria-label="AI Werewolf architecture">
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2 2 L10 6 L2 10 Z" fill="#8f7b6b"/>
    </marker>
  </defs>
  <rect width="1080" height="950" fill="#f7efe4"/>
  <text x="540" y="58" text-anchor="middle" font-size="34" font-weight="800" fill="#2c211b">AI Werewolf Product Architecture</text>
  <text x="540" y="88" text-anchor="middle" font-size="18" fill="#6f6259">Frontend -> Game Engine -> Cognitive Agents -> Evaluation -> Knowledge Feedback</text>
  {arrow_svg}
  {"".join(box_svg)}
</svg>
"""


def generate_loop_svg(strict: dict[str, Any]) -> str:
    dbv = strict.get("db_verify", {})
    cards = [
        (
            "Play",
            "7-player real LLM game",
            f"{strict['game']['winner']} win / {strict['game']['duration_s']}s",
            110,
            "#fffaf3",
        ),
        (
            "Audit",
            "AgentDecision + GameEvent",
            f"{dbv.get('decision_count')} decisions / {dbv.get('event_count')} events",
            350,
            "#f8efe4",
        ),
        (
            "Evaluate",
            "Track B scoring",
            f"{strict['artifacts'].get('evaluation_count')} evals / {strict['artifacts'].get('review_count')} review",
            590,
            "#eef7f1",
        ),
        ("Evolve", "Track C lessons", f"+{dbv.get('new_lessons')} candidate lessons", 830, "#f4edf8"),
    ]
    body = []
    for title, subtitle, value, x, color in cards:
        body.append(
            f"""<g>
  <rect x="{x}" y="170" width="190" height="150" rx="22" fill="{color}" stroke="#dcc7ae" stroke-width="2"/>
  <text x="{x + 95}" y="216" text-anchor="middle" font-size="29" font-weight="800" fill="#2c211b">{title}</text>
  <text x="{x + 95}" y="254" text-anchor="middle" font-size="17" fill="#6f6259">{escape(subtitle)}</text>
  <text x="{x + 95}" y="292" text-anchor="middle" font-size="18" font-weight="700" fill="#9c5d2c">{escape(str(value))}</text>
</g>"""
        )
    arrows = "\n".join(
        f'<path d="M{x} 245 L{x + 45} 245" stroke="#8f7b6b" stroke-width="5" marker-end="url(#arrow)" fill="none"/>'
        for x in (300, 540, 780)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1130" height="510" viewBox="0 0 1130 510" role="img" aria-label="Play Evaluate Evolve loop">
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2 2 L10 6 L2 10 Z" fill="#8f7b6b"/>
    </marker>
  </defs>
  <rect width="1130" height="510" fill="#f7efe4"/>
  <text x="565" y="72" text-anchor="middle" font-size="36" font-weight="800" fill="#2c211b">Play -> Evaluate -> Evolve</text>
  <text x="565" y="108" text-anchor="middle" font-size="18" fill="#6f6259">Strict run evidence: {escape(strict["game"]["game_id"])}</text>
  {arrows}
  {"".join(body)}
  <path d="M930 330 C930 420 200 420 200 330" stroke="#9c5d2c" stroke-width="5" fill="none" marker-end="url(#arrow)" opacity="0.72"/>
  <text x="565" y="444" text-anchor="middle" font-size="19" fill="#6f6259">candidate knowledge returns to StrategyRetriever after safety filters</text>
</svg>
"""


def generate_evidence_chain_svg() -> str:
    labels = [
        ("GameEvent", "phase / event_type / actor / target"),
        ("AgentDecision", "observation / raw_output / parsed_action"),
        ("DecisionScore", "correctness / reasoning / impact"),
        ("PublishedReview", "markdown / html / replay bundle"),
        ("StrategyKnowledgeDoc", "candidate / active / deprecated"),
        ("StrategyRetriever", "filtered top-k strategy"),
    ]
    rows = []
    y = 110
    for i, (title, desc) in enumerate(labels):
        rows.append(
            f"""<g>
  <circle cx="120" cy="{y + 40}" r="24" fill="#9c5d2c"/>
  <text x="120" y="{y + 48}" text-anchor="middle" font-size="22" font-weight="800" fill="#fffaf3">{i + 1}</text>
  <rect x="175" y="{y}" width="650" height="80" rx="16" fill="#fffaf3" stroke="#dcc7ae" stroke-width="2"/>
  <text x="205" y="{y + 32}" font-size="24" font-weight="800" fill="#2c211b">{title}</text>
  <text x="205" y="{y + 60}" font-size="18" fill="#6f6259">{desc}</text>
</g>"""
        )
        if i < len(labels) - 1:
            rows.append(
                f'<path d="M120 {y + 66} L120 {y + 112}" stroke="#8f7b6b" stroke-width="4" marker-end="url(#arrow)" fill="none"/>'
            )
        y += 105
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="920" height="800" viewBox="0 0 920 800" role="img" aria-label="Database evidence chain">
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2 2 L10 6 L2 10 Z" fill="#8f7b6b"/>
    </marker>
  </defs>
  <rect width="920" height="800" fill="#f7efe4"/>
  <text x="460" y="58" text-anchor="middle" font-size="34" font-weight="800" fill="#2c211b">Database Evidence Chain</text>
  {"".join(rows)}
</svg>
"""


def generate_game_snapshot_html(strict: dict[str, Any], replay: dict[str, Any]) -> str:
    game = strict.get("game", {})
    dbv = strict.get("db_verify", {})
    artifacts = strict.get("artifacts", {})
    players = replay.get("players") or game.get("players") or []
    player_names = {p.get("id", ""): p.get("name", "") for p in players}
    events = replay.get("events") or []
    decisions = replay.get("decisions") or []

    action_counts: Counter[str] = Counter()
    provider_counts: Counter[str] = Counter()
    retrieval_count = 0
    for decision in decisions:
        parsed = decision.get("parsed_action") or {}
        metadata = parsed.get("metadata") or {}
        action_counts[parsed.get("action_type") or parsed.get("type") or parsed.get("action") or "unknown"] += 1
        provider_counts[metadata.get("provider") or "unknown"] += 1
        if metadata.get("retrieval_used") or parsed.get("retrieval_used"):
            retrieval_count += 1

    event_counts = Counter(event.get("type") or event.get("event_type") or "unknown" for event in events)
    notable_events = [
        event
        for event in events
        if (event.get("type") in {"CHAT_MESSAGE", "VOTE_CAST", "PLAYER_DIED", "HUNTER_SHOT", "GAME_END"})
    ][-12:]

    player_cards = []
    for player in players:
        role = player.get("role", "Unknown")
        alignment = alignment_for_role(role)
        alive = player.get("is_alive", player.get("alive", False))
        persona = player.get("persona") or {}
        if not persona:
            # Role/persona data is available in the first GAME_START event.
            for event in events:
                content = event.get("content") or {}
                for entry in content.get("players", []) if isinstance(content.get("players"), list) else []:
                    if entry.get("id") == player.get("id"):
                        persona = entry.get("persona") or {}
                        break
        player_cards.append(
            f"""
            <article class="player-card {alignment} {"alive" if alive else "dead"}">
              <div class="seat">{escape(str(player.get("seat", player.get("seat_no", "?"))))}</div>
              <div>
                <h3>{escape(player.get("name", "Unknown"))}</h3>
                <p>{escape(role)} · {escape(persona.get("mbti", "MBTI?"))} {escape(persona.get("style_label", ""))}</p>
              </div>
              <span class="status">{"Alive" if alive else "Dead D" + str(player.get("death_day") or "")}</span>
            </article>
            """
        )

    timeline = []
    for event in notable_events:
        timeline.append(
            f"""
            <li>
              <span class="seq">#{event.get("seq")}</span>
              <span class="phase">{escape(event.get("phase", ""))}</span>
              <span class="etype">{escape(event.get("type", event.get("event_type", "")))}</span>
              <p>{escape(event_summary(event, player_names))}</p>
            </li>
            """
        )

    action_bars = "".join(
        f'<div class="bar-row"><span>{escape(k)}</span><b style="width:{max(8, v * 100 / max(action_counts.values() or [1])):.1f}%"></b><em>{v}</em></div>'
        for k, v in action_counts.most_common()
    )
    event_bars = "".join(
        f'<div class="bar-row"><span>{escape(k)}</span><b style="width:{max(8, v * 100 / max(event_counts.values() or [1])):.1f}%"></b><em>{v}</em></div>'
        for k, v in event_counts.most_common(8)
    )

    metrics = "".join(
        [
            metric_card("Winner", str(game.get("winner", "")).upper(), "strict JSON"),
            metric_card("Players", game.get("player_count"), "strict JSON"),
            metric_card("Days", game.get("days"), "strict JSON"),
            metric_card("Duration", f"{game.get('duration_s')}s", "strict JSON"),
            metric_card("Decisions", dbv.get("decision_count"), "DB verify"),
            metric_card("Events", dbv.get("event_count"), "DB verify"),
            metric_card("Tool traces", dbv.get("decisions_with_tool_trace"), "DB verify"),
            metric_card("New lessons", dbv.get("new_lessons"), "Track C"),
            metric_card("Evaluations", artifacts.get("evaluation_count"), "Track B"),
            metric_card("Review", artifacts.get("review_count"), "Track B"),
        ]
    )

    provider_text = ", ".join(f"{k}: {v}" for k, v in provider_counts.items())
    warnings_text = ", ".join(f"{k}={v}" for k, v in (strict.get("log_scan") or {}).items())

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Werewolf Strict Game Snapshot</title>
  <style>
    :root {{
      --bg: #f7efe4;
      --paper: #fffaf3;
      --ink: #241b16;
      --muted: #74675c;
      --line: #e2ccb2;
      --accent: #9c5d2c;
      --wolf: #9f3f3f;
      --village: #2d7d55;
      --blue: #405f8c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #fbf5ec 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      padding: 32px;
    }}
    .page {{ max-width: 1480px; margin: 0 auto; }}
    .hero {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 22px;
      align-items: stretch;
      margin-bottom: 22px;
    }}
    .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 20px 56px rgba(79, 52, 26, 0.12);
      overflow: hidden;
    }}
    .hero-main {{ padding: 30px; }}
    .eyebrow {{ color: var(--accent); font-weight: 800; letter-spacing: .06em; text-transform: uppercase; font-size: 12px; }}
    h1 {{ font-size: 46px; line-height: 1.05; margin: 10px 0 12px; }}
    .subtitle {{ color: var(--muted); font-size: 16px; line-height: 1.6; max-width: 780px; }}
    .game-id {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); margin-top: 16px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-top: 22px; }}
    .metric-card {{ background: #fbf1e5; border: 1px solid #ead6bc; border-radius: 14px; padding: 14px; min-height: 92px; }}
    .metric-value {{ font-weight: 900; color: var(--accent); font-size: 24px; line-height: 1.1; }}
    .metric-label {{ color: var(--ink); font-weight: 700; margin-top: 6px; }}
    .metric-source {{ color: var(--muted); font-size: 11px; margin-top: 4px; }}
    .players {{ padding: 18px; display: grid; gap: 10px; }}
    .player-card {{ display: grid; grid-template-columns: 46px 1fr auto; align-items: center; gap: 12px; padding: 12px; border-radius: 14px; border: 1px solid var(--line); background: #fffdf8; }}
    .player-card.wolf {{ border-left: 6px solid var(--wolf); }}
    .player-card.village {{ border-left: 6px solid var(--village); }}
    .player-card.dead {{ opacity: 0.68; }}
    .seat {{ width: 38px; height: 38px; border-radius: 50%; background: #2b1f48; color: #fff; display: grid; place-items: center; font-weight: 900; }}
    .player-card h3 {{ margin: 0; font-size: 17px; }}
    .player-card p {{ margin: 3px 0 0; color: var(--muted); font-size: 12px; }}
    .status {{ font-size: 12px; font-weight: 800; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }}
    .section {{ padding: 22px; }}
    h2 {{ margin: 0 0 14px; font-size: 24px; }}
    .timeline {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
    .timeline li {{ display: grid; grid-template-columns: 54px 155px 118px 1fr; gap: 10px; align-items: start; border-bottom: 1px solid #ead6bc; padding: 10px 0; }}
    .timeline li:last-child {{ border-bottom: 0; }}
    .seq {{ color: var(--accent); font-weight: 800; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .phase {{ color: var(--blue); font-size: 12px; font-weight: 800; }}
    .etype {{ color: var(--muted); font-size: 12px; font-weight: 700; }}
    .timeline p {{ margin: 0; line-height: 1.5; color: #382b22; font-size: 13px; }}
    .bar-row {{ display: grid; grid-template-columns: 116px 1fr 42px; gap: 10px; align-items: center; margin: 9px 0; font-size: 13px; }}
    .bar-row b {{ display: block; height: 14px; background: linear-gradient(90deg, var(--accent), #d8a36f); border-radius: 999px; }}
    .bar-row em {{ font-style: normal; color: var(--muted); text-align: right; font-weight: 800; }}
    .note {{ color: var(--muted); font-size: 12px; line-height: 1.6; border-top: 1px solid #ead6bc; margin-top: 16px; padding-top: 12px; }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="panel hero-main">
        <div class="eyebrow">Real strict-mode game screenshot source</div>
        <h1>AI Werewolf 真实对局总览</h1>
        <p class="subtitle">该画面由真实 strict mode 对局生成：后端 replay 接口提供事件、玩家和决策，strict JSON 提供验收指标。未使用 mock、demo、fake 或 heuristic 数据。</p>
        <div class="game-id">game_id: {escape(game.get("game_id", replay.get("id", "")))}</div>
        <div class="metrics">{metrics}</div>
      </div>
      <div class="panel players">{"".join(player_cards)}</div>
    </section>
    <section class="grid">
      <div class="panel section">
        <h2>关键事件时间线</h2>
        <ol class="timeline">{"".join(timeline)}</ol>
      </div>
      <div class="panel section">
        <h2>决策与事件分布</h2>
        <h3>Agent actions</h3>
        {action_bars}
        <h3>Event types</h3>
        {event_bars}
        <p class="note">Provider distribution in replay decisions: {escape(provider_text)}. Retrieval used by {retrieval_count}/{len(decisions)} decisions. Risk keyword log scan: {escape(warnings_text)}.</p>
      </div>
    </section>
  </main>
</body>
</html>
"""


def generate_assets_index(game_id: str, assets: list[str]) -> str:
    links = "\n".join(f'<li><a href="{escape(name)}">{escape(name)}</a></li>' for name in assets)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>AI Werewolf Closure Assets</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#f7efe4; color:#241b16; padding:32px; }}
    main {{ max-width:960px; margin:auto; background:#fffaf3; border:1px solid #e2ccb2; border-radius:18px; padding:28px; }}
    a {{ color:#9c5d2c; font-weight:700; }}
    li {{ margin:10px 0; }}
  </style>
</head>
<body>
  <main>
    <h1>AI Werewolf Closure Assets</h1>
    <p>Source game_id: <code>{escape(game_id)}</code></p>
    <ul>{links}</ul>
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", default=None)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    strict = read_json(STRICT_REPORT)
    game_id = args.game_id or strict.get("game", {}).get("game_id")
    if not game_id:
        raise SystemExit("game_id not found; pass --game-id")

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    backend = args.backend.rstrip("/")
    replay_url = f"{backend}/api/replay/{game_id}?show_private=true"
    review_url = f"{backend}/api/games/{game_id}/reviews/html"

    replay = safe_fetch_json(replay_url)
    if replay is None:
        raise SystemExit(f"Replay endpoint is required for real-game visual assets: {replay_url}")

    review_html = safe_fetch_text(review_url)

    write(out / "ai-werewolf-icon.svg", generate_icon_svg())
    write(out / "architecture.svg", generate_architecture_svg())
    write(out / "play-evaluate-evolve.svg", generate_loop_svg(strict))
    write(out / "database-evidence-chain.svg", generate_evidence_chain_svg())
    write(out / "real-game-snapshot.html", generate_game_snapshot_html(strict, replay))
    if review_html:
        write(out / "strict-game-review.html", review_html)

    manifest = {
        "game_id": game_id,
        "backend": backend,
        "sources": {
            "strict_report": str(STRICT_REPORT.relative_to(ROOT)),
            "replay_url": replay_url,
            "review_url": review_url,
        },
        "assets": [
            "ai-werewolf-icon.svg",
            "architecture.svg",
            "play-evaluate-evolve.svg",
            "database-evidence-chain.svg",
            "real-game-snapshot.html",
            "strict-game-review.html" if review_html else None,
        ],
    }
    manifest["assets"] = [item for item in manifest["assets"] if item]
    write(out / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write(out / "index.html", generate_assets_index(game_id, manifest["assets"]))


if __name__ == "__main__":
    main()
