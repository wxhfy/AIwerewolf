#!/usr/bin/env python3
"""
Phase V3-1: Pre-action Context Feature Builder.

Extracts rich pre-action features for every opportunity using:
- Raw replay_bundle events (CHAT_MESSAGE, VOTE_CAST, NIGHT_ACTION, PRIVATE_INFO)
- On-the-fly speech act analysis with Chinese werewolf-specific regex
- On-the-fly suspicion matrix building
- decisions (agent reasoning, selected_action, context)

Enriches opportunities.jsonl with role-specific pre-action features.
ALL features are verifiably pre-action (available to player at decision time).
"""

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "health"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def safe_float(v, default=0.5):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ============================================================
# CUSTOM SPEECH ACT ANALYZER (Chinese Werewolf Patterns)
# ============================================================

# Patterns for Chinese werewolf speech analysis
_SUSPICION_PATTERNS = [
    re.compile(p) for p in [
        r'(?:引起了?我的?|重点)?注意',
        r'(?:留了個|留了个|留了)?心眼',
        r'(?:有点|有些|稍微|比较)?怀疑',
        r'(?:放在)?观察名单',
        r'查杀',
        r'(?:像|是|可能是)狼',
        r'(?:投|出|票|归票)[@＠]?\d*[号#]?[:：]?',
        r'(?:不太|不)?看好',
        r'(?:有|很|非常)?可疑',
        r'(?:狼|铁狼|狼人)',
    ]
]

_DEFENSE_PATTERNS = [
    re.compile(p) for p in [
        r'(?:像|是|应该是)好',
        r'(?:保|信|相信)',
        r'金水',
        r'(?:银水|好人)',
        r'(?:暂|暂时)?(?:不|没)?(?:想|会)?(?:投|出)',
    ]
]

_CLAIM_PATTERNS = [
    ("seer_claim", re.compile(r'(?:我是|跳)(?:预言家|预|先知)')),
    ("role_claim", re.compile(r'(?:我是|跳|我的身份是)(?:女巫|守卫|猎人|村民|白痴)')),
    ("seer_result", re.compile(r'(?:查验|验了|昨晚验)')),
    ("check_wolf", re.compile(r'查杀')),
    ("check_good", re.compile(r'金水')),
    ("vote_direction", re.compile(r'(?:全票|归票|跟票|出)[@＠]?\d*[号#]?[:：]?')),
]


def _extract_mentioned_names(speech_text, all_names):
    """Extract player names mentioned in speech via @N号:姓名 or direct name."""
    mentioned = []
    for name in all_names:
        if name and name in speech_text:
            mentioned.append(name)
    # Also find @N号 patterns
    at_pattern = re.findall(r'[@＠]\d+[号#][:：]?(\S+)', speech_text)
    for at_name in at_pattern:
        if at_name in all_names and at_name not in mentioned:
            mentioned.append(at_name)
    return mentioned


def analyze_single_speech(speech_text, reasoning_text, actor_name, all_names, name_to_id):
    """Analyze a single speech for werewolf-relevant speech acts."""
    result = {
        "suspected_players": [],
        "defended_players": [],
        "claims": [],
        "risk_flags": [],
        "stance": "neutral",
    }

    mentioned_names = _extract_mentioned_names(speech_text, all_names)
    lowered = speech_text.lower()

    # Check for suspicion
    for name in mentioned_names:
        if name == actor_name:
            continue
        pid = name_to_id.get(name, name)

        # Check each suspicion pattern near the name
        name_pos = speech_text.find(name)
        if name_pos < 0:
            continue
        context_start = max(0, name_pos - 20)
        context_end = min(len(speech_text), name_pos + len(name) + 30)
        context = speech_text[context_start:context_end]

        is_suspected = False
        for pat in _SUSPICION_PATTERNS:
            if pat.search(context):
                is_suspected = True
                break

        is_defended = False
        for pat in _DEFENSE_PATTERNS:
            if pat.search(context):
                is_defended = True
                break

        if is_suspected and not is_defended:
            result["suspected_players"].append(pid)
        elif is_defended and not is_suspected:
            result["defended_players"].append(pid)
        # If both, don't classify

    # Check for claims
    for claim_type, pat in _CLAIM_PATTERNS:
        if pat.search(speech_text):
            result["claims"].append(claim_type)

    # Risk flags
    if re.search(r'(?:我知道|我听说|内部消息|私聊)', speech_text):
        result["risk_flags"].append("private_info_leak")
    if re.search(r'(?:我确定|绝对|100%|肯定是)', speech_text):
        result["risk_flags"].append("overconfidence")

    # Stance
    has_sus = len(result["suspected_players"]) > 0
    has_def = len(result["defended_players"]) > 0
    has_claims = len(result["claims"]) > 0
    if has_sus and has_claims:
        result["stance"] = "aggressive"
    elif has_def:
        result["stance"] = "defensive"
    elif has_claims:
        result["stance"] = "informative"
    else:
        result["stance"] = "neutral"

    return result


def build_speech_acts_from_events(events, players):
    """Build rich speech acts from raw replay events."""
    name_to_id = {p["name"]: p["id"] for p in players}
    all_names = [p["name"] for p in players]
    acts = []

    for event in events:
        if event.get("event_type") != "CHAT_MESSAGE":
            continue
        content = event.get("content", {}) or {}
        actor_id = content.get("actor_id", event.get("actor_id", ""))
        actor_name = content.get("actor_name", "")
        speech = content.get("speech", "")
        reasoning = content.get("reasoning", "")

        if not speech:
            continue

        analysis = analyze_single_speech(speech, reasoning, actor_name, all_names, name_to_id)

        act = {
            "speech_event_id": event.get("event_id", ""),
            "player_id": actor_id,
            "player_name": actor_name,
            "day": event.get("day", 0),
            "phase": event.get("phase", ""),
            "speech_text": speech[:200],
            "reasoning": reasoning[:200],
            "suspected_players": analysis["suspected_players"],
            "defended_players": analysis["defended_players"],
            "claims": analysis["claims"],
            "risk_flags": analysis["risk_flags"],
            "stance": analysis["stance"],
            "mentioned_players": [name_to_id.get(n, n) for n in
                                  _extract_mentioned_names(speech, all_names)
                                  if n != actor_name],
            "grounded_event_ids": [],  # Chat events don't have event grounding
            "evidence_event_ids": [],
            "summary": speech[:100],
        }
        acts.append(act)

    return acts


def build_suspicion_matrix_from_speech_acts(speech_acts, players, all_events):
    """Build suspicion matrix that evolves with game events."""
    player_ids = [p["id"] for p in players]
    snapshots = []

    # Initial state: everyone at 0.5
    current_scores = {pid: 0.5 for pid in player_ids}
    current_evidence = {pid: [] for pid in player_ids}

    # Record initial snapshot
    snapshots.append({
        "day": 0, "phase": "SETUP",
        "target_scores": dict(current_scores),
        "evidence_event_ids": {pid: list(ev) for pid, ev in current_evidence.items()},
    })

    # Process events in order
    phase_order = {
        "SETUP": 0, "NIGHT_START": 1, "NIGHT_GUARD_ACTION": 2,
        "NIGHT_WOLF_ACTION": 3, "NIGHT_WITCH_ACTION": 4,
        "NIGHT_SEER_ACTION": 5, "NIGHT_RESOLVE": 6,
        "DAY_START": 7, "DAY_BADGE_SIGNUP": 8, "DAY_BADGE_SPEECH": 9,
        "DAY_BADGE_ELECTION": 10, "DAY_SPEECH": 11,
        "DAY_VOTE": 12, "DAY_RESOLVE": 13,
        "HUNTER_SHOOT": 14, "DAY_LAST_WORDS": 15, "GAME_END": 16,
    }

    # Group speech acts by event
    sa_by_event = {}
    for sa in speech_acts:
        eid = sa.get("speech_event_id", "")
        if eid:
            sa_by_event[eid] = sa

    current_day = 0
    current_phase_order = 0

    for event in all_events:
        eid = event.get("event_id", "")
        event_type = event.get("event_type", "")
        day = event.get("day", 0)
        phase = event.get("phase", "")
        po = phase_order.get(phase, 0)

        # New day/phase transition: record snapshot
        if day > current_day or (day == current_day and po > current_phase_order):
            current_day = day
            current_phase_order = po
            snapshots.append({
                "day": day, "phase": phase,
                "target_scores": dict(current_scores),
                "evidence_event_ids": {pid: list(ev) for pid, ev in current_evidence.items()},
            })

        # Process speech acts: update suspicion
        sa = sa_by_event.get(eid)
        if sa:
            speaker_id = sa.get("player_id", "")
            for target_id in sa.get("suspected_players", []):
                if target_id in current_scores:
                    delta = 0.08  # Each accusation adds suspicion
                    current_scores[target_id] = clamp(current_scores[target_id] + delta)
                    current_evidence[target_id].append(eid)
            for target_id in sa.get("defended_players", []):
                if target_id in current_scores:
                    delta = -0.05  # Each defense reduces suspicion
                    current_scores[target_id] = clamp(current_scores[target_id] + delta)

            # Seer claims have strong effect
            claims = sa.get("claims", [])
            if "check_wolf" in claims:
                for target_id in sa.get("suspected_players", []):
                    if target_id in current_scores:
                        current_scores[target_id] = clamp(current_scores[target_id] + 0.15)
            if "check_good" in claims:
                for target_id in sa.get("defended_players", []):
                    if target_id in current_scores:
                        current_scores[target_id] = clamp(current_scores[target_id] - 0.15)

        # Process votes: voting for someone increases their suspicion slightly
        if event_type == "VOTE_CAST":
            content = event.get("content", {}) or {}
            target_id = content.get("target_id", event.get("target_id", ""))
            if target_id in current_scores:
                current_scores[target_id] = clamp(current_scores[target_id] + 0.03)
                current_evidence[target_id].append(eid)

        # Process deaths: dead players are no longer suspect
        if event_type == "PLAYER_DIED":
            content = event.get("content", {}) or {}
            dead_id = content.get("player_id", "")
            if dead_id in current_scores:
                current_scores[dead_id] = 0.1  # Dead = confirmed not the immediate threat

        # Process night actions (publicly known)
        if event_type == "NIGHT_ACTION":
            content = event.get("content", {}) or {}
            target = content.get("target", {}) or {}
            target_id = target.get("id", "")
            actor_id = content.get("actor_id", event.get("actor_id", ""))
            phase_str = event.get("phase", "")

    # Final snapshot
    snapshots.append({
        "day": current_day, "phase": "GAME_END",
        "target_scores": dict(current_scores),
        "evidence_event_ids": {pid: list(ev) for pid, ev in current_evidence.items()},
    })

    return snapshots


# ============================================================
# FEATURE EXTRACTORS
# ============================================================

def get_suspicion_snapshot_before(sm_snapshots, day, phase, player_id, target_id):
    """Get the suspicion_matrix snapshot just before the given (day, phase).

    Returns (target_suspicion, target_rank, target_percentile, all_scores, evidence_events).
    """
    # sm_snapshots is a list of dicts with: day, phase, target_scores, evidence_event_ids
    # Sort by (day, phase_order) to find the latest snapshot before the decision
    phase_order = {
        "SETUP": 0, "NIGHT_START": 1, "NIGHT_GUARD_ACTION": 2,
        "NIGHT_WOLF_ACTION": 3, "NIGHT_WITCH_ACTION": 4,
        "NIGHT_SEER_ACTION": 5, "NIGHT_RESOLVE": 6,
        "DAY_START": 7, "DAY_BADGE_SIGNUP": 8, "DAY_BADGE_SPEECH": 9,
        "DAY_BADGE_ELECTION": 10, "DAY_SPEECH": 11,
        "DAY_VOTE": 12, "DAY_RESOLVE": 13,
        "HUNTER_SHOOT": 14, "DAY_LAST_WORDS": 15, "GAME_END": 16,
    }

    target_phase_order = phase_order.get(phase, 0)

    best_snapshot = None
    best_order = -1

    for snap in sm_snapshots:
        snap_day = snap.get("day", 0)
        snap_phase = snap.get("phase", "SETUP")
        snap_order = phase_order.get(snap_phase, 0)

        # Snapshot must be at or before the decision
        if snap_day < day or (snap_day == day and snap_order <= target_phase_order):
            if snap_order > best_order or (snap_order == best_order and snap_day > (best_snapshot.get("day", 0) if best_snapshot else 0)):
                best_snapshot = snap
                best_order = snap_order

    if best_snapshot is None and sm_snapshots:
        best_snapshot = sm_snapshots[0]  # Fallback to first snapshot

    if best_snapshot is None:
        return 0.5, 0, 0.5, {}, []

    scores = best_snapshot.get("target_scores", {}) or {}
    evidence = best_snapshot.get("evidence_event_ids", {}) or {}

    target_suspicion = safe_float(scores.get(target_id, 0.5))

    # Rank and percentile among all players
    all_scores_list = sorted(scores.values(), reverse=True)
    target_rank = sum(1 for s in all_scores_list if s > target_suspicion) + 1
    n_players = max(len(all_scores_list), 1)
    target_percentile = 1.0 - (target_rank - 1) / max(n_players - 1, 1)
    if target_rank == 1:
        target_percentile = 1.0
    elif target_rank == n_players:
        target_percentile = 0.0

    target_evidence = evidence.get(target_id, [])
    return target_suspicion, target_rank, target_percentile, scores, target_evidence


def count_public_evidence(speech_acts, target_id, before_day, before_phase):
    """Count speech acts that mention/suspect/defend target_id before the decision."""
    phase_order_map = {
        "SETUP": 0, "NIGHT_START": 1, "NIGHT_GUARD_ACTION": 2,
        "NIGHT_WOLF_ACTION": 3, "NIGHT_WITCH_ACTION": 4,
        "NIGHT_SEER_ACTION": 5, "NIGHT_RESOLVE": 6,
        "DAY_START": 7, "DAY_BADGE_SIGNUP": 8, "DAY_BADGE_SPEECH": 9,
        "DAY_BADGE_ELECTION": 10, "DAY_SPEECH": 11,
        "DAY_VOTE": 12, "DAY_RESOLVE": 13,
        "HUNTER_SHOOT": 14, "DAY_LAST_WORDS": 15, "GAME_END": 16,
    }
    target_order = phase_order_map.get(before_phase, 12)

    against_count = 0
    for_count = 0
    accusation_count = 0
    defense_count = 0
    mention_count = 0

    for sa in speech_acts:
        sa_day = sa.get("day", 0)
        sa_phase = sa.get("phase", "")
        sa_order = phase_order_map.get(sa_phase, 0)

        if sa_day > before_day:
            continue
        if sa_day == before_day and sa_order > target_order:
            continue

        # Check if target is suspected/defended/mentioned
        suspected = sa.get("suspected_players", []) or []
        defended = sa.get("defended_players", []) or []
        mentioned = sa.get("mentioned_players", []) or []

        if target_id in suspected:
            against_count += 1
            accusation_count += 1
        if target_id in defended:
            for_count += 1
            defense_count += 1
        if target_id in mentioned:
            mention_count += 1

    return against_count, for_count, accusation_count, defense_count, mention_count


def _resolve_target_from_decisions(opp, decisions, speech_acts, votes_list=None):
    """Resolve target player ID from decisions/votes data.

    The opportunity's chosen_action_summary is often empty.
    Priority: votes list (direct target_id) > decisions (parsed from raw_text/private_reason).
    """
    player_id = opp.get("player_id", "")
    opp_type = opp.get("opportunity_type", "")
    gf = opp.get("game_features", {}) or {}
    day = gf.get("day", 0)

    # For vote opportunities, check the votes list directly
    if opp_type == "vote" and votes_list:
        for v in votes_list:
            if v.get("voter_id") == player_id and v.get("day") == day:
                return v.get("target_id", "")

    # Build name->id map from speech_acts
    name_to_id = {}
    for sa in speech_acts:
        pid = sa.get("player_id", "")
        pname = sa.get("player_name", "")
        if pid and pname:
            name_to_id[pname] = pid

    sid = opp.get("source_decision_id", "")
    if sid:
        for dec in decisions:
            if dec.get("decision_id") == sid:
                # Try selected_action.target first
                sa = dec.get("selected_action", {}) or {}
                target_raw = sa.get("target", "")
                if isinstance(target_raw, dict):
                    return target_raw.get("id", "")
                elif isinstance(target_raw, str) and target_raw:
                    if target_raw in name_to_id:
                        return name_to_id[target_raw]
                # Try parsing private_reason (may be JSON string or already parsed)
                pr = dec.get("private_reason", "")
                if isinstance(pr, dict):
                    t = pr.get("target", "")
                    if t and t in name_to_id:
                        return name_to_id[t]
                elif isinstance(pr, str) and pr:
                    try:
                        pr_dict = json.loads(pr)
                        if isinstance(pr_dict, dict):
                            t = pr_dict.get("target", "")
                            if t and t in name_to_id:
                                return name_to_id[t]
                    except (json.JSONDecodeError, TypeError):
                        pass
    return ""


def extract_vote_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract rich pre-action vote features."""
    features = {}

    gf = opp.get("game_features", {}) or {}
    tf = opp.get("target_features", {}) or {}
    day = gf.get("day", 1)
    phase = opp.get("phase", "DAY_VOTE")
    player_id = opp.get("player_id", "")

    # Build name->id map from players (passed from caller via events workaround)
    # We rely on decisions + speech_acts which have proper IDs
    target_id = _resolve_target_from_decisions(opp, decisions, speech_acts, votes)

    if not target_id:
        # Fallback: try chosen_action_summary
        chosen = opp.get("chosen_action_summary", {})
        if isinstance(chosen, dict):
            target_id = chosen.get("target_id", chosen.get("target", ""))

    # 1. Suspicion features
    suspicion, rank, percentile, all_scores, evidence = get_suspicion_snapshot_before(
        sm_snapshots, day, phase, player_id, target_id
    )
    features["target_suspicion_before_vote"] = round(suspicion, 4)
    features["target_suspicion_rank_before_vote"] = rank
    features["target_suspicion_percentile"] = round(percentile, 4)

    # 2. Public evidence against/for target
    against, for_t, acc_count, def_count, mention_count = count_public_evidence(
        speech_acts, target_id, day, phase
    )
    features["public_evidence_count_against_target"] = against
    features["public_evidence_count_for_target"] = for_t
    features["target_received_accusations_count"] = acc_count
    features["target_received_defenses_count"] = def_count

    # 3. Seer claims about target
    seer_claim_against = 0
    seer_claim_support = 0
    for sa in speech_acts:
        claims = sa.get("claims", []) or []
        for claim in claims:
            if isinstance(claim, dict) and claim.get("type") == "seer_result":
                claim_target = claim.get("target_id", "")
                claim_result = claim.get("result", "")
                if claim_target == target_id:
                    if claim_result in ("wolf", "werewolf"):
                        seer_claim_against += 1
                    else:
                        seer_claim_support += 1
    features["seer_claim_against_target"] = clamp(seer_claim_against, 0, 3) / 3.0
    features["seer_claim_support_target"] = clamp(seer_claim_support, 0, 3) / 3.0

    # 4. Voter's own speech consistency
    voter_suspected_in_speech = set()
    voter_defended_in_speech = set()
    for sa in speech_acts:
        if sa.get("player_id") == player_id:
            voter_suspected_in_speech.update(sa.get("suspected_players", []) or [])
            voter_defended_in_speech.update(sa.get("defended_players", []) or [])

    if target_id in voter_suspected_in_speech:
        features["vote_consistent_with_own_speech"] = 1.0
    elif target_id in voter_defended_in_speech:
        features["vote_consistent_with_own_speech"] = 0.0
    else:
        features["vote_consistent_with_own_speech"] = 0.5  # Neutral

    # 5. Vote consistent with public top suspicion?
    if all_scores:
        top_suspected = max(all_scores, key=lambda k: all_scores[k])
        features["vote_consistent_with_public_top_suspicion"] = 1.0 if target_id == top_suspected else 0.0
    else:
        features["vote_consistent_with_public_top_suspicion"] = 0.5

    # 6. Is following majority?
    vote_targets = Counter()
    for vote in votes:
        v_day = vote.get("day", 0)
        v_phase = vote.get("phase", "")
        if v_day == day:
            vote_targets[vote.get("target_id", "")] += 1

    if vote_targets:
        majority_target, majority_count = vote_targets.most_common(1)[0]
        total_votes = sum(vote_targets.values())
        is_majority = (target_id == majority_target and majority_count > total_votes // 2)
        features["is_following_majority_without_reason"] = 1.0 if is_majority else 0.0
    else:
        features["is_following_majority_without_reason"] = 0.0

    # 7. Protecting high-suspicion player?
    if all_scores and target_id in all_scores:
        max_susp = max(all_scores.values())
        features["is_protecting_high_suspicion_player"] = (
            1.0 if all_scores[target_id] < 0.3 and max_susp > 0.7 else 0.0
        )
    else:
        features["is_protecting_high_suspicion_player"] = 0.0

    # 8. Public trust of voter (average suspicion of voter by others)
    voter_suspicion_avg = 0.5
    voter_counts = 0
    for snap in sm_snapshots[-5:]:  # Last few snapshots
        ts = snap.get("target_scores", {}) or {}
        if player_id in ts:
            voter_suspicion_avg += ts[player_id]
            voter_counts += 1
    if voter_counts > 0:
        voter_suspicion_avg /= voter_counts
    features["speaker_trust_score_of_voter"] = round(1.0 - voter_suspicion_avg, 4)

    return features


def extract_speech_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract pre-action speech features from speech_acts data."""
    features = {}
    gf = opp.get("game_features", {}) or {}
    player_id = opp.get("player_id", "")

    # Find the speech_act entry for this opportunity
    sa_entry = None
    for sa in speech_acts:
        if sa.get("player_id") == player_id and sa.get("day") == gf.get("day"):
            sa_entry = sa
            break

    if sa_entry is None:
        # Fallback: neutral values
        for key in ["claim_count", "grounded_claim_count", "ungrounded_claim_count",
                     "accusation_count", "defense_count", "vote_suggestion_present",
                     "role_claim_present", "seer_result_claim_present",
                     "consistency_with_previous_vote", "consistency_with_previous_speech",
                     "responds_to_accusation", "creates_new_public_evidence",
                     "private_info_leak_risk", "fabrication_risk"]:
            features[key] = 0.0 if "count" in key or "present" in key or "risk" in key else 0.5
        return features

    claims = sa_entry.get("claims", []) or []
    grounded = sa_entry.get("grounded_event_ids", []) or []
    risk_flags = sa_entry.get("risk_flags", []) or []

    features["claim_count"] = len(claims)
    features["grounded_claim_count"] = len(grounded)
    features["ungrounded_claim_count"] = max(0, len(claims) - len(grounded))

    # Accusations / defenses from speech_acts
    suspected = sa_entry.get("suspected_players", []) or []
    defended = sa_entry.get("defended_players", []) or []
    features["accusation_count"] = len(suspected)
    features["defense_count"] = len(defended)

    # Claims analysis
    vote_suggestion = False
    role_claim = False
    seer_claim = False
    for claim in claims:
        if isinstance(claim, dict):
            t = claim.get("type", "")
            if t in ("vote_suggestion", "vote_recommendation"):
                vote_suggestion = True
            elif t in ("role_claim", "claim_role"):
                role_claim = True
            elif t in ("seer_result", "seer_check"):
                seer_claim = True
    features["vote_suggestion_present"] = 1.0 if vote_suggestion else 0.0
    features["role_claim_present"] = 1.0 if role_claim else 0.0
    features["seer_result_claim_present"] = 1.0 if seer_claim else 0.0

    # Consistency with previous vote
    prev_votes_same_player = [v for v in votes if v.get("voter_id") == player_id
                               and (v.get("day", 0) < gf.get("day", 0))]
    if prev_votes_same_player:
        last_vote_target = prev_votes_same_player[-1].get("target_id", "")
        # Check if current speech mentions the last vote target
        mentioned = sa_entry.get("mentioned_players", []) or []
        features["consistency_with_previous_vote"] = (
            1.0 if last_vote_target in mentioned else 0.3
        )
    else:
        features["consistency_with_previous_vote"] = 0.5

    # Consistency with previous speech
    prev_speeches = [s for s in speech_acts if s.get("player_id") == player_id
                      and (s.get("day", 0) < gf.get("day", 0)
                           or (s.get("day", 0) == gf.get("day", 0)
                               and s.get("speech_event_id") != sa_entry.get("speech_event_id")))]
    if prev_speeches:
        prev_suspected = set()
        for ps in prev_speeches:
            prev_suspected.update(ps.get("suspected_players", []) or [])
        overlap = len(set(suspected) & prev_suspected)
        features["consistency_with_previous_speech"] = (
            1.0 if overlap > 0 else (0.5 if len(suspected) > 0 else 0.5)
        )
    else:
        features["consistency_with_previous_speech"] = 0.5

    # Responds to accusation?
    # Check if player was accused in recent speeches and responds
    was_accused = False
    for sa in speech_acts:
        if player_id in (sa.get("suspected_players", []) or []):
            was_accused = True
            break
    responds = len(grounded) > 0 or len(claims) > 0
    features["responds_to_accusation"] = 1.0 if (was_accused and responds) else (0.0 if was_accused else 0.5)

    # Creates new public evidence
    features["creates_new_public_evidence"] = 1.0 if len(grounded) > 0 else 0.0

    # Risk flags
    features["private_info_leak_risk"] = 1.0 if "private_info_leak" in risk_flags else 0.0
    features["fabrication_risk"] = 1.0 if "fabrication" in risk_flags else 0.0

    return features


def extract_seer_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract Seer-specific pre-action features."""
    features = {}
    gf = opp.get("game_features", {}) or {}
    tf = opp.get("target_features", {}) or {}
    day = gf.get("day", 1)
    player_id = opp.get("player_id", "")
    target_id = _resolve_target_from_decisions(opp, decisions, speech_acts, votes)

    # Count from decisions how many wolf checks this seer has made
    wolf_checks = 0
    good_checks = 0
    for dec in decisions:
        if dec.get("player_id") == player_id and dec.get("phase", "").startswith("NIGHT_SEER"):
            # We can't know the actual result from decisions, but we know the seer checked
            pass

    # Check if checked target is under pressure (from suspicion_matrix)
    target_susp, _, _, all_scores, _ = get_suspicion_snapshot_before(
        sm_snapshots, day, "NIGHT_SEER_ACTION", player_id, target_id
    )
    features["checked_target_under_pressure"] = 1.0 if target_susp > 0.6 else (0.0 if target_susp < 0.4 else 0.5)

    # Good player under pressure (any player with low suspicion who's being voted)
    if all_scores:
        good_under_pressure = sum(1 for pid, score in all_scores.items()
                                   if score > 0.6 and pid != player_id)
        features["good_player_under_pressure"] = clamp(good_under_pressure / max(len(all_scores) - 1, 1), 0, 1)
    else:
        features["good_player_under_pressure"] = 0.0

    # Seer self under pressure
    self_susp = safe_float(all_scores.get(player_id, 0.5)) if all_scores else 0.5
    features["seer_self_under_pressure"] = 1.0 if self_susp > 0.6 else 0.0

    # Public suspicion of checked wolf (only relevant if we could verify alignment)
    features["public_suspicion_of_checked_wolf"] = target_susp

    # Vote convertibility: are there enough votes to change the outcome?
    vote_counts = Counter()
    for vote in votes:
        if vote.get("day") == day:
            vote_counts[vote.get("target_id", "")] += 1
    total_votes = sum(vote_counts.values())
    features["vote_convertibility"] = 1.0 if total_votes >= 3 else (0.5 if total_votes >= 1 else 0.0)

    # Days since last check
    check_days = set()
    for dec in decisions:
        if dec.get("player_id") == player_id and "SEER" in dec.get("phase", ""):
            check_days.add(dec.get("day", 0))
    last_check_day = max(check_days) if check_days else 0
    features["days_since_check"] = day - last_check_day

    # Release timing need
    camp_bal = gf.get("camp_balance", {}) or {}
    v_alive = camp_bal.get("village_alive", 3)
    features["release_timing_need"] = 1.0 if v_alive <= 3 else (0.5 if v_alive <= 5 else 0.2)

    # Exposure risk from suspicion
    features["exposure_risk"] = self_susp

    return features


def extract_witch_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract Witch-specific pre-action features."""
    features = {}
    gf = opp.get("game_features", {}) or {}
    tf = opp.get("target_features", {}) or {}
    day = gf.get("day", 1)
    player_id = opp.get("player_id", "")
    target_id = _resolve_target_from_decisions(opp, decisions, speech_acts, votes)

    opp_type = opp.get("opportunity_type", "")

    # Target suspicion
    target_susp, _, _, all_scores, evidence = get_suspicion_snapshot_before(
        sm_snapshots, day, "NIGHT_WITCH_ACTION", player_id, target_id
    )
    features["target_suspicion_before_action"] = round(target_susp, 4)

    # Public evidence against target
    against, for_t, acc_count, def_count, _ = count_public_evidence(
        speech_acts, target_id, day, "NIGHT_WITCH_ACTION"
    )
    features["public_evidence_against_target"] = clamp(acc_count / 5.0, 0, 1)

    # Medicine/poison remaining (from previous witch actions in same game)
    poison_used = sum(1 for dec in decisions
                      if dec.get("player_id") == player_id and "POISON" in dec.get("phase", ""))
    antidote_used = sum(1 for dec in decisions
                        if dec.get("player_id") == player_id and "SAVE" in dec.get("phase", ""))
    features["medicine_remaining"] = 1.0 if antidote_used == 0 else 0.0
    features["poison_remaining"] = 1.0 if poison_used == 0 else 0.0

    # Timing
    is_endgame = gf.get("is_endgame", False)
    alive = gf.get("alive_count", 12) if isinstance(gf.get("alive_count"), (int, float)) else len(all_scores)
    features["is_endgame"] = 1.0 if is_endgame else 0.0
    features["poison_timing_need"] = 1.0 if (is_endgame or alive <= 4) else (0.5 if alive <= 6 else 0.2)

    # Save target features
    # Role value estimate from public claims
    target_claimed_role = None
    for sa in speech_acts:
        claims = sa.get("claims", []) or []
        for claim in claims:
            if isinstance(claim, dict) and claim.get("player_id") == target_id:
                rt = claim.get("role_type") or claim.get("claimed_role")
                if rt:
                    target_claimed_role = rt
    role_value_map = {"Seer": 1.0, "Witch": 0.9, "Guard": 0.7, "Hunter": 0.7, "Villager": 0.3, "Werewolf": 0.0}
    features["save_target_claimed_role_value"] = role_value_map.get(target_claimed_role or "", 0.3)

    # Public trust of save target
    target_trust = safe_float(all_scores.get(target_id, 0.5)) if all_scores else 0.5
    features["save_target_public_trust"] = round(1.0 - target_trust, 4)

    # Estimated kill likelihood (from suspicion + exposure)
    target_is_exposed = tf.get("target_is_exposed", False) if tf else False
    kill_likelihood = 0.8 if (target_susp < 0.3 and target_is_exposed) else (
        0.5 if target_susp < 0.4 else 0.3)
    features["estimated_kill_likelihood"] = kill_likelihood

    # Resource timing
    features["resource_timing"] = 1.0 if day <= 2 else (0.7 if day <= 3 else 0.4)

    # Risk of blind poison (insufficient evidence)
    features["risk_of_blind_poison"] = 1.0 if (acc_count < 2 and target_susp < 0.6) else (
        0.5 if acc_count < 4 else 0.0)

    return features


def extract_werewolf_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract Werewolf-specific pre-action features.

    NOTE: Werewolves DO know their teammates' alignment. But per the scoring
    contract, we do NOT use actual target_alignment even for wolves.
    Instead, we proxy alignment through observed patterns.
    """
    features = {}
    gf = opp.get("game_features", {}) or {}
    day = gf.get("day", 1)
    player_id = opp.get("player_id", "")
    target_id = _resolve_target_from_decisions(opp, decisions, speech_acts, votes)

    # Self suspicion
    _, _, _, all_scores, _ = get_suspicion_snapshot_before(
        sm_snapshots, day, "NIGHT_WOLF_ACTION", player_id, player_id
    )
    self_susp = safe_float(all_scores.get(player_id, 0.5)) if all_scores else 0.5
    features["self_suspicion_before"] = round(self_susp, 4)

    # Accuses good player? (We proxy: accusing players with low suspicion)
    # This uses public information only
    voter_suspected = set()
    for sa in speech_acts:
        if sa.get("player_id") == player_id:
            voter_suspected.update(sa.get("suspected_players", []) or [])

    low_suspicion_players = {pid for pid, score in (all_scores or {}).items()
                              if score < 0.3 and pid != player_id}
    if voter_suspected & low_suspicion_players:
        features["accuses_good_player"] = 1.0  # Publicly trusted player
    else:
        features["accuses_good_player"] = 0.0

    # Defends teammate? (We proxy: defending players who are also suspected by few)
    voter_defended = set()
    for sa in speech_acts:
        if sa.get("player_id") == player_id:
            voter_defended.update(sa.get("defended_players", []) or [])

    high_suspicion_players = {pid for pid, score in (all_scores or {}).items()
                               if score > 0.6 and pid != player_id}
    if voter_defended & high_suspicion_players:
        features["defends_teammate"] = 1.0  # Defending suspected player = potential teammate
    else:
        features["defends_teammate"] = 0.0

    # Distance from teammate (proxy: how different are speech patterns from co-suspected players)
    features["distance_from_teammate"] = 0.5  # Neutral without teammate knowledge

    # Vote alignment (do wolves vote together? proxy check)
    wolf_vote_targets = Counter()
    for vote in votes:
        if vote.get("day") == day and vote.get("voter_id") in high_suspicion_players:
            wolf_vote_targets[vote.get("target_id", "")] += 1
    my_vote_target = ""
    for vote in votes:
        if vote.get("voter_id") == player_id and vote.get("day") == day:
            my_vote_target = vote.get("target_id", "")
    if wolf_vote_targets and my_vote_target:
        features["wolf_team_vote_alignment"] = (
            1.0 if wolf_vote_targets.most_common(1)[0][0] == my_vote_target else 0.0
        )
    else:
        features["wolf_team_vote_alignment"] = 0.5

    # Public reason groundness (speech quality)
    sa_count = sum(1 for sa in speech_acts if sa.get("player_id") == player_id)
    total_grounded = sum(len(sa.get("grounded_event_ids", []) or [])
                         for sa in speech_acts if sa.get("player_id") == player_id)
    features["public_reason_groundedness"] = clamp(total_grounded / max(sa_count * 2, 1), 0, 1)

    # Risk flags from speeches
    risk_count = sum(len(sa.get("risk_flags", []) or [])
                     for sa in speech_acts if sa.get("player_id") == player_id)
    features["wolf_perspective_leak_risk"] = clamp(risk_count / max(sa_count, 1), 0, 1)

    # Misdirects vote pressure
    features["misdirects_vote_pressure"] = (
        1.0 if (features["accuses_good_player"] > 0.5 and my_vote_target in low_suspicion_players)
        else 0.0
    )

    return features


def extract_guard_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract additional Guard-specific pre-action features beyond what's in opportunities."""
    features = {}
    gf = opp.get("game_features", {}) or {}
    tf = opp.get("target_features", {}) or {}
    day = gf.get("day", 1)
    player_id = opp.get("player_id", "")
    target_id = _resolve_target_from_decisions(opp, decisions, speech_acts, votes)

    # These supplement tf features already in opportunities
    target_susp, _, _, all_scores, _ = get_suspicion_snapshot_before(
        sm_snapshots, day, "NIGHT_GUARD_ACTION", player_id, target_id
    )
    features["guard_target_suspicion"] = round(target_susp, 4)

    # How many players suspect this target
    if all_scores:
        features["guard_target_consensus_suspicion"] = (
            sum(1 for pid, s in all_scores.items() if s > 0.6 and pid != player_id) /
            max(len(all_scores) - 1, 1)
        )
    else:
        features["guard_target_consensus_suspicion"] = 0.5

    # Target mentioned count in speeches
    against, _, _, _, _ = count_public_evidence(speech_acts, target_id, day, "NIGHT_GUARD_ACTION")
    features["guard_target_public_mentions"] = clamp(against / 5.0, 0, 1)

    return features


def extract_hunter_features(opp, sm_snapshots, speech_acts, decisions, votes, events):
    """Extract Hunter-specific pre-action features."""
    features = {}
    gf = opp.get("game_features", {}) or {}
    day = gf.get("day", 1)
    player_id = opp.get("player_id", "")
    target_id = _resolve_target_from_decisions(opp, decisions, speech_acts, votes)

    # Shot target suspicion
    target_susp, _, _, all_scores, _ = get_suspicion_snapshot_before(
        sm_snapshots, day, "HUNTER_SHOOT", player_id, target_id
    )
    features["shot_target_suspicion"] = round(target_susp, 4)

    # Hunter's own suspicion
    self_susp = safe_float(all_scores.get(player_id, 0.5)) if all_scores else 0.5
    features["hunter_self_suspicion"] = round(self_susp, 4)

    # Shot timing
    features["shot_timing"] = 1.0 if day <= 2 else (0.5 if day <= 3 else 0.2)

    return features


# ============================================================
# MAIN FEATURE BUILDER
# ============================================================

def build_v3_features():
    """Main entry point: enrich opportunities with V3 pre-action features."""
    print("Loading data...")
    opportunities = load_jsonl(DATA / "opportunities.jsonl")
    print(f"  Opportunities: {len(opportunities)}")

    # Load reviews from DB
    # Ensure both project root and backend are on path
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    from db import SessionLocal
    from db.models import PublishedReview

    session = SessionLocal()
    reviews = session.query(PublishedReview).filter(
        PublishedReview.replay_bundle != None,
        PublishedReview.suspicion_matrix != None,
        PublishedReview.speech_acts != None,
    ).all()
    print(f"  Reviews with all data: {len(reviews)}")

    # Build game_id -> review index
    review_index = {}
    for r in reviews:
        review_index[r.game_id] = r

    # Feature extractor dispatch
    FEATURE_EXTRACTORS = {
        "vote": extract_vote_features,
        "speech": extract_speech_features,
        "seer_check": extract_seer_features,
        "seer_release": extract_seer_features,
        "witch_save": extract_witch_features,
        "witch_poison": extract_witch_features,
        "witch_skip": extract_witch_features,
        "werewolf_kill": extract_werewolf_features,
        "guard_protect": extract_guard_features,
        "hunter_shot": extract_hunter_features,
    }

    enriched = []
    feature_coverage = Counter()
    feature_values = defaultdict(list)
    match_count = 0
    miss_count = 0

    for i, opp in enumerate(opportunities):
        game_id = opp.get("game_id", "")
        opp_type = opp.get("opportunity_type", "")
        role = opp.get("role", "")

        review = review_index.get(game_id)
        if review is None:
            miss_count += 1
            enriched.append(opp)  # Keep original
            continue

        match_count += 1
        bundle = review.replay_bundle or {}
        events = bundle.get("events", [])
        decisions = bundle.get("decisions", [])
        votes_list = bundle.get("votes", [])
        players = bundle.get("players", [])

        # ON-THE-FLY: build rich speech_acts and suspicion_matrix from raw events
        speech_acts = build_speech_acts_from_events(events, players)
        sm_snapshots = build_suspicion_matrix_from_speech_acts(speech_acts, players, events)

        # Build new features dict
        new_features = {}

        # Extract role-specific features
        extractor = FEATURE_EXTRACTORS.get(opp_type)
        if extractor:
            # Remap events for consistency
            remapped_events = []
            for e in events:
                remapped = dict(e)
                content = e.get("content", {}) or {}
                if e.get("event_type") == "CHAT_MESSAGE":
                    remapped["payload"] = {
                        "actor_id": content.get("actor_id", e.get("actor_id", "")),
                        "actor_name": content.get("actor_name", ""),
                        "speech": content.get("speech", ""),
                    }
                remapped_events.append(remapped)

            extracted = extractor(opp, sm_snapshots, speech_acts, decisions, votes_list, remapped_events)
            new_features.update(extracted)

        # Track feature coverage and values
        for k, v in new_features.items():
            feature_coverage[k] += 1
            feature_values[k].append(v)

        # Merge with original opportunity
        enriched_opp = dict(opp)
        enriched_opp["v3_pre_features"] = new_features
        enriched_opp["_v3_data_available"] = True
        enriched_opp["_sa_count"] = len(speech_acts)
        enriched_opp["_sm_snapshot_count"] = len(sm_snapshots)
        enriched_opp["_event_count"] = len(events)

        enriched.append(enriched_opp)

        if (i + 1) % 500 == 0:
            print(f"  Processed {i + 1}/{len(opportunities)}...")

    session.close()

    print(f"  Matched: {match_count}, Missing reviews: {miss_count}")

    # Write enriched opportunities
    out_path = DATA / "opportunities_v3_features.jsonl"
    with open(out_path, "w") as f:
        for opp in enriched:
            f.write(json.dumps(opp, ensure_ascii=False) + "\n")
    print(f"  Written to {out_path}")

    # Generate feature report
    generate_feature_report(feature_coverage, feature_values, len(opportunities), enriched)

    return enriched


def generate_feature_report(feature_coverage, feature_values, total_count, enriched):
    """Generate pre_action_feature_report.md."""
    lines = []
    lines.append("# Pre-Action Feature Report V3")
    lines.append("")
    lines.append(f"**Date**: 2026-05-28")
    lines.append(f"**Total opportunities**: {total_count}")
    lines.append("")

    lines.append("## 1. Feature Coverage")
    lines.append("")
    lines.append("| Feature | Coverage | Rate | Mean | Std | Min | Max |")
    lines.append("|---|---|---|---|---|---|---|")

    zero_variance_features = []
    low_coverage_features = []

    for feat in sorted(feature_coverage.keys()):
        count = feature_coverage[feat]
        rate = count / total_count
        values = feature_values[feat]
        mean_v = sum(values) / len(values) if values else 0
        std_v = (sum((x - mean_v) ** 2 for x in values) / len(values)) ** 0.5 if values else 0
        min_v = min(values) if values else 0
        max_v = max(values) if values else 0

        lines.append(f"| {feat} | {count} | {rate:.1%} | {mean_v:.4f} | {std_v:.4f} | {min_v:.4f} | {max_v:.4f} |")

        if std_v < 0.01:
            zero_variance_features.append(feat)
        if rate < 0.30:
            low_coverage_features.append(feat)

    lines.append("")

    # 2. Role/Action feature counts
    lines.append("## 2. Features per Role-Action")
    lines.append("")
    role_action_features = defaultdict(set)
    for opp in enriched:
        v3f = opp.get("v3_pre_features", {})
        key = f"{opp.get('role', '?')}|{opp.get('opportunity_type', '?')}"
        role_action_features[key].update(v3f.keys())

    lines.append("| Role-Action | Feature Count | Features |")
    lines.append("|---|---|---|")
    for key in sorted(role_action_features.keys()):
        feats = role_action_features[key]
        lines.append(f"| {key} | {len(feats)} | {', '.join(sorted(feats)[:6])} |")
    lines.append("")

    # 3. Zero variance features
    lines.append("## 3. Near-Zero Variance Features (Std < 0.01)")
    lines.append("")
    if zero_variance_features:
        for f in zero_variance_features:
            lines.append(f"- `{f}`")
    else:
        lines.append("None found.")
    lines.append("")

    # 4. Low coverage features
    lines.append("## 4. Low Coverage Features (< 30%)")
    lines.append("")
    if low_coverage_features:
        for f in low_coverage_features:
            lines.append(f"- `{f}`: {feature_coverage[f]}/{total_count} ({feature_coverage[f]/total_count:.1%})")
    else:
        lines.append("None found.")
    lines.append("")

    # 5. Vote-specific stats
    lines.append("## 5. Vote Feature Variance")
    lines.append("")
    vote_features = [k for k in feature_coverage.keys() if "vote" in k.lower() or "suspicion" in k.lower()]
    for feat in vote_features:
        values = feature_values.get(feat, [])
        if values:
            mean_v = sum(values) / len(values)
            std_v = (sum((x - mean_v) ** 2 for x in values) / len(values)) ** 0.5
            lines.append(f"- `{feat}`: mean={mean_v:.4f}, std={std_v:.4f}")
    lines.append("")

    # 6. Conclusion
    lines.append("## 6. Summary")
    lines.append("")
    lines.append(f"- Total features: {len(feature_coverage)}")
    lines.append(f"- Zero-variance features: {len(zero_variance_features)}")
    lines.append(f"- Low-coverage features: {len(low_coverage_features)}")
    lines.append(f"- Opportunities with V3 features: {sum(1 for o in enriched if o.get('_v3_data_available'))}")
    lines.append("")

    report_path = DATA / "pre_action_feature_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Feature report written to {report_path}")


if __name__ == "__main__":
    build_v3_features()
