"""Three-Tier Per-Step Decision Scoring — cascade architecture.

Tier 1 (DETERMINISTIC): Hard-rule scoring for all decisions. Free, instant, 100% reliable.
Tier 2 (LIGHT LLM):    Single-judge LLM for ambiguous decisions (correctness ∈ [0.3,0.7]).
Tier 3 (HEAVY LLM):    3-judge panel for high-impact + high-disagreement decisions.

~85% decisions resolve at Tier 1, ~12% at Tier 2, ~3% at Tier 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass
class DecisionScore:
    decision_id: str
    player_id: str
    player_name: str
    role: str
    day: int
    phase: str
    action_type: str
    correctness: float
    reasoning_quality: float
    timeliness: float
    impact: float
    overall_score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    alternative: str = ""
    # Three-tier cascade
    needs_light_llm: bool = False
    needs_heavy_llm: bool = False
    light_llm_score: float | None = None
    heavy_llm_score: float | None = None
    scoring_tier: str = "deterministic"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredStep:
    """A single scored decision step — bridges PerStepScorer → KnowledgeAbstractor."""

    step_id: str = ""
    step_type: str = ""  # "speech" | "vote" | "night_action"
    day: int = 0
    phase: str = ""
    role: str = ""
    step_score: float = 0.0  # 0-1 overall score from PerStepScorer
    scoring_tier: str = "deterministic"
    action_summary: str = ""  # What the agent did
    is_highlight: bool = False  # score >= 0.75
    is_mistake: bool = False  # score <= 0.30
    mistake_type: str = ""  # "fabrication" | "empty_speech" | "wrong_vote" | "missed_skill" | "bad_target"
    strategy_applied: bool = False
    strategy_impact: float = 0.0
    retrieved_strategies: list[dict] = field(default_factory=list)
    lesson_abstract: str = ""  # Extracted lesson text
    lesson_tags: list[str] = field(default_factory=list)
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class PlayerReviewReport:
    """Per-player review report — bridges PerStepScorer → KnowledgeAbstractor."""

    game_id: str = ""
    player_id: str = ""
    role: str = ""
    persona_style: str = ""
    persona_mbti: str = ""
    scored_steps: list[ScoredStep] = field(default_factory=list)


class PerStepScorer:
    """Three-tier decision scorer with cascade architecture.

    Usage:
        scorer = PerStepScorer(llm_client=client)  # client optional
        scores = scorer.score_all(decisions, state_dict, speech_acts)
        # scores now have scoring_tier ∈ {"deterministic","light_llm","heavy_llm"}
    """

    def __init__(self, llm_client: Any = None):
        self._llm = llm_client

    # ---- Tier 1: Deterministic Scoring ----

    def score_vote(self, decision: dict, state: dict) -> DecisionScore:
        tid = decision.get("target_id", "")
        t_align = _align(state, tid)
        t_role = _role(state, tid)
        day = decision.get("day", 0)
        correct = 0.95 if t_align == "wolf" else (0.15 if t_role in _KEY_VILLAGE else 0.35)
        overall = round(
            0.50 * correct
            + 0.25 * _reasoning(decision.get("raw_text", ""))
            + 0.10 * min(0.9, 0.5 + day * 0.08)
            + 0.15 * _vote_weight(decision) * 0.6,
            3,
        )
        return DecisionScore(
            decision_id=decision.get("id", ""),
            player_id=decision.get("player_id", ""),
            player_name=decision.get("player_name", ""),
            role=decision.get("player_role", ""),
            day=day,
            phase=decision.get("phase", "DAY_VOTE"),
            action_type="vote",
            correctness=correct,
            reasoning_quality=_reasoning(decision.get("raw_text", "")),
            timeliness=min(0.9, 0.5 + day * 0.08),
            impact=_vote_weight(decision) * 0.6,
            overall_score=overall,
            needs_light_llm=(0.20 < correct < 0.80),
            evidence=[f"Target={t_role}({t_align})"] + (["Good vote!"] if t_align == "wolf" else []),
            alternative=_alt_vote(state, tid),
            scoring_tier="deterministic",
        )

    def score_talk(self, decision: dict, speech_acts: list[dict], state: dict) -> DecisionScore:
        pid = decision.get("player_id", "")
        day = decision.get("day", 0)
        act = next((a for a in speech_acts if a.get("player_id") == pid and a.get("day") == day), None)
        if act is None:
            return DecisionScore(
                decision_id=decision.get("id", ""),
                player_id=pid,
                player_name=decision.get("player_name", ""),
                role=decision.get("player_role", ""),
                day=day,
                phase=decision.get("phase", "DAY_SPEECH"),
                action_type="talk",
                correctness=0.45,
                reasoning_quality=_reasoning(decision.get("raw_text", "")),
                timeliness=0.7,
                impact=0.3,
                overall_score=0.45,
                needs_light_llm=True,  # No speech act data → definitely needs LLM
                evidence=["Speech not analyzed."],
                scoring_tier="deterministic",
            )
        stance = act.get("stance", "neutral")
        risks = len(act.get("risk_flags", [])) * 0.15
        grounded = min(0.2, len(act.get("grounded_event_ids", [])) * 0.1)
        stance_s = {"accuse": 0.8, "defend": 0.8, "claim": 0.7}.get(stance, 0.3)
        correct = max(0.1, min(0.95, stance_s - risks + grounded))
        impact = 0.3 + min(0.3, len(act.get("suspected_players", [])) * 0.05)
        overall = round(
            0.40 * correct + 0.35 * _reasoning(decision.get("raw_text", "")) + 0.10 * 0.7 + 0.15 * impact, 3
        )
        return DecisionScore(
            decision_id=decision.get("id", ""),
            player_id=pid,
            player_name=decision.get("player_name", ""),
            role=decision.get("player_role", ""),
            day=day,
            phase=decision.get("phase", "DAY_SPEECH"),
            action_type="talk",
            correctness=correct,
            reasoning_quality=_reasoning(decision.get("raw_text", "")),
            timeliness=0.7,
            impact=impact,
            overall_score=overall,
            needs_light_llm=(0.25 < correct < 0.75),
            evidence=_talk_evidence(act),
            scoring_tier="deterministic",
        )

    def score_night(self, decision: dict, state: dict) -> DecisionScore:
        at = decision.get("action_type", "")
        tid = decision.get("target_id", "")
        t_role = _role(state, tid)
        t_align = _align(state, tid)
        correct, ev = _night_correct(at, t_role, t_align)
        day = decision.get("day", 0)
        impact = _night_impact(t_role, t_align)
        overall = round(
            0.55 * correct + 0.20 * _reasoning(decision.get("raw_text", "")) + 0.10 * 0.8 + 0.15 * impact, 3
        )
        return DecisionScore(
            decision_id=decision.get("id", ""),
            player_id=decision.get("player_id", ""),
            player_name=decision.get("player_name", ""),
            role=decision.get("player_role", ""),
            day=day,
            phase=decision.get("phase", ""),
            action_type=at,
            correctness=correct,
            reasoning_quality=_reasoning(decision.get("raw_text", "")),
            timeliness=0.8,
            impact=impact,
            overall_score=overall,
            needs_light_llm=(0.25 < correct < 0.75),
            evidence=ev,
            scoring_tier="deterministic",
        )

    # ---- Tier 2: Light LLM Scoring ----

    def score_with_light_llm(self, score: DecisionScore, decision: dict, context: dict) -> DecisionScore:
        """Upgrade an ambiguous score with a single lightweight LLM call."""
        if self._llm is None:
            return score
        try:
            from backend.eval.llm_judge import LLMJudgePanel

            panel = LLMJudgePanel(self._llm)
            result = panel.score_step(decision, context)
            if result:
                score.light_llm_score = result.overall / 10.0  # normalize [0,10] → [0,1]
                score.scoring_tier = "light_llm"
                score.evidence.append(
                    f"LLM: reasonability={result.reasonability:.1f} depth={result.reasoning_depth:.1f}"
                )
        except Exception:
            pass
        return score

    # ---- Tier 3: Heavy LLM Scoring (high-impact only) ----

    def score_with_heavy_llm(self, score: DecisionScore, decision: dict, game_state: dict) -> DecisionScore:
        """Upgrade a high-impact ambiguous score with 3-judge panel.

        Uses per-step evaluation with the full 3-judge + Critic panel
        for decisions that are both ambiguous and high-impact.
        """
        if self._llm is None or not score.needs_heavy_llm:
            return score
        try:
            from backend.eval.llm_judge import LLMJudgePanel

            panel = LLMJudgePanel(self._llm)
            # Use per-step rubric with 3-judge panel (not game-level score_game)
            result = panel.score_step_with_panel(decision, game_state)
            if result:
                score.heavy_llm_score = result.overall / 10.0  # normalize [0,10] → [0,1]
                score.scoring_tier = "heavy_llm"
                score.metadata["judge_agreement"] = getattr(result, "judge_agreement", None)
        except Exception:
            pass
        return score

    # ---- Full Cascade Orchestration ----

    def score_all(
        self,
        decisions: list[dict],
        state: dict,
        speech_acts: list[dict],
        *,
        light_llm: bool = False,
        heavy_llm: bool = False,
    ) -> list[DecisionScore]:
        """Score all decisions with cascade.

        Args:
            decisions: List of decision dicts.
            state: Game state dict with players.
            speech_acts: Speech act analysis results.
            light_llm: If True, run Tier 2 for ambiguous decisions.
            heavy_llm: If True, run Tier 3 for high-impact + ambiguous.

        Returns:
            List of DecisionScore with scoring_tier set.
        """
        scores = []
        for d in decisions:
            phase = str(d.get("phase", ""))
            if "VOTE" in phase or "BADGE_ELECTION" in phase:
                s = self.score_vote(d, state)
            elif "SPEECH" in phase or "TALK" in phase or "LAST_WORDS" in phase:
                s = self.score_talk(d, speech_acts, state)
            elif "NIGHT" in phase or "HUNTER" in phase:
                s = self.score_night(d, state)
            else:
                continue
            scores.append(s)

        # Tier 2: Light LLM for ambiguous decisions
        if light_llm and self._llm:
            for s in scores:
                if s.needs_light_llm:
                    d = next((x for x in decisions if x.get("id") == s.decision_id), {})
                    self.score_with_light_llm(s, d, {"visible_info": _visible_context(state, s)})

        # Tier 3: Heavy LLM for high-impact + low-confidence + ambiguous
        if heavy_llm and self._llm:
            for s in scores:
                if s.needs_light_llm and s.impact > 0.5:
                    s.needs_heavy_llm = True
                    d = next((x for x in decisions if x.get("id") == s.decision_id), {})
                    self.score_with_heavy_llm(s, d, state)

        # Propagate LLM scores to overall_score so downstream consumers
        # (KnowledgeAbstractor, track_b) use the higher-quality estimate.
        for s in scores:
            if s.scoring_tier == "heavy_llm" and s.heavy_llm_score is not None:
                s.overall_score = s.heavy_llm_score
            elif s.scoring_tier == "light_llm" and s.light_llm_score is not None:
                s.overall_score = s.light_llm_score

        return scores

    def tally_tiers(self, scores: list[DecisionScore]) -> dict[str, int]:
        """Count decisions per scoring tier."""
        from collections import Counter

        return dict(Counter(s.scoring_tier for s in scores))


# ---- Helpers ----

_KEY_VILLAGE = {"Seer", "Witch", "Hunter", "Guard"}
_WOLF_ROLES = {"Werewolf", "WhiteWolfKing"}


def _role(s, pid):
    for p in s.get("players", []):
        if p.get("id") == pid:
            return p.get("role", "?")
    return "?"


def _align(s, pid):
    for p in s.get("players", []):
        if p.get("id") == pid:
            return p.get("alignment", "?")
    return "?"


def _reasoning(text: str) -> float:
    if not text:
        return 0.3
    s = 0.5
    if len(text) > 80:
        s += 0.15
    if len(text) > 200:
        s += 0.10
    import re

    if re.search(r"\d+号", text):
        s += 0.10
    if any(w in text for w in ["因为", "所以", "如果", "但是", "因此"]):
        s += 0.10
    return min(0.95, s)


def _vote_weight(d):
    return float(d.get("vote_weight", 1.0))


def _alt_vote(s, tid):
    if _align(s, tid) == "wolf":
        return ""
    for p in s.get("players", []):
        if p.get("alignment") == "wolf" and p.get("alive", True):
            return f"Better: {p.get('name', '?')}({p.get('role', '?')})"
    return ""


def _talk_evidence(act):
    ev = []
    if act.get("suspected_players"):
        ev.append(f"Accused {len(act['suspected_players'])}")
    if act.get("grounded_event_ids"):
        ev.append(f"Grounded in {len(act['grounded_event_ids'])} events")
    if act.get("risk_flags"):
        ev.append(f"Risks: {','.join(act['risk_flags'])}")
    return ev or ["Neutral speech"]


def _night_correct(at, trole, talign):
    if at == "attack":
        if trole in _KEY_VILLAGE:
            return 0.90, [f"Killed key role {trole}"]
        return (0.60, ["Attacked villager"]) if talign == "village" else (0.10, [f"Attacked wolf {trole}"])
    if at == "divine":
        return (0.95, [f"Found wolf {trole}"]) if talign == "wolf" else (0.50, ["Checked known good"])
    if at in ("guard", "guard_protect"):
        return (0.85, [f"Protected {trole}"]) if trole in _KEY_VILLAGE else (0.50, ["Guarded non-key"])
    if at == "witch_save":
        return (
            (0.95, [f"Saved {trole}"])
            if trole in _KEY_VILLAGE
            else (0.10, ["Saved wolf"])
            if talign == "wolf"
            else (0.75, ["Saved villager"])
        )
    if at == "witch_poison":
        return (
            (0.95, [f"Poisoned wolf {trole}"])
            if talign == "wolf"
            else (0.05, [f"Poisoned key {trole}"])
            if trole in _KEY_VILLAGE
            else (0.20, ["Poisoned villager"])
        )
    return 0.50, ["Unknown"]


def _night_impact(trole, talign):
    return 0.85 if trole in _KEY_VILLAGE else (0.70 if talign == "wolf" else 0.40)


def _visible_context(state, score):
    # NOTE: score.role is the TRUE role (ground truth).  This is intentional —
    # the per-step scorer runs post-game with full knowledge of all roles.
    # For mid-game evaluation, the caller should not pass true roles here.
    return f"Day {score.day}, Phase {score.phase}, Role {score.role}"
