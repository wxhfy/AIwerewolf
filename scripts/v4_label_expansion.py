#!/usr/bin/env python3
"""
V4 Label Expansion Pipeline (Phases V4-1, V4-2).

V4-1: Hard Negative Mining - algorithmically identify likely bad decisions
      from existing opportunities using V3 pre-action features.

V4-2: Counterfactual Pairwise Generation - construct action_a vs action_b
      pairs where one action is clearly better given available information.
"""

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "health"


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ============================================================
# V4-1: HARD NEGATIVE MINING
# ============================================================

def mine_vote_bad_candidates(opp, feats):
    """Identify vote decisions that look bad based on pre-action features."""
    reasons = []

    # 1. Voting for low suspicion target when high suspicion targets exist
    target_susp = feats.get("target_suspicion_percentile", 0.5)
    voted_top = feats.get("vote_consistent_with_public_top_suspicion", 0.5)
    if voted_top < 0.3 and target_susp < 0.4:
        reasons.append("vote_low_suspicion_ignore_high")

    # 2. Vote contradicts own speech
    vcos = feats.get("vote_consistent_with_own_speech", 0.5)
    if vcos < 0.3:
        reasons.append("vote_contradicts_own_speech")

    # 3. Following majority without reason
    is_following = feats.get("is_following_majority_without_reason", 0.0)
    if is_following > 0.5:
        reasons.append("following_majority_without_reason")

    # 4. Protecting high suspicion player
    is_protecting = feats.get("is_protecting_high_suspicion_player", 0.0)
    if is_protecting > 0.5:
        reasons.append("protecting_high_suspicion_player")

    # 5. Low trust voter making high-stakes vote
    trust = feats.get("speaker_trust_score_of_voter", 0.5)
    if trust < 0.3 and voted_top < 0.3:
        reasons.append("low_trust_voter_making_contrarian_vote")

    confidence = min(0.9, len(reasons) * 0.25 + 0.3) if reasons else 0.0
    return reasons, confidence


def mine_witch_bad_candidates(opp, feats):
    """Identify Witch decisions that look bad."""
    reasons = []
    opp_type = opp.get("opportunity_type", "")

    if opp_type == "witch_poison":
        # Low evidence poison
        evidence = feats.get("public_evidence_against_target", 0.0)
        target_susp = feats.get("target_suspicion_before_action", 0.5)
        if evidence < 0.2 and target_susp < 0.5:
            reasons.append("low_evidence_poison_low_suspicion_target")

        # Blind poison in non-endgame
        is_endgame = feats.get("is_endgame", 0.0)
        blind_risk = feats.get("risk_of_blind_poison", 0.0)
        if blind_risk > 0.7 and is_endgame < 0.5:
            reasons.append("blind_poison_non_critical_round")

    elif opp_type == "witch_save":
        # Saving low value target
        role_val = feats.get("save_target_claimed_role_value", 0.3)
        if role_val < 0.5:
            reasons.append("saving_low_value_target")

        # Early antidote on low-kill-likelihood target
        kill_likelihood = feats.get("estimated_kill_likelihood", 0.3)
        if kill_likelihood < 0.4:
            reasons.append("using_antidote_on_low_risk_target")

    elif opp_type == "witch_skip":
        # Skipping when high suspicion target exists
        target_susp = feats.get("target_suspicion_before_action", 0.5)
        if target_susp > 0.6:
            reasons.append("skipping_when_high_suspicion_target_exists")

    confidence = min(0.9, len(reasons) * 0.3 + 0.2) if reasons else 0.0
    return reasons, confidence


def mine_seer_bad_candidates(opp, feats):
    """Identify Seer decisions that look bad."""
    reasons = []
    opp_type = opp.get("opportunity_type", "")

    if opp_type == "seer_check":
        # Checking low-information target
        target_susp = feats.get("checked_target_under_pressure", 0.5)
        good_pressure = feats.get("good_player_under_pressure", 0.0)
        if target_susp < 0.3 and good_pressure > 0.3:
            reasons.append("checking_low_info_target_when_good_under_pressure")

        # Checking already-exposed player
        days_since = feats.get("days_since_check", 0)
        if days_since < -1:
            reasons.append("checking_already_exposed_player")

    elif opp_type == "seer_release":
        # Seer under pressure but hiding info
        self_pressure = feats.get("seer_self_under_pressure", 0.0)
        release_timing = feats.get("release_timing_need", 0.5)
        if self_pressure < 0.5 and release_timing > 0.7:
            reasons.append("hiding_critical_info_when_release_needed")

    confidence = min(0.9, len(reasons) * 0.3 + 0.2) if reasons else 0.0
    return reasons, confidence


def mine_werewolf_bad_candidates(opp, feats):
    """Identify Werewolf decisions that look bad."""
    reasons = []
    opp_type = opp.get("opportunity_type", "")

    # Self-suspicion check - high suspicion wolves making aggressive moves
    self_susp = feats.get("self_suspicion_before", 0.5)
    if self_susp > 0.7:
        reasons.append("high_suspicion_wolf_making_aggressive_move")

    # Group behavior indicators
    if opp_type == "vote":
        wolf_alignment = feats.get("wolf_team_vote_alignment", 0.5)
        if wolf_alignment > 0.8:
            reasons.append("wolf_team_voting_together_obviously")

        # Accusing good player (low suspicion = publicly trusted)
        accuses_good = feats.get("accuses_good_player", 0.0)
        if accuses_good > 0.5 and self_susp < 0.3:
            reasons.append("low_suspicion_wolf_accusing_trusted_player")

    elif opp_type == "werewolf_kill":
        # Killing low-value target
        accuses_good = feats.get("accuses_good_player", 0.0)
        if accuses_good < 0.5:
            reasons.append("killing_low_priority_target")

    # Leak risk
    leak_risk = feats.get("wolf_perspective_leak_risk", 0.0)
    if leak_risk > 0.3:
        reasons.append("wolf_perspective_leak_in_speech")

    confidence = min(0.9, len(reasons) * 0.3 + 0.2) if reasons else 0.0
    return reasons, confidence


def mine_villager_bad_candidates(opp, feats):
    """Identify Villager decisions that look bad."""
    reasons = []

    opp_type = opp.get("opportunity_type", "")
    if opp_type == "vote":
        vcos = feats.get("vote_consistent_with_own_speech", 0.5)
        is_following = feats.get("is_following_majority_without_reason", 0.0)

        if is_following > 0.5 and vcos < 0.5:
            reasons.append("blind_following_without_own_reasoning")

        voted_top = feats.get("vote_consistent_with_public_top_suspicion", 0.5)
        if voted_top < 0.3:
            reasons.append("voting_against_public_consensus_without_justification")

    elif opp_type == "speech":
        grounded = feats.get("grounded_claim_count", 0)
        claims = feats.get("claim_count", 0)
        if grounded == 0 and claims > 1:
            reasons.append("multiple_claims_no_grounding")

    confidence = min(0.9, len(reasons) * 0.3 + 0.2) if reasons else 0.0
    return reasons, confidence


def mine_hunter_bad_candidates(opp, feats):
    """Identify Hunter decisions that look bad."""
    reasons = []

    opp_type = opp.get("opportunity_type", "")
    if opp_type == "hunter_shot":
        target_susp = feats.get("shot_target_suspicion", 0.5)
        if target_susp < 0.4:
            reasons.append("shooting_low_suspicion_target")
        if target_susp < 0.6 and feats.get("hunter_self_suspicion", 0.5) < 0.4:
            reasons.append("random_shot_without_evidence")

        shot_timing = feats.get("shot_timing", 0.5)
        if shot_timing > 0.7 and target_susp < 0.5:
            reasons.append("early_shot_on_low_confidence_target")

    confidence = min(0.9, len(reasons) * 0.3 + 0.2) if reasons else 0.0
    return reasons, confidence


# Miner dispatch
BAD_CANDIDATE_MINERS = {
    "vote": {"Werewolf": mine_werewolf_bad_candidates,
             "Witch": mine_vote_bad_candidates,
             "Seer": mine_vote_bad_candidates,
             "Guard": mine_vote_bad_candidates,
             "Hunter": mine_vote_bad_candidates,
             "Villager": mine_villager_bad_candidates},
    "werewolf_kill": {"Werewolf": mine_werewolf_bad_candidates},
    "witch_poison": {"Witch": mine_witch_bad_candidates},
    "witch_save": {"Witch": mine_witch_bad_candidates},
    "witch_skip": {"Witch": mine_witch_bad_candidates},
    "seer_check": {"Seer": mine_seer_bad_candidates},
    "seer_release": {"Seer": mine_seer_bad_candidates},
    "hunter_shot": {"Hunter": mine_hunter_bad_candidates},
    "speech": {"Villager": mine_villager_bad_candidates,
               "Werewolf": mine_werewolf_bad_candidates},
}


# ============================================================
# V4-2: COUNTERFACTUAL PAIRWISE GENERATION
# ============================================================

def generate_witch_poison_pairwise(opp, feats, opp_index):
    """Generate Witch poison A/B pairs."""
    pairs = []
    evidence = feats.get("public_evidence_against_target", 0.0)
    target_susp = feats.get("target_suspicion_before_action", 0.5)

    # If low evidence + low suspicion: the better action would be skip
    if evidence < 0.3 and target_susp < 0.5:
        pairs.append({
            "action_a": "poison_low_evidence_target",
            "action_b": "skip_poison_or_wait_for_more_info",
            "expected_label": "B_better",
            "rationale": "Low public evidence and low suspicion: better to conserve poison for higher-confidence target",
        })

    return pairs


def generate_witch_save_pairwise(opp, feats, opp_index):
    """Generate Witch save A/B pairs."""
    pairs = []
    role_val = feats.get("save_target_claimed_role_value", 0.3)
    kill_likelihood = feats.get("estimated_kill_likelihood", 0.3)

    if role_val > 0.7 and kill_likelihood > 0.5:
        pairs.append({
            "action_a": "use_antidote_on_key_role",
            "action_b": "save_antidote_for_later",
            "expected_label": "A_better",
            "rationale": f"Target has high claimed role value ({role_val:.2f}) and moderate kill likelihood",
        })

    return pairs


def generate_seer_release_pairwise(opp, feats, opp_index):
    """Generate Seer release A/B pairs."""
    pairs = []
    release_timing = feats.get("release_timing_need", 0.5)

    if release_timing > 0.7:
        pairs.append({
            "action_a": "release_check_result_now",
            "action_b": "hide_check_result_until_later",
            "expected_label": "A_better",
            "rationale": "Release timing is critical: village needs info now",
        })

    return pairs


def generate_villager_vote_pairwise(opp, feats, opp_index):
    """Generate Villager vote A/B pairs."""
    pairs = []
    voted_top = feats.get("vote_consistent_with_public_top_suspicion", 0.5)
    vcos = feats.get("vote_consistent_with_own_speech", 0.5)

    if voted_top < 0.3:
        pairs.append({
            "action_a": "vote_off_consensus_target",
            "action_b": "vote_public_top_suspicion",
            "expected_label": "B_better",
            "rationale": "Voting against public consensus without strong evidence is poor decision-making",
        })

    return pairs


def generate_werewolf_deception_pairwise(opp, feats, opp_index):
    """Generate Werewolf deception A/B pairs."""
    pairs = []
    wolf_alignment = feats.get("wolf_team_vote_alignment", 0.5)
    accuses_good = feats.get("accuses_good_player", 0.0)

    if wolf_alignment > 0.8:
        pairs.append({
            "action_a": "all_wolves_vote_together",
            "action_b": "diversify_wolf_votes_to_avoid_detection",
            "expected_label": "B_better",
            "rationale": "All wolves voting identically makes team detection trivial",
        })

    if accuses_good > 0.5:
        pairs.append({
            "action_a": "accuse_publicly_trusted_player",
            "action_b": "redirect_to_less_trusted_player_or_stay_neutral",
            "expected_label": "B_better",
            "rationale": "Accusing publicly trusted players draws unnecessary attention",
        })

    return pairs


def generate_hunter_shot_pairwise(opp, feats, opp_index):
    """Generate Hunter shot A/B pairs."""
    pairs = []
    target_susp = feats.get("shot_target_suspicion", 0.5)

    if target_susp < 0.5:
        pairs.append({
            "action_a": "shoot_low_suspicion_target",
            "action_b": "restrain_and_not_shoot",
            "expected_label": "B_better",
            "rationale": "Shooting low suspicion target risks hitting good player; restraint preserves village numbers",
        })

    return pairs


# Pairwise generator dispatch
PAIRWISE_GENERATORS = {
    "witch_poison": (generate_witch_poison_pairwise, "Witch"),
    "witch_save": (generate_witch_save_pairwise, "Witch"),
    "seer_release": (generate_seer_release_pairwise, "Seer"),
    "vote": (generate_villager_vote_pairwise, None),  # Any non-Guard role
    "werewolf_kill": (generate_werewolf_deception_pairwise, "Werewolf"),  # Also works for deception
    "hunter_shot": (generate_hunter_shot_pairwise, "Hunter"),
}


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    random.seed(42)
    print("=" * 60)
    print("V4 Label Expansion Pipeline")
    print("=" * 60)

    # Load data
    print("\n[1] Loading data...")
    opportunities = load_jsonl(DATA / "opportunities_v3_features.jsonl")
    opp_orig = load_jsonl(DATA / "opportunities.jsonl")
    opp_orig_index = {o["opportunity_id"]: o for o in opp_orig}
    print(f"  V3 opportunities: {len(opportunities)}")

    # ============================================================
    # PHASE V4-1: Hard Negative Mining
    # ============================================================
    print("\n[2] V4-1: Hard Negative Mining...")
    candidates = []
    candidate_counter = Counter()

    for opp in opportunities:
        role = opp.get("role", "unknown")
        opp_type = opp.get("opportunity_type", "unknown")
        feats = opp.get("v3_pre_features", {})

        # Find miner for this type+role combination
        miners_for_type = BAD_CANDIDATE_MINERS.get(opp_type, {})
        miner = miners_for_type.get(role)
        if miner is None:
            continue

        reasons, confidence = miner(opp, feats)
        if not reasons or confidence < 0.3:
            continue

        gf = opp.get("game_features", {}) or {}
        candidate = {
            "sample_id": f"hn-{opp['opportunity_id']}",
            "game_id": opp["game_id"],
            "role": role,
            "opportunity_type": opp_type,
            "player_id": opp["player_id"],
            "day": gf.get("day", 0),
            "context_summary": f"D{gf.get('day', 0)} {opp_type} by {role}",
            "chosen_action": opp.get("chosen_action_summary", {}),
            "why_candidate_bad": reasons,
            "pre_features_snapshot": {k: round(feats.get(k, 0), 4) for k in sorted(feats.keys())},
            "evidence_event_ids": opp.get("evidence_event_ids", []),
            "candidate_confidence": round(confidence, 3),
            "needs_labeling": True,
        }
        candidates.append(candidate)
        candidate_counter[(role, opp_type)] += 1

    # Write candidates
    with open(DATA / "hard_negative_candidates_v4.jsonl", "w") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"  Total candidates: {len(candidates)}")
    print("  By role-action:")
    for (role, opp_type), count in candidate_counter.most_common():
        print(f"    {role:>10} | {opp_type:<16}: {count}")

    # Mining report
    report_lines = []
    report_lines.append("# Hard Negative Mining Report V4")
    report_lines.append("")
    report_lines.append(f"**Date**: 2026-05-28")
    report_lines.append(f"**Total candidates**: {len(candidates)}")
    report_lines.append("")
    report_lines.append("## By Role-Action")
    report_lines.append("")
    report_lines.append("| Role | Action | Candidates |")
    report_lines.append("|---|---|---|")
    for (role, opp_type), count in candidate_counter.most_common():
        report_lines.append(f"| {role} | {opp_type} | {count} |")
    report_lines.append("")
    report_lines.append("## Candidate Reasons Distribution")
    report_lines.append("")
    reason_counter = Counter()
    for c in candidates:
        for r in c["why_candidate_bad"]:
            reason_counter[r] += 1
    for reason, count in reason_counter.most_common():
        report_lines.append(f"- `{reason}`: {count}")
    report_lines.append("")
    report_lines.append("**IMPORTANT**: These are CANDIDATES for labeling, NOT confirmed bad decisions.")
    report_lines.append("Human or LLM verification is required before using as labels.")
    with open(DATA / "hard_negative_mining_report_v4.md", "w") as f:
        f.write("\n".join(report_lines))
    print("  -> hard_negative_mining_report_v4.md")

    # ============================================================
    # PHASE V4-2: Counterfactual Pairwise Generation
    # ============================================================
    print("\n[3] V4-2: Counterfactual Pairwise Generation...")
    pairwise = []
    pairwise_counter = Counter()

    for opp in opportunities:
        opp_type = opp.get("opportunity_type", "")
        role = opp.get("role", "unknown")
        feats = opp.get("v3_pre_features", {})

        gen_entry = PAIRWISE_GENERATORS.get(opp_type)
        if gen_entry is None:
            continue
        generator, required_role = gen_entry
        if required_role and role != required_role:
            continue

        pairs = generator(opp, feats, opp_orig_index)
        for p in pairs:
            gf = opp.get("game_features", {}) or {}
            sample = {
                "sample_id": f"pw-{opp['opportunity_id']}-{len(pairwise)}",
                "game_id": opp["game_id"],
                "role": role,
                "opportunity_type": opp_type,
                "context": f"D{gf.get('day', 0)} {opp_type} by {role}",
                "action_a": p["action_a"],
                "action_b": p["action_b"],
                "expected_label": p["expected_label"],
                "label_source": "counterfactual_or_rule",
                "confidence": 0.7,
                "rationale": p["rationale"],
                "evidence_event_ids": opp.get("evidence_event_ids", []),
                "synthetic": True,
            }
            pairwise.append(sample)
            pairwise_counter[(role, opp_type)] += 1

    with open(DATA / "pairwise_candidates_v4.jsonl", "w") as f:
        for p in pairwise:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"  Total pairwise samples: {len(pairwise)}")
    print("  By role-action:")
    for (role, opp_type), count in pairwise_counter.most_common():
        print(f"    {role:>10} | {opp_type:<16}: {count}")

    # Pairwise report
    pw_lines = []
    pw_lines.append("# Counterfactual Pairwise Generation Report V4")
    pw_lines.append("")
    pw_lines.append(f"**Date**: 2026-05-28")
    pw_lines.append(f"**Total pairwise samples**: {len(pairwise)}")
    pw_lines.append("")
    pw_lines.append("## By Role-Action")
    pw_lines.append("")
    pw_lines.append("| Role | Action | Pairs |")
    pw_lines.append("|---|---|---|")
    for (role, opp_type), count in pairwise_counter.most_common():
        pw_lines.append(f"| {role} | {opp_type} | {count} |")
    pw_lines.append("")
    pw_lines.append("## Rationale Distribution")
    pw_lines.append("")
    rationale_counter = Counter(p["rationale"] for p in pairwise)
    for rationale, count in rationale_counter.most_common(10):
        pw_lines.append(f"- {rationale}: {count}")
    pw_lines.append("")
    pw_lines.append("**IMPORTANT**: Labels are rule-based, NOT from final game outcome.")
    pw_lines.append("Pairwise samples should be verified before use in model training.")
    with open(DATA / "pairwise_generation_report_v4.md", "w") as f:
        f.write("\n".join(pw_lines))
    print("  -> pairwise_generation_report_v4.md")

    print(f"\n{'='*60}")
    print(f"V4-1: {len(candidates)} hard negative candidates")
    print(f"V4-2: {len(pairwise)} pairwise samples")
    print(f"Total new labeling candidates: {len(candidates) + len(pairwise)}")
    print(f"{'='*60}")
    print("Done.")


if __name__ == "__main__":
    main()
