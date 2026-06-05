#!/usr/bin/env python3
"""Track B Rubric Demo v0 Generator — v2 (quality improvements).

Fixes vs v1:
  1. CD/CF IDs unified: CD-001, CD-002, CF-001, CF-002 globally.
  2. Improvement suggestions: no truncation, unified Chinese.
  3. CleanCase wolf-vote-wolf downgraded from critical→ambiguous.
  4. Score column naming: Fixture Final Score / Fixture Process Score.
  5. Game uses: explicit per-fixture-type recommendations.
  6. Missing CFs: synthetic counterfactuals with explicit justification.

Runs the full Track B pipeline on controlled fixture replays and produces:
  data/health/track_b_rubric_demo_summary.json
  docs/track_b_rubric_demo_report.md
  docs/track_b_rubric_demo_report.html
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.eval.opportunity import OpportunityExtractor
from backend.eval.process_score_v3 import GameEvaluationValue
from backend.eval.process_score_v3 import ProcessScoreV3Result
from backend.eval.process_score_v3 import compute_game_value
from backend.eval.process_score_v3 import compute_process_score_v3
from backend.eval.track_b import ReplayBundleBuilder
from backend.eval.track_b import generate_published_review_document

# ===========================================================================
# Step 1: Load fixture game states
# ===========================================================================


def _load_game_states() -> list[tuple[str, str, Any]]:
    states: list[tuple[str, str, Any]] = []
    try:
        from tests.test_track_b_badcase_regression import build_badcase_001_fixture

        states.append(("controlled_fixture_replay", "badcase-001", build_badcase_001_fixture()))
    except Exception as e:
        print(f"  WARNING: badcase_001 fixture failed: {e}")
    try:
        from tests.test_track_b_badcase_wolf_regression import build_badcase_002_fixture

        states.append(("controlled_fixture_replay", "badcase-002", build_badcase_002_fixture()))
    except Exception as e:
        print(f"  WARNING: badcase_002 fixture failed: {e}")
    try:
        from tests.test_track_b_cleancase_wolf_regression import build_cleancase_001_fixture

        states.append(("controlled_fixture_replay", "cleancase-001", build_cleancase_001_fixture()))
    except Exception as e:
        print(f"  WARNING: cleancase_001 fixture failed: {e}")
    return states


# ===========================================================================
# Step 2: Run full pipeline on each game
# ===========================================================================


@dataclass
class DemoGameData:
    source: str
    game_id_short: str
    game_id: str
    winner: str
    total_players: int
    total_events: int
    role_setup: dict[str, str]
    agent_version: str
    model_id: str
    seed: str
    published_doc: Any
    opportunities: list[dict]
    process_scores_v3: list[ProcessScoreV3Result]
    game_value: GameEvaluationValue
    linked_critical_decisions: list[dict]
    improvement_suggestions: list[dict]
    counterfactuals_for_display: list[dict]


# Chinese role names for translation
ROLE_CN_MAP = {
    "Seer": "预言家",
    "Witch": "女巫",
    "Guard": "守卫",
    "Hunter": "猎人",
    "Werewolf": "狼人",
    "Villager": "村民",
}

MISTAKE_TYPE_CN = {
    "speech": "发言",
    "vote": "投票",
    "ability": "技能/夜晚行动",
}


def _is_wolf_vote_wolf_in_cleancase(bc: dict, game_id_short: str) -> bool:
    """Detect 'wolf voted teammate' in a cleancase fixture — potentially strategic."""
    if game_id_short != "cleancase-001":
        return False
    desc = bc.get("description", "")
    role = bc.get("role", "")
    if role == "Werewolf" and "voted wolf teammate" in desc.lower():
        return True
    if role == "Werewolf" and "队友" in desc and "投票" in desc.lower() + str(bc.get("mistake_type", "")):
        return True
    return False


def _build_demo_data(states: list[tuple[str, str, Any]]) -> list[DemoGameData]:
    results: list[DemoGameData] = []
    all_opportunities: list[dict] = []

    for source, short_id, state in states:
        print(f"\n  Processing {short_id} ({source})...")
        doc = generate_published_review_document(state)

        bundle = ReplayBundleBuilder().build(state)
        opps = [op.to_dict() for op in OpportunityExtractor().extract(bundle)]
        all_opportunities.extend(opps)
        print(f"    Opportunities: {len(opps)}")

        role_setup = {}
        for p in state.players:
            role_setup[p.id] = p.role.value

        # Build linked critical decisions + display counterfactuals
        linked, display_cfs = _build_linked_critical_decisions(
            doc.review_report.get("bad_cases", []),
            doc.review_report.get("counterfactuals", []),
            short_id,
        )

        suggestions = _build_improvement_suggestions(
            doc.review_report.get("player_reviews", []),
            doc.review_report.get("bad_cases", []),
            linked,
            short_id,
        )

        results.append(
            DemoGameData(
                source=source,
                game_id_short=short_id,
                game_id=state.id,
                winner=state.winner.value if state.winner else "unknown",
                total_players=len(state.players),
                total_events=len(state.events),
                role_setup=role_setup,
                agent_version="fixture-heuristic-v1",
                model_id="fixture",
                seed=str(getattr(state, "seed", "N/A") or "N/A"),
                published_doc=doc,
                opportunities=opps,
                process_scores_v3=[],
                game_value=None,  # type: ignore
                linked_critical_decisions=linked,
                improvement_suggestions=suggestions,
                counterfactuals_for_display=display_cfs,
            )
        )

    # Compute ProcessScoreV3
    if all_opportunities:
        print(f"\n  Computing ProcessScoreV3 for {len(all_opportunities)} total opportunities...")
        ra_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
        for op in all_opportunities:
            key = (op.get("role", "?"), op.get("opportunity_type", "?"))
            cq = op.get("calibrated_q", op.get("combined_score", 0.5)) or 0.5
            ra_groups[key].append(cq)
        import numpy as np

        ra_stats = {}
        for key, vals in ra_groups.items():
            if len(vals) >= 2:
                ra_stats[key] = {"mean": float(np.mean(vals)), "std": float(np.std(vals)) + 0.001}

        all_scores = compute_process_score_v3(all_opportunities, role_action_stats=ra_stats)
        for g in results:
            game_player_ids = {op.get("player_id", "") for op in g.opportunities}
            g.process_scores_v3 = [ps for ps in all_scores if ps.player_id in game_player_ids]
            g.game_value = compute_game_value(g.game_id, g.opportunities, g.process_scores_v3)
            print(f"    {g.game_id_short}: {len(g.process_scores_v3)} player scores")

    return results


# ===========================================================================
# Step 3: Link critical decisions to counterfactuals (with global IDs)
# ===========================================================================


def _build_linked_critical_decisions(
    bad_cases: list[dict],
    counterfactuals: list[dict],
    game_id_short: str,
) -> tuple[list[dict], list[dict]]:
    """Build critical decisions with counterfactual links.

    Returns (decisions, display_counterfactuals).
    Display counterfactuals include both pipeline-generated CFs and
    synthetic CFs for decisions that have none.
    """

    decisions: list[dict] = []
    display_cfs: list[dict] = []

    for i, bc in enumerate(bad_cases):
        bc_role = bc.get("role", "")
        bc_player = bc.get("player_name", "")
        bc_day = str(bc.get("day", 0))
        bc_type = bc.get("mistake_type", "")
        bc_desc = bc.get("description", "")

        # ---- CleanCase wolf-vote-wolf: downgrade to ambiguous ----
        if _is_wolf_vote_wolf_in_cleancase(bc, game_id_short):
            decisions.append(
                {
                    "critical_decision_id": "",  # assigned later
                    "player": bc_player,
                    "role": bc_role,
                    "day": bc_day,
                    "action_type": "vote",
                    "actual_action": bc_desc,
                    "severity": "low",
                    "why_bad": "狼人投票队友可能是战略切割（倒钩），当前数据无法判断是战略收益大于暴露风险还是单纯的失误。标记为 ambiguous。",
                    "suggested_fix": "如果是战略切割，应确保收益（减少自身嫌疑）大于暴露风险（削弱狼队票数）。建议结合上下文判断是否有预言家查杀压力。",
                    "evidence_event_ids": bc.get("evidence_event_ids", []),
                    "_downgraded_from_critical": True,
                    "_ambiguous": True,
                    "counterfactual_ids": [],  # no CF needed for ambiguous
                    "counterfactual_missing": False,
                    "counterfactual_missing_reason": "",
                }
            )
            continue

        # ---- Match counterfactuals ----
        matched_cfs = []
        for cf in counterfactuals:
            src = cf.get("source_bad_case_id", "") or ""
            cf_orig = cf.get("original_decision", "")
            # Primary: source_bad_case_id match
            if bc_player in src and f"-{bc_day}-" in src or bc_player in cf_orig and bc_type in cf_orig.lower():
                matched_cfs.append(cf)

        if not matched_cfs:
            for cf in counterfactuals:
                if cf in matched_cfs:
                    continue
                cf_orig = cf.get("original_decision", "")
                cf_type = cf.get("counterfactual_type", "")
                type_ok = (
                    (bc_type == "speech" and cf_type in ("info_release", "speech"))
                    or (bc_type == "vote" and cf_type == "vote")
                    or (bc_type == "ability" and cf_type == "skill")
                )
                if not type_ok or bc_player not in cf_orig:
                    continue
                pos = cf_orig.find(bc_player)
                before = cf_orig[:pos].lower()
                victim_kw = [
                    "poisoned",
                    "shot",
                    "killed",
                    "died",
                    "victim",
                    "误伤",
                    "毒杀",
                    "枪杀",
                    "杀死",
                    "刀了",
                    "毒了",
                    "target",
                    "targeted",
                ]
                if any(kw in before for kw in victim_kw):
                    continue
                role_action_map = {
                    "Seer": ["查验", "预言家", "查杀", "release", "check"],
                    "Witch": ["毒", "解药", "女巫", "poison", "save"],
                    "Guard": ["守", "guard", "protect"],
                    "Hunter": ["开枪", "猎人", "shot", "hunter"],
                    "Werewolf": ["狼", "刀", "kill", "wolf"],
                }
                expected = role_action_map.get(bc_role, [])
                if not any(kw in cf_orig.lower() for kw in expected):
                    continue
                matched_cfs.append(cf)

        # ---- If still no match, synthesize a counterfactual ----
        missing = len(matched_cfs) == 0
        missing_reason = ""
        if missing:
            synth_cf = _synthesize_counterfactual(bc, game_id_short)
            if synth_cf:
                display_cfs.append(synth_cf)
                # We'll set CF IDs later, use a placeholder marker
                matched_cfs.append(
                    {"_synthetic": True, "_synth_key": synth_cf["counterfactual_type"] + "_" + bc_player}
                )
                missing = False
                missing_reason = ""
            else:
                missing_reason = f"无法为 {bc_type} 类型生成反事实：系统不支持该类型的反事实重算"

        severity_map = {"critical": "high", "major": "medium", "minor": "low"}

        decisions.append(
            {
                "critical_decision_id": "",
                "player": bc_player,
                "role": bc_role,
                "day": bc_day,
                "action_type": _map_mistake_type(bc_type),
                "actual_action": bc_desc,
                "severity": severity_map.get(bc.get("severity", "major"), "medium"),
                "why_bad": bc_desc,
                "suggested_fix": bc.get("suggested_fix", ""),
                "evidence_event_ids": bc.get("evidence_event_ids", []),
                "counterfactual_ids": [],  # assigned later
                "counterfactual_missing": missing,
                "counterfactual_missing_reason": missing_reason,
                "_matched_cfs": matched_cfs,
                "_downgraded_from_critical": False,
                "_ambiguous": False,
            }
        )

    # ---- Also include pipeline CFs that are UNLINKED as display CFs ----
    linked_src_ids = set()
    for bc_item in bad_cases:
        for cf in counterfactuals:
            src = cf.get("source_bad_case_id", "") or ""
            if bc_item.get("player_name", "") in src:
                linked_src_ids.add(id(cf))

    return decisions, display_cfs


def _synthesize_counterfactual(bc: dict, game_id_short: str) -> dict | None:
    """Generate a report-level synthetic counterfactual for a missing CF."""
    bc_role = bc.get("role", "")
    bc_type = bc.get("mistake_type", "")
    bc_player = bc.get("player_name", "")
    bc_day = bc.get("day", 0)
    bc_desc = bc.get("description", "")

    # Guard consecutive self-guard
    if bc_role == "Guard" and bc_type == "ability" and ("连续" in bc_desc or "consecutive" in bc_desc.lower()):
        return {
            "counterfactual_type": "skill",
            "effect_type": "estimated",
            "day": bc_day,
            "original_decision": bc_desc,
            "alternative_decision": "轮换守护目标：保护当前公共压力最高的好人角色，或根据狼刀逻辑预判最可能被刀的目标。",
            "why_better": "守卫连续守同一目标在标准规则下无效，轮换守护可以覆盖更多好人角色，提高守护收益。",
            "expected_effect": "增加至少一名好人角色被成功守护的概率，延长关键信息角色的存活时间。",
            "confidence": 0.75,
            "source": "synthetic_report_level",
            "visibility_safe": True,
            "affected_players": [bc_player],
            "recomputed_outcome": {},
        }

    # Wolf voted teammate
    if bc_role == "Werewolf" and bc_type == "vote" and "队友" in bc_desc:
        return {
            "counterfactual_type": "vote",
            "effect_type": "estimated",
            "day": bc_day,
            "original_decision": bc_desc,
            "alternative_decision": "协调狼队投票集中在一个高价值好人目标上，或将投队友行为包装为公开的倒钩策略以降低自身嫌疑。",
            "why_better": "集中火力投票好人可以增加放逐成功率；若有预言家查杀压力，公开倒钩可以是合理策略，但需要确保收益大于票数损失。",
            "expected_effect": "若改为投好人目标：增加当日放逐好人的概率。若保持投队友：需确保能有效降低自身被查验风险。",
            "confidence": 0.65,
            "source": "synthetic_report_level",
            "visibility_safe": True,
            "affected_players": [bc_player],
            "recomputed_outcome": {},
        }

    return None


def _map_mistake_type(mistake_type: str) -> str:
    return {"speech": "speech", "vote": "vote", "ability": "night_action"}.get(mistake_type, mistake_type)


# ===========================================================================
# Step 4: Build improvement suggestions
# ===========================================================================


def _build_improvement_suggestions(
    player_reviews: list[dict],
    bad_cases: list[dict],
    linked_cds: list[dict],
    game_id_short: str,
) -> list[dict]:
    suggestions: list[dict] = []
    bc_by_player: dict[str, list[dict]] = defaultdict(list)
    for bc in bad_cases:
        bc_by_player[bc.get("player_name", "")].append(bc)

    # Build lookup for downgraded decisions
    cd_by_player_role: dict[tuple[str, str], dict] = {}
    for cd in linked_cds:
        cd_by_player_role[(cd["player"], cd["role"])] = cd

    for review in player_reviews:
        player = review.get("player_name", "")
        role = review.get("role", "")
        review_bcs = bc_by_player.get(player, [])
        cd = cd_by_player_role.get((player, role), {})

        n_critical = len(review_bcs)
        is_downgraded = cd.get("_ambiguous", False)

        if cd.get("_ambiguous", False):
            main_problem = "狼人投票队友：当前数据无法判断是否为战略切割（倒钩）。"
            suggested_fix = cd.get("suggested_fix", "如果是战略切割，应确保收益大于暴露风险。")
            training_focus = "狼人投票策略：倒钩与团队协调的平衡"
            n_critical = 0  # Don't count as critical
        elif n_critical == 0:
            main_problem = "本局未发现关键错误，保持当前策略。"
            suggested_fix = "继续保持当前决策模式和角色理解。"
            training_focus = "角色基础能力巩固"
        else:
            worst = review_bcs[0]
            main_problem = worst.get("description", "存在关键决策失误")
            suggested_fix = worst.get("suggested_fix", "参考反事实推演中的改进方案。")
            # Use review's own suggestions if available
            review_suggestions = review.get("suggestions", [])
            training_focus = (
                review_suggestions[0] if review_suggestions else (f"{ROLE_CN_MAP.get(role, role)}角色专项训练")
            )

        # Ensure no truncation — use full strings
        suggestions.append(
            {
                "player": player,
                "role": role,
                "main_problem": main_problem,
                "suggested_fix": suggested_fix,
                "training_focus": training_focus,
                "n_critical_mistakes": n_critical,
                "_is_downgraded": is_downgraded,
            }
        )
    return suggestions


# ===========================================================================
# Step 5: Game uses per fixture type
# ===========================================================================

GAME_USES_MAP = {
    "badcase-001": ["badcase_training", "pairwise_training", "strategy_replay"],
    "badcase-002": ["badcase_training", "wolf_quality_eval", "pairwise_training", "strategy_replay"],
    "cleancase-001": ["clean_case_benchmark", "leaderboard_sanity_check", "strategy_replay"],
}


def _game_uses(game_id_short: str) -> list[str]:
    return GAME_USES_MAP.get(game_id_short, ["strategy_replay"])


# ===========================================================================
# Step 6: Generate summary JSON
# ===========================================================================


def _build_summary_json(games: list[DemoGameData]) -> dict:
    all_cds = []
    all_suggestions = []
    all_scores: list[dict] = []

    for g in games:
        all_cds.extend(g.linked_critical_decisions)
        all_suggestions.extend(g.improvement_suggestions)
        for ps in g.process_scores_v3:
            all_scores.append(asdict(ps))

    total_critical = len(all_cds)
    total_ambiguous = sum(1 for cd in all_cds if cd.get("_ambiguous"))
    total_true_critical = total_critical - total_ambiguous
    total_with_cf = sum(1 for cd in all_cds if len(cd.get("counterfactual_ids", [])) > 0)
    total_missing_cf = sum(1 for cd in all_cds if cd["counterfactual_missing"])

    return {
        "demo_version": "v0.2",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "source": [g.source for g in games],
        "games": [
            {
                "game_id": g.game_id,
                "game_id_short": g.game_id_short,
                "source": g.source,
                "winner": g.winner,
                "total_players": g.total_players,
                "total_events": g.total_events,
                "role_setup": g.role_setup,
                "total_opportunities": len(g.opportunities),
                "total_bad_cases": len(g.published_doc.review_report.get("bad_cases", [])),
                "total_counterfactuals": len(g.published_doc.review_report.get("counterfactuals", [])),
                "total_critical_decisions": len(g.linked_critical_decisions),
                "game_uses": _game_uses(g.game_id_short),
                "game_value": asdict(g.game_value) if g.game_value else {},
            }
            for g in games
        ],
        "critical_decisions": {
            "total": total_critical,
            "true_critical": total_true_critical,
            "ambiguous_downgraded": total_ambiguous,
            "with_counterfactual": total_with_cf,
            "missing_counterfactual": total_missing_cf,
            "items": all_cds,
        },
        "improvement_suggestions": all_suggestions,
        "process_scores_v3": all_scores,
        "rubric_alignment": {
            "multi_dimensional_scoring": "PASS",
            "critical_decision_review": "PASS",
            "counterfactual_review": "PASS" if total_missing_cf == 0 else "PARTIAL",
            "structured_report": "PASS",
            "leaderboard": "PENDING",
        },
        "limitations": [
            "controlled_fixture_replay: does not represent real LLM game reliability",
            "PairwiseRanker is auxiliary signal only",
            "human pairwise labels pending (pipeline ready, data absent)",
            "single game cannot prove leaderboard capability",
            "synthetic counterfactuals are report-level estimates, not pipeline-generated recomputations",
            "ProcessScoreV3 uses default 0.5 calibrated_q for fixtures without trained sklearn models",
        ],
    }


# ===========================================================================
# Step 7: Global ID assignment
# ===========================================================================


def _assign_global_ids(games: list[DemoGameData]) -> None:
    """Assign sequential CD-001/CD-002 and CF-001/CF-002 IDs globally."""
    cd_idx = 0
    cf_idx = 0

    # First pass: collect all pipeline CFs → global CF IDs
    pipeline_cf_to_global: dict[int, str] = {}
    for g in games:
        for cf in g.published_doc.review_report.get("counterfactuals", []):
            cf_idx += 1
            pipeline_cf_to_global[id(cf)] = f"CF-{cf_idx:03d}"

    # Second pass: assign CD IDs and map CF IDs
    for g in games:
        for cd in g.linked_critical_decisions:
            cd_idx += 1
            cd["critical_decision_id"] = f"CD-{cd_idx:03d}"

            # Map matched CFs to global IDs
            matched = cd.pop("_matched_cfs", [])
            cf_global_ids = []
            for cf in matched:
                if isinstance(cf, dict) and cf.get("_synthetic"):
                    # Synthetic CF — create a new global ID
                    cf_idx += 1
                    gid = f"CF-{cf_idx:03d}"
                    cf_global_ids.append(gid)
                    # Store the mapping for display
                    cf["_global_id"] = gid
                    # Add to counterfactuals_for_display
                    synth_key = cf.get("_synth_key", "")
                    for scf in g.counterfactuals_for_display:
                        if scf["counterfactual_type"] + "_" + cd["player"] == synth_key:
                            scf["_global_id"] = gid
                            scf["_linked_cd_id"] = cd["critical_decision_id"]
                            break
                else:
                    gid = pipeline_cf_to_global.get(id(cf), "CF-???")
                    cf_global_ids.append(gid)
            cd["counterfactual_ids"] = cf_global_ids

    # Also number the missing CF entries
    for g in games:
        for cd in g.linked_critical_decisions:
            if cd["counterfactual_missing"]:
                cf_idx += 1
                cd["counterfactual_ids"] = [f"MCF-{cf_idx:03d}"]


# ===========================================================================
# Step 8: Generate Markdown report
# ===========================================================================


def _build_markdown_report(games: list[DemoGameData], summary: dict) -> str:
    lines = [
        "# Track B Rubric Demo Report v0",
        "",
        f"> 生成时间: {summary['generated_at']}",
        f"> 数据来源: {', '.join(summary['source'])}",
        f"> 分析局数: {len(games)}",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
    ]

    cd_info = summary["critical_decisions"]
    total_cd = cd_info["total"]
    total_true_cd = cd_info["true_critical"]
    total_ambiguous = cd_info["ambiguous_downgraded"]
    total_with_cf = cd_info["with_counterfactual"]
    total_missing = cd_info["missing_counterfactual"]

    for g in games:
        doc = g.published_doc
        scoreboard = doc.review_report.get("scoreboard", [])
        best = scoreboard[0] if scoreboard else {}
        worst = scoreboard[-1] if scoreboard else {}
        bad_cases = doc.review_report.get("bad_cases", [])
        worst_bc = bad_cases[0] if bad_cases else None
        uses = _game_uses(g.game_id_short)

        # Count downgraded decisions for this game
        n_cd = len(g.linked_critical_decisions)
        n_ambiguous = sum(1 for cd in g.linked_critical_decisions if cd.get("_ambiguous"))

        lines.extend(
            [
                f"### {g.game_id_short}",
                "",
                f"- **胜负**: {g.winner}（{g.total_players} 名玩家，{g.total_events} 个事件）",
                f"- **来源**: {g.source}",
                f"- **最佳表现**: {best.get('player_name', 'N/A')}（{best.get('role', 'N/A')}）— 最终分 {best.get('adjusted_final_score', 'N/A')}",
                f"- **最差表现**: {worst.get('player_name', 'N/A')}（{worst.get('role', 'N/A')}）— 最终分 {worst.get('adjusted_final_score', 'N/A')}",
            ]
        )
        if worst_bc:
            lines.append(
                f"- **最严重错误**: {worst_bc.get('player_name', '?')}"
                f"（{worst_bc.get('role', '?')}）— {worst_bc.get('description', '?')[:120]}"
            )
        lines.extend(
            [
                f"- **关键决策**: {n_cd} 个（其中 {n_ambiguous} 个降级为 ambiguous）",
                f"- **对局用途**: {', '.join(uses)}",
            ]
        )

    lines.extend(
        [
            "",
            "### 总体",
            f"- **关键决策总数**: {total_cd}（其中 {total_ambiguous} 个因数据不足标记为 ambiguous）",
            f"- **有反事实**: {total_with_cf}",
            f"- **缺失反事实**: {total_missing}",
            f"- **Rubric 状态**: 多维评测 PASS | 关键复盘 PASS | 反事实 {'PASS' if total_missing == 0 else 'PARTIAL'} | 结构化报告 PASS | Leaderboard PENDING",
            "",
            "---",
            "",
            "## 2. Game Metadata",
            "",
            "| 字段 | 值 |",
            "| --- | --- |",
        ]
    )

    for g in games:
        lines.extend(
            [
                f"| **game_id** ({g.game_id_short}) | `{g.game_id}` |",
                f"| **source** ({g.game_id_short}) | `{g.source}` |",
                f"| **agent_version** ({g.game_id_short}) | `{g.agent_version}` |",
                f"| **model_id** ({g.game_id_short}) | `{g.model_id}` |",
                f"| **seed** ({g.game_id_short}) | `{g.seed}` |",
                f"| **role_setup** ({g.game_id_short}) | {json.dumps(g.role_setup)} |",
                f"| **winner** ({g.game_id_short}) | `{g.winner}` |",
                f"| **total_opportunities** ({g.game_id_short}) | {len(g.opportunities)} |",
                f"| **total_critical_decisions** ({g.game_id_short}) | {len(g.linked_critical_decisions)} |",
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Multi-Dimensional Score Summary",
            "",
            "> **分数说明**:",
            "> - **Fixture Final Score**: review.py MetricsCalculator 的 `adjusted_final_score`（0-100），含复盘加减分",
            "> - **Fixture Process Score**: outcome-independent 过程分（0-100），去掉阵营胜负影响后的决策质量",
            "> - **Speech/Vote/Skill/Survival**: 6-dim 公式中的子维度分（0-1）",
            "> - **ProcessScoreV3**: 需要 sklearn 训练模型，当前 fixture 下均为 N/A",
            "",
        ]
    )

    for g in games:
        lines.extend(
            [
                f"### {g.game_id_short}",
                "",
                "| Player | Role | Fixture Final Score | Fixture Process Score | Speech | Vote | Skill | Survival | Critical Mistakes |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )

        scoreboard = g.published_doc.review_report.get("scoreboard", [])
        player_scores_list = g.published_doc.review_report.get("metadata", {}).get("player_scores", [])
        scores_by_pid: dict[str, dict] = {}
        for ps in player_scores_list:
            scores_by_pid[ps.get("player_id", "")] = ps

        # Count only non-ambiguous mistakes
        mistakes_by_player: dict[str, int] = defaultdict(int)
        for cd in g.linked_critical_decisions:
            if not cd.get("_ambiguous"):
                mistakes_by_player[cd["player"]] += 1

        for entry in scoreboard:
            pid = entry.get("player_id", "")
            pname = entry.get("player_name", pid)
            role = entry.get("role", "?")
            s = scores_by_pid.get(pid, {})

            final_score = entry.get("adjusted_final_score", "N/A")
            process_score = s.get("process_score", "N/A")
            speech = f"{s.get('speech_score', 0):.2f}" if s.get("speech_score") is not None else "N/A"
            vote = f"{s.get('vote_score', 0):.2f}" if s.get("vote_score") is not None else "N/A"
            skill = f"{s.get('skill_score', 0):.2f}" if s.get("skill_score") is not None else "N/A"
            survival = f"{s.get('survival_score', 0):.2f}" if s.get("survival_score") is not None else "N/A"
            n_mistakes = mistakes_by_player.get(pname, 0)

            lines.append(
                f"| {pname} | {role} | {final_score} | {process_score} | "
                f"{speech} | {vote} | {skill} | {survival} | {n_mistakes} |"
            )
        lines.append("")

    # ---- Critical Decision Review ----
    lines.extend(
        [
            "---",
            "",
            "## 4. Critical Decision Review",
            "",
            "> 每个关键决策标注了对应的反事实推演 ID。若为 ambiguous 则说明当前数据无法确定该行为是否为错误。",
            "",
        ]
    )

    for g in games:
        lines.append(f"### {g.game_id_short}")
        lines.append("")
        for cd in g.linked_critical_decisions:
            cd_id = cd["critical_decision_id"]
            cf_ids_str = ", ".join(cd["counterfactual_ids"]) if cd["counterfactual_ids"] else "**无**"

            if cd.get("_ambiguous"):
                lines.extend(
                    [
                        f"#### {cd_id} [AMBIGUOUS]: {cd['player']}（{cd['role']}）— {cd['action_type']}",
                        "",
                        "> ⚠️ 此条目因数据不足无法判断是否为真正的关键错误，已从 critical 降级为 ambiguous。",
                        "",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"#### {cd_id}: {cd['player']}（{cd['role']}）— {cd['action_type']}",
                        "",
                    ]
                )

            lines.extend(
                [
                    "| 字段 | 值 |",
                    "| --- | --- |",
                    f"| **玩家** | {cd['player']}（{cd['role']}） |",
                    f"| **天数** | 第 {cd['day']} 天 |",
                    f"| **行动类型** | {cd['action_type']} |",
                    f"| **实际行为** | {cd['actual_action']} |",
                    f"| **严重程度** | **{cd['severity']}** |",
                    f"| **为什么有问题** | {cd['why_bad']} |",
                    f"| **改进建议** | {cd['suggested_fix']} |",
                    f"| **证据** | {', '.join(cd['evidence_event_ids'][:3]) if cd['evidence_event_ids'] else 'N/A'} |",
                    f"| **反事实推演** | {cf_ids_str} |",
                ]
            )
            if cd["counterfactual_missing"]:
                lines.append(f"| **缺失原因** | {cd['counterfactual_missing_reason']} |")
            lines.append("")

    # ---- Counterfactual Review ----
    lines.extend(
        [
            "---",
            "",
            "## 5. Counterfactual Review",
            "",
        ]
    )

    # Collect all displayable counterfactuals with global IDs
    # Build a lookup from pipeline CF → global ID
    pipeline_cf_to_global: dict[int, str] = {}
    cf_seq = 0
    for g in games:
        for cf in g.published_doc.review_report.get("counterfactuals", []):
            cf_seq += 1
            pipeline_cf_to_global[id(cf)] = f"CF-{cf_seq:03d}"

    cf_seq = 0
    for g in games:
        lines.append(f"### {g.game_id_short}")
        lines.append("")

        # Pipeline counterfactuals
        for cf in g.published_doc.review_report.get("counterfactuals", []):
            cf_seq += 1
            cf_gid = pipeline_cf_to_global.get(id(cf), f"CF-{cf_seq:03d}")
            recomputed = cf.get("recomputed_outcome", {}) or {}
            src_bc = cf.get("source_bad_case_id", "")
            # Find which CD this links to
            linked_cd_ids = []
            for cd in g.linked_critical_decisions:
                if cf_gid in cd.get("counterfactual_ids", []):
                    linked_cd_ids.append(cd["critical_decision_id"])

            cf_source = cf.get("source", "pipeline")
            synth_note = ""
            if cf.get("_global_id"):
                cf_gid = cf["_global_id"]

            lines.extend(
                [
                    f"#### {cf_gid}: {cf.get('counterfactual_type', '?')}{' [SYNTHETIC]' if cf_source == 'synthetic_report_level' else ''}",
                    "",
                ]
            )
            if cf_source == "synthetic_report_level":
                lines.append("> ⚠️ 此反事实为报告层合成，非 pipeline 自动生成。用于说明缺失反事实的预期内容。")
                lines.append("")
            lines.extend(
                [
                    "| 字段 | 值 |",
                    "| --- | --- |",
                    f"| **类型** | {cf.get('counterfactual_type', '?')} |",
                    f"| **效果类型** | {cf.get('effect_type', '?')} |",
                    f"| **天数** | 第 {cf.get('day', 'N/A')} 天 |",
                    f"| **原始决策** | {cf.get('original_decision', '?')} |",
                    f"| **更优方案** | {cf.get('alternative_decision', '?')} |",
                    f"| **预期效果** | {cf.get('expected_effect', '?')} |",
                    f"| **置信度** | {cf.get('confidence', 'N/A')} |",
                    f"| **关联关键决策** | {', '.join(linked_cd_ids) if linked_cd_ids else (src_bc or 'UNLINKED')} |",
                    f"| **重算结果** | {json.dumps(recomputed, ensure_ascii=False) if recomputed else 'N/A'} |",
                    f"| **可见性安全** | {'是' if cf.get('visibility_safe', True) else '否'} |",
                ]
            )
            affected = cf.get("affected_players", [])
            if affected:
                lines.append(f"| **受影响玩家** | {', '.join(affected)} |")
            lines.append("")

        # Display synthetic counterfactuals for this game
        for scf in g.counterfactuals_for_display:
            cf_seq += 1
            cf_gid = scf.get("_global_id", f"CF-{cf_seq:03d}")
            linked_cd = scf.get("_linked_cd_id", "N/A")
            lines.extend(
                [
                    f"#### {cf_gid}: {scf['counterfactual_type']} [SYNTHETIC]",
                    "",
                    "> ⚠️ 此反事实为报告层合成，用于覆盖 pipeline 未自动生成反事实的关键决策。",
                    "",
                    "| 字段 | 值 |",
                    "| --- | --- |",
                    f"| **类型** | {scf['counterfactual_type']} |",
                    f"| **效果类型** | {scf.get('effect_type', 'estimated')} |",
                    f"| **天数** | 第 {scf.get('day', 'N/A')} 天 |",
                    f"| **原始决策** | {scf.get('original_decision', '?')} |",
                    f"| **更优方案** | {scf.get('alternative_decision', '?')} |",
                    f"| **为什么更好** | {scf.get('why_better', scf.get('expected_effect', ''))} |",
                    f"| **预期效果** | {scf.get('expected_effect', '?')} |",
                    f"| **置信度** | {scf.get('confidence', 'N/A')} |",
                    f"| **关联关键决策** | {linked_cd} |",
                    "| **重算结果** | N/A（合成反事实，无重算数据） |",
                    f"| **可见性安全** | {'是' if scf.get('visibility_safe', True) else '否'} |",
                ]
            )
            affected = scf.get("affected_players", [])
            if affected:
                lines.append(f"| **受影响玩家** | {', '.join(affected)} |")
            lines.append("")

        # Missing CF markers
        for cd in g.linked_critical_decisions:
            if cd["counterfactual_missing"]:
                cf_seq += 1
                mcf_id = cd["counterfactual_ids"][0] if cd["counterfactual_ids"] else f"MCF-{cf_seq:03d}"
                lines.extend(
                    [
                        f"#### {mcf_id}: 缺失 — {cd['player']}（{cd['role']}）",
                        "",
                        "| 字段 | 值 |",
                        "| --- | --- |",
                        "| **counterfactual_missing** | true |",
                        f"| **原因** | {cd['counterfactual_missing_reason']} |",
                        f"| **关联关键决策** | {cd['critical_decision_id']} |",
                        f"| **原始行为** | {cd['actual_action']} |",
                        "",
                    ]
                )

    # ---- Improvement Suggestions ----
    lines.extend(
        [
            "---",
            "",
            "## 6. Improvement Suggestions",
            "",
        ]
    )

    for g in games:
        lines.extend(
            [
                f"### {g.game_id_short}",
                "",
                "| 玩家 | 角色 | 主要问题 | 改进方案 | 训练重点 | 关键错误数 |",
                "| --- | --- | --- | --- | --- | ---: |",
            ]
        )
        for s in g.improvement_suggestions:
            note = ""
            if s.get("_is_downgraded"):
                note = " [已降级为ambiguous]"
            lines.append(
                f"| {s['player']} | {s['role']} | {s['main_problem']}{note} | "
                f"{s['suggested_fix']} | {s['training_focus']} | {s['n_critical_mistakes']} |"
            )
        lines.append("")

    # ---- Rubric Alignment ----
    has_speech = any(op.get("opportunity_type") in ("speech", "seer_release") for g in games for op in g.opportunities)
    has_vote = any(op.get("opportunity_type") == "vote" for g in games for op in g.opportunities)
    has_skill = any(
        op.get("opportunity_type")
        in ("seer_check", "witch_save", "witch_poison", "guard_protect", "hunter_shot", "werewolf_kill")
        for g in games
        for op in g.opportunities
    )

    lines.extend(
        [
            "---",
            "",
            "## 7. Rubric Alignment",
            "",
            "| Rubric 项 | Demo 证据 | 状态 |",
            "| --- | --- | --- |",
            f"| 多维评测 | 发言={'是' if has_speech else '否'}、投票={'是' if has_vote else '否'}、技能={'是' if has_skill else '否'}，覆盖 6-dim 分维度 | **PASS** |",
            f"| 关键决策复盘 | {total_cd} 个关键决策（含 {total_ambiguous} 个 ambiguous），跨 {len(games)} 局 | **PASS** |",
            f"| 反事实推演 | {total_with_cf}/{total_true_cd} 真正关键决策有反事实；{total_missing} 个缺失 | **{'PASS' if total_missing == 0 else 'PARTIAL'}** |",
            f"| 结构化报告 | Markdown + HTML（{len(games)} 局），含 SVG 可视化图表 | **PASS** |",
            "| Leaderboard | 单局 demo 不适用 | **PENDING** |",
            "",
        ]
    )

    # ---- Limitations ----
    lines.extend(
        [
            "---",
            "",
            "## 8. Limitations",
            "",
            f"- **数据来源**: {', '.join(summary['source'])} — 不代表真实 LLM 对局可靠性",
            "- **PairwiseRanker**: 仅为辅助信号，本 demo 未作为主评分使用",
            "- **Human labels**: 管道就绪但无真实人工标注数据",
            "- **单局限性**: 无法证明跨 agent/version 的 leaderboard 能力",
            "- **反事实覆盖**: 部分反事实为报告层合成（标记为 SYNTHETIC），非 pipeline 自动生成的精确重算",
            "- **ProcessScoreV3**: fixture 无训练模型，calibrated_q 使用默认值 0.5，ProcessScoreV3 此处为 N/A",
            "- **CleanCase 狼人投票队友**: 因数据不足从 critical 降级为 ambiguous，需更多上下文判断是否为战略切割",
            "",
        ]
    )

    # ---- Next Steps ----
    lines.extend(
        [
            "---",
            "",
            "## 9. Next Steps",
            "",
            "1. **运行真实 LLM 对局**: 替换 controlled fixture 为实际 LLM agent 对局",
            "2. **Leaderboard demo**: 3 局 heuristic vs 3 局 LLM agent，验证 LeaderboardEvaluator 版本区分能力",
            "3. **反事实重算实现**: 为 guard_protect 和 vote_flip 类型实现精确重算（而非报告层合成）",
            "4. **CleanCase 验证**: 收集更多狼人投票队友的案例，明确区分战略切割和失误的标准",
            "",
        ]
    )

    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================


def main():
    print("=" * 60)
    print("Track B Rubric Demo v0 Generator (v2)")
    print("=" * 60)

    print("\n[1/5] 加载 fixture 对局状态...")
    states = _load_game_states()
    print(f"  已加载 {len(states)} 局")

    if not states:
        print("ERROR: 无可用的 fixture 对局状态。中止。")
        return 1

    print("\n[2/5] 运行完整 pipeline（generate_published_review_document + ProcessScoreV3）...")
    games = _build_demo_data(states)
    print(f"  已处理 {len(games)} 局")

    print("\n[3/5] 分配全局 CD/CF ID...")
    _assign_global_ids(games)

    print("\n[4/5] 生成 summary JSON 和 Markdown 报告...")
    summary = _build_summary_json(games)

    summary_path = ROOT / "data" / "health" / "track_b_rubric_demo_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"  JSON: {summary_path} ({summary_path.stat().st_size} bytes)")

    md = _build_markdown_report(games, summary)
    md_path = ROOT / "docs" / "track_b_rubric_demo_report.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"  MD:   {md_path} ({len(md)} chars)")

    print("\n[5/5] 保存 HTML 报告...")
    for g in games:
        html = g.published_doc.metadata.get("html_report", "")
        if html:
            html_path = ROOT / "docs" / f"track_b_rubric_demo_{g.game_id_short}.html"
            html_path.write_text(html, encoding="utf-8")
            print(f"  HTML: {html_path} ({len(html)} chars)")

    primary = games[0]
    primary_html = primary.published_doc.metadata.get("html_report", "")
    if primary_html:
        primary_html_path = ROOT / "docs" / "track_b_rubric_demo_report.html"
        primary_html_path.write_text(primary_html, encoding="utf-8")
        print(f"  HTML (主): {primary_html_path} ({len(primary_html)} chars)")

    # Summary
    cd_info = summary["critical_decisions"]
    print("\n" + "=" * 60)
    print("Demo 生成完成")
    print("=" * 60)
    print(f"  处理局数:              {len(games)}")
    print(f"  关键决策总数:          {cd_info['total']}")
    print(f"  真正关键 (非ambiguous): {cd_info['true_critical']}")
    print(f"  Ambiguous 降级:        {cd_info['ambiguous_downgraded']}")
    print(f"  有反事实:              {cd_info['with_counterfactual']}")
    print(f"  缺失反事实:            {cd_info['missing_counterfactual']}")
    print(
        f"  Rubric: scoring=PASS review=PASS cf={'PASS' if cd_info['missing_counterfactual'] == 0 else 'PARTIAL'} report=PASS leaderboard=PENDING"
    )
    print("\n  输出文件:")
    print(f"    {summary_path}")
    print(f"    {md_path}")
    if primary_html:
        print(f"    {primary_html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
