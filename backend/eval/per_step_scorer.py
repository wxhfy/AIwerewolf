"""Per-Step Decision Scoring — scores every individual agent decision independently.

Unlike MetricsCalculator (one score per game), this scores each talk/vote/night
action with its own correctness, reasoning quality, timeliness, and impact.

Enables:
  1. Decision quality trajectory — when did the player make good/bad calls?
  2. Per-phase analysis — are night votes better than day speeches?
  3. Individual audit — "this specific vote was wrong because X was a confirmed wolf"

All scoring is DETERMINISTIC — no LLM calls, pure game-state comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionScore:
    decision_id: str; player_id: str; player_name: str
    role: str; day: int; phase: str; action_type: str
    correctness: float; reasoning_quality: float
    timeliness: float; impact: float; overall_score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    alternative: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class PerStepScorer:

    # ---- Vote (exact) ----

    def score_vote(self, decision: dict, state: dict) -> DecisionScore:
        tid = decision.get("target_id", "")
        t_align = _align(state, tid)
        t_role = _role(state, tid)
        day = decision.get("day", 0)
        correct = 0.95 if t_align == "wolf" else (0.15 if t_role in _KEY_VILLAGE else 0.35)
        return DecisionScore(
            decision_id=decision.get("id",""), player_id=decision.get("player_id",""),
            player_name=decision.get("player_name",""), role=decision.get("player_role",""),
            day=day, phase=decision.get("phase","DAY_VOTE"), action_type="vote",
            correctness=correct,
            reasoning_quality=_reasoning(decision.get("raw_text","")),
            timeliness=min(0.9, 0.5+day*0.08), impact=_vote_weight(decision)*0.6,
            overall_score=round(0.50*correct + 0.25*_reasoning(decision.get("raw_text","")) + 0.10*min(0.9,0.5+day*0.08) + 0.15*_vote_weight(decision)*0.6, 3),
            evidence=[f"Target={t_role}({t_align})"] + (["Good vote!"] if t_align=="wolf" else []),
            alternative=_alt_vote(state, tid),
        )

    # ---- Speech (heuristic) ----

    def score_talk(self, decision: dict, speech_acts: list[dict], state: dict) -> DecisionScore:
        # Match by player + day + phase (decisions don't store the CHAT_MESSAGE event_id)
        pid = decision.get("player_id","")
        day = decision.get("day",0)
        act = next((a for a in speech_acts
                    if a.get("player_id")==pid and a.get("day")==day), None)
        if act is None:
            return DecisionScore(
                decision_id=decision.get("id",""), player_id=decision.get("player_id",""),
                player_name=decision.get("player_name",""), role=decision.get("player_role",""),
                day=decision.get("day",0), phase=decision.get("phase","DAY_SPEECH"), action_type="talk",
                correctness=0.45, reasoning_quality=_reasoning(decision.get("raw_text","")),
                timeliness=0.7, impact=0.3, overall_score=0.45,
                evidence=["Speech not analyzed."],
            )
        stance = act.get("stance","neutral")
        risks = len(act.get("risk_flags",[]))*0.15
        grounded = min(0.2, len(act.get("grounded_event_ids",[]))*0.1)
        stance_s = {"accuse":0.8,"defend":0.8,"claim":0.7}.get(stance,0.3)
        correct = max(0.1, min(0.95, stance_s-risks+grounded))
        return DecisionScore(
            decision_id=decision.get("id",""), player_id=decision.get("player_id",""),
            player_name=decision.get("player_name",""), role=decision.get("player_role",""),
            day=decision.get("day",0), phase=decision.get("phase","DAY_SPEECH"), action_type="talk",
            correctness=correct, reasoning_quality=_reasoning(decision.get("raw_text","")),
            timeliness=0.7, impact=0.3+min(0.3,len(act.get("suspected_players",[]))*0.05),
            overall_score=round(0.40*correct + 0.35*_reasoning(decision.get("raw_text","")) + 0.10*0.7 + 0.15*(0.3+min(0.3,len(act.get("suspected_players",[]))*0.05)), 3),
            evidence=_talk_evidence(act),
        )

    # ---- Night (exact) ----

    def score_night(self, decision: dict, state: dict) -> DecisionScore:
        at = decision.get("action_type","")
        tid = decision.get("target_id","")
        t_role = _role(state, tid); t_align = _align(state, tid)
        correct, ev = _night_correct(at, t_role, t_align)
        day = decision.get("day",0)
        return DecisionScore(
            decision_id=decision.get("id",""), player_id=decision.get("player_id",""),
            player_name=decision.get("player_name",""), role=decision.get("player_role",""),
            day=day, phase=decision.get("phase",""), action_type=at,
            correctness=correct, reasoning_quality=_reasoning(decision.get("raw_text","")),
            timeliness=0.8, impact=_night_impact(t_role, t_align),
            overall_score=round(0.55*correct + 0.20*_reasoning(decision.get("raw_text","")) + 0.10*0.8 + 0.15*_night_impact(t_role,t_align), 3),
            evidence=ev,
        )


# ---- Helpers ----

_KEY_VILLAGE = {"Seer","Witch","Hunter","Guard"}
_WOLF_ROLES = {"Werewolf","WhiteWolfKing"}

def _role(s, pid):
    for p in s.get("players",[]):
        if p.get("id")==pid: return p.get("role","?")
    return "?"

def _align(s, pid):
    for p in s.get("players",[]):
        if p.get("id")==pid: return p.get("alignment","?")
    return "?"

def _reasoning(text: str) -> float:
    if not text: return 0.3
    s = 0.5
    if len(text)>80: s+=0.15
    if len(text)>200: s+=0.10
    import re
    if re.search(r'\d+号',text): s+=0.10
    if any(w in text for w in ["因为","所以","如果","但是","因此"]): s+=0.10
    return min(0.95, s)

def _vote_weight(d): return float(d.get("vote_weight",1.0))

def _alt_vote(s, tid):
    if _align(s,tid)=="wolf": return ""
    for p in s.get("players",[]):
        if p.get("alignment")=="wolf" and p.get("alive",True):
            return f"Better: {p.get('name','?')}({p.get('role','?')})"
    return ""

def _talk_evidence(act):
    ev=[]
    if act.get("suspected_players"): ev.append(f"Accused {len(act['suspected_players'])}")
    if act.get("grounded_event_ids"): ev.append(f"Grounded in {len(act['grounded_event_ids'])} events")
    if act.get("risk_flags"): ev.append(f"Risks: {','.join(act['risk_flags'])}")
    return ev or ["Neutral speech"]

def _night_correct(at, trole, talign):
    if at=="attack":
        if trole in _KEY_VILLAGE: return 0.90, [f"Killed key role {trole}"]
        return (0.60,["Attacked villager"]) if talign=="village" else (0.10,[f"Attacked wolf {trole}"])
    if at=="divine":
        return (0.95,[f"Found wolf {trole}"]) if talign=="wolf" else (0.50,["Checked known good"])
    if at in ("guard","guard_protect"):
        return (0.85,[f"Protected {trole}"]) if trole in _KEY_VILLAGE else (0.50,["Guarded non-key"])
    if at=="witch_save":
        return (0.95,[f"Saved {trole}"]) if trole in _KEY_VILLAGE else (0.10,["Saved wolf"]) if talign=="wolf" else (0.75,["Saved villager"])
    if at=="witch_poison":
        return (0.95,[f"Poisoned wolf {trole}"]) if talign=="wolf" else (0.05,[f"Poisoned key {trole}"]) if trole in _KEY_VILLAGE else (0.20,["Poisoned villager"])
    return 0.50,["Unknown"]

def _night_impact(trole, talign): return 0.85 if trole in _KEY_VILLAGE else (0.70 if talign=="wolf" else 0.40)
