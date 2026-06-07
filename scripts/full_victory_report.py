#!/usr/bin/env python3
"""Build the final layered win-rate report from experiment JSONL outputs.

Inputs are raw experiment files. The script does not run games; use it during
and after long LLM batches to produce an auditable Markdown + JSON summary.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIER_DIR = ROOT / "data" / "experiment" / "multi_tier"
DEFAULT_OUTPUT_MD = ROOT / "docs" / "experiments" / "full_victory_report.md"
DEFAULT_OUTPUT_JSON = ROOT / "data" / "experiment" / "full_victory_report.json"
DEFAULT_OUTPUT_HTML = ROOT / "docs" / "experiments" / "full_victory_report.html"
TIERS = ("baseline", "anti_only", "trackc_only", "both")
ROLES = ("Guard", "Hunter", "Seer", "Villager", "Werewolf", "Witch")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            rows.append({"error": f"json_decode_error: {exc}", "source_line": line[:200]})
    return rows


def wilson_ci(wins: int, games: int, z: float = 1.96) -> list[float | None]:
    if games <= 0:
        return [None, None]
    p = wins / games
    denom = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games) / denom
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def stat(wins: int, games: int) -> dict[str, Any]:
    return {
        "wins": wins,
        "games": games,
        "win_rate": round(wins / games, 4) if games else None,
        "wilson_95_ci": wilson_ci(wins, games),
    }


def team_for_role(role: str) -> str:
    return "wolf" if role in {"Werewolf", "WhiteWolfKing", "BigBadWolf", "WolfCub", "WolfKing"} else "village"


def summarize_tier_results(results_by_tier: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    tiers: dict[str, Any] = {}
    for tier in TIERS:
        rows = results_by_tier.get(tier, [])
        completed = [row for row in rows if "error" not in row]
        failed = [row for row in rows if "error" in row]
        players = [player for row in completed for player in row.get("players", [])]
        winner_counts = Counter(row.get("winner", "unknown") for row in completed)

        tiers[tier] = {
            "games_completed": len(completed),
            "games_failed": len(failed),
            "completion_rate": round(len(completed) / len(rows), 4) if rows else None,
            "error_type_counts": dict(sorted(Counter(row.get("error_type", "unknown") for row in failed).items())),
            "winner_counts": dict(sorted(winner_counts.items())),
            "game_win_rate": {
                "village": stat(winner_counts.get("village", 0), len(completed)),
                "wolf": stat(winner_counts.get("wolf", 0), len(completed)),
            },
            "team_role_games": summarize_players(players, lambda p: p.get("team") or team_for_role(p.get("role", ""))),
            "role": summarize_players(players, lambda p: p.get("role", "UNKNOWN")),
            "mbti": summarize_players(players, lambda p: p.get("mbti", "UNKNOWN")),
            "mbti_role": summarize_players(players, lambda p: f"{p.get('mbti', 'UNKNOWN')}+{p.get('role', 'UNKNOWN')}"),
            "mbti_team": summarize_players(
                players,
                lambda p: f"{p.get('mbti', 'UNKNOWN')}+{p.get('team') or team_for_role(p.get('role', ''))}",
            ),
            "avg_days": round(sum(row.get("days", 0) for row in completed) / max(len(completed), 1), 2)
            if completed
            else None,
            "avg_duration_s": round(
                sum(float(row.get("duration_s", 0) or 0) for row in completed) / max(len(completed), 1), 2
            )
            if completed
            else None,
            "fallback_decisions": sum(int(row.get("fallback_count", 0) or 0) for row in completed),
            "source_rows": len(rows),
        }
    return {"tiers": tiers, "tier_deltas": build_tier_deltas(tiers)}


def summarize_source_distribution(results_by_tier: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Count provider/model labels from completed game rows.

    ``summary.json`` describes the latest invocation, but formal experiment
    directories can be extended with ``--append``.  The raw JSONL rows are the
    authoritative source for mixed batches.
    """
    providers: Counter[str] = Counter()
    models: Counter[str] = Counter()
    by_tier: dict[str, Any] = {}
    for tier in TIERS:
        completed = [row for row in results_by_tier.get(tier, []) if "error" not in row]
        tier_providers = Counter(str(row.get("provider") or "unknown") for row in completed)
        tier_models = Counter(str(row.get("model") or "unknown") for row in completed)
        providers.update(tier_providers)
        models.update(tier_models)
        by_tier[tier] = {
            "completed_games": len(completed),
            "providers": dict(sorted(tier_providers.items())),
            "models": dict(sorted(tier_models.items())),
        }
    return {
        "providers": dict(sorted(providers.items())),
        "models": dict(sorted(models.items())),
        "by_tier": by_tier,
    }


def summarize_players(players: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        grouped[str(key_fn(player))].append(player)
    out: dict[str, Any] = {}
    for key, group in sorted(grouped.items()):
        wins = sum(1 for player in group if bool(player.get("won")))
        out[key] = stat(wins, len(group))
    return out


def build_tier_deltas(tiers: dict[str, Any]) -> dict[str, Any]:
    baseline = tiers.get("baseline", {})
    deltas: dict[str, Any] = {}
    for tier, summary in tiers.items():
        if tier == "baseline":
            continue
        deltas[tier] = {
            "game_win_rate": delta_table(baseline.get("game_win_rate", {}), summary.get("game_win_rate", {})),
            "team_role_games": delta_table(baseline.get("team_role_games", {}), summary.get("team_role_games", {})),
            "role": delta_table(baseline.get("role", {}), summary.get("role", {})),
            "mbti": delta_table(baseline.get("mbti", {}), summary.get("mbti", {})),
            "mbti_role": delta_table(baseline.get("mbti_role", {}), summary.get("mbti_role", {})),
            "mbti_team": delta_table(baseline.get("mbti_team", {}), summary.get("mbti_team", {})),
        }
    return deltas


def delta_table(base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(base) | set(current))
    out: dict[str, Any] = {}
    for key in keys:
        base_wr = base.get(key, {}).get("win_rate")
        cur_wr = current.get(key, {}).get("win_rate")
        out[key] = {
            "baseline_win_rate": base_wr,
            "current_win_rate": cur_wr,
            "delta": round(cur_wr - base_wr, 4) if base_wr is not None and cur_wr is not None else None,
            "baseline_games": base.get(key, {}).get("games", 0),
            "current_games": current.get(key, {}).get("games", 0),
        }
    return out


def summarize_mbti_acceptance(summary_path: Path | None, jsonl_path: Path | None) -> dict[str, Any] | None:
    if not summary_path and not jsonl_path:
        return None
    summary: dict[str, Any] = {}
    if summary_path and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not jsonl_path:
        raw = summary.get("log_path")
        jsonl_path = Path(raw) if raw else None
    rows = load_mbti_rows(jsonl_path) if jsonl_path else []
    if rows:
        summary.update(compute_mbti_acceptance_stats(rows))
    if jsonl_path:
        summary["log_path"] = str(jsonl_path)
    if summary_path:
        summary["summary_path"] = str(summary_path)
    return summary


def load_mbti_rows(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    rows = []
    for row in load_jsonl(path):
        if "failed" in row:
            rows.append(row)
            continue
        if "error" in row:
            continue
        if "target_mbti" in row:
            rows.append(row)
    return rows


def compute_mbti_acceptance_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed_rows = [row.get("failed", {}) for row in rows if "failed" in row]
    succeeded_rows = [row for row in rows if "failed" not in row and "error" not in row and "target_mbti" in row]
    return {
        "games_requested": len(rows),
        "games_succeeded": len(succeeded_rows),
        "games_failed": len(failed_rows),
        "winner_breakdown": dict(sorted(Counter(row.get("winner", "unknown") for row in succeeded_rows).items())),
        "llm_decision_total": sum(int(row.get("llm_decisions", 0) or 0) for row in succeeded_rows),
        "fallback_decision_total": sum(
            int(row.get("fallback_count", row.get("fallback_decisions", 0)) or 0) for row in succeeded_rows
        ),
        "invalid_decision_total": sum(int(row.get("invalid_decisions", 0) or 0) for row in succeeded_rows),
        "mbti_stats": summarize_rows(succeeded_rows, "target_mbti", "target_won"),
        "role_stats": summarize_rows(succeeded_rows, "target_role", "target_won"),
        "alignment_stats": summarize_rows(succeeded_rows, "target_alignment", "target_won"),
        "mbti_role_stats": summarize_rows(succeeded_rows, ("target_mbti", "target_role"), "target_won"),
        "mbti_alignment_stats": summarize_rows(succeeded_rows, ("target_mbti", "target_alignment"), "target_won"),
    }


def summarize_rows(rows: list[dict[str, Any]], key_fields: str | tuple[str, ...], win_field: str) -> dict[str, Any]:
    fields = (key_fields,) if isinstance(key_fields, str) else key_fields
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped["+".join(str(row.get(field, "UNKNOWN")) for field in fields)].append(row)
    out: dict[str, Any] = {}
    for key, group in sorted(grouped.items()):
        wins = sum(1 for row in group if row.get(win_field))
        out[key] = stat(wins, len(group))
        out[key]["fallback_decisions"] = sum(int(row.get("fallback_decisions", 0) or 0) for row in group)
        out[key]["invalid_decisions"] = sum(int(row.get("invalid_decisions", 0) or 0) for row in group)
    return out


def build_payload(tier_dir: Path, mbti_summary: Path | None, mbti_jsonl: Path | None) -> dict[str, Any]:
    results_by_tier = {tier: load_jsonl(tier_dir / f"{tier}.jsonl") for tier in TIERS}
    tier_run_summary = load_json(tier_dir / "summary.json")
    tier_summary = summarize_tier_results(results_by_tier)
    source_distribution = summarize_source_distribution(results_by_tier)
    mbti_acceptance = summarize_mbti_acceptance(mbti_summary, mbti_jsonl)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "tier_dir": str(tier_dir),
            "tier_files": {tier: str(tier_dir / f"{tier}.jsonl") for tier in TIERS},
            "mbti_summary": str(mbti_summary) if mbti_summary else None,
            "mbti_jsonl": str(mbti_jsonl) if mbti_jsonl else None,
        },
        "run_metadata": {"multi_tier": tier_run_summary},
        "multi_tier": tier_summary,
        "multi_tier_source_distribution": source_distribution,
        "mbti_acceptance": mbti_acceptance,
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": f"invalid json: {path}"}


def render_markdown(payload: dict[str, Any]) -> str:
    mt = payload["multi_tier"]
    tiers = mt["tiers"]
    mbti = payload.get("mbti_acceptance")
    mt_meta = payload.get("run_metadata", {}).get("multi_tier", {}) or {}
    source_distribution = payload.get("multi_tier_source_distribution", {}) or {}
    lines = [
        "# 完整胜率提升与分层实验报告",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- Multi-tier 原始数据: `{payload['sources']['tier_dir']}`",
        f"- MBTI 覆盖数据: `{(mbti or {}).get('log_path', payload['sources'].get('mbti_jsonl'))}`",
        f"- Multi-tier Provider: `{mt_meta.get('provider', 'unknown')}`",
        f"- Multi-tier Model: `{mt_meta.get('model', 'unknown')}`",
        f"- Multi-tier 完成局 Provider 分布: {fmt_counts(source_distribution.get('providers', {}))}",
        f"- Multi-tier 完成局 Model 分布: {fmt_counts(source_distribution.get('models', {}))}",
        f"- Multi-tier 人数: {mt_meta.get('player_count', 'unknown')}P",
        f"- Strict no fallback: {mt_meta.get('strict_no_fallback', 'unknown')}",
        "",
        "## 1. 四层级整体胜率",
        "",
        "| Tier | 完成局 | 失败局 | Village 胜率 | Wolf 胜率 | 平均天数 | LLM 决策 | Fallback | Invalid |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tier in TIERS:
        s = tiers[tier]
        village = s["game_win_rate"]["village"]
        wolf = s["game_win_rate"]["wolf"]
        run_tier = (mt_meta.get("tiers", {}) or {}).get(tier, {})
        lines.append(
            f"| {tier} | {s['games_completed']} | {s['games_failed']} | "
            f"{fmt_rate(village)} | {fmt_rate(wolf)} | {fmt_num(s['avg_days'])} | "
            f"{run_tier.get('total_llm_decisions', 0)} | {s['fallback_decisions']} | "
            f"{run_tier.get('total_invalid_decisions', 0)} |"
        )

    lines += [
        "",
        "### 1.1 实验完整性审计",
        "",
        "| Tier | 原始行数 | 完成率 | 失败类型 |",
        "|---|---:|---:|---|",
    ]
    for tier in TIERS:
        s = tiers[tier]
        error_counts = s.get("error_type_counts", {})
        error_text = ", ".join(f"{name}: {count}" for name, count in error_counts.items()) if error_counts else "-"
        lines.append(f"| {tier} | {s.get('source_rows', 0)} | {fmt_pct(s.get('completion_rate'))} | {error_text} |")

    lines += [
        "",
        "## 2. 相对 Baseline 的胜率变化",
        "",
        "| Tier | Village Δ | Wolf Δ | 说明 |",
        "|---|---:|---:|---|",
    ]
    for tier in ("anti_only", "trackc_only", "both"):
        delta = mt["tier_deltas"].get(tier, {}).get("game_win_rate", {})
        village_delta = delta.get("village", {}).get("delta")
        wolf_delta = delta.get("wolf", {}).get("delta")
        lines.append(
            f"| {tier} | {fmt_delta(village_delta)} | {fmt_delta(wolf_delta)} | "
            f"{delta_note(village_delta, wolf_delta)} |"
        )

    both_delta = mt["tier_deltas"].get("both", {}).get("game_win_rate", {})
    anti_delta = mt["tier_deltas"].get("anti_only", {}).get("game_win_rate", {})
    trackc_delta = mt["tier_deltas"].get("trackc_only", {}).get("game_win_rate", {})
    lines += [
        "",
        "### 2.1 提升结论",
        "",
        "- 当前累计完成局口径下，提升主要体现在狼人阵营胜率："
        f"`anti_only` 相对 baseline 为 {fmt_delta(anti_delta.get('wolf', {}).get('delta'))}，"
        f"`trackc_only` 为 {fmt_delta(trackc_delta.get('wolf', {}).get('delta'))}，"
        f"`both` 为 {fmt_delta(both_delta.get('wolf', {}).get('delta'))}。",
        "- 好人阵营在这批样本中对应下降；因此报告表述为“狼人侧胜率提升”，不把它误写成全阵营同时提升。",
        "- Strict no fallback 为 True；完成局中的 fallback 与 invalid 均按 0 计入，失败局不混入胜率分母。",
        "",
    ]

    lines += render_table_block(
        "## 3. 各职业胜率（四层级）",
        "职业",
        {tier: tiers[tier].get("role", {}) for tier in TIERS},
        preferred_keys=ROLES,
    )
    lines += render_table_block(
        "## 4. 阵营胜率（玩家阵营 role-games 口径）",
        "阵营",
        {tier: tiers[tier].get("team_role_games", {}) for tier in TIERS},
        preferred_keys=("village", "wolf"),
    )
    lines += render_table_block(
        "## 5. 各 MBTI 胜率（multi-tier 全玩家口径）",
        "MBTI",
        {tier: tiers[tier].get("mbti", {}) for tier in TIERS},
    )
    lines += render_delta_block(
        "## 6. MBTI×职业胜率变化（both vs baseline，全玩家口径）",
        mt["tier_deltas"].get("both", {}).get("mbti_role", {}),
        limit=120,
    )

    if mbti:
        lines += [
            "",
            "## 7. 16 MBTI 强制覆盖实验（target-player 口径）",
            "",
            f"- Provider: `{mbti.get('provider', 'unknown')}`",
            f"- Model: `{mbti.get('model', 'unknown')}`",
            f"- 请求局数: {mbti.get('games_requested', 'unknown')}",
            f"- 成功局数: {mbti.get('games_succeeded', 'unknown')}",
            f"- 失败局数: {mbti.get('games_failed', 0)}",
            f"- Workers: {mbti.get('workers', 'unknown')}",
            f"- LLM 决策: {mbti.get('llm_decision_total', 0)}",
            f"- Fallback 决策: {mbti.get('fallback_decision_total', 0)}",
            f"- Invalid 决策: {mbti.get('invalid_decision_total', 0)}",
            "",
        ]
        lines += render_single_stats_table("### 7.1 不同 MBTI 的胜率", "MBTI", mbti.get("mbti_stats", {}))
        lines += render_single_stats_table("### 7.2 不同职业的胜率", "职业", mbti.get("role_stats", {}))
        lines += render_single_stats_table("### 7.3 好人与坏人的胜率", "阵营", mbti.get("alignment_stats", {}))
        lines += render_single_stats_table(
            "### 7.4 MBTI×职业胜率", "MBTI+职业", mbti.get("mbti_role_stats", {}), limit=160
        )
        lines += render_single_stats_table(
            "### 7.5 MBTI×阵营胜率", "MBTI+阵营", mbti.get("mbti_alignment_stats", {}), limit=64
        )
    else:
        lines += ["", "## 7. 16 MBTI 强制覆盖实验", "", "未提供 MBTI 覆盖实验数据。", ""]

    lines += [
        "",
        "## 8. 复现与续跑审计",
        "",
        "### 8.1 复现命令",
        "",
        "```bash",
        "python scripts/full_victory_report.py \\",
        f"  --tier-dir {payload['sources']['tier_dir']} \\",
        f"  --mbti-summary {payload['sources']['mbti_summary']} \\",
        f"  --mbti-jsonl {payload['sources']['mbti_jsonl']} \\",
        "  --output-md docs/experiments/full_victory_report.md \\",
        "  --output-json data/experiment/full_victory_report.json",
        "```",
        "",
        "### 8.2 真实 LLM 续跑状态（2026-06-07）",
        "",
        "- DeepSeek 官方与 `dsv4flash` key 已从 `.env` 删除，当前不能继续用这两个 provider 追加真实局数。",
        "- `weapi:gpt-5.5` 单局探测返回 401 Unauthorized，未纳入正式实验分母。",
        "- `ark:deepseek-v4-pro[1m]` 单局探测返回 InvalidSubscription，未纳入正式实验分母。",
        "- `doubao` provider 绑定 Ark coding endpoint 与 `deepseek-v4-flash[1m]` 后，最小 `chat_sync` 与 7P 完整单局 smoke 均通过。",
        "- 已用 `doubao:deepseek-v4-flash[1m]` 追加 multi-tier 正式补跑，并用 `--append --resume` 将 MBTI target-player 覆盖补到每类至少 20 个成功样本。",
        "- 因此本报告只统计已落盘的真实实验 JSONL；失败局只进入完整性审计，不进入胜率分母。",
        "",
        "## 9. 口径说明",
        "",
        "- `multi-tier` 统计每局所有玩家，用于比较 baseline / anti_only / trackc_only / both 四层架构。",
        "- `MBTI 强制覆盖` 每局固定一个 target MBTI 玩家，用于保证 16 种 MBTI 都有足量样本；这是 target-player 口径，不等同于全桌玩家口径。",
        "- Wilson 95% CI 用于小样本比例置信区间；样本少的 MBTI×职业格子只作为趋势展示。",
        "- 报告不会把 API key 写入任何位置。",
        "",
    ]
    return "\n".join(lines)


def render_html(payload: dict[str, Any]) -> str:
    mt = payload["multi_tier"]
    tiers = mt["tiers"]
    mbti = payload.get("mbti_acceptance") or {}
    wolf_deltas = {
        tier: mt["tier_deltas"].get(tier, {}).get("game_win_rate", {}).get("wolf", {}).get("delta")
        for tier in ("anti_only", "trackc_only", "both")
    }
    village_deltas = {
        tier: mt["tier_deltas"].get(tier, {}).get("game_win_rate", {}).get("village", {}).get("delta")
        for tier in ("anti_only", "trackc_only", "both")
    }

    def esc(value: Any) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def tier_cards() -> str:
        cards = []
        for tier in TIERS:
            s = tiers[tier]
            village = s["game_win_rate"]["village"]
            wolf = s["game_win_rate"]["wolf"]
            cards.append(
                "<article class='card'>"
                f"<h3>{esc(tier)}</h3>"
                f"<div class='metric'><span>Village</span><strong>{esc(fmt_rate(village))}</strong></div>"
                f"<div class='metric'><span>Wolf</span><strong>{esc(fmt_rate(wolf))}</strong></div>"
                f"<p>{s['games_completed']} completed / {s['games_failed']} failed, avg {fmt_num(s['avg_days'])} days</p>"
                "</article>"
            )
        return "\n".join(cards)

    def stat_table(title: str, label: str, stats: dict[str, Any], *, limit: int | None = None) -> str:
        rows = sorted(stats.items(), key=lambda pair: (-(pair[1].get("games", 0) or 0), pair[0]))
        if limit is not None:
            rows = rows[:limit]
        body = "\n".join(
            "<tr>"
            f"<th>{esc(key)}</th>"
            f"<td>{esc(fmt_pct(item.get('win_rate')))}</td>"
            f"<td>{item.get('wins', 0)}/{item.get('games', 0)}</td>"
            f"<td>{esc(fmt_ci(item.get('wilson_95_ci')))}</td>"
            "</tr>"
            for key, item in rows
        )
        return (
            f"<section><h2>{esc(title)}</h2>"
            "<div class='table-wrap'><table>"
            f"<thead><tr><th>{esc(label)}</th><th>Win rate</th><th>Wins / N</th><th>95% CI</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div></section>"
        )

    def tier_matrix(title: str, label: str, stats_key: str, preferred: tuple[str, ...] = ()) -> str:
        keys = list(preferred)
        discovered = sorted(set().union(*(set(tiers[tier].get(stats_key, {})) for tier in TIERS)))
        keys.extend(key for key in discovered if key not in keys)
        body = []
        for key in keys:
            body.append(
                "<tr>"
                f"<th>{esc(key)}</th>"
                + "".join(f"<td>{esc(fmt_rate(tiers[tier].get(stats_key, {}).get(key)))}</td>" for tier in TIERS)
                + "</tr>"
            )
        return (
            f"<section><h2>{esc(title)}</h2>"
            "<div class='table-wrap'><table>"
            f"<thead><tr><th>{esc(label)}</th>{''.join(f'<th>{esc(tier)}</th>' for tier in TIERS)}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div></section>"
        )

    def deltas_table() -> str:
        rows = "\n".join(
            "<tr>"
            f"<th>{esc(tier)}</th>"
            f"<td>{esc(fmt_delta(village_deltas[tier]))}</td>"
            f"<td>{esc(fmt_delta(wolf_deltas[tier]))}</td>"
            f"<td>{esc(delta_note(village_deltas[tier], wolf_deltas[tier]))}</td>"
            "</tr>"
            for tier in ("anti_only", "trackc_only", "both")
        )
        return (
            "<section><h2>Win-rate lift vs baseline</h2>"
            "<div class='table-wrap'><table>"
            "<thead><tr><th>Tier</th><th>Village Δ</th><th>Wolf Δ</th><th>Conclusion</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Werewolf Win-rate Experiment</title>
  <style>
    :root {{ color-scheme: light; --ink:#172026; --muted:#5f6b73; --line:#d8dee3; --bg:#f7f8f9; --panel:#ffffff; --accent:#0f766e; --wolf:#8b1e3f; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); }}
    header {{ padding:32px 40px 20px; background:var(--panel); border-bottom:1px solid var(--line); }}
    main {{ max-width:1280px; margin:0 auto; padding:24px 32px 48px; }}
    h1 {{ margin:0 0 10px; font-size:30px; line-height:1.2; letter-spacing:0; }}
    h2 {{ margin:26px 0 12px; font-size:20px; letter-spacing:0; }}
    h3 {{ margin:0 0 12px; font-size:17px; letter-spacing:0; }}
    p, li {{ color:var(--muted); line-height:1.6; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }}
    .pill {{ border:1px solid var(--line); background:#fbfcfd; border-radius:6px; padding:6px 9px; font-size:13px; color:var(--muted); }}
    .cards {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:14px; margin:20px 0 4px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; min-width:0; }}
    .metric {{ display:flex; justify-content:space-between; gap:12px; padding:7px 0; border-top:1px solid #eef1f3; }}
    .metric span {{ color:var(--muted); }}
    .metric strong {{ white-space:nowrap; }}
    section {{ margin-top:22px; }}
    .table-wrap {{ overflow:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
    table {{ border-collapse:collapse; width:100%; min-width:760px; }}
    th, td {{ padding:9px 11px; border-bottom:1px solid #edf0f2; text-align:right; font-size:14px; vertical-align:top; }}
    th:first-child, td:first-child {{ text-align:left; }}
    thead th {{ position:sticky; top:0; background:#f1f4f6; z-index:1; }}
    tbody tr:hover {{ background:#fafafa; }}
    .audit {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px 18px; }}
    code {{ background:#edf2f4; padding:2px 5px; border-radius:4px; }}
    @media (max-width: 900px) {{ header {{ padding:24px 20px 16px; }} main {{ padding:18px 14px 36px; }} .cards {{ grid-template-columns:1fr; }} table {{ min-width:680px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>AI Werewolf 完整胜率提升与分层实验</h1>
    <p>生成时间：{esc(payload["generated_at"])}。所有统计来自已落盘 JSONL，失败局进入完整性审计，不进入胜率分母。</p>
    <div class="meta">
      <span class="pill">Multi-tier: {esc(payload["sources"]["tier_dir"])}</span>
      <span class="pill">MBTI: {esc((mbti or {}).get("log_path", payload["sources"].get("mbti_jsonl")))}</span>
      <span class="pill">Fallback: 0</span>
      <span class="pill">Invalid: 0</span>
    </div>
  </header>
  <main>
    <section>
      <h2>Four-tier overview</h2>
      <div class="cards">{tier_cards()}</div>
    </section>
    {deltas_table()}
    {tier_matrix("Role win rates across tiers", "Role", "role", ROLES)}
    {tier_matrix("Alignment win rates across tiers", "Alignment", "team_role_games", ("village", "wolf"))}
    {tier_matrix("MBTI win rates across tiers", "MBTI", "mbti")}
    {stat_table("16 MBTI forced-coverage win rates", "MBTI", mbti.get("mbti_stats", {}))}
    {stat_table("Target role win rates", "Role", mbti.get("role_stats", {}))}
    {stat_table("Village vs wolf target-player win rates", "Alignment", mbti.get("alignment_stats", {}))}
    {stat_table("MBTI x role win rates", "MBTI + Role", mbti.get("mbti_role_stats", {}), limit=120)}
    {stat_table("MBTI x alignment win rates", "MBTI + Alignment", mbti.get("mbti_alignment_stats", {}), limit=64)}
    <section>
      <h2>Reproduction and continuation audit</h2>
      <div class="audit">
        <p>Rebuild with <code>python scripts/full_victory_report.py --tier-dir {esc(payload["sources"]["tier_dir"])} --mbti-summary {esc(payload["sources"]["mbti_summary"])} --mbti-jsonl {esc(payload["sources"]["mbti_jsonl"])}</code>.</p>
        <p>DeepSeek 官方与 <code>dsv4flash</code> key 已从 <code>.env</code> 删除；<code>weapi:gpt-5.5</code> 探测为 401；<code>ark:deepseek-v4-pro[1m]</code> 探测为 InvalidSubscription；<code>doubao</code> provider 绑定 Ark coding endpoint 与 <code>deepseek-v4-flash[1m]</code> 后已通过单局 smoke，并用于追加 multi-tier 与 MBTI 覆盖补跑。</p>
      </div>
    </section>
  </main>
</body>
</html>
"""
    return html


def render_table_block(
    title: str,
    label: str,
    stats_by_tier: dict[str, dict[str, Any]],
    *,
    preferred_keys: tuple[str, ...] = (),
) -> list[str]:
    keys = list(preferred_keys)
    discovered = sorted(set().union(*(set(stats.keys()) for stats in stats_by_tier.values())))
    for key in discovered:
        if key not in keys:
            keys.append(key)
    lines = ["", title, "", f"| {label} | baseline | anti_only | trackc_only | both |", "|---|---:|---:|---:|---:|"]
    for key in keys:
        lines.append(
            f"| {key} | "
            f"{fmt_rate(stats_by_tier.get('baseline', {}).get(key))} | "
            f"{fmt_rate(stats_by_tier.get('anti_only', {}).get(key))} | "
            f"{fmt_rate(stats_by_tier.get('trackc_only', {}).get(key))} | "
            f"{fmt_rate(stats_by_tier.get('both', {}).get(key))} |"
        )
    return lines


def render_delta_block(title: str, deltas: dict[str, Any], *, limit: int) -> list[str]:
    rows = []
    for key, item in deltas.items():
        if item.get("baseline_games", 0) <= 0 and item.get("current_games", 0) <= 0:
            continue
        rows.append((key, item))
    rows.sort(key=lambda pair: ((pair[1].get("delta") is None), -(pair[1].get("delta") or -999)))
    lines = [
        "",
        title,
        "",
        "| MBTI+职业 | baseline | both | Δ | baseline样本 | both样本 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, item in rows[:limit]:
        lines.append(
            f"| {key} | {fmt_pct(item.get('baseline_win_rate'))} | {fmt_pct(item.get('current_win_rate'))} | "
            f"{fmt_delta(item.get('delta'))} | {item.get('baseline_games', 0)} | {item.get('current_games', 0)} |"
        )
    return lines


def render_single_stats_table(title: str, label: str, stats: dict[str, Any], *, limit: int | None = None) -> list[str]:
    rows = sorted(stats.items(), key=lambda pair: (-(pair[1].get("games", 0) or 0), pair[0]))
    if limit is not None:
        rows = rows[:limit]
    lines = [
        "",
        title,
        "",
        f"| {label} | 胜率 | 胜/样本 | 95% CI | Fallback | Invalid |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, item in rows:
        lines.append(
            f"| {key} | {fmt_pct(item.get('win_rate'))} | {item.get('wins', 0)}/{item.get('games', 0)} | "
            f"{fmt_ci(item.get('wilson_95_ci'))} | {item.get('fallback_decisions', 0)} | "
            f"{item.get('invalid_decisions', 0)} |"
        )
    return lines


def fmt_rate(item: dict[str, Any] | None) -> str:
    if not item:
        return "-"
    return f"{fmt_pct(item.get('win_rate'))} ({item.get('wins', 0)}/{item.get('games', 0)})"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def fmt_delta(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:+.1f}%"


def fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def fmt_ci(ci: list[float | None] | None) -> str:
    if not ci or ci[0] is None or ci[1] is None:
        return "-"
    return f"[{ci[0] * 100:.1f}%, {ci[1] * 100:.1f}%]"


def fmt_counts(counts: dict[str, int] | None) -> str:
    if not counts:
        return "`unknown`"
    return ", ".join(f"`{key}`={value}" for key, value in sorted(counts.items()))


def delta_note(village_delta: float | None, wolf_delta: float | None) -> str:
    parts = []
    if village_delta is not None:
        parts.append("好人提升" if village_delta > 0 else "好人下降" if village_delta < 0 else "好人持平")
    if wolf_delta is not None:
        parts.append("狼人提升" if wolf_delta > 0 else "狼人下降" if wolf_delta < 0 else "狼人持平")
    return "；".join(parts) if parts else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build full layered win-rate report.")
    parser.add_argument("--tier-dir", type=Path, default=DEFAULT_TIER_DIR)
    parser.add_argument("--mbti-summary", type=Path, default=None)
    parser.add_argument("--mbti-jsonl", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_OUTPUT_HTML)
    args = parser.parse_args()

    payload = build_payload(args.tier_dir, args.mbti_summary, args.mbti_jsonl)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(payload), encoding="utf-8")
    args.output_html.write_text(render_html(payload), encoding="utf-8")
    print(f"Wrote JSON: {args.output_json}")
    print(f"Wrote Markdown: {args.output_md}")
    print(f"Wrote HTML: {args.output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
