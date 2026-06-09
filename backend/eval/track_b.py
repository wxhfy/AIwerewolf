"""Track B review + validation + publishing pipeline.

Builds on top of backend.eval.review's existing metrics/report generator and
adds the missing acceptance-layer pieces from docs/B_REVIEW_VALIDATION_PLAN.md:

- replay bundle
- speech acts
- public suspicion matrix
- validation result with multi-gate issues
- repair loop
- publishable review document for API/frontend persistence
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from html import escape
from typing import Any
from typing import Iterable
from uuid import uuid4

from backend.engine.models import EventType
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.eval.review import LeaderboardAggregator
from backend.eval.review import generate_review_report
from backend.eval.types import BadCaseReport
from backend.eval.types import CounterfactualCase
from backend.eval.types import MVPResult
from backend.eval.types import PlayerReview
from backend.eval.types import ReviewReport
from backend.eval.types import StrategySuggestion
from backend.eval.types import TurningPoint


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


@dataclass
class ReplayBundle:
    game_id: str
    rule_pack: str
    seed: int | None
    players: list[dict[str, Any]]
    events: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    votes: list[dict[str, Any]]
    deaths: list[dict[str, Any]]
    final_state: dict[str, Any]
    winner: str | None
    finished_at: str


@dataclass
class SpeechAct:
    speech_event_id: str
    player_id: str
    player_name: str
    day: int
    phase: str
    stance: str
    claims: list[str] = field(default_factory=list)
    suspected_players: list[str] = field(default_factory=list)
    defended_players: list[str] = field(default_factory=list)
    mentioned_players: list[str] = field(default_factory=list)
    grounded_event_ids: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    evidence_event_ids: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class SuspicionSnapshot:
    game_id: str
    day: int
    phase: str
    event_id: str | None
    target_scores: dict[str, float]
    evidence_event_ids: dict[str, list[str]]


@dataclass
class ValidationIssue:
    issue_id: str
    severity: str
    gate: str
    issue_type: str
    location: dict[str, Any]
    message: str
    evidence: list[str]
    required_fix: str
    repair_tool: str | None
    blocking: bool


@dataclass
class ValidationResult:
    report_id: str
    game_id: str
    passed: bool
    grade: str
    score: float
    issues: list[ValidationIssue]
    required_tools: list[str]
    revision_instructions: list[str]
    publish_allowed: bool


@dataclass
class PublishedReviewDocument:
    report_id: str
    game_id: str
    status: str
    view_scope: str
    created_at: str
    published_at: str | None
    replay_bundle: dict[str, Any]
    review_report: dict[str, Any]
    markdown: str
    speech_acts: list[dict[str, Any]]
    suspicion_matrix: list[dict[str, Any]]
    validation_result: dict[str, Any]
    repair_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VisualReportAgent:
    """Single-purpose visual agent that paints SVG assets for the HTML report."""

    def render_story_banner(self, document: PublishedReviewDocument) -> str:
        report = document.review_report
        players = document.replay_bundle.get("players", [])
        scoreboard = report.get("scoreboard", [])
        top_names = [escape(str(item.get("player_name", ""))) for item in scoreboard[:3] if item.get("player_name")]
        cast = " · ".join(top_names) or "No standout cast"
        winner = escape(str(report.get("winner") or document.replay_bundle.get("winner") or "unknown"))
        total_days = int(report.get("total_days") or 0)
        total_events = int(report.get("total_events") or len(document.replay_bundle.get("events", [])))
        alive_count = sum(1 for player in players if player.get("alive"))
        return f"""
        <svg viewBox="0 0 1100 260" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="review banner">
          <defs>
            <linearGradient id="bannerBg" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#f6dcc0" />
              <stop offset="50%" stop-color="#f2efe8" />
              <stop offset="100%" stop-color="#d9b38a" />
            </linearGradient>
            <linearGradient id="moonGlow" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#fff6db" />
              <stop offset="100%" stop-color="#e7c289" />
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="1100" height="260" rx="28" fill="url(#bannerBg)" />
          <circle cx="872" cy="74" r="42" fill="url(#moonGlow)" opacity="0.95" />
          <path d="M0 198 C180 160 280 250 466 212 C666 170 790 230 1100 178 L1100 260 L0 260 Z" fill="#c48752" opacity="0.25"/>
          <path d="M0 214 C140 176 308 236 476 208 C640 182 830 238 1100 188 L1100 260 L0 260 Z" fill="#7d4f34" opacity="0.16"/>
          <g transform="translate(58 52)">
            <text x="0" y="0" font-size="14" font-family="Segoe UI, PingFang SC, sans-serif" fill="#7a6c62" letter-spacing="2">VISUAL REPORT AGENT</text>
            <text x="0" y="48" font-size="34" font-weight="700" font-family="Segoe UI, PingFang SC, sans-serif" fill="#1f1a17">AI Werewolf · Final Table Tableau</text>
            <text x="0" y="88" font-size="16" font-family="Segoe UI, PingFang SC, sans-serif" fill="#4b3d34">Winner: {winner} · Days: {total_days} · Events: {total_events} · Alive at finish: {alive_count}</text>
            <text x="0" y="122" font-size="15" font-family="Segoe UI, PingFang SC, sans-serif" fill="#5f5147">Standout seats: {cast}</text>
          </g>
          <g transform="translate(768 136)">
            <rect x="0" y="0" width="240" height="74" rx="18" fill="#fff9f1" stroke="#dfc7ac"/>
            <text x="22" y="28" font-size="13" font-family="Segoe UI, PingFang SC, sans-serif" fill="#7a6c62">Players / Seats</text>
            <text x="22" y="56" font-size="28" font-weight="700" font-family="Segoe UI, PingFang SC, sans-serif" fill="#1f1a17">{len(players)}</text>
            <text x="136" y="28" font-size="13" font-family="Segoe UI, PingFang SC, sans-serif" fill="#7a6c62">Report grade</text>
            <text x="136" y="56" font-size="28" font-weight="700" font-family="Segoe UI, PingFang SC, sans-serif" fill="#9c5d2c">{escape(str(document.validation_result.get("grade", "n/a")))}</text>
          </g>
        </svg>
        """

    def render_timeline_ribbon(self, document: PublishedReviewDocument) -> str:
        points = document.review_report.get("turning_points", [])[:5]
        width = 980
        height = 180
        if not points:
            return f"""
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="empty timeline">
              <rect width="{width}" height="{height}" rx="24" fill="#fffaf3" stroke="#e5d3bd"/>
              <text x="36" y="54" font-size="24" font-family="Segoe UI, PingFang SC, sans-serif" fill="#1f1a17">No turning points recorded</text>
              <text x="36" y="88" font-size="15" font-family="Segoe UI, PingFang SC, sans-serif" fill="#7a6c62">The validator published this report without strong highlight events.</text>
            </svg>
            """
        step = width / max(len(points), 1)
        nodes: list[str] = [
            f'<line x1="60" y1="{height / 2:.1f}" x2="{width - 60}" y2="{height / 2:.1f}" stroke="#d3b18d" stroke-width="6" stroke-linecap="round"/>'
        ]
        for index, point in enumerate(points):
            x = step * index + step / 2
            y = 90 if index % 2 == 0 else 114
            title = escape(str(point.get("title", "Turning point")))
            desc = escape(str(point.get("description", "")))[:68]
            day = escape(str(point.get("day", "-")))
            nodes.append(
                f"""
                <circle cx="{x:.1f}" cy="{height / 2:.1f}" r="12" fill="#9c5d2c" />
                <line x1="{x:.1f}" y1="{height / 2:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#9c5d2c" stroke-width="3"/>
                <rect x="{x - 88:.1f}" y="{y - 42:.1f}" width="176" height="62" rx="16" fill="#fff9f1" stroke="#dfc7ac"/>
                <text x="{x - 74:.1f}" y="{y - 18:.1f}" font-size="13" font-family="Segoe UI, PingFang SC, sans-serif" fill="#9c5d2c">Day {day}</text>
                <text x="{x - 74:.1f}" y="{y + 2:.1f}" font-size="14" font-weight="700" font-family="Segoe UI, PingFang SC, sans-serif" fill="#1f1a17">{title}</text>
                <text x="{x - 74:.1f}" y="{y + 22:.1f}" font-size="11.5" font-family="Segoe UI, PingFang SC, sans-serif" fill="#6d6057">{desc}</text>
                """
            )
        return f"""
        <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="turning point timeline">
          <rect width="{width}" height="{height}" rx="24" fill="#fffaf3" stroke="#e5d3bd"/>
          {"".join(nodes)}
        </svg>
        """

    def render_suspicion_heatmap(self, document: PublishedReviewDocument) -> str:
        snapshots = document.suspicion_matrix[-4:]
        players = document.replay_bundle.get("players", [])
        player_names = {player["id"]: player["name"] for player in players}
        ordered_ids = [player["id"] for player in players[:8]]
        max(len(snapshots), 1)
        rows = max(len(ordered_ids), 1)
        width = 980
        height = 76 + rows * 36
        cell_w = 150
        cell_h = 26
        header_x = 168
        nodes = [f'<rect width="{width}" height="{height}" rx="24" fill="#fffaf3" stroke="#e5d3bd"/>']
        for col, snapshot in enumerate(snapshots):
            label = escape(f"D{snapshot['day']} · {snapshot['phase']}")
            nodes.append(
                f'<text x="{header_x + col * cell_w + 20}" y="34" font-size="12" font-family="Segoe UI, PingFang SC, sans-serif" fill="#7a6c62">{label}</text>'
            )
        for row, player_id in enumerate(ordered_ids):
            y = 58 + row * 36
            nodes.append(
                f'<text x="24" y="{y + 18}" font-size="13" font-family="Segoe UI, PingFang SC, sans-serif" fill="#1f1a17">{escape(player_names.get(player_id, player_id))}</text>'
            )
            for col, snapshot in enumerate(snapshots):
                value = float(snapshot.get("target_scores", {}).get(player_id, 0.0))
                shade = int(255 - min(max(value, 0.0), 1.0) * 120)
                fill = f"rgb(190,{shade},{shade - 24 if shade > 40 else 16})"
                nodes.append(
                    f'<rect x="{header_x + col * cell_w}" y="{y}" width="118" height="{cell_h}" rx="10" fill="{fill}" stroke="#ebd8c5"/>'
                )
                nodes.append(
                    f'<text x="{header_x + col * cell_w + 44}" y="{y + 17}" font-size="12" font-weight="700" font-family="Segoe UI, PingFang SC, sans-serif" fill="#fff">{value:.2f}</text>'
                )
        return f"""
        <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="suspicion heatmap">
          {"".join(nodes)}
        </svg>
        """

    def render_vote_flow(self, document: PublishedReviewDocument) -> str:
        """Vote flow diagram: who voted for whom across days (sankey-style SVG)."""
        votes = document.replay_bundle.get("votes", [])
        players = document.replay_bundle.get("players", [])
        names = {p["id"]: p["name"] for p in players}
        if not votes:
            return ""
        by_day: dict[int, list[dict]] = {}
        for v in votes:
            by_day.setdefault(v.get("day", 0), []).append(v)
        days = sorted(by_day.keys())[-3:]
        width, _cell_h, row_h = 980, 28, 36
        height = 50 + len(days) * (len(players) * row_h + 20)
        nodes = [
            f'<rect width="{width}" height="{height}" rx="24" fill="#fffaf3" stroke="#e5d3bd"/>',
            '<text x="36" y="34" font-size="16" font-weight="700" fill="#1f1a17">Vote Flow</text>',
        ]
        y = 50
        for day in days:
            day_votes = by_day.get(day, [])
            nodes.append(f'<text x="36" y="{y + 18}" font-size="14" fill="#9c5d2c">Day {day}</text>')
            y += 24
            for v in day_votes[: len(players) * 2]:
                voter_n = escape(names.get(v.get("voter_id", ""), "?"))
                target_n = escape(names.get(v.get("target_id", ""), "?"))
                nodes.append(f'<text x="36" y="{y + 18}" font-size="12" fill="#4b3d34">{voter_n} → {target_n}</text>')
                y += row_h
            y += 8
        return f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">{"".join(nodes)}</svg>'

    def render_decision_trajectory(self, document: PublishedReviewDocument) -> str:
        """Per-player decision quality trajectory (SVG line chart)."""
        per_step = document.review_report.get("metadata", {}).get("per_step_scores", [])
        if not per_step:
            return ""
        players = {}
        for ps in per_step:
            players.setdefault(ps.get("player_name", "?"), []).append(ps)
        width, height = 980, 120 + len(players) * 80
        nodes = [
            f'<rect width="{width}" height="{height}" rx="24" fill="#fffaf3" stroke="#e5d3bd"/>',
            '<text x="36" y="34" font-size="16" font-weight="700" fill="#1f1a17">Decision Quality Trajectory</text>',
        ]
        colors = ["#9c5d2c", "#4a90d9", "#e74c3c", "#27ae60", "#8e44ad", "#f39c12", "#1abc9c"]
        y = 50
        for pi, (pname, scores) in enumerate(players.items()):
            color = colors[pi % len(colors)]
            nodes.append(f'<text x="36" y="{y + 16}" font-size="12" fill="{color}">{escape(pname)}</text>')
            if len(scores) >= 2:
                step_w = (width - 80) / max(len(scores) - 1, 1)
                pts = [
                    f"{80 + i * step_w:.0f},{y + 50 - s.get('overall_score', 0.5) * 30:.0f}"
                    for i, s in enumerate(scores)
                ]
                nodes.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
            y += 70
        return f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">{"".join(nodes)}</svg>'

    def render_score_radar(self, document: PublishedReviewDocument) -> str:
        """Multi-dimensional score radar for top 3 players (SVG)."""
        scoreboard = document.review_report.get("scoreboard", [])[:3]
        players = document.replay_bundle.get("players", [])
        names = {p["id"]: p["name"] for p in players}
        if not scoreboard:
            return ""
        width, height, cx, cy, r = 400, 300, 180, 150, 110
        dims = ["strategy", "logic", "social"]
        colors = ["#9c5d2c", "#4a90d9", "#e74c3c"]
        angles = {d: -90 + i * 120 for i, d in enumerate(dims)}
        nodes = [
            f'<rect width="{width}" height="{height}" rx="20" fill="#fffaf3" stroke="#e5d3bd"/>',
            '<text x="20" y="28" font-size="14" font-weight="700" fill="#1f1a17">Score Radar</text>',
        ]
        for level in [0.3, 0.6, 0.9]:
            pts = [
                f"{cx + r * level * __import__('math').cos(__import__('math').radians(a)):.0f},{cy + r * level * __import__('math').sin(__import__('math').radians(a)):.0f}"
                for a in angles.values()
            ]
            nodes.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="#e5d3bd" stroke-width="1"/>')
        for dim, angle in angles.items():
            lx = cx + r * 1.05 * __import__("math").cos(__import__("math").radians(angle))
            ly = cy + r * 1.05 * __import__("math").sin(__import__("math").radians(angle))
            nodes.append(
                f'<text x="{lx - 16:.0f}" y="{ly + 4:.0f}" font-size="10" fill="#7a6c62" text-anchor="middle">{dim}</text>'
            )
        for pi, player in enumerate(scoreboard):
            pid = player.get("player_id", "")
            pname = escape(names.get(pid, player.get("player_name", "?")))
            scores = player.get("judge_scores", {})
            pts = []
            for dim, angle in angles.items():
                s = scores.get(dim, 0.5) / 10.0
                x = cx + r * s * __import__("math").cos(__import__("math").radians(angle))
                y = cy + r * s * __import__("math").sin(__import__("math").radians(angle))
                pts.append(f"{x:.0f},{y:.0f}")
            nodes.append(
                f'<polygon points="{" ".join(pts)}" fill="{colors[pi]}" fill-opacity="0.2" stroke="{colors[pi]}" stroke-width="2"/>'
            )
            nodes.append(f'<text x="20" y="{270 + pi * 14}" font-size="10" fill="{colors[pi]}">{pname}</text>')
        return f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">{"".join(nodes)}</svg>'


class HTMLReviewRenderer:
    def render(self, document: PublishedReviewDocument) -> str:
        report = document.review_report
        scoreboard = list(report.get("scoreboard", []))
        player_reviews = list(report.get("player_reviews", []))
        turning_points = list(report.get("turning_points", []))
        counterfactuals = list(report.get("counterfactuals", []))
        bad_cases = list(report.get("bad_cases", []))
        mvp_results = list(report.get("mvp_results", []))
        strategy_suggestions = list(report.get("strategy_suggestions", []))
        validation = document.validation_result

        player_name_by_id = {p["id"]: p["name"] for p in document.replay_bundle.get("players", [])}
        total_players = len(document.replay_bundle.get("players", []))
        village_count = sum(1 for p in document.replay_bundle.get("players", []) if p.get("alignment") == "village")
        wolf_count = total_players - village_count
        winner = escape(str(report.get("winner", "unknown")))
        winner_label = "🐺 狼人胜" if winner == "wolf" else "🏘️ 村民胜"
        game_summary = escape(str(report.get("game_summary", "")))
        total_days = int(report.get("total_days", 0))
        total_events = int(report.get("total_events", 0))
        score_max = max([float(e.get("adjusted_final_score", 0)) for e in scoreboard] + [1.0])

        # ---- build sections ----
        scoreboard_html = self._build_scoreboard(scoreboard, score_max)
        mvp_html = self._build_mvp(mvp_results)
        player_reviews_html = self._build_player_reviews(player_reviews, score_max)
        turning_html = self._build_turning_points(turning_points)
        counterfactual_html = self._build_counterfactuals(counterfactuals)
        bad_cases_html = self._build_bad_cases(bad_cases)
        strategy_html = self._build_strategies(strategy_suggestions)
        camp_html = self._build_camp(village_count, wolf_count, winner)
        meta_html = self._build_meta(document, len(scoreboard), total_days, total_events, validation)
        suspicion_html = self._build_suspicion(document, player_name_by_id)
        speech_html = self._build_speech_acts(document)
        validation_html = self._build_validation(validation)

        # ---- leaderboards (queried from DB) ----
        model_lb_html = self._build_model_leaderboard()
        framework_lb_html = self._build_framework_leaderboard()

        return self._render_full_html(
            document,
            winner_label,
            game_summary,
            meta_html,
            mvp_html,
            scoreboard_html,
            player_reviews_html,
            turning_html,
            counterfactual_html,
            bad_cases_html,
            strategy_html,
            camp_html,
            suspicion_html,
            speech_html,
            model_lb_html,
            framework_lb_html,
            validation_html,
        )

    # ── sub-renderers ─────────────────────────────────────────────

    def _build_meta(self, document, n_players, total_days, total_events, validation):
        gid = escape(document.game_id[:8])
        grade = escape(str(validation.get("grade", "-")))
        status = "✓ 已发布" if validation.get("publish_allowed") else "审核中"
        return f"""<div class="meta-card"><span class="meta-label">对局</span><strong>{gid}</strong></div>
<div class="meta-card"><span class="meta-label">玩家</span><strong>{n_players}</strong></div>
<div class="meta-card"><span class="meta-label">天数 / 事件</span><strong>{total_days}天 · {total_events}事件</strong></div>
<div class="meta-card"><span class="meta-label">校验</span><strong class="{"pass" if grade == "pass" else "fail"}">{grade} · {status}</strong></div>"""

    def _build_mvp(self, mvp_results):
        if not mvp_results:
            return ""
        cards = []
        for mvp in mvp_results[:2]:
            mtype = {"global_mvp": "🏆 全局 MVP", "winner_mvp": "🥇 胜方 MVP"}.get(mvp.get("mvp_type", ""), "⭐ MVP")
            name = escape(str(mvp.get("player_name", "")))
            role = escape(str(mvp.get("role", "")))
            reason = escape(str(mvp.get("reason", "")))
            evidence = "".join(f"<li>{escape(str(e))}</li>" for e in mvp.get("evidence", [])[:3])
            cards.append(f"""<div class="mvp-card">
  <div class="mvp-type">{mtype}</div>
  <div class="mvp-name">{name} <span class="mvp-role">{role}</span></div>
  <p class="mvp-reason">{reason}</p>
  <ul class="mvp-evidence">{evidence}</ul>
</div>""")
        return f"""<section class="section" id="mvp">
<h2 class="section-title">MVP</h2>
<div class="mvp-grid">{"".join(cards)}</div>
</section>"""

    def _build_scoreboard(self, scoreboard, score_max):
        rows = []
        medals = ["🥇", "🥈", "🥉"]
        for e in scoreboard[:7]:
            rank = int(e.get("rank", 0))
            medal = medals[rank - 1] if rank <= 3 else f"#{rank}"
            name = escape(str(e.get("player_name", "")))
            role = escape(str(e.get("role", "")))
            align = escape(str(e.get("alignment", "")))
            score = float(e.get("adjusted_final_score", 0))
            pct = (score / score_max) * 100
            side_cls = "wolf-side" if align == "wolf" else "village-side"
            rows.append(f"""<div class="sb-row">
  <span class="sb-medal">{medal}</span>
  <div class="sb-info">
    <span class="sb-name">{name}</span>
    <span class="sb-meta">{role} · <span class="{side_cls}">{align}</span></span>
  </div>
  <div class="sb-bar-track"><div class="sb-bar" style="width:{pct:.0f}%"></div></div>
  <span class="sb-score">{score:.1f}</span>
</div>""")
        return f"""<section class="section">
<h2 class="section-title">玩家评分榜</h2>
<div class="scoreboard">{"".join(rows)}</div>
</section>"""

    def _build_player_reviews(self, player_reviews, score_max):
        if not player_reviews:
            return ""
        cards = []
        for i, pr in enumerate(player_reviews[:7]):
            name = escape(str(pr.get("player_name", "")))
            role = escape(str(pr.get("role", "")))
            align = escape(str(pr.get("alignment", "")))
            overall = escape(str(pr.get("overall_summary", "")))
            score = float(pr.get("adjusted_final_score", 0))
            process = float(pr.get("process_score", 0))
            outcome = float(pr.get("outcome_bonus", 0))
            speech = escape(str(pr.get("speech_summary", "")))
            score_summary = escape(str(pr.get("score_summary", "")))
            pct = (score / score_max) * 100

            strengths = "".join(f"<li>{escape(str(s))}</li>" for s in pr.get("strengths", [])[:4])
            weaknesses = "".join(f"<li>{escape(str(w))}</li>" for w in pr.get("weaknesses", [])[:4])
            highlights = "".join(f"<li>{escape(str(h))}</li>" for h in pr.get("highlights", [])[:4])
            suggestions = "".join(f"<li>{escape(str(s))}</li>" for s in pr.get("suggestions", [])[:4])
            mistakes = "".join(f"<li>{escape(str(m))}</li>" for m in pr.get("mistakes", [])[:4])

            collapsed = "collapsed" if i >= 3 else ""
            cards.append(f"""<details class="player-card {collapsed}" {"open" if i < 3 else ""}>
<summary class="pc-summary">
  <span class="pc-index">#{i + 1}</span>
  <span class="pc-name">{name}</span>
  <span class="pc-role">{role} · {align}</span>
  <span class="pc-score-badge" style="--pct:{pct:.0f}%">{score:.1f}</span>
  <svg class="pc-chevron" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>
</summary>
<div class="pc-body">
  <p class="pc-overall">{overall}</p>
  <div class="pc-score-grid">
    <div class="pc-score-item"><span class="pc-sl">过程分</span><strong>{process:.1f}</strong></div>
    <div class="pc-score-item"><span class="pc-sl">胜负加成</span><strong>{outcome:.1f}</strong></div>
    <div class="pc-score-item"><span class="pc-sl">最终得分</span><strong>{score:.1f}</strong></div>
  </div>
  <p class="pc-speech">💬 {speech}</p>
  <p class="pc-score-note">{score_summary}</p>
  {f'<div class="pc-col"><h4>✅ 优势</h4><ul>{strengths}</ul></div>' if strengths else ""}
  {f'<div class="pc-col"><h4>⚠️ 不足</h4><ul>{weaknesses}</ul></div>' if weaknesses else ""}
  {f'<div class="pc-col"><h4>🌟 亮点</h4><ul>{highlights}</ul></div>' if highlights else ""}
  {f'<div class="pc-col"><h4>💡 建议</h4><ul>{suggestions}</ul></div>' if suggestions else ""}
  {f'<div class="pc-col"><h4>❌ 失误</h4><ul>{mistakes}</ul></div>' if mistakes else ""}
</div>
</details>""")
        return f"""<section class="section" id="player-reviews">
<h2 class="section-title">个人深度复盘</h2>
<div class="player-cards">{"".join(cards)}</div>
</section>"""

    def _build_turning_points(self, turning_points):
        if not turning_points:
            return '<section class="section"><h2 class="section-title">关键决策复盘</h2><p class="empty">暂无关键转折点</p></section>'
        items = []
        for tp in turning_points[:6]:
            day = tp.get("day", "?")
            title = escape(str(tp.get("title", "")))
            desc = escape(str(tp.get("description", "")))
            impact = float(tp.get("impact", 0))
            impact_cls = "impact-high" if impact >= 1.0 else "impact-mid" if impact >= 0.5 else "impact-low"
            related = ", ".join(str(p) for p in tp.get("related_players", [])[:3])
            evidence = "".join(f"<li>{escape(str(e))}</li>" for e in tp.get("evidence", [])[:2])
            items.append(f"""<div class="tp-card">
  <div class="tp-header">
    <span class="tp-day">D{day}</span>
    <span class="tp-title">{title}</span>
    <span class="tp-impact {impact_cls}">{impact:+.1f}</span>
  </div>
  <p class="tp-desc">{desc}</p>
  {f'<p class="tp-related">👥 {related}</p>' if related else ""}
  {f'<ul class="tp-evidence">{evidence}</ul>' if evidence else ""}
</div>""")
        return f"""<section class="section" id="turning-points">
<h2 class="section-title">关键决策复盘</h2>
<div class="tp-grid">{"".join(items)}</div>
</section>"""

    def _build_counterfactuals(self, counterfactuals):
        if not counterfactuals:
            return (
                '<section class="section"><h2 class="section-title">反事实推演</h2><p class="empty">暂无</p></section>'
            )
        items = []
        for cf in counterfactuals[:6]:
            ctype = escape(str(cf.get("counterfactual_type", cf.get("phase", ""))))
            desc = escape(str(cf.get("expected_effect", cf.get("description", ""))))
            conf = float(cf.get("confidence", 0.5)) * 100
            assumptions = cf.get("assumptions", "")
            if isinstance(assumptions, dict):
                orig = escape(str(assumptions.get("original_decision", "")))
                alt = escape(str(assumptions.get("alternative", "")))
            else:
                orig = escape(str(assumptions))
                alt = ""
            items.append(f"""<div class="cf-card">
  <div class="cf-type">{ctype}</div>
  <p class="cf-desc">{desc}</p>
  <div class="cf-confidence"><span class="cf-bar" style="width:{conf:.0f}%"></span><span class="cf-pct">{conf:.0f}% 置信</span></div>
  {f'<div class="cf-compare"><span class="cf-orig">{orig}</span><span class="cf-arrow">→</span><span class="cf-alt">{alt}</span></div>' if orig and alt else ""}
</div>""")
        return f"""<section class="section" id="counterfactuals">
<h2 class="section-title">反事实推演</h2>
<div class="cf-grid">{"".join(items)}</div>
</section>"""

    def _build_bad_cases(self, bad_cases):
        if not bad_cases:
            return ""
        items = "".join(
            f"""<div class="bc-card">
  <span class="bc-player">{escape(str(b.get("player_name", "")))}</span>
  <span class="bc-severity">{escape(str(b.get("severity", "")))}</span>
  <p class="bc-desc">{escape(str(b.get("description", "")))}</p>
</div>"""
            for b in bad_cases[:5]
        )
        return f"""<section class="section" id="bad-cases">
<h2 class="section-title">关键失误</h2>
<div class="bc-grid">{items}</div>
</section>"""

    def _build_strategies(self, suggestions):
        if not suggestions:
            return ""
        items = "".join(
            f"""<div class="sg-card sg-{escape(str(s.get("priority", "medium")))}">
  <span class="sg-priority">{escape(str(s.get("priority", "medium")))}</span>
  <p class="sg-text">{escape(str(s.get("suggestion", "")))}</p>
  <span class="sg-target">→ {escape(str(s.get("target_type", "")))} · {escape(str(s.get("target", "")))}</span>
</div>"""
            for s in suggestions[:8]
        )
        return f"""<section class="section" id="strategies">
<h2 class="section-title">策略建议</h2>
<div class="sg-grid">{items}</div>
</section>"""

    def _build_camp(self, village_count, wolf_count, winner):
        vpct = round(village_count / max(village_count + wolf_count, 1) * 100)
        return f"""<div class="panel">
<h2>阵营分布</h2>
<div class="camp-ring" style="--vpct:{vpct}%"></div>
<div class="camp-caption">🏘️ Village {village_count} · 🐺 Wolf {wolf_count}</div>
</div>"""

    def _build_suspicion(self, document, name_by_id):
        if not document.suspicion_matrix:
            return ""
        latest = document.suspicion_matrix[-1]["target_scores"]
        items = sorted(latest.items(), key=lambda x: x[1], reverse=True)[:8]
        rows = "".join(
            f"""<div class="row compact">
  <div class="row-head"><span class="name">{escape(name_by_id.get(pid, pid))}</span></div>
  <div class="bar-wrap"><div class="bar suspicion" style="width:{float(v) * 100:.0f}%"></div><span class="bar-value">{float(v):.2f}</span></div>
</div>"""
            for pid, v in items
        )
        return f"""<div class="panel">
<h2>公共怀疑矩阵（最终帧）</h2>
{rows}
</div>"""

    def _build_speech_acts(self, document):
        counts: dict[str, int] = {}
        for item in document.speech_acts:
            counts[item["stance"]] = counts.get(item["stance"], 0) + 1
        chips = (
            "".join(
                f'<div class="speech-chip"><span>{escape(s)}</span><strong>{c}</strong></div>'
                for s, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            )
            or '<div class="speech-chip"><span>—</span><strong>0</strong></div>'
        )
        return f"""<div class="panel">
<h2>Speech Act 画像</h2>
<div class="speech-grid">{chips}</div>
</div>"""

    def _build_validation(self, validation):
        issues = validation.get("issues", [])
        grade = escape(str(validation.get("grade", "-")))
        score = float(validation.get("score", 0))
        publish = "✓ 可发布" if validation.get("publish_allowed") else "⏳ 审核中"
        issue_rows = (
            "".join(
                f"<li><strong>{escape(i.get('gate', ''))}</strong><span>{escape(i.get('message', ''))}</span></li>"
                for i in issues[:6]
            )
            or "<li><strong>PASS</strong><span>无阻塞问题</span></li>"
        )
        return f"""<section class="section" id="validation">
<h2 class="section-title">报告可信度校验</h2>
<div class="val-header">
  <span class="val-grade {"pass" if grade == "pass" else "fail"}">{grade.upper()}</span>
  <span class="val-score">评分 {score:.2f}</span>
  <span class="val-publish">{publish}</span>
</div>
<ul class="clean">{issue_rows}</ul>
</section>"""

    def _build_model_leaderboard(self):
        rows = self._leaderboard_rows("provider")
        if not rows:
            return ""
        items = ""
        for name, total, wolf_wins, village_wins in rows:
            total = total or 1
            wp = round(wolf_wins / total * 100)
            vp = round(village_wins / total * 100)
            items += f"""<div class="lb-row">
  <span class="lb-name">{escape(name)}</span>
  <span class="lb-games">{total}局</span>
  <div class="lb-bar-dual"><span class="lb-wolf" style="width:{wp}%"></span><span class="lb-vill" style="width:{vp}%"></span></div>
  <span class="lb-pct"><span class="lb-wolf-txt">🐺{wp}%</span> <span class="lb-vill-txt">🏘️{vp}%</span></span>
</div>"""
        return f"""<section class="section" id="model-lb">
<h2 class="section-title">模型胜率榜</h2>
<div class="leaderboard">{items}</div>
</section>"""

    def _build_framework_leaderboard(self):
        rows = self._leaderboard_rows("model_name", limit=6)
        if not rows:
            return ""
        items = ""
        for name, total, wolf_wins, village_wins in rows:
            total = total or 1
            wp = round(wolf_wins / total * 100)
            vp = round(village_wins / total * 100)
            items += f"""<div class="lb-row">
  <span class="lb-name">{escape(name[:40])}</span>
  <span class="lb-games">{total}局</span>
  <div class="lb-bar-dual"><span class="lb-wolf" style="width:{wp}%"></span><span class="lb-vill" style="width:{vp}%"></span></div>
  <span class="lb-pct"><span class="lb-wolf-txt">🐺{wp}%</span> <span class="lb-vill-txt">🏘️{vp}%</span></span>
</div>"""
        return f"""<section class="section" id="framework-lb">
<h2 class="section-title">Agent 框架胜率榜</h2>
<div class="leaderboard">{items}</div>
</section>"""

    def _leaderboard_rows(self, group_field: str, *, limit: int | None = None) -> list[tuple[str, int, int, int]]:
        try:
            from backend.db.database import SessionLocal
            from backend.db.models import AgentDecision
            from backend.db.models import Game

            group_column = AgentDecision.provider if group_field == "provider" else AgentDecision.model_name
            db = SessionLocal()
            try:
                rows = (
                    db.query(group_column, Game.id, Game.winner)
                    .join(Game, Game.id == AgentDecision.game_id)
                    .filter(Game.status == "finished")
                    .filter(AgentDecision.provider.in_(("doubao", "deepseek", "dsv4flash", "weapi")))
                    .filter(group_column.isnot(None))
                    .filter(group_column != "")
                    .distinct()
                    .all()
                )
            finally:
                db.close()

            grouped: dict[str, dict[str, int]] = {}
            for raw_name, game_id, winner in rows:
                name = str(raw_name or "unknown")
                if not name:
                    continue
                bucket = grouped.setdefault(name, {"games": 0, "wolf": 0, "village": 0})
                bucket["games"] += 1
                if winner == "wolf":
                    bucket["wolf"] += 1
                elif winner == "village":
                    bucket["village"] += 1

            ranked = sorted(grouped.items(), key=lambda item: (-item[1]["games"], item[0]))
            if limit is not None:
                ranked = ranked[:limit]
            return [(name, stats["games"], stats["wolf"], stats["village"]) for name, stats in ranked]
        except Exception:
            return []

    # ── full HTML template ────────────────────────────────────────

    def _render_full_html(
        self,
        document,
        winner_label,
        game_summary,
        meta_html,
        mvp_html,
        scoreboard_html,
        player_reviews_html,
        turning_html,
        counterfactual_html,
        bad_cases_html,
        strategy_html,
        camp_html,
        suspicion_html,
        speech_html,
        model_lb_html,
        framework_lb_html,
        validation_html,
    ):
        gid = escape(document.game_id)
        created = escape(str(document.created_at))
        published = escape(str(document.published_at or "-"))
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Track B Review · 复盘报告 · {gid[:8]}</title>
<style>
:root{{--bg:#faf7f2;--paper:#fffdf9;--ink:#1f1a17;--muted:#6b6058;--line:#e8ddd0;--accent:#9c5d2c;
  --accent2:#c88448;--danger:#b33a3a;--success:#2d7d55;--gold:#b8801d;--wolf:#c0392b;--village:#2d7d55;
  --shadow:0 8px 32px rgba(71,49,26,.08);--radius:16px;--radius-sm:10px;}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{margin:0;font-family:"Segoe UI","PingFang SC","Hiragino Sans GB",sans-serif;
  background:linear-gradient(180deg,#f5efe4 0%,var(--bg) 40%,#ede4d6 100%);color:var(--ink);padding:24px;-webkit-font-smoothing:antialiased}}
.report{{max-width:1100px;margin:0 auto}}
.report-header{{background:linear-gradient(135deg,#2a1f14 0%,#3d2b1a 40%,#5a3d22 100%);color:#f0e6d8;
  border-radius:var(--radius);padding:32px 36px;margin-bottom:24px;position:relative;overflow:hidden}}
.report-header::before{{content:"";position:absolute;top:-60px;right:-60px;width:240px;height:240px;
  background:radial-gradient(circle,rgba(255,255,255,.06),transparent 70%);border-radius:50%}}
.header-eyebrow{{font-size:11px;letter-spacing:.15em;text-transform:uppercase;opacity:.6;margin-bottom:8px}}
.header-title{{font-size:36px;font-weight:800;line-height:1.15;margin-bottom:10px;position:relative}}
.header-winner{{display:inline-block;font-size:18px;padding:4px 16px;border-radius:99px;
  background:rgba(255,255,255,.12);backdrop-filter:blur(8px);margin-bottom:12px}}
.header-summary{{font-size:14px;opacity:.75;max-width:600px;line-height:1.6}}
.meta-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px;position:relative}}
.meta-card{{background:rgba(255,255,255,.08);border-radius:var(--radius-sm);padding:14px 16px;backdrop-filter:blur(4px)}}
.meta-label{{display:block;font-size:11px;opacity:.5;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}}
.meta-card strong{{font-size:22px;font-weight:700;display:block}}
.meta-card strong.pass{{color:#8fd49e}} .meta-card strong.fail{{color:#f08080}}

.section{{margin-bottom:28px}}
.section-title{{font-size:20px;font-weight:800;margin-bottom:16px;padding-left:14px;border-left:4px solid var(--accent);line-height:1.3}}
.empty{{color:var(--muted);font-style:italic;padding:16px}}

/* MVP */
.mvp-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.mvp-card{{background:linear-gradient(135deg,rgba(255,255,255,.9),rgba(255,248,240,.95));border:1px solid var(--line);
  border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}}
.mvp-type{{font-size:16px;font-weight:700;color:var(--accent);margin-bottom:4px}}
.mvp-name{{font-size:20px;font-weight:800}} .mvp-role{{font-size:14px;color:var(--muted);margin-left:8px}}
.mvp-reason{{color:var(--muted);font-size:14px;margin-top:8px;line-height:1.5}}
.mvp-evidence{{margin-top:10px;padding-left:18px;font-size:13px;color:var(--muted);line-height:1.6}}

/* Scoreboard */
.scoreboard{{display:grid;gap:8px}}
.sb-row{{display:grid;grid-template-columns:40px 1fr 2fr 60px;gap:12px;align-items:center;
  padding:10px 14px;background:rgba(255,255,255,.7);border:1px solid var(--line);border-radius:var(--radius-sm)}}
.sb-medal{{font-size:20px;text-align:center}}
.sb-name{{font-weight:700;font-size:15px}} .sb-meta{{font-size:12px;color:var(--muted)}}
.wolf-side{{color:var(--wolf);font-weight:600}} .village-side{{color:var(--village);font-weight:600}}
.sb-bar-track{{height:10px;border-radius:99px;background:rgba(156,93,44,.1);overflow:hidden}}
.sb-bar{{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),var(--accent2))}}
.sb-score{{font-weight:800;font-size:18px;text-align:right;font-variant-numeric:tabular-nums}}

/* Player Review Cards */
.player-cards{{display:grid;gap:10px}}
.player-card{{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);overflow:hidden;transition:all .2s}}
.player-card[open]{{border-color:var(--accent-soft,var(--accent2))}}
.pc-summary{{display:grid;grid-template-columns:40px 1fr auto 60px 24px;gap:12px;align-items:center;
  padding:14px 18px;cursor:pointer;list-style:none;user-select:none}}
.pc-summary::-webkit-details-marker{{display:none}}
.pc-index{{font-size:13px;color:var(--muted);font-weight:600}}
.pc-name{{font-weight:700;font-size:16px}} .pc-role{{font-size:13px;color:var(--muted)}}
.pc-score-badge{{display:inline-flex;align-items:center;justify-content:center;min-width:54px;padding:4px 10px;
  border-radius:99px;font-weight:800;font-size:15px;
  background:conic-gradient(var(--accent) var(--pct),#eee var(--pct) 100%);color:var(--ink)}}
.pc-chevron{{width:20px;height:20px;color:var(--muted);transition:transform .2s}}
details[open] .pc-chevron{{transform:rotate(180deg)}}
.pc-body{{padding:0 18px 18px;display:grid;gap:14px}}
.pc-overall{{font-size:14px;color:var(--ink);line-height:1.6}}
.pc-score-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.pc-score-item{{background:rgba(156,93,44,.06);border-radius:var(--radius-sm);padding:12px;text-align:center}}
.pc-sl{{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;margin-bottom:4px}}
.pc-score-item strong{{font-size:22px;font-weight:800}}
.pc-speech{{font-size:13px;color:var(--muted);line-height:1.5}}
.pc-score-note{{font-size:12px;color:var(--muted)}}
.pc-col{{margin-top:4px}} .pc-col h4{{font-size:13px;font-weight:700;margin-bottom:6px}}
.pc-col ul{{padding-left:18px;font-size:13px;color:var(--muted);line-height:1.7}}

/* Turning Points */
.tp-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.tp-card{{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px;box-shadow:var(--shadow)}}
.tp-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.tp-day{{font-size:12px;font-weight:700;background:var(--accent);color:#fff;padding:2px 8px;border-radius:99px}}
.tp-title{{font-weight:700;font-size:15px}}
.tp-impact{{font-size:12px;font-weight:800;padding:2px 8px;border-radius:99px}}
.impact-high{{background:#fef2f2;color:var(--danger)}} .impact-mid{{background:#fffbeb;color:var(--gold)}}
.impact-low{{background:#f0fdf4;color:var(--success)}}
.tp-desc{{font-size:13px;color:var(--muted);line-height:1.55}}
.tp-related{{font-size:12px;color:var(--muted);margin-top:6px}}
.tp-evidence{{margin-top:6px;padding-left:16px;font-size:12px;color:var(--muted);line-height:1.5}}

/* Counterfactuals */
.cf-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.cf-card{{background:rgba(255,255,255,.7);border:1px dashed var(--line);border-radius:var(--radius);
  padding:16px}}
.cf-type{{font-size:12px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}}
.cf-desc{{font-size:14px;line-height:1.5;margin-bottom:10px}}
.cf-confidence{{display:flex;align-items:center;gap:8px}}
.cf-bar{{display:inline-block;height:5px;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--accent2))}}
.cf-pct{{font-size:12px;color:var(--muted);white-space:nowrap}}
.cf-compare{{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;margin-top:10px;
  font-size:12px;background:rgba(0,0,0,.02);padding:10px;border-radius:8px}}
.cf-orig{{color:var(--danger)}} .cf-arrow{{color:var(--muted)}} .cf-alt{{color:var(--success)}}

/* Bad Cases */
.bc-grid{{display:grid;gap:10px}}
.bc-card{{background:#fef2f2;border:1px solid #fecaca;border-radius:var(--radius);padding:14px}}
.bc-player{{font-weight:700;font-size:14px}} .bc-severity{{float:right;font-size:11px;color:var(--danger);
  background:#fee2e2;padding:2px 8px;border-radius:99px}}
.bc-desc{{font-size:13px;color:var(--muted);margin-top:6px;line-height:1.5}}

/* Strategy Suggestions */
.sg-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.sg-card{{padding:14px;border-radius:var(--radius-sm);border:1px solid var(--line)}}
.sg-high{{background:linear-gradient(135deg,#fef2f2,rgba(255,255,255,.8));border-color:#fecaca}}
.sg-medium{{background:linear-gradient(135deg,#fffbeb,rgba(255,255,255,.8));border-color:#fde68a}}
.sg-priority{{display:inline-block;font-size:10px;font-weight:700;text-transform:uppercase;
  padding:2px 6px;border-radius:4px;margin-bottom:6px}}
.sg-high .sg-priority{{background:var(--danger);color:#fff}}
.sg-medium .sg-priority{{background:var(--gold);color:#fff}}
.sg-text{{font-size:13px;line-height:1.55}}
.sg-target{{display:block;font-size:11px;color:var(--muted);margin-top:6px}}

/* Side panels */
.side-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:24px}}
.panel{{background:rgba(255,255,255,.7);border:1px solid var(--line);border-radius:var(--radius);
  padding:18px;box-shadow:var(--shadow)}}
.panel h2{{font-size:16px;font-weight:700;margin-bottom:12px}}
.camp-ring{{width:140px;height:140px;margin:0 auto 10px;border-radius:50%;
  background:conic-gradient(var(--village) 0 var(--vpct),var(--wolf) var(--vpct) 100%);display:grid;place-items:center}}
.camp-ring::after{{content:"";width:70px;height:70px;border-radius:50%;background:#fffdf9}}
.camp-caption{{text-align:center;font-size:13px;color:var(--muted)}}
.row.compact{{display:grid;grid-template-columns:100px 1fr;gap:8px;align-items:center;margin-bottom:8px;font-size:13px}}
.row-head .name{{font-weight:600}}
.bar-wrap{{position:relative;height:16px;border-radius:99px;background:rgba(156,93,44,.1);overflow:hidden}}
.bar{{position:absolute;inset:0 auto 0 0;border-radius:inherit;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}}
.bar.suspicion{{background:linear-gradient(90deg,#b55b47,#d79958)}}
.bar-value{{position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:11px;font-weight:700;color:#fff}}
.speech-grid{{display:flex;flex-wrap:wrap;gap:8px}}
.speech-chip{{border:1px solid var(--line);background:rgba(255,255,255,.6);border-radius:99px;
  padding:6px 12px;display:inline-flex;gap:8px;align-items:center;font-size:13px}}
.speech-chip strong{{font-weight:800}}

/* Leaderboard */
.leaderboard{{display:grid;gap:8px}}
.lb-row{{display:grid;grid-template-columns:140px 56px 1fr 120px;gap:10px;align-items:center;
  padding:10px 14px;background:rgba(255,255,255,.7);border:1px solid var(--line);border-radius:var(--radius-sm)}}
.lb-name{{font-weight:700;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.lb-games{{font-size:12px;color:var(--muted)}}
.lb-bar-dual{{display:flex;height:12px;border-radius:99px;overflow:hidden}}
.lb-wolf{{background:var(--wolf);transition:width .3s}}
.lb-vill{{background:var(--village);transition:width .3s}}
.lb-pct{{font-size:12px;text-align:right}}
.lb-wolf-txt{{color:var(--wolf);font-weight:600}} .lb-vill-txt{{color:var(--village);font-weight:600}}

/* Validation */
.val-header{{display:flex;align-items:center;gap:14px;margin-bottom:12px}}
.val-grade{{font-size:18px;font-weight:800;padding:4px 14px;border-radius:99px}}
.val-grade.pass{{background:#dcfce7;color:var(--success)}} .val-grade.fail{{background:#fef2f2;color:var(--danger)}}
.val-score{{font-size:14px;color:var(--muted)}} .val-publish{{font-size:13px;color:var(--muted)}}
ul.clean{{list-style:none;padding:0;display:grid;gap:8px;font-size:13px;color:var(--muted);line-height:1.5}}

.footer{{text-align:center;font-size:12px;color:var(--muted);padding:20px;border-top:1px solid var(--line);margin-top:24px}}

@media(max-width:768px){{
  .meta-grid,.mvp-grid,.tp-grid,.cf-grid,.sg-grid,.side-grid{{grid-template-columns:1fr}}
  .sb-row{{grid-template-columns:32px 1fr 60px}} .sb-bar-track{{display:none}}
  .lb-row{{grid-template-columns:1fr}} .header-title{{font-size:26px}}
}}
</style>
</head>
<body>
<div class="report">
<header class="report-header">
  <div class="header-eyebrow">Track B Review · Post-Game Review</div>
  <h1 class="header-title">AI Werewolf 复盘报告</h1>
  <div class="header-winner">{winner_label}</div>
  <p class="header-summary">{game_summary}</p>
  <div class="meta-grid">{meta_html}</div>
</header>

{mvp_html}
{scoreboard_html}
{player_reviews_html}
{turning_html}
{counterfactual_html}
{bad_cases_html}

<div class="side-grid">{camp_html}{suspicion_html}{speech_html}</div>

{model_lb_html}
{framework_lb_html}
{strategy_html}
{validation_html}

<div class="footer">Generated {created} · Published {published}</div>
</div>
</body>
</html>"""


class ReplayBundleBuilder:
    def build(self, state: GameState) -> ReplayBundle:
        events = [self._event_payload(event) for event in state.events]
        votes = [
            {
                "event_id": event.id,
                "day": event.day,
                "phase": event.phase.value,
                "voter_id": event.payload.get("voter_id"),
                "target_id": event.payload.get("target_id"),
            }
            for event in state.events
            if event.type == EventType.VOTE_CAST
        ]
        deaths = [
            {
                "event_id": event.id,
                "day": event.day,
                "phase": event.phase.value,
                "player_id": event.payload.get("player_id"),
                "reason": event.payload.get("reason"),
            }
            for event in state.events
            if event.type == EventType.PLAYER_DIED
        ]
        return ReplayBundle(
            game_id=state.id,
            rule_pack="wolfcha-default",
            seed=getattr(state, "seed", None),
            players=[
                {
                    "id": player.id,
                    "seat": player.seat,
                    "name": player.name,
                    "role": player.role.value,
                    "alignment": player.alignment.value,
                    "is_ai": player.is_ai,
                    "agent_type": player.agent_type,
                    "model_name": player.model_name,
                    "prompt_version": player.prompt_version,
                    "alive": player.alive,
                    "death_day": player.death_day,
                    "death_reason": player.death_reason,
                    "persona": player.persona,
                }
                for player in state.players
            ],
            events=events,
            decisions=[
                {
                    "decision_id": record.id,
                    "event_id": None,
                    "player_id": record.player_id,
                    "role": state.player(record.player_id).role.value,
                    "camp": state.player(record.player_id).alignment.value,
                    "day": record.day,
                    "phase": str(record.phase),
                    "observation_summary": json.dumps(record.observation, ensure_ascii=False)[:500],
                    "legal_actions": list(record.legal_actions or []),
                    "selected_action": dict(record.parsed_action or {}),
                    "public_reason": (record.parsed_action or {}).get("reasoning"),
                    "private_reason": record.raw_output[:500] if record.raw_output else None,
                    "prompt_version": record.prompt_version,
                    "strategy_version": None,
                    "persona_id": (state.player(record.player_id).persona or {}).get("name"),
                    "model_name": state.player(record.player_id).model_name,
                    "parsed_success": bool(record.is_valid),
                    "fallback_used": bool((record.parsed_action or {}).get("source") == "fallback"),
                    "error_type": record.error_type,
                }
                for record in state.decision_records
            ],
            votes=votes,
            deaths=deaths,
            final_state=state.moderator_dict(),
            winner=state.winner.value if state.winner else None,
            finished_at=_utcnow_iso(),
        )

    def _event_payload(self, event: GameEvent) -> dict[str, Any]:
        payload = dict(event.payload)
        public_text = None
        if event.type == EventType.CHAT_MESSAGE:
            public_text = str(payload.get("speech") or "")
        elif event.type == EventType.VOTE_CAST:
            public_text = f"{payload.get('voter_name', payload.get('voter_id'))} -> {payload.get('target_name', payload.get('target_id'))}"
        elif event.type == EventType.PLAYER_DIED:
            public_text = (
                f"{payload.get('player_name', payload.get('player_id'))} died by {payload.get('reason', 'unknown')}"
            )
        return {
            "event_id": event.id,
            "game_id": payload.get("game_id"),
            "seq": payload.get("seq"),
            "day": event.day,
            "phase": event.phase.value,
            "event_type": event.type.value,
            "actor_id": payload.get("actor_id") or payload.get("voter_id") or payload.get("hunter_id"),
            "target_id": payload.get("target_id"),
            "visibility": event.visibility,
            "visible_to": list(event.visible_to),
            "content": payload,
            "public_text": public_text,
            "decision_id": None,
            "causal_parent_ids": [],
        }


class SpeechActAnalyzer:
    ROLE_CLAIM_PATTERN = re.compile(
        r"(我是|我就是|i am|i'm)\s*(预言家|女巫|猎人|守卫|村民|狼人|seer|witch|hunter|guard|villager|werewolf)", re.I
    )
    CHECK_WOLF_PATTERN = re.compile(r"(查杀|金水|wolf|good)", re.I)

    def analyze(self, state: GameState) -> list[SpeechAct]:
        name_to_id = {player.name: player.id for player in state.players}
        public_events = [event for event in state.events if event.visibility == "public"]
        acts: list[SpeechAct] = []
        for event in public_events:
            if event.type != EventType.CHAT_MESSAGE:
                continue
            actor_id = str(event.payload.get("actor_id") or "")
            actor_name = str(event.payload.get("actor_name") or state.player(actor_id).name)
            speech = str(event.payload.get("speech") or "")
            mentioned_players = [name for name in name_to_id if name and name in speech and name != actor_name]
            suspected_players: list[str] = []
            defended_players: list[str] = []
            claims: list[str] = []
            risk_flags: list[str] = []
            lowered = speech.lower()
            for name in mentioned_players:
                if (
                    any(
                        token in speech
                        for token in [f"投{name}", f"{name}像狼", f"怀疑{name}", f"出{name}", f"{name}有问题"]
                    )
                    or "vote" in lowered
                    or "wolf" in lowered
                ):
                    suspected_players.append(name_to_id[name])
                if (
                    any(
                        token in speech
                        for token in [f"保{name}", f"{name}像好", f"{name}偏好", f"信{name}", f"{name}金水"]
                    )
                    or "good" in lowered
                ):
                    defended_players.append(name_to_id[name])
            if self.ROLE_CLAIM_PATTERN.search(speech):
                claims.append("role_claim")
            if self.CHECK_WOLF_PATTERN.search(speech):
                claims.append("check_result")
            if any(token in speech for token in ["队友", "昨晚刀", "狼队", "private_reason"]):
                risk_flags.append("private_info_leak_risk")
            if any(token in speech for token in ["一定", "必然", "百分百", "100%"]) and "证据" not in speech:
                risk_flags.append("fabrication_risk")
            grounded = self._grounded_event_ids(public_events, event, mentioned_players)
            stance = "neutral"
            if suspected_players:
                stance = "accuse"
            elif defended_players:
                stance = "defend"
            elif claims:
                stance = "claim"
            acts.append(
                SpeechAct(
                    speech_event_id=event.id,
                    player_id=actor_id,
                    player_name=actor_name,
                    day=event.day,
                    phase=event.phase.value,
                    stance=stance,
                    claims=sorted(set(claims)),
                    suspected_players=sorted(set(suspected_players)),
                    defended_players=sorted(set(defended_players)),
                    mentioned_players=mentioned_players,
                    grounded_event_ids=grounded,
                    risk_flags=sorted(set(risk_flags)),
                    evidence_event_ids=[event.id, *grounded][:4],
                    summary=speech[:180],
                )
            )
        return acts

    def _grounded_event_ids(
        self,
        public_events: Iterable[GameEvent],
        current_event: GameEvent,
        mentioned_players: list[str],
    ) -> list[str]:
        grounded: list[str] = []
        for event in public_events:
            if event.id == current_event.id:
                break
            payload = event.payload
            if any(name in json.dumps(payload, ensure_ascii=False) for name in mentioned_players):
                grounded.append(event.id)
        return grounded[-3:]


class SuspicionMatrixBuilder:
    def build(self, state: GameState, speech_acts: list[SpeechAct]) -> list[SuspicionSnapshot]:
        scores = {player.id: 0.5 for player in state.players}
        evidence = {player.id: [] for player in state.players}
        acts_by_event = {act.speech_event_id: act for act in speech_acts}
        snapshots: list[SuspicionSnapshot] = []
        for event in [item for item in state.events if item.visibility == "public"]:
            if event.type == EventType.CHAT_MESSAGE:
                act = acts_by_event.get(event.id)
                if act is not None:
                    for target_id in act.suspected_players:
                        scores[target_id] = min(1.0, scores[target_id] + 0.08)
                        evidence[target_id].append(event.id)
                    for target_id in act.defended_players:
                        if scores.get(target_id, 0.5) >= 0.58:
                            scores[act.player_id] = min(1.0, scores[act.player_id] + 0.05)
                            evidence[act.player_id].append(event.id)
                    if "fabrication_risk" in act.risk_flags:
                        scores[act.player_id] = min(1.0, scores[act.player_id] + 0.12)
                        evidence[act.player_id].append(event.id)
                    if "private_info_leak_risk" in act.risk_flags:
                        scores[act.player_id] = min(1.0, scores[act.player_id] + 0.2)
                        evidence[act.player_id].append(event.id)
            elif event.type == EventType.VOTE_CAST:
                voter_id = str(event.payload.get("voter_id") or "")
                target_id = str(event.payload.get("target_id") or "")
                target_player = state.player(target_id) if target_id else None
                if voter_id and target_player is not None:
                    if target_player.alignment.value == "village":
                        scores[voter_id] = min(1.0, scores[voter_id] + 0.08)
                    else:
                        scores[voter_id] = max(0.0, scores[voter_id] - 0.08)
                    evidence[voter_id].append(event.id)
            snapshots.append(
                SuspicionSnapshot(
                    game_id=state.id,
                    day=event.day,
                    phase=event.phase.value,
                    event_id=event.id,
                    target_scores={player_id: round(value, 4) for player_id, value in scores.items()},
                    evidence_event_ids={player_id: list(ids[-5:]) for player_id, ids in evidence.items()},
                )
            )
        return snapshots


class TrackBValidator:
    def validate(
        self,
        *,
        report_id: str,
        game_id: str,
        replay_bundle: ReplayBundle,
        review_report: dict[str, Any],
        markdown: str,
        speech_acts: list[SpeechAct],
        suspicion_matrix: list[SuspicionSnapshot],
        view_scope: str,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        issues.extend(self._schema_validity(report_id, review_report))
        issues.extend(self._report_completeness(markdown, review_report))
        issues.extend(self._evidence_coverage(review_report))
        issues.extend(self._fact_consistency(replay_bundle, review_report, speech_acts, suspicion_matrix))
        issues.extend(self._score_consistency(review_report, markdown))
        issues.extend(self._counterfactual_soundness(replay_bundle, review_report))
        issues.extend(self._visibility_safety(review_report, markdown, view_scope))
        issues.extend(self._recommendation_grounding(review_report))
        issues.extend(self._agent_robustness(replay_bundle))
        issues.extend(self._presentation_quality(markdown))

        blocking = [item for item in issues if item.blocking]
        if blocking:
            grade = "reject"
        elif issues:
            grade = "needs_revision"
        else:
            grade = "pass"
        passed = not issues
        score = _clamp_score(1.0 - 0.08 * len(issues) - 0.1 * len(blocking))
        return ValidationResult(
            report_id=report_id,
            game_id=game_id,
            passed=passed,
            grade=grade,
            score=score,
            issues=issues,
            required_tools=sorted({item.repair_tool for item in issues if item.repair_tool}),
            revision_instructions=[item.required_fix for item in issues],
            publish_allowed=passed,
        )

    def _schema_validity(self, report_id: str, review_report: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        required = [
            "game_id",
            "scoreboard",
            "mvp_results",
            "turning_points",
            "player_reviews",
            "bad_cases",
            "counterfactuals",
            "strategy_suggestions",
            "metadata",
        ]
        for field_name in required:
            if field_name not in review_report:
                issues.append(
                    self._issue(
                        "SchemaValidityGate",
                        "critical",
                        "missing_field",
                        {"field": field_name},
                        f"报告缺少字段 {field_name}",
                        [],
                        f"补齐字段 {field_name}",
                        "ReplayQueryTool",
                    )
                )
        if not isinstance(review_report.get("scoreboard", []), list):
            issues.append(
                self._issue(
                    "SchemaValidityGate",
                    "critical",
                    "bad_type",
                    {"field": "scoreboard"},
                    "scoreboard 必须是列表",
                    [],
                    "重建 scoreboard",
                    "ScoreRecomputeTool",
                )
            )
        if review_report.get("game_id") and review_report.get("game_id") != report_id.split(":")[-1]:
            pass
        return issues

    def _agent_robustness(self, replay_bundle: ReplayBundle) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        fallback_decisions: list[str] = []
        invalid_decisions: list[str] = []
        for decision in replay_bundle.decisions:
            selected = decision.get("selected_action") or {}
            metadata = selected.get("metadata") if isinstance(selected, dict) else {}
            fallback_used = bool(decision.get("fallback_used")) or bool((metadata or {}).get("fallback"))
            if fallback_used:
                fallback_decisions.append(str(decision.get("decision_id") or decision.get("player_id") or "unknown"))
            if decision.get("parsed_success") is False:
                invalid_decisions.append(str(decision.get("decision_id") or decision.get("player_id") or "unknown"))
        if fallback_decisions:
            issues.append(
                self._issue(
                    "AgentRobustnessGate",
                    "critical",
                    "fallback_used",
                    {"decision_ids": fallback_decisions[:10], "count": len(fallback_decisions)},
                    "对局包含 fallback 决策，不能作为高质量 LLM/策略验收样本发布。",
                    fallback_decisions[:10],
                    "重新运行对局或修复 LLM 输出解析，确保所有 AgentDecision 由目标 agent 有效产生。",
                    "ReplayQueryTool",
                )
            )
        if invalid_decisions:
            issues.append(
                self._issue(
                    "AgentRobustnessGate",
                    "critical",
                    "invalid_decision",
                    {"decision_ids": invalid_decisions[:10], "count": len(invalid_decisions)},
                    "对局包含非法或解析失败决策，不能发布为 ApprovedReviewReport。",
                    invalid_decisions[:10],
                    "修复 ActionValidator / Agent 输出后重新生成复盘。",
                    "ReplayQueryTool",
                )
            )
        return issues

    def _report_completeness(self, markdown: str, review_report: dict[str, Any]) -> list[ValidationIssue]:
        required_sections = [
            "# 本局复盘报告",
            "## 1. 本局概览",
            "## 2. MVP",
            "## 3. 玩家评分榜",
            "## 4. 关键转折点",
            "## 5. 反事实推演",
            "## 6. 玩家逐个复盘",
            "## 7. 关键失误",
            "## 8. 策略建议",
            "## 10. 报告可信度校验",
        ]
        issues: list[ValidationIssue] = []
        for section in required_sections:
            if section not in markdown:
                issues.append(
                    self._issue(
                        "ReportCompletenessGate",
                        "major",
                        "missing_section",
                        {"section": section},
                        f"Markdown 缺少章节 {section}",
                        [],
                        f"补全章节 {section}",
                        "ScoreTableRenderer",
                    )
                )
        if not review_report.get("turning_points"):
            issues.append(
                self._issue(
                    "ReportCompletenessGate",
                    "major",
                    "missing_highlight",
                    {"section": "turning_points"},
                    "报告没有关键高光/转折点",
                    [],
                    "补充高光或转折点",
                    "EvidenceResolveTool",
                )
            )
        return issues

    def _evidence_coverage(self, review_report: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for section_name in ["mvp_results", "turning_points", "bad_cases", "counterfactuals", "strategy_suggestions"]:
            for index, item in enumerate(review_report.get(section_name, [])):
                evidence = item.get("evidence_event_ids") or item.get("evidence") or item.get("grounded_event_ids")
                if not evidence:
                    issues.append(
                        self._issue(
                            "EvidenceCoverageGate",
                            "critical",
                            "missing_evidence",
                            {"section": section_name, "index": index},
                            f"{section_name}[{index}] 缺少 evidence_event_ids",
                            [],
                            "补齐证据链",
                            "EvidenceResolveTool",
                        )
                    )
        return issues

    def _fact_consistency(
        self,
        replay_bundle: ReplayBundle,
        review_report: dict[str, Any],
        speech_acts: list[SpeechAct],
        suspicion_matrix: list[SuspicionSnapshot],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        event_ids = {event["event_id"] for event in replay_bundle.events}
        for section_name in ["mvp_results", "turning_points", "bad_cases", "counterfactuals", "strategy_suggestions"]:
            for index, item in enumerate(review_report.get(section_name, [])):
                for evidence_id in item.get("evidence_event_ids", []):
                    if evidence_id not in event_ids:
                        issues.append(
                            self._issue(
                                "FactConsistencyGate",
                                "critical",
                                "unknown_event",
                                {"section": section_name, "index": index},
                                f"{section_name}[{index}] 引用了不存在的事件 {evidence_id}",
                                [evidence_id],
                                "重查事实证据",
                                "ReplayQueryTool",
                            )
                        )
        if not speech_acts:
            issues.append(
                self._issue(
                    "FactConsistencyGate",
                    "major",
                    "missing_speech_acts",
                    {"section": "speech_acts"},
                    "缺少 SpeechAct 分析结果",
                    [],
                    "生成 SpeechAct 分析",
                    "SpeechActRecheckTool",
                )
            )
        if not suspicion_matrix:
            issues.append(
                self._issue(
                    "FactConsistencyGate",
                    "major",
                    "missing_suspicion_matrix",
                    {"section": "suspicion_matrix"},
                    "缺少 SuspicionMatrix",
                    [],
                    "重建公共怀疑矩阵",
                    "ReplayQueryTool",
                )
            )
        return issues

    def _score_consistency(self, review_report: dict[str, Any], markdown: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        player_scores = {item["player_id"]: item for item in review_report.get("metadata", {}).get("player_scores", [])}
        for entry in review_report.get("scoreboard", []):
            score_payload = player_scores.get(entry.get("player_id"))
            if score_payload is None:
                issues.append(
                    self._issue(
                        "ScoreConsistencyGate",
                        "critical",
                        "missing_player_score",
                        {"player_id": entry.get("player_id")},
                        f"{entry.get('player_name')} 缺少 player_scores 来源",
                        [],
                        "补齐 player_scores",
                        "ScoreRecomputeTool",
                    )
                )
                continue
            expected = round(
                float(score_payload.get("adjusted_final_score") or score_payload.get("final_score") or 0.0), 2
            )
            actual = round(float(entry.get("adjusted_final_score") or 0.0), 2)
            if expected != actual:
                issues.append(
                    self._issue(
                        "ScoreConsistencyGate",
                        "critical",
                        "score_mismatch",
                        {"player_id": entry.get("player_id")},
                        f"{entry.get('player_name')} 的最终分与底层 player_scores 不一致",
                        [],
                        "重算 scoreboard",
                        "ScoreRecomputeTool",
                    )
                )
            if str(actual) not in markdown:
                issues.append(
                    self._issue(
                        "ScoreConsistencyGate",
                        "major",
                        "markdown_score_mismatch",
                        {"player_id": entry.get("player_id")},
                        f"Markdown 未展示 {entry.get('player_name')} 的最终分 {actual}",
                        [],
                        "重绘分数表",
                        "ScoreTableRenderer",
                    )
                )
        return issues

    def _counterfactual_soundness(
        self, replay_bundle: ReplayBundle, review_report: dict[str, Any]
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        vote_events = list(replay_bundle.votes)
        grouped_votes: dict[int, list[dict[str, Any]]] = {}
        for vote in vote_events:
            grouped_votes.setdefault(int(vote["day"]), []).append(vote)
        for index, item in enumerate(review_report.get("counterfactuals", [])):
            cf_type = item.get("counterfactual_type")
            effect_type = item.get("effect_type", "estimated")
            recomputed = item.get("recomputed_outcome") or {}
            if cf_type == "vote":
                day = int(item.get("day") or 0)
                evidence_ids = set(item.get("evidence_event_ids", []))
                if day not in grouped_votes or not evidence_ids:
                    issues.append(
                        self._issue(
                            "CounterfactualSoundnessGate",
                            "major",
                            "invalid_vote_cf",
                            {"index": index},
                            "vote_flip 反事实缺少原始票型依据",
                            list(evidence_ids),
                            "补齐投票证据并重算",
                            "CounterfactualRecomputeTool",
                        )
                    )
                # B §21 vote_flip must declare exact_recalculation and present a recomputed tally.
                if effect_type != "exact_recalculation":
                    issues.append(
                        self._issue(
                            "CounterfactualSoundnessGate",
                            "major",
                            "vote_cf_wrong_effect_type",
                            {"index": index, "effect_type": effect_type},
                            "vote_flip 反事实必须标记 effect_type=exact_recalculation",
                            [],
                            "在 CounterfactualCase 上补 effect_type=exact_recalculation",
                            "CounterfactualRecomputeTool",
                        )
                    )
                if "new_tally" not in recomputed and "tally_unchanged" not in recomputed:
                    issues.append(
                        self._issue(
                            "CounterfactualSoundnessGate",
                            "major",
                            "vote_cf_no_recompute",
                            {"index": index},
                            "vote_flip 反事实未给出重算后的票型 (new_tally / tally_unchanged)",
                            [],
                            "调用 _recompute_vote_flip 写入 recomputed_outcome",
                            "CounterfactualRecomputeTool",
                        )
                    )
            if cf_type == "skill":
                if effect_type != "local_recalculation":
                    issues.append(
                        self._issue(
                            "CounterfactualSoundnessGate",
                            "major",
                            "skill_cf_wrong_effect_type",
                            {"index": index, "effect_type": effect_type},
                            "skill 反事实必须标记 effect_type=local_recalculation",
                            [],
                            "在 CounterfactualCase 上补 effect_type=local_recalculation",
                            "CounterfactualRecomputeTool",
                        )
                    )
            if cf_type == "info_release":
                expected = str(item.get("expected_effect") or "")
                if any(token in expected for token in ["一定", "必然", "稳胜", "100%"]):
                    issues.append(
                        self._issue(
                            "CounterfactualSoundnessGate",
                            "major",
                            "deterministic_info_cf",
                            {"index": index},
                            "信息释放反事实不能写成必然结果",
                            item.get("evidence_event_ids", []),
                            "将结论改成 estimated 语气",
                            "CounterfactualRecomputeTool",
                        )
                    )
                if effect_type != "estimated":
                    issues.append(
                        self._issue(
                            "CounterfactualSoundnessGate",
                            "major",
                            "info_cf_wrong_effect_type",
                            {"index": index, "effect_type": effect_type},
                            "info_release 反事实必须标记 effect_type=estimated",
                            [],
                            "在 CounterfactualCase 上补 effect_type=estimated",
                            "CounterfactualRecomputeTool",
                        )
                    )
        return issues

    def _visibility_safety(
        self, review_report: dict[str, Any], markdown: str, view_scope: str
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if view_scope == "moderator_view":
            return issues
        leaked_tokens = ["private_reason", "狼队友", "昨晚刀口", "未公开查验"]
        for token in leaked_tokens:
            if token in markdown:
                issues.append(
                    self._issue(
                        "VisibilitySafetyGate",
                        "critical",
                        "private_leak",
                        {"token": token},
                        f"公开报告泄露了私有信息：{token}",
                        [],
                        "移除私有信息",
                        "VisibilityCheckTool",
                    )
                )
        for review in review_report.get("player_reviews", []):
            if "private_reason" in json.dumps(review, ensure_ascii=False):
                issues.append(
                    self._issue(
                        "VisibilitySafetyGate",
                        "critical",
                        "private_leak",
                        {"player_id": review.get("player_id")},
                        "player review 泄露了 private_reason",
                        [],
                        "去除私有字段",
                        "VisibilityCheckTool",
                    )
                )
        return issues

    def _recommendation_grounding(self, review_report: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for index, item in enumerate(review_report.get("strategy_suggestions", [])):
            if not item.get("evidence_event_ids"):
                issues.append(
                    self._issue(
                        "RecommendationGroundingGate",
                        "major",
                        "ungrounded_suggestion",
                        {"index": index},
                        "策略建议缺少来源证据",
                        [],
                        "为策略建议补充 evidence_event_ids",
                        "EvidenceResolveTool",
                    )
                )
        return issues

    def _presentation_quality(self, markdown: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if any(token in markdown for token in ["global_mvp", "winning_camp_mvp", "DAY_SPEECH", '"scoreboard"']):
            issues.append(
                self._issue(
                    "PresentationQualityGate",
                    "major",
                    "debug_token",
                    {},
                    "Markdown 仍包含英文枚举或调试字段",
                    [],
                    "转成中文展示并移除调试字段",
                    "ScoreTableRenderer",
                )
            )
        return issues

    def _issue(
        self,
        gate: str,
        severity: str,
        issue_type: str,
        location: dict[str, Any],
        message: str,
        evidence: list[str],
        required_fix: str,
        repair_tool: str | None,
    ) -> ValidationIssue:
        return ValidationIssue(
            issue_id=str(uuid4()),
            severity=severity,
            gate=gate,
            issue_type=issue_type,
            location=location,
            message=message,
            evidence=list(evidence),
            required_fix=required_fix,
            repair_tool=repair_tool,
            blocking=severity == "critical",
        )


class ReviewRepairLoop:
    def run(
        self,
        *,
        replay_bundle: ReplayBundle,
        review_report: dict[str, Any],
        markdown: str,
        speech_acts: list[SpeechAct],
        suspicion_matrix: list[SuspicionSnapshot],
        validator: TrackBValidator,
        view_scope: str,
        max_rounds: int = 3,
    ) -> tuple[dict[str, Any], str, ValidationResult, list[dict[str, Any]]]:
        repair_history: list[dict[str, Any]] = []
        # Pre-pass: always backfill evidence_event_ids so downstream consumers
        # (KnowledgeExtractor, frontend dashboards) never see an unattributed
        # claim. The operation is idempotent — items that already have
        # evidence are left alone — and matches Track B §12 "every conclusion
        # must carry evidence".
        review_report = self._repair_evidence(review_report, replay_bundle)
        validation = validator.validate(
            report_id=f"review:{replay_bundle.game_id}",
            game_id=replay_bundle.game_id,
            replay_bundle=replay_bundle,
            review_report=review_report,
            markdown=markdown,
            speech_acts=speech_acts,
            suspicion_matrix=suspicion_matrix,
            view_scope=view_scope,
        )
        for round_no in range(1, max_rounds + 1):
            if validation.passed:
                break
            before = len(validation.issues)
            review_report = self._repair_evidence(review_report, replay_bundle)
            markdown = self._repair_markdown(markdown, review_report)
            validation = validator.validate(
                report_id=f"review:{replay_bundle.game_id}",
                game_id=replay_bundle.game_id,
                replay_bundle=replay_bundle,
                review_report=review_report,
                markdown=markdown,
                speech_acts=speech_acts,
                suspicion_matrix=suspicion_matrix,
                view_scope=view_scope,
            )
            repair_history.append(
                {
                    "round": round_no,
                    "issues_before": before,
                    "issues_after": len(validation.issues),
                    "grade_after": validation.grade,
                }
            )
        return review_report, markdown, validation, repair_history

    def _repair_evidence(self, review_report: dict[str, Any], replay_bundle: ReplayBundle) -> dict[str, Any]:
        players_by_name = {player["name"]: player["id"] for player in replay_bundle.players}
        vote_events = [event for event in replay_bundle.events if event["event_type"] == EventType.VOTE_CAST.value]
        speech_events = [event for event in replay_bundle.events if event["event_type"] == EventType.CHAT_MESSAGE.value]
        action_events = [
            event
            for event in replay_bundle.events
            if event["event_type"] in {EventType.NIGHT_ACTION.value, EventType.HUNTER_SHOT.value}
        ]
        death_events = [event for event in replay_bundle.events if event["event_type"] == EventType.PLAYER_DIED.value]

        def actor_events(
            player_name: str, day: int | None = None, sources: list[dict[str, Any]] | None = None
        ) -> list[str]:
            player_id = players_by_name.get(player_name)
            if not player_id:
                return []
            pool = sources or replay_bundle.events
            return [
                event["event_id"]
                for event in pool
                if event.get("actor_id") == player_id and (day is None or int(event.get("day") or 0) == int(day))
            ]

        for case in review_report.get("bad_cases", []):
            if case.get("evidence_event_ids"):
                continue
            player_name = case.get("player_name", "")
            day = case.get("day")
            mistake_type = str(case.get("mistake_type") or "")
            if "vote" in mistake_type:
                case["evidence_event_ids"] = actor_events(player_name, day, vote_events)[:3]
                if not case["evidence_event_ids"]:
                    case["evidence_event_ids"] = actor_events(player_name, None, vote_events)[-3:]
            elif any(token in mistake_type for token in ["ability", "poison", "shoot", "save", "check"]):
                case["evidence_event_ids"] = actor_events(player_name, day, action_events)[:3]
                if not case["evidence_event_ids"]:
                    case["evidence_event_ids"] = actor_events(player_name, None, action_events)[-3:]
            elif "speech" in mistake_type or "leak" in mistake_type or "fabric" in mistake_type:
                case["evidence_event_ids"] = actor_events(player_name, day, speech_events)[:3]
                if not case["evidence_event_ids"]:
                    case["evidence_event_ids"] = actor_events(player_name, None, speech_events)[-3:]
            else:
                case["evidence_event_ids"] = (
                    actor_events(player_name, day) + actor_events(player_name, day, death_events)
                )[:3]
            if not case["evidence_event_ids"]:
                case["evidence_event_ids"] = actor_events(player_name)[-3:]

        for item in review_report.get("turning_points", []):
            if item.get("evidence_event_ids"):
                continue
            item["evidence_event_ids"] = self._evidence_from_names_and_day(item, replay_bundle)

        for item in review_report.get("mvp_results", []):
            if item.get("evidence_event_ids"):
                continue
            item["evidence_event_ids"] = self._evidence_from_names_and_day(item, replay_bundle)

        for item in review_report.get("counterfactuals", []):
            if item.get("evidence_event_ids"):
                continue
            day = item.get("day")
            affected = item.get("affected_players") or []
            if item.get("counterfactual_type") == "vote":
                item["evidence_event_ids"] = [
                    event["event_id"] for event in vote_events if int(event.get("day") or 0) == int(day or 0)
                ][:5]
            else:
                names = [name for name in affected if isinstance(name, str)]
                item["evidence_event_ids"] = self._evidence_from_names_and_day(
                    {"related_players": names, "day": day}, replay_bundle
                )

        for item in review_report.get("strategy_suggestions", []):
            if item.get("evidence_event_ids"):
                continue
            target = item.get("target")
            player_name = target if item.get("target_type") == "player" else ""
            if player_name:
                item["evidence_event_ids"] = actor_events(player_name)[:3]
            else:
                item["evidence_event_ids"] = [event["event_id"] for event in speech_events[:2]] or [
                    event["event_id"] for event in vote_events[:2]
                ]
        return review_report

    def _repair_markdown(self, markdown: str, review_report: dict[str, Any]) -> str:
        base = markdown.split("## 10. 报告可信度校验", 1)[0].rstrip()
        if "## 4. 关键转折点" not in base and review_report.get("turning_points"):
            base += "\n\n## 4. 关键转折点\n- 已从结构化报告补回关键转折点。"
        return _append_validation_section(base, None)

    def _evidence_from_names_and_day(self, item: dict[str, Any], replay_bundle: ReplayBundle) -> list[str]:
        day = item.get("day")
        names = set(item.get("related_players") or [])
        for key in ["player_name", "target", "display_name"]:
            value = item.get(key)
            if isinstance(value, str) and value:
                names.add(value)
        if not names:
            return [
                event["event_id"]
                for event in replay_bundle.events
                if day is None or int(event.get("day") or 0) == int(day or 0)
            ][:3]
        matched: list[str] = []
        for event in replay_bundle.events:
            if day is not None and int(event.get("day") or 0) != int(day):
                continue
            blob = json.dumps(event.get("content") or {}, ensure_ascii=False)
            if any(name in blob for name in names):
                matched.append(event["event_id"])
        return matched[:4]


def _append_validation_section(markdown: str, validation: ValidationResult | None) -> str:
    lines = [markdown.rstrip(), "", "## 10. 报告可信度校验"]
    if validation is None:
        lines.append("- 状态：待校验")
        lines.append("- 备注：报告生成后会执行多门校验与修复循环。")
    else:
        status = "通过" if validation.passed else "未通过"
        lines.append(f"- 状态：{status}")
        lines.append(f"- 等级：{validation.grade}")
        lines.append(f"- 分数：{validation.score:.2f}")
        lines.append(f"- 可发布：{'是' if validation.publish_allowed else '否'}")
        if validation.issues:
            lines.append("- 关键问题：")
            for issue in validation.issues[:8]:
                lines.append(f"  - [{issue.gate}] {issue.message}")
        else:
            lines.append("- 关键问题：无")
    return "\n".join(lines)


def _build_leaderboard_snapshot(review_report: dict[str, Any]) -> dict[str, Any]:
    aggregator = LeaderboardAggregator()
    result = aggregator.aggregate_all([ReviewReport(**review_report)])
    return {key: value.to_dict() for key, value in result.items()}


def _record_knowledge_usage(state: GameState, review_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Track C §20 feedback loop. For each AgentDecision that retrieved
    knowledge docs (recorded via retrieved_knowledge_ids), look up whether
    that player got tagged in a BadCase on the same day; mark the knowledge
    helpful if not, otherwise mark it as failure. This is what eventually
    lets DreamJob deprecate consistently-unhelpful docs."""
    bad_case_player_days: set[tuple[str, int]] = set()
    for case in review_report.get("bad_cases", []):
        player_name = case.get("player_name") or ""
        day = case.get("day")
        if player_name and day is not None:
            bad_case_player_days.add((player_name, int(day)))
    feedback: list[dict[str, Any]] = []
    try:
        from backend.db.persist import record_knowledge_usage
    except Exception:
        record_knowledge_usage = None  # type: ignore
    player_name_by_id = {p.id: p.name for p in state.players}
    for record in state.decision_records:
        parsed = record.parsed_action or {}
        doc_ids = list(parsed.get("retrieved_knowledge_ids") or [])
        if not doc_ids:
            continue
        player_name = player_name_by_id.get(record.player_id, "")
        helpful = (player_name, int(record.day)) not in bad_case_player_days
        for doc_id in doc_ids:
            feedback.append(
                {
                    "doc_id": doc_id,
                    "player_id": record.player_id,
                    "day": record.day,
                    "phase": record.phase,
                    "helpful": helpful,
                }
            )
            if record_knowledge_usage is not None:
                try:
                    record_knowledge_usage(
                        {
                            "game_id": state.id,
                            "decision_id": record.id,
                            "player_id": record.player_id,
                            "knowledge_doc_id": doc_id,
                            "retrieved": True,
                            "used": True,
                            "decision_outcome": "good" if helpful else "bad",
                            "helpful": helpful,
                            "metadata": {"day": record.day, "phase": record.phase},
                        }
                    )
                except Exception:
                    # Persistence is best-effort; an in-memory store still
                    # has the truth in the feedback list above.
                    pass
    return feedback


def _compute_per_step_scores(
    state: GameState,
    replay_bundle: ReplayBundle,
    speech_acts: list[SpeechAct],
    *,
    llm_client: Any = None,
    cascade: bool = False,
) -> list[dict[str, Any]]:
    """Compute per-step decision scores with optional three-tier cascade.

    Tier 1 (deterministic): Always runs — hard rules for all decisions. Free, instant.
    Tier 2 (light LLM):    Activates when cascade=True + llm_client is set.
                            Single-judge LLM for ambiguous decisions (~12% of total).
    Tier 3 (heavy LLM):    3-judge panel for high-impact + ambiguous (~3% of total).

    Args:
        state: Full game state.
        replay_bundle: Replay data including decisions.
        speech_acts: Analyzed speech acts.
        llm_client: Optional LLM client for Tier 2/3 scoring.
        cascade: If True and llm_client is provided, run the three-tier cascade.
    """
    from backend.eval.per_step_scorer import PerStepScorer

    scorer = PerStepScorer(llm_client=llm_client)
    players = {p.id: p for p in state.players}
    state_dict = {
        "players": [
            {
                "id": p.id,
                "name": p.name,
                "role": p.role.value if hasattr(p.role, "value") else str(p.role),
                "alignment": p.alignment.value if hasattr(p.alignment, "value") else str(p.alignment),
                "alive": p.alive,
            }
            for p in state.players
        ],
    }
    acts_dicts = [
        {
            "player_id": a.player_id,
            "day": a.day,
            "stance": a.stance,
            "suspected_players": a.suspected_players,
            "defended_players": a.defended_players,
            "grounded_event_ids": a.grounded_event_ids,
            "risk_flags": a.risk_flags,
        }
        for a in speech_acts
    ]

    # Build decision dicts for score_all (standard format)
    decision_dicts = []
    for decision in replay_bundle.decisions or []:
        pa = decision.get("selected_action") or {}
        player_id = decision.get("player_id", "")
        player = players.get(player_id)
        if player is None:
            continue
        decision_dicts.append(
            {
                "id": decision.get("decision_id", ""),
                "player_id": player_id,
                "player_name": player.name,
                "player_role": player.role.value if hasattr(player.role, "value") else str(player.role),
                "day": decision.get("day", 0),
                "phase": decision.get("phase", ""),
                "target_id": pa.get("target_id", ""),
                "action_type": pa.get("action_type", ""),
                "raw_text": str(pa.get("reasoning", "") or ""),
            }
        )

    # Run cascade scoring
    if cascade and llm_client is not None:
        scores = scorer.score_all(decision_dicts, state_dict, acts_dicts, light_llm=True, heavy_llm=True)
        tier_counts = scorer.tally_tiers(scores)
        import logging

        logging.getLogger(__name__).info(f"Per-step cascade complete: {tier_counts}")
    else:
        scores = scorer.score_all(decision_dicts, state_dict, acts_dicts)

    return [
        {
            "decision_id": s.decision_id,
            "player_name": s.player_name,
            "role": s.role,
            "day": s.day,
            "phase": s.phase,
            "action_type": s.action_type,
            "correctness": s.correctness,
            "overall_score": s.overall_score,
            "evidence": s.evidence,
            "scoring_tier": s.scoring_tier,
            "light_llm_score": s.light_llm_score,
            "heavy_llm_score": s.heavy_llm_score,
            "metadata": s.metadata,
        }
        for s in scores
    ]


def _extract_and_store_knowledge(
    state: GameState,
    per_step_scores: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> int:
    """Extract Track C knowledge from Track B enriched per-step scores.

    Converts Track B's per-step score dicts into ScoredStep objects, groups by
    player into PlayerReviewReports, calls KnowledgeAbstractor, and persists
    lessons to PostgreSQL.

    Returns number of lessons stored (0 if skipped or failed).
    """
    try:
        from collections import defaultdict

        import psycopg2

        from backend.db.database import DEFAULT_DB_URL
        from backend.eval.knowledge_abstractor import KnowledgeAbstractor
        from backend.eval.knowledge_abstractor import store_lessons_to_db
        from backend.eval.per_step_scorer import PlayerReviewReport
        from backend.eval.per_step_scorer import ScoredStep

        if not DEFAULT_DB_URL.startswith(("postgres://", "postgresql://")):
            return 0

        # 1. Check if Track B already extracted knowledge for this game
        conn = psycopg2.connect(DEFAULT_DB_URL)
        c = conn.cursor()
        import json as _track_c_json

        c.execute(
            "SELECT COUNT(*) FROM strategy_knowledge_docs WHERE source_report_ids @> %s::jsonb",
            (_track_c_json.dumps([state.id]),),
        )
        existing = c.fetchone()[0]
        c.close()
        conn.close()
        if existing > 0:
            import logging

            logging.getLogger(__name__).info(
                f"Knowledge already extracted for game {state.id} ({existing} lessons), skipping"
            )
            return existing

        # 2. Build lookup: decision_id → decision dict (for raw_text, player_id)
        decision_lookup: dict[str, dict] = {}
        for dec in decisions:
            did = dec.get("decision_id", "")
            if did:
                decision_lookup[did] = dec

        # 3. Build ScoredStep objects from per_step_scores + decision lookup
        by_player: dict[str, list[ScoredStep]] = defaultdict(list)
        players = {p.id: p for p in state.players}

        for ps in per_step_scores:
            did = ps.get("decision_id", "")
            dec = decision_lookup.get(did, {})
            pid = dec.get("player_id", "")
            if not pid:
                continue
            phase = str(ps.get("phase", ""))
            step_type = _phase_to_step_type(phase)
            role = str(ps.get("role", ""))
            score = float(ps.get("overall_score", 0.5))
            correctness = float(ps.get("correctness", 0.5))

            # Get action_summary from decision's selected_action
            selected = dec.get("selected_action") or {}
            raw_text = str(selected.get("reasoning") or dec.get("public_reason") or "")[:200]
            action_summary = raw_text[:200] if raw_text else f"{role} {step_type} on D{ps.get('day', 0)}"

            evidence = ps.get("evidence") or []
            lesson_abstract = str(evidence[0]) if evidence else ""

            # Infer mistake_type
            mistake_type = ""
            if score <= 0.30:
                if correctness < 0.2 and "VOTE" in phase:
                    mistake_type = "wrong_vote"
                elif correctness < 0.3 and ("SPEECH" in phase or "TALK" in phase) and len(raw_text) < 30:
                    mistake_type = "empty_speech"
                elif correctness < 0.3 and "NIGHT" in phase:
                    mistake_type = "bad_target"
                elif correctness < 0.3:
                    mistake_type = "bad_decision"

            by_player[pid].append(
                ScoredStep(
                    step_id=did,
                    step_type=step_type,
                    day=int(ps.get("day", 0)),
                    phase=phase,
                    role=role,
                    step_score=score,
                    scoring_tier=str(ps.get("scoring_tier", "deterministic")),
                    action_summary=action_summary,
                    is_highlight=(score >= 0.75),
                    is_mistake=(score <= 0.30),
                    mistake_type=mistake_type,
                    lesson_abstract=lesson_abstract,
                    lesson_tags=[role, step_type],
                    evidence_event_ids=[did],
                )
            )

        # 4. Build PlayerReviewReports
        reviews: list[PlayerReviewReport] = []
        for pid, steps in by_player.items():
            player = players.get(pid)
            persona = (player.persona or {}) if player else {}
            reviews.append(
                PlayerReviewReport(
                    game_id=state.id,
                    player_id=pid,
                    role=steps[0].role if steps else "",
                    persona_style=str(persona.get("style_label", "") or ""),
                    persona_mbti=str(persona.get("mbti", "") or ""),
                    scored_steps=steps,
                )
            )

        # 5. Run KnowledgeAbstractor
        abstractor = KnowledgeAbstractor()
        by_role_lessons = abstractor.abstract_from_game(reviews)
        all_lessons = []
        for lessons in by_role_lessons.values():
            all_lessons.extend(lessons)

        if not all_lessons:
            return 0

        # 6. Store lessons
        stored = store_lessons_to_db(all_lessons)
        import logging

        logging.getLogger(__name__).info(f"Track B→C: {stored} knowledge lessons extracted for game {state.id}")
        return stored

    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            f"Knowledge extraction from Track B scores failed (non-fatal): {e}", exc_info=True
        )
        return 0


def _phase_to_step_type(phase: str) -> str:
    """Map phase string to step_type: speech | vote | night_action."""
    if "SPEECH" in phase or "TALK" in phase or "LAST_WORDS" in phase:
        return "speech"
    if "VOTE" in phase or "BADGE" in phase:
        return "vote"
    return "night_action"


def _compute_llm_game_scores(
    state: GameState,
    replay_bundle: ReplayBundle,
    llm_client: Any,
) -> list[dict[str, Any]] | None:
    """Run full LLM Judge Panel (3-judge + Critic round) for game-level scoring.

    This is the heaviest scoring tier — 3 specialized judges independently score
    each player on strategy, logic, and social dimensions, then a Critic round
    challenges extreme scores, followed by trimmed-mean aggregation.

    Args:
        state: Full game state.
        replay_bundle: Replay data including decisions.
        llm_client: LLM client (must support chat_sync).

    Returns:
        List of GameLevelScore dicts, or None on failure.
    """
    try:
        from backend.eval.llm_judge import LLMJudgePanel

        panel = LLMJudgePanel(llm_client)

        # Build game_state dict for the judge panel
        game_state_dict = {
            "winner": str(state.winner or "unknown"),
            "players": [
                {
                    "name": p.name,
                    "role": p.role.value if hasattr(p.role, "value") else str(p.role),
                    "alignment": p.alignment.value if hasattr(p.alignment, "value") else str(p.alignment),
                }
                for p in state.players
            ],
            "events": [
                {
                    "type": e.type.value if hasattr(e.type, "value") else str(e.type),
                    "day": e.day,
                    "phase": e.phase.value if hasattr(e.phase, "value") else str(e.phase),
                    "payload": e.payload or {},
                }
                for e in state.events[-200:]  # Last 200 events max
            ],
        }

        # Build player_decisions dict
        player_decisions: dict[str, list[dict]] = {}
        for decision in replay_bundle.decisions or []:
            pa = decision.get("selected_action") or {}
            player_name = decision.get("player_name", "") or str(
                next((p.name for p in state.players if p.id == decision.get("player_id", "")), "")
            )
            if not player_name:
                continue
            player_decisions.setdefault(player_name, []).append(
                {
                    "id": decision.get("decision_id", ""),
                    "player_name": player_name,
                    "player_role": decision.get("player_role", ""),
                    "day": decision.get("day", 0),
                    "phase": decision.get("phase", ""),
                    "action_type": pa.get("action_type", ""),
                    "target_id": pa.get("target_id", ""),
                    "raw_text": str(pa.get("reasoning", "") or ""),
                }
            )

        game_scores = panel.score_game(game_state_dict, player_decisions)

        return [
            {
                "player_name": s.player_name,
                "role": s.role,
                "alignment": s.alignment,
                "strategy_score": s.strategy_score,
                "logic_score": s.logic_score,
                "social_score": s.social_score,
                "composite": s.composite,
                "judge_agreement": s.judge_agreement,
                "rubric_hash": s.rubric_hash,
            }
            for s in game_scores
        ]
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"LLM game-level scoring failed: {e}")
        return None


def generate_published_review_document(
    state: GameState,
    *,
    view_scope: str = "moderator_view",
    llm_client: Any = None,
    cascade: bool = False,
) -> PublishedReviewDocument:
    """Generate a complete published review document for a finished game.

    Args:
        state: Completed game state.
        view_scope: Visibility scope for the published document.
        llm_client: Optional LLM client. When provided with cascade=True,
                    enables Tier 2 (light LLM single-judge) and Tier 3
                    (heavy LLM 3-judge panel) scoring.
        cascade: If True and llm_client is provided, run three-tier cascade
                 (deterministic → light LLM → heavy LLM).
    """
    replay_bundle = ReplayBundleBuilder().build(state)
    generated = generate_review_report(state)
    review_report = dict(generated["report"])
    base_markdown = _append_validation_section(generated["final_markdown"], None)
    speech_acts = SpeechActAnalyzer().analyze(state)
    suspicion_matrix = SuspicionMatrixBuilder().build(state, speech_acts)
    repair_loop = ReviewRepairLoop()
    validator = TrackBValidator()
    review_report, markdown, validation, repair_history = repair_loop.run(
        replay_bundle=replay_bundle,
        review_report=review_report,
        markdown=base_markdown,
        speech_acts=speech_acts,
        suspicion_matrix=suspicion_matrix,
        validator=validator,
        view_scope=view_scope,
    )
    markdown = _append_validation_section(markdown.split("## 10. 报告可信度校验", 1)[0].rstrip(), validation)
    status = (
        "approved"
        if validation.publish_allowed
        else ("needs_revision" if validation.grade == "needs_revision" else "rejected")
    )
    knowledge_feedback: list[dict[str, Any]] = []
    if validation.publish_allowed:
        # Track C §20: close the knowledge-usage feedback loop. For every
        # AgentDecision that retrieved a knowledge doc, mark the doc helpful
        # iff the player wasn't tagged in a BadCase on that day; otherwise
        # mark it as failure. This is the data plane that lets DreamJob
        # demote unhelpful knowledge over time.
        knowledge_feedback = _record_knowledge_usage(state, review_report)
    leaderboard_snapshot = _build_leaderboard_snapshot(review_report)
    # B Track: per-step decision scoring (three-tier cascade when llm_client provided)
    per_step_scores = _compute_per_step_scores(
        state,
        replay_bundle,
        speech_acts,
        llm_client=llm_client,
        cascade=cascade,
    )
    review_report.setdefault("metadata", {})["per_step_scores"] = per_step_scores

    # Track C: Extract knowledge from Track B enriched per-step scores
    # (Critical fix C6: B→C data handoff was broken — Track B computed scores
    # but never fed them to KnowledgeAbstractor).
    _extract_and_store_knowledge(state, per_step_scores, replay_bundle.decisions or [])

    # C Track: LLM Judge Panel game-level scoring (optional, heavy)
    if cascade and llm_client is not None:
        llm_game_scores = _compute_llm_game_scores(state, replay_bundle, llm_client)
        if llm_game_scores:
            review_report.setdefault("metadata", {})["llm_game_scores"] = llm_game_scores
    preview_document = PublishedReviewDocument(
        report_id=str(uuid4()),
        game_id=state.id,
        status=status,
        view_scope=view_scope,
        created_at=_utcnow_iso(),
        published_at=_utcnow_iso() if validation.publish_allowed else None,
        replay_bundle=asdict(replay_bundle),
        review_report=review_report,
        markdown=markdown,
        speech_acts=[asdict(item) for item in speech_acts],
        suspicion_matrix=[asdict(item) for item in suspicion_matrix],
        validation_result=asdict(validation),
        repair_history=repair_history,
        metadata={},
    )
    html_report = HTMLReviewRenderer().render(preview_document)
    return PublishedReviewDocument(
        report_id=preview_document.report_id,
        game_id=state.id,
        status=status,
        view_scope=view_scope,
        created_at=preview_document.created_at,
        published_at=preview_document.published_at,
        replay_bundle=preview_document.replay_bundle,
        review_report=review_report,
        markdown=markdown,
        speech_acts=preview_document.speech_acts,
        suspicion_matrix=preview_document.suspicion_matrix,
        validation_result=asdict(validation),
        repair_history=repair_history,
        metadata={
            "quality_passed": generated["quality_passed"],
            "evaluator_grade": generated["evaluator_grade"],
            "evaluator_score": generated["evaluator_score"],
            "iterations": generated["iterations"],
            "leaderboard_snapshot": leaderboard_snapshot,
            "html_report": html_report,
            "knowledge_feedback": knowledge_feedback,
        },
    )


def _coerce_dataclass(cls, value: Any) -> Any:
    if isinstance(value, cls):
        return value
    if isinstance(value, dict):
        allowed = set(getattr(cls, "__dataclass_fields__", {}).keys())
        return cls(**{key: val for key, val in value.items() if key in allowed})
    return value


def reconstruct_review_report(payload: dict[str, Any]) -> ReviewReport:
    """Rebuild a ReviewReport with typed nested review artifacts.

    Track C's strategy extractor consumes attributes on bad cases,
    counterfactuals and player reviews, so returning nested dicts here creates
    a runtime-only break in the B→C pipeline. Keep unknown future fields out of
    the constructors but preserve known fields as dataclasses.
    """
    return ReviewReport(
        game_id=payload["game_id"],
        winner=payload.get("winner"),
        total_days=payload.get("total_days", 0),
        total_events=payload.get("total_events", 0),
        game_summary=payload.get("game_summary", ""),
        scoreboard=list(payload.get("scoreboard", [])),
        mvp_results=[_coerce_dataclass(MVPResult, item) for item in payload.get("mvp_results", [])],
        turning_points=[_coerce_dataclass(TurningPoint, item) for item in payload.get("turning_points", [])],
        player_reviews=[_coerce_dataclass(PlayerReview, item) for item in payload.get("player_reviews", [])],
        bad_cases=[_coerce_dataclass(BadCaseReport, item) for item in payload.get("bad_cases", [])],
        counterfactuals=[_coerce_dataclass(CounterfactualCase, item) for item in payload.get("counterfactuals", [])],
        strategy_suggestions=[
            _coerce_dataclass(StrategySuggestion, item) for item in payload.get("strategy_suggestions", [])
        ],
        metadata=dict(payload.get("metadata", {})),
    )
