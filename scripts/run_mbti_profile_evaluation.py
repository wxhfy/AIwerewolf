#!/usr/bin/env python3
"""Track B MBTI/Profile Evaluation v0.

Runs same-profile games with 4 MBTI-style strategy profiles on deepseek-v4-pro.
Collects process scores, speech semantic audit features, and generates report.

Usage:
  python scripts/run_mbti_profile_evaluation.py
  python scripts/run_mbti_profile_evaluation.py --seeds 100,200,300
  python scripts/run_mbti_profile_evaluation.py --games-per-profile 5
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agents.characters import _hydrate_persona
from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.engine.rules import get_role_configuration
from backend.eval.heads.speech_semantic import SpeechSemanticScorer
from backend.eval.opportunity import OpportunityExtractor
from backend.eval.track_b import ReplayBundleBuilder
from backend.eval.track_b import generate_published_review_document

# ===========================================================================
# MBTI Profile Definitions
# ===========================================================================

MBTI_PROFILES = {
    "INTJ-strategist": {
        "mbti": "INTJ",
        "style_label": "analytical",
        "voice_rules": [
            "做长线推理，少说废话",
            "每次发言至少引用一个公开事实",
            "避免无证据的断言",
            "投票前先在心中排除非狼选项",
        ],
        "vocabulary_style": "academic",
        "speech_length_habit": "detailed",
        "reasoning_style": "logical_chain",
        "social_habit": "lone_wolf",
        "pressure_style": "calm",
        "uncertainty_style": "admit_ignorance",
        "wolf_deception_style": "identity_hiding",
        "description": "长线规划，重视证据和反事实推理，发言精准克制",
    },
    "ENTJ-shotcaller": {
        "mbti": "ENTJ",
        "style_label": "aggressive",
        "voice_rules": [
            "积极主导归票方向",
            "用总结性发言引导团队决策",
            "快速锁定目标，不拖泥带水",
            "发言要有方向感，避免信息过载",
        ],
        "vocabulary_style": "terse",
        "speech_length_habit": "short_and_punchy",
        "reasoning_style": "logical_chain",
        "social_habit": "leader",
        "pressure_style": "counter_attack",
        "uncertainty_style": "overcompensate",
        "wolf_deception_style": "aggressive_framing",
        "description": "强势归票，主动领导，快速决策，善于推动票型",
    },
    "ENFP-social-chaotic": {
        "mbti": "ENFP",
        "style_label": "chaotic",
        "voice_rules": [
            "积极发言，高互动频率",
            "对新信息保持开放，可以灵活调整立场",
            "多用追问和假设性发言",
            "表达风格生动有趣",
        ],
        "vocabulary_style": "dramatic",
        "speech_length_habit": "storyteller",
        "reasoning_style": "gut_feeling",
        "social_habit": "mediator",
        "pressure_style": "deflect",
        "uncertainty_style": "admit_ignorance",
        "wolf_deception_style": "social_manipulation",
        "description": "高互动、多发言、信息开放、容易被新发言影响",
    },
    "ISTJ-conservative": {
        "mbti": "ISTJ",
        "style_label": "passive",
        "voice_rules": [
            "只基于确认的公开信息发言",
            "不轻易毒、枪、跳身份",
            "优先安全行动，避免高风险操作",
            "稳定执行角色职责，不冒险",
        ],
        "vocabulary_style": "colloquial",
        "speech_length_habit": "short_and_punchy",
        "reasoning_style": "comparative",
        "social_habit": "follower",
        "pressure_style": "defensive",
        "uncertainty_style": "stay_quiet",
        "wolf_deception_style": "low_profile",
        "description": "证据优先、低风险、稳定执行、不冒进",
    },
}

# Shared model config
BASE_MODEL = "deepseek-v4-pro[1m]"


def _make_persona_dict(profile_name: str, profile: dict, player_name: str) -> dict:
    """Build a PERSONA_POOL-compatible dict for a profile."""
    return {
        "name": player_name,
        "mbti": profile["mbti"],
        "gender": "male",
        "age": 30,
        "basic_info": f"AI player with {profile_name} strategy profile. {profile['description']}",
        "style_label": profile["style_label"],
        "voice_rules": profile["voice_rules"],
        "vocabulary_style": profile["vocabulary_style"],
        "speech_length_habit": profile["speech_length_habit"],
        "reasoning_style": profile["reasoning_style"],
        "social_habit": profile["social_habit"],
        "humor_style": "dry",
        "pressure_style": profile["pressure_style"],
        "uncertainty_style": profile["uncertainty_style"],
        "wolf_deception_style": profile.get("wolf_deception_style", ""),
        "mistake_pattern": "",
        "logic_style": profile["reasoning_style"],
        "trigger_topics": [],
        "werewolf_experience": "experienced",
        "system_prompt": "",
    }


# ===========================================================================
# Game Runner
# ===========================================================================


async def run_profile_game(profile_name: str, seed: int, player_count: int = 7) -> dict:
    """Run one game where all players share the same MBTI profile."""
    profile = MBTI_PROFILES[profile_name]
    roles = get_role_configuration(player_count)
    players = build_players(roles, seed=seed)
    player_names = [p.name for p in players]

    # Build persona dicts for each player (same profile, different names)
    sampled_personas = [_make_persona_dict(profile_name, profile, name) for name in player_names]

    config = {
        "type": "llm",
        "seed": seed,
        "provider": "doubao",
        "model": BASE_MODEL,
        "api_key": os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
        "base_url": os.getenv("ANTHROPIC_BASE_URL", ""),
    }
    agents = create_agents(players, config)

    # Inject custom personas into agents BEFORE initialize
    persona_objs = [_hydrate_persona(pd) for pd in sampled_personas]
    for i, (_pid, agent) in enumerate(agents.items()):
        if hasattr(agent, "character") and agent.character:
            agent.character.persona = persona_objs[i]

    game = WerewolfGame(
        players=players,
        agents=agents,
        seed=seed,
        max_days=5,
        strategy_version=f"mbti-{profile_name}",
    )

    t0 = time.perf_counter()
    game.play()
    elapsed = time.perf_counter() - t0
    state = game.state
    winner = state.winner.value if state.winner else "unknown"

    # Full review
    doc = generate_published_review_document(state)
    doc.review_report.get("scoreboard", [])
    player_scores_list = doc.review_report.get("metadata", {}).get("player_scores", [])
    bad_cases = doc.review_report.get("bad_cases", [])
    counterfactuals = doc.review_report.get("counterfactuals", [])

    # Extract opportunities
    bundle = ReplayBundleBuilder().build(state)
    opps = [op.to_dict() for op in OpportunityExtractor().extract(bundle)]

    # Build player scores
    player_scores = []
    process_scores = []
    speech_scores = []
    vote_scores = []
    skill_scores = []
    survival_scores = []

    for ps in player_scores_list:
        player_scores.append(
            {
                "player_id": ps.get("player_id", ""),
                "player_name": ps.get("player_name", ""),
                "role": ps.get("role", ""),
                "alignment": ps.get("alignment", ""),
                "final_score": ps.get("final_score", 0),
                "process_score": ps.get("process_score", 0),
                "speech_score": ps.get("speech_score", 0) or 0,
                "vote_score": ps.get("vote_score", 0) or 0,
                "skill_score": ps.get("skill_score", 0) or 0,
                "survival_score": ps.get("survival_score", 0) or 0,
            }
        )
        process_scores.append(ps.get("process_score", 0) or 0)
        speech_scores.append(ps.get("speech_score", 0) or 0)
        vote_scores.append(ps.get("vote_score", 0) or 0)
        skill_scores.append(ps.get("skill_score", 0) or 0)
        survival_scores.append(ps.get("survival_score", 0) or 0)

    # Speech semantic audit
    scorer = SpeechSemanticScorer()
    speech_audit_features: dict[str, list[float]] = defaultdict(list)
    speech_act_probs: dict[str, list[float]] = defaultdict(list)

    for event in state.events:
        speech_text = ""
        if hasattr(event, "payload") and isinstance(event.payload, dict):
            speech_text = str(event.payload.get("speech", ""))
        if speech_text:
            result = scorer.score(speech_text)
            for feat, val in result.audit_features.items():
                speech_audit_features[feat].append(float(val))
            for act, val in result.speech_act_probs.items():
                speech_act_probs[act].append(float(val))

    len(player_scores_list) or 1
    role_setup = {p.id: p.role.value for p in state.players}
    role_dist = {}
    for r in role_setup.values():
        role_dist[r] = role_dist.get(r, 0) + 1

    print(
        f"  [{profile_name}] seed={seed} winner={winner} days={state.day} "
        f"events={len(state.events)} badcases={len(bad_cases)} time={elapsed:.0f}s"
    )

    return {
        "game_id": state.id,
        "profile": profile_name,
        "model": BASE_MODEL,
        "seed": seed,
        "source": "real_llm_game",
        "winner": winner,
        "total_days": state.day,
        "total_events": len(state.events),
        "total_opportunities": len(opps),
        "role_setup": role_setup,
        "role_distribution": role_dist,
        "player_scores": player_scores,
        "bad_cases": [
            {
                "player_name": bc.get("player_name", ""),
                "role": bc.get("role", ""),
                "day": bc.get("day", 0),
                "severity": bc.get("severity", ""),
                "description": bc.get("description", ""),
                "suggested_fix": bc.get("suggested_fix", ""),
            }
            for bc in bad_cases
        ],
        "counterfactual_count": len(counterfactuals),
        "critical_mistake_count": len(bad_cases),
        "avg_process_score": round(float(np.mean(process_scores)), 2),
        "avg_speech_score": round(float(np.mean(speech_scores)), 2),
        "avg_vote_score": round(float(np.mean(vote_scores)), 2),
        "avg_skill_score": round(float(np.mean(skill_scores)), 2),
        "avg_survival_score": round(float(np.mean(survival_scores)), 2),
        "speech_audit": {
            feat: round(float(np.mean(vals)), 4) if vals else 0.0 for feat, vals in speech_audit_features.items()
        },
        "speech_act_distribution": {
            act: round(float(np.mean(vals)), 4) if vals else 0.0 for act, vals in speech_act_probs.items()
        },
    }


async def run_all(profiles: list[str], seeds: list[int]) -> list[dict]:
    results = []
    for profile_name in profiles:
        print(f"\n{'=' * 50}")
        print(f"Profile: {profile_name}")
        print(f"{'=' * 50}")
        for seed in seeds:
            result = await run_profile_game(profile_name, seed)
            results.append(result)
    return results


# ===========================================================================
# Aggregation & Report
# ===========================================================================


def build_leaderboard(games: list[dict]) -> dict:
    by_profile: dict[str, list[dict]] = defaultdict(list)
    for g in games:
        by_profile[g["profile"]].append(g)

    entries = []
    for profile_name, game_list in sorted(by_profile.items()):
        n = len(game_list)
        all_process = []
        all_speech = []
        all_vote = []
        all_skill = []
        all_survival = []
        total_mistakes = 0
        total_cf = 0
        wins = 0
        all_audit: dict[str, list[float]] = defaultdict(list)
        all_acts: dict[str, list[float]] = defaultdict(list)
        role_games: dict[str, int] = defaultdict(int)

        for g in game_list:
            for ps in g["player_scores"]:
                all_process.append(ps["process_score"])
                all_speech.append(ps["speech_score"])
                all_vote.append(ps["vote_score"])
                all_skill.append(ps["skill_score"])
                all_survival.append(ps["survival_score"])
            total_mistakes += g["critical_mistake_count"]
            total_cf += g["counterfactual_count"]
            if g["winner"] == "village":
                wins += 1
            for feat, val in g.get("speech_audit", {}).items():
                all_audit[feat].append(val)
            for act, val in g.get("speech_act_distribution", {}).items():
                all_acts[act].append(val)
            for role, count in g.get("role_distribution", {}).items():
                role_games[role] += count

        avg_process = round(float(np.mean(all_process)), 2)
        sem = float(np.std(all_process)) / max(np.sqrt(len(all_process)), 1)

        entries.append(
            {
                "profile": profile_name,
                "mbti": MBTI_PROFILES[profile_name]["mbti"],
                "description": MBTI_PROFILES[profile_name]["description"],
                "games_played": n,
                "avg_process_score": avg_process,
                "avg_speech_score": round(float(np.mean(all_speech)), 2),
                "avg_vote_score": round(float(np.mean(all_vote)), 2),
                "avg_skill_score": round(float(np.mean(all_skill)), 2),
                "avg_survival_score": round(float(np.mean(all_survival)), 2),
                "critical_mistake_rate": round(total_mistakes / max(n * 7, 1), 2),
                "counterfactual_coverage": round(total_cf / max(total_mistakes, 1), 2) if total_mistakes > 0 else 1.0,
                "win_rate": round(wins / max(n, 1), 2),
                "confidence_interval": [
                    round(max(0, avg_process - 1.96 * sem), 2),
                    round(min(100, avg_process + 1.96 * sem), 2),
                ],
                "low_sample_warning": n < 10,
                "speech_audit": {feat: round(float(np.mean(vals)), 4) for feat, vals in all_audit.items()},
                "speech_act_distribution": {act: round(float(np.mean(vals)), 4) for act, vals in all_acts.items()},
                "role_distribution": dict(role_games),
            }
        )

    entries.sort(key=lambda e: e["avg_process_score"], reverse=True)
    return {"entries": entries, "total_games": len(games), "base_model": BASE_MODEL}


def build_report(games: list[dict], leaderboard: dict) -> str:
    E = leaderboard["entries"]

    def e_profile(name):
        for e in E:
            if e["profile"] == name:
                return e
        return E[0] if E else {}

    lines = [
        "# Track B MBTI/Profile Evaluation v0 Report",
        "",
        f"> Base model: {BASE_MODEL}",
        f"> Total games: {leaderboard['total_games']}",
        "> Source: real_llm_game (same-profile mode)",
        f"> Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
    ]

    if len(E) >= 2:
        first = E[0]
        last = E[-1]
        lines.extend(
            [
                f"- **最高 process score**: **{first['profile']}** ({first['mbti']}) — {first['avg_process_score']}",
                f"- **最低 process score**: {last['profile']} ({last['mbti']}) — {last['avg_process_score']}",
                f"- **分差**: {round(first['avg_process_score'] - last['avg_process_score'], 2)}",
            ]
        )

    # Find biggest dimension differences
    for dim, label in [
        ("avg_speech_score", "发言"),
        ("avg_vote_score", "投票"),
        ("avg_skill_score", "技能"),
        ("avg_survival_score", "存活"),
    ]:
        vals = [e[dim] for e in E]
        round(max(vals) - min(vals), 2)
        top_e = max(E, key=lambda e: e[dim])
        lines.append(f"- **{label}最高**: {top_e['profile']} ({top_e[dim]})")

    lines.extend(
        [
            "",
            "> ⚠️ **重要提示**: MBTI 标签是 strategy profiles（策略画像），不是心理学真实性验证。",
            f"> 每个 profile 仅 {E[0]['games_played']} 局，属于低样本 smoke test。",
            "",
        ]
    )

    # --- Experiment Setup ---
    lines.extend(
        [
            "---",
            "",
            "## 2. Experiment Setup",
            "",
            "| 参数 | 值 |",
            "| --- | --- |",
            f"| **底座模型** | {BASE_MODEL} |",
            f"| **Profiles** | {len(E)} 个 MBTI-style strategy profiles |",
            f"| **每 profile 局数** | {E[0]['games_played']} |",
            "| **模式** | same-profile（同局所有玩家使用相同 profile） |",
            "| **单局玩家数** | 7 |",
            "| **来源** | real_llm_game |",
            "| **评分来源** | review.py MetricsCalculator process_score |",
            "",
            "### Profiles",
            "",
            "| Profile | MBTI | Style | Description |",
            "| --- | --- | --- | --- |",
        ]
    )
    for e in E:
        lines.append(
            f"| {e['profile']} | {e['mbti']} | {MBTI_PROFILES[e['profile']]['style_label']} | {e['description']} |"
        )

    # --- Leaderboard ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Profile Leaderboard",
            "",
            "| Rank | Profile | Games | Process | Speech | Vote | Skill | Survival | Critical Rate | Win Rate | CI (95%) | Warning |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for i, e in enumerate(E):
        ci = f"[{e['confidence_interval'][0]}, {e['confidence_interval'][1]}]"
        warning = "LOW_SAMPLE" if e["low_sample_warning"] else ""
        lines.append(
            f"| {i + 1} | {e['profile']} | {e['games_played']} | {e['avg_process_score']} | "
            f"{e['avg_speech_score']} | {e['avg_vote_score']} | {e['avg_skill_score']} | "
            f"{e['avg_survival_score']} | {e['critical_mistake_rate']} | {e['win_rate']} | {ci} | {warning} |"
        )

    # --- Speech Act Distribution ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## 4. Speech Act Distribution",
            "",
            "> 来自 SpeechSemanticScorer v0 (audit-only, 不影响主分)",
            "",
            "| Profile | Evidence Grounding | Actionability | Identity Claim | Pressure | Info Seeking | Defensive |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for e in E:
        sa = e.get("speech_audit", {})
        lines.append(
            f"| {e['profile']} | {sa.get('evidence_grounding_signal', 0):.3f} | "
            f"{sa.get('actionability_signal', 0):.3f} | {sa.get('identity_claim_signal', 0):.3f} | "
            f"{sa.get('pressure_signal', 0):.3f} | {sa.get('information_seeking_signal', 0):.3f} | "
            f"{sa.get('defensive_posture_signal', 0):.3f} |"
        )

    # --- Expected vs Observed ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## 5. Expected vs Observed",
            "",
            "| Profile | Expected Behavior | Observed Pattern | Match? |",
            "| --- | --- | --- | --- |",
        ]
    )
    expectations = {
        "INTJ-strategist": (
            "高 evidence_grounding, 低 defensive_posture, 低 critical mistake rate",
            lambda e: (
                e.get("speech_audit", {}).get("evidence_grounding_signal", 0) > 0.3 and e["critical_mistake_rate"] < 0.3
            ),
        ),
        "ENTJ-shotcaller": (
            "高 actionability, 高 pressure, 高 vote_score",
            lambda e: e.get("speech_audit", {}).get("actionability_signal", 0) > 0.15 and e["avg_vote_score"] > 0.5,
        ),
        "ENFP-social-chaotic": (
            "高 information_seeking, 高 defensive_posture, speech 波动大",
            lambda e: e.get("speech_audit", {}).get("information_seeking_signal", 0) > 0.35,
        ),
        "ISTJ-conservative": (
            "低 critical mistake rate, 低 identity_claim",
            lambda e: (
                e["critical_mistake_rate"] < 0.3 and e.get("speech_audit", {}).get("identity_claim_signal", 0) < 0.25
            ),
        ),
    }
    for e in E:
        exp_text, check_fn = expectations.get(e["profile"], ("", lambda _: False))
        match_status = "partial" if check_fn(e) else "weak"
        sa = e.get("speech_audit", {})
        obs = f"evidence={sa.get('evidence_grounding_signal', 0):.2f}, action={sa.get('actionability_signal', 0):.2f}, critical_rate={e['critical_mistake_rate']}"
        lines.append(f"| {e['profile']} | {exp_text} | {obs} | {match_status} |")

    # --- Dimension Breakdown ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## 6. Dimension Breakdown",
            "",
            "| Profile | Main Strength | Main Weakness | Evidence |",
            "| --- | --- | --- | --- |",
        ]
    )
    for e in E:
        dims = {k: e.get(k, 0) for k in ["avg_speech_score", "avg_vote_score", "avg_skill_score", "avg_survival_score"]}
        best_dim = max(dims, key=dims.get)
        worst_dim = min(dims, key=dims.get)
        dim_labels = {
            "avg_speech_score": "发言",
            "avg_vote_score": "投票",
            "avg_skill_score": "技能",
            "avg_survival_score": "存活",
        }
        lines.append(
            f"| {e['profile']} | {dim_labels[best_dim]} ({dims[best_dim]}) | {dim_labels[worst_dim]} ({dims[worst_dim]}) | {best_dim}={dims[best_dim]}, {worst_dim}={dims[worst_dim]} |"
        )

    # --- Role Breakdown ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## 7. Role Breakdown",
            "",
            "| Profile | Role | Samples | Low Sample |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for e in E:
        for role, count in sorted(e.get("role_distribution", {}).items()):
            low = "YES" if count < 3 else ""
            lines.append(f"| {e['profile']} | {role} | {count} | {low} |")

    # --- Representative Reviews ---
    lines.extend(
        [
            "",
            "---",
            "",
            "## 8. Representative Reviews",
            "",
        ]
    )
    for e in E:
        profile_games = [g for g in games if g["profile"] == e["profile"]]
        lines.append(f"### {e['profile']} ({e['mbti']})")
        lines.append("")
        shown = 0
        for g in profile_games:
            for bc in g.get("bad_cases", [])[:1]:
                if shown >= 2:
                    break
                lines.extend(
                    [
                        f"- **{bc['player_name']}** ({bc['role']}) Day {bc['day']} — {bc['severity']}",
                        f"  - 描述: {bc['description']}",
                        f"  - 建议: {bc['suggested_fix']}",
                        "",
                    ]
                )
                shown += 1
            if shown >= 2:
                break
        if shown == 0:
            lines.append("*本 profile 未检测到关键错误。*")
            lines.append("")

    # --- Validity Evidence ---
    lines.extend(
        [
            "---",
            "",
            "## 9. Validity Evidence",
            "",
            "### 9.1 Sensitivity",
            "",
            "不同 profile 是否产生可见的维度差异？",
            "",
        ]
    )
    # Check process score range
    process_range = round(max(e["avg_process_score"] for e in E) - min(e["avg_process_score"] for e in E), 2)
    speech_audit_range = round(
        max(e.get("speech_audit", {}).get("evidence_grounding_signal", 0) for e in E)
        - min(e.get("speech_audit", {}).get("evidence_grounding_signal", 0) for e in E),
        3,
    )
    lines.extend(
        [
            f"- Process score 跨 profile 范围: **{process_range}** 分",
            f"- Speech audit evidence_grounding 范围: **{speech_audit_range}**",
            f"- 存在维度级差异: {'是' if process_range > 2 else '有限'}",
            "",
            "### 9.2 Specificity",
            "",
            "差异是否落在预期维度？",
            "",
            "见 §5 Expected vs Observed 表。",
            "",
            "### 9.3 Reviewability",
            "",
            "见 §8 Representative Reviews。",
            "",
            "### 9.4 Robustness",
            "",
            f"- 每个 profile 仅 {E[0]['games_played']} 局，趋势不可靠",
            "- 同一 profile 内各 seed 间存在随机波动",
            "- 需要 ≥10 局/profile 才能做稳健性判断",
            "- 当前仅提供方向性信号",
            "",
        ]
    )

    # --- Limitations ---
    lines.extend(
        [
            "---",
            "",
            "## 10. Limitations",
            "",
            "- **MBTI 标签是 strategy profiles**，不是心理学真实性验证",
            f"- **低样本**: 每个 profile 仅 {E[0]['games_played']} 局，不构成统计显著结论",
            "- **SpeechSemanticScorer 是 audit-only**，不影响 process score",
            "- **speech act ≠ speech quality**：发言行为分类不等于发言质量",
            "- **无人工验证**: 没有 human pairwise labels 或 speech quality labels",
            "- **same-profile 模式**: 同局内所有玩家使用相同 profile，未测试 mixed-profile 对抗",
            "- **PairwiseRanker 保持 audit/debug only**",
            "",
        ]
    )

    # --- Next Steps ---
    lines.extend(
        [
            "---",
            "",
            "## 11. Next Steps",
            "",
            "1. **扩样本**: 每个 profile 至少 10 局",
            "2. **Mixed-profile rotation**: 同局内混合不同 profile 对抗",
            "3. **人工复核**: 30 个 critical decisions 的 human review",
            "4. **Speech semantic human validation**: ≥50 speech samples with human quality labels",
            "5. **Cross-model**: 在固定 profile 下比较不同底座模型",
            "",
        ]
    )

    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================


async def main_async(seeds: list[int], games_per_profile: int):
    profiles = list(MBTI_PROFILES.keys())
    seeds = seeds[:games_per_profile]

    print("=" * 60)
    print("Track B MBTI/Profile Evaluation v0")
    print("=" * 60)
    print(f"Profiles: {profiles}")
    print(f"Seeds: {seeds}")
    print(f"Total games: {len(profiles) * len(seeds)}")

    print("\n[1/3] Running games...")
    games = await run_all(profiles, seeds)

    # Save games
    games_path = ROOT / "data" / "health" / "track_b_mbti_profile_games.jsonl"
    games_path.parent.mkdir(parents=True, exist_ok=True)
    with open(games_path, "w", encoding="utf-8") as f:
        for g in games:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"\n[2/3] Games saved: {games_path} ({len(games)} records)")

    # Build leaderboard & report
    leaderboard = build_leaderboard(games)
    summary_path = ROOT / "data" / "health" / "track_b_mbti_profile_summary.json"
    summary_path.write_text(json.dumps(leaderboard, ensure_ascii=False, indent=2))
    print(f"  Summary saved: {summary_path}")

    print("\n[3/3] Building report...")
    report = build_report(games, leaderboard)
    report_path = ROOT / "docs" / "track_b_mbti_profile_evaluation_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  Report saved: {report_path} ({len(report)} chars)")

    # Summary
    print("\n" + "=" * 60)
    print("MBTI Profile Evaluation Complete")
    print("=" * 60)
    for e in leaderboard["entries"]:
        print(
            f"  {e['profile']} ({e['mbti']}): process={e['avg_process_score']}, "
            f"speech={e['avg_speech_score']}, vote={e['avg_vote_score']}, "
            f"skill={e['avg_skill_score']}, mistakes={e['critical_mistake_rate']}"
        )


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="100,200,300", help="Comma-separated seeds")
    parser.add_argument("--games-per-profile", type=int, default=3)
    args = parser.parse_args()
    seeds = [int(s.strip()) for s in args.seeds.split(",")]
    asyncio.run(main_async(seeds, args.games_per_profile))


if __name__ == "__main__":
    main()
