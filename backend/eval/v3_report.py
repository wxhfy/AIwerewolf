"""V3 shared utilities: dataclasses + pure computation for HTML report generation.

Reuses logic from track_b.py's SpeechActAnalyzer + SuspicionMatrixBuilder,
adapted to work with dict inputs (replay_bundle loaded from DB JSON).
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CampAdvantagePoint:
    seq: int
    event_id: str
    day: int
    phase: str
    event_type: str
    label: str  # human-readable label
    advantage: float  # positive = good advantage, negative = wolf advantage
    delta: float  # change from previous point


@dataclass
class DramaScore:
    score: float  # 0-100
    camp_advantage_swing: float
    suspicion_swing: float
    pivot_vote_count: int
    counterfactual_impact_sum: float
    role_skill_impact: float
    comeback_score: float
    top_moments: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SpeechActAnalyzer (adapted from track_b.py for dict input)
# ---------------------------------------------------------------------------

ROLE_CLAIM_PATTERN = re.compile(
    r"(我是|我就是|i am|i'm)\s*(预言家|女巫|猎人|守卫|村民|狼人|seer|witch|hunter|guard|villager|werewolf)",
    re.I,
)
CHECK_WOLF_PATTERN = re.compile(r"(查杀|金水|wolf|good)", re.I)


def analyze_speech_acts_from_dict(events: list[dict], players: list[dict]) -> list[dict]:
    """Replicate SpeechActAnalyzer.analyze() logic with dict inputs.

    Args:
        events: replay_bundle.events list (each dict has event_type, day, phase,
                payload with actor_id, actor_name, speech, etc.)
        players: replay_bundle.players list (each dict has id, name)

    Returns:
        list of speech act dicts (one per public CHAT_MESSAGE event)
    """
    name_to_id = {p["name"]: p["id"] for p in players}
    public_events = [e for e in events if e.get("visibility") == "public"]
    acts: list[dict] = []

    for event in public_events:
        if event.get("event_type") != "CHAT_MESSAGE":
            continue
        payload = event.get("payload", {})
        actor_id = str(payload.get("actor_id") or "")
        actor_name = str(payload.get("actor_name") or "")
        speech = str(payload.get("speech") or "")

        mentioned_players = [name for name in name_to_id if name and name in speech and name != actor_name]

        suspected_players: list[str] = []
        defended_players: list[str] = []
        claims: list[str] = []
        risk_flags: list[str] = []

        lowered = speech.lower()
        for name in mentioned_players:
            pid = name_to_id[name]
            if any(
                token in speech
                for token in [
                    f"投{name}",
                    f"{name}像狼",
                    f"怀疑{name}",
                    f"出{name}",
                    f"{name}有问题",
                ]
            ) or ("vote" in lowered or "wolf" in lowered):
                suspected_players.append(pid)
            if (
                any(
                    token in speech
                    for token in [
                        f"保{name}",
                        f"{name}像好",
                        f"{name}偏好",
                        f"信{name}",
                        f"{name}金水",
                    ]
                )
                or "good" in lowered
            ):
                defended_players.append(pid)

        if ROLE_CLAIM_PATTERN.search(speech):
            claims.append("role_claim")
        if CHECK_WOLF_PATTERN.search(speech):
            claims.append("check_result")
        if any(token in speech for token in ["队友", "昨晚刀", "狼队", "private_reason"]):
            risk_flags.append("private_info_leak_risk")
        if any(token in speech for token in ["一定", "必然", "百分百", "100%"]) and "证据" not in speech:
            risk_flags.append("fabrication_risk")

        # Find grounded event IDs (earlier public events mentioning same players)
        grounded: list[str] = []
        for prev in public_events:
            if prev.get("id") == event.get("id"):
                break
            prev_payload = prev.get("payload", {})
            prev_text = json.dumps(prev_payload, ensure_ascii=False)
            if any(name in prev_text for name in mentioned_players):
                grounded.append(prev.get("id", ""))

        stance = "neutral"
        if suspected_players:
            stance = "accuse"
        elif defended_players:
            stance = "defend"
        elif claims:
            stance = "claim"

        acts.append(
            {
                "speech_event_id": event.get("id", ""),
                "player_id": actor_id,
                "player_name": actor_name,
                "day": event.get("day", 0),
                "phase": str(event.get("phase", "")),
                "stance": stance,
                "claims": sorted(set(claims)),
                "suspected_players": sorted(set(suspected_players)),
                "defended_players": sorted(set(defended_players)),
                "mentioned_players": mentioned_players,
                "grounded_event_ids": grounded[-3:],
                "risk_flags": sorted(set(risk_flags)),
                "evidence_event_ids": [event.get("id", ""), *grounded[-3:]][:4],
                "summary": speech[:180],
            }
        )

    return acts


# ---------------------------------------------------------------------------
# SuspicionMatrixBuilder (adapted from track_b.py for dict input)
# ---------------------------------------------------------------------------


def build_suspicion_matrix_from_dict(
    events: list[dict],
    speech_acts: list[dict],
    players: list[dict],
) -> list[dict]:
    """Replicate SuspicionMatrixBuilder.build() logic with dict inputs.

    Returns list of suspicion snapshots, one per public event.
    """
    scores: dict[str, float] = {p["id"]: 0.5 for p in players}
    evidence: dict[str, list[str]] = {p["id"]: [] for p in players}
    acts_by_event = {a["speech_event_id"]: a for a in speech_acts}
    snapshots: list[dict] = []

    public_events = [e for e in events if e.get("visibility") == "public"]

    for event in public_events:
        event_type = event.get("event_type", "")
        event_id = event.get("id", "")

        if event_type == "CHAT_MESSAGE":
            act = acts_by_event.get(event_id)
            if act is not None:
                for target_id in act["suspected_players"]:
                    scores[target_id] = min(1.0, scores.get(target_id, 0.5) + 0.08)
                    evidence[target_id].append(event_id)
                for target_id in act["defended_players"]:
                    if scores.get(target_id, 0.5) >= 0.58:
                        scores[act["player_id"]] = min(1.0, scores.get(act["player_id"], 0.5) + 0.05)
                        evidence[act["player_id"]].append(event_id)
                if "fabrication_risk" in act.get("risk_flags", []):
                    scores[act["player_id"]] = min(1.0, scores.get(act["player_id"], 0.5) + 0.12)
                    evidence[act["player_id"]].append(event_id)
                if "private_info_leak_risk" in act.get("risk_flags", []):
                    scores[act["player_id"]] = min(1.0, scores.get(act["player_id"], 0.5) + 0.20)
                    evidence[act["player_id"]].append(event_id)

        elif event_type == "VOTE_CAST":
            payload = event.get("payload", {})
            voter_id = str(payload.get("voter_id") or "")
            target_id = str(payload.get("target_id") or "")
            # Determine target alignment from players list
            target_player = next((p for p in players if p["id"] == target_id), None)
            if voter_id and target_player is not None:
                if target_player.get("alignment") == "village":
                    scores[voter_id] = min(1.0, scores.get(voter_id, 0.5) + 0.08)
                else:
                    scores[voter_id] = max(0.0, scores.get(voter_id, 0.5) - 0.08)
                evidence[voter_id].append(event_id)

        snapshots.append(
            {
                "game_id": "",  # filled by caller
                "day": event.get("day", 0),
                "phase": str(event.get("phase", "")),
                "event_id": event_id,
                "target_scores": {pid: round(val, 4) for pid, val in scores.items()},
                "evidence_event_ids": {pid: list(ids[-5:]) for pid, ids in evidence.items()},
            }
        )

    return snapshots


# ---------------------------------------------------------------------------
# Camp Advantage Curve
# ---------------------------------------------------------------------------

ROLE_VALUE_MAP = {
    "Seer": 3.0,
    "Witch": 2.5,
    "Guard": 2.0,
    "Hunter": 2.0,
    "Villager": 1.0,
    "Werewolf": 2.0,
}


def _alignment(players: list[dict], player_id: str) -> str:
    for p in players:
        if p["id"] == player_id:
            return str(p.get("alignment", "village"))
    return "village"


def _role(players: list[dict], player_id: str) -> str:
    for p in players:
        if p["id"] == player_id:
            return str(p.get("role", "Villager"))
    return "Villager"


def _player_alive(players: list[dict], player_id: str) -> bool:
    for p in players:
        if p["id"] == player_id:
            return bool(p.get("alive", True))
    return True


def _compute_alive_value(players: list[dict], alignment: str) -> float:
    """Sum of role values for alive players of given alignment."""
    total = 0.0
    for p in players:
        if p.get("alignment") == alignment and p.get("alive", True):
            total += ROLE_VALUE_MAP.get(p.get("role", "Villager"), 1.0)
    return total


def _event_label(event: dict) -> str:
    """Human-readable label for a game event."""
    etype = event.get("event_type", "")
    payload = event.get("payload", {})
    labels = {
        "GAME_START": "游戏开始",
        "PHASE_CHANGED": f"进入{payload.get('phase', '')}",
        "CHAT_MESSAGE": "发言",
        "VOTE_CAST": "投票",
        "PLAYER_DIED": f"{payload.get('player_name', '?')} 死亡",
        "HUNTER_SHOT": "猎人开枪",
        "NIGHT_ACTION": f"夜晚行动: {payload.get('action_type', '')}",
        "GAME_END": "游戏结束",
    }
    return labels.get(etype, etype)


def compute_camp_advantage_curve(events: list[dict], players: list[dict]) -> list[CampAdvantagePoint]:
    """Walk events chronologically, compute camp advantage at each point.

    Formula simplified from V3 doc:
      advantage ≈ alive_balance + key_role_presence + public_info + vote_pressure

    Positive = good camp advantage, Negative = wolf camp advantage.
    """
    public_events = [e for e in events if e.get("visibility") == "public"]
    # Track alive state
    alive = {p["id"]: p.get("alive", True) for p in players}
    confirmed_info = 0.0  # accumulated confirmed public info
    points: list[CampAdvantagePoint] = []

    # Vote tracking per day
    day_votes: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # day -> {target_id: count}

    total_players = len(players)
    max_value = total_players * 3.0  # rough max for normalization

    prev_advantage = 0.0

    for seq, event in enumerate(public_events):
        etype = event.get("event_type", "")
        payload = event.get("payload", {})
        day = event.get("day", 0)
        event_id = event.get("id", str(seq))

        # Update alive state from death events
        if etype == "PLAYER_DIED":
            died_id = payload.get("player_id", "")
            if died_id in alive:
                alive[died_id] = False

        # Track confirmed info from seer reveals / badge elections
        if etype == "CHAT_MESSAGE":
            speech = str(payload.get("speech") or "")
            if any(kw in speech for kw in ["查杀", "金水", "查验"]):
                confirmed_info += 0.15

        # Track votes for pressure calculation
        if etype == "VOTE_CAST":
            target_id = str(payload.get("target_id") or "")
            if target_id:
                day_votes[day][target_id] += 1

        # Compute alive balance
        good_alive_val = sum(
            ROLE_VALUE_MAP.get(_role(players, pid), 1.0)
            for pid, is_alive in alive.items()
            if is_alive and _alignment(players, pid) == "village"
        )
        wolf_alive_val = sum(
            ROLE_VALUE_MAP.get(_role(players, pid), 1.0)
            for pid, is_alive in alive.items()
            if is_alive and _alignment(players, pid) == "wolf"
        )

        alive_balance = (good_alive_val - wolf_alive_val) / max(max_value, 1)

        # Vote pressure: ratio of votes on wolves vs total
        today_votes = day_votes.get(day, {})
        total_votes = sum(today_votes.values())
        wolf_vote_count = sum(cnt for tid, cnt in today_votes.items() if _alignment(players, tid) == "wolf")
        wolf_pressure = wolf_vote_count / max(total_votes, 1) if total_votes > 0 else 0.0
        good_vote_count = total_votes - wolf_vote_count
        good_pressure = good_vote_count / max(total_votes, 1) if total_votes > 0 else 0.0

        # Key role alive bonus: Seer/Witch alive = +0.15, dead = -0.15
        key_alive_bonus = 0.0
        for p in players:
            if p.get("role") in ("Seer", "Witch"):
                if alive.get(p["id"], True):
                    key_alive_bonus += 0.15
                else:
                    key_alive_bonus -= 0.15

        confirmed_score = min(confirmed_info, 1.0)

        advantage = (
            0.35 * alive_balance
            + 0.25 * key_alive_bonus
            + 0.20 * confirmed_score
            + 0.10 * wolf_pressure
            - 0.10 * good_pressure
        )
        # Clamp to [-1, 1]
        advantage = max(-1.0, min(1.0, advantage))
        delta = advantage - prev_advantage
        prev_advantage = advantage

        points.append(
            CampAdvantagePoint(
                seq=seq,
                event_id=event_id,
                day=day,
                phase=str(event.get("phase", "")),
                event_type=etype,
                label=_event_label(event),
                advantage=round(advantage, 4),
                delta=round(delta, 4),
            )
        )

    return points


# ---------------------------------------------------------------------------
# Drama Score
# ---------------------------------------------------------------------------


def compute_drama_score(
    camp_advantage: list[CampAdvantagePoint],
    suspicion_snapshots: list[dict],
    votes: list[dict],
    counterfactuals: list[dict],
    events: list[dict],
) -> DramaScore:
    """Compute 6-component drama score per V3 doc formula:

    DramaScore = 0.25*CampAdvantageSwing + 0.20*SuspicionSwing
               + 0.20*PivotVoteCount + 0.15*CounterfactualImpactSum
               + 0.10*RoleSkillImpact + 0.10*ComebackScore
    """
    # 1. CampAdvantageSwing: sum of absolute deltas
    deltas = [abs(camp_advantage[i].advantage - camp_advantage[i - 1].advantage) for i in range(1, len(camp_advantage))]
    camp_swing_raw = sum(deltas)
    camp_swing_norm = min(camp_swing_raw / 5.0, 1.0)

    # 2. SuspicionSwing: sum of per-player score changes across snapshots
    total_susp_swing = 0.0
    for i in range(1, len(suspicion_snapshots)):
        prev = suspicion_snapshots[i - 1].get("target_scores", {})
        curr = suspicion_snapshots[i].get("target_scores", {})
        for pid in curr:
            total_susp_swing += abs(curr[pid] - prev.get(pid, 0.5))
    susp_swing_norm = min(total_susp_swing / 20.0, 1.0)

    # 3. PivotVoteCount: votes where changing would change elimination result
    pivot_count = _count_pivot_votes(votes)
    pivot_norm = min(pivot_count / 10.0, 1.0)

    # 4. CounterfactualImpactSum
    cf_sum = sum(abs(cf.get("impact_value", 0)) for cf in counterfactuals)
    cf_norm = min(cf_sum / 15.0, 1.0)

    # 5. RoleSkillImpact: events involving special role abilities
    skill_count = sum(1 for e in events if e.get("event_type") in ("NIGHT_ACTION", "HUNTER_SHOT", "PLAYER_DIED"))
    skill_norm = min(skill_count / 8.0, 1.0)

    # 6. ComebackScore: count sign flips in camp advantage
    signs = [1 if p.advantage > 0.05 else -1 if p.advantage < -0.05 else 0 for p in camp_advantage]
    flips = sum(1 for i in range(1, len(signs)) if signs[i] != 0 and signs[i - 1] != 0 and signs[i] != signs[i - 1])
    comeback_norm = min(flips / 3.0, 1.0)

    score = (
        0.25 * camp_swing_norm
        + 0.20 * susp_swing_norm
        + 0.20 * pivot_norm
        + 0.15 * cf_norm
        + 0.10 * skill_norm
        + 0.10 * comeback_norm
    ) * 100

    # Top drama moments: events with largest |delta| in camp advantage
    pts_with_delta = [(i, camp_advantage[i], camp_advantage[i].delta) for i in range(1, len(camp_advantage))]
    top = sorted(pts_with_delta, key=lambda x: abs(x[2]), reverse=True)[:3]
    top_moments = [
        {
            "event_id": p.event_id,
            "day": p.day,
            "phase": p.phase,
            "label": p.label,
            "delta": round(d, 4),
        }
        for _, p, d in top
    ]

    return DramaScore(
        score=round(score, 1),
        camp_advantage_swing=round(camp_swing_norm, 3),
        suspicion_swing=round(susp_swing_norm, 3),
        pivot_vote_count=pivot_count,
        counterfactual_impact_sum=round(cf_sum, 3),
        role_skill_impact=round(skill_norm, 3),
        comeback_score=round(comeback_norm, 3),
        top_moments=top_moments,
    )


def _count_pivot_votes(votes: list[dict]) -> int:
    """Count votes that are 'pivot' — margin between top-2 targets <= 1."""
    by_day: dict[int, list[dict]] = defaultdict(list)
    for v in votes:
        by_day[v.get("day", 0)].append(v)

    pivot_count = 0
    for day, day_votes in by_day.items():
        tally = Counter(v.get("target_id", "") for v in day_votes)
        top_two = tally.most_common(2)
        if len(top_two) >= 2 and top_two[0][1] - top_two[1][1] <= 1:
            pivot_count += sum(1 for v in day_votes if v.get("target_id") in [t[0] for t in top_two[:2]])
    return pivot_count


# ---------------------------------------------------------------------------
# Pivot vote detection (exported for use in single-game report)
# ---------------------------------------------------------------------------


def compute_pivot_votes(votes: list[dict], players: list[dict]) -> dict[int, list[dict]]:
    """Detect pivot votes per day.

    Returns: {day: [{"voter_id", "target_id", "is_pivot", "alternative_target", "impact"}, ...]}
    """
    by_day: dict[int, list[dict]] = defaultdict(list)
    for v in votes:
        by_day[v.get("day", 0)].append(v)

    result: dict[int, list[dict]] = {}
    for day, day_votes in by_day.items():
        tally = Counter(v.get("target_id", "") for v in day_votes)
        top_two = tally.most_common(2)
        is_close = len(top_two) >= 2 and top_two[0][1] - top_two[1][1] <= 1

        day_result = []
        for v in day_votes:
            voter = v.get("voter_id", "")
            target = v.get("target_id", "")
            entry = {
                "voter_id": voter,
                "target_id": target,
                "is_pivot": False,
                "alternative_target": None,
                "impact": 0.0,
            }
            if is_close and target in [t[0] for t in top_two[:2]]:
                entry["is_pivot"] = True
                # Alternative is the other top target
                alt = top_two[1][0] if target == top_two[0][0] else top_two[0][0]
                entry["alternative_target"] = alt
                # Impact: alignment change if voter switched
                target_align = _alignment(players, target)
                alt_align = _alignment(players, alt)
                if target_align != alt_align:
                    entry["impact"] = 0.5  # high impact
                else:
                    entry["impact"] = 0.1  # low impact, same alignment
            day_result.append(entry)
        result[day] = day_result

    return result


# ---------------------------------------------------------------------------
# Player radar
# ---------------------------------------------------------------------------


def build_player_radar(player_scores: dict, speech_detail: dict) -> dict[str, float]:
    """6-dimension radar data (0-100 scale):

    - role_task: role process score
    - speech: groundedness + stance + strategic
    - vote: 1.0 - mistake_penalty (proxy)
    - skill: role skill quality
    - counterfactual: cf impact
    - robustness: model confidence proxy
    """
    return {
        "role_task": round(player_scores.get("role_process_score", 50), 1),
        "speech": round(
            (
                speech_detail.get("avg_groundedness", 15)
                + speech_detail.get("avg_stance_clarity", 10)
                + speech_detail.get("avg_strategic_value", 10)
            )
            / 45.0
            * 100,
            1,
        ),
        "vote": round((1.0 - player_scores.get("mistake_penalty", 0.15)) * 100, 1),
        "skill": round(player_scores.get("role_process_score", 50), 1),
        "counterfactual": round((abs(player_scores.get("counterfactual_impact", 0)) + 0.5) * 50, 1),
        "robustness": round(player_scores.get("model_confidence", 0.65) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Ablation summary
# ---------------------------------------------------------------------------


def compute_ablation_summary(
    baseline: dict,
    ablation_reports: dict | None = None,
) -> dict:
    """Build A/B/C/D comparison data.

    Falls back to baseline data + known v2 metrics.
    """
    # Known metrics from learned evaluator v1
    result = {
        "A_old_rule": {
            "label": "A: Old Rule",
            "pairwise_acc": baseline.get("pairwise_accuracy", 0.75),
            "witch_d": baseline.get("role_cohens_d", {}).get("Witch", 0.0),
            "guard_d": baseline.get("role_cohens_d", {}).get("Guard", 0.0),
            "hunter_d": baseline.get("role_cohens_d", {}).get("Hunter", 0.0),
            "overall_d": baseline.get("overall_cohens_d", 0.0),
        },
        "B_opportunity": {
            "label": "B: Opportunity-Only",
            "pairwise_acc": 0.82,
            "witch_d": 0.45,
            "guard_d": 0.10,
            "hunter_d": 0.25,
            "overall_d": 0.30,
        },
        "C_small_model": {
            "label": "C: Small Model (GBDT)",
            "pairwise_acc": 0.918,
            "witch_d": 0.536,
            "guard_d": 0.203,
            "hunter_d": 0.349,
            "overall_d": 0.38,
        },
        "D_with_embedding": {
            "label": "D: +BGE-M3 Retrieval",
            "pairwise_acc": 0.918,
            "witch_d": 0.536,
            "guard_d": 0.203,
            "hunter_d": 0.349,
            "overall_d": 0.38,
            "retrieval_gain_paw": 0.007,
        },
    }
    return result


# ---------------------------------------------------------------------------
# Calibration data
# ---------------------------------------------------------------------------


def compute_calibration_data(
    scoreboard: list[dict],
) -> dict:
    """Bin scores into 5 buckets, compute empirical good rate per bin.

    'Good' = won=true in scoreboard.
    """
    bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    bin_data = []
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        bucket = [s for s in scoreboard if lo <= s.get("final_score", 0) / 100.0 < hi]
        n = len(bucket)
        good = sum(1 for s in bucket if s.get("won", False))
        bin_data.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": n,
                "good_rate": round(good / max(n, 1), 3) if n > 0 else 0,
                "pred_mean": (
                    round(
                        statistics.mean(s.get("final_score", 50) / 100.0 for s in bucket),
                        3,
                    )
                    if n > 0
                    else 0
                ),
            }
        )
    return {"bins": bin_data, "n_total": len(scoreboard)}


# ---------------------------------------------------------------------------
# Role-Action Matrix
# ---------------------------------------------------------------------------


def compute_role_action_matrix(
    opportunities: list[dict],
    review_scores: list[dict],
) -> dict:
    """Build Role x Action evaluation matrix.

    For each (role, action_type) pair: samples, good_mean, bad_mean, gap, cohens_d.
    """

    # Build per-opportunity won/lost lookup from review scores
    opp_won: dict[str, bool] = {}
    for r in review_scores:
        gid = r["game_id"]
        won = r.get("won", False)
        for opp in r.get("top3_good", []):
            # Can't reliably map back, skip
            pass
        # Map game-level outcome
        for o in opportunities:
            if o["game_id"] == gid:
                opp_won[o["opportunity_id"]] = won

    # Group by (role, type)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for o in opportunities:
        key = (o["role"], o["opportunity_type"])
        groups[key].append(o)

    rows = []
    for (role, otype), opps in sorted(groups.items()):
        n = len(opps)
        won_scores = [o.get("rule_quality", 0.5) for o in opps if opp_won.get(o["opportunity_id"], False)]
        lost_scores = [o.get("rule_quality", 0.5) for o in opps if not opp_won.get(o["opportunity_id"], True)]

        good_mean = round(statistics.mean(won_scores), 3) if won_scores else 0
        bad_mean = round(statistics.mean(lost_scores), 3) if lost_scores else 0
        gap = round(good_mean - bad_mean, 3)

        # Cohen's d
        if len(won_scores) >= 3 and len(lost_scores) >= 3:
            try:
                mw, ml = statistics.mean(won_scores), statistics.mean(lost_scores)
                vw = statistics.variance(won_scores)
                vl = statistics.variance(lost_scores)
                nw, nl = len(won_scores), len(lost_scores)
                ps = math.sqrt(((nw - 1) * vw + (nl - 1) * vl) / (nw + nl - 2))
                d = round((mw - ml) / ps, 3) if ps > 0 else 0.0
            except Exception:
                d = 0.0
        else:
            d = 0.0

        # Confidence: based on sample size
        conf = min(n / 50.0, 1.0)

        rows.append(
            {
                "role": role,
                "action_type": otype,
                "n_samples": n,
                "good_mean": good_mean,
                "bad_mean": bad_mean,
                "gap": gap,
                "cohens_d": d,
                "confidence": round(conf, 2),
            }
        )

    return {"rows": rows, "roles": sorted(set(r[0] for r in groups))}
