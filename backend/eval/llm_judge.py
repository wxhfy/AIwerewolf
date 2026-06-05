"""LLM Judge Panel — RULERS-style locked-rubric + evidence-anchored scoring.

Three judges (Strategist, Logician, Psychologist) independently score each player,
then Critic round challenges extreme scores, followed by trimmed-mean aggregation.

Design references:
  - RULERS: locked rubrics + evidence-anchored + checklist scoring
  - Auto-Arena: committee judging with debate rounds
  - CourtEval: Grader + Critic adversarial validation
  - Ensemble k=8: multiple samples + variance reduction
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from typing import Any

from backend.eval.judge_rubric import (
    STRATEGIST_RUBRIC, LOGICIAN_RUBRIC, PSYCHOLOGIST_RUBRIC,
    PER_STEP_RUBRIC, RUBRIC_VERSION, RUBRIC_HASH,
)

logger = logging.getLogger(__name__)


@dataclass
class JudgeVerdict:
    """One judge's score for one rubric item."""
    item_id: str
    score: float         # 0-10
    reasoning: str       # justification
    evidence: list[str]  # event IDs cited


@dataclass
class JudgeReport:
    """Complete report from one judge for one player."""
    judge_type: str       # "strategist" | "logician" | "psychologist"
    player_name: str
    role: str
    verdicts: list[JudgeVerdict]
    overall_score: float  # average across items


@dataclass
class GameLevelScore:
    """Reliable game-level score for one player."""
    player_name: str; role: str; alignment: str
    strategy_score: float; logic_score: float; social_score: float
    composite: float                        # trimmed mean
    judge_agreement: float                   # std across judges (lower = more agreement)
    individual_reports: list[JudgeReport]
    rubric_version: str = RUBRIC_VERSION
    rubric_hash: str = RUBRIC_HASH


@dataclass
class PerStepScore:
    """LLM-judged score for a single decision."""
    decision_id: str; player_name: str; action_type: str
    day: int; phase: str
    reasonability: float     # 0-10: was it reasonable given known info?
    reasoning_depth: float   # 0-10: was the reasoning sound?
    overall: float
    evidence: list[str]
    judge_agreement: float = 0.0  # std across judges for panel scoring
    rubric_version: str = RUBRIC_VERSION


class LLMJudgePanel:
    """3-judge panel with locked rubrics and Critic round.

    Usage:
        panel = LLMJudgePanel(llm_client)
        scores = panel.score_game(game_state_dict, player_decisions)
    """

    def __init__(self, llm_client: Any):
        self._llm = llm_client
        self._judges = {
            "strategist": STRATEGIST_RUBRIC,
            "logician": LOGICIAN_RUBRIC,
            "psychologist": PSYCHOLOGIST_RUBRIC,
        }

    # ---- Game-Level Scoring ----

    def score_game(self, game_state: dict, player_decisions: dict[str, list[dict]]) -> list[GameLevelScore]:
        """Score all players in a finished game.

        Args:
            game_state: Dict with players, winner, events summary.
            player_decisions: {player_name: [decision_dicts]}.

        Returns:
            List of GameLevelScore, one per player.
        """
        scores = []
        for pdata in game_state.get("players", []):
            name = pdata["name"]
            role = pdata["role"]
            alignment = pdata.get("alignment", "village")
            decs = player_decisions.get(name, [])

            reports = []
            for judge_type, rubric in self._judges.items():
                try:
                    report = self._judge_player(judge_type, rubric, name, role, alignment, decs, game_state)
                    reports.append(report)
                except Exception as e:
                    logger.warning(f"Judge {judge_type} failed for {name}: {e}")

            if not reports:
                continue

            # Critic round: review judge disagreement, produce adjusted composite
            critic_result = self._critic_review(reports, {"player_name": name, "role": role})
            composite = critic_result["final_score"]
            if critic_result.get("adjusted"):
                logger.info(
                    f"Critic adjusted {name}({role}) composite={composite:.2f} "
                    f"(disagreement={critic_result.get('disagreement', 0):.2f})"
                )

            scores_list = [r.overall_score for r in reports]
            judge_agreement = statistics.stdev(scores_list) if len(scores_list) >= 2 else 0.0

            strategy_score = next((r.overall_score for r in reports if r.judge_type == "strategist"), 5.0)
            logic_score = next((r.overall_score for r in reports if r.judge_type == "logician"), 5.0)
            social_score = next((r.overall_score for r in reports if r.judge_type == "psychologist"), 5.0)

            scores.append(GameLevelScore(
                player_name=name, role=role, alignment=alignment,
                strategy_score=strategy_score, logic_score=logic_score,
                social_score=social_score, composite=composite,
                judge_agreement=judge_agreement, individual_reports=reports,
            ))

        return scores

    def _judge_player(
        self, judge_type: str, rubric: list, name: str, role: str,
        alignment: str, decisions: list[dict], game_state: dict,
    ) -> JudgeReport:
        """One judge scores one player using the locked rubric."""
        # Build the judging prompt
        events_summary = _summarize_events(game_state, name, max_events=15)
        decisions_summary = _summarize_decisions(decisions, max_decisions=12)

        prompt = _build_judge_prompt(
            judge_type=judge_type, rubric=rubric,
            player_name=name, role=role, alignment=alignment,
            events=events_summary, decisions=decisions_summary,
            game_state=game_state,
        )

        system = (
            f"你是狼人杀{_judge_label(judge_type)}。"
            f"请根据以下量规对玩家 {name}({role}) 进行评分。"
            f"每个评分必须引用具体的游戏事件作为证据。"
            f"输出严格的JSON格式。"
        )

        raw = self._call_llm(system, prompt, max_tokens=1500)
        parsed = self._parse_judge_output(raw, rubric)

        return JudgeReport(
            judge_type=judge_type, player_name=name, role=role,
            verdicts=parsed,
            overall_score=statistics.mean([v.score for v in parsed]) if parsed else 5.0,
        )

    # ---- Critic Round (adversarial validation) ----

    def _critic_review(self, judge_results: list[JudgeReport], game_data: dict) -> dict:
        """Critic reviews judge disagreement and recommends score adjustment."""
        if len(judge_results) < 3:
            scores = [r.overall_score for r in judge_results]
            return {"adjusted": False, "final_score": sum(scores) / max(len(scores), 1)}

        # Build judge info: (judge_type, overall_score, reasoning_summary)
        judge_info = []
        for r in judge_results:
            reasoning_snippets = " | ".join(v.reasoning[:80] for v in r.verdicts[:2])
            judge_info.append((r.judge_type, r.overall_score, reasoning_snippets))

        # Sort by score for trimmed mean
        judge_info.sort(key=lambda x: x[1])
        scores = [x[1] for x in judge_info]

        # Trimmed mean: drop highest and lowest
        trimmed_mean = scores[1] if len(scores) == 3 else sum(scores[1:-1]) / (len(scores) - 2)

        disagreement = max(scores) - min(scores)
        if disagreement <= 0.3:
            return {"adjusted": False, "final_score": trimmed_mean, "disagreement": round(disagreement, 3)}

        # Build Critic prompt
        player_name = game_data.get("player_name", "unknown")
        role = game_data.get("role", "unknown")

        judge_lines = []
        for jtype, score, snippet in judge_info:
            judge_lines.append(f"- {_judge_label(jtype)}: {score:.2f} — {snippet}")

        system_prompt = (
            "你是狼人杀评分Critic（批评家），负责审查三位裁判的评分是否存在分歧过大，"
            "并根据推理质量给出调整后的分数。只输出JSON，不要额外解释。"
        )

        critic_prompt = f"""三位裁判对玩家 {player_name}({role})的评分存在较大分歧:

{chr(10).join(judge_lines)}

最大分歧: {disagreement:.2f}。请审查各裁判的推理，给出你认可的调整分数。

返回JSON格式: {{"adjusted_score": <0-10>, "reasoning": "<简述为何这样调整>"}}"""

        try:
            response = self._call_llm(system_prompt, critic_prompt, max_tokens=500)
            critic_data = self._parse_step_output(response)
            if critic_data:
                critic_score = float(critic_data.get("adjusted_score", trimmed_mean))
                # Weight critic at 25%, trimmed mean at 75%
                final = trimmed_mean * 0.75 + critic_score * 0.25
                return {
                    "adjusted": True, "final_score": round(final, 3),
                    "disagreement": round(disagreement, 3),
                    "critic_score": critic_score,
                    "critic_reasoning": critic_data.get("reasoning", ""),
                }
            else:
                return {"adjusted": False, "final_score": trimmed_mean, "disagreement": round(disagreement, 3)}
        except Exception as e:
            logger.warning(f"Critic review failed: {e}")
            return {"adjusted": False, "final_score": trimmed_mean, "disagreement": round(disagreement, 3)}

    # ---- Per-Step Scoring (lightweight, single judge) ----

    def score_step(
        self, decision: dict, game_context: dict,
    ) -> PerStepScore | None:
        """Score a single decision using the per-step rubric.

        Only called for ambiguous decisions (correctness ∈ [0.3, 0.7]).
        """
        prompt = _build_per_step_prompt(decision, game_context, PER_STEP_RUBRIC)
        system = (
            "你是狼人杀决策评估者。请根据量规对这个单独的决策进行评分。"
            "注意：只基于该玩家当时能看到的信息，而非全局信息。"
            "输出JSON格式。"
        )

        raw = self._call_llm(system, prompt, max_tokens=500)
        parsed = self._parse_step_output(raw)

        if parsed:
            return PerStepScore(
                decision_id=decision.get("id", ""),
                player_name=decision.get("player_name", ""),
                action_type=decision.get("action_type", "?"),
                day=decision.get("day", 0),
                phase=decision.get("phase", ""),
                reasonability=parsed.get("T1_score", 5.0),
                reasoning_depth=parsed.get("T2_score", 5.0),
                overall=(parsed.get("T1_score", 5.0) + parsed.get("T2_score", 5.0)) / 2,
                evidence=parsed.get("evidence", []),
            )
        return None

    def score_step_with_panel(
        self, decision: dict, game_context: dict,
    ) -> PerStepScore | None:
        """Score a single decision using the full 3-judge panel with per-step rubric.

        Uses all 3 judges independently scoring the same decision, then
        trimmed-mean aggregation. Higher confidence than single-judge score_step.
        """
        scores = []
        for judge_type, _ in self._judges.items():
            prompt = _build_per_step_prompt(decision, game_context, PER_STEP_RUBRIC)
            system = (
                f"你是狼人杀{_judge_label(judge_type)}。"
                f"请根据量规对这个单独的决策进行评分。"
                f"注意：只基于该玩家当时能看到的信息，而非全局信息。"
                f"输出严格的JSON格式。"
            )
            raw = self._call_llm(system, prompt, max_tokens=500)
            parsed = self._parse_step_output(raw)
            if parsed:
                scores.append((parsed.get("T1_score", 5.0) + parsed.get("T2_score", 5.0)) / 2)
            else:
                scores.append(5.0)

        if not scores:
            return None

        # Trimmed mean: drop min and max when 3 scores
        if len(scores) >= 3:
            scores_sorted = sorted(scores)
            trimmed_mean = scores_sorted[1]
        else:
            trimmed_mean = sum(scores) / len(scores)

        judge_agreement = statistics.stdev(scores) if len(scores) >= 2 else 0.0

        return PerStepScore(
            decision_id=decision.get("id", ""),
            player_name=decision.get("player_name", ""),
            action_type=decision.get("action_type", "?"),
            day=decision.get("day", 0),
            phase=decision.get("phase", ""),
            reasonability=trimmed_mean,
            reasoning_depth=trimmed_mean,
            overall=trimmed_mean,
            evidence=[],
            judge_agreement=judge_agreement,
        )

    def _call_llm(self, system: str, user: str, max_tokens: int = 800) -> str:
        """Call the LLM client."""
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            resp = self._llm.chat_sync(messages, max_tokens=max_tokens)
            if isinstance(resp, dict):
                choices = resp.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
            return str(resp)
        except Exception as e:
            logger.error(f"LLM judge call failed: {e}")
            return "{}"

    def _parse_judge_output(self, raw: str, rubric: list) -> list[JudgeVerdict]:
        """Parse LLM output into structured verdicts."""
        try:
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group())
            verdicts = []
            for item in rubric:
                key = f"{item.id}_score"
                reason_key = f"{item.id}_reasoning"
                ev_key = f"{item.id}_evidence"
                if key in data:
                    verdicts.append(JudgeVerdict(
                        item_id=item.id,
                        score=float(data.get(key, 5)),
                        reasoning=str(data.get(reason_key, "")),
                        evidence=data.get(ev_key, []) if isinstance(data.get(ev_key), list) else [],
                    ))
            return verdicts
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse judge output: {e}")
            return []

    def _parse_step_output(self, raw: str) -> dict | None:
        """Parse per-step LLM output."""
        try:
            import re
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if not m:
                return None
            return json.loads(m.group())
        except json.JSONDecodeError:
            return None


# ============================================================
# Prompt builders
# ============================================================

def _judge_label(judge_type: str) -> str:
    return {"strategist": "策略分析师", "logician": "逻辑检查官", "psychologist": "社交心理学家"}.get(judge_type, judge_type)


def _build_judge_prompt(
    judge_type: str, rubric: list, player_name: str, role: str,
    alignment: str, events: str, decisions: str, game_state: dict,
) -> str:
    """Build the judging prompt with locked rubric items."""
    winner = game_state.get("winner", "unknown")
    total_players = len(game_state.get("players", []))

    lines = [
        f"# 游戏概况",
        f"胜方: {winner} | 总玩家: {total_players}人",
        f"",
        f"# 被评估玩家",
        f"姓名: {player_name} | 角色: {role} | 阵营: {alignment}",
        f"",
        f"# 游戏事件（与该玩家相关）",
        events,
        f"",
        f"# 决策记录",
        decisions,
        f"",
        f"# 评分量规（{_judge_label(judge_type)}视角）",
        f"请对以下每个维度单独评分（0-10整数），并引用具体事件ID作为证据：",
        f"",
    ]

    for item in rubric:
        lines.append(f"## {item.id}: {item.question}")
        lines.append("评分标准：")
        for score, desc in sorted(item.anchors.items()):
            lines.append(f"  {score}分: {desc}")
        lines.append(f"证据要求: 引用具体的游戏事件/发言/投票作为判断依据")
        lines.append("")

    lines.append("# 输出格式（严格JSON，不要额外解释）")
    lines.append("{")
    for item in rubric:
        lines.append(f'  "{item.id}_score": <0-10的整数>,')
        lines.append(f'  "{item.id}_reasoning": "<1-2句评分理由，引用具体事实>",')
        lines.append(f'  "{item.id}_evidence": ["<event_id_1>", "<event_id_2>"],')
    lines.append("}")

    return "\n".join(lines)


def _build_per_step_prompt(decision: dict, context: dict, rubric: list) -> str:
    """Build a lightweight per-step scoring prompt."""
    lines = [
        f"# 决策信息",
        f"玩家: {decision.get('player_name', '?')} ({decision.get('player_role', '?')})",
        f"时间: Day {decision.get('day', 0)} / {decision.get('phase', '?')}",
        f"行动类型: {decision.get('action_type', '?')}",
        f"目标: {decision.get('target_id', 'none')}",
        f"推理: {decision.get('raw_text', '')[:300]}",
        f"",
        f"# 当时可见信息",
        context.get("visible_info", "无"),
        f"",
        f"# 评分",
    ]
    for item in rubric:
        lines.append(f"{item.id}: {item.question}")
        lines.append("评分: " + ", ".join(f"{s}={d}" for s, d in sorted(item.anchors.items())))
        lines.append("")

    lines.append('输出JSON: {"T1_score": <0-10>, "T2_score": <0-10>, "T1_reasoning": "...", "T2_reasoning": "...", "evidence": ["..."]}')
    return "\n".join(lines)


def _summarize_events(game_state: dict, player_name: str, max_events: int = 15) -> str:
    """Summarize game events relevant to a specific player."""
    events = game_state.get("events", [])
    relevant = []
    for e in events:
        payload = e.get("payload", {}) or {}
        text = str(payload.get("speech", "") or payload.get("message", ""))
        if player_name in text or payload.get("actor_name") == player_name:
            relevant.append(e)
        elif payload.get("target_name") == player_name:
            relevant.append(e)
    if len(relevant) > max_events:
        relevant = relevant[-max_events:]

    lines = []
    for e in relevant:
        payload = e.get("payload", {}) or {}
        day = e.get("day", "?")
        etype = e.get("type", "?")
        actor = payload.get("actor_name", "")
        target = payload.get("target_name", "")
        speech = str(payload.get("speech", "") or "")[:100]
        if speech:
            lines.append(f"  D{day} [{etype}] {actor}: {speech}")
        elif target:
            lines.append(f"  D{day} [{etype}] {actor} → {target}")
    return "\n".join(lines) if lines else "(无相关事件)"


def _summarize_decisions(decisions: list[dict], max_decisions: int = 12) -> str:
    """Summarize a player's decisions."""
    if not decisions:
        return "(无决策记录)"

    decs = decisions[-max_decisions:]
    lines = []
    for d in decs:
        day = d.get("day", "?")
        phase = d.get("phase", "?")
        at = d.get("action_type", "?")
        target = d.get("target", "") or d.get("target_id", "")
        reasoning = str(d.get("reasoning", "") or "")[:80]
        lines.append(f"  D{day} [{phase}] {at} → {target} | {reasoning}")
    return "\n".join(lines)
