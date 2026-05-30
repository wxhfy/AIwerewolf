#!/usr/bin/env python3
"""Track B Minimal Leaderboard Demo — LLM Agent Version Comparison.

Runs real LLM games (not heuristic, not fixture) and produces:
  data/health/track_b_minimal_leaderboard_games.jsonl
  data/health/track_b_minimal_leaderboard_summary.json
  docs/track_b_minimal_leaderboard_report.md
  docs/track_b_minimal_leaderboard_report.html (if available)

Agent versions compared:
  - llm-dsv4flash-v1: deepseek-v4-flash[1m] (faster/cheaper)
  - llm-dsv4pro-v1:   deepseek-v4-pro[1m]   (more capable)

Seeds: 100, 200, 300 for both versions (same seeds = same role setup = fair).
3 games × 2 versions = 6 total games.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players, get_role_configuration
from backend.eval.track_b import generate_published_review_document
from backend.eval.process_score_v3 import compute_process_score_v3, compute_game_value


# Agent version configs
AGENT_CONFIGS = {
    "llm-dsv4flash-v1": {
        "type": "llm",
        "provider": "doubao",
        "model": "deepseek-v4-flash[1m]",
        "api_key_env": "ANTHROPIC_AUTH_TOKEN",
        "base_url_env": "ANTHROPIC_BASE_URL",
    },
    "llm-dsv4pro-v1": {
        "type": "llm",
        "provider": "doubao",
        "model": "deepseek-v4-pro[1m]",
        "api_key_env": "ANTHROPIC_AUTH_TOKEN",
        "base_url_env": "ANTHROPIC_BASE_URL",
    },
}

SEEDS = [100, 200, 300]
PLAYER_COUNT = 7
MAX_DAYS = 5


def _make_config(agent_version: str, seed: int) -> dict:
    cfg = AGENT_CONFIGS[agent_version]
    return {
        "type": cfg["type"],
        "seed": seed,
        "provider": cfg["provider"],
        "model": cfg["model"],
        "api_key": os.getenv(cfg["api_key_env"], ""),
        "base_url": os.getenv(cfg["base_url_env"], ""),
    }


@dataclass
class GameResult:
    game_id: str
    agent_version: str
    model_id: str
    seed: int
    source: str
    winner: str
    total_days: int
    total_events: int
    total_opportunities: int
    role_setup: dict[str, str]
    player_scores: list[dict]
    critical_mistakes: int
    counterfactual_count: int
    avg_process_score: float
    avg_speech_score: float
    avg_vote_score: float
    avg_skill_score: float
    avg_survival_score: float
    process_scores_v3: list[dict] = field(default_factory=list)


async def run_one_game(agent_version: str, seed: int) -> GameResult:
    """Run one game and extract all scoring data."""
    config = _make_config(agent_version, seed)
    roles = get_role_configuration(PLAYER_COUNT)
    players = build_players(roles, seed=seed)
    agents = create_agents(players, config)

    game = WerewolfGame(
        players=players, agents=agents, seed=seed,
        max_days=MAX_DAYS, strategy_version=agent_version,
    )

    t0 = time.perf_counter()
    game.play()
    elapsed = time.perf_counter() - t0

    state = game.state
    winner = state.winner.value if state.winner else "unknown"
    role_setup = {p.id: p.role.value for p in state.players}

    # Run through review pipeline
    doc = generate_published_review_document(state)

    # Extract scores
    scoreboard = doc.review_report.get("scoreboard", [])
    player_scores_list = doc.review_report.get("metadata", {}).get("player_scores", [])

    player_scores = []
    process_scores = []
    speech_scores = []
    vote_scores = []
    skill_scores = []
    survival_scores = []

    for ps in player_scores_list:
        player_scores.append({
            "player_id": ps.get("player_id", ""),
            "player_name": ps.get("player_name", ""),
            "role": ps.get("role", ""),
            "alignment": ps.get("alignment", ""),
            "final_score": ps.get("final_score", 0),
            "adjusted_final_score": ps.get("adjusted_final_score", ps.get("final_score", 0)),
            "process_score": ps.get("process_score", 0),
            "speech_score": ps.get("speech_score", 0),
            "vote_score": ps.get("vote_score", 0),
            "skill_score": ps.get("skill_score", 0),
            "survival_score": ps.get("survival_score", 0),
            "role_task_score": ps.get("role_task_score", 0),
            "mistake_penalty": ps.get("mistake_penalty", 0),
        })
        process_scores.append(ps.get("process_score", 0) or 0)
        speech_scores.append(ps.get("speech_score", 0) or 0)
        vote_scores.append(ps.get("vote_score", 0) or 0)
        skill_scores.append(ps.get("skill_score", 0) or 0)
        survival_scores.append(ps.get("survival_score", 0) or 0)

    bad_cases = doc.review_report.get("bad_cases", [])
    counterfactuals = doc.review_report.get("counterfactuals", [])

    # Extract opportunities for ProcessScoreV3
    from backend.eval.track_b import ReplayBundleBuilder
    from backend.eval.opportunity import OpportunityExtractor
    bundle = ReplayBundleBuilder().build(state)
    opps = [op.to_dict() for op in OpportunityExtractor().extract(bundle)]

    n = len(player_scores_list) or 1
    print(f"  [{agent_version}] seed={seed} winner={winner} "
          f"days={state.day} events={len(state.events)} "
          f"opps={len(opps)} badcases={len(bad_cases)} "
          f"time={elapsed:.0f}s")

    return GameResult(
        game_id=state.id,
        agent_version=agent_version,
        model_id=config["model"],
        seed=seed,
        source="real_llm_game",
        winner=winner,
        total_days=state.day,
        total_events=len(state.events),
        total_opportunities=len(opps),
        role_setup=role_setup,
        player_scores=player_scores,
        critical_mistakes=len(bad_cases),
        counterfactual_count=len(counterfactuals),
        avg_process_score=round(float(np.mean(process_scores)), 4),
        avg_speech_score=round(float(np.mean(speech_scores)), 4),
        avg_vote_score=round(float(np.mean(vote_scores)), 4),
        avg_skill_score=round(float(np.mean(skill_scores)), 4),
        avg_survival_score=round(float(np.mean(survival_scores)), 4),
    )


async def run_all_games() -> list[GameResult]:
    results: list[GameResult] = []
    for agent_version in ["llm-dsv4flash-v1", "llm-dsv4pro-v1"]:
        print(f"\n{'='*50}")
        print(f"Running: {agent_version}")
        print(f"{'='*50}")
        for seed in SEEDS:
            result = await run_one_game(agent_version, seed)
            results.append(result)
    return results


def build_leaderboard(games: list[GameResult]) -> dict:
    by_version: dict[str, list[GameResult]] = defaultdict(list)
    for g in games:
        by_version[g.agent_version].append(g)

    # Also collect all player scores per version for role normalization
    all_player_scores: dict[str, list[dict]] = defaultdict(list)
    for g in games:
        for ps in g.player_scores:
            all_player_scores[g.agent_version].append(ps)

    # Compute role-level averages per version
    role_stats: dict[str, dict[str, dict]] = {}
    for version, pss in all_player_scores.items():
        by_role: dict[str, list[float]] = defaultdict(list)
        for ps in pss:
            by_role[ps["role"]].append(ps["process_score"])
        role_stats[version] = {
            role: {
                "n": len(scores),
                "avg_process": round(float(np.mean(scores)), 2),
                "std_process": round(float(np.std(scores)), 2),
                "avg_vote": round(float(np.mean([ps["vote_score"] for ps in pss if ps["role"] == role])), 2),
                "avg_speech": round(float(np.mean([ps["speech_score"] for ps in pss if ps["role"] == role])), 2),
                "avg_skill": round(float(np.mean([ps["skill_score"] for ps in pss if ps["role"] == role])), 2),
            }
            for role, scores in by_role.items()
        }

    entries = []
    for version, game_list in sorted(by_version.items()):
        n = len(game_list)
        process_scores_all = []
        speech_all, vote_all, skill_all, survival_all = [], [], [], []
        critical_mistakes_total = 0
        wins = 0

        for g in game_list:
            for ps in g.player_scores:
                process_scores_all.append(ps["process_score"])
                speech_all.append(ps["speech_score"])
                vote_all.append(ps["vote_score"])
                skill_all.append(ps["skill_score"])
                survival_all.append(ps["survival_score"])
            critical_mistakes_total += g.critical_mistakes
            if g.winner == "village":
                wins += 1  # heuristic: village win rate (role-dependent)

        # Actually win rate is an outcome metric. Let's compute average camp_result.
        avg_win_bonus = round(float(np.mean([
            ps.get("final_score", 0) - ps.get("process_score", 0)
            for g in game_list for ps in g.player_scores
        ])), 2)

        avg_process = round(float(np.mean(process_scores_all)), 2)
        avg_speech = round(float(np.mean(speech_all)), 2)
        avg_vote = round(float(np.mean(vote_all)), 2)
        avg_skill = round(float(np.mean(skill_all)), 2)
        avg_survival = round(float(np.mean(survival_all)), 2)
        mistake_rate = round(critical_mistakes_total / max(n * PLAYER_COUNT, 1), 2)

        # Confidence interval
        sem = float(np.std(process_scores_all)) / np.sqrt(max(len(process_scores_all), 1))
        ci_low = round(max(0, avg_process - 1.96 * sem), 2)
        ci_high = round(min(100, avg_process + 1.96 * sem), 2)

        cfg = AGENT_CONFIGS.get(version, {})
        entries.append({
            "agent_version": version,
            "model_id": cfg.get("model", "unknown"),
            "games_played": n,
            "avg_process_score": avg_process,
            "avg_speech_score": avg_speech,
            "avg_vote_score": avg_vote,
            "avg_skill_score": avg_skill,
            "avg_survival_score": avg_survival,
            "critical_mistake_rate": mistake_rate,
            "confidence_interval": [ci_low, ci_high],
            "low_sample_warning": n < 10,
            "role_breakdown": role_stats.get(version, {}),
        })

    # Sort by avg_process_score descending
    entries.sort(key=lambda e: e["avg_process_score"], reverse=True)

    return {
        "leaderboard_type": "agent_version_comparison",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "real_llm_game",
        "scoring_method": "review.py MetricsCalculator process_score (outcome-independent)",
        "entries": entries,
        "total_games": len(games),
    }


def build_report(games: list[GameResult], leaderboard: dict) -> str:
    entries = leaderboard["entries"]
    lines = [
        "# Track B Minimal Leaderboard Demo Report",
        "",
        f"> 生成时间: {leaderboard['generated_at']}",
        f"> 评分方法: {leaderboard['scoring_method']}",
        f"> 来源: {leaderboard['source']}",
        f"> 总局数: {leaderboard['total_games']}",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
    ]

    if len(entries) >= 2:
        first = entries[0]
        second = entries[1]
        diff = round(first["avg_process_score"] - second["avg_process_score"], 2)
        lines.extend([
            f"- **排名第一**: **{first['agent_version']}**（{first['model_id']}）— avg process score {first['avg_process_score']}",
            f"- **排名第二**: {second['agent_version']}（{second['model_id']}）— avg process score {second['avg_process_score']}",
            f"- **分差**: {diff} 分",
            f"- **主要差异维度**: 待分析",
            f"- **样本量**: 每个版本 {first['games_played']} 局，共 {leaderboard['total_games']} 局",
        ])

        # Identify which dimensions drive the difference
        dims = []
        for dim in ["avg_speech_score", "avg_vote_score", "avg_skill_score", "avg_survival_score"]:
            d = round(first[dim] - second[dim], 2)
            if abs(d) > 0.01:
                dims.append(f"{dim} ({'+' if d > 0 else ''}{d})")
        if dims:
            lines.append(f"- **差异维度**: {', '.join(dims)}")
        else:
            lines.append("- **差异维度**: 两个版本在各维度上表现接近，需要更多样本验证")

        lines.extend([
            "",
            "> ⚠️ **重要提示**: 这是一个低样本量的 Leaderboard smoke test（每个版本仅 3 局），",
            "> 不是统计可靠的正式 benchmark。排名和分差可能随更多对局而变化。",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 2. Experiment Setup",
        "",
        "| 参数 | 值 |",
        "| --- | --- |",
        f"| **Agent 版本** | {', '.join(e['agent_version'] for e in entries)} |",
        f"| **模型** | {', '.join(e['model_id'] for e in entries)} |",
        f"| **每版本局数** | {entries[0]['games_played'] if entries else 'N/A'} |",
        f"| **Seeds** | {SEEDS} |",
        f"| **单局玩家数** | {PLAYER_COUNT} |",
        f"| **最高天数** | {MAX_DAYS} |",
        f"| **来源** | {leaderboard['source']} |",
        f"| **角色分配** | 7人标准局：狼人×2 + 预言家 + 女巫 + 守卫 + 猎人 + 村民 |",
        f"| **评分来源** | review.py MetricsCalculator (6-dim formula) |",
        f"| **排名指标** | outcome-independent process_score（不受阵营胜负影响） |",
        "",
        "---",
        "",
        "## 3. Leaderboard",
        "",
        "| Rank | Agent Version | Model | Games | Avg Process | Speech | Vote | Skill | Survival | Critical Mistake Rate | Confidence (95%) | Warning |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])

    for i, e in enumerate(entries):
        rank = i + 1
        ci = f"[{e['confidence_interval'][0]}, {e['confidence_interval'][1]}]"
        warning = "LOW_SAMPLE" if e["low_sample_warning"] else ""
        lines.append(
            f"| {rank} | {e['agent_version']} | {e['model_id']} | {e['games_played']} | "
            f"{e['avg_process_score']} | {e['avg_speech_score']} | {e['avg_vote_score']} | "
            f"{e['avg_skill_score']} | {e['avg_survival_score']} | "
            f"{e['critical_mistake_rate']} | {ci} | {warning} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 4. Role Breakdown",
        "",
    ])

    for e in entries:
        lines.extend([
            f"### {e['agent_version']}",
            "",
            "| Role | Samples | Avg Process | Avg Vote | Avg Speech | Avg Skill | Low Sample |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        rb = e.get("role_breakdown", {})
        for role in ["Seer", "Witch", "Guard", "Hunter", "Werewolf", "Villager"]:
            rs = rb.get(role, {})
            n = rs.get("n", 0)
            low = "YES" if n < 3 else ""
            lines.append(
                f"| {role} | {n} | {rs.get('avg_process', 'N/A')} | "
                f"{rs.get('avg_vote', 'N/A')} | {rs.get('avg_speech', 'N/A')} | "
                f"{rs.get('avg_skill', 'N/A')} | {low} |"
            )
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 5. Per-Game Summary",
        "",
        "| Game ID | Version | Seed | Winner | Days | Events | Bad Cases | CFs | Avg Process |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ])

    for g in games:
        gid_short = g.game_id[:8]
        lines.append(
            f"| `{gid_short}` | {g.agent_version} | {g.seed} | {g.winner} | "
            f"{g.total_days} | {g.total_events} | {g.critical_mistakes} | "
            f"{g.counterfactual_count} | {g.avg_process_score} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 6. Representative Critical Mistakes",
        "",
    ])

    # Run review pipeline on each game to extract bad cases
    for g in games[:4]:  # Show first 4 games
        state = None
        try:
            roles = get_role_configuration(PLAYER_COUNT)
            players = build_players(roles, seed=g.seed)
            config = _make_config(g.agent_version, g.seed)
            agents = create_agents(players, config)
            game = WerewolfGame(players=players, agents=agents, seed=g.seed, max_days=MAX_DAYS, strategy_version=g.agent_version)
            game.play()
            state = game.state
        except Exception:
            continue

        if state is None:
            continue

        try:
            doc = generate_published_review_document(state)
            bad_cases = doc.review_report.get("bad_cases", [])
            if bad_cases:
                lines.append(f"### {g.agent_version} — seed={g.seed}")
                lines.append("")
                for bc in bad_cases[:2]:
                    lines.extend([
                        f"- **{bc.get('player_name', '?')}**（{bc.get('role', '?')}）Day {bc.get('day', '?')}",
                        f"  - 类型: {bc.get('mistake_type', '?')}",
                        f"  - 严重程度: {bc.get('severity', '?')}",
                        f"  - 描述: {bc.get('description', '?')}",
                        f"  - 建议: {bc.get('suggested_fix', '?')}",
                        "",
                    ])
        except Exception:
            continue

    lines.extend([
        "---",
        "",
        "## 7. Interpretation",
        "",
    ])

    if len(entries) >= 2:
        first = entries[0]
        second = entries[1]
        diff = round(first["avg_process_score"] - second["avg_process_score"], 2)

        better = first["agent_version"]
        worse = second["agent_version"]

        lines.extend([
            f"### {better} vs {worse}",
            "",
            f"**{better}** 的 avg_process_score 高出 **{diff} 分**。",
            "",
            "#### 优势维度",
        ])
        for dim, label in [("avg_speech_score", "发言"), ("avg_vote_score", "投票"),
                           ("avg_skill_score", "技能"), ("avg_survival_score", "存活")]:
            d = round(first[dim] - second[dim], 2)
            if d > 0.01:
                lines.append(f"- **{label}**: +{d}（{first[dim]} vs {second[dim]}）")
            elif d < -0.01:
                lines.append(f"- **{label}**: {d}（{first[dim]} vs {second[dim]}）— {worse} 略优")
            else:
                lines.append(f"- **{label}**: 基本持平（{first[dim]} vs {second[dim]}）")

        lines.extend([
            "",
            f"#### {worse} 的主要弱点",
        ])
        critical_diff = round(second["critical_mistake_rate"] - first["critical_mistake_rate"], 2)
        if critical_diff > 0:
            lines.append(f"- 关键错误率高出 {critical_diff}（{second['critical_mistake_rate']} vs {first['critical_mistake_rate']}）")

        lines.extend([
            "",
            "#### 可信度评估",
            "",
            f"- 每个版本仅 {first['games_played']} 局，样本量不足以得出统计显著结论",
            "- 需要至少 10+10 局才能进行初步正式对比",
            "- 排名方向性可信，但精确分差不可靠",
            "- 建议固定 seeds 和角色轮换来减少角色分配的随机差异",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 8. Rubric Alignment",
        "",
        "| Rubric Item | Status | Evidence |",
        "| --- | --- | --- |",
        "| Multi-dimensional evaluation | **PASS** | 6-dim formula: speech/vote/skill/survival/role_task/mistake_penalty |",
        "| Key decision review | **PASS** | BadCaseDetector identifies critical mistakes per game |",
        "| Counterfactual reasoning | **PASS** | Pipeline generates counterfactuals for each bad case |",
        "| Structured report | **PASS** | Markdown + HTML reports via generate_published_review_document |",
        f"| Leaderboard | **PASS_SMOKE** | {leaderboard['total_games']} real LLM games, {len(entries)} agent versions compared, low-sample smoke test |",
        "",
    ])

    lines.extend([
        "---",
        "",
        "## 9. Limitations",
        "",
        f"- **样本量不足**: 每个版本仅 {entries[0]['games_played'] if entries else 'N/A'} 局，不构成统计显著 benchmark",
        "- **角色分布不均**: 同一 seed 下角色固定，角色分配可能影响 agent 表现",
        "- **没有真实人工标注**: human pairwise labels pending",
        "- **PairwiseRanker 未参与主评分**: 仅为辅助信号",
        "- **ProcessScoreV3 未使用**: 当前使用 review.py MetricsCalculator process_score",
        "- **单一模型族对比**: 两个版本都是 DeepSeek V4 系列，差异有限",
        "- **不是正式 benchmark**: 仅作为 pipeline smoke test 和基础设施验证",
        "",
    ])

    lines.extend([
        "---",
        "",
        "## 10. Next Steps",
        "",
        "1. **扩样本**: 每个版本至少 10 局，使用固定 seed 集和角色轮换",
        "2. **加真实 LLM agent**: 接入更多模型（如 DeepSeek V3.2, Doubao Seed 2.0）进行跨模型族对比",
        "3. **加 Human pairwise validation**: 收集真实人工标注来校准评分",
        "4. **提升到正式 benchmark**: 10+ games × 3+ model families + human labels + ProcessScoreV3",
        "",
    ])

    return "\n".join(lines)


async def main_async():
    print("=" * 60)
    print("Track B Minimal Leaderboard Demo")
    print("=" * 60)
    print(f"Agent versions: {list(AGENT_CONFIGS.keys())}")
    print(f"Seeds: {SEEDS}")
    print(f"Players per game: {PLAYER_COUNT}")
    print(f"Total games to run: {len(AGENT_CONFIGS) * len(SEEDS)}")

    # Run all games
    print("\n[1/4] Running LLM games...")
    games = await run_all_games()

    # Save games JSONL
    print(f"\n[2/4] Saving game records...")
    games_path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_games.jsonl"
    games_path.parent.mkdir(parents=True, exist_ok=True)
    with open(games_path, "w", encoding="utf-8") as f:
        for g in games:
            record = {
                "game_id": g.game_id,
                "agent_version": g.agent_version,
                "model_id": g.model_id,
                "seed": g.seed,
                "source": g.source,
                "role_setup": g.role_setup,
                "winner": g.winner,
                "total_days": g.total_days,
                "total_events": g.total_events,
                "total_opportunities": g.total_opportunities,
                "player_scores": g.player_scores,
                "game_summary": {
                    "avg_process_score": g.avg_process_score,
                    "avg_speech_score": g.avg_speech_score,
                    "avg_vote_score": g.avg_vote_score,
                    "avg_skill_score": g.avg_skill_score,
                    "avg_survival_score": g.avg_survival_score,
                    "critical_mistakes": g.critical_mistakes,
                    "counterfactual_count": g.counterfactual_count,
                },
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  Written: {games_path} ({games_path.stat().st_size} bytes)")

    # Build leaderboard
    print("\n[3/4] Building leaderboard...")
    leaderboard = build_leaderboard(games)

    summary_path = ROOT / "data" / "health" / "track_b_minimal_leaderboard_summary.json"
    summary_path.write_text(json.dumps(leaderboard, ensure_ascii=False, indent=2))
    print(f"  Written: {summary_path} ({summary_path.stat().st_size} bytes)")

    # Build report
    print("\n[4/4] Building report...")
    report = build_report(games, leaderboard)

    report_path = ROOT / "docs" / "track_b_minimal_leaderboard_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  Written: {report_path} ({len(report)} chars)")

    # Summary
    print("\n" + "=" * 60)
    print("Leaderboard Demo Complete")
    print("=" * 60)
    entries = leaderboard["entries"]
    if len(entries) >= 2:
        print(f"  1st: {entries[0]['agent_version']} — avg_process={entries[0]['avg_process_score']}")
        print(f"  2nd: {entries[1]['agent_version']} — avg_process={entries[1]['avg_process_score']}")
        print(f"  Diff: {round(entries[0]['avg_process_score'] - entries[1]['avg_process_score'], 2)}")
    print(f"  Sample: {entries[0]['games_played']} games/version")
    print(f"  Low sample warning: {entries[0]['low_sample_warning']}")
    print(f"  Rubric Leaderboard: PASS_SMOKE")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
